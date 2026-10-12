"""Tests for proposing a topic from a search (no network; OpenAlex and the 9B are faked)."""
from __future__ import annotations

from athena.evolution import propose as p
from athena.evolution.corpus import relevance
from athena.evolution.openalex import Work


def work(wid: str, title: str, year: int, cited: int, abstract: str | None = None, field: str = "Computer Science",
         work_type: str = "article") -> Work:
    return Work(openalex_id=wid, title=title, year=year, cited_by_count=cited, abstract=abstract, field_name=field,
                work_type=work_type)


class FakeOpenAlex:
    def __init__(self, title_hits, semantic_hits=(), counts=(("Computer Science", 90), ("Engineering", 10))):
        self.title_hits, self.semantic_hits, self.counts = list(title_hits), list(semantic_hits), list(counts)
        self.spent_usd = 0.0
        self.calls = []

    def field_counts(self, terms):
        self.calls.append(("fields", tuple(terms)))
        self.spent_usd += 0.001
        return self.counts

    def search_works(self, terms, limit, fields=None, in_title=False):
        self.calls.append(("title", tuple(terms), tuple(fields or ()), in_title))
        self.spent_usd += 0.001
        return self.title_hits[:limit]

    def semantic_search(self, query, limit=50):
        self.calls.append(("semantic", query))
        self.spent_usd += 0.001
        return self.semantic_hits


class TestText:
    def test_variants(self):
        assert p.variants("Mixture  of Experts") == ["mixture of experts", "mixture-of-experts"]
        assert p.variants("retrieval-augmented generation") == [
            "retrieval-augmented generation", "retrieval augmented generation"]

    def test_name_and_slug(self):
        assert p.topic_name("object tracking") == "Object tracking"
        assert p.topic_name("LoRA") == "LoRA"
        assert p.slugify("Mixture of Experts (MoE)!") == "mixture-of-experts-moe"

    def test_lint_drops_generic_words_quotes_acronyms_and_singularises(self):
        assert p.lint_keywords(["Fine-tuning", "MoE", "Graph Attention Networks", "transformer", "x"], "mixture") == [
            '"moe"', "graph attention network"]
        # The query's own generic words stay.
        assert p.lint_keywords(["transformers"], "transformers") == ["transformer"]

    def test_quoted_keywords_match_whole_words_only(self):
        assert relevance("MOT17 results", None, ['"mot"']) == 0.0
        assert relevance("Motion forecasting", None, ['"mot"']) == 0.0
        assert relevance("A new MOT benchmark", None, ['"mot"']) == 1.0
        assert relevance("MoEs at scale", None, ['"moe"']) == 1.0
        assert relevance("Motion forecasting", None, ["mot"]) == 1.0  # unquoted: word start, as before

    def test_acronyms_need_two_papers_and_capitals(self):
        texts = ["Sparse mixture of experts (MoE) layers", "A Mixture-of-Experts (MoE) model",
                 "mixture of experts (gate) networks", "Mixtures of Experts (HME)."]
        assert p.acronyms("mixture of experts", texts) == ["moe"]
        assert p.acronyms("speculative decoding", ["speculative decoding (SD)"] * 2) == []  # two letters need 3
        assert p.acronyms("speculative decoding", ["speculative decoding (SD)"] * 3) == ["sd"]

    def test_inflections_become_keywords_and_other_phrases_are_offered(self):
        texts = ["Hierarchical mixtures of experts"] * 3 + ["the number of experts grows"] * 3 + \
                ["deep neural networks"] * 3 + ["social networks"] * 3
        inflections, offered = p.phrases("mixture of experts", texts, ["mixture of expert"])
        assert inflections == ["mixtures of experts"]
        assert offered == ["number of experts"]
        _, offered = p.phrases("graph neural networks", texts, ["graph neural network"])
        assert offered == ["social networks"]  # "deep" is generic


