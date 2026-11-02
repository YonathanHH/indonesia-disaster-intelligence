"use client";
import type { Escalation, Overview } from "../lib/types";
import { fmtRel, fmtWIB } from "../lib/format";

const POSTURE_LABEL: Record<string, string> = {
  NORMAL: "Normal posture",
  WATCH: "Watch posture",
  ALERT: "Alert posture",
};

export default function TopBar({
  overview,
  escalation,
  loading,
  err,
  onBriefing,
  onPosture,
}: {
  overview: Overview | null;
  escalation: Escalation | null;
  loading: boolean;
  err: string | null;
  onBriefing: () => void;
  onPosture: () => void;
}) {
  const status = err ? "off" : loading ? "sync" : "live";
  const statusLabel = status === "off" ? "Offline" : status === "sync" ? "Syncing" : "Live";
  const posture = escalation ? escalation.level.toLowerCase() : "";
  const postureLabel = escalation ? POSTURE_LABEL[escalation.level] ?? escalation.level : "";
  const postureHint = escalation
    ? [escalation.posture, ...escalation.triggers.map((t) => t.title)].join(" · ")
    : "";
  return (
    <header className="topbar">
      <div className="brand">
        <span className="brand-mark" aria-hidden="true">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
            <path
              d="M2 13h3.4l1.9-6 3.2 12 3-9 1.8 3H22"
              stroke="currentColor"
              strokeWidth="1.6"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </span>
        <div style={{ minWidth: 0 }}>
          <h1>BMKG Intelligence</h1>
          <span className="scope">Indonesia · BMKG open data · WIB</span>
        </div>
      </div>

      <div className="topbar-state">
        {escalation && (
          <button
            className={`posture ${posture}`}
            onClick={onPosture}
            title={postureHint}
            aria-label={`System ${postureLabel}. Open the briefing`}
          >
            <span className="dot" aria-hidden="true" />
            {postureLabel}
            {escalation.triggers.length > 0 && (
              <span className="posture-count" title={`${escalation.triggers.length} active triggers`}>
                {escalation.triggers.length}
              </span>
            )}
          </button>
        )}
        <span
          className={`linkstate ${status === "off" ? "off" : status === "sync" ? "sync" : ""}`}
          role="status"
          aria-label={`Data link ${statusLabel}`}
        >
          <span className="dot" />
          {statusLabel}
        </span>
        <span title={overview?.last_update ? fmtWIB(overview.last_update) + " WIB" : undefined}>
          Updated {fmtRel(overview?.last_update)}
        </span>
      </div>

      <div className="topbar-actions">
        <button className="btn btn-primary" onClick={onBriefing} title="Open the executive briefing">
          Briefing
        </button>
      </div>
    </header>
  );
}
