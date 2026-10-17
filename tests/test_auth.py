"""Accounts: first-admin setup, sessions in a cookie, roles, per-user saved lists and daily limits."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from athena.api import auth
from athena.api.deps import get_db, get_redis
from athena.api.main import app
from athena.core.models import (
    InterestProfile, ItemFeedback, ItemRead, SavedList, SavedListItem, User, UserHighlight, UserNote, UserSession,
)

pytestmark = pytest.mark.real_auth


class FakeRedis:
    def __init__(self):
        self.store: dict[str, str] = {}

    def get(self, key):
        return self.store.get(key)

    def setex(self, key, ttl, value):
        self.store[key] = value

    def incr(self, key):
        self.store[key] = str(int(self.store.get(key, 0)) + 1)
        return int(self.store[key])

    def expire(self, key, ttl):
        return True

    def delete(self, *keys):
        for k in keys:
            self.store.pop(k, None)


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    tables = [User.__table__, UserSession.__table__, SavedList.__table__, SavedListItem.__table__,
              ItemRead.__table__, UserNote.__table__, UserHighlight.__table__, ItemFeedback.__table__,
              InterestProfile.__table__]
    for table in tables:
        table.create(engine)
    Session = sessionmaker(bind=engine)

    def override():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    redis = FakeRedis()
    app.dependency_overrides[get_db] = override
    app.dependency_overrides[get_redis] = lambda: redis
    yield Session, redis
    app.dependency_overrides.clear()


def client() -> TestClient:
    return TestClient(app)


def setup_admin(c: TestClient):
    body = {"email": "Admin@Example.com", "display_name": "Ada", "password": "correct horse"}
    return c.post("/api/v1/auth/setup", json=body)


def make_user(admin: TestClient, email="bo@example.com", role="user") -> tuple[dict, TestClient]:
    """Create an account as the admin, then log it in and replace the temporary password."""
    made = admin.post("/api/v1/users", json={"email": email, "display_name": "Bo", "role": role}).json()
    c = client()
    login = {"email": email, "password": made["temporary_password"]}
    assert c.post("/api/v1/auth/login", json=login).status_code == 200
    assert c.post("/api/v1/auth/password", json={"current_password": made["temporary_password"],
                                                 "new_password": "battery staple"}).status_code == 200
    return made, c


class TestSetupAndLogin:
    def test_first_visit_creates_the_admin_once(self, db):
        c = client()
        assert c.get("/api/v1/auth/status").json() == {"needs_setup": True, "user": None}
        r = setup_admin(c)
        assert r.status_code == 201 and r.json()["role"] == "admin" and r.json()["email"] == "admin@example.com"
        assert c.get("/api/v1/auth/me").json()["display_name"] == "Ada"  # the setup logged in
        assert setup_admin(client()).status_code == 409

    def test_setup_hands_old_saved_lists_to_the_admin(self, db):
        Session, _ = db
        with Session() as s:
            s.add(SavedList(name="From before accounts"))
            s.commit()
        c = client()
        setup_admin(c)
        assert [lst["name"] for lst in c.get("/api/v1/lists").json()] == ["From before accounts"]

    def test_short_passwords_and_bad_emails_are_refused(self, db):
        c = client()
        assert c.post("/api/v1/auth/setup", json={"email": "a@b.co", "display_name": "A",
                                                  "password": "short"}).status_code == 422
        assert c.post("/api/v1/auth/setup", json={"email": "not-an-email", "display_name": "A",
                                                  "password": "long enough"}).status_code == 422

    def test_login_logout_and_the_cookie(self, db):
        setup_admin(client())
        c = client()
        assert c.get("/api/v1/feed").status_code == 401
        assert c.post("/api/v1/auth/login", json={"email": "admin@example.com", "password": "nope"}).status_code == 401
        r = c.post("/api/v1/auth/login", json={"email": " ADMIN@example.com ", "password": "correct horse"})
        assert r.status_code == 200
        cookie = r.headers["set-cookie"].lower()
        assert auth.COOKIE in cookie and "httponly" in cookie and "samesite=lax" in cookie
        assert c.get("/api/v1/auth/me").status_code == 200
        assert c.post("/api/v1/auth/logout").status_code == 204
        assert c.get("/api/v1/auth/me").status_code == 401

    def test_the_cookie_is_secure_over_https(self, db):
        """Behind nginx, uvicorn takes the scheme from X-Forwarded-Proto; the cookie follows the scheme."""
        setup_admin(client())
        body = {"email": "admin@example.com", "password": "correct horse"}
        plain = client().post("/api/v1/auth/login", json=body)
        assert "secure" not in plain.headers["set-cookie"].lower()
        https = TestClient(app, base_url="https://testserver").post("/api/v1/auth/login", json=body)
        assert https.status_code == 200 and "secure" in https.headers["set-cookie"].lower()

    def test_only_the_token_hash_is_stored(self, db):
        Session, _ = db
        c = client()
        setup_admin(c)
        token = c.cookies.get(auth.COOKIE)
        with Session() as s:
            stored = s.query(UserSession).one().token_hash
        assert token and stored != token and len(stored) == 64

    def test_repeated_failures_are_slowed_down(self, db):
        setup_admin(client())
        c = client()
        for _ in range(10):
            c.post("/api/v1/auth/login", json={"email": "admin@example.com", "password": "wrong"})
        r = c.post("/api/v1/auth/login", json={"email": "admin@example.com", "password": "correct horse"})
        assert r.status_code == 429


class TestAccounts:
    def test_a_temporary_password_must_be_replaced_first(self, db):
        admin = client()
        setup_admin(admin)
        made = admin.post("/api/v1/users", json={"email": "bo@example.com", "display_name": "Bo"}).json()
        assert made["must_change_password"] and len(made["temporary_password"]) >= 8
        c = client()
        c.post("/api/v1/auth/login", json={"email": "bo@example.com", "password": made["temporary_password"]})
        r = c.get("/api/v1/lists")
        assert r.status_code == 403 and r.json()["detail"] == auth.PASSWORD_CHANGE_REQUIRED
        assert c.post("/api/v1/auth/password", json={"current_password": made["temporary_password"],
                                                     "new_password": "battery staple"}).status_code == 200
        assert c.get("/api/v1/lists").status_code == 200

    def test_users_cannot_reach_admin_routes(self, db):
        admin = client()
        setup_admin(admin)
        _, bo = make_user(admin)
        assert bo.get("/api/v1/users").status_code == 403
        assert bo.get("/api/v1/settings/models").status_code == 403
        assert bo.post("/api/v1/sync").status_code == 403
        assert bo.delete("/api/v1/evolution/topics/some-map").status_code == 403
        assert admin.get("/api/v1/users").status_code == 200

    def test_deactivating_ends_the_sessions(self, db):
        admin = client()
        setup_admin(admin)
        made, bo = make_user(admin)
        assert admin.patch(f"/api/v1/users/{made['id']}", json={"is_active": False}).status_code == 200
        assert bo.get("/api/v1/auth/me").status_code == 401
        assert client().post("/api/v1/auth/login", json={"email": "bo@example.com",
                                                         "password": "battery staple"}).status_code == 401

    def test_reset_password_ends_sessions_and_issues_a_new_temporary_one(self, db):
        admin = client()
        setup_admin(admin)
        made, bo = make_user(admin)
        reset = admin.post(f"/api/v1/users/{made['id']}/reset-password").json()
        assert reset["must_change_password"] and reset["temporary_password"] != made["temporary_password"]
        assert bo.get("/api/v1/auth/me").status_code == 401

    def test_the_last_admin_stays_an_admin(self, db):
        admin = client()
        me = setup_admin(admin).json()
        assert admin.patch(f"/api/v1/users/{me['id']}", json={"role": "user"}).status_code == 409
        assert admin.patch(f"/api/v1/users/{me['id']}", json={"is_active": False}).status_code == 409
        make_user(admin, "second@example.com", role="admin")
        assert admin.patch(f"/api/v1/users/{me['id']}", json={"role": "user"}).status_code == 200

    def test_emails_are_unique(self, db):
        admin = client()
        setup_admin(admin)
        admin.post("/api/v1/users", json={"email": "bo@example.com", "display_name": "Bo"})
        r = admin.post("/api/v1/users", json={"email": "BO@example.com", "display_name": "Bo again"})
        assert r.status_code == 409


class TestPerUserData:
    def test_saved_lists_belong_to_one_user(self, db):
        admin = client()
        setup_admin(admin)
        _, bo = make_user(admin)
        mine = admin.post("/api/v1/lists", json={"name": "Reading"}).json()
        assert bo.post("/api/v1/lists", json={"name": "Reading"}).status_code == 201  # names are per user
        assert [lst["name"] for lst in bo.get("/api/v1/lists").json()] == ["Reading"]
        assert bo.patch(f"/api/v1/lists/{mine['id']}", json={"name": "Mine now"}).status_code == 404
        assert bo.delete(f"/api/v1/lists/{mine['id']}").status_code == 404
        assert bo.delete(f"/api/v1/lists/{mine['id']}/items/{mine['id']}").status_code == 404
        assert admin.get("/api/v1/lists").json()[0]["name"] == "Reading"

    def test_daily_limits_apply_to_users_not_admins(self, db, monkeypatch):
        monkeypatch.setenv("LIMIT_MAP_PROPOSAL_PER_DAY", "2")
        admin = client()
        setup_admin(admin)
        _, bo = make_user(admin)
        empty = {"id": "f" * 32, "query": "x", "candidates": []}
        with patch("athena.api.routers.evolution.topics.proposals.propose", side_effect=lambda q: dict(empty)):
            codes = [bo.post("/api/v1/evolution/proposals", json={"query": "object tracking"}).status_code
                     for _ in range(3)]
            assert codes == [200, 200, 429]
            assert all(admin.post("/api/v1/evolution/proposals", json={"query": "object tracking"}).status_code
                       == 200 for _ in range(3))


class TestOnboarding:
    def test_new_accounts_start_without_the_guide_done(self, db):
        admin = client()
        assert setup_admin(admin).json()["onboarded_at"] is None
        _, bo = make_user(admin)
        assert bo.get("/api/v1/auth/status").json()["user"]["onboarded_at"] is None

    def test_finishing_or_skipping_puts_the_guide_away_and_it_can_come_back(self, db):
        c = client()
        setup_admin(c)
        assert c.post("/api/v1/auth/onboarding", json={"done": True}).json()["onboarded_at"] is not None
        assert c.get("/api/v1/auth/status").json()["user"]["onboarded_at"] is not None
        assert c.post("/api/v1/auth/onboarding", json={"done": False}).json()["onboarded_at"] is None

    def test_the_guide_waits_for_a_temporary_password_to_be_replaced(self, db):
        admin = client()
        setup_admin(admin)
        made = admin.post("/api/v1/users", json={"email": "cy@example.com", "display_name": "Cy"}).json()
        c = client()
        c.post("/api/v1/auth/login", json={"email": "cy@example.com", "password": made["temporary_password"]})
        assert c.post("/api/v1/auth/onboarding", json={"done": True}).status_code == 403
        assert client().post("/api/v1/auth/onboarding", json={"done": True}).status_code == 401

    def test_accounts_from_before_the_guide_are_marked_once(self, db):
        from athena.api.migrations import add_release
        Session, _ = db
        c = client()
        setup_admin(c)
        settings: dict[str, str] = {}
        with patch.object(add_release, "engine", Session.kw["bind"]), \
                patch("athena.core.config_store.get_setting", lambda k, d="": settings.get(k, d)), \
                patch("athena.core.config_store.set_setting", side_effect=settings.__setitem__):
            assert add_release.mark_existing_accounts() == 1
            _, bo = make_user(c)  # made after the release: sees the guide
            assert add_release.mark_existing_accounts() == 0
        assert c.get("/api/v1/auth/status").json()["user"]["onboarded_at"] is not None
        assert bo.get("/api/v1/auth/status").json()["user"]["onboarded_at"] is None
