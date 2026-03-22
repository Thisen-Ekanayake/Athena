"""
Athena Layer 5 — Feed Router

GET /api/v1/feed — paginated, sorted, filtered content feed.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import select, func, desc, asc
import redis as redis_lib

from athena.api.deps import get_db, get_redis
from athena.api.cache import cache_get, cache_set
from athena.api.config import settings
from athena.api.schemas import (
    FeedResponse, FeedItemResponse, PaginationInfo,
    SourceInfo, ClusterInfo,
)
from athena.core.models import (
    ContentItem, Source, Cluster, ItemLink, ContentCategory,
)

router = APIRouter(prefix="/api/v1", tags=["Feed"])


def _build_feed_item(item: ContentItem, related_count: int = 0) -> dict:
    """Convert a ContentItem ORM object to a FeedItemResponse-compatible dict."""
    source = item.source
    cluster = item.cluster

    return {
        "id": item.id,
        "title": item.title,
        "url": item.url,
        "source": {
            "name": source.name if source else "Unknown",
            "type": source.type.value if source and hasattr(source.type, 'value') else str(source.type) if source else "unknown",  # noqa: E501
            "authority": source.authority_score if source else 0.5,
        },
        "category": item.category.value if hasattr(item.category, 'value') else str(item.category),  # noqa: E501
        "authors": item.authors or [],
        "published_at": item.published_at.isoformat() if item.published_at else None,  # noqa: E501
        "citation_count": item.citation_count or 0,
        "score": round(item.score, 4) if item.score else 0.0,
        "is_trending": item.is_trending or False,
        "category_rank": item.category_rank,
        "summary": item.summary,
        "summary_status": item.summary_status.value if item.summary_status and hasattr(item.summary_status, 'value') else str(item.summary_status) if item.summary_status else None,  # noqa: E501
        "takeaways": item.takeaways,
        "cluster": {
            "id": cluster.id,
            "label": cluster.label,
        } if cluster else None,
        "related_count": related_count,
    }


@router.get("/feed", response_model=FeedResponse)
def get_feed(
    sort: str = Query("score", pattern="^(score|date|trending)$"),
    category: str | None = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=50),
    cluster_id: str | None = Query(None),
    source_id: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    db: Session = Depends(get_db),
    r: redis_lib.Redis = Depends(get_redis),
):
    """
    Returns a paginated, sorted list of content cards.
    The primary endpoint for the main feed.
    """
    # ── Cache check ─────────────────────────────────────
    cache_key = f"feed:{sort}:{category}:{page}:{limit}:{cluster_id}:{source_id}:{date_from}:{date_to}"  # noqa: E501
    cached = cache_get(r, cache_key)
    if cached:
        return cached

    # ── Build query ─────────────────────────────────────
    query = select(ContentItem).join(
        Source, ContentItem.source_id == Source.id, isouter=True
    ).outerjoin(
        Cluster, ContentItem.cluster_id == Cluster.id
    )

    # Filters
    if category:
        query = query.where(ContentItem.category == category)
    if cluster_id:
        query = query.where(ContentItem.cluster_id == cluster_id)
    if source_id:
        query = query.where(ContentItem.source_id == source_id)
    if date_from:
        query = query.where(ContentItem.published_at >= date_from)
    if date_to:
        query = query.where(ContentItem.published_at <= date_to)

    # Sort
    if sort == "score":
        query = query.order_by(desc(ContentItem.score))
    elif sort == "date":
        query = query.order_by(desc(ContentItem.published_at))
    elif sort == "trending":
        query = query.where(ContentItem.is_trending.is_(True))
        query = query.order_by(desc(ContentItem.score))

    # ── Count total ─────────────────────────────────────
    count_query = select(func.count()).select_from(query.subquery())
    total = db.execute(count_query).scalar() or 0

    # ── Paginate ────────────────────────────────────────
    offset = (page - 1) * limit
    items = db.execute(
        query.offset(offset).limit(limit)
    ).scalars().all()

    # Get related counts for each item
    item_ids = [item.id for item in items]
    related_counts = {}
    if item_ids:
        related_q = (
            select(
                ItemLink.source_item_id,
                func.count(ItemLink.id).label("cnt")
            )
            .where(ItemLink.source_item_id.in_(item_ids))
            .group_by(ItemLink.source_item_id)
        )
        for row in db.execute(related_q).all():
            related_counts[row[0]] = row[1]

    # ── Build response ──────────────────────────────────
    response = {
        "items": [
            _build_feed_item(item, related_counts.get(item.id, 0))
            for item in items
        ],
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total,
            "has_next": (page * limit) < total,
        },
    }

    # ── Cache store ─────────────────────────────────────
    ttl = settings.CACHE_FEED_SCORE_TTL if sort == "score" else settings.CACHE_FEED_DATE_TTL  # noqa: E501
    cache_set(r, cache_key, response, ttl)

    return response
