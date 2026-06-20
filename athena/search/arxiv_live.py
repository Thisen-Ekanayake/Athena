"""Live paper search against the arXiv Atom API.

Free, key-less alternative/supplement to Semantic Scholar. Returns results in
the same dict shape as ``search_semantic_scholar`` so they can be merged.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import datetime

import httpx
from loguru import logger

ARXIV_URL = "https://export.arxiv.org/api/query"
NAMESPACE = {"atom": "http://www.w3.org/2005/Atom"}
DEFAULT_TIMEOUT = 30.0

# Filler words that hurt arXiv relevance ranking when a user types a
# natural-language request instead of keywords.
_STOPWORDS = {
    "find", "me", "show", "get", "give", "research", "researches", "paper",
    "papers", "about", "on", "for", "the", "a", "an", "of", "in", "into",
    "regarding", "related", "to", "some", "any", "please", "study", "studies",
    "work", "works", "recent", "latest",
}
_PUNCT_RE = re.compile(r"[^\w\s]")
_WS_RE = re.compile(r"\s+")


def _clean_query(query: str) -> str:
    """Strip punctuation and common filler words for a keyword-style query."""
    lowered = _PUNCT_RE.sub(" ", query.lower())
    tokens = [t for t in _WS_RE.sub(" ", lowered).split() if t and t not in _STOPWORDS]
    cleaned = " ".join(tokens).strip()
    # Fall back to the raw (punctuation-stripped) query if we stripped everything.
    return cleaned or _WS_RE.sub(" ", lowered).strip()


def _parse_year(published: str | None) -> int | None:
    if not published:
        return None
    try:
        return datetime.fromisoformat(published.replace("Z", "+00:00")).year
    except ValueError:
        return None


def _parse_entry(entry: ET.Element) -> dict | None:
    ns = NAMESPACE
    title_el = entry.find("atom:title", ns)
    summary_el = entry.find("atom:summary", ns)
    title = (title_el.text or "").strip().replace("\n", " ") if title_el is not None else ""
    abstract = (summary_el.text or "").strip() if summary_el is not None else ""
    if not abstract:
        return None

    id_el = entry.find("atom:id", ns)
    url = (id_el.text or "").strip() if id_el is not None else None
    arxiv_id = url.split("/")[-1] if url else ""

    published_el = entry.find("atom:published", ns)
    year = _parse_year(published_el.text.strip() if published_el is not None and published_el.text else None)

    authors = [
        author.find("atom:name", ns).text
        for author in entry.findall("atom:author", ns)
        if author.find("atom:name", ns) is not None
    ]

    return {
        "id": arxiv_id or url or "",
        "title": title,
        "abstract": abstract,
        "url": url,
        "year": year,
        "authors": authors,
        "citation_count": None,
        "score": None,
        "source": "arxiv",
    }


def search_arxiv(query: str, limit: int = 15) -> list[dict]:
    """Fetch live papers from arXiv.

    Filters out results without abstracts. Returns an empty list on any
    HTTP / parse failure — never raises.
    """
    if not query or not query.strip():
        return []

    params = {
        "search_query": f"all:{_clean_query(query)}",
        "start": 0,
        "max_results": limit,
        "sortBy": "relevance",
        "sortOrder": "descending",
    }
    try:
        with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
            resp = client.get(ARXIV_URL, params=params)
            resp.raise_for_status()
            root = ET.fromstring(resp.text)
    except httpx.HTTPError as exc:
        logger.warning(f"arxiv: HTTP error — {exc}")
        return []
    except ET.ParseError as exc:
        logger.warning(f"arxiv: XML parse error — {exc}")
        return []

    papers: list[dict] = []
    for entry in root.findall("atom:entry", NAMESPACE):
        paper = _parse_entry(entry)
        if paper is not None:
            papers.append(paper)
    return papers
