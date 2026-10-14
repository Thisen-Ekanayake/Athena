"""
Athena Layer 5 — Research Evolution Router

GET  /api/v1/evolution/topics                                — topics (curated and search-built) and their status
GET  /api/v1/evolution/search?q=                             — match a query to a topic by alias or by its
                                                               papers' content, or say it is not covered
POST /api/v1/evolution/proposals                             — propose a topic for a query (anchors, keywords,
                                                               fields); the 9B refines it if the GPU is free
GET  /api/v1/evolution/proposals/{id}                        — a proposal, polled while the 9B works
POST /api/v1/evolution/topics                                — build a topic from a checked proposal
GET  /api/v1/evolution/topics/{slug}                         — one topic's status, uncached, for build progress
POST /api/v1/evolution/topics/{slug}/rebuild                 — rebuild a search-built topic
DELETE /api/v1/evolution/topics/{slug}                       — delete a search-built topic
GET  /api/v1/evolution/topics/{slug}/graph                   — papers and citation edges for the timeline graph
GET  /api/v1/evolution/topics/{slug}/timeline                — milestones by year, and notable papers without
                                                               openly available full text
GET  /api/v1/evolution/topics/{slug}/papers/{paper_id}       — one paper with what it builds on, what built on it,
                                                               and strict gap -> resolution links with evidence
GET  /api/v1/evolution/topics/{slug}/gaps                    — gap themes with yearly counts, persisting first
POST /api/v1/evolution/topics/{slug}/milestones/{paper_id}   — pin, unpin, or reset a milestone
GET  /api/v1/evolution/topics/{slug}/reading-path?n=10       — a survey, then milestones in order, each with a
                                                               model-written line on why it matters
PUT|DELETE /api/v1/evolution/papers/{paper_id}/read          — tick or untick a paper as read (per user)
GET  /api/v1/evolution/topics/{slug}/export?what=&format=    — milestones or the reading path as BibTeX, RIS or
                                                               Markdown; gap themes as CSV
GET  /api/v1/evolution/topics/{slug}/people                  — key authors and labs per era, and who introduced
                                                               each milestone
GET  /api/v1/evolution/items/{item_id}                       — a feed item's place in the maps, and the
                                                               milestones it cites
GET  /api/v1/evolution/new-papers?days=30&topic=             — recent feed papers that cite map milestones
POST /api/v1/evolution/idea-checks                           — check an idea against every map: closest papers,
                                                               gap themes it touches, a short verdict
GET|DELETE /api/v1/evolution/idea-checks[/{id}]              — the user's saved checks
POST /api/v1/evolution/topics/{slug}/ask                     — a question answered from the map's papers, streamed,
                                                               citing paper and section
GET|DELETE /api/v1/evolution/topics/{slug}/questions         — the user's questions to a map
DELETE /api/v1/evolution/questions/{id}                      — one of them
GET  /api/v1/evolution/topics/{slug}/links                   — papers shared with other maps, and milestones
                                                               borrowed and lent
GET  /api/v1/evolution/topics/{slug}/changes                 — snapshots and what changed between them
POST /api/v1/evolution/topics/{slug}/refresh                 — rebuild, read new full text, GPU lane, snapshot (admin)
POST /api/v1/evolution/topics/{slug}/full-text               — read full text and run the GPU lane only (admin)
PATCH /api/v1/evolution/topics/{slug}/settings               — how often the map is refreshed (admin)
"""
import json
import re
import time
from typing import Literal
from uuid import UUID

import httpx
import redis as redis_lib
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from loguru import logger
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from athena.api import auth
from athena.api.cache import cache_get, cache_invalidate, cache_set
from athena.api.config import settings
from athena.api.deps import get_db, get_redis
from athena.core.models import User
from athena.database import evolution as db
from athena.database import watches as watch_db
from athena.core import llm
from athena.evolution import ask, export, ideas, notes
from athena.evolution import propose as proposals
from athena.evolution.classify import chat_available
from athena.evolution.openalex import FIELD_IDS, OpenAlexBudgetError
from athena.evolution.search import find_topic_by_content

router = APIRouter(prefix="/api/v1/evolution", tags=["Evolution"])

MAX_ACTIVE_SEARCH_BUILDS = 3  # search-built topics queued or building at once
_OPENALEX_ID = re.compile(r"^W\d{1,12}$")


class MilestoneOverrideRequest(BaseModel):
    action: Literal["pin", "unpin", "reset"]
    note: str | None = Field(None, max_length=500)


class IdeaCheckRequest(BaseModel):
    idea: str = Field(..., min_length=20, max_length=4000)
    verdict: bool = True


class AskTurn(BaseModel):
    question: str = Field(..., max_length=1000)
    answer: str = Field(..., max_length=6000)


class AskRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=1000)
    sections: list[Literal["method", "results", "limitations"]] = Field(default_factory=list, max_length=3)
    history: list[AskTurn] = Field(default_factory=list, max_length=6)


