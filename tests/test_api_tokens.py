"""Access tokens for agents: made and revoked in a browser session, shown once, valid only on the MCP server's
in-process calls (scope key ``auth.AGENT``), never on the REST API from outside."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from athena.api import auth
from athena.api.deps import get_db, get_redis
from athena.api.main import app
from athena.core.models import ApiToken, SavedList, SavedListItem, User, UserSession
from tests.test_auth import FakeRedis, make_user, setup_admin

pytestmark = pytest.mark.real_auth


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    for table in (User.__table__, UserSession.__table__, ApiToken.__table__, SavedList.__table__,
                  SavedListItem.__table__):
        table.create(engine)
    Session = sessionmaker(bind=engine)

    def override():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override
    app.dependency_overrides[get_redis] = lambda: FakeRedis()
    yield Session
    app.dependency_overrides.clear()


async def as_agent(scope, receive, send):
    """What athena/mcp/api.py does: the same app, with the agent mark in the scope."""
    scope[auth.AGENT] = True
    await app(scope, receive, send)


def agent(token: str | None) -> TestClient:
    return TestClient(as_agent, headers={"Authorization": f"Bearer {token}"} if token else {})


def admin_with_token(name="Claude Code", **extra) -> tuple[TestClient, dict]:
    c = TestClient(app)
    setup_admin(c)
    made = c.post("/api/v1/tokens", json={"name": name, **extra})
    assert made.status_code == 201
    return c, made.json()


def test_a_token_is_shown_once_and_listed_without_it(db):
    c, made = admin_with_token()
    assert made["token"].startswith("ath_") and made["hint"] == made["token"][:8]
    listed = c.get("/api/v1/tokens").json()
    assert [t["name"] for t in listed] == ["Claude Code"] and "token" not in listed[0]
    with db() as s:
        row = s.query(ApiToken).one()
        assert made["token"] not in (row.token_hash, row.hint)


def test_the_token_works_on_the_mcp_servers_calls(db):
    _, made = admin_with_token()
    me = agent(made["token"]).get("/api/v1/auth/me")
    assert me.status_code == 200 and me.json()["display_name"] == "Ada"
    with db() as s:
        assert s.query(ApiToken).one().last_used_at is not None


def test_the_token_does_nothing_on_the_rest_api_from_outside(db):
    _, made = admin_with_token()
    outside = TestClient(app, headers={"Authorization": f"Bearer {made['token']}"})
    assert outside.get("/api/v1/auth/me").status_code == 401
    assert outside.get("/api/v1/lists").status_code == 401


def test_an_agent_call_does_not_take_a_cookie(db):
    c, _ = admin_with_token()
    cookie = c.cookies.get(auth.COOKIE)
    assert TestClient(as_agent, cookies={auth.COOKIE: cookie}).get("/api/v1/auth/me").status_code == 401
    assert agent("ath_made-up").get("/api/v1/auth/me").status_code == 401
    assert agent(None).get("/api/v1/auth/me").status_code == 401


def test_a_revoked_or_expired_token_stops_working(db):
    c, made = admin_with_token()
    assert c.delete(f"/api/v1/tokens/{made['id']}").status_code == 204
    assert agent(made["token"]).get("/api/v1/auth/me").status_code == 401

    made = c.post("/api/v1/tokens", json={"name": "Old", "expires_days": 1}).json()
    with db() as s:
        row = s.get(ApiToken, UUID(made["id"]))
        row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        s.commit()
    assert agent(made["token"]).get("/api/v1/auth/me").status_code == 401


def test_a_deactivated_account_takes_its_tokens_with_it(db):
    admin, _ = admin_with_token()
    bo, bo_client = make_user(admin)
    token = bo_client.post("/api/v1/tokens", json={"name": "Bo's agent"}).json()["token"]
    assert agent(token).get("/api/v1/auth/me").json()["email"] == "bo@example.com"
    assert admin.patch(f"/api/v1/users/{bo['id']}", json={"is_active": False}).status_code == 200
    assert agent(token).get("/api/v1/auth/me").status_code == 401


def test_tokens_are_your_own_and_an_agent_cannot_manage_them(db):
    admin, made = admin_with_token()
    _, bo_client = make_user(admin)
    assert bo_client.get("/api/v1/tokens").json() == []
    assert bo_client.delete(f"/api/v1/tokens/{made['id']}").status_code == 404
    a = agent(made["token"])
    assert a.get("/api/v1/tokens").status_code == 403
    assert a.post("/api/v1/tokens", json={"name": "More"}).status_code == 403
