from athena.core.models import Source, SourceType, SourceCategory
from athena.database.db import SessionLocal
import sys
import os

# Ensure athena is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


# OpenAI, Google DeepMind and Meta AI come from scripts/setup_project.py; their feeds here duplicated them under
# other URLs.
COMPANY_FEEDS = [
    {"name": "BAIR", "url": "https://bair.berkeley.edu/blog/feed.xml"},
    {"name": "Google Research", "url": "https://blog.research.google/feeds/posts/default"},
{"name": "Apple Machine Learning", "url": "https://machinelearning.apple.com/feed.xml"},
]


def seed_feeds():
    db = SessionLocal()
    try:
        for feed in COMPANY_FEEDS:
            exists = db.query(Source).filter(Source.url == feed["url"]).first()
            if not exists:
                new_source = Source(
                    name=feed["name"],
                    url=feed["url"],
                    type=SourceType.RSS,
                    category=SourceCategory.COMPANY,
                    is_active=True,
                    added_by="system",
                    authority_score=0.9
                )
                db.add(new_source)
                print(f"Added company feed: {feed['name']}")
            else:
                print(f"Feed already exists: {feed['name']}")

        db.commit()
        print("Company feeds seeding complete.")
    finally:
        db.close()


if __name__ == "__main__":
    seed_feeds()
