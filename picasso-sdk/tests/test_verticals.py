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
from anastasia.modules.car_modules import build_all_car_modules, build_discover_cars_card
from anastasia.modules.activity_modules import build_all_activity_modules, build_viator_card
from anastasia.modules.insurance_modules import build_all_insurance_modules, build_safetywing_card
from anastasia.verticals.flights import FlightsNeuron
from anastasia.verticals.hotels import HotelsNeuron
from anastasia.verticals.cars import CarsNeuron
from anastasia.verticals.activities import ActivitiesNeuron
from anastasia.verticals.insurance import InsuranceNeuron
from anastasia.platform import AnastasiaPlatform
from anastasia.dispatch.coordinator import VerticalSearchCoordinator


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
        assert health["modules_total"] == 2  # liteAPI + Duffel Stays
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


# ---------------------------------------------------------------------------
# CarsNeuron Tests (Build #181)
# ---------------------------------------------------------------------------


class TestCarsNeuron:
    def test_name(self):
        neuron = CarsNeuron()
        assert neuron.name == "cars"

    def test_version(self):
        neuron = CarsNeuron()
        assert neuron.version == "1.0.0"

    def test_dependencies(self):
        neuron = CarsNeuron()
        assert "knowledge" in neuron.dependencies

    def test_health_before_init(self):
        neuron = CarsNeuron()
        health = neuron.health_check()
        assert health["healthy"] is False
        assert "not initialized" in health["details"].lower()

    def test_initialize_disabled(self, event_bus):
        neuron = CarsNeuron()
        neuron.initialize(event_bus, {"cars_enabled": False})

        health = neuron.health_check()
        assert health["vertical"] == "cars"
        assert health["enabled"] is False
        assert health["healthy"] is True
        assert "disabled" in health["details"].lower()

    def test_initialize_enabled(self, event_bus):
        neuron = CarsNeuron()
        neuron.initialize(event_bus, {"cars_enabled": True})

        health = neuron.health_check()
        assert health["enabled"] is True
        assert health["modules_total"] == 1  # Discover Cars
        assert health["modules_configured"] == 0  # No env vars set

    def test_initialize_with_credentials(self, event_bus):
        os.environ["DISCOVER_CARS_USERNAME"] = "test_user"
        os.environ["DISCOVER_CARS_PASSWORD"] = "test_pass"
        os.environ["DISCOVER_CARS_TOKEN"] = "test_token_12345678"
        try:
            neuron = CarsNeuron()
            neuron.initialize(event_bus, {"cars_enabled": True})

            health = neuron.health_check()
            assert health["modules_configured"] == 1
            assert health["can_search"] is True
            assert health["can_book"] is True
        finally:
            del os.environ["DISCOVER_CARS_USERNAME"]
            del os.environ["DISCOVER_CARS_PASSWORD"]
            del os.environ["DISCOVER_CARS_TOKEN"]

    def test_enable_disable(self, event_bus):
        neuron = CarsNeuron()
        neuron.initialize(event_bus, {"cars_enabled": False})

        assert neuron.is_enabled is False
        neuron.enable()
        assert neuron.is_enabled is True
        neuron.disable()
        assert neuron.is_enabled is False

    def test_plan_search_disabled(self, event_bus):
        neuron = CarsNeuron()
        neuron.initialize(event_bus, {"cars_enabled": False})

        plan = neuron.plan_search()
        assert plan.modules == []
        assert "disabled" in plan.notes[0].lower()

    def test_plan_search_enabled(self, event_bus):
        os.environ["DISCOVER_CARS_USERNAME"] = "test_user"
        os.environ["DISCOVER_CARS_PASSWORD"] = "test_pass"
        os.environ["DISCOVER_CARS_TOKEN"] = "test_token_12345678"
        try:
            neuron = CarsNeuron()
            neuron.initialize(event_bus, {"cars_enabled": True})

            plan = neuron.plan_search(location="Paris")
            assert len(plan.modules) == 1
            assert plan.primary == "discover_cars"
        finally:
            del os.environ["DISCOVER_CARS_USERNAME"]
            del os.environ["DISCOVER_CARS_PASSWORD"]
            del os.environ["DISCOVER_CARS_TOKEN"]

    def test_event_tracking(self, event_bus):
        neuron = CarsNeuron()
        neuron.initialize(event_bus, {"cars_enabled": True})

        event_bus.publish(Event(
            type=EventType.BOOKING_CREATED,
            source="cars",
            data={"booking_id": "CB001", "source": "discover_cars"},
        ))

        health = neuron.health_check()
        assert health["bookings_handled"] == 1

    def test_shutdown(self, event_bus):
        neuron = CarsNeuron()
        neuron.initialize(event_bus, {})
        neuron.shutdown()

        health = neuron.health_check()
        assert health["healthy"] is False

    def test_registry_accessor(self, event_bus):
        neuron = CarsNeuron()
        neuron.initialize(event_bus, {})
        assert neuron.registry is not None

    def test_director_accessor(self, event_bus):
        neuron = CarsNeuron()
        neuron.initialize(event_bus, {})
        assert neuron.director is not None


