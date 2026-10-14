"""Celery tasks for the research evolution feature (queue: ``evolution``, one at a time)."""
from loguru import logger

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


@celery_app.task
def link_feed() -> dict:
    """Feed papers that are map papers, and new ones citing milestones. Network only: on the default queue."""
    from athena.evolution.feedlink import check_feed_citations, link_feed_items
    return {"linked": link_feed_items()} | check_feed_citations()


# ── refresh steps (E4); see athena.evolution.refresh ──────────────────


@celery_app.task
def refresh_due_topics() -> list[str]:
    from athena.evolution.refresh import refresh_due_topics as queue_due
    return queue_due()


@celery_app.task
def fetch_method_names_step(slug: str) -> dict:
    """Names citing papers use, for the rebuild's score. Network only, so it runs on the default queue."""
    from athena.evolution.method_names import fetch_method_names
    try:
        return fetch_method_names(slug)
    except Exception as exc:  # Semantic Scholar down: the rebuild uses the names already stored
        logger.warning(f"Refresh {slug}: method names not fetched: {exc}")
        return {"error": str(exc)[:300]}


@celery_app.task
def refresh_build(slug: str) -> dict:
    """Rebuild with the old map readable meanwhile (status ``refining``). A failure stops the chain.

    The build saves in one transaction, so when it fails the previous map is still there: it goes back to
    ``ready`` with a note, instead of the ``failed`` a first build gets.
    """
    from athena.database import evolution as db
    from athena.database.db import SessionLocal
    from athena.evolution.build import build_search_topic, build_topic as run_build
    with SessionLocal() as session:
        topic = db.get_topic(session, slug)
        origin = topic.origin if topic else None
    try:
        if origin == "search":
            return build_search_topic(slug, stage_status="refining", snapshot=False)
        return run_build(slug, stage_status="refining", snapshot=False)
    except Exception as exc:
        db.set_topic_status(slug, "ready", f"The refresh failed, so this is the previous build: {exc}"[:500])
        raise


@celery_app.task
def refresh_full_text(slug: str) -> dict:
    from athena.evolution.fulltext import run_full_text
    try:
        return run_full_text(slug)
    except Exception as exc:  # GROBID down: the lane still labels and embeds what is there
        logger.warning(f"Refresh {slug}: full text not processed: {exc}")
        return {"error": str(exc)[:300]}


@celery_app.task
def refresh_gpu_lane() -> dict:
    from athena.evolution.gpu import run_gpu_lane as run_lane
    try:
        return run_lane()
    except Exception as exc:  # no model server: the snapshot still records the rebuild
        logger.warning(f"Refresh: GPU lane did not run: {exc}")
        return {"error": str(exc)[:300]}


@celery_app.task
def snapshot_topic(slug: str, reason: str = "refresh") -> dict:
    from athena.database import evolution as db
    from athena.database.db import SessionLocal
    from athena.evolution.build import fetch_citation_years
    with SessionLocal() as session:
        topic = db.get_topic(session, slug)
        result = db.take_snapshot(session, topic, reason) if topic is not None else {}
    if topic is not None:
        fetch_citation_years(slug)
    return result
