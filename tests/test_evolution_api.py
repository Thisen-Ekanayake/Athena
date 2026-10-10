"""Tests for the /api/v1/evolution endpoints (database layer mocked)."""
from __future__ import annotations

import fnmatch
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from athena.api.deps import get_db, get_redis
from athena.api.main import app

ROUTER_DB = "athena.api.routers.evolution.db"
TOPIC = SimpleNamespace(slug="object-detection", name="Object detection", built_at=None)
SUMMARY = {"slug": "object-detection", "name": "Object detection", "status": "ready"}


class FakeRedis:
    def __init__(self):
        self.store: dict[str, str] = {}

    def get(self, key):
        return self.store.get(key)

    def setex(self, key, ttl, value):
        self.store[key] = value

    def scan_iter(self, match, count=100):
        return [k for k in list(self.store) if fnmatch.fnmatch(k, match)]

    def delete(self, *keys):
        for k in keys:
            self.store.pop(k, None)
        return len(keys)


@pytest.fixture
def client():
    redis = FakeRedis()
    app.dependency_overrides[get_db] = lambda: None
    app.dependency_overrides[get_redis] = lambda: redis
    yield TestClient(app), redis
    app.dependency_overrides.clear()


def test_search_finds_a_topic(client):
    c, _ = client
    with patch(f"{ROUTER_DB}.find_topic", return_value=TOPIC), \
            patch(f"{ROUTER_DB}.topic_summary", return_value=SUMMARY):
        body = c.get("/api/v1/evolution/search", params={"q": "yolo"}).json()
    assert body["found"] is True
    assert body["topic"]["slug"] == "object-detection"


def test_search_says_when_a_topic_is_not_in_the_system(client):
    c, _ = client
    with patch(f"{ROUTER_DB}.find_topic", return_value=None), \
            patch(f"{ROUTER_DB}.list_topics", return_value=[SUMMARY]):
        body = c.get("/api/v1/evolution/search", params={"q": "protein folding"}).json()
    assert body["found"] is False
    assert "not in the system" in body["message"]
    assert body["available"] == ["Object detection"]


def test_unknown_topic_is_404(client):
    c, _ = client
    with patch(f"{ROUTER_DB}.get_topic", return_value=None):
        assert c.get("/api/v1/evolution/topics/nope/graph").status_code == 404


def test_graph_is_cached(client):
    c, _ = client
    payload = {"topic": SUMMARY, "nodes": [], "edges": [], "total_papers": 0, "year_range": None}
    with patch(f"{ROUTER_DB}.get_topic", return_value=TOPIC), \
            patch(f"{ROUTER_DB}.topic_graph", return_value=payload) as build:
        c.get("/api/v1/evolution/topics/object-detection/graph")
        c.get("/api/v1/evolution/topics/object-detection/graph")
    assert build.call_count == 1


def test_pin_invalidates_the_topic_cache(client):
    c, redis = client
    redis.store["evo:object-detection:graph:250:unbuilt"] = "{}"
    paper_id = uuid4()
    with patch(f"{ROUTER_DB}.get_topic", return_value=TOPIC), \
            patch(f"{ROUTER_DB}.set_override", return_value=True) as set_override, \
            patch(f"{ROUTER_DB}.paper_detail", return_value={"id": str(paper_id), "is_milestone": True}):
        resp = c.post(f"/api/v1/evolution/topics/object-detection/milestones/{paper_id}",
                      json={"action": "pin", "note": "On the survey roadmap"})
    assert resp.status_code == 200
    assert set_override.call_args.args[2:] == (paper_id, "pin", "On the survey roadmap")
    assert redis.store == {}


def test_milestone_override_rejects_unknown_actions(client):
    c, _ = client
    resp = c.post(f"/api/v1/evolution/topics/object-detection/milestones/{uuid4()}", json={"action": "promote"})
    assert resp.status_code == 422


def test_milestone_override_for_a_paper_outside_the_topic_is_404(client):
    c, _ = client
    with patch(f"{ROUTER_DB}.get_topic", return_value=TOPIC), patch(f"{ROUTER_DB}.set_override", return_value=False):
        resp = c.post(f"/api/v1/evolution/topics/object-detection/milestones/{uuid4()}", json={"action": "unpin"})
    assert resp.status_code == 404
