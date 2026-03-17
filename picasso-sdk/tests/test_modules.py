"""
Tests for ANASTASiA Module Registry — Dynamic API integration system.

Tests cover:
- KnowledgeCard creation, serialization, prompt generation
- APIModule credential checking and loading
- ModuleRegistry: register, list, filter, credential refresh, tools aggregation
- ModuleDirector: search planning, booking routing, capability queries, dashboard
- Flight module knowledge cards (all 8 sources)
- End-to-end: build all modules → register → plan search → route booking

MYSTES KYRIOS LLC — Confidential.
"""

import json
import os
import pytest

from anastasia.modules.registry import (
    APIModule,
    AuthType,
    KnowledgeCard,
    ModuleRegistry,
    SourceType,
    VerticalType,
)
from anastasia.modules.director import (
    BookingRoute,
    ModuleDirector,
    SearchPlan,
)
from anastasia.modules.flight_modules import (
    build_all_flight_modules,
    build_all_hotel_modules,
    build_all_modules,
    build_duffel_card,
    build_kiwi_card,
    build_liteapi_card,
    build_picasso_card,
)


# =========================================================================
# KNOWLEDGE CARD TESTS
# =========================================================================

class TestKnowledgeCard:
    """Test KnowledgeCard creation and serialization."""

    def test_create_card(self):
        card = build_picasso_card()
        assert card.module_id == "picasso_redbox"
        assert card.name == "Picasso/Redbox"
        assert card.vertical == "flights"
        assert card.source_type == "gds"
        assert card.priority == 100
        assert card.capabilities["pos_arbitrage"] is True
        assert card.carrier_count == 500

    def test_card_serialization(self):
        card = build_duffel_card()
        data = card.to_dict()
        assert isinstance(data, dict)
        assert data["module_id"] == "duffel_ndc"
        assert data["carrier_count"] == 300
        assert data["capabilities"]["search"] is True

    def test_card_deserialization(self):
        card = build_kiwi_card()
        data = card.to_dict()
        restored = KnowledgeCard.from_dict(data)
        assert restored.module_id == card.module_id
        assert restored.name == card.name
        assert restored.carrier_count == card.carrier_count
        assert restored.capabilities == card.capabilities
        assert restored.date_format == "DD/MM/YYYY"

    def test_card_roundtrip(self):
        """Verify serialization/deserialization preserves all fields."""
        for card_fn in [build_picasso_card, build_duffel_card, build_kiwi_card, build_liteapi_card]:
            card = card_fn()
            data = card.to_dict()
            restored = KnowledgeCard.from_dict(data)
            assert restored.module_id == card.module_id
            assert restored.priority == card.priority
            assert restored.source_type == card.source_type

    def test_card_to_prompt(self):
        card = build_picasso_card()
        prompt = card.to_prompt()
        assert "Picasso/Redbox" in prompt
        assert "GDS" in prompt.upper()
        assert "pos_arbitrage" in prompt
        assert "YYYY-MM-DD" in prompt

    def test_card_prompt_includes_quirks(self):
        card = build_kiwi_card()
        prompt = card.to_prompt()
        assert "DD/MM/YYYY" in prompt
        assert "booking_token" in prompt

    def test_card_prompt_includes_booking_flow(self):
        card = build_duffel_card()
        prompt = card.to_prompt()
        assert "search" in prompt
        assert "create_order" in prompt


# =========================================================================
# API MODULE TESTS
# =========================================================================

