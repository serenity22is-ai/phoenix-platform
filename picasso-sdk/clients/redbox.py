"""
Picasso Travel / AERTiCKET Redbox API Client

Full-featured Python SDK for the Redbox flight booking API at aerpackit.flightconex.de.
Picasso is a 102-country POS consolidator with IATA subsidiaries in 25+ countries.

Redbox API:
    Base URL: https://aerpackit.flightconex.de/redbox
    Auth: Session-based (redbox-session-token from Cockpit portal)
    Airport search: https://geo.direct-res.de/solr/select/ (public, no auth)

Usage:
    from picasso import RedboxClient

    client = RedboxClient(
        agency_id="YOUR_AGENCY_ID",
        branch="YOUR_BRANCH",
    )
    result = client.search_flights("JFK", "LHR", "2026-03-15", return_date="2026-03-22")
    if result["success"]:
        for flight in result["flights"]:
            print(flight["airline"], flight["price"], flight["duration_formatted"])
"""

import logging
import os
import re

import requests
from typing import List, Dict, Optional, Callable

logger = logging.getLogger("picasso.client")

# Redbox API base URL
DEFAULT_REDBOX_URL = "https://aerpackit.flightconex.de/redbox"

# Airport autocomplete (public Solr — no auth needed)
GEO_SOLR_URL = "https://geo.direct-res.de/solr/select/"

# Cabin class mapping (user-friendly → Redbox enum)
CABIN_MAP = {
    "economy": "ECONOMY",
    "premium_economy": "PREMIUM_ECONOMY",
    "premium economy": "PREMIUM_ECONOMY",
    "business": "BUSINESS",
    "first": "FIRST",
}


