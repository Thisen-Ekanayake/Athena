"""Tests for the research search subsystem (athena.search) and POST /api/v1/search."""
from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient

from athena.api.main import app
from athena.search import merger, semantic_scholar


# ────────────────────────────────────────────────────────────────────────
# merger.py
# ────────────────────────────────────────────────────────────────────────


def _paper(title: str, *, source: str = "local", citations: int = 0, paper_id: str | None = None) -> dict:
    return {
        "id": paper_id or f"{source}-{title}",
        "title": title,
        "abstract": "abstract text",
        "url": "https://example.com",
        "year": 2024,
        "authors": ["Author A"],
        "citation_count": citations,
        "score": 0.9 if source == "local" else None,
        "source": source,
    }


class TestMerger:
    def test_dedupe_keeps_local_version(self):
        local = [_paper("Attention Is All You Need", source="local", paper_id="local-1")]
        live = [
            _paper("attention is all you need!", source="semantic_scholar", paper_id="s2-1", citations=50000),
        ]
        merged = merger.merge_results(local, live, max_total=10)

        assert len(merged) == 1
        assert merged[0]["id"] == "local-1"
        assert merged[0]["source"] == "local"

    def test_unique_live_appended_after_local(self):
        local = [_paper("Paper A", source="local", paper_id="local-A")]
        live = [
            _paper("Paper B", source="semantic_scholar", paper_id="s2-B", citations=10),
            _paper("Paper C", source="semantic_scholar", paper_id="s2-C", citations=50),
        ]
        merged = merger.merge_results(local, live, max_total=10)

        assert [p["id"] for p in merged] == ["local-A", "s2-C", "s2-B"]

    def test_max_total_respected(self):
        local = [_paper(f"Local {i}", source="local", paper_id=f"local-{i}") for i in range(5)]
        live = [
            _paper(f"Live {i}", source="semantic_scholar", paper_id=f"s2-{i}", citations=i)
            for i in range(10)
        ]
        merged = merger.merge_results(local, live, max_total=6)

        assert len(merged) == 6
        assert sum(1 for p in merged if p["source"] == "local") == 5
        assert sum(1 for p in merged if p["source"] == "semantic_scholar") == 1

    def test_punctuation_insensitive_dedupe(self):
        local = [_paper("Deep Learning: A Review", source="local", paper_id="local-1")]
        live = [_paper("deep learning  a review!!!", source="semantic_scholar", paper_id="s2-1")]
        merged = merger.merge_results(local, live, max_total=10)

        assert len(merged) == 1
        assert merged[0]["id"] == "local-1"

    def test_empty_inputs(self):
        assert merger.merge_results([], [], max_total=10) == []
        assert merger.merge_results([_paper("Solo", source="local")], [], max_total=10)[0]["title"] == "Solo"

    def test_zero_max_total(self):
        local = [_paper("X", source="local")]
        assert merger.merge_results(local, [], max_total=0) == []

    def test_keep_order_takes_the_sources_ranking_over_citations(self):
        s2 = [_paper("Old classic", source="semantic_scholar", citations=900),
              _paper("Other", source="semantic_scholar", citations=40)]
        arxiv = [_paper("HelaBERT", source="arxiv", citations=0), _paper("old classic", source="arxiv")]
        live = merger.interleave(s2, arxiv)
        assert [p["title"] for p in live] == ["Old classic", "HelaBERT", "Other", "old classic"]
        assert [p["title"] for p in merger.merge_results([], live, max_total=2, keep_order=True)] == \
            ["Old classic", "HelaBERT"]
        assert "HelaBERT" not in [p["title"] for p in merger.merge_results([], live, max_total=2)]


# ────────────────────────────────────────────────────────────────────────
# semantic_scholar.py
# ────────────────────────────────────────────────────────────────────────


def _ss_payload(papers: list[dict]) -> dict:
    return {"data": papers}


