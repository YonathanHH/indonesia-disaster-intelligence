"use client";
import type { CSSProperties } from "react";
import type { EventDetail, Overview } from "../lib/types";
import { fmtClock, fmtRel, fmtWIB, prioColor, prioLabel, typeLabel } from "../lib/format";
import { EmptyState, SkeletonRows } from "./ui";

/** Human labels for score components (quake-v1 / weather-v1). */
const COMP_LABEL: Record<string, string> = {
  magnitude_base: "Magnitude base",
  severity_base: "Severity base",
  shallow: "Shallow ≤30km",
  intermediate: "Intermediate 30–70km",
  deep: "Deep ≥150km",
  very_deep: "Very deep ≥300km",
  felt_bonus: "Felt / MMI bonus",
  felt_areas: "Felt areas",
  tsunami_potential: "Tsunami potential",
  urgency: "Urgency",
  certainty: "Certainty",
  area_bonus: "Area coverage",
  hazard_bonus: "Hazard keywords",
  exposure_bonus: "Exposure corroboration",
  sequence_bonus: "Sequence activity",
  history_bonus: "Unusual regional activity",
};

function ScoreBreakdown({ bd }: { bd: Record<string, unknown> | null }) {
  if (!bd || typeof bd !== "object") return null;
  const comps = (bd as { components?: Record<string, unknown> }).components;
  const method = (bd as { method?: string }).method;
  if (!comps || typeof comps !== "object") return null;
  const entries = Object.entries(comps).filter(([, v]) => typeof v === "number");
  if (entries.length === 0) return null;
  const maxAbs = Math.max(...entries.map(([, v]) => Math.abs(v as number)), 0.01);
  return (
    <div>
      {method && <div className="note" style={{ marginBottom: 8 }}>Method {String(method)}</div>}
      {entries.map(([k, v]) => {
        const n = v as number;
        const pct = Math.min(100, (Math.abs(n) / maxAbs) * 100);
        return (
          <div key={k} className="comp">
            <span className="cl">{COMP_LABEL[k] ?? k.replace(/_/g, " ")}</span>
            <span className="ctrack">
              <span
                className="cfill"
                style={{
                  width: `${pct}%`,
                  background: n < 0 ? "var(--crit)" : undefined,
                }}
              />
            </span>
            <span className={`cv ${n < 0 ? "neg" : ""}`}>{n > 0 ? `+${n}` : `${n}`}</span>
          </div>
        );
      })}
    </div>
  );
}

function Observations({ obs }: { obs: EventDetail["observations"] }) {
  if (obs.length === 0) return <p className="note" style={{ margin: 0 }}>No linked observations.</p>;
  return (
    <div>
      {obs.map((o) => (
        <div key={o.id} className="obsrow">
          <div className="head">
            <span>{o.source}</span>
            <span>{o.kind}</span>
            <span className="mono" style={{ marginLeft: "auto" }}>{fmtClock(o.observed_at)}</span>
          </div>
          <div className="text">{o.text}</div>
          <div className="links">
            {o.url && (
              <a href={o.url} target="_blank" rel="noreferrer">
                Source link
              </a>
            )}
            {o.author && <span style={{ color: "var(--muted)" }}> · {o.author}</span>}
          </div>
        </div>
      ))}
    </div>
  );
}

