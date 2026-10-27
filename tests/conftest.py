"""Shared test setup: API tests run as a logged-in admin unless they test logging in itself."""
from uuid import uuid4

import pytest
from sqlalchemy import ARRAY
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from athena.core.models import User


@compiles(JSONB, "sqlite")
@compiles(ARRAY, "sqlite")
def _as_json(type_, compiler, **kw):  # Postgres types in tables SQLite tests create; SQLite stores them as JSON
    return "JSON"


ADMIN = User(id=uuid4(), email="admin@example.com", display_name="Admin", password_hash="-", role="admin",
             is_active=True, must_change_password=False)


@pytest.fixture(autouse=True)
def logged_in_admin(request):
    """Every route needs an account since F2; most tests are about something else, so they get an admin.

    Mark a test (or module) with ``@pytest.mark.real_auth`` to go through the real session cookie.
    """
    if request.node.get_closest_marker("real_auth"):
        yield
        return
    from athena.api.auth import active_user, current_user
    from athena.api.main import app
    app.dependency_overrides[current_user] = lambda: ADMIN
    app.dependency_overrides[active_user] = lambda: ADMIN
    yield
    app.dependency_overrides.pop(current_user, None)
    app.dependency_overrides.pop(active_user, None)


@pytest.fixture(autouse=True)
def model_registry(monkeypatch):
    """No model registry and no chat lane in Redis unless a test sets them: the real ones read the database and
    Redis of whatever machine runs the tests. Returns the list ``registry.snapshot()`` serves."""
    from athena.model_server import lane, registry
    from tests.fakes import FakeRedis
    rows: list[dict] = []
    fake = FakeRedis()
    monkeypatch.setattr(registry, "snapshot", lambda: rows)
    monkeypatch.setattr(lane, "_redis", lambda: fake)
    return rows


def pytest_configure(config):
    config.addinivalue_line("markers", "real_auth: use real sessions instead of the logged-in admin")
    config.addinivalue_line("markers", "network: needs the internet; CI runs -m 'not network'")


@pytest.fixture(autouse=True)
def usage_rows(monkeypatch):
    """Model calls in tests are fakes: their usage rows are collected here instead of reaching a database."""
    from athena.core import usage
    written: list[dict] = []
    monkeypatch.setattr(usage, "_write", written.extend)
    yield written
    usage.flush()