class TestAPIModule:
    """Test APIModule credential checking and loading."""

    def test_unconfigured_module(self):
        card = KnowledgeCard(
            module_id="test_module",
            name="Test",
            vendor="Test Corp",
            credential_env_vars=["NONEXISTENT_TEST_KEY_XYZ"],
        )
        module = APIModule(knowledge_card=card)
        assert module.check_configured() is False
        assert module.is_configured is False

    def test_configured_module(self, monkeypatch):
        monkeypatch.setenv("TEST_MODULE_KEY_ABC", "valid_key_12345")
        card = KnowledgeCard(
            module_id="test_module",
            name="Test",
            vendor="Test Corp",
            credential_env_vars=["TEST_MODULE_KEY_ABC"],
        )
        module = APIModule(knowledge_card=card)
        assert module.check_configured() is True
        assert module.is_configured is True

    def test_load_without_factory(self):
        card = KnowledgeCard(
            module_id="test_module",
            name="Test",
            vendor="Test Corp",
            credential_env_vars=[],
        )
        module = APIModule(knowledge_card=card)
        module.check_configured()
        # No factory — load returns current is_loaded state
        assert module.load() is False  # not loaded since no factory

    def test_load_with_factory(self, monkeypatch):
        monkeypatch.setenv("TEST_MODULE_KEY_DEF", "some_valid_key_here")
        card = KnowledgeCard(
            module_id="test_module",
            name="Test",
            vendor="Test Corp",
            credential_env_vars=["TEST_MODULE_KEY_DEF"],
        )

        class MockClient:
            pass

        module = APIModule(
            knowledge_card=card,
            client_factory=MockClient,
        )
        assert module.load() is True
        assert module.is_loaded is True
        assert isinstance(module.client_instance, MockClient)

    def test_unload(self, monkeypatch):
        monkeypatch.setenv("TEST_MODULE_KEY_GHI", "key_value_123456")
        card = KnowledgeCard(
            module_id="test_module",
            name="Test",
            vendor="Test Corp",
            credential_env_vars=["TEST_MODULE_KEY_GHI"],
        )
        module = APIModule(
            knowledge_card=card,
            client_factory=lambda: "client",
        )
        module.load()
        assert module.is_loaded
        module.unload()
        assert not module.is_loaded
        assert module.client_instance is None

    def test_short_credential_rejected(self, monkeypatch):
        """Credentials shorter than 5 chars are rejected."""
        monkeypatch.setenv("TEST_SHORT_KEY", "abc")
        card = KnowledgeCard(
            module_id="test_module",
            name="Test",
            vendor="Test Corp",
            credential_env_vars=["TEST_SHORT_KEY"],
        )
        module = APIModule(knowledge_card=card)
        assert module.check_configured() is False


# =========================================================================
# MODULE REGISTRY TESTS
# =========================================================================

