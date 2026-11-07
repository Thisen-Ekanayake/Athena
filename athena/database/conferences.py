"""
Reads and writes for conference proceedings (athena/conferences/): editions, topic shares over the years, venues side
by side, top papers, and the topic list.

An edition is one venue's papers of one year, of the chosen kinds (main, findings, journal). Venue ``all`` is the
whole family's year: no venue join, so a joint event's papers count once.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from athena.conferences import anthology
from athena.conferences import venues as V
from athena.core.models import ConfPaper, ConfSummary, ConfTopic, ConfVolume, ConfVolumeVenue

TOP_AWARDS = 30


def _scope(q, venue: str, kinds: list[str]):
    q = q.select_from(ConfPaper).join(ConfVolume, ConfVolume.id == ConfPaper.volume_id).where(
        ConfVolume.kind.in_(kinds))
    if venue != V.ALL:
        q = q.join(ConfVolumeVenue, ConfVolumeVenue.volume_id == ConfPaper.volume_id).where(
            ConfVolumeVenue.venue == venue)
    return q


def topics(session: Session) -> list[ConfTopic]:
    return list(session.execute(select(ConfTopic).order_by(ConfTopic.position, ConfTopic.id)).scalars())


def topic_brief(t: ConfTopic) -> dict:
    return {"id": t.id, "name": t.name, "description": t.description, "position": t.position}


def years(session: Session, venue: str, kinds: list[str]) -> dict[int, int]:
    """{year: papers} of a venue's editions."""
    q = _scope(select(ConfPaper.year, func.count()), venue, kinds).group_by(ConfPaper.year)
    return dict(session.execute(q).all())


def venues(session: Session) -> list[dict]:
    """Each venue with its editions, newest first, and paper counts by kind."""
    rows = session.execute(
        select(ConfVolumeVenue.venue, ConfVolume.year, ConfVolume.kind, func.sum(ConfVolume.paper_count))
        .join(ConfVolume, ConfVolume.id == ConfVolumeVenue.volume_id)
        .group_by(ConfVolumeVenue.venue, ConfVolume.year, ConfVolume.kind)).all()
    by_venue: dict[str, dict[int, dict[str, int]]] = {}
    for venue, year, kind, n in rows:
        by_venue.setdefault(venue, {}).setdefault(year, {})[kind] = int(n or 0)
    out = []
    for slug, v in V.VENUES.items():
        eds = by_venue.get(slug, {})
        out.append({"slug": slug, "name": v.name, "full_name": v.full_name, "journal": v.journal,
                    "years": sorted(eds, reverse=True),
                    "editions": [{"year": y, "papers": sum(eds[y].values())} for y in sorted(eds)],
                    "latest": max(eds) if eds else None,
                    "latest_papers": sum(eds[max(eds)].values()) if eds else 0,
                    "latest_kinds": eds[max(eds)] if eds else {},
                    "papers": sum(sum(k.values()) for k in eds.values())})
    return out


def topic_counts(session: Session, venue: str, year: int | None, kinds: list[str]) -> dict[int | None, int]:
    q = _scope(select(ConfPaper.topic_id, func.count()), venue, kinds)
    if year is not None:
        q = q.where(ConfPaper.year == year)
    return dict(session.execute(q.group_by(ConfPaper.topic_id)).all())


def kind_counts(session: Session, venue: str, year: int, kinds: list[str]) -> dict[str, int]:
    q = _scope(select(ConfVolume.kind, func.count()), venue, kinds).where(ConfPaper.year == year)
    return dict(session.execute(q.group_by(ConfVolume.kind)).all())


def shares(session: Session, venue: str, year: int, prev: int | None, kinds: list[str]) -> list[dict]:
    """Each topic's papers and share this edition and the previous one, biggest first. Papers not yet sorted are
    left out of the shares."""
    now = topic_counts(session, venue, year, kinds)
    before = topic_counts(session, venue, prev, kinds) if prev else {}
    n_now = sum(v for k, v in now.items() if k is not None)
    n_before = sum(v for k, v in before.items() if k is not None)
    out = []
    for t in topics(session):
        share = now.get(t.id, 0) / n_now if n_now else 0.0
        prev_share = before.get(t.id, 0) / n_before if n_before else None
        out.append({"id": t.id, "name": t.name, "papers": now.get(t.id, 0), "share": share,
                    "prev_papers": before.get(t.id, 0) if prev else None, "prev_share": prev_share,
                    "change": share - prev_share if prev_share is not None else None})
    return sorted(out, key=lambda r: -r["papers"])


