# Vercel deployment + scheduled executive digest

Date: 2026-11-02
Status: approved design, pending implementation plan
Scope: deploy bmkgintel to Vercel; convert the executive brief from a user-triggered
computation into a stored artifact produced by scheduled jobs.

## 1. Problem

Two things are true today and both block a public deployment:

- The backend is a resident process. `backend/app/main.py:19-35` starts an infinite
  `asyncio` ingest loop in the FastAPI lifespan, and state lives in a local SQLite file
  (`backend/bmkgintel.db`) or a Docker volume. Neither survives a serverless platform.
- The executive brief is recomputed inside the request path. `GET /api/v1/briefing`
  (`backend/app/api/routes.py:170-174`) calls `build_briefing` on every request, which
  runs queries over up to 2000 history rows, scrapes MAGMA live, and may make a
  20-second LLM call. The result is never persisted — no briefing table exists. The only
  way to get a digest is for a human to click.

Goal: the system produces the digest on its own schedule, the dashboard reads a stored
document, and the whole thing runs on Vercel's free tier.

## 2. Approved decisions

| # | Decision | Choice |
|---|---|---|
| 1 | Data freshness | Daily crons + guarded ingest on dashboard load |
| 2 | Topology | One Vercel project, two Vercel Services |
| 3 | Digest LLM | OpenRouter free router (`openrouter/free`) |
| 4 | Database | Neon via Vercel Marketplace, direct (non-pooled) endpoint |
| 5 | Brief lifecycle | Auto-rebuild on each new ingest; no Regenerate button |
| 6 | Analytics sidecar | Replace DuckDB with SQL aggregates |
| 7 | Exposure | Public read; authenticated jobs |
| 8 | Execution model | Rebuild inside the invoking function (Approach A), no `waitUntil` |

## 3. Platform constraints (verified, not assumed)

- **Cron requests are HTTP GET.** Vercel "makes an HTTP GET request to your project's
  production deployment URL". A `POST`-only job endpoint returns 405 and silently never runs.
- **Cron schedules are always UTC.** `0 17 * * *` = 00:00 WIB, `0 18 * * *` = 01:00 WIB.
- **Hobby crons run at most once per day, with per-hour precision.** An expression that
  fires more often fails the deployment. A job set for 18:00 UTC may run any time up to
  18:59:59 UTC, so "01:00 WIB" is really "01:00–01:59 WIB". Per-minute precision requires Pro.
- **No retry, best-effort delivery, and overlapping runs are possible.** Vercel does not
  retry a failed cron, may skip one on transient network error, and may deliver the same
  scheduled run twice. Jobs must be idempotent and reconciliation-based, and must lock
  against concurrent execution.
- **`CRON_SECRET`** in the project's env vars is automatically sent as
  `Authorization: Bearer <secret>` on cron invocations.
- **Vercel Postgres no longer exists.** Postgres comes from the Marketplace (Neon, Supabase,
  etc.). Neon supports PostGIS via `CREATE EXTENSION`.
- **Python on Vercel is GA.** ASGI apps are detected from `requirements.txt` and loaded from
  a recognised entrypoint (`app` / `main` / `asgi`, at root or under `src/` or `app/`), or
  from an explicit `entrypoint` setting. Standard Python bundle limit is 500 MB uncompressed.
- **FastAPI lifespan startup runs on Vercel; shutdown cleanup is limited to ~500 ms.**
- **Python functions should not rely on `waitUntil`** for post-response work; Vercel's
  FastAPI guide directs background work to Cron Jobs or Queues.
- **Fluid Compute gives every plan 300 s max duration**, which covers ingest + brief + LLM.
- **Services are Beta on all plans.** When `services` is present, `functions`,
  `installCommand`, `buildCommand`, `devCommand`, `ignoreCommand`, `outputDirectory` and
  `framework` are invalid at the top level and must move into the owning service.
  **A routed service receives the original request path**, unchanged.

## 4. Architecture

`vercel.json` at the repository root:

```json
{
  "$schema": "https://openapi.vercel.sh/vercel.json",
  "services": {
    "web": { "root": "frontend/" },
    "api": { "root": "backend/", "entrypoint": "app.main:app" }
  },
  "rewrites": [
    { "source": "/api/v1/(.*)", "destination": { "service": "api" } },
    { "source": "/(.*)", "destination": { "service": "web" } }
  ],
  "crons": [
    { "path": "/api/v1/jobs/nightly-ingest", "schedule": "0 17 * * *" },
    { "path": "/api/v1/jobs/nightly-brief", "schedule": "0 18 * * *" }
  ]
}
```

Because routing preserves the request path, FastAPI's `/api/v1` prefix and every route in
`routes.py` are unchanged, and the browser stays same-origin.

Changes this forces:

