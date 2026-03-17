"""
Billing — Stripe subscription management with usage metering.

Pricing channels:
    Retail (direct OTA):
        Starter $249/mo, Pro $599/mo, Enterprise $1,499/mo
    Wholesale (consolidator resale):
        Starter $99/mo, Pro $249/mo, Enterprise $599/mo
    Partner (AERTiCKET platform license — volume-committed per-agency):
        1-10,000 agencies: $299/mo per agency
        10,001-50,000:     $199/mo per agency (blended)
        50,001-100,000:    $149/mo per agency (blended)
        100,001+:          $99/mo per agency (blended)
        + $250K/yr platform integration fee
        All agencies get full Enterprise feature set.

Usage metering:
    - AI requests (chat + assist messages) counted per billing period
    - Overage charged per-request past tier threshold
    - Flight searches, bookings, and document generations tracked but not billed separately

MYSTES KYRIOS LLC — Confidential.
"""

import json
import logging
import os
import time
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, List

logger = logging.getLogger(__name__)


# ============================================================================
# PLAN DEFINITIONS
# ============================================================================

@dataclass
class PlanLimits:
    """Usage limits for a billing plan."""
    ai_requests_per_month: int = 0         # 0 = unlimited
    searches_per_month: int = 0
    bookings_per_month: int = 0
    sessions_per_key: int = 10
    overage_rate_usd: float = 0.01         # Per AI request over limit


@dataclass
class BillingPlan:
    """Billing plan definition."""
    plan_id: str = ""
    name: str = ""
    tier: str = "starter"                  # starter, pro, enterprise
    price_monthly_usd: float = 0.0
    wholesale_monthly_usd: float = 0.0
    limits: PlanLimits = field(default_factory=PlanLimits)
    features: List[str] = field(default_factory=list)
    stripe_price_id: str = ""              # Stripe Price object ID
    stripe_product_id: str = ""            # Stripe Product object ID
    active: bool = True

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "BillingPlan":
        limits = data.pop("limits", {})
        plan = cls(**{k: v for k, v in data.items() if k != "limits"})
        if limits:
            plan.limits = PlanLimits(**limits)
        return plan


# Default plans — can be overridden via config
PLANS = {
    "starter": BillingPlan(
        plan_id="starter",
        name="Starter",
        tier="starter",
        price_monthly_usd=249.00,
        wholesale_monthly_usd=99.00,
        limits=PlanLimits(
            ai_requests_per_month=2000,
            searches_per_month=5000,
            bookings_per_month=100,
            sessions_per_key=10,
            overage_rate_usd=0.01,
        ),
        features=[
            "ai_chat",
            "structured_search",
            "config_dashboard",
            "airport_search",
            "fare_rules",
            "seatmap",
        ],
    ),
    "pro": BillingPlan(
        plan_id="pro",
        name="Pro",
        tier="pro",
        price_monthly_usd=599.00,
        wholesale_monthly_usd=249.00,
        limits=PlanLimits(
            ai_requests_per_month=10000,
            searches_per_month=25000,
            bookings_per_month=1000,
            sessions_per_key=50,
            overage_rate_usd=0.008,
        ),
        features=[
            "ai_chat",
            "structured_search",
            "config_dashboard",
            "airport_search",
            "fare_rules",
            "seatmap",
            "booking_enabled",
            "booking_management",
            "document_generation",
            "auto_heal_daemon",
            "audit_trail",
            "extras_discovery",
        ],
    ),
    "enterprise": BillingPlan(
        plan_id="enterprise",
        name="Enterprise",
        tier="enterprise",
        price_monthly_usd=1499.00,
        wholesale_monthly_usd=599.00,
        limits=PlanLimits(
            ai_requests_per_month=50000,
            searches_per_month=0,       # unlimited
            bookings_per_month=0,       # unlimited
            sessions_per_key=200,
            overage_rate_usd=0.005,
        ),
        features=[
            "ai_chat",
            "structured_search",
            "config_dashboard",
            "airport_search",
            "fare_rules",
            "seatmap",
            "booking_enabled",
            "booking_management",
            "document_generation",
            "auto_heal_daemon",
            "audit_trail",
            "extras_discovery",
            "consumer_ui",
            "white_label",
            "custom_branding",
            "webhooks",
            "priority_support",
        ],
    ),
}


# ============================================================================
# PARTNER VOLUME PRICING (AERTiCKET / platform license deals)
# ============================================================================

