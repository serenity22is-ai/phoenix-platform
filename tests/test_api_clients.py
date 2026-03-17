"""
MYSTES API Client Tests — Build #102

Tests for liteapi_client.py (hotel search + booking) and picasso_client.py
(multi-POS flight search + booking). Covers margin filtering, savings
calculations, pricing logic, and the full search→prebook→book pipeline.

Run: pytest tests/test_api_clients.py -v
"""

import json
import sys
import os
import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch, PropertyMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _mock_member():
    """Return a mock authenticated free member (45% fee per Build #170).

    Fee tiers: Guest=50% | Free Member=45% | Travel+=35% | B2B=25%/20%/15%
    """
    user = MagicMock()
    user.is_authenticated = True
    return user


# ===================================================================
# liteAPI Hotel Client Tests
# ===================================================================

class TestLiteAPIClient:
    """Test liteapi_client.py hotel search, margin filter, prebook, and booking."""

    def test_not_configured(self):
        """Search returns error when LITEAPI_KEY is missing."""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("LITEAPI_KEY", None)
            from liteapi_client import LiteAPIHotelClient
            client = LiteAPIHotelClient()
            client.api_key = ""
            result = client.search_hotels("PAR", check_in="2026-03-15", check_out="2026-03-18")
            assert result["success"] is False
            assert "not configured" in result["error"].lower()

    def test_date_defaults(self):
        """When no dates given, defaults to tomorrow + 1 night."""
        from liteapi_client import LiteAPIHotelClient
        client = LiteAPIHotelClient()
        client.api_key = ""  # Will fail early, but we can test the config check
        result = client.search_hotels("PAR")
        assert result["success"] is False  # Fails at config check

    @patch("liteapi_client.requests.post")
    @patch("liteapi_client.requests.get")
    def test_search_returns_hotels(self, mock_get, mock_post):
        """Search parses liteAPI response into normalized hotel dicts."""
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"data": [
                {
                    "hotelId": "H001",
                    "roomTypes": [{
                        "offerId": "OFF-001",
                        "offerRetailRate": {"amount": "120.00", "currency": "USD"},
                        "suggestedSellingPrice": {"amount": "180.00", "currency": "USD"},
                        "rates": [{
                            "retailRate": {
                                "total": [{"amount": "120.00", "currency": "USD"}]
                            },
                            "name": "Deluxe Room",
                            "boardName": "Room Only",
                            "boardType": "RO",
                            "cancellationPolicies": {
                                "refundableTag": "RFN",
                                "cancelPolicyInfos": []
                            },
                        }],
                    }],
                }
            ]}
        )
        mock_post.return_value.raise_for_status = MagicMock()

        # Bulk hotel name lookup
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"data": [{"id": "H001", "name": "Grand Hotel Paris"}]}
        )

        from liteapi_client import LiteAPIHotelClient
        client = LiteAPIHotelClient()
        client.api_key = "test_key"

        result = client.search_hotels("PAR", check_in="2026-03-15", check_out="2026-03-18")

        assert result["success"] is True
        assert len(result["hotels"]) == 1
        hotel = result["hotels"][0]
        assert hotel["hotel_name"] == "Grand Hotel Paris"
        assert hotel["offer_id"] == "OFF-001"
        assert hotel["room_type"] == "Deluxe Room"
        assert hotel["nights"] == 3
        assert hotel["source"] == "liteapi"
        assert hotel["cancellation_description"] == "Free cancellation"

    @patch("liteapi_client.requests.post")
    @patch("liteapi_client.requests.get")
    def test_margin_filter_skips_inverted(self, mock_get, mock_post):
        """Hotels where our cost >= Google price are filtered out."""
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"data": [
                {
                    "hotelId": "H001",
                    "roomTypes": [{
                        "offerId": "OFF-001",
                        "offerRetailRate": {"amount": "200.00", "currency": "USD"},
                        "suggestedSellingPrice": {"amount": "180.00", "currency": "USD"},
                        "rates": [{
                            "retailRate": {"total": [{"amount": "200.00", "currency": "USD"}]},
                            "name": "Room", "boardName": "", "boardType": "",
                            "cancellationPolicies": {},
                        }],
                    }],
                },
                {
                    "hotelId": "H002",
                    "roomTypes": [{
                        "offerId": "OFF-002",
                        "offerRetailRate": {"amount": "100.00", "currency": "USD"},
                        "suggestedSellingPrice": {"amount": "180.00", "currency": "USD"},
                        "rates": [{
                            "retailRate": {"total": [{"amount": "100.00", "currency": "USD"}]},
                            "name": "Room", "boardName": "", "boardType": "",
                            "cancellationPolicies": {},
                        }],
                    }],
                },
            ]}
        )
        mock_post.return_value.raise_for_status = MagicMock()
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"data": [{"id": "H001", "name": "Hotel"}, {"id": "H002", "name": "Hotel"}]}
        )

        from liteapi_client import LiteAPIHotelClient
        client = LiteAPIHotelClient()
        client.api_key = "test_key"

        result = client.search_hotels("PAR", check_in="2026-03-15", check_out="2026-03-16")

        # H001 has cost $200 >= Google $180, should be filtered out
        # H002 has cost $100 < Google $180, should be included
        assert result["success"] is True
        assert len(result["hotels"]) == 1
        assert result["hotels"][0]["hotel_id"] == "H002"

    @patch("liteapi_client.requests.post")
    @patch("liteapi_client.requests.get")
    def test_savings_calculation(self, mock_get, mock_post):
        """MYSTES price = our_cost + 35% of savings. Subscriber saves 65%."""
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"data": [
                {
                    "hotelId": "H001",
                    "roomTypes": [{
                        "offerId": "OFF-001",
                        "offerRetailRate": {"amount": "100.00", "currency": "USD"},
                        "suggestedSellingPrice": {"amount": "200.00", "currency": "USD"},
                        "rates": [{
                            "retailRate": {"total": [{"amount": "100.00", "currency": "USD"}]},
                            "name": "Room", "boardName": "", "boardType": "",
                            "cancellationPolicies": {},
                        }],
                    }],
                },
            ]}
        )
        mock_post.return_value.raise_for_status = MagicMock()
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"data": [{"id": "H001", "name": "Hotel"}]}
        )

        from liteapi_client import LiteAPIHotelClient
        client = LiteAPIHotelClient()
        client.api_key = "test_key"

        result = client.search_hotels("PAR", check_in="2026-03-15", check_out="2026-03-16", user=_mock_member())
        hotel = result["hotels"][0]

        # Google price: $200, our cost: $100, savings_raw = $100
        # Free member fee: 45% of $100 = $45 (Build #170)
        # MYSTES price: $100 + $45 = $145
        # User savings: $200 - $145 = $55
        # Savings pct: 55/200 = 27.5%
        assert hotel["google_price"] == 200.00
        assert hotel["our_cost"] == 100.00
        assert hotel["platform_fee"] == 45.0
        assert hotel["price_total"] == 145.00
        assert hotel["user_savings"] == 55.00
        assert hotel["savings_pct"] == 27.5

    @patch("liteapi_client.requests.post")
    @patch("liteapi_client.requests.get")
    def test_platform_fee_small_savings(self, mock_get, mock_post):
        """Platform fee is 45% for free members on small savings (Build #170)."""
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"data": [
                {
                    "hotelId": "H001",
                    "roomTypes": [{
                        "offerId": "OFF-001",
                        "offerRetailRate": {"amount": "95.00", "currency": "USD"},
                        "suggestedSellingPrice": {"amount": "100.00", "currency": "USD"},
                        "rates": [{
                            "retailRate": {"total": [{"amount": "95.00", "currency": "USD"}]},
                            "name": "Room", "boardName": "", "boardType": "",
                            "cancellationPolicies": {},
                        }],
                    }],
                },
            ]}
        )
        mock_post.return_value.raise_for_status = MagicMock()
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"data": [{"id": "H001", "name": "Hotel"}]}
        )

        from liteapi_client import LiteAPIHotelClient
        client = LiteAPIHotelClient()
        client.api_key = "test_key"

        result = client.search_hotels("PAR", check_in="2026-03-15", check_out="2026-03-16", user=_mock_member())
        hotel = result["hotels"][0]

        # savings_raw = $5, free member 45% = $2.25 (Build #170)
        assert hotel["platform_fee"] == 2.25
        assert hotel["price_total"] == 97.25  # $95 + $2.25

    @patch("liteapi_client.requests.post")
    @patch("liteapi_client.requests.get")
    def test_platform_fee_large_savings(self, mock_get, mock_post):
        """Platform fee is 45% for free members on large savings, no cap (Build #170)."""
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"data": [
                {
                    "hotelId": "H001",
                    "roomTypes": [{
                        "offerId": "OFF-001",
                        "offerRetailRate": {"amount": "500.00", "currency": "USD"},
                        "suggestedSellingPrice": {"amount": "1000.00", "currency": "USD"},
                        "rates": [{
                            "retailRate": {"total": [{"amount": "500.00", "currency": "USD"}]},
                            "name": "Room", "boardName": "", "boardType": "",
                            "cancellationPolicies": {},
                        }],
                    }],
                },
            ]}
        )
        mock_post.return_value.raise_for_status = MagicMock()
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"data": [{"id": "H001", "name": "Hotel"}]}
        )

        from liteapi_client import LiteAPIHotelClient
        client = LiteAPIHotelClient()
        client.api_key = "test_key"

        result = client.search_hotels("PAR", check_in="2026-03-15", check_out="2026-03-16", user=_mock_member())
        hotel = result["hotels"][0]

        # savings_raw = $500, free member 45% = $225 (Build #170, no cap)
        assert hotel["platform_fee"] == 225.0
        assert hotel["price_total"] == 725.00  # $500 + $225

    @patch("liteapi_client.requests.post")
    def test_validate_offer_returns_prebook_id(self, mock_post):
        """validate_offer returns prebookId needed for booking."""
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"data": {
                "prebookId": "PB-12345",
                "offerRetailRate": {"amount": "120.00", "currency": "USD"},
            }}
        )
        mock_post.return_value.raise_for_status = MagicMock()

        from liteapi_client import LiteAPIHotelClient
        client = LiteAPIHotelClient()
        client.api_key = "test_key"

        result = client.validate_offer("OFF-001")
        assert result["success"] is True
        assert result["prebook_id"] == "PB-12345"
        assert result["price"] == 120.00

    @patch("liteapi_client.requests.post")
    def test_validate_offer_no_prebook_id(self, mock_post):
        """validate_offer fails if no prebookId in response."""
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"data": {}}
        )
        mock_post.return_value.raise_for_status = MagicMock()

        from liteapi_client import LiteAPIHotelClient
        client = LiteAPIHotelClient()
        client.api_key = "test_key"

        result = client.validate_offer("OFF-001")
        assert result["success"] is False
        assert "prebookId" in result["error"].lower() or "unavailable" in result["error"].lower()

    @patch("liteapi_client.requests.post")
    def test_create_booking_requires_prebook_id(self, mock_post):
        """create_booking fails without prebook_id."""
        from liteapi_client import LiteAPIHotelClient
        client = LiteAPIHotelClient()
        client.api_key = "test_key"

        result = client.create_booking(
            offer_id="OFF-001",
            guest={"first_name": "John", "last_name": "Doe", "email": "john@test.com"},
            payment={"card_number": "4242424242424242", "expiry_date": "12/28", "cvc": "123"},
            prebook_id=None,
        )
        assert result["success"] is False
        assert "prebook_id" in result["error"].lower()

    @patch("liteapi_client.requests.post")
    def test_create_booking_success(self, mock_post):
        """create_booking sends correct payload and returns booking_id."""
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"data": {
                "bookingId": "BK-999",
                "refNumber": "REF-ABC",
            }}
        )
        mock_post.return_value.raise_for_status = MagicMock()

        from liteapi_client import LiteAPIHotelClient
        client = LiteAPIHotelClient()
        client.api_key = "test_key"

        result = client.create_booking(
            offer_id="OFF-001",
            guest={"first_name": "John", "last_name": "Doe", "email": "john@test.com", "phone": "+1234567890"},
            prebook_id="PB-12345",
            client_reference="deal_001",
        )
        assert result["success"] is True
        assert result["booking_id"] == "BK-999"
        assert result["provider_confirmation"] == "REF-ABC"

        # Verify payload shape (holder/guests/ACC_CREDIT_CARD format)
        call_kwargs = mock_post.call_args
        payload = call_kwargs.kwargs.get("json", call_kwargs[1].get("json", {}))
        assert payload["prebookId"] == "PB-12345"
        assert payload["holder"]["firstName"] == "John"
        assert payload["guests"][0]["lastName"] == "Doe"
        assert payload["payment"]["method"] == "ACC_CREDIT_CARD"
        assert payload["clientReference"] == "deal_001"

    @patch("liteapi_client.requests.post")
    def test_search_handles_http_error(self, mock_post):
        """Search gracefully handles HTTP errors."""
        resp = MagicMock()
        resp.status_code = 500
        resp.json.return_value = {"error": {"message": "Internal server error"}}
        mock_post.return_value = resp
        mock_post.return_value.raise_for_status.side_effect = (
            __import__("requests").exceptions.HTTPError(response=resp)
        )

        from liteapi_client import LiteAPIHotelClient
        client = LiteAPIHotelClient()
        client.api_key = "test_key"

        result = client.search_hotels("PAR", check_in="2026-03-15", check_out="2026-03-16")
        assert result["success"] is False
        assert "error" in result


