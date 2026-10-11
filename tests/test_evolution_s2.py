"""Tests for the Semantic Scholar client and corpus augmentation (mocked transport; no network)."""
from __future__ import annotations

import json

import httpx
import pytest

from athena.evolution.config import TopicConfig
from athena.evolution.corpus import Seed, augment_with_s2, same_title, select_corpus
from athena.evolution.openalex import OpenAlexClient, Work
from athena.evolution.semantic_scholar import (
    S2Paper, SemanticScholarAuthError, SemanticScholarClient, lookup_id,
)


def s2_raw(pid: str, title: str, refs: list[dict] = (), arxiv: str | None = None, doi: str | None = None,
           citations: int = 10, abstract: str | None = None) -> dict:
    ext = {k: v for k, v in {"ArXiv": arxiv, "DOI": doi}.items() if v}
    return {"paperId": pid, "externalIds": ext, "title": title, "year": 2023, "citationCount": citations,
            "referenceCount": len(refs), "references": list(refs), "abstract": abstract}


def ref(pid: str, title: str, arxiv: str | None = None, doi: str | None = None) -> dict:
    ext = {k: v for k, v in {"ArXiv": arxiv, "DOI": doi}.items() if v}
    return {"paperId": pid, "externalIds": ext, "title": title, "year": 2021}


def s2_client(papers: dict[str, dict], tmp_path=None, contexts: dict | None = None):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("/paper/batch"):
            ids = json.loads(request.content)["ids"]
            return httpx.Response(200, json=[papers.get(i) for i in ids])
        if request.url.path.endswith("/references"):
            pid = request.url.path.split("/")[-2]
            return httpx.Response(200, json={"offset": 0, "data": (contexts or {}).get(pid, [])})
        return httpx.Response(404, json={})

    http = httpx.Client(base_url="https://api.semanticscholar.org/graph/v1", transport=httpx.MockTransport(handler))
    return SemanticScholarClient(api_key="", cache_dir=str(tmp_path) if tmp_path else "", http=http,
                                 min_interval=0), seen


def oa_client(works_by_doi: dict[str, dict]):
    def handler(request: httpx.Request) -> httpx.Response:
        flt = request.url.params.get("filter", "")
        if flt.startswith("doi:"):
            dois = flt[4:].split("|")
            return httpx.Response(200, json={"results": [works_by_doi[d] for d in dois if d in works_by_doi]})
        return httpx.Response(200, json={"results": []})

    http = httpx.Client(base_url="https://api.openalex.org", transport=httpx.MockTransport(handler))
    return OpenAlexClient(api_key="", mailto="", cache_dir="", http=http)


def work(wid: str, title: str, refs=(), arxiv_id=None, doi=None, year=2022) -> Work:
    return Work(openalex_id=wid, title=title, year=year, referenced_works=list(refs), arxiv_id=arxiv_id, doi=doi,
                field_name="Computer Science", cited_by_count=5)


