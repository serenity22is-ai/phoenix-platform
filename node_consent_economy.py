"""
Node Consent Economy — Performance-Based Tier System + Revenue Allocation (Build #75)

Core engine for:
- XRPL wallet auto-generation on signup
- Data consent management (user toggles what data they share)
- Tier assessment (0-100 scoring → Bronze/Silver/Gold/Platinum)
- Platform activity tracking (server-side events from Mystes usage)
- Revenue allocation (arbitrage fee ledger — additional vertical)
- Referral system (auto-generated codes, activation bonuses, revenue share)
- Fleet management (commercial enrollment, bulk benefits)
- Crypto conversion (BTC/ETH → XRP/RLUSD via conversion vehicle)

The node's primary compensation is the data extraction rate (node_yield_dashboard.py).
Tiers multiply that rate. Arbitrage fee allocation is an additional revenue stream.
"""

import logging
import os
import secrets
import json
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tier Configuration
# ---------------------------------------------------------------------------

TIER_THRESHOLDS = {
    'bronze': 0,
    'silver': 25,
    'gold': 50,
    'platinum': 75,
}

# ---------------------------------------------------------------------------
# Phase-aware tier benefits
# Reads MYSTES_ECONOMIC_PHASE from mystes_ai.py to select active tier config.
# Phase 1: lean caps, overage-funded. Phase 2: aggressive, node-subsidized.
# ---------------------------------------------------------------------------

PHASE1_TIER_BENEFITS = {
    'bronze':   {
        'payout_multiplier': 1.0,  'arbitrage_discount': 0.0,  'mystes_suite': False,
        'free_queries_per_day': 5,  'free_tools_per_query': 3,   # 3 markets
        'requires_data_sharing': False, 'requires_dedicated_mode': False,
    },
    'silver':   {
        'payout_multiplier': 1.10, 'arbitrage_discount': 0.0,  'mystes_suite': False,
        'free_queries_per_day': 10, 'free_tools_per_query': 5,   # 5 markets
        'requires_data_sharing': True, 'requires_dedicated_mode': False,
    },
    'gold':     {
        'payout_multiplier': 1.25, 'arbitrage_discount': 0.05, 'mystes_suite': False,
        'free_queries_per_day': 20, 'free_tools_per_query': 8,   # 8 markets
        'requires_data_sharing': True, 'requires_dedicated_mode': False,
    },
    'platinum': {
        'payout_multiplier': 1.50, 'arbitrage_discount': 0.10, 'mystes_suite': True,
        'free_queries_per_day': 40, 'free_tools_per_query': 12,  # 12 markets
        'requires_data_sharing': True, 'requires_dedicated_mode': True,
    },
}

PHASE2_TIER_BENEFITS = {
    'bronze':   {
        'payout_multiplier': 1.0,  'arbitrage_discount': 0.0,  'mystes_suite': False,
        'free_queries_per_day': 10, 'free_tools_per_query': 5,   # 5 markets
        'requires_data_sharing': False, 'requires_dedicated_mode': False,
    },
    'silver':   {
        'payout_multiplier': 1.25, 'arbitrage_discount': 0.05, 'mystes_suite': False,
        'free_queries_per_day': 20, 'free_tools_per_query': 8,   # 8 markets
        'requires_data_sharing': True, 'requires_dedicated_mode': False,
    },
    'gold':     {
        'payout_multiplier': 1.50, 'arbitrage_discount': 0.10, 'mystes_suite': False,
        'free_queries_per_day': 40, 'free_tools_per_query': 12,  # 12 markets
        'requires_data_sharing': True, 'requires_dedicated_mode': False,
    },
    'platinum': {
        'payout_multiplier': 2.0,  'arbitrage_discount': 0.15, 'mystes_suite': True,
        'free_queries_per_day': 999, 'free_tools_per_query': 15, # unlimited
        'requires_data_sharing': True, 'requires_dedicated_mode': True,
    },
}

PHASE3_TIER_BENEFITS = {
    'bronze':   {
        'payout_multiplier': 1.0,  'arbitrage_discount': 0.0,  'mystes_suite': False,
        'free_queries_per_day': 100, 'free_tools_per_query': 10,   # 10 markets — generous
        'requires_data_sharing': False, 'requires_dedicated_mode': False,
        'query_cost_to_mystes': 0.0,   # zero — we own the SERP
        'arbitrage_reward_pct': 0.02,   # 2% of booking fee to discovering node
    },
    'silver':   {
        'payout_multiplier': 1.25, 'arbitrage_discount': 0.05, 'mystes_suite': False,
        'free_queries_per_day': 250, 'free_tools_per_query': 12,  # 12 markets
        'requires_data_sharing': True, 'requires_dedicated_mode': False,
        'query_cost_to_mystes': 0.0,
        'arbitrage_reward_pct': 0.05,   # 5% of booking fee
    },
    'gold':     {
        'payout_multiplier': 1.50, 'arbitrage_discount': 0.10, 'mystes_suite': True,
        'free_queries_per_day': 500, 'free_tools_per_query': 15,  # all markets
        'requires_data_sharing': True, 'requires_dedicated_mode': False,
        'query_cost_to_mystes': 0.0,
        'arbitrage_reward_pct': 0.10,   # 10% of booking fee
    },
    'platinum': {
        'payout_multiplier': 2.0,  'arbitrage_discount': 0.15, 'mystes_suite': True,
        'free_queries_per_day': 9999, 'free_tools_per_query': 15, # unlimited
        'requires_data_sharing': True, 'requires_dedicated_mode': True,
        'query_cost_to_mystes': 0.0,
        'arbitrage_reward_pct': 0.15,   # 15% of booking fee — max reward
    },
}

def _get_economic_phase():
    """Read phase from mystes_ai to stay in sync."""
    try:
        from mystes_ai import MYSTES_ECONOMIC_PHASE
        return MYSTES_ECONOMIC_PHASE
    except ImportError:
        return int(os.environ.get("MYSTES_ECONOMIC_PHASE", "1"))

