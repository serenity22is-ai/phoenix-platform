"""
Comprehensive tests for AirGateway NDC API client.

Tests cover:
    Phase 1 (Core):
    - Client initialization and configuration
    - Error classification and retryable detection
    - Shopping session tracking and expiry
    - Provider validation against known airlines
    - Search request construction (POS, cabin, providers)
    - Offer parsing (segments, price, metadata)
    - Price verification with session checks
    - Booking (instant purchase + hold mode)
    - Booking response parsing (order_id, PNR, tickets, status)
    - OrderPoll for async confirmation
    - Order management (cancel, refund, reshop, seats, services)
    - Ticket issuance
    - Knowledge card JSON integrity
    - Tool definitions completeness

    Phase 2 (Production Hardening):
    - Input validation (IATA codes, dates, passenger data)
    - Retry with exponential backoff (retryable vs non-retryable)
    - Request metrics (per-endpoint latency, success/error rates)
    - Multi-POS arbitrage scanner (parallel search, dedup, savings)
    - Automated confirmation poller (await_confirmation loop)
    - Constants and configuration validation

MYSTES KYRIOS LLC — Confidential.
"""

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Import the client under test
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "clients"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from clients.airgateway import (
    ARBITRAGE_MARKETS,
    BOOKING_STATUS,
    CABIN_DISPLAY,
    CABIN_MAP,
    DEFAULT_MAX_RETRIES,
    DEFAULT_RETRY_BASE_DELAY,
    DEFAULT_RETRY_MAX_DELAY,
    ERROR_TYPES,
    KNOWN_PROVIDERS,
    PRODUCTION_BASE,
    REQUIRED_PAX_FIELDS,
    RETRYABLE_ERRORS,
    SANDBOX_BASE,
    SESSION_MAX_AGE,
    VALID_PAX_TYPES,
    VALID_TITLES,
    AirGatewayClient,
    RequestMetrics,
    ValidationError,
    validate_date,
    validate_iata,
    validate_passengers,
)


# =========================================================================
# FIXTURES
# =========================================================================

@pytest.fixture
def client():
    """Create a configured AirGateway client (sandbox)."""
    return AirGatewayClient(api_key="test_key_1234567890", sandbox=True)


@pytest.fixture
def prod_client():
    """Create a production AirGateway client."""
    return AirGatewayClient(api_key="prod_key_1234567890", sandbox=False)


@pytest.fixture
def unconfigured_client():
    """Create a client with no API key."""
    return AirGatewayClient(api_key="", sandbox=True)


@pytest.fixture
def mock_shopping_response():
    """A realistic AirGateway AirShopping response."""
    return {
        "shoppingResponseID": "sr_abc123",
        "offers": [
            {
                "offerID": "offer_001",
                "shoppingResponseID": "sr_abc123",
                "owner": "BA",
                "totalPrice": {"total": 465.50, "currency": "USD"},
                "baseFare": {"amount": 380.00},
                "tax": {"amount": 85.50},
                "cabin": "economy",
                "fareBasisCode": "YOWUS",
                "bookingClass": "Y",
                "fareType": "PUB",
                "refundable": False,
                "changeable": True,
                "segments": [
                    {
                        "flightNumber": "BA115",
                        "origin": "JFK",
                        "destination": "LHR",
                        "departureTime": "2026-04-15T19:00:00",
                        "arrivalTime": "2026-04-16T07:00:00",
                        "operatingCarrier": "BA",
                        "marketingCarrier": "BA",
                        "cabin": "economy",
                        "aircraft": "777",
                        "duration": "PT7H",
                    }
                ],
            },
            {
                "offerID": "offer_002",
                "owner": "AA",
                "totalPrice": 512.00,
                "segments": [
                    {
                        "flightNumber": "AA100",
                        "origin": "JFK",
                        "destination": "LHR",
                        "departureTime": "2026-04-15T21:00:00",
                        "arrivalTime": "2026-04-16T09:05:00",
                        "operatingCarrier": "AA",
                        "cabin": "economy",
                    },
                ],
            },
            {
                "offerID": "offer_003",
                "owner": "LH",
                "totalPrice": 890.00,
                "cabin": "business",
                "segments": [
                    {
                        "flightNumber": "LH401",
                        "origin": "JFK",
                        "destination": "FRA",
                        "departureTime": "2026-04-15T17:30:00",
                        "arrivalTime": "2026-04-16T07:20:00",
                        "operatingCarrier": "LH",
                    },
                    {
                        "flightNumber": "LH920",
                        "origin": "FRA",
                        "destination": "LHR",
                        "departureTime": "2026-04-16T09:00:00",
                        "arrivalTime": "2026-04-16T09:45:00",
                        "operatingCarrier": "LH",
                    },
                ],
            },
        ],
    }


@pytest.fixture
def mock_booking_response():
    """A realistic AirGateway OrderCreate response."""
    return {
        "id": "ord_xyz789",
        "bookingReference": "ABC123",
        "airlinePNR": "XYZ789",
        "status": "Confirmed",
        "owner": "BA",
        "totalPrice": {"total": 465.50, "currency": "USD"},
        "tickets": [
            {
                "ticketNumber": "125-1234567890",
                "travelerReference": "T1",
                "status": "issued",
            }
        ],
        "passengers": [
            {
                "nameGiven": "John",
                "surname": "Doe",
                "travelerReference": "T1",
                "passengerType": "ADT",
            }
        ],
        "payment": {"status": "settled"},
        "createdAt": "2026-04-15T10:30:00Z",
    }


@pytest.fixture
def mock_hold_response():
    """A realistic AirGateway hold booking response."""
    return {
        "id": "ord_hold_001",
        "bookingReference": "HOLD99",
        "status": "pending",
        "owner": "LH",
        "totalPrice": {"total": 890.00, "currency": "USD"},
        "tickets": [],
        "passengers": [],
        "payment": {"status": "pending", "paymentMode": "hold"},
        "holdExpiry": "2026-04-18T10:30:00Z",
        "createdAt": "2026-04-15T10:30:00Z",
    }


# =========================================================================
# INITIALIZATION TESTS
# =========================================================================

class TestClientInit:
    """Test client initialization and configuration."""

    def test_sandbox_url(self, client):
        assert client._base_url == SANDBOX_BASE

    def test_production_url(self, prod_client):
        assert prod_client._base_url == PRODUCTION_BASE

    def test_api_key_stored(self, client):
        assert client._key == "test_key_1234567890"

    def test_is_configured_with_key(self, client):
        assert client.is_configured() is True

    def test_is_configured_without_key(self, unconfigured_client):
        assert unconfigured_client.is_configured() is False

    def test_is_configured_short_key(self):
        c = AirGatewayClient(api_key="short")
        assert c.is_configured() is False

    def test_session_headers(self, client):
        headers = client._session.headers
        assert headers["Authorization"] == "test_key_1234567890"
        assert headers["Content-Type"] == "application/json"
        assert headers["AG-Consumer"] == "MYSTES"

    def test_session_tracking_initialized(self, client):
        assert isinstance(client._shopping_sessions, dict)
        assert len(client._shopping_sessions) == 0

    def test_env_var_fallback(self):
        with patch.dict(os.environ, {"AIRGATEWAY_API_KEY": "env_key_12345"}):
            c = AirGatewayClient()
            assert c._key == "env_key_12345"


# =========================================================================
# ERROR CLASSIFICATION TESTS
# =========================================================================

class TestErrorClassification:
    """Test HTTP error classification and retryable detection."""

    def test_all_error_types_mapped(self):
        """Every HTTP error status has a classification."""
        for status in [400, 401, 403, 404, 409, 422, 429, 500, 502, 503, 504]:
            assert status in ERROR_TYPES
            assert isinstance(ERROR_TYPES[status], str)

    def test_retryable_errors_subset(self):
        """Retryable errors are a subset of all error types."""
        all_types = set(ERROR_TYPES.values())
        assert RETRYABLE_ERRORS.issubset(all_types | {"timeout", "connection_error"})

    def test_429_is_retryable(self):
        assert ERROR_TYPES[429] in RETRYABLE_ERRORS

    def test_502_is_retryable(self):
        assert ERROR_TYPES[502] in RETRYABLE_ERRORS

    def test_503_is_retryable(self):
        assert ERROR_TYPES[503] in RETRYABLE_ERRORS

    def test_504_is_retryable(self):
        assert ERROR_TYPES[504] in RETRYABLE_ERRORS

    def test_401_is_not_retryable(self):
        assert ERROR_TYPES[401] not in RETRYABLE_ERRORS

    def test_400_is_not_retryable(self):
        assert ERROR_TYPES[400] not in RETRYABLE_ERRORS

    def test_409_is_not_retryable(self):
        assert ERROR_TYPES[409] not in RETRYABLE_ERRORS

    @patch("clients.airgateway.requests.Session")
    def test_error_response_includes_type(self, mock_session_cls, client):
        """Error responses include error_type and retryable fields."""
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_resp.text = "Rate limited"
        client._session.post = MagicMock(return_value=mock_resp)

        result = client._request("test", {})

        assert result["success"] is False
        assert result["error_type"] == "rate_limited"
        assert result["retryable"] is True
        assert result["status"] == 429

    @patch("clients.airgateway.requests.Session")
    def test_timeout_classified(self, mock_session_cls, client):
        """Timeouts are classified as retryable."""
        import requests as req
        client._session.post = MagicMock(side_effect=req.exceptions.Timeout("timed out"))

        result = client._request("test", {})

        assert result["success"] is False
        assert result["error_type"] == "timeout"
        assert result["retryable"] is True

    @patch("clients.airgateway.requests.Session")
    def test_connection_error_classified(self, mock_session_cls, client):
        """Connection errors are classified as retryable."""
        import requests as req
        client._session.post = MagicMock(side_effect=req.exceptions.ConnectionError("refused"))

        result = client._request("test", {})

        assert result["success"] is False
        assert result["error_type"] == "connection_error"
        assert result["retryable"] is True

    @patch("clients.airgateway.requests.Session")
    def test_unknown_error_not_retryable(self, mock_session_cls, client):
        """Generic exceptions are not retryable."""
        client._session.post = MagicMock(side_effect=ValueError("bad"))

        result = client._request("test", {})

        assert result["success"] is False
        assert result["error_type"] == "client_error"
        assert result["retryable"] is False


