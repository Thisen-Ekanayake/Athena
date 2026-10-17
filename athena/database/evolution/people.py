"""
Key people per map: authors and labs per era, and who introduced each milestone.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from athena.core.models import EvoPaper, EvoTopic, EvoTopicPaper
from athena.evolution.config import TopicConfig
from athena.evolution.eras import on_topic_method
from athena.evolution.people import PeoplePaper, key_people, milestone_people, people_by_era
from athena.database.evolution.topics import (
    _overrides, _topic_rows, effective_milestone, method_names, topic_eras, topic_summary,
)


def topic_people(session: Session, topic: EvoTopic) -> dict:
    """Key authors and labs per era and overall, and who introduced each milestone."""
    overrides = _overrides(session, topic.id)
    rows = _topic_rows(session, topic.id)
    weight = TopicConfig.from_dict(topic.config).weights.relevance
    on_topic = [(tp, p) for tp, p in rows if on_topic_method(tp.kind, tp.score_detail, weight)]
    milestones = {p.id for tp, p in rows
                  if effective_milestone(tp.is_milestone_auto, overrides[p.id].action if p.id in overrides else None)}
    names = method_names(session, {p.id: p.title for _, p in rows if p.id in milestones})

    def person_paper(tp: EvoTopicPaper, p: EvoPaper) -> PeoplePaper:
        return PeoplePaper(id=str(p.id), title=p.title, year=p.year, milestone_score=tp.milestone_score or 0.0,
                           is_milestone=p.id in milestones, named_method=names.get(p.id) or tp.named_method,
                           authorships=p.authorships or [], authors=p.authors or [])

    papers = [person_paper(tp, p) for tp, p in on_topic]
    # Milestones a person pinned although they are not on-topic method papers still had authors.
    pinned = [person_paper(tp, p) for tp, p in rows
              if p.id in milestones and not on_topic_method(tp.kind, tp.score_detail, weight)]
    with_ids = sum(bool(p.authorships) for p in papers)
    return {
        "topic": topic_summary(topic),
        "eras": people_by_era(papers, topic_eras(topic, rows)),
        "overall": key_people(papers),
        "milestones": milestone_people(papers + pinned),
        "papers": len(papers),
        "papers_with_ids": with_ids,  # the rest are told apart by name only
    }