class RedboxClient:
    """
    Picasso Travel / AERTiCKET Redbox API client.

    Provides access to all 12 Redbox API endpoints:
    - Flight search (availableFare)
    - Fare rules
    - Seatmaps
    - Shopping cart (CRUD + addAndCheckOut)
    - Booking (superPNR create + search)
    - Documents (itinerary, offer, confirmation)
    - Traveler profiles
    - Session configuration

    Auth is session-based via a redbox-session-token cookie.
    Provide a token directly, via environment variable, or via a TokenManager.

    Args:
        agency_id: Your Picasso agency ID (required).
        branch: Your Picasso branch code (required).
        session_token: Static session token string.
        token_provider: Callable that returns a fresh token (e.g., TokenManager.get_token).
            Takes precedence over session_token if both are provided.
        base_url: Redbox API base URL. Defaults to production.
    """

    def __init__(
        self,
        agency_id: str,
        branch: str,
        session_token: Optional[str] = None,
        token_provider: Optional[Callable[[], str]] = None,
        base_url: Optional[str] = None,
    ):
        self.agency_id = agency_id
        self.branch = branch
        self._static_token = session_token or os.environ.get("PICASSO_SESSION_TOKEN", "")
        self._token_provider = token_provider
        self._base_url = base_url or os.environ.get("PICASSO_REDBOX_URL", DEFAULT_REDBOX_URL)
        self._session = requests.Session()

    @property
    def session_token(self) -> str:
        """Return a valid session token (dynamic provider preferred over static)."""
        if self._token_provider:
            return self._token_provider()
        return self._static_token

    def _api_url(self, endpoint: str) -> str:
        """Build full Redbox API URL with session token."""
        return f"{self._base_url}/api/{self.session_token}/{endpoint}"

    def is_configured(self) -> bool:
        """Check if a valid session token is available."""
        token = self.session_token
        return bool(token) and len(token) >= 20

    def invalidate_token(self):
        """Signal the token provider to refresh (no-op for static tokens)."""
        if self._token_provider and hasattr(self._token_provider, '__self__'):
            manager = self._token_provider.__self__
            if hasattr(manager, 'invalidate'):
                manager.invalidate()

    # -------------------------------------------------------------------------
    # Airport Search (Public Solr — no auth needed)
    # -------------------------------------------------------------------------

    def search_airports(self, query: str, max_results: int = 10) -> List[Dict]:
        """
        Search airports via the public Solr geo service.

        No Redbox auth required — this is a public endpoint.

        Args:
            query: Airport name, city, or IATA code to search for.
            max_results: Maximum number of results to return.

        Returns:
            List of airport dicts with keys: code, name, airport_name,
            country, country_name, type, is_multi.
        """
        try:
            response = self._session.get(
                GEO_SOLR_URL,
                params={"q": query, "rows": max_results, "wt": "json"},
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
            logger.error(f"Airport search error: {e}")
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
        """
        Search flights with automatic retry on token expiration.

        Args:
            origin: Origin IATA code (JFK, LAX, TYS).
            destination: Destination IATA code (LHR, NRT, CDG).
            departure_date: Date in YYYY-MM-DD format.
            return_date: Optional return date for round-trip searches.
            adults: Number of adult passengers (ADT).
            children: Number of child passengers (CHD).
            infants: Number of infant passengers (INF).
            cabin_class: ECONOMY, PREMIUM_ECONOMY, BUSINESS, or FIRST.
            max_results: Maximum results per page (capped at 50).
            nonstop_only: If True, only return non-stop flights.
            fare_types: Fare types to search. Default: ["PUB", "NET"].

        Returns:
            Dict with keys: success, flights, source, origin, destination,
            date, return_date, total_results, airlines_count, currency,
            fare_search_id. On failure: success=False with error message.
        """
        result = self._search_flights_inner(
            origin, destination, departure_date, return_date,
            adults, children, infants, cabin_class,
            max_results, nonstop_only, fare_types,
        )

        # If auth error, invalidate token and retry once
        if not result.get("success") and self._is_auth_error(result.get("error", "")):
            logger.info("Auth error detected — refreshing token and retrying")
            self.invalidate_token()
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
        """Inner search implementation (no retry logic)."""
        if not self.is_configured():
            return {
                "success": False,
                "flights": [],
                "error": "Not configured — no session token available",
                "source": "redbox",
            }

        # Build segment list
        segments = [{
            "departure": origin.upper(),
            "destination": destination.upper(),
            "departureDate": departure_date,
        }]
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

        # Normalize cabin class
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

        trip_desc = f"{origin}\u2192{destination} on {departure_date}"
        if return_date:
            trip_desc += f" returning {return_date}"
        logger.info(f"Searching: {trip_desc}")

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
            logger.error(f"Search submit error: {error}")
            return {"success": False, "flights": [], "error": error, "source": "redbox"}
        except Exception as e:
            logger.error(f"Search submit error: {e}")
            return {"success": False, "flights": [], "error": str(e), "source": "redbox"}

        # Check for API errors
        if search_data.get("webServiceErrors"):
            errors = search_data["webServiceErrors"]
            error_msg = errors[0].get("description", "Unknown error")
            detail = errors[0].get("detailMessages", [""])[0] if errors[0].get("detailMessages") else ""
            logger.error(f"Search error: {error_msg} \u2014 {detail}")
            return {"success": False, "flights": [], "error": f"{error_msg}: {detail}", "source": "redbox"}

        fare_search_id = search_data.get("fareSearchId")
        num_results = search_data.get("numberOfResults", 0)
        num_airlines = search_data.get("numberOfAirlines", 0)

        if not fare_search_id or num_results == 0:
            logger.info("No results found")
            return {
                "success": False, "flights": [], "source": "redbox",
                "error": "No flights found for this route/date",
            }

        logger.info(f"Found {num_results} fares from {num_airlines} airlines")

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
            logger.error(f"Results fetch error: {e}")
            return {"success": False, "flights": [], "error": str(e), "source": "redbox"}

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

        logger.info(f"Returning {len(flights)} flights")
        return {
            "success": len(flights) > 0,
            "flights": flights,
            "source": "redbox",
            "origin": origin.upper(),
            "destination": destination.upper(),
            "date": departure_date,
            "return_date": return_date,
            "total_results": num_results,
            "airlines_count": num_airlines,
            "currency": currency,
            "fare_search_id": fare_search_id,
        }

    def get_search_results(
        self,
        fare_search_id: str,
        page_number: int = 1,
        results_per_page: int = 20,
        include_details: bool = True,
        show_filters: bool = False,
        sorting_criteria: Optional[str] = None,
        filter_criteria: Optional[Dict] = None,
    ) -> Dict:
        """
        Fetch paginated results from an existing search.

        Use this for pagination or applying filters/sorting after initial search.

        Args:
            fare_search_id: Search ID from search_flights() result.
            page_number: Page number (1-indexed, must be >= 1).
            results_per_page: Results per page (max 50).
            include_details: Include additionalFareInfos in results.
            show_filters: Include 19 filter categories in response.
            sorting_criteria: Sort by "PRICE", etc.
            filter_criteria: Filter dict to narrow results.

        Returns:
            Dict with flights, filters, pagination info.
        """
        payload = {
            "pageNumber": max(1, page_number),
            "resultsPerPage": min(results_per_page, 50),
            "includeDetails": include_details,
            "showFilters": show_filters,
        }
        if sorting_criteria:
            payload["sortingCriteria"] = sorting_criteria
        if filter_criteria:
            payload["filterCriteria"] = filter_criteria

        try:
            response = self._session.post(
                self._api_url(f"availableFare/{fare_search_id}"),
                json=payload,
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()

            currency = data.get("currencyIsoCode", "USD")
            raw_results = data.get("results", [])
            flights = [self._parse_redbox_result(r, currency) for r in raw_results]
            flights = [f for f in flights if f]

            return {
                "success": True,
                "flights": flights,
                "fare_search_id": fare_search_id,
                "page_number": data.get("pageNumber", page_number),
                "total_results": data.get("numberOfResultsFiltered", len(flights)),
                "currency": currency,
                "filters": data.get("filters") if show_filters else None,
                "markup_threshold": data.get("agentMarkup2Threshold"),
            }
        except requests.exceptions.HTTPError as e:
            error = self._parse_redbox_error(e.response)
            return {"success": False, "error": error}
        except Exception as e:
            logger.error(f"Get results error: {e}")
            return {"success": False, "error": str(e)}

    def _parse_redbox_result(self, result: Dict, currency: str = "USD") -> Optional[Dict]:
        """Parse a single Redbox flight result into a clean dict."""
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
            seat_selection = None
            cancellation_policy = None
            rebooking_policy = None
            ticket_deadline = None
            ancillaries_available = False
            extras_available = False
            for info in additional:
                info_type = info.get("type")
                if info_type == "baggageInfo":
                    baggage_info = info.get("weightInfo", "")
                elif info_type == "cheapestFare":
                    is_cheapest = True
                elif info_type == "seatFeatureInfo":
                    seat_selection = {
                        "available": bool(info.get("reservable")),
                        "seatmap": bool(info.get("seatmapAvailable")),
                        "cancelable": bool(info.get("cancelable")),
                    }
                elif info_type == "fareInfo":
                    cancellation_policy = info.get("cancellationInfo", "UNKNOWN")
                    rebooking_policy = info.get("rebookingInfo", "UNKNOWN")
                elif info_type == "ticketTimeLimitInfo":
                    ticket_deadline = info.get("ticketTimeLimit")
                elif info_type == "ancillariesBookable":
                    ancillaries_available = True
                elif info_type == "extrasAvailable":
                    extras_available = bool(info.get("display", True))

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
                "source": "redbox",
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
                "duration_minutes": RedboxClient.parse_iso_duration(outbound.get("total_travel_time", "")),
                "duration_formatted": RedboxClient.format_iso_duration(outbound.get("total_travel_time", "")),
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

                # Policies and extras
                "seat_selection": seat_selection,
                "cancellation_policy": cancellation_policy,
                "rebooking_policy": rebooking_policy,
                "ticket_deadline": ticket_deadline,
                "ancillaries_available": ancillaries_available,
                "extras_available": extras_available,

                # Pricing
                "price": total,
                "total": total,
                "base_fare": base_fare,
                "tax": total_tax,
                "ticket_fee": ticket_fee,
                "currency": currency,

                # Raw price details for advanced use
                "price_details": result.get("priceDetails", []),
            }

        except Exception as e:
            logger.error(f"Error parsing result: {e}")
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
            "direction": leg_data.get("direction", ""),
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
            "arrival_time": seg.get("arrivalTimestamp", ""),
            "duration": seg.get("duration", ""),
            "cabin_class": seg.get("cabinClass", "ECONOMY"),
            "booking_class": booking.get("code", ""),
            "fare_base": seg.get("fareBase", ""),
            "fare_family": seg.get("fareFamily", {}).get("airlineName", ""),
            "equipment": seg.get("equipmentInfo", {}).get("code", ""),
            "equipment_name": seg.get("equipmentInfo", {}).get("name", ""),
            "baggage_allowance": seg.get("baggageAllowance", ""),
            "available_seats": seg.get("availableSeats"),
            "ground_time": seg.get("groundTime", ""),
            "technical_stops": seg.get("numberOfTechnicalStops", 0),
            "operating_carrier": operating.get("code", carrier_code),
            "operating_carrier_name": operating.get("name", ""),
            "is_codeshare": operating.get("code", carrier_code) != carrier_code,
        }

    # -------------------------------------------------------------------------
    # Cart Item Builders (static helpers)
    # -------------------------------------------------------------------------

    @staticmethod
    def build_insurance_item(
        insurance_id: str,
        plan_name: str = "",
        passenger_indices: List[int] = None,
        fare_id: str = "",
        price: float = 0.0,
        provider: str = "",
        coverage_type: str = "",
    ) -> Dict:
        """
        Build an INSURANCE cart item for the shopping cart.

        Insurance options are typically discovered via get_extras() after
        a flight search. The insurance_id comes from those results.

        Args:
            insurance_id: Insurance option ID from get_extras().
            plan_name: Human-readable plan name (e.g., "Travel Protection Plus").
            passenger_indices: Which passengers to insure (0-indexed). None = all.
            fare_id: Associated flight fare ID.
            price: Insurance price per passenger.
            provider: Insurance provider name.
            coverage_type: Type of coverage (e.g., "CANCELLATION", "COMPREHENSIVE").

        Returns:
            Cart item dict ready for cartItemList.
        """
        item = {
            "type": "INSURANCE",
            "insuranceId": insurance_id,
        }
        if plan_name:
            item["planName"] = plan_name
        if passenger_indices is not None:
            item["passengerIndices"] = passenger_indices
        if fare_id:
            item["flightId"] = fare_id
        if price:
            item["price"] = round(price, 2)
        if provider:
            item["provider"] = provider
        if coverage_type:
            item["coverageType"] = coverage_type
        return item

    @staticmethod
    def build_ancillary_item(
        ancillary_id: str,
        service_type: str,
        segment_ids: List[str] = None,
        passenger_indices: List[int] = None,
        quantity: int = 1,
        price: float = 0.0,
        description: str = "",
    ) -> Dict:
        """
        Build an ANCILLARY cart item (baggage, meals, priority boarding, etc.).

        Ancillary options are discovered via get_extras() after a flight search.

        Args:
            ancillary_id: Ancillary option ID from get_extras().
            service_type: Service category — BAGGAGE, MEAL, PRIORITY_BOARDING,
                LOUNGE_ACCESS, WIFI, FAST_TRACK, SPORTS_EQUIPMENT, etc.
            segment_ids: Which flight segments this applies to.
            passenger_indices: Which passengers (0-indexed). None = all.
            quantity: Number of items (e.g., 2 checked bags).
            price: Price per unit.
            description: Human-readable description.

        Returns:
            Cart item dict ready for cartItemList.
        """
        item = {
            "type": "ANCILLARY",
            "ancillaryId": ancillary_id,
            "serviceType": service_type,
        }
        if segment_ids:
            item["segmentIds"] = segment_ids
        if passenger_indices is not None:
            item["passengerIndices"] = passenger_indices
        if quantity > 1:
            item["quantity"] = quantity
        if price:
            item["price"] = round(price, 2)
        if description:
            item["description"] = description
        return item

    @staticmethod
    def build_seat_item(
        seat_number: str,
        segment_id: str,
        passenger_index: int = 0,
        price: float = 0.0,
        cabin_class: str = "",
    ) -> Dict:
        """
        Build a SEAT cart item for seat selection.

        Use get_seatmap() to discover available seats first.

        Args:
            seat_number: Seat designation (e.g., "14A", "32C").
            segment_id: Flight segment ID this seat is for.
            passenger_index: Which passenger (0-indexed).
            price: Seat selection fee.
            cabin_class: Override cabin (e.g., for paid upgrades).

        Returns:
            Cart item dict ready for cartItemList.
        """
        item = {
            "type": "SEAT",
            "seatNumber": seat_number,
            "segmentId": segment_id,
            "passengerIndex": passenger_index,
        }
        if price:
            item["price"] = round(price, 2)
        if cabin_class:
            item["cabinClass"] = cabin_class
        return item

    @staticmethod
    def build_frequent_flyer_item(
        ff_number: str,
        airline_code: str,
        passenger_index: int = 0,
    ) -> Dict:
        """
        Build a frequent flyer / loyalty program item.

        Note: This may be part of the PASSENGER item in some Redbox versions.
        Check if your agency has loyalty program integration enabled.

        Args:
            ff_number: Frequent flyer membership number.
            airline_code: Airline loyalty program IATA code.
            passenger_index: Which passenger (0-indexed).

        Returns:
            Dict that can be added to passenger data or as a separate cart item.
        """
        return {
            "type": "FREQUENT_FLYER",
            "frequentFlyerNumber": ff_number,
            "airlineCode": airline_code.upper(),
            "passengerIndex": passenger_index,
        }

    # -------------------------------------------------------------------------
    # Extras Discovery (Insurance, Ancillaries, Seats)
    # -------------------------------------------------------------------------

    def get_extras(
        self,
        fare_search_id: str,
        fare_id: str,
    ) -> Dict:
        """
        Discover available extras for a fare — insurance, ancillaries, seats.

        Call this after search_flights() when extras_available or
        ancillaries_available flags are True on a fare result.

        Args:
            fare_search_id: Search ID from search_flights().
            fare_id: Specific fare ID from search results.

        Returns:
            Dict with success, insurance_options, ancillary_options,
            seat_info, and raw extras data.
        """
        try:
            response = self._session.get(
                self._api_url(f"availableFare/{fare_search_id}/extras"),
                params={"fareId": fare_id},
                headers={"Accept": "application/json"},
                timeout=20,
            )
            response.raise_for_status()
            data = response.json()

            # Parse insurance options
            insurance_options = []
            for ins in data.get("insuranceOptions", data.get("insurance", [])):
                insurance_options.append({
                    "insurance_id": ins.get("id", ins.get("insuranceId", "")),
                    "plan_name": ins.get("name", ins.get("planName", "")),
                    "provider": ins.get("provider", ins.get("insuranceProvider", "")),
                    "price_per_pax": float(ins.get("pricePerPax", ins.get("price", 0))),
                    "coverage_type": ins.get("coverageType", ins.get("type", "")),
                    "description": ins.get("description", ""),
                    "currency": ins.get("currency", "USD"),
                    "terms_url": ins.get("termsUrl", ins.get("termsAndConditionsUrl", "")),
                })

            # Parse ancillary options
            ancillary_options = []
            for anc in data.get("ancillaryOptions", data.get("ancillaries", [])):
                ancillary_options.append({
                    "ancillary_id": anc.get("id", anc.get("ancillaryId", "")),
                    "service_type": anc.get("serviceType", anc.get("type", "")),
                    "description": anc.get("description", anc.get("name", "")),
                    "price": float(anc.get("price", anc.get("amount", 0))),
                    "currency": anc.get("currency", "USD"),
                    "segment_ids": anc.get("segmentIds", anc.get("applicableSegments", [])),
                    "max_quantity": anc.get("maxQuantity", 1),
                })

            # Parse seat availability summary
            seat_info = data.get("seatInfo", data.get("seatAvailability", {}))

            return {
                "success": True,
                "fare_id": fare_id,
                "insurance_options": insurance_options,
                "ancillary_options": ancillary_options,
                "seat_info": seat_info,
                "insurance_count": len(insurance_options),
                "ancillary_count": len(ancillary_options),
                "raw": data,
            }
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else 0
            if status == 404:
                # Endpoint may not exist — extras discovery not available
                logger.info(f"Extras endpoint not available (404) for fare {fare_id}")
                return {
                    "success": True,
                    "fare_id": fare_id,
                    "insurance_options": [],
                    "ancillary_options": [],
                    "seat_info": {},
                    "insurance_count": 0,
                    "ancillary_count": 0,
                    "note": "Extras discovery endpoint not available. "
                            "Insurance/ancillaries may need to be added via Cockpit portal.",
                }
            error = self._parse_redbox_error(e.response)
            return {"success": False, "error": error}
        except Exception as e:
            logger.error(f"Get extras error: {e}")
            return {"success": False, "error": str(e)}

    # -------------------------------------------------------------------------
    # Fare Rules
    # -------------------------------------------------------------------------

    def get_fare_rules(self, fare_search_id: str, fare_id: str) -> Dict:
        """
        Get fare rules for a specific fare from search results.

        Returns structured fare rules with categories like:
        RU (Rule Application), FL (Flight Application),
        AP (Advance Purchase), MN (Min Stay), MX (Max Stay),
        PE (Penalties), etc. Each category contains HTML-formatted rule text.

        Args:
            fare_search_id: Search ID from search_flights().
            fare_id: Fare ID from the flight result.

        Returns:
            Dict with success, fare_id, rules (dict of category->title/text),
            rule_count.
        """
        try:
            url = self._api_url(f"availableFare/{fare_search_id}/fareRules")
            response = self._session.get(
                url,
                params={"fareId": fare_id},
                headers={"Accept": "application/json"},
                timeout=20,
            )
            response.raise_for_status()
            data = response.json()

            rules = {}
            for rule in data if isinstance(data, list) else data.get("fareRules", data.get("rules", [])):
                category = rule.get("category", rule.get("code", ""))
                title = rule.get("title", rule.get("name", category))
                text = rule.get("text", rule.get("content", ""))
                if category:
                    rules[category] = {"title": title, "text": text}

            return {
                "success": True,
                "fare_id": fare_id,
                "rules": rules,
                "rule_count": len(rules),
            }
        except requests.exceptions.HTTPError as e:
            error = self._parse_redbox_error(e.response)
            return {"success": False, "error": error}
        except Exception as e:
            logger.error(f"Fare rules error: {e}")
            return {"success": False, "error": str(e)}

    # -------------------------------------------------------------------------
    # Seatmap
    # -------------------------------------------------------------------------

    def get_seatmap(
        self,
        airline_code: str,
        flight_number: str,
        departure: str,
        destination: str,
        departure_date: str,
        booking_class: str = "Y",
        cabin_class: str = "ECONOMY",
        reservation_system: str = "AMADEUS",
    ) -> Dict:
        """
        Get seatmap for a specific flight.

        Args:
            airline_code: Marketing airline IATA code (AA, DL, UA).
            flight_number: Flight number (e.g., "1758").
            departure: Departure airport IATA code.
            destination: Destination airport IATA code.
            departure_date: Date in YYYY-MM-DD format.
            booking_class: GDS booking class code (Y, B, M, etc.).
            cabin_class: ECONOMY, PREMIUM_ECONOMY, BUSINESS, or FIRST.
            reservation_system: GDS system (AMADEUS, SABRE, AER_DC, FARELOGIX).

        Returns:
            Dict with success and seatmap data.
        """
        try:
            response = self._session.post(
                self._api_url("seatmap"),
                json={
                    "marketingAirline": airline_code.upper(),
                    "flightNumber": str(flight_number),
                    "departure": departure.upper(),
                    "destination": destination.upper(),
                    "departureDate": departure_date,
                    "bookingClass": booking_class.upper(),
                    "cabinClass": cabin_class.upper(),
                    "reservationSystem": reservation_system.upper(),
                },
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                timeout=20,
            )
            response.raise_for_status()
            data = response.json()

            return {
                "success": True,
                "airline": airline_code,
                "flight_number": flight_number,
                "seatmap": data,
            }
        except requests.exceptions.HTTPError as e:
            error = self._parse_redbox_error(e.response)
            return {"success": False, "error": error}
        except Exception as e:
            logger.error(f"Seatmap error: {e}")
            return {"success": False, "error": str(e)}

    # -------------------------------------------------------------------------
    # Shopping Cart
    # -------------------------------------------------------------------------

    def get_shopping_cart(self) -> Dict:
        """Get current shopping cart contents."""
        try:
            response = self._session.get(
                self._api_url("shoppingCart"),
                headers={"Accept": "application/json"},
                timeout=15,
            )
            response.raise_for_status()
            data = response.json()
            return {
                "success": True,
                "cart": data,
                "cart_id": data.get("shoppingCartId"),
                "expires": data.get("expirationTimestamp"),
            }
        except requests.exceptions.HTTPError as e:
            error = self._parse_redbox_error(e.response)
            return {"success": False, "error": error}
        except Exception as e:
            logger.error(f"Get cart error: {e}")
            return {"success": False, "error": str(e)}

    def create_shopping_cart(self, items: List[Dict] = None) -> Dict:
        """
        Create a new shopping cart, optionally with initial items.

        Args:
            items: Optional list of cart items (FLIGHT, PASSENGER, etc.).

        Returns:
            Dict with success, cart data, cart_id, expires.
        """
        try:
            payload = {}
            if items:
                payload["cartItemList"] = items

            response = self._session.post(
                self._api_url("shoppingCart"),
                json=payload,
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                timeout=15,
            )
            response.raise_for_status()
            data = response.json()
            return {
                "success": True,
                "cart": data,
                "cart_id": data.get("shoppingCartId"),
                "expires": data.get("expirationTimestamp"),
            }
        except requests.exceptions.HTTPError as e:
            error = self._parse_redbox_error(e.response)
            return {"success": False, "error": error}
        except Exception as e:
            logger.error(f"Create cart error: {e}")
            return {"success": False, "error": str(e)}

    def add_to_cart_and_checkout(
        self,
        fare_search_id: str,
        fare_id: str,
        passengers: List[Dict],
        itinerary_ids: List[str] = None,
        markup_amount: float = 0.0,
        extra_cart_items: List[Dict] = None,
    ) -> Dict:
        """
        Add flight + passengers to cart and checkout in one step.

        This is the primary booking entry point — combines cart creation,
        flight selection, passenger data, and checkout into one API call.

        Args:
            fare_search_id: From search_flights() result.
            fare_id: Selected fare ID from search results.
            passengers: List of passenger dicts. Required keys:
                - firstName (str): First name
                - lastName (str): Last name
                - paxType (str): ADT, CHD, or INF
                Optional keys:
                - dateOfBirth (str): YYYY-MM-DD
                - gender (str): Male or Female (capitalized)
                - title (str): Mr, Mrs, Ms, etc.
                - email (str): Contact email
                - phone (str): Contact phone
                - passportNumber (str): For international flights
                - passportExpiry (str): YYYY-MM-DD
                - nationality (str): Country code
            itinerary_ids: Itinerary IDs from fare result (defaults to ["0"]).
            markup_amount: Fee to add via BOOKING_FEE_OVERRIDE. The issued
                ticket will reflect the marked-up price. Max $999 per Redbox
                threshold.
            extra_cart_items: Additional cart items — INSURANCE, ANCILLARY,
                SEAT, etc. Built via build_insurance_item(), build_ancillary_item(),
                build_seat_item(), or manually constructed dicts.

        Returns:
            Dict with success, cart data, cart_id, expires, items.
        """
        if itinerary_ids is None:
            itinerary_ids = ["0"]

        cart_items = []

        # Flight item
        cart_items.append({
            "type": "FLIGHT",
            "fareSearchId": fare_search_id,
            "fareIds": [fare_id],
            "itineraryIds": itinerary_ids,
        })

        # Passenger items
        for pax in passengers:
            pax_item = {
                "type": "PASSENGER",
                "firstName": pax.get("firstName", pax.get("first_name", "")),
                "lastName": pax.get("lastName", pax.get("last_name", "")),
                "paxType": pax.get("paxType", pax.get("pax_type", "ADT")),
            }

            # Optional passenger fields
            if pax.get("dateOfBirth") or pax.get("date_of_birth"):
                pax_item["dateOfBirth"] = pax.get("dateOfBirth", pax.get("date_of_birth"))
            if pax.get("gender"):
                # Redbox expects "Male"/"Female" (capitalized), not "MALE"/"FEMALE"
                pax_item["gender"] = pax["gender"].strip().capitalize()
            if pax.get("title"):
                pax_item["title"] = pax["title"]
            if pax.get("salutation"):
                pax_item["salutation"] = pax["salutation"]
            if pax.get("middleNames") or pax.get("middle_name"):
                pax_item["middleNames"] = pax.get("middleNames", pax.get("middle_name"))

            # Contact data — Redbox uses nested contactData:
            # emailAddress (NOT email), phoneNumber, telCountryCode
            contact_data = {}
            if pax.get("email"):
                contact_data["emailAddress"] = pax["email"]
            if pax.get("phone") or pax.get("phoneNumber"):
                contact_data["phoneNumber"] = pax.get("phone", pax.get("phoneNumber"))
            if contact_data:
                pax_item["contactData"] = contact_data

            # APIS document — passport/travel document for international flights
            apis = {}
            if pax.get("passportNumber") or pax.get("passport_number"):
                apis["documentNumber"] = pax.get("passportNumber", pax.get("passport_number"))
            if pax.get("passportExpiry") or pax.get("passport_expiry"):
                apis["expiryDate"] = pax.get("passportExpiry", pax.get("passport_expiry"))
            if pax.get("nationality"):
                apis["nationality"] = pax["nationality"]
            if apis:
                pax_item["apisDocument"] = apis

            cart_items.append(pax_item)

        # BOOKING_FEE_OVERRIDE to mark up the ticket price
        if markup_amount and markup_amount > 0:
            cart_items.append({
                "type": "BOOKING_FEE_OVERRIDE",
                "value": round(markup_amount, 2),
                "flightIdList": [fare_id],
            })

        # Add any extra cart items (insurance, ancillaries, seats, etc.)
        if extra_cart_items:
            cart_items.extend(extra_cart_items)

        try:
            markup_str = f", markup=${markup_amount:.2f}" if markup_amount else ""
            logger.info(f"Adding to cart: fare={fare_id}, {len(passengers)} pax{markup_str}")
            response = self._session.post(
                self._api_url("shoppingCart/addAndCheckOut"),
                json={"cartItemList": cart_items},
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()

            cart_id = data.get("shoppingCartId")
            logger.info(f"Cart created: {cart_id}")

            return {
                "success": True,
                "cart": data,
                "cart_id": cart_id,
                "expires": data.get("expirationTimestamp"),
                "items": data.get("cartItemList", []),
            }
        except requests.exceptions.HTTPError as e:
            error = self._parse_redbox_error(e.response)
            logger.error(f"Add to cart error: {error}")
            return {"success": False, "error": error}
        except Exception as e:
            logger.error(f"Add to cart error: {e}")
            return {"success": False, "error": str(e)}

    def delete_shopping_cart(self, cart_id: str) -> Dict:
        """Delete a shopping cart by ID."""
        try:
            response = self._session.delete(
                self._api_url(f"shoppingCart/{cart_id}"),
                headers={"Accept": "application/json"},
                timeout=15,
            )
            response.raise_for_status()
            return {"success": True}
        except Exception as e:
            logger.error(f"Delete cart error: {e}")
            return {"success": False, "error": str(e)}

    # -------------------------------------------------------------------------
    # SuperPNR — Booking Creation & Management
    # -------------------------------------------------------------------------

    def create_booking(
        self,
        shopping_cart_id: str,
        order_tickets: bool = True,
        optimize_fare: bool = False,
    ) -> Dict:
        """
        Create a booking (superPNR) from a shopping cart.

        This is the final step that books the flight and creates the PNR
        in the airline's system.

        Args:
            shopping_cart_id: Cart ID from add_to_cart_and_checkout().
            order_tickets: If True, issue tickets immediately.
            optimize_fare: If True, attempt to optimize the fare.

        Returns:
            Dict with success, booking data, super_pnr_id, locator/pnr, status.
        """
        try:
            payload = {
                "shoppingCartId": shopping_cart_id,
                "orderTickets": order_tickets,
            }
            if optimize_fare:
                payload["optimizeFare"] = True

            logger.info(f"Creating booking from cart {shopping_cart_id}")
            response = self._session.post(
                self._api_url("superPNR"),
                json=payload,
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                timeout=60,
            )
            response.raise_for_status()
            data = response.json()

            super_pnr_id = data.get("superPnrId", data.get("id"))
            locator = data.get("locator", data.get("pnrLocator", data.get("recordLocator")))
            status = data.get("status", data.get("bookingStatus"))

            logger.info(f"Booking created: superPnrId={super_pnr_id}, locator={locator}")

            return {
                "success": True,
                "booking": data,
                "super_pnr_id": super_pnr_id,
                "locator": locator,
                "pnr": locator,
                "status": status,
            }
        except requests.exceptions.HTTPError as e:
            error = self._parse_redbox_error(e.response)
            logger.error(f"Create booking error: {error}")
            return {"success": False, "error": error}
        except Exception as e:
            logger.error(f"Create booking error: {e}")
            return {"success": False, "error": str(e)}

    def search_bookings(
        self,
        locator: str = None,
        departure: str = None,
        destination: str = None,
        airline: str = None,
        date_from: str = None,
        date_to: str = None,
        travel_date_from: str = None,
        travel_date_to: str = None,
        agent: str = None,
        search_option: str = None,
    ) -> Dict:
        """
        Search existing bookings (superPNR search).

        At least one filter parameter is required.

        Args:
            locator: PNR/record locator to search for.
            departure: Departure airport code.
            destination: Destination airport code.
            airline: Validating airline code.
            date_from/date_to: Booking creation date range (YYYY-MM-DD).
            travel_date_from/travel_date_to: Travel date range.
            agent: Agent name filter.
            search_option: Search option filter.

        Returns:
            Dict with success, search_id, summary (13 status fields),
            bookings list, totals.
        """
        payload = {}
        if locator:
            payload["locator"] = locator
        if departure:
            payload["departure"] = departure
        if destination:
            payload["destination"] = destination
        if airline:
            payload["validatingAirline"] = airline
        if date_from:
            payload["from"] = date_from
        if date_to:
            payload["until"] = date_to
        if travel_date_from:
            payload["travelDateFrom"] = travel_date_from
        if travel_date_to:
            payload["travelDateUntil"] = travel_date_to
        if agent:
            payload["agent"] = agent
        if search_option:
            payload["superPnrSearchOption"] = search_option

        try:
            response = self._session.post(
                self._api_url("superPNR/search"),
                json=payload,
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()

            search_id = data.get("superPnrSearchId")
            summary = data.get("searchSummary", {})

            return {
                "success": True,
                "search_id": search_id,
                "summary": summary,
                "bookings": data.get("results", data.get("superPnrs", [])),
                "total_open": summary.get("openBookings", 0),
                "total_issued": summary.get("issued", 0),
                "total_cancelled": summary.get("cancelled", 0),
            }
        except requests.exceptions.HTTPError as e:
            error = self._parse_redbox_error(e.response)
            return {"success": False, "error": error}
        except Exception as e:
            logger.error(f"Search bookings error: {e}")
            return {"success": False, "error": str(e)}

    # -------------------------------------------------------------------------
    # High-Level Booking Flow
    # -------------------------------------------------------------------------

    def book_flight(
        self,
        fare_search_id: str,
        fare_id: str,
        passengers: List[Dict],
        order_tickets: bool = True,
        itinerary_ids: List[str] = None,
        markup_amount: float = 0.0,
        extra_cart_items: List[Dict] = None,
    ) -> Dict:
        """
        Complete end-to-end flight booking in one call.

        Orchestrates: addToCart+checkout -> createBooking (superPNR).

        Args:
            fare_search_id: From search_flights() result.
            fare_id: Selected fare from search results.
            passengers: List of passenger dicts (see add_to_cart_and_checkout).
            order_tickets: If True, issue tickets immediately.
            itinerary_ids: Override itinerary selection.
            markup_amount: Platform fee via BOOKING_FEE_OVERRIDE.
            extra_cart_items: Additional cart items (INSURANCE, ANCILLARY,
                SEAT, etc.). Use build_insurance_item(), build_ancillary_item(),
                build_seat_item() to construct these.

        Returns:
            Dict with success, pnr, locator, super_pnr_id, status,
            cart_id, booking_data, step.
        """
        extras_desc = f", +{len(extra_cart_items)} extras" if extra_cart_items else ""
        logger.info(f"=== BOOKING FLOW START: fare={fare_id}, {len(passengers)} pax{extras_desc} ===")

        # Step 1: Add to cart and checkout
        cart_result = self.add_to_cart_and_checkout(
            fare_search_id=fare_search_id,
            fare_id=fare_id,
            passengers=passengers,
            itinerary_ids=itinerary_ids,
            markup_amount=markup_amount,
            extra_cart_items=extra_cart_items,
        )

        if not cart_result.get("success"):
            logger.error(f"Cart creation failed: {cart_result.get('error')}")
            return {
                "success": False,
                "error": f"Cart creation failed: {cart_result.get('error')}",
                "step": "cart",
            }

        cart_id = cart_result["cart_id"]

        # Step 2: Create booking (superPNR)
        booking_result = self.create_booking(
            shopping_cart_id=cart_id,
            order_tickets=order_tickets,
        )

        if not booking_result.get("success"):
            self.delete_shopping_cart(cart_id)
            logger.error(f"Booking failed: {booking_result.get('error')}")
            return {
                "success": False,
                "error": f"Booking failed: {booking_result.get('error')}",
                "step": "booking",
                "cart_id": cart_id,
            }

        pnr = booking_result.get("pnr") or booking_result.get("locator")
        super_pnr_id = booking_result.get("super_pnr_id")

        logger.info(f"=== BOOKING COMPLETE: PNR={pnr} ===")

        return {
            "success": True,
            "pnr": pnr,
            "locator": pnr,
            "super_pnr_id": super_pnr_id,
            "status": booking_result.get("status"),
            "cart_id": cart_id,
            "booking_data": booking_result.get("booking"),
            "step": "complete",
        }

    # -------------------------------------------------------------------------
    # Booking Management (Cancel, Void, Refund, Details)
    # -------------------------------------------------------------------------

    def get_booking_details(self, super_pnr_id: str) -> Dict:
        """
        Get full details for a booking by SuperPNR ID.

        Returns the complete booking record including PNR, segments,
        passengers, ticket numbers, status, and pricing.

        Args:
            super_pnr_id: SuperPNR ID from create_booking() or search_bookings().

        Returns:
            Dict with success, booking details, status, pnr, passengers,
            segments, tickets.
        """
        try:
            response = self._session.get(
                self._api_url(f"superPNR/{super_pnr_id}"),
                headers={"Accept": "application/json"},
                timeout=20,
            )
            response.raise_for_status()
            data = response.json()

            return {
                "success": True,
                "super_pnr_id": super_pnr_id,
                "booking": data,
                "status": data.get("status", data.get("bookingStatus")),
                "pnr": data.get("locator", data.get("pnrLocator", data.get("recordLocator"))),
                "passengers": data.get("passengers", data.get("passengerList", [])),
                "segments": data.get("segments", data.get("segmentList", data.get("flightSegments", []))),
                "tickets": data.get("tickets", data.get("ticketList", [])),
                "insurance": data.get("insurance", data.get("insuranceDetails", [])),
                "ancillaries": data.get("ancillaries", data.get("ancillaryServices", [])),
                "total_price": data.get("totalPrice", data.get("total")),
                "currency": data.get("currency", data.get("currencyIsoCode")),
            }
        except requests.exceptions.HTTPError as e:
            error = self._parse_redbox_error(e.response)
            return {"success": False, "error": error}
        except Exception as e:
            logger.error(f"Get booking details error: {e}")
            return {"success": False, "error": str(e)}

    def cancel_booking(
        self,
        super_pnr_id: str,
        reason: str = "",
        segment_ids: List[str] = None,
    ) -> Dict:
        """
        Cancel a booking (SuperPNR).

        Cancellation policies vary by fare — check fare rules first via
        get_fare_rules(). Some fares are non-refundable but still cancellable
        (with penalty). Others are fully non-cancellable.

        Args:
            super_pnr_id: SuperPNR ID to cancel.
            reason: Optional cancellation reason.
            segment_ids: Cancel specific segments only (partial cancel).
                None = cancel entire booking.

        Returns:
            Dict with success, cancellation status, refund info.
        """
        try:
            payload = {
                "superPnrId": super_pnr_id,
            }
            if reason:
                payload["reason"] = reason
            if segment_ids:
                payload["segmentIds"] = segment_ids

            logger.info(f"Cancelling booking: {super_pnr_id}")
            response = self._session.post(
                self._api_url(f"superPNR/{super_pnr_id}/cancel"),
                json=payload,
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()

            status = data.get("status", data.get("cancellationStatus"))
            refund = data.get("refundInfo", data.get("refundDetails", {}))

            logger.info(f"Booking {super_pnr_id} cancelled — status: {status}")

            return {
                "success": True,
                "super_pnr_id": super_pnr_id,
                "status": status,
                "refund_eligible": bool(refund),
                "refund_amount": refund.get("amount", refund.get("refundAmount")),
                "refund_currency": refund.get("currency"),
                "penalty_amount": refund.get("penalty", refund.get("penaltyAmount")),
                "cancellation_data": data,
            }
        except requests.exceptions.HTTPError as e:
            error = self._parse_redbox_error(e.response)
            logger.error(f"Cancel booking error: {error}")
            return {"success": False, "error": error}
        except Exception as e:
            logger.error(f"Cancel booking error: {e}")
            return {"success": False, "error": str(e)}

    def void_ticket(self, super_pnr_id: str) -> Dict:
        """
        Void an issued ticket within the airline void window (typically 24h).

        Voiding is different from cancellation: it completely reverses the
        ticketing as if it never happened. No penalties, full refund.
        Only available within the void window after ticket issuance.

        Args:
            super_pnr_id: SuperPNR ID of the booking with tickets to void.

        Returns:
            Dict with success, void status.
        """
        try:
            logger.info(f"Voiding tickets for booking: {super_pnr_id}")
            response = self._session.post(
                self._api_url(f"superPNR/{super_pnr_id}/void"),
                json={"superPnrId": super_pnr_id},
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()

            logger.info(f"Tickets voided for {super_pnr_id}")

            return {
                "success": True,
                "super_pnr_id": super_pnr_id,
                "status": data.get("status", "voided"),
                "void_data": data,
            }
        except requests.exceptions.HTTPError as e:
            error = self._parse_redbox_error(e.response)
            logger.error(f"Void ticket error: {error}")
            return {"success": False, "error": error}
        except Exception as e:
            logger.error(f"Void ticket error: {e}")
            return {"success": False, "error": str(e)}

    def request_refund(
        self,
        super_pnr_id: str,
        refund_type: str = "FULL",
        amount: float = None,
        reason: str = "",
    ) -> Dict:
        """
        Request a refund for a cancelled booking.

        Refund processing depends on fare rules and airline policy.
        Penalties may apply. The refund is processed through the agency's
        Cockpit account settlement.

        Args:
            super_pnr_id: SuperPNR ID of the cancelled booking.
            refund_type: "FULL" or "PARTIAL".
            amount: For partial refunds, the amount to refund.
            reason: Refund reason.

        Returns:
            Dict with success, refund status, reference number.
        """
        try:
            payload = {
                "superPnrId": super_pnr_id,
                "refundType": refund_type.upper(),
            }
            if amount is not None:
                payload["amount"] = round(amount, 2)
            if reason:
                payload["reason"] = reason

            logger.info(f"Requesting {refund_type} refund for booking: {super_pnr_id}")
            response = self._session.post(
                self._api_url(f"superPNR/{super_pnr_id}/refund"),
                json=payload,
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()

            ref_number = data.get("refundReference", data.get("referenceNumber"))
            logger.info(f"Refund requested: ref={ref_number}")

            return {
                "success": True,
                "super_pnr_id": super_pnr_id,
                "refund_reference": ref_number,
                "refund_status": data.get("status", data.get("refundStatus")),
                "refund_amount": data.get("amount", data.get("refundAmount")),
                "penalty_amount": data.get("penalty", data.get("penaltyAmount")),
                "estimated_processing": data.get("estimatedProcessingTime"),
                "refund_data": data,
            }
        except requests.exceptions.HTTPError as e:
            error = self._parse_redbox_error(e.response)
            logger.error(f"Refund request error: {error}")
            return {"success": False, "error": error}
        except Exception as e:
            logger.error(f"Refund request error: {e}")
            return {"success": False, "error": str(e)}

    # -------------------------------------------------------------------------
    # Documents
    # -------------------------------------------------------------------------

    def generate_document(
        self,
        document_type: str,
        shopping_cart_id: str = None,
        super_pnr_id: str = None,
        fare_search_id: str = None,
        fare_ids: List[str] = None,
        passenger_list: List[Dict] = None,
        display_prices: bool = True,
        language: str = "en",
        email_recipients: List[str] = None,
        hide_agency_fees: bool = False,
        custom_reference: str = None,
    ) -> Dict:
        """
        Generate a document (PDF/email) via Redbox.

        Args:
            document_type: ITINERARY, OFFER, CONFIRMATION, or TRAVEL_REGISTRATION.
            shopping_cart_id: Cart ID (for pre-booking docs).
            super_pnr_id: SuperPNR ID (for post-booking docs).
            fare_search_id: Search ID (for offer docs).
            fare_ids: List of fare IDs to include.
            passenger_list: Passenger details for the document.
            display_prices: Whether to show prices.
            language: ISO language code (default "en").
            email_recipients: Email addresses to send document to.
            hide_agency_fees: Whether to hide agency markup.
            custom_reference: Custom reference number.

        Returns:
            Dict with success, document_type, content_type (pdf/json),
            and content/document data.
        """
        payload = {
            "documentType": document_type.upper(),
            "displayPrices": display_prices,
            "languageIsoCode": language,
        }

        if shopping_cart_id:
            payload["shoppingCartId"] = shopping_cart_id
        if super_pnr_id:
            payload["superPnrId"] = super_pnr_id
        if fare_search_id:
            payload["fareSearchId"] = fare_search_id
        if fare_ids:
            payload["fareIds"] = fare_ids
        if passenger_list:
            payload["passengerList"] = passenger_list
        if email_recipients:
            payload["emailRecipients"] = email_recipients
        if hide_agency_fees:
            payload["hideAgencyFees"] = True
        if custom_reference:
            payload["customReferenceNumber"] = custom_reference

        try:
            logger.info(f"Generating {document_type} document")
            response = self._session.post(
                self._api_url("document"),
                json=payload,
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                timeout=30,
            )
            response.raise_for_status()

            content_type = response.headers.get("Content-Type", "")
            if "application/pdf" in content_type:
                return {
                    "success": True,
                    "document_type": document_type,
                    "content_type": "pdf",
                    "content": response.content,
                }
            else:
                data = response.json()
                return {
                    "success": True,
                    "document_type": document_type,
                    "content_type": "json",
                    "document": data,
                }
        except requests.exceptions.HTTPError as e:
            error = self._parse_redbox_error(e.response)
            return {"success": False, "error": error}
        except Exception as e:
            logger.error(f"Document generation error: {e}")
            return {"success": False, "error": str(e)}

    # -------------------------------------------------------------------------
    # Traveler Profiles
    # -------------------------------------------------------------------------

    def search_profiles(self, search_term: str) -> Dict:
        """
        Search traveler profiles.

        Args:
            search_term: Name or identifier to search for.

        Returns:
            Dict with success, profiles list, count.
        """
        try:
            response = self._session.get(
                self._api_url("profile"),
                params={"searchTerm": search_term},
                headers={"Accept": "application/json"},
                timeout=15,
            )
            response.raise_for_status()
            data = response.json()

            profiles = data if isinstance(data, list) else data.get("profiles", [])
            return {
                "success": True,
                "profiles": profiles,
                "count": len(profiles),
            }
        except requests.exceptions.HTTPError as e:
            error = self._parse_redbox_error(e.response)
            return {"success": False, "error": error}
        except Exception as e:
            logger.error(f"Profile search error: {e}")
            return {"success": False, "error": str(e)}

    # -------------------------------------------------------------------------
    # Session & Configuration
    # -------------------------------------------------------------------------

    def get_configuration(self) -> Dict:
        """
        Get Redbox configuration for current session.

        Returns session inactivity timestamp and other config.
        """
        try:
            response = self._session.get(
                self._api_url("configuration"),
                headers={"Accept": "application/json"},
                timeout=10,
            )
            response.raise_for_status()
            return {"success": True, "config": response.json()}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _parse_redbox_error(self, response) -> str:
        """Extract error message from Redbox API error response."""
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

    @staticmethod
    def parse_iso_duration(duration: str) -> int:
        """Parse ISO 8601 duration (PT10H25M) to total minutes."""
        if not duration:
            return 0
        match = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?', duration)
        if match:
            hours = int(match.group(1) or 0)
            minutes = int(match.group(2) or 0)
            return hours * 60 + minutes
        return 0

    @staticmethod
    def format_iso_duration(duration: str) -> str:
        """Format ISO 8601 duration (PT10H25M) to human-readable 'Xh Ym'."""
        minutes = RedboxClient.parse_iso_duration(duration)
        if minutes <= 0:
            return ""
        h, m = divmod(minutes, 60)
        if h and m:
            return f"{h}h {m}m"
        elif h:
            return f"{h}h"
        return f"{m}m"

