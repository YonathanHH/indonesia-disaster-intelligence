"""Persistence + rebuild policy for the executive brief.

Two-layer design carried over from services/briefing.py: the deterministic core
is a function of stored data, and the LLM note is an optional gloss. This module
decides *when* to rebuild and *where* the document lives; briefing.py still
decides what the document says.
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, desc, select

from app.models import Briefing
from app.services import briefing as briefing_svc
from app.services import job_state

log = logging.getLogger(__name__)

MAX_AGE_DAYS = 30


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def newest(session, *, kind: str | None = None) -> Briefing | None:
    stmt = select(Briefing)
    if kind:
        stmt = stmt.where(Briefing.kind == kind)
    stmt = stmt.order_by(desc(Briefing.generated_at)).limit(1)
    return (await session.execute(stmt)).scalar_one_or_none()


def rebuild_needed(
    latest: Briefing | None,
    ingest_ok_at: datetime | None,
    *,
    floor_seconds: int,
    now: datetime,
) -> bool:
    """Should we spend an LLM call on a fresher brief?

    The three-way rule from the spec: a brief is current when it already reflects
    the newest successful ingest, and it is rate-limited by `floor_seconds` even
    when it is stale.
    """
    if latest is None:
        return True                      # nothing stored yet
    if ingest_ok_at is None:
        return False                     # nothing new to reflect
    gen = _aware(latest.generated_at)
    if now - gen < timedelta(seconds=floor_seconds):
        return False
    based = _aware(latest.based_on_ingest_at)
    if based is None:
        return True                      # cannot prove freshness
    return based < _aware(ingest_ok_at)


async def store(
    session,
    payload: dict,
    *,
    kind: str,
    based_on_ingest_at: datetime | None,
    llm_status: str | None,
    llm_model: str | None,
) -> Briefing:
    now = datetime.now(timezone.utc)
    row = Briefing(
        kind=kind,
        generated_at=now,
        based_on_ingest_at=based_on_ingest_at,
        payload=payload,
        llm_status=llm_status,
        llm_model=llm_model,
        created_at=now,
    )
    session.add(row)
    # Bounds a row-per-rebuild table without a second scheduled job.
    await session.execute(
        delete(Briefing).where(Briefing.generated_at < now - timedelta(days=MAX_AGE_DAYS))
    )
    await session.commit()
    return row


async def build_and_store(session, kind: str) -> Briefing:
    payload = await briefing_svc.build_briefing(session)
    return await store(
        session,
        payload,
        kind=kind,
        based_on_ingest_at=await job_state.last_ok(session, job_state.KEY_INGEST),
        llm_status=payload.get("llm_status"),
        llm_model=payload.get("llm_model"),
    )


async def current_document(session) -> dict | None:
    row = await newest(session)
    if row is None:
        return None
    return {**row.payload, "kind": row.kind}