# ---------------------------------------------------------------------------
# ActivitiesNeuron Tests (Build #181)
# ---------------------------------------------------------------------------


class TestActivitiesNeuron:
    def test_name(self):
        neuron = ActivitiesNeuron()
        assert neuron.name == "activities"

    def test_version(self):
        neuron = ActivitiesNeuron()
        assert neuron.version == "1.0.0"

    def test_dependencies(self):
        neuron = ActivitiesNeuron()
        assert "knowledge" in neuron.dependencies

    def test_health_before_init(self):
        neuron = ActivitiesNeuron()
        health = neuron.health_check()
        assert health["healthy"] is False
        assert "not initialized" in health["details"].lower()

    def test_initialize_disabled(self, event_bus):
        neuron = ActivitiesNeuron()
        neuron.initialize(event_bus, {"activities_enabled": False})

        health = neuron.health_check()
        assert health["vertical"] == "activities"
        assert health["enabled"] is False
        assert health["healthy"] is True

    def test_initialize_enabled(self, event_bus):
        neuron = ActivitiesNeuron()
        neuron.initialize(event_bus, {"activities_enabled": True})

        health = neuron.health_check()
        assert health["enabled"] is True
        assert health["modules_total"] == 1  # Viator
        assert health["modules_configured"] == 0

    def test_initialize_with_credentials(self, event_bus):
        os.environ["VIATOR_API_KEY"] = "viator_test_key_12345678"
        try:
            neuron = ActivitiesNeuron()
            neuron.initialize(event_bus, {"activities_enabled": True})

            health = neuron.health_check()
            assert health["modules_configured"] == 1
            assert health["can_search"] is True
            assert health["can_book"] is True
        finally:
            del os.environ["VIATOR_API_KEY"]

    def test_enable_disable(self, event_bus):
        neuron = ActivitiesNeuron()
        neuron.initialize(event_bus, {"activities_enabled": False})

        assert neuron.is_enabled is False
        neuron.enable()
        assert neuron.is_enabled is True
        neuron.disable()
        assert neuron.is_enabled is False

    def test_plan_search_disabled(self, event_bus):
        neuron = ActivitiesNeuron()
        neuron.initialize(event_bus, {"activities_enabled": False})

        plan = neuron.plan_search()
        assert plan.modules == []
        assert "disabled" in plan.notes[0].lower()

    def test_plan_search_enabled(self, event_bus):
        os.environ["VIATOR_API_KEY"] = "viator_test_key_12345678"
        try:
            neuron = ActivitiesNeuron()
            neuron.initialize(event_bus, {"activities_enabled": True})

            plan = neuron.plan_search(destination="Paris")
            assert len(plan.modules) == 1
            assert plan.primary == "viator_activities"
        finally:
            del os.environ["VIATOR_API_KEY"]

    def test_event_tracking(self, event_bus):
        neuron = ActivitiesNeuron()
        neuron.initialize(event_bus, {"activities_enabled": True})

        event_bus.publish(Event(
            type=EventType.BOOKING_CREATED,
            source="activities",
            data={"booking_id": "AB001", "source": "viator"},
        ))

        health = neuron.health_check()
        assert health["bookings_handled"] == 1

    def test_shutdown(self, event_bus):
        neuron = ActivitiesNeuron()
        neuron.initialize(event_bus, {})
        neuron.shutdown()

        health = neuron.health_check()
        assert health["healthy"] is False

    def test_registry_accessor(self, event_bus):
        neuron = ActivitiesNeuron()
        neuron.initialize(event_bus, {})
        assert neuron.registry is not None

    def test_director_accessor(self, event_bus):
        neuron = ActivitiesNeuron()
        neuron.initialize(event_bus, {})
        assert neuron.director is not None


