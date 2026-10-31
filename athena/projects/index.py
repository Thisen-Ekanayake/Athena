"""
A project's passages in Qdrant (collection ``project_chunks``), and finding the ones that answer a question.

Everything in a project is cut into passages of about CHUNK_CHARS and embedded: a feed paper's title, abstract,
summary and takeaways (and its full text when it can be fetched), a map paper's abstract and parsed sections, a
map's overview (milestones by year and open problems), a literature review, an idea check, a saved list's papers,
an outside paper's abstract, an uploaded file's text or an image's caption, and an artifact. Each point carries
``project_id``, ``user_id`` and ``source`` (``item:<project item id>``, ``file:<id>``, ``artifact:<id>``), so a
source is re-indexed by deleting its points first. The collection is derived from PostgreSQL and can be dropped.
"""
from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from uuid import UUID

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

COLLECTION = "project_chunks"
CHUNK_CHARS = 1500
OVERLAP_CHARS = 200
MAX_CHUNKS = 400          # per source: a 300-page book is still searchable, without hours of embedding
EMBED_BATCH = 16
INSTRUCT = "Given a question, retrieve passages from the user's research project that answer it"
HITS = 8
PER_SOURCE = 3
MIN_SCORE = 0.3
CAPTION_PROMPT = ("Describe this image for someone who cannot see it, so it can be found by search later: what it "
                  "shows, any text in it word for word, and for a chart or figure its axes, labels and main finding. "
                  "Plain prose, at most 150 words.")
_NAMESPACE = uuid.UUID("5b0c2f4e-8f43-4a8e-9d0e-6d2f4c1a7b31")


@dataclass
class Passage:
    n: int
    kind: str                 # paper | map | review | idea_check | list | file | artifact
    source: str               # item:<id> | file:<id> | artifact:<id>
    title: str
    text: str
    score: float
    link: str | None = None

    def public(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k != "text"} | {"excerpt": self.text[:400]}


# ── Qdrant ───────────────────────────────────────────────────────────


def client():
    from athena.evolution import vectors
    return vectors.client()


def ensure_collection(qdrant=None) -> None:
    from qdrant_client.http import models as qm

    from athena.core.llm import EMBED_DIM
    qdrant = qdrant or client()
    if qdrant.collection_exists(COLLECTION):
        return
    qdrant.create_collection(COLLECTION, vectors_config=qm.VectorParams(size=EMBED_DIM, distance=qm.Distance.COSINE))
    for field in ("project_id", "user_id", "source"):
        qdrant.create_payload_index(COLLECTION, field, field_schema=qm.PayloadSchemaType.KEYWORD)


def delete_source(source: str, qdrant=None) -> None:
    from qdrant_client.http import models as qm
    qdrant = qdrant or client()
    if qdrant.collection_exists(COLLECTION):
        qdrant.delete(COLLECTION, points_selector=qm.FilterSelector(filter=qm.Filter(must=[
            qm.FieldCondition(key="source", match=qm.MatchValue(value=source))])))


def delete_project(project_id: UUID, qdrant=None) -> None:
    from qdrant_client.http import models as qm
    try:
        qdrant = qdrant or client()
        if qdrant.collection_exists(COLLECTION):
            qdrant.delete(COLLECTION, points_selector=qm.FilterSelector(filter=qm.Filter(must=[
                qm.FieldCondition(key="project_id", match=qm.MatchValue(value=str(project_id)))])))
    except Exception as exc:  # the points are derived data: a later rebuild drops them anyway
        logger.warning(f"Project {project_id}: passages not removed from Qdrant: {exc}")


# ── passages ─────────────────────────────────────────────────────────


def chunk(text: str, size: int = CHUNK_CHARS, overlap: int = OVERLAP_CHARS) -> list[str]:
    """Cut text into passages of about ``size`` characters, at paragraph or sentence ends where possible."""
    text = "\n".join(line.rstrip() for line in (text or "").strip().splitlines())
    if len(text) <= size:
        return [text] if text.strip() else []
    out, start = [], 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            window = text[start:end]
            cut = max(window.rfind("\n\n"), window.rfind(". "), window.rfind("\n"))
            if cut > size // 2:
                end = start + cut + 1
        piece = text[start:end].strip()
        if piece:
            out.append(piece)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return out


def _feed_item_text(session: Session, item, full_text: bool) -> str:
    parts = [item.title, ", ".join(item.authors or [])]
    if item.abstract:
        parts.append(f"Abstract: {item.abstract}")
    if item.summary:
        parts.append(f"Summary: {item.summary}")
    if item.takeaways:
        parts.append("Key takeaways:\n" + "\n".join(f"- {t}" for t in item.takeaways if isinstance(t, str)))
    if full_text:
        try:
            import asyncio

            from athena.core.qa_fetcher import fetch_article_content
            result = asyncio.run(fetch_article_content(item))
            if not result.partial and result.text:
                parts.append(result.text)
        except Exception as exc:  # no network or no PDF: the abstract still answers
            logger.info(f"Project index: no full text for {item.id}: {exc}")
    return "\n\n".join(p for p in parts if p)


