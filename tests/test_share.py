"""Shared maps (ROADMAP R2): making and revoking links, the admin switch, and the read-only routes without a login."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import ARRAY, create_engine, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from athena.api.deps import get_db, get_redis
from athena.api.main import app
from athena.api.routers import share as share_routes
from athena.core.models import AppSetting, EvoTopic, MapShare, SavedList, SavedListItem, User, UserSession
from athena.database import shares
from tests.fakes import FakeRedis
from tests.test_auth import make_user, setup_admin

pytestmark = pytest.mark.real_auth


@compiles(JSONB, "sqlite")
@compiles(ARRAY, "sqlite")
def _as_json(type_, compiler, **kw):  # the map tables use Postgres types; SQLite stores them as JSON
    return "JSON"


@pytest.fixture
def env(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    for model in (User, UserSession, SavedList, SavedListItem, EvoTopic, MapShare, AppSetting):
        model.__table__.create(engine)
    Session = sessionmaker(bind=engine)
    settings: dict[str, str] = {}
    monkeypatch.setattr(shares, "get_setting", lambda key, default="": settings.get(key, default))

    def session():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    redis = FakeRedis()
    app.dependency_overrides[get_db] = session
    app.dependency_overrides[get_redis] = lambda: redis
    with Session() as s:
        for slug, status, built in (("peft", "ready", True), ("rag", "building", False)):
            # Core, not the ORM: an explicit None keeps the list columns' Python defaults out of SQLite.
            s.execute(EvoTopic.__table__.insert().values(
                id=uuid4(), slug=slug, name=slug.upper(), status=status, origin="search", query=slug, aliases=None,
                seeds=None, config=None, build_stats={"papers": 300},
                built_at=datetime(2026, 10, 1, tzinfo=timezone.utc) if built else None))
        s.commit()
    yield Session, settings, redis
    app.dependency_overrides.clear()


def admin_client():
    c = TestClient(app)
    assert setup_admin(c).status_code == 201
    return c


def make_link(c, slug="peft", **body):
    return c.post(f"/api/v1/evolution/topics/{slug}/shares", json=body)


# ── making links ─────────────────────────────────────────────────────


def test_any_user_can_share_a_built_map(env):
    admin = admin_client()
    _, bo = make_user(admin)
    resp = make_link(bo, expires_days=30)
    assert resp.status_code == 201
    link = resp.json()
    assert len(link["token"]) >= 20 and link["creator"] == "Bo" and link["views"] == 0
    expires = datetime.fromisoformat(link["expires_at"])
    assert timedelta(days=29) < expires - datetime.now(timezone.utc) <= timedelta(days=30)


def test_an_unbuilt_map_cannot_be_shared(env):
    assert make_link(admin_client(), "rag").status_code == 409


def test_expiry_is_one_of_the_offered_lengths(env):
    assert make_link(admin_client(), expires_days=12).status_code == 422


def test_people_see_their_own_links_and_admins_see_all(env):
    admin = admin_client()
    _, bo = make_user(admin)
    make_link(admin)
    make_link(bo)
    assert len(bo.get("/api/v1/evolution/topics/peft/shares").json()["shares"]) == 1
    assert len(admin.get("/api/v1/evolution/topics/peft/shares").json()["shares"]) == 2
    everything = admin.get("/api/v1/evolution/shares").json()["shares"]
    assert {s["topic"]["slug"] for s in everything} == {"peft"}


def test_only_the_maker_or_an_admin_can_revoke(env):
    admin = admin_client()
    _, bo = make_user(admin)
    _, cy = make_user(admin, email="cy@example.com")
    mine = make_link(bo).json()
    assert cy.delete(f"/api/v1/evolution/shares/{mine['id']}").status_code == 403
    assert bo.delete(f"/api/v1/evolution/shares/{mine['id']}").status_code == 204
    assert bo.delete(f"/api/v1/evolution/shares/{mine['id']}").status_code == 404  # already gone
    theirs = make_link(bo).json()
    assert admin.delete(f"/api/v1/evolution/shares/{theirs['id']}").status_code == 204
    assert bo.get("/api/v1/evolution/topics/peft/shares").json()["shares"] == []


def test_only_admins_switch_sharing_and_switched_off_means_no_new_links(env):
    _, settings, _ = env
    admin = admin_client()
    _, bo = make_user(admin)
    with patch("athena.api.routers.evolution.sharing.set_setting", side_effect=settings.__setitem__):
        assert bo.put("/api/v1/evolution/sharing", json={"enabled": False}).status_code == 403
        assert admin.put("/api/v1/evolution/sharing", json={"enabled": False}).status_code == 200
    assert bo.get("/api/v1/evolution/sharing").json() == {"enabled": False}
    assert make_link(bo).status_code == 403


def test_making_a_link_needs_an_account(env):
    admin_client()
    assert make_link(TestClient(app)).status_code == 401


# ── opening a link ───────────────────────────────────────────────────


def anonymous():
    return TestClient(app)  # no cookie


def test_anyone_with_the_link_can_open_the_map_without_its_builders_details(env):
    token = make_link(admin_client()).json()["token"]
    resp = anonymous().get(f"/api/v1/share/{token}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["slug"] == "peft" and body["name"] == "PEFT"
    assert not {"created_by", "build_stats", "query"} & set(body)
    assert body["shared"]["expires_at"] is None


def test_opening_a_link_counts_a_view_and_polling_does_not(env):
    Session, _, _ = env
    token = make_link(admin_client()).json()["token"]
    c = anonymous()
    for _ in range(2):
        assert c.post(f"/api/v1/share/{token}/view").status_code == 204
        c.get(f"/api/v1/share/{token}")
    with Session() as s:
        assert s.execute(select(MapShare.views)).scalar_one() == 2


@pytest.mark.parametrize("change", ["revoked", "expired", "sharing_off", "unknown"])
def test_a_dead_link_is_not_found(env, change):
    Session, settings, _ = env
    token = make_link(admin_client()).json()["token"]
    with Session() as s:
        share = s.execute(select(MapShare)).scalar_one()
        if change == "revoked":
            share.revoked_at = datetime.now(timezone.utc)
        elif change == "expired":
            share.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        s.commit()
    if change == "sharing_off":
        settings["SHARING_ENABLED"] = "false"
    resp = anonymous().get(f"/api/v1/share/{'nope' if change == 'unknown' else token}")
    assert resp.status_code == 404 and "expired" in resp.json()["detail"]


def test_the_map_routes_answer_as_the_map_does_without_private_fields(env):
    token = make_link(admin_client()).json()["token"]
    graph = {"topic": {"slug": "peft", "created_by": "someone", "build_stats": {}}, "nodes": [1], "edges": []}
    with patch.object(share_routes.graph, "topic_graph", return_value=graph) as built:
        body = anonymous().get(f"/api/v1/share/{token}/graph", params={"limit": 600}).json()
    assert built.call_args.args[:2] == ("peft", 600)
    assert body["nodes"] == [1] and body["topic"] == {"slug": "peft"}
    assert anonymous().get(f"/api/v1/share/{token}/graph", params={"limit": 2000}).status_code == 422
    with patch.object(share_routes.graph, "topic_graph", return_value=graph) as built:
        assert anonymous().get(f"/api/v1/share/{token}/graph", params={"limit": 0}).status_code == 200  # "All"
    assert built.call_args.args[:2] == ("peft", 0)


def test_the_reading_path_has_no_reader_and_never_asks_the_model(env):
    token = make_link(admin_client()).json()["token"]
    path = {"topic": {"slug": "peft"}, "survey": None, "steps": [{"id": str(uuid4()), "why": None}]}
    with patch("athena.api.routers.share.db.reading_path", return_value=path) as build, \
            patch("athena.evolution.notes.write_notes") as write:
        body = anonymous().get(f"/api/v1/share/{token}/reading-path", params={"n": 12}).json()
    assert build.call_args.args[2:] == (None, 12)
    assert body["notes_pending"] is False
    write.assert_not_called()


def test_changes_leave_out_the_upkeep_settings(env):
    token = make_link(admin_client()).json()["token"]
    changes = {"topic": {"slug": "peft"}, "refresh_days": 30, "snapshots": [{"id": "s1"}]}
    with patch("athena.api.routers.share.db.topic_changes", return_value=changes):
        body = anonymous().get(f"/api/v1/share/{token}/changes").json()
    assert body == {"topic": {"slug": "peft"}, "snapshots": [{"id": "s1"}]}


def test_exports_need_no_reader(env):
    token = make_link(admin_client()).json()["token"]
    with patch.object(share_routes.reading, "export_file", return_value={"ok": True}) as export:
        anonymous().get(f"/api/v1/share/{token}/export", params={"what": "milestones", "format": "bib"})
    assert export.call_args.args[2:] == ("milestones", "bib", 10)  # no user


def test_questions_follows_and_other_maps_stay_behind_the_login(env):
    admin_client()
    c = anonymous()
    assert c.post("/api/v1/evolution/topics/peft/ask", json={"question": "why?"}).status_code == 401
    assert c.get("/api/v1/evolution/topics/peft/graph").status_code == 401
    assert c.get("/api/v1/watches").status_code == 401


def test_anonymous_traffic_is_rate_limited(env, monkeypatch):
    monkeypatch.setattr(share_routes, "RATE_LIMIT", 3)
    token = make_link(admin_client()).json()["token"]
    codes = [anonymous().get(f"/api/v1/share/{token}").status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]
