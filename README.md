# BMKG Intelligence — Indonesia Environmental Intelligence Dashboard

Bloomberg-Terminal-style geospatial intelligence console on top of **BMKG authoritative data**,
with deterministic correlation and explainable intelligence scoring layered on (never replacing facts).

> v1 scope: BMKG-only. No social / Twitter ingestion. All event facts come from
> BMKG open feeds; enrichment is system-derived heuristics, clearly labelled.
>
> **Status: local-only.** No public deployment yet — run it via the Quickstart below
> (`localhost:3000` + `localhost:8000`).

## Screenshot

**Main Dashboard**
<img width="1919" height="937" alt="image" src="https://github.com/user-attachments/assets/e5aba748-1ec9-4d68-b3a9-10e7a8bebd3b" />

**AI Executive Summary Briefing**
<img width="1919" height="939" alt="image" src="https://github.com/user-attachments/assets/9ac0c92f-806a-4245-b9bd-922a54ae3805" />


## Architecture

```
BMKG TEWS JSON (autogempa / gempaterkini / gempadirasakan)
BMKG CAP nowcast RSS+XML (severe weather)  ──► collectors/ ──► ingest.py ──►
                                                     │            correlate (deterministic) → score → template assessment
                                                     ▼
                                       Postgres(+PostGIS, prod) / SQLite (local dev)
                                                     ▼
                                       FastAPI (/api/v1) ──► Next.js + MapLibre dashboard
```

**Key decisions / tradeoffs**
- Canonical `Event` + supporting `Observation`s + append-only `EventHistory`. One quake across
  the 3 BMKG feeds = one event.
- Correlation is **deterministic** (exact DateTime, then time/distance/magnitude windows).
  No LLM matching — auditable, no invented links.
- Scores are labelled **intelligence priority (0–10)**, explainable component breakdown,
  not validated risk estimates.
- AI text lives only in `ai_assessment`; facts stay in typed columns. Offline template works
  with zero keys; `OPENROUTER_API_KEY` optionally rephrases via OpenRouter (facts frozen).
  Default model is `openrouter/free` (zero-cost router); override with `OPENROUTER_MODEL`.
  Get a key at https://openrouter.ai/keys — free models need no credits.
- DB: Postgres+PostGIS via `docker compose` in prod; SQLite file fallback for zero-dependency
  local dev. Portable lat/lon columns + optional `geom` geography column on Postgres.

## Project structure

```
.
├── backend/            # FastAPI + SQLAlchemy ingest/API service
│   ├── app/
│   │   ├── collectors/ # BMKG quake, CAP nowcast, MAGMA volcanoes, plate boundaries
│   │   ├── services/   # ingest, correlation, scoring, briefing, situations, ...
│   │   ├── api/        # HTTP routes (thin)
│   │   └── core/       # config, db, logging
│   ├── tests/          # pytest suite
│   ├── requirements.txt
│   ├── Dockerfile
│   └── .env.example
├── frontend/           # Next.js + MapLibre dashboard
│   ├── app/ components/ lib/
│   ├── Dockerfile
│   └── .env.example
├── docker-compose.yml
└── .github/workflows/ci.yml
```

## Prerequisites

- Python 3.12+, Node 20+, Docker (optional, for prod-like PostGIS stack)

## Quickstart (local, no Docker)

Backend:
```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m app.ingest_cli --once      # live ingest from BMKG (~30 events)
uvicorn app.main:app --reload --port 8000
```

Frontend:
```bash
cd frontend
npm install
cp .env.example .env.local   # point NEXT_PUBLIC_API_URL at the backend
npm run dev                  # http://localhost:3000 (use `npm run dev -- -p 3100` if 3000 is taken)
```

The map defaults to the public MapLibre demo globe style so it works with zero
API keys; set a production vector-tile URL (e.g. in `components/Map.tsx`) before
any public deployment.

Verify: `curl localhost:8000/api/v1/status`, open the map, click an event.

## Configuration

Backend (`backend/.env`, see `backend/.env.example`):

