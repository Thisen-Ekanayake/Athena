"""
Embedding everything again after a switch of embedding model (Settings → Models and keys → Make default).

Vectors from two models cannot be compared, so every store starts again with the new one: the feed collection is
dropped and every item queued for the minute embedding run; the maps' vectors (passages, gap statements, abstracts)
are forgotten and the maps' GPU lane embeds them again; each project's passages are dropped and indexed again.
Clusters and item links follow on their own six-hourly run. ``scripts/backfill_embeddings.py --reset`` runs the
same steps by hand.

The switch is recorded in Redis (``STATUS_KEY``) with who made it and when, and ``status()`` counts what is left,
so Settings can say how far it has got.
"""
from __future__ import annotations

import json
import os
import time

from loguru import logger
from sqlalchemy import delete, func, select, update

from athena.pipeline.celery_app import celery_app

EMBEDDING_QUEUE_KEY = "athena:embedding_queue"
STATUS_KEY = "athena:reembed"
STATUS_TTL = 14 * 86400


def _redis():
    from athena.core.redis_client import get_redis
    return get_redis(decode_responses=True)


def _staging_dir() -> str:
    """STAGING_DIR, falling back to /tmp when it isn't writable (dev machines)."""
    from athena.pipeline.crawl import STAGING_DIR
    try:
        os.makedirs(STAGING_DIR, exist_ok=True)
        return STAGING_DIR
    except OSError:
        fallback = "/tmp/athena/staging"
        os.makedirs(fallback, exist_ok=True)
        logger.warning(f"{STAGING_DIR!r} not writable; staging to {fallback!r}")
        return fallback


def restage() -> int:
    """Queue every feed item not embedded yet, writing its title and abstract out again when its staged text is gone.
    Returns how many were queued."""
    from athena.core.models import ContentItem
    from athena.database.db import SessionLocal
    from athena.pipeline.crawl import _preprocess_text
    staging_dir = _staging_dir()
    r = _redis()
    queued = 0
    with SessionLocal() as session:
        items = session.execute(select(ContentItem).where(ContentItem.embedded_at.is_(None))).scalars().all()
        for item in items:
            if not (item.full_text_path and os.path.exists(item.full_text_path)):
                text = _preprocess_text(f"{item.title or ''}\n\n{item.abstract or ''}")
                if not text.strip():
                    continue
                path = os.path.join(staging_dir, f"{item.id}.txt")
                with open(path, "w", encoding="utf-8") as f:
                    f.write(text)
                item.full_text_path = path
            r.rpush(EMBEDDING_QUEUE_KEY, str(item.id))
            queued += 1
        session.commit()
    logger.info(f"Re-embed: {queued} feed items queued")
    return queued


def reset_feed() -> None:
    """Forget every feed vector so the configured embedding model can fill the collection again."""
    from athena.core.models import AppSetting, ContentItem
    from athena.database.db import SessionLocal
    from athena.pipeline.embedding_worker import COLLECTION_NAME, qdrant
    if qdrant.collection_exists(COLLECTION_NAME):
        qdrant.delete_collection(COLLECTION_NAME)
    _redis().delete(EMBEDDING_QUEUE_KEY)
    with SessionLocal() as session:
        session.execute(update(ContentItem).values(embedded_at=None, embedding_id=None, embedding_model=None))
        session.execute(delete(AppSetting).where(AppSetting.key == "EMBED_SPACE_FEED"))
        session.commit()


def reset_evolution() -> None:
    """Forget the maps' vectors; the next GPU lane embeds them with the configured model."""
    from athena.core.models import AppSetting
    from athena.database import evolution as evo_db
    from athena.database.db import SessionLocal
    from athena.evolution import vectors
    qdrant = vectors.client()
    for name in (vectors.COLLECTION, vectors.GAP_COLLECTION, vectors.ABSTRACT_COLLECTION):
        if qdrant.collection_exists(name):
            qdrant.delete_collection(name)
    with SessionLocal() as session:
        evo_db.forget_vectors(session)
        session.execute(delete(AppSetting).where(AppSetting.key == "EMBED_SPACE_EVOLUTION"))
        session.commit()


def reset_projects() -> list[str]:
    """Drop every project passage and mark what each project holds as pending again; returns the project ids."""
    from athena.core.models import Artifact, Project, ProjectItem, UserFile
    from athena.database.db import SessionLocal
    from athena.projects import index
    qdrant = index.client()
    if qdrant.collection_exists(index.COLLECTION):
        qdrant.delete_collection(index.COLLECTION)
    with SessionLocal() as session:
        for model in (ProjectItem, Artifact):
            session.execute(update(model).values(index_status="pending"))
        session.execute(update(UserFile).where(UserFile.status == "ready").values(index_status="pending"))
        session.commit()
        return [str(pid) for pid in session.execute(select(Project.id)).scalars()]


@celery_app.task(name="athena.pipeline.reembed.reembed_all")
def reembed_all() -> dict:
    """Every store again with the configured embedding model (see the module docstring)."""
    from athena.evolution.tasks import run_gpu_lane
    from athena.projects import tasks as project_tasks
    reset_feed()
    queued = restage()
    reset_evolution()
    projects = reset_projects()
    for pid in projects:
        project_tasks.queue(pid)
    run_gpu_lane.apply_async(queue="evolution")
    logger.info(f"Re-embed started: {queued} feed items, {len(projects)} projects, the maps' lane queued")
    return {"feed": queued, "projects": len(projects)}


def start(model: str, previous: str | None, by: str | None) -> None:
    """Record the switch and queue ``reembed_all`` on the default worker."""
    _redis().set(STATUS_KEY, json.dumps({"model": model, "previous": previous, "by": by, "since": time.time()}),
                 ex=STATUS_TTL)
    reembed_all.delay()


def status() -> dict | None:
    """The last switch and what is left of it: {model, previous, by, since, feed_left, maps_left, projects_left,
    done}; None when there was none in the last two weeks."""
    from athena.core.models import Artifact, ContentItem, EvoChunk, EvoPaper, ProjectItem, UserFile
    from athena.database.db import SessionLocal
    try:
        raw = _redis().get(STATUS_KEY)
    except Exception:
        return None
    if not raw:
        return None
    state = json.loads(raw)
    with SessionLocal() as session:
        def count(query) -> int:
            return session.execute(query).scalar() or 0
        feed = count(select(func.count()).select_from(ContentItem).where(ContentItem.embedded_at.is_(None)))
        abstracts = select(func.count()).select_from(EvoPaper).where(
            EvoPaper.abstract_embedded_at.is_(None), EvoPaper.abstract.isnot(None))
        chunks = select(func.count()).select_from(EvoChunk).where(EvoChunk.embedded_at.is_(None))
        maps = count(chunks) + count(abstracts)
        projects = sum(count(select(func.count()).select_from(m).where(m.index_status == "pending"))
                       for m in (ProjectItem, UserFile, Artifact))
    return state | {"feed_left": feed, "maps_left": maps, "projects_left": projects,
                    "done": not (feed or maps or projects)}


def clear() -> None:
    _redis().delete(STATUS_KEY)
