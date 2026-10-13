"""
Athena Layer 5 — Inbox Router

GET  /api/v1/inbox            — recent events (map updates, new maps, feed papers citing milestones), newest first
GET  /api/v1/inbox/unread     — how many are unread, for the bell
POST /api/v1/inbox/seen       — mark everything read up to now
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from athena.api import auth
from athena.api.deps import get_db
from athena.core.models import User
from athena.database import inbox as db

router = APIRouter(prefix="/api/v1/inbox", tags=["Inbox"])


@router.get("")
def list_events(limit: int = Query(30, ge=1, le=200), session: Session = Depends(get_db),
                user: User = Depends(auth.active_user)):
    return db.events_for(session, user, limit)


@router.get("/unread")
def unread(session: Session = Depends(get_db), user: User = Depends(auth.active_user)):
    return {"unread": db.unread_count(session, user)}


@router.post("/seen", status_code=204)
def seen(session: Session = Depends(get_db), user: User = Depends(auth.active_user)):
    db.mark_seen(session, user)
