"""Pydantic response/request schemas."""
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

Priority = Literal["LOW", "MODERATE", "HIGH", "CRITICAL"]


class ObservationOut(BaseModel):
    id: str
    kind: str
    source: str
    external_id: str
    author: str | None
    text: str | None
    url: str | None
    observed_at: datetime
    structured: dict | None = None

    model_config = {"from_attributes": True}


class EventListOut(BaseModel):
    id: str
    type: str
    title: str
    occurred_at: datetime
    latitude: float
    longitude: float
    depth_km: float | None
    magnitude: float | None
    priority: str
    score: float
    status: str
    summary: str | None
    source_count: int
    expires_at: datetime | None = None

    model_config = {"from_attributes": True}


class EventDetailOut(EventListOut):
    score_breakdown: dict | None = None
    ai_assessment: str | None = None
    extra: dict | None = None
    observations: list[ObservationOut] = []
    history: list[dict[str, Any]] = []
    cluster: dict[str, Any] | None = None
    exposure: dict[str, Any] | None = None
    history_context: dict[str, Any] | None = None
    situations: list[dict[str, Any]] = []


class FeedItem(BaseModel):
    kind: str  # new_event | observation | resolved (legacy rows may carry social_signal)
    ts: datetime
    event_id: str | None
    title: str
    detail: str | None = None


class OverviewStats(BaseModel):
    active_events: int
    high_priority: int
    quakes_24h: int
    active_weather_alerts: int
    tsunami_alerts: int
    last_update: datetime | None
    collectors: dict[str, dict[str, Any]]


class WatchItem(BaseModel):
    event_id: str
    title: str
    type: str
    priority: str
    score: float
    occurred_at: datetime
    why: str
    cluster: dict[str, Any] | None = None
    exposure_class: str | None = None
    history_class: str | None = None
    situations: list[str] = []


class ActionItem(BaseModel):
    action: str
    reason: str
    urgency: str  # immediate | soon | routine
    event_ids: list[str] = []


class ChangeItem(BaseModel):
    event_id: str
    title: str
    type: str
    priority: str
    score: float
    occurred_at: datetime
    detail: str = ""


class ChangesOut(BaseModel):
    generated_at: datetime
    since: datetime
    new_events: list[ChangeItem]
    escalated: list[ChangeItem]
    de_escalated: list[ChangeItem]
    resolved: list[ChangeItem]
    expired: list[ChangeItem]
    growing_sequences: list[dict[str, Any]]
    counts: dict[str, int]


class ClusterOut(BaseModel):
    cluster_id: str
    method: str
    member_ids: list[str]
    member_count: int
    mainshock_id: str
    mainshock_magnitude: float | None = None
    mainshock_title: str
    started_at: datetime
    latest_at: datetime
    centroid: list[float]
    history: dict[str, Any] | None = None
    situation_ids: list[str] = []


class SituationOut(BaseModel):
    situation_id: str
    kind: str
    method: str
    title: str
    severity: str
    member_ids: list[str]
    observed: dict[str, Any]
    interpretation: str
    confidence: str
    caveats: list[str]


class EscalationTriggerOut(BaseModel):
    trigger_id: str
    rule: str
    method: str
    level: str
    title: str
    why: str
    event_ids: list[str] = []
    situation_ids: list[str] = []
    confidence: str


class EscalationOut(BaseModel):
    level: str
    method: str
    generated_at: datetime
    triggers: list[EscalationTriggerOut]
    posture: str


class BriefingOut(BaseModel):
    generated_at: datetime
    headline: str
    overview: list[str]
    watchlist: list[WatchItem]
    recommended_actions: list[ActionItem]
    developments: ChangesOut
    sequences: list[ClusterOut]
    situations: list[SituationOut]
    escalation: EscalationOut
    llm_summary: str | None = None
    llm_model: str | None = None
    llm_status: str | None = None
    caveats: list[str]


class AnalyticsOut(BaseModel):
    generated_at: datetime
    total_events: int
    by_type: dict[str, int]
    by_priority: dict[str, int]
    quakes_24h: int
    avg_magnitude_7d: float | None = None
    daily_counts_14d: list[dict[str, Any]]
    top_regions: list[dict[str, Any]]
    observations: int
