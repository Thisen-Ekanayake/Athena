"""
Key people per map.
"""
import redis as redis_lib
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from athena.api.cache import cache_get, cache_set
from athena.api.config import settings
from athena.api.deps import get_db, get_redis
from athena.database import evolution as db
from athena.api.routers.evolution._common import _built_topic_or_409, _cache_key

router = APIRouter()


@router.get("/topics/{slug}/people")
def topic_people(slug: str, session: Session = Depends(get_db), r: redis_lib.Redis = Depends(get_redis)):
    topic = _built_topic_or_409(session, slug)
    key = _cache_key(session, topic, "people")
    cached = cache_get(r, key)
    if cached:
        return cached
    payload = db.topic_people(session, topic)
    cache_set(r, key, payload, settings.CACHE_CLUSTERS_TTL)
    return payload
