"""
The inbox: events, who sees them, each user's read position and their settings.

Map events are shared rows: everyone sees new maps, and a map's followers (those who want its updates as they
happen) see its changes and the feed papers citing its milestones. Watch matches and digests belong to one user.
A user can mute the two shared kinds anyone might find noisy: new maps and papers citing milestones.

A user sees the events of the last INBOX_DAYS days; those after their read position (or, before they first
open the inbox, after their account was created) count as unread.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from athena.core.models import InboxEvent, InboxSettings, InboxState, User

INBOX_DAYS = 60
MUTABLE_KINDS = ("map_new", "feed_citations")
DEFAULT_SETTINGS = {"digest": "weekly", "digest_day": 0, "muted_kinds": [], "last_digest_at": None}
DIGEST_HOUR_UTC = int(os.getenv("INBOX_DIGEST_HOUR_UTC", "1"))  # 06:30 in Sri Lanka, after the nightly map refresh


def add_event(session: Session, kind: str, title: str, body: str | None = None, link: str | None = None,
              topic_id: UUID | None = None, payload: dict | None = None, user_id: UUID | None = None,
              event_id: UUID | None = None) -> InboxEvent:
    """Record an event, shared unless it has a ``user_id``; the caller commits."""
    event = InboxEvent(kind=kind, title=title[:300], body=(body or None) and body[:1000], link=link,
                       topic_id=topic_id, user_id=user_id, payload=payload or {}, created_at=datetime.now(timezone.utc))
    if event_id is not None:
        event.id = event_id
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


def _visible(user: User, muted: list[str]):
    """The user's own events, plus the shared ones they follow (new maps reach everyone) and did not mute."""
    from athena.database.watches import followed_topics
    shared = and_(InboxEvent.user_id.is_(None), or_(
        InboxEvent.kind == "map_new", InboxEvent.topic_id.is_(None),
        InboxEvent.topic_id.in_(followed_topics(user.id, "instant"))))
    if muted:
        shared = and_(shared, InboxEvent.kind.notin_(muted))
    return or_(InboxEvent.user_id == user.id, shared)


def unread_count(session: Session, user: User) -> int:
    visible = _visible(user, get_settings(session, user)["muted_kinds"])
    return session.execute(select(func.count()).select_from(InboxEvent).where(
        _recent(), visible, InboxEvent.created_at > _seen(session, user))).scalar_one()


def events_for(session: Session, user: User, limit: int = 30) -> dict:
    seen = _seen(session, user)
    visible = _visible(user, get_settings(session, user)["muted_kinds"])
    rows = session.execute(select(InboxEvent).where(_recent(), visible).order_by(InboxEvent.created_at.desc())
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


def get_settings(session: Session, user: User) -> dict:
    row = session.get(InboxSettings, user.id)
    if row is None:
        return dict(DEFAULT_SETTINGS)
    return {"digest": row.digest, "digest_day": row.digest_day, "muted_kinds": list(row.muted_kinds or []),
            "last_digest_at": _aware(row.last_digest_at)}


def save_settings(session: Session, user_id: UUID, **values) -> None:
    """Change some of a user's settings (digest, digest_day, muted_kinds, last_digest_at); the rest keep theirs."""
    base = {k: v for k, v in DEFAULT_SETTINGS.items() if k != "last_digest_at"}
    stmt = insert(InboxSettings).values(user_id=user_id, **(base | values))
    session.execute(stmt.on_conflict_do_update(index_elements=["user_id"], set_=values))
    session.commit()
