"""
SaaS Feature Gating — Tier-based access control for ANASTASiA neurons.

Maps billing plan tiers to neuron capabilities. Premium features
(Update Call System, Credential Network, Daemon Bridge) are gated
behind higher tiers. This module bridges billing -> neuron access.

THE PYRAMID — Tier Structure (Build #156):
    Sandbox (free): FULL suite access, pay-per-query past free limits.
        Free: 500 API/mo, 100 suite AI/mo, 10 dev AI/mo, 50 searches/day.
        Overage: $0.02/API, $0.10/suite AI, $0.15/dev AI, $0.25/credential query.
        Bookings at B2C rates (35-50% of savings). Template preview + branding.
    Starter $99:  Turnkey template deployed, credential portal, all verticals
    Pro $299:     Own credentials, dev terminal, modules, credential network (5% routing)
    Enterprise $799: ALL neurons, bulk provisioning, dedicated credentials (3% routing)

MYSTES KYRIOS LLC — Confidential.
"""

import logging
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Set

from ..core.events import EventBus, Event, EventType
from ..core.registry import NeuronModule

logger = logging.getLogger(__name__)

__all__ = [
    "TierDefinition",
    "AccessDecision",
    "FeatureGate",
    "SaaSModule",
]


# ---------------------------------------------------------------------------
# Feature flag keys — canonical list used across all tiers
# ---------------------------------------------------------------------------

ALL_FEATURE_KEYS = [
    "ai_chat",
    "flights_search",
    "hotels_search",
    "booking",
    "update_call_system",
    "credential_network",
    "credential_portal",
    "daemon_bridge",
    "intelligence",
    "analytics",
    "webhooks",
    "white_label",
    "custom_branding",
    "api_access",
    "bulk_provisioning",
    "document_generation",
    "seatmap",
    "dev_terminal",
    "module_marketplace",
    "dev_ai_chat",
    "bundle_builder",
    "unified_search",
    "template_preview",
]


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class TierDefinition:
    """
    Defines what a billing tier grants: which neurons, features, and limits.

    Attributes:
        tier_id:            Canonical tier identifier ("free", "pro", "enterprise").
        name:               Human-readable tier name.
        neurons_allowed:    Neuron module names accessible on this tier.
                            ``["*"]`` means all neurons are accessible.
        features:           Feature flag map. ``True`` = enabled, ``False`` = gated.
        limits:             Resource limits. ``-1`` = unlimited.
        price_usd_monthly:  Monthly price in USD (0.0 for free tier).
    """

    tier_id: str = ""
    name: str = ""
    neurons_allowed: List[str] = field(default_factory=list)
    features: Dict[str, bool] = field(default_factory=dict)
    limits: Dict[str, int] = field(default_factory=dict)
    price_usd_monthly: float = 0.0

    def to_dict(self) -> dict:
        """Serialize to a plain dict for JSON/API responses."""
        return asdict(self)


@dataclass
class AccessDecision:
    """
    Result of a feature/neuron/limit access check.

    Attributes:
        allowed:        Whether access is granted.
        tier_id:        The requester's current tier.
        resource:       What was requested (neuron name, feature key, or limit key).
        reason:         Machine-readable reason string.
        upgrade_prompt: Human-readable upgrade CTA (``None`` when allowed).
    """

    allowed: bool = False
    tier_id: str = ""
    resource: str = ""
    reason: str = ""
    upgrade_prompt: Optional[str] = None

    def to_dict(self) -> dict:
        """Serialize to a plain dict for JSON/API responses."""
        return asdict(self)


# ---------------------------------------------------------------------------
# FeatureGate — main utility class
# ---------------------------------------------------------------------------

