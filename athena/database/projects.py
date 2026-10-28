"""
Projects, chats, uploaded files and artifacts: reads, writes and the shapes the API returns (athena.projects).

Everything here belongs to one user; callers pass ``user_id`` and get None for someone else's rows, which routes
answer as 404. Indexing (athena.projects.index) follows ``index_status`` on items, files and artifacts.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import Integer, func, select, update
from sqlalchemy.orm import Session

from athena.core.models import (
    Artifact, ArtifactVersion, ChatMessage, ContentItem, Conversation, ConversationMap, EvoIdeaCheck, EvoPaper,
    EvoTopic, EvoTopicPaper, LitReview, Project, ProjectItem, SavedList, SavedListItem, UserFile,
)

KINDS = ("paper", "map", "review", "idea_check", "list")
MAP_KEYS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"  # one letter per map a chat holds
TITLE_MAX = 120


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


# ── projects ─────────────────────────────────────────────────────────


def project_dict(p: Project, counts: dict | None = None) -> dict:
    return {"id": str(p.id), "name": p.name, "description": p.description or "", "instructions": p.instructions or "",
            "created_at": _iso(p.created_at), "updated_at": _iso(p.updated_at), "counts": counts or {}}


def _counts(session: Session, project_ids: list[UUID]) -> dict[UUID, dict]:
    out = {pid: {"chats": 0, "items": 0, "files": 0, "artifacts": 0} for pid in project_ids}
    if not project_ids:
        return out
    for key, model in (("chats", Conversation), ("items", ProjectItem), ("files", UserFile), ("artifacts", Artifact)):
        for pid, n in session.execute(select(model.project_id, func.count()).where(
                model.project_id.in_(project_ids)).group_by(model.project_id)):
            out[pid][key] = n
    return out


def list_projects(session: Session, user_id: UUID) -> list[dict]:
    rows = session.execute(select(Project).where(Project.user_id == user_id)
                           .order_by(Project.updated_at.desc())).scalars().all()
    counts = _counts(session, [p.id for p in rows])
    return [project_dict(p, counts[p.id]) for p in rows]


def get_project(session: Session, user_id: UUID, project_id: UUID) -> Project | None:
    p = session.get(Project, project_id)
    return p if p is not None and p.user_id == user_id else None


def project_counts(session: Session, project: Project) -> dict:
    return _counts(session, [project.id])[project.id]


def create_project(session: Session, user_id: UUID, name: str, description: str = "",
                   instructions: str = "") -> Project:
    p = Project(user_id=user_id, name=name.strip()[:TITLE_MAX], description=description.strip(),
                instructions=instructions.strip(), created_at=_now(), updated_at=_now())
    session.add(p)
    session.commit()
    return p


def update_project(session: Session, project: Project, **fields) -> Project:
    for key in ("name", "description", "instructions"):
        if fields.get(key) is not None:
            value = fields[key].strip()
            setattr(project, key, value[:TITLE_MAX] if key == "name" else value)
    touch_project(session, project.id, commit=False)
    session.commit()
    return project


def touch_project(session: Session, project_id: UUID | None, commit: bool = True) -> None:
    if project_id is None:
        return
    session.execute(update(Project).where(Project.id == project_id).values(updated_at=_now()))
    if commit:
        session.commit()


def delete_project(session: Session, project: Project) -> list[str]:
    """Remove a project with its chats, items, files and artifacts; returns the files' paths to delete."""
    paths = list(session.execute(select(UserFile.path).where(
        (UserFile.project_id == project.id)
        | UserFile.conversation_id.in_(select(Conversation.id).where(Conversation.project_id == project.id))
    )).scalars())
    for model in (UserFile, Artifact, Conversation, ProjectItem):  # SQLite tests do not cascade
        for row in session.execute(select(model).where(model.project_id == project.id)).scalars():
            session.delete(row)
    session.delete(project)
    session.commit()
    return paths


# ── project items ────────────────────────────────────────────────────


class ItemError(ValueError):
    """The thing to add does not exist, or belongs to someone else."""


