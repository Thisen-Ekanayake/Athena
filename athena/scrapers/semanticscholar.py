import os
import httpx
from typing import Dict, Any, Optional
from loguru import logger

class SemanticScholarEnricher:
    BASE_URL = "https://api.semanticscholar.org/graph/v1"
    
    def __init__(self):
        self.api_key = os.getenv("SEMANTIC_SCHOLAR_API_KEY")
        self.headers = {"x-api-key": self.api_key} if self.api_key else {}

    async def fetch_paper_metrics(self, arxiv_id: str) -> Optional[Dict[str, Any]]:
        """
        Fetch citation count and influence score matching an arXiv ID.
        Rate limited to 1 request / second globally via Celery.
        """
        url = f"{self.BASE_URL}/paper/ARXIV:{arxiv_id}"
        # We request fields: citationCount, influenceMetrics (if available) - influence score isn't a direct field anymore, 
        # so we fetch citationCount, and referenceCount as basic metrics.
        params = {"fields": "citationCount,referenceCount,influentialCitationCount"}
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(url, headers=self.headers, params=params, timeout=10.0)
                if response.status_code == 404:
                    logger.debug(f"Semantic Scholar: Paper not found for arXiv:{arxiv_id}")
                    return None
                response.raise_for_status()
                data = response.json()
                
                return {
                    "citation_count": data.get("citationCount", 0),
                    "influential_citation_count": data.get("influentialCitationCount", 0),
                    "reference_count": data.get("referenceCount", 0)
                }
            except Exception as e:
                logger.error(f"Semantic Scholar Enrichment Error for {arxiv_id}: {e}")
                return None
