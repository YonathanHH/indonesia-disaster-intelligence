// Empty by default: requests go to the same origin and Next proxies /api/v1/*
// to FastAPI (see next.config.mjs). Set NEXT_PUBLIC_API_URL only to bypass it.
const BASE = process.env.NEXT_PUBLIC_API_URL ?? "";

async function get<T>(path: string): Promise<T> {
  const r = await fetch(`${BASE}${path}`, { cache: "no-store" });
  if (!r.ok) throw new Error(`API ${r.status} ${path}`);
  return r.json() as Promise<T>;
}

export const api = {
  overview: () => get<import("./types").Overview>("/api/v1/status"),
  events: (q = "") => get<import("./types").BMKGEvent[]>(`/api/v1/events?limit=200${q}`),
  detail: (id: string) => get<import("./types").EventDetail>(`/api/v1/events/${id}`),
  feed: () => get<import("./types").FeedItem[]>("/api/v1/feed?limit=60"),
  overlays: () => get<import("./types").OverlayLayer[]>("/api/v1/overlays"),
  overlayGeojson: (id: string) => get<{ type: string; features: unknown[] }>(`/api/v1/overlays/${id}`),
  briefing: () => get<import("./types").Briefing>("/api/v1/briefing"),
  escalation: () => get<import("./types").Escalation>("/api/v1/escalation"),
  changes: (hours: number) =>
    get<import("./types").Developments>(`/api/v1/changes?since_hours=${hours.toFixed(2)}`),
  clusters: () => get<import("./types").ClusterSequence[]>("/api/v1/clusters"),
  analytics: (refresh = false) =>
    get<import("./types").Analytics>(`/api/v1/analytics?refresh=${refresh ? "true" : "false"}`),
  ingest: () =>
    fetch(`${BASE}/api/v1/ingest/run`, { method: "POST" }).then((r) => r.json()),
  resolve: (id: string) =>
    fetch(`${BASE}/api/v1/events/${id}/resolve`, { method: "POST" }).then((r) => r.json()),
};
