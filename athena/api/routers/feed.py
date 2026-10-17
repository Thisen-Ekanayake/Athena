"""
Athena Layer 5 — Feed Router

GET /api/v1/feed — paginated, sorted, filtered content feed.
"""
from datetime import datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from loguru import logger
from sqlalchemy.orm import Session
from sqlalchemy import select, func, desc
import redis as redis_lib

from athena.api.auth import active_user
from athena.api.deps import get_db, get_redis
from athena.api.cache import cache_get, cache_set
from athena.api.config import settings
from athena.api.schemas import (
    FeedResponse,
)
from athena.core.models import (
    ContentItem, Source, Cluster, ItemLink, User,
)
from athena.database import feedback, personal
from athena.pipeline import interests

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
        # Milestones of the evolution maps this paper cites (athena.evolution.feedlink)
        "milestones_cited": len(((item.extra_data or {}).get("evolution") or {}).get("cites") or []),
        # Citations gained this week (athena.pipeline.momentum); papers only, None until known
        "citation_gain_7d": item.citation_gain_7d,
    }


@router.get("/feed", response_model=FeedResponse)
def get_feed(
    sort: str = Query("score", pattern="^(score|date|trending|foryou)$"),
    category: str | None = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=50),
    cluster_id: str | None = Query(None),
    source_id: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    date_range: str | None = Query(None, pattern="^(24h|7d|30d)$"),
    unread: bool = Query(False),
    db: Session = Depends(get_db),
    r: redis_lib.Redis = Depends(get_redis),
    user: User = Depends(active_user),
):
    """
    Returns a paginated, sorted list of content cards.
    The primary endpoint for the main feed. Items the user marked "not interested" are left out of every order;
    ``foryou`` orders by the score blended with the user's interests (athena.pipeline.interests), and falls back to
    the score (``personalised`` false) while there is nothing to learn from or personalisation is off.
    ``unread`` leaves out what the user marked read.
    """
    filters = f"{category}:{cluster_id}:{source_id}:{date_from}:{date_to}:{date_range}"
    conditions = _conditions(category, cluster_id, source_id, date_from, date_to, date_range)
    hides = feedback.has_hidden(db, user.id)
    if hides:
        conditions.append(feedback.not_hidden(user.id))
    if unread:
        conditions.append(personal.unread_filter(user.id))

    if sort == "foryou":
        profile = interests.active_profile(db, user.id)
        if profile is not None:
            try:
                ranking = interests.ranked(db, r, user.id, profile, conditions, f"{filters}:{unread}")
                return _for_user(db, user, _ranked_page(db, ranking["order"], page, limit))
            except Exception as exc:  # Qdrant down: the plain score order below
                logger.warning(f"For you: falling back to the score for {user.id}: {exc}")
        sort = "score"

    # ── Cache check ─────────────────────────────────────
    # The user only joins the key when the page depends on them; each item's own state is added afterwards.
    mine = f":u{user.id}:{interests.version(r, user.id)}" if unread or hides else ""
    cache_key = f"feed:{sort}:{page}:{limit}:{filters}{mine}"
    cached = cache_get(r, cache_key)
    if cached:
        return _for_user(db, user, cached)

    # ── Build query ─────────────────────────────────────
    query = select(ContentItem).join(
        Source, ContentItem.source_id == Source.id, isouter=True
    ).outerjoin(
        Cluster, ContentItem.cluster_id == Cluster.id
    ).where(*conditions)

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

    # ── Build response ──────────────────────────────────
    response = {
        "items": _feed_items(db, items),
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total,
            "has_next": (page * limit) < total,
        },
        "personalised": False,
    }

    # ── Cache store ─────────────────────────────────────
    ttl = settings.CACHE_FEED_SCORE_TTL if sort == "score" else settings.CACHE_FEED_DATE_TTL  # noqa: E501
    if unread:
        ttl = min(ttl, 60)  # marking an item read changes this page
    cache_set(r, cache_key, response, ttl)

    return _for_user(db, user, response)


def _conditions(category, cluster_id, source_id, date_from, date_to, date_range) -> list:
    """The feed's filters as WHERE clauses on ContentItem."""
    conditions = []
    if category:
        conditions.append(ContentItem.category == category)
    if cluster_id:
        conditions.append(ContentItem.cluster_id == cluster_id)
    if source_id:
        conditions.append(ContentItem.source_id == source_id)
    if date_from:
        conditions.append(ContentItem.published_at >= date_from)
    if date_to:
        conditions.append(ContentItem.published_at <= date_to)
    if date_range:
        now = datetime.utcnow()
        since = {"24h": timedelta(hours=24), "7d": timedelta(days=7), "30d": timedelta(days=30)}[date_range]
        conditions.append(ContentItem.published_at >= now - since)
    return conditions


def _feed_items(db: Session, items: list) -> list[dict]:
    """Feed cards for ``items``, with how many related items each has."""
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
    return [_build_feed_item(item, related_counts.get(item.id, 0)) for item in items]


def _ranked_page(db: Session, order: list, page: int, limit: int) -> dict:
    """One page of a For-you order ([[id, for_you, interest rank], ...]), each card with its interest rank."""
    rows = order[(page - 1) * limit:page * limit]
    ids = [UUID(row[0]) for row in rows]
    found = {i.id: i for i in db.execute(select(ContentItem).where(ContentItem.id.in_(ids))).scalars().all()} \
        if ids else {}
    items = [found[i] for i in ids if i in found]
    interest = {UUID(row[0]): row[2] for row in rows}
    return {
        "items": [card | {"interest": interest.get(item.id)} for card, item in zip(_feed_items(db, items), items)],
        "pagination": {"page": page, "limit": limit, "total": len(order), "has_next": page * limit < len(order)},
        "personalised": True,
    }


def _for_user(db: Session, user: User, response: dict) -> dict:
    """The page with each item's ``me`` (read, reaction, annotated) for this user."""
    ids = [UUID(str(i["id"])) for i in response["items"]]
    reactions = feedback.reactions_for(db, user.id, ids)
    return response | {"items": personal.overlay(db, user.id, response["items"], reactions)}


def without_hidden(db: Session, user: User, response: dict) -> dict:
    """A short shared list (Rising) without the user's "not interested" items, taken out after the cache read."""
    hidden = {str(i) for i in feedback.hidden_ids(db, user.id)}
    return response | {"items": [i for i in response["items"] if str(i["id"]) not in hidden]} if hidden else response
