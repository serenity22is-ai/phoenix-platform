"""
APAi Tier Feature Gating — controls what each subscription tier can access.

APAi tiers (LOCKED — Build #193, planning session 2026-04-18):
    Pro ($299/mo)        — "I'm getting started"
    Enterprise ($599/mo) — "I'm running a business"
    Scale ($999/mo)      — "I'm building an empire"

Core promises (NOT tier-gated — same for everyone):
    - ANASTASiA intelligence quality (Opus 4.6)
    - Full API access (111+ endpoints)
    - Network access (everyone can route)
    - Turnkey template (everyone gets it)
    - Sandbox environment
    - Security (same encryption, same vault)
    - ANASTASiA Terminal (everyone gets it)
    - Basic analytics

MYSTES KYRIOS LLC — Confidential.
"""

import logging
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


# ============================================================================
# Tier Hierarchy — higher index = more access
# ============================================================================

TIER_RANK = {
    "pro": 0,
    "enterprise": 1,
    "scale": 2,
}

# Aliases that map to canonical tier names
TIER_ALIASES = {
    "starter": "pro",  # Legacy alias
    "basic": "pro",
}


def _canonical_tier(tier: str) -> str:
    """Normalize tier name to canonical form."""
    t = (tier or "pro").lower().strip()
    return TIER_ALIASES.get(t, t)


# ============================================================================
# Resource Limits Per Tier
# ============================================================================

TIER_LIMITS = {
    "pro": {
        "credential_vault_max": 3,
        "team_seats_max": 1,
        "queries_per_month": 500,
        "overage_rate_usd": 0.12,
        "routing_fee_pct": 5,
    },
    "enterprise": {
        "credential_vault_max": 10,
        "team_seats_max": 5,
        "queries_per_month": 2000,
        "overage_rate_usd": 0.08,
        "routing_fee_pct": 3,
    },
    "scale": {
        "credential_vault_max": 0,  # 0 = unlimited
        "team_seats_max": 0,        # 0 = unlimited
        "queries_per_month": 5000,
        "overage_rate_usd": 0.05,
        "routing_fee_pct": 2,
    },
}


# ============================================================================
# Feature Access Per Tier
# ============================================================================

# Features available at each tier. Higher tiers inherit all lower-tier features.
# This is a flat map: feature_name → minimum tier required.
FEATURE_MIN_TIER = {
    # --- Available to ALL tiers (Pro+) ---
    "api_access": "pro",
    "turnkey_template": "pro",
    "admin_dashboard": "pro",
    "anastasia_terminal": "pro",
    "knowledge_cards": "pro",
    "sandbox": "pro",
    "network_access": "pro",
    "basic_analytics": "pro",
    "basic_branding": "pro",
    "credential_vault": "pro",
    "community_support": "pro",

    # --- Enterprise+ features ---
    "white_label": "enterprise",
    "full_analytics": "enterprise",
    "revenue_analytics": "enterprise",
    "transaction_audit_trail": "enterprise",
    "query_budget_controls": "enterprise",
    "webhook_system": "enterprise",
    "custom_notifications": "enterprise",
    "dynamic_terms": "enterprise",
    "team_roles": "enterprise",
    "custom_sdk_deploy": "enterprise",
    "email_support": "enterprise",

    # --- Scale-only features ---
    "network_intelligence_feed": "scale",
    "provider_reputation_dashboard": "scale",
    "credential_health_monitoring": "scale",
    "booking_failure_recovery": "scale",
    "revenue_forecasting": "scale",
    "bulk_operations": "scale",
    "data_export": "scale",
    "priority_support": "scale",
}

# Human-readable labels for taste strategy UI
FEATURE_LABELS = {
    "white_label": "White-Label Branding",
    "full_analytics": "Full Revenue Analytics",
    "revenue_analytics": "P&L Per Route Analytics",
    "transaction_audit_trail": "Transaction Audit Trail",
    "query_budget_controls": "Query Budget Controls",
    "webhook_system": "Webhook System",
    "custom_notifications": "Custom Notification Templates",
    "dynamic_terms": "Dynamic / Seasonal Terms",
    "team_roles": "Team Roles (Admin, Ops, Finance, Dev)",
    "custom_sdk_deploy": "Custom SDK Development",
    "email_support": "Email Support (24h Response)",
    "network_intelligence_feed": "Network Intelligence Feed",
    "provider_reputation_dashboard": "Provider Reputation Dashboard",
    "credential_health_monitoring": "Credential Health Monitoring",
    "booking_failure_recovery": "Booking Failure Recovery",
    "revenue_forecasting": "Revenue Forecasting",
    "bulk_operations": "Bulk Operations",
    "data_export": "Data Export (No Lock-In)",
    "priority_support": "Priority Support (4h Response)",
}


