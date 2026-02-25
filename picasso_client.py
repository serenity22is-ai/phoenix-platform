"""
Picasso Travel / AERTiCKET Redbox API Client for MYSTES

Flight search via the Redbox API at aerpackit.flightconex.de.
Picasso is a 102-country POS consolidator with IATA subsidiaries in 25+ countries.

Replaces amadeus_client.py as the primary flight search engine.

Redbox API:
    Base URL: https://aerpackit.flightconex.de/redbox
    Auth: Session-based (redbox-session-token from Cockpit portal)
    Airport search: https://geo.direct-res.de/solr/select/ (public, no auth)

Usage:
    from picasso_client import PicassoClient, search_with_picasso

    result = search_with_picasso("JFK", "LHR", "2026-03-15", return_date="2026-03-22")
    if result["success"]:
        for flight in result["flights"]:
            print(flight["airline"], flight["price"], flight["duration"])
"""

import os
import re
import requests
from typing import List, Dict, Optional

from dotenv import load_dotenv
load_dotenv()

# Redbox API
REDBOX_BASE_URL = os.environ.get(
    "PICASSO_REDBOX_URL",
    "https://aerpackit.flightconex.de/redbox",
)

# Airport autocomplete (public Solr — no auth needed)
GEO_SOLR_URL = "https://geo.direct-res.de/solr/select/"

# Cabin class mapping
CABIN_MAP = {
    "economy": "ECONOMY",
    "premium_economy": "PREMIUM_ECONOMY",
    "premium economy": "PREMIUM_ECONOMY",
    "business": "BUSINESS",
    "first": "FIRST",
}


