"""
A feed that learns from feedback (ROADMAP P1): reactions and the user's interest settings.

PUT|DELETE /api/v1/items/{item_id}/feedback      — 👍 (up), 👎 (down) or not interested (hide); remove it
GET        /api/v1/me/interests                  — on or off, and what there is to learn from
PUT        /api/v1/me/interests                  — switch "Personalise my feed" on or off
GET        /api/v1/me/feedback?reaction=up       — the items with one kind of reaction, newest first
DELETE     /api/v1/me/feedback                   — forget every reaction (saved items still count)

The order itself is the feed's ``sort=foryou`` (athena.api.routers.feed).
"""
from __future__ import annotations

from typing import Literal
from uuid import UUID

import redis as redis_lib
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from athena.api import auth
from athena.api.deps import get_db, get_redis
from athena.core.models import User
from athena.database import feedback
from athena.pipeline import interests

router = APIRouter(prefix="/api/v1", tags=["Interests"])


class ReactionRequest(BaseModel):
    reaction: Literal["up", "down", "hide"]


class InterestSettings(BaseModel):
    enabled: bool


@router.put("/items/{item_id}/feedback")
def react(item_id: UUID, body: ReactionRequest, session: Session = Depends(get_db),
          r: redis_lib.Redis = Depends(get_redis), user: User = Depends(auth.active_user)):
    if not feedback.set_reaction(session, user.id, item_id, body.reaction):
        raise HTTPException(status_code=404, detail="Item not found")
    interests.touch(session, user.id, r)
    return {"reaction": body.reaction}


@router.delete("/items/{item_id}/feedback", status_code=204)
def unreact(item_id: UUID, session: Session = Depends(get_db), r: redis_lib.Redis = Depends(get_redis),
            user: User = Depends(auth.active_user)):
    feedback.clear_reaction(session, user.id, item_id)
    interests.touch(session, user.id, r)
    return Response(status_code=204)


@router.get("/me/interests")
def my_interests(session: Session = Depends(get_db), user: User = Depends(auth.active_user)):
    return interests.summary(session, user.id)


@router.put("/me/interests")
def set_my_interests(body: InterestSettings, session: Session = Depends(get_db),
                     r: redis_lib.Redis = Depends(get_redis), user: User = Depends(auth.active_user)):
    interests.set_enabled(session, user.id, body.enabled, r)
    return interests.summary(session, user.id)


@router.get("/me/feedback")
def my_feedback(reaction: Literal["up", "down", "hide"], session: Session = Depends(get_db),
                user: User = Depends(auth.active_user)):
    return {"items": feedback.listed(session, user.id, reaction)}


@router.delete("/me/feedback")
def reset_feedback(session: Session = Depends(get_db), r: redis_lib.Redis = Depends(get_redis),
                   user: User = Depends(auth.active_user)):
    removed = feedback.reset(session, user.id)
    interests.touch(session, user.id, r)
    return {"removed": removed}
