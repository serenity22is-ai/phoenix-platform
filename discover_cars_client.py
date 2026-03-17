"""
Discover Cars Rental API Client for MYSTES

Car rental aggregator: 500+ suppliers, 10,000+ locations, 145+ countries.
Aggregates Hertz, Alamo, Enterprise, Sixt, Europcar, and more.

Discover Cars B4B API:
    Base URL: https://api-partner.discovercars.com
    Auth: username + password + token (request from partner support)
    Docs: https://api-partner.discovercars.com/help
    B4B signup: https://pages.discovercars.com/b4b
    Affiliate: https://www.discovercars.com/affiliate

Revenue: 70% commission share from offers, ~$20 per booking.

Usage:
    from discover_cars_client import DiscoverCarsClient, search_car_rentals

    result = search_car_rentals(
        pickup_location="CDG",
        pickup_date="2026-04-15",
        dropoff_date="2026-04-22",
    )
    if result["success"]:
        for car in result["cars"]:
            print(car["vehicle_name"], car["price_total"], car["currency"])
"""

import os
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional

from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger(__name__)

DISCOVER_CARS_BASE_URL = "https://api-partner.discovercars.com"


class DiscoverCarsClient:
    """
    Discover Cars B4B API client.

    Auth: username + password + token triple (all sent as headers/params).
    Get credentials from partner support after B4B signup.

    Booking flow:
        1. Search locations (get location IDs)
        2. Search cars (by location + dates)
        3. Get car details / terms
        4. Create booking
        5. Cancel booking

    Set DISCOVER_CARS_USERNAME, DISCOVER_CARS_PASSWORD, DISCOVER_CARS_TOKEN in .env.
    """

    def __init__(self):
        import requests
        self._username = os.environ.get("DISCOVER_CARS_USERNAME", "")
        self._password = os.environ.get("DISCOVER_CARS_PASSWORD", "")
        self._token = os.environ.get("DISCOVER_CARS_TOKEN", "")
        self._session = requests.Session()
        self._session.headers.update({
            "Accept": "application/json",
            "Content-Type": "application/json",
        })

    def is_configured(self) -> bool:
        return bool(self._username and self._password and self._token)

    def _url(self, path: str) -> str:
        return f"{DISCOVER_CARS_BASE_URL}{path}"

    def _auth_params(self) -> dict:
        """Return auth params to include in every request."""
        return {
            "username": self._username,
            "password": self._password,
            "token": self._token,
        }

    def _request(self, method: str, path: str, json_data: dict = None,
                 params: dict = None, timeout: int = 30) -> dict:
        """Make an authenticated request to Discover Cars API."""
        merged_params = self._auth_params()
        if params:
            merged_params.update(params)

        try:
            resp = self._session.request(
                method,
                self._url(path),
                json=json_data,
                params=merged_params,
                timeout=timeout,
            )
            if resp.status_code >= 400:
                error_body = resp.json() if resp.text else {}
                error_msg = error_body.get("message", error_body.get("error", resp.text))
                logger.error("DiscoverCars API error %d: %s", resp.status_code, error_msg)
                return {"success": False, "error": error_msg, "status": resp.status_code}
            data = resp.json()
            return {"success": True, "data": data}
        except Exception as e:
            logger.error("DiscoverCars request failed: %s", str(e))
            return {"success": False, "error": str(e)}

    # =========================================================================
    # LOCATIONS
    # =========================================================================

    def search_locations(self, query: str, language: str = "en") -> dict:
        """
        Search for pickup/dropoff locations.

        Args:
            query: Location search term (e.g., "Paris CDG", "LAX")
            language: Language code

        Returns:
            dict with locations list (id, name, type, coordinates)
        """
        result = self._request(
            "GET",
            "/api/locations",
            params={"query": query, "language": language},
        )
        if not result["success"]:
            return result

        data = result["data"]
        raw_locations = data if isinstance(data, list) else data.get("locations", data.get("data", []))

        locations = []
        for loc in raw_locations:
            locations.append({
                "location_id": loc.get("id", loc.get("locationId", "")),
                "name": loc.get("name", ""),
                "type": loc.get("type", loc.get("locationType", "")),
                "city": loc.get("city", loc.get("cityName", "")),
                "country": loc.get("country", loc.get("countryName", "")),
                "country_code": loc.get("countryCode", ""),
                "iata_code": loc.get("iataCode", loc.get("airportCode", "")),
                "latitude": loc.get("latitude", loc.get("lat", 0)),
                "longitude": loc.get("longitude", loc.get("lng", 0)),
            })

        return {"success": True, "locations": locations}

    def get_locations(self, language: str = "en") -> dict:
        """Get all active locations available for search."""
        return self._request("GET", "/api/locations/active", params={"language": language})

    # =========================================================================
    # CAR SEARCH
    # =========================================================================

    def search_cars(
        self,
        pickup_location_id: str,
        pickup_date: str,
        pickup_time: str = "10:00",
        dropoff_date: str = None,
        dropoff_time: str = "10:00",
        dropoff_location_id: Optional[str] = None,
        currency: str = "USD",
        language: str = "en",
        driver_age: int = 30,
    ) -> dict:
        """
        Search for available rental cars.

        Args:
            pickup_location_id: Location ID from search_locations
            pickup_date: "YYYY-MM-DD"
            pickup_time: "HH:MM" (24h format)
            dropoff_date: "YYYY-MM-DD" (default: pickup + 7 days)
            dropoff_time: "HH:MM"
            dropoff_location_id: Different dropoff location (one-way)
            currency: Price currency
            language: Language code
            driver_age: Driver age (affects pricing)

        Returns:
            dict with cars list (vehicle, price, supplier, features)
        """
        if not dropoff_date:
            pickup_dt = datetime.strptime(pickup_date, "%Y-%m-%d")
            dropoff_date = (pickup_dt + timedelta(days=7)).strftime("%Y-%m-%d")

        if not dropoff_location_id:
            dropoff_location_id = pickup_location_id

        params = {
            "pickupLocationId": pickup_location_id,
            "pickupDate": pickup_date,
            "pickupTime": pickup_time,
            "dropoffLocationId": dropoff_location_id,
            "dropoffDate": dropoff_date,
            "dropoffTime": dropoff_time,
            "currency": currency,
            "language": language,
            "driverAge": driver_age,
        }

        result = self._request("GET", "/api/search", params=params, timeout=60)
        if not result["success"]:
            return result

        data = result["data"]
        raw_cars = data if isinstance(data, list) else data.get("cars", data.get("results", data.get("data", [])))

        cars = []
        for car in raw_cars:
            parsed = self._parse_car(car, currency, pickup_date, dropoff_date)
            if parsed:
                cars.append(parsed)

        cars.sort(key=lambda c: c["price_total"])

        return {
            "success": True,
            "cars": cars,
            "total_count": len(cars),
            "pickup_date": pickup_date,
            "dropoff_date": dropoff_date,
            "source": "discover_cars",
        }

    def _parse_car(self, car: dict, currency: str, pickup_date: str,
                   dropoff_date: str) -> Optional[dict]:
        """Parse a car result into normalized format."""
        try:
            # Vehicle info
            vehicle = car.get("vehicle", car)
            vehicle_name = vehicle.get("name", vehicle.get("vehicleName", "Unknown Car"))
            vehicle_type = vehicle.get("type", vehicle.get("vehicleType", ""))
            vehicle_class = vehicle.get("class", vehicle.get("vehicleClass", ""))

            # Features
            transmission = vehicle.get("transmission", vehicle.get("gearbox", ""))
            fuel_type = vehicle.get("fuelType", vehicle.get("fuel", ""))
            seats = vehicle.get("seats", vehicle.get("passengerCount", 0))
            doors = vehicle.get("doors", vehicle.get("doorCount", 0))
            bags_large = vehicle.get("largeBags", vehicle.get("bigSuitcases", 0))
            bags_small = vehicle.get("smallBags", vehicle.get("smallSuitcases", 0))
            air_conditioning = vehicle.get("airConditioning", vehicle.get("hasAC", False))

            # Supplier
            supplier = car.get("supplier", car.get("provider", {}))
            supplier_name = supplier.get("name", "") if isinstance(supplier, dict) else str(supplier)

            # Pricing
            pricing = car.get("pricing", car.get("price", car))
            price_total = float(pricing.get("totalPrice", pricing.get("total", pricing.get("price", 0))))
            price_per_day = float(pricing.get("pricePerDay", pricing.get("dailyRate", 0)))
            price_currency = pricing.get("currency", currency)

            # Extras
            fuel_policy = car.get("fuelPolicy", "")
            mileage = car.get("mileage", car.get("mileagePolicy", ""))
            insurance_included = car.get("insuranceIncluded", False)

            # Image
            image_url = vehicle.get("imageUrl", vehicle.get("image", ""))

            # Offer ID for booking
            offer_id = car.get("offerId", car.get("id", car.get("resultId", "")))

            return {
                "offer_id": str(offer_id),
                "vehicle_name": vehicle_name,
                "vehicle_type": vehicle_type,
                "vehicle_class": vehicle_class,
                "transmission": transmission,
                "fuel_type": fuel_type,
                "seats": seats,
                "doors": doors,
                "bags_large": bags_large,
                "bags_small": bags_small,
                "air_conditioning": air_conditioning,
                "supplier": supplier_name,
                "price_total": price_total,
                "price_per_day": price_per_day,
                "currency": price_currency,
                "fuel_policy": fuel_policy,
                "mileage_policy": mileage,
                "insurance_included": insurance_included,
                "image_url": image_url,
                "pickup_date": pickup_date,
                "dropoff_date": dropoff_date,
                "source": "discover_cars",
            }
        except Exception as e:
            logger.warning("Failed to parse DiscoverCars result: %s", str(e))
            return None

    # =========================================================================
    # CAR DETAILS
    # =========================================================================

    def get_car_details(self, offer_id: str, currency: str = "USD") -> dict:
        """Get detailed info for a specific car offer."""
        return self._request(
            "GET",
            f"/api/cars/{offer_id}",
            params={"currency": currency},
        )

    # =========================================================================
    # BOOKING
    # =========================================================================

    def create_booking(
        self,
        offer_id: str,
        driver: dict,
        flight_number: Optional[str] = None,
        extras: Optional[List[str]] = None,
    ) -> dict:
        """
        Book a rental car.

        Args:
            offer_id: Car offer ID from search results
            driver: {first_name, last_name, email, phone, country_code, age}
            flight_number: Optional flight number for airport pickups
            extras: Optional list of extra IDs (GPS, child seat, etc.)

        Returns:
            dict with booking_id, confirmation_number, status
        """
        body = {
            "offerId": offer_id,
            "driver": {
                "firstName": driver.get("first_name", ""),
                "lastName": driver.get("last_name", ""),
                "email": driver.get("email", ""),
                "phone": driver.get("phone", ""),
                "countryCode": driver.get("country_code", "US"),
                "age": driver.get("age", 30),
            },
        }

        if flight_number:
            body["flightNumber"] = flight_number
        if extras:
            body["extras"] = extras

        result = self._request("POST", "/api/bookings", json_data=body, timeout=60)
        if not result["success"]:
            return result

        data = result["data"]
        return {
            "success": True,
            "booking_id": data.get("bookingId", data.get("id", "")),
            "confirmation_number": data.get("confirmationNumber", data.get("reference", "")),
            "status": data.get("status", ""),
            "total_price": data.get("totalPrice", 0),
            "currency": data.get("currency", "USD"),
            "voucher_url": data.get("voucherUrl", ""),
            "raw_booking": data,
        }

    def get_booking(self, booking_id: str) -> dict:
        """Get booking details."""
        return self._request("GET", f"/api/bookings/{booking_id}")

    def cancel_booking(self, booking_id: str) -> dict:
        """Cancel a car rental booking."""
        result = self._request("POST", f"/api/bookings/{booking_id}/cancel")
        if not result["success"]:
            return result

        data = result["data"]
        return {
            "success": True,
            "booking_id": booking_id,
            "status": data.get("status", "cancelled"),
            "refund_amount": data.get("refundAmount", 0),
        }

    # =========================================================================
    # REFERENCE DATA
    # =========================================================================

    def get_currencies(self) -> dict:
        """Get supported currencies."""
        return self._request("GET", "/api/currencies")

    def get_fuel_policies(self) -> dict:
        """Get fuel policy descriptions."""
        return self._request("GET", "/api/fuel-policies")

    def get_payment_types(self) -> dict:
        """Get available payment types."""
        return self._request("GET", "/api/payment-types")