# =========================================================================
# SESSION TRACKING TESTS
# =========================================================================

class TestSessionTracking:
    """Test shopping session expiry tracking."""

    def test_track_session(self, client):
        client._track_session("session_001")
        assert "session_001" in client._shopping_sessions
        assert isinstance(client._shopping_sessions["session_001"], float)

    def test_valid_session(self, client):
        client._track_session("fresh_session")
        assert client.is_session_valid("fresh_session") is True

    def test_expired_session(self, client):
        client._shopping_sessions["old_session"] = time.time() - SESSION_MAX_AGE - 1
        assert client.is_session_valid("old_session") is False

    def test_unknown_session_assumed_valid(self, client):
        assert client.is_session_valid("unknown_session") is True

    def test_empty_session_id_invalid(self, client):
        assert client.is_session_valid("") is False

    def test_session_age_known(self, client):
        client._shopping_sessions["aged_session"] = time.time() - 300
        age = client.get_session_age("aged_session")
        assert age is not None
        assert 299 <= age <= 302

    def test_session_age_unknown(self, client):
        assert client.get_session_age("nonexistent") is None

    def test_session_tracked_on_search(self, client, mock_shopping_response):
        """Search results track the session automatically."""
        with patch.object(client, "_request", return_value={
            "success": True, "data": mock_shopping_response,
        }):
            result = client.search_flights("JFK", "LHR", "2026-04-15")
            assert result["success"]
            assert "sr_abc123" in client._shopping_sessions


# =========================================================================
# PROVIDER VALIDATION TESTS
# =========================================================================

class TestProviderValidation:
    """Test airline provider validation."""

    def test_wildcard_passthrough(self, client):
        validated, unknown = client.validate_providers("*")
        assert validated == "*"
        assert unknown == []

    def test_known_providers(self, client):
        validated, unknown = client.validate_providers("BA,LH,AF")
        assert validated == "BA,LH,AF"
        assert unknown == []

    def test_unknown_providers_warned(self, client):
        validated, unknown = client.validate_providers("BA,ZZ,XX")
        assert validated == "BA,ZZ,XX"
        assert "ZZ" in unknown
        assert "XX" in unknown

    def test_case_normalization(self, client):
        validated, unknown = client.validate_providers("ba,lh")
        assert validated == "BA,LH"

    def test_whitespace_handling(self, client):
        validated, unknown = client.validate_providers("BA , LH , AF")
        assert validated == "BA,LH,AF"

    def test_known_providers_set_complete(self):
        """All 12 confirmed NDC-direct airlines are in the set."""
        expected = {"A3", "AA", "AF", "AV", "AY", "BA", "EK", "IB", "KL", "LH", "QF", "SQ"}
        assert KNOWN_PROVIDERS == expected

    def test_providers_validated_on_search(self, client, mock_shopping_response):
        """Search validates providers before making request."""
        with patch.object(client, "_request", return_value={
            "success": True, "data": mock_shopping_response,
        }) as mock_req:
            client.search_flights("JFK", "LHR", "2026-04-15", providers="BA,LH")
            call_args = mock_req.call_args
            headers = call_args[1].get("extra_headers", call_args[0][2] if len(call_args[0]) > 2 else {})
            assert headers.get("AG-Providers") == "BA,LH"


# =========================================================================
# CABIN MAP TESTS
# =========================================================================

class TestCabinMaps:
    """Test cabin class mapping."""

    def test_economy_maps(self):
        assert CABIN_MAP["economy"] == "7"
        assert CABIN_MAP["ECONOMY"] == "7"

    def test_premium_economy_maps(self):
        assert CABIN_MAP["premium_economy"] == "4"

    def test_business_maps(self):
        assert CABIN_MAP["business"] == "2"

    def test_first_maps(self):
        assert CABIN_MAP["first"] == "1"

    def test_display_map_reverse(self):
        for code, name in CABIN_DISPLAY.items():
            assert CABIN_MAP[name] == code


# =========================================================================
# SEARCH TESTS
# =========================================================================

class TestSearch:
    """Test flight search construction and parsing."""

    def test_search_one_way(self, client, mock_shopping_response):
        with patch.object(client, "_request", return_value={
            "success": True, "data": mock_shopping_response,
        }) as mock_req:
            result = client.search_flights("JFK", "LHR", "2026-04-15")

            assert result["success"]
            assert result["source"] == "airgateway_ndc"
            assert result["pos_country"] == "US"
            assert result["shopping_response_id"] == "sr_abc123"
            assert result["total_results"] == 3

            # Check request body
            body = mock_req.call_args[0][1]
            assert len(body["originDestinations"]) == 1
            assert body["originDestinations"][0]["departure"]["airportCode"] == "JFK"
            assert body["metadata"]["country"] == "US"

    def test_search_round_trip(self, client, mock_shopping_response):
        with patch.object(client, "_request", return_value={
            "success": True, "data": mock_shopping_response,
        }) as mock_req:
            client.search_flights("JFK", "LHR", "2026-04-15", return_date="2026-04-22")

            body = mock_req.call_args[0][1]
            assert len(body["originDestinations"]) == 2
            assert body["originDestinations"][1]["departure"]["airportCode"] == "LHR"

    def test_search_pos_arbitrage(self, client, mock_shopping_response):
        with patch.object(client, "_request", return_value={
            "success": True, "data": mock_shopping_response,
        }) as mock_req:
            result = client.search_flights("JFK", "LHR", "2026-04-15", country="DK")

            body = mock_req.call_args[0][1]
            assert body["metadata"]["country"] == "DK"
            assert result["pos_country"] == "DK"

    def test_search_cabin_class(self, client, mock_shopping_response):
        with patch.object(client, "_request", return_value={
            "success": True, "data": mock_shopping_response,
        }) as mock_req:
            client.search_flights("JFK", "LHR", "2026-04-15", cabin_class="business")

            body = mock_req.call_args[0][1]
            assert body["preferences"]["cabin"] == ["2"]

    def test_search_nonstop(self, client, mock_shopping_response):
        with patch.object(client, "_request", return_value={
            "success": True, "data": mock_shopping_response,
        }) as mock_req:
            client.search_flights("JFK", "LHR", "2026-04-15", nonstop=True)

            body = mock_req.call_args[0][1]
            assert body["preferences"]["nonStop"] is True

    def test_search_passengers(self, client, mock_shopping_response):
        with patch.object(client, "_request", return_value={
            "success": True, "data": mock_shopping_response,
        }) as mock_req:
            client.search_flights("JFK", "LHR", "2026-04-15", adults=2, children=1, infants=1)

            body = mock_req.call_args[0][1]
            assert body["travelers"]["adt"] == 2
            assert body["travelers"]["chd"] == 1
            assert body["travelers"]["inf"] == 1

    def test_search_failure_passthrough(self, client):
        with patch.object(client, "_request", return_value={
            "success": False, "error": "API error", "error_type": "server_error",
        }):
            result = client.search_flights("JFK", "LHR", "2026-04-15")
            assert result["success"] is False
            assert "error" in result


# =========================================================================
# OFFER PARSING TESTS
# =========================================================================

