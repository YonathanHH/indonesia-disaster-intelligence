# Vercel Deployment + Scheduled Executive Digest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy bmkgintel to Vercel as two services in one project, and replace the user-triggered executive brief with a persisted artifact produced by nightly crons plus a guarded rebuild on every new ingest.

**Architecture:** One Vercel project, two Vercel Services (`frontend/` Next.js + `backend/` FastAPI-as-ASGI), top-level rewrites keep the browser same-origin, and `vercel.json` crons fire `GET /api/v1/jobs/*` at 17:00 and 18:00 UTC. Briefings are stored in a new `briefings` table; `GET /briefing` becomes a single indexed read. Concurrency is handled with atomic `UPDATE ... WHERE claimed_at < cutoff` claims in a `job_state` table, which also serves as the rate limit for the unauthenticated on-load ingest.

**Tech Stack:** Python 3.12, FastAPI 0.116, SQLAlchemy 2 async (SQLite for tests, Neon Postgres+PostGIS for prod), pytest with `asyncio_mode=auto`; Next.js 14.2.5 App Router, React 18, MapLibre GL; Vercel Services (Beta) + Vercel Cron Jobs.

**Spec:** `docs/superpowers/specs/2026-11-02-vercel-deploy-scheduled-digest-design.md` (commit `18c0932`). Read the spec alongside this plan; the spec argues the tradeoffs, this plan lists the edits.

## Global Constraints

Every task's requirements implicitly include this section.

- **Every timestamp written to the database is UTC.** Use `datetime.now(timezone.utc)`. SQLite's `DateTime(timezone=True)` stores wall-clock only, so a non-UTC value silently corrupts interval math. Read back through the `_aware()` helper already used in `services/analytics.py:24` and `services/briefing.py`.
- **Vercel cron jobs issue HTTP GET, never POST.** A job endpoint declared `@router.post` returns 405 and never runs.
- **Cron schedules are UTC and, on Hobby, at most once per day** with per-hour (±59 min) precision. `0 17 * * *` = 00:00 WIB; `0 18 * * *` = 01:00 WIB.
- **Fail closed on secrets.** A missing `CRON_SECRET` or `OPERATOR_SECRET` returns 401; it never degrades into permissive access.
- **`Briefing.payload` is the `BriefingOut` dict verbatim.** Do not reshape it — that property is what keeps `frontend/lib/types.ts` and `BriefingPanel` untouched apart from the two UI removals in Task 10.
- **No local filesystem writes** anywhere in backend code. No `duckdb`, no `.db` files in prod paths.
- **`Observation.external_id` stays UNIQUE** and is the idempotency anchor that makes duplicate cron delivery safe.
- **Tests run from `backend/`:** `python -m pytest -q` (`pytest.ini` sets `asyncio_mode = auto`, `testpaths = tests`). Service-level tests use the `session` fixture in `backend/tests/conftest.py` (in-memory SQLite). HTTP-level tests use `fastapi.testclient.TestClient(app, raise_server_exceptions=False)`. There is no async HTTP test harness in this repo — do not invent one; test DB-touching logic at the service layer.
- **Frontend verification is `npm run typecheck` + `npm run build`** (CI, `frontend/`, node 20). No frontend test runner exists.

## File Structure

Created:
- `backend/app/services/job_state.py` — atomic cross-instance claims; the only place that touches `job_state`.
- `backend/app/services/brief_store.py` — persist/read/prune/guard the brief document; the only place that touches `briefings`.
- `backend/app/api/jobs.py` — the two cron endpoints plus the `require_cron` / `require_operator` dependencies.
- `backend/tests/test_job_state.py`, `backend/tests/test_brief_store.py`, `backend/tests/test_jobs.py`, `backend/tests/test_ingest_guard.py`

Modified:
- `backend/app/models.py` — add `Briefing`, `JobState`.
- `backend/app/core/config.py` — add `brief_min_rebuild_seconds`, `cron_secret`, `allowed_origins`, `operator_secret`, `cors_origins`.
- `backend/app/core/db.py` — tolerate the `create_all` race and a denied `CREATE EXTENSION postgis`; Neon prepared-statement safety.
- `backend/app/schemas.py` — `BriefingOut.kind`.
- `backend/app/services/enrichment.py:31` — `PLACEHOLDER_MODELS` correction.
- `backend/app/services/analytics.py` — SQL aggregations, no DuckDB.
- `backend/app/api/routes.py` — `GET /briefing` reads the store; `POST /ingest/run` claims + rebuilds; `resolve` gated; `status` reports last brief.
- `backend/app/main.py` — delete `_background_loop`; CORS from settings; mount the jobs router.
- `backend/requirements.txt`, `backend/.env.example`, `.gitignore`
- `frontend/next.config.mjs` — delete the `rewrites()` block.
- `frontend/lib/types.ts`, `frontend/lib/api.ts`, `frontend/components/Dashboard.tsx`, `frontend/components/TopBar.tsx`, `frontend/components/BriefingPanel.tsx`
- `README.md`
- `vercel.json` (new, repo root)

Tests for the two removed UI controls live in `npm run typecheck` (deleting a prop from a typed component fails the build if a caller still passes it), not in a JS test runner.

---

### Task 1: Briefing and JobState tables + new settings

**Files:**
- Modify: `backend/app/models.py` (append after `IngestState`, which ends at line 89)
- Modify: `backend/app/core/config.py:5-23`
- Modify: `backend/.env.example`
- Test: `backend/tests/test_brief_store.py` (created here, extended in Task 3)

**Interfaces:**
- Produces: `app.models.Briefing` with columns `id, kind, generated_at, based_on_ingest_at, payload, llm_status, llm_model, created_at`; `app.models.JobState` with `key, claimed_at, last_ok_at, last_error`; `app.core.config.settings.brief_min_rebuild_seconds: int`, `.cron_secret: str`, `.allowed_origins: str`, `.operator_secret: str`, `.cors_origins -> list[str]`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_brief_store.py`:

```python
from datetime import datetime, timezone

from app.core.config import settings
from app.models import Briefing, JobState


async def test_new_tables_exist(session):
    session.add(JobState(key="ingest"))
    session.add(
        Briefing(
            kind="daily",
            generated_at=datetime.now(timezone.utc),
            based_on_ingest_at=None,
            payload={"headline": "x"},
            llm_status="ok",
            llm_model="openrouter/free",
            created_at=datetime.now(timezone.utc),
        )
    )
    await session.commit()
    assert isinstance((await session.get(Briefing, 1) is None) or True, bool)


def test_new_settings_defaults():
    assert settings.brief_min_rebuild_seconds == 900
    assert settings.cron_secret == ""
    assert settings.allowed_origins == ""
    assert settings.operator_secret == ""
    assert settings.cors_origins == []
```

Note: `Briefing.id` is a uuid string primary key, so do not fetch by integer. Replace the weak `assert` line above with a real check before committing:

```python
    row = (await session.execute(select(Briefing))).scalar_one()
    assert row.payload == {"headline": "x"}
    assert row.kind == "daily"
```

and add `from sqlalchemy import select` at the top. (This correction is part of Step 3's implementation check — the final test must assert on real content, not a tautology.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_brief_store.py -q`
Expected: FAIL — `ImportError: cannot import name 'Briefing'`.

- [ ] **Step 3: Add the models**

Append to `backend/app/models.py`:

```python
class Briefing(Base):
    """A stored executive brief. `payload` is the complete BriefingOut document,
    so the read path never recomputes and the client contract is unchanged."""

    __tablename__ = "briefings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    kind: Mapped[str] = mapped_column(String(16), index=True)  # daily | live
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    # The ingest this document reflects: job_state(key='ingest').last_ok_at at build
    # time. NULL means "built with no recorded ingest", which always looks stale.
    based_on_ingest_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    payload: Mapped[dict] = mapped_column(JSON)
    llm_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    llm_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )


class JobState(Base):
    """One row per scheduled key, used as an atomic cross-instance claim.

    Serverless runs many instances and Vercel can deliver the same cron run twice,
    so `try_claim` is a conditional UPDATE: the instance whose statement reports
    rowcount == 1 owns the work. `claimed_at` gates the interval; `last_ok_at` is
    the reference every freshness comparison reads.
    """

    __tablename__ = "job_state"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)  # ingest | brief
    claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_ok_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
```

- [ ] **Step 4: Add the settings**

In `backend/app/core/config.py`, insert after `ingest_interval_seconds: int = 300` (line 9) and before the OpenRouter block:

```python
    # Floor between brief rebuilds, independent of how often ingest runs.
    brief_min_rebuild_seconds: int = 900
    # Vercel sends CRON_SECRET as `Authorization: Bearer <value>` on cron hits.
    # Unset = every job call is rejected (fail closed), not "allow everyone".
    cron_secret: str = ""
    operator_secret: str = ""
    # Comma-separated exact origins. Empty means no cross-origin grants, which is
    # correct because Vercel service routing keeps the browser same-origin.
    allowed_origins: str = ""
```

Add the property next to `is_postgres` (line 25-27):

```python
    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]
```

- [ ] **Step 5: Document the new vars**

Append to `backend/.env.example`:

```
# --- scheduled jobs (Vercel) ---
# Vercel Cron sends this as `Authorization: Bearer <value>`; generate a random
# string of 16+ chars. Jobs return 401 when it is unset.
CRON_SECRET=
# Gates mutating endpoints (POST /events/{id}/resolve). Not used by the public UI.
OPERATOR_SECRET=
# Comma-separated browser origins allowed cross-origin access. Leave empty when
# the dashboard and API share one origin (the Vercel Services default).
ALLOWED_ORIGINS=
# Minimum seconds between two executive-brief rebuilds.
BRIEF_MIN_REBUILD_SECONDS=900
```

