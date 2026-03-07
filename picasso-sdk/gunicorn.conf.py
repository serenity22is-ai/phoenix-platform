# =============================================================================
# ANASTASiA API — Gunicorn Configuration
# =============================================================================

import os

# Server Socket
port = os.environ.get("PORT", "8000")
bind = os.environ.get("GUNICORN_BIND", f"0.0.0.0:{port}")
backlog = 2048

# Worker Processes
# gthread — real OS threads, safe with all C extensions.
# 2 workers × 4 threads = 8 concurrent requests.
workers = int(os.environ.get("GUNICORN_WORKERS", "2"))
worker_class = "gthread"
threads = int(os.environ.get("GUNICORN_THREADS", "4"))

# Timeouts — AI chat can take 30s+ for Claude responses
timeout = 180
graceful_timeout = 30
keepalive = 5

# Memory Leak Prevention
max_requests = 1000
max_requests_jitter = 50

# Preloading
preload_app = True

# Logging
accesslog = os.environ.get("GUNICORN_ACCESS_LOG", "-")
errorlog = os.environ.get("GUNICORN_ERROR_LOG", "-")
loglevel = os.environ.get("GUNICORN_LOG_LEVEL", "info")
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'
capture_output = True

# Process Naming
proc_name = "anastasia"

# Security
limit_request_line = 8190
limit_request_fields = 100
limit_request_field_size = 8190


# Server Hooks
def on_starting(server):
    server.log.info("ANASTASiA API is starting...")


def post_fork(server, worker):
    server.log.info(f"Worker spawned (pid: {worker.pid})")


def when_ready(server):
    server.log.info("ANASTASiA API is ready. Spawning workers...")


def worker_abort(worker):
    worker.log.warning(f"Worker {worker.pid} was aborted (possible timeout)")
