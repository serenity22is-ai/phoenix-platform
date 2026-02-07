"""
Amadeus API Client for PHOENIX

Provides rich flight data (flight numbers, layovers, aircraft types) to complement
proxy-based price scraping. Amadeus free tier: 2,000 requests/month.

Usage:
    from amadeus_client import AmadeusClient, search_with_amadeus

    result = search_with_amadeus("TYS", "PHX", "2026-02-15")
    if result["success"]:
        for flight in result["flights"]:
            print(flight["airline_name"], flight["flight_number"], flight["price"])
"""

import os
import requests
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import json

from dotenv import load_dotenv
load_dotenv()


class AmadeusClient:
    """
    Amadeus Flight Offers Search API client.

    Free tier: 2,000 requests/month
    Docs: https://developers.amadeus.com/self-service/category/flights/api-doc/flight-offers-search

    Set AMADEUS_ENV=production in .env to use real inventory and pricing.
    Default: test (synthetic data, no real bookings).
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
        if env == "production":
            print(f"[AMADEUS] *** PRODUCTION MODE — real inventory, real bookings ***")
        else:
            print(f"[AMADEUS] Test mode — synthetic data, simulated bookings")

        if not self.api_key or not self.api_secret:
            print("[AMADEUS] Warning: API credentials not configured")
            print("[AMADEUS] Get free API key at: https://developers.amadeus.com/register")

    def _get_access_token(self) -> Optional[str]:
        """Get OAuth2 access token from Amadeus."""
        # Return cached token if still valid
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
        except requests.exceptions.RequestException as e:
            print(f"[AMADEUS] Auth failed: {e}")
            return None
        except Exception as e:
            print(f"[AMADEUS] Auth error: {e}")
            return None

    def is_configured(self) -> bool:
        """Check if Amadeus API is properly configured."""
        return bool(self.api_key and self.api_secret)

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
    ) -> Dict:
        """
        Search for flight offers using Amadeus API.

        Args:
            origin: Origin airport code (e.g., "JFK")
            destination: Destination airport code (e.g., "BCN")
            departure_date: Outbound date (YYYY-MM-DD)
            return_date: Return date for round-trips (optional)
            adults: Number of adult travelers
            cabin_class: ECONOMY, PREMIUM_ECONOMY, BUSINESS, FIRST
            max_results: Max number of results
            nonstop_only: Only return non-stop flights

        Returns:
            Dict with success, flights list, source
        """
        if not self.is_configured():
            return {
                "success": False,
                "flights": [],
                "source": "amadeus",
                "error": "Authentication failed - check AMADEUS_API_KEY and AMADEUS_API_SECRET",
            }

        token = self._get_access_token()
        if not token:
            return {
                "success": False,
                "flights": [],
                "source": "amadeus",
                "error": "Authentication failed - check AMADEUS_API_KEY and AMADEUS_API_SECRET",
            }

        params = {
            "originLocationCode": origin.upper(),
            "destinationLocationCode": destination.upper(),
            "departureDate": departure_date,
            "adults": adults,
            "travelClass": cabin_class,
            "currencyCode": "USD",
            "max": max_results,
        }
        if return_date:
            params["returnDate"] = return_date
        if nonstop_only:
            params["nonStop"] = "true"

        trip_desc = f"{origin}→{destination} on {departure_date}"
        if return_date:
            trip_desc += f" returning {return_date}"
        print(f"[AMADEUS] Searching {trip_desc}")

        try:
            response = requests.get(
                f"{self.BASE_URL}/v2/shopping/flight-offers",
                params=params,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                },
                timeout=30,
            )

            if response.status_code == 200:
                data = response.json()
                dictionaries = data.get("dictionaries", {})
                offers = data.get("data", [])
                print(f"[AMADEUS] Found {len(offers)} flight offers")

                flights = []
                for offer in offers:
                    try:
                        parsed = self._parse_flight_offer(offer, dictionaries)
                        if parsed:
                            flights.append(parsed)
                    except Exception as e:
                        print(f"[AMADEUS] Error parsing offer: {e}")

                return {"success": True, "flights": flights, "source": "amadeus"}

            elif response.status_code == 400:
                error_data = response.json()
                errors = error_data.get("errors", [])
                detail = errors[0].get("detail", "Bad request") if errors else "Invalid search parameters"
                print(f"[AMADEUS] Error: {detail}")
                return {"success": False, "flights": [], "source": "amadeus", "error": f"API error: {detail}"}
            else:
                print(f"[AMADEUS] Error: HTTP {response.status_code}")
                return {"success": False, "flights": [], "source": "amadeus", "error": f"API error: HTTP {response.status_code}"}

        except requests.exceptions.Timeout:
            print("[AMADEUS] Request timed out")
            return {"success": False, "flights": [], "source": "amadeus", "error": "Request timeout"}
        except Exception as e:
            print(f"[AMADEUS] Error: {e}")
            return {"success": False, "flights": [], "source": "amadeus", "error": str(e)}

    def _parse_flight_offer(self, offer: Dict, dictionaries: Dict) -> Optional[Dict]:
        """
        Parse an Amadeus flight offer into our normalized format.

        Args:
            offer: Raw flight offer from Amadeus API
            dictionaries: Lookup dictionaries for carriers, aircraft, etc.

        Returns:
            Normalized flight dict or None
        """
        try:
            price = float(offer.get("price", {}).get("total", 0))
            currency = offer.get("price", {}).get("currency", "USD")
            itineraries = offer.get("itineraries", [])

            if not itineraries:
                return None

            # Parse baggage info from travelerPricings
            baggage_info = None
            traveler_pricings = offer.get("travelerPricings", [])
            if traveler_pricings:
                fare_details = traveler_pricings[0].get("fareDetailsBySegment", [])
                if fare_details:
                    cabin = fare_details[0].get("cabin", "ECONOMY")
                    bags = fare_details[0].get("includedCheckedBags", {})
                    bag_qty = bags.get("quantity", 0)
                    bag_weight = bags.get("weight")
                    if bag_qty:
                        baggage_info = f"{bag_qty} checked bag(s) included"
                        if bag_weight:
                            baggage_info = f"{bag_qty} bag(s), {bag_weight}kg each"
                    booking_class = fare_details[0].get("class", "")
                else:
                    cabin = "ECONOMY"
                    booking_class = ""
            else:
                cabin = "ECONOMY"
                booking_class = ""

            # Parse outbound itinerary
            outbound = self._parse_itinerary(itineraries[0], dictionaries)

            # Parse return itinerary if present
            return_flight = None
            is_round_trip = len(itineraries) > 1
            if is_round_trip:
                return_flight = self._parse_itinerary(itineraries[1], dictionaries)

            # Build match key for correlating with proxy prices
            match_key = f"{outbound['segments'][0]['carrier']}_{outbound['segments'][0]['flight_number']}_{outbound['segments'][0]['departure_time'][:16]}" if outbound["segments"] else None

            result = {
                "offer_id": offer.get("id"),
                "source": "amadeus",
                "price": price,
                "price_per_adult": price,
                "currency": currency,

                # Primary carrier info
                "airline": outbound["segments"][0]["marketing_carrier"] if outbound["segments"] else None,
                "marketing_carrier": outbound["segments"][0]["marketing_carrier"] if outbound["segments"] else None,
                "airline_name": outbound["segments"][0]["marketing_carrier_name"] if outbound["segments"] else None,
                "marketing_carrier_name": outbound["segments"][0]["marketing_carrier_name"] if outbound["segments"] else None,
                "flight_number": outbound["segments"][0]["flight_number"] if outbound["segments"] else None,

                # Route and times
                "departure_airport": outbound["segments"][0]["departure_airport"] if outbound["segments"] else None,
                "arrival_airport": outbound["segments"][-1]["arrival_airport"] if outbound["segments"] else None,
                "departure_time": outbound["segments"][0]["departure_time"] if outbound["segments"] else None,
                "arrival_time": outbound["segments"][-1]["arrival_time"] if outbound["segments"] else None,
                "duration_minutes": outbound["duration_minutes"],
                "duration_formatted": outbound["duration_formatted"],

                # Stops and layovers
                "stops": outbound["stops"],
                "layovers": outbound["layovers"],

                # Aircraft
                "aircraft": outbound["segments"][0].get("aircraft_name") or outbound["segments"][0].get("aircraft_code") if outbound["segments"] else None,

                # Segments
                "segments": outbound["segments"],

                # Return
                "return_flight": return_flight,
                "is_round_trip": is_round_trip,

                # Cabin and baggage
                "cabin_class": cabin,
                "baggage_info": baggage_info,
                "booking_class": booking_class,

                # Match key
                "match_key": match_key,

                # Codeshare
                "is_codeshare": outbound["segments"][0].get("is_codeshare", False) if outbound["segments"] else False,
                "operating_carrier": outbound["segments"][0].get("operating_carrier") if outbound["segments"] else None,

                # Raw offer for booking (needed for price_confirm + create_booking)
                "raw_offer": offer,
            }
            return result

        except Exception as e:
            print(f"[AMADEUS] Error parsing offer: {e}")
            return None

    def _parse_itinerary(self, itinerary: Dict, dictionaries: Dict) -> Dict:
        """Parse a single itinerary (outbound or return)."""
        raw_segments = itinerary.get("segments", [])
        carriers_dict = dictionaries.get("carriers", {})
        aircraft_dict = dictionaries.get("aircraft", {})

        segments = []
        total_duration = itinerary.get("duration", "PT0H0M")
        layovers = []

        for idx, seg in enumerate(raw_segments):
            carrier_code = seg.get("carrierCode", "")
            operating = seg.get("operating", {})
            operating_code = operating.get("carrierCode", "")
            seg_duration = seg.get("duration", "PT0H0M")

            dep = seg.get("departure", {})
            arr = seg.get("arrival", {})

            segment = {
                "code": carrier_code,
                "carrier": carrier_code,
                "carrier_name": carriers_dict.get(carrier_code, carrier_code),
                "flight_number": f"{carrier_code}{seg.get('number', '')}",
                "departure_airport": dep.get("iataCode", ""),
                "departure_terminal": dep.get("terminal", ""),
                "departure_time": dep.get("at", "").replace("+00:00", ""),
                "arrival_airport": arr.get("iataCode", ""),
                "arrival_terminal": arr.get("terminal", ""),
                "arrival_time": arr.get("at", "").replace("+00:00", ""),
                "duration_minutes": self._parse_duration(seg_duration),
                "duration_formatted": self._format_duration(seg_duration),
                "aircraft_code": seg.get("aircraft", {}).get("code", ""),
                "aircraft_name": aircraft_dict.get(seg.get("aircraft", {}).get("code", ""), ""),
                "operating_carrier": operating_code or carrier_code,
                "marketing_carrier": carrier_code,
                "marketing_carrier_name": carriers_dict.get(carrier_code, carrier_code),
                "operating_carrier_name": carriers_dict.get(operating_code, operating_code) if operating_code else carriers_dict.get(carrier_code, carrier_code),
                "is_codeshare": bool(operating_code and operating_code != carrier_code),
            }
            segments.append(segment)

            # Calculate layover between this segment and next
            if idx < len(raw_segments) - 1:
                next_seg = raw_segments[idx + 1]
                next_dep = next_seg.get("departure", {})
                try:
                    arr_time = datetime.fromisoformat(arr.get("at", "").replace("Z", "+00:00"))
                    next_dep_time = datetime.fromisoformat(next_dep.get("at", "").replace("Z", "+00:00"))
                    layover_mins = int((next_dep_time - arr_time).total_seconds() / 60)
                    layover_hours = layover_mins // 60
                    layover_remainder = layover_mins % 60
                    layovers.append({
                        "airport": arr.get("iataCode", ""),
                        "duration_minutes": layover_mins,
                        "duration_formatted": f"{layover_hours}h {layover_remainder}m",
                    })
                except (ValueError, TypeError):
                    layovers.append({
                        "airport": arr.get("iataCode", ""),
                        "duration_minutes": 0,
                        "duration_formatted": "?",
                    })

        return {
            "segments": segments,
            "stops": len(raw_segments) - 1,
            "layovers": layovers,
            "duration_minutes": self._parse_duration(total_duration),
            "duration_formatted": self._format_duration(total_duration),
        }

    def _parse_duration(self, duration_str: str) -> int:
        """Parse ISO 8601 duration (PT14H30M) to minutes."""
        if not duration_str:
            return 0
        try:
            duration_str = duration_str.replace("PT", "")
            hours = 0
            minutes = 0
            if "H" in duration_str:
                parts = duration_str.split("H")
                hours = int(parts[0])
                duration_str = parts[1] if len(parts) > 1 else ""
            if "M" in duration_str:
                minutes = int(duration_str.replace("M", ""))
            return hours * 60 + minutes
        except (ValueError, IndexError):
            return 0

    def _format_duration(self, duration_str: str) -> str:
        """Format ISO 8601 duration to human readable."""
        mins = self._parse_duration(duration_str)
        if mins == 0:
            return "?"
        hours = mins // 60
        remainder = mins % 60
        if hours and remainder:
            return f"{hours}h {remainder}m"
        elif hours:
            return f"{hours}h"
        else:
            return f"{remainder}m"


    def price_confirm(self, offer: Dict) -> Dict:
        """
        Confirm pricing for a specific flight offer before booking.

        Args:
            offer: Raw Amadeus flight offer object (from search response)

        Returns:
            Dict with success, confirmed_offer (updated pricing), original_price, confirmed_price
        """
        token = self._get_access_token()
        if not token:
            return {"success": False, "error": "Authentication failed"}

        try:
            response = requests.post(
                f"{self.BASE_URL}/v1/shopping/flight-offers/pricing",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json={
                    "data": {
                        "type": "flight-offers-pricing",
                        "flightOffers": [offer],
                    }
                },
                timeout=30,
            )

            if response.status_code == 200:
                data = response.json()
                confirmed_offers = data.get("data", {}).get("flightOffers", [])
                if confirmed_offers:
                    confirmed = confirmed_offers[0]
                    return {
                        "success": True,
                        "confirmed_offer": confirmed,
                        "original_price": float(offer.get("price", {}).get("total", 0)),
                        "confirmed_price": float(confirmed.get("price", {}).get("total", 0)),
                        "currency": confirmed.get("price", {}).get("currency", "USD"),
                    }
                return {"success": False, "error": "No confirmed offers returned"}
            else:
                error_data = response.json()
                errors = error_data.get("errors", [])
                detail = errors[0].get("detail", "Price confirmation failed") if errors else "Unknown error"
                return {"success": False, "error": detail}

        except Exception as e:
            return {"success": False, "error": str(e)}

    def _build_traveler_object(self, traveler: Dict, traveler_id: str = "1") -> Dict:
        """Build Amadeus traveler object from dict or TravelerProfile. (Build #98)"""
        # If it's already in Amadeus format (has 'id' key), return as-is
        if "id" in traveler and "name" in traveler:
            return traveler

        traveler_obj = {
            "id": traveler_id,
            "dateOfBirth": traveler.get("date_of_birth", "1990-01-01"),
            "name": {
                "firstName": traveler.get("first_name", "").upper(),
                "lastName": traveler.get("last_name", "").upper(),
            },
            "gender": traveler.get("gender", "MALE").upper(),
            "contact": {
                "emailAddress": traveler.get("email", ""),
                "phones": [{
                    "deviceType": "MOBILE",
                    "countryCallingCode": traveler.get("phone_country_code", "1"),
                    "number": traveler.get("phone", "").replace("+", "").replace("-", "").replace(" ", ""),
                }],
            },
        }

        # Add middle name if present
        if traveler.get("middle_name"):
            traveler_obj["name"]["secondLastName"] = traveler["middle_name"].upper()

        # Add passport/document if provided (required for international)
        if traveler.get("passport_number"):
            traveler_obj["documents"] = [{
                "documentType": "PASSPORT",
                "number": traveler["passport_number"],
                "expiryDate": traveler.get("passport_expiry", "2030-01-01"),
                "issuanceCountry": traveler.get("passport_country", "US"),
                "nationality": traveler.get("nationality", "US"),
                "holder": True,
            }]

        return traveler_obj

    def create_booking(self, offer: Dict, traveler: Dict) -> Dict:
        """
        Create a flight booking for a single traveler (Flight Orders API).

        For multi-passenger bookings, use create_booking_multi() instead.

        Args:
            offer: Confirmed flight offer (from price_confirm, or raw search offer)
            traveler: Dict with passenger details:
                - first_name, last_name (required)
                - date_of_birth (YYYY-MM-DD)
                - gender (MALE/FEMALE)
                - email, phone (required)
                - passport_number, passport_expiry, passport_country, nationality (optional)

        Returns:
            Dict with success, order_id, pnr, segments, price, raw_order
        """
        return self.create_booking_multi(offer, [traveler])

    def create_booking_multi(self, offer: Dict, travelers: List[Dict], contact_email: str = None) -> Dict:
        """
        Create a flight booking for multiple travelers (Flight Orders API). (Build #98)

        Supports up to 9 passengers per PNR (Amadeus limit).

        Args:
            offer: Confirmed flight offer (from price_confirm, or raw search offer)
            travelers: List of dicts, each with passenger details:
                - first_name, last_name (required)
                - date_of_birth (YYYY-MM-DD)
                - gender (MALE/FEMALE)
                - email, phone (at least one traveler must have contact info)
                - passport_number, passport_expiry, passport_country, nationality (for international)
            contact_email: Optional primary contact email for the booking

        Returns:
            Dict with success, order_id, pnr, segments, price, travelers_booked, raw_order
        """
        if not travelers:
            return {"success": False, "error": "At least one traveler is required"}

        if len(travelers) > 9:
            return {"success": False, "error": "Maximum 9 passengers per booking (Amadeus limit)"}

        token = self._get_access_token()
        if not token:
            return {"success": False, "error": "Authentication failed"}

        # Build traveler objects with sequential IDs
        traveler_objects = []
        for idx, traveler in enumerate(travelers, start=1):
            traveler_obj = self._build_traveler_object(traveler, str(idx))
            traveler_objects.append(traveler_obj)

        # Ensure at least one traveler has contact info
        has_contact = any(
            t.get("contact", {}).get("emailAddress") or
            t.get("contact", {}).get("phones", [{}])[0].get("number")
            for t in traveler_objects
        )
        if not has_contact and contact_email:
            # Add contact to first traveler
            traveler_objects[0]["contact"] = {
                "emailAddress": contact_email,
                "phones": [{"deviceType": "MOBILE", "countryCallingCode": "1", "number": "0000000000"}],
            }

        payload = {
            "data": {
                "type": "flight-order",
                "flightOffers": [offer],
                "travelers": traveler_objects,
                "remarks": {
                    "general": [{
                        "subType": "GENERAL_MISCELLANEOUS",
                        "text": f"PHOENIX BOOKING - {len(travelers)} PAX",
                    }]
                },
                "ticketingAgreement": {
                    "option": "DELAY_TO_QUEUE",
                    "delay": "6D",
                },
            }
        }

        try:
            response = requests.post(
                f"{self.BASE_URL}/v1/booking/flight-orders",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=60,
            )

            if response.status_code in (200, 201):
                data = response.json()
                order = data.get("data", {})
                records = order.get("associatedRecords", [])
                pnr = records[0].get("reference") if records else None
                provider = records[0].get("originSystemCode") if records else None

                # Extract segment details for confirmation display
                segments = []
                flight_offers = order.get("flightOffers", [])
                if flight_offers:
                    for itin in flight_offers[0].get("itineraries", []):
                        for seg in itin.get("segments", []):
                            segments.append({
                                "origin": seg["departure"]["iataCode"],
                                "destination": seg["arrival"]["iataCode"],
                                "departure": seg["departure"].get("at", ""),
                                "arrival": seg["arrival"].get("at", ""),
                                "terminal_dep": seg["departure"].get("terminal"),
                                "terminal_arr": seg["arrival"].get("terminal"),
                                "carrier": seg.get("carrierCode", ""),
                                "flight_number": seg.get("number", ""),
                                "aircraft": seg.get("aircraft", {}).get("code", ""),
                                "duration": seg.get("duration", ""),
                            })

                price = float(flight_offers[0]["price"]["total"]) if flight_offers else 0
                currency = flight_offers[0]["price"].get("currency", "USD") if flight_offers else "USD"

                # Extract booked travelers
                booked_travelers = order.get("travelers", [])
                travelers_count = len(booked_travelers)

                print(f"[AMADEUS] Booking created: PNR={pnr}, {travelers_count} pax, price=${price}")
                return {
                    "success": True,
                    "order_id": order.get("id"),
                    "pnr": pnr,
                    "provider": provider,
                    "segments": segments,
                    "price": price,
                    "currency": currency,
                    "travelers_booked": travelers_count,
                    "raw_order": order,
                }

            else:
                error_data = response.json()
                errors = error_data.get("errors", [])
                detail = errors[0].get("detail", "Booking failed") if errors else "Unknown error"
                code = errors[0].get("code", "") if errors else ""
                print(f"[AMADEUS] Booking failed: {code} - {detail}")
                return {
                    "success": False,
                    "error": detail,
                    "error_code": code,
                }

        except Exception as e:
            print(f"[AMADEUS] Booking error: {e}")
            return {"success": False, "error": str(e)}


def search_with_amadeus(
    origin: str,
    destination: str,
    departure_date: str,
    return_date: Optional[str] = None,
    adults: int = 1,
    cabin_class: str = "economy",
) -> Dict:
    """
    Convenience function to search flights with Amadeus.

    Returns flight details suitable for merging with proxy price data.
    """
    client = AmadeusClient()
    if not client.is_configured():
        return {
            "success": False,
            "flights": [],
            "error": "Amadeus API not configured. Set AMADEUS_API_KEY and AMADEUS_API_SECRET in .env",
        }

    # Map cabin class names
    cabin_map = {
        "economy": "ECONOMY",
        "premium_economy": "PREMIUM_ECONOMY",
        "business": "BUSINESS",
        "first": "FIRST",
    }
    mapped_cabin = cabin_map.get(cabin_class.lower(), "ECONOMY")

    result = client.search_flights(
        origin=origin,
        destination=destination,
        departure_date=departure_date,
        return_date=return_date,
        adults=adults,
        cabin_class=mapped_cabin,
    )
    return result


if __name__ == "__main__":
    print("=" * 60)
    print("AMADEUS API TEST")
    print("=" * 60)

    client = AmadeusClient()
    if not client.is_configured():
        print("\nAmadeus API not configured!")
        print("To enable rich flight data:")
        print("1. Sign up at https://developers.amadeus.com/register")
        print("2. Create an app to get API key and secret")
        print("3. Add to .env:")
        print("   AMADEUS_API_KEY=your_api_key")
        print("   AMADEUS_API_SECRET=your_api_secret")
    else:
        result = client.search_flights("TYS", "PHX", "2026-02-15")
        if result["success"]:
            print(f"\nFound {len(result['flights'])} flights:\n")
            for i, flight in enumerate(result["flights"]):
                print(f"{i+1}. {flight['airline_name']} {flight['flight_number']}")
                print(f"   {flight['departure_airport']} {flight['departure_time']} → {flight['arrival_airport']} {flight['arrival_time']}")
                print(f"   Duration: {flight['duration_formatted']} | Stops: {flight['stops']} | Aircraft: {flight['aircraft']}")
                if flight.get("layovers"):
                    layover_info = ", ".join(f"{l['airport']} ({l['duration_formatted']})" for l in flight["layovers"])
                    print(f"   Layovers: {layover_info}")
                print(f"   Price: ${flight['price']} {flight['currency']}")
                if flight.get("baggage_info"):
                    print(f"   Baggage: {flight['baggage_info']}")
                print()
        else:
            print(f"\nSearch failed: {result.get('error')}")
    print("=" * 60)
