"""
liteAPI Hotel Client for MYSTES

Single-call hotel search + two-step booking (prebook → book).
Replaces amadeus_hotel_client.py (Amadeus Self-Service discontinued).

liteAPI docs: https://docs.liteapi.travel
Base URL: https://api.liteapi.travel/v3.0/
Auth: X-API-Key header (no OAuth token exchange).

Usage:
    from liteapi_client import LiteAPIHotelClient, search_hotels

    result = search_hotels("PAR", check_in="2026-03-15", check_out="2026-03-18")
    if result["success"]:
        for hotel in result["hotels"]:
            print(hotel["hotel_name"], hotel["price_per_night"], hotel["currency"])
"""

import os
import requests
from datetime import datetime, timedelta
from typing import List, Dict, Optional

from dotenv import load_dotenv
load_dotenv()

BASE_URL = "https://api.liteapi.travel/v3.0"


class LiteAPIHotelClient:
    """
    liteAPI Hotel Search + Booking client.

    Search:  POST /hotels/rates
    Prebook: POST /rates/prebook  (validates offer + returns prebookId)
    Book:    POST /rates/book

    Set LITEAPI_KEY in .env (sandbox keys start with 'sand_').
    """

    def __init__(self):
        self.api_key = os.environ.get("LITEAPI_KEY", "")

    def _headers(self) -> Dict[str, str]:
        return {
            "X-API-Key": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def is_configured(self) -> bool:
        return bool(self.api_key)

    # -------------------------------------------------------------------------
    # Search: POST /hotels/rates
    # -------------------------------------------------------------------------

    def search_hotels(
        self,
        city_code: str,
        check_in: Optional[str] = None,
        check_out: Optional[str] = None,
        adults: int = 1,
        rooms: int = 1,
        currency: str = "USD",
        ratings: Optional[List[int]] = None,
        max_hotels: int = 20,
        user=None,
    ) -> Dict:
        """
        Search hotels by IATA city/airport code via liteAPI.

        Single API call replaces Amadeus two-step (hotel list + offers).

        Args:
            city_code: IATA city/airport code (PAR, NYC, LON, TYO)
            check_in: YYYY-MM-DD (default: tomorrow)
            check_out: YYYY-MM-DD (default: check_in + 1)
            adults: Adults per room
            rooms: Number of rooms
            currency: Price currency
            ratings: Star rating filter [3, 4, 5]
            max_hotels: Max hotels to return

        Returns:
            Dict with success, hotels list (with pricing), source
        """
        if not self.is_configured():
            return {"success": False, "hotels": [], "error": "liteAPI not configured (LITEAPI_KEY missing)"}

        # Date defaults
        if not check_in:
            check_in = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        if not check_out:
            ci = datetime.strptime(check_in, "%Y-%m-%d")
            check_out = (ci + timedelta(days=1)).strftime("%Y-%m-%d")

        ci_date = datetime.strptime(check_in, "%Y-%m-%d")
        co_date = datetime.strptime(check_out, "%Y-%m-%d")
        nights = max((co_date - ci_date).days, 1)

        # Build occupancies list (one per room)
        occupancies = [{"adults": adults, "children": []} for _ in range(rooms)]

        # Resolve IATA code to city name + country code for liteAPI
        # liteAPI works best with cityName + countryCode (iataCode is unreliable)
        # Hotels use city codes (PAR, NYC, LON) — airports module only has airport codes (CDG, JFK, LHR)
        city_name = None
        country_code = None

        # City code → city name mapping (hotel search form uses these)
        CITY_CODES = {
            "PAR": ("Paris", "FR"), "NYC": ("New York", "US"), "LON": ("London", "GB"),
            "TYO": ("Tokyo", "JP"), "ROM": ("Rome", "IT"), "BCN": ("Barcelona", "ES"),
            "BKK": ("Bangkok", "TH"), "DXB": ("Dubai", "AE"), "SIN": ("Singapore", "SG"),
            "LAX": ("Los Angeles", "US"), "SFO": ("San Francisco", "US"), "MIA": ("Miami", "US"),
            "CHI": ("Chicago", "US"), "SYD": ("Sydney", "AU"), "HKG": ("Hong Kong", "HK"),
            "SEL": ("Seoul", "KR"), "AMS": ("Amsterdam", "NL"), "BER": ("Berlin", "DE"),
            "MAD": ("Madrid", "ES"), "LIS": ("Lisbon", "PT"), "IST": ("Istanbul", "TR"),
            "MEX": ("Mexico City", "MX"), "YTO": ("Toronto", "CA"), "OSA": ("Osaka", "JP"),
            "MUC": ("Munich", "DE"), "VIE": ("Vienna", "AT"), "PRG": ("Prague", "CZ"),
            "DUB": ("Dublin", "IE"), "ATH": ("Athens", "GR"), "HNL": ("Honolulu", "US"),
        }

        code_upper = city_code.upper()
        if code_upper in CITY_CODES:
            city_name, country_code = CITY_CODES[code_upper]
        else:
            # Try airports module (airport codes like CDG, JFK, LHR)
            try:
                from airports import AIRPORTS
                info = AIRPORTS.get(code_upper)
                if info:
                    city_name = info.get("city")
                    country_code = info.get("country_code")
            except ImportError:
                pass

        payload = {
            "checkin": check_in,
            "checkout": check_out,
            "currency": currency,
            "guestNationality": "US",
            "occupancies": occupancies,
            "limit": max_hotels,
            "timeout": 10,
        }

        if city_name and country_code:
            payload["cityName"] = city_name
            payload["countryCode"] = country_code
        else:
            # Fallback: try iataCode directly
            payload["iataCode"] = city_code.upper()

        if ratings:
            payload["starRating"] = ratings

        print(f"[LITEAPI] Searching hotels in {city_code} ({check_in} to {check_out})...")

        try:
            response = requests.post(
                f"{BASE_URL}/hotels/rates",
                headers=self._headers(),
                json=payload,
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()
        except requests.exceptions.HTTPError as e:
            error = self._parse_error(e.response)
            print(f"[LITEAPI] Search error: {error}")
            return {"success": False, "hotels": [], "error": error,
                    "source": "liteapi", "check_in": check_in, "check_out": check_out}
        except Exception as e:
            print(f"[LITEAPI] Search error: {e}")
            return {"success": False, "hotels": [], "error": str(e),
                    "source": "liteapi", "check_in": check_in, "check_out": check_out}

        raw_hotels = data.get("data", [])
        if raw_hotels is None:
            raw_hotels = []
        print(f"[LITEAPI] Found {len(raw_hotels)} hotels in {city_code}")

        # Fetch hotel names in one bulk call (rates endpoint doesn't include them)
        hotel_names = {}
        try:
            name_params = {}
            if city_name and country_code:
                name_params = {"cityName": city_name, "countryCode": country_code}
            else:
                name_params = {"hotelId": ",".join(h.get("hotelId", "") for h in raw_hotels[:max_hotels] if h.get("hotelId"))}
            resp = requests.get(
                f"{BASE_URL}/data/hotels",
                params=name_params,
                headers=self._headers(),
                timeout=15,
            )
            if resp.status_code == 200:
                for hdata in resp.json().get("data", []):
                    hid = hdata.get("id", hdata.get("hotelId", ""))
                    if hid:
                        hotel_names[hid] = hdata.get("name", "Unknown Hotel")
        except Exception:
            pass  # Names are nice-to-have, not critical

        hotels = []
        for raw_hotel in raw_hotels[:max_hotels]:
            hotel_id = raw_hotel.get("hotelId", "")
            hotel_name = hotel_names.get(hotel_id, raw_hotel.get("name", "Unknown Hotel"))

            room_types = raw_hotel.get("roomTypes", [])
            if not room_types:
                continue

            # Take first room type with an offer
            room_type_obj = room_types[0]
            offer_id = room_type_obj.get("offerId", "")
            rates_list = room_type_obj.get("rates", [])
            if not rates_list:
                continue
            rate = rates_list[0]

            # --- Pricing ---
            retail = rate.get("retailRate", {})
            total_list = retail.get("total", [])
            price_total_obj = next(
                (t for t in total_list if t.get("currency") == currency),
                total_list[0] if total_list else {},
            )
            price_total = float(price_total_obj.get("amount", 0))
            price_currency = price_total_obj.get("currency", currency)
            price_per_night = round(price_total / nights, 2) if nights > 0 else price_total

            # Base price (offer-level retail rate = our net cost)
            offer_retail = room_type_obj.get("offerRetailRate", {})
            price_base = float(offer_retail.get("amount", price_total))

            # Google/retail benchmark (suggestedSellingPrice — NOT offerInitialPrice which equals our cost)
            suggested = room_type_obj.get("suggestedSellingPrice", {})
            if not suggested or not isinstance(suggested, dict) or not suggested.get("amount"):
                # Fallback: check inside retail rate
                ssp_list = rate.get("retailRate", {}).get("suggestedSellingPrice", [])
                if ssp_list and isinstance(ssp_list, list) and ssp_list:
                    suggested = ssp_list[0]
            google_price = float(suggested.get("amount", 0)) if isinstance(suggested, dict) else 0

            # Margin filter: skip hotels where our cost >= Google price (no arbitrage)
            if google_price > 0 and price_base >= google_price:
                continue  # Inverted margin — skip this hotel

            # Calculate savings vs Google benchmark
            if google_price > 0:
                savings_raw = google_price - price_base
                # MYSTES fee based on membership status
                from payments import get_fee_percent
                platform_fee = round(savings_raw * get_fee_percent(user), 2)
                mystes_price = price_base + platform_fee
                user_savings = google_price - mystes_price
                savings_pct = round((user_savings / google_price * 100), 1) if google_price > 0 else 0
                mystes_per_night = round(mystes_price / nights, 2) if nights > 0 else mystes_price
            else:
                # No benchmark available — show at our price with flat fee
                platform_fee = 15.00
                mystes_price = price_total + platform_fee
                user_savings = 0
                savings_pct = 0
                mystes_per_night = round(mystes_price / nights, 2) if nights > 0 else mystes_price

            # --- Room info ---
            room_name = rate.get("name", "Standard Room")
            board_name = rate.get("boardName", "")  # e.g. "Room Only", "Bed and Breakfast"
            board_type = rate.get("boardType", "")   # e.g. "RO", "BB"

            # --- Cancellation ---
            cancel_policies = rate.get("cancellationPolicies", {})
            cancel_deadline = None
            cancel_desc = None
            if isinstance(cancel_policies, dict):
                policy_infos = cancel_policies.get("cancelPolicyInfos", [])
                if policy_infos:
                    cancel_deadline = policy_infos[0].get("cancelTime")
                refundable_tag = cancel_policies.get("refundableTag", "")
                if refundable_tag == "RFN":
                    cancel_desc = "Free cancellation"
                elif refundable_tag == "NRFN":
                    cancel_desc = "Non-refundable"
                elif refundable_tag:
                    cancel_desc = refundable_tag

            hotels.append({
                # Identity
                "hotel_id": hotel_id,
                "hotel_name": hotel_name,
                "offer_id": offer_id,
                "city_code": city_code.upper(),
                # Dates
                "check_in": check_in,
                "check_out": check_out,
                "nights": nights,
                # Pricing — MYSTES price (what user pays)
                "price_total": round(mystes_price, 2),
                "price_base": round(price_base, 2),
                "price_per_night": mystes_per_night,
                "currency": price_currency,
                # Savings vs Google
                "google_price": round(google_price, 2) if google_price > 0 else None,
                "our_cost": round(price_base, 2),
                "platform_fee": round(platform_fee, 2),
                "user_savings": round(user_savings, 2),
                "savings_pct": savings_pct,
                # Room
                "room_type": room_name,
                "bed_type": board_type,
                "room_description": board_name,
                # Cancellation
                "cancellation_deadline": cancel_deadline,
                "cancellation_description": cancel_desc,
                # Occupancy
                "adults": adults,
                "rooms": rooms,
                "source": "liteapi",
                # Raw offer for downstream booking
                "raw_offer": rate,
            })

        print(f"[LITEAPI] Returning {len(hotels)} hotel offers")
        return {
            "success": len(hotels) > 0,
            "hotels": hotels,
            "source": "liteapi",
            "check_in": check_in,
            "check_out": check_out,
        }

    # -------------------------------------------------------------------------
    # Validate: POST /rates/prebook
    # -------------------------------------------------------------------------

    def validate_offer(self, offer_id: str) -> Dict:
        """
        Validate a hotel offer via liteAPI prebook.

        Returns prebookId which is required for create_booking().

        Args:
            offer_id: Offer ID from search results

        Returns:
            Dict with success, available, price, currency, prebook_id
        """
        if not self.is_configured():
            return {"success": False, "available": False, "error": "liteAPI not configured"}

        print(f"[LITEAPI] Prebooking offer {offer_id[:50]}...")

        try:
            response = requests.post(
                f"{BASE_URL}/rates/prebook",
                headers=self._headers(),
                json={"offerId": offer_id},
                timeout=20,
            )
            response.raise_for_status()
            data = response.json()
        except requests.exceptions.HTTPError as e:
            error = self._parse_error(e.response)
            print(f"[LITEAPI] Prebook error: {error}")
            return {"success": False, "available": False, "error": error}
        except Exception as e:
            print(f"[LITEAPI] Prebook error: {e}")
            return {"success": False, "available": False, "error": str(e)}

        prebook_data = data.get("data", {})
        if prebook_data is None:
            prebook_data = {}
        prebook_id = prebook_data.get("prebookId")

        if not prebook_id:
            return {
                "success": False,
                "available": False,
                "error": "No prebookId returned — offer may be unavailable",
            }

        # Extract updated price
        price = 0.0
        price_currency = "USD"
        offer_price = prebook_data.get("offerRetailRate", {})
        if offer_price:
            price = float(offer_price.get("amount", 0))
            price_currency = offer_price.get("currency", "USD")

        print(f"[LITEAPI] Prebook OK: prebookId={prebook_id}, price={price} {price_currency}")
        return {
            "success": True,
            "available": True,
            "price": price,
            "currency": price_currency,
            "prebook_id": prebook_id,
            "offer": prebook_data,
        }

    # -------------------------------------------------------------------------
    # Book: POST /rates/book
    # -------------------------------------------------------------------------

    def create_booking(
        self,
        offer_id: str,
        guest: Dict,
        payment: Optional[Dict] = None,
        prebook_id: Optional[str] = None,
        client_reference: Optional[str] = None,
    ) -> Dict:
        """
        Book a hotel room via liteAPI.

        Requires prebook_id from validate_offer() — call validate first.
        Payment uses ACC_CREDIT_CARD (charges the card on your liteAPI dashboard).

        Args:
            offer_id: Offer ID (kept for interface compat)
            guest: {first_name, last_name, email, phone, special_requests}
            payment: Optional override. Default: ACC_CREDIT_CARD
            prebook_id: From validate_offer() — required
            client_reference: Optional booking reference for tracking

        Returns:
            Dict with success, booking_id, provider_confirmation
        """
        if not self.is_configured():
            return {"success": False, "error": "liteAPI not configured"}

        if not prebook_id:
            return {
                "success": False,
                "error": "prebook_id is required for liteAPI booking. Call validate_offer() first.",
            }

        first_name = guest.get("first_name", "")
        last_name = guest.get("last_name", "")

        payload = {
            "prebookId": prebook_id,
            "holder": {
                "firstName": first_name,
                "lastName": last_name,
                "email": guest.get("email", ""),
                "phone": guest.get("phone", ""),
            },
            "guests": [
                {
                    "occupancyNumber": 1,
                    "firstName": first_name,
                    "lastName": last_name,
                    "email": guest.get("email", ""),
                    "phone": guest.get("phone", ""),
                    "remarks": guest.get("special_requests", ""),
                }
            ],
            "payment": payment or {"method": "ACC_CREDIT_CARD"},
        }

        if client_reference:
            payload["clientReference"] = client_reference

        print(f"[LITEAPI] Booking with prebookId={prebook_id}...")

        try:
            response = requests.post(
                f"{BASE_URL}/rates/book",
                headers=self._headers(),
                json=payload,
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()
        except requests.exceptions.HTTPError as e:
            error = self._parse_error(e.response)
            print(f"[LITEAPI] Booking error: {error}")
            return {"success": False, "error": error}
        except Exception as e:
            print(f"[LITEAPI] Booking error: {e}")
            return {"success": False, "error": str(e)}

        book_data = data.get("data", {})
        if book_data is None:
            book_data = {}
        booking_id = book_data.get("bookingId") or book_data.get("id")
        provider_ref = book_data.get("refNumber") or book_data.get("confirmationCode")

        print(f"[LITEAPI] Booking created: {booking_id}, ref={provider_ref}")
        return {
            "success": True,
            "booking_id": booking_id,
            "provider_confirmation": provider_ref,
            "raw_order": book_data,
        }

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _parse_error(self, response) -> str:
        try:
            data = response.json()
            if "error" in data:
                err = data["error"]
                if isinstance(err, dict):
                    return err.get("message", f"HTTP {response.status_code}")
                return str(err)
            return data.get("message", f"HTTP {response.status_code}")
        except Exception:
            return f"HTTP {response.status_code}"


# ---------------------------------------------------------------------------
# Module-level convenience (drop-in for amadeus_hotel_client.search_hotels)
# ---------------------------------------------------------------------------

_hotel_client: Optional[LiteAPIHotelClient] = None


def _get_client() -> LiteAPIHotelClient:
    global _hotel_client
    if _hotel_client is None:
        _hotel_client = LiteAPIHotelClient()
    return _hotel_client


def search_hotels(
    city_code: str,
    check_in: Optional[str] = None,
    check_out: Optional[str] = None,
    adults: int = 1,
    rooms: int = 1,
    currency: str = "USD",
    ratings: Optional[List[int]] = None,
    max_hotels: int = 20,
    user=None,
) -> Dict:
    """Module-level convenience — drop-in replacement for amadeus_hotel_client.search_hotels."""
    return _get_client().search_hotels(
        city_code=city_code,
        check_in=check_in,
        check_out=check_out,
        adults=adults,
        rooms=rooms,
        currency=currency,
        ratings=ratings,
        max_hotels=max_hotels,
        user=user,
    )
