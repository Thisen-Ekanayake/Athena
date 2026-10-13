"""API tests for the evolution tools (ROADMAP E1-E9), with the database layer mocked."""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from athena.api.deps import get_db, get_redis
from athena.api.main import app
from tests.conftest import ADMIN
from tests.fakes import FakeRedis

ROUTER_DB = "athena.api.routers.evolution.db"
TOPIC = SimpleNamespace(id=uuid4(), slug="object-detection", name="Object detection", built_at=datetime(2026, 10, 12),
                        status="ready", origin="curated", status_detail=None, config={})
USER = SimpleNamespace(**{**{c: getattr(ADMIN, c) for c in ("id", "email", "display_name", "is_active")},
                          "role": "user", "must_change_password": False})


@pytest.fixture
def client():
    redis = FakeRedis()
    app.dependency_overrides[get_db] = lambda: None
    app.dependency_overrides[get_redis] = lambda: redis
    yield TestClient(app), redis
    app.dependency_overrides.clear()


def as_user():
    """Log in as an ordinary user (limits apply) instead of the admin from conftest."""
    from athena.api.auth import active_user, current_user
    app.dependency_overrides[current_user] = lambda: USER
    app.dependency_overrides[active_user] = lambda: USER


def path_payload(*whys):
    step = {"id": str(uuid4()), "why": None, "read": False, "builds_on": [], "addresses": []}
    return {"topic": {}, "n": 10, "survey": None, "other_surveys": [], "read_count": 0, "total": len(whys),
            "steps": [step | {"id": str(uuid4()), "why": w} for w in whys]}


# ── E1 reading path ────────────────────────────────────────────────────


def test_reading_path_writes_missing_notes_after_responding(client):
    c, redis = client
    with patch(f"{ROUTER_DB}.get_topic", return_value=TOPIC), \
            patch(f"{ROUTER_DB}.reading_path", return_value=path_payload("Known.", None)) as build, \
            patch("athena.evolution.notes.write_notes") as write:
        body = c.get("/api/v1/evolution/topics/object-detection/reading-path", params={"n": 12}).json()
    assert body["notes_pending"] is True and body["notes_error"] is None
    assert build.call_args.args[2:] == (ADMIN.id, 12)
    write.assert_called_once()
    assert write.call_args.args[0] == "object-detection" and len(write.call_args.args[1]) == 2


def test_reading_path_does_not_write_twice_at_once(client):
    c, redis = client
    redis.set("evo:notes:object-detection", "1")
    with patch(f"{ROUTER_DB}.get_topic", return_value=TOPIC), \
            patch(f"{ROUTER_DB}.reading_path", return_value=path_payload(None)), \
            patch("athena.evolution.notes.write_notes") as write:
        body = c.get("/api/v1/evolution/topics/object-detection/reading-path").json()
    assert body["notes_pending"] is True
    write.assert_not_called()


def test_empty_notes_are_not_asked_for_again(client):
    c, _ = client
    with patch(f"{ROUTER_DB}.get_topic", return_value=TOPIC), \
            patch(f"{ROUTER_DB}.reading_path", return_value=path_payload("Known.", "")), \
            patch("athena.evolution.notes.write_notes") as write:
        body = c.get("/api/v1/evolution/topics/object-detection/reading-path").json()
    assert body["notes_pending"] is False
    write.assert_not_called()


def test_a_recent_failure_stops_the_polling(client):
    c, redis = client
    redis.set("evo:notes:failed:object-detection", "No model server")
    with patch(f"{ROUTER_DB}.get_topic", return_value=TOPIC), \
            patch(f"{ROUTER_DB}.reading_path", return_value=path_payload(None)), \
            patch("athena.evolution.notes.write_notes") as write:
        body = c.get("/api/v1/evolution/topics/object-detection/reading-path").json()
    assert body["notes_pending"] is False and body["notes_error"] == "No model server"
    write.assert_not_called()


def test_reading_path_of_an_unbuilt_map_is_409(client):
    c, _ = client
    with patch(f"{ROUTER_DB}.get_topic", return_value=SimpleNamespace(**{**vars(TOPIC), "built_at": None})):
        assert c.get("/api/v1/evolution/topics/object-detection/reading-path").status_code == 409