def paper_brief(p: ConfPaper, topic_names: dict[int, str], kind: str | None = None) -> dict:
    return {"id": p.id, "title": p.title, "year": p.year, "authors": (p.authors or [])[:4],
            "author_count": len(p.authors or []), "awards": p.awards or [], "award_rank": p.award_rank,
            "citation_count": p.citation_count, "kind": kind,
            "topic": {"id": p.topic_id, "name": topic_names.get(p.topic_id)} if p.topic_id else None,
            "url": anthology.page_url(p.id), "pdf_url": anthology.pdf_url(p.id), "item_id": p.item_id}


def _names(session: Session) -> dict[int, str]:
    return {t.id: t.name for t in topics(session)}


def ranked(session: Session, venue: str, kinds: list[str], year: int | None = None, topic_id: int | None = None,
           awards_only: bool = False, offset: int = 0, limit: int = 20) -> tuple[list[dict], int]:
    """Papers of an edition (or of every year), award winners first, then by citations; and how many there are."""
    q = _scope(select(ConfPaper, ConfVolume.kind), venue, kinds)
    if year is not None:
        q = q.where(ConfPaper.year == year)
    if topic_id is not None:
        q = q.where(ConfPaper.topic_id == topic_id)
    if awards_only:
        q = q.where(ConfPaper.award_rank.is_not(None))
    total = session.execute(select(func.count()).select_from(q.subquery())).scalar() or 0
    rows = session.execute(q.order_by(ConfPaper.award_rank.is_(None), ConfPaper.award_rank,
                                      ConfPaper.citation_count.is_(None), ConfPaper.citation_count.desc(),
                                      ConfPaper.id).offset(offset).limit(limit)).all()
    names = _names(session)
    return [paper_brief(p, names, kind) for p, kind in rows], total


def previous_edition(session: Session, venue: str, year: int, kinds: list[str]) -> int | None:
    q = _scope(select(func.max(ConfPaper.year)), venue, kinds).where(ConfPaper.year < year)
    return session.execute(q).scalar()


def progress(session: Session, venue: str, year: int | None, kinds: list[str]) -> dict:
    """How much of an edition (or everything) is embedded and sorted, and has citation counts."""
    q = _scope(select(func.count(), func.count(ConfPaper.topic_id), func.count(ConfPaper.citations_at),
                      func.count(ConfPaper.abstract)), venue, kinds)
    if year is not None:
        q = q.where(ConfPaper.year == year)
    total, sorted_, cited, abstracts = session.execute(q).one()
    return {"papers": total, "sorted": sorted_, "cited": cited, "abstracts": abstracts}


def overview(session: Session, venue: str, year: int | None, kinds: list[str]) -> dict | None:
    """One edition: counts, topic shares against the previous edition, award winners, rising and falling terms
    and the written summary. Without ``year``, the latest. None for a venue with no papers."""
    from athena.conferences import terms
    eds = years(session, venue, kinds)
    if not eds:
        return None
    year = year if year in eds else max(eds)
    prev = previous_edition(session, venue, year, kinds)
    awards, _ = ranked(session, venue, kinds, year=year, awards_only=True, limit=TOP_AWARDS)
    summary = session.get(ConfSummary, (venue, year))
    return {
        "venue": venue, "name": V.label(venue), "year": year, "previous_year": prev, "kinds": kinds,
        "years": [{"year": y, "papers": eds[y]} for y in sorted(eds)],
        "papers": eds[year], "by_kind": kind_counts(session, venue, year, kinds),
        "topics": shares(session, venue, year, prev, kinds),
        "awards": awards,
        "terms": terms.for_edition(session, venue, year),
        "summary": {"text": summary.text, "written_at": summary.written_at, "model": summary.model}
        if summary else None,
        "progress": progress(session, venue, year, kinds),
    }