# ---------------------------------------------------------------------------
# InsuranceNeuron Tests (Build #181)
# ---------------------------------------------------------------------------


class TestInsuranceNeuron:
    def test_name(self):
        neuron = InsuranceNeuron()
        assert neuron.name == "insurance"

    def test_version(self):
        neuron = InsuranceNeuron()
        assert neuron.version == "1.0.0"

    def test_dependencies(self):
        neuron = InsuranceNeuron()
        assert "knowledge" in neuron.dependencies

    def test_health_before_init(self):
        neuron = InsuranceNeuron()
        health = neuron.health_check()
        assert health["healthy"] is False
        assert "not initialized" in health["details"].lower()

    def test_initialize_disabled(self, event_bus):
        neuron = InsuranceNeuron()
        neuron.initialize(event_bus, {"insurance_enabled": False})

        health = neuron.health_check()
        assert health["vertical"] == "insurance"
        assert health["enabled"] is False
        assert health["healthy"] is True

    def test_initialize_enabled(self, event_bus):
        neuron = InsuranceNeuron()
        neuron.initialize(event_bus, {"insurance_enabled": True})

        health = neuron.health_check()
        assert health["enabled"] is True
        assert health["modules_total"] == 1  # SafetyWing
        assert health["modules_configured"] == 0

    def test_initialize_with_credentials(self, event_bus):
        os.environ["SAFETYWING_API_KEY"] = "safetywing_test_key_12345678"
        try:
            neuron = InsuranceNeuron()
            neuron.initialize(event_bus, {"insurance_enabled": True})

            health = neuron.health_check()
            assert health["modules_configured"] == 1
            assert health["can_search"] is True
            assert health["can_book"] is True
        finally:
            del os.environ["SAFETYWING_API_KEY"]

    def test_enable_disable(self, event_bus):
        neuron = InsuranceNeuron()
        neuron.initialize(event_bus, {"insurance_enabled": False})

        assert neuron.is_enabled is False
        neuron.enable()
        assert neuron.is_enabled is True
        neuron.disable()
        assert neuron.is_enabled is False

    def test_plan_search_disabled(self, event_bus):
        neuron = InsuranceNeuron()
        neuron.initialize(event_bus, {"insurance_enabled": False})

        plan = neuron.plan_search()
        assert plan.modules == []
        assert "disabled" in plan.notes[0].lower()

    def test_plan_search_enabled(self, event_bus):
        os.environ["SAFETYWING_API_KEY"] = "safetywing_test_key_12345678"
        try:
            neuron = InsuranceNeuron()
            neuron.initialize(event_bus, {"insurance_enabled": True})

            plan = neuron.plan_search(destination_country="FR")
            assert len(plan.modules) == 1
            assert plan.primary == "safetywing_insurance"
        finally:
            del os.environ["SAFETYWING_API_KEY"]

    def test_event_tracking(self, event_bus):
        neuron = InsuranceNeuron()
        neuron.initialize(event_bus, {"insurance_enabled": True})

        event_bus.publish(Event(
            type=EventType.BOOKING_CREATED,
            source="insurance",
            data={"booking_id": "IB001", "source": "safetywing"},
        ))

        health = neuron.health_check()
        assert health["bookings_handled"] == 1

    def test_shutdown(self, event_bus):
        neuron = InsuranceNeuron()
        neuron.initialize(event_bus, {})
        neuron.shutdown()

        health = neuron.health_check()
        assert health["healthy"] is False

    def test_registry_accessor(self, event_bus):
        neuron = InsuranceNeuron()
        neuron.initialize(event_bus, {})
        assert neuron.registry is not None

    def test_director_accessor(self, event_bus):
        neuron = InsuranceNeuron()
        neuron.initialize(event_bus, {})
        assert neuron.director is not None