class TestModuleRegistry:
    """Test ModuleRegistry — central module management."""

    @pytest.fixture
    def registry(self):
        return ModuleRegistry()

    @pytest.fixture
    def sample_module(self):
        card = KnowledgeCard(
            module_id="test_flights",
            name="Test Flights",
            vendor="Test Corp",
            vertical=VerticalType.FLIGHTS.value,
            source_type=SourceType.GDS.value,
            credential_env_vars=[],
            capabilities={"search": True, "book": True},
            priority=80,
        )
        return APIModule(
            knowledge_card=card,
            tools=[{"name": "test_search", "description": "Search"}],
            knowledge_prompt="You can search for flights.",
        )

    def test_register_and_get(self, registry, sample_module):
        registry.register(sample_module)
        retrieved = registry.get("test_flights")
        assert retrieved is not None
        assert retrieved.knowledge_card.name == "Test Flights"

    def test_register_duplicate_overwrites(self, registry, sample_module):
        registry.register(sample_module)
        registry.register(sample_module)
        assert len(registry.list_modules()) == 1

    def test_unregister(self, registry, sample_module):
        registry.register(sample_module)
        assert registry.unregister("test_flights") is True
        assert registry.get("test_flights") is None

    def test_unregister_nonexistent(self, registry):
        assert registry.unregister("nonexistent") is False

    def test_list_modules_all(self, registry):
        for mod in build_all_modules():
            registry.register(mod)
        all_mods = registry.list_modules()
        assert len(all_mods) == 8  # 7 flights + 1 hotel

    def test_list_modules_by_vertical(self, registry):
        for mod in build_all_modules():
            registry.register(mod)
        flights = registry.list_modules(vertical="flights")
        hotels = registry.list_modules(vertical="hotels")
        assert len(flights) == 7
        assert len(hotels) == 1

    def test_list_modules_by_source_type(self, registry):
        for mod in build_all_modules():
            registry.register(mod)
        gds = registry.list_modules(source_type="gds")
        ndc = registry.list_modules(source_type="ndc")
        aggregator = registry.list_modules(source_type="aggregator")
        assert len(gds) == 2   # Picasso + Mystifly
        assert len(ndc) == 2   # Duffel + AirGateway
        assert len(aggregator) == 2  # Kiwi + TripStack

    def test_list_sorted_by_priority(self, registry):
        for mod in build_all_modules():
            registry.register(mod)
        flights = registry.list_modules(vertical="flights")
        priorities = [m.knowledge_card.priority for m in flights]
        assert priorities == sorted(priorities, reverse=True)

    def test_list_configured_only(self, registry, monkeypatch):
        monkeypatch.setenv("DUFFEL_ACCESS_TOKEN", "duffel_test_valid_token_1234567890")
        for mod in build_all_modules():
            registry.register(mod)
        configured = registry.list_configured()
        # Only Duffel should be configured (we set its env var)
        assert len(configured) >= 1
        ids = [m.knowledge_card.module_id for m in configured]
        assert "duffel_ndc" in ids

    def test_get_card(self, registry, sample_module):
        registry.register(sample_module)
        card = registry.get_card("test_flights")
        assert card is not None
        assert card.name == "Test Flights"
        assert registry.get_card("nonexistent") is None

    def test_get_tools(self, registry, sample_module):
        registry.register(sample_module)
        # Module has no credentials configured by default (empty list = configured)
        tools = registry.get_tools(configured_only=True)
        assert len(tools) == 1
        assert tools[0]["name"] == "test_search"

    def test_get_knowledge_prompts(self, registry, sample_module):
        registry.register(sample_module)
        prompts = registry.get_knowledge_prompts(configured_only=True)
        assert "search for flights" in prompts

    def test_refresh_credentials(self, registry, monkeypatch):
        for mod in build_all_modules():
            registry.register(mod)
        results = registry.refresh_credentials()
        assert len(results) == 8
        # Without env vars, all should be unconfigured (except those with empty credential lists)
        for mid, configured in results.items():
            # All real modules require credentials
            assert configured is False

    def test_get_status(self, registry, sample_module):
        registry.register(sample_module)
        status = registry.get_status()
        assert "test_flights" in status
        assert status["test_flights"]["name"] == "Test Flights"
        assert status["test_flights"]["vertical"] == "flights"

    def test_dashboard(self, registry):
        for mod in build_all_modules():
            registry.register(mod)
        dashboard = registry.to_dashboard()
        assert "Module Registry Dashboard" in dashboard
        assert "Picasso/Redbox" in dashboard

    def test_persistence(self, tmp_path):
        """Test saving and loading knowledge cards from disk."""
        registry = ModuleRegistry(storage_dir=str(tmp_path / "cards"))
        card = build_picasso_card()
        registry.register(APIModule(knowledge_card=card))

        # Verify file was saved
        card_file = tmp_path / "cards" / "picasso_redbox.json"
        assert card_file.exists()
        data = json.loads(card_file.read_text())
        assert data["module_id"] == "picasso_redbox"

        # Load into a new registry
        new_registry = ModuleRegistry(storage_dir=str(tmp_path / "cards"))
        count = new_registry.load_cards_from_disk()
        assert count == 1
        loaded = new_registry.get("picasso_redbox")
        assert loaded is not None
        assert loaded.knowledge_card.name == "Picasso/Redbox"


# =========================================================================
# MODULE DIRECTOR TESTS
# =========================================================================

