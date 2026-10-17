"""
The reading path, read marks, and exports of milestones, the path and gap themes.
"""
from typing import Literal
from uuid import UUID

import redis as redis_lib
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from athena.api import auth
from athena.api.deps import get_db, get_redis
from athena.core.models import User
from athena.database import evolution as db
from athena.evolution import export, notes
from athena.api.routers.evolution._common import _built_topic_or_409

router = APIRouter()


@router.get("/topics/{slug}/reading-path")
def reading_path(
    slug: str,
    background: BackgroundTasks,
    n: int = Query(10, ge=3, le=30),
    session: Session = Depends(get_db),
    r: redis_lib.Redis = Depends(get_redis),
    user: User = Depends(auth.active_user),
):
    """``n`` papers to learn the field from. Missing notes are written after the response; poll until
    ``notes_pending`` is false."""
    topic = _built_topic_or_409(session, slug)
    path = db.reading_path(session, topic, user.id, n)
    entries = ([path["survey"]] if path["survey"] else []) + path["steps"]
    pending, error = False, None
    if any(e["why"] is None for e in entries):  # "" is a note the model could not write; not retried
        error = notes.last_failure(r, slug)
        if error is None:
            if notes.claim(r, slug):
                background.add_task(notes.write_notes, slug, [UUID(e["id"]) for e in entries], r)
            pending = True
    return path | {"notes_pending": pending, "notes_error": error}


@router.put("/papers/{paper_id}/read", status_code=204)
def mark_read(paper_id: UUID, session: Session = Depends(get_db), user: User = Depends(auth.active_user)):
    if not db.set_read(session, user.id, paper_id, True):
        raise HTTPException(status_code=404, detail="Unknown paper")


@router.delete("/papers/{paper_id}/read", status_code=204)
def mark_unread(paper_id: UUID, session: Session = Depends(get_db), user: User = Depends(auth.active_user)):
    if not db.set_read(session, user.id, paper_id, False):
        raise HTTPException(status_code=404, detail="Unknown paper")


EXPORT_FORMATS = {"milestones": {"bib", "ris", "md"}, "reading-path": {"bib", "ris", "md"}, "gaps": {"csv"}}
MEDIA_TYPES = {"bib": "application/x-bibtex", "ris": "application/x-research-info-systems",
               "md": "text/markdown", "csv": "text/csv"}


@router.get("/topics/{slug}/export")
def export_topic(
    slug: str,
    what: Literal["milestones", "reading-path", "gaps"],
    format: Literal["bib", "ris", "md", "csv"],
    n: int = Query(10, ge=3, le=30),
    session: Session = Depends(get_db),
    user: User = Depends(auth.active_user),
):
    _check_export(what, format)
    return export_file(session, _built_topic_or_409(session, slug), what, format, n, user.id)


def _check_export(what: str, format: str) -> None:
    if format not in EXPORT_FORMATS[what]:
        raise HTTPException(status_code=422, detail=f"{what} exports as {', '.join(sorted(EXPORT_FORMATS[what]))}")


def export_file(session: Session, topic, what: str, format: str, n: int, user_id: UUID | None = None) -> Response:
    """A map's milestones, reading path or gap themes as a download; shared links export without a reader."""
    _check_export(what, format)
    slug = topic.slug
    built = topic.built_at.date().isoformat() if hasattr(topic.built_at, "date") else None
    if what == "gaps":
        body = export.gaps_csv(db.gap_export_rows(session, topic))
    elif what == "milestones":
        papers = db.export_papers(session, db.milestone_ids(session, topic))
        body = export.markdown_milestones(topic.name, papers, built) if format == "md" else (
            export.bibtex(papers) if format == "bib" else export.ris(papers))
    else:
        path = db.reading_path(session, topic, user_id, n)
        entries = ([path["survey"]] if path["survey"] else []) + path["steps"]
        papers = db.export_papers(session, [UUID(e["id"]) for e in entries])
        extra = {e["id"]: {"why": e["why"], "named_method": e["named_method"]} for e in entries}
        papers = [p | extra.get(p["id"], {}) for p in papers]
        if format == "md":
            survey = papers[0] if path["survey"] else None
            body = export.markdown_path(topic.name, survey, papers[1:] if survey else papers, built)
        else:
            body = export.bibtex(papers) if format == "bib" else export.ris(papers)
    filename = f"{slug}-{what}.{format}"
    return Response(body, media_type=f"{MEDIA_TYPES[format]}; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})
