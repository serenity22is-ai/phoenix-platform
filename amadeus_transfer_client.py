"""
Amadeus Transfer (Cars & Transfers) API Client for PHOENIX

Covers ground transportation: private transfers, taxis, shared shuttles,
airport express, limos, and car services.

Endpoints:
  1. Transfer Search: POST /v1/shopping/transfer-offers
  2. Transfer Booking: POST /v1/ordering/transfer-orders
  3. Transfer Cancel: POST /v1/ordering/transfer-orders/{orderId}/transfers/cancellation

Uses same credentials and environment as amadeus_client.py.

Usage:
    from amadeus_transfer_client import AmadeusTransferClient, search_transfers

    result = search_transfers(
        start_location="JFK",
        end_address="350 5th Ave, New York, NY 10118",
        start_datetime="2026-03-15T14:00:00",
        passengers=2,
    )
    if result["success"]:
        for offer in result["transfers"]:
            print(offer["vehicle_type"], offer["price"], offer["currency"])
"""

import os
import requests
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import json

from dotenv import load_dotenv
load_dotenv()


class AmadeusTransferClient:
    """
    Amadeus Transfer Search + Booking API client.

    Transfer Search: POST /v1/shopping/transfer-offers
    Transfer Booking: POST /v1/ordering/transfer-orders
    Transfer Cancel: POST /v1/ordering/transfer-orders/{id}/transfers/cancellation

    Covers: private transfers, taxis, shared shuttles, airport express,
    limos, hourly services, private jets, helicopters.

    Set AMADEUS_ENV=production in .env for real inventory.
    """

    ENVIRONMENTS = {
        "test": "https://test.api.amadeus.com",
        "production": "https://api.amadeus.com",
    }

    # Transfer types supported by the API
    TRANSFER_TYPES = [
        "PRIVATE",          # Private car/van
        "SHARED",           # Shared shuttle
        "TAXI",             # Taxi
        "HOURLY",           # Hourly car service
        "AIRPORT_EXPRESS",  # Airport express bus/train
        "AIRPORT_BUS",      # Airport bus
        "PRIVATE_JET",      # Private jet
        "HELICOPTER",       # Helicopter
    ]

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
            print(f"[AMADEUS TRANSFER] Auth error: {e}")
            return None

    def is_configured(self) -> bool:
        return bool(self.api_key and self.api_secret)

    # -------------------------------------------------------------------------
    # Transfer Search
    # -------------------------------------------------------------------------

    def search_transfers(
        self,
        start_location_code: Optional[str] = None,
        start_address: Optional[str] = None,
        start_city: Optional[str] = None,
        start_country: Optional[str] = None,
        start_lat: Optional[float] = None,
        start_lon: Optional[float] = None,
        end_location_code: Optional[str] = None,
        end_address: Optional[str] = None,
        end_city: Optional[str] = None,
        end_country: Optional[str] = None,
        end_lat: Optional[float] = None,
        end_lon: Optional[float] = None,
        start_datetime: Optional[str] = None,
        passengers: int = 1,
        transfer_type: str = "PRIVATE",
        currency: str = "USD",
    ) -> Dict:
        """
        Search for transfer offers.

        Location can be specified by IATA code OR address OR lat/lon.

        Args:
            start_location_code: IATA airport/city code (e.g., "JFK")
            start_address: Street address for pickup
            start_city, start_country: City/country for address
            start_lat, start_lon: GPS coordinates
            end_location_code: IATA code for destination
            end_address: Street address for dropoff
            end_city, end_country: City/country for address
            end_lat, end_lon: GPS coordinates
            start_datetime: ISO 8601 (e.g., "2026-03-15T14:00:00")
            passengers: Number of passengers
            transfer_type: PRIVATE, SHARED, TAXI, HOURLY, etc.
            currency: Price currency

        Returns:
            Dict with success, transfers list
        """
        if not self.is_configured():
            return {"success": False, "transfers": [], "error": "Amadeus not configured"}

        token = self._get_access_token()
        if not token:
            return {"success": False, "transfers": [], "error": "Authentication failed"}

        if not start_datetime:
            start_datetime = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%dT14:00:00")

        # Build start location
        start_location = {}
        if start_location_code:
            start_location["locationCode"] = start_location_code.upper()
        elif start_lat and start_lon:
            start_location["geoCode"] = str(start_lat) + "," + str(start_lon)
        if start_address:
            start_location["address"] = {"line": start_address}
            if start_city:
                start_location["address"]["cityName"] = start_city
            if start_country:
                start_location["address"]["countryCode"] = start_country

        # Build end location
        end_location = {}
        if end_location_code:
            end_location["locationCode"] = end_location_code.upper()
        elif end_lat and end_lon:
            end_location["geoCode"] = str(end_lat) + "," + str(end_lon)
        if end_address:
            end_location["address"] = {"line": end_address}
            if end_city:
                end_location["address"]["cityName"] = end_city
            if end_country:
                end_location["address"]["countryCode"] = end_country

        payload = {
            "startLocationCode": start_location.get("locationCode", ""),
            "startDateTime": start_datetime,
            "passengers": passengers,
            "transferType": transfer_type,
        }

        # Add end location (either code or address)
        if end_location.get("locationCode"):
            payload["endLocationCode"] = end_location["locationCode"]
        if end_address:
            payload["endAddressLine"] = end_address
        if end_city:
            payload["endCityName"] = end_city
        if end_country:
            payload["endCountryCode"] = end_country
        if start_address:
            payload["startAddressLine"] = start_address
        if start_city:
            payload["startCityName"] = start_city
        if start_country:
            payload["startCountryCode"] = start_country

        # Clean empty strings
        payload = {k: v for k, v in payload.items() if v}

        start_desc = start_location_code or start_address or f"{start_lat},{start_lon}"
        end_desc = end_location_code or end_address or f"{end_lat},{end_lon}"
        print(f"[AMADEUS TRANSFER] Searching {transfer_type} transfers: {start_desc} → {end_desc}")

        try:
            response = requests.post(
                f"{self.BASE_URL}/v1/shopping/transfer-offers",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=30,
            )

            if response.status_code == 200:
                data = response.json()
                raw_offers = data.get("data", [])
                print(f"[AMADEUS TRANSFER] Found {len(raw_offers)} transfer offers")

                transfers = []
                for offer in raw_offers:
                    # Vehicle info
                    vehicle = offer.get("vehicle", {})
                    vehicle_code = vehicle.get("code", "")
                    vehicle_category = vehicle.get("category", "")
                    vehicle_desc = vehicle.get("description", "")
                    max_passengers = vehicle.get("seats", [{}])[0].get("count") if vehicle.get("seats") else None
                    max_bags = vehicle.get("baggages", [{}])[0].get("count") if vehicle.get("baggages") else None

                    # Price
                    quotation = offer.get("quotation", {})
                    price_total = float(quotation.get("totalPrice", {}).get("value", 0))
                    price_currency = quotation.get("totalPrice", {}).get("currencyCode", currency)
                    base_price = float(quotation.get("base", {}).get("monetaryAmount", 0)) if quotation.get("base") else price_total

                    # Service provider
                    service_provider = offer.get("serviceProvider", {})
                    provider_name = service_provider.get("name", "Unknown Provider")
                    provider_code = service_provider.get("code", "")

                    # Cancellation
                    cancellation = offer.get("cancellationRules", [])
                    cancellation_policy = cancellation[0].get("freeText") if cancellation else None

                    # Start/end details
                    start_info = offer.get("start", {})
                    end_info = offer.get("end", {})

                    parsed = {
                        "offer_id": offer.get("id"),
                        "transfer_type": offer.get("transferType", transfer_type),

                        "vehicle_code": vehicle_code,
                        "vehicle_category": vehicle_category,
                        "vehicle_description": vehicle_desc,
                        "max_passengers": max_passengers,
                        "max_bags": max_bags,

                        "price": price_total,
                        "price_base": base_price,
                        "currency": price_currency,

                        "provider_name": provider_name,
                        "provider_code": provider_code,

                        "start_location": start_info.get("locationCode"),
                        "start_datetime": start_info.get("dateTime", start_datetime),
                        "end_location": end_info.get("locationCode"),

                        "duration_minutes": offer.get("duration", {}).get("value"),
                        "distance_km": offer.get("distance", {}).get("value"),
                        "distance_unit": offer.get("distance", {}).get("unit", "KM"),

                        "cancellation_policy": cancellation_policy,
                        "passengers": passengers,
                        "source": "amadeus",

                        # Raw offer for booking
                        "raw_offer": offer,
                    }
                    transfers.append(parsed)

                # Sort by price
                transfers.sort(key=lambda t: t["price"])

                return {
                    "success": len(transfers) > 0,
                    "transfers": transfers,
                    "source": "amadeus",
                    "transfer_type": transfer_type,
                }

            else:
                error = self._parse_error(response)
                print(f"[AMADEUS TRANSFER] Error: {error}")
                return {"success": False, "transfers": [], "error": error}

        except Exception as e:
            print(f"[AMADEUS TRANSFER] Error: {e}")
            return {"success": False, "transfers": [], "error": str(e)}

    # -------------------------------------------------------------------------
    # Transfer Booking
    # -------------------------------------------------------------------------

    def create_booking(self, offer_id: str, passenger: Dict, payment: Optional[Dict] = None) -> Dict:
        """
        Book a transfer.

        Args:
            offer_id: Transfer offer ID from search
            passenger: Dict with:
                - first_name, last_name
                - email, phone
                - country_code (2-letter)
            payment: Optional payment info (some transfers are pay-on-arrival)

        Returns:
            Dict with success, order_id, confirmation
        """
        token = self._get_access_token()
        if not token:
            return {"success": False, "error": "Authentication failed"}

        passengers_list = [{
            "firstName": passenger.get("first_name", "").upper(),
            "lastName": passenger.get("last_name", "").upper(),
            "contacts": {
                "email": passenger.get("email", ""),
                "phoneNumber": passenger.get("phone", ""),
            },
        }]

        payload = {
            "data": {
                "type": "transfer-order",
                "passengers": passengers_list,
                "note": "Booked via Phoenix",
            }
        }

        try:
            response = requests.post(
                f"{self.BASE_URL}/v1/ordering/transfer-orders?offerId={offer_id}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=30,
            )

            if response.status_code in (200, 201):
                data = response.json()
                order = data.get("data", {})
                order_id = order.get("id")
                transfers = order.get("transfers", [])
                confirmation = transfers[0].get("confirmationNumber") if transfers else None

                print(f"[AMADEUS TRANSFER] Booking created: {order_id}, conf={confirmation}")
                return {
                    "success": True,
                    "order_id": order_id,
                    "confirmation": confirmation,
                    "raw_order": order,
                }
            else:
                error = self._parse_error(response)
                print(f"[AMADEUS TRANSFER] Booking failed: {error}")
                return {"success": False, "error": error}

        except Exception as e:
            print(f"[AMADEUS TRANSFER] Booking error: {e}")
            return {"success": False, "error": str(e)}

    # -------------------------------------------------------------------------
    # Transfer Cancellation
    # -------------------------------------------------------------------------

    def cancel_booking(self, order_id: str, confirmation_number: str) -> Dict:
        """
        Cancel a transfer booking.

        Args:
            order_id: Transfer order ID
            confirmation_number: Provider confirmation number

        Returns:
            Dict with success, status
        """
        token = self._get_access_token()
        if not token:
            return {"success": False, "error": "Authentication failed"}

        try:
            response = requests.post(
                f"{self.BASE_URL}/v1/ordering/transfer-orders/{order_id}/transfers/cancellation",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json={
                    "data": {
                        "confirmationNbr": confirmation_number,
                    }
                },
                timeout=20,
            )

            if response.status_code in (200, 204):
                print(f"[AMADEUS TRANSFER] Cancellation confirmed: {order_id}")
                return {"success": True, "order_id": order_id, "status": "cancelled"}
            else:
                error = self._parse_error(response)
                return {"success": False, "error": error}

        except Exception as e:
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

_transfer_client = None

def _get_client() -> AmadeusTransferClient:
    global _transfer_client
    if _transfer_client is None:
        _transfer_client = AmadeusTransferClient()
    return _transfer_client

def search_transfers(
    start_location_code: Optional[str] = None,
    end_location_code: Optional[str] = None,
    end_address: Optional[str] = None,
    end_city: Optional[str] = None,
    end_country: Optional[str] = None,
    start_datetime: Optional[str] = None,
    passengers: int = 1,
    transfer_type: str = "PRIVATE",
    currency: str = "USD",
) -> Dict:
    """Convenience function for transfer search."""
    client = _get_client()
    return client.search_transfers(
        start_location_code=start_location_code,
        end_location_code=end_location_code,
        end_address=end_address,
        end_city=end_city,
        end_country=end_country,
        start_datetime=start_datetime,
        passengers=passengers,
        transfer_type=transfer_type,
        currency=currency,
    )
