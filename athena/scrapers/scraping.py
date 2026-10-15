import html
import json
import re
from typing import Callable, List, Optional, Set
from datetime import datetime
from urllib.parse import urljoin, urlparse
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

MAX_ARTICLES = 10  # newest articles read per source and sync
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/129.0.0.0 Safari/537.36")
# Paths under a listing that are more listings, not articles
_NOT_ARTICLE = ("/page/", "/tag/", "/tags/", "/category/", "/categories/", "/author/", "/authors/", "/topics/")


def article_links(listing_url: str, hrefs: List[str], limit: int = MAX_ARTICLES) -> List[str]:
    """Links that look like the listing's articles, in page order: same host, one level under its path."""
    base = urlparse(listing_url)
    prefix = base.path.rstrip("/") + "/"
    out: List[str] = []
    for href in hrefs:
        u = urlparse(href)
        if u.netloc != base.netloc or not u.path.startswith(prefix):
            continue
        slug = u.path[len(prefix):].strip("/")
        if len(slug) < 4 or any(part in u.path for part in _NOT_ARTICLE):
            continue
        link = f"{u.scheme}://{u.netloc}{u.path}"
        if link not in out:
            out.append(link)
        if len(out) >= limit:
            break
    return out


_WRITTEN_DATE = re.compile(
    r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)"
    r" \d{1,2}, \d{4}\b")


def _date(value) -> Optional[datetime]:
    if not value:
        return None
    try:
        from dateutil import parser as dateparser
        return dateparser.parse(str(value))
    except (ValueError, OverflowError):
        return None


def page_meta(page_html: str) -> dict:
    """An article page's title, publication date and authors, from its meta tags, JSON-LD or markup."""
    soup = BeautifulSoup(page_html, "html.parser")

    def meta(*names):
        for name in names:
            tag = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name})
            if tag and tag.get("content"):
                return tag["content"].strip()
        return None

    ld: dict = {}
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except ValueError:
            continue
        nodes = data if isinstance(data, list) else data.get("@graph", [data]) if isinstance(data, dict) else []
        for node in nodes:
            if isinstance(node, dict) and node.get("datePublished"):
                ld = node
                break
        if ld:
            break

    h1 = soup.find("h1")
    title = meta("og:title", "twitter:title") or (h1.get_text(" ", strip=True) if h1 else None) or (
        soup.title.get_text(strip=True) if soup.title else None)
    time_tag = soup.find("time", attrs={"datetime": True})
    published = _date(meta("article:published_time", "og:published_time", "publish-date", "date")
                      or ld.get("datePublished") or (time_tag["datetime"] if time_tag else None))
    if published is None:
        # Some sites (Meta's blog) only print the date: the first one written out near the top of the page
        body = soup.body.get_text(" ", strip=True)[:4000] if soup.body else ""
        found = _WRITTEN_DATE.search(body)
        published = _date(found.group(0)) if found else None
    people = ld.get("author") or []
    people = people if isinstance(people, list) else [people]
    authors = [p["name"] for p in people if isinstance(p, dict) and p.get("name")]
    if not authors and meta("author"):
        authors = [meta("author")]
    return {"title": html.unescape(title) if title else None, "published_at": published, "authors": authors}


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

    def __init__(self, source_id: str, source_category: str = "blog",
                 known: Optional[Callable[[List[str]], Set[str]]] = None):
        super().__init__(source_id)
        self.source_category = source_category
        # Tells which article URLs are stored already, so their pages are not fetched again
        self.known = known

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
        Find the source's articles, then fetch each one's full page HTML with Playwright.

        Articles come from the source's RSS/Atom feed, or, for a site with none (Anthropic's and Meta's news
        pages), from the links on its listing page. Pages already stored are not fetched again.
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

        articles: Optional[List[dict]] = None
        if feed.entries:
            articles = []
            for entry in feed.entries[:MAX_ARTICLES]:
                link = entry.get('link', '').strip()
                if not link:
                    continue
                published_parsed = entry.get('published_parsed') or entry.get(
                    'updated_parsed') or entry.get('created_parsed')
                authors = [a.get('name') for a in entry.get('authors', []) if a.get('name')]
                if not authors and entry.get('author'):
                    authors = [entry.author]
                articles.append({
                    "link": link,
                    "title": html.unescape(entry.get('title', '').strip()) or None,
                    "published_at": datetime.fromtimestamp(time.mktime(published_parsed)) if published_parsed else None,
                    "authors": authors,
                })

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(user_agent=USER_AGENT)
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

            if articles is None:
                logger.info(f"No RSS/Atom feed for {url}; reading article links from the page.")
                articles = [{"link": link} for link in await self._listing_links(page, url)]

            self.found = len(articles)
            known = self.known([a["link"] for a in articles]) if self.known else set()
            if known:
                logger.info(f"{len(known)} of {len(articles)} articles at {url} are already stored.")

            for article in articles:
                link = article["link"]
                if link in known:
                    continue
                try:
                    logger.info(f"Extracting HTML via Playwright: {link}")
                    try:
                        await page.goto(link, wait_until="domcontentloaded", timeout=30000)
                        await page.wait_for_timeout(2000)
                        page_html = await page.content()
                    except Exception as goto_err:
                        logger.warning(f"Timeout or error loading {link}, skipping: {goto_err}")
                        continue

                    meta = page_meta(page_html)
                    raw_items.append({
                        "title": article.get("title") or meta["title"] or "Unknown",
                        "link": link,
                        "published_at": article.get("published_at") or meta["published_at"] or datetime.utcnow(),
                        "page_html": page_html,
                        "authors": article.get("authors") or meta["authors"],
                        "feed_url": url
                    })
                except Exception as e:
                    logger.error(f"Error fetching {link} with Playwright: {e!r}")
                    continue

            await browser.close()

        return raw_items

    async def _listing_links(self, page, url: str) -> List[str]:
        """Article links on a listing page: same site, under the page's own path (/news -> /news/<slug>)."""
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(3000)  # listings are often filled in by script
        except Exception as e:
            logger.warning(f"Could not load the listing page {url}: {e!r}")
            return []
        hrefs = await page.eval_on_selector_all("a[href]", "els => els.map(e => e.href)")
        return article_links(page.url, hrefs)

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
        category = (ContentCategory.COMPANY_BLOG if self.source_category == "company"
                    else ContentCategory.COMMUNITY_BLOG)

        content_hash = self.generate_content_hash(f"{title}|{text_content}")

        return ContentItemCreate(
            source_id=self.source_id,
            title=title,
            url=link,
            published_at=raw['published_at'],
            authors=authors,
            abstract=text_content[:800],
            category=category.value,
            content_hash=content_hash,
            extra_data={"feed_link": raw['feed_url'], "full_text_scraped": True}
        )
