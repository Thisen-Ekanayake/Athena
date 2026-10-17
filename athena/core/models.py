from datetime import datetime
from uuid import uuid4
from sqlalchemy import (
    Column, String, DateTime, Integer, Float, Boolean, ARRAY, JSON,
    Enum as SQLEnum, ForeignKey, Index, UniqueConstraint, func,
)
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
    QA = "qa"


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
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

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
    authors = Column(ARRAY(String).with_variant(JSON(), "sqlite"), default=[])  # JSON in the SQLite tests
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
    # Citations gained over the last 7 and 30 days, from metric snapshots (athena.pipeline.momentum); papers only
    citation_gain_7d = Column(Integer, nullable=True)
    citation_gain_30d = Column(Integer, nullable=True)
    embedding_id = Column(String, nullable=True)
    embedding_model = Column(String, nullable=True)  # the EMBED_MODEL that made the vector
    embedded_at = Column(DateTime(timezone=True), nullable=True)
    cluster_id = Column(PG_UUID(as_uuid=True), ForeignKey("clusters.id"), nullable=True)
    cluster_distance = Column(Float, nullable=True)  # distance to cluster centroid
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
    weight_recency = Column(Float, default=0.20)
    weight_authority = Column(Float, default=0.20)
    # The "For you" order's share for a user's interests (athena.pipeline.interests); the four above sum to 1
    weight_preference = Column(Float, default=0.30)
    half_life_days = Column(Integer, default=30)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    notes = Column(String, nullable=True)


class MetricSnapshot(Base):
    """An item's citation count and raw engagement on one day, for velocity and the momentum charts.

    ``daily`` rows are taken once a day (athena.pipeline.momentum); ``rebuilt`` rows are a paper's past, rebuilt
    once from the dates of the papers citing it, one row per day the count changed.
    """
    __tablename__ = "metric_snapshots"
    __table_args__ = (Index("ix_metric_snapshots_item_date", "item_id", "snapshot_date"),)

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    item_id = Column(PG_UUID(as_uuid=True), ForeignKey("content_items.id"), nullable=False)
    citation_count = Column(Integer, default=0)
    engagement_raw = Column(Float, default=0.0)
    snapshot_date = Column(DateTime(timezone=True), default=datetime.utcnow)
    source = Column(String, nullable=False, default="daily", server_default="daily")  # daily | rebuilt

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


class QAFetchCache(Base):
    """Caches fetch status and metadata for Q&A features."""
    __tablename__ = "qa_fetch_cache"

    item_id = Column(PG_UUID(as_uuid=True), ForeignKey("content_items.id"), primary_key=True)
    fetch_method = Column(String, nullable=False)  # staged | http | playwright | pdf | abstract_only
    word_count = Column(Integer, default=0)
    is_partial = Column(Boolean, default=False)
    last_fetched_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    fetch_latency_ms = Column(Integer, default=0)

    content_item = relationship("ContentItem", backref="qa_fetch_cache")


class QAUsageLog(Base):
    """Audit log for Q&A feature token usage and session history."""
    __tablename__ = "qa_usage_log"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    item_id = Column(PG_UUID(as_uuid=True), ForeignKey("content_items.id"), nullable=False)
    user_id = Column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    session_id = Column(String, nullable=False)
    turn_number = Column(Integer, nullable=False)
    question_length = Column(Integer, default=0)
    fetch_method = Column(String, nullable=False)
    fetch_latency_ms = Column(Integer, default=0)
    article_tokens = Column(Integer, default=0)
    history_tokens = Column(Integer, default=0)
    answer_tokens = Column(Integer, default=0)
    total_cost_usd = Column(Float, default=0.0)
    model = Column(String, nullable=False)
    partial_content = Column(Boolean, default=False)
    success = Column(Boolean, default=True)
    error_type = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    content_item = relationship("ContentItem", backref="qa_usage_logs")


class ClusterRunLog(Base):
    """Audit log for clustering pipeline runs."""
    __tablename__ = "cluster_run_logs"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    started_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    total_items = Column(Integer, default=0)
    num_clusters = Column(Integer, default=0)
    noise_items = Column(Integer, default=0)
    new_clusters = Column(Integer, default=0)
    merged_clusters = Column(Integer, default=0)
    deactivated_clusters = Column(Integer, default=0)
    umap_dims = Column(Integer, default=50)
    hdbscan_min_cluster_size = Column(Integer, default=5)
    status = Column(String, default="running")  # running, success, failed
    error_message = Column(String, nullable=True)


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


