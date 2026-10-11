"""Tests for the research-evolution citation-graph algorithms and milestone scoring."""
from __future__ import annotations

import pytest

from athena.database.evolution import effective_milestone
from athena.evolution import graph as g
from athena.evolution.config import TopicConfig
from athena.evolution.corpus import Corpus, CorpusPaper
from athena.evolution.milestones import (
    PaperScore, classify_kind, era_bounds, named_method, relevance, score_topic, select_milestones,
)
from athena.evolution.openalex import Work

# A(2000) <- B(2001), C(2001) <- D(2002) <- E(2003): knowledge flows A -> {B, C} -> D -> E.
DIAMOND_YEARS = {"A": 2000, "B": 2001, "C": 2001, "D": 2002, "E": 2003}
DIAMOND_EDGES = [("B", "A"), ("C", "A"), ("D", "B"), ("D", "C"), ("E", "D")]


def diamond() -> g.CitationGraph:
    return g.build_graph(DIAMOND_YEARS, DIAMOND_EDGES, DIAMOND_YEARS)


class TestBuildGraph:
    def test_drops_edges_where_the_citing_paper_is_older(self):
        cg = g.build_graph(["old", "new"], [("old", "new")], {"old": 2000, "new": 2010})
        assert cg.graph.ecount() == 0
        assert cg.dropped_time_reversed == 1

    def test_breaks_cycles(self):
        cg = g.build_graph(["a", "b"], [("a", "b"), ("b", "a")], {"a": 2020, "b": 2020})
        assert cg.graph.is_dag()
        assert cg.dropped_for_cycles == 1

    def test_ignores_edges_to_unknown_papers_and_self_citations(self):
        cg = g.build_graph(["a"], [("a", "a"), ("a", "zzz")], {"a": 2020})
        assert cg.graph.ecount() == 0


class TestSearchPathCount:
    def test_edge_weights_on_a_diamond(self):
        weights = g.spc_weights(diamond())
        # Two source-to-sink paths (A-B-D-E, A-C-D-E); every edge but D->E carries one of them.
        assert weights[("B", "A")] == pytest.approx(0.5)
        assert weights[("C", "A")] == pytest.approx(0.5)
        assert weights[("D", "B")] == pytest.approx(0.5)
        assert weights[("E", "D")] == pytest.approx(1.0)

    def test_node_flow(self):
        flow = g.node_flow(diamond())
        assert flow["A"] == pytest.approx(1.0)
        assert flow["B"] == pytest.approx(0.5)
        assert flow["D"] == pytest.approx(1.0)

    def test_global_main_path_runs_source_to_sink(self):
        cg = diamond()
        path = g.global_main_path(cg, g.spc_weights(cg))
        assert len(path) == 3
        assert path[0][1] == "A"           # starts at the oldest paper
        assert path[-1] == ("E", "D")      # ends at the newest

    def test_key_routes_extend_to_source_and_sink(self):
        cg = diamond()
        edges = g.key_route_main_paths(cg, g.spc_weights(cg), routes=1)
        nodes = {n for edge in edges for n in edge}
        assert ("E", "D") in edges
        assert {"A", "E"} <= nodes

    def test_main_path_returns_weights(self):
        main = g.main_path(diamond(), routes=1)
        assert all(len(edge) == 3 and edge[2] > 0 for edge in main)


class TestScaling:
    def test_pagerank_favours_the_most_built_upon_paper(self):
        pr = g.pagerank(diamond())
        assert pr["A"] > pr["E"]

    def test_percentile_ranks_count_ties_as_half(self):
        ranks = g.percentile_ranks({"a": 1, "b": 1, "c": 3})
        assert ranks["a"] == ranks["b"] == pytest.approx(1 / 3)
        assert ranks["c"] == pytest.approx(5 / 6)

    def test_log_scaled_keeps_orders_of_magnitude(self):
        scaled = g.log_scaled({"tiny": 0.001, "mid": 0.01, "top": 0.1, "none": 0.0})
        assert scaled["top"] == 1.0
        assert scaled["tiny"] == 0.0
        assert scaled["mid"] == pytest.approx(0.5)
        assert scaled["none"] == 0.0

    def test_count_scaled(self):
        scaled = g.count_scaled({"a": 0, "b": 9, "c": 99})
        assert scaled["a"] == 0.0 and scaled["c"] == 1.0
        assert 0 < scaled["b"] < 1

    def test_cohort_scaled_compares_within_nearby_years(self):
        values = {"old_giant": 50000.0, "old_small": 100.0, "new_top": 500.0}
        years = {"old_giant": 2005, "old_small": 2005, "new_top": 2022}
        scaled = g.cohort_scaled(values, years, window=2)
        assert scaled["new_top"] == 1.0  # best of its own years, not buried under 2005
        assert scaled["old_small"] < scaled["old_giant"] == 1.0


