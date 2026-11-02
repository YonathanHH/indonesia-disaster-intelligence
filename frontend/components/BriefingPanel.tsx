"use client";
import { useEffect, useRef } from "react";
import type { Briefing, ChangeItem } from "../lib/types";
import { fmtWIB, prioColor, prioLabel } from "../lib/format";

const LLM_STATUS_LABEL: Record<string, string> = {
  off: "no key configured",
  misconfigured: "model not configured",
  empty: "empty response",
  rejected: "failed validation",
  error: "request failed",
};

const URG_ORDER = ["immediate", "soon", "routine"] as const;
const URG_LABEL: Record<string, string> = {
  immediate: "Immediate",
  soon: "Soon",
  routine: "Routine",
};

function ChangeGroup({
  label,
  items,
  tone,
  onSelect,
}: {
  label: string;
  items: ChangeItem[];
  tone: string;
  onSelect: (id: string) => void;
}) {
  if (!items || items.length === 0) return null;
  return (
    <div className="change">
      <span className="change-label" style={{ color: tone }}>
        {label}
        <span className="change-count">{items.length}</span>
      </span>
      {items.slice(0, 3).map((it) => (
        <button key={it.event_id} className="wlrow" onClick={() => onSelect(it.event_id)}>
          <span className="wrank">{prioLabel(it.priority).slice(0, 1)}</span>
          <span style={{ minWidth: 0 }}>
            <span className="wt" style={{ display: "block" }}>{it.title}</span>
            <span className="wmeta">
              <span>{it.detail || fmtWIB(it.occurred_at)}</span>
            </span>
          </span>
        </button>
      ))}
      {items.length > 3 && (
        <div className="note" style={{ padding: "4px 0 0 32px" }}>+{items.length - 3} more</div>
      )}
    </div>
  );
}

