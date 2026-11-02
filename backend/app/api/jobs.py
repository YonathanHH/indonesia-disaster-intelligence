"""Scheduled job endpoints, invoked by Vercel Cron over HTTP GET.

Crons are best-effort, never retried, and can be delivered twice or overlap, so
both jobs are idempotent and reconciliation-based (spec §10). GET is not a
mistake: a POST-only job endpoint returns 405 to every scheduled run and looks
like a healthy deploy that never ingests anything.
"""
import logging

from fastapi import APIRouter, Depends, Header, HTTPException

from app.core.config import settings

log = logging.getLogger(__name__)
router = APIRouter()


def _bearer(authorization: str | None, secret: str, label: str) -> None:
    if not secret or authorization != f"Bearer {secret}":
        raise HTTPException(401, f"invalid {label}")


def require_cron(authorization: str | None = Header(None)) -> None:
    _bearer(authorization, settings.cron_secret, "cron secret")


def require_operator(authorization: str | None = Header(None)) -> None:
    _bearer(authorization, settings.operator_secret, "operator secret")


@router.get("/jobs/nightly-ingest", dependencies=[Depends(require_cron)])
async def nightly_ingest():
    raise NotImplementedError  # filled in by Task 7


@router.get("/jobs/nightly-brief", dependencies=[Depends(require_cron)])
async def nightly_brief():
    raise NotImplementedError  # filled in by Task 7