class AppSetting(Base):
    """User-configurable key/value settings persisted in the database."""
    __tablename__ = "app_settings"

    key = Column(String, primary_key=True)
    value = Column(String, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)


# ── Accounts ─────────────────────────────────────────────────────────


class User(Base):
    """An account. The first one is the admin; the admin creates the rest (there is no public sign-up)."""
    __tablename__ = "users"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    email = Column(String, unique=True, nullable=False)  # stored lower-case
    display_name = Column(String, nullable=False)
    password_hash = Column(String, nullable=False)       # argon2id
    role = Column(String, nullable=False, default="user")  # admin | user
    is_active = Column(Boolean, nullable=False, default=True)
    must_change_password = Column(Boolean, nullable=False, default=False)  # set by temporary passwords
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_login_at = Column(DateTime(timezone=True), nullable=True)
    onboarded_at = Column(DateTime(timezone=True), nullable=True)  # finished or skipped the setup guide


class UserSession(Base):
    """A login. The browser holds the token in an httpOnly cookie; only its SHA-256 is stored."""
    __tablename__ = "user_sessions"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id = Column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = Column(String, unique=True, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=False)  # rolling: pushed back while the session is used
    last_seen_at = Column(DateTime(timezone=True), nullable=True)
    user_agent = Column(String, nullable=True)

    user = relationship("User")


# ── Research evolution ───────────────────────────────────────────────
# Papers here are a separate corpus from content_items: they come from
# OpenAlex, are grouped into curated topics, and never enter the feed.


class EvoTopic(Base):
    """A research topic whose evolution graph is built ahead of time (curated) or from a search."""
    __tablename__ = "evo_topics"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    slug = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=False)
    aliases = Column(ARRAY(String), default=[])
    description = Column(String, nullable=True)
    seeds = Column(JSONB, default=[])   # [{openalex_id, title, year, arxiv_id}] anchors, hand-picked or proposed
    config = Column(JSONB, default={})  # corpus limits and milestone weights; see athena.evolution.config
    # pending | building | refining (graph viewable, abstracts being embedded) | ready | failed
    status = Column(String, default="pending")
    status_detail = Column(String, nullable=True)
    built_at = Column(DateTime(timezone=True), nullable=True)
    origin = Column(String, nullable=False, server_default="curated")  # curated | search
    query = Column(String, nullable=True)            # the search a search-built topic came from
    build_stats = Column(JSONB, nullable=True)       # the last build's summary (corpus, Semantic Scholar, timing)
    # Who built a search-built topic; curated topics have none. Maps are shared with every user.
    created_by = Column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    topic_papers = relationship("EvoTopicPaper", back_populates="topic", cascade="all, delete-orphan")


class EvoPaper(Base):
    """One paper (an OpenAlex work), shared across topics."""
    __tablename__ = "evo_papers"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    openalex_id = Column(String, unique=True, nullable=False)  # short form, e.g. "W2626778328"
    doi = Column(String, nullable=True, index=True)
    arxiv_id = Column(String, nullable=True, index=True)
    title = Column(String, nullable=False)
    abstract = Column(String, nullable=True)
    year = Column(Integer, nullable=True)            # repaired first-appearance year
    year_source = Column(String, nullable=True)      # seed | arxiv | citers | openalex
    openalex_year = Column(Integer, nullable=True)   # as reported, kept for auditing the repair
    venue = Column(String, nullable=True)
    work_type = Column(String, nullable=True)
    authors = Column(JSONB, default=[])
    # [{id, name, institutions: [{id, name, country}]}] from OpenAlex, for the people view; ``authors`` keeps names
    authorships = Column(JSONB, default=[])
    cited_by_count = Column(Integer, default=0)      # OpenAlex's count
    s2_paper_id = Column(String, nullable=True, index=True)  # Semantic Scholar paperId
    s2_cited_by_count = Column(Integer, nullable=True)       # often far higher for ML preprints
    primary_topic = Column(String, nullable=True)
    is_oa = Column(Boolean, default=False)
    oa_pdf_url = Column(String, nullable=True)
    full_text_status = Column(String, default="unavailable")  # unavailable | available | parsed | failed
    abstract_embedded_at = Column(DateTime(timezone=True), nullable=True)  # Tier 1: in Qdrant's paper_abstracts
    merged_ids = Column(ARRAY(String), default=[])   # duplicate OpenAlex records folded into this one
    content_item_id = Column(PG_UUID(as_uuid=True), ForeignKey("content_items.id"), nullable=True)
    # The name citing papers give it, read from Semantic Scholar's citing sentences ({name, users, citers,
    # fetched_at}; name is null when none stands out). A milestone-score feature: see athena.evolution.method_names.
    cited_name = Column(JSONB, nullable=True)
    extra = Column(JSONB, default={})
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)


