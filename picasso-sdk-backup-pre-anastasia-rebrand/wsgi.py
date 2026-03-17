"""
ANASTASIA API — WSGI entry point for production deployment.

Usage:
    gunicorn --config gunicorn.conf.py wsgi:app

Environment variables (required):
    ANTHROPIC_API_KEY      — Claude API key for AI agent
    ANASTASIA_MASTER_KEY   — Master admin key for registering agencies

Environment variables (optional):
    AGENT_MODEL            — Claude model ID (default: claude-haiku-4-5-20251001)
    STRIPE_SECRET_KEY      — Stripe API key for billing
    STRIPE_WEBHOOK_SECRET  — Stripe webhook signing secret
    CONFIG_DIR             — Agency config storage dir (default: .agency_configs)
    ADMIN_AUTH_TOKEN_HASH   — Admin auth token hash
    ENABLE_DAEMON          — Enable auto-heal daemon (default: true)
    DAEMON_INTERVAL        — Daemon check interval in seconds (default: 60)

MYSTES KYRIOS LLC — Confidential.
"""

import os
import logging

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

from picasso.agent.api import create_app

config = {
    "ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY", ""),
    "AGENT_MODEL": os.environ.get("AGENT_MODEL", "claude-haiku-4-5-20251001"),
    "MASTER_KEY": os.environ.get("ANASTASIA_MASTER_KEY", ""),
    "CONFIG_DIR": os.environ.get("CONFIG_DIR", ".agency_configs"),
    "STRIPE_SECRET_KEY": os.environ.get("STRIPE_SECRET_KEY", ""),
    "STRIPE_WEBHOOK_SECRET": os.environ.get("STRIPE_WEBHOOK_SECRET", ""),
    "ADMIN_AUTH_TOKEN_HASH": os.environ.get("ADMIN_AUTH_TOKEN_HASH", ""),
    "ENABLE_DAEMON": os.environ.get("ENABLE_DAEMON", "true").lower() == "true",
    "DAEMON_INTERVAL": int(os.environ.get("DAEMON_INTERVAL", "60")),
    "MAX_SESSIONS_PER_KEY": int(os.environ.get("MAX_SESSIONS_PER_KEY", "50")),
    "SESSION_TTL_SECONDS": int(os.environ.get("SESSION_TTL_SECONDS", "3600")),
}

app = create_app(config)
