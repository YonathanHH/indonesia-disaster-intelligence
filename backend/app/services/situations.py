"""Cross-hazard situation intelligence (deterministic, co-occurrence only).

A Situation groups active developments that form a meaningful connected
picture: earthquake + tsunami potential, rain + landslide exposure, volcanic
activity overlapping tectonic/weather activity, or several hazard types
affecting one region. Detection is conservative on purpose:

  - Co-occurrence in space + time is OBSERVED and reported as such.
  - Causality is NEVER claimed ("rain may worsen landslide exposure" is
    stated as conditional concern, not cause and effect).
  - Every situation carries separated `observed` (facts) and
    `interpretation` (why grouped, confidence LOW/MODERATE) plus caveats.

Method (situation-v1). All rules are pure functions of active events
(+ volcano levels when supplied — volcano rules are skipped, never
improvised, when levels are unavailable):
  - TSUNAMI_THREAT: each active tsunami_alert + active quakes within
    200 km / 72 h as possibly-related source activity. Severity CRITICAL,
    confidence MODERATE (bulletin-backed).
  - VOLCANO_TECTONIC: active quake sequence whose centroid is within
    100 km of a SIAGA/AWAS volcano. Severity from volcano level.
  - RAIN_LANDSLIDE: severe_weather mentioning longsor/banjir/hujan lebat
    + shallow-or-any M>=4.5 quake within 150 km / 14 d. Severity HIGH.
  - WEATHER_VOLCANO: severe_weather centroid within 150 km of a SIAGA+
    volcano (ash/lahar-rain conditional concern). Severity HIGH/MODERATE.
  - MULTI_HAZARD_REGION: >=2 distinct hazard types chained within
    150 km / 7 d. Severity = max member priority.

Situation ids (`sit-<kind>-<hash8>`) are stable while membership holds;
they rotate as situations evolve — documented, not hidden.

Read-time computation, no storage. Situations influence attention through
briefing watchlist ranking and dedicated actions, NOT through numeric
score modifiers (scores keep their three capped, explainable bonuses).
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

from app.services.geo import haversine_km

METHOD = "situation-v1"
QUAKE_TYPES = ("earthquake", "tsunami_alert")
RAIN_KEYS = ("longsor", "banjir", "hujan lebat")
ELEVATED_VOLC = ("SIAGA", "AWAS")


def _get(obj, key: str, default=None):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _aware(dt: datetime) -> datetime:
    return dt if dt is not None and dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _sid(kind: str, member_ids: list[str]) -> str:
    h = hashlib.sha1(f"{kind}:{','.join(sorted(member_ids))}".encode()).hexdigest()
    return f"sit-{kind.lower()}-{h[:8]}"


def _base(kind: str, title: str, severity: str, member_ids: list[str],
          observed: dict, interpretation: str, confidence: str) -> dict:
    return {
        "situation_id": _sid(kind, member_ids),
        "kind": kind,
        "method": METHOD,
        "title": title,
        "severity": severity,
        "member_ids": sorted(member_ids),
        "observed": observed,
        "interpretation": interpretation,
        "confidence": confidence,
        "caveats": [
            "Grouping is co-occurrence in space and time, not established causality.",
            "Member events keep their own BMKG-sourced facts; this situation adds context only.",
        ],
    }


def _active(events: list, types: tuple | None = None) -> list:
    return [e for e in events
            if _get(e, "status", "active") == "active"
            and (types is None or _get(e, "type") in types)]


def _near(lat: float, lon: float, at: datetime, events: list,
          dist_km: float, hours: float) -> list:
    if lat is None or lon is None or at is None:
        return []
    out = []
    for e in events:
        elat, elon, ets = _get(e, "latitude"), _get(e, "longitude"), _get(e, "occurred_at")
        if elat is None or elon is None or ets is None:
            continue
        if abs((_aware(at) - _aware(ets)).total_seconds()) / 3600.0 > hours:
            continue
        if haversine_km(lat, lon, elat, elon) <= dist_km:
            out.append(e)
    return out


def _max_severity(events: list) -> str:
    rank = {"LOW": 0, "MODERATE": 1, "HIGH": 2, "CRITICAL": 3}
    best, sev = -1, "MODERATE"
    for e in events:
        r = rank.get(str(_get(e, "priority", "MODERATE")), 1)
        if r > best:
            best, sev = r, str(_get(e, "priority", "MODERATE"))
    return sev


def detect_tsunami_threats(events: list, now: datetime) -> list[dict]:
    out = []
    quakes = _active(events, QUAKE_TYPES)
    for t in [e for e in quakes if _get(e, "type") == "tsunami_alert"]:
        related = [e for e in _near(_get(t, "latitude"), _get(t, "longitude"),
                                    _get(t, "occurred_at"), quakes, 200.0, 72.0)
                   if str(_get(e, "id")) != str(_get(t, "id"))]
        members = [t] + related
        extra = _get(t, "extra", None) or {}
        region = extra.get("region") if isinstance(extra, dict) else None
        out.append(_base(
            "TSUNAMI_THREAT",
            f"Tsunami threat — {region or _get(t, 'title', 'Indonesia')}",
            "CRITICAL", [str(_get(e, "id")) for e in members],
            {"tsunami_event_id": str(_get(t, "id")),
             "bulletin": ((extra.get("potensi_text") or "")[:200] or None
                          if isinstance(extra, dict) else None),
             "related_quakes": len(related)},
            ("BMKG tsunami bulletin active; nearby quake activity is reported as "
             "possibly-related source context, not as a confirmed trigger."),
            "MODERATE"))
    return out


def detect_rain_landslide(events: list, now: datetime) -> list[dict]:
    out = []
    quakes = _active(events, QUAKE_TYPES)
    for w in _active(events, ("severe_weather",)):
        text = f"{_get(w, 'title', '')} {(w.get('summary') if isinstance(w, dict) else getattr(w, 'summary', '')) or ''}".lower()
        keys = [k for k in RAIN_KEYS if k in text]
        if not keys:
            continue
        nearby = [e for e in _near(_get(w, "latitude"), _get(w, "longitude"),
                                   _get(w, "occurred_at"), quakes, 150.0, 14 * 24.0)
                  if (_get(e, "magnitude") or 0) >= 4.5]
        if not nearby:
            continue
        members = [w] + nearby
        out.append(_base(
            "RAIN_LANDSLIDE",
            f"Rain + landslide exposure — {_get(w, 'title', 'severe weather')[:80]}",
            _max_severity(members), [str(_get(e, "id")) for e in members],
            {"weather_event_id": str(_get(w, "id")), "keywords": keys,
             "quakes_14d": len(nearby)},
            ("Heavy-rain alert overlaps recent M4.5+ shaking; saturated slopes near "
             "the epicentral area merit landslide watch. Conditional concern — "
             "no landslide has been observed by this system."),
            "LOW"))
    return out


def _elevated_volcanoes(volcanoes: list | None) -> list[dict]:
    return [v for v in (volcanoes or [])
            if (v.get("level") if isinstance(v, dict) else _get(v, "level")) in ELEVATED_VOLC]


def detect_volcano_tectonic(sequences: list, volcanoes: list | None,
                            events_by_id: dict) -> list[dict]:
    out = []
    for v in _elevated_volcanoes(volcanoes):
        vlat = v.get("latitude") if isinstance(v, dict) else _get(v, "latitude")
        vlon = v.get("longitude") if isinstance(v, dict) else _get(v, "longitude")
        lvl = v.get("level") if isinstance(v, dict) else _get(v, "level")
        if vlat is None or vlon is None:
            continue
        for c in sequences:
            clat, clon = (c.get("centroid") or (None, None))
            if clat is None:
                continue
            if haversine_km(clat, clon, vlat, vlon) > 100.0:
                continue
            members = [events_by_id[mid] for mid in c["member_ids"] if mid in events_by_id]
            if not members:
                continue
            sev = "CRITICAL" if lvl == "AWAS" else "HIGH"
            out.append(_base(
                "VOLCANO_TECTONIC",
                f"Seismic sequence near {v.get('name', 'volcano')} ({lvl})",
                sev, [str(_get(e, "id")) for e in members],
                {"volcano": v.get("name"), "volcano_level": lvl,
                 "cluster_id": c["cluster_id"], "member_count": c["member_count"],
                 "distance_km": round(haversine_km(clat, clon, vlat, vlon), 1)},
                ("Earthquake sequence centroid lies within 100 km of an elevated "
                 "volcano. Reported as co-location for awareness; volcanic and "
                 "tectonic processes are not linked by this system."),
                "LOW"))
    return out


def detect_weather_volcano(events: list, volcanoes: list | None) -> list[dict]:
    out = []
    for v in _elevated_volcanoes(volcanoes):
        vlat = v.get("latitude") if isinstance(v, dict) else _get(v, "latitude")
        vlon = v.get("longitude") if isinstance(v, dict) else _get(v, "longitude")
        lvl = v.get("level") if isinstance(v, dict) else _get(v, "level")
        if vlat is None or vlon is None:
            continue
        for w in _active(events, ("severe_weather",)):
            wlat, wlon = _get(w, "latitude"), _get(w, "longitude")
            if wlat is None or wlon is None:
                continue
            dist = haversine_km(wlat, wlon, vlat, vlon)
            if dist > 150.0:
                continue
            out.append(_base(
                "WEATHER_VOLCANO",
                f"Severe weather near {v.get('name', 'volcano')} ({lvl})",
                "HIGH" if lvl == "AWAS" else "MODERATE",
                [str(_get(w, "id"))],
                {"volcano": v.get("name"), "volcano_level": lvl,
                 "distance_km": round(dist, 1)},
                ("Severe-weather alert overlaps an elevated volcano's vicinity; "
                 "lahar/ash-rain compounding is a conditional concern only."),
                "LOW"))
    return out


def detect_multi_hazard_regions(events: list, now: datetime) -> list[dict]:
    actives = [e for e in _active(events) if _get(e, "occurred_at") is not None
               and _get(e, "latitude") is not None]
    chains: list[list] = []
    for e in sorted(actives, key=lambda x: _aware(_get(x, "occurred_at"))):
        placed = False
        for chain in chains:
            last = chain[-1]
            gap_h = abs((_aware(_get(e, "occurred_at")) - _aware(_get(last, "occurred_at"))
                         ).total_seconds()) / 3600.0
            if gap_h <= 7 * 24.0 and haversine_km(
                    _get(e, "latitude"), _get(e, "longitude"),
                    _get(last, "latitude"), _get(last, "longitude")) <= 150.0:
                chain.append(e)
                placed = True
                break
        if not placed:
            chains.append([e])
    out = []
    for chain in chains:
        kinds = {("quake" if _get(e, "type") in QUAKE_TYPES else _get(e, "type")) for e in chain}
        if len(chain) >= 2 and len(kinds) >= 2:
            lats = [_get(e, "latitude") for e in chain]
            lons = [_get(e, "longitude") for e in chain]
            out.append(_base(
                "MULTI_HAZARD_REGION",
                f"Multi-hazard region — {', '.join(sorted(kinds))} ({len(chain)} events)",
                _max_severity(chain), [str(_get(e, "id")) for e in chain],
                {"hazard_kinds": sorted(kinds), "member_count": len(chain),
                 "centroid": [round(sum(lats) / len(lats), 3), round(sum(lons) / len(lons), 3)]},
                ("Different hazard types are simultaneously active in one region; "
                 "response attention is shared, not necessarily causally linked."),
                "LOW"))
    return out


def _dedupe(situations: list[dict]) -> list[dict]:
    seen, out = set(), []
    for s in situations:
        key = (s["kind"], tuple(s["member_ids"]))
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


def detect_situations(events: list, sequences: list | None = None,
                      volcanoes: list | None = None,
                      now: datetime | None = None) -> list[dict]:
    """Run all rules. Volcano rules silently skip when levels unavailable."""
    now = _aware(now) if now is not None else datetime.now(timezone.utc)
    events_by_id = {str(_get(e, "id")): e for e in events}
    found: list[dict] = []
    found += detect_tsunami_threats(events, now)
    found += detect_rain_landslide(events, now)
    found += detect_multi_hazard_regions(events, now)
    if volcanoes is not None:
        found += detect_volcano_tectonic(sequences or [], volcanoes, events_by_id)
        found += detect_weather_volcano(events, volcanoes)
    found = _dedupe(found)
    rank = {"CRITICAL": 0, "HIGH": 1, "MODERATE": 2, "LOW": 3}
    found.sort(key=lambda s: (rank.get(s["severity"], 2), s["title"]))
    return found


def situations_for_event(event_id: str, situations: list[dict]) -> list[dict]:
    return [s for s in situations if event_id in s["member_ids"]]


def member_severity(event_id: str, situations: list[dict]) -> str | None:
    """Highest situation severity covering the event (for attention ranking)."""
    rank = {"LOW": 0, "MODERATE": 1, "HIGH": 2, "CRITICAL": 3}
    best, out = -1, None
    for s in situations_for_event(event_id, situations):
        r = rank.get(s["severity"], 0)
        if r > best:
            best, out = r, s["severity"]
    return out
