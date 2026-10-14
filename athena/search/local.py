"""Local paper search over Qdrant + PostgreSQL.

Embeds the user query with the same model used by the embedding pipeline,
runs an ANN search against the same Qdrant collection the pipeline writes to,
and hydrates the matched IDs against PostgreSQL ContentItem rows.
"""
from __future__ import annotations

from uuid import UUID

from loguru import logger
from qdrant_client import QdrantClient
from sqlalchemy import select

from athena.core import llm
from athena.core.models import ContentItem
from athena.database.db import SessionLocal
from athena.search import hybrid
from athena.pipeline.embedding_worker import (
    COLLECTION_NAME,
    QDRANT_URL,
)

# Qwen3-Embedding embeds queries with an instruction and documents without one.
SEARCH_INSTRUCT = "Given a search query, retrieve AI research papers and articles relevant to it"


def embed_query(query: str) -> list[float]:
    """Embed a query with the same model used by the ingest pipeline."""
    return llm.embed([query], instruct=SEARCH_INSTRUCT, feature="search")[0].tolist()


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
    """Keyword plus meaning search against ingested content (athena.search.hybrid).

    Returns up to ``limit`` items, exact title matches first. With the model server or Qdrant down it answers
    from keywords alone, and on any other failure it returns an empty list so the caller can still serve live
    results.
    """
    if not query or not query.strip():
        return []

    def semantic(q: str, n: int, category: str | None) -> list[dict]:
        hits = _qdrant_search(embed_query(q), limit=n)
        return [{"id": UUID(hit_id), "similarity": score} for hit_id, score in hits]

    try:
        with SessionLocal() as db:
            results, _ = hybrid.search(db, query, limit, None, semantic)
            rows = {row.id: row for row in db.execute(
                select(ContentItem).where(ContentItem.id.in_([r["id"] for r in results]))).scalars()} \
                if results else {}
            return [_item_to_dict(rows[r["id"]], r["similarity"] if r["similarity"] is not None else 0.0)
                    for r in results if r["id"] in rows]
    except Exception as exc:
        logger.warning(f"search_local: search failed — {exc}")
        return []
