"""
A user's own reading state (ROADMAP P2): read marks, notes and highlights on feed items and map papers.

PUT|DELETE /api/v1/items/{item_id}/read                     — mark a feed item read or unread
GET        /api/v1/items/{item_id}/me                       — read mark, reaction, note and highlights
PUT|DELETE /api/v1/items/{item_id}/note                     — write or remove the note (an empty one removes it)
GET|POST   /api/v1/items/{item_id}/highlights               — the item's highlights; add one
GET        /api/v1/evolution/papers/{paper_id}/me           — the same for a map paper (read = the reading-path tick)
PUT|DELETE /api/v1/evolution/papers/{paper_id}/note
GET|POST   /api/v1/evolution/papers/{paper_id}/highlights
PATCH|DELETE /api/v1/highlights/{highlight_id}              — change a highlight's comment; remove it
GET        /api/v1/library/notes?kind=all|item|paper&q=     — notes and highlights, one entry per paper
GET        /api/v1/library/read?page=                       — what was marked read, the latest first

Everything is the user's own: another user's highlight answers 404.
"""
from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from athena.api import auth
from athena.api.deps import get_db
from athena.core.models import ContentItem, EvoPaper, User
from athena.database import personal

router = APIRouter(prefix="/api/v1", tags=["Reading"])

ITEM_FIELDS = ("summary", "abstract")


class NoteRequest(BaseModel):
    body: str = Field("", max_length=personal.NOTE_MAX)


class HighlightRequest(BaseModel):
    field: str
    quote: str = Field(..., min_length=1, max_length=personal.QUOTE_MAX)
    start: int | None = Field(None, ge=0)
    prefix: str | None = Field(None, max_length=200)
    suffix: str | None = Field(None, max_length=200)
    comment: str | None = Field(None, max_length=2000)
    context: dict = Field(default_factory=dict)

    @field_validator("quote")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("a highlight needs some text")
        return value


class HighlightUpdate(BaseModel):
    comment: str | None = Field(None, max_length=2000)


