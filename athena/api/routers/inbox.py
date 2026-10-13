"""
Athena Layer 5 — Inbox Router

GET  /api/v1/inbox            — recent entries the user sees, newest first: new maps, updates and citing papers
                                for the maps they follow, what their watches caught, their digests
GET  /api/v1/inbox/unread     — how many are unread, for the bell
POST /api/v1/inbox/seen       — mark everything read up to now
GET  /api/v1/inbox/settings   — the user's digest schedule and muted kinds
PUT  /api/v1/inbox/settings   — change them
"""
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from athena.api import auth
from athena.api.deps import get_db
from athena.core.models import User
from athena.database import inbox as db


class InboxSettingsBody(BaseModel):
    digest: Literal["off", "daily", "weekly"]
    digest_day: int = Field(0, ge=0, le=6)  # 0 = Monday
    muted_kinds: list[Literal["map_new", "feed_citations"]] = []


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


def _public(settings: dict) -> dict:
    last = settings.get("last_digest_at")
    return {k: v for k, v in settings.items() if k != "last_digest_at"} | {
        "last_digest_at": last.isoformat() if last else None}


@router.get("/settings")
def get_settings(session: Session = Depends(get_db), user: User = Depends(auth.active_user)):
    return _public(db.get_settings(session, user))


@router.put("/settings")
def put_settings(body: InboxSettingsBody, session: Session = Depends(get_db),
                 user: User = Depends(auth.active_user)):
    db.save_settings(session, user.id, digest=body.digest, digest_day=body.digest_day,
                     muted_kinds=sorted(set(body.muted_kinds)))
    return _public(db.get_settings(session, user))
