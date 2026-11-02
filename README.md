# BMKG Intelligence — Indonesia Environmental Intelligence Dashboard

Bloomberg-Terminal-style geospatial intelligence console on top of **BMKG authoritative data**,
with deterministic correlation and explainable intelligence scoring layered on (never replacing facts).

> v1 scope: BMKG-only. No social / Twitter ingestion. All event facts come from
> BMKG open feeds; enrichment is system-derived heuristics, clearly labelled.
>
> **Deployment target: Vercel** — one project, two services (`web` = Next.js,
> `api` = FastAPI), configured in `vercel.json`. Collection is scheduled, not
> user-triggered: `0 17 * * *` UTC ingests BMKG data and `0 18 * * *` UTC writes
> the morning executive brief, i.e. **00:00 and 01:00 WIB**. Vercel cron schedules
> are always UTC, and the Hobby plan fires a daily cron anywhere inside its hour —
> 17:00 UTC can run at 17:59 — so read "00:00" as "within the first hour of the
> day". Nothing depends on the exact minute: both jobs are idempotent, and opening
> the dashboard re-runs whatever is overdue.
>
> Local use is unchanged: run it via the Quickstart below
> (`localhost:3000` + `localhost:8000`).

## Screenshot

**Main Dashboard**
<img width="1919" height="937" alt="image" src="https://github.com/user-attachments/assets/e5aba748-1ec9-4d68-b3a9-10e7a8bebd3b" />

**AI Executive Summary Briefing**
<img width="1919" height="939" alt="image" src="https://github.com/user-attachments/assets/9ac0c92f-806a-4245-b9bd-922a54ae3805" />


## Architecture

```
Vercel Cron (17:00 / 18:00 UTC = 00:00 / 01:00 WIB)
        │ GET /api/v1/jobs/nightly-ingest · GET /api/v1/jobs/nightly-brief
        │ Bearer CRON_SECRET
        ▼
BMKG TEWS JSON (autogempa / gempaterkini / gempadirasakan)
BMKG CAP nowcast RSS+XML (severe weather)  ──► collectors/ ──► ingest.py ──►
                                                     │            correlate (deterministic) → score → template assessment
                                                     ▼
                                       Postgres(+PostGIS, prod) / SQLite (local dev)
                                                     │
                                       stored briefing document (a read, not a recompute)
                                                     ▼
                          FastAPI (/api/v1) ──► Next.js + MapLibre dashboard
                          Vercel service "api" ◄── rewrite /api/v1/* ── Vercel service "web"
```

**Key decisions / tradeoffs**
- Canonical `Event` + supporting `Observation`s + append-only `EventHistory`. One quake across
  the 3 BMKG feeds = one event.
- Ingestion is **scheduled and claimed**, never user-triggered. The crons own the nightly
  cycle; `POST /ingest/run` on dashboard load only does real work when the claim interval has
  elapsed, so five tabs opening at once cost one BMKG round trip. There is no `while True`
  loop in the app: a serverless invocation is not a process that can host one.
- Executive briefings are **stored rows, read on demand** (`GET /briefing` → the newest
  document, tagged `kind: daily | live`), not recomputed per request. Rebuilding an LLM note
  takes ~25s, which belongs in a cron, not in a page load.
- Correlation is **deterministic** (exact DateTime, then time/distance/magnitude windows).
  No LLM matching — auditable, no invented links.
- Scores are labelled **intelligence priority (0–10)**, explainable component breakdown,
  not validated risk estimates.
- AI text lives only in `ai_assessment`; facts stay in typed columns. Offline template works
  with zero keys; `OPENROUTER_API_KEY` optionally rephrases via OpenRouter (facts frozen).
  Default model is `openrouter/free` (zero-cost router); override with `OPENROUTER_MODEL`.
  Get a key at https://openrouter.ai/keys — free models need no credits.
- DB: Postgres+PostGIS (Neon on Vercel, `docker compose` locally) in prod; SQLite file
  fallback for zero-dependency local dev. Portable lat/lon columns + optional `geom`
  geography column on Postgres — the app degrades to the portable columns if the role
  cannot `CREATE EXTENSION postgis`.
