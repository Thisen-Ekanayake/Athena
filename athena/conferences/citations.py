"""
Citation counts for conference papers, and abstracts for the ones the Anthology has none for.

Each source misses papers the other has: Semantic Scholar knows most papers by their Anthology id (``ACL:P18-1031``)
but not every recent one; OpenAlex knows recent ones by DOI (``10.18653/v1/2024.acl-long.1``), which papers from
before about 2016 lack. Both are asked and the larger count is kept. The Anthology has almost no abstracts before
2015, so an abstract either source has fills the gap, and the paper is embedded again with it.

Counts of the last two years' papers move fast and are refreshed weekly, older ones monthly.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from loguru import logger
from sqlalchemy import or_, select

from athena.core.models import ConfPaper
from athena.database.db import SessionLocal

CHUNK = 1000
RECENT_YEARS = 2
RECENT_DAYS = 7
OLD_DAYS = 30
OA_SELECT = "id,doi,cited_by_count,abstract_inverted_index"
S2_FIELDS = "paperId,citationCount,abstract"


def _due(session, now: datetime, limit: int):
    recent = now.year - RECENT_YEARS
    return list(session.execute(
        select(ConfPaper).where(or_(
            ConfPaper.citations_at.is_(None),
            (ConfPaper.year >= recent) & (ConfPaper.citations_at < now - timedelta(days=RECENT_DAYS)),
            (ConfPaper.year < recent) & (ConfPaper.citations_at < now - timedelta(days=OLD_DAYS)),
        )).order_by(ConfPaper.citations_at.is_not(None), ConfPaper.year.desc(), ConfPaper.id).limit(limit)
    ).scalars())


def _openalex(papers: list[ConfPaper]) -> dict[str, tuple[int, str | None]]:
    """{doi (lower case): (citations, abstract)}"""
    from athena.core.openalex import OpenAlexClient
    dois = [p.doi for p in papers if p.doi]
    if not dois:
        return {}
    client = OpenAlexClient(cache_dir="")  # counts must be today's
    return {w.doi.lower(): (w.cited_by_count, w.abstract) for w in client.get_works_by_doi(dois, select=OA_SELECT)
            if w.doi}


def _semantic_scholar(papers: list[ConfPaper]) -> dict[str, tuple[int, str | None]]:
    """{anthology id: (citations, abstract)}"""
    from athena.core.semantic_scholar import SemanticScholarClient
    client = SemanticScholarClient(cache_dir="")
    found = client.get_papers([f"ACL:{p.id}" for p in papers], fields=S2_FIELDS)
    return {key[4:]: (paper.citation_count, paper.abstract) for key, paper in found.items() if paper}


def _usable(abstract: str | None) -> str | None:
    text = " ".join((abstract or "").split())
    return text if len(text) >= 80 else None  # "Abstract not available", a stray heading


def refresh(limit: int | None = None, deadline: float | None = None) -> dict:
    """Ask both sources about due papers, newest and never-asked first, ``CHUNK`` at a time until ``limit`` papers
    or the ``deadline`` (time.monotonic()). A source that fails is left out of that chunk; a paper neither knows is
    marked asked so it waits its turn again."""
    from athena.core.openalex import OpenAlexBudgetError
    now = datetime.now(timezone.utc)
    stats = {"asked": 0, "counted": 0, "abstracts": 0}
    with SessionLocal() as session:
        while limit is None or stats["asked"] < limit:
            if deadline is not None and time.monotonic() > deadline:
                stats["more"] = True
                break
            papers = _due(session, now, CHUNK if limit is None else min(CHUNK, limit - stats["asked"]))
            if not papers:
                break
            try:
                oa = _openalex(papers)
            except OpenAlexBudgetError as exc:
                logger.warning(f"Conference citations: {exc}")
                oa, stats["openalex_budget"] = {}, True
            except Exception as exc:
                logger.warning(f"Conference citations: OpenAlex failed for a chunk: {exc}")
                oa = {}
            try:
                s2 = _semantic_scholar(papers)
            except Exception as exc:
                logger.warning(f"Conference citations: Semantic Scholar failed for a chunk: {exc}")
                s2 = {}
            if not oa and not s2:
                stats["failed"] = True
                break  # both down: try again on the next run rather than mark the chunk asked
            for p in papers:
                answers = [a for a in (oa.get((p.doi or "").lower()), s2.get(p.id)) if a]
                if answers:
                    p.citation_count = max(max(a[0] or 0 for a in answers), p.citation_count or 0)
                    stats["counted"] += 1
                if not p.abstract:
                    for source, answer in (("openalex", oa.get((p.doi or "").lower())), ("semantic_scholar",
                                                                                         s2.get(p.id))):
                        if answer and (text := _usable(answer[1])):
                            p.abstract, p.abstract_from = text, source
                            p.embedded_at = p.embed_model = None  # embed again with it
                            stats["abstracts"] += 1
                            break
                p.citations_at = now
            session.commit()
            stats["asked"] += len(papers)
            logger.info(f"Conference citations: {stats}")
    return stats
