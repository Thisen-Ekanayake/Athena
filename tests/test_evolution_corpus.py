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

    def __init__(self, seeds: list[Work], hits: list[Work]):
        self.seeds = {w.openalex_id: w for w in seeds}
        self.hits = hits
        self.searches: list[tuple] = []
        self.requests = self.cache_hits = 0
        self.spent_usd = 0.0

    def get_work(self, wid):
        return self.seeds.get(wid)

    def get_works(self, ids):
        return []

    def citing_works(self, wid, limit):
        return []

    def search_works(self, terms, limit, fields=None, in_title=False):
        self.searches.append((tuple(terms), limit, tuple(fields or ())))
        return self.hits[:limit]


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
        assert oa.searches == [(("object tracking",), 1000, ("Computer Science",))]
        assert corpus.stats["openalex_search_hits"] == 2 and corpus.stats["s2"] == "off"

    def test_no_search_by_default(self):
        corpus, oa = self.run(s2=False)
        assert oa.searches == [] and set(corpus.papers) == {"S1", "S2"}

    def test_no_key_skips_semantic_scholar_when_keyless_is_off(self, monkeypatch):
        monkeypatch.setattr("athena.core.semantic_scholar.get_setting", lambda key, default=None: default)
        corpus, _ = self.run(s2=True, s2_keyless=False)
        assert corpus.stats["s2"].startswith("skipped")
        assert set(corpus.papers) == {"S1", "S2"}
