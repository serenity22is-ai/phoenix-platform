"""
BookingDispatcher — Card-guided booking execution engine.

Replaces the hardcoded if/else chain in server.py with card-driven dispatch.
Reads knowledge cards (JSON) to determine how to route each booking.
Zero Anthropic API cost — pure Python logic.

Architecture:
    MYSTES passes: raw_offer + passenger_data + client instances
    Dispatcher reads: knowledge card for that source
    Transformer converts: MYSTES form → provider passenger format
    Handler calls: the correct client method with the right arguments
    Returns: standardized {success, confirmation_code, booking_source} result

The dispatcher does NOT import API clients directly. MYSTES injects them.
This keeps ANASTASiA independent of MYSTES's import paths.
"""

import json
import os
import logging
from typing import Dict, Optional

from .transformer import PassengerTransformer

logger = logging.getLogger(__name__)


class BookingDispatcher:
    """
    Card-guided booking dispatch. Routes bookings to the correct API client
    using knowledge cards for passenger transformation and booking flow.

    Usage:
        dispatcher = BookingDispatcher()
        result = dispatcher.dispatch(
            raw_offer={"source": "duffel_ndc", "offer_id": "off_xxx"},
            passenger_data={"first_name": "John", ...},
            clients={"duffel_ndc": duffel_client},
        )
    """

    def __init__(self, cards_dir: Optional[str] = None):
        self.cards: Dict[str, dict] = {}
        self.transformer = PassengerTransformer()
        self._load_cards(cards_dir)

    # Source aliases: search.py uses short names, cards use module_id
    _SOURCE_ALIASES = {
        "picasso": "picasso_redbox",
        "liteapi": "liteapi_hotels",
        "discover_cars": "discover_cars",
        "viator": "viator_activities",
        "safetywing": "safetywing_insurance",
        "duffel_stays": "duffel_stays",
    }

    def _load_cards(self, cards_dir: Optional[str] = None):
        """Load all knowledge cards from JSON files."""
        if cards_dir is None:
            cards_dir = os.path.join(
                os.path.dirname(__file__), "..", "modules", "cards"
            )
        cards_dir = os.path.abspath(cards_dir)

        if not os.path.isdir(cards_dir):
            logger.warning(f"Knowledge cards directory not found: {cards_dir}")
            return

        for fname in os.listdir(cards_dir):
            if not fname.endswith(".json"):
                continue
            path = os.path.join(cards_dir, fname)
            try:
                with open(path) as f:
                    card = json.load(f)
                module_id = card.get("module_id", fname.replace(".json", ""))
                self.cards[module_id] = card
                logger.debug(f"Loaded knowledge card: {module_id}")
            except Exception as e:
                logger.warning(f"Failed to load card {fname}: {e}")

        # Register aliases so search.py source names resolve to cards
        for alias, module_id in self._SOURCE_ALIASES.items():
            if module_id in self.cards and alias not in self.cards:
                self.cards[alias] = self.cards[module_id]

    def get_card(self, source: str) -> Optional[dict]:
        """Get the knowledge card for a given source."""
        return self.cards.get(source)

    def available_sources(self) -> list:
        """List all sources with loaded knowledge cards."""
        return list(self.cards.keys())

    def dispatch(
        self,
        raw_offer: dict,
        passenger_data: dict,
        clients: dict,
        markup: float = 0.0,
    ) -> dict:
        """
        Execute a booking using the correct API client, guided by knowledge cards.

        Args:
            raw_offer: Dict from search results containing source + booking refs.
                Must include 'source' key matching a knowledge card module_id.
                Examples:
                    {"source": "picasso", "fare_id": "...", "fare_search_id": "..."}
                    {"source": "duffel_ndc", "offer_id": "off_xxx"}
                    {"source": "kiwi_tequila", "booking_token": "..."}
                    {"source": "airgateway_ndc", "offer_id": "..."}
            passenger_data: MYSTES standard form data:
                {first_name, last_name, date_of_birth, gender, email, phone,
                 title, passport_number, nationality,
                 additional_passengers: [{...}, ...]}
            clients: Dict mapping source names to client instances.
                MYSTES injects these — dispatcher never imports clients directly.
            markup: Platform fee amount for Picasso (passed as booking markup).

        Returns:
            Standardized result dict:
                {success: bool, confirmation_code: str, booking_source: str,
                 order_id: str (optional), pnr: str (optional), error: str (on failure)}
        """
        source = raw_offer.get("source")
        if not source:
            return {"success": False, "error": "No source in raw_offer"}

        # Look up knowledge card
        card = self.cards.get(source)
        if not card:
            return {"success": False, "error": f"No knowledge card for source: {source}"}

        # Check if this source can book
        capabilities = card.get("capabilities", {})
        if not capabilities.get("book"):
            return {"success": False, "error": f"Source {source} does not support booking"}

        # Get client
        client = clients.get(source)
        if not client:
            return {"success": False, "error": f"No client registered for source: {source}"}

        # Transform passengers using knowledge card
        passengers = self.transformer.transform_all(passenger_data, card)

        # Dispatch to source-specific handler
        handler = _HANDLERS.get(source)
        if not handler:
            return {
                "success": False,
                "error": f"No booking handler for source: {source}",
            }

        try:
            logger.info(
                f"[DISPATCH] Routing booking to {card.get('name', source)} "
                f"(source={source}, passengers={len(passengers)})"
            )
            return handler(raw_offer, passengers, client, card, markup)
        except Exception as e:
            logger.error(f"[DISPATCH] {source} booking error: {e}")
            return {
                "success": False,
                "error": str(e),
                "booking_source": source,
            }


