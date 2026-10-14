"""
A user's own reading state (ROADMAP P2): read marks, notes and highlights on feed items and map papers.

A feed item and a map paper can be the same paper (``EvoPaper.content_item_id``); marking either as read marks
both. Notes and highlights belong to one of them, named by ``target``: ``item:<id>`` or ``paper:<id>``.

Shared, cached payloads (the feed, an item's detail) never carry any of this: list routes add each item's
``me`` after their cache read (``overlay``), and a paper's own state comes from its ``/me`` route.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from athena.core.models import (
    ContentItem, EvoPaper, EvoReadingProgress, EvoTopic, EvoTopicPaper, ItemRead, UserHighlight, UserNote,
)

CONTEXT_CHARS = 32
NOTE_MAX = 20_000
QUOTE_MAX = 4_000


def target(kind: str, ident) -> str:
    return f"{kind}:{ident}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── read marks ───────────────────────────────────────────────────────


def _tick(session: Session, model, user_id: UUID, key: str, ident: UUID, read: bool) -> None:
    row = session.get(model, {"user_id": user_id, key: ident})
    if read and row is None:
        session.add(model(user_id=user_id, **{key: ident}))
    elif not read and row is not None:
        session.delete(row)


def set_item_read(session: Session, user_id: UUID, item_id: UUID, read: bool) -> bool:
    """Mark a feed item read or unread, and the map papers that are the same paper. False if it is unknown."""
    if session.get(ContentItem, item_id) is None:
        return False
    _tick(session, ItemRead, user_id, "item_id", item_id, read)
    for paper_id in session.execute(select(EvoPaper.id).where(EvoPaper.content_item_id == item_id)).scalars():
        _tick(session, EvoReadingProgress, user_id, "paper_id", paper_id, read)
    session.commit()
    return True


def set_paper_read(session: Session, user_id: UUID, paper_id: UUID, read: bool) -> bool:
    """Mark a map paper read or unread, and the feed item that is the same paper. False if it is unknown."""
    paper = session.get(EvoPaper, paper_id)
    if paper is None:
        return False
    _tick(session, EvoReadingProgress, user_id, "paper_id", paper_id, read)
    if paper.content_item_id:
        _tick(session, ItemRead, user_id, "item_id", paper.content_item_id, read)
    session.commit()
    return True


def read_items(session: Session, user_id: UUID, item_ids: list) -> set:
    if not item_ids:
        return set()
    return set(session.execute(select(ItemRead.item_id).where(
        ItemRead.user_id == user_id, ItemRead.item_id.in_(item_ids))).scalars().all())


def unread_filter(user_id: UUID):
    """A WHERE clause keeping feed items the user has not marked read."""
    return ~select(ItemRead.item_id).where(ItemRead.user_id == user_id,
                                           ItemRead.item_id == ContentItem.id).exists()


# ── notes ────────────────────────────────────────────────────────────


def _note_dict(note: UserNote | None) -> dict | None:
    if note is None:
        return None
    return {"body": note.body, "updated_at": note.updated_at.isoformat() if note.updated_at else None}


def get_note(session: Session, user_id: UUID, tgt: str) -> UserNote | None:
    return session.execute(select(UserNote).where(UserNote.user_id == user_id, UserNote.target == tgt)).scalar()


def save_note(session: Session, user_id: UUID, tgt: str, body: str, **ids) -> dict | None:
    """Write the note (an empty one removes it). ``ids`` is item_id= or paper_id=."""
    body = (body or "").strip()
    note = get_note(session, user_id, tgt)
    if not body:
        if note is not None:
            session.delete(note)
            session.commit()
        return None
    if note is None:
        note = UserNote(user_id=user_id, target=tgt, **ids)
        session.add(note)
    note.body = body[:NOTE_MAX]
    note.updated_at = _now()
    session.commit()
    return _note_dict(note)


# ── highlights ───────────────────────────────────────────────────────


def anchor(text: str | None, quote: str, start: int | None, prefix: str | None, suffix: str | None) -> dict | None:
    """Where ``quote`` is in ``text`` now: at its stored offset if it is still there, else the match whose
    surrounding text fits best. None when it is gone (the highlight is "detached")."""
    if not text or not quote:
        return None
    if start is not None and text[start:start + len(quote)] == quote:
        return {"start": start, "end": start + len(quote)}
    best, best_fit, at = None, -1, text.find(quote)
    while at != -1:
        before, after = text[max(0, at - CONTEXT_CHARS):at], text[at + len(quote):at + len(quote) + CONTEXT_CHARS]
        fit = _common_suffix(before, prefix or "") + _common_prefix(after, suffix or "")
        if fit > best_fit:
            best, best_fit = at, fit
        at = text.find(quote, at + 1)
    return {"start": best, "end": best + len(quote)} if best is not None else None


def _common_prefix(a: str, b: str) -> int:
    n = 0
    while n < min(len(a), len(b)) and a[n] == b[n]:
        n += 1
    return n


def _common_suffix(a: str, b: str) -> int:
    return _common_prefix(a[::-1], b[::-1])


def highlight_dict(h: UserHighlight, texts: dict[str, str] | None = None) -> dict:
    out = {"id": str(h.id), "field": h.field, "quote": h.quote, "comment": h.comment, "context": h.context or {},
           "created_at": h.created_at.isoformat() if h.created_at else None}
    if texts is not None:
        out["anchor"] = anchor(texts.get(h.field), h.quote, h.start_offset, h.prefix, h.suffix)
    return out


def highlights(session: Session, user_id: UUID, tgt: str) -> list[UserHighlight]:
    return list(session.execute(select(UserHighlight).where(
        UserHighlight.user_id == user_id, UserHighlight.target == tgt).order_by(UserHighlight.created_at)).scalars())


def add_highlight(session: Session, user_id: UUID, tgt: str, field: str, quote: str, start: int | None = None,
                  prefix: str | None = None, suffix: str | None = None, comment: str | None = None,
                  context: dict | None = None, **ids) -> UserHighlight:
    quote = quote[:QUOTE_MAX]
    h = UserHighlight(user_id=user_id, target=tgt, field=field, quote=quote, start_offset=start,
                      end_offset=start + len(quote) if start is not None else None,
                      prefix=(prefix or "")[-CONTEXT_CHARS:] or None, suffix=(suffix or "")[:CONTEXT_CHARS] or None,
                      comment=(comment or "").strip() or None, context=context or {}, **ids)
    session.add(h)
    session.commit()
    return h


def _own_highlight(session: Session, user_id: UUID, highlight_id: UUID) -> UserHighlight | None:
    h = session.get(UserHighlight, highlight_id)
    return h if h is not None and h.user_id == user_id else None


def update_highlight(session: Session, user_id: UUID, highlight_id: UUID, comment: str | None) -> dict | None:
    h = _own_highlight(session, user_id, highlight_id)
    if h is None:
        return None
    h.comment = (comment or "").strip() or None
    session.commit()
    return highlight_dict(h)


def delete_highlight(session: Session, user_id: UUID, highlight_id: UUID) -> bool:
    h = _own_highlight(session, user_id, highlight_id)
    if h is None:
        return False
    session.delete(h)
    session.commit()
    return True


# ── one paper's state ────────────────────────────────────────────────


def item_texts(item: ContentItem) -> dict[str, str]:
    """The text of each field a feed item's highlights can sit in."""
    texts = {"summary": item.summary or "", "abstract": item.abstract or ""}
    for i, t in enumerate(item.takeaways or []):
        texts[f"takeaway:{i}"] = str(t)
    return texts


