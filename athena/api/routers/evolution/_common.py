"""
What the map routes share: finding the topic, and the cache key of what is read from it.
"""
from fastapi import HTTPException
from sqlalchemy.orm import Session

from athena.database import evolution as db


def _topic_or_404(session: Session, slug: str):
    topic = db.get_topic(session, slug)
    if topic is None:
        raise HTTPException(status_code=404, detail=f"Topic '{slug}' is not in the system")
    return topic


def _built_topic_or_409(session: Session, slug: str):
    topic = _topic_or_404(session, slug)
    if topic.built_at is None:
        raise HTTPException(status_code=409, detail="This map has not been built yet")
    return topic


def _cache_key(session: Session, topic, *parts) -> str:
    # built_at in the key: a rebuild gets fresh entries without waiting for the TTL. The labels
    # version does the same for full text and strict links, which arrive without a rebuild.
    built = topic.built_at.isoformat() if topic.built_at else "unbuilt"
    # The status too: a topic read while it builds must not stay cached as building once it is ready.
    return ":".join(["evo", topic.slug, *map(str, parts), built, topic.status or "", db.labels_version(session)])
