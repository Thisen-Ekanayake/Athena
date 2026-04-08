# Athena

> AI research intelligence — aggregate, process, rank, and explore content from across the AI landscape.

```mermaid
graph LR
    subgraph Sources
        A1[ArXiv]
        A2[Semantic Scholar]
        A3[Papers With Code]
        A4[RSS Feeds]
        A5[Playwright Scrapers]
    end

    subgraph Pipeline
        B1[Scraper Layer]
        B2[Celery Workers]
        B3[Embeddings]
        B4[Clustering]
        B5[Scoring]
        B6[Summarisation]
    end

    subgraph Storage
        C1[(PostgreSQL)]
        C2[(Qdrant)]
        C3[(Redis)]
    end

    subgraph Serve
        D1[FastAPI]
        D2[Vue Frontend]
    end

    Sources --> B1
    B1 --> B2
    B2 --> B3 & B4 & B5 & B6
    B3 --> C2
    B2 --> C1
    C3 --- B2
    C1 & C2 --> D1
    D1 --> D2
```

---

## Architecture

```mermaid
graph TD
    subgraph Acquisition ["Layer 1–2 · Acquisition & Polling"]
        S1["arxiv.py"]
        S2["semanticscholar.py"]
        S3["paperswithcode.py"]
        S4["rss.py"]
        S5["lesswrong.py · substack.py\nthegradient.py · towardsdatascience.py"]
    end

    subgraph Pipeline ["Layer 3–4 · Processing (Celery Beat)"]
        direction TB
        T1["scoring.py\nevery 1 min"]
        T2["embedding_worker.py\nevery 1 min"]
        T3["clustering.py\nevery 6 h"]
        T4["summarisation_tasks.py\non demand"]
        T5["crawl sources\nevery 6 h"]
    end

    subgraph API ["Layer 5 · API  :8000"]
        R1["/feed · /items · /sources"]
        R2["/clusters · /trending"]
        R3["/search · /qa · /score"]
        R4["/sync"]
    end

    DB[(PostgreSQL\nContent · Clusters\nSources · Scores)]
    VDB[(Qdrant\nEmbeddings)]
    CACHE[(Redis\nBroker · Cache)]

    Acquisition --> Pipeline
    Pipeline <--> CACHE
    Pipeline --> DB & VDB
    DB & VDB --> API
    API --> FE["Vue.js Frontend\n:5173"]
```

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
docker-compose up -d

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
