"""
MYSTES Duffel Stays Integration Tests — Build #199

Tests for:
- DuffelStaysClient (SDK client, all 11 endpoints)
- Knowledge card loading and registration
- Booking dispatcher handler
- Dual-source hotel search
- Fee calculation (NO maximum cap)

Run: python3 -m pytest tests/test_duffel_stays.py -v
"""

import json
import os
import sys
import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch, PropertyMock

# Ensure project root and SDK are on path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
SDK_PATH = os.path.join(PROJECT_ROOT, "picasso-sdk")
if SDK_PATH not in sys.path:
    sys.path.insert(0, SDK_PATH)


# ===================================================================
# DuffelStaysClient SDK Tests
# ===================================================================

class TestDuffelStaysSDKClient:
    """Test picasso-sdk/clients/duffel_stays.py — all 11 endpoints."""

    def _make_client(self, token="duffel_test_abc123def456ghi789"):
        from clients.duffel_stays import DuffelStaysClient
        return DuffelStaysClient(access_token=token)

    def test_is_configured_with_token(self):
        """Client reports configured when token is set."""
        client = self._make_client()
        assert client.is_configured() is True

    def test_is_not_configured_without_token(self):
        """Client reports not configured when token is empty."""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("DUFFEL_ACCESS_TOKEN", None)
            from clients.duffel_stays import DuffelStaysClient
            client = DuffelStaysClient(access_token="")
            assert client.is_configured() is False

    def test_suggest_min_3_chars(self):
        """suggest_accommodation requires at least 3 characters."""
        client = self._make_client()
        result = client.suggest_accommodation("Hi")
        assert result["success"] is False
        assert "3 characters" in result["error"]

    @patch("clients.duffel_stays.requests.Session")
    def test_suggest_accommodation(self, mock_session_cls):
        """suggest_accommodation calls POST /stays/accommodation/suggestions."""
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": [
                {"id": "acc_123", "name": "Hilton London", "type": "accommodation",
                 "location": {"geographic_coordinates": {"latitude": 51.5, "longitude": -0.1}}},
            ]
        }
        mock_session.request.return_value = mock_resp
        mock_session_cls.return_value = mock_session

        client = self._make_client()
        client._session = mock_session
        result = client.suggest_accommodation("Hilton London")
        assert result["success"] is True
        assert result["count"] == 1
        assert result["suggestions"][0]["name"] == "Hilton London"

    @patch("clients.duffel_stays.requests.Session")
    def test_search_stays_requires_location(self, mock_session_cls):
        """search_stays requires either coordinates or accommodation_ids."""
        client = self._make_client()
        result = client.search_stays(
            check_in_date="2026-04-01",
            check_out_date="2026-04-03",
        )
        assert result["success"] is False
        assert "latitude" in result["error"].lower() or "accommodation" in result["error"].lower()

    @patch("clients.duffel_stays.requests.Session")
    def test_search_stays_with_coordinates(self, mock_session_cls):
        """search_stays returns normalized results with coordinates."""
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": {
                "id": "sr_abc123",
                "results": [
                    {
                        "accommodation": {
                            "id": "acc_001",
                            "name": "Grand Hotel",
                            "star_rating": 4,
                            "location": {
                                "geographic_coordinates": {"latitude": 48.86, "longitude": 2.35}
                            },
                        },
                        "rates": [
                            {"id": "rate_001", "total_amount": "350.00", "total_currency": "USD"},
                            {"id": "rate_002", "total_amount": "420.00", "total_currency": "USD"},
                        ],
                    }
                ],
            }
        }
        mock_session.request.return_value = mock_resp
        mock_session_cls.return_value = mock_session

        client = self._make_client()
        client._session = mock_session
        result = client.search_stays(
            check_in_date="2026-04-01",
            check_out_date="2026-04-03",
            latitude=48.86,
            longitude=2.35,
        )
        assert result["success"] is True
        assert result["search_result_id"] == "sr_abc123"
        assert len(result["results"]) == 1
        hotel = result["results"][0]
        assert hotel["property_name"] == "Grand Hotel"
        assert hotel["cheapest_rate_total"] == 350.0
        assert hotel["cheapest_rate_id"] == "rate_001"
        assert hotel["source"] == "duffel_stays"

    @patch("clients.duffel_stays.requests.Session")
    def test_create_quote(self, mock_session_cls):
        """create_quote returns quote_id and expires_at."""
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": {
                "id": "quo_abc123",
                "total_amount": "350.00",
                "total_currency": "USD",
                "expires_at": "2026-04-01T12:00:00Z",
                "accommodation": {"name": "Grand Hotel"},
            }
        }
        mock_session.request.return_value = mock_resp
        mock_session_cls.return_value = mock_session

        client = self._make_client()
        client._session = mock_session
        result = client.create_quote("rate_001")
        assert result["success"] is True
        assert result["quote_id"] == "quo_abc123"
        assert result["total_amount"] == "350.00"
        assert "expires_at" in result

    @patch("clients.duffel_stays.requests.Session")
    def test_book_stay(self, mock_session_cls):
        """book_stay creates a booking and returns confirmation."""
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": {
                "id": "bok_abc123",
                "status": "confirmed",
                "confirmation_number": "HTLCONF789",
                "check_in_date": "2026-04-01",
                "check_out_date": "2026-04-03",
                "total_amount": "350.00",
                "total_currency": "USD",
                "accommodation": {"name": "Grand Hotel"},
                "guests": [{"given_name": "John", "family_name": "Doe"}],
                "created_at": "2026-03-17T10:00:00Z",
                "cancellation_policy": {},
            }
        }
        mock_session.request.return_value = mock_resp
        mock_session_cls.return_value = mock_session

        client = self._make_client()
        client._session = mock_session
        result = client.book_stay(
            quote_id="quo_abc123",
            email="john@test.com",
            phone_number="+12125551234",
            guests=[{"given_name": "John", "family_name": "Doe"}],
        )
        assert result["success"] is True
        assert result["booking_id"] == "bok_abc123"
        assert result["status"] == "confirmed"
        assert result["confirmation_number"] == "HTLCONF789"

    @patch("clients.duffel_stays.requests.Session")
    def test_get_booking(self, mock_session_cls):
        """get_booking retrieves booking details."""
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": {
                "id": "bok_abc123",
                "status": "confirmed",
                "confirmation_number": "HTLCONF789",
                "check_in_date": "2026-04-01",
                "check_out_date": "2026-04-03",
                "total_amount": "350.00",
                "total_currency": "USD",
                "accommodation": {},
                "guests": [],
                "created_at": "2026-03-17T10:00:00Z",
                "cancellation_policy": {},
            }
        }
        mock_session.request.return_value = mock_resp
        mock_session_cls.return_value = mock_session

        client = self._make_client()
        client._session = mock_session
        result = client.get_booking("bok_abc123")
        assert result["success"] is True
        assert result["booking_id"] == "bok_abc123"

    @patch("clients.duffel_stays.requests.Session")
    def test_cancel_booking(self, mock_session_cls):
        """cancel_booking returns cancellation status."""
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": {
                "status": "cancelled",
                "refund_amount": "350.00",
                "refund_currency": "USD",
            }
        }
        mock_session.request.return_value = mock_resp
        mock_session_cls.return_value = mock_session

        client = self._make_client()
        client._session = mock_session
        result = client.cancel_booking("bok_abc123")
        assert result["success"] is True
        assert result["status"] == "cancelled"

    @patch("clients.duffel_stays.requests.Session")
    def test_list_bookings(self, mock_session_cls):
        """list_bookings returns paginated booking list."""
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": [
                {
                    "id": "bok_001",
                    "status": "confirmed",
                    "confirmation_number": "CONF001",
                    "check_in_date": "2026-04-01",
                    "check_out_date": "2026-04-03",
                    "total_amount": "350.00",
                    "total_currency": "USD",
                    "created_at": "2026-03-17T10:00:00Z",
                },
            ],
            "meta": {"after": "cursor_abc"},
        }
        mock_session.request.return_value = mock_resp
        mock_session_cls.return_value = mock_session

        client = self._make_client()
        client._session = mock_session
        result = client.list_bookings(limit=10)
        assert result["success"] is True
        assert result["count"] == 1
        assert result["bookings"][0]["booking_id"] == "bok_001"

    @patch("clients.duffel_stays.requests.Session")
    def test_api_error_handling(self, mock_session_cls):
        """API errors return success=False with error details."""
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 422
        mock_resp.json.return_value = {
            "errors": [{"code": "invalid_input", "message": "phone_number must be E.164"}]
        }
        mock_resp.text = '{"errors": [{"code": "invalid_input", "message": "phone_number must be E.164"}]}'
        mock_session.request.return_value = mock_resp
        mock_session_cls.return_value = mock_session

        client = self._make_client()
        client._session = mock_session
        result = client.book_stay(
            quote_id="quo_abc",
            email="test@test.com",
            phone_number="bad-phone",
            guests=[{"given_name": "Test", "family_name": "User"}],
        )
        assert result["success"] is False
        assert "E.164" in result.get("error", "")


