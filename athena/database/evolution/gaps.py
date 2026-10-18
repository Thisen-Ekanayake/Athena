"""
Gaps: the statements, their labels and vectors, loose links to later papers, and the themes they form.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, aliased

from athena.core.models import (
    EvoCitationContext, EvoGapStatement, EvoGapTheme, EvoGapThemeMember, EvoLooseLink, EvoPaper, EvoTopic,
)
from athena.database.db import SessionLocal
from athena.database.evolution.topics import (
    LIMITATION_LABELS, LOOSE_MIN_SCORE, _chunks, _overrides, _topic_rows, effective_milestone, method_names,
    topic_summary,
)


def gap_export_rows(session: Session, topic: EvoTopic) -> list[dict]:
    """Every statement in the topic's gap themes, with its theme, for the CSV export."""
    in_topic = {p.id: p for _, p in _topic_rows(session, topic.id)}
    order = {"persisting": 0, "new": 1, "addressed": 2, "quiet": 3}
    themes = sorted(session.execute(select(EvoGapTheme).where(EvoGapTheme.topic_id == topic.id)).scalars(),
                    key=lambda t: (order.get(t.status, 4), -t.size))
    members: dict[UUID, list[EvoGapStatement]] = defaultdict(list)
    for theme_id, gap in session.execute(
            select(EvoGapThemeMember.theme_id, EvoGapStatement)
            .join(EvoGapStatement, EvoGapThemeMember.gap_id == EvoGapStatement.id)
            .where(EvoGapThemeMember.theme_id.in_([t.id for t in themes]))):
        members[theme_id].append(gap)
    out = []
    for t in themes:
        for g in sorted(members.get(t.id, []), key=lambda g: (in_topic[g.source_paper_id].year or 0
                                                              if g.source_paper_id in in_topic else 0)):
            paper, source = in_topic.get(g.paper_id), in_topic.get(g.source_paper_id)
            out.append({
                "theme": t.label, "status": t.status, "first_year": t.first_year, "last_year": t.last_year,
                "theme_size": t.size, "statement": g.sentence, "origin": g.origin, "section": g.section_type,
                "paper": paper.title if paper else None, "paper_year": paper.year if paper else None,
                "stated_by": source.title if source and g.origin == "citing" else None,
                "stated_by_year": source.year if source and g.origin == "citing" else None,
            })
    return out


def sync_citing_gaps(session: Session) -> int:
    """Make every strict link a gap statement about the cited paper, and drop ones no longer strict."""
    from athena.evolution.fulltext import sentence_hash
    strict = {c.id: c for c in session.execute(
        select(EvoCitationContext).where(EvoCitationContext.label.in_(LIMITATION_LABELS),
                                         EvoCitationContext.attributed.is_(True))).scalars()}
    session.execute(delete(EvoGapStatement).where(
        EvoGapStatement.origin == "citing", EvoGapStatement.context_id.notin_(list(strict) or [uuid4()])))
    rows = [{"id": uuid4(), "paper_id": c.cited_id, "source_paper_id": c.citing_id, "origin": "citing",
             "context_id": c.id, "section_type": c.section_type, "sentence": c.sentence[:4000],
             "sentence_hash": sentence_hash(c.sentence), "label": "gap", "model": c.model,
             "labelled_at": c.labelled_at} for c in strict.values()]
    for chunk in _chunks(rows):
        session.execute(insert(EvoGapStatement).values(chunk).on_conflict_do_nothing(constraint="uq_evo_gap_statement"))
    session.commit()
    return len(rows)


def pending_gap_candidates(session: Session, limit: int) -> list[tuple[EvoGapStatement, str]]:
    return session.execute(
        select(EvoGapStatement, EvoPaper.title)
        .join(EvoPaper, EvoGapStatement.source_paper_id == EvoPaper.id)
        .where(EvoGapStatement.label.is_(None))
        .order_by(EvoGapStatement.source_paper_id)
        .limit(limit)
    ).all()


def save_gap_labels(session: Session, labels: list[dict]) -> None:
    """``labels``: [{id, label, model}]."""
    now = datetime.now(timezone.utc)
    for row in labels:
        session.execute(update(EvoGapStatement).where(EvoGapStatement.id == row["id"]).values(
            label=row["label"], model=row["model"], labelled_at=now))
    session.commit()


