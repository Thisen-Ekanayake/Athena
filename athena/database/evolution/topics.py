"""
Topics (maps): creating, finding, building and listing them, and what every part of a map reads: its papers,
milestone overrides, eras, method names and the cache versions.
"""
from __future__ import annotations

import os
from collections import defaultdict
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from athena.core.models import (
    EvoCitation, EvoCitationContext, EvoGapTheme, EvoMainPathEdge, EvoMilestoneOverride, EvoPaper, EvoSnapshot,
    EvoTopic, EvoTopicPaper,
)
from athena.database.db import SessionLocal
from athena.evolution.config import TopicConfig
from athena.evolution.eras import stored_eras
from athena.evolution.names import detect_method_name

if TYPE_CHECKING:
    from athena.evolution.corpus import Corpus
    from athena.evolution.milestones import TopicScores


OVERRIDE_ACTIONS = {"pin", "unpin", "reset"}


# Loose links below this cosine similarity are not shown. Stored links go down to the lane's floor (0.3),
# so the cutoff can change without recomputing them. Set by eye on samples of the first run: below 0.55
# matches were mostly unrelated, 0.65-0.70 about half right, 0.70 and above mostly right.
LOOSE_MIN_SCORE = float(os.getenv("EVOLUTION_LOOSE_MIN_SCORE", "0.68"))


# Citing-sentence labels that state a limitation of the cited paper; with ``attributed`` they make a strict link.
LIMITATION_LABELS = ("addresses_limitation", "criticises")


_BATCH = 500


def effective_milestone(auto: bool, override: str | None) -> bool:
    """A person's pin or unpin wins over the automatic pick."""
    if override == "pin":
        return True
    if override == "unpin":
        return False
    return auto


def _chunks(rows: list, size: int = _BATCH):
    for start in range(0, len(rows), size):
        yield rows[start:start + size]


def upsert_topic(slug: str, name: str, aliases: list[str], description: str, seeds: list[dict],
                 config: dict, origin: str = "curated", query: str | None = None,
                 created_by: UUID | None = None) -> None:
    values = {"slug": slug, "name": name, "aliases": aliases, "description": description, "seeds": seeds,
              "config": config, "origin": origin, "query": query}
    with SessionLocal() as session:
        stmt = insert(EvoTopic).values(id=uuid4(), status="pending", created_by=created_by, **values)
        stmt = stmt.on_conflict_do_update(index_elements=["slug"], set_=values)
        session.execute(stmt)
        session.commit()


def get_topic(session: Session, slug: str) -> EvoTopic | None:
    return session.execute(select(EvoTopic).where(EvoTopic.slug == slug)).scalar_one_or_none()


def set_topic_status(slug: str, status: str, status_detail: str | None = None, stats: dict | None = None) -> None:
    """``stats`` marks a finished build: it is stored, and ``built_at`` moves on so cached reads expire."""
    with SessionLocal() as session:
        topic = get_topic(session, slug)
        if topic is None:
            return
        topic.status = status
        topic.status_detail = status_detail
        if stats is not None:
            topic.build_stats = stats
            topic.built_at = datetime.now(timezone.utc)
        session.commit()


def delete_topic(session: Session, topic: EvoTopic) -> None:
    """Remove a topic with its scores, main path, overrides and gap themes. Papers are shared and stay."""
    # The database cascades to every topic table, in one statement rather than one per row.
    session.execute(delete(EvoTopic).where(EvoTopic.id == topic.id))
    session.commit()


def active_search_builds(session: Session) -> int:
    """Search-built topics waiting for, or in, their first build."""
    return session.execute(select(func.count()).select_from(EvoTopic).where(
        EvoTopic.origin == "search", EvoTopic.status.in_(["pending", "building"]))).scalar_one()


def slug_taken(session: Session, slug: str) -> bool:
    return session.execute(select(EvoTopic.id).where(EvoTopic.slug == slug)).first() is not None


def find_topic(session: Session, query: str) -> EvoTopic | None:
    """Match a free-text query against topic names and aliases ("lora fine-tuning" -> PEFT)."""
    q = " ".join(query.lower().replace("-", " ").split())
    if len(q) < 2:
        return None
    matches = []
    for topic in session.execute(select(EvoTopic)).scalars():
        for name in [topic.slug.replace("-", " "), topic.name, *(topic.aliases or [])]:
            n = " ".join(name.lower().replace("-", " ").split())
            if n == q or (len(n) >= 3 and f" {n} " in f" {q} ") or (len(q) >= 3 and q in n):
                # Prefer built topics, then the most specific (longest) matching name.
                matches.append((topic.status == "ready", len(n), topic))
    return max(matches, key=lambda m: m[:2])[2] if matches else None


