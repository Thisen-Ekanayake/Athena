"""
Shared maps (ROADMAP R2): the read-only routes behind a share link, open to anyone who has the link.

Mounted without the login dependency. Every route resolves the token first (404 when sharing is off or the link is
unknown, revoked, expired or its map is not built) and then answers as the map's own route does, through the same
database functions and cache. What a share leaves out: questions to the map (they cost model time), links to other
maps, the feed, follows and read ticks, the map's builder and its build details. The reading path shows the notes
already written and never asks the model for more.

Anonymous traffic is rate-limited per address (RATE_LIMIT requests per RATE_WINDOW seconds).
"""
from __future__ import annotations

import time
from typing import Literal
from uuid import UUID

import redis as redis_lib
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from athena.api.deps import get_db, get_redis
from athena.api.routers import evolution as maps
from athena.database import evolution as db
from athena.database import shares

router = APIRouter(prefix="/api/v1/share", tags=["Shared maps"])

RATE_LIMIT = 300
RATE_WINDOW = 600
GRAPH_LIMITS = (80, 250, 600)  # the sizes the map page offers
PRIVATE_TOPIC_FIELDS = ("created_by", "build_stats", "query")
NOT_FOUND = "This link has expired, was revoked, or sharing is switched off"


def _rate_limit(request: Request, r: redis_lib.Redis) -> None:
    address = request.client.host if request.client else "unknown"
    key = f"share_rl:{address}:{int(time.time()) // RATE_WINDOW}"
    try:
        count = int(r.incr(key))
        if count == 1:
            r.expire(key, RATE_WINDOW)
    except redis_lib.RedisError:
        return  # no limit is better than no map
    if count > RATE_LIMIT:
        raise HTTPException(status_code=429, detail="Too many requests from this address; try again in a few minutes")


def shared(token: str, request: Request, session: Session = Depends(get_db),
           r: redis_lib.Redis = Depends(get_redis)):
    """The link and its map, or 404."""
    _rate_limit(request, r)
    found = shares.resolve(session, token)
    if found is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    return found


def _public(payload: dict) -> dict:
    """The payload without the map's builder and build details."""
    topic = payload.get("topic")
    if isinstance(topic, dict):
        payload = payload | {"topic": {k: v for k, v in topic.items() if k not in PRIVATE_TOPIC_FIELDS}}
    return payload


@router.get("/{token}")
def shared_topic(found=Depends(shared), session: Session = Depends(get_db)):
    """The map's summary; opening the link counts as a view."""
    share, topic = found
    shares.count_view(session, share)
    return _public({"topic": db.topic_summary(topic)})["topic"] | {
        "shared": {"expires_at": shares.as_dict(share)["expires_at"]}}


@router.get("/{token}/graph")
def shared_graph(limit: int = Query(250), found=Depends(shared), session: Session = Depends(get_db),
                 r: redis_lib.Redis = Depends(get_redis)):
    if limit not in GRAPH_LIMITS:
        raise HTTPException(status_code=422, detail=f"limit is one of {', '.join(map(str, GRAPH_LIMITS))}")
    return _public(maps.topic_graph(found[1].slug, limit, session, r))


@router.get("/{token}/timeline")
def shared_timeline(found=Depends(shared), session: Session = Depends(get_db),
                    r: redis_lib.Redis = Depends(get_redis)):
    return _public(maps.topic_timeline(found[1].slug, session, r))


@router.get("/{token}/gaps")
def shared_gaps(found=Depends(shared), session: Session = Depends(get_db), r: redis_lib.Redis = Depends(get_redis)):
    return _public(maps.topic_gaps(found[1].slug, session, r))


@router.get("/{token}/people")
def shared_people(found=Depends(shared), session: Session = Depends(get_db),
                  r: redis_lib.Redis = Depends(get_redis)):
    return _public(maps.topic_people(found[1].slug, session, r))


@router.get("/{token}/changes")
def shared_changes(found=Depends(shared), session: Session = Depends(get_db)):
    changes = db.topic_changes(session, found[1])
    return _public({"topic": changes["topic"], "snapshots": changes["snapshots"]})


@router.get("/{token}/papers/{paper_id}")
def shared_paper(paper_id: UUID, found=Depends(shared), session: Session = Depends(get_db)):
    return maps.paper_detail(found[1].slug, paper_id, session)


@router.get("/{token}/reading-path")
def shared_reading_path(n: int = Query(10, ge=3, le=30), found=Depends(shared), session: Session = Depends(get_db)):
    """The path with the notes written so far; a shared link never asks the model for the missing ones."""
    path = db.reading_path(session, found[1], None, n)
    return _public(path | {"notes_pending": False, "notes_error": None})


@router.get("/{token}/export")
def shared_export(what: Literal["milestones", "reading-path", "gaps"], format: Literal["bib", "ris", "md", "csv"],
                  n: int = Query(10, ge=3, le=30), found=Depends(shared), session: Session = Depends(get_db)):
    return maps.export_file(session, found[1], what, format, n)
