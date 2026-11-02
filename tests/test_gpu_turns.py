"""Turns on the GPU: background work grouped by model, so the router swaps per turn rather than per batch."""
from __future__ import annotations

import time

import pytest

from athena.model_server import activity, lane, turns

NINE_B, EMBED = "qwen3.5-9b", "qwen3-embedding-8b"


@pytest.fixture(autouse=True)
def gpu_presets(monkeypatch):
    servers = {NINE_B: "gpu", EMBED: "gpu", "small": "cpu"}
    monkeypatch.setattr(activity, "server_of", lambda model: servers.get(model))
    monkeypatch.setattr(lane, "POLL", 0.01)


def waiter(who: str, model: str, level: int, since: float | None = None) -> None:
    lane._waiting(None, who, "turn", model=model, priority=level, ttl=60) if since is None else \
        lane._redis().set(f"{lane.WAITING}{who}", __import__("json").dumps(
            {"who": who, "reason": "turn", "since": since, "model": model, "priority": level}), ex=60)


def test_the_first_work_takes_the_turn_and_the_same_model_never_waits():
    assert lane.yield_to_chat(who="summary", model=NINE_B) == 0
    assert turns.turn()["model"] == NINE_B
    with turns.priority(turns.BACKLOG):  # lower priority, but the loaded model: it runs beside the summaries
        assert lane.yield_to_chat(who="map_build", model=NINE_B) == 0


def test_cpu_and_unknown_models_take_no_turns():
    lane.yield_to_chat(who="summary", model=NINE_B)
    assert lane.yield_to_chat(who="summary", model="small") == 0
    assert lane.yield_to_chat(who="summary", model="hosted-model") == 0
    assert turns.turn()["model"] == NINE_B


def test_work_for_another_model_waits_while_the_loaded_one_is_in_use():
    lane.yield_to_chat(who="summary", model=NINE_B)  # the feed uses the 9B now
    assert turns.check(EMBED, turns.ROUTINE) == f"{NINE_B} has the GPU"
    assert lane.yield_to_chat(who="feed_embed", model=EMBED, max_wait=0.03) >= 0.03  # someone's work runs in the end


def test_asked_for_work_takes_the_gpu_after_the_call_in_hand():
    lane.yield_to_chat(who="summary", model=NINE_B)
    with activity.track("summary", NINE_B):  # a summary is being written
        assert turns.check(EMBED, turns.ASKED) == f"{NINE_B} is finishing a call"
        waiter("map_embed", EMBED, turns.ASKED)  # as yield_to_chat lists it
        assert turns.turn()["model"] == EMBED  # the turn moved: the next summary waits
        assert turns.check(NINE_B, turns.ROUTINE) == f"{EMBED} has the GPU"
    assert turns.check(EMBED, turns.ASKED) is None


def test_an_idle_model_gives_way_at_once(monkeypatch):
    lane.yield_to_chat(who="summary", model=NINE_B)
    monkeypatch.setattr(turns, "IDLE", 0.0)  # its last use is already too long ago
    assert turns.check(EMBED, turns.BACKLOG) is None and turns.turn()["model"] == EMBED


def test_equal_work_swaps_once_the_turn_is_up(monkeypatch):
    lane.yield_to_chat(who="summary", model=NINE_B)
    waiter("feed_embed", EMBED, turns.ROUTINE)
    assert turns.check(NINE_B, turns.ROUTINE) is None  # the 9B keeps its turn
    monkeypatch.setattr(turns, "TURN", 0.0)
    assert turns.check(NINE_B, turns.ROUTINE) == f"{EMBED} has the GPU"


def test_backlog_waits_for_routine_work_until_it_has_aged(monkeypatch):
    lane.yield_to_chat(who="summary", model=NINE_B)
    monkeypatch.setattr(turns, "TURN", 0.0)
    waiter("map_embed", EMBED, turns.BACKLOG, since=time.time() - 60)
    assert turns.check(NINE_B, turns.ROUTINE) is None  # lower priority: the turn being up is not enough
    waiter("map_embed", EMBED, turns.BACKLOG, since=time.time() - turns.AGING - 1)
    assert turns.check(NINE_B, turns.ROUTINE) == f"{EMBED} has the GPU"


def test_a_waiter_that_gave_up_hands_the_turn_back():
    lane.yield_to_chat(who="summary", model=NINE_B)
    lane._redis().set(turns.TURN_KEY, '{"model": "%s", "since": %f}' % (EMBED, time.time()))  # its waiter died
    assert turns.check(NINE_B, turns.ROUTINE) is None and turns.turn()["model"] == NINE_B