# ---------------------------------------------------------------------------
# Knowledge Card Module Builder Tests (Build #181)
# ---------------------------------------------------------------------------


class TestCarModules:
    def test_discover_cars_card(self):
        card = build_discover_cars_card()
        assert card.module_id == "discover_cars"
        assert card.vertical == "car_rental"
        assert card.carrier_count == 500
        assert card.capabilities["search"] is True
        assert card.capabilities["book"] is True

    def test_build_all_car_modules(self):
        modules = build_all_car_modules(from_json=True)
        assert len(modules) >= 1
        assert modules[0].knowledge_card.vertical == "car_rental"


class TestActivityModules:
    def test_viator_card(self):
        card = build_viator_card()
        assert card.module_id == "viator_activities"
        assert card.vertical == "activities"
        assert card.carrier_count == 300000
        assert card.capabilities["search"] is True
        assert card.capabilities["book"] is True

    def test_build_all_activity_modules(self):
        modules = build_all_activity_modules(from_json=True)
        assert len(modules) >= 1
        assert modules[0].knowledge_card.vertical == "activities"


class TestInsuranceModules:
    def test_safetywing_card(self):
        card = build_safetywing_card()
        assert card.module_id == "safetywing_insurance"
        assert card.vertical == "insurance"
        assert card.carrier_count == 2
        assert card.capabilities["search"] is True
        assert card.capabilities["book"] is True

    def test_build_all_insurance_modules(self):
        modules = build_all_insurance_modules(from_json=True)
        assert len(modules) >= 1
        assert modules[0].knowledge_card.vertical == "insurance"


# ---------------------------------------------------------------------------
# Updated Platform Integration Tests (Build #181)
# ---------------------------------------------------------------------------


class TestNewVerticalPlatformIntegration:
    def test_platform_includes_new_verticals(self, temp_dir):
        """Platform should include cars, activities, and insurance neurons."""
        platform = AnastasiaPlatform({"data_dir": temp_dir})
        results = platform.start()

        assert "cars" in results
        assert "activities" in results
        assert "insurance" in results
        assert results["cars"] is True
        assert results["activities"] is True
        assert results["insurance"] is True

        platform.stop()


# ---------------------------------------------------------------------------
# Vertical Neuron Search Method Tests (Build #182)
# ---------------------------------------------------------------------------


class TestCarsNeuronSearch:
    """Test CarsNeuron.search() with injected client."""

    def test_search_disabled_returns_error(self, event_bus):
        neuron = CarsNeuron()
        neuron.initialize(event_bus, {"cars_enabled": False})
        result = neuron.search("LAX", "2026-06-01", "2026-06-05")
        assert result["success"] is False
        assert "disabled" in result["error"].lower()

    def test_search_no_client_returns_error(self, event_bus):
        neuron = CarsNeuron()
        neuron.initialize(event_bus, {"cars_enabled": True})
        result = neuron.search("LAX", "2026-06-01", "2026-06-05", client=None)
        assert result["success"] is False
        assert "client" in result["error"].lower()

    def test_search_with_mock_client(self, event_bus):
        class MockClient:
            def search_locations(self, q):
                return [{"id": "LOC1", "name": q}]
            def search_cars(self, **kw):
                return [{"id": "C1", "name": "Economy", "price": 45.0, "supplier": "Hertz"}]

        neuron = CarsNeuron()
        neuron.initialize(event_bus, {"cars_enabled": True})
        result = neuron.search("LAX", "2026-06-01", "2026-06-05", client=MockClient())
        assert result["success"] is True
        assert len(result["cars"]) == 1
        assert result["cars"][0]["raw_offer"]["source"] == "discover_cars"
        assert result["cars"][0]["raw_offer"]["pickup_location_id"] == "LOC1"
        assert result["source"] == "discover_cars"


