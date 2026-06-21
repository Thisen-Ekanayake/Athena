"""
Backfill embeddings for items that were never embedded.

Items get embedded only when crawled live (stage_content_item -> embedding
queue). Items ingested before the embedding pipeline was healthy — or whose
staging files were lost (e.g. /var/lib/athena/staging wiped) — are left with
embedded_at = NULL and a full_text_path pointing at a missing file, so the
embedding worker skips them forever.

This script re-stages every such item from its title + abstract and pushes it
onto the embedding queue.

Usage:
    python -m scripts.backfill_embeddings              # re-stage + enqueue only
    python -m scripts.backfill_embeddings --drain      # also embed now (uses OpenAI)
"""
import os
import sys

from loguru import logger
from sqlalchemy import select, update

from athena.database.db import SessionLocal
from athena.core.models import ContentItem
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
    """Process the embedding queue to completion (calls OpenAI; costs credits)."""
    from athena.pipeline.embedding_worker import process_embedding_queue
    r = get_redis()
    batches = 0
    while r.llen(EMBEDDING_QUEUE_KEY) > 0:
        process_embedding_queue()
        batches += 1
        remaining = r.llen(EMBEDDING_QUEUE_KEY)
        logger.info(f"Drain batch {batches} done; {remaining} left in queue.")
    logger.success(f"Embedding queue drained in {batches} batches.")


if __name__ == "__main__":
    backfill()
    if "--drain" in sys.argv[1:]:
        drain()
