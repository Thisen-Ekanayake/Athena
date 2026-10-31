"""Tests for building a topic corpus from seeds (selection only; no network)."""
from __future__ import annotations

from athena.evolution.config import TopicConfig
from athena.evolution.corpus import Seed, _citer_bound, select_corpus
from athena.core.openalex import Work


def work(wid: str, refs: list[str] = (), year: int = 2020, cited_by: int = 10, title: str | None = None,
         field: str = "Computer Science", arxiv_id: str | None = None) -> Work:
    return Work(openalex_id=wid, title=title or f"Paper {wid} about detection", year=year,
                referenced_works=list(refs), cited_by_count=cited_by, field_name=field, arxiv_id=arxiv_id)


def build(seed_works, candidates, seeds=None, **config):
    seeds = seeds or [Seed(openalex_id=w.openalex_id) for w in seed_works]
    return select_corpus({w.openalex_id: w for w in seed_works}, {w.openalex_id: w for w in candidates},
                         seeds, TopicConfig(**config))


class TestAcceptance:
    def test_candidates_need_two_links_to_accepted_papers(self):
        s1, s2 = work("S1", year=2015), work("S2", year=2016)
        both = work("X", ["S1", "S2"])
        one = work("Z", ["S1"])
        corpus = build([s1, s2], [both, one])
        assert "X" in corpus.papers
        assert "Z" not in corpus.papers

    def test_acceptance_repeats_until_nothing_changes(self):
        s1, s2 = work("S1", year=2015), work("S2", year=2016)
        x = work("X", ["S1", "S2"], year=2018)
        y = work("Y", ["S1", "X"], year=2019)  # cites one seed, but joins through X
        corpus = build([s1, s2], [x, y])
        assert "Y" in corpus.papers

    def test_ancestors_cited_by_two_seeds_are_kept(self):
        root = work("R", year=2005)
        s1, s2 = work("S1", ["R"], year=2015), work("S2", ["R"], year=2016)
        corpus = build([s1, s2], [root])
        assert "R" in corpus.papers
        assert ("S1", "R") in corpus.edges

    def test_out_of_field_and_paratext_are_dropped(self):
        s1, s2 = work("S1"), work("S2")
        bio = work("B", ["S1", "S2"], field="Medicine")
        para = work("P", ["S1", "S2"])
        para.work_type = "paratext"
        corpus = build([s1, s2], [bio, para])
        assert "B" not in corpus.papers and "P" not in corpus.papers

    def test_citations_to_a_seed_alias_count_for_the_seed(self):
        s1, s2 = work("S1"), work("S2")
        x = work("X", ["S1-preprint", "S2"])
        seeds = [Seed(openalex_id="S1", alt_ids=["S1-preprint"]), Seed(openalex_id="S2")]
        corpus = build([s1, s2], [x, work("S1-preprint")], seeds=seeds)
        assert ("X", "S1") in corpus.edges
        assert "S1-preprint" not in corpus.papers


class TestCap:
    def test_papers_are_ranked_against_their_own_year(self):
        # Four 2018 papers link to each other; two 2026 papers have had time only to cite the seeds.
        seeds = [work("S1", year=2015), work("S2", year=2016)]
        old = []
        for i in range(4):
            old.append(work(f"O{i}", ["S1", "S2", *(o.openalex_id for o in old)], year=2018))
        new = [work("N0", ["S1", "S2"], year=2026), work("N1", ["S1", "S2"], year=2026)]
        corpus = build(seeds, old + new, max_papers=5)
        assert len(corpus.papers) == 5
        assert "N0" in corpus.papers or "N1" in corpus.papers


