"""
Viator Activities & Tours API Client for MYSTES

Search 300,000+ tours, activities, and experiences across 200+ countries.
Commission-based: free to search, 8% commission on bookings.

Viator Partner API v2 (built from OpenAPI spec):
    Production: https://api.viator.com/partner
    Sandbox: https://api.sandbox.viator.com/partner
    Auth: exp-api-key header
    Docs: https://docs.viator.com/partner-api/technical/

33 endpoints. Key flow: search → product details → availability/check → bookings/hold → bookings/book

Usage:
    from viator_client import ViatorClient, search_activities

    result = search_activities("Paris", date_from="2026-04-15", date_to="2026-04-18")
    if result["success"]:
        for activity in result["activities"]:
            print(activity["title"], activity["price"], activity["currency"])
"""

import os
import logging
import uuid
from datetime import datetime, timedelta
from typing import List, Dict, Optional

from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger(__name__)

VIATOR_PRODUCTION_URL = "https://api.viator.com/partner"
VIATOR_SANDBOX_URL = "https://api.sandbox.viator.com/partner"


class ViatorClient:
    """
    Viator Partner API v2 client for tours & activities.

    Built from the official OpenAPI 3.0 spec (openapi.json).

    Auth: exp-api-key header (static API key from partner dashboard).
    Language: Accept-Language header.

    Full booking flow:
        1. GET  /destinations — cache destination list (weekly refresh)
        2. POST /products/search — search by destination + filters
           POST /search/freetext — search by keyword
        3. GET  /products/{product-code} — full product details
        4. POST /availability/check — real-time pricing + availability
        5. POST /bookings/hold — lock price (merchant partners only)
        6. POST /bookings/book — create booking
        7. POST /bookings/{booking-reference}/cancel — cancel booking

    Set VIATOR_API_KEY in .env.
    Set VIATOR_ENV=sandbox for testing (default: production).
    """

    def __init__(self, api_key: Optional[str] = None):
        import requests
        self._key = api_key or os.environ.get("VIATOR_API_KEY", "")
        self._session = requests.Session()

        env = os.environ.get("VIATOR_ENV", "production").lower()
        self._base_url = VIATOR_SANDBOX_URL if env == "sandbox" else VIATOR_PRODUCTION_URL

        self._session.headers.update({
            "exp-api-key": self._key,
            "Accept": "application/json;version=2.0",
            "Content-Type": "application/json",
            "Accept-Language": "en-US",
        })

    def is_configured(self) -> bool:
        return bool(self._key) and len(self._key) >= 10

    def _url(self, path: str) -> str:
        return f"{self._base_url}{path}"

    def _request(self, method: str, path: str, json_data: dict = None,
                 params: dict = None, timeout: int = 30) -> dict:
        """Make an authenticated request to Viator API."""
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
                error_msg = error_body.get("message", resp.text)
                if "errors" in error_body:
                    errors = error_body["errors"]
                    if isinstance(errors, list) and errors:
                        error_msg = errors[0].get("message", error_msg)
                logger.error("Viator API error %d: %s", resp.status_code, error_msg)
                return {"success": False, "error": error_msg, "status": resp.status_code}
            return {"success": True, "data": resp.json()}
        except Exception as e:
            logger.error("Viator request failed: %s", str(e))
            return {"success": False, "error": str(e)}

    # =========================================================================
    # DESTINATIONS (GET /destinations — cache weekly)
    # =========================================================================

    def get_destinations(self) -> dict:
        """
        Get all destinations supported by the API.

        Should be cached and refreshed weekly.

        Returns:
            dict with destinations list [{destinationId, name, type, parentId, lookupId, ...}]
        """
        result = self._request("GET", "/destinations")
        if not result["success"]:
            return result

        data = result["data"]
        destinations = data.get("destinations", [])
        return {
            "success": True,
            "destinations": destinations,
            "total_count": data.get("totalCount", len(destinations)),
        }

    # =========================================================================
    # SEARCH: POST /search/freetext
    # =========================================================================

    def search_freetext(
        self,
        query: str,
        search_types: Optional[List[str]] = None,
        currency: str = "USD",
        start: int = 1,
        count: int = 20,
    ) -> dict:
        """
        Freetext search for products, destinations, and/or attractions.

        From OpenAPI spec: searchTypes is array of objects with searchType field.
        Valid searchType values: "PRODUCTS", "DESTINATIONS", "ATTRACTIONS"

        Args:
            query: Free-text search term (required)
            search_types: List of types to search ["PRODUCTS", "DESTINATIONS"]
            currency: Currency code (required)
            start: Pagination start (1-based)
            count: Number of results

        Returns:
            dict with products, destinations, attractions sections
        """
        if not search_types:
            search_types = ["PRODUCTS"]

        body = {
            "searchTerm": query,
            "currency": currency,
            "searchTypes": [
                {"searchType": st, "pagination": {"start": start, "count": count}}
                for st in search_types
            ],
        }

        result = self._request("POST", "/search/freetext", json_data=body, timeout=45)
        if not result["success"]:
            return result

        data = result["data"]
        return {"success": True, "data": data}

    # =========================================================================
    # PRODUCT SEARCH: POST /products/search
    # =========================================================================

    def search_products(
        self,
        destination_id: str,
        currency: str = "USD",
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        sort_by: str = "DEFAULT",
        sort_order: str = "DESCENDING",
        start: int = 1,
        count: int = 20,
        attraction_id: Optional[int] = None,
        tag_ids: Optional[List[int]] = None,
        flags: Optional[List[str]] = None,
        lowest_price: Optional[float] = None,
        highest_price: Optional[float] = None,
        rating_from: Optional[int] = None,
        rating_to: Optional[int] = None,
        duration_from: Optional[int] = None,
        duration_to: Optional[int] = None,
        confirmation_type: Optional[str] = None,
    ) -> dict:
        """
        Search products by destination with filters.

        From OpenAPI spec:
        - filtering.destination (required): numeric destination reference string
        - sorting.sort: "DEFAULT", "PRICE", "TRAVELER_RATING"
        - sorting.order: "ASCENDING", "DESCENDING"
        - flags: "FREE_CANCELLATION", "SKIP_THE_LINE", "PRIVATE_TOUR", "LIKELY_TO_SELL_OUT", etc.
        - confirmationType: "INSTANT"

        Returns:
            dict with products list and totalCount
        """
        filtering = {"destination": str(destination_id)}

        if date_from:
            filtering["startDate"] = date_from
        if date_to:
            filtering["endDate"] = date_to
        if attraction_id is not None:
            filtering["attractionId"] = attraction_id
        if tag_ids:
            filtering["tags"] = tag_ids
        if flags:
            filtering["flags"] = flags
        if lowest_price is not None:
            filtering["lowestPrice"] = lowest_price
        if highest_price is not None:
            filtering["highestPrice"] = highest_price
        if rating_from is not None or rating_to is not None:
            rating = {}
            if rating_from is not None:
                rating["from"] = rating_from
            if rating_to is not None:
                rating["to"] = rating_to
            filtering["rating"] = rating
        if duration_from is not None or duration_to is not None:
            dur = {}
            if duration_from is not None:
                dur["from"] = duration_from
            if duration_to is not None:
                dur["to"] = duration_to
            filtering["durationInMinutes"] = dur
        if confirmation_type:
            filtering["confirmationType"] = confirmation_type

        body = {
            "filtering": filtering,
            "sorting": {"sort": sort_by, "order": sort_order},
            "pagination": {"start": start, "count": count},
            "currency": currency,
        }

        result = self._request("POST", "/products/search", json_data=body, timeout=45)
        if not result["success"]:
            return result

        data = result["data"]
        products = data.get("products", [])

        activities = []
        for product in products:
            activity = self._parse_product_summary(product, currency)
            if activity:
                activities.append(activity)

        return {
            "success": True,
            "activities": activities,
            "total_count": data.get("totalCount", len(activities)),
            "source": "viator",
        }

    def _parse_product_summary(self, product: dict, currency: str = "USD") -> Optional[dict]:
        """Parse a ProductSummary from search results into normalized format."""
        try:
            product_code = product.get("productCode", "")
            title = product.get("title", "Unknown Activity")

            # Pricing (ProductSearchPricing schema)
            pricing = product.get("pricing", {})
            summary = pricing.get("summary", {})
            from_price = float(summary.get("fromPrice", 0))
            from_price_before_discount = float(summary.get("fromPriceBeforeDiscount", from_price))
            price_currency = pricing.get("currency", currency)

            # Reviews
            reviews = product.get("reviews", {})
            avg_rating = reviews.get("combinedAverageRating", 0)
            total_reviews = reviews.get("totalReviews", 0)

            # Images — get first variant >= 200px wide
            images = product.get("images", [])
            thumbnail = ""
            if images:
                variants = images[0].get("variants", [])
                for v in variants:
                    if v.get("width", 0) >= 200:
                        thumbnail = v.get("url", "")
                        break
                if not thumbnail and variants:
                    thumbnail = variants[0].get("url", "")

            # Duration
            duration = product.get("duration", {})
            duration_str = ""
            if duration:
                fixed = duration.get("fixedDurationInMinutes")
                if fixed:
                    hours = fixed // 60
                    mins = fixed % 60
                    duration_str = f"{hours}h {mins}m" if hours else f"{mins}m"
                else:
                    from_mins = duration.get("variableDurationFromMinutes", 0)
                    to_mins = duration.get("variableDurationToMinutes", 0)
                    if from_mins and to_mins:
                        duration_str = f"{from_mins // 60}h-{to_mins // 60}h"

            # Flags (array of strings per OpenAPI spec)
            flags = product.get("flags", [])
            free_cancellation = "FREE_CANCELLATION" in flags
            skip_the_line = "SKIP_THE_LINE" in flags
            likely_to_sell_out = "LIKELY_TO_SELL_OUT" in flags
            private_tour = "PRIVATE_TOUR" in flags

            # Destinations
            destinations = product.get("destinations", [])
            destination_name = destinations[0].get("ref", "") if destinations else ""

            # Tags
            tags = product.get("tags", [])

            # Confirmation type
            confirmation_type = product.get("confirmationType", "")

            return {
                "product_code": product_code,
                "title": title,
                "description": product.get("description", ""),
                "price": from_price,
                "price_before_discount": from_price_before_discount,
                "currency": price_currency,
                "rating": avg_rating,
                "review_count": total_reviews,
                "duration": duration_str,
                "thumbnail": thumbnail,
                "free_cancellation": free_cancellation,
                "skip_the_line": skip_the_line,
                "likely_to_sell_out": likely_to_sell_out,
                "private_tour": private_tour,
                "confirmation_type": confirmation_type,
                "destination": destination_name,
                "tags": tags,
                "product_url": product.get("productUrl", ""),
                "source": "viator",
            }
        except Exception as e:
            logger.warning("Failed to parse Viator product: %s", str(e))
            return None

    # =========================================================================
    # PRODUCT DETAILS: GET /products/{product-code}
    # =========================================================================

    def get_product(self, product_code: str) -> dict:
        """
        Get full product details by product code.

        Returns the full Product schema with: productOptions, bookingQuestions,
        cancellationPolicy, logistics, itinerary, inclusions, exclusions, etc.
        """
        return self._request("GET", f"/products/{product_code}")

    def get_products_bulk(self, product_codes: List[str]) -> dict:
        """Bulk fetch product details (POST /products/bulk)."""
        body = {"productCodes": product_codes}
        return self._request("POST", "/products/bulk", json_data=body, timeout=60)

    def get_products_modified_since(self, modified_since: str, count: int = 100) -> dict:
        """Get products modified since a date (GET /products/modified-since)."""
        return self._request(
            "GET", "/products/modified-since",
            params={"modifiedSince": modified_since, "count": count},
        )

    def get_booking_questions(self) -> dict:
        """Get all possible booking questions (GET /products/booking-questions)."""
        return self._request("GET", "/products/booking-questions")

    # =========================================================================
    # AVAILABILITY: POST /availability/check
    # =========================================================================

    def check_availability(
        self,
        product_code: str,
        travel_date: str,
        currency: str = "USD",
        pax_mix: Optional[List[dict]] = None,
        product_option_code: Optional[str] = None,
        start_time: Optional[str] = None,
    ) -> dict:
        """
        Real-time availability and pricing check.

        From OpenAPI spec (CheckAvailabilityRequest):
        - productCode (required): string
        - travelDate (required): "YYYY-MM-DD"
        - currency (required): 3-letter code
        - paxMix (required): [{ageBand: "ADULT"|"CHILD"|"INFANT"|"YOUTH"|"SENIOR"|"TRAVELER", numberOfTravelers: int}]
        - productOptionCode (optional): string
        - startTime (optional): "HH:MM:SS"

        Response (CheckAvailabilityResponse):
        - bookableItems: [{productOptionCode, startTime, available, capacity, lineItems, unavailableReason}]

        Must be called immediately before booking.
        """
        if not pax_mix:
            pax_mix = [{"ageBand": "ADULT", "numberOfTravelers": 1}]

        body = {
            "productCode": product_code,
            "travelDate": travel_date,
            "currency": currency,
            "paxMix": pax_mix,
        }

        if product_option_code:
            body["productOptionCode"] = product_option_code
        if start_time:
            body["startTime"] = start_time

        result = self._request("POST", "/availability/check", json_data=body, timeout=30)
        if not result["success"]:
            return result

        data = result["data"]
        bookable_items = data.get("bookableItems", [])

        slots = []
        for item in bookable_items:
            slot = {
                "product_option_code": item.get("productOptionCode", ""),
                "start_time": item.get("startTime", ""),
                "available": item.get("available", False),
                "unavailable_reason": item.get("unavailableReason", ""),
                "total_price": 0,
                "currency": data.get("currency", currency),
                "line_items": [],
            }

            # Parse pricing from lineItems
            line_items = item.get("lineItems", [])
            total = 0
            for li in line_items:
                age_band = li.get("ageBand", "")
                num_travelers = li.get("numberOfTravelers", 0)
                subtotal_obj = li.get("subtotalPrice", {}).get("price", {})
                retail_price = float(subtotal_obj.get("recommendedRetailPrice", 0))
                partner_net = float(subtotal_obj.get("partnerNetPrice", 0))
                total += retail_price
                slot["line_items"].append({
                    "age_band": age_band,
                    "travelers": num_travelers,
                    "retail_price": retail_price,
                    "partner_net_price": partner_net,
                })

            slot["total_price"] = total
            slots.append(slot)

        return {
            "success": True,
            "product_code": data.get("productCode", product_code),
            "travel_date": data.get("travelDate", travel_date),
            "currency": data.get("currency", currency),
            "slots": slots,
            "source": "viator",
        }

    def get_availability_schedule(self, product_code: str) -> dict:
        """Get availability schedule for a product (GET /availability/schedules/{product-code})."""
        return self._request("GET", f"/availability/schedules/{product_code}")

    def get_availability_schedules_bulk(self, product_codes: List[str]) -> dict:
        """Bulk fetch availability schedules (POST /availability/schedules/bulk)."""
        body = {"productCodes": product_codes}
        return self._request("POST", "/availability/schedules/bulk", json_data=body, timeout=60)

    # =========================================================================
    # BOOKING: POST /bookings/hold + POST /bookings/book
    # =========================================================================

    def hold_booking(
        self,
        product_code: str,
        travel_date: str,
        currency: str = "USD",
        pax_mix: Optional[List[dict]] = None,
        product_option_code: Optional[str] = None,
        start_time: Optional[str] = None,
    ) -> dict:
        """
        Create a booking hold (merchant partners only).

        Locks price and/or availability. Returns bookingRef for use in book.

        From OpenAPI spec (BookingHoldRequest extends BookingRequest):
        Required: productCode, travelDate, paxMix, currency
        """
        if not pax_mix:
            pax_mix = [{"ageBand": "ADULT", "numberOfTravelers": 1}]

        body = {
            "productCode": product_code,
            "travelDate": travel_date,
            "currency": currency,
            "paxMix": pax_mix,
        }

        if product_option_code:
            body["productOptionCode"] = product_option_code
        if start_time:
            body["startTime"] = start_time

        return self._request("POST", "/bookings/hold", json_data=body, timeout=30)

    def create_booking(
        self,
        product_code: str,
        travel_date: str,
        currency: str = "USD",
        pax_mix: Optional[List[dict]] = None,
        product_option_code: Optional[str] = None,
        start_time: Optional[str] = None,
        booker_first_name: str = "",
        booker_last_name: str = "",
        communication_phone: str = "",
        communication_email: Optional[str] = None,
        partner_booking_ref: Optional[str] = None,
        booking_question_answers: Optional[List[dict]] = None,
        language_guide: Optional[dict] = None,
        booking_ref: Optional[str] = None,
    ) -> dict:
        """
        Book an activity/tour.

        From OpenAPI spec (BookingBookRequest extends BookingRequest):
        Required from BookingRequest: productCode, travelDate, paxMix, currency
        Required from BookingBookRequest: bookerInfo, communication, partnerBookingRef

        bookerInfo: {firstName, lastName} — name only, no email
        communication: {phone (required, must start with +), email (optional)}
        partnerBookingRef: your unique reference (required, max 100 chars)
        bookingRef: from hold_booking (optional, links to a hold)
        bookingQuestionAnswers: [{question, answer, unit?, travelerNum?}]

        Response (BookingBookResponse):
        - status: "CONFIRMED", "PENDING", "REJECTED"
        - bookingRef: Viator reference (BR-XXXXXXXXX)
        - partnerBookingRef, lineItems, totalPrice, cancellationPolicy, voucherInfo
        """
        if not pax_mix:
            pax_mix = [{"ageBand": "ADULT", "numberOfTravelers": 1}]

        if not partner_booking_ref:
            partner_booking_ref = f"MYSTES-{uuid.uuid4().hex[:12].upper()}"

        body = {
            "productCode": product_code,
            "travelDate": travel_date,
            "currency": currency,
            "paxMix": pax_mix,
            "bookerInfo": {
                "firstName": booker_first_name,
                "lastName": booker_last_name,
            },
            "communication": {
                "phone": communication_phone,
            },
            "partnerBookingRef": partner_booking_ref,
        }

        if product_option_code:
            body["productOptionCode"] = product_option_code
        if start_time:
            body["startTime"] = start_time
        if communication_email:
            body["communication"]["email"] = communication_email
        if booking_question_answers:
            body["bookingQuestionAnswers"] = booking_question_answers
        if language_guide:
            body["languageGuide"] = language_guide
        if booking_ref:
            body["bookingRef"] = booking_ref

        result = self._request("POST", "/bookings/book", json_data=body, timeout=60)
        if not result["success"]:
            return result

        data = result["data"]
        return {
            "success": True,
            "status": data.get("status", ""),
            "booking_ref": data.get("bookingRef", ""),
            "partner_booking_ref": data.get("partnerBookingRef", partner_booking_ref),
            "rejection_reason": data.get("rejectionReasonCode", ""),
            "total_price": data.get("totalPrice", {}),
            "line_items": data.get("lineItems", []),
            "cancellation_policy": data.get("cancellationPolicy", {}),
            "voucher_info": data.get("voucherInfo", {}),
            "raw_booking": data,
        }

    # =========================================================================
    # BOOKING CART: POST /bookings/cart/hold + POST /bookings/cart/book
    # =========================================================================

    def cart_hold(self, items: List[dict]) -> dict:
        """Hold multiple bookable items in a cart (POST /bookings/cart/hold)."""
        body = {"items": items}
        return self._request("POST", "/bookings/cart/hold", json_data=body, timeout=60)

    def cart_book(self, items: List[dict]) -> dict:
        """Book multiple items from a cart (POST /bookings/cart/book)."""
        body = {"items": items}
        return self._request("POST", "/bookings/cart/book", json_data=body, timeout=60)

    # =========================================================================
    # BOOKING STATUS: POST /bookings/status
    # =========================================================================

    def get_booking_status(
        self,
        booking_ref: Optional[str] = None,
        partner_booking_ref: Optional[str] = None,
        voucher_format: str = "HTML",
    ) -> dict:
        """
        Get booking status (POST /bookings/status).

        From OpenAPI spec: provide either bookingRef OR partnerBookingRef.
        voucherFormat: "PDF" or "HTML" (default HTML).
        """
        body = {}
        if booking_ref:
            body["bookingRef"] = booking_ref
        if partner_booking_ref:
            body["partnerBookingRef"] = partner_booking_ref
        if voucher_format:
            body["voucherFormat"] = voucher_format

        return self._request("POST", "/bookings/status", json_data=body)

    # =========================================================================
    # BOOKING CANCELLATION: POST /bookings/{booking-reference}/cancel
    # =========================================================================

    def get_cancel_quote(self, booking_ref: str) -> dict:
        """
        Get cancellation quote (GET /bookings/{booking-reference}/cancel-quote).

        Returns refund details before committing to cancellation.
        """
        return self._request("GET", f"/bookings/{booking_ref}/cancel-quote")

    def cancel_booking(self, booking_ref: str, reason_code: str) -> dict:
        """
        Cancel a booking (POST /bookings/{booking-reference}/cancel).

        From OpenAPI spec (CancellationRequest):
        - reasonCode (required): from GET /bookings/cancel-reasons

        Response (CancelBookingResponse):
        - bookingId, reason, status
        """
        body = {"reasonCode": reason_code}
        result = self._request("POST", f"/bookings/{booking_ref}/cancel", json_data=body)
        if not result["success"]:
            return result

        data = result["data"]
        return {
            "success": True,
            "booking_id": data.get("bookingId", ""),
            "status": data.get("status", ""),
            "reason": data.get("reason", {}),
            "refund_details": data.get("refundDetails", {}),
        }

    def get_cancel_reasons(self) -> dict:
        """Get valid cancellation reason codes (GET /bookings/cancel-reasons)."""
        return self._request("GET", "/bookings/cancel-reasons")

    def get_bookings_modified_since(self, modified_since: str) -> dict:
        """Get bookings modified since a date (GET /bookings/modified-since)."""
        return self._request(
            "GET", "/bookings/modified-since",
            params={"modifiedSince": modified_since},
        )

    # =========================================================================
    # AMENDMENTS: POST /amendment/quote + POST /amendment/amend/{quote-reference}
    # =========================================================================

    def check_amendment(self, booking_ref: str) -> dict:
        """Check if a booking is amendable (GET /amendment/check/{booking-reference})."""
        return self._request("GET", f"/amendment/check/{booking_ref}")

    def quote_amendment(self, booking_ref: str, new_travel_date: Optional[str] = None,
                        new_pax_mix: Optional[List[dict]] = None) -> dict:
        """Get an amendment quote (POST /amendment/quote)."""
        body = {"bookingRef": booking_ref}
        if new_travel_date:
            body["travelDate"] = new_travel_date
        if new_pax_mix:
            body["paxMix"] = new_pax_mix
        return self._request("POST", "/amendment/quote", json_data=body)

    def amend_booking(self, quote_reference: str) -> dict:
        """Confirm an amendment (POST /amendment/amend/{quote-reference})."""
        return self._request("POST", f"/amendment/amend/{quote_reference}")

    # =========================================================================
    # ATTRACTIONS: POST /attractions/search + GET /attractions/{attraction-id}
    # =========================================================================

    def search_attractions(self, destination_id: int, start: int = 1, count: int = 20) -> dict:
        """
        Search attractions for a destination (POST /attractions/search).

        From OpenAPI spec: destinationId is integer (required).
        """
        body = {
            "destinationId": destination_id,
            "sorting": {"sort": "TRAVELER_RATING", "order": "DESCENDING"},
            "pagination": {"start": start, "count": count},
        }
        return self._request("POST", "/attractions/search", json_data=body)

    def get_attraction(self, attraction_id: str) -> dict:
        """Get attraction details (GET /attractions/{attraction-id})."""
        return self._request("GET", f"/attractions/{attraction_id}")

    # =========================================================================
    # REVIEWS: POST /reviews/product
    # =========================================================================

    def get_reviews(
        self,
        product_code: str,
        count: int = 10,
        start: int = 1,
        provider: str = "ALL",
        sort_by: str = "MOST_RECENT",
        ratings: Optional[List[int]] = None,
    ) -> dict:
        """
        Get reviews for a product (POST /reviews/product).

        From OpenAPI spec:
        - provider (required): "VIATOR", "TRIPADVISOR", "ALL"
        - sortBy: "HIGHEST_RATING_PER_LOCALE", "MOST_RECENT", "HIGHEST_RATED", "LOWEST_RATED"
        - ratings: [3, 4, 5] to filter
        """
        body = {
            "productCode": product_code,
            "count": count,
            "start": start,
            "provider": provider,
        }
        if sort_by:
            body["sortBy"] = sort_by
        if ratings:
            body["ratings"] = ratings

        return self._request("POST", "/reviews/product", json_data=body)

    # =========================================================================
    # REFERENCE DATA: GET /products/tags, GET /destinations, POST /exchange-rates
    # =========================================================================

    def get_tags(self) -> dict:
        """Get all product tags/categories (GET /products/tags)."""
        return self._request("GET", "/products/tags")

    def get_exchange_rates(self, source_currency: str, target_currencies: List[str]) -> dict:
        """Get exchange rates (POST /exchange-rates)."""
        body = {
            "sourceCurrency": source_currency,
            "targetCurrencies": target_currencies,
        }
        return self._request("POST", "/exchange-rates", json_data=body)

    def get_locations_bulk(self, locations: List[dict]) -> dict:
        """Get location details in bulk (POST /locations/bulk)."""
        body = {"locations": locations}
        return self._request("POST", "/locations/bulk", json_data=body)

    def search_suppliers_by_products(self, product_codes: List[str]) -> dict:
        """Search suppliers by product codes (POST /suppliers/search/product-codes)."""
        body = {"productCodes": product_codes}
        return self._request("POST", "/suppliers/search/product-codes", json_data=body)


