"""Celery tasks for the research evolution feature (queue: ``evolution``, one at a time)."""
from athena.pipeline.celery_app import celery_app


@celery_app.task
def build_topic(slug: str) -> dict:
    # Imported here so modules that only enqueue the task do not need igraph.
    from athena.evolution.build import build_topic as run_build
    return run_build(slug)


@celery_app.task
def process_full_text(slug: str, reparse: bool = False) -> dict:
    """Tier 2 PDFs -> GROBID -> sections, chunks, citing sentences. CPU only."""
    from athena.evolution.fulltext import run_full_text
    return run_full_text(slug, reparse=reparse)
