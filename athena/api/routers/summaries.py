"""
Item summaries and the admin summary tools.

GET  /api/v1/items/{item_id}/summary                    — an item's summary; written on demand when it is lazy or stale
GET  /api/v1/admin/summaries/status                     — items by summary status, and why items were skipped (admin)
GET  /api/v1/admin/summaries/cost                       — today's and the last 7 days' summary spend (admin)
GET  /api/v1/admin/summaries/sample                     — 10 random summaries to spot-check (admin)
POST /api/v1/admin/items/{item_id}/regenerate-summary   — queue one item for a new summary (admin)
"""
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from athena.api.auth import require_admin
from athena.api.deps import get_db
from athena.core.models import ContentItem, Source, SummaryStatus, UsageEvent

router = APIRouter(prefix="/api/v1", tags=["Summarisation"])
# What usage_events calls summaries and cluster labels (athena.pipeline.summarisation.USAGE_FEATURES)
SUMMARY_FEATURES = ("summary", "cluster_label")


@router.get("/items/{item_id}/summary")
def get_item_summary(item_id: str, db: Session = Depends(get_db)):
    """Fetch summary for an item. Generates on-demand if status is LAZY."""
    try:
        item_uuid = UUID(item_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid item ID format")

    item = db.execute(select(ContentItem).where(ContentItem.id == item_uuid)).scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    from athena.pipeline.summarisation_tasks import (
        summarise_on_demand_sync, _does_item_need_resummary,
        get_active_prompt_version
    )
    from athena.core.models import JobType

    active_prompt = get_active_prompt_version(JobType.ITEM_SUMMARY, db)
    needs_resummary = False
    if active_prompt and _does_item_need_resummary(item, active_prompt.version):
        needs_resummary = True

    if item.summary_status == SummaryStatus.SKIPPED:
        needs_resummary = False  # the same thin text would be skipped again
    if item.summary_status == SummaryStatus.LAZY or needs_resummary:
        item = summarise_on_demand_sync(item_id)
        if not item or item.summary_status != SummaryStatus.COMPLETE:
            raise HTTPException(status_code=500, detail="Failed to generate on-demand summary")

    return {
        "item_id": str(item.id),
        "status": item.summary_status.value if item.summary_status else None,
        "summary": item.summary,
        "takeaways": item.takeaways,
        "version": item.summary_version,
        "summarised_at": item.summarised_at.isoformat() if item.summarised_at else None,
        "skipped": (item.extra_data or {}).get("summary_skipped"),
    }


@router.get("/admin/summaries/status")
def summary_status(db: Session = Depends(get_db), user=Depends(require_admin)):
    """How many items are at each summary status, and the skipped ones by source and reason, most first."""
    counts = {s.value: 0 for s in SummaryStatus}
    for status, n in db.execute(select(ContentItem.summary_status, func.count())
                                .group_by(ContentItem.summary_status)).all():
        if status is not None:
            counts[status.value] += n
    skipped: dict[tuple, int] = {}
    for name, extra in db.execute(select(Source.name, ContentItem.extra_data)
                                  .join(Source, Source.id == ContentItem.source_id, isouter=True)
                                  .where(ContentItem.summary_status == SummaryStatus.SKIPPED)).all():
        key = (name or "Unknown", (extra or {}).get("summary_skipped") or "no reason given")
        skipped[key] = skipped.get(key, 0) + 1
    return {"counts": counts, "skipped": [{"source": s, "reason": reason, "count": n}
                                          for (s, reason), n in sorted(skipped.items(), key=lambda kv: -kv[1])]}


@router.get("/admin/summaries/cost")
def get_summarisation_cost(db: Session = Depends(get_db), user=Depends(require_admin)):
    """Summary and cluster-label spend in USD today and over the last 7 days, and today's tokens by model."""
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=7)
    features = UsageEvent.feature.in_(SUMMARY_FEATURES)

    def spend(since: datetime) -> float:
        return db.execute(select(func.coalesce(func.sum(UsageEvent.cost_usd), 0.0))
                          .where(features, UsageEvent.created_at >= since)).scalar_one()

    stats = db.execute(
        select(UsageEvent.feature, UsageEvent.model, func.sum(UsageEvent.calls),
               func.sum(UsageEvent.input_tokens), func.sum(UsageEvent.output_tokens))
        .where(features, UsageEvent.created_at >= today_start)
        .group_by(UsageEvent.feature, UsageEvent.model)
    ).all()
    return {
        "today_spend_usd": round(spend(today_start), 4),
        "7_day_spend_usd": round(spend(week_start), 4),
        "breakdown": [{"feature": feature, "model": model, "calls": calls or 0, "input_tokens": tokens_in or 0,
                       "output_tokens": tokens_out or 0}
                      for feature, model, calls, tokens_in, tokens_out in stats],
    }


@router.get("/admin/summaries/sample")
def get_summary_sample(db: Session = Depends(get_db), user=Depends(require_admin)):
    """Returns 10 random summaries for manual spot-check."""
    items = db.execute(
        select(ContentItem)
        .where(ContentItem.summary_status == SummaryStatus.COMPLETE)
        .order_by(func.random())
        .limit(10)
    ).scalars().all()

    return [
        {
            "id": str(item.id),
            "title": item.title,
            "category": item.category.value if hasattr(item.category, 'value') else str(item.category),
            "summary": item.summary,
            "takeaways": item.takeaways
        }
        for item in items
    ]


@router.post("/admin/items/{item_id}/regenerate-summary")
def regenerate_summary(item_id: str, db: Session = Depends(get_db), user=Depends(require_admin)):
    """Manually trigger regeneration for a specific item."""
    try:
        item_uuid = UUID(item_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid item ID format")

    item = db.execute(select(ContentItem).where(ContentItem.id == item_uuid)).scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    from athena.pipeline.summarisation_tasks import summarise_item_worker
    summarise_item_worker.apply_async(args=[item_id], queue='summary_urgent')
    return {"status": "regenerating", "message": f"Item {item_id} enqueued to summary_urgent"}
