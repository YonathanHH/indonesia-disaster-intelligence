from datetime import datetime, timezone

import pytest

from app.api import jobs
from app.services import brief_store, ingest, job_state


@pytest.fixture
def stubbed(monkeypatch):
    """Count upstream work, but keep the real brief table so the rebuild guard has
    something to read back."""
    calls = {"ingest": 0, "brief": 0}

    async def fake_run_ingest(session):
        calls["ingest"] += 1
        return {"quakes": 1, "weather": 0, "errors": []}

    async def fake_build_and_store(session, kind):
        calls["brief"] += 1
        return await brief_store.store(
            session, {"headline": "stub", "generated_at": datetime.now(timezone.utc).isoformat()},
            kind=kind,
            based_on_ingest_at=await job_state.last_ok(session, job_state.KEY_INGEST),
            llm_status="ok", llm_model="openrouter/free",
        )

    monkeypatch.setattr(ingest, "run_ingest", fake_run_ingest)
    monkeypatch.setattr(brief_store, "build_and_store", fake_build_and_store)
    return calls


async def test_second_ingest_request_does_no_work(session, stubbed):
    a = await jobs.run_ingest_cycle(session, force=False)
    b = await jobs.run_ingest_cycle(session, force=False)
    assert stubbed["ingest"] == 1
    assert "skipped" in b and a["quakes"] == 1


async def test_five_loads_cost_one_brief_build(session, stubbed, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.brief_min_rebuild_seconds", 900)
    for _ in range(5):
        await jobs.run_ingest_cycle(session, force=False)
        await jobs.maybe_rebuild_brief(session)
    assert stubbed["ingest"] == 1
    assert stubbed["brief"] == 1


async def test_brief_rebuilt_once_after_a_real_ingest(session, stubbed, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.brief_min_rebuild_seconds", 0)
    await jobs.run_ingest_cycle(session, force=True)
    assert await jobs.maybe_rebuild_brief(session) is True
    assert stubbed["brief"] == 1
    assert await jobs.maybe_rebuild_brief(session) is False  # the stored brief is now current
    assert stubbed["brief"] == 1


async def test_briefing_read_returns_stored_document(session, stubbed):
    await brief_store.store(
        session, {"headline": "stored"}, kind="daily",
        based_on_ingest_at=None, llm_status="ok", llm_model="openrouter/free",
    )
    doc = await brief_store.current_document(session)
    assert doc == {"headline": "stored", "kind": "daily"}
    assert stubbed["ingest"] == 0  # reading a brief must never trigger work


def _full_payload() -> dict:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "generated_at": now, "headline": "stored headline", "overview": [],
        "watchlist": [], "recommended_actions": [],
        "developments": {"generated_at": now, "since": now, "new_events": [],
                         "escalated": [], "de_escalated": [], "resolved": [],
                         "expired": [], "growing_sequences": [], "counts": {}},
        "sequences": [], "situations": [],
        "escalation": {"level": "NORMAL", "method": "rules", "generated_at": now,
                       "triggers": [], "posture": "routine monitoring"},
        "llm_summary": None, "llm_model": None, "llm_status": "off", "caveats": [],
    }


async def test_briefing_endpoint_reads_storage_without_computing(session, monkeypatch):
    # The whole point of the store: an open drawer must not run collectors or the LLM.
    # httpx+ASGITransport, not TestClient: the latter runs the app in a second event
    # loop, which strands the fixture's aiosqlite connection.
    import httpx

    from app.core.db import get_session
    from app.main import app

    await brief_store.store(
        session, _full_payload(), kind="daily", based_on_ingest_at=None,
        llm_status="off", llm_model=None,
    )

    async def override():
        yield session

    def explode(*a, **k):
        raise AssertionError("read path must not recompute the brief")

    app.dependency_overrides[get_session] = override
    monkeypatch.setattr("app.services.briefing.build_briefing", explode)
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            r = await ac.get("/api/v1/briefing")
            assert r.status_code == 200, r.text
            assert r.json()["headline"] == "stored headline"
            assert r.json()["kind"] == "daily"

            s = await ac.get("/api/v1/status")
            assert s.status_code == 200, s.text
            assert s.json()["last_brief_at"] is not None
            assert s.json()["last_brief_llm_status"] == "off"
    finally:
        app.dependency_overrides.clear()