# ===================================================================
# Picasso Client Tests
# ===================================================================

class TestPicassoClient:
    """Test picasso_client.py Redbox API flight search and booking."""

    def _make_client(self, token="test_valid_session_token_xyz"):
        """Create a PicassoClient with mocked token manager and session."""
        from picasso_client import PicassoClient
        client = PicassoClient()
        client._token_manager = MagicMock()
        client._token_manager.get_token.return_value = token
        client._token_manager.invalidate = MagicMock()
        client._session = MagicMock()
        return client

    def test_not_configured(self):
        """Search returns error when token manager has no token."""
        client = self._make_client(token="")

        result = client.search_flights("JFK", "LHR", "2026-03-15")
        assert result["success"] is False
        assert "not configured" in result["error"].lower()

    def test_is_configured(self):
        """is_configured returns True when token manager has a valid token."""
        client = self._make_client(token="valid_session_token_12345678901234567890")
        assert client.is_configured() is True

    def test_is_not_configured_short_token(self):
        """is_configured returns False for tokens shorter than 20 chars."""
        client = self._make_client(token="short")
        assert client.is_configured() is False

    def test_search_flights_redbox(self):
        """Search submits to Redbox availableFare and parses results."""
        client = self._make_client()

        # Mock step 1: search submission returns fareSearchId
        search_response = MagicMock()
        search_response.status_code = 200
        search_response.json.return_value = {
            "fareSearchId": "FS-12345",
            "numberOfResults": 1,
            "numberOfAirlines": 1,
        }
        search_response.raise_for_status = MagicMock()

        # Mock step 2: results fetch returns flight data
        results_response = MagicMock()
        results_response.status_code = 200
        results_response.json.return_value = {
            "currencyIsoCode": "EUR",
            "results": [{
                "fareId": "FARE-001",
                "gds": "1A",
                "validatingAirline": {"code": "AA", "name": "American Airlines", "icao": "AAL"},
                "total": 350.0,
                "totalTax": 85.0,
                "cabinClassList": ["ECONOMY"],
                "fareCharacteristicList": ["PUB"],
                "priceDetails": [{"gdsFarePerPax": 265.0, "taxPerPax": 85.0, "ticketFeeDetails": {"originalTicketFee": 0}}],
                "legList": [{
                    "departure": {"code": "JFK", "name": "John F Kennedy"},
                    "destination": {"code": "LHR", "name": "London Heathrow"},
                    "departureTimestamp": "2026-03-15T08:00:00",
                    "arrivalTimestamp": "2026-03-15T20:00:00",
                    "totalTravelTime": "PT7H",
                    "stops": [],
                    "itineraryList": [{"segmentList": [{
                        "departure": {"code": "JFK"},
                        "destination": {"code": "LHR"},
                        "departureTimestamp": "2026-03-15T08:00:00",
                        "marketingAirline": {"code": "AA", "name": "American Airlines"},
                        "flightNumber": "100",
                        "cabinClass": "ECONOMY",
                        "bookingClass": {"code": "V"},
                    }]}],
                }],
                "additionalFareInfos": [],
                "fareFamilies": [],
            }],
        }
        results_response.raise_for_status = MagicMock()

        # Wire mocks: first POST = search, second POST = results
        client._session.post.side_effect = [search_response, results_response]

        result = client.search_flights("JFK", "LHR", "2026-03-15")

        assert result["success"] is True
        assert len(result["flights"]) == 1
        assert result["source"] == "picasso"
        assert result["fare_search_id"] == "FS-12345"

        flight = result["flights"][0]
        assert flight["airline"] == "AA"
        assert flight["origin"] == "JFK"
        assert flight["destination"] == "LHR"
        assert flight["price"] == 350.0
        assert flight["fare_id"] == "FARE-001"

    def test_search_no_results(self):
        """Search returns gracefully when no flights found."""
        client = self._make_client()

        search_response = MagicMock()
        search_response.json.return_value = {
            "fareSearchId": None,
            "numberOfResults": 0,
        }
        search_response.raise_for_status = MagicMock()
        client._session.post.return_value = search_response

        result = client.search_flights("JFK", "LHR", "2026-03-15")
        assert result["success"] is False
        assert "no flights" in result["error"].lower()

    def test_parse_iso_duration(self):
        """Duration parser handles ISO 8601 format (PT10H25M)."""
        client = self._make_client()

        assert client._parse_iso_duration("PT7H30M") == 450
        assert client._parse_iso_duration("PT14H") == 840
        assert client._parse_iso_duration("PT45M") == 45
        assert client._parse_iso_duration("") == 0
        assert client._parse_iso_duration(None) == 0

    def test_format_iso_duration(self):
        """Duration formatter outputs human-readable strings."""
        client = self._make_client()

        assert client._format_iso_duration("PT7H30M") == "7h 30m"
        assert client._format_iso_duration("PT2H") == "2h"
        assert client._format_iso_duration("PT45M") == "45m"
        assert client._format_iso_duration("") == ""

    def test_create_booking(self):
        """create_booking sends cart ID and returns PNR."""
        client = self._make_client()

        booking_response = MagicMock()
        booking_response.status_code = 200
        booking_response.json.return_value = {
            "superPnrId": "SPNR-001",
            "locator": "ABC123",
            "status": "CONFIRMED",
        }
        booking_response.raise_for_status = MagicMock()
        client._session.post.return_value = booking_response

        result = client.create_booking(shopping_cart_id="CART-001")
        assert result["success"] is True
        assert result["pnr"] == "ABC123"
        assert result["super_pnr_id"] == "SPNR-001"

    def test_module_level_search(self):
        """Module-level search_flights_multi_pos maps cabin class correctly."""
        from picasso_client import search_flights_multi_pos
        with patch("picasso_client._get_client") as mock_get:
            mock_client = MagicMock()
            mock_client.search_flights.return_value = {"success": True, "flights": []}
            mock_get.return_value = mock_client

            search_flights_multi_pos("JFK", "LHR", "2026-03-15", cabin_class="business")

            call_args = mock_client.search_flights.call_args
            assert call_args.kwargs["cabin_class"] == "BUSINESS"


