import httpx
from typing import Dict, Any, Optional, List
from loguru import logger


class PapersWithCodeEnricher:
    BASE_URL = "https://paperswithcode.com/api/v1"

    async def fetch_paper_artifacts(self, arxiv_id: str) -> Optional[Dict[str, Any]]:
        """
        Fetch GitHub repos and benchmark scores for a given arXiv ID.
        """
        async with httpx.AsyncClient() as client:
            try:
                # 1. Find the paper on PWC using arxiv_id
                response = await client.get(f"{self.BASE_URL}/papers/", params={"arxiv_id": arxiv_id}, timeout=10.0)
                response.raise_for_status()
                data = response.json()

                if not data.get("results"):
                    logger.debug(f"PapersWithCode: No entry for arXiv:{arxiv_id}")
                    return None

                pwc_paper_id = data["results"][0]["id"]

                # 2. Fetch repositories
                repos = await self._fetch_repos(client, pwc_paper_id)

                # 3. Fetch benchmark results (new — per the acquisition plan)
                benchmarks = await self._fetch_benchmarks(client, pwc_paper_id)

                return {
                    "pwc_id": pwc_paper_id,
                    "repositories": repos,
                    "benchmarks": benchmarks
                }
            except Exception as e:
                logger.error(f"Papers With Code Enrichment Error for {arxiv_id}: {e}")
                return None

    async def _fetch_repos(self, client: httpx.AsyncClient, pwc_paper_id: str) -> List[Dict]:
        try:
            resp = await client.get(f"{self.BASE_URL}/papers/{pwc_paper_id}/repositories/", timeout=10.0)
            resp.raise_for_status()
            data = resp.json()
            return [
                {"url": r.get("url"), "stars": r.get("stars"), "framework": r.get("framework")}
                for r in data.get("results", [])
            ]
        except Exception as e:
            logger.warning(f"Could not fetch repos for {pwc_paper_id}: {e}")
            return []

    async def _fetch_benchmarks(self, client: httpx.AsyncClient, pwc_paper_id: str) -> List[Dict]:
        """Fetch benchmark results from /papers/{id}/results/."""
        try:
            resp = await client.get(f"{self.BASE_URL}/papers/{pwc_paper_id}/results/", timeout=10.0)
            resp.raise_for_status()
            data = resp.json()
            benchmarks = []
            for result in data.get("results", []):
                benchmarks.append({
                    "task": result.get("task", {}).get("name"),
                    "dataset": result.get("dataset", {}).get("name"),
                    "metric": result.get("metric"),
                    "score": result.get("score"),
                    "model": result.get("model"),
                })
            return benchmarks
        except Exception as e:
            logger.warning(f"Could not fetch benchmarks for {pwc_paper_id}: {e}")
            return []