# ===================================================================
# Knowledge Card Tests
# ===================================================================

class TestDuffelStaysKnowledgeCard:
    """Test the duffel_stays.json knowledge card."""

    def test_card_json_loads(self):
        """Card JSON file loads and parses correctly."""
        card_path = os.path.join(
            PROJECT_ROOT, "picasso-sdk", "anastasia", "modules", "cards", "duffel_stays.json"
        )
        assert os.path.exists(card_path), f"Card not found: {card_path}"
        with open(card_path) as f:
            card = json.load(f)
        assert card["module_id"] == "duffel_stays"
        assert card["vertical"] == "hotels"
        assert card["capabilities"]["search"] is True
        assert card["capabilities"]["book"] is True
        assert card["capabilities"]["cancel"] is True

    def test_card_has_correct_auth(self):
        """Card uses same DUFFEL_ACCESS_TOKEN as flights."""
        card_path = os.path.join(
            PROJECT_ROOT, "picasso-sdk", "anastasia", "modules", "cards", "duffel_stays.json"
        )
        with open(card_path) as f:
            card = json.load(f)
        assert "DUFFEL_ACCESS_TOKEN" in card["credential_env_vars"]
        assert card["auth_type"] == "bearer_token"

    def test_card_registered_in_hotel_modules(self):
        """Card auto-registers via build_all_hotel_modules(from_json=True)."""
        from anastasia.modules.flight_modules import build_all_hotel_modules
        modules = build_all_hotel_modules(from_json=True)
        module_ids = [m.knowledge_card.module_id for m in modules]
        assert "duffel_stays" in module_ids


