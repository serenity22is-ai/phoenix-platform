"""
Tests for SaaS Feature Gating -- tier-based access control for ANASTASiA neurons.

Covers tier definitions, neuron access checks, feature flag checks, resource
limit enforcement, combined checks, upgrade prompts, tier comparison, minimum
tier lookups, and SaaSModule lifecycle.

MYSTES KYRIOS LLC -- Confidential.
"""

import pytest

from anastasia.core.events import EventBus
from anastasia.saas import SaaSModule, FeatureGate, TierDefinition, AccessDecision


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def gate():
    """Create a FeatureGate without an event bus (standalone mode)."""
    return FeatureGate()


@pytest.fixture
def gate_with_bus():
    """Create a FeatureGate wired to an event bus."""
    bus = EventBus()
    return FeatureGate(event_bus=bus), bus


@pytest.fixture
def saas_module():
    """Create a SaaSModule instance."""
    return SaaSModule()


# ---------------------------------------------------------------------------
# Tier Definitions
# ---------------------------------------------------------------------------

class TestTierDefinitions:
    """Verify the four tiers are defined with correct attributes."""

    def test_four_tiers_defined(self, gate):
        """TIERS dict contains exactly free, starter, pro, enterprise."""
        expected = {"free", "starter", "pro", "enterprise"}
        assert set(gate.TIERS.keys()) == expected

    def test_free_tier_limits(self, gate):
        """Free tier has 500 api calls, 50 searches, 0 bookings."""
        free = gate.TIERS["free"]
        assert free.limits["api_calls_per_month"] == 500
        assert free.limits["searches_per_day"] == 50
        assert free.limits["bookings_per_month"] == 0

    def test_enterprise_unlimited(self, gate):
        """Enterprise tier has all major limits set to -1 (unlimited)."""
        ent = gate.TIERS["enterprise"]
        assert ent.limits["api_calls_per_month"] == -1
        assert ent.limits["searches_per_day"] == -1
        assert ent.limits["bookings_per_month"] == -1
        assert ent.limits["ai_requests_per_month"] == -1


# ---------------------------------------------------------------------------
# Neuron Access
# ---------------------------------------------------------------------------

class TestNeuronAccess:
    """Neuron-level access checks based on tier."""

    def test_check_neuron_access_allowed(self, gate):
        """Pro tier can access the intelligence neuron."""
        decision = gate.check_neuron_access("pro", "intelligence")
        assert decision.allowed is True
        assert decision.reason == "allowed"

    def test_check_neuron_access_denied(self, gate):
        """Free tier cannot access the intelligence neuron."""
        decision = gate.check_neuron_access("free", "intelligence")
        assert decision.allowed is False
        assert "tier_required" in decision.reason
        assert decision.upgrade_prompt is not None

    def test_enterprise_all_neurons(self, gate):
        """Enterprise has '*' in neurons_allowed, granting access to any neuron."""
        ent = gate.TIERS["enterprise"]
        assert "*" in ent.neurons_allowed

        # Any arbitrary neuron name should be allowed
        decision = gate.check_neuron_access("enterprise", "anything_at_all")
        assert decision.allowed is True


# ---------------------------------------------------------------------------
# Feature Access
# ---------------------------------------------------------------------------

class TestFeatureAccess:
    """Feature-flag access checks based on tier."""

    def test_check_feature_access_allowed(self, gate):
        """Pro tier has update_call_system enabled."""
        decision = gate.check_feature_access("pro", "update_call_system")
        assert decision.allowed is True

    def test_check_feature_access_denied(self, gate):
        """Free tier does not have update_call_system enabled."""
        decision = gate.check_feature_access("free", "update_call_system")
        assert decision.allowed is False
        assert decision.upgrade_prompt is not None
        assert "tier_required" in decision.reason


# ---------------------------------------------------------------------------
# Limit Checks
# ---------------------------------------------------------------------------

class TestLimitChecks:
    """Resource limit enforcement based on tier."""

    def test_check_limit_within(self, gate):
        """100 used out of 10000 pro api calls is allowed."""
        decision = gate.check_limit("pro", "api_calls_per_month", 100)
        assert decision.allowed is True

    def test_check_limit_exceeded(self, gate):
        """25001 used out of 25000 pro api calls is denied."""
        decision = gate.check_limit("pro", "api_calls_per_month", 25001)
        assert decision.allowed is False
        assert decision.reason == "limit_exceeded"
        assert decision.upgrade_prompt is not None

    def test_check_limit_unlimited(self, gate):
        """Enterprise -1 limit means always allowed regardless of usage."""
        decision = gate.check_limit("enterprise", "api_calls_per_month", 999999)
        assert decision.allowed is True


