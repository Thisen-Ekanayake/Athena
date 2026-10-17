"""
Users' reactions to feed items (ROADMAP P1): 👍 (up), 👎 (down) and "not interested" (hide).

One reaction per item. Hidden items leave the user's feed, Home, Rising and Clusters (search and saved lists still
show them). All three feed the interest profile (athena.pipeline.interests), together with saved items.
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from athena.core.models import ContentItem, ItemFeedback, SavedList, SavedListItem

REACTIONS = ("up", "down", "hide")


def set_reaction(session: Session, user_id: UUID, item_id: UUID, reaction: str) -> bool:
    """Record (or replace) a reaction. False if the item is unknown."""
    if reaction not in REACTIONS:
        raise ValueError(f"reaction must be one of {', '.join(REACTIONS)}")
    if session.get(ContentItem, item_id) is None:
        return False
    row = session.get(ItemFeedback, {"user_id": user_id, "item_id": item_id})
    if row is None:
        session.add(ItemFeedback(user_id=user_id, item_id=item_id, reaction=reaction))
    elif row.reaction != reaction:
        row.reaction = reaction
        row.created_at = func.now()
    session.commit()
    return True


def clear_reaction(session: Session, user_id: UUID, item_id: UUID) -> None:
    session.execute(delete(ItemFeedback).where(ItemFeedback.user_id == user_id, ItemFeedback.item_id == item_id))
    session.commit()


def reset(session: Session, user_id: UUID) -> int:
    """Forget every reaction (saved items stay, and still count). Returns how many there were."""
    gone = session.execute(delete(ItemFeedback).where(ItemFeedback.user_id == user_id)).rowcount
    session.commit()
    return gone


def reactions_for(session: Session, user_id: UUID, item_ids: list) -> dict:
    if not item_ids:
        return {}
    return dict(session.execute(select(ItemFeedback.item_id, ItemFeedback.reaction).where(
        ItemFeedback.user_id == user_id, ItemFeedback.item_id.in_(item_ids))).all())


def has_hidden(session: Session, user_id: UUID) -> bool:
    return session.execute(select(ItemFeedback.item_id).where(
        ItemFeedback.user_id == user_id, ItemFeedback.reaction == "hide").limit(1)).scalar_one_or_none() is not None


def hidden_ids(session: Session, user_id: UUID) -> set:
    return set(session.execute(select(ItemFeedback.item_id).where(
        ItemFeedback.user_id == user_id, ItemFeedback.reaction == "hide")).scalars().all())


def not_hidden(user_id: UUID):
    """A WHERE clause leaving out the feed items the user marked "not interested"."""
    return ~select(ItemFeedback.item_id).where(ItemFeedback.user_id == user_id, ItemFeedback.reaction == "hide",
                                               ItemFeedback.item_id == ContentItem.id).exists()


def signals(session: Session, user_id: UUID, limit: int) -> tuple[list[UUID], list[UUID]]:
    """(liked, disliked) item ids, newest first, at most ``limit`` each.

    Liked: 👍 and saved items. Disliked: 👎 and hidden ones. An explicit reaction wins over a save.
    """
    reacted = session.execute(select(ItemFeedback.item_id, ItemFeedback.reaction, ItemFeedback.created_at)
                              .where(ItemFeedback.user_id == user_id)
                              .order_by(ItemFeedback.created_at.desc())).all()
    explicit = {item_id for item_id, _, _ in reacted}
    saved = session.execute(select(SavedListItem.item_id, func.max(SavedListItem.added_at).label("at"))
                            .join(SavedList, SavedList.id == SavedListItem.list_id)
                            .where(SavedList.user_id == user_id).group_by(SavedListItem.item_id)).all()
    liked = [(at, item_id) for item_id, reaction, at in reacted if reaction == "up"] + \
        [(at, item_id) for item_id, at in saved if item_id not in explicit]
    liked.sort(key=lambda x: x[0] or 0, reverse=True)
    disliked = [item_id for item_id, reaction, _ in reacted if reaction in ("down", "hide")]
    return [i for _, i in liked][:limit], disliked[:limit]


def counts(session: Session, user_id: UUID) -> dict:
    """Reactions by kind, and saved items that count as liked."""
    out = {r: 0 for r in REACTIONS}
    out.update(dict(session.execute(select(ItemFeedback.reaction, func.count()).where(
        ItemFeedback.user_id == user_id).group_by(ItemFeedback.reaction)).all()))
    reacted = select(ItemFeedback.item_id).where(ItemFeedback.user_id == user_id)
    out["saved"] = session.execute(
        select(func.count(func.distinct(SavedListItem.item_id)))
        .join(SavedList, SavedList.id == SavedListItem.list_id)
        .where(SavedList.user_id == user_id, SavedListItem.item_id.notin_(reacted))).scalar() or 0
    return out


def listed(session: Session, user_id: UUID, reaction: str, limit: int = 200) -> list[dict]:
    """Items with one kind of reaction, newest first, for the Personalisation settings."""
    rows = session.execute(select(ContentItem, ItemFeedback.created_at)
                           .join(ItemFeedback, ItemFeedback.item_id == ContentItem.id)
                           .where(ItemFeedback.user_id == user_id, ItemFeedback.reaction == reaction)
                           .order_by(ItemFeedback.created_at.desc()).limit(limit)).all()
    return [{"id": str(item.id), "title": item.title, "url": item.url,
             "source": item.source.name if item.source else None,
             "category": item.category.value if hasattr(item.category, "value") else str(item.category),
             "reacted_at": at.isoformat() if at else None} for item, at in rows]
