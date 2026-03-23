#!/usr/bin/env python3
"""
MYSTES Production Environment Validator — Build #189

Checks all required configuration, credentials, and connectivity
for a production deployment. Run before going live.

Usage:
    python3 scripts/validate_env.py

MYSTES KYRIOS LLC — Confidential.
"""

import os
import sys

# ANSI colors for terminal output
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BOLD = "\033[1m"
RESET = "\033[0m"

results = {"pass": 0, "fail": 0, "warn": 0}


def check(name, condition, required=True):
    """Record a check result."""
    if condition:
        print(f"  {GREEN}PASS{RESET}  {name}")
        results["pass"] += 1
    elif required:
        print(f"  {RED}FAIL{RESET}  {name}")
        results["fail"] += 1
    else:
        print(f"  {YELLOW}WARN{RESET}  {name}")
        results["warn"] += 1


def main():
    print(f"\n{BOLD}MYSTES Production Environment Validator{RESET}")
    print("=" * 50)

    # --- Core Configuration ---
    print(f"\n{BOLD}[Core Configuration]{RESET}")

    secret = os.getenv("SECRET_KEY", "")
    check("SECRET_KEY is set", bool(secret))
    check("SECRET_KEY is not default", secret not in ("", "dev-secret", "test-secret-key-ci", "change-me"))

    flask_env = os.getenv("FLASK_ENV", "")
    check("FLASK_ENV = production", flask_env == "production", required=False)

    db_url = os.getenv("DATABASE_URL", "")
    check("DATABASE_URL is set", bool(db_url))
    check("DATABASE_URL is PostgreSQL (not SQLite)",
          db_url.startswith("postgresql://") or db_url.startswith("postgres://"),
          required=True)

    # --- Payment Configuration ---
    print(f"\n{BOLD}[Payment (Stripe)]{RESET}")

    stripe_key = os.getenv("STRIPE_SECRET_KEY", "")
    check("STRIPE_SECRET_KEY is set", bool(stripe_key))
    check("STRIPE_SECRET_KEY is live (sk_live_)",
          stripe_key.startswith("sk_live_"), required=False)

    stripe_pub = os.getenv("STRIPE_PUBLISHABLE_KEY", "")
    check("STRIPE_PUBLISHABLE_KEY is set", bool(stripe_pub))

    stripe_wh = os.getenv("STRIPE_WEBHOOK_SECRET", "")
    check("STRIPE_WEBHOOK_SECRET is set", bool(stripe_wh))

    # --- Flight API Credentials ---
    print(f"\n{BOLD}[Flight APIs]{RESET}")

    picasso_email = os.getenv("PICASSO_EMAIL", "")
    picasso_pass = os.getenv("PICASSO_PASSWORD", "")
    picasso_token = os.getenv("PICASSO_TOKEN", "")
    check("Picasso credentials present (email+password or token)",
          bool(picasso_email and picasso_pass) or bool(picasso_token))

    duffel_token = os.getenv("DUFFEL_ACCESS_TOKEN", "")
    check("DUFFEL_ACCESS_TOKEN is set", bool(duffel_token))
    check("Duffel token is live (not test_)",
          not duffel_token.startswith("duffel_test_"), required=False)

    # --- Hotel API ---
    print(f"\n{BOLD}[Hotel API]{RESET}")

    liteapi_key = os.getenv("LITEAPI_KEY", "")
    check("LITEAPI_KEY is set", bool(liteapi_key), required=False)

    # --- Optional Services ---
    print(f"\n{BOLD}[Optional Services]{RESET}")

    redis_url = os.getenv("REDIS_URL", "")
    check("REDIS_URL is set (rate limiting)", bool(redis_url), required=False)

    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
    check("ANTHROPIC_API_KEY is set (AI chat)", bool(anthropic_key), required=False)

    render_key = os.getenv("RENDER_API_KEY", "")
    check("RENDER_API_KEY is set (APAi provisioning)", bool(render_key), required=False)

    # --- Connectivity ---
    print(f"\n{BOLD}[Connectivity]{RESET}")

    # Database
    if db_url:
        try:
            import sqlalchemy
            engine = sqlalchemy.create_engine(db_url, pool_pre_ping=True)
            with engine.connect() as conn:
                result = conn.execute(sqlalchemy.text("SELECT 1"))
                result.fetchone()
            check("Database connection", True)

            # Count tables
            inspector = sqlalchemy.inspect(engine)
            tables = inspector.get_table_names()
            check(f"Database has tables ({len(tables)} found)", len(tables) > 0)
            engine.dispose()
        except Exception as e:
            check(f"Database connection ({e})", False)
    else:
        check("Database connection (no URL)", False)

    # Redis
    if redis_url:
        try:
            import redis
            r = redis.from_url(redis_url, socket_timeout=5)
            r.ping()
            check("Redis connection", True)
        except Exception as e:
            check(f"Redis connection ({e})", False, required=False)
    else:
        check("Redis connection (not configured)", False, required=False)

    # --- Summary ---
    print(f"\n{'=' * 50}")
    total = results["pass"] + results["fail"] + results["warn"]
    print(f"{BOLD}Results:{RESET} {GREEN}{results['pass']} passed{RESET}, "
          f"{RED}{results['fail']} failed{RESET}, "
          f"{YELLOW}{results['warn']} warnings{RESET} "
          f"({total} total)")

    if results["fail"] == 0:
        print(f"\n{GREEN}{BOLD}READY FOR PRODUCTION{RESET}")
        return 0
    else:
        print(f"\n{RED}{BOLD}NOT READY — fix {results['fail']} failing check(s){RESET}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
