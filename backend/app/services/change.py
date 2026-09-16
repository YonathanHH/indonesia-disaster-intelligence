"""Situation change detection — "What Changed?" (deterministic, stateless).

Compares the current situation against a lookback window using the
append-only EventHistory log plus event timestamps. No snapshot tables:
the history log IS the previous-state record, and `since` is caller-supplied
(default 24h), so any consumer (briefing, /changes, future digests) shares
one code path.

Change kinds:
  - new: Event.created_at >= since
  - escalated / de_escalated: EventHistory kind "rescore" with band change
    (written by ingest felt-merge going forward; older data has none — by
    design, we never invent history)
  - resolved: EventHistory kind "resolved" in window
  - expired: severe_weather still active with expires_at < now (current-state
    warning, not windowed — expiry is a fact about now)
  - growing_sequences: cluster whose latest member arrived in window

Each item carries enough to render without extra queries:
{event_id, title, type, priority, score, occurred_at, detail}.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models import Event, EventHistory
from app.services import clustering

BAND_RANK = {"LOW": 0, "MODERATE": 1, "HIGH": 2, "CRITICAL": 3}


def _aware(dt: datetime) -> datetime:
    return dt if dt is not None and dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _item(e: Event, detail: str = "") -> dict:
    return {
        "event_id": e.id,
        "title": e.title,
        "type": e.type,
        "priority": e.priority,
        "score": e.score,
        "occurred_at": _aware(e.occurred_at).isoformat(),
        "detail": detail,
    }


def _band_of(priority: str) -> int:
    return BAND_RANK.get(str(priority or "").upper(), 0)


async def compute_changes(session, since: datetime | None = None,
                          window_hours: float = 24.0) -> dict:
    """Compute situation changes vs the lookback window."""
    now = datetime.now(timezone.utc)
    since = _aware(since) if since is not None else now - timedelta(hours=window_hours)

    events: list[Event] = (await session.execute(select(Event))).scalars().all()
    by_id = {e.id: e for e in events}

    hist: list[EventHistory] = (await session.execute(
        select(EventHistory).where(EventHistory.ts >= since).order_by(EventHistory.ts)
    )).scalars().all()

    new_events = [_item(e, "first seen in window") for e in events
                  if _aware(e.created_at) >= since]
    new_events.sort(key=lambda d: d["occurred_at"], reverse=True)

    escalated, de_escalated, resolved = [], [], []
    for h in hist:
        e = by_id.get(h.event_id)
        if h.kind == "rescore" and isinstance(h.payload, dict):
            before = _band_of((h.payload.get("before") or {}).get("priority", ""))
            after = _band_of((h.payload.get("after") or {}).get("priority", ""))
            if after > before and e is not None:
                escalated.append(_item(e, h.payload.get("reason", "re-scored higher") or ""))
            elif after < before and e is not None:
                de_escalated.append(_item(e, h.payload.get("reason", "re-scored lower") or ""))
        elif h.kind == "resolved" and e is not None:
            resolved.append(_item(e, h.message or "marked resolved"))

    expired = [_item(e, f"alert expired {_aware(e.expires_at).isoformat()}")
               for e in events
               if e.type == "severe_weather" and e.status == "active"
               and e.expires_at is not None and _aware(e.expires_at) < now]
    expired.sort(key=lambda d: d["occurred_at"], reverse=True)

    active = [e for e in events if e.status == "active"]
    sequences = clustering.find_sequences(active)
    growing = []
    for c in sequences:
        latest = c["latest_at"]
        try:
            if _aware(latest) >= since:
                growing.append({
                    "cluster_id": c["cluster_id"],
                    "member_count": c["member_count"],
                    "mainshock_magnitude": c["mainshock_magnitude"],
                    "mainshock_title": c["mainshock_title"],
                    "mainshock_id": c["mainshock_id"],
                    "latest_at": _aware(latest).isoformat(),
                })
        except TypeError:
            continue

    return {
        "generated_at": now.isoformat(),
        "since": since.isoformat(),
        "new_events": new_events,
        "escalated": escalated,
        "de_escalated": de_escalated,
        "resolved": resolved,
        "expired": expired,
        "growing_sequences": growing,
        "counts": {
            "new": len(new_events),
            "escalated": len(escalated),
            "de_escalated": len(de_escalated),
            "resolved": len(resolved),
            "expired": len(expired),
            "growing_sequences": len(growing),
        },
    }
