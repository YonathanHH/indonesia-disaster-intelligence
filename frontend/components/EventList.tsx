"use client";
import { useEffect, useRef } from "react";
import type { BMKGEvent } from "../lib/types";
import { EmptyState, SectionHead, TypeMark } from "./ui";
import { fmtRel, prioColor, prioLabel, typeLabel } from "../lib/format";

export type SortMode = "score" | "newest" | "oldest" | "magnitude";

const SORT_LABEL: Record<SortMode, string> = {
  score: "Score",
  newest: "Newest",
  oldest: "Oldest",
  magnitude: "Magnitude",
};

export default function EventList({
  events,
  filtered,
  loading,
  selectedId,
  hoverId,
  sortMode,
  typeF,
  prioF,
  query,
  hasFilters,
  onSort,
  onType,
  onPriority,
  onQuery,
  onSelect,
  onHover,
  onClearFilters,
}: {
  events: BMKGEvent[];
  filtered: BMKGEvent[];
  loading: boolean;
  selectedId: string | null;
  hoverId: string | null;
  sortMode: SortMode;
  typeF: string;
  prioF: string;
  query: string;
  hasFilters: boolean;
  onSort: (m: SortMode) => void;
  onType: (v: string) => void;
  onPriority: (v: string) => void;
  onQuery: (v: string) => void;
  onSelect: (id: string) => void;
  onHover: (id: string | null) => void;
  onClearFilters: () => void;
}) {
  const rowRefs = useRef<Map<string, HTMLButtonElement>>(new Map());

  // keep the selected row visible when selection comes from the map or activity list
  useEffect(() => {
    if (!selectedId) return;
    rowRefs.current.get(selectedId)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [selectedId]);

  return (
    <section className="panel" style={{ flex: "1 1 auto" }} aria-label="Priority events">
      <SectionHead
        title="Priority events"
        count={hasFilters ? `${filtered.length} of ${events.length}` : `${filtered.length} ranked`}
      >
        <select
          value={sortMode}
          onChange={(e) => onSort(e.target.value as SortMode)}
          title="Sort priority events"
          aria-label="Sort priority events"
        >
          {(Object.keys(SORT_LABEL) as SortMode[]).map((m) => (
            <option key={m} value={m}>
              {SORT_LABEL[m]}
            </option>
          ))}
        </select>
      </SectionHead>

      <div className="filters">
        <input
          placeholder="Search events"
          value={query}
          onChange={(e) => onQuery(e.target.value)}
          aria-label="Search events"
        />
        <div className="filter-row">
          <select value={typeF} onChange={(e) => onType(e.target.value)} aria-label="Filter by hazard type">
            <option value="">All hazards</option>
            <option value="earthquake">Earthquakes</option>
            <option value="severe_weather">Severe weather</option>
            <option value="tsunami_alert">Tsunami</option>
          </select>
          <select value={prioF} onChange={(e) => onPriority(e.target.value)} aria-label="Filter by priority">
            <option value="">All priorities</option>
            <option value="CRITICAL">Critical</option>
            <option value="HIGH">High</option>
            <option value="MODERATE">Moderate</option>
            <option value="LOW">Low</option>
          </select>
        </div>
        {hasFilters && filtered.length > 0 && (
          <div className="filter-state">
            <span>{filtered.length} matching events</span>
            <span className="grow" />
            <button onClick={onClearFilters}>Clear filters</button>
          </div>
        )}
      </div>

      <div className="panelbody">
        {loading && events.length === 0 && <SkeletonRows n={7} h={57} />}

        {!loading && filtered.length === 0 && (
          <EmptyState
            title="No events match the current filters"
            sub="Clear the hazard, priority or situation filter to widen the watch."
            action={
              hasFilters ? (
                <button className="btn" onClick={onClearFilters}>
                  Clear filters
                </button>
              ) : undefined
            }
          />
        )}

        {filtered.map((e, i) => {
          const color = prioColor(e.priority);
          return (
            <button
              key={e.id}
              ref={(el) => {
                if (el) rowRefs.current.set(e.id, el);
                else rowRefs.current.delete(e.id);
              }}
              className={`evrow ${e.id === selectedId ? "sel" : ""} ${
                e.id === hoverId ? "hl" : ""
              } ${e.status !== "active" ? "resolved" : ""}`}
              onClick={() => onSelect(e.id)}
              onMouseEnter={() => onHover(e.id)}
              onMouseLeave={() => onHover(null)}
              onFocus={() => onHover(e.id)}
              onBlur={() => onHover(null)}
              title={e.title}
              aria-current={e.id === selectedId ? "true" : undefined}
            >
              <span className="rank">{i + 1}</span>
              <span className="ev-main">
                <span className="ev-title">{e.title}</span>
                <span className="ev-meta">
                  <span className="ev-sev" style={{ color }}>
                    <span className="sevdot" style={{ background: color }} />
                    {prioLabel(e.priority)}
                  </span>
                  <span className="ev-type">
                    <TypeMark type={e.type} />
                    {typeLabel(e.type)}
                  </span>
                  {e.magnitude != null && <span className="ev-mag">M{e.magnitude.toFixed(1)}</span>}
                  {e.source_count > 1 && <span className="ev-src">{e.source_count} src</span>}
                  {e.status !== "active" && <span className="ev-resolved">Resolved</span>}
                </span>
              </span>
              <span className="ev-side">
                <span className="ev-score">{e.score.toFixed(1)}</span>
                <span className="ev-time">{fmtRel(e.occurred_at)}</span>
              </span>
            </button>
          );
        })}
      </div>
    </section>
  );
}

function SkeletonRows({ n = 6, h = 57 }: { n?: number; h?: number }) {
  return (
    <div
      style={{ padding: "12px 16px", display: "flex", flexDirection: "column", gap: 10 }}
      aria-busy="true"
      aria-label="Loading"
    >
      {Array.from({ length: n }).map((_, i) => (
        <div key={i} className="skel" style={{ height: h }} />
      ))}
    </div>
  );
}
