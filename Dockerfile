# PHOENIX Flight Arbitrage Platform - Production Dockerfile

# Stage 1: Builder
FROM python:3.11-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Stage 2: Production
FROM python:3.11-slim AS production

LABEL maintainer="PHOENIX Team"
LABEL description="PHOENIX Flight Arbitrage Platform"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FLASK_ENV=production \
    FLASK_APP=server.py

WORKDIR /app

# Runtime deps (libpq for PostgreSQL, curl for healthcheck)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /usr/local

# Install Playwright Chromium + all its system deps
RUN playwright install --with-deps chromium

# Non-root user
RUN groupadd -r phoenix && useradd -r -g phoenix -d /app -s /sbin/nologin phoenix

COPY . .

RUN mkdir -p /app/instance /app/logs && \
    chown -R phoenix:phoenix /app

USER phoenix

EXPOSE 5001

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:5001/ || exit 1

CMD ["gunicorn", "--config", "gunicorn.conf.py", "server:app"]
