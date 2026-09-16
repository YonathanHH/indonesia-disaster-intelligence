"""HTTP API layer (thin — domain logic lives in services/)."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.db import get_session
from app.models import Event, EventHistory, IngestState, Observation
from app.schemas import AnalyticsOut, BriefingOut, ChangesOut, ClusterOut, EscalationOut, EventDetailOut, EventListOut, FeedItem, OverviewStats, SituationOut
from app.services import analytics as analytics_svc
from app.services import briefing as briefing_svc
from app.services import change as change_svc
from app.services import clustering as clustering_svc
from app.services import history as history_svc
from app.services import ingest as ingest_svc
from app.services import overlays as overlays_svc
from app.services import situations as situations_svc

router = APIRouter()


@router.get("/health")
async def health():
    return {"status": "ok"}


@router.get("/status", response_model=OverviewStats)
async def status(session: AsyncSession = Depends(get_session)):
    now = datetime.now(timezone.utc)
    active = (await session.execute(
        select(func.count()).select_from(Event).where(Event.status == "active"))).scalar() or 0
    high = (await session.execute(
        select(func.count()).select_from(Event).where(
            Event.status == "active", Event.priority.in_(["HIGH", "CRITICAL"])))).scalar() or 0
    day_ago = now - timedelta(hours=24)
    quakes = (await session.execute(
        select(func.count()).select_from(Event).where(
            Event.type.in_(["earthquake", "tsunami_alert"]), Event.occurred_at >= day_ago))).scalar() or 0
    wx = (await session.execute(
        select(func.count()).select_from(Event).where(
            Event.type == "severe_weather", Event.status == "active"))).scalar() or 0
    tsu = (await session.execute(
        select(func.count()).select_from(Event).where(
            Event.type == "tsunami_alert", Event.status == "active"))).scalar() or 0
    last_obs = (await session.execute(select(func.max(Observation.created_at)))).scalar()
    collectors = {}
    for row in (await session.execute(select(IngestState))).scalars().all():
        collectors[row.collector] = {"last_run_at": row.last_run_at, "last_ok_at": row.last_ok_at,
                                     "last_error": row.last_error, "items_fetched": row.items_fetched}
    return OverviewStats(active_events=active, high_priority=high, quakes_24h=quakes,
                         active_weather_alerts=wx, tsunami_alerts=tsu,
                         last_update=last_obs, collectors=collectors)


@router.get("/events", response_model=list[EventListOut])
async def list_events(
    session: AsyncSession = Depends(get_session),
    type: str | None = Query(default=None),
    priority: str | None = Query(default=None),
    q: str | None = Query(default=None),
    status_: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, le=500),
    since: datetime | None = None,
):
    stmt = select(Event).order_by(desc(Event.occurred_at)).limit(limit)
    if type:
        stmt = stmt.where(Event.type == type)
    if priority:
        stmt = stmt.where(Event.priority == priority)
    if status_:
        stmt = stmt.where(Event.status == status_)
    if since:
        stmt = stmt.where(Event.occurred_at >= since)
    if q:
        stmt = stmt.where(Event.title.ilike(f"%{q}%"))
    rows = (await session.execute(stmt)).scalars().all()
    return rows


@router.get("/events/{event_id}", response_model=EventDetailOut)
async def event_detail(event_id: str, session: AsyncSession = Depends(get_session)):
    e = (await session.execute(
        select(Event).where(Event.id == event_id)
        .options(selectinload(Event.observations), selectinload(Event.history)))).scalar_one_or_none()
    if e is None:
        raise HTTPException(404, "event not found")
    obs = sorted(e.observations, key=lambda o: o.observed_at, reverse=True)
    hist = [{"ts": h.ts, "kind": h.kind, "message": h.message, "payload": h.payload}
            for h in sorted(e.history, key=lambda h: h.ts)]
    from app.schemas import EventDetailOut as _Detail, ObservationOut as _Obs
    base = EventListOut.model_validate(e).model_dump()
    cluster = None
    history_context = None
    if e.type in ("earthquake", "tsunami_alert"):
        recent = (await session.execute(
            select(Event).where(Event.type.in_(("earthquake", "tsunami_alert")))
            .order_by(desc(Event.occurred_at)).limit(200))).scalars().all()
        cluster = clustering_svc.cluster_for_event(
            e.id, clustering_svc.find_sequences(recent))
        try:
            from datetime import timedelta as _td
            hist_rows = (await session.execute(
                select(Event).where(Event.type.in_(("earthquake", "tsunami_alert")),
                                    Event.occurred_at >= (
                                        datetime.now(timezone.utc) - _td(days=400)).replace(tzinfo=None))
                .order_by(desc(Event.occurred_at)).limit(2000))).scalars().all()
            history_context = history_svc.assess_history(
                e.latitude, e.longitude, e.magnitude, hist_rows)
        except Exception:
            history_context = None
    exposure = (e.extra or {}).get("exposure") if isinstance(e.extra, dict) else None
    # DB-only situations in the detail path (no network I/O here; volcano
    # rules surface in /briefing and /situations).
    actives = (await session.execute(
        select(Event).where(Event.status == "active")
        .order_by(desc(Event.occurred_at)).limit(500))).scalars().all()
    seqs = clustering_svc.find_sequences(actives)
    my_situations = situations_svc.situations_for_event(
        e.id, situations_svc.detect_situations(actives, seqs, None))
    return _Detail(**base, score_breakdown=e.score_breakdown, ai_assessment=e.ai_assessment,
                   extra=e.extra,
                   observations=[_Obs.model_validate(o) for o in obs], history=hist,
                   cluster=cluster, exposure=exposure, history_context=history_context,
                   situations=my_situations)


@router.get("/feed", response_model=list[FeedItem])
async def feed(session: AsyncSession = Depends(get_session), limit: int = Query(default=50, le=200)):
    """Chronological developments: event creations + observations, newest first."""
    obs_rows = (await session.execute(
        select(Observation).order_by(desc(Observation.observed_at)).limit(limit)
    )).scalars().all()
    items: list[FeedItem] = []
    seen_events: set[str] = set()
    for o in obs_rows:
        if o.kind == "social_post":
            kind = "social_signal"
        elif o.event_id and o.event_id not in seen_events:
            kind = "new_event"
            seen_events.add(o.event_id)
        else:
            kind = "observation"
        items.append(FeedItem(kind="social_signal" if o.kind == "social_post" else kind,
                              ts=o.observed_at, event_id=o.event_id,
                              title=o.text[:160] if o.text else o.kind,
                              detail=f"{o.source}/{o.kind}"))
    return items


@router.post("/ingest/run")
async def ingest_run(session: AsyncSession = Depends(get_session)):
    summary = await ingest_svc.run_ingest(session)
    return summary


@router.post("/events/{event_id}/resolve")
async def resolve_event(event_id: str, session: AsyncSession = Depends(get_session)):
    e = (await session.execute(select(Event).where(Event.id == event_id))).scalar_one_or_none()
    if e is None:
        raise HTTPException(404, "event not found")
    e.status = "resolved"
    e.updated_at = datetime.now(timezone.utc)
    session.add(EventHistory(event_id=e.id, kind="resolved", message="Operator marked event resolved"))
    await session.commit()
    return {"ok": True}


@router.get("/briefing", response_model=BriefingOut)
async def briefing(session: AsyncSession = Depends(get_session)):
    """Executive briefing: deterministic situation summary + watchlist +
    recommended actions, with optional LLM polish when configured."""
    return await briefing_svc.build_briefing(session)


@router.get("/changes", response_model=ChangesOut)
async def changes(since_hours: float = Query(default=24.0, gt=0, le=24 * 30),
                  session: AsyncSession = Depends(get_session)):
    """What Changed? Situation delta vs the lookback window (default 24h).

    Stateless: derived from the append-only EventHistory log + timestamps.
    Kinds: new, escalated, de-escalated, resolved, expired, growing_sequences.
    """
    from datetime import timedelta
    since = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    return await change_svc.compute_changes(session, since)


@router.get("/clusters", response_model=list[ClusterOut])
async def clusters(session: AsyncSession = Depends(get_session)):
    """Earthquake sequence clusters over recent quake-type events.

    Deterministic single-link chaining (|dt|<=72h, <=120km); no storage.
    Each cluster carries historical context vs up to 400d of regional record.
    """
    from datetime import timedelta as _td
    rows = (await session.execute(
        select(Event).where(Event.type.in_(("earthquake", "tsunami_alert")))
        .order_by(desc(Event.occurred_at)).limit(500))).scalars().all()
    found = clustering_svc.find_sequences(rows)
    try:
        hist_rows = (await session.execute(
            select(Event).where(Event.type.in_(("earthquake", "tsunami_alert")),
                                Event.occurred_at >= (
                                    datetime.now(timezone.utc) - _td(days=400)).replace(tzinfo=None))
            .order_by(desc(Event.occurred_at)).limit(2000))).scalars().all()
    except Exception:
        hist_rows = rows
    actives = [e for e in rows if e.status == "active"]
    seqs = clustering_svc.find_sequences(actives)
    sit_by_member: dict[str, list[str]] = {}
    for s in situations_svc.detect_situations(actives, seqs, None):
        for mid in s["member_ids"]:
            sit_by_member.setdefault(mid, []).append(s["situation_id"])
    out = []
    for c in found:
        out.append({**c, "history": history_svc.sequence_history(c, hist_rows),
                    "situation_ids": sit_by_member.get(c["mainshock_id"], [])})
    return out


@router.get("/situations", response_model=list[SituationOut])
async def situations(session: AsyncSession = Depends(get_session)):
    """Connected cross-hazard situations over active events.

    Deterministic co-occurrence rules (situation-v1); volcano rules use live
    PVMBG levels when reachable, otherwise DB-only rules still apply.
    Co-occurrence is reported, causality never claimed.
    """
    from app.collectors import magma
    actives = (await session.execute(
        select(Event).where(Event.status == "active")
        .order_by(desc(Event.occurred_at)).limit(500))).scalars().all()
    seqs = clustering_svc.find_sequences(actives)
    try:
        volcs = (await magma.get_volcanoes()).get("volcanoes", [])
    except Exception:
        volcs = None
    return situations_svc.detect_situations(actives, seqs, volcs)


@router.get("/escalation", response_model=EscalationOut)
async def escalation(session: AsyncSession = Depends(get_session)):
    """System escalation level (NORMAL/WATCH/ALERT) with evidence-backed triggers.

    Corroboration-gated: bulletins/AWAS fire alone; everything else needs
    converging signals. Shares the evaluator with the Executive Briefing.
    """
    from datetime import timedelta as _td
    from app.collectors import magma
    now = datetime.now(timezone.utc)
    actives = (await session.execute(
        select(Event).where(Event.status == "active")
        .order_by(desc(Event.score)).limit(500))).scalars().all()
    seqs = clustering_svc.find_sequences(actives)
    try:
        hist_rows = (await session.execute(
            select(Event).where(Event.type.in_(("earthquake", "tsunami_alert")),
                                Event.occurred_at >= (now - _td(days=400)).replace(tzinfo=None))
            .order_by(desc(Event.occurred_at)).limit(2000))).scalars().all()
    except Exception:
        hist_rows = actives
    seq_history = {c["cluster_id"]: history_svc.sequence_history(c, hist_rows, now)
                   for c in seqs}
    try:
        volcs = (await magma.get_volcanoes()).get("volcanoes", [])
    except Exception:
        volcs = []
    sits = situations_svc.detect_situations(actives, seqs, volcs or None, now)
    day_ago = now - _td(hours=24)
    try:
        developments = await change_svc.compute_changes(session, day_ago)
    except Exception:
        developments = {}
    from app.services import escalation as escalation_svc
    return escalation_svc.evaluate_escalation(
        events=actives, sequences=seqs, situations=sits, volcanoes=volcs,
        developments=developments, seq_history=seq_history, now=now)


@router.get("/analytics", response_model=AnalyticsOut)
async def analytics(refresh: bool = True, session: AsyncSession = Depends(get_session)):
    """OLAP analytics over a DuckDB sidecar mirror (disposable cache).

    Primary store stays Postgres/SQLite; `refresh=true` (default) re-mirrors
    `events` into the DuckDB file before aggregating. Pass
    `refresh=false` to query the last snapshot without a re-mirror.
    """
    return await analytics_svc.get_analytics(session, refresh=refresh)


@router.get("/overlays")
async def overlay_index():
    """Available geological map layers with attribution + freshness."""
    return await overlays_svc.layer_index()


@router.get("/overlays/volcanoes")
async def overlay_volcanoes():
    return await overlays_svc.volcanoes_geojson()


@router.get("/overlays/plates")
async def overlay_plates():
    return await overlays_svc.plates_geojson()


@router.get("/overlays/faults")
async def overlay_faults():
    try:
        return await overlays_svc.faults_geojson()
    except overlays_svc.OverlayUnavailable as e:
        raise HTTPException(404, str(e))