# =============================================================================
# Source-specific booking handlers
# =============================================================================
# Each handler knows that provider's booking API signature.
# The knowledge card tells us WHAT to do; the handler tells us HOW.
# =============================================================================


def _book_picasso(raw_offer, passengers, client, card, markup):
    """
    Picasso/Redbox GDS booking.

    Flow: select_fare → add_passengers → book_superPNR → issue_ticket
    Client method: book_flight(fare_search_id, fare_id, passengers, order_tickets, markup_amount)
    """
    fare_id = raw_offer.get("fare_id")
    fare_search_id = raw_offer.get("fare_search_id")

    if not fare_id or not fare_search_id:
        return {
            "success": False,
            "error": "Missing fare_id or fare_search_id for Picasso booking",
            "booking_source": "picasso",
        }

    result = client(
        fare_search_id=fare_search_id,
        fare_id=fare_id,
        passengers=passengers,
        order_tickets=True,
        markup_amount=round(markup, 2),
    )

    if result and result.get("success"):
        return {
            "success": True,
            "confirmation_code": result.get("pnr") or result.get("locator"),
            "pnr": result.get("pnr"),
            "super_pnr_id": result.get("super_pnr_id"),
            "booking_source": "picasso",
            "booking_data": result.get("booking_data"),
        }

    return {
        "success": False,
        "error": result.get("error", "Picasso booking failed")
        if result
        else "Picasso booking returned empty result",
        "step": result.get("step") if result else None,
        "booking_source": "picasso",
    }


def _book_duffel_ndc(raw_offer, passengers, client, card, markup):
    """
    Duffel NDC booking.

    Flow: refresh_offer → create_order (with optional services)
    Client method: create_order(offer_id, passengers, payment_type, services, metadata)
    """
    offer_id = raw_offer.get("offer_id")

    if not offer_id:
        return {
            "success": False,
            "error": "Missing offer_id for Duffel booking",
            "booking_source": "duffel",
        }

    # Extract selected services from raw_offer (stored by MYSTES checkout)
    services = raw_offer.get("selected_services")
    metadata = raw_offer.get("metadata")

    # Build create_order kwargs
    kwargs = {
        "offer_id": offer_id,
        "passengers": passengers,
        "payment_type": "balance",
    }
    if services:
        kwargs["services"] = services
    if metadata:
        kwargs["metadata"] = metadata

    result = client.create_order(**kwargs)

    if result and result.get("success"):
        return {
            "success": True,
            "confirmation_code": result.get("booking_reference"),
            "order_id": result.get("order_id"),
            "booking_source": "duffel",
            "documents": result.get("documents", []),
            "services": result.get("services", []),
        }

    return {
        "success": False,
        "error": result.get("error", "Duffel booking failed")
        if result
        else "Duffel booking returned empty result",
        "booking_source": "duffel",
    }


