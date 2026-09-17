"use client";
import type { EventDetail, Overview } from "../lib/types";
import { Badge, EmptyState, SkeletonRows } from "./ui";
import { fmtClock, fmtRel, fmtWIB, prioColor, typeLabel } from "../lib/format";

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
      {method && (
        <div style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--faint)", marginBottom: 8 }}>
          METHOD {String(method).toUpperCase()}
        </div>
      )}
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
                  background: n < 0 ? "var(--crit)" : "var(--accent)",
                  left: 0,
                }}
              />
            </span>
            <span className="cv" style={{ color: n < 0 ? "var(--crit)" : undefined }}>
              {n > 0 ? `+${n}` : `${n}`}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function Observations({ obs }: { obs: EventDetail["observations"] }) {
  if (obs.length === 0) return <p style={{ fontSize: 12, color: "var(--faint)" }}>No linked observations.</p>;
  return (
    <div>
      {obs.map((o) => (
        <div key={o.id} className="obsrow">
          <div className="head">
            <span className="chip">{o.source}</span>
            <span className="chip">{o.kind}</span>
            <span className="mono" style={{ fontSize: 10, color: "var(--faint)" }}>{fmtClock(o.observed_at)}</span>
          </div>
          <div style={{ marginTop: 2 }}>{o.text}</div>
          <div style={{ marginTop: 3, fontSize: 11 }}>
            {o.url && (
              <a href={o.url} target="_blank" rel="noreferrer">source link</a>
            )}
            {o.author && <span style={{ color: "var(--faint)" }}> · {o.author}</span>}
          </div>
        </div>
      ))}
    </div>
  );
}