class TestDuplicatesAndYears:
    def test_duplicate_records_merge_into_the_most_cited(self):
        s1, s2 = work("S1"), work("S2")
        conf = work("FRCNN", ["S1", "S2"], year=2015, cited_by=28000, title="Fast R-CNN")
        preprint = work("FRCNN-arxiv", ["S1", "S2"], year=2015, cited_by=1700, title="Fast R-CNN",
                        arxiv_id="1504.08083")
        corpus = build([s1, s2], [conf, preprint])
        assert "FRCNN" in corpus.papers and "FRCNN-arxiv" not in corpus.papers
        kept = corpus.papers["FRCNN"]
        assert kept.merged_ids == ["FRCNN-arxiv"]
        assert kept.work.arxiv_id == "1504.08083"  # the preprint's link carries over

    def test_seed_title_and_year_are_trusted(self):
        s1 = work("S1", year=2025, title="LoRA Fine-Tuning of a 3B Code LLM")
        s2 = work("S2")
        seeds = [Seed(openalex_id="S1", title="LoRA: Low-Rank Adaptation", year=2021), Seed(openalex_id="S2")]
        corpus = build([s1, s2], [], seeds=seeds)
        assert corpus.papers["S1"].title == "LoRA: Low-Rank Adaptation"
        assert (corpus.papers["S1"].year, corpus.papers["S1"].year_source) == (2021, "seed")

    def test_year_repaired_from_citers(self):
        # OpenAlex dates the Transformer paper 2025; papers citing it from 2017-2018 pull it back.
        s1, s2 = work("S1", year=2014), work("S2", year=2015)
        transformer = work("T", ["S1", "S2"], year=2025)
        citers = [work(f"C{i}", ["T", "S1"], year=2017 + i % 2) for i in range(6)]
        corpus = build([s1, s2], [transformer, *citers])
        assert corpus.papers["T"].year == 2017
        assert corpus.papers["T"].year_source == "citers"

    def test_arxiv_id_beats_a_later_publication_year(self):
        s1, s2 = work("S1", year=2010), work("S2", year=2011)
        paper = work("P", ["S1", "S2"], year=2016, arxiv_id="1506.01497")
        corpus = build([s1, s2], [paper])
        assert (corpus.papers["P"].year, corpus.papers["P"].year_source) == (2015, "arxiv")

    def test_citer_bound_needs_two_citers_and_ignores_one_outlier(self):
        assert _citer_bound([2012]) is None
        assert _citer_bound([2012] + [2016] * 40) == 2016


class TestStoredYearMerge:
    """Papers are shared across topics, so a build merges its view with the stored row."""

    def merged(self, new_year, new_source, old_year, old_source):
        from types import SimpleNamespace

        from athena.database.evolution import _merge_paper
        from athena.evolution.corpus import CorpusPaper
        paper = CorpusPaper(work=work("W1", year=new_year), year=new_year, year_source=new_source, role="core")
        existing = SimpleNamespace(id="x", title="Old", year=old_year, year_source=old_source, arxiv_id=None,
                                   oa_pdf_url=None, is_oa=False, abstract=None, s2_paper_id=None,
                                   s2_cited_by_count=None, full_text_status="available")
        row = _merge_paper("W1", paper, existing, now=None)
        return row["year"], row["year_source"]

    def test_seed_year_is_kept(self):
        assert self.merged(2016, "openalex", 2015, "seed") == (2015, "seed")

    def test_arxiv_year_replaces_an_earlier_citer_guess(self):
        # A revised 2023 preprint "citing" DoRA once dated it 2023; its arXiv ID says 2024.
        assert self.merged(2024, "arxiv", 2023, "citers") == (2024, "arxiv")

    def test_arxiv_year_is_kept_over_a_later_guess(self):
        assert self.merged(2022, "citers", 2024, "arxiv") == (2024, "arxiv")

    def test_otherwise_the_earliest_year_wins(self):
        assert self.merged(2018, "openalex", 2017, "citers") == (2017, "citers")


class FakeOpenAlex:
    """Seeds by ID, no citers, and fixed search hits."""

    def __init__(self, seeds: list[Work], hits: list[Work], citers: dict[str, list[Work]] | None = None):
        self.seeds = {w.openalex_id: w for w in seeds}
        self.hits = hits
        self.citers = citers or {}
        self.searches: list[tuple] = []
        self.citer_calls: list[tuple] = []
        self.requests = self.cache_hits = 0
        self.spent_usd = 0.0

    def get_work(self, wid):
        return self.seeds.get(wid)

    def get_works(self, ids):
        return []

    def citing_works(self, wid, limit, year=None):
        self.citer_calls.append((wid, limit, year))
        return [w for w in self.citers.get(wid, []) if year is None or w.year == year][:limit]

    def search_works(self, terms, limit, fields=None, in_title=False, year=None):
        self.searches.append((tuple(terms), limit, tuple(fields or ()), year))
        return [w for w in self.hits if year is None or w.year == year][:limit]