class EvoCitation(Base):
    """citing_id cites cited_id. Only edges between papers in some topic corpus are stored."""
    __tablename__ = "evo_citations"
    __table_args__ = (
        UniqueConstraint("citing_id", "cited_id", name="uq_evo_citation"),
    )

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    citing_id = Column(PG_UUID(as_uuid=True), ForeignKey("evo_papers.id", ondelete="CASCADE"),
                       nullable=False, index=True)
    cited_id = Column(PG_UUID(as_uuid=True), ForeignKey("evo_papers.id", ondelete="CASCADE"),
                      nullable=False, index=True)
    source = Column(String, default="openalex")  # openalex | grobid | s2


class EvoTopicPaper(Base):
    """A paper's place in one topic: graph scores and milestone status."""
    __tablename__ = "evo_topic_papers"
    __table_args__ = (
        UniqueConstraint("topic_id", "paper_id", name="uq_evo_topic_paper"),
    )

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    topic_id = Column(PG_UUID(as_uuid=True), ForeignKey("evo_topics.id", ondelete="CASCADE"), nullable=False)
    paper_id = Column(PG_UUID(as_uuid=True), ForeignKey("evo_papers.id", ondelete="CASCADE"), nullable=False)
    role = Column(String, default="core")       # seed | core
    kind = Column(String, default="method")     # method | survey | dataset | benchmark
    in_degree = Column(Integer, default=0)      # citations from inside the topic
    out_degree = Column(Integer, default=0)
    pagerank = Column(Float, default=0.0)
    citation_percentile = Column(Float, default=0.0)  # citations relative to topic papers from nearby years, 0-1
    specificity = Column(Float, default=0.0)    # share of the paper's citations that come from this topic
    on_main_path = Column(Boolean, default=False)
    named_method = Column(String, nullable=True)
    milestone_score = Column(Float, default=0.0)
    is_milestone_auto = Column(Boolean, default=False)
    score_detail = Column(JSONB, default={})

    topic = relationship("EvoTopic", back_populates="topic_papers")
    paper = relationship("EvoPaper")


class EvoMainPathEdge(Base):
    """An edge on a topic's main path, with its search path count (SPC) weight."""
    __tablename__ = "evo_main_path_edges"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    topic_id = Column(PG_UUID(as_uuid=True), ForeignKey("evo_topics.id", ondelete="CASCADE"), nullable=False)
    citing_id = Column(PG_UUID(as_uuid=True), ForeignKey("evo_papers.id", ondelete="CASCADE"), nullable=False)
    cited_id = Column(PG_UUID(as_uuid=True), ForeignKey("evo_papers.id", ondelete="CASCADE"), nullable=False)
    spc_weight = Column(Float, nullable=False)


class EvoMilestoneOverride(Base):
    """A person's pin or unpin of a milestone. Applied at read time, so rebuilds never undo it."""
    __tablename__ = "evo_milestone_overrides"
    __table_args__ = (
        UniqueConstraint("topic_id", "paper_id", name="uq_evo_milestone_override"),
    )

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    topic_id = Column(PG_UUID(as_uuid=True), ForeignKey("evo_topics.id", ondelete="CASCADE"), nullable=False)
    paper_id = Column(PG_UUID(as_uuid=True), ForeignKey("evo_papers.id", ondelete="CASCADE"), nullable=False)
    action = Column(String, nullable=False)  # pin | unpin
    note = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class EvoSection(Base):
    """A section of a Tier 2 paper's full text, parsed by GROBID."""
    __tablename__ = "evo_sections"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    paper_id = Column(PG_UUID(as_uuid=True), ForeignKey("evo_papers.id", ondelete="CASCADE"),
                      nullable=False, index=True)
    position = Column(Integer, nullable=False)       # order in the paper; the abstract comes first
    heading = Column(String, nullable=False)
    number = Column(String, nullable=True)           # "3.2", as GROBID read it
    section_type = Column(String, nullable=False)    # see athena.evolution.tei.SECTION_TYPES
    rule_type = Column(String, nullable=True)        # the heading rule's answer before inheritance
    n_sentences = Column(Integer, default=0)


