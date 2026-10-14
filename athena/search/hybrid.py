"""
Keyword plus meaning search over the feed (ROADMAP S3).

Two rankings, fused:

- meaning: the query's vector against the feed's vectors in Qdrant, as before;
- keywords: Postgres full-text search over the title (weight A), summary (B) and abstract (C), through the generated
  ``content_items.search_vector`` column (athena.api.migrations.add_writing). The English parser keeps names whole
  ("lora", "yolov8", "rt-detr", "gpt-4o"), so an exact name is found even where its vector sits among loosely
  related items.

The lists are fused by reciprocal rank (k = RRF_K). Items whose title holds a short query as a whole word come
first, so "LoRA" or "YOLOv8" lead with the papers named so. Each result says how it matched: ``exact``, ``both``,
``keyword`` or ``meaning``. On a database without full-text search (the SQLite tests) the keyword side is a plain
substring match, as the old fallback was.

Follows (athena.pipeline.watches) keep meaning-only matching: their floor was calibrated on it.
"""
from __future__ import annotations

import re
from uuid import UUID

from loguru import logger
from sqlalchemy import desc, false, func, literal, literal_column, or_, select
from sqlalchemy.orm import Session

from athena.core.models import ContentCategory, ContentItem

RRF_K = 60
SEMANTIC_HITS = 50
KEYWORD_HITS = 50
EXACT_MAX_WORDS = 4   # longer queries are questions, not names
# A keyword match below this ts_rank_cd (normalised 0-1) has the query's words scattered through an abstract: on the
# local feed, "retrieval for code" matched a SAR imagery dataset at 0.019. Fused by rank alone it would sit near the
# top, so only exact titles and matches at least this strong count. Title matches score 0.5 and up.
KEYWORD_MIN_RANK = 0.05


def _is_postgres(session: Session) -> bool:
    try:
        return session.get_bind().dialect.name == "postgresql"
    except Exception:
        return False


def _category(category: str | None):
    try:
        return ContentCategory(category) if category else None
    except ValueError:
        return None


def title_pattern(query: str) -> str | None:
    """A Postgres regex for the query as a whole word or phrase in a title, or None for a long query. Hyphens and
    spaces between words match each other ("retrieval-augmented generation", "Retrieval Augmented Generation")."""
    if len(query.split()) > EXACT_MAX_WORDS:
        return None
    words = [w for w in re.split(r"[\s\-]+", query.strip()) if w]
    if not words:
        return None
    return r"\m" + r"[\s\-]+".join(re.escape(w) for w in words) + r"\M"


def keyword_statement(query: str, limit: int, category: str | None, postgres: bool):
    """(id, rank, exact) for items matching the query's words, best first."""
    q = query.strip()
    cat = _category(category)
    pattern = title_pattern(q)
    if postgres:
        vector = literal_column("content_items.search_vector")
        tsquery = func.websearch_to_tsquery("english", q)
        rank = func.ts_rank_cd(vector, tsquery, 32)
        exact = ContentItem.title.op("~*")(pattern) if pattern else false()
        stmt = select(ContentItem.id, rank.label("rank"), exact.label("exact")).where(
            or_(vector.op("@@")(tsquery), exact))
        order = (desc("exact"), desc("rank"))
    else:
        like = f"%{q}%"
        stmt = select(ContentItem.id, literal(0.0).label("rank"), ContentItem.title.ilike(like).label("exact")).where(
            or_(ContentItem.title.ilike(like), ContentItem.summary.ilike(like)))
        order = (desc("exact"), desc(ContentItem.score))
    if cat is not None:
        stmt = stmt.where(ContentItem.category == cat)
    return stmt.order_by(*order).limit(limit)


def keyword_hits(session: Session, query: str, limit: int = KEYWORD_HITS, category: str | None = None) -> list[dict]:
    postgres = _is_postgres(session)
    rows = session.execute(keyword_statement(query, limit, category, postgres)).all()
    return [{"id": UUID(str(item_id)), "rank": float(rank or 0), "exact": bool(exact)} for item_id, rank, exact in rows
            if exact or not postgres or float(rank or 0) >= KEYWORD_MIN_RANK]


def fuse(semantic: list[dict], keyword: list[dict], limit: int) -> list[dict]:
    """Reciprocal-rank fusion of the two lists ([{id, similarity}] and [{id, rank, exact}], best first).

    Exact title matches lead, in fused order. Returns [{id, score, match, similarity}].
    """
    fused: dict[UUID, dict] = {}
    for i, hit in enumerate(semantic):
        entry = fused.setdefault(hit["id"], {"id": hit["id"], "score": 0.0, "meaning": False, "keyword": False,
                                             "exact": False, "similarity": None})
        entry["score"] += 1 / (RRF_K + i + 1)
        entry["meaning"], entry["similarity"] = True, hit.get("similarity")
    for i, hit in enumerate(keyword):
        entry = fused.setdefault(hit["id"], {"id": hit["id"], "score": 0.0, "meaning": False, "keyword": False,
                                             "exact": False, "similarity": None})
        entry["score"] += 1 / (RRF_K + i + 1)
        entry["keyword"] = True
        entry["exact"] = entry["exact"] or hit.get("exact", False)
    ranked = sorted(fused.values(), key=lambda e: (e["exact"], e["score"]), reverse=True)[:limit]
    return [{"id": e["id"], "score": round(e["score"], 6), "similarity": e["similarity"],
             "match": "exact" if e["exact"] else "both" if e["meaning"] and e["keyword"]
             else "keyword" if e["keyword"] else "meaning"} for e in ranked]


def search(session: Session, query: str, limit: int = 20, category: str | None = None,
           semantic_search=None) -> tuple[list[dict], str]:
    """The fused results and how they were found: ``hybrid``, ``keyword`` (no embedding model) or ``semantic``.

    ``semantic_search(query, limit, category)`` returns [{id, similarity}]; a failure leaves the keyword side alone.
    """
    semantic, keyword, meaning_ok, keyword_ok = [], [], False, False
    if semantic_search is not None:
        try:
            semantic, meaning_ok = semantic_search(query, SEMANTIC_HITS, category), True
        except Exception as exc:  # the embedding model or Qdrant is down: keywords still answer
            logger.warning(f"Search: meaning side failed, keywords only: {exc}")
    try:
        keyword, keyword_ok = keyword_hits(session, query, KEYWORD_HITS, category), True
    except Exception as exc:  # no search column yet (migration not run): meaning only
        logger.warning(f"Search: keyword side failed, meaning only: {exc}")
        session.rollback()
    method = ("hybrid" if meaning_ok and keyword_ok else "keyword" if keyword_ok
              else "semantic" if meaning_ok else "none")
    return fuse(semantic, keyword, limit), method
