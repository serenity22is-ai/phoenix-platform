"""
Phoenix Trip Bundle — Multi-Vertical Package Booking

Combines flights + hotels + transfers into a single trip package
with a reduced platform fee. Each vertical is searched and booked
through Amadeus Self-Service APIs.

Consumer sees: "Book your complete trip and save on Phoenix fees."

Booking flow:
    1. search_bundle()  — Search all three verticals at once
    2. create_bundle()  — Lock selected offers into a bundle (draft)
    3. book_bundle()    — Execute all Amadeus bookings, link to bundle

Usage:
    from trip_bundle import bundle_manager

    # Search
    results = bundle_manager.search_bundle(
        origin="JFK", destination="CDG",
        departure_date="2026-06-15", return_date="2026-06-22",
        adults=2, city_code="PAR",
    )

    # Create bundle from selections
    bundle = bundle_manager.create_bundle(
        user_id=42,
        flight_offer=results["flights"]["flights"][0]["raw_offer"],
        hotel_offer_id="OFFER123",
        transfer_offer_id="TRANSFER456",
    )

    # Book everything
    result = bundle_manager.book_bundle(
        bundle_id=bundle["bundle_id"],
        traveler={...},
        payment={...},
    )
"""

import json
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Dict, List, Optional

from amadeus_client import AmadeusClient
from amadeus_hotel_client import AmadeusHotelClient
from amadeus_transfer_client import AmadeusTransferClient
from vertical_pipelines import calculate_bundle_fee, CONSOLIDATOR_FEE_PER_TICKET

logger = logging.getLogger(__name__)