class TestMilestoneHelpers:
    @pytest.mark.parametrize("title,kind", [
        ("Object Detection in 20 Years: A Survey", "survey"),
        ("ImageNet: A large-scale hierarchical image database", "dataset"),
        ("The PASCAL Visual Object Classes Challenge", "benchmark"),
        ("Fast R-CNN", "method"),
    ])
    def test_classify_kind(self, title, kind):
        assert classify_kind(title) == kind

    def test_review_work_type_is_a_survey(self):
        assert classify_kind("Deep learning", "review") == "survey"

    @pytest.mark.parametrize("title,name", [
        ("LoRA: Low-Rank Adaptation of Large Language Models", "LoRA"),
        ("Faster R-CNN: Towards Real-Time Object Detection", "Faster R-CNN"),
        ("You Only Look Once: Unified, Real-Time Object Detection", None),
        ("Fast R-CNN", None),
    ])
    def test_named_method(self, title, name):
        assert named_method(title) == name

    def test_relevance(self):
        keywords = ["detect"]
        assert relevance("Fast R-CNN for detection", None, keywords) == 1.0
        assert relevance("Objects as Points", "we detect objects as points", keywords) == 0.5
        assert relevance("Deep Residual Learning", "image recognition", keywords) == 0.0
        assert relevance("Anything", None, []) == 1.0

    def test_relevance_matches_keywords_at_word_starts(self):
        assert relevance("LoRA: Low-Rank Adaptation", None, ["lora"]) == 1.0
        assert relevance("Curiosity-driven exploration", "Exploration in floral fields", ["lora"]) == 0.0
        assert relevance("Faster R-CNN", None, ["r-cnn"]) == 1.0

    def test_era_bounds_split_long_sparse_eras(self):
        years = [1990] + [2015] * 10 + [2016] * 10
        bounds = era_bounds(years, eras=2, max_era_years=6)
        assert bounds[0] == (1990, 1995)
        assert bounds[-1] == (2015, 2016)
        assert all(end - start < 6 for start, end in bounds)

    def test_effective_milestone(self):
        assert effective_milestone(False, "pin") is True
        assert effective_milestone(True, "unpin") is False
        assert effective_milestone(True, None) is True


def _score(score: float, kind: str = "method", rel: float = 1.0) -> PaperScore:
    return PaperScore(kind=kind, named_method=None, in_degree=0, out_degree=0, pagerank=0.0, citation_score=0.0,
                      specificity=0.0, relevance=rel, on_main_path=False, milestone_score=score)


class TestSelectMilestones:
    def test_global_top_survives_a_crowded_era(self):
        scores = {f"p{i}": _score(0.9 - i * 0.01) for i in range(6)}
        years = {pid: 2015 for pid in scores}
        config = TopicConfig(eras=1, milestones_per_era=3, global_top=5)
        assert len(select_milestones(scores, years, config)) == 5

    def test_min_score_stops_padding_sparse_eras(self):
        scores = {"weak": _score(0.2), "strong": _score(0.9)}
        years = {"weak": 1985, "strong": 2015}
        config = TopicConfig(global_top=0, milestone_min_score=0.55)
        assert select_milestones(scores, years, config) == {"strong"}

    def test_only_on_topic_methods_qualify(self):
        scores = {"survey": _score(0.99, kind="survey"), "offtopic": _score(0.99, rel=0.0), "ok": _score(0.6)}
        years = {pid: 2020 for pid in scores}
        assert select_milestones(scores, years, TopicConfig()) == {"ok"}


def _paper(pid: str, year: int, cited_by: int, title: str | None = None, abstract: str = "detection") -> CorpusPaper:
    work = Work(openalex_id=pid, title=title or f"Object detection {pid}", year=year, cited_by_count=cited_by,
                abstract=abstract)
    return CorpusPaper(work=work, year=year, year_source="openalex", role="core")


def test_score_topic_marks_the_central_paper_as_a_milestone():
    papers = {"root": _paper("root", 2010, 20000)}
    edges = set()
    for i in range(12):
        pid = f"f{i}"
        papers[pid] = _paper(pid, 2012 + i % 4, 50)
        edges.add((pid, "root"))
    papers["backbone"] = _paper("backbone", 2011, 90000, title="Deep residual networks", abstract="image recognition")
    for i in range(12):
        edges.add((f"f{i}", "backbone"))
    scores = score_topic(Corpus(papers=papers, edges=edges), TopicConfig(keywords=["detect"]))
    assert scores.papers["root"].is_milestone_auto
    assert not scores.papers["backbone"].is_milestone_auto  # cited a lot, but off-topic
    assert scores.papers["root"].milestone_score > scores.papers["f0"].milestone_score
