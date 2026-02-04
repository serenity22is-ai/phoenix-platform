"""
PHOENIX Commercial Account System

Manages travel agency / OTA onboarding, API key lifecycle, tiered fee
calculation, and usage metering.

Fee Model:
    - Fee = savings_usd × fee_percent / 100
    - NO minimum fee — Phoenix only earns when it finds savings
    - No savings = no charge (pure value alignment)
    - Only charged on COMPLETED bookings (searches are free within quota)
    - Rate tier determined by rolling 30-day ticket volume
    - If volume drops below tier threshold for 2 consecutive 30-day periods,
      tier downgrades (rate cut suspended)

Tier Ladder:
    starter      —  0+   tickets/30d  → 20% of savings
    professional —  50+  tickets/30d  → 15% of savings
    enterprise   —  500+ tickets/30d  → 10% of savings
    partner      —  5000+ tickets/30d → 7%  of savings

Usage:
    from commercial import commercial_manager

    # Onboard a new agency
    result = commercial_manager.create_account(
        name="Apex Travel",
        contact_email="ops@apextravel.com",
        owner_user_id=42,
    )

    # Generate API key
    key_result = commercial_manager.create_api_key(account_id, scopes=["search", "book", "p2p"])

    # Record a completed booking and calculate fee
    fee = commercial_manager.record_transaction(
        account_id=account_id,
        retail_price_usd=800,
        booked_price_usd=620,
        origin="JFK", destination="NRT", market_used="JP",
    )

    # Recalculate tiers (called by Celery beat daily)
    commercial_manager.recalculate_tiers()
"""

import hashlib
import json
import logging
import secrets
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import bcrypt

logger = logging.getLogger(__name__)


# ============================================================
# Tier Configuration
# ============================================================

TIERS = {
    "starter": {
        "min_tickets_30d": 0,
        "fee_percent": 20.0,
        "max_daily_searches": 500,
        "max_concurrent_searches": 10,
    },
    "professional": {
        "min_tickets_30d": 50,
        "fee_percent": 15.0,
        "max_daily_searches": 2000,
        "max_concurrent_searches": 25,
    },
    "enterprise": {
        "min_tickets_30d": 500,
        "fee_percent": 10.0,
        "max_daily_searches": 10000,
        "max_concurrent_searches": 50,
    },
    "partner": {
        "min_tickets_30d": 5000,
        "fee_percent": 7.0,
        "max_daily_searches": 50000,
        "max_concurrent_searches": 100,
    },
}

# Ordered from highest to lowest for tier calculation
TIER_ORDER = ["partner", "enterprise", "professional", "starter"]

# How many consecutive periods below threshold before downgrade
DOWNGRADE_GRACE_PERIODS = 2


def calculate_fee(savings_usd, fee_percent):
    """
    Calculate the Phoenix fee for a completed transaction.

    No minimum fee — if savings are zero, fee is zero.
    Phoenix only earns when it delivers value.

    Returns fee_amount (float).
    """
    if savings_usd <= 0:
        return 0.0
    return round(savings_usd * (fee_percent / 100.0), 2)


def determine_tier(tickets_30d):
    """Determine the appropriate tier based on 30-day ticket volume."""
    for tier_name in TIER_ORDER:
        if tickets_30d >= TIERS[tier_name]["min_tickets_30d"]:
            return tier_name
    return "starter"


