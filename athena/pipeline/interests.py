"""
A feed that learns from feedback (ROADMAP P1): each user's interest profile and their "For you" order.

Profile. Items a user liked (👍 or saved to a list) and disliked (👎 or "not interested"), the newest MAX_SIGNALS of
each, become two vectors: the mean of their feed vectors, renormalised. A reaction or a save only marks the profile
stale (``embed_model`` None) and bumps its version; the next For-you read rebuilds it, so writes never wait on
Qdrant. A change of the feed's embedding model makes every profile stale the same way.

Interest of an item: cos(item, liked) − NEGATIVE_WEIGHT · cos(item, disliked), scored by Qdrant against the
candidate ids (no vectors leave Qdrant).

For-you order, for the feed's current filters with hidden items left out:
1. candidates: the POOL best by score, plus the NEAREST items to the liked vector that pass the filters, so
   something the user would like but the global score ranks low can still surface;
2. the score and the interest each become a percentile rank among the candidates. Global scores sit between 0
   and about 0.5 and differ by category, so a raw blend would let the interest swamp them or vanish;
3. for_you = (1 − w) · score rank + w · interest rank, where w is the category's preference weight
   (ScoringConfig.weight_preference) times min(1, signals / FULL_AT): the first few reactions only nudge it.
The order is cached for RANK_TTL per user, profile version, weight version and filters.
"""
from __future__ import annotations

import bisect
import hashlib
import json
import os
from datetime import datetime, timezone
from uuid import UUID

import numpy as np
from loguru import logger
from sqlalchemy import desc, select

from athena.core.models import ContentItem, InterestProfile
from athena.database import feedback

FEED_COLLECTION = os.getenv("QDRANT_COLLECTION", "athena_content")
NEGATIVE_WEIGHT = 0.5
MAX_SIGNALS = 300
FULL_AT = 5
POOL = int(os.getenv("FORYOU_POOL", "1000"))
NEAREST = 200
RANK_TTL = 300
NEUTRAL = 0.5            # the interest rank of a candidate without a vector


def _qdrant():
    from qdrant_client import QdrantClient
    return QdrantClient(url=os.getenv("QDRANT_URL", "http://localhost:6333"))


# ── versions (cache keys) ────────────────────────────────────────────


def _get(r, key: str) -> str:
    try:
        value = r.get(key)
    except Exception:
        return "0"
    return value.decode() if isinstance(value, bytes) else str(value or "0")


def version(r, user_id) -> str:
    return _get(r, f"pref:ver:{user_id}")


def weights_version(r) -> str:
    return _get(r, "pref:ver:global")


def bump(r, user_id=None) -> None:
    try:
        r.incr(f"pref:ver:{user_id}" if user_id else "pref:ver:global")
    except Exception as exc:  # the cache keeps a stale order for RANK_TTL at most
        logger.debug(f"Interests: version bump failed: {exc}")


# ── profile ──────────────────────────────────────────────────────────


def touch(session, user_id: UUID, r=None) -> None:
    """Something the profile learns from changed: rebuild it on its next use."""
    profile = session.get(InterestProfile, user_id)
    if profile is None:
        session.add(InterestProfile(user_id=user_id, enabled=True))
    else:
        profile.embed_model = None
    session.commit()
    if r is not None:
        bump(r, user_id)


def _mean(vectors: list) -> list[float] | None:
    if not vectors:
        return None
    mean = np.mean(np.stack(vectors), axis=0)
    norm = float(np.linalg.norm(mean))
    return (mean / norm).tolist() if norm else None


def rebuild(session, user_id: UUID, qdrant=None) -> InterestProfile:
    from athena.core import llm
    from athena.evolution.vectors import vectors_for
    liked, disliked = feedback.signals(session, user_id, MAX_SIGNALS)
    vectors = vectors_for(liked + disliked, name=FEED_COLLECTION, qdrant=qdrant or _qdrant()) \
        if liked or disliked else {}
    profile = session.get(InterestProfile, user_id) or InterestProfile(user_id=user_id, enabled=True)
    session.add(profile)
    pos, neg = [vectors[i] for i in liked if i in vectors], [vectors[i] for i in disliked if i in vectors]
    profile.positive, profile.negative = _mean(pos), _mean(neg)
    profile.n_positive, profile.n_negative = len(pos), len(neg)
    profile.embed_model = llm.embed_model()
    profile.updated_at = datetime.now(timezone.utc)
    session.commit()
    return profile


def active_profile(session, user_id: UUID, qdrant=None) -> InterestProfile | None:
    """The user's profile, rebuilt if stale; None when personalisation is off or nothing is learned yet."""
    from athena.core import llm
    profile = session.get(InterestProfile, user_id)
    if profile is None or not profile.enabled:
        return None
    if profile.embed_model != llm.embed_model():
        try:
            profile = rebuild(session, user_id, qdrant)
        except Exception as exc:  # Qdrant down: the feed falls back to the plain score
            session.rollback()
            logger.warning(f"Interests: profile rebuild failed for {user_id}: {exc}")
            return None
    if profile.positive is None and profile.negative is None:
        return None
    return profile


def confidence(profile: InterestProfile) -> float:
    return min(1.0, (profile.n_positive + profile.n_negative) / FULL_AT)


def summary(session, user_id: UUID) -> dict:
    """On or off, and what there is to learn from, without touching Qdrant."""
    profile = session.get(InterestProfile, user_id)
    counts = feedback.counts(session, user_id)
    signals = counts["up"] + counts["saved"] + counts["down"] + counts["hide"]
    return {"enabled": profile.enabled if profile else True, "signals": signals, "full_at": FULL_AT,
            "ready": signals >= FULL_AT, "counts": counts}


