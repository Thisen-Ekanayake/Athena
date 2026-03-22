import httpx
from bs4 import BeautifulSoup
from typing import List, Any
from datetime import datetime
from athena.scrapers.base import BaseScraper
from athena.core.schemas import ContentItemCreate
from athena.core.models import ContentCategory

class TheGradientScraper(BaseScraper):
    BASE_URL = "https://thegradient.pub/"

    async def fetch(self, limit: int = 10) -> List[Any]:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Athena/1.0"}
            response = await client.get(self.BASE_URL, headers=headers)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, "html.parser")
            # The Gradient uses Ghost; posts are typically in 'post-card' classes
            articles = soup.find_all("article", class_="post-card")
            return articles[:limit]

    def parse(self, raw: Any) -> ContentItemCreate:
        # raw is a BeautifulSoup <article> element for a Ghost post
        link_el = raw.find("a", class_="post-card-image-link") or raw.find("a", class_="post-card-content-link")
        url = link_el["href"] if link_el and "href" in link_el.attrs else ""
        if url.startswith("/"):
            url = f"https://thegradient.pub{url}"
            
        title_el = raw.find("h2", class_="post-card-title")
        title = title_el.get_text().strip() if title_el else "Untitled Gradient Article"
        
        abstract_el = raw.find("div", class_="post-card-excerpt")
        abstract = abstract_el.get_text().strip() if abstract_el else ""
        
        # Ghost typically uses .author-name
        author_el = raw.find("span", class_="post-card-author") or raw.find("li", class_="author-list-item")
        authors = [author_el.get_text().strip()] if author_el else []
        
        # Date is often in a time tag or not surfaced on the index
        time_el = raw.find("time")
        published_at = datetime.utcnow()
        if time_el and "datetime" in time_el.attrs:
            try:
                published_at = datetime.fromisoformat(time_el["datetime"])
            except ValueError:
                pass
                
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
