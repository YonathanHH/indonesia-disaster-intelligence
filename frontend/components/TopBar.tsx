"use client";
import type { Overview } from "../lib/types";
import { fmtWIB } from "../lib/format";

export default function TopBar({
  overview,
  loading,
  err,
  onIngest,
  onBriefing,
}: {
  overview: Overview | null;
  loading: boolean;
  err: string | null;
  onIngest: () => void;
  onBriefing: () => void;
}) {
  const status = err ? "off" : loading ? "sync" : "live";
  return (
    <header className="topbar">
      <div className="brand">
        <span className="brand-name">BMKG INTELLIGENCE</span>
        <span className="brand-sub">INDONESIA ENVIRONMENTAL INTELLIGENCE</span>
      </div>

      <span
        className={`pill ${status === "live" ? "pill-live" : status === "off" ? "pill-off" : "pill-sync"}`}
        role="status"
        aria-label={`Data link ${status}`}
      >
        <span className="dot" />
        {status === "live" ? "LIVE" : status === "off" ? "OFFLINE" : "SYNC"}
      </span>

      <span className="spacer" />

      <span className="mono topbar-upd" style={{ fontSize: 10.5, color: "var(--faint)", whiteSpace: "nowrap" }}>
        UPD {overview?.last_update ? fmtWIB(overview.last_update) : "—"} WIB
      </span>
      <span className="topbar-src" style={{ fontSize: 10, color: "var(--faint)", whiteSpace: "nowrap" }}>
        DATA: BMKG · data.bmkg.go.id
      </span>

      <div className="topbar-actions">
        <button className="btn" onClick={onIngest} title="Run all BMKG collectors now">
          ↻ Ingest
        </button>
        <button className="btn" onClick={onBriefing} title="Open executive briefing">
          ▤ Briefing
        </button>
      </div>
    </header>
  );
}
