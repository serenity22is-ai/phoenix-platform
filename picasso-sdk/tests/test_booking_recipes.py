"""Tests for the Booking Recipe system (Build #238).

Three-tier airline booking engine:
  Tier 1: Compiled recipes (zero AI cost)
  Tier 2: AI recipe generator (one-time cost)
  Tier 3: AI live executor (per-booking fallback)
"""

import json
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ─── Recipe Card Schema Tests ────────────────────────────────────────────────

class TestBookingRecipeSchema:
    """Test BookingRecipe dataclass and JSON serialization."""

    def test_recipe_from_json(self, tmp_path):
        from anastasia.booking_recipes import BookingRecipe

        card = {
            "recipe_id": "test_airline",
            "airline_group": "test_group",
            "airlines": ["TA", "TB"],
            "base_url": "https://testairline.com",
            "language_path": "/en/",
            "session_setup": {
                "load_url": "https://testairline.com/en/",
                "wait_for": "networkidle",
                "extract_tokens": {
                    "csrf_token": {"source": "cookie", "name": "XSRF"}
                },
            },
            "steps": [
                {
                    "name": "search_offers",
                    "method": "POST",
                    "url": "/api/search",
                    "headers": {"X-CSRF": "${csrf_token}"},
                    "body": {"origin": "${origin_iata}", "dest": "${destination_iata}"},
                    "response_extract": {"offer_id": "$.offers[0].id"},
                    "validation": {"status_code": 200},
                },
                {
                    "name": "submit_payment",
                    "method": "POST",
                    "url": "/api/pay",
                    "body": {"card": "${card_number}"},
                    "response_extract": {"pnr": "$.confirmationCode"},
                    "validation": {"status_code": [200, 201]},
                },
            ],
            "card_data_wipe": {
                "after_step": "submit_payment",
                "on_failure": True,
                "fields": ["card_number", "card_cvv"],
            },
            "error_patterns": {
                "session_expired": {"status": 401, "retry": True},
                "payment_declined": {"body_contains": "declined", "abort": True},
            },
            "metadata": {
                "created_by": "test",
                "created_at": "2026-04-21T00:00:00Z",
            },
        }

        path = tmp_path / "test_airline.json"
        path.write_text(json.dumps(card))

        recipe = BookingRecipe.from_json(path)

        assert recipe.recipe_id == "test_airline"
        assert recipe.airline_group == "test_group"
        assert recipe.airlines == ["TA", "TB"]
        assert recipe.base_url == "https://testairline.com"
        assert len(recipe.steps) == 2
        assert recipe.steps[0].name == "search_offers"
        assert recipe.steps[0].method == "POST"
        assert recipe.steps[1].name == "submit_payment"

    def test_recipe_covers_airline(self, tmp_path):
        from anastasia.booking_recipes import BookingRecipe

        card = {
            "recipe_id": "lh_group",
            "airline_group": "lufthansa",
            "airlines": ["LH", "LX", "OS", "SN", "EW"],
            "base_url": "https://www.lufthansa.com",
            "steps": [],
        }
        path = tmp_path / "lh.json"
        path.write_text(json.dumps(card))

        recipe = BookingRecipe.from_json(path)

        assert recipe.covers_airline("LH")
        assert recipe.covers_airline("lx")  # Case-insensitive
        assert recipe.covers_airline("OS")
        assert not recipe.covers_airline("AA")
        assert not recipe.covers_airline("DL")

    def test_recipe_roundtrip_json(self, tmp_path):
        from anastasia.booking_recipes import BookingRecipe

        card = {
            "recipe_id": "roundtrip_test",
            "airline_group": "test",
            "airlines": ["XX"],
            "base_url": "https://example.com",
            "steps": [
                {
                    "name": "search",
                    "method": "GET",
                    "url": "/api/search?q=${origin_iata}",
                    "response_extract": {"offer_id": "$.id"},
                    "validation": {"status_code": 200},
                }
            ],
        }
        path = tmp_path / "roundtrip.json"
        path.write_text(json.dumps(card))

        recipe = BookingRecipe.from_json(path)
        exported = recipe.to_json()

        assert exported["recipe_id"] == "roundtrip_test"
        assert exported["airlines"] == ["XX"]
        assert len(exported["steps"]) == 1
        assert exported["steps"][0]["name"] == "search"

    def test_recipe_default_card_data_wipe(self, tmp_path):
        from anastasia.booking_recipes import BookingRecipe

        card = {
            "recipe_id": "defaults",
            "airline_group": "test",
            "airlines": ["ZZ"],
            "base_url": "https://example.com",
            "steps": [],
        }
        path = tmp_path / "defaults.json"
        path.write_text(json.dumps(card))

        recipe = BookingRecipe.from_json(path)
        assert "card_number" in recipe.card_data_wipe["fields"]
        assert recipe.card_data_wipe["on_failure"] is True


