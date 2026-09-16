"""Geological overlay registry (map context layers, not events).

Available layers:
  - volcanoes: PVMBG/MAGMA monitored volcanoes + live alert levels.
  - plates:    PB2002 plate boundaries clipped to Indonesia (Bird 2003).
  - faults:    OPT-IN only. No reliable open fault-trace dataset covers
    Indonesia (GEM GAF-DB explicitly excludes the Malay Archipelago; OSM has
    ~zero mapped fault ways in the region; the PuSGeN active-fault map is not
    machine-readable). Set FAULTS_GEOJSON_URL to serve a custom LineString /
    MultiLineString GeoJSON (e.g. licensed PuSGeN digitisation). We deliberately
    do not hand-draw faults — invented fault traces would violate the same
    provenance rule as invented events.
"""
import logging
import time

import httpx

from app.collectors import magma, plates
from app.core.config import settings

log = logging.getLogger(__name__)

LON_MIN, LON_MAX = 90.0, 145.0
LAT_MIN, LAT_MAX = -12.0, 8.0

_faults_cache: dict = {"fc": None, "at": 0.0}
FAULTS_TTL = 7 * 86400


class OverlayUnavailable(Exception):
    pass


def _in_window(lon: float, lat: float) -> bool:
    return LON_MIN <= lon <= LON_MAX and LAT_MIN <= lat <= LAT_MAX


def clip_lines(fc: dict) -> dict:
    """Keep LineString/MultiLineString features touching the Indonesia window."""
    out = []
    for f in fc.get("features", []):
        geom = f.get("geometry") or {}
        lines = []
        if geom.get("type") == "LineString":
            lines = [geom.get("coordinates", [])]
        elif geom.get("type") == "MultiLineString":
            lines = geom.get("coordinates", [])
        else:
            continue
        kept = [[c for c in line if _in_window(c[0], c[1])] for line in lines]
        kept = [line for line in kept if len(line) >= 2]
        if not kept:
            continue
        props = f.get("properties") or {}
        out.append({
            "type": "Feature",
            "properties": {"name": props.get("name") or props.get("Name") or props.get("NAME") or ""},
            "geometry": {"type": "LineString" if len(kept) == 1 else "MultiLineString",
                         "coordinates": kept[0] if len(kept) == 1 else kept},
        })
    return {"type": "FeatureCollection", "features": out}


async def layer_index() -> list[dict]:
    volcanoes = await magma.get_volcanoes()
    plate_data = await plates.get_plates()
    layers = [
        {"id": "volcanoes", "title": "Volcanoes (PVMBG alert levels)", "kind": "points",
         "attribution": volcanoes["attribution"], "count": len(volcanoes["volcanoes"]),
         "updated_at": volcanoes["levels_updated_at"], "available": bool(volcanoes["volcanoes"])},
        {"id": "plates", "title": "Plate boundaries (PB2002)", "kind": "lines",
         "attribution": plate_data.get("attribution", ""), "count": len(plate_data.get("features", [])),
         "updated_at": plate_data.get("updated_at"), "available": bool(plate_data.get("features"))},
    ]
    if settings.faults_geojson_url:
        layers.append({"id": "faults", "title": "Active faults (custom source)", "kind": "lines",
                       "attribution": "Custom fault source (see FAULTS_GEOJSON_URL)",
                       "count": None, "updated_at": None, "available": True})
    else:
        layers.append({"id": "faults", "title": "Active faults", "kind": "lines",
                       "attribution": "", "count": 0, "updated_at": None, "available": False,
                       "reason": "No open fault-trace dataset covers Indonesia; set FAULTS_GEOJSON_URL to enable."})
    return layers


async def volcanoes_geojson() -> dict:
    data = await magma.get_volcanoes()
    return {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {"name": v["name"], "level": v["level"], "level_code": v["level_code"],
                           "color": v["level_color"], "province": v["province"], "url": v["url"]},
            "geometry": {"type": "Point", "coordinates": [v["longitude"], v["latitude"]]},
        } for v in data["volcanoes"]],
        "attribution": data["attribution"],
        "updated_at": data["levels_updated_at"],
    }


async def plates_geojson() -> dict:
    return await plates.get_plates()


async def faults_geojson(client: httpx.AsyncClient | None = None) -> dict:
    if not settings.faults_geojson_url:
        raise OverlayUnavailable(
            "Fault layer not configured: no open fault-trace dataset covers Indonesia "
            "(GEM excludes the Malay Archipelago). Set FAULTS_GEOJSON_URL to a LineString/"
            "MultiLineString GeoJSON to enable.")
    import datetime as _dt

    now = time.time()
    if _faults_cache["fc"] is None or now - _faults_cache["at"] > FAULTS_TTL:
        own = client is None
        if own:
            client = httpx.AsyncClient(timeout=settings.bmkg_http_timeout,
                                       headers={"User-Agent": "bmkgintel/1.0"})
        assert client is not None
        try:
            r = await client.get(settings.faults_geojson_url)
            r.raise_for_status()
            clipped = clip_lines(r.json())
            _faults_cache["fc"], _faults_cache["at"] = clipped, now
        finally:
            if own:
                await client.aclose()
    fc = _faults_cache["fc"] or {"type": "FeatureCollection", "features": []}
    return {**fc, "updated_at": _dt.datetime.fromtimestamp(_faults_cache["at"], _dt.timezone.utc).isoformat()
            if _faults_cache["at"] else None}