def _item(session: Session, item_id: UUID) -> ContentItem:
    item = session.get(ContentItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return item


def _paper(session: Session, paper_id: UUID) -> EvoPaper:
    paper = session.get(EvoPaper, paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="Paper not found")
    return paper


def _check_field(field: str, allowed: tuple[str, ...], takeaways: int = 0) -> None:
    if field in allowed:
        return
    if takeaways and field.startswith("takeaway:") and field[9:].isdigit() and int(field[9:]) < takeaways:
        return
    raise HTTPException(status_code=422, detail=f"Highlights go in {', '.join(allowed)}"
                        + (" or a takeaway" if takeaways else ""))


# ── feed items ───────────────────────────────────────────────────────


@router.put("/items/{item_id}/read", status_code=204)
def mark_item_read(item_id: UUID, session: Session = Depends(get_db), user: User = Depends(auth.active_user)):
    if not personal.set_item_read(session, user.id, item_id, True):
        raise HTTPException(status_code=404, detail="Item not found")
    return Response(status_code=204)


@router.delete("/items/{item_id}/read", status_code=204)
def mark_item_unread(item_id: UUID, session: Session = Depends(get_db), user: User = Depends(auth.active_user)):
    if not personal.set_item_read(session, user.id, item_id, False):
        raise HTTPException(status_code=404, detail="Item not found")
    return Response(status_code=204)


@router.get("/items/{item_id}/me")
def item_me(item_id: UUID, session: Session = Depends(get_db), user: User = Depends(auth.active_user)):
    return personal.item_state(session, user.id, _item(session, item_id))


@router.put("/items/{item_id}/note")
def save_item_note(item_id: UUID, body: NoteRequest, session: Session = Depends(get_db),
                   user: User = Depends(auth.active_user)):
    _item(session, item_id)
    return {"note": personal.save_note(session, user.id, personal.target("item", item_id), body.body,
                                       item_id=item_id)}


@router.delete("/items/{item_id}/note", status_code=204)
def delete_item_note(item_id: UUID, session: Session = Depends(get_db), user: User = Depends(auth.active_user)):
    personal.save_note(session, user.id, personal.target("item", item_id), "")
    return Response(status_code=204)


@router.get("/items/{item_id}/highlights")
def item_highlights(item_id: UUID, session: Session = Depends(get_db), user: User = Depends(auth.active_user)):
    return {"highlights": personal.item_state(session, user.id, _item(session, item_id))["highlights"]}


@router.post("/items/{item_id}/highlights", status_code=201)
def add_item_highlight(item_id: UUID, body: HighlightRequest, session: Session = Depends(get_db),
                       user: User = Depends(auth.active_user)):
    item = _item(session, item_id)
    _check_field(body.field, ITEM_FIELDS, len(item.takeaways or []))
    h = personal.add_highlight(session, user.id, personal.target("item", item_id), item_id=item_id,
                               **body.model_dump())
    return personal.highlight_dict(h, personal.item_texts(item))


# ── map papers ───────────────────────────────────────────────────────


@router.get("/evolution/papers/{paper_id}/me")
def paper_me(paper_id: UUID, session: Session = Depends(get_db), user: User = Depends(auth.active_user)):
    return personal.paper_state(session, user.id, _paper(session, paper_id))


@router.put("/evolution/papers/{paper_id}/note")
def save_paper_note(paper_id: UUID, body: NoteRequest, session: Session = Depends(get_db),
                    user: User = Depends(auth.active_user)):
    _paper(session, paper_id)
    return {"note": personal.save_note(session, user.id, personal.target("paper", paper_id), body.body,
                                       paper_id=paper_id)}


@router.delete("/evolution/papers/{paper_id}/note", status_code=204)
def delete_paper_note(paper_id: UUID, session: Session = Depends(get_db), user: User = Depends(auth.active_user)):
    personal.save_note(session, user.id, personal.target("paper", paper_id), "")
    return Response(status_code=204)


@router.get("/evolution/papers/{paper_id}/highlights")
def paper_highlights(paper_id: UUID, session: Session = Depends(get_db), user: User = Depends(auth.active_user)):
    return {"highlights": personal.paper_state(session, user.id, _paper(session, paper_id))["highlights"]}


@router.post("/evolution/papers/{paper_id}/highlights", status_code=201)
def add_paper_highlight(paper_id: UUID, body: HighlightRequest, session: Session = Depends(get_db),
                        user: User = Depends(auth.active_user)):
    paper = _paper(session, paper_id)
    _check_field(body.field, ("abstract", "passage"))
    h = personal.add_highlight(session, user.id, personal.target("paper", paper_id), paper_id=paper_id,
                               **body.model_dump())
    return personal.highlight_dict(h, {"abstract": paper.abstract or ""})


# ── highlights, library ──────────────────────────────────────────────


@router.patch("/highlights/{highlight_id}")
def update_highlight(highlight_id: UUID, body: HighlightUpdate, session: Session = Depends(get_db),
                     user: User = Depends(auth.active_user)):
    updated = personal.update_highlight(session, user.id, highlight_id, body.comment)
    if updated is None:
        raise HTTPException(status_code=404, detail="Highlight not found")
    return updated


@router.delete("/highlights/{highlight_id}", status_code=204)
def delete_highlight(highlight_id: UUID, session: Session = Depends(get_db), user: User = Depends(auth.active_user)):
    if not personal.delete_highlight(session, user.id, highlight_id):
        raise HTTPException(status_code=404, detail="Highlight not found")
    return Response(status_code=204)


@router.get("/library/notes")
def library_notes(kind: Literal["all", "item", "paper"] = "all", q: str | None = Query(None, max_length=200),
                  session: Session = Depends(get_db), user: User = Depends(auth.active_user)):
    return {"entries": personal.library_notes(session, user.id, kind, q)}


@router.get("/library/read")
def library_read(page: int = Query(1, ge=1), limit: int = Query(30, ge=1, le=100),
                 session: Session = Depends(get_db), user: User = Depends(auth.active_user)):
    return personal.read_history(session, user.id, page, limit)
