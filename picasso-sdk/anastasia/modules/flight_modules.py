"""
Flight & Hotel Vertical Modules — Knowledge card management.

Knowledge cards are stored as JSON files in the cards/ directory.
Each card is a standalone reference document that teaches ANASTASiA
(Claude Opus 4.6) everything about an API: capabilities, auth, data
formats, quirks, booking flow, and routing hints.

JSON format enables autonomous updates — the APIWatchdog and
UpdatePipeline can modify cards without touching Python code.

Python builder functions are retained as fallbacks and for testing.

MYSTES KYRIOS LLC — Confidential.
"""

import json
import logging
from pathlib import Path
from typing import List, Optional

from .registry import (
    APIModule,
    AuthType,
    KnowledgeCard,
    SourceType,
    VerticalType,
)

logger = logging.getLogger("anastasia.modules.flight_modules")

# Path to JSON knowledge cards
CARDS_DIR = Path(__file__).parent / "cards"


# =========================================================================
# JSON CARD LOADER — Primary path (machine-readable, auto-updatable)
# =========================================================================

def load_card_from_json(card_path: Path) -> KnowledgeCard:
    """Load a single knowledge card from a JSON file.

    Extra fields (changelog_url, docs_url, sandbox_probe_endpoints)
    are stored in the JSON but filtered out when constructing the
    KnowledgeCard dataclass — they're consumed by the APIWatchdog.
    """
    data = json.loads(card_path.read_text(encoding="utf-8"))
    # Filter to only KnowledgeCard fields
    valid_fields = set(KnowledgeCard.__dataclass_fields__.keys())
    card_data = {k: v for k, v in data.items() if k in valid_fields}
    return KnowledgeCard(**card_data)


def load_all_json_cards(vertical: Optional[str] = None) -> List[KnowledgeCard]:
    """Load all knowledge cards from the cards/ directory.

    Args:
        vertical: Filter by vertical type (e.g., "flights", "hotels").
                  None returns all cards.
    """
    if not CARDS_DIR.exists():
        logger.warning("Cards directory not found: %s", CARDS_DIR)
        return []

    cards = []
    for path in sorted(CARDS_DIR.glob("*.json")):
        try:
            card = load_card_from_json(path)
            if vertical is None or card.vertical == vertical:
                cards.append(card)
        except Exception as e:
            logger.error("Failed to load card %s: %s", path.name, e)

    return cards


def load_card_raw(card_path: Path) -> dict:
    """Load raw JSON data from a card file.

    Returns the full dict including watchdog metadata fields
    (changelog_url, docs_url, sandbox_probe_endpoints) that
    aren't part of the KnowledgeCard dataclass.
    """
    return json.loads(card_path.read_text(encoding="utf-8"))


def save_card_json(card: KnowledgeCard, extra: Optional[dict] = None) -> Path:
    """Save a knowledge card to JSON.

    Args:
        card: The KnowledgeCard to serialize.
        extra: Additional fields to include (e.g., changelog_url, docs_url).

    Returns:
        Path to the saved file.
    """
    CARDS_DIR.mkdir(parents=True, exist_ok=True)
    data = card.to_dict()
    # Add all KnowledgeCard fields that to_dict() might miss
    for field_name in KnowledgeCard.__dataclass_fields__:
        if field_name not in data:
            data[field_name] = getattr(card, field_name)
    if extra:
        data.update(extra)
    path = CARDS_DIR / f"{card.module_id}.json"
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Saved knowledge card: %s → %s", card.module_id, path)
    return path


def get_card_path(module_id: str) -> Path:
    """Get the filesystem path for a module's JSON card."""
    return CARDS_DIR / f"{module_id}.json"


# =========================================================================
# FLIGHT VERTICAL — Python builders (fallback + testing)
# =========================================================================

