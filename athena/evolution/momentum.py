"""
Citations per year for map papers (ROADMAP P3), and the papers rising fastest in a map.

OpenAlex keeps each work's citations per calendar year for the last ten years (``counts_by_year``). They are
fetched with their own small ``select`` (OpenAlexClient.citation_years), so the cached answers map builds read
stay as they are and no evaluation changes, and stored in ``EvoPaper.extra["counts_by_year"]``. A map's papers get
them after each build and refresh; a paper fetched in the last REFETCH_DAYS keeps what it has.

Rising: the last twelve months are estimated from calendar years as this year so far plus the part of last year
still inside the window, and likewise the twelve months before. That keeps January stable, when this year holds
almost nothing yet. Papers are ranked by (last + PRIOR) / (previous + PRIOR) among those with at least
RISING_FLOOR citations in the last twelve months, so 2 → 6 is not "3x".
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from loguru import logger
from sqlalchemy import select

REFETCH_DAYS = 30
RISING_FLOOR = 15
RISING_PRIOR = 10
YEARS_SHOWN = 8


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


def refresh_topic_years(session, topic, client=None, now: datetime | None = None, force: bool = False) -> int:
    """Fetch citations per year for a map's papers that have none or are older than REFETCH_DAYS."""
    from athena.core.models import EvoPaper, EvoTopicPaper
    from athena.core.openalex import OpenAlexClient
    now = now or datetime.now(timezone.utc)
    papers = session.execute(select(EvoPaper).join(EvoTopicPaper, EvoTopicPaper.paper_id == EvoPaper.id)
                             .where(EvoTopicPaper.topic_id == topic.id)).scalars().all()
    stale = (now - timedelta(days=REFETCH_DAYS)).isoformat()
    due = [p for p in papers if force or ((p.extra or {}).get("counts_fetched_at") or "") < stale]
    if not due:
        return 0
    years = (client or OpenAlexClient()).citation_years([p.openalex_id for p in due])
    for paper in due:  # one OpenAlex no longer knows (merged away) is asked about again only after REFETCH_DAYS
        found = {"counts_by_year": {str(y): n for y, n in sorted(years[paper.openalex_id].items())}} \
            if paper.openalex_id in years else {}
        paper.extra = {**(paper.extra or {}), **found, "counts_fetched_at": now.isoformat()}
    session.commit()
    logger.info(f"Topic {topic.slug}: citations per year for {len(due)} papers")
    return len(due)