class FeatureGate:
    """
    Maps billing plan tiers to ANASTASiA neuron capabilities.

    This is a standalone utility, NOT a NeuronModule. It is consumed by
    the ``SaaSModule`` neuron and by API middleware for request-level gating.

    Usage::

        gate = FeatureGate(event_bus=bus)

        decision = gate.check_feature_access("free", "webhooks")
        if not decision.allowed:
            return {"error": decision.reason, "upgrade": decision.upgrade_prompt}
    """

    # ------------------------------------------------------------------
    # Tier Definitions (class-level constants)
    # ------------------------------------------------------------------

    TIERS: Dict[str, TierDefinition] = {
        "free": TierDefinition(
            tier_id="free",
            name="Sandbox",
            neurons_allowed=["knowledge", "resilience", "compliance", "sandbox"],
            features={
                "ai_chat": True,
                "flights_search": True,
                "hotels_search": False,
                "booking": False,
                "update_call_system": False,
                "credential_network": False,
                "credential_portal": False,
                "daemon_bridge": False,
                "intelligence": False,
                "analytics": False,
                "webhooks": False,
                "white_label": True,
                "custom_branding": True,
                "api_access": True,
                "bulk_provisioning": False,
                "document_generation": False,
                "seatmap": False,
                "dev_terminal": True,
                "module_marketplace": False,
                "dev_ai_chat": True,
                "bundle_builder": False,
                "unified_search": False,
                "template_preview": True,
            },
            limits={
                "api_calls_per_month": 500,
                "searches_per_day": 50,
                "bookings_per_month": 0,
                "ai_requests_per_month": 100,
                "max_passengers": 4,
                "dev_ai_requests_per_month": 10,
                "suite_ai_requests_per_month": 100,
            },
            price_usd_monthly=0.0,
        ),

        "starter": TierDefinition(
            tier_id="starter",
            name="Starter",
            neurons_allowed=[
                "knowledge", "resilience", "compliance", "sandbox",
                "portability", "integrator",
            ],
            features={
                "ai_chat": True,
                "flights_search": True,
                "hotels_search": True,
                "booking": True,
                "update_call_system": False,
                "credential_network": False,
                "credential_portal": True,
                "daemon_bridge": False,
                "intelligence": False,
                "analytics": True,
                "webhooks": False,
                "white_label": True,
                "custom_branding": True,
                "api_access": True,
                "bulk_provisioning": False,
                "document_generation": True,
                "seatmap": True,
                "dev_terminal": False,
                "module_marketplace": False,
                "dev_ai_chat": False,
                "bundle_builder": True,
                "unified_search": True,
                "template_preview": True,
            },
            limits={
                "api_calls_per_month": 5000,
                "searches_per_day": 500,
                "bookings_per_month": 100,
                "ai_requests_per_month": 500,
                "max_passengers": 9,
                "dev_ai_requests_per_month": 0,
                "suite_ai_requests_per_month": 500,
            },
            price_usd_monthly=99.0,
        ),

        "pro": TierDefinition(
            tier_id="pro",
            name="Pro",
            neurons_allowed=[
                "knowledge", "resilience", "compliance", "sandbox",
                "portability", "intelligence", "integrator", "devterminal",
            ],
            features={
                "ai_chat": True,
                "flights_search": True,
                "hotels_search": True,
                "booking": True,
                "update_call_system": True,
                "credential_network": True,
                "credential_portal": True,
                "daemon_bridge": False,
                "intelligence": True,
                "analytics": True,
                "webhooks": True,
                "white_label": True,
                "custom_branding": True,
                "api_access": True,
                "bulk_provisioning": False,
                "document_generation": True,
                "seatmap": True,
                "dev_terminal": True,
                "module_marketplace": True,
                "dev_ai_chat": True,
                "bundle_builder": True,
                "unified_search": True,
                "template_preview": True,
            },
            limits={
                "api_calls_per_month": 25000,
                "searches_per_day": 2500,
                "bookings_per_month": 500,
                "ai_requests_per_month": 10000,
                "max_passengers": 9,
                "dev_ai_requests_per_month": 2000,
                "suite_ai_requests_per_month": 2000,
            },
            price_usd_monthly=299.0,
        ),

        "enterprise": TierDefinition(
            tier_id="enterprise",
            name="Enterprise",
            neurons_allowed=["*"],
            features={
                "ai_chat": True,
                "flights_search": True,
                "hotels_search": True,
                "booking": True,
                "update_call_system": True,
                "credential_network": True,
                "credential_portal": True,
                "daemon_bridge": True,
                "intelligence": True,
                "analytics": True,
                "webhooks": True,
                "white_label": True,
                "custom_branding": True,
                "api_access": True,
                "bulk_provisioning": True,
                "document_generation": True,
                "seatmap": True,
                "dev_terminal": True,
                "module_marketplace": True,
                "dev_ai_chat": True,
                "bundle_builder": True,
                "unified_search": True,
                "template_preview": True,
            },
            limits={
                "api_calls_per_month": -1,
                "searches_per_day": -1,
                "bookings_per_month": -1,
                "ai_requests_per_month": -1,
                "max_passengers": 9,
                "dev_ai_requests_per_month": 5000,
                "suite_ai_requests_per_month": 5000,
            },
            price_usd_monthly=799.0,
        ),
    }

    # Ordered from lowest to highest for minimum-tier lookups
    TIER_ORDER = ["free", "starter", "pro", "enterprise"]

    def __init__(self, event_bus: Optional[EventBus] = None):
        """
        Initialize the feature gate.

        Args:
            event_bus: Optional event bus for publishing ``saas.access_denied``
                       events when a check fails. Pass ``None`` for standalone
                       usage (e.g., in tests or CLI tools).
        """
        self._event_bus = event_bus

    # ------------------------------------------------------------------
    # Access Checking
    # ------------------------------------------------------------------

    def check_neuron_access(self, tier_id: str, neuron_name: str) -> AccessDecision:
        """
        Check whether a tier allows access to a specific neuron module.

        ``"*"`` in ``neurons_allowed`` grants access to every neuron.

        Args:
            tier_id:     The agency's current tier.
            neuron_name: The neuron module name to check (e.g., ``"intelligence"``).

        Returns:
            An :class:`AccessDecision` with the verdict and, if denied,
            an upgrade prompt.
        """
        tier = self.TIERS.get(tier_id)
        if tier is None:
            return AccessDecision(
                allowed=False,
                tier_id=tier_id,
                resource=neuron_name,
                reason=f"unknown_tier: {tier_id}",
                upgrade_prompt="Contact support — unrecognized billing tier.",
            )

        if "*" in tier.neurons_allowed or neuron_name in tier.neurons_allowed:
            return AccessDecision(
                allowed=True,
                tier_id=tier_id,
                resource=neuron_name,
                reason="allowed",
            )

        # Denied — find the minimum tier that includes this neuron
        min_tier = self.get_minimum_tier_for(neuron=neuron_name)
        prompt = self.get_upgrade_prompt(tier_id, neuron_name, min_tier)

        decision = AccessDecision(
            allowed=False,
            tier_id=tier_id,
            resource=neuron_name,
            reason=f"tier_required: {min_tier or 'enterprise'}",
            upgrade_prompt=prompt,
        )
        self._publish_denied(decision)
        return decision

    def check_feature_access(self, tier_id: str, feature_name: str) -> AccessDecision:
        """
        Check whether a tier has a specific feature flag enabled.

        Args:
            tier_id:      The agency's current tier.
            feature_name: Feature key (e.g., ``"webhooks"``, ``"update_call_system"``).

        Returns:
            An :class:`AccessDecision` with the verdict and, if denied,
            an upgrade prompt.
        """
        tier = self.TIERS.get(tier_id)
        if tier is None:
            return AccessDecision(
                allowed=False,
                tier_id=tier_id,
                resource=feature_name,
                reason=f"unknown_tier: {tier_id}",
                upgrade_prompt="Contact support — unrecognized billing tier.",
            )

        if tier.features.get(feature_name, False):
            return AccessDecision(
                allowed=True,
                tier_id=tier_id,
                resource=feature_name,
                reason="allowed",
            )

        # Denied — find the minimum tier that includes this feature
        min_tier = self.get_minimum_tier_for(feature=feature_name)
        prompt = self.get_upgrade_prompt(tier_id, feature_name, min_tier)

        decision = AccessDecision(
            allowed=False,
            tier_id=tier_id,
            resource=feature_name,
            reason=f"tier_required: {min_tier or 'enterprise'}",
            upgrade_prompt=prompt,
        )
        self._publish_denied(decision)
        return decision

    def check_limit(
        self,
        tier_id: str,
        resource: str,
        current_usage: int,
    ) -> AccessDecision:
        """
        Check whether current usage is within a tier's resource limit.

        A limit of ``-1`` means unlimited (always allowed).

        Args:
            tier_id:       The agency's current tier.
            resource:      Limit key (e.g., ``"api_calls_per_month"``).
            current_usage: The agency's current usage count for this resource.

        Returns:
            An :class:`AccessDecision`. When denied, ``reason`` is
            ``"limit_exceeded"`` and ``upgrade_prompt`` suggests the next tier.
        """
        tier = self.TIERS.get(tier_id)
        if tier is None:
            return AccessDecision(
                allowed=False,
                tier_id=tier_id,
                resource=resource,
                reason=f"unknown_tier: {tier_id}",
                upgrade_prompt="Contact support — unrecognized billing tier.",
            )

        limit = tier.limits.get(resource)
        if limit is None:
            # Unknown limit key — allow by default (fail open for unrecognized resources)
            return AccessDecision(
                allowed=True,
                tier_id=tier_id,
                resource=resource,
                reason="allowed",
            )

        # -1 = unlimited
        if limit == -1:
            return AccessDecision(
                allowed=True,
                tier_id=tier_id,
                resource=resource,
                reason="allowed",
            )

        if current_usage < limit:
            return AccessDecision(
                allowed=True,
                tier_id=tier_id,
                resource=resource,
                reason="allowed",
            )

        # Exceeded — suggest next tier up
        next_tier = self._next_tier(tier_id)
        if next_tier:
            next_def = self.TIERS[next_tier]
            next_limit = next_def.limits.get(resource, 0)
            limit_desc = "unlimited" if next_limit == -1 else f"{next_limit:,}"
            prompt = (
                f"You've reached your {tier.name} limit of {limit:,} {resource}. "
                f"Upgrade to {next_def.name} (${next_def.price_usd_monthly:.0f}/mo) "
                f"for {limit_desc} {resource}."
            )
        else:
            prompt = (
                f"You've reached the maximum limit of {limit:,} {resource}. "
                f"Contact sales for custom limits."
            )

        decision = AccessDecision(
            allowed=False,
            tier_id=tier_id,
            resource=resource,
            reason="limit_exceeded",
            upgrade_prompt=prompt,
        )
        self._publish_denied(decision)
        return decision

    def check_all(
        self,
        tier_id: str,
        neuron: Optional[str] = None,
        feature: Optional[str] = None,
        resource: Optional[str] = None,
        usage: int = 0,
    ) -> AccessDecision:
        """
        Combined access check: neuron + feature + limit in one call.

        Checks are evaluated in order (neuron, feature, limit) and the
        first denial short-circuits the remaining checks.

        Args:
            tier_id:  The agency's current tier.
            neuron:   Neuron module name to check (optional).
            feature:  Feature key to check (optional).
            resource: Limit key to check (optional).
            usage:    Current usage count for the resource (only used with ``resource``).

        Returns:
            The first :class:`AccessDecision` that denies access, or an
            ``allowed=True`` decision if all checks pass.
        """
        if neuron is not None:
            decision = self.check_neuron_access(tier_id, neuron)
            if not decision.allowed:
                return decision

        if feature is not None:
            decision = self.check_feature_access(tier_id, feature)
            if not decision.allowed:
                return decision

        if resource is not None:
            decision = self.check_limit(tier_id, resource, usage)
            if not decision.allowed:
                return decision

        # All checks passed (or nothing was checked)
        return AccessDecision(
            allowed=True,
            tier_id=tier_id,
            resource=neuron or feature or resource or "",
            reason="allowed",
        )

    # ------------------------------------------------------------------
    # Tier Management
    # ------------------------------------------------------------------

    def get_tier(self, tier_id: str) -> Optional[TierDefinition]:
        """
        Get a tier definition by ID.

        Args:
            tier_id: Tier identifier (``"free"``, ``"pro"``, ``"enterprise"``).

        Returns:
            The :class:`TierDefinition`, or ``None`` if not found.
        """
        return self.TIERS.get(tier_id)

    def list_tiers(self) -> List[TierDefinition]:
        """
        Return all tier definitions in ascending order (free -> enterprise).

        Returns:
            List of :class:`TierDefinition` instances.
        """
        return [self.TIERS[tid] for tid in self.TIER_ORDER if tid in self.TIERS]

    def get_upgrade_prompt(
        self,
        current_tier: str,
        requested_resource: str,
        target_tier: Optional[str] = None,
    ) -> str:
        """
        Build a human-readable upgrade message.

        Args:
            current_tier:       The agency's current tier ID.
            requested_resource: What was denied (neuron name or feature key).
            target_tier:        If known, the minimum tier needed. When ``None``,
                                the prompt defaults to suggesting the next tier up.

        Returns:
            A string like ``"Upgrade to Pro ($299/mo) for Update Call System access."``.
        """
        if target_tier and target_tier in self.TIERS:
            target = self.TIERS[target_tier]
        else:
            next_tid = self._next_tier(current_tier)
            if next_tid:
                target = self.TIERS[next_tid]
            else:
                return f"Contact sales for {requested_resource} access."

        resource_display = requested_resource.replace("_", " ").title()
        return (
            f"Upgrade to {target.name} (${target.price_usd_monthly:.0f}/mo) "
            f"for {resource_display} access."
        )

    def get_tier_comparison(self) -> Dict[str, Any]:
        """
        Build a side-by-side comparison of all tiers for display.

        Returns a dict structured for easy rendering in dashboards or
        API responses::

            {
                "tiers": [...],
                "features": {"ai_chat": {"free": True, ...}, ...},
                "limits": {"api_calls_per_month": {"free": 500, ...}, ...},
            }
        """
        tiers_list = []
        features_comparison: Dict[str, Dict[str, bool]] = {}
        limits_comparison: Dict[str, Dict[str, int]] = {}

        for tid in self.TIER_ORDER:
            tier = self.TIERS.get(tid)
            if tier is None:
                continue

            tiers_list.append({
                "tier_id": tier.tier_id,
                "name": tier.name,
                "price_usd_monthly": tier.price_usd_monthly,
                "neurons_allowed": tier.neurons_allowed,
            })

            for feat_key in ALL_FEATURE_KEYS:
                if feat_key not in features_comparison:
                    features_comparison[feat_key] = {}
                features_comparison[feat_key][tid] = tier.features.get(feat_key, False)

            for limit_key, limit_val in tier.limits.items():
                if limit_key not in limits_comparison:
                    limits_comparison[limit_key] = {}
                limits_comparison[limit_key][tid] = limit_val

        return {
            "tiers": tiers_list,
            "features": features_comparison,
            "limits": limits_comparison,
        }

    def get_minimum_tier_for(
        self,
        feature: Optional[str] = None,
        neuron: Optional[str] = None,
    ) -> Optional[str]:
        """
        Find the lowest tier that grants access to a feature or neuron.

        Args:
            feature: Feature key to look up (e.g., ``"webhooks"``).
            neuron:  Neuron module name to look up (e.g., ``"intelligence"``).

        Returns:
            The tier ID (e.g., ``"pro"``), or ``None`` if no tier grants access.
        """
        for tid in self.TIER_ORDER:
            tier = self.TIERS.get(tid)
            if tier is None:
                continue

            if feature is not None:
                if tier.features.get(feature, False):
                    return tid

            if neuron is not None:
                if "*" in tier.neurons_allowed or neuron in tier.neurons_allowed:
                    return tid

        return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _next_tier(self, current_tier: str) -> Optional[str]:
        """Return the next tier up from ``current_tier``, or ``None`` if at the top."""
        try:
            idx = self.TIER_ORDER.index(current_tier)
        except ValueError:
            return None
        if idx + 1 < len(self.TIER_ORDER):
            return self.TIER_ORDER[idx + 1]
        return None

    def _publish_denied(self, decision: AccessDecision) -> None:
        """Publish a ``saas.access_denied`` event if an event bus is wired."""
        if self._event_bus is None:
            return

        try:
            self._event_bus.publish(Event(
                type=EventType.CUSTOM,
                data={
                    "event_name": "saas.access_denied",
                    "tier_id": decision.tier_id,
                    "resource": decision.resource,
                    "reason": decision.reason,
                    "upgrade_prompt": decision.upgrade_prompt,
                },
                source="saas",
            ))
        except Exception as exc:
            logger.warning("Failed to publish saas.access_denied event: %s", exc)


