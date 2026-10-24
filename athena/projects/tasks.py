"""
Indexing a project in the background: one ``index_project`` run per project at a time, which keeps going while
new things arrive. Queued on Celery's shared queue (one run per change a user makes, never one per item); with no
broker the API indexes in a thread instead, so a single-machine setup without a worker still works.
"""
from __future__ import annotations

import threading
from uuid import UUID

from loguru import logger

from athena.pipeline.celery_app import celery_app

LOCK = "athena:project_index:{id}"
QUEUED = "athena:project_index_queued:{id}"
LOCK_SECONDS = 3600


def _redis():
    from athena.core.redis_client import get_redis
    return get_redis(decode_responses=True)


def run(project_id: str) -> dict:
    """Index what is pending until nothing is; returns the counts. Skips when another run holds the project."""
    from athena.database import projects as db
    from athena.database.db import SessionLocal
    from athena.projects import index

    r = _redis()
    r.delete(QUEUED.format(id=project_id))
    lock = LOCK.format(id=project_id)
    if not r.set(lock, "1", nx=True, ex=LOCK_SECONDS):
        return {"skipped": True}
    totals = {"indexed": 0, "failed": 0}
    try:
        with SessionLocal() as session:
            for _ in range(20):  # rows added while a pass runs are taken by the next one
                counts = index.index_pending(session, UUID(project_id))
                totals = {k: totals[k] + counts[k] for k in totals}
                if not any(db.pending_index(session, UUID(project_id))) or counts == {"indexed": 0, "failed": 0}:
                    break
    finally:
        r.delete(lock)
    return totals


@celery_app.task(name="athena.projects.tasks.index_project")
def index_project(project_id: str) -> dict:
    return run(project_id)


def queue(project_id: UUID | str) -> None:
    """Ask for the project to be indexed; a run already queued covers it."""
    project_id = str(project_id)
    try:
        r = _redis()
        if not r.set(QUEUED.format(id=project_id), "1", nx=True, ex=600):
            return
    except Exception as exc:
        logger.warning(f"Project {project_id}: Redis unavailable, indexing in a thread: {exc}")
        threading.Thread(target=_safe_run, args=(project_id,), daemon=True).start()
        return
    try:
        index_project.delay(project_id)
    except Exception as exc:  # no broker: index here, off the request
        logger.warning(f"Project {project_id}: worker unreachable, indexing in a thread: {exc}")
        threading.Thread(target=_safe_run, args=(project_id,), daemon=True).start()


def _safe_run(project_id: str) -> None:
    try:
        run(project_id)
    except Exception as exc:
        logger.warning(f"Project {project_id}: indexing failed: {exc}")
