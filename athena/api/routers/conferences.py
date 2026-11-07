"""
Conference proceedings (athena/conferences/): the ACL family's editions, topics over the years and top papers.
Shared by everyone; the topic list and syncing are for admins.

GET    /api/v1/conferences                              — venues with their editions, the topic list, pipeline status
GET    /api/v1/conferences/compare?venues=&year=&kinds= — venues side by side in one year
GET    /api/v1/conferences/papers/{paper_id}            — one paper, with similar papers
POST   /api/v1/conferences/papers/{paper_id}/item       — the paper as a feed item (made now if needed), to save it
GET    /api/v1/conferences/{venue}?year=&kinds=         — one edition: shares, awards, terms, summary (latest year)
GET    /api/v1/conferences/{venue}/trends?kinds=&start=&end= — papers per topic per year
GET    /api/v1/conferences/{venue}/papers?year=&topic=&kinds=&offset=&limit= — top papers (awards, then citations)
POST   /api/v1/conferences/topics                       — admin: add a topic
PATCH  /api/v1/conferences/topics/{id}                  — admin: rename, describe or move one
DELETE /api/v1/conferences/topics/{id}                  — admin
POST   /api/v1/conferences/sync                         — admin: read the Anthology again now

``venue`` is a venue's slug (acl, emnlp, …) or ``all`` for the whole family. ``kinds`` is a comma-separated choice
of main, findings and journal (all three by default).
"""
from __future__ import annotations

from datetime import datetime, timezone

import redis as redis_lib
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from athena.api import auth
from athena.api.cache import cache_get, cache_set
from athena.api.deps import get_db, get_redis
from athena.conferences import embed, items, tasks, topics as T, venues as V
from athena.core.models import ConfPaper, ConfTopic, User
from athena.database import conferences as db

router = APIRouter(prefix="/api/v1/conferences", tags=["Conferences"])

CACHE_TTL = 6 * 3600  # the version in each key changes whenever the data does


def _kinds(kinds: str | None) -> list[str]:
    picked = [k.strip() for k in (kinds or "").split(",") if k.strip()]
    bad = [k for k in picked if k not in V.KINDS]
    if bad:
        raise HTTPException(status_code=422, detail=f"Unknown kind: {', '.join(bad)} (main, findings or journal)")
    return picked or list(V.KINDS)


def _venue(venue: str) -> str:
    if venue != V.ALL and venue not in V.VENUES:
        raise HTTPException(status_code=404, detail=f"No venue {venue!r}")
    return venue


def _key(*parts) -> str:
    return "conf:" + ":".join(str(p) for p in (tasks.version(), *parts))


def _cached(r: redis_lib.Redis, key: str, make):
    hit = cache_get(r, key)
    if hit is not None:
        return hit
    value = make()
    cache_set(r, key, value, CACHE_TTL)
    return value


@router.get("")
def list_conferences(session: Session = Depends(get_db), r: redis_lib.Redis = Depends(get_redis)):
    def make():
        total = session.execute(select(func.count()).select_from(ConfPaper)).scalar() or 0
        family = db.years(session, V.ALL, list(V.KINDS))
        return {"family": {"slug": V.ALL, "name": V.FAMILY_NAME,
                           "editions": [{"year": y, "papers": family[y]} for y in sorted(family)]},
                "venues": db.venues(session),
                "topics": [db.topic_brief(t) for t in db.topics(session)],
                "progress": db.progress(session, V.ALL, None, list(V.KINDS)) if total else
                {"papers": 0, "sorted": 0, "cited": 0, "abstracts": 0}}
    return _cached(r, _key("list"), make) | {"status": tasks.status()}


@router.get("/compare")
def compare(venues: str = Query(..., description="Comma-separated venue slugs"), year: int = Query(...),
            kinds: str | None = None, session: Session = Depends(get_db), r: redis_lib.Redis = Depends(get_redis)):
    slugs = [_venue(v.strip()) for v in venues.split(",") if v.strip()][:8]
    if not slugs:
        raise HTTPException(status_code=422, detail="Name at least one venue")
    picked = _kinds(kinds)
    return _cached(r, _key("compare", ",".join(slugs), year, ",".join(picked)),
                   lambda: db.compare(session, slugs, year, picked))


@router.get("/papers/{paper_id}")
def get_paper(paper_id: str, session: Session = Depends(get_db)):
    found = db.paper(session, paper_id)
    if found is None:
        raise HTTPException(status_code=404, detail="Paper not found")
    try:
        similar = db.papers_by_id(session, embed.similar(paper_id, 6))
    except Exception:
        similar = []  # Qdrant down, or the paper not embedded yet
    return found | {"similar": similar}


