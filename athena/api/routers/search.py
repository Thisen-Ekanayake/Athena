"""
Athena Layer 5 — Search Router

GET /api/v1/search — semantic search via OpenAI embed + Qdrant ANN.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session
from loguru import logger

from athena.api.deps import get_db
from athena.api.config import settings
from athena.api.routers.feed import _build_feed_item
from athena.core.models import ContentItem, Source

router = APIRouter(prefix="/api/v1", tags=["Search"])


def _embed_query(query_text: str) -> list[float]:
    """Embed a search query using OpenAI text-embedding-3-small."""
    import openai

    client = openai.OpenAI(api_key=settings.OPENAI_API_KEY)
    response = client.embeddings.create(
        input=query_text,
        model="text-embedding-3-small",
    )
    return response.data[0].embedding


def _qdrant_search(
    vector: list[float],
    limit: int = 20,
    category: str | None = None,
) -> list[dict]:
    """Run ANN search on Qdrant and return point IDs with scores."""
    from qdrant_client import QdrantClient
    from qdrant_client.models import Filter, FieldCondition, MatchValue

    client = QdrantClient(url=settings.QDRANT_URL)

    query_filter = None
    if category:
        query_filter = Filter(
            must=[
                FieldCondition(
                    key="category",
                    match=MatchValue(value=category),
                )
            ]
        )

    results = client.search(
        collection_name=settings.QDRANT_COLLECTION,
        query_vector=vector,
        limit=limit,
        query_filter=query_filter,
    )

    return [
        {
            "id": str(point.id),
            "similarity": round(point.score, 4),
            "payload": point.payload or {},
        }
        for point in results
    ]


@router.get("/search")
def search(
    q: str = Query(..., min_length=1, max_length=500),
    category: str | None = Query(None),
    limit: int = Query(20, ge=1, le=20),
    db: Session = Depends(get_db),
):
    """
    Semantic search: embeds the query string server-side and
    runs Qdrant ANN search. Returns ranked results.
    """
    if not settings.OPENAI_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="Search is temporarily unavailable",
        )

    try:
        # 1. Embed query server-side
        vector = _embed_query(q)
    except Exception as e:
        logger.error(f"OpenAI embed failed: {e}")
        raise HTTPException(
            status_code=503,
            detail="Search is temporarily unavailable",
        )

    try:
        # 2. Qdrant ANN search
        qdrant_results = _qdrant_search(vector, limit, category)
    except Exception as e:
        logger.error(f"Qdrant search failed: {e}")
        raise HTTPException(
            status_code=503,
            detail="Search temporarily unavailable — try again shortly",
        )

    if not qdrant_results:
        return {"query": q, "items": [], "total": 0}

    # 3. Map Qdrant point IDs to content_item IDs
    # Qdrant stores embedding_id on the content_item
    point_ids = [r["id"] for r in qdrant_results]
    similarity_map = {r["id"]: r["similarity"] for r in qdrant_results}

    # Fetch items by embedding_id
    items = db.execute(
        select(ContentItem)
        .join(Source, ContentItem.source_id == Source.id, isouter=True)
        .where(ContentItem.embedding_id.in_(point_ids))
    ).scalars().all()

    # Build response sorted by similarity
    item_map = {item.embedding_id: item for item in items}
    sorted_items = []
    for pid in point_ids:
        item = item_map.get(pid)
        if item:
            item_dict = _build_feed_item(item)
            item_dict["similarity"] = similarity_map.get(pid, 0.0)
            sorted_items.append(item_dict)

    return {
        "query": q,
        "items": sorted_items,
        "total": len(sorted_items),
    }
