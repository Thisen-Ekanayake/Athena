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

## 6. Project Structure Overview

- `athena/scrapers/`: Individual source connectors.
- `athena/database/`: Database logic (SQLAlchemy models).
- `athena/pipeline/`: Celery task definitions.
- `scripts/`: Utility scripts for management and verification.