class TestCandidatesAndAnchors:
    def test_fields_cover_80_percent_at_most_three(self):
        assert p.pick_fields([("Biochemistry, Genetics and Molecular Biology", 85), ("Computer Science", 15)]) == [
            "Biochemistry, Genetics and Molecular Biology"]
        assert p.pick_fields([("A", 40), ("B", 30), ("C", 20), ("D", 10)]) == ["A", "B", "C"]
        assert p.pick_fields([]) == ["Computer Science"]

    def test_duplicate_records_are_grouped_within_two_years(self):
        hits = [work("W1", "Fast R-CNN detector design", 2015, 900), work("W2", "Fast R-CNN detector design", 2016, 50),
                work("W3", "Fast R-CNN detector design", 2009, 5)]
        [c] = [c for c in p.group_candidates(hits, [], "detector", ["Computer Science"]) if c.openalex_id == "W1"]
        assert c.alt_ids == ["W2"] and c.year == 2015 and c.title_match

    def test_out_of_field_and_paratext_are_dropped(self):
        hits = [work("W1", "Power transformers", 2000, 50, field="Engineering"),
                work("W2", "Erratum: transformers", 2020, 50, work_type="erratum"),
                work("W3", "Vision transformers", 2021, 50)]
        ids = [c.openalex_id for c in p.group_candidates([], hits, "transformers", ["Computer Science"])]
        assert ids == ["W3"]

    def test_anchors_spread_over_the_years_with_one_survey(self):
        cands = [p.Candidate(f"W{i}", f"T{i}", y, cites, "method", title_match=True)
                 for i, (y, cites) in enumerate([(1994, 2600), (1995, 300), (2012, 590), (2017, 250),
                                                 (2021, 400), (2024, 270)])]
        cands.append(p.Candidate("W9", "A survey", 2012, 560, "survey", title_match=True))
        anchors = p.pick_anchors(cands)
        assert anchors[:3] == ["W0", "W2", "W4"]  # best of each third, not the three most cited
        assert anchors[-1] == "W9" and len(anchors) == 4

    def test_semantic_only_candidates_are_not_anchors_when_titles_match(self):
        cands = [p.Candidate("W1", "Object tracking", 2006, 100, "method", title_match=True),
                 p.Candidate("W2", "Tracking objects as points", 2020, 9000, "method", semantic=True)]
        assert p.pick_anchors(cands) == ["W1"]


class TestPropose:
    def test_propose_end_to_end(self):
        title_hits = [
            work("W1", "Hierarchical Mixtures of Experts and the EM Algorithm", 1994, 2669,
                 "Hierarchical mixtures of experts (HME) ..."),
            work("W2", "Outrageously Large Neural Networks: The Sparsely-Gated Mixture-of-Experts Layer", 2017, 250,
                 "We introduce a Sparsely-Gated Mixture-of-Experts (MoE) layer."),
            work("W3", "Switch Transformers with mixture of experts", 2021, 900, "mixture of experts (MoE) routing"),
            work("W4", "Mixture of experts: a literature survey", 2012, 560),
        ]
        client = FakeOpenAlex(title_hits, [work("W5", "Adaptive Mixtures of Local Experts", 1991, 5256)])
        out = p.propose("mixture of experts", client)
        assert out["fields"] == ["Computer Science"] and out["cost_usd"] == 0.003
        assert client.calls[1] == ("title", ("mixture of experts", "mixture-of-experts"), ("Computer Science",),
                                   True)
        assert '"moe"' in out["keywords"] and "mixture of expert" in out["keywords"]
        assert set(out["anchors"]) >= {"W1", "W3"} and "W4" in out["anchors"]  # W4: the one survey
        assert [c["openalex_id"] for c in out["candidates"]][0] == "W5"  # most cited first
        assert all("abstract" not in c for c in out["candidates"])
        assert "_abstracts" not in p.public(out)


class FakeClassifier:
    model = "fake-9b"

    def __init__(self, answer):
        self.answer = answer
        self.prompts = []

    def ask(self, prompt, schema, name, think=False, max_tokens=None):
        self.prompts.append((prompt, schema))
        return self.answer


PROPOSAL = {
    "query": "object tracking", "name": "Object tracking", "aliases": ["object tracking"],
    "keywords": ["object tracking", '"mot"'], "anchors": ["W1", "W2"],
    "candidates": [{"openalex_id": f"W{i}", "title": f"Paper {i}", "year": 2000 + i, "citations": i}
                   for i in range(1, 6)],
    "_abstracts": {"W1": "We track objects."},
}


