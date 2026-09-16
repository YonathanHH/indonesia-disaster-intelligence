"""BMKG parsing / normalization tests use real-shaped fixtures."""
from app.collectors.bmkg_quake import normalize_quake_record, parse_coords, parse_depth
from app.collectors.bmkg_cap import parse_cap, parse_polygon, parse_rss


def test_parse_depth():
    assert parse_depth("10 km") == 10.0
    assert parse_depth("376 km") == 376.0
    assert parse_depth(None) is None


def test_parse_coords():
    assert parse_coords("-5.81,106.56") == (-5.81, 106.56)


def test_normalize_latest_real_shape():
    raw = {"Tanggal": "12 Sep 2026", "Jam": "20:05:59 WIB", "DateTime": "2026-09-12T13:05:59+00:00",
           "Coordinates": "-8.96,116.84", "Lintang": "8.96 LS", "Bujur": "116.84 BT",
           "Magnitude": "2.7", "Kedalaman": "10 km",
           "Wilayah": "Pusat gempa berada di darat 23 km Selatan Sumbawa Barat",
           "Potensi": "Gempa ini dirasakan untuk diteruskan pada masyarakat",
           "Dirasakan": "III Sumbawa Barat", "Shakemap": "20260912200559.mmi.jpg"}
    n = normalize_quake_record(raw, "bmkg_latest")
    assert n is not None
    assert n["structured"]["magnitude"] == 2.7
    assert n["structured"]["latitude"] == -8.96
    assert n["structured"]["tsunami_potential"] is False
    assert "shakemap_url" in n["structured"]


def test_normalize_tsunami_flag():
    raw = {"DateTime": "2026-09-12T13:05:59+00:00", "Coordinates": "-8.96,116.84",
           "Magnitude": "7.5", "Kedalaman": "10 km", "Wilayah": "X",
           "Potensi": "Berpotensi TSUNAMI untuk diteruskan pada masyarakat"}
    n = normalize_quake_record(raw, "bmkg_m5")
    assert n["structured"]["tsunami_potential"] is True


def test_normalize_malformed_skipped():
    assert normalize_quake_record({"Magnitude": "x"}, "bmkg_m5") is None


def test_rss_parsing_real_shape():
    rss = b"""<?xml version="1.0"?><rss version="2.0"><channel>
    <item><title>Hujan Lebat di Jambi</title><link>https://x/id/1_alert.xml</link>
    <description>desc</description><guid>2.49.0.1.360.0.2026.09.12.14.15.005</guid>
    <pubDate>Sat, 12 Sep 2026 01:55:00 +0700</pubDate></item></channel></rss>"""
    items = parse_rss(rss)
    assert len(items) == 1 and items[0]["guid"].startswith("2.49")


def test_cap_parsing_and_polygon():
    cap = b"""<alert xmlns="urn:oasis:names:tc:emergency:cap:1.2"><info>
    <event>flood</event><severity>Severe</severity><urgency>Expected</urgency><certainty>Likely</certainty>
    <effective>2026-09-12T02:05:00+07:00</effective><expires>2026-09-12T05:00:00+07:00</expires>
    <headline>Hujan Lebat di Jambi</headline><description>desc</description>
    <area><areaDesc>JAMBI</areaDesc><polygon>-1.0,103.0 -1.1,103.1 -1.0,103.2</polygon></area>
    </info></alert>"""
    out = parse_cap(cap)
    assert out["severity"] == "Severe"
    assert len(out["polygons"]) == 1 and len(out["polygons"][0]) == 3
    assert parse_polygon("-1.0,103.0 -1.1,103.1") == [(-1.0, 103.0), (-1.1, 103.1)]
