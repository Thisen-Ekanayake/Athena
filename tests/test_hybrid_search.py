"""Keyword plus meaning search (ROADMAP S3): fusion order, exact names first, the Postgres query, the fallbacks."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from athena.api.deps import get_db
from athena.api.main import app
from athena.core.models import (
    Cluster, ContentCategory, ContentItem, InterestProfile, ItemFeedback, ItemRead, Source, SourceCategory,
    SourceType, UserHighlight, UserNote,
)
from athena.search import hybrid

A, B, C, D = (uuid4() for _ in range(4))


# ── fusion ───────────────────────────────────────────────────────────


def test_fuse_puts_exact_titles_first_then_ranks_by_both_lists():
    semantic = [{"id": A, "similarity": 0.8}, {"id": B, "similarity": 0.7}, {"id": C, "similarity": 0.6}]
    keyword = [{"id": D, "rank": 0.6, "exact": True}, {"id": C, "rank": 0.4, "exact": False}]
    out = hybrid.fuse(semantic, keyword, 10)
    assert [r["id"] for r in out] == [D, C, A, B]   # D names the query; C is in both lists
    assert {r["id"]: r["match"] for r in out} == {D: "exact", C: "both", A: "meaning", B: "meaning"}
    assert out[1]["similarity"] == 0.6 and out[0]["similarity"] is None
    assert len(hybrid.fuse(semantic, keyword, 2)) == 2


def test_title_pattern_is_for_short_queries_and_escapes_punctuation():
    assert hybrid.title_pattern("RT-DETR") == r"\mRT\-DETR\M"
    assert hybrid.title_pattern("low rank  adaptation") == r"\mlow\s+rank\s+adaptation\M"
    assert hybrid.title_pattern("how do retrieval augmented models handle code") is None


def test_the_postgres_query_ranks_full_text_and_flags_exact_titles():
    compiled = hybrid.keyword_statement("YOLOv8", 50, "paper", postgres=True).compile(dialect=postgresql.dialect())
    sql, params = str(compiled), compiled.params
    assert "websearch_to_tsquery(" in sql and "ts_rank_cd(content_items.search_vector" in sql
    assert "content_items.search_vector @@ websearch_to_tsquery(" in sql
    assert "content_items.title ~* " in sql and "ORDER BY exact DESC, rank DESC" in sql
    assert {"english", "YOLOv8", r"\mYOLOv8\M", 32} <= set(params.values())
    assert any(getattr(v, "name", None) == "PAPER" for v in params.values())


# ── the route ────────────────────────────────────────────────────────


@pytest.fixture
def Session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    for model in (Source, Cluster, ContentItem, ItemRead, UserNote, UserHighlight, ItemFeedback, InterestProfile):
        model.__table__.create(engine)
    factory = sessionmaker(bind=engine)
    with factory() as s:
        source_id = uuid4()
        s.execute(Source.__table__.insert().values(id=source_id, name="ArXiv AI", url="https://export.arxiv.org",
                                                   type=SourceType.API, category=SourceCategory.PAPER,
                                                   fetch_config=None))
        for item_id, title, score in ((A, "Adapters for vision transformers", 0.4),
                                      (B, "LoRA: low-rank adaptation of large language models", 0.2),
                                      (C, "Scaling laws for parameter-efficient tuning", 0.3)):
            s.execute(ContentItem.__table__.insert().values(
                id=item_id, source_id=source_id, title=title, url=f"https://example.org/{item_id}", score=score,
                published_at=datetime(2026, 10, 1, tzinfo=timezone.utc), category=ContentCategory.PAPER,
                content_hash=str(item_id), authors=None, extra_data={}, summary=f"About {title.lower()}."))
        s.commit()

    def session():
        db = factory()
        try:
            yield db
        finally:
            db.close()
    app.dependency_overrides[get_db] = session
    yield factory
    app.dependency_overrides.pop(get_db, None)


def test_search_mixes_both_sides_and_says_how_each_matched(Session):
    meaning = [{"id": str(A), "similarity": 0.81, "payload": {}}, {"id": str(C), "similarity": 0.7, "payload": {}}]
    with patch("athena.api.routers.search.embed_query", return_value=[0.1]), \
            patch("athena.api.routers.search._qdrant_search", return_value=meaning):
        body = TestClient(app).get("/api/v1/search", params={"q": "LoRA"}).json()
    assert body["method"] == "hybrid"
    matched = [(i["title"][:4], i["match"]) for i in body["items"]]
    assert matched == [("LoRA", "exact"), ("Adap", "meaning"), ("Scal", "meaning")]
    assert body["items"][1]["similarity"] == 0.81 and body["items"][0]["me"]["read"] is False


def test_keywords_still_answer_when_the_model_server_is_down(Session):
    with patch("athena.api.routers.search.embed_query", side_effect=ConnectionError("no model server")):
        body = TestClient(app).get("/api/v1/search", params={"q": "scaling laws"}).json()
    assert body["method"] == "keyword"
    assert [i["title"] for i in body["items"]] == ["Scaling laws for parameter-efficient tuning"]


def test_research_search_library_side_uses_the_fusion(Session, monkeypatch):
    from athena.search import local
    monkeypatch.setattr(local, "SessionLocal", Session)
    monkeypatch.setattr(local, "embed_query", lambda q: [0.1])
    monkeypatch.setattr(local, "_qdrant_search", lambda vector, limit: [(str(C), 0.7)])
    found = local.search_local("LoRA", limit=5)
    assert [p["title"][:4] for p in found] == ["LoRA", "Scal"]
    assert found[0]["score"] == 0.0 and found[1]["score"] == 0.7
