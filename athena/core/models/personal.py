"""
Per-user data: saved lists, read marks, notes, highlights, reactions, interest profiles, the inbox
and watches, and literature reviews.
"""
from uuid import uuid4
from sqlalchemy import (
    Column, String, DateTime, Integer, Float, Boolean, ARRAY, JSON,
    ForeignKey, Index, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB
from sqlalchemy.orm import relationship

from athena.core.models.base import Base


# ── Saved lists ───────────────────────────────────────────────────────


class SavedList(Base):
    """A user-created collection (e.g. 'NLP', 'Computer Vision') of content items."""
    __tablename__ = "saved_lists"
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_saved_list_user_name"),
    )

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    # Null only for lists from before accounts; the first admin account takes them over.
    user_id = Column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    name = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    items = relationship(
        "SavedListItem",
        back_populates="list",
        cascade="all, delete-orphan",
    )


class SavedListItem(Base):
    """Membership row linking a ContentItem to a SavedList."""
    __tablename__ = "saved_list_items"
    __table_args__ = (
        UniqueConstraint("list_id", "item_id", name="uq_saved_list_item"),
    )

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    list_id = Column(
        PG_UUID(as_uuid=True),
        ForeignKey("saved_lists.id", ondelete="CASCADE"),
        nullable=False,
    )
    item_id = Column(
        PG_UUID(as_uuid=True),
        ForeignKey("content_items.id", ondelete="CASCADE"),
        nullable=False,
    )
    added_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    list = relationship("SavedList", back_populates="items")
    content_item = relationship("ContentItem")


# ── Inbox and watches ─────────────────────────────────────────────────


class InboxEvent(Base):
    """Something to tell users about.

    Map events (a map changed, a new map is ready, new papers cite a map's milestones) are shared rows with no
    ``user_id``: everyone sees new maps, and a map's followers see the rest. Watch matches and digests belong to
    one user. Each user's read position is in ``InboxState``.
    """
    __tablename__ = "inbox_events"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    kind = Column(String, nullable=False)            # map_changes | map_new | feed_citations | watch_matches | digest
    title = Column(String, nullable=False)
    body = Column(String, nullable=True)
    link = Column(String, nullable=True)             # a path in the app
    topic_id = Column(PG_UUID(as_uuid=True), ForeignKey("evo_topics.id", ondelete="CASCADE"), nullable=True)
    user_id = Column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    payload = Column(JSONB, nullable=False, default={})
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)


class InboxState(Base):
    """Where a user has read the inbox up to."""
    __tablename__ = "inbox_state"

    user_id = Column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    last_seen_at = Column(DateTime(timezone=True), nullable=False)


class InboxSettings(Base):
    """A user's digest schedule and the shared kinds they muted. No row means the defaults."""
    __tablename__ = "inbox_settings"

    user_id = Column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    digest = Column(String, nullable=False, default="weekly")   # off | daily | weekly
    digest_day = Column(Integer, nullable=False, default=0)     # weekly digests: 0 = Monday ... 6 = Sunday
    muted_kinds = Column(JSONB, nullable=False, default=[])     # map_new | feed_citations
    last_digest_at = Column(DateTime(timezone=True), nullable=True)


class Watch(Base):
    """Something a user follows: a map, a search, a source or a cluster.

    ``target`` names it once per user (``map:<id>``, ``search:<query>``, ...). A search keeps its query's vector,
    and the embedding model that made it, so it can be compared with new feed items.
    """
    __tablename__ = "watches"
    __table_args__ = (UniqueConstraint("user_id", "target", name="uq_watch_user_target"),)

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id = Column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = Column(String, nullable=False)            # map | search | source | cluster
    target = Column(String, nullable=False)
    topic_id = Column(PG_UUID(as_uuid=True), ForeignKey("evo_topics.id", ondelete="CASCADE"), nullable=True)
    source_id = Column(PG_UUID(as_uuid=True), ForeignKey("sources.id", ondelete="CASCADE"), nullable=True)
    cluster_id = Column(PG_UUID(as_uuid=True), ForeignKey("clusters.id", ondelete="CASCADE"), nullable=True)
    query = Column(String, nullable=True)
    query_vector = Column(ARRAY(Float), nullable=True)
    embed_model = Column(String, nullable=True)
    delivery = Column(String, nullable=False, default="instant")  # instant (its own inbox entries) | digest
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    checked_at = Column(DateTime(timezone=True), nullable=True)


class WatchHit(Base):
    """A feed item a watch caught. Each item counts once per watch; the digest reads these."""
    __tablename__ = "watch_hits"
    __table_args__ = (UniqueConstraint("watch_id", "item_id", name="uq_watch_hit"),)

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    watch_id = Column(PG_UUID(as_uuid=True), ForeignKey("watches.id", ondelete="CASCADE"), nullable=False,
                      index=True)
    item_id = Column(PG_UUID(as_uuid=True), ForeignKey("content_items.id", ondelete="CASCADE"), nullable=False)
    similarity = Column(Float, nullable=True)        # searches only
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)


# ── Reading and personalisation ───────────────────────────────────────