def build_picasso_card() -> KnowledgeCard:
    """Picasso/Redbox — GDS consolidator via AERTiCKET Cockpit."""
    return KnowledgeCard(
        module_id="picasso_redbox",
        name="Picasso/Redbox",
        vendor="AERTiCKET (Picasso Travel)",
        version="1.0",
        vertical=VerticalType.FLIGHTS.value,
        source_type=SourceType.GDS.value,
        auth_type=AuthType.SESSION_TOKEN.value,
        credential_env_vars=["PICASSO_SESSION_TOKEN"],
        auth_notes="Session-based auth via Cockpit SSO. TOTP + Playwright auto-login. "
                   "Token persisted to .picasso_token.json (24h TTL).",
        capabilities={
            "search": True, "book": True, "cancel": False, "change": False,
            "seat_map": True, "ancillaries": True, "fare_rules": True,
            "multi_city": True, "pos_arbitrage": True, "virtual_interlining": False,
        },
        carrier_count=500,
        coverage_notes="Airlines via Amadeus GDS. 102-country POS for geographic arbitrage.",
        geographic_focus="global",
        date_format="YYYY-MM-DD",
        currency_param="implicit",
        passenger_format={
            "name_fields": ["firstName", "lastName"],
            "gender_values": ["Male", "Female"],
            "dob_format": "YYYY-MM-DD",
            "type_codes": ["ADT", "CHD", "INF"],
        },
        pricing_model="net_fare",
        pricing_notes="Net consolidator fare + your markup. POS arbitrage creates savings.",
        priority=100,
        strengths=["pos_arbitrage", "102_country_pos", "consolidator_fares",
                    "gds_content", "fare_rules", "seat_maps"],
        weaknesses=["session_based_auth", "complex_token_management",
                     "no_direct_cancel", "no_direct_change"],
        best_for=["international_arbitrage", "consolidator_fares",
                   "multi_pos_comparison", "gds_rich_content"],
        quirks=[
            {"issue": "Session token expires every 24h", "workaround": "Auto-login via picasso_auth.py"},
            {"issue": "Passenger types are GDS codes (ADT/CHD/INF)", "workaround": "Map from common names"},
            {"issue": "Fare types: PUB/NET/NEG", "workaround": "Default to PUB for retail"},
        ],
        booking_steps=["search", "select_fare", "add_passengers", "book_superPNR", "issue_ticket"],
        booking_notes="Produces airline PNR via superPNR system.",
        readiness="production",
        confidence=0.95,
        learned_from=["mystes_internal", "reverse_engineering"],
    )


def build_duffel_card() -> KnowledgeCard:
    """Duffel — NDC direct airline connections."""
    return KnowledgeCard(
        module_id="duffel_ndc",
        name="Duffel NDC",
        vendor="Duffel",
        version="2.0",
        vertical=VerticalType.FLIGHTS.value,
        source_type=SourceType.NDC.value,
        auth_type=AuthType.BEARER_TOKEN.value,
        credential_env_vars=["DUFFEL_ACCESS_TOKEN"],
        auth_notes="Static Bearer token. No expiry, no refresh. "
                   "Test tokens: duffel_test_*, Live: duffel_live_*.",
        capabilities={
            "search": True, "book": True, "cancel": True, "change": True,
            "seat_map": True, "ancillaries": True, "fare_rules": False,
            "multi_city": True, "pos_arbitrage": False, "virtual_interlining": False,
        },
        carrier_count=300,
        coverage_notes="300+ airlines via NDC direct connections. NDC-exclusive fares.",
        geographic_focus="global",
        date_format="YYYY-MM-DD",
        currency_param="currency",
        passenger_format={
            "name_fields": ["given_name", "family_name"],
            "gender_values": ["m", "f"],
            "title_values": ["mr", "mrs", "ms", "miss", "dr"],
            "dob_format": "YYYY-MM-DD",
            "dob_field": "born_on",
            "type_codes": ["adult", "child", "infant_without_seat"],
        },
        pricing_model="commission",
        pricing_notes="Free search. $3 + 1% per confirmed booking.",
        priority=80,
        strengths=["ndc_exclusive_fares", "300_airlines", "simple_auth",
                    "full_booking_lifecycle", "ancillary_services", "seat_maps"],
        weaknesses=["no_pos_arbitrage", "single_pos", "offer_expiry_15_30min"],
        best_for=["ndc_direct_fares", "airline_ancillaries", "simple_booking",
                   "order_management", "cancellation_changes"],
        quirks=[
            {"issue": "Offers expire 15-30 min after search", "workaround": "Refresh via GET /air/offers/{id} before booking"},
            {"issue": "Gender: m/f (not Male/Female)", "workaround": "Map from common values"},
            {"issue": "Title: lowercase (mr/mrs, not MR/MRS)", "workaround": "Lowercase before sending"},
            {"issue": "Cancellation is two-step (request → confirm)", "workaround": "Show refund amount before confirming"},
        ],
        booking_steps=["search", "refresh_offer", "create_order"],
        booking_notes="Single-step booking. Returns airline PNR (booking_reference).",
        readiness="tested",
        confidence=0.90,
        learned_from=["mystes_internal", "duffel_docs"],
    )


