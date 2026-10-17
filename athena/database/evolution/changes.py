"""
Snapshots and the changelog between them, and which maps are due for a refresh.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from athena.core.models import EvoGapTheme, EvoGapThemeMember, EvoSnapshot, EvoTopic
from athena.evolution.config import TopicConfig
from athena.database.evolution.topics import _overrides, _topic_rows, effective_milestone, method_names, topic_summary


def snapshot_state(session: Session, topic: EvoTopic) -> tuple[dict, dict[str, dict]]:
    """The topic as it stands: milestones, gap themes with their members, paper IDs; and each paper's
    title, year and score (for naming the best new papers)."""
    overrides = _overrides(session, topic.id)
    rows = _topic_rows(session, topic.id)
    milestones = [(tp, p) for tp, p in rows
                  if effective_milestone(tp.is_milestone_auto, overrides[p.id].action if p.id in overrides else None)]
    names = method_names(session, {p.id: p.title for _, p in milestones})
    themes = list(session.execute(select(EvoGapTheme).where(EvoGapTheme.topic_id == topic.id)).scalars())
    members: dict[UUID, list[str]] = defaultdict(list)
    for theme_id, gap_id in session.execute(select(EvoGapThemeMember.theme_id, EvoGapThemeMember.gap_id).where(
            EvoGapThemeMember.theme_id.in_([t.id for t in themes]))):
        members[theme_id].append(str(gap_id))
    state = {
        "milestones": sorted(({"paper_id": str(p.id), "title": p.title, "year": p.year,
                               "named_method": names.get(p.id) or tp.named_method,
                               "score": round(tp.milestone_score or 0.0, 3)} for tp, p in milestones),
                             key=lambda m: (m["year"] or 0, m["title"])),
        "themes": [{"label": t.label, "status": t.status, "size": t.size, "first_year": t.first_year,
                    "last_year": t.last_year, "members": sorted(members.get(t.id, []))} for t in themes],
        "paper_ids": sorted(str(p.id) for _, p in rows),
    }
    info = {str(p.id): {"title": p.title, "year": p.year, "score": tp.milestone_score or 0.0} for tp, p in rows}
    return state, info


def take_snapshot(session: Session, topic: EvoTopic, reason: str) -> dict:
    """Store the topic's current state and what changed since the last snapshot."""
    from athena.evolution.snapshots import OPEN, diff
    state, info = snapshot_state(session, topic)
    last = session.execute(select(EvoSnapshot).where(EvoSnapshot.topic_id == topic.id)
                           .order_by(EvoSnapshot.taken_at.desc()).limit(1)).scalar_one_or_none()
    before = {"milestones": last.milestones, "themes": last.themes, "paper_ids": last.paper_ids} if last else None
    stats = {"papers": len(state["paper_ids"]), "milestones": len(state["milestones"]),
             "themes": len(state["themes"]), "open_themes": sum(t["status"] in OPEN for t in state["themes"])}
    row = EvoSnapshot(topic_id=topic.id, taken_at=datetime.now(timezone.utc), built_at=topic.built_at,
                      reason=reason, stats=stats, changes=diff(before, state, info), **state)
    session.add(row)
    _announce(session, topic, reason, row.changes, stats, first=before is None)
    session.commit()
    return {"id": str(row.id), "stats": stats, "changes": row.changes}


def _announce(session: Session, topic: EvoTopic, reason: str, changes: dict | None, stats: dict,
              first: bool) -> None:
    """Inbox entries for a snapshot: a map's first build, or a later one that changed something."""
    from athena.database import inbox
    from athena.evolution.snapshots import is_empty, summary
    if reason == "baseline":
        return  # recorded for an existing map, not news
    if first:
        inbox.add_event(session, "map_new", f"New map: {topic.name}",
                        f"{stats['papers']} papers, {stats['milestones']} milestones", f"/evolution/{topic.slug}",
                        topic.id, {"stats": stats})
    elif changes is not None and not is_empty(changes):
        inbox.add_event(session, "map_changes", f"{topic.name} updated", "; ".join(summary(changes)) or None,
                        f"/evolution/{topic.slug}?tab=changes", topic.id,
                        {"reason": reason, "counts": {k: (len(v) if isinstance(v, list) else v)
                                                      for k, v in changes.items()}})


def topic_changes(session: Session, topic: EvoTopic, limit: int = 20) -> dict:
    """Snapshots newest first, each with what changed since the one before."""
    rows = session.execute(select(EvoSnapshot.id, EvoSnapshot.taken_at, EvoSnapshot.reason, EvoSnapshot.built_at,
                                  EvoSnapshot.stats, EvoSnapshot.changes)
                           .where(EvoSnapshot.topic_id == topic.id)
                           .order_by(EvoSnapshot.taken_at.desc()).limit(limit)).all()
    config = TopicConfig.from_dict(topic.config)
    return {"topic": topic_summary(topic), "refresh_days": config.refresh_days,
            "snapshots": [{"id": str(r.id), "taken_at": r.taken_at.isoformat(), "reason": r.reason,
                           "built_at": r.built_at.isoformat() if r.built_at else None, "stats": r.stats or {},
                           "changes": r.changes} for r in rows]}


def due_for_refresh(session: Session, now: datetime, limit: int) -> list[str]:
    """Built topics whose last build is older than their refresh interval, oldest first."""
    due = []
    for topic in session.execute(select(EvoTopic).where(EvoTopic.status == "ready", EvoTopic.built_at.isnot(None))
                                 .order_by(EvoTopic.built_at)).scalars():
        days = TopicConfig.from_dict(topic.config).refresh_days
        if days > 0 and topic.built_at <= now - timedelta(days=days):
            due.append(topic.slug)
    return due[:limit]
