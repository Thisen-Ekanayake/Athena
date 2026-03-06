import os
import sys

# Add the project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from athena.database.db import SessionLocal
from athena.core.models import Source, ContentItem

def verify():
    with SessionLocal() as session:
        source_count = session.query(Source).count()
        item_count = session.query(ContentItem).count()
        
        print(f"Total Sources: {source_count}")
        print(f"Total Content Items: {item_count}")
        
        # Breakdown by category
        from sqlalchemy import text
        results = session.execute(text("SELECT category, count(*) FROM content_items GROUP BY category")).all()
        print("\nItems by Category:")
        for res in results:
            print(f"  {res[0]}: {res[1]}")

        # Breakdown by source (including those with 0 items)
        from sqlalchemy import text
        results = session.execute(text("SELECT s.name, (SELECT count(*) FROM content_items WHERE source_id = s.id) FROM sources s")).all()
        print("\nSources and Item Counts:")
        for res in results:
            print(f"  {res[0]}: {res[1]}")

if __name__ == "__main__":
    verify()
