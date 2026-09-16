"""Ingest orchestration: idempotent persist + correlate + score + history.

Idempotency: Observation.external_id is UNIQUE. Re-running a collector
re-fetches the same rows -> IntegrityError on insert -> skipped, and the
existing event is NOT duplicated (match_quake finds it anyway).
Each ingest updates IngestState for /status visibility.
"""
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.collectors import bmkg_cap, bmkg_quake
from app.models import Event, EventHistory, IngestState, Observation
from app.services import correlation, enrichment, scoring

log = logging.getLogger(__name__)


def to_jsonable(obj):
    """Recursively convert datetimes etc. so raw/structured payloads are JSON-serializable."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    return obj


async def _record_state(session, collector: str, ok: bool, n: int, err: str | None = None):
    st = (await session.execute(select(IngestState).where(IngestState.collector == collector))).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if st is None:
        st = IngestState(collector=collector)
        session.add(st)
    st.last_run_at = now
    st.items_fetched = n
    if ok:
        st.last_ok_at = now
        st.last_error = None
    else:
        st.last_error = (err or "unknown")[:2000]


async def _save_observation(session, norm: dict) -> Observation | None:
    """Insert unless external_id exists. Returns None on duplicate.

    Uses a SAVEPOINT so a duplicate-key rollback only undoes this insert,
    never the rest of the batch (a plain session.rollback() here would
    discard all previously flushed events/observations in the run).
    """
    existing = (await session.execute(
        select(Observation.id).where(Observation.external_id == norm["external_id"]))).scalar_one_or_none()
    if existing is not None:
        return None
    obs = Observation(
        kind=norm["kind"], source=norm["source"], external_id=norm["external_id"],
        author=norm.get("author"), text=norm.get("text"), url=norm.get("url"),
        observed_at=norm["observed_at"], structured=to_jsonable(norm.get("structured")),
        raw=to_jsonable(norm.get("raw")),
    )
    session.add(obs)
    try:
        async with session.begin_nested():
            await session.flush()
        return obs
    except IntegrityError:
        return None


async def _apply_intel_modifiers(session, event, pure_score: float, pure_breakdown: dict) -> list[str]:
    """System-derived attention modifiers, capped at +1.0 over the pure score.

    Recomputes the conservative exposure assessment (stored namespaced at
    extra["exposure"]) and the historical regional context (stored at
    extra["history"]), adds labelled breakdown keys (exposure_bonus /
    sequence_bonus / history_bonus, 0.5 each, total capped with proportional
    scaling so components always sum to the applied delta), re-bands
    priority. Returns human descriptions for history payloads. Pure BMKG
    facts untouched; pure scoring functions untouched.
    """
    from datetime import timedelta

    from app.services import clustering
    from app.services import exposure as exposure_svc
    from app.services import history as history_svc
    from app.services.scoring import band

    applied: list[str] = []
    try:
        event.extra = {**(event.extra or {}), "exposure": exposure_svc.assess_exposure(event)}
    except Exception:
        log.exception("exposure assessment failed")
        return applied
    bonuses: dict[str, tuple[float, str]] = {}
    try:
        b, reason = exposure_svc.exposure_bonus(event.extra["exposure"], event.type)
        if b:
            bonuses["exposure_bonus"] = (b, f"exposure: {reason}")
    except Exception:
        log.exception("exposure bonus check failed")
    if event.type in ("earthquake", "tsunami_alert"):
        try:
            recent = (await session.execute(
                select(Event).where(Event.type.in_(("earthquake", "tsunami_alert")),
                                    Event.status == "active")
                .order_by(Event.occurred_at.desc()).limit(200))).scalars().all()
            n = clustering.companion_count(
                event.latitude, event.longitude, event.occurred_at, recent,
                exclude_id=event.id)
            if n >= 2:
                bonuses["sequence_bonus"] = (0.5, f"{n} nearby quakes in 72h")
        except Exception:
            log.exception("sequence companion check failed")
        try:
            window_lo = event.occurred_at - timedelta(days=400)
            if window_lo.tzinfo is not None:
                # DB stores naive datetimes on SQLite; compare naive.
                window_lo = window_lo.replace(tzinfo=None)
            hist_rows = (await session.execute(
                select(Event).where(Event.type.in_(("earthquake", "tsunami_alert")),
                                    Event.occurred_at >= window_lo)
                .order_by(Event.occurred_at.desc()).limit(2000))).scalars().all()
            # Anchor at event time (not wall-clock): the context describes
            # whether this event was unusual when it happened. Identical for
            # live ingest; correct for backfills.
            ctx = history_svc.assess_history(
                event.latitude, event.longitude, event.magnitude, hist_rows,
                now=event.occurred_at)
            event.extra = {**(event.extra or {}), "history": ctx}
            b, reason = history_svc.history_bonus(ctx)
            if b:
                bonuses["history_bonus"] = (b, f"history: {reason}")
        except Exception:
            log.exception("history assessment failed")
    raw_total = round(sum(v for v, _ in bonuses.values()), 2)
    if raw_total <= 0:
        return applied
    cap = 1.0
    scaled = dict(bonuses)
    if raw_total > cap:
        factor = cap / raw_total
        scaled = {k: (round(v * factor, 2), r) for k, (v, r) in bonuses.items()}
        drift = round(cap - sum(v for v, _ in scaled.values()), 2)
        if drift:
            biggest = max(scaled, key=lambda k: scaled[k][0])
            v, r = scaled[biggest]
            scaled[biggest] = (round(v + drift, 2), r)
    total = round(sum(v for v, _ in scaled.values()), 2)
    score = min(10.0, round(pure_score + total, 2))
    comps = dict((pure_breakdown or {}).get("components", {}))
    for k, (v, reason) in scaled.items():
        comps[k] = v
        applied.append(f"{k} +{v} ({reason})")
    event.score = score
    event.score_breakdown = {**(pure_breakdown or {}), "components": comps, "priority": band(score)}
    event.priority = event.score_breakdown["priority"]
    return applied


async def ingest_quake_observation(session, norm: dict) -> Event | None:
    obs = await _save_observation(session, norm)
    s = norm["structured"]
    lat, lon, mag = s["latitude"], s["longitude"], s["magnitude"]
    event = await correlation.match_quake(session, norm["observed_at"], lat, lon, mag)
    if event is None:
        score, breakdown = scoring.score_earthquake(mag, s.get("depth_km"), s.get("felt"), bool(s.get("tsunami_potential")))
        event = Event(
            type="tsunami_alert" if s.get("tsunami_potential") else "earthquake",
            title=f"M{mag:.1f} — {s.get('region') or 'Indonesia'}",
            occurred_at=norm["observed_at"], latitude=lat, longitude=lon,
            depth_km=s.get("depth_km"), magnitude=mag,
            priority=breakdown["priority"], score=score, score_breakdown=breakdown,
            summary=enrichment.event_summary("earthquake", s),
            ai_assessment=enrichment.template_assessment("earthquake", s, score, breakdown["priority"]),
            extra={"region": s.get("region"), "felt": s.get("felt"),
                   "potensi_text": s.get("potensi_text"), "shakemap_url": s.get("shakemap_url")},
            source_count=0,
        )
        session.add(event)
        await session.flush()
        mods = await _apply_intel_modifiers(session, event, score, breakdown)
        if mods:
            event.ai_assessment = enrichment.template_assessment(
                "earthquake", s, event.score, event.priority)
        session.add(EventHistory(event_id=event.id, kind="created",
                                 message=f"Canonical event created from {norm['kind']} observation",
                                 payload={"external_id": norm["external_id"],
                                          **({"intel_modifiers": mods} if mods else {})}))
    if obs is not None:
        obs.event_id = event.id
        event.source_count = (event.source_count or 0) + 1
        event.updated_at = datetime.now(timezone.utc)
        session.add(EventHistory(event_id=event.id, kind="observation",
                                 message=f"Correlated {norm['kind']} observation {norm['external_id']}",
                                 payload={"observation_id": obs.id}))
    # Merge enrichment from ANY feed row for this BMKG event — including rows
    # that deduplicate to an existing observation (e.g. the felt feed carries
    # Dirasakan areas that the M5+ feed row for the same quake lacks).
    if s.get("felt") and s["felt"] not in ((event.extra or {}).get("felt") or ""):
        before = {"score": event.score, "priority": event.priority}
        merged_felt = "; ".join(filter(None, {(event.extra or {}).get("felt") or "", s["felt"]}))
        event.extra = {**(event.extra or {}), "felt": merged_felt}
        score, breakdown = scoring.score_earthquake(
            event.magnitude, event.depth_km, merged_felt,
            bool((event.extra or {}).get("tsunami_flag") or s.get("tsunami_potential")))
        event.score, event.score_breakdown, event.priority = score, breakdown, breakdown["priority"]
        mods = await _apply_intel_modifiers(session, event, score, breakdown)
        event.ai_assessment = enrichment.template_assessment(
            "earthquake",
            {"magnitude": event.magnitude, "depth_km": event.depth_km,
             "region": (event.extra or {}).get("region"), "felt": merged_felt,
             "tsunami_potential": s.get("tsunami_potential")}, event.score, event.priority)
        after = {"score": event.score, "priority": event.priority}
        from app.services.change import BAND_RANK
        if BAND_RANK.get(after["priority"], 0) != BAND_RANK.get(before["priority"], 0):
            session.add(EventHistory(event_id=event.id, kind="rescore",
                                     message=f"Priority {before['priority']} → {after['priority']} on felt merge",
                                     payload={"before": before, "after": after,
                                              "reason": f"felt reports: {merged_felt[:160]}",
                                              "external_id": norm["external_id"],
                                              **({"intel_modifiers": mods} if mods else {})}))
        else:
            session.add(EventHistory(event_id=event.id, kind="observation",
                                     message=f"Enriched felt data from {norm['kind']} row",
                                     payload={"external_id": norm["external_id"],
                                              **({"intel_modifiers": mods} if mods else {})}))
    if obs is not None:
        await session.flush()
    return event


async def ingest_weather_observation(session, norm: dict) -> Event | None:
    s = norm["structured"]
    if s.get("latitude") is None:  # no geometry — keep observation, skip event
        await _save_observation(session, norm)
        return None
    from dateutil import parser as dateparser
    eff = dateparser.isoparse(s["effective"])
    exp = dateparser.isoparse(s["expires"])
    event = await correlation.match_weather(session, norm["text"] or "", eff, exp)
    obs = await _save_observation(session, norm)
    if event is None:
        score, breakdown = scoring.score_weather(
            s.get("severity"), s.get("urgency"), s.get("certainty"),
            s.get("area_count", 0), s.get("headline", ""), s.get("description", ""))
        event = Event(
            type="severe_weather", title=s.get("headline") or norm["text"] or "Weather alert",
            occurred_at=eff, latitude=s["latitude"], longitude=s["longitude"],
            priority=breakdown["priority"], score=score, score_breakdown=breakdown,
            summary=enrichment.event_summary("severe_weather", s),
            ai_assessment=enrichment.template_assessment("severe_weather", s, score, breakdown["priority"]),
            expires_at=exp,
            extra={"areas": s.get("areas", [])[:50], "polygons": (norm.get("raw") or {}).get("polygons", [])[:10],
                   "severity": s.get("severity"), "urgency": s.get("urgency"),
                   "certainty": s.get("certainty"), "web": s.get("web")},
            source_count=0,
        )
        session.add(event)
        await session.flush()
        mods = await _apply_intel_modifiers(session, event, score, breakdown)
        if mods:
            event.ai_assessment = enrichment.template_assessment(
                "severe_weather", s, event.score, event.priority)
        session.add(EventHistory(event_id=event.id, kind="created",
                                 message=f"Weather alert created: {event.title}",
                                 payload={"external_id": norm["external_id"],
                                          **({"intel_modifiers": mods} if mods else {})}))
    if obs is not None:
        obs.event_id = event.id
        event.source_count = (event.source_count or 0) + 1
        event.updated_at = datetime.now(timezone.utc)
        session.add(EventHistory(event_id=event.id, kind="observation",
                                 message=f"Correlated CAP observation {norm['external_id']}",
                                 payload={"observation_id": obs.id}))
        await session.flush()
    return event


async def run_ingest(session) -> dict:
    """Run all collectors. Returns summary counts. Commits once at end."""
    summary: dict = {"quakes": 0, "weather": 0, "errors": []}
    try:
        quakes = await bmkg_quake.fetch_all_quakes()
        for norm in quakes:
            try:
                await ingest_quake_observation(session, norm)
                summary["quakes"] += 1
            except Exception as e:
                log.exception("quake ingest item failed")
                summary["errors"].append(str(e)[:300])
        await _record_state(session, "bmkg_quake", True, len(quakes))
    except Exception as e:
        log.exception("quake collector failed")
        await _record_state(session, "bmkg_quake", False, 0, str(e))
        summary["errors"].append(f"bmkg_quake: {e}"[:300])
    try:
        weather = await bmkg_cap.fetch_nowcast()
        for norm in weather:
            try:
                await ingest_weather_observation(session, norm)
                summary["weather"] += 1
            except Exception as e:
                log.exception("weather ingest item failed")
                summary["errors"].append(str(e)[:300])
        await _record_state(session, "bmkg_cap", True, len(weather))
    except Exception as e:
        log.exception("cap collector failed")
        await _record_state(session, "bmkg_cap", False, 0, str(e))
        summary["errors"].append(f"bmkg_cap: {e}"[:300])
    await session.commit()
    return summary
