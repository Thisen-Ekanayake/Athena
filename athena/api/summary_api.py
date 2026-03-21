from uuid import UUID
from fastapi import FastAPI, HTTPException, Depends
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from datetime import datetime, timezone

from athena.database.db import SessionLocal
from athena.core.models import ContentItem, SummaryStatus, SummaryUsageLog

app = FastAPI(title="Athena Summarisation API", version="1.0.0")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.get("/items/{item_id}/summary")
def get_item_summary(item_id: str, db: Session = Depends(get_db)):
    """Fetch summary for an item. Generates on-demand if status is LAZY."""
    try:
        item_uuid = UUID(item_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid item ID format")

    item = db.execute(select(ContentItem).where(ContentItem.id == item_uuid)).scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    if item.summary_status == SummaryStatus.LAZY:
        from athena.pipeline.summarisation_tasks import summarise_on_demand_sync
        item = summarise_on_demand_sync(item_id)
        if not item or item.summary_status != SummaryStatus.COMPLETE:
            raise HTTPException(status_code=500, detail="Failed to generate on-demand summary")

    return {
        "item_id": str(item.id),
        "status": item.summary_status.value if item.summary_status else None,
        "summary": item.summary,
        "takeaways": item.takeaways,
        "version": item.summary_version,
        "summarised_at": item.summarised_at.isoformat() if item.summarised_at else None
    }


@app.get("/admin/summaries/cost")
def get_summarisation_cost(db: Session = Depends(get_db)):
    """Daily and 7-day rolling spend in USD, and token breakdowns."""
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=7)

    today_spend = db.execute(
        select(func.sum(SummaryUsageLog.total_cost_usd))
        .where(SummaryUsageLog.created_at >= today_start)
    ).scalar() or 0.0

    weekly_spend = db.execute(
        select(func.sum(SummaryUsageLog.total_cost_usd))
        .where(SummaryUsageLog.created_at >= week_start)
    ).scalar() or 0.0

    return {
        "today_spend_usd": round(today_spend, 4),
        "7_day_spend_usd": round(weekly_spend, 4)
    }


@app.get("/admin/summaries/sample")
def get_summary_sample(db: Session = Depends(get_db)):
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


@app.post("/admin/items/{item_id}/regenerate-summary")
def regenerate_summary(item_id: str, db: Session = Depends(get_db)):
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