class TopicSettingsRequest(BaseModel):
    refresh_days: int | None = Field(None, ge=0, le=365)
    # The named-method milestone feature (E9) for this map; applies at the next build.
    named_method: bool | None = None


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


def _topic_or_404(session: Session, slug: str):
    topic = db.get_topic(session, slug)
    if topic is None:
        raise HTTPException(status_code=404, detail=f"Topic '{slug}' is not in the system")
    return topic


def _built_topic_or_409(session: Session, slug: str):
    topic = _topic_or_404(session, slug)
    if topic.built_at is None:
        raise HTTPException(status_code=409, detail="This map has not been built yet")
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


@router.get("/topics/{slug}/people")
def topic_people(slug: str, session: Session = Depends(get_db), r: redis_lib.Redis = Depends(get_redis)):
    topic = _built_topic_or_409(session, slug)
    key = _cache_key(session, topic, "people")
    cached = cache_get(r, key)
    if cached:
        return cached
    payload = db.topic_people(session, topic)
    cache_set(r, key, payload, settings.CACHE_CLUSTERS_TTL)
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


# ── reading path (E1) ──────────────────────────────────────────────────


@router.get("/topics/{slug}/reading-path")
def reading_path(
    slug: str,
    background: BackgroundTasks,
    n: int = Query(10, ge=3, le=30),
    session: Session = Depends(get_db),
    r: redis_lib.Redis = Depends(get_redis),
    user: User = Depends(auth.active_user),
):
    """``n`` papers to learn the field from. Missing notes are written after the response; poll until
    ``notes_pending`` is false."""
    topic = _built_topic_or_409(session, slug)
    path = db.reading_path(session, topic, user.id, n)
    entries = ([path["survey"]] if path["survey"] else []) + path["steps"]
    pending, error = False, None
    if any(e["why"] is None for e in entries):  # "" is a note the model could not write; not retried
        error = notes.last_failure(r, slug)
        if error is None:
            if notes.claim(r, slug):
                background.add_task(notes.write_notes, slug, [UUID(e["id"]) for e in entries], r)
            pending = True
    return path | {"notes_pending": pending, "notes_error": error}


@router.put("/papers/{paper_id}/read", status_code=204)
def mark_read(paper_id: UUID, session: Session = Depends(get_db), user: User = Depends(auth.active_user)):
    if not db.set_read(session, user.id, paper_id, True):
        raise HTTPException(status_code=404, detail="Unknown paper")


@router.delete("/papers/{paper_id}/read", status_code=204)
def mark_unread(paper_id: UUID, session: Session = Depends(get_db), user: User = Depends(auth.active_user)):
    if not db.set_read(session, user.id, paper_id, False):
        raise HTTPException(status_code=404, detail="Unknown paper")


# ── exports (E6) ───────────────────────────────────────────────────────

EXPORT_FORMATS = {"milestones": {"bib", "ris", "md"}, "reading-path": {"bib", "ris", "md"}, "gaps": {"csv"}}
MEDIA_TYPES = {"bib": "application/x-bibtex", "ris": "application/x-research-info-systems",
               "md": "text/markdown", "csv": "text/csv"}


