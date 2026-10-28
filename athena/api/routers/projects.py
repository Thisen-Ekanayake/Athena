"""
Projects (athena.projects): a user's workspace of papers, maps, reviews, idea checks, saved lists, files, chats and
artifacts, with instructions for every chat in it. Private to their owner.

GET    /api/v1/projects                          — yours, most recently active first, with counts
POST   /api/v1/projects                          — {name, description?, instructions?}
GET    /api/v1/projects/membership?ref=          — the projects that hold a thing (item:<id>, map:<slug>, ...)
GET    /api/v1/projects/{id}                     — the project with its items, files, artifacts and chats
PATCH  /api/v1/projects/{id}                     — name, description, instructions
DELETE /api/v1/projects/{id}                     — with its chats, files and artifacts
POST   /api/v1/projects/{id}/items               — add {kind, id} or an outside paper {kind: paper, meta}
PATCH  /api/v1/projects/{id}/items/{item_id}     — {share}: a map goes to every chat in the project as a graph
DELETE /api/v1/projects/{id}/items/{item_id}
POST   /api/v1/projects/{id}/reindex             — index everything again (after a map rebuild, say)
POST   /api/v1/projects/{id}/files               — upload files into the project's knowledge (multipart)
GET    /api/v1/files/{id}/content                — a file's bytes (previews, downloads)
DELETE /api/v1/files/{id}
"""
from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from athena.api import auth
from athena.api.deps import get_db
from athena.core.models import Artifact, EvoTopic, Project, ProjectItem, User, UserFile
from athena.database import projects as db
from athena.projects import files as uploads, index, tasks

router = APIRouter(prefix="/api/v1", tags=["Projects"])


class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    description: str = Field("", max_length=2000)
    instructions: str = Field("", max_length=20000)


class ProjectUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    description: str | None = Field(None, max_length=2000)
    instructions: str | None = Field(None, max_length=20000)


class ItemShare(BaseModel):
    share: bool


class ItemAdd(BaseModel):
    kind: Literal["paper", "map", "review", "idea_check", "list"]
    id: str | None = Field(None, max_length=300)
    meta: dict | None = None


def _own(session: Session, project_id: UUID, user: User) -> Project:
    p = db.get_project(session, user.id, project_id)
    if p is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return p


def _full(session: Session, p: Project, user: User) -> dict:
    return db.project_dict(p, db.project_counts(session, p)) | {
        "items": db.describe_items(session, db.items_of(session, p.id)),
        "files": [db.file_dict(f) for f in db.files_of(session, project_id=p.id)],
        "artifacts": [db.artifact_dict(a, content=False) for a in db.artifacts_of(session, user.id, project_id=p.id)],
        "chats": db.list_conversations(session, user.id, project_id=p.id, limit=200),
    }


@router.get("/projects")
def list_projects(session: Session = Depends(get_db), user: User = Depends(auth.active_user)):
    return {"projects": db.list_projects(session, user.id)}


@router.post("/projects", status_code=201)
def create_project(body: ProjectCreate, session: Session = Depends(get_db), user: User = Depends(auth.active_user)):
    p = db.create_project(session, user.id, body.name, body.description, body.instructions)
    return _full(session, p, user)


@router.get("/projects/membership")
def membership(ref: str, session: Session = Depends(get_db), user: User = Depends(auth.active_user)):
    """Which of your projects hold ``ref``. Maps may be named by slug (``map:<slug>``)."""
    if ref.startswith("map:"):
        topic = session.execute(select(EvoTopic).where(EvoTopic.slug == ref[4:])).scalar_one_or_none()
        if topic is not None:
            ref = f"map:{topic.id}"
    rows = session.execute(select(ProjectItem.project_id).join(Project, Project.id == ProjectItem.project_id)
                           .where(Project.user_id == user.id, ProjectItem.ref == ref)).scalars().all()
    return {"ref": ref, "project_ids": [str(r) for r in rows]}


@router.get("/projects/{project_id}")
def get_project(project_id: UUID, session: Session = Depends(get_db), user: User = Depends(auth.active_user)):
    return _full(session, _own(session, project_id, user), user)


@router.patch("/projects/{project_id}")
def update_project(project_id: UUID, body: ProjectUpdate, session: Session = Depends(get_db),
                   user: User = Depends(auth.active_user)):
    p = db.update_project(session, _own(session, project_id, user), **body.model_dump())
    return db.project_dict(p, db.project_counts(session, p))


@router.delete("/projects/{project_id}", status_code=204)
def delete_project(project_id: UUID, session: Session = Depends(get_db), user: User = Depends(auth.active_user)):
    p = _own(session, project_id, user)
    uploads.remove(db.delete_project(session, p))
    index.delete_project(project_id)
    return Response(status_code=204)