def pending_gap_vectors(session: Session, limit: int) -> list[tuple[EvoGapStatement, int | None]]:
    """Gap statements without a vector, with the year the stating paper appeared."""
    return session.execute(
        select(EvoGapStatement, EvoPaper.year)
        .join(EvoPaper, EvoGapStatement.source_paper_id == EvoPaper.id)
        .where(EvoGapStatement.label == "gap", EvoGapStatement.embedded_at.is_(None))
        .limit(limit)
    ).all()


def mark_gaps(session: Session, gap_ids: list[UUID], column: str) -> None:
    session.execute(update(EvoGapStatement).where(EvoGapStatement.id.in_(gap_ids))
                    .values({column: datetime.now(timezone.utc)}))
    session.commit()


def pending_loose(session: Session, limit: int) -> list[tuple[EvoGapStatement, int | None]]:
    """Embedded gap statements whose loose links have not been searched."""
    return session.execute(
        select(EvoGapStatement, EvoPaper.year)
        .join(EvoPaper, EvoGapStatement.source_paper_id == EvoPaper.id)
        .where(EvoGapStatement.embedded_at.isnot(None), EvoGapStatement.loose_checked_at.is_(None))
        .limit(limit)
    ).all()


def save_loose_links(session: Session, gap_id: UUID, links: list[dict]) -> None:
    """Replace a gap statement's loose links. ``links``: [{paper_id, chunk_id, score, cites}]."""
    session.execute(delete(EvoLooseLink).where(EvoLooseLink.gap_id == gap_id))
    if links:
        session.execute(insert(EvoLooseLink).values([{"id": uuid4(), "gap_id": gap_id, **link} for link in links]))


def topic_gap_rows(session: Session, topic: EvoTopic) -> list[dict]:
    """Gap statements about papers in the topic, stated by papers in the topic, with years and labels."""
    in_topic = {p.id: p for _, p in _topic_rows(session, topic.id)}
    source = aliased(EvoPaper)
    rows = session.execute(
        select(EvoGapStatement, source.year, EvoCitationContext.label)
        .join(source, EvoGapStatement.source_paper_id == source.id)
        .outerjoin(EvoCitationContext, EvoGapStatement.context_id == EvoCitationContext.id)
        .where(EvoGapStatement.label == "gap", EvoGapStatement.embedded_at.isnot(None),
               EvoGapStatement.paper_id.in_(list(in_topic)), EvoGapStatement.source_paper_id.in_(list(in_topic)))
    ).all()
    return [{"id": g.id, "paper_id": g.paper_id, "source_paper_id": g.source_paper_id, "origin": g.origin,
             "sentence": g.sentence, "section_type": g.section_type, "year": year,
             "fix": context_label == "addresses_limitation"} for g, year, context_label in rows]


def save_themes(topic_id: UUID, themes: list[dict]) -> None:
    """Replace a topic's gap themes. ``themes``: [{label, size, yearly, first_year, last_year, status, detail,
    members}]."""
    with SessionLocal() as session:
        session.execute(delete(EvoGapTheme).where(EvoGapTheme.topic_id == topic_id))
        for t in themes:
            theme_id = uuid4()
            session.execute(insert(EvoGapTheme).values(
                id=theme_id, topic_id=topic_id, **{k: v for k, v in t.items() if k != "members"}))
            session.execute(insert(EvoGapThemeMember).values([{"theme_id": theme_id, "gap_id": g}
                                                              for g in t["members"]]))
        session.commit()