class TestOfferParsing:
    """Test parsing of AirGateway offers into normalized dicts."""

    def test_parse_nonstop_offer(self, client):
        offer = {
            "offerID": "off_001",
            "owner": "BA",
            "totalPrice": {"total": 465.50, "currency": "USD"},
            "baseFare": {"amount": 380},
            "tax": {"amount": 85.50},
            "cabin": "economy",
            "fareType": "PUB",
            "refundable": False,
            "segments": [{
                "flightNumber": "BA115",
                "origin": "JFK",
                "destination": "LHR",
                "departureTime": "2026-04-15T19:00:00",
                "arrivalTime": "2026-04-16T07:00:00",
                "operatingCarrier": "BA",
                "cabin": "economy",
            }],
        }
        result = client._parse_offer(offer)

        assert result["offer_id"] == "off_001"
        assert result["airline"] == "BA"
        assert result["origin"] == "JFK"
        assert result["destination"] == "LHR"
        assert result["stops"] == 0
        assert result["price"] == "465.5"
        assert result["base_fare"] == "380"
        assert result["tax"] == "85.5"
        assert result["source"] == "airgateway_ndc"
        assert result["fare_type"] == "PUB"
        assert result["refundable"] is False

    def test_parse_connecting_offer(self, client):
        offer = {
            "offerID": "off_002",
            "owner": "LH",
            "totalPrice": 890.00,
            "segments": [
                {"flightNumber": "LH401", "origin": "JFK", "destination": "FRA",
                 "departureTime": "T17:30", "arrivalTime": "T07:20",
                 "operatingCarrier": "LH"},
                {"flightNumber": "LH920", "origin": "FRA", "destination": "LHR",
                 "departureTime": "T09:00", "arrivalTime": "T09:45",
                 "operatingCarrier": "LH"},
            ],
        }
        result = client._parse_offer(offer)

        assert result["stops"] == 1
        assert result["origin"] == "JFK"
        assert result["destination"] == "LHR"
        assert len(result["segments"]) == 2
        assert result["segments"][0]["flight_number"] == "LH401"
        assert result["segments"][1]["flight_number"] == "LH920"

    def test_parse_price_as_dict(self, client):
        offer = {
            "offerID": "off_003",
            "owner": "AA",
            "totalPrice": {"total": 512.00, "currency": "USD"},
            "segments": [{"origin": "JFK", "destination": "LHR",
                          "departureTime": "T21:00", "arrivalTime": "T09:00"}],
        }
        result = client._parse_offer(offer)
        assert result["price"] == "512.0"

    def test_parse_price_as_number(self, client):
        offer = {
            "offerID": "off_004",
            "owner": "AF",
            "totalPrice": 399.99,
            "segments": [{"origin": "JFK", "destination": "CDG",
                          "departureTime": "T22:00", "arrivalTime": "T11:00"}],
        }
        result = client._parse_offer(offer)
        assert result["price"] == "399.99"

    def test_parse_no_segments_returns_none(self, client):
        offer = {"offerID": "off_empty", "owner": "XX", "totalPrice": 100}
        assert client._parse_offer(offer) is None

    def test_parse_empty_segments_returns_none(self, client):
        offer = {"offerID": "off_empty2", "owner": "XX", "totalPrice": 100, "segments": []}
        assert client._parse_offer(offer) is None

    def test_parse_alternative_field_names(self, client):
        """Handles alternative field naming (departureAirport vs origin)."""
        offer = {
            "id": "alt_001",
            "airline": "SQ",
            "price": 1200,
            "itinerary": [{
                "flightNumber": "SQ25",
                "departureAirport": "SIN",
                "arrivalAirport": "LHR",
                "departure": "2026-04-15T01:00:00",
                "arrival": "2026-04-15T07:30:00",
                "airline": "SQ",
            }],
        }
        result = client._parse_offer(offer)

        assert result["offer_id"] == "alt_001"
        assert result["airline"] == "SQ"
        assert result["origin"] == "SIN"
        assert result["destination"] == "LHR"
        assert result["price"] == "1200"

    def test_parse_shopping_response_multiple(self, client, mock_shopping_response):
        flights = client._parse_shopping_response(mock_shopping_response)
        assert len(flights) == 3
        airlines = {f["airline"] for f in flights}
        assert airlines == {"BA", "AA", "LH"}


# =========================================================================
# PRICE VERIFICATION TESTS
# =========================================================================

class TestPriceVerification:
    """Test OfferPrice / price verification."""

    def test_verify_checks_session(self, client):
        client._shopping_sessions["expired"] = time.time() - SESSION_MAX_AGE - 100
        result = client.verify_price("expired", ["offer_001"])
        assert result["success"] is False
        assert result["error_type"] == "session_expired"

    def test_verify_valid_session(self, client):
        client._track_session("valid_session")
        with patch.object(client, "_request", return_value={
            "success": True,
            "data": {"offer": {"totalPrice": {"total": 465.50, "currency": "USD"}}},
        }):
            result = client.verify_price("valid_session", ["offer_001"])
            assert result["success"]
            assert "verified_price" in result
            assert result["verified_price"]["total"] == 465.50

    def test_verify_failure_passthrough(self, client):
        client._track_session("sess")
        with patch.object(client, "_request", return_value={
            "success": False, "error": "409 Conflict", "error_type": "conflict",
        }):
            result = client.verify_price("sess", ["offer_001"])
            assert result["success"] is False


# =========================================================================
# BOOKING TESTS
# =========================================================================

class TestBooking:
    """Test OrderCreate with instant purchase and hold modes."""

    @pytest.fixture
    def passengers(self):
        return [{
            "nameGiven": "John",
            "surname": "Doe",
            "nameTitle": "MR",
            "gender": "Male",
            "birthdate": "1990-01-15",
            "passengerType": "ADT",
            "emailContact": "john@example.com",
            "phone": "+12125551234",
            "travelerReference": "T1",
        }]

    def test_instant_booking(self, client, passengers, mock_booking_response):
        client._track_session("book_sess")
        with patch.object(client, "_request", return_value={
            "success": True, "data": mock_booking_response,
        }) as mock_req:
            result = client.create_order("book_sess", passengers)

            assert result["success"]
            assert "booking" in result
            booking = result["booking"]
            assert booking["order_id"] == "ord_xyz789"
            assert booking["pnr"] == "ABC123"
            assert booking["airline_pnr"] == "XYZ789"
            assert booking["status"] == "confirmed"
            assert booking["owner"] == "BA"
            assert len(booking["tickets"]) == 1
            assert booking["tickets"][0]["ticket_number"] == "125-1234567890"

            # Verify body does NOT have hold mode
            body = mock_req.call_args[0][1]
            assert "paymentMode" not in body.get("payment", {})

    def test_hold_booking(self, client, passengers, mock_hold_response):
        client._track_session("hold_sess")
        with patch.object(client, "_request", return_value={
            "success": True, "data": mock_hold_response,
        }) as mock_req:
            result = client.create_order("hold_sess", passengers, hold_mode=True)

            assert result["success"]
            booking = result["booking"]
            assert booking["order_id"] == "ord_hold_001"
            assert booking["status"] == "pending"
            assert booking["hold_expiry"] == "2026-04-18T10:30:00Z"

            # Verify body has hold mode
            body = mock_req.call_args[0][1]
            assert body["payment"]["paymentMode"] == "hold"

    def test_fake_ticket_mode(self, client, passengers, mock_booking_response):
        client._track_session("fake_sess")
        with patch.object(client, "_request", return_value={
            "success": True, "data": mock_booking_response,
        }) as mock_req:
            client.create_order("fake_sess", passengers, fake_ticket=True)

            body = mock_req.call_args[0][1]
            assert body["payment"]["fakeTicket"] is True

    def test_booking_session_expired(self, client, passengers):
        client._shopping_sessions["expired"] = time.time() - SESSION_MAX_AGE - 1
        result = client.create_order("expired", passengers)
        assert result["success"] is False
        assert result["error_type"] == "session_expired"

    def test_booking_payment_methods(self, client, passengers, mock_booking_response):
        """All three payment methods are passed correctly."""
        for method in ["cash", "card", "ms"]:
            client._track_session(f"pm_{method}")
            with patch.object(client, "_request", return_value={
                "success": True, "data": mock_booking_response,
            }) as mock_req:
                client.create_order(f"pm_{method}", passengers, payment_method=method)
                headers = mock_req.call_args.kwargs.get("extra_headers", {})
                assert headers["NDC-Payment-Method"] == method


# =========================================================================
# BOOKING RESPONSE PARSING TESTS
# =========================================================================

class TestBookingResponseParsing:
    """Test extraction of booking details from API responses."""

    def test_parse_full_response(self, client, mock_booking_response):
        booking = client._parse_booking_response(mock_booking_response)

        assert booking["order_id"] == "ord_xyz789"
        assert booking["pnr"] == "ABC123"
        assert booking["airline_pnr"] == "XYZ789"
        assert booking["status"] == "confirmed"
        assert booking["owner"] == "BA"
        assert booking["total_price"] == 465.50
        assert booking["currency"] == "USD"
        assert booking["payment_status"] == "settled"
        assert booking["created_at"] == "2026-04-15T10:30:00Z"

    def test_parse_tickets(self, client, mock_booking_response):
        booking = client._parse_booking_response(mock_booking_response)

        assert len(booking["tickets"]) == 1
        assert booking["tickets"][0]["ticket_number"] == "125-1234567890"
        assert booking["tickets"][0]["passenger_ref"] == "T1"
        assert booking["tickets"][0]["status"] == "issued"

    def test_parse_passengers(self, client, mock_booking_response):
        booking = client._parse_booking_response(mock_booking_response)

        assert len(booking["passengers"]) == 1
        assert booking["passengers"][0]["name"] == "John Doe"
        assert booking["passengers"][0]["reference"] == "T1"
        assert booking["passengers"][0]["type"] == "ADT"

    def test_parse_hold_response(self, client, mock_hold_response):
        booking = client._parse_booking_response(mock_hold_response)

        assert booking["status"] == "pending"
        assert booking["hold_expiry"] == "2026-04-18T10:30:00Z"
        assert len(booking["tickets"]) == 0

    def test_parse_nested_order_response(self, client):
        """Handle responses with nested 'order' object."""
        data = {
            "order": {
                "id": "nested_001",
                "bookingReference": "NEST99",
                "airlinePNR": "APNR99",
                "status": "ticketed",
                "owner": "AF",
                "totalPrice": {"total": 600, "currency": "EUR"},
                "tickets": [{"ticketNumber": "057-999", "travelerReference": "T1"}],
                "passengers": [{"nameGiven": "Jane", "surname": "Smith",
                                "travelerReference": "T1", "passengerType": "ADT"}],
                "payment": {"status": "settled"},
                "createdAt": "2026-04-15T12:00:00Z",
            }
        }
        booking = client._parse_booking_response(data)

        assert booking["order_id"] == "nested_001"
        assert booking["pnr"] == "NEST99"
        assert booking["airline_pnr"] == "APNR99"
        assert booking["status"] == "ticketed"
        assert booking["owner"] == "AF"

    def test_parse_ticket_as_string(self, client):
        """Handle tickets as simple string list."""
        data = {
            "id": "str_tkt_001",
            "status": "ticketed",
            "tickets": ["125-1111111111", "125-2222222222"],
        }
        booking = client._parse_booking_response(data)

        assert len(booking["tickets"]) == 2
        assert booking["tickets"][0]["ticket_number"] == "125-1111111111"

    def test_parse_minimal_response(self, client):
        """Handle minimal response (just order_id)."""
        data = {"id": "min_001"}
        booking = client._parse_booking_response(data)

        assert booking["order_id"] == "min_001"
        assert booking["status"] == "pending"
        assert len(booking["tickets"]) == 0

    def test_status_normalized_lowercase(self, client):
        """Status is always lowercased."""
        data = {"id": "case_001", "status": "CONFIRMED"}
        booking = client._parse_booking_response(data)
        assert booking["status"] == "confirmed"