def _overrides(session: Session, topic_id) -> dict:
    rows = session.execute(select(EvoMilestoneOverride).where(EvoMilestoneOverride.topic_id == topic_id)).scalars()
    return {o.paper_id: o for o in rows}


def _topic_rows(session: Session, topic_id) -> list[tuple[EvoTopicPaper, EvoPaper]]:
    return session.execute(
        select(EvoTopicPaper, EvoPaper)
        .join(EvoPaper, EvoTopicPaper.paper_id == EvoPaper.id)
        .where(EvoTopicPaper.topic_id == topic_id)
    ).all()


def list_topics(session: Session) -> list[dict]:
    out = []
    changes = latest_changes(session)
    for topic in session.execute(select(EvoTopic).order_by(EvoTopic.name)).scalars():
        rows = _topic_rows(session, topic.id)
        overrides = _overrides(session, topic.id)
        milestones = sum(
            effective_milestone(tp.is_milestone_auto, overrides[p.id].action if p.id in overrides else None)
            for tp, p in rows
        )
        out.append(topic_summary(topic) | {"paper_count": len(rows), "milestone_count": milestones,
                                           "last_change": changes.get(topic.slug)})
    return out


def topic_summary(topic: EvoTopic) -> dict:
    return {
        "id": str(topic.id) if getattr(topic, "id", None) else None,
        "slug": topic.slug,
        "name": topic.name,
        "aliases": topic.aliases or [],
        "description": topic.description,
        "status": topic.status,
        "status_detail": topic.status_detail,
        "built_at": topic.built_at.isoformat() if topic.built_at else None,
        "origin": getattr(topic, "origin", None) or "curated",
        "query": getattr(topic, "query", None),
        "build_stats": getattr(topic, "build_stats", None) or {},
        "created_by": str(topic.created_by) if getattr(topic, "created_by", None) else None,
    }


def _merge_paper(oid: str, paper, existing: EvoPaper | None, now: datetime) -> dict:
    """Combine a build's view of a paper with what is stored; papers are shared across topics.

    Without this, the last topic built wins: building PEFT after object detection reset R-CNN's
    seed-corrected year and arXiv ID. Seed metadata wins, then a year read from an arXiv ID (it records
    first appearance exactly), then the earliest other year; links are only ever added.
    """
    w = paper.work
    title, year, year_source = w.title[:1000], paper.year, paper.year_source
    arxiv_id, oa_pdf_url, is_oa, abstract = w.arxiv_id, w.oa_pdf_url, w.is_oa, w.abstract
    s2_paper_id, s2_cited_by_count = w.s2_paper_id, w.s2_cited_by_count
    status = None
    if existing is not None:
        if existing.year_source == "seed" and year_source != "seed":
            title, year, year_source = existing.title, existing.year, existing.year_source
        elif year_source in ("seed", "arxiv"):
            pass
        elif existing.year_source == "arxiv" or (existing.year and (year is None or existing.year < year)):
            year, year_source = existing.year, existing.year_source
        arxiv_id = arxiv_id or existing.arxiv_id
        oa_pdf_url = oa_pdf_url or existing.oa_pdf_url
        is_oa = bool(is_oa or existing.is_oa)
        abstract = abstract or existing.abstract
        s2_paper_id = s2_paper_id or existing.s2_paper_id
        s2_cited_by_count = s2_cited_by_count or existing.s2_cited_by_count
        if existing.full_text_status in ("parsed", "failed"):
            status = existing.full_text_status  # a later phase already processed the full text
    return {
        "id": existing.id if existing is not None else uuid4(), "openalex_id": oid, "doi": w.doi,
        "arxiv_id": arxiv_id, "title": title, "abstract": abstract, "year": year, "year_source": year_source,
        "openalex_year": w.year, "venue": w.venue, "work_type": w.work_type, "authors": w.authors,
        # A build from an older cache entry may lack them; keep what a backfill stored.
        "authorships": w.authorships or getattr(existing, "authorships", None) or [],
        "cited_by_count": w.cited_by_count, "s2_paper_id": s2_paper_id, "s2_cited_by_count": s2_cited_by_count,
        "primary_topic": w.primary_topic, "is_oa": is_oa,
        "oa_pdf_url": oa_pdf_url,
        "full_text_status": status or ("available" if (arxiv_id or oa_pdf_url) else "unavailable"),
        "merged_ids": paper.merged_ids, "updated_at": now,
    }


