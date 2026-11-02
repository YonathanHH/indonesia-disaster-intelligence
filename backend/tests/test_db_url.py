from app.core.db import driver_url

NEON_POOLED = (
    "postgresql://neondb_owner:pw@ep-delicate-bread-pooler.c-3.ap-southeast-1.aws"
    ".neon.tech:5432/neondb?channel_binding=require&sslmode=require"
)


def test_neon_url_becomes_asyncpg_compatible():
    """Neon ships libpq params; asyncpg only accepts `ssl` and no `channel_binding`."""
    out = driver_url(NEON_POOLED)
    assert "channel_binding" not in out
    assert "sslmode" not in out
    assert "ssl=require" in out
    assert out.startswith("postgresql+asyncpg://")
    assert "neondb" in out and "pooler" in out


def test_bare_postgresql_scheme_gets_the_async_driver():
    """create_async_engine("postgresql://") selects psycopg2, which is not installed."""
    assert driver_url("postgresql://u:p@h:5432/db").startswith("postgresql+asyncpg://")


def test_explicit_asyncpg_scheme_is_untouched():
    url = "postgresql+asyncpg://u:p@h:5432/db?ssl=require"
    assert driver_url(url) == url


def test_tls_strength_is_not_silently_weakened():
    out = driver_url("postgresql://u:p@h/db?sslmode=verify-full")
    assert "ssl=verify-full" in out


def test_sqlite_url_is_left_alone():
    url = "sqlite+aiosqlite:///./bmkgintel.db"
    assert driver_url(url) == url


def test_postgres_url_without_params_is_unchanged():
    url = "postgresql+asyncpg://u:p@localhost:5432/db"
    assert driver_url(url) == url


def test_other_query_params_survive():
    out = driver_url("postgresql://u:p@h/db?sslmode=require&application_name=bmkg")
    assert "application_name=bmkg" in out
    assert "ssl=require" in out