export default function EventDetailPanel({
  detail,
  loading,
  onResolve,
  onClose,
  resolving,
}: {
  detail: EventDetail | null;
  loading: boolean;
  onResolve: (id: string) => void;
  onClose: () => void;
  resolving: boolean;
}) {
  if (loading && !detail) {
    return (
      <div className="panel" style={{ height: "100%" }}>
        <div className="panelhead">
          <span className="title">Event detail</span>
          <span className="grow" />
          <button className="btn btn-quiet" onClick={onClose}>Close</button>
        </div>
        <div className="panelbody"><SkeletonRows n={6} h={38} /></div>
      </div>
    );
  }

  if (!detail) {
    return (
      <div className="panel" style={{ height: "100%" }}>
        <div className="panelhead">
          <span className="title">Event detail</span>
          <span className="grow" />
          <button className="btn btn-quiet" onClick={onClose}>Close</button>
        </div>
        <EmptyState
          title="Event unavailable"
          sub="The event could not be loaded. It may have been removed from the feed."
          action={<button className="btn" onClick={onClose}>Back to list</button>}
        />
      </div>
    );
  }

  const c = prioColor(detail.priority);
  return (
    <div className="panel" style={{ height: "100%", "--sev": c } as CSSProperties}>
      <div className="panelhead">
        <span className="title">Event detail</span>
        <span className="grow" />
        {detail.status === "active" ? (
          <button className="btn" onClick={() => onResolve(detail.id)} disabled={resolving}>
            {resolving ? "Resolving…" : "Resolve event"}
          </button>
        ) : (
          <span className="note">Resolved</span>
        )}
        <button className="btn btn-quiet" onClick={onClose} title="Close detail">
          Close
        </button>
      </div>

      <div className="detailbody">
        <div className="dt-head">
          <span className="dt-sev" style={{ color: c }}>
            <span className="sevdot" style={{ background: c }} />
            {prioLabel(detail.priority)}
          </span>
          <span>{typeLabel(detail.type)}</span>
          <span>{detail.source_count} source{detail.source_count === 1 ? "" : "s"}</span>
        </div>
        <h2 className="dt-title">{detail.title}</h2>

        <div className="facts">
          <div className="fact">
            <dt>Occurred</dt>
            <dd>{fmtWIB(detail.occurred_at)}</dd>
          </div>
          <div className="fact">
            <dt>Location</dt>
            <dd>{detail.latitude.toFixed(3)}, {detail.longitude.toFixed(3)}</dd>
          </div>
          {detail.magnitude != null && (
            <div className="fact">
              <dt>Magnitude</dt>
              <dd>M{detail.magnitude.toFixed(1)}</dd>
            </div>
          )}
          {detail.depth_km != null && (
            <div className="fact">
              <dt>Depth</dt>
              <dd>{detail.depth_km} km</dd>
            </div>
          )}
          {detail.expires_at && (
            <div className="fact">
              <dt>Expires</dt>
              <dd>{fmtWIB(detail.expires_at)}</dd>
            </div>
          )}
        </div>

        <div className="score-block">
          <div className="score-head">
            <span className="score-label">Intelligence priority</span>
            <span className="score-value">
              {detail.score.toFixed(1)}
              <span> / 10</span>
            </span>
          </div>
          <div className="score-track">
            <div className="score-fill" style={{ width: `${detail.score * 10}%` }} />
          </div>
          <div className="score-note">Guides attention; not a risk estimate.</div>
        </div>

        {detail.ai_assessment && (
          <>
            <div className="sect">
              <span>Assessment</span>
              <span className="note">Interpretive</span>
            </div>
            <div className="assess">{detail.ai_assessment}</div>
            <p className="note" style={{ marginTop: 6 }}>
              Not BMKG-verified. Facts above come from the source feed.
            </p>
          </>
        )}

        <div className="sect">
          <span>Score breakdown</span>
          <span className="note">points of 10</span>
        </div>
        <ScoreBreakdown bd={detail.score_breakdown} />

        {detail.cluster && (
          <>
            <div className="sect">
              <span>Sequence</span>
              <span className="note">{detail.cluster.cluster_id}</span>
            </div>
            <p className="prose" style={{ margin: 0 }}>
              Part of a {detail.cluster.member_count}-event sequence around a
              M{detail.cluster.mainshock_magnitude} mainshock. Related events are
              developing as one situation, not isolated incidents.
            </p>
            <p className="note" style={{ marginTop: 4 }}>
              System-derived cluster (sequence-v1). The briefing shows the full chain.
            </p>
          </>
        )}

        {detail.exposure && (
          <>
            <div className="sect">
              <span>Exposure</span>
              <span className="note">
                {detail.exposure.class} · {detail.exposure.confidence} confidence
              </span>
            </div>
            {detail.exposure.coastal_threat && (
              <p className="prose" style={{ marginTop: 0 }}>
                <span className="sevword" style={{ color: "var(--crit)" }}>
                  <span className="sevdot" style={{ background: "var(--crit)" }} />
                  Coastal threat
                </span>{" "}
                BMKG tsunami bulletin active. Treat nearby coasts as exposed until cleared.
              </p>
            )}
            {detail.exposure.nearest_cities.length > 0 ? (
              <ul className="mini">
                {detail.exposure.nearest_cities.slice(0, 3).map((nc) => (
                  <li key={nc.city}>
                    <span>{nc.city}, {nc.province}</span>
                    <span className="mono">{nc.km} km</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="prose" style={{ margin: 0 }}>
                No major city within 150 km of the epicentre.
              </p>
            )}
            {detail.exposure.felt_areas > 0 && (
              <p className="note" style={{ marginTop: 6 }}>
                Felt in {detail.exposure.felt_areas} area{detail.exposure.felt_areas === 1 ? "" : "s"}.
              </p>
            )}
            {detail.exposure.assets.slice(0, 2).map((a) => (
              <p key={a} className="prose" style={{ marginTop: 6, marginBottom: 0 }}>{a}</p>
            ))}
            <p className="note" style={{ marginTop: 6 }}>
              Heuristic overlay, not a loss estimate. Distances are epicentral.
            </p>
          </>
        )}

        {detail.history_context && (
          <>
            <div className="sect">
              <span>Regional history</span>
              <span className="note">{detail.history_context.class}</span>
            </div>
            <p className="prose" style={{ margin: 0 }}>
              {detail.history_context.observed.recent_count} regional event
              {detail.history_context.observed.recent_count === 1 ? "" : "s"} in the last{" "}
              {detail.history_context.observed.recent_days} days, against about{" "}
              {detail.history_context.observed.expected_7d} expected over the{" "}
              {detail.history_context.observed.baseline_days}-day BMKG record.
              {detail.history_context.observed.largest_in_days != null &&
                ` Largest magnitude in ${detail.history_context.observed.largest_in_days}+ days.`}
            </p>
            <p className="note" style={{ marginTop: 4 }}>
              Observed counts from recorded history; the class is interpretation, not a forecast.
            </p>
          </>
        )}

        {detail.situations.length > 0 && (
          <>
            <div className="sect">
              <span>Situations</span>
              <span className="note">co-occurrence, not causality</span>
            </div>
            {detail.situations.map((s) => {
              const sc =
                s.severity === "CRITICAL" ? "var(--crit)" : s.severity === "HIGH" ? "var(--high)" : "var(--muted)";
              return (
                <div key={s.situation_id} className="sitrow">
                  <div className="sit-head">
                    <span className="sevword" style={{ color: sc }}>
                      <span className="sevdot" style={{ background: sc }} />
                      {prioLabel(s.severity)}
                    </span>
                    <span className="sit-title">{s.title}</span>
                  </div>
                  <div className="sit-text">{s.interpretation}</div>
                  <div className="sit-meta">
                    {s.kind.replace(/_/g, " ")} · {s.member_ids.length} linked · {s.confidence} confidence
                  </div>
                </div>
              );
            })}
          </>
        )}

        <div className="sect">
          <span>Observations</span>
          <span className="note">{detail.observations.length}</span>
        </div>
        <Observations obs={detail.observations} />

        <div className="sect">
          <span>Event log</span>
          <span className="note">oldest first</span>
        </div>
        {detail.history.length === 0 && <p className="note" style={{ margin: 0 }}>No recorded changes.</p>}
        {detail.history.map((h, i) => (
          <div key={i} className={`histrow h-${h.kind}`}>
            <span className="hdot" />
            <span style={{ minWidth: 0 }}>
              <span className="hkind">{h.kind.replace(/_/g, " ")}</span>
              <span className="hmsg">{h.message}</span>
            </span>
            <span className="ht" title={h.ts}>{fmtClock(h.ts)}</span>
          </div>
        ))}

        {detail.extra && (
          <details>
            <summary>Raw provenance</summary>
            <pre className="raw">{JSON.stringify(detail.extra, null, 2).slice(0, 3000)}</pre>
          </details>
        )}
      </div>
    </div>
  );
}

/** Compact feed health for the footer, kept out of the working canvas. */
export function FeedsBar({ overview }: { overview: Overview | null }) {
  if (!overview) return null;
  const rows = Object.entries(overview.collectors);
  return (
    <footer className="feedsbar" aria-label="Data feed health">
      <span className="feeds-label">Feeds</span>
      {rows.map(([name, c]) => {
        const bad = !!c.last_error;
        const fresh = c.last_ok_at ? fmtRel(c.last_ok_at) : "never";
        return (
          <span
            key={name}
            className={`feedstate ${bad ? "err" : ""}`}
            title={
              bad
                ? `${name}: ${c.last_error}`
                : `${name}: last ok ${c.last_ok_at ?? "never"}`
            }
          >
            <span className="dot" />
            <span className="fname">{name}</span>
            <span className="fmeta">{c.items_fetched} items · {fresh}</span>
            {bad && <span className="ferr">{c.last_error}</span>}
          </span>
        );
      })}
      <span className="feeds-right">
        Updated {fmtWIB(overview.last_update)} WIB · refreshes every 60 s · BMKG open data
      </span>
    </footer>
  );
}