# ─── Recipe Registry Tests ───────────────────────────────────────────────────

class TestRecipeRegistry:
    """Test RecipeRegistry airline → recipe lookup."""

    def test_register_and_lookup(self):
        from anastasia.booking_recipes import BookingRecipe, RecipeRegistry, RecipeStep

        registry = RecipeRegistry()

        recipe = BookingRecipe(
            recipe_id="lh_group",
            airline_group="lufthansa",
            airlines=["LH", "LX", "OS"],
            base_url="https://www.lufthansa.com",
            steps=[],
        )
        registry.register(recipe)

        assert registry.recipe_count == 1
        assert registry.airline_count == 3
        assert registry.has_recipe("LH")
        assert registry.has_recipe("lx")
        assert not registry.has_recipe("AA")

        found = registry.find_by_airline("OS")
        assert found is not None
        assert found.recipe_id == "lh_group"

    def test_multiple_recipes(self):
        from anastasia.booking_recipes import BookingRecipe, RecipeRegistry

        registry = RecipeRegistry()

        registry.register(BookingRecipe(
            recipe_id="lh", airline_group="lufthansa",
            airlines=["LH", "LX"], base_url="https://lufthansa.com", steps=[],
        ))
        registry.register(BookingRecipe(
            recipe_id="af", airline_group="airfrance_klm",
            airlines=["AF", "KL"], base_url="https://airfrance.com", steps=[],
        ))

        assert registry.recipe_count == 2
        assert registry.airline_count == 4
        assert registry.find_by_airline("LH").recipe_id == "lh"
        assert registry.find_by_airline("KL").recipe_id == "af"

    def test_load_from_directory(self, tmp_path):
        from anastasia.booking_recipes import RecipeRegistry

        # Create two recipe cards
        for name, airlines in [("recipe_a", ["AA"]), ("recipe_b", ["BB", "CC"])]:
            card = {
                "recipe_id": name,
                "airline_group": name,
                "airlines": airlines,
                "base_url": f"https://{name}.com",
                "steps": [],
            }
            (tmp_path / f"{name}.json").write_text(json.dumps(card))

        registry = RecipeRegistry()
        loaded = registry.load_from_directory(tmp_path)

        assert loaded == 2
        assert registry.airline_count == 3
        assert registry.has_recipe("AA")
        assert registry.has_recipe("CC")

    def test_load_skips_invalid_json(self, tmp_path):
        from anastasia.booking_recipes import RecipeRegistry

        (tmp_path / "good.json").write_text(json.dumps({
            "recipe_id": "good", "airline_group": "g",
            "airlines": ["GG"], "base_url": "https://g.com", "steps": [],
        }))
        (tmp_path / "bad.json").write_text("not json at all")

        registry = RecipeRegistry()
        loaded = registry.load_from_directory(tmp_path)

        assert loaded == 1
        assert registry.has_recipe("GG")


# ─── Recipe Engine Tests ─────────────────────────────────────────────────────