Also change the `OPENROUTER_MODEL` line's comment: it currently calls `openrouter/free` a default that must be overridden; Task 4 makes it a legitimate value, so update the wording here in the same commit to avoid a doc that contradicts the code.

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_brief_store.py -q`
Expected: PASS (2 tests).

Run: `cd backend && python -m pytest -q`
Expected: PASS — existing suite unaffected (new tables are additive; `conftest.py` creates all tables via `Base.metadata.create_all`).

- [ ] **Step 7: Commit**

```bash
git add backend/app/models.py backend/app/core/config.py backend/.env.example backend/tests/test_brief_store.py
git commit -m "feat: add briefings and job_state tables with scheduling settings"
```

---

### Task 2: Atomic claim primitive

**Files:**
- Create: `backend/app/services/job_state.py`
- Test: `backend/tests/test_job_state.py`

**Interfaces:**
- Consumes: `app.models.JobState` (Task 1).
- Produces:
  - `async def try_claim(session, key: str, min_interval_seconds: int, *, force: bool = False) -> bool` — True when this instance now owns the work.
  - `async def mark_done(session, key: str, *, error: str | None = None) -> None` — stamps `last_ok_at` (UTC now) and `last_error`.
  - `async def last_ok(session, key: str) -> datetime | None` — tz-aware UTC or None.
  - `KEY_INGEST = "ingest"`, `KEY_BRIEF = "brief"`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_job_state.py`:

```python
from datetime import datetime, timedelta, timezone

from app.models import JobState
from app.services import job_state


async def test_first_claim_wins_second_loses(session):
    assert await job_state.try_claim(session, "ingest", 300) is True
    await session.commit()
    assert await job_state.try_claim(session, "ingest", 300) is False


async def test_claim_expires_after_interval(session):
    assert await job_state.try_claim(session, "ingest", 300) is True
    await session.execute(
        JobState.__table__.update()
        .where(JobState.key == "ingest")
        .values(claimed_at=datetime.now(timezone.utc) - timedelta(seconds=301))
    )
    assert await job_state.try_claim(session, "ingest", 300) is True


async def test_force_writes_without_checking_and_blocks_others(session):
    # A scheduled run must never be skipped, but stamping the claim still stops
    # concurrent on-load requests from duplicating the same BMKG fetch.
    assert await job_state.try_claim(session, "ingest", 300, force=True) is True
    assert await job_state.try_claim(session, "ingest", 300) is False


async def test_mark_done_sets_last_ok_and_last_error(session):
    await job_state.try_claim(session, "ingest", 300)
    await job_state.mark_done(session, "ingest")
    await session.commit()
    ok = await job_state.last_ok(session, "ingest")
    assert ok is not None and ok.tzinfo is not None

    await job_state.mark_done(session, "brief", error="openrouter timeout")
    await session.commit()
    row = await session.get(JobState, "brief")
    assert row.last_error == "openrouter timeout"
    assert row.last_ok_at is None


async def test_last_ok_missing_row_returns_none(session):
    assert await job_state.last_ok(session, "nope") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_job_state.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.job_state'`.

- [ ] **Step 3: Implement**

Create `backend/app/services/job_state.py`:

```python
"""Atomic cross-instance claims for scheduled work.

Serverless gives us many instances, no shared memory, and Vercel cron that can
overlap or deliver the same run twice. So the lock is one conditional UPDATE:
whoever moves `claimed_at` owns the work, everybody else does nothing.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError

from app.models import JobState

KEY_INGEST = "ingest"
KEY_BRIEF = "brief"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def _ensure_row(session, key: str) -> None:
    """Create the claim row if absent. Savepoint keeps a duplicate-key insert
    from poisoning the caller's transaction on both SQLite and Postgres."""
    try:
        async with session.begin_nested():
            session.add(JobState(key=key))
    except IntegrityError:
        pass


async def try_claim(session, key: str, min_interval_seconds: int, *, force: bool = False) -> bool:
    """Take ownership of `key`. False means someone else is already working.

    `force=True` skips the interval check — for scheduled runs that must not be
    skipped by an earlier user-triggered fetch — but still stamps `claimed_at`.
    """
    now = _utcnow()
    await _ensure_row(session, key)
    stmt = update(JobState).where(JobState.key == key)
    if not force:
        cutoff = now - timedelta(seconds=min_interval_seconds)
        stmt = stmt.where(or_(JobState.claimed_at.is_(None), JobState.claimed_at < cutoff))
    res = await session.execute(stmt.values(claimed_at=now))
    return res.rowcount == 1


async def mark_done(session, key: str, *, error: str | None = None) -> None:
    await _ensure_row(session, key)
    if error:
        await session.execute(
            update(JobState).where(JobState.key == key).values(last_error=error[:500])
        )
    else:
        await session.execute(
            update(JobState)
            .where(JobState.key == key)
            .values(last_ok_at=_utcnow(), last_error=None)
        )


async def last_ok(session, key: str) -> datetime | None:
    row = (
        await session.execute(select(JobState).where(JobState.key == key))
    ).scalar_one_or_none()
    return _aware(row.last_ok_at) if row else None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_job_state.py -q`
Expected: PASS (5 tests).

If `test_first_claim_wins_second_loses` fails with the second call returning `True`, the cause is autocommit isolation — add `await session.commit()` after the first `try_claim` inside the test is already there; if it still fails, verify `_ensure_row`'s savepoint is flushing (add `await session.flush()` before the `async with` exit is not needed — `begin_nested` flushes on exit).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/job_state.py backend/tests/test_job_state.py
git commit -m "feat: add atomic job claim primitive for scheduled work"
```

---

### Task 3: Brief store — persist, read, prune, and the rebuild guard

**Files:**
- Create: `backend/app/services/brief_store.py`
- Test: `backend/tests/test_brief_store.py` (extend the file started in Task 1)

**Interfaces:**
- Consumes: `app.models.Briefing` (Task 1), `job_state.last_ok` (Task 2), `app.services.briefing.build_briefing(session) -> dict` (existing, unchanged).
- Produces:
  - `MAX_AGE_DAYS = 30`
  - `async def newest(session, *, kind: str | None = None) -> Briefing | None`
  - `async def store(session, payload: dict, *, kind: str, based_on_ingest_at: datetime | None, llm_status: str | None, llm_model: str | None) -> Briefing`
  - `def rebuild_needed(newest: Briefing | None, ingest_ok_at: datetime | None, *, floor_seconds: int, now: datetime) -> bool` — pure, no I/O
  - `async def build_and_store(session, kind: str) -> Briefing`
  - `async def current_document(session) -> dict | None` — the payload dict with `kind` merged in, for the read path

- [ ] **Step 1: Write the failing tests for the pure guard**

Append to `backend/tests/test_brief_store.py`:

```python
from datetime import datetime, timedelta, timezone

from app.services import brief_store

T0 = datetime(2026, 11, 2, 18, 0, tzinfo=timezone.utc)


def _brief(age_min=0, based_on=T0):
    b = brief_store.Briefing.__new__(brief_store.Briefing)
    b.generated_at = T0 - timedelta(minutes=age_min)
    b.based_on_ingest_at = based_on
    return b


def test_no_brief_needs_rebuild():
    assert brief_store.rebuild_needed(None, T0, floor_seconds=900, now=T0) is True


def test_current_brief_needs_no_rebuild():
    assert brief_store.rebuild_needed(_brief(), T0, floor_seconds=900, now=T0) is False


def test_stale_brief_needs_rebuild():
    b = _brief(based_on=T0 - timedelta(hours=1))
    assert brief_store.rebuild_needed(b, T0, floor_seconds=900, now=T0 + timedelta(hours=2)) is True


def test_floor_blocks_even_when_stale():
    # Five dashboard loads in one minute must not mean five LLM calls.
    b = _brief(based_on=T0 - timedelta(hours=1))
    assert brief_store.rebuild_needed(b, T0, floor_seconds=900, now=T0 + timedelta(minutes=10)) is False


def test_brief_with_no_ingest_reference_always_looks_stale():
    b = _brief(age_min=120, based_on=None)
    assert brief_store.rebuild_needed(b, T0, floor_seconds=900, now=T0 + timedelta(hours=1)) is True


def test_no_ingest_recorded_means_nothing_to_reflect():
    assert brief_store.rebuild_needed(_brief(), None, floor_seconds=900, now=T0) is False
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend && python -m pytest tests/test_brief_store.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.brief_store'`.

- [ ] **Step 3: Implement the store and guard**

Create `backend/app/services/brief_store.py`:

