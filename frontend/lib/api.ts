const BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

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
  ingest: () =>
    fetch(`${BASE}/api/v1/ingest/run`, { method: "POST" }).then((r) => r.json()),
  resolve: (id: string) =>
    fetch(`${BASE}/api/v1/events/${id}/resolve`, { method: "POST" }).then((r) => r.json()),
};