@dataclass
class PartnerVolumeTier:
    """Volume-committed pricing tier for platform partners."""
    min_agencies: int = 0
    max_agencies: int = 0              # 0 = unlimited
    per_agency_monthly_usd: float = 0.0
    overage_rate_usd: float = 0.005
    label: str = ""


# Blended rate — once a partner crosses a threshold, ALL agencies
# drop to that tier's rate. Incentivizes committing big and fast.
PARTNER_VOLUME_TIERS = [
    PartnerVolumeTier(
        min_agencies=1,
        max_agencies=10000,
        per_agency_monthly_usd=299.00,
        overage_rate_usd=0.005,
        label="Launch",
    ),
    PartnerVolumeTier(
        min_agencies=10001,
        max_agencies=50000,
        per_agency_monthly_usd=199.00,
        overage_rate_usd=0.004,
        label="Scale",
    ),
    PartnerVolumeTier(
        min_agencies=50001,
        max_agencies=100000,
        per_agency_monthly_usd=149.00,
        overage_rate_usd=0.003,
        label="Network",
    ),
    PartnerVolumeTier(
        min_agencies=100001,
        max_agencies=0,
        per_agency_monthly_usd=99.00,
        overage_rate_usd=0.002,
        label="Global",
    ),
]

# Annual platform integration fee for partner deals
PARTNER_PLATFORM_FEE_ANNUAL_USD = 250_000.00

# Partner agencies get full Enterprise feature set
PARTNER_FEATURES = PLANS["enterprise"].features.copy()

# Partner AI request limits — per agency, generous (they're paying per-agency)
PARTNER_LIMITS = PlanLimits(
    ai_requests_per_month=0,        # unlimited per agency (metered for overage)
    searches_per_month=0,           # unlimited
    bookings_per_month=0,           # unlimited
    sessions_per_key=500,
    overage_rate_usd=0.003,
)


def get_partner_rate(total_agencies: int) -> dict:
    """
    Calculate the per-agency rate for a partner based on committed volume.

    Blended pricing — crossing a threshold drops ALL agencies to that rate.

    Args:
        total_agencies: Total committed agency count across all subsidiaries.

    Returns:
        {
            "tier_label": str,
            "per_agency_monthly": float,
            "total_monthly": float,
            "total_annual": float,
            "platform_fee_annual": float,
            "overage_rate": float,
            "grand_total_annual": float,
        }
    """
    tier = PARTNER_VOLUME_TIERS[0]  # default to first tier
    for t in PARTNER_VOLUME_TIERS:
        if total_agencies >= t.min_agencies:
            tier = t
        else:
            break

    monthly = tier.per_agency_monthly_usd * total_agencies
    annual = monthly * 12
    grand_total = annual + PARTNER_PLATFORM_FEE_ANNUAL_USD

    return {
        "tier_label": tier.label,
        "per_agency_monthly": tier.per_agency_monthly_usd,
        "total_agencies": total_agencies,
        "total_monthly": round(monthly, 2),
        "total_annual": round(annual, 2),
        "platform_fee_annual": PARTNER_PLATFORM_FEE_ANNUAL_USD,
        "overage_rate": tier.overage_rate_usd,
        "grand_total_annual": round(grand_total, 2),
    }


def get_partner_quote(subsidiaries: Dict[str, int]) -> dict:
    """
    Generate a full partner pricing quote for a consolidator group.

    Args:
        subsidiaries: Dict mapping subsidiary name to agency count.
            Example: {"Servivuelos": 11500, "Picasso DE": 8000, ...}

    Returns:
        Full quote with per-subsidiary breakdown and totals.
    """
    total = sum(subsidiaries.values())
    rate_info = get_partner_rate(total)

    breakdown = []
    for name, count in sorted(subsidiaries.items(), key=lambda x: -x[1]):
        breakdown.append({
            "subsidiary": name,
            "agencies": count,
            "monthly_cost": round(count * rate_info["per_agency_monthly"], 2),
        })

    return {
        "total_agencies": total,
        "rate": rate_info,
        "subsidiaries": breakdown,
        "summary": (
            f"{total:,} agencies across {len(subsidiaries)} subsidiaries "
            f"@ ${rate_info['per_agency_monthly']}/agency/mo "
            f"({rate_info['tier_label']} tier) = "
            f"${rate_info['total_monthly']:,.2f}/mo "
            f"(${rate_info['grand_total_annual']:,.2f}/yr incl. platform fee)"
        ),
    }