def build_kiwi_card() -> KnowledgeCard:
    """Kiwi Tequila — Aggregator with virtual interlining."""
    return KnowledgeCard(
        module_id="kiwi_tequila",
        name="Kiwi Tequila",
        vendor="Kiwi.com",
        version="2.0",
        vertical=VerticalType.FLIGHTS.value,
        source_type=SourceType.AGGREGATOR.value,
        auth_type=AuthType.API_KEY_HEADER.value,
        credential_env_vars=["KIWI_API_KEY"],
        auth_notes="API key in 'apikey' header. Partnership-based (invitation-only).",
        capabilities={
            "search": True, "book": True, "cancel": False, "change": False,
            "seat_map": False, "ancillaries": False, "fare_rules": False,
            "multi_city": True, "pos_arbitrage": False, "virtual_interlining": True,
        },
        carrier_count=750,
        coverage_notes="750+ carriers including 150+ ground transport. Virtual interlining.",
        geographic_focus="global",
        date_format="DD/MM/YYYY",
        currency_param="curr",
        passenger_format={
            "name_fields": ["name", "surname"],
            "gender_values": None,
            "dob_format": "DD/MM/YYYY",
            "dob_field": "birthday",
            "type_codes": ["adult", "child", "infant"],
        },
        pricing_model="commission",
        pricing_notes="Free search. Commission on bookings. Kiwi is merchant of record.",
        priority=60,
        strengths=["virtual_interlining", "750_carriers", "lcc_coverage",
                    "ground_transport", "widest_carrier_coverage"],
        weaknesses=["no_pos_arbitrage", "no_seat_maps", "no_ancillaries",
                     "kiwi_booking_id_not_pnr", "invitation_only"],
        best_for=["maximum_coverage", "lcc_routes", "virtual_interlining",
                   "creative_routing", "multi_carrier_itineraries"],
        quirks=[
            {"issue": "Dates must be DD/MM/YYYY (not ISO)", "workaround": "Convert YYYY-MM-DD → DD/MM/YYYY"},
            {"issue": "booking_token expires in ~30 min", "workaround": "Validate with check_flights promptly"},
            {"issue": "Kiwi is merchant of record", "workaround": "Passengers get Kiwi booking_id, not airline PNR"},
            {"issue": "May include buses/trains in results", "workaround": "Set vehicle_type=aircraft to filter"},
        ],
        booking_steps=["search", "check_flights", "save_booking", "confirm_payment"],
        booking_notes="3-phase booking. Kiwi handles ticketing and support.",
        readiness="tested",
        confidence=0.85,
        learned_from=["mystes_internal", "kiwi_tequila_docs"],
    )


def build_mystifly_card() -> KnowledgeCard:
    """Mystifly OnePoint — Multi-GDS aggregator with 80+ POS."""
    return KnowledgeCard(
        module_id="mystifly",
        name="Mystifly OnePoint",
        vendor="Mystifly",
        version="2.0",
        vertical=VerticalType.FLIGHTS.value,
        source_type=SourceType.GDS.value,
        auth_type=AuthType.BEARER_TOKEN.value,
        credential_env_vars=["MYSTIFLY_API_KEY", "MYSTIFLY_ACCOUNT_ID"],
        auth_notes="API key + account ID. Partnership registration at developer.mystifly.com required. "
                   "All API docs gated behind partner login. REST v2 (JSON) or SOAP (XML). "
                   "Cannot build client without partnership access.",
        capabilities={
            "search": True, "book": True, "cancel": True, "change": True,
            "seat_map": False, "ancillaries": True, "fare_rules": True,
            "multi_city": True, "pos_arbitrage": True, "virtual_interlining": False,
        },
        carrier_count=700,
        coverage_notes="700+ airlines via multi-GDS (Amadeus, Sabre, Galileo, Worldspan). "
                       "80+ POS for geographic arbitrage. Enterprise B2B focus, Singapore HQ.",
        geographic_focus="global",
        date_format="YYYY-MM-DD",
        currency_param="currency",
        passenger_format={
            "name_fields": ["firstName", "lastName"],
            "gender_values": ["M", "F"],
            "dob_format": "YYYY-MM-DD",
            "type_codes": ["ADT", "CHD", "INF"],
        },
        pricing_model="net_fare",
        pricing_notes="Net fare + markup. Multi-GDS comparison across 4 GDS systems.",
        priority=90,
        strengths=["pos_arbitrage", "80_pos", "multi_gds", "700_airlines",
                    "fare_rules", "full_booking", "rest_and_soap", "enterprise_grade"],
        weaknesses=["requires_partnership", "no_seat_maps",
                     "docs_gated_behind_login", "no_public_sandbox"],
        best_for=["multi_gds_arbitrage", "comprehensive_coverage",
                   "fare_rule_access", "booking_management", "enterprise_integrations"],
        quirks=[
            {"issue": "All docs require partnership login", "workaround": "Must register at developer.mystifly.com"},
            {"issue": "Two API versions (REST v2 + SOAP)", "workaround": "Prefer REST v2 for new integrations"},
        ],
        booking_steps=["search", "price", "book", "ticket"],
        booking_notes="Full booking lifecycle with airline PNR. Multi-GDS fare comparison.",
        readiness="discovered",
        confidence=0.55,
        learned_from=["mystifly_website", "industry_research"],
    )