class EvoChunk(Base):
    """About 300 words of one section. The id doubles as the point id in Qdrant's paper_chunks."""
    __tablename__ = "evo_chunks"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    paper_id = Column(PG_UUID(as_uuid=True), ForeignKey("evo_papers.id", ondelete="CASCADE"),
                      nullable=False, index=True)
    section_id = Column(PG_UUID(as_uuid=True), ForeignKey("evo_sections.id", ondelete="CASCADE"), nullable=False)
    position = Column(Integer, nullable=False)       # order within the paper
    section_type = Column(String, nullable=False)
    text = Column(String, nullable=False)            # without the title and heading prefix added for embedding
    n_words = Column(Integer, default=0)
    embedded_at = Column(DateTime(timezone=True), nullable=True)  # null: waiting for the GPU lane


class EvoCitationContext(Base):
    """A sentence in which citing_id cites cited_id, and what the classifier said about it.

    A strict gap -> resolution link is a context whose label states a limitation of the cited
    paper (addresses_limitation or criticises) and whose problem is attributed to the cited
    paper's own method (``attributed``).
    """
    __tablename__ = "evo_citation_contexts"
    __table_args__ = (
        UniqueConstraint("citing_id", "cited_id", "sentence_hash", name="uq_evo_citation_context"),
    )

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    citing_id = Column(PG_UUID(as_uuid=True), ForeignKey("evo_papers.id", ondelete="CASCADE"),
                       nullable=False, index=True)
    cited_id = Column(PG_UUID(as_uuid=True), ForeignKey("evo_papers.id", ondelete="CASCADE"),
                      nullable=False, index=True)
    source = Column(String, nullable=False)          # grobid | s2
    section_type = Column(String, nullable=True)     # unknown for Semantic Scholar contexts
    sentence = Column(String, nullable=False)
    sentence_hash = Column(String, nullable=False)
    marked = Column(String, nullable=True)           # the sentence with the cited paper's markers in [[ ]]
    mention = Column(String, nullable=True)          # the word right before the citation marker ("LoRA")
    cues = Column(JSONB, default=[])                 # contrast and limitation cue words in the sentence
    s2_intents = Column(JSONB, default=[])
    label = Column(String, nullable=True)            # Task B label; null until classified
    attributed = Column(Boolean, nullable=True)      # asked only for limitation labels
    model = Column(String, nullable=True)
    labelled_at = Column(DateTime(timezone=True), nullable=True)


class EvoGapStatement(Base):
    """A sentence stating a research gap: a paper's own limitation, or a later paper stating one of it.

    ``paper_id`` is the paper the gap belongs to; ``source_paper_id`` the paper whose text states it.
    Own statements (origin "own") are candidates until the 9B labels them; statements from strict
    links (origin "citing") are gaps by construction.
    """
    __tablename__ = "evo_gap_statements"
    __table_args__ = (
        UniqueConstraint("source_paper_id", "paper_id", "sentence_hash", name="uq_evo_gap_statement"),
    )

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    paper_id = Column(PG_UUID(as_uuid=True), ForeignKey("evo_papers.id", ondelete="CASCADE"),
                      nullable=False, index=True)
    source_paper_id = Column(PG_UUID(as_uuid=True), ForeignKey("evo_papers.id", ondelete="CASCADE"),
                             nullable=False, index=True)
    origin = Column(String, nullable=False)          # own | citing
    context_id = Column(PG_UUID(as_uuid=True), ForeignKey("evo_citation_contexts.id", ondelete="CASCADE"),
                        nullable=True)
    section_type = Column(String, nullable=True)
    sentence = Column(String, nullable=False)
    sentence_hash = Column(String, nullable=False)
    label = Column(String, nullable=True)            # gap | not_gap; null until classified
    model = Column(String, nullable=True)
    labelled_at = Column(DateTime(timezone=True), nullable=True)
    embedded_at = Column(DateTime(timezone=True), nullable=True)      # vector in Qdrant's gap_statements
    loose_checked_at = Column(DateTime(timezone=True), nullable=True)  # loose links searched
    cross_checked_at = Column(DateTime(timezone=True), nullable=True)  # other maps' papers searched (E7)


