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

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

log = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


engine = create_async_engine(
    settings.database_url,
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
