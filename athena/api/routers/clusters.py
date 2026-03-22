"""
Athena Layer 5 — Clusters Router

GET /api/v1/clusters       — all active clusters with item counts
GET /api/v1/clusters/{id}  — cluster detail + paginated items
"""
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, desc
from sqlalchemy.orm import Session
import redis as redis_lib

from athena.api.deps import get_db, get_redis
from athena.api.cache import cache_get, cache_set
from athena.api.config import settings
from athena.api.routers.feed import _build_feed_item
from athena.core.models import (
    ContentItem, Cluster, Source, ItemLink,
)

router = APIRouter(prefix="/api/v1", tags=["Clusters"])


@router.get("/clusters")
def get_clusters(
    category: str | None = Query(None),
    min_items: int = Query(5, ge=0),
    db: Session = Depends(get_db),
    r: redis_lib.Redis = Depends(get_redis),
):
    """
    Returns all active clusters with item count, label, and description.
    """
    cache_key = f"clusters:{category}:{min_items}"
    cached = cache_get(r, cache_key)
    if cached:
        return cached

    # Subquery for item counts per cluster
    count_sub = (
        select(
            ContentItem.cluster_id,
            func.count(ContentItem.id).label("item_count")
        )
        .group_by(ContentItem.cluster_id)
        .subquery()
    )

    query = (
        select(Cluster, count_sub.c.item_count)
        .outerjoin(count_sub, Cluster.id == count_sub.c.cluster_id)
        .where(Cluster.is_active.is_(True))
    )

    if min_items > 0:
        query = query.where(
            func.coalesce(count_sub.c.item_count, 0) >= min_items
        )

    query = query.order_by(desc(count_sub.c.item_count))
    results = db.execute(query).all()

    response = [
        {
            "id": cluster.id,
            "label": cluster.label,
            "summary": cluster.summary,
            "item_count": item_count or 0,
            "is_active": cluster.is_active,
        }
        for cluster, item_count in results
    ]

    cache_set(r, cache_key, response, settings.CACHE_CLUSTERS_TTL)
    return response


@router.get("/clusters/{cluster_id}")
def get_cluster_detail(
    cluster_id: str,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=50),
    sort: str = Query("score", pattern="^(score|date)$"),
    db: Session = Depends(get_db),
    r: redis_lib.Redis = Depends(get_redis),
):
    """
    Returns cluster metadata and top items sorted by score.
    """
    try:
        cluster_uuid = UUID(cluster_id)
    except ValueError:
        raise HTTPException(
            status_code=400, detail="Invalid cluster ID format"
        )

    cache_key = f"cluster:{cluster_id}:{page}:{sort}"
    cached = cache_get(r, cache_key)
    if cached:
        return cached

    cluster = db.execute(
        select(Cluster).where(Cluster.id == cluster_uuid)
    ).scalar_one_or_none()

    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster not found")

    # Item count
    total = db.execute(
        select(func.count(ContentItem.id))
        .where(ContentItem.cluster_id == cluster_uuid)
    ).scalar() or 0

    # Items query
    items_query = (
        select(ContentItem)
        .join(Source, ContentItem.source_id == Source.id, isouter=True)
        .where(ContentItem.cluster_id == cluster_uuid)
    )
    if sort == "score":
        items_query = items_query.order_by(desc(ContentItem.score))
    else:
        items_query = items_query.order_by(desc(ContentItem.published_at))

    offset = (page - 1) * limit
    items = db.execute(
        items_query.offset(offset).limit(limit)
    ).scalars().all()

    response = {
        "cluster": {
            "id": cluster.id,
            "label": cluster.label,
            "summary": cluster.summary,
            "item_count": total,
            "is_active": cluster.is_active,
        },
        "items": [_build_feed_item(item) for item in items],
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total,
            "has_next": (page * limit) < total,
        },
    }

    cache_set(r, cache_key, response, settings.CACHE_CLUSTER_DETAIL_TTL)
    return response