@router.post("/papers/{paper_id}/item")
def paper_as_item(paper_id: str, session: Session = Depends(get_db)):
    """The paper's feed item, to save to a list or add to a project like any other paper."""
    paper = session.get(ConfPaper, paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="Paper not found")
    item, made = items.as_item(session, paper)
    return {"item_id": str(item.id), "made": made}


class TopicIn(BaseModel):
    name: str = Field(..., min_length=2, max_length=80)
    description: str = Field("", max_length=400)


class TopicPatch(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=80)
    description: str | None = Field(None, max_length=400)
    position: int | None = Field(None, ge=0, le=1000)


def _resort() -> None:
    try:
        tasks.reassign.apply_async(countdown=5)  # several edits in a row: one re-sort, after them
    except Exception:
        pass  # no broker: the next sync's embedding sorts with the new list


def _name_taken(session: Session, name: str, other_than: int | None = None) -> bool:
    q = select(ConfTopic.id).where(func.lower(ConfTopic.name) == name.strip().lower())
    if other_than is not None:
        q = q.where(ConfTopic.id != other_than)
    return session.execute(q).first() is not None


@router.post("/topics", status_code=201)
def add_topic(body: TopicIn, session: Session = Depends(get_db), _: User = Depends(auth.require_admin)):
    if _name_taken(session, body.name):
        raise HTTPException(status_code=409, detail="There is a topic with that name")
    last = session.execute(select(func.max(ConfTopic.position))).scalar()
    topic = ConfTopic(name=body.name.strip(), description=body.description.strip(),
                      position=(last + 1) if last is not None else 0)
    session.add(topic)
    session.commit()
    tasks.bump()
    _resort()
    return db.topic_brief(topic)


@router.patch("/topics/{topic_id}")
def edit_topic(topic_id: int, body: TopicPatch, session: Session = Depends(get_db),
               _: User = Depends(auth.require_admin)):
    topic = session.get(ConfTopic, topic_id)
    if topic is None:
        raise HTTPException(status_code=404, detail="Topic not found")
    if body.name is not None and _name_taken(session, body.name, topic_id):
        raise HTTPException(status_code=409, detail="There is a topic with that name")
    meaning = False
    if body.name is not None and body.name.strip() != topic.name:
        topic.name, meaning = body.name.strip(), True
    if body.description is not None and body.description.strip() != topic.description:
        topic.description, meaning = body.description.strip(), True
    if body.position is not None:
        topic.position = body.position
    if meaning:
        T.touch(topic)
    topic.updated_at = datetime.now(timezone.utc)
    session.commit()
    tasks.bump()
    if meaning:
        _resort()
    return db.topic_brief(topic)


@router.delete("/topics/{topic_id}", status_code=204)
def delete_topic(topic_id: int, session: Session = Depends(get_db), _: User = Depends(auth.require_admin)):
    topic = session.get(ConfTopic, topic_id)
    if topic is None:
        raise HTTPException(status_code=404, detail="Topic not found")
    session.delete(topic)
    session.commit()
    tasks.bump()
    _resort()


@router.post("/sync", status_code=202)
def start_sync(force: bool = False, _: User = Depends(auth.require_admin)):
    try:
        tasks.sync.delay(force, True)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"No worker to sync with: {exc}")
    tasks.set_status(stage="queued", error=None)
    return {"queued": True}


@router.get("/{venue}")
def edition(venue: str, year: int | None = None, kinds: str | None = None, session: Session = Depends(get_db),
            r: redis_lib.Redis = Depends(get_redis)):
    venue, picked = _venue(venue), _kinds(kinds)
    view = _cached(r, _key("edition", venue, year, ",".join(picked)), lambda: db.overview(session, venue, year, picked))
    if view is None:
        raise HTTPException(status_code=404, detail=f"No {V.label(venue)} papers yet")
    return view


@router.get("/{venue}/trends")
def trends(venue: str, kinds: str | None = None, start: int | None = None, end: int | None = None,
           session: Session = Depends(get_db), r: redis_lib.Redis = Depends(get_redis)):
    venue, picked = _venue(venue), _kinds(kinds)
    return _cached(r, _key("trends", venue, ",".join(picked), start, end),
                   lambda: db.trends(session, venue, picked, start, end))


@router.get("/{venue}/papers")
def top_papers(venue: str, year: int | None = None, topic: int | None = None, kinds: str | None = None,
               awards: bool = False, offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100),
               session: Session = Depends(get_db)):
    venue, picked = _venue(venue), _kinds(kinds)
    papers, total = db.ranked(session, venue, picked, year=year, topic_id=topic, awards_only=awards, offset=offset,
                              limit=limit)
    names = {t.id: t.name for t in db.topics(session)}
    return {"venue": venue, "name": V.label(venue), "year": year,
            "topic": {"id": topic, "name": names.get(topic)} if topic is not None else None,
            "papers": papers, "total": total, "offset": offset}
