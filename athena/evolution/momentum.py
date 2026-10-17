"""
Citations per year for map papers (ROADMAP P3), and the papers rising fastest in a map.

OpenAlex keeps each work's citations per calendar year for the last ten years (``counts_by_year``). They are
fetched with their own small ``select`` (OpenAlexClient.citation_years), so the cached answers map builds read
stay as they are and no evaluation changes, and stored in ``EvoPaper.extra["counts_by_year"]``. A map's papers get
them after each build and refresh; a paper fetched in the last REFETCH_DAYS keeps what it has.

How a paper's yearly counts become "rising" is in ``athena.core.citation_gains``, next to the feed's gains.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from loguru import logger
from sqlalchemy import select

REFETCH_DAYS = 30


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
