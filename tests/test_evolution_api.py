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
TOPIC = SimpleNamespace(slug="object-detection", name="Object detection", built_at=None, status="ready",
                        origin="curated", status_detail=None)
SEARCH_TOPIC = SimpleNamespace(slug="object-tracking", name="Object tracking", built_at=None, status="ready",
                               origin="search", status_detail=None)
ROUTER = "athena.api.routers.evolution"
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


def test_search_falls_back_to_the_papers_content(client):
    c, _ = client
    match = {"method": "text", "matching_papers": 40, "ranking": []}
    with patch(f"{ROUTER_DB}.find_topic", return_value=None), \
            patch("athena.api.routers.evolution.find_topic_by_content", return_value=(TOPIC, match)), \
            patch(f"{ROUTER_DB}.topic_summary", return_value=SUMMARY):
        body = c.get("/api/v1/evolution/search", params={"q": "anchor-free detectors"}).json()
    assert body["found"] is True and body["match"]["method"] == "text"


def test_search_says_when_a_topic_is_not_in_the_system(client):
    c, _ = client
    with patch(f"{ROUTER_DB}.find_topic", return_value=None), \
            patch("athena.api.routers.evolution.find_topic_by_content", return_value=(None, {"method": "text"})), \
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
            patch(f"{ROUTER_DB}.labels_version", return_value="0-0"), \
            patch(f"{ROUTER_DB}.topic_graph", return_value=payload) as build:
        c.get("/api/v1/evolution/topics/object-detection/graph")
        c.get("/api/v1/evolution/topics/object-detection/graph")
    assert build.call_count == 1


def test_new_labels_refresh_the_cached_graph(client):
    # Strict links arrive from the GPU lane without a rebuild, so built_at alone would serve stale edges.
    c, _ = client
    payload = {"topic": SUMMARY, "nodes": [], "edges": [], "total_papers": 0, "year_range": None}
    with patch(f"{ROUTER_DB}.get_topic", return_value=TOPIC), \
            patch(f"{ROUTER_DB}.labels_version", side_effect=["10-100", "12-160"]), \
            patch(f"{ROUTER_DB}.topic_graph", return_value=payload) as build:
        c.get("/api/v1/evolution/topics/object-detection/graph")
        c.get("/api/v1/evolution/topics/object-detection/graph")
    assert build.call_count == 2


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


def test_gaps_are_served_and_cached(client):
    c, _ = client
    payload = {"topic": SUMMARY, "latest_year": 2024, "themes": [], "loose_min_score": 0.6}
    with patch(f"{ROUTER_DB}.get_topic", return_value=TOPIC), \
            patch(f"{ROUTER_DB}.labels_version", return_value="0-0-0"), \
            patch(f"{ROUTER_DB}.topic_gaps", return_value=payload) as build:
        assert c.get("/api/v1/evolution/topics/object-detection/gaps").json()["latest_year"] == 2024
        c.get("/api/v1/evolution/topics/object-detection/gaps")
    assert build.call_count == 1


def test_a_status_change_refreshes_the_cached_graph(client):
    # Read while building, the graph must not stay cached with the "building" status once ready.
    c, _ = client
    payload = {"topic": SUMMARY, "nodes": [], "edges": [], "total_papers": 0, "year_range": None}
    building = SimpleNamespace(**{**vars(TOPIC), "status": "building"})
    with patch(f"{ROUTER_DB}.get_topic", side_effect=[building, TOPIC]), \
            patch(f"{ROUTER_DB}.labels_version", return_value="0-0"), \
            patch(f"{ROUTER_DB}.topic_graph", return_value=payload) as build:
        c.get("/api/v1/evolution/topics/object-detection/graph")
        c.get("/api/v1/evolution/topics/object-detection/graph")
    assert build.call_count == 2


# ── search-built topics ────────────────────────────────────────────────

PROPOSAL = {
    "id": "a" * 32, "query": "object tracking", "created_at": 0, "name": "Object tracking", "description": "",
    "aliases": ["object tracking"], "fields": ["Computer Science"], "field_counts": [],
    "candidates": [{"openalex_id": "W1", "title": "Object tracking", "year": 2006, "citations": 10,
                    "kind": "method", "venue": None, "alt_ids": [], "title_match": True, "semantic": False}],
    "anchors": ["W1"], "keywords": ["object tracking"], "keyword_suggestions": [], "cost_usd": 0.003,
    "refine": {"status": "unavailable"}, "_abstracts": {"W1": "The goal of this article..."},
}


def test_proposal_queues_the_9b_when_it_can_run(client):
    c, redis = client
    with patch(f"{ROUTER}.proposals.propose", return_value=dict(PROPOSAL)), \
            patch(f"{ROUTER}.chat_available", return_value=True), patch(f"{ROUTER}._enqueue") as enqueue:
        body = c.post("/api/v1/evolution/proposals", json={"query": "object tracking"}).json()
    assert body["refine"]["status"] == "pending" and "_abstracts" not in body
    assert enqueue.call_args.args == ("athena.evolution.tasks.refine_proposal", ["a" * 32])
    assert enqueue.call_args.kwargs["expires"] == 180
    assert c.get(f"/api/v1/evolution/proposals/{'a' * 32}").json()["anchors"] == ["W1"]
    assert "evoprop:" + "a" * 32 in redis.store