class CommercialManager:
    """Manages commercial account lifecycle, API keys, and fee calculation."""

    # ------------------------------------------------------------------
    # Account Management
    # ------------------------------------------------------------------

    def create_account(self, name, contact_email, owner_user_id,
                       contact_name=None, company_website=None,
                       referral_code=None):
        """Onboard a new commercial account."""
        from models import db, CommercialAccount

        account_id = f"PHX-{secrets.token_hex(6).upper()}"

        # Generate or validate referral code
        if referral_code:
            referral_code = self._sanitize_referral_code(referral_code)
            existing = CommercialAccount.query.filter_by(referral_code=referral_code).first()
            if existing:
                return {"error": f"Referral code '{referral_code}' already taken"}
        else:
            referral_code = self._generate_referral_code(name)

        starter = TIERS["starter"]
        account = CommercialAccount(
            account_id=account_id,
            name=name,
            contact_email=contact_email,
            contact_name=contact_name,
            company_website=company_website,
            owner_user_id=owner_user_id,
            referral_code=referral_code,
            current_tier="starter",
            fee_percent=starter["fee_percent"],
            max_daily_searches=starter["max_daily_searches"],
            max_concurrent_searches=starter["max_concurrent_searches"],
            activated_at=datetime.utcnow(),
        )
        db.session.add(account)
        db.session.commit()

        logger.info(f"Commercial account created: {account_id} ({name}) referral={referral_code}")
        return {"account_id": account_id, "tier": "starter", "referral_code": referral_code}

    def get_account(self, account_id):
        """Get account details by account_id string."""
        from models import CommercialAccount
        return CommercialAccount.query.filter_by(account_id=account_id).first()

    def suspend_account(self, account_id, reason=None):
        """Suspend a commercial account."""
        from models import db, CommercialAccount
        account = CommercialAccount.query.filter_by(account_id=account_id).first()
        if not account:
            return {"error": "Account not found"}
        account.is_active = False
        account.suspended_at = datetime.utcnow()
        db.session.commit()
        logger.info(f"Commercial account suspended: {account_id} ({reason})")
        return {"ok": True}

    def reactivate_account(self, account_id):
        """Reactivate a suspended account."""
        from models import db, CommercialAccount
        account = CommercialAccount.query.filter_by(account_id=account_id).first()
        if not account:
            return {"error": "Account not found"}
        account.is_active = True
        account.suspended_at = None
        db.session.commit()
        return {"ok": True}

    def list_accounts(self, active_only=True, limit=100):
        """List commercial accounts."""
        from models import CommercialAccount
        query = CommercialAccount.query
        if active_only:
            query = query.filter_by(is_active=True)
        accounts = query.order_by(CommercialAccount.created_at.desc()).limit(limit).all()
        return [a.to_dict() for a in accounts]

    # ------------------------------------------------------------------
    # API Key Management
    # ------------------------------------------------------------------

    def create_api_key(self, account_id, label="Default", scopes=None,
                       expires_days=None):
        """
        Generate a new API key for a commercial account.

        Returns the full key ONCE — it cannot be retrieved again.
        """
        from models import db, CommercialAccount, CommercialAPIKey

        account = CommercialAccount.query.filter_by(account_id=account_id).first()
        if not account:
            return {"error": "Account not found"}

        # Generate key: phx_{32 hex chars}
        raw_key = secrets.token_hex(32)
        full_key = f"phx_{raw_key}"
        prefix = raw_key[:8]

        # Hash for storage
        key_hash = bcrypt.hashpw(raw_key.encode(), bcrypt.gensalt()).decode()

        if scopes is None:
            scopes = ["search", "book", "p2p", "analytics"]

        expires_at = None
        if expires_days:
            expires_at = datetime.utcnow() + timedelta(days=expires_days)

        api_key = CommercialAPIKey(
            account_id=account.id,
            key_prefix=prefix,
            key_hash=key_hash,
            label=label,
            scopes=json.dumps(scopes),
            expires_at=expires_at,
        )
        db.session.add(api_key)
        db.session.commit()

        logger.info(f"API key created for {account_id}: phx_{prefix}...")
        return {
            "api_key": full_key,
            "key_id": api_key.id,
            "prefix": f"phx_{prefix}...",
            "scopes": scopes,
            "expires_at": expires_at.isoformat() if expires_at else None,
            "warning": "Store this key securely — it cannot be retrieved again.",
        }

    def verify_api_key(self, key_string):
        """
        Verify an API key and return the associated account.

        Args:
            key_string: Full key string (phx_xxx...)

        Returns:
            (CommercialAccount, CommercialAPIKey, scopes) tuple or None
        """
        from models import db, CommercialAPIKey, CommercialAccount

        if not key_string or not key_string.startswith("phx_"):
            return None

        raw_key = key_string[4:]  # Strip "phx_" prefix
        prefix = raw_key[:8]

        # Find candidate keys by prefix (fast lookup)
        candidates = CommercialAPIKey.query.filter_by(
            key_prefix=prefix,
            is_active=True,
        ).all()

        for api_key in candidates:
            if bcrypt.checkpw(raw_key.encode(), api_key.key_hash.encode()):
                # Check expiration
                if api_key.expires_at and datetime.utcnow() > api_key.expires_at:
                    return None

                # Check account is active
                account = CommercialAccount.query.get(api_key.account_id)
                if not account or not account.is_active:
                    return None

                # Update usage stats
                api_key.last_used_at = datetime.utcnow()
                api_key.total_requests = (api_key.total_requests or 0) + 1
                db.session.commit()

                scopes = json.loads(api_key.scopes) if api_key.scopes else []
                return (account, api_key, scopes)

        return None

    def revoke_api_key(self, key_id, account_id):
        """Revoke an API key."""
        from models import db, CommercialAPIKey, CommercialAccount

        account = CommercialAccount.query.filter_by(account_id=account_id).first()
        if not account:
            return {"error": "Account not found"}

        api_key = CommercialAPIKey.query.filter_by(
            id=key_id, account_id=account.id
        ).first()
        if not api_key:
            return {"error": "Key not found"}

        api_key.is_active = False
        db.session.commit()
        return {"ok": True}

    # ------------------------------------------------------------------
    # Fee Calculation & Transaction Recording
    # ------------------------------------------------------------------

    def record_transaction(self, account_id, retail_price_usd, booked_price_usd,
                           origin=None, destination=None, market_used=None,
                           booking_id=None, p2p_transaction_id=None):
        """
        Record a completed booking through a commercial account.
        Calculates and records the fee.

        Only call this on COMPLETED bookings — not on searches or failed attempts.
        """
        from models import db, CommercialAccount, CommercialTransaction

        account = CommercialAccount.query.filter_by(account_id=account_id).first()
        if not account:
            return {"error": "Account not found"}

        savings = max(0, retail_price_usd - booked_price_usd)
        savings_pct = round((savings / retail_price_usd) * 100, 1) if retail_price_usd > 0 else 0

        fee_amount = calculate_fee(savings, account.fee_percent)

        tx = CommercialTransaction(
            account_id=account.id,
            booking_id=booking_id,
            p2p_transaction_id=p2p_transaction_id,
            retail_price_usd=retail_price_usd,
            booked_price_usd=booked_price_usd,
            savings_usd=savings,
            savings_percent=savings_pct,
            fee_percent_applied=account.fee_percent,
            fee_amount_usd=fee_amount,
            origin=origin,
            destination=destination,
            market_used=market_used,
        )
        db.session.add(tx)

        # Update account rolling stats
        account.total_tickets = (account.total_tickets or 0) + 1
        account.total_revenue_usd = (account.total_revenue_usd or 0) + fee_amount
        db.session.commit()

        logger.info(
            f"Commercial tx: {account_id} | savings=${savings:.2f} | "
            f"fee=${fee_amount:.2f} ({account.fee_percent}%) | "
            f"{origin}→{destination} via {market_used}"
        )

        return {
            "fee_amount_usd": fee_amount,
            "fee_percent": account.fee_percent,
            "savings_usd": savings,
            "tier": account.current_tier,
        }

    def get_account_stats(self, account_id):
        """Get usage stats for a commercial account."""
        from models import db, CommercialAccount, CommercialTransaction

        account = CommercialAccount.query.filter_by(account_id=account_id).first()
        if not account:
            return None

        cutoff_30d = datetime.utcnow() - timedelta(days=30)
        cutoff_7d = datetime.utcnow() - timedelta(days=7)

        # 30-day stats
        stats_30d = db.session.query(
            db.func.count(CommercialTransaction.id).label("tickets"),
            db.func.sum(CommercialTransaction.fee_amount_usd).label("revenue"),
            db.func.sum(CommercialTransaction.savings_usd).label("savings"),
            db.func.avg(CommercialTransaction.savings_percent).label("avg_savings_pct"),
        ).filter(
            CommercialTransaction.account_id == account.id,
            CommercialTransaction.created_at >= cutoff_30d,
        ).first()

        # 7-day stats
        stats_7d = db.session.query(
            db.func.count(CommercialTransaction.id).label("tickets"),
            db.func.sum(CommercialTransaction.fee_amount_usd).label("revenue"),
        ).filter(
            CommercialTransaction.account_id == account.id,
            CommercialTransaction.created_at >= cutoff_7d,
        ).first()

        # Next tier info
        current_tier = account.current_tier
        next_tier = None
        tickets_to_next = None
        for i, t in enumerate(TIER_ORDER):
            if t == current_tier and i > 0:
                next_tier = TIER_ORDER[i - 1]
                tickets_to_next = max(
                    0,
                    TIERS[next_tier]["min_tickets_30d"] - (stats_30d.tickets or 0)
                )
                break

        return {
            **account.to_dict(),
            "stats_30d": {
                "tickets": stats_30d.tickets or 0,
                "revenue_usd": round(stats_30d.revenue or 0, 2),
                "total_savings_usd": round(stats_30d.savings or 0, 2),
                "avg_savings_pct": round(stats_30d.avg_savings_pct or 0, 1),
            },
            "stats_7d": {
                "tickets": stats_7d.tickets or 0,
                "revenue_usd": round(stats_7d.revenue or 0, 2),
            },
            "next_tier": next_tier,
            "tickets_to_next_tier": tickets_to_next,
            "tier_config": TIERS[current_tier],
        }

    # ------------------------------------------------------------------
    # Tier Recalculation (called by Celery beat, daily)
    # ------------------------------------------------------------------

    def recalculate_tiers(self):
        """
        Recalculate fee tiers for all active commercial accounts based on
        rolling 30-day ticket volume.

        Upgrade: Immediate when volume crosses threshold.
        Downgrade: Only after 2 consecutive periods below threshold (grace).
        """
        from models import db, CommercialAccount, CommercialTransaction

        cutoff = datetime.utcnow() - timedelta(days=30)
        accounts = CommercialAccount.query.filter_by(is_active=True).all()

        upgrades = 0
        downgrades = 0

        for account in accounts:
            # Count tickets in last 30 days
            ticket_count = CommercialTransaction.query.filter(
                CommercialTransaction.account_id == account.id,
                CommercialTransaction.created_at >= cutoff,
            ).count()

            # Sum revenue in last 30 days
            rev = db.session.query(
                db.func.sum(CommercialTransaction.fee_amount_usd)
            ).filter(
                CommercialTransaction.account_id == account.id,
                CommercialTransaction.created_at >= cutoff,
            ).scalar() or 0

            account.tickets_last_30d = ticket_count
            account.revenue_last_30d_usd = rev

            # Determine what tier they qualify for
            qualified_tier = determine_tier(ticket_count)
            current_tier = account.current_tier

            current_idx = TIER_ORDER.index(current_tier) if current_tier in TIER_ORDER else len(TIER_ORDER) - 1
            qualified_idx = TIER_ORDER.index(qualified_tier)

            if qualified_idx < current_idx:
                # Upgrade — immediate
                self._apply_tier(account, qualified_tier)
                account.periods_below_threshold = 0
                upgrades += 1
                logger.info(
                    f"Commercial tier UPGRADE: {account.account_id} "
                    f"{current_tier} → {qualified_tier} ({ticket_count} tickets/30d)"
                )
            elif qualified_idx > current_idx:
                # Below current tier threshold — grace period
                account.periods_below_threshold = (account.periods_below_threshold or 0) + 1
                if account.periods_below_threshold >= DOWNGRADE_GRACE_PERIODS:
                    self._apply_tier(account, qualified_tier)
                    account.periods_below_threshold = 0
                    downgrades += 1
                    logger.info(
                        f"Commercial tier DOWNGRADE: {account.account_id} "
                        f"{current_tier} → {qualified_tier} ({ticket_count} tickets/30d)"
                    )
                else:
                    logger.info(
                        f"Commercial tier WARNING: {account.account_id} below threshold "
                        f"({account.periods_below_threshold}/{DOWNGRADE_GRACE_PERIODS} periods)"
                    )
            else:
                # Same tier — reset grace counter
                account.periods_below_threshold = 0

            account.last_tier_review = datetime.utcnow()

        db.session.commit()
        return {"reviewed": len(accounts), "upgrades": upgrades, "downgrades": downgrades}

    def _apply_tier(self, account, tier_name):
        """Apply tier configuration to an account."""
        tier = TIERS[tier_name]
        account.current_tier = tier_name
        account.fee_percent = tier["fee_percent"]
        account.max_daily_searches = tier["max_daily_searches"]
        account.max_concurrent_searches = tier["max_concurrent_searches"]

        # Notify via SSE
        try:
            from event_stream import publish_event
            publish_event(f"user:{account.owner_user_id}", "tier_changed", {
                "account_id": account.account_id,
                "new_tier": tier_name,
                "fee_percent": tier["fee_percent"],
            })
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Referral System
    # ------------------------------------------------------------------

    def _sanitize_referral_code(self, code):
        """Sanitize a referral code: uppercase, alphanumeric only, max 20 chars."""
        import re
        cleaned = re.sub(r'[^A-Z0-9]', '', code.upper())
        return cleaned[:20] if cleaned else None

    def _generate_referral_code(self, company_name):
        """Auto-generate a referral code from company name."""
        from models import CommercialAccount
        import re

        # Extract alpha chars, uppercase, max 12 chars
        base = re.sub(r'[^A-Z]', '', company_name.upper())[:12]
        if not base:
            base = "PHOENIX"

        code = base
        suffix = 1
        while CommercialAccount.query.filter_by(referral_code=code).first():
            code = f"{base}{suffix}"
            suffix += 1

        return code

    def get_account_by_referral_code(self, referral_code):
        """Look up a commercial account by its referral code."""
        from models import CommercialAccount
        code = self._sanitize_referral_code(referral_code)
        if not code:
            return None
        return CommercialAccount.query.filter_by(
            referral_code=code, is_active=True
        ).first()

    def attribute_referral(self, user_id, referral_code):
        """
        Attribute a user signup to a commercial account's referral code.

        Called during user registration when a referral code is provided
        (e.g. from /join/<code> redirect or signup form).

        Returns the commercial account dict or None.
        """
        from models import db, User

        account = self.get_account_by_referral_code(referral_code)
        if not account:
            return None

        user = User.query.get(user_id)
        if not user:
            return None

        # Don't re-attribute if already referred
        if user.referred_by_account_id:
            return None

        user.referred_by_account_id = account.id
        user.referral_code_used = account.referral_code
        account.total_referred_users = (account.total_referred_users or 0) + 1

        db.session.commit()

        logger.info(
            f"Referral attributed: user {user_id} → account {account.account_id} "
            f"(code: {account.referral_code}, total referred: {account.total_referred_users})"
        )
        return account.to_dict()

    def activate_helper_node(self, user_id):
        """
        Mark a referred user as an active helper node.
        Increments the referring account's helper count.
        """
        from models import db, User

        user = User.query.get(user_id)
        if not user or user.is_helper_node:
            return False

        user.is_helper_node = True

        # Update referring account's helper count
        if user.referred_by_account_id:
            from models import CommercialAccount
            account = CommercialAccount.query.get(user.referred_by_account_id)
            if account:
                account.total_referred_helpers = (account.total_referred_helpers or 0) + 1

        db.session.commit()
        return True

    def get_referral_stats(self, account_id):
        """Get referral statistics for a commercial account."""
        from models import db, User, CommercialAccount

        account = CommercialAccount.query.filter_by(account_id=account_id).first()
        if not account:
            return None

        referred = User.query.filter_by(referred_by_account_id=account.id)
        total_referred = referred.count()
        active_helpers = referred.filter_by(is_helper_node=True).count()

        # Count referred users who have completed bookings
        from models import Booking
        referred_ids = [u.id for u in referred.all()]
        active_bookers = 0
        if referred_ids:
            active_bookers = Booking.query.filter(
                Booking.user_id.in_(referred_ids),
                Booking.status == 'completed',
            ).with_entities(Booking.user_id).distinct().count()

        return {
            "account_id": account.account_id,
            "referral_code": account.referral_code,
            "total_referred_users": total_referred,
            "active_helper_nodes": active_helpers,
            "active_bookers": active_bookers,
            "referral_url": f"/join/{account.referral_code}",
        }

    def update_referral_code(self, account_id, new_code):
        """Update an account's referral code (must be unique)."""
        from models import db, CommercialAccount

        account = CommercialAccount.query.filter_by(account_id=account_id).first()
        if not account:
            return {"error": "Account not found"}

        new_code = self._sanitize_referral_code(new_code)
        if not new_code or len(new_code) < 3:
            return {"error": "Referral code must be at least 3 characters"}

        existing = CommercialAccount.query.filter_by(referral_code=new_code).first()
        if existing and existing.id != account.id:
            return {"error": f"Code '{new_code}' already taken"}

        old_code = account.referral_code
        account.referral_code = new_code
        db.session.commit()

        logger.info(f"Referral code updated: {account_id} {old_code} → {new_code}")
        return {"ok": True, "referral_code": new_code}


# Global instance
commercial_manager = CommercialManager()
