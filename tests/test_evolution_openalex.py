"""Tests for the OpenAlex client (mocked transport; no network)."""
from __future__ import annotations

import httpx
import pytest

from athena.evolution.openalex import (
    OpenAlexBudgetError, OpenAlexClient, Work, arxiv_id_from, arxiv_year, reconstruct_abstract, search_expression,
)


def raw_work(n: int, **extra) -> dict:
    return {"id": f"https://openalex.org/W{n}", "display_name": f"Paper {n}", "publication_year": 2020,
            "cited_by_count": n, "referenced_works": [], **extra}


def make_client(handler, tmp_path=None) -> tuple[OpenAlexClient, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    http = httpx.Client(base_url="https://api.openalex.org", transport=httpx.MockTransport(record))
    client = OpenAlexClient(api_key="", mailto="", cache_dir=str(tmp_path) if tmp_path else "", http=http)
    return client, seen


class TestParsing:
    def test_reconstruct_abstract(self):
        assert reconstruct_abstract({"world": [1], "Hello": [0], "again": [2]}) == "Hello world again"
        assert reconstruct_abstract(None) is None

    def test_arxiv_id_from_doi_and_locations(self):
        assert arxiv_id_from({"doi": "https://doi.org/10.48550/arxiv.2106.09685"}) == "2106.09685"
        located = {"locations": [{"landing_page_url": "http://arxiv.org/abs/1504.08083v2"}]}
        assert arxiv_id_from(located) == "1504.08083"
        assert arxiv_id_from({"doi": "https://doi.org/10.1109/cvpr.2014.81"}) is None

    def test_arxiv_year(self):
        assert arxiv_year("2106.09685") == 2021
        assert arxiv_year("cs/0102001") == 2001
        assert arxiv_year("hep-th/9901001") == 1999
        assert arxiv_year(None) is None

    def test_work_from_api(self):
        work = Work.from_api(raw_work(
            7,
            doi="https://doi.org/10.48550/arxiv.1311.2524",
            referenced_works=["https://openalex.org/W1"],
            authorships=[{"author": {"display_name": "Ross Girshick"}}],
            primary_topic={"display_name": "Object detection", "field": {"display_name": "Computer Science"}},
            open_access={"is_oa": True, "oa_url": "https://arxiv.org/pdf/1311.2524"},
        ))
        assert work.openalex_id == "W7"
        assert work.doi == "10.48550/arxiv.1311.2524"
        assert work.arxiv_id == "1311.2524"
        assert work.referenced_works == ["W1"]
        assert work.authors == ["Ross Girshick"]
        assert work.field_name == "Computer Science"
        assert work.is_oa and work.oa_pdf_url == "https://arxiv.org/pdf/1311.2524"


class TestClient:
    def test_citing_works_pages_until_a_short_page(self):
        def handler(request):
            page = int(request.url.params["page"])
            per_page = int(request.url.params["per-page"])
            count = per_page if page == 1 else 3
            return httpx.Response(200, json={"results": [raw_work(page * 1000 + i) for i in range(count)]},
                                  headers={"x-ratelimit-cost-usd": "0.0001"})

        client, seen = make_client(handler)
        works = client.citing_works("W1", limit=500)
        assert len(works) == 203
        assert len(seen) == 2
        assert seen[0].url.params["filter"] == "cites:W1"
        assert client.spent_usd == pytest.approx(0.0002)

    def test_get_works_batches_one_hundred_ids_per_call(self):
        client, seen = make_client(lambda r: httpx.Response(200, json={"results": []}))
        client.get_works([f"W{i}" for i in range(150)])
        assert len(seen) == 2
        assert seen[0].url.params["filter"].startswith("openalex:W0|W1|")

    def test_missing_work_returns_none(self):
        client, _ = make_client(lambda r: httpx.Response(404, json={}))
        assert client.get_work("W404") is None

    def test_responses_are_cached_on_disk(self, tmp_path):
        client, seen = make_client(lambda r: httpx.Response(200, json=raw_work(5)), tmp_path)
        assert client.get_work("W5").openalex_id == "W5"
        assert client.get_work("W5").openalex_id == "W5"
        assert len(seen) == 1
        assert client.cache_hits == 1

    def test_budget_exhaustion_raises_without_retrying(self):
        client, seen = make_client(lambda r: httpx.Response(429, json={}, headers={"x-ratelimit-remaining-usd": "0"}))
        with pytest.raises(OpenAlexBudgetError):
            client.get_works(["W1"])
        assert len(seen) == 1


class TestSearch:
    def test_search_expression_quotes_phrases_and_drops_commas(self):
        assert search_expression(["Mixture of Experts", "mixture-of-experts", "MoE", "moe", "a, b"]) == \
            '"mixture of experts" OR "mixture-of-experts" OR moe OR "a b"'

    def test_search_works_pages_most_cited_first_with_field_ids(self):
        def handler(request):
            page = int(request.url.params["page"])
            count = 200 if page == 1 else 50
            return httpx.Response(200, json={"results": [raw_work(page * 1000 + i) for i in range(count)]})

        client, seen = make_client(handler)
        works = client.search_works(["object tracking"], limit=1000,
                                    fields=["Computer Science", "Biochemistry, Genetics and Molecular Biology"])
        assert len(works) == 250 and len(seen) == 2
        assert seen[0].url.params["filter"] == \
            'title_and_abstract.search:"object tracking",primary_topic.field.id:17|13'
        assert seen[0].url.params["sort"] == "cited_by_count:desc"

    def test_title_search_and_no_fields(self):
        client, seen = make_client(lambda r: httpx.Response(200, json={"results": []}))
        assert client.search_works(["lora"], limit=10, in_title=True) == []
        assert seen[0].url.params["filter"] == "title.search:lora"

    def test_semantic_search_failure_returns_nothing(self):
        client, _ = make_client(lambda r: httpx.Response(400, json={"error": "bad"}))
        assert client.semantic_search("speculative decoding") == []

    def test_semantic_search_params(self):
        client, seen = make_client(lambda r: httpx.Response(200, json={"results": [raw_work(1)]}))
        assert [w.openalex_id for w in client.semantic_search("speculative decoding")] == ["W1"]
        assert seen[0].url.params["search.semantic"] == "speculative decoding"
        assert seen[0].url.params["per-page"] == "50"
        assert "filter" not in seen[0].url.params  # semantic search refuses field filters

    def test_errors_do_not_carry_the_api_key(self):
        http = httpx.Client(base_url="https://api.openalex.org",
                            transport=httpx.MockTransport(lambda r: httpx.Response(400, json={"message": "bad"})))
        client = OpenAlexClient(api_key="SECRET", mailto="", cache_dir="", http=http)
        with pytest.raises(httpx.HTTPStatusError) as err:
            client.get_works(["W1"])
        assert "SECRET" not in str(err.value) and "bad" in str(err.value)

    def test_field_counts_largest_first(self):
        groups = [{"key": "https://openalex.org/fields/17", "key_display_name": "Computer Science", "count": 643},
                  {"key": "https://openalex.org/fields/13",
                   "key_display_name": "Biochemistry, Genetics and Molecular Biology", "count": 5914},
                  {"key": "unknown", "key_display_name": "", "count": 3}]
        client, seen = make_client(lambda r: httpx.Response(200, json={"group_by": groups}))
        assert client.field_counts(["protein structure prediction"]) == [
            ("Biochemistry, Genetics and Molecular Biology", 5914), ("Computer Science", 643)]
        assert seen[0].url.params["group_by"] == "primary_topic.field.id"
