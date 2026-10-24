"""The app's route table (ROADMAP_v2 B1): one handler per path, no stray docs, and the routes Settings uses."""
import secrets
from collections import Counter
from uuid import uuid4

import pytest
from fastapi.routing import iter_route_contexts
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from athena.api.deps import get_db
from athena.api.main import app
from athena.core.models import FetchLog, Source, SourceCategory, SourceType


def _routes():
    # FastAPI keeps included routers nested in app.routes; iter_route_contexts walks them with full paths.
    return [(method, route.path) for route in iter_route_contexts(app.routes) for method in (route.methods or [])]


def test_no_two_routes_share_a_method_and_path():
    routes = _routes()
    assert len(routes) > 100  # every router, not just the app's own /health
    assert [pair for pair, n in Counter(routes).items() if n > 1] == []


def test_no_docs_under_the_api_prefix():
    paths = {path for _, path in _routes()}
    assert not {p for p in paths if p.startswith(("/api/v1/docs", "/api/v1/redoc", "/api/v1/openapi"))}


@pytest.mark.parametrize("method,path", [
    ("POST", "/api/v1/admin/rescore-all"),
    ("GET", "/api/v1/health/scoring"),
    ("GET", "/api/v1/health/fetch"),
    ("GET", "/api/v1/items/{item_id}/score-breakdown"),
    ("GET", "/api/v1/items/{item_id}/summary"),
    ("GET", "/api/v1/admin/summaries/cost"),
    ("GET", "/api/v1/admin/summaries/sample"),
    ("POST", "/api/v1/admin/items/{item_id}/regenerate-summary"),
])
def test_kept_routes_exist(method, path):
    assert (method, path) in _routes()


@pytest.mark.parametrize("path", ["/api/v1/items/top/{category}", "/api/v1/items/trending", "/api/v1/trending"])
def test_unreachable_routes_are_gone(path):
    assert path not in {p for _, p in _routes()}


def test_fetch_health_uses_the_shared_session():
    """The scoring routes take athena.api.deps.get_db, so a test (or any override) reaches them."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Source.__table__.create(engine)
    FetchLog.__table__.create(engine)
    Session = sessionmaker(bind=engine)
    with Session() as s:
        source = Source(id=uuid4(), name="S", url="https://example.com", type=SourceType.RSS,
                        category=SourceCategory.COMPANY)
        s.add(source)
        s.add_all([FetchLog(source_id=source.id, status="success", duration_ms=1.0),
                   FetchLog(source_id=source.id, status="error", duration_ms=1.0)])
        s.commit()

    def override():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override
    try:
        r = TestClient(app).get("/api/v1/health/fetch")
    finally:
        app.dependency_overrides.pop(get_db, None)
    assert r.status_code == 200
    assert r.json() == {"total_fetches": 2, "successful_fetches": 1, "failed_fetches": 1, "success_rate": 50.0}


# ── API docs (B2): off by default; Basic Auth when a password is set ──

DOC_PATHS = ["/docs", "/redoc", "/openapi.json"]
DOCS_USER = "athena"
DOCS_PASS = secrets.token_urlsafe(16)  # made each run, so no credential sits in the repo


def _app_with_docs(monkeypatch, enabled: bool, password: str = ""):
    from athena.api import main
    monkeypatch.setattr(main.settings, "DOCS_ENABLED", enabled)
    monkeypatch.setattr(main.settings, "DOCS_USERNAME", DOCS_USER)
    monkeypatch.setattr(main.settings, "DOCS_PASSWORD", password)
    return main.create_app()


@pytest.mark.parametrize("path", DOC_PATHS)
def test_docs_are_off_unless_enabled(monkeypatch, path):
    assert TestClient(_app_with_docs(monkeypatch, False, DOCS_PASS)).get(path).status_code == 404


@pytest.mark.parametrize("path", DOC_PATHS)
def test_docs_with_a_password_ask_for_it(monkeypatch, path):
    client = TestClient(_app_with_docs(monkeypatch, True, DOCS_PASS))
    assert client.get(path).status_code == 401
    assert client.get(path, auth=(DOCS_USER, DOCS_PASS + "-wrong")).status_code == 401
    assert client.get(path, auth=(DOCS_USER, DOCS_PASS)).status_code == 200


def test_the_schema_lists_the_api(monkeypatch):
    client = TestClient(_app_with_docs(monkeypatch, True, DOCS_PASS))
    schema = client.get("/openapi.json", auth=(DOCS_USER, DOCS_PASS)).json()
    assert "/api/v1/health/fetch" in schema["paths"]


def test_docs_without_a_password_are_open_and_warn(monkeypatch):
    from loguru import logger
    warnings = []
    sink = logger.add(lambda m: warnings.append(m.record["message"]), level="WARNING")
    try:
        client = TestClient(_app_with_docs(monkeypatch, True))
    finally:
        logger.remove(sink)
    assert all(client.get(p).status_code == 200 for p in DOC_PATHS)
    assert any("DOCS_PASSWORD" in w for w in warnings)