# =============================================================================
# CONVENIENCE FUNCTION (matches other vertical client patterns)
# =============================================================================

_cars_client: Optional[DiscoverCarsClient] = None


def _get_client() -> DiscoverCarsClient:
    global _cars_client
    if _cars_client is None:
        _cars_client = DiscoverCarsClient()
    return _cars_client


def search_car_rentals(
    pickup_location: str,
    pickup_date: Optional[str] = None,
    dropoff_date: Optional[str] = None,
    pickup_time: str = "10:00",
    dropoff_time: str = "10:00",
    dropoff_location: Optional[str] = None,
    currency: str = "USD",
    driver_age: int = 30,
) -> dict:
    """
    Search car rentals via Discover Cars.

    Convenience wrapper matching other vertical client patterns.

    Args:
        pickup_location: Airport code or location name (e.g., "CDG", "Paris")
        pickup_date: "YYYY-MM-DD" (default: tomorrow)
        dropoff_date: "YYYY-MM-DD" (default: +7 days)
        pickup_time: "HH:MM"
        dropoff_time: "HH:MM"
        dropoff_location: Different return location (one-way)
        currency: Price currency
        driver_age: Driver age

    Returns:
        dict with success, cars list, source
    """
    client = _get_client()
    if not client.is_configured():
        return {
            "success": False,
            "error": "Discover Cars not configured — set DISCOVER_CARS_USERNAME, DISCOVER_CARS_PASSWORD, DISCOVER_CARS_TOKEN in .env",
            "cars": [],
        }

    if not pickup_date:
        pickup_date = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

    # Resolve location name to location ID
    loc_result = client.search_locations(pickup_location)
    if not loc_result["success"] or not loc_result.get("locations"):
        return {
            "success": False,
            "error": f"Location not found: {pickup_location}",
            "cars": [],
        }
    pickup_id = loc_result["locations"][0]["location_id"]

    dropoff_id = pickup_id
    if dropoff_location:
        drop_result = client.search_locations(dropoff_location)
        if drop_result["success"] and drop_result.get("locations"):
            dropoff_id = drop_result["locations"][0]["location_id"]

    return client.search_cars(
        pickup_location_id=pickup_id,
        pickup_date=pickup_date,
        pickup_time=pickup_time,
        dropoff_date=dropoff_date,
        dropoff_time=dropoff_time,
        dropoff_location_id=dropoff_id,
        currency=currency,
        driver_age=driver_age,
    )
