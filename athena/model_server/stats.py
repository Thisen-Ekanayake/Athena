"""
Speeds per model and context for this machine (athena.model_server.speed), from the registry and its benchmarks,
cached for a few seconds per process; and recording a chat turn's speed.
"""
from __future__ import annotations

import time

from loguru import logger

from athena.model_server import gpu, registry, speed

CACHE_SECONDS = 15.0
MIN_TOKENS = 24           # shorter answers say more about the prompt than about the model's speed
_cache: tuple[float, dict] | None = None


def device_of(plan: dict) -> str:
    return "cpu" if plan.get("device") == "cpu" else gpu.device_key()


def benches() -> list[dict]:
    """Benchmarks of the files as they are now (an older file's do not count)."""
    from athena.database import model_registry as db
    from athena.database.db import SessionLocal
    current = {r["id"]: r["fingerprint"] for r in registry.snapshot()}
    try:
        with SessionLocal() as session:
            return [{"model_id": str(b.model_id), "context": b.context, "device": b.device, "gen_tps": b.gen_tps,
                     "prompt_tps": b.prompt_tps, "load_seconds": b.load_seconds, "samples": b.samples,
                     "source": b.source, "gpu_layers": b.gpu_layers,
                     "updated_at": b.updated_at.isoformat() if b.updated_at else None}
                    for b in db.benchmarks(session) if current.get(str(b.model_id)) == b.fingerprint]
    except Exception as exc:
        logger.debug(f"No benchmarks: {exc}")
        return []


def estimates() -> dict[str, dict[int, dict]]:
    global _cache
    if _cache and time.monotonic() - _cache[0] < CACHE_SECONDS:
        return _cache[1]
    rows = registry.snapshot()
    out = speed.estimates(rows, benches(), device_of) if rows else {}
    _cache = (time.monotonic(), out)
    return out


def invalidate() -> None:
    global _cache
    _cache = None


def record_turn(preset: str, timings: dict | None) -> dict | None:
    """Fold a chat answer's llama.cpp timings into its model's speed at that context; returns what the message
    keeps ({tps, prompt_tps, device, gpu_layers, layers, context}), or None for a model the registry does not know."""
    from athena.database import model_registry as db
    from athena.database.db import SessionLocal
    found = registry.preset_info(preset)
    if not found:
        return None
    plan = found["plan"]
    out = {"device": plan["device"], "gpu_layers": plan["gpu_layers"], "layers": plan["layers"],
           "context": found["context"], "tps": None, "prompt_tps": None}
    timings = timings or {}
    if timings.get("predicted_per_second"):
        out["tps"] = round(float(timings["predicted_per_second"]), 1)
    if timings.get("prompt_per_second") and (timings.get("prompt_n") or 0) >= 64:
        out["prompt_tps"] = round(float(timings["prompt_per_second"]), 1)
    if out["tps"] and (timings.get("predicted_n") or 0) >= MIN_TOKENS:
        try:
            with SessionLocal() as session:
                m = db.by_name(session, found["model"])
                if m is not None:
                    db.record_speed(session, m, device_of(plan), found["context"], gen_tps=out["tps"],
                                    prompt_tps=out["prompt_tps"], gpu_layers=plan["gpu_layers"])
            invalidate()
        except Exception as exc:
            logger.debug(f"Turn speed not recorded: {exc}")
    return out
