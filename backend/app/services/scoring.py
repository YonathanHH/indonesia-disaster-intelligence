"""Deterministic baseline intelligence priority score (0-10) + LOW/MODERATE/HIGH/CRITICAL.

Explicitly NOT a validated risk estimate — labelled 'intelligence priority'.
Methodology is explainable: every score returns component contributions.

Earthquake signals: magnitude (base), depth modifier, felt/MMI modifier,
tsunami-potential flag.
Weather (CAP) signals: severity/urgency/certainty mapping, area count,
hazard keywords. Unknown fields degrade gracefully (no crash, lower score).
"""
from __future__ import annotations


def band(score: float) -> str:
    if score >= 8:
        return "CRITICAL"
    if score >= 6:
        return "HIGH"
    if score >= 4:
        return "MODERATE"
    return "LOW"


def score_earthquake(magnitude: float | None, depth_km: float | None,
                     felt_text: str | None, tsunami: bool) -> tuple[float, dict]:
    parts: dict[str, float] = {}
    m = magnitude or 0
    # base curve
    if m >= 7:
        base = 9.0
    elif m >= 6:
        base = 7.5
    elif m >= 5:
        base = 6.0
    elif m >= 4:
        base = 4.5
    elif m >= 3:
        base = 3.0
    elif m > 0:
        base = 1.5
    else:
        base = 1.0
    parts["magnitude_base"] = round(base, 2)
    score = base
    # depth: shallow amplifies, very deep dampens
    if depth_km is not None:
        if depth_km <= 30:
            parts["shallow"] = 1.0
            score += 1.0
        elif depth_km <= 70:
            parts["intermediate"] = 0.25
            score += 0.25
        elif depth_km >= 300:
            parts["very_deep"] = -1.5
            score -= 1.5
        elif depth_km >= 150:
            parts["deep"] = -0.75
            score -= 0.75
    # felt reports
    felt_n, mmi_bonus = 0, 0.0
    if felt_text:
        segs = [s.strip() for s in felt_text.replace(";", ",").split(",") if s.strip()]
        felt_n = len(segs)
        upper = felt_text.upper()
        if "V" in upper and "IV" in upper:
            mmi_bonus = 1.5
        elif "IV" in upper:
            mmi_bonus = 1.0
        elif "III" in upper:
            mmi_bonus = 0.5
        elif "II" in upper:
            mmi_bonus = 0.25
        if felt_n >= 10:
            mmi_bonus += 0.5
    parts["felt_bonus"] = round(min(mmi_bonus, 2.0), 2)
    score += min(mmi_bonus, 2.0)
    parts["felt_areas"] = felt_n
    if tsunami:
        parts["tsunami_potential"] = 2.0
        score += 2.0
    score = max(0.0, min(10.0, round(score, 2)))
    return score, {"components": parts, "method": "quake-v1", "priority": band(score)}


SEV_MAP = {"extreme": 4.0, "severe": 3.0, "moderate": 2.0, "minor": 1.0}
URG_MAP = {"immediate": 1.5, "expected": 1.0, "future": 0.25}
CERT_MAP = {"observed": 1.0, "likely": 0.75, "possible": 0.4, "unlikely": 0.0}
HAZARD_KEYS = {"petir": 0.5, "angin kencang": 0.75, "banjir": 0.75, "longsor": 0.75,
               "hujan lebat": 0.5, "gelombang": 0.5}


def score_weather(severity: str | None, urgency: str | None, certainty: str | None,
                  area_count: int, headline: str, description: str) -> tuple[float, dict]:
    parts: dict[str, float] = {}
    sev = (severity or "").lower()
    base = SEV_MAP.get(sev, 2.0)  # default moderate when CAP omits severity
    parts["severity_base"] = base
    score = base + 1.0  # lift so real alerts land in MODERATE+
    u = URG_MAP.get((urgency or "").lower(), 0.5)
    c = CERT_MAP.get((certainty or "").lower(), 0.5)
    parts["urgency"] = u
    parts["certainty"] = c
    score += u + c
    area_bonus = min(max(area_count, 0) / 20.0, 1.5)
    parts["area_bonus"] = round(area_bonus, 2)
    score += area_bonus
    text = f"{headline or ''} {description or ''}".lower()
    hz = sum(v for k, v in HAZARD_KEYS.items() if k in text)
    hz = min(hz, 1.5)
    parts["hazard_bonus"] = hz
    score += hz
    score = max(0.0, min(10.0, round(score, 2)))
    return score, {"components": parts, "method": "weather-v1", "priority": band(score)}
