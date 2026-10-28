"""
Chats go first on the GPU.

The GPU router holds one model at a time, so a background batch (feed embeddings, a map's labelling, project
indexing, summaries) that asks for the embedder while someone chats makes the router swap the chat model out and
back for every batch. While a chat is loading or answering it holds a short-lived Redis flag; background work calls
``yield_to_chat()`` between batches, which waits while the flag is up (up to ``MAX_WAIT``, so a chat left open never
stalls the pipeline for good), and the minute runs skip a turn.

A benchmark holds the same flag as ``benchmark``, so summaries do not swap its model out mid-measurement, and gives
way itself to a chat (``yield_to_chat(me="benchmark")`` waits only while someone else holds it).
"""
from __future__ import annotations

import time

from loguru import logger

KEY = "athena:chat_active"
HOLD_SECONDS = 90         # a turn refreshes the flag as it streams; a warm-up holds it this long
MAX_WAIT = 300.0
POLL = 1.0


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


def yield_to_chat(max_wait: float = MAX_WAIT, me: str | None = None) -> float:
    """Wait while a chat (or a benchmark) holds the model server, unless ``me`` holds it; returns the seconds
    waited."""
    waited = 0.0
    while waited < max_wait and chat_active() and (me is None or holder() != me):
        if waited == 0:
            logger.info("Background model work waits for a chat")
        time.sleep(POLL)
        waited += POLL
    return waited
