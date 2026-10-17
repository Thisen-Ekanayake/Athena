"""
Questions to the maps: idea checks and the questions asked of one map, per user.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from athena.core.models import EvoIdeaCheck, EvoMapQuestion
from athena.database.db import SessionLocal


def _idea_check(c: EvoIdeaCheck, full: bool = True) -> dict:
    result = c.result or {}
    themes = result.get("themes") or []
    out = {"id": str(c.id), "idea": c.idea if full else c.idea[:240], "created_at": c.created_at.isoformat(),
           "papers": len(result.get("papers") or []), "themes": len(themes),
           "open_themes": sum(bool(t.get("open")) for t in themes)}
    return out | {"result": result} if full else out


def save_idea_check(session: Session, user_id: UUID, idea: str, result: dict) -> dict:
    check = EvoIdeaCheck(user_id=user_id, idea=idea, result=result, created_at=datetime.now(timezone.utc))
    session.add(check)
    session.commit()
    return _idea_check(check)


def list_idea_checks(session: Session, user_id: UUID, limit: int = 50) -> list[dict]:
    rows = session.execute(select(EvoIdeaCheck).where(EvoIdeaCheck.user_id == user_id)
                           .order_by(EvoIdeaCheck.created_at.desc()).limit(limit)).scalars()
    return [_idea_check(c, full=False) for c in rows]


def get_idea_check(session: Session, user_id: UUID, check_id: UUID) -> dict | None:
    """A user's own check; another user's is as good as missing."""
    check = session.get(EvoIdeaCheck, check_id)
    return _idea_check(check) if check is not None and check.user_id == user_id else None


def delete_idea_check(session: Session, user_id: UUID, check_id: UUID) -> bool:
    deleted = session.execute(delete(EvoIdeaCheck).where(EvoIdeaCheck.id == check_id,
                                                         EvoIdeaCheck.user_id == user_id)).rowcount
    session.commit()
    return bool(deleted)


def save_map_question(user_id: UUID, topic_id: UUID, question: str, answer: str, sources: list[dict],
                      sections: list[str], input_tokens: int, output_tokens: int, model: str) -> UUID:
    """Runs after a streamed answer, so it opens its own session (the request's has closed)."""
    with SessionLocal() as session:
        row = EvoMapQuestion(user_id=user_id, topic_id=topic_id, question=question, answer=answer, sources=sources,
                             sections=sections, input_tokens=input_tokens, output_tokens=output_tokens, model=model,
                             created_at=datetime.now(timezone.utc))
        session.add(row)
        session.commit()
        return row.id


def map_questions(session: Session, user_id: UUID, topic_id: UUID, limit: int = 30) -> list[dict]:
    """A user's questions to one map, oldest first, so the page can show them as a conversation."""
    rows = list(session.execute(select(EvoMapQuestion).where(
        EvoMapQuestion.user_id == user_id, EvoMapQuestion.topic_id == topic_id)
        .order_by(EvoMapQuestion.created_at.desc()).limit(limit)).scalars())
    return [{"id": str(q.id), "question": q.question, "answer": q.answer, "sources": q.sources or [],
             "sections": q.sections or [], "created_at": q.created_at.isoformat()} for q in reversed(rows)]


def delete_map_question(session: Session, user_id: UUID, question_id: UUID | None = None,
                        topic_id: UUID | None = None) -> int:
    """One of a user's questions, or all of them for a topic."""
    stmt = delete(EvoMapQuestion).where(EvoMapQuestion.user_id == user_id)
    if question_id is not None:
        stmt = stmt.where(EvoMapQuestion.id == question_id)
    if topic_id is not None:
        stmt = stmt.where(EvoMapQuestion.topic_id == topic_id)
    deleted = session.execute(stmt).rowcount
    session.commit()
    return deleted
