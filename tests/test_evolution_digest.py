"""A research map as a graph for a chat model (athena.evolution.digest): ids that hold across levels, the main
path as chains, typed links from citing sentences, open problems tied to papers, and the mentions an answer makes."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from athena.core.models import (
    EvoCitation, EvoCitationContext, EvoGapStatement, EvoGapTheme, EvoGapThemeMember, EvoLooseLink, EvoMainPathEdge,
    EvoMilestoneOverride, EvoPaper, EvoTopic, EvoTopicPaper,
)
from athena.evolution import digest as d


def data() -> dict:
    """Five papers: 1 → 2 → 4 on the main path (2 is not a milestone), 3 and 5 off it."""
    nodes = [
        {"n": 1, "paper_id": "p1", "year": 2019, "title": "Parameter-Efficient Transfer Learning for NLP",
         "label": "Adapters", "milestone": True, "main": True},
        {"n": 2, "paper_id": "p2", "year": 2020, "title": "AdapterFusion", "label": None, "milestone": False,
         "main": True},
        {"n": 3, "paper_id": "p3", "year": 2021, "title": "Prefix-Tuning: Optimizing Continuous Prompts",
         "label": "Prefix-Tuning", "milestone": True, "main": False},
        {"n": 4, "paper_id": "p4", "year": 2021, "title": "LoRA: Low-Rank Adaptation of Large Language Models",
         "label": "LoRA", "milestone": True, "main": True},
        {"n": 5, "paper_id": "p5", "year": 2023, "title": "QLoRA: Efficient Finetuning of Quantized LLMs",
         "label": "QLoRA", "milestone": True, "main": False},
    ]
    return {"slug": "peft", "name": "PEFT", "description": "Adapting large models cheaply.", "papers": 120,
            "years": [2017, 2025], "nodes": nodes, "main": [[2, 1], [4, 2]],
            "links": [{"from": 4, "to": 1, "rel": "fixes", "quote": "adapters add inference latency"},
                      {"from": 5, "to": 4, "rel": "builds on"}, {"from": 3, "to": 1, "rel": "cites"}],
            "eras": [[2017, 2020], [2021, 2025]],
            "gaps": [{"label": "forgetting", "status": "persisting", "years": [2019, 2024], "raised": [1, 3],
                      "fixed": [5]}]}


def test_the_full_graph_names_papers_and_their_links():
    text = d.render(data(), "A", d.FULL)
    assert text.startswith("Map A: PEFT [slug peft]: 120 papers, 2017–2025")
    assert "A1 2019 Adapters: Parameter-Efficient Transfer Learning for NLP *" in text
    assert "A4 2021 LoRA: Low-Rank Adaptation of Large Language Models *" in text  # the title already names it
    assert "A2 2020 AdapterFusion\n" in text
    assert "Main path (→ the later paper builds on the earlier): A1 → A2 → A4" in text
    assert "A4 fixes A1: “adapters add inference latency”" in text and "A5 builds on A4" in text
    assert "A3 cites A1" in text
    assert "Eras: 2017–2020 A1–A2 · 2021–2025 A3–A5" in text
    assert "- forgetting (persisting, 2019–2024): raised by A1, A3; addressed by A5" in text


def test_smaller_levels_keep_the_ids_and_skip_over_hidden_papers():
    compact = d.render(data(), "B", d.COMPACT)
    assert "B2" not in compact  # not a milestone
    assert "B1 → B4" in compact and "B4 fixes B1" in compact and "“" not in compact and "cites" not in compact
    minimal = d.render(data(), "B", d.MINIMAL)
    assert "B4 2021 LoRA" in minimal and "Links" not in minimal and "Open problems" not in minimal
    assert len(minimal) < len(compact) < len(d.render(data(), "B", d.FULL))


def test_branching_main_paths_cover_each_edge_once():
    assert d.chains([(2, 1), (3, 2), (4, 2)], {1, 2, 3, 4}) == [[1, 2, 3], [2, 4]]
    assert d.chains([(2, 1), (3, 2)], {1, 3}) == [[1, 3]]
    assert d.chains([], {1}) == []


def test_mentions_are_the_known_ids():
    known = d.refs(data(), "A")
    assert known["A4"] == {"slug": "peft", "map": "PEFT", "paper_id": "p4", "label": "LoRA", "year": 2021}
    found = d.mentioned("LoRA (A4) beat Adapters (A1) on an A100 (A9 is unknown).", known)
    assert set(found) == {"A4", "A1"}


@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    for model in (EvoTopic, EvoPaper, EvoTopicPaper, EvoCitation, EvoCitationContext, EvoMainPathEdge,
                  EvoMilestoneOverride, EvoGapStatement, EvoGapTheme, EvoGapThemeMember, EvoLooseLink):
        model.__table__.create(engine)
    with sessionmaker(bind=engine)() as s:
        yield s


def test_a_built_map_becomes_a_graph(session, monkeypatch):
    monkeypatch.setattr(d, "_redis", lambda: (_ for _ in ()).throw(RuntimeError("no redis")))
    tid = uuid4()
    session.execute(EvoTopic.__table__.insert().values(id=tid, slug="peft", name="PEFT", status="ready", config={},
                                                       aliases=None, seeds=[],
                                                       built_at=datetime(2026, 10, 1, tzinfo=timezone.utc)))
    topic = session.get(EvoTopic, tid)
    papers = {}
    for key, year, title, milestone, main in [("ad", 2019, "Adapters for NLP", True, True),
                                              ("mid", 2020, "A step between", False, True),
                                              ("lora", 2021, "LoRA: Low-Rank Adaptation", True, True),
                                              ("noise", 2022, "Unrelated", False, False)]:
        p = EvoPaper(id=uuid4(), openalex_id=f"W{key}", title=title, year=year)
        papers[key] = p  # Core insert: SQLite has no ARRAY for merged_ids
        session.execute(EvoPaper.__table__.insert().values(
            id=p.id, openalex_id=p.openalex_id, title=title, year=year, authors=[], authorships=[], merged_ids=None,
            extra={}))
        session.add(EvoTopicPaper(id=uuid4(), topic_id=topic.id, paper_id=p.id, kind="method", on_main_path=main,
                                  is_milestone_auto=milestone, milestone_score=1.0 if milestone else 0.1,
                                  score_detail={"relevance": 1}))
    session.add(EvoMilestoneOverride(id=uuid4(), topic_id=topic.id, paper_id=papers["mid"].id, action="pin"))
    for citing, cited in [("mid", "ad"), ("lora", "mid"), ("lora", "ad")]:
        session.add(EvoCitation(id=uuid4(), citing_id=papers[citing].id, cited_id=papers[cited].id))
    for citing, cited in [("mid", "ad"), ("lora", "mid")]:
        session.add(EvoMainPathEdge(id=uuid4(), topic_id=topic.id, citing_id=papers[citing].id,
                                    cited_id=papers[cited].id, spc_weight=1.0))
    session.add(EvoCitationContext(id=uuid4(), citing_id=papers["lora"].id, cited_id=papers["ad"].id,
                                   source="grobid", sentence="Adapters [[12]] add inference latency.",
                                   sentence_hash="h", label="addresses_limitation", attributed=True, cues=[],
                                   s2_intents=[]))
    session.commit()

    data = d.digest(session, topic)
    assert [n["title"] for n in data["nodes"]] == ["Adapters for NLP", "A step between", "LoRA: Low-Rank Adaptation"]
    assert all(n["milestone"] for n in data["nodes"])  # the pin counts
    assert data["main"] == [[2, 1], [3, 2]] and data["papers"] == 4
    assert {"from": 3, "to": 1, "rel": "fixes", "quote": "Adapters 12 add inference latency."} in data["links"]
    text = d.render(data, "A")
    assert "A1 → A2 → A3" in text and "A3 fixes A1" in text

    topic.built_at = None
    assert d.digest(session, topic) is None