class TripBundleManager:
    """
    Orchestrates multi-vertical trip searches and bookings.

    Three Amadeus APIs, one Phoenix transaction.
    """

    def __init__(self):
        self._flight_client = AmadeusClient()
        self._hotel_client = AmadeusHotelClient()
        self._transfer_client = AmadeusTransferClient()

    # -----------------------------------------------------------------
    # Search — all three verticals at once
    # -----------------------------------------------------------------

    def search_bundle(
        self,
        # Flight params
        origin: str,
        destination: str,
        departure_date: str,
        return_date: Optional[str] = None,
        adults: int = 1,
        cabin_class: str = "ECONOMY",
        # Hotel params
        city_code: Optional[str] = None,
        check_in: Optional[str] = None,
        check_out: Optional[str] = None,
        rooms: int = 1,
        hotel_ratings: Optional[List[int]] = None,
        max_hotels: int = 20,
        # Transfer params
        airport_code: Optional[str] = None,
        transfer_type: str = "PRIVATE",
        # Shared
        currency: str = "USD",
    ) -> Dict:
        """
        Search flights, hotels, and transfers in parallel.

        Args:
            origin: Origin airport code (e.g., "JFK")
            destination: Destination airport code (e.g., "CDG")
            departure_date: YYYY-MM-DD
            return_date: YYYY-MM-DD (optional, for round-trip)
            adults: Number of travelers
            cabin_class: ECONOMY, BUSINESS, FIRST
            city_code: IATA city code for hotels (e.g., "PAR"). Defaults to destination.
            check_in: Hotel check-in date. Defaults to departure_date.
            check_out: Hotel check-out date. Defaults to return_date or departure+1.
            rooms: Number of hotel rooms
            hotel_ratings: Star rating filter (e.g., [3, 4, 5])
            max_hotels: Max hotels to price
            airport_code: Airport for transfer pickup. Defaults to destination.
            transfer_type: PRIVATE, SHARED, TAXI, etc.
            currency: Price currency

        Returns:
            Dict with flights, hotels, transfers results + bundle fee preview.
        """
        # Default city_code to destination
        if not city_code:
            city_code = destination

        # Default hotel dates to flight dates
        if not check_in:
            check_in = departure_date
        if not check_out:
            check_out = return_date

        # Default airport for transfer
        if not airport_code:
            airport_code = destination

        # Transfer datetime: arrival day at 14:00
        transfer_datetime = f"{departure_date}T14:00:00"

        results = {
            "flights": None,
            "hotels": None,
            "transfers": None,
        }

        # Run searches in parallel
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = {}

            # Flight search
            futures[executor.submit(
                self._flight_client.search_flights,
                origin=origin,
                destination=destination,
                departure_date=departure_date,
                return_date=return_date,
                adults=adults,
                cabin_class=cabin_class,
            )] = "flights"

            # Hotel search
            futures[executor.submit(
                self._hotel_client.search_hotels,
                city_code=city_code,
                check_in=check_in,
                check_out=check_out,
                adults=adults,
                rooms=rooms,
                currency=currency,
                ratings=hotel_ratings,
                max_hotels=max_hotels,
            )] = "hotels"

            # Transfer search
            futures[executor.submit(
                self._transfer_client.search_transfers,
                start_location_code=airport_code,
                end_location_code=None,
                end_address=None,
                end_city=city_code,
                start_datetime=transfer_datetime,
                passengers=adults,
                transfer_type=transfer_type,
                currency=currency,
            )] = "transfers"

            for future in as_completed(futures):
                key = futures[future]
                try:
                    results[key] = future.result()
                except Exception as e:
                    logger.error("Bundle search %s failed: %s", key, e)
                    results[key] = {"success": False, "error": str(e)}

        # Count successful verticals
        available = []
        if results["flights"] and results["flights"].get("success"):
            available.append("flights")
        if results["hotels"] and results["hotels"].get("success"):
            available.append("hotels")
        if results["transfers"] and results["transfers"].get("success"):
            available.append("transfers")

        # Preview bundle fee if we have at least 2 verticals
        fee_preview = None
        consolidator_total = 0.0
        if len(available) >= 2:
            # Use cheapest from each vertical as preview
            preview_amounts = []
            preview_savings = []
            for vertical in ["flights", "hotels", "transfers"]:
                r = results.get(vertical)
                if r and r.get("success"):
                    if vertical == "flights":
                        flights = r.get("flights", [])
                        cheapest = min((f["price"] for f in flights), default=0)
                        # Bake in consolidator cost — this is COGS, user sees total
                        ticket_count = adults if adults else 1
                        consolidator_total = CONSOLIDATOR_FEE_PER_TICKET * ticket_count
                        cheapest += consolidator_total
                        preview_amounts.append(cheapest)
                    elif vertical == "hotels":
                        hotels = r.get("hotels", [])
                        cheapest = min((h["price_total"] for h in hotels), default=0)
                        preview_amounts.append(cheapest)
                    elif vertical == "transfers":
                        transfers = r.get("transfers", [])
                        cheapest = min((t["price"] for t in transfers), default=0)
                        preview_amounts.append(cheapest)
                    preview_savings.append(0)  # No savings estimate at search time
                else:
                    preview_amounts.append(0)
                    preview_savings.append(0)

            fee_preview = calculate_bundle_fee(
                component_amounts=preview_amounts,
                component_savings=preview_savings,
                consolidator_cost=consolidator_total,
            )

        return {
            "success": len(available) >= 1,
            "flights": results["flights"],
            "hotels": results["hotels"],
            "transfers": results["transfers"],
            "available_verticals": available,
            "bundle_eligible": len(available) >= 2,
            "fee_preview": fee_preview,
            "search_params": {
                "origin": origin,
                "destination": destination,
                "departure_date": departure_date,
                "return_date": return_date,
                "adults": adults,
                "city_code": city_code,
                "currency": currency,
            },
        }

    # -----------------------------------------------------------------
    # Create — lock selections into a bundle
    # -----------------------------------------------------------------

    def create_bundle(
        self,
        user_id: Optional[int],
        flight_offer: Optional[Dict] = None,
        hotel_offer_id: Optional[str] = None,
        transfer_offer_id: Optional[str] = None,
        flight_price_usd: float = 0,
        hotel_price_usd: float = 0,
        transfer_price_usd: float = 0,
        flight_savings_usd: float = 0,
        hotel_savings_usd: float = 0,
        transfer_savings_usd: float = 0,
        origin: str = "",
        destination: str = "",
        departure_date: Optional[str] = None,
        return_date: Optional[str] = None,
        adults: int = 1,
        currency: str = "USD",
        completed_transactions: int = 0,
    ) -> Dict:
        """
        Create a trip bundle from selected offers.

        Requires at least 2 components for bundle pricing.
        Single-component bookings should use the individual booking flow.

        Args:
            user_id: Phoenix user ID
            flight_offer: Raw Amadeus flight offer dict (for booking later)
            hotel_offer_id: Amadeus hotel offer ID
            transfer_offer_id: Amadeus transfer offer ID
            flight_price_usd, hotel_price_usd, transfer_price_usd: Component prices
            flight_savings_usd, hotel_savings_usd, transfer_savings_usd: Component savings
            origin, destination: Airport codes
            departure_date, return_date: Trip dates
            adults: Number of travelers
            currency: Price currency
            completed_transactions: For tier calculation

        Returns:
            Dict with bundle_id, bundle_uuid, pricing breakdown.
        """
        try:
            from models import db, TripBundle, BundleItem
        except ImportError:
            return {"success": False, "error": "Database models not available"}

        # Count components
        components = []
        if flight_offer:
            components.append(("flight", flight_offer, flight_price_usd))
        if hotel_offer_id:
            components.append(("hotel", hotel_offer_id, hotel_price_usd))
        if transfer_offer_id:
            components.append(("transfer", transfer_offer_id, transfer_price_usd))

        if len(components) < 2:
            return {
                "success": False,
                "error": "Bundle requires at least 2 components. Use individual booking for single items.",
            }

        # Add consolidator cost to flight price (COGS baked into user-facing price)
        consolidator_total = 0.0
        if flight_offer and flight_price_usd > 0:
            ticket_count = adults if adults else 1
            consolidator_total = CONSOLIDATOR_FEE_PER_TICKET * ticket_count
            flight_price_usd += consolidator_total

        # Calculate bundle fee (flight amount now includes consolidator cost)
        amounts = [flight_price_usd, hotel_price_usd, transfer_price_usd]
        savings = [flight_savings_usd, hotel_savings_usd, transfer_savings_usd]
        fee_result = calculate_bundle_fee(
            amounts, savings, completed_transactions,
            consolidator_cost=consolidator_total,
        )

        # Create bundle record
        bundle_uuid = str(uuid.uuid4())
        dep_date = None
        ret_date = None
        if departure_date:
            try:
                dep_date = datetime.strptime(departure_date, "%Y-%m-%d").date()
            except ValueError:
                pass
        if return_date:
            try:
                ret_date = datetime.strptime(return_date, "%Y-%m-%d").date()
            except ValueError:
                pass

        bundle = TripBundle(
            bundle_uuid=bundle_uuid,
            user_id=user_id,
            total_amount_usd=fee_result["total_amount"],
            total_savings_usd=fee_result["total_savings"],
            bundle_fee_usd=fee_result["total_fee"],
            bundle_discount_pct=fee_result["discount_pct"],
            currency=currency,
            status="draft",
            origin=origin,
            destination=destination,
            departure_date=dep_date,
            return_date=ret_date,
            adults=adults,
        )
        db.session.add(bundle)
        db.session.flush()  # Get bundle.id

        # Create bundle items
        if flight_offer:
            item = BundleItem(
                bundle_id=bundle.id,
                item_type="flight",
                offer_data=json.dumps(flight_offer) if isinstance(flight_offer, dict) else flight_offer,
                offer_id=flight_offer.get("id") if isinstance(flight_offer, dict) else None,
                price_usd=flight_price_usd,
                currency=currency,
                price_local=flight_price_usd,
            )
            db.session.add(item)

        if hotel_offer_id:
            item = BundleItem(
                bundle_id=bundle.id,
                item_type="hotel",
                offer_id=hotel_offer_id,
                price_usd=hotel_price_usd,
                currency=currency,
                price_local=hotel_price_usd,
            )
            db.session.add(item)

        if transfer_offer_id:
            item = BundleItem(
                bundle_id=bundle.id,
                item_type="transfer",
                offer_id=transfer_offer_id,
                price_usd=transfer_price_usd,
                currency=currency,
                price_local=transfer_price_usd,
            )
            db.session.add(item)

        db.session.commit()

        logger.info(
            "Bundle created: %s (%d components, $%.2f total, $%.2f fee)",
            bundle_uuid, len(components), fee_result["total_amount"], fee_result["total_fee"],
        )

        return {
            "success": True,
            "bundle_id": bundle.id,
            "bundle_uuid": bundle_uuid,
            "num_components": len(components),
            "pricing": fee_result,
            "bundle": bundle.to_dict(),
        }

    # -----------------------------------------------------------------
    # Book — execute all Amadeus bookings
    # -----------------------------------------------------------------

    def book_bundle(
        self,
        bundle_id: int,
        traveler: Dict,
        payment: Optional[Dict] = None,
    ) -> Dict:
        """
        Execute bookings for all components in a bundle.

        Calls Amadeus APIs sequentially (flight → hotel → transfer).
        If a component fails, the bundle is marked as 'partial' and
        successful bookings are preserved. User decides on cancellation.

        Args:
            bundle_id: TripBundle record ID
            traveler: Dict with passenger/guest info:
                - first_name, last_name (required)
                - email, phone (required)
                - date_of_birth (YYYY-MM-DD, for flights)
                - gender (MALE/FEMALE, for flights)
                - title (MR/MS/MRS, for hotels)
                - passport_number, passport_expiry, passport_country (optional)
                - country_code (2-letter, for transfers)
            payment: Dict with card info (for hotel booking):
                - vendor_code (VI, MC, AX)
                - card_number
                - expiry_date (YYYY-MM)

        Returns:
            Dict with bundle status and individual booking results.
        """
        try:
            from models import db, TripBundle, BundleItem, Booking
        except ImportError:
            return {"success": False, "error": "Database models not available"}

        bundle = TripBundle.query.get(bundle_id)
        if not bundle:
            return {"success": False, "error": f"Bundle {bundle_id} not found"}

        if bundle.status not in ("draft", "payment_pending"):
            return {"success": False, "error": f"Bundle status is '{bundle.status}', cannot book"}

        bundle.status = "booking"
        db.session.commit()

        items = BundleItem.query.filter_by(bundle_id=bundle.id).all()
        results = {}
        all_success = True

        for item in items:
            item.status = "booking"
            db.session.commit()

            try:
                if item.item_type == "flight":
                    result = self._book_flight(item, traveler)
                elif item.item_type == "hotel":
                    result = self._book_hotel(item, traveler, payment)
                elif item.item_type == "transfer":
                    result = self._book_transfer(item, traveler)
                else:
                    result = {"success": False, "error": f"Unknown item type: {item.item_type}"}

                if result.get("success"):
                    item.status = "booked"
                    item.amadeus_order_id = result.get("order_id") or result.get("booking_id")
                    item.confirmation_code = result.get("confirmation") or result.get("pnr") or result.get("provider_confirmation")
                    item.booked_at = datetime.utcnow()

                    # Create Booking record
                    booking = Booking(
                        user_id=bundle.user_id,
                        passenger_name=f"{traveler.get('first_name', '')} {traveler.get('last_name', '')}",
                        passenger_email=traveler.get("email", ""),
                        confirmation_code=item.confirmation_code,
                        status="booked",
                        fulfillment_type="automated",
                        fulfillment_notes=f"Bundle {bundle.bundle_uuid} — {item.item_type}",
                    )
                    db.session.add(booking)
                    db.session.flush()
                    item.booking_id = booking.id
                else:
                    item.status = "failed"
                    all_success = False

                results[item.item_type] = result

            except Exception as e:
                logger.error("Bundle booking failed for %s: %s", item.item_type, e)
                item.status = "failed"
                results[item.item_type] = {"success": False, "error": str(e)}
                all_success = False

            db.session.commit()

        # Update bundle status
        booked_count = sum(1 for i in items if i.status == "booked")
        if all_success:
            bundle.status = "booked"
            bundle.booked_at = datetime.utcnow()
        elif booked_count > 0:
            bundle.status = "partial"
        else:
            bundle.status = "failed"

        db.session.commit()

        logger.info(
            "Bundle %s booking complete: %s (%d/%d booked)",
            bundle.bundle_uuid, bundle.status, booked_count, len(items),
        )

        return {
            "success": all_success,
            "bundle_uuid": bundle.bundle_uuid,
            "bundle_status": bundle.status,
            "booked_count": booked_count,
            "total_count": len(items),
            "results": results,
            "bundle": bundle.to_dict(),
        }

    # -----------------------------------------------------------------
    # Individual booking helpers
    # -----------------------------------------------------------------

    def _book_flight(self, item: "BundleItem", traveler: Dict) -> Dict:
        """Book a flight component via Amadeus Flight Orders."""
        offer = json.loads(item.offer_data) if item.offer_data else None
        if not offer:
            return {"success": False, "error": "No flight offer data"}

        result = self._flight_client.create_booking(
            offer=offer,
            traveler=traveler,
        )
        return result

    def _book_hotel(self, item: "BundleItem", traveler: Dict, payment: Optional[Dict]) -> Dict:
        """Book a hotel component via Amadeus Hotel Booking."""
        if not item.offer_id:
            return {"success": False, "error": "No hotel offer ID"}
        if not payment:
            return {"success": False, "error": "Hotel booking requires payment info"}

        guest = {
            "title": traveler.get("title", "MR"),
            "first_name": traveler.get("first_name", ""),
            "last_name": traveler.get("last_name", ""),
            "email": traveler.get("email", ""),
            "phone": traveler.get("phone", ""),
        }

        result = self._hotel_client.create_booking(
            offer_id=item.offer_id,
            guest=guest,
            payment=payment,
        )
        return result

    def _book_transfer(self, item: "BundleItem", traveler: Dict) -> Dict:
        """Book a transfer component via Amadeus Transfer Orders."""
        if not item.offer_id:
            return {"success": False, "error": "No transfer offer ID"}

        passenger = {
            "first_name": traveler.get("first_name", ""),
            "last_name": traveler.get("last_name", ""),
            "email": traveler.get("email", ""),
            "phone": traveler.get("phone", ""),
            "country_code": traveler.get("country_code", "US"),
        }

        result = self._transfer_client.create_booking(
            offer_id=item.offer_id,
            passenger=passenger,
        )
        return result

    # -----------------------------------------------------------------
    # Retrieve
    # -----------------------------------------------------------------

    def get_bundle(self, bundle_uuid: str) -> Dict:
        """Retrieve a bundle by UUID with all component details."""
        try:
            from models import TripBundle
        except ImportError:
            return {"success": False, "error": "Database models not available"}

        bundle = TripBundle.query.filter_by(bundle_uuid=bundle_uuid).first()
        if not bundle:
            return {"success": False, "error": f"Bundle {bundle_uuid} not found"}

        return {
            "success": True,
            "bundle": bundle.to_dict(),
        }

    def get_user_bundles(self, user_id: int) -> Dict:
        """Retrieve all bundles for a user."""
        try:
            from models import TripBundle
        except ImportError:
            return {"success": False, "error": "Database models not available"}

        bundles = TripBundle.query.filter_by(user_id=user_id).order_by(
            TripBundle.created_at.desc()
        ).all()

        return {
            "success": True,
            "bundles": [b.to_dict() for b in bundles],
            "count": len(bundles),
        }


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

bundle_manager = TripBundleManager()
