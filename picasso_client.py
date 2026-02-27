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
    # Fare Rules
    # -------------------------------------------------------------------------

    def get_fare_rules(self, fare_search_id: str, fare_id: str) -> Dict:
        """
        Get fare rules for a specific fare from search results.

        Returns structured fare rules with categories like:
        - RU (Rule Application), FL (Flight Application)
        - AP (Advance Purchase), MN (Min Stay), MX (Max Stay)
        - PE (Penalties), etc.

        Each category contains HTML-formatted rule text.
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
            print(f"[PICASSO] Fare rules error: {e}")
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
            airline_code: Marketing airline IATA code (AA, DL, UA)
            flight_number: Flight number (e.g., "1758")
            departure: Departure airport IATA
            destination: Destination airport IATA
            departure_date: YYYY-MM-DD
            booking_class: GDS booking class code (Y, B, M, etc.)
            cabin_class: ECONOMY/PREMIUM_ECONOMY/BUSINESS/FIRST
            reservation_system: GDS (AMADEUS, SABRE, etc.)

        Returns:
            Seatmap data with rows, columns, seat availability.
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
            print(f"[PICASSO] Seatmap error: {e}")
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
            print(f"[PICASSO] Get cart error: {e}")
            return {"success": False, "error": str(e)}

    def create_shopping_cart(self, items: List[Dict] = None) -> Dict:
        """
        Create a new shopping cart, optionally with initial items.

        Args:
            items: Optional list of cart items to add immediately.

        Returns:
            Cart details including shoppingCartId.
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
            print(f"[PICASSO] Create cart error: {e}")
            return {"success": False, "error": str(e)}

    def add_to_cart_and_checkout(
        self,
        fare_search_id: str,
        fare_id: str,
        passengers: List[Dict],
        itinerary_ids: List[str] = None,
        markup_amount: float = 0.0,
    ) -> Dict:
        """
        Add flight + passengers to cart and checkout in one step.

        This is the primary booking entry point — combines cart creation,
        flight selection, passenger data, and checkout into one API call.

        Args:
            fare_search_id: From search results
            fare_id: Selected fare from search results
            passengers: List of passenger dicts with:
                - firstName, lastName, paxType (ADT/CHD/INF)
                - dateOfBirth (YYYY-MM-DD), gender (Male/Female)
                - Optional: title, email, phone, passport fields
            itinerary_ids: Itinerary IDs from the fare result (defaults to ["0"])
            markup_amount: Platform fee to add via BOOKING_FEE_OVERRIDE so
                the issued ticket reflects the customer-facing price (not
                the wholesale fare). This hides wholesale pricing from
                the end consumer and satisfies airline contractual
                requirements. Max $999 per Redbox threshold.

        Returns:
            Cart with shoppingCartId for superPNR creation.
        """
        if itinerary_ids is None:
            itinerary_ids = ["0"]

        cart_items = []

        # Flight item
        flight_item = {
            "type": "FLIGHT",
            "fareSearchId": fare_search_id,
            "fareIds": [fare_id],
            "itineraryIds": itinerary_ids,
        }
        cart_items.append(flight_item)

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
                gender_raw = pax["gender"].strip()
                pax_item["gender"] = gender_raw.capitalize()
            if pax.get("title"):
                pax_item["title"] = pax["title"]
            if pax.get("salutation"):
                pax_item["salutation"] = pax["salutation"]
            if pax.get("middleNames") or pax.get("middle_name"):
                pax_item["middleNames"] = pax.get("middleNames", pax.get("middle_name"))

            # Contact data — Redbox uses nested contactData with specific field names:
            # emailAddress (NOT email), phoneNumber, telCountryCode, ctc, travellerId
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

        # Add BOOKING_FEE_OVERRIDE to mark up the ticket price so it
        # matches what the customer paid (hides wholesale pricing).
        if markup_amount and markup_amount > 0:
            cart_items.append({
                "type": "BOOKING_FEE_OVERRIDE",
                "value": round(markup_amount, 2),
                "flightIdList": [fare_id],
            })

        try:
            markup_str = f", markup=${markup_amount:.2f}" if markup_amount else ""
            print(f"[PICASSO] Adding to cart: fare={fare_id}, {len(passengers)} passengers{markup_str}")
            response = self._session.post(
                self._api_url("shoppingCart/addAndCheckOut"),
                json={"cartItemList": cart_items},
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()

            cart_id = data.get("shoppingCartId")
            expires = data.get("expirationTimestamp")
            print(f"[PICASSO] Cart created: {cart_id}, expires: {expires}")

            return {
                "success": True,
                "cart": data,
                "cart_id": cart_id,
                "expires": expires,
                "items": data.get("cartItemList", []),
            }
        except requests.exceptions.HTTPError as e:
            error = self._parse_redbox_error(e.response)
            print(f"[PICASSO] Add to cart error: {error}")
            return {"success": False, "error": error}
        except Exception as e:
            print(f"[PICASSO] Add to cart error: {e}")
            return {"success": False, "error": str(e)}

    def delete_shopping_cart(self, cart_id: str) -> Dict:
        """Delete a shopping cart."""
        try:
            response = self._session.delete(
                self._api_url(f"shoppingCart/{cart_id}"),
                headers={"Accept": "application/json"},
                timeout=15,
            )
            response.raise_for_status()
            return {"success": True}
        except Exception as e:
            print(f"[PICASSO] Delete cart error: {e}")
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

        This is the final step that actually books the flight and creates
        the PNR in the airline's system.

        Args:
            shopping_cart_id: Cart ID from add_to_cart_and_checkout()
            order_tickets: If True, issue tickets immediately. If False,
                          create PNR only (tickets issued later).
            optimize_fare: If True, attempt to optimize the fare.

        Returns:
            Booking details including PNR/locator, booking status.
        """
        try:
            payload = {
                "shoppingCartId": shopping_cart_id,
                "orderTickets": order_tickets,
            }
            if optimize_fare:
                payload["optimizeFare"] = True

            print(f"[PICASSO] Creating booking from cart {shopping_cart_id}, orderTickets={order_tickets}")
            response = self._session.post(
                self._api_url("superPNR"),
                json=payload,
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                timeout=60,
            )
            response.raise_for_status()
            data = response.json()

            # Extract key booking data
            super_pnr_id = data.get("superPnrId", data.get("id"))
            locator = data.get("locator", data.get("pnrLocator", data.get("recordLocator")))
            status = data.get("status", data.get("bookingStatus"))

            print(f"[PICASSO] Booking created: superPnrId={super_pnr_id}, locator={locator}, status={status}")

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
            print(f"[PICASSO] Create booking error: {error}")
            return {"success": False, "error": error}
        except Exception as e:
            print(f"[PICASSO] Create booking error: {e}")
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

        Args:
            locator: PNR locator/record locator to search for
            departure: Departure airport code
            destination: Destination airport code
            airline: Validating airline code
            date_from/date_to: Booking creation date range (YYYY-MM-DD)
            travel_date_from/travel_date_to: Travel date range
            agent: Agent name
            search_option: Search option filter

        Returns:
            List of matching bookings with summary stats.
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
                "raw": data,
            }
        except requests.exceptions.HTTPError as e:
            error = self._parse_redbox_error(e.response)
            return {"success": False, "error": error}
        except Exception as e:
            print(f"[PICASSO] Search bookings error: {e}")
            return {"success": False, "error": str(e)}

    # -------------------------------------------------------------------------
    # Documents — Itinerary, Offer, Confirmation, Travel Registration
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
            document_type: ITINERARY, OFFER, CONFIRMATION, or TRAVEL_REGISTRATION
            shopping_cart_id: Cart ID (for pre-booking docs)
            super_pnr_id: SuperPNR ID (for post-booking docs)
            fare_search_id: Search ID (for offer docs)
            fare_ids: List of fare IDs to include
            passenger_list: Passenger details for the document
            display_prices: Whether to show prices on the document
            language: ISO language code
            email_recipients: Email addresses to send document to
            hide_agency_fees: Whether to hide agency markup
            custom_reference: Custom reference number on document

        Returns:
            Document data (may include download URL or raw content).
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
            print(f"[PICASSO] Generating {document_type} document")
            response = self._session.post(
                self._api_url("document"),
                json=payload,
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                timeout=30,
            )
            response.raise_for_status()

            # Document may return PDF bytes or JSON
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
            print(f"[PICASSO] Document generation error: {e}")
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
            List of matching traveler profiles.
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
            print(f"[PICASSO] Profile search error: {e}")
            return {"success": False, "error": str(e)}

    # -------------------------------------------------------------------------
    # Session & Configuration
    # -------------------------------------------------------------------------

    def get_session_info(self) -> Dict:
        """Get current session configuration and info."""
        try:
            response = self._session.get(
                self._api_url("clientSession"),
                headers={"Accept": "application/json"},
                timeout=10,
            )
            response.raise_for_status()
            return {"success": True, "session": response.json()}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_configuration(self) -> Dict:
        """Get Redbox configuration for current session."""
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
    # High-Level Booking Flow (Orchestrated)
    # -------------------------------------------------------------------------

    def book_flight(
        self,
        fare_search_id: str,
        fare_id: str,
        passengers: List[Dict],
        order_tickets: bool = True,
        itinerary_ids: List[str] = None,
        markup_amount: float = 0.0,
    ) -> Dict:
        """
        Complete end-to-end flight booking.

        Orchestrates: addToCart → checkout → createBooking (superPNR).

        Args:
            fare_search_id: From search results
            fare_id: Selected fare from search results
            passengers: List of passenger dicts:
                - firstName/first_name, lastName/last_name
                - paxType/pax_type (ADT/CHD/INF)
                - dateOfBirth/date_of_birth (YYYY-MM-DD)
                - gender (Male/Female)
                - email, phone (optional)
                - passportNumber, passportExpiry, nationality (for intl flights)
            order_tickets: If True, issue tickets immediately
            itinerary_ids: Override itinerary selection
            markup_amount: Platform fee to bake into ticket via
                BOOKING_FEE_OVERRIDE so issued ticket matches customer price.

        Returns:
            Complete booking result with PNR, status, cart details.
        """
        markup_str = f", markup=${markup_amount:.2f}" if markup_amount else ""
        print(f"[PICASSO] === BOOKING FLOW START ===")
        print(f"[PICASSO] fare_search_id={fare_search_id}, fare_id={fare_id}")
        print(f"[PICASSO] Passengers: {len(passengers)}, orderTickets={order_tickets}{markup_str}")

        # Step 1: Add to cart and checkout (with markup if applicable)
        cart_result = self.add_to_cart_and_checkout(
            fare_search_id=fare_search_id,
            fare_id=fare_id,
            passengers=passengers,
            itinerary_ids=itinerary_ids,
            markup_amount=markup_amount,
        )

        if not cart_result.get("success"):
            print(f"[PICASSO] Cart creation failed: {cart_result.get('error')}")
            return {
                "success": False,
                "error": f"Cart creation failed: {cart_result.get('error')}",
                "step": "cart",
            }

        cart_id = cart_result["cart_id"]
        print(f"[PICASSO] Cart created: {cart_id}")

        # Step 2: Create booking (superPNR)
        booking_result = self.create_booking(
            shopping_cart_id=cart_id,
            order_tickets=order_tickets,
        )

        if not booking_result.get("success"):
            # Try to clean up cart
            self.delete_shopping_cart(cart_id)
            print(f"[PICASSO] Booking creation failed: {booking_result.get('error')}")
            return {
                "success": False,
                "error": f"Booking failed: {booking_result.get('error')}",
                "step": "booking",
                "cart_id": cart_id,
            }

        pnr = booking_result.get("pnr") or booking_result.get("locator")
        super_pnr_id = booking_result.get("super_pnr_id")

        print(f"[PICASSO] === BOOKING FLOW COMPLETE ===")
        print(f"[PICASSO] PNR: {pnr}, SuperPNR: {super_pnr_id}")

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


# --- Fare Rules ---

def get_fare_rules(fare_search_id: str, fare_id: str) -> Dict:
    """Get fare rules for a specific fare."""
    return _get_client().get_fare_rules(fare_search_id, fare_id)


# --- Seatmap ---

def get_seatmap(
    airline_code: str,
    flight_number: str,
    departure: str,
    destination: str,
    departure_date: str,
    booking_class: str = "Y",
    cabin_class: str = "ECONOMY",
) -> Dict:
    """Get seatmap for a specific flight."""
    return _get_client().get_seatmap(
        airline_code, flight_number, departure, destination,
        departure_date, booking_class, cabin_class,
    )


# --- Shopping Cart ---

def get_shopping_cart() -> Dict:
    """Get current shopping cart."""
    return _get_client().get_shopping_cart()


def add_to_cart_and_checkout(
    fare_search_id: str,
    fare_id: str,
    passengers: List[Dict],
    itinerary_ids: List[str] = None,
    markup_amount: float = 0.0,
) -> Dict:
    """Add flight + passengers to cart and checkout."""
    return _get_client().add_to_cart_and_checkout(
        fare_search_id, fare_id, passengers, itinerary_ids, markup_amount,
    )


# --- Booking (SuperPNR) ---

def create_booking(shopping_cart_id: str, order_tickets: bool = True) -> Dict:
    """Create a booking from a shopping cart."""
    return _get_client().create_booking(shopping_cart_id, order_tickets)


def search_bookings(locator: str = None, **kwargs) -> Dict:
    """Search existing bookings."""
    return _get_client().search_bookings(locator=locator, **kwargs)


def book_flight(
    fare_search_id: str,
    fare_id: str,
    passengers: List[Dict],
    order_tickets: bool = True,
    markup_amount: float = 0.0,
) -> Dict:
    """Complete end-to-end flight booking (cart → book → PNR)."""
    return _get_client().book_flight(
        fare_search_id, fare_id, passengers, order_tickets,
        markup_amount=markup_amount,
    )


# --- Documents ---

def generate_document(document_type: str, **kwargs) -> Dict:
    """Generate a document (ITINERARY, OFFER, CONFIRMATION, TRAVEL_REGISTRATION)."""
    return _get_client().generate_document(document_type, **kwargs)


# --- Profiles ---

def search_profiles(search_term: str) -> Dict:
    """Search traveler profiles."""
    return _get_client().search_profiles(search_term)


# --- Session ---

def get_session_info() -> Dict:
    """Get current Redbox session info."""
    return _get_client().get_session_info()


def get_configuration() -> Dict:
    """Get Redbox configuration."""
    return _get_client().get_configuration()
