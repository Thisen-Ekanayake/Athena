"""
Phase 0 — check that the Semantic Scholar key works and returns citation contexts.

Every arXiv paper in the current DB has ``extra_data.semantic_scholar = null``;
this tells apart a key problem from papers that were simply too new to be indexed.

Usage:
    python -m scripts.evolution_bench.s2_check
"""
import httpx

from athena.core.config_store import get_setting

BASE = "https://api.semanticscholar.org/graph/v1"
LORA = "arXiv:2106.09685"


def main():
    key = get_setting("SEMANTIC_SCHOLAR_API_KEY")
    headers = {"x-api-key": key} if key else {}
    print(f"API key configured: {'yes' if key else 'no'}")

    with httpx.Client(timeout=30.0, headers=headers) as client:
        r = client.get(f"{BASE}/paper/{LORA}", params={"fields": "title,year,citationCount"})
        print(f"paper lookup: HTTP {r.status_code}")
        if r.status_code == 200:
            print(f"  {r.json()}")
        else:
            print(f"  {r.text[:300]}")

        r = client.get(f"{BASE}/paper/{LORA}/citations",
                       params={"fields": "title,year,contexts,intents,isInfluential", "limit": 5})
        print(f"citations with contexts: HTTP {r.status_code}")
        if r.status_code != 200:
            print(f"  {r.text[:300]}")
            return
        for item in r.json().get("data", []):
            citing = item.get("citingPaper", {})
            contexts = item.get("contexts") or []
            print(f"  - {citing.get('title', '')[:80]} ({citing.get('year')}) intents={item.get('intents')} "
                  f"contexts={len(contexts)}")
            if contexts:
                print(f"      \"{contexts[0][:200]}\"")


if __name__ == "__main__":
    main()
