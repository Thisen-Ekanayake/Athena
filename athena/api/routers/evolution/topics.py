"""
Topics: listing and matching them, proposals, building, rebuilding and deleting search-built ones, the
changelog, refreshes and their settings (athena.api.routers.evolution lists every route).
"""
import re
import time

import httpx
import redis as redis_lib
from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from athena.api import auth
from athena.api.cache import cache_invalidate
from athena.api.deps import get_db, get_redis
from athena.core.models import User
from athena.database import evolution as db
from athena.database import watches as watch_db
from athena.evolution import propose as proposals
from athena.evolution.classify import chat_available
from athena.core.openalex import FIELD_IDS, OpenAlexBudgetError
from athena.evolution.search import find_topic_by_content
from athena.api.routers.evolution._common import _built_topic_or_409, _topic_or_404

router = APIRouter()


MAX_ACTIVE_SEARCH_BUILDS = 3  # search-built topics queued or building at once
_OPENALEX_ID = re.compile(r"^W\d{1,12}$")


class TopicSettingsRequest(BaseModel):
    refresh_days: int | None = Field(None, ge=0, le=365)


class ProposalRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=200)


class AnchorIn(BaseModel):
    openalex_id: str
    alt_ids: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("openalex_id")
    @classmethod
    def _work_id(cls, v: str) -> str:
        if not _OPENALEX_ID.match(v):
            raise ValueError("not an OpenAlex work ID (W123)")
        return v

    @field_validator("alt_ids")
    @classmethod
    def _work_ids(cls, v: list[str]) -> list[str]:
        if not all(_OPENALEX_ID.match(i) for i in v):
            raise ValueError("not OpenAlex work IDs (W123)")
        return v


class TopicCreateRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=200)
    name: str = Field(..., min_length=2, max_length=80)
    description: str = Field("", max_length=500)
    aliases: list[str] = Field(default_factory=list, max_length=20)
    keywords: list[str] = Field(..., min_length=1, max_length=25)
    anchors: list[AnchorIn] = Field(..., min_length=1, max_length=8)
    fields: list[str] = Field(default_factory=list, max_length=5)
    proposal_id: str | None = None

    @field_validator("fields")
    @classmethod
    def _known_fields(cls, v: list[str]) -> list[str]:
        unknown = [f for f in v if f not in FIELD_IDS]
        if unknown:
            raise ValueError(f"unknown OpenAlex fields: {unknown}")
        return v


def _enqueue(task: str, args: list, **options) -> None:
    """Send a task to the evolution worker by name, so the API never imports the worker's code."""
    from athena.pipeline.celery_app import celery_app
    celery_app.send_task(task, args=args, queue="evolution", **options)


def _clean(values: list[str], limit: int, max_len: int) -> list[str]:
    out = (" ".join(str(v).split())[:max_len] for v in values)
    return list(dict.fromkeys(v for v in out if v))[:limit]


def _search_topic_or_409(session: Session, slug: str):
    topic = _topic_or_404(session, slug)
    if topic.origin != "search":
        raise HTTPException(status_code=409, detail="Curated topics are rebuilt with scripts/build_evolution_topic.py")
    return topic


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


@router.post("/proposals")
def create_proposal(body: ProposalRequest, r: redis_lib.Redis = Depends(get_redis),
                    _user: User = Depends(auth.spend("map_proposal"))):
    """Anchors, keywords and fields for a query, from three OpenAlex searches; the 9B refines it if it can."""
    try:
        proposal = proposals.propose(body.query)
    except OpenAlexBudgetError as exc:
        raise HTTPException(status_code=429, detail=str(exc))
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"OpenAlex did not answer: {exc}")
    if proposal["candidates"] and chat_available():
        proposal["refine"] = {"status": "pending", "deadline": time.time() + proposals.REFINE_WAIT_SECONDS}
        proposals.save(r, proposal)
        try:
            # Expires unstarted if a GPU lane holds the evolution queue; the rules' proposal then stands.
            _enqueue("athena.evolution.tasks.refine_proposal", [proposal["id"]],
                     expires=proposals.REFINE_WAIT_SECONDS)
        except Exception as exc:  # no broker: the rules' proposal is still useful
            logger.warning(f"Could not queue the proposal refinement: {exc}")
            proposal["refine"] = {"status": "unavailable"}
    proposals.save(r, proposal)
    return proposals.public(proposal)


@router.get("/proposals/{proposal_id}")
def get_proposal(proposal_id: str, r: redis_lib.Redis = Depends(get_redis)):
    proposal = proposals.load(r, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="This proposal has expired; search again")
    return proposals.public(proposal)


