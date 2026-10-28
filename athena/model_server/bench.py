"""
The benchmark a model gets when it is added: at each of its contexts, load it (timing the load), read a prompt of
about a thousand tokens and write 128 tokens, and keep llama.cpp's own timings. Results are kept per file, device and
context (llm_benchmarks), so a model is measured again only when its file or the GPU changes, or an admin asks.

A run gives way to chats between contexts (athena.model_server.lane), runs one at a time, and leaves the router as
it found it: the chat model that was loaded before is loaded again at the end.
"""
from __future__ import annotations

import contextvars
import json
import threading
import time

import httpx
from loguru import logger

from athena.core import usage
from athena.model_server import activity, lane, loading, registry, stats

STATUS_KEY = "athena:model_bench"
MODEL_KEY = "athena:model_bench:{id}"
LOCK_KEY = "athena:model_bench_lock"
LOCK_SECONDS = 1800
BENCH = "benchmark"
LANE_SECONDS = 180        # one context: a load and an answer, on the CPU too
ANSWER_TOKENS = 128
PARAGRAPH = ("Research on language models moves quickly: new architectures, training recipes and evaluation suites "
             "appear every week, and a careful reader keeps track of which results replicate, which baselines were "
             "tuned fairly and which claims rest on a single benchmark. ")
PROMPT = PARAGRAPH * 24 + "\n\nWrite a short essay on how to read machine learning papers critically."


def _redis():
    from athena.core.redis_client import get_redis
    return get_redis(decode_responses=True)


def _status(**fields) -> None:
    """The running (or last) benchmark, and each model's last one, which Settings shows under the model."""
    try:
        value = json.dumps(fields | {"at": time.time()})
        _redis().set(STATUS_KEY, value, ex=3600)
        if fields.get("model_id"):
            _redis().set(MODEL_KEY.format(id=fields["model_id"]), value, ex=7 * 86400)
    except Exception:
        pass


def last(model_id: str) -> dict | None:
    """A model's last benchmark: {state, results, error, at}."""
    try:
        raw = _redis().get(MODEL_KEY.format(id=model_id))
        return json.loads(raw) if raw else None
    except Exception:
        return None


def status() -> dict | None:
    try:
        raw = _redis().get(STATUS_KEY)
        return json.loads(raw) if raw else None
    except Exception:
        return None


def measured(model_id: str) -> set[int]:
    """Contexts this file already has a benchmark for on this machine."""
    return {b["context"] for b in stats.benches()
            if b["model_id"] == model_id and b["source"] == "benchmark" and b.get("gen_tps")
            and b["device"] == stats.device_of(_plan(model_id, b["context"]))}


def _plan(model_id: str, context: int) -> dict:
    row = next((r for r in registry.snapshot() if r["id"] == model_id), None)
    c = next((c for c in (row or {}).get("contexts", []) if c["context"] == context), None)
    return (c or {}).get("plan") or {"device": "gpu"}


class LoadFailed(RuntimeError):
    """The model did not load; larger contexts of it will not either."""


def one(t: dict) -> dict:
    """Load ``t``'s preset and time an answer; {gen_tps, prompt_tps}."""
    if reason := loading.load(t, for_chat=False):
        raise LoadFailed(reason)
    body = {"model": t["preset"], "messages": [{"role": "user", "content": PROMPT}], "max_tokens": ANSWER_TOKENS,
            "temperature": 0, "ignore_eos": True, "cache_prompt": False,
            "chat_template_kwargs": {"enable_thinking": False}}
    with activity.track("benchmark", t["preset"]) as call:
        resp = httpx.post(f"{t['url']}/chat/completions", json=body, timeout=600.0)
        resp.raise_for_status()
        call.tokens(*usage.tokens_of(resp.json().get("usage")))
    timings = resp.json().get("timings") or {}
    return {"gen_tps": timings.get("predicted_per_second"), "prompt_tps": timings.get("prompt_per_second")}


def run(model_id: str, force: bool = False) -> dict:
    """Benchmark every context of a chat model that has none yet (all of them with ``force``)."""
    from athena.database import model_registry as db
    from athena.database.db import SessionLocal
    r = _redis()
    if not r.set(LOCK_KEY, model_id, nx=True, ex=LOCK_SECONDS):
        return {"skipped": "another benchmark is running"}
    done: dict[int, dict] = {}
    try:
        registry.invalidate()
        row = next((x for x in registry.snapshot() if x["id"] == model_id), None)
        if row is None or row["role"] != "chat" or not row["enabled"]:
            return {"skipped": "not a chat model"}
        if not row["complete"]:
            _status(model=row["name"], model_id=model_id, state="failed",
                    error="The file is incomplete (a download cut short?), so llama.cpp cannot load it.")
            return {"skipped": "incomplete file"}
        have = set() if force else measured(model_id)
        todo = [c["context"] for c in row["contexts"] if c["context"] not in have]
        before = [m.get("id") for m in loading.router_models(loading.target(row["name"], None)["url"])
                  if (m.get("status") or {}).get("value") == "loaded"]
        for i, context in enumerate(todo):
            _status(model=row["name"], model_id=model_id, context=context, step=i + 1, of=len(todo), state="running")
            lane.yield_to_chat(me=BENCH, who="benchmark", pausable=False)
            lane.hold(LANE_SECONDS, what=BENCH)  # background work waits, so it does not swap the model out
            t = loading.target(row["name"], context)
            try:
                result = one(t)
            except LoadFailed as exc:  # smallest contexts go first: the rest would not load either
                logger.warning(f"Benchmark {t['preset']}: {exc}")
                done[context] = {"error": str(exc)[:300]}
                break
            except Exception as exc:
                logger.warning(f"Benchmark {t['preset']}: {exc}")
                done[context] = {"error": str(exc)[:300]}
                continue
            with SessionLocal() as session:
                m = db.get_model(session, model_id)
                db.record_speed(session, m, stats.device_of(t["plan"]), context, gen_tps=result["gen_tps"],
                                prompt_tps=result["prompt_tps"], gpu_layers=t["plan"]["gpu_layers"],
                                source="benchmark", replace=True)
            stats.invalidate()
            done[context] = result
            logger.info(f"Benchmark {t['preset']}: {result}")
        if todo:
            restore(before)
        errors = [v["error"] for v in done.values() if "error" in v]
        _status(model=row["name"], model_id=model_id, state="failed" if errors and len(errors) == len(done) else "done",
                results={str(k): v for k, v in done.items()}, error=errors[0] if errors else None)
        return {"results": done}
    except Exception as exc:
        _status(model_id=model_id, state="failed", error=str(exc)[:300])
        raise
    finally:
        if lane.holder() == BENCH:
            lane.release()
        r.delete(LOCK_KEY)


def restore(before: list[str]) -> None:
    """After a benchmark, load the chat model that was loaded before it, else the default chat model at its default
    context: never leave the last context measured (often the largest) in memory."""
    back = registry.preset_info(before[0]) if before else None
    t = (loading.target(back["model"], back["context"], back["vision"]) if back and back["row"]["role"] == "chat"
         else loading.resting_target())
    if t:
        loading.load(t, for_chat=False)


def start(model_id: str, force: bool = False) -> None:
    """Run in a thread of this process: the API has no GPU of its own to protect, and a worker may not be up."""
    def go():
        try:
            run(model_id, force)
        except Exception as exc:
            logger.warning(f"Benchmark of {model_id} failed: {exc}")
    # In the request's context, so its calls name the admin who started it.
    threading.Thread(target=contextvars.copy_context().run, args=(go,), daemon=True, name=f"bench-{model_id}").start()