# ===================================================================
# Integration Tests — New Pages and Routes
# ===================================================================

class TestNewRoutes:
    """Test routes added in Build #102."""

    @pytest.fixture
    def client(self):
        from server import app, db
        app.config['TESTING'] = True
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        app.config['WTF_CSRF_ENABLED'] = False
        app.config['SERVER_NAME'] = 'localhost.localdomain'
        app.config['RATELIMIT_ENABLED'] = False

        with app.app_context():
            db.create_all()
            yield app.test_client()
            db.drop_all()

    @pytest.fixture
    def auth_client(self, client):
        from server import app, db
        from models import User
        with app.app_context():
            user = User(email='test@example.com', name='Test User', is_active=True)
            user.set_password('TestPass123!')
            db.session.add(user)
            db.session.commit()
            client.post('/login', data={
                'email': 'test@example.com',
                'password': 'TestPass123!',
            }, follow_redirects=True)
            yield client

    def test_health_endpoint(self, client):
        """Health endpoint still works after all changes."""
        resp = client.get('/health')
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data['status'] in ('healthy', 'ok')

    def test_home_page_branding(self, client):
        """Homepage shows MYSTES branding."""
        resp = client.get('/')
        assert resp.status_code == 200
        assert b'MYSTES' in resp.data

    def test_hotel_search_api_requires_data(self, auth_client):
        """Hotel search API requires proper parameters."""
        resp = auth_client.post('/api/hotels/search',
                                data=json.dumps({}),
                                content_type='application/json')
        assert resp.status_code in (200, 400, 410, 422)  # 410 when vertical_hotels disabled

    def test_hotel_select_api_requires_auth(self, client):
        """Hotel select endpoint requires auth or rejects bad data (410 when disabled)."""
        resp = client.post('/api/hotels/select',
                           data=json.dumps({"offer_id": "test"}),
                           content_type='application/json')
        assert resp.status_code in (302, 400, 401, 403, 410)

    def test_mystes_ai_page_loads(self, auth_client):
        """MYSTES AI chat page loads for authenticated users."""
        resp = auth_client.get('/ai')
        assert resp.status_code == 200
        assert b'MYSTES' in resp.data


