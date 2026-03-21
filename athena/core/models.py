from datetime import datetime
from uuid import uuid4
from sqlalchemy import Column, String, DateTime, Integer, Float, Boolean, ARRAY, Enum as SQLEnum, ForeignKey
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB
from sqlalchemy.orm import declarative_base, relationship
import enum

Base = declarative_base()


class SummaryStatus(str, enum.Enum):
    PENDING = "pending"
    COMPLETE = "complete"
    FAILED = "failed"
    LAZY = "lazy"


class JobType(str, enum.Enum):
    ITEM_SUMMARY = "item_summary"
    CLUSTER_LABEL = "cluster_label"
    TRENDING_BRIEF = "trending_brief"


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
    authority_score = Column(Float, default=0.5)  # [0.0–1.0] source quality rating

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
    score_version = Column(Integer, nullable=True)  # FK → scoring_config.version
    scored_at = Column(DateTime(timezone=True), nullable=True)
    is_trending = Column(Boolean, default=False)
    category_rank = Column(Integer, nullable=True)
    embedding_id = Column(String, nullable=True)
    embedded_at = Column(DateTime(timezone=True), nullable=True)
    cluster_id = Column(PG_UUID(as_uuid=True), ForeignKey("clusters.id"), nullable=True)
    extra_data = Column(JSONB, default={})

    # Summarisation fields
    summary = Column(String, nullable=True)
    takeaways = Column(JSONB, nullable=True)
    summary_version = Column(Integer, nullable=True)  # FK -> prompt_versions.version (logical)
    summarised_at = Column(DateTime(timezone=True), nullable=True)
    summary_status = Column(SQLEnum(SummaryStatus), default=SummaryStatus.PENDING)

    source = relationship("Source", back_populates="content_items")
    cluster = relationship("Cluster", back_populates="content_items")


class FetchLog(Base):
    __tablename__ = "fetch_logs"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    source_id = Column(PG_UUID(as_uuid=True), ForeignKey("sources.id"), nullable=False)
    status = Column(String, nullable=False)  # 'success' or 'error'
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


class Cluster(Base):
    __tablename__ = "clusters"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    label = Column(String, nullable=True)
    summary = Column(String, nullable=True)
    centroid = Column(ARRAY(Float), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
    # metadata is a reserved keyword in some contexts, but let's stick to
    # metadata_ to be safe if needed, or just metadata
    metadata_ = Column("metadata", JSONB, default={})

    content_items = relationship("ContentItem", back_populates="cluster")


class ItemLink(Base):
    __tablename__ = "item_links"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    source_item_id = Column(PG_UUID(as_uuid=True), ForeignKey("content_items.id"), nullable=False)
    target_item_id = Column(PG_UUID(as_uuid=True), ForeignKey("content_items.id"), nullable=False)
    similarity_score = Column(Float, nullable=False)
    link_type = Column(String, nullable=False)  # 'nearest_neighbour', 'cross_cluster'
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class ContentScore(Base):
    """Per-item sub-score breakdown for scoring transparency."""
    __tablename__ = "content_scores"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    item_id = Column(PG_UUID(as_uuid=True), ForeignKey("content_items.id"), nullable=False)
    citation_score = Column(Float, default=0.0)
    engagement_score = Column(Float, default=0.5)
    sentiment_score = Column(Float, default=0.5)
    recency_score = Column(Float, default=0.5)
    authority_score = Column(Float, default=0.5)
    composite_score = Column(Float, default=0.0)
    score_version = Column(Integer, nullable=False)
    computed_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    metadata_ = Column("metadata", JSONB, default={})  # extra debug info

    content_item = relationship("ContentItem", backref="content_scores")


class ScoringConfig(Base):
    """Versioned weight profiles per content category."""
    __tablename__ = "scoring_config"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    version = Column(Integer, nullable=False, unique=True)
    category = Column(SQLEnum(ContentCategory), nullable=False)
    weight_citation = Column(Float, default=0.30)
    weight_engagement = Column(Float, default=0.15)
    weight_sentiment = Column(Float, default=0.15)
    weight_recency = Column(Float, default=0.20)
    weight_authority = Column(Float, default=0.20)
    half_life_days = Column(Integer, default=30)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    notes = Column(String, nullable=True)


class MetricSnapshot(Base):
    """Daily snapshot of citation_count + engagement per item for velocity computation."""
    __tablename__ = "metric_snapshots"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    item_id = Column(PG_UUID(as_uuid=True), ForeignKey("content_items.id"), nullable=False)
    citation_count = Column(Integer, default=0)
    engagement_raw = Column(Float, default=0.0)
    snapshot_date = Column(DateTime(timezone=True), default=datetime.utcnow)

    content_item = relationship("ContentItem", backref="metric_snapshots")


class PromptVersion(Base):
    """Versioning for LLM prompts used in summarisation."""
    __tablename__ = "prompt_versions"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    job_type = Column(SQLEnum(JobType), nullable=False)
    version = Column(Integer, nullable=False)
    system_prompt = Column(String, nullable=False)
    user_prompt_tpl = Column(String, nullable=False)
    is_active = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    notes = Column(String, nullable=True)


class SummaryUsageLog(Base):
    """Audit log for OpenAI LLM token usage and cost."""
    __tablename__ = "summary_usage_log"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    item_id = Column(PG_UUID(as_uuid=True), ForeignKey("content_items.id"), nullable=True)
    cluster_id = Column(PG_UUID(as_uuid=True), ForeignKey("clusters.id"), nullable=True)
    job_type = Column(SQLEnum(JobType), nullable=False)
    model = Column(String, nullable=False)
    prompt_version = Column(Integer, nullable=False)
    input_tokens = Column(Integer, default=0)
    output_tokens = Column(Integer, default=0)
    total_cost_usd = Column(Float, default=0.0)
    latency_ms = Column(Integer, default=0)
    success = Column(Boolean, default=True)
    error_message = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class TrendingBrief(Base):
    """Daily generated trend digest per category."""
    __tablename__ = "trending_briefs"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    category = Column(SQLEnum(ContentCategory), nullable=False)
    brief = Column(String, nullable=False)
    theme = Column(String, nullable=False)
    generated_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    prompt_version = Column(Integer, nullable=False)
    source_item_ids = Column(ARRAY(PG_UUID(as_uuid=True)), default=[])
