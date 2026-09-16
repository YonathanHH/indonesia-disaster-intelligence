"""Overlay collector/service tests (fixtures only — no network)."""
import pytest

from app.collectors import magma
from app.collectors.plates import clip_feature_collection
from app.services import overlays
from app.services.overlays import clip_lines

BASE_HTML = """
<table><tbody>
<tr><td><a href="https://magma.esdm.go.id/v1/gunung-api/merapi">Merapi</a></td><td>-7.542</td><td>110.442</td></tr>
<tr><td><a href="https://magma.esdm.go.id/v1/gunung-api/agung/">Agung</a></td><td>-8.342</td><td>115.508</td></tr>
<tr><td>header</td><td>Latitude (LU)</td><td>Longitude (BT)</td></tr>
</tbody></table>
"""

LEVELS_HTML = """
<table><tbody>
<tr><td><a>Level III (Siaga)</a><span>desc</span></td><td>1</td></tr>
<tr><td>Merapi - Daerah Istimewa Yogyakarta dan Jawa Tengah <a>Lihat laporan</a><br></td></tr>
<tr><td><a>Level I (Normal)</a><span>desc</span></td><td>1</td></tr>
<tr><td>Agung - Bali <a>Lihat laporan</a><br></td></tr>
</tbody></table>
"""


def test_magma_base_parsing():
    rows = magma.parse_base(BASE_HTML)
    assert len(rows) == 2
    assert rows[0] == {"name": "Merapi", "slug": "merapi", "latitude": -7.542, "longitude": 110.442}
    assert rows[1]["slug"] == "agung"  # trailing slash tolerated


def test_magma_levels_parsing():
    lv = magma.parse_levels(LEVELS_HTML)
    assert lv["merapi"] == {"level": "siaga", "province": "Daerah Istimewa Yogyakarta dan Jawa Tengah"}
    assert lv["agung"] == {"level": "normal", "province": "Bali"}


async def test_volcano_merge_marks_unknown_without_levels(monkeypatch):
    async def fake_base(*a, **k):
        return None

    monkeypatch.setattr(magma, "_fetch", fake_base)
    magma._cache.update({"base": [{"name": "Merapi", "slug": "merapi", "latitude": -7.5, "longitude": 110.4}],
                         "base_at": 9999999999.0, "levels": None, "levels_at": 0.0})
    out = await magma.get_volcanoes()
    assert out["volcanoes"][0]["level"] == "UNKNOWN"
    magma._cache.update({"base": None, "base_at": 0.0, "levels": None, "levels_at": 0.0})


def test_plates_clip_keeps_indonesia_only():
    fc = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"Name": "SU-AU", "PlateA": "SU", "PlateB": "AU", "Type": "subduction"},
         "geometry": {"type": "LineString", "coordinates": [[104.5, -8.1], [106.0, -9.2], [50.0, 30.0]]}},
        {"type": "Feature", "properties": {"Name": "AF-AN", "PlateA": "AF", "PlateB": "AN", "Type": ""},
         "geometry": {"type": "LineString", "coordinates": [[-10.0, -55.0], [-11.0, -56.0]]}},
    ]}
    out = clip_feature_collection(fc)
    assert len(out["features"]) == 1
    f = out["features"][0]
    assert f["properties"] == {"name": "SU-AU", "plates": "SU-AU", "boundary_type": "subduction"}
    assert f["geometry"]["coordinates"] == [[104.5, -8.1], [106.0, -9.2]]


def test_clip_lines_handles_multi():
    fc = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"name": "Semangko"},
         "geometry": {"type": "MultiLineString",
                      "coordinates": [[[100.0, 0.0], [101.0, 1.0]], [[-50.0, -50.0], [-51.0, -51.0]]]}},
        {"type": "Feature", "properties": {},
         "geometry": {"type": "Point", "coordinates": [110.0, -7.5]}},
    ]}
    out = clip_lines(fc)
    assert len(out["features"]) == 1
    assert out["features"][0]["geometry"]["type"] == "LineString"


async def test_faults_unconfigured_raises(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "faults_geojson_url", "")
    with pytest.raises(overlays.OverlayUnavailable):
        await overlays.faults_geojson()


async def test_layer_index_reports_faults_unavailable(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "faults_geojson_url", "")
    monkeypatch.setattr(magma, "get_volcanoes", lambda *a, **k: _empty_volc())
    from app.collectors import plates as plates_mod
    monkeypatch.setattr(plates_mod, "get_plates", lambda *a, **k: _empty_plates())
    idx = await overlays.layer_index()
    by_id = {l["id"]: l for l in idx}
    assert by_id["faults"]["available"] is False
    assert "reason" in by_id["faults"]


def _empty_volc():
    async def _go(*a, **k):
        return {"volcanoes": [], "updated_at": None, "levels_updated_at": None, "attribution": "x"}
    return _go()


def _empty_plates():
    async def _go(*a, **k):
        return {"type": "FeatureCollection", "features": [], "attribution": "y", "updated_at": None}
    return _go()