# ============================================================================
# USAGE TRACKER
# ============================================================================

class UsageTracker:
    """
    Track API usage per agency per billing period.

    File-based storage — one JSON file per agency per month.
    Format: {agency_key_hash}_{YYYY-MM}.json

    Thread-safe via atomic writes (write to temp, rename).
    """

    def __init__(self, data_dir: str = ".usage_data"):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)

    def _period_key(self, timestamp: float = None) -> str:
        """Current billing period key (YYYY-MM)."""
        t = time.gmtime(timestamp or time.time())
        return f"{t.tm_year:04d}-{t.tm_mon:02d}"

    def _path(self, key_hash: str, period: str = None) -> str:
        period = period or self._period_key()
        return os.path.join(self.data_dir, f"{key_hash}_{period}.json")

    def _load(self, key_hash: str, period: str = None) -> dict:
        path = self._path(key_hash, period)
        if os.path.exists(path):
            try:
                with open(path) as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                pass
        return {
            "key_hash": key_hash,
            "period": period or self._period_key(),
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

    def _save(self, key_hash: str, data: dict, period: str = None):
        path = self._path(key_hash, period)
        tmp_path = path + ".tmp"
        with open(tmp_path, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, path)

    def record_ai_request(
        self,
        key_hash: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ):
        """Record an AI chat/assist request."""
        period = self._period_key()
        data = self._load(key_hash, period)
        data["ai_requests"] += 1
        data["ai_input_tokens"] += input_tokens
        data["ai_output_tokens"] += output_tokens
        now = time.time()
        if not data["first_request_at"]:
            data["first_request_at"] = now
        data["last_request_at"] = now
        self._save(key_hash, data, period)

    def record_search(self, key_hash: str):
        """Record a flight search."""
        period = self._period_key()
        data = self._load(key_hash, period)
        data["searches"] += 1
        data["last_request_at"] = time.time()
        self._save(key_hash, data, period)

    def record_booking(self, key_hash: str):
        """Record a booking."""
        period = self._period_key()
        data = self._load(key_hash, period)
        data["bookings"] += 1
        data["last_request_at"] = time.time()
        self._save(key_hash, data, period)

    def record_document(self, key_hash: str):
        """Record a document generation."""
        period = self._period_key()
        data = self._load(key_hash, period)
        data["documents"] += 1
        self._save(key_hash, data, period)

    def record_error(self, key_hash: str):
        """Record an API error."""
        period = self._period_key()
        data = self._load(key_hash, period)
        data["errors"] += 1
        self._save(key_hash, data, period)

    def get_usage(self, key_hash: str, period: str = None) -> dict:
        """Get usage for a specific period (default: current)."""
        return self._load(key_hash, period or self._period_key())

    def get_usage_history(self, key_hash: str, months: int = 6) -> List[dict]:
        """Get usage for the last N months."""
        history = []
        now = time.time()
        for i in range(months):
            t = now - (i * 30 * 24 * 3600)
            period = self._period_key(t)
            usage = self._load(key_hash, period)
            if usage.get("first_request_at"):
                history.append(usage)
        return history

    def check_limit(
        self,
        key_hash: str,
        counter: str,
        limit: int,
    ) -> dict:
        """
        Check if an agency has exceeded a usage limit.

        Returns:
            {"allowed": bool, "current": int, "limit": int, "remaining": int}
        """
        if limit <= 0:
            return {"allowed": True, "current": 0, "limit": 0, "remaining": -1}

        usage = self._load(key_hash)
        current = usage.get(counter, 0)
        return {
            "allowed": current < limit,
            "current": current,
            "limit": limit,
            "remaining": max(0, limit - current),
        }


# ============================================================================
# BILLING MANAGER
# ============================================================================

class BillingManager:
    """
    Manages agency subscriptions, usage limits, and Stripe integration.

    Stripe integration is optional — works without it for development/testing.
    When Stripe is configured, subscriptions are synced bidirectionally:
        - Agency signup → create Stripe customer + subscription
        - Stripe webhook → update agency status
        - Usage metering → Stripe usage records (for overage billing)
    """

    def __init__(
        self,
        usage_tracker: UsageTracker,
        stripe_api_key: str = "",
        plans: Dict[str, BillingPlan] = None,
        data_dir: str = ".billing_data",
    ):
        self.usage = usage_tracker
        self.plans = plans or PLANS
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)

        # Stripe client (lazy init)
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
                logger.info("Stripe SDK initialized")
            except ImportError:
                logger.warning("Stripe SDK not installed — billing in offline mode")
        return self._stripe

    # --- Subscription State (file-based) ---

    def _sub_path(self, key_hash: str) -> str:
        return os.path.join(self.data_dir, f"sub_{key_hash}.json")

    def _load_subscription(self, key_hash: str) -> dict:
        path = self._sub_path(key_hash)
        if os.path.exists(path):
            try:
                with open(path) as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                pass
        return {}

    def _save_subscription(self, key_hash: str, data: dict):
        path = self._sub_path(key_hash)
        with open(path, "w") as f:
            json.dump(data, f, indent=2)

    def get_subscription(self, key_hash: str) -> dict:
        """Get subscription details for an agency."""
        sub = self._load_subscription(key_hash)
        if not sub:
            return {
                "status": "none",
                "plan_id": None,
                "message": "No active subscription",
            }

        plan = self.plans.get(sub.get("plan_id", ""))
        usage = self.usage.get_usage(key_hash)

        result = {
            "status": sub.get("status", "unknown"),
            "plan_id": sub.get("plan_id"),
            "plan_name": plan.name if plan else "Unknown",
            "stripe_customer_id": sub.get("stripe_customer_id"),
            "stripe_subscription_id": sub.get("stripe_subscription_id"),
            "current_period_start": sub.get("current_period_start"),
            "current_period_end": sub.get("current_period_end"),
            "created_at": sub.get("created_at"),
        }

        # Add usage vs limits
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
        """
        Create a new subscription for an agency or partner.

        If Stripe is configured, creates a Stripe customer + subscription.
        Otherwise, stores subscription state locally (dev/testing mode).

        Args:
            key_hash: Agency API key hash
            plan_id: Plan ID (starter, pro, enterprise, or partner_enterprise)
            email: Billing email
            agency_name: Agency name for Stripe customer
            stripe_payment_method: Stripe PaymentMethod ID (pm_...)
            pricing_level: "retail", "wholesale", or "partner"
            committed_agencies: For partner deals — total committed agency count

        Returns:
            Subscription details dict
        """
        # Partner pricing — bypass plan lookup, use volume tiers
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
                "created_at": now,
                "current_period_start": now,
                "current_period_end": now + (30 * 24 * 3600),
            }
            self._save_subscription(key_hash, sub_data)
            logger.info(
                f"Partner subscription created for {key_hash[:8]} "
                f"({committed_agencies} agencies @ ${rate_info['per_agency_monthly']}/mo, "
                f"{rate_info['tier_label']} tier)"
            )
            return {
                "success": True,
                "plan_id": "partner_enterprise",
                "pricing_level": "partner",
                "plan_name": f"Partner Enterprise ({rate_info['tier_label']})",
                "status": "active",
                "committed_agencies": committed_agencies,
                "per_agency_rate": rate_info["per_agency_monthly"],
                "total_monthly": rate_info["total_monthly"],
                "total_annual": rate_info["grand_total_annual"],
            }

        plan = self.plans.get(plan_id)
        if not plan:
            return {"success": False, "error": f"Unknown plan: {plan_id}"}
        if not plan.active:
            return {"success": False, "error": f"Plan {plan_id} is not available"}

        now = time.time()
        sub_data = {
            "plan_id": plan_id,
            "pricing_level": pricing_level,
            "status": "active",
            "email": email,
            "agency_name": agency_name,
            "created_at": now,
            "current_period_start": now,
            "current_period_end": now + (30 * 24 * 3600),  # ~30 days
        }

        # Create Stripe customer + subscription if Stripe is configured
        if self.stripe and plan.stripe_price_id:
            try:
                customer = self.stripe.Customer.create(
                    email=email,
                    name=agency_name,
                    metadata={"key_hash": key_hash, "plan_id": plan_id},
                )
                sub_data["stripe_customer_id"] = customer.id

                sub_params = {
                    "customer": customer.id,
                    "items": [{"price": plan.stripe_price_id}],
                    "metadata": {"key_hash": key_hash},
                }
                if stripe_payment_method:
                    sub_params["default_payment_method"] = stripe_payment_method

                subscription = self.stripe.Subscription.create(**sub_params)
                sub_data["stripe_subscription_id"] = subscription.id
                sub_data["current_period_start"] = subscription.current_period_start
                sub_data["current_period_end"] = subscription.current_period_end

                logger.info(
                    f"Stripe subscription created: {subscription.id} "
                    f"(customer: {customer.id}, plan: {plan_id})"
                )
            except Exception as e:
                logger.error(f"Stripe subscription creation failed: {e}")
                return {"success": False, "error": f"Payment setup failed: {e}"}
        else:
            logger.info(f"Local subscription created for {key_hash[:8]} (plan: {plan_id})")

        self._save_subscription(key_hash, sub_data)

        return {
            "success": True,
            "plan_id": plan_id,
            "plan_name": plan.name,
            "status": "active",
            "stripe_customer_id": sub_data.get("stripe_customer_id"),
            "stripe_subscription_id": sub_data.get("stripe_subscription_id"),
        }

    def change_plan(self, key_hash: str, new_plan_id: str) -> dict:
        """
        Upgrade or downgrade a subscription.

        If Stripe is configured, updates the Stripe subscription.
        """
        sub = self._load_subscription(key_hash)
        if not sub:
            return {"success": False, "error": "No active subscription"}

        new_plan = self.plans.get(new_plan_id)
        if not new_plan:
            return {"success": False, "error": f"Unknown plan: {new_plan_id}"}

        old_plan_id = sub.get("plan_id")

        # Update Stripe subscription if configured
        if self.stripe and sub.get("stripe_subscription_id") and new_plan.stripe_price_id:
            try:
                stripe_sub = self.stripe.Subscription.retrieve(sub["stripe_subscription_id"])
                self.stripe.Subscription.modify(
                    sub["stripe_subscription_id"],
                    items=[{
                        "id": stripe_sub["items"]["data"][0]["id"],
                        "price": new_plan.stripe_price_id,
                    }],
                    metadata={"plan_id": new_plan_id},
                    proration_behavior="create_prorations",
                )
                logger.info(f"Stripe subscription updated: {old_plan_id} → {new_plan_id}")
            except Exception as e:
                logger.error(f"Stripe plan change failed: {e}")
                return {"success": False, "error": f"Plan change failed: {e}"}

        sub["plan_id"] = new_plan_id
        self._save_subscription(key_hash, sub)

        return {
            "success": True,
            "old_plan": old_plan_id,
            "new_plan": new_plan_id,
            "plan_name": new_plan.name,
        }

    def cancel_subscription(self, key_hash: str, reason: str = "") -> dict:
        """Cancel a subscription (end of billing period)."""
        sub = self._load_subscription(key_hash)
        if not sub:
            return {"success": False, "error": "No active subscription"}

        # Cancel on Stripe
        if self.stripe and sub.get("stripe_subscription_id"):
            try:
                self.stripe.Subscription.modify(
                    sub["stripe_subscription_id"],
                    cancel_at_period_end=True,
                    metadata={"cancel_reason": reason},
                )
                logger.info(f"Stripe subscription cancelled: {sub['stripe_subscription_id']}")
            except Exception as e:
                logger.error(f"Stripe cancellation failed: {e}")

        sub["status"] = "cancelling"
        sub["cancel_reason"] = reason
        sub["cancelled_at"] = time.time()
        self._save_subscription(key_hash, sub)

        return {
            "success": True,
            "status": "cancelling",
            "effective_date": sub.get("current_period_end"),
            "message": "Subscription will remain active until the end of the current billing period.",
        }

    def check_access(self, key_hash: str, feature: str = None) -> dict:
        """
        Check if an agency has access to a feature and is within usage limits.

        This is the main gate called before every API request.

        Returns:
            {"allowed": bool, "reason": str, "plan": str, "overage": bool}
        """
        sub = self._load_subscription(key_hash)
        if not sub or sub.get("status") not in ("active", "cancelling"):
            return {
                "allowed": False,
                "reason": "No active subscription",
                "plan": None,
                "overage": False,
            }

        plan = self.plans.get(sub.get("plan_id", ""))
        if not plan:
            return {
                "allowed": False,
                "reason": "Invalid plan",
                "plan": sub.get("plan_id"),
                "overage": False,
            }

        # Check feature access
        if feature and feature not in plan.features:
            return {
                "allowed": False,
                "reason": f"Feature '{feature}' not available on {plan.name} plan. Upgrade to access.",
                "plan": plan.plan_id,
                "overage": False,
            }

        # Check AI request limit
        usage = self.usage.get_usage(key_hash)
        ai_used = usage.get("ai_requests", 0)
        ai_limit = plan.limits.ai_requests_per_month
        overage = False

        if ai_limit > 0 and ai_used >= ai_limit:
            overage = True
            # Allow overage (billed extra) rather than hard-blocking
            logger.info(
                f"Agency {key_hash[:8]} exceeded AI request limit "
                f"({ai_used}/{ai_limit}), overage billing applies"
            )

        return {
            "allowed": True,
            "plan": plan.plan_id,
            "plan_name": plan.name,
            "overage": overage,
            "ai_requests_used": ai_used,
            "ai_requests_limit": ai_limit,
        }

    def report_usage_to_stripe(self, key_hash: str) -> dict:
        """
        Report current period usage to Stripe for overage billing.

        Call this periodically (e.g., daily) or on period end.
        """
        if not self.stripe:
            return {"success": False, "error": "Stripe not configured"}

        sub = self._load_subscription(key_hash)
        if not sub or not sub.get("stripe_subscription_id"):
            return {"success": False, "error": "No Stripe subscription"}

        plan = self.plans.get(sub.get("plan_id", ""))
        if not plan:
            return {"success": False, "error": "Invalid plan"}

        usage = self.usage.get_usage(key_hash)
        ai_used = usage.get("ai_requests", 0)
        ai_limit = plan.limits.ai_requests_per_month
        overage_count = max(0, ai_used - ai_limit) if ai_limit > 0 else 0

        if overage_count <= 0:
            return {"success": True, "overage": 0, "message": "No overage"}

        try:
            # Create a usage record on the metered Stripe subscription item
            stripe_sub = self.stripe.Subscription.retrieve(sub["stripe_subscription_id"])
            # Find the metered item (if exists)
            for item in stripe_sub["items"]["data"]:
                if item.get("price", {}).get("recurring", {}).get("usage_type") == "metered":
                    self.stripe.SubscriptionItem.create_usage_record(
                        item["id"],
                        quantity=overage_count,
                        timestamp=int(time.time()),
                        action="set",
                    )
                    logger.info(f"Reported {overage_count} overage requests to Stripe")
                    return {"success": True, "overage": overage_count}

            return {"success": True, "overage": overage_count, "note": "No metered item found"}

        except Exception as e:
            logger.error(f"Stripe usage report failed: {e}")
            return {"success": False, "error": str(e)}

    def handle_webhook(self, payload: bytes, sig_header: str, webhook_secret: str) -> dict:
        """
        Handle Stripe webhook events.

        Supported events:
            - customer.subscription.updated → sync status
            - customer.subscription.deleted → mark cancelled
            - invoice.payment_failed → flag for attention
            - invoice.paid → confirm active

        Args:
            payload: Raw request body bytes
            sig_header: Stripe-Signature header value
            webhook_secret: Webhook endpoint secret (whsec_...)

        Returns:
            {"handled": bool, "event_type": str}
        """
        if not self.stripe:
            return {"handled": False, "error": "Stripe not configured"}

        try:
            event = self.stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
        except Exception as e:
            logger.error(f"Webhook signature verification failed: {e}")
            return {"handled": False, "error": "Invalid signature"}

        event_type = event["type"]
        data = event["data"]["object"]
        key_hash = data.get("metadata", {}).get("key_hash", "")

        logger.info(f"Stripe webhook: {event_type} (key_hash: {key_hash[:8]})")

        if event_type == "customer.subscription.updated":
            if key_hash:
                sub = self._load_subscription(key_hash)
                sub["status"] = data.get("status", sub.get("status"))
                sub["current_period_start"] = data.get("current_period_start")
                sub["current_period_end"] = data.get("current_period_end")
                self._save_subscription(key_hash, sub)
            return {"handled": True, "event_type": event_type}

        elif event_type == "customer.subscription.deleted":
            if key_hash:
                sub = self._load_subscription(key_hash)
                sub["status"] = "cancelled"
                sub["cancelled_at"] = time.time()
                self._save_subscription(key_hash, sub)
            return {"handled": True, "event_type": event_type}

        elif event_type == "invoice.payment_failed":
            if key_hash:
                sub = self._load_subscription(key_hash)
                sub["status"] = "past_due"
                sub["payment_failed_at"] = time.time()
                self._save_subscription(key_hash, sub)
            return {"handled": True, "event_type": event_type}

        elif event_type == "invoice.paid":
            if key_hash:
                sub = self._load_subscription(key_hash)
                if sub.get("status") == "past_due":
                    sub["status"] = "active"
                    sub.pop("payment_failed_at", None)
                    self._save_subscription(key_hash, sub)
            return {"handled": True, "event_type": event_type}

        return {"handled": False, "event_type": event_type}

    def get_plans(self, pricing_level: str = "retail") -> List[dict]:
        """
        Get all available plans for display.

        Args:
            pricing_level: "retail" (direct OTA), "wholesale" (consolidator),
                           or "partner" (AERTiCKET platform license).
        """
        if pricing_level == "partner":
            # Partner gets a single Enterprise-level plan with volume pricing
            return [{
                "plan_id": "partner_enterprise",
                "name": "Partner Enterprise",
                "tier": "enterprise",
                "pricing_model": "per_agency_volume",
                "volume_tiers": [
                    {
                        "label": t.label,
                        "min_agencies": t.min_agencies,
                        "max_agencies": t.max_agencies or "unlimited",
                        "per_agency_monthly": t.per_agency_monthly_usd,
                    }
                    for t in PARTNER_VOLUME_TIERS
                ],
                "platform_fee_annual": PARTNER_PLATFORM_FEE_ANNUAL_USD,
                "limits": asdict(PARTNER_LIMITS),
                "features": PARTNER_FEATURES,
                "active": True,
            }]

        results = []
        for p in self.plans.values():
            if not p.active:
                continue
            price = (
                p.wholesale_monthly_usd if pricing_level == "wholesale"
                else p.price_monthly_usd
            )
            results.append({
                "plan_id": p.plan_id,
                "name": p.name,
                "tier": p.tier,
                "price_monthly": price,
                "limits": asdict(p.limits),
                "features": p.features,
                "active": p.active,
            })
        return results

    def estimate_cost(self, key_hash: str) -> dict:
        """
        Estimate current period cost including overage.

        Handles retail, wholesale, and partner pricing levels.

        Returns:
            {"base_cost": float, "overage_cost": float, "total_estimated": float, ...}
        """
        sub = self._load_subscription(key_hash)
        if not sub:
            return {"error": "No subscription"}

        pricing_level = sub.get("pricing_level", "retail")

        # Partner pricing — per-agency volume model
        if pricing_level == "partner":
            total_agencies = sub.get("committed_agencies", 1)
            rate_info = get_partner_rate(total_agencies)
            usage = self.usage.get_usage(key_hash)
            ai_used = usage.get("ai_requests", 0)
            overage_rate = rate_info["overage_rate"]

            return {
                "plan": "partner_enterprise",
                "pricing_level": "partner",
                "tier_label": rate_info["tier_label"],
                "base_cost": rate_info["per_agency_monthly"],
                "total_agencies": total_agencies,
                "total_monthly": rate_info["total_monthly"],
                "ai_requests_used": ai_used,
                "ai_requests_limit": 0,  # unlimited
                "overage_requests": 0,
                "overage_rate": overage_rate,
                "overage_cost": 0.0,
                "total_estimated": rate_info["total_monthly"],
                "platform_fee_monthly": round(PARTNER_PLATFORM_FEE_ANNUAL_USD / 12, 2),
            }

        # Retail / wholesale pricing
        plan = self.plans.get(sub.get("plan_id", ""))
        if not plan:
            return {"error": "Invalid plan"}

        base_cost = (
            plan.wholesale_monthly_usd if pricing_level == "wholesale"
            else plan.price_monthly_usd
        )

        usage = self.usage.get_usage(key_hash)
        ai_used = usage.get("ai_requests", 0)
        ai_limit = plan.limits.ai_requests_per_month
        overage_count = max(0, ai_used - ai_limit) if ai_limit > 0 else 0
        overage_cost = overage_count * plan.limits.overage_rate_usd

        return {
            "plan": plan.plan_id,
            "pricing_level": pricing_level,
            "base_cost": base_cost,
            "ai_requests_used": ai_used,
            "ai_requests_limit": ai_limit,
            "overage_requests": overage_count,
            "overage_rate": plan.limits.overage_rate_usd,
            "overage_cost": round(overage_cost, 2),
            "total_estimated": round(base_cost + overage_cost, 2),
        }
