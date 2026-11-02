from datetime import datetime, timedelta, timezone

from app.models import JobState
from app.services import job_state


async def test_first_claim_wins_second_loses(session):
    assert await job_state.try_claim(session, "ingest", 300) is True
    await session.commit()
    assert await job_state.try_claim(session, "ingest", 300) is False


async def test_claim_expires_after_interval(session):
    assert await job_state.try_claim(session, "ingest", 300) is True
    await session.execute(
        JobState.__table__.update()
        .where(JobState.key == "ingest")
        .values(claimed_at=datetime.now(timezone.utc) - timedelta(seconds=301))
    )
    assert await job_state.try_claim(session, "ingest", 300) is True


async def test_force_writes_without_checking_and_blocks_others(session):
    # A scheduled run must never be skipped, but stamping the claim still stops
    # concurrent on-load requests from duplicating the same BMKG fetch.
    assert await job_state.try_claim(session, "ingest", 300, force=True) is True
    assert await job_state.try_claim(session, "ingest", 300) is False


async def test_mark_done_sets_last_ok_and_last_error(session):
    await job_state.try_claim(session, "ingest", 300)
    await job_state.mark_done(session, "ingest")
    await session.commit()
    ok = await job_state.last_ok(session, "ingest")
    assert ok is not None and ok.tzinfo is not None

    await job_state.mark_done(session, "brief", error="openrouter timeout")
    await session.commit()
    row = await session.get(JobState, "brief")
    assert row.last_error == "openrouter timeout"
    assert row.last_ok_at is None


async def test_last_ok_missing_row_returns_none(session):
    assert await job_state.last_ok(session, "nope") is None
