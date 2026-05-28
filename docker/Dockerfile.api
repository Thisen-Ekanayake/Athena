# Stage 1 — builder
# python:3.11-slim + build-essential so C-extension packages (psycopg2, etc.)
# can compile. Nothing from this stage leaks into the final image.
FROM python:3.11-slim AS builder
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /build
COPY requirements.api.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.api.txt

# Stage 2 — runtime
# Clean python:3.11-slim with only the runtime shared lib (libpq5).
# Compiled packages are copied in from the builder — no gcc, no headers.
FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 curl \
    && rm -rf /var/lib/apt/lists/*
COPY --from=builder /install /usr/local
WORKDIR /app
COPY . .
CMD ["uvicorn", "athena.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
