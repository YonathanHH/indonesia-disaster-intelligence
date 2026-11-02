from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.api import jobs as jobs_module
from app.main import app
from app.services import brief_store, ingest, job_state


def _client():
    return TestClient(app, raise_server_exceptions=False)


def test_nightly_ingest_requires_secret(monkeypatch):
    monkeypatch.setattr("app.core.config.settings.cron_secret", "s3cret-value-1234")
    c = _client()
    assert c.get("/api/v1/jobs/nightly-ingest").status_code == 401
    assert c.get("/api/v1/jobs/nightly-ingest", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert c.get("/api/v1/jobs/nightly-ingest", headers={"Authorization": "s3cret-value-1234"}).status_code == 401


def test_jobs_fail_closed_when_secret_unset(monkeypatch):
    # A forgotten env var must not become an open write path on a public domain.
    monkeypatch.setattr("app.core.config.settings.cron_secret", "")
    c = _client()
    assert c.get("/api/v1/jobs/nightly-ingest").status_code == 401


def test_cron_endpoints_are_get_only(monkeypatch):
    # Vercel cron issues GET; POST must not be the verb that works.
    monkeypatch.setattr("app.core.config.settings.cron_secret", "x")
    c = _client()
    assert c.post("/api/v1/jobs/nightly-ingest").status_code == 405


def test_resolve_requires_operator_secret(monkeypatch):
    monkeypatch.setattr("app.core.config.settings.operator_secret", "op-secret")
    c = _client()
    assert c.post("/api/v1/events/does-not-exist/resolve").status_code == 401


@pytest.fixture
def stubbed(monkeypatch):
    """Replace every upstream caller with a counter so a test can assert what ran."""
    calls = {"ingest": 0, "brief": 0}

    async def fake_run_ingest(session):
        calls["ingest"] += 1
        return {"quakes": 0, "weather": 0, "errors": []}

    async def fake_build_and_store(session, kind):
        calls["brief"] += 1

        class _R:
            generated_at = datetime.now(timezone.utc)
            kind = "stub"
            llm_status = "ok"

        return _R()

    monkeypatch.setattr(ingest, "run_ingest", fake_run_ingest)
    monkeypatch.setattr(brief_store, "build_and_store", fake_build_and_store)
    return calls


async def test_nightly_ingest_ignores_the_interval_claim(session, stubbed):
    # A user-triggered fetch seconds ago must not cause the scheduled run to skip
    # BMKG — a forced claim stamps the row instead of checking it.
    await job_state.try_claim(session, "ingest", 300)
    await session.commit()
    out = await jobs_module.nightly_ingest(session=session)
    assert stubbed["ingest"] == 1
    assert out["forced"] is True


async def test_nightly_brief_reingests_when_data_is_stale(session, stubbed):
    await job_state.mark_done(session, "ingest")
    await session.execute(
        job_state.JobState.__table__.update()
        .where(job_state.JobState.key == "ingest")
        .values(last_ok_at=datetime.now(timezone.utc) - timedelta(hours=13))
    )
    await session.commit()
    out = await jobs_module.nightly_brief(session=session)
    assert stubbed["ingest"] == 1 and stubbed["brief"] == 1
    assert out["reconciled_ingest"] is True


async def test_nightly_brief_skips_ingest_when_fresh(session, stubbed):
    await job_state.mark_done(session, "ingest")
    await session.commit()
    out = await jobs_module.nightly_brief(session=session)
    assert stubbed["ingest"] == 0 and stubbed["brief"] == 1
    assert out["reconciled_ingest"] is False


async def test_partial_collector_failure_leaves_last_ok_unchanged(session, monkeypatch):
    # A run that fetched nothing must not be recorded as a success, or /status and
    # the brief guard will treat broken data as fresh.
    from app.models import JobState

    async def failing_ingest(_session):
        return {"quakes": 0, "weather": 0, "errors": ["bmkg_quake: timeout"]}

    monkeypatch.setattr(ingest, "run_ingest", failing_ingest)
    await jobs_module.run_ingest_cycle(session, force=True)
    row = await session.get(JobState, "ingest")
    assert row.last_ok_at is None
    assert "bmkg_quake: timeout" in row.last_error
