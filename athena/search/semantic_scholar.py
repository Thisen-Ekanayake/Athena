"""Live paper search against the Semantic Scholar Graph API."""
from __future__ import annotations

import httpx
from loguru import logger

from athena.core.config_store import get_setting

SEMANTIC_SCHOLAR_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
FIELDS = "title,abstract,year,authors,citationCount,url"
DEFAULT_TIMEOUT = 15.0


def _build_headers() -> dict[str, str]:
    headers = {"Accept": "application/json"}
    api_key = get_setting("SEMANTIC_SCHOLAR_API_KEY")
    if api_key:
        headers["x-api-key"] = api_key
    return headers


def _normalise_paper(raw: dict) -> dict | None:
    abstract = (raw.get("abstract") or "").strip()
    if not abstract:
        return None

    authors_raw = raw.get("authors") or []
    authors = [a.get("name") for a in authors_raw if isinstance(a, dict) and a.get("name")]

    citation_count = raw.get("citationCount")
    if citation_count is None:
        citation_count = 0

    return {
        "id": raw.get("paperId") or "",
        "title": raw.get("title") or "",
        "abstract": abstract,
        "url": raw.get("url"),
        "year": raw.get("year"),
        "authors": authors,
        "citation_count": int(citation_count),
        "score": None,
        "source": "semantic_scholar",
    }


def search_semantic_scholar(query: str, limit: int = 15) -> list[dict]:
    """Fetch live papers from Semantic Scholar.

    Filters out results without abstracts. Returns an empty list on any
    HTTP / parse failure — never raises.
    """
    if not query or not query.strip():
        return []

    params = {"query": query, "fields": FIELDS, "limit": limit}
    try:
        with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
            resp = client.get(
                SEMANTIC_SCHOLAR_URL,
                params=params,
                headers=_build_headers(),
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as exc:
        logger.warning(f"semantic_scholar: HTTP error — {exc}")
        return []
    except ValueError as exc:
        logger.warning(f"semantic_scholar: invalid JSON — {exc}")
        return []

    raw_papers = data.get("data") or []
    papers: list[dict] = []
    for raw in raw_papers:
        if not isinstance(raw, dict):
            continue
        paper = _normalise_paper(raw)
        if paper is not None:
            papers.append(paper)
    return papers
