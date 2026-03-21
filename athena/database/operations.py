from sqlalchemy.dialects.postgresql import insert
from sqlalchemy import select
from athena.database.db import SessionLocal
from athena.core.models import Source, ContentItem
from athena.core.schemas import SourceCreate, ContentItemCreate
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
    with SessionLocal() as session:
        from sqlalchemy import update
        stmt = update(ContentItem).where(ContentItem.url == url).values(
            citation_count=citation_count,
            extra_data=extra_data
        )
        session.execute(stmt)
        session.commit()

def get_active_sources():
    with SessionLocal() as session:
        return session.execute(select(Source).where(Source.is_active == True)).scalars().all()


def get_scoring_config(category: str):
    """Fetch the active scoring config for a given content category."""
    from athena.core.models import ScoringConfig
    with SessionLocal() as session:
        config = session.execute(
            select(ScoringConfig)
            .where(ScoringConfig.is_active == True)
            .where(ScoringConfig.category == category)
            .order_by(ScoringConfig.version.desc())
        ).scalar_one_or_none()
        return config


def save_metric_snapshot(item_id, citation_count: int, engagement_raw: float):
    """Save a daily metric snapshot for velocity computation."""
    from athena.core.models import MetricSnapshot
    from datetime import datetime, timezone
    with SessionLocal() as session:
        snapshot = MetricSnapshot(
            item_id=item_id,
            citation_count=citation_count,
            engagement_raw=engagement_raw,
            snapshot_date=datetime.now(timezone.utc),
        )
        session.add(snapshot)
        session.commit()
