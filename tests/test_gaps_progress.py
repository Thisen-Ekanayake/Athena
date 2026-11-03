"""How far a map's open problems have got: stages, counts, an estimate, and why nothing is happening."""
from __future__ import annotations

import time

import pytest

from athena.evolution import progress, tasks
from tests.fakes import FakeRedis


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from athena.api.deps import get_db, get_redis
    from athena.api.main import app
    redis = FakeRedis()
    app.dependency_overrides[get_db] = lambda: None
    app.dependency_overrides[get_redis] = lambda: redis
    yield TestClient(app), redis
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def fake_redis(monkeypatch):
    from athena.core import redis_client
    fake = progress._redis()  # conftest's fake, shared with the lane
    monkeypatch.setattr(redis_client, "get_redis", lambda *a, **kw: fake)
    return fake


def test_stages_count_and_estimate_the_time_left(monkeypatch):
    assert progress.get("vln") is None
    progress.stage("vln", "labelling", 1200)
    state = progress.get("vln")
    assert state["label"] == "Labelling citing sentences" and state["done"] == 0 and state["eta_seconds"] is None
    started = state["started"]
    monkeypatch.setattr(time, "time", lambda: started + 100)
    progress.advance("vln", 300)
    assert progress.get("vln")["done"] == 300 and progress.get("vln")["eta_seconds"] == 300  # 900 left at 3/s
    progress.stage(None, "labelling")  # no map: nothing is written
    progress.advance(None)


def test_a_note_stays_until_the_map_is_queued_again():
    progress.stage("vln", "reading", note="The PDFs were not read: GROBID is not reachable")
    progress.stage("vln", "labelling", 10)
    assert progress.get("vln")["note"].startswith("The PDFs were not read")
    progress.stage("vln", "queued")
    assert progress.get("vln")["note"] is None


def test_grobid_down_is_said_on_the_map_and_the_lane_still_runs(monkeypatch):
    from athena.evolution import fulltext

    def run(slug, on_progress=None):
        raise RuntimeError("GROBID is not reachable at http://localhost:8070. Start it with `docker compose …`.")
    monkeypatch.setattr(fulltext, "run_full_text", run)
    assert "error" in tasks.refresh_full_text("vln")
    assert "GROBID is not reachable" in progress.get("vln")["note"]


def test_full_text_counts_the_pdfs(monkeypatch):
    from athena.evolution import fulltext

    def run(slug, on_progress=None):
        on_progress(0, 40)
        on_progress(25, 40)
        return {"processed": 25}
    monkeypatch.setattr(fulltext, "run_full_text", run)
    tasks.refresh_full_text("vln")
    state = progress.get("vln")
    assert (state["stage"], state["done"], state["total"]) == ("reading", 25, 40)


def test_the_gaps_route_adds_progress_and_what_the_lane_waits_for(client, monkeypatch):
    from unittest.mock import patch
    from types import SimpleNamespace
    from athena.model_server import lane
    c, _ = client
    topic = SimpleNamespace(slug="vln", built_at=None, status="ready")
    progress.stage("vln", "embedding")
    lane._waiting(None, "map_embed", "turn", model="qwen3-embedding-8b", priority=2, detail="qwen3.5-9b has the GPU")
    with patch("athena.api.routers.evolution.gaps._topic_or_404", return_value=topic), \
            patch("athena.api.routers.evolution.gaps._cache_key", return_value="k"), \
            patch("athena.api.routers.evolution.gaps.db.topic_gaps", return_value={"themes": []}):
        body = c.get("/api/v1/evolution/topics/vln/gaps").json()
    assert body["progress"]["stage"] == "embedding" and body["themes"] == []
    assert body["waiting"]["reason"] == "turn" and body["waiting"]["detail"] == "qwen3.5-9b has the GPU"