def _book_kiwi_tequila(raw_offer, passengers, client, card, markup):
    """
    Kiwi Tequila aggregator booking.

    Flow: check_flights → save_booking → confirm_payment
    Client method: check_flights(token), save_booking(token, passengers)
    """
    booking_token = raw_offer.get("booking_token")

    if not booking_token:
        return {
            "success": False,
            "error": "Missing booking_token for Kiwi booking",
            "booking_source": "kiwi",
        }

    # Step 1: Validate flight availability
    check = client.check_flights(booking_token)
    if not check or not check.get("success"):
        return {
            "success": False,
            "error": check.get("error", "Kiwi check_flights failed")
            if check
            else "Kiwi check_flights returned empty",
            "booking_source": "kiwi",
        }

    # Step 2: Create booking
    result = client.save_booking(
        booking_token=booking_token,
        passengers=passengers,
    )

    if result and result.get("success"):
        return {
            "success": True,
            "confirmation_code": result.get("booking_id"),
            "booking_source": "kiwi",
        }

    return {
        "success": False,
        "error": result.get("error", "Kiwi booking failed")
        if result
        else "Kiwi save_booking returned empty",
        "booking_source": "kiwi",
    }


def _book_airgateway_ndc(raw_offer, passengers, client, card, markup):
    """
    AirGateway NDC booking.

    Flow: verify_price → create_order
    Client method: verify_price(offer_id), create_order(offer_id, passengers)
    """
    offer_id = raw_offer.get("offer_id")

    if not offer_id:
        return {
            "success": False,
            "error": "Missing offer_id for AirGateway booking",
            "booking_source": "airgateway",
        }

    # Step 1: Verify price (required before booking)
    verify = client.verify_price(offer_id)
    if not verify or not verify.get("success"):
        error_msg = (
            verify.get("error", "AirGateway price verification failed")
            if verify
            else "AirGateway verify_price returned empty"
        )
        return {
            "success": False,
            "error": error_msg,
            "booking_source": "airgateway",
        }

    # Step 2: Create order
    result = client.create_order(
        offer_id=offer_id,
        passengers=passengers,
    )

    if result and result.get("success"):
        return {
            "success": True,
            "confirmation_code": result.get("order_id")
            or result.get("booking_reference"),
            "booking_source": "airgateway",
        }

    return {
        "success": False,
        "error": result.get("error", "AirGateway booking failed")
        if result
        else "AirGateway create_order returned empty",
        "booking_source": "airgateway",
    }


def _book_discover_cars(raw_offer, passengers, client, card, markup):
    """
    Discover Cars aggregator booking.

    Flow: search → select offer → create_booking
    Client method: create_booking(offer_id, driver, flight_number)
    """
    offer_id = raw_offer.get("offer_id")

    if not offer_id:
        return {
            "success": False,
            "error": "Missing offer_id for Discover Cars booking",
            "booking_source": "discover_cars",
        }

    lead = passengers[0] if passengers else {}
    driver = {
        "first_name": lead.get("first_name", ""),
        "last_name": lead.get("last_name", ""),
        "email": lead.get("email", ""),
        "phone": lead.get("phone", ""),
        "country_code": lead.get("nationality", ""),
        "age": lead.get("age", 30),
    }

    result = client.create_booking(
        offer_id=offer_id,
        driver=driver,
        flight_number=raw_offer.get("flight_number"),
    )

    if result and result.get("success"):
        return {
            "success": True,
            "confirmation_code": result.get("booking_id") or result.get("confirmation_code"),
            "booking_source": "discover_cars",
        }

    return {
        "success": False,
        "error": result.get("error", "Discover Cars booking failed")
        if result
        else "Discover Cars booking returned empty result",
        "booking_source": "discover_cars",
    }


def _book_viator(raw_offer, passengers, client, card, markup):
    """
    Viator activities booking.

    Flow: search → product_details → availability_check → book
    Client method: create_booking(product_code, travel_date, currency, pax_mix, booker, ...)
    """
    product_code = raw_offer.get("product_code")
    travel_date = raw_offer.get("travel_date")

    if not product_code:
        return {
            "success": False,
            "error": "Missing product_code for Viator booking",
            "booking_source": "viator",
        }

    lead = passengers[0] if passengers else {}
    pax_mix = raw_offer.get("pax_mix", [{"ageBand": "ADULT", "numberOfTravelers": 1}])

    result = client.create_booking(
        product_code=product_code,
        travel_date=travel_date,
        currency=raw_offer.get("currency", "USD"),
        pax_mix=pax_mix,
        first_name=lead.get("first_name", ""),
        last_name=lead.get("last_name", ""),
        email=lead.get("email", ""),
        phone=lead.get("phone", ""),
    )

    if result and result.get("success"):
        return {
            "success": True,
            "confirmation_code": result.get("booking_ref") or result.get("confirmation_code"),
            "booking_source": "viator",
        }

    return {
        "success": False,
        "error": result.get("error", "Viator booking failed")
        if result
        else "Viator booking returned empty result",
        "booking_source": "viator",
    }