def _ref_for(session: Session, user_id: UUID, kind: str, ident: str | None, meta: dict | None) -> tuple[str, dict]:
    """The ``ref`` and foreign keys for adding ``kind``/``ident`` to a project, checked."""
    def uuid(value) -> UUID:
        try:
            return UUID(str(value))
        except ValueError:
            raise ItemError(f"Not an id: {value}")

    if kind == "paper":
        if meta and not ident:  # found by search, not in Athena
            key = meta.get("doi") or meta.get("arxiv_id") or meta.get("external_id") or meta.get("url")
            if not key or not meta.get("title"):
                raise ItemError("An outside paper needs a title and a DOI, arXiv id or link")
            clean = {k: meta.get(k) for k in ("title", "abstract", "url", "year", "authors", "doi", "arxiv_id",
                                              "external_id", "source") if meta.get(k) is not None}
            return f"ext:{key}", {"meta": clean}
        if ident and str(ident).startswith("paper:"):
            pid = uuid(str(ident)[6:])
            if session.get(EvoPaper, pid) is None:
                raise ItemError("Paper not found")
            return f"paper:{pid}", {"paper_id": pid}
        iid = uuid(str(ident).removeprefix("item:"))
        if session.get(ContentItem, iid) is None:
            raise ItemError("Paper not found")
        return f"item:{iid}", {"item_id": iid}
    if kind == "map":
        topic = session.execute(select(EvoTopic).where(EvoTopic.slug == ident)).scalar_one_or_none() \
            if ident and not _is_uuid(ident) else session.get(EvoTopic, uuid(ident))
        if topic is None:
            raise ItemError("Map not found")
        return f"map:{topic.id}", {"topic_id": topic.id}
    owned = {"review": (LitReview, "review_id", "review"), "idea_check": (EvoIdeaCheck, "idea_check_id", "idea"),
             "list": (SavedList, "list_id", "list")}
    if kind in owned:
        model, column, prefix = owned[kind]
        row = session.get(model, uuid(ident))
        if row is None or row.user_id != user_id:
            raise ItemError(f"{kind.replace('_', ' ').capitalize()} not found")
        return f"{prefix}:{row.id}", {column: row.id}
    raise ItemError(f"Unknown kind: {kind}")


def _is_uuid(value: str) -> bool:
    try:
        UUID(str(value))
        return True
    except ValueError:
        return False


def add_item(session: Session, user_id: UUID, project: Project, kind: str, ident: str | None = None,
             meta: dict | None = None) -> tuple[ProjectItem, bool]:
    """Add something to a project; (item, created). Adding it again returns the row already there."""
    ref, columns = _ref_for(session, user_id, kind, ident, meta)
    existing = session.execute(select(ProjectItem).where(ProjectItem.project_id == project.id,
                                                         ProjectItem.ref == ref)).scalar_one_or_none()
    if existing is not None:
        return existing, False
    item = ProjectItem(project_id=project.id, kind=kind, ref=ref, index_status="pending", added_at=_now(),
                       **{"meta": {}} | columns)
    session.add(item)
    touch_project(session, project.id, commit=False)
    session.commit()
    return item, True


def remove_item(session: Session, project: Project, item_id: UUID) -> bool:
    item = session.get(ProjectItem, item_id)
    if item is None or item.project_id != project.id:
        return False
    session.delete(item)
    touch_project(session, project.id, commit=False)
    session.commit()
    return True


def share_item(session: Session, project: Project, item_id: UUID, share: bool) -> ProjectItem | None:
    """Give a project's map to its chats as a graph, or stop; None for an item that is not one of its maps."""
    item = session.get(ProjectItem, item_id)
    if item is None or item.project_id != project.id or item.kind != "map":
        return None
    item.share = share
    session.commit()
    return item


def items_of(session: Session, project_id: UUID) -> list[ProjectItem]:
    return list(session.execute(select(ProjectItem).where(ProjectItem.project_id == project_id)
                                .order_by(ProjectItem.added_at.desc())).scalars())


