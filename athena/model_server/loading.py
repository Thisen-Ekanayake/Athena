"""
Loading a model before it is needed, and what the page shows while it loads.

The router does not report how far a load has got, only its status (unloaded, loading, loaded, failed). Athena keeps
when a load started and how long the same model at the same context took last time (else its size over this
machine's load speed), and shows stages from the router (waiting for another model to finish, swapping it out,
loading) with a bar timed from that estimate. Past the estimate the bar slows towards 99% rather than claiming done.

A load Athena starts (``warm``: the moment someone picks a model or starts typing, and before every turn) runs in a
thread that asks the router to load the preset, retries while the router is full (its model busy with a background
batch, which ``lane`` makes give way), and records how long the load took.
"""
from __future__ import annotations

import json
import math
import threading
import time

import httpx
from loguru import logger

from athena.model_server import lane

LOAD_KEY = "athena:model_load:{preset}"
LOAD_TIMEOUT = 600.0
POLL = 0.5
_threads: dict[str, threading.Thread] = {}
_guard = threading.Lock()


def _redis():
    from athena.core.redis_client import get_redis
    return get_redis(decode_responses=True)


def router_models(url: str) -> list[dict]:
    """What a router lists now (no cache); [] when it does not answer."""
    from athena.core import llm
    try:
        resp = httpx.get(f"{llm.server_root(url)}/models", timeout=3.0)
        resp.raise_for_status()
        return resp.json().get("data") or []
    except (httpx.HTTPError, ValueError):
        return []


def _status(entry: dict | None) -> str:
    status = (entry or {}).get("status") or {}
    if status.get("failed"):
        return "failed"
    return status.get("value") or "unknown"


def target(model: str, context: int | None, vision: bool = False) -> dict | None:
    """The preset for ``model`` at ``context`` and the router serving it: {preset, url, server, plan, row,
    context}; None when the registry does not know the model."""
    from athena.core import llm
    from athena.model_server import registry
    row = registry.find(model)
    if row is None:
        return None
    contexts = {c["context"]: c for c in row["contexts"]}
    c = contexts.get(context or row["default_context"]) or contexts.get(row["default_context"]) or row["contexts"][0]
    preset = c["vision_preset"] if vision and c["vision_preset"] else c["preset"]
    url = registry.cpu_base_url() if c["server"] == "cpu" else llm.chat_base_url()
    return {"preset": preset, "url": url, "server": c["server"], "plan": c["plan"], "row": row,
            "context": c["context"]}


def target_of(preset: str) -> dict | None:
    """``target`` for a preset name (what a chat turn sends)."""
    from athena.model_server import registry
    found = registry.preset_info(preset)
    return target(found["model"], found["context"], found["vision"]) if found else None


def _record(t: dict, seconds: float) -> None:
    from athena.database import model_registry as db
    from athena.database.db import SessionLocal
    from athena.model_server import gpu
    try:
        with SessionLocal() as session:
            m = db.by_name(session, t["row"]["name"])
            if m is not None:
                device = "cpu" if t["plan"]["device"] == "cpu" else gpu.device_key()
                db.record_speed(session, m, device, t["context"], load_seconds=seconds,
                                gpu_layers=t["plan"]["gpu_layers"])
    except Exception as exc:
        logger.debug(f"Load time not recorded: {exc}")


def expected_seconds(t: dict) -> float:
    from athena.model_server import speed, stats
    est = stats.estimates().get(t["row"]["name"], {}).get(t["context"]) or {}
    fallback = speed.LOAD_OVERHEAD_S + t["row"]["size_bytes"] / speed.DEFAULT_LOAD_BYTES_PER_S
    return float(est.get("load_seconds") or fallback)


def ensure_loaded(t: dict, timeout: float = LOAD_TIMEOUT, for_chat: bool = True) -> bool:
    """Load ``t``'s preset and wait until it is ready; True when it is. Records the load time. A load for a chat
    keeps background work waiting (``lane``); a benchmark's does not, or it would wait for itself."""
    preset, url = t["preset"], t["url"]
    from athena.core import llm
    key = LOAD_KEY.format(preset=preset)
    started = None
    deadline = time.monotonic() + timeout
    asked = False
    while time.monotonic() < deadline:
        listed = {m.get("id"): m for m in router_models(url)}
        status = _status(listed.get(preset))
        if status == "loaded":
            if started is not None:
                _record(t, time.time() - started)
            _clear(key)
            return True
        if status == "failed" and asked:
            _clear(key)
            return False
        if status == "loading" and started is None:
            started = time.time()
            _mark(key, started, t)
        if status in ("unloaded", "failed", "unknown") and preset in listed:
            _mark(key, None, t)  # the router first unloads the model it holds; the request returns once it starts
            try:
                resp = httpx.post(f"{llm.server_root(url)}/models/load", json={"model": preset}, timeout=600.0)
                if resp.status_code < 400:
                    asked, started = True, time.time()
                    _mark(key, started, t)
                elif "already" not in resp.text:  # full: its model is busy with a batch, which gives way
                    _mark(key, None, t, waiting=True)
            except httpx.HTTPError as exc:
                logger.info(f"Loading {preset}: {exc}")
        elif preset not in listed and not listed:
            return False  # the router is not there
        if for_chat:
            lane.hold(what=preset)
        time.sleep(POLL)
    _clear(key)
    return False


