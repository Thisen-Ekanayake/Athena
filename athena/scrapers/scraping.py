import asyncio
from typing import List, Dict, Any
from datetime import datetime
from playwright.async_api import async_playwright
from athena.scrapers.base import BaseScraper
from athena.core.schemas import ContentItemCreate
from athena.core.models import ContentCategory
from loguru import logger

class PlaywrightScraper(BaseScraper):
    async def fetch(self, url: str, selector: str, category: str = ContentCategory.COMMUNITY_BLOG.value) -> List[ContentItemCreate]:
        items = []
        async with async_playwright() as p:
            try:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                await page.goto(url, wait_until="networkidle")

                # Example scraping logic (generic, needs refinement per site)
                cards = await page.query_selector_all(selector)
                for card in cards:
                    try:
                        title_el = await card.query_selector("h2, h3, a.title")
                        title = await title_el.inner_text() if title_el else "Unknown Title"
                        
                        link_el = await card.query_selector("a")
                        link = await link_el.get_attribute("href") if link_el else ""
                        if link and not link.startswith("http"):
                            from urllib.parse import urljoin
                            link = urljoin(url, link)

                        content_hash = self.generate_content_hash(f"{title}|{link}")

                        item = ContentItemCreate(
                            source_id=self.source_id,
                            title=title.strip(),
                            url=link,
                            published_at=datetime.utcnow(), # Scraped sites often need dynamic extraction
                            authors=[],
                            abstract=None,
                            category=category,
                            content_hash=content_hash,
                            extra_data={"scraped_from": url}
                        )
                        items.append(item)
                    except Exception as e:
                        logger.error(f"Error parsing card: {e}")
                        continue

                await browser.close()
            except Exception as e:
                logger.error(f"Error during playwright scraping of {url}: {e}")
        
        return items