class ItemRead(Base):
    """A feed item a user has marked as read. Map papers have their own (EvoReadingProgress); a feed item and the
    map paper it is stay in step (athena.database.personal)."""
    __tablename__ = "item_reads"

    user_id = Column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    item_id = Column(PG_UUID(as_uuid=True), ForeignKey("content_items.id", ondelete="CASCADE"), primary_key=True)
    read_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class UserNote(Base):
    """A user's own note on a feed item or a map paper. ``target`` names the paper once per user (``item:<id>`` or
    ``paper:<id>``); the foreign key that matches it removes the note with the paper."""
    __tablename__ = "user_notes"
    __table_args__ = (UniqueConstraint("user_id", "target", name="uq_user_note_target"),)

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id = Column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    target = Column(String, nullable=False)
    item_id = Column(PG_UUID(as_uuid=True), ForeignKey("content_items.id", ondelete="CASCADE"), nullable=True)
    paper_id = Column(PG_UUID(as_uuid=True), ForeignKey("evo_papers.id", ondelete="CASCADE"), nullable=True)
    body = Column(String, nullable=False, default="")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class UserHighlight(Base):
    """A passage a user marked in text the app shows: an abstract, a summary, a takeaway, or a passage an answer
    about a map cited. Kept as the quote with its offsets and a little text on either side, so it can be found
    again if the text around it changes; one that can't be found is still listed."""
    __tablename__ = "user_highlights"
    __table_args__ = (Index("ix_user_highlights_user_target", "user_id", "target"),)

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id = Column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    target = Column(String, nullable=False)          # item:<id> | paper:<id>
    item_id = Column(PG_UUID(as_uuid=True), ForeignKey("content_items.id", ondelete="CASCADE"), nullable=True)
    paper_id = Column(PG_UUID(as_uuid=True), ForeignKey("evo_papers.id", ondelete="CASCADE"), nullable=True)
    field = Column(String, nullable=False)           # abstract | summary | takeaway:<n> | passage
    quote = Column(String, nullable=False)
    start_offset = Column(Integer, nullable=True)    # where the quote was in the field's text
    end_offset = Column(Integer, nullable=True)
    prefix = Column(String, nullable=True)           # up to 32 characters before and after it
    suffix = Column(String, nullable=True)
    comment = Column(String, nullable=True)
    context = Column(JSONB, nullable=False, default={})  # passages: the map, section and chunk they came from
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ItemFeedback(Base):
    """A user's reaction to a feed item: up (more like this), down (less), or hide (not interested: also left out
    of their feed). One per item; a new reaction replaces the old one."""
    __tablename__ = "item_feedback"
    __table_args__ = (Index("ix_item_feedback_user_reaction", "user_id", "reaction"),)

    user_id = Column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    item_id = Column(PG_UUID(as_uuid=True), ForeignKey("content_items.id", ondelete="CASCADE"), primary_key=True)
    reaction = Column(String, nullable=False)        # up | down | hide
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class InterestProfile(Base):
    """What a user's reactions and saves say they like, as two vectors in the feed's embedding space: the mean of
    the items they liked or saved, and of those they marked down or hid (athena.pipeline.interests). Rebuilt
    whenever those change, and when the feed's embedding model does. No row: nothing learned yet, and on."""
    __tablename__ = "interest_profiles"

    user_id = Column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    enabled = Column(Boolean, nullable=False, default=True)   # "Personalise my feed"
    positive = Column(ARRAY(Float).with_variant(JSON(), "sqlite"), nullable=True)  # JSON in the SQLite tests
    negative = Column(ARRAY(Float).with_variant(JSON(), "sqlite"), nullable=True)
    n_positive = Column(Integer, nullable=False, default=0)
    n_negative = Column(Integer, nullable=False, default=0)
    embed_model = Column(String, nullable=True)      # the model that made the vectors; None: rebuild on next use
    updated_at = Column(DateTime(timezone=True), nullable=True)


# ── Writing ───────────────────────────────────────────────────────────


class LitReview(Base):
    """A literature review a user asked for (athena.evolution.review).

    ``map`` reviews are grounded in a built map: its eras, milestones, open problems and the papers' own text.
    ``abstracts`` reviews come from search results when no map matches. Written in the background section by
    section; ``sections`` and ``progress`` fill in as it goes, and ``sources`` holds the numbered references.
    """
    __tablename__ = "lit_reviews"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id = Column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    topic_id = Column(PG_UUID(as_uuid=True), ForeignKey("evo_topics.id", ondelete="SET NULL"), nullable=True)
    query = Column(String, nullable=True)
    title = Column(String, nullable=False)
    mode = Column(String, nullable=False)              # map | abstracts
    status = Column(String, nullable=False, default="queued")  # queued | running | done | failed
    progress = Column(JSONB, nullable=False, default={})       # {step, of, label, at}
    sections = Column(JSONB, nullable=False, default=[])       # [{key, title, level, markdown}]
    sources = Column(JSONB, nullable=False, default=[])        # [{n, title, year, authors, venue, doi, arxiv_id, url}]
    markdown = Column(String, nullable=True)
    error = Column(String, nullable=True)
    model = Column(String, nullable=True)
    input_tokens = Column(Integer, nullable=False, default=0)
    output_tokens = Column(Integer, nullable=False, default=0)
    built_at = Column(DateTime(timezone=True), nullable=True)  # the map build it was written from
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    finished_at = Column(DateTime(timezone=True), nullable=True)
