"""
Athena Layer 5 — Trending Router

GET /api/v1/trending — trending items + daily brief.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, desc
from sqlalchemy.orm import Session
import redis as redis_lib

from athena.api.deps import get_db, get_redis
from athena.api.cache import cache_get, cache_set
from athena.api.config import settings
from athena.api.routers.feed import _build_feed_item
from athena.core.models import ContentItem, Source, TrendingBrief

router = APIRouter(prefix="/api/v1", tags=["Trending"])


@router.get("/trending")
def get_trending(
    category: str | None = Query(None),
    db: Session = Depends(get_db),
    r: redis_lib.Redis = Depends(get_redis),
):
    """
    Returns currently trending items and the daily trending brief.
    """
    cache_key = f"trending:{category}"
    cached = cache_get(r, cache_key)
    if cached:
        return cached

    # Fetch trending items
    query = (
        select(ContentItem)
        .join(Source, ContentItem.source_id == Source.id, isouter=True)
        .where(ContentItem.is_trending.is_(True))
    )
    if category:
        query = query.where(ContentItem.category == category)
    query = query.order_by(desc(ContentItem.score))

    items = db.execute(query).scalars().all()

    # Fetch latest trending brief
    brief_query = (
        select(TrendingBrief)
        .order_by(desc(TrendingBrief.generated_at))
    )
    if category:
        brief_query = brief_query.where(TrendingBrief.category == category)
    brief = db.execute(brief_query).scalar_one_or_none()

    response = {
        "brief": {
            "theme": brief.theme if brief else None,
            "brief": brief.brief if brief else None,
            "generated_at": (
                brief.generated_at.isoformat()
                if brief and brief.generated_at else None
            ),
        } if brief else None,
        "items": [_build_feed_item(item) for item in items],
    }

    cache_set(r, cache_key, response, settings.CACHE_TRENDING_TTL)
    return response
