"""
Picasso Travel / AERTiCKET Cockpit API Client for MYSTES

Multi-market POS flight search + ticket issuance via Cockpit API.
Picasso is a 102-country POS consolidator with IATA subsidiaries in 25+ countries.

Replaces amadeus_client.py as the primary flight search + booking engine.

Cockpit API:
    Base URL: https://cockpit.picassotravel.com/api/v1
    Auth: API key + secret (OAuth2 or static key — TBD on onboarding)
    Docs: Available post-onboarding

The key feature: every search returns fares from MULTIPLE POS markets.
We pick the cheapest POS, display that to the user, and pocket 25% of the
savings vs the US-POS price (which equals Google Flights pricing).

Usage:
    from picasso_client import PicassoClient, search_flights_multi_pos

    result = search_flights_multi_pos("JFK", "LHR", "2026-03-15")
    if result["success"]:
        for flight in result["flights"]:
            print(flight["airline"], flight["price"], flight["pos_market"])
            print(f"Google price: ${flight['us_price']} → MYSTES: ${flight['mystes_price']}")
            print(f"You save: ${flight['savings']} ({flight['savings_pct']}%)")
"""

import os
import requests
from datetime import datetime, timedelta
from typing import List, Dict, Optional

from dotenv import load_dotenv
load_dotenv()

# Cockpit API base URL — will be confirmed during onboarding
BASE_URL = os.environ.get(
    "PICASSO_API_URL",
    "https://cockpit.picassotravel.com/api/v1",
)

# Platform fee: 25% of savings between cheapest POS and US POS
PLATFORM_FEE_PERCENT = 0.25
PLATFORM_FEE_MIN_USD = 3.00
PLATFORM_FEE_MAX_USD = 50.00


