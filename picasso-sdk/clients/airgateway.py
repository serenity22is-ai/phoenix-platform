"""
AirGateway NDC API Client — ANASTASiA SDK

NDC aggregator connected to 25+ airlines via direct NDC connections, plus
AERTiCKET consolidator content (102 POS, GDS fares). JSON REST API.

AirGateway API v1.2:
    Sandbox: https://api.airgateway.net/v1.2/
    Production: https://api.airgateway.com/v1.2/
    Auth: API key in Authorization header
    Docs: https://support.airgateway.com/
    Swagger: https://api.airgateway.net/v1.2/swagger-ui/
    Postman: https://github.com/AirGateway/postman-json-api

Connected airlines (confirmed): A3, AA, AF, AV, AY, BA, EK, IB, KL, LH, QF, SQ
Plus AERTiCKET GDS content (Amadeus, Sabre, Travelport).

Usage:
    from clients.airgateway import AirGatewayClient

    client = AirGatewayClient(api_key="your_key")
    result = client.search_flights("JFK", "LHR", "2026-04-15")

MYSTES KYRIOS LLC — Confidential.
"""

import logging
import os
import uuid
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger("picasso.airgateway")

SANDBOX_BASE = "https://api.airgateway.net/v1.2"
PRODUCTION_BASE = "https://api.airgateway.com/v1.2"

# Cabin class codes — AirGateway uses numeric codes
CABIN_MAP = {
    "economy": "7",
    "ECONOMY": "7",
    "premium_economy": "4",
    "PREMIUM_ECONOMY": "4",
    "business": "2",
    "BUSINESS": "2",
    "first": "1",
    "FIRST": "1",
}

CABIN_DISPLAY = {
    "7": "economy",
    "4": "premium_economy",
    "2": "business",
    "1": "first",
}


