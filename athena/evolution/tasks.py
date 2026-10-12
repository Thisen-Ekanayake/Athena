"""Celery tasks for the research evolution feature (queue: ``evolution``, one at a time)."""
from athena.pipeline.celery_app import celery_app


@celery_app.task
def build_topic(slug: str) -> dict:
    # Imported here so modules that only enqueue the task do not need igraph.
    from athena.evolution.build import build_topic as run_build
    return run_build(slug)


@celery_app.task
def build_search_topic(slug: str) -> dict:
    """A topic built from a search: the map, then again with abstract embeddings."""
    from athena.evolution.build import build_search_topic as run_build
    return run_build(slug)


@celery_app.task
def refine_proposal(proposal_id: str) -> str:
    """Ask the 9B to improve a search's topic proposal. Enqueued with an expiry: a busy GPU skips it."""
    from athena.evolution.propose import run_refinement
    return run_refinement(proposal_id)


@celery_app.task
def process_full_text(slug: str, reparse: bool = False) -> dict:
    """Tier 2 PDFs -> GROBID -> sections, chunks, citing sentences. CPU only."""
    from athena.evolution.fulltext import run_full_text
    return run_full_text(slug, reparse=reparse)


@celery_app.task
def run_gpu_lane(embed: bool = True, classify: bool = True) -> dict:
    """Embed pending chunks, then label pending citing sentences, one model on the GPU at a time."""
    from athena.evolution.gpu import run_gpu_lane as run_lane
    return run_lane(embed=embed, classify=classify)
