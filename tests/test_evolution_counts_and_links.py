"""The maps list counts papers and milestones in the database, and a map's links to the others are read from a
few columns of their rows (athena.database.evolution.topics.list_topics, graph.topic_links)."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from athena.core.models import (
    EvoCitation, EvoCitationContext, EvoGapTheme, EvoMilestoneOverride, EvoPaper, EvoSnapshot, EvoTopic,
    EvoTopicPaper,
)
from athena.database.evolution import graph as g, topics as t


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    for model in (EvoTopic, EvoPaper, EvoTopicPaper, EvoCitation, EvoCitationContext, EvoMilestoneOverride,
                  EvoSnapshot, EvoGapTheme):
        model.__table__.create(engine)
    statements: list[str] = []
    event.listen(engine, "before_cursor_execute", lambda conn, cur, sql, *rest: statements.append(sql))
    with sessionmaker(bind=engine)() as s:
        s.statements = statements
        yield s


def a_map(session, slug: str, built: bool = True) -> EvoTopic:
    tid = uuid4()
    session.execute(EvoTopic.__table__.insert().values(
        id=tid, slug=slug, name=slug.upper(), status="ready", config={}, aliases=None, seeds=[],
        built_at=datetime(2026, 10, 1, tzinfo=timezone.utc) if built else None))
    return session.get(EvoTopic, tid)


def a_paper(session, title: str, year: int = 2020):
    pid = uuid4()
    session.execute(EvoPaper.__table__.insert().values(  # Core insert: SQLite has no ARRAY for merged_ids
        id=pid, openalex_id=f"W{title}", title=title, year=year, authors=[], authorships=[], merged_ids=None, extra={}))
    return pid


def put(session, topic: EvoTopic, paper, milestone: bool = False, score: float = 0.0) -> None:
    session.add(EvoTopicPaper(id=uuid4(), topic_id=topic.id, paper_id=paper, kind="method",
                              score_detail={"relevance": 0.2},  # an on-topic method paper
                              is_milestone_auto=milestone, milestone_score=score))


def cite(session, citing, cited) -> None:
    session.add(EvoCitation(id=uuid4(), citing_id=citing, cited_id=cited))


def pin(session, topic: EvoTopic, paper, action: str) -> None:
    session.add(EvoMilestoneOverride(id=uuid4(), topic_id=topic.id, paper_id=paper, action=action))


def test_the_list_counts_papers_and_milestones_with_pins_applied(db):
    peft, rag = a_map(db, "peft"), a_map(db, "rag")
    a_map(db, "empty", built=False)
    lora, adapters, prefix, shared = (a_paper(db, n) for n in ("lora", "adapters", "prefix", "shared"))
    put(db, peft, lora, milestone=True)
    put(db, peft, adapters, milestone=True)
    put(db, peft, prefix)
    put(db, peft, shared)
    put(db, rag, shared, milestone=True)
    pin(db, peft, adapters, "unpin")   # an automatic pick a person took away
    pin(db, peft, prefix, "pin")       # and one a person added
    pin(db, rag, lora, "pin")          # a pin for a paper that is not in that map counts for nothing
    db.commit()
    listed = {m["slug"]: (m["paper_count"], m["milestone_count"]) for m in t.list_topics(db)}
    assert listed == {"peft": (4, 2), "rag": (1, 1), "empty": (0, 0)}
    # the same answer as the rule the map pages use, paper by paper
    for topic in (peft, rag):
        overrides = t._overrides(db, topic.id)
        by_rule = sum(t.effective_milestone(tp.is_milestone_auto, overrides[p.id].action if p.id in overrides else None)
                      for tp, p in t._topic_rows(db, topic.id))
        assert listed[topic.slug][1] == by_rule


def test_the_list_does_not_load_the_maps_papers(db):
    """Counting used to load every paper of every map (abstracts, authors and all): 1.3 s for 18 maps."""
    for slug in ("a", "b", "c"):
        topic = a_map(db, slug)
        put(db, topic, a_paper(db, f"{slug}1"), milestone=True)
    db.commit()
    db.statements.clear()
    assert len(t.list_topics(db)) == 3
    assert len(db.statements) == 3  # the latest changes, the counts, the maps: not one more per map
    assert not any("evo_papers" in sql for sql in db.statements)


def test_links_shared_borrowed_and_lent(db):
    peft, rag, vla = a_map(db, "peft"), a_map(db, "rag"), a_map(db, "vla")
    lora, adapters, both = a_paper(db, "lora"), a_paper(db, "adapters"), a_paper(db, "both")
    dpr, fid, rt2 = a_paper(db, "dpr"), a_paper(db, "fid"), a_paper(db, "rt2")
    put(db, peft, lora, milestone=True, score=0.9)
    put(db, peft, adapters, score=0.4)
    put(db, peft, both, score=0.2)
    put(db, rag, dpr, milestone=True)
    put(db, rag, fid)
    put(db, rag, both, milestone=True)
    put(db, vla, rt2)
    cite(db, adapters, dpr)   # PEFT borrows RAG's milestone
    cite(db, lora, dpr)
    cite(db, fid, lora)       # RAG and VLA build on PEFT's milestone
    cite(db, rt2, lora)
    cite(db, rt2, adapters)   # not a milestone here: not lent
    db.commit()
    links = g.topic_links(db, peft)
    assert links["shared"]["total"] == 1
    assert links["shared"]["papers"][0]["title"] == "both"
    assert links["shared"]["papers"][0]["elsewhere"] == [{"topic": "rag", "topic_name": "RAG", "milestone": True}]
    assert [(b["title"], b["citing_papers"], b["from"]["topic"]) for b in links["borrowed"]] == [("dpr", 2, "rag")]
    assert [(lent["title"], lent["citing_papers"], lent["by"]) for lent in links["lent"]] == [
        ("lora", 2, {"RAG": 1, "VLA": 1})]


def test_links_read_the_other_maps_narrowly_and_keep_long_id_lists_out_of_the_query(db, monkeypatch):
    peft, rag = a_map(db, "peft"), a_map(db, "rag")
    lora = a_paper(db, "lora")
    put(db, peft, lora, milestone=True)
    others = [a_paper(db, f"r{i}") for i in range(6)]
    for p in others:
        put(db, rag, p)
        cite(db, p, lora)
    db.commit()
    monkeypatch.setattr(g, "_CITING_IN_QUERY", 3)  # six citing papers: more than the query names
    db.statements.clear()
    links = g.topic_links(db, peft)
    assert [(lent["title"], lent["citing_papers"], lent["by"]) for lent in links["lent"]] == [("lora", 6, {"RAG": 6})]
    other_rows = [sql for sql in db.statements if "FROM evo_topic_papers" in sql and "evo_papers" not in sql]
    assert len(other_rows) == 1 and "score_detail" not in other_rows[0]  # one read of three columns
    citation_reads = [sql for sql in db.statements if "FROM evo_citations" in sql]
    assert citation_reads and all("citing_id IN" not in sql for sql in citation_reads)


def test_the_labels_version_changes_with_rows_and_labels(db):
    before = t.labels_version(db)
    a, b = a_paper(db, "a"), a_paper(db, "b")
    db.add(EvoCitationContext(id=uuid4(), citing_id=a, cited_id=b, source="grobid", sentence="x", sentence_hash="h1"))
    db.commit()
    added = t.labels_version(db)
    db.execute(EvoCitationContext.__table__.update().values(
        label="uses", labelled_at=datetime(2026, 11, 1, tzinfo=timezone.utc)))
    db.commit()
    assert len({before, added, t.labels_version(db)}) == 3
