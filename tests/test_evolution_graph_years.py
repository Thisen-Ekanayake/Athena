"""A map's graph for a span of years (athena.database.evolution.graph.topic_graph with year_from / year_to)."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from athena.core.models import (
    EvoCitation, EvoCitationContext, EvoGapStatement, EvoLooseLink, EvoMainPathEdge, EvoMilestoneOverride, EvoPaper,
    EvoTopic, EvoTopicPaper,
)
from athena.database.evolution import graph as g


@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    for model in (EvoTopic, EvoPaper, EvoTopicPaper, EvoCitation, EvoCitationContext, EvoMainPathEdge,
                  EvoMilestoneOverride, EvoGapStatement, EvoLooseLink):
        model.__table__.create(engine)
    with sessionmaker(bind=engine)() as s:
        yield s


def _map(session) -> EvoTopic:
    tid = uuid4()
    session.execute(EvoTopic.__table__.insert().values(id=tid, slug="peft", name="PEFT", status="ready", config={},
                                                       aliases=None, seeds=[],
                                                       built_at=datetime(2026, 10, 1, tzinfo=timezone.utc)))
    ids = {}
    for key, year in [("a", 2019), ("b", 2020), ("c", 2021), ("d", 2021), ("undated", None)]:
        ids[key] = uuid4()
        session.execute(EvoPaper.__table__.insert().values(  # Core insert: SQLite has no ARRAY for merged_ids
            id=ids[key], openalex_id=f"W{key}", title=key, year=year, authors=[], authorships=[], merged_ids=None,
            extra={}))
        session.add(EvoTopicPaper(id=uuid4(), topic_id=tid, paper_id=ids[key], kind="method", score_detail={}))
    for citing, cited in [("b", "a"), ("c", "b"), ("d", "b")]:
        session.add(EvoCitation(id=uuid4(), citing_id=ids[citing], cited_id=ids[cited]))
    session.commit()
    return session.get(EvoTopic, tid)


def test_every_year_by_default(session):
    graph = g.topic_graph(session, _map(session), limit=0)
    assert sorted(n["title"] for n in graph["nodes"]) == ["a", "b", "c", "d", "undated"]
    assert graph["years"] == [2019, 2020, 2021]


def test_a_range_draws_only_its_papers_and_the_links_between_them(session):
    graph = g.topic_graph(session, _map(session), limit=0, year_from=2020, year_to=2021)
    titles = {n["id"]: n["title"] for n in graph["nodes"]}
    assert sorted(titles.values()) == ["b", "c", "d"]
    assert sorted((titles[e["source"]], titles[e["target"]]) for e in graph["edges"]) == [("c", "b"), ("d", "b")]
    assert graph["years"] == [2019, 2020, 2021]  # still the whole map, for the year picker
    assert (graph["in_range"], graph["total_papers"]) == (3, 5)


def test_one_year(session):
    graph = g.topic_graph(session, _map(session), limit=0, year_from=2021, year_to=2021)
    assert sorted(n["title"] for n in graph["nodes"]) == ["c", "d"]
    assert graph["edges"] == []
