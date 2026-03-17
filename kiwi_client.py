"""
Kiwi Tequila Flight API Client for MYSTES

Virtual interlining across 750+ carriers (airlines, buses, trains, ferries)
via Kiwi.com's Tequila aggregation API. Finds routes that traditional GDS
systems cannot construct — connecting carriers that don't normally interline.

Kiwi Tequila API:
    Base URL: https://tequila-api.kiwi.com
    Auth: API key header (apikey: YOUR_KEY)
    Pricing: Free search, commission on bookings
    Coverage: 750+ carriers including 150+ ground transport

Usage:
    from kiwi_client import KiwiClient, search_with_kiwi

    result = search_with_kiwi("JFK", "LAX", "2026-04-15")
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

KIWI_BASE_URL = "https://tequila-api.kiwi.com"

CABIN_MAP = {
    "economy": "M",
    "premium_economy": "W",
    "premium economy": "W",
    "business": "C",
    "first": "F",
}

CABIN_DISPLAY = {
    "M": "economy",
    "W": "premium_economy",
    "C": "business",
    "F": "first",
}


class KiwiClient:
    """
    Kiwi Tequila Flight API client.

    Simple API key auth — no session management, no token refresh.
    Key obtained from Kiwi Tequila portal (invitation-based partnership).
    """

    def __init__(self, api_key: Optional[str] = None):
        import requests
        self._key = api_key or os.environ.get("KIWI_API_KEY", "")
        self._session = requests.Session()
        self._session.headers.update({
            "apikey": self._key,
            "Accept": "application/json",
        })

    def is_configured(self) -> bool:
        """Check if Kiwi API key is set."""
        return bool(self._key) and len(self._key) >= 10

    def _url(self, path: str) -> str:
        return f"{KIWI_BASE_URL}{path}"

    def _request(self, method: str, path: str, params: dict = None,
                 json_data: dict = None, timeout: int = 60) -> dict:
        """Make an authenticated request to Kiwi Tequila API."""
        try:
            resp = self._session.request(
                method,
                self._url(path),
                params=params,
                json=json_data,
                timeout=timeout,
            )
            if resp.status_code >= 400:
                error_msg = resp.text[:500] if resp.text else f"HTTP {resp.status_code}"
                logger.error("Kiwi API error %d: %s", resp.status_code, error_msg)
                return {"success": False, "error": error_msg, "status": resp.status_code}
            return {"success": True, "data": resp.json()}
        except Exception as e:
            logger.error("Kiwi request failed: %s", str(e))
            return {"success": False, "error": str(e)}

    # =========================================================================
    # LOCATION SEARCH
    # =========================================================================

    def search_locations(self, query: str, location_types: str = "airport,city") -> dict:
        """
        Search for airports/cities by name.

        Args:
            query: Search term (e.g. "New York", "JFK")
            location_types: Comma-separated types: airport, city, country

        Returns:
            dict with locations list
        """
        result = self._request("GET", "/locations/query", params={
            "term": query,
            "location_types": location_types,
            "limit": 10,
        })
        if not result["success"]:
            return result

        locations = result["data"].get("locations", [])
        return {
            "success": True,
            "locations": [
                {
                    "id": loc.get("id", ""),
                    "name": loc.get("name", ""),
                    "code": loc.get("code", loc.get("id", "")),
                    "city": loc.get("city", {}).get("name", "") if loc.get("city") else "",
                    "country": loc.get("country", {}).get("name", ""),
                    "type": loc.get("type", ""),
                }
                for loc in locations
            ],
        }

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
        max_stopovers: Optional[int] = None,
        currency: str = "USD",
        sort: str = "price",
        limit: int = 50,
    ) -> dict:
        """
        Search for flights via Kiwi Tequila API.

        Args:
            origin: IATA airport code (e.g. "JFK")
            destination: IATA airport code (e.g. "LAX")
            departure_date: "YYYY-MM-DD" (converted to DD/MM/YYYY for Kiwi)
            return_date: "YYYY-MM-DD" (optional, for round-trip)
            passengers: Number of adult passengers
            cabin_class: economy, premium_economy, business, first
            max_stopovers: Max number of stops (0=direct only)
            currency: Currency code for prices (default USD)
            sort: Sort order: price, quality, date, duration
            limit: Max results to return

        Returns:
            dict with success, flights list, search_id
        """
        # Convert YYYY-MM-DD to DD/MM/YYYY (Kiwi format)
        dep_kiwi = self._to_kiwi_date(departure_date)

        params = {
            "fly_from": origin.upper(),
            "fly_to": destination.upper(),
            "date_from": dep_kiwi,
            "date_to": dep_kiwi,
            "adults": passengers,
            "curr": currency,
            "sort": sort,
            "limit": limit,
            "vehicle_type": "aircraft",  # flights only, no buses/trains
        }

        cabin = CABIN_MAP.get(cabin_class.lower(), "M")
        params["selected_cabins"] = cabin

        if return_date:
            ret_kiwi = self._to_kiwi_date(return_date)
            params["return_from"] = ret_kiwi
            params["return_to"] = ret_kiwi
            params["flight_type"] = "round"
        else:
            params["flight_type"] = "oneway"

        if max_stopovers is not None:
            params["max_stopovers"] = max_stopovers

        result = self._request("GET", "/v2/search", params=params, timeout=90)

        if not result["success"]:
            return result

        data = result["data"]
        search_id = data.get("search_id", "")
        raw_flights = data.get("data", [])

        flights = []
        for item in raw_flights:
            flight = self._parse_itinerary(item)
            if flight:
                flights.append(flight)

        return {
            "success": True,
            "flights": flights,
            "search_id": search_id,
            "total_results": data.get("_results", len(flights)),
            "currency": data.get("currency", currency),
            "source": "kiwi_tequila",
        }

    def _parse_itinerary(self, item: dict) -> Optional[dict]:
        """Parse a Kiwi itinerary into a normalized flight dict."""
        try:
            route = item.get("route", [])
            if not route:
                return None

            # Filter to outbound segments only (return=0)
            outbound_segments = [s for s in route if s.get("return", 0) == 0]
            if not outbound_segments:
                outbound_segments = route  # fallback

            first_seg = outbound_segments[0]
            last_seg = outbound_segments[-1]

            # Airlines — Kiwi returns list of airline codes
            airlines = item.get("airlines", item.get("airline", []))
            if isinstance(airlines, str):
                airlines = [airlines]
            primary_airline = airlines[0] if airlines else ""

            # Departure/arrival times
            dep_time = first_seg.get("local_departure", "")
            arr_time = last_seg.get("local_arrival", "")

            # Duration in seconds → human readable
            duration_secs = item.get("duration", {}).get("departure", 0)
            if not duration_secs and dep_time and arr_time:
                try:
                    dep_dt = datetime.fromisoformat(dep_time.replace("Z", "+00:00"))
                    arr_dt = datetime.fromisoformat(arr_time.replace("Z", "+00:00"))
                    duration_secs = int((arr_dt - dep_dt).total_seconds())
                except (ValueError, TypeError):
                    pass

            hours, remainder = divmod(max(0, duration_secs), 3600)
            minutes = remainder // 60
            duration_str = f"{hours}h {minutes}m"

            # Build segment details
            segment_details = []
            for seg in outbound_segments:
                segment_details.append({
                    "flight_number": f"{seg.get('airline', '')}{seg.get('flight_no', '')}",
                    "aircraft": seg.get("equipment", ""),
                    "origin": seg.get("flyFrom", ""),
                    "destination": seg.get("flyTo", ""),
                    "departing_at": seg.get("local_departure", ""),
                    "arriving_at": seg.get("local_arrival", ""),
                    "operating_carrier": seg.get("operating_carrier", seg.get("airline", "")),
                    "cabin_class": CABIN_DISPLAY.get(
                        seg.get("cabin_class", "M"), "economy"
                    ) if seg.get("cabin_class") else "",
                })

            # Baggage info
            bags_price = item.get("bags_price", {})
            baglimit = item.get("baglimit", {})
            baggages = []
            if baglimit.get("hand_weight"):
                baggages.append({
                    "type": "carry_on",
                    "quantity": 1,
                    "weight_kg": baglimit.get("hand_weight", 0),
                })
            for bag_num in ["1", "2"]:
                if bag_num in bags_price:
                    baggages.append({
                        "type": f"checked_{bag_num}",
                        "quantity": 1,
                        "price": bags_price[bag_num],
                    })

            # Return slice for round trips
            return_segments = [s for s in route if s.get("return", 0) == 1]
            return_slice = None
            if return_segments:
                ret_first = return_segments[0]
                ret_last = return_segments[-1]
                return_slice = {
                    "origin": ret_first.get("flyFrom", ""),
                    "destination": ret_last.get("flyTo", ""),
                    "departure_time": ret_first.get("local_departure", ""),
                    "arrival_time": ret_last.get("local_arrival", ""),
                    "stops": len(return_segments) - 1,
                    "airline": ret_first.get("airline", ""),
                }

            return {
                "kiwi_id": item.get("id", ""),
                "booking_token": item.get("booking_token", ""),
                "deep_link": item.get("deep_link", ""),
                "airline": primary_airline,
                "airline_code": primary_airline,
                "airline_logo": "",
                "airlines": airlines,
                "operating_airline": first_seg.get(
                    "operating_carrier", primary_airline
                ),
                "origin": item.get("flyFrom", first_seg.get("flyFrom", "")),
                "origin_name": item.get("cityFrom", ""),
                "destination": item.get("flyTo", last_seg.get("flyTo", "")),
                "destination_name": item.get("cityTo", ""),
                "departure_time": dep_time,
                "arrival_time": arr_time,
                "duration": duration_str,
                "stops": len(outbound_segments) - 1,
                "price": str(item.get("price", "0")),
                "currency": "USD",  # set by search params
                "cabin_class": CABIN_DISPLAY.get(
                    item.get("cabin_class", "M"), "economy"
                ) if item.get("cabin_class") else "economy",
                "segments": segment_details,
                "baggages": baggages,
                "availability": item.get("availability", {}).get("seats"),
                "source": "kiwi_tequila",
                "virtual_interlining": item.get("virtual_interlining", False),
                "bags_recheck_required": any(
                    s.get("bags_recheck_required", False) for s in route
                ),
                "return_slice": return_slice,
            }
        except Exception as e:
            logger.warning("Failed to parse Kiwi itinerary: %s", str(e))
            return None

    # =========================================================================
    # BOOKING FLOW
    # =========================================================================

    def check_flights(self, booking_token: str, bags: int = 0,
                      adults: int = 1, children: int = 0,
                      infants: int = 0) -> dict:
        """
        Phase 1: Validate flight availability and current price.

        Must be called within 30 minutes of search.

        Args:
            booking_token: Token from search results
            bags: Number of checked bags
            adults/children/infants: Passenger counts

        Returns:
            dict with flights_checked, price_change, session_id
        """
        params = {
            "booking_token": booking_token,
            "bnum": bags,
            "adults": adults,
            "children": children,
            "infants": infants,
            "currency": "USD",
        }
        return self._request("GET", "/v2/booking/check_flights", params=params)

    def save_booking(
        self,
        booking_token: str,
        session_id: str,
        passengers: List[dict],
        bags: int = 0,
    ) -> dict:
        """
        Phase 2: Create the booking with passenger details.

        Args:
            booking_token: Token from search
            session_id: Session ID from check_flights
            passengers: List of dicts with:
                - name, surname, birthday (DD/MM/YYYY), nationality
                - category: "adult"/"child"/"infant"
                - email, phone
                - cardno (passport number), expiration (DD/MM/YYYY)
            bags: Number of checked bags

        Returns:
            dict with booking_id, transaction_id, status
        """
        body = {
            "booking_token": booking_token,
            "session_id": session_id,
            "passengers": passengers,
            "bags": bags,
            "lang": "en",
            "currency": "USD",
        }
        return self._request("POST", "/v2/booking/save_booking", json_data=body)

    def confirm_payment(self, booking_id: int, transaction_id: str) -> dict:
        """
        Phase 3: Confirm payment was processed.

        Must be called within 30 minutes of save_booking.

        Args:
            booking_id: ID from save_booking response
            transaction_id: Transaction ID from save_booking response

        Returns:
            dict with status (0=success, 1=payment failed, -1=timeout)
        """
        body = {
            "booking_id": booking_id,
            "transaction_id": transaction_id,
        }
        return self._request("POST", "/v2/booking/confirm_payment", json_data=body)

    # =========================================================================
    # HELPERS
    # =========================================================================

    @staticmethod
    def _to_kiwi_date(date_str: str) -> str:
        """Convert YYYY-MM-DD to DD/MM/YYYY (Kiwi format)."""
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            return dt.strftime("%d/%m/%Y")
        except (ValueError, TypeError):
            return date_str


# =============================================================================
# CONVENIENCE FUNCTION (matches picasso_client / duffel_client pattern)
# =============================================================================

def search_with_kiwi(
    origin: str,
    destination: str,
    departure_date: str,
    return_date: Optional[str] = None,
    passengers: int = 1,
    cabin_class: str = "economy",
    max_connections: Optional[int] = None,
) -> dict:
    """
    Search flights via Kiwi Tequila API.

    Convenience wrapper matching the picasso_client / duffel_client interface.
    Returns normalized flight data.
    """
    client = KiwiClient()
    if not client.is_configured():
        return {
            "success": False,
            "error": "Kiwi not configured — set KIWI_API_KEY in .env",
            "flights": [],
        }
    return client.search_flights(
        origin=origin,
        destination=destination,
        departure_date=departure_date,
        return_date=return_date,
        passengers=passengers,
        cabin_class=cabin_class,
        max_stopovers=max_connections,
    )