# ---------------------------------------------------------------------------
# SaaSModule — NeuronModule subclass
# ---------------------------------------------------------------------------

class SaaSModule(NeuronModule):
    """
    ANASTASiA neuron module that exposes the :class:`FeatureGate`.

    This is a thin wrapper that registers the feature gate with the
    module registry so it participates in platform lifecycle (health
    checks, initialization, shutdown). The actual gating logic lives
    in :class:`FeatureGate`.

    Has no dependencies on other neurons — it is consumed by the API
    middleware layer and by other modules that need to check access.

    Usage::

        from anastasia.saas import SaaSModule

        module = SaaSModule()
        registry.register(module)
        registry.initialize_all(config)

        decision = module.gate.check_feature_access("pro", "webhooks")
    """

    def __init__(self) -> None:
        """Initialize the module (gate is wired in ``initialize``)."""
        self._gate: FeatureGate = FeatureGate()

    @property
    def name(self) -> str:
        """Unique module identifier."""
        return "saas"

    @property
    def version(self) -> str:
        """Module version."""
        return "1.0.0"

    @property
    def dependencies(self) -> List[str]:
        """No dependencies — standalone, used by api.py middleware."""
        return []

    @property
    def gate(self) -> FeatureGate:
        """The :class:`FeatureGate` instance managed by this module."""
        return self._gate

    def initialize(self, event_bus: EventBus, config: Dict[str, Any]) -> None:
        """
        Wire the event bus into the feature gate.

        Args:
            event_bus: Shared event bus for publishing access-denied events.
            config:    Platform configuration dict (currently unused by SaaS).
        """
        self._gate = FeatureGate(event_bus=event_bus)

        tier_count = len(FeatureGate.TIERS)
        feature_count = len(ALL_FEATURE_KEYS)
        logger.info(
            "SaaS neuron initialized (%d tiers, %d feature flags)",
            tier_count,
            feature_count,
        )

    def health_check(self) -> Dict[str, Any]:
        """
        Return health status of the SaaS module.

        Reports tier count, feature count, and confirms the gate is
        operational.
        """
        tier_count = len(FeatureGate.TIERS)
        feature_count = len(ALL_FEATURE_KEYS)

        return {
            "healthy": True,
            "details": "SaaS feature gating operational",
            "tier_count": tier_count,
            "feature_count": feature_count,
            "tiers": list(FeatureGate.TIERS.keys()),
        }

    def shutdown(self) -> None:
        """No-op — the feature gate holds no resources requiring cleanup."""
        logger.info("SaaS neuron shut down")
