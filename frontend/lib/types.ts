export type BMKGEvent = {
  id: string;
  type: string;
  title: string;
  occurred_at: string;
  latitude: number;
  longitude: number;
  depth_km: number | null;
  magnitude: number | null;
  priority: "LOW" | "MODERATE" | "HIGH" | "CRITICAL";
  score: number;
  status: string;
  summary: string | null;
  source_count: number;
  expires_at: string | null;
};

export type EventDetail = BMKGEvent & {
  score_breakdown: Record<string, unknown> | null;
  ai_assessment: string | null;
  extra: Record<string, unknown> | null;
  observations: {
    id: string;
    kind: string;
    source: string;
    external_id: string;
    author: string | null;
    text: string | null;
    url: string | null;
    observed_at: string;
    structured: Record<string, unknown> | null;
  }[];
  history: { ts: string; kind: string; message: string; payload: unknown }[];
  cluster: {
    cluster_id: string;
    member_count: number;
    mainshock_id: string;
    mainshock_magnitude: number | null;
    mainshock_title: string;
  } | null;
  exposure: {
    class: string;
    method: string;
    confidence: string;
    felt_areas: number;
    nearest_cities: { city: string; province: string; km: number }[];
    nearest_city_km: number | null;
    coastal_threat: boolean;
    assets: string[];
    caveats: string[];
  } | null;
  history_context: HistoryContext | null;
  situations: Situation[];
};

export type FeedItem = {
  kind: string;
  ts: string;
  event_id: string | null;
  title: string;
  detail: string | null;
};

export type Overview = {
  active_events: number;
  high_priority: number;
  quakes_24h: number;
  active_weather_alerts: number;
  tsunami_alerts: number;
  last_update: string | null;
  collectors: Record<string, { last_run_at: string | null; last_ok_at: string | null; last_error: string | null; items_fetched: number }>;
};

export type OverlayLayer = {
  id: string;
  title: string;
  kind: string;
  attribution: string;
  count: number | null;
  updated_at: string | null;
  available: boolean;
  reason?: string | null;
};

export type VolcanoFeature = {
  type: "Feature";
  properties: {
    name: string;
    level: string;
    level_code: number;
    color: string;
    province: string;
    url: string;
  };
  geometry: { type: "Point"; coordinates: [number, number] };
};

export type Situation = {
  situation_id: string;
  kind: string;
  method: string;
  title: string;
  severity: string;
  member_ids: string[];
  observed: Record<string, unknown>;
  interpretation: string;
  confidence: string;
  caveats: string[];
};

export type EscalationTrigger = {
  trigger_id: string;
  rule: string;
  method: string;
  level: string;
  title: string;
  why: string;
  event_ids: string[];
  situation_ids: string[];
  confidence: string;
};

export type Escalation = {
  level: string;
  method: string;
  generated_at: string;
  triggers: EscalationTrigger[];
  posture: string;
};

export type WatchItem = {
  event_id: string;
  title: string;
  type: string;
  priority: string;
  score: number;
  occurred_at: string;
  why: string;
  cluster: {
    cluster_id: string;
    member_count: number;
    mainshock_magnitude: number | null;
    mainshock_id: string;
  } | null;
  exposure_class: string | null;
  history_class: string | null;
  situations: string[];
};

export type ChangeItem = {
  event_id: string;
  title: string;
  type: string;
  priority: string;
  score: number;
  occurred_at: string;
  detail: string;
};

export type Developments = {
  generated_at: string;
  since: string;
  new_events: ChangeItem[];
  escalated: ChangeItem[];
  de_escalated: ChangeItem[];
  resolved: ChangeItem[];
  expired: ChangeItem[];
  growing_sequences: {
    cluster_id: string;
    member_count: number;
    mainshock_magnitude: number | null;
    mainshock_title: string;
    mainshock_id: string;
    latest_at: string;
  }[];
  counts: Record<string, number>;
};

export type Sequence = {
  cluster_id: string;
  member_count: number;
  mainshock_id: string;
  mainshock_magnitude: number | null;
  mainshock_title: string;
  started_at: string;
  latest_at: string;
  centroid: number[];
  history: HistoryContext | null;
  situation_ids: string[];
};

export type HistoryContext = {
  class: string;
  method: string;
  confidence: string;
  ratio: number;
  observed: {
    region_km: number;
    baseline_days: number;
    recent_days: number;
    baseline_count: number;
    recent_count: number;
    expected_7d: number;
    daily_rate: number;
    largest_in_days: number | null;
  };
  caveats: string[];
};

export type ActionItem = {
  action: string;
  reason: string;
  urgency: "immediate" | "soon" | "routine";
  event_ids: string[];
};

export type Briefing = {
  generated_at: string;
  headline: string;
  overview: string[];
  watchlist: WatchItem[];
  recommended_actions: ActionItem[];
  developments: Developments;
  sequences: Sequence[];
  situations: Situation[];
  escalation: Escalation;
  llm_summary: string | null;
  llm_model: string | null;
  llm_status: string | null;
  caveats: string[];
};
