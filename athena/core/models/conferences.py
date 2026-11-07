"""
Conference proceedings (athena/conferences/): the ACL family's papers from the ACL Anthology, kept apart from the feed.

A volume is one book of proceedings (``2024.acl-long``, ``P18-1``) and may belong to more than one venue (COLING/ACL
2006, LREC-COLING 2024). Papers get a topic from a fixed, admin-editable list by their embedding, citation counts from
OpenAlex and Semantic Scholar, and their awards from the Anthology. Rising terms and a written summary are kept per
venue and year.
"""
from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID

from athena.core.models.base import Base


class ConfVolume(Base):
    __tablename__ = "conf_volumes"

    id = Column(String, primary_key=True)                 # the Anthology's volume id: 2024.acl-long, P18-1
    year = Column(Integer, nullable=False, index=True)
    kind = Column(String, nullable=False)                 # main | findings | journal
    title = Column(String, nullable=False)
    paper_count = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ConfVolumeVenue(Base):
    """Which venues a volume counts for: one row each, so a joint event counts for both."""
    __tablename__ = "conf_volume_venues"

    volume_id = Column(String, ForeignKey("conf_volumes.id", ondelete="CASCADE"), primary_key=True)
    venue = Column(String, primary_key=True, index=True)  # athena.conferences.venues.VENUES


class ConfTopic(Base):
    """One area of the fixed topic list. Papers go to the topic whose ``vector`` (name and description, embedded as a
    query) is nearest theirs."""
    __tablename__ = "conf_topics"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False, unique=True)
    description = Column(String, nullable=False, default="")
    position = Column(Integer, nullable=False, default=0)
    vector = Column(JSONB, nullable=True)                 # EMBED_DIM floats; None until embedded or after an edit
    vector_model = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ConfPaper(Base):
    __tablename__ = "conf_papers"

    id = Column(String, primary_key=True)                 # the Anthology id: 2024.acl-long.1, P18-1031
    volume_id = Column(String, ForeignKey("conf_volumes.id", ondelete="CASCADE"), nullable=False, index=True)
    year = Column(Integer, nullable=False, index=True)
    title = Column(String, nullable=False)
    abstract = Column(String, nullable=True)
    # anthology | openalex | semantic_scholar: before about 2015 the Anthology has almost no abstracts
    abstract_from = Column(String, nullable=True)
    authors = Column(JSONB, nullable=False, default=list)  # ["First Last", …]
    doi = Column(String, nullable=True)
    awards = Column(JSONB, nullable=False, default=list)   # ["Best Paper Award", …] as the Anthology names them
    award_rank = Column(Integer, nullable=True, index=True)  # 0 best paper, 1 outstanding, 2 any other award
    citation_count = Column(Integer, nullable=True)
    citations_at = Column(DateTime(timezone=True), nullable=True)
    topic_id = Column(Integer, ForeignKey("conf_topics.id", ondelete="SET NULL"), nullable=True, index=True)
    topic_score = Column(Float, nullable=True)            # cosine to the topic: how sure the match is
    embedded_at = Column(DateTime(timezone=True), nullable=True)
    embed_model = Column(String, nullable=True)
    # The feed item made when someone saved it or added it to a project
    item_id = Column(PG_UUID(as_uuid=True), ForeignKey("content_items.id", ondelete="SET NULL"), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ConfTerm(Base):
    """A phrase that rose (or fell) most at a venue's edition against its previous one; venue ``all`` is the
    whole family's year."""
    __tablename__ = "conf_terms"

    venue = Column(String, primary_key=True)
    year = Column(Integer, primary_key=True)
    term = Column(String, primary_key=True)
    papers = Column(Integer, nullable=False)              # papers using it this edition
    share = Column(Float, nullable=False)                 # of the edition's papers
    prev_share = Column(Float, nullable=False)            # of the previous edition's
    score = Column(Float, nullable=False)                 # z-score of the log-odds ratio; negative: fell


class ConfSummary(Base):
    """What a venue's edition was about, written by the chat model from its numbers."""
    __tablename__ = "conf_summaries"

    venue = Column(String, primary_key=True)
    year = Column(Integer, primary_key=True)
    text = Column(String, nullable=False)
    stats_hash = Column(String, nullable=False)           # the numbers it was written from; others → rewrite
    model = Column(String, nullable=True)
    written_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
