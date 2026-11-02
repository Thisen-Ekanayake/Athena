"""
Whose turn the GPU is: background work grouped by model, so the router swaps as rarely as it can.

The GPU router holds one model at a time and a swap costs seconds (a load from the page cache is ~4 s), longer
than one batch of work. Background work used to ask for its model batch by batch, so a map embedding its abstracts
and the feed's summaries swapped the 9B and the embedder every second (2026-11-02: one map batch every ~80 s). Like
a disk's elevator, the model in memory now keeps the GPU while anyone has work for it, and work for another model
waits until

- nobody has used the loaded model for ``IDLE`` seconds,
- it has a higher priority than the work using the loaded model (it goes once the call in hand ends), or
- the loaded model has had ``TURN`` seconds while work of the same priority waited, or the other work has waited
  ``AGING`` seconds (then it gets the next turn whatever its priority).

Priorities: ``ASKED`` (someone waits for it: a map they built or asked to read, an upload), ``ROUTINE`` (the feed),
``BACKLOG`` (scheduled map refreshes and the leftovers of maps nobody asked about). Chats come before all of them
through the lane's own flag. Work for the loaded model never waits on priority: the feed's summaries run beside a
map's labelling on the 9B.

Redis holds the turn (model, since) and when each model was last used at each priority; the waiters are the lane's
``WAITING`` keys, which carry model and priority, and calls in flight come from ``activity``. Only presets on the
GPU router take turns: the CPU router keeps its models loaded beside it, and a hosted endpoint has no swaps.
"""
from __future__ import annotations

import json
import os
import socket
import time
from contextlib import contextmanager
from contextvars import ContextVar

TURN_KEY = "athena:lane:turn"
USED_KEY = "athena:lane:used"     # hash "model|priority|process" -> when work last passed the gate
TURN = 300.0     # a model keeps the GPU this long while work of the same priority waits for another
IDLE = 30.0      # unused this long, the loaded model gives way at once (covers the gaps between a worker's calls)
AGING = 1800.0   # work that waited this long gets the next turn, whatever its priority
ACTIVE = 60.0     # used this recently by higher-priority work, a model is theirs: lower work on it waits too
DRAIN_MAX = 300.0  # a swap waits for a call in flight at most this old: older, its process is taken for dead

BACKLOG, ROUTINE, ASKED = 0, 1, 2
NAMES = {BACKLOG: "backlog", ROUTINE: "routine", ASKED: "asked for"}
# Work that does not say otherwise. Maps' work is backlog unless a task says someone asked for it (``asked``).
DEFAULTS = {"summary": ROUTINE, "cluster_label": ROUTINE, "feed_embed": ROUTINE, "project_index": ASKED,
            "map_proposal": ASKED}

_current: ContextVar[int | None] = ContextVar("athena_gpu_priority", default=None)


def _redis():
    from athena.core.redis_client import get_redis
    return get_redis(decode_responses=True)


@contextmanager
def priority(level: int):
    """Work done inside counts at ``level``: ``with turns.priority(turns.ASKED): build(...)``."""
    token = _current.set(level)
    try:
        yield
    finally:
        _current.reset(token)


def priority_of(who: str | None) -> int:
    current = _current.get()
    if current is not None:
        return current
    return DEFAULTS.get(who or "", BACKLOG)


def takes_turns(model: str | None) -> bool:
    """Whether ``model`` is on the GPU router, the one that swaps."""
    if not model:
        return False
    from athena.model_server import activity
    return activity.server_of(model) == "gpu"


def turn() -> dict | None:
    """{model, since} of the model whose turn it is; None before anyone asked."""
    try:
        raw = _redis().get(TURN_KEY)
        return json.loads(raw) if raw else None
    except Exception:
        return None


def _me() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def used(model: str, level: int) -> None:
    """Work at ``level`` in this process passed the gate for ``model`` (and is about to call it)."""
    try:
        _redis().hset(USED_KEY, f"{model}|{level}|{_me()}", time.time())
    except Exception:
        pass


def _stamps(now: float, window: float) -> list[tuple[str, int, str | None]]:
    """[(model, priority, process)] used within ``window`` seconds."""
    try:
        stamps = _redis().hgetall(USED_KEY)
    except Exception:
        return []
    out = []
    for key, at in stamps.items():
        parts = key.split("|")
        if len(parts) < 2 or now - float(at) >= window:
            continue
        out.append((parts[0], int(parts[1]), parts[2] if len(parts) > 2 else None))
    return out