class AirGatewayClient:
    """
    AirGateway NDC API client for ANASTASiA.

    JSON REST API with API key auth. All endpoints use POST.
    10 NDC operations: AirShopping, OfferPrice, OrderCreate, OrderRetrieve,
    OrderCancel, OrderReshopRefund, OrderReshopReprice, SeatAvailability,
    ServiceList, AirDocIssue.

    Args:
        api_key: AirGateway API key (or set AIRGATEWAY_API_KEY env var).
        sandbox: Use sandbox environment (default True).
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        sandbox: bool = True,
    ):
        self._key = api_key or os.environ.get("AIRGATEWAY_API_KEY", "")
        self._base_url = SANDBOX_BASE if sandbox else PRODUCTION_BASE
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": self._key,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "AG-Consumer": "MYSTES",
        })

    def is_configured(self) -> bool:
        """Check if API key is set and looks valid."""
        return bool(self._key) and len(self._key) >= 10

    def _request(
        self,
        endpoint: str,
        body: dict,
        extra_headers: Optional[dict] = None,
        timeout: int = 90,
    ) -> dict:
        """Make a POST request to an AirGateway endpoint."""
        url = f"{self._base_url}/{endpoint}"
        headers = {}
        if extra_headers:
            headers.update(extra_headers)

        # Generate unique request/session IDs
        headers.setdefault("AG-Request-ID", str(uuid.uuid4()))
        headers.setdefault("AG-Session-ID", str(uuid.uuid4()))

        try:
            resp = self._session.post(
                url, json=body, headers=headers, timeout=timeout,
            )
            if resp.status_code >= 400:
                error_msg = resp.text[:500] if resp.text else f"HTTP {resp.status_code}"
                logger.error(
                    "AirGateway %d on %s: %s",
                    resp.status_code, endpoint, error_msg,
                )
                return {
                    "success": False,
                    "error": error_msg,
                    "status": resp.status_code,
                }
            return {"success": True, "data": resp.json()}
        except requests.exceptions.Timeout:
            logger.error("AirGateway request timed out: %s", endpoint)
            return {"success": False, "error": "Request timed out"}
        except Exception as e:
            logger.error("AirGateway request failed: %s", str(e))
            return {"success": False, "error": str(e)}

    # =========================================================================
    # FLIGHT SEARCH
    # =========================================================================

    def search_flights(
        self,
        origin: str,
        destination: str,
        departure_date: str,
        return_date: Optional[str] = None,
        adults: int = 1,
        children: int = 0,
        infants: int = 0,
        cabin_class: str = "economy",
        nonstop: bool = False,
        providers: str = "*",
        country: str = "US",
        currency: str = "USD",
        timeout_seconds: int = 60,
        max_per_provider: int = 30,
    ) -> dict:
        """
        Search for flights via AirGateway NDC.

        Args:
            origin: Origin IATA code (e.g., "JFK")
            destination: Destination IATA code (e.g., "LHR")
            departure_date: "YYYY-MM-DD"
            return_date: "YYYY-MM-DD" (optional for round-trip)
            adults: Number of adults
            children: Number of children (2-11)
            infants: Number of infants (<2)
            cabin_class: economy, premium_economy, business, first
            nonstop: Direct flights only
            providers: "*" for all airlines, or comma-separated IATA codes
            country: POS country code (enables arbitrage — e.g., "DK", "ES")
            currency: Currency code for prices
            timeout_seconds: Max time to wait for airline responses
            max_per_provider: Max offers per cabin per airline

        Returns:
            dict with success, flights list, shopping_response_id
        """
        # Build origin/destination list
        origin_dests = [{
            "departure": {
                "airportCode": origin.upper(),
                "date": departure_date,
            },
            "arrival": {
                "airportCode": destination.upper(),
            },
        }]

        if return_date:
            origin_dests.append({
                "departure": {
                    "airportCode": destination.upper(),
                    "date": return_date,
                },
                "arrival": {
                    "airportCode": origin.upper(),
                },
            })

        cabin = CABIN_MAP.get(cabin_class.lower(), "7")

        body = {
            "metadata": {
                "country": country.upper(),
                "currency": currency.upper(),
                "locale": "en_US",
            },
            "originDestinations": origin_dests,
            "preferences": {
                "cabin": [cabin],
                "nonStop": nonstop,
            },
            "travelers": {
                "adt": adults,
                "chd": children,
                "inf": infants,
            },
        }

        headers = {
            "AG-Providers": providers,
            "AG-Request-Timeout": str(timeout_seconds),
            "AG-Per-Provider-Limit": str(max_per_provider),
            "NDC-Method": "AirShopping",
        }

        result = self._request("AirShopping", body, extra_headers=headers)
        if not result["success"]:
            return result

        data = result["data"]
        flights = self._parse_shopping_response(data, currency)
        shopping_id = data.get("shoppingResponseID", data.get("id", ""))

        return {
            "success": True,
            "flights": flights,
            "shopping_response_id": shopping_id,
            "total_results": len(flights),
            "currency": currency,
            "source": "airgateway_ndc",
            "pos_country": country,
        }

    def _parse_shopping_response(self, data: dict, currency: str = "USD") -> list:
        """Parse AirGateway shopping response into normalized flight dicts."""
        flights = []
        offers = data.get("offers", data.get("data", []))
        if not isinstance(offers, list):
            return flights

        for offer in offers:
            try:
                flight = self._parse_offer(offer, currency)
                if flight:
                    flights.append(flight)
            except Exception as e:
                logger.warning("Failed to parse AirGateway offer: %s", str(e))
        return flights

    def _parse_offer(self, offer: dict, currency: str = "USD") -> Optional[dict]:
        """Parse a single offer into a normalized flight dict."""
        segments_data = offer.get("segments", offer.get("itinerary", []))
        if not segments_data:
            return None

        if isinstance(segments_data, list) and segments_data:
            first_seg = segments_data[0]
            last_seg = segments_data[-1]
        else:
            return None

        # Extract basic flight info
        origin = first_seg.get("origin", first_seg.get("departureAirport", ""))
        destination = last_seg.get("destination", last_seg.get("arrivalAirport", ""))
        dep_time = first_seg.get("departureTime", first_seg.get("departure", ""))
        arr_time = last_seg.get("arrivalTime", last_seg.get("arrival", ""))
        airline = offer.get("owner", offer.get("airline", first_seg.get("airline", "")))

        price = offer.get("totalPrice", offer.get("price", 0))
        if isinstance(price, dict):
            price = price.get("total", price.get("amount", 0))

        segments = []
        for seg in segments_data:
            segments.append({
                "flight_number": seg.get("flightNumber", ""),
                "origin": seg.get("origin", seg.get("departureAirport", "")),
                "destination": seg.get("destination", seg.get("arrivalAirport", "")),
                "departing_at": seg.get("departureTime", seg.get("departure", "")),
                "arriving_at": seg.get("arrivalTime", seg.get("arrival", "")),
                "operating_carrier": seg.get("operatingCarrier", seg.get("airline", "")),
                "marketing_carrier": seg.get("marketingCarrier", airline),
                "cabin": seg.get("cabin", ""),
                "aircraft": seg.get("aircraft", ""),
            })

        return {
            "offer_id": offer.get("offerID", offer.get("id", "")),
            "shopping_response_id": offer.get("shoppingResponseID", offer.get("responseID", "")),
            "airline": airline,
            "airline_code": airline,
            "origin": origin,
            "destination": destination,
            "departure_time": dep_time,
            "arrival_time": arr_time,
            "stops": max(0, len(segments_data) - 1),
            "price": str(price),
            "currency": currency,
            "cabin_class": offer.get("cabin", "economy"),
            "segments": segments,
            "source": "airgateway_ndc",
            "fare_basis": offer.get("fareBasisCode", ""),
            "booking_class": offer.get("bookingClass", ""),
        }

    # =========================================================================
    # OFFER PRICE VERIFICATION
    # =========================================================================

    def verify_price(self, shopping_response_id: str, offer_ids: list) -> dict:
        """
        Verify offer pricing before booking (OfferPrice).

        Args:
            shopping_response_id: From search results
            offer_ids: List of offer IDs to price

        Returns:
            dict with verified pricing
        """
        body = {
            "shoppingResponseID": shopping_response_id,
            "offerIDs": offer_ids,
        }
        return self._request("OfferPrice", body, extra_headers={
            "NDC-Method": "OfferPrice",
        })

    # =========================================================================
    # BOOKING
    # =========================================================================

    def create_order(
        self,
        shopping_response_id: str,
        passengers: list,
        payment_method: str = "cash",
    ) -> dict:
        """
        Create a booking (OrderCreate).

        Args:
            shopping_response_id: From search/price verification
            passengers: List of passenger dicts:
                - nameGiven: First name
                - surname: Last name
                - nameTitle: MR/MRS/MS/MISS
                - gender: Male/Female
                - birthdate: YYYY-MM-DD
                - passengerType: ADT/CHD/INF (CNN for child in some airlines)
                - emailContact: Email address
                - phone: Phone number with country code
                - travelerReference: T1/T2/T3
                Optional:
                - countryCode: Nationality
                - documentNumber: Passport number
                - documentExpiry: Passport expiry date
            payment_method: card, cash, or ms

        Returns:
            dict with order_id, booking_reference
        """
        body = {
            "shoppingResponseID": shopping_response_id,
            "passengers": passengers,
            "payment": {"method": payment_method},
        }
        return self._request("OrderCreate", body, extra_headers={
            "NDC-Method": "OrderCreate",
            "NDC-Payment-Method": payment_method,
        })

    def retrieve_order(self, order_id: str, owner: str = "") -> dict:
        """
        Retrieve an existing booking (OrderRetrieve).

        Args:
            order_id: AirGateway order ID
            owner: Airline owner code (optional)
        """
        body = {"id": order_id}
        if owner:
            body["owner"] = owner
        return self._request("OrderRetrieve", body, extra_headers={
            "NDC-Method": "OrderRetrieve",
        })

    def cancel_order(self, order_id: str, cancel_type: str = "void") -> dict:
        """
        Cancel a booking (OrderCancel).

        Args:
            order_id: AirGateway order ID
            cancel_type: "void" for void, "cancel" for cancellation
        """
        body = {"id": order_id, "type": cancel_type}
        return self._request("OrderCancel", body, extra_headers={
            "NDC-Method": "OrderCancel",
        })

    # =========================================================================
    # ORDER MANAGEMENT
    # =========================================================================

    def reshop_refund(self, order_id: str) -> dict:
        """Request refund quote for an order (OrderReshopRefund)."""
        body = {"id": order_id, "type": "refund"}
        return self._request("OrderReshopRefund", body, extra_headers={
            "NDC-Method": "OrderReshopRefund",
        })

    def reshop_reprice(self, order_id: str) -> dict:
        """Reprice a reshop option (OrderReshopReprice)."""
        body = {"id": order_id}
        return self._request("OrderReshopReprice", body, extra_headers={
            "NDC-Method": "OrderReshopReprice",
        })

    def get_seat_availability(self, order_id: str) -> dict:
        """Get available seats for an order (SeatAvailability)."""
        body = {"id": order_id}
        return self._request("SeatAvailability", body, extra_headers={
            "NDC-Method": "SeatAvailability",
            "NDC-Sub-Method": "preSeatAvailability",
        })

    def get_service_list(self, order_id: str) -> dict:
        """Get available ancillary services (ServiceList)."""
        body = {"id": order_id}
        return self._request("ServiceList", body, extra_headers={
            "NDC-Method": "ServiceList",
            "NDC-Sub-Method": "preServiceList",
        })

    def issue_ticket(self, order_id: str) -> dict:
        """Issue ticket for a booked order (AirDocIssue)."""
        body = {"id": order_id}
        return self._request("AirDocIssue", body, extra_headers={
            "NDC-Method": "AirDocIssue",
        })