- **Delete the `rewrites()` block** in `frontend/next.config.mjs:21-28`. Top-level service
  routing owns it now; leaving it means the frontend service tries to proxy to
  `127.0.0.1:8000` inside a function. `NEXT_PUBLIC_API_URL` stays empty and
  `frontend/lib/api.ts` is unchanged.
- **Delete `_background_loop` and its `create_task`** in `backend/app/main.py:19-35`.
  `init_db()` stays in the lifespan.
- **Leave the Docker path alone**: `docker-compose.yml`, both Dockerfiles,
  `STANDALONE_OUTPUT`, `instrumentation.ts` and `scripts/dev-backend.mjs` remain the local
  dev route. `instrumentation.ts` already no-ops unless `NODE_ENV=development`.

## 5. Data model

`init_db` uses `create_all` with no Alembic, so new tables appear on the next deploy with
no migration work.

```python
class Briefing(Base):
    __tablename__ = "briefings"
    id: str                       # uuid primary key
    kind: str                     # "daily" | "live"   (indexed)
    generated_at: datetime        # timezone-aware UTC (indexed)
    based_on_ingest_at: datetime | None   # the ingest this document reflects
    payload: dict                 # JSON: the complete BriefingOut document
    llm_status: str | None        # ok | off | misconfigured | empty | rejected | error
    llm_model: str | None
    created_at: datetime

class JobState(Base):
    """Atomic cross-instance claims for scheduled work."""
    __tablename__ = "job_state"
    key: str                      # primary key: "ingest" | "brief"
    claimed_at: datetime | None   # when this instance took ownership
    last_ok_at: datetime | None   # when that run finished successfully
    last_error: str | None
```

**"The newest ingest" is always `job_state(key='ingest').last_ok_at`** — set on a successful
`run_ingest`, and copied into a new brief row as its `based_on_ingest_at`. Both guards and
the 12 h reconciliation test read that one field, never `IngestState.last_ok_at` (which is
per-collector and can disagree mid-run).

`payload` holds the existing `BriefingOut` dict (`backend/app/schemas.py:164-177`) verbatim,
so `GET /api/v1/briefing` returns a stored document of exactly the shape it returns today.
`frontend/lib/types.ts` and the `BriefingPanel` data contract do not change.

Retention: the insert transaction also deletes `briefings` rows older than 30 days.

New settings in `backend/app/core/config.py`:

| Var | Default | Purpose |
|---|---|---|
| `brief_min_rebuild_seconds` | `900` | floor between brief rebuilds, independent of ingest frequency |
| `cron_secret` | `""` | bearer token for `/jobs/*`; unset fails closed |
| `allowed_origins` | `""` | replaces `allow_origins=["*"]`; empty means no cross-origin grants |
| `operator_secret` | `""` | gates `POST /events/{id}/resolve` |

`ingest_interval_seconds` is repurposed: it was the loop's sleep, and becomes the minimum
seconds between real (unclaimed-skipped) ingests. Same name, same 300 default.

## 6. Jobs, guards, request path

New `backend/app/api/jobs.py` for the endpoints and `backend/app/services/brief_store.py`
for the logic, keeping `api/` thin and offloading a 314-line `routes.py`.

| Endpoint | Trigger | Behaviour |
|---|---|---|
| `GET /api/v1/jobs/nightly-ingest` | cron 17:00 UTC | `run_ingest` only. Does not build a brief. **Writes the ingest claim timestamp without checking it** — a scheduled run is never skipped, and by writing the claim it stops concurrent `POST /ingest/run` requests from duplicating the same fetch. |
| `GET /api/v1/jobs/nightly-brief` | cron 18:00 UTC | If newest successful ingest is >12 h old, ingest first. Then build + store `kind="daily"`. |
| `POST /api/v1/ingest/run` | dashboard load | Claim-guarded ingest, then guard-checked brief rebuild (`kind="live"`). |
| `GET /api/v1/briefing` | drawer open | Newest stored row, no computation. |

**Both guards are atomic DB claims**, because serverless runs many instances and cron can
overlap or duplicate:

```sql
UPDATE job_state SET claimed_at = :now
 WHERE key = :key AND (claimed_at IS NULL OR claimed_at < :now - :min_interval)
```

`rowcount == 1` → this instance owns the work. `rowcount == 0` → someone else is already
doing it; return immediately having done nothing. One statement, identical semantics on
Postgres and SQLite.

The brief guard is what converts five dashboard loads into one LLM call. Rebuild requires
all three:

1. the newest brief's `based_on_ingest_at` is older than the newest completed ingest, and
2. at least `brief_min_rebuild_seconds` since the newest brief, and
3. a won `key='brief'` claim.

