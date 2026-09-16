"""System-wide escalation and anomaly detection (deterministic, evidence-based).

Answers: "is hazard activity becoming meaningfully unusual right now, and
at what level should the operator hold the posture?" Levels:

  NORMAL — routine monitoring cadence.
  WATCH  — heightened monitoring; corroborated unusual activity or load.
  ALERT  — coordinate response posture; authoritative bulletin or strong
           corroborated anomaly.

Method (escalation-v1). Triggers fire only on corroboration or an
authoritative bulletin — never on a single uncorroborated signal:
  - TSUNAMI_BULLETIN (ALERT): active BMKG tsunami bulletin. Authoritative.
  - VOLCANO_AWAS (ALERT): PVMBG level AWAS. Authoritative.
  - SIGNIFICANT_HISTORY (ALERT): sequence/event history class SIGNIFICANT
    (burst vs own baseline with absolute-count guards).
  - MAJOR_SEQUENCE (ALERT): mainshock M>=7 with >=3 sequence members.
  - SIAGA_CONCENTRATION (WATCH): >=2 volcanoes at SIAGA, or a HIGH+
    volcano-tectonic situation.
  - SITUATION_LOAD (WATCH): >=2 HIGH+ situations active.
  - SEVERITY_LOAD (WATCH): >=4 active HIGH/CRITICAL events.
  - EXPIRED_PILEUP (WATCH): >=3 active alerts past expiry (hygiene —
    actionable: confirm renewal or resolve).

Each trigger carries stable ids, evidence references (event/situation ids
plus the numbers behind the call), and confidence. The system level is the
max trigger level. Pure function — briefing and /escalation share it.
No prediction, no causality: triggers describe observed state.
"""
from __future__ import annotations

from datetime import datetime, timezone

METHOD = "escalation-v1"
LEVELS = ("NORMAL", "WATCH", "ALERT")
_LEVEL_RANK = {"NORMAL": 0, "WATCH": 1, "ALERT": 2}


def _get(obj, key: str, default=None):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _trig(rule: str, level: str, title: str, why: str, event_ids: list[str],
          situation_ids: list[str], confidence: str) -> dict:
    return {
        "trigger_id": f"esc-{rule.lower()}",
        "rule": rule,
        "method": METHOD,
        "level": level,
        "title": title,
        "why": why,
        "event_ids": sorted(set(event_ids)),
        "situation_ids": sorted(set(situation_ids)),
        "confidence": confidence,
    }


