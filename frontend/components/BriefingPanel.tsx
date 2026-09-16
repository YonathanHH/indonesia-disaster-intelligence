"use client";
import { useEffect, useRef } from "react";
import type { Briefing, ChangeItem } from "../lib/types";
import { Badge } from "./ui";
import { fmtWIB } from "../lib/format";

const LLM_STATUS_LABEL: Record<string, string> = {
  off: "AI note off — no key",
  misconfigured: "AI note unavailable — model not configured",
  empty: "AI note withheld — empty response",
  rejected: "AI note withheld — failed validation",
  error: "AI note unavailable — request failed",
};

const URG_ORDER = ["immediate", "soon", "routine"] as const;
const URG_LABEL: Record<string, string> = {
  immediate: "Immediate",
  soon: "Soon",
  routine: "Routine",
};

export default function BriefingPanel({
  briefing,
  loading,
  error,
  onClose,
  onRefresh,
  onSelectEvent,
}: {
  briefing: Briefing | null;
  loading: boolean;
  error?: string | null;
  onClose: () => void;
  onRefresh: () => void;
  onSelectEvent: (id: string) => void;
}) {
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const aiActive = !!briefing?.llm_summary;
  const dev = briefing?.developments;

  const renderChanges = (label: string, items: ChangeItem[], tone: string) => {
    if (!items || items.length === 0) return null;
    return (
      <div style={{ marginTop: 8 }}>
        <span className="chip" style={{ color: tone }}>
          {label} · {items.length}
        </span>
        {items.slice(0, 3).map((it) => (
          <button
            key={it.event_id}
            className="wlrow"
            onClick={() => { onSelectEvent(it.event_id); onClose(); }}
            title={it.detail || it.title}
          >
            <span className="wrank">→</span>
            <span style={{ minWidth: 0 }}>
              <span className="wt" style={{ display: "block" }}>{it.title}</span>
              <span className="wmeta">
                <Badge prio={it.priority} />
                <span className="m">{it.detail || fmtWIB(it.occurred_at)}</span>
              </span>
            </span>
          </button>
        ))}
        {items.length > 3 && (
          <div style={{ fontSize: 11, color: "var(--faint)", padding: "2px 0 0 30px" }}>
            +{items.length - 3} more
          </div>
        )}
      </div>
    );
  };

  return (
    <>
      <div className="drawer-backdrop" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-modal="true" aria-label="Executive briefing">
        <div className="drawer-head">
          <div>
            <div className="sect" style={{ padding: 0, margin: 0 }}>Executive briefing</div>
            <div style={{ fontSize: 11, color: "var(--faint)", fontFamily: "var(--mono)" }}>
              {briefing ? fmtWIB(briefing.generated_at) : "—"} WIB
            </div>
          </div>
          <div style={{ display: "flex", gap: 6 }}>
            <button className="btn" onClick={onRefresh} title="Regenerate briefing">↻ Regenerate</button>
            <button className="btn" ref={closeRef} onClick={onClose} title="Close (Esc)">✕</button>
          </div>
        </div>

        {loading && (
          <div className="brief-body">
            {[56, 120, 200].map((h, i) => (
              <div key={i} className="skel" style={{ height: h, marginBottom: 12 }} />
            ))}
          </div>
        )}

        {!loading && error && !briefing && (
          <div className="brief-body">
            <p style={{ fontSize: 13 }}>⚠ Briefing failed: {error}</p>
            <button className="btn" onClick={onRefresh}>Retry</button>
          </div>
        )}

        {briefing && (
          <div className="brief-body">
            <div className="brief-masthead">
              <div className="bm-kicker">BMKG Intelligence · Situation Brief</div>
              <h2 className="brief-headline">{briefing.headline}</h2>
              <div className="brief-meta">
                <span>ISSUED {fmtWIB(briefing.generated_at)} WIB</span>
                <span>
                  {aiActive ? `AI NOTE · ${briefing.llm_model}` : `DETERMINISTIC · ${LLM_STATUS_LABEL[briefing.llm_status ?? ""] ?? "AI note unavailable"}`}
                </span>
              </div>
            </div>

            {briefing.escalation && briefing.escalation.level !== "NORMAL" && (
              <div
                role="alert"
                style={{
                  marginTop: 12,
                  border: `1px solid ${briefing.escalation.level === "ALERT" ? "var(--crit)" : "var(--mod)"}`,
                  borderRadius: "var(--r2)",
                  padding: "10px 12px",
                  background: briefing.escalation.level === "ALERT"
                    ? "rgba(255, 93, 93, 0.08)" : "rgba(245, 197, 24, 0.07)",
                }}
              >
                <span className={`urg ${briefing.escalation.level === "ALERT" ? "u-immediate" : "u-soon"}`}>
                  {briefing.escalation.level}
                </span>
                <div style={{ fontSize: 12.5, fontWeight: 600, marginTop: 6 }}>
                  {briefing.escalation.posture}
                </div>
                {briefing.escalation.triggers.map((t) => (
                  <div key={t.trigger_id} style={{ marginTop: 8 }}>
                    <div style={{ fontSize: 12, fontWeight: 600 }}>{t.title}</div>
                    <div style={{ fontSize: 11.5, color: "var(--dim)" }}>{t.why}</div>
                    <div style={{ fontSize: 10, color: "var(--faint)", fontFamily: "var(--mono)", marginTop: 2 }}>
                      {t.rule} · {t.confidence} confidence
                    </div>
                    {t.event_ids.length > 0 && (
                      <div className="alinks" style={{ marginTop: 4 }}>
                        {t.event_ids.slice(0, 3).map((id) => (
                          <button key={id} className="btn btn-ghost" style={{ padding: "2px 6px" }} onClick={() => { onSelectEvent(id); onClose(); }}>
                            Open event →
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}

            <section className="brief-sec">
              <span className="bs-title"><span className="bs-num">01</span>Situation assessment</span>
              <ul style={{ margin: "8px 0 0", paddingLeft: 18, fontSize: 13 }}>
                {briefing.overview.map((line, i) => (
                  <li key={i} style={{ marginBottom: 5, lineHeight: 1.5 }}>{line}</li>
                ))}
              </ul>
            </section>

            <section className="brief-sec">
              <span className="bs-title"><span className="bs-num">02</span>What changed · 24h</span>
              {dev && (
                <>
                  <div style={{ fontSize: 12, color: "var(--dim)", marginTop: 6 }}>
                    {dev.counts.new} new · {dev.counts.escalated} escalated ·{" "}
                    {dev.counts.de_escalated} de-escalated · {dev.counts.resolved} resolved ·{" "}
                    {dev.counts.expired} past expiry
                    {dev.counts.growing_sequences > 0 &&
                      ` · ${dev.counts.growing_sequences} growing sequence(s)`}
                  </div>
                  {renderChanges("ESCALATED", dev.escalated, "var(--crit)")}
                  {renderChanges("NEW", dev.new_events, "var(--accent)")}
                  {renderChanges("EXPIRED", dev.expired, "var(--mod)")}
                  {renderChanges("RESOLVED", dev.resolved, "var(--low)")}
                  {dev.growing_sequences.length > 0 && (
                    <div style={{ marginTop: 8 }}>
                      <span className="chip" style={{ color: "var(--mod)" }}>
                        SEQUENCES · {dev.growing_sequences.length}
                      </span>
                      {dev.growing_sequences.slice(0, 2).map((g) => {
                        const full = briefing.sequences.find((s) => s.cluster_id === g.cluster_id);
                        const hc = full?.history?.class;
                        return (
                          <button
                            key={g.cluster_id}
                            className="wlrow"
                            onClick={() => { onSelectEvent(g.mainshock_id); onClose(); }}
                          >
                            <span className="wrank">≋</span>
                            <span style={{ minWidth: 0 }}>
                              <span className="wt" style={{ display: "block" }}>
                                {g.cluster_id} · {g.member_count} events · mainshock M{g.mainshock_magnitude}
                              </span>
                              <span className="wmeta">
                                <span className="m">{g.mainshock_title}</span>
                                {hc && hc !== "NORMAL" && (
                                  <span className="chip" title="Behavior vs regional history">
                                    {hc}
                                  </span>
                                )}
                              </span>
                            </span>
                          </button>
                        );
                      })}
                    </div>
                  )}
                </>
              )}
            </section>

            <section className="brief-sec">
              <span className="bs-title">
                <span className="bs-num">03</span>Priority watchlist
                <span style={{ fontWeight: 400, textTransform: "none", letterSpacing: 0, marginLeft: 6 }}>
                  {briefing.watchlist.length} items
                </span>
              </span>
              {briefing.watchlist.length === 0 && (
                <p style={{ fontSize: 12.5, color: "var(--faint)" }}>No active events under watch.</p>
              )}
              {briefing.watchlist.map((w, i) => (
                <button
                  key={w.event_id}
                  className="wlrow"
                  onClick={() => { onSelectEvent(w.event_id); onClose(); }}
                >
                  <span className="wrank">{String(i + 1).padStart(2, "0")}</span>
                  <span style={{ minWidth: 0 }}>
                    <span className="wt" style={{ display: "block" }}>{w.title}</span>
                    <span className="wmeta">
                      <Badge prio={w.priority} />
                      <span className="m">{w.score.toFixed(1)}/10</span>
                      <span className="m">{fmtWIB(w.occurred_at)}</span>
                      {w.cluster && (
                        <span className="chip" title={`${w.cluster.member_count} events in this sequence`}>
                          ≋ {w.cluster.cluster_id} ×{w.cluster.member_count}
                        </span>
                      )}
                      {w.exposure_class && (
                        <span className="chip" title="System-derived exposure class (heuristic)">
                          EXP {w.exposure_class}
                        </span>
                      )}
                      {w.history_class && w.history_class !== "NORMAL" && (
                        <span className="chip" title="Behavior vs regional BMKG history (not a forecast)">
                          HIST {w.history_class}
                        </span>
                      )}
                      {w.situations && w.situations.length > 0 && (
                        <span className="chip" title={`Part of ${w.situations.length} connected situation(s)`}>
                          SIT ×{w.situations.length}
                        </span>
                      )}
                    </span>
                    <span className="wwhy" style={{ display: "block" }}>{w.why}</span>
                  </span>
                </button>
              ))}
            </section>

            {briefing.situations && briefing.situations.length > 0 && (
              <section className="brief-sec">
                <span className="bs-title"><span className="bs-num">04</span>Connected situations</span>
                <div style={{ fontSize: 11, color: "var(--faint)", marginTop: 4 }}>
                  Co-occurrence in space and time — not established causality.
                </div>
                {briefing.situations.map((s) => (
                  <div key={s.situation_id} className="actrow" style={{ marginTop: 6 }}>
                    <span className={`urg ${s.severity === "CRITICAL" ? "u-immediate" : s.severity === "HIGH" ? "u-soon" : "u-routine"}`}>
                      {s.severity}
                    </span>{" "}
                    <span className="chip" title="Situation detection rule">{s.kind}</span>
                    <div className="at">{s.title}</div>
                    <div className="ar">{s.interpretation}</div>
                    <div style={{ marginTop: 4, fontSize: 11, color: "var(--faint)" }}>
                      {s.member_ids.length} linked event(s) · {s.confidence} confidence
                    </div>
                    {s.member_ids.length > 0 && (
                      <div className="alinks">
                        {s.member_ids.slice(0, 3).map((id) => (
                          <button key={id} className="btn btn-ghost" style={{ padding: "2px 6px" }} onClick={() => { onSelectEvent(id); onClose(); }}>
                            Open event →
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </section>
            )}

            <section className="brief-sec">
              <span className="bs-title"><span className="bs-num">05</span>Recommended actions</span>
              {URG_ORDER.map((u) => {
                const items = briefing.recommended_actions.filter((a) => a.urgency === u);
                if (items.length === 0) return null;
                return (
                  <div key={u} style={{ marginTop: 8 }}>
                    <span className={`urg u-${u}`}>{URG_LABEL[u].toUpperCase()}</span>
                    {items.map((a, i) => (
                      <div key={i} className="actrow" style={{ marginTop: 6 }}>
                        <div className="at">{a.action}</div>
                        <div className="ar">{a.reason}</div>
                        {a.event_ids.length > 0 && (
                          <div className="alinks">
                            {a.event_ids.map((id) => (
                              <button key={id} className="btn btn-ghost" style={{ padding: "2px 6px" }} onClick={() => { onSelectEvent(id); onClose(); }}>
                                Open event →
                              </button>
                            ))}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                );
              })}
            </section>

            <section className="brief-sec">
              <span className="bs-title"><span className="bs-num">06</span>Analyst note</span>
              <div className="ai-note" style={{ marginTop: 8 }}>
                <div className="ai-label">
                  {aiActive ? "⚡ AI interpretive — verify against BMKG records" : "∅ AI note withheld"}
                </div>
                {briefing.llm_summary ? (
                  <>
                    <div className="ai-text">{briefing.llm_summary}</div>
                    <div className="ai-foot">MODEL {briefing.llm_model} · NOT A BMKG STATEMENT</div>
                  </>
                ) : (
                  <div className="ai-text" style={{ color: "var(--faint)" }}>
                    {LLM_STATUS_LABEL[briefing.llm_status ?? ""] ?? "AI note unavailable."}{" "}
                    The assessment above is unaffected.
                  </div>
                )}
              </div>
            </section>

            <section className="brief-sec">
              <span className="bs-title"><span className="bs-num">07</span>Confidence &amp; caveats</span>
              <ul style={{ margin: "8px 0 0", paddingLeft: 18, fontSize: 12, color: "var(--dim)" }}>
                {briefing.caveats.map((c, i) => (
                  <li key={i} style={{ marginBottom: 5, lineHeight: 1.5 }}>{c}</li>
                ))}
              </ul>
            </section>
          </div>
        )}
      </aside>
    </>
  );
}
