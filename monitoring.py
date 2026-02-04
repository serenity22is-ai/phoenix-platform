"""
PHOENIX Monitoring & Alerting Module

Provides:
- Sentry error tracking integration
- Prometheus metrics endpoint (/metrics)
- Application metrics collection (requests, latency, errors, business metrics)
- Health check enrichment

Usage:
    from monitoring import init_monitoring, track_request, track_p2p_event
    init_monitoring(app)
"""

import os
import time
import logging
from functools import wraps

logger = logging.getLogger(__name__)


# ============================================================
# Sentry Integration
# ============================================================

def init_sentry(app):
    """Initialize Sentry error tracking if DSN is configured."""
    dsn = os.environ.get("SENTRY_DSN")
    if not dsn:
        logger.info("Sentry DSN not configured — error tracking disabled")
        return False

    try:
        import sentry_sdk
        from sentry_sdk.integrations.flask import FlaskIntegration
        from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

        sentry_sdk.init(
            dsn=dsn,
            integrations=[
                FlaskIntegration(transaction_style="url"),
                SqlalchemyIntegration(),
            ],
            environment=os.environ.get("FLASK_ENV", "production"),
            release=os.environ.get("APP_VERSION", "0.1.0"),
            traces_sample_rate=float(os.environ.get("SENTRY_TRACES_RATE", "0.1")),
            profiles_sample_rate=float(os.environ.get("SENTRY_PROFILES_RATE", "0.1")),
            send_default_pii=False,
            before_send=_sentry_before_send,
        )
        logger.info("Sentry initialized successfully")
        return True
    except ImportError:
        logger.warning("sentry-sdk not installed — pip install sentry-sdk[flask]")
        return False
    except Exception as e:
        logger.error(f"Sentry init failed: {e}")
        return False


def _sentry_before_send(event, hint):
    """Filter sensitive data before sending to Sentry."""
    if "request" in event and "data" in event["request"]:
        data = event["request"]["data"]
        if isinstance(data, dict):
            for key in ("password", "card_number", "xrp_wallet", "wallet_address",
                        "stripe_token", "secret", "fulfillment"):
                if key in data:
                    data[key] = "[REDACTED]"
    return event


# ============================================================
# Prometheus Metrics
# ============================================================

class PrometheusMetrics:
    """Lightweight Prometheus metrics collector (no external deps required)."""

    def __init__(self):
        self._counters = {}
        self._gauges = {}
        self._histograms = {}
        self._start_time = time.time()

    def inc(self, name, value=1, labels=None):
        key = self._key(name, labels)
        self._counters[key] = self._counters.get(key, 0) + value

    def set_gauge(self, name, value, labels=None):
        key = self._key(name, labels)
        self._gauges[key] = value

    def observe(self, name, value, labels=None):
        key = self._key(name, labels)
        if key not in self._histograms:
            self._histograms[key] = {"count": 0, "sum": 0.0}
        self._histograms[key]["count"] += 1
        self._histograms[key]["sum"] += value

    def _key(self, name, labels):
        if labels:
            label_str = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
            return f"{name}{{{label_str}}}"
        return name

    def export(self):
        """Export metrics in Prometheus text exposition format."""
        lines = []
        lines.append(f"# PHOENIX Metrics")
        lines.append(f"# Generated at {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}")
        lines.append("")

        # Uptime
        lines.append("# HELP phoenix_uptime_seconds Application uptime in seconds")
        lines.append("# TYPE phoenix_uptime_seconds gauge")
        lines.append(f"phoenix_uptime_seconds {time.time() - self._start_time:.1f}")
        lines.append("")

        # Counters
        for key, value in sorted(self._counters.items()):
            name = key.split("{")[0] if "{" in key else key
            lines.append(f"# TYPE {name} counter")
            lines.append(f"{key} {value}")

        if self._counters:
            lines.append("")

        # Gauges
        for key, value in sorted(self._gauges.items()):
            name = key.split("{")[0] if "{" in key else key
            lines.append(f"# TYPE {name} gauge")
            lines.append(f"{key} {value}")

        if self._gauges:
            lines.append("")

        # Histograms (simplified — count + sum)
        for key, data in sorted(self._histograms.items()):
            name = key.split("{")[0] if "{" in key else key
            lines.append(f"# TYPE {name} summary")
            lines.append(f"{key}_count {data['count']}")
            lines.append(f"{key}_sum {data['sum']:.4f}")

        lines.append("")
        return "\n".join(lines)