class TestRecipeEngine:
    """Test the recipe execution engine (variable resolution, JSONPath, etc.)."""

    def test_resolve_variable(self):
        from anastasia.booking_recipes.engine import _resolve_variable

        assert _resolve_variable("${name}", {"name": "John"}) == "John"
        assert _resolve_variable("/api/${id}/book", {"id": "123"}) == "/api/123/book"
        assert _resolve_variable("no vars here", {}) == "no vars here"
        assert _resolve_variable("${missing}", {}) == "${missing}"

    def test_resolve_template_nested(self):
        from anastasia.booking_recipes.engine import _resolve_template

        template = {
            "passengers": [
                {"firstName": "${first}", "lastName": "${last}"}
            ],
            "meta": {"ref": "${ref_id}"},
        }
        variables = {"first": "John", "last": "Doe", "ref_id": "ABC"}

        result = _resolve_template(template, variables)

        assert result["passengers"][0]["firstName"] == "John"
        assert result["passengers"][0]["lastName"] == "Doe"
        assert result["meta"]["ref"] == "ABC"

    def test_extract_jsonpath_simple(self):
        from anastasia.booking_recipes.engine import _extract_jsonpath

        data = {"offers": [{"id": "off_123", "price": 599}], "total": 1}

        assert _extract_jsonpath(data, "$.offers[0].id") == "off_123"
        assert _extract_jsonpath(data, "$.offers[0].price") == 599
        assert _extract_jsonpath(data, "$.total") == 1
        assert _extract_jsonpath(data, "$.missing") is None
        assert _extract_jsonpath(data, "$.offers[5].id") is None

    def test_extract_jsonpath_nested(self):
        from anastasia.booking_recipes.engine import _extract_jsonpath

        data = {
            "booking": {
                "confirmation": {"code": "PNR123", "type": "confirmed"},
                "payment": {"amount": "599.00", "currency": "DKK"},
            }
        }

        assert _extract_jsonpath(data, "$.booking.confirmation.code") == "PNR123"
        assert _extract_jsonpath(data, "$.booking.payment.currency") == "DKK"

    def test_validate_response_status_code(self):
        from anastasia.booking_recipes.engine import RecipeEngine

        engine = RecipeEngine()

        # Single status code
        assert engine._validate_response(200, {}, {"status_code": 200}) is None
        assert engine._validate_response(404, {}, {"status_code": 200}) is not None

        # List of status codes
        assert engine._validate_response(201, {}, {"status_code": [200, 201]}) is None
        assert engine._validate_response(500, {}, {"status_code": [200, 201]}) is not None

    def test_validate_response_required_fields(self):
        from anastasia.booking_recipes.engine import RecipeEngine

        engine = RecipeEngine()

        body = {"offer_id": "123", "price": 500}
        assert engine._validate_response(200, body, {"required_fields": ["offer_id"]}) is None
        assert engine._validate_response(200, body, {"required_fields": ["missing_field"]}) is not None

    def test_wipe_card_data(self):
        from anastasia.booking_recipes.engine import RecipeEngine

        engine = RecipeEngine()
        variables = {
            "pax_first_name": "John",
            "card_number": "4111111111111111",
            "card_cvv": "123",
            "card_exp_month": "12",
        }

        engine._wipe_card_data(variables, ["card_number", "card_cvv"])

        assert variables["card_number"] is None
        assert variables["card_cvv"] is None
        assert variables["card_exp_month"] is None  # Wiped by keyword match
        assert variables["pax_first_name"] == "John"  # Preserved

    def test_build_fetch_script(self):
        from anastasia.booking_recipes.engine import RecipeEngine

        engine = RecipeEngine()
        script = engine._build_fetch_script(
            url="https://airline.com/api/search",
            method="POST",
            headers={"X-CSRF": "token123"},
            body={"origin": "JFK", "dest": "LHR"},
        )

        assert "fetch(" in script
        assert "https://airline.com/api/search" in script
        assert "POST" in script

    def test_check_error_patterns(self):
        from anastasia.booking_recipes.engine import RecipeEngine, StepResult

        engine = RecipeEngine()

        error_patterns = {
            "session_expired": {"status": 401, "retry": True},
            "payment_declined": {"body_contains": "declined", "abort": True},
        }

        # Session expired → should retry
        result = StepResult(step_name="test", success=False, status_code=401)
        retry, abort = engine._check_error_patterns(result, error_patterns)
        assert retry is True
        assert abort is False

        # Payment declined → should abort
        result = StepResult(
            step_name="test", success=False, status_code=400,
            response_body={"error": "Card was declined by bank"},
        )
        retry, abort = engine._check_error_patterns(result, error_patterns)
        assert retry is False
        assert abort is True

        # Unknown error → no match
        result = StepResult(step_name="test", success=False, status_code=500)
        retry, abort = engine._check_error_patterns(result, error_patterns)
        assert retry is False
        assert abort is False


