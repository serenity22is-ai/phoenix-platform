"""
Tests for ANASTASiA Vertical Neurons — Flights + Hotels.

Validates that vertical neurons:
1. Initialize correctly with Module Registry
2. Report accurate health status
3. Plan searches across configured modules
4. Route bookings to correct modules
5. Handle event bus subscriptions
6. Integrate with the platform as registered neurons

MYSTES KYRIOS LLC — Confidential.
"""

import os
import pytest
import tempfile

from anastasia.core.events import Event, EventBus, EventType
from anastasia.modules.registry import APIModule, ModuleRegistry, VerticalType
from anastasia.modules.director import ModuleDirector
from anastasia.modules.flight_modules import (
    build_all_flight_modules,
    build_all_hotel_modules,
    build_all_modules,
    build_picasso_card,
    build_duffel_card,
    build_kiwi_card,
    build_airgateway_card,
    build_liteapi_card,
)
from anastasia.verticals.flights import FlightsNeuron
from anastasia.verticals.hotels import HotelsNeuron
from anastasia.platform import AnastasiaPlatform


@pytest.fixture
def event_bus():
    return EventBus()


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


# ---------------------------------------------------------------------------
# FlightsNeuron Tests
# ---------------------------------------------------------------------------


class TestFlightsNeuron:
    def test_name(self):
        neuron = FlightsNeuron()
        assert neuron.name == "flights"

    def test_version(self):
        neuron = FlightsNeuron()
        assert neuron.version == "1.0.0"

    def test_dependencies(self):
        neuron = FlightsNeuron()
        assert "knowledge" in neuron.dependencies

    def test_health_before_init(self):
        neuron = FlightsNeuron()
        health = neuron.health_check()
        assert health["healthy"] is False
        assert "not initialized" in health["details"].lower()

    def test_initialize(self, event_bus):
        neuron = FlightsNeuron()
        neuron.initialize(event_bus, {})

        health = neuron.health_check()
        # Unhealthy because no credentials are configured
        assert health["vertical"] == "flights"
        assert health["modules_total"] == 7  # All 7 flight modules registered
        assert health["modules_configured"] == 0  # None configured (no env vars)
        assert health["can_search"] is False
        assert health["can_book"] is False

    def test_initialize_with_pre_built_registry(self, event_bus):
        """When a flights_registry is passed in config, use it."""
        registry = ModuleRegistry()
        card = build_picasso_card()
        mod = APIModule(knowledge_card=card)
        # Simulate credentials being set
        os.environ["PICASSO_SESSION_TOKEN"] = "test_token_12345678"
        try:
            mod.check_configured()
            registry.register(mod)

            neuron = FlightsNeuron()
            neuron.initialize(event_bus, {"flights_registry": registry})

            health = neuron.health_check()
            assert health["modules_configured"] == 1
            assert "Picasso/Redbox" in health["module_names"]
            assert health["can_search"] is True
            assert health["has_arbitrage"] is True
        finally:
            del os.environ["PICASSO_SESSION_TOKEN"]

    def test_plan_search(self, event_bus):
        """Director should create a search plan from configured modules."""
        registry = ModuleRegistry()
        card = build_picasso_card()
        mod = APIModule(knowledge_card=card)
        os.environ["PICASSO_SESSION_TOKEN"] = "test_token_12345678"
        try:
            mod.check_configured()
            registry.register(mod)

            neuron = FlightsNeuron()
            neuron.initialize(event_bus, {"flights_registry": registry})

            plan = neuron.plan_search(origin="JFK", destination="LHR")
            assert plan.primary == "picasso_redbox"
            assert "picasso_redbox" in plan.modules
            assert plan.merge_strategy == "cheapest_wins_with_arbitrage"
        finally:
            del os.environ["PICASSO_SESSION_TOKEN"]

    def test_plan_search_not_initialized(self):
        neuron = FlightsNeuron()
        plan = neuron.plan_search()
        assert plan.modules == []
        assert "Not initialized" in plan.notes

    def test_get_search_modules(self, event_bus):
        neuron = FlightsNeuron()
        neuron.initialize(event_bus, {})
        modules = neuron.get_search_modules()
        # No credentials = no configured modules
        assert modules == []

    def test_route_booking(self, event_bus):
        registry = ModuleRegistry()
        card = build_duffel_card()
        mod = APIModule(knowledge_card=card)
        os.environ["DUFFEL_ACCESS_TOKEN"] = "duffel_test_1234567890"
        try:
            mod.check_configured()
            registry.register(mod)

            neuron = FlightsNeuron()
            neuron.initialize(event_bus, {"flights_registry": registry})

            route = neuron.route_booking(source="ndc")
            assert route is not None
            assert route.module_id == "duffel_ndc"
        finally:
            del os.environ["DUFFEL_ACCESS_TOKEN"]

    def test_generate_system_prompt(self, event_bus):
        registry = ModuleRegistry()
        card = build_picasso_card()
        mod = APIModule(knowledge_card=card)
        os.environ["PICASSO_SESSION_TOKEN"] = "test_token_12345678"
        try:
            mod.check_configured()
            registry.register(mod)

            neuron = FlightsNeuron()
            neuron.initialize(event_bus, {"flights_registry": registry})

            prompt = neuron.generate_system_prompt()
            assert "AVAILABLE API MODULES" in prompt
            assert "Picasso/Redbox" in prompt
        finally:
            del os.environ["PICASSO_SESSION_TOKEN"]

    def test_get_capabilities(self, event_bus):
        registry = ModuleRegistry()
        card = build_picasso_card()
        mod = APIModule(knowledge_card=card)
        os.environ["PICASSO_SESSION_TOKEN"] = "test_token_12345678"
        try:
            mod.check_configured()
            registry.register(mod)

            neuron = FlightsNeuron()
            neuron.initialize(event_bus, {"flights_registry": registry})

            caps = neuron.get_capabilities()
            assert "search" in caps
            assert "book" in caps
            assert "picasso_redbox" in caps["search"]
        finally:
            del os.environ["PICASSO_SESSION_TOKEN"]

    def test_event_tracking(self, event_bus):
        neuron = FlightsNeuron()
        neuron.initialize(event_bus, {})

        # Publish search event
        event_bus.publish(Event(
            type=EventType.SEARCH_COMPLETED,
            source="booking_agent",
            data={"route": "JFK-LHR", "results": []},
        ))

        health = neuron.health_check()
        assert health["searches_handled"] == 1
        assert health["bookings_handled"] == 0

        # Publish booking event
        event_bus.publish(Event(
            type=EventType.BOOKING_CREATED,
            source="booking_agent",
            data={"booking_id": "BK001", "source": "picasso"},
        ))

        health = neuron.health_check()
        assert health["bookings_handled"] == 1

    def test_shutdown(self, event_bus):
        neuron = FlightsNeuron()
        neuron.initialize(event_bus, {})
        neuron.shutdown()

        health = neuron.health_check()
        assert health["healthy"] is False

    def test_registry_accessor(self, event_bus):
        neuron = FlightsNeuron()
        assert neuron.registry is None

        neuron.initialize(event_bus, {})
        assert neuron.registry is not None

    def test_director_accessor(self, event_bus):
        neuron = FlightsNeuron()
        assert neuron.director is None

        neuron.initialize(event_bus, {})
        assert neuron.director is not None

    def test_multi_module_search_plan(self, event_bus):
        """Search plan with multiple configured modules."""
        registry = ModuleRegistry()

        os.environ["PICASSO_SESSION_TOKEN"] = "test_token_12345678"
        os.environ["DUFFEL_ACCESS_TOKEN"] = "duffel_test_1234567890"
        os.environ["KIWI_API_KEY"] = "kiwi_test_key_12345678"
        try:
            for card_fn in [build_picasso_card, build_duffel_card, build_kiwi_card]:
                card = card_fn()
                mod = APIModule(knowledge_card=card)
                env_var = card.credential_env_vars[0]
                mod.check_configured()
                registry.register(mod)

            neuron = FlightsNeuron()
            neuron.initialize(event_bus, {"flights_registry": registry})

            plan = neuron.plan_search()
            assert len(plan.modules) == 3
            assert plan.primary == "picasso_redbox"  # Highest priority
            assert plan.estimated_sources == 3
        finally:
            del os.environ["PICASSO_SESSION_TOKEN"]
            del os.environ["DUFFEL_ACCESS_TOKEN"]
            del os.environ["KIWI_API_KEY"]


