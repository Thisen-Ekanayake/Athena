"""
Keeping maps up to date (ROADMAP E4).

A refresh runs, in order: the method-name fetch (Semantic Scholar, network
only, on the default queue), a rebuild that keeps the old map readable while
it runs, the full-text pass for new Tier 2 papers, the GPU lane (labels,
embeddings, gap themes, loose and cross-map links), and finally a snapshot,
which records what changed. Every step but the rebuild logs a failure and
lets the chain go on, so a GROBID or model-server outage still ends in a
rebuilt map and a changelog entry.

Each topic sets how often it is refreshed (``TopicConfig.refresh_days``);
``refresh_due_topics`` runs nightly and queues at most a couple of topics, so
the GPU lane's work stays within a night. Chains are built from task names, so
the API can queue them without importing the worker's code.
"""
from __future__ import annotations

import os

NIGHTLY_LIMIT = 2
# 21:00 UTC is 02:30 in Sri Lanka, where the GPU sits; override for other time zones.
REFRESH_HOUR_UTC = int(os.getenv("EVOLUTION_REFRESH_HOUR_UTC", "21"))
TASKS = "athena.evolution.tasks"


def _step(name: str, *args, queue: str = "evolution"):
    from athena.pipeline.celery_app import celery_app
    return celery_app.signature(f"{TASKS}.{name}", args=list(args), queue=queue, immutable=True)


def refresh_chain(slug: str, rebuild: bool = True, full_text: bool = True, reason: str = "refresh"):
    """The Celery chain for one topic: names, rebuild, full text, GPU lane, then a snapshot."""
    from celery import chain
    steps = []
    if rebuild:
        steps += [_step("fetch_method_names_step", slug, queue="celery"), _step("refresh_build", slug)]
    if full_text:
        steps += [_step("refresh_full_text", slug), _step("refresh_gpu_lane")]
    steps.append(_step("snapshot_topic", slug, reason))
    return chain(*steps)


def queue_refresh(slug: str, rebuild: bool = True, full_text: bool = True, reason: str = "refresh") -> str:
    return refresh_chain(slug, rebuild, full_text, reason).apply_async().id


def refresh_due_topics() -> list[str]:
    """Queue a refresh for the topics whose last build is older than their interval."""
    from datetime import datetime, timezone

    from athena.database import evolution as db
    from athena.database.db import SessionLocal
    with SessionLocal() as session:
        due = db.due_for_refresh(session, datetime.now(timezone.utc), NIGHTLY_LIMIT)
    for slug in due:
        db.set_topic_status(slug, "refining", "Scheduled refresh queued")
        queue_refresh(slug)
    return due
