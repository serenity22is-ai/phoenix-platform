# ANASTASiA API — Production Dockerfile
FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# System deps: curl for health checks
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install the SDK with all dependencies (agent + billing)
COPY pyproject.toml README.md ./
COPY picasso/ picasso/
COPY anastasia/ anastasia/
COPY clients/ clients/
RUN pip install --no-cache-dir ".[agent,billing]"

# Gunicorn (not in pyproject.toml deps — production-only)
RUN pip install --no-cache-dir gunicorn

# App entry point + config
COPY wsgi.py gunicorn.conf.py ./

# Persistent storage for agency configs + usage data
RUN mkdir -p /app/.agency_configs /app/logs

# Non-root user
RUN groupadd -r anastasia && useradd -r -g anastasia -d /app -s /sbin/nologin anastasia \
    && chown -R anastasia:anastasia /app

USER anastasia

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/health || exit 1

CMD ["gunicorn", "--config", "gunicorn.conf.py", "wsgi:app"]
