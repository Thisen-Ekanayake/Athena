"""Local paper search over Qdrant + PostgreSQL.

Embeds the user query with the same model used by the embedding pipeline,
runs an ANN search against the same Qdrant collection the pipeline writes to,
and hydrates the matched IDs against PostgreSQL ContentItem rows.
"""
from __future__ import annotations

from uuid import UUID

from loguru import logger
from openai import OpenAI
from qdrant_client import QdrantClient
from sqlalchemy import select

from athena.core.config_store import get_setting
from athena.core.models import ContentItem
from athena.database.db import SessionLocal
from athena.pipeline.embedding_worker import (
    COLLECTION_NAME,
    EMBEDDING_MODEL,
    QDRANT_URL,
)


def _embed_query(query: str) -> list[float]:
    """Embed a query with the same model used by the ingest pipeline."""
    client = OpenAI(api_key=get_setting("OPENAI_API_KEY"))
    response = client.embeddings.create(input=query, model=EMBEDDING_MODEL)
    return response.data[0].embedding


def _qdrant_search(vector: list[float], limit: int) -> list[tuple[str, float]]:
    client = QdrantClient(url=QDRANT_URL)
    response = client.query_points(
        collection_name=COLLECTION_NAME,
        query=vector,
        limit=limit,
    )
    return [(str(point.id), round(float(point.score), 4)) for point in response.points]


def _item_to_dict(item: ContentItem, score: float) -> dict:
    return {
        "id": str(item.id),
        "title": item.title or "",
        "abstract": item.abstract or item.summary,
        "url": item.url,
        "year": item.published_at.year if item.published_at else None,
        "authors": list(item.authors or []),
        "citation_count": int(item.citation_count or 0),
        "score": score,
        "source": "local",
    }


def search_local(query: str, limit: int = 20) -> list[dict]:
    """Run a semantic search against ingested content.

    Returns up to ``limit`` papers ordered by cosine similarity. On any
    failure (missing API key, Qdrant down, etc.) returns an empty list
    so the caller can still serve live results.
    """
    if not query or not query.strip():
        return []

    try:
        vector = _embed_query(query)
    except Exception as exc:
        logger.warning(f"search_local: embedding failed — {exc}")
        return []

    try:
        hits = _qdrant_search(vector, limit=limit)
    except Exception as exc:
        logger.warning(f"search_local: Qdrant query failed — {exc}")
        return []

    if not hits:
        return []

    id_values: list = []
    for hit_id, _ in hits:
        try:
            id_values.append(UUID(hit_id))
        except (ValueError, TypeError):
            id_values.append(hit_id)

    with SessionLocal() as db:
        rows = db.execute(
            select(ContentItem).where(ContentItem.id.in_(id_values))
        ).scalars().all()

    by_id = {str(row.id): row for row in rows}
    results: list[dict] = []
    for hit_id, score in hits:
        row = by_id.get(hit_id)
        if row is None:
            continue
        results.append(_item_to_dict(row, score))
    return results