def evaluate_escalation(events: list | None = None, sequences: list | None = None,
                        situations: list | None = None, volcanoes: list | None = None,
                        developments: dict | None = None,
                        seq_history: dict | None = None,
                        now: datetime | None = None) -> dict:
    """Evaluate system escalation level. Never raises on bad input."""
    now = now or datetime.now(timezone.utc)
    events = list(events or [])
    sequences = list(sequences or [])
    situations = list(situations or [])
    volcanoes = list(volcanoes or [])
    seq_history = seq_history or {}
    triggers: list[dict] = []
    faults: list[str] = []

    def _safe(rule: str, fn):
        try:
            out = fn()
            if out:
                triggers.extend(out if isinstance(out, list) else [out])
        except Exception as e:  # one bad rule must not kill the others
            faults.append(f"{rule}: {e}")

    try:
        active = [e for e in events if _get(e, "status", "active") == "active"]
        high = [e for e in active if str(_get(e, "priority", "")) in ("HIGH", "CRITICAL")]
    except Exception as e:
        faults.append(f"prefilter: {e}")
        active, high = [], []

    def _bulletins():
        found = []
        tsunami = [e for e in active if _get(e, "type") == "tsunami_alert"]
        if tsunami:
            found.append(_trig(
                "TSUNAMI_BULLETIN", "ALERT",
                f"Tsunami bulletin active ({len(tsunami)} event(s))",
                "BMKG flags tsunami potential; bulletins supersede all other signals.",
                [str(_get(e, "id")) for e in tsunami],
                [s["situation_id"] for s in situations if s["kind"] == "TSUNAMI_THREAT"],
                "MODERATE"))
        awas = [v for v in volcanoes
                if (v.get("level") if isinstance(v, dict) else _get(v, "level")) == "AWAS"]
        if awas:
            names = ", ".join((v.get("name", "?") if isinstance(v, dict) else str(_get(v, "name", "?")))
                              for v in awas[:4])
            found.append(_trig(
                "VOLCANO_AWAS", "ALERT", f"Volcano at AWAS: {names}",
                "PVMBG highest alert level; exclusion zones apply per MAGMA guidance.",
                [], [], "MODERATE"))
        return found

    def _anomalies():
        found = []
        sig_seqs = [c for c in sequences
                    if (seq_history.get(c.get("cluster_id")) or {}).get("class") == "SIGNIFICANT"]
        if sig_seqs:
            c = sig_seqs[0]
            h = seq_history.get(c.get("cluster_id")) or {}
            obs = h.get("observed", {})
            found.append(_trig(
                "SIGNIFICANT_HISTORY", "ALERT",
                f"Regional activity SIGNIFICANT vs history ({c.get('cluster_id')})",
                (f"{obs.get('recent_count', 0)} regional events in 7d vs "
                 f"~{obs.get('expected_7d', 0)} expected from "
                 f"{obs.get('baseline_days', 180)}d of recorded BMKG history."),
                list(c.get("member_ids") or []), [],
                h.get("confidence", "LOW")))
        for c in sequences:
            if (c.get("mainshock_magnitude") or 0) >= 7.0 and (c.get("member_count") or 0) >= 3:
                found.append(_trig(
                    "MAJOR_SEQUENCE", "ALERT",
                    f"Major sequence: mainshock M{c.get('mainshock_magnitude')} "
                    f"with {c.get('member_count')} events ({c.get('cluster_id')})",
                    "M7+ mainshock producing aftershocks; further felt events possible but not certain.",
                    list(c.get("member_ids") or []), [],
                    "MODERATE"))
                break
        return found

    def _load():
        found = []
        siaga = [v for v in volcanoes
                 if (v.get("level") if isinstance(v, dict) else _get(v, "level")) == "SIAGA"]
        volc_tec = [s for s in situations
                    if s["kind"] == "VOLCANO_TECTONIC" and s["severity"] in ("HIGH", "CRITICAL")]
        if len(siaga) >= 2 or volc_tec:
            found.append(_trig(
                "SIAGA_CONCENTRATION", "WATCH",
                f"Volcanic concentration: {len(siaga)} at SIAGA"
                + (f", {len(volc_tec)} tectonic co-location(s)" if volc_tec else ""),
                "Multiple elevated volcanoes and/or seismic co-location merit heightened volcano watch.",
                [], [s["situation_id"] for s in volc_tec],
                "LOW"))
        hot_sits = [s for s in situations if s["severity"] in ("HIGH", "CRITICAL")]
        if len(hot_sits) >= 2:
            found.append(_trig(
                "SITUATION_LOAD", "WATCH",
                f"{len(hot_sits)} HIGH+ situations active",
                "Several connected situations compete for attention; coordinate monitoring across them.",
                sorted({m for s in hot_sits for m in s["member_ids"]}),
                [s["situation_id"] for s in hot_sits],
                "LOW"))
        if len(high) >= 4:
            found.append(_trig(
                "SEVERITY_LOAD", "WATCH",
                f"{len(high)} HIGH/CRITICAL events active",
                "Sustained high-priority load; confirm triage order matches the watchlist.",
                [str(_get(e, "id")) for e in high[:10]], [],
                "LOW"))
        expired = (developments or {}).get("expired", []) if isinstance(developments, dict) else []
        if len(expired) >= 3:
            found.append(_trig(
                "EXPIRED_PILEUP", "WATCH",
                f"{len(expired)} alerts past expiry still active",
                "Stale alerts distort the picture; confirm renewal or resolve each one.",
                [str(i.get("event_id")) for i in expired[:10] if isinstance(i, dict)], [],
                "LOW"))
        return found

    for rule, fn in (("bulletins", _bulletins), ("anomalies", _anomalies), ("load", _load)):
        _safe(rule, fn)

    if faults and not triggers:
        # Only report degradation when nothing else fired: a masked bug must
        # never look like a real escalation, nor vanish silently.
        triggers.append(_trig("EVALUATION_FAULT", "WATCH",
                              "Escalation evaluation degraded",
                              "Trigger computation hit unexpected data; treat posture as WATCH until reviewed.",
                              [], [], "LOW"))

    level = "NORMAL"
    for t in triggers:
        if _LEVEL_RANK.get(t["level"], 0) > _LEVEL_RANK[level]:
            level = t["level"]
    posture = {
        "NORMAL": "Maintain routine monitoring cadence.",
        "WATCH": "Heightened monitoring: review triggers below, confirm triage, shorten revisit intervals.",
        "ALERT": "Coordinate response posture now: confirm bulletins, readiness, and exclusion zones; verify field reports before acting.",
    }[level]
    return {
        "level": level,
        "method": METHOD,
        "generated_at": (now if now.tzinfo else now.replace(tzinfo=timezone.utc)).isoformat(),
        "triggers": triggers,
        "posture": posture,
    }