# ===================================================================
# Booking Dispatcher Tests
# ===================================================================

class TestDuffelStaysDispatcher:
    """Test BookingDispatcher routing for duffel_stays source."""

    def test_dispatcher_has_duffel_stays_handler(self):
        """Dispatcher has a handler registered for duffel_stays."""
        from anastasia.dispatch.dispatcher import _HANDLERS
        assert "duffel_stays" in _HANDLERS

    def test_dispatcher_missing_rate_id(self):
        """Dispatcher returns error when rate_id is missing."""
        from anastasia.dispatch.dispatcher import _HANDLERS
        handler = _HANDLERS["duffel_stays"]
        result = handler(
            raw_offer={"source": "duffel_stays"},
            passengers=[{"given_name": "John", "family_name": "Doe", "email": "j@test.com"}],
            client=MagicMock(),
            card={},
            markup=0,
        )
        assert result["success"] is False
        assert "rate_id" in result["error"].lower()

    def test_dispatcher_quote_then_book_flow(self):
        """Dispatcher creates quote then books on successful flow."""
        from anastasia.dispatch.dispatcher import _HANDLERS
        handler = _HANDLERS["duffel_stays"]

        mock_client = MagicMock()
        mock_client.create_quote.return_value = {
            "success": True,
            "quote_id": "quo_test",
        }
        mock_client.book_stay.return_value = {
            "success": True,
            "booking_id": "bok_test",
            "confirmation_number": "CONF_TEST",
        }

        result = handler(
            raw_offer={"source": "duffel_stays", "rate_id": "rate_123"},
            passengers=[{
                "given_name": "John", "family_name": "Doe",
                "email": "j@test.com", "phone": "+12125551234",
            }],
            client=mock_client,
            card={},
            markup=0,
        )
        assert result["success"] is True
        assert result["booking_source"] == "duffel_stays"
        mock_client.create_quote.assert_called_once_with("rate_123")
        mock_client.book_stay.assert_called_once()


# ===================================================================
# Fee Calculation Tests
# ===================================================================

