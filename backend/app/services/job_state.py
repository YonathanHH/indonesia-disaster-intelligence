"""Atomic cross-instance claims for scheduled work.

Serverless gives us many instances, no shared memory, and Vercel cron that can
overlap or deliver the same run twice. So the lock is one conditional UPDATE:
whoever moves `claimed_at` owns the work, everybody else does nothing.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError

from app.models import JobState

KEY_INGEST = "ingest"
KEY_BRIEF = "brief"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def _ensure_row(session, key: str) -> None:
    """Create the claim row if absent. Savepoint keeps a duplicate-key insert
    from poisoning the caller's transaction on both SQLite and Postgres."""
    try:
        async with session.begin_nested():
            session.add(JobState(key=key))
    except IntegrityError:
        pass


async def try_claim(session, key: str, min_interval_seconds: int, *, force: bool = False) -> bool:
    """Take ownership of `key`. False means someone else is already working.

    `force=True` skips the interval check — for scheduled runs that must not be
    skipped by an earlier user-triggered fetch — but still stamps `claimed_at`.
    """
    now = _utcnow()
    await _ensure_row(session, key)
    stmt = update(JobState).where(JobState.key == key)
    if not force:
        cutoff = now - timedelta(seconds=min_interval_seconds)
        stmt = stmt.where(or_(JobState.claimed_at.is_(None), JobState.claimed_at < cutoff))
    res = await session.execute(stmt.values(claimed_at=now))
    return res.rowcount == 1


async def mark_done(session, key: str, *, error: str | None = None) -> None:
    await _ensure_row(session, key)
    if error:
        await session.execute(
            update(JobState).where(JobState.key == key).values(last_error=error[:500])
        )
    else:
        await session.execute(
            update(JobState)
            .where(JobState.key == key)
            .values(last_ok_at=_utcnow(), last_error=None)
        )


async def last_ok(session, key: str) -> datetime | None:
    row = (
        await session.execute(select(JobState).where(JobState.key == key))
    ).scalar_one_or_none()
    return _aware(row.last_ok_at) if row else None
