"""
Share links for maps (ROADMAP R2): a read-only link anyone can open without an account.

Any user can share any built map, since maps are a shared library already. A link lasts until it is revoked, or
until it expires when it was made with an expiry. Its creator or an admin can revoke it, and an admin can switch
sharing off for the whole app (SHARING_ENABLED), which stops every link at once without revoking them.

The token is the whole secret. It is stored as it is, so a link can be copied again later: it only grants reading
what every user can already read.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from athena.core.config_store import get_setting
from athena.core.models import EvoTopic, MapShare, User

SHARING_KEY = "SHARING_ENABLED"
EXPIRY_DAYS = (7, 30, 90)
BUILT = ("ready", "refining")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    return dt.replace(tzinfo=timezone.utc) if dt is not None and dt.tzinfo is None else dt


def sharing_enabled() -> bool:
    return get_setting(SHARING_KEY, "true").strip().lower() not in ("false", "0", "no", "off")


def is_active(share: MapShare, now: datetime | None = None) -> bool:
    expires = _aware(share.expires_at)
    return share.revoked_at is None and (expires is None or expires > (now or _now()))


def create(session: Session, topic: EvoTopic, user: User, expires_days: int | None) -> MapShare:
    share = MapShare(topic_id=topic.id, token=secrets.token_urlsafe(16), created_by=user.id, created_at=_now(),
                     expires_at=_now() + timedelta(days=expires_days) if expires_days else None, views=0)
    session.add(share)
    session.commit()
    return share


def as_dict(share: MapShare, creator: str | None = None, topic: EvoTopic | None = None) -> dict:
    out = {"id": str(share.id), "token": share.token, "created_by": str(share.created_by) if share.created_by else None,
           "creator": creator, "created_at": _aware(share.created_at).isoformat() if share.created_at else None,
           "expires_at": _aware(share.expires_at).isoformat() if share.expires_at else None,
           "views": share.views or 0,
           "last_viewed_at": _aware(share.last_viewed_at).isoformat() if share.last_viewed_at else None}
    if topic is not None:
        out["topic"] = {"slug": topic.slug, "name": topic.name}
    return out


def list_for(session: Session, user: User, topic: EvoTopic | None = None) -> list[dict]:
    """The active links to ``topic`` (every map's when None): the user's own, or everyone's for an admin."""
    stmt = (select(MapShare, User.display_name, EvoTopic)
            .join(EvoTopic, EvoTopic.id == MapShare.topic_id)
            .outerjoin(User, User.id == MapShare.created_by)
            .where(MapShare.revoked_at.is_(None))
            .order_by(MapShare.created_at.desc()))
    if topic is not None:
        stmt = stmt.where(MapShare.topic_id == topic.id)
    if user.role != "admin":
        stmt = stmt.where(MapShare.created_by == user.id)
    now = _now()
    return [as_dict(share, creator, None if topic is not None else t)
            for share, creator, t in session.execute(stmt).all() if is_active(share, now)]


def revoke(session: Session, share_id: UUID, user: User) -> bool | None:
    """True when revoked; None when there is no such link; False when it is someone else's and ``user`` is no admin."""
    share = session.get(MapShare, share_id)
    if share is None or share.revoked_at is not None:
        return None
    if user.role != "admin" and share.created_by != user.id:
        return False
    share.revoked_at = _now()
    session.commit()
    return True


def resolve(session: Session, token: str) -> tuple[MapShare, EvoTopic] | None:
    """The link and its map, or None when sharing is off or the link is unknown, revoked, expired or unbuilt."""
    if not token or len(token) > 64 or not sharing_enabled():
        return None
    row = session.execute(select(MapShare, EvoTopic).join(EvoTopic, EvoTopic.id == MapShare.topic_id)
                          .where(MapShare.token == token)).first()
    if row is None:
        return None
    share, topic = row
    if not is_active(share) or topic.built_at is None or topic.status not in BUILT:
        return None
    return share, topic


def count_view(session: Session, share: MapShare) -> None:
    share.views = (share.views or 0) + 1
    share.last_viewed_at = _now()
    session.commit()
