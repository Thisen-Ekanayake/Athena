"""
What the model servers are doing, for Settings → Models and keys → Activity.

Every model call goes through ``track`` (``start`` and ``finish`` for a stream): while it runs it sits in a Redis
hash of calls in flight; when it ends it goes to a list of recent calls and to today's totals per feature. No prompt
or answer text is kept, only the feature, the model, who asked, token counts and times.

Each local router holds one model at a time, so a call for another preset than the one its router last served
swapped models. Those swaps, the loads Athena starts itself and the unloads an admin asks for go to a list of recent
swaps. Everything here is best effort: a Redis error never fails a model call.
"""
from __future__ import annotations

import json
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import date

from loguru import logger

LIVE = "athena:llm:live"
LOG = "athena:llm:log"
SWAPS = "athena:llm:swaps"
TODAY = "athena:llm:today:{day}"
LAST = "athena:llm:last:{server}"
LOG_SIZE = 100
SWAP_SIZE = 50
LIVE_MAX_AGE = 900.0       # a call older than the longest client timeout died with its process
TODAY_TTL = 3 * 86400

# Who the request being served belongs to (set by the API's login check): a call that names no user is theirs. Celery
# tasks and start-up have none, so their calls are background or system work.
acting_user: ContextVar[str | None] = ContextVar("athena_acting_user", default=None)

# What each feature is called on the page: the usage page's names, and the calls it does not count.
EXTRA_LABELS = {"benchmark": "Benchmarks", "connection_test": "Connection tests", "startup": "Start-up",
                "other": "Other"}


def label(feature: str) -> str:
    from athena.core.usage import FEATURES
    return FEATURES.get(feature) or EXTRA_LABELS.get(feature) or feature


def _redis():
    from athena.core.redis_client import get_redis
    return get_redis(decode_responses=True)


def server_of(model: str | None) -> str | None:
    """"gpu" or "cpu": the local router that serves this preset; None for a model the registry does not know."""
    if not model:
        return None
    try:
        from athena.model_server import registry
        found = registry.preset_info(model)
    except Exception:
        return None
    return found["server"] if found else None


@dataclass
class Call:
    feature: str
    model: str
    kind: str = "chat"
    user_id: str | None = None
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    started: float = field(default_factory=time.time)
    server: str | None = None
    swapped: bool = False
    input_tokens: int = 0
    output_tokens: int = 0
    done: bool = False

    def tokens(self, input_tokens: int | None, output_tokens: int | None = 0) -> None:
        self.input_tokens, self.output_tokens = int(input_tokens or 0), int(output_tokens or 0)

    def public(self) -> dict:
        return {"id": self.id, "feature": self.feature, "model": self.model, "kind": self.kind,
                "user_id": self.user_id, "started": self.started, "server": self.server, "swapped": self.swapped}


def start(feature: str | None, model: str | None, kind: str = "chat", user_id=None) -> Call:
    """A call begins: it is listed as in flight, and a swap is noted if its router held another preset."""
    user_id = user_id or acting_user.get()
    call = Call(feature=feature or "other", model=model or "", kind=kind,
                user_id=str(user_id) if user_id else None)
    try:
        r = _redis()
        call.server = server_of(call.model)
        if call.server:
            previous = r.getset(LAST.format(server=call.server), call.model)
            if previous != call.model:
                call.swapped = True
                swap(call.server, previous, call.model, cause=call.feature)
        r.hset(LIVE, call.id, json.dumps(call.public()))
    except Exception as exc:
        logger.debug(f"Activity not recorded: {exc}")
    return call


def finish(call: Call, error: BaseException | None = None) -> None:
    """A call ends: off the in-flight list, onto the recent list and today's totals. Safe to call twice."""
    if call.done:
        return
    call.done = True
    seconds = round(time.time() - call.started, 2)
    status = "done" if error is None else "stopped" if _stopped(error) else "failed"
    entry = call.public() | {"seconds": seconds, "status": status, "error": _error_name(error),
                             "input_tokens": call.input_tokens, "output_tokens": call.output_tokens}
    try:
        today = TODAY.format(day=date.today().isoformat())
        pipe = _redis().pipeline()
        pipe.hdel(LIVE, call.id)
        pipe.lpush(LOG, json.dumps(entry))
        pipe.ltrim(LOG, 0, LOG_SIZE - 1)
        pipe.hincrby(today, f"{call.feature}|calls", 1)
        pipe.hincrby(today, f"{call.feature}|input_tokens", call.input_tokens)
        pipe.hincrby(today, f"{call.feature}|output_tokens", call.output_tokens)
        pipe.hincrbyfloat(today, f"{call.feature}|seconds", seconds)
        if status == "failed":
            pipe.hincrby(today, f"{call.feature}|failed", 1)
        pipe.expire(today, TODAY_TTL)
        pipe.execute()
    except Exception as exc:
        logger.debug(f"Activity not recorded: {exc}")


