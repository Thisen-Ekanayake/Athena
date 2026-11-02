"""Celery tasks for the research evolution feature (queue: ``evolution``, one at a time)."""
from loguru import logger

from athena.pipeline.celery_app import celery_app


@celery_app.task
def build_topic(slug: str) -> dict:
    # Imported here so modules that only enqueue the task do not need igraph.
    from athena.evolution.build import build_topic as run_build
    return run_build(slug)


@celery_app.task
def build_search_topic(slug: str, asked: bool = True) -> dict:
    """A topic built from a search: the map, then again with abstract embeddings. Someone asked for it, so its
    model work goes ahead of the feed's on the GPU (``turns``)."""
    from athena.evolution.build import build_search_topic as run_build
    from athena.model_server import turns
    with turns.priority(turns.ASKED if asked else turns.BACKLOG):
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
def run_gpu_lane(embed: bool = True, classify: bool = True, slug: str | None = None, asked: bool = False) -> dict:
    """Embed pending chunks, then label pending citing sentences, one model on the GPU at a time. With ``slug``, that
    map's work only, and the rest is queued as a backlog run; ``asked``: someone waits for it, so it goes ahead of
    the feed (``turns``). Queued again when background work stays paused, and a backlog run when other work waits
    for the evolution worker (what was done is kept)."""
    return _gpu_lane(embed, classify, slug, asked)


BACKLOG_QUEUED = "athena:evo:backlog_queued"  # one backlog lane run in the queue at a time


def queue_backlog() -> bool:
    """Queue a backlog lane run unless one is queued already."""
    from athena.core.redis_client import get_redis
    try:
        if not get_redis().set(BACKLOG_QUEUED, "1", nx=True, ex=24 * 3600):
            return False
    except Exception:
        pass
    run_gpu_lane.apply_async(args=[True, True, None, False])
    return True


def _gpu_lane(embed: bool, classify: bool, slug: str | None, asked: bool) -> dict:
    from athena.evolution.model_lane import StepAside, run_lane
    from athena.model_server import lane, turns
    if slug is None:
        from athena.core.redis_client import get_redis
        try:
            get_redis().delete(BACKLOG_QUEUED)  # this is the queued one: a later map may queue the next
        except Exception:
            pass
    try:
        with turns.priority(turns.ASKED if asked else turns.BACKLOG):
            summary = run_lane(embed=embed, classify=classify, slug=slug)
    except lane.Paused as exc:
        run_gpu_lane.apply_async(args=[embed, classify, slug, asked], countdown=lane.REQUEUE_SECONDS)
        return {"paused": str(exc)}
    except StepAside as exc:  # to the back of the queue, behind the work that waits
        if slug is None:
            queue_backlog()
        else:
            run_gpu_lane.apply_async(args=[embed, classify, slug, asked])
        return {"stepped_aside": str(exc)}
    if slug is not None:
        queue_backlog()  # the maps nobody is waiting for, once this one is done
    return summary


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
def refresh_build(slug: str, asked: bool = False) -> dict:
    """Rebuild with the old map readable meanwhile (status ``refining``). A failure stops the chain.

    The build saves in one transaction, so when it fails the previous map is still there: it goes back to
    ``ready`` with a note, instead of the ``failed`` a first build gets.
    """
    from athena.database import evolution as db
    from athena.database.db import SessionLocal
    from athena.evolution.build import build_search_topic, build_topic as run_build
    from athena.model_server import turns
    with SessionLocal() as session:
        topic = db.get_topic(session, slug)
        origin = topic.origin if topic else None
    try:
        if origin == "search":
            with turns.priority(turns.ASKED if asked else turns.BACKLOG):
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
def refresh_gpu_lane(slug: str | None = None, asked: bool = False) -> dict:
    """The refresh's GPU lane: the map's own work (``slug``), then a backlog run is queued. A pause or another task
    waiting queues the lane again; the snapshot goes ahead either way."""
    try:
        return _gpu_lane(True, True, slug, asked)
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


# ── literature reviews (S1); see athena.evolution.review ──────────────


@celery_app.task
def write_review(review_id: str) -> dict:
    """Write a saved literature review section by section. Model calls only: on the default queue, so a review
    does not wait behind a map build."""
    from athena.evolution.review import run
    return run(review_id)
