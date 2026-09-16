"""Executive briefing builder: situation summary + watchlist + recommended actions.

Two-layer design (same rule as event enrichment):
  - Deterministic core: headline, overview bullets, watchlist and recommended
    actions are pure functions of structured data (events, scores, volcano
    levels, expiries). Auditable, works offline, never invents.
  - Optional LLM polish: a single `llm_summary` paragraph via OpenRouter when
    configured; interpretive gloss only, facts stay in the structured fields.
The endpoint never fails because an upstream (MAGMA) is down — gaps degrade
into explicit caveats.
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import desc, select

from app.collectors import magma
from app.models import Event
from app.services import change as change_svc
from app.services import clustering as clustering_svc
from app.services import enrichment
from app.services import escalation as escalation_svc
from app.services import history as history_svc
from app.services import situations as situations_svc

log = logging.getLogger(__name__)

HIGH = ("HIGH", "CRITICAL")
MAX_WATCH = 5
MAX_ACTIONS = 8


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _why_matters(e: Event, cluster: dict | None = None) -> str:
    extra = e.extra or {}
    expo = extra.get("exposure") if isinstance(extra.get("exposure"), dict) else None
    if e.type in ("earthquake", "tsunami_alert"):
        s = f"M{e.magnitude} at {e.depth_km} km depth near {extra.get('region') or 'Indonesia'}"
        if extra.get("felt"):
            s += f"; felt: {extra['felt'][:120]}"
        if e.type == "tsunami_alert":
            s += "; BMKG flags tsunami potential"
        if cluster:
            s += (f"; sequence {cluster['cluster_id']} ({cluster['member_count']} events, "
                  f"mainshock M{cluster['mainshock_magnitude']})")
        if expo:
            s += f"; exposure {expo.get('class', '?')} ({expo.get('confidence', '?')} confidence, heuristic)"
            cities = expo.get("nearest_cities") or []
            if cities:
                s += f"; nearest city {cities[0]['city']} ~{cities[0]['km']} km"
        return s
    if e.type == "severe_weather":
        areas = extra.get("areas") or []
        s = (e.summary or e.title)
        if areas:
            s += f" ({len(areas)} areas listed)"
        if e.expires_at:
            s += f"; expires {_aware(e.expires_at).strftime('%H:%M %Z')}"
        if expo:
            s += f"; exposure {expo.get('class', '?')} (heuristic)"
        return s
    return e.summary or e.title


async def build_briefing(session) -> dict:
    now = datetime.now(timezone.utc)
    day_ago = now - timedelta(hours=24)

    rows = (await session.execute(
        select(Event).where(Event.status == "active").order_by(desc(Event.score)))).scalars().all()
    high = [e for e in rows if e.priority in HIGH]
    new_24h = [e for e in rows if _aware(e.occurred_at) >= day_ago]
    tsunami = [e for e in rows if e.type == "tsunami_alert"]
    weather = [e for e in rows if e.type == "severe_weather"]
    expiring = [e for e in weather
                if e.expires_at and _aware(e.expires_at) <= now + timedelta(hours=6)]

    try:
        volc = await magma.get_volcanoes()
        volcs = volc.get("volcanoes", [])
    except Exception as e:
        log.warning("briefing: volcano data unavailable: %s", e)
        volcs = []
    siaga = [v for v in volcs if v.get("level") in ("SIAGA", "AWAS")]
    waspada_n = sum(1 for v in volcs if v.get("level") == "WASPADA")
    volc_ok = bool(volcs)

    # ---- headline ----
    parts = [f"{len(high)} high-priority event{'s' if len(high) != 1 else ''} active"]
    if tsunami:
        parts.append(f"{len(tsunami)} tsunami-potential")
    if siaga:
        parts.append(f"{len(siaga)} volcano{'es' if len(siaga) != 1 else ''} at "
                     f"{'AWAS' if any(v.get('level') == 'AWAS' for v in siaga) else 'SIAGA'}")
    elif volc_ok:
        parts.append("no volcano above Waspada")
    headline = " · ".join(parts)
    headline = headline[:1].upper() + headline[1:] + "."

    # ---- overview ----
    overview = [
        f"{len(rows)} active events tracked, of which {len(high)} are high/critical priority.",
        f"{len(new_24h)} new event{'s' if len(new_24h) != 1 else ''} in the last 24 hours.",
    ]
    if tsunami:
        overview.append(f"{len(tsunami)} active tsunami-potential event(s) — see watchlist first.")
    else:
        overview.append("No active tsunami-potential events reported by BMKG.")
    if volc_ok:
        names = ", ".join(v["name"] for v in siaga[:6])
        overview.append(
            f"{len(siaga)} volcano(es) at Siaga/Awas{f' ({names})' if names else ''}; "
            f"{waspada_n} at Waspada."
            if siaga else f"Volcano picture calm: {waspada_n} at Waspada, none at Siaga or above.")
    else:
        overview.append("Volcano alert levels currently unavailable (MAGMA unreachable).")
    if weather:
        overview.append(f"{len(weather)} active severe-weather alert(s)"
                        + (f", {len(expiring)} expiring within 6 hours." if expiring else "."))
    else:
        overview.append("No active severe-weather alerts.")

    # ---- developments + sequences (system-derived intelligence) ----
    developments = await change_svc.compute_changes(session, day_ago)
    dc = developments["counts"]
    overview.append(
        f"Changed in 24h: {dc['new']} new, {dc['escalated']} escalated, "
        f"{dc['de_escalated']} de-escalated, {dc['resolved']} resolved, "
        f"{dc['expired']} alert(s) past expiry.")
    sequences = clustering_svc.find_sequences(rows)
    # Historical context per sequence, over up to 400d of regional BMKG record.
    hist_base = [e for e in rows]
    try:
        hist_rows = (await session.execute(
            select(Event).where(Event.type.in_(("earthquake", "tsunami_alert")),
                                Event.occurred_at >= (now - timedelta(days=400)).replace(tzinfo=None))
            .order_by(Event.occurred_at.desc()).limit(2000))).scalars().all()
        hist_base = list(hist_rows)
    except Exception:
        log.warning("briefing: history baseline query failed, using active events only")
    seq_history = {c["cluster_id"]: history_svc.sequence_history(c, hist_base, now)
                   for c in sequences}
    if sequences:
        top = sequences[0]
        th = seq_history.get(top["cluster_id"], {})
        overview.append(
            f"{len(sequences)} earthquake sequence(s) active; largest: "
            f"{top['member_count']} events, mainshock M{top['mainshock_magnitude']} "
            f"({top['mainshock_title'][:80]}); regional behavior "
            f"{th.get('class', 'NORMAL')} vs history.")
    cluster_by_event = {}
    for c in sequences:
        for mid in c["member_ids"]:
            cluster_by_event[mid] = c

    # ---- cross-hazard situations (system-derived, co-occurrence only) ----
    situations = situations_svc.detect_situations(rows, sequences, volcs if volc_ok else None, now)
    if situations:
        kinds = ", ".join(f"{s['kind']} ({s['severity']})" for s in situations[:3])
        overview.append(f"{len(situations)} connected situation(s): {kinds}.")

    # ---- system escalation (max trigger level; corroboration-gated) ----
    escalation = escalation_svc.evaluate_escalation(
        events=rows, sequences=sequences, situations=situations,
        volcanoes=volcs if volc_ok else [], developments=developments,
        seq_history=seq_history, now=now)
    if escalation["level"] != "NORMAL":
        overview.append(
            f"Escalation {escalation['level']}: "
            + "; ".join(t["title"] for t in escalation["triggers"][:3]) + ".")
    headline = (f"{escalation['level']} · {headline}"
                if escalation["level"] != "NORMAL" else headline)

    # ---- watchlist ----
    # Attention ranking: event priority band first (never demoted across
    # bands), then situation severity, then score. Situations influence
    # order transparently; numeric scores are untouched.
    _RANK = {"CRITICAL": 0, "HIGH": 1, "MODERATE": 2, "LOW": 3}
    _SIT_RANK = {"CRITICAL": 0, "HIGH": 1, "MODERATE": 2, "LOW": 3}
    ranked = sorted(rows, key=lambda e: (
        _RANK.get(e.priority, 3),
        _SIT_RANK.get(situations_svc.member_severity(e.id, situations) or "NONE", 4),
        -(e.score or 0)))
    watch_items = []
    for e in ranked[:MAX_WATCH]:
        why = _why_matters(e, cluster_by_event.get(e.id))
        cl = cluster_by_event.get(e.id)
        hist = seq_history.get(cl["cluster_id"]) if cl else None
        if hist and hist.get("class") in ("ELEVATED", "UNUSUAL", "SIGNIFICANT"):
            obs = hist.get("observed", {})
            why += (f"; historically {hist['class'].lower()} for this region "
                    f"({obs.get('recent_count', 0)} in 7d vs ~{obs.get('expected_7d', 0)} expected)")
        watch_items.append({
            "event_id": e.id, "title": e.title, "type": e.type,
            "priority": e.priority, "score": e.score,
            "occurred_at": _aware(e.occurred_at).isoformat(),
            "why": why,
            "cluster": (lambda c: {
                "cluster_id": c["cluster_id"], "member_count": c["member_count"],
                "mainshock_magnitude": c["mainshock_magnitude"],
                "mainshock_id": c["mainshock_id"],
            })(cl) if cl else None,
            "exposure_class": ((e.extra or {}).get("exposure") or {}).get("class")
            if isinstance((e.extra or {}).get("exposure"), dict) else None,
            "history_class": (hist or {}).get("class") if hist else None,
            "situations": [s["situation_id"] for s in
                           situations_svc.situations_for_event(e.id, situations)],
        })
    watchlist = watch_items

    # ---- recommended actions (rule-based, highest urgency first) ----
    actions: list[dict] = []

    def add(action: str, reason: str, urgency: str, event_ids: list[str]):
        if len(actions) < MAX_ACTIONS:
            actions.append({"action": action, "reason": reason,
                            "urgency": urgency, "event_ids": event_ids})

    if escalation["level"] != "NORMAL":
        trig_titles = "; ".join(t["title"] for t in escalation["triggers"][:4])
        trig_events = sorted({eid for t in escalation["triggers"]
                              for eid in t["event_ids"]})[:6]
        add(f"Posture {escalation['level']}: {escalation['posture']}",
            f"Triggers: {trig_titles}. Each trigger cites its evidence; verify bulletins before acting.",
            "immediate" if escalation["level"] == "ALERT" else "soon", trig_events)
    for e in tsunami[:2]:
        region = (e.extra or {}).get("region") or "the affected coast"
        add(f"Confirm the latest BMKG tsunami bulletin and coastal evacuation readiness near {region}.",
            "BMKG flags tsunami potential for this event; bulletins supersede all other signals.",
            "immediate", [e.id])
    for e in [e for e in high if e.type == "earthquake" and (e.score or 0) >= 8][:2]:
        felt = (e.extra or {}).get("felt")
        add("Escalate monitoring: track BMKG updates and the aftershock sequence; verify damage reports"
            + (f" from {felt[:100]}" if felt else "") + " before acting on them.",
            f"M{e.magnitude} at {e.depth_km} km depth scores {e.score}/10 intelligence priority.",
            "immediate", [e.id])
    for e in [e for e in high if e.type == "earthquake" and (e.score or 0) < 8][:2]:
        felt = (e.extra or {}).get("felt")
        if felt:
            add(f"Check shaking-impact reports in {felt[:120]}.",
                "Felt reports indicate populated-area exposure; impact unconfirmed until verified.",
                "soon", [e.id])
    for c in sequences[:2]:
        main_id = c["mainshock_id"]
        main = next((e for e in rows if e.id == main_id), None)
        region = ((main.extra or {}).get("region") if main else None) or "the sequence area"
        urgent = "soon" if (c["mainshock_magnitude"] or 0) < 7 else "immediate"
        h = seq_history.get(c["cluster_id"], {})
        reason = ("Clustered earthquakes indicate a developing situation; further felt "
                  "aftershocks are possible but not certain.")
        if h.get("class") in ("UNUSUAL", "SIGNIFICANT"):
            obs = h.get("observed", {})
            reason += (f" This pace is {h['class'].lower()} for the region "
                       f"({obs.get('recent_count', 0)} in 7d vs ~{obs.get('expected_7d', 0)} "
                       f"expected from {obs.get('baseline_days', 180)}d of BMKG history).")
            urgent = "immediate" if h["class"] == "SIGNIFICANT" else urgent
        add(f"Track aftershock sequence {c['cluster_id']} near {region}: "
            f"{c['member_count']} events, mainshock M{c['mainshock_magnitude']}.",
            reason, urgent, [main_id])
    for it in developments["expired"][:2]:
        add(f"Reassess past-expiry alert: {it['title']}.",
            "The BMKG validity window has passed with the alert still active; confirm renewal or resolve it.",
            "soon", [it["event_id"]])
    for s in situations[:2]:
        sev_urg = {"CRITICAL": "immediate", "HIGH": "soon"}.get(s["severity"], "routine")
        add(f"Coordinate around {s['title']} ({s['kind']}, {len(s['member_ids'])} linked).",
            s["interpretation"] + " Co-occurrence only — no causal link established.",
            sev_urg, [mid for mid in s["member_ids"]][:4])
    for e in [e for e in high if e.type == "severe_weather"][:2]:
        exp = f" Reassess at/after expiry ({_aware(e.expires_at).strftime('%d %b %H:%M %Z')})." if e.expires_at else ""
        add(f"Maintain flood-response posture for {e.title}.{exp}",
            "BMKG nowcast warns of heavy rain, lightning, strong wind and local flooding.",
            "soon", [e.id])
    for v in siaga[:4]:
        lvl = v.get("level", "SIAGA")
        add(f"Enforce the PVMBG exclusion zone around {v['name']} ({lvl}); check its MAGMA report.",
            f"PVMBG raised {v['name']} to {lvl}; follow the linked official recommendation.",
            "immediate" if lvl == "AWAS" else "soon", [])
    if waspada_n:
        add(f"Routine watch on {waspada_n} volcano(es) at Waspada; review on any level change.",
            "Elevated but stable per PVMBG; no action beyond monitoring cadence.",
            "routine", [])
    if not actions:
        add("Maintain routine monitoring cadence; no high-priority events active.",
            "Nothing currently meets the escalation thresholds.",
            "routine", [])

    caveats = [
        "Intelligence priority scores guide attention; they are not validated risk estimates.",
        "AI-generated text is interpretive. Facts come from BMKG records and PVMBG levels.",
        "Sequence clusters, exposure classes, history classes and situations are "
        "system-derived heuristics, not BMKG statements; situations report "
        "co-occurrence, never causality.",
    ]
    if not volc_ok:
        caveats.append("Volcano levels could not be refreshed; act on last confirmed PVMBG status.")

    # ---- optional LLM executive note (grounded gloss only) ----
    llm_summary, llm_model, llm_status = None, None, "off"
    try:
        from app.core.config import settings
        if settings.openrouter_api_key:
            evidence = enrichment.build_briefing_evidence(
                headline, overview, rows,
                counts={"active": len(rows), "high": len(high),
                        "new_24h": len(new_24h), "tsunami": len(tsunami),
                        "weather": len(weather)},
                volcano={"available": volc_ok,
                         "siaga": [v.get("name", "") for v in siaga],
                         "waspada_count": waspada_n},
                developments=developments,
                sequences=[{**c, "history": seq_history.get(c["cluster_id"])}
                           for c in sequences],
                situations=[{
                    "situation_id": s["situation_id"], "kind": s["kind"],
                    "title": s["title"], "severity": s["severity"],
                    "member_ids": s["member_ids"],
                    "interpretation": s["interpretation"],
                } for s in situations],
                escalation={
                    "level": escalation["level"],
                    "posture": escalation["posture"],
                    "triggers": [{
                        "trigger_id": t["trigger_id"], "rule": t["rule"],
                        "level": t["level"], "title": t["title"],
                        "why": t["why"], "confidence": t["confidence"],
                    } for t in escalation["triggers"]],
                },
            )
            llm_summary, llm_status = await enrichment.maybe_llm_note(evidence)
            llm_model = settings.openrouter_model if llm_summary else None
            if llm_status == "misconfigured":
                caveats.append("AI note unavailable: OPENROUTER_MODEL is not set to a real model id.")
    except Exception as e:
        log.warning("briefing LLM note failed: %s", e)
        llm_status = "error"

    return {
        "generated_at": now.isoformat(),
        "headline": headline,
        "overview": overview,
        "watchlist": watchlist,
        "recommended_actions": actions,
        "developments": developments,
        "escalation": escalation,
        "sequences": [{
            "cluster_id": c["cluster_id"], "method": c["method"],
            "member_ids": c["member_ids"], "member_count": c["member_count"],
            "mainshock_id": c["mainshock_id"],
            "mainshock_magnitude": c["mainshock_magnitude"],
            "mainshock_title": c["mainshock_title"],
            "started_at": _aware(c["started_at"]).isoformat(),
            "latest_at": _aware(c["latest_at"]).isoformat(),
            "centroid": c["centroid"],
            "history": seq_history.get(c["cluster_id"]),
            "situation_ids": [s["situation_id"] for s in situations
                              if c["mainshock_id"] in s["member_ids"]
                              or any(m in s["member_ids"] for m in c["member_ids"])],
        } for c in sequences],
        "situations": situations,
        "llm_summary": llm_summary,
        "llm_model": llm_model,
        "llm_status": llm_status,
        "caveats": caveats,
    }
