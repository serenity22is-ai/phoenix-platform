"""
Duffel Stays Hotel API Client — ANASTASiA SDK

Hotel accommodation search and booking via Duffel's Stays API.
Complements liteAPI (aggregator) with Duffel's direct hotel supply
for rate comparison and booking diversification.

Duffel Stays API:
    Base URL: https://api.duffel.com
    Auth: Bearer token (Authorization header)
    Version: v2 (Duffel-Version header)
    Endpoints: /stays/* namespace

Usage:
    from clients.duffel_stays import DuffelStaysClient

    client = DuffelStaysClient(access_token="duffel_test_...")
    result = client.search_stays(
        latitude=40.7128, longitude=-74.0060,
        check_in_date="2026-04-15", check_out_date="2026-04-18",
        adults=2, rooms=1,
    )
    if result["success"]:
        for hotel in result["results"]:
            print(hotel["property_name"], hotel["cheapest_rate_total"],
                  hotel["cheapest_rate_currency"])

MYSTES KYRIOS LLC — Confidential.
"""

import logging
import os
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger("picasso.duffel_stays")

DUFFEL_BASE_URL = "https://api.duffel.com"


class DuffelStaysClient:
    """
    Duffel Stays Hotel API client for ANASTASiA.

    Simple Bearer token auth — no session management, no token refresh.
    Token is static until manually rotated in the Duffel dashboard.
    Uses the same DUFFEL_ACCESS_TOKEN as the flights client.

    Mirrors the DuffelNDCClient pattern for consistency across the SDK.

    Args:
        access_token: Duffel API access token (or set DUFFEL_ACCESS_TOKEN env var).
        base_url: API base URL (default: https://api.duffel.com).
    """

    def __init__(
        self,
        access_token: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        self._token = access_token or os.environ.get("DUFFEL_ACCESS_TOKEN", "")
        self._base_url = base_url or DUFFEL_BASE_URL
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {self._token}",
            "Duffel-Version": "v2",
            "Accept": "application/json",
            "Content-Type": "application/json",
        })

    def is_configured(self) -> bool:
        """Check if a Duffel token is set and looks valid."""
        return bool(self._token) and len(self._token) >= 20

    def _url(self, path: str) -> str:
        return f"{self._base_url}{path}"

    def _request(
        self,
        method: str,
        path: str,
        json_data: dict = None,
        params: dict = None,
        timeout: int = 60,
    ) -> dict:
        """Make an authenticated request to Duffel API."""
        try:
            resp = self._session.request(
                method,
                self._url(path),
                json=json_data,
                params=params,
                timeout=timeout,
            )
            if resp.status_code >= 400:
                error_body = resp.json() if resp.text else {}
                errors = error_body.get("errors", [])
                error_msg = errors[0].get("message", resp.text) if errors else resp.text
                error_code = errors[0].get("code", "") if errors else ""
                logger.error(
                    "Duffel Stays API %d on %s %s: %s",
                    resp.status_code, method, path, error_msg,
                )
                return {
                    "success": False,
                    "error": error_msg,
                    "error_code": error_code,
                    "status": resp.status_code,
                }
            data = resp.json()
            return {
                "success": True,
                "data": data.get("data", data),
                "meta": data.get("meta"),
            }
        except requests.exceptions.Timeout:
            logger.error("Duffel Stays request timed out: %s %s", method, path)
            return {"success": False, "error": "Request timed out"}
        except Exception as e:
            logger.error("Duffel Stays request failed: %s", str(e))
            return {"success": False, "error": str(e)}

    # =========================================================================
    # INTERNAL HELPERS
    # =========================================================================

    @staticmethod
    def _parse_search_result(
        result: dict,
        check_in: str = "",
        check_out: str = "",
    ) -> Optional[dict]:
        """
        Normalize a Duffel Stays search result into a standard dict.

        Args:
            result: Raw search result item from the API.
            check_in: Check-in date string passed through from the search.
            check_out: Check-out date string passed through from the search.

        Returns:
            Normalized hotel result dict, or None if parsing fails.
        """
        try:
            accommodation = result.get("accommodation", {})
            rates = result.get("rates", [])
            location = accommodation.get("location", {})
            geo = location.get("geographic_coordinates", {})

            # Find cheapest rate
            cheapest_rate = None
            cheapest_total = float("inf")
            for rate in rates:
                try:
                    total = float(rate.get("total_amount", "0"))
                    if total < cheapest_total:
                        cheapest_total = total
                        cheapest_rate = rate
                except (ValueError, TypeError):
                    continue

            return {
                "property_id": accommodation.get("id", ""),
                "property_name": accommodation.get("name", ""),
                "star_rating": accommodation.get("star_rating"),
                "location": {
                    "latitude": float(geo.get("latitude", 0)),
                    "longitude": float(geo.get("longitude", 0)),
                },
                "cheapest_rate_total": cheapest_total if cheapest_rate else 0.0,
                "cheapest_rate_currency": (
                    cheapest_rate.get("total_currency", "USD")
                    if cheapest_rate else "USD"
                ),
                "cheapest_rate_id": (
                    cheapest_rate.get("id", "")
                    if cheapest_rate else ""
                ),
                "rates": rates,
                "check_in": check_in,
                "check_out": check_out,
                "source": "duffel_stays",
                "raw": result,
            }
        except Exception as e:
            logger.warning("Failed to parse Duffel Stays result: %s", str(e))
            return None

    # =========================================================================
    # ACCOMMODATION SUGGESTIONS (Autocomplete)
    # =========================================================================

    def suggest_accommodation(self, query: str) -> dict:
        """
        Autocomplete accommodation by name or location.

        Minimum 3 characters required for the query.

        Args:
            query: Search text (e.g., "Hilton London", "Times Square")

        Returns:
            dict with success and list of accommodation suggestions.
        """
        if len(query) < 3:
            return {
                "success": False,
                "error": "Query must be at least 3 characters",
            }

        body = {"data": {"query": query}}
        result = self._request(
            "POST",
            "/stays/accommodation/suggestions",
            json_data=body,
        )
        if not result["success"]:
            return result

        suggestions = result["data"] if isinstance(result["data"], list) else []
        return {
            "success": True,
            "suggestions": [
                {
                    "id": s.get("id", ""),
                    "name": s.get("name", ""),
                    "type": s.get("type", ""),
                    "location": s.get("location", {}),
                }
                for s in suggestions
            ],
            "count": len(suggestions),
        }

    # =========================================================================
    # ACCOMMODATION BROWSE (Geo-radius)
    # =========================================================================

    def browse_accommodation(
        self,
        latitude: float,
        longitude: float,
        radius: int = 5,
    ) -> dict:
        """
        Browse accommodation within a geographic radius.

        Args:
            latitude: Center latitude for the search area.
            longitude: Center longitude for the search area.
            radius: Search radius in km (1-100, default: 5).

        Returns:
            dict with success and list of nearby properties.
        """
        radius = max(1, min(100, radius))
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "radius": radius,
        }
        result = self._request("GET", "/stays/accommodation", params=params)
        if not result["success"]:
            return result

        properties = result["data"] if isinstance(result["data"], list) else []
        return {
            "success": True,
            "properties": [
                {
                    "id": p.get("id", ""),
                    "name": p.get("name", ""),
                    "star_rating": p.get("star_rating"),
                    "location": p.get("location", {}),
                    "photos": p.get("photos", []),
                }
                for p in properties
            ],
            "count": len(properties),
        }

    # =========================================================================
    # ACCOMMODATION DETAILS
    # =========================================================================

    def get_accommodation(self, accommodation_id: str) -> dict:
        """
        Get detailed property information.

        Args:
            accommodation_id: Duffel accommodation ID.

        Returns:
            dict with success and full property details.
        """
        result = self._request(
            "GET", f"/stays/accommodation/{accommodation_id}"
        )
        if not result["success"]:
            return result

        prop = result["data"]
        return {
            "success": True,
            "property": {
                "id": prop.get("id", ""),
                "name": prop.get("name", ""),
                "description": prop.get("description", ""),
                "star_rating": prop.get("star_rating"),
                "location": prop.get("location", {}),
                "amenities": prop.get("amenities", []),
                "photos": prop.get("photos", []),
                "rooms": prop.get("rooms", []),
                "check_in_information": prop.get("check_in_information", {}),
                "check_out_information": prop.get("check_out_information", {}),
            },
            "raw": prop,
        }

    # =========================================================================
    # STAYS SEARCH
    # =========================================================================

    def search_stays(
        self,
        check_in_date: str,
        check_out_date: str,
        adults: int = 1,
        children: int = 0,
        rooms: int = 1,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        accommodation_ids: Optional[List[str]] = None,
    ) -> dict:
        """
        Search for hotel stays with pricing.

        Must provide EITHER geographic coordinates (latitude + longitude)
        OR a list of accommodation IDs — not both.

        Args:
            check_in_date: "YYYY-MM-DD" check-in date.
            check_out_date: "YYYY-MM-DD" check-out date.
            adults: Number of adult guests (default: 1).
            children: Number of child guests (default: 0).
            rooms: Number of rooms required (default: 1).
            latitude: Search center latitude (use with longitude).
            longitude: Search center longitude (use with latitude).
            accommodation_ids: List of specific accommodation IDs to search.

        Returns:
            dict with success, results (normalized), search_result_id, total_results.
        """
        # Build guest list
        guests = []
        for _ in range(adults):
            guests.append({"type": "adult"})
        for _ in range(children):
            guests.append({"type": "child"})

        data: Dict[str, Any] = {
            "check_in_date": check_in_date,
            "check_out_date": check_out_date,
            "guests": guests,
            "rooms": rooms,
        }

        if accommodation_ids:
            data["accommodation"] = accommodation_ids
        elif latitude is not None and longitude is not None:
            data["location"] = {
                "geographic_coordinates": {
                    "latitude": latitude,
                    "longitude": longitude,
                }
            }
        else:
            return {
                "success": False,
                "error": "Must provide either (latitude, longitude) or accommodation_ids",
            }

        body = {"data": data}

        result = self._request(
            "POST",
            "/stays/search",
            json_data=body,
            timeout=90,
        )
        if not result["success"]:
            return result

        response_data = result["data"]
        search_result_id = response_data.get("id", "")
        raw_results = response_data.get("results", [])

        # Parse and normalize results
        results = []
        for raw in raw_results:
            parsed = self._parse_search_result(
                raw,
                check_in=check_in_date,
                check_out=check_out_date,
            )
            if parsed:
                results.append(parsed)

        # Sort by cheapest rate ascending
        results.sort(key=lambda r: r.get("cheapest_rate_total", float("inf")))

        return {
            "success": True,
            "results": results,
            "search_result_id": search_result_id,
            "total_results": len(raw_results),
            "source": "duffel_stays",
        }

    # =========================================================================
    # FETCH ALL RATES
    # =========================================================================

    def fetch_all_rates(self, search_result_id: str) -> dict:
        """
        Fetch all available rates for a search result.

        Call this after search to get the complete rate set for a property.

        Args:
            search_result_id: The search result ID from search_stays().

        Returns:
            dict with success and full rate data.
        """
        result = self._request(
            "POST",
            f"/stays/search_results/{search_result_id}/actions/fetch_all_rates",
            json_data={},
        )
        if not result["success"]:
            return result

        response_data = result["data"]
        raw_results = response_data.get("results", [])

        # Re-parse results with all rates now available
        results = []
        for raw in raw_results:
            parsed = self._parse_search_result(raw)
            if parsed:
                results.append(parsed)

        return {
            "success": True,
            "results": results,
            "total_results": len(raw_results),
        }

    # =========================================================================
    # QUOTES (Price Lock)
    # =========================================================================

    def create_quote(self, rate_id: str) -> dict:
        """
        Create a quote to lock in a rate before booking.

        The quote holds the price for a limited time (see expires_at).

        Args:
            rate_id: The rate ID from search results.

        Returns:
            dict with success, quote_id, total_amount, total_currency, expires_at.
        """
        body = {"data": {"rate_id": rate_id}}
        result = self._request("POST", "/stays/quotes", json_data=body)
        if not result["success"]:
            return result

        quote = result["data"]
        return {
            "success": True,
            "quote_id": quote.get("id", ""),
            "rate_id": rate_id,
            "total_amount": quote.get("total_amount", ""),
            "total_currency": quote.get("total_currency", "USD"),
            "expires_at": quote.get("expires_at", ""),
            "accommodation": quote.get("accommodation", {}),
            "check_in_date": quote.get("check_in_date", ""),
            "check_out_date": quote.get("check_out_date", ""),
            "raw": quote,
        }

    # =========================================================================
    # BOOKING
    # =========================================================================

    def book_stay(
        self,
        quote_id: str,
        email: str,
        phone_number: str,
        guests: List[Dict[str, str]],
        loyalty_programme_account_number: Optional[str] = None,
        accommodation_special_requests: Optional[str] = None,
    ) -> dict:
        """
        Book a hotel stay using a quote.

        Args:
            quote_id: The quote ID from create_quote().
            email: Guest contact email.
            phone_number: Guest phone in E.164 format (e.g., "+14155552671").
            guests: List of guest dicts, each with "given_name" and "family_name".
            loyalty_programme_account_number: Optional loyalty program number.
            accommodation_special_requests: Optional free-text special requests.

        Returns:
            dict with booking_id, status, confirmation details.
        """
        data: Dict[str, Any] = {
            "quote_id": quote_id,
            "email": email,
            "phone_number": phone_number,
            "guests": guests,
        }

        if loyalty_programme_account_number:
            data["loyalty_programme_account_number"] = loyalty_programme_account_number

        if accommodation_special_requests:
            data["accommodation_special_requests"] = accommodation_special_requests

        body = {"data": data}

        result = self._request("POST", "/stays/bookings", json_data=body)
        if not result["success"]:
            return result

        booking = result["data"]
        return {
            "success": True,
            "booking_id": booking.get("id", ""),
            "status": booking.get("status", ""),
            "confirmation_number": booking.get("confirmation_number", ""),
            "check_in_date": booking.get("check_in_date", ""),
            "check_out_date": booking.get("check_out_date", ""),
            "total_amount": booking.get("total_amount", ""),
            "total_currency": booking.get("total_currency", ""),
            "accommodation": booking.get("accommodation", {}),
            "guests": booking.get("guests", []),
            "created_at": booking.get("created_at", ""),
            "cancellation_policy": booking.get("cancellation_policy", {}),
            "raw": booking,
        }

    # =========================================================================
    # BOOKING MANAGEMENT
    # =========================================================================

    def get_booking(self, booking_id: str) -> dict:
        """
        Get full booking details.

        Args:
            booking_id: Duffel stays booking ID.

        Returns:
            dict with success and booking details.
        """
        result = self._request("GET", f"/stays/bookings/{booking_id}")
        if not result["success"]:
            return result

        booking = result["data"]
        return {
            "success": True,
            "booking_id": booking.get("id", ""),
            "status": booking.get("status", ""),
            "confirmation_number": booking.get("confirmation_number", ""),
            "check_in_date": booking.get("check_in_date", ""),
            "check_out_date": booking.get("check_out_date", ""),
            "total_amount": booking.get("total_amount", ""),
            "total_currency": booking.get("total_currency", ""),
            "accommodation": booking.get("accommodation", {}),
            "guests": booking.get("guests", []),
            "created_at": booking.get("created_at", ""),
            "cancellation_policy": booking.get("cancellation_policy", {}),
            "raw": booking,
        }

    def list_bookings(
        self,
        limit: int = 50,
        after: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> dict:
        """
        List stays bookings with pagination.

        Args:
            limit: Max bookings to return (default: 50).
            after: Cursor for pagination (from meta.after in previous response).
            user_id: Filter bookings by user ID.

        Returns:
            dict with success and list of bookings.
        """
        params: Dict[str, Any] = {"limit": limit}
        if after:
            params["after"] = after
        if user_id:
            params["user_id"] = user_id

        result = self._request("GET", "/stays/bookings", params=params)
        if not result["success"]:
            return result

        bookings = result["data"] if isinstance(result["data"], list) else []
        return {
            "success": True,
            "bookings": [
                {
                    "booking_id": b.get("id", ""),
                    "status": b.get("status", ""),
                    "confirmation_number": b.get("confirmation_number", ""),
                    "check_in_date": b.get("check_in_date", ""),
                    "check_out_date": b.get("check_out_date", ""),
                    "total_amount": b.get("total_amount", ""),
                    "total_currency": b.get("total_currency", ""),
                    "created_at": b.get("created_at", ""),
                }
                for b in bookings
            ],
            "count": len(bookings),
            "meta": result.get("meta"),
        }

    def update_booking(self, booking_id: str, updates: dict) -> dict:
        """
        Update a stays booking.

        Args:
            booking_id: Duffel stays booking ID.
            updates: Dict of fields to update (wrapped in {"data": ...}).

        Returns:
            dict with success and updated booking details.
        """
        body = {"data": updates}
        result = self._request(
            "PATCH",
            f"/stays/bookings/{booking_id}",
            json_data=body,
        )
        if not result["success"]:
            return result

        booking = result["data"]
        return {
            "success": True,
            "booking_id": booking.get("id", ""),
            "status": booking.get("status", ""),
            "raw": booking,
        }

    # =========================================================================
    # CANCELLATION
    # =========================================================================

    def cancel_booking(self, booking_id: str) -> dict:
        """
        Cancel a stays booking.

        Args:
            booking_id: Duffel stays booking ID.

        Returns:
            dict with success, cancellation status, and refund info.
        """
        result = self._request(
            "POST",
            f"/stays/bookings/{booking_id}/actions/cancel",
        )
        if not result["success"]:
            return result

        cancellation = result["data"]
        return {
            "success": True,
            "booking_id": booking_id,
            "status": cancellation.get("status", "cancelled"),
            "refund_amount": cancellation.get("refund_amount", ""),
            "refund_currency": cancellation.get("refund_currency", ""),
            "raw": cancellation,
        }
