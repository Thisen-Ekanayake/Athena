"""The maps' GPU lane: the map someone asked about first, the backlog shortest first, and the backlog stepping
aside for work queued behind it."""
from __future__ import annotations

import pytest

from athena.evolution import model_lane, tasks
from athena.model_server import turns
from tests.fakes import FakeRedis


@pytest.fixture
def fake_redis(monkeypatch):
    from athena.core import redis_client
    fake = FakeRedis()
    monkeypatch.setattr(redis_client, "get_redis", lambda *a, **kw: fake)
    return fake


@pytest.fixture
def scopes(monkeypatch):
    """Three ready maps with 30, 5 and 0 sentences left to label; records each lane scope that runs."""
    ran = []
    left = {"vln": 30, "depth": 5, "mirrors": 0}
    monkeypatch.setattr(model_lane, "_ready_topics", lambda session, slug=None: [
        type("T", (), {"slug": s})() for s in left])
    monkeypatch.setattr(model_lane.db, "topic_scope", lambda session, topic: {"tier2": {topic.slug}, "papers": set()})
    monkeypatch.setattr(model_lane.db, "count_pending_contexts", lambda session, ids: left[next(iter(ids))])
    monkeypatch.setattr(model_lane, "_run_scope", lambda embed, classify, slug: ran.append(slug) or {"slug": slug})
    return ran


def test_one_map_runs_alone(scopes):
    assert model_lane.run_lane(slug="vln") == {"vln": {"slug": "vln"}}
    assert scopes == ["vln"]


def test_the_backlog_goes_shortest_first_then_the_rest(scopes):
    assert model_lane.backlog_order() == ["depth", "vln"]  # nothing left in mirrors
    model_lane.run_lane()
    assert scopes == ["depth", "vln", None]


def test_backlog_steps_aside_for_queued_work_but_asked_work_never_does(fake_redis):
    model_lane._step_aside()  # nothing queued
    fake_redis.rpush(model_lane.EVOLUTION_QUEUE, "a full-text request")
    with turns.priority(turns.BACKLOG):
        with pytest.raises(model_lane.StepAside):
            model_lane._step_aside()
    with turns.priority(turns.ASKED):
        model_lane._step_aside()


def test_a_scoped_run_labels_only_that_maps_sentences(monkeypatch, fake_redis):
    seen = {}

    class Clf:
        local, model, model_tag = True, "qwen3.5-9b", "qwen3.5-9b+think"

        def __init__(self, **kw):
            seen["wait"] = kw.get("wait")

    monkeypatch.setattr(model_lane, "Classifier", Clf)
    monkeypatch.setattr(model_lane, "chat_server", lambda: ("http://x", __import__("contextlib").nullcontext()))
    monkeypatch.setattr(model_lane, "SessionLocal", lambda: __import__("contextlib").nullcontext())
    monkeypatch.setattr(model_lane.db, "all_tier2_ids", lambda session: pytest.fail("labelled every map"))
    monkeypatch.setattr(model_lane.db, "unconfirmed_strict", lambda *a: pytest.fail("rechecked every map"))
    monkeypatch.setattr(model_lane.db, "pending_contexts", lambda s, cited, n: seen.setdefault("cited", cited) and [])
    monkeypatch.setattr(model_lane.db, "pending_gap_candidates", lambda s, n, papers: seen.setdefault("papers", papers)
                        and [])
    model_lane.classify_pending(scope={"tier2": {"a"}, "papers": {"a", "b"}})
    assert seen == {"wait": {}, "cited": {"a"}, "papers": {"a", "b"}}


def test_an_asked_map_queues_the_backlog_once(monkeypatch, fake_redis):
    queued = []
    monkeypatch.setattr(model_lane, "run_lane", lambda **kw: {"ran": kw["slug"]})
    monkeypatch.setattr(tasks.run_gpu_lane, "apply_async", lambda **kw: queued.append(kw))
    assert tasks.run_gpu_lane(True, True, "vln", True) == {"ran": "vln"}
    tasks.run_gpu_lane(True, True, "depth", True)
    assert queued == [{"args": [True, True, None, False]}]  # one backlog run in the queue
    tasks.run_gpu_lane(True, True, None, False)  # it starts: the next map may queue another
    assert tasks.queue_backlog() and len(queued) == 2


def test_a_backlog_run_that_steps_aside_goes_to_the_back(monkeypatch, fake_redis):
    queued = []

    def run_lane(**kw):
        raise model_lane.StepAside("1 task waits")
    monkeypatch.setattr(model_lane, "run_lane", run_lane)
    monkeypatch.setattr(tasks.run_gpu_lane, "apply_async", lambda **kw: queued.append(kw))
    assert "stepped_aside" in tasks.run_gpu_lane(True, True, None, False)
    assert "stepped_aside" in tasks.refresh_gpu_lane("vln")  # a scheduled refresh's own map too
    assert queued == [{"args": [True, True, None, False]}, {"args": [True, True, "vln", False]}]