def describe_items(session: Session, items: list[ProjectItem]) -> list[dict]:
    """Each item with what the page shows: title, a line under it, and where it links."""
    def ids(column: str) -> list[UUID]:
        return [getattr(i, column) for i in items if getattr(i, column)]

    def load(model, column):
        wanted = ids(column)
        return {r.id: r for r in session.execute(select(model).where(model.id.in_(wanted))).scalars()} \
            if wanted else {}

    feed, papers, topics = load(ContentItem, "item_id"), load(EvoPaper, "paper_id"), load(EvoTopic, "topic_id")
    reviews, ideas = load(LitReview, "review_id"), load(EvoIdeaCheck, "idea_check_id")
    lists = load(SavedList, "list_id")
    list_sizes = dict(session.execute(select(SavedListItem.list_id, func.count()).where(
        SavedListItem.list_id.in_(list(lists))).group_by(SavedListItem.list_id)).all()) if lists else {}

    out = []
    for i in items:
        title, subtitle, link, extra = "(removed)", None, None, {}
        if i.item_id and (c := feed.get(i.item_id)):
            title, link = c.title, f"/items/{c.id}"
            subtitle = ", ".join((c.authors or [])[:3]) + (f" · {c.published_at.year}" if c.published_at else "")
            extra = {"url": c.url}
        elif i.paper_id and (p := papers.get(i.paper_id)):
            names = [a.get("name") if isinstance(a, dict) else str(a) for a in (p.authors or [])[:3]]
            title, subtitle = p.title, ", ".join(n for n in names if n) + (f" · {p.year}" if p.year else "")
            extra = {"url": p.oa_pdf_url or (f"https://doi.org/{p.doi}" if p.doi else None)}
        elif i.ref.startswith("ext:"):
            m = i.meta or {}
            title = m.get("title") or i.ref[4:]
            subtitle = ", ".join((m.get("authors") or [])[:3]) + (f" · {m['year']}" if m.get("year") else "")
            extra = {"url": m.get("url")}
        elif i.topic_id and (t := topics.get(i.topic_id)):
            title, subtitle, link = t.name, t.description, f"/evolution/{t.slug}"
            extra = {"slug": t.slug, "built": t.built_at is not None, "share": bool(i.share),
                     "topic_id": str(t.id)}
        elif i.review_id and (r := reviews.get(i.review_id)):
            title, subtitle, link = r.title, r.status, f"/reviews/{r.id}"
        elif i.idea_check_id and (c := ideas.get(i.idea_check_id)):
            title, subtitle, link = c.idea[:TITLE_MAX], "Idea check", f"/evolution/ideas?check={c.id}"
        elif i.list_id and (sl := lists.get(i.list_id)):
            title, subtitle, link = sl.name, f"{list_sizes.get(sl.id, 0)} saved items", "/library"
        out.append({"id": str(i.id), "kind": i.kind, "ref": i.ref, "title": title, "subtitle": (subtitle or "").strip(
            " ·") or None, "link": link, "index_status": i.index_status, "index_error": i.index_error,
            "added_at": _iso(i.added_at)} | extra)
    return out


# ── conversations and messages ───────────────────────────────────────


def conversation_dict(c: Conversation, project: Project | None = None) -> dict:
    return {"id": str(c.id), "title": c.title, "project_id": str(c.project_id) if c.project_id else None,
            "project_name": project.name if project else None, "model": c.model, "effort": c.effort,
            "context": c.context, "pinned": c.pinned_at is not None, "archived": c.archived_at is not None,
            "created_at": _iso(c.created_at), "updated_at": _iso(c.updated_at)}


def list_conversations(session: Session, user_id: UUID, project_id: UUID | None = None, standalone: bool = False,
                       limit: int = 50, query: str | None = None, archived: bool = False) -> list[dict]:
    """Pinned chats first, then the most recent. Archived chats only when asked for, and then only those."""
    stmt = select(Conversation, Project).outerjoin(Project, Project.id == Conversation.project_id).where(
        Conversation.user_id == user_id)
    if project_id is not None:
        stmt = stmt.where(Conversation.project_id == project_id)
    elif standalone:
        stmt = stmt.where(Conversation.project_id.is_(None))
    if query:
        stmt = stmt.where(Conversation.title.ilike(f"%{query}%"))
    stmt = stmt.where(Conversation.archived_at.isnot(None) if archived else Conversation.archived_at.is_(None))
    order = (Conversation.updated_at.desc(),) if archived else \
        (Conversation.pinned_at.is_(None), Conversation.pinned_at.desc(), Conversation.updated_at.desc())
    rows = session.execute(stmt.order_by(*order).limit(limit)).all()
    return [conversation_dict(c, p) for c, p in rows]


