from datetime import datetime, timedelta, timezone

from app.models import Event
from app.services import analytics as analytics_svc


async def _mk(session, **kw):
    now = datetime.now(timezone.utc)
    base = dict(type="earthquake", title="M5 — Test", occurred_at=now,
                latitude=-7.0, longitude=110.0, depth_km=10.0, magnitude=5.0,
                priority="HIGH", score=7.0, status="active", extra={"region": "Java"})
    base.update(kw)
    e = Event(**base)
    session.add(e)
    await session.flush()
    return e


async def test_analytics_duckdb_mirror(tmp_path, session):
    now = datetime.now(timezone.utc)
    await _mk(session, magnitude=5.0, priority="HIGH", extra={"region": "Java"})
    await _mk(session, magnitude=6.0, priority="CRITICAL", extra={"region": "Java"},
              occurred_at=now - timedelta(days=2))
    await _mk(session, type="severe_weather", title="Storm", magnitude=None,
              priority="MODERATE", extra={"region": "Sumatra"})
    await session.commit()

    out = await analytics_svc.get_analytics(
        session, refresh=True, duckdb_path=str(tmp_path / "a.duckdb"))
    assert out["total_events"] == 3
    assert out["by_type"]["earthquake"] == 2
    assert out["by_priority"]["HIGH"] == 1
    assert out["avg_magnitude_7d"] == 5.5
    assert out["top_regions"][0] == {"region": "Java", "count": 2}
    assert len(out["daily_counts_14d"]) >= 1

    # Second call without refresh still reads last snapshot.
    out2 = await analytics_svc.get_analytics(
        session, refresh=False, duckdb_path=str(tmp_path / "a.duckdb"))
    assert out2["total_events"] == 3