class TestClient:
    def test_lookup_id_prefers_arxiv_then_doi_then_mag(self):
        assert lookup_id("2106.09685", "10.1/x", "W1") == "ARXIV:2106.09685"
        assert lookup_id(None, "10.1/x", "W1") == "DOI:10.1/x"
        assert lookup_id(None, None, "W2194775991") == "MAG:2194775991"
        assert lookup_id(None, None, "W4378509449") is None  # created by OpenAlex, not inherited from MAG

    def test_batch_parses_and_caches_per_paper(self, tmp_path):
        papers = {"ARXIV:1": s2_raw("p1", "QLoRA", [ref("r1", "LoRA", arxiv="2106.09685")], citations=5938)}
        client, seen = s2_client(papers, tmp_path)
        out = client.get_papers(["ARXIV:1", "ARXIV:404"])
        assert out["ARXIV:404"] is None
        paper = out["ARXIV:1"]
        assert isinstance(paper, S2Paper) and paper.citation_count == 5938
        assert paper.references[0].arxiv_id == "2106.09685"
        # Both answers are cached, including "not found"; a new id is the only one fetched.
        client.get_papers(["ARXIV:1", "ARXIV:404", "ARXIV:2"])
        assert json.loads(seen[-1].content)["ids"] == ["ARXIV:2"]
        assert len(seen) == 2

    def test_reference_contexts(self):
        contexts = {"p1": [{"contexts": ["LoRA [12] freezes the weights."], "intents": ["methodology"],
                            "isInfluential": True, "citedPaper": ref("r1", "LoRA", arxiv="2106.09685")}]}
        client, _ = s2_client({}, contexts=contexts)
        [ctx] = client.reference_contexts("p1")
        assert ctx.cited.arxiv_id == "2106.09685"
        assert ctx.contexts == ["LoRA [12] freezes the weights."]
        assert ctx.is_influential

    def test_rejected_key_falls_back_to_the_keyless_pool(self, monkeypatch):
        monkeypatch.setattr("athena.evolution.semantic_scholar.MIN_INTERVAL_NO_KEY", 0)

        def handler(request: httpx.Request) -> httpx.Response:
            if "x-api-key" in request.headers:
                return httpx.Response(403, json={"message": "Forbidden"})
            return httpx.Response(200, json=[s2_raw("p1", "QLoRA")])

        http = httpx.Client(base_url="https://api.semanticscholar.org/graph/v1", headers={"x-api-key": "expired"},
                            transport=httpx.MockTransport(handler))
        client = SemanticScholarClient(api_key="expired", cache_dir="", http=http, min_interval=0)
        assert client.get_papers(["ARXIV:1"])["ARXIV:1"].title == "QLoRA"
        assert client.api_key == ""

    def test_403_without_a_key_raises(self):
        http = httpx.Client(base_url="https://api.semanticscholar.org/graph/v1",
                            transport=httpx.MockTransport(lambda r: httpx.Response(403, json={"message": "Forbidden"})))
        client = SemanticScholarClient(api_key="", cache_dir="", http=http, min_interval=0)
        with pytest.raises(SemanticScholarAuthError):
            client.get_papers(["ARXIV:1"])


class TestSameTitle:
    def test_punctuation_and_case_do_not_matter(self):
        assert same_title("QLoRA: Efficient Finetuning of Quantized LLMs",
                          "QLoRA - efficient finetuning of quantized LLMs")

    def test_a_different_paper_does_not_match(self):
        assert not same_title("LoRA: Low-Rank Adaptation of Large Language Models",
                              "LoRA Fine-Tuning of a 3B Code LLM for Algorithmic Efficiency")


