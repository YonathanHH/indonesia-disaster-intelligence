from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy import select

from app.core.config import settings
from app.models import Briefing, JobState
from app.services import brief_store, job_state


async def test_new_tables_exist(session):
    session.add(JobState(key="ingest"))
    session.add(
        Briefing(
            kind="daily",
            generated_at=datetime.now(timezone.utc),
            based_on_ingest_at=None,
            payload={"headline": "x"},
            llm_status="ok",
            llm_model="openrouter/free",
            created_at=datetime.now(timezone.utc),
        )
    )
    await session.commit()
    row = (await session.execute(select(Briefing))).scalar_one()
    assert row.payload == {"headline": "x"}
    assert row.kind == "daily"


def test_new_settings_defaults():
    assert settings.brief_min_rebuild_seconds == 900
    assert settings.cron_secret == ""
    assert settings.allowed_origins == ""
    assert settings.operator_secret == ""
    assert settings.cors_origins == []


T0 = datetime(2026, 11, 2, 18, 0, tzinfo=timezone.utc)


def _brief(age_min=0, based_on=T0):
    # rebuild_needed is pure: it reads two columns, so a stand-in is enough and
    # keeps these cases free of database state.
    return SimpleNamespace(
        generated_at=T0 - timedelta(minutes=age_min),
        based_on_ingest_at=based_on,
    )


def test_no_brief_needs_rebuild():
    assert brief_store.rebuild_needed(None, T0, floor_seconds=900, now=T0) is True


def test_current_brief_needs_no_rebuild():
    assert brief_store.rebuild_needed(_brief(), T0, floor_seconds=900, now=T0) is False


def test_stale_brief_needs_rebuild():
    b = _brief(based_on=T0 - timedelta(hours=1))
    assert brief_store.rebuild_needed(b, T0, floor_seconds=900, now=T0 + timedelta(hours=2)) is True


def test_floor_blocks_even_when_stale():
    # Five dashboard loads in one minute must not mean five LLM calls.
    b = _brief(based_on=T0 - timedelta(hours=1))
    assert brief_store.rebuild_needed(b, T0, floor_seconds=900, now=T0 + timedelta(minutes=10)) is False


def test_brief_with_no_ingest_reference_always_looks_stale():
    b = _brief(age_min=120, based_on=None)
    assert brief_store.rebuild_needed(b, T0, floor_seconds=900, now=T0 + timedelta(hours=1)) is True


def test_no_ingest_recorded_means_nothing_to_reflect():
    assert brief_store.rebuild_needed(_brief(), None, floor_seconds=900, now=T0) is False


async def test_store_then_read_newest(session):
    now = datetime.now(timezone.utc)
    await brief_store.store(
        session, {"headline": "old", "generated_at": now.isoformat()},
        kind="daily", based_on_ingest_at=None, llm_status="ok", llm_model="m",
    )
    await brief_store.store(
        session, {"headline": "new", "generated_at": now.isoformat()},
        kind="live", based_on_ingest_at=now, llm_status=None, llm_model=None,
    )
    doc = await brief_store.current_document(session)
    assert doc["headline"] == "new" and doc["kind"] == "live"
    daily = await brief_store.newest(session, kind="daily")
    assert daily.payload["headline"] == "old"


async def test_store_prunes_old_rows(session):
    old = Briefing(
        kind="daily",
        generated_at=datetime.now(timezone.utc) - timedelta(days=31),
        based_on_ingest_at=None,
        payload={"headline": "ancient"},
        created_at=datetime.now(timezone.utc),
    )
    session.add(old)
    await session.commit()
    await brief_store.store(
        session, {"headline": "fresh"}, kind="live",
        based_on_ingest_at=None, llm_status=None, llm_model=None,
    )
    remaining = (await session.execute(select(Briefing))).scalars().all()
    assert [b.payload["headline"] for b in remaining] == ["fresh"]


async def test_build_and_store_uses_ingest_time_as_reference(session):
    # build_briefing does live upstream calls; stub it, as the API tests already do
    # for collectors elsewhere in the suite.
    async def fake_build(_session):
        return {"headline": "h", "generated_at": "x", "llm_status": "ok", "llm_model": "openrouter/free"}

    orig = brief_store.briefing_svc.build_briefing
    brief_store.briefing_svc.build_briefing = fake_build
    try:
        await job_state.try_claim(session, job_state.KEY_INGEST, 300)
        await job_state.mark_done(session, job_state.KEY_INGEST)
        await session.commit()
        row = await brief_store.build_and_store(session, "daily")
        assert row.kind == "daily" and row.llm_status == "ok"
        assert row.based_on_ingest_at == await job_state.last_ok(session, job_state.KEY_INGEST)
    finally:
        brief_store.briefing_svc.build_briefing = orig