class PicassoClient:
    """
    Picasso Travel / AERTiCKET Redbox API client.

    Flight search via session-based auth against the Redbox backend.
    Session token is managed automatically by PicassoTokenManager
    (auto-login via Keycloak or headless browser, with fallback to manual token).
    """

    def __init__(self):
        from picasso_auth import token_manager
        self._token_manager = token_manager
        self.agency_id = os.environ.get("PICASSO_AGENCY_ID", "629818")
        self.branch = os.environ.get("PICASSO_BRANCH", "PICL_707")
        self._session = requests.Session()

    @property
    def session_token(self) -> str:
        """Dynamic property — always returns a fresh valid token."""
        return self._token_manager.get_token()

    def _api_url(self, endpoint: str) -> str:
        """Build full Redbox API URL with session token."""
        return f"{REDBOX_BASE_URL}/api/{self.session_token}/{endpoint}"

    def is_configured(self) -> bool:
        """Check if Picasso is configured (auto-login or manual token)."""
        token = self._token_manager.get_token()
        return bool(token) and len(token) >= 20

    # -------------------------------------------------------------------------
    # Airport Search (Public Solr — no auth needed)
    # -------------------------------------------------------------------------

    def search_airports(self, query: str, max_results: int = 10, language: str = "en") -> List[Dict]:
        """
        Search airports via the public Solr geo service.

        Returns list of airports with IATA codes, names, countries.
        No auth required — this is a public endpoint.
        """
        try:
            response = self._session.get(
                GEO_SOLR_URL,
                params={
                    "q": query,
                    "rows": max_results,
                    "wt": "json",
                },
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()
            docs = data.get("response", {}).get("docs", [])

            airports = []
            for doc in docs:
                poi_id = doc.get("POI_ID", "")
                doc_type = doc.get("TYPE", [])
                name = doc.get("NAME_EN", doc.get("NAME", ""))
                airport_name = doc.get("airporten_US_s", "")

                airports.append({
                    "code": poi_id,
                    "name": name,
                    "airport_name": airport_name,
                    "country": doc.get("COUNTRY", ""),
                    "country_name": doc.get("COUNTRY_EN", ""),
                    "type": doc_type[0] if doc_type else "unknown",
                    "is_multi": "multiairport" in doc_type if isinstance(doc_type, list) else False,
                })
            return airports
        except Exception as e:
            print(f"[PICASSO] Airport search error: {e}")
            return []

    # -------------------------------------------------------------------------
    # Flight Search
    # -------------------------------------------------------------------------

    def _is_auth_error(self, error_str: str) -> bool:
        """Detect if an error is authentication-related."""
        indicators = ["401", "403", "unauthorized", "forbidden", "session", "expired"]
        return any(ind in error_str.lower() for ind in indicators)

    def search_flights(
        self,
        origin: str,
        destination: str,
        departure_date: str,
        return_date: Optional[str] = None,
        adults: int = 1,
        children: int = 0,
        infants: int = 0,
        cabin_class: str = "ECONOMY",
        max_results: int = 20,
        nonstop_only: bool = False,
        fare_types: Optional[List[str]] = None,
    ) -> Dict:
        """Search flights with automatic retry on token expiration."""
        result = self._search_flights_inner(
            origin, destination, departure_date, return_date,
            adults, children, infants, cabin_class,
            max_results, nonstop_only, fare_types,
        )

        # If auth error, invalidate token and retry once
        if not result.get("success") and self._is_auth_error(result.get("error", "")):
            print("[PICASSO] Auth error detected — refreshing token and retrying...")
            self._token_manager.invalidate()
            result = self._search_flights_inner(
                origin, destination, departure_date, return_date,
                adults, children, infants, cabin_class,
                max_results, nonstop_only, fare_types,
            )

        return result

    def _search_flights_inner(
        self,
        origin: str,
        destination: str,
        departure_date: str,
        return_date: Optional[str] = None,
        adults: int = 1,
        children: int = 0,
        infants: int = 0,
        cabin_class: str = "ECONOMY",
        max_results: int = 20,
        nonstop_only: bool = False,
        fare_types: Optional[List[str]] = None,
    ) -> Dict:
        """
        Search flights via Redbox API (inner implementation).

        Args:
            origin: Origin IATA code (JFK, TYS, LAX)
            destination: Destination IATA code (LHR, NRT, CDG)
            departure_date: YYYY-MM-DD
            return_date: Optional return date for round-trip
            adults: Number of adult passengers
            children: Number of child passengers
            infants: Number of infant passengers
            cabin_class: ECONOMY, PREMIUM_ECONOMY, BUSINESS, FIRST
            max_results: Max results to return
            nonstop_only: Filter to non-stop only
            fare_types: Fare types to search (default: PUB + NET)

        Returns:
            Dict with success, flights, source, etc.
        """
        if not self.is_configured():
            return {
                "success": False,
                "flights": [],
                "error": "Picasso not configured (PICASSO_SESSION_TOKEN missing)",
                "source": "picasso",
            }

        # Build segment list
        segments = [
            {
                "departure": origin.upper(),
                "destination": destination.upper(),
                "departureDate": departure_date,
            }
        ]
        if return_date:
            segments.append({
                "departure": destination.upper(),
                "destination": origin.upper(),
                "departureDate": return_date,
            })

        # Build passenger list
        pax_list = []
        if adults > 0:
            pax_list.append({"type": "ADT", "count": adults})
        if children > 0:
            pax_list.append({"type": "CHD", "count": children})
        if infants > 0:
            pax_list.append({"type": "INF", "count": infants})

        # Cabin class
        cabin = CABIN_MAP.get(cabin_class.lower(), cabin_class.upper())

        # Fare types
        fares = fare_types or ["PUB", "NET"]

        payload = {
            "segmentList": segments,
            "passengerTypeCountList": pax_list,
            "cabinClassList": [cabin],
            "fareCharacteristicList": fares,
            "nonStopFlightsOnly": nonstop_only,
        }

        trip_desc = f"{origin}→{destination} on {departure_date}"
        if return_date:
            trip_desc += f" returning {return_date}"
        print(f"[PICASSO] Searching: {trip_desc}")

        # Step 1: Submit search
        try:
            response = self._session.post(
                self._api_url("availableFare"),
                json=payload,
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                timeout=30,
            )
            response.raise_for_status()
            search_data = response.json()
        except requests.exceptions.HTTPError as e:
            error = self._parse_redbox_error(e.response)
            print(f"[PICASSO] Search submit error: {error}")
            return {"success": False, "flights": [], "error": error, "source": "picasso"}
        except Exception as e:
            print(f"[PICASSO] Search submit error: {e}")
            return {"success": False, "flights": [], "error": str(e), "source": "picasso"}

        # Check for API errors
        if search_data.get("webServiceErrors"):
            errors = search_data["webServiceErrors"]
            error_msg = errors[0].get("description", "Unknown error")
            detail = errors[0].get("detailMessages", [""])[0] if errors[0].get("detailMessages") else ""
            print(f"[PICASSO] Search error: {error_msg} — {detail}")
            return {"success": False, "flights": [], "error": f"{error_msg}: {detail}", "source": "picasso"}

        fare_search_id = search_data.get("fareSearchId")
        num_results = search_data.get("numberOfResults", 0)
        num_airlines = search_data.get("numberOfAirlines", 0)

        if not fare_search_id or num_results == 0:
            print("[PICASSO] No results found")
            return {
                "success": False, "flights": [], "source": "picasso",
                "error": "No flights found for this route/date",
            }

        print(f"[PICASSO] Found {num_results} fares from {num_airlines} airlines")

        # Step 2: Fetch results (paginated)
        try:
            results_response = self._session.post(
                self._api_url(f"availableFare/{fare_search_id}"),
                json={"pageNumber": 1, "resultsPerPage": min(max_results, 50)},
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                timeout=30,
            )
            results_response.raise_for_status()
            results_data = results_response.json()
        except Exception as e:
            print(f"[PICASSO] Results fetch error: {e}")
            return {"success": False, "flights": [], "error": str(e), "source": "picasso"}

        currency = results_data.get("currencyIsoCode", "USD")
        raw_results = results_data.get("results", [])

        # Parse results
        flights = []
        for raw in raw_results:
            parsed = self._parse_redbox_result(raw, currency)
            if parsed:
                flights.append(parsed)

        # Sort by price
        flights.sort(key=lambda f: f.get("price", 99999))

        print(f"[PICASSO] Returning {len(flights)} flights")
        return {
            "success": len(flights) > 0,
            "flights": flights,
            "source": "picasso",
            "origin": origin.upper(),
            "destination": destination.upper(),
            "date": departure_date,
            "return_date": return_date,
            "total_results": num_results,
            "airlines_count": num_airlines,
            "currency": currency,
            "fare_search_id": fare_search_id,
        }

    def _parse_redbox_result(self, result: Dict, currency: str = "USD") -> Optional[Dict]:
        """Parse a single Redbox flight result into MYSTES format."""
        try:
            airline = result.get("validatingAirline", {})
            total = float(result.get("total", 0))
            total_tax = float(result.get("totalTax", 0))
            fare_id = result.get("fareId", "")
            gds = result.get("gds", "")

            # Price details
            price_details = result.get("priceDetails", [{}])[0] if result.get("priceDetails") else {}
            base_fare = float(price_details.get("gdsFarePerPax", 0))
            tax_per_pax = float(price_details.get("taxPerPax", 0))
            ticket_fee = float(price_details.get("ticketFeeDetails", {}).get("originalTicketFee", 0))

            # Fare family
            fare_families = result.get("fareFamilies", [])
            fare_family_name = fare_families[0].get("airlineName", "") if fare_families else ""

            # Fare characteristics
            fare_chars = result.get("fareCharacteristicList", [])

            # Additional fare info
            additional = result.get("additionalFareInfos", [])
            baggage_info = None
            is_cheapest = False
            for info in additional:
                if info.get("type") == "baggageInfo":
                    baggage_info = info.get("weightInfo", "")
                if info.get("type") == "cheapestFare":
                    is_cheapest = True

            # Parse legs
            legs = []
            all_segments = []
            for leg_data in result.get("legList", []):
                leg = self._parse_leg(leg_data)
                legs.append(leg)
                all_segments.extend(leg.get("segments", []))

            # Primary leg info (outbound)
            outbound = legs[0] if legs else {}
            inbound = legs[1] if len(legs) > 1 else None

            return {
                # Identity
                "offer_id": fare_id,
                "fare_id": fare_id,
                "source": "picasso",
                "gds": gds,

                # Carrier
                "airline": airline.get("code", ""),
                "airline_name": airline.get("name", ""),
                "airline_icao": airline.get("icao", ""),

                # Route (outbound)
                "origin": outbound.get("departure_code", ""),
                "destination": outbound.get("destination_code", ""),
                "departure_time": outbound.get("departure_time", ""),
                "arrival_time": outbound.get("arrival_time", ""),

                # Duration
                "duration": outbound.get("total_travel_time", ""),
                "duration_minutes": self._parse_iso_duration(outbound.get("total_travel_time", "")),
                "duration_formatted": self._format_iso_duration(outbound.get("total_travel_time", "")),
                "stops": outbound.get("stop_count", 0),
                "stop_airports": outbound.get("stop_codes", []),

                # Return leg
                "return_departure_time": inbound.get("departure_time", "") if inbound else None,
                "return_arrival_time": inbound.get("arrival_time", "") if inbound else None,
                "return_duration": inbound.get("total_travel_time", "") if inbound else None,
                "return_stops": inbound.get("stop_count", 0) if inbound else None,

                # Legs and segments
                "legs": legs,
                "segments": all_segments,

                # Cabin and fare
                "cabin_class": result.get("cabinClassList", ["ECONOMY"])[0],
                "fare_family": fare_family_name,
                "fare_type": fare_chars[0] if fare_chars else "PUB",
                "baggage_info": baggage_info,
                "is_cheapest": is_cheapest,

                # Pricing
                "price": total,
                "total": total,
                "base_fare": base_fare,
                "tax": total_tax,
                "ticket_fee": ticket_fee,
                "currency": currency,

                # For MYSTES display compatibility
                "mystes_price": total,
                "deal": None,
            }

        except Exception as e:
            print(f"[PICASSO] Error parsing result: {e}")
            return None

    def _parse_leg(self, leg_data: Dict) -> Dict:
        """Parse a leg (outbound or inbound) from Redbox result."""
        departure = leg_data.get("departure", {})
        destination = leg_data.get("destination", {})
        stops = leg_data.get("stops", [])

        segments = []
        for itin in leg_data.get("itineraryList", []):
            for seg_data in itin.get("segmentList", []):
                seg = self._parse_segment(seg_data)
                segments.append(seg)

        return {
            "departure_code": departure.get("code", ""),
            "departure_name": departure.get("name", ""),
            "destination_code": destination.get("code", ""),
            "destination_name": destination.get("name", ""),
            "departure_time": leg_data.get("departureTimestamp", ""),
            "arrival_time": leg_data.get("arrivalTimestamp", ""),
            "total_travel_time": leg_data.get("totalTravelTime", ""),
            "total_transfer_time": leg_data.get("totalTransferTime", ""),
            "stop_count": len(stops),
            "stop_codes": [s.get("code", "") for s in stops],
            "stop_names": [s.get("name", "") for s in stops],
            "segments": segments,
        }

    def _parse_segment(self, seg: Dict) -> Dict:
        """Parse a single flight segment."""
        dep = seg.get("departure", {})
        dest = seg.get("destination", {})
        marketing = seg.get("marketingAirline", {})
        operating = seg.get("operatingAirline", marketing)
        booking = seg.get("bookingClass", {})

        flight_num = seg.get("flightNumber", "")
        carrier_code = marketing.get("code", "")
        full_flight = f"{carrier_code}{flight_num}" if carrier_code and flight_num else ""

        return {
            "carrier": carrier_code,
            "carrier_name": marketing.get("name", ""),
            "carrier_icao": marketing.get("icao", ""),
            "flight_number": full_flight,
            "flight_num_raw": flight_num,
            "departure_airport": dep.get("code", ""),
            "departure_name": dep.get("name", ""),
            "departure_time": seg.get("departureTimestamp", ""),
            "arrival_airport": dest.get("code", ""),
            "arrival_name": dest.get("name", ""),
            "cabin_class": seg.get("cabinClass", "ECONOMY"),
            "booking_class": booking.get("code", ""),
            "fare_base": seg.get("fareBase", ""),
            "fare_family": seg.get("fareFamily", {}).get("airlineName", ""),
            "ground_time": seg.get("groundTime", ""),
            "operating_carrier": operating.get("code", carrier_code),
            "is_codeshare": operating.get("code", carrier_code) != carrier_code,
        }

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _parse_redbox_error(self, response) -> str:
        """Extract error message from Redbox API response."""
        try:
            data = response.json()
            if "webServiceErrors" in data:
                errors = data["webServiceErrors"]
                if errors:
                    desc = errors[0].get("description", "")
                    detail = errors[0].get("detailMessages", [""])[0] if errors[0].get("detailMessages") else ""
                    return f"{desc}: {detail}" if detail else desc
            if "detail" in data:
                return data["detail"]
            return f"HTTP {response.status_code}"
        except Exception:
            return f"HTTP {response.status_code}"

    def _parse_iso_duration(self, duration: str) -> int:
        """Parse ISO 8601 duration (PT10H25M) to minutes."""
        if not duration:
            return 0
        match = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?', duration)
        if match:
            hours = int(match.group(1) or 0)
            minutes = int(match.group(2) or 0)
            return hours * 60 + minutes
        return 0

    def _format_iso_duration(self, duration: str) -> str:
        """Format ISO 8601 duration (PT10H25M) to 'Xh Ym'."""
        minutes = self._parse_iso_duration(duration)
        if minutes <= 0:
            return ""
        h, m = divmod(minutes, 60)
        if h and m:
            return f"{h}h {m}m"
        elif h:
            return f"{h}h"
        return f"{m}m"


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------

_client: Optional[PicassoClient] = None


def _get_client() -> PicassoClient:
    global _client
    if _client is None:
        _client = PicassoClient()
    return _client


def search_airports(query: str, max_results: int = 10) -> List[Dict]:
    """Search airports via public Solr geo service (no auth needed)."""
    return _get_client().search_airports(query, max_results)


def search_flights_multi_pos(
    origin: str,
    destination: str,
    departure_date: str,
    return_date: Optional[str] = None,
    adults: int = 1,
    cabin_class: str = "economy",
    max_results: int = 20,
    nonstop_only: bool = False,
) -> Dict:
    """
    Module-level convenience — search flights via Redbox.

    Drop-in replacement for amadeus_client.search_with_amadeus().
    """
    mapped_cabin = CABIN_MAP.get(cabin_class.lower(), "ECONOMY")

    return _get_client().search_flights(
        origin=origin,
        destination=destination,
        departure_date=departure_date,
        return_date=return_date,
        adults=adults,
        cabin_class=mapped_cabin,
        max_results=max_results,
        nonstop_only=nonstop_only,
    )


def search_with_picasso(
    origin: str,
    destination: str,
    departure_date: str,
    return_date: Optional[str] = None,
    adults: int = 1,
    cabin_class: str = "economy",
) -> Dict:
    """Alias — same interface for backward compatibility."""
    return search_flights_multi_pos(
        origin=origin,
        destination=destination,
        departure_date=departure_date,
        return_date=return_date,
        adults=adults,
        cabin_class=cabin_class,
    )
