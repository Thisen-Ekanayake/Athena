"""Tests for topic membership from abstract embeddings (pure; no Qdrant)."""
from __future__ import annotations

import numpy as np

from athena.evolution.corpus import Corpus, CorpusPaper
from athena.evolution.membership import MIN_PROFILE_PAPERS, semantic_membership
from athena.evolution.openalex import Work


def paper(pid: str, title: str, abstract: str | None = None) -> CorpusPaper:
    return CorpusPaper(work=Work(openalex_id=pid, title=title, year=2020, abstract=abstract), year=2020,
                       year_source="openalex", role="core")


def unit(v):
    v = np.asarray(v, dtype=float)
    return v / np.linalg.norm(v)


def setup():
    rng = np.random.default_rng(0)
    topic, other = rng.normal(size=32), rng.normal(size=32)
    papers, vectors = {}, {}
    for i in range(MIN_PROFILE_PAPERS + 5):  # papers naming the topic in their title
        papers[f"T{i}"] = paper(f"T{i}", f"LoRA variant {i}")
        vectors[f"T{i}"] = unit(topic + 0.3 * rng.normal(size=32))
    papers["near"] = paper("near", "A method", "We compare with LoRA.")              # keyword in the abstract only
    vectors["near"] = unit(topic + 0.3 * rng.normal(size=32))
    papers["far"] = paper("far", "Image captioning", "Unlike LoRA, we caption images.")  # mentions it, is about else
    vectors["far"] = unit(other)
    papers["hub"] = paper("hub", "A foundation model", "Pre-trained language models.")    # no keyword at all
    vectors["hub"] = unit(topic)
    papers["new"] = paper("new", "Fresh paper", "It cites LoRA.")                          # no vector yet
    return Corpus(papers=papers, edges=set()), vectors


def test_abstract_mentions_far_from_the_topic_are_removed():
    corpus, vectors = setup()
    m = semantic_membership(corpus, ["lora"], vectors, seed_ids=set())
    assert m.relevance["near"] == 0.5
    assert m.relevance["far"] == 0.0
    assert m.stats["on_topic_removed"] == 1


def test_similarity_never_adds_a_paper_without_a_keyword():
    corpus, vectors = setup()
    assert semantic_membership(corpus, ["lora"], vectors, seed_ids=set()).relevance["hub"] == 0.0


def test_titles_count_and_papers_without_vectors_keep_the_keyword_rule():
    corpus, vectors = setup()
    m = semantic_membership(corpus, ["lora"], vectors, seed_ids=set())
    assert all(m.relevance[f"T{i}"] == 1.0 for i in range(MIN_PROFILE_PAPERS))
    assert m.relevance["new"] == 0.5


def test_too_few_title_papers_fall_back_to_keywords():
    corpus, vectors = setup()
    few = {pid: v for pid, v in vectors.items() if not pid.startswith("T") or pid in ("T0", "T1")}
    m = semantic_membership(corpus, ["lora"], few, seed_ids=set())
    assert m.relevance["far"] == 0.5 and m.stats["membership"].startswith("keywords")
