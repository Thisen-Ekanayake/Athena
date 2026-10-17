"""
Citation gains: the pure maths behind the feed's and the maps' "rising".

The two measures differ because their data does:

- Feed papers (``athena.pipeline.momentum``) get a Semantic Scholar count every day, kept as snapshots, so their gain
  is exact: today's count minus the count of the latest snapshot at or before the window's start (``gain``).
- Map papers (``athena.evolution.momentum``) only have OpenAlex citations per calendar year. The last twelve months
  are estimated from them as this year so far plus the part of last year still inside the window, and likewise the
  twelve months before (``twelve_months``). That keeps January stable, when this year holds almost nothing yet.
  Papers are ranked by (last + PRIOR) / (previous + PRIOR) among those with at least RISING_FLOOR citations in the
  last twelve months, so 2 → 6 is not "3x" (``rising_entry``).
"""
from __future__ import annotations

import bisect
from datetime import datetime, timezone

RISING_FLOOR = 15
RISING_PRIOR = 10
YEARS_SHOWN = 8


# ── feed papers: daily snapshots ─────────────────────────────────────


def count_at(history: list[tuple[datetime, int]], when: datetime) -> int | None:
    """The count of the latest snapshot at or before ``when`` (``history`` sorted by date), or None."""
    i = bisect.bisect_right([d for d, _ in history], when)
    return history[i - 1][1] if i else None


def gain(history: list[tuple[datetime, int]], current: int, published: datetime | None, since: datetime) -> int | None:
    """Citations gained since ``since``. A paper published after it gained everything it has; one with no snapshot
    from then is unknown."""
    before = count_at(history, since)
    if before is None:
        if published is not None and published >= since:
            before = 0
        else:
            return None
    return max(0, current - before)


# ── map papers: citations per calendar year ──────────────────────────


def _year_fraction(now: datetime) -> float:
    start = datetime(now.year, 1, 1, tzinfo=timezone.utc)
    end = datetime(now.year + 1, 1, 1, tzinfo=timezone.utc)
    return (now - start).total_seconds() / (end - start).total_seconds()


def counts_of(paper) -> dict[int, int]:
    """A paper's stored citations per year ({year: n}; JSON keeps the years as strings)."""
    raw = (paper.extra or {}).get("counts_by_year") or {}
    return {int(y): int(n) for y, n in raw.items()}


def twelve_months(counts: dict[int, int], now: datetime) -> tuple[float, float]:
    """(last twelve months, the twelve before), estimated from calendar-year counts."""
    elapsed = _year_fraction(now)
    year = now.year
    last = counts.get(year, 0) + counts.get(year - 1, 0) * (1 - elapsed)
    before = counts.get(year - 1, 0) * elapsed + counts.get(year - 2, 0) * (1 - elapsed)
    return last, before


def by_year(counts: dict[int, int], now: datetime, years: int = YEARS_SHOWN) -> list[dict]:
    """The last ``years`` calendar years, oldest first; the current one is partial."""
    return [{"year": y, "citations": counts.get(y, 0), "partial": y == now.year}
            for y in range(now.year - years + 1, now.year + 1)]


def rising_entry(counts: dict[int, int], now: datetime) -> dict | None:
    """A paper's place in "rising", or None when it is below the floor or not rising."""
    last, before = twelve_months(counts, now)
    if last < RISING_FLOOR:
        return None
    ratio = (last + RISING_PRIOR) / (before + RISING_PRIOR)
    if ratio <= 1:
        return None
    return {"last_12_months": round(last), "previous_12_months": round(before), "ratio": round(ratio, 2)}
