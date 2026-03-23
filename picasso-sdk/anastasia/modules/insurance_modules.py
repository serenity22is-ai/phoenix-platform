"""
Insurance Vertical Modules — Knowledge card management.

Manages API modules for the travel insurance vertical.
Currently supports SafetyWing (Nomad Insurance + Remote Health).

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

logger = logging.getLogger("anastasia.modules.insurance_modules")


# =========================================================================
# Python builder (fallback)
# =========================================================================

def build_safetywing_card() -> KnowledgeCard:
    """SafetyWing — Travel/health insurance for nomads and travelers."""
    return KnowledgeCard(
        module_id="safetywing_insurance",
        name="SafetyWing Insurance",
        vendor="SafetyWing",
        version="1.0",
        vertical=VerticalType.INSURANCE.value,
        source_type=SourceType.DIRECT.value,
        auth_type=AuthType.API_KEY_HEADER.value,
        credential_env_vars=["SAFETYWING_API_KEY"],
        auth_notes="X-API-KEY header. Sandbox at chick.test-bird.one.",
        capabilities={
            "search": True, "book": True, "cancel": True, "change": False,
            "quote": True, "plans": True,
        },
        carrier_count=2,
        coverage_notes="Nomad Insurance (travel medical) + Remote Health (comprehensive). Global coverage.",
        geographic_focus="global",
        date_format="YYYY-MM-DD",
        currency_param="implicit",
        passenger_format={
            "name_fields": ["firstName", "lastName"],
            "requires_email": True,
            "requires_dob": True,
            "dob_format": "YYYY-MM-DD",
            "requires_nationality": True,
        },
        pricing_model="commission",
        pricing_notes="Affiliate commission on policy purchases. Monthly or per-trip pricing.",
        priority=70,
        strengths=["nomad_focused", "global_coverage", "simple_api", "sandbox_available"],
        weaknesses=["limited_products", "no_change_support"],
        best_for=["travel_insurance", "nomad_insurance", "health_insurance_abroad", "upsell_on_bookings"],
        quirks=[
            {"issue": "Two possible quote endpoints", "workaround": "Try /api/remote-health/v1/quotes first"},
            {"issue": "Member creation = policy creation", "workaround": "add_member creates the policy directly"},
        ],
        booking_steps=["get_plans", "get_quote", "add_member"],
        booking_notes="Insurance upsell on flight/hotel bookings. Member creation IS policy creation.",
        readiness="tested",
        confidence=0.70,
        learned_from=["mystes_internal", "safetywing_docs"],
    )


# =========================================================================
# Registry builder
# =========================================================================

def build_all_insurance_modules(from_json: bool = True) -> List[APIModule]:
    """Build APIModule instances for all known insurance sources."""
    if from_json and CARDS_DIR.exists():
        cards = load_all_json_cards(vertical=VerticalType.INSURANCE.value)
        if cards:
            return [APIModule(knowledge_card=card) for card in cards]

    return [APIModule(knowledge_card=build_safetywing_card())]
