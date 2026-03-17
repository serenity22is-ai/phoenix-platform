"""
Duffel NDC Flight API Client — ANASTASiA SDK

Direct NDC connections to 300+ airlines via Duffel's unified API.
Complements Picasso/Redbox (GDS/consolidator) with NDC-only fares
that airlines pull from traditional GDS channels.

Duffel API:
    Base URL: https://api.duffel.com
    Auth: Bearer token (Authorization header)
    Version: v2 (Duffel-Version header)
    Pricing: Free search, $3 + 1% per confirmed booking

Usage:
    from clients.duffel import DuffelNDCClient

    client = DuffelNDCClient(access_token="duffel_test_...")
    result = client.search_flights("JFK", "LHR", "2026-04-15")
    if result["success"]:
        for flight in result["flights"]:
            print(flight["airline"], flight["price"], flight["duration"])

MYSTES KYRIOS LLC — Confidential.
"""

import logging
import os
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

import requests

logger = logging.getLogger("picasso.duffel")

DUFFEL_BASE_URL = "https://api.duffel.com"

CABIN_MAP = {
    "economy": "economy",
    "ECONOMY": "economy",
    "premium_economy": "premium_economy",
    "PREMIUM_ECONOMY": "premium_economy",
    "premium economy": "premium_economy",
    "business": "business",
    "BUSINESS": "business",
    "first": "first",
    "FIRST": "first",
}