class TestOpenAlexSearchAndSkippedS2:
    def setup_method(self):
        from athena.evolution import corpus as c
        self.c = c
        self.s1, self.s2 = work("S1", year=2015), work("S2", year=2016)
        # H1 cites both seeds and joins; H2 cites one seed only and stays out.
        self.hits = [work("H1", refs=["S1", "S2"], year=2018), work("H2", refs=["S1"], year=2019)]

    def run(self, **config):
        oa = FakeOpenAlex([self.s1, self.s2], self.hits)
        seeds = [Seed(openalex_id="S1"), Seed(openalex_id="S2")]
        corpus = self.c.build_corpus(oa, seeds, TopicConfig(**config), search_terms=["object tracking"])
        return corpus, oa

    def test_search_hits_join_only_through_links(self):
        corpus, oa = self.run(s2=False, openalex_search_max=1000, fields=["Computer Science"])
        assert set(corpus.papers) == {"S1", "S2", "H1"}
        assert oa.searches == [(("object tracking",), 1000, ("Computer Science",), None)]
        assert corpus.stats["openalex_search_hits"] == 2 and corpus.stats["s2"] == "off"

    def test_no_search_by_default(self):
        corpus, oa = self.run(s2=False)
        assert oa.searches == [] and set(corpus.papers) == {"S1", "S2"}

    def test_no_key_skips_semantic_scholar_when_keyless_is_off(self, monkeypatch):
        monkeypatch.setattr("athena.core.semantic_scholar.get_setting", lambda key, default=None: default)
        corpus, _ = self.run(s2=True, s2_keyless=False)
        assert corpus.stats["s2"].startswith("skipped")
        assert set(corpus.papers) == {"S1", "S2"}


class TestRecentYears:
    """Lists cut short at their most cited also fetch each recent year's most cited."""

    def setup_method(self, method):
        from athena.evolution import corpus as c
        self.c = c
        self.s1, self.s2 = work("S1", year=2015), work("S2", year=2016)
        self.old = [work(f"O{i}", ["S1", "S2"], year=2019, cited_by=500) for i in range(3)]
        self.new = work("N", ["S1", "S2"], year=2026, cited_by=1)

    def run(self, monkeypatch, **config):
        class Today:
            @staticmethod
            def today():
                from datetime import date
                return date(2026, 10, 31)

        monkeypatch.setattr(self.c, "date", Today)
        oa = FakeOpenAlex([self.s1, self.s2], self.old + [self.new], citers={"S1": self.old + [self.new]})
        seeds = [Seed(openalex_id="S1"), Seed(openalex_id="S2")]
        corpus = self.c.build_corpus(oa, seeds, TopicConfig(s2=False, **config), search_terms=["object tracking"])
        return corpus, oa

    def test_full_citer_lists_get_each_recent_year(self, monkeypatch):
        corpus, oa = self.run(monkeypatch, citers_per_seed=3, recent_years=2, recent_per_year=50)
        assert ("S1", 50, 2025) in oa.citer_calls and ("S1", 50, 2026) in oa.citer_calls
        assert ("S2", 3, None) in oa.citer_calls and ("S2", 50, 2026) not in oa.citer_calls  # S2's list was short
        assert "N" in corpus.papers

    def test_full_search_gets_each_recent_year(self, monkeypatch):
        corpus, oa = self.run(monkeypatch, citers_per_seed=10, openalex_search_max=3, recent_years=1)
        assert [s[3] for s in oa.searches] == [None, 2026]
        assert corpus.stats["openalex_search_hits"] == 4

    def test_off(self, monkeypatch):
        corpus, oa = self.run(monkeypatch, citers_per_seed=3, recent_per_year=0)
        assert all(year is None for _, _, year in oa.citer_calls)
        assert "N" not in corpus.papers
