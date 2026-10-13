"""API tests for the evolution tools (ROADMAP E1-E9), with the database layer mocked."""
from __future__ import annotations

from datetime import datetime, timezone
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


# ── E2 idea checks ─────────────────────────────────────────────────────

IDEA = {"idea": "Fine-tune adapters in two bits without losing accuracy."}


def test_idea_check_is_saved_to_the_account(client):
    c, _ = client
    as_user()
    result = {"papers": [], "themes": [], "unthemed_gaps": [], "verdict": None, "usage": None}
    with patch("athena.evolution.ideas.check_idea", return_value=result) as check, \
            patch(f"{ROUTER_DB}.save_idea_check", return_value={"id": "1", "result": result}) as save:
        resp = c.post("/api/v1/evolution/idea-checks", json=IDEA)
    assert resp.status_code == 201
    assert check.call_args.kwargs == {"verdict": True}
    assert save.call_args.args[1:] == (USER.id, IDEA["idea"], result)


def test_idea_checks_have_a_daily_limit(client):
    c, redis = client
    as_user()
    with patch("athena.evolution.ideas.check_idea", return_value={}), \
            patch(f"{ROUTER_DB}.save_idea_check", return_value={}):
        codes = [c.post("/api/v1/evolution/idea-checks", json=IDEA).status_code for _ in range(21)]
    assert codes[:20] == [201] * 20 and codes[20] == 429


def test_idea_check_without_an_embedder_is_503(client):
    c, _ = client
    from athena.evolution.ideas import IdeaCheckUnavailable
    with patch("athena.evolution.ideas.check_idea", side_effect=IdeaCheckUnavailable("no model")):
        resp = c.post("/api/v1/evolution/idea-checks", json=IDEA)
    assert resp.status_code == 503 and resp.json()["detail"] == "no model"


def test_idea_checks_are_private(client):
    c, _ = client
    as_user()
    check_id = uuid4()
    with patch(f"{ROUTER_DB}.get_idea_check", return_value=None) as read:
        assert c.get(f"/api/v1/evolution/idea-checks/{check_id}").status_code == 404
    assert read.call_args.args[1:] == (USER.id, check_id)
    with patch(f"{ROUTER_DB}.delete_idea_check", return_value=False):
        assert c.delete(f"/api/v1/evolution/idea-checks/{check_id}").status_code == 404


def test_short_ideas_are_rejected(client):
    c, _ = client
    assert c.post("/api/v1/evolution/idea-checks", json={"idea": "too short"}).status_code == 422


# ── E3 questions to a map ──────────────────────────────────────────────


class FakeStream:
    def __init__(self, tokens):
        self.tokens = list(tokens)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.tokens:
            raise StopAsyncIteration
        delta = SimpleNamespace(content=self.tokens.pop(0))
        return SimpleNamespace(choices=[SimpleNamespace(delta=delta)])


class FakeChat:
    def __init__(self, tokens):
        self.tokens = tokens
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    async def create(self, **kwargs):
        self.kwargs = kwargs
        return FakeStream(self.tokens)


def _events(resp):
    import json
    return [json.loads(line[6:]) for line in resp.text.splitlines() if line.startswith("data: {")]


def test_ask_streams_sources_then_tokens_then_the_saved_id(client):
    from athena.evolution.ask import Source
    c, redis = client
    as_user()
    src = Source(n=1, paper_id="p", title="LoRA", year=2021, named_method="LoRA", section_type="method",
                 heading="Method", text="Merged weights.", abstract_only=False, score=0.8)
    chat = FakeChat(["Weights merge ", "[1]."])
    with patch(f"{ROUTER_DB}.get_topic", return_value=TOPIC), \
            patch("athena.evolution.ask.retrieve", return_value=[src]) as retrieve, \
            patch("athena.core.llm.async_chat_client", return_value=chat), \
            patch(f"{ROUTER_DB}.save_map_question", return_value=uuid4()) as save:
        resp = c.post("/api/v1/evolution/topics/object-detection/ask",
                      json={"question": "Why no latency?", "sections": ["method"]})
    events = _events(resp)
    assert events[0]["sources"][0]["title"] == "LoRA" and events[0]["abstract_only"] == 0
    assert [e["token"] for e in events[1:3]] == ["Weights merge ", "[1]."]
    assert events[3]["done"] is True
    assert retrieve.call_args.args[2:] == ("Why no latency?", ["method"])
    assert save.call_args.args[:4] == (USER.id, TOPIC.id, "Why no latency?", "Weights merge [1].")
    assert int(redis.get(f"limit:{USER.id}:map_qa_tokens:{datetime.now(timezone.utc):%Y-%m-%d}")) > 0