class TestRefine:
    def test_the_9b_picks_by_number_and_its_keywords_are_linted(self):
        clf = FakeClassifier({"name": "Visual object tracking", "description": "Following objects across frames.",
                              "aliases": ["visual tracking", "MOT"], "keywords": ["Siamese tracker", "deep learning",
                                                                                  "correlation filters"],
                              "anchors": [3, 5, 99, 3]})
        out = p.refine(PROPOSAL, clf)
        assert out["anchors"] == ["W3", "W5"] and out["anchors_from_model"]
        assert out["keywords"] == ["object tracking", '"mot"', "siamese tracker", "correlation filter"]
        assert out["name"] == "Visual object tracking"
        assert "visual tracking" in out["aliases"]
        prompt, schema = clf.prompts[0]
        assert "1. Paper 1 (2001, 1 citations)\n   We track objects." in prompt
        assert schema["properties"]["anchors"]["items"]["enum"] == [1, 2, 3, 4, 5]

    def test_too_few_anchors_or_no_answer_keep_the_rules(self):
        out = p.refine(PROPOSAL, FakeClassifier({"anchors": [4], "keywords": [], "name": "", "aliases": []}))
        assert out["anchors"] == ["W1", "W2"] and not out["anchors_from_model"]
        assert out["name"] == "Object tracking"
        assert p.merge_refinement(PROPOSAL, None)["keywords"] == ["object tracking", '"mot"']


class FakeRedis:
    def __init__(self):
        self.store = {}

    def setex(self, key, ttl, value):
        self.store[key] = value

    def get(self, key):
        return self.store.get(key)


class TestStorage:
    def test_round_trip_and_bad_ids(self):
        r = FakeRedis()
        p.save(r, {"id": "c" * 32, "x": 1})
        assert p.load(r, "c" * 32) == {"id": "c" * 32, "x": 1}
        assert p.load(r, "../etc") is None

    def test_run_refinement_skips_cancelled_and_stores_failures(self, monkeypatch):
        import athena.evolution.gpu as gpu

        r = FakeRedis()
        p.save(r, {"id": "d" * 32, "refine": {"status": "cancelled"}})
        assert p.run_refinement("d" * 32, r) == "skipped"

        def broken_server():
            raise RuntimeError("out of VRAM")

        monkeypatch.setattr(gpu, "chat_server", broken_server)
        p.save(r, PROPOSAL | {"id": "e" * 32, "refine": {"status": "pending", "deadline": 9e9}})
        assert p.run_refinement("e" * 32, r) == "failed"
        assert p.load(r, "e" * 32)["refine"] == {"status": "failed", "error": "out of VRAM"}


class TestBuildSearchTopic:
    def setup_method(self):
        self.statuses = []
        self.builds = []

    def patch(self, monkeypatch, embed):
        import athena.evolution.build as build
        import athena.evolution.gpu as gpu

        def fake_build(slug, stage_status="building", status_after="ready"):
            self.builds.append((stage_status, status_after))
            return {"papers": 10, "membership": "semantic" if len(self.builds) > 1 else "keywords"}

        monkeypatch.setattr(build, "build_topic", fake_build)
        monkeypatch.setattr(build.db, "set_topic_status",
                            lambda slug, status, detail=None, stats=None: self.statuses.append((status, stats)))
        monkeypatch.setattr(gpu, "embed_abstracts", embed)
        return build

    def test_map_first_then_rebuilt_with_embeddings(self, monkeypatch):
        build = self.patch(monkeypatch, lambda: 42)
        out = build.build_search_topic("object-tracking")
        assert self.builds == [("building", "refining"), ("refining", "ready")]
        assert out["membership"] == "semantic" and out["abstracts_embedded"] == 42
        assert self.statuses[-1][0] == "ready" and self.statuses[-1][1]["refine"] == "done"

    def test_no_embedder_keeps_the_first_map(self, monkeypatch):
        def no_gpu():
            raise RuntimeError("Model file not found")

        build = self.patch(monkeypatch, no_gpu)
        out = build.build_search_topic("object-tracking")
        assert self.builds == [("building", "refining")]
        assert out["membership"] == "keywords"
        status, stats = self.statuses[-1]
        assert status == "ready" and stats["refine"].startswith("skipped (Model file not found")