# Global metrics instance
metrics = PrometheusMetrics()


# ============================================================
# Request Tracking Middleware
# ============================================================

def init_request_tracking(app):
    """Add before/after request hooks for metrics collection."""
    from flask import request, g

    @app.before_request
    def _before_request():
        g.request_start_time = time.time()

    @app.after_request
    def _after_request(response):
        if hasattr(g, "request_start_time"):
            duration = time.time() - g.request_start_time
            endpoint = request.endpoint or "unknown"
            method = request.method
            status = response.status_code

            metrics.inc("phoenix_http_requests_total", labels={
                "method": method,
                "endpoint": endpoint,
                "status": str(status),
            })
            metrics.observe("phoenix_http_request_duration_seconds", duration, labels={
                "method": method,
                "endpoint": endpoint,
            })

            if status >= 500:
                metrics.inc("phoenix_http_errors_total", labels={
                    "method": method,
                    "endpoint": endpoint,
                    "status": str(status),
                })

        return response


# ============================================================
# Business Metrics Helpers
# ============================================================

def track_search(origin, destination, market):
    metrics.inc("phoenix_searches_total", labels={
        "origin": origin, "destination": destination, "market": market,
    })


def track_p2p_event(event, market="unknown"):
    metrics.inc("phoenix_p2p_events_total", labels={
        "event": event, "market": market,
    })


def track_payment(method, amount_usd, status):
    metrics.inc("phoenix_payments_total", labels={
        "method": method, "status": status,
    })
    if status == "verified":
        metrics.inc("phoenix_revenue_usd_total", value=amount_usd, labels={
            "method": method,
        })


def track_helper_online(country_code, online_count):
    metrics.set_gauge("phoenix_helpers_online", online_count, labels={
        "country": country_code,
    })


def track_escrow(action, amount_rlusd):
    metrics.inc("phoenix_escrow_events_total", labels={"action": action})
    metrics.inc("phoenix_escrow_volume_rlusd_total", value=amount_rlusd, labels={
        "action": action,
    })


# ============================================================
# Database Metrics (for /metrics endpoint)
# ============================================================

def collect_db_metrics(app):
    """Collect current database state metrics."""
    try:
        from models import User, Deal, HelperProfile, P2PTransaction, P2PEscrow

        with app.app_context():
            metrics.set_gauge("phoenix_users_total", User.query.count())
            metrics.set_gauge("phoenix_users_verified",
                              User.query.filter_by(is_verified=True).count())
            metrics.set_gauge("phoenix_deals_active",
                              Deal.query.filter_by(is_active=True).count())
            metrics.set_gauge("phoenix_helpers_total",
                              HelperProfile.query.count())
            metrics.set_gauge("phoenix_helpers_approved",
                              HelperProfile.query.filter_by(is_approved=True).count())
            metrics.set_gauge("phoenix_helpers_online_total",
                              HelperProfile.query.filter_by(is_online=True).count())
            metrics.set_gauge("phoenix_p2p_transactions_total",
                              P2PTransaction.query.count())
            for status in ["requested", "matched", "escrow_locked", "purchasing",
                           "confirmed", "completed", "failed", "cancelled"]:
                metrics.set_gauge("phoenix_p2p_by_status",
                                  P2PTransaction.query.filter_by(status=status).count(),
                                  labels={"status": status})
    except Exception as e:
        logger.error(f"Failed to collect DB metrics: {e}")


# ============================================================
# Metrics Endpoint
# ============================================================

def register_metrics_endpoint(app):
    """Register /metrics endpoint for Prometheus scraping."""
    from flask import Response

    @app.route("/metrics")
    def prometheus_metrics():
        collect_db_metrics(app)
        return Response(metrics.export(), mimetype="text/plain; charset=utf-8")


# ============================================================
# Init All Monitoring
# ============================================================

def init_monitoring(app):
    """Initialize all monitoring: Sentry + Prometheus + request tracking."""
    sentry_ok = init_sentry(app)
    init_request_tracking(app)
    register_metrics_endpoint(app)

    logger.info(
        f"Monitoring initialized — Sentry: {'enabled' if sentry_ok else 'disabled'}, "
        f"Prometheus: /metrics"
    )
    return {
        "sentry": sentry_ok,
        "prometheus": True,
    }
