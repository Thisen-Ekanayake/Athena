"""
Scoring health and rescoring (Settings → Health and Clusters).

POST /api/v1/admin/rescore-all   — queue a full re-score (admin)
GET  /api/v1/health/scoring      — how many items are scored, trending and queued, and the average score
GET  /api/v1/health/fetch        — fetch successes and failures over all fetch logs
"""
from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from athena.api.auth import require_admin
from athena.api.deps import get_db
from athena.core.models import ContentItem, FetchLog
from athena.pipeline.scoring import score_all_items

router = APIRouter(prefix="/api/v1", tags=["Scoring"])


@router.post("/admin/rescore-all")
def trigger_rescore(user=Depends(require_admin)):
    """Admin endpoint: trigger a full re-score of all items (e.g. after config change)."""
    score_all_items.delay()
    return {"status": "Re-score triggered", "message": "All items will be re-scored in the background."}


@router.get("/health/scoring")
def scoring_health(db: Session = Depends(get_db)):
    """Scoring health metrics for the dashboard."""
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
    from athena.core.redis_client import get_redis
    r = get_redis()
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


@router.get("/health/fetch")
def fetch_health(db: Session = Depends(get_db)):
    """Fetch health data for the dashboard."""
    total_logs = db.execute(select(func.count(FetchLog.id))).scalar() or 0
    successful_fetches = db.execute(
        select(func.count(FetchLog.id)).where(FetchLog.status == "success")
    ).scalar() or 0
    failed_fetches = total_logs - successful_fetches

    return {
        "total_fetches": total_logs,
        "successful_fetches": successful_fetches,
        "failed_fetches": failed_fetches,
        "success_rate": round(successful_fetches / max(total_logs, 1) * 100, 2)
    }