def get_conversation(session: Session, user_id: UUID, conversation_id: UUID) -> Conversation | None:
    c = session.get(Conversation, conversation_id)
    return c if c is not None and c.user_id == user_id else None


def create_conversation(session: Session, user_id: UUID, project_id: UUID | None = None,
                        title: str | None = None, model: str | None = None,
                        effort: str | None = None, context: int | None = None) -> Conversation:
    c = Conversation(user_id=user_id, project_id=project_id, title=(title or "New chat").strip()[:TITLE_MAX],
                     model=model, effort=effort, context=context, created_at=_now(), updated_at=_now())
    session.add(c)
    touch_project(session, project_id, commit=False)
    session.commit()
    return c


def move_conversation(session: Session, c: Conversation, project_id: UUID | None) -> None:
    """Move a chat (with its files and artifacts) into a project, another one, or out of projects."""
    c.project_id = project_id
    session.execute(update(Artifact).where(Artifact.conversation_id == c.id).values(
        project_id=project_id, index_status="pending" if project_id else "none"))
    touch_project(session, project_id, commit=False)
    session.commit()


def mark_conversation(session: Session, c: Conversation, pinned: bool | None = None,
                      archived: bool | None = None) -> None:
    """Pin or unpin, archive or unarchive. Archiving unpins: an archived chat is out of the lists."""
    if pinned is not None:
        c.pinned_at = _now() if pinned else None
    if archived is not None:
        c.archived_at = _now() if archived else None
        if archived:
            c.pinned_at = None
    session.commit()


def delete_conversation(session: Session, c: Conversation) -> list[str]:
    paths = list(session.execute(select(UserFile.path).where(UserFile.conversation_id == c.id)).scalars())
    for row in session.execute(select(UserFile).where(UserFile.conversation_id == c.id)).scalars():
        session.delete(row)
    for row in session.execute(select(ChatMessage).where(ChatMessage.conversation_id == c.id)).scalars():
        session.delete(row)
    for row in session.execute(select(ConversationMap).where(ConversationMap.conversation_id == c.id)).scalars():
        session.delete(row)
    session.execute(update(Artifact).where(Artifact.conversation_id == c.id).values(conversation_id=None))
    session.delete(c)
    session.commit()
    return paths


def message_dict(m: ChatMessage) -> dict:
    return {"id": str(m.id), "role": m.role, "content": m.content, "reasoning": m.reasoning,
            "reasoning_ms": m.reasoning_ms, "steps": m.steps or [], "sources": m.sources or [],
            "attachments": m.attachments or [], "artifacts": m.artifacts or [], "map_refs": m.map_refs or {},
            "model": m.model, "effort": m.effort,
            "status": m.status, "error": m.error, "input_tokens": m.input_tokens, "output_tokens": m.output_tokens,
            "stats": m.stats, "created_at": _iso(m.created_at)}


def messages_of(session: Session, conversation_id: UUID) -> list[ChatMessage]:
    return list(session.execute(select(ChatMessage).where(ChatMessage.conversation_id == conversation_id)
                                .order_by(ChatMessage.created_at, ChatMessage.role.desc())).scalars())


def add_message(session: Session, conversation: Conversation, role: str, content: str, **fields) -> ChatMessage:
    m = ChatMessage(conversation_id=conversation.id, role=role, content=content, created_at=_now(),
                    **{"steps": [], "sources": [], "attachments": [], "artifacts": []} | fields)
    session.add(m)
    conversation.updated_at = _now()
    touch_project(session, conversation.project_id, commit=False)
    session.commit()
    return m


# ── maps in chats ────────────────────────────────────────────────────


class MapError(ValueError):
    """A map that cannot be attached: not found, not built, or no letter left."""


def map_stats(session: Session, topic_ids: list[UUID]) -> dict[UUID, dict]:
    """Papers and milestones per map, for the lists."""
    if not topic_ids:
        return {}
    rows = session.execute(select(EvoTopicPaper.topic_id, func.count(), func.sum(
        func.cast(EvoTopicPaper.is_milestone_auto, Integer))).where(EvoTopicPaper.topic_id.in_(topic_ids))
        .group_by(EvoTopicPaper.topic_id)).all()
    return {t: {"papers": n, "milestones": int(m or 0)} for t, n, m in rows}


