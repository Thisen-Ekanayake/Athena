"""
Reading path: learn a field in N papers.

A survey first, then milestones in the order they appeared. When a topic has
more milestones than the path has room for, every era keeps its best one
before any era gets a second, so the path spans the field's history instead
of crowding into its busiest years. Main-path milestones win ties: they are the
papers the field's citation flow runs through. (A larger bonus put YOLO ahead
of Faster R-CNN, which is not on object detection's main path.)

Pure functions over stored rows; ``athena.database.evolution.reading_path``
feeds them and adds the notes and read ticks.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Hashable

from athena.evolution.eras import find_era

MAIN_PATH_BONUS = 0.02
SURVEY_ALTERNATES = 2


@dataclass
class PathCandidate:
    id: Hashable
    year: int | None
    kind: str
    milestone_score: float
    on_main_path: bool
    is_milestone: bool   # with a person's pin or unpin applied
    on_topic: bool       # mentions the topic's keywords (or is close to it in meaning)
    milestones_cited: int = 0  # for surveys: how many of the topic's milestones it cites

    @property
    def rank(self) -> float:
        return self.milestone_score + (MAIN_PATH_BONUS if self.on_main_path else 0.0)


def pick_survey(papers: list[PathCandidate]) -> tuple[PathCandidate | None, list[PathCandidate]]:
    """The survey to start with, and a couple of others.

    On-topic surveys first (any survey when none is), ranked by the share of milestones they cite (against
    the survey citing the most) plus their score. Citing the milestones is what makes a survey cover the path:
    by score or recency alone, object detection got narrow ones (remote-sensing detection, a review of YOLO
    versions); by milestones cited alone, diffusion models got a survey of image editing.
    """
    surveys = [p for p in papers if p.kind == "survey" and p.year is not None]
    pool = [p for p in surveys if p.on_topic] or surveys
    if not pool:
        return None, []
    most = max(p.milestones_cited for p in pool) or 1
    ranked = sorted(pool, key=lambda p: p.milestones_cited / most + p.milestone_score, reverse=True)
    return ranked[0], ranked[1:1 + SURVEY_ALTERNATES]


def pick_steps(papers: list[PathCandidate], count: int, eras: list[tuple[int, int]]) -> list[PathCandidate]:
    """``count`` milestones in year order, covering as many eras as there is room for."""
    milestones = [p for p in papers if p.is_milestone and p.year is not None]
    if count <= 0:
        return []
    if len(milestones) > count:
        by_rank = sorted(milestones, key=lambda p: p.rank, reverse=True)
        best_per_era: dict[tuple[int, int] | None, PathCandidate] = {}
        for p in by_rank:
            best_per_era.setdefault(find_era(p.year, eras), p)
        picked = sorted(best_per_era.values(), key=lambda p: p.rank, reverse=True)[:count]
        chosen = {p.id for p in picked}
        picked += [p for p in by_rank if p.id not in chosen][:count - len(picked)]
        milestones = picked
    return sorted(milestones, key=lambda p: (p.year, -p.rank))


def build_path(papers: list[PathCandidate], n: int,
               eras: list[tuple[int, int]]) -> tuple[PathCandidate | None, list[PathCandidate], list[PathCandidate]]:
    """(survey, other surveys, milestone steps): ``n`` papers in all, the survey counting as one."""
    survey, others = pick_survey(papers)
    return survey, others, pick_steps(papers, n - 1 if survey else n, eras)