def _mark(key: str, started: float | None, t: dict, waiting: bool = False) -> None:
    try:
        _redis().set(key, json.dumps({"started": started, "expected": expected_seconds(t), "waiting": waiting}),
                     ex=int(LOAD_TIMEOUT))
    except Exception:
        pass


def _clear(key: str) -> None:
    try:
        _redis().delete(key)
    except Exception:
        pass


def warm(model: str, context: int | None, vision: bool = False) -> dict | None:
    """Start loading in the background (one thread per preset); returns the state now."""
    t = target(model, context, vision)
    if t is None:
        return None
    warm_target(t)
    return state_of(t)


def warm_target(t: dict) -> None:
    lane.hold(what=t["preset"])
    with _guard:
        running = _threads.get(t["preset"])
        if not (running and running.is_alive()):
            thread = threading.Thread(target=_safe_load, args=(t,), daemon=True, name=f"warm-{t['preset']}")
            _threads[t["preset"]] = thread
            thread.start()


def _safe_load(t: dict) -> None:
    try:
        ensure_loaded(t)
    except Exception as exc:
        logger.warning(f"Warming {t['preset']} failed: {exc}")


def _label(preset: str | None) -> str | None:
    """A preset as people read it: "qwen3.5-9b at 20k", "qwen3.5-9b at 8k with images"; the name otherwise."""
    from athena.model_server import presets, registry
    found = registry.preset_info(preset) if preset else None
    if not found or found["row"]["role"] == "embed":
        return found["model"] if found else preset
    return f"{found['model']} at {presets.ctx_label(found['context'])}{' with images' if found['vision'] else ''}"


def progress(elapsed: float, expected: float) -> float:
    """0..0.99: in step with the estimate up to 90%, then easing towards 99% however long it takes."""
    expected = max(expected, 0.5)
    if elapsed <= expected:
        return 0.9 * elapsed / expected
    return min(0.9 + 0.09 * (1 - math.exp(-(elapsed - expected) / expected)), 0.99)


def state(model: str, context: int | None, vision: bool = False) -> dict | None:
    """What the page shows for ``model`` at ``context`` (``state_of``); None for a model the registry lacks."""
    t = target(model, context, vision)
    return state_of(t) if t else None


def state_of(t: dict) -> dict:
    """{preset, status, device, stages, progress, eta_seconds, expected_seconds, other}. status is loaded | loading
    | waiting | swapping | unloaded | failed | offline."""
    from athena.model_server import gpu
    model = t["row"]["name"]
    listed = router_models(t["url"])
    by_id = {m.get("id"): m for m in listed}
    status = _status(by_id.get(t["preset"])) if listed else "offline"
    others = [m.get("id") for m in listed if m.get("id") != t["preset"] and _status(m) in ("loaded", "loading")]
    marked: dict = {}
    try:
        raw = _redis().get(LOAD_KEY.format(preset=t["preset"]))
        marked = json.loads(raw) if raw else {}
    except Exception:
        pass
    expected = float(marked.get("expected") or expected_seconds(t))
    plan, info = t["plan"], gpu.gpu()
    device = {"kind": plan["device"], "gpu": (info or {}).get("name") if plan["device"] != "cpu" else None,
              "gpu_layers": plan["gpu_layers"], "layers": plan["layers"], "vram_mb": plan["vram_mb"],
              "ram_mb": plan["ram_mb"]}
    other = _label(next((o for o in others if o), None))
    if status in ("unloaded", "unknown") and (marked.get("waiting") or (other and t["server"] == "gpu")):
        status = "waiting" if marked.get("waiting") else ("swapping" if marked else "unloaded")
    elapsed = time.time() - marked["started"] if marked.get("started") else 0.0
    if status == "loading":
        pct = progress(elapsed, expected)
        eta = max(expected - elapsed, 0.0)
    else:
        pct = 1.0 if status == "loaded" else 0.0
        eta = expected if status != "loaded" else 0.0
    where = {"gpu": "onto the GPU", "split": "onto the GPU and CPU", "cpu": "into memory (CPU)"}[plan["device"]]
    stages = []
    if other and t["server"] == "gpu" and status != "loaded":
        stages.append({"label": f"{'Waiting for' if status == 'waiting' else 'Unloading'} {other}",
                       "state": "active" if status in ("waiting", "swapping") else "done"})
    stages.append({"label": f"Reading weights {where}",
                   "state": "active" if status == "loading" else ("done" if status == "loaded" else "pending")})
    stages.append({"label": "Ready", "state": "done" if status == "loaded" else "pending"})
    return {"model": model, "preset": t["preset"], "context": t["context"], "server": t["server"], "status": status,
            "device": device, "stages": stages, "progress": round(pct, 3), "eta_seconds": round(eta, 1),
            "expected_seconds": round(expected, 1), "elapsed_seconds": round(elapsed, 1), "other": other}
