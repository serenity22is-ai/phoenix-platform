"""
Car Rental Vertical Modules — Knowledge card management.

Manages API modules for the car rental vertical.
Currently supports Discover Cars (500+ suppliers, 145 countries).

MYSTES KYRIOS LLC — Confidential.
"""

import logging
from typing import List

from .registry import (
    APIModule,
    AuthType,
    KnowledgeCard,
    SourceType,
    VerticalType,
)
from .flight_modules import CARDS_DIR, load_all_json_cards

logger = logging.getLogger("anastasia.modules.car_modules")


# =========================================================================
# Python builder (fallback)
# =========================================================================

def build_discover_cars_card() -> KnowledgeCard:
    """Discover Cars — Car rental aggregator with 500+ suppliers."""
    return KnowledgeCard(
        module_id="discover_cars",
        name="Discover Cars",
        vendor="Discover Cars",
        version="1.0",
        vertical=VerticalType.CAR_RENTAL.value,
        source_type=SourceType.AGGREGATOR.value,
        auth_type=AuthType.CUSTOM.value,
        credential_env_vars=["DISCOVER_CARS_USERNAME", "DISCOVER_CARS_PASSWORD", "DISCOVER_CARS_TOKEN"],
        auth_notes="Triple auth: username + password + token sent as query params.",
        capabilities={
            "search": True, "book": True, "cancel": True, "change": False,
            "location_search": True,
        },
        carrier_count=500,
        coverage_notes="500+ car rental suppliers across 10,000+ locations in 145+ countries.",
        geographic_focus="global",
        date_format="YYYY-MM-DD",
        currency_param="currency",
        passenger_format={
            "name_fields": ["firstName", "lastName"],
            "requires_age": True,
            "requires_email": True,
            "requires_phone": True,
            "requires_country_code": True,
        },
        pricing_model="commission",
        pricing_notes="70% commission share from offers.",
        priority=80,
        strengths=["500_suppliers", "145_countries", "10k_locations", "commission_share"],
        weaknesses=["no_change_support", "requires_location_id_lookup"],
        best_for=["car_rental_search", "airport_pickups", "global_coverage"],
        quirks=[
            {"issue": "Requires location ID, not IATA code", "workaround": "Call search_locations first to resolve"},
            {"issue": "Auth is triple param (username/password/token)", "workaround": "All three sent as query parameters"},
        ],
        booking_steps=["search_locations", "search_cars", "get_details", "create_booking"],
        booking_notes="Location must be resolved to ID before car search. Returns voucher URL on booking.",
        readiness="tested",
        confidence=0.80,
        learned_from=["mystes_internal", "discover_cars_b4b_docs"],
    )


# =========================================================================
# Registry builder
# =========================================================================

def build_all_car_modules(from_json: bool = True) -> List[APIModule]:
    """Build APIModule instances for all known car rental sources."""
    if from_json and CARDS_DIR.exists():
        cards = load_all_json_cards(vertical=VerticalType.CAR_RENTAL.value)
        if cards:
            return [APIModule(knowledge_card=card) for card in cards]

    return [APIModule(knowledge_card=build_discover_cars_card())]
