# =============================================================================
# MYSTES Flight Arbitrage Platform - Gunicorn Configuration
# =============================================================================

import multiprocessing
import os

# Server Socket
port = os.environ.get("PORT", "5001")
bind = os.environ.get("GUNICORN_BIND", f"0.0.0.0:{port}")
backlog = 2048

# Worker Processes
# 2 workers × 4 threads on Render Pro (4GB RAM) — plenty of headroom.
# gevent is NOT used because psycopg2 (C extension) corrupts connections
# under gevent's monkey-patched sockets. gthread uses real OS threads instead.
_default_workers = int(os.environ.get("WEB_CONCURRENCY", 2))
workers = int(os.environ.get("GUNICORN_WORKERS", _default_workers))
worker_class = "gthread"
threads = 4

# Worker heartbeat temp directory — CRITICAL for Docker containers.
# Default /tmp uses overlay filesystem (slow I/O). Delayed heartbeat writes
# cause the master to kill workers thinking they're hung. /dev/shm is
# RAM-backed — instant writes, no false timeouts.
worker_tmp_dir = "/dev/shm"

# Timeouts
timeout = 120
graceful_timeout = 30
keepalive = 5

# Memory Leak Prevention — recycle workers periodically to prevent
# long-running memory bloat from 15K-line server.py.
max_requests = 1000
max_requests_jitter = 50

# Preloading — load app once in master, fork to workers. Saves memory.
preload_app = True

# Logging
accesslog = os.environ.get("GUNICORN_ACCESS_LOG", "-")
errorlog = os.environ.get("GUNICORN_ERROR_LOG", "-")
loglevel = os.environ.get("GUNICORN_LOG_LEVEL", "info")
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'
capture_output = True

# Process Naming
proc_name = "mystes"

# Security
limit_request_line = 8190
limit_request_fields = 100
limit_request_field_size = 8190


# Server Hooks
def on_starting(server):
    server.log.info("MYSTES is starting...")


def post_fork(server, worker):
    server.log.info(f"Worker spawned (pid: {worker.pid})")


def when_ready(server):
    server.log.info("MYSTES is ready. Spawning workers...")


def worker_abort(worker):
    worker.log.warning(f"Worker {worker.pid} was aborted (possible timeout)")
