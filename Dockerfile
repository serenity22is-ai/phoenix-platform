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

# System deps for Playwright and runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
    libx11-6 libx11-xcb1 libxcb1 libxcomposite1 libxcursor1 libxdamage1 \
    libxext6 libxfixes3 libxi6 libxrandr2 libxrender1 libxss1 libxtst6 \
    libglib2.0-0 libnss3 libnssutil3 libnspr4 \
    libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 libdbus-1-3 \
    libatspi2.0-0 libgbm1 libpango-1.0-0 libcairo2 libasound2 \
    libfontconfig1 libfreetype6 libpq5 curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /usr/local

# Install Playwright Chromium only
RUN playwright install chromium && playwright install-deps chromium

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
