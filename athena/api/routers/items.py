"""
Athena Layer 5 — Items Router

GET /api/v1/items/{id}                — single item with full detail
GET /api/v1/items/{id}/score-breakdown — score explainability
GET /api/v1/items/{id}/related        — nearest-neighbour items
"""
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, desc
from sqlalchemy.orm import Session
import redis as redis_lib

from athena.api.deps import get_db, get_redis
from athena.api.cache import cache_get, cache_set
from athena.api.config import settings
from athena.api.routers.feed import _build_feed_item
from athena.core.models import (
    ContentItem, ContentScore, ItemLink, Source, Cluster,
    SummaryStatus,
)

router = APIRouter(prefix="/api/v1", tags=["Items"])


@router.get("/items/{item_id}")
def get_item(
    item_id: str,
    db: Session = Depends(get_db),
    r: redis_lib.Redis = Depends(get_redis),
):
    """
    Returns a single content item with full detail.
    Triggers on-demand summarisation if summary_status = lazy.
    """
    # Cache check
    cache_key = f"item:{item_id}"
    cached = cache_get(r, cache_key)
    if cached:
        return cached

    try:
        item_uuid = UUID(item_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid item ID format")

    item = db.execute(
        select(ContentItem)
        .join(Source, ContentItem.source_id == Source.id, isouter=True)
        .outerjoin(Cluster, ContentItem.cluster_id == Cluster.id)
        .where(ContentItem.id == item_uuid)
    ).scalar_one_or_none()

    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    # Trigger on-demand summarisation for lazy items
    if item.summary_status == SummaryStatus.LAZY:
        try:
            from athena.pipeline.summarisation_tasks import (
                summarise_on_demand_sync,
            )
            updated = summarise_on_demand_sync(item_id)
            if updated and updated.summary_status == SummaryStatus.COMPLETE:
                db.refresh(item)
        except Exception:
            pass  # Item returned without summary — UI shows retry link

    # Count related
    related_count = db.execute(
        select(ItemLink)
        .where(ItemLink.source_item_id == item_uuid)
    ).scalars().all()

    response = _build_feed_item(item, len(related_count))
    response["abstract"] = item.abstract
    response["fetched_at"] = (
        item.fetched_at.isoformat() if item.fetched_at else None
    )
    response["summarised_at"] = (
        item.summarised_at.isoformat() if item.summarised_at else None
    )

    cache_set(r, cache_key, response, settings.CACHE_ITEM_TTL)
    return response


@router.get("/items/{item_id}/score-breakdown")
def get_score_breakdown(
    item_id: str,
    db: Session = Depends(get_db),
):
    """
    Returns the full per-signal score breakdown for the
    score tooltip on hover.
    """
    try:
        item_uuid = UUID(item_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid item ID format")

    item = db.execute(
        select(ContentItem).where(ContentItem.id == item_uuid)
    ).scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    score_record = db.execute(
        select(ContentScore)
        .where(ContentScore.item_id == item_uuid)
        .order_by(desc(ContentScore.computed_at))
        .limit(1)
    ).scalars().first()
    if not score_record:
        raise HTTPException(
            status_code=404,
            detail="No score computed for this item yet",
        )

    # Fetch scoring config weights
    from athena.pipeline.scoring import _get_weights
    category = (
        item.category.value
        if hasattr(item.category, 'value')
        else str(item.category)
    )
    weights = _get_weights(category, db)

    def _label(score: float) -> str:
        if score >= 0.85:
            return "Top-tier"
        elif score >= 0.70:
            return "Strong"
        elif score >= 0.55:
            return "Good"
        elif score >= 0.40:
            return "Moderate"
        elif score >= 0.25:
            return "Low"
        return "Minimal"

    return {
        "item_id": str(item.id),
        "title": item.title,
        "composite_score": round(score_record.composite_score, 4),
        "is_trending": item.is_trending or False,
        "category_rank": item.category_rank,
        "signals": {
            "citation_impact": {
                "score": round(score_record.citation_score, 4),
                "label": _label(score_record.citation_score),
                "weight": weights.get("citation", 0.30),
            },
            "engagement": {
                "score": round(score_record.engagement_score, 4),
                "label": _label(score_record.engagement_score),
                "weight": weights.get("engagement", 0.15),
            },
            "community_sentiment": {
                "score": round(score_record.sentiment_score, 4),
                "label": _label(score_record.sentiment_score),
                "weight": weights.get("sentiment", 0.15),
            },
            "recency_velocity": {
                "score": round(score_record.recency_score, 4),
                "label": _label(score_record.recency_score),
                "weight": weights.get("recency", 0.20),
            },
            "source_authority": {
                "score": round(score_record.authority_score, 4),
                "label": _label(score_record.authority_score),
                "weight": weights.get("authority", 0.20),
            },
        },
        "computed_at": (
            score_record.computed_at.isoformat()
            if score_record.computed_at else None
        ),
        "score_version": score_record.score_version,
    }


@router.get("/items/{item_id}/related")
def get_related_items(
    item_id: str,
    limit: int = Query(5, ge=1, le=10),
    db: Session = Depends(get_db),
):
    """
    Returns the nearest-neighbour items from item_links.
    Used for the related articles sidebar.
    """
    try:
        item_uuid = UUID(item_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid item ID format")

    # Fetch linked items sorted by similarity
    links = db.execute(
        select(ItemLink)
        .where(ItemLink.source_item_id == item_uuid)
        .order_by(desc(ItemLink.similarity_score))
        .limit(limit)
    ).scalars().all()

    if not links:
        return []

    target_ids = [link.target_item_id for link in links]
    similarity_map = {
        link.target_item_id: link.similarity_score for link in links
    }

    items = db.execute(
        select(ContentItem).where(ContentItem.id.in_(target_ids))
    ).scalars().all()

    return [
        {
            "id": item.id,
            "title": item.title,
            "url": item.url,
            "score": round(item.score, 4) if item.score else 0.0,
            "similarity": round(
                similarity_map.get(item.id, 0.0), 4
            ),
            "category": (
                item.category.value
                if hasattr(item.category, 'value')
                else str(item.category)
            ),
            "published_at": (
                item.published_at.isoformat()
                if item.published_at else None
            ),
        }
        for item in items
    ]
