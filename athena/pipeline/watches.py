"""
Watches and digests (ROADMAP N1).

Every hour each search, source and cluster watch looks at the feed items that arrived since its last check, with
an hour's overlap so items committed late are not missed (``watch_hits`` keeps an item from counting twice):

- a search compares its query's vector with the new items' vectors and keeps those at or above SEARCH_FLOOR;
- a source takes its new items;
- a cluster takes the new items re-clustering put in it (clustering runs every six hours, so it looks
  CLUSTER_DAYS back, and a cluster re-clustering retired is skipped).

A watch delivered "as it happens" adds an inbox entry for what it caught; one delivered "in the digest" only
records it.

Every day at INBOX_DIGEST_HOUR_UTC, users whose digest is due get one entry that rolls up the period: what each
watch caught, updates to the maps they follow, new maps, feed papers citing their maps' milestones, the top new
papers and the latest trending briefs. It makes no model call.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from uuid import UUID

from loguru import logger
from sqlalchemy import func, select

from athena.database.inbox import DIGEST_HOUR_UTC  # noqa: F401  (the beat schedule reads it from here)
from athena.pipeline.celery_app import celery_app

# Query-to-item cosine similarity a followed search needs (Qwen3-Embedding-8B, 1024 dims, query instruction).
# Calibrated 2026-10-13 with scripts/calibrate_watch_floor.py on the 30 closest feed items of 10 queries, labelled
# by hand: the lowest floor with dev precision >= 0.8. Dev 0.81 precision, 0.44 recall; test 0.87 and 0.66. Short
# queries sit lower ("object detection" tops out at 0.62), so a follow of a narrow, short query may stay quiet.
SEARCH_FLOOR = 0.625
OVERLAP = timedelta(hours=1)
CLUSTER_DAYS = 3
MAX_CANDIDATES = 2000          # newest first; a backlog bigger than this is not news
EVENT_ITEMS = 20               # items kept in one inbox entry
DIGEST_ITEMS = 5
DIGEST_GUARD = timedelta(hours=20)  # a digest never comes twice in a day, whatever the schedule did


# ── watch checks ─────────────────────────────────────────────────────


def _since(watch, now: datetime) -> datetime:
    start = watch.checked_at or watch.created_at or now
    return (start.replace(tzinfo=timezone.utc) if start.tzinfo is None else start) - OVERLAP


def _query_vector(session, watch) -> list[float]:
    """The query's vector, embedded again when the feed's embedding model changed since it was made."""
    from athena.core import llm
    from athena.search.local import embed_query
    model = llm.embed_model()
    if watch.query_vector is None or watch.embed_model != model:
        watch.query_vector, watch.embed_model = embed_query(watch.query), model
    return list(watch.query_vector)


def search_hits(session, watch, now: datetime, qdrant) -> dict[UUID, float]:
    from qdrant_client.models import Filter, HasIdCondition

    from athena.core.models import ContentItem
    from athena.pipeline.embedding_worker import COLLECTION_NAME
    ids = session.execute(select(ContentItem.id).where(ContentItem.embedded_at > _since(watch, now))
                          .order_by(ContentItem.embedded_at.desc()).limit(MAX_CANDIDATES)).scalars().all()
    if not ids:
        return {}
    response = qdrant.query_points(
        collection_name=COLLECTION_NAME, query=_query_vector(session, watch), limit=len(ids),
        query_filter=Filter(must=[HasIdCondition(has_id=[str(i) for i in ids])]), score_threshold=SEARCH_FLOOR)
    return {UUID(str(p.id)): round(float(p.score), 4) for p in response.points}


def source_hits(session, watch, now: datetime) -> dict[UUID, None]:
    from athena.core.models import ContentItem
    ids = session.execute(select(ContentItem.id).where(
        ContentItem.source_id == watch.source_id, ContentItem.fetched_at > _since(watch, now))
        .order_by(ContentItem.fetched_at.desc()).limit(MAX_CANDIDATES)).scalars().all()
    return dict.fromkeys(ids)


def cluster_hits(session, watch, now: datetime) -> dict[UUID, None]:
    from athena.core.models import Cluster, ContentItem
    if not session.execute(select(Cluster.is_active).where(Cluster.id == watch.cluster_id)).scalar():
        return {}
    created = watch.created_at.replace(tzinfo=timezone.utc) if watch.created_at.tzinfo is None else watch.created_at
    since = max(created, now - timedelta(days=CLUSTER_DAYS))
    ids = session.execute(select(ContentItem.id).where(
        ContentItem.cluster_id == watch.cluster_id, ContentItem.fetched_at >= since)
        .order_by(ContentItem.fetched_at.desc()).limit(MAX_CANDIDATES)).scalars().all()
    return dict.fromkeys(ids)


def matches_title(kind: str, n: int, label: str) -> str:
    """'3 new matches for "video diffusion"', '1 new from The Gradient', '4 new in "LLM agents"'."""
    if kind == "search":
        return f'{n} new {"match" if n == 1 else "matches"} for "{label}"'
    if kind == "source":
        return f"{n} new from {label}"
    return f'{n} new in "{label}"'


def _items(session, ids, similarity: dict) -> list[dict]:
    """The caught items, best first (closest for a search, else highest score)."""
    from athena.core.models import ContentItem
    rows = session.execute(select(ContentItem.id, ContentItem.title, ContentItem.score)
                           .where(ContentItem.id.in_(list(ids)))).all()
    items = [{"id": str(i), "title": t, "score": round(s, 3) if s is not None else None,
              "similarity": similarity.get(i)} for i, t, s in rows]
    return sorted(items, key=lambda x: (-(x["similarity"] or 0), -(x["score"] or 0)))


def check_watch(session, watch, now: datetime, qdrant, info: dict) -> int:
    """Check one watch; returns how many items it caught for the first time. The caller commits."""
    from athena.database import inbox
    from athena.database import watches as db
    if watch.kind == "search":
        found = search_hits(session, watch, now, qdrant)
    elif watch.kind == "source":
        found = source_hits(session, watch, now)
    else:
        found = cluster_hits(session, watch, now)
    new = db.add_hits(session, watch.id, found)
    if new and watch.delivery == "instant":
        items = _items(session, new, found)
        inbox.add_event(session, "watch_matches", matches_title(watch.kind, len(new), info["label"]),
                        "; ".join(i["title"] for i in items[:3]) + ("; ..." if len(items) > 3 else ""),
                        info["link"], None, {"watch_id": str(watch.id), "watch_kind": watch.kind,
                                             "label": info["label"], "items": items[:EVENT_ITEMS]},
                        user_id=watch.user_id)
    watch.checked_at = now
    return len(new)


def run_checks(qdrant=None, now: datetime | None = None) -> dict:
    from athena.database import watches as db
    from athena.database.db import SessionLocal
    now = now or datetime.now(timezone.utc)
    summary = {"watches": 0, "caught": 0, "failed": 0}
    with SessionLocal() as session:
        watches = db.checkable(session)
        info = db.describe(watches, session)
        if qdrant is None and any(w.kind == "search" for w in watches):
            from qdrant_client import QdrantClient

            from athena.pipeline.embedding_worker import QDRANT_URL
            qdrant = QdrantClient(url=QDRANT_URL)
        for watch in watches:
            try:
                summary["caught"] += check_watch(session, watch, now, qdrant, info[watch.id])
                session.commit()
                summary["watches"] += 1
            except Exception as exc:  # one broken watch (model server down, ...) must not stop the rest
                session.rollback()
                summary["failed"] += 1
                logger.warning(f"Watch {watch.id} ({watch.kind}) not checked: {exc}")
    logger.info(f"Watches checked: {summary}")
    return summary


@celery_app.task
def check_watches() -> dict:
    """Hourly: search, source and cluster watches against the new feed items."""
    return run_checks()


# ── digests ──────────────────────────────────────────────────────────


def is_due(settings: dict, now: datetime) -> bool:
    """Daily digests come every day, weekly ones on the chosen day; never twice within DIGEST_GUARD."""
    if settings["digest"] == "off":
        return False
    if settings["digest"] == "weekly" and now.weekday() != settings["digest_day"]:
        return False
    last = settings.get("last_digest_at")
    return last is None or now - last >= DIGEST_GUARD


def period_start(settings: dict, now: datetime) -> datetime:
    days = 1 if settings["digest"] == "daily" else 7
    last = settings.get("last_digest_at")
    return max(last, now - timedelta(days=2 * days)) if last else now - timedelta(days=days)


def digest_title(frequency: str, start: datetime, end: datetime) -> str:
    """'Your daily digest · Wed 14 Oct', 'Your weekly digest · 7–13 Oct' or '· 29 Sep – 5 Oct'."""
    if frequency == "daily":
        return f"Your daily digest · {end:%a} {end.day} {end:%b}"
    last = end - timedelta(days=1)
    span = (f"{start.day}–{last.day} {last:%b}" if (start.month, start.year) == (last.month, last.year)
            else f"{start.day} {start:%b} – {last.day} {last:%b}")
    return f"Your weekly digest · {span}"


def digest_body(payload: dict) -> str:
    """One line: what each section holds."""
    parts = []
    caught = sum(w["count"] for w in payload["watches"])
    if caught:
        n = len(payload["watches"])
        parts.append(f"{caught} new from {n} {'watch' if n == 1 else 'watches'}")
    if payload["maps"]:
        names = list(dict.fromkeys(m["name"] for m in payload["maps"]))
        parts.append(f"{', '.join(names[:3])}{', ...' if len(names) > 3 else ''} updated")
    if payload["new_maps"]:
        n = len(payload["new_maps"])
        parts.append(f"{n} new {'map' if n == 1 else 'maps'}")
    cites = sum(len(c["items"]) for c in payload["citations"])
    if cites:
        parts.append(f"{cites} {'paper cites' if cites == 1 else 'papers cite'} milestones")
    if payload["top_papers"]:
        parts.append(f"top new: {payload['top_papers'][0]['title']}")
    return " · ".join(parts)


def digest_is_empty(payload: dict) -> bool:
    return not any(payload[k] for k in ("watches", "maps", "new_maps", "citations", "top_papers"))


def build_digest(session, user, start: datetime, end: datetime, muted: list[str]) -> dict:
    """The digest's sections for one user and period, as the inbox entry's payload."""
    from athena.core.models import (
        ContentItem, EvoSnapshot, EvoTopic, InboxEvent, TrendingBrief, Watch, WatchHit,
    )
    from athena.database import watches as db
    from athena.evolution.snapshots import is_empty, summary

    watches = session.execute(select(Watch).where(Watch.user_id == user.id)).scalars().all()
    info = db.describe(watches, session)
    caught = defaultdict(list)
    for watch_id, item_id, title, score, similarity in session.execute(
            select(WatchHit.watch_id, ContentItem.id, ContentItem.title, ContentItem.score, WatchHit.similarity)
            .join(ContentItem, ContentItem.id == WatchHit.item_id)
            .where(WatchHit.watch_id.in_([w.id for w in watches]), WatchHit.created_at >= start,
                   WatchHit.created_at < end)):
        caught[watch_id].append({"id": str(item_id), "title": title,
                                 "score": round(score, 3) if score is not None else None, "similarity": similarity})
    watch_sections = []
    for w in watches:
        if caught.get(w.id):
            items = sorted(caught[w.id], key=lambda x: (-(x["similarity"] or 0), -(x["score"] or 0)))
            watch_sections.append({"watch_id": str(w.id), "kind": w.kind, "label": info[w.id]["label"],
                                   "link": info[w.id]["link"], "count": len(items), "items": items[:DIGEST_ITEMS]})
    watch_sections.sort(key=lambda s: -s["count"])

    followed = db.followed_topics(user.id)
    maps = [{"name": name, "slug": slug, "changes": summary(changes), "reason": reason,
             "taken_at": taken.isoformat()}
            for name, slug, changes, reason, taken in session.execute(
                select(EvoTopic.name, EvoTopic.slug, EvoSnapshot.changes, EvoSnapshot.reason, EvoSnapshot.taken_at)
                .join(EvoTopic, EvoTopic.id == EvoSnapshot.topic_id)
                .where(EvoSnapshot.topic_id.in_(followed), EvoSnapshot.taken_at >= start, EvoSnapshot.taken_at < end)
                .order_by(EvoSnapshot.taken_at))
            if changes and not is_empty(changes)]  # a first snapshot's changes are JSON null, not SQL NULL

    shared = select(InboxEvent).where(InboxEvent.user_id.is_(None), InboxEvent.created_at >= start,
                                      InboxEvent.created_at < end).order_by(InboxEvent.created_at)
    new_maps = [] if "map_new" in muted else [
        {"title": e.title, "link": e.link, "body": e.body}
        for e in session.execute(shared.where(InboxEvent.kind == "map_new")).scalars()]
    citations = []
    if "feed_citations" not in muted:
        for e in session.execute(shared.where(InboxEvent.kind == "feed_citations",
                                              InboxEvent.topic_id.in_(followed))).scalars():
            citations.append({"title": e.title, "link": e.link, "items": (e.payload or {}).get("items", [])})

    top = session.execute(select(ContentItem.id, ContentItem.title, ContentItem.score).where(
        ContentItem.fetched_at >= start, ContentItem.fetched_at < end, ContentItem.score.isnot(None))
        .order_by(ContentItem.score.desc()).limit(DIGEST_ITEMS)).all()
    new_items = session.execute(select(func.count()).select_from(ContentItem).where(
        ContentItem.fetched_at >= start, ContentItem.fetched_at < end)).scalar_one()

    briefs = {}
    for b in session.execute(select(TrendingBrief).where(TrendingBrief.generated_at >= start,
                                                         TrendingBrief.generated_at < end)
                             .order_by(TrendingBrief.generated_at)).scalars():
        briefs[b.category.value] = {"category": b.category.value, "theme": b.theme, "brief": b.brief,
                                    "generated_at": b.generated_at.isoformat()}

    return {"period": {"start": start.isoformat(), "end": end.isoformat()}, "watches": watch_sections,
            "maps": maps, "new_maps": new_maps, "citations": citations, "new_items": new_items,
            "top_papers": [{"id": str(i), "title": t, "score": round(s, 3)} for i, t, s in top],
            "briefs": list(briefs.values())}


def send_digest(session, user, settings: dict, now: datetime) -> bool:
    """Write the user's digest for the period ending now (unless it holds nothing). The caller commits."""
    from athena.database import inbox
    start = period_start(settings, now)
    payload = build_digest(session, user, start, now, settings["muted_kinds"])
    payload["frequency"] = settings["digest"]
    if digest_is_empty(payload):
        return False
    inbox.add_event(session, "digest", digest_title(settings["digest"], start, now), digest_body(payload),
                    None, None, payload, user_id=user.id)
    return True


