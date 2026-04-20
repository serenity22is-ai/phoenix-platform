"""
Duffel NDC Flight API Client for MYSTES

Direct NDC connections to 300+ airlines via Duffel's unified API.
Complements Picasso (GDS/consolidator) with NDC-only fares that airlines
pull from traditional GDS channels.

Duffel API:
    Base URL: https://api.duffel.com
    Auth: Bearer token (Authorization header)
    Version: v2 (Duffel-Version header)
    Pricing: Free search, $3 + 1% per confirmed booking

Usage:
    from duffel_client import DuffelClient, search_with_duffel

    result = search_with_duffel("JFK", "LAX", "2026-04-15")
    if result["success"]:
        for flight in result["flights"]:
            print(flight["airline"], flight["price"], flight["currency"])
"""

import os
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger(__name__)

DUFFEL_BASE_URL = "https://api.duffel.com"

CABIN_MAP = {
    "economy": "economy",
    "premium_economy": "premium_economy",
    "premium economy": "premium_economy",
    "business": "business",
    "first": "first",
}


class DuffelClient:
    """
    Duffel NDC Flight API client.

    Simple Bearer token auth — no session management, no token refresh.
    Token is static until manually rotated in the Duffel dashboard.
    """

    def __init__(self, access_token: Optional[str] = None):
        import requests
        self._token = access_token or os.environ.get("DUFFEL_ACCESS_TOKEN", "")
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {self._token}",
            "Duffel-Version": "v2",
            "Accept": "application/json",
            "Content-Type": "application/json",
        })

    def is_configured(self) -> bool:
        """Check if Duffel token is set."""
        return bool(self._token) and len(self._token) >= 20

    def _url(self, path: str) -> str:
        return f"{DUFFEL_BASE_URL}{path}"

    def _request(self, method: str, path: str, json_data: dict = None,
                 params: dict = None, timeout: int = 60) -> dict:
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
                logger.error("Duffel API error %d: %s", resp.status_code, error_msg)
                return {"success": False, "error": error_msg, "status": resp.status_code}
            return {"success": True, "data": resp.json().get("data", resp.json())}
        except Exception as e:
            logger.error("Duffel request failed: %s", str(e))
            return {"success": False, "error": str(e)}

    # =========================================================================
    # FLIGHT SEARCH
    # =========================================================================

    def search_flights(
        self,
        origin: str,
        destination: str,
        departure_date: str,
        return_date: Optional[str] = None,
        passengers: int = 1,
        cabin_class: str = "economy",
        max_connections: Optional[int] = None,
    ) -> dict:
        """
        Search for flights via Duffel NDC API.

        Args:
            origin: IATA airport code (e.g. "JFK")
            destination: IATA airport code (e.g. "LAX")
            departure_date: "YYYY-MM-DD"
            return_date: "YYYY-MM-DD" (optional, for round-trip)
            passengers: Number of adult passengers
            cabin_class: economy, premium_economy, business, first
            max_connections: Max number of stops (0=direct only)

        Returns:
            dict with success, flights list, offer_request_id
        """
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

        pax = [{"type": "adult"} for _ in range(passengers)]
        cabin = CABIN_MAP.get(cabin_class.lower(), "economy")

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

        flights = []
        for offer in offers:
            flight = self._parse_offer(offer)
            if flight:
                flights.append(flight)

        flights.sort(key=lambda f: float(f.get("price", 9999)))

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
            if outbound is None:
                return None
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
                segment_details.append({
                    "flight_number": (
                        seg.get("marketing_carrier", {}).get("iata_code", "") +
                        seg.get("marketing_carrier_flight_number", "")
                    ),
                    "aircraft": seg.get("aircraft", {}).get("name", ""),
                    "origin": seg.get("origin", {}).get("iata_code", ""),
                    "destination": seg.get("destination", {}).get("iata_code", ""),
                    "departing_at": seg.get("departing_at", ""),
                    "arriving_at": seg.get("arriving_at", ""),
                    "operating_carrier": seg.get("operating_carrier", {}).get("name", ""),
                    "cabin_class": seg.get("passengers", [{}])[0].get(
                        "cabin_class_marketing_name", ""
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
                "currency": offer.get("total_currency", "USD"),
                "cabin_class": offer.get("cabin_class", "economy"),
                "segments": segment_details,
                "baggages": bags,
                "source": "duffel_ndc",
                "owner": offer.get("owner", {}).get("name", ""),
                "expires_at": offer.get("expires_at", ""),
                # Return slice for round trips
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
        """Get current offer details (price may have changed)."""
        return self._request("GET", f"/air/offers/{offer_id}")

    def get_available_services(self, offer_id: str) -> dict:
        """
        Get available ancillary services for an offer.

        Returns bags, seats, meals, and other purchasable extras.
        Each service has an ID that can be passed to create_order().
        """
        result = self._request(
            "GET", f"/air/offers/{offer_id}/available_services"
        )
        if not result["success"]:
            return result

        services = result["data"] if isinstance(result["data"], list) else []
        parsed = {"baggage": [], "seat": [], "meal": [], "other": []}
        for svc in services:
            entry = {
                "id": svc.get("id", ""),
                "type": svc.get("type", ""),
                "total_amount": svc.get("total_amount", "0"),
                "total_currency": svc.get("total_currency", "USD"),
                "maximum_quantity": svc.get("maximum_quantity", 1),
                "passenger_ids": svc.get("passenger_ids", []),
                "segment_ids": svc.get("segment_ids", []),
                "metadata": svc.get("metadata", {}),
            }
            svc_type = svc.get("type", "other")
            if svc_type in parsed:
                parsed[svc_type].append(entry)
            else:
                parsed["other"].append(entry)

        all_services = []
        for group in parsed.values():
            all_services.extend(group)

        return {
            "success": True,
            "services": all_services,
            "by_type": parsed,
            "count": len(all_services),
        }

    # =========================================================================
    # SEAT MAPS
    # =========================================================================

    def get_seat_map(self, offer_id: str) -> dict:
        """
        Get seat map for an offer.

        Returns cabin layout with rows and seats per segment,
        normalized for the MYSTES seatmap modal renderer.
        """
        result = self._request(
            "GET", "/air/seat_maps",
            params={"offer_id": offer_id}
        )
        if not result["success"]:
            return result

        seat_maps_raw = result["data"] if isinstance(result["data"], list) else []
        if not seat_maps_raw:
            return {"success": True, "seatmap": None, "seat_maps": []}

        # Parse first seat map into the format renderSeatmap() expects
        first_map = seat_maps_raw[0]
        cabins = first_map.get("cabins", [])
        rows = []
        for cabin in cabins:
            for row_data in cabin.get("rows", []):
                sections = row_data.get("sections", [])
                seats = []
                for section in sections:
                    for element in section.get("elements", []):
                        if element.get("type") == "seat":
                            seat_svc = element.get("available_services", [])
                            price = 0
                            service_id = ""
                            if seat_svc:
                                price = float(seat_svc[0].get("total_amount", 0))
                                service_id = seat_svc[0].get("id", "")
                            seats.append({
                                "column": element.get("designator", "")[-1:] if element.get("designator") else "",
                                "seat_id": element.get("designator", ""),
                                "available": len(seat_svc) > 0,
                                "status": "available" if seat_svc else "occupied",
                                "price": price,
                                "service_id": service_id,
                                "characteristics": element.get("disclosures", []),
                            })
                rows.append({
                    "row_number": str(row_data.get("sections", [{}])[0].get("elements", [{}])[0].get("designator", "")[:-1]) if sections else "",
                    "seats": seats,
                })

        # Build full seat_maps list for multi-segment flights
        parsed_maps = []
        for sm in seat_maps_raw:
            parsed_maps.append({
                "segment_id": sm.get("segment_id", ""),
                "slice_id": sm.get("slice_id", ""),
                "cabins": len(sm.get("cabins", [])),
                "raw_cabins": sm.get("cabins", []),
            })

        return {
            "success": True,
            "seatmap": {"rows": rows},
            "seat_maps": parsed_maps,
        }

    # =========================================================================
    # BOOKING (Order Creation)
    # =========================================================================

    def create_order(
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
                - id: passenger ID from offer request
                - given_name, family_name, born_on, gender, title
                - email, phone_number
            payment_type: "balance" (Duffel balance) or "arc_bsp_cash" (IATA agent)
            payment_amount: Total amount (must match offer total + services)
            payment_currency: Currency code (must match offer currency)
            services: List of service selections [{id, quantity}] from get_available_services
            metadata: Custom metadata dict stored with order

        Returns:
            dict with booking_reference, order_id, documents, services
        """
        # Get fresh offer to confirm current price
        offer_result = self.get_offer(offer_id)
        if not offer_result["success"]:
            return offer_result

        offer_data = offer_result["data"]
        amount = payment_amount or offer_data.get("total_amount", "")
        currency = payment_currency or offer_data.get("total_currency", "USD")

        # Add service costs to total
        if services:
            svc_total = sum(
                float(s.get("total_amount", s.get("amount", 0)))
                for s in services if s.get("total_amount") or s.get("amount")
            )
            if svc_total > 0:
                amount = str(round(float(amount) + svc_total, 2))

        body: Dict = {
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
            "services": order.get("services", []),
            "documents": order.get("documents", []),
            "conditions": order.get("conditions", {}),
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
            "services": order.get("services", []),
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
    # CANCELLATION (Two-Step: Quote → Confirm)
    # =========================================================================

    def get_cancellation_quote(self, order_id: str) -> dict:
        """
        Request cancellation quote — shows refund amount BEFORE confirming.

        Returns cancellation_id, refund_amount, refund_currency.
        Call confirm_cancellation() with the cancellation_id to execute.
        """
        body = {"data": {"order_id": order_id}}
        result = self._request(
            "POST", "/air/order_cancellations", json_data=body
        )
        if not result["success"]:
            return result

        cancellation = result["data"]
        return {
            "success": True,
            "cancellation_id": cancellation.get("id", ""),
            "refund_amount": cancellation.get("refund_amount", "0"),
            "refund_currency": cancellation.get("refund_currency", "USD"),
            "expires_at": cancellation.get("expires_at", ""),
            "status": cancellation.get("status", ""),
            "order_id": cancellation.get("order_id", order_id),
        }

    def confirm_cancellation(self, cancellation_id: str) -> dict:
        """Confirm a cancellation that was previously quoted."""
        result = self._request(
            "POST",
            f"/air/order_cancellations/{cancellation_id}/actions/confirm",
        )
        if not result["success"]:
            return result
        data = result.get("data", {})
        return {
            "success": True,
            "cancellation_id": cancellation_id,
            "status": "confirmed",
            "refund_amount": data.get("refund_amount", "0"),
            "refund_currency": data.get("refund_currency", "USD"),
        }

    def cancel_order(self, order_id: str) -> dict:
        """
        Cancel an order (quote + auto-confirm in one call).

        For consumer-facing UI, use get_cancellation_quote() + confirm_cancellation()
        separately to show refund amount before confirming.
        """
        quote = self.get_cancellation_quote(order_id)
        if not quote["success"]:
            return quote

        confirm = self.confirm_cancellation(quote["cancellation_id"])
        if not confirm["success"]:
            return {
                "success": False,
                "error": confirm.get("error", "Cancellation confirmation failed"),
                "cancellation_id": quote["cancellation_id"],
                "refund_amount": quote["refund_amount"],
                "refund_currency": quote["refund_currency"],
            }

        return {
            "success": True,
            "cancellation_id": quote["cancellation_id"],
            "status": "confirmed",
            "refund_amount": quote["refund_amount"],
            "refund_currency": quote["refund_currency"],
        }

    def get_cancellation(self, cancellation_id: str) -> dict:
        """Get cancellation details by ID."""
        return self._request(
            "GET", f"/air/order_cancellations/{cancellation_id}"
        )

    # =========================================================================
    # ORDER CHANGES (Date/Route Modification)
    # =========================================================================

    def request_order_change(
        self,
        order_id: str,
        slices_to_remove: List[str],
        slices_to_add: List[dict],
    ) -> dict:
        """
        Request an order change (date/route change).

        Args:
            order_id: Order to change
            slices_to_remove: List of slice IDs to remove from the order
            slices_to_add: New slice definitions [{origin, destination, departure_date, cabin_class}]

        Returns:
            Change request with ID for retrieving change offers
        """
        body = {
            "data": {
                "order_id": order_id,
                "slices": {
                    "remove": [{"slice_id": sid} for sid in slices_to_remove],
                    "add": [
                        {
                            "origin": s["origin"],
                            "destination": s["destination"],
                            "departure_date": s["departure_date"],
                            "cabin_class": s.get("cabin_class", "economy"),
                        }
                        for s in slices_to_add
                    ],
                },
            }
        }
        result = self._request(
            "POST", "/air/order_change_requests", json_data=body
        )
        if not result["success"]:
            return result
        data = result["data"]
        return {
            "success": True,
            "change_request_id": data.get("id", ""),
            "order_id": data.get("order_id", order_id),
            "status": data.get("status", ""),
            "change_offers": data.get("order_change_offers", []),
        }

    def get_order_change_offers(self, change_request_id: str) -> dict:
        """Get available change offers for a change request."""
        result = self._request(
            "GET",
            f"/air/order_change_requests/{change_request_id}",
        )
        if not result["success"]:
            return result
        data = result["data"]
        offers = data.get("order_change_offers", [])
        parsed = []
        for o in offers:
            parsed.append({
                "change_offer_id": o.get("id", ""),
                "change_total_amount": o.get("change_total_amount", "0"),
                "change_total_currency": o.get("change_total_currency", "USD"),
                "penalty_total_amount": o.get("penalty_total_amount", "0"),
                "new_total_amount": o.get("new_total_amount", "0"),
                "refund_to": o.get("refund_to", ""),
                "slices": o.get("slices", []),
                "expires_at": o.get("expires_at", ""),
            })
        return {
            "success": True,
            "change_offers": parsed,
            "count": len(parsed),
            "status": data.get("status", ""),
        }

    def confirm_order_change(
        self,
        change_offer_id: str,
        payment: Optional[dict] = None,
    ) -> dict:
        """
        Confirm an order change with the selected change offer.

        Args:
            change_offer_id: The change offer to accept
            payment: Payment for fare difference {type, amount, currency} (if extra cost)
        """
        body: Dict = {
            "data": {
                "selected_order_change_offer": change_offer_id,
            }
        }
        if payment:
            body["data"]["payment"] = payment

        result = self._request("POST", "/air/order_changes", json_data=body)
        if not result["success"]:
            return result
        data = result["data"]
        return {
            "success": True,
            "order_change_id": data.get("id", ""),
            "order_id": data.get("order_id", ""),
            "status": data.get("status", ""),
            "new_slices": data.get("slices", {}).get("add", []),
        }

    # =========================================================================
    # POST-BOOKING SERVICES
    # =========================================================================

    def add_services_to_order(self, order_id: str, services: List[dict]) -> dict:
        """
        Add ancillary services to an existing order (post-booking).

        Args:
            order_id: The order to add services to
            services: List of service selections [{id, quantity}]

        Note: Duffel uses payment for post-booking service additions.
        """
        # Get order to calculate payment
        order_result = self.get_order(order_id)
        if not order_result["success"]:
            return order_result

        svc_total = sum(
            float(s.get("total_amount", s.get("amount", 0)))
            for s in services if s.get("total_amount") or s.get("amount")
        )

        body = {
            "data": {
                "payment": {
                    "type": "balance",
                    "amount": str(round(svc_total, 2)),
                    "currency": order_result.get("total_currency", "USD"),
                },
                "services": [
                    {"id": s["id"], "quantity": s.get("quantity", 1)}
                    for s in services
                ],
            }
        }

        return self._request(
            "POST", f"/air/orders/{order_id}/services", json_data=body
        )

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

    def delete_webhook(self, webhook_id: str) -> dict:
        """Delete a webhook."""
        return self._request("DELETE", f"/air/webhooks/{webhook_id}")

    # =========================================================================
    # REFERENCE DATA
    # =========================================================================

    def list_airlines(self, limit: int = 50) -> dict:
        """List airlines available through Duffel."""
        return self._request("GET", "/air/airlines", params={"limit": limit})

    def get_airline(self, airline_id: str) -> dict:
        """Get airline details by ID."""
        return self._request("GET", f"/air/airlines/{airline_id}")

    def list_airports(self, limit: int = 50) -> dict:
        """List airports."""
        return self._request("GET", "/air/airports", params={"limit": limit})

    def get_airport(self, airport_id: str) -> dict:
        """Get airport details by ID."""
        return self._request("GET", f"/air/airports/{airport_id}")

    def suggest_places(self, query: str) -> dict:
        """Autocomplete places (airports, cities)."""
        return self._request(
            "GET", "/places/suggestions",
            params={"query": query}
        )

    # =========================================================================
    # ACCOUNT
    # =========================================================================

    def get_balance(self) -> dict:
        """Check Duffel account balance."""
        return self._request("GET", "/payments/balance")


# =============================================================================
# CONVENIENCE FUNCTION (matches picasso_client.search_with_picasso pattern)
# =============================================================================

def search_with_duffel(
    origin: str,
    destination: str,
    departure_date: str,
    return_date: Optional[str] = None,
    passengers: int = 1,
    cabin_class: str = "economy",
    max_connections: Optional[int] = None,
) -> dict:
    """
    Search flights via Duffel NDC API.

    Convenience wrapper matching the picasso_client.search_with_picasso interface.
    Returns normalized flight data.
    """
    client = DuffelClient()
    if not client.is_configured():
        return {
            "success": False,
            "error": "Duffel not configured — set DUFFEL_ACCESS_TOKEN in .env",
            "flights": [],
        }
    return client.search_flights(
        origin=origin,
        destination=destination,
        departure_date=departure_date,
        return_date=return_date,
        passengers=passengers,
        cabin_class=cabin_class,
        max_connections=max_connections,
    )
