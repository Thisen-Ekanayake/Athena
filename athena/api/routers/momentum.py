"""
Citation momentum (ROADMAP P3): how fast feed papers gather citations (athena.pipeline.momentum).

GET /api/v1/items/{item_id}/momentum     — total, gains over 7 and 30 days, and the last 90 days, one point a day
GET /api/v1/momentum/rising?window=7d    — feed papers by citations gained over 7 or 30 days
"""
from datetime import datetime, timezone
from uuid import UUID

import redis as redis_lib
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from athena.api.auth import active_user
from athena.api.cache import cache_get, cache_set
from athena.api.deps import get_db, get_redis
from athena.api.routers.feed import _build_feed_item, _for_user
from athena.core.models import ContentCategory, ContentItem, User
from athena.pipeline import momentum

router = APIRouter(prefix="/api/v1", tags=["Momentum"])

RISING_TTL = 3600  # the gains change once a day
SPARK_DAYS = {"7d": 30, "30d": 90}


@router.get("/items/{item_id}/momentum")
def item_momentum(item_id: UUID, db: Session = Depends(get_db)):
    item = db.get(ContentItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    ss = (item.extra_data or {}).get("semantic_scholar") or {}
    is_paper = item.category == ContentCategory.PAPER
    return {
        "total": item.citation_count or 0,
        "fetched_at": ss.get("fetched_at"),
        "gain_7d": item.citation_gain_7d,
        "gain_30d": item.citation_gain_30d,
        "series": momentum.series(db, item, datetime.now(timezone.utc)) if is_paper else [],
    }


@router.get("/momentum/rising")
def rising(window: str = Query("7d", pattern="^(7d|30d)$"), limit: int = Query(10, ge=1, le=50),
           db: Session = Depends(get_db), r: redis_lib.Redis = Depends(get_redis),
           user: User = Depends(active_user)):
    key = f"rising:{window}:{limit}"
    cached = cache_get(r, key)
    if cached:
        return _for_user(db, user, cached)
    column = ContentItem.citation_gain_7d if window == "7d" else ContentItem.citation_gain_30d
    items = db.execute(select(ContentItem).where(column > 0)
                       .order_by(desc(column), desc(ContentItem.citation_count)).limit(limit)).scalars().all()
    now = datetime.now(timezone.utc)
    payload = {"window": window, "items": [
        _build_feed_item(item) | {
            "gain": getattr(item, column.key),
            "series": [p["citations"] for p in momentum.series(db, item, now, SPARK_DAYS[window])],
        } for item in items]}
    cache_set(r, key, payload, RISING_TTL)
    return _for_user(db, user, payload)
