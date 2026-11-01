"use client";
import type { Analytics, BMKGEvent, Overview } from "../lib/types";
import { fmtRel, prioColor, prioLabel, typeLabel } from "../lib/format";

export type KpiKey = "active" | "high" | "quakes24h" | "weather" | "tsunami";

const HINTS: Record<KpiKey, string> = {
  active: "Events with status active",
  high: "Events at HIGH or CRITICAL priority",
  quakes24h: "Earthquakes in the last 24 hours",
  weather: "Active severe-weather alerts",
  tsunami: "Active tsunami-potential events",
};

/** Fill the 14-day window so quiet days render as real zeros, not gaps. */
function dailySeries(rows: Analytics["daily_counts_14d"]) {
  const byDay = new Map(rows.map((r) => [r.day, r.count]));
  const out: { day: string; count: number }[] = [];
  const now = new Date();
  for (let i = 13; i >= 0; i--) {
    const d = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate() - i));
    const key = d.toISOString().slice(0, 10);
    out.push({ day: key, count: byDay.get(key) ?? 0 });
  }
  return out;
}

function Trend({ analytics }: { analytics: Analytics }) {
  const series = dailySeries(analytics.daily_counts_14d);
  const max = Math.max(1, ...series.map((s) => s.count));
  const avg = analytics.avg_magnitude_7d;
  const today = series[series.length - 1];
  if (!series.some((s) => s.count > 0)) return null;
  return (
    <div
      className="trend"
      role="img"
      aria-label={`Events per day over 14 days. Today ${today.count}.${avg != null ? ` Average magnitude over 7 days ${avg.toFixed(1)}.` : ""}`}
      title={`Events per day, last 14 days${avg != null ? ` · average magnitude (7 days) M${avg.toFixed(1)}` : ""}`}
    >
      <span className="trend-label">14-day activity</span>
      <span className="trend-bars" aria-hidden="true">
        {series.map((s) => (
          <span
            key={s.day}
            className={`tbar ${s.day === today.day ? "tday" : ""}`}
            style={{ height: `${4 + Math.round((s.count / max) * 20)}px` }}
            title={`${s.day} · ${s.count} event${s.count === 1 ? "" : "s"}`}
          />
        ))}
      </span>
    </div>
  );
}

export default function StatusStrip({
  overview,
  kpi,
  onToggle,
  topEvent,
  onSelectTop,
  filteredCount,
  analytics,
}: {
  overview: Overview;
  kpi: KpiKey | null;
  onToggle: (k: KpiKey) => void;
  topEvent: BMKGEvent | null;
  onSelectTop: (id: string) => void;
  filteredCount: number;
  analytics: Analytics | null;
}) {
  const items: { key: KpiKey; v: number; l: string }[] = [
    { key: "active", v: overview.active_events, l: "Active events" },
    { key: "high", v: overview.high_priority, l: "High priority" },
    { key: "quakes24h", v: overview.quakes_24h, l: "Quakes 24h" },
    { key: "weather", v: overview.active_weather_alerts, l: "Weather alerts" },
    { key: "tsunami", v: overview.tsunami_alerts, l: "Tsunami alerts" },
  ];

  return (
    <section className="situation" aria-label="Current situation">
      <div className="finding">
        {topEvent && <div className="finding-label">Highest priority now</div>}
        {topEvent ? (
          <button
            className="finding-event"
            onClick={() => onSelectTop(topEvent.id)}
            title={topEvent.title}
          >
            <span className="finding-title">{topEvent.title}</span>
            <span className="finding-meta">
              <span className="sev" style={{ color: prioColor(topEvent.priority) }}>
                <span className="sevdot" style={{ background: prioColor(topEvent.priority) }} />
                {prioLabel(topEvent.priority)}
              </span>
              <span>{typeLabel(topEvent.type)}</span>
              {topEvent.magnitude != null && (
                <span className="mono">M{topEvent.magnitude.toFixed(1)}</span>
              )}
              <span>
                Priority {topEvent.score.toFixed(1)}/10
              </span>
              {topEvent.source_count > 1 && (
                <span>{topEvent.source_count} sources merged</span>
              )}
              <span className="mono">{fmtRel(topEvent.occurred_at)}</span>
            </span>
          </button>
        ) : (
          <>
            <span className="finding-title" style={{ color: "var(--muted)" }}>
              {filteredCount === 0 && kpi ? "No events match this filter" : "No active events in view"}
            </span>
            <span className="finding-meta">
              {kpi ? "Clear the filter to widen the watch." : "Run Ingest to pull the latest BMKG feeds."}
            </span>
          </>
        )}
      </div>

      <div className="situation-right">
        {analytics && <Trend analytics={analytics} />}
        <nav className="kpis" aria-label="Situation filters">
          {items.map((it) => (
            <button
              key={it.key}
              className={`kpi ${kpi === it.key ? "on" : ""} ${it.v === 0 ? "zero" : ""}`}
              onClick={() => onToggle(it.key)}
              title={`${HINTS[it.key]}. Click to filter, click again to clear.`}
              aria-pressed={kpi === it.key}
            >
              <span className="kpi-v">{it.v}</span>
              <span className="kpi-l">{it.l}</span>
            </button>
          ))}
        </nav>
      </div>
    </section>
  );
}