# ---------------------------------------------------------------------------
# HotelsNeuron Tests
# ---------------------------------------------------------------------------


class TestHotelsNeuron:
    def test_name(self):
        neuron = HotelsNeuron()
        assert neuron.name == "hotels"

    def test_version(self):
        neuron = HotelsNeuron()
        assert neuron.version == "1.0.0"

    def test_dependencies(self):
        neuron = HotelsNeuron()
        assert "knowledge" in neuron.dependencies

    def test_health_before_init(self):
        neuron = HotelsNeuron()
        health = neuron.health_check()
        assert health["healthy"] is False

    def test_initialize_disabled(self, event_bus):
        """Hotels should be disabled by default (Phase 1 — flights only)."""
        neuron = HotelsNeuron()
        neuron.initialize(event_bus, {})

        health = neuron.health_check()
        assert health["vertical"] == "hotels"
        assert health["enabled"] is False
        assert health["healthy"] is True  # Neuron itself is healthy, just gated
        assert "disabled" in health["details"].lower()

    def test_initialize_enabled(self, event_bus):
        neuron = HotelsNeuron()
        neuron.initialize(event_bus, {"hotels_enabled": True})

        health = neuron.health_check()
        assert health["enabled"] is True
        assert health["modules_total"] == 1  # liteAPI
        assert health["modules_configured"] == 0  # No LITEAPI_KEY set

    def test_initialize_with_credentials(self, event_bus):
        """With LITEAPI_KEY set, hotels module should be configured."""
        os.environ["LITEAPI_KEY"] = "sand_test_key_1234567890"
        try:
            neuron = HotelsNeuron()
            neuron.initialize(event_bus, {"hotels_enabled": True})

            health = neuron.health_check()
            assert health["enabled"] is True
            assert health["modules_configured"] == 1
            assert "liteAPI Hotels" in health["module_names"]
            assert health["can_search"] is True
            assert health["can_book"] is True
        finally:
            del os.environ["LITEAPI_KEY"]

    def test_enable_disable(self, event_bus):
        neuron = HotelsNeuron()
        neuron.initialize(event_bus, {})

        assert neuron.is_enabled is False
        neuron.enable()
        assert neuron.is_enabled is True
        neuron.disable()
        assert neuron.is_enabled is False

    def test_plan_search_disabled(self, event_bus):
        neuron = HotelsNeuron()
        neuron.initialize(event_bus, {})  # Disabled by default

        plan = neuron.plan_search()
        assert plan.modules == []
        assert "disabled" in plan.notes[0].lower()

    def test_plan_search_enabled(self, event_bus):
        os.environ["LITEAPI_KEY"] = "sand_test_key_1234567890"
        try:
            neuron = HotelsNeuron()
            neuron.initialize(event_bus, {"hotels_enabled": True})

            plan = neuron.plan_search(city="Paris", country="FR")
            assert len(plan.modules) == 1
            assert plan.primary == "liteapi_hotels"
        finally:
            del os.environ["LITEAPI_KEY"]

    def test_get_search_modules_disabled(self, event_bus):
        neuron = HotelsNeuron()
        neuron.initialize(event_bus, {})
        assert neuron.get_search_modules() == []

    def test_event_tracking(self, event_bus):
        neuron = HotelsNeuron()
        neuron.initialize(event_bus, {"hotels_enabled": True})

        event_bus.publish(Event(
            type=EventType.BOOKING_CREATED,
            source="hotels",
            data={"booking_id": "HB001", "source": "liteapi"},
        ))

        health = neuron.health_check()
        assert health["bookings_handled"] == 1

    def test_shutdown(self, event_bus):
        neuron = HotelsNeuron()
        neuron.initialize(event_bus, {})
        neuron.shutdown()

        health = neuron.health_check()
        assert health["healthy"] is False

    def test_registry_accessor(self, event_bus):
        neuron = HotelsNeuron()
        neuron.initialize(event_bus, {})
        assert neuron.registry is not None

    def test_director_accessor(self, event_bus):
        neuron = HotelsNeuron()
        neuron.initialize(event_bus, {})
        assert neuron.director is not None


