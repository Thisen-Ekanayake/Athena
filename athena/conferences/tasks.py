"""
The conference pipeline's Celery tasks, on the default queue.

A sync (weekly, or an admin's button) reads the Anthology and stores it, works out the rising terms, then hands on
to two chains side by side: citation counts and missing abstracts (network), and embedding and topics → summaries
(GPU). Each long step runs in slices of
``SLICE_SECONDS`` and queues the next slice itself, so the first build (about 60,000 papers, hours of embedding)
never holds a worker thread for long, and a restart picks up where it stopped. One run of each step at a time
(a Redis lock). An admin's sync takes turns on the GPU at the feed's priority; the weekly one is backlog work, which
waits until the feed leaves the GPU alone. What is happening is kept in Redis for Settings → Conferences.
"""
from __future__ import annotations

import json
import time
from contextlib import contextmanager
from datetime import datetime, timezone

from loguru import logger

from athena.pipeline.celery_app import celery_app

SLICE_SECONDS = 600
STATUS_KEY = "athena:conferences:status"
VERSION_KEY = "athena:conferences:version"
LOCK_KEY = "athena:conferences:lock:{step}"


def _redis():
    from athena.core.redis_client import get_redis
    return get_redis(decode_responses=True)


def status() -> dict:
    try:
        return json.loads(_redis().get(STATUS_KEY) or "{}")
    except Exception:
        return {}


def set_status(**fields) -> None:
    try:
        now = datetime.now(timezone.utc).isoformat()
        _redis().set(STATUS_KEY, json.dumps(status() | fields | {"updated_at": now}))
    except Exception:
        pass


def version() -> int:
    """Bumped whenever what the pages show changes, so cached answers are not reused."""
    try:
        return int(_redis().get(VERSION_KEY) or 0)
    except Exception:
        return 0


def bump() -> None:
    try:
        _redis().incr(VERSION_KEY)
    except Exception:
        pass


@contextmanager
def _only_one(step: str, ttl: int = SLICE_SECONDS + 300):
    """Yields whether this run holds the step's lock (another run already doing the step: False)."""
    key = LOCK_KEY.format(step=step)
    try:
        held = bool(_redis().set(key, "1", nx=True, ex=ttl))
    except Exception:
        held = True  # no Redis: nothing to coordinate with
    try:
        yield held
    finally:
        if held:
            try:
                _redis().delete(key)
            except Exception:
                pass


def _level(asked: bool) -> int:
    """An admin's sync shares the GPU with the feed turn by turn (``ROUTINE``); the weekly one is ``BACKLOG``, which
    goes when the feed leaves the GPU alone."""
    from athena.model_server import turns
    return turns.ROUTINE if asked else turns.BACKLOG


def _held(exc_stage: str) -> None:
    """After ``lane.Paused``: paused by an admin, or only waited long for its turn on the GPU."""
    from athena.model_server import lane
    set_status(stage="paused" if lane.paused("conferences") else "waiting", note=exc_stage)


@celery_app.task(name="athena.conferences.tasks.sync")
def sync(force: bool = False, asked: bool = False) -> dict:
    """Read the Anthology (download only when it changed, unless ``force``), store it, then work out terms and queue
    the rest. ``asked``: an admin started it, so its model work goes at the feed's priority."""
    from athena.conferences import anthology, embed, terms, topics
    from athena.database.db import SessionLocal
    with _only_one("sync", ttl=3600) as held:
        if not held:
            return {"skipped": "a sync is running"}
        set_status(stage="importing", error=None, started_at=datetime.now(timezone.utc).isoformat())
        try:
            xml_dir, changed = anthology.fetch(force=force)
            with SessionLocal() as session:
                topics.ensure_seeded(session)
                stats = anthology.store(session, anthology.read_all(xml_dir)) if changed or force or \
                    not _has_papers(session) else {"unchanged": True}
                removed = stats.pop("removed", [])
                if not stats.get("unchanged"):
                    set_status(stage="terms")
                    terms.compute(session)
            embed.remove(removed)
            stats["removed"] = len(removed)
        except Exception as exc:
            logger.exception("Conference sync failed")
            set_status(stage="idle", error=str(exc)[:300])
            return {"error": str(exc)}
        bump()
        set_status(stage="embedding", last_sync=datetime.now(timezone.utc).isoformat(), last_stats=stats)
    # Side by side: counts take about two hours the first time and need no GPU. A paper that gets an abstract
    # from them is embedded again; the citations' last slice queues that.
    embed_papers.delay(asked)
    citations.delay(True, asked)
    return stats