def test_proposal_without_a_chat_model_keeps_the_rules(client):
    c, _ = client
    with patch(f"{ROUTER}.proposals.propose", return_value=dict(PROPOSAL)), \
            patch(f"{ROUTER}.chat_available", return_value=False), patch(f"{ROUTER}._enqueue") as enqueue:
        body = c.post("/api/v1/evolution/proposals", json={"query": "object tracking"}).json()
    assert body["refine"]["status"] == "unavailable" and not enqueue.called


def test_a_refinement_the_gpu_never_started_shows_as_expired(client):
    c, redis = client
    from athena.evolution import propose
    propose.save(redis, PROPOSAL | {"refine": {"status": "pending", "deadline": 1.0}})
    assert c.get(f"/api/v1/evolution/proposals/{'a' * 32}").json()["refine"]["status"] == "expired"


def test_unknown_proposal_is_404(client):
    c, _ = client
    assert c.get("/api/v1/evolution/proposals/" + "b" * 32).status_code == 404
    assert c.get("/api/v1/evolution/proposals/not-an-id").status_code == 404


TOPIC_BODY = {"query": "object tracking", "name": "Object tracking", "keywords": ["Object Tracking", '"mot"'],
              "anchors": [{"openalex_id": "W1", "alt_ids": ["W2", "W1"]}], "fields": ["Computer Science"],
              "proposal_id": "a" * 32}


def test_create_topic_stores_a_search_topic_and_queues_its_build(client):
    c, redis = client
    from athena.evolution import propose
    propose.save(redis, PROPOSAL | {"refine": {"status": "pending", "deadline": 9e9}})
    with patch(f"{ROUTER_DB}.active_search_builds", return_value=0), \
            patch(f"{ROUTER_DB}.slug_taken", side_effect=[True, False]), \
            patch(f"{ROUTER_DB}.upsert_topic") as upsert, patch(f"{ROUTER_DB}.set_topic_status"), \
            patch(f"{ROUTER_DB}.get_topic", return_value=SEARCH_TOPIC), \
            patch(f"{ROUTER_DB}.topic_summary", return_value={"slug": "object-tracking-2"}), \
            patch(f"{ROUTER}._enqueue") as enqueue:
        resp = c.post("/api/v1/evolution/topics", json=TOPIC_BODY)
    assert resp.status_code == 201
    slug, name, aliases, _, seeds, config = upsert.call_args.args
    assert slug == "object-tracking-2"  # "object-tracking" was taken
    assert seeds == [{"openalex_id": "W1", "alt_ids": ["W2"]}]
    assert config == {"keywords": ["object tracking", '"mot"'], "fields": ["Computer Science"],
                      "openalex_search_max": 1000, "s2_keyless": False}
    assert upsert.call_args.kwargs == {"origin": "search", "query": "object tracking"}
    assert "object tracking" in aliases
    assert enqueue.call_args.args == ("athena.evolution.tasks.build_search_topic", ["object-tracking-2"])
    assert propose.load(redis, "a" * 32)["refine"]["status"] == "cancelled"


def test_create_topic_validates_its_input(client):
    c, _ = client
    assert c.post("/api/v1/evolution/topics", json=TOPIC_BODY | {"anchors": []}).status_code == 422
    assert c.post("/api/v1/evolution/topics", json=TOPIC_BODY | {"keywords": []}).status_code == 422
    assert c.post("/api/v1/evolution/topics", json=TOPIC_BODY | {"fields": ["Alchemy"]}).status_code == 422
    bad_id = [{"openalex_id": "https://evil", "alt_ids": []}]
    assert c.post("/api/v1/evolution/topics", json=TOPIC_BODY | {"anchors": bad_id}).status_code == 422


def test_too_many_search_builds_at_once_is_429(client):
    c, _ = client
    with patch(f"{ROUTER_DB}.active_search_builds", return_value=3):
        assert c.post("/api/v1/evolution/topics", json=TOPIC_BODY).status_code == 429


def test_curated_topics_cannot_be_deleted_or_rebuilt_here(client):
    c, _ = client
    with patch(f"{ROUTER_DB}.get_topic", return_value=TOPIC), patch(f"{ROUTER_DB}.delete_topic") as delete:
        assert c.delete("/api/v1/evolution/topics/object-detection").status_code == 409
        assert c.post("/api/v1/evolution/topics/object-detection/rebuild").status_code == 409
    assert not delete.called


def test_search_topics_can_be_deleted_and_rebuilt(client):
    c, redis = client
    redis.store["evo:object-tracking:graph:250:unbuilt:ready:0"] = "{}"
    with patch(f"{ROUTER_DB}.get_topic", return_value=SEARCH_TOPIC), patch(f"{ROUTER_DB}.delete_topic") as delete:
        assert c.delete("/api/v1/evolution/topics/object-tracking").status_code == 204
    assert delete.called and redis.store == {}
    with patch(f"{ROUTER_DB}.get_topic", return_value=SEARCH_TOPIC), patch(f"{ROUTER_DB}.set_topic_status"), \
            patch(f"{ROUTER_DB}.topic_summary", return_value={"slug": "object-tracking"}), \
            patch(f"{ROUTER}._enqueue") as enqueue:
        assert c.post("/api/v1/evolution/topics/object-tracking/rebuild").status_code == 200
    assert enqueue.call_args.args == ("athena.evolution.tasks.build_search_topic", ["object-tracking"])
    building = SimpleNamespace(**{**vars(SEARCH_TOPIC), "status": "building"})
    with patch(f"{ROUTER_DB}.get_topic", return_value=building):
        assert c.post("/api/v1/evolution/topics/object-tracking/rebuild").status_code == 409