def topic_gaps(session: Session, topic: EvoTopic, examples: int = 3) -> dict:
    """The topic's gap themes, persisting ones first, each with yearly counts, papers and example sentences."""
    overrides = _overrides(session, topic.id)
    rows = {p.id: (tp, p) for tp, p in _topic_rows(session, topic.id)}
    themes = list(session.execute(select(EvoGapTheme).where(EvoGapTheme.topic_id == topic.id)).scalars())
    members: dict[UUID, list[EvoGapStatement]] = defaultdict(list)
    for theme_id, gap in session.execute(
            select(EvoGapThemeMember.theme_id, EvoGapStatement)
            .join(EvoGapStatement, EvoGapThemeMember.gap_id == EvoGapStatement.id)
            .where(EvoGapThemeMember.theme_id.in_([t.id for t in themes]))):
        members[theme_id].append(gap)
    loose: dict[UUID, list[EvoLooseLink]] = defaultdict(list)
    gap_ids = [g.id for gs in members.values() for g in gs]
    for link in session.execute(select(EvoLooseLink).where(EvoLooseLink.gap_id.in_(gap_ids),
                                                           EvoLooseLink.score >= LOOSE_MIN_SCORE)).scalars():
        loose[link.gap_id].append(link)
    names = method_names(session, {pid: p.title for pid, (_, p) in rows.items()})

    def mini(pid) -> dict | None:
        if pid not in rows:
            return None
        tp, p = rows[pid]
        action = overrides[pid].action if pid in overrides else None
        return {"id": str(pid), "title": p.title, "year": p.year, "named_method": names.get(pid) or tp.named_method,
                "is_milestone": effective_milestone(tp.is_milestone_auto, action)}

    out = []
    for t in themes:
        gs = members.get(t.id, [])
        # Examples: own statements first (the paper on its own gap), then the most recent.
        picks = sorted(gs, key=lambda g: (g.origin != "own", -(rows[g.source_paper_id][1].year or 0)
                                          if g.source_paper_id in rows else 0))[:examples]
        candidates: dict[UUID, float] = {}
        for g in gs:
            for link in loose.get(g.id, []):
                if link.paper_id in rows and rows[link.paper_id][0].kind == "method":
                    candidates[link.paper_id] = max(link.score, candidates.get(link.paper_id, 0.0))
        detail = t.detail or {}
        out.append({
            "id": str(t.id), "label": t.label, "size": t.size, "status": t.status,
            "first_year": t.first_year, "last_year": t.last_year,
            "yearly": [{"year": int(y), "count": n} for y, n in sorted((t.yearly or {}).items())],
            "own": detail.get("own", 0), "citing": detail.get("citing", 0),
            "papers": [m for m in (mini(UUID(pid)) for pid in detail.get("papers", [])) if m],
            "fixed_by": [m for m in (mini(UUID(pid)) for pid in detail.get("fixed_by", [])) if m],
            "examples": [{"sentence": g.sentence, "origin": g.origin, "section_type": g.section_type,
                          "paper": mini(g.paper_id), "stated_by": mini(g.source_paper_id)} for g in picks],
            "loose_candidates": [{"paper": mini(pid), "score": round(score, 3)}
                                 for pid, score in sorted(candidates.items(), key=lambda kv: -kv[1])[:5]],
        })
    order = {"persisting": 0, "new": 1, "addressed": 2, "quiet": 3}
    out.sort(key=lambda t: (order.get(t["status"], 3), -t["size"]))
    latest = max((t.detail or {}).get("latest_topic_year") or 0 for t in themes) if themes else None
    return {"topic": topic_summary(topic), "latest_year": latest or None, "themes": out,
            "loose_min_score": LOOSE_MIN_SCORE}


def themes_to_label(session: Session) -> list[tuple[EvoGapTheme, str, list[str]]]:
    """Gap themes without a 9B label, with their topic's name and up to six statements (own text first)."""
    out = []
    themes = session.execute(select(EvoGapTheme, EvoTopic.name)
                             .join(EvoTopic, EvoGapTheme.topic_id == EvoTopic.id)).all()
    for theme, topic_name in themes:
        if (theme.detail or {}).get("label_model"):
            continue
        gaps = session.execute(select(EvoGapStatement)
                               .join(EvoGapThemeMember, EvoGapThemeMember.gap_id == EvoGapStatement.id)
                               .where(EvoGapThemeMember.theme_id == theme.id)).scalars().all()
        gaps = sorted(gaps, key=lambda g: g.origin != "own")[:6]
        out.append((theme, topic_name, [g.sentence[:400] for g in gaps]))
    return out


def save_theme_label(session: Session, theme_id: UUID, label: str, model: str) -> None:
    theme = session.get(EvoGapTheme, theme_id)
    theme.detail = {**(theme.detail or {}), "label_model": model, "terms_label": theme.label}
    theme.label = label
    session.commit()
