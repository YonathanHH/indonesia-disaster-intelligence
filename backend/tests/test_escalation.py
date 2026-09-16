"""Tests for system escalation (pure evaluator + briefing/route wiring)."""
from datetime import datetime, timedelta, timezone

from app.services import escalation as esc_svc

NOW = datetime(2026, 9, 15, 12, 0, 0, tzinfo=timezone.utc)


def _e(id, type="earthquake", priority="MODERATE", score=5.0, hours_ago=2):
    return {"id": id, "type": type, "title": f"T {id}", "priority": priority,
            "score": score, "status": "active",
            "occurred_at": NOW - timedelta(hours=hours_ago),
            "latitude": -7.0, "longitude": 110.0}


def test_quiet_is_normal():
    out = esc_svc.evaluate_escalation(events=[_e("a")], now=NOW)
    assert out["level"] == "NORMAL"
    assert out["triggers"] == []
    assert "Routine" in out["posture"] or "routine" in out["posture"].lower()


def test_tsunami_bulletin_alerts_alone():
    t = _e("t", type="tsunami_alert", priority="CRITICAL", score=9.5)
    out = esc_svc.evaluate_escalation(events=[t], now=NOW)
    assert out["level"] == "ALERT"
    assert out["triggers"][0]["rule"] == "TSUNAMI_BULLETIN"
    assert out["triggers"][0]["event_ids"] == ["t"]


def test_awas_alerts_alone():
    out = esc_svc.evaluate_escalation(
        events=[], volcanoes=[{"name": "Merapi", "level": "AWAS"}], now=NOW)
    assert out["level"] == "ALERT"
    assert out["triggers"][0]["rule"] == "VOLCANO_AWAS"


def test_significant_history_alerts():
    seq = {"cluster_id": "seq-x", "member_ids": ["a", "b", "c", "d"],
           "member_count": 4, "mainshock_magnitude": 6.0}
    sh = {"seq-x": {"class": "SIGNIFICANT", "confidence": "MODERATE",
                    "observed": {"recent_count": 6, "expected_7d": 0.5,
                                 "baseline_days": 180}}}
    out = esc_svc.evaluate_escalation(events=[], sequences=[seq], seq_history=sh, now=NOW)
    assert out["level"] == "ALERT"
    assert any(t["rule"] == "SIGNIFICANT_HISTORY" for t in out["triggers"])


def test_load_triggers_watch_not_alert():
    evs = [_e(f"h{i}", priority="HIGH", score=7.0) for i in range(4)]
    out = esc_svc.evaluate_escalation(events=evs, now=NOW)
    assert out["level"] == "WATCH"
    assert any(t["rule"] == "SEVERITY_LOAD" for t in out["triggers"])


def test_expired_pileup_is_actionable_watch():
    dev = {"expired": [{"event_id": f"e{i}"} for i in range(3)]}
    out = esc_svc.evaluate_escalation(events=[], developments=dev, now=NOW)
    assert out["level"] == "WATCH"
    assert out["triggers"][0]["rule"] == "EXPIRED_PILEUP"


def test_never_raises_on_garbage():
    out = esc_svc.evaluate_escalation(events=None, sequences="junk",
                                      volcanoes=[None], developments=[], now=NOW)
    assert out["level"] in ("NORMAL", "WATCH", "ALERT")


def test_broken_rule_does_not_mask_real_triggers(monkeypatch):
    # A programming error in one rule must not suppress (or masquerade as)
    # genuine triggers from the other rules.
    import app.services.escalation as esc_mod
    real_trig = esc_mod._trig
    calls = {"n": 0}

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 2:  # break the second trigger only
            raise RuntimeError("boom")
        return real_trig(*a, **k)
    monkeypatch.setattr(esc_mod, "_trig", flaky)
    t = _e("t", type="tsunami_alert", priority="CRITICAL", score=9.5)
    evs = [t] + [_e(f"h{i}", priority="HIGH", score=7.0) for i in range(4)]
    out = esc_svc.evaluate_escalation(events=evs, now=NOW)
    rules = {x["rule"] for x in out["triggers"]}
    assert "TSUNAMI_BULLETIN" in rules
    assert out["level"] == "ALERT"
    assert "EVALUATION_FAULT" not in rules


async def test_briefing_carries_escalation(session, monkeypatch):
    from app.collectors import magma
    from app.core.config import settings
    from app.models import Event
    from app.services import briefing
    monkeypatch.setattr(settings, "openrouter_api_key", "")

    async def _v(*a, **k):
        return {"volcanoes": [], "updated_at": None, "levels_updated_at": None,
                "attribution": "test"}
    monkeypatch.setattr(magma, "get_volcanoes", _v)
    now = datetime.now(timezone.utc)
    session.add(Event(type="tsunami_alert", title="M7 — T",
                      occurred_at=now - timedelta(hours=1),
                      latitude=-8.0, longitude=110.0, depth_km=20.0, magnitude=7.0,
                      priority="CRITICAL", score=9.5, summary="x",
                      extra={"region": "X", "potensi_text": "Berpotensi TSUNAMI"}))
    await session.commit()
    b = await briefing.build_briefing(session)
    assert b["escalation"]["level"] == "ALERT"
    assert b["headline"].startswith("ALERT")
    assert b["recommended_actions"][0]["urgency"] == "immediate"
    assert "Posture ALERT" in b["recommended_actions"][0]["action"]