export default function EventDetail({
  detail,
  loading,
  onResolve,
  resolving,
}: {
  detail: EventDetail | null;
  loading: boolean;
  onResolve: (id: string) => void;
  resolving: boolean;
}) {
  if (loading && !detail) {
    return (
      <div className="panel" style={{ height: "100%" }}>
        <div className="panelhead"><span className="title">Event detail</span></div>
        <div className="panelbody"><SkeletonRows n={6} h={36} /></div>
      </div>
    );
  }
  if (!detail) return null;
  const c = prioColor(detail.priority);
  return (
    <div className="panel" style={{ height: "100%" }}>
      <div className="panelhead">
        <span className="title">Event detail</span>
        <span className="grow" />
        {detail.status === "active" ? (
          <button className="btn" onClick={() => onResolve(detail.id)} disabled={resolving}>
            {resolving ? "Resolving…" : "✓ Resolve"}
          </button>
        ) : (
          <span className="chip">RESOLVED</span>
        )}
      </div>

      <div className="detailbody">
        <div className="dt-head">
          <Badge prio={detail.priority} />
          <span className="chip">{typeLabel(detail.type)}</span>
          <span className="mono" style={{ fontSize: 10, color: "var(--faint)" }}>
            {detail.source_count} source{detail.source_count === 1 ? "" : "s"}
          </span>
        </div>
        <h2 className="dt-title">{detail.title}</h2>

        <div style={{ fontSize: 9.5, fontWeight: 700, letterSpacing: "0.1em", color: "var(--faint)", marginTop: 12 }}>
          INTELLIGENCE PRIORITY <span style={{ fontWeight: 400, letterSpacing: 0 }}>· guides attention, not a risk estimate</span>
        </div>
        <div className="scorebar" style={{ marginTop: 5 }} aria-label={`Intelligence priority score ${detail.score.toFixed(1)} of 10`}>
          <span className="track">
            <span className="fill" style={{ width: `${detail.score * 10}%`, background: c }} />
          </span>
          <span className="val">{detail.score.toFixed(1)}/10</span>
        </div>

        <dl className="kv">
          <dt>Time (WIB)</dt><dd>{fmtWIB(detail.occurred_at)}</dd>
          <dt>Location</dt><dd>{detail.latitude.toFixed(3)}, {detail.longitude.toFixed(3)}</dd>
          {detail.magnitude != null && (<><dt>Magnitude</dt><dd>M{detail.magnitude.toFixed(1)}</dd></>)}
          {detail.depth_km != null && (<><dt>Depth</dt><dd>{detail.depth_km} km</dd></>)}
          {detail.expires_at && (<><dt>Expires</dt><dd>{fmtWIB(detail.expires_at)}</dd></>)}
        </dl>

        {detail.ai_assessment && (
          <>
            <div className="sect">Intelligence assessment</div>
            <div className="assess">{detail.ai_assessment}</div>
            <div style={{ fontSize: 10, color: "var(--faint)", marginTop: -2, marginBottom: 8 }}>
              Interpretive — not BMKG-verified. Facts above.
            </div>
          </>
        )}

        <div className="sect">Score breakdown</div>
        <ScoreBreakdown bd={detail.score_breakdown} />

        {detail.cluster && (
          <>
            <div className="sect">Sequence · {detail.cluster.cluster_id}</div>
            <div style={{ fontSize: 12, color: "var(--dim)", lineHeight: 1.55 }}>
              Part of a {detail.cluster.member_count}-event sequence
              (mainshock M{detail.cluster.mainshock_magnitude}).
              Related events are developing as one situation, not isolated incidents.
              <div style={{ marginTop: 4, fontSize: 11, color: "var(--faint)" }}>
                System-derived cluster (sequence-v1) — see briefing watchlist for the full chain.
              </div>
            </div>
          </>
        )}

        {detail.exposure && (
          <>
            <div className="sect">
              Exposure · {detail.exposure.class}{" "}
              <span className="note">heuristic, {detail.exposure.confidence} confidence</span>
            </div>
            <div style={{ fontSize: 12, color: "var(--dim)", lineHeight: 1.55 }}>
              {detail.exposure.coastal_threat && (
                <div style={{ marginBottom: 4 }}>
                  <span className="badge b-CRITICAL">COASTAL THREAT</span>{" "}
                  BMKG tsunami bulletin active — treat nearby coasts as exposed until cleared.
                </div>
              )}
              {detail.exposure.nearest_cities.length > 0 ? (
                <div>
                  Nearest cities (epicentral):{" "}
                  {detail.exposure.nearest_cities.slice(0, 3).map((nc, i) => (
                    <span key={nc.city}>
                      {i > 0 && " · "}{nc.city} ~{nc.km} km
                    </span>
                  ))}
                  {detail.exposure.felt_areas > 0 && ` · felt in ${detail.exposure.felt_areas} area(s)`}
                </div>
              ) : (
                <div>
                  No major city within 150 km of the epicenter
                  {detail.exposure.felt_areas > 0 && ` · felt in ${detail.exposure.felt_areas} area(s)`}.
                </div>
              )}
              {detail.exposure.assets.slice(0, 2).map((a) => (
                <div key={a} style={{ marginTop: 4, fontSize: 11.5 }}>{a}</div>
              ))}
              <div style={{ marginTop: 4, fontSize: 10.5, color: "var(--faint)" }}>
                Heuristic overlay, not a loss estimate. Distances are epicentral, not shaking footprints.
              </div>
            </div>
          </>
        )}

        {detail.history_context && (
          <>
            <div className="sect">
              Historical context · {detail.history_context.class}{" "}
              <span className="note">vs {detail.history_context.observed.baseline_days}d regional BMKG record</span>
            </div>
            <div style={{ fontSize: 12, color: "var(--dim)", lineHeight: 1.55 }}>
              {detail.history_context.observed.recent_count} regional event(s) in the last{" "}
              {detail.history_context.observed.recent_days} days vs ~
              {detail.history_context.observed.expected_7d} expected
              {detail.history_context.observed.largest_in_days != null &&
                ` · largest M in ${detail.history_context.observed.largest_in_days}d+ of record`}{" "}
              ({detail.history_context.confidence} confidence).
              <div style={{ marginTop: 4, fontSize: 10.5, color: "var(--faint)" }}>
                Observed counts from recorded history; the class is system interpretation, not a forecast.
              </div>
            </div>
          </>
        )}

        {detail.situations && detail.situations.length > 0 && (
          <>
            <div className="sect">
              Situations · {detail.situations.length}{" "}
              <span className="note">connected hazards, co-occurrence only</span>
            </div>
            {detail.situations.map((s) => (
              <div key={s.situation_id} style={{ marginBottom: 8, fontSize: 12, lineHeight: 1.55 }}>
                <span className={`urg ${s.severity === "CRITICAL" ? "u-immediate" : s.severity === "HIGH" ? "u-soon" : "u-routine"}`}>
                  {s.severity}
                </span>{" "}
                <span style={{ fontWeight: 600 }}>{s.title}</span>
                <div style={{ color: "var(--dim)", marginTop: 2 }}>{s.interpretation}</div>
                <div style={{ fontSize: 10.5, color: "var(--faint)", marginTop: 2 }}>
                  {s.kind} · {s.member_ids.length} linked · {s.confidence} confidence
                </div>
              </div>
            ))}
          </>
        )}

        <div className="sect">Observations · {detail.observations.length}</div>
        <Observations obs={detail.observations} />

        <div className="sect">History</div>
        {detail.history.map((h, i) => (
          <div key={i} className={`histrow h-${h.kind}`}>
            <span className="hdot" />
            <span style={{ flex: 1, minWidth: 0 }}>
              <span className="hkind">{h.kind.replace(/_/g, " ")}</span>
              <span className="hmsg">{h.message}</span>
            </span>
            <span className="ht" title={h.ts}>{fmtClock(h.ts)}</span>
          </div>
        ))}

        {detail.extra && (
          <details style={{ marginTop: 12 }}>
            <summary style={{ fontSize: 10, color: "var(--faint)", textTransform: "uppercase", letterSpacing: "0.08em", cursor: "pointer" }}>
              Provenance / raw
            </summary>
            <pre className="raw">{JSON.stringify(detail.extra, null, 2).slice(0, 3000)}</pre>
          </details>
        )}
      </div>
    </div>
  );
}