# ─── Network Recorder Tests ──────────────────────────────────────────────────

class TestNetworkRecorder:
    """Test the network capture and classification system."""

    def test_classify_request(self):
        from anastasia.booking_recipes.recorder import _classify_request

        assert _classify_request("/api/offers/search", "POST", None) == "search"
        assert _classify_request("/api/booking/select", "POST", None) == "select"
        assert _classify_request("/api/passengers", "PUT", None) == "passenger"
        assert _classify_request("/api/payment", "POST", None) == "payment"
        assert _classify_request("/api/confirm", "POST", None) == "confirm"
        assert _classify_request("/api/seatmap", "GET", None) == "extras"
        assert _classify_request("/api/unknown", "GET", None) == "other"

    def test_classify_from_body(self):
        from anastasia.booking_recipes.recorder import _classify_request

        body_pax = '{"firstName": "John", "lastName": "Doe"}'
        assert _classify_request("/api/step3", "POST", body_pax) == "passenger"

        body_card = '{"cardNumber": "4111111111111111"}'
        assert _classify_request("/api/step4", "POST", body_card) == "payment"

    def test_is_api_call(self):
        from anastasia.booking_recipes.recorder import _is_api_call

        assert _is_api_call("/api/search", "POST", "application/json", "xhr") is True
        assert _is_api_call("/style.css", "GET", "text/css", "stylesheet") is False
        assert _is_api_call("/logo.png", "GET", "image/png", "image") is False
        assert _is_api_call("/graphql", "POST", "application/json", "fetch") is True
        assert _is_api_call("/booking/create", "POST", "application/json", "xhr") is True

    def test_is_booking_related(self):
        from anastasia.booking_recipes.recorder import _is_booking_related

        assert _is_booking_related("/api/booking/create", "POST", None) is True
        assert _is_booking_related("/api/analytics", "POST", None) is False
        assert _is_booking_related(
            "/api/step", "POST", '{"passenger": {"name": "John"}}'
        ) is True

    def test_network_capture_save_load(self, tmp_path):
        from anastasia.booking_recipes.recorder import CapturedRequest, NetworkCapture

        capture = NetworkCapture(
            airline="TestAir",
            base_url="https://testair.com",
            captured_at="2026-04-21T12:00:00Z",
            duration_seconds=120,
            requests=[
                CapturedRequest(
                    timestamp=1.5,
                    method="POST",
                    url="https://testair.com/api/search",
                    headers={"content-type": "application/json"},
                    body='{"origin": "JFK"}',
                    resource_type="xhr",
                    status_code=200,
                    response_body='{"offers": []}',
                    is_api_call=True,
                    is_booking_related=True,
                    category="search",
                ),
                CapturedRequest(
                    timestamp=5.0,
                    method="GET",
                    url="https://testair.com/logo.png",
                    headers={},
                    body=None,
                    resource_type="image",
                    is_api_call=False,
                    is_booking_related=False,
                    category="other",
                ),
            ],
            cookies=[{"name": "session", "domain": "testair.com"}],
        )

        path = str(tmp_path / "capture.json")
        capture.save(path)

        loaded = NetworkCapture.load(path)
        assert loaded.airline == "TestAir"
        assert len(loaded.requests) == 2
        assert len(loaded.api_requests) == 1
        assert len(loaded.booking_requests) == 1
        assert loaded.api_requests[0].category == "search"


# ─── AI Recipe Generator Tests ───────────────────────────────────────────────

