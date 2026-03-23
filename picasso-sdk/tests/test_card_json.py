"""
Tests for JSON knowledge card loading and saving.

Tests cover the JSON card lifecycle: loading individual cards, loading
filtered sets, raw loading (with watchdog metadata), save/reload
roundtrips, and consistency between JSON cards and Python builders.

MYSTES KYRIOS LLC — Confidential.
"""

import json
import pytest
from pathlib import Path

from anastasia.modules.registry import (
    APIModule,
    KnowledgeCard,
    VerticalType,
)
from anastasia.modules.flight_modules import (
    CARDS_DIR,
    build_all_flight_modules,
    build_all_hotel_modules,
    build_all_modules,
    build_picasso_card,
    build_duffel_card,
    build_kiwi_card,
    build_liteapi_card,
    get_card_path,
    load_all_json_cards,
    load_card_from_json,
    load_card_raw,
    save_card_json,
)


# =========================================================================
# CARDS DIRECTORY TESTS
# =========================================================================

class TestCardsDirectory:
    """Verify the cards/ directory structure."""

    def test_cards_directory_exists(self):
        """CARDS_DIR exists and contains JSON files."""
        assert CARDS_DIR.exists(), f"Cards directory not found: {CARDS_DIR}"
        assert CARDS_DIR.is_dir(), f"CARDS_DIR is not a directory: {CARDS_DIR}"
        json_files = list(CARDS_DIR.glob("*.json"))
        assert len(json_files) > 0, "No JSON card files found in cards directory"

    def test_get_card_path(self):
        """get_card_path returns correct path construction."""
        path = get_card_path("picasso_redbox")
        assert path == CARDS_DIR / "picasso_redbox.json"
        assert path.suffix == ".json"
        assert path.stem == "picasso_redbox"

        path2 = get_card_path("some_module")
        assert path2 == CARDS_DIR / "some_module.json"


# =========================================================================
# INDIVIDUAL CARD LOADING
# =========================================================================

class TestLoadIndividualCards:
    """Test loading individual JSON card files."""

    def test_load_picasso_card_from_json(self):
        """Load picasso_redbox.json and verify key fields."""
        card_path = CARDS_DIR / "picasso_redbox.json"
        assert card_path.exists(), f"Missing card file: {card_path}"
        card = load_card_from_json(card_path)

        assert isinstance(card, KnowledgeCard)
        assert card.module_id == "picasso_redbox"
        assert card.name == "Picasso/Redbox"
        assert card.vertical == "flights"
        assert card.source_type == "gds"
        assert card.priority == 100
        assert card.capabilities["pos_arbitrage"] is True
        assert card.capabilities["search"] is True
        assert card.carrier_count == 500
        assert card.readiness == "production"

    def test_load_duffel_card_from_json(self):
        """Load duffel_ndc.json and verify key fields."""
        card_path = CARDS_DIR / "duffel_ndc.json"
        assert card_path.exists(), f"Missing card file: {card_path}"
        card = load_card_from_json(card_path)

        assert isinstance(card, KnowledgeCard)
        assert card.module_id == "duffel_ndc"
        assert card.name == "Duffel NDC"
        assert card.vertical == "flights"
        assert card.source_type == "ndc"
        assert card.priority == 80
        assert card.capabilities["cancel"] is True
        assert card.capabilities["pos_arbitrage"] is False
        assert "DUFFEL_ACCESS_TOKEN" in card.credential_env_vars


# =========================================================================
# BULK CARD LOADING
# =========================================================================

class TestLoadAllCards:
    """Test loading multiple cards with vertical filtering."""

    def test_load_all_flight_cards(self):
        """Load all flight vertical cards — should be 7."""
        cards = load_all_json_cards(vertical="flights")
        assert len(cards) == 7, (
            f"Expected 7 flight cards, got {len(cards)}: "
            f"{[c.module_id for c in cards]}"
        )
        for card in cards:
            assert card.vertical == "flights"

    def test_load_all_hotel_cards(self):
        """Load all hotel vertical cards — should be 1."""
        cards = load_all_json_cards(vertical="hotels")
        assert len(cards) == 1, (
            f"Expected 1 hotel card, got {len(cards)}: "
            f"{[c.module_id for c in cards]}"
        )
        assert cards[0].module_id == "liteapi_hotels"
        assert cards[0].vertical == "hotels"

    def test_load_all_cards(self):
        """Load all cards across verticals — should be 11 (7 flight + 1 hotel + 1 car + 1 activity + 1 insurance)."""
        cards = load_all_json_cards(vertical=None)
        assert len(cards) == 11, (
            f"Expected 11 total cards, got {len(cards)}: "
            f"{[c.module_id for c in cards]}"
        )


