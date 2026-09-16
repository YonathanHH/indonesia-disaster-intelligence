"""BMKG earthquake collectors.

Verified live endpoints (no auth, JSON):
  - https://data.bmkg.go.id/DataMKG/TEWS/autogempa.json      latest (single object)
  - https://data.bmkg.go.id/DataMKG/TEWS/gempaterkini.json   last 15 M5+ (list)
  - https://data.bmkg.go.id/DataMKG/TEWS/gempadirasakan.json last 15 felt (list)

Record shape (all strings):
  Tanggal, Jam, DateTime (ISO UTC), Coordinates "lat,lon", Lintang, Bujur,
  Magnitude, Kedalaman "10 km", Wilayah, Potensi ("Tidak berpotensi tsunami" |
  "Berpotensi TSUNAMI ..." | "Gempa ini dirasakan..."), Dirasakan ("III Sumbawa..."),
  Shakemap ("20260912200559.mmi.jpg").
"""
import logging
import re
from datetime import datetime, timezone

import httpx
from dateutil import parser as dateparser

from app.core.config import settings

log = logging.getLogger(__name__)

BASE = "https://data.bmkg.go.id/DataMKG/TEWS"
FEEDS = {
    "bmkg_latest": f"{BASE}/autogempa.json",
    "bmkg_m5": f"{BASE}/gempaterkini.json",
    "bmkg_felt": f"{BASE}/gempadirasakan.json",
}
SHAKEMAP_BASE = "https://static.bmkg.go.id"


def _f(x, default=None):
    try:
        return float(str(x).strip())
    except (ValueError, AttributeError, TypeError):
        return default


def parse_depth(s: str | None) -> float | None:
    if not s:
        return None
    m = re.search(r"([\d.]+)", str(s))
    return float(m.group(1)) if m else None


def parse_coords(s: str | None) -> tuple[float | None, float | None]:
    if not s:
        return None, None
    try:
        lat_s, lon_s = str(s).split(",")
        return float(lat_s.strip()), float(lon_s.strip())
    except ValueError:
        return None, None


def parse_datetime(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        dt = dateparser.isoparse(str(s).strip())
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def normalize_quake_record(raw: dict, kind: str) -> dict | None:
    """Return normalized observation dict, or None if unparseable (logged, skipped)."""
    dt = parse_datetime(raw.get("DateTime"))
    lat, lon = parse_coords(raw.get("Coordinates"))
    mag = _f(raw.get("Magnitude"))
    if dt is None or lat is None or lon is None or mag is None:
        log.warning("Skipping malformed quake record kind=%s raw=%s", kind, raw)
        return None
    depth = parse_depth(raw.get("Kedalaman"))
    potensi = (raw.get("Potensi") or "").strip()
    tsunami_flag = "tsunami" in potensi.lower() and "tidak" not in potensi.lower()
    shakemap = (raw.get("Shakemap") or "").strip() or None
    wilayah = (raw.get("Wilayah") or "").strip()
    external_id = f"bmkg-quake:{dt.isoformat()}:{lat:.3f}:{lon:.3f}:M{mag:.1f}"
    return {
        "kind": kind,
        "source": "bmkg",
        "external_id": external_id,
        "author": "BMKG",
        "text": f"M{mag:.1f} — {wilayah} ({depth} km)".replace("None km", "kedalaman tak diketahui"),
        "url": f"https://www.bmkg.go.id/gempabumi/gempabumi-terkini",
        "observed_at": dt,
        "structured": {
            "magnitude": mag,
            "depth_km": depth,
            "latitude": lat,
            "longitude": lon,
            "region": wilayah,
            "tsunami_potential": tsunami_flag,
            "potensi_text": potensi,
            "felt": (raw.get("Dirasakan") or "").strip() or None,
            "shakemap_url": f"{SHAKEMAP_BASE}/{shakemap}" if shakemap else None,
            "datetime": dt.isoformat(),
        },
        "raw": raw,
    }


async def _fetch_json(client: httpx.AsyncClient, url: str) -> dict | None:
    for attempt in range(3):
        try:
            r = await client.get(url)
            r.raise_for_status()
            return r.json()
        except Exception as e:  # timeouts, malformed JSON, 5xx — retry then give up
            log.warning("fetch %s attempt %d failed: %s", url, attempt + 1, e)
            if attempt == 2:
                return None
    return None


async def fetch_all_quakes(client: httpx.AsyncClient | None = None) -> list[dict]:
    """Fetch + normalize all three feeds. Never raises; partial failures return partial data."""
    own = client is None
    if own:
        client = httpx.AsyncClient(timeout=settings.bmkg_http_timeout, headers={"User-Agent": "bmkgintel/1.0"})
    assert client is not None
    out: list[dict] = []
    try:
        for kind, url in FEEDS.items():
            payload = await _fetch_json(client, url)
            if not payload:
                continue
            gempa = (payload.get("Infogempa") or {}).get("gempa")
            records = gempa if isinstance(gempa, list) else ([gempa] if gempa else [])
            for raw in records:
                norm = normalize_quake_record(raw, kind)
                if norm:
                    out.append(norm)
    finally:
        if own:
            await client.aclose()
    return out
