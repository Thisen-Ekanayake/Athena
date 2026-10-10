"""Tests for building a topic corpus from seeds (selection only; no network)."""
from __future__ import annotations

from athena.evolution.config import TopicConfig
from athena.evolution.corpus import Seed, _citer_bound, select_corpus
from athena.evolution.openalex import Work


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
