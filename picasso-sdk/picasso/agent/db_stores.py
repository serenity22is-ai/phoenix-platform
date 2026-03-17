"""
Database-Backed Store Implementations — Drop-in replacements for file-based stores.

Each class mirrors the public API of its file-based counterpart:
    DBConfigStore   ↔  ConfigStore   (config.py)
    DBUsageTracker  ↔  UsageTracker  (billing.py)
    DBBillingManager ↔ BillingManager (billing.py)

Activated when STORAGE_BACKEND=db is set. File-based stores remain default.

MYSTES KYRIOS LLC — Confidential.
"""

import logging
import os
import time
from typing import Dict, List, Optional

from .db_models import db, Agency, UsageRecord, Subscription

logger = logging.getLogger(__name__)


# ============================================================================
# DB CONFIG STORE
# ============================================================================

class DBConfigStore:
    """
    Database-backed agency configuration store.

    Same public API as ConfigStore (config.py).
    """

    def get(self, key_hash: str):
        """Load agency config by API key hash."""
        from .config import AgencyConfig

        agency = Agency.query.filter_by(key_hash=key_hash).first()
        if not agency or not agency.config_json:
            return None
        try:
            return AgencyConfig.from_dict(agency.config_json)
        except Exception as e:
            logger.error("Failed to load config for %s: %s", key_hash[:8], e)
            return None

    def save(self, key_hash: str, config):
        """Save agency config."""
        agency = Agency.query.filter_by(key_hash=key_hash).first()
        config_data = config.to_dict(include_secrets=True)

        if agency:
            agency.config_json = config_data
            agency.company_name = getattr(config, "agency_name", "") or agency.company_name
            agency.tier = getattr(config, "tier", "tier2") or agency.tier
            agency.is_active = getattr(config, "active", True)
        else:
            agency = Agency(
                key_hash=key_hash,
                company_name=getattr(config, "agency_name", ""),
                tier=getattr(config, "tier", "tier2"),
                is_active=getattr(config, "active", True),
                config_json=config_data,
            )
            db.session.add(agency)

        db.session.commit()

    def delete(self, key_hash: str):
        """Delete agency config and related records."""
        UsageRecord.query.filter_by(key_hash=key_hash).delete()
        Subscription.query.filter_by(key_hash=key_hash).delete()
        agency = Agency.query.filter_by(key_hash=key_hash).first()
        if agency:
            db.session.delete(agency)
        db.session.commit()

    def list_all(self) -> list:
        """List all agency configs (without secrets)."""
        from .config import AgencyConfig

        agencies = Agency.query.filter_by(is_active=True).all()
        configs = []
        for agency in agencies:
            if agency.config_json:
                try:
                    cfg = AgencyConfig.from_dict(agency.config_json)
                    configs.append({
                        "key_hash": agency.key_hash,
                        **cfg.to_dict(include_secrets=False),
                    })
                except Exception:
                    pass
        return configs


# ============================================================================
# DB USAGE TRACKER
# ============================================================================

class DBUsageTracker:
    """
    Database-backed usage tracking.

    Same public API as UsageTracker (billing.py).
    """

    def _period_key(self, timestamp: float = None) -> str:
        """Current billing period key (YYYY-MM)."""
        t = time.gmtime(timestamp or time.time())
        return f"{t.tm_year:04d}-{t.tm_mon:02d}"

    def _get_or_create(self, key_hash: str, period: str = None) -> UsageRecord:
        """Get or create usage record for key_hash + period."""
        period = period or self._period_key()
        record = UsageRecord.query.filter_by(
            key_hash=key_hash, period=period
        ).first()
        if not record:
            record = UsageRecord(key_hash=key_hash, period=period)
            db.session.add(record)
            db.session.flush()
        return record

    def record_ai_request(self, key_hash: str, input_tokens: int = 0, output_tokens: int = 0):
        """Record an AI chat/assist request."""
        record = self._get_or_create(key_hash)
        record.ai_requests = (record.ai_requests or 0) + 1
        record.ai_input_tokens = (record.ai_input_tokens or 0) + input_tokens
        record.ai_output_tokens = (record.ai_output_tokens or 0) + output_tokens
        now = time.time()
        if not record.first_request_at:
            record.first_request_at = now
        record.last_request_at = now
        db.session.commit()

    def record_search(self, key_hash: str):
        """Record a flight search."""
        record = self._get_or_create(key_hash)
        record.searches = (record.searches or 0) + 1
        record.last_request_at = time.time()
        db.session.commit()

    def record_booking(self, key_hash: str):
        """Record a booking."""
        record = self._get_or_create(key_hash)
        record.bookings = (record.bookings or 0) + 1
        record.last_request_at = time.time()
        db.session.commit()

    def record_document(self, key_hash: str):
        """Record a document generation."""
        record = self._get_or_create(key_hash)
        record.documents = (record.documents or 0) + 1
        db.session.commit()

    def record_error(self, key_hash: str):
        """Record an API error."""
        record = self._get_or_create(key_hash)
        record.errors = (record.errors or 0) + 1
        db.session.commit()

    def get_usage(self, key_hash: str, period: str = None) -> dict:
        """Get usage for a specific period (default: current)."""
        period = period or self._period_key()
        record = UsageRecord.query.filter_by(
            key_hash=key_hash, period=period
        ).first()
        if record:
            return record.to_dict()
        return {
            "key_hash": key_hash,
            "period": period,
            "ai_requests": 0,
            "searches": 0,
            "bookings": 0,
            "documents": 0,
            "errors": 0,
            "ai_input_tokens": 0,
            "ai_output_tokens": 0,
            "first_request_at": None,
            "last_request_at": None,
        }

    def get_usage_history(self, key_hash: str, months: int = 6) -> List[dict]:
        """Get usage for the last N months."""
        history = []
        now = time.time()
        for i in range(months):
            t = now - (i * 30 * 24 * 3600)
            period = self._period_key(t)
            usage = self.get_usage(key_hash, period)
            if usage.get("first_request_at"):
                history.append(usage)
        return history

    def check_limit(self, key_hash: str, counter: str, limit: int) -> dict:
        """Check if an agency has exceeded a usage limit."""
        if limit <= 0:
            return {"allowed": True, "current": 0, "limit": 0, "remaining": -1}

        usage = self.get_usage(key_hash)
        current = usage.get(counter, 0)
        return {
            "allowed": current < limit,
            "current": current,
            "limit": limit,
            "remaining": max(0, limit - current),
        }


