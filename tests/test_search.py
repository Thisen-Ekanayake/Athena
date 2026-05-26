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


# ────────────────────────────────────────────────────────────────────────
# semantic_scholar.py
# ────────────────────────────────────────────────────────────────────────


def _ss_payload(papers: list[dict]) -> dict:
    return {"data": papers}


class _FakeResponse:
    def __init__(self, json_data: dict, status_code: int = 200):
        self._json = json_data
        self.status_code = status_code

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "boom",
                request=httpx.Request("GET", "https://api.semanticscholar.org"),
                response=httpx.Response(self.status_code),
            )


class _FakeClient:
    def __init__(self, response: _FakeResponse | Exception):
        self._response = response

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def get(self, url, params=None, headers=None):
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


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
        fake_client = _FakeClient(_FakeResponse(payload))

        with patch.object(semantic_scholar.httpx, "Client", return_value=fake_client):
            results = semantic_scholar.search_semantic_scholar("transformers", limit=10)

        assert len(results) == 1
        assert results[0]["id"] == "p1"
        assert results[0]["source"] == "semantic_scholar"
        assert results[0]["authors"] == ["Jane Doe", "John Roe"]
        assert results[0]["citation_count"] == 12

    def test_http_error_returns_empty_list(self):
        fake_client = _FakeClient(httpx.ConnectError("nope"))
        with patch.object(semantic_scholar.httpx, "Client", return_value=fake_client):
            results = semantic_scholar.search_semantic_scholar("anything")
        assert results == []

    def test_non_200_response_returns_empty_list(self):
        fake_client = _FakeClient(_FakeResponse({}, status_code=500))
        with patch.object(semantic_scholar.httpx, "Client", return_value=fake_client):
            results = semantic_scholar.search_semantic_scholar("anything")
        assert results == []

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
             patch("athena.api.routers.search.generate_lit_review", return_value="A review."):
            resp = client.post(
                "/api/v1/search",
                json={"query": "graph neural networks", "limit": 20, "generate_review": True},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["query"] == "graph neural networks"
        assert body["local_count"] == 1
        assert body["live_count"] == 1
        assert body["lit_review"] == "A review."
        assert len(body["papers"]) == 2
        assert body["papers"][0]["source"] == "local"

    def test_generate_review_false_skips_llm(self, client):
        local = [_paper("Paper A", source="local")]

        with patch("athena.api.routers.search.search_local", return_value=local), \
             patch("athena.api.routers.search.search_semantic_scholar", return_value=[]), \
             patch("athena.api.routers.search.generate_lit_review") as mock_llm:
            resp = client.post(
                "/api/v1/search",
                json={"query": "topic xyz", "generate_review": False},
            )

        assert resp.status_code == 200
        assert resp.json()["lit_review"] is None
        mock_llm.assert_not_called()

    def test_no_papers_no_lit_review(self, client):
        with patch("athena.api.routers.search.search_local", return_value=[]), \
             patch("athena.api.routers.search.search_semantic_scholar", return_value=[]), \
             patch("athena.api.routers.search.generate_lit_review") as mock_llm:
            resp = client.post(
                "/api/v1/search",
                json={"query": "an obscure topic"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["papers"] == []
        assert body["lit_review"] is None
        assert body["local_count"] == 0
        assert body["live_count"] == 0
        mock_llm.assert_not_called()

    def test_query_too_short_rejected(self, client):
        resp = client.post("/api/v1/search", json={"query": "ab"})
        assert resp.status_code == 422

    def test_lit_review_failure_returns_502(self, client):
        local = [_paper("Paper A", source="local")]
        with patch("athena.api.routers.search.search_local", return_value=local), \
             patch("athena.api.routers.search.search_semantic_scholar", return_value=[]), \
             patch("athena.api.routers.search.generate_lit_review", side_effect=RuntimeError("LLM down")):
            resp = client.post("/api/v1/search", json={"query": "neural search"})

        assert resp.status_code == 502
