"""
Amadeus Hotel API Client for PHOENIX

Two-step hotel search:
  1. Hotel List API → find hotels by city code → get Amadeus hotelIds
  2. Hotel Search API v3 → get offers/prices for those hotels

Plus booking:
  3. Hotel Booking API → book a specific offer → confirmation

Uses same credentials and environment as amadeus_client.py.

Usage:
    from amadeus_hotel_client import AmadeusHotelClient, search_hotels

    result = search_hotels("PAR", check_in="2026-03-15", check_out="2026-03-18")
    if result["success"]:
        for hotel in result["hotels"]:
            print(hotel["name"], hotel["price_per_night"], hotel["currency"])
"""

import os
import requests
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import json

from dotenv import load_dotenv
load_dotenv()


class AmadeusHotelClient:
    """
    Amadeus Hotel Search + Booking API client.

    Hotel List: GET /v1/reference-data/locations/hotels/by-city
    Hotel Search v3: GET /v3/shopping/hotel-offers
    Hotel Offer: GET /v3/shopping/hotel-offers/{offerId}
    Hotel Booking: POST /v2/booking/hotel-orders

    Set AMADEUS_ENV=production in .env for real inventory.
    """

    ENVIRONMENTS = {
        "test": "https://test.api.amadeus.com",
        "production": "https://api.amadeus.com",
    }

    def __init__(self):
        self.api_key = os.environ.get("AMADEUS_API_KEY", "")
        self.api_secret = os.environ.get("AMADEUS_API_SECRET", "")
        self._access_token = None
        self._token_expires_at = None

        env = os.environ.get("AMADEUS_ENV", "test").lower()
        self.BASE_URL = self.ENVIRONMENTS.get(env, self.ENVIRONMENTS["test"])
        self._env = env

    def _get_access_token(self) -> Optional[str]:
        """Get OAuth2 access token (cached)."""
        if self._access_token and self._token_expires_at and datetime.now() < self._token_expires_at:
            return self._access_token

        try:
            response = requests.post(
                f"{self.BASE_URL}/v1/security/oauth2/token",
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
            self._access_token = data["access_token"]
            self._token_expires_at = datetime.now() + timedelta(seconds=data.get("expires_in", 1799) - 60)
            return self._access_token
        except Exception as e:
            print(f"[AMADEUS HOTEL] Auth error: {e}")
            return None

    def is_configured(self) -> bool:
        return bool(self.api_key and self.api_secret)

    # -------------------------------------------------------------------------
    # Step 1: Hotel List — find hotels by city
    # -------------------------------------------------------------------------

    def search_hotels_by_city(
        self,
        city_code: str,
        radius: int = 20,
        radius_unit: str = "KM",
        chain_codes: Optional[List[str]] = None,
        ratings: Optional[List[int]] = None,
        hotel_source: str = "ALL",
    ) -> Dict:
        """
        Find hotels in a city. Returns Amadeus hotelIds for step 2.

        Args:
            city_code: IATA city code (e.g., "PAR", "NYC", "LON")
            radius: Search radius from city center
            radius_unit: KM or MILE
            chain_codes: Filter by chain (e.g., ["MC", "HH"] for Marriott, Hilton)
            ratings: Filter by star rating (e.g., [3, 4, 5])
            hotel_source: ALL, DIRECTCHAIN, or BEDBANK

        Returns:
            Dict with success, hotels list (id, name, city, lat/lon)
        """
        token = self._get_access_token()
        if not token:
            return {"success": False, "hotels": [], "error": "Authentication failed"}

        params = {
            "cityCode": city_code.upper(),
            "radius": radius,
            "radiusUnit": radius_unit,
            "hotelSource": hotel_source,
        }
        if chain_codes:
            params["chainCodes"] = ",".join(chain_codes)
        if ratings:
            params["ratings"] = ",".join(str(r) for r in ratings)

        print(f"[AMADEUS HOTEL] Finding hotels in {city_code}...")

        try:
            response = requests.get(
                f"{self.BASE_URL}/v1/reference-data/locations/hotels/by-city",
                params=params,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                },
                timeout=20,
            )

            if response.status_code == 200:
                data = response.json()
                raw_hotels = data.get("data", [])
                print(f"[AMADEUS HOTEL] Found {len(raw_hotels)} hotels in {city_code}")

                hotels = []
                for h in raw_hotels:
                    hotels.append({
                        "hotel_id": h.get("hotelId"),
                        "name": h.get("name", "Unknown Hotel"),
                        "chain_code": h.get("chainCode"),
                        "city_code": h.get("iataCode"),
                        "latitude": h.get("geoCode", {}).get("latitude"),
                        "longitude": h.get("geoCode", {}).get("longitude"),
                        "country_code": h.get("address", {}).get("countryCode"),
                    })

                return {"success": True, "hotels": hotels, "source": "amadeus"}

            else:
                error = self._parse_error(response)
                print(f"[AMADEUS HOTEL] Error: {error}")
                return {"success": False, "hotels": [], "error": error}

        except Exception as e:
            print(f"[AMADEUS HOTEL] Error: {e}")
            return {"success": False, "hotels": [], "error": str(e)}

    # -------------------------------------------------------------------------
    # Step 2: Hotel Search v3 — get offers/prices
    # -------------------------------------------------------------------------

    def search_hotel_offers(
        self,
        hotel_ids: List[str],
        check_in: Optional[str] = None,
        check_out: Optional[str] = None,
        adults: int = 1,
        rooms: int = 1,
        currency: str = "USD",
        best_rate_only: bool = True,
    ) -> Dict:
        """
        Search hotel offers (prices) for specific hotels.

        Args:
            hotel_ids: List of Amadeus hotel IDs (from step 1, max ~50 per call)
            check_in: YYYY-MM-DD (default: tomorrow)
            check_out: YYYY-MM-DD (default: check_in + 1)
            adults: Number of adults per room
            rooms: Number of rooms
            currency: Price currency
            best_rate_only: Only return cheapest offer per hotel

        Returns:
            Dict with success, hotels list with pricing
        """
        token = self._get_access_token()
        if not token:
            return {"success": False, "hotels": [], "error": "Authentication failed"}

        if not check_in:
            check_in = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        if not check_out:
            ci = datetime.strptime(check_in, "%Y-%m-%d")
            check_out = (ci + timedelta(days=1)).strftime("%Y-%m-%d")

        # API accepts max ~50 hotel IDs per request
        batch_size = 50
        all_hotels = []

        for i in range(0, len(hotel_ids), batch_size):
            batch = hotel_ids[i:i + batch_size]

            params = {
                "hotelIds": ",".join(batch),
                "adults": adults,
                "checkInDate": check_in,
                "checkOutDate": check_out,
                "roomQuantity": rooms,
                "currency": currency,
                "bestRateOnly": str(best_rate_only).lower(),
            }

            print(f"[AMADEUS HOTEL] Searching offers for {len(batch)} hotels "
                  f"({check_in} to {check_out}, {currency})...")

            try:
                response = requests.get(
                    f"{self.BASE_URL}/v3/shopping/hotel-offers",
                    params=params,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/json",
                    },
                    timeout=30,
                )

                if response.status_code == 200:
                    data = response.json()
                    raw_results = data.get("data", [])

                    for result in raw_results:
                        hotel_info = result.get("hotel", {})
                        offers = result.get("offers", [])

                        for offer in offers:
                            price_obj = offer.get("price", {})
                            total = float(price_obj.get("total", 0))
                            curr = price_obj.get("currency", currency)
                            base = float(price_obj.get("base", 0))

                            # Calculate nights
                            ci_date = datetime.strptime(check_in, "%Y-%m-%d")
                            co_date = datetime.strptime(check_out, "%Y-%m-%d")
                            nights = max((co_date - ci_date).days, 1)
                            price_per_night = round(total / nights, 2)

                            # Room info
                            room = offer.get("room", {})
                            room_type = room.get("typeEstimated", {})
                            room_desc = room.get("description", {}).get("text", "")

                            # Policies
                            policies = offer.get("policies", {})
                            cancellation = policies.get("cancellation", {})
                            payment = policies.get("guarantee", {}).get("acceptedPayments", {})

                            parsed = {
                                "hotel_id": hotel_info.get("hotelId"),
                                "hotel_name": hotel_info.get("name", "Unknown Hotel"),
                                "chain_code": hotel_info.get("chainCode"),
                                "city_code": hotel_info.get("cityCode"),
                                "latitude": hotel_info.get("latitude"),
                                "longitude": hotel_info.get("longitude"),

                                "offer_id": offer.get("id"),
                                "check_in": offer.get("checkInDate", check_in),
                                "check_out": offer.get("checkOutDate", check_out),
                                "nights": nights,

                                "price_total": total,
                                "price_base": base,
                                "price_per_night": price_per_night,
                                "currency": curr,
                                "taxes": price_obj.get("taxes"),
                                "commission": offer.get("commission"),

                                "room_type": room_type.get("category", "STANDARD"),
                                "bed_type": room_type.get("bedType"),
                                "beds": room_type.get("beds"),
                                "room_description": room_desc,

                                "cancellation_deadline": cancellation.get("deadline"),
                                "cancellation_description": cancellation.get("description", {}).get("text"),
                                "payment_methods": payment.get("methods", []),

                                "adults": adults,
                                "rooms": rooms,
                                "source": "amadeus",

                                # Raw offer for booking
                                "raw_offer": offer,
                            }

                            all_hotels.append(parsed)

                elif response.status_code == 400:
                    error = self._parse_error(response)
                    print(f"[AMADEUS HOTEL] Batch error: {error}")
                else:
                    print(f"[AMADEUS HOTEL] HTTP {response.status_code}")

            except Exception as e:
                print(f"[AMADEUS HOTEL] Batch error: {e}")

        print(f"[AMADEUS HOTEL] Found {len(all_hotels)} hotel offers")
        return {
            "success": len(all_hotels) > 0,
            "hotels": all_hotels,
            "source": "amadeus",
            "check_in": check_in,
            "check_out": check_out,
        }

    # -------------------------------------------------------------------------
    # Combined: City → Hotels → Offers (convenience method)
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
    ) -> Dict:
        """
        Full hotel search: find hotels in city → get prices.

        Args:
            city_code: IATA city code (PAR, NYC, LON, TYO)
            check_in: YYYY-MM-DD
            check_out: YYYY-MM-DD
            adults: Adults per room
            rooms: Number of rooms
            currency: Price currency
            ratings: Star rating filter [3, 4, 5]
            max_hotels: Max hotels to price (API limits apply)

        Returns:
            Dict with success, hotels (with pricing), source
        """
        if not self.is_configured():
            return {"success": False, "hotels": [], "error": "Amadeus not configured"}

        # Step 1: Find hotels
        list_result = self.search_hotels_by_city(
            city_code=city_code,
            ratings=ratings,
        )

        if not list_result["success"] or not list_result["hotels"]:
            return {
                "success": False,
                "hotels": [],
                "error": list_result.get("error", "No hotels found"),
            }

        # Take top N hotels by ID
        hotel_ids = [h["hotel_id"] for h in list_result["hotels"][:max_hotels] if h.get("hotel_id")]

        if not hotel_ids:
            return {"success": False, "hotels": [], "error": "No valid hotel IDs"}

        # Step 2: Get prices
        offers_result = self.search_hotel_offers(
            hotel_ids=hotel_ids,
            check_in=check_in,
            check_out=check_out,
            adults=adults,
            rooms=rooms,
            currency=currency,
        )

        return offers_result

    # -------------------------------------------------------------------------
    # Step 3: Validate offer (real-time price check)
    # -------------------------------------------------------------------------

    def validate_offer(self, offer_id: str) -> Dict:
        """
        Validate a hotel offer — get latest price and availability.

        Args:
            offer_id: Offer ID from search results

        Returns:
            Dict with success, offer (updated pricing)
        """
        token = self._get_access_token()
        if not token:
            return {"success": False, "error": "Authentication failed"}

        try:
            response = requests.get(
                f"{self.BASE_URL}/v3/shopping/hotel-offers/{offer_id}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                },
                timeout=20,
            )

            if response.status_code == 200:
                data = response.json()
                offer_data = data.get("data", {})
                offers = offer_data.get("offers", [])
                if offers:
                    price = float(offers[0].get("price", {}).get("total", 0))
                    return {
                        "success": True,
                        "offer": offers[0],
                        "price": price,
                        "currency": offers[0].get("price", {}).get("currency", "USD"),
                        "available": True,
                    }
                return {"success": False, "error": "Offer no longer available", "available": False}

            else:
                error = self._parse_error(response)
                return {"success": False, "error": error}

        except Exception as e:
            return {"success": False, "error": str(e)}

    # -------------------------------------------------------------------------
    # Step 4: Book hotel
    # -------------------------------------------------------------------------

    def create_booking(self, offer_id: str, guest: Dict, payment: Dict) -> Dict:
        """
        Book a hotel room.

        Args:
            offer_id: Offer ID from search/validation
            guest: Dict with name, contact:
                - title (MR/MS/MRS)
                - first_name, last_name
                - email, phone
            payment: Dict with card info:
                - vendor_code (VI, MC, AX)
                - card_number
                - expiry_date (YYYY-MM)

        Returns:
            Dict with success, booking_id, provider_confirmation
        """
        token = self._get_access_token()
        if not token:
            return {"success": False, "error": "Authentication failed"}

        payload = {
            "data": {
                "type": "hotel-order",
                "roomAssociations": [
                    {
                        "offerId": offer_id,
                        "guestReferences": [
                            {"guestReference": "1"}
                        ],
                    }
                ],
                "guests": [
                    {
                        "tid": 1,
                        "name": {
                            "title": guest.get("title", "MR"),
                            "firstName": guest.get("first_name", "").upper(),
                            "lastName": guest.get("last_name", "").upper(),
                        },
                        "contact": {
                            "email": guest.get("email", ""),
                            "phone": guest.get("phone", ""),
                        },
                    }
                ],
                "payment": {
                    "method": "CREDIT_CARD",
                    "paymentCard": {
                        "vendorCode": payment.get("vendor_code", "VI"),
                        "cardNumber": payment.get("card_number", ""),
                        "expiryDate": payment.get("expiry_date", ""),
                    },
                },
            }
        }

        try:
            response = requests.post(
                f"{self.BASE_URL}/v2/booking/hotel-orders",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=30,
            )

            if response.status_code in (200, 201):
                data = response.json()
                order = data.get("data", [{}])
                if isinstance(order, list):
                    order = order[0] if order else {}

                booking_id = order.get("id")
                provider_ref = order.get("associatedRecords", [{}])[0].get("reference") if order.get("associatedRecords") else None

                print(f"[AMADEUS HOTEL] Booking created: {booking_id}, ref={provider_ref}")
                return {
                    "success": True,
                    "booking_id": booking_id,
                    "provider_confirmation": provider_ref,
                    "raw_order": order,
                }
            else:
                error = self._parse_error(response)
                print(f"[AMADEUS HOTEL] Booking failed: {error}")
                return {"success": False, "error": error}

        except Exception as e:
            print(f"[AMADEUS HOTEL] Booking error: {e}")
            return {"success": False, "error": str(e)}

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _parse_error(self, response) -> str:
        try:
            data = response.json()
            errors = data.get("errors", [])
            if errors:
                return errors[0].get("detail", f"HTTP {response.status_code}")
            return f"HTTP {response.status_code}"
        except Exception:
            return f"HTTP {response.status_code}"


# ---------------------------------------------------------------------------
# Module-level convenience
# ---------------------------------------------------------------------------

_hotel_client = None

def _get_client() -> AmadeusHotelClient:
    global _hotel_client
    if _hotel_client is None:
        _hotel_client = AmadeusHotelClient()
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
) -> Dict:
    """Convenience function for hotel search."""
    client = _get_client()
    return client.search_hotels(
        city_code=city_code,
        check_in=check_in,
        check_out=check_out,
        adults=adults,
        rooms=rooms,
        currency=currency,
        ratings=ratings,
        max_hotels=max_hotels,
    )