# =========================================================================
# CARD FIELD VALIDATION
# =========================================================================

class TestCardFieldValidation:
    """Verify structural integrity of all loaded cards."""

    def test_card_has_required_fields(self):
        """Every card has module_id, name, vertical, capabilities."""
        cards = load_all_json_cards()
        assert len(cards) > 0, "No cards loaded"
        for card in cards:
            assert card.module_id, f"Missing module_id on card"
            assert card.name, f"Missing name on card {card.module_id}"
            assert card.vertical, f"Missing vertical on card {card.module_id}"
            assert isinstance(card.capabilities, dict), (
                f"capabilities is not a dict on card {card.module_id}"
            )
            assert len(card.capabilities) > 0, (
                f"Empty capabilities on card {card.module_id}"
            )

    def test_card_capabilities_are_booleans(self):
        """All capabilities dict values are bool."""
        cards = load_all_json_cards()
        for card in cards:
            for cap_name, cap_value in card.capabilities.items():
                assert isinstance(cap_value, bool), (
                    f"Capability '{cap_name}' on card {card.module_id} "
                    f"is {type(cap_value).__name__}, expected bool"
                )

    def test_card_readiness_values(self):
        """All readiness values are valid (production/tested/discovered)."""
        valid_readiness = {"production", "tested", "discovered"}
        cards = load_all_json_cards()
        for card in cards:
            assert card.readiness in valid_readiness, (
                f"Card {card.module_id} has invalid readiness '{card.readiness}'. "
                f"Must be one of: {valid_readiness}"
            )


# =========================================================================
# RAW CARD LOADING (watchdog metadata)
# =========================================================================

class TestLoadCardRaw:
    """Test raw card loading which includes extra watchdog fields."""

    def test_load_card_raw_includes_extra_fields(self):
        """Raw load includes changelog_url, docs_url, sandbox_probe_endpoints."""
        card_path = CARDS_DIR / "picasso_redbox.json"
        raw = load_card_raw(card_path)

        assert isinstance(raw, dict)
        # Standard KnowledgeCard fields are present
        assert raw["module_id"] == "picasso_redbox"
        assert raw["name"] == "Picasso/Redbox"

        # Extra watchdog fields — these are NOT in KnowledgeCard dataclass
        assert "changelog_url" in raw, "Raw card missing changelog_url"
        assert "docs_url" in raw, "Raw card missing docs_url"
        assert "sandbox_probe_endpoints" in raw, "Raw card missing sandbox_probe_endpoints"
        assert isinstance(raw["sandbox_probe_endpoints"], list)

    def test_load_card_raw_vs_structured(self):
        """Raw load has more keys than the structured KnowledgeCard."""
        card_path = CARDS_DIR / "duffel_ndc.json"
        raw = load_card_raw(card_path)
        structured = load_card_from_json(card_path)

        # Raw dict should have keys not present on KnowledgeCard
        kc_fields = set(KnowledgeCard.__dataclass_fields__.keys())
        extra_keys = set(raw.keys()) - kc_fields
        assert len(extra_keys) > 0, (
            "Expected raw card to have extra fields beyond KnowledgeCard"
        )
        assert "changelog_url" in extra_keys or "docs_url" in extra_keys


# =========================================================================
# SAVE AND RELOAD ROUNDTRIP
# =========================================================================

