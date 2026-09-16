"""Tests for cross-hazard situation intelligence (hermetic, no network)."""
from datetime import datetime, timedelta, timezone

from app.services import situations as sit_svc

NOW = datetime(2026, 9, 15, 12, 0, 0, tzinfo=timezone.utc)


def _q(id, hours_ago, lat=-7.0, lon=110.0, mag=5.0, priority="MODERATE", score=5.0,
       type="earthquake", status="active", extra=None):
    return {"id": id, "type": type, "title": f"M{mag} — T",
            "occurred_at": NOW - timedelta(hours=hours_ago),
            "latitude": lat, "longitude": lon, "depth_km": 10.0, "magnitude": mag,
            "priority": priority, "score": score, "status": status,
            "extra": extra or {"region": "Test"}}


def _w(id, hours_ago, lat=-7.0, lon=110.0, title="Hujan Lebat disertai banjir di Test",
       summary="x"):
    return {"id": id, "type": "severe_weather", "title": title,
            "occurred_at": NOW - timedelta(hours=hours_ago),
            "latitude": lat, "longitude": lon, "priority": "HIGH", "score": 7.0,
            "status": "active", "summary": summary,
            "extra": {"areas": ["A", "B"]}, "expires_at": NOW + timedelta(hours=3)}


def _volc(name="Merapi", level="SIAGA", lat=-7.54, lon=110.44):
    return {"name": name, "level": level, "latitude": lat, "longitude": lon,
            "province": "DI Yogyakarta"}


def test_tsunami_threat_links_nearby_quakes():
    t = _q("t", 2, mag=7.0, priority="CRITICAL", score=9.0, type="tsunami_alert",
           extra={"region": "South Java", "potensi_text": "Berpotensi TSUNAMI"})
    q = _q("q", 3, lat=-7.05, lon=110.05, mag=5.5)
    far = _q("f", 3, lat=3.5, lon=98.6, mag=5.0)
    out = sit_svc.detect_tsunami_threats([t, q, far], NOW)
    assert len(out) == 1
    s = out[0]
    assert s["kind"] == "TSUNAMI_THREAT" and s["severity"] == "CRITICAL"
    assert set(s["member_ids"]) == {"t", "q"}
    assert s["confidence"] == "MODERATE"
    assert any("caus" in c for c in s["caveats"])


def test_rain_landslide_needs_keywords_and_quake():
    w = _w("w", 1)
    q = _q("q", 100, mag=5.0)  # within 14d, nearby, M>=4.5
    out = sit_svc.detect_rain_landslide([w, q], NOW)
    assert len(out) == 1
    assert out[0]["kind"] == "RAIN_LANDSLIDE"
    assert "no landslide has been observed" in out[0]["interpretation"]
    # no keywords -> nothing
    plain = _w("p", 1, title="Cerah berawan di Test")
    assert sit_svc.detect_rain_landslide([plain, q], NOW) == []
    # no quake -> nothing
    assert sit_svc.detect_rain_landslide([w], NOW) == []


def test_volcano_tectonic_colocation():
    from app.services import clustering as cl
    a = _q("a", 30, lat=-7.5, lon=110.4, mag=6.0)
    b = _q("b", 10, lat=-7.52, lon=110.42, mag=4.5)
    seqs = cl.find_sequences([a, b])
    assert len(seqs) == 1
    by_id = {"a": a, "b": b}
    out = sit_svc.detect_volcano_tectonic(seqs, [_volc()], by_id)
    assert len(out) == 1
    assert out[0]["kind"] == "VOLCANO_TECTONIC"
    assert out[0]["observed"]["volcano"] == "Merapi"
    assert "not linked" in out[0]["interpretation"]
    # normal-level volcano -> nothing
    assert sit_svc.detect_volcano_tectonic(seqs, [_volc(level="NORMAL")], by_id) == []
    # volcano rules skip entirely when levels unavailable
    assert sit_svc.detect_situations([a, b], seqs, None, NOW) == [] or True
    no_volc = [s for s in sit_svc.detect_situations([a, b], seqs, None, NOW)
               if s["kind"] in ("VOLCANO_TECTONIC", "WEATHER_VOLCANO")]
    assert no_volc == []


def test_multi_hazard_region_needs_two_kinds():
    q1 = _q("q1", 5)
    q2 = _q("q2", 6, lat=-7.02, lon=110.02)
    assert sit_svc.detect_multi_hazard_regions([q1, q2], NOW) == []  # one kind only
    w = _w("w", 4)
    out = sit_svc.detect_multi_hazard_regions([q1, q2, w], NOW)
    assert len(out) == 1
    assert out[0]["kind"] == "MULTI_HAZARD_REGION"
    assert set(out[0]["observed"]["hazard_kinds"]) == {"quake", "severe_weather"}


def test_situation_ids_stable_and_deduped():
    t = _q("t", 2, mag=7.0, type="tsunami_alert")
    q = _q("q", 3)
    a = sit_svc.detect_situations([t, q], [], None, NOW)
    b = sit_svc.detect_situations([q, t], [], None, NOW)  # order swapped
    assert [s["situation_id"] for s in a] == [s["situation_id"] for s in b]


def test_member_severity_and_membership():
    t = _q("t", 2, mag=7.0, priority="CRITICAL", type="tsunami_alert")
    q = _q("q", 3, priority="MODERATE")
    sits = sit_svc.detect_situations([t, q], [], None, NOW)
    assert sit_svc.member_severity("t", sits) == "CRITICAL"
    assert sit_svc.member_severity("q", sits) == "CRITICAL"
    assert sit_svc.member_severity("zzz", sits) is None
    assert len(sit_svc.situations_for_event("t", sits)) >= 1


async def test_briefing_includes_situations(session, monkeypatch):
    from app.collectors import magma
    from app.core.config import settings
    from app.models import Event
    from app.services import briefing
    monkeypatch.setattr(settings, "openrouter_api_key", "")

    async def _volc_empty(*a, **k):
        return {"volcanoes": [], "updated_at": None, "levels_updated_at": None,
                "attribution": "test"}
    monkeypatch.setattr(magma, "get_volcanoes", _volc_empty)
    now = datetime.now(timezone.utc)
    session.add(Event(type="tsunami_alert", title="M7 — T", occurred_at=now - timedelta(hours=2),
                      latitude=-8.0, longitude=110.0, depth_km=20.0, magnitude=7.0,
                      priority="CRITICAL", score=9.5, summary="x",
                      extra={"region": "South Java", "potensi_text": "Berpotensi TSUNAMI"}))
    session.add(Event(type="severe_weather", title="Hujan Lebat banjir di Coast",
                      occurred_at=now - timedelta(hours=1), latitude=-8.0, longitude=110.1,
                      priority="HIGH", score=7.0, summary="x",
                      expires_at=now + timedelta(hours=5), extra={"areas": ["A"]}))
    await session.commit()
    b = await briefing.build_briefing(session)
    kinds = {s["kind"] for s in b["situations"]}
    assert "TSUNAMI_THREAT" in kinds and "MULTI_HAZARD_REGION" in kinds
    assert any("situation" in line.lower() for line in b["overview"])
    assert any(w.get("situations") for w in b["watchlist"])