def item_state(session: Session, user_id: UUID, item: ContentItem, reaction: str | None = None) -> dict:
    tgt = target("item", item.id)
    read = session.get(ItemRead, {"user_id": user_id, "item_id": item.id})
    texts = item_texts(item)
    return {"read": read is not None, "read_at": read.read_at.isoformat() if read and read.read_at else None,
            "reaction": reaction, "note": _note_dict(get_note(session, user_id, tgt)),
            "highlights": [highlight_dict(h, texts) for h in highlights(session, user_id, tgt)]}


def paper_state(session: Session, user_id: UUID, paper: EvoPaper) -> dict:
    tgt = target("paper", paper.id)
    read = session.get(EvoReadingProgress, {"user_id": user_id, "paper_id": paper.id})
    texts = {"abstract": paper.abstract or ""}
    return {"read": read is not None, "read_at": read.read_at.isoformat() if read and read.read_at else None,
            "note": _note_dict(get_note(session, user_id, tgt)),
            "highlights": [highlight_dict(h, texts) for h in highlights(session, user_id, tgt)]}


# ── lists ────────────────────────────────────────────────────────────


def overlay(session: Session, user_id: UUID, items: list[dict], reactions: dict | None = None) -> list[dict]:
    """Add ``me`` (read, reaction, annotated) to each feed item dict, in three queries for the whole page."""
    ids = [UUID(str(i["id"])) for i in items]
    if not ids:
        return items
    read = read_items(session, user_id, ids)
    targets = {target("item", i): i for i in ids}
    annotated = set()
    for model in (UserNote, UserHighlight):
        annotated |= {targets[t] for t in session.execute(select(model.target).where(
            model.user_id == user_id, model.target.in_(list(targets)))).scalars().all()}
    reactions = reactions or {}
    return [i | {"me": {"read": iid in read, "annotated": iid in annotated, "reaction": reactions.get(iid)}}
            for i, iid in zip(items, ids)]


def _items_by_id(session: Session, ids: list) -> dict:
    return {i.id: i for i in session.execute(select(ContentItem).where(ContentItem.id.in_(ids))).scalars()} \
        if ids else {}


