"""
Athena Layer 3 — Score Breakdown API

FastAPI endpoint for exposing score explainability to the card UI (Layer 5).
"""
from uuid import UUID
from fastapi import FastAPI, HTTPException, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from athena.database.db import SessionLocal
from athena.core.models import ContentItem, ContentScore
from athena.pipeline.scoring import score_all_items

app = FastAPI(title="Athena Scoring API", version="1.0.0")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _score_label(score: float) -> str:
    """Convert a numeric score to a human-readable label."""
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
    else:
        return "Minimal"


@app.get("/items/{item_id}/score-breakdown")
def get_score_breakdown(item_id: str, db: Session = Depends(get_db)):
    """
    Returns the full score breakdown for a content item.

    Response shape matches the plan document:
    {
        "composite_score": 0.84,
        "is_trending": true,
        "signals": {
            "citation_impact": {"score": 0.91, "label": "Strong", "weight": 0.30},
            ...
        },
        "computed_at": "...",
        "score_version": 3
    }
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

    # Get the latest content_score for this item
    score_record = db.execute(
        select(ContentScore)
        .where(ContentScore.item_id == item_uuid)
        .order_by(ContentScore.computed_at.desc())
    ).scalar_one_or_none()

    if not score_record:
        raise HTTPException(status_code=404, detail="No score computed for this item yet")

    # Fetch scoring config weights for context
    from athena.pipeline.scoring import _get_weights
    category = item.category.value if hasattr(item.category, 'value') else str(item.category)
    weights = _get_weights(category, db)

    return {
        "item_id": str(item.id),
        "title": item.title,
        "composite_score": round(score_record.composite_score, 4),
        "is_trending": item.is_trending or False,
        "category_rank": item.category_rank,
        "signals": {
            "citation_impact": {
                "score": round(score_record.citation_score, 4),
                "label": _score_label(score_record.citation_score),
                "weight": weights.get("citation", 0.30),
            },
            "engagement": {
                "score": round(score_record.engagement_score, 4),
                "label": _score_label(score_record.engagement_score),
                "weight": weights.get("engagement", 0.15),
            },
            "community_sentiment": {
                "score": round(score_record.sentiment_score, 4),
                "label": _score_label(score_record.sentiment_score),
                "weight": weights.get("sentiment", 0.15),
            },
            "recency_velocity": {
                "score": round(score_record.recency_score, 4),
                "label": _score_label(score_record.recency_score),
                "weight": weights.get("recency", 0.20),
            },
            "source_authority": {
                "score": round(score_record.authority_score, 4),
                "label": _score_label(score_record.authority_score),
                "weight": weights.get("authority", 0.20),
            },
        },
        "computed_at": score_record.computed_at.isoformat() if score_record.computed_at else None,
        "score_version": score_record.score_version,
    }


@app.get("/items/top/{category}")
def get_top_items(category: str, limit: int = 20, db: Session = Depends(get_db)):
    """Get top-ranked items in a category."""
    items = db.execute(
        select(ContentItem)
        .where(ContentItem.category == category)
        .where(ContentItem.score.isnot(None))
        .order_by(ContentItem.category_rank.asc())
        .limit(limit)
    ).scalars().all()

    return [
        {
            "id": str(item.id),
            "title": item.title,
            "url": item.url,
            "score": round(item.score, 4) if item.score else 0,
            "category_rank": item.category_rank,
            "is_trending": item.is_trending or False,
            "published_at": item.published_at.isoformat() if item.published_at else None,
        }
        for item in items
    ]


@app.get("/items/trending")
def get_trending_items(limit: int = 20, db: Session = Depends(get_db)):
    """Get currently trending items across all categories."""
    items = db.execute(
        select(ContentItem)
        .where(ContentItem.is_trending .is_(True))
        .order_by(ContentItem.score.desc())
        .limit(limit)
    ).scalars().all()

    return [
        {
            "id": str(item.id),
            "title": item.title,
            "url": item.url,
            "score": round(item.score, 4) if item.score else 0,
            "category": item.category.value if hasattr(item.category, 'value') else str(item.category),
            "is_trending": True,
            "published_at": item.published_at.isoformat() if item.published_at else None,
        }
        for item in items
    ]


@app.post("/admin/rescore-all")
def trigger_rescore():
    """Admin endpoint: trigger a full re-score of all items (e.g. after config change)."""
    score_all_items.delay()
    return {"status": "Re-score triggered", "message": "All items will be re-scored in the background."}


@app.get("/health/scoring")
def scoring_health(db: Session = Depends(get_db)):
    """Scoring health metrics for the dashboard."""
    from sqlalchemy import func

    total_items = db.execute(select(func.count(ContentItem.id))).scalar()
    scored_items = db.execute(
        select(func.count(ContentItem.id)).where(ContentItem.scored_at.isnot(None))
    ).scalar()
    trending_items = db.execute(
        select(func.count(ContentItem.id)).where(ContentItem.is_trending .is_(True))
    ).scalar()
    avg_score = db.execute(
        select(func.avg(ContentItem.score)).where(ContentItem.score > 0)
    ).scalar()

    # Queue depth
    import redis as redis_lib
    import os
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    r = redis_lib.from_url(redis_url)
    queue_depth = r.llen("athena:scoring_queue")

    return {
        "total_items": total_items or 0,
        "scored_items": scored_items or 0,
        "unscored_items": (total_items or 0) - (scored_items or 0),
        "trending_items": trending_items or 0,
        "average_score": round(avg_score, 4) if avg_score else 0,
        "scoring_queue_depth": queue_depth,
        "trending_percentage": round(
            (trending_items or 0) / max(1, total_items or 1) * 100, 2
        ),
    }
