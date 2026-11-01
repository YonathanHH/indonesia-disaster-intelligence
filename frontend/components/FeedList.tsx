"use client";
import type { BMKGEvent, FeedItem } from "../lib/types";
import { EmptyState, SectionHead, TypeMark } from "./ui";
import { fmtRel, typeLabel } from "../lib/format";

const KIND_LABEL: Record<string, string> = {
  new_event: "Detected",
  observation: "Observed",
};

export default function FeedList({
  feed,
  eventsById,
  onSelect,
}: {
  feed: FeedItem[];
  eventsById: Map<string, BMKGEvent>;
  onSelect: (id: string) => void;
}) {
  // the API emits the same observation more than once; keep the first of each
  const seen = new Set<string>();
  const items = feed.filter((f) => {
    const k = `${f.ts}|${f.kind}|${f.event_id ?? ""}|${f.title}`;
    if (seen.has(k)) return false;
    seen.add(k);
    return true;
  });
  return (
    <section className="panel" style={{ flex: "0 0 150px" }} aria-label="Recent activity">
      <SectionHead title="Recent activity" count={items.length} note="newest first" />
      <div className="panelbody">
        {items.length === 0 && (
          <EmptyState title="No recent activity" sub="Run Ingest to pull the latest BMKG observations." />
        )}
        {items.map((f, i) => {
          const key = `${f.ts}-${f.event_id ?? f.title}-${i}`;
          const clickable = !!f.event_id;
          const linked = (f.event_id && eventsById.get(f.event_id)) || null;
          const body = (
            <>
              <span className="feed-kind">
                <span className="sevdot" />
                {KIND_LABEL[f.kind] ?? f.kind.replace(/_/g, " ")}
              </span>
              <span className="feed-title">
                {linked && <TypeMark type={linked.type} size={7} />}
                {f.title || "Untitled item"}
              </span>
              <span className="feed-time" title={f.ts}>
                {fmtRel(f.ts)}
              </span>
            </>
          );
          const tip = [
            KIND_LABEL[f.kind] ?? f.kind.replace(/_/g, " "),
            f.title,
            linked ? typeLabel(linked.type) : null,
            linked?.magnitude != null ? `M${linked.magnitude.toFixed(1)}` : null,
            f.detail,
          ]
            .filter(Boolean)
            .join(" · ");
          return clickable ? (
            <button
              key={key}
              className={`feedrow fk-${f.kind}`}
              onClick={() => onSelect(f.event_id!)}
              title={tip}
            >
              {body}
            </button>
          ) : (
            <div key={key} className={`feedrow fk-${f.kind}`} role="listitem" title={tip}>
              {body}
            </div>
          );
        })}
      </div>
    </section>
  );
}
