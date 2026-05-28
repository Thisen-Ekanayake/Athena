# Athena

> AI research intelligence — aggregate, process, rank, and explore content from across the AI landscape.

## System Architecture
![architecture](diagrams/system_architecture.png)

- **Sources** — content is pulled from ArXiv, Semantic Scholar, Research Papers, RSS feeds, and Playwright-driven scrapers.
- **Pipeline** — a Scraper Layer normalises raw content and queues it to Celery Workers, which run four parallel tasks: clustering (UMAP + HDBSCAN), scoring, summarisation (OpenAI), and embedding generation.
- **Storage** — enriched data is persisted to PostgreSQL (structured records), Qdrant (vector embeddings), and Redis (Celery broker/cache).
- **Serve** — FastAPI queries both databases and delivers ranked, enriched, and semantically searchable results to the Vue 3 frontend.

---

## Data Flow

```mermaid
sequenceDiagram
    participant Scraper
    participant Celery
    participant Postgres
    participant Qdrant
    participant API
    participant UI

    Scraper->>Postgres: insert raw ContentItem
    Celery->>Postgres: enrich (citations, metadata)
    Celery->>Qdrant: generate & store embeddings
    Celery->>Postgres: run scoring & clustering
    Celery->>Postgres: generate AI summary
    UI->>API: GET /feed, /search, /qa
    API->>Postgres: ranked content query
    API->>Qdrant: semantic search
    API-->>UI: ranked + enriched results
```

---

## Quick Start

```bash
# 1. Python env
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt && playwright install chromium
cp .env.example .env

# 2. Infrastructure
docker compose -f docker/docker-compose.yml up -d

# 3. Init & run
python3 scripts/setup_project.py   # schema + seed sources
python3 scripts/run_crawl.py       # first ingestion pass
celery -A athena.pipeline.tasks worker -l info --pool=threads
```

**Services**

| Service | Port |
|---------|------|
| FastAPI | 8000 |
| Vue Frontend | 5173 |
| PostgreSQL | 5432 |
| Redis | 6379 |
| Qdrant | 6333 |

---

## Stack

```mermaid
graph LR
    FE["Vue 3 + Vite"]
    BE["FastAPI + Uvicorn"]
    WQ["Celery + Redis"]
    DB["PostgreSQL\n(SQLAlchemy)"]
    VDB["Qdrant\n(vector search)"]
    LLM["OpenAI\n(summaries · QA · embeddings)"]
    ML["scikit-learn · UMAP · HDBSCAN\n(clustering)"]

    FE <--> BE
    BE <--> DB & VDB
    WQ --> DB & VDB & LLM & ML
```

---

## Contributing

1. Fork → `git checkout -b feature/your-feature`
2. Commit → `git commit -m 'feat: description'`
3. PR → open against `main`

## License

MIT — see [LICENSE](LICENSE)