# =========================================================================
# ORDER POLL TESTS
# =========================================================================

class TestOrderPoll:
    """Test async booking confirmation polling."""

    def test_poll_returns_booking(self, client, mock_booking_response):
        with patch.object(client, "_request", return_value={
            "success": True, "data": mock_booking_response,
        }):
            result = client.poll_order("ord_xyz789")

            assert result["success"]
            assert "booking" in result
            assert result["booking"]["order_id"] == "ord_xyz789"

    def test_poll_sends_correct_method(self, client, mock_booking_response):
        with patch.object(client, "_request", return_value={
            "success": True, "data": mock_booking_response,
        }) as mock_req:
            client.poll_order("ord_001", owner="BA")

            body = mock_req.call_args[0][1]
            assert body["id"] == "ord_001"
            assert body["owner"] == "BA"
            headers = mock_req.call_args.kwargs.get("extra_headers", {})
            assert headers["NDC-Method"] == "OrderPoll"


# =========================================================================
# ORDER MANAGEMENT TESTS
# =========================================================================

class TestOrderManagement:
    """Test order retrieval, cancellation, and post-booking ops."""

    def test_retrieve_order_parses_booking(self, client, mock_booking_response):
        with patch.object(client, "_request", return_value={
            "success": True, "data": mock_booking_response,
        }):
            result = client.retrieve_order("ord_xyz789")
            assert result["success"]
            assert "booking" in result
            assert result["booking"]["pnr"] == "ABC123"

    def test_cancel_void(self, client):
        with patch.object(client, "_request", return_value={
            "success": True, "data": {"status": "voided"},
        }) as mock_req:
            result = client.cancel_order("ord_001", cancel_type="void")
            assert result["success"]
            body = mock_req.call_args[0][1]
            assert body["type"] == "void"

    def test_cancel_with_refund(self, client):
        with patch.object(client, "_request", return_value={
            "success": True, "data": {"status": "cancelled"},
        }) as mock_req:
            result = client.cancel_order("ord_001", cancel_type="cancel")
            body = mock_req.call_args[0][1]
            assert body["type"] == "cancel"

    def test_reshop_refund(self, client):
        with patch.object(client, "_request", return_value={
            "success": True, "data": {"refundAmount": 420.00},
        }) as mock_req:
            result = client.reshop_refund("ord_001")
            assert result["success"]
            headers = mock_req.call_args.kwargs.get("extra_headers", {})
            assert headers["NDC-Method"] == "OrderReshopRefund"

    def test_reshop_reprice(self, client):
        with patch.object(client, "_request", return_value={
            "success": True, "data": {"priceDifference": 50.00},
        }) as mock_req:
            result = client.reshop_reprice("ord_001")
            assert result["success"]
            headers = mock_req.call_args.kwargs.get("extra_headers", {})
            assert headers["NDC-Method"] == "OrderReshopReprice"

    def test_seat_availability(self, client):
        with patch.object(client, "_request", return_value={
            "success": True, "data": {"seats": []},
        }) as mock_req:
            result = client.get_seat_availability("ord_001")
            assert result["success"]
            headers = mock_req.call_args.kwargs.get("extra_headers", {})
            assert headers["NDC-Method"] == "SeatAvailability"

    def test_service_list(self, client):
        with patch.object(client, "_request", return_value={
            "success": True, "data": {"services": []},
        }) as mock_req:
            result = client.get_service_list("ord_001")
            assert result["success"]
            headers = mock_req.call_args.kwargs.get("extra_headers", {})
            assert headers["NDC-Method"] == "ServiceList"


# =========================================================================
# TICKET ISSUANCE TESTS
# =========================================================================

class TestTicketIssuance:
    """Test AirDocIssue ticket issuance."""

    def test_issue_ticket(self, client, mock_booking_response):
        with patch.object(client, "_request", return_value={
            "success": True, "data": mock_booking_response,
        }) as mock_req:
            result = client.issue_ticket("ord_001")

            assert result["success"]
            assert "booking" in result
            assert result["booking"]["tickets"][0]["ticket_number"] == "125-1234567890"

            headers = mock_req.call_args.kwargs.get("extra_headers", {})
            assert headers["NDC-Method"] == "AirDocIssue"

    def test_issue_ticket_failure(self, client):
        with patch.object(client, "_request", return_value={
            "success": False, "error": "Ticketing failed", "error_type": "server_error",
        }):
            result = client.issue_ticket("ord_001")
            assert result["success"] is False
            assert "booking" not in result


# =========================================================================
# KNOWLEDGE CARD JSON TESTS
# =========================================================================

class TestKnowledgeCard:
    """Test the airgateway_ndc.json knowledge card integrity."""

    @pytest.fixture
    def card(self):
        card_path = Path(__file__).parent.parent / "anastasia" / "modules" / "cards" / "airgateway_ndc.json"
        with open(card_path) as f:
            return json.load(f)

    def test_card_loads(self, card):
        assert card["module_id"] == "airgateway_ndc"

    def test_change_supported(self, card):
        """change capability must be true (via OrderReshop workflow)."""
        assert card["capabilities"]["change"] is True

    def test_fare_rules_supported(self, card):
        """fare_rules must be true (via OrderReshopRefund)."""
        assert card["capabilities"]["fare_rules"] is True

    def test_hold_supported(self, card):
        """hold capability must be true."""
        assert card["capabilities"]["hold"] is True

    def test_ticket_issuance_supported(self, card):
        """ticket_issuance must be true (AirDocIssue)."""
        assert card["capabilities"]["ticket_issuance"] is True

    def test_async_confirmation_supported(self, card):
        """async_confirmation must be true (OrderPoll)."""
        assert card["capabilities"]["async_confirmation"] is True

    def test_pos_arbitrage_supported(self, card):
        assert card["capabilities"]["pos_arbitrage"] is True

    def test_no_virtual_interlining(self, card):
        assert card["capabilities"]["virtual_interlining"] is False

    def test_tool_count(self, card):
        """11 tools should be listed."""
        assert card["tool_count"] == 11
        assert len(card["tools"]) == 11

    def test_ndc_operations(self, card):
        """All 11 NDC operations documented."""
        assert len(card["ndc_operations"]) == 11
        assert "OrderPoll" in card["ndc_operations"]
        assert "AirDocIssue" in card["ndc_operations"]

    def test_session_ttl(self, card):
        assert card["session_ttl_seconds"] == 1800

    def test_readiness_production(self, card):
        assert card["readiness"] == "production"

    def test_confidence_high(self, card):
        assert card["confidence"] >= 0.90

    def test_weaknesses_accurate(self, card):
        """Weaknesses should NOT include false claims."""
        weaknesses = card["weaknesses"]
        # These were corrected — should NOT be in weaknesses
        assert "no_change_support" not in weaknesses
        assert "no_fare_rules_api" not in weaknesses

    def test_booking_steps_complete(self, card):
        steps = card["booking_steps"]
        assert "search" in steps
        assert "verify_price" in steps
        assert "create_order" in steps
        assert "poll_order" in steps
        assert "issue_ticket" in steps


# =========================================================================
# TOOL DEFINITIONS TESTS
# =========================================================================