class TestSaveAndReloadRoundtrip:
    """Test saving a card to JSON and reloading it."""

    def test_save_and_reload_roundtrip(self, tmp_path, monkeypatch):
        """Save a card, reload it, verify fields match."""
        # Create a test card
        card = KnowledgeCard(
            module_id="test_roundtrip",
            name="Roundtrip Test Module",
            vendor="Test Corp",
            version="2.5",
            vertical="flights",
            source_type="ndc",
            auth_type="bearer_token",
            credential_env_vars=["TEST_TOKEN"],
            capabilities={
                "search": True,
                "book": True,
                "cancel": False,
                "pos_arbitrage": True,
            },
            carrier_count=42,
            priority=77,
            readiness="tested",
            confidence=0.88,
            strengths=["fast", "reliable"],
            weaknesses=["limited_coverage"],
            best_for=["testing"],
            quirks=[{"issue": "test quirk", "workaround": "ignore it"}],
            booking_steps=["search", "book"],
            booking_notes="Test booking flow.",
        )

        # Monkeypatch CARDS_DIR to use tmp_path
        import anastasia.modules.flight_modules as fm
        monkeypatch.setattr(fm, "CARDS_DIR", tmp_path)

        # Save the card
        saved_path = save_card_json(card, extra={"docs_url": "https://example.com"})
        assert saved_path.exists()
        assert saved_path.name == "test_roundtrip.json"

        # Verify the saved JSON has the extra field
        raw = json.loads(saved_path.read_text())
        assert raw["docs_url"] == "https://example.com"

        # Reload the card
        reloaded = load_card_from_json(saved_path)
        assert isinstance(reloaded, KnowledgeCard)

        # Verify all fields match
        assert reloaded.module_id == card.module_id
        assert reloaded.name == card.name
        assert reloaded.vendor == card.vendor
        assert reloaded.version == card.version
        assert reloaded.vertical == card.vertical
        assert reloaded.source_type == card.source_type
        assert reloaded.auth_type == card.auth_type
        assert reloaded.credential_env_vars == card.credential_env_vars
        assert reloaded.capabilities == card.capabilities
        assert reloaded.carrier_count == card.carrier_count
        assert reloaded.priority == card.priority
        assert reloaded.readiness == card.readiness
        assert reloaded.confidence == card.confidence
        assert reloaded.strengths == card.strengths
        assert reloaded.weaknesses == card.weaknesses
        assert reloaded.best_for == card.best_for
        assert reloaded.quirks == card.quirks
        assert reloaded.booking_steps == card.booking_steps
        assert reloaded.booking_notes == card.booking_notes

    def test_save_with_extra_fields_preserved(self, tmp_path, monkeypatch):
        """Extra fields (changelog_url, etc.) survive save/raw-load."""
        import anastasia.modules.flight_modules as fm
        monkeypatch.setattr(fm, "CARDS_DIR", tmp_path)

        card = KnowledgeCard(
            module_id="test_extras",
            name="Extras Test",
            vendor="Test Corp",
        )
        extra = {
            "changelog_url": "https://example.com/changelog",
            "docs_url": "https://example.com/docs",
            "sandbox_probe_endpoints": ["health", "search"],
        }
        saved_path = save_card_json(card, extra=extra)

        raw = load_card_raw(saved_path)
        assert raw["changelog_url"] == "https://example.com/changelog"
        assert raw["docs_url"] == "https://example.com/docs"
        assert raw["sandbox_probe_endpoints"] == ["health", "search"]


# =========================================================================
# JSON vs PYTHON BUILDER CONSISTENCY
# =========================================================================

class TestJsonMatchesPythonBuilders:
    """Verify JSON cards produce the same data as Python builder functions."""

    def test_json_cards_match_python_builders(self):
        """Compare JSON-loaded Picasso card with build_picasso_card()."""
        json_card = load_card_from_json(CARDS_DIR / "picasso_redbox.json")
        py_card = build_picasso_card()

        # Core identity must match
        assert json_card.module_id == py_card.module_id
        assert json_card.name == py_card.name
        assert json_card.vendor == py_card.vendor
        assert json_card.version == py_card.version

        # Classification must match
        assert json_card.vertical == py_card.vertical
        assert json_card.source_type == py_card.source_type

        # Capabilities must match
        assert json_card.capabilities == py_card.capabilities

        # Routing hints must match
        assert json_card.priority == py_card.priority
        assert json_card.readiness == py_card.readiness
        assert json_card.carrier_count == py_card.carrier_count

    def test_duffel_json_matches_python(self):
        """Duffel JSON card matches build_duffel_card()."""
        json_card = load_card_from_json(CARDS_DIR / "duffel_ndc.json")
        py_card = build_duffel_card()

        assert json_card.module_id == py_card.module_id
        assert json_card.name == py_card.name
        assert json_card.capabilities == py_card.capabilities
        assert json_card.priority == py_card.priority

    def test_kiwi_json_matches_python(self):
        """Kiwi JSON card matches build_kiwi_card()."""
        json_card = load_card_from_json(CARDS_DIR / "kiwi_tequila.json")
        py_card = build_kiwi_card()

        assert json_card.module_id == py_card.module_id
        assert json_card.name == py_card.name
        assert json_card.capabilities == py_card.capabilities
        assert json_card.date_format == py_card.date_format

    def test_liteapi_json_matches_python(self):
        """liteAPI JSON card matches build_liteapi_card()."""
        json_card = load_card_from_json(CARDS_DIR / "liteapi_hotels.json")
        py_card = build_liteapi_card()

        assert json_card.module_id == py_card.module_id
        assert json_card.name == py_card.name
        assert json_card.vertical == py_card.vertical
        assert json_card.capabilities == py_card.capabilities
        assert json_card.carrier_count == py_card.carrier_count


