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


def build_topic(slug: str, client: OpenAlexClient | None = None,
                s2: SemanticScholarClient | None = None) -> dict:
    with SessionLocal() as session:
        topic = db.get_topic(session, slug)
        if topic is None:
            raise ValueError(f"Unknown topic {slug!r}; seed it with scripts/seed_evolution_topics.py")
        config = TopicConfig.from_dict(topic.config)
        seeds = [Seed(**s) for s in (topic.seeds or [])]
        search_terms = [topic.name, *(topic.aliases or [])]

    start = time.time()
    db.set_topic_status(slug, "building")
    try:
        corpus = build_corpus(client or OpenAlexClient(), seeds, config, s2, search_terms)
        membership = topic_membership(corpus, config)
        scores = score_topic(corpus, config, membership)
        db.save_topic_build(slug, corpus, scores)
    except Exception as exc:
        db.set_topic_status(slug, "failed", str(exc)[:500])
        raise
    summary = corpus.stats | scores.stats | {"seconds": round(time.time() - start, 1)}
    db.set_topic_status(slug, "ready", ", ".join(f"{k}={v}" for k, v in summary.items()))
    logger.info(f"Built topic {slug}: {summary}")
    return summary
