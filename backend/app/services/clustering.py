"""Event clustering / sequence detection (deterministic, offline).

Purpose: recognise related earthquakes as a developing situation (e.g.
mainshock-aftershock sequence) instead of only isolated events.

Method (sequence-v1, single-link chaining over active quake-type events
sorted by time): link consecutive events when BOTH hold:
  - |dt| <= SEQ_GAP_HOURS (72h)
  - haversine distance <= SEQ_DIST_KM (120km)
Clusters with >=2 members are sequences. Mainshock = max magnitude
(earliest wins ties). Cluster id is derived from the mainshock event id
(`seq-<first8>`), so it is stable across recomputation without storage.

Read-time computation over active events — no migration, no background job.
Same helper serves ingest (companion count for a small, capped, fully
labelled score modifier), briefing (watchlist/actions), and /clusters.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.services.geo import haversine_km

SEQ_GAP_HOURS = 72.0
SEQ_DIST_KM = 120.0
SEQ_METHOD = "sequence-v1"
QUAKE_TYPES = ("earthquake", "tsunami_alert")


def _get(obj, key: str, default=None):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _aware(dt: datetime) -> datetime:
    # SQLite drops tzinfo; normalise so aware/naive never mix in arithmetic.
    return dt if dt is not None and dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _ts(e) -> datetime:
    return _aware(_get(e, "occurred_at"))


def find_sequences(events: list) -> list[dict]:
    """Group quake-type events into sequences. Returns cluster dicts."""
    quakes = sorted(
        [e for e in events if _get(e, "type") in QUAKE_TYPES and _ts(e) is not None],
        key=lambda e: _ts(e),
    )
    chains: list[list] = []
    for e in quakes:
        placed = False
        for chain in chains:
            last = chain[-1]
            gap_h = abs((_ts(e) - _ts(last)).total_seconds()) / 3600.0
            dist = haversine_km(
                _get(e, "latitude"), _get(e, "longitude"),
                _get(last, "latitude"), _get(last, "longitude"),
            )
            if gap_h <= SEQ_GAP_HOURS and dist <= SEQ_DIST_KM:
                chain.append(e)
                placed = True
                break
        if not placed:
            chains.append([e])
    out = []
    for chain in chains:
        if len(chain) < 2:
            continue
        mags = [(_get(m, "magnitude") or 0) for m in chain]
        main = chain[mags.index(max(mags))]
        main_id = str(_get(main, "id", ""))
        lats = [_get(m, "latitude") for m in chain]
        lons = [_get(m, "longitude") for m in chain]
        out.append({
            "cluster_id": f"seq-{main_id[:8]}",
            "method": SEQ_METHOD,
            "member_ids": [str(_get(m, "id")) for m in chain],
            "member_count": len(chain),
            "mainshock_id": main_id,
            "mainshock_magnitude": _get(main, "magnitude"),
            "mainshock_title": str(_get(main, "title", "")),
            "started_at": min(_ts(m) for m in chain),
            "latest_at": max(_ts(m) for m in chain),
            "centroid": [sum(lats) / len(lats), sum(lons) / len(lons)],
        })
    out.sort(key=lambda c: c["latest_at"], reverse=True)
    return out


def cluster_for_event(event_id: str, clusters: list[dict]) -> dict | None:
    for c in clusters:
        if event_id in c["member_ids"]:
            return c
    return None


def companion_count(lat: float, lon: float, at: datetime, events: list,
                    hours: float = SEQ_GAP_HOURS, dist_km: float = SEQ_DIST_KM,
                    exclude_id: str | None = None) -> int:
    """Count quake-type events near (lat, lon, at). Used for the ingest modifier."""
    n = 0
    for e in events:
        if _get(e, "type") not in QUAKE_TYPES:
            continue
        if exclude_id is not None and str(_get(e, "id")) == exclude_id:
            continue
        ets = _ts(e)
        if ets is None:
            continue
        gap_h = abs((_aware(at) - ets).total_seconds()) / 3600.0
        if gap_h > hours:
            continue
        if haversine_km(lat, lon, _get(e, "latitude"), _get(e, "longitude")) <= dist_km:
            n += 1
    return n
