"""Historical context — is current behavior normal for this region?

Compares current/sequence activity against the system's own accumulated
BMKG-derived record (no external catalog, no new tables). For a location
and magnitude, answers: how often does this region shake like this, and is
right now unusual?

Method (history-v1), all deterministic and offline:
  - Region: quake-type events within REGION_KM (200 km) of the point.
  - Baseline: regional events in [now-180d, now-7d] -> daily rate.
    The trailing 7 days are excluded so the current burst never inflates
    its own baseline.
  - Recent: regional events in the last 7 days (includes the event under
    review — "current behavior" includes right now).
  - Ratio = recent / max(expected, floor). Classes with absolute-count
    guards so tiny samples can't scream:
      SIGNIFICANT: ratio >= 8 and recent >= 4
      UNUSUAL:     ratio >= 4 and recent >= 3
      ELEVATED:    ratio >= 2 and recent >= 3, or largest regional event
                   in >= 180 days with M >= 6
      NORMAL:      otherwise
  - Baseline with < 5 events -> NORMAL, confidence LOW, explicit
    "insufficient history" caveat (cold-start safe for fresh DBs).

Observed facts (counts, dates, magnitudes from stored BMKG rows) and
interpretation (class, ratio) are kept in separate keys. Classes describe
position relative to local recorded history — never a forecast.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services.geo import haversine_km

METHOD = "history-v1"
REGION_KM = 200.0
BASELINE_DAYS = 180
RECENT_DAYS = 7
MIN_BASELINE = 5

CLASSES = ("NORMAL", "ELEVATED", "UNUSUAL", "SIGNIFICANT")
QUAKE_TYPES = ("earthquake", "tsunami_alert")


def _get(obj, key: str, default=None):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _aware(dt: datetime) -> datetime:
    return dt if dt is not None and dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def regional_quakes(lat: float, lon: float, events: list,
                    radius_km: float = REGION_KM) -> list:
    """Quake-type events with coordinates inside the radius, oldest first."""
    out = []
    for e in events:
        if _get(e, "type") not in QUAKE_TYPES:
            continue
        elat, elon = _get(e, "latitude"), _get(e, "longitude")
        ets = _get(e, "occurred_at")
        if elat is None or elon is None or ets is None:
            continue
        if haversine_km(lat, lon, elat, elon) <= radius_km:
            out.append(e)
    out.sort(key=lambda e: _aware(_get(e, "occurred_at")))
    return out


def assess_history(lat: float, lon: float, magnitude: float | None,
                   events: list, now: datetime | None = None) -> dict:
    """Classify current regional behavior vs its own recorded baseline."""
    now = _aware(now) if now is not None else datetime.now(timezone.utc)
    regional = regional_quakes(lat, lon, events)
    base_lo = now - timedelta(days=BASELINE_DAYS)
    recent_lo = now - timedelta(days=RECENT_DAYS)

    baseline = [e for e in regional if base_lo <= _aware(_get(e, "occurred_at")) < recent_lo]
    recent = [e for e in regional if _aware(_get(e, "occurred_at")) >= recent_lo]
    year = [e for e in regional if _aware(_get(e, "occurred_at")) >= now - timedelta(days=365)]

    n_base, n_recent = len(baseline), len(recent)
    base_days = BASELINE_DAYS - RECENT_DAYS
    daily_rate = n_base / base_days if base_days > 0 else 0.0
    expected = round(daily_rate * RECENT_DAYS, 2)
    ratio = round(n_recent / max(expected, 0.25), 2)

    # Largest-in-record check (observed fact, exact). Only strictly historical
    # events count — the event under review must not compare against itself.
    mag = magnitude or 0
    past = [e for e in year if _aware(_get(e, "occurred_at")) < recent_lo]
    bigger = [e for e in past
              if (_get(e, "magnitude") or 0) >= mag and mag > 0]
    if mag > 0 and not bigger:
        largest_days = 365
    elif bigger:
        latest_bigger = max(_aware(_get(e, "occurred_at")) for e in bigger)
        largest_days = (now - latest_bigger).days
    else:
        largest_days = None

    observed = {
        "region_km": REGION_KM,
        "baseline_days": BASELINE_DAYS,
        "recent_days": RECENT_DAYS,
        "baseline_count": n_base,
        "recent_count": n_recent,
        "expected_7d": expected,
        "daily_rate": round(daily_rate, 3),
        "largest_in_days": largest_days,
    }

    caveats = [
        "Baseline is this system's recorded BMKG history, not a complete seismic catalog.",
        "Classes describe position relative to local history, not a forecast.",
    ]
    if n_base < MIN_BASELINE:
        return {
            "class": "NORMAL",
            "method": METHOD,
            "confidence": "LOW",
            "ratio": ratio,
            "observed": observed,
            "caveats": caveats + [
                f"Only {n_base} baseline event(s) in region; insufficient history for anomaly detection.",
            ],
        }

    cls = "NORMAL"
    if ratio >= 8 and n_recent >= 4:
        cls = "SIGNIFICANT"
    elif ratio >= 4 and n_recent >= 3:
        cls = "UNUSUAL"
    elif ratio >= 2 and n_recent >= 3:
        cls = "ELEVATED"
    if cls in ("NORMAL", "ELEVATED") and mag >= 6 and (largest_days or 0) >= 180:
        cls = "ELEVATED"

    return {
        "class": cls,
        "method": METHOD,
        "confidence": "MODERATE" if n_base >= 20 else "LOW",
        "ratio": ratio,
        "observed": observed,
        "caveats": caveats,
    }


def sequence_history(cluster: dict, events: list,
                     now: datetime | None = None) -> dict:
    """Historical context for a sequence cluster (centroid + mainshock)."""
    clat, clon = cluster.get("centroid") or (None, None)
    if clat is None or clon is None:
        return {
            "class": "NORMAL", "method": METHOD, "confidence": "LOW",
            "ratio": 0.0, "observed": {}, "caveats": ["No centroid available."],
            "cluster_id": cluster.get("cluster_id"),
            "member_count": cluster.get("member_count"),
        }
    ctx = assess_history(clat, clon, cluster.get("mainshock_magnitude"), events, now)
    ctx["cluster_id"] = cluster.get("cluster_id")
    ctx["member_count"] = cluster.get("member_count")
    return ctx


def history_bonus(context: dict) -> tuple[float, str]:
    """Capped scoring modifier. Fires only on UNUSUAL/SIGNIFICANT."""
    cls = context.get("class")
    if cls in ("UNUSUAL", "SIGNIFICANT"):
        obs = context.get("observed", {})
        return 0.5, (f"{cls.lower()} regional activity "
                     f"({obs.get('recent_count', 0)} in 7d vs "
                     f"~{obs.get('expected_7d', 0)} expected)")
    return 0.0, ""