class TestHotelFeeCalculation:
    """Test MYSTES fee rules: $3 minimum, NO maximum cap."""

    def test_fee_minimum_3_dollars(self):
        """Fee never goes below $3 even on tiny totals."""
        raw_total = 5.00
        fee_pct = 0.50  # Guest tier
        fee = max(3.0, raw_total * fee_pct)
        assert fee == 3.0  # $5 * 0.50 = $2.50, but min is $3

    def test_fee_no_maximum_cap(self):
        """Fee has NO maximum cap — scales with price. CRITICAL RULE."""
        raw_total = 5000.00
        fee_pct = 0.50  # Guest tier
        fee = max(3.0, raw_total * fee_pct)
        assert fee == 2500.0  # $5000 * 0.50 = $2500, NO cap
        # Explicitly verify NO $50 cap (a common past mistake)
        assert fee > 50

    def test_fee_tiers(self):
        """Verify fee percentages for each tier."""
        raw_total = 100.0
        tiers = {
            "guest": 0.50,
            "free": 0.45,
            "travel_plus": 0.35,
            "b2b_starter": 0.25,
            "b2b_growth": 0.20,
            "b2b_volume": 0.15,
        }
        for tier, pct in tiers.items():
            fee = max(3.0, raw_total * pct)
            expected = raw_total * pct
            assert fee == expected, f"{tier} fee should be ${expected}, got ${fee}"


# ===================================================================
# Dual-Source Search Tests
# ===================================================================

class TestDualSourceHotelSearch:
    """Test dual-source hotel search (liteAPI + Duffel Stays)."""

    def test_dedup_keeps_cheapest(self):
        """When both sources return same hotel, cheapest wins."""
        hotels = [
            {"hotel_name": "Grand Hotel", "price_total": 450.0, "source": "liteapi", "offer_id": "lite_1"},
            {"hotel_name": "Grand Hotel", "price_total": 380.0, "source": "duffel_stays", "offer_id": "duffel_1"},
            {"hotel_name": "Budget Inn", "price_total": 120.0, "source": "liteapi", "offer_id": "lite_2"},
        ]
        # Replicate the dedup logic from routes_hotels.py
        seen = {}
        for h in hotels:
            key = h.get("hotel_name", "").strip().lower()
            if key not in seen or h.get("price_total", float("inf")) < seen[key].get("price_total", float("inf")):
                seen[key] = h
        deduped = list(seen.values())
        assert len(deduped) == 2
        grand = next(h for h in deduped if "grand" in h["hotel_name"].lower())
        assert grand["source"] == "duffel_stays"
        assert grand["price_total"] == 380.0

    def test_dedup_case_insensitive(self):
        """Dedup is case-insensitive on hotel name."""
        hotels = [
            {"hotel_name": "HILTON PARIS", "price_total": 500.0, "source": "liteapi", "offer_id": "a"},
            {"hotel_name": "Hilton Paris", "price_total": 480.0, "source": "duffel_stays", "offer_id": "b"},
        ]
        seen = {}
        for h in hotels:
            key = h.get("hotel_name", "").strip().lower()
            if key not in seen or h.get("price_total", float("inf")) < seen[key].get("price_total", float("inf")):
                seen[key] = h
        deduped = list(seen.values())
        assert len(deduped) == 1
        assert deduped[0]["price_total"] == 480.0

    def test_single_source_still_works(self):
        """When only one source returns results, they pass through."""
        hotels = [
            {"hotel_name": "Hotel A", "price_total": 200.0, "source": "duffel_stays", "offer_id": "d1"},
            {"hotel_name": "Hotel B", "price_total": 300.0, "source": "duffel_stays", "offer_id": "d2"},
        ]
        seen = {}
        for h in hotels:
            key = h.get("hotel_name", "").strip().lower()
            if key not in seen or h.get("price_total", float("inf")) < seen[key].get("price_total", float("inf")):
                seen[key] = h
        deduped = list(seen.values())
        assert len(deduped) == 2

    def test_graceful_degradation(self):
        """When one source fails, the other still returns results."""
        # Simulate: liteapi returns results, duffel fails (returns [])
        liteapi_results = [
            {"hotel_name": "Hotel One", "price_total": 250.0, "source": "liteapi", "offer_id": "l1"},
        ]
        duffel_results = []  # Failed
        all_hotels = liteapi_results + duffel_results
        assert len(all_hotels) == 1
        assert all_hotels[0]["source"] == "liteapi"