class TestModuleDirector:
    """Test ModuleDirector — dynamic API orchestration engine."""

    @pytest.fixture
    def populated_registry(self, monkeypatch):
        """Registry with all modules, Duffel configured."""
        monkeypatch.setenv("DUFFEL_ACCESS_TOKEN", "duffel_test_abcdef1234567890")
        registry = ModuleRegistry()
        for mod in build_all_modules():
            registry.register(mod)
        return registry

    @pytest.fixture
    def director(self, populated_registry):
        return ModuleDirector(populated_registry)

    def test_plan_search_no_configured(self):
        """Empty registry returns empty plan."""
        registry = ModuleRegistry()
        director = ModuleDirector(registry)
        plan = director.plan_search()
        assert plan.modules == []
        assert plan.primary == "none"
        assert "No configured modules" in plan.notes[0]

    def test_plan_search_with_configured(self, director):
        plan = director.plan_search(vertical="flights")
        assert len(plan.modules) >= 1
        assert "duffel_ndc" in plan.modules
        assert plan.primary == "duffel_ndc"  # Highest priority configured
        assert plan.estimated_sources >= 1

    def test_plan_search_hotels(self, director, monkeypatch):
        monkeypatch.setenv("LITEAPI_KEY", "sand_3bbd3fde_test_key_12345678")
        director.registry.refresh_credentials()
        plan = director.plan_search(vertical="hotels")
        assert len(plan.modules) >= 1
        assert "liteapi_hotels" in plan.modules

    def test_merge_strategy_arbitrage(self, director, monkeypatch):
        """When POS arbitrage module is configured, merge strategy reflects it."""
        monkeypatch.setenv("PICASSO_SESSION_TOKEN", "valid_session_token_12345678")
        director.registry.refresh_credentials()
        plan = director.plan_search(vertical="flights")
        assert "arbitrage" in plan.merge_strategy

    def test_route_booking_by_source(self, director):
        """Route booking by source type."""
        route = director.route_booking(source="ndc")
        assert route is not None
        assert route.module_id == "duffel_ndc"
        assert "search" in route.booking_steps

    def test_route_booking_by_module_id(self, director):
        route = director.route_booking(source="any", module_id="duffel_ndc")
        assert route is not None
        assert route.module_id == "duffel_ndc"

    def test_route_booking_unconfigured(self, director):
        """Routing to unconfigured source returns None."""
        route = director.route_booking(source="gds")
        # GDS (Picasso) is not configured in this test fixture
        assert route is None

    def test_can_search(self, director):
        assert director.can_search("flights") is True
        # Hotels not configured in fixture
        assert director.can_search("hotels") is False

    def test_can_book(self, director):
        assert director.can_book("flights") is True

    def test_get_capabilities(self, director):
        caps = director.get_capabilities()
        assert "search" in caps
        assert "duffel_ndc" in caps["search"]

    def test_get_verticals(self, director):
        verticals = director.get_verticals()
        assert "flights" in verticals
        assert "hotels" in verticals
        flights = verticals["flights"]
        assert flights["total"] == 7
        assert flights["configured"] >= 1

    def test_generate_system_prompt(self, director):
        prompt = director.generate_system_prompt()
        assert "AVAILABLE API MODULES" in prompt
        assert "Duffel" in prompt
        assert "ROUTING GUIDANCE" in prompt

    def test_generate_system_prompt_empty(self):
        """Empty registry generates empty prompt."""
        registry = ModuleRegistry()
        director = ModuleDirector(registry)
        assert director.generate_system_prompt() == ""

    def test_generate_dashboard(self, director):
        dashboard = director.generate_dashboard()
        assert "ANASTASiA Module Director" in dashboard
        assert "FLIGHTS" in dashboard
        assert "CAPABILITIES" in dashboard


# =========================================================================
# FLIGHT MODULE CARD TESTS
# =========================================================================

class TestFlightModules:
    """Test all flight module knowledge cards."""

    def test_all_flight_modules_count(self):
        modules = build_all_flight_modules()
        assert len(modules) == 7

    def test_all_hotel_modules_count(self):
        modules = build_all_hotel_modules()
        assert len(modules) == 1

    def test_all_modules_count(self):
        modules = build_all_modules()
        assert len(modules) == 8

    def test_picasso_card_details(self):
        card = build_picasso_card()
        assert card.priority == 100
        assert card.capabilities["pos_arbitrage"] is True
        assert card.source_type == "gds"
        assert "PICASSO_SESSION_TOKEN" in card.credential_env_vars
        assert "ADT" in card.passenger_format["type_codes"]
        assert card.readiness == "production"

    def test_duffel_card_details(self):
        card = build_duffel_card()
        assert card.priority == 80
        assert card.capabilities["cancel"] is True
        assert card.capabilities["pos_arbitrage"] is False
        assert "DUFFEL_ACCESS_TOKEN" in card.credential_env_vars
        assert card.date_format == "YYYY-MM-DD"
        assert card.passenger_format["dob_field"] == "born_on"

    def test_kiwi_card_details(self):
        card = build_kiwi_card()
        assert card.priority == 60
        assert card.capabilities["virtual_interlining"] is True
        assert card.capabilities["pos_arbitrage"] is False
        assert "KIWI_API_KEY" in card.credential_env_vars
        assert card.date_format == "DD/MM/YYYY"
        assert card.carrier_count == 750

    def test_liteapi_card_details(self):
        card = build_liteapi_card()
        assert card.vertical == "hotels"
        assert card.source_type == "wholesaler"
        assert card.carrier_count == 2000000
        assert "LITEAPI_KEY" in card.credential_env_vars

    def test_all_cards_have_required_fields(self):
        """Every knowledge card must have essential fields."""
        for mod in build_all_modules():
            card = mod.knowledge_card
            assert card.module_id, f"Missing module_id"
            assert card.name, f"Missing name for {card.module_id}"
            assert card.vendor, f"Missing vendor for {card.module_id}"
            assert card.vertical in [v.value for v in VerticalType], (
                f"Invalid vertical {card.vertical} for {card.module_id}"
            )
            assert card.source_type in [s.value for s in SourceType], (
                f"Invalid source_type {card.source_type} for {card.module_id}"
            )
            assert 0 <= card.priority <= 100, (
                f"Priority {card.priority} out of range for {card.module_id}"
            )
            assert len(card.credential_env_vars) > 0, (
                f"No credentials defined for {card.module_id}"
            )

    def test_unique_module_ids(self):
        """All module IDs must be unique."""
        modules = build_all_modules()
        ids = [m.knowledge_card.module_id for m in modules]
        assert len(ids) == len(set(ids)), f"Duplicate module IDs: {ids}"

    def test_unique_priorities_per_vertical(self):
        """Within a vertical, priorities should be unique to avoid ambiguous routing."""
        modules = build_all_modules()
        by_vertical = {}
        for mod in modules:
            card = mod.knowledge_card
            by_vertical.setdefault(card.vertical, []).append(card.priority)
        for vertical, priorities in by_vertical.items():
            assert len(priorities) == len(set(priorities)), (
                f"Duplicate priorities in {vertical}: {priorities}"
            )


