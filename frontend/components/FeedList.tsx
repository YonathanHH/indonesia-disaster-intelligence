"use client";
import type { BMKGEvent, FeedItem } from "../lib/types";
import { EmptyState, SectionHead, TypeMark } from "./ui";
import { fmtRel, typeLabel } from "../lib/format";

const KIND_LABEL: Record<string, string> = {
  new_event: "NEW EVENT",
  observation: "OBS",
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
  return (
    <section className="panel" style={{ flex: "1" }} aria-label="Event feed">
      <SectionHead title="Event feed" count={feed.length} note="chronological" />
      <div className="panelbody">
        {feed.length === 0 && (
          <EmptyState title="No recent activity" sub="Run Ingest to pull the latest BMKG feeds." />
        )}
        {feed.map((f, i) => {
          const key = `${f.ts}-${f.event_id ?? f.title}-${i}`;
          const clickable = !!f.event_id;
          const linked = (f.event_id && eventsById.get(f.event_id)) || null;
          const body = (
            <>
              <span className="bar" />
              <span style={{ minWidth: 0 }}>
                <span className="head">
                  <span className="kind">{KIND_LABEL[f.kind] ?? f.kind.toUpperCase()}</span>
                  {linked && (
                    <span className="ftype">
                      <TypeMark type={linked.type} size={7} />
                      {typeLabel(linked.type)}
                      {linked.magnitude != null && ` M${linked.magnitude.toFixed(1)}`}
                    </span>
                  )}
                  <span className="time" title={f.ts}>{fmtRel(f.ts)}</span>
                </span>
                <span className="t" style={{ display: "block" }}>{f.title || "—"}</span>
                {f.detail && <span className="src" style={{ display: "block" }}>{f.detail}</span>}
              </span>
            </>
          );
          return clickable ? (
            <button key={key} className={`feedrow fk-${f.kind}`} onClick={() => onSelect(f.event_id!)}>
              {body}
            </button>
          ) : (
            <div key={key} className={`feedrow fk-${f.kind}`} role="listitem">
              {body}
            </div>
          );
        })}
      </div>
    </section>
  );
}