def save_topic_build(slug: str, corpus: "Corpus", scores: "TopicScores") -> None:
    """Replace a topic's papers, scores and main path with a fresh build. Overrides are kept."""
    now = datetime.now(timezone.utc)
    with SessionLocal() as session:
        topic = get_topic(session, slug)
        if topic is None:
            raise ValueError(f"Unknown topic {slug!r}")

        existing = {e.openalex_id: e for e in session.execute(
            select(EvoPaper).where(EvoPaper.openalex_id.in_(list(corpus.papers)))).scalars()}
        paper_rows = [_merge_paper(oid, p, existing.get(oid), now) for oid, p in corpus.papers.items()]
        for chunk in _chunks(paper_rows):
            stmt = insert(EvoPaper).values(chunk)
            updates = {c: stmt.excluded[c] for c in chunk[0] if c not in ("id", "openalex_id")}
            session.execute(stmt.on_conflict_do_update(index_elements=["openalex_id"], set_=updates))

        ids = dict(session.execute(
            select(EvoPaper.openalex_id, EvoPaper.id).where(EvoPaper.openalex_id.in_(list(corpus.papers)))
        ).all())

        session.execute(delete(EvoTopicPaper).where(EvoTopicPaper.topic_id == topic.id))
        tp_rows = []
        for oid, p in corpus.papers.items():
            s = scores.papers[oid]
            tp_rows.append({
                "id": uuid4(), "topic_id": topic.id, "paper_id": ids[oid], "role": p.role, "kind": s.kind,
                "in_degree": s.in_degree, "out_degree": s.out_degree, "pagerank": s.pagerank,
                "citation_percentile": s.citation_score, "specificity": s.specificity,
                "on_main_path": s.on_main_path, "named_method": s.named_method,
                "milestone_score": s.milestone_score, "is_milestone_auto": s.is_milestone_auto,
                "score_detail": s.detail,
            })
        for chunk in _chunks(tp_rows):
            session.execute(insert(EvoTopicPaper).values(chunk))

        cite_rows = [{"id": uuid4(), "citing_id": ids[a], "cited_id": ids[b],
                      "source": corpus.edge_sources.get((a, b), "openalex")} for a, b in corpus.edges]
        for chunk in _chunks(cite_rows):
            session.execute(insert(EvoCitation).values(chunk).on_conflict_do_nothing(constraint="uq_evo_citation"))

        session.execute(delete(EvoMainPathEdge).where(EvoMainPathEdge.topic_id == topic.id))
        mp_rows = [{"id": uuid4(), "topic_id": topic.id, "citing_id": ids[a], "cited_id": ids[b], "spc_weight": w}
                   for a, b, w in scores.main_path]
        if mp_rows:
            session.execute(insert(EvoMainPathEdge).values(mp_rows))
        session.commit()


def labels_version(session: Session) -> str:
    """Changes whenever full text, labels or gap themes change, which happens without a topic rebuild."""
    count, last = session.execute(select(func.count(EvoCitationContext.id),
                                         func.max(EvoCitationContext.labelled_at))).one()
    themes = session.execute(select(func.max(EvoGapTheme.built_at))).scalar()
    stamp = lambda t: int(t.timestamp()) if t else 0  # noqa: E731
    return f"{count}-{stamp(last)}-{stamp(themes)}"


def method_names(session: Session, papers: dict[UUID, str]) -> dict[UUID, str]:
    """Names citing sentences use for each paper ({id: title} in, {id: name} out)."""
    if not papers:
        return {}
    mentions: dict[UUID, list[tuple[UUID, str]]] = defaultdict(list)
    citers: dict[UUID, set[UUID]] = defaultdict(set)
    for cited, citing, words in session.execute(
            select(EvoCitationContext.cited_id, EvoCitationContext.citing_id, EvoCitationContext.mention)
            .where(EvoCitationContext.cited_id.in_(list(papers))).distinct()):
        citers[cited].add(citing)
        if words:
            mentions[cited].append((citing, words))
    out = {}
    for pid, pairs in mentions.items():
        name = detect_method_name(pairs, papers[pid], len(citers[pid]))
        if name:
            out[pid] = name
    return out