def get_tier_benefits():
    """Return the active tier benefits dict for the current economic phase."""
    phase = _get_economic_phase()
    if phase >= 3:
        return PHASE3_TIER_BENEFITS
    elif phase >= 2:
        return PHASE2_TIER_BENEFITS
    return PHASE1_TIER_BENEFITS

# Active reference — code that reads TIER_BENEFITS directly gets the Phase 1 default.
# New code should call get_tier_benefits() to be phase-aware.
TIER_BENEFITS = PHASE1_TIER_BENEFITS

# ---------------------------------------------------------------------------
# Tier Preference Routing — Task Volume Multipliers
# ---------------------------------------------------------------------------
# Higher-tier nodes get dispatched more tasks via preference routing in
# node_registry.discover_nodes(). This translates to more extraction events
# per day → more earnings from DATA_CATEGORY_VALUES payouts.
#
# The multiplier represents how many MORE tasks a node at this tier gets
# relative to bronze baseline. Derived from routing weight ratios.
#
# Data Richness Effect:
#   When a node shares more data categories, the combined dataset is richer.
#   B2B buyers pay a premium for datasets with more coverage (e.g., a dataset
#   with price + ad + social data is worth more than price alone).
#   This premium is modeled as a multiplier on pool revenue that benefits ALL nodes.
#
# data_richness_contribution: how much this tier adds to the network data
# quality score. Network average determines pool revenue multiplier.
# ---------------------------------------------------------------------------
TIER_PREFERENCE_MULTIPLIERS = {
    'bronze':   {'task_volume_mult': 1.0,  'data_richness_contribution': 0.3},
    'silver':   {'task_volume_mult': 1.5,  'data_richness_contribution': 0.6},
    'gold':     {'task_volume_mult': 2.5,  'data_richness_contribution': 0.85},
    'platinum': {'task_volume_mult': 4.0,  'data_richness_contribution': 1.0},
}

# Maximum data richness multiplier on pool B2B revenue.
# If the entire network were platinum (richness_contribution=1.0), pool revenue
# gets multiplied by this factor. Reality: network average is ~0.5 (mix of tiers).
# Formula: 1.0 + (avg_richness × (MAX_MULTIPLIER - 1.0))
DATA_RICHNESS_MAX_POOL_MULTIPLIER = 1.8  # up to 80% more B2B revenue from rich data

def compute_network_data_richness(tier_distribution: dict = None) -> float:
    """Compute the network-wide data richness score (0.0 to 1.0).

    Higher = richer dataset = B2B clients pay more = bigger pool for everyone.
    This is the positive-sum dynamic: higher tiers sharing more data categories
    increases revenue for ALL tiers.

    Args:
        tier_distribution: Dict of {tier: fraction}. If None, uses projection defaults.

    Returns:
        Float between 0.0 and 1.0 representing network data quality.
    """
    if tier_distribution is None:
        # Default from projection model
        tier_distribution = {'bronze': 0.50, 'silver': 0.30, 'gold': 0.15, 'platinum': 0.05}

    weighted_richness = sum(
        tier_distribution.get(tier, 0) * TIER_PREFERENCE_MULTIPLIERS[tier]['data_richness_contribution']
        for tier in TIER_PREFERENCE_MULTIPLIERS
    )
    return min(1.0, weighted_richness)

def compute_pool_richness_multiplier(tier_distribution: dict = None) -> float:
    """Compute the pool revenue multiplier from network data richness.

    Returns:
        Multiplier >= 1.0 applied to pool B2B revenue.
    """
    richness = compute_network_data_richness(tier_distribution)
    return 1.0 + (richness * (DATA_RICHNESS_MAX_POOL_MULTIPLIER - 1.0))

# Arbitrage fee allocation — what percentage of the fee goes where
# The fee itself comes from the customer (25% of savings in Phase 1, tier-variant in Phase 2)
# All costs/shares come FROM that fee — customer savings are untouched
PHASE1_FEE_ALLOCATION = {
    'bronze':   {'node_share': 0.30, 'referral_share': 0.01, 'infra_share': 0.04, 'platform_fee_pct': 0.25},
    'silver':   {'node_share': 0.30, 'referral_share': 0.01, 'infra_share': 0.04, 'platform_fee_pct': 0.25},
    'gold':     {'node_share': 0.35, 'referral_share': 0.01, 'infra_share': 0.04, 'platform_fee_pct': 0.20},
    'platinum': {'node_share': 0.40, 'referral_share': 0.01, 'infra_share': 0.04, 'platform_fee_pct': 0.15},
}

PHASE2_FEE_ALLOCATION = {
    'bronze':   {'node_share': 0.30, 'referral_share': 0.01, 'infra_share': 0.04, 'platform_fee_pct': 0.25},
    'silver':   {'node_share': 0.35, 'referral_share': 0.01, 'infra_share': 0.04, 'platform_fee_pct': 0.20},
    'gold':     {'node_share': 0.40, 'referral_share': 0.01, 'infra_share': 0.04, 'platform_fee_pct': 0.15},
    'platinum': {'node_share': 0.50, 'referral_share': 0.01, 'infra_share': 0.04, 'platform_fee_pct': 0.10},
}

# Phase 3: Mystes owns GDS/SERP. No external API costs. Lower fees, higher node shares.
# Arbitrage reward pool is NEW: a % of booking fee goes to nodes whose searches
# discovered the price arbitrage that led to a booking.
PHASE3_FEE_ALLOCATION = {
    'bronze':   {'node_share': 0.40, 'referral_share': 0.01, 'infra_share': 0.02, 'platform_fee_pct': 0.25, 'arbitrage_reward_pool': 0.02},
    'silver':   {'node_share': 0.45, 'referral_share': 0.01, 'infra_share': 0.02, 'platform_fee_pct': 0.20, 'arbitrage_reward_pool': 0.05},
    'gold':     {'node_share': 0.50, 'referral_share': 0.01, 'infra_share': 0.02, 'platform_fee_pct': 0.15, 'arbitrage_reward_pool': 0.10},
    'platinum': {'node_share': 0.55, 'referral_share': 0.01, 'infra_share': 0.02, 'platform_fee_pct': 0.10, 'arbitrage_reward_pool': 0.15},
}