```python
"""Persistence + rebuild policy for the executive brief.

Two-layer design carried over from services/briefing.py: the deterministic core
is a function of stored data, and the LLM note is an optional gloss. This module
decides *when* to rebuild and *where* the document lives; briefing.py still
decides what the document says.
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, desc, select

from app.models import Briefing
from app.services import briefing as briefing_svc
from app.services import job_state

log = logging.getLogger(__name__)

MAX_AGE_DAYS = 30


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def newest(session, *, kind: str | None = None) -> Briefing | None:
    stmt = select(Briefing)
    if kind:
        stmt = stmt.where(Briefing.kind == kind)
    stmt = stmt.order_by(desc(Briefing.generated_at)).limit(1)
    return (await session.execute(stmt)).scalar_one_or_none()


def rebuild_needed(
    newest: Briefing | None,
    ingest_ok_at: datetime | None,
    *,
    floor_seconds: int,
    now: datetime,
) -> bool:
    """Should we spend an LLM call on a fresher brief?

    The three-way rule from the spec: a brief is current when it already reflects
    the newest successful ingest, and it is rate-limited by `floor_seconds` even
    when it is stale.
    """
    if newest is None:
        return True                      # nothing stored yet
    if ingest_ok_at is None:
        return False                     # nothing new to reflect
    gen = _aware(newest.generated_at)
    if now - gen < timedelta(seconds=floor_seconds):
        return False
    based = _aware(newest.based_on_ingest_at)
    if based is None:
        return True                      # cannot prove freshness
    return based < _aware(ingest_ok_at)


async def store(
    session,
    payload: dict,
    *,
    kind: str,
    based_on_ingest_at: datetime | None,
    llm_status: str | None,
    llm_model: str | None,
) -> Briefing:
    now = datetime.now(timezone.utc)
    row = Briefing(
        kind=kind,
        generated_at=now,
        based_on_ingest_at=based_on_ingest_at,
        payload=payload,
        llm_status=llm_status,
        llm_model=llm_model,
        created_at=now,
    )
    session.add(row)
    # Bounds a row-per-rebuild table without a second scheduled job.
    await session.execute(
        delete(Briefing).where(Briefing.generated_at < now - timedelta(days=MAX_AGE_DAYS))
    )
    await session.commit()
    return row


async def build_and_store(session, kind: str) -> Briefing:
    payload = await briefing_svc.build_briefing(session)
    return await store(
        session,
        payload,
        kind=kind,
        based_on_ingest_at=await job_state.last_ok(session, job_state.KEY_INGEST),
        llm_status=payload.get("llm_status"),
        llm_model=payload.get("llm_model"),
    )


async def current_document(session) -> dict | None:
    row = await newest(session)
    if row is None:
        return None
    return {**row.payload, "kind": row.kind}
```

`rebuild_needed`'s parameter is deliberately named `newest` to shadow nothing — it takes a `Briefing | None`. Keep the signature exactly as written; Task 8 calls it positionally with those three keyword args.

- [ ] **Step 4: Run the pure tests**

Run: `cd backend && python -m pytest tests/test_brief_store.py -q -k "rebuild or stale or floor or ingests or brief_with"`
Expected: PASS.

- [ ] **Step 5: Write and run the store/read tests**

Append to `backend/tests/test_brief_store.py`:

```python
async def test_store_then_read_newest(session):
    now = datetime.now(timezone.utc)
    await brief_store.store(
        session, {"headline": "old", "generated_at": now.isoformat()},
        kind="daily", based_on_ingest_at=None, llm_status="ok", llm_model="m",
    )
    await brief_store.store(
        session, {"headline": "new", "generated_at": now.isoformat()},
        kind="live", based_on_ingest_at=now, llm_status=None, llm_model=None,
    )
    doc = await brief_store.current_document(session)
    assert doc["headline"] == "new" and doc["kind"] == "live"
    daily = await brief_store.newest(session, kind="daily")
    assert daily.payload["headline"] == "old"


async def test_store_prunes_old_rows(session):
    from app.models import Briefing

    old = Briefing(
        kind="daily",
        generated_at=datetime.now(timezone.utc) - timedelta(days=31),
        based_on_ingest_at=None,
        payload={"headline": "ancient"},
        created_at=datetime.now(timezone.utc),
    )
    session.add(old)
    await session.commit()
    await brief_store.store(
        session, {"headline": "fresh"}, kind="live",
        based_on_ingest_at=None, llm_status=None, llm_model=None,
    )
    remaining = (await session.execute(select(Briefing))).scalars().all()
    assert [b.payload["headline"] for b in remaining] == ["fresh"]


async def test_build_and_store_uses_ingest_time_as_reference(session):
    # build_briefing does live upstream calls; stub it, as the API tests already do
    # for collectors elsewhere in the suite.
    async def fake_build(_session):
        return {"headline": "h", "generated_at": "x", "llm_status": "ok", "llm_model": "openrouter/free"}

    orig = brief_store.briefing_svc.build_briefing
    brief_store.briefing_svc.build_briefing = fake_build
    try:
        await job_state.try_claim(session, job_state.KEY_INGEST, 300)
        await job_state.mark_done(session, job_state.KEY_INGEST)
        await session.commit()
        row = await brief_store.build_and_store(session, "daily")
        assert row.kind == "daily" and row.llm_status == "ok"
        assert row.based_on_ingest_at == await job_state.last_ok(session, job_state.KEY_INGEST)
    finally:
        brief_store.briefing_svc.build_briefing = orig
```

Add to the imports at the top of the file: `from app.services import job_state`.

Run: `cd backend && python -m pytest tests/test_brief_store.py -q`
Expected: PASS (all tests in the file).

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/brief_store.py backend/tests/test_brief_store.py
git commit -m "feat: persist executive briefs with a rate-limited rebuild guard"
```

---

### Task 4: Make `openrouter/free` a legitimate model id

**Files:**
- Modify: `backend/app/services/enrichment.py:30-31`
- Modify: `backend/app/services/briefing.py:335-336` (the `misconfigured` caveat wording)
- Test: `backend/tests/test_enrichment.py` (existing file — append)

**Interfaces:**
- Consumes: nothing new.
- Produces: `enrichment.PLACEHOLDER_MODELS == {"", "free"}`; `is_model_configured("openrouter/free")` is `True`.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_enrichment.py`:

```python
def test_openrouter_routers_are_real_model_ids():
    # openrouter/free selects among free models at random; openrouter/auto is the
    # Auto Router. Both are routable, so neither may be treated as unset.
    from app.services import enrichment

    assert enrichment.is_model_configured("openrouter/free") is True
    assert enrichment.is_model_configured("openrouter/auto") is True
    assert enrichment.is_model_configured("z-ai/glm-5.2:free") is True


def test_true_placeholders_still_rejected():
    from app.services import enrichment

    assert enrichment.is_model_configured("") is False
    assert enrichment.is_model_configured("free") is False
    assert enrichment.is_model_configured(None) is False
    assert enrichment.is_model_configured("  ") is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && python -m pytest tests/test_enrichment.py -q -k "openrouter_routers"`
Expected: FAIL — `assert False is True`.

- [ ] **Step 3: Fix the set and its comment**

In `backend/app/services/enrichment.py`, replace lines 30-31:

```python
# Model IDs that are placeholders, not real OpenRouter model IDs.
PLACEHOLDER_MODELS = {"", "openrouter/free", "openrouter/auto", "free"}
```

with:

```python
# Values that mean "operator has not chosen a model". `openrouter/free` (routes
# among free models at random) and `openrouter/auto` (the Auto Router) are real,
# routable IDs and must NOT be listed here.
PLACEHOLDER_MODELS = {"", "free"}
```

`is_model_configured` (line 286) already does `model.strip() not in PLACEHOLDER_MODELS`, so the `None` and whitespace cases keep working unchanged.

- [ ] **Step 4: Correct the now-wrong caveat text**

In `backend/app/services/briefing.py:335-336`, the message tells operators to set "a real model id" — which implied `openrouter/free` was not real. Replace:

```python
            if llm_status == "misconfigured":
                caveats.append("AI note unavailable: OPENROUTER_MODEL is not set to a real model id.")
```

with:

```python
            if llm_status == "misconfigured":
                caveats.append(
                    "AI note unavailable: OPENROUTER_MODEL is empty or a placeholder. "
                    "Set it to a model id, or use openrouter/free for the free router."
                )
```

- [ ] **Step 5: Run the full backend suite**

Run: `cd backend && python -m pytest -q`
Expected: PASS. If `test_enrichment.py` has an existing assertion that `openrouter/free` is misconfigured, update that assertion — it encoded the wrong assumption, and the spec §8 overrides it.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/enrichment.py backend/app/services/briefing.py backend/tests/test_enrichment.py
git commit -m "fix: treat OpenRouter free and auto routers as real model ids"
```

---

### Task 5: Analytics without DuckDB

**Files:**
- Modify: `backend/app/services/analytics.py` (full rewrite of the aggregation path)
- Modify: `backend/app/api/routes.py:282-291` (drop the `duckdb_path` coupling), `backend/app/core/config.py:21` (remove `duckdb_path`)
- Modify: `backend/requirements.txt` (delete `duckdb==1.2.2`), `.gitignore`
- Test: `backend/tests/test_analytics.py` (rewrite)

**Interfaces:**
- Consumes: `app.models.Event`, `app.models.Observation`.
- Produces: `async def get_analytics(session, refresh: bool = True) -> dict` with the same keys as today: `generated_at, total_events, by_type, by_priority, quakes_24h, avg_magnitude_7d, top_regions, daily_counts_14d, observations`.

- [ ] **Step 1: Rewrite the test first**

Replace `backend/tests/test_analytics.py` entirely (the current test passes `duckdb_path`, which no longer exists):

```python
from datetime import datetime, timedelta, timezone

from app.models import Event, Observation
from app.services import analytics as analytics_svc


async def _mk(session, **kw):
    now = datetime.now(timezone.utc)
    base = dict(type="earthquake", title="M5 — Test", occurred_at=now,
                latitude=-7.0, longitude=110.0, depth_km=10.0, magnitude=5.0,
                priority="HIGH", score=7.0, status="active", extra={"region": "Java"})
    base.update(kw)
    e = Event(**base)
    session.add(e)
    await session.flush()
    return e


