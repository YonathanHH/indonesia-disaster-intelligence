from datetime import datetime, timedelta, timezone

from app.models import Event, Observation
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


async def test_analytics_aggregates_in_sql(session):
    now = datetime.now(timezone.utc)
    await _mk(session, magnitude=5.0, priority="HIGH", extra={"region": "Java"})
    await _mk(session, magnitude=6.0, priority="CRITICAL", extra={"region": "Java"},
              occurred_at=now - timedelta(days=2))
    await _mk(session, type="severe_weather", title="Storm", magnitude=None,
              priority="MODERATE", extra={"region": "Sumatra"})
    session.add(Observation(kind="bmkg_m5", source="bmkg", external_id="obs-1",
                            observed_at=now))
    await session.commit()

    out = await analytics_svc.get_analytics(session, refresh=True)
    assert out["total_events"] == 3
    assert out["by_type"] == {"earthquake": 2, "severe_weather": 1}
    assert out["by_priority"]["HIGH"] == 1
    assert out["quakes_24h"] == 1                  # the 2-day-old one is outside 24h
    assert out["avg_magnitude_7d"] == 5.5          # the weather row has magnitude NULL
    assert out["top_regions"][0] == {"region": "Java", "count": 2}
    assert out["observations"] == 1
    assert len(out["daily_counts_14d"]) == 2
    assert all(set(d) == {"day", "count"} for d in out["daily_counts_14d"])


async def test_analytics_without_refresh_skips_observation_count(session):
    now = datetime.now(timezone.utc)
    await _mk(session)
    session.add(Observation(kind="bmkg_m5", source="bmkg", external_id="obs-2",
                            observed_at=now))
    await session.commit()
    out = await analytics_svc.get_analytics(session, refresh=False)
    assert out["total_events"] == 1
    assert out["observations"] == 0      # preserved behaviour: counted only on refresh


async def test_analytics_empty_db(session):
    out = await analytics_svc.get_analytics(session, refresh=True)
    assert out["total_events"] == 0
    assert out["by_type"] == {} and out["by_priority"] == {}
    assert out["avg_magnitude_7d"] is None
    assert out["top_regions"] == [] and out["daily_counts_14d"] == []


def test_duckdb_setting_is_gone():
    from app.core.config import settings

    assert not hasattr(settings, "duckdb_path")
