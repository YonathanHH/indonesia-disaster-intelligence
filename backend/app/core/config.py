"""Central configuration."""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "BMKG Intelligence"
    database_url: str = "sqlite+aiosqlite:///./bmkgintel.db"
    bmkg_http_timeout: int = 15
    ingest_interval_seconds: int = 300
    # Optional LLM rephrase via OpenRouter (OpenAI-compatible API).
    # Get a key at https://openrouter.ai/keys — free models need no credits.
    openrouter_api_key: str = ""
    openrouter_model: str = "openrouter/free"
    openrouter_site_url: str = ""
    openrouter_app_name: str = "BMKG Intelligence"
    # Optional custom active-fault GeoJSON URL (LineString/MultiLineString).
    # Empty = faults layer reports unavailable (no open dataset covers Indonesia).
    faults_geojson_url: str = ""
    # DuckDB sidecar for OLAP analytics. Primary store stays Postgres/SQLite;
    # this file is rebuilt as a mirror on demand by /api/v1/analytics.
    duckdb_path: str = "./analytics.duckdb"

    model_config = {"env_file": ".env", "extra": "ignore"}

    @property
    def is_postgres(self) -> bool:
        return self.database_url.startswith("postgresql")


settings = Settings()
