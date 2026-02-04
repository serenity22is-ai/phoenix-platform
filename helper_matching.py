"""
PHOENIX Smart Helper Matching Algorithm

Scores and ranks available helpers for P2P purchase requests using a
weighted multi-factor algorithm instead of simple rating sort.

Scoring Factors (weights sum to 1.0):
    - Reliability score     (0.30) — success rate, no failed/cancelled txns
    - Rating                (0.20) — average user rating
    - Experience            (0.15) — total completed transactions
    - Availability fit      (0.15) — hours match, daily capacity remaining
    - Recency               (0.10) — recently active helpers preferred
    - Speed bonus           (0.10) — average completion time

Usage:
    from helper_matching import match_helper

    result = match_helper(
        target_market="ES",
        transaction_amount_usd=450.0,
    )
    # Returns: {"helper_id": 7, "score": 0.87, "factors": {...}} or None

    # Or get ranked list:
    from helper_matching import rank_helpers
    ranked = rank_helpers(target_market="JP", limit=5)
"""

import logging
import math
from datetime import datetime, timedelta
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Scoring weights (must sum to 1.0)
WEIGHT_RELIABILITY = 0.30
WEIGHT_RATING = 0.20
WEIGHT_EXPERIENCE = 0.15
WEIGHT_AVAILABILITY = 0.15
WEIGHT_RECENCY = 0.10
WEIGHT_SPEED = 0.10

# Thresholds
MIN_TRANSACTIONS_FOR_FULL_SCORE = 10  # Below this, experience is scaled
RECENCY_DECAY_HOURS = 48  # Activity older than this gets lower score
HIGH_VALUE_THRESHOLD_USD = 500  # Higher-value txns prefer more experienced helpers


def score_helper(helper, now=None, transaction_amount_usd=None):
    """
    Calculate a composite score for a helper (0.0 – 1.0).

    Args:
        helper: HelperProfile model instance.
        now: Current datetime (defaults to utcnow).
        transaction_amount_usd: Optional amount for experience weighting.

    Returns:
        dict with total score and individual factor scores.
    """
    if now is None:
        now = datetime.utcnow()

    factors = {}

    # --- Reliability (0–1): success rate with penalty for failures ---
    total = helper.total_transactions or 0
    success = helper.successful_transactions or 0
    failed = helper.failed_transactions or 0

    if total == 0:
        # New helper — neutral score, slight penalty for no track record
        factors["reliability"] = 0.5
    else:
        success_rate = success / total
        # Apply a penalty that's harsher for recent failures
        failure_penalty = min(failed * 0.05, 0.3)  # Max 30% penalty
        factors["reliability"] = max(0.0, success_rate - failure_penalty)

    # --- Rating (0–1): normalized from 1–5 scale ---
    rating = helper.average_rating or 5.0
    factors["rating"] = (rating - 1.0) / 4.0  # Map 1–5 → 0–1

    # --- Experience (0–1): log-scaled transaction count ---
    if total == 0:
        factors["experience"] = 0.0
    elif total >= MIN_TRANSACTIONS_FOR_FULL_SCORE:
        factors["experience"] = 1.0
    else:
        # Log scale so first few txns matter more
        factors["experience"] = math.log(1 + total) / math.log(1 + MIN_TRANSACTIONS_FOR_FULL_SCORE)

    # For high-value transactions, boost experience weight
    exp_weight = WEIGHT_EXPERIENCE
    rel_weight = WEIGHT_RELIABILITY
    if transaction_amount_usd and transaction_amount_usd > HIGH_VALUE_THRESHOLD_USD:
        # Shift 5% weight from availability to experience+reliability
        exp_weight += 0.025
        rel_weight += 0.025

    # --- Availability fit (0–1): daily capacity remaining ---
    remaining = max(0, (helper.max_daily_transactions or 10) - (helper.transactions_today or 0))
    max_daily = helper.max_daily_transactions or 10
    if max_daily > 0:
        factors["availability"] = remaining / max_daily
    else:
        factors["availability"] = 0.0

    # Check if current hour falls within helper's available hours
    current_hour = now.hour  # UTC — in production, convert to helper's timezone
    start = helper.available_hours_start or 0
    end = helper.available_hours_end or 24
    if start <= end:
        in_hours = start <= current_hour < end
    else:
        # Wraps midnight (e.g., 22–6)
        in_hours = current_hour >= start or current_hour < end

    if not in_hours:
        factors["availability"] *= 0.3  # Significant penalty if outside hours

    # --- Recency (0–1): how recently the helper was active ---
    last_active = helper.last_active or helper.created_at
    if last_active:
        hours_since_active = (now - last_active).total_seconds() / 3600
        if hours_since_active <= 1:
            factors["recency"] = 1.0
        elif hours_since_active <= RECENCY_DECAY_HOURS:
            factors["recency"] = 1.0 - (hours_since_active / RECENCY_DECAY_HOURS)
        else:
            factors["recency"] = 0.1  # Still online but stale
    else:
        factors["recency"] = 0.3

    # --- Speed bonus (0–1): estimated from average time between match and confirm ---
    # We approximate from last_transaction timing; a dedicated metric would be better
    if helper.last_transaction and total > 0:
        # If they completed a transaction recently, they're fast
        hours_since_last = (now - helper.last_transaction).total_seconds() / 3600
        if hours_since_last < 2:
            factors["speed"] = 1.0
        elif hours_since_last < 12:
            factors["speed"] = 0.7
        else:
            factors["speed"] = 0.4
    else:
        factors["speed"] = 0.5  # Unknown speed, neutral

    # --- Compute weighted total ---
    avail_weight = WEIGHT_AVAILABILITY
    if transaction_amount_usd and transaction_amount_usd > HIGH_VALUE_THRESHOLD_USD:
        avail_weight -= 0.05

    total_score = (
        factors["reliability"] * rel_weight
        + factors["rating"] * WEIGHT_RATING
        + factors["experience"] * exp_weight
        + factors["availability"] * avail_weight
        + factors["recency"] * WEIGHT_RECENCY
        + factors["speed"] * WEIGHT_SPEED
    )

    return {
        "score": round(total_score, 4),
        "factors": {k: round(v, 4) for k, v in factors.items()},
    }


