"""Async engine + session factory.

Tradeoff: PostgreSQL(+PostGIS) is the production target, but local dev
must work with zero dependencies. So we default to SQLite file DB and
enable PostGIS opportunistically when DATABASE_URL is postgres.
Spatial queries use DB-side ST_* functions when available, otherwise a
Python haversine fallback (services/geo.py). No hard GeoAlchemy
dependency — lat/lon float columns are the portable source of truth,
with an optional generated geography column created on postgres.
"""
import logging
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

log = logging.getLogger(__name__)


def driver_url(url: str) -> str:
    """Rewrite a provider's connection string into what asyncpg actually accepts.

    Neon ships `sslmode` and `channel_binding`, and SQLAlchemy forwards every
    query parameter to asyncpg.connect() — which raises TypeError on either name.
    A bare `postgresql://` is worse: create_async_engine() reads it as psycopg2,
    a sync driver we do not install, so the engine cannot even be built.
    """
    if not url.startswith("postgresql"):
        return url
    parts = urlsplit(url)
    kept, changed = [], False
    for key, value in parse_qsl(parts.query):
        if key == "channel_binding":
            changed = True
            continue
        if key == "sslmode":
            key, changed = "ssl", True
        kept.append((key, value))
    scheme = parts.scheme
    if scheme == "postgresql":
        scheme, changed = "postgresql+asyncpg", True
    if not changed:
        return url
    return urlunsplit((scheme, parts.netloc, parts.path, urlencode(kept), parts.fragment))


class Base(DeclarativeBase):
    pass


engine = create_async_engine(
    driver_url(settings.database_url),
    pool_pre_ping=True,
    future=True,
    # asyncpg prepares statements by default, which a transaction pooler such as
    # PgBouncer breaks. Neon's pooled endpoint is PgBouncer, so a switch to it
    # would otherwise produce random 500s with no obvious cause.
    **({"connect_args": {"statement_cache_size": 0, "prepared_statement_cache_size": 0}}
       if settings.is_postgres else {}),
)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_session():
    async with SessionLocal() as session:
        yield session


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
            # Optional, and optional must mean optional: the default role may lack
            # extension privileges, and aborting startup over a helper column would
            # take the whole API down with it. Runs after create_all, which the
            # original "safe to re-run" comment assumed but did not guarantee.
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
