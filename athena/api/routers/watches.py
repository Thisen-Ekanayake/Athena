"""
Follows (watches)

GET    /api/v1/watches         — what the user follows, with what each caught in the last 7 days
POST   /api/v1/watches         — follow a map, a search, a source or a cluster (following it again is a no-op)
PATCH  /api/v1/watches/{id}    — deliver its news as it happens or only in the digest
DELETE /api/v1/watches/{id}    — stop following
"""
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from loguru import logger
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from athena.api import auth
from athena.api.deps import get_db
from athena.core.models import Cluster, EvoTopic, Source, User
from athena.database import watches as db

router = APIRouter(prefix="/api/v1/watches", tags=["Inbox"])

Delivery = Literal["instant", "digest"]


class FollowRequest(BaseModel):
    kind: Literal["map", "search", "source", "cluster"]
    topic_id: UUID | None = None
    source_id: UUID | None = None
    cluster_id: UUID | None = None
    query: str | None = Field(None, min_length=3, max_length=300)
    delivery: Delivery = "instant"

    @model_validator(mode="after")
    def has_its_target(self):
        field = {"map": "topic_id", "source": "source_id", "cluster": "cluster_id", "search": "query"}[self.kind]
        if getattr(self, field) is None or (self.kind == "search" and not self.query.strip()):
            raise ValueError(f"Following a {self.kind} needs {field}")
        return self


class DeliveryRequest(BaseModel):
    delivery: Delivery


def _one(session: Session, watch) -> dict:
    return db.as_dict(watch, db.describe([watch], session)[watch.id])


@router.get("")
def list_watches(session: Session = Depends(get_db), user: User = Depends(auth.active_user)):
    return {"watches": db.list_for(session, user), "limit": db.MAX_WATCHES}


@router.post("")
def follow(body: FollowRequest, response: Response, session: Session = Depends(get_db),
           user: User = Depends(auth.active_user)):
    targets = {"map": (EvoTopic, body.topic_id), "source": (Source, body.source_id),
               "cluster": (Cluster, body.cluster_id)}
    if body.kind in targets:
        model, ref = targets[body.kind]
        if session.get(model, ref) is None:
            raise HTTPException(status_code=404, detail=f"No such {body.kind}")
    vector = embed_model = None
    if body.kind == "search":
        if db.find(session, user, db.target_for("search", body.query)) is None:  # only a new one needs embedding
            from athena.core import llm
            from athena.search.local import embed_query
            try:
                vector, embed_model = embed_query(db.clean_query(body.query)), llm.embed_model()
            except Exception as exc:
                logger.warning(f"Could not embed a followed search: {exc}")
                raise HTTPException(status_code=503, detail="The embedding model is not reachable; try again soon")
    try:
        watch, created = db.follow(session, user, body.kind, topic_id=body.topic_id, source_id=body.source_id,
                                   cluster_id=body.cluster_id, query=body.query, vector=vector,
                                   embed_model=embed_model, delivery=body.delivery)
    except db.WatchLimit:
        raise HTTPException(status_code=409, detail=f"You can follow up to {db.MAX_WATCHES} things; drop one first")
    response.status_code = 201 if created else 200
    return _one(session, watch)


@router.patch("/{watch_id}")
def set_delivery(watch_id: UUID, body: DeliveryRequest, session: Session = Depends(get_db),
                 user: User = Depends(auth.active_user)):
    watch = db.set_delivery(session, user, watch_id, body.delivery)
    if watch is None:
        raise HTTPException(status_code=404, detail="Watch not found")
    return _one(session, watch)


@router.delete("/{watch_id}", status_code=204)
def unfollow(watch_id: UUID, session: Session = Depends(get_db), user: User = Depends(auth.active_user)):
    if not db.unfollow(session, user, watch_id):
        raise HTTPException(status_code=404, detail="Watch not found")
