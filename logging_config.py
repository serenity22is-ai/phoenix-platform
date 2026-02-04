"""
PHOENIX Structured JSON Logging Configuration

Provides:
- JSON formatted log output for production (machine-parseable)
- Human-readable colored output for development
- Request context enrichment (request_id, user_id, IP)
- Log rotation via RotatingFileHandler
- Separate error log file

Usage:
    from logging_config import init_logging
    init_logging(app)
"""

import json
import logging
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler

from flask import g, request, has_request_context


class JSONFormatter(logging.Formatter):
    """Structured JSON log formatter for production."""

    def format(self, record):
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Add request context if available
        if has_request_context():
            log_entry["request"] = {
                "method": request.method,
                "path": request.path,
                "remote_addr": request.remote_addr,
                "user_agent": str(request.user_agent)[:200],
            }
            if hasattr(g, "request_id"):
                log_entry["request_id"] = g.request_id
            if hasattr(g, "user_id"):
                log_entry["user_id"] = g.user_id

        # Add exception info if present
        if record.exc_info and record.exc_info[0]:
            log_entry["exception"] = {
                "type": record.exc_info[0].__name__,
                "message": str(record.exc_info[1]),
            }

        # Add extra fields
        for key in ("duration_ms", "status_code", "endpoint", "p2p_transaction_id",
                     "escrow_id", "market", "search_id"):
            if hasattr(record, key):
                log_entry[key] = getattr(record, key)

        return json.dumps(log_entry, default=str)


class DevFormatter(logging.Formatter):
    """Human-readable colored formatter for development."""

    COLORS = {
        "DEBUG": "\033[36m",     # Cyan
        "INFO": "\033[32m",      # Green
        "WARNING": "\033[33m",   # Yellow
        "ERROR": "\033[31m",     # Red
        "CRITICAL": "\033[35m",  # Magenta
    }
    RESET = "\033[0m"

    def format(self, record):
        color = self.COLORS.get(record.levelname, "")
        ts = datetime.now().strftime("%H:%M:%S")
        ctx = ""
        if has_request_context():
            ctx = f" [{request.method} {request.path}]"
        return f"{color}{ts} {record.levelname:<8}{self.RESET} {record.name}{ctx} - {record.getMessage()}"


def init_logging(app):
    """Configure structured logging for the Flask app."""
    env = os.environ.get("FLASK_ENV", "development")
    log_level = logging.DEBUG if env == "development" else logging.INFO
    log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")

    # Create log directory
    os.makedirs(log_dir, exist_ok=True)

    # Root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Remove existing handlers
    root_logger.handlers.clear()

    if env == "production":
        # JSON formatter for production
        formatter = JSONFormatter()

        # Console handler (JSON)
        console = logging.StreamHandler(sys.stdout)
        console.setLevel(log_level)
        console.setFormatter(formatter)
        root_logger.addHandler(console)

        # File handler — all logs (rotating, 10MB x 5 files)
        file_handler = RotatingFileHandler(
            os.path.join(log_dir, "phoenix.log"),
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
        )
        file_handler.setLevel(log_level)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

        # Error file handler — errors only
        error_handler = RotatingFileHandler(
            os.path.join(log_dir, "phoenix-errors.log"),
            maxBytes=10 * 1024 * 1024,
            backupCount=3,
        )
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(formatter)
        root_logger.addHandler(error_handler)
    else:
        # Dev colored output
        formatter = DevFormatter()
        console = logging.StreamHandler(sys.stdout)
        console.setLevel(log_level)
        console.setFormatter(formatter)
        root_logger.addHandler(console)

    # Quiet noisy libraries
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    # Request context middleware
    @app.before_request
    def _set_request_context():
        g.request_id = request.headers.get("X-Request-ID", str(uuid.uuid4())[:8])
        g.request_start = time.time()
        try:
            from flask_login import current_user
            if current_user.is_authenticated:
                g.user_id = current_user.id
        except Exception:
            pass

    @app.after_request
    def _log_request(response):
        if request.path in ("/health", "/metrics", "/favicon.ico"):
            return response

        duration_ms = 0
        if hasattr(g, "request_start"):
            duration_ms = round((time.time() - g.request_start) * 1000, 1)

        logger = logging.getLogger("phoenix.access")
        extra = {
            "duration_ms": duration_ms,
            "status_code": response.status_code,
            "endpoint": request.endpoint or "unknown",
        }

        if response.status_code >= 500:
            logger.error(
                f"{request.method} {request.path} {response.status_code} ({duration_ms}ms)",
                extra=extra,
            )
        elif response.status_code >= 400:
            logger.warning(
                f"{request.method} {request.path} {response.status_code} ({duration_ms}ms)",
                extra=extra,
            )
        else:
            logger.info(
                f"{request.method} {request.path} {response.status_code} ({duration_ms}ms)",
                extra=extra,
            )

        return response

    app.logger.info(f"Logging initialized — env={env}, level={logging.getLevelName(log_level)}")
