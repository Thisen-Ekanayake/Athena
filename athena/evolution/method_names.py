"""
Named methods from Semantic Scholar's citing sentences (ROADMAP E9, parked).

A paper that introduced a named method is cited by that name ("LoRA [15]",
"Faster R-CNN (Ren et al., 2015)"). Tier 2 full text already yields such
names, but only for papers that Tier 2 papers cite, which are mostly the
current milestones; as a score feature that would only reinforce the current
picks. So the feature reads names from Semantic Scholar instead, for each
topic's top candidates by milestone score, whatever their milestone status:
one request per paper for its newest 1,000 citing papers. Without an API key
that is one request every 3 seconds or so, about ten minutes per topic, and
responses are cached for 30 days.

The result is stored per paper in ``evo_papers.cited_name``. Run it by hand
(``scripts/evolution_method_names.py``); refreshes no longer fetch it.

Parked (ROADMAP_v2 D4): as a milestone-score feature it never earned a weight.
Evaluated 2026-10-13 (``scripts/evolution_bench/eval_named_method.py``, replayed
on the four curated topics): reference milestones picked at w = 0 / 0.05 /
0.10 / 0.15 were object detection 9/9/9/8 of 11, PEFT 8/8/9/9 of 12, diffusion
7/6/5/4 of 12, RAG 7/6/5/1 of 10. A name is found for 55-75% of each topic's top
150 candidates, so the feature mostly reshuffles them (RAG lost RETRO,
Contriever and Active RAG to R3 and BERTserini). No weight gains on a topic
without losing on another, so builds no longer score it; the stored names stay
for the eval and for display.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Hashable, Iterable
from uuid import UUID

from loguru import logger

from athena.evolution.fulltext import s2_marked
from athena.evolution.names import detect_method_name, suffixes

TOP_CANDIDATES = 150
REFRESH_DAYS = 30  # names are fetched again after this long, as the S2 cache expires
# A name counts when at least MIN_USERS citing papers, and MIN_SHARE of those whose sentences could show one,
# use it. Many Semantic Scholar sentences cite several papers at once and so cannot say which name belongs to
# which; against every citing paper, the Phase 2 share (0.3) named no object detection paper at all. Checked by
# eye on object detection's top 48: at 0.1 the names are right (R-CNN, HOG, DPM, YOLO, SSD, FPN, DETR, OHEM);
# 0.05 adds ConvNet and dataset names, and 0.15 loses YOLO and Focal Loss.
MIN_USERS = 5
MIN_SHARE = 0.1


def name_from_contexts(contexts: Iterable[tuple[Hashable, list[str]]], title: str) -> dict:
    """{name, users, citers} from (citing paper, sentences) pairs. ``name`` is None when none stands out.

    ``citers`` counts the citing papers with a sentence citing only this paper, the ones that could show a name.
    """
    mentions: list[tuple[Hashable, str]] = []
    observable = set()
    for citer, sentences in contexts:
        for sentence in sentences:
            mention, marked = s2_marked(sentence)  # one marker only: then it must be this paper's
            if marked:
                observable.add(citer)
            if mention:
                mentions.append((citer, mention))
    name = detect_method_name(mentions, title, len(observable), min_citers=MIN_USERS, min_share=MIN_SHARE)
    users = len({c for c, m in mentions if name in suffixes(m)}) if name else 0
    return {"name": name, "users": users, "citers": len(observable)}


def candidates(session, topic, top: int = TOP_CANDIDATES) -> list[tuple[UUID, str, str]]:
    """(paper id, Semantic Scholar id, title) of the topic's on-topic method papers with the highest scores."""
    from athena.database import evolution as db
    from athena.evolution.config import TopicConfig
    from athena.evolution.eras import on_topic_method

    weight = TopicConfig.from_dict(topic.config).weights.relevance
    rows = [(tp.milestone_score or 0.0, p) for tp, p in db._topic_rows(session, topic.id)
            if p.s2_paper_id and on_topic_method(tp.kind, tp.score_detail, weight)]
    rows.sort(key=lambda r: r[0], reverse=True)
    return [(p.id, p.s2_paper_id, p.title) for _, p in rows[:top]]


def fetch_method_names(slug: str, top: int = TOP_CANDIDATES, s2=None, force: bool = False) -> dict:
    """Fetch citing sentences for the topic's top candidates and store each one's cited name."""
    from athena.database import evolution as db
    from athena.database.db import SessionLocal
    from athena.core.semantic_scholar import SemanticScholarClient

    s2 = s2 or SemanticScholarClient()
    now = datetime.now(timezone.utc)
    named = fetched = skipped = 0
    with SessionLocal() as session:
        topic = db.get_topic(session, slug)
        if topic is None:
            raise ValueError(f"Unknown topic {slug!r}")
        todo = candidates(session, topic, top)
        fresh = db.cited_names_fetched_since(session, [pid for pid, _, _ in todo], REFRESH_DAYS)
        for i, (paper_id, s2_id, title) in enumerate(todo, start=1):
            if paper_id in fresh and not force:
                skipped += 1
                continue
            result = name_from_contexts(s2.citation_contexts(s2_id), title)
            db.save_cited_name(session, paper_id, result | {"fetched_at": now.isoformat()})
            fetched += 1
            named += result["name"] is not None
            if i % 25 == 0:
                logger.info(f"Method names for {slug}: {i}/{len(todo)} papers, {named} named")
    summary = {"candidates": len(todo), "fetched": fetched, "skipped_fresh": skipped, "named": named,
               "s2_requests": s2.requests}
    logger.info(f"Method names for {slug}: {summary}")
    return summary
