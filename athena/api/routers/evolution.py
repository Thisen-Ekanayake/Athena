"""
Athena Layer 5 — Research Evolution Router

GET  /api/v1/evolution/topics                                — curated topics and their build status
GET  /api/v1/evolution/search?q=                             — match a query to a topic by alias or by its
                                                               papers' content, or say it is not covered
GET  /api/v1/evolution/topics/{slug}/graph                   — papers and citation edges for the timeline graph
GET  /api/v1/evolution/topics/{slug}/timeline                — milestones by year, and notable papers without
                                                               openly available full text
GET  /api/v1/evolution/topics/{slug}/papers/{paper_id}       — one paper with what it builds on, what built on it,
                                                               and strict gap -> resolution links with evidence
GET  /api/v1/evolution/topics/{slug}/gaps                    — gap themes with yearly counts, persisting first
POST /api/v1/evolution/topics/{slug}/milestones/{paper_id}   — pin, unpin, or reset a milestone
"""
from typing import Literal
from uuid import UUID

import redis as redis_lib
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from athena.api.cache import cache_get, cache_invalidate, cache_set
from athena.api.config import settings
from athena.api.deps import get_db, get_redis
from athena.database import evolution as db
from athena.evolution.search import find_topic_by_content

router = APIRouter(prefix="/api/v1/evolution", tags=["Evolution"])


class MilestoneOverrideRequest(BaseModel):
    action: Literal["pin", "unpin", "reset"]
    note: str | None = Field(None, max_length=500)


def _topic_or_404(session: Session, slug: str):
    topic = db.get_topic(session, slug)
    if topic is None:
        raise HTTPException(status_code=404, detail=f"Topic '{slug}' is not in the system")
    return topic


def _cache_key(session: Session, topic, *parts) -> str:
    # built_at in the key: a rebuild gets fresh entries without waiting for the TTL. The labels
    # version does the same for full text and strict links, which arrive without a rebuild.
    built = topic.built_at.isoformat() if topic.built_at else "unbuilt"
    # The status too: a topic read while it builds must not stay cached as building once it is ready.
    return ":".join(["evo", topic.slug, *map(str, parts), built, topic.status or "", db.labels_version(session)])


@router.get("/topics")
def list_topics(session: Session = Depends(get_db)):
    return db.list_topics(session)


@router.get("/search")
def search_topics(q: str = Query(..., min_length=1, max_length=200), session: Session = Depends(get_db)):
    """Names and aliases first; then the topic whose papers best match the query (semantic, else full text)."""
    topic = db.find_topic(session, q)
    match = {"method": "alias"}
    if topic is None:
        topic, match = find_topic_by_content(session, q)
    if topic is None:
        available = [t["name"] for t in db.list_topics(session)]
        return {
            "found": False,
            "query": q,
            "message": f"'{q}' is not in the system yet.",
            "available": available,
            "match": match,
        }
    return {"found": True, "query": q, "topic": db.topic_summary(topic), "match": match}


@router.get("/topics/{slug}/graph")
def topic_graph(
    slug: str,
    limit: int = Query(250, ge=10, le=2000),
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


@router.get("/topics/{slug}/papers/{paper_id}")
def paper_detail(slug: str, paper_id: UUID, session: Session = Depends(get_db)):
    topic = _topic_or_404(session, slug)
    detail = db.paper_detail(session, topic, paper_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Paper is not part of this topic")
    return detail


@router.post("/topics/{slug}/milestones/{paper_id}")
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
