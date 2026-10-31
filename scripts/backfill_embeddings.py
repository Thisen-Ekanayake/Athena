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
lane afterwards (scripts/evolution_full_text.py --gpu-only --all). Settings →
Models and keys → Make default on an embedding model does all of this, and
project passages too (athena.pipeline.reembed).

Usage:
    python -m scripts.backfill_embeddings              # re-stage + enqueue only
    python -m scripts.backfill_embeddings --drain      # also embed now (calls the embedding model)
    python -m scripts.backfill_embeddings --reset      # re-embed the whole feed, then re-cluster
    python -m scripts.backfill_embeddings --reset --evolution   # ... and forget the evolution vectors
"""
import sys

from loguru import logger

from athena.core.redis_client import get_redis
from athena.pipeline.reembed import EMBEDDING_QUEUE_KEY, reset_evolution, reset_feed, restage


def backfill() -> int:
    """Re-stage and enqueue every item with embedded_at IS NULL. Returns count."""
    enqueued = restage()
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
        logger.info("Feed vectors forgotten.")
        if "--evolution" in args:
            reset_evolution()
            logger.success("Evolution vectors forgotten. Run: python3 scripts/evolution_full_text.py --gpu-only --all")
    backfill()
    if "--drain" in args or "--reset" in args:
        drain()
    if "--reset" in args:
        recluster()
