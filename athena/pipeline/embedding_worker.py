import os
import json
import time
from typing import List
from uuid import UUID
from datetime import datetime
from loguru import logger
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels
from openai import OpenAI
from sqlalchemy import select, update
import redis as redis_lib

from athena.database.db import SessionLocal
from athena.core.models import ContentItem
from athena.pipeline.preprocessing import preprocess
from athena.pipeline.tasks import celery_app

# Config
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
COLLECTION_NAME = "athena_content"
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIM = 1536
BATCH_SIZE = 20

# Clients
qdrant = QdrantClient(url=QDRANT_URL)
openai = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def init_qdrant():
    """Ensure the Qdrant collection exists with correct config."""
    collections = qdrant.get_collections().collections
    exists = any(c.name == COLLECTION_NAME for c in collections)
    
    if not exists:
        logger.info(f"Creating Qdrant collection: {COLLECTION_NAME}")
        qdrant.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=qmodels.VectorParams(
                size=EMBEDDING_DIM,
                distance=qmodels.Distance.COSINE
            )
        )
    else:
        logger.info(f"Qdrant collection {COLLECTION_NAME} already exists.")

@celery_app.task
def process_embedding_queue():
    """
    Pull items from 'athena:embedding_queue' and process them in batches.
    """
    init_qdrant()
    
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    r = redis_lib.from_url(redis_url)
    
    item_ids = []
    # Pull up to BATCH_SIZE items
    for _ in range(BATCH_SIZE):
        item_id = r.lpop("athena:embedding_queue")
        if not item_id:
            break
        item_ids.append(item_id.decode('utf-8'))
        
    if not item_ids:
        return
        
    logger.info(f"Processing batch of {len(item_ids)} items for embedding.")
    
    process_batch(item_ids)

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
                    abstract=item.abstract or ""
                )
                batch_texts.append(processed_text)
                valid_items.append(item)
            except Exception as e:
                logger.error(f"Error preprocessing item {item.id}: {e}")
                
        if not batch_texts:
            return
            
        try:
            # 1. Generate Embeddings
            response = openai.embeddings.create(
                input=batch_texts,
                model=EMBEDDING_MODEL
            )
            embeddings = [data.embedding for data in response.data]
            
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
                        embedding_id=str(item.id), # Using same UUID for simplicity
                        embedded_at=datetime.utcnow()
                    )
                )
            session.commit()
            logger.info(f"Successfully embedded and updated {len(valid_items)} items.")
            
        except Exception as e:
            logger.error(f"Failed to process embedding batch: {e}")
            # Potentially re-queue items?
            for item_id in item_ids:
                r = redis_lib.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
                r.rpush("athena:embedding_queue", item_id)
            session.rollback()
