"""Exposure & impact intelligence (conservative, uncertainty-explicit).

What this is: a heuristic overlay that answers "who/what might be exposed?"
for significant events using ONLY data already in the system (epicenter,
magnitude, depth, felt text, CAP areas/polygons) plus a small static
gazetteer of major Indonesian city coordinates.

What this is NOT: not a loss estimate, not a population-exposure model, not
ground truth. There is no gridded-population dataset in this repo, so this
module deliberately avoids population numbers entirely. Distances are exact
haversine math from BMKG coordinates; everything else is a labelled
qualitative class with LOW/MODERATE confidence and explicit caveats.

City coordinates below are stable public geographic facts (provincial
capitals / major cities). If a coordinate is ever in doubt, the module still
works — nearest-city is informational context, never a scoring input beyond
the capped, labelled `exposure_bonus` applied at ingest.

Output (`assess_exposure`): {
  class: LOCALIZED | REGIONAL | WIDESPREAD,
  method: "exposure-v1",
  confidence: LOW | MODERATE,
  felt_areas: int,
  nearest_cities: [{city, province, km}],
  coastal_threat: bool,
  assets: [heuristic flags],
  caveats: [...],
}
Stored namespaced at Event.extra["exposure"]; surfaced in detail, briefing
evidence, and the AI note — never silently merged into BMKG facts.
"""
from __future__ import annotations

import re

from app.services.geo import haversine_km

METHOD = "exposure-v1"
NEAR_CITY_KM = 150.0
MAX_CITIES = 5

# name, province, lat, lon — major cities / provincial capitals (public geography).
CITIES: tuple[tuple[str, str, float, float], ...] = (
    ("Jakarta", "DKI Jakarta", -6.21, 106.85),
    ("Bandung", "Jawa Barat", -6.92, 107.61),
    ("Semarang", "Jawa Tengah", -6.99, 110.42),
    ("Yogyakarta", "DI Yogyakarta", -7.80, 110.36),
    ("Surabaya", "Jawa Timur", -7.26, 112.75),
    ("Serang", "Banten", -6.12, 106.15),
    ("Denpasar", "Bali", -8.67, 115.22),
    ("Mataram", "Nusa Tenggara Barat", -8.58, 116.12),
    ("Kupang", "Nusa Tenggara Timur", -10.18, 123.61),
    ("Medan", "Sumatera Utara", 3.59, 98.67),
    ("Padang", "Sumatera Barat", -0.95, 100.35),
    ("Pekanbaru", "Riau", 0.51, 101.45),
    ("Jambi", "Jambi", -1.61, 103.61),
    ("Palembang", "Sumatera Selatan", -2.99, 104.76),
    ("Bengkulu", "Bengkulu", -3.80, 102.27),
    ("Bandar Lampung", "Lampung", -5.43, 105.27),
    ("Banda Aceh", "Aceh", 5.55, 95.32),
    ("Pontianak", "Kalimantan Barat", -0.03, 109.34),
    ("Palangkaraya", "Kalimantan Tengah", -2.21, 113.91),
    ("Banjarmasin", "Kalimantan Selatan", -3.32, 114.59),
    ("Samarinda", "Kalimantan Timur", -0.50, 117.15),
    ("Tanjung Selor", "Kalimantan Utara", 2.84, 117.37),
    ("Manado", "Sulawesi Utara", 1.47, 124.84),
    ("Palu", "Sulawesi Tengah", -0.90, 119.87),
    ("Makassar", "Sulawesi Selatan", -5.15, 119.41),
    ("Kendari", "Sulawesi Tenggara", -3.99, 122.52),
    ("Gorontalo", "Gorontalo", 0.54, 123.06),
    ("Mamuju", "Sulawesi Barat", -2.67, 118.89),
    ("Ambon", "Maluku", -3.70, 128.17),
    ("Ternate", "Maluku Utara", 0.79, 127.39),
    ("Jayapura", "Papua", -2.53, 140.72),
    ("Manokwari", "Papua Barat", -0.86, 134.08),
)


def _get(obj, key: str, default=None):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def count_felt_areas(felt_text: str | None) -> int:
    if not felt_text:
        return 0
    segs = [s.strip() for s in re.split(r"[;,]", felt_text) if s.strip()]
    return len(segs)


