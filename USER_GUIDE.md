# Athena Data Acquisition - User Guide

This guide provides instructions on how to set up, run, and verify the Athena Data Acquisition layer.

## Prerequisites

- **Python 3.10+**
- **Docker and Docker Compose**
- **Node.js** (for Playwright browser installation)

## 1. Environment Setup

First, create and activate a virtual environment, then install the required Python dependencies:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Then, install the Playwright browsers:

```bash
playwright install chromium
```

Create a `.env` file from the example and ensure you have the necessary API keys (especially `SEMANTIC_SCHOLAR_API_KEY` for paper enrichment):

```bash
cp .env.example .env
```

## 2. Start Infrastructure

Start the PostgreSQL, Redis, and Qdrant services using Docker Compose. This is **mandatory** for the backend and workers to function:

```bash
docker compose -f docker/docker-compose.yml up -d
```

Verify that the services are running:

```bash
docker compose -f docker/docker-compose.yml ps
```

## 3. Initialize and Seed

Run the setup script to initialize the database schema and seed all 11 sources (8 RSS/API + 3 headless-scraped):

```bash
python3 scripts/setup_project.py
```

## 4. Run Ingestion Pass

Trigger a manual crawl for all active sources. This will fetch new data, deduplicate using SHA-256 hashes, save it to the database, and  automatically stage content to `/tmp/athena/staging/` and push item IDs to the Redis embedding queue:

```bash
python3 scripts/run_crawl.py
```

### 4.1. Run Enrichment Workers (All Phases)

Start the Celery worker to process enrichment tasks (Semantic Scholar, Papers With Code) and staging tasks (Phase 5). In a **new terminal**:

```bash
source venv/bin/activate
celery -A athena.pipeline.tasks worker -l info --pool=threads
```

> **Note**: The Celery worker must be running for arXiv enrichment and content staging to work. The `run_crawl.py` script dispatches tasks to work queue; the worker processes them.

## 5. Verify Results

Check the ingestion results to see the record counts and source breakdown:

```bash
python3 scripts/verify_db.py
```

### Expected Output
You should see **11 total sources** (8 RSS/API + 3 headless-scraped blogs):
```text
Total Sources: 11
Total Content Items: ~1800+

Sources and Item Counts:
  [API]   ArXiv AI: ~10+
  [RSS]   OpenAI News: ~884
  [RSS]   Google DeepMind Blog: ~100
  [RSS]   Meta AI Blog: ~X
  [RSS]   Microsoft Research Blog: ~X
  [RSS]   Hugging Face Blog: ~748
  [RSS]   Anthropic News: 0 (404 - feed discontinued)
  [RSS]   NVIDIA Blog: ~18
  [SCRAPE] The Gradient: ~10
  [SCRAPE] Towards Data Science: ~10
  [SCRAPE] LessWrong: ~10
```

Check if arXiv papers were enriched with citation counts from Semantic Scholar and benchmarks from Papers With Code:
```bash
python3 scripts/view_db.py -s "ArXiv" -n 5
```
Look for the `extra_data.semantic_scholar` or `extra_data.paperswithcode` fields. Note that ArXiv IDs are automatically normalized to remove version suffixes (e.g. `2401.00001v1` becomes `2401.00001`) for better API compatibility.

### Verifying Fetch Logs (Phase 3)
Fetch logs are written to the `fetch_logs` table after every run. Check them with:
```bash
# In psql:
docker exec -it athena-db-1 psql -U athena_user -d athena_db -c "SELECT s.name, fl.status, fl.duration_ms FROM fetch_logs fl LEFT JOIN sources s ON fl.source_id = s.id ORDER BY fl.created_at DESC LIMIT 11;"
```

### Verifying Staging & Embedding Queue (Phase 5)
After running with the Celery worker, new items should be staged to disk and queued for embedding:
```bash
# Check staging directory
ls /tmp/athena/staging/ | wc -l

# Check Redis embedding queue
docker exec -it athena-redis-1 redis-cli llen athena:embedding_queue
```

## 6. Architecture Overview (Phases 1-5)

