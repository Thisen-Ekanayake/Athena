"""Live paper search against the Semantic Scholar Graph API.

It goes through the shared client (``athena.core.semantic_scholar``), so it takes its turn with map builds and
the workers and retries a rate limit, but gives up after about ten seconds: someone is waiting for the results.
"""
from __future__ import annotations

import httpx
from loguru import logger

from athena.core.semantic_scholar import SemanticScholarAuthError, SemanticScholarClient

PATIENCE = 10.0  # seconds a search may spend waiting out rate limits
DEFAULT_TIMEOUT = 15.0


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

    try:
        client = SemanticScholarClient(cache_dir="", patience=PATIENCE)
        client.http.timeout = httpx.Timeout(DEFAULT_TIMEOUT)
        with client.http:
            raw_papers = client.search(query, limit=limit)
    except (httpx.HTTPError, SemanticScholarAuthError) as exc:
        logger.warning(f"semantic_scholar: HTTP error — {exc}")
        return []
    except ValueError as exc:
        logger.warning(f"semantic_scholar: invalid JSON — {exc}")
        return []

    papers: list[dict] = []
    for raw in raw_papers:
        if not isinstance(raw, dict):
            continue
        paper = _normalise_paper(raw)
        if paper is not None:
            papers.append(paper)
    return papers
