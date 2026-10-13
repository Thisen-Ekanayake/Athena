"""
Eras: a topic's years split into periods holding equal numbers of papers.

Milestones are picked per era (``athena.evolution.milestones``); the reading
path, the people view and a paper's place in a map use the same eras, read back
from stored rows. No third-party imports, so the API image can use it.
"""
from __future__ import annotations

from typing import Iterable


def era_bounds(paper_years: list[int], eras: int, max_era_years: int) -> list[tuple[int, int]]:
    """Split years into eras holding equal numbers of papers, then cut any era longer than ``max_era_years``.

    A paper's era follows from the rank of its year, so one year never spans two eras.
    """
    ordered = sorted(paper_years)
    n = len(ordered)
    if n == 0:
        return []
    starts = sorted({ordered[min(n - 1, i * n // eras)] for i in range(eras)})
    bounds = []
    for i, start in enumerate(starts):
        end = starts[i + 1] - 1 if i + 1 < len(starts) else ordered[-1]
        while end - start + 1 > max_era_years:
            bounds.append((start, start + max_era_years - 1))
            start += max_era_years
        bounds.append((start, end))
    return bounds


def era_of(year: int, bounds: list[tuple[int, int]]) -> tuple[int, int]:
    return next(b for b in bounds if b[0] <= year <= b[1])


def find_era(year: int | None, bounds: list[tuple[int, int]]) -> tuple[int, int] | None:
    """The era holding ``year``; years outside every era (off-topic papers, say) take the nearest one."""
    if year is None or not bounds:
        return None
    for b in bounds:
        if b[0] <= year <= b[1]:
            return b
    return bounds[0] if year < bounds[0][0] else bounds[-1]


def on_topic_method(kind: str | None, score_detail: dict | None, relevance_weight: float) -> bool:
    """Whether a stored paper could be a milestone: an on-topic method paper.

    The build keeps relevance only inside the score breakdown (weight x relevance), so a positive part
    means on-topic; with the relevance weight at zero every paper counts as on-topic.
    """
    if kind != "method":
        return False
    return relevance_weight <= 0 or (score_detail or {}).get("relevance", 0) > 0


def stored_eras(rows: Iterable[tuple[str | None, dict | None, int | None]], eras: int, max_era_years: int,
                relevance_weight: float) -> list[tuple[int, int]]:
    """The milestone eras of a built topic, from (kind, score_detail, year) rows."""
    years = [year for kind, detail, year in rows
             if year is not None and on_topic_method(kind, detail, relevance_weight)]
    return era_bounds(years, eras, max_era_years)
