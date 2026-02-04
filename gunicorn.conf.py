# =============================================================================
# PHOENIX Flight Arbitrage Platform - Gunicorn Configuration
# =============================================================================

import multiprocessing
import os

# Server Socket
bind = os.environ.get("GUNICORN_BIND", "0.0.0.0:5001")
backlog = 2048

# Worker Processes
workers = int(os.environ.get("GUNICORN_WORKERS", multiprocessing.cpu_count() * 2 + 1))
worker_class = "gevent"
worker_connections = 1000
threads = 1

# Timeouts (120s for long proxy scrape requests)
timeout = 120
graceful_timeout = 30
keepalive = 5

# Memory Leak Prevention
max_requests = 1000
max_requests_jitter = 50

# Preloading
preload_app = True

# Logging
accesslog = os.environ.get("GUNICORN_ACCESS_LOG", "/app/logs/gunicorn-access.log")
errorlog = os.environ.get("GUNICORN_ERROR_LOG", "/app/logs/gunicorn-error.log")
loglevel = os.environ.get("GUNICORN_LOG_LEVEL", "info")
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'
capture_output = True

# Process Naming
proc_name = "phoenix"

# Security
limit_request_line = 8190
limit_request_fields = 100
limit_request_field_size = 8190


# Server Hooks
def on_starting(server):
    server.log.info("PHOENIX is starting...")


def post_fork(server, worker):
    server.log.info(f"Worker spawned (pid: {worker.pid})")


def when_ready(server):
    server.log.info("PHOENIX is ready. Spawning workers...")


def worker_abort(worker):
    worker.log.warning(f"Worker {worker.pid} was aborted (possible timeout)")
