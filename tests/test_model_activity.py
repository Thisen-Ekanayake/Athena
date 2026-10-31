"""What the model servers are doing: calls in flight and done, swaps, today's totals, pausing background work, and
an unload that waits for the router and says what would load the model again."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from athena.api.main import app
from athena.model_server import activity, lane, loading


@pytest.fixture
def gpu_presets(monkeypatch):
    """Two presets on the GPU router and one on the CPU router."""
    servers = {"qwen3.5-9b": "gpu", "qwen3-embedding-8b": "gpu", "small": "cpu"}
    monkeypatch.setattr(activity, "server_of", lambda model: servers.get(model))


def test_a_call_is_live_then_logged_with_sizes_and_no_text(gpu_presets):
    with activity.track("summary", "qwen3.5-9b") as call:
        (live,) = activity.live()
        assert live["feature"] == "summary" and live["server"] == "gpu" and "elapsed" in live
        call.tokens(1200, 300)
    assert activity.live() == []
    (done,) = activity.recent()
    assert done["status"] == "done" and (done["input_tokens"], done["output_tokens"]) == (1200, 300)
    assert set(done) == {"id", "feature", "model", "kind", "user_id", "started", "server", "swapped", "seconds",
                         "status", "error", "input_tokens", "output_tokens"}
    (today,) = activity.today()
    assert today["label"] == "Summaries" and today["calls"] == 1 and today["input_tokens"] == 1200


def test_a_failure_keeps_the_kind_of_error_but_not_its_message(gpu_presets):
    with pytest.raises(ValueError):
        with activity.track("chat", "qwen3.5-9b", user_id="u1"):
            raise ValueError("the prompt was: a secret plan")
    (failed,) = activity.recent()
    assert failed["status"] == "failed" and failed["error"] == "ValueError" and "secret" not in json.dumps(failed)
    assert activity.today()[0]["failed"] == 1


def test_a_stream_that_is_stopped_is_not_a_failure(gpu_presets):
    call = activity.start("chat", "qwen3.5-9b")
    activity.finish(call, GeneratorExit())
    activity.finish(call)  # a second finish changes nothing
    assert [r["status"] for r in activity.recent()] == ["stopped"]


def test_switching_presets_on_one_router_is_a_swap(gpu_presets):
    for model in ("qwen3.5-9b", "qwen3.5-9b", "qwen3-embedding-8b", "small", "hosted-model"):
        with activity.track("feed_embed" if "embed" in model else "summary", model):
            pass
    swaps = activity.swaps()  # newest first
    assert [(s["server"], s["before"], s["after"], s["cause"]) for s in swaps] == [
        ("cpu", None, "small", "summary"),
        ("gpu", "qwen3.5-9b", "qwen3-embedding-8b", "feed_embed"),
        ("gpu", None, "qwen3.5-9b", "summary"),
    ]
    activity.swap("gpu", "qwen3-embedding-8b", None, "unload")  # after an unload the next call loads again
    with activity.track("summary", "qwen3-embedding-8b") as call:
        pass
    assert call.swapped


# ── pausing background work ─────────────────────────────────────────


def test_a_pause_holds_background_work_but_not_what_people_asked_for(monkeypatch):
    monkeypatch.setattr(lane, "POLL", 0.01)
    monkeypatch.setattr(lane, "PAUSE_HOLD", 0.05)
    lane.pause(by="Admin")
    assert lane.paused()["by"] == "Admin"
    assert lane.yield_to_chat(who="project_index", pausable=False) == 0
    seen = []
    monkeypatch.setattr(lane, "_waiting", lambda key, who, reason: seen.append((who, reason)) or "k")
    with pytest.raises(lane.Paused):  # past the hold the task queues itself again
        lane.yield_to_chat(who="summary")
    assert seen[0] == ("summary", "paused")
    lane.resume()
    assert lane.paused() is None and lane.yield_to_chat(who="summary") == 0


def test_each_group_pauses_on_its_own(monkeypatch):
    from athena.pipeline import embedding_worker
    monkeypatch.setattr(lane, "POLL", 0.01)
    monkeypatch.setattr(lane, "PAUSE_HOLD", 0.05)
    lane.pause("maps", by="Admin")
    assert lane.pauses()["maps"]["by"] == "Admin" and lane.pauses()["feed"] is None
    assert lane.paused() is None  # not everything
    assert lane.yield_to_chat(who="summary") == 0 and lane.yield_to_chat(who="cluster_label") == 0
    with pytest.raises(lane.Paused):
        lane.yield_to_chat(who="map_embed")
    ran = []
    monkeypatch.setattr(embedding_worker, "init_qdrant", lambda: ran.append(1) or (_ for _ in ()).throw(RuntimeError))
    with pytest.raises(RuntimeError):
        embedding_worker.process_embedding_queue()  # the feed's embeddings still run
    lane.pause("feed")
    embedding_worker.process_embedding_queue()
    assert ran == [1] and lane.paused()["by"] == "Admin"  # both groups now: everything is paused
    lane.resume("maps")
    assert lane.pauses() == {"feed": lane.pauses()["feed"], "maps": None} and lane.yield_to_chat(who="map_build") == 0


def test_a_pause_from_before_groups_holds_both():
    lane._redis().set(lane.PAUSE_KEY, '{"by": "Admin", "since": 1}')
    assert lane.pauses() == {"feed": {"by": "Admin", "since": 1}, "maps": {"by": "Admin", "since": 1}}
    assert lane._redis().get(lane.PAUSE_KEY) is None
    lane.resume()
    assert lane.pauses() == {"feed": None, "maps": None}


def test_waiters_are_listed_while_they_wait(monkeypatch):
    monkeypatch.setattr(lane, "POLL", 0.01)
    lane.hold()
    seen = []
    real = lane._waiting

    def spy(key, who, reason):
        key = real(key, who, reason)
        seen.append(lane.waiting())
        return key
    monkeypatch.setattr(lane, "_waiting", spy)
    lane.yield_to_chat(max_wait=0.03, who="map_build")
    assert seen and seen[0][0]["who"] == "map_build" and seen[0][0]["reason"] == "chat"
    assert lane.waiting() == []  # gone once it stops waiting


def test_minute_embedding_runs_skip_while_paused(monkeypatch):
    from athena.pipeline import embedding_worker
    lane.pause()
    monkeypatch.setattr(embedding_worker, "init_qdrant", lambda: pytest.fail("ran while paused"))
    embedding_worker.process_embedding_queue()


def test_a_map_lane_held_too_long_queues_itself_again(monkeypatch):
    from athena.evolution import model_lane, tasks
    queued = []
    monkeypatch.setattr(model_lane, "run_lane", lambda **kw: (_ for _ in ()).throw(lane.Paused("held")))
    monkeypatch.setattr(tasks.run_gpu_lane, "apply_async", lambda **kw: queued.append(kw))
    assert "paused" in tasks.run_gpu_lane(True, False)
    assert queued == [{"args": [True, False], "countdown": lane.REQUEUE_SECONDS}]


# ── unloading ────────────────────────────────────────────────────────


def test_unload_waits_until_the_router_lets_go(monkeypatch):
    monkeypatch.setattr(loading, "POLL", 0.01)
    gpu_states = iter(["loaded", "loaded", "loaded"])  # the router still lists it twice after being asked
    asked = []
    monkeypatch.setattr(loading, "router_models", lambda url: [
        {"id": "qwen3.5-9b", "status": {"value": next(gpu_states, "unloaded")}}] if "8080" in url else [])
    monkeypatch.setattr(loading.httpx, "post", lambda url, json, timeout: asked.append(json["model"]))
    row = {"contexts": [{"preset": "qwen3.5-9b", "vision_preset": None}]}
    assert loading.unload(row) == ["qwen3.5-9b"] and asked == ["qwen3.5-9b"]
    assert next(gpu_states, "drained") == "drained"  # it polled until the router no longer listed it loaded
    (swap,) = activity.swaps()
    assert (swap["before"], swap["after"], swap["cause"]) == ("qwen3.5-9b", None, "unload")


# ── the admin page ───────────────────────────────────────────────────


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(loading, "router_models", lambda url: [])
    from athena.model_server import gpu
    monkeypatch.setattr(gpu, "gpu", lambda: None)
    return TestClient(app)


def test_the_page_shows_calls_lane_queues_and_totals(client, gpu_presets):
    call = activity.start("summary", "qwen3.5-9b")
    lane.hold(what="chat")
    activity._redis().rpush("summary_standard", "a", "b")
    body = client.get("/api/v1/models/activity").json()
    (live,) = body["calls"]
    assert live["label"] == "Summaries" and live["background"] and live["user"] is None
    assert body["lane"]["holder"] == "chat" and body["lane"]["paused"] is None
    assert {"label": "Feed summaries", "count": 2, "group": "feed"} in body["queues"]
    assert body["swaps"][0]["cause_label"] == "Summaries"
    activity.finish(call)
    body = client.get("/api/v1/models/activity").json()
    assert body["calls"] == [] and body["recent"][0]["status"] == "done" and body["today"][0]["calls"] == 1


def test_pause_and_resume(client):
    assert client.post("/api/v1/models/activity/pause").json()["paused"]["since"] > 0
    assert client.get("/api/v1/models/activity").json()["lane"]["paused"]
    resumed = client.post("/api/v1/models/activity/resume").json()
    assert resumed["paused"] is None and all(g["paused"] is None for g in resumed["groups"])
    assert lane.paused() is None


def test_one_group_is_paused_and_resumed(client):
    body = client.post("/api/v1/models/activity/pause", json={"group": "maps"}).json()
    assert body["paused"] is None
    assert {g["key"]: bool(g["paused"]) for g in body["groups"]} == {"feed": False, "maps": True}
    groups = client.get("/api/v1/models/activity").json()["lane"]["groups"]
    assert [(g["key"], g["label"]) for g in groups] == [("feed", "Feed"), ("maps", "Maps")]
    assert client.post("/api/v1/models/activity/pause", json={"group": "trending"}).status_code == 422
    assert client.post("/api/v1/models/activity/resume", json={"group": "maps"}).json()["groups"][1]["paused"] is None


def test_unload_says_which_background_work_will_load_the_model_again(gpu_presets):
    from athena.api.routers import model_activity
    with activity.track("summary", "qwen3.5-9b"):
        pass
    with activity.track("chat", "qwen3.5-9b", user_id="u1"):  # a person's chat is not background work
        pass
    assert model_activity.reloads({"qwen3.5-9b"}) == ["Summaries"]
    assert model_activity.reloads({"qwen3-embedding-8b"}) == []
    lane.pause("maps")
    assert model_activity.reloads({"qwen3.5-9b"}) == ["Summaries"]  # another group's pause does not hold it
    lane.pause("feed")
    assert model_activity.reloads({"qwen3.5-9b"}) == []  # paused: it stays out


# ── what stays loaded ────────────────────────────────────────────────


def test_the_default_model_loads_at_start_up_unless_the_router_holds_one(monkeypatch):
    t = {"preset": "qwen3.5-9b", "url": "http://127.0.0.1:8080/v1"}
    monkeypatch.setattr(loading, "resting_target", lambda: t)
    loads = []
    monkeypatch.setattr(loading, "load",
                        lambda target, for_chat=True, cause=None: loads.append((target["preset"], cause)))
    listed = [{"id": "qwen3.5-9b", "status": {"value": "unloaded"}}]
    monkeypatch.setattr(loading, "router_models", lambda url: listed)
    loading.load_on_start().join(2)
    assert loads == [("qwen3.5-9b", "startup")]
    listed[0]["status"]["value"] = "loaded"  # only the API restarted: leave the router as it is
    loading.load_on_start().join(2)
    lane.pause()  # an admin keeps the GPU free
    listed[0]["status"]["value"] = "unloaded"
    loading.load_on_start().join(2)
    assert len(loads) == 1


def test_a_benchmark_puts_back_the_chat_model_not_its_last_context(monkeypatch):
    from athena.model_server import bench, registry
    loads = []
    monkeypatch.setattr(loading, "load", lambda target, for_chat=True, cause=None: loads.append(target))
    monkeypatch.setattr(loading, "resting_target", lambda: "default at its default context")
    monkeypatch.setattr(loading, "target", lambda model, context, vision=False: (model, context, vision))
    infos = {"qwen3.5-9b@32k": {"model": "qwen3.5-9b", "context": 32768, "vision": False, "row": {"role": "chat"}},
             "qwen3-embedding-8b": {"model": "qwen3-embedding-8b", "context": 2048, "vision": False,
                                    "row": {"role": "embed"}}}
    monkeypatch.setattr(registry, "preset_info", infos.get)
    bench.restore(["qwen3.5-9b@32k"])
    bench.restore(["qwen3-embedding-8b"])
    bench.restore([])
    assert loads == [("qwen3.5-9b", 32768, False), "default at its default context", "default at its default context"]


def test_calls_made_while_serving_a_request_name_its_user(gpu_presets):
    from types import SimpleNamespace

    from fastapi import APIRouter, Depends, FastAPI

    from athena.api.auth import acting_user, active_user
    router = APIRouter()

    @router.get("/sync")  # a sync route runs in a thread
    def sync_route():
        with activity.track("chat", "qwen3.5-9b"):  # e.g. a chat's title, which names no user itself
            pass

    @router.get("/async")
    async def async_route():
        with activity.track("search", "qwen3-embedding-8b", kind="embed"):
            pass

    app = FastAPI()
    app.include_router(router, dependencies=[Depends(acting_user)])
    app.dependency_overrides[active_user] = lambda: SimpleNamespace(id="u-7")
    client = TestClient(app)
    client.get("/sync")
    client.get("/async")
    with activity.track("summary", "qwen3.5-9b"):  # outside a request: background work
        pass
    assert [r["user_id"] for r in activity.recent()] == [None, "u-7", "u-7"]
