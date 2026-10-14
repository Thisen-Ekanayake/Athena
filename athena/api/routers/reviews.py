"""
Literature reviews (ROADMAP S1): written in the background, saved per user (athena.evolution.review).

POST   /api/v1/reviews                     — start one: {query} or {topic_slug}; grounded in a map when one matches
GET    /api/v1/reviews                     — yours, newest first
GET    /api/v1/reviews/{id}                — one review; polled while it is written
DELETE /api/v1/reviews/{id}
GET    /api/v1/reviews/{id}/export?format= — md (the review with its references) or bib (the papers it cites)

A review counts against the daily literature-review allowance and the monthly budget when it starts. Each user
writes one at a time.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

import redis as redis_lib
from fastapi import APIRouter, Depends, HTTPException, Response
from loguru import logger
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from athena.api import auth
from athena.api.deps import get_db, get_redis
from athena.core.models import EvoTopic, LitReview, User
from athena.evolution import export, review as reviews

router = APIRouter(prefix="/api/v1", tags=["Reviews"])

MEDIA_TYPES = {"md": "text/markdown", "bib": "application/x-bibtex"}


class ReviewRequest(BaseModel):
    query: str | None = Field(None, min_length=3, max_length=300)
    topic_slug: str | None = Field(None, max_length=200)

    @model_validator(mode="after")
    def one_of(self):
        if not self.query and not self.topic_slug:
            raise ValueError("Give a query or a map")
        return self


def _summary(r: LitReview, topic: EvoTopic | None) -> dict:
    return {"id": str(r.id), "title": r.title, "query": r.query, "mode": r.mode,
            "status": "failed" if reviews.is_stale(r) else r.status,
            "topic": {"slug": topic.slug, "name": topic.name} if topic else None,
            "progress": r.progress or {}, "cited": len(r.sources or []),
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None}


def _full(r: LitReview, topic: EvoTopic | None) -> dict:
    stale = reviews.is_stale(r)
    return _summary(r, topic) | {
        "sections": r.sections or [], "sources": r.sources or [], "markdown": r.markdown,
        "error": "The worker stopped before the review was finished; start it again." if stale else r.error,
        "model": r.model, "input_tokens": r.input_tokens, "output_tokens": r.output_tokens,
        "built_at": r.built_at.isoformat() if r.built_at else None}


def _own(session: Session, review_id: UUID, user: User) -> LitReview:
    r = session.get(LitReview, review_id)
    if r is None or r.user_id != user.id:
        raise HTTPException(status_code=404, detail="Review not found")
    return r


def _map_for(session: Session, body: ReviewRequest) -> EvoTopic | None:
    """The built map a review is grounded in: the one asked for, else the one the query matches, else none."""
    from athena.database import evolution as db
    from athena.evolution.search import find_topic_by_content
    if body.topic_slug:
        topic = db.get_topic(session, body.topic_slug)
        if topic is None:
            raise HTTPException(status_code=404, detail="Map not found")
        if topic.built_at is None:
            raise HTTPException(status_code=409, detail="This map is not built yet")
        return topic
    topic = db.find_topic(session, body.query)
    if topic is None:
        try:
            topic, _ = find_topic_by_content(session, body.query)
        except Exception as exc:  # no embedding model: an abstracts review still works
            logger.warning(f"Review: map matching failed: {exc}")
            topic = None
    return topic if topic is not None and topic.built_at is not None else None


@router.post("/reviews", status_code=202)
def start_review(body: ReviewRequest, session: Session = Depends(get_db), r: redis_lib.Redis = Depends(get_redis),
                 user: User = Depends(auth.active_user)):
    topic = _map_for(session, body)
    if reviews.active(session, user.id) is not None:
        raise HTTPException(status_code=409, detail="A review of yours is still being written; wait for it to finish")
    auth.use(r, user, "lit_review")
    review = LitReview(user_id=user.id, topic_id=topic.id if topic else None, query=body.query,
                       title=f"{topic.name if topic else body.query}: a literature review",
                       mode="map" if topic else "abstracts", status="queued",
                       progress={"step": 0, "of": 1, "label": "Waiting for the worker",
                                 "at": datetime.now(timezone.utc).isoformat()})
    session.add(review)
    session.commit()
    try:
        _queue(str(review.id))
    except Exception as exc:  # no broker: say so now rather than after the stale timeout
        review.status, review.error = "failed", f"The background worker could not be reached: {str(exc)[:200]}"
        session.commit()
    return _summary(review, topic)


def _queue(review_id: str) -> None:
    from athena.evolution.tasks import write_review
    write_review.delay(review_id)


@router.get("/reviews")
def list_reviews(session: Session = Depends(get_db), user: User = Depends(auth.active_user)):
    rows = session.execute(select(LitReview, EvoTopic).outerjoin(EvoTopic, EvoTopic.id == LitReview.topic_id)
                           .where(LitReview.user_id == user.id).order_by(LitReview.created_at.desc())).all()
    return {"reviews": [_summary(r, t) for r, t in rows]}


@router.get("/reviews/{review_id}")
def get_review(review_id: UUID, session: Session = Depends(get_db), user: User = Depends(auth.active_user)):
    r = _own(session, review_id, user)
    return _full(r, session.get(EvoTopic, r.topic_id) if r.topic_id else None)


@router.delete("/reviews/{review_id}", status_code=204)
def delete_review(review_id: UUID, session: Session = Depends(get_db), user: User = Depends(auth.active_user)):
    session.delete(_own(session, review_id, user))
    session.commit()
    return Response(status_code=204)


@router.get("/reviews/{review_id}/export")
def export_review(review_id: UUID, format: Literal["md", "bib"], session: Session = Depends(get_db),
                  user: User = Depends(auth.active_user)):
    r = _own(session, review_id, user)
    if r.status != "done":
        raise HTTPException(status_code=409, detail="The review is not finished")
    body = (r.markdown or "") if format == "md" else (export.bibtex(r.sources) if r.sources else "")
    name = "".join(ch if ch.isalnum() else "-" for ch in (r.title or "review").lower()).strip("-")[:80] or "review"
    return Response(body, media_type=f"{MEDIA_TYPES[format]}; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}.{format}"'})
