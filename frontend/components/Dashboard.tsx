"use client";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Map from "../components/Map";
import TopBar from "../components/TopBar";
import StatusStrip, { type KpiKey } from "../components/StatusStrip";
import EventList, { type SortMode } from "../components/EventList";
import FeedList from "../components/FeedList";
import EventDetail, { FeedsBar } from "../components/EventDetail";
import BriefingPanel from "../components/BriefingPanel";
import { api } from "../lib/api";
import { fmtClock } from "../lib/format";
import type {
  Analytics,
  BMKGEvent,
  Briefing,
  ClusterSequence,
  Developments,
  Escalation,
  EventDetail as EventDetailT,
  FeedItem,
  OverlayLayer,
  Overview,
  VolcanoFeature,
} from "../lib/types";

export default function Dashboard() {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [events, setEvents] = useState<BMKGEvent[]>([]);
  const [feed, setFeed] = useState<FeedItem[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [hoverId, setHoverId] = useState<string | null>(null);
  const [detail, setDetail] = useState<EventDetailT | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [typeF, setTypeF] = useState("");
  const [prioF, setPrioF] = useState("");
  const [q, setQ] = useState("");
  const [qDeb, setQDeb] = useState(""); // debounced search -> fewer refetches
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [layers, setLayers] = useState<OverlayLayer[]>([]);
  const [showVolcanoes, setShowVolcanoes] = useState(true);
  const [showPlates, setShowPlates] = useState(false);
  const [volcanoes, setVolcanoes] = useState<VolcanoFeature[] | null>(null);
  const [plates, setPlates] = useState<{ type: string; features: unknown[] } | null>(null);
  const [briefingOpen, setBriefingOpen] = useState(false);
  const [briefing, setBriefing] = useState<Briefing | null>(null);
  const [briefingLoading, setBriefingLoading] = useState(false);
  const [briefingErr, setBriefingErr] = useState<string | null>(null);
  const [escalation, setEscalation] = useState<Escalation | null>(null);
  const [changes, setChanges] = useState<Developments | null>(null);
  const [changesSince, setChangesSince] = useState<number | null>(null);
  const [changesDismissed, setChangesDismissed] = useState(false);
  const [clusters, setClusters] = useState<ClusterSequence[]>([]);
  const [showSequences, setShowSequences] = useState(true);
  const [analytics, setAnalytics] = useState<Analytics | null>(null);
  const [sortMode, setSortMode] = useState<SortMode>("score");
  const [kpi, setKpi] = useState<KpiKey | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [resolving, setResolving] = useState(false);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const changesSinceRef = useRef<number | null>(null);
  const analyticsLoadRef = useRef<Promise<void> | null>(null);
  const refreshedRef = useRef(false);

  const toggleKpi = useCallback(
    (key: KpiKey) => setKpi((prev) => (prev === key ? null : key)),
    []
  );

  const clearFilters = useCallback(() => {
    setKpi(null);
    setTypeF("");
    setPrioF("");
    setQ("");
    setQDeb("");
  }, []);

  // debounce search input -> qDeb (server query)
  useEffect(() => {
    const t = setTimeout(() => setQDeb(q), 350);
    return () => clearTimeout(t);
  }, [q]);

  // auto-dismiss operator toast
  const flash = useCallback((text: string) => {
    setMsg(text);
    if (toastTimer.current) clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setMsg(null), 12000);
  }, []);

  const loadBriefing = useCallback(async () => {
    setBriefingLoading(true);
    setBriefingErr(null);
    try {
      const b = await api.briefing();
      setBriefing(b);
      if (b.escalation) setEscalation(b.escalation);
    } catch (e) {
      setBriefing(null);
      setBriefingErr(e instanceof Error ? e.message : "Briefing unavailable. Is the backend running?");
    } finally {
      setBriefingLoading(false);
    }
  }, []);

  const openBriefing = useCallback(() => {
    setBriefingOpen(true);
    loadBriefing();
  }, [loadBriefing]);

  const loadEscalation = useCallback(async () => {
    try {
      setEscalation(await api.escalation());
    } catch {
      /* keep the last known posture */
    }
  }, []);

  const loadClusters = useCallback(async () => {
    try {
      setClusters(await api.clusters());
    } catch {
      /* the sequence layer simply stays empty */
    }
  }, []);

  // One analytics request at a time per page: a refresh recomputes the aggregates
  // from the event table, and a failed read must not immediately retry while
  // another tab may already be triggering the same recompute.
  const loadAnalytics = useCallback(async (refresh = false) => {
    if (analyticsLoadRef.current) {
      if (!refresh) return analyticsLoadRef.current;
      await analyticsLoadRef.current;
    }
    const run = async () => {
      try {
        let a = await api.analytics(refresh);
        if (!refresh && a.daily_counts_14d.length === 0) {
          await new Promise((r) => setTimeout(r, 1200));
          a = await api.analytics(false);
          if (a.daily_counts_14d.length === 0) a = await api.analytics(true);
        }
        setAnalytics(a);
      } catch {
        /* the sparkline stays hidden */
      }
    };
    const p = run();
    analyticsLoadRef.current = p;
    try {
      await p;
    } finally {
      if (analyticsLoadRef.current === p) analyticsLoadRef.current = null;
    }
  }, []);

  const loadChanges = useCallback(async () => {
    const since = changesSinceRef.current;
    if (!since) return;
    try {
      setChanges(await api.changes((Date.now() - since) / 3_600_000));
    } catch {
      setChanges(null);
    }
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setErr(null);
    try {
      const [o, f] = await Promise.all([api.overview(), api.feed()]);
      setOverview(o);
      setFeed(f);
      const params: string[] = [];
      if (typeF) params.push(`&type=${typeF}`);
      if (prioF) params.push(`&priority=${prioF}`);
      if (qDeb) params.push(`&q=${encodeURIComponent(qDeb)}`);
      setEvents(await api.events(params.join("")));
    } catch (e) {
      setErr(e instanceof Error ? e.message : "API unreachable. Is the backend running on :8000?");
    } finally {
      setLoading(false);
    }
  }, [typeF, prioF, qDeb]);

  // The server decides whether this is a real fetch (atomic claim) and whether a
  // brief rebuild is due, so the client always asks and never reasons about age.
  // Fire-and-forget: a rebuild can take ~25s, which must not block first paint.
  const refreshInBackground = useCallback(async () => {
    // The mount effect re-runs whenever a filter changes; one ask per page load.
    if (refreshedRef.current) return;
    refreshedRef.current = true;
    const res = await api.ingest();
    if (res.skipped) return;
    await load();
    loadEscalation();
    loadClusters();
    loadAnalytics(true);
    loadChanges();
    if (res.brief_rebuilt && briefingOpen) loadBriefing();
  }, [load, loadEscalation, loadClusters, loadAnalytics, loadChanges, briefingOpen, loadBriefing]);

  const resolveEvent = useCallback(
    async (id: string) => {
      setResolving(true);
      try {
        await api.resolve(id);
        setDetail(await api.detail(id));
        load();
      } catch {
        flash("Resolve failed. Is the backend running?");
      } finally {
        setResolving(false);
      }
    },
    [load, flash]
  );

  useEffect(() => {
    load();
    refreshInBackground();
    const t = setInterval(load, 60000);
    return () => clearInterval(t);
  }, [load, refreshInBackground]);

  // posture, sequences and the since-last-visit delta change on a slower cadence
  // than the event list; analytics is refreshed once and after each ingest.
  useEffect(() => {
    loadEscalation();
    loadClusters();
    loadAnalytics();
    const t = setInterval(() => {
      loadEscalation();
      loadClusters();
      loadChanges();
    }, 300000);
    return () => clearInterval(t);
  }, [loadEscalation, loadClusters, loadAnalytics, loadChanges]);

  useEffect(() => {
    const KEY = "bmkgintel.last-visit";
    let previous = 0;
    try {
      const raw = localStorage.getItem(KEY);
      previous = raw ? Number(raw) : 0;
      localStorage.setItem(KEY, String(Date.now()));
    } catch {
      return;
    }
    const hours = previous ? (Date.now() - previous) / 3_600_000 : 0;
    if (!Number.isFinite(hours) || hours < 0.1 || hours > 72) return;
    changesSinceRef.current = previous;
    setChangesSince(previous);
    loadChanges();
  }, [loadChanges]);

  useEffect(() => {
    api.overlays().then(setLayers).catch(() => setLayers([]));
  }, []);
  useEffect(() => {
    if (showVolcanoes && !volcanoes) {
      api.overlayGeojson("volcanoes")
        .then((fc) => setVolcanoes((fc.features as VolcanoFeature[]) ?? []))
        .catch(() => setVolcanoes([]));
    }
  }, [showVolcanoes, volcanoes]);
  useEffect(() => {
    if (showPlates && !plates) {
      api.overlayGeojson("plates")
        .then(setPlates)
        .catch(() => setPlates({ type: "FeatureCollection", features: [] }));
    }
  }, [showPlates, plates]);

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      setDetailLoading(false);
      return;
    }
    setDetailLoading(true);
    api
      .detail(selectedId)
      .then(setDetail)
      .catch(() => setDetail(null))
      .finally(() => setDetailLoading(false));
  }, [selectedId]);

  // status-strip KPI filter — shared by the map and the priority list
  const visibleEvents = useMemo(() => {
    if (!kpi) return events;
    const dayAgo = Date.now() - 24 * 60 * 60 * 1000;
    switch (kpi) {
      case "active":
        return events.filter((e) => e.status === "active");
      case "high":
        return events.filter((e) => e.priority === "HIGH" || e.priority === "CRITICAL");
      case "quakes24h":
        return events.filter(
          (e) =>
            (e.type === "earthquake" || e.type === "tsunami_alert") &&
            +new Date(e.occurred_at) >= dayAgo
        );
      case "weather":
        return events.filter((e) => e.type === "severe_weather" && e.status === "active");
      case "tsunami":
        return events.filter((e) => e.type === "tsunami_alert" && e.status === "active");
    }
  }, [events, kpi]);

  const priority = useMemo(() => {
    const arr = [...visibleEvents];
    switch (sortMode) {
      case "newest":
        arr.sort((a, b) => +new Date(b.occurred_at) - +new Date(a.occurred_at));
        break;
      case "oldest":
        arr.sort((a, b) => +new Date(a.occurred_at) - +new Date(b.occurred_at));
        break;
      case "magnitude":
        arr.sort(
          (a, b) =>
            (b.magnitude ?? -Infinity) - (a.magnitude ?? -Infinity) ||
            +new Date(b.occurred_at) - +new Date(a.occurred_at)
        );
        break;
      case "score":
      default:
        arr.sort((a, b) => b.score - a.score || +new Date(b.occurred_at) - +new Date(a.occurred_at));
        break;
    }
    return arr;
  }, [visibleEvents, sortMode]);

  const topEvent = useMemo(
    () =>
      visibleEvents.reduce<BMKGEvent | null>(
        (best, e) => (!best || e.score > best.score ? e : best),
        null
      ),
    [visibleEvents]
  );

  const faultsOff = layers.find((l) => l.id === "faults" && !l.available);
  const volcanoLayer = layers.find((l) => l.id === "volcanoes");
  const rightOpen = !!selectedId || detailLoading;
  const eventsById = useMemo(() => new globalThis.Map(events.map((e) => [e.id, e] as [string, BMKGEvent])), [events]);
  const hasFilters = !!kpi || !!typeF || !!prioF || !!qDeb;

  const growingIds = useMemo(
    () => changes?.growing_sequences.map((g) => g.cluster_id) ?? [],
    [changes]
  );

  // only sequences whose mainshock and at least one member survive the current
  // filters are drawn, so the layer always explains what is actually plotted
  const visibleSequences = useMemo(() => {
    if (!showSequences) return [];
    const byId = new globalThis.Map(visibleEvents.map((e) => [e.id, e] as [string, BMKGEvent]));
    return clusters
      .filter(
        (c) =>
          byId.has(c.mainshock_id) &&
          c.member_ids.some((id) => id !== c.mainshock_id && byId.has(id))
      )
      .sort((a, b) => +new Date(b.latest_at) - +new Date(a.latest_at))
      .slice(0, 6);
  }, [clusters, visibleEvents, showSequences]);

  const deltaItems = changes
    ? [
        { n: changes.counts.new ?? 0, label: "new" },
        { n: changes.counts.escalated ?? 0, label: "escalated" },
        { n: changes.counts.de_escalated ?? 0, label: "de-escalated" },
        { n: changes.counts.resolved ?? 0, label: "resolved" },
        { n: changes.counts.expired ?? 0, label: "expired" },
        {
          n: changes.counts.growing_sequences ?? 0,
          label: changes.counts.growing_sequences === 1 ? "sequence growing" : "sequences growing",
        },
      ].filter((it) => it.n > 0)
    : [];

  return (
    <div className="app">
      <TopBar
        overview={overview}
        escalation={escalation}
        loading={loading}
        err={err}
        onBriefing={openBriefing}
        onPosture={openBriefing}
      />

      {err && (
        <div className="errbanner" role="alert">
          <span className="grow">
            {err} Locally, start the backend with <code>uvicorn app.main:app</code>.
          </span>
          <button className="btn" onClick={load}>Retry</button>
        </div>
      )}

      {msg && (
        <div className="toast" role="status">
          <span className="grow">{msg}</span>
          <button className="btn btn-quiet" onClick={() => setMsg(null)} aria-label="Dismiss message">
            Dismiss
          </button>
        </div>
      )}

      {overview && (
        <StatusStrip
          overview={overview}
          kpi={kpi}
          onToggle={toggleKpi}
          topEvent={topEvent}
          onSelectTop={setSelectedId}
          filteredCount={visibleEvents.length}
          analytics={analytics}
        />
      )}

      {changes && changesSince && !changesDismissed && deltaItems.length > 0 && (
        <div className="deltabanner" role="status">
          <span className="delta-label">
            Since <span className="mono">{fmtClock(new Date(changesSince).toISOString())}</span>
          </span>
          <span className="delta-items">
            {deltaItems.map((it) => (
              <span className="delta-item" key={it.label}>
                <span className="n">{it.n}</span>
                {it.label}
              </span>
            ))}
          </span>
          <span className="delta-actions">
            <button className="btn" onClick={openBriefing}>
              Open briefing
            </button>
            <button className="btn btn-quiet" onClick={() => setChangesDismissed(true)}>
              Dismiss
            </button>
          </span>
        </div>
      )}

      <div className={`layout ${rightOpen ? "with-detail" : ""}`}>
        {/* left rail: priority + activity */}
        <div className="rail rail-left">
          <EventList
            events={events}
            filtered={priority}
            loading={loading}
            selectedId={selectedId}
            hoverId={hoverId}
            sortMode={sortMode}
            typeF={typeF}
            prioF={prioF}
            query={q}
            hasFilters={hasFilters}
            onSort={setSortMode}
            onType={setTypeF}
            onPriority={setPrioF}
            onQuery={setQ}
            onSelect={setSelectedId}
            onHover={setHoverId}
            onClearFilters={clearFilters}
          />
          <FeedList feed={feed} eventsById={eventsById} onSelect={(id) => setSelectedId(id)} />
        </div>

        {/* center: the watch map */}
        <div className="mapcol">
          <div className="maphead" role="toolbar" aria-label="Map layers">
            <span className="map-title">
              Indonesia watch
              <span className="count">{visibleEvents.length} plotted</span>
            </span>
            <div className="map-layers">
              <label
                className="layerchk"
                title="Connect earthquake sequences to their mainshock"
              >
                <input
                  type="checkbox"
                  checked={showSequences}
                  onChange={(e) => setShowSequences(e.target.checked)}
                />
                Sequences
                {showSequences && visibleSequences.length > 0 ? ` · ${visibleSequences.length}` : ""}
              </label>
              <label
                className="layerchk"
                title={volcanoLayer?.attribution ?? "PVMBG volcano levels"}
              >
                <input
                  type="checkbox"
                  checked={showVolcanoes}
                  onChange={(e) => setShowVolcanoes(e.target.checked)}
                />
                Volcanoes{volcanoLayer?.count != null ? ` · ${volcanoLayer.count}` : ""}
              </label>
              <label className="layerchk" title="PB2002 tectonic plate boundaries">
                <input
                  type="checkbox"
                  checked={showPlates}
                  onChange={(e) => setShowPlates(e.target.checked)}
                />
                Plates
              </label>
              {faultsOff && (
                <span className="layer-note" title={faultsOff.reason ?? ""}>
                  Faults unavailable
                </span>
              )}
            </div>
          </div>
          <Map
            events={visibleEvents}
            selectedId={selectedId}
            hoverId={hoverId}
            onSelect={setSelectedId}
            onHover={setHoverId}
            volcanoes={volcanoes}
            showVolcanoes={showVolcanoes}
            plates={plates}
            showPlates={showPlates}
            sequences={visibleSequences}
            showSequences={showSequences}
            growingIds={growingIds}
          />
        </div>

        {/* right rail: the selected event */}
        {rightOpen && (
          <div className="rail rail-detail">
            <EventDetail
              detail={detail}
              loading={detailLoading}
              onResolve={resolveEvent}
              onClose={() => setSelectedId(null)}
              resolving={resolving}
            />
          </div>
        )}
      </div>

      <FeedsBar overview={overview} />

      {briefingOpen && (
        <BriefingPanel
          briefing={briefing}
          loading={briefingLoading}
          error={briefingErr}
          onClose={() => setBriefingOpen(false)}
          onSelectEvent={setSelectedId}
        />
      )}
    </div>
  );
}