def rank_helpers(target_market, limit=10, transaction_amount_usd=None,
                 require_wallet=True, require_card=True):
    """
    Get a ranked list of available helpers for a target market.

    Args:
        target_market: Country code (e.g. "ES", "JP").
        limit: Max helpers to return.
        transaction_amount_usd: For experience weighting on high-value txns.
        require_wallet: Require a verified XRPL wallet.
        require_card: Require an active payment card.

    Returns:
        List of dicts: [{"helper_id": ..., "score": ..., "factors": ...}, ...]
    """
    from models import HelperProfile, UserWallet, UserCard

    helpers = HelperProfile.query.filter_by(
        country_code=target_market,
        is_active=True,
        is_approved=True,
        is_online=True,
    ).all()

    now = datetime.utcnow()
    scored = []

    for helper in helpers:
        # Daily capacity check
        if (helper.transactions_today or 0) >= (helper.max_daily_transactions or 10):
            continue

        # Wallet and card checks
        if require_wallet:
            has_wallet = UserWallet.query.filter_by(
                user_id=helper.user_id, is_verified=True
            ).count() > 0
            if not has_wallet:
                continue

        if require_card:
            has_card = UserCard.query.filter_by(
                user_id=helper.user_id, is_active=True
            ).count() > 0
            if not has_card:
                continue

        result = score_helper(helper, now=now, transaction_amount_usd=transaction_amount_usd)
        scored.append({
            "helper_id": helper.id,
            "user_id": helper.user_id,
            "country_code": helper.country_code,
            **result,
        })

    # Sort by score descending
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:limit]


def match_helper(target_market, transaction_amount_usd=None):
    """
    Find the best available helper for a P2P transaction.

    Returns the top-scored helper or None if no helpers available.
    """
    ranked = rank_helpers(
        target_market=target_market,
        limit=1,
        transaction_amount_usd=transaction_amount_usd,
    )
    if not ranked:
        return None
    return ranked[0]
