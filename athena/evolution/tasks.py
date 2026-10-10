"""Celery tasks for the research evolution feature (queue: ``evolution``)."""
from athena.pipeline.celery_app import celery_app


@celery_app.task
def build_topic(slug: str) -> dict:
    # Imported here so modules that only enqueue the task do not need igraph.
    from athena.evolution.build import build_topic as run_build
    return run_build(slug)
