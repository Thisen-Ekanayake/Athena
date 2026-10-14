import asyncio
from typing import Dict, Any, Optional

from loguru import logger

COUNT_FIELDS = "paperId,externalIds,citationCount,referenceCount"
PATIENCE = 120.0  # seconds one lookup may wait out rate limits; the daily momentum refresh catches what it misses


class SemanticScholarEnricher:
    """Citation counts for a new arXiv paper, through the shared Semantic Scholar client (its turn and retries)."""

    async def fetch_paper_metrics(self, arxiv_id: str) -> Optional[Dict[str, Any]]:
        """
        Fetch the citation and reference counts of an arXiv paper, or None when it is unknown or the lookup fails.
        """
        return await asyncio.to_thread(self._fetch, arxiv_id)

    @staticmethod
    def _fetch(arxiv_id: str) -> Optional[Dict[str, Any]]:
        from athena.evolution.semantic_scholar import SemanticScholarClient
        key = f"ARXIV:{arxiv_id}"
        try:
            client = SemanticScholarClient(cache_dir="", patience=PATIENCE)
            with client.http:
                paper = client.get_papers([key], fields=COUNT_FIELDS).get(key)
        except Exception as e:
            logger.error(f"Semantic Scholar Enrichment Error for {arxiv_id}: {e}")
            return None
        if paper is None:
            logger.debug(f"Semantic Scholar: Paper not found for arXiv:{arxiv_id}")
            return None
        return {
            "paper_id": paper.paper_id,
            "citation_count": paper.citation_count,
            "reference_count": paper.reference_count,
        }