def run_digests(now: datetime | None = None, user_id: str | None = None) -> dict:
    """Digests for every user whose digest is due; ``user_id`` sends that user's now, whatever the schedule."""
    from athena.core.models import User
    from athena.database import inbox
    from athena.database.db import SessionLocal
    now = now or datetime.now(timezone.utc)
    summary = {"sent": 0, "empty": 0, "failed": 0}
    with SessionLocal() as session:
        users = session.execute(select(User).where(User.is_active.is_(True))).scalars().all()
        for user in users:
            if user_id and str(user.id) != user_id:
                continue
            settings = inbox.get_settings(session, user)
            if user_id:
                settings = settings | {"digest": "daily" if settings["digest"] == "daily" else "weekly"}
            elif not is_due(settings, now):
                continue
            try:
                sent = send_digest(session, user, settings, now)
                session.commit()
                inbox.save_settings(session, user.id, last_digest_at=now)
                summary["sent" if sent else "empty"] += 1
            except Exception as exc:
                session.rollback()
                summary["failed"] += 1
                logger.warning(f"Digest for {user.email} not sent: {exc}")
    logger.info(f"Digests: {summary}")
    return summary


@celery_app.task
def send_digests() -> dict:
    """Daily at INBOX_DIGEST_HOUR_UTC: the digests that are due."""
    return run_digests()
