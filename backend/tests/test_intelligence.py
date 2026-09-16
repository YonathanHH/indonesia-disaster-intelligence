"""Tests for the analytical intelligence layer.

Covers: clustering/sequences, exposure heuristics, change detection,
ingest modifiers + rescore history, briefing integration. All hermetic
(in-memory DB, no network).
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.collectors import magma
from app.core.config import settings
from app.models import Event, EventHistory
from app.services import briefing, change as change_svc
from app.services import clustering as clustering_svc
from app.services import exposure as exposure_svc
from app.services import history as history_svc
from app.services import ingest as ingest_svc

NOW = datetime(2026, 9, 15, 12, 0, 0, tzinfo=timezone.utc)


def _norm(dt, lat, lon, mag, kind="bmkg_m5", felt=None,
          potensi="Tidak berpotensi tsunami", depth=10.0):
    return {"kind": kind, "source": "bmkg", "external_id": f"intel:{dt.isoformat()}:{kind}:{mag}",
            "author": "BMKG", "text": f"M{mag}", "url": None, "observed_at": dt,
            "structured": {"magnitude": mag, "depth_km": depth, "latitude": lat, "longitude": lon,
                           "region": "Test Region", "tsunami_potential": False,
                           "potensi_text": potensi, "felt": felt,
                           "shakemap_url": None, "datetime": dt.isoformat()},
            "raw": {}}


def _ev(id="e1", type="earthquake", hours_ago=2, lat=-6.2, lon=106.8, mag=5.0,
        priority="MODERATE", score=5.0, status="active", extra=None):
    return {"id": id, "type": type, "title": f"M{mag} — Test",
            "occurred_at": NOW - timedelta(hours=hours_ago),
            "latitude": lat, "longitude": lon, "depth_km": 10.0, "magnitude": mag,
            "priority": priority, "score": score, "status": status,
            "extra": extra or {}}


# ---------------- clustering ----------------

def test_sequence_chains_nearby_events():
    a = _ev("a", hours_ago=50, lat=-7.0, lon=110.0, mag=6.5)
    b = _ev("b", hours_ago=30, lat=-7.05, lon=110.05, mag=4.5)
    c = _ev("c", hours_ago=5, lat=-7.1, lon=109.95, mag=4.0)
    far = _ev("d", hours_ago=4, lat=3.5, lon=98.6, mag=5.0)  # Aceh, far away
    seqs = clustering_svc.find_sequences([a, b, c, far])
    assert len(seqs) == 1
    s = seqs[0]
    assert s["member_count"] == 3
    assert s["mainshock_id"] == "a" and s["mainshock_magnitude"] == 6.5
    assert s["cluster_id"] == "seq-a"
    assert s["method"] == "sequence-v1"


def test_sequence_respects_time_gap():
    a = _ev("a", hours_ago=200, mag=6.0)
    b = _ev("b", hours_ago=1, mag=4.0)  # same place, 8+ days apart
    assert clustering_svc.find_sequences([a, b]) == []


def test_sequence_ignores_weather_and_singles():
    w = _ev("w", type="severe_weather", hours_ago=1)
    q = _ev("q", hours_ago=1)
    assert clustering_svc.find_sequences([w, q]) == []


def test_companion_count():
    base = [_ev("a", hours_ago=10), _ev("b", hours_ago=20)]
    n = clustering_svc.companion_count(-6.2, 106.8, NOW, base, exclude_id="new")
    assert n == 2
    assert clustering_svc.companion_count(3.5, 98.6, NOW, base) == 0


# ---------------- exposure ----------------

def test_exposure_quake_near_city():
    e = _ev(lat=-6.21, lon=106.85, mag=5.5)  # Jakarta epicenter
    a = exposure_svc.assess_exposure(e)
    assert a["method"] == "exposure-v1"
    assert a["nearest_cities"][0]["city"] == "Jakarta"
    assert a["nearest_cities"][0]["km"] == 0.0
    assert a["confidence"] in ("LOW", "MODERATE")
    assert any("not a loss" in c for c in a["caveats"])
    # no population figures anywhere: city entries carry coords-derived km only,
    # and the disclaimer states that explicitly
    assert all(set(c.keys()) == {"city", "province", "km"} for c in a["nearest_cities"])
    assert not any("pop" in k.lower() for k in a.keys())
    assert any("no population figures" in c.lower() for c in a["caveats"])


def test_exposure_class_scales_with_magnitude_and_felt():
    assert exposure_svc.assess_exposure(_ev(mag=7.2))["class"] == "WIDESPREAD"
    felt = _ev(mag=5.0, extra={"felt": "III A, III B, IV C, III D, II E"})
    got = exposure_svc.assess_exposure(felt)
    assert got["felt_areas"] == 5
    assert exposure_svc.exposure_bonus(got, "earthquake") == (0.5, "felt in 5 areas")


def test_exposure_tsunami_is_context_not_bonus():
    e = _ev("t", type="tsunami_alert", mag=7.0,
            extra={"tsunami_potential": True, "region": "South Java"})
    a = exposure_svc.assess_exposure(e)
    assert a["coastal_threat"] is True
    assert any("coastal" in x for x in a["assets"])
    # tsunami flag alone (no felt) earns no extra bonus: +2.0 component covers it
    lonely = exposure_svc.assess_exposure(_ev("t2", type="tsunami_alert", mag=6.0,
                                              extra={"tsunami_potential": True}))
    assert exposure_svc.exposure_bonus(lonely, "tsunami_alert") == (0.0, "")


def test_exposure_weather_scales_with_areas():
    e = _ev("w", type="severe_weather", mag=None,
            extra={"areas": [f"Area {i}" for i in range(35)]})
    a = exposure_svc.assess_exposure(e)
    assert a["class"] == "WIDESPREAD"
    assert exposure_svc.exposure_bonus(a, "severe_weather") == (0.5, "broad CAP coverage")


# ---------------- ingest modifiers + rescore history ----------------

async def test_modifiers_capped_and_labelled(session):
    # three companions first (separate times/locations that won't merge)
    base = NOW - timedelta(hours=30)
    await ingest_svc.ingest_quake_observation(
        session, _norm(base, -6.2, 106.8, 4.5, kind="bmkg_m5", felt="III X, III Y, IV Z, III W"))
    await session.commit()
    e = await ingest_svc.ingest_quake_observation(
        session, _norm(base + timedelta(hours=1), -6.25, 106.85, 4.6, kind="bmkg_m5"))
    await session.commit()
    # main event: felt-heavy (REGIONAL + felt>=3 -> exposure bonus) + 2 companions (sequence bonus)
    main = await ingest_svc.ingest_quake_observation(
        session, _norm(base + timedelta(hours=2), -6.22, 106.82, 5.8, kind="bmkg_latest",
                       felt="III A, III B, IV C, III D"))
    await session.commit()
    assert main is not None
    comps = main.score_breakdown["components"]
    assert comps.get("exposure_bonus") == 0.5
    # capped: never more than +1.0 over the pure score_earthquake value
    from app.services.scoring import score_earthquake
    pure, _ = score_earthquake(5.8, 10.0, "III A, III B, IV C, III D", False)
    assert main.score <= round(pure + 1.0, 2)
    assert main.score >= pure
    assert (main.extra or {}).get("exposure", {}).get("method") == "exposure-v1"
    hist = (await session.execute(
        select(EventHistory).where(EventHistory.event_id == main.id,
                                   EventHistory.kind == "created"))).scalars().all()
    assert any("intel_modifiers" in (h.payload or {}) for h in hist)


async def test_felt_merge_writes_rescore_on_band_change(session):
    dt = NOW - timedelta(hours=3)
    e = await ingest_svc.ingest_quake_observation(
        session, _norm(dt, -8.0, 115.0, 5.9, kind="bmkg_m5"))
    await session.commit()
    assert e.priority == "HIGH"  # 6.0 + 1.0 shallow = 7.0
    # felt feed arrives: +1.5 MMI + exposure bonus -> 8.0+ CRITICAL
    e2 = await ingest_svc.ingest_quake_observation(
        session, _norm(dt, -8.0, 115.0, 5.9, kind="bmkg_felt",
                       felt="V A, IV B, III C, III D, III E, III F"))
    await session.commit()
    assert e2.id == e.id
    assert e2.priority == "CRITICAL"
    rows = (await session.execute(
        select(EventHistory).where(EventHistory.event_id == e.id,
                                   EventHistory.kind == "rescore"))).scalars().all()
    assert len(rows) == 1
    assert rows[0].payload["before"]["priority"] == "HIGH"
    assert rows[0].payload["after"]["priority"] == "CRITICAL"


# ---------------- change detection ----------------

async def test_compute_changes_finds_new_resolved_expired(session):
    from app.models import EventHistory as EH
    now = datetime.now(timezone.utc)
    e1 = Event(type="earthquake", title="M5 — New", occurred_at=now - timedelta(hours=2),
               latitude=-7.0, longitude=110.0, depth_km=10.0, magnitude=5.0,
               priority="MODERATE", score=5.0, status="active", summary="x")
    e2 = Event(type="severe_weather", title="Storm", occurred_at=now - timedelta(hours=30),
               latitude=-2.0, longitude=104.0, priority="MODERATE", score=5.0,
               status="active", summary="x",
               expires_at=now - timedelta(hours=1),
               extra={"areas": ["A"]})
    session.add_all([e1, e2])
    await session.flush()
    session.add(EH(event_id=e1.id, kind="resolved", message="Operator marked event resolved"))
    await session.commit()

    out = await change_svc.compute_changes(session, since=now - timedelta(hours=24))
    assert out["counts"]["new"] >= 1
    assert any(i["event_id"] == e1.id for i in out["resolved"])
    assert any(i["event_id"] == e2.id for i in out["expired"])
    assert out["counts"]["escalated"] == 0  # no rescore history yet


async def test_compute_changes_detects_escalation(session):
    dt = NOW - timedelta(hours=3)
    e = await ingest_svc.ingest_quake_observation(
        session, _norm(dt, -8.0, 115.0, 5.9, kind="bmkg_m5"))
    await session.commit()
    await ingest_svc.ingest_quake_observation(
        session, _norm(dt, -8.0, 115.0, 5.9, kind="bmkg_felt",
                       felt="V A, IV B, III C, III D, III E, III F"))
    await session.commit()
    out = await change_svc.compute_changes(session, since=NOW - timedelta(hours=24))
    assert any(i["event_id"] == e.id for i in out["escalated"])


# ---------------- briefing integration ----------------

async def test_briefing_has_developments_and_sequences(session, monkeypatch):
    monkeypatch.setattr(magma, "get_volcanoes", _volc())
    monkeypatch.setattr(settings, "openrouter_api_key", "")
    dt = NOW - timedelta(hours=2)
    await ingest_svc.ingest_quake_observation(
        session, _norm(dt, -7.0, 110.0, 6.5, kind="bmkg_m5"))
    await session.commit()
    await ingest_svc.ingest_quake_observation(
        session, _norm(dt + timedelta(hours=1), -7.05, 110.05, 4.5, kind="bmkg_latest"))
    await session.commit()
    b = await briefing.build_briefing(session)
    assert "developments" in b and b["developments"]["counts"]["new"] >= 1
    assert len(b["sequences"]) == 1
    assert b["sequences"][0]["member_count"] == 2
    assert any("sequence" in (w.get("why") or "").lower() or w.get("cluster")
               for w in b["watchlist"])
    assert any("aftershock sequence" in a["action"] for a in b["recommended_actions"])
    assert any("heuristic" in c for c in b["caveats"])


def _volc():
    async def _go(*a, **k):
        return {"volcanoes": [], "updated_at": None, "levels_updated_at": None,
                "attribution": "test"}
    return _go


# ---------------- historical context ----------------

def _hist_ev(id, days_ago, mag=4.5, lat=-7.0, lon=110.0):
    return {"id": id, "type": "earthquake", "title": f"M{mag}",
            "occurred_at": NOW - timedelta(days=days_ago),
            "latitude": lat, "longitude": lon, "magnitude": mag}


def _quiet_region():
    # ~1 event/month baseline: 6 events spread over 180d, none recent
    return [_hist_ev(f"q{i}", days_ago=20 + i * 28, mag=4.0 + (i % 3) * 0.5)
            for i in range(6)]


def test_history_quiet_is_normal():
    ctx = history_svc.assess_history(-7.0, 110.0, 4.5, _quiet_region(), NOW)
    assert ctx["class"] == "NORMAL"
    assert ctx["method"] == "history-v1"
    assert ctx["observed"]["baseline_count"] == 6
    assert history_svc.history_bonus(ctx) == (0.0, "")


def test_history_burst_is_significant():
    events = _quiet_region() + [
        _hist_ev(f"r{i}", days_ago=2, mag=5.0) for i in range(6)]
    ctx = history_svc.assess_history(-7.0, 110.0, 5.0, events, NOW)
    assert ctx["class"] == "SIGNIFICANT"
    assert ctx["observed"]["recent_count"] == 6
    b, reason = history_svc.history_bonus(ctx)
    assert b == 0.5 and "significant" in reason


def test_history_elevated_band():
    events = _quiet_region() + [_hist_ev(f"r{i}", days_ago=3, mag=4.5) for i in range(3)]
    ctx = history_svc.assess_history(-7.0, 110.0, 4.5, events, NOW)
    assert ctx["class"] in ("ELEVATED", "UNUSUAL")


def test_history_cold_start_is_normal_with_caveat():
    ctx = history_svc.assess_history(-7.0, 110.0, 6.0, [], NOW)
    assert ctx["class"] == "NORMAL"
    assert ctx["confidence"] == "LOW"
    assert any("insufficient history" in c for c in ctx["caveats"])


def test_history_largest_in_record_elevates():
    # quiet baseline, one M6.5 today: largest in 365d -> at least ELEVATED
    events = _quiet_region() + [_hist_ev("big", days_ago=0, mag=6.5)]
    ctx = history_svc.assess_history(-7.0, 110.0, 6.5, events, NOW)
    assert ctx["class"] in ("ELEVATED", "UNUSUAL", "SIGNIFICANT")
    assert ctx["observed"]["largest_in_days"] == 365


def test_history_observed_vs_interpretation_separated():
    ctx = history_svc.assess_history(-7.0, 110.0, 5.0, _quiet_region(), NOW)
    assert set(ctx["observed"].keys()) == {
        "region_km", "baseline_days", "recent_days", "baseline_count",
        "recent_count", "expected_7d", "daily_rate", "largest_in_days"}
    assert isinstance(ctx["class"], str) and isinstance(ctx["caveats"], list)


def test_sequence_history_attaches():
    events = _quiet_region() + [_hist_ev(f"r{i}", days_ago=1, mag=5.0) for i in range(4)]
    clusters = clustering_svc.find_sequences(events)
    assert clusters
    h = history_svc.sequence_history(clusters[0], events, NOW)
    assert h["cluster_id"] == clusters[0]["cluster_id"]
    assert h["class"] in ("ELEVATED", "UNUSUAL", "SIGNIFICANT")


async def test_ingest_modifiers_capped_at_one_with_history(session):
    # quiet baseline far back + recent burst companions + felt-heavy mainshock:
    # exposure + sequence + history bonuses would sum 1.5 -> capped 1.0
    base = NOW - timedelta(hours=30)
    for i in range(6):  # quiet baseline region events (old, won't chain)
        old = NOW - timedelta(days=30 + i * 25)
        await ingest_svc.ingest_quake_observation(
            session, _norm(old, -7.0, 110.0, 4.2, kind="bmkg_m5"))
    for i in range(3):  # recent companions (chain + history burst)
        await ingest_svc.ingest_quake_observation(
            session, _norm(base + timedelta(hours=i), -7.02, 110.02, 4.6, kind="bmkg_m5"))
    await session.commit()
    main = await ingest_svc.ingest_quake_observation(
        session, _norm(base + timedelta(hours=4), -7.0, 110.0, 6.2, kind="bmkg_latest",
                       felt="IV A, III B, III C, III D"))
    await session.commit()
    comps = main.score_breakdown["components"]
    bonus_sum = round(sum(v for k, v in comps.items() if k.endswith("_bonus")
                          and k in ("exposure_bonus", "sequence_bonus", "history_bonus")), 2)
    from app.services.scoring import score_earthquake
    pure, _ = score_earthquake(6.2, 10.0, "IV A, III B, III C, III D", False)
    assert bonus_sum <= 1.0
    assert main.score == round(min(10.0, pure + bonus_sum), 2)
    assert (main.extra or {}).get("history", {}).get("method") == "history-v1"


async def test_briefing_sequences_carry_history(session, monkeypatch):
    monkeypatch.setattr(magma, "get_volcanoes", _volc())
    monkeypatch.setattr(settings, "openrouter_api_key", "")
    dt = NOW - timedelta(hours=2)
    await ingest_svc.ingest_quake_observation(
        session, _norm(dt, -7.0, 110.0, 6.5, kind="bmkg_m5"))
    await session.commit()
    await ingest_svc.ingest_quake_observation(
        session, _norm(dt + timedelta(hours=1), -7.05, 110.05, 4.5, kind="bmkg_latest"))
    await session.commit()
    b = await briefing.build_briefing(session)
    assert b["sequences"] and b["sequences"][0]["history"]["method"] == "history-v1"
    assert any("regional behavior" in line for line in b["overview"])
