"""
Activities Vertical Modules — Knowledge card management.

Manages API modules for the activities/tours/experiences vertical.
Currently supports Viator (300,000+ products, 200 countries).

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

logger = logging.getLogger("anastasia.modules.activity_modules")


# =========================================================================
# Python builder (fallback)
# =========================================================================

def build_viator_card() -> KnowledgeCard:
    """Viator — Activities aggregator powered by TripAdvisor."""
    return KnowledgeCard(
        module_id="viator_activities",
        name="Viator Activities",
        vendor="Viator (TripAdvisor)",
        version="2.0",
        vertical=VerticalType.ACTIVITIES.value,
        source_type=SourceType.AGGREGATOR.value,
        auth_type=AuthType.API_KEY_HEADER.value,
        credential_env_vars=["VIATOR_API_KEY"],
        auth_notes="Static API key in exp-api-key header. Sandbox at api.sandbox.viator.com.",
        capabilities={
            "search": True, "book": True, "cancel": True, "change": True,
            "hold": True, "cart": True, "reviews": True,
        },
        carrier_count=300000,
        coverage_notes="300,000+ tours, activities, and experiences across 200+ countries.",
        geographic_focus="global",
        date_format="YYYY-MM-DD",
        currency_param="currency",
        passenger_format={
            "name_fields": ["firstName", "lastName"],
            "age_bands": ["ADULT", "CHILD", "INFANT", "YOUTH", "SENIOR", "TRAVELER"],
            "requires_phone": True,
            "phone_must_start_with_plus": True,
        },
        pricing_model="commission",
        pricing_notes="Free to search. 8% commission on bookings. Viator is merchant of record.",
        priority=90,
        strengths=["300k_products", "200_countries", "tripadvisor_reviews",
                    "instant_confirmation", "free_cancellation", "sandbox_available"],
        weaknesses=["destination_id_required", "complex_booking_questions"],
        best_for=["activities_search", "tour_booking", "destination_experiences", "skip_the_line"],
        quirks=[
            {"issue": "Phone must start with + for booking", "workaround": "Prepend country code if missing"},
            {"issue": "Availability check required before booking", "workaround": "Always call /availability/check first"},
            {"issue": "partnerBookingRef must be unique", "workaround": "Generate MYSTES-{uuid} format"},
        ],
        booking_steps=["search", "product_details", "availability_check", "hold_optional", "book"],
        booking_notes="Returns BR-XXXXXXXXX booking reference. 8% commission.",
        readiness="tested",
        confidence=0.85,
        learned_from=["mystes_internal", "viator_openapi_spec"],
    )


# =========================================================================
# Registry builder
# =========================================================================

def build_all_activity_modules(from_json: bool = True) -> List[APIModule]:
    """Build APIModule instances for all known activity sources."""
    if from_json and CARDS_DIR.exists():
        cards = load_all_json_cards(vertical=VerticalType.ACTIVITIES.value)
        if cards:
            return [APIModule(knowledge_card=card) for card in cards]

    return [APIModule(knowledge_card=build_viator_card())]