def test_ask_stops_at_the_token_allowance(client):
    c, redis = client
    as_user()
    redis.set(f"limit:{USER.id}:map_qa_tokens:{datetime.now(timezone.utc):%Y-%m-%d}", 10**9)
    with patch(f"{ROUTER_DB}.get_topic", return_value=TOPIC), patch("athena.evolution.ask.retrieve") as retrieve:
        resp = c.post("/api/v1/evolution/topics/object-detection/ask", json={"question": "Why?"})
    assert resp.status_code == 429 and "tokens" in resp.json()["detail"]
    retrieve.assert_not_called()


def test_ask_without_an_embedder_is_503(client):
    from athena.evolution.ask import AskUnavailable
    c, _ = client
    with patch(f"{ROUTER_DB}.get_topic", return_value=TOPIC), \
            patch("athena.evolution.ask.retrieve", side_effect=AskUnavailable("no model")):
        resp = c.post("/api/v1/evolution/topics/object-detection/ask", json={"question": "Why?"})
    assert resp.status_code == 503


def test_questions_are_per_user(client):
    c, _ = client
    as_user()
    with patch(f"{ROUTER_DB}.get_topic", return_value=TOPIC), \
            patch(f"{ROUTER_DB}.map_questions", return_value=[]) as read:
        assert c.get("/api/v1/evolution/topics/object-detection/questions").json() == []
    assert read.call_args.args[1:] == (USER.id, TOPIC.id)
    with patch(f"{ROUTER_DB}.delete_map_question", return_value=0):
        assert c.delete(f"/api/v1/evolution/questions/{uuid4()}").status_code == 404


# ── E7 links between maps ──────────────────────────────────────────────


def test_links_are_cached_until_any_map_changes(client):
    c, _ = client
    payload = {"topic": {}, "shared": {"total": 0, "papers": []}, "borrowed": [], "lent": []}
    with patch(f"{ROUTER_DB}.get_topic", return_value=TOPIC), patch(f"{ROUTER_DB}.labels_version", return_value="0"), \
            patch(f"{ROUTER_DB}.maps_version", side_effect=["1-6", "1-6", "2-6"]), \
            patch(f"{ROUTER_DB}.topic_links", return_value=payload) as build:
        for _ in range(3):
            assert c.get("/api/v1/evolution/topics/object-detection/links").json() == payload
    assert build.call_count == 2


# ── E4 refresh and changes ─────────────────────────────────────────────


def test_refresh_is_admin_only(client):
    c, _ = client
    as_user()
    assert c.post("/api/v1/evolution/topics/object-detection/refresh").status_code == 403
    assert c.post("/api/v1/evolution/topics/object-detection/full-text").status_code == 403
    assert c.patch("/api/v1/evolution/topics/object-detection/settings", json={"refresh_days": 7}).status_code == 403


def test_refresh_queues_the_chain_and_keeps_the_map_readable(client):
    c, _ = client
    with patch(f"{ROUTER_DB}.get_topic", return_value=TOPIC), patch(f"{ROUTER_DB}.set_topic_status") as status, \
            patch("athena.evolution.refresh.queue_refresh", return_value="t1") as queue:
        resp = c.post("/api/v1/evolution/topics/object-detection/refresh")
    assert resp.status_code == 202 and resp.json()["task_id"] == "t1"
    assert status.call_args.args == ("object-detection", "refining", "Refresh queued")
    assert queue.call_args.args == ("object-detection",)


def test_refresh_of_a_busy_map_is_409(client):
    c, _ = client
    busy = SimpleNamespace(**{**vars(TOPIC), "status": "building"})
    with patch(f"{ROUTER_DB}.get_topic", return_value=busy):
        assert c.post("/api/v1/evolution/topics/object-detection/refresh").status_code == 409


def test_full_text_skips_the_rebuild(client):
    c, _ = client
    with patch(f"{ROUTER_DB}.get_topic", return_value=TOPIC), \
            patch("athena.evolution.refresh.queue_refresh", return_value="t2") as queue:
        assert c.post("/api/v1/evolution/topics/object-detection/full-text").status_code == 202
    assert queue.call_args.kwargs == {"rebuild": False, "reason": "full_text"}


def test_refresh_interval_is_bounded(client):
    c, _ = client
    assert c.patch("/api/v1/evolution/topics/object-detection/settings", json={"refresh_days": 400}).status_code == 422


def test_refresh_chain_order():
    from athena.evolution.refresh import refresh_chain
    names = [t.task.rsplit(".", 1)[1] for t in refresh_chain("peft").tasks]
    assert names == ["fetch_method_names_step", "refresh_build", "refresh_full_text", "refresh_gpu_lane",
                     "snapshot_topic"]
    assert [t.task.rsplit(".", 1)[1] for t in refresh_chain("peft", rebuild=False).tasks] == [
        "refresh_full_text", "refresh_gpu_lane", "snapshot_topic"]
    assert refresh_chain("peft").tasks[0].options["queue"] == "celery"