class TestToolDefinitions:
    """Test the tool definitions file for completeness."""

    @pytest.fixture
    def tools(self):
        # Import tool definitions
        tools_path = Path(__file__).parent.parent / "picasso" / "agent" / "airgateway_tools.py"
        import importlib.util
        spec = importlib.util.spec_from_file_location("airgateway_tools", tools_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.AIRGATEWAY_TOOL_DEFINITIONS

    def test_eleven_tools_defined(self, tools):
        assert len(tools) == 11

    def test_all_tool_names_prefixed(self, tools):
        for tool in tools:
            assert tool["name"].startswith("agw_"), f"Tool {tool['name']} missing agw_ prefix"

    def test_required_tools_present(self, tools):
        names = {t["name"] for t in tools}
        required = {
            "agw_search_flights", "agw_verify_price", "agw_create_order",
            "agw_retrieve_order", "agw_cancel_order", "agw_poll_order",
            "agw_issue_ticket", "agw_get_seats", "agw_get_services",
            "agw_reshop_refund", "agw_reshop_reprice",
        }
        assert required == names

    def test_create_order_has_hold_mode(self, tools):
        create_tool = next(t for t in tools if t["name"] == "agw_create_order")
        props = create_tool["input_schema"]["properties"]
        assert "hold_mode" in props
        assert props["hold_mode"]["type"] == "boolean"

    def test_create_order_has_fake_ticket(self, tools):
        create_tool = next(t for t in tools if t["name"] == "agw_create_order")
        props = create_tool["input_schema"]["properties"]
        assert "fake_ticket" in props

    def test_search_has_country(self, tools):
        search_tool = next(t for t in tools if t["name"] == "agw_search_flights")
        props = search_tool["input_schema"]["properties"]
        assert "country" in props

    def test_all_tools_have_required_fields(self, tools):
        for tool in tools:
            assert "name" in tool
            assert "description" in tool
            assert "input_schema" in tool
            assert tool["input_schema"]["type"] == "object"
            assert "properties" in tool["input_schema"]
            assert "required" in tool["input_schema"]


# =========================================================================
# BOOKING STATUS TESTS
# =========================================================================

class TestBookingStatus:
    """Test booking status constants."""

    def test_all_statuses_defined(self):
        expected = {"pending", "confirmed", "ticketed", "failed", "cancelled", "voided"}
        assert set(BOOKING_STATUS.keys()) == expected

    def test_all_statuses_have_descriptions(self):
        for status, desc in BOOKING_STATUS.items():
            assert isinstance(desc, str)
            assert len(desc) > 10


# =========================================================================
# PHASE 2: INPUT VALIDATION TESTS
# =========================================================================

class TestValidateIata:
    """Test IATA airport code validation."""

    def test_valid_code(self):
        assert validate_iata("JFK") == "JFK"

    def test_valid_code_lowercase(self):
        assert validate_iata("jfk") == "JFK"

    def test_valid_code_mixed_case(self):
        assert validate_iata("Lhr") == "LHR"

    def test_valid_code_with_whitespace(self):
        assert validate_iata("  jfk  ") == "JFK"

    def test_empty_string_raises(self):
        with pytest.raises(ValidationError, match="IATA code is required"):
            validate_iata("")

    def test_none_raises(self):
        with pytest.raises(ValidationError, match="IATA code is required"):
            validate_iata(None)

    def test_too_short_raises(self):
        with pytest.raises(ValidationError, match="not a valid IATA code"):
            validate_iata("JF")

    def test_too_long_raises(self):
        with pytest.raises(ValidationError, match="not a valid IATA code"):
            validate_iata("JFKK")

    def test_numeric_raises(self):
        with pytest.raises(ValidationError, match="not a valid IATA code"):
            validate_iata("123")

    def test_mixed_alphanumeric_raises(self):
        with pytest.raises(ValidationError, match="not a valid IATA code"):
            validate_iata("JF1")

    def test_custom_field_name_in_error(self):
        with pytest.raises(ValidationError, match="origin"):
            validate_iata("", "origin")

    def test_non_string_raises(self):
        with pytest.raises(ValidationError, match="IATA code is required"):
            validate_iata(123)


class TestValidateDate:
    """Test date string validation."""

    def test_valid_date(self):
        assert validate_date("2026-04-15") == "2026-04-15"

    def test_valid_leap_day(self):
        assert validate_date("2024-02-29") == "2024-02-29"

    def test_empty_string_raises(self):
        with pytest.raises(ValidationError, match="date is required"):
            validate_date("")

    def test_none_raises(self):
        with pytest.raises(ValidationError, match="date is required"):
            validate_date(None)

    def test_wrong_format_raises(self):
        with pytest.raises(ValidationError, match="not valid"):
            validate_date("04/15/2026")

    def test_invalid_date_raises(self):
        with pytest.raises(ValidationError, match="not a valid calendar date"):
            validate_date("2026-02-30")

    def test_non_leap_feb29_raises(self):
        with pytest.raises(ValidationError, match="not a valid calendar date"):
            validate_date("2025-02-29")

    def test_invalid_month_raises(self):
        with pytest.raises(ValidationError, match="not a valid calendar date"):
            validate_date("2026-13-01")

    def test_custom_field_name(self):
        with pytest.raises(ValidationError, match="departure_date"):
            validate_date("bad", "departure_date")

    def test_non_string_raises(self):
        with pytest.raises(ValidationError, match="date is required"):
            validate_date(20260415)


class TestValidatePassengers:
    """Test passenger data validation."""

    @pytest.fixture
    def valid_pax(self):
        return [{
            "nameGiven": "John",
            "surname": "Doe",
            "nameTitle": "MR",
            "gender": "Male",
            "birthdate": "1990-01-15",
            "passengerType": "ADT",
            "emailContact": "john@example.com",
            "phone": "+12125551234",
            "travelerReference": "T1",
        }]

    def test_valid_passenger(self, valid_pax):
        warnings = validate_passengers(valid_pax)
        assert warnings == []

    def test_empty_list_raises(self):
        with pytest.raises(ValidationError, match="at least one passenger"):
            validate_passengers([])

    def test_none_raises(self):
        with pytest.raises(ValidationError, match="at least one passenger"):
            validate_passengers(None)

    def test_non_dict_passenger_raises(self):
        with pytest.raises(ValidationError, match="must be a dict"):
            validate_passengers(["not a dict"])

    def test_missing_required_field_raises(self, valid_pax):
        del valid_pax[0]["emailContact"]
        with pytest.raises(ValidationError, match="missing required fields.*emailContact"):
            validate_passengers(valid_pax)

    def test_invalid_title_raises(self, valid_pax):
        valid_pax[0]["nameTitle"] = "DR"
        with pytest.raises(ValidationError, match="nameTitle.*invalid"):
            validate_passengers(valid_pax)

    def test_invalid_gender_raises(self, valid_pax):
        valid_pax[0]["gender"] = "M"
        with pytest.raises(ValidationError, match="gender must be 'Male' or 'Female'"):
            validate_passengers(valid_pax)

    def test_invalid_passenger_type_raises(self, valid_pax):
        valid_pax[0]["passengerType"] = "ADULT"
        with pytest.raises(ValidationError, match="passengerType.*invalid"):
            validate_passengers(valid_pax)

    def test_duplicate_traveler_ref_raises(self, valid_pax):
        pax2 = valid_pax[0].copy()
        # Same travelerReference "T1"
        with pytest.raises(ValidationError, match="duplicate travelerReference"):
            validate_passengers(valid_pax + [pax2])

    def test_infants_exceed_adults_raises(self):
        adult = {
            "nameGiven": "John", "surname": "Doe", "nameTitle": "MR",
            "gender": "Male", "birthdate": "1990-01-15", "passengerType": "ADT",
            "emailContact": "j@e.com", "phone": "+1", "travelerReference": "T1",
        }
        infant1 = {
            "nameGiven": "Baby", "surname": "Doe", "nameTitle": "MR",
            "gender": "Male", "birthdate": "2025-06-01", "passengerType": "INF",
            "emailContact": "j@e.com", "phone": "+1", "travelerReference": "T2",
        }
        infant2 = {
            "nameGiven": "Baby2", "surname": "Doe", "nameTitle": "MRS",
            "gender": "Female", "birthdate": "2025-07-01", "passengerType": "INF",
            "emailContact": "j@e.com", "phone": "+1", "travelerReference": "T3",
        }
        with pytest.raises(ValidationError, match="infants exceed.*adults"):
            validate_passengers([adult, infant1, infant2])

    def test_no_adult_raises(self):
        child = {
            "nameGiven": "Kid", "surname": "Doe", "nameTitle": "MR",
            "gender": "Male", "birthdate": "2015-01-15", "passengerType": "CHD",
            "emailContact": "j@e.com", "phone": "+1", "travelerReference": "T1",
        }
        with pytest.raises(ValidationError, match="at least one adult"):
            validate_passengers([child])

    def test_invalid_email_returns_warning(self, valid_pax):
        valid_pax[0]["emailContact"] = "bademail"
        warnings = validate_passengers(valid_pax)
        assert any("may be invalid" in w for w in warnings)

    def test_short_name_returns_warning(self, valid_pax):
        valid_pax[0]["nameGiven"] = "J"
        warnings = validate_passengers(valid_pax)
        assert any("very short" in w for w in warnings)

    def test_cnn_passenger_type_valid(self, valid_pax):
        """CNN is a valid child type (some airlines use it instead of CHD)."""
        child = {
            "nameGiven": "Kid", "surname": "Doe", "nameTitle": "MR",
            "gender": "Male", "birthdate": "2015-01-15", "passengerType": "CNN",
            "emailContact": "j@e.com", "phone": "+1", "travelerReference": "T2",
        }
        warnings = validate_passengers(valid_pax + [child])
        assert isinstance(warnings, list)

    def test_multiple_passengers_valid(self, valid_pax):
        pax2 = valid_pax[0].copy()
        pax2["nameGiven"] = "Jane"
        pax2["nameTitle"] = "MRS"
        pax2["gender"] = "Female"
        pax2["travelerReference"] = "T2"
        warnings = validate_passengers(valid_pax + [pax2])
        assert warnings == []

    def test_search_validates_inputs(self, client):
        """search_flights raises ValidationError on bad inputs."""
        with pytest.raises(ValidationError, match="not a valid IATA code"):
            client.search_flights("XX", "LHR", "2026-04-15")

    def test_search_validates_same_origin_dest(self, client):
        with pytest.raises(ValidationError, match="cannot be the same"):
            client.search_flights("JFK", "JFK", "2026-04-15")

    def test_search_validates_date(self, client):
        with pytest.raises(ValidationError, match="not valid"):
            client.search_flights("JFK", "LHR", "15-04-2026")

    def test_search_validates_cabin(self, client):
        with pytest.raises(ValidationError, match="cabin_class.*invalid"):
            client.search_flights("JFK", "LHR", "2026-04-15", cabin_class="super_first")

    def test_search_validates_infants(self, client):
        with pytest.raises(ValidationError, match="infants exceed"):
            client.search_flights("JFK", "LHR", "2026-04-15", adults=1, infants=2)

    def test_booking_validates_passengers(self, client):
        """create_order raises ValidationError on bad passenger data."""
        client._track_session("validate_sess")
        bad_pax = [{"nameGiven": "John"}]  # Missing required fields
        with pytest.raises(ValidationError, match="missing required fields"):
            client.create_order("validate_sess", bad_pax)


# =========================================================================
# PHASE 2: RETRY WITH EXPONENTIAL BACKOFF TESTS
# =========================================================================

class TestRetryLogic:
    """Test retry with exponential backoff on retryable errors."""

    def test_retry_on_429(self, client):
        """429 rate_limited triggers retry and eventually succeeds."""
        mock_resp_fail = MagicMock()
        mock_resp_fail.status_code = 429
        mock_resp_fail.text = "Rate limited"

        mock_resp_ok = MagicMock()
        mock_resp_ok.status_code = 200
        mock_resp_ok.json.return_value = {"ok": True}

        client._session.post = MagicMock(side_effect=[mock_resp_fail, mock_resp_ok])

        with patch("clients.airgateway.time.sleep"):
            result = client._request("test", {})

        assert result["success"] is True
        assert result["attempts"] == 2

    def test_retry_on_502(self, client):
        """502 gateway_error triggers retry."""
        mock_fail = MagicMock()
        mock_fail.status_code = 502
        mock_fail.text = "Bad Gateway"

        mock_ok = MagicMock()
        mock_ok.status_code = 200
        mock_ok.json.return_value = {"data": "ok"}

        client._session.post = MagicMock(side_effect=[mock_fail, mock_ok])

        with patch("clients.airgateway.time.sleep"):
            result = client._request("test", {})

        assert result["success"] is True
        assert result["attempts"] == 2

    def test_retry_on_timeout(self, client):
        """Timeouts trigger retry."""
        import requests as req

        mock_ok = MagicMock()
        mock_ok.status_code = 200
        mock_ok.json.return_value = {"ok": True}

        client._session.post = MagicMock(
            side_effect=[req.exceptions.Timeout("timed out"), mock_ok]
        )

        with patch("clients.airgateway.time.sleep"):
            result = client._request("test", {})

        assert result["success"] is True
        assert result["attempts"] == 2

    def test_retry_on_connection_error(self, client):
        """ConnectionError triggers retry."""
        import requests as req

        mock_ok = MagicMock()
        mock_ok.status_code = 200
        mock_ok.json.return_value = {"ok": True}

        client._session.post = MagicMock(
            side_effect=[req.exceptions.ConnectionError("refused"), mock_ok]
        )

        with patch("clients.airgateway.time.sleep"):
            result = client._request("test", {})

        assert result["success"] is True
        assert result["attempts"] == 2

    def test_no_retry_on_401(self, client):
        """401 auth_failed does NOT retry."""
        mock_fail = MagicMock()
        mock_fail.status_code = 401
        mock_fail.text = "Unauthorized"

        client._session.post = MagicMock(return_value=mock_fail)

        result = client._request("test", {})

        assert result["success"] is False
        assert result["error_type"] == "auth_failed"
        assert result["attempts"] == 1
        # Only called once — no retries
        assert client._session.post.call_count == 1

    def test_no_retry_on_422(self, client):
        """422 validation_error does NOT retry."""
        mock_fail = MagicMock()
        mock_fail.status_code = 422
        mock_fail.text = "Validation error"

        client._session.post = MagicMock(return_value=mock_fail)

        result = client._request("test", {})

        assert result["success"] is False
        assert result["attempts"] == 1
        assert client._session.post.call_count == 1

    def test_max_retries_exhausted(self, client):
        """After max retries, returns last error."""
        mock_fail = MagicMock()
        mock_fail.status_code = 503
        mock_fail.text = "Service Unavailable"

        client._session.post = MagicMock(return_value=mock_fail)

        with patch("clients.airgateway.time.sleep"):
            result = client._request("test", {})

        assert result["success"] is False
        assert result["error_type"] == "service_unavailable"
        assert result["attempts"] == DEFAULT_MAX_RETRIES + 1
        assert client._session.post.call_count == DEFAULT_MAX_RETRIES + 1

    def test_max_retries_zero_no_retry(self, client):
        """max_retries=0 means no retries at all."""
        mock_fail = MagicMock()
        mock_fail.status_code = 429
        mock_fail.text = "Rate limited"

        client._session.post = MagicMock(return_value=mock_fail)

        result = client._request("test", {}, max_retries=0)

        assert result["success"] is False
        assert result["attempts"] == 1
        assert client._session.post.call_count == 1

    def test_booking_uses_zero_retries(self, client):
        """create_order passes max_retries=0 to prevent double-booking."""
        client._track_session("no_retry_sess")
        pax = [{
            "nameGiven": "John", "surname": "Doe", "nameTitle": "MR",
            "gender": "Male", "birthdate": "1990-01-15", "passengerType": "ADT",
            "emailContact": "j@e.com", "phone": "+1", "travelerReference": "T1",
        }]

        with patch.object(client, "_request", return_value={
            "success": True, "data": {"id": "ord_001", "status": "confirmed"},
        }) as mock_req:
            client.create_order("no_retry_sess", pax)
            # Verify max_retries=0 was passed
            assert mock_req.call_args.kwargs.get("max_retries") == 0

    def test_cancel_uses_zero_retries(self, client):
        """cancel_order passes max_retries=0."""
        with patch.object(client, "_request", return_value={
            "success": True, "data": {"status": "voided"},
        }) as mock_req:
            client.cancel_order("ord_001")
            assert mock_req.call_args.kwargs.get("max_retries") == 0

    def test_issue_ticket_uses_zero_retries(self, client):
        """issue_ticket passes max_retries=0."""
        with patch.object(client, "_request", return_value={
            "success": True, "data": {"id": "ord_001", "status": "ticketed"},
        }) as mock_req:
            client.issue_ticket("ord_001")
            assert mock_req.call_args.kwargs.get("max_retries") == 0

    def test_exponential_backoff_delays(self, client):
        """Verify backoff delays are exponential: 1, 2, 4 seconds."""
        mock_fail = MagicMock()
        mock_fail.status_code = 429
        mock_fail.text = "Rate limited"

        client._session.post = MagicMock(return_value=mock_fail)

        sleep_calls = []
        with patch("clients.airgateway.time.sleep", side_effect=lambda d: sleep_calls.append(d)):
            client._request("test", {})

        # 3 retries = 3 sleep calls with exponential backoff
        assert len(sleep_calls) == DEFAULT_MAX_RETRIES
        assert sleep_calls[0] == DEFAULT_RETRY_BASE_DELAY * 1    # 1.0
        assert sleep_calls[1] == DEFAULT_RETRY_BASE_DELAY * 2    # 2.0
        assert sleep_calls[2] == DEFAULT_RETRY_BASE_DELAY * 4    # 4.0

    def test_backoff_capped_at_max(self):
        """Backoff delay is capped at DEFAULT_RETRY_MAX_DELAY."""
        client = AirGatewayClient(
            api_key="test_key_1234567890",
            max_retries=10,
            retry_base_delay=10.0,  # Very aggressive base
        )

        mock_fail = MagicMock()
        mock_fail.status_code = 429
        mock_fail.text = "Rate limited"

        client._session.post = MagicMock(return_value=mock_fail)

        sleep_calls = []
        with patch("clients.airgateway.time.sleep", side_effect=lambda d: sleep_calls.append(d)):
            client._request("test", {})

        # All delays should be <= DEFAULT_RETRY_MAX_DELAY (30s)
        for delay in sleep_calls:
            assert delay <= DEFAULT_RETRY_MAX_DELAY

    def test_latency_tracked_on_success(self, client):
        """Successful requests include latency_ms."""
        mock_ok = MagicMock()
        mock_ok.status_code = 200
        mock_ok.json.return_value = {"ok": True}

        client._session.post = MagicMock(return_value=mock_ok)
        result = client._request("test", {})

        assert "latency_ms" in result
        assert result["latency_ms"] >= 0

    def test_latency_tracked_on_failure(self, client):
        """Failed requests include latency_ms."""
        mock_fail = MagicMock()
        mock_fail.status_code = 401
        mock_fail.text = "Unauthorized"

        client._session.post = MagicMock(return_value=mock_fail)
        result = client._request("test", {})

        assert "latency_ms" in result
        assert result["latency_ms"] >= 0

    def test_custom_retry_config(self):
        """Client accepts custom max_retries and retry_base_delay."""
        c = AirGatewayClient(api_key="test_key_1234567890", max_retries=5, retry_base_delay=0.5)
        assert c._max_retries == 5
        assert c._retry_base_delay == 0.5


# =========================================================================
# PHASE 2: REQUEST METRICS TESTS
# =========================================================================

class TestRequestMetrics:
    """Test per-endpoint request metrics tracking."""

    @pytest.fixture
    def metrics(self):
        return RequestMetrics()

    def test_record_success(self, metrics):
        metrics.record_success("AirShopping", 150.5)
        stats = metrics.get_stats("AirShopping")

        assert stats["total_requests"] == 1
        assert stats["success_count"] == 1
        assert stats["error_count"] == 0
        assert stats["success_rate"] == 100.0
        assert stats["avg_latency_ms"] == 150.5
        assert stats["min_latency_ms"] == 150.5
        assert stats["max_latency_ms"] == 150.5

    def test_record_error(self, metrics):
        metrics.record_error("OfferPrice", 200.0, "rate_limited")
        stats = metrics.get_stats("OfferPrice")

        assert stats["total_requests"] == 1
        assert stats["success_count"] == 0
        assert stats["error_count"] == 1
        assert stats["success_rate"] == 0.0
        assert stats["error_types"] == {"rate_limited": 1}
        assert stats["last_error"]["type"] == "rate_limited"

    def test_record_retry(self, metrics):
        metrics.record_success("AirShopping", 100.0)
        metrics.record_retry("AirShopping")
        metrics.record_retry("AirShopping")
        stats = metrics.get_stats("AirShopping")

        assert stats["retry_count"] == 2

    def test_multiple_requests(self, metrics):
        metrics.record_success("AirShopping", 100.0)
        metrics.record_success("AirShopping", 200.0)
        metrics.record_error("AirShopping", 300.0, "timeout")
        stats = metrics.get_stats("AirShopping")

        assert stats["total_requests"] == 3
        assert stats["success_count"] == 2
        assert stats["error_count"] == 1
        assert stats["avg_latency_ms"] == 200.0
        assert stats["min_latency_ms"] == 100.0
        assert stats["max_latency_ms"] == 300.0
        assert round(stats["success_rate"], 1) == 66.7

    def test_get_stats_unknown_endpoint(self, metrics):
        stats = metrics.get_stats("NonExistent")
        assert stats == {}

    def test_get_all_stats(self, metrics):
        metrics.record_success("AirShopping", 100.0)
        metrics.record_success("OfferPrice", 80.0)
        metrics.record_error("OrderCreate", 500.0, "conflict")

        all_stats = metrics.get_stats()
        assert len(all_stats) == 3
        assert "AirShopping" in all_stats
        assert "OfferPrice" in all_stats
        assert "OrderCreate" in all_stats

    def test_reset(self, metrics):
        metrics.record_success("AirShopping", 100.0)
        metrics.record_error("OfferPrice", 200.0, "timeout")
        metrics.reset()

        assert metrics.get_stats() == {}
        assert metrics.get_stats("AirShopping") == {}

    def test_client_has_metrics(self, client):
        """Client has a RequestMetrics instance on init."""
        assert isinstance(client.metrics, RequestMetrics)

    def test_metrics_recorded_on_success(self, client):
        """Successful requests are recorded in metrics."""
        mock_ok = MagicMock()
        mock_ok.status_code = 200
        mock_ok.json.return_value = {"ok": True}

        client._session.post = MagicMock(return_value=mock_ok)
        client._request("AirShopping", {})

        stats = client.metrics.get_stats("AirShopping")
        assert stats["total_requests"] == 1
        assert stats["success_count"] == 1

    def test_metrics_recorded_on_error(self, client):
        """Errors are recorded in metrics."""
        mock_fail = MagicMock()
        mock_fail.status_code = 401
        mock_fail.text = "Unauthorized"

        client._session.post = MagicMock(return_value=mock_fail)
        client._request("OfferPrice", {})

        stats = client.metrics.get_stats("OfferPrice")
        assert stats["error_count"] == 1
        assert stats["error_types"] == {"auth_failed": 1}

    def test_metrics_retries_counted(self, client):
        """Retries are counted in metrics."""
        mock_fail = MagicMock()
        mock_fail.status_code = 429
        mock_fail.text = "Rate limited"

        mock_ok = MagicMock()
        mock_ok.status_code = 200
        mock_ok.json.return_value = {"ok": True}

        client._session.post = MagicMock(side_effect=[mock_fail, mock_fail, mock_ok])

        with patch("clients.airgateway.time.sleep"):
            client._request("AirShopping", {})

        stats = client.metrics.get_stats("AirShopping")
        assert stats["success_count"] == 1
        assert stats["retry_count"] == 2

    def test_error_type_distribution(self, metrics):
        """Multiple error types tracked per endpoint."""
        metrics.record_error("AirShopping", 100.0, "timeout")
        metrics.record_error("AirShopping", 100.0, "timeout")
        metrics.record_error("AirShopping", 100.0, "rate_limited")

        stats = metrics.get_stats("AirShopping")
        assert stats["error_types"] == {"timeout": 2, "rate_limited": 1}

    def test_last_success_at_recorded(self, metrics):
        metrics.record_success("AirShopping", 100.0)
        stats = metrics.get_stats("AirShopping")
        assert stats["last_success_at"] is not None
        assert isinstance(stats["last_success_at"], float)


# =========================================================================
# PHASE 2: MULTI-POS ARBITRAGE SCANNER TESTS
# =========================================================================

class TestArbitrageScan:
    """Test multi-POS parallel arbitrage scanner."""

    def test_arbitrage_markets_constant(self):
        """Default arbitrage markets include key POS countries."""
        assert "US" in ARBITRAGE_MARKETS
        assert "DK" in ARBITRAGE_MARKETS
        assert "ES" in ARBITRAGE_MARKETS
        assert "GB" in ARBITRAGE_MARKETS
        assert "DE" in ARBITRAGE_MARKETS
        assert len(ARBITRAGE_MARKETS) >= 6

    def test_basic_scan(self, client):
        """arbitrage_scan returns deduped results across markets."""
        us_response = {
            "success": True,
            "flights": [
                {"airline": "BA", "departure_time": "T19:00", "price": "465.50",
                 "offer_id": "us_1", "origin": "JFK", "destination": "LHR"},
            ],
            "shopping_response_id": "sr_us",
        }
        dk_response = {
            "success": True,
            "flights": [
                {"airline": "BA", "departure_time": "T19:00", "price": "385.00",
                 "offer_id": "dk_1", "origin": "JFK", "destination": "LHR"},
            ],
            "shopping_response_id": "sr_dk",
        }

        def mock_search(origin, destination, departure_date, **kwargs):
            country = kwargs.get("country", "US")
            return us_response if country == "US" else dk_response

        with patch.object(client, "search_flights", side_effect=mock_search):
            result = client.arbitrage_scan(
                "JFK", "LHR", "2026-04-15", markets=["US", "DK"]
            )

        assert result["success"]
        assert result["markets_searched"] == 2
        assert result["total_unique"] == 1  # Same flight, deduped
        # DK price won (385 < 465.50)
        assert result["flights"][0]["price"] == "385.00"
        assert result["flights"][0]["pos_country"] == "DK"

    def test_dedup_keeps_cheapest(self, client):
        """Dedup keeps the cheapest offer per airline+departure_time."""
        flights = [
            {"airline": "BA", "departure_time": "T19:00", "price": "500",
             "pos_country": "US"},
            {"airline": "BA", "departure_time": "T19:00", "price": "400",
             "pos_country": "DK"},
            {"airline": "BA", "departure_time": "T19:00", "price": "420",
             "pos_country": "ES"},
        ]
        result = client._dedup_arbitrage(flights)

        assert len(result) == 1
        assert result[0]["price"] == "400"
        assert result[0]["pos_country"] == "DK"

    def test_dedup_different_flights_kept(self, client):
        """Different flights (different airline or time) are all kept."""
        flights = [
            {"airline": "BA", "departure_time": "T19:00", "price": "400",
             "pos_country": "DK"},
            {"airline": "AA", "departure_time": "T21:00", "price": "450",
             "pos_country": "US"},
            {"airline": "LH", "departure_time": "T17:30", "price": "890",
             "pos_country": "DE"},
        ]
        result = client._dedup_arbitrage(flights)

        assert len(result) == 3

    def test_dedup_sorted_by_price(self, client):
        """Deduped results are sorted by price ascending."""
        flights = [
            {"airline": "LH", "departure_time": "T17:30", "price": "890",
             "pos_country": "DE"},
            {"airline": "BA", "departure_time": "T19:00", "price": "400",
             "pos_country": "DK"},
            {"airline": "AA", "departure_time": "T21:00", "price": "450",
             "pos_country": "US"},
        ]
        result = client._dedup_arbitrage(flights)

        prices = [float(f["price"]) for f in result]
        assert prices == sorted(prices)

    def test_savings_calculation(self, client):
        """Savings stats computed correctly."""
        deduped = [
            {"airline": "BA", "departure_time": "T19:00", "price": "385",
             "pos_country": "DK"},
            {"airline": "AA", "departure_time": "T21:00", "price": "450",
             "pos_country": "US"},
        ]
        market_results = {
            "US": {"success": True, "count": 2, "cheapest": 450},
            "DK": {"success": True, "count": 1, "cheapest": 385},
        }
        savings = client._calc_arbitrage_savings(deduped, market_results)

        assert savings["found"] is True
        assert savings["non_us_winners"] == 1
        assert savings["us_winners"] == 1
        assert savings["cheapest_flight"] == 385.0
        assert "DK" in savings["winning_markets"]

    def test_no_savings_when_us_wins(self, client):
        """No savings when US market has all cheapest."""
        deduped = [
            {"airline": "BA", "departure_time": "T19:00", "price": "400",
             "pos_country": "US"},
        ]
        savings = client._calc_arbitrage_savings(deduped, {})
        assert savings["found"] is False

    def test_scan_validates_inputs(self, client):
        """arbitrage_scan validates IATA codes and dates."""
        with pytest.raises(ValidationError, match="not a valid IATA code"):
            client.arbitrage_scan("XX", "LHR", "2026-04-15")

    def test_scan_default_markets(self, client):
        """Default markets are top 6 from ARBITRAGE_MARKETS."""
        with patch.object(client, "search_flights", return_value={
            "success": True, "flights": [], "shopping_response_id": "sr",
        }) as mock_search:
            client.arbitrage_scan("JFK", "LHR", "2026-04-15")
            # Should have searched 6 markets (default)
            assert mock_search.call_count == 6

    def test_scan_custom_markets(self, client):
        """Custom markets override default."""
        with patch.object(client, "search_flights", return_value={
            "success": True, "flights": [], "shopping_response_id": "sr",
        }) as mock_search:
            client.arbitrage_scan(
                "JFK", "LHR", "2026-04-15",
                markets=["US", "DK", "GB"]
            )
            assert mock_search.call_count == 3

    def test_scan_market_results_tracked(self, client):
        """Per-market results are tracked."""
        def mock_search(origin, destination, departure_date, **kwargs):
            country = kwargs.get("country", "US")
            return {
                "success": True,
                "flights": [
                    {"airline": "BA", "departure_time": "T19:00",
                     "price": "400" if country == "US" else "350",
                     "offer_id": f"off_{country}",
                     "origin": "JFK", "destination": "LHR"},
                ],
                "shopping_response_id": f"sr_{country}",
            }

        with patch.object(client, "search_flights", side_effect=mock_search):
            result = client.arbitrage_scan(
                "JFK", "LHR", "2026-04-15", markets=["US", "DK"]
            )

        assert "US" in result["market_results"]
        assert "DK" in result["market_results"]
        assert result["market_results"]["US"]["count"] == 1
        assert result["market_results"]["DK"]["count"] == 1

    def test_scan_handles_market_failure(self, client):
        """Failed market searches don't crash the scan."""
        def mock_search(origin, destination, departure_date, **kwargs):
            country = kwargs.get("country", "US")
            if country == "DK":
                raise Exception("DK market unavailable")
            return {
                "success": True,
                "flights": [
                    {"airline": "BA", "departure_time": "T19:00", "price": "400",
                     "offer_id": "us_1", "origin": "JFK", "destination": "LHR"},
                ],
                "shopping_response_id": "sr_us",
            }

        with patch.object(client, "search_flights", side_effect=mock_search):
            result = client.arbitrage_scan(
                "JFK", "LHR", "2026-04-15", markets=["US", "DK"]
            )

        assert result["success"]
        assert result["total_unique"] == 1
        assert result["market_results"]["DK"]["success"] is False

    def test_flights_tagged_with_pos(self, client):
        """Each flight is tagged with its POS country and shopping_response_id."""
        def mock_search(origin, destination, departure_date, **kwargs):
            return {
                "success": True,
                "flights": [
                    {"airline": "BA", "departure_time": "T19:00", "price": "400",
                     "offer_id": "off_1", "origin": "JFK", "destination": "LHR"},
                ],
                "shopping_response_id": f"sr_{kwargs.get('country', 'US')}",
            }

        with patch.object(client, "search_flights", side_effect=mock_search):
            result = client.arbitrage_scan(
                "JFK", "LHR", "2026-04-15", markets=["US"]
            )

        flight = result["flights"][0]
        assert flight["pos_country"] == "US"
        assert flight["shopping_response_id"] == "sr_US"


# =========================================================================
# PHASE 2: AUTOMATED CONFIRMATION POLLER TESTS
# =========================================================================

class TestAwaitConfirmation:
    """Test automated booking confirmation polling."""

    def test_immediate_confirmation(self, client):
        """Returns immediately if status is not pending."""
        with patch.object(client, "poll_order", return_value={
            "success": True,
            "booking": {"status": "confirmed", "order_id": "ord_001", "pnr": "ABC123"},
        }):
            result = client.await_confirmation("ord_001", timeout=30)

        assert result["success"]
        assert result["booking"]["status"] == "confirmed"

    def test_confirms_after_two_polls(self, client):
        """Polls until status changes from pending."""
        poll_results = [
            {"success": True, "booking": {"status": "pending", "order_id": "ord_001"}},
            {"success": True, "booking": {"status": "pending", "order_id": "ord_001"}},
            {"success": True, "booking": {"status": "confirmed", "order_id": "ord_001", "pnr": "XYZ"}},
        ]

        with patch.object(client, "poll_order", side_effect=poll_results):
            with patch("clients.airgateway.time.sleep"):
                result = client.await_confirmation("ord_001", poll_interval=0.01, timeout=30)

        assert result["booking"]["status"] == "confirmed"

    def test_timeout_falls_back_to_retrieve(self, client):
        """On timeout, falls back to OrderRetrieve for final state."""
        with patch.object(client, "poll_order", return_value={
            "success": True, "booking": {"status": "pending", "order_id": "ord_001"},
        }):
            with patch.object(client, "retrieve_order", return_value={
                "success": True, "booking": {"status": "pending", "order_id": "ord_001"},
            }) as mock_retrieve:
                with patch("clients.airgateway.time.sleep"):
                    result = client.await_confirmation(
                        "ord_001", poll_interval=0.01, timeout=0.03
                    )

        # Should have called retrieve_order as fallback
        mock_retrieve.assert_called()
        assert result.get("confirmation_timed_out") is True

    def test_poll_failure_falls_back_to_retrieve(self, client):
        """If poll_order fails, falls back to retrieve_order."""
        with patch.object(client, "poll_order", return_value={
            "success": False, "error": "Poll failed",
        }):
            with patch.object(client, "retrieve_order", return_value={
                "success": True, "booking": {"status": "confirmed", "order_id": "ord_001"},
            }) as mock_retrieve:
                with patch("clients.airgateway.time.sleep"):
                    result = client.await_confirmation(
                        "ord_001", poll_interval=0.01, timeout=0.05
                    )

        mock_retrieve.assert_called()

    def test_owner_passed_to_poll(self, client):
        """Owner code is forwarded to poll_order."""
        with patch.object(client, "poll_order", return_value={
            "success": True, "booking": {"status": "confirmed", "order_id": "ord_001"},
        }) as mock_poll:
            client.await_confirmation("ord_001", owner="BA")

        mock_poll.assert_called_with("ord_001", owner="BA")

    def test_ticketed_status_stops_polling(self, client):
        """Status 'ticketed' also stops polling (not just 'confirmed')."""
        with patch.object(client, "poll_order", return_value={
            "success": True, "booking": {"status": "ticketed", "order_id": "ord_001"},
        }):
            result = client.await_confirmation("ord_001")

        assert result["booking"]["status"] == "ticketed"

    def test_failed_status_stops_polling(self, client):
        """Status 'failed' also stops polling."""
        with patch.object(client, "poll_order", return_value={
            "success": True, "booking": {"status": "failed", "order_id": "ord_001"},
        }):
            result = client.await_confirmation("ord_001")

        assert result["booking"]["status"] == "failed"


# =========================================================================
# PHASE 2: CONSTANTS AND EDGE CASES
# =========================================================================

class TestConstants:
    """Test that Phase 2 constants are properly defined."""

    def test_default_max_retries(self):
        assert DEFAULT_MAX_RETRIES == 3

    def test_default_retry_base_delay(self):
        assert DEFAULT_RETRY_BASE_DELAY == 1.0

    def test_default_retry_max_delay(self):
        assert DEFAULT_RETRY_MAX_DELAY == 30.0

    def test_valid_titles(self):
        assert VALID_TITLES == {"MR", "MRS", "MS", "MISS"}

    def test_valid_pax_types(self):
        assert VALID_PAX_TYPES == {"ADT", "CHD", "CNN", "INF"}

    def test_required_pax_fields(self):
        assert "nameGiven" in REQUIRED_PAX_FIELDS
        assert "surname" in REQUIRED_PAX_FIELDS
        assert "nameTitle" in REQUIRED_PAX_FIELDS
        assert "gender" in REQUIRED_PAX_FIELDS
        assert "birthdate" in REQUIRED_PAX_FIELDS
        assert "passengerType" in REQUIRED_PAX_FIELDS
        assert "emailContact" in REQUIRED_PAX_FIELDS
        assert "phone" in REQUIRED_PAX_FIELDS
        assert "travelerReference" in REQUIRED_PAX_FIELDS