async def test_analytics_aggregates_in_sql(session):
    now = datetime.now(timezone.utc)
    await _mk(session, magnitude=5.0, priority="HIGH", extra={"region": "Java"})
    await _mk(session, magnitude=6.0, priority="CRITICAL", extra={"region": "Java"},
              occurred_at=now - timedelta(days=2))
    await _mk(session, type="severe_weather", title="Storm", magnitude=None,
              priority="MODERATE", extra={"region": "Sumatra"})
    session.add(Observation(kind="bmkg_m5", source="bmkg", external_id="obs-1",
                            observed_at=now))
    await session.commit()

    out = await analytics_svc.get_analytics(session, refresh=True)
    assert out["total_events"] == 3
    assert out["by_type"] == {"earthquake": 2, "severe_weather": 1}
    assert out["by_priority"]["HIGH"] == 1
    assert out["quakes_24h"] == 1                  # the 2-day-old one is outside 24h
    assert out["avg_magnitude_7d"] == 5.5          # the weather row has magnitude NULL
    assert out["top_regions"][0] == {"region": "Java", "count": 2}
    assert out["observations"] == 1
    assert len(out["daily_counts_14d"]) == 2
    assert all(set(d) == {"day", "count"} for d in out["daily_counts_14d"])


async def test_analytics_without_refresh_skips_observation_count(session):
    now = datetime.now(timezone.utc)
    await _mk(session)
    session.add(Observation(kind="bmkg_m5", source="bmkg", external_id="obs-2",
                            observed_at=now))
    await session.commit()
    out = await analytics_svc.get_analytics(session, refresh=False)
    assert out["total_events"] == 1
    assert out["observations"] == 0      # preserved behaviour: counted only on refresh


async def test_analytics_empty_db(session):
    out = await analytics_svc.get_analytics(session, refresh=True)
    assert out["total_events"] == 0
    assert out["by_type"] == {} and out["by_priority"] == {}
    assert out["avg_magnitude_7d"] is None
    assert out["top_regions"] == [] and out["daily_counts_14d"] == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && python -m pytest tests/test_analytics.py -q`
Expected: FAIL — `TypeError: get_analytics() got an unexpected keyword argument` is *not* expected here (the new calls omit `duckdb_path`); expect the DuckDB file-write/`avg_magnitude_7d` assertions to fail first.

- [ ] **Step 3: Rewrite the service**

Replace the body of `backend/app/services/analytics.py` (keep `_aware`, delete `_run_snapshot_and_query`, `_event_rows`, and the `asyncio.to_thread` call):

```python
"""Analytics aggregations over the primary store.

Formerly mirrored every event into a local DuckDB file. That bought nothing —
the six aggregations are native SQL, and the file needs a writable disk, which
serverless does not give us. `top_regions` still reads `extra` in Python
because portable JSON-path SQL differs between SQLite and Postgres and the row
count is small by design (BMKG feeds, not a history warehouse).
"""
import logging
from collections import Counter
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.models import Event, Observation

log = logging.getLogger(__name__)

QUAKE_TYPES = ("earthquake", "tsunami_alert")


def _aware(dt: datetime) -> datetime:
    return dt if dt is not None and dt.tzinfo else (dt.replace(tzinfo=timezone.utc) if dt else dt)


async def get_analytics(session, refresh: bool = True) -> dict:
    now = datetime.now(timezone.utc)
    day_ago, week_ago, fortnight_ago = (
        now - timedelta(hours=24),
        now - timedelta(days=7),
        now - timedelta(days=14),
    )

    async def scalar(stmt) -> int:
        return (await session.execute(stmt)).scalar() or 0

    total = await scalar(select(func.count()).select_from(Event))
    by_type = {
        t: c
        for t, c in (
            await session.execute(select(Event.type, func.count()).group_by(Event.type))
        ).all()
    }
    by_priority = {
        p: c
        for p, c in (
            await session.execute(select(Event.priority, func.count()).group_by(Event.priority))
        ).all()
    }
    quakes_24h = await scalar(
        select(func.count())
        .select_from(Event)
        .where(Event.type.in_(QUAKE_TYPES), Event.occurred_at >= day_ago)
    )
    avg_raw = (
        await session.execute(
            select(func.avg(Event.magnitude)).where(
                Event.magnitude.is_not(None), Event.occurred_at >= week_ago
            )
        )
    ).scalar()
    daily = [
        {"day": str(d), "count": c}
        for d, c in (
            await session.execute(
                select(func.date(Event.occurred_at), func.count())
                .where(Event.occurred_at >= fortnight_ago)
                .group_by(func.date(Event.occurred_at))
                .order_by(func.date(Event.occurred_at))
            )
        ).all()
    ]
    extra_rows = (await session.execute(select(Event.extra))).scalars().all()
    top = Counter((r or {}).get("region") or "Unknown" for r in extra_rows).most_common(10)
    observations = await scalar(select(func.count()).select_from(Observation)) if refresh else 0

    return {
        "generated_at": now.isoformat(),
        "total_events": total,
        "by_type": by_type,
        "by_priority": by_priority,
        "quakes_24h": quakes_24h,
        "avg_magnitude_7d": float(avg_raw) if avg_raw is not None else None,
        "top_regions": [{"region": r, "count": c} for r, c in top],
        "daily_counts_14d": daily,
        "observations": observations,
    }
```

- [ ] **Step 4: Update the route and config**

In `backend/app/api/routes.py:282-291`, the handler already calls `analytics_svc.get_analytics(session, refresh=refresh)` — no change needed there. Remove `duckdb_path: str = "./analytics.duckdb"` from `backend/app/core/config.py:21` and its README row.

In `backend/requirements.txt`, delete the `duckdb==1.2.2` line (and the duplicated bare `httpx` on line 12 — it appears at line 8 already).

- [ ] **Step 5: Run the suite**

Run: `cd backend && python -m pytest -q`
Expected: PASS. Then confirm nothing still imports duckdb:
Run: `cd backend && grep -rn "duckdb" app/ tests/ requirements.txt || echo "clean"`
Expected: `clean`.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/analytics.py backend/app/core/config.py backend/requirements.txt backend/tests/test_analytics.py .gitignore
git commit -m "refactor: compute analytics with SQL aggregations, drop DuckDB sidecar"
```

---

### Task 5b: Remove the local-file artifacts from the repo contract

**Files:**
- Modify: `.gitignore`
- Delete: `backend/analytics.duckdb`, `backend/bmkgintel.db` (local state, not source)

- [ ] **Step 1: Add ignore rules**

Append to `.gitignore`:

```
# local state — never deployed (Vercel filesystems are ephemeral)
backend/*.db
backend/*.duckdb
```

- [ ] **Step 2: Untrack and remove the working copies**

```bash
git rm --cached backend/analytics.duckdb backend/bmkgintel.db 2>/dev/null || true
git status --short
```
Expected: only the two staged deletions plus `.gitignore`. If either file was never tracked, `git rm --cached` reports a pathspec error and the `|| true` absorbs it — verify with `git status --short` before committing.

- [ ] **Step 3: Commit**

```bash
git commit -m "chore: stop tracking local sqlite and duckdb state files"
```

---

### Task 6: Jobs API skeleton and cron authentication

**Files:**
- Create: `backend/app/api/jobs.py`
- Modify: `backend/app/main.py` (mount the router, CORS from settings)
- Modify: `backend/app/schemas.py:164-177` (`BriefingOut.kind`)
- Test: `backend/tests/test_jobs.py`

**Interfaces:**
- Consumes: `settings.cron_secret`, `settings.operator_secret` (Task 1).
- Produces: `jobs.router`; `jobs.require_cron` and `jobs.require_operator` as FastAPI dependencies; `jobs.cron_protected(...)` behaviour reused by Task 7.

- [ ] **Step 1: Write the failing auth tests**

Create `backend/tests/test_jobs.py`:

```python
from fastapi.testclient import TestClient

from app.main import app


def _client():
    return TestClient(app, raise_server_exceptions=False)


def test_nightly_ingest_requires_secret(monkeypatch):
    monkeypatch.setattr("app.core.config.settings.cron_secret", "s3cret-value-1234")
    c = _client()
    assert c.get("/api/v1/jobs/nightly-ingest").status_code == 401
    assert c.get("/api/v1/jobs/nightly-ingest", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert c.get("/api/v1/jobs/nightly-ingest", headers={"Authorization": "s3cret-value-1234"}).status_code == 401


def test_jobs_fail_closed_when_secret_unset(monkeypatch):
    # A forgotten env var must not become an open write path on a public domain.
    monkeypatch.setattr("app.core.config.settings.cron_secret", "")
    c = _client()
    assert c.get("/api/v1/jobs/nightly-ingest").status_code == 401


def test_cron_endpoints_are_get_only(monkeypatch):
    # Vercel cron issues GET; POST must not be the verb that works.
    monkeypatch.setattr("app.core.config.settings.cron_secret", "x")
    c = _client()
    assert c.post("/api/v1/jobs/nightly-ingest").status_code == 405


def test_resolve_requires_operator_secret(monkeypatch):
    monkeypatch.setattr("app.core.config.settings.operator_secret", "op-secret")
    c = _client()
    assert c.post("/api/v1/events/does-not-exist/resolve").status_code == 401
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend && python -m pytest tests/test_jobs.py -q`
Expected: FAIL — 404 for `/api/v1/jobs/*` (router does not exist yet).