class TestAIRecipeGenerator:
    """Test the AI recipe generation (mocked Anthropic calls)."""

    def test_prepare_capture_summary(self):
        from anastasia.booking_recipes.generator import AIRecipeGenerator
        from anastasia.booking_recipes.recorder import CapturedRequest, NetworkCapture

        generator = AIRecipeGenerator(anthropic_api_key="test")

        capture = NetworkCapture(
            airline="TestAir",
            base_url="https://testair.com",
            captured_at="2026-04-21",
            duration_seconds=60,
            requests=[
                CapturedRequest(
                    timestamp=1.0, method="POST",
                    url="https://testair.com/api/search",
                    headers={"content-type": "application/json"},
                    body='{"origin": "JFK"}', resource_type="xhr",
                    status_code=200, response_body='{"offers": [{"id": "off1"}]}',
                    is_api_call=True, is_booking_related=True, category="search",
                ),
            ],
        )

        summary = generator._prepare_capture_summary(capture)
        assert "SEARCH" in summary
        assert "/api/search" in summary
        assert "POST" in summary

    @patch("anthropic.Anthropic")
    def test_generate_from_capture(self, mock_anthropic_cls):
        from anastasia.booking_recipes.generator import AIRecipeGenerator
        from anastasia.booking_recipes.recorder import CapturedRequest, NetworkCapture

        # Mock Anthropic response
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=json.dumps({
            "recipe_id": "testair_recipe",
            "airline_group": "testair",
            "airlines": ["TA"],
            "base_url": "https://testair.com",
            "steps": [
                {"name": "search", "method": "POST", "url": "/api/search",
                 "body": {"origin": "${origin_iata}"}, "response_extract": {"offer_id": "$.id"},
                 "validation": {"status_code": 200}},
            ],
            "error_patterns": {},
            "metadata": {},
        }))]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        mock_anthropic_cls.return_value = mock_client

        generator = AIRecipeGenerator(anthropic_api_key="sk-test")

        capture = NetworkCapture(
            airline="TestAir", base_url="https://testair.com",
            captured_at="2026-04-21", duration_seconds=60,
            requests=[CapturedRequest(
                timestamp=1.0, method="POST", url="/api/search",
                headers={}, body='{}', resource_type="xhr",
                status_code=200, is_api_call=True,
                is_booking_related=True, category="search",
            )],
        )

        recipe_data = generator.generate_from_capture(
            capture, airline_group="testair", airlines=["TA"]
        )

        assert recipe_data["recipe_id"] == "testair_recipe"
        assert recipe_data["airlines"] == ["TA"]
        assert len(recipe_data["steps"]) == 1
        assert recipe_data["metadata"]["created_by"] == "anastasia_recipe_generator"

    def test_save_recipe(self, tmp_path):
        from anastasia.booking_recipes.generator import AIRecipeGenerator

        generator = AIRecipeGenerator()
        recipe_data = {
            "recipe_id": "save_test",
            "airline_group": "test",
            "airlines": ["ST"],
            "base_url": "https://test.com",
            "steps": [],
        }

        path = generator.save_recipe(recipe_data, output_dir=tmp_path)
        assert path.exists()
        loaded = json.loads(path.read_text())
        assert loaded["recipe_id"] == "save_test"


# ─── BookingRecipeModule Tests ───────────────────────────────────────────────

class TestBookingRecipeModule:
    """Test the NeuronModule interface."""

    def test_initialize_and_health(self, tmp_path):
        from anastasia.booking_recipes import BookingRecipeModule

        # Create a recipe card
        card = {
            "recipe_id": "test", "airline_group": "test",
            "airlines": ["TT"], "base_url": "https://test.com", "steps": [],
        }
        (tmp_path / "test.json").write_text(json.dumps(card))

        module = BookingRecipeModule()
        module.initialize(
            event_bus=MagicMock(),
            config={"recipe_cards_dir": str(tmp_path)},
        )

        health = module.health_check()
        assert health["healthy"] is True
        assert health["recipes_loaded"] == 1
        assert health["airlines_covered"] == 1

    def test_has_recipe_for(self, tmp_path):
        from anastasia.booking_recipes import BookingRecipeModule

        card = {
            "recipe_id": "lh", "airline_group": "lufthansa",
            "airlines": ["LH", "LX"], "base_url": "https://lh.com", "steps": [],
        }
        (tmp_path / "lh.json").write_text(json.dumps(card))

        module = BookingRecipeModule()
        module.initialize(event_bus=MagicMock(), config={"recipe_cards_dir": str(tmp_path)})

        assert module.has_recipe_for("LH") is True
        assert module.has_recipe_for("LX") is True
        assert module.has_recipe_for("AA") is False

    def test_record_execution_stats(self):
        from anastasia.booking_recipes import BookingRecipeModule

        module = BookingRecipeModule()
        module._initialized = True

        module.record_execution(success=True)
        module.record_execution(success=True)
        module.record_execution(success=False)

        health = module.health_check()
        assert health["total_executions"] == 3
        assert health["total_failures"] == 1
        assert health["success_rate"] == 66.7

    def test_shutdown(self, tmp_path):
        from anastasia.booking_recipes import BookingRecipeModule

        module = BookingRecipeModule()
        module.initialize(event_bus=MagicMock(), config={"recipe_cards_dir": str(tmp_path)})
        assert module.health_check()["healthy"] is True

        module.shutdown()
        assert module.health_check()["healthy"] is False