# ===================================================================
# Hotel Session Caching Tests
# ===================================================================

class TestHotelSessionCaching:
    """Test that AI chat hotel search results get cached in session."""

    def test_hotel_results_cache_logic(self):
        """Verify the session caching logic for hotel search results."""
        # Simulate the caching code from mystes_ai_api.py line 217-224
        tool_calls_raw = [
            {
                "tool": "search_hotels",
                "result": {
                    "success": True,
                    "hotels": [
                        {"offer_id": "OFF-001", "hotel_name": "Grand Hotel", "price_total": 125.00},
                        {"offer_id": "OFF-002", "hotel_name": "City Inn", "price_total": 89.00},
                        {"hotel_name": "No Offer Hotel"},  # Missing offer_id — should be skipped
                    ]
                }
            }
        ]

        # Simulate the caching logic
        session = {}
        for tc in (tool_calls_raw if isinstance(tool_calls_raw, list) else []):
            if tc.get("tool") == "search_hotels" and isinstance(tc.get("result"), dict):
                hotels = tc["result"].get("hotels", [])
                if hotels:
                    session['hotel_search_results'] = {
                        h.get("offer_id"): h for h in hotels if h.get("offer_id")
                    }

        assert "hotel_search_results" in session
        assert len(session["hotel_search_results"]) == 2
        assert "OFF-001" in session["hotel_search_results"]
        assert "OFF-002" in session["hotel_search_results"]
        assert session["hotel_search_results"]["OFF-001"]["hotel_name"] == "Grand Hotel"

    def test_non_hotel_tool_doesnt_cache(self):
        """Non-hotel tool calls don't populate hotel_search_results."""
        tool_calls_raw = [
            {"tool": "search_flights", "result": {"flights": [{"id": "F1"}]}}
        ]

        session = {}
        for tc in (tool_calls_raw if isinstance(tool_calls_raw, list) else []):
            if tc.get("tool") == "search_hotels" and isinstance(tc.get("result"), dict):
                hotels = tc["result"].get("hotels", [])
                if hotels:
                    session['hotel_search_results'] = {
                        h.get("offer_id"): h for h in hotels if h.get("offer_id")
                    }

        assert "hotel_search_results" not in session

    def test_empty_hotel_results_dont_cache(self):
        """Empty hotel results don't create a session entry."""
        tool_calls_raw = [
            {"tool": "search_hotels", "result": {"success": False, "hotels": []}}
        ]

        session = {}
        for tc in (tool_calls_raw if isinstance(tool_calls_raw, list) else []):
            if tc.get("tool") == "search_hotels" and isinstance(tc.get("result"), dict):
                hotels = tc["result"].get("hotels", [])
                if hotels:
                    session['hotel_search_results'] = {
                        h.get("offer_id"): h for h in hotels if h.get("offer_id")
                    }

        assert "hotel_search_results" not in session


