import asyncio
import sys
import os
from uuid import uuid4

# Add the project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# noqa: E402
from athena.scrapers.rss import RSSScraper


async def test_rss():
    print("Testing RSS Scraper...")
    source_id = str(uuid4())
    scraper = RSSScraper(source_id=source_id)

    # Testing with OpenAI blog RSS
    url = "https://openai.com/news/rss.xml"
    raw_results = await scraper.fetch(url)
    results = [scraper.parse(raw) for raw in raw_results]

    print(f"Found {len(results)} items from {url}:")
    for i, item in enumerate(results[:5]):
        print(f"\n[{i+1}] {item.title}")
        print(f"    URL: {item.url}")
        print(f"    Published: {item.published_at}")


if __name__ == "__main__":
    asyncio.run(test_rss())
