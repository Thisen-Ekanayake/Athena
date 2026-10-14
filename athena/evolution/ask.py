"""
Ask a map (ROADMAP E3): answers from one topic's papers, citing paper and section.

Retrieval looks only at the topic's papers. Papers whose full text was read
(Tier 2) answer with passages from their sections (Qdrant's ``paper_chunks``),
filtered by section type when asked; the rest answer with their abstract
(``paper_abstracts``), and the answer says so. Filtering by paper ID rather
than the chunks' ``topic_ids`` payload keeps papers that joined a map after
their chunks were embedded.

The chat model gets the passages numbered and must cite them as [n]; the API
streams its answer (``athena.api.routers.evolution``).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

INSTRUCT = "Given a question about a research field, retrieve passages from papers that answer it"
CHUNK_HITS = 12
PER_PAPER = 3
ABSTRACT_HITS = 6           # alongside full-text passages
ABSTRACT_ONLY_HITS = 10     # when no paper in the topic has full text
MIN_SCORE = 0.45            # as for topic search (athena.evolution.search.SEMANTIC_MIN_SCORE)
SECTIONS = {  # the filters offered, and the section types each covers (athena.evolution.tei.SECTION_TYPES)
    "method": ["method"],
    "results": ["results", "discussion"],
    "limitations": ["limitations", "future_work", "discussion", "conclusion"],
}
SECTION_LABELS = {"abstract": "Abstract", "intro": "Introduction", "related_work": "Related work", "method": "Method",
                  "results": "Results", "discussion": "Discussion", "limitations": "Limitations",
                  "conclusion": "Conclusion", "future_work": "Future work", "other": "Body"}
SYSTEM = ("You answer questions about a research field using only the numbered sources you are given. "
          "Cite the sources for every claim as [n], with the number of the source it comes from. If the sources do "
          "not answer the question, say so plainly instead of guessing. Be concise: a few short paragraphs or a "
          "short list.")


class AskUnavailable(RuntimeError):
    """No embedding endpoint answered."""


@dataclass
class Source:
    n: int
    paper_id: str
    title: str
    year: int | None
    named_method: str | None
    section_type: str
    heading: str
    text: str
    abstract_only: bool
    score: float

    def public(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k != "text"} | {"excerpt": self.text[:400]}


def _filter(qm, ids: list[str], section_types: list[str] | None):
    must = [qm.FieldCondition(key="paper_id", match=qm.MatchAny(any=ids))]
    if section_types:
        must.append(qm.FieldCondition(key="section_type", match=qm.MatchAny(any=section_types)))
    return qm.Filter(must=must)


def retrieve(session: Session, topic, question: str, sections: list[str] | None = None,
             paper_ids: list[UUID] | None = None, chunk_limit: int = CHUNK_HITS, per_paper: int = PER_PAPER,
             with_abstracts: bool = True) -> list[Source]:
    """The passages and abstracts that best answer ``question``, numbered in the order given to the model.

    ``paper_ids`` keeps the search to those papers of the topic (a literature review asks about one era's
    milestones at a time); ``with_abstracts`` False returns full-text passages only.
    """
    from qdrant_client.http import models as qm

    from athena.core.models import EvoChunk, EvoPaper, EvoSection
    from athena.database import evolution as db
    from athena.evolution import vectors
    from athena.evolution.search import embed_query

    vec = embed_query(question, INSTRUCT, timeout=30.0)
    if vec is None:
        raise AskUnavailable("The embedding model did not answer; start the model server and try again.")
    rows = {p.id: (tp, p) for tp, p in db._topic_rows(session, topic.id)}
    if paper_ids is not None:
        wanted = set(paper_ids)
        rows = {pid: row for pid, row in rows.items() if pid in wanted}
    parsed = [str(pid) for pid, (_, p) in rows.items() if p.full_text_status == "parsed"]
    others = [str(pid) for pid, (_, p) in rows.items() if p.full_text_status != "parsed"]
    types = sorted({t for s in sections or [] for t in SECTIONS.get(s, [])}) or None
    qdrant = vectors.client()

    chunk_hits = []
    if parsed and qdrant.collection_exists(vectors.COLLECTION):
        taken: dict[str, int] = {}
        for hit in qdrant.query_points(vectors.COLLECTION, query=vec.tolist(), query_filter=_filter(qm, parsed, types),
                                       limit=chunk_limit * 4, with_payload=True).points:
            pid = hit.payload["paper_id"]
            if hit.score < MIN_SCORE or taken.get(pid, 0) >= per_paper:
                continue
            taken[pid] = taken.get(pid, 0) + 1
            chunk_hits.append(hit)
            if len(chunk_hits) == chunk_limit:
                break
    abstract_hits = []
    if with_abstracts and others and qdrant.collection_exists(vectors.ABSTRACT_COLLECTION):
        limit = ABSTRACT_HITS if parsed else ABSTRACT_ONLY_HITS
        abstract_hits = [h for h in qdrant.query_points(vectors.ABSTRACT_COLLECTION, query=vec.tolist(),
                                                        query_filter=_filter(qm, others, None), limit=limit).points
                         if h.score >= MIN_SCORE]

    chunks = {c.id: (c, s) for c, s in session.execute(
        select(EvoChunk, EvoSection).join(EvoSection, EvoChunk.section_id == EvoSection.id)
        .where(EvoChunk.id.in_([UUID(str(h.id)) for h in chunk_hits])))} if chunk_hits else {}
    names = db.method_names(session, {pid: p.title for pid, (_, p) in rows.items()
                                      if str(pid) in {h.payload["paper_id"] for h in chunk_hits}
                                      | {str(h.id) for h in abstract_hits}})
    found: list[tuple[float, dict]] = []
    for h in chunk_hits:
        cs = chunks.get(UUID(str(h.id)))
        if cs is None:
            continue  # re-parsed since it was embedded
        chunk, section = cs
        tp, p = rows[chunk.paper_id]
        found.append((h.score, {"paper_id": str(p.id), "title": p.title, "year": p.year,
                                "named_method": names.get(p.id) or tp.named_method,
                                "section_type": chunk.section_type, "heading": section.heading,
                                "text": chunk.text, "abstract_only": False}))
    abstracts = {p.id: p for p in session.execute(select(EvoPaper).where(
        EvoPaper.id.in_([UUID(str(h.id)) for h in abstract_hits]))).scalars()} if abstract_hits else {}
    for h in abstract_hits:
        p = abstracts.get(UUID(str(h.id)))
        if p is None or not p.abstract:
            continue
        tp, _ = rows[p.id]
        found.append((h.score, {"paper_id": str(p.id), "title": p.title, "year": p.year,
                                "named_method": names.get(p.id) or tp.named_method, "section_type": "abstract",
                                "heading": "Abstract", "text": p.abstract, "abstract_only": True}))
    found.sort(key=lambda f: -f[0])
    return [Source(n=i, score=round(score, 3), **f) for i, (score, f) in enumerate(found, start=1)]


def messages(topic_name: str, question: str, sources: list[Source], history: list[dict]) -> list[dict]:
    """The chat: system rules, earlier turns (their answers only, without sources), then sources and question."""
    listed = "\n\n".join(
        f"[{s.n}] {s.title} ({s.year or 'n.d.'}), "
        f"{'abstract only' if s.abstract_only else SECTION_LABELS.get(s.section_type, 'Body') + ': ' + s.heading}"
        f"\n{s.text}" for s in sources)
    out = [{"role": "system", "content": SYSTEM}]
    for turn in history[-3:]:
        out += [{"role": "user", "content": turn["question"][:1000]},
                {"role": "assistant", "content": turn["answer"][:2000]}]
    prompt = f"Research field: {topic_name}\n\nSources:\n\n{listed or '(none found)'}\n\nQuestion: {question}"
    out.append({"role": "user", "content": prompt})
    return out
