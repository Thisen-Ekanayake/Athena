# Contributing to Athena

## Prerequisites

- Python 3.11+
- Node.js 18+
- Docker & Docker Compose
- Git

## Local Dev Setup

### 1. Clone and create the Python environment

```bash
git clone https://github.com/your-username/athena.git
cd athena
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env and fill in your API keys:
#   OPENAI_API_KEY, SEMANTIC_SCHOLAR_API_KEY, CROSSREF_EMAIL
```

### 3. Start infrastructure

```bash
docker compose -f docker/docker-compose.yml up -d
# Services: PostgreSQL (5432), Redis (6379), Qdrant (6333)
```

### 4. Initialise the database and seed sources

```bash
python3 scripts/setup_project.py
```

### 5. Run the backend

```bash
uvicorn athena.api.main:app --reload
# API available at http://localhost:8000
# Swagger docs at http://localhost:8000/docs  (requires DOCS_USERNAME/DOCS_PASSWORD if set)
```

### 6. Start the Celery worker (separate terminal)

```bash
source venv/bin/activate
celery -A athena.pipeline.tasks worker -l info --pool=threads
```

### 7. Run the frontend

```bash
cd frontend
npm install
npm run dev
# UI available at http://localhost:5173
```

### 8. Trigger a first ingestion pass

```bash
python3 scripts/run_crawl.py
```

## Running Tests

```bash
# Unit + integration tests (no live services needed)
pytest tests/test_scoring.py tests/test_scoring_integration.py tests/test_preprocessing.py -v

# Connector tests
pytest tests/test_connectors.py -v

# All tests
pytest -v
```

## Linting

```bash
flake8 . --max-line-length=120 --exclude="__pycache__,*.pyc,.venv,venv,.git,frontend/node_modules"
```

## Project Layout

```
athena/
  api/          FastAPI routers, deps, schemas
  core/         Models, config, Redis client
  database/     SQLAlchemy DB session and operations
  pipeline/     Celery tasks: embedding, scoring, summarisation, clustering
  scrapers/     Source-specific scrapers (ArXiv, RSS, Playwright, etc.)
frontend/       Vue 3 + Vite UI
scripts/        One-off admin and setup scripts
tests/          Pytest test suite
diagrams/       Architecture diagrams
```

## Branching and PRs

1. Fork the repo and create a feature branch: `git checkout -b feature/your-feature`
2. Keep commits focused and use [Conventional Commits](https://www.conventionalcommits.org/) style (`feat:`, `fix:`, `chore:`, etc.)
3. Ensure `flake8` passes and relevant tests are green before opening a PR
4. Open a PR against `main` with a clear description of what changed and why
