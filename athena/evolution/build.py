"""
Build one topic end to end: OpenAlex + Semantic Scholar corpus -> on-topic
papers (keywords and abstract embeddings) -> citation graph -> milestone
scores -> PostgreSQL. Runs from the Celery ``evolution`` queue or from
``scripts/build_evolution_topic.py``.
"""
from __future__ import annotations

import time

from loguru import logger

from athena.database import evolution as db
from athena.database.db import SessionLocal
from athena.evolution.config import TopicConfig
from athena.evolution.corpus import Seed, build_corpus
from athena.evolution.membership import Membership, abstract_vectors, keyword_only, semantic_membership
from athena.evolution.milestones import score_topic
from athena.evolution.openalex import OpenAlexClient
from athena.evolution.semantic_scholar import SemanticScholarClient


def topic_membership(corpus, config: TopicConfig) -> Membership:
    """On-topic papers from keywords and stored abstract vectors (vectors appear after a GPU lane)."""
    if not config.semantic_membership:
        return keyword_only(corpus, config.keywords, "turned off for this topic")
    seeds = {pid for pid, p in corpus.papers.items() if p.role == "seed"}
    return semantic_membership(corpus, config.keywords, abstract_vectors(list(corpus.papers)), seeds)


def build_topic(slug: str, client: OpenAlexClient | None = None, s2: SemanticScholarClient | None = None,
                stage_status: str = "building", status_after: str = "ready") -> dict:
    """Build ``slug`` and save it. Progress goes to ``status_detail`` under ``stage_status``.

    A search-built topic's first pass ends at ``refining`` (the map is viewable while its abstracts are
    embedded), and its second pass keeps that status while it runs, so the map stays up.
    """
    with SessionLocal() as session:
        topic = db.get_topic(session, slug)
        if topic is None:
            raise ValueError(f"Unknown topic {slug!r}; seed it with scripts/seed_evolution_topics.py")
        config = TopicConfig.from_dict(topic.config)
        seeds = [Seed(**s) for s in (topic.seeds or [])]
        search_terms = [topic.name, *(topic.aliases or [])]

    def stage(text: str) -> None:
        db.set_topic_status(slug, stage_status, text)

    start = time.time()
    stage("Starting")
    try:
        corpus = build_corpus(client or OpenAlexClient(), seeds, config, s2, search_terms, on_stage=stage)
        stage("Scoring milestones")
        membership = topic_membership(corpus, config)
        scores = score_topic(corpus, config, membership)
        stage("Saving the map")
        db.save_topic_build(slug, corpus, scores)
    except Exception as exc:
        db.set_topic_status(slug, "failed", str(exc)[:500])
        raise
    summary = corpus.stats | scores.stats | {"seconds": round(time.time() - start, 1)}
    db.set_topic_status(slug, status_after, ", ".join(f"{k}={v}" for k, v in summary.items()), stats=summary)
    logger.info(f"Built topic {slug}: {summary}")
    return summary


def build_search_topic(slug: str) -> dict:
    """A search-built topic: the map from keywords first, then again once its abstracts have vectors.

    The first pass ends at ``refining``, so the map can be read while the GPU embeds the abstracts. If the
    embedder cannot run (no model, the card busy elsewhere), the map stays as built, with keyword
    membership, and says why.
    """
    summary = build_topic(slug, status_after="refining")
    try:
        from athena.evolution.gpu import embed_abstracts  # numpy and Qdrant: the worker image only
        db.set_topic_status(slug, "refining", "Embedding the papers' abstracts")
        embedded = embed_abstracts()
    except Exception as exc:
        logger.warning(f"Topic {slug}: abstracts not embedded, keeping keyword membership: {exc}")
        note = f"Kept keyword membership: the abstracts could not be embedded ({exc})"
        db.set_topic_status(slug, "ready", note[:500], stats=summary | {"refine": f"skipped ({str(exc)[:200]})"})
        return summary
    try:
        refined = build_topic(slug, stage_status="refining")
    except Exception as exc:
        # The first pass's map is still stored; show it rather than a failure.
        logger.warning(f"Topic {slug}: the refining rebuild failed, keeping the first map: {exc}")
        db.set_topic_status(slug, "ready", f"The refining rebuild failed ({exc})"[:500],
                            stats=summary | {"refine": f"failed ({str(exc)[:200]})"})
        return summary
    refined |= {"abstracts_embedded": embedded, "refine": "done"}
    db.set_topic_status(slug, "ready", ", ".join(f"{k}={v}" for k, v in refined.items()), stats=refined)
    return refined
