"""
Credit Tiers — Tier definitions and progression logic for agency credits.

Agencies earn lifetime credits through discovery, contributions, referrals,
and usage. Higher tiers unlock better multipliers, deeper discounts, and
premium benefits.

MYSTES KYRIOS LLC — Confidential.
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class CreditTiers:
    """
    Defines the credit tier system for ANASTASiA agencies.

    Tiers are based on lifetime credits (total ever earned, not current
    balance). This means spending credits does not demote an agency —
    loyalty is permanent.

    Tier ladder:
        Bronze   :      0 –    999  (1.0x, 0% discount)
        Silver   :  1,000 –  4,999  (1.25x, 5% discount)
        Gold     :  5,000 – 19,999  (1.5x, 10% discount)
        Platinum : 20,000+          (2.0x, 15% discount)
    """

    TIERS: Dict[str, Dict[str, Any]] = {
        "Bronze": {
            "min_credits": 0,
            "max_credits": 999,
            "multiplier": 1.0,
            "discount_percent": 0.0,
            "benefits": [
                "basic_support",
            ],
        },
        "Silver": {
            "min_credits": 1000,
            "max_credits": 4999,
            "multiplier": 1.25,
            "discount_percent": 5.0,
            "benefits": [
                "priority_support",
                "early_access",
            ],
        },
        "Gold": {
            "min_credits": 5000,
            "max_credits": 19999,
            "multiplier": 1.5,
            "discount_percent": 10.0,
            "benefits": [
                "priority_support",
                "early_access",
                "custom_branding",
                "dedicated_account_manager",
            ],
        },
        "Platinum": {
            "min_credits": 20000,
            "max_credits": None,  # No upper bound
            "multiplier": 2.0,
            "discount_percent": 15.0,
            "benefits": [
                "priority_support",
                "early_access",
                "custom_branding",
                "dedicated_account_manager",
                "revenue_share",
                "roadmap_input",
            ],
        },
    }

    # Ordered tier names from lowest to highest
    TIER_ORDER: List[str] = ["Bronze", "Silver", "Gold", "Platinum"]

    def get_tier(self, lifetime_credits: int) -> Dict[str, Any]:
        """
        Return the full tier info dict for a given lifetime credit level.

        Args:
            lifetime_credits: Total credits ever earned by the agency.

        Returns:
            Dict with keys: name, min_credits, max_credits, multiplier,
            discount_percent, benefits.
        """
        resolved = self._resolve_tier_name(lifetime_credits)
        tier_data = self.TIERS[resolved]
        return {"name": resolved, **tier_data}

    def get_multiplier(self, lifetime_credits: int) -> float:
        """
        Return the reward multiplier for a given lifetime credit level.

        Higher tiers earn credits faster — a Platinum agency earns 2x
        the base reward compared to Bronze.

        Args:
            lifetime_credits: Total credits ever earned by the agency.

        Returns:
            Multiplier as a float (1.0 – 2.0).
        """
        tier_name = self._resolve_tier_name(lifetime_credits)
        return self.TIERS[tier_name]["multiplier"]

    def get_benefits(self, lifetime_credits: int) -> List[str]:
        """
        Return the list of benefit slugs for a given lifetime credit level.

        Args:
            lifetime_credits: Total credits ever earned by the agency.

        Returns:
            List of benefit identifier strings.
        """
        tier_name = self._resolve_tier_name(lifetime_credits)
        return list(self.TIERS[tier_name]["benefits"])

    def get_next_tier(self, lifetime_credits: int) -> Optional[Dict[str, Any]]:
        """
        Return the next tier info and credits needed to reach it.

        Args:
            lifetime_credits: Total credits ever earned by the agency.

        Returns:
            Dict with keys: name, min_credits, credits_needed. Returns None
            if the agency is already at the highest tier (Platinum).
        """
        current_name = self._resolve_tier_name(lifetime_credits)
        current_index = self.TIER_ORDER.index(current_name)

        if current_index >= len(self.TIER_ORDER) - 1:
            # Already at Platinum — no next tier
            return None

        next_name = self.TIER_ORDER[current_index + 1]
        next_data = self.TIERS[next_name]
        credits_needed = next_data["min_credits"] - lifetime_credits

        return {
            "name": next_name,
            "min_credits": next_data["min_credits"],
            "credits_needed": max(0, credits_needed),
        }

    def get_discount_percent(self, lifetime_credits: int) -> float:
        """
        Return the subscription discount percentage for a given credit level.

        Bronze = 0%, Silver = 5%, Gold = 10%, Platinum = 15%.

        Args:
            lifetime_credits: Total credits ever earned by the agency.

        Returns:
            Discount as a percentage float (0.0 – 15.0).
        """
        tier_name = self._resolve_tier_name(lifetime_credits)
        return self.TIERS[tier_name]["discount_percent"]

    def get_tier_progress(self, lifetime_credits: int) -> Dict[str, Any]:
        """
        Return a progress snapshot showing current tier, next tier, and
        how far along the agency is toward the next tier.

        Args:
            lifetime_credits: Total credits ever earned by the agency.

        Returns:
            Dict with keys: current_tier, credits, next_tier, credits_needed,
            progress_pct. If already at Platinum, next_tier is None,
            credits_needed is 0, and progress_pct is 100.0.
        """
        current = self.get_tier(lifetime_credits)
        next_tier = self.get_next_tier(lifetime_credits)

        if next_tier is None:
            # Platinum — fully progressed
            return {
                "current_tier": current["name"],
                "credits": lifetime_credits,
                "next_tier": None,
                "credits_needed": 0,
                "progress_pct": 100.0,
            }

        # Calculate progress within the current tier's range
        tier_floor = current["min_credits"]
        tier_ceiling = next_tier["min_credits"]
        tier_span = tier_ceiling - tier_floor
        credits_into_tier = lifetime_credits - tier_floor

        if tier_span > 0:
            progress_pct = round((credits_into_tier / tier_span) * 100.0, 1)
        else:
            progress_pct = 100.0

        # Clamp to [0, 100]
        progress_pct = max(0.0, min(100.0, progress_pct))

        return {
            "current_tier": current["name"],
            "credits": lifetime_credits,
            "next_tier": next_tier["name"],
            "credits_needed": next_tier["credits_needed"],
            "progress_pct": progress_pct,
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _resolve_tier_name(self, lifetime_credits: int) -> str:
        """
        Resolve the tier name for a given credit level.

        Iterates tiers from highest to lowest and returns the first
        match where lifetime_credits >= min_credits.
        """
        for tier_name in reversed(self.TIER_ORDER):
            if lifetime_credits >= self.TIERS[tier_name]["min_credits"]:
                return tier_name
        # Should never reach here, but default to Bronze
        return "Bronze"