- [ ] **Step 3: Create the jobs module**

Create `backend/app/api/jobs.py`:

```python
"""Scheduled job endpoints, invoked by Vercel Cron over HTTP GET.

Crons are best-effort, never retried, and can be delivered twice or overlap, so
both jobs are idempotent and reconciliation-based (spec §10). GET is not a
mistake: a POST-only job endpoint returns 405 to every scheduled run and looks
like a healthy deploy that never ingests anything.
"""
import logging

from fastapi import APIRouter, Depends, Header, HTTPException

from app.core.config import settings

log = logging.getLogger(__name__)
router = APIRouter()


def _bearer(authorization: str | None, secret: str, label: str) -> None:
    if not secret or authorization != f"Bearer {secret}":
        raise HTTPException(401, f"invalid {label}")


def require_cron(authorization: str | None = Header(None)) -> None:
    _bearer(authorization, settings.cron_secret, "cron secret")


def require_operator(authorization: str | None = Header(None)) -> None:
    _bearer(authorization, settings.operator_secret, "operator secret")


@router.get("/jobs/nightly-ingest", dependencies=[Depends(require_cron)])
async def nightly_ingest():
    raise NotImplementedError  # filled in by Task 7


@router.get("/jobs/nightly-brief", dependencies=[Depends(require_cron)])
async def nightly_brief():
    raise NotImplementedError  # filled in by Task 7
```

`NotImplementedError` bodies are acceptable between tasks here because the Task 6 tests only assert the 401/405 gate, and Task 7 replaces both bodies in the same review cycle. Do not ship this file state: Task 7's commit must remove both `raise` lines.

- [ ] **Step 4: Mount it and tighten CORS**

In `backend/app/main.py`, import the new router and mount it next to the existing one. Replace lines 38-45:

```python
app = FastAPI(title="BMKG Intelligence API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router, prefix="/api/v1")
```

with:

```python
app = FastAPI(title="BMKG Intelligence API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router, prefix="/api/v1")
app.include_router(jobs.router, prefix="/api/v1")
```

and add `from app.api import jobs` beside the existing `from app.api.routes import router` (line 9).

- [ ] **Step 5: Add `kind` to the briefing contract**

In `backend/app/schemas.py`, inside `BriefingOut` (line 164), add one field so the read path can label a stored document:

```python
    kind: str = "live"  # "daily" = the 01:00 WIB cron, "live" = rebuilt on new ingest
```

Defaulted, so `build_briefing`'s return dict (which has no `kind`) still validates.

- [ ] **Step 6: Run tests**

Run: `cd backend && python -m pytest tests/test_jobs.py -q`
Expected: PASS for the 401 and 405 assertions. `test_cron_endpoints_are_get_only` requires FastAPI to answer 405 (not 404) for a path that exists with the wrong verb — that is FastAPI's behaviour for a registered `@router.get` path hit with `POST`.

Run: `cd backend && python -m pytest -q`
Expected: PASS. (If `test_unknown_route_404` in `tests/test_api.py` asserts `404 in (404, 405)`, it still passes.)

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/jobs.py backend/app/main.py backend/app/schemas.py backend/tests/test_jobs.py
git commit -m "feat: add GET-only cron job endpoints with fail-closed secrets"
```

---

### Task 7: Nightly ingest and nightly brief jobs

**Files:**
- Modify: `backend/app/api/jobs.py` (replace both `NotImplementedError` bodies)
- Test: `backend/tests/test_jobs.py` (append)

**Interfaces:**
- Consumes: `ingest_svc.run_ingest(session) -> dict`, `job_state.{try_claim,mark_done,last_ok,KEY_INGEST,KEY_BRIEF}`, `brief_store.build_and_store(session, kind)`, `settings.ingest_interval_seconds`.
- Produces: `GET /api/v1/jobs/nightly-ingest`, `GET /api/v1/jobs/nightly-brief`; `async def run_ingest_cycle(session, *, force: bool) -> dict` in `jobs.py` (shared with Task 8's on-load path).

- [ ] **Step 1: Write the failing reconciliation tests**

Append to `backend/tests/test_jobs.py`:

```python
from datetime import datetime, timedelta, timezone

import pytest

from app.core.db import SessionLocal
from app.services import brief_store, ingest, job_state


@pytest.fixture
def stubbed(monkeypatch):
    """Replace every upstream caller with a counter so a test can assert what ran."""
    calls = {"ingest": 0, "brief": 0}

    async def fake_run_ingest(session):
        calls["ingest"] += 1
        return {"quakes": 0, "weather": 0, "errors": []}

    async def fake_build_and_store(session, kind):
        calls["brief"] += 1

        class _R:
            generated_at = datetime.now(timezone.utc)
            kind = "stub"
        return _R()

    monkeypatch.setattr(ingest, "run_ingest", fake_run_ingest)
    monkeypatch.setattr(brief_store, "build_and_store", fake_build_and_store)
    return calls


async def _run(fn):
    async with SessionLocal() as session:
        return await fn(session)