def _papers_by_id(session: Session, ids: list) -> dict:
    """Map papers with one built map each is in, for a link to it."""
    if not ids:
        return {}
    papers = {p.id: {"paper": p, "map": None}
              for p in session.execute(select(EvoPaper).where(EvoPaper.id.in_(ids))).scalars()}
    for paper_id, slug, name in session.execute(
            select(EvoTopicPaper.paper_id, EvoTopic.slug, EvoTopic.name)
            .join(EvoTopic, EvoTopic.id == EvoTopicPaper.topic_id)
            .where(EvoTopicPaper.paper_id.in_(ids), EvoTopic.built_at.isnot(None)).order_by(EvoTopic.name)):
        if papers[paper_id]["map"] is None:
            papers[paper_id]["map"] = {"slug": slug, "name": name}
    return papers


def _about(kind: str, found) -> dict:
    if kind == "item":
        return {"kind": "item", "id": str(found.id), "title": found.title, "url": found.url,
                "source": found.source.name if found.source else None,
                "category": found.category.value if hasattr(found.category, "value") else str(found.category),
                "published_at": found.published_at.isoformat() if found.published_at else None}
    paper = found["paper"]
    return {"kind": "paper", "id": str(paper.id), "title": paper.title, "year": paper.year, "map": found["map"]}


def library_notes(session: Session, user_id: UUID, kind: str = "all", q: str | None = None) -> list[dict]:
    """Notes and highlights, one entry per paper, the most recently touched first."""
    notes = {n.target: n for n in session.execute(select(UserNote).where(UserNote.user_id == user_id)).scalars()}
    marks = defaultdict(list)
    for h in session.execute(select(UserHighlight).where(UserHighlight.user_id == user_id)
                             .order_by(UserHighlight.created_at)).scalars():
        marks[h.target].append(h)
    targets = [t for t in set(notes) | set(marks) if kind == "all" or t.startswith(kind + ":")]
    item_ids = [UUID(t.split(":", 1)[1]) for t in targets if t.startswith("item:")]
    paper_ids = [UUID(t.split(":", 1)[1]) for t in targets if t.startswith("paper:")]
    found = {target("item", k): v for k, v in _items_by_id(session, item_ids).items()} | \
        {target("paper", k): v for k, v in _papers_by_id(session, paper_ids).items()}
    needle = (q or "").strip().lower()
    out = []
    for t in targets:
        if t not in found:
            continue
        note, hs = notes.get(t), marks.get(t, [])
        about = _about(t.split(":", 1)[0], found[t])
        if needle and not any(needle in (s or "").lower() for s in
                              [about["title"], note.body if note else ""] + [h.quote for h in hs]
                              + [h.comment for h in hs]):
            continue
        times = [x for x in [note.updated_at if note else None] + [h.created_at for h in hs] if x]
        touched = max(times) if times else None
        out.append({"about": about, "note": _note_dict(note), "highlights": [highlight_dict(h) for h in hs],
                    "updated_at": touched.isoformat() if touched else None})
    out.sort(key=lambda e: e["updated_at"] or "", reverse=True)
    return out


def read_history(session: Session, user_id: UUID, page: int = 1, limit: int = 30) -> dict:
    """Feed items and map papers marked read, the latest first. A paper read in both counts once (as the item)."""
    items = session.execute(select(ItemRead.item_id, ItemRead.read_at).where(ItemRead.user_id == user_id)).all()
    papers = session.execute(
        select(EvoReadingProgress.paper_id, EvoReadingProgress.read_at, EvoPaper.content_item_id)
        .join(EvoPaper, EvoPaper.id == EvoReadingProgress.paper_id)
        .where(EvoReadingProgress.user_id == user_id)).all()
    item_ids = {i for i, _ in items}
    rows = [("item", i, at) for i, at in items] + \
        [("paper", p, at) for p, at, linked in papers if linked not in item_ids]
    rows.sort(key=lambda r: r[2] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    total = len(rows)
    rows = rows[(page - 1) * limit:page * limit]
    found_items = _items_by_id(session, [i for k, i, _ in rows if k == "item"])
    found_papers = _papers_by_id(session, [i for k, i, _ in rows if k == "paper"])
    out = []
    for kind, ident, at in rows:
        found = (found_items if kind == "item" else found_papers).get(ident)
        if found is not None:
            out.append({"about": _about(kind, found), "read_at": at.isoformat() if at else None})
    return {"entries": out, "pagination": {"page": page, "limit": limit, "total": total,
                                           "has_next": page * limit < total}}


def read_counts(session: Session, user_id: UUID, list_ids: list) -> dict:
    """How many items of each saved list the user has read."""
    from athena.core.models import SavedListItem
    if not list_ids:
        return {}
    return dict(session.execute(
        select(SavedListItem.list_id, func.count())
        .join(ItemRead, (ItemRead.item_id == SavedListItem.item_id) & (ItemRead.user_id == user_id))
        .where(SavedListItem.list_id.in_(list_ids)).group_by(SavedListItem.list_id)).all())
