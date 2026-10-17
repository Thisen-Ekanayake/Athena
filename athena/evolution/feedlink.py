"""
Linking the feed to the maps (ROADMAP E5).

Two links:

1. A feed paper that is itself in a map: matched on its arXiv ID and stored in
   ``EvoPaper.content_item_id``, so the paper panel can show its place in the
   map.
2. A new feed paper that cites a map's milestones ("new in your maps"): its
   reference list comes from Semantic Scholar (one batch request covers 200
   papers, and works without a key), else from OpenAlex, and is matched against
   every map paper by arXiv ID, DOI, Semantic Scholar ID or title. The result is
   kept in ``ContentItem.extra_data["evolution"]``.

New preprints often have no references in either source for a few days, so a
paper without any is asked about again a week later, until it is two months
old. Runs every six hours on the default queue.
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from uuid import UUID

from loguru import logger
from sqlalchemy import select, update

ARXIV_URL = re.compile(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5}|[a-z\-]+(?:\.[A-Z]{2})?/\d{7})(?:v\d+)?",
                       re.IGNORECASE)
FEED_DAYS = 60     # feed papers are checked until they are this old
RECHECK_DAYS = 7   # a paper whose references were not found yet is asked about again after this long


def arxiv_id_from_url(url: str | None) -> str | None:
    match = ARXIV_URL.search(url or "")
    return match.group(1) if match else None


def link_feed_items() -> int:
    """Point map papers at the feed items that are the same paper. Returns how many links are new."""
    from athena.core.models import ContentItem, EvoPaper
    from athena.database.db import SessionLocal

    with SessionLocal() as session:
        by_arxiv = {}
        for item_id, url in session.execute(select(ContentItem.id, ContentItem.url)
                                            .where(ContentItem.url.ilike("%arxiv.org/%"))):
            if arxiv := arxiv_id_from_url(url):
                by_arxiv[arxiv] = item_id
        linked = 0
        for paper_id, arxiv, current in session.execute(
                select(EvoPaper.id, EvoPaper.arxiv_id, EvoPaper.content_item_id)
                .where(EvoPaper.arxiv_id.in_(list(by_arxiv)))):
            item_id = by_arxiv.get(re.sub(r"v\d+$", "", arxiv))
            if item_id and item_id != current:
                session.execute(update(EvoPaper).where(EvoPaper.id == paper_id).values(content_item_id=item_id))
                linked += 1
        session.commit()
    return linked


def milestone_citations(cited: set[UUID], membership: dict[UUID, list[dict]]) -> tuple[list[dict], dict[str, int]]:
    """The milestones among ``cited`` (one entry per map they are a milestone of), and map papers cited per map."""
    cites, per_map = [], defaultdict(int)
    for pid in cited:
        for place in membership.get(pid, []):
            per_map[place["topic"]] += 1
            if place["milestone"]:
                cites.append(place | {"paper_id": str(pid)})
    cites.sort(key=lambda c: (c["topic"], c.get("year") or 0))
    return cites, dict(per_map)


def announce(session, citing: list) -> None:
    """One inbox entry per map for the feed papers found citing its milestones in this run; its followers see it."""
    from athena.database import inbox
    names = lambda cites: list(dict.fromkeys(c.get("named_method") or c["title"] for c in cites))  # noqa: E731
    per_map, map_names = defaultdict(list), {}
    for item, cites in citing:
        for slug in dict.fromkeys(c["topic"] for c in cites):
            per_map[slug].append((item, [c for c in cites if c["topic"] == slug]))
            map_names[slug] = next(c["topic_name"] for c in cites if c["topic"] == slug)
    ids = _topic_ids(session, list(per_map))
    for slug, entries in per_map.items():
        n = len(entries)
        inbox.add_event(
            session, "feed_citations",
            f"{n} new {'paper cites' if n == 1 else 'papers cite'} milestones of {map_names[slug]}",
            "; ".join(item.title for item, _ in entries[:3]) + ("; ..." if n > 3 else ""), f"/evolution/{slug}",
            ids.get(slug),
            {"items": [{"id": str(item.id), "title": item.title, "cites": names(cites)[:5]}
                       for item, cites in entries[:20]]})


def _topic_ids(session, slugs: list[str]) -> dict:
    from athena.core.models import EvoTopic
    return dict(session.execute(select(EvoTopic.slug, EvoTopic.id).where(EvoTopic.slug.in_(slugs))).all())


def check_feed_citations(s2=None, openalex=None, now: datetime | None = None) -> dict:
    """Which map milestones each recent feed paper cites."""
    from athena.core.models import ContentCategory, ContentItem, EvoPaper
    from athena.database import evolution as db
    from athena.database.db import SessionLocal
    from athena.evolution.fulltext import PaperIndex
    from athena.core.openalex import OpenAlexClient
    from athena.core.semantic_scholar import SemanticScholarClient

    now = now or datetime.now(timezone.utc)
    s2 = s2 or SemanticScholarClient()
    summary = {"checked": 0, "with_references": 0, "citing_milestones": 0}
    with SessionLocal() as session:
        items = list(session.execute(select(ContentItem).where(
            ContentItem.category == ContentCategory.PAPER,
            ContentItem.published_at >= now - timedelta(days=FEED_DAYS))).scalars())
        due = {}
        for item in items:
            arxiv = arxiv_id_from_url(item.url)
            state = (item.extra_data or {}).get("evolution") or {}
            if not arxiv or state.get("references"):
                continue  # done once its references were found
            checked = state.get("checked_at")
            if checked and datetime.fromisoformat(checked) > now - timedelta(days=RECHECK_DAYS):
                continue
            due[arxiv] = item
        if not due:
            return summary
        index = PaperIndex(db.known_papers(session))
        refs: dict[str, set[UUID]] = {}
        counts: dict[str, int] = {}
        found = s2.get_papers([f"ARXIV:{a}" for a in due], max_age=RECHECK_DAYS * 86400)
        for arxiv in due:
            paper = found.get(f"ARXIV:{arxiv}")
            if paper and paper.references:
                counts[arxiv] = len(paper.references)
                refs[arxiv] = {pid for r in paper.references if (pid := index.find_s2(r, []))}
        missing = [a for a in due if a not in refs]
        if missing:
            try:
                works = (openalex or OpenAlexClient()).get_works_by_doi([f"10.48550/arxiv.{a}" for a in missing])
            except Exception as exc:  # OpenAlex's allowance or the network: Semantic Scholar's answers still count
                logger.warning(f"Feed citations: OpenAlex lookup failed: {exc}")
                works = []
            known = {oid: pid for pid, oid in session.execute(select(EvoPaper.id, EvoPaper.openalex_id))}
            for work in works:
                if work.arxiv_id in due and work.referenced_works:
                    counts[work.arxiv_id] = len(work.referenced_works)
                    refs[work.arxiv_id] = {known[w] for w in work.referenced_works if w in known}
        membership = db.map_membership(session, list({pid for ids in refs.values() for pid in ids}))
        citing = []
        for arxiv, item in due.items():
            cites, per_map = milestone_citations(refs.get(arxiv, set()), membership)
            item.extra_data = {**(item.extra_data or {}), "evolution": {
                "checked_at": now.isoformat(), "references": counts.get(arxiv, 0), "maps": per_map, "cites": cites}}
            summary["checked"] += 1
            summary["with_references"] += arxiv in counts
            summary["citing_milestones"] += bool(cites)
            if cites:
                citing.append((item, cites))
        if citing:
            announce(session, citing)
        session.commit()
    logger.info(f"Feed citations: {summary}")
    return summary
