from typing import Dict, Any, Optional

from loguru import logger

COUNT_FIELDS = "paperId,externalIds,citationCount,referenceCount"
PATIENCE = 120.0  # seconds a lookup may wait out rate limits; the daily momentum refresh catches what it misses


class SemanticScholarEnricher:
    """Citation counts for new arXiv papers, through the shared Semantic Scholar client (its turn and retries)."""

    @staticmethod
    def fetch_many(arxiv_ids: list[str]) -> Dict[str, Optional[Dict[str, Any]]]:
        """The citation and reference counts of arXiv papers by id: one request per 200 papers.

        A paper maps to None when Semantic Scholar doesn't know it yet, and every paper does when the lookup fails.
        """
        from athena.core.semantic_scholar import SemanticScholarClient
        keys = {arxiv_id: f"ARXIV:{arxiv_id}" for arxiv_id in arxiv_ids}
        try:
            client = SemanticScholarClient(cache_dir="", patience=PATIENCE)
            with client.http:
                papers = client.get_papers(list(keys.values()), fields=COUNT_FIELDS)
        except Exception as e:
            logger.error(f"Semantic Scholar enrichment failed for {len(keys)} papers: {e}")
            return dict.fromkeys(keys)
        found = {arxiv_id: papers.get(key) for arxiv_id, key in keys.items()}
        logger.debug(f"Semantic Scholar knows {sum(p is not None for p in found.values())} of {len(found)} papers")
        return {arxiv_id: None if paper is None else {
            "paper_id": paper.paper_id,
            "citation_count": paper.citation_count,
            "reference_count": paper.reference_count,
        } for arxiv_id, paper in found.items()}
