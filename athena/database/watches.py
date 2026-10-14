"""
Watches: what each user follows (a map, a search, a source or a cluster) and the feed items each one caught.

Map watches decide whose inbox a map's updates reach (``athena.database.inbox``); search, source and cluster
watches are checked against new feed items by ``athena.pipeline.watches``.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from athena.core.models import Cluster, EvoTopic, Source, User, Watch, WatchHit

KINDS = ("map", "search", "source", "cluster")
DELIVERIES = ("instant", "digest")
MAX_WATCHES = 50


class WatchLimit(Exception):
    """The user already follows MAX_WATCHES things."""


def clean_query(query: str) -> str:
    return " ".join(query.split())


def target_for(kind: str, ref: UUID | str) -> str:
    """The name a watch has once per user: ``map:<id>``, ``search:<lower-case query>``, ..."""
    return f"search:{clean_query(str(ref)).lower()}" if kind == "search" else f"{kind}:{ref}"


def follow(session: Session, user: User, kind: str, *, topic_id: UUID | None = None, source_id: UUID | None = None,
           cluster_id: UUID | None = None, query: str | None = None, vector: list[float] | None = None,
           embed_model: str | None = None, delivery: str = "instant") -> tuple[Watch, bool]:
    """Follow something; following it again returns the existing watch. Returns (watch, created)."""
    ref = {"map": topic_id, "source": source_id, "cluster": cluster_id, "search": query}[kind]
    target = target_for(kind, ref)
    existing = find(session, user, target)
    if existing is not None:
        return existing, False
    count = session.execute(select(func.count()).select_from(Watch).where(Watch.user_id == user.id)).scalar_one()
    if count >= MAX_WATCHES:
        raise WatchLimit()
    watch = Watch(user_id=user.id, kind=kind, target=target, topic_id=topic_id, source_id=source_id,
                  cluster_id=cluster_id, query=clean_query(query) if query else None, query_vector=vector,
                  embed_model=embed_model, delivery=delivery, created_at=datetime.now(timezone.utc))
    session.add(watch)
    session.commit()
    return watch, True


def find(session: Session, user: User, target: str) -> Watch | None:
    return session.execute(select(Watch).where(Watch.user_id == user.id, Watch.target == target)).scalar()


def follow_map(session: Session, user_id: UUID, topic_id: UUID, commit: bool = False) -> int:
    """Follow a map for a user unless they already do (no limit: Athena does this for them, not they).

    Returns 1 for a new follow. Commits only when asked to.
    """
    stmt = insert(Watch).values(user_id=user_id, kind="map", target=target_for("map", topic_id), topic_id=topic_id,
                                delivery="instant", created_at=datetime.now(timezone.utc))
    added = session.execute(stmt.on_conflict_do_nothing(constraint="uq_watch_user_target")).rowcount or 0
    if commit:
        session.commit()
    return added


def get_for(session: Session, user: User, watch_id: UUID) -> Watch | None:
    watch = session.get(Watch, watch_id)
    return watch if watch is not None and watch.user_id == user.id else None


def set_delivery(session: Session, user: User, watch_id: UUID, delivery: str) -> Watch | None:
    watch = get_for(session, user, watch_id)
    if watch is not None:
        watch.delivery = delivery
        session.commit()
    return watch


def unfollow(session: Session, user: User, watch_id: UUID) -> bool:
    watch = get_for(session, user, watch_id)
    if watch is None:
        return False
    session.delete(watch)
    session.commit()
    return True


def followed_topics(user_id: UUID, delivery: str | None = None):
    """A subquery of the map ids a user follows (only those with this delivery, when given)."""
    q = select(Watch.topic_id).where(Watch.user_id == user_id, Watch.kind == "map")
    return q.where(Watch.delivery == delivery) if delivery else q


def describe(watches: list[Watch], session: Session) -> dict[UUID, dict]:
    """Each watch's label, link and status (``retired`` for a cluster that re-clustering dropped)."""
    def lookup(model, ids, *cols):
        ids = [i for i in ids if i is not None]
        return {r[0]: r[1:] for r in session.execute(select(model.id, *cols).where(model.id.in_(ids)))} if ids else {}

    topics = lookup(EvoTopic, [w.topic_id for w in watches], EvoTopic.name, EvoTopic.slug)
    sources = lookup(Source, [w.source_id for w in watches], Source.name)
    clusters = lookup(Cluster, [w.cluster_id for w in watches], Cluster.label, Cluster.is_active)
    out = {}
    for w in watches:
        status = "active"
        if w.kind == "map":
            name, slug = topics.get(w.topic_id, ("A deleted map", None))
            label, link = name, f"/evolution/{slug}" if slug else None
        elif w.kind == "source":
            label, link = sources.get(w.source_id, ("A deleted source",))[0], f"/sources/{w.source_id}"
        elif w.kind == "cluster":
            name, active = clusters.get(w.cluster_id, (None, False))
            label, link = name or "Unnamed cluster", f"/clusters/{w.cluster_id}"
            status = "active" if active else "retired"
        else:
            label, link = w.query or "", f"/search?q={quote(w.query or '')}"
        out[w.id] = {"label": label, "link": link, "status": status}
    return out


def list_for(session: Session, user: User) -> list[dict]:
    """The user's watches, newest first, with what each caught in the last 7 days."""
    watches = session.execute(select(Watch).where(Watch.user_id == user.id)
                              .order_by(Watch.created_at.desc())).scalars().all()
    since = datetime.now(timezone.utc) - timedelta(days=7)
    hits = dict(session.execute(select(WatchHit.watch_id, func.count()).where(
        WatchHit.watch_id.in_([w.id for w in watches]), WatchHit.created_at >= since)
        .group_by(WatchHit.watch_id)).all()) if watches else {}
    info = describe(watches, session)
    return [as_dict(w, info[w.id], hits.get(w.id, 0)) for w in watches]


def as_dict(w: Watch, info: dict, hits_7d: int = 0) -> dict:
    ref = {"map": w.topic_id, "source": w.source_id, "cluster": w.cluster_id}.get(w.kind)
    return {"id": str(w.id), "kind": w.kind, "target": w.target, "ref": str(ref) if ref else w.query,
            "delivery": w.delivery, "created_at": w.created_at.isoformat() if w.created_at else None,
            "hits_7d": hits_7d, **info}


def checkable(session: Session) -> list[Watch]:
    """Search, source and cluster watches of active users: the ones checked against new feed items."""
    return session.execute(select(Watch).join(User, User.id == Watch.user_id).where(
        Watch.kind.in_(("search", "source", "cluster")), User.is_active.is_(True))).scalars().all()


def add_hits(session: Session, watch_id: UUID, hits: dict[UUID, float | None]) -> set[UUID]:
    """Record what a watch caught; returns the items it had not caught before. The caller commits."""
    if not hits:
        return set()
    now = datetime.now(timezone.utc)
    stmt = insert(WatchHit).values([{"watch_id": watch_id, "item_id": i, "similarity": s, "created_at": now}
                                    for i, s in hits.items()])
    return set(session.execute(stmt.on_conflict_do_nothing(constraint="uq_watch_hit")
                               .returning(WatchHit.item_id)).scalars())
