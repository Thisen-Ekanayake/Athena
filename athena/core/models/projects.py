"""
Projects and chats, per user: a project gathers papers, maps, reviews, idea checks, saved lists, uploaded files,
chats and artifacts (documents the model writes), with instructions sent to every chat in it. Chats can also stand
alone and move into a project later (athena.projects).
"""
from uuid import uuid4
from sqlalchemy import Column, String, DateTime, Integer, ForeignKey, Index, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB

from athena.core.models.base import Base


class Project(Base):
    """A user's workspace. ``instructions`` go into the system prompt of every chat in it."""
    __tablename__ = "projects"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id = Column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String, nullable=False)
    description = Column(String, nullable=False, default="")
    instructions = Column(String, nullable=False, default="")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ProjectItem(Base):
    """Something of Athena's in a project: a paper, map, literature review, idea check or saved list.

    ``ref`` names it once per project (``item:<id>``, ``paper:<id>``, ``map:<id>``, ``review:<id>``, ``idea:<id>``,
    ``list:<id>``, or ``ext:<doi|arxiv|url>`` for a paper found by search that is not in Athena); the foreign key
    that matches it removes the row with the thing. External papers keep their title, abstract and link in
    ``meta``. ``index_status`` follows its passages into Qdrant's ``project_chunks``.
    """
    __tablename__ = "project_items"
    __table_args__ = (UniqueConstraint("project_id", "ref", name="uq_project_item_ref"),)

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id = Column(PG_UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False,
                        index=True)
    kind = Column(String, nullable=False)            # paper | map | review | idea_check | list
    ref = Column(String, nullable=False)
    item_id = Column(PG_UUID(as_uuid=True), ForeignKey("content_items.id", ondelete="CASCADE"), nullable=True)
    paper_id = Column(PG_UUID(as_uuid=True), ForeignKey("evo_papers.id", ondelete="CASCADE"), nullable=True)
    topic_id = Column(PG_UUID(as_uuid=True), ForeignKey("evo_topics.id", ondelete="CASCADE"), nullable=True)
    review_id = Column(PG_UUID(as_uuid=True), ForeignKey("lit_reviews.id", ondelete="CASCADE"), nullable=True)
    idea_check_id = Column(PG_UUID(as_uuid=True), ForeignKey("evo_idea_checks.id", ondelete="CASCADE"),
                           nullable=True)
    list_id = Column(PG_UUID(as_uuid=True), ForeignKey("saved_lists.id", ondelete="CASCADE"), nullable=True)
    meta = Column(JSONB, nullable=False, default={})
    index_status = Column(String, nullable=False, default="pending")  # pending | indexed | failed
    index_error = Column(String, nullable=True)
    added_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Conversation(Base):
    """A chat. ``model``, ``effort`` and ``context`` are the last ones used, which the next message starts from. A
    pinned chat lists first; an archived one leaves the lists until it is unarchived."""
    __tablename__ = "conversations"
    __table_args__ = (Index("ix_conversations_user_updated", "user_id", "updated_at"),)

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id = Column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    project_id = Column(PG_UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True,
                        index=True)
    title = Column(String, nullable=False, default="New chat")
    model = Column(String, nullable=True)
    effort = Column(String, nullable=True)           # off | low | medium | high
    context = Column(Integer, nullable=True)         # the context size picked (tokens); the model's default when unset
    pinned_at = Column(DateTime(timezone=True), nullable=True)
    archived_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ChatMessage(Base):
    """One turn. An assistant turn keeps its thinking, the tool calls it made (``steps``), the passages it was
    given (``sources``, cited as [n]) and the artifacts it wrote; a user turn keeps its attached files."""
    __tablename__ = "chat_messages"
    __table_args__ = (Index("ix_chat_messages_conversation_created", "conversation_id", "created_at"),)

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    conversation_id = Column(PG_UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"),
                             nullable=False)
    role = Column(String, nullable=False)            # user | assistant
    content = Column(String, nullable=False, default="")
    reasoning = Column(String, nullable=True)
    reasoning_ms = Column(Integer, nullable=True)
    steps = Column(JSONB, nullable=False, default=[])        # [{tool, args, summary, ok}]
    sources = Column(JSONB, nullable=False, default=[])      # [{n, kind, ref, title, excerpt, ...}]
    attachments = Column(JSONB, nullable=False, default=[])  # [{id, filename, kind}]
    artifacts = Column(JSONB, nullable=False, default=[])    # [{id, title, version}]
    model = Column(String, nullable=True)
    effort = Column(String, nullable=True)
    status = Column(String, nullable=False, default="done")  # done | stopped | failed
    error = Column(String, nullable=True)
    input_tokens = Column(Integer, nullable=False, default=0)
    output_tokens = Column(Integer, nullable=False, default=0)
    # How the answer ran: {tps, prompt_tps, ttft_ms, load_ms, device, gpu_layers, layers, context}
    stats = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class UserFile(Base):
    """A file a user uploaded: into a project's knowledge (``project_id``) or onto a chat message
    (``conversation_id``). PDFs and text files keep their text; images keep a caption for project search and go to
    the vision model as they are. The bytes are under ATHENA_UPLOADS_DIR at ``path``."""
    __tablename__ = "user_files"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id = Column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(PG_UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True,
                        index=True)
    conversation_id = Column(PG_UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"),
                             nullable=True, index=True)
    filename = Column(String, nullable=False)
    mime = Column(String, nullable=False)
    kind = Column(String, nullable=False)            # pdf | text | image
    size = Column(Integer, nullable=False, default=0)
    path = Column(String, nullable=False)
    text = Column(String, nullable=True)
    caption = Column(String, nullable=True)
    pages = Column(Integer, nullable=True)
    status = Column(String, nullable=False, default="pending")       # pending | ready | failed
    error = Column(String, nullable=True)
    index_status = Column(String, nullable=False, default="pending")  # pending | indexed | failed | none
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Artifact(Base):
    """A Markdown document the model wrote in a chat, or the user did, kept with every version."""
    __tablename__ = "artifacts"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id = Column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(PG_UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True,
                        index=True)
    conversation_id = Column(PG_UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="SET NULL"),
                             nullable=True, index=True)
    title = Column(String, nullable=False)
    content = Column(String, nullable=False, default="")
    version = Column(Integer, nullable=False, default=1)
    index_status = Column(String, nullable=False, default="pending")  # pending | indexed | failed | none
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ArtifactVersion(Base):
    """One saved state of an artifact. ``author`` is model or user; ``message_id`` the turn that wrote it."""
    __tablename__ = "artifact_versions"
    __table_args__ = (UniqueConstraint("artifact_id", "version", name="uq_artifact_version"),)

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    artifact_id = Column(PG_UUID(as_uuid=True), ForeignKey("artifacts.id", ondelete="CASCADE"), nullable=False)
    version = Column(Integer, nullable=False)
    title = Column(String, nullable=False)
    content = Column(String, nullable=False, default="")
    author = Column(String, nullable=False, default="model")  # model | user
    message_id = Column(PG_UUID(as_uuid=True), ForeignKey("chat_messages.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
