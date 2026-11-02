"""Analytics aggregations over the primary store.

Formerly mirrored every event into a local DuckDB file. That bought nothing —
the six aggregations are native SQL, and the file needs a writable disk, which
serverless does not give us. `top_regions` still reads `extra` in Python
because portable JSON-path SQL differs between SQLite and Postgres and the row
count is small by design (BMKG feeds, not a history warehouse).
"""
from collections import Counter
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.models import Event, Observation

QUAKE_TYPES = ("earthquake", "tsunami_alert")


async def get_analytics(session, refresh: bool = True) -> dict:
    now = datetime.now(timezone.utc)
    day_ago, week_ago, fortnight_ago = (
        now - timedelta(hours=24),
        now - timedelta(days=7),
        now - timedelta(days=14),
    )

    async def scalar(stmt) -> int:
        return (await session.execute(stmt)).scalar() or 0

    total = await scalar(select(func.count()).select_from(Event))
    by_type = {
        t: c
        for t, c in (
            await session.execute(select(Event.type, func.count()).group_by(Event.type))
        ).all()
    }
    by_priority = {
        p: c
        for p, c in (
            await session.execute(select(Event.priority, func.count()).group_by(Event.priority))
        ).all()
    }
    quakes_24h = await scalar(
        select(func.count())
        .select_from(Event)
        .where(Event.type.in_(QUAKE_TYPES), Event.occurred_at >= day_ago)
    )
    avg_raw = (
        await session.execute(
            select(func.avg(Event.magnitude)).where(
                Event.magnitude.is_not(None), Event.occurred_at >= week_ago
            )
        )
    ).scalar()
    daily = [
        {"day": str(d), "count": c}
        for d, c in (
            await session.execute(
                select(func.date(Event.occurred_at), func.count())
                .where(Event.occurred_at >= fortnight_ago)
                .group_by(func.date(Event.occurred_at))
                .order_by(func.date(Event.occurred_at))
            )
        ).all()
    ]
    extra_rows = (await session.execute(select(Event.extra))).scalars().all()
    top = Counter((r or {}).get("region") or "Unknown" for r in extra_rows).most_common(10)
    observations = await scalar(select(func.count()).select_from(Observation)) if refresh else 0

    return {
        "generated_at": now.isoformat(),
        "total_events": total,
        "by_type": by_type,
        "by_priority": by_priority,
        "quakes_24h": quakes_24h,
        "avg_magnitude_7d": float(avg_raw) if avg_raw is not None else None,
        "top_regions": [{"region": r, "count": c} for r, c in top],
        "daily_counts_14d": daily,
        "observations": observations,
    }
