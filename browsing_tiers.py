"""
Phoenix Browsing Data Tier System (Build #70)

Defines buyer access tiers for browsing intelligence data.
Free tier gets aggregated trends only; paid tiers unlock raw events,
domain reports, real-time streaming, and higher rate limits.
"""

import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tier definitions
# ---------------------------------------------------------------------------

BROWSING_TIERS = {
    "browsing_free": {
        "name": "Free",
        "monthly_price": 0,
        "monthly_events": 1000,
        "features": ["aggregated_trends"],
        "max_days_back": 7,
        "max_results_per_query": 50,
        "rate_limit_per_minute": 10,
        "domain_reports": False,
        "raw_events": False,
        "real_time_streaming": False,
        "quality_feedback": False,
        "description": "Aggregated browsing trends only. 7-day lookback.",
    },
    "browsing_starter": {
        "name": "Starter",
        "monthly_price": 199,
        "monthly_events": 50000,
        "features": ["aggregated_trends", "raw_events", "domain_reports"],
        "max_days_back": 30,
        "max_results_per_query": 500,
        "rate_limit_per_minute": 60,
        "domain_reports": True,
        "raw_events": True,
        "real_time_streaming": False,
        "quality_feedback": True,
        "description": "Raw events + domain reports. 30-day lookback.",
    },
    "browsing_professional": {
        "name": "Professional",
        "monthly_price": 999,
        "monthly_events": 500000,
        "features": ["aggregated_trends", "raw_events", "domain_reports", "real_time_streaming"],
        "max_days_back": 90,
        "max_results_per_query": 1000,
        "rate_limit_per_minute": 300,
        "domain_reports": True,
        "raw_events": True,
        "real_time_streaming": True,
        "quality_feedback": True,
        "description": "Full access + real-time streaming. 90-day lookback.",
    },
    "browsing_enterprise": {
        "name": "Enterprise",
        "monthly_price": 4999,
        "monthly_events": -1,  # Unlimited
        "features": ["aggregated_trends", "raw_events", "domain_reports", "real_time_streaming", "custom_extractors"],
        "max_days_back": 365,
        "max_results_per_query": 5000,
        "rate_limit_per_minute": 1000,
        "domain_reports": True,
        "raw_events": True,
        "real_time_streaming": True,
        "quality_feedback": True,
        "description": "Unlimited events. Custom extractors. 365-day lookback.",
    },
}


def get_tier(tier_key):
    """Get tier config by key, defaulting to free."""
    return BROWSING_TIERS.get(tier_key, BROWSING_TIERS["browsing_free"])


def check_browsing_access(account, feature):
    """Check if a commercial account has access to a browsing feature.

    Features: aggregated_trends, raw_events, domain_reports,
              real_time_streaming, quality_feedback, custom_extractors
    """
    tier_key = getattr(account, "browsing_tier", None) or "browsing_free"
    tier = get_tier(tier_key)
    return feature in tier["features"] or tier.get(feature, False)


def check_browsing_quota(account):
    """Check whether the account has remaining browsing event quota.

    Returns dict with 'allowed' bool and quota details.
    """
    tier_key = getattr(account, "browsing_tier", None) or "browsing_free"
    tier = get_tier(tier_key)

    monthly_limit = tier["monthly_events"]
    if monthly_limit == -1:
        return {
            "allowed": True,
            "tier": tier_key,
            "monthly_limit": "unlimited",
            "used": getattr(account, "browsing_events_used_this_month", 0) or 0,
            "remaining": "unlimited",
        }

    used = getattr(account, "browsing_events_used_this_month", 0) or 0
    remaining = max(0, monthly_limit - used)

    return {
        "allowed": remaining > 0,
        "tier": tier_key,
        "monthly_limit": monthly_limit,
        "used": used,
        "remaining": remaining,
    }


def record_browsing_usage(account, events_consumed):
    """Increment the account's browsing event usage counter."""
    from models import db
    try:
        current = getattr(account, "browsing_events_used_this_month", 0) or 0
        account.browsing_events_used_this_month = current + events_consumed
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception("Failed to record browsing usage for account %s", account.id)


def reset_monthly_browsing(account):
    """Reset browsing usage if the billing period has elapsed."""
    from models import db
    now = datetime.utcnow()
    reset_date = getattr(account, "browsing_month_reset_date", None)
    if reset_date and now >= reset_date:
        account.browsing_events_used_this_month = 0
        account.browsing_month_reset_date = reset_date + timedelta(days=30)
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            logger.exception("Failed to reset browsing credits for account %s", account.id)


def get_browsing_tier_info(account):
    """Get full tier info + usage for an account."""
    tier_key = getattr(account, "browsing_tier", None) or "browsing_free"
    tier = get_tier(tier_key)
    used = getattr(account, "browsing_events_used_this_month", 0) or 0
    monthly_limit = tier["monthly_events"]

    return {
        "tier": tier_key,
        "tier_name": tier["name"],
        "monthly_price": tier["monthly_price"],
        "monthly_events": monthly_limit if monthly_limit != -1 else "unlimited",
        "events_used": used,
        "events_remaining": "unlimited" if monthly_limit == -1 else max(0, monthly_limit - used),
        "max_days_back": tier["max_days_back"],
        "max_results_per_query": tier["max_results_per_query"],
        "rate_limit_per_minute": tier["rate_limit_per_minute"],
        "features": tier["features"],
        "description": tier["description"],
        "reset_date": getattr(account, "browsing_month_reset_date", None),
    }


def get_all_tiers():
    """Return all browsing tier options for pricing display."""
    return {
        key: {
            "name": t["name"],
            "monthly_price": t["monthly_price"],
            "monthly_events": t["monthly_events"] if t["monthly_events"] != -1 else "unlimited",
            "features": t["features"],
            "max_days_back": t["max_days_back"],
            "max_results_per_query": t["max_results_per_query"],
            "rate_limit_per_minute": t["rate_limit_per_minute"],
            "description": t["description"],
        }
        for key, t in BROWSING_TIERS.items()
    }
