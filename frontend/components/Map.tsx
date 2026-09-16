"use client";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useEffect, useRef } from "react";
import type { BMKGEvent, VolcanoFeature } from "../lib/types";
import { prioColor } from "../lib/format";

type PlatesFC = { type: string; features: unknown[] };

const VOLC_COLOR: Record<string, string> = {
  AWAS: "#ff5d5d",
  SIAGA: "#ff9349",
  WASPADA: "#f5c518",
  NORMAL: "#2dd4a7",
};

function escapeHtml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

/** Zoom-relative marker scale: 1.0 at the default zoom, growing when zoomed
 *  in (legibility) and shrinking when zoomed out (declutter). Capped both ends. */
function zoomScale(z: number): number {
  const s = 1.0 + (z - 4.2) * 0.14;
  return Math.min(1.8, Math.max(0.65, Math.round(s * 100) / 100));
}

/** One event marker: dark fill + priority-colored ring; size encodes magnitude. */
function buildEventEl(e: BMKGEvent, selected: boolean): HTMLElement {
  const el = document.createElement("div");
  const isQuake = e.type === "earthquake" || e.type === "tsunami_alert";
  const mag = e.magnitude ?? 4;
  const size = isQuake ? Math.min(10 + mag * 4.5, 38) : 18;
  const color = prioColor(e.priority);
  el.className = `mk ${e.type === "severe_weather" ? "mk-wx" : ""} ${selected ? "mk-sel" : ""} ${
    e.type === "tsunami_alert" ? "mk-pulse" : ""
  }`
    .trim()
    .replace(/\s+/g, " ");
  el.style.width = `${size}px`;
  el.style.height = `${size}px`;
  el.style.color = color; // pulse ring uses currentColor
  el.title = `${e.title} — ${e.priority} (${e.score.toFixed(1)})`;
  el.setAttribute("role", "button");
  el.setAttribute("aria-label", el.title);
  el.tabIndex = 0;

  const core = document.createElement("div");
  core.className = "mk-core";
  core.style.border = `${selected ? 2.5 : 1.5}px solid ${color}`;
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
      style: "https://demotiles.maplibre.org/globe.json",
      center: [118, -2.5],
      zoom: 4.2,
      attributionControl: { compact: true },
    });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-right");
    // keep marker legibility across zoom: one CSS var write per frame,
    // GPU-composited via transform — no marker rebuilds
    const applyScale = () => {
      ref.current?.style.setProperty("--mk-scale", String(zoomScale(map.getZoom())));
    };
    map.on("zoom", applyScale);
    applyScale();
    mapRef.current = map;
    return () => {
      map.off("zoom", applyScale);
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
          `<div style="font-weight:700;font-size:12.5px">${escapeHtml(e.title)}</div>` +
            `<div style="font-size:11px;color:#8fa1b5;margin-top:3px">${escapeHtml(e.type)} · ${e.priority} · score ${e.score.toFixed(1)}` +
            (e.magnitude != null ? ` · M${e.magnitude}` : "") + `</div>`
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
      el.title = `${p.name} — PVMBG ${p.level}`;
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
        paint: { "line-color": "#7c8db0", "line-width": 1.2, "line-opacity": 0.7, "line-dasharray": [3, 2] },
      });
      map.addLayer({
        id: "plates-subduction",
        type: "line",
        source: "plates-src",
        filter: ["==", ["get", "boundary_type"], "subduction"],
        paint: { "line-color": "#e879a9", "line-width": 2.2, "line-opacity": 0.9 },
      });
    };
    if (map.isStyleLoaded()) apply();
    else map.once("styledata", apply);
  }, [plates, showPlates]);

  return (
    <div className={`mapwrap ${selectedId ? "has-selection" : ""}`}>
      <div id="map" ref={ref} role="application" aria-label="Indonesia hazard map" />
      <div className="maplegend" aria-hidden="true">
        <span className="lg-title">Legend</span>
        <span className="lg-row"><span className="sw" style={{ background: "#2dd4a7" }} /> LOW</span>
        <span className="lg-row"><span className="sw" style={{ background: "#f5c518" }} /> MODERATE</span>
        <span className="lg-row"><span className="sw" style={{ background: "#ff9349" }} /> HIGH</span>
        <span className="lg-row"><span className="sw" style={{ background: "#ff5d5d" }} /> CRITICAL</span>
        <span className="lg-sep" />
        <span className="lg-row"><span className="sw" style={{ width: 14, background: "transparent", border: "2px solid #8fa1b5" }} /> size = magnitude</span>
        <span className="lg-row"><span className="sw sq" style={{ background: "transparent", border: "2px solid #8fa1b5" }} /> severe weather</span>
        {showVolcanoes && (
          <>
            <span className="lg-sep" />
            <span className="lg-row"><span className="sw tri" /> volcano · PVMBG level</span>
          </>
        )}
        {showPlates && (
          <>
            <span className="lg-sep" />
            <span className="lg-row"><span className="ln" style={{ borderColor: "#e879a9" }} /> subduction</span>
            <span className="lg-row"><span className="ln" style={{ borderColor: "#7c8db0" }} /> plate boundary</span>
          </>
        )}
      </div>
    </div>
  );
}
