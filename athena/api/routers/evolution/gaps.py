"""
Gap themes, and idea checks against every map.
"""
from uuid import UUID

import redis as redis_lib
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from athena.api import auth
from athena.api.cache import cache_get, cache_set
from athena.api.config import settings
from athena.api.deps import get_db, get_redis
from athena.core.models import User
from athena.database import evolution as db
from athena.evolution import ideas
from athena.api.routers.evolution._common import _cache_key, _topic_or_404

router = APIRouter()


class IdeaCheckRequest(BaseModel):
    idea: str = Field(..., min_length=20, max_length=4000)
    verdict: bool = True


@router.get("/topics/{slug}/gaps")
def topic_gaps(slug: str, session: Session = Depends(get_db), r: redis_lib.Redis = Depends(get_redis)):
    topic = _topic_or_404(session, slug)
    key = _cache_key(session, topic, "gaps")
    cached = cache_get(r, key)
    if cached:
        return cached
    payload = db.topic_gaps(session, topic)
    cache_set(r, key, payload, settings.CACHE_CLUSTERS_TTL)
    return payload


@router.post("/idea-checks", status_code=201)
def create_idea_check(body: IdeaCheckRequest, session: Session = Depends(get_db),
                      user: User = Depends(auth.spend("idea_check"))):
    """The idea against every built map. Takes a few seconds, longer with the verdict; saved to the account."""
    idea = body.idea.strip()
    try:
        result = ideas.check_idea(session, idea, verdict=body.verdict, user_id=user.id)
    except ideas.IdeaCheckUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return db.save_idea_check(session, user.id, idea, result)


@router.get("/idea-checks")
def list_idea_checks(session: Session = Depends(get_db), user: User = Depends(auth.active_user)):
    return db.list_idea_checks(session, user.id)


@router.get("/idea-checks/{check_id}")
def get_idea_check(check_id: UUID, session: Session = Depends(get_db), user: User = Depends(auth.active_user)):
    check = db.get_idea_check(session, user.id, check_id)
    if check is None:
        raise HTTPException(status_code=404, detail="Check not found")
    return check


@router.delete("/idea-checks/{check_id}", status_code=204)
def delete_idea_check(check_id: UUID, session: Session = Depends(get_db), user: User = Depends(auth.active_user)):
    if not db.delete_idea_check(session, user.id, check_id):
        raise HTTPException(status_code=404, detail="Check not found")
