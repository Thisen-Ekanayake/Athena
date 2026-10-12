"""
Backfill embeddings for items that were never embedded.

Items get embedded only when crawled live (stage_content_item -> embedding
queue). Items ingested before the embedding pipeline was healthy — or whose
staging files were lost (e.g. /var/lib/athena/staging wiped) — are left with
embedded_at = NULL and a full_text_path pointing at a missing file, so the
embedding worker skips them forever.

This script re-stages every such item whose staging file is gone from its
title + abstract, and pushes every unembedded item onto the embedding queue.

--reset is for a switch of embedding model (EMBED_MODEL): vectors from two
models cannot be compared, so the feed collection is dropped, every item is
embedded again, and clusters and item links are rebuilt from the new vectors.
With --evolution it also forgets the research-evolution vectors; run the GPU
lane afterwards (scripts/evolution_full_text.py --gpu-only --all).

Usage:
    python -m scripts.backfill_embeddings              # re-stage + enqueue only
    python -m scripts.backfill_embeddings --drain      # also embed now (calls the embedding model)
    python -m scripts.backfill_embeddings --reset      # re-embed the whole feed, then re-cluster
    python -m scripts.backfill_embeddings --reset --evolution   # ... and forget the evolution vectors
"""
import os
import sys

from loguru import logger
from sqlalchemy import delete, select, update

from athena.database.db import SessionLocal
from athena.core.models import AppSetting, ContentItem
from athena.core.redis_client import get_redis
from athena.pipeline.tasks import STAGING_DIR, _preprocess_text

EMBEDDING_QUEUE_KEY = "athena:embedding_queue"


def _staging_dir() -> str:
    """STAGING_DIR, falling back to /tmp when it isn't writable (dev machines)."""
    try:
        os.makedirs(STAGING_DIR, exist_ok=True)
        return STAGING_DIR
    except OSError:
        fallback = "/tmp/athena/staging"
        os.makedirs(fallback, exist_ok=True)
        logger.warning(f"{STAGING_DIR!r} not writable; staging to {fallback!r}")
        return fallback


def backfill() -> int:
    """Re-stage and enqueue every item with embedded_at IS NULL. Returns count."""
    staging_dir = _staging_dir()
    r = get_redis()
    enqueued = 0

    with SessionLocal() as session:
        items = session.execute(
            select(ContentItem).where(ContentItem.embedded_at.is_(None))
        ).scalars().all()
        logger.info(f"Found {len(items)} unembedded items to backfill.")

        for item in items:
            if item.full_text_path and os.path.exists(item.full_text_path):
                r.rpush(EMBEDDING_QUEUE_KEY, str(item.id))  # its staged text is still there
                enqueued += 1
                continue
            text = _preprocess_text(f"{item.title or ''}\n\n{item.abstract or ''}")
            if not text.strip():
                logger.warning(f"Item {item.id} has no title/abstract text; skipping.")
                continue

            file_path = os.path.join(staging_dir, f"{item.id}.txt")
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(text)

            session.execute(
                update(ContentItem)
                .where(ContentItem.id == item.id)
                .values(full_text_path=file_path)
            )
            r.rpush(EMBEDDING_QUEUE_KEY, str(item.id))
            enqueued += 1

        session.commit()

    logger.success(f"Backfill staged and enqueued {enqueued} items.")
    return enqueued


def drain() -> None:
    """Process the embedding queue to completion (calls the embedding model)."""
    from athena.pipeline.embedding_worker import process_embedding_queue
    r = get_redis()
    batches = 0
    remaining = r.llen(EMBEDDING_QUEUE_KEY)
    while remaining > 0:
        process_embedding_queue()
        batches += 1
        before, remaining = remaining, r.llen(EMBEDDING_QUEUE_KEY)
        logger.info(f"Drain batch {batches} done; {remaining} left in queue.")
        if remaining >= before:  # a failed batch goes back on the queue; stop instead of looping
            raise SystemExit("The embedding queue is not shrinking; see the errors above (is the model server up?).")
    logger.success(f"Embedding queue drained in {batches} batches.")


def reset_feed() -> None:
    """Forget every feed vector so the configured embedding model can fill the collection again."""
    from athena.pipeline.embedding_worker import COLLECTION_NAME, qdrant
    if qdrant.collection_exists(COLLECTION_NAME):
        qdrant.delete_collection(COLLECTION_NAME)
        logger.info(f"Dropped the Qdrant collection {COLLECTION_NAME}.")
    get_redis().delete(EMBEDDING_QUEUE_KEY)
    with SessionLocal() as session:
        session.execute(update(ContentItem).values(embedded_at=None, embedding_id=None, embedding_model=None))
        session.execute(delete(AppSetting).where(AppSetting.key == "EMBED_SPACE_FEED"))
        session.commit()


def reset_evolution() -> None:
    """Forget the research-evolution vectors; the next GPU lane embeds them with the configured model."""
    from athena.database import evolution as evo_db
    from athena.evolution import vectors
    qdrant = vectors.client()
    for name in (vectors.COLLECTION, vectors.GAP_COLLECTION, vectors.ABSTRACT_COLLECTION):
        if qdrant.collection_exists(name):
            qdrant.delete_collection(name)
            logger.info(f"Dropped the Qdrant collection {name}.")
    with SessionLocal() as session:
        evo_db.forget_vectors(session)
        session.execute(delete(AppSetting).where(AppSetting.key == "EMBED_SPACE_EVOLUTION"))
        session.commit()
    logger.success("Evolution vectors forgotten. Run: python3 scripts/evolution_full_text.py --gpu-only --all")


def recluster() -> None:
    """Clusters and item links come from the vectors, so rebuild them after a re-embed."""
    from athena.pipeline.clustering import compute_item_links, run_clustering
    run_clustering()
    compute_item_links()
    logger.success("Clusters and item links rebuilt.")


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--reset" in args:
        reset_feed()
        if "--evolution" in args:
            reset_evolution()
    backfill()
    if "--drain" in args or "--reset" in args:
        drain()
    if "--reset" in args:
        recluster()
