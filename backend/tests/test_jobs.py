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
