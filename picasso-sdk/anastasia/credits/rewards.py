"""
Rewards Calculator — Computes credit rewards for agency contributions.

The core economic insight: when an agency is the first to install ANASTASiA
on a new system, they teach us that system at zero R&D cost. Discovery
credits are the thank-you — they reduce the agency's costs because their
installation created value for the entire network.

Reward schedule:
    New system discovery  : 500 base + 50/endpoint + 100/quirk
    Quirk discovery       : 50 (info) / 100 (warning) / 250 (critical)
    Adapter built         : 200 (untested) / 500 (tested + verified)
    Referral              : 250 (pro) / 500 (enterprise)
    Usage loyalty         : 1 credit per 100 API calls

All rewards are subject to the agency's tier multiplier.

MYSTES KYRIOS LLC — Confidential.
"""

import logging
import math
from typing import Optional

from .tiers import CreditTiers

logger = logging.getLogger(__name__)


class RewardsCalculator:
    """
    Calculates credit rewards for agency contributions to the ANASTASiA
    network.

    Every calculation method returns the raw credit amount *before* tier
    multiplier application. Use :meth:`apply_tier_multiplier` to get the
    final amount, or call the individual methods which document their
    base values.

    Args:
        tiers: A CreditTiers instance used for tier multiplier lookups.
    """

    # ------------------------------------------------------------------
    # Reward schedule constants
    # ------------------------------------------------------------------

    # Discovery
    DISCOVERY_BASE: int = 500
    DISCOVERY_PER_ENDPOINT: int = 50
    DISCOVERY_PER_QUIRK: int = 100

    # Quirk severity
    QUIRK_REWARDS: dict = {
        "info": 50,
        "warning": 100,
        "critical": 250,
    }

    # Adapter
    ADAPTER_UNTESTED: int = 200
    ADAPTER_TESTED: int = 500

    # Referral by plan
    REFERRAL_REWARDS: dict = {
        "pro": 250,
        "enterprise": 500,
    }

    # Usage loyalty
    USAGE_CREDITS_PER_CALLS: int = 1      # credits awarded per threshold
    USAGE_CALL_THRESHOLD: int = 100        # API calls per credit

    def __init__(self, tiers: CreditTiers) -> None:
        self._tiers = tiers

    # ------------------------------------------------------------------
    # Reward calculations
    # ------------------------------------------------------------------

    def calculate_discovery_reward(
        self,
        system_name: str,
        endpoints_documented: int,
        quirks_found: int,
    ) -> int:
        """
        Calculate credits for being the first agency to install on a
        new system.

        This is the highest-value reward because it teaches ANASTASiA a
        completely new system at zero R&D cost.

        Formula:
            500 + (50 * endpoints_documented) + (100 * quirks_found)

        Args:
            system_name: Identifier of the newly discovered system.
            endpoints_documented: Number of endpoints the agency documented
                during installation.
            quirks_found: Number of quirks (edge cases, undocumented
                behaviors) the agency discovered.

        Returns:
            Base credit reward (before tier multiplier).
        """
        base = (
            self.DISCOVERY_BASE
            + (self.DISCOVERY_PER_ENDPOINT * max(0, endpoints_documented))
            + (self.DISCOVERY_PER_QUIRK * max(0, quirks_found))
        )
        logger.info(
            "Discovery reward for '%s': %d credits "
            "(%d endpoints, %d quirks)",
            system_name, base, endpoints_documented, quirks_found,
        )
        return base

    def calculate_quirk_reward(self, severity: str) -> int:
        """
        Calculate credits for discovering a new quirk in an existing system.

        Quirks are undocumented behaviors, edge cases, or bugs in
        third-party systems. Higher severity = higher reward because
        the discovery saves more pain for future agencies.

        Args:
            severity: One of "info", "warning", or "critical".

        Returns:
            Base credit reward (before tier multiplier).

        Raises:
            ValueError: If severity is not a recognized level.
        """
        severity_lower = severity.lower().strip()
        if severity_lower not in self.QUIRK_REWARDS:
            raise ValueError(
                f"Unknown quirk severity '{severity}'. "
                f"Must be one of: {list(self.QUIRK_REWARDS.keys())}"
            )
        reward = self.QUIRK_REWARDS[severity_lower]
        logger.debug("Quirk reward (severity=%s): %d credits", severity_lower, reward)
        return reward

    def calculate_adapter_reward(
        self,
        adapter_type: str,
        tested: bool,
    ) -> int:
        """
        Calculate credits for building a new adapter.

        Tested and verified adapters earn more than 2x untested ones
        because verification ensures the adapter actually works for
        future agencies.

        Args:
            adapter_type: Identifier for the adapter (e.g., "rest_json",
                "soap_xml", "graphql").
            tested: Whether the adapter has been tested and verified.

        Returns:
            Base credit reward (before tier multiplier).
        """
        reward = self.ADAPTER_TESTED if tested else self.ADAPTER_UNTESTED
        logger.debug(
            "Adapter reward (type=%s, tested=%s): %d credits",
            adapter_type, tested, reward,
        )
        return reward

    def calculate_referral_reward(self, referred_plan: str) -> int:
        """
        Calculate credits for referring a new agency to the platform.

        Higher-tier plan referrals earn more because they bring more
        value to the network.

        Args:
            referred_plan: The plan the referred agency signed up for.
                One of "pro" or "enterprise".

        Returns:
            Base credit reward (before tier multiplier).

        Raises:
            ValueError: If referred_plan is not a recognized plan.
        """
        plan_lower = referred_plan.lower().strip()
        if plan_lower not in self.REFERRAL_REWARDS:
            raise ValueError(
                f"Unknown plan '{referred_plan}'. "
                f"Must be one of: {list(self.REFERRAL_REWARDS.keys())}"
            )
        reward = self.REFERRAL_REWARDS[plan_lower]
        logger.debug("Referral reward (plan=%s): %d credits", plan_lower, reward)
        return reward

    def calculate_usage_reward(
        self,
        api_calls: int,
        period: str = "month",
    ) -> int:
        """
        Calculate loyalty credits based on API usage volume.

        Rewards consistent platform usage. 1 credit per 100 API calls.

        Args:
            api_calls: Number of API calls made in the period.
            period: Time period label (for logging/auditing). Defaults
                to "month".

        Returns:
            Base credit reward (before tier multiplier).
        """
        if api_calls <= 0:
            return 0
        reward = math.floor(api_calls / self.USAGE_CALL_THRESHOLD) * self.USAGE_CREDITS_PER_CALLS
        logger.debug(
            "Usage reward (%d calls, period=%s): %d credits",
            api_calls, period, reward,
        )
        return reward

    # ------------------------------------------------------------------
    # Tier multiplier
    # ------------------------------------------------------------------

    def apply_tier_multiplier(
        self,
        base_credits: int,
        agency_id: str,
        lifetime_credits: Optional[int] = None,
    ) -> int:
        """
        Apply the agency's tier multiplier to a base credit amount.

        The multiplier rewards loyalty — Platinum agencies earn 2x
        the base reward for every contribution.

        Args:
            base_credits: The raw credit amount before multiplier.
            agency_id: Agency identifier (for logging).
            lifetime_credits: The agency's total lifetime credits. If
                provided, used directly for tier lookup. If None, the
                caller is responsible for providing the correct value
                (this method does not query storage).

        Returns:
            Final credit amount after multiplier, rounded down to
            the nearest integer.

        Raises:
            ValueError: If lifetime_credits is None (must be provided
                by caller since RewardsCalculator has no storage access).
        """
        if lifetime_credits is None:
            raise ValueError(
                "lifetime_credits must be provided — RewardsCalculator "
                "does not have direct storage access."
            )

        multiplier = self._tiers.get_multiplier(lifetime_credits)
        final = math.floor(base_credits * multiplier)

        if multiplier > 1.0:
            logger.info(
                "Tier multiplier applied for agency '%s': "
                "%d base * %.2fx = %d credits",
                agency_id, base_credits, multiplier, final,
            )

        return final
