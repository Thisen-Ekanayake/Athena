"""
A map's graph, timeline, links to other maps, rising papers, one paper's detail and milestone overrides.
"""
from typing import Literal
from uuid import UUID

import redis as redis_lib
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from athena.api import auth
from athena.api.cache import cache_get, cache_invalidate, cache_set
from athena.api.config import settings
from athena.api.deps import get_db, get_redis
from athena.database import evolution as db
from athena.api.routers.evolution._common import _built_topic_or_409, _cache_key, _topic_or_404

router = APIRouter()


class MilestoneOverrideRequest(BaseModel):
    action: Literal["pin", "unpin", "reset"]
    note: str | None = Field(None, max_length=500)


@router.get("/topics/{slug}/graph")
def topic_graph(
    slug: str,
    limit: int = Query(250, ge=0, le=2000, description="Papers to draw; 0 draws every paper"),
    session: Session = Depends(get_db),
    r: redis_lib.Redis = Depends(get_redis),
):
    topic = _topic_or_404(session, slug)
    key = _cache_key(session, topic, "graph", limit)
    cached = cache_get(r, key)
    if cached:
        return cached
    payload = db.topic_graph(session, topic, limit=limit)
    cache_set(r, key, payload, settings.CACHE_CLUSTERS_TTL)
    return payload


@router.get("/topics/{slug}/timeline")
def topic_timeline(slug: str, session: Session = Depends(get_db), r: redis_lib.Redis = Depends(get_redis)):
    topic = _topic_or_404(session, slug)
    key = _cache_key(session, topic, "timeline")
    cached = cache_get(r, key)
    if cached:
        return cached
    payload = db.topic_timeline(session, topic)
    cache_set(r, key, payload, settings.CACHE_CLUSTERS_TTL)
    return payload


@router.get("/topics/{slug}/links")
def topic_links(slug: str, session: Session = Depends(get_db), r: redis_lib.Redis = Depends(get_redis)):
    topic = _built_topic_or_409(session, slug)
    # Other maps' builds change the links too, so the key carries every built map's build time.
    key = _cache_key(session, topic, "links", db.maps_version(session))
    cached = cache_get(r, key)
    if cached:
        return cached
    payload = db.topic_links(session, topic)
    cache_set(r, key, payload, settings.CACHE_CLUSTERS_TTL)
    return payload


@router.get("/topics/{slug}/rising")
def topic_rising(slug: str, limit: int = Query(10, ge=1, le=30), session: Session = Depends(get_db),
                 r: redis_lib.Redis = Depends(get_redis)):
    """The map's papers gaining citations fastest (OpenAlex's citations per year)."""
    topic = _built_topic_or_409(session, slug)
    key = _cache_key(session, topic, "rising", limit)
    cached = cache_get(r, key)
    if cached:
        return cached
    payload = {"papers": db.topic_rising(session, topic, limit)}
    # Citations per year arrive after a build without changing it, so this keeps for minutes, not the hour.
    cache_set(r, key, payload, settings.CACHE_CLUSTER_DETAIL_TTL)
    return payload


@router.get("/topics/{slug}/papers/{paper_id}")
def paper_detail(slug: str, paper_id: UUID, session: Session = Depends(get_db)):
    topic = _topic_or_404(session, slug)
    detail = db.paper_detail(session, topic, paper_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Paper is not part of this topic")
    return detail


@router.post("/topics/{slug}/milestones/{paper_id}", dependencies=[Depends(auth.require_admin)])
def set_milestone(
    slug: str,
    paper_id: UUID,
    body: MilestoneOverrideRequest,
    session: Session = Depends(get_db),
    r: redis_lib.Redis = Depends(get_redis),
):
    topic = _topic_or_404(session, slug)
    if not db.set_override(session, topic, paper_id, body.action, body.note):
        raise HTTPException(status_code=404, detail="Paper is not part of this topic")
    cache_invalidate(r, f"evo:{slug}:*")
    return db.paper_detail(session, topic, paper_id)