def build_airgateway_card() -> KnowledgeCard:
    """AirGateway — NDC aggregator + AERTiCKET consolidator with POS arbitrage."""
    return KnowledgeCard(
        module_id="airgateway_ndc",
        name="AirGateway NDC",
        vendor="AirGateway",
        version="1.2",
        vertical=VerticalType.FLIGHTS.value,
        source_type=SourceType.NDC.value,
        auth_type=AuthType.API_KEY_HEADER.value,
        credential_env_vars=["AIRGATEWAY_API_KEY"],
        auth_notes="API key in Authorization header (raw key, NOT Bearer prefix). "
                   "Sandbox key from airgateway.com dashboard. "
                   "Production key requires commercial agreement. "
                   "No token expiry — key is permanent until rotated.",
        capabilities={
            "search": True, "book": True, "cancel": True, "change": False,
            "seat_map": True, "ancillaries": True, "fare_rules": False,
            "multi_city": True, "pos_arbitrage": True, "virtual_interlining": False,
        },
        carrier_count=25,
        coverage_notes="25+ airlines via NDC-direct (A3, AA, AF, AV, AY, BA, EK, IB, KL, LH, QF, SQ) "
                       "plus AERTiCKET consolidator GDS content (Amadeus, Sabre, Travelport). "
                       "POS arbitrage via metadata.country — same 102-country network as Redbox.",
        geographic_focus="global",
        date_format="YYYY-MM-DD",
        currency_param="metadata.currency",
        passenger_format={
            "name_fields": ["nameGiven", "surname"],
            "title_field": "nameTitle",
            "title_values": ["MR", "MRS", "MS", "MISS"],
            "gender_values": ["Male", "Female"],
            "dob_format": "YYYY-MM-DD",
            "dob_field": "birthdate",
            "type_codes": ["ADT", "CHD", "INF"],
            "type_field": "passengerType",
            "reference_field": "travelerReference",
            "contact_fields": ["emailContact", "phone"],
        },
        pricing_model="commission",
        pricing_notes="Free search. Commission on bookings. "
                      "Agency settles via AirGateway account (cash/card/ms).",
        priority=85,
        strengths=["pos_arbitrage", "ndc_direct", "aertickket_partner",
                    "102_country_pos", "ancillaries", "seat_maps",
                    "json_rest_api", "swagger_docs", "sandbox_available"],
        weaknesses=["25_ndc_airlines_only", "no_fare_rules_api",
                     "no_change_support", "no_virtual_interlining"],
        best_for=["ndc_arbitrage", "ndc_direct_fares", "airline_partnerships",
                   "aa_ba_lh_af_kl_ek_fares", "aertickket_gds_via_ndc"],
        quirks=[
            {"issue": "Auth header is raw key, NOT Bearer prefix", "workaround": "Send Authorization: {key} (not Bearer {key})"},
            {"issue": "Cabin codes are numeric: 7=econ, 4=prem, 2=biz, 1=first", "workaround": "Client maps standard names to codes"},
            {"issue": "All endpoints use POST (even retrieves)", "workaround": "Always use POST method"},
            {"issue": "Gender must be 'Male'/'Female' (capitalized)", "workaround": "Map from common values"},
            {"issue": "Title must be UPPERCASE (MR/MRS/MS/MISS)", "workaround": "Uppercase before sending"},
            {"issue": "ShoppingResponseID is session-scoped and expires", "workaround": "Use promptly, search again if expired"},
            {"issue": "AG-Providers header controls which airlines respond", "workaround": "Use '*' for all, or comma-separated IATA codes"},
        ],
        booking_steps=["search", "verify_price", "create_order"],
        booking_notes="NDC booking via OrderCreate. Returns airline PNR via order. "
                      "10 NDC operations: AirShopping, OfferPrice, OrderCreate, "
                      "OrderRetrieve, OrderCancel, OrderReshopRefund, OrderReshopReprice, "
                      "SeatAvailability, ServiceList, AirDocIssue.",
        readiness="tested",
        confidence=0.90,
        learned_from=["airgateway_docs", "airgateway_swagger", "airgateway_postman", "mystes_internal"],
    )


