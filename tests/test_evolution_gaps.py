"""Tests for gap themes (pure; no database, no GPU)."""
from __future__ import annotations

import numpy as np

from athena.evolution.fulltext import gap_candidates
from athena.evolution.gaps import build_themes, cluster, theme_terms
from athena.evolution.tei import ParsedPaper, Section, Sentence


def near(base: np.ndarray, rng, n: int) -> list[np.ndarray]:
    return [base + 0.05 * rng.normal(size=base.shape) for _ in range(n)]


def gap_row(i, sentence, year, origin="own", fix=False, paper="A"):
    return {"id": i, "paper_id": paper, "source_paper_id": f"S{i}", "origin": origin, "sentence": sentence,
            "year": year, "fix": fix}


class TestCluster:
    def test_similar_vectors_cluster_and_strays_are_left_out(self):
        rng = np.random.default_rng(0)
        a, b = rng.normal(size=64), rng.normal(size=64)
        vecs = np.array(near(a, rng, 4) + near(b, rng, 3) + [rng.normal(size=64)])
        labels = cluster(vecs, distance=0.3, min_size=3)
        assert labels[:4] == [0] * 4 and labels[4:7] == [1] * 3 and labels[7] == -1

    def test_too_few_statements_make_no_theme(self):
        assert cluster(np.ones((2, 8)), min_size=3) == [-1, -1]


class TestTerms:
    def test_distinctive_words_beat_shared_ones(self):
        terms = theme_terms({0: ["quantized adapters lose accuracy after merging",
                                 "merging quantized adapters is lossy", "quantized adapters cannot be merged"],
                             1: ["prompt tuning converges slowly", "slow convergence of prompt tuning on models",
                                 "prompt tuning needs many steps"]})
        assert terms[0][0] == "quantized adapters" and terms[1][0] == "prompt tuning"
        assert not any("models" in t.split() for t in terms[1])  # a generic word

    def test_terms_do_not_repeat_words(self):
        terms = theme_terms({0: ["merging quantized adapters loses accuracy"] * 3, 1: ["other words here"] * 3})
        words = [w for t in terms[0] for w in t.split()]
        assert len(words) == len(set(words))


class TestThemes:
    def setup_method(self):
        rng = np.random.default_rng(1)
        a, b = rng.normal(size=64), rng.normal(size=64)
        self.vecs = np.array(near(a, rng, 3) + near(b, rng, 3))
        self.rows = [gap_row(0, "merging quantized adapters loses accuracy", 2021),
                     gap_row(1, "quantized adapters cannot be merged", 2022),
                     gap_row(2, "merging quantized adapters hurts accuracy", 2024),
                     gap_row(3, "prompt tuning converges slowly", 2019),
                     gap_row(4, "prompt tuning converges slowly on small models", 2020),
                     gap_row(5, "slow convergence of prompt tuning", 2020)]

    def themes(self):
        by_member = {}
        for t in build_themes(self.rows, self.vecs, distance=0.3):
            by_member["quantized" if 0 in t["members"] else "prompt"] = t
        return by_member

    def test_status_follows_recent_mentions_and_fixes(self):
        themes = self.themes()
        assert themes["quantized"]["status"] == "persisting"   # stated since 2021 and still in 2024
        assert themes["prompt"]["status"] == "quiet"           # last stated in 2020
        for row in self.rows[:3]:
            row["year"] = 2024 - row["id"] % 2
        assert self.themes()["quantized"]["status"] == "new"   # only stated in 2023-2024
        self.rows[4]["fix"] = True
        assert self.themes()["prompt"]["status"] == "addressed"

    def test_yearly_counts(self):
        assert self.themes()["prompt"]["yearly"] == {"2019": 1, "2020": 2}

    def test_persisting_themes_come_first(self):
        assert build_themes(self.rows, self.vecs, distance=0.3)[0]["status"] == "persisting"


def test_gap_candidates_need_a_cue_except_in_limitations():
    s = lambda text: Sentence(text=text)  # noqa: E731
    parsed = ParsedPaper(title="T", bib={}, sections=[
        Section("Introduction", "1", "intro", "intro",
                [s("However, adapters add latency at inference."), s("We propose a new method for this.")]),
        Section("Method", "2", "method", "method", [s("However, this is a method detail.")]),
        Section("Limitations", "6", "limitations", "limitations", [s("Our study covers only English data.")]),
    ])
    assert gap_candidates(parsed) == [("intro", "However, adapters add latency at inference."),
                                      ("limitations", "Our study covers only English data.")]


def test_text_search_needs_a_topic_keyword():
    from types import SimpleNamespace

    from athena.evolution.search import _mentions_keywords
    peft = SimpleNamespace(config={"keywords": ["lora", "adapter", "soft prompt"]})
    assert _mentions_keywords("LoRA variants", peft)
    assert _mentions_keywords("soft prompts for small models", peft)
    assert not _mentions_keywords("speech recognition", peft)
    assert _mentions_keywords("anything", SimpleNamespace(config={}))  # no keywords: no gate


def test_labels_ignore_citations_and_author_names():
    from athena.evolution.gaps import _clean
    assert "Lester" not in _clean("Prompt tuning lags full tuning (Lester et al., 2021).")
    assert "[12, 14]" not in _clean("Adapters add latency [12, 14] at inference.")
    assert _clean("3.1 Lack of universality of prompts").strip().startswith("Lack")
