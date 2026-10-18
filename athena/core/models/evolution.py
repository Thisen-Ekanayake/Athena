"""
Research maps (evolution).

Papers here are a separate corpus from content_items: they come from
OpenAlex, are grouped into topics, and never enter the feed. Share links to maps live here too.
"""
from datetime import datetime
from uuid import uuid4
from sqlalchemy import (
    Column, String, DateTime, Integer, Float, Boolean, ARRAY, ForeignKey, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB
from sqlalchemy.orm import relationship

from athena.core.models.base import Base


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
