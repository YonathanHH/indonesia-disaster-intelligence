from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.core.db import Base
from app.main import app


def _client(tmp_path):
    import app.core.db as db
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    # isolated sqlite file for API test
    url = f"sqlite:///{tmp_path}/api.db"
    eng = create_engine(url)
    Base.metadata.create_all(eng)
    Sm = sessionmaker(bind=eng)

    async def override():
        s = Sm()
        try:
            yield s
        finally:
            s.close()

    # NOTE: routes use AsyncSession interface (execute/commit); use a sync shim
    # Simpler: test health + validation paths that don't hit DB transactionally.
    return TestClient(app, raise_server_exceptions=False)


def test_health():
    c = TestClient(app, raise_server_exceptions=False)
    r = c.get("/api/v1/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_unknown_route_404():
    c = TestClient(app, raise_server_exceptions=False)
    r = c.get("/api/v1/social/import")
    assert r.status_code in (404, 405)