| Phase | Component | Status |
|-------|-----------|--------|
| **Phase 1** | ArXiv + Semantic Scholar + Papers With Code Connectors | ✅ Done |
| **Phase 2** | 7 Company RSS feeds + Celery Beat 6h polling | ✅ Done |
| **Phase 3** | Retry logic (3x backoff), FetchLog table, Auto-disable on 5 failures | ✅ Done |
| **Phase 4** | Playwright headless scraper (The Gradient, TDS, LessWrong) | ✅ Done |
| **Phase 5** | Full-text staging to disk + Redis embedding queue handoff | ✅ Done |

You should stop the active Celery worker (`Ctrl+C`) when you are done verifying.

## 7. Viewing Database Contents

You can view the ingested items using the provided viewing script or by connecting directly to the database.

### Using the Viewing Script

A utility script `scripts/view_db.py` is provided to easily view the latest ingested items from the terminal.

To view the 10 most recent items:
```bash
python3 scripts/view_db.py
```

To view more items (e.g., 20):
```bash
python3 scripts/view_db.py -n 20
```

To filter by a specific source (e.g., "ArXiv"):
```bash
python3 scripts/view_db.py -s "ArXiv"
```

To filter by category (e.g., "PAPER" or "COMMUNITY_BLOG"):
```bash
python3 scripts/view_db.py -c "PAPER"
```

### Accessing PostgreSQL Directly

The PostgreSQL database is exposed on `localhost:5432`. You can connect to it using any SQL client (like DBeaver, DataGrip, or `psql`).

**Connection Details:**
- **Host**: `localhost`
- **Port**: `5432`
- **Database Name**: `athena_db`
- **Username**: `athena_user`
- **Password**: `athena_password`

**Using `psql` from terminal:**
```bash
docker exec -it athena-db-1 psql -U athena_user -d athena_db
```

Once inside, you can run standard SQL queries:
```sql
-- View all sources
SELECT id, name, type, category FROM sources;

-- View recent content titles
SELECT title, published_at FROM content_items ORDER BY published_at DESC LIMIT 5;
```

## 8. Running the Application End-to-End

### 8.1. Start the Backend API

The backend API provides the endpoints for the frontend application. It can be run either via Docker or locally.

**Option A: Running locally (Development)**
Ensure your virtual environment is active and infrastructure (DB, Redis, Qdrant) is running, then start the FastAPI server:
```bash
source venv/bin/activate
uvicorn athena.api.main:app --host 0.0.0.0 --port 8000 --reload
```
The API will be available at `http://localhost:8000`. You can view the interactive API documentation at `http://localhost:8000/docs`.

**Option B: Using Docker Compose**
The `web` service in `docker/docker-compose.yml` automatically starts the API when you run `docker compose -f docker/docker-compose.yml up -d`.

### 8.2. Start the Frontend Application

The frontend is a React application built with Vite. To open it:

```bash
# Open a new terminal
cd frontend
npm install   # (Only needed the first time)
npm run dev
```

The frontend will be available at `http://localhost:5173` (or another port specified by Vite in the console).

## 9. Running Tests

The project uses `pytest` for the backend test suite. Make sure your virtual environment is active and your infrastructure containers are running.

```bash
# Run all tests
pytest tests/

# Run tests with verbose output
pytest -v tests/

# Run a specific test file
pytest tests/test_api.py
```

## 10. Troubleshooting

### Backend Returns 500 Error
This is usually caused by the database services not running. Ensure you have run:
```bash
docker compose -f docker/docker-compose.yml up -d
```
And verify with `docker compose -f docker/docker-compose.yml ps` that `athena-db-1`, `athena-redis-1`, and `athena-qdrant-1` are all "Up".

### Celery Worker Not Processing Enrichment
1. Ensure Redis is running and accessible.
2. Check that the `SEMANTIC_SCHOLAR_API_KEY` is set in your `.env` file.
3. ArXiv enrichment requires the worker to be running in a separate terminal with `--pool=threads`.

### Frontend Cannot Connect to Backend
Ensure the backend is running on `http://localhost:8000`. If you are running the backend in Docker, check the port mapping in `docker/docker-compose.yml`.
