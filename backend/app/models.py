"""Canonical domain model.

Event  = real-world hazard (canonical, deduplicated).
Observation = one source record supporting an event (BMKG feed row / CAP alert).
EventHistory = append-only audit trail for timelines / change detection.
"""
import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class Event(Base):
    __tablename__ = "events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    type: Mapped[str] = mapped_column(String(32), index=True)  # earthquake | severe_weather | tsunami_alert
    title: Mapped[str] = mapped_column(String(512))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    depth_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    magnitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    priority: Mapped[str] = mapped_column(String(16), index=True, default="LOW")  # LOW|MODERATE|HIGH|CRITICAL
    score: Mapped[float] = mapped_column(Float, default=0.0)
    score_breakdown: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_assessment: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    extra: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # type-specific attrs
    source_count: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    observations: Mapped[list["Observation"]] = relationship(back_populates="event", cascade="all, delete-orphan")
    history: Mapped[list["EventHistory"]] = relationship(back_populates="event", cascade="all, delete-orphan")


class Observation(Base):
    __tablename__ = "observations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    event_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("events.id"), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)  # bmkg_quake | bmkg_felt | bmkg_m5 | bmkg_cap
    source: Mapped[str] = mapped_column(String(64))  # bmkg
    external_id: Mapped[str] = mapped_column(String(256), unique=True, index=True)  # dedup key
    author: Mapped[str | None] = mapped_column(String(256), nullable=True)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    structured: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # normalized extraction
    raw: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    event: Mapped[Event | None] = relationship(back_populates="observations")


class EventHistory(Base):
    __tablename__ = "event_history"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    event_id: Mapped[str] = mapped_column(String(36), ForeignKey("events.id"), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, index=True)
    kind: Mapped[str] = mapped_column(String(32))  # created | observation | rescore | resolved | note
    message: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    event: Mapped[Event] = relationship(back_populates="history")


class IngestState(Base):
    """Last-run bookkeeping per collector (for /status + admin visibility)."""

    __tablename__ = "ingest_state"

    collector: Mapped[str] = mapped_column(String(64), primary_key=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_ok_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    items_fetched: Mapped[int] = mapped_column(Integer, default=0)
