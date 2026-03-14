# Athena Data Acquisition - User Guide

This guide provides instructions on how to set up, run, and verify the Athena Data Acquisition layer.

## Prerequisites

- **Python 3.10+**
- **Docker and Docker Compose**
- **Node.js** (for Playwright browser installation)

## 1. Environment Setup

First, install the required Python dependencies:

```bash
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

Trigger a manual crawl for all active sources. This will fetch data and save it to the database:

```bash
python3 scripts/run_crawl.py
```

## 5. Verify Results

Check the ingestion results to see the record counts and source breakdown:

```bash
python3 scripts/verify_db.py
```

### Expected Output
You should see a summary similar to this:
```text
Total Sources: 3
Total Content Items: 985

Sources and Item Counts:
  ArXiv AI: 10
  OpenAI News: 875
  Google DeepMind Blog: 100
```

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