class TestActivitiesNeuronSearch:
    """Test ActivitiesNeuron.search() with injected client."""

    def test_search_disabled_returns_error(self, event_bus):
        neuron = ActivitiesNeuron()
        neuron.initialize(event_bus, {"activities_enabled": False})
        result = neuron.search("Paris")
        assert result["success"] is False
        assert "disabled" in result["error"].lower()

    def test_search_with_mock_client(self, event_bus):
        class MockClient:
            def search_freetext(self, q):
                return [{"dest_id": "D1", "name": q}]
            def search_products(self, **kw):
                return [{"code": "P1", "title": "Eiffel Tour", "price": 25.0}]

        neuron = ActivitiesNeuron()
        neuron.initialize(event_bus, {"activities_enabled": True})
        result = neuron.search("Paris", query="eiffel", client=MockClient())
        assert result["success"] is True
        assert len(result["activities"]) == 1
        assert result["activities"][0]["raw_offer"]["source"] == "viator"
        assert result["activities"][0]["raw_offer"]["product_code"] == "P1"
        assert result["source"] == "viator"


class TestInsuranceNeuronSearch:
    """Test InsuranceNeuron.search() with injected client."""

    def test_search_disabled_returns_error(self, event_bus):
        neuron = InsuranceNeuron()
        neuron.initialize(event_bus, {"insurance_enabled": False})
        result = neuron.search("US", "2026-06-01", "2026-06-15")
        assert result["success"] is False
        assert "disabled" in result["error"].lower()

    def test_search_with_mock_client(self, event_bus):
        class MockClient:
            def get_quote(self, **kw):
                return [{"plan_id": "NI1", "name": "Nomad Insurance", "price_per_day": 1.68}]

        neuron = InsuranceNeuron()
        neuron.initialize(event_bus, {"insurance_enabled": True})
        result = neuron.search("FR", "2026-06-01", "2026-06-15", travelers=2, client=MockClient())
        assert result["success"] is True
        assert len(result["quotes"]) == 1
        assert result["quotes"][0]["raw_offer"]["source"] == "safetywing"
        assert result["quotes"][0]["raw_offer"]["plan_id"] == "NI1"
        assert result["quotes"][0]["raw_offer"]["travelers"] == 2
        assert result["source"] == "safetywing"

    def test_cars_neuron_accessible(self, temp_dir):
        platform = AnastasiaPlatform({"data_dir": temp_dir})
        platform.start()

        cars = platform.get_module("cars")
        assert cars is not None
        assert cars.name == "cars"

        health = cars.health_check()
        assert health["vertical"] == "cars"

        platform.stop()

    def test_activities_neuron_accessible(self, temp_dir):
        platform = AnastasiaPlatform({"data_dir": temp_dir})
        platform.start()

        activities = platform.get_module("activities")
        assert activities is not None
        assert activities.name == "activities"

        health = activities.health_check()
        assert health["vertical"] == "activities"

        platform.stop()

    def test_insurance_neuron_accessible(self, temp_dir):
        platform = AnastasiaPlatform({"data_dir": temp_dir})
        platform.start()

        insurance = platform.get_module("insurance")
        assert insurance is not None
        assert insurance.name == "insurance"

        health = insurance.health_check()
        assert health["vertical"] == "insurance"

        platform.stop()


