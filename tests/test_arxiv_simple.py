import asyncio
import sys
import os
from uuid import uuid4

# Add the project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from athena.scrapers.arxiv import ArXivScraper

async def test_arxiv():
    print("Testing ArXiv Scraper...")
    source_id = str(uuid4())
    scraper = ArXivScraper(source_id=source_id)
    
    results = await scraper.fetch(max_results=5)
    
    print(f"Found {len(results)} items:")
    for i, item in enumerate(results):
        print(f"\n[{i+1}] {item.title}")
        print(f"    URL: {item.url}")
        print(f"    Authors: {', '.join(item.authors)}")
        print(f"    Published: {item.published_at}")

if __name__ == "__main__":
    asyncio.run(test_arxiv())
