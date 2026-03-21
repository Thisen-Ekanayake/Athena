import html
from typing import List
from datetime import datetime
import time
import feedparser
from playwright.async_api import async_playwright
from newspaper import Article
from loguru import logger

from athena.scrapers.base import BaseScraper
from athena.core.schemas import ContentItemCreate
from athena.core.models import ContentCategory


class PlaywrightScraper(BaseScraper):
    """
    Scraper that fetches RSS feeds to find URLs, and then uses a headless browser
    (Playwright) and Newspaper3k to bypass paywalls/JS blocks and extract the full
    clean body text of the articles.
    """

    async def fetch(self, url: str) -> List[ContentItemCreate]:
        items = []
        logger.info(f"Fetching feed for Playwright: {url}")
        feed = feedparser.parse(url)

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",  # noqa: E501
            )
            page = await context.new_page()

            for entry in feed.entries[:10]:  # Limit to 10 latest to avoid long crawls
                try:
                    title = html.unescape(entry.get('title', 'Unknown').strip())
                    link = entry.get('link', '').strip()

                    if not link:
                        continue

                    published_parsed = entry.get('published_parsed') or entry.get(
                        'updated_parsed') or entry.get('created_parsed')
                    if published_parsed:
                        published_at = datetime.fromtimestamp(time.mktime(published_parsed))
                    else:
                        published_at = datetime.utcnow()

                    logger.info(f"Extracting HTML via Playwright: {link}")
                    try:
                        await page.goto(link, wait_until="domcontentloaded", timeout=30000)
                        await page.wait_for_timeout(2000)
                        page_html = await page.content()
                    except Exception as goto_err:
                        logger.warning(f"Timeout or error loading {link}, skipping: {goto_err}")
                        continue

                    article = Article(url=link)
                    article.set_html(page_html)
                    article.parse()

                    text_content = article.text.strip()
                    if not text_content:
                        continue

                    authors = article.authors if article.authors else []
                    if not authors and entry.get('author'):
                        authors = [entry.author]

                    content_hash = self.generate_content_hash(f"{title}|{text_content}")

                    item = ContentItemCreate(
                        source_id=self.source_id,
                        title=title,
                        url=link,
                        published_at=published_at,
                        authors=authors,
                        abstract=text_content[:800],  # using text preview as abstract
                        category=ContentCategory.COMMUNITY_BLOG.value,
                        content_hash=content_hash,
                        extra_data={"feed_link": url, "full_text_scraped": True}
                    )
                    items.append(item)
                except Exception as e:
                    logger.error(f"Error scraping {entry.get('link')} with Playwright: {e}")
                    continue

            await browser.close()

        if not items:
            raise Exception(f"Failed to scrape any items using Playwright from {url}.")

        return items