```
mount ──► POST /ingest/run ──► claim? ──no──► 200 {"skipped":"recent_ingest"}  (~30 ms, no BMKG call)
                 │yes
                 ▼
            run_ingest ──► brief older than ingest, and past the floor? ──no──► 200 summary
                 │yes
                 ▼
        claim('brief') ──► build_briefing (SQL + MAGMA + LLM ≤20 s) ──► store ──► 200
```

Worst case roughly 25 s against a 300 s budget.

**Frontend.** `Dashboard.tsx` fires the on-load ingest without awaiting before first render,
then refreshes the panels when it resolves. The current manual path awaits the POST and then
reloads five data sets (`frontend/components/Dashboard.tsx:186-200`); the automatic version
renders from existing data immediately. The client always asks and the server decides, so no
staleness logic is duplicated in the UI.

Removed from the deployed UI: the **Regenerate** button (`BriefingPanel.tsx:99-101`, wired to
`onRefresh` at `Dashboard.tsx:557`) and the manual **Ingest** trigger (`Dashboard.tsx:389`),
both superseded by automatic behaviour. The drawer gains a kind label plus the existing
generation timestamp, since a stored brief is a dated document: its embedded `escalation`
and `developments` are frozen at build time, while the header posture chip remains live
from `/api/v1/escalation` on its existing 300 s poll.

## 7. Analytics without DuckDB

`analytics.py` mirrors every event into a local file and then runs six `COUNT` / `GROUP BY`
/ `AVG` queries that SQL performs natively. On Vercel the file has nowhere to live but `/tmp`,
and each cold instance would rebuild it.

- Rewrite `_run_snapshot_and_query` as SQLAlchemy aggregations against `events`.
- Return the identical JSON shape; the analytics panel is unchanged.
- Drop `duckdb` from `backend/requirements.txt`, remove `duckdb_path` from config,
  and delete the `DUCKDB_PATH` row from the README configuration table.
- Gitignore `analytics.duckdb` and `bmkgintel.db`.

## 8. LLM configuration correction

`PLACEHOLDER_MODELS` in `backend/app/services/enrichment.py:31` is
`{"", "openrouter/free", "openrouter/auto", "free"}` with the comment "Model IDs that are
placeholders, not real OpenRouter model IDs". That is factually wrong: `openrouter/free` is
a real router that selects free models at random, and `openrouter/auto` is the Auto Router.

- Remove `openrouter/free` and `openrouter/auto` from `PLACEHOLDER_MODELS`, keeping `""` and
  `"free"`. Update the comment and the stale notes in `backend/.env.example`.
- `OPENROUTER_MODEL=openrouter/free` in production.

Accepted consequences, stated so they are not mistaken for a bug later: the model id changes
nightly (which is why `llm_model` is stored per row), and a random free model is more likely
to miss the JSON contract or trip `sanitize_llm_note`'s grounding check, producing
`rejected` or `empty`. The deterministic brief is stored either way, and `llm_status` is
surfaced so a high rejection rate is visible before anyone decides to pin a specific model.

## 9. Security

- `require_cron` dependency compares the `Authorization` header to `Bearer $CRON_SECRET`.
  **If `CRON_SECRET` is unset, respond 401** — a forgotten secret fails loud in the logs
  rather than leaving an open write path.
- `POST /ingest/run` stays unauthenticated because a secret in client JS is not a secret.
  The atomic ingest claim is the actual authorization: at most one real fetch per
  `ingest_interval_seconds` globally.
- `POST /events/{id}/resolve` requires the `operator_secret` header.
- `CORSMiddleware` `allow_origins=["*"]` (`backend/app/main.py:39-44`) becomes the
  `ALLOWED_ORIGINS` list, empty by default. Safe because service routing keeps the browser
  same-origin.
- Cron invocations reach the production deployment only, and do not follow redirects.

**Resolve in the deployed UI (chosen):** the action is hidden on the public dashboard and the
endpoint stays secret-gated for use from a terminal or the local app. The alternative — a
Next.js route handler under `/api/ops/resolve/{id}` that injects the secret server-side via a
service binding — is deferred, not rejected; it is reachable if operator triage in production
becomes a real requirement.

## 10. Failure modes