def _map_text(session: Session, topic) -> str:
    from athena.database import evolution as evo
    parts = [f"Research map: {topic.name}", topic.description or ""]
    if topic.built_at is None:
        return "\n\n".join(p for p in parts if p) + "\n\n(The map is not built yet.)"
    try:
        timeline = evo.topic_timeline(session, topic)
        lines = [f"{y['year']}: " + "; ".join(f"{p.get('named_method') or p['title']} ({p['title']})"
                                              for p in y["papers"][:6]) for y in timeline["years"]]
        parts.append("Milestones by year:\n" + "\n".join(lines))
    except Exception as exc:
        logger.warning(f"Project index: no timeline for {topic.slug}: {exc}")
    try:
        gaps = evo.topic_gaps(session, topic)
        lines = [f"- {t['label']} ({t['status']}, {t.get('first_year')}–{t.get('last_year')})"
                 for t in gaps.get("themes", [])[:15]]
        if lines:
            parts.append("Open problems and gaps:\n" + "\n".join(lines))
    except Exception as exc:
        logger.warning(f"Project index: no gaps for {topic.slug}: {exc}")
    return "\n\n".join(p for p in parts if p)


def _idea_text(check) -> str:
    result = check.result or {}
    verdict = result.get("verdict") or {}
    parts = [f"Idea check: {check.idea}"]
    for key in ("closest", "new", "gaps"):
        if verdict.get(key):
            value = verdict[key]
            parts.append(f"{key.capitalize()}: {value if isinstance(value, str) else value}")
    papers = result.get("papers") or []
    if papers:
        parts.append("Most similar papers:\n" + "\n".join(f"- {p.get('title')} ({p.get('year')})" for p in papers[:8]))
    return "\n\n".join(parts)


def item_passages(session: Session, item, full_text: bool = True) -> tuple[str, list[str], str | None]:
    """(title, passages, link) for a project item."""
    from athena.core.models import (
        ContentItem, EvoChunk, EvoIdeaCheck, EvoPaper, EvoTopic, LitReview, SavedList, SavedListItem,
    )
    if item.item_id:
        c = session.get(ContentItem, item.item_id)
        return c.title, chunk(_feed_item_text(session, c, full_text)), f"/items/{c.id}"
    if item.paper_id:
        p = session.get(EvoPaper, item.paper_id)
        head = f"{p.title} ({p.year or 'n.d.'})"
        passages = chunk(f"{head}\n\nAbstract: {p.abstract or ''}")
        sections = session.execute(select(EvoChunk.text).where(EvoChunk.paper_id == p.id)
                                   .order_by(EvoChunk.position)).scalars().all()
        return p.title, passages + [f"{head}\n\n{t}" for t in sections], None
    if item.ref.startswith("ext:"):
        m = item.meta or {}
        text = f"{m.get('title')} ({m.get('year') or 'n.d.'})\n{', '.join(m.get('authors') or [])}\n\n" \
               f"Abstract: {m.get('abstract') or '(none)'}"
        return m.get("title") or item.ref, chunk(text), m.get("url")
    if item.topic_id:
        t = session.get(EvoTopic, item.topic_id)
        return t.name, chunk(_map_text(session, t)), f"/evolution/{t.slug}"
    if item.review_id:
        r = session.get(LitReview, item.review_id)
        return r.title, chunk(r.markdown or "\n\n".join(s.get("markdown", "") for s in r.sections or [])), \
            f"/reviews/{r.id}"
    if item.idea_check_id:
        c = session.get(EvoIdeaCheck, item.idea_check_id)
        return c.idea[:120], chunk(_idea_text(c)), None
    if item.list_id:
        sl = session.get(SavedList, item.list_id)
        rows = session.execute(select(ContentItem).join(SavedListItem, SavedListItem.item_id == ContentItem.id)
                               .where(SavedListItem.list_id == sl.id)).scalars().all()
        return sl.name, [f"From the saved list {sl.name}:\n{_feed_item_text(session, c, False)}"[:CHUNK_CHARS * 2]
                         for c in rows], "/library"
    return item.ref, [], None


