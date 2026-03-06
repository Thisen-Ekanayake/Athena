import sys
import os
from uuid import uuid4

# Add the project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from athena.database.db import init_db
from athena.database.operations import upsert_source
from athena.core.schemas import SourceCreate
from athena.core.models import SourceType, SourceCategory

def setup():
    print("Initializing Database...")
    init_db()
    
    print("Seeding Initial Sources...")
    
    # ArXiv Source
    upsert_source(SourceCreate(
        name="ArXiv AI",
        url="https://export.arxiv.org/api/query",
        type=SourceType.API,
        category=SourceCategory.PAPER,
        fetch_config={"query": "cat:cs.AI OR cat:cs.LG", "max_results": 20}
    ))
    
    # OpenAI Blog
    upsert_source(SourceCreate(
        name="OpenAI News",
        url="https://openai.com/news/rss.xml",
        type=SourceType.RSS,
        category=SourceCategory.COMPANY
    ))
    
    # Google DeepMind Blog
    upsert_source(SourceCreate(
        name="Google DeepMind Blog",
        url="https://deepmind.google/blog/rss.xml",
        type=SourceType.RSS,
        category=SourceCategory.COMPANY
    ))

    print("Setup Complete.")

if __name__ == "__main__":
    setup()