# =========================================================================
# END-TO-END TESTS
# =========================================================================

class TestEndToEnd:
    """End-to-end: build → register → plan → route."""

    def test_full_pipeline(self, monkeypatch):
        """Build all modules, register, plan a search, route a booking."""
        # Configure Duffel
        monkeypatch.setenv("DUFFEL_ACCESS_TOKEN", "duffel_test_abcdef1234567890")

        # Build and register
        registry = ModuleRegistry()
        for mod in build_all_modules():
            registry.register(mod)

        director = ModuleDirector(registry)

        # Plan a flight search
        plan = director.plan_search(vertical="flights")
        assert len(plan.modules) >= 1
        assert plan.primary == "duffel_ndc"

        # Route an NDC booking
        route = director.route_booking(source="ndc")
        assert route is not None
        assert route.module_id == "duffel_ndc"
        assert "YYYY-MM-DD" in route.date_format

        # Check capabilities
        assert director.can_search("flights")
        assert director.can_book("flights")

        # Generate dashboard
        dashboard = director.generate_dashboard()
        assert "FLIGHTS" in dashboard

    def test_multi_source_pipeline(self, monkeypatch):
        """When multiple sources are configured, plan includes all of them."""
        monkeypatch.setenv("DUFFEL_ACCESS_TOKEN", "duffel_test_abcdef1234567890")
        monkeypatch.setenv("KIWI_API_KEY", "kiwi_test_key_valid_1234567890")

        registry = ModuleRegistry()
        for mod in build_all_modules():
            registry.register(mod)

        director = ModuleDirector(registry)
        plan = director.plan_search(vertical="flights")

        assert "duffel_ndc" in plan.modules
        assert "kiwi_tequila" in plan.modules
        assert plan.estimated_sources >= 2

    def test_all_sources_configured(self, monkeypatch):
        """When all 3 primary sources are configured, all appear in plan."""
        monkeypatch.setenv("PICASSO_SESSION_TOKEN", "picasso_valid_session_token_12345678")
        monkeypatch.setenv("DUFFEL_ACCESS_TOKEN", "duffel_test_abcdef1234567890")
        monkeypatch.setenv("KIWI_API_KEY", "kiwi_test_key_valid_1234567890")

        registry = ModuleRegistry()
        for mod in build_all_modules():
            registry.register(mod)

        director = ModuleDirector(registry)
        plan = director.plan_search(vertical="flights")

        assert "picasso_redbox" in plan.modules
        assert "duffel_ndc" in plan.modules
        assert "kiwi_tequila" in plan.modules
        assert plan.primary == "picasso_redbox"  # Highest priority (100)
        assert plan.estimated_sources == 3
        assert "arbitrage" in plan.merge_strategy