def get_fee_allocation():
    """Return the active fee allocation dict for the current economic phase."""
    phase = _get_economic_phase()
    if phase >= 3:
        return PHASE3_FEE_ALLOCATION
    elif phase >= 2:
        return PHASE2_FEE_ALLOCATION
    return PHASE1_FEE_ALLOCATION

FEE_ALLOCATION = PHASE1_FEE_ALLOCATION

# Consent category weights for tier scoring
CONSENT_WEIGHTS = {
    'location': 0,          # Required baseline
    'search_queries': 5,
    'price_observations': 6,
    'ad_impressions': 8,
    'social_signals': 7,
    'browsing_data': 4,
    'business_data': 10,
}

# Platform activity event values (counted like extension events for tier scoring)
PLATFORM_ACTIVITY_VALUES = {
    'platform_search': 0.001,
    'platform_comparison': 0.0005,
    'platform_booking': 0.01,
    'platform_ai_query': 0.002,
    'platform_deal_view': 0.0003,
    # Build #76 — Multi-vertical arbitrage activities
    'platform_hotel_search': 0.001,
    'platform_cruise_search': 0.002,
    'platform_rental_search': 0.001,
    'platform_package_search': 0.003,
    'platform_hotel_booking': 0.01,
    'platform_cruise_booking': 0.02,
    'platform_rental_booking': 0.008,
    'platform_arbitrage_search': 0.001,
}

# Referral config
REFERRAL_ACTIVATION_BONUS = 0.50  # RLUSD
REFERRAL_REVENUE_SHARE_PCT = 0.03  # 3% of referee earnings
MAX_REFERRAL_SCORE_NODES = 10
REFERRAL_POINTS_PER_NODE = 3

# Crypto conversion
CRYPTO_CONVENIENCE_FEE_PCT = 0.035  # 3.5% — pure margin, conversion costs pass through to user via Coinbase Commerce
SUPPORTED_CRYPTOS = ['BTC', 'ETH', 'LTC', 'DOGE', 'USDT', 'USDC']

# Wallet encryption key from environment
WALLET_ENCRYPTION_KEY = os.environ.get('WALLET_ENCRYPTION_KEY', os.environ.get('SECRET_KEY', 'dev-key-change-in-production'))


# ---------------------------------------------------------------------------
# Encryption helpers for wallet seed storage
# ---------------------------------------------------------------------------

def _encrypt_seed(seed: str) -> str:
    """Encrypt XRPL wallet seed for storage. Uses Fernet symmetric encryption."""
    try:
        from cryptography.fernet import Fernet
        import hashlib
        import base64
        key = base64.urlsafe_b64encode(hashlib.sha256(WALLET_ENCRYPTION_KEY.encode()).digest())
        f = Fernet(key)
        return f.encrypt(seed.encode()).decode()
    except ImportError:
        # Fallback: base64 encode (NOT secure — for dev only)
        import base64
        logger.warning("cryptography package not installed — using insecure base64 encoding for wallet seed")
        return base64.b64encode(seed.encode()).decode()


def _decrypt_seed(encrypted: str) -> str:
    """Decrypt XRPL wallet seed."""
    try:
        from cryptography.fernet import Fernet
        import hashlib
        import base64
        key = base64.urlsafe_b64encode(hashlib.sha256(WALLET_ENCRYPTION_KEY.encode()).digest())
        f = Fernet(key)
        return f.decrypt(encrypted.encode()).decode()
    except ImportError:
        import base64
        return base64.b64decode(encrypted.encode()).decode()