class EvoGapTheme(Base):
    """A cluster of one topic's gap statements, with how often it was stated each year."""
    __tablename__ = "evo_gap_themes"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    topic_id = Column(PG_UUID(as_uuid=True), ForeignKey("evo_topics.id", ondelete="CASCADE"),
                      nullable=False, index=True)
    label = Column(String, nullable=False)           # distinctive terms of its statements
    size = Column(Integer, nullable=False)
    yearly = Column(JSONB, default={})               # {"2021": 3, ...}, by the year the stating paper appeared
    first_year = Column(Integer, nullable=True)
    last_year = Column(Integer, nullable=True)
    status = Column(String, nullable=False)          # persisting | new | addressed | quiet
    detail = Column(JSONB, default={})               # papers, fixes, counts by origin
    built_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class EvoGapThemeMember(Base):
    __tablename__ = "evo_gap_theme_members"

    theme_id = Column(PG_UUID(as_uuid=True), ForeignKey("evo_gap_themes.id", ondelete="CASCADE"), primary_key=True)
    gap_id = Column(PG_UUID(as_uuid=True), ForeignKey("evo_gap_statements.id", ondelete="CASCADE"),
                    primary_key=True, index=True)


class EvoLooseLink(Base):
    """A later paper whose text matches an earlier paper's gap, with no citation needed. Shown dashed, on request.

    ``chunk_id`` is not a foreign key: chunk IDs survive re-parsing, and a link to a chunk that is gone
    simply drops out of reads.
    """
    __tablename__ = "evo_loose_links"
    __table_args__ = (
        UniqueConstraint("gap_id", "paper_id", name="uq_evo_loose_link"),
    )

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    gap_id = Column(PG_UUID(as_uuid=True), ForeignKey("evo_gap_statements.id", ondelete="CASCADE"),
                    nullable=False, index=True)
    paper_id = Column(PG_UUID(as_uuid=True), ForeignKey("evo_papers.id", ondelete="CASCADE"),
                      nullable=False, index=True)
    chunk_id = Column(PG_UUID(as_uuid=True), nullable=False)
    score = Column(Float, nullable=False)            # cosine similarity of the best matching chunk
    cites = Column(Boolean, default=False)           # whether the later paper cites the gap's paper anyway


class EvoCrossLink(Base):
    """A paper in another map whose text matches a gap statement: a loose link across maps.

    Like ``EvoLooseLink``, ``chunk_id`` is not a foreign key; a link to a chunk that is gone drops out of reads.
    """
    __tablename__ = "evo_cross_links"
    __table_args__ = (
        UniqueConstraint("gap_id", "paper_id", name="uq_evo_cross_link"),
    )

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    gap_id = Column(PG_UUID(as_uuid=True), ForeignKey("evo_gap_statements.id", ondelete="CASCADE"),
                    nullable=False, index=True)
    paper_id = Column(PG_UUID(as_uuid=True), ForeignKey("evo_papers.id", ondelete="CASCADE"),
                      nullable=False, index=True)
    chunk_id = Column(PG_UUID(as_uuid=True), nullable=False)
    score = Column(Float, nullable=False)


# ── Research evolution: reading, questions and history ───────────────


