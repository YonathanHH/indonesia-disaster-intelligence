"use client";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useEffect, useRef } from "react";
import type { BMKGEvent, ClusterSequence, VolcanoFeature } from "../lib/types";
import { prioColor, prioLabel, typeLabel } from "../lib/format";

type PlatesFC = { type: string; features: unknown[] };

const VOLC_COLOR: Record<string, string> = {
  AWAS: "#e5566f",
  SIAGA: "#e8824f",
  WASPADA: "#d9a441",
  NORMAL: "#4fae8d",
};

/* Dark operational basemap (free, no key), without its labels: reference
 * cities are drawn in the app's type so orientation never depends on basemap
 * glyphs. Falls back to the MapLibre demo globe style if CARTO is unreachable. */
const DARK_STYLE = "https://basemaps.cartocdn.com/gl/dark-matter-nolabels-gl-style/style.json";
const FALLBACK_STYLE = "https://demotiles.maplibre.org/globe.json";

const CITIES: { name: string; lngLat: [number, number]; side?: "left" }[] = [
  { name: "Banda Aceh", lngLat: [95.3238, 5.5483] },
  { name: "Medan", lngLat: [98.6722, 3.5952] },
  { name: "Padang", lngLat: [100.4172, -0.9471] },
  { name: "Pontianak", lngLat: [109.3425, -0.0263] },
  { name: "Balikpapan", lngLat: [116.8529, -1.2379] },
  { name: "Manado", lngLat: [124.8421, 1.4748], side: "left" },
  { name: "Makassar", lngLat: [119.4327, -5.1477] },
  { name: "Jakarta", lngLat: [106.8456, -6.2088] },
  { name: "Surabaya", lngLat: [112.7521, -7.2575] },
  { name: "Denpasar", lngLat: [115.2126, -8.6705] },
  { name: "Kupang", lngLat: [123.607, -10.1772] },
  { name: "Jayapura", lngLat: [140.7181, -2.5337], side: "left" },
];

function escapeHtml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

/** Zoom-relative marker scale: 1.0 at the default zoom, growing when zoomed
 *  in (legibility) and shrinking when zoomed out (declutter). Capped both ends. */
function zoomScale(z: number): number {
  const s = 1.0 + (z - 4.2) * 0.14;
  return Math.min(1.8, Math.max(0.65, Math.round(s * 100) / 100));
}

/** One event marker: filled severity color + dark stroke; shape encodes type
 *  (circle = quake, diamond = severe weather, ringed circle = tsunami);
 *  size encodes magnitude for quakes. */
function buildEventEl(e: BMKGEvent, selected: boolean): HTMLElement {
  const el = document.createElement("div");
  const mag = e.magnitude ?? 4;
  const isWx = e.type === "severe_weather";
  const isTsu = e.type === "tsunami_alert";
  const size = isWx ? 14 : isTsu ? Math.min(13 + mag * 3.3, 31) : Math.min(9 + mag * 3.3, 30);
  const color = prioColor(e.priority);
  el.className = `mk ${isWx ? "mk-wx" : isTsu ? "mk-tsu" : "mk-q"} ${selected ? "mk-sel" : ""}`
    .trim()
    .replace(/\s+/g, " ");
  el.style.width = `${Math.round(size)}px`;
  el.style.height = `${Math.round(size)}px`;
  el.style.color = color; // pulse ring uses currentColor
  el.title = `${e.title} · ${e.priority} (${e.score.toFixed(1)})`;
  el.setAttribute("role", "button");
  el.setAttribute("aria-label", el.title);
  el.tabIndex = 0;

  const core = document.createElement("div");
  core.className = "mk-core";
  core.style.background = color;
  core.style.borderColor = "#171719";
  if (isWx) core.style.transform = "rotate(45deg) scale(var(--mk-scale, 1))";
  el.appendChild(core);
  return el;
}

