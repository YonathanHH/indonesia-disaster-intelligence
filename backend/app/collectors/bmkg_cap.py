"""BMKG severe-weather nowcast (CAP) collector.

Verified live endpoints (no auth, XML):
  - https://www.bmkg.go.id/alerts/nowcast/id        RSS of active provincial alerts
  - https://www.bmkg.go.id/alerts/nowcast/id/{code}_alert.xml   CAP detail (polygon areas)

RSS item: title, link (detail CAP), description, guid, pubDate.
CAP detail: <alert><info><event/effective/expires/headline/description/
<area><areaDesc><polygon>>. Polygons are "lat,lon lat,lon ..." strings.

We store one canonical Event per CAP guid; centroid of first polygon is the
map point, full polygons preserved in extra for frontend rendering.
"""
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import httpx
from dateutil import parser as dateparser

from app.core.config import settings

log = logging.getLogger(__name__)

RSS_URL = "https://www.bmkg.go.id/alerts/nowcast/id"
NS = {"cap": "urn:oasis:names:tc:emergency:cap:1.2"}


def _text(el: ET.Element | None) -> str:
    return (el.text or "").strip() if el is not None and el.text else ""


def parse_rss(xml_bytes: bytes) -> list[dict]:
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as e:
        log.warning("RSS parse failed: %s", e)
        return []
    items = []
    for it in root.findall(".//item"):
        title = _text(it.find("title"))
        link = _text(it.find("link"))
        desc = _text(it.find("description"))
        guid = _text(it.find("guid")) or link
        pub = _text(it.find("pubDate"))
        try:
            pub_dt = dateparser.parse(pub) if pub else datetime.now(timezone.utc)
            if pub_dt and pub_dt.tzinfo is None:
                pub_dt = pub_dt.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            pub_dt = datetime.now(timezone.utc)
        if not guid:
            continue
        items.append({"guid": guid, "title": title, "link": link, "description": desc, "pubDate": pub_dt})
    return items


def parse_polygon(s: str) -> list[tuple[float, float]]:
    pts = []
    for tok in re.split(r"\s+", s.strip()):
        if "," not in tok:
            continue
        try:
            a, b = tok.split(",", 1)
            pts.append((float(a.strip()), float(b.strip())))
        except ValueError:
            continue
    return pts


def parse_cap(xml_bytes: bytes) -> dict:
    """Extract effective/expires/event/headline/areas/polygons from CAP XML."""
    root = ET.fromstring(xml_bytes)
    # CAP docs may or may not use namespace prefix
    def find(path: str):
        el = root.find(f".//cap:{path}", NS)
        if el is None:
            el = root.find(f".//{path}")
        return el

    def findall_area():
        areas = root.findall(".//cap:area", NS) or root.findall(".//area")
        return areas

    event = _text(find("event"))
    effective = _text(find("effective"))
    expires = _text(find("expires"))
    headline = _text(find("headline"))
    description = _text(find("description"))
    web = _text(find("web"))
    severity = _text(find("severity"))
    urgency = _text(find("urgency"))
    certainty = _text(find("certainty"))
    areas, polygons = [], []
    for a in findall_area():
        desc_el = a.find("cap:areaDesc", NS)
        if desc_el is None:
            desc_el = a.find("areaDesc")
        poly_el = a.find("cap:polygon", NS)
        if poly_el is None:
            poly_el = a.find("polygon")
        ad = _text(desc_el)
        poly = parse_polygon(_text(poly_el)) if poly_el is not None else []
        if ad:
            areas.append(ad)
        if poly:
            polygons.append(poly)
    return {
        "event": event, "effective": effective, "expires": expires,
        "headline": headline, "description": description, "web": web,
        "severity": severity, "urgency": urgency, "certainty": certainty,
        "areas": areas, "polygons": polygons,
    }


def centroid(polygons: list[list[tuple[float, float]]]) -> tuple[float | None, float | None]:
    pts = [p for poly in polygons for p in poly]
    if not pts:
        return None, None
    return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)


def _dt(s: str | None, fallback: datetime) -> datetime:
    if not s:
        return fallback
    try:
        d = dateparser.isoparse(s)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return fallback


async def fetch_nowcast(client: httpx.AsyncClient | None = None, max_alerts: int = 25) -> list[dict]:
    """Return normalized weather observations. Never raises."""
    own = client is None
    if own:
        client = httpx.AsyncClient(timeout=settings.bmkg_http_timeout, headers={"User-Agent": "bmkgintel/1.0"})
    assert client is not None
    out: list[dict] = []
    try:
        try:
            r = await client.get(RSS_URL)
            r.raise_for_status()
            items = parse_rss(r.content)
        except Exception as e:
            log.warning("nowcast RSS fetch failed: %s", e)
            return []
        for it in items[:max_alerts]:
            cap = {"event": "", "effective": "", "expires": "", "headline": "",
                   "description": it["description"], "web": "", "severity": "",
                   "urgency": "", "certainty": "", "areas": [], "polygons": []}
            try:
                if it["link"]:
                    d = await client.get(it["link"])
                    d.raise_for_status()
                    cap = parse_cap(d.content)
            except Exception as e:
                log.warning("CAP detail %s failed, using RSS fallback: %s", it["link"], e)
            lat, lon = centroid(cap["polygons"])
            if lat is None:  # no geometry — keep observation but unmappable; skip event creation later
                lat, lon = None, None
            effective = _dt(cap["effective"], it["pubDate"])
            expires = _dt(cap["expires"], it["pubDate"])
            out.append({
                "kind": "bmkg_cap",
                "source": "bmkg",
                "external_id": f"bmkg-cap:{it['guid']}",
                "author": "BMKG",
                "text": it["title"] or cap["headline"],
                "url": it["link"] or None,
                "observed_at": it["pubDate"],
                "structured": {
                    "event": cap["event"] or it["title"],
                    "headline": cap["headline"] or it["title"],
                    "description": cap["description"] or it["description"],
                    "severity": cap["severity"], "urgency": cap["urgency"],
                    "certainty": cap["certainty"],
                    "effective": effective.isoformat(), "expires": expires.isoformat(),
                    "areas": cap["areas"], "area_count": len(cap["areas"]),
                    "latitude": lat, "longitude": lon,
                    "web": cap["web"] or None,
                },
                "raw": {"rss": it, "cap": {k: v for k, v in cap.items() if k != "polygons"},
                        "polygons": cap["polygons"]},
            })
    finally:
        if own:
            await client.aclose()
    return out