@router.post("/topics", status_code=201)
def create_topic(body: TopicCreateRequest, session: Session = Depends(get_db),
                 r: redis_lib.Redis = Depends(get_redis), user: User = Depends(auth.active_user)):
    """Store a checked proposal as a search-built topic and queue its build. Every user sees the map."""
    if db.active_search_builds(session) >= MAX_ACTIVE_SEARCH_BUILDS:
        raise HTTPException(status_code=429, detail="A few maps are already being built; try again when one is done")
    query = proposals.clean_query(body.query)
    base = proposals.slugify(body.name)
    slug, n = base, 2
    while db.slug_taken(session, slug):
        slug, n = f"{base}-{n}", n + 1
    keywords = _clean([k.lower() for k in body.keywords], 25, 60)
    if not keywords:
        raise HTTPException(status_code=422, detail="Give at least one keyword")
    auth.use(r, user, "map_build")
    aliases = _clean([*proposals.variants(query), *body.aliases], 20, 80)
    seeds = [{"openalex_id": a.openalex_id, "alt_ids": [i for i in a.alt_ids if i != a.openalex_id]}
             for a in body.anchors]
    config = {"keywords": keywords, "fields": body.fields, "openalex_search_max": 1000, "s2_keyless": False}
    db.upsert_topic(slug, " ".join(body.name.split()), aliases, body.description.strip() or None, seeds, config,
                    origin="search", query=query, created_by=user.id)
    db.set_topic_status(slug, "pending", "Waiting for the evolution worker")
    if body.proposal_id:
        proposal = proposals.load(r, body.proposal_id)
        if proposal and (proposal.get("refine") or {}).get("status") == "pending":
            proposal["refine"] = {"status": "cancelled"}  # built already: the 9B need not start
            proposals.save(r, proposal)
    try:
        _enqueue("athena.evolution.tasks.build_search_topic", [slug])
    except Exception as exc:
        db.set_topic_status(slug, "failed", f"Could not queue the build: {exc}"[:500])
        raise HTTPException(status_code=503, detail="The task queue is not reachable; is Redis running?")
    topic = db.get_topic(session, slug)  # not loaded in this session before, so read fresh
    watch_db.follow_map(session, user.id, topic.id, commit=True)  # its builder hears about its later updates
    return db.topic_summary(topic)


@router.get("/topics/{slug}")
def topic_status(slug: str, session: Session = Depends(get_db)):
    """One topic's summary, never cached: the UI polls it while a map builds."""
    return db.topic_summary(_topic_or_404(session, slug))


@router.post("/topics/{slug}/rebuild", dependencies=[Depends(auth.require_admin)])
def rebuild_topic(slug: str, session: Session = Depends(get_db), r: redis_lib.Redis = Depends(get_redis)):
    topic = _search_topic_or_409(session, slug)
    if topic.status in ("pending", "building", "refining"):
        raise HTTPException(status_code=409, detail="This map is already being built")
    waiting = {"status": "pending", "status_detail": "Waiting for the evolution worker"}
    db.set_topic_status(slug, **waiting)
    try:
        _enqueue("athena.evolution.tasks.build_search_topic", [slug])
    except Exception:
        db.set_topic_status(slug, topic.status, topic.status_detail)
        raise HTTPException(status_code=503, detail="The task queue is not reachable; is Redis running?")
    cache_invalidate(r, f"evo:{slug}:*")
    # ``topic`` was loaded before the status changed (in another session), so the summary is patched.
    return db.topic_summary(topic) | waiting


@router.delete("/topics/{slug}", status_code=204, dependencies=[Depends(auth.require_admin)])
def delete_topic(slug: str, session: Session = Depends(get_db), r: redis_lib.Redis = Depends(get_redis)):
    topic = _search_topic_or_409(session, slug)
    db.delete_topic(session, topic)
    cache_invalidate(r, f"evo:{slug}:*")


@router.get("/topics/{slug}/changes")
def topic_changes(slug: str, session: Session = Depends(get_db)):
    return db.topic_changes(session, _topic_or_404(session, slug))


def _queue_or_503(slug: str, **kwargs) -> str:
    from athena.evolution.refresh import queue_refresh
    try:
        return queue_refresh(slug, **kwargs)
    except Exception as exc:
        logger.warning(f"Could not queue the refresh of {slug}: {exc}")
        raise HTTPException(status_code=503, detail="The task queue is not reachable; is Redis running?")


@router.post("/topics/{slug}/refresh", status_code=202, dependencies=[Depends(auth.require_admin)])
def refresh_topic(slug: str, session: Session = Depends(get_db), r: redis_lib.Redis = Depends(get_redis)):
    """Everything a scheduled refresh does, now. The map stays readable while it runs."""
    topic = _built_topic_or_409(session, slug)
    if topic.status in ("pending", "building", "refining"):
        raise HTTPException(status_code=409, detail="This map is already being built")
    before = (topic.status, topic.status_detail)
    db.set_topic_status(slug, "refining", "Refresh queued")
    try:
        task_id = _queue_or_503(slug)
    except HTTPException:
        db.set_topic_status(slug, *before)
        raise
    cache_invalidate(r, f"evo:{slug}:*")
    return {"queued": True, "task_id": task_id}


@router.post("/topics/{slug}/full-text", status_code=202, dependencies=[Depends(auth.require_admin)])
def read_full_text(slug: str, session: Session = Depends(get_db)):
    """Tier 2 full text, then the GPU lane (labels, embeddings, gap themes), then a snapshot. No rebuild."""
    _built_topic_or_409(session, slug)
    return {"queued": True, "task_id": _queue_or_503(slug, rebuild=False, reason="full_text")}


@router.patch("/topics/{slug}/settings", dependencies=[Depends(auth.require_admin)])
def topic_settings(slug: str, body: TopicSettingsRequest, session: Session = Depends(get_db)):
    """How often the map is refreshed."""
    from athena.evolution.config import TopicConfig
    topic = _topic_or_404(session, slug)
    config = dict(topic.config or {})
    if body.refresh_days is not None:
        config["refresh_days"] = body.refresh_days
    topic.config = config
    session.commit()
    current = TopicConfig.from_dict(config)
    return {"slug": slug, "refresh_days": current.refresh_days}
