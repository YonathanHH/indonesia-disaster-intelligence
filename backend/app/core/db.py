"""Async engine + session factory.

Tradeoff: PostgreSQL(+PostGIS) is the production target, but local dev
must work with zero dependencies. So we default to SQLite file DB and
enable PostGIS opportunistically when DATABASE_URL is postgres.
Spatial queries use DB-side ST_* functions when available, otherwise a
Python haversine fallback (services/geo.py). No hard GeoAlchemy
dependency — lat/lon float columns are the portable source of truth,
with an optional generated geography column created on postgres.
"""
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


class Base(DeclarativeBase):
    pass


engine = create_async_engine(settings.database_url, pool_pre_ping=True, future=True)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_session():
    async with SessionLocal() as session:
        yield session


async def init_db() -> None:
    from app import models  # noqa: F401  (register tables)

    async with engine.begin() as conn:
        if settings.is_postgres:
            await conn.execute(__import__("sqlalchemy").text("CREATE EXTENSION IF NOT EXISTS postgis"))
        await conn.run_sync(Base.metadata.create_all)
        if settings.is_postgres:
            # Optional geography helper column for spatial indexing; safe to re-run.
            await conn.execute(
                __import__("sqlalchemy").text(
                    "ALTER TABLE events ADD COLUMN IF NOT EXISTS geom geography(Point,4326) "
                    "GENERATED ALWAYS AS (ST_SetSRID(ST_MakePoint(longitude, latitude),4326)::geography) STORED"
                )
            )
