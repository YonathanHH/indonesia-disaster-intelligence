"use client";
import type { Overview } from "../lib/types";

export type KpiKey = "active" | "high" | "quakes24h" | "weather" | "tsunami";

const HINTS: Record<KpiKey, string> = {
  active: "status = active",
  high: "HIGH / CRITICAL",
  quakes24h: "quakes, last 24h",
  weather: "active severe wx",
  tsunami: "active tsunami potential",
};

export default function StatusStrip({
  overview,
  kpi,
  onToggle,
}: {
  overview: Overview;
  kpi: KpiKey | null;
  onToggle: (k: KpiKey) => void;
}) {
  const items: { key: KpiKey; v: number; l: string }[] = [
    { key: "active", v: overview.active_events, l: "Active events" },
    { key: "high", v: overview.high_priority, l: "High / Critical" },
    { key: "quakes24h", v: overview.quakes_24h, l: "Quakes 24h" },
    { key: "weather", v: overview.active_weather_alerts, l: "Weather alerts" },
    { key: "tsunami", v: overview.tsunami_alerts, l: "Tsunami alerts" },
  ];
  return (
    <nav className="statstrip" aria-label="Situation filters">
      {items.map((it) => (
        <button
          key={it.key}
          className={`stat ${kpi === it.key ? "on" : ""}`}
          onClick={() => onToggle(it.key)}
          title={`Filter priority list: ${HINTS[it.key]} — click again to clear`}
          aria-pressed={kpi === it.key}
        >
          <span className={`v ${it.v === 0 ? "zero" : ""}`}>{it.v}</span>
          <span className="l">{it.l}</span>
          <span className="hint">{kpi === it.key ? "FILTER ON · click to clear" : HINTS[it.key]}</span>
        </button>
      ))}
    </nav>
  );
}