class EvoPaperNote(Base):
    """Model-written text about a paper's place in one topic, kept for the build it was written for.

    kind "why": the reading path's one line on why the paper matters.
    """
    __tablename__ = "evo_paper_notes"
    __table_args__ = (
        UniqueConstraint("topic_id", "paper_id", "kind", name="uq_evo_paper_note"),
    )

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    topic_id = Column(PG_UUID(as_uuid=True), ForeignKey("evo_topics.id", ondelete="CASCADE"), nullable=False)
    paper_id = Column(PG_UUID(as_uuid=True), ForeignKey("evo_papers.id", ondelete="CASCADE"), nullable=False)
    kind = Column(String, nullable=False)
    text = Column(String, nullable=False)
    model = Column(String, nullable=True)
    built_at = Column(DateTime(timezone=True), nullable=True)  # the topic build it describes; stale once rebuilt
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class EvoReadingProgress(Base):
    """A paper a user has marked as read. Per paper, so reading it in one map counts in every map."""
    __tablename__ = "evo_reading_progress"

    user_id = Column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    paper_id = Column(PG_UUID(as_uuid=True), ForeignKey("evo_papers.id", ondelete="CASCADE"), primary_key=True)
    read_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class EvoIdeaCheck(Base):
    """An idea or abstract checked against every map: the closest papers, the gaps it touches, a verdict."""
    __tablename__ = "evo_idea_checks"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id = Column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    idea = Column(String, nullable=False)
    result = Column(JSONB, nullable=False, default={})
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class EvoMapQuestion(Base):
    """A question asked of one map, its answer and the passages it cited."""
    __tablename__ = "evo_map_questions"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id = Column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    topic_id = Column(PG_UUID(as_uuid=True), ForeignKey("evo_topics.id", ondelete="CASCADE"),
                      nullable=False, index=True)
    question = Column(String, nullable=False)
    answer = Column(String, nullable=False, default="")
    sources = Column(JSONB, nullable=False, default=[])
    sections = Column(JSONB, nullable=False, default=[])   # section-type filters the question was asked with
    input_tokens = Column(Integer, default=0)
    output_tokens = Column(Integer, default=0)
    model = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class EvoSnapshot(Base):
    """A topic's milestones and gap themes at one point, and what changed since the snapshot before it."""
    __tablename__ = "evo_snapshots"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    topic_id = Column(PG_UUID(as_uuid=True), ForeignKey("evo_topics.id", ondelete="CASCADE"),
                      nullable=False, index=True)
    taken_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    built_at = Column(DateTime(timezone=True), nullable=True)  # the build it describes
    reason = Column(String, nullable=False)          # baseline | build | refresh | full_text
    milestones = Column(JSONB, nullable=False, default=[])  # [{paper_id, title, year, named_method, score}]
    themes = Column(JSONB, nullable=False, default=[])      # [{label, status, size, first_year, last_year, members}]
    paper_ids = Column(JSONB, nullable=False, default=[])
    stats = Column(JSONB, nullable=False, default={})
    changes = Column(JSONB, nullable=True)           # against the previous snapshot; null for the first


# ── Inbox ────────────────────────────────────────────────────────────


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


# ── Usage and sharing ────────────────────────────────────────────────


class UsageEvent(Base):
    """Model calls: who asked (none for background work), for what, and their tokens and cost.

    Append-only, so a month's spend survives users deleting their questions and checks. Cost is priced when the
    call is made, at the prices set then.
    """
    __tablename__ = "usage_events"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    user_id = Column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    feature = Column(String, nullable=False)         # qa | map_qa | idea_check | lit_review | summary | ...
    kind = Column(String, nullable=False, default="chat")  # chat | embed
    model = Column(String, nullable=False, default="")
    calls = Column(Integer, nullable=False, default=1)  # background calls are summed into one row a minute
    input_tokens = Column(Integer, nullable=False, default=0)
    output_tokens = Column(Integer, nullable=False, default=0)
    cost_usd = Column(Float, nullable=False, default=0.0)


class MapShare(Base):
    """A read-only link to a map for people without an account. The token is the whole secret."""
    __tablename__ = "map_shares"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    topic_id = Column(PG_UUID(as_uuid=True), ForeignKey("evo_topics.id", ondelete="CASCADE"), nullable=False,
                      index=True)
    token = Column(String, unique=True, nullable=False)
    created_by = Column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=True)   # none: until revoked
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    views = Column(Integer, nullable=False, default=0)
    last_viewed_at = Column(DateTime(timezone=True), nullable=True)

    topic = relationship("EvoTopic")


# ── Reading and personalisation ──────────────────────────────────────


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


# ── Writing ──────────────────────────────────────────────────────────


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
