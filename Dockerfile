# MYSTES Flight Arbitrage Platform - Production Dockerfile
FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FLASK_ENV=production \
    FLASK_APP=server.py

# System deps: gcc for compiling C extensions, libpq for PostgreSQL, curl for health checks
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App source
COPY . .

# Non-root user
RUN groupadd -r mystes && useradd -r -g mystes -d /app -s /sbin/nologin mystes \
    && mkdir -p /app/instance /app/logs \
    && chown -R mystes:mystes /app

USER mystes

CMD ["gunicorn", "--config", "gunicorn.conf.py", "server:app"]
