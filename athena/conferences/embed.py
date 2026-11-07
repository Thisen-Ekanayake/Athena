"""
Conference papers' vectors: title and abstract embedded as documents into Qdrant's ``conf_papers``, then sorted into
a topic (athena.conferences.topics) batch by batch.

This is backlog work on the GPU: it gives way to chats, takes turns with the other models' work (``turns``), stops
while an admin pauses background work, and runs in slices (``SLICE_SECONDS``) that queue the next one, so a first
build of all ~60,000 papers never holds a worker for hours. Newest papers go first.
"""
from __future__ import annotations

import os
import time
import uuid
from datetime import datetime, timezone
from typing import Iterator

import numpy as np
from loguru import logger
from sqlalchemy import or_, select, update

from athena.conferences import topics as T
from athena.core import llm
from athena.core.models import ConfPaper
from athena.database.db import SessionLocal
from athena.model_server import lane

COLLECTION = "conf_papers"
BATCH = 32
FEATURE = "conf_embed"
_qdrant = None


def qdrant():
    global _qdrant
    if _qdrant is None:
        from qdrant_client import QdrantClient
        _qdrant = QdrantClient(url=os.getenv("QDRANT_URL", "http://localhost:6333"))
    return _qdrant


def ensure_collection() -> None:
    from qdrant_client.http import models as qm
    client = qdrant()
    if not client.collection_exists(COLLECTION):
        client.create_collection(
            COLLECTION, vectors_config=qm.VectorParams(size=llm.EMBED_DIM, distance=qm.Distance.COSINE))


def point_id(paper_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"anthology:{paper_id}"))


def paper_text(p: ConfPaper) -> str:
    return f"{p.title}\n\n{p.abstract}" if p.abstract else p.title


def pending_count(session, model: str | None = None) -> int:
    from sqlalchemy import func
    model = model or llm.embed_model()
    return session.execute(select(func.count()).select_from(ConfPaper).where(
        or_(ConfPaper.embedded_at.is_(None), ConfPaper.embed_model != model))).scalar() or 0


def run(deadline: float | None = None, limit: int | None = None) -> dict:
    """Embed and sort papers without a vector from the current model, newest first, until none are left, ``limit``
    papers are done or the ``deadline`` (time.monotonic()) passes. ``more`` says whether any are left."""
    from qdrant_client.http import models as qm
    model = llm.embed_model()
    ensure_collection()
    done = 0
    with SessionLocal() as session:
        T.ensure_seeded(session)
        topic_ids, topic_vectors = T.topic_matrix(session, model)
        while True:
            if (deadline is not None and time.monotonic() > deadline) or (limit is not None and done >= limit):
                return {"embedded": done, "more": pending_count(session, model) > 0}
            papers = list(session.execute(
                select(ConfPaper).where(or_(ConfPaper.embedded_at.is_(None), ConfPaper.embed_model != model))
                .order_by(ConfPaper.year.desc(), ConfPaper.id).limit(BATCH)).scalars())
            if not papers:
                return {"embedded": done, "more": False}
            lane.yield_to_chat(who=FEATURE, model=model)  # chats first, then the GPU's turns; Paused when held
            vectors = llm.embed([paper_text(p) for p in papers], feature=FEATURE)
            qdrant().upsert(COLLECTION, points=[
                qm.PointStruct(id=point_id(p.id), vector=v.tolist(), payload={"paper_id": p.id, "year": p.year})
                for p, v in zip(papers, vectors)])
            now = datetime.now(timezone.utc)
            sorted_ = T.nearest(vectors, topic_ids, topic_vectors) if topic_vectors is not None \
                else [(None, None)] * len(papers)
            session.execute(update(ConfPaper), [
                {"id": p.id, "embedded_at": now, "embed_model": model, "topic_id": tid, "topic_score": score}
                for p, (tid, score) in zip(papers, sorted_)])
            session.commit()
            done += len(papers)
            if done % (BATCH * 20) == 0:
                logger.info(f"Conference papers embedded this run: {done}")


def scroll_vectors(page: int = 1000) -> Iterator[tuple[list[str], np.ndarray]]:
    """Every stored paper vector, a page at a time: (paper ids, unit vectors)."""
    client = qdrant()
    if not client.collection_exists(COLLECTION):
        return
    offset = None
    while True:
        points, offset = client.scroll(COLLECTION, limit=page, offset=offset, with_vectors=True, with_payload=True)
        if points:
            yield ([p.payload["paper_id"] for p in points],
                   np.asarray([p.vector for p in points], dtype=np.float32))
        if offset is None:
            return


def remove(paper_ids: list[str]) -> None:
    """Drop the vectors of papers the Anthology no longer lists."""
    if not paper_ids:
        return
    from qdrant_client.http import models as qm
    client = qdrant()
    if client.collection_exists(COLLECTION):
        client.delete(COLLECTION, points_selector=qm.PointIdsList(points=[point_id(p) for p in paper_ids]))


def similar(paper_id: str, limit: int = 8) -> list[str]:
    """The ids of the conference papers nearest one paper."""
    client = qdrant()
    if not client.collection_exists(COLLECTION):
        return []
    hits = client.query_points(COLLECTION, query=point_id(paper_id), limit=limit + 1, with_payload=True).points
    return [h.payload["paper_id"] for h in hits if h.payload.get("paper_id") != paper_id][:limit]