def _demand(now: float, waiters: list[dict], live: list[dict], asking: str | None = None) -> dict[str, dict]:
    """{model: {priority, since, waiting}}: who wants each GPU model now. ``since`` is the oldest wait (a model only
    in use has none); ``waiting`` is whether anyone waits for it. This process's own recent use of a model other than
    the one it is ``asking`` for does not count: a map job moving from the 9B to the embedder is not held up by
    itself (it waited the whole ``IDLE`` window while summaries took the 9B back, 2026-11-02)."""
    out: dict[str, dict] = {}

    def add(model: str, level: int, since: float | None = None):
        d = out.setdefault(model, {"priority": level, "since": None, "waiting": False})
        d["priority"] = max(d["priority"], level)
        if since is not None:
            d["waiting"] = True
            d["since"] = since if d["since"] is None else min(d["since"], since)

    for w in waiters:
        if w.get("model") and w.get("priority") is not None:
            add(w["model"], int(w["priority"]), float(w.get("since") or now))
    me = _me()
    for model, level, who in _stamps(now, IDLE):
        if who != me or model == asking:
            add(model, level)
    for call in live:
        if call.get("server") == "gpu" and call.get("model"):
            add(call["model"], DEFAULTS.get(call.get("feature") or "", BACKLOG))
    return out


def _target(current: dict | None, demand: dict[str, dict], now: float) -> str | None:
    """The model whose turn it should be."""
    def best(models):
        return max(models, key=lambda m: (demand[m]["priority"], -(demand[m]["since"] or now)))

    model = (current or {}).get("model")
    if model not in demand:  # nobody uses the loaded model: the most pressing work goes
        return best(demand) if demand else model
    others = [m for m, d in demand.items() if m != model and d["waiting"]]
    if not others:
        return model
    other = best(others)
    mine, theirs = demand[model]["priority"], demand[other]["priority"]
    held = now - float(current.get("since") or now)
    if theirs > mine:
        return other
    if held >= TURN and (theirs == mine or now - demand[other]["since"] >= AGING):
        return other
    return model


def _busy_above(model: str, level: int, now: float, live: list[dict]) -> int | None:
    """The highest priority above ``level`` that is calling ``model`` now or used it in the last ``ACTIVE`` seconds,
    if any (a thinking call can outlast the window, so calls in flight count too)."""
    me = _me()
    levels = [lv for m, lv, who in _stamps(now, ACTIVE) if m == model and who != me]
    levels += [int(c["priority"]) for c in live if c.get("model") == model and c.get("priority") is not None
               and now - float(c.get("started") or now) < DRAIN_MAX]
    top = max(levels, default=None)
    return top if top is not None and top > level else None


def check(model: str, level: int, waited: float = 0.0) -> str | None:
    """None when work at ``level`` may call ``model`` now; otherwise what it waits for (the activity page's line).

    Moves the turn on when it should; a model whose turn it is still waits for calls in flight on another model to
    end, so a call is never cut off by a swap. The model server answers one request at a time, so while work of a
    higher priority is using the model, lower work on the same model waits as well (2026-11-02: summaries took half
    the 9B from a map someone was waiting for), until it has ``waited`` ``AGING`` seconds."""
    from athena.model_server import activity, lane
    now = time.time()
    live = activity.live()
    demand = _demand(now, lane.waiting(), live, asking=model)
    demand.setdefault(model, {"priority": level, "since": now, "waiting": True})
    current = turn()
    target = _target(current, demand, now)
    if target and target != (current or {}).get("model"):
        try:
            _redis().set(TURN_KEY, json.dumps({"model": target, "since": now}))
        except Exception:
            return None  # no Redis: no turns, as before
    if target != model:
        return f"{target} has the GPU"
    above = _busy_above(model, level, now, live)
    if above is not None and waited < AGING:
        return f"{NAMES[above]} work is using {model}"
    # A process that died mid-call leaves its call listed (activity drops it once it is sure); a swap waits at
    # most DRAIN_MAX for one, not the 15 minutes it took the list to forget one on 2026-11-02.
    busy = sorted({c["model"] for c in live if c.get("server") == "gpu" and c.get("model") not in (None, model)
                   and now - float(c.get("started") or now) < DRAIN_MAX})
    if busy:
        return f"{busy[0]} is finishing a call"
    return None