# ---------------------------------------------------------------------------
# Combined Check
# ---------------------------------------------------------------------------

class TestCombinedCheck:
    """check_all evaluates neuron + feature + limit in one call."""

    def test_check_all_combined(self, gate):
        """Pro tier with reasonable usage passes all three checks."""
        decision = gate.check_all(
            tier_id="pro",
            neuron="intelligence",
            feature="update_call_system",
            resource="api_calls_per_month",
            usage=500,
        )
        assert decision.allowed is True

    def test_check_all_neuron_denied(self, gate):
        """Free tier fails on neuron check before reaching feature or limit."""
        decision = gate.check_all(
            tier_id="free",
            neuron="intelligence",
            feature="booking",
            resource="api_calls_per_month",
            usage=10,
        )
        assert decision.allowed is False
        assert decision.resource == "intelligence"


# ---------------------------------------------------------------------------
# Upgrade Prompts & Tier Comparison
# ---------------------------------------------------------------------------

class TestUpgradeAndComparison:
    """Upgrade prompts and tier comparison output."""

    def test_get_upgrade_prompt(self, gate):
        """get_upgrade_prompt returns a readable human-facing message."""
        prompt = gate.get_upgrade_prompt("free", "update_call_system", "pro")
        assert isinstance(prompt, str)
        assert "Pro" in prompt
        assert "$299" in prompt
        assert "Update Call System" in prompt

    def test_get_tier_comparison(self, gate):
        """get_tier_comparison returns a side-by-side dict with tiers/features/limits."""
        comparison = gate.get_tier_comparison()
        assert "tiers" in comparison
        assert "features" in comparison
        assert "limits" in comparison

        tier_ids = [t["tier_id"] for t in comparison["tiers"]]
        assert tier_ids == ["free", "starter", "pro", "enterprise"]

        # Verify feature comparison has entries for each tier
        assert "ai_chat" in comparison["features"]
        assert set(comparison["features"]["ai_chat"].keys()) == {
            "free", "starter", "pro", "enterprise"
        }


# ---------------------------------------------------------------------------
# Minimum Tier Lookups
# ---------------------------------------------------------------------------

class TestMinimumTierLookups:
    """Finding the lowest tier that grants a feature or neuron."""

    def test_get_minimum_tier_for_feature(self, gate):
        """credential_network requires pro tier."""
        min_tier = gate.get_minimum_tier_for(feature="credential_network")
        assert min_tier == "pro"

    def test_get_minimum_tier_for_neuron(self, gate):
        """intelligence neuron requires pro tier."""
        min_tier = gate.get_minimum_tier_for(neuron="intelligence")
        assert min_tier == "pro"


# ---------------------------------------------------------------------------
# Unknown Tier
# ---------------------------------------------------------------------------

class TestUnknownTier:
    """Handling of unrecognized tier IDs."""

    def test_unknown_tier_returns_none(self, gate):
        """get_tier with a nonexistent tier ID returns None."""
        result = gate.get_tier("nonexistent")
        assert result is None


# ---------------------------------------------------------------------------
# SaaSModule Lifecycle
# ---------------------------------------------------------------------------

class TestSaaSModule:
    """SaaSModule NeuronModule lifecycle: name, initialize, health_check."""

    def test_saas_module_name(self, saas_module):
        """Module name is 'saas'."""
        assert saas_module.name == "saas"

    def test_saas_module_initialize(self, saas_module):
        """initialize wires the event bus and creates a new FeatureGate."""
        bus = EventBus()
        saas_module.initialize(event_bus=bus, config={})

        # After initialization the gate should be functional
        decision = saas_module.gate.check_feature_access("pro", "webhooks")
        assert decision.allowed is True

    def test_saas_module_health_check(self, saas_module):
        """health_check returns healthy status with tier and feature counts."""
        health = saas_module.health_check()
        assert health["healthy"] is True
        assert health["tier_count"] == 4
        assert health["feature_count"] > 0
        assert "tiers" in health
        assert "free" in health["tiers"]
        assert "starter" in health["tiers"]
        assert "enterprise" in health["tiers"]