# ============================================================================
# DB BILLING MANAGER
# ============================================================================

class DBBillingManager:
    """
    Database-backed billing/subscription manager.

    Same public API as BillingManager (billing.py) for subscription state.
    Wraps DBUsageTracker for usage queries.
    """

    def __init__(self, usage_tracker: DBUsageTracker, stripe_api_key: str = "", plans=None):
        from .billing import PLANS
        self.usage = usage_tracker
        self.plans = plans or PLANS
        self._stripe = None
        self._stripe_key = stripe_api_key or os.environ.get("STRIPE_SECRET_KEY", "")

    @property
    def stripe(self):
        """Lazy-load Stripe SDK."""
        if self._stripe is None and self._stripe_key:
            try:
                import stripe
                stripe.api_key = self._stripe_key
                self._stripe = stripe
            except ImportError:
                logger.warning("Stripe SDK not installed — billing in offline mode")
        return self._stripe

    def _load_subscription(self, key_hash: str) -> dict:
        sub = Subscription.query.filter_by(key_hash=key_hash).first()
        return sub.to_dict() if sub else {}

    def _save_subscription(self, key_hash: str, data: dict):
        sub = Subscription.query.filter_by(key_hash=key_hash).first()
        if sub:
            for k, v in data.items():
                if hasattr(sub, k):
                    setattr(sub, k, v)
        else:
            sub = Subscription(key_hash=key_hash, **{
                k: v for k, v in data.items()
                if hasattr(Subscription, k) and k != "key_hash"
            })
            db.session.add(sub)
        db.session.commit()

    def get_subscription(self, key_hash: str) -> dict:
        """Get subscription details for an agency."""
        sub_data = self._load_subscription(key_hash)
        if not sub_data:
            return {
                "status": "none",
                "plan_id": None,
                "message": "No active subscription",
            }

        plan = self.plans.get(sub_data.get("plan_id", ""))
        usage = self.usage.get_usage(key_hash)

        result = {
            "status": sub_data.get("status", "unknown"),
            "plan_id": sub_data.get("plan_id"),
            "plan_name": plan.name if plan else "Unknown",
            "stripe_customer_id": sub_data.get("stripe_customer_id"),
            "stripe_subscription_id": sub_data.get("stripe_subscription_id"),
            "current_period_start": sub_data.get("current_period_start"),
            "current_period_end": sub_data.get("current_period_end"),
            "created_at": None,
        }

        if plan:
            limits = plan.limits
            result["usage"] = {
                "ai_requests": {
                    "used": usage.get("ai_requests", 0),
                    "limit": limits.ai_requests_per_month,
                    "remaining": max(0, limits.ai_requests_per_month - usage.get("ai_requests", 0))
                    if limits.ai_requests_per_month > 0 else -1,
                },
                "searches": {
                    "used": usage.get("searches", 0),
                    "limit": limits.searches_per_month,
                },
                "bookings": {
                    "used": usage.get("bookings", 0),
                    "limit": limits.bookings_per_month,
                },
            }
            result["overage_rate"] = limits.overage_rate_usd

        return result

    def create_subscription(
        self,
        key_hash: str,
        plan_id: str,
        email: str = "",
        agency_name: str = "",
        stripe_payment_method: str = "",
        pricing_level: str = "retail",
        committed_agencies: int = 0,
    ) -> dict:
        """Create a new subscription for an agency."""
        from .billing import get_partner_rate

        if pricing_level == "partner":
            if committed_agencies <= 0:
                return {"success": False, "error": "Partner deals require committed_agencies > 0"}
            rate_info = get_partner_rate(committed_agencies)
            now = time.time()
            sub_data = {
                "plan_id": "partner_enterprise",
                "pricing_level": "partner",
                "status": "active",
                "email": email,
                "agency_name": agency_name,
                "committed_agencies": committed_agencies,
                "per_agency_rate": rate_info["per_agency_monthly"],
                "tier_label": rate_info["tier_label"],
                "current_period_start": now,
                "current_period_end": now + (30 * 24 * 3600),
            }
            self._save_subscription(key_hash, sub_data)
            return {
                "success": True,
                "plan_id": "partner_enterprise",
                "pricing_level": "partner",
                "committed_agencies": committed_agencies,
                "per_agency_rate": rate_info["per_agency_monthly"],
                "monthly_total": rate_info["monthly_total"],
                "tier_label": rate_info["tier_label"],
            }

        plan = self.plans.get(plan_id)
        if not plan:
            return {"success": False, "error": f"Unknown plan: {plan_id}"}

        now = time.time()
        sub_data = {
            "plan_id": plan_id,
            "pricing_level": pricing_level,
            "status": "active",
            "email": email,
            "agency_name": agency_name,
            "current_period_start": now,
            "current_period_end": now + (30 * 24 * 3600),
        }

        # Stripe integration (if configured)
        if self.stripe and stripe_payment_method:
            try:
                customer = self.stripe.Customer.create(
                    email=email,
                    name=agency_name,
                    payment_method=stripe_payment_method,
                    invoice_settings={"default_payment_method": stripe_payment_method},
                    metadata={"key_hash": key_hash, "plan_id": plan_id},
                )
                subscription = self.stripe.Subscription.create(
                    customer=customer.id,
                    items=[{"price": plan.stripe_price_id}],
                    metadata={"key_hash": key_hash},
                )
                sub_data["stripe_customer_id"] = customer.id
                sub_data["stripe_subscription_id"] = subscription.id
            except Exception as e:
                logger.error("Stripe subscription creation failed: %s", e)
                return {"success": False, "error": f"Payment failed: {e}"}

        self._save_subscription(key_hash, sub_data)
        return {"success": True, **sub_data}

    def cancel_subscription(self, key_hash: str, reason: str = "") -> dict:
        """Cancel an agency's subscription."""
        sub_data = self._load_subscription(key_hash)
        if not sub_data or sub_data.get("status") == "none":
            return {"success": False, "error": "No active subscription"}

        sub_data["status"] = "canceled"
        self._save_subscription(key_hash, sub_data)
        return {"success": True, "status": "canceled"}

    def update_subscription_status(self, key_hash: str, status: str, **kwargs):
        """Update subscription status (used by Stripe webhooks)."""
        sub_data = self._load_subscription(key_hash)
        if not sub_data:
            sub_data = {"key_hash": key_hash}
        sub_data["status"] = status
        for k, v in kwargs.items():
            sub_data[k] = v
        self._save_subscription(key_hash, sub_data)


