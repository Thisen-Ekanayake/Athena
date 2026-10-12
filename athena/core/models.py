from datetime import datetime
from uuid import uuid4
from sqlalchemy import (
    Column, String, DateTime, Integer, Float, Boolean, ARRAY,
    Enum as SQLEnum, ForeignKey, UniqueConstraint, func,
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
    TRENDING_BRIEF = "trending_brief"
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
    embedding_model = Column(String, default="text-embedding-3-small")
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

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(String, nullable=False, unique=True)
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


class ReferenceEmbedding(Base):
    """Stores positive/negative reference embeddings for semantic scoring."""
    __tablename__ = "reference_embeddings"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    label = Column(String, nullable=False)  # 'positive' or 'negative'
    text_content = Column(String, nullable=False)
    embedding = Column(ARRAY(Float), nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class ScoreAuditLog(Base):
    """Audit log for significant score changes (> 0.1 delta)."""
    __tablename__ = "score_audit_logs"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    item_id = Column(PG_UUID(as_uuid=True), ForeignKey("content_items.id"), nullable=False)
    old_score = Column(Float, nullable=False)
    new_score = Column(Float, nullable=False)
    delta = Column(Float, nullable=False)
    reason = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class AppSetting(Base):
    """User-configurable key/value settings persisted in the database."""
    __tablename__ = "app_settings"

    key = Column(String, primary_key=True)
    value = Column(String, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)


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
