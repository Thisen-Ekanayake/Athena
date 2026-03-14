import httpx
from typing import Dict, Any, Optional
from loguru import logger

class PapersWithCodeEnricher:
    BASE_URL = "https://paperswithcode.com/api/v1"

    async def fetch_paper_artifacts(self, arxiv_id: str) -> Optional[Dict[str, Any]]:
        """
        Fetch GitHub repos and benchmark scores for a given arXiv ID.
        """
        url = f"{self.BASE_URL}/papers/"
        params = {"arxiv_id": arxiv_id}
        
        async with httpx.AsyncClient() as client:
            try:
                # 1. Find the paper on PWC using arxiv_id
                response = await client.get(url, params=params, timeout=10.0)
                response.raise_for_status()
                data = response.json()
                
                if not data.get("results"):
                    logger.debug(f"PapersWithCode: No entry for arXiv:{arxiv_id}")
                    return None
                
                # We take the first result's ID
                pwc_paper_id = data["results"][0]["id"]
                
                # 2. Get the repositories for this paper
                repo_url = f"{self.BASE_URL}/papers/{pwc_paper_id}/repositories/"
                repo_response = await client.get(repo_url, timeout=10.0)
                repo_response.raise_for_status()
                repo_data = repo_response.json()
                
                repos = []
                if "results" in repo_data:
                    for repo in repo_data["results"]:
                        repos.append({
                            "url": repo.get("url"),
                            "stars": repo.get("stars"),
                            "framework": repo.get("framework")
                        })
                
                return {
                    "pwc_id": pwc_paper_id,
                    "repositories": repos
                }
            except Exception as e:
                logger.error(f"Papers With Code Enrichment Error for {arxiv_id}: {e}")
                return None
