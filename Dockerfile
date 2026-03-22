FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
# - gcc, g++, build-essential: required for compiling C/C++ extensions
#   (hdbscan, umap-learn, scipy, scikit-learn)
# - libpq-dev: required for psycopg2-binary
# - libffi-dev, libssl-dev: required for cryptography / python-jose
# - python3-dev: required for packages that compile against Python headers
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    build-essential \
    libpq-dev \
    libffi-dev \
    libssl-dev \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Upgrade pip to latest to avoid resolution issues
RUN pip install --no-cache-dir --upgrade pip

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# Default command: run the Celery worker
CMD ["celery", "-A", "athena.pipeline.tasks", "worker", "--loglevel=info", "-B"]