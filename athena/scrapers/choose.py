"""Which scraper reads a source: by its type, then its URL."""
from athena.core.models import SourceType
from athena.core.safe_http import host_is
from athena.scrapers.arxiv import ArXivScraper
from athena.scrapers.lesswrong import AIAlignmentForumScraper, LessWrongScraper
from athena.scrapers.rss import RSSScraper
from athena.scrapers.scraping import PlaywrightScraper
from athena.scrapers.substack import SubstackScraper


def scraper_for(source, source_id: str):
    """Factory: return the right scraper for this source type and URL (its host, not any text in it)."""
    url = source.url
    stype = source.type

    if stype == SourceType.API:
        if host_is(url, "arxiv.org"):
            return ArXivScraper(source_id=source_id)
    cat = source.category.value if hasattr(source.category, 'value') else str(source.category)
    if stype == SourceType.RSS:
        return RSSScraper(source_id=source_id, source_category=cat)
    elif stype == SourceType.SCRAPE:
        # Route to API-based scrapers where possible to avoid fragile headless browser
        if host_is(url, "lesswrong.com"):
            return LessWrongScraper(source_id=source_id)
        elif host_is(url, "alignmentforum.org"):
            return AIAlignmentForumScraper(source_id=source_id)
        elif host_is(url, "substack.com"):
            return SubstackScraper(source_id=source_id)
        else:
            from athena.database.operations import known_urls
            return PlaywrightScraper(source_id=source_id, source_category=cat, known=known_urls)
    return None
