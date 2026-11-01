/** Shared formatting + display constants (single source of truth). */

export const PRIO_COLOR: Record<string, string> = {
  LOW: "#4fae8d",
  MODERATE: "#d9a441",
  HIGH: "#e8824f",
  CRITICAL: "#e5566f",
};

export const TYPE_LABEL: Record<string, string> = {
  earthquake: "Earthquake",
  severe_weather: "Severe weather",
  tsunami_alert: "Tsunami",
  volcano: "Volcano",
};

export function prioColor(p: string): string {
  return PRIO_COLOR[p] ?? "#909298";
}

/** Sentence-case severity for labels ("CRITICAL" -> "Critical"). */
export function prioLabel(p: string): string {
  return p.charAt(0) + p.slice(1).toLowerCase();
}

/** Absolute time, Asia/Jakarta (WIB). */
export function fmtWIB(s: string | null | undefined): string {
  if (!s) return "—";
  try {
    return new Date(s).toLocaleString("en-GB", {
      timeZone: "Asia/Jakarta",
      day: "2-digit",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return s;
  }
}

/** Clock time only (lists/feeds). */
export function fmtClock(s: string | null | undefined): string {
  if (!s) return "—";
  try {
    return new Date(s).toLocaleTimeString("en-GB", {
      timeZone: "Asia/Jakarta",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return s;
  }
}

/** Relative time — "4m", "2h 05m", "3d". Falls back to clock time when >7d. */
export function fmtRel(s: string | null | undefined): string {
  if (!s) return "—";
  const then = new Date(s).getTime();
  if (Number.isNaN(then)) return s;
  const diff = Math.max(0, Date.now() - then);
  const m = Math.floor(diff / 60_000);
  if (m < 1) return "now";
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ${String(m % 60).padStart(2, "0")}m`;
  const d = Math.floor(h / 24);
  if (d <= 7) return `${d}d`;
  return fmtClock(s);
}

export function typeLabel(t: string): string {
  return TYPE_LABEL[t] ?? t.replace(/_/g, " ");
}