def chat_map_dict(cm: ConversationMap, t: EvoTopic, stats: dict | None = None) -> dict:
    return {"topic_id": str(t.id), "slug": t.slug, "name": t.name, "description": t.description,
            "share": cm.share, "key": cm.key, "built": t.built_at is not None, "built_at": _iso(t.built_at),
            "added_at": _iso(cm.added_at)} | (stats or {})


def chat_maps(session: Session, conversation_id: UUID) -> list[tuple[ConversationMap, EvoTopic]]:
    return list(session.execute(
        select(ConversationMap, EvoTopic).join(EvoTopic, EvoTopic.id == ConversationMap.topic_id)
        .where(ConversationMap.conversation_id == conversation_id).order_by(ConversationMap.added_at)).all())


def describe_chat_maps(session: Session, conversation_id: UUID) -> list[dict]:
    rows = chat_maps(session, conversation_id)
    stats = map_stats(session, [t.id for _, t in rows])
    return [chat_map_dict(cm, t, stats.get(t.id)) for cm, t in rows]


def find_map(session: Session, ident: str) -> EvoTopic | None:
    """A map by id or slug."""
    if _is_uuid(ident):
        return session.get(EvoTopic, UUID(str(ident)))
    return session.execute(select(EvoTopic).where(EvoTopic.slug == ident)).scalar_one_or_none()


def attach_maps(session: Session, c: Conversation, wanted: list[tuple[str, bool]]) -> list[ConversationMap]:
    """Attach built maps (id or slug, share) to a chat; one already there takes the new share. Each new map
    gets the first letter no map in the chat holds, so a removed map's letter can come back."""
    held = {cm.topic_id: cm for cm, _ in chat_maps(session, c.id)}
    used = {cm.key for cm in held.values()}
    out = []
    for ident, share in wanted:
        topic = find_map(session, ident)
        if topic is None:
            raise MapError("Map not found")
        if topic.built_at is None:
            raise MapError(f"The map {topic.name} is not built yet")
        if topic.id in held:
            held[topic.id].share = share
            out.append(held[topic.id])
            continue
        key = next((k for k in MAP_KEYS if k not in used), None)
        if key is None:
            raise MapError(f"A chat holds at most {len(MAP_KEYS)} maps")
        used.add(key)
        cm = ConversationMap(conversation_id=c.id, topic_id=topic.id, share=share, key=key, added_at=_now())
        session.add(cm)
        held[topic.id] = cm
        out.append(cm)
    c.updated_at = _now()
    session.commit()
    return out


def chat_map(session: Session, conversation_id: UUID, ident: str) -> ConversationMap | None:
    topic = find_map(session, ident)
    if topic is None:
        return None
    return session.execute(select(ConversationMap).where(ConversationMap.conversation_id == conversation_id,
                                                         ConversationMap.topic_id == topic.id)).scalar_one_or_none()


# ── files ────────────────────────────────────────────────────────────


def file_dict(f: UserFile) -> dict:
    return {"id": str(f.id), "filename": f.filename, "mime": f.mime, "kind": f.kind, "size": f.size,
            "pages": f.pages, "status": f.status, "error": f.error, "index_status": f.index_status,
            "chars": len(f.text or ""), "caption": f.caption, "detached": f.detached_at is not None,
            "project_id": str(f.project_id) if f.project_id else None,
            "conversation_id": str(f.conversation_id) if f.conversation_id else None,
            "created_at": _iso(f.created_at)}


def get_file(session: Session, user_id: UUID, file_id: UUID) -> UserFile | None:
    f = session.get(UserFile, file_id)
    return f if f is not None and f.user_id == user_id else None


def files_of(session: Session, project_id: UUID | None = None, conversation_id: UUID | None = None) -> list[UserFile]:
    stmt = select(UserFile)
    stmt = stmt.where(UserFile.project_id == project_id) if project_id else stmt.where(
        UserFile.conversation_id == conversation_id)
    return list(session.execute(stmt.order_by(UserFile.created_at.desc())).scalars())


