import os
import sys
from sqlalchemy import select, desc
import argparse

# Add the project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from athena.database.db import SessionLocal
from athena.core.models import ContentItem, Source

def view_items(limit=10, source_name=None, category=None):
    with SessionLocal() as session:
        query = select(ContentItem).join(Source).order_by(desc(ContentItem.published_at))
        
        if source_name:
            query = query.where(Source.name.ilike(f"%{source_name}%"))
        
        if category:
            query = query.where(ContentItem.category == category)
            
        query = query.limit(limit)
        items = session.execute(query).scalars().all()
        
        if not items:
            print("No items found matching the criteria.")
            return

        print(f"\n--- Showing latest {len(items)} items ---" + (f" (filtered by source: {source_name})" if source_name else "") + (f" (filtered by category: {category})" if category else ""))
        print("-" * 80)
        
        for idx, item in enumerate(items, 1):
            source = session.execute(select(Source).where(Source.id == item.source_id)).scalar_one()
            print(f"{idx}. [{source.name}] {item.title}")
            print(f"   URL: {item.url}")
            print(f"   Published: {item.published_at}")
            print(f"   Category: {item.category.name}")
            if item.authors:
                print(f"   Authors: {', '.join(item.authors)}")
            if item.abstract:
                # Truncate abstract for display
                abstract = item.abstract if len(item.abstract) < 150 else item.abstract[:147] + "..."
                print(f"   Abstract: {abstract}")
            print("-" * 80)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="View recent items from the Athena database.")
    parser.add_argument("-n", "--limit", type=int, default=10, help="Number of items to display (default: 10)")
    parser.add_argument("-s", "--source", type=str, help="Filter by source name (e.g., 'ArXiv')")
    parser.add_argument("-c", "--category", type=str, help="Filter by content category (e.g., 'PAPER', 'COMMUNITY_BLOG')")
    
    args = parser.parse_args()
    view_items(limit=args.limit, source_name=args.source, category=args.category)
