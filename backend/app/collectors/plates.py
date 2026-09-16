"""Tectonic plate-boundary overlay (PB2002, Bird 2003).

Source: https://github.com/fraxen/tectonicplates (GeoJSON of PB2002_boundaries).
Fetched server-side, clipped to the Indonesia window, cached 30d. Subduction
segments (properties.Type == 'subduction', incl. the Sunda/Java trench) are
kept with their type so the frontend can style them distinctly.
Attribution required: Bird (2003) via fraxen/tectonicplates.
"""
import logging
import time

import httpx

from app.core.config import settings

log = logging.getLogger(__name__)

PB2002_URL = "https://raw.githubusercontent.com/fraxen/tectonicplates/master/GeoJSON/PB2002_boundaries.json"
# Indonesia window (generous so trench + Philippine Sea segments survive clip)
LON_MIN, LON_MAX = 90.0, 145.0
LAT_MIN, LAT_MAX = -12.0, 8.0

_cache: dict = {"fc": None, "at": 0.0}
TTL = 30 * 86400


def clip_feature_collection(fc: dict) -> dict:
    out = []
    for f in fc.get("features", []):
        geom = f.get("geometry") or {}
        if geom.get("type") != "LineString":
            continue
        coords = [c for c in geom.get("coordinates", [])
                  if LON_MIN <= c[0] <= LON_MAX and LAT_MIN <= c[1] <= LAT_MAX]
        if len(coords) < 2:
            continue
        props = f.get("properties") or {}
        out.append({
            "type": "Feature",
            "properties": {
                "name": props.get("Name", ""),
                "plates": f"{props.get('PlateA', '')}-{props.get('PlateB', '')}",
                "boundary_type": (props.get("Type") or "divergent/transform").lower(),
            },
            "geometry": {"type": "LineString", "coordinates": coords},
        })
    return {"type": "FeatureCollection", "features": out,
            "attribution": "Plate boundaries: Bird (2003) PB2002 via fraxen/tectonicplates"}


async def get_plates(client: httpx.AsyncClient | None = None, force: bool = False) -> dict:
    import datetime as _dt

    own = client is None
    if own:
        client = httpx.AsyncClient(timeout=settings.bmkg_http_timeout,
                                   headers={"User-Agent": "bmkgintel/1.0"})
    assert client is not None
    now = time.time()
    try:
        if force or _cache["fc"] is None or now - _cache["at"] > TTL:
            try:
                r = await client.get(PB2002_URL)
                r.raise_for_status()
                clipped = clip_feature_collection(r.json())
                if clipped["features"]:
                    _cache["fc"], _cache["at"] = clipped, now
            except Exception as e:
                log.warning("PB2002 fetch failed: %s", e)
    finally:
        if own:
            await client.aclose()
    fc = _cache["fc"] or {"type": "FeatureCollection", "features": [],
                          "attribution": "Plate boundaries: Bird (2003) PB2002 via fraxen/tectonicplates"}
    return {**fc, "updated_at": _dt.datetime.fromtimestamp(_cache["at"], _dt.timezone.utc).isoformat()
            if _cache["at"] else None}