export default function Map({
  events,
  selectedId,
  hoverId,
  onSelect,
  onHover,
  volcanoes,
  showVolcanoes,
  plates,
  showPlates,
  sequences,
  showSequences,
  growingIds,
}: {
  events: BMKGEvent[];
  selectedId: string | null;
  hoverId: string | null;
  onSelect: (id: string) => void;
  onHover: (id: string | null) => void;
  volcanoes: VolcanoFeature[] | null;
  showVolcanoes: boolean;
  plates: PlatesFC | null;
  showPlates: boolean;
  sequences: ClusterSequence[];
  showSequences: boolean;
  growingIds: string[];
}) {
  const ref = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const markers = useRef<maplibregl.Marker[]>([]);
  const markerEls = useRef<globalThis.Map<string, HTMLElement>>(new globalThis.Map());
  const volcanoMarkers = useRef<maplibregl.Marker[]>([]);
  const onSelectRef = useRef(onSelect);
  const onHoverRef = useRef(onHover);
  onSelectRef.current = onSelect;
  onHoverRef.current = onHover;

  // init
  useEffect(() => {
    if (!ref.current || mapRef.current) return;
    const map = new maplibregl.Map({
      container: ref.current,
      style: DARK_STYLE,
      center: [118, -2.5],
      zoom: 4.2,
      attributionControl: { compact: true },
    });
    // keep the console usable offline / when CARTO is blocked
    map.on("error", () => {
      try {
        const style = map.getStyle();
        const src = (style?.sprite ?? "") as string;
        if (!src.includes("demotiles")) map.setStyle(FALLBACK_STYLE);
      } catch {
        /* keep current style */
      }
    });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-right");
    const cityMarks: { el: HTMLElement; lngLat: [number, number] }[] = [];
    for (const c of CITIES) {
      const el = document.createElement("div");
      el.className = c.side === "left" ? "citymark citymark-left" : "citymark";
      el.style.zIndex = "4";
      const dot = document.createElement("span");
      dot.className = "cdot";
      const name = document.createElement("span");
      name.className = "cname";
      name.textContent = c.name;
      el.append(dot, name);
      new maplibregl.Marker({ element: el, anchor: c.side === "left" ? "right" : "left" })
        .setLngLat(c.lngLat)
        .addTo(map);
      cityMarks.push({ el, lngLat: c.lngLat });
    }
    // a label whose city is outside the view would otherwise leave a clipped tail
    const syncCities = () => {
      const bounds = map.getBounds();
      for (const c of cityMarks) {
        c.el.style.display = bounds.contains(c.lngLat) ? "" : "none";
      }
    };
    map.on("moveend", syncCities);
    syncCities();
    // keep marker legibility across zoom: one CSS var write per frame,
    // GPU-composited via transform, so markers never rebuild
    const applyScale = () => {
      ref.current?.style.setProperty("--mk-scale", String(zoomScale(map.getZoom())));
    };
    map.on("zoom", applyScale);
    applyScale();
    mapRef.current = map;
    return () => {
      map.off("zoom", applyScale);
      map.off("moveend", syncCities);
      map.remove();
      mapRef.current = null;
    };
  }, []);

  // event markers
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    markers.current.forEach((m) => m.remove());
    markers.current = [];
    markerEls.current.clear();
    const selected = events.find((e) => e.id === selectedId);
    // draw unselected first so the selected marker stacks on top
    for (const e of selected ? events.filter((x) => x.id !== selected.id) : events) {
      addMarker(map, e, false);
    }
    if (selected) addMarker(map, selected, true);
  }, [events, selectedId]);

  // hover ring follows list hover (and vice versa) without rebuilding markers
  useEffect(() => {
    markerEls.current.forEach((el, id) => {
      el.classList.toggle("mk-hover", id === hoverId);
    });
  }, [hoverId]);

  function addMarker(map: maplibregl.Map, e: BMKGEvent, isSelected: boolean) {
    const el = buildEventEl(e, isSelected);
    const color = prioColor(e.priority);
    el.addEventListener("click", (ev) => {
      ev.stopPropagation();
      onSelectRef.current(e.id);
    });
    el.addEventListener("mouseenter", () => onHoverRef.current(e.id));
    el.addEventListener("mouseleave", () => onHoverRef.current(null));
    el.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter" || ev.key === " ") {
        ev.preventDefault();
        onSelectRef.current(e.id);
      }
    });
    const mk = new maplibregl.Marker({ element: el })
      .setLngLat([e.longitude, e.latitude])
      .setPopup(
        new maplibregl.Popup({ offset: 14, closeButton: true }).setHTML(
          `<div style="display:flex;align-items:center;gap:7px"><span style="width:7px;height:7px;border-radius:50%;background:${color};flex:none"></span>` +
            `<span style="font-size:12px;font-weight:600;color:${color}">${escapeHtml(prioLabel(e.priority))}</span>` +
            `<span style="font-size:12px;color:#909298">${escapeHtml(typeLabel(e.type))} · ${e.score.toFixed(1)}/10</span></div>` +
            `<div style="font-weight:600;font-size:13.5px;margin-top:5px;line-height:1.4">${escapeHtml(e.title)}</div>` +
            (e.magnitude != null
              ? `<div style="font-size:12px;color:#909298;margin-top:3px;font-family:'JetBrains Mono',monospace">M${e.magnitude.toFixed(1)}${e.depth_km != null ? ` · ${Math.round(e.depth_km)} km deep` : ""}</div>`
              : "") +
            `<div style="font-size:12px;color:#909298;margin-top:2px">${e.source_count} source${e.source_count === 1 ? "" : "s"}</div>`
        )
      )
      .addTo(map);
    markers.current.push(mk);
    markerEls.current.set(e.id, el);
  }

  // fly to selected
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !selectedId) return;
    const e = events.find((x) => x.id === selectedId);
    if (!e) return;
    map.flyTo({
      center: [e.longitude, e.latitude],
      zoom: Math.max(map.getZoom(), 5.4),
      speed: 1.2,
      essential: true,
    });
  }, [selectedId, events]);

  // volcano markers
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    volcanoMarkers.current.forEach((m) => m.remove());
    volcanoMarkers.current = [];
    if (!showVolcanoes || !volcanoes) return;
    for (const v of volcanoes) {
      const el = document.createElement("div");
      const p = v.properties;
      const c = VOLC_COLOR[p.level] || p.color || "#8fa1b5";
      // outer box is maplibre-positioned; inner triangle scales with zoom
      el.style.width = "16px";
      el.style.height = "12px";
      el.style.cursor = "pointer";
      el.title = `${p.name} · PVMBG ${p.level}`;
      el.setAttribute("role", "button");
      el.setAttribute("aria-label", el.title);
      el.tabIndex = 0;
      const tri = document.createElement("div");
      tri.className = "vk-core";
      tri.style.borderBottom = `10px solid ${c}`;
      el.appendChild(tri);
      const mk = new maplibregl.Marker({ element: el })
        .setLngLat([v.geometry.coordinates[0], v.geometry.coordinates[1]])
        .setPopup(
          new maplibregl.Popup({ offset: 10 }).setHTML(
            `<div style="font-weight:700;font-size:12.5px">${escapeHtml(p.name)}</div>` +
              `<div style="font-size:11px;margin-top:2px">PVMBG level: <b style="color:${c}">${escapeHtml(p.level)}</b>` +
              (p.province ? ` · ${escapeHtml(p.province)}` : "") + `</div>` +
              (p.url
                ? `<a href="${escapeHtml(p.url)}" target="_blank" rel="noreferrer" style="font-size:11px">MAGMA report →</a>`
                : "")
          )
        )
        .addTo(map);
      volcanoMarkers.current.push(mk);
    }
  }, [volcanoes, showVolcanoes]);

  // plate boundary layers
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const apply = () => {
      for (const id of ["plates-line", "plates-subduction"]) {
        if (map.getLayer(id)) map.removeLayer(id);
      }
      if (map.getSource("plates-src")) map.removeSource("plates-src");
      if (!showPlates || !plates) return;
      map.addSource("plates-src", { type: "geojson", data: plates as never });
      map.addLayer({
        id: "plates-line",
        type: "line",
        source: "plates-src",
        filter: ["!=", ["get", "boundary_type"], "subduction"],
        paint: { "line-color": "#6b6c72", "line-width": 1.1, "line-opacity": 0.8, "line-dasharray": [3, 2] },
      });
      map.addLayer({
        id: "plates-subduction",
        type: "line",
        source: "plates-src",
        filter: ["==", ["get", "boundary_type"], "subduction"],
        paint: { "line-color": "#8aa9cf", "line-width": 2, "line-opacity": 0.85 },
      });
    };
    if (map.isStyleLoaded()) apply();
    else map.once("styledata", apply);
  }, [plates, showPlates]);

  // aftershock sequences: thin links from mainshock to members + a ring at the
  // mainshock, in that event's priority colour. Growing sequences read brighter.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const apply = () => {
      for (const id of ["seq-ring", "seq-lines", "seq-under"]) {
        if (map.getLayer(id)) map.removeLayer(id);
      }
      if (map.getSource("seq-src")) map.removeSource("seq-src");
      if (!showSequences) return;
      const byId = new globalThis.Map(events.map((e) => [e.id, e] as [string, BMKGEvent]));
      const growing = new Set(growingIds);
      const features: unknown[] = [];
      for (const c of sequences) {
        const main = byId.get(c.mainshock_id);
        if (!main) continue;
        const color = prioColor(main.priority);
        const grow = growing.has(c.cluster_id);
        let linked = false;
        for (const id of c.member_ids) {
          if (id === c.mainshock_id) continue;
          const m = byId.get(id);
          if (!m) continue;
          linked = true;
          features.push({
            type: "Feature",
            properties: { color, grow: grow ? 1 : 0 },
            geometry: {
              type: "LineString",
              coordinates: [
                [main.longitude, main.latitude],
                [m.longitude, m.latitude],
              ],
            },
          });
        }
        if (linked) {
          features.push({
            type: "Feature",
            properties: { color, grow: grow ? 1 : 0 },
            geometry: { type: "Point", coordinates: [main.longitude, main.latitude] },
          });
        }
      }
      if (features.length === 0) return;
      map.addSource("seq-src", {
        type: "geojson",
        data: { type: "FeatureCollection", features } as never,
      });
      map.addLayer({
        id: "seq-under",
        type: "line",
        source: "seq-src",
        filter: ["==", ["geometry-type"], "LineString"],
        paint: { "line-color": ["get", "color"], "line-width": 7, "line-opacity": 0.08 },
      });
      map.addLayer({
        id: "seq-lines",
        type: "line",
        source: "seq-src",
        filter: ["==", ["geometry-type"], "LineString"],
        paint: {
          "line-color": ["get", "color"],
          "line-width": 1.4,
          "line-opacity": ["case", ["==", ["get", "grow"], 1], 0.75, 0.45],
        },
      });
      map.addLayer({
        id: "seq-ring",
        type: "circle",
        source: "seq-src",
        filter: ["==", ["geometry-type"], "Point"],
        paint: {
          "circle-radius": ["case", ["==", ["get", "grow"], 1], 28, 23],
          "circle-color": ["get", "color"],
          "circle-opacity": ["case", ["==", ["get", "grow"], 1], 0.12, 0.05],
          "circle-stroke-color": ["get", "color"],
          "circle-stroke-width": 1.2,
          "circle-stroke-opacity": ["case", ["==", ["get", "grow"], 1], 0.75, 0.45],
        },
      });
    };
    if (map.isStyleLoaded()) apply();
    else map.once("styledata", apply);
  }, [sequences, showSequences, growingIds, events]);

  return (
    <div className={`mapwrap ${selectedId ? "has-selection" : ""}`}>
      <div id="map" ref={ref} role="application" aria-label="Indonesia hazard map" />
      <div className="mapfoot">
        <div className="legend" aria-label="Map legend">
          <span className="legend-item"><span className="sw" style={{ background: "#4fae8d" }} />Low</span>
          <span className="legend-item"><span className="sw" style={{ background: "#d9a441" }} />Moderate</span>
          <span className="legend-item"><span className="sw" style={{ background: "#e8824f" }} />High</span>
          <span className="legend-item"><span className="sw" style={{ background: "#e5566f" }} />Critical</span>
          <span className="legend-sep" />
          <span className="legend-item"><span className="sw" style={{ background: "var(--muted)" }} />Quake · size = magnitude</span>
          <span className="legend-item"><span className="sw sw-dia" style={{ background: "var(--muted)" }} />Severe weather</span>
          <span className="legend-item"><span className="sw-ring" style={{ borderStyle: "dashed" }} />Tsunami potential</span>
          {showVolcanoes && (
            <span className="legend-item"><span className="sw sw-tri" />Volcano · PVMBG level</span>
          )}
          {showSequences && sequences.length > 0 && (
            <span className="legend-item">
              <span className="ln" style={{ borderColor: "var(--muted)", opacity: 0.7 }} />
              Aftershock sequence
            </span>
          )}
          {showPlates && (
            <>
              <span className="legend-sep" />
              <span className="legend-item"><span className="ln" style={{ borderColor: "#8aa9cf" }} />Subduction</span>
              <span className="legend-item"><span className="ln" style={{ borderColor: "#6b6c72" }} />Plate boundary</span>
            </>
          )}
        </div>
        <span className="foot-attr">BMKG · PVMBG · PB2002 · CARTO</span>
      </div>
    </div>
  );
}
