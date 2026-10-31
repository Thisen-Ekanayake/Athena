"""
Chats go first on the GPU.

The GPU router holds one model at a time, so a background batch (feed embeddings, a map's labelling, project
indexing, summaries) that asks for the embedder while someone chats makes the router swap the chat model out and
back for every batch. While a chat is loading or answering it holds a short-lived Redis flag; background work calls
``yield_to_chat()`` between batches, which waits for as long as the flag is up and then carries on by itself, and the
minute runs skip a turn. The flag lapses ``HOLD_SECONDS`` after the chat's last turn or warm-up, so a chat left open
holds nothing.

A benchmark holds the same flag as ``benchmark``, so summaries do not swap its model out mid-measurement, and gives
way itself to a chat (``yield_to_chat(me="benchmark")`` waits only while someone else holds it).

An admin can pause background work (Settings → Models and keys → Activity): feed summaries, cluster labels, feed
embeddings and the maps' model lane then wait at the same points until it is resumed, so an unloaded model stays out
of memory. A call already running finishes; what people ask for (chats, Q&A, reviews, search, project indexing) never
waits. Celery redelivers a task unacknowledged for an hour (``task_acks_late``, the broker's visibility timeout), so a
pause holds one task at most ``PAUSE_HOLD`` and then raises ``Paused``; the task queues itself again.

Whoever waits is listed under ``WAITING`` (one short-lived key each) for the activity page.
"""
from __future__ import annotations

import json
import time
import uuid

from loguru import logger

KEY = "athena:chat_active"
PAUSE_KEY = "athena:background_paused"
WAITING = "athena:lane:waiting:"
HOLD_SECONDS = 90         # a turn refreshes the flag as it streams; a warm-up holds it this long
ASKED_WAIT = 300.0         # work someone asked for (an upload, a benchmark) waits this long at most, then runs
PAUSE_HOLD = 45 * 60.0    # under the broker's one-hour visibility timeout
POLL = 1.0
REQUEUE_SECONDS = 60


class Paused(RuntimeError):
    """Background work was paused for longer than one task may wait; queue the task again."""


def _redis():
    from athena.core.redis_client import get_redis
    return get_redis(decode_responses=True)


def hold(seconds: int = HOLD_SECONDS, what: str = "chat") -> None:
    """Mark a chat as using the model server for the next ``seconds``."""
    try:
        _redis().set(KEY, what, ex=seconds)
    except Exception as exc:
        logger.debug(f"Chat lane flag not set: {exc}")


def release() -> None:
    try:
        _redis().delete(KEY)
    except Exception:
        pass


def chat_active() -> bool:
    try:
        return bool(_redis().exists(KEY))
    except Exception:
        return False


def holder() -> str | None:
    try:
        return _redis().get(KEY)
    except Exception:
        return None


def pause(by: str | None = None) -> dict:
    """Hold background model work until ``resume``."""
    state = {"by": by, "since": time.time()}
    _redis().set(PAUSE_KEY, json.dumps(state))
    return state


def resume() -> None:
    _redis().delete(PAUSE_KEY)


def paused() -> dict | None:
    """{by, since} while background work is paused, else None."""
    try:
        raw = _redis().get(PAUSE_KEY)
        return json.loads(raw) if raw else None
    except Exception:
        return None


def yield_to_chat(max_wait: float | None = None, me: str | None = None, who: str = "background",
                  pausable: bool = True) -> float:
    """Wait while a chat (or a benchmark) holds the model server, unless ``me`` holds it, and while background work
    is paused when ``pausable``; returns the seconds waited. ``who`` (a usage feature) names the waiter on the
    activity page. Background work (``pausable``) waits out the whole chat, but raises ``Paused`` after
    ``PAUSE_HOLD`` seconds of waiting, chat and pause together, so its task can queue itself again. Work someone
    asked for passes ``max_wait`` (``ASKED_WAIT``) and then runs beside the chat."""
    waited = paused_for = 0.0
    key = None
    try:
        while True:
            if pausable and waited + paused_for >= PAUSE_HOLD and (paused() or chat_active()):
                raise Paused(f"{who} waited {int(waited + paused_for)} s for background work to resume")
            if pausable and paused():
                reason = "paused"
                paused_for += POLL
            elif (max_wait is None or waited < max_wait) and chat_active() and (me is None or holder() != me):
                reason = "chat"
                if waited == 0:
                    logger.info("Background model work waits for a chat")
                waited += POLL
            else:
                return waited + paused_for
            key = _waiting(key, who, reason)
            time.sleep(POLL)
    finally:
        if key:
            try:
                _redis().delete(key)
            except Exception:
                pass


def _waiting(key: str | None, who: str, reason: str) -> str:
    """List this waiter for a few seconds more (it refreshes every poll, so a dead process drops off)."""
    key = key or f"{WAITING}{uuid.uuid4().hex[:12]}"
    try:
        r = _redis()
        since = None
        if raw := r.get(key):
            since = json.loads(raw).get("since")
        r.set(key, json.dumps({"who": who, "reason": reason, "since": since or time.time()}), ex=int(POLL * 5))
    except Exception:
        pass
    return key


def waiting() -> list[dict]:
    """Background work waiting now: [{who, reason (chat | paused), since}], longest first."""
    try:
        r = _redis()
        keys = list(r.scan_iter(f"{WAITING}*"))
        rows = [json.loads(v) for v in r.mget(keys) if v] if keys else []
    except Exception:
        return []
    return sorted(rows, key=lambda w: w.get("since") or 0)
