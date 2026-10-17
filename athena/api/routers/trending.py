"""
Athena Layer 5 — Trending Router

GET /api/v1/trending — trending items.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, desc
from sqlalchemy.orm import Session
import redis as redis_lib

from athena.api.deps import get_db, get_redis
from athena.api.cache import cache_get, cache_set
from athena.api.config import settings
from athena.api.auth import active_user
from athena.api.routers.feed import _build_feed_item, _for_user
from athena.database import feedback
from athena.core.models import ContentItem, Source, User

router = APIRouter(prefix="/api/v1", tags=["Trending"])


@router.get("/trending")
def get_trending(
    category: str | None = Query(None),
    db: Session = Depends(get_db),
    r: redis_lib.Redis = Depends(get_redis),
    user: User = Depends(active_user),
):
    """
    Returns currently trending items.
    """
    cache_key = f"trending:{category}"
    cached = cache_get(r, cache_key)
    if cached:
        return _for_user(db, user, _without_hidden(db, user, cached))

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

    response = {"items": [_build_feed_item(item) for item in items]}

    cache_set(r, cache_key, response, settings.CACHE_TRENDING_TTL)
    return _for_user(db, user, _without_hidden(db, user, response))


def _without_hidden(db: Session, user: User, response: dict) -> dict:
    """Trending is one short shared list: the user's "not interested" items come out after the cache."""
    hidden = {str(i) for i in feedback.hidden_ids(db, user.id)}
    return response | {"items": [i for i in response["items"] if str(i["id"]) not in hidden]} if hidden else response
