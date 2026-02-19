# MYSTES Flight Arbitrage Platform - Production Dockerfile

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

LABEL maintainer="MYSTES Team"
LABEL description="MYSTES Flight Arbitrage Platform"

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

# NOTE: Playwright browser binary NOT installed in production container.
# The web server doesn't need it — airline_booker/google_flights_scraper
# degrade gracefully when Chromium is absent. This saves ~700MB.

# Non-root user
RUN groupadd -r mystes && useradd -r -g mystes -d /app -s /sbin/nologin mystes

COPY . .

RUN mkdir -p /app/instance /app/logs && \
    chown -R mystes:mystes /app

USER mystes

EXPOSE 5001

# Render provides its own health checks via healthCheckPath — no Docker HEALTHCHECK needed.
# (The previous HEALTHCHECK was hardcoded to port 5001, but Render sets PORT dynamically.)

CMD ["gunicorn", "--config", "gunicorn.conf.py", "server:app"]