@router.post("/projects/{project_id}/items", status_code=201)
def add_item(project_id: UUID, body: ItemAdd, session: Session = Depends(get_db),
             user: User = Depends(auth.active_user)):
    p = _own(session, project_id, user)
    try:
        item, created = db.add_item(session, user.id, p, body.kind, body.id, body.meta)
    except db.ItemError as exc:
        raise HTTPException(status_code=404 if "not found" in str(exc) else 422, detail=str(exc))
    if created:
        tasks.queue(p.id)
    return db.describe_items(session, [item])[0] | {"created": created}


@router.patch("/projects/{project_id}/items/{item_id}")
def share_item(project_id: UUID, item_id: UUID, body: ItemShare, session: Session = Depends(get_db),
               user: User = Depends(auth.active_user)):
    """A map's ``share``: every chat in the project gets it as a graph (athena.evolution.digest)."""
    item = db.share_item(session, _own(session, project_id, user), item_id, body.share)
    if item is None:
        raise HTTPException(status_code=404, detail="Map not found in this project")
    return db.describe_items(session, [item])[0]


@router.delete("/projects/{project_id}/items/{item_id}", status_code=204)
def remove_item(project_id: UUID, item_id: UUID, session: Session = Depends(get_db),
                user: User = Depends(auth.active_user)):
    if not db.remove_item(session, _own(session, project_id, user), item_id):
        raise HTTPException(status_code=404, detail="Item not found")
    _forget(f"item:{item_id}")
    return Response(status_code=204)


def _forget(source: str) -> None:
    try:
        index.delete_source(source)
    except Exception:  # Qdrant down: retrieval skips sources whose rows are gone
        pass


@router.post("/projects/{project_id}/reindex", status_code=202)
def reindex(project_id: UUID, session: Session = Depends(get_db), user: User = Depends(auth.active_user)):
    p = _own(session, project_id, user)
    session.execute(update(ProjectItem).where(ProjectItem.project_id == p.id).values(index_status="pending"))
    session.execute(update(UserFile).where(UserFile.project_id == p.id, UserFile.status == "ready")
                    .values(index_status="pending"))
    session.execute(update(Artifact).where(Artifact.project_id == p.id).values(index_status="pending"))
    session.commit()
    tasks.queue(p.id)
    return {"queued": True}


# ── files ────────────────────────────────────────────────────────────


async def store_upload(session: Session, user: User, upload: UploadFile, project_id: UUID | None = None,
                       conversation_id: UUID | None = None) -> UserFile:
    """Save an upload and read its text; a file that cannot be read is kept as failed, with the reason."""
    filename = (upload.filename or "file").replace("/", "_").replace("\\", "_")[:200]
    try:
        kind, mime = uploads.kind_of(filename, upload.content_type)
    except uploads.UnsupportedFile as exc:
        raise HTTPException(status_code=415, detail=f"{filename}: {exc}")
    data = await upload.read()
    path = await run_in_threadpool(uploads.save, user.id, filename, data)
    f = UserFile(user_id=user.id, project_id=project_id, conversation_id=conversation_id, filename=filename,
                 mime=mime, kind=kind, size=len(data), path=path, status="pending",
                 index_status="pending" if project_id else "none")
    try:
        f.text, f.pages = await run_in_threadpool(uploads.extract_text, kind, data)
        f.status = "ready"
        if kind == "pdf" and not (f.text or "").strip():
            f.status, f.error = "failed", "No text could be read from this PDF (a scan?). Upload page images instead."
    except Exception as exc:
        f.status, f.error = "failed", f"The file could not be read: {str(exc)[:200]}"
    session.add(f)
    session.commit()
    return f


@router.post("/projects/{project_id}/files", status_code=201)
async def upload_project_files(project_id: UUID, files: list[UploadFile] = File(...),
                               session: Session = Depends(get_db), user: User = Depends(auth.active_user)):
    p = _own(session, project_id, user)
    saved = [await store_upload(session, user, f, project_id=p.id) for f in files]
    db.touch_project(session, p.id)
    tasks.queue(p.id)
    return {"files": [db.file_dict(f) for f in saved]}


def _own_file(session: Session, file_id: UUID, user: User) -> UserFile:
    f = db.get_file(session, user.id, file_id)
    if f is None:
        raise HTTPException(status_code=404, detail="File not found")
    return f


@router.get("/files/{file_id}/content")
def file_content(file_id: UUID, download: bool = False, session: Session = Depends(get_db),
                 user: User = Depends(auth.active_user)):
    f = _own_file(session, file_id, user)
    path = uploads.full_path(f.path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="The file is gone from the uploads folder")
    return FileResponse(path, media_type=f.mime, filename=f.filename,
                        content_disposition_type="attachment" if download else "inline")


@router.delete("/files/{file_id}", status_code=204)
def delete_file(file_id: UUID, session: Session = Depends(get_db), user: User = Depends(auth.active_user)):
    f = _own_file(session, file_id, user)
    path, project_id = f.path, f.project_id
    session.delete(f)
    db.touch_project(session, project_id, commit=False)
    session.commit()
    uploads.remove([path])
    _forget(f"file:{file_id}")
    return Response(status_code=204)
