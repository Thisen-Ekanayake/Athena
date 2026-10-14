"""Literature reviews (ROADMAP S1): citations checked and renumbered, the map outline, the pipeline with a fake model,
the abstracts fallback, and the routes."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import re
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from athena.api.deps import get_db, get_redis
from athena.api.main import app
from athena.api.routers import reviews as review_routes
from athena.core.models import EvoTopic, LitReview, SavedList, User, UserSession
from athena.database import evolution as evo_db
from athena.evolution import review
from tests.fakes import FakeRedis
from tests.test_auth import make_user, setup_admin

BUILT = datetime(2026, 10, 1, tzinfo=timezone.utc)


# ── citations ────────────────────────────────────────────────────────


def test_citations_outside_a_section_are_removed():
    text, removed = review.check_citations("LoRA freezes weights [1, 9]. It adds adapters [9]. Both do [2-4].",
                                           {1, 2, 3})
    assert text == "LoRA freezes weights [1]. It adds adapters. Both do [2, 3]."
    assert removed == 3


def test_citations_are_renumbered_by_first_appearance():
    texts, mapping = review.renumber(["A [5] and [2, 5].", "B [7][2]. No citation here."])
    assert texts == ["A [1] and [1, 2].", "B [3][2]. No citation here."]
    assert mapping == {5: 1, 2: 2, 7: 3}


def test_a_reference_line():
    p = review.Paper(key="k", title="LoRA", year=2021, authors=["E. Hu", "Y. Shen", "P. Wallis", "Z. Allen-Zhu"],
                     venue="ICLR", url="https://arxiv.org/abs/2106.09685")
    assert review.reference(3, p) == ("[3] E. Hu, Y. Shen, P. Wallis et al. (2021). *LoRA*. ICLR. "
                                      "https://arxiv.org/abs/2106.09685")


# ── a fake map ───────────────────────────────────────────────────────


def paper(name, year, score, abstract=None):
    return SimpleNamespace(id=uuid4(), title=f"{name}: a method", year=year, authors=[f"{name} Author"], venue=None,
                           doi=None, arxiv_id=None, openalex_id=f"W{name}", abstract=abstract or f"{name} does X.",
                           score=score, name=name)


@pytest.fixture
def fake_map(monkeypatch):
    papers = [paper("Adapter", 2019, 0.9), paper("LoRA", 2021, 0.95), paper("DoRA", 2024, 0.7),
              paper("Survey", 2024, 0.1)]
    by_id = {p.id: p for p in papers}
    node = lambda p: {"id": str(p.id), "title": p.title, "year": p.year, "named_method": p.name,  # noqa: E731
                      "milestone_score": p.score}
    milestones = papers[:3]
    monkeypatch.setattr(evo_db, "_topic_rows", lambda s, tid: [(SimpleNamespace(), p) for p in papers])
    monkeypatch.setattr(evo_db, "topic_eras", lambda topic, rows: [(2019, 2020), (2021, 2023), (2024, 2025)])
    monkeypatch.setattr(evo_db, "topic_timeline", lambda s, t: {"years": [
        {"year": p.year, "papers": [node(p)]} for p in milestones]})
    monkeypatch.setattr(evo_db, "topic_gaps", lambda s, t: {"themes": [{
        "label": "Memory at inference", "status": "persisting", "first_year": 2021, "last_year": 2024,
        "examples": [{"sentence": "Merging adapters at inference remains costly.", "paper": node(papers[1]),
                      "stated_by": node(papers[2])}],
        "fixed_by": [node(papers[2])]}]})
    monkeypatch.setattr(evo_db, "reading_path", lambda s, t, u, n: {
        "survey": node(papers[3]) | {"why": "Start here."},
        "steps": [node(p) | {"why": None} for p in milestones]})
    topic = SimpleNamespace(id=uuid4(), slug="peft", name="Parameter-efficient fine-tuning", built_at=BUILT)
    session = SimpleNamespace(get=lambda model, pid: by_id.get(pid))
    return topic, session, papers


def test_the_outline_follows_the_map(fake_map):
    topic, session, papers = fake_map
    registry = review.Registry()
    sections = review.outline(session, topic, registry)
    assert [s.key for s in sections] == ["overview", "history", "era-2019", "era-2021", "era-2024", "approaches",
                                         "gaps", "reading"]
    era = sections[3]
    assert era.title == "2021–2023" and era.papers == [papers[1].id] and "LoRA" in era.task
    assert era.evidence[0][2] == "LoRA does X."
    gaps = sections[6]
    assert "persisting" in gaps.evidence[0][1] and gaps.evidence[0][2].startswith("Merging adapters")
    assert sections[-1].markdown.splitlines()[0].startswith("1. **Survey** (2024): Start here. [")
    assert len(registry.papers) == 4   # each paper numbered once


def test_a_map_review_end_to_end_with_a_fake_model(fake_map):
    topic, session, papers = fake_map
    calls, saved = [], []

    def chat(messages, max_tokens):
        prompt = messages[-1]["content"]
        calls.append(prompt)
        if "opening overview" in prompt:
            return "The field moved from adapters to low-rank updates [2] and [99].", 100, 40
        listed = sorted({int(n) for n in re.findall(r"^\[(\d+)\]", prompt, flags=re.M)})
        return f"<think>hmm</think>Claim one [{listed[0]}]. Invented [42].", 500, 120

    def retrieve(session, topic, question, sections, **kw):
        assert kw["paper_ids"] and kw["with_abstracts"] is False
        pid = kw["paper_ids"][0]
        return [SimpleNamespace(paper_id=str(pid), named_method=None, section_type="method", heading="Method",
                                text="Passage text.")]

    result = review.write_map_review(session, topic, chat, saved.append, retrieve)
    assert len(calls) == 6     # 3 eras, approaches, open problems, then the overview
    assert result.removed == 6  # each [42], and the overview's [99]
    md = result.markdown
    assert md.startswith("# Parameter-efficient fine-tuning: a literature review")
    assert "## How the field developed" in md and "### 2021–2023" in md and "## References" in md
    assert "<think>" not in md and "[42]" not in md and "[99]" not in md
    cited = [s["n"] for s in result.sources]
    assert cited == list(range(1, len(cited) + 1))      # renumbered 1..n
    assert md.count("\n[1] ") == 1 and all(f"[{n}] " in md for n in cited)
    assert any(s.get("progress", {}).get("label", "").startswith("Writing") for s in saved)


def test_an_abstracts_review_cites_only_its_results():
    papers = [{"id": "s2-1", "title": "Graph RAG", "abstract": "Graphs help retrieval.", "year": 2024,
               "authors": ["A"], "url": "https://x"},
              {"id": "s2-2", "title": "No abstract", "abstract": None}]

    def chat(messages, max_tokens):
        assert "abstracts only" in messages[-1]["content"]
        return "## Overview\nGraphs help [1]. Not real [7].", 10, 10

    result = review.write_abstracts_review("graph rag", papers, chat, lambda f: None)
    assert result.removed == 1 and len(result.sources) == 1
    assert "### Overview" in result.markdown and "from the abstracts of 1 search results" in result.markdown


# ── routes ───────────────────────────────────────────────────────────


@pytest.fixture
def env(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    for model in (User, UserSession, SavedList, EvoTopic, LitReview):
        model.__table__.create(engine)
    Session = sessionmaker(bind=engine)

    def session():
        s = Session()
        try:
            yield s
        finally:
            s.close()
    redis = FakeRedis()
    app.dependency_overrides[get_db] = session
    app.dependency_overrides[get_redis] = lambda: redis
    with Session() as s:
        s.execute(EvoTopic.__table__.insert().values(id=uuid4(), slug="peft", name="PEFT", status="ready",
                                                     aliases=None, seeds=None, config=None, built_at=BUILT))
        s.commit()
    queued = []
    monkeypatch.setattr(review_routes, "_queue", queued.append)
    monkeypatch.setattr("athena.evolution.search.find_topic_by_content", lambda s, q: (None, {}))
    yield Session, queued
    app.dependency_overrides.clear()


@pytest.mark.real_auth
def test_starting_reviews_from_a_map_or_a_query(env):
    Session, queued = env
    admin = TestClient(app)
    assert setup_admin(admin).status_code == 201
    started = admin.post("/api/v1/reviews", json={"topic_slug": "peft"})
    assert started.status_code == 202
    body = started.json()
    assert body["mode"] == "map" and body["topic"]["slug"] == "peft" and body["status"] == "queued"
    assert queued == [body["id"]]
    assert admin.post("/api/v1/reviews", json={"query": "graph rag"}).status_code == 409   # one at a time
    with Session() as s:
        s.get(LitReview, UUID(body["id"])).status = "done"
        s.commit()
    other = admin.post("/api/v1/reviews", json={"query": "graph rag"}).json()
    assert other["mode"] == "abstracts" and other["topic"] is None
    assert {r["id"] for r in admin.get("/api/v1/reviews").json()["reviews"]} == {other["id"], body["id"]}
    assert admin.post("/api/v1/reviews", json={}).status_code == 422
    assert admin.post("/api/v1/reviews", json={"topic_slug": "nope"}).status_code == 404


@pytest.mark.real_auth
def test_reviews_are_private_exportable_and_stale_ones_fail(env):
    Session, _ = env
    admin = TestClient(app)
    setup_admin(admin)
    _, bo = make_user(admin)
    rid = admin.post("/api/v1/reviews", json={"topic_slug": "peft"}).json()["id"]
    assert bo.get(f"/api/v1/reviews/{rid}").status_code == 404
    assert bo.delete(f"/api/v1/reviews/{rid}").status_code == 404
    assert admin.get(f"/api/v1/reviews/{rid}/export", params={"format": "md"}).status_code == 409
    with Session() as s:
        r = s.get(LitReview, UUID(rid))
        r.progress = {"at": (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()}
        s.commit()
    stale = admin.get(f"/api/v1/reviews/{rid}").json()
    assert stale["status"] == "failed" and "worker stopped" in stale["error"]
    with Session() as s:
        r = s.get(LitReview, UUID(rid))
        r.status, r.markdown = "done", "# PEFT: a literature review\n\nText [1]."
        r.sources = [{"n": 1, "title": "LoRA", "year": 2021, "authors": ["E. Hu"], "arxiv_id": "2106.09685",
                      "url": "https://arxiv.org/abs/2106.09685"}]
        s.commit()
    md = admin.get(f"/api/v1/reviews/{rid}/export", params={"format": "md"})
    assert md.text.startswith("# PEFT")
    assert 'filename="peft--a-literature-review.md"' in md.headers["content-disposition"]
    assert "@misc{hu2021lora," in admin.get(f"/api/v1/reviews/{rid}/export", params={"format": "bib"}).text
    assert admin.delete(f"/api/v1/reviews/{rid}").status_code == 204


@pytest.mark.real_auth
def test_a_review_spends_the_daily_allowance(env, monkeypatch):
    monkeypatch.setenv("LIMIT_LIT_REVIEW_PER_DAY", "1")
    Session, _ = env
    admin = TestClient(app)
    setup_admin(admin)
    _, bo = make_user(admin)
    first = bo.post("/api/v1/reviews", json={"topic_slug": "peft"})
    assert first.status_code == 202
    with Session() as s:
        s.get(LitReview, UUID(first.json()["id"])).status = "done"
        s.commit()
    assert bo.post("/api/v1/reviews", json={"topic_slug": "peft"}).status_code == 429


def test_the_worker_runs_a_saved_review_and_records_failure(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    for model in (User, EvoTopic, LitReview):
        model.__table__.create(engine)
    Session = sessionmaker(bind=engine)
    monkeypatch.setattr("athena.database.db.SessionLocal", Session)
    with Session() as s:
        user = User(id=uuid4(), email="a@b.c", display_name="A", password_hash="-", role="admin")
        s.add(user)
        s.flush()
        ok, bad = LitReview(user_id=user.id, query="graph rag", title="t", mode="abstracts"), \
            LitReview(user_id=user.id, query="graph rag", title="t", mode="map")
        s.add_all([ok, bad])
        s.commit()
        ok_id, bad_id = ok.id, bad.id
    papers = [{"id": "1", "title": "Graph RAG", "abstract": "Graphs help.", "year": 2024}]
    assert review.run(ok_id, chat=lambda m, t: ("Graphs help [1].", 5, 5), papers=papers) == {
        "status": "done", "citations_removed": 0}
    assert review.run(bad_id, chat=lambda m, t: ("", 0, 0))["status"] == "failed"   # no map
    with Session() as s:
        done, failed = s.get(LitReview, ok_id), s.get(LitReview, bad_id)
        assert done.status == "done" and done.sources[0]["title"] == "Graph RAG" and done.finished_at
        assert failed.status == "failed" and "map" in failed.error
    assert review.run(ok_id)["status"] == "done"   # a finished review is not written again
    with patch.object(review, "write_abstracts_review") as never:
        review.run(ok_id)
        never.assert_not_called()