- Mutating endpoints are secret-gated (`OPERATOR_SECRET`); the public UI keeps no credentials,
  because a secret in client JS is not a secret.

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
│   ├── instrumentation.ts        # starts FastAPI when `next dev` boots
│   ├── scripts/dev-backend.mjs   # backend launcher (auto-uses backend/.venv)
│   ├── Dockerfile
│   └── .env.example
├── docker-compose.yml
├── vercel.json         # two services (web + api), routing, cron schedules
├── package.json        # root shortcuts: `npm run dev` / `npm run dev:docker`
├── scripts/setup.mjs   # `npm run setup`: venv + backend/frontend deps
└── .github/workflows/ci.yml
```

## Prerequisites

- Node 20+, Python 3.12+ (Docker only needed for the optional `dev:docker` PostGIS stack)

## Quickstart (no Docker)

```bash
npm run setup   # creates backend/.venv + installs Python and frontend deps
cp backend/.env.example backend/.env          # first time only
cp frontend/.env.example frontend/.env.local  # first time only

npm run dev  # Next dev on :3000; it starts FastAPI on :8000 automatically
```

`npm run setup` is idempotent: it reuses `backend/.venv` and only installs
missing packages. The first dashboard load asks the API to collect, so
`python -m app.ingest_cli --once` is only needed if you want data before opening
the UI.

You only need one command. `npm run dev` (from the repo root or `frontend/`)
starts Next.js, which launches the API, waits for it to be ready, and proxies
`/api/v1/*` to it (development only — in a deployment, Vercel's route table sends
`/api/v1/*` to the `api` service). Open **http://localhost:3000** — the API is
never a separate terminal. Use `npm run dev:backend` if you want the API on its own.

Docker alternative (prod-like, with PostGIS):

```bash
npm run dev:docker  # postgis :5432, backend :8000, frontend :3000
npm run dev:down    # stop the stack
```

The map uses CARTO's key-free `dark-matter` vector style as its basemap, with the
public MapLibre demo globe only as an `on("error")` fallback, so it works with no
API keys and needs no configuration before deploying.

Verify: open http://localhost:3000 and click an event. `curl localhost:3000/api/v1/status` should return the same payload as `curl localhost:8000/api/v1/status`.

## Configuration

Backend (`backend/.env`, see `backend/.env.example`):

| Var | Default | Notes |
|-----|---------|-------|
| `DATABASE_URL` | `sqlite+aiosqlite:///./bmkgintel.db` | `postgresql+asyncpg://…` for prod/PostGIS (Neon: use the **direct**, non-pooled URL) |
| `BMKG_HTTP_TIMEOUT` | `15` | Upstream fetch timeout (s) |
| `INGEST_INTERVAL_SECONDS` | `300` | Minimum seconds between real ingests (the on-load refresh guard); respects BMKG 60 req/min/IP |
| `BRIEF_MIN_REBUILD_SECONDS` | `900` | Floor between stored-brief rebuilds, independent of how often ingest runs |
| `CRON_SECRET` | empty | Bearer token Vercel Cron must present on `/api/v1/jobs/*`. **Unset = every job call is rejected** (fail closed) |
| `OPERATOR_SECRET` | empty | Bearer token required by `POST /api/v1/events/{id}/resolve`. Unset = Resolve is closed; the public UI holds no secret |
| `ALLOWED_ORIGINS` | empty | Comma-separated exact origins for CORS. Leave empty in the Vercel deploy — routing keeps the browser same-origin |
| `OPENROUTER_API_KEY` | empty | Optional LLM polish; offline template otherwise |
| `OPENROUTER_MODEL` | `openrouter/free` | A working value: OpenRouter's zero-cost router. Pin a specific `:free` model id to override |
| `FAULTS_GEOJSON_URL` | empty | Optional LineString/MultiLineString GeoJSON to enable faults layer |

Frontend (`frontend/.env.local`, see `frontend/.env.example`):

| Var | Default | Notes |
|-----|---------|-------|
| `NEXT_PUBLIC_API_URL` | empty | Empty = same-origin `/api/v1/*`: proxied by Next in dev, routed by Vercel's `rewrites` in a deployment. Set only to call the backend directly. |
| `BACKEND_INTERNAL_URL` | `http://127.0.0.1:8000` | Where the dev server proxies API requests. Compose sets `http://backend:8000`. Unused in production. |
| `BACKEND_PORT` | `8000` | Port the auto-started backend listens on (local dev). |
| `DEV_BACKEND` | unset | Set `0` to stop `next dev` from auto-starting the API. |

Never commit `.env` / `.env.local` — they are gitignored. CI uses examples/defaults only.

## Deploy on Vercel

`vercel.json` declares the whole topology: a `web` service (`frontend/`, Next.js) and an
`api` service (`backend/`, FastAPI on the Python runtime), the route table that exposes
`/api/v1/*` to `api` and everything else to `web`, and the two crons. Services are in Beta
and available on all plans.

1. **Storage.** Install Neon from the Vercel Marketplace and set `DATABASE_URL` to its
   **direct** (non-pooled) `postgresql+asyncpg://…` URL. The engine runs with
   `statement_cache_size = 0`, so a transaction-pooling URL also works if you hit Neon's
   connection ceiling — but the direct URL is the simpler default for a nightly job.
   PostGIS is optional: if the role cannot `CREATE EXTENSION postgis`, the app logs it and
   keeps the portable lat/lon columns.
2. **Secrets.** Set `CRON_SECRET`, `OPERATOR_SECRET`, `OPENROUTER_API_KEY`,
   `OPENROUTER_MODEL=openrouter/free` in the project's Environment Variables (never as
   `NEXT_PUBLIC_*`; the browser must not see them). `ALLOWED_ORIGINS` can stay empty.
3. **Deploy.** `vercel` (preview) then promote. Crons attach to **production** only;
   confirm with `vercel crons list`.
4. **Check.** `GET /api/v1/jobs/nightly-ingest` without the header must return `401`;
   with `Authorization: Bearer $CRON_SECRET` it returns the ingest summary.
   `GET /api/v1/briefing` must answer in well under a second — it reads a stored document.

Hobby fires each daily cron somewhere inside its hour, so the brief can land up to an hour
after the ingest (or, at worst, a minute after it). That is harmless: the brief stamps the
ingest it was built on, and the next dashboard load rebuilds a `live` brief if the data moved.

`backend/.env` for local dev must keep a SQLite or compose-Postgres `DATABASE_URL`. Pointing
`npm run dev` at the production database makes your laptop and the crons race over the same rows.

## Docker (prod-like, with PostGIS)

```bash
npm run dev:docker   # or: docker compose up --build
# frontend :3000, backend :8000, postgis :5432
```

The browser still uses only http://localhost:3000; Next proxies `/api/v1/*`
to the `backend` service over the compose network.

## API

- `GET /api/v1/status` — KPIs + collector health
- `GET /api/v1/events?type=&priority=&status=&q=&since=&limit=`
- `GET /api/v1/events/{id}` — detail + observations + history + breakdown
- `GET /api/v1/feed?limit=` — chronological developments
- `POST /api/v1/ingest/run` — on-load refresh, fired by the dashboard. Claim-guarded
  (`INGEST_INTERVAL_SECONDS`) and unauthenticated by design: a secret in client JS is not a
  secret, so the claim interval is the authorization. Returns `{quakes, weather, skipped?,
  brief_rebuilt}`
- `GET /api/v1/jobs/nightly-ingest` — 00:00 WIB cron. Collectors only, `Bearer CRON_SECRET`
- `GET /api/v1/jobs/nightly-brief` — 01:00 WIB cron. Stores the dated `kind: daily` brief,
  re-ingesting first if the last success is >12h old
- `POST /api/v1/events/{id}/resolve` — requires `Bearer OPERATOR_SECRET` (no secret in the
  public UI)
- `GET /api/v1/briefing` — the **stored** executive briefing (newest row, `kind: daily | live`):
  headline, situation overview, priority watchlist, rule-based recommended actions
  (immediate/soon/routine), caveats, plus the optional OpenRouter executive note
  (`llm_summary`, null when unconfigured; `llm_status` explains why:
  off/misconfigured/empty/rejected/error). Builds once on an empty store, never per request
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
npm run typecheck && npm run build   # frontend shortcuts from repo root
```

CI (`.github/workflows/ci.yml`) runs the same on push/PR.

## Data & attribution

All event facts originate from BMKG open feeds (`data.bmkg.go.id`, `bmkg.go.id/alerts/nowcast`).
The UI header and API root carry the required attribution: *"Data: BMKG (Badan Meteorologi,
Klimatologi, dan Geofisika)"*. Respect the 60 req/min/IP limit; the nightly cron does one full
cycle and the on-load guard keeps any extra collection to at most one per `INGEST_INTERVAL_SECONDS`.