def get_storage_backend():
    """Determine which storage backend to use based on STORAGE_BACKEND env var."""
    return os.environ.get("STORAGE_BACKEND", "file")


def create_stores(app_config: dict = None):
    """
    Factory function to create the appropriate stores based on STORAGE_BACKEND.

    Returns:
        (config_store, usage_tracker, billing_manager)
    """
    app_config = app_config or {}
    backend = get_storage_backend()

    if backend == "db":
        config_store = DBConfigStore()
        usage_tracker = DBUsageTracker()
        stripe_key = app_config.get("STRIPE_SECRET_KEY") or os.environ.get("STRIPE_SECRET_KEY", "")
        billing_manager = DBBillingManager(
            usage_tracker=usage_tracker,
            stripe_api_key=stripe_key,
        )
        logger.info("Storage backend: PostgreSQL (db)")
    else:
        from .config import ConfigStore
        from .billing import BillingManager, UsageTracker

        config_dir = app_config.get("CONFIG_DIR", ".agency_configs")
        data_dir = os.path.join(config_dir, ".data")
        config_store = ConfigStore(config_dir)
        usage_tracker = UsageTracker(os.path.join(data_dir, "usage"))
        stripe_key = app_config.get("STRIPE_SECRET_KEY") or os.environ.get("STRIPE_SECRET_KEY", "")
        billing_manager = BillingManager(
            usage_tracker=usage_tracker,
            stripe_api_key=stripe_key,
            data_dir=os.path.join(data_dir, "billing"),
        )
        logger.info("Storage backend: file-based (default)")

    return config_store, usage_tracker, billing_manager