export default function BriefingPanel({
  briefing,
  loading,
  error,
  onClose,
  onSelectEvent,
}: {
  briefing: Briefing | null;
  loading: boolean;
  error?: string | null;
  onClose: () => void;
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

  return (
    <>
      <div className="drawer-backdrop" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-modal="true" aria-label="Executive briefing">
        <div className="drawer-head">
          <div>
            <div className="drawer-label">Situation brief</div>
            <div className="drawer-title">Executive briefing</div>
            <div className="drawer-time">
              {briefing
                ? `${briefing.kind === "daily" ? "Morning executive summary" : "Live brief"} · ${fmtWIB(briefing.generated_at)} WIB`
                : "—"}
            </div>
          </div>
          <div className="drawer-actions">
            <button className="btn btn-quiet" ref={closeRef} onClick={onClose} title="Close (Esc)">
              Close
            </button>
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
            <p className="prose" style={{ marginTop: 0 }}>Briefing unavailable: {error}</p>
            <button className="btn" onClick={onClose}>Close</button>
          </div>
        )}

        {briefing && (
          <div className="brief-body">
            <div className="brief-masthead">
              <h2 className="brief-headline">{briefing.headline}</h2>
              <div className="brief-meta">
                <span>Issued {fmtWIB(briefing.generated_at)} WIB</span>
                <span>
                  {aiActive
                    ? `AI note · ${briefing.llm_model}`
                    : `Deterministic · AI note ${LLM_STATUS_LABEL[briefing.llm_status ?? ""] ?? "unavailable"}`}
                </span>
              </div>
            </div>

            {briefing.escalation && briefing.escalation.level !== "NORMAL" && (
              <div
                className={`escalation ${briefing.escalation.level === "ALERT" ? "alert" : ""}`}
                role="alert"
              >
                <div className="esc-level">{prioLabel(briefing.escalation.level)}</div>
                <div className="esc-posture">{briefing.escalation.posture}</div>
                {briefing.escalation.triggers.map((t) => (
                  <div key={t.trigger_id} className="trig">
                    <div className="trig-title">{t.title}</div>
                    <div className="trig-why">{t.why}</div>
                    <div className="trig-meta">
                      {t.rule.toLowerCase().replace(/_/g, " ")} · {t.confidence.toLowerCase()} confidence
                    </div>
                    {t.event_ids.length > 0 && (
                      <div className="alinks" style={{ marginTop: 6 }}>
                        <button
                          className="btn btn-quiet"
                          style={{ height: 26, fontSize: 12 }}
                          onClick={() => { onSelectEvent(t.event_ids[0]); onClose(); }}
                        >
                          Open top event
                        </button>
                        {t.event_ids.length > 1 && (
                          <span className="tag" style={{ alignSelf: "center" }}>
                            {t.event_ids.length - 1} more related
                          </span>
                        )}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}

            <section className="brief-sec">
              <div className="bs-title">
                <span>Situation assessment</span>
              </div>
              <ul className="brief-list">
                {briefing.overview.map((line, i) => (
                  <li key={i}>{line}</li>
                ))}
              </ul>
            </section>

            <section className="brief-sec">
              <div className="bs-title">
                <span>What changed</span>
                <span className="bs-note">last 24 hours</span>
              </div>
              {dev && (
                <>
                  <p className="prose" style={{ margin: "8px 0 0" }}>
                    {dev.counts.new} new · {dev.counts.escalated} escalated ·{" "}
                    {dev.counts.de_escalated} de-escalated · {dev.counts.resolved} resolved ·{" "}
                    {dev.counts.expired} past expiry
                    {dev.counts.growing_sequences > 0 &&
                      ` · ${dev.counts.growing_sequences} growing sequence${dev.counts.growing_sequences === 1 ? "" : "s"}`}
                  </p>
                  <ChangeGroup
                    label="Escalated"
                    items={dev.escalated}
                    tone="var(--crit)"
                    onSelect={(id) => { onSelectEvent(id); onClose(); }}
                  />
                  <ChangeGroup
                    label="New"
                    items={dev.new_events}
                    tone="var(--accent)"
                    onSelect={(id) => { onSelectEvent(id); onClose(); }}
                  />
                  <ChangeGroup
                    label="Expired"
                    items={dev.expired}
                    tone="var(--mod)"
                    onSelect={(id) => { onSelectEvent(id); onClose(); }}
                  />
                  <ChangeGroup
                    label="Resolved"
                    items={dev.resolved}
                    tone="var(--low)"
                    onSelect={(id) => { onSelectEvent(id); onClose(); }}
                  />
                  {dev.growing_sequences.length > 0 && (
                    <div className="change">
                      <span className="change-label" style={{ color: "var(--mod)" }}>
                        Growing sequences
                        <span className="change-count">{dev.growing_sequences.length}</span>
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
                            <span className="wrank">Seq</span>
                            <span style={{ minWidth: 0 }}>
                              <span className="wt" style={{ display: "block" }}>
                                {g.member_count} events · mainshock M{g.mainshock_magnitude}
                              </span>
                              <span className="wmeta">
                                <span>{g.mainshock_title}</span>
                                {hc && hc !== "NORMAL" && <span>History {hc}</span>}
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
              <div className="bs-title">
                <span>Priority watchlist</span>
                <span className="bs-note">{briefing.watchlist.length} items</span>
              </div>
              {briefing.watchlist.length === 0 && (
                <p className="note" style={{ marginTop: 8 }}>No active events under watch.</p>
              )}
              {briefing.watchlist.map((w, i) => (
                <button
                  key={w.event_id}
                  className="wlrow"
                  onClick={() => { onSelectEvent(w.event_id); onClose(); }}
                >
                  <span className="wrank">{i + 1}</span>
                  <span style={{ minWidth: 0 }}>
                    <span className="wt" style={{ display: "block" }}>{w.title}</span>
                    <span className="wmeta">
                      <span className="sevword" style={{ color: prioColor(w.priority) }}>
                        <span className="sevdot" style={{ background: prioColor(w.priority) }} />
                        {prioLabel(w.priority)}
                      </span>
                      <span className="mono">{w.score.toFixed(1)}/10</span>
                      <span>{fmtWIB(w.occurred_at)}</span>
                      {w.cluster && (
                        <span title={`${w.cluster.member_count} events in this sequence`}>
                          Sequence ×{w.cluster.member_count}
                        </span>
                      )}
                      {w.exposure_class && (
                        <span title="System-derived exposure class (heuristic)">
                          Exposure {w.exposure_class}
                        </span>
                      )}
                      {w.history_class && w.history_class !== "NORMAL" && (
                        <span title="Behaviour against regional BMKG history (not a forecast)">
                          History {w.history_class}
                        </span>
                      )}
                      {w.situations.length > 0 && (
                        <span title={`Part of ${w.situations.length} connected situations`}>
                          {w.situations.length} situation{w.situations.length === 1 ? "" : "s"}
                        </span>
                      )}
                    </span>
                    <span className="wwhy" style={{ display: "block" }}>{w.why}</span>
                  </span>
                </button>
              ))}
            </section>

            {briefing.situations.length > 0 && (
              <section className="brief-sec">
                <div className="bs-title">
                  <span>Connected situations</span>
                  <span className="bs-note">co-occurrence, not causality</span>
                </div>
                {briefing.situations.map((s) => {
                  const sc =
                    s.severity === "CRITICAL" ? "var(--crit)" : s.severity === "HIGH" ? "var(--high)" : "var(--muted)";
                  return (
                    <div key={s.situation_id} className="situation-card">
                      <div className="sc-head">
                        <span className="sevword" style={{ color: sc }}>
                          <span className="sevdot" style={{ background: sc }} />
                          {prioLabel(s.severity)}
                        </span>
                        <span className="tag">{s.kind.replace(/_/g, " ")}</span>
                      </div>
                      <div className="sc-title">{s.title}</div>
                      <div className="sc-text">{s.interpretation}</div>
                      <div className="sc-meta">
                        {s.member_ids.length} linked event{s.member_ids.length === 1 ? "" : "s"} · {s.confidence} confidence
                      </div>
                      {s.member_ids.length > 0 && (
                        <div className="alinks" style={{ marginTop: 7 }}>
                          {s.member_ids.slice(0, 3).map((id) => (
                            <button
                              key={id}
                              className="btn btn-quiet"
                              style={{ height: 26, fontSize: 12 }}
                              onClick={() => { onSelectEvent(id); onClose(); }}
                            >
                              Open event
                            </button>
                          ))}
                        </div>
                      )}
                    </div>
                  );
                })}
              </section>
            )}

            <section className="brief-sec">
              <div className="bs-title">
                <span>Recommended actions</span>
              </div>
              {URG_ORDER.map((u) => {
                const items = briefing.recommended_actions.filter((a) => a.urgency === u);
                if (items.length === 0) return null;
                return (
                  <div key={u} style={{ marginTop: 10 }}>
                    <span className={`urgency ${u}`}>{URG_LABEL[u]}</span>
                    {items.map((a, i) => (
                      <div key={i} className="actrow">
                        <div className="at">{a.action}</div>
                        <div className="ar">{a.reason}</div>
                        {a.event_ids.length > 0 && (
                          <div className="alinks">
                            {a.event_ids.map((id) => (
                              <button
                                key={id}
                                className="btn btn-quiet"
                                style={{ height: 26, fontSize: 12 }}
                                onClick={() => { onSelectEvent(id); onClose(); }}
                              >
                                Open event
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
              <div className="bs-title">
                <span>Analyst note</span>
              </div>
              <div className="ai-note">
                <div className="ai-label">
                  {aiActive ? `AI note · ${briefing.llm_model}` : "AI note withheld"}
                </div>
                {briefing.llm_summary ? (
                  <>
                    <div className="ai-text">{briefing.llm_summary}</div>
                    <div className="ai-foot">Interpretive, not a BMKG statement. Verify against source records.</div>
                  </>
                ) : (
                  <div className="ai-text" style={{ color: "var(--muted)" }}>
                    {LLM_STATUS_LABEL[briefing.llm_status ?? ""] ?? "AI note unavailable."} The deterministic
                    assessment above is unaffected.
                  </div>
                )}
              </div>
            </section>

            <section className="brief-sec">
              <div className="bs-title">
                <span>Confidence and caveats</span>
              </div>
              <ul className="brief-list" style={{ color: "var(--muted)", fontSize: 12 }}>
                {briefing.caveats.map((c, i) => (
                  <li key={i}>{c}</li>
                ))}
              </ul>
            </section>
          </div>
        )}
      </aside>
    </>
  );
}