class PicassoClient:
    """
    Picasso Travel / AERTiCKET Cockpit API client.

    Multi-market POS flight search + ticket issuance.

    Auth method TBD — skeleton supports both API key and OAuth2.
    Set PICASSO_API_KEY (and optionally PICASSO_API_SECRET) in .env.
    """

    def __init__(self):
        self.api_key = os.environ.get("PICASSO_API_KEY", "")
        self.api_secret = os.environ.get("PICASSO_API_SECRET", "")
        self._access_token = None
        self._token_expires_at = None

    def _headers(self) -> Dict[str, str]:
        """Build request headers. Supports both API key and OAuth2 token."""
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"
        elif self.api_key:
            headers["X-API-Key"] = self.api_key
        return headers

    def is_configured(self) -> bool:
        """Check if Picasso API credentials are set."""
        return bool(self.api_key)

    def _authenticate(self) -> bool:
        """
        Authenticate with Cockpit API (OAuth2 flow if required).

        Returns True if authenticated, False otherwise.
        If API uses static key auth, this is a no-op that returns True.
        """
        # If we have a valid token, reuse it
        if self._access_token and self._token_expires_at:
            if datetime.now() < self._token_expires_at:
                return True

        # If no secret, assume static API key auth (no token exchange needed)
        if not self.api_secret:
            return bool(self.api_key)

        # OAuth2 token exchange (if Cockpit uses this)
        try:
            response = requests.post(
                f"{BASE_URL}/auth/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.api_key,
                    "client_secret": self.api_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=15,
            )
            response.raise_for_status()
            data = response.json()
            self._access_token = data.get("access_token")
            expires_in = data.get("expires_in", 3600)
            self._token_expires_at = datetime.now() + timedelta(seconds=expires_in - 60)
            return bool(self._access_token)
        except Exception as e:
            print(f"[PICASSO] Auth failed: {e}")
            return False

    # -------------------------------------------------------------------------
    # Search: Multi-POS Flight Search
    # -------------------------------------------------------------------------

    def search_flights(
        self,
        origin: str,
        destination: str,
        departure_date: str,
        return_date: Optional[str] = None,
        adults: int = 1,
        cabin_class: str = "ECONOMY",
        max_results: int = 15,
        nonstop_only: bool = False,
        pos_markets: Optional[List[str]] = None,
    ) -> Dict:
        """
        Search flights across multiple POS markets via Cockpit API.

        This is the core arbitrage engine. Returns fares from multiple markets,
        identifies the cheapest, calculates savings vs US POS, and applies
        MYSTES platform fee.

        Args:
            origin: Origin IATA code (JFK, TYS, LAX)
            destination: Destination IATA code (LHR, NRT, CDG)
            departure_date: YYYY-MM-DD
            return_date: Optional return date for round-trip
            adults: Number of adult passengers
            cabin_class: ECONOMY, PREMIUM_ECONOMY, BUSINESS, FIRST
            max_results: Max flights per POS market
            nonstop_only: Filter to non-stop only
            pos_markets: Specific POS markets to query (default: all available)

        Returns:
            Dict with success, flights (with pricing from cheapest POS),
            us_benchmark, markets_searched, source
        """
        if not self.is_configured():
            return {
                "success": False,
                "flights": [],
                "error": "Picasso API not configured (PICASSO_API_KEY missing)",
                "source": "picasso",
            }

        if not self._authenticate():
            return {
                "success": False,
                "flights": [],
                "error": "Picasso authentication failed",
                "source": "picasso",
            }

        # Build search payload
        # NOTE: Actual field names will be confirmed during Cockpit API onboarding.
        # This skeleton uses the most likely REST API structure based on
        # Picasso's documented fare search capabilities.
        payload = {
            "origin": origin.upper(),
            "destination": destination.upper(),
            "departureDate": departure_date,
            "adults": adults,
            "cabinClass": cabin_class,
            "maxResults": max_results,
            "currency": "USD",
        }
        if return_date:
            payload["returnDate"] = return_date
        if nonstop_only:
            payload["nonStop"] = True
        if pos_markets:
            payload["posMarkets"] = pos_markets

        trip_desc = f"{origin}→{destination} on {departure_date}"
        if return_date:
            trip_desc += f" returning {return_date}"
        print(f"[PICASSO] Searching multi-POS fares: {trip_desc}")

        try:
            response = requests.post(
                f"{BASE_URL}/flights/search",
                headers=self._headers(),
                json=payload,
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()
        except requests.exceptions.HTTPError as e:
            error = self._parse_error(e.response)
            print(f"[PICASSO] Search error: {error}")
            return {"success": False, "flights": [], "error": error, "source": "picasso"}
        except Exception as e:
            print(f"[PICASSO] Search error: {e}")
            return {"success": False, "flights": [], "error": str(e), "source": "picasso"}

        # Parse response — structure TBD, this is the expected shape
        raw_offers = data.get("data", data.get("offers", data.get("flights", [])))
        if not raw_offers:
            raw_offers = []

        markets_searched = data.get("marketsSearched", data.get("pos_count", 0))
        print(f"[PICASSO] Found {len(raw_offers)} offers across {markets_searched} POS markets")

        # Process offers: find US benchmark, identify cheapest POS, calculate savings
        flights = []
        for offer in raw_offers[:max_results]:
            parsed = self._parse_flight_offer(offer)
            if parsed:
                flights.append(parsed)

        # Sort by MYSTES price (cheapest first)
        flights.sort(key=lambda f: f.get("mystes_price", f.get("price", 9999)))

        print(f"[PICASSO] Returning {len(flights)} flights with POS arbitrage pricing")
        return {
            "success": len(flights) > 0,
            "flights": flights,
            "source": "picasso",
            "markets_searched": markets_searched,
            "origin": origin.upper(),
            "destination": destination.upper(),
            "date": departure_date,
            "return_date": return_date,
        }

    def _parse_flight_offer(self, offer: Dict) -> Optional[Dict]:
        """
        Parse a Cockpit API flight offer into normalized MYSTES format.

        The key innovation: each offer includes pricing from multiple POS markets.
        We extract the US price (Google benchmark) and cheapest POS price,
        then calculate the MYSTES price (cheapest + 25% of savings).

        Args:
            offer: Raw offer from Cockpit API

        Returns:
            Normalized flight dict with arbitrage pricing, or None
        """
        try:
            # Extract POS-specific pricing
            # Expected structure: offer.pricing = [{pos: "US", amount: 450}, {pos: "DK", amount: 380}, ...]
            pricing_by_pos = offer.get("pricing", offer.get("posFares", []))

            if isinstance(pricing_by_pos, list):
                pos_prices = {}
                for p in pricing_by_pos:
                    pos = p.get("pos", p.get("market", p.get("pointOfSale", "")))
                    amount = float(p.get("amount", p.get("price", p.get("total", 0))))
                    if pos and amount > 0:
                        pos_prices[pos] = amount
            elif isinstance(pricing_by_pos, dict):
                pos_prices = {k: float(v) for k, v in pricing_by_pos.items() if float(v) > 0}
            else:
                # Single-POS fallback
                price = float(offer.get("price", {}).get("total", offer.get("price", 0)))
                pos_prices = {"US": price}

            if not pos_prices:
                return None

            # US price = Google Flights benchmark
            us_price = pos_prices.get("US", 0)

            # Find cheapest POS
            cheapest_pos = min(pos_prices, key=pos_prices.get)
            cheapest_price = pos_prices[cheapest_pos]

            # If no US price, use the max price as benchmark
            if not us_price:
                us_price = max(pos_prices.values())

            # Calculate savings and MYSTES pricing
            savings_raw = us_price - cheapest_price
            if savings_raw > 0:
                platform_fee = savings_raw * PLATFORM_FEE_PERCENT
                platform_fee = max(PLATFORM_FEE_MIN_USD, min(PLATFORM_FEE_MAX_USD, platform_fee))
                mystes_price = cheapest_price + platform_fee
                user_savings = us_price - mystes_price
                savings_pct = (user_savings / us_price * 100) if us_price > 0 else 0
            else:
                # No arbitrage — price at cheapest (which equals US)
                platform_fee = 0
                mystes_price = cheapest_price
                user_savings = 0
                savings_pct = 0

            # Parse itinerary
            itineraries = offer.get("itineraries", offer.get("segments", []))
            segments = []
            for seg_data in (itineraries if isinstance(itineraries, list) else []):
                # Handle nested segments within itineraries
                if "segments" in seg_data:
                    for seg in seg_data["segments"]:
                        segments.append(self._parse_segment(seg))
                else:
                    segments.append(self._parse_segment(seg_data))

            # Primary flight info from first segment
            first_seg = segments[0] if segments else {}
            last_seg = segments[-1] if segments else {}

            # Count stops
            outbound_stops = max(len(segments) - 1, 0)

            # Duration
            duration_str = offer.get("duration", offer.get("totalDuration", ""))
            duration_mins = self._parse_duration(duration_str)
            duration_fmt = self._format_duration(duration_mins)

            # Layovers
            layovers = []
            for i in range(len(segments) - 1):
                arr_time_str = segments[i].get("arrival_time", "")
                dep_time_str = segments[i + 1].get("departure_time", "")
                try:
                    arr_t = datetime.fromisoformat(arr_time_str.replace("Z", "+00:00"))
                    dep_t = datetime.fromisoformat(dep_time_str.replace("Z", "+00:00"))
                    layover_mins = int((dep_t - arr_t).total_seconds() / 60)
                    lh, lm = divmod(layover_mins, 60)
                    layovers.append({
                        "airport": segments[i].get("arrival_airport", ""),
                        "duration_minutes": layover_mins,
                        "duration_formatted": f"{lh}h {lm}m",
                    })
                except (ValueError, TypeError):
                    layovers.append({
                        "airport": segments[i].get("arrival_airport", ""),
                        "duration_minutes": 0,
                        "duration_formatted": "?",
                    })

            return {
                # Identity
                "offer_id": offer.get("id", offer.get("offerId", "")),
                "source": "picasso",

                # Carrier
                "airline": first_seg.get("marketing_carrier", ""),
                "airline_name": first_seg.get("marketing_carrier_name", first_seg.get("marketing_carrier", "")),
                "marketing_carrier": first_seg.get("marketing_carrier", ""),
                "flight_number": first_seg.get("flight_number", ""),

                # Route
                "origin": first_seg.get("departure_airport", ""),
                "destination": last_seg.get("arrival_airport", ""),
                "departure_airport": first_seg.get("departure_airport", ""),
                "arrival_airport": last_seg.get("arrival_airport", ""),
                "departure_time": first_seg.get("departure_time", ""),
                "arrival_time": last_seg.get("arrival_time", ""),

                # Duration
                "duration_minutes": duration_mins,
                "duration_formatted": duration_fmt,
                "duration": duration_fmt,
                "stops": outbound_stops,
                "layovers": layovers,

                # Segments
                "segments": segments,

                # Cabin
                "cabin_class": offer.get("cabinClass", offer.get("cabin", "ECONOMY")),
                "baggage_info": offer.get("baggageInfo", offer.get("baggage", None)),

                # === PRICING (the core arbitrage data) ===
                "price": mystes_price,            # What the user pays
                "mystes_price": mystes_price,     # Same — MYSTES price after fee
                "cheapest_price": cheapest_price,  # Our cost (cheapest POS)
                "us_price": us_price,             # Google benchmark (US POS)
                "savings": round(user_savings, 2),
                "savings_pct": round(savings_pct, 1),
                "platform_fee": round(platform_fee, 2),
                "cheapest_market": cheapest_pos,
                "currency": "USD",

                # POS data (all markets)
                "pos_prices": pos_prices,

                # Deal object (for renderFlightCards compatibility)
                "deal": {
                    "home_price": round(us_price, 2),
                    "arbitrage_price": round(mystes_price, 2),
                    "price_difference": round(user_savings, 2),
                    "user_saves_pct": round(savings_pct, 1),
                    "cheapest_market": cheapest_pos,
                } if user_savings > 0 else None,

                # Raw offer for downstream booking
                "raw_offer": offer,
            }

        except Exception as e:
            print(f"[PICASSO] Error parsing offer: {e}")
            return None

    def _parse_segment(self, seg: Dict) -> Dict:
        """Parse a single flight segment."""
        dep = seg.get("departure", seg)
        arr = seg.get("arrival", seg)

        carrier = seg.get("carrierCode", seg.get("carrier", seg.get("marketingCarrier", "")))
        flight_num = seg.get("number", seg.get("flightNumber", ""))
        if flight_num and not flight_num.startswith(carrier):
            flight_num = f"{carrier}{flight_num}"

        return {
            "carrier": carrier,
            "marketing_carrier": carrier,
            "marketing_carrier_name": seg.get("carrierName", seg.get("airlineName", carrier)),
            "flight_number": flight_num,
            "departure_airport": dep.get("iataCode", dep.get("airport", dep.get("origin", ""))),
            "departure_terminal": dep.get("terminal", ""),
            "departure_time": dep.get("at", dep.get("dateTime", dep.get("departureTime", ""))),
            "arrival_airport": arr.get("iataCode", arr.get("airport", arr.get("destination", ""))),
            "arrival_terminal": arr.get("terminal", ""),
            "arrival_time": arr.get("at", arr.get("dateTime", arr.get("arrivalTime", ""))),
            "aircraft_code": seg.get("aircraft", {}).get("code", seg.get("aircraftCode", "")),
            "aircraft_name": seg.get("aircraft", {}).get("name", seg.get("aircraftName", "")),
            "operating_carrier": seg.get("operatingCarrier", carrier),
            "is_codeshare": bool(seg.get("operatingCarrier") and seg.get("operatingCarrier") != carrier),
        }

    # -------------------------------------------------------------------------
    # Price Confirm (Pre-booking validation)
    # -------------------------------------------------------------------------

    def price_confirm(self, offer_id: str, pos_market: str = None) -> Dict:
        """
        Confirm pricing for a specific offer before booking.

        Args:
            offer_id: Offer ID from search results
            pos_market: POS market to confirm price in (the cheapest one)

        Returns:
            Dict with success, confirmed_price, pos_market, bookable
        """
        if not self.is_configured():
            return {"success": False, "error": "Picasso not configured"}

        if not self._authenticate():
            return {"success": False, "error": "Authentication failed"}

        payload = {"offerId": offer_id}
        if pos_market:
            payload["pointOfSale"] = pos_market

        print(f"[PICASSO] Confirming price for offer {offer_id[:30]}... (POS: {pos_market or 'best'})")

        try:
            response = requests.post(
                f"{BASE_URL}/flights/price-confirm",
                headers=self._headers(),
                json=payload,
                timeout=20,
            )
            response.raise_for_status()
            data = response.json()
        except requests.exceptions.HTTPError as e:
            error = self._parse_error(e.response)
            return {"success": False, "error": error}
        except Exception as e:
            return {"success": False, "error": str(e)}

        confirmed = data.get("data", data)
        price = float(confirmed.get("price", confirmed.get("total", 0)))
        confirmed_pos = confirmed.get("pointOfSale", confirmed.get("pos", pos_market))

        print(f"[PICASSO] Price confirmed: ${price} (POS: {confirmed_pos})")
        return {
            "success": True,
            "confirmed_price": price,
            "currency": confirmed.get("currency", "USD"),
            "pos_market": confirmed_pos,
            "bookable": confirmed.get("bookable", True),
            "confirmed_offer": confirmed,
        }

    # -------------------------------------------------------------------------
    # Book: Create Flight Order
    # -------------------------------------------------------------------------

    def create_booking(
        self,
        offer_id: str,
        travelers: List[Dict],
        pos_market: str = None,
        contact_email: str = None,
    ) -> Dict:
        """
        Book a flight via Picasso Cockpit API.

        Picasso issues the ticket through their IATA subsidiary in the
        specified POS market. No IATA accreditation needed on our end.

        Args:
            offer_id: Offer ID from search/price-confirm
            travelers: List of passenger dicts:
                - first_name, last_name (required)
                - date_of_birth (YYYY-MM-DD)
                - gender (MALE/FEMALE)
                - email, phone
                - passport_number, passport_expiry, passport_country (international)
            pos_market: POS market for ticket issuance (cheapest)
            contact_email: Primary contact email

        Returns:
            Dict with success, booking_id, pnr, segments, price
        """
        if not self.is_configured():
            return {"success": False, "error": "Picasso not configured"}

        if not self._authenticate():
            return {"success": False, "error": "Authentication failed"}

        if not travelers:
            return {"success": False, "error": "At least one traveler is required"}

        # Build traveler objects
        traveler_objects = []
        for idx, t in enumerate(travelers, start=1):
            traveler_obj = {
                "id": str(idx),
                "firstName": t.get("first_name", "").upper(),
                "lastName": t.get("last_name", "").upper(),
                "dateOfBirth": t.get("date_of_birth", "1990-01-01"),
                "gender": t.get("gender", "MALE").upper(),
                "email": t.get("email", contact_email or ""),
                "phone": t.get("phone", ""),
            }
            if t.get("passport_number"):
                traveler_obj["document"] = {
                    "type": "PASSPORT",
                    "number": t["passport_number"],
                    "expiryDate": t.get("passport_expiry", "2030-01-01"),
                    "issuanceCountry": t.get("passport_country", "US"),
                    "nationality": t.get("nationality", "US"),
                }
            traveler_objects.append(traveler_obj)

        payload = {
            "offerId": offer_id,
            "travelers": traveler_objects,
        }
        if pos_market:
            payload["pointOfSale"] = pos_market
        if contact_email:
            payload["contactEmail"] = contact_email

        print(f"[PICASSO] Booking offer {offer_id[:30]}... ({len(travelers)} pax, POS: {pos_market or 'best'})")

        try:
            response = requests.post(
                f"{BASE_URL}/flights/book",
                headers=self._headers(),
                json=payload,
                timeout=60,
            )
            response.raise_for_status()
            data = response.json()
        except requests.exceptions.HTTPError as e:
            error = self._parse_error(e.response)
            print(f"[PICASSO] Booking error: {error}")
            return {"success": False, "error": error}
        except Exception as e:
            print(f"[PICASSO] Booking error: {e}")
            return {"success": False, "error": str(e)}

        order = data.get("data", data)
        booking_id = order.get("bookingId", order.get("id", ""))
        pnr = order.get("pnr", order.get("recordLocator", order.get("confirmationCode", "")))
        price = float(order.get("price", {}).get("total", order.get("totalPrice", 0)))

        # Extract segments
        segments = []
        for seg in order.get("segments", order.get("itinerary", {}).get("segments", [])):
            segments.append({
                "origin": seg.get("departure", {}).get("iataCode", seg.get("origin", "")),
                "destination": seg.get("arrival", {}).get("iataCode", seg.get("destination", "")),
                "departure": seg.get("departure", {}).get("at", seg.get("departureTime", "")),
                "arrival": seg.get("arrival", {}).get("at", seg.get("arrivalTime", "")),
                "carrier": seg.get("carrierCode", seg.get("carrier", "")),
                "flight_number": seg.get("number", seg.get("flightNumber", "")),
            })

        print(f"[PICASSO] Booking created: PNR={pnr}, {len(travelers)} pax, ${price}")
        return {
            "success": True,
            "booking_id": booking_id,
            "pnr": pnr,
            "provider": "picasso",
            "segments": segments,
            "price": price,
            "currency": order.get("currency", "USD"),
            "pos_market": pos_market,
            "travelers_booked": len(travelers),
            "raw_order": order,
        }

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _parse_error(self, response) -> str:
        """Extract error message from API response."""
        try:
            data = response.json()
            if "error" in data:
                err = data["error"]
                if isinstance(err, dict):
                    return err.get("message", f"HTTP {response.status_code}")
                return str(err)
            if "errors" in data:
                errors = data["errors"]
                if isinstance(errors, list) and errors:
                    return errors[0].get("detail", errors[0].get("message", f"HTTP {response.status_code}"))
            return data.get("message", f"HTTP {response.status_code}")
        except Exception:
            return f"HTTP {response.status_code}"

    def _parse_duration(self, duration_input) -> int:
        """Parse duration to minutes. Handles ISO 8601 (PT14H30M) and plain minutes."""
        if isinstance(duration_input, (int, float)):
            return int(duration_input)
        if not duration_input or not isinstance(duration_input, str):
            return 0
        try:
            s = duration_input.replace("PT", "")
            hours = 0
            minutes = 0
            if "H" in s:
                parts = s.split("H")
                hours = int(parts[0])
                s = parts[1] if len(parts) > 1 else ""
            if "M" in s:
                minutes = int(s.replace("M", ""))
            return hours * 60 + minutes
        except (ValueError, IndexError):
            return 0

    def _format_duration(self, minutes: int) -> str:
        """Format minutes to 'Xh Ym'."""
        if minutes <= 0:
            return ""
        h, m = divmod(minutes, 60)
        if h and m:
            return f"{h}h {m}m"
        elif h:
            return f"{h}h"
        else:
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


def search_flights_multi_pos(
    origin: str,
    destination: str,
    departure_date: str,
    return_date: Optional[str] = None,
    adults: int = 1,
    cabin_class: str = "economy",
    max_results: int = 15,
    nonstop_only: bool = False,
) -> Dict:
    """
    Module-level convenience — search flights with multi-POS arbitrage.

    Drop-in replacement for amadeus_client.search_with_amadeus().
    Returns the same flight dict shape with added arbitrage pricing fields.
    """
    cabin_map = {
        "economy": "ECONOMY",
        "premium_economy": "PREMIUM_ECONOMY",
        "business": "BUSINESS",
        "first": "FIRST",
    }
    mapped_cabin = cabin_map.get(cabin_class.lower(), "ECONOMY")

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
    """Alias — same interface as amadeus_client.search_with_amadeus()."""
    return search_flights_multi_pos(
        origin=origin,
        destination=destination,
        departure_date=departure_date,
        return_date=return_date,
        adults=adults,
        cabin_class=cabin_class,
    )
