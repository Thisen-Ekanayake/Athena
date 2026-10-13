"""
Topic search: which curated topic a free-text query is about.

1. Names and aliases ("lora fine-tuning" -> PEFT), as before.
2. Semantic: the query embedded with Qwen3-Embedding against every topic paper's
   title and abstract (Qdrant's paper_abstracts, Tier 1). Needs the embedding
   endpoint; the GPU lane stops its server when done, so this works while it
   runs, or always with an external embedding API.
3. Text: PostgreSQL full-text search over the same titles and abstracts, so a
   search still works with no model running.

Steps 2 and 3 vote: each matching paper counts for the topics it belongs to,
weighted by how well it matches. A topic must win clearly, or the answer is
that the topic is not in the system. Text matches alone are too eager (PEFT has
adapter papers for speech, so "speech recognition" would land there), so in
step 3 the query must also mention one of the topic's own keywords.
"""
from __future__ import annotations

from collections import defaultdict
from uuid import UUID

import httpx
from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from athena.core.models import EvoPaper, EvoTopic, EvoTopicPaper

QUERY_INSTRUCT = "Given a research topic, retrieve titles and abstracts of papers about it"
SEMANTIC_HITS = 50
SEMANTIC_MIN_SCORE = 0.45   # cosine; below it a paper is not about the query
TEXT_HITS = 200
MIN_PAPERS = 5              # a topic needs this many matching papers
MIN_SHARE = 0.6             # and this share of the vote


def _mentions_keywords(query: str, topic: EvoTopic) -> bool:
    from athena.evolution.corpus import relevance  # word-start matching, as for paper relevance
    keywords = (topic.config or {}).get("keywords") or []
    return not keywords or relevance(query, None, keywords) > 0


def _vote(session: Session, weights: dict[UUID, float],
          require_keywords: str | None = None) -> tuple[EvoTopic | None, list[dict]]:
    if not weights:
        return None, []
    rows = session.execute(select(EvoTopicPaper.paper_id, EvoTopic)
                           .join(EvoTopic, EvoTopicPaper.topic_id == EvoTopic.id)
                           .where(EvoTopicPaper.paper_id.in_(list(weights)), EvoTopic.status == "ready")).all()
    if require_keywords is not None:
        rows = [(pid, t) for pid, t in rows if _mentions_keywords(require_keywords, t)]
    score: dict[UUID, float] = defaultdict(float)
    papers: dict[UUID, int] = defaultdict(int)
    topics = {}
    for paper_id, topic in rows:
        score[topic.id] += weights[paper_id]
        papers[topic.id] += 1
        topics[topic.id] = topic
    if not score:
        return None, []
    ranking = [{"slug": topics[t].slug, "score": round(v, 3), "papers": papers[t]}
               for t, v in sorted(score.items(), key=lambda kv: -kv[1])]
    best = max(score, key=score.get)
    if papers[best] < MIN_PAPERS or score[best] < MIN_SHARE * sum(score.values()):
        return None, ranking
    return topics[best], ranking


def embed_query(text: str, instruct: str, timeout: float = 10.0):
    """``text`` as a query vector in the evolution collections' space, or None when no embedding endpoint answers.

    Uses the evolution lane's embedder (EVOLUTION_EMBED_* override the app's own), so queries land in the same
    space as the stored abstracts, chunks and gap statements. The timeout leaves room for the router to swap
    the embedder in (about 1.5 s) behind a running request.
    """
    import numpy as np

    from athena.evolution import vectors
    from athena.evolution.classify import auth_headers, embed_model_name, embed_url
    url = embed_url()
    try:
        resp = httpx.post(f"{url}/v1/embeddings", timeout=timeout, headers=auth_headers(url), json={
            "input": [f"Instruct: {instruct}\nQuery: {text}"],
            "model": embed_model_name()})
        resp.raise_for_status()
    except httpx.HTTPError:
        return None
    return vectors.truncate(np.asarray([resp.json()["data"][0]["embedding"]]))[0]


def semantic_weights(query: str, timeout: float = 10.0) -> dict[UUID, float] | None:
    """Paper -> similarity for the papers nearest the query, or None when no embedding endpoint answers."""
    from athena.evolution import vectors
    vec = embed_query(query, QUERY_INSTRUCT, timeout)
    if vec is None:
        return None
    qdrant = vectors.client()
    if not qdrant.collection_exists(vectors.ABSTRACT_COLLECTION):
        return None
    hits = qdrant.query_points(vectors.ABSTRACT_COLLECTION, query=vec.tolist(), limit=SEMANTIC_HITS).points
    return {UUID(h.payload["paper_id"]): float(h.score) for h in hits if h.score >= SEMANTIC_MIN_SCORE}


def text_weights(session: Session, query: str) -> dict[UUID, float]:
    """Paper -> full-text rank of its title and abstract, for topic papers matching the query."""
    document = func.to_tsvector("english", EvoPaper.title + " " + func.coalesce(EvoPaper.abstract, ""))
    tsquery = func.websearch_to_tsquery("english", query)
    rank = func.ts_rank_cd(document, tsquery)
    rows = session.execute(
        select(EvoPaper.id, rank)
        .where(document.op("@@")(tsquery), EvoPaper.id.in_(select(EvoTopicPaper.paper_id)))
        .order_by(rank.desc()).limit(TEXT_HITS)).all()
    return {pid: float(r) for pid, r in rows}


def find_topic_by_content(session: Session, query: str) -> tuple[EvoTopic | None, dict]:
    """The topic whose papers best match ``query``, and how it was decided."""
    weights = semantic_weights(query)
    method = "semantic"
    if weights is None:
        method = "text"
        try:
            weights = text_weights(session, query)
        except Exception as exc:  # SQLite in tests has no full-text search
            logger.debug(f"Full-text topic search failed: {exc}")
            weights = {}
    topic, ranking = _vote(session, weights, require_keywords=query if method == "text" else None)
    return topic, {"method": method, "matching_papers": len(weights), "ranking": ranking[:5]}