def topic_eras(topic: EvoTopic, rows: list[tuple[EvoTopicPaper, EvoPaper]]) -> list[tuple[int, int]]:
    """The eras milestones were picked in, from a built topic's stored rows."""
    config = TopicConfig.from_dict(topic.config)
    return stored_eras(((tp.kind, tp.score_detail, p.year) for tp, p in rows), config.eras, config.max_era_years,
                       config.weights.relevance)


def maps_version(session: Session) -> str:
    """Changes when any map is built or deleted."""
    latest, count = session.execute(select(func.max(EvoTopic.built_at), func.count(EvoTopic.id))).one()
    return f"{int(latest.timestamp()) if latest else 0}-{count}"


def latest_changes(session: Session) -> dict[str, dict]:
    """Each topic's latest snapshot that changed something, for the topic cards."""
    out = {}
    # Only the changes: a snapshot's other columns hold every paper ID of the map.
    rows = session.execute(select(EvoSnapshot.taken_at, EvoSnapshot.changes, EvoTopic.slug)
                           .join(EvoTopic, EvoSnapshot.topic_id == EvoTopic.id)
                           .where(EvoSnapshot.changes.isnot(None)).order_by(EvoSnapshot.taken_at.desc())).all()
    for taken_at, changes, slug in rows:
        c = changes or {}
        counts = {"new_milestones": len(c.get("new_milestones", [])), "new_gaps": len(c.get("new_gaps", [])),
                  "solved_gaps": len(c.get("solved_gaps", [])), "papers_added": c.get("papers_added", 0)}
        if slug not in out and any(counts.values()):
            out[slug] = {"taken_at": taken_at.isoformat(), **counts}
    return out


def save_cited_name(session: Session, paper_id: UUID, value: dict) -> None:
    session.execute(update(EvoPaper).where(EvoPaper.id == paper_id).values(cited_name=value))
    session.commit()


def cited_names_fetched_since(session: Session, paper_ids: list[UUID], days: int) -> set[UUID]:
    """Papers whose cited name was fetched in the last ``days`` days."""
    cutoff = datetime.now(timezone.utc).timestamp() - days * 86400
    out = set()
    for pid, value in session.execute(select(EvoPaper.id, EvoPaper.cited_name).where(
            EvoPaper.id.in_(paper_ids), EvoPaper.cited_name.isnot(None))):
        try:
            if datetime.fromisoformat(value["fetched_at"]).timestamp() >= cutoff:
                out.add(pid)
        except (KeyError, TypeError, ValueError):
            continue
    return out


def milestone_ids(session: Session, topic: EvoTopic) -> list[UUID]:
    """The topic's milestones (pins applied), oldest first."""
    overrides = _overrides(session, topic.id)
    rows = [(p.year or 0, p.id) for tp, p in _topic_rows(session, topic.id)
            if effective_milestone(tp.is_milestone_auto, overrides[p.id].action if p.id in overrides else None)]
    return [pid for _, pid in sorted(rows)]


def set_override(session: Session, topic: EvoTopic, paper_id: UUID, action: str, note: str | None) -> bool:
    """Pin, unpin, or reset a milestone. Returns False if the paper is not in the topic."""
    if action not in OVERRIDE_ACTIONS:
        raise ValueError(f"action must be one of {sorted(OVERRIDE_ACTIONS)}")
    in_topic = session.execute(
        select(EvoTopicPaper.id).where(EvoTopicPaper.topic_id == topic.id, EvoTopicPaper.paper_id == paper_id)
    ).first()
    if in_topic is None:
        return False
    if action == "reset":
        session.execute(delete(EvoMilestoneOverride).where(
            EvoMilestoneOverride.topic_id == topic.id, EvoMilestoneOverride.paper_id == paper_id))
    else:
        stmt = insert(EvoMilestoneOverride).values(id=uuid4(), topic_id=topic.id, paper_id=paper_id,
                                                   action=action, note=note)
        session.execute(stmt.on_conflict_do_update(
            constraint="uq_evo_milestone_override",
            set_={"action": action, "note": note, "created_at": datetime.now(timezone.utc)},
        ))
    session.commit()
    return True