# ============================================================================
# Gating Functions
# ============================================================================

def has_feature(tier: str, feature: str) -> bool:
    """Check if a tier has access to a specific feature.

    Returns True if the tier meets or exceeds the minimum tier
    required for the feature.
    """
    tier = _canonical_tier(tier)
    min_tier = FEATURE_MIN_TIER.get(feature)
    if min_tier is None:
        # Unknown feature — allow by default (fail open for new features)
        return True
    return TIER_RANK.get(tier, 0) >= TIER_RANK.get(min_tier, 0)


def check_feature(tier: str, feature: str) -> Tuple[bool, Optional[str]]:
    """Check feature access with upgrade message.

    Returns:
        (allowed, upgrade_message) — message is None if allowed.
    """
    if has_feature(tier, feature):
        return True, None

    min_tier = FEATURE_MIN_TIER.get(feature, "enterprise")
    label = FEATURE_LABELS.get(feature, feature.replace("_", " ").title())
    return False, f"{label} requires {min_tier.title()} tier or above."


def get_limits(tier: str) -> Dict[str, Any]:
    """Get resource limits for a tier."""
    tier = _canonical_tier(tier)
    return dict(TIER_LIMITS.get(tier, TIER_LIMITS["pro"]))


def check_vault_limit(tier: str, current_count: int) -> Tuple[bool, int]:
    """Check if adding another credential would exceed vault limit.

    Returns:
        (allowed, max_allowed) — max_allowed=0 means unlimited.
    """
    limits = get_limits(tier)
    max_creds = limits["credential_vault_max"]
    if max_creds == 0:  # unlimited
        return True, 0
    return current_count < max_creds, max_creds


def check_team_seats(tier: str, current_count: int) -> Tuple[bool, int]:
    """Check if adding another team member would exceed seat limit.

    Returns:
        (allowed, max_allowed) — max_allowed=0 means unlimited.
    """
    limits = get_limits(tier)
    max_seats = limits["team_seats_max"]
    if max_seats == 0:  # unlimited
        return True, 0
    return current_count < max_seats, max_seats


def get_tier_from_db(key_hash: str) -> str:
    """Look up the APAi tier for an agency from the database.

    Falls back to 'pro' if not found.
    """
    try:
        from picasso.agent.db_models import db, Agency
        agency = Agency.query.filter_by(key_hash=key_hash).first()
        if agency and agency.tier:
            return _canonical_tier(agency.tier)
    except Exception as e:
        logger.debug("Could not look up tier for %s: %s", key_hash[:8], e)
    return "pro"


def get_locked_features(tier: str) -> list:
    """Get list of features that are locked (not available) at this tier.

    Used for the 'taste' strategy — showing greyed-out features.
    """
    tier = _canonical_tier(tier)
    locked = []
    for feature, min_tier in FEATURE_MIN_TIER.items():
        if not has_feature(tier, feature):
            locked.append({
                "feature": feature,
                "label": FEATURE_LABELS.get(feature, feature),
                "requires": min_tier,
            })
    return locked


def get_tier_summary(tier: str) -> Dict[str, Any]:
    """Get complete tier info for dashboard rendering.

    Includes limits, available features, and locked features with labels.
    """
    tier = _canonical_tier(tier)
    limits = get_limits(tier)
    available = [f for f in FEATURE_MIN_TIER if has_feature(tier, f)]
    locked = get_locked_features(tier)

    return {
        "tier": tier,
        "limits": limits,
        "features_available": available,
        "features_locked": locked,
        "upgrade_target": {
            "pro": "enterprise",
            "enterprise": "scale",
            "scale": None,
        }.get(tier),
    }
