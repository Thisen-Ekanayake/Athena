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

An admin can pause background work (Settings → Models and keys → Activity), all of it or one group (``GROUPS``):
the feed's summaries, cluster labels and embeddings, or the maps' model work. Paused work waits at the same points
until it is resumed, so an unloaded model stays out of memory. A call already running finishes; what people ask for
(chats, Q&A, reviews, search, project indexing) never waits. Celery redelivers a task unacknowledged for an hour
(``task_acks_late``, the broker's visibility timeout), so a pause holds one task at most ``PAUSE_HOLD`` and then raises
``Paused``; the task queues itself again.

Whoever waits is listed under ``WAITING`` (one short-lived key each) for the activity page.
"""
from __future__ import annotations

import json
import time
import uuid

from loguru import logger

KEY = "athena:chat_active"
PAUSE_KEY = "athena:background_paused"            # before groups: everything; taken over by both groups
GROUP_KEY = "athena:background_paused:{group}"
# What a pause can hold, and which background features each group covers.
GROUPS = {
    "feed": {"label": "Feed", "covers": "summaries, cluster labels and embeddings of new items",
             "features": ("summary", "cluster_label", "feed_embed")},
    "maps": {"label": "Maps", "covers": "embedding and labelling for map builds and refreshes",
             "features": ("map_build", "map_embed")},
}
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


def group_of(feature: str | None) -> str | None:
    """The group (``GROUPS``) a background feature belongs to; None for anything else."""
    return next((g for g, spec in GROUPS.items() if feature in spec["features"]), None)


def _groups(group: str | None) -> list[str]:
    if group is not None and group not in GROUPS:
        raise ValueError(f"No background group {group!r}")
    return [group] if group else list(GROUPS)


def pause(group: str | None = None, by: str | None = None) -> dict:
    """Hold one group's background model work, or all of it, until ``resume``; a group already paused keeps who
    paused it and since when. Returns every group's state (``pauses``)."""
    state = json.dumps({"by": by, "since": time.time()})
    for g in _groups(group):
        _redis().set(GROUP_KEY.format(group=g), state, nx=True)
    return pauses()


def resume(group: str | None = None) -> None:
    keys = [GROUP_KEY.format(group=g) for g in _groups(group)]
    _redis().delete(*keys, PAUSE_KEY)


def pauses() -> dict[str, dict | None]:
    """{group: {by, since} or None}. A pause from before groups pauses every group once, and is then gone."""
    try:
        r = _redis()
        if legacy := r.get(PAUSE_KEY):
            for g in GROUPS:
                r.set(GROUP_KEY.format(group=g), legacy, nx=True)
            r.delete(PAUSE_KEY)
        out = {}
        for g in GROUPS:
            raw = r.get(GROUP_KEY.format(group=g))
            out[g] = json.loads(raw) if raw else None
        return out
    except Exception:
        return {g: None for g in GROUPS}


def paused(group: str | None = None) -> dict | None:
    """{by, since} while ``group`` is paused; without a group, only while every group is (the earliest pause)."""
    states = pauses()
    if group is not None:
        return states.get(group)
    if not all(states.values()):
        return None
    return min(states.values(), key=lambda s: s.get("since") or 0)


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
            held = pausable and bool(paused(group_of(who)) if group_of(who) else paused())
            if pausable and waited + paused_for >= PAUSE_HOLD and (held or chat_active()):
                raise Paused(f"{who} waited {int(waited + paused_for)} s for background work to resume")
            if held:
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
