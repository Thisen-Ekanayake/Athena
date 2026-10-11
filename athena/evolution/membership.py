"""
Topic membership from abstract embeddings (Tier 1).

Which corpus papers are about the topic decides which can be milestones, lie
on the main path, or be a milestone's successor. Keywords alone get this
wrong both ways: an abstract that merely mentions fine-tuning made R-CNN a
PEFT paper, and a paper about kNN-LM never says "retrieval-augmented".

So each topic gets a profile: the mean abstract vector of its seeds and of
every corpus paper whose title contains a topic keyword (those papers name
the topic outright). A paper whose topic keyword appears only in its
abstract counts as on-topic only if its abstract is at least as close to the
profile as the 10th percentile of the title papers; below that it is a
paper that merely mentions the topic. A title keyword always counts, and a
paper without a vector yet (new since the last GPU lane) keeps the keyword
rule.

Similarity only removes, never adds. Letting it add papers without a keyword
(at the title papers' median and 10th percentile) was tried first: the same
reference papers were picked in all four topics, but field-wide papers that
share the vocabulary without being about the topic (BERT, GPT-3, T5, ResNet,
GANs) became on-topic and, being cited by everyone, milestones, pushing out
SSD, MAD-X, P-Tuning v2, NCSN and RocketQA. The papers it removed were
mostly off-topic (captioning and class-incremental learning in object
detection, agent taxonomies in RAG, time series in diffusion).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from sqlalchemy import select

from athena.evolution.corpus import Corpus, relevance

LOW_PERCENTILE = 10
MIN_PROFILE_PAPERS = 10  # fewer title papers than this: not enough to set thresholds, keywords decide


@dataclass
class Membership:
    relevance: dict[str, float]               # paper -> 0, 0.5 or 1
    similarity: dict[str, float] = field(default_factory=dict)  # paper -> cosine to the profile
    stats: dict = field(default_factory=dict)


def keyword_only(corpus: Corpus, keywords: list[str], reason: str) -> Membership:
    rel = {pid: relevance(p.title, p.work.abstract, keywords) for pid, p in corpus.papers.items()}
    return Membership(rel, stats={"membership": f"keywords ({reason})"})


def semantic_membership(corpus: Corpus, keywords: list[str], vectors: dict[str, np.ndarray],
                        seed_ids: set[str]) -> Membership:
    """Relevance from keywords and abstract similarity to the topic profile (see module docstring)."""
    if not keywords:
        return keyword_only(corpus, keywords, "the topic has no keywords")
    titled = {pid for pid, p in corpus.papers.items() if relevance(p.title, None, keywords) > 0}
    profile_ids = [pid for pid in titled | seed_ids if pid in vectors]
    if len(profile_ids) < MIN_PROFILE_PAPERS:
        return keyword_only(corpus, keywords, f"only {len(profile_ids)} titled papers have vectors")

    profile = np.mean([vectors[pid] for pid in profile_ids], axis=0)
    profile /= np.linalg.norm(profile) or 1.0
    sims = {pid: float(np.dot(vec, profile)) for pid, vec in vectors.items() if pid in corpus.papers}
    low = float(np.percentile([sims[pid] for pid in titled if pid in sims], LOW_PERCENTILE))

    rel: dict[str, float] = {}
    removed = 0
    for pid, paper in corpus.papers.items():
        rel[pid] = relevance(paper.title, paper.work.abstract, keywords)
        if 0 < rel[pid] < 1 and pid in sims and sims[pid] < low:
            rel[pid] = 0.0  # the keyword is only in the abstract, and the paper is about something else
            removed += 1
    stats = {"membership": "semantic", "profile_papers": len(profile_ids), "with_vectors": len(sims),
             "threshold": round(low, 3), "on_topic_removed": removed}
    return Membership(rel, sims, stats)


def abstract_vectors(openalex_ids: list[str]) -> dict[str, np.ndarray]:
    """Stored abstract vectors (Qdrant paper_abstracts) for the papers Athena already knows."""
    from athena.core.models import EvoPaper
    from athena.database.db import SessionLocal
    from athena.evolution import vectors

    with SessionLocal() as session:
        ids = dict(session.execute(select(EvoPaper.id, EvoPaper.openalex_id)
                                   .where(EvoPaper.openalex_id.in_(openalex_ids),
                                          EvoPaper.abstract_embedded_at.isnot(None))).all())
    if not ids:
        return {}
    qdrant = vectors.client()
    if not qdrant.collection_exists(vectors.ABSTRACT_COLLECTION):
        return {}
    found = vectors.vectors_for(list(ids), name=vectors.ABSTRACT_COLLECTION, qdrant=qdrant)
    return {ids[pid]: vec for pid, vec in found.items()}
