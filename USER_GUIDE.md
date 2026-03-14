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

Create a `.env` file from the example:

```bash
cp .env.example .env
```

## 2. Start Infrastructure

Start the PostgreSQL, Redis, and Qdrant services using Docker Compose:

```bash
docker-compose up -d
```

Verify that the services are running:

```bash
docker-compose ps
```

## 3. Initialize and Seed

Run the setup script to initialize the database schema and seed the initial sources (ArXiv, OpenAI, Google DeepMind):

```bash
python3 scripts/setup_project.py
```

## 4. Run Ingestion Pass

Trigger a manual crawl for all 8 active sources. This will fetch new data, deduplicate using SHA-256 hashes, and save it to the database:

```bash
python3 scripts/run_crawl.py
```

### 4.1. Run Enrichment Workers (Phase 1/2)

To process Semantic Scholar metrics (rate-limited to 1 req/sec) and Papers With Code benchmarks, you need to start the Celery worker. *Note: The crawler scripts add tasks to the Redis queue, which this worker executes.*

In a new terminal window, activate your python environment and run:
```bash
celery -A athena.pipeline.tasks worker -l info --pool=threads
```

## 5. Verify Results

Check the ingestion results to see the record counts and source breakdown:

```bash
python3 scripts/verify_db.py
```

### Expected Output
Because the feeds update dynamically, your exact item counts will vary, but you should see 8 total sources configured:
```text
Total Sources: 8
Total Content Items: ~1770

Sources and Item Counts:
  Anthropic News: X
  ArXiv AI: X
  Google DeepMind Blog: X
  Hugging Face Blog: X
  Meta AI Blog: X
  Microsoft Research Blog: X
  NVIDIA Blog: X
  OpenAI News: X
```

### Verifying Enrichment Data
You can use the database viewer to check if arXiv papers were successfully enriched with citation counts.
```bash
python3 scripts/view_db.py -s "ArXiv" -n 5
```
Look for the `extra_data` or `citation_count` fields in the output to confirm Semantic Scholar data was appended by the Celery worker.


## 6. What's Next? (Phases 3-5)

Once you have verified the RSS and API ingest pipelines are working (Phases 1 & 2), the next architectural milestones in the `AI-News-RAG-System-Checklist.md` are:

- **Phase 3**: Implement robust retry logic, dead-letter queues, fetch logs, and rate-limiting trackers to handle production load.
- **Phase 4**: Setup Playwright headless scraping for Javascript-heavy community blogs (e.g., The Gradient).
- **Phase 5**: Complete LLM enrichment (summaries, tags) and vector database handoffs.

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