def build_travelfusion_card() -> KnowledgeCard:
    """Travelfusion — Direct connections to 412+ airlines (LCC + legacy)."""
    return KnowledgeCard(
        module_id="travelfusion",
        name="Travelfusion",
        vendor="Travelfusion (Travelport subsidiary)",
        version="1.0",
        vertical=VerticalType.FLIGHTS.value,
        source_type=SourceType.DIRECT.value,
        auth_type=AuthType.SESSION_TOKEN.value,
        credential_env_vars=["TRAVELFUSION_USERNAME", "TRAVELFUSION_PASSWORD"],
        auth_notes="XML API. Token-based auth — login endpoint returns session token "
                   "with 12-hour expiry. Docs at xmldocs.travelfusion.com (requires "
                   "commercial agreement to access). Travelport subsidiary.",
        capabilities={
            "search": True, "book": True, "cancel": True, "change": False,
            "seat_map": False, "ancillaries": True, "fare_rules": True,
            "multi_city": False, "pos_arbitrage": False, "virtual_interlining": False,
        },
        carrier_count=412,
        coverage_notes="412+ airlines via direct screen-scraping connections. "
                       "Includes both LCC and legacy carriers. "
                       "Travelport subsidiary — enterprise distribution.",
        geographic_focus="global",
        date_format="YYYY-MM-DD",
        passenger_format={
            "name_fields": ["FirstName", "LastName"],
            "gender_values": ["M", "F"],
            "dob_format": "YYYY-MM-DD",
            "type_codes": ["ADT", "CHD", "INF"],
        },
        pricing_model="commission",
        pricing_notes="Commission per booking. Enterprise pricing — contact sales.",
        priority=55,
        strengths=["412_airlines", "direct_connections", "lcc_and_legacy",
                    "travelport_subsidiary", "ancillaries", "fare_rules"],
        weaknesses=["xml_soap_api", "requires_commercial_agreement",
                     "12h_token_expiry", "no_arbitrage", "no_public_sandbox"],
        best_for=["direct_airline_fares", "lcc_routes", "legacy_carrier_fares",
                   "carrier_ancillaries", "enterprise_integrations"],
        quirks=[
            {"issue": "XML/SOAP protocol (not JSON REST)", "workaround": "Need XML parser — xml.etree or lxml"},
            {"issue": "Token expires every 12 hours", "workaround": "Auto-refresh via login endpoint"},
            {"issue": "Docs require commercial agreement", "workaround": "Cannot build without partnership access"},
        ],
        booking_steps=["search", "get_details", "book", "confirm"],
        booking_notes="Direct carrier booking. Returns airline PNR. XML request/response format throughout.",
        readiness="discovered",
        confidence=0.45,
        learned_from=["travelfusion_website", "xmldocs_partial", "industry_research"],
    )


def build_tripstack_card() -> KnowledgeCard:
    """TripStack — Virtual interlining aggregator with VI Guarantee."""
    return KnowledgeCard(
        module_id="tripstack",
        name="TripStack",
        vendor="TripStack (Hopper subsidiary)",
        version="1.0",
        vertical=VerticalType.FLIGHTS.value,
        source_type=SourceType.AGGREGATOR.value,
        auth_type=AuthType.API_KEY_HEADER.value,
        credential_env_vars=["TRIPSTACK_API_KEY"],
        auth_notes="Partnership-based access only. Minimal public API documentation. "
                   "Contact sales for integration. Recently acquired by Hopper.",
        capabilities={
            "search": True, "book": True, "cancel": False, "change": False,
            "seat_map": False, "ancillaries": False, "fare_rules": False,
            "multi_city": True, "pos_arbitrage": False, "virtual_interlining": True,
        },
        carrier_count=250,
        coverage_notes="250+ carriers with Virtual Interlining (VI) Guarantee. "
                       "Combines LCC + legacy + NDC carriers into protected itineraries. "
                       "Montreal-based. Now part of Hopper.",
        geographic_focus="global",
        date_format="YYYY-MM-DD",
        passenger_format={},
        pricing_model="commission",
        pricing_notes="Commission per booking. TripStack is merchant of record for VI bookings.",
        priority=45,
        strengths=["virtual_interlining", "vi_guarantee", "lcc_ndc_combo",
                    "missed_connection_protection", "hopper_backing"],
        weaknesses=["minimal_public_docs", "partnership_only", "no_arbitrage",
                     "no_ancillaries", "no_seat_maps", "no_public_sandbox"],
        best_for=["creative_routing", "lcc_ndc_combinations",
                   "protected_virtual_interlining", "missed_connection_guarantee"],
        quirks=[
            {"issue": "Minimal public API docs", "workaround": "Cannot build without partnership access"},
            {"issue": "Now owned by Hopper", "workaround": "May integrate with Hopper's API in future"},
        ],
        booking_steps=["search", "validate", "book"],
        booking_notes="TripStack is merchant of record for VI bookings. "
                      "VI Guarantee protects against missed connections.",
        readiness="discovered",
        confidence=0.25,
        learned_from=["tripstack_website", "industry_research"],
    )


