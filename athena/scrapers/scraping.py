import html
from typing import List, Optional
from datetime import datetime
from urllib.parse import urljoin
import time
import feedparser
import httpx
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
from newspaper import Article
from loguru import logger

from athena.scrapers.base import BaseScraper
from athena.core.schemas import ContentItemCreate
from athena.core.models import ContentCategory

# Common feed locations to probe when a source URL is an HTML page, not a feed.
_FEED_FALLBACK_PATHS = (
    "/rss/", "/rss", "/feed/", "/feed",
    "/atom.xml", "/index.xml", "/feed.xml", "/rss.xml",
)


class PlaywrightScraper(BaseScraper):
    """
    Scraper that fetches RSS feeds to find URLs, and then uses a headless browser
    (Playwright) and Newspaper3k to bypass paywalls/JS blocks and extract the full
    clean body text of the articles.
    """

    async def _discover_feed(self, url: str) -> Optional[str]:
        """
        Resolve an RSS/Atom feed from an HTML page URL.

        Tries feed autodiscovery (<link rel="alternate">) first, then a set of
        common feed paths. Returns the first candidate that yields entries, or
        None if nothing usable is found.
        """
        candidates: List[str] = []

        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as client:
                resp = await client.get(
                    url,
                    headers={"User-Agent": "Mozilla/5.0 (compatible; Athena/1.0)"},
                )
            soup = BeautifulSoup(resp.text, "html.parser")
            for link in soup.find_all("link", rel="alternate"):
                ltype = (link.get("type") or "").lower()
                href = link.get("href")
                if href and ("rss" in ltype or "atom" in ltype or "xml" in ltype):
                    candidates.append(urljoin(url, href))
        except Exception as e:
            logger.warning(f"Feed autodiscovery request failed for {url}: {e}")

        candidates.extend(urljoin(url, path) for path in _FEED_FALLBACK_PATHS)

        seen = set()
        for cand in candidates:
            if cand in seen:
                continue
            seen.add(cand)
            try:
                if feedparser.parse(cand).entries:
                    return cand
            except Exception:
                continue
        return None

    async def fetch(self, url: str) -> List[dict]:
        """
        Fetch RSS entries and for each, fetch the full page HTML using Playwright.
        Returns a list of raw dictionaries containing metadata and HTML content.
        """
        raw_items = []
        logger.info(f"Fetching feed for Playwright: {url}")
        feed = feedparser.parse(url)

        if not feed.entries:
            # The source URL is an HTML page, not a feed — try to discover one.
            discovered = await self._discover_feed(url)
            if discovered:
                logger.info(f"Discovered feed for {url}: {discovered}")
                feed = feedparser.parse(discovered)

        if not feed.entries:
            logger.warning(f"No RSS/Atom feed could be discovered for {url}; nothing to crawl.")
            return raw_items

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",  # noqa: E501
            )
            page = await context.new_page()

            # Verify playwright is usable
            try:
                await page.goto("about:blank")
            except Exception as e:
                if "Executable doesn't exist" in str(e):
                    logger.critical(
                        "Playwright browsers NOT found! Please ensure 'playwright install' "
                        "was run in the worker environment."
                    )
                    await browser.close()
                    raise RuntimeError(
                        "Playwright browsers missing. Rebuild docker container with "
                        "'docker compose -f docker/docker-compose.yml up --build'."
                    )
                raise e

            for entry in feed.entries[:10]:
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

                    authors = [a.get('name') for a in entry.get('authors', []) if a.get('name')]
                    if not authors and entry.get('author'):
                        authors = [entry.author]

                    raw_items.append({
                        "title": title,
                        "link": link,
                        "published_at": published_at,
                        "page_html": page_html,
                        "authors": authors,
                        "feed_url": url
                    })
                except Exception as e:
                    logger.error(f"Error fetching {entry.get('link')} with Playwright: {e}")
                    continue

            await browser.close()

        return raw_items

    def parse(self, raw: dict) -> ContentItemCreate:
        """
        Extract the article body from the raw HTML using Newspaper3k.
        """
        link = raw['link']
        title = raw['title']
        page_html = raw['page_html']

        article = Article(url=link)
        article.set_html(page_html)
        article.parse()

        text_content = article.text.strip()
        if not text_content:
            raise ValueError(f"No text content could be extracted from {link}")

        authors = raw['authors']
        if not authors and article.authors:
            authors = article.authors

        content_hash = self.generate_content_hash(f"{title}|{text_content}")

        return ContentItemCreate(
            source_id=self.source_id,
            title=title,
            url=link,
            published_at=raw['published_at'],
            authors=authors,
            abstract=text_content[:800],
            category=ContentCategory.COMMUNITY_BLOG.value,
            content_hash=content_hash,
            extra_data={"feed_link": raw['feed_url'], "full_text_scraped": True}
        )
