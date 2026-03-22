import httpx
from bs4 import BeautifulSoup
from typing import List, Any
from datetime import datetime
from athena.scrapers.base import BaseScraper
from athena.core.schemas import ContentItemCreate
from athena.core.models import ContentCategory


class TowardsDataScienceScraper(BaseScraper):
    BASE_URL = "https://towardsdatascience.com/latest"

    async def fetch(self, limit: int = 10) -> List[Any]:
        # Simple httpx fetch since TDS latest page is mostly SSR for initial articles
        async with httpx.AsyncClient(follow_redirects=True) as client:
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Athena/1.0"}
            response = await client.get(self.BASE_URL, headers=headers)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, "html.parser")
            # Medium's layout classes change frequently but articles are mapped in <article> tags
            articles = soup.find_all("article")
            return articles[:limit]

    def parse(self, raw: Any) -> ContentItemCreate:
        # raw is a BeautifulSoup <article> element
        title_el = raw.find("h2")
        title = title_el.get_text().strip() if title_el else "Untitled TDS Article"

        # Look for the main article link
        link_el = raw.find("a", {"data-testid": "postPreviewTitle"})
        # Fallback to general h2 parent link or any valid href in the article block
        if not link_el:
            link_el = next((a for a in raw.find_all("a") if a.find("h2")), None)

        url = link_el["href"].split("?")[0] if link_el and "href" in link_el.attrs else ""
        if url.startswith("/"):
            url = f"https://towardsdatascience.com{url}"

        # Try to parse published date - Medium puts it in a span or time tag
        time_el = raw.find("time")
        published_at = datetime.utcnow()  # fallback
        if time_el and "datetime" in time_el.attrs:
            try:
                published_at = datetime.fromisoformat(time_el["datetime"].replace("Z", "+00:00"))
            except ValueError:
                pass

        # Author extraction
        author_el = raw.find("div", {"data-testid": "authorName"})
        authors = [author_el.get_text().strip()] if author_el else []

        # Abstract/preview text
        preview_el = raw.find("h3")
        abstract = preview_el.get_text().strip() if preview_el else ""

        content_hash = self.generate_content_hash(f"{title}|{abstract}")

        return ContentItemCreate(
            source_id=self.source_id,
            title=title,
            url=url,
            published_at=published_at,
            authors=authors,
            abstract=abstract,
            category=ContentCategory.COMMUNITY_BLOG.value,
            content_hash=content_hash,
            extra_data={}
        )