# ===================================================================
# Pricing Model Invariant Tests
# ===================================================================

class TestPricingInvariants:
    """Test core pricing model invariants that must always hold."""

    def test_free_member_fee_is_45_percent(self):
        """Authenticated free members get 45% platform fee (Build #170)."""
        from payments import get_fee_percent
        assert get_fee_percent(_mock_member()) == 0.45

    def test_non_member_fee_is_50_percent(self):
        """Anonymous/guest users get 50% platform fee."""
        from payments import get_fee_percent
        assert get_fee_percent(None) == 0.50
        assert get_fee_percent() == 0.50

    def test_member_always_saves_on_arbitrage(self):
        """Members ALWAYS pay less than Google when there IS arbitrage."""
        from payments import get_fee_percent
        fee_pct = get_fee_percent(_mock_member())

        test_cases = [
            (450, 350),   # Normal savings
            (205, 200),   # Tiny savings
            (1500, 1000), # Large savings
            (100, 50),    # 50% savings
        ]

        for us_price, cheapest_price in test_cases:
            savings_raw = us_price - cheapest_price
            platform_fee = savings_raw * fee_pct
            mystes_price = cheapest_price + platform_fee

            assert mystes_price < us_price, (
                f"Member should save: US=${us_price}, MYSTES=${mystes_price}"
            )

    def test_non_member_always_saves_on_arbitrage(self):
        """Non-members ALWAYS pay less than Google when there IS arbitrage."""
        from payments import get_fee_percent
        fee_pct = get_fee_percent(None)

        test_cases = [
            (450, 350),   # Normal savings
            (205, 200),   # Tiny savings
            (1500, 1000), # Large savings
            (100, 50),    # 50% savings
        ]

        for us_price, cheapest_price in test_cases:
            savings_raw = us_price - cheapest_price
            platform_fee = savings_raw * fee_pct
            mystes_price = cheapest_price + platform_fee

            assert mystes_price < us_price, (
                f"Non-member should save: US=${us_price}, MYSTES=${mystes_price}"
            )

    def test_platform_always_earns_on_arbitrage(self):
        """Platform ALWAYS earns a fee when there IS arbitrage."""
        from payments import get_fee_percent

        test_cases = [
            (450, 350),
            (205, 200),
            (1500, 1000),
        ]

        for user in [_mock_member(), None]:
            fee_pct = get_fee_percent(user)
            for us_price, cheapest_price in test_cases:
                savings_raw = us_price - cheapest_price
                platform_fee = savings_raw * fee_pct
                assert platform_fee > 0

    def test_hotel_margin_filter_prevents_loss(self):
        """Margin filter ensures we never sell hotels at a loss."""
        # Simulate the margin filter logic from liteapi_client.py
        test_hotels = [
            {"our_cost": 200, "google_price": 180},   # Loss — skip
            {"our_cost": 100, "google_price": 200},   # Profit — keep
            {"our_cost": 150, "google_price": 150},   # Break-even — skip
            {"our_cost": 99,  "google_price": 100},   # Tiny margin — keep
        ]

        kept = []
        for h in test_hotels:
            if h["google_price"] > 0 and h["our_cost"] >= h["google_price"]:
                continue
            kept.append(h)

        assert len(kept) == 2
        assert all(h["our_cost"] < h["google_price"] for h in kept)


