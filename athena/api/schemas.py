"""
Athena Layer 5 — Pydantic v2 Response Schemas

Response models for all API endpoints, matching the plan document Section 3.4.
"""
from datetime import datetime
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict


# ── Nested components ───────────────────────────────────

class SourceInfo(BaseModel):
    name: str
    type: str
    authority: float


class ClusterInfo(BaseModel):
    id: UUID
    label: Optional[str] = None


# ── Feed item ───────────────────────────────────────────

class FeedItemResponse(BaseModel):
    id: UUID
    title: str
    url: str
    source: SourceInfo
    category: str
    authors: List[str] = []
    published_at: Optional[datetime] = None
    citation_count: int = 0
    score: float = 0.0
    is_trending: bool = False
    category_rank: Optional[int] = None
    summary: Optional[str] = None
    summary_status: Optional[str] = None
    takeaways: Optional[list] = None
    cluster: Optional[ClusterInfo] = None
    related_count: int = 0

    model_config = ConfigDict(from_attributes=True)


class PaginationInfo(BaseModel):
    page: int
    limit: int
    total: int
    has_next: bool


class FeedResponse(BaseModel):
    items: List[FeedItemResponse]
    pagination: PaginationInfo


# ── Single item detail ──────────────────────────────────

class ItemDetailResponse(FeedItemResponse):
    abstract: Optional[str] = None
    full_text_path: Optional[str] = None
    fetched_at: Optional[datetime] = None
    embedded_at: Optional[datetime] = None
    summarised_at: Optional[datetime] = None


# ── Score breakdown ─────────────────────────────────────

class SignalScore(BaseModel):
    score: float
    label: str
    weight: float


class ScoreBreakdownResponse(BaseModel):
    item_id: str
    title: str
    composite_score: float
    is_trending: bool
    category_rank: Optional[int] = None
    signals: dict  # signal_name -> SignalScore dict
    computed_at: Optional[str] = None
    score_version: Optional[int] = None


# ── Related items ───────────────────────────────────────

class RelatedItemResponse(BaseModel):
    id: UUID
    title: str
    url: str
    score: float = 0.0
    similarity: float = 0.0
    category: str
    published_at: Optional[datetime] = None


# ── Clusters ────────────────────────────────────────────

class ClusterSummaryResponse(BaseModel):
    id: UUID
    label: Optional[str] = None
    summary: Optional[str] = None
    item_count: int = 0
    is_active: bool = True
    category: Optional[str] = None


class ClusterDetailResponse(BaseModel):
    cluster: ClusterSummaryResponse
    items: List[FeedItemResponse]
    pagination: PaginationInfo


# ── Trending ────────────────────────────────────────────

class TrendingBriefResponse(BaseModel):
    theme: Optional[str] = None
    brief: Optional[str] = None
    generated_at: Optional[datetime] = None


class TrendingResponse(BaseModel):
    brief: Optional[TrendingBriefResponse] = None
    items: List[FeedItemResponse]


# ── Search ──────────────────────────────────────────────

class SearchResultItem(FeedItemResponse):
    similarity: float = 0.0


class SearchResponse(BaseModel):
    query: str
    items: List[SearchResultItem]
    total: int


# ── Sources ─────────────────────────────────────────────

class SourceResponse(BaseModel):
    id: UUID
    name: str
    url: str
    type: str
    category: str
    authority_score: float = 0.5
    is_active: bool = True
    added_by: str = "system"
    last_fetched_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    consecutive_failures: int = 0

    model_config = ConfigDict(from_attributes=True)


class SourcePreviewItem(BaseModel):
    title: str
    url: str
    published_at: Optional[str] = None
    summary: Optional[str] = None


class SourcePreviewResponse(BaseModel):
    source_type: str
    source_name: str
    sample_items: List[SourcePreviewItem] = []
    # Present only on the confirm step.
    id: Optional[str] = None
    queued: Optional[bool] = None
    error: Optional[str] = None


class SourceCreateRequest(BaseModel):
    url: str
    name: Optional[str] = None
    category: str = "blog"
    # False -> preview only (no DB write, no crawl). True -> persist + queue.
    confirm: bool = False


class SourceUpdateRequest(BaseModel):
    name: Optional[str] = None
    url: Optional[str] = None


class SourceToggleResponse(BaseModel):
    id: UUID
    is_active: bool
    message: str