# ── artifacts ────────────────────────────────────────────────────────


def artifact_dict(a: Artifact, content: bool = True) -> dict:
    out = {"id": str(a.id), "title": a.title, "version": a.version,
           "project_id": str(a.project_id) if a.project_id else None,
           "conversation_id": str(a.conversation_id) if a.conversation_id else None,
           "index_status": a.index_status, "created_at": _iso(a.created_at), "updated_at": _iso(a.updated_at),
           "chars": len(a.content or "")}
    return out | ({"content": a.content} if content else {})


def get_artifact(session: Session, user_id: UUID, artifact_id: UUID) -> Artifact | None:
    a = session.get(Artifact, artifact_id)
    return a if a is not None and a.user_id == user_id else None


def artifacts_of(session: Session, user_id: UUID, project_id: UUID | None = None,
                 conversation_id: UUID | None = None) -> list[Artifact]:
    stmt = select(Artifact).where(Artifact.user_id == user_id)
    if project_id is not None:
        stmt = stmt.where(Artifact.project_id == project_id)
    if conversation_id is not None:
        stmt = stmt.where(Artifact.conversation_id == conversation_id)
    return list(session.execute(stmt.order_by(Artifact.updated_at.desc())).scalars())


def create_artifact(session: Session, user_id: UUID, title: str, content: str, project_id: UUID | None = None,
                    conversation_id: UUID | None = None, author: str = "model",
                    message_id: UUID | None = None) -> Artifact:
    a = Artifact(user_id=user_id, project_id=project_id, conversation_id=conversation_id,
                 title=(title or "Untitled").strip()[:TITLE_MAX], content=content, version=1,
                 index_status="pending" if project_id else "none", created_at=_now(), updated_at=_now())
    session.add(a)
    session.flush()
    session.add(ArtifactVersion(artifact_id=a.id, version=1, title=a.title, content=content, author=author,
                                message_id=message_id, created_at=_now()))
    touch_project(session, project_id, commit=False)
    session.commit()
    return a


def revise_artifact(session: Session, a: Artifact, content: str | None = None, title: str | None = None,
                    author: str = "model", message_id: UUID | None = None) -> Artifact:
    """Save a new version; unchanged text and title save nothing."""
    content = a.content if content is None else content
    title = (title or a.title).strip()[:TITLE_MAX]
    if content == a.content and title == a.title:
        return a
    a.version += 1
    a.content, a.title, a.updated_at = content, title, _now()
    if a.project_id:
        a.index_status = "pending"
    session.add(ArtifactVersion(artifact_id=a.id, version=a.version, title=title, content=content, author=author,
                                message_id=message_id, created_at=_now()))
    touch_project(session, a.project_id, commit=False)
    session.commit()
    return a


def artifact_versions(session: Session, artifact_id: UUID) -> list[dict]:
    return [{"version": v.version, "title": v.title, "author": v.author, "chars": len(v.content or ""),
             "message_id": str(v.message_id) if v.message_id else None, "created_at": _iso(v.created_at)}
            for v in session.execute(select(ArtifactVersion).where(ArtifactVersion.artifact_id == artifact_id)
                                     .order_by(ArtifactVersion.version.desc())).scalars()]


def artifact_version(session: Session, artifact_id: UUID, version: int) -> ArtifactVersion | None:
    return session.execute(select(ArtifactVersion).where(ArtifactVersion.artifact_id == artifact_id,
                                                         ArtifactVersion.version == version)).scalar_one_or_none()


# ── what still needs indexing ────────────────────────────────────────


def pending_index(session: Session, project_id: UUID) -> tuple[list[ProjectItem], list[UserFile], list[Artifact]]:
    items = list(session.execute(select(ProjectItem).where(ProjectItem.project_id == project_id,
                                                           ProjectItem.index_status == "pending")).scalars())
    files = list(session.execute(select(UserFile).where(UserFile.project_id == project_id, UserFile.status == "ready",
                                                        UserFile.index_status == "pending")).scalars())
    arts = list(session.execute(select(Artifact).where(Artifact.project_id == project_id,
                                                       Artifact.index_status == "pending")).scalars())
    return items, files, arts