def set_enabled(session, user_id: UUID, enabled: bool, r=None) -> None:
    profile = session.get(InterestProfile, user_id)
    if profile is None:
        profile = InterestProfile(user_id=user_id)
        session.add(profile)
    profile.enabled = enabled
    session.commit()
    if r is not None:
        bump(r, user_id)


# ── scoring ──────────────────────────────────────────────────────────


def interest_raw(qdrant, profile: InterestProfile, ids: list) -> dict:
    """cos(item, liked) − NEGATIVE_WEIGHT · cos(item, disliked) for the ids that have vectors."""
    from qdrant_client.models import Filter, HasIdCondition
    if not ids:
        return {}
    only = Filter(must=[HasIdCondition(has_id=[str(i) for i in ids])])

    def similarity(vector) -> dict:
        if vector is None:
            return {}
        points = qdrant.query_points(collection_name=FEED_COLLECTION, query=list(vector), query_filter=only,
                                     limit=len(ids), with_payload=False).points
        return {UUID(str(p.id)): float(p.score) for p in points}

    pos, neg = similarity(profile.positive), similarity(profile.negative)
    return {i: pos.get(i, 0.0) - NEGATIVE_WEIGHT * neg.get(i, 0.0) for i in set(pos) | set(neg)}


def percentiles(values: dict) -> dict:
    """Each key's rank among the values on 0..1, ties sharing their average rank."""
    order = sorted(values, key=lambda k: values[k])
    n, out, i = len(order), {}, 0
    while i < n:
        j = i
        while j + 1 < n and values[order[j + 1]] == values[order[i]]:
            j += 1
        rank = ((i + j) / 2) / (n - 1) if n > 1 else NEUTRAL
        for k in order[i:j + 1]:
            out[k] = rank
        i = j + 1
    return out


def preference_weights(session) -> dict:
    """Each category's preference weight (ScoringConfig, else the default)."""
    from athena.pipeline.scoring import DEFAULT_WEIGHTS, _get_weights
    return {c: _get_weights(c, session).get("preference") for c in DEFAULT_WEIGHTS}


def _category(value) -> str:
    return value.value if hasattr(value, "value") else str(value)


def blend(candidates: list[tuple], raw: dict, weights: dict, conf: float) -> list[list]:
    """[[id, for_you, interest rank], ...] best first, from (id, score, category) candidates."""
    score_rank = percentiles({c[0]: c[1] or 0.0 for c in candidates})
    interest_rank = percentiles({i: v for i, v in raw.items()})
    rows = []
    for item_id, score, category in candidates:
        w = (weights.get(_category(category)) or 0.0) * conf
        interest = interest_rank.get(item_id, NEUTRAL)
        rows.append([str(item_id), (1 - w) * score_rank[item_id] + w * interest, interest, score or 0.0])
    rows.sort(key=lambda row: (row[1], row[3]), reverse=True)
    return [[item_id, round(f, 6), round(i, 4)] for item_id, f, i, _ in rows]


def ranked(session, r, user_id: UUID, profile: InterestProfile, conditions: list, filters_key: str,
           qdrant=None) -> dict:
    """The For-you order for these filters: {"order": [[id, for_you, interest rank]], "raws": sorted interests}."""
    digest = hashlib.sha1(filters_key.encode()).hexdigest()[:16]
    key = f"foryou:{user_id}:{version(r, user_id)}:{weights_version(r)}:{digest}"
    try:
        cached = r.get(key)
        if cached:
            return json.loads(cached)
    except Exception:
        pass
    qdrant = qdrant or _qdrant()
    columns = select(ContentItem.id, ContentItem.score, ContentItem.category).where(*conditions)
    candidates = [tuple(row) for row in session.execute(columns.order_by(desc(ContentItem.score)).limit(POOL))]
    seen = {c[0] for c in candidates}
    if profile.positive is not None:
        near = [UUID(str(p.id)) for p in qdrant.query_points(
            collection_name=FEED_COLLECTION, query=list(profile.positive), limit=NEAREST, with_payload=False).points]
        near = [i for i in near if i not in seen]
        if near:
            candidates += [tuple(row) for row in session.execute(columns.where(ContentItem.id.in_(near)))]
    raw = interest_raw(qdrant, profile, [c[0] for c in candidates])
    result = {"order": blend(candidates, raw, preference_weights(session), confidence(profile)),
              "raws": sorted(raw.values())}
    try:
        r.setex(key, RANK_TTL, json.dumps(result))
    except Exception:
        pass
    return result


def interest_of(session, r, user_id: UUID, item: ContentItem, qdrant=None) -> dict | None:
    """The item's interest rank in the user's whole feed and the weight it has in their For-you order, or None."""
    profile = active_profile(session, user_id, qdrant)
    if profile is None:
        return None
    qdrant = qdrant or _qdrant()
    try:
        whole = ranked(session, r, user_id, profile, [feedback.not_hidden(user_id)], "all", qdrant)
        found = next((row for row in whole["order"] if row[0] == str(item.id)), None)
        if found is not None:
            rank = found[2]
        else:
            raw = interest_raw(qdrant, profile, [item.id]).get(item.id)
            raws = whole["raws"]
            rank = bisect.bisect_left(raws, raw) / max(1, len(raws) - 1) if raw is not None and raws else NEUTRAL
    except Exception as exc:
        logger.warning(f"Interests: no interest score for {item.id}: {exc}")
        return None
    weight = (preference_weights(session).get(_category(item.category)) or 0.0) * confidence(profile)
    return {"score": round(min(1.0, rank), 4), "weight": round(weight, 4)}
