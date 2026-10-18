"""
Search.

GET /api/v1/search   — keyword plus meaning search over the existing feed (athena.search.hybrid).
POST /api/v1/search  — research search: the library, Semantic Scholar and arXiv. Literature reviews are written
                       by athena.api.routers.reviews.
"""
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from athena.api import auth
from athena.api.deps import get_db
from athena.api.config import settings
from athena.api.auth import active_user
from athena.api.routers.feed import _build_feed_item, _for_user
from athena.core.models import ContentItem, User
from athena.search import hybrid
from athena.search.arxiv_live import search_arxiv
from athena.search.local import embed_query, search_local
from athena.search.merger import merge_results
from athena.search.semantic_scholar import search_semantic_scholar

router = APIRouter(prefix="/api/v1", tags=["Search"])


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

    response = client.query_points(
        collection_name=settings.QDRANT_COLLECTION,
        query=vector,
        limit=limit,
        query_filter=query_filter,
    )

    return [
        {
            "id": str(point.id),
            "similarity": round(point.score, 4),
            "payload": point.payload or {},
        }
        for point in response.points
    ]


@router.get("/search")
def search(
    q: str = Query(..., min_length=1, max_length=500),
    category: str | None = Query(None),
    limit: int = Query(20, ge=1, le=20),
    db: Session = Depends(get_db),
    user: User = Depends(active_user),
):
    """Keyword plus meaning search over the feed (athena.search.hybrid): exact names first, then the two rankings
    fused. Each item says how it matched; ``method`` says which sides answered."""
    def semantic(query: str, n: int, cat: str | None) -> list[dict]:
        hits = _qdrant_search(embed_query(query), n, cat)
        return [{"id": UUID(h["id"]), "similarity": h["similarity"]} for h in hits]

    results, method = hybrid.search(db, q, limit, category, semantic)
    found = {item.id: item for item in db.execute(
        select(ContentItem).where(ContentItem.id.in_([r["id"] for r in results]))).scalars().all()} if results else {}
    items = [_build_feed_item(found[r["id"]]) | {"similarity": r["similarity"], "match": r["match"]}
             for r in results if r["id"] in found]
    return _for_user(db, user, {"query": q, "items": items, "total": len(items), "method": method})


# ── Research search (POST /api/v1/search) ────────────────────


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=3, max_length=500)
    limit: int = Field(20, ge=1, le=50)


class PaperResult(BaseModel):
    id: str
    title: str
    abstract: str | None = None
    url: str | None = None
    year: int | None = None
    authors: list[str] = []
    citation_count: int | None = None
    score: float | None = None
    source: str


class SearchResponse(BaseModel):
    papers: list[PaperResult]
    local_count: int
    live_count: int
    query: str


@router.post("/search", response_model=SearchResponse)
def research_search(payload: SearchRequest, user: User = Depends(auth.active_user)) -> SearchResponse:
    """Research search: the library (keywords plus meaning), Semantic Scholar and arXiv, merged."""
    query = payload.query.strip()
    limit = payload.limit

    local_papers = search_local(query, limit=limit)
    # Live sources: Semantic Scholar (richer metadata, may be rate-limited) plus
    # arXiv (free, key-less) as a fallback/supplement.
    live_papers = search_semantic_scholar(query, limit=15) + search_arxiv(query, limit=15)
    merged = merge_results(local_papers, live_papers, max_total=limit)

    return SearchResponse(
        papers=[PaperResult(**p) for p in merged],
        local_count=len(local_papers),
        live_count=len(live_papers),
        query=query,
    )