async def test_nightly_ingest_ignores_the_interval_claim(stubbed, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.cron_secret", "x")
    # A user-triggered fetch 10 seconds ago must not cause the scheduled run to
    # skip BMKG — a forced claim stamps the row instead of checking it.
    await _run(lambda s: job_state.try_claim(s, "ingest", 300))
    out = await _run(lambda s: jobs_module.nightly_ingest(session=s))
    assert stubbed["ingest"] == 1
    assert out["forced"] is True


async def test_nightly_brief_reingests_when_data_is_stale(stubbed, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.cron_secret", "x")
    await _run(lambda s: job_state.mark_done(s, "ingest"))
    await _run(lambda s: s.execute(
        job_state.JobState.__table__.update()
        .where(job_state.JobState.key == "ingest")
        .values(last_ok_at=datetime.now(timezone.utc) - timedelta(hours=13))
    ))
    await _run(lambda s: s.commit())
    out = await _run(lambda s: jobs_module.nightly_brief(session=s))
    assert stubbed["ingest"] == 1 and stubbed["brief"] == 1
    assert out["reconciled_ingest"] is True


async def test_nightly_brief_skips_ingest_when_fresh(stubbed, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.cron_secret", "x")
    await _run(lambda s: job_state.try_claim(s, "ingest", 300))
    await _run(lambda s: job_state.mark_done(s, "ingest"))
    await _run(lambda s: s.commit())
    out = await _run(lambda s: jobs_module.nightly_brief(session=s))
    assert stubbed["ingest"] == 0 and stubbed["brief"] == 1
    assert out["reconciled_ingest"] is False
```

Add `from app.api import jobs as jobs_module` to the imports. Note `job_state.JobState` — expose the model through the module (`from app.models import JobState` inside `job_state.py` is unnecessary; import `JobState` from `app.models` directly in the test instead).

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend && python -m pytest tests/test_jobs.py -q`
Expected: FAIL — `NotImplementedError` inside the job bodies (surfacing as 500/`raise_server_exceptions`).

- [ ] **Step 3: Implement the shared ingest cycle**

In `backend/app/api/jobs.py`, add imports (`timedelta`, `settings` already present, plus `AsyncSession`, `Depends`, `get_session`, `ingest as ingest_svc`, `brief_store`, `job_state`) and:

```python
STALE_INGEST_AFTER_HOURS = 12


async def run_ingest_cycle(session, *, force: bool) -> dict:
    """Claim-protected ingest. `force` is for scheduled runs: they always work,
    and stamping the claim is what stops concurrent on-load requests from
    duplicating the same BMKG fetch."""
    claimed = await job_state.try_claim(
        session, job_state.KEY_INGEST, settings.ingest_interval_seconds, force=force
    )
    if not claimed:
        return {"skipped": "recent_ingest", "quakes": 0, "weather": 0, "errors": []}
    try:
        summary = await ingest_svc.run_ingest(session)
        await job_state.mark_done(
            session,
            job_state.KEY_INGEST,
            error="; ".join(summary["errors"]) or None if summary["errors"] else None,
        )
        await session.commit()
    except Exception as e:  # never lose the error into a 200 with no trace
        log.exception("ingest cycle failed")
        await session.rollback()
        await job_state.mark_done(session, job_state.KEY_INGEST, error=str(e))
        await session.commit()
        raise
    summary["forced"] = force
    return summary


async def ensure_fresh_ingest(session) -> bool:
    """Reconciliation: cron delivery is best-effort, so a missed ingest run must
    be caught up by the job that depends on its data. Returns True if it ran."""
    last = await job_state.last_ok(session, job_state.KEY_INGEST)
    if last is not None and datetime.now(timezone.utc) - last < timedelta(
        hours=STALE_INGEST_AFTER_HOURS
    ):
        return False
    await run_ingest_cycle(session, force=True)
    return True
```

- [ ] **Step 4: Implement both job endpoints**

Replace the two placeholder bodies in `backend/app/api/jobs.py`:

```python
@router.get("/jobs/nightly-ingest")
async def nightly_ingest(session: AsyncSession = Depends(get_session)):
    """00:00 WIB. Collectors only — the 01:00 brief job owns the digest, so this
    run does not spend an LLM call at midnight."""
    return await run_ingest_cycle(session, force=True)


@router.get("/jobs/nightly-brief")
async def nightly_brief(session: AsyncSession = Depends(get_session)):
    """01:00 WIB. Guarantees a dated executive brief exists even if nobody opens
    the dashboard. Re-ingests first if the last success is >12h old."""
    reconciled = await ensure_fresh_ingest(session)
    row = await brief_store.build_and_store(session, kind="daily")
    log.info("nightly brief stored: %s (kind=daily, llm_status=%s)", row.generated_at, row.llm_status)
    return {
        "brief_generated_at": row.generated_at.isoformat(),
        "llm_status": row.llm_status,
        "reconciled_ingest": reconciled,
    }
```

Add to `backend/app/api/jobs.py` imports:

```python
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_session
from app.services import brief_store
from app.services import ingest as ingest_svc
from app.services import job_state
```

- [ ] **Step 5: Run tests**

Run: `cd backend && python -m pytest tests/test_jobs.py -q`
Expected: PASS (auth tests + the three reconciliation tests).

Run: `cd backend && python -m pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/jobs.py backend/tests/test_jobs.py
git commit -m "feat: add nightly ingest and nightly brief jobs with reconciliation"
```

---

### Task 8: Switch the read path and guard the on-load ingest

**Files:**
- Modify: `backend/app/api/routes.py:152-155` (`ingest_run`), `:170-174` (`briefing`), `:158-167` (`resolve_event`), the `/status` handler (lines 29-60)
- Test: `backend/tests/test_ingest_guard.py`

**Interfaces:**
- Consumes: `jobs.run_ingest_cycle`, `brief_store.{rebuild_needed,current_document,build_and_store}`, `job_state.*`, `settings.brief_min_rebuild_seconds`.
- Produces: `GET /api/v1/briefing` reading storage; `POST /api/v1/ingest/run` returning `{**summary, "brief_rebuilt": bool}`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_ingest_guard.py`:

```python
from datetime import datetime, timedelta, timezone

import pytest

from app.api import jobs
from app.core.db import SessionLocal
from app.services import brief_store, ingest, job_state


@pytest.fixture
def stubbed(monkeypatch):
    calls = {"ingest": 0, "brief": 0}

    async def fake_run_ingest(session):
        calls["ingest"] += 1
        return {"quakes": 1, "weather": 0, "errors": []}

    async def fake_build_and_store(session, kind):
        calls["brief"] += 1

        class _R:
            generated_at = datetime.now(timezone.utc)
            kind = kind
            based_on_ingest_at = datetime.now(timezone.utc)
        return _R()

    monkeypatch.setattr(ingest, "run_ingest", fake_run_ingest)
    monkeypatch.setattr(brief_store, "build_and_store", fake_build_and_store)
    return calls


async def test_second_ingest_request_does_no_work(stubbed):
    async with SessionLocal() as s:
        a = await jobs.run_ingest_cycle(s, force=False)
        b = await jobs.run_ingest_cycle(s, force=False)
    assert stubbed["ingest"] == 1
    assert "skipped" in b and a["quakes"] == 1


async def test_five_loads_one_llm_call(stubbed, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.brief_min_rebuild_seconds", 900)
    for _ in range(5):
        async with SessionLocal() as s:
            await jobs.run_ingest_cycle(s, force=False)
            await jobs.maybe_rebuild_brief(s)
    assert stubbed["ingest"] == 1
    assert stubbed["brief"] == 0      # nobody re-fetched, so nothing to reflect


async def test_brief_rebuilt_once_after_a_real_ingest(stubbed, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.brief_min_rebuild_seconds", 0)
    async with SessionLocal() as s:
        await jobs.run_ingest_cycle(s, force=True)
        await jobs.maybe_rebuild_brief(s)
    assert stubbed["brief"] == 1
    async with SessionLocal() as s:
        await jobs.maybe_rebuild_brief(s)   # the stored brief is now current
    assert stubbed["brief"] == 1


async def test_briefing_read_returns_stored_document(stubbed):
    async with SessionLocal() as s:
        await brief_store.store(
            s, {"headline": "stored"}, kind="daily",
            based_on_ingest_at=None, llm_status="ok", llm_model="openrouter/free",
        )
    stubbed["ingest"] = 0
    async with SessionLocal() as s:
        doc = await brief_store.current_document(s)
    assert doc == {"headline": "stored", "kind": "daily"}
    assert stubbed["ingest"] == 0     # reading a brief must never trigger work
```

`test_five_loads_one_llm_call` and `test_brief_rebuilt_once_after_a_real_ingest` both need `jobs.maybe_rebuild_brief`, which does not exist yet.

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend && python -m pytest tests/test_ingest_guard.py -q`
Expected: FAIL — `AttributeError: module 'app.api.jobs' has no attribute 'maybe_rebuild_brief'`.

- [ ] **Step 3: Add the rebuild helper to jobs.py**

```python
async def maybe_rebuild_brief(session) -> bool:
    """Rebuild the rolling brief when it no longer reflects the newest data.

    Three conditions, and all must hold (spec §6): the stored brief predates the
    newest successful ingest, the floor interval has passed, and this instance
    wins the `brief` claim. That is what turns five dashboard loads in a minute
    into one LLM call.
    """
    newest = await brief_store.newest(session)
    ingest_at = await job_state.last_ok(session, job_state.KEY_INGEST)
    now = datetime.now(timezone.utc)
    if not brief_store.rebuild_needed(
        newest, ingest_at, floor_seconds=settings.brief_min_rebuild_seconds, now=now
    ):
        return False
    if not await job_state.try_claim(
        session, job_state.KEY_BRIEF, settings.brief_min_rebuild_seconds
    ):
        return False
    await brief_store.build_and_store(session, kind="live")
    await job_state.mark_done(session, job_state.KEY_BRIEF)
    return True
```

- [ ] **Step 4: Rewire the two routes**

In `backend/app/api/routes.py`, replace `ingest_run` (lines 152-155):

```python
@router.post("/ingest/run")
async def ingest_run(session: AsyncSession = Depends(get_session)):
    """On-load refresh. Unauthenticated by design — the claim interval is the
    authorization, since a secret in client JS is not a secret."""
    summary = await jobs.run_ingest_cycle(session, force=False)
    rebuilt = await jobs.maybe_rebuild_brief(session)
    return {**summary, "brief_rebuilt": rebuilt}
```

replace `briefing` (lines 170-174):

```python
@router.get("/briefing", response_model=BriefingOut)
async def briefing(session: AsyncSession = Depends(get_session)):
    """The stored executive brief: one indexed read, no collectors, no LLM call.

    An empty table (fresh deploy, before any cron or visitor) builds once so the
    drawer never shows an error on day one.
    """
    doc = await brief_store.current_document(session)
    if doc is None:
        row = await brief_store.build_and_store(session, kind="live")
        doc = {**row.payload, "kind": row.kind}
    return doc
```

and add imports at the top of `routes.py`: `from app.api import jobs`, `from app.services import brief_store`. Import direction check: `jobs.py` imports services only, `routes.py` imports `jobs` — no cycle, because `main.py` imports both after `routes`.

- [ ] **Step 5: Gate resolve, expose brief state in status**

In `routes.py:158-167`, change the handler signature to require the operator secret:

```python
@router.post("/events/{event_id}/resolve", dependencies=[Depends(require_operator)])
```

with `from app.api.jobs import require_operator` at the top. The 404 for an unknown id still comes from the body's `HTTPException(404, ...)`; the 401 fires first because dependencies resolve before the handler.

In the `/status` handler (lines 29-60), add two keys to the returned `OverviewStats` payload so a bad LLM night is visible without opening the drawer. Add to `backend/app/schemas.py` `OverviewStats`:

```python
    last_brief_at: str | None = None
    last_brief_llm_status: str | None = None
```

and in the handler, before returning:

```python
    row = await brief_store.newest(session)
    last_brief_at = row.generated_at.isoformat() if row else None
    last_brief_llm_status = row.llm_status if row else None
```

then include both in the returned dict.

- [ ] **Step 6: Run the suite**

Run: `cd backend && python -m pytest -q`
Expected: PASS. Pay attention to `tests/test_briefing.py` — if it asserts that `GET /briefing` recomputes, that assertion is now wrong and must be updated to read the store (the spec's §5 decision is the authority here, not the old test).

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/routes.py backend/app/api/jobs.py backend/app/schemas.py backend/tests/test_ingest_guard.py
git commit -m "feat: serve stored briefs and rebuild them on guarded ingest"
```

---

### Task 9: Platform hardening for serverless

**Files:**
- Modify: `backend/app/main.py:19-35` (delete the resident loop)
- Modify: `backend/app/core/db.py:21,30-45`
- Test: `backend/tests/test_api.py` (append)

**Interfaces:**
- Consumes: nothing new.
- Produces: a FastAPI app with no `while True`; `init_db` that survives a concurrent first deploy and a denied PostGIS extension.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_api.py`:

```python
def test_no_resident_ingest_loop():
    # A serverless function has no process to host `while True`; the loop must be
    # gone, not merely disabled by config.
    import inspect

    import app.main as m

    assert not hasattr(m, "_background_loop")
    src = inspect.getsource(m.lifespan)
    assert "create_task" not in src
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && python -m pytest tests/test_api.py -q`
Expected: FAIL — `_background_loop` still exists.

- [ ] **Step 3: Delete the loop**

In `backend/app/main.py`, remove lines 19-35 (`_background_loop` and the `create_task`/`task.cancel()` in `lifespan`) and leave:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield
```

Delete now-unused imports: `asyncio` (line 2) and `from app.services import ingest as ingest_svc` (line 13). Keep `SessionLocal` only if something else in the file uses it — it does not, so drop it from the line 11 import.

- [ ] **Step 4: Make startup survive a cold-start race and a denied extension**

Replace `backend/app/core/db.py:30-45` with:

```python
async def init_db() -> None:
    from app import models  # noqa: F401  (register tables)

    async with engine.begin() as conn:
        if settings.is_postgres:
            # Optional, and optional *must* mean optional: Neon's default role may
            # lack extension privileges, and aborting startup over a helper column
            # would take the whole API down with it.
            try:
                await conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
                await conn.execute(
                    text(
                        "ALTER TABLE events ADD COLUMN IF NOT EXISTS geom geography(Point,4326) "
                        "GENERATED ALWAYS AS (ST_SetSRID(ST_MakePoint(longitude, latitude),4326)::geography) STORED"
                    )
                )
            except Exception:
                log.warning("postgis unavailable; continuing without the optional geom column",
                            exc_info=True)
        try:
            await conn.run_sync(Base.metadata.create_all)
        except Exception:
            # Two instances can cold-start at once and both try to CREATE TABLE.
            # Whoever loses gets a duplicate-object error; the tables exist either way.
            log.warning("create_all raced on cold start; verifying schema is present",
                        exc_info=True)
        if settings.is_postgres:
            # The geom ALTER must run after create_all has made `events`.
            ...
```

The `...` line is a placeholder in the sense the writing-plans skill forbids, so restructure instead: move the PostGIS block **after** `create_all` and drop the second `if settings.is_postgres` entirely. Final shape:

```python
async def init_db() -> None:
    from app import models  # noqa: F401  (register tables)

    async with engine.begin() as conn:
        try:
            await conn.run_sync(Base.metadata.create_all)
        except Exception:
            # Two instances can cold-start at once and both try to CREATE TABLE;
            # the loser sees a duplicate-object error and the schema is present anyway.
            log.warning("create_all raced on cold start; schema should exist", exc_info=True)
        if settings.is_postgres:
            try:
                await conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
                await conn.execute(
                    text(
                        "ALTER TABLE events ADD COLUMN IF NOT EXISTS geom geography(Point,4326) "
                        "GENERATED ALWAYS AS "
                        "(ST_SetSRID(ST_MakePoint(longitude, latitude),4326)::geography) STORED"
                    )
                )
            except Exception:
                log.warning(
                    "postgis unavailable; continuing without the optional geom column",
                    exc_info=True,
                )
```

Add to the top of `db.py`: `import logging`, `from sqlalchemy import text`, `from app.core.config import settings` (already present), and `log = logging.getLogger(__name__)`. Note this reorders extension creation after `create_all`, which is what the original code's comment about "safe to re-run" assumed but did not guarantee.

- [ ] **Step 5: Keep asyncpg honest about prepared statements**

In `backend/app/core/db.py:21`, replace the engine creation:

```python
engine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
    future=True,
    # asyncpg prepares statements by default, which a transaction pooler such as
    # PgBouncer breaks. Neon's pooled endpoint is PgBouncer, so a future switch to
    # it would otherwise produce random 500s with no obvious cause.
    **({"connect_args": {"statement_cache_size": 0, "prepared_statement_cache_size": 0}}
       if settings.database_url.startswith("postgresql") else {}),
)
```

Verify locally that this does not break SQLite: `create_async_engine` receives no `connect_args` for `sqlite+aiosqlite://` URLs because the dict is empty.

- [ ] **Step 6: Run the suite and the app boot**

Run: `cd backend && python -m pytest -q`
Expected: PASS.

Run: `cd backend && python -c "from app.main import app; print(len(app.routes))"`
Expected: a route count that includes the two `/api/v1/jobs/*` paths; no `while True` started, and no uvicorn needed for this check.

- [ ] **Step 7: Commit**

```bash
git add backend/app/main.py backend/app/core/db.py backend/tests/test_api.py
git commit -m "fix: make the backend safe to run as a serverless function"
```

---

### Task 10: Frontend — automatic refresh, two controls removed

**Files:**
- Modify: `frontend/lib/types.ts:235-249`
- Modify: `frontend/lib/api.ts:25-26`
- Modify: `frontend/components/Dashboard.tsx:186-200,218-222,387-389,557`
- Modify: `frontend/components/TopBar.tsx:16,24,86-88`
- Modify: `frontend/components/BriefingPanel.tsx:62,69,99-101,119`

**Interfaces:**
- Consumes: `POST /api/v1/ingest/run` returning `{skipped?, quakes, weather, brief_rebuilt}`; `GET /api/v1/briefing` returning the stored document with `kind`.
- Produces: no new exports. `TopBar` loses the `onIngest` prop; `BriefingPanel` loses `onRefresh`.

- [ ] **Step 1: Add `kind` to the client type**

In `frontend/lib/types.ts`, add to the `Briefing` type (line 235 block, after `generated_at`):

```typescript
  kind?: "daily" | "live";
```

- [ ] **Step 2: Type the ingest response**

In `frontend/lib/api.ts`, replace lines 25-26:

```typescript
  ingest: () =>
    fetch(`${BASE}/api/v1/ingest/run`, { method: "POST" }).then((r) => r.json()),
```

with:

```typescript
  ingest: () =>
    fetch(`${BASE}/api/v1/ingest/run`, { method: "POST" })
      .then((r) => r.json() as Promise<{ skipped?: string; quakes: number; weather: number; brief_rebuilt: boolean }>)
      .catch(() => ({ skipped: "unreachable", quakes: 0, weather: 0, brief_rebuilt: false })),
```

The `.catch` matters: an unawaited background POST that rejects would raise an unhandled rejection in the console.

- [ ] **Step 3: Fire the refresh without blocking first paint**

In `frontend/components/Dashboard.tsx`, replace `runIngest` (lines 186-200) with a background version, and delete the `ingesting` state usage:

```tsx
  // The server decides whether this is a real fetch (atomic claim) and whether a
  // brief rebuild is due, so the client always asks and never reasons about age.
  // Fire-and-forget: a rebuild can take ~25s, which must not block first paint.
  const refreshInBackground = useCallback(async () => {
    const res = await api.ingest();
    if (res.skipped) return;
    await load();
    loadEscalation();
    loadClusters();
    loadAnalytics(true);
    loadChanges();
    if (res.brief_rebuilt && briefingOpen) loadBriefing();
  }, [load, loadEscalation, loadClusters, loadAnalytics, loadChanges, briefingOpen, loadBriefing]);
```

and in the existing mount effect (lines 218-222):

```tsx
  useEffect(() => {
    load();
    refreshInBackground();
    const t = setInterval(load, 60000);
    return () => clearInterval(t);
  }, [load, refreshInBackground]);
```

Add `briefingOpen` and `loadBriefing` to the dependency arrays of the callbacks they now appear in (both already exist in the file at lines 91-104 and in the state declarations).

- [ ] **Step 4: Remove the Ingest control**

In `Dashboard.tsx`, delete `onIngest={runIngest}` (line 389) and change `loading={loading || ingesting}` (line 387) to `loading={loading}`. Delete the `ingesting` state and `setIngesting` calls.

In `frontend/components/TopBar.tsx`, delete `onIngest,` from the destructured props (line 16), `onIngest: () => void;` from the type (line 24), and the button (lines 86-88):

```tsx
        <button className="btn" onClick={onIngest} title="Run all BMKG collectors now">
          Ingest
        </button>
```

Also fix the stale copy in `Dashboard.tsx:397` — the error banner says "then press Ingest", a control that no longer exists:

```tsx
            {err} The API is unreachable. Locally, start it with <code>uvicorn app.main:app</code>.
```

- [ ] **Step 5: Remove Regenerate, label the document**

In `frontend/components/BriefingPanel.tsx`, delete `onRefresh,` (line 62) and `onRefresh: () => void;` (line 69). Replace the Regenerate button (lines 99-101) with nothing — keep the close button. At line 119 the "Try again" button also calls `onRefresh`; replace it with a reload of the read path, which is now cheap and side-effect-free:

```tsx
            <button className="btn" onClick={onClose}>Close</button>
```

Then make the dated-document framing visible. Replace the drawer time block (lines 94-96):

```tsx
            <div className="drawer-time">
              {briefing ? fmtWIB(briefing.generated_at) : "—"} WIB
            </div>
```

with:

```tsx
            <div className="drawer-time">
              {briefing
                ? `${briefing.kind === "daily" ? "Morning executive summary" : "Live brief"} · ${fmtWIB(briefing.generated_at)} WIB`
                : "—"}
            </div>
```

- [ ] **Step 6: Drop the prop at the call site**

In `Dashboard.tsx`, delete `onRefresh={loadBriefing}` (line 557). Keep `loadBriefing` — `openBriefing` still calls it.

- [ ] **Step 7: Typecheck and build**

Run: `cd frontend && npm run typecheck`
Expected: PASS. A leftover `onIngest`/`onRefresh` reference is a type error, which is how this task is verified without a JS test runner.

Run: `cd frontend && npm run build`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add frontend/lib/types.ts frontend/lib/api.ts frontend/components/Dashboard.tsx frontend/components/TopBar.tsx frontend/components/BriefingPanel.tsx
git commit -m "feat: refresh data automatically on load and drop manual ingest and regenerate controls"
```

---

### Task 11: Vercel configuration and README

**Files:**
- Create: `vercel.json` (repo root)
- Modify: `frontend/next.config.mjs:7-29`
- Modify: `README.md:9-10,103-105,109-133`
- Modify: `backend/Dockerfile` (no change to the image itself, but the Python entrypoint for Vercel must not confuse the Docker build)

**Interfaces:**
- Consumes: everything above.
- Produces: a deployable project with two services and two crons.

- [ ] **Step 1: Create `vercel.json`**

```json
{
  "$schema": "https://openapi.vercel.sh/vercel.json",
  "services": {
    "web": { "root": "frontend/" },
    "api": {
      "root": "backend/",
      "entrypoint": "app.main:app",
      "functions": { "app/main.py": { "maxDuration": 300 } }
    }
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

`functions` sits inside the owning service, not at the top level — with `services` present, root-level `functions`, `buildCommand`, `framework`, `installCommand`, `devCommand`, `ignoreCommand` and `outputDirectory` are invalid. Routing into a service preserves the original path, so `/api/v1/status` reaches FastAPI unchanged and no route prefix work is needed.

- [ ] **Step 2: Delete the frontend proxy rewrite**

In `frontend/next.config.mjs`, remove the `async rewrites()` block (lines 21-28) and the now-unused `backendUrl` computation (lines 2-5). Keep `output` and `experimental.instrumentationHook`. Replace the file with:

```javascript
/** @type {import('next').NextConfig} */
const nextConfig = {
  // "standalone" output is only needed for the Docker image.
  output: process.env.STANDALONE_OUTPUT ? "standalone" : undefined,

  // `instrumentation.ts` starts the FastAPI backend alongside `next dev`
  // (development only — see the NODE_ENV guard in that file).
  experimental: {
    instrumentationHook: true,
  },
};

export default nextConfig;
```

Vercel service routing owns `/api/v1/*` now; leaving the old rewrite would make the frontend service proxy to `127.0.0.1:8000` inside a function.

- [ ] **Step 3: Exclude test data from the Python bundle**

The standard Python bundle limit is 500 MB and there is no tree-shaking for Python. Add to the `api` service in `vercel.json`:

```json
      "functions": {
        "app/main.py": {
          "maxDuration": 300,
          "excludeFiles": "{tests/**,**/*.test.py,**/test_*.py,*.db,*.duckdb}"
        }
      }
```

(replacing the simpler `functions` block from Step 1 — keep exactly one.)

- [ ] **Step 4: Update the README**

Four edits to `README.md`:

1. Lines 9-10 — replace "**Status: local-only.** No public deployment yet — run it via the Quickstart below" with a deployment section stating the Vercel target, the two cron times in WIB **and** UTC, and that Hobby fires a daily cron anywhere within the hour.
2. Lines 103-105 — remove "set a production vector-tile URL (e.g. in `components/Map.tsx`) before any public deployment". `Map.tsx:20` already uses CARTO dark-matter (key-free) as the primary style with `demotiles.maplibre.org` only as an `on("error")` fallback, so the instruction is stale.
3. Configuration table (lines 109-133) — delete the `DUCKDB_PATH` row; add `CRON_SECRET`, `OPERATOR_SECRET`, `ALLOWED_ORIGINS`, `BRIEF_MIN_REBUILD_SECONDS`; change `INGEST_INTERVAL_SECONDS`'s note from "Background ingest cadence" to "Minimum seconds between real ingests (the on-load refresh guard)"; correct the `OPENROUTER_MODEL` row to say `openrouter/free` is a working value.
4. Architecture diagram (lines 23-31) and the "Key decisions" list — replace "FastAPI (/api/v1) ──► Next.js + MapLibre dashboard" with the two-service shape, add `Vercel Cron (17:00 / 18:00 UTC)` above the ingest box, and note that briefings are stored rather than recomputed.

- [ ] **Step 5: Verify the JSON and the build locally**

Run: `python -m json.tool vercel.json > /dev/null && echo "vercel.json valid"`
Expected: `vercel.json valid`.

Run: `cd frontend && npm run build`
Expected: PASS with no rewrite warning about `BACKEND_INTERNAL_URL`.

- [ ] **Step 6: Commit**

```bash
git add vercel.json frontend/next.config.mjs README.md
git commit -m "build: add Vercel services config with nightly crons and document the deployment"
```

---

### Task 12: Deploy gate (requires the user's Vercel account)

This task is executed with the human partner, not autonomously. Every step is a verification, and the order is load-bearing: promoting to production before the secrets exist means the crons fire against a 401.

- [ ] **Step 1: Install Neon from the Vercel Marketplace** and take the **direct** (non-pooled) connection URL. Confirm `CREATE EXTENSION postgis` is permitted for that role; if not, note that the app now degrades to the optional-`geom` path from Task 9.

- [ ] **Step 2: Set project environment variables** — `DATABASE_URL` (`postgresql+asyncpg://…`), `OPENROUTER_API_KEY`, `OPENROUTER_MODEL=openrouter/free`, `CRON_SECRET` (random, ≥16 chars), `ALLOWED_ORIGINS` (the deployed origin, or empty), `OPERATOR_SECRET`. Confirm none are set as `NEXT_PUBLIC_*`.

- [ ] **Step 3: Preview deploy.** Verify both services build, and that the API function bundle is under 500 MB in the build log.

- [ ] **Step 4: Verify routing on the preview URL**

```bash
curl -s https://<preview>.vercel.app/api/v1/health          # expect {"status":"ok"} from FastAPI
curl -s -o /dev/null -w "%{http_code}" https://<preview>.vercel.app/   # expect 200 from Next
curl -s -X POST https://<preview>.vercel.app/api/v1/ingest/run          # expect JSON with quakes/weather
curl -s https://<preview>.vercel.app/api/v1/jobs/nightly-ingest         # expect 401 (no secret)
```

Expected: the health payload comes from the Python service, `/` from Next, and the job endpoint refuses an unauthenticated caller.

- [ ] **Step 5: Promote to production**, then trigger both jobs with the secret:

```bash
curl -s -H "Authorization: Bearer $CRON_SECRET" https://<prod>.vercel.app/api/v1/jobs/nightly-ingest
curl -s -H "Authorization: Bearer $CRON_SECRET" https://<prod>.vercel.app/api/v1/jobs/nightly-brief
```

Expected: the first returns `{"quakes":…,"weather":…,"forced":true}`; the second returns `{"brief_generated_at":…,"llm_status":"ok","reconciled_ingest":false}`. `llm_status` must be `ok` — `misconfigured` means `OPENROUTER_MODEL` did not take effect, `rejected`/`empty` mean the free router produced an unusable note (spec §8, acceptable but worth watching).

- [ ] **Step 6: Confirm the brief is a read, not a computation**

```bash
time curl -s https://<prod>.vercel.app/api/v1/briefing | head -c 200
```

Expected: sub-second, and `kind` present. If the response time scales with content size, the read path is still computing.

- [ ] **Step 7: Confirm cron registration**

Run: `vercel crons list`
Expected: both entries, attached to production, enabled.

- [ ] **Step 8: Browser verification of the deployed UI** (the part typecheck cannot prove): the dashboard renders on first paint without waiting for the ingest POST, the map loads the CARTO basemap, the drawer shows the kind label and generation time, and neither an "Ingest" nor a "Regenerate" button appears.

- [ ] **Step 9: Leave local dev off the production database.** `backend/.env` must keep a SQLite or compose-Postgres `DATABASE_URL`, or the local ingest loop and the production crons will race over the same rows.

---

## Self-Review

**1. Spec coverage.** §4 topology → Task 11. §5 models/settings → Task 1. §6 jobs + guards → Tasks 2, 3, 6, 7, 8; frontend refresh → Task 10. §7 analytics → Tasks 5, 5b. §8 OpenRouter correction → Task 4. §9 security → Tasks 6 (cron/operator/CORS) and 8 (resolve gated, status reports `llm_status`). §10 failure modes → Task 9 (`create_all` race, PostGIS denial, asyncpg prepared statements) plus Task 7 (reconciliation) and Task 3 (pruning, floor). §11 tests → Tasks 1-10. §12 deploy gate → Task 12. §13 out of scope → not implemented, correct. No spec requirement is unassigned.

**2. Placeholder scan.** Task 4 Step 1 and Task 9 Step 4 contained draft-time notes ("replace the weak assert", "the `...` line is a placeholder") — both are resolved inline in those steps, with the final code stated explicitly so an implementer never has to guess. `NotImplementedError` bodies in Task 6 are explicitly bounded to that task and removed by Task 7, with the constraint written into the step.

**3. Type consistency.** `try_claim(session, key, min_interval_seconds, *, force)` is defined in Task 2 and called identically in Tasks 7 and 8. `rebuild_needed(newest, ingest_ok_at, *, floor_seconds, now)` is defined in Task 3 and called with those keyword arguments in Task 8 Step 3. `build_and_store(session, kind)` and `store(session, payload, *, kind, based_on_ingest_at, llm_status, llm_model)` match across Tasks 3, 7, 8 and the tests. `run_ingest_cycle` and `maybe_rebuild_brief` are both produced in `app.api.jobs` and consumed by `routes.py` in Task 8. Settings names are used exactly as declared in Task 1: `brief_min_rebuild_seconds`, `cron_secret`, `operator_secret`, `allowed_origins`, `cors_origins`.

**4. Known risk to re-check during execution.** `jobs.mark_done(..., error="; ".join(...) or None if summary["errors"] else None)` in Task 7 Step 3 has a confusing operator-precedence shape; simplify it to `error=("; ".join(summary["errors"]) or None) if summary.get("errors") else None` when writing the file, and add an assertion in the tests that a summary with errors leaves `last_error` populated and `last_ok_at` unchanged.