# ─── Integration Smoke Test ──────────────────────────────────────────────────

class TestRecipeIntegration:
    """End-to-end recipe load → variable resolution → step validation."""

    def test_full_recipe_variable_flow(self, tmp_path):
        """Load a recipe, resolve all variables, validate step structure."""
        from anastasia.booking_recipes import BookingRecipe, RecipeRegistry
        from anastasia.booking_recipes.engine import _resolve_template

        card = {
            "recipe_id": "integration_test",
            "airline_group": "test_airline",
            "airlines": ["IA"],
            "base_url": "https://integration-airline.com",
            "session_setup": {
                "load_url": "https://integration-airline.com/en/",
                "extract_tokens": {
                    "csrf": {"source": "cookie", "name": "XSRF"}
                },
            },
            "steps": [
                {
                    "name": "search",
                    "method": "POST",
                    "url": "/api/search",
                    "headers": {"X-CSRF": "${csrf}"},
                    "body": {
                        "from": "${origin_iata}",
                        "to": "${destination_iata}",
                        "date": "${departure_date}",
                        "pax": [{"first": "${pax_first_name}", "last": "${pax_last_name}"}],
                    },
                    "response_extract": {"offer_id": "$.offers[0].id"},
                    "validation": {"status_code": 200, "required_fields": ["offer_id"]},
                },
                {
                    "name": "submit_payment",
                    "method": "POST",
                    "url": "/api/booking/${offer_id}/pay",
                    "body": {"card": "${card_number}", "cvv": "${card_cvv}"},
                    "response_extract": {"pnr": "$.confirmation"},
                    "validation": {"status_code": [200, 201]},
                },
            ],
            "card_data_wipe": {
                "after_step": "submit_payment",
                "on_failure": True,
                "fields": ["card_number", "card_cvv"],
            },
        }

        path = tmp_path / "integration.json"
        path.write_text(json.dumps(card))

        # Load
        registry = RecipeRegistry()
        registry.load_from_directory(tmp_path)
        recipe = registry.find_by_airline("IA")
        assert recipe is not None

        # Resolve variables
        variables = {
            "csrf": "token_abc",
            "origin_iata": "JFK",
            "destination_iata": "NRT",
            "departure_date": "2026-06-01",
            "pax_first_name": "Jane",
            "pax_last_name": "Smith",
            "card_number": "4111111111111111",
            "card_cvv": "123",
            "offer_id": "off_999",
        }

        # Resolve step 0 body
        resolved_body = _resolve_template(recipe.steps[0].body, variables)
        assert resolved_body["from"] == "JFK"
        assert resolved_body["to"] == "NRT"
        assert resolved_body["pax"][0]["first"] == "Jane"

        # Resolve step 1 URL
        from anastasia.booking_recipes.engine import _resolve_variable
        resolved_url = _resolve_variable(recipe.steps[1].url, variables)
        assert resolved_url == "/api/booking/off_999/pay"

        # Resolve step 1 body
        resolved_pay = _resolve_template(recipe.steps[1].body, variables)
        assert resolved_pay["card"] == "4111111111111111"
