from datetime import datetime, timezone

from app.services import ingest as ingest_svc
from app.services.geo import haversine_km
from app.services.scoring import score_earthquake, score_weather


def _norm(dt, lat, lon, mag, kind="bmkg_m5", felt=None, potensi="Tidak berpotensi tsunami"):
    return {"kind": kind, "source": "bmkg", "external_id": f"t:{dt.isoformat()}:{kind}",
            "author": "BMKG", "text": f"M{mag}", "url": None, "observed_at": dt,
            "structured": {"magnitude": mag, "depth_km": 10.0, "latitude": lat, "longitude": lon,
                           "region": "X", "tsunami_potential": False,
                           "potensi_text": potensi, "felt": felt,
                           "shakemap_url": None, "datetime": dt.isoformat()},
            "raw": {}}


async def test_dedup_idempotent(session):
    dt = datetime(2026, 9, 12, 6, 14, 33, tzinfo=timezone.utc)
    await ingest_svc.ingest_quake_observation(session, _norm(dt, -6.03, 130.66, 5.1, "bmkg_m5"))
    await session.commit()
    # same feed row from another feed, same DateTime -> same canonical event, no duplicate
    await ingest_svc.ingest_quake_observation(session, _norm(dt, -6.03, 130.66, 5.1, "bmkg_felt",
                                                             felt="III Tiakur"))
    await session.commit()
    from sqlalchemy import func, select
    from app.models import Event
    n = (await session.execute(select(func.count()).select_from(Event))).scalar()
    assert n == 1


async def test_fuzzy_correlation_nearby(session):
    from datetime import timedelta
    dt = datetime(2026, 9, 12, 6, 14, 33, tzinfo=timezone.utc)
    await ingest_svc.ingest_quake_observation(session, _norm(dt, -6.03, 130.66, 5.1))
    await session.commit()
    # slightly revised coords/mag 8 min later -> same event
    await ingest_svc.ingest_quake_observation(
        session, _norm(dt + timedelta(minutes=8), -6.05, 130.70, 5.2, "bmkg_latest"))
    await session.commit()
    from sqlalchemy import func, select
    from app.models import Event
    n = (await session.execute(select(func.count()).select_from(Event))).scalar()
    assert n == 1


async def test_distinct_events_not_merged(session):
    from datetime import timedelta
    dt = datetime(2026, 9, 12, 6, 14, 33, tzinfo=timezone.utc)
    await ingest_svc.ingest_quake_observation(session, _norm(dt, -6.03, 130.66, 5.1))
    await ingest_svc.ingest_quake_observation(session, _norm(dt + timedelta(hours=5), 3.44, 124.53, 5.1))
    await session.commit()
    from sqlalchemy import func, select
    from app.models import Event
    n = (await session.execute(select(func.count()).select_from(Event))).scalar()
    assert n == 2


async def test_duplicate_midbatch_loses_nothing(session):
    """A duplicate external_id in the middle of a batch must not roll back siblings."""
    from datetime import timedelta
    from sqlalchemy import func, select
    from app.models import Event, Observation
    dt = datetime(2026, 9, 12, 6, 14, 33, tzinfo=timezone.utc)
    a = _norm(dt, -6.03, 130.66, 5.1, "bmkg_m5")
    b = _norm(dt + timedelta(hours=2), 3.44, 124.53, 5.1, "bmkg_m5")
    dup = dict(a)
    for norm in (a, b, dup):  # dup shares a's external_id
        await ingest_svc.ingest_quake_observation(session, norm)
    await session.commit()
    n_events = (await session.execute(select(func.count()).select_from(Event))).scalar()
    n_obs = (await session.execute(select(func.count()).select_from(Observation))).scalar()
    assert (n_events, n_obs) == (2, 2)


async def test_rerun_is_idempotent(session):
    from datetime import timedelta
    from sqlalchemy import func, select
    from app.models import Event, Observation
    dt = datetime(2026, 9, 12, 6, 14, 33, tzinfo=timezone.utc)
    norms = [_norm(dt, -6.03, 130.66, 5.1, "bmkg_m5"),
             _norm(dt + timedelta(hours=2), 3.44, 124.53, 5.1, "bmkg_m5")]
    for _ in range(2):  # run the whole batch twice
        for norm in norms:
            await ingest_svc.ingest_quake_observation(session, norm)
        await session.commit()
    n_events = (await session.execute(select(func.count()).select_from(Event))).scalar()
    n_obs = (await session.execute(select(func.count()).select_from(Observation))).scalar()
    assert (n_events, n_obs) == (2, 2)


def test_haversine_sanity():
    assert haversine_km(-6.03, 130.66, -6.05, 130.70) < 10


def test_quake_scoring_explainable():
    s, b = score_earthquake(6.2, 10.0, "III Tiakur", False)
    assert s >= 6 and b["priority"] in ("HIGH", "CRITICAL")
    assert "magnitude_base" in b["components"]
    deep, _ = score_earthquake(5.9, 376.0, None, False)
    shallow, _ = score_earthquake(5.9, 10.0, None, False)
    assert deep < shallow  # deep-focus penalty


def test_weather_scoring():
    s, b = score_weather("Severe", "Expected", "Likely", 40, "Hujan Lebat disertai Petir di Jambi", "banjir lokal")
    assert s >= 6 and b["priority"] in ("HIGH", "CRITICAL")
