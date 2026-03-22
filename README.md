# Athena

Athena is a sophisticated data acquisition and RAG (Retrieval-Augmented Generation) system designed to aggregate, process, and rank information from various AI research and industry sources. It provides a unified platform for tracking AI trends, research papers, and industry news.

## 🚀 Quick Start

### 1. Environment Setup
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install chromium
cp .env.example .env
```

### 2. Infrastructure
Start PostgreSQL, Redis, and Qdrant services:
```bash
docker-compose up -d
```

### 3. Initialize & Run
```bash
# Setup DB schema and seed initial sources
python3 scripts/setup_project.py

# Run the data ingestion pass
python3 scripts/run_crawl.py

# Start Celery worker for background enrichment and processing
celery -A athena.pipeline.tasks worker -l info --pool=threads
```

## 🏗 Architecture & Layers

Athena is built with a layered architecture to ensure scalability and separation of concerns:

- **Layer 1: Acquisition**: Connectors for ArXiv, Semantic Scholar, and Papers With Code.
- **Layer 2: Polling**: Scheduled RSS/API polling for major AI companies (OpenAI, DeepMind, Meta, etc.).
- **Layer 3: Scoring**: Multi-signal scoring system based on citations, recency, and engagement.
- **Layer 4: Enrichment**: Automated summarization, embedding generation, and clustering.
- **Layer 5: API**: Unified FastAPI application serving the research intelligence feed.

## 🛠 Key Features

- **Multi-Source Ingestion**: 
  - **Connectors**: ArXiv, Semantic Scholar, Papers With Code.
  - **RSS Feeds**: Major AI lab blogs and news.
  - **Headless Scraping**: Playwright-based scrapers for The Gradient, Towards Data Science, LessWrong, and Substack.
- **Intelligent Processing**: 
  - **Enrichment**: Citation counts and paper metadata enrichment.
  - **RAG Ready**: Qdrant vector database integration for semantic search.
  - **Summarization**: Automated AI-generated summaries of lengthy articles.
- **Advanced API**: 
  - **Routers**: Feed, Items, Clusters, Trending, Search, and Sources.
  - **Q&A System**: Integrated Q&A API for interacting with research content.
  - **Scoring & Ranking**: Dynamic ranking based on custom weight profiles.

## 🤝 Contributing

Contributions are welcome! Please follow these steps:
1. Fork the project.
2. Create your feature branch (`git checkout -b feature/AmazingFeature`).
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`).
4. Push to the branch (`git push origin feature/AmazingFeature`).
5. Open a Pull Request.

## 📜 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 📂 Documentation

For detailed technical guides and component breakdowns:
- [User Guide](USER_GUIDE.md) - Full setup and execution manual.
- [Codebase Documentation](docs/) - Technical details of every script and module.
