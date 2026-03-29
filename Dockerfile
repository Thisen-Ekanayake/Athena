# Use the full Python image which already includes build tools (gcc, g++, make, etc.)
# This is larger (~330MB vs ~50MB) but builds MUCH faster and more reliably.
FROM python:3.11-bookworm

# Set build-time environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install only the necessary runtime libraries not already in the full image
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install -r requirements.txt

# (Optional) Install Playwright browsers if your scrapers use them
# RUN playwright install --with-deps chromium

# Copy the rest of the application
COPY . .

# Default command
CMD ["celery", "-A", "athena.pipeline.tasks", "worker", "--loglevel=info", "-B"]