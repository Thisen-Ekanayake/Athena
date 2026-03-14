"""
LessWrong and AI Alignment Forum API scrapers.
Both platforms share the same GraphQL API endpoint format.
No headless scraping required — they provide a public GraphQL API.
"""
import httpx
from typing import List, Any
from datetime import datetime, timezone
from athena.scrapers.base import BaseScraper
from athena.core.schemas import ContentItemCreate
from athena.core.models import ContentCategory
from loguru import logger

LESSWRONG_API = "https://www.lesswrong.com/graphql"
ALIGNMENT_FORUM_API = "https://www.alignmentforum.org/graphql"

POSTS_QUERY = """
query RecentPosts($limit: Int!) {
  posts(input: {terms: {view: "new", limit: $limit}}) {
    results {
      _id
      title
      pageUrl
      postedAt
      htmlBody
      user { displayName }
      baseScore
    }
  }
}
"""

class LessWrongScraper(BaseScraper):
    """Fetches posts from LessWrong via their public GraphQL API."""
    API_URL = LESSWRONG_API
    SITE_NAME = "LessWrong"

    async def fetch(self, limit: int = 20) -> List[Any]:
        """Fetch recent posts from the GraphQL endpoint."""
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(
                    self.API_URL,
                    json={"query": POSTS_QUERY, "variables": {"limit": limit}},
                    headers={"Content-Type": "application/json"},
                    timeout=20.0
                )
                resp.raise_for_status()
                data = resp.json()
                posts = data.get("data", {}).get("posts", {}).get("results", [])
                logger.info(f"{self.SITE_NAME} API returned {len(posts)} posts.")
                return posts
            except Exception as e:
                logger.error(f"Error fetching from {self.SITE_NAME} API: {e}")
                raise e

    def parse(self, post: Any) -> ContentItemCreate:
        """Normalise a single LessWrong GraphQL post to ContentItemCreate."""
        title = post.get("title", "Unknown Title")
        url = post.get("pageUrl", "")
        posted_at_str = post.get("postedAt", "")
        try:
            published_at = datetime.fromisoformat(posted_at_str.replace("Z", "+00:00"))
        except Exception:
            published_at = datetime.now(tz=timezone.utc)

        author = post.get("user", {}).get("displayName", "Unknown")
        html_body = post.get("htmlBody", "") or ""
        # Strip HTML from body to get plain text preview
        import re
        plain_text = re.sub(r'<[^>]+>', '', html_body).strip()

        content_hash = self.generate_content_hash(f"{title}|{plain_text[:500]}")

        return ContentItemCreate(
            source_id=self.source_id,
            title=title,
            url=url,
            published_at=published_at,
            authors=[author],
            abstract=plain_text[:800],
            category=ContentCategory.COMMUNITY_BLOG.value,
            content_hash=content_hash,
            extra_data={"base_score": post.get("baseScore", 0), "source": self.SITE_NAME}
        )


class AIAlignmentForumScraper(LessWrongScraper):
    """
    Fetches posts from the AI Alignment Forum.
    Identical GraphQL API to LessWrong — only the endpoint differs.
    """
    API_URL = ALIGNMENT_FORUM_API
    SITE_NAME = "AI Alignment Forum"
