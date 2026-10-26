"""
Chats with the local models, alone or in a project, and the artifacts they write (athena.projects).

GET    /api/v1/chat/models                       — the models a chat may pick, which ones think, the effort levels
GET    /api/v1/chats?project_id=&standalone=&q=  — yours, most recent first
POST   /api/v1/chats                             — {project_id?, model?, effort?}
GET    /api/v1/chats/{id}                        — the chat with its messages, files and artifacts
PATCH  /api/v1/chats/{id}                        — {title} and/or {project_id} (null: out of its project)
DELETE /api/v1/chats/{id}
POST   /api/v1/chats/{id}/files                  — attach files to the next message (multipart)
POST   /api/v1/chats/{id}/messages               — send one, streamed as server-sent events (athena.projects.chat);
                                                   {retry: true} answers the last question again
GET    /api/v1/artifacts?project_id=&chat_id=
POST   /api/v1/artifacts                         — one the user writes: {title, content, project_id?, chat_id?}
GET    /api/v1/artifacts/{id}
PATCH  /api/v1/artifacts/{id}                    — {title?, content?}: a new version
DELETE /api/v1/artifacts/{id}
GET    /api/v1/artifacts/{id}/versions
GET    /api/v1/artifacts/{id}/versions/{n}
POST   /api/v1/artifacts/{id}/restore            — {version}: a new version with that one's text
GET    /api/v1/artifacts/{id}/export             — the Markdown as a download

No daily allowance: the models are the user's own. The monthly budget and token cap (athena.core.usage) still
refuse other accounts once spent.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from athena.api import auth
from athena.api.deps import get_db
from athena.api.routers.projects import _forget, store_upload
from athena.core import llm, usage
from athena.core.models import ChatMessage, Conversation, Project, User, UserFile
from athena.database import projects as db
from athena.projects import chat, files as uploads, index, tasks, tools

router = APIRouter(prefix="/api/v1", tags=["Chats"])

Effort = Literal["off", "low", "medium", "high"]
STALE_STREAM = timedelta(minutes=15)   # a "streaming" message this old lost its worker


class ChatCreate(BaseModel):
    project_id: UUID | None = None
    model: str | None = Field(None, max_length=200)
    effort: Effort | None = None


class ChatUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=120)
    project_id: UUID | None = None


class MessageSend(BaseModel):
    content: str = Field("", max_length=100_000)
    model: str | None = Field(None, max_length=200)
    effort: Effort | None = None
    attachment_ids: list[UUID] = Field(default_factory=list, max_length=20)
    retry: bool = False


class ArtifactCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=120)
    content: str = Field("", max_length=1_000_000)
    project_id: UUID | None = None
    chat_id: UUID | None = None


class ArtifactUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=120)
    content: str | None = Field(None, max_length=1_000_000)


class Restore(BaseModel):
    version: int = Field(..., ge=1)


def _refuse_if_spent(user: User) -> None:
    if user.role != "admin" and (reason := usage.refusal(user)):
        raise HTTPException(status_code=429, detail=reason)


def _own_chat(session: Session, chat_id: UUID, user: User) -> Conversation:
    c = db.get_conversation(session, user.id, chat_id)
    if c is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    return c


def _own_project(session: Session, project_id: UUID | None, user: User) -> Project | None:
    if project_id is None:
        return None
    p = db.get_project(session, user.id, project_id)
    if p is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return p


def _message(m: ChatMessage) -> dict:
    out = db.message_dict(m)
    if m.status == "streaming" and m.created_at and \
            datetime.now(timezone.utc) - _aware(m.created_at) > STALE_STREAM:
        out["status"] = "stopped"
    return out


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# ── models ───────────────────────────────────────────────────────────


@router.get("/chat/models")
def chat_models(user: User = Depends(auth.active_user)):
    models = llm.chat_models()
    default = llm.chat_model()
    return {"models": models, "default": default if any(m["id"] == default for m in models)
            else (models[0]["id"] if models else default),
            "efforts": [{"id": e, "budget": b} for e, b in llm.EFFORT_BUDGETS.items()], "default_effort": "low",
            "vision_model": llm.vision_model()}


# ── chats ────────────────────────────────────────────────────────────


@router.get("/chats")
def list_chats(project_id: UUID | None = None, standalone: bool = False, q: str | None = None, limit: int = 50,
               session: Session = Depends(get_db), user: User = Depends(auth.active_user)):
    return {"chats": db.list_conversations(session, user.id, project_id=project_id, standalone=standalone,
                                           limit=max(1, min(limit, 500)), query=(q or "").strip() or None)}


@router.post("/chats", status_code=201)
def create_chat(body: ChatCreate, session: Session = Depends(get_db), user: User = Depends(auth.active_user)):
    project = _own_project(session, body.project_id, user)
    c = db.create_conversation(session, user.id, project.id if project else None, model=body.model,
                               effort=body.effort)
    return db.conversation_dict(c, project)


@router.get("/chats/{chat_id}")
def get_chat(chat_id: UUID, session: Session = Depends(get_db), user: User = Depends(auth.active_user)):
    c = _own_chat(session, chat_id, user)
    project = session.get(Project, c.project_id) if c.project_id else None
    return db.conversation_dict(c, project) | {
        "messages": [_message(m) for m in db.messages_of(session, c.id)],
        "files": [db.file_dict(f) for f in db.files_of(session, conversation_id=c.id)],
        "artifacts": [db.artifact_dict(a, content=False)
                      for a in db.artifacts_of(session, user.id, conversation_id=c.id)],
    }


@router.patch("/chats/{chat_id}")
def update_chat(chat_id: UUID, body: ChatUpdate, session: Session = Depends(get_db),
                user: User = Depends(auth.active_user)):
    c = _own_chat(session, chat_id, user)
    if body.title:
        c.title = body.title.strip()
        session.commit()
    if "project_id" in body.model_fields_set and body.project_id != c.project_id:
        old = c.project_id
        project = _own_project(session, body.project_id, user)
        db.move_conversation(session, c, project.id if project else None)
        if old:
            for a in db.artifacts_of(session, user.id, conversation_id=c.id):
                _forget(f"artifact:{a.id}")
        if project:
            tasks.queue(project.id)
    project = session.get(Project, c.project_id) if c.project_id else None
    return db.conversation_dict(c, project)


@router.delete("/chats/{chat_id}", status_code=204)
def delete_chat(chat_id: UUID, session: Session = Depends(get_db), user: User = Depends(auth.active_user)):
    uploads.remove(db.delete_conversation(session, _own_chat(session, chat_id, user)))
    return Response(status_code=204)


@router.post("/chats/{chat_id}/files", status_code=201)
async def upload_chat_files(chat_id: UUID, files: list[UploadFile] = File(...), session: Session = Depends(get_db),
                            user: User = Depends(auth.active_user)):
    c = _own_chat(session, chat_id, user)
    saved = [await store_upload(session, user, f, conversation_id=c.id) for f in files]
    return {"files": [db.file_dict(f) for f in saved]}


# ── a turn ───────────────────────────────────────────────────────────


def _attachment(f: UserFile) -> dict:
    return {"id": str(f.id), "filename": f.filename, "kind": f.kind, "text": f.text, "path": f.path, "mime": f.mime,
            "caption": f.caption}


def _history(messages: list[ChatMessage]) -> list[dict]:
    out = []
    for m in messages:
        if m.role not in ("user", "assistant") or (m.role == "assistant" and not m.content):
            continue
        text = m.content
        if m.role == "user" and m.attachments:
            text += "\n\n(" + ", ".join(f"attached {a['filename']}" for a in m.attachments) + ")"
        out.append({"role": m.role, "content": text})
    return out


def _catalog(session: Session, project: Project, user: User) -> list[str]:
    kinds = {"paper": "Paper", "map": "Research map", "review": "Literature review", "idea_check": "Idea check",
             "list": "Saved list"}
    lines = [f"- {kinds.get(i['kind'], i['kind'])}: {i['title']}"
             + (f" (map slug {i['slug']})" if i.get("slug") else "")
             for i in db.describe_items(session, db.items_of(session, project.id))]
    lines += [f"- File: {f.filename}" for f in db.files_of(session, project_id=project.id)]
    lines += [f"- Chat: {c['title']}"
              for c in db.list_conversations(session, user.id, project_id=project.id, limit=20)]
    return lines


@router.post("/chats/{chat_id}/messages")
async def send_message(chat_id: UUID, body: MessageSend, session: Session = Depends(get_db),
                       user: User = Depends(auth.active_user)):
    _refuse_if_spent(user)
    c = _own_chat(session, chat_id, user)
    history = db.messages_of(session, c.id)
    if history and history[-1].status == "streaming" and _message(history[-1])["status"] == "streaming":
        raise HTTPException(status_code=409, detail="This chat is still answering; wait or stop it first")

    if body.retry:  # answer the last question again: drop the answer after it
        while history and history[-1].role == "assistant":
            session.delete(history.pop())
        session.commit()
        if not history:
            raise HTTPException(status_code=409, detail="There is no question to answer again")
        question_msg = history.pop()
        question, attached = question_msg.content, [UUID(a["id"]) for a in question_msg.attachments or []]
    else:
        question, attached = body.content.strip(), body.attachment_ids
        if not question:
            raise HTTPException(status_code=422, detail="Write a message")
    files = []
    if attached:
        files = list(session.execute(select(UserFile).where(UserFile.id.in_(attached), UserFile.user_id == user.id,
                                                            UserFile.conversation_id == c.id)).scalars())
        if len(files) != len(set(attached)) and not body.retry:
            raise HTTPException(status_code=404, detail="An attached file was not found in this chat")
        if bad := [f.filename for f in files if f.status != "ready"]:
            raise HTTPException(status_code=422, detail=f"Not readable: {', '.join(bad)}")

    models = {m["id"]: m for m in llm.chat_models()}
    model = body.model or c.model or llm.chat_model()
    if models and model not in models:
        raise HTTPException(status_code=422, detail=f"The model {model} is not available")
    effort = body.effort or c.effort or "low"
    c.model, c.effort = model, effort
    first_turn = not history
    if not body.retry:
        db.add_message(session, c, "user", question, attachments=[
            {"id": str(f.id), "filename": f.filename, "kind": f.kind} for f in files])
    reply = db.add_message(session, c, "assistant", "", status="streaming", model=model, effort=effort)

    project = session.get(Project, c.project_id) if c.project_id else None
    turn = chat.Turn(
        user_id=user.id, conversation_id=c.id, message_id=reply.id, project_id=project.id if project else None,
        project_name=project.name if project else None, project_description=project.description if project else "",
        instructions=project.instructions if project else "",
        catalog=_catalog(session, project, user) if project else [],
        artifacts=[{"id": str(a.id), "title": a.title, "chars": len(a.content or "")} for a in
                   db.artifacts_of(session, user.id, project_id=project.id if project else None,
                                   conversation_id=None if project else c.id)],
        history=_history(history), question=question, attachments=[_attachment(f) for f in files], model=model,
        effort=effort, first_turn=first_turn, maps=tools.ready_maps(session))
    reply_id, title_wanted = reply.id, first_turn and c.title == "New chat"

    def retrieve(q: str):
        return index.retrieve(turn.project_id, q)

    def save(fields: dict) -> dict:
        from athena.database.db import SessionLocal
        with SessionLocal() as s:
            m = s.get(ChatMessage, reply_id)
            for key, value in fields.items():
                setattr(m, key, value)
            conv = s.get(Conversation, turn.conversation_id)
            conv.updated_at = datetime.now(timezone.utc)
            s.commit()
            return db.message_dict(m)

    def name_chat(answer: str) -> str | None:
        from athena.database.db import SessionLocal
        title = chat.title_for(question, answer, model) if model == llm.chat_model() else None
        title = title or (" ".join(question.split()[:8])[:80] or "New chat")
        with SessionLocal() as s:
            conv = s.get(Conversation, turn.conversation_id)
            if conv.title == "New chat":
                conv.title = title
                s.commit()
        return title

    async def stream():
        yield _sse({"type": "start", "message_id": str(reply_id), "model": model, "effort": effort})
        answer, wrote = "", False
        async for event in chat.run(turn, retrieve, tools.execute, save):
            if event["type"] == "done":
                answer = event["message"]["content"]
            wrote = wrote or event["type"] == "artifact"
            yield _sse(event)
        if title_wanted:
            title = await run_in_threadpool(name_chat, answer)
            yield _sse({"type": "title", "title": title})
        if project and wrote:  # artifacts written in a project join its search
            tasks.queue(project.id)
        yield "data: [DONE]\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, default=str)}\n\n"


# ── artifacts ────────────────────────────────────────────────────────


def _own_artifact(session: Session, artifact_id: UUID, user: User):
    a = db.get_artifact(session, user.id, artifact_id)
    if a is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return a


@router.get("/artifacts")
def list_artifacts(project_id: UUID | None = None, chat_id: UUID | None = None, session: Session = Depends(get_db),
                   user: User = Depends(auth.active_user)):
    return {"artifacts": [db.artifact_dict(a, content=False) for a in
                          db.artifacts_of(session, user.id, project_id=project_id, conversation_id=chat_id)]}


@router.post("/artifacts", status_code=201)
def create_artifact(body: ArtifactCreate, session: Session = Depends(get_db), user: User = Depends(auth.active_user)):
    project = _own_project(session, body.project_id, user)
    conv = _own_chat(session, body.chat_id, user) if body.chat_id else None
    a = db.create_artifact(session, user.id, body.title, body.content, author="user",
                           project_id=project.id if project else (conv.project_id if conv else None),
                           conversation_id=conv.id if conv else None)
    if a.project_id:
        tasks.queue(a.project_id)
    return db.artifact_dict(a)


@router.get("/artifacts/{artifact_id}")
def get_artifact(artifact_id: UUID, session: Session = Depends(get_db), user: User = Depends(auth.active_user)):
    return db.artifact_dict(_own_artifact(session, artifact_id, user))


@router.patch("/artifacts/{artifact_id}")
def update_artifact(artifact_id: UUID, body: ArtifactUpdate, session: Session = Depends(get_db),
                    user: User = Depends(auth.active_user)):
    a = db.revise_artifact(session, _own_artifact(session, artifact_id, user), content=body.content,
                           title=body.title, author="user")
    if a.project_id and a.index_status == "pending":
        tasks.queue(a.project_id)
    return db.artifact_dict(a)


@router.delete("/artifacts/{artifact_id}", status_code=204)
def delete_artifact(artifact_id: UUID, session: Session = Depends(get_db), user: User = Depends(auth.active_user)):
    a = _own_artifact(session, artifact_id, user)
    project_id = a.project_id
    session.delete(a)
    db.touch_project(session, project_id, commit=False)
    session.commit()
    _forget(f"artifact:{artifact_id}")
    return Response(status_code=204)


@router.get("/artifacts/{artifact_id}/versions")
def artifact_versions(artifact_id: UUID, session: Session = Depends(get_db), user: User = Depends(auth.active_user)):
    return {"versions": db.artifact_versions(session, _own_artifact(session, artifact_id, user).id)}


@router.get("/artifacts/{artifact_id}/versions/{version}")
def artifact_version(artifact_id: UUID, version: int, session: Session = Depends(get_db),
                     user: User = Depends(auth.active_user)):
    v = db.artifact_version(session, _own_artifact(session, artifact_id, user).id, version)
    if v is None:
        raise HTTPException(status_code=404, detail="Version not found")
    return {"version": v.version, "title": v.title, "content": v.content, "author": v.author,
            "created_at": v.created_at.isoformat() if v.created_at else None}


@router.post("/artifacts/{artifact_id}/restore")
def restore_artifact(artifact_id: UUID, body: Restore, session: Session = Depends(get_db),
                     user: User = Depends(auth.active_user)):
    a = _own_artifact(session, artifact_id, user)
    v = db.artifact_version(session, a.id, body.version)
    if v is None:
        raise HTTPException(status_code=404, detail="Version not found")
    a = db.revise_artifact(session, a, content=v.content, title=v.title, author="user")
    if a.project_id and a.index_status == "pending":
        tasks.queue(a.project_id)
    return db.artifact_dict(a)


@router.get("/artifacts/{artifact_id}/export")
def export_artifact(artifact_id: UUID, session: Session = Depends(get_db), user: User = Depends(auth.active_user)):
    a = _own_artifact(session, artifact_id, user)
    name = "".join(ch if ch.isalnum() else "-" for ch in a.title.lower()).strip("-")[:80] or "artifact"
    body = a.content if a.content.lstrip().startswith("# ") else f"# {a.title}\n\n{a.content}"
    return Response(body, media_type="text/markdown; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}.md"'})
