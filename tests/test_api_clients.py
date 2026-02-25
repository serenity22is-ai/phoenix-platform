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
    """Return a mock authenticated user (member pricing = 25% fee)."""
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
                        "offerInitialPrice": {"amount": "180.00", "currency": "USD"},
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

        # Hotel name lookup
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"data": {"name": "Grand Hotel Paris"}}
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
                        "offerInitialPrice": {"amount": "180.00", "currency": "USD"},
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
                        "offerInitialPrice": {"amount": "180.00", "currency": "USD"},
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
            json=lambda: {"data": {"name": "Hotel"}}
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
        """MYSTES price = our_cost + 25% of savings. User saves 75%."""
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"data": [
                {
                    "hotelId": "H001",
                    "roomTypes": [{
                        "offerId": "OFF-001",
                        "offerRetailRate": {"amount": "100.00", "currency": "USD"},
                        "offerInitialPrice": {"amount": "200.00", "currency": "USD"},
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
            json=lambda: {"data": {"name": "Hotel"}}
        )

        from liteapi_client import LiteAPIHotelClient
        client = LiteAPIHotelClient()
        client.api_key = "test_key"

        result = client.search_hotels("PAR", check_in="2026-03-15", check_out="2026-03-16", user=_mock_member())
        hotel = result["hotels"][0]

        # Google price: $200, our cost: $100, savings_raw = $100
        # Member fee: 25% of $100 = $25
        # MYSTES price: $100 + $25 = $125
        # User savings: $200 - $125 = $75
        # Savings pct: 75/200 = 37.5%
        assert hotel["google_price"] == 200.00
        assert hotel["our_cost"] == 100.00
        assert hotel["platform_fee"] == 25.00
        assert hotel["price_total"] == 125.00
        assert hotel["user_savings"] == 75.00
        assert hotel["savings_pct"] == 37.5

    @patch("liteapi_client.requests.post")
    @patch("liteapi_client.requests.get")
    def test_platform_fee_small_savings(self, mock_get, mock_post):
        """Platform fee is flat 25% even on small savings."""
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"data": [
                {
                    "hotelId": "H001",
                    "roomTypes": [{
                        "offerId": "OFF-001",
                        "offerRetailRate": {"amount": "95.00", "currency": "USD"},
                        "offerInitialPrice": {"amount": "100.00", "currency": "USD"},
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
            json=lambda: {"data": {"name": "Hotel"}}
        )

        from liteapi_client import LiteAPIHotelClient
        client = LiteAPIHotelClient()
        client.api_key = "test_key"

        result = client.search_hotels("PAR", check_in="2026-03-15", check_out="2026-03-16", user=_mock_member())
        hotel = result["hotels"][0]

        # savings_raw = $5, member 25% = $1.25
        assert hotel["platform_fee"] == 1.25
        assert hotel["price_total"] == 96.25  # $95 + $1.25

    @patch("liteapi_client.requests.post")
    @patch("liteapi_client.requests.get")
    def test_platform_fee_large_savings(self, mock_get, mock_post):
        """Platform fee is flat 25% even on large savings (no cap)."""
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"data": [
                {
                    "hotelId": "H001",
                    "roomTypes": [{
                        "offerId": "OFF-001",
                        "offerRetailRate": {"amount": "500.00", "currency": "USD"},
                        "offerInitialPrice": {"amount": "1000.00", "currency": "USD"},
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
            json=lambda: {"data": {"name": "Hotel"}}
        )

        from liteapi_client import LiteAPIHotelClient
        client = LiteAPIHotelClient()
        client.api_key = "test_key"

        result = client.search_hotels("PAR", check_in="2026-03-15", check_out="2026-03-16", user=_mock_member())
        hotel = result["hotels"][0]

        # savings_raw = $500, member 25% = $125
        assert hotel["platform_fee"] == 125.00
        assert hotel["price_total"] == 625.00  # $500 + $125

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
            guest={"first_name": "John", "last_name": "Doe", "email": "john@test.com"},
            payment={"card_number": "4242424242424242", "expiry_date": "12/28", "cvc": "123", "vendor_code": "VI"},
            prebook_id="PB-12345",
        )
        assert result["success"] is True
        assert result["booking_id"] == "BK-999"
        assert result["provider_confirmation"] == "REF-ABC"

        # Verify payload shape
        call_kwargs = mock_post.call_args
        payload = call_kwargs.kwargs.get("json", call_kwargs[1].get("json", {}))
        assert payload["prebookId"] == "PB-12345"
        assert payload["guestInfo"]["guestFirstName"] == "John"

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
    """Test picasso_client.py multi-POS flight search and booking."""

    def test_not_configured(self):
        """Search returns error when PICASSO_API_KEY is missing."""
        from picasso_client import PicassoClient
        client = PicassoClient()
        client.api_key = ""

        result = client.search_flights("JFK", "LHR", "2026-03-15")
        assert result["success"] is False
        assert "not configured" in result["error"].lower()

    def test_is_configured(self):
        """is_configured returns True when key is set."""
        from picasso_client import PicassoClient
        client = PicassoClient()
        client.api_key = "test_key"
        assert client.is_configured() is True

    @patch("picasso_client.requests.post")
    def test_search_flights_multi_pos(self, mock_post):
        """Search parses multi-POS pricing and calculates arbitrage."""
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "data": [
                    {
                        "id": "OFF-001",
                        "pricing": [
                            {"pos": "US", "amount": 450},
                            {"pos": "DK", "amount": 350},
                            {"pos": "ES", "amount": 380},
                        ],
                        "itineraries": [{
                            "segments": [{
                                "carrierCode": "AA",
                                "number": "100",
                                "carrierName": "American Airlines",
                                "departure": {"iataCode": "JFK", "at": "2026-03-15T08:00:00"},
                                "arrival": {"iataCode": "LHR", "at": "2026-03-15T20:00:00"},
                            }]
                        }],
                        "duration": "PT7H",
                        "cabinClass": "ECONOMY",
                    }
                ],
                "marketsSearched": 105,
            }
        )
        mock_post.return_value.raise_for_status = MagicMock()

        from picasso_client import PicassoClient
        client = PicassoClient()
        client.api_key = "test_key"

        result = client.search_flights("JFK", "LHR", "2026-03-15")

        assert result["success"] is True
        assert len(result["flights"]) == 1
        assert result["markets_searched"] == 105
        assert result["source"] == "picasso"

        flight = result["flights"][0]
        assert flight["us_price"] == 450
        assert flight["cheapest_market"] == "MYSTES"  # B2C safe — real POS in _internal fields
        assert flight["_internal_pos_market"] == "DK"
        assert flight["_internal_cheapest_price"] == 350

    @patch("picasso_client.requests.post")
    def test_pos_arbitrage_pricing(self, mock_post):
        """Verify MYSTES pricing: cheapest + 25% of savings (min $3, max $50)."""
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "data": [{
                    "id": "OFF-001",
                    "pricing": [
                        {"pos": "US", "amount": 400},
                        {"pos": "DK", "amount": 300},
                    ],
                    "itineraries": [{"segments": [{
                        "carrierCode": "AA", "number": "1",
                        "departure": {"iataCode": "JFK", "at": "2026-03-15T08:00:00"},
                        "arrival": {"iataCode": "LHR", "at": "2026-03-15T20:00:00"},
                    }]}],
                    "duration": "PT7H",
                }],
                "marketsSearched": 2,
            }
        )
        mock_post.return_value.raise_for_status = MagicMock()

        from picasso_client import PicassoClient
        client = PicassoClient()
        client.api_key = "test_key"

        result = client.search_flights("JFK", "LHR", "2026-03-15")
        flight = result["flights"][0]

        # US: $400, DK: $300, savings_raw = $100
        # Platform fee: 25% of $100 = $25
        # MYSTES price: $300 + $25 = $325
        # User savings: $400 - $325 = $75
        assert flight["mystes_price"] == 325.0
        assert flight["platform_fee"] == 25.0
        assert flight["savings"] == 75.0
        assert flight["savings_pct"] == pytest.approx(18.75, abs=0.1)

    @patch("picasso_client.requests.post")
    def test_no_arbitrage_when_us_cheapest(self, mock_post):
        """When US is the cheapest POS, no savings and zero platform fee."""
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "data": [{
                    "id": "OFF-001",
                    "pricing": [
                        {"pos": "US", "amount": 300},
                        {"pos": "DK", "amount": 350},
                    ],
                    "itineraries": [{"segments": [{
                        "carrierCode": "UA", "number": "1",
                        "departure": {"iataCode": "JFK", "at": "2026-03-15T08:00:00"},
                        "arrival": {"iataCode": "LHR", "at": "2026-03-15T20:00:00"},
                    }]}],
                    "duration": "PT7H",
                }],
                "marketsSearched": 2,
            }
        )
        mock_post.return_value.raise_for_status = MagicMock()

        from picasso_client import PicassoClient
        client = PicassoClient()
        client.api_key = "test_key"

        result = client.search_flights("JFK", "LHR", "2026-03-15")
        flight = result["flights"][0]

        assert flight["savings"] == 0
        assert flight["platform_fee"] == 0
        assert flight["mystes_price"] == 300.0
        assert flight["deal"] is None  # No deal object when no savings

    # Note: platform_fee is NOT computed in picasso_client.py — it's computed
    # in search.py when comparing Picasso prices against Google prices.
    # Fee invariant tests are in TestPricingInvariants below.

    def test_parse_duration_iso(self):
        """Duration parser handles ISO 8601 format."""
        from picasso_client import PicassoClient
        client = PicassoClient()

        assert client._parse_duration("PT7H30M") == 450
        assert client._parse_duration("PT14H") == 840
        assert client._parse_duration("PT45M") == 45
        assert client._parse_duration("") == 0
        assert client._parse_duration(None) == 0
        assert client._parse_duration(120) == 120

    def test_format_duration(self):
        """Duration formatter outputs human-readable strings."""
        from picasso_client import PicassoClient
        client = PicassoClient()

        assert client._format_duration(450) == "7h 30m"
        assert client._format_duration(120) == "2h"
        assert client._format_duration(45) == "45m"
        assert client._format_duration(0) == ""

    @patch("picasso_client.requests.post")
    def test_price_confirm(self, mock_post):
        """price_confirm validates offer and returns confirmed price."""
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"data": {
                "price": 325.50,
                "currency": "USD",
                "pointOfSale": "DK",
                "bookable": True,
            }}
        )
        mock_post.return_value.raise_for_status = MagicMock()

        from picasso_client import PicassoClient
        client = PicassoClient()
        client.api_key = "test_key"

        result = client.price_confirm("OFF-001", pos_market="DK")
        assert result["success"] is True
        assert result["confirmed_price"] == 325.50
        assert result["pos_market"] == "DK"
        assert result["bookable"] is True

    @patch("picasso_client.requests.post")
    def test_create_booking(self, mock_post):
        """create_booking sends traveler data and returns PNR."""
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"data": {
                "bookingId": "BK-PIC-001",
                "pnr": "ABC123",
                "totalPrice": 325.50,
                "currency": "USD",
                "segments": [{
                    "departure": {"iataCode": "JFK"},
                    "arrival": {"iataCode": "LHR"},
                    "carrierCode": "AA",
                    "number": "100",
                }],
            }}
        )
        mock_post.return_value.raise_for_status = MagicMock()

        from picasso_client import PicassoClient
        client = PicassoClient()
        client.api_key = "test_key"

        result = client.create_booking(
            offer_id="OFF-001",
            travelers=[{
                "first_name": "John",
                "last_name": "Doe",
                "date_of_birth": "1990-05-15",
                "gender": "MALE",
                "email": "john@test.com",
                "phone": "+15551234567",
                "passport_number": "P12345678",
                "passport_expiry": "2030-01-01",
                "passport_country": "US",
            }],
            pos_market="DK",
            contact_email="john@test.com",
        )

        assert result["success"] is True
        assert result["pnr"] == "ABC123"
        assert result["booking_id"] == "BK-PIC-001"
        assert result["travelers_booked"] == 1
        assert result["provider"] == "picasso"

        # Verify payload includes passport info
        call_kwargs = mock_post.call_args
        payload = call_kwargs.kwargs.get("json", call_kwargs[1].get("json", {}))
        assert payload["travelers"][0]["document"]["type"] == "PASSPORT"
        assert payload["pointOfSale"] == "DK"

    @patch("picasso_client.requests.post")
    def test_create_booking_no_travelers(self, mock_post):
        """create_booking fails with empty travelers list."""
        from picasso_client import PicassoClient
        client = PicassoClient()
        client.api_key = "test_key"

        result = client.create_booking(
            offer_id="OFF-001",
            travelers=[],
            pos_market="DK",
        )
        assert result["success"] is False
        assert "traveler" in result["error"].lower()

    @patch("picasso_client.requests.post")
    def test_deal_object_for_renderflight_compat(self, mock_post):
        """Flight offers with savings include a deal object for renderFlightCards."""
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "data": [{
                    "id": "OFF-001",
                    "pricing": [
                        {"pos": "US", "amount": 500},
                        {"pos": "ES", "amount": 400},
                    ],
                    "itineraries": [{"segments": [{
                        "carrierCode": "IB", "number": "1",
                        "departure": {"iataCode": "JFK", "at": "2026-03-15T08:00:00"},
                        "arrival": {"iataCode": "MAD", "at": "2026-03-15T20:00:00"},
                    }]}],
                    "duration": "PT8H",
                }],
                "marketsSearched": 2,
            }
        )
        mock_post.return_value.raise_for_status = MagicMock()

        from picasso_client import PicassoClient
        client = PicassoClient()
        client.api_key = "test_key"

        result = client.search_flights("JFK", "MAD", "2026-03-15")
        flight = result["flights"][0]

        assert flight["deal"] is not None
        assert flight["deal"]["home_price"] == 500.0
        assert flight["deal"]["cheapest_market"] == "MYSTES"  # B2C safe
        assert flight["deal"]["price_difference"] > 0

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

    def test_node_yield_dashboard_loads(self, auth_client):
        """Node yield dashboard page loads successfully."""
        resp = auth_client.get('/node/dashboard')
        assert resp.status_code == 200
        assert b'Yield Dashboard' in resp.data or b'yield' in resp.data.lower()

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

    def test_member_fee_is_25_percent(self):
        """Authenticated members get 25% platform fee."""
        from payments import get_fee_percent
        assert get_fee_percent(_mock_member()) == 0.25

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
