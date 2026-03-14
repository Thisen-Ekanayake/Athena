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
    with SessionLocal() as session:
        success_count = 0
        for item in items:
            try:
                data = item.dict()
                data['url'] = str(data['url'])
                # We use content_hash as the primary deduplicator if it exists
                stmt = insert(ContentItem).values(**data)
                stmt = stmt.on_conflict_do_nothing(index_elements=['url'])
                result = session.execute(stmt)
                if result.rowcount > 0:
                    success_count += 1
                    new_urls.append(data['url'])
            except Exception as e:
                # Silently skip duplicates if they weren't caught by on_conflict
                if "unique constraint" in str(e).lower():
                    continue
                logger.error(f"Error saving item {item.url}: {e}")
                continue
        session.commit()
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