def caption(file, model: str | None = None, feature: str = "project_index", wait: bool = True) -> str | None:
    """A description of an uploaded image by the vision model, for project search and later chat turns. A chat
    captions right after its own turn (``wait`` False), while the chat still holds the model."""
    from athena.core import llm, usage
    from athena.projects import files
    from athena.model_server import activity, lane
    model = model or llm.vision_model()
    if wait:
        # Someone's upload: never held by a pause, and it waits for a chat only so long.
        lane.yield_to_chat(who=feature, pausable=False, max_wait=lane.ASKED_WAIT)
    with activity.track(feature, model, user_id=file.user_id) as call:
        resp = llm.chat_client(timeout=300, model=model).chat.completions.create(
            model=model, max_tokens=400, temperature=0.2, extra_body=llm.effort_extra(model, "off")[0],
            messages=[{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": files.image_data_url(file.path, file.mime)}},
                {"type": "text", "text": CAPTION_PROMPT}]}])
        call.tokens(*usage.tokens_of(resp.usage))
    usage.add(feature, model, *usage.tokens_of(resp.usage), user_id=file.user_id)
    return (resp.choices[0].message.content or "").strip() or None


# ── indexing ─────────────────────────────────────────────────────────


def _upsert(source: str, project_id: UUID, user_id: UUID, kind: str, title: str, link: str | None,
            passages: list[str], qdrant) -> int:
    from qdrant_client.http import models as qm

    from athena.core import llm
    from athena.model_server import lane
    delete_source(source, qdrant)
    passages = [p for p in passages if p.strip()][:MAX_CHUNKS]
    for start in range(0, len(passages), EMBED_BATCH):
        batch = passages[start:start + EMBED_BATCH]
        lane.yield_to_chat(who="project_index", pausable=False, max_wait=lane.ASKED_WAIT)
        vectors = llm.embed(batch, feature="project_index", user_id=user_id)
        qdrant.upsert(COLLECTION, points=[qm.PointStruct(
            id=str(uuid.uuid5(_NAMESPACE, f"{source}:{start + i}")), vector=vec.tolist(),
            payload={"project_id": str(project_id), "user_id": str(user_id), "source": source, "kind": kind,
                     "title": title, "link": link, "text": text, "position": start + i})
            for i, (text, vec) in enumerate(zip(batch, vectors))])
    return len(passages)


def index_pending(session: Session, project_id: UUID, full_text: bool = True) -> dict:
    """Embed everything in the project still marked pending. Returns counts."""
    from athena.core.models import Project
    from athena.database import projects as db

    project = session.get(Project, project_id)
    if project is None:
        return {"indexed": 0, "failed": 0}
    qdrant = client()
    ensure_collection(qdrant)
    items, uploads, arts = db.pending_index(session, project_id)
    done = failed = 0

    def run(row, source: str, kind: str, make) -> None:
        nonlocal done, failed
        try:
            title, passages, link = make()
            _upsert(source, project_id, project.user_id, kind, title, link, passages, qdrant)
            row.index_status = "indexed"
            if hasattr(row, "index_error"):
                row.index_error = None
            done += 1
        except Exception as exc:
            logger.warning(f"Project {project_id}: {source} not indexed: {exc}")
            session.rollback()
            row.index_status = "failed"
            if hasattr(row, "index_error"):
                row.index_error = str(exc)[:300]
            failed += 1
        session.commit()

    for item in items:
        run(item, f"item:{item.id}", item.kind, lambda item=item: item_passages(session, item, full_text))
    for f in uploads:
        def make_file(f=f):
            if f.kind == "image" and not f.caption:
                f.caption = caption(f)
            text = f.caption if f.kind == "image" else f.text
            return f.filename, chunk(f"{f.filename}\n\n{text or ''}"), None
        run(f, f"file:{f.id}", "file", make_file)
    for a in arts:
        run(a, f"artifact:{a.id}", "artifact", lambda a=a: (a.title, chunk(f"# {a.title}\n\n{a.content}"), None))
    return {"indexed": done, "failed": failed}


# ── retrieval ────────────────────────────────────────────────────────


def retrieve(project_id: UUID, question: str, limit: int = HITS, start: int = 1) -> list[Passage]:
    """The project's passages that best answer ``question``, at most PER_SOURCE from one source, numbered from
    ``start``. [] when nothing is indexed yet; raises when the embedding model does not answer."""
    from qdrant_client.http import models as qm

    from athena.core import llm
    qdrant = client()
    if not qdrant.collection_exists(COLLECTION):
        return []
    vec = llm.embed([question], instruct=INSTRUCT, timeout=60.0, feature="chat")[0]
    hits = qdrant.query_points(COLLECTION, query=vec.tolist(), limit=limit * 4, with_payload=True,
                               query_filter=qm.Filter(must=[qm.FieldCondition(
                                   key="project_id", match=qm.MatchValue(value=str(project_id)))])).points
    taken: dict[str, int] = {}
    out: list[Passage] = []
    for h in hits:
        p = h.payload or {}
        if h.score < MIN_SCORE or taken.get(p.get("source"), 0) >= PER_SOURCE:
            continue
        taken[p["source"]] = taken.get(p["source"], 0) + 1
        out.append(Passage(n=start + len(out), kind=p.get("kind", ""), source=p["source"], title=p.get("title", ""),
                           text=p.get("text", ""), score=round(h.score, 3), link=p.get("link")))
        if len(out) == limit:
            break
    return out
