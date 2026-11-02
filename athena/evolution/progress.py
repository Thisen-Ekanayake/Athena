"""
How far a map's open problems have got: reading PDFs, labelling sentences, embedding, building and naming themes.

Full text and the GPU lane take hours on a busy card, and a map is ``ready`` all the while, so its gaps tab said
"no open problems" with no reason (2026-11-02). Each step writes its stage and counts here (Redis, one key per map,
kept a couple of days); the gaps route returns it, with what the lane waits for, and the gaps tab shows a line with
an estimate from the stage's rate so far.
"""
from __future__ import annotations

import json
import time

KEY = "athena:evo:progress:{slug}"
TTL = 2 * 86400
STAGES = {
    "queued": "Waiting for the map worker",
    "reading": "Reading the papers' PDFs",
    "labelling": "Labelling citing sentences",
    "gaps": "Checking stated limitations",
    "embedding": "Embedding passages and gaps",
    "themes": "Grouping gaps into themes",
    "naming": "Naming the themes",
    "done": "Open problems are up to date",
}


def _redis():
    from athena.core.redis_client import get_redis
    return get_redis(decode_responses=True)


def get(slug: str) -> dict | None:
    """{stage, label, done, total, started, updated, eta_seconds, note} or None."""
    try:
        raw = _redis().get(KEY.format(slug=slug))
    except Exception:
        return None
    if not raw:
        return None
    state = json.loads(raw)
    state["label"] = STAGES.get(state.get("stage"), state.get("stage"))
    done, total, started = state.get("done") or 0, state.get("total"), state.get("started")
    state["eta_seconds"] = None
    if total and done and started and done < total:
        rate = done / max(time.time() - started, 1e-6)
        state["eta_seconds"] = round((total - done) / rate)
    return state


def _write(slug: str, state: dict) -> None:
    try:
        _redis().set(KEY.format(slug=slug), json.dumps(state), ex=TTL)
    except Exception:
        pass


def stage(slug: str | None, name: str, total: int | None = None, note: str | None = None) -> None:
    """``slug``'s work is at stage ``name`` now, with ``total`` items to do (counted with ``advance``). A note
    (why the PDFs were not read) stays until the next stage that sets one."""
    if not slug:
        return
    previous = get(slug) or {}
    _write(slug, {"stage": name, "done": 0, "total": total, "started": time.time(), "updated": time.time(),
                  "note": note if note is not None else previous.get("note") if name != "queued" else None})


def advance(slug: str | None, n: int = 1) -> None:
    if not slug:
        return
    state = get(slug)
    if state is None:
        return
    state["done"] = (state.get("done") or 0) + n
    state["updated"] = time.time()
    for k in ("label", "eta_seconds"):
        state.pop(k, None)
    _write(slug, state)
