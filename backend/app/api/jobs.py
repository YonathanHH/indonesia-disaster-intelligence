"""Scheduled job endpoints, invoked by Vercel Cron over HTTP GET.

Crons are best-effort, never retried, and can be delivered twice or overlap, so
both jobs are idempotent and reconciliation-based (spec §10). GET is not a
mistake: a POST-only job endpoint returns 405 to every scheduled run and looks
like a healthy deploy that never ingests anything.
"""
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_session
from app.services import brief_store
from app.services import ingest as ingest_svc
from app.services import job_state

log = logging.getLogger(__name__)
router = APIRouter()

# Older than this, the nightly brief re-ingests before writing a digest.
STALE_INGEST_AFTER_HOURS = 12


def _bearer(authorization: str | None, secret: str, label: str) -> None:
    if not secret or authorization != f"Bearer {secret}":
        raise HTTPException(401, f"invalid {label}")


def require_cron(authorization: str | None = Header(None)) -> None:
    _bearer(authorization, settings.cron_secret, "cron secret")


def require_operator(authorization: str | None = Header(None)) -> None:
    _bearer(authorization, settings.operator_secret, "operator secret")


async def run_ingest_cycle(session, *, force: bool) -> dict:
    """Claim-protected ingest. `force` is for scheduled runs: they always work,
    and stamping the claim is what stops concurrent on-load requests from
    duplicating the same BMKG fetch."""
    claimed = await job_state.try_claim(
        session, job_state.KEY_INGEST, settings.ingest_interval_seconds, force=force
    )
    if not claimed:
        return {"skipped": "recent_ingest", "quakes": 0, "weather": 0, "errors": []}
    try:
        summary = await ingest_svc.run_ingest(session)
        errors = summary.get("errors") or []
        await job_state.mark_done(
            session, job_state.KEY_INGEST, error=("; ".join(errors)[:500]) if errors else None
        )
        await session.commit()
    except Exception as e:  # never lose the error into a 200 with no trace
        log.exception("ingest cycle failed")
        await session.rollback()
        await job_state.mark_done(session, job_state.KEY_INGEST, error=str(e))
        await session.commit()
        raise
    summary["forced"] = force
    return summary


async def ensure_fresh_ingest(session) -> bool:
    """Reconciliation: cron delivery is best-effort, so a missed ingest run must
    be caught up by the job that depends on its data. Returns True if it ran."""
    last = await job_state.last_ok(session, job_state.KEY_INGEST)
    if last is not None and datetime.now(timezone.utc) - last < timedelta(
        hours=STALE_INGEST_AFTER_HOURS
    ):
        return False
    await run_ingest_cycle(session, force=True)
    return True


async def maybe_rebuild_brief(session) -> bool:
    """Rebuild the rolling brief when it no longer reflects the newest data.

    Three conditions, and all must hold (spec §6): the stored brief predates the
    newest successful ingest, the floor interval has passed, and this instance
    wins the `brief` claim. That is what turns five dashboard loads in a minute
    into one LLM call.
    """
    latest = await brief_store.newest(session)
    ingest_at = await job_state.last_ok(session, job_state.KEY_INGEST)
    now = datetime.now(timezone.utc)
    if not brief_store.rebuild_needed(
        latest, ingest_at, floor_seconds=settings.brief_min_rebuild_seconds, now=now
    ):
        return False
    if not await job_state.try_claim(
        session, job_state.KEY_BRIEF, settings.brief_min_rebuild_seconds
    ):
        return False
    await brief_store.build_and_store(session, kind="live")
    await job_state.mark_done(session, job_state.KEY_BRIEF)
    return True


@router.get("/jobs/nightly-ingest", dependencies=[Depends(require_cron)])
async def nightly_ingest(session: AsyncSession = Depends(get_session)):
    """00:00 WIB. Collectors only — the 01:00 brief job owns the digest, so this
    run does not spend an LLM call at midnight."""
    return await run_ingest_cycle(session, force=True)


@router.get("/jobs/nightly-brief", dependencies=[Depends(require_cron)])
async def nightly_brief(session: AsyncSession = Depends(get_session)):
    """01:00 WIB. Guarantees a dated executive brief exists even if nobody opens
    the dashboard. Re-ingests first if the last success is >12h old."""
    reconciled = await ensure_fresh_ingest(session)
    row = await brief_store.build_and_store(session, kind="daily")
    log.info("nightly brief stored: %s (kind=daily, llm_status=%s)", row.generated_at, row.llm_status)
    return {
        "brief_generated_at": row.generated_at.isoformat(),
        "llm_status": row.llm_status,
        "reconciled_ingest": reconciled,
    }