def _book_safetywing(raw_offer, passengers, client, card, markup):
    """
    SafetyWing insurance booking.

    Flow: get_plans → get_quote → add_member (member creation IS policy creation)
    Client method: add_member(plan_id, member, start_date)
    """
    plan_id = raw_offer.get("plan_id")

    if not plan_id:
        return {
            "success": False,
            "error": "Missing plan_id for SafetyWing booking",
            "booking_source": "safetywing",
        }

    lead = passengers[0] if passengers else {}
    member = {
        "first_name": lead.get("first_name", ""),
        "last_name": lead.get("last_name", ""),
        "email": lead.get("email", ""),
        "date_of_birth": lead.get("date_of_birth", ""),
        "nationality": lead.get("nationality", ""),
    }

    result = client.add_member(
        plan_id=plan_id,
        member=member,
        start_date=raw_offer.get("start_date"),
    )

    if result and result.get("success"):
        return {
            "success": True,
            "confirmation_code": result.get("policy_id") or result.get("member_id"),
            "booking_source": "safetywing",
        }

    return {
        "success": False,
        "error": result.get("error", "SafetyWing booking failed")
        if result
        else "SafetyWing add_member returned empty result",
        "booking_source": "safetywing",
    }


def _book_duffel_stays(raw_offer, passengers, client, card, markup):
    """
    Duffel Stays hotel booking.

    Flow: create_quote(rate_id) → book_stay(quote_id, email, phone, guests)
    Client is a DuffelStaysClient instance injected by MYSTES.
    """
    rate_id = raw_offer.get("rate_id")

    if not rate_id:
        return {
            "success": False,
            "error": "Missing rate_id for Duffel Stays booking",
            "booking_source": "duffel_stays",
        }

    # Step 1: Create quote (lock the price)
    quote_result = client.create_quote(rate_id)
    if not quote_result or not quote_result.get("success"):
        return {
            "success": False,
            "error": quote_result.get("error", "Duffel Stays quote creation failed")
            if quote_result
            else "Duffel Stays create_quote returned empty result",
            "booking_source": "duffel_stays",
        }

    quote_id = quote_result.get("quote_id")

    # Step 2: Build guest list from transformed passengers
    lead = passengers[0] if passengers else {}
    guests = [
        {
            "given_name": p.get("given_name", p.get("first_name", "")),
            "family_name": p.get("family_name", p.get("last_name", "")),
        }
        for p in passengers
    ]

    # Step 3: Book the stay
    result = client.book_stay(
        quote_id=quote_id,
        email=lead.get("email", ""),
        phone_number=lead.get("phone", lead.get("phone_number", "")),
        guests=guests,
        loyalty_programme_account_number=raw_offer.get("loyalty_programme_account_number"),
        accommodation_special_requests=raw_offer.get("accommodation_special_requests"),
    )

    if result and result.get("success"):
        return {
            "success": True,
            "confirmation_code": result.get("confirmation_number")
            or result.get("booking_id"),
            "booking_id": result.get("booking_id"),
            "booking_source": "duffel_stays",
        }

    return {
        "success": False,
        "error": result.get("error", "Duffel Stays booking failed")
        if result
        else "Duffel Stays book_stay returned empty result",
        "booking_source": "duffel_stays",
    }


# Handler registry — maps source module_id to booking function
_HANDLERS = {
    "picasso": _book_picasso,
    "duffel_ndc": _book_duffel_ndc,
    "kiwi_tequila": _book_kiwi_tequila,
    "airgateway_ndc": _book_airgateway_ndc,
    "discover_cars": _book_discover_cars,
    "viator": _book_viator,
    "safetywing": _book_safetywing,
    "duffel_stays": _book_duffel_stays,
}
