"""
The inbox: shared events (map updates, new maps, feed papers citing milestones) and each user's read position.

A user sees the events of the last INBOX_DAYS days; those after their read position (or, before they first
open the inbox, after their account was created) count as unread.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from athena.core.models import InboxEvent, InboxState, User

INBOX_DAYS = 60


def add_event(session: Session, kind: str, title: str, body: str | None = None, link: str | None = None,
              topic_id: UUID | None = None, payload: dict | None = None) -> InboxEvent:
    """Record an event; the caller commits."""
    event = InboxEvent(kind=kind, title=title[:300], body=(body or None) and body[:1000], link=link,
                       topic_id=topic_id, payload=payload or {}, created_at=datetime.now(timezone.utc))
    session.add(event)
    return event


def _aware(dt: datetime | None) -> datetime | None:
    return dt.replace(tzinfo=timezone.utc) if dt is not None and dt.tzinfo is None else dt


def _seen(session: Session, user: User) -> datetime:
    state = session.get(InboxState, user.id)
    if state is not None:
        return _aware(state.last_seen_at)
    return _aware(user.created_at) or datetime.now(timezone.utc)


def _recent():
    return InboxEvent.created_at >= datetime.now(timezone.utc) - timedelta(days=INBOX_DAYS)


def unread_count(session: Session, user: User) -> int:
    return session.execute(select(func.count()).select_from(InboxEvent).where(
        _recent(), InboxEvent.created_at > _seen(session, user))).scalar_one()


def events_for(session: Session, user: User, limit: int = 30) -> dict:
    seen = _seen(session, user)
    rows = session.execute(select(InboxEvent).where(_recent()).order_by(InboxEvent.created_at.desc())
                           .limit(limit)).scalars()
    events = [{"id": str(e.id), "kind": e.kind, "title": e.title, "body": e.body, "link": e.link,
               "payload": e.payload or {}, "created_at": e.created_at.isoformat(),
               "unread": _aware(e.created_at) > seen} for e in rows]
    return {"events": events, "unread": unread_count(session, user)}


def mark_seen(session: Session, user: User) -> None:
    now = datetime.now(timezone.utc)
    stmt = insert(InboxState).values(user_id=user.id, last_seen_at=now)
    session.execute(stmt.on_conflict_do_update(index_elements=["user_id"], set_={"last_seen_at": now}))
    session.commit()