| Failure | Behaviour |
|---|---|
| BMKG upstream down or rate-limited | `run_ingest` already records `IngestState.last_error` and returns partial summary; job responds 200 with errors listed. The next day's `nightly-brief` reconciliation re-ingests, so a missed run is caught up rather than lost. |
| Cron skipped entirely (best-effort delivery) | Data goes stale; `nightly-brief` re-ingests when the newest success is >12 h old. |
| Cron delivered twice | Ingest claim serialises it, and `Observation.external_id` UNIQUE makes the work idempotent. |
| Process killed between claim and store | Self-heals: the brief is still older than the newest ingest, so the next eligible attempt rebuilds. |
| OpenRouter timeout / refusal / ungrounded output | `maybe_llm_note` never raises; the complete deterministic brief is stored with `llm_status` set. |
| Cold-start `create_all` race | Two instances can both attempt `CREATE TABLE briefings`; `init_db` swallows the already-exists error and proceeds. |
| `CREATE EXTENSION postgis` denied on Neon | Currently aborts startup. Wrap it so `geom` stays genuinely optional, as the code already documents it to be. |
| Neon autosuspended (~5 min idle) | First request of a session pays a resume. Cron has 300 s of headroom; the dashboard pays once. |
| asyncpg against a PgBouncer pooled endpoint | Prepared statements fail. Use Neon's direct endpoint, or set `statement_cache_size=0` in `create_async_engine` connect args. |
| Function exceeds 300 s | Not expected (~25 s worst case), but the ingest and brief claims are separate so a timeout cannot leave the brief permanently stale. |

## 11. Testing

Backend, pytest against SQLite so it runs in existing CI (`.github/workflows/ci.yml`):

- `GET /jobs/*` with missing, wrong, or unset `CRON_SECRET` → 401 in all three cases.
- Second concurrent ingest claim performs zero collector calls and returns `skipped`.
- Brief guard: no rebuild when `based_on_ingest_at` is current; no rebuild inside
  `brief_min_rebuild_seconds` even when stale; exactly one rebuild for five simultaneous
  requests.
- `nightly-brief` ingests first when the newest success is >12 h old, and does not when fresh.
- `GET /briefing` issues no collector or LLM calls (asserted by counters) and returns the
  stored payload unchanged.
- Empty store: `GET /briefing` builds once, stores `kind="live"`, and a second call reads it.
- Insert prunes rows older than 30 days.
- Analytics returns the same top-level keys and values from SQL as the DuckDB path did.
- `is_model_configured("openrouter/free")` is now `True`; `""` and `"free"` remain `False`.
- `resolve` without a matching operator header → 401 (the same fail-closed rule as the cron
  endpoints: an unset `OPERATOR_SECRET` also returns 401, never a permissive fallback).

Frontend: `npm run typecheck`, then browser verification on the deployed preview — drawer
shows the stored brief with kind and generation time, no Regenerate or Ingest controls,
CARTO basemap loads, and the on-load ingest POST does not block first paint.

Local job simulation without Vercel: `curl -H "Authorization: Bearer $CRON_SECRET"
http://localhost:8000/api/v1/jobs/nightly-brief`.

## 12. Deploy gate (ordered, one time)

1. Install the Neon Marketplace integration; take the **direct**, non-pooled connection URL.
2. Set project env vars: `DATABASE_URL`, `OPENROUTER_API_KEY`,
   `OPENROUTER_MODEL=openrouter/free`, `CRON_SECRET` (random, ≥16 chars),
   `ALLOWED_ORIGINS`, `OPERATOR_SECRET`.
3. Preview deploy; confirm both services build and the Python bundle is under 500 MB
   (`excludeFiles` on `tests/`).
4. Confirm `/api/v1/status` from the preview domain reaches the `api` service and the
   dashboard renders from it on one origin.
5. Promote to production.
6. Trigger both job endpoints by hand with the secret header; confirm PostGIS extension
   state, rows in `events`, and one `briefings` row with `llm_status="ok"`.
7. `vercel crons list` shows both entries attached to production.
8. Update the README: replace "Status: local-only", document the Vercel path, and drop the
   stale instruction to configure a production tile URL — `Map.tsx:20` already uses CARTO
   key-free with `demotiles.maplibre.org` only as an error fallback.

**Do not point local `npm run dev` at the production Neon database.** The local ingest loop
and the production crons would race over the same rows. Keep local dev on SQLite or the
compose Postgres.

## 13. Out of scope

- Intraday (hourly) ingestion. Blocked by Hobby's once-per-day cron limit; the upgrade is a
  Pro plan, or Approach B (Vercel Queues) if rebuilds need to decouple from requests.
- Vercel Daemons to preserve the resident loop. Rejected: Beta, production-only (no
  previews), and a 24/7 instance draws Provisioned Memory every hour it runs, exceeding
  Hobby's included quotas.
- Authenticated operator UI.
- A "past briefs" history view. Rows are retained for 30 days, but no UI is built for them now.
- Next.js 14.2.5 upgrade, and PostGIS spatial-query adoption beyond the optional `geom` column.

## 14. Decisions log

Freshness, topology, LLM, database, brief lifecycle, analytics, exposure, and execution
model were each chosen explicitly in conversation on 2026-11-02. The execution model
(§6, "Approach A") replaced an earlier assumption in this same design that the rebuild could
ride an after-response `waitUntil`; Vercel's FastAPI guidance does not support that for
Python, so the work happens inside the invoking function.
