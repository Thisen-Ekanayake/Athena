import os
import time
from typing import List
from datetime import datetime
from loguru import logger
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels
from sqlalchemy import select, update

from athena.core import llm
from athena.database.db import SessionLocal
from athena.core.models import ContentItem
from athena.core.redis_client import get_redis
from athena.pipeline.preprocessing import preprocess
from athena.pipeline.celery_app import celery_app

# Config
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
COLLECTION_NAME = "athena_content"
EMBEDDING_DIM = llm.EMBED_DIM
BATCH_SIZE = 20
DRAIN_SECONDS = 45  # a run keeps taking batches this long; beat starts one a minute

# Clients
qdrant = QdrantClient(url=QDRANT_URL)


def init_qdrant():
    """Ensure the Qdrant collection exists with the right size, and holds vectors from the configured model.

    Raises llm.EmbedSpaceMismatch for a collection built by another model (e.g. the old 1536-dimension
    OpenAI one): re-embed with scripts/backfill_embeddings.py --reset.
    """
    if not qdrant.collection_exists(COLLECTION_NAME):
        logger.info(f"Creating Qdrant collection: {COLLECTION_NAME}")
        qdrant.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=qmodels.VectorParams(
                size=EMBEDDING_DIM,
                distance=qmodels.Distance.COSINE
            )
        )
    size = qdrant.get_collection(COLLECTION_NAME).config.params.vectors.size
    llm.check_embed_space("feed", collection_dim=size)


@celery_app.task
def process_embedding_queue():
    """
    Pull items from 'athena:embedding_queue' and process them in batches.
    """
    try:
        init_qdrant()
    except llm.EmbedSpaceMismatch as e:
        logger.error(f"Feed embedding paused: {e}")
        return

    r = get_redis()

    # Keep taking batches for most of the minute: one batch of 20 a minute took most of an hour to embed a
    # sync's worth of arXiv papers. The deadline keeps one run from overlapping the next for long.
    deadline = time.monotonic() + DRAIN_SECONDS
    while time.monotonic() < deadline:
        item_ids = []
        for _ in range(BATCH_SIZE):
            item_id = r.lpop("athena:embedding_queue")
            if not item_id:
                break
            item_ids.append(item_id.decode('utf-8'))

        if not item_ids:
            return

        logger.info(f"Processing batch of {len(item_ids)} items for embedding.")
        try:
            process_batch(item_ids)
        except Exception as e:  # before the batch could start (no free database connection): keep its items
            logger.error(f"Embedding batch not started; its items go back on the queue: {e}")
            r.rpush("athena:embedding_queue", *item_ids)
            return


def process_batch(item_ids: List[str]):
    with SessionLocal() as session:
        # Fetch items from DB
        items = session.execute(
            select(ContentItem).where(ContentItem.id.in_(item_ids))
        ).scalars().all()

        batch_texts = []
        valid_items = []

        for item in items:
            if not item.full_text_path or not os.path.exists(item.full_text_path):
                logger.warning(f"Full text path missing or invalid for item {item.id}")
                continue

            try:
                with open(item.full_text_path, 'r', encoding='utf-8') as f:
                    content = f.read()

                processed_text = preprocess(
                    text=content,
                    title=item.title or "",
                    authors=item.authors or [],
                    abstract=item.abstract or "",
                    max_tokens=llm.embed_input_tokens()
                )
                batch_texts.append(processed_text)
                valid_items.append(item)
            except Exception as e:
                logger.error(f"Error preprocessing item {item.id}: {e}")

        if not batch_texts:
            return

        try:
            # 1. Generate Embeddings (the client retries rate limits itself)
            model = llm.embed_model()
            embeddings = [vec.tolist() for vec in llm.embed(batch_texts, feature="feed_embed")]

            # 2. Upsert to Qdrant
            points = []
            for item, vector in zip(valid_items, embeddings):
                points.append(qmodels.PointStruct(
                    id=str(item.id),
                    vector=vector,
                    payload={
                        "title": item.title,
                        "url": item.url,
                        "published_at": item.published_at.isoformat() if item.published_at else None,
                        "source_id": str(item.source_id) if item.source_id else None,
                        "category": item.category.value if hasattr(item.category, 'value') else str(item.category)
                    }
                ))

            qdrant.upsert(
                collection_name=COLLECTION_NAME,
                points=points
            )

            # 3. Update PostgreSQL
            for item in valid_items:
                session.execute(
                    update(ContentItem).where(ContentItem.id == item.id).values(
                        embedding_id=str(item.id),
                        embedding_model=model,
                        embedded_at=datetime.utcnow()
                    )
                )
            session.commit()
            logger.info(f"Successfully embedded and updated {len(valid_items)} items.")

            # Push embedded items to the scoring queue
            r = get_redis()
            for item in valid_items:
                r.rpush("athena:scoring_queue", str(item.id))
            logger.info(f"Queued {len(valid_items)} items for scoring.")

        except Exception as e:
            logger.error(f"Failed to process embedding batch: {e}")
            r = get_redis()
            for item_id in item_ids:
                r.rpush("athena:embedding_queue", item_id)
            session.rollback()