/** Default right-panel content when nothing is selected: collector health. */
export function CollectorHealth({ overview }: { overview: Overview | null }) {
  if (!overview) return null;
  const rows = Object.entries(overview.collectors);
  const okCount = rows.filter(([, c]) => !c.last_error && c.last_ok_at).length;
  return (
    <div className="panel" style={{ height: "100%" }}>
      <div className="panelhead">
        <span className="title">System status</span>
        <span className="count">{okCount}/{rows.length} OK</span>
      </div>
      <div className="detailbody">
        <div className="sect" style={{ marginTop: 0 }}>
          Collectors <span className="note">muted by design — errors surface here only</span>
        </div>
        {rows.length === 0 && (
          <EmptyState title="No ingest runs yet" sub="Press ↻ Ingest to run the collectors." />
        )}
        {rows.map(([name, c]) => {
          const bad = !!c.last_error;
          const fresh = c.last_ok_at ? fmtRel(c.last_ok_at) : "never";
          return (
            <div key={name} className={`crow ${bad ? "cerr" : ""}`} title={c.last_error ?? `last ok ${c.last_ok_at ?? "never"}`}>
              <span className="cn">{name}</span>
              <span className="cs">{c.items_fetched} items · {fresh}</span>
              <span className={`cs ${bad ? "cstate-err" : "cstate-ok"}`}>
                {bad ? "ERROR" : c.last_ok_at ? "OK" : "—"}
              </span>
              {bad && <span className="cerrmsg">{c.last_error}</span>}
            </div>
          );
        })}
        <div className="sect">How to read this console</div>
        <p style={{ fontSize: 12, color: "var(--dim)", lineHeight: 1.6 }}>
          Select an event in the list, on the map, or in the feed to inspect its
          facts, intelligence score, observations, and history.
          Scores are <em>intelligence priority</em> — they guide attention and
          are not validated risk estimates. Facts come from BMKG open feeds.
        </p>
        <p style={{ fontSize: 11, color: "var(--faint)", lineHeight: 1.6 }}>
          UPD {overview.last_update ? fmtWIB(overview.last_update) : "—"} WIB · auto-refresh 60s
        </p>
      </div>
    </div>
  );
}