def trends(session: Session, venue: str, kinds: list[str], start: int | None = None, end: int | None = None,
           ) -> dict:
    """Papers per topic per year, with each year's sorted total, for shares over time."""
    q = _scope(select(ConfPaper.year, ConfPaper.topic_id, func.count()), venue, kinds)
    if start:
        q = q.where(ConfPaper.year >= start)
    if end:
        q = q.where(ConfPaper.year <= end)
    by_year: dict[int, dict] = {}
    for year, topic_id, n in session.execute(q.group_by(ConfPaper.year, ConfPaper.topic_id)).all():
        row = by_year.setdefault(year, {"year": year, "papers": 0, "sorted": 0, "topics": {}})
        row["papers"] += n
        if topic_id is not None:
            row["sorted"] += n
            row["topics"][str(topic_id)] = n
    return {"venue": venue, "name": V.label(venue), "kinds": kinds,
            "topics": [topic_brief(t) for t in topics(session)],
            "years": [by_year[y] for y in sorted(by_year)]}


def compare(session: Session, venue_slugs: list[str], year: int, kinds: list[str]) -> dict:
    """Venues side by side in one year: each one's topic shares (venues without an edition that year are listed
    as missing)."""
    out, missing = [], []
    for slug in venue_slugs:
        counts = topic_counts(session, slug, year, kinds)
        total = sum(counts.values())
        if not total:
            missing.append(slug)
            continue
        sorted_ = sum(v for k, v in counts.items() if k is not None)
        out.append({"venue": slug, "name": V.label(slug), "papers": total, "sorted": sorted_,
                    "topics": {str(k): v for k, v in counts.items() if k is not None}})
    return {"year": year, "kinds": kinds, "topics": [topic_brief(t) for t in topics(session)], "venues": out,
            "missing": missing}


def paper(session: Session, paper_id: str) -> dict | None:
    p = session.get(ConfPaper, paper_id)
    if p is None:
        return None
    vol = session.get(ConfVolume, p.volume_id)
    venue_slugs = list(session.execute(select(ConfVolumeVenue.venue).where(
        ConfVolumeVenue.volume_id == p.volume_id)).scalars())
    return paper_brief(p, _names(session), vol.kind if vol else None) | {
        "authors": p.authors or [], "abstract": p.abstract, "abstract_from": p.abstract_from, "doi": p.doi,
        "volume": {"id": p.volume_id, "title": vol.title if vol else None},
        "venues": [{"slug": s, "name": V.label(s)} for s in venue_slugs if s in V.VENUES],
        "topic_score": p.topic_score, "citations_at": p.citations_at,
    }


def papers_by_id(session: Session, ids: list[str]) -> list[dict]:
    if not ids:
        return []
    rows = {p.id: (p, k) for p, k in session.execute(
        select(ConfPaper, ConfVolume.kind).join(ConfVolume, ConfVolume.id == ConfPaper.volume_id)
        .where(ConfPaper.id.in_(ids))).all()}
    names = _names(session)
    return [paper_brief(rows[i][0], names, rows[i][1]) for i in ids if i in rows]


def edition_numbers(session: Session, venue: str, year: int, kinds: list[str]) -> dict:
    """What a summary is written from: the numbers of ``overview`` without the papers' details."""
    view = overview(session, venue, year, kinds)
    if view is None:
        return {}
    return {
        "venue": view["name"], "year": year, "previous_year": view["previous_year"], "papers": view["papers"],
        "by_kind": view["by_kind"],
        "topics": [{"name": t["name"], "share": round(t["share"] * 100, 1),
                    "change": round(t["change"] * 100, 1) if t["change"] is not None else None}
                   for t in view["topics"][:12]],
        "rising": [t["term"] for t in view["terms"]["rising"][:12]],
        "falling": [t["term"] for t in view["terms"]["falling"][:8]],
        # By title, so a change in citations (which orders the page's list) does not count as new numbers
        "awards": sorted(({"title": a["title"], "award": (a["awards"] or [""])[0]} for a in view["awards"]
                          if a["award_rank"] is not None and a["award_rank"] <= 1), key=lambda a: a["title"])[:10],
        "sorted": view["progress"]["sorted"],
    }