class DuffelNDCClient:
    """
    Duffel NDC Flight API client for ANASTASiA.

    Simple Bearer token auth — no session management, no token refresh.
    Token is static until manually rotated in the Duffel dashboard.

    Mirrors the RedboxClient pattern for consistency across the SDK.

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
                    "Duffel API %d on %s %s: %s",
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
            logger.error("Duffel request timed out: %s %s", method, path)
            return {"success": False, "error": "Request timed out"}
        except Exception as e:
            logger.error("Duffel request failed: %s", str(e))
            return {"success": False, "error": str(e)}

    # =========================================================================
    # PLACES (Airport/City autocomplete)
    # =========================================================================

    def search_places(self, query: str) -> List[Dict]:
        """
        Autocomplete airports and cities by name.

        Args:
            query: Search text (e.g., "New York", "JFK", "London")

        Returns:
            List of place dicts with iata_code, name, type, city, etc.
        """
        result = self._request("GET", "/places/suggestions", params={"query": query})
        if not result["success"]:
            return []
        places = result["data"]
        return [
            {
                "iata_code": p.get("iata_code", ""),
                "name": p.get("name", ""),
                "type": p.get("type", ""),
                "city_name": p.get("city_name", (p.get("city") or {}).get("name", "")),
                "iata_city_code": p.get("iata_city_code", ""),
                "latitude": p.get("latitude"),
                "longitude": p.get("longitude"),
            }
            for p in places
        ]

    # =========================================================================
    # FLIGHT SEARCH
    # =========================================================================

    def search_flights(
        self,
        origin: str,
        destination: str,
        departure_date: str,
        return_date: Optional[str] = None,
        adults: int = 1,
        children: int = 0,
        infants: int = 0,
        cabin_class: str = "economy",
        max_connections: Optional[int] = None,
        max_results: int = 50,
        nonstop_only: bool = False,
    ) -> dict:
        """
        Search for flights via Duffel NDC API.

        Args:
            origin: IATA airport code (e.g., "JFK")
            destination: IATA airport code (e.g., "LHR")
            departure_date: "YYYY-MM-DD"
            return_date: "YYYY-MM-DD" (optional, for round-trip)
            adults: Number of adult passengers (default: 1)
            children: Number of child passengers aged 2-11 (default: 0)
            infants: Number of infant (lap) passengers under 2 (default: 0)
            cabin_class: economy, premium_economy, business, first
            max_connections: Max stops (0=direct only, None=any)
            max_results: Cap on results returned (default: 50)
            nonstop_only: If True, sets max_connections=0

        Returns:
            dict with success, flights list, offer_request_id, total_offers
        """
        if nonstop_only:
            max_connections = 0

        slices = [
            {
                "origin": origin.upper(),
                "destination": destination.upper(),
                "departure_date": departure_date,
            }
        ]
        if return_date:
            slices.append({
                "origin": destination.upper(),
                "destination": origin.upper(),
                "departure_date": return_date,
            })

        if max_connections is not None:
            for s in slices:
                s["max_connections"] = max_connections

        # Build passenger list
        pax = []
        for _ in range(adults):
            pax.append({"type": "adult"})
        for _ in range(children):
            pax.append({"type": "child", "age": 8})  # default child age
        for _ in range(infants):
            pax.append({"type": "infant_without_seat"})

        cabin = CABIN_MAP.get(cabin_class, "economy")

        body = {
            "data": {
                "slices": slices,
                "passengers": pax,
                "cabin_class": cabin,
            }
        }

        result = self._request(
            "POST",
            "/air/offer_requests",
            json_data=body,
            params={"return_offers": "true", "supplier_timeout": "30000"},
            timeout=90,
        )

        if not result["success"]:
            return result

        data = result["data"]
        offer_request_id = data.get("id", "")
        offers = data.get("offers", [])

        # Parse offers into normalized flight dicts
        flights = []
        for offer in offers:
            flight = self._parse_offer(offer)
            if flight:
                flights.append(flight)

        # Sort by price ascending
        flights.sort(key=lambda f: float(f.get("price", 9999)))

        # Cap results
        if max_results and len(flights) > max_results:
            flights = flights[:max_results]

        return {
            "success": True,
            "flights": flights,
            "offer_request_id": offer_request_id,
            "total_offers": len(offers),
            "source": "duffel_ndc",
        }

    def _parse_offer(self, offer: dict) -> Optional[dict]:
        """Parse a Duffel offer into a normalized flight dict."""
        try:
            slices = offer.get("slices", [])
            if not slices:
                return None

            outbound = slices[0]
            segments = outbound.get("segments", [])
            if not segments:
                return None

            first_seg = segments[0]
            last_seg = segments[-1]

            marketing_carrier = first_seg.get("marketing_carrier", {})
            operating_carrier = first_seg.get("operating_carrier", {})

            dep_time = first_seg.get("departing_at", "")
            arr_time = last_seg.get("arriving_at", "")

            # Calculate duration
            duration_str = ""
            if dep_time and arr_time:
                try:
                    dep_dt = datetime.fromisoformat(dep_time)
                    arr_dt = datetime.fromisoformat(arr_time)
                    delta = arr_dt - dep_dt
                    hours, remainder = divmod(int(delta.total_seconds()), 3600)
                    minutes = remainder // 60
                    duration_str = f"{hours}h {minutes}m"
                except (ValueError, TypeError):
                    pass

            # Build segment details
            segment_details = []
            for seg in segments:
                seg_carrier = seg.get("marketing_carrier", {})
                seg_op = seg.get("operating_carrier", {})
                seg_pax = seg.get("passengers", [{}])
                segment_details.append({
                    "flight_number": (
                        seg_carrier.get("iata_code", "") +
                        seg.get("marketing_carrier_flight_number", "")
                    ),
                    "aircraft": seg.get("aircraft", {}).get("name", ""),
                    "origin": seg.get("origin", {}).get("iata_code", ""),
                    "origin_name": seg.get("origin", {}).get("name", ""),
                    "destination": seg.get("destination", {}).get("iata_code", ""),
                    "destination_name": seg.get("destination", {}).get("name", ""),
                    "departing_at": seg.get("departing_at", ""),
                    "arriving_at": seg.get("arriving_at", ""),
                    "operating_carrier": seg_op.get("name", ""),
                    "operating_carrier_code": seg_op.get("iata_code", ""),
                    "cabin_class": (
                        seg_pax[0].get("cabin_class_marketing_name", "")
                        if seg_pax else ""
                    ),
                    "cabin": (
                        seg_pax[0].get("cabin_class", "economy")
                        if seg_pax else "economy"
                    ),
                })

            # Baggage info
            bags = []
            for seg in segments:
                for pax in seg.get("passengers", []):
                    for bag in pax.get("baggages", []):
                        bags.append({
                            "type": bag.get("type", ""),
                            "quantity": bag.get("quantity", 0),
                        })

            origin_info = first_seg.get("origin", {})
            dest_info = last_seg.get("destination", {})

            # Parse conditions (cancellation/change policies)
            conditions = offer.get("conditions", {})
            change_cond = conditions.get("change_before_departure") or {}
            refund_cond = conditions.get("refund_before_departure") or {}

            return {
                "offer_id": offer.get("id", ""),
                "airline": marketing_carrier.get("name", "Unknown"),
                "airline_code": marketing_carrier.get("iata_code", ""),
                "airline_logo": marketing_carrier.get("logo_symbol_url", ""),
                "operating_airline": operating_carrier.get("name", ""),
                "origin": origin_info.get("iata_code", ""),
                "origin_name": origin_info.get("name", ""),
                "destination": dest_info.get("iata_code", ""),
                "destination_name": dest_info.get("name", ""),
                "departure_time": dep_time,
                "arrival_time": arr_time,
                "duration": duration_str,
                "stops": len(segments) - 1,
                "price": offer.get("total_amount", "0"),
                "base_fare": offer.get("base_amount", "0"),
                "tax": offer.get("tax_amount", "0"),
                "currency": offer.get("total_currency", "USD"),
                "cabin_class": offer.get("cabin_class", "economy"),
                "segments": segment_details,
                "baggages": bags,
                "source": "duffel_ndc",
                "owner": offer.get("owner", {}).get("name", ""),
                "expires_at": offer.get("expires_at", ""),
                # Conditions
                "changeable": change_cond.get("allowed"),
                "change_penalty": change_cond.get("penalty_amount"),
                "refundable": refund_cond.get("allowed"),
                "refund_penalty": refund_cond.get("penalty_amount"),
                # Passengers from offer (needed for booking)
                "passenger_ids": [
                    p.get("id", "") for p in offer.get("passengers", [])
                ],
                # Return slice
                "return_slice": (
                    self._parse_return_slice(slices[1])
                    if len(slices) > 1 and slices[1] is not None
                    else None
                ),
            }
        except Exception as e:
            logger.warning("Failed to parse Duffel offer: %s", str(e))
            return None

    def _parse_return_slice(self, slice_data: dict) -> Optional[dict]:
        """Parse return slice for round-trip flights."""
        segments = slice_data.get("segments", [])
        if not segments:
            return None
        first_seg = segments[0]
        last_seg = segments[-1]
        return {
            "origin": first_seg.get("origin", {}).get("iata_code", ""),
            "destination": last_seg.get("destination", {}).get("iata_code", ""),
            "departure_time": first_seg.get("departing_at", ""),
            "arrival_time": last_seg.get("arriving_at", ""),
            "stops": len(segments) - 1,
            "airline": first_seg.get("marketing_carrier", {}).get("name", ""),
        }

    # =========================================================================
    # OFFER DETAILS & SERVICES
    # =========================================================================

    def get_offer(self, offer_id: str) -> dict:
        """Get current offer details (price may have changed since search)."""
        result = self._request("GET", f"/air/offers/{offer_id}")
        if not result["success"]:
            return result
        offer = result["data"]
        flight = self._parse_offer(offer)
        return {
            "success": True,
            "flight": flight,
            "raw": offer,
        }

    def get_available_services(self, offer_id: str) -> dict:
        """
        Get available ancillary services for an offer.

        Returns baggage, seats, meals, and other purchasable extras.
        """
        result = self._request(
            "GET", f"/air/offers/{offer_id}/available_services"
        )
        if not result["success"]:
            return result

        services = result["data"] if isinstance(result["data"], list) else []
        parsed = []
        for svc in services:
            parsed.append({
                "service_id": svc.get("id", ""),
                "type": svc.get("type", ""),
                "total_amount": svc.get("total_amount", "0"),
                "total_currency": svc.get("total_currency", "USD"),
                "maximum_quantity": svc.get("maximum_quantity", 1),
                "passenger_ids": svc.get("passenger_ids", []),
                "segment_ids": svc.get("segment_ids", []),
                "metadata": svc.get("metadata", {}),
            })

        return {
            "success": True,
            "services": parsed,
            "count": len(parsed),
        }

    # =========================================================================
    # SEAT MAPS
    # =========================================================================

    def get_seat_map(self, offer_id: str) -> dict:
        """
        Get seat map for an offer.

        Returns cabin layout with available/occupied seats per segment.
        """
        result = self._request(
            "GET", "/air/seat_maps", params={"offer_id": offer_id}
        )
        if not result["success"]:
            return result

        seat_maps = result["data"] if isinstance(result["data"], list) else []
        parsed = []
        for sm in seat_maps:
            cabins = sm.get("cabins", [])
            segment = sm.get("slice", {})
            parsed.append({
                "segment_id": sm.get("segment_id", ""),
                "slice_id": sm.get("slice_id", ""),
                "cabins": len(cabins),
                "total_rows": sum(len(c.get("rows", [])) for c in cabins),
                "raw_cabins": cabins,  # Full cabin/row/seat data
            })

        return {
            "success": True,
            "seat_maps": parsed,
            "count": len(parsed),
        }

    # =========================================================================
    # BOOKING (Order Creation)
    # =========================================================================

    def book_flight(
        self,
        offer_id: str,
        passengers: List[dict],
        payment_type: str = "balance",
        payment_amount: Optional[str] = None,
        payment_currency: Optional[str] = None,
        services: Optional[List[dict]] = None,
        metadata: Optional[dict] = None,
    ) -> dict:
        """
        Book a flight by creating an order.

        Args:
            offer_id: The selected offer ID from search results
            passengers: List of passenger dicts with:
                - id: passenger ID from offer (links search pax to booking pax)
                - given_name, family_name, born_on (YYYY-MM-DD)
                - gender: "m" or "f"
                - title: "mr", "mrs", "ms", "miss", "dr"
                - email, phone_number (with country code)
                - identity_documents: [{type, unique_identifier, expires_on, issuing_country_code}]
                - loyalty_programme_accounts: [{airline_iata_code, account_number}]
            payment_type: "balance" (Duffel balance) or "arc_bsp_cash" (IATA agent)
            payment_amount: Total amount (if not provided, fetches from offer)
            payment_currency: Currency code (if not provided, fetches from offer)
            services: List of service selections [{id, quantity}]
            metadata: Custom metadata dict stored with order

        Returns:
            dict with booking_reference, order_id, status, documents
        """
        # Refresh offer to get current price
        offer_result = self._request("GET", f"/air/offers/{offer_id}")
        if not offer_result["success"]:
            return offer_result

        offer_data = offer_result["data"]
        amount = payment_amount or offer_data.get("total_amount", "")
        currency = payment_currency or offer_data.get("total_currency", "USD")

        # Add service costs to total if services selected
        if services:
            svc_total = sum(
                float(s.get("amount", 0)) for s in services if s.get("amount")
            )
            if svc_total > 0:
                amount = str(round(float(amount) + svc_total, 2))

        body: Dict[str, Any] = {
            "data": {
                "type": "instant",
                "selected_offers": [offer_id],
                "payments": [
                    {
                        "type": payment_type,
                        "amount": amount,
                        "currency": currency,
                    }
                ],
                "passengers": passengers,
            }
        }

        if services:
            body["data"]["services"] = [
                {"id": s["id"], "quantity": s.get("quantity", 1)}
                for s in services
            ]

        if metadata:
            body["data"]["metadata"] = metadata

        result = self._request("POST", "/air/orders", json_data=body)
        if not result["success"]:
            return result

        order = result["data"]
        return {
            "success": True,
            "order_id": order.get("id", ""),
            "booking_reference": order.get("booking_reference", ""),
            "status": order.get("status", ""),
            "total_amount": order.get("total_amount", ""),
            "total_currency": order.get("total_currency", ""),
            "base_amount": order.get("base_amount", ""),
            "tax_amount": order.get("tax_amount", ""),
            "passengers": order.get("passengers", []),
            "slices": order.get("slices", []),
            "documents": order.get("documents", []),
            "created_at": order.get("created_at", ""),
        }

    # =========================================================================
    # ORDER MANAGEMENT
    # =========================================================================

    def get_order(self, order_id: str) -> dict:
        """Get full order details (booking status, tickets, segments)."""
        result = self._request("GET", f"/air/orders/{order_id}")
        if not result["success"]:
            return result
        order = result["data"]
        return {
            "success": True,
            "order_id": order.get("id", ""),
            "booking_reference": order.get("booking_reference", ""),
            "status": order.get("status", ""),
            "total_amount": order.get("total_amount", ""),
            "total_currency": order.get("total_currency", ""),
            "passengers": order.get("passengers", []),
            "slices": order.get("slices", []),
            "documents": order.get("documents", []),
            "conditions": order.get("conditions", {}),
            "created_at": order.get("created_at", ""),
            "metadata": order.get("metadata", {}),
        }

    def list_orders(self, limit: int = 50, after: str = None) -> dict:
        """List orders with pagination."""
        params = {"limit": limit}
        if after:
            params["after"] = after
        result = self._request("GET", "/air/orders", params=params)
        if not result["success"]:
            return result
        orders = result["data"] if isinstance(result["data"], list) else []
        return {
            "success": True,
            "orders": [
                {
                    "order_id": o.get("id", ""),
                    "booking_reference": o.get("booking_reference", ""),
                    "status": o.get("status", ""),
                    "total_amount": o.get("total_amount", ""),
                    "total_currency": o.get("total_currency", ""),
                    "created_at": o.get("created_at", ""),
                }
                for o in orders
            ],
            "count": len(orders),
            "meta": result.get("meta"),
        }

    # =========================================================================
    # CANCELLATION
    # =========================================================================

    def cancel_order(self, order_id: str) -> dict:
        """
        Cancel an order (two-step: request → confirm).

        Returns refund amount and penalty before confirming.
        """
        # Step 1: Request cancellation
        body = {"data": {"order_id": order_id}}
        result = self._request(
            "POST", "/air/order_cancellations", json_data=body
        )
        if not result["success"]:
            return result

        cancellation = result["data"]
        cancellation_id = cancellation.get("id", "")

        # Extract refund info
        refund_amount = cancellation.get("refund_amount", "0")
        refund_currency = cancellation.get("refund_currency", "USD")

        # Step 2: Confirm the cancellation
        confirm_result = self._request(
            "POST",
            f"/air/order_cancellations/{cancellation_id}/actions/confirm",
        )
        if not confirm_result["success"]:
            return {
                "success": False,
                "error": confirm_result.get("error", "Cancellation confirmation failed"),
                "cancellation_id": cancellation_id,
                "refund_amount": refund_amount,
                "refund_currency": refund_currency,
            }

        return {
            "success": True,
            "cancellation_id": cancellation_id,
            "status": "confirmed",
            "refund_amount": refund_amount,
            "refund_currency": refund_currency,
        }

    def get_cancellation(self, cancellation_id: str) -> dict:
        """Get cancellation details."""
        return self._request(
            "GET", f"/air/order_cancellations/{cancellation_id}"
        )

    # =========================================================================
    # ORDER CHANGES
    # =========================================================================

    def request_order_change(
        self,
        order_id: str,
        new_slices: List[dict],
    ) -> dict:
        """
        Request to change an order (date/route change).

        Args:
            order_id: Order to change
            new_slices: New slice definitions [{origin, destination, departure_date}]

        Returns:
            Change request with available change offers
        """
        body = {
            "data": {
                "order_id": order_id,
                "slices": {
                    "add": [
                        {
                            "origin": s["origin"],
                            "destination": s["destination"],
                            "departure_date": s["departure_date"],
                            "cabin_class": s.get("cabin_class", "economy"),
                        }
                        for s in new_slices
                    ],
                },
            }
        }
        return self._request(
            "POST", "/air/order_change_requests", json_data=body
        )

    def confirm_order_change(self, change_offer_id: str, payment: dict = None) -> dict:
        """
        Confirm an order change with a selected change offer.

        Args:
            change_offer_id: The change offer to accept
            payment: Payment for fare difference (if any)
        """
        body: Dict[str, Any] = {
            "data": {
                "selected_order_change_offer": change_offer_id,
            }
        }
        if payment:
            body["data"]["payment"] = payment

        return self._request("POST", "/air/order_changes", json_data=body)

    # =========================================================================
    # REFERENCE DATA
    # =========================================================================

    def list_airlines(self, limit: int = 200) -> dict:
        """List airlines available through Duffel."""
        result = self._request(
            "GET", "/air/airlines", params={"limit": limit}
        )
        if not result["success"]:
            return result
        airlines = result["data"] if isinstance(result["data"], list) else []
        return {
            "success": True,
            "airlines": [
                {
                    "id": a.get("id", ""),
                    "name": a.get("name", ""),
                    "iata_code": a.get("iata_code", ""),
                    "logo": a.get("logo_symbol_url", ""),
                }
                for a in airlines
            ],
            "count": len(airlines),
        }

    def get_airline(self, airline_id: str) -> dict:
        """Get airline details by ID."""
        return self._request("GET", f"/air/airlines/{airline_id}")

    def list_airports(self, limit: int = 200) -> dict:
        """List airports."""
        return self._request("GET", "/air/airports", params={"limit": limit})

    def get_airport(self, airport_id: str) -> dict:
        """Get airport details."""
        return self._request("GET", f"/air/airports/{airport_id}")

    # =========================================================================
    # PAYMENTS (Balance)
    # =========================================================================

    def get_balance(self) -> dict:
        """Check Duffel account balance."""
        return self._request("GET", "/payments/balance")

    # =========================================================================
    # WEBHOOKS
    # =========================================================================

    def create_webhook(self, url: str, events: List[str]) -> dict:
        """Register a webhook for order events."""
        body = {
            "data": {
                "url": url,
                "events": events,
            }
        }
        return self._request("POST", "/air/webhooks", json_data=body)

    def list_webhooks(self) -> dict:
        """List registered webhooks."""
        return self._request("GET", "/air/webhooks")
