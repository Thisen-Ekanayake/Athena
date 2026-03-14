from datetime import datetime
from typing import List, Optional
from uuid import UUID, uuid4
from sqlalchemy import Column, String, DateTime, Integer, Float, Boolean, ARRAY, Enum as SQLEnum, ForeignKey, JSON
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB
from sqlalchemy.orm import declarative_base, relationship
import enum

Base = declarative_base()

class SourceType(str, enum.Enum):
    API = "api"
    RSS = "rss"
    SCRAPE = "scrape"

class SourceCategory(str, enum.Enum):
    PAPER = "paper"
    COMPANY = "company"
    BLOG = "blog"

class ContentCategory(str, enum.Enum):
    PAPER = "paper"
    COMPANY_BLOG = "company_blog"
    COMMUNITY_BLOG = "community_blog"

class Source(Base):
    __tablename__ = "sources"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(String, nullable=False)
    url = Column(String, unique=True, nullable=False)
    type = Column(SQLEnum(SourceType), nullable=False)
    category = Column(SQLEnum(SourceCategory), nullable=False)
    fetch_config = Column(JSONB, default={})
    last_fetched_at = Column(DateTime(timezone=True), nullable=True)
    is_active = Column(Boolean, default=True)
    added_by = Column(String, default="system")
    consecutive_failures = Column(Integer, default=0)

    content_items = relationship("ContentItem", back_populates="source")
    fetch_logs = relationship("FetchLog", back_populates="source")

class ContentItem(Base):
    __tablename__ = "content_items"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    source_id = Column(PG_UUID(as_uuid=True), ForeignKey("sources.id"), nullable=False)
    title = Column(String, nullable=False)
    url = Column(String, unique=True, nullable=False)
    published_at = Column(DateTime(timezone=True), nullable=False)
    fetched_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    authors = Column(ARRAY(String), default=[])
    abstract = Column(String, nullable=True)
    full_text_path = Column(String, nullable=True)
    citation_count = Column(Integer, default=0)
    category = Column(SQLEnum(ContentCategory), nullable=False)
    content_hash = Column(String, index=True, unique=True)
    score = Column(Float, default=0.0)
    cluster_id = Column(PG_UUID(as_uuid=True), nullable=True)
    extra_data = Column(JSONB, default={})

    source = relationship("Source", back_populates="content_items")

class FetchLog(Base):
    __tablename__ = "fetch_logs"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    source_id = Column(PG_UUID(as_uuid=True), ForeignKey("sources.id"), nullable=False)
    status = Column(String, nullable=False) # 'success' or 'error'
    error_message = Column(String, nullable=True)
    duration_ms = Column(Float, nullable=False)
    items_fetched = Column(Integer, default=0)  # number of new items saved this run
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    source = relationship("Source", back_populates="fetch_logs")

class QuarantineItem(Base):
    """Holds raw items that failed Pydantic schema validation for later inspection."""
    __tablename__ = "quarantine_items"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    source_id = Column(PG_UUID(as_uuid=True), ForeignKey("sources.id"), nullable=False)
    raw_data = Column(JSONB, nullable=True)  # serialized raw item that failed parsing
    error_message = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