def nearest_cities(lat: float, lon: float, max_km: float = NEAR_CITY_KM,
                   limit: int = MAX_CITIES) -> list[dict]:
    out = []
    for name, prov, clat, clon in CITIES:
        km = haversine_km(lat, lon, clat, clon)
        if km <= max_km:
            out.append({"city": name, "province": prov, "km": round(km, 1)})
    out.sort(key=lambda d: d["km"])
    return out[:limit]


def assess_exposure(event) -> dict:
    """Conservative exposure assessment for a quake- or weather-type event."""
    etype = str(_get(event, "type", ""))
    lat, lon = _get(event, "latitude"), _get(event, "longitude")
    mag = _get(event, "magnitude")
    depth = _get(event, "depth_km")
    extra = _get(event, "extra", None) or {}
    if not isinstance(extra, dict):
        extra = {}
    felt = extra.get("felt")
    felt_n = count_felt_areas(felt if isinstance(felt, str) else None)
    tsunami = bool(extra.get("tsunami_flag") or extra.get("tsunami_potential"))
    if etype == "tsunami_alert":
        tsunami = True

    cities = nearest_cities(lat, lon) if lat is not None and lon is not None else []
    nearest_km = cities[0]["km"] if cities else None

    assets: list[str] = []
    caveats = [
        "Heuristic overlay, not a loss or casualty estimate.",
        "Distances are epicentral/map-centroid, not shaking footprints.",
        "No gridded-population data in this system; no population figures claimed.",
    ]
    if etype in ("earthquake", "tsunami_alert"):
        m = mag or 0
        if tsunami:
            assets.append("coastal-exposure: BMKG flags tsunami potential; treat coasts near the epicenter as exposed until the bulletin clears")
            caveats.append("Tsunami exposure is bulletin-driven, not wave-modelled here.")
        if m >= 7:
            cls = "WIDESPREAD"
        elif m >= 6 or felt_n >= 5 or (nearest_km is not None and nearest_km < 50 and m >= 5):
            cls = "REGIONAL"
        else:
            cls = "LOCALIZED"
        if depth is not None and depth >= 150:
            caveats.append(f"Deep focus ({depth} km) usually dampens shaking despite magnitude.")
        confidence = "MODERATE" if (felt or tsunami or nearest_km is not None) else "LOW"
    elif etype == "severe_weather":
        areas = extra.get("areas") or []
        n_areas = len(areas) if isinstance(areas, list) else int(extra.get("area_count", 0) or 0)
        if n_areas >= 30:
            cls = "WIDESPREAD"
        elif n_areas >= 10:
            cls = "REGIONAL"
        else:
            cls = "LOCALIZED"
        assets.append("reported-areas: impact limited to BMKG-listed kecamatan unless the alert renews/expands")
        caveats.append("Polygons are nowcast guidance with short validity; check expiry.")
        confidence = "MODERATE" if n_areas >= 10 else "LOW"
        felt_n = n_areas
    else:
        cls = "LOCALIZED"
        confidence = "LOW"

    return {
        "class": cls,
        "method": METHOD,
        "confidence": confidence,
        "felt_areas": felt_n,
        "nearest_cities": cities,
        "nearest_city_km": nearest_km,
        "coastal_threat": tsunami,
        "assets": assets,
        "caveats": caveats,
    }


def exposure_bonus(assessment: dict, event_type: str) -> tuple[float, str]:
    """Small capped scoring modifier with a human-readable reason.

    Returns (bonus, reason). Bonus is 0.0 or 0.5 — never more. Only fires on
    corroborated signals (felt areas, wide CAP coverage), never on proximity
    alone and never for tsunami bulletins (the +2.0 tsunami score component
    already covers those).
    """
    cls = assessment.get("class")
    if event_type in ("earthquake", "tsunami_alert"):
        if cls == "WIDESPREAD" or (cls == "REGIONAL" and assessment.get("felt_areas", 0) >= 3):
            return 0.5, f"felt in {assessment.get('felt_areas', 0)} areas"
    elif event_type == "severe_weather":
        if cls == "WIDESPREAD":
            return 0.5, "broad CAP coverage"
    return 0.0, ""
