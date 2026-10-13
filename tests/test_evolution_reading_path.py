"""Reading path (E1): which papers, in which order, and the notes on why each matters."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from athena.evolution import notes
from athena.evolution.reading_path import PathCandidate, build_path, pick_steps, pick_survey
from tests.fakes import FakeRedis


def paper(pid, year, score, kind="method", milestone=True, main=False, on_topic=True, cited=0):
    return PathCandidate(id=pid, year=year, kind=kind, milestone_score=score, on_main_path=main,
                         is_milestone=milestone, on_topic=on_topic, milestones_cited=cited)


class TestPickSurvey:
    def test_prefers_the_survey_that_cites_the_milestones(self):
        narrow = paper("narrow", 2024, 0.60, kind="survey", cited=3)
        broad = paper("broad", 2019, 0.52, kind="survey", cited=26)
        best, others = pick_survey([narrow, broad])
        assert best.id == "broad" and [o.id for o in others] == ["narrow"]

    def test_score_breaks_close_coverage(self):
        editing = paper("editing", 2024, 0.46, kind="survey", cited=16)
        general = paper("general", 2022, 0.64, kind="survey", cited=14)
        assert pick_survey([editing, general])[0].id == "general"

    def test_on_topic_surveys_come_first(self):
        off = paper("off", 2020, 0.9, kind="survey", on_topic=False, cited=30)
        on = paper("on", 2020, 0.3, kind="survey", cited=1)
        assert pick_survey([off, on])[0].id == "on"

    def test_no_survey(self):
        assert pick_survey([paper("m", 2020, 0.8)]) == (None, [])


class TestPickSteps:
    ERAS = [(2000, 2009), (2010, 2014), (2015, 2015), (2016, 2020)]

    def test_every_era_gets_one_before_any_gets_two(self):
        papers = [paper("a", 2005, 0.70), paper("b", 2012, 0.65), paper("c1", 2015, 0.90), paper("c2", 2015, 0.88),
                  paper("c3", 2015, 0.86), paper("d", 2018, 0.60)]
        steps = pick_steps(papers, 4, self.ERAS)
        assert [s.id for s in steps] == ["a", "b", "c1", "d"]

    def test_fills_by_score_once_every_era_has_one(self):
        papers = [paper("a", 2005, 0.70), paper("c1", 2015, 0.90), paper("c2", 2015, 0.88), paper("d", 2018, 0.60)]
        assert [s.id for s in pick_steps(papers, 3, self.ERAS)] == ["a", "c1", "d"]
        assert [s.id for s in pick_steps(papers, 4, self.ERAS)] == ["a", "c1", "c2", "d"]

    def test_main_path_only_breaks_ties(self):
        papers = [paper("faster", 2015, 0.869), paper("yolo", 2015, 0.814, main=True)]
        assert [s.id for s in pick_steps(papers, 1, self.ERAS)] == ["faster"]

    def test_only_milestones_with_years(self):
        papers = [paper("m", 2015, 0.9), paper("not", 2016, 0.95, milestone=False), paper("undated", None, 0.99)]
        assert [s.id for s in pick_steps(papers, 5, self.ERAS)] == ["m"]

    def test_the_survey_counts_towards_n(self):
        papers = [paper("s", 2019, 0.5, kind="survey", milestone=False, cited=2)] + [
            paper(f"m{i}", 2000 + i, 0.5 + i / 100) for i in range(10)]
        survey, _, steps = build_path(papers, 5, [(2000, 2009)])
        assert survey.id == "s" and len(steps) == 4
        assert [s.year for s in steps] == sorted(s.year for s in steps)


class TestNotes:
    PAPER = {"paper_id": uuid4(), "title": "Faster R-CNN: Towards Real-Time Object Detection", "year": 2015,
             "kind": "method", "abstract": "We introduce a Region Proposal Network.", "name": "Faster R-CNN",
             "builds_on": ["R-CNN (2013)"]}

    def test_prompt_asks_to_check_the_abstract(self):
        text = notes.prompt("Object detection", self.PAPER)
        assert "Abstract: We introduce" in text and "abstract_matches" in text and "R-CNN (2013)" in text

    def test_prompt_without_an_abstract_says_only_the_title_is_known(self):
        text = notes.prompt("Object detection", self.PAPER | {"abstract": None})
        assert "Abstract:" not in text and "Only the title is known" in text

    def test_clean(self):
        assert notes.clean('  "It introduced  RPNs."  ') == "It introduced RPNs."
        assert notes.clean("word " * 60) == ""

    def _run(self, answers, context=None):
        r = FakeRedis()
        r.set("evo:notes:object-detection", "1")
        topic = SimpleNamespace(name="Object detection", built_at=None)
        saved = []
        with patch("athena.database.db.SessionLocal") as session, \
                patch("athena.database.evolution.get_topic", return_value=topic), \
                patch("athena.database.evolution.current_notes", return_value={}), \
                patch("athena.database.evolution.note_context", return_value=context or [self.PAPER]), \
                patch("athena.database.evolution.save_note",
                      side_effect=lambda s, t, pid, text, m: saved.append(text)), \
                patch("athena.core.llm.chat_json", side_effect=answers) as chat:
            session.return_value.__enter__.return_value = object()
            written = notes.write_notes("object-detection", [self.PAPER["paper_id"]], r)
        return written, saved, chat, r

    def test_a_mismatched_abstract_is_asked_again_without_it(self):
        usage = {"model": "m"}
        written, saved, chat, r = self._run([({"abstract_matches": False, "why": "The abstract is about X."}, usage),
                                             ({"abstract_matches": False, "why": "It introduced RPNs."}, usage)])
        assert written == 1 and saved == ["It introduced RPNs."]
        assert "Abstract:" not in chat.call_args_list[1].args[0]
        assert not r.exists("evo:notes:object-detection")  # the lock is released

    def test_an_empty_note_is_stored_so_it_is_not_asked_again(self):
        written, saved, _, _ = self._run([({"abstract_matches": True, "why": ""}, {"model": "m"})])
        assert written == 0 and saved == [""]

    def test_a_failure_is_remembered_and_the_lock_released(self):
        written, saved, _, r = self._run(RuntimeError("no model server"))
        assert written == 0 and saved == []
        assert "no model server" in notes.last_failure(r, "object-detection")
        assert not r.exists("evo:notes:object-detection")