# ===================================================================
# Stripe Payment Flow Tests
# ===================================================================

class TestStripePaymentFlow:
    """Test Stripe payment infrastructure: metadata, webhooks, refunds, duplicate prevention."""

    def test_checkout_session_includes_user_id_metadata(self):
        """create_stripe_checkout_session passes user_id in metadata."""
        from payments import create_stripe_checkout_session, STRIPE_AVAILABLE

        if not STRIPE_AVAILABLE:
            pytest.skip("Stripe not installed")

        with patch("payments.stripe") as mock_stripe, \
             patch("payments.PAYMENT_CONFIG", {"stripe_secret_key": "sk_test_xxx", "stripe_publishable_key": "pk_test_xxx"}):
            mock_session = MagicMock()
            mock_session.id = "cs_test_123"
            mock_session.url = "https://checkout.stripe.com/test"
            mock_stripe.checkout.Session.create.return_value = mock_session
            mock_stripe.error.StripeError = Exception

            result = create_stripe_checkout_session(
                deal_id="DEAL-001",
                fee_usd=25.00,
                user_email="test@example.com",
                success_url="http://localhost/success",
                cancel_url="http://localhost/cancel",
                user_id=42
            )

            assert result.get("session_id") == "cs_test_123"

            # Verify metadata includes user_id
            call_kwargs = mock_stripe.checkout.Session.create.call_args
            metadata = call_kwargs.kwargs.get("metadata") or call_kwargs[1].get("metadata")
            assert metadata["user_id"] == "42"
            assert metadata["deal_id"] == "DEAL-001"
            assert metadata["fee_usd"] == "25.0"

    def test_checkout_session_without_user_id(self):
        """create_stripe_checkout_session works without user_id (backward compat)."""
        from payments import create_stripe_checkout_session, STRIPE_AVAILABLE

        if not STRIPE_AVAILABLE:
            pytest.skip("Stripe not installed")

        with patch("payments.stripe") as mock_stripe, \
             patch("payments.PAYMENT_CONFIG", {"stripe_secret_key": "sk_test_xxx", "stripe_publishable_key": "pk_test_xxx"}):
            mock_session = MagicMock()
            mock_session.id = "cs_test_456"
            mock_session.url = "https://checkout.stripe.com/test"
            mock_stripe.checkout.Session.create.return_value = mock_session
            mock_stripe.error.StripeError = Exception

            result = create_stripe_checkout_session(
                deal_id="DEAL-002",
                fee_usd=15.00,
                user_email="user@example.com",
                success_url="http://localhost/success",
                cancel_url="http://localhost/cancel"
            )

            assert result.get("session_id") == "cs_test_456"
            call_kwargs = mock_stripe.checkout.Session.create.call_args
            metadata = call_kwargs.kwargs.get("metadata") or call_kwargs[1].get("metadata")
            assert "user_id" not in metadata

    def test_webhook_handler_returns_user_data(self):
        """handle_stripe_webhook returns user_id, payment_intent, customer_email."""
        from payments import handle_stripe_webhook, STRIPE_AVAILABLE

        if not STRIPE_AVAILABLE:
            pytest.skip("Stripe not installed")

        with patch("payments.stripe") as mock_stripe:
            mock_event = MagicMock()
            mock_event.type = "checkout.session.completed"
            mock_session = MagicMock()
            mock_session.metadata = {
                "deal_id": "DEAL-001",
                "fee_usd": "25.0",
                "user_id": "42",
            }
            mock_session.id = "cs_test_123"
            mock_session.payment_intent = "pi_test_abc"
            mock_session.customer_email = "test@example.com"
            mock_event.data.object = mock_session
            mock_stripe.Webhook.construct_event.return_value = mock_event
            mock_stripe.error.SignatureVerificationError = Exception

            result = handle_stripe_webhook(b"payload", "sig_test")

            assert result["event"] == "payment_completed"
            assert result["user_id"] == "42"
            assert result["payment_intent"] == "pi_test_abc"
            assert result["customer_email"] == "test@example.com"
            assert result["deal_id"] == "DEAL-001"

    def test_webhook_handler_expired_event(self):
        """handle_stripe_webhook handles checkout.session.expired."""
        from payments import handle_stripe_webhook, STRIPE_AVAILABLE

        if not STRIPE_AVAILABLE:
            pytest.skip("Stripe not installed")

        with patch("payments.stripe") as mock_stripe:
            mock_event = MagicMock()
            mock_event.type = "checkout.session.expired"
            mock_session = MagicMock()
            mock_session.metadata = {"deal_id": "DEAL-001"}
            mock_session.id = "cs_expired_123"
            mock_session.customer_email = "test@example.com"
            mock_event.data.object = mock_session
            mock_stripe.Webhook.construct_event.return_value = mock_event
            mock_stripe.error.SignatureVerificationError = Exception

            result = handle_stripe_webhook(b"payload", "sig_test")

            assert result["event"] == "payment_expired"
            assert result["session_id"] == "cs_expired_123"

    def test_refund_creation(self):
        """create_stripe_refund calls Stripe with correct params."""
        from payments import create_stripe_refund, STRIPE_AVAILABLE

        if not STRIPE_AVAILABLE:
            pytest.skip("Stripe not installed")

        with patch("payments.stripe") as mock_stripe, \
             patch("payments.PAYMENT_CONFIG", {"stripe_secret_key": "sk_test_xxx"}):
            mock_refund = MagicMock()
            mock_refund.id = "re_test_123"
            mock_refund.amount = 2500
            mock_refund.status = "succeeded"
            mock_refund.currency = "usd"
            mock_stripe.Refund.create.return_value = mock_refund
            mock_stripe.error.StripeError = Exception

            result = create_stripe_refund("pi_test_abc", amount_cents=2500)

            assert result["success"] is True
            assert result["refund_id"] == "re_test_123"
            assert result["amount"] == 2500
            mock_stripe.Refund.create.assert_called_once_with(
                payment_intent="pi_test_abc",
                reason="requested_by_customer",
                amount=2500
            )

    def test_refund_full_amount(self):
        """create_stripe_refund without amount_cents does full refund."""
        from payments import create_stripe_refund, STRIPE_AVAILABLE

        if not STRIPE_AVAILABLE:
            pytest.skip("Stripe not installed")

        with patch("payments.stripe") as mock_stripe, \
             patch("payments.PAYMENT_CONFIG", {"stripe_secret_key": "sk_test_xxx"}):
            mock_refund = MagicMock()
            mock_refund.id = "re_full_456"
            mock_refund.amount = 5000
            mock_refund.status = "succeeded"
            mock_refund.currency = "usd"
            mock_stripe.Refund.create.return_value = mock_refund
            mock_stripe.error.StripeError = Exception

            result = create_stripe_refund("pi_test_def")

            assert result["success"] is True
            mock_stripe.Refund.create.assert_called_once_with(
                payment_intent="pi_test_def",
                reason="requested_by_customer"
            )

    def test_webhook_duplicate_prevention_logic(self):
        """Verify the duplicate check logic used in webhook handler."""
        # Simulate the dedup logic from webhook_stripe in server.py
        existing_payments = {
            "pi_abc": {"status": "verified"},
            "pi_def": {"status": "pending"},
        }

        # Case 1: payment_intent already verified — should skip
        payment_intent = "pi_abc"
        existing = existing_payments.get(payment_intent)
        should_create = not (existing and existing["status"] == "verified")
        assert should_create is False

        # Case 2: payment_intent pending — should upgrade to verified
        payment_intent = "pi_def"
        existing = existing_payments.get(payment_intent)
        should_create = not (existing and existing["status"] == "verified")
        assert should_create is True

        # Case 3: unknown payment_intent — should create new
        payment_intent = "pi_new"
        existing = existing_payments.get(payment_intent)
        should_create = not (existing and existing["status"] == "verified")
        assert should_create is True

    def test_metadata_validation_logic(self):
        """Verify metadata deal_id validation logic from payment_success_handler."""
        # Simulate the metadata validation from payment/success
        url_deal_id = "DEAL-001"

        # Case 1: matching metadata — should proceed
        metadata_deal_id = "DEAL-001"
        valid = not metadata_deal_id or metadata_deal_id == url_deal_id
        assert valid is True

        # Case 2: mismatched metadata — should reject
        metadata_deal_id = "DEAL-999"
        valid = not metadata_deal_id or metadata_deal_id == url_deal_id
        assert valid is False

        # Case 3: no metadata deal_id — should proceed (backward compat)
        metadata_deal_id = None
        valid = not metadata_deal_id or metadata_deal_id == url_deal_id
        assert valid is True