def _live(*responses: httpx.Response | Exception):
    """Patch live search's Semantic Scholar client to answer from ``responses``, in turn."""
    from athena.core.semantic_scholar import SemanticScholarClient
    answers = iter(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        answer = next(answers)
        if isinstance(answer, Exception):
            raise answer
        return answer

    def make(**kwargs):
        http = httpx.Client(base_url="https://api.semanticscholar.org/graph/v1", transport=httpx.MockTransport(handler))
        return SemanticScholarClient(api_key="k", http=http, min_interval=0, **kwargs)

    return patch.object(semantic_scholar, "SemanticScholarClient", side_effect=make)


class TestSemanticScholar:
    def test_filters_missing_abstracts(self):
        payload = _ss_payload([
            {
                "paperId": "p1",
                "title": "Has abstract",
                "abstract": "Some abstract here.",
                "year": 2024,
                "authors": [{"name": "Jane Doe"}, {"name": "John Roe"}],
                "citationCount": 12,
                "url": "https://example.com/p1",
            },
            {
                "paperId": "p2",
                "title": "Missing abstract",
                "abstract": None,
                "year": 2023,
                "authors": [],
                "citationCount": 0,
            },
            {
                "paperId": "p3",
                "title": "Empty abstract",
                "abstract": "   ",
                "year": 2023,
                "authors": [],
                "citationCount": 0,
            },
        ])
        with _live(httpx.Response(200, json=payload)):
            results = semantic_scholar.search_semantic_scholar("transformers", limit=10)

        assert len(results) == 1
        assert results[0]["id"] == "p1"
        assert results[0]["source"] == "semantic_scholar"
        assert results[0]["authors"] == ["Jane Doe", "John Roe"]
        assert results[0]["citation_count"] == 12

    def test_http_error_returns_empty_list(self):
        with patch.object(semantic_scholar, "PATIENCE", 0), _live(httpx.ConnectError("nope")):
            results = semantic_scholar.search_semantic_scholar("anything")
        assert results == []

    def test_non_200_response_returns_empty_list(self):
        with patch.object(semantic_scholar, "PATIENCE", 0), _live(httpx.Response(500, json={})):
            results = semantic_scholar.search_semantic_scholar("anything")
        assert results == []

    def test_a_rate_limit_is_waited_out(self):
        payload = _ss_payload([{"paperId": "p1", "title": "LoRA", "abstract": "Low-rank adapters.", "authors": []}])
        with patch.object(semantic_scholar, "PATIENCE", 5), \
                _live(httpx.Response(429, json={}), httpx.Response(200, json=payload)):
            results = semantic_scholar.search_semantic_scholar("lora")
        assert [r["id"] for r in results] == ["p1"]

    def test_empty_query_returns_empty_list(self):
        assert semantic_scholar.search_semantic_scholar("") == []
        assert semantic_scholar.search_semantic_scholar("   ") == []


# ────────────────────────────────────────────────────────────────────────
# POST /api/v1/search
# ────────────────────────────────────────────────────────────────────────


@pytest.fixture
def client():
    return TestClient(app)


class TestResearchSearchEndpoint:
    def test_happy_path(self, client):
        local = [_paper("Paper A", source="local", paper_id="local-A")]
        live = [_paper("Paper B", source="semantic_scholar", paper_id="s2-B", citations=5)]

        with patch("athena.api.routers.search.search_local", return_value=local), \
             patch("athena.api.routers.search.search_semantic_scholar", return_value=live), \
             patch("athena.api.routers.search.search_arxiv", return_value=[]):
            resp = client.post("/api/v1/search", json={"query": "graph neural networks", "limit": 20})

        assert resp.status_code == 200
        body = resp.json()
        assert body["query"] == "graph neural networks"
        assert body["local_count"] == 1
        assert body["live_count"] == 1
        assert len(body["papers"]) == 2
        assert body["papers"][0]["source"] == "local"
        assert "lit_review" not in body  # reviews are written by /reviews now

    def test_an_old_review_flag_is_ignored(self, client):
        with patch("athena.api.routers.search.search_local", return_value=[_paper("Paper A")]), \
             patch("athena.api.routers.search.search_semantic_scholar", return_value=[]), \
             patch("athena.api.routers.search.search_arxiv", return_value=[]):
            resp = client.post("/api/v1/search", json={"query": "topic xyz", "generate_review": True})
        assert resp.status_code == 200 and len(resp.json()["papers"]) == 1

    def test_no_papers(self, client):
        with patch("athena.api.routers.search.search_local", return_value=[]), \
             patch("athena.api.routers.search.search_semantic_scholar", return_value=[]), \
             patch("athena.api.routers.search.search_arxiv", return_value=[]):
            resp = client.post("/api/v1/search", json={"query": "an obscure topic"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["papers"] == []
        assert body["local_count"] == 0
        assert body["live_count"] == 0

    def test_query_too_short_rejected(self, client):
        resp = client.post("/api/v1/search", json={"query": "ab"})
        assert resp.status_code == 422