# ---------------------------------------------------------------------------
# VerticalSearchCoordinator Tests (Build #183)
# ---------------------------------------------------------------------------


class TestVerticalSearchCoordinator:
    """Test the thin search routing wrapper."""

    def test_route_to_cars(self, temp_dir):
        """Coordinator routes search to CarsNeuron."""
        platform = AnastasiaPlatform({"data_dir": temp_dir})
        platform.start()

        coordinator = VerticalSearchCoordinator(platform)
        result = coordinator.search("cars", pickup_location="LAX", pickup_date="2026-05-01", dropoff_date="2026-05-05")
        # Without a real client, search should return error or empty results
        assert isinstance(result, dict)

        platform.stop()

    def test_route_to_activities(self, temp_dir):
        """Coordinator routes search to ActivitiesNeuron."""
        platform = AnastasiaPlatform({"data_dir": temp_dir})
        platform.start()

        coordinator = VerticalSearchCoordinator(platform)
        result = coordinator.search("activities", destination="Rome")
        assert isinstance(result, dict)

        platform.stop()

    def test_unknown_vertical_returns_error(self, temp_dir):
        """Unknown vertical should return error dict."""
        platform = AnastasiaPlatform({"data_dir": temp_dir})
        platform.start()

        coordinator = VerticalSearchCoordinator(platform)
        result = coordinator.search("spaceflights")
        assert result["success"] is False
        assert "not found" in result["error"]

        platform.stop()

    def test_available_verticals_list(self, temp_dir):
        """Available verticals lists neurons with search()."""
        platform = AnastasiaPlatform({"data_dir": temp_dir})
        platform.start()

        coordinator = VerticalSearchCoordinator(platform)
        verticals = coordinator.available_verticals
        assert isinstance(verticals, list)
        # Cars, activities, insurance all have search() methods (Build #182)
        assert "cars" in verticals
        assert "activities" in verticals
        assert "insurance" in verticals

        platform.stop()


# ============================================================
# Neuron Edge Cases (Build #188)
# ============================================================

class TestNeuronEdgeCases:
    """Edge cases: disabled neurons, missing clients."""

    def test_cars_search_no_client(self):
        """CarsNeuron.search with client=None returns error."""
        neuron = CarsNeuron()
        neuron._enabled = True
        result = neuron.search("LAX", "2026-04-01", "2026-04-05", client=None)
        assert result["success"] is False
        assert "client" in result["error"].lower()

    def test_cars_search_disabled(self):
        """CarsNeuron disabled returns error."""
        neuron = CarsNeuron()
        neuron._enabled = False
        result = neuron.search("LAX", "2026-04-01", "2026-04-05")
        assert result["success"] is False
        assert "disabled" in result["error"].lower()

    def test_activities_search_no_client(self):
        """ActivitiesNeuron.search with client=None returns error."""
        neuron = ActivitiesNeuron()
        neuron._enabled = True
        result = neuron.search("Paris", client=None)
        assert result["success"] is False
        assert "client" in result["error"].lower()

    def test_activities_search_disabled(self):
        """ActivitiesNeuron disabled returns error."""
        neuron = ActivitiesNeuron()
        neuron._enabled = False
        result = neuron.search("Paris")
        assert result["success"] is False
        assert "disabled" in result["error"].lower()

    def test_insurance_search_no_client(self):
        """InsuranceNeuron.search with client=None returns error."""
        neuron = InsuranceNeuron()
        neuron._enabled = True
        result = neuron.search("US", "2026-04-01", "2026-04-15", client=None)
        assert result["success"] is False
        assert "client" in result["error"].lower()

    def test_insurance_search_disabled(self):
        """InsuranceNeuron disabled returns error."""
        neuron = InsuranceNeuron()
        neuron._enabled = False
        result = neuron.search("US", "2026-04-01", "2026-04-15")
        assert result["success"] is False
        assert "disabled" in result["error"].lower()
