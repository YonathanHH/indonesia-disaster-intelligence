"""DuckDB sidecar analytics (OLAP mirror).

Primary store stays Postgres (prod) / SQLite (local dev) — the system of
record for ingest + API. This module mirrors `events` (+ minimal
`observations` counts) into a local DuckDB file on demand and runs
analytical aggregations there (GROUP BY type/priority/day, averages).

Usage: GET /api/v1/analytics[?refresh=true] -> refresh snapshot then query.
The DuckDB file is a disposable cache: delete it any time, it rebuilds.
"""
import asyncio
import logging
from collections import Counter
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.config import settings
from app.models import Event, Observation

log = logging.getLogger(__name__)


def _aware(dt: datetime) -> datetime:
    return dt if dt is not None and dt.tzinfo else (dt.replace(tzinfo=timezone.utc) if dt else dt)


def _event_rows(events: list[Event]) -> list[tuple]:
    rows = []
    for e in events:
        rows.append((
            e.id, e.type, e.title, _aware(e.occurred_at), e.latitude, e.longitude,
            e.depth_km, e.magnitude, e.priority, float(e.score or 0.0), e.status,
            _aware(e.created_at) if e.created_at else None,
        ))
    return rows


def _run_snapshot_and_query(event_rows: list[tuple], obs_count: int, duckdb_path: str) -> dict:
    import duckdb

    now = datetime.now(timezone.utc)
    day_ago = now - timedelta(hours=24)
    week_ago = now - timedelta(days=7)
    fortnight_ago = now - timedelta(days=14)

    con = duckdb.connect(duckdb_path)
    try:
        con.execute("""
            CREATE OR REPLACE TABLE events (
                id VARCHAR, type VARCHAR, title VARCHAR,
                occurred_at TIMESTAMPTZ, latitude DOUBLE, longitude DOUBLE,
                depth_km DOUBLE, magnitude DOUBLE,
                priority VARCHAR, score DOUBLE, status VARCHAR,
                created_at TIMESTAMPTZ
            )
        """)
        con.execute("DELETE FROM events")
        if event_rows:
            con.executemany("INSERT INTO events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", event_rows)

        total = con.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        by_type = dict(con.execute("SELECT type, COUNT(*) FROM events GROUP BY type").fetchall())
        by_priority = dict(con.execute("SELECT priority, COUNT(*) FROM events GROUP BY priority").fetchall())
        quakes_24h = con.execute(
            "SELECT COUNT(*) FROM events WHERE type IN ('earthquake','tsunami_alert') AND occurred_at >= ?",
            [day_ago],
        ).fetchone()[0]
        avg_mag = con.execute(
            "SELECT AVG(magnitude) FROM events WHERE magnitude IS NOT NULL AND occurred_at >= ?",
            [week_ago],
        ).fetchone()[0]
        daily = con.execute(
            """SELECT CAST(occurred_at AS DATE) AS day, COUNT(*)
               FROM events WHERE occurred_at >= ? GROUP BY 1 ORDER BY 1""",
            [fortnight_ago],
        ).fetchall()
    finally:
        con.close()

    return {
        "generated_at": now.isoformat(),
        "total_events": total,
        "by_type": by_type,
        "by_priority": by_priority,
        "quakes_24h": quakes_24h,
        "avg_magnitude_7d": float(avg_mag) if avg_mag is not None else None,
        "daily_counts_14d": [{"day": str(d), "count": c} for d, c in daily],
        "observations": obs_count,
    }


async def get_analytics(session, refresh: bool = True, duckdb_path: str | None = None) -> dict:
    """Mirror primary DB -> DuckDB file, run OLAP aggregations, return payload."""
    path = duckdb_path or settings.duckdb_path
    events: list[Event] = (await session.execute(select(Event))).scalars().all()
    obs_count: int = 0
    if refresh:
        from sqlalchemy import func
        obs_count = (await session.execute(select(func.count()).select_from(Observation))).scalar() or 0
    rows = _event_rows(events)

    # Top regions need `extra.region` JSON — cheaper in Python than DuckDB JSON SQL.
    top = Counter((e.extra or {}).get("region") or "Unknown" for e in events).most_common(10)

    # DuckDB calls are blocking -> run in a thread (safe under asyncio).
    try:
        result = await asyncio.to_thread(_run_snapshot_and_query, rows, obs_count, path)
    except Exception as e:
        log.warning("duckdb analytics failed (%s), falling back to python aggs", e)
        now = datetime.now(timezone.utc)
        result = {
            "generated_at": now.isoformat(),
            "total_events": len(events),
            "by_type": dict(Counter(e.type for e in events)),
            "by_priority": dict(Counter(e.priority for e in events)),
            "quakes_24h": sum(1 for e in events if e.type in ("earthquake", "tsunami_alert")
                              and _aware(e.occurred_at) >= now - timedelta(hours=24)),
            "avg_magnitude_7d": None,
            "daily_counts_14d": [],
            "observations": obs_count,
        }
    result["top_regions"] = [{"region": r, "count": c} for r, c in top]
    return result