# ---------------------------------------------------------------------------
# Platform Integration Tests
# ---------------------------------------------------------------------------


class TestVerticalPlatformIntegration:
    def test_platform_includes_verticals(self, temp_dir):
        """Platform should include both flights and hotels neurons."""
        platform = AnastasiaPlatform({"data_dir": temp_dir})
        results = platform.start()

        assert "flights" in results
        assert "hotels" in results
        assert results["flights"] is True
        assert results["hotels"] is True

        platform.stop()

    def test_flights_neuron_accessible(self, temp_dir):
        platform = AnastasiaPlatform({"data_dir": temp_dir})
        platform.start()

        flights = platform.get_module("flights")
        assert flights is not None
        assert flights.name == "flights"

        health = flights.health_check()
        assert health["vertical"] == "flights"
        assert health["modules_total"] == 7  # All 7 known flight sources

        platform.stop()

    def test_hotels_neuron_accessible(self, temp_dir):
        platform = AnastasiaPlatform({"data_dir": temp_dir})
        platform.start()

        hotels = platform.get_module("hotels")
        assert hotels is not None
        assert hotels.name == "hotels"

        health = hotels.health_check()
        assert health["vertical"] == "hotels"
        assert health["enabled"] is False  # Phase 1 default

        platform.stop()

    def test_verticals_in_module_list(self, temp_dir):
        """Both verticals should appear in platform module listing."""
        platform = AnastasiaPlatform({"data_dir": temp_dir})
        platform.start()

        modules = platform.list_modules()
        names = {m["name"] for m in modules}
        assert "flights" in names
        assert "hotels" in names

        platform.stop()

    def test_vertical_event_integration(self, temp_dir):
        """Vertical neurons should receive events from the platform event bus."""
        platform = AnastasiaPlatform({"data_dir": temp_dir})
        platform.start()

        flights = platform.get_module("flights")
        bus = platform.get_event_bus()

        # Publish a search event
        bus.publish(Event(
            type=EventType.SEARCH_COMPLETED,
            source="booking_agent",
            data={"route": "JFK-LHR", "results": [], "source": "picasso"},
        ))

        health = flights.health_check()
        assert health["searches_handled"] == 1

        platform.stop()