@contextmanager
def track(feature: str | None, model: str | None, kind: str = "chat", user_id=None):
    """``with track("summary", model) as call: ...; call.tokens(i, o)``"""
    call = start(feature, model, kind, user_id)
    try:
        yield call
    except BaseException as exc:
        finish(call, exc)
        raise
    finish(call)


def _stopped(error: BaseException) -> bool:
    import asyncio
    return isinstance(error, (GeneratorExit, asyncio.CancelledError, KeyboardInterrupt))


def _error_name(error: BaseException | None) -> str | None:
    """The kind of failure without its message, which may quote the prompt: "APITimeoutError", "HTTP 503"."""
    if error is None or _stopped(error):
        return None
    status = getattr(error, "status_code", None) or getattr(getattr(error, "response", None), "status_code", None)
    return f"{type(error).__name__}{f' (HTTP {status})' if status else ''}"


# ── swaps ────────────────────────────────────────────────────────────


def swap(server: str, before: str | None, after: str | None, cause: str, seconds: float | None = None) -> None:
    """Note that ``server``'s router went from ``before`` to ``after`` (None: nothing loaded) because of ``cause``."""
    try:
        r = _redis()
        if after is None:
            r.delete(LAST.format(server=server))
        else:
            r.set(LAST.format(server=server), after)
        r.lpush(SWAPS, json.dumps({"at": time.time(), "server": server, "before": before, "after": after,
                                   "cause": cause, "seconds": round(seconds, 1) if seconds is not None else None}))
        r.ltrim(SWAPS, 0, SWAP_SIZE - 1)
    except Exception as exc:
        logger.debug(f"Swap not recorded: {exc}")


def loaded(server: str, preset: str, cause: str, seconds: float) -> None:
    """A load Athena asked for finished (``loading.load``); a swap if the router last served something else."""
    try:
        previous = _redis().get(LAST.format(server=server))
    except Exception:
        previous = None
    swap(server, previous if previous != preset else None, preset, cause, seconds)


# ── reading it back ──────────────────────────────────────────────────


def _rows(raw: list[str]) -> list[dict]:
    out = []
    for item in raw:
        try:
            out.append(json.loads(item))
        except (TypeError, ValueError):
            continue
    return out


def live() -> list[dict]:
    """Calls in flight, oldest first; entries left by a process that died are dropped."""
    try:
        r = _redis()
        found = r.hgetall(LIVE)
    except Exception:
        return []
    now, calls, dead = time.time(), [], []
    for key, value in found.items():
        rows = _rows([value])
        if not rows or now - rows[0].get("started", 0) > LIVE_MAX_AGE:
            dead.append(key)
            continue
        calls.append(rows[0] | {"elapsed": round(now - rows[0]["started"], 1)})
    if dead:
        try:
            r.hdel(LIVE, *dead)
        except Exception:
            pass
    return sorted(calls, key=lambda c: c["started"])


def recent(limit: int = LOG_SIZE) -> list[dict]:
    try:
        return _rows(_redis().lrange(LOG, 0, limit - 1))
    except Exception:
        return []


def swaps(limit: int = SWAP_SIZE) -> list[dict]:
    try:
        return _rows(_redis().lrange(SWAPS, 0, limit - 1))
    except Exception:
        return []


def today() -> list[dict]:
    """Today's calls per feature: {feature, label, calls, failed, input_tokens, output_tokens, seconds}, busiest
    first."""
    try:
        raw = _redis().hgetall(TODAY.format(day=date.today().isoformat()))
    except Exception:
        return []
    by: dict[str, dict] = {}
    for key, value in raw.items():
        feature, _, name = key.rpartition("|")
        row = by.setdefault(feature, {"feature": feature, "label": label(feature), "calls": 0, "failed": 0,
                                      "input_tokens": 0, "output_tokens": 0, "seconds": 0.0})
        row[name] = round(float(value), 1) if name == "seconds" else int(float(value))
    return sorted(by.values(), key=lambda r: -r["seconds"])
