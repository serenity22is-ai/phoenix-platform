"""
Credits Neuron — Contribution credit tracking and rewards for agencies.

Agencies that are the first to install ANASTASiA on a new system earn
discovery credits because their installation teaches ANASTASiA a new
system at zero R&D cost. Credits translate into subscription discounts,
tier upgrades, and premium benefits.

This module provides:
    CreditsModule      — NeuronModule wiring (event bus, lifecycle)
    CreditTracker      — Append-only ledger for credit transactions
    RewardsCalculator  — Reward schedule and tier-multiplied calculations
    CreditTiers        — Tier definitions, multipliers, and benefits

MYSTES KYRIOS LLC — Confidential.
"""

import logging
import os
from typing import Any, Dict, List

from ..core.events import EventBus, Event, EventType
from ..core.registry import NeuronModule

from .tiers import CreditTiers
from .rewards import RewardsCalculator
from .tracker import CreditTracker

logger = logging.getLogger(__name__)

__all__ = [
    "CreditsModule",
    "CreditTracker",
    "RewardsCalculator",
    "CreditTiers",
]


class CreditsModule(NeuronModule):
    """
    Credits neuron module — wires together the credit tracker, rewards
    calculator, and tier system under the ANASTASiA module lifecycle.

    No dependencies on other neurons. Publishes CREDIT_EARNED and
    CREDIT_REDEEMED events on the shared event bus.

    Config keys consumed during ``initialize()``:
        credits_storage_dir (str): Directory for ledger files.
            Defaults to ``./data/credits``.

    Usage:
        registry = ModuleRegistry(event_bus)
        registry.register(CreditsModule())
        registry.initialize_all(config)
    """

    @property
    def name(self) -> str:
        return "credits"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def dependencies(self) -> List[str]:
        return []

    def __init__(self) -> None:
        self._event_bus: EventBus = None  # type: ignore[assignment]
        self._tiers: CreditTiers = None  # type: ignore[assignment]
        self._rewards: RewardsCalculator = None  # type: ignore[assignment]
        self._tracker: CreditTracker = None  # type: ignore[assignment]
        self._initialized = False

    def initialize(self, event_bus: EventBus, config: Dict[str, Any]) -> None:
        """
        Initialize the credits neuron.

        Creates the tier system, rewards calculator, and credit tracker,
        then subscribes to relevant events for automatic credit awards.

        Args:
            event_bus: Shared ANASTASiA event bus.
            config: Platform configuration dict.
        """
        self._event_bus = event_bus

        # Resolve storage directory
        storage_dir = config.get(
            "credits_storage_dir",
            os.path.join(".", "data", "credits"),
        )

        # Build components
        self._tiers = CreditTiers()
        self._rewards = RewardsCalculator(self._tiers)
        self._tracker = CreditTracker(event_bus, storage_dir)

        # Subscribe to events that trigger automatic credit awards
        event_bus.subscribe(
            EventType.SYSTEM_DISCOVERED,
            self._on_system_discovered,
        )
        event_bus.subscribe(
            EventType.QUIRK_DISCOVERED,
            self._on_quirk_discovered,
        )

        self._initialized = True
        logger.info(
            "Credits neuron initialized (storage: %s)", storage_dir,
        )

    def health_check(self) -> Dict[str, Any]:
        """
        Return health status for the credits neuron.

        Returns:
            Dict with ``healthy`` bool and diagnostic details.
        """
        if not self._initialized:
            return {"healthy": False, "details": "Not initialized"}

        try:
            balances = self._tracker.get_all_balances()
            return {
                "healthy": True,
                "details": "Credits neuron operational",
                "agencies_tracked": len(balances),
                "total_credits_outstanding": sum(balances.values()),
            }
        except Exception as e:
            return {
                "healthy": False,
                "details": f"Health check failed: {e}",
            }

    def shutdown(self) -> None:
        """Graceful shutdown — no persistent resources to release."""
        self._initialized = False
        logger.info("Credits neuron shut down")

    # ------------------------------------------------------------------
    # Component accessors
    # ------------------------------------------------------------------

    @property
    def tiers(self) -> CreditTiers:
        """Access the tier system."""
        return self._tiers

    @property
    def rewards(self) -> RewardsCalculator:
        """Access the rewards calculator."""
        return self._rewards

    @property
    def tracker(self) -> CreditTracker:
        """Access the credit tracker."""
        return self._tracker

    # ------------------------------------------------------------------
    # Event handlers — automatic credit awards
    # ------------------------------------------------------------------

    def _on_system_discovered(self, event: Event) -> None:
        """
        Automatically award discovery credits when a new system is
        discovered by an agency.

        Expected event data keys:
            agency_id (str): The discovering agency.
            system_name (str): Name of the discovered system.
            endpoints_documented (int): Count of documented endpoints.
            quirks_found (int): Count of quirks found during discovery.
        """
        data = event.data
        agency_id = event.agency_id or data.get("agency_id")
        if not agency_id:
            logger.warning(
                "SYSTEM_DISCOVERED event without agency_id, skipping credit award"
            )
            return

        system_name = data.get("system_name", "unknown")
        endpoints = data.get("endpoints_documented", 0)
        quirks = data.get("quirks_found", 0)

        # Calculate reward
        base = self._rewards.calculate_discovery_reward(
            system_name=system_name,
            endpoints_documented=endpoints,
            quirks_found=quirks,
        )

        # Apply tier multiplier
        lifetime = self._get_lifetime_credits(agency_id)
        final = self._rewards.apply_tier_multiplier(
            base_credits=base,
            agency_id=agency_id,
            lifetime_credits=lifetime,
        )

        # Award
        self._tracker.award_credits(
            agency_id=agency_id,
            amount=final,
            reason=f"discovery:{system_name}",
            metadata={
                "system_name": system_name,
                "endpoints_documented": endpoints,
                "quirks_found": quirks,
                "base_credits": base,
                "tier_multiplier": self._tiers.get_multiplier(lifetime),
            },
        )

    def _on_quirk_discovered(self, event: Event) -> None:
        """
        Automatically award quirk discovery credits.

        Expected event data keys:
            agency_id (str): The discovering agency.
            severity (str): Quirk severity — "info", "warning", or "critical".
            system_name (str): System where the quirk was found.
        """
        data = event.data
        agency_id = event.agency_id or data.get("agency_id")
        if not agency_id:
            logger.warning(
                "QUIRK_DISCOVERED event without agency_id, skipping credit award"
            )
            return

        severity = data.get("severity", "info")
        system_name = data.get("system_name", "unknown")

        # Calculate reward
        base = self._rewards.calculate_quirk_reward(severity)

        # Apply tier multiplier
        lifetime = self._get_lifetime_credits(agency_id)
        final = self._rewards.apply_tier_multiplier(
            base_credits=base,
            agency_id=agency_id,
            lifetime_credits=lifetime,
        )

        # Award
        self._tracker.award_credits(
            agency_id=agency_id,
            amount=final,
            reason=f"quirk:{system_name}:{severity}",
            metadata={
                "system_name": system_name,
                "severity": severity,
                "base_credits": base,
                "tier_multiplier": self._tiers.get_multiplier(lifetime),
            },
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_lifetime_credits(self, agency_id: str) -> int:
        """
        Calculate lifetime credits for an agency by summing all earn
        transactions from their history.
        """
        history = self._tracker.get_history(agency_id, limit=10000)
        return sum(
            t["amount"] for t in history
            if t.get("type") == CreditTracker.TYPE_EARN
        )
