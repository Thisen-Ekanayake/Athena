"""
Where feed items sit in the maps, and recent feed papers that cite map milestones.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from athena.core.models import EvoGapStatement, EvoLooseLink, EvoMilestoneOverride, EvoPaper, EvoTopic, EvoTopicPaper
from athena.evolution.eras import find_era
from athena.database.evolution.graph import _strict
from athena.database.evolution.topics import (
    LOOSE_MIN_SCORE, _overrides, _topic_rows, effective_milestone, topic_eras, topic_summary,
)


def map_membership(session: Session, paper_ids: list[UUID]) -> dict[UUID, list[dict]]:
    """Each paper's place in every built map: topic, milestone or not (pins applied), and its name."""
    if not paper_ids:
        return {}
    rows = session.execute(
        select(EvoTopicPaper, EvoTopic, EvoPaper)
        .join(EvoTopic, EvoTopicPaper.topic_id == EvoTopic.id).join(EvoPaper, EvoTopicPaper.paper_id == EvoPaper.id)
        .where(EvoTopicPaper.paper_id.in_(paper_ids), EvoTopic.built_at.isnot(None))).all()
    pins = {(o.topic_id, o.paper_id): o.action for o in session.execute(select(EvoMilestoneOverride).where(
        EvoMilestoneOverride.paper_id.in_(paper_ids))).scalars()}
    out: dict[UUID, list[dict]] = defaultdict(list)
    for tp, topic, p in rows:
        name = tp.named_method or ((p.cited_name or {}).get("name") if isinstance(p.cited_name, dict) else None)
        out[p.id].append({"topic": topic.slug, "topic_name": topic.name, "title": p.title, "year": p.year,
                          "named_method": name,
                          "milestone": effective_milestone(tp.is_milestone_auto, pins.get((topic.id, p.id)))})
    return out


def feed_place(session: Session, item_id: UUID) -> dict | None:
    """Where a feed item sits in the maps (when it is a map paper), and the milestones it cites."""
    from athena.core.models import ContentItem
    item = session.get(ContentItem, item_id)
    if item is None:
        return None
    places = []
    for p in session.execute(select(EvoPaper).where(EvoPaper.content_item_id == item_id)).scalars():
        for tp, topic in session.execute(
                select(EvoTopicPaper, EvoTopic).join(EvoTopic, EvoTopicPaper.topic_id == EvoTopic.id)
                .where(EvoTopicPaper.paper_id == p.id, EvoTopic.built_at.isnot(None))).all():
            rows = _topic_rows(session, topic.id)
            override = _overrides(session, topic.id).get(p.id)
            rank = 1 + sum((other.milestone_score or 0) > (tp.milestone_score or 0) for other, _ in rows)
            era = find_era(p.year, topic_eras(topic, rows))
            in_topic = {q.id for _, q in rows}
            gaps = [g.sentence for g in session.execute(select(EvoGapStatement).where(
                EvoGapStatement.paper_id == p.id, EvoGapStatement.label == "gap",
                EvoGapStatement.origin == "own")).scalars()]
            fixes = {}
            for ctx in _strict(session, citing=[p.id], within=in_topic):
                if ctx.label == "addresses_limitation":
                    fixes.setdefault(ctx.cited_id, ctx.sentence)
            titles = dict(session.execute(
                select(EvoPaper.id, EvoPaper.title).where(EvoPaper.id.in_(list(fixes)))).all())
            loose = session.execute(select(func.count()).select_from(EvoLooseLink).where(
                EvoLooseLink.paper_id == p.id, EvoLooseLink.score >= LOOSE_MIN_SCORE)).scalar_one()
            places.append({
                "topic": topic_summary(topic), "paper_id": str(p.id), "kind": tp.kind, "year": p.year,
                "era": list(era) if era else None,
                "is_milestone": effective_milestone(tp.is_milestone_auto, override.action if override else None),
                "on_main_path": tp.on_main_path, "rank": rank, "of": len(rows),
                "gaps_stated": gaps[:5], "gaps_stated_count": len(gaps),
                "solves": [{"paper_id": str(pid), "title": titles.get(pid), "sentence": sentence}
                           for pid, sentence in fixes.items()][:5],
                "loose_matches": loose,
            })
    state = (item.extra_data or {}).get("evolution") or {}
    return {"item_id": str(item.id), "places": places, "cites": state.get("cites", []),
            "maps_cited": state.get("maps", {}), "references": state.get("references"),
            "checked_at": state.get("checked_at")}


def new_feed_papers(session: Session, days: int = 30, topic: str | None = None) -> list[dict]:
    """Recent feed papers that cite milestones, the ones citing the most first."""
    from athena.core.models import ContentItem
    since = datetime.now(timezone.utc) - timedelta(days=days)
    out = []
    for item in session.execute(select(ContentItem).where(ContentItem.published_at >= since,
                                                          ContentItem.extra_data.has_key("evolution"))).scalars():
        cites = [c for c in ((item.extra_data or {}).get("evolution") or {}).get("cites", [])
                 if topic is None or c["topic"] == topic]
        if cites:
            out.append({"id": str(item.id), "title": item.title, "url": item.url,
                        "published_at": item.published_at.isoformat(), "score": item.score, "cites": cites})
    out.sort(key=lambda x: x["published_at"], reverse=True)
    out.sort(key=lambda x: len(x["cites"]), reverse=True)  # stable: newest first among equals
    return out