def test_reading_path_bounds_n(client):
    c, _ = client
    assert c.get("/api/v1/evolution/topics/object-detection/reading-path", params={"n": 2}).status_code == 422
    assert c.get("/api/v1/evolution/topics/object-detection/reading-path", params={"n": 31}).status_code == 422


def test_read_ticks_are_per_user(client):
    c, _ = client
    as_user()
    paper_id = uuid4()
    with patch(f"{ROUTER_DB}.set_read", return_value=True) as set_read:
        assert c.put(f"/api/v1/evolution/papers/{paper_id}/read").status_code == 204
        assert c.delete(f"/api/v1/evolution/papers/{paper_id}/read").status_code == 204
    calls = [call.args[1:] for call in set_read.call_args_list]
    assert calls == [(USER.id, paper_id, True), (USER.id, paper_id, False)]
    with patch(f"{ROUTER_DB}.set_read", return_value=False):
        assert c.put(f"/api/v1/evolution/papers/{paper_id}/read").status_code == 404


# ── E6 exports ─────────────────────────────────────────────────────────


def test_export_milestones_as_bibtex(client):
    c, _ = client
    paper = {"id": "1", "title": "Fast R-CNN", "year": 2015, "authors": ["Ross Girshick"], "venue": None,
             "doi": None, "arxiv_id": "1504.08083", "url": "https://arxiv.org/abs/1504.08083"}
    with patch(f"{ROUTER_DB}.get_topic", return_value=TOPIC), patch(f"{ROUTER_DB}.milestone_ids", return_value=[1]), \
            patch(f"{ROUTER_DB}.export_papers", return_value=[paper]):
        resp = c.get("/api/v1/evolution/topics/object-detection/export", params={"what": "milestones", "format": "bib"})
    assert resp.status_code == 200
    assert resp.headers["content-disposition"] == 'attachment; filename="object-detection-milestones.bib"'
    assert resp.text.startswith("@misc{girshick2015fast,")


def test_export_rejects_formats_that_do_not_fit(client):
    c, _ = client
    resp = c.get("/api/v1/evolution/topics/object-detection/export", params={"what": "gaps", "format": "bib"})
    assert resp.status_code == 422


# ── E8 people ──────────────────────────────────────────────────────────


def test_people_are_served_and_cached(client):
    c, _ = client
    payload = {"topic": {}, "eras": [], "overall": {"authors": [], "labs": []}, "milestones": [], "papers": 0,
               "papers_with_ids": 0}
    with patch(f"{ROUTER_DB}.get_topic", return_value=TOPIC), patch(f"{ROUTER_DB}.labels_version", return_value="0"), \
            patch(f"{ROUTER_DB}.topic_people", return_value=payload) as build:
        assert c.get("/api/v1/evolution/topics/object-detection/people").json() == payload
        assert c.get("/api/v1/evolution/topics/object-detection/people").json() == payload
    assert build.call_count == 1


# ── E5 the feed and the maps ───────────────────────────────────────────


def test_feed_item_place(client):
    c, _ = client
    item_id = uuid4()
    place = {"item_id": str(item_id), "places": [], "cites": [{"topic": "peft"}], "maps_cited": {"peft": 1},
             "references": 30, "checked_at": None}
    with patch(f"{ROUTER_DB}.feed_place", return_value=place) as read:
        assert c.get(f"/api/v1/evolution/items/{item_id}").json() == place
    assert read.call_args.args[1] == item_id
    with patch(f"{ROUTER_DB}.feed_place", return_value=None):
        assert c.get(f"/api/v1/evolution/items/{item_id}").status_code == 404


def test_new_papers_for_one_map(client):
    c, _ = client
    with patch(f"{ROUTER_DB}.new_feed_papers", return_value=[]) as read:
        assert c.get("/api/v1/evolution/new-papers", params={"days": 14, "topic": "peft"}).json() == []
    assert read.call_args.args[1:] == (14, "peft")