def _has_papers(session) -> bool:
    from sqlalchemy import select
    from athena.core.models import ConfPaper
    return session.execute(select(ConfPaper.id).limit(1)).first() is not None


@celery_app.task(name="athena.conferences.tasks.citations")
def citations(then_embed: bool = False, asked: bool = False) -> dict:
    """Citation counts and missing abstracts for the papers due, one slice; then embedding."""
    from athena.conferences import citations as cites
    with _only_one("citations") as held:
        if not held:
            return {"skipped": "already running"}
        stats = cites.refresh(deadline=time.monotonic() + SLICE_SECONDS)
    bump()
    if stats.get("more"):
        citations.delay(then_embed, asked)
    elif then_embed:
        embed_papers.delay(asked)  # papers that got an abstract; a run already going takes them too
    return stats


@celery_app.task(name="athena.conferences.tasks.embed_papers")
def embed_papers(asked: bool = False) -> dict:
    """One slice of embedding and sorting, then the next slice or the summaries."""
    from athena.conferences import embed
    from athena.model_server import lane, turns
    with _only_one("embed") as held:
        if not held:
            return {"skipped": "already running"}
        set_status(stage="embedding")
        try:
            with turns.priority(_level(asked)):
                stats = embed.run(deadline=time.monotonic() + SLICE_SECONDS)
        except lane.Paused as exc:
            _held("embedding")
            embed_papers.apply_async(args=[asked], countdown=lane.REQUEUE_SECONDS)
            return {"paused": str(exc)}
        except Exception as exc:
            logger.exception("Conference embedding failed")
            set_status(stage="idle", error=f"Embedding: {str(exc)[:280]}")
            return {"error": str(exc)}
    bump()
    if stats.get("more"):
        embed_papers.delay(asked)
    else:
        write_summaries.delay(asked)
    return stats


@celery_app.task(name="athena.conferences.tasks.reassign")
def reassign() -> dict:
    """Sort every paper again after the topic list changed, then rewrite the summaries whose numbers moved."""
    from athena.conferences import topics
    from athena.database.db import SessionLocal
    with _only_one("reassign") as held:
        if not held:
            reassign.apply_async(countdown=30)  # an edit during a re-sort: sort once more after it
            return {"skipped": "already running"}
        set_status(stage="sorting")
        with SessionLocal() as session:
            done = topics.reassign_all(session)
    bump()
    write_summaries.delay(True)  # an admin edited the topics
    return {"sorted": done}


@celery_app.task(name="athena.conferences.tasks.write_summaries")
def write_summaries(asked: bool = False) -> dict:
    from athena.conferences import summaries
    from athena.model_server import lane, turns
    with _only_one("summaries") as held:
        if not held:
            return {"skipped": "already running"}
        set_status(stage="summaries")
        try:
            with turns.priority(_level(asked)):
                stats = summaries.run(deadline=time.monotonic() + SLICE_SECONDS)
        except lane.Paused as exc:
            _held("summaries")
            write_summaries.apply_async(args=[asked], countdown=lane.REQUEUE_SECONDS)
            return {"paused": str(exc)}
    bump()
    if stats.get("more"):
        write_summaries.delay(asked)
    else:
        set_status(stage="idle")
    return stats


@celery_app.task(name="athena.conferences.tasks.daily")
def daily() -> dict:
    """Counts that are due (the last two years' weekly, older monthly), and any embedding left over."""
    from athena.conferences import embed
    from athena.database.db import SessionLocal
    with SessionLocal() as session:
        if not _has_papers(session):
            return {"skipped": "no conference papers yet"}
        pending = embed.pending_count(session)
    citations.delay(bool(pending))
    return {"pending_embeddings": pending}
