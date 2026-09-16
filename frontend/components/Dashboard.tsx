"use client";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Map from "../components/Map";
import TopBar from "../components/TopBar";
import StatusStrip, { type KpiKey } from "../components/StatusStrip";
import EventList, { type SortMode } from "../components/EventList";
import FeedList from "../components/FeedList";
import EventDetail, { CollectorHealth } from "../components/EventDetail";
import BriefingPanel from "../components/BriefingPanel";
import { api } from "../lib/api";
import type { BMKGEvent, Briefing, EventDetail as EventDetailT, FeedItem, OverlayLayer, Overview, VolcanoFeature } from "../lib/types";

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
  const [sortMode, setSortMode] = useState<SortMode>("score");
  const [kpi, setKpi] = useState<KpiKey | null>(null);
  const [ingesting, setIngesting] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [resolving, setResolving] = useState(false);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

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
  const flash = useCallback((msg: string) => {
    setMsg(msg);
    if (toastTimer.current) clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setMsg(null), 12000);
  }, []);

  const loadBriefing = useCallback(async () => {
    setBriefingLoading(true);
    setBriefingErr(null);
    try {
      setBriefing(await api.briefing());
    } catch (e) {
      setBriefing(null);
      setBriefingErr(e instanceof Error ? e.message : "Briefing unavailable — is the backend running?");
    } finally {
      setBriefingLoading(false);
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
      setErr(e instanceof Error ? e.message : "API unreachable — is the backend running on :8000?");
    } finally {
      setLoading(false);
    }
  }, [typeF, prioF, qDeb]);

  const runIngest = useCallback(async () => {
    setIngesting(true);
    try {
      await api.ingest();
      await load();
    } catch {
      setErr("Ingest failed — is the backend running on :8000?");
    } finally {
      setIngesting(false);
    }
  }, [load]);

  const resolveEvent = useCallback(
    async (id: string) => {
      setResolving(true);
      try {
        await api.resolve(id);
        setDetail(await api.detail(id));
        load();
      } catch {
        flash("⚠ Resolve failed — is the backend running?");
      } finally {
        setResolving(false);
      }
    },
    [load, flash]
  );

  useEffect(() => {
    load();
    const t = setInterval(load, 60000);
    return () => clearInterval(t);
  }, [load]);

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

  const priority = useMemo(() => {
    const now = Date.now();
    const dayAgo = now - 24 * 60 * 60 * 1000;
    let arr = [...events];
    switch (kpi) {
      case "active":
        arr = arr.filter((e) => e.status === "active");
        break;
      case "high":
        arr = arr.filter((e) => e.priority === "HIGH" || e.priority === "CRITICAL");
        break;
      case "quakes24h":
        arr = arr.filter(
          (e) =>
            (e.type === "earthquake" || e.type === "tsunami_alert") &&
            +new Date(e.occurred_at) >= dayAgo
        );
        break;
      case "weather":
        arr = arr.filter((e) => e.type === "severe_weather" && e.status === "active");
        break;
      case "tsunami":
        arr = arr.filter((e) => e.type === "tsunami_alert" && e.status === "active");
        break;
      default:
        break;
    }
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
    return arr.slice(0, 30);
  }, [events, sortMode, kpi]);

  const faultsOff = layers.find((l) => l.id === "faults" && !l.available);
  const rightOpen = !!selectedId || detailLoading;

  return (
    <div className="app">
      <TopBar
        overview={overview}
        loading={loading || ingesting}
        err={err}
        onIngest={runIngest}
        onBriefing={() => {
          setBriefingOpen(true);
          loadBriefing();
        }}
      />

      {err && (
        <div className="errbanner" role="alert">
          <span className="grow">
            {err} Start backend: <span className="mono">uvicorn app.main:app</span> then press ↻ Ingest.
          </span>
          <button className="btn" onClick={load}>Retry</button>
        </div>
      )}

      {msg && (
        <div className="toast" role="status">
          <span className="grow">{msg}</span>
          <button className="btn btn-ghost" onClick={() => setMsg(null)} aria-label="Dismiss">✕</button>
        </div>
      )}

      {overview && <StatusStrip overview={overview} kpi={kpi} onToggle={toggleKpi} />}

      <div className="layout">
        {/* left rail: priority + feed */}
        <div className="rail">
          <EventList
            events={events}
            filtered={priority}
            loading={loading}
            selectedId={selectedId}
            hoverId={hoverId}
            sortMode={sortMode}
            onSort={setSortMode}
            onSelect={setSelectedId}
            onHover={setHoverId}
            onClearFilters={clearFilters}
          />
          <FeedList feed={feed} onSelect={(id) => setSelectedId(id)} />
        </div>

        {/* center: map surface */}
        <div className="rail" style={{ borderRight: "none", overflow: "hidden" }}>
          <div className="maptoolbar" role="toolbar" aria-label="Map filters and layers">
            <label style={{ display: "flex", gap: 4, alignItems: "center" }}>
              <span className="sr-only">Type</span>
              <select value={typeF} onChange={(e) => setTypeF(e.target.value)} aria-label="Filter by type">
                <option value="">ALL TYPES</option>
                <option value="earthquake">EARTHQUAKE</option>
                <option value="severe_weather">SEVERE WX</option>
                <option value="tsunami_alert">TSUNAMI</option>
              </select>
            </label>
            <label style={{ display: "flex", gap: 4, alignItems: "center" }}>
              <span className="sr-only">Priority</span>
              <select value={prioF} onChange={(e) => setPrioF(e.target.value)} aria-label="Filter by priority">
                <option value="">ALL PRIORITIES</option>
                <option>CRITICAL</option>
                <option>HIGH</option>
                <option>MODERATE</option>
                <option>LOW</option>
              </select>
            </label>
            <input
              placeholder="Search — e.g. Cilacap"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              aria-label="Search events"
              style={{ width: 180 }}
            />
            {kpi && (
              <button className="btn" onClick={() => setKpi(null)} title="Clear status-strip filter">
                ✕ {kpi.toUpperCase()}
              </button>
            )}
            <span className="label" style={{ marginLeft: 4 }}>Layers</span>
            {layers
              .filter((l) => l.id === "volcanoes" || l.id === "plates")
              .map((l) => (
                <label
                  key={l.id}
                  className="layerchk"
                  title={l.attribution}
                  style={{ opacity: l.available ? 1 : 0.45 }}
                >
                  <input
                    type="checkbox"
                    disabled={!l.available}
                    checked={l.id === "volcanoes" ? showVolcanoes : showPlates}
                    onChange={(e) =>
                      l.id === "volcanoes"
                        ? setShowVolcanoes(e.target.checked)
                        : setShowPlates(e.target.checked)
                    }
                  />
                  {l.id === "volcanoes" ? `▲ Volc${l.count != null ? ` ${l.count}` : ""}` : `≋ Plates`}
                </label>
              ))}
            {faultsOff && (
              <span className="label" title={faultsOff.reason ?? ""} style={{ opacity: 0.6 }}>
                ⛔ Faults unavailable
              </span>
            )}
            <span className="plotcount">{events.length} plotted</span>
          </div>
          <div style={{ flex: 1, minHeight: 0 }}>
            <Map
              events={events}
              selectedId={selectedId}
              hoverId={hoverId}
              onSelect={setSelectedId}
              onHover={setHoverId}
              volcanoes={volcanoes}
              showVolcanoes={showVolcanoes}
              plates={plates}
              showPlates={showPlates}
            />
          </div>
        </div>

        {/* right rail: detail / system status */}
        <div className={`rail rail-right ${rightOpen ? "open" : ""}`}>
          {rightOpen ? (
            <>
              <EventDetail
                detail={detail}
                loading={detailLoading}
                onResolve={resolveEvent}
                resolving={resolving}
              />
              <button
                className="btn"
                onClick={() => setSelectedId(null)}
                style={{ margin: 12 }}
                title="Close detail (back to system status)"
              >
                ← Back to system status
              </button>
            </>
          ) : (
            <CollectorHealth overview={overview} />
          )}
        </div>
      </div>

      {briefingOpen && (
        <BriefingPanel
          briefing={briefing}
          loading={briefingLoading}
          error={briefingErr}
          onClose={() => setBriefingOpen(false)}
          onRefresh={loadBriefing}
          onSelectEvent={setSelectedId}
        />
      )}
    </div>
  );
}