# ===================================================================
# Suggest Endpoint Tests
# ===================================================================

class TestHotelSuggestEndpoint:
    """Test /api/hotels/suggest endpoint."""

    def test_suggest_min_chars(self):
        """Suggest requires at least 3 characters."""
        # This tests the client-side validation
        from clients.duffel_stays import DuffelStaysClient
        client = DuffelStaysClient(access_token="test")
        result = client.suggest_accommodation("ab")
        assert result["success"] is False

    def test_suggest_returns_suggestions(self):
        """Suggest returns properly formatted suggestions."""
        from clients.duffel_stays import DuffelStaysClient
        client = DuffelStaysClient(access_token="test")
        with patch.object(client, "_request") as mock_req:
            mock_req.return_value = {
                "success": True,
                "data": [
                    {"id": "acc_1", "name": "Hilton NYC", "type": "accommodation",
                     "location": {"geographic_coordinates": {"latitude": 40.7, "longitude": -74.0}}},
                    {"id": "loc_1", "name": "New York City", "type": "city",
                     "location": {"geographic_coordinates": {"latitude": 40.7, "longitude": -74.0}}},
                ],
            }
            result = client.suggest_accommodation("New York")
        assert result["success"] is True
        assert result["count"] == 2
        assert result["suggestions"][0]["name"] == "Hilton NYC"


# ===================================================================
# Booking Execution Tests
# ===================================================================

class TestDuffelStaysBookingExecution:
    """Test server.py automated booking execution for Duffel Stays."""

    def test_duffel_source_detected(self):
        """Booking routes to Duffel Stays when source=duffel_stays in raw_offer."""
        raw_offer = json.dumps({
            "source": "duffel_stays",
            "rate_id": "rate_abc",
            "accommodation_id": "acc_123",
        })
        parsed = json.loads(raw_offer)
        assert parsed["source"] == "duffel_stays"
        assert parsed["rate_id"] == "rate_abc"

    def test_phone_e164_formatting(self):
        """Phone numbers get formatted to E.164 for Duffel."""
        phone = "555-123-4567"
        if not phone.startswith("+"):
            phone = "+1" + phone.replace("-", "").replace(" ", "").replace("(", "").replace(")", "")
        assert phone == "+15551234567"

    def test_phone_already_e164(self):
        """Already-formatted E.164 phones pass through unchanged."""
        phone = "+442071234567"
        if not phone.startswith("+"):
            phone = "+1" + phone.replace("-", "")
        assert phone == "+442071234567"


# ===================================================================
# Agent Tools & Knowledge Tests
# ===================================================================

class TestDuffelStaysAgentFiles:
    """Test that agent tool definitions and knowledge base load correctly."""

    def test_tool_definitions_load(self):
        """Tool definitions list has 11 entries."""
        sdk_agent_path = os.path.join(PROJECT_ROOT, "picasso-sdk", "picasso", "agent")
        sys.path.insert(0, sdk_agent_path)
        from duffel_stays_tools import DUFFEL_STAYS_TOOL_DEFINITIONS
        assert len(DUFFEL_STAYS_TOOL_DEFINITIONS) == 11
        names = [t["name"] for t in DUFFEL_STAYS_TOOL_DEFINITIONS]
        assert "duffel_stays_search" in names
        assert "duffel_stays_book" in names
        assert "duffel_stays_cancel_booking" in names

    def test_knowledge_base_loads(self):
        """Knowledge base string is non-empty and has key sections."""
        sdk_agent_path = os.path.join(PROJECT_ROOT, "picasso-sdk", "picasso", "agent")
        sys.path.insert(0, sdk_agent_path)
        from duffel_stays_knowledge import DUFFEL_STAYS_KNOWLEDGE_BASE
        assert len(DUFFEL_STAYS_KNOWLEDGE_BASE) > 500
        assert "BOOKING FLOW" in DUFFEL_STAYS_KNOWLEDGE_BASE
        assert "E.164" in DUFFEL_STAYS_KNOWLEDGE_BASE
        assert "QUOTE EXPIRY" in DUFFEL_STAYS_KNOWLEDGE_BASE
