"""
The feed and the maps: a feed item's place in them, and recent feed papers citing their milestones.
"""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from athena.api.deps import get_db
from athena.database import evolution as db

router = APIRouter()


@router.get("/items/{item_id}")
def feed_item_place(item_id: UUID, session: Session = Depends(get_db)):
    place = db.feed_place(session, item_id)
    if place is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return place


@router.get("/new-papers")
def new_papers(days: int = Query(30, ge=1, le=120), topic: str | None = Query(None, max_length=200),
               limit: int | None = Query(None, ge=1, le=500, description="Only the first this many; all when unset"),
               session: Session = Depends(get_db)):
    """Feed papers from the last ``days`` days that cite milestones, those citing the most first. The pages show
    the first few, so they ask for ``limit``: a month of them is over a thousand papers, most of a megabyte."""
    return db.new_feed_papers(session, days, topic, limit)
