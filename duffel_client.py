"""
Duffel NDC Flight API Client for MYSTES

Direct NDC connections to 300+ airlines via Duffel's unified API.
Complements Picasso (GDS/consolidator) with NDC-only fares that airlines
pull from traditional GDS channels.

Duffel API:
    Base URL: https://api.duffel.com
    Auth: Bearer token (Authorization header)
    Version: v2 (Duffel-Version header)
    Pricing: Free search, $3 + 1% per confirmed booking

Usage:
    from duffel_client import DuffelClient, search_with_duffel

    result = search_with_duffel("JFK", "LAX", "2026-04-15")
    if result["success"]:
        for flight in result["flights"]:
            print(flight["airline"], flight["price"], flight["currency"])
"""

import os
import logging
from datetime import datetime
from typing import List, Dict, Optional

from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger(__name__)

DUFFEL_BASE_URL = "https://api.duffel.com"

CABIN_MAP = {
    "economy": "economy",
    "premium_economy": "premium_economy",
    "premium economy": "premium_economy",
    "business": "business",
    "first": "first",
}


class DuffelClient:
    """
    Duffel NDC Flight API client.

    Simple Bearer token auth — no session management, no token refresh.
    Token is static until manually rotated in the Duffel dashboard.
    """

    def __init__(self, access_token: Optional[str] = None):
        import requests
        self._token = access_token or os.environ.get("DUFFEL_ACCESS_TOKEN", "")
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {self._token}",
            "Duffel-Version": "v2",
            "Accept": "application/json",
            "Content-Type": "application/json",
        })

    def is_configured(self) -> bool:
        """Check if Duffel token is set."""
        return bool(self._token) and len(self._token) >= 20

    def _url(self, path: str) -> str:
        return f"{DUFFEL_BASE_URL}{path}"

    def _request(self, method: str, path: str, json_data: dict = None,
                 params: dict = None, timeout: int = 60) -> dict:
        """Make an authenticated request to Duffel API."""
        try:
            resp = self._session.request(
                method,
                self._url(path),
                json=json_data,
                params=params,
                timeout=timeout,
            )
            if resp.status_code >= 400:
                error_body = resp.json() if resp.text else {}
                errors = error_body.get("errors", [])
                error_msg = errors[0].get("message", resp.text) if errors else resp.text
                logger.error("Duffel API error %d: %s", resp.status_code, error_msg)
                return {"success": False, "error": error_msg, "status": resp.status_code}
            return {"success": True, "data": resp.json().get("data", resp.json())}
        except Exception as e:
            logger.error("Duffel request failed: %s", str(e))
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
        passengers: int = 1,
        cabin_class: str = "economy",
        max_connections: Optional[int] = None,
    ) -> dict:
        """
        Search for flights via Duffel NDC API.

        Args:
            origin: IATA airport code (e.g. "JFK")
            destination: IATA airport code (e.g. "LAX")
            departure_date: "YYYY-MM-DD"
            return_date: "YYYY-MM-DD" (optional, for round-trip)
            passengers: Number of adult passengers
            cabin_class: economy, premium_economy, business, first
            max_connections: Max number of stops (0=direct only)

        Returns:
            dict with success, flights list, offer_request_id
        """
        slices = [
            {
                "origin": origin.upper(),
                "destination": destination.upper(),
                "departure_date": departure_date,
            }
        ]
        if return_date:
            slices.append({
                "origin": destination.upper(),
                "destination": origin.upper(),
                "departure_date": return_date,
            })

        if max_connections is not None:
            for s in slices:
                s["max_connections"] = max_connections

        pax = [{"type": "adult"} for _ in range(passengers)]
        cabin = CABIN_MAP.get(cabin_class.lower(), "economy")

        body = {
            "data": {
                "slices": slices,
                "passengers": pax,
                "cabin_class": cabin,
            }
        }

        result = self._request(
            "POST",
            "/air/offer_requests",
            json_data=body,
            params={"return_offers": "true", "supplier_timeout": "30000"},
            timeout=90,
        )

        if not result["success"]:
            return result

        data = result["data"]
        offer_request_id = data.get("id", "")
        offers = data.get("offers", [])

        flights = []
        for offer in offers:
            flight = self._parse_offer(offer)
            if flight:
                flights.append(flight)

        flights.sort(key=lambda f: float(f.get("price", 9999)))

        return {
            "success": True,
            "flights": flights,
            "offer_request_id": offer_request_id,
            "total_offers": len(offers),
            "source": "duffel_ndc",
        }

    def _parse_offer(self, offer: dict) -> Optional[dict]:
        """Parse a Duffel offer into a normalized flight dict."""
        try:
            slices = offer.get("slices", [])
            if not slices:
                return None

            outbound = slices[0]
            if outbound is None:
                return None
            segments = outbound.get("segments", [])
            if not segments:
                return None

            first_seg = segments[0]
            last_seg = segments[-1]

            marketing_carrier = first_seg.get("marketing_carrier", {})
            operating_carrier = first_seg.get("operating_carrier", {})

            dep_time = first_seg.get("departing_at", "")
            arr_time = last_seg.get("arriving_at", "")

            # Calculate duration
            duration_str = ""
            if dep_time and arr_time:
                try:
                    dep_dt = datetime.fromisoformat(dep_time)
                    arr_dt = datetime.fromisoformat(arr_time)
                    delta = arr_dt - dep_dt
                    hours, remainder = divmod(int(delta.total_seconds()), 3600)
                    minutes = remainder // 60
                    duration_str = f"{hours}h {minutes}m"
                except (ValueError, TypeError):
                    pass

            # Build segment details
            segment_details = []
            for seg in segments:
                segment_details.append({
                    "flight_number": (
                        seg.get("marketing_carrier", {}).get("iata_code", "") +
                        seg.get("marketing_carrier_flight_number", "")
                    ),
                    "aircraft": seg.get("aircraft", {}).get("name", ""),
                    "origin": seg.get("origin", {}).get("iata_code", ""),
                    "destination": seg.get("destination", {}).get("iata_code", ""),
                    "departing_at": seg.get("departing_at", ""),
                    "arriving_at": seg.get("arriving_at", ""),
                    "operating_carrier": seg.get("operating_carrier", {}).get("name", ""),
                    "cabin_class": seg.get("passengers", [{}])[0].get(
                        "cabin_class_marketing_name", ""
                    ),
                })

            # Baggage info
            bags = []
            for seg in segments:
                for pax in seg.get("passengers", []):
                    for bag in pax.get("baggages", []):
                        bags.append({
                            "type": bag.get("type", ""),
                            "quantity": bag.get("quantity", 0),
                        })

            origin_info = first_seg.get("origin", {})
            dest_info = last_seg.get("destination", {})

            return {
                "offer_id": offer.get("id", ""),
                "airline": marketing_carrier.get("name", "Unknown"),
                "airline_code": marketing_carrier.get("iata_code", ""),
                "airline_logo": marketing_carrier.get("logo_symbol_url", ""),
                "operating_airline": operating_carrier.get("name", ""),
                "origin": origin_info.get("iata_code", ""),
                "origin_name": origin_info.get("name", ""),
                "destination": dest_info.get("iata_code", ""),
                "destination_name": dest_info.get("name", ""),
                "departure_time": dep_time,
                "arrival_time": arr_time,
                "duration": duration_str,
                "stops": len(segments) - 1,
                "price": offer.get("total_amount", "0"),
                "currency": offer.get("total_currency", "USD"),
                "cabin_class": offer.get("cabin_class", "economy"),
                "segments": segment_details,
                "baggages": bags,
                "source": "duffel_ndc",
                "owner": offer.get("owner", {}).get("name", ""),
                "expires_at": offer.get("expires_at", ""),
                # Return slice for round trips
                "return_slice": (
                    self._parse_return_slice(slices[1])
                    if len(slices) > 1 and slices[1] is not None
                    else None
                ),
            }
        except Exception as e:
            logger.warning("Failed to parse Duffel offer: %s", str(e))
            return None

    def _parse_return_slice(self, slice_data: dict) -> Optional[dict]:
        """Parse return slice for round-trip flights."""
        segments = slice_data.get("segments", [])
        if not segments:
            return None
        first_seg = segments[0]
        last_seg = segments[-1]
        return {
            "origin": first_seg.get("origin", {}).get("iata_code", ""),
            "destination": last_seg.get("destination", {}).get("iata_code", ""),
            "departure_time": first_seg.get("departing_at", ""),
            "arrival_time": last_seg.get("arriving_at", ""),
            "stops": len(segments) - 1,
            "airline": first_seg.get("marketing_carrier", {}).get("name", ""),
        }

    # =========================================================================
    # OFFER DETAILS
    # =========================================================================

    def get_offer(self, offer_id: str) -> dict:
        """Get current offer details (price may have changed)."""
        return self._request("GET", f"/air/offers/{offer_id}")

    # =========================================================================
    # BOOKING
    # =========================================================================

    def create_order(
        self,
        offer_id: str,
        passengers: List[dict],
        payment_type: str = "balance",
        payment_amount: Optional[str] = None,
        payment_currency: Optional[str] = None,
    ) -> dict:
        """
        Book a flight by creating an order.

        Args:
            offer_id: The selected offer ID from search results
            passengers: List of passenger dicts with:
                - id: passenger ID from offer request
                - given_name, family_name, born_on, gender, title
                - email, phone_number
            payment_type: "balance" (Duffel balance) or "arc_bsp_cash" (IATA agent)
            payment_amount: Total amount (must match offer total)
            payment_currency: Currency code (must match offer currency)

        Returns:
            dict with booking_reference, order_id
        """
        # Get fresh offer to confirm current price
        offer_result = self.get_offer(offer_id)
        if not offer_result["success"]:
            return offer_result

        offer_data = offer_result["data"]
        amount = payment_amount or offer_data.get("total_amount", "")
        currency = payment_currency or offer_data.get("total_currency", "USD")

        body = {
            "data": {
                "selected_offers": [offer_id],
                "payments": [
                    {
                        "type": payment_type,
                        "amount": amount,
                        "currency": currency,
                    }
                ],
                "passengers": passengers,
            }
        }

        result = self._request("POST", "/air/orders", json_data=body)
        if not result["success"]:
            return result

        order = result["data"]
        return {
            "success": True,
            "order_id": order.get("id", ""),
            "booking_reference": order.get("booking_reference", ""),
            "status": order.get("status", ""),
            "total_amount": order.get("total_amount", ""),
            "total_currency": order.get("total_currency", ""),
            "passengers": order.get("passengers", []),
            "slices": order.get("slices", []),
        }

    # =========================================================================
    # ORDER MANAGEMENT
    # =========================================================================

    def get_order(self, order_id: str) -> dict:
        """Get order details."""
        return self._request("GET", f"/air/orders/{order_id}")

    def cancel_order(self, order_id: str) -> dict:
        """Request cancellation for an order."""
        body = {"data": {"order_id": order_id}}
        result = self._request(
            "POST", "/air/order_cancellations", json_data=body
        )
        if not result["success"]:
            return result

        cancellation = result["data"]
        cancellation_id = cancellation.get("id", "")

        # Confirm the cancellation
        confirm_result = self._request(
            "POST", f"/air/order_cancellations/{cancellation_id}/actions/confirm"
        )
        return confirm_result

    # =========================================================================
    # SEAT MAPS
    # =========================================================================

    def get_seat_map(self, offer_id: str) -> dict:
        """Get seat map for an offer."""
        return self._request(
            "GET", "/air/seat_maps",
            params={"offer_id": offer_id}
        )

    # =========================================================================
    # REFERENCE DATA
    # =========================================================================

    def list_airlines(self, limit: int = 50) -> dict:
        """List airlines available through Duffel."""
        return self._request("GET", "/air/airlines", params={"limit": limit})

    def get_airline(self, airline_id: str) -> dict:
        """Get airline details by ID."""
        return self._request("GET", f"/air/airlines/{airline_id}")

    def list_airports(self, limit: int = 50) -> dict:
        """List airports."""
        return self._request("GET", "/air/airports", params={"limit": limit})

    def get_airport(self, airport_id: str) -> dict:
        """Get airport details by ID."""
        return self._request("GET", f"/air/airports/{airport_id}")

    def suggest_places(self, query: str) -> dict:
        """Autocomplete places (airports, cities)."""
        return self._request(
            "GET", "/places/suggestions",
            params={"query": query}
        )


# =============================================================================
# CONVENIENCE FUNCTION (matches picasso_client.search_with_picasso pattern)
# =============================================================================

def search_with_duffel(
    origin: str,
    destination: str,
    departure_date: str,
    return_date: Optional[str] = None,
    passengers: int = 1,
    cabin_class: str = "economy",
    max_connections: Optional[int] = None,
) -> dict:
    """
    Search flights via Duffel NDC API.

    Convenience wrapper matching the picasso_client.search_with_picasso interface.
    Returns normalized flight data.
    """
    client = DuffelClient()
    if not client.is_configured():
        return {
            "success": False,
            "error": "Duffel not configured — set DUFFEL_ACCESS_TOKEN in .env",
            "flights": [],
        }
    return client.search_flights(
        origin=origin,
        destination=destination,
        departure_date=departure_date,
        return_date=return_date,
        passengers=passengers,
        cabin_class=cabin_class,
        max_connections=max_connections,
    )