@router.get("/topics/{slug}/export")
def export_topic(
    slug: str,
    what: Literal["milestones", "reading-path", "gaps"],
    format: Literal["bib", "ris", "md", "csv"],
    n: int = Query(10, ge=3, le=30),
    session: Session = Depends(get_db),
    user: User = Depends(auth.active_user),
):
    if format not in EXPORT_FORMATS[what]:
        raise HTTPException(status_code=422, detail=f"{what} exports as {', '.join(sorted(EXPORT_FORMATS[what]))}")
    topic = _built_topic_or_409(session, slug)
    built = topic.built_at.date().isoformat() if hasattr(topic.built_at, "date") else None
    if what == "gaps":
        body = export.gaps_csv(db.gap_export_rows(session, topic))
    elif what == "milestones":
        papers = db.export_papers(session, db.milestone_ids(session, topic))
        body = export.markdown_milestones(topic.name, papers, built) if format == "md" else (
            export.bibtex(papers) if format == "bib" else export.ris(papers))
    else:
        path = db.reading_path(session, topic, user.id, n)
        entries = ([path["survey"]] if path["survey"] else []) + path["steps"]
        papers = db.export_papers(session, [UUID(e["id"]) for e in entries])
        extra = {e["id"]: {"why": e["why"], "named_method": e["named_method"]} for e in entries}
        papers = [p | extra.get(p["id"], {}) for p in papers]
        if format == "md":
            survey = papers[0] if path["survey"] else None
            body = export.markdown_path(topic.name, survey, papers[1:] if survey else papers, built)
        else:
            body = export.bibtex(papers) if format == "bib" else export.ris(papers)
    filename = f"{slug}-{what}.{format}"
    return Response(body, media_type=f"{MEDIA_TYPES[format]}; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


# ── the feed and the maps (E5) ─────────────────────────────────────────


@router.get("/items/{item_id}")
def feed_item_place(item_id: UUID, session: Session = Depends(get_db)):
    place = db.feed_place(session, item_id)
    if place is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return place


@router.get("/new-papers")
def new_papers(days: int = Query(30, ge=1, le=120), topic: str | None = Query(None, max_length=200),
               session: Session = Depends(get_db)):
    """Feed papers from the last ``days`` days that cite milestones, those citing the most first."""
    return db.new_feed_papers(session, days, topic)


# ── idea checks (E2) ───────────────────────────────────────────────────


@router.post("/idea-checks", status_code=201)
def create_idea_check(body: IdeaCheckRequest, session: Session = Depends(get_db),
                      user: User = Depends(auth.spend("idea_check"))):
    """The idea against every built map. Takes a few seconds, longer with the verdict; saved to the account."""
    idea = body.idea.strip()
    try:
        result = ideas.check_idea(session, idea, verdict=body.verdict)
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


# ── questions to a map (E3) ────────────────────────────────────────────

ANSWER_TOKENS = 900


def _sse(payload) -> str:
    return f"data: {json.dumps(payload)}\n\n"


@router.post("/topics/{slug}/ask")
async def ask_map(slug: str, body: AskRequest, session: Session = Depends(get_db),
                  r: redis_lib.Redis = Depends(get_redis), user: User = Depends(auth.spend("map_qa"))):
    """Streams server-sent events: the numbered sources first, then the answer's tokens, then the saved
    question's id."""
    topic = _built_topic_or_409(session, slug)
    auth.check_tokens(r, user, "map_qa")
    try:
        sources = await run_in_threadpool(ask.retrieve, session, topic, body.question, body.sections)
    except ask.AskUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    chat = ask.messages(topic.name, body.question, sources, [t.model_dump() for t in body.history])
    input_tokens = sum(len(m["content"]) for m in chat) // 4  # an estimate; the served model counts its own
    model = llm.chat_model("qa")
    public = [s.public() for s in sources]
    topic_id, question, sections = topic.id, body.question, list(body.sections)

    async def generate():
        yield _sse({"sources": public, "abstract_only": sum(s.abstract_only for s in sources)})
        parts: list[str] = []
        try:
            stream = await llm.async_chat_client().chat.completions.create(
                model=model, messages=chat, max_tokens=ANSWER_TOKENS, temperature=0.2, stream=True,
                extra_body=llm.chat_extra())
            async for chunk in stream:
                delta = chunk.choices[0].delta.content if chunk.choices else None
                if delta:
                    parts.append(delta)
                    yield _sse({"token": delta})
        except Exception as exc:  # the model server went away mid-answer
            logger.warning(f"Ask {slug}: the answer failed: {exc}")
            yield _sse({"error": f"The model did not answer: {str(exc)[:200]}"})
        answer = "".join(parts)
        output_tokens = len(answer) // 4
        auth.add_tokens(r, user, "map_qa", input_tokens + output_tokens)
        if answer:
            question_id = await run_in_threadpool(db.save_map_question, user.id, topic_id, question, answer, public,
                                                  sections, input_tokens, output_tokens, model)
            yield _sse({"done": True, "question_id": str(question_id)})
        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.get("/topics/{slug}/questions")
def map_questions(slug: str, session: Session = Depends(get_db), user: User = Depends(auth.active_user)):
    return db.map_questions(session, user.id, _topic_or_404(session, slug).id)


@router.delete("/topics/{slug}/questions", status_code=204)
def clear_map_questions(slug: str, session: Session = Depends(get_db), user: User = Depends(auth.active_user)):
    db.delete_map_question(session, user.id, topic_id=_topic_or_404(session, slug).id)


@router.delete("/questions/{question_id}", status_code=204)
def delete_map_question(question_id: UUID, session: Session = Depends(get_db),
                        user: User = Depends(auth.active_user)):
    if not db.delete_map_question(session, user.id, question_id=question_id):
        raise HTTPException(status_code=404, detail="Question not found")


# ── refresh and changelog (E4) ─────────────────────────────────────────


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
    """How often the map is refreshed, and whether its milestone scores use cited method names."""
    from athena.evolution.config import NAMED_METHOD_ON, TopicConfig
    topic = _topic_or_404(session, slug)
    config = dict(topic.config or {})
    if body.refresh_days is not None:
        config["refresh_days"] = body.refresh_days
    if body.named_method is not None:
        weights = {k: v for k, v in (config.get("weights") or {}).items() if k != "named_method"}
        if body.named_method:
            weights["named_method"] = NAMED_METHOD_ON
        config["weights"] = weights
    topic.config = config
    session.commit()
    current = TopicConfig.from_dict(config)
    return {"slug": slug, "refresh_days": current.refresh_days, "named_method": current.weights.named_method > 0}