| Var | Default | Notes |
|-----|---------|-------|
| `DATABASE_URL` | `sqlite+aiosqlite:///./bmkgintel.db` | Use `postgresql+asyncpg://…` for prod/PostGIS |
| `BMKG_HTTP_TIMEOUT` | `15` | Upstream fetch timeout (s) |
| `INGEST_INTERVAL_SECONDS` | `300` | Background ingest cadence; respects BMKG 60 req/min/IP |
| `OPENROUTER_API_KEY` | empty | Optional LLM polish; offline template otherwise |
| `OPENROUTER_MODEL` | `openrouter/free` | Pin e.g. a `:free` model id |
| `FAULTS_GEOJSON_URL` | empty | Optional LineString/MultiLineString GeoJSON to enable faults layer |
| `DUCKDB_PATH` | `./analytics.duckdb` | Disposable OLAP mirror, rebuilt on demand |

Frontend (`frontend/.env.local`, see `frontend/.env.example`):

| Var | Default | Notes |
|-----|---------|-------|
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | Backend base URL |

Never commit `.env` / `.env.local` — they are gitignored. CI uses examples/defaults only.

## Docker (prod-like, with PostGIS)

```bash
docker compose up --build
# frontend :3000, backend :8000, postgis :5432
```

## API

- `GET /api/v1/status` — KPIs + collector health
- `GET /api/v1/events?type=&priority=&status=&q=&since=&limit=`
- `GET /api/v1/events/{id}` — detail + observations + history + breakdown
- `GET /api/v1/feed?limit=` — chronological developments
- `POST /api/v1/ingest/run` — trigger collectors
- `POST /api/v1/events/{id}/resolve`
- `GET /api/v1/briefing` — executive briefing: headline, situation overview,
  priority watchlist, rule-based recommended actions (immediate/soon/routine),
  caveats, plus optional OpenRouter executive note (`llm_summary`, null when
  unconfigured; `llm_status` explains why: off/misconfigured/empty/rejected/error)
- `GET /api/v1/changes?since_hours=24` — What Changed: new, escalated,
  de-escalated, resolved, expired, growing sequences (stateless, from history log)
- `GET /api/v1/clusters` — earthquake sequence clusters (|dt|≤72h, ≤120km chains),
  each with historical context vs up to 400d of regional record
- `GET /api/v1/situations` — connected cross-hazard situations (tsunami threat,
  rain+landslide, volcano-tectonic, weather-volcano, multi-hazard region);
  co-occurrence reported, causality never claimed
- `GET /api/v1/escalation` — system posture NORMAL/WATCH/ALERT with
  evidence-backed, corroboration-gated triggers

## Map overlay layers

Toggleable in the map toolbar (backend-driven via `GET /api/v1/overlays`):

- **Volcanoes** (`GET /api/v1/overlays/volcanoes`) — 69 PVMBG-monitored volcanoes
  with live alert levels (Normal/Waspada/Siaga/Awas) scraped from MAGMA
  Indonesia's server-rendered pages. Triangle color = level.
- **Plate boundaries** (`GET /api/v1/overlays/plates`) — PB2002 (Bird 2003)
  clipped to Indonesia; subduction segments (Sunda/Java trench) drawn distinctly.
- **Active faults** — intentionally *disabled* until configured. No open
  fault-trace dataset covers Indonesia (GEM GAF-DB excludes the Malay
  Archipelago; OSM has ~zero mapped faults there), and hand-drawn faults would
  violate the provenance rule. Set `FAULTS_GEOJSON_URL` to a LineString /
  MultiLineString GeoJSON to enable `GET /api/v1/overlays/faults`.

## Tests / checks

```bash
cd backend && python -m pytest -q
cd ../frontend && npm run typecheck && npm run build
```

CI (`.github/workflows/ci.yml`) runs the same on push/PR.

## Data & attribution

All event facts originate from BMKG open feeds (`data.bmkg.go.id`, `bmkg.go.id/alerts/nowcast`).
The UI header and API root carry the required attribution: *"Data: BMKG (Badan Meteorologi,
Klimatologi, dan Geofisika)"*. Respect the 60 req/min/IP limit; background ingest defaults to 5 min.
