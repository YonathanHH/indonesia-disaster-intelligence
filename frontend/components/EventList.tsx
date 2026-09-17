"use client";
import { useEffect, useRef } from "react";
import type { BMKGEvent } from "../lib/types";
import { Badge, EmptyState, SectionHead, SkeletonRows, TypeMark } from "./ui";
import { fmtRel, prioColor, typeLabel } from "../lib/format";

export type SortMode = "score" | "newest" | "oldest" | "magnitude";

export default function EventList({
  events,
  filtered,
  loading,
  selectedId,
  hoverId,
  sortMode,
  onSort,
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
  onSort: (m: SortMode) => void;
  onSelect: (id: string) => void;
  onHover: (id: string | null) => void;
  onClearFilters: () => void;
}) {
  const rowRefs = useRef<Map<string, HTMLButtonElement>>(new Map());

  // keep the selected row visible when selection comes from the map/feed
  useEffect(() => {
    if (!selectedId) return;
    rowRefs.current.get(selectedId)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [selectedId]);
  return (
    <section className="panel" style={{ flex: "1.25" }} aria-label="Priority intelligence">
      <SectionHead title="Priority intelligence" count={`${filtered.length}/${events.length}`}>
        <label className="layerchk" style={{ gap: 4 }}>
          <span className="sr-only">Sort</span>
          <select
            value={sortMode}
            onChange={(e) => onSort(e.target.value as SortMode)}
            title="Sort order"
            aria-label="Sort priority intelligence"
            style={{ height: 22, fontSize: 10, padding: "0 4px" }}
          >
            <option value="score">SCORE</option>
            <option value="newest">NEWEST</option>
            <option value="oldest">OLDEST</option>
            <option value="magnitude">MAGNITUDE</option>
          </select>
        </label>
      </SectionHead>

      <div className="panelbody">
        {loading && events.length === 0 && <SkeletonRows n={6} h={52} />}

        {!loading && filtered.length === 0 && (
          <EmptyState
            title="No events match the current filters"
            sub="Adjust type, priority, search, or the status strip above."
            action={
              <button className="btn" onClick={onClearFilters}>
                Clear all filters
              </button>
            }
          />
        )}

        {filtered.map((e, i) => (
          <button
            key={e.id}
            ref={(el) => {
              if (el) rowRefs.current.set(e.id, el);
              else rowRefs.current.delete(e.id);
            }}
            className={`evrow sev-${e.priority} type-${e.type} ${e.id === selectedId ? "sel" : ""} ${e.id === hoverId ? "hl" : ""}`}
            onClick={() => onSelect(e.id)}
            onMouseEnter={() => onHover(e.id)}
            onMouseLeave={() => onHover(null)}
            onFocus={() => onHover(e.id)}
            onBlur={() => onHover(null)}
            title={e.title}
          >
            <span className="rank">{String(i + 1).padStart(2, "0")}</span>
            <span className="main">
              <span className="t">{e.title}</span>
              <span className="meta">
                <Badge prio={e.priority} />
                <span className="m type">
                  <TypeMark type={e.type} />
                  {typeLabel(e.type)}
                </span>
                {e.magnitude != null && <span className="m mag">M{e.magnitude.toFixed(1)}</span>}
                {e.depth_km != null && <span className="m">{Math.round(e.depth_km)}km</span>}
                {e.status !== "active" && <span className="chip">RESOLVED</span>}
              </span>
            </span>
            <span className="side">
              <span className="score" style={{ color: prioColor(e.priority) }}>
                {e.score.toFixed(1)}
              </span>
              <span className="rel">{fmtRel(e.occurred_at)}</span>
            </span>
          </button>
        ))}
      </div>
    </section>
  );
}
