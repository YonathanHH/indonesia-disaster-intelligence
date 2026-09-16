"""Deterministic event correlation (dedup + matching).

Quake matching order:
  1. exact dedup via Observation.external_id unique key (same feed row twice -> skip)
  2. exact DateTime match against open earthquake events (same BMKG event across feeds)
  3. fuzzy: |dt|<=20min AND dist<=150km AND |dMag|<=0.7 -> same event
     (tolerates rounding/revision across autogempa vs gempaterkini vs felt)
CAP weather: same province token + overlapping validity window -> same event;
else new event.

Probabilistic/LLM matching deliberately NOT used — deterministic windows are
auditable and avoid inventing links. Thresholds are constants for testability.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from app.models import Event
from app.services.geo import haversine_km

QUAKE_TIME_MIN = 20
QUAKE_DIST_KM = 150
QUAKE_DM = 0.7


def _ensure_aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def match_quake(session, observed_at: datetime, lat: float, lon: float, mag: float) -> Event | None:
    observed_at = _ensure_aware(observed_at)
    rows = (await session.execute(
        select(Event).where(Event.type == "earthquake", Event.status == "active").order_by(Event.occurred_at.desc()).limit(200)
    )).scalars().all()
    # 1. exact datetime hit (same BMKG event across feeds)
    for e in rows:
        if _ensure_aware(e.occurred_at) == observed_at:
            return e
    # 2. fuzzy
    best, best_d = None, 1e9
    for e in rows:
        if e.latitude is None or e.magnitude is None:
            continue
        dt_min = abs((_ensure_aware(e.occurred_at) - observed_at).total_seconds()) / 60
        if dt_min > QUAKE_TIME_MIN:
            continue
        d = haversine_km(lat, lon, e.latitude, e.longitude)
        if d > QUAKE_DIST_KM:
            continue
        if abs((e.magnitude or 0) - mag) > QUAKE_DM:
            continue
        if d < best_d:
            best, best_d = e, d
    return best


def _province_token(text: str) -> str:
    low = (text or "").lower()
    for prov in ("jambi", "riau", "kalimantan utara", "jawa", "sumatera", "sulawesi",
                 "papua", "nusa tenggara", "maluku", "kalimantan", "bali", "aceh"):
        if prov in low:
            return prov
    words = [w for w in low.replace("-", " ").split() if len(w) > 4][:4]
    return " ".join(words)


async def match_weather(session, title: str, effective, expires) -> Event | None:
    tok = _province_token(title or "")
    if not tok:
        return None
    rows = (await session.execute(
        select(Event).where(Event.type == "severe_weather", Event.status == "active").order_by(Event.occurred_at.desc()).limit(100)
    )).scalars().all()
    for e in rows:
        if tok and tok not in (e.title or "").lower():
            continue
        e_exp = _ensure_aware(e.expires_at) if e.expires_at else None
        try:
            eff = _ensure_aware(effective)
            exp = _ensure_aware(expires)
        except Exception:
            continue
        if e_exp and eff and e_exp >= eff:
            return e
        if exp and _ensure_aware(e.occurred_at) <= exp:
            # overlapping window fallback
            return e
    return None