class NodeConsentEconomy:
    """Core engine for the node consent economy."""

    # ===================================================================
    # Wallet Management
    # ===================================================================

    def generate_wallet_for_user(self, user_id):
        """Auto-generate XRPL wallet on signup. Store encrypted seed + public address."""
        from models import db, User

        user = User.query.get(user_id)
        if not user:
            return {'error': 'User not found'}

        if user.xrpl_wallet_address:
            return {
                'status': 'exists',
                'address': user.xrpl_wallet_address,
            }

        try:
            from xrpl.core.keypairs import generate_seed, derive_keypair, derive_classic_address
            seed = generate_seed()
            public_key, _ = derive_keypair(seed)
            address = derive_classic_address(public_key)
        except ImportError:
            # Fallback for environments without xrpl package
            logger.warning("xrpl package not available — generating placeholder wallet")
            seed = f"s{secrets.token_hex(20)}"
            address = f"r{secrets.token_hex(20)[:33]}"

        user.xrpl_wallet_address = address
        user.xrpl_wallet_seed_encrypted = _encrypt_seed(seed)
        user.xrpl_wallet_created_at = datetime.utcnow()

        # Auto-generate referral code if not exists
        if not user.node_referral_code:
            user.node_referral_code = f"PX{secrets.token_hex(4).upper()}"

        db.session.commit()

        logger.info("Generated XRPL wallet for user %d: %s", user_id, address)
        return {
            'status': 'created',
            'address': address,
            'created_at': user.xrpl_wallet_created_at.isoformat(),
        }

    def get_wallet_info(self, user_id):
        """Get wallet address and basic info (no seed exposed)."""
        from models import User

        user = User.query.get(user_id)
        if not user:
            return {'error': 'User not found'}

        if not user.xrpl_wallet_address:
            return {'error': 'No wallet generated', 'has_wallet': False}

        return {
            'has_wallet': True,
            'address': user.xrpl_wallet_address,
            'created_at': user.xrpl_wallet_created_at.isoformat() if user.xrpl_wallet_created_at else None,
            'kyc_status': user.kyc_status or 'none',
            'kyc_verified_at': user.kyc_verified_at.isoformat() if user.kyc_verified_at else None,
        }

    # ===================================================================
    # Consent Management
    # ===================================================================

    def create_default_profile(self, user_id):
        """Create default NodeConsentProfile on signup — Bronze tier, location consent only."""
        from models import db, NodeConsentProfile, User

        existing = NodeConsentProfile.query.filter_by(user_id=user_id).first()
        if existing:
            return existing

        user = User.query.get(user_id)
        if not user:
            return None

        profile = NodeConsentProfile(
            user_id=user_id,
            node_id=f"NODE-{secrets.token_hex(6).upper()}",
            consent_location=True,
            current_tier='bronze',
            tier_score=0.0,
            payout_multiplier=1.0,
            arbitrage_fee_discount=0.0,
            mystes_suite_access=False,
        )
        db.session.add(profile)
        db.session.commit()

        logger.info("Created consent profile for user %d: node %s", user_id, profile.node_id)
        return profile

    def update_consent(self, user_id, updates):
        """Update consent toggles. Triggers tier reassessment."""
        from models import db, NodeConsentProfile

        profile = NodeConsentProfile.query.filter_by(user_id=user_id).first()
        if not profile:
            profile = self.create_default_profile(user_id)
            if not profile:
                return {'error': 'User not found'}

        consent_fields = {
            'search_queries': 'consent_search_queries',
            'price_observations': 'consent_price_observations',
            'ad_impressions': 'consent_ad_impressions',
            'social_signals': 'consent_social_signals',
            'browsing_data': 'consent_browsing_data',
            'business_data': 'consent_business_data',
        }
        # Also accept full column names (consent_search_queries, etc.)
        consent_fields_full = {col: col for col in consent_fields.values()}
        consent_fields.update(consent_fields_full)

        changed = []
        for key, col in consent_fields.items():
            if key in updates:
                old_val = getattr(profile, col)
                new_val = bool(updates[key])
                if old_val != new_val:
                    setattr(profile, col, new_val)
                    changed.append(key)

        if 'background_service_enabled' in updates:
            profile.background_service_enabled = bool(updates['background_service_enabled'])
        if 'background_service_hours_target' in updates:
            profile.background_service_hours_target = max(1, min(24, int(updates['background_service_hours_target'])))

        db.session.commit()

        # Reassess tier if consent changed
        tier_result = None
        if changed:
            tier_result = self.assess_tier(user_id)

        return {
            'updated': changed,
            'profile': profile.to_dict(),
            'tier_reassessed': tier_result is not None,
        }

    # ===================================================================
    # Tier Assessment Engine
    # ===================================================================

    def assess_tier(self, user_id, period_days=30):
        """Full tier assessment — calculate 0-100 score and assign tier."""
        from models import db, NodeConsentProfile, NodeTierHistory

        profile = NodeConsentProfile.query.filter_by(user_id=user_id).first()
        if not profile:
            profile = self.create_default_profile(user_id)
            if not profile:
                return {'error': 'User not found'}

        end = datetime.utcnow()
        start = end - timedelta(days=period_days)

        # Calculate components
        data_share = self._calculate_data_share_score(user_id, profile, start, end)
        referral = self._calculate_referral_score(user_id)
        quality = self._calculate_quality_score(user_id, start, end)
        longevity = self._calculate_longevity_score(user_id)

        total_score = min(100.0, data_share + referral + quality + longevity)

        # Determine tier
        new_tier = 'bronze'
        for tier_name in ['platinum', 'gold', 'silver', 'bronze']:
            if total_score >= TIER_THRESHOLDS[tier_name]:
                new_tier = tier_name
                break

        old_tier = profile.current_tier
        benefits = TIER_BENEFITS[new_tier]

        # Update profile
        profile.tier_score = total_score
        profile.data_share_score = data_share
        profile.referral_score = referral
        profile.quality_score = quality
        profile.longevity_score = longevity
        profile.current_tier = new_tier
        profile.payout_multiplier = benefits['payout_multiplier']
        profile.arbitrage_fee_discount = benefits['arbitrage_discount']
        profile.mystes_suite_access = benefits['mystes_suite']
        profile.last_tier_assessment = datetime.utcnow()

        # Calculate next threshold
        for tier_name in ['silver', 'gold', 'platinum']:
            if TIER_THRESHOLDS[tier_name] > total_score:
                profile.next_tier_threshold = TIER_THRESHOLDS[tier_name]
                break
        else:
            profile.next_tier_threshold = 100.0

        # Record tier change if applicable
        if old_tier != new_tier:
            history = NodeTierHistory(
                user_id=user_id,
                previous_tier=old_tier,
                new_tier=new_tier,
                tier_score=total_score,
                data_share_score=data_share,
                referral_score=referral,
                quality_score=quality,
                longevity_score=longevity,
                reason=f"Periodic assessment: {old_tier} -> {new_tier}",
            )
            db.session.add(history)
            logger.info("Tier change for user %d: %s -> %s (score: %.1f)", user_id, old_tier, new_tier, total_score)

        db.session.commit()

        return {
            'user_id': user_id,
            'tier': new_tier,
            'previous_tier': old_tier,
            'changed': old_tier != new_tier,
            'score': round(total_score, 2),
            'breakdown': {
                'data_share': round(data_share, 2),
                'referral': round(referral, 2),
                'quality': round(quality, 2),
                'longevity': round(longevity, 2),
            },
            'benefits': benefits,
            'next_threshold': profile.next_tier_threshold,
        }

    def _calculate_data_share_score(self, user_id, profile, start, end):
        """Data share score (max 40). Based on consent categories x event volume."""
        from models import db, NodeDataExtraction, BrowsingEvent

        # Sum consent weights for enabled categories
        consent_weight = 0
        if profile.consent_search_queries:
            consent_weight += CONSENT_WEIGHTS['search_queries']
        if profile.consent_price_observations:
            consent_weight += CONSENT_WEIGHTS['price_observations']
        if profile.consent_ad_impressions:
            consent_weight += CONSENT_WEIGHTS['ad_impressions']
        if profile.consent_social_signals:
            consent_weight += CONSENT_WEIGHTS['social_signals']
        if profile.consent_browsing_data:
            consent_weight += CONSENT_WEIGHTS['browsing_data']
        if profile.consent_business_data:
            consent_weight += CONSENT_WEIGHTS['business_data']

        # Max consent weight is 40 (5+6+8+7+4+10)
        max_consent_weight = sum(CONSENT_WEIGHTS.values())

        # Count events in period (extension + platform)
        extraction_count = NodeDataExtraction.query.filter(
            NodeDataExtraction.user_id == user_id,
            NodeDataExtraction.created_at >= start,
            NodeDataExtraction.created_at <= end,
        ).count() if hasattr(NodeDataExtraction, 'user_id') else 0

        browsing_count = BrowsingEvent.query.filter(
            BrowsingEvent.ingested_at >= start,
            BrowsingEvent.ingested_at <= end,
        ).count() if hasattr(BrowsingEvent, 'node_id') else 0

        # Use whichever we can count — approximate for now
        total_events = extraction_count + browsing_count

        # Volume factor: 0.5 base + 0.5 scaled by events (capped at 1000)
        volume_factor = 0.5 + 0.5 * min(total_events / 1000.0, 1.0)

        # Score: consent_weight / max_weight * 40 * volume_factor
        if max_consent_weight == 0:
            return 0.0

        score = (consent_weight / max_consent_weight) * 40.0 * volume_factor
        return min(40.0, score)

    def _calculate_referral_score(self, user_id):
        """Referral score (max 30). 3 pts per active referred node, max 10."""
        from models import NodeReferral

        active_referrals = NodeReferral.query.filter(
            NodeReferral.referrer_user_id == user_id,
            NodeReferral.is_activated == True,
            NodeReferral.is_churned == False,
        ).count()

        capped = min(active_referrals, MAX_REFERRAL_SCORE_NODES)
        return float(capped * REFERRAL_POINTS_PER_NODE)

    def _calculate_quality_score(self, user_id, start, end):
        """Quality score (max 20). Data quality (15) + consistency (5)."""
        from models import HelperProfile

        profile = HelperProfile.query.filter_by(user_id=user_id).first()
        if not profile:
            return 5.0  # Default baseline for platform-only users

        # Data quality from average rating (0-5 scale -> 0-15)
        rating = getattr(profile, 'average_rating', 5.0) or 5.0
        quality_pts = (rating / 5.0) * 15.0

        # Consistency: based on activity recency
        last_active = profile.last_active or profile.last_seen
        if last_active:
            days_since = (datetime.utcnow() - last_active).days
            if days_since <= 1:
                consistency = 5.0
            elif days_since <= 7:
                consistency = 3.0
            elif days_since <= 30:
                consistency = 1.0
            else:
                consistency = 0.0
        else:
            consistency = 2.0

        return min(20.0, quality_pts + consistency)

    def _calculate_longevity_score(self, user_id):
        """Longevity score (max 10). Based on account age."""
        from models import User

        user = User.query.get(user_id)
        if not user or not user.created_at:
            return 0.0

        days_active = (datetime.utcnow() - user.created_at).days

        if days_active >= 365:
            return 10.0
        elif days_active >= 180:
            return 8.0
        elif days_active >= 90:
            return 5.0
        elif days_active >= 30:
            return 2.0
        return 0.0

    # ===================================================================
    # Platform Activity Tracking
    # ===================================================================

    def record_platform_activity(self, user_id, activity_type, metadata=None):
        """Record platform activity (search, comparison, booking, AI query, deal view).

        These events count toward the node's tier score and data extraction value.
        Generated server-side when a logged-in node uses Mystes — no extension needed.
        """
        if activity_type not in PLATFORM_ACTIVITY_VALUES:
            logger.warning("Unknown platform activity type: %s", activity_type)
            return

        from models import db, NodeDataExtraction, NodeConsentProfile

        profile = NodeConsentProfile.query.filter_by(user_id=user_id).first()
        if not profile:
            # Auto-create profile if missing
            profile = self.create_default_profile(user_id)

        value = PLATFORM_ACTIVITY_VALUES[activity_type]

        # Apply tier payout multiplier to the platform activity value
        effective_value = value * (profile.payout_multiplier if profile else 1.0)

        try:
            extraction = NodeDataExtraction(
                task_id=f"PL-{secrets.token_hex(8)}",
                task_type="platform_activity",
                user_id=user_id,
                data_category=activity_type,
                commercial_value_usd=effective_value,
                quality_score=100,  # Platform events are always high quality
            )
            db.session.add(extraction)
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            logger.warning("Failed to record platform activity for user %d: %s", user_id, exc)

    # ===================================================================
    # Revenue Allocation (Arbitrage Fee Ledger — Additional Vertical)
    # ===================================================================

    def allocate_booking_fee(self, deal_id, fee_usd, serving_node_user_id=None):
        """Allocate an arbitrage fee across node, referrer, infra, and platform.

        This is an ADDITIONAL revenue stream for the serving node — on top of
        their primary data extraction earnings. The fee comes from the customer's
        arbitrage savings (25% or tier-specific rate). All shares come FROM that fee.
        """
        from models import db, RevenueAllocation, NodeConsentProfile, NodeReferral

        allocation_id = f"RA-{secrets.token_hex(8)}"

        # Get serving node's tier
        node_tier = 'bronze'
        referrer_user_id = None

        if serving_node_user_id:
            profile = NodeConsentProfile.query.filter_by(user_id=serving_node_user_id).first()
            if profile:
                node_tier = profile.current_tier

            # Check if serving node has a referrer
            referral = NodeReferral.query.filter_by(
                referee_user_id=serving_node_user_id,
                is_activated=True,
                is_churned=False,
            ).first()
            if referral:
                referrer_user_id = referral.referrer_user_id

        alloc_config = FEE_ALLOCATION.get(node_tier, FEE_ALLOCATION['bronze'])

        node_share_pct = alloc_config['node_share'] if serving_node_user_id else 0.0
        referral_share_pct = alloc_config['referral_share'] if referrer_user_id else 0.0
        infra_share_pct = alloc_config['infra_share']

        node_share_usd = fee_usd * node_share_pct
        referral_share_usd = fee_usd * referral_share_pct
        infra_share_usd = fee_usd * infra_share_pct
        platform_profit = fee_usd - node_share_usd - referral_share_usd - infra_share_usd

        allocation = RevenueAllocation(
            allocation_id=allocation_id,
            deal_id=deal_id,
            total_fee_usd=fee_usd,
            node_user_id=serving_node_user_id,
            node_tier=node_tier,
            node_share_pct=node_share_pct,
            node_share_usd=node_share_usd,
            referrer_user_id=referrer_user_id,
            referral_share_usd=referral_share_usd,
            infra_share_usd=infra_share_usd,
            platform_profit_usd=platform_profit,
            node_payout_status='pending' if serving_node_user_id else 'na',
            referrer_payout_status='pending' if referrer_user_id else 'na',
        )
        db.session.add(allocation)
        db.session.commit()

        logger.info(
            "Fee allocation %s: $%.2f fee -> node $%.2f (%s/%s), referrer $%.2f, infra $%.2f, platform $%.2f",
            allocation_id, fee_usd, node_share_usd, node_tier,
            f"{node_share_pct:.0%}", referral_share_usd, infra_share_usd, platform_profit,
        )

        return allocation

    def get_allocation_history(self, user_id, limit=50):
        """Get revenue allocation history for a node."""
        from models import RevenueAllocation

        allocations = RevenueAllocation.query.filter(
            (RevenueAllocation.node_user_id == user_id) |
            (RevenueAllocation.referrer_user_id == user_id)
        ).order_by(RevenueAllocation.created_at.desc()).limit(limit).all()

        total_node_earnings = sum(
            a.node_share_usd for a in allocations if a.node_user_id == user_id
        )
        total_referral_earnings = sum(
            a.referral_share_usd for a in allocations if a.referrer_user_id == user_id
        )

        return {
            'allocations': [a.to_dict() for a in allocations],
            'summary': {
                'total_node_earnings_usd': round(total_node_earnings, 4),
                'total_referral_earnings_usd': round(total_referral_earnings, 4),
                'total_combined_usd': round(total_node_earnings + total_referral_earnings, 4),
                'count': len(allocations),
            },
        }

    # ===================================================================
    # Referral System
    # ===================================================================

    def create_referral(self, referrer_user_id, referee_user_id, code):
        """Create a referral record when a new user signs up with a referral code."""
        from models import db, NodeReferral, User

        # Anti-gaming: self-referral check
        if referrer_user_id == referee_user_id:
            return {'error': 'Self-referral not allowed'}

        # Check for existing referral
        existing = NodeReferral.query.filter_by(referee_user_id=referee_user_id).first()
        if existing:
            return {'error': 'User already has a referral record'}

        referral = NodeReferral(
            referral_id=f"REF-{secrets.token_hex(6)}",
            referrer_user_id=referrer_user_id,
            referee_user_id=referee_user_id,
            referral_code=code,
        )
        db.session.add(referral)

        # Update referrer stats
        referrer = User.query.get(referrer_user_id)
        if referrer:
            referrer.total_node_referrals = (referrer.total_node_referrals or 0) + 1

        db.session.commit()

        logger.info("Referral created: %s referred user %d via code %s", referrer_user_id, referee_user_id, code)
        return {'referral_id': referral.referral_id, 'status': 'created'}

    def activate_referral(self, referee_user_id):
        """Activate referral on referee's first meaningful session."""
        from models import db, NodeReferral, User

        referral = NodeReferral.query.filter_by(
            referee_user_id=referee_user_id,
            is_activated=False,
        ).first()
        if not referral:
            return {'status': 'no_pending_referral'}

        referral.is_activated = True
        referral.activated_at = datetime.utcnow()

        # Pay activation bonus
        referral.activation_bonus_paid = True
        referral.activation_bonus_amount = REFERRAL_ACTIVATION_BONUS

        # Update referrer active count
        referrer = User.query.get(referral.referrer_user_id)
        if referrer:
            referrer.active_node_referrals = (referrer.active_node_referrals or 0) + 1

        db.session.commit()

        logger.info("Referral activated: %s (referrer user %d)", referral.referral_id, referral.referrer_user_id)
        return {
            'status': 'activated',
            'referral_id': referral.referral_id,
            'bonus_amount': REFERRAL_ACTIVATION_BONUS,
        }

    def calculate_referral_revenue_share(self, referee_user_id, earnings_usd):
        """Calculate referral revenue share — 3% of referee earnings to referrer."""
        from models import db, NodeReferral

        referral = NodeReferral.query.filter_by(
            referee_user_id=referee_user_id,
            is_activated=True,
            is_churned=False,
        ).first()
        if not referral:
            return {'share_usd': 0.0, 'referrer_user_id': None}

        share = earnings_usd * REFERRAL_REVENUE_SHARE_PCT
        referral.referee_total_earnings = (referral.referee_total_earnings or 0) + earnings_usd

        db.session.commit()

        return {
            'share_usd': round(share, 6),
            'referrer_user_id': referral.referrer_user_id,
            'referral_id': referral.referral_id,
        }

    def detect_churned_referrals(self):
        """Detect referrals where the referee has been inactive for 60+ days."""
        from models import db, NodeReferral, User

        cutoff = datetime.utcnow() - timedelta(days=60)
        churned_count = 0

        active_referrals = NodeReferral.query.filter_by(
            is_activated=True,
            is_churned=False,
        ).all()

        for referral in active_referrals:
            referee = User.query.get(referral.referee_user_id)
            if not referee:
                continue

            last_activity = referee.last_login or referee.created_at
            if last_activity and last_activity < cutoff:
                referral.is_churned = True
                referral.churned_at = datetime.utcnow()
                churned_count += 1

                # Update referrer active count
                referrer = User.query.get(referral.referrer_user_id)
                if referrer and referrer.active_node_referrals:
                    referrer.active_node_referrals = max(0, referrer.active_node_referrals - 1)

        if churned_count:
            db.session.commit()
            logger.info("Detected %d churned referrals", churned_count)

        return churned_count

    def get_referral_stats(self, user_id):
        """Get referral statistics for a user."""
        from models import NodeReferral, User

        user = User.query.get(user_id)
        if not user:
            return {'error': 'User not found'}

        referrals = NodeReferral.query.filter_by(referrer_user_id=user_id).all()

        total = len(referrals)
        active = sum(1 for r in referrals if r.is_activated and not r.is_churned)
        churned = sum(1 for r in referrals if r.is_churned)
        pending = sum(1 for r in referrals if not r.is_activated)

        total_bonus = sum(r.activation_bonus_amount for r in referrals if r.activation_bonus_paid)
        total_referee_earnings = sum(r.referee_total_earnings or 0 for r in referrals)
        estimated_revenue_share = total_referee_earnings * REFERRAL_REVENUE_SHARE_PCT

        return {
            'referral_code': user.node_referral_code,
            'total': total,
            'active': active,
            'pending': pending,
            'churned': churned,
            'total_bonus_paid_rlusd': round(total_bonus, 4),
            'total_referee_earnings_usd': round(total_referee_earnings, 4),
            'estimated_revenue_share_usd': round(estimated_revenue_share, 4),
            'referrals': [r.to_dict() for r in referrals[:20]],
        }

    # ===================================================================
    # Fleet Management
    # ===================================================================

    def create_fleet(self, commercial_account_id, name, contact_email, max_nodes=100):
        """Create a fleet account for commercial node management."""
        from models import db, FleetAccount

        fleet_id = f"FL-{secrets.token_hex(6).upper()}"
        enrollment_key = f"ENROLL-{secrets.token_hex(8).upper()}"

        fleet = FleetAccount(
            fleet_id=fleet_id,
            commercial_account_id=commercial_account_id,
            name=name,
            contact_email=contact_email,
            max_nodes=max_nodes,
            enrollment_key=enrollment_key,
        )
        db.session.add(fleet)
        db.session.commit()

        logger.info("Fleet created: %s (%s) — max %d nodes", fleet_id, name, max_nodes)
        return fleet.to_dict()

    def enroll_node_in_fleet(self, user_id, enrollment_key):
        """Enroll a node in a fleet via enrollment key."""
        from models import db, FleetAccount, HelperProfile

        fleet = FleetAccount.query.filter_by(enrollment_key=enrollment_key, is_active=True).first()
        if not fleet:
            return {'error': 'Invalid enrollment key'}

        if fleet.active_node_count >= fleet.max_nodes:
            return {'error': 'Fleet is at maximum capacity'}

        profile = HelperProfile.query.filter_by(user_id=user_id).first()
        if not profile:
            return {'error': 'No helper profile found — user must activate node first'}

        if profile.fleet_id:
            return {'error': 'Node is already enrolled in a fleet'}

        profile.fleet_id = fleet.fleet_id
        fleet.active_node_count += 1
        fleet.total_node_count += 1

        db.session.commit()

        logger.info("Node user %d enrolled in fleet %s", user_id, fleet.fleet_id)
        return {
            'status': 'enrolled',
            'fleet_id': fleet.fleet_id,
            'fleet_name': fleet.name,
        }

    def get_fleet_stats(self, fleet_id):
        """Get aggregate stats for a fleet."""
        from models import FleetAccount, HelperProfile, NodeConsentProfile

        fleet = FleetAccount.query.filter_by(fleet_id=fleet_id).first()
        if not fleet:
            return {'error': 'Fleet not found'}

        # Get all nodes in fleet
        fleet_profiles = HelperProfile.query.filter_by(fleet_id=fleet_id).all()
        user_ids = [p.user_id for p in fleet_profiles]

        # Tier distribution
        tier_dist = {'bronze': 0, 'silver': 0, 'gold': 0, 'platinum': 0}
        if user_ids:
            consent_profiles = NodeConsentProfile.query.filter(
                NodeConsentProfile.user_id.in_(user_ids)
            ).all()
            for cp in consent_profiles:
                tier_dist[cp.current_tier] = tier_dist.get(cp.current_tier, 0) + 1

        result = fleet.to_dict()
        result['tier_distribution'] = tier_dist
        result['online_count'] = sum(1 for p in fleet_profiles if p.is_online)
        return result

    # ===================================================================
    # Crypto Conversion
    # ===================================================================

    def initiate_conversion(self, user_id, source_currency, source_amount):
        """Initiate a crypto conversion (BTC/ETH/etc -> XRP/RLUSD)."""
        from models import db, CryptoConversion, User

        source_currency = source_currency.upper()
        if source_currency not in SUPPORTED_CRYPTOS:
            return {'error': f'Unsupported currency: {source_currency}. Supported: {SUPPORTED_CRYPTOS}'}

        user = User.query.get(user_id)
        if not user or not user.xrpl_wallet_address:
            return {'error': 'User must have an XRPL wallet before converting'}

        conversion_id = f"CVT-{secrets.token_hex(8)}"

        conversion = CryptoConversion(
            conversion_id=conversion_id,
            user_id=user_id,
            source_currency=source_currency,
            source_amount=source_amount,
            target_currency='XRP',
            convenience_fee_pct=CRYPTO_CONVENIENCE_FEE_PCT,
            status='pending_deposit',
        )
        db.session.add(conversion)
        db.session.commit()

        logger.info("Conversion initiated: %s — %s %s -> XRP for user %d",
                     conversion_id, source_amount, source_currency, user_id)

        return {
            'conversion_id': conversion_id,
            'status': 'pending_deposit',
            'source_currency': source_currency,
            'source_amount': source_amount,
            'convenience_fee_pct': CRYPTO_CONVENIENCE_FEE_PCT,
            'instructions': f'Send {source_amount} {source_currency} to the Mystes deposit address. '
                          f'A {CRYPTO_CONVENIENCE_FEE_PCT*100:.1f}% convenience fee will be applied.',
        }

    def confirm_conversion(self, conversion_id):
        """Confirm a conversion after deposit is verified. Triggers conversion or pre-fund."""
        from models import db, CryptoConversion

        conversion = CryptoConversion.query.filter_by(conversion_id=conversion_id).first()
        if not conversion:
            return {'error': 'Conversion not found'}

        if conversion.status != 'pending_deposit':
            return {'error': f'Conversion is in {conversion.status} state, not pending_deposit'}

        # Calculate fee and target amount (placeholder rate — real implementation
        # would call Coinbase/exchange API for live rates)
        fee_usd = conversion.source_amount * conversion.convenience_fee_pct
        conversion.convenience_fee_usd = fee_usd
        conversion.status = 'converting'
        conversion.conversion_vehicle = 'coinbase'

        db.session.commit()

        logger.info("Conversion confirmed: %s — now converting via %s",
                     conversion_id, conversion.conversion_vehicle)

        return {
            'conversion_id': conversion_id,
            'status': 'converting',
            'convenience_fee_usd': round(fee_usd, 4),
        }

    def pre_fund_conversion(self, conversion_id):
        """Pre-fund a conversion from Mystes seed account for speed."""
        from models import db, CryptoConversion

        conversion = CryptoConversion.query.filter_by(conversion_id=conversion_id).first()
        if not conversion:
            return {'error': 'Conversion not found'}

        if conversion.status not in ('converting', 'pending_deposit'):
            return {'error': f'Cannot pre-fund conversion in {conversion.status} state'}

        conversion.pre_funded = True
        conversion.status = 'pre_funded'

        db.session.commit()

        logger.info("Conversion pre-funded: %s", conversion_id)

        return {
            'conversion_id': conversion_id,
            'status': 'pre_funded',
            'pre_funded': True,
        }

    def get_conversion_history(self, user_id, limit=20):
        """Get conversion history for a user."""
        from models import CryptoConversion

        conversions = CryptoConversion.query.filter_by(user_id=user_id).order_by(
            CryptoConversion.created_at.desc()
        ).limit(limit).all()

        return {
            'conversions': [c.to_dict() for c in conversions],
            'count': len(conversions),
        }

    # ===================================================================
    # Admin
    # ===================================================================

    def get_consent_economy_dashboard(self):
        """Admin dashboard data for the consent economy."""
        from models import db, NodeConsentProfile, NodeReferral, FleetAccount, RevenueAllocation, User

        total_profiles = NodeConsentProfile.query.count()

        # Tier distribution
        tier_dist = {}
        for tier in ['bronze', 'silver', 'gold', 'platinum']:
            tier_dist[tier] = NodeConsentProfile.query.filter_by(current_tier=tier).count()

        # Wallet stats
        wallets_generated = User.query.filter(User.xrpl_wallet_address != None).count()
        kyc_verified = User.query.filter_by(kyc_status='verified').count()

        # Referral stats
        total_referrals = NodeReferral.query.count()
        active_referrals = NodeReferral.query.filter_by(is_activated=True, is_churned=False).count()

        # Fleet stats
        total_fleets = FleetAccount.query.filter_by(is_active=True).count()
        total_fleet_nodes = db.session.query(
            db.func.coalesce(db.func.sum(FleetAccount.active_node_count), 0)
        ).filter_by(is_active=True).scalar()

        # Revenue allocation stats
        total_allocations = RevenueAllocation.query.count()
        total_fees = db.session.query(
            db.func.coalesce(db.func.sum(RevenueAllocation.total_fee_usd), 0)
        ).scalar()
        total_node_payouts = db.session.query(
            db.func.coalesce(db.func.sum(RevenueAllocation.node_share_usd), 0)
        ).scalar()
        total_platform_profit = db.session.query(
            db.func.coalesce(db.func.sum(RevenueAllocation.platform_profit_usd), 0)
        ).scalar()

        # Consent opt-in rates
        consent_rates = {}
        if total_profiles > 0:
            for field_name, display_name in [
                ('consent_search_queries', 'search_queries'),
                ('consent_price_observations', 'price_observations'),
                ('consent_ad_impressions', 'ad_impressions'),
                ('consent_social_signals', 'social_signals'),
                ('consent_browsing_data', 'browsing_data'),
                ('consent_business_data', 'business_data'),
            ]:
                opted_in = NodeConsentProfile.query.filter(
                    getattr(NodeConsentProfile, field_name) == True
                ).count()
                consent_rates[display_name] = round(opted_in / total_profiles * 100, 1)

        return {
            'total_profiles': total_profiles,
            'tier_distribution': tier_dist,
            'wallets': {
                'generated': wallets_generated,
                'kyc_verified': kyc_verified,
            },
            'referrals': {
                'total': total_referrals,
                'active': active_referrals,
            },
            'fleets': {
                'total': total_fleets,
                'total_nodes': int(total_fleet_nodes),
            },
            'revenue_allocation': {
                'total_allocations': total_allocations,
                'total_fees_usd': round(float(total_fees), 2),
                'total_node_payouts_usd': round(float(total_node_payouts), 2),
                'total_platform_profit_usd': round(float(total_platform_profit), 2),
            },
            'consent_opt_in_rates': consent_rates,
        }

    def run_monthly_tier_assessment(self):
        """Run tier assessment for all nodes. Typically called by a cron job."""
        from models import NodeConsentProfile

        profiles = NodeConsentProfile.query.all()
        results = {'assessed': 0, 'upgraded': 0, 'downgraded': 0, 'unchanged': 0, 'errors': 0}

        for profile in profiles:
            try:
                result = self.assess_tier(profile.user_id)
                results['assessed'] += 1

                if result.get('changed'):
                    old = result.get('previous_tier', 'bronze')
                    new = result.get('tier', 'bronze')
                    tier_order = ['bronze', 'silver', 'gold', 'platinum']
                    if tier_order.index(new) > tier_order.index(old):
                        results['upgraded'] += 1
                    else:
                        results['downgraded'] += 1
                else:
                    results['unchanged'] += 1

            except Exception as exc:
                logger.warning("Tier assessment failed for user %d: %s", profile.user_id, exc)
                results['errors'] += 1

        logger.info("Monthly tier assessment: %s", results)
        return results

    # ===================================================================
    # Signup Integration
    # ===================================================================

    def onboard_new_user(self, user_id, referral_code=None):
        """Full onboarding for a new user: wallet + consent profile + referral."""
        # 1. Generate XRPL wallet
        wallet_result = self.generate_wallet_for_user(user_id)

        # 2. Create consent profile
        profile = self.create_default_profile(user_id)

        # 3. Process referral if code provided
        referral_result = None
        if referral_code:
            from models import User
            referrer = User.query.filter_by(node_referral_code=referral_code).first()
            if referrer and referrer.id != user_id:
                referral_result = self.create_referral(referrer.id, user_id, referral_code)

        return {
            'wallet': wallet_result,
            'profile': profile.to_dict() if profile else None,
            'referral': referral_result,
        }


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

node_consent_economy = NodeConsentEconomy()
