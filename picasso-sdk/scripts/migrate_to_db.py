#!/usr/bin/env python3
"""
One-Time Migration: File-based JSON → PostgreSQL

Reads all existing JSON data from .agency_configs/, .usage_data/, .billing_data/
and inserts into the corresponding database tables. Idempotent — skips records
that already exist.

Usage:
    # Set env vars first:
    export STORAGE_BACKEND=db
    export DATABASE_URL=postgresql://user:pass@host:5432/dbname

    # Run migration:
    python scripts/migrate_to_db.py

MYSTES KYRIOS LLC — Confidential.
"""

import json
import logging
import os
import sys

# Add parent directory to path so we can import from the SDK
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def migrate():
    """Run the full migration."""
    from flask import Flask
    from picasso.agent.db_models import db, init_db, Agency, UsageRecord, Subscription

    app = Flask(__name__)
    init_db(app)

    with app.app_context():
        stats = {"agencies": 0, "usage": 0, "subscriptions": 0, "skipped": 0}

        # --- Migrate agency configs ---
        config_dir = os.environ.get("CONFIG_DIR", ".agency_configs")
        if os.path.exists(config_dir):
            for fname in os.listdir(config_dir):
                if not fname.endswith(".json"):
                    continue
                key_hash = fname[:-5]

                # Skip if already exists
                if Agency.query.filter_by(key_hash=key_hash).first():
                    stats["skipped"] += 1
                    continue

                filepath = os.path.join(config_dir, fname)
                try:
                    with open(filepath) as f:
                        config_data = json.load(f)

                    agency = Agency(
                        key_hash=key_hash,
                        company_name=config_data.get("agency_name", ""),
                        contact_email=config_data.get("contact_email", ""),
                        tier=config_data.get("tier", "tier2"),
                        is_active=config_data.get("active", True),
                        config_json=config_data,
                    )
                    db.session.add(agency)
                    stats["agencies"] += 1
                    logger.info("Migrated agency: %s (%s)", key_hash[:8], config_data.get("agency_name", "?"))
                except Exception as e:
                    logger.error("Failed to migrate agency %s: %s", fname, e)

        # --- Migrate usage data ---
        usage_dir = os.environ.get("USAGE_DIR", os.path.join(config_dir, ".data", "usage"))
        if not os.path.exists(usage_dir):
            usage_dir = ".usage_data"
        if os.path.exists(usage_dir):
            for fname in os.listdir(usage_dir):
                if not fname.endswith(".json"):
                    continue

                # Parse filename: {key_hash}_{YYYY-MM}.json
                parts = fname[:-5].rsplit("_", 1)
                if len(parts) != 2:
                    continue
                key_hash, period = parts

                if UsageRecord.query.filter_by(key_hash=key_hash, period=period).first():
                    stats["skipped"] += 1
                    continue

                filepath = os.path.join(usage_dir, fname)
                try:
                    with open(filepath) as f:
                        data = json.load(f)

                    record = UsageRecord(
                        key_hash=key_hash,
                        period=period,
                        ai_requests=data.get("ai_requests", 0),
                        searches=data.get("searches", 0),
                        bookings=data.get("bookings", 0),
                        documents=data.get("documents", 0),
                        errors=data.get("errors", 0),
                        ai_input_tokens=data.get("ai_input_tokens", 0),
                        ai_output_tokens=data.get("ai_output_tokens", 0),
                        first_request_at=data.get("first_request_at"),
                        last_request_at=data.get("last_request_at"),
                    )
                    db.session.add(record)
                    stats["usage"] += 1
                except Exception as e:
                    logger.error("Failed to migrate usage %s: %s", fname, e)

        # --- Migrate billing/subscription data ---
        billing_dir = os.environ.get("BILLING_DIR", os.path.join(config_dir, ".data", "billing"))
        if not os.path.exists(billing_dir):
            billing_dir = ".billing_data"
        if os.path.exists(billing_dir):
            for fname in os.listdir(billing_dir):
                if not fname.startswith("sub_") or not fname.endswith(".json"):
                    continue

                key_hash = fname[4:-5]  # Remove "sub_" prefix and ".json" suffix

                if Subscription.query.filter_by(key_hash=key_hash).first():
                    stats["skipped"] += 1
                    continue

                filepath = os.path.join(billing_dir, fname)
                try:
                    with open(filepath) as f:
                        data = json.load(f)

                    sub = Subscription(
                        key_hash=key_hash,
                        plan_id=data.get("plan_id", "pro"),
                        pricing_level=data.get("pricing_level", "retail"),
                        status=data.get("status", "active"),
                        email=data.get("email", ""),
                        agency_name=data.get("agency_name", ""),
                        stripe_customer_id=data.get("stripe_customer_id"),
                        stripe_subscription_id=data.get("stripe_subscription_id"),
                        committed_agencies=data.get("committed_agencies", 0),
                        per_agency_rate=data.get("per_agency_rate"),
                        tier_label=data.get("tier_label"),
                        current_period_start=data.get("current_period_start"),
                        current_period_end=data.get("current_period_end"),
                    )
                    db.session.add(sub)
                    stats["subscriptions"] += 1
                    logger.info("Migrated subscription: %s (%s)", key_hash[:8], data.get("plan_id", "?"))
                except Exception as e:
                    logger.error("Failed to migrate subscription %s: %s", fname, e)

        db.session.commit()

        logger.info("=" * 50)
        logger.info("Migration complete!")
        logger.info("  Agencies:      %d migrated", stats["agencies"])
        logger.info("  Usage records: %d migrated", stats["usage"])
        logger.info("  Subscriptions: %d migrated", stats["subscriptions"])
        logger.info("  Skipped:       %d (already in DB)", stats["skipped"])


if __name__ == "__main__":
    if not os.environ.get("DATABASE_URL"):
        logger.error("DATABASE_URL env var required. Set it before running migration.")
        sys.exit(1)
    migrate()
