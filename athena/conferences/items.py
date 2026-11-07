"""
A conference paper as a feed item, made when someone saves it to a list or adds it to a project, so it is read,
noted and searched like any other paper of Athena's. Its source is "ACL Anthology", which is never crawled.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from athena.conferences import anthology
from athena.core.models import (
    ConfPaper, ConfVolume, ContentCategory, ContentItem, Source, SourceCategory, SourceType, SummaryStatus,
)

SOURCE_NAME = "ACL Anthology"
SOURCE_URL = "https://aclanthology.org/"


def source(session: Session) -> Source:
    row = session.execute(select(Source).where(Source.url == SOURCE_URL)).scalar_one_or_none()
    if row is None:
        row = Source(name=SOURCE_NAME, url=SOURCE_URL, type=SourceType.API, category=SourceCategory.PAPER,
                     is_active=False, added_by="system", authority_score=0.8, fetch_config={"conferences": True})
        session.add(row)
        session.flush()
    return row


def as_item(session: Session, paper: ConfPaper) -> tuple[ContentItem, bool]:
    """The paper's feed item, made now if it has none; (item, made)."""
    if paper.item_id and (item := session.get(ContentItem, paper.item_id)):
        return item, False
    url = anthology.page_url(paper.id)
    item = session.execute(select(ContentItem).where(ContentItem.url == url)).scalar_one_or_none()
    made = item is None
    if made:
        vol = session.get(ConfVolume, paper.volume_id)
        item = ContentItem(
            source_id=source(session).id, title=paper.title, url=url,
            published_at=datetime(paper.year, 1, 1, tzinfo=timezone.utc), authors=paper.authors or [],
            abstract=paper.abstract, citation_count=paper.citation_count or 0, category=ContentCategory.PAPER,
            content_hash=hashlib.sha256(url.encode()).hexdigest(), summary_status=SummaryStatus.PENDING,
            extra_data={"anthology_id": paper.id, "pdf_url": anthology.pdf_url(paper.id), "doi": paper.doi,
                        "venue": vol.title if vol else None, "awards": paper.awards or []})
        session.add(item)
        session.flush()
    paper.item_id = item.id
    session.commit()
    if made:
        _stage(item, paper)
    return item, made


def _stage(item: ContentItem, paper: ConfPaper) -> None:
    """Its text to the embedding queue, as the crawl does for new items (best effort: no worker, no vector yet)."""
    try:
        from athena.pipeline.crawl import stage_content_item
        stage_content_item.delay(item.url, paper.abstract or paper.title, paper.title, str(item.id))
    except Exception:
        pass
