"""PVMBG/MAGMA volcano overlay collector.

Authoritative source: MAGMA Indonesia (Pusat Vulkanologi dan Mitigasi
Bencana Geologi, Badan Geologi, Kementerian ESDM).
  - Base list (name, slug, lat, lon): https://magma.esdm.go.id/v1/gunung-api
  - Live activity levels:             https://magma.esdm.go.id/v1/gunung-api/tingkat-aktivitas
Both pages are server-rendered HTML tables — parsed with stdlib html.parser
(no new dependencies). Levels change often (cache 1h); base coords rarely
(cache 30d). Process-local TTL cache; failures return the last good snapshot.
"""
import logging
import re
import time
from html.parser import HTMLParser

import httpx

from app.core.config import settings

log = logging.getLogger(__name__)

BASE_URL = "https://magma.esdm.go.id/v1/gunung-api"
LEVELS_URL = "https://magma.esdm.go.id/v1/gunung-api/tingkat-aktivitas"

LEVELS = {
    "awas": {"code": 4, "label": "AWAS", "color": "#f87171"},
    "siaga": {"code": 3, "label": "SIAGA", "color": "#fb923c"},
    "waspada": {"code": 2, "label": "WASPADA", "color": "#fbbf24"},
    "normal": {"code": 1, "label": "NORMAL", "color": "#34d399"},
}

_cache: dict = {"base": None, "base_at": 0.0, "levels": None, "levels_at": 0.0}
BASE_TTL = 30 * 86400
LEVELS_TTL = 3600


def _norm_name(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


class _BaseTableParser(HTMLParser):
    """Extract (name, slug, lat, lon) rows from the Data Dasar table."""

    def __init__(self):
        super().__init__()
        self.rows: list[dict] = []
        self._cells: list[str] = []
        self._href = ""
        self._in_td = False
        self._buf = ""

    def handle_starttag(self, tag, attrs):
        if tag == "td":
            self._in_td = True
            self._buf = ""
        if tag == "a":
            for k, v in attrs:
                if k == "href" and "/v1/gunung-api/" in v:
                    self._href = v.rstrip("/").split("/")[-1]

    def handle_data(self, data):
        if self._in_td:
            self._buf += data

    def handle_endtag(self, tag):
        if tag == "td":
            self._in_td = False
            self._cells.append(self._buf.strip())
        if tag == "tr":
            if len(self._cells) >= 3 and self._href:
                try:
                    self.rows.append({
                        "name": self._cells[0], "slug": self._href,
                        "latitude": float(self._cells[1]), "longitude": float(self._cells[2]),
                    })
                except ValueError:
                    pass
            self._cells = []
            self._href = ""


class _LevelsParser(HTMLParser):
    """Extract {volcano_name: {level, province}} from the Tingkat Aktivitas table.

    Level header rows contain 'Level IV (Awas)' etc.; member rows contain
    'Name - Province' followed by a 'Lihat laporan' link.
    """

    def __init__(self):
        super().__init__()
        self.levels: dict[str, dict] = {}
        self._current: str | None = None
        self._in_td = False
        self._buf = ""

    def handle_starttag(self, tag, attrs):
        if tag == "td":
            self._in_td = True
            self._buf = ""

    def handle_data(self, data):
        if self._in_td:
            self._buf += data

    def handle_endtag(self, tag):
        if tag != "td":
            return
        self._in_td = False
        text = self._buf.strip()
        m = re.search(r"Level\s+(IV|III|II|I)\s*\(([^)]+)\)", text)
        if m:
            key = m.group(2).strip().lower()
            if key in LEVELS:
                self._current = key
            return
        if self._current and text and "Lihat laporan" in text:
            name = text.split("Lihat laporan")[0].strip()
            if " - " in name:
                vname, province = name.split(" - ", 1)
            else:
                vname, province = name, ""
            self.levels[_norm_name(vname)] = {"level": self._current, "province": province.strip()}


def parse_base(html: str) -> list[dict]:
    p = _BaseTableParser()
    p.feed(html)
    return p.rows


def parse_levels(html: str) -> dict[str, dict]:
    p = _LevelsParser()
    p.feed(html)
    return p.levels


async def _fetch(client: httpx.AsyncClient, url: str) -> str | None:
    try:
        r = await client.get(url)
        r.raise_for_status()
        return r.text
    except Exception as e:
        log.warning("MAGMA fetch %s failed: %s", url, e)
        return None


async def get_volcanoes(client: httpx.AsyncClient | None = None, force: bool = False) -> dict:
    """Return {volcanoes: [...merged...], updated_at, levels_updated_at, attribution}.

    Never raises — on total failure returns the last cached snapshot or empty.
    """
    import datetime as _dt

    own = client is None
    if own:
        client = httpx.AsyncClient(timeout=settings.bmkg_http_timeout,
                                   headers={"User-Agent": "bmkgintel/1.0"})
    assert client is not None
    now = time.time()
    try:
        if force or _cache["base"] is None or now - _cache["base_at"] > BASE_TTL:
            html = await _fetch(client, BASE_URL)
            if html:
                rows = parse_base(html)
                if rows:
                    _cache["base"], _cache["base_at"] = rows, now
        if force or _cache["levels"] is None or now - _cache["levels_at"] > LEVELS_TTL:
            html = await _fetch(client, LEVELS_URL)
            if html:
                lv = parse_levels(html)
                if lv:
                    _cache["levels"], _cache["levels_at"] = lv, now
    finally:
        if own:
            await client.aclose()
    base = _cache["base"] or []
    levels = _cache["levels"] or {}
    merged = []
    for v in base:
        lv = levels.get(_norm_name(v["name"]), {})
        key = lv.get("level")
        meta = LEVELS.get(key, {"code": 0, "label": "UNKNOWN", "color": "#93a1b3"})
        merged.append({
            **v,
            "level": meta["label"], "level_code": meta["code"], "level_color": meta["color"],
            "province": lv.get("province", ""),
            "url": f"https://magma.esdm.go.id/v1/gunung-api/{v['slug']}",
        })
    return {
        "volcanoes": merged,
        "updated_at": _dt.datetime.fromtimestamp(_cache["base_at"], _dt.timezone.utc).isoformat()
        if _cache["base_at"] else None,
        "levels_updated_at": _dt.datetime.fromtimestamp(_cache["levels_at"], _dt.timezone.utc).isoformat()
        if _cache["levels_at"] else None,
        "attribution": "PVMBG/MAGMA Indonesia (Badan Geologi, Kementerian ESDM)",
    }
