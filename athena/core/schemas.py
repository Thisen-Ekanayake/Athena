from datetime import datetime
from typing import List, Optional, Any, Dict
from uuid import UUID
from pydantic import BaseModel, HttpUrl, Field

class SourceBase(BaseModel):
    name: str
    url: HttpUrl
    type: str
    category: str
    fetch_config: Dict[str, Any] = {}
    is_active: bool = True

class SourceCreate(SourceBase):
    pass

class SourceRead(SourceBase):
    id: UUID
    last_fetched_at: Optional[datetime] = None
    added_by: str

    class Config:
        from_attributes = True

class ContentItemBase(BaseModel):
    title: str
    url: HttpUrl
    published_at: datetime
    authors: List[str] = []
    abstract: Optional[str] = None
    category: str
    extra_data: Dict[str, Any] = {}

class ContentItemCreate(ContentItemBase):
    source_id: UUID
    content_hash: str

class ContentItemRead(ContentItemBase):
    id: UUID
    source_id: UUID
    fetched_at: datetime
    citation_count: int
    score: float
    cluster_id: Optional[UUID] = None

    class Config:
        from_attributes = True
