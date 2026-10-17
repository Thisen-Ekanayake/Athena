from sqlalchemy.dialects.postgresql import insert
from sqlalchemy import select
from athena.database.db import SessionLocal
from athena.core.models import Source, ContentItem
from athena.core.schemas import SourceCreate, ContentItemCreate
from datetime import datetime
from loguru import logger


def upsert_source(source_data: SourceCreate) -> Source:
    data = source_data.dict()
    data['url'] = str(data['url'])

    with SessionLocal() as session:
        stmt = insert(Source).values(**data)
        stmt = stmt.on_conflict_do_update(
            index_elements=['url'],
            set_={k: v for k, v in data.items() if k != 'url'}
        )
        session.execute(stmt)
        session.commit()
        return session.execute(select(Source).where(Source.url == data['url'])).scalar_one()


def save_content_items(items: list[ContentItemCreate]) -> list[str]:
    new_urls = []
    success_count = 0
    with SessionLocal() as session:
        for item in items:
            try:
                data = item.dict()
                data['url'] = str(data['url'])

                # Check for existing content_hash first to avoid transaction rollback loop
                from sqlalchemy import select
                existing = session.execute(
                    select(ContentItem).where(ContentItem.content_hash == data['content_hash'])
                ).scalar_one_or_none()

                if existing:
                    continue

                stmt = insert(ContentItem).values(**data)
                stmt = stmt.on_conflict_do_nothing(index_elements=['url'])
                result = session.execute(stmt)

                if result.rowcount > 0:
                    success_count += 1
                    new_urls.append(data['url'])
                session.commit()
            except Exception as e:
                session.rollback()
                if "unique constraint" not in str(e).lower():
                    logger.error(f"Error saving item {item.url}: {e}")
                continue

        logger.info(f"Successfully processed {len(items)} items. New items added: {success_count}")
        return new_urls


def update_content_item_metrics(url: str, citation_count: int, extra_data: dict):
    """Merge enrichment results into an item. Keys the scrapers set (arxiv_id, pdf_url) stay, a failed lookup
    (None) keeps what an earlier one found, and the citation count never goes down to a missing answer's 0."""
    with SessionLocal() as session:
        item = session.execute(select(ContentItem).where(ContentItem.url == url)).scalar_one_or_none()
        if item is None:
            return
        item.extra_data = {**(item.extra_data or {}), **{k: v for k, v in extra_data.items() if v is not None}}
        item.citation_count = max(item.citation_count or 0, citation_count or 0)
        session.commit()


def get_active_sources():
    with SessionLocal() as session:
        return session.execute(select(Source).where(Source.is_active .is_(True))).scalars().all()


def get_scoring_config(category: str):
    """Fetch the active scoring config for a given content category."""
    from athena.core.models import ScoringConfig
    with SessionLocal() as session:
        config = session.execute(
            select(ScoringConfig)
            .where(ScoringConfig.is_active .is_(True))
            .where(ScoringConfig.category == category)
            .order_by(ScoringConfig.version.desc())
        ).scalars().first()
        return config


def fetch_durations(source_ids: list) -> dict[str, float]:
    """Each source's usual fetch time in seconds: the median of its last five successful fetches."""
    from statistics import median
    from athena.core.models import FetchLog
    out: dict[str, float] = {}
    with SessionLocal() as session:
        for source_id in source_ids:
            rows = session.execute(
                select(FetchLog.duration_ms)
                .where(FetchLog.source_id == source_id, FetchLog.status == "success")
                .order_by(FetchLog.created_at.desc()).limit(5)
            ).scalars().all()
            if rows:
                out[str(source_id)] = median(rows) / 1000
    return out


def latest_published(source_id) -> datetime | None:
    """When the newest item this source has given us was published."""
    from sqlalchemy import func
    with SessionLocal() as session:
        return session.execute(
            select(func.max(ContentItem.published_at)).where(ContentItem.source_id == source_id)
        ).scalar_one_or_none()


def known_urls(urls: list[str]) -> set[str]:
    """The URLs among ``urls`` that are already stored."""
    if not urls:
        return set()
    with SessionLocal() as session:
        return set(session.execute(select(ContentItem.url).where(ContentItem.url.in_(urls))).scalars())
