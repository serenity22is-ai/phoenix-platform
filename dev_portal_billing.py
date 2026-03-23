"""
APAi Admin Portal Billing — Build #194

Query metering for APAi subscriber teams. All queries count against the
subscriber's pool. Overages billed through subscriber's Stripe subscription.

Tiers match APAi subscription (ALL PROVISIONAL):
    Pro ($299/mo)        — 500 queries included, $0.12 overage
    Enterprise ($599/mo) — 2,000 queries included, $0.08 overage
    Scale ($999/mo)      — 5,000 queries included, $0.05 overage

Replaces standalone Dev Portal billing (Build #184). Standalone SCRAPPED.

MYSTES KYRIOS LLC — Confidential.
"""

import logging
import os
import time
from datetime import datetime, timezone

logger = logging.getLogger("anastasia.admin.billing")


# APAi tier definitions — query limits and overage rates
TIER_CONFIG = {
    "pro": {
        "price_usd": 299,
        "queries_included": 500,
        "overage_rate": 0.12,
        "routing_fee_pct": 5,
        "price_id_env": "APAI_PRO_STRIPE_PRICE_ID",
    },
    "enterprise": {
        "price_usd": 599,
        "queries_included": 2000,
        "overage_rate": 0.08,
        "routing_fee_pct": 3,
        "price_id_env": "APAI_ENTERPRISE_STRIPE_PRICE_ID",
    },
    "scale": {
        "price_usd": 999,
        "queries_included": 5000,
        "overage_rate": 0.05,
        "routing_fee_pct": 2,
        "price_id_env": "APAI_SCALE_STRIPE_PRICE_ID",
    },
}

# Default tier for fallback
DEFAULT_TIER = "pro"


def get_tier_config(tier):
    """Get configuration for an APAi billing tier."""
    return TIER_CONFIG.get(tier, TIER_CONFIG[DEFAULT_TIER])


def record_query_usage(member_account, admin_account=None):
    """
    Increment usage counter on team member and subscriber (admin) accounts.

    For multi-seat: member tracks own queries, admin tracks aggregate.
    Overages reported to Stripe through admin's metered billing.

    Args:
        member_account: DevPortalAccount of the team member making the query
        admin_account: DevPortalAccount of the subscriber (role=admin).
                       If None and member is admin, uses member_account.
    """
    from models import db

    # Increment member's own counter
    member_account.queries_used_this_period += 1
    member_account.total_queries_lifetime += 1

    # Determine admin account for aggregate billing
    if admin_account is None:
        if member_account.role == 'admin':
            admin_account = member_account
        else:
            # Look up admin for this team
            from models import DevPortalAccount
            admin_account = DevPortalAccount.query.filter_by(
                commercial_account_id=member_account.commercial_account_id,
                role='admin',
            ).first()

    # Increment admin's aggregate counter (if different from member)
    if admin_account and admin_account.id != member_account.id:
        admin_account.queries_used_this_period += 1
        admin_account.total_queries_lifetime += 1

    # Check if this query is an overage (bill to Stripe)
    billing_account = admin_account or member_account
    tier = billing_account.billing_tier or DEFAULT_TIER
    config = get_tier_config(tier)
    included = config["queries_included"]
    used = billing_account.queries_used_this_period

    if used > included and billing_account.stripe_metered_item_id:
        _report_stripe_usage(billing_account, quantity=1)

    db.session.commit()


def _report_stripe_usage(account, quantity=1):
    """Report usage to Stripe metered billing (fire-and-forget)."""
    try:
        import stripe as stripe_mod
        stripe_mod.api_key = os.environ.get("STRIPE_SECRET_KEY")

        if not stripe_mod.api_key or not account.stripe_metered_item_id:
            return

        stripe_mod.SubscriptionItem.create_usage_record(
            account.stripe_metered_item_id,
            quantity=quantity,
            timestamp=int(time.time()),
            action="increment",
        )
        logger.debug("Reported %d query to Stripe for %s", quantity, account.account_id)
    except Exception as e:
        # Fire-and-forget — never block chat on billing failure
        logger.error("Stripe usage report failed for %s: %s", account.account_id, e)


def check_quota(member_account, admin_account=None):
    """
    Check if a team member can make a query. Quota is checked against
    the subscriber's (admin's) aggregate usage.

    All APAi tiers are always allowed to query (billing handles overages).
    Returns usage stats for the frontend.

    Args:
        member_account: DevPortalAccount of the team member
        admin_account: DevPortalAccount of the subscriber (optional)

    Returns:
        dict: {allowed, tier, used, included, overage, rate}
    """
    # Find billing account
    billing_account = member_account
    if admin_account:
        billing_account = admin_account
    elif member_account.role != 'admin':
        from models import DevPortalAccount
        admin = DevPortalAccount.query.filter_by(
            commercial_account_id=member_account.commercial_account_id,
            role='admin',
        ).first()
        if admin:
            billing_account = admin

    tier = billing_account.billing_tier or DEFAULT_TIER
    config = get_tier_config(tier)
    used = billing_account.queries_used_this_period or 0
    included = config["queries_included"]

    # Check subscription status
    if billing_account.subscription_status not in ("active", "none"):
        return {
            "allowed": False,
            "error": "subscription_inactive",
            "tier": tier,
            "subscription_status": billing_account.subscription_status,
        }

    # Check per-member limit (if set)
    if member_account.query_limit and member_account.queries_used_this_period >= member_account.query_limit:
        return {
            "allowed": False,
            "error": "member_limit_reached",
            "tier": tier,
            "member_used": member_account.queries_used_this_period,
            "member_limit": member_account.query_limit,
        }

    return {
        "allowed": True,
        "tier": tier,
        "used": used,
        "included": included,
        "overage": max(0, used - included),
        "overage_rate": config["overage_rate"],
        "total_lifetime": billing_account.total_queries_lifetime or 0,
        "member_used": member_account.queries_used_this_period or 0,
    }


def get_usage_stats(member_account, admin_account=None):
    """
    Get detailed usage statistics for the admin dashboard.

    Args:
        member_account: DevPortalAccount instance
        admin_account: Optional subscriber account for aggregate stats

    Returns:
        dict with usage, billing, and cost information
    """
    billing_account = member_account
    if admin_account:
        billing_account = admin_account
    elif member_account.role != 'admin':
        from models import DevPortalAccount
        admin = DevPortalAccount.query.filter_by(
            commercial_account_id=member_account.commercial_account_id,
            role='admin',
        ).first()
        if admin:
            billing_account = admin

    tier = billing_account.billing_tier or DEFAULT_TIER
    config = get_tier_config(tier)
    used = billing_account.queries_used_this_period or 0
    included = config["queries_included"]
    overage = max(0, used - included)

    estimated_cost = config["price_usd"] + (overage * config["overage_rate"])

    return {
        "tier": tier,
        "tier_price_usd": config["price_usd"],
        "queries_used": used,
        "queries_included": included,
        "queries_remaining": max(0, included - used),
        "overage_queries": overage,
        "overage_rate": config["overage_rate"],
        "estimated_cost_usd": round(estimated_cost, 2),
        "total_lifetime": billing_account.total_queries_lifetime or 0,
        "member_used": member_account.queries_used_this_period or 0,
        "period_start": billing_account.period_start.isoformat() if billing_account.period_start else None,
        "period_end": billing_account.period_end.isoformat() if billing_account.period_end else None,
        "subscription_status": billing_account.subscription_status,
    }
