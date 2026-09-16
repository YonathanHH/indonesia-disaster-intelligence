"""Briefing builder tests (in-memory DB, mocked volcano source)."""
from datetime import datetime, timedelta, timezone

from app.collectors import magma
from app.core.config import settings
from app.models import Event
from app.services import briefing, enrichment


def _mk(type="earthquake", title="M5.0 — X", priority="MODERATE", score=5.0,
        mag=5.0, depth=10.0, extra=None, hours_ago=2, expires_in_h=None):
    now = datetime.now(timezone.utc)
    return Event(
        type=type, title=title, occurred_at=now - timedelta(hours=hours_ago),
        latitude=-7.5, longitude=110.4, depth_km=depth, magnitude=mag,
        priority=priority, score=score, score_breakdown={},
        summary=title, extra=extra or {},
        expires_at=(now + timedelta(hours=expires_in_h)) if expires_in_h else None,
    )


def _volc(levels):
    async def _go(*a, **k):
        return {"volcanoes": [
            {"name": n, "slug": n.lower(), "latitude": -7.0, "longitude": 110.0,
             "level": lvl, "level_code": 3, "level_color": "#fb923c",
             "province": "Jawa Timur", "url": "https://magma.esdm.go.id/"}
            for n, lvl in levels], "updated_at": None, "levels_updated_at": None,
            "attribution": "test"}
    return _go


async def test_full_briefing(session, monkeypatch):
    monkeypatch.setattr(magma, "get_volcanoes", _volc([("Merapi", "SIAGA"), ("Bromo", "WASPADA")]))
    monkeypatch.setattr(settings, "openrouter_api_key", "")  # hermetic: no live LLM
    session.add(_mk(type="tsunami_alert", title="M7.0 — South Java", priority="CRITICAL",
                    score=9.0, mag=7.0, extra={"region": "South Java", "felt": "III Cilacap"}))
    session.add(_mk(type="severe_weather", title="Hujan Lebat di Jambi", priority="HIGH",
                    score=7.0, mag=None, depth=None, hours_ago=1, expires_in_h=2,
                    extra={"areas": ["A", "B"]}))
    session.add(_mk(title="M3.0 — Y", priority="LOW", score=2.0, mag=3.0))
    await session.commit()

    b = await briefing.build_briefing(session)
    assert "2 high-priority" in b["headline"]
    assert b["watchlist"][0]["title"] == "M7.0 — South Java"  # top score first
    assert "felt" in b["watchlist"][0]["why"]

    urgencies = [a["urgency"] for a in b["recommended_actions"]]
    assert urgencies[0] == "immediate"
    texts = " ".join(a["action"] + a["reason"] for a in b["recommended_actions"])
    assert "tsunami bulletin" in texts
    assert "expiry" in texts or "Reassess" in texts
    assert "Merapi" in texts and "exclusion zone" in texts
    assert b["llm_summary"] is None  # no key in test env
    assert any("not validated risk" in c for c in b["caveats"])


async def test_empty_briefing_with_volcano_outage(session, monkeypatch):
    async def _boom(*a, **k):
        raise RuntimeError("magma down")
    monkeypatch.setattr(magma, "get_volcanoes", _boom)

    b = await briefing.build_briefing(session)
    assert b["watchlist"] == []
    assert len(b["recommended_actions"]) == 1
    assert b["recommended_actions"][0]["urgency"] == "routine"
    assert any("could not be refreshed" in c for c in b["caveats"])


async def test_calm_volcano_picture(session, monkeypatch):
    monkeypatch.setattr(magma, "get_volcanoes", _volc([("Agung", "NORMAL")]))
    monkeypatch.setattr(settings, "openrouter_api_key", "")
    b = await briefing.build_briefing(session)
    assert any("calm" in line for line in b["overview"])


async def test_llm_polish_wires_through(session, monkeypatch):
    monkeypatch.setattr(magma, "get_volcanoes", _volc([]))
    monkeypatch.setattr(settings, "openrouter_api_key", "sk-or-test")
    monkeypatch.setattr(settings, "openrouter_model", "some/model")

    async def fake_note(evidence):
        assert evidence["events"] == [] or "event_id" in evidence["events"][0]
        return ("Two high-priority events are active including a CRITICAL M7.0 tsunami-potential "
                "earthquake near South Java with shaking felt in Cilacap. Maintain coastal readiness "
                "and monitor official BMKG bulletins for further updates.", "ok")

    monkeypatch.setattr(enrichment, "maybe_llm_note", fake_note)
    b = await briefing.build_briefing(session)
    assert b["llm_summary"].startswith("Two high-priority")
    assert b["llm_model"] == "some/model"
    assert b["llm_status"] == "ok"


async def test_llm_misconfigured_adds_caveat(session, monkeypatch):
    monkeypatch.setattr(magma, "get_volcanoes", _volc([]))
    monkeypatch.setattr(settings, "openrouter_api_key", "sk-or-test")
    monkeypatch.setattr(settings, "openrouter_model", "openrouter/free")
    b = await briefing.build_briefing(session)
    assert b["llm_summary"] is None
    assert b["llm_status"] == "misconfigured"
    assert any("OPENROUTER_MODEL" in c for c in b["caveats"])
