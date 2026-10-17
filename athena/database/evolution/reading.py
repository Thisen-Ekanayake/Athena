"""
The reading path and its notes, and per-user read marks.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from athena.core.models import EvoCitation, EvoPaper, EvoPaperNote, EvoReadingProgress, EvoTopic, EvoTopicPaper
from athena.evolution.config import TopicConfig
from athena.evolution.eras import on_topic_method
from athena.evolution.reading_path import PathCandidate, build_path
from athena.database.evolution.graph import _node, _strict
from athena.database.evolution.topics import (
    _overrides, _topic_rows, effective_milestone, method_names, topic_eras, topic_summary,
)


NOTE_WHY = "why"


def current_notes(session: Session, topic: EvoTopic, paper_ids: list[UUID], kind: str = NOTE_WHY) -> dict[UUID, str]:
    """Notes written for the topic's current build; a rebuild makes the old ones stale."""
    if not paper_ids:
        return {}
    rows = session.execute(select(EvoPaperNote).where(
        EvoPaperNote.topic_id == topic.id, EvoPaperNote.paper_id.in_(paper_ids), EvoPaperNote.kind == kind)).scalars()
    return {n.paper_id: n.text for n in rows if n.built_at == topic.built_at}


def save_note(session: Session, topic: EvoTopic, paper_id: UUID, text: str, model: str,
              kind: str = NOTE_WHY) -> None:
    values = {"text": text, "model": model, "built_at": topic.built_at, "created_at": datetime.now(timezone.utc)}
    stmt = insert(EvoPaperNote).values(id=uuid4(), topic_id=topic.id, paper_id=paper_id, kind=kind, **values)
    session.execute(stmt.on_conflict_do_update(constraint="uq_evo_paper_note", set_=values))
    session.commit()


def read_papers(session: Session, user_id: UUID | None, paper_ids: list[UUID]) -> set[UUID]:
    if user_id is None or not paper_ids:
        return set()
    return set(session.execute(select(EvoReadingProgress.paper_id).where(
        EvoReadingProgress.user_id == user_id, EvoReadingProgress.paper_id.in_(paper_ids))).scalars())


def set_read(session: Session, user_id: UUID, paper_id: UUID, read: bool) -> bool:
    """Tick or untick a paper for a user, and the feed item that is the same paper. False if it is unknown."""
    from athena.database.personal import set_paper_read
    return set_paper_read(session, user_id, paper_id, read)


def reading_path(session: Session, topic: EvoTopic, user_id: UUID | None, n: int = 10) -> dict:
    """A survey, then milestones in year order: ``n`` papers, with notes, links between steps and read ticks."""
    overrides = _overrides(session, topic.id)
    rows = _topic_rows(session, topic.id)
    by_id = {p.id: (tp, p) for tp, p in rows}
    relevance_weight = TopicConfig.from_dict(topic.config).weights.relevance
    candidates = [
        PathCandidate(id=p.id, year=p.year, kind=tp.kind, milestone_score=tp.milestone_score or 0.0,
                      on_main_path=bool(tp.on_main_path),
                      # on_topic_method asks for a method paper too; here only the relevance counts
                      on_topic=on_topic_method("method", tp.score_detail, relevance_weight),
                      is_milestone=effective_milestone(tp.is_milestone_auto,
                                                       overrides[p.id].action if p.id in overrides else None))
        for tp, p in rows
    ]
    milestones = [c.id for c in candidates if c.is_milestone]
    surveys = {c.id: c for c in candidates if c.kind == "survey"}
    for citing, count in session.execute(
            select(EvoCitation.citing_id, func.count()).where(EvoCitation.citing_id.in_(list(surveys)),
                                                              EvoCitation.cited_id.in_(milestones))
            .group_by(EvoCitation.citing_id)):
        surveys[citing].milestones_cited = count
    survey, others, steps = build_path(candidates, n, topic_eras(topic, rows))
    path = ([survey] if survey else []) + steps
    ids = [c.id for c in path]
    names = method_names(session, {i: by_id[i][1].title for i in ids})
    notes = current_notes(session, topic, ids)
    read = read_papers(session, user_id, ids)
    position = {pid: i for i, pid in enumerate(ids)}
    cites: dict[UUID, set[UUID]] = defaultdict(set)
    for citing, cited in session.execute(select(EvoCitation.citing_id, EvoCitation.cited_id).where(
            EvoCitation.citing_id.in_(ids), EvoCitation.cited_id.in_(ids))):
        cites[citing].add(cited)
    fixes: dict[UUID, set[UUID]] = defaultdict(set)
    for ctx in _strict(session, citing=ids, cited=ids):
        fixes[ctx.citing_id].add(ctx.cited_id)

    def earlier(pid: UUID, targets: set[UUID]) -> list[int]:
        return sorted(position[t] + 1 for t in targets if position.get(t, len(ids)) < position[pid])

    def entry(c: PathCandidate) -> dict:
        tp, p = by_id[c.id]
        return _node(tp, p, overrides.get(c.id), names.get(c.id)) | {
            "position": position[c.id] + 1,
            "why": notes.get(c.id),
            "read": c.id in read,
            # Earlier steps this one cites, and earlier steps whose stated limitation it takes on (by number).
            "builds_on": earlier(c.id, cites.get(c.id, set())),
            "addresses": earlier(c.id, fixes.get(c.id, set())),
        }

    def other(c: PathCandidate) -> dict:
        tp, p = by_id[c.id]
        return _node(tp, p, overrides.get(c.id))

    return {
        "topic": topic_summary(topic),
        "n": n,
        "survey": entry(survey) if survey else None,
        "other_surveys": [other(c) for c in others],
        "steps": [entry(c) for c in steps],
        "read_count": len(read),
        "total": len(ids),
    }


def note_context(session: Session, topic: EvoTopic, paper_ids: list[UUID]) -> list[dict]:
    """What the note writer needs about each paper: title, year, name, abstract and the earlier papers in
    ``paper_ids`` it cites."""
    rows = {p.id: (tp, p) for tp, p in session.execute(
        select(EvoTopicPaper, EvoPaper).join(EvoPaper, EvoTopicPaper.paper_id == EvoPaper.id)
        .where(EvoTopicPaper.topic_id == topic.id, EvoPaper.id.in_(paper_ids))).all()}
    names = method_names(session, {pid: p.title for pid, (_, p) in rows.items()})
    cites: dict[UUID, set[UUID]] = defaultdict(set)
    for citing, cited in session.execute(select(EvoCitation.citing_id, EvoCitation.cited_id).where(
            EvoCitation.citing_id.in_(paper_ids), EvoCitation.cited_id.in_(paper_ids))):
        cites[citing].add(cited)
    out = []
    for i, pid in enumerate(paper_ids):
        if pid not in rows:
            continue
        tp, p = rows[pid]

        def label(other: UUID) -> str:
            _, q = rows[other]
            return f"{names.get(other) or q.title} ({q.year})"
        out.append({
            "paper_id": pid, "title": p.title, "year": p.year, "kind": tp.kind, "abstract": p.abstract,
            "name": names.get(pid) or tp.named_method,
            "builds_on": [label(o) for o in paper_ids[:i] if o in cites.get(pid, set()) and o in rows][-3:],
        })
    return out