# ---------------------------------------------------------------------------
# AirGateway Knowledge Card Tests
# ---------------------------------------------------------------------------


class TestAirGatewayCard:
    def test_airgateway_card_details(self):
        card = build_airgateway_card()

        assert card.module_id == "airgateway_ndc"
        assert card.name == "AirGateway NDC"
        assert card.vendor == "AirGateway"
        assert card.version == "1.2"
        assert card.source_type == "ndc"
        assert card.vertical == "flights"
        assert card.auth_type == "api_key_header"
        assert card.carrier_count == 25

    def test_airgateway_has_pos_arbitrage(self):
        card = build_airgateway_card()
        assert card.capabilities["pos_arbitrage"] is True
        assert "pos_arbitrage" in card.strengths
        assert "102_country_pos" in card.strengths

    def test_airgateway_passenger_format(self):
        card = build_airgateway_card()
        pf = card.passenger_format
        assert pf["name_fields"] == ["nameGiven", "surname"]
        assert pf["gender_values"] == ["Male", "Female"]
        assert pf["type_codes"] == ["ADT", "CHD", "INF"]
        assert pf["title_values"] == ["MR", "MRS", "MS", "MISS"]
        assert pf["dob_format"] == "YYYY-MM-DD"

    def test_airgateway_priority(self):
        card = build_airgateway_card()
        assert card.priority == 85  # High — NDC + POS arbitrage

    def test_airgateway_readiness(self):
        card = build_airgateway_card()
        assert card.readiness == "tested"
        assert card.confidence == 0.90

    def test_airgateway_quirks(self):
        card = build_airgateway_card()
        assert len(card.quirks) >= 5
        # Check for the auth quirk
        auth_quirks = [q for q in card.quirks if "Bearer" in q.get("workaround", "")]
        assert len(auth_quirks) >= 1

    def test_airgateway_booking_steps(self):
        card = build_airgateway_card()
        assert card.booking_steps == ["search", "verify_price", "create_order"]

    def test_airgateway_credential_env_vars(self):
        card = build_airgateway_card()
        assert "AIRGATEWAY_API_KEY" in card.credential_env_vars