def test_turn_waits_are_listed_with_model_and_priority(monkeypatch):
    lane.yield_to_chat(who="summary", model=NINE_B)
    seen = []
    real = lane._waiting

    def spy(key, who, reason, **kw):
        key = real(key, who, reason, **kw)
        seen.extend(lane.waiting())
        return key
    monkeypatch.setattr(lane, "_waiting", spy)
    lane.yield_to_chat(who="feed_embed", model=EMBED, max_wait=0.02)
    assert seen[0]["reason"] == "turn" and seen[0]["model"] == EMBED and seen[0]["priority"] == turns.ROUTINE
    assert seen[0]["detail"] == f"{NINE_B} has the GPU" and lane.waiting() == []


def test_background_work_waiting_its_turn_too_long_queues_itself_again(monkeypatch):
    monkeypatch.setattr(lane, "PAUSE_HOLD", 0.03)
    lane.yield_to_chat(who="summary", model=NINE_B)
    with pytest.raises(lane.Paused):
        lane.yield_to_chat(who="map_embed", model=EMBED)


def test_the_minute_run_skips_and_keeps_its_place_in_line():
    lane.yield_to_chat(who="summary", model=NINE_B)
    assert not lane.my_turn("feed_embed", EMBED)
    (w,) = lane.waiting()
    first = w["since"]
    assert not lane.my_turn("feed_embed", EMBED)
    assert lane.waiting()[0]["since"] == first  # it ages across runs
    assert lane.my_turn("feed_embed", "small")  # a CPU model never waits


def test_the_minute_embedding_run_leaves_the_queue_alone_when_not_its_turn(monkeypatch):
    from athena.pipeline import embedding_worker
    lane.yield_to_chat(who="summary", model=NINE_B)
    monkeypatch.setattr(embedding_worker, "init_qdrant", lambda: None)
    monkeypatch.setattr(embedding_worker.llm, "embed_model", lambda: EMBED)
    r = lane._redis()
    monkeypatch.setattr(embedding_worker, "get_redis", lambda: r)
    r.rpush("athena:embedding_queue", "item-1")
    monkeypatch.setattr(embedding_worker, "process_batch", lambda ids: pytest.fail("embedded out of turn"))
    embedding_worker.process_embedding_queue()
    assert r.llen("athena:embedding_queue") == 1
    assert [w["who"] for w in lane.waiting()] == ["feed_embed"]


def test_an_empty_embedding_queue_does_not_ask_for_the_embedder(monkeypatch):
    from athena.pipeline import embedding_worker
    lane.yield_to_chat(who="summary", model=NINE_B)
    monkeypatch.setattr(embedding_worker, "init_qdrant", lambda: None)
    monkeypatch.setattr(embedding_worker, "get_redis", lane._redis)
    embedding_worker.process_embedding_queue()
    assert lane.waiting() == []


def test_priorities_come_from_the_feature_unless_a_task_says_otherwise():
    assert turns.priority_of("summary") == turns.ROUTINE and turns.priority_of("map_build") == turns.BACKLOG
    assert turns.priority_of("project_index") == turns.ASKED
    with turns.priority(turns.ASKED):
        assert turns.priority_of("map_embed") == turns.ASKED
    assert turns.priority_of("map_embed") == turns.BACKLOG


def test_a_built_map_is_asked_for_and_a_scheduled_refresh_is_backlog(monkeypatch):
    from athena.evolution import build, model_lane, tasks
    seen = []
    monkeypatch.setattr(build, "build_search_topic", lambda slug, **kw: seen.append(turns.priority_of("map_embed")))
    tasks.build_search_topic("vln")
    monkeypatch.setattr(model_lane, "run_lane", lambda **kw: seen.append(turns.priority_of("map_build")) or {})
    tasks.refresh_gpu_lane("vln", True)
    tasks.refresh_gpu_lane()
    assert seen == [turns.ASKED, turns.ASKED, turns.BACKLOG]


def test_a_refresh_someone_started_carries_it_through_the_chain():
    from athena.evolution.refresh import refresh_chain
    steps = {t.task.rsplit(".", 1)[1]: t.args for t in refresh_chain("vln", asked=True).tasks}
    assert tuple(steps["refresh_build"]) == ("vln", True) == tuple(steps["refresh_gpu_lane"])
    assert tuple(refresh_chain("vln").tasks[0].args) == ("vln", False)