# =========================================================================
# HOTEL VERTICAL
# =========================================================================

def build_liteapi_card() -> KnowledgeCard:
    """liteAPI — Hotel wholesaler with 2M+ properties."""
    return KnowledgeCard(
        module_id="liteapi_hotels",
        name="liteAPI Hotels",
        vendor="liteAPI",
        version="3.0",
        vertical=VerticalType.HOTELS.value,
        source_type=SourceType.WHOLESALER.value,
        auth_type=AuthType.API_KEY_HEADER.value,
        credential_env_vars=["LITEAPI_KEY"],
        auth_notes="API key in header. Self-serve dashboard.",
        capabilities={
            "search": True, "book": True, "cancel": True,
            "change": False, "prebook_validate": True,
        },
        carrier_count=2000000,
        coverage_notes="2M+ hotel properties globally.",
        geographic_focus="global",
        date_format="YYYY-MM-DD",
        passenger_format={"name_fields": ["firstName", "lastName"]},
        pricing_model="net_fare",
        pricing_notes="Net rate with built-in commission. No per-API-call fees.",
        priority=80,
        strengths=["2m_properties", "global_coverage", "net_rates", "self_serve"],
        weaknesses=["no_change_support"],
        best_for=["hotel_search", "hotel_booking", "wholesaler_rates"],
        quirks=[
            {"issue": "Hotel names not in rate response", "workaround": "Fetch from /data/hotel endpoint"},
            {"issue": "Booking requires prebookId from prebook step", "workaround": "Always prebook before booking"},
        ],
        booking_steps=["search", "prebook", "book"],
        booking_notes="No passport needed for hotels. $15 flat fee.",
        readiness="tested",
        confidence=0.85,
        learned_from=["mystes_internal", "liteapi_docs"],
    )


# =========================================================================
# REGISTRY BUILDERS
# =========================================================================

def build_all_flight_modules(from_json: bool = True) -> list:
    """Build APIModule instances for all known flight sources.

    Args:
        from_json: If True, load from JSON cards (primary path).
                   If False, use Python builder functions (fallback).
    """
    if from_json and CARDS_DIR.exists():
        cards = load_all_json_cards(vertical="flights")
        if cards:
            return [APIModule(knowledge_card=card) for card in cards]

    # Fallback to Python builders
    cards = [
        build_picasso_card(),
        build_duffel_card(),
        build_kiwi_card(),
        build_mystifly_card(),
        build_airgateway_card(),
        build_travelfusion_card(),
        build_tripstack_card(),
    ]
    return [APIModule(knowledge_card=card) for card in cards]


def build_all_hotel_modules(from_json: bool = True) -> list:
    """Build APIModule instances for all known hotel sources."""
    if from_json and CARDS_DIR.exists():
        cards = load_all_json_cards(vertical="hotels")
        if cards:
            return [APIModule(knowledge_card=card) for card in cards]

    return [APIModule(knowledge_card=build_liteapi_card())]


def build_all_modules(from_json: bool = True) -> list:
    """Build all known modules across all verticals."""
    from .car_modules import build_all_car_modules
    from .activity_modules import build_all_activity_modules
    from .insurance_modules import build_all_insurance_modules
    return (
        build_all_flight_modules(from_json)
        + build_all_hotel_modules(from_json)
        + build_all_car_modules(from_json)
        + build_all_activity_modules(from_json)
        + build_all_insurance_modules(from_json)
    )