# =========================================================================
# MODULE BUILDER TESTS (from_json flag)
# =========================================================================

class TestBuildModulesFromJson:
    """Test build_all_*_modules with from_json=True and from_json=False."""

    def test_build_all_flight_modules_from_json(self):
        """from_json=True returns APIModule instances from JSON cards."""
        modules = build_all_flight_modules(from_json=True)
        assert len(modules) == 7
        for mod in modules:
            assert isinstance(mod, APIModule)
            assert mod.knowledge_card.vertical == "flights"

    def test_build_all_flight_modules_from_python(self):
        """from_json=False returns APIModule instances from Python builders."""
        modules = build_all_flight_modules(from_json=False)
        assert len(modules) == 7
        for mod in modules:
            assert isinstance(mod, APIModule)
            assert mod.knowledge_card.vertical == "flights"

    def test_build_all_hotel_modules_from_json(self):
        """Hotel modules from JSON."""
        modules = build_all_hotel_modules(from_json=True)
        assert len(modules) == 1
        assert modules[0].knowledge_card.vertical == "hotels"
        assert modules[0].knowledge_card.module_id == "liteapi_hotels"

    def test_build_all_hotel_modules_from_python(self):
        """Hotel modules from Python builder."""
        modules = build_all_hotel_modules(from_json=False)
        assert len(modules) == 1
        assert modules[0].knowledge_card.module_id == "liteapi_hotels"

    def test_build_all_modules_count(self):
        """Total modules = 11 (7 flights + 1 hotel + 1 car + 1 activity + 1 insurance)."""
        modules = build_all_modules(from_json=True)
        assert len(modules) == 11

        # Verify the breakdown
        flight_ids = [m.knowledge_card.module_id for m in modules
                      if m.knowledge_card.vertical == "flights"]
        hotel_ids = [m.knowledge_card.module_id for m in modules
                     if m.knowledge_card.vertical == "hotels"]
        car_ids = [m.knowledge_card.module_id for m in modules
                   if m.knowledge_card.vertical == "car_rental"]
        activity_ids = [m.knowledge_card.module_id for m in modules
                        if m.knowledge_card.vertical == "activities"]
        insurance_ids = [m.knowledge_card.module_id for m in modules
                         if m.knowledge_card.vertical == "insurance"]
        assert len(flight_ids) == 7
        assert len(hotel_ids) == 1
        assert len(car_ids) == 1
        assert len(activity_ids) == 1
        assert len(insurance_ids) == 1

    def test_json_and_python_produce_same_module_ids(self):
        """JSON path and Python path produce the same set of module IDs."""
        json_modules = build_all_modules(from_json=True)
        py_modules = build_all_modules(from_json=False)

        json_ids = sorted(m.knowledge_card.module_id for m in json_modules)
        py_ids = sorted(m.knowledge_card.module_id for m in py_modules)
        assert json_ids == py_ids


# =========================================================================
# ERROR HANDLING
# =========================================================================

class TestCardErrorHandling:
    """Test error handling for invalid card files."""

    def test_load_card_invalid_json(self, tmp_path):
        """Invalid JSON raises an error."""
        bad_file = tmp_path / "broken.json"
        bad_file.write_text("{ this is not valid json !!!", encoding="utf-8")

        with pytest.raises(json.JSONDecodeError):
            load_card_from_json(bad_file)

    def test_load_card_missing_file(self, tmp_path):
        """Loading a nonexistent file raises FileNotFoundError."""
        missing = tmp_path / "nonexistent.json"
        with pytest.raises(FileNotFoundError):
            load_card_from_json(missing)

    def test_load_all_from_empty_directory(self, tmp_path, monkeypatch):
        """load_all_json_cards from empty dir returns empty list."""
        import anastasia.modules.flight_modules as fm
        monkeypatch.setattr(fm, "CARDS_DIR", tmp_path)

        cards = load_all_json_cards()
        assert cards == []

    def test_load_all_from_missing_directory(self, tmp_path, monkeypatch):
        """load_all_json_cards from nonexistent dir returns empty list."""
        import anastasia.modules.flight_modules as fm
        monkeypatch.setattr(fm, "CARDS_DIR", tmp_path / "does_not_exist")

        cards = load_all_json_cards()
        assert cards == []