# =============================================================================
# CONVENIENCE FUNCTION (matches other vertical client patterns)
# =============================================================================

_viator_client: Optional[ViatorClient] = None


def _get_client() -> ViatorClient:
    global _viator_client
    if _viator_client is None:
        _viator_client = ViatorClient()
    return _viator_client


def search_activities(
    destination: Optional[str] = None,
    query: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    currency: str = "USD",
    max_results: int = 20,
    user=None,
) -> dict:
    """
    Search activities/tours via Viator.

    Convenience wrapper matching the liteapi_client.search_hotels interface.

    Args:
        destination: Destination name or numeric ID (e.g., "Paris", "684")
        query: Freetext search (alternative to destination)
        date_from: "YYYY-MM-DD"
        date_to: "YYYY-MM-DD"
        currency: Price currency
        max_results: Max results to return
        user: Current user (for fee calculation)

    Returns:
        dict with success, activities list, source
    """
    client = _get_client()
    if not client.is_configured():
        return {
            "success": False,
            "error": "Viator not configured — set VIATOR_API_KEY in .env",
            "activities": [],
        }

    # Default dates
    if not date_from:
        date_from = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    if not date_to:
        date_to = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")

    # If query provided, use freetext search
    if query and not destination:
        ft_result = client.search_freetext(
            query=query, search_types=["PRODUCTS"],
            currency=currency, count=max_results,
        )
        if not ft_result["success"]:
            return {"success": False, "error": ft_result.get("error", ""), "activities": []}

        products = ft_result["data"].get("products", {}).get("results", [])
        activities = []
        for p in products:
            parsed = client._parse_product_summary(p, currency)
            if parsed:
                activities.append(parsed)
        return {"success": True, "activities": activities, "total_count": len(activities), "source": "viator"}

    # Resolve destination name to ID if needed
    destination_id = None
    if destination:
        if destination.isdigit():
            destination_id = destination
        else:
            ft_result = client.search_freetext(
                query=destination, search_types=["DESTINATIONS"],
                currency=currency, count=5,
            )
            if ft_result["success"]:
                dest_data = ft_result["data"].get("destinations", {})
                dest_results = dest_data.get("results", [])
                if dest_results:
                    destination_id = str(dest_results[0].get("ref", dest_results[0].get("destinationId", "")))

    if not destination_id:
        return {
            "success": False,
            "error": f"Could not resolve destination: {destination}",
            "activities": [],
        }

    return client.search_products(
        destination_id=destination_id,
        date_from=date_from,
        date_to=date_to,
        currency=currency,
        count=max_results,
    )
