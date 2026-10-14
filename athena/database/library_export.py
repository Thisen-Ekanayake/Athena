"""
A saved list as citations (ROADMAP S2): each item as a paper dict for athena.evolution.export.

Feed items carry title, year, authors, link and (for arXiv papers) the arXiv id. A paper that is also in a map
(``EvoPaper.content_item_id``) takes the map's DOI, venue, authors and repaired year, which are better than the
feed's. Blog posts become online sources with their publisher and the export date. The reader's note and highlights
go into ``note``: the note first, then each highlight as a quote with its comment.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from athena.core.models import ContentCategory, ContentItem, EvoPaper, SavedListItem, UserHighlight, UserNote
from athena.evolution.feedlink import arxiv_id_from_url


def _note_text(note: UserNote | None, highlights: list[UserHighlight]) -> str:
    parts = [note.body.strip()] if note and note.body.strip() else []
    for h in highlights:
        parts.append(f"“{h.quote.strip()}”" + (f" ({h.comment.strip()})" if h.comment else ""))
    return "\n\n".join(parts)


def list_papers(session: Session, user_id: UUID, list_id: UUID, today: date | None = None) -> list[dict]:
    """The list's items as export paper dicts, in the list's order (newest added first)."""
    items = list(session.execute(
        select(ContentItem).join(SavedListItem, SavedListItem.item_id == ContentItem.id)
        .where(SavedListItem.list_id == list_id).order_by(SavedListItem.added_at.desc())).scalars())
    if not items:
        return []
    ids = [i.id for i in items]
    linked = {}
    for paper in session.execute(select(EvoPaper).where(EvoPaper.content_item_id.in_(ids))).scalars():
        linked.setdefault(paper.content_item_id, paper)
    targets = {f"item:{i}": i for i in ids}
    notes = {targets[n.target]: n for n in session.execute(select(UserNote).where(
        UserNote.user_id == user_id, UserNote.target.in_(list(targets)))).scalars()}
    marks = defaultdict(list)
    for h in session.execute(select(UserHighlight).where(UserHighlight.user_id == user_id,
                                                         UserHighlight.target.in_(list(targets)))
                             .order_by(UserHighlight.created_at)).scalars():
        marks[targets[h.target]].append(h)
    today = today or date.today()

    out = []
    for item in items:
        paper = {"title": item.title, "year": item.published_at.year if item.published_at else None,
                 "authors": list(item.authors or []), "url": item.url, "arxiv_id": arxiv_id_from_url(item.url)}
        evo = linked.get(item.id)
        if evo is not None:
            paper |= {"doi": evo.doi, "venue": evo.venue, "year": evo.year or paper["year"],
                      "authors": list(evo.authors or []) or paper["authors"],
                      "arxiv_id": evo.arxiv_id or paper["arxiv_id"]}
        if item.category != ContentCategory.PAPER and not paper["arxiv_id"]:
            paper |= {"kind_hint": "online", "publisher": item.source.name if item.source else None,
                      "accessed": today.isoformat()}
        note = _note_text(notes.get(item.id), marks.get(item.id, []))
        if note:
            paper["note"] = note
        out.append(paper)
    return out