class TestAugment:
    def setup_method(self):
        self.lora_title = "LoRA: Low-Rank Adaptation of Large Language Models"
        self.lora = work("W1", self.lora_title, arxiv_id="2106.09685", year=2021)
        self.adapters = work("W2", "Parameter-Efficient Transfer Learning for NLP", arxiv_id="1902.00751", year=2019)
        # Two OpenAlex citers of the seeds, both with references, both citing QLoRA per Semantic Scholar.
        self.c1 = work("W10", "Sparse adapter fine-tuning", ["W1", "W2"], arxiv_id="2401.00001")
        self.c2 = work("W11", "Mixture of LoRA experts for fine-tuning", ["W1", "W2"], arxiv_id="2401.00002")
        # OpenAlex lists no references for this preprint.
        self.c3 = work("W12", "Tiny adapters for fine-tuning", [], arxiv_id="2401.00003")
        qlora_ref = ref("pq", "QLoRA: Efficient Finetuning of Quantized LLMs", arxiv="2305.14314")
        lora_ref = ref("pl", self.lora_title, arxiv="2106.09685")
        adapters_ref = ref("pa", "Parameter-Efficient Transfer Learning for NLP", arxiv="1902.00751")
        self.s2_papers = {
            "ARXIV:2106.09685": s2_raw("pl", self.lora_title, arxiv="2106.09685", citations=30000),
            "ARXIV:1902.00751": s2_raw("pa", "Parameter-Efficient Transfer Learning for NLP", arxiv="1902.00751"),
            "ARXIV:2401.00001": s2_raw("p10", "Sparse adapter fine-tuning", [lora_ref, qlora_ref]),
            "ARXIV:2401.00002": s2_raw("p11", "Mixture of LoRA experts for fine-tuning", [lora_ref, qlora_ref]),
            "ARXIV:2401.00003": s2_raw("p12", "Tiny adapters for fine-tuning", [lora_ref, adapters_ref, qlora_ref]),
            "pq": s2_raw("pq", "QLoRA: Efficient Finetuning of Quantized LLMs", [lora_ref], arxiv="2305.14314",
                         citations=5938),
        }
        self.oa = oa_client({"10.48550/arxiv.2305.14314": {
            "id": "https://openalex.org/W20", "doi": "https://doi.org/10.48550/arxiv.2305.14314",
            "display_name": "QLoRA: Efficient Finetuning of Quantized LLMs", "publication_year": 2023,
            "cited_by_count": 500, "referenced_works": [],
            "primary_topic": {"field": {"display_name": "Computer Science"}}}})
        self.seeds = [Seed(openalex_id="W1", title=self.lora_title, year=2021, arxiv_id="2106.09685"),
                      Seed(openalex_id="W2", year=2019)]
        self.config = TopicConfig(s2_expand_min_citers=2, keywords=["lora", "adapter", "finetun", "fine-tun"])

    def run(self):
        s2, _ = s2_client(self.s2_papers)
        seed_works = {"W1": self.lora, "W2": self.adapters}
        candidates = {w.openalex_id: w for w in (self.c1, self.c2, self.c3)}
        stats = augment_with_s2(s2, self.oa, seed_works, candidates, self.seeds, self.config)
        return seed_works, candidates, stats

    def test_fills_missing_reference_lists(self):
        _, candidates, stats = self.run()
        assert set(candidates["W12"].s2_refs) >= {"W1", "W2"}
        assert stats["s2_refs_added"] >= 2

    def test_adds_papers_the_pool_cites_but_openalex_never_linked(self):
        seed_works, candidates, stats = self.run()
        assert "W20" in candidates
        qlora = candidates["W20"]
        assert qlora.s2_refs == ["W1"]
        assert qlora.citations == 5938
        assert stats["s2_candidates_added"] == 1
        corpus = select_corpus(seed_works, candidates, self.seeds, self.config)
        # QLoRA cites one seed and is cited by three accepted papers, so it joins.
        assert "W20" in corpus.papers
        assert corpus.edge_sources[("W12", "W1")] == "s2"
        assert ("W10", "W1") not in corpus.edge_sources  # OpenAlex had this one

    def test_arxiv_ids_are_filled_from_semantic_scholar(self):
        self.c2.arxiv_id = None
        self.c2.doi = "10.1/mole"
        raw = self.s2_papers.pop("ARXIV:2401.00002")
        self.s2_papers["DOI:10.1/mole"] = raw | {"externalIds": {"ArXiv": "2401.00002"}}
        _, candidates, _ = self.run()
        assert candidates["W11"].arxiv_id == "2401.00002"

    def test_off_topic_outside_papers_are_not_fetched_into_the_pool(self):
        self.config.keywords = ["detection"]
        _, candidates, stats = self.run()
        assert "W20" not in candidates
        assert stats["s2_outside_on_topic"] == 0

    def test_wrong_record_behind_a_doi_is_not_trusted(self):
        # The OpenAlex record carries another paper's title, so Semantic Scholar's data is not attached to it.
        self.c3.title = "Something else entirely about crops"
        _, candidates, stats = self.run()
        assert candidates["W12"].s2_refs == []
        assert stats["s2_title_mismatch"] == 1
