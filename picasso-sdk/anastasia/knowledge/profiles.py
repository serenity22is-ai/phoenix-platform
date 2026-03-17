"""
ProfileStore — SystemProfile CRUD with persistent JSON storage.

Manages the lifecycle of SystemProfile objects: create, read, update, delete,
and search. Profiles are persisted as individual JSON files on disk and
loaded into memory for fast access. All mutations are thread-safe and
auto-saved.

Seeded with the Redbox (AERTiCKET/Picasso Travel) profile on first
initialization since that system is already reverse-engineered and
in production use.

MYSTES KYRIOS LLC — Confidential.
"""

import json
import logging
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.types import (
    AdapterPattern,
    BookingFlow,
    SystemProfile,
    SystemQuirk,
    VerticalType,
)
from ..core.events import Event, EventBus, EventType

logger = logging.getLogger(__name__)


def _build_redbox_seed_profile() -> SystemProfile:
    """
    Build the seed profile for Redbox (AERTiCKET/Picasso Travel).

    This system is already reverse-engineered and integrated in the MYSTES
    platform. The profile captures all functional knowledge accumulated
    during Builds #119-123.
    """
    endpoints = [
        {
            "path": "/availableFare/search",
            "method": "POST",
            "purpose": "Search available fares across POS markets",
            "notes": "Passenger types must be GDS codes: ADT/CHD/INF",
        },
        {
            "path": "/availableFare/details",
            "method": "POST",
            "purpose": "Get detailed fare breakdown for a specific offer",
        },
        {
            "path": "/shoppingCart/add",
            "method": "POST",
            "purpose": "Add selected fare to shopping cart",
        },
        {
            "path": "/shoppingCart/get",
            "method": "GET",
            "purpose": "Retrieve current shopping cart contents",
        },
        {
            "path": "/shoppingCart/remove",
            "method": "DELETE",
            "purpose": "Remove item from shopping cart",
        },
        {
            "path": "/superPNR/create",
            "method": "POST",
            "purpose": "Create super-PNR from cart (finalize booking)",
        },
        {
            "path": "/superPNR/get",
            "method": "GET",
            "purpose": "Retrieve super-PNR details",
        },
        {
            "path": "/seatmap/get",
            "method": "POST",
            "purpose": "Retrieve seat map for a flight segment",
        },
        {
            "path": "/document/list",
            "method": "GET",
            "purpose": "List booking documents (e-tickets, invoices)",
        },
        {
            "path": "/document/download",
            "method": "GET",
            "purpose": "Download a specific document by ID",
        },
        {
            "path": "/profile/get",
            "method": "GET",
            "purpose": "Retrieve agency/branch profile configuration",
        },
        {
            "path": "/configuration/get",
            "method": "GET",
            "purpose": "Retrieve system configuration and feature flags",
        },
    ]

    booking_flow = BookingFlow(
        steps=[
            {
                "order": 1,
                "name": "search",
                "endpoint": "/availableFare/search",
                "method": "POST",
                "required_fields": [
                    "origin", "destination", "departureDate",
                    "passengers", "cabinClass",
                ],
                "notes": "Use GDS pax codes (ADT/CHD/INF). "
                         "Fare types: PUB/NET/NEG. "
                         "Cabin: ECONOMY/PREMIUM_ECONOMY/BUSINESS/FIRST.",
            },
            {
                "order": 2,
                "name": "select_fare",
                "endpoint": "/availableFare/details",
                "method": "POST",
                "required_fields": ["fareId"],
                "notes": "Returns full price breakdown per passenger type.",
            },
            {
                "order": 3,
                "name": "add_to_cart",
                "endpoint": "/shoppingCart/add",
                "method": "POST",
                "required_fields": ["fareId", "passengers"],
                "notes": "Cart is session-scoped; clearing session clears cart.",
            },
            {
                "order": 4,
                "name": "checkout",
                "endpoint": "/shoppingCart/get",
                "method": "GET",
                "required_fields": [],
                "notes": "Validate cart contents before creating super-PNR.",
            },
            {
                "order": 5,
                "name": "create_booking",
                "endpoint": "/superPNR/create",
                "method": "POST",
                "required_fields": ["cartId", "passengerDetails", "contactInfo"],
                "notes": "Creates PNR in GDS. Returns confirmation number.",
            },
        ],
        total_steps=5,
        estimated_time_seconds=12.0,
        requires_auth=True,
        supports_guest=False,
    )

    quirks = [
        SystemQuirk(
            description="Session tokens expire after 24 hours. "
                        "Auto-login via Playwright + TOTP is required for "
                        "unattended operation.",
            category="auth",
            severity="warning",
            workaround="Use picasso_auth.py token manager with 24h TTL refresh.",
            discovered_by="mystes_internal",
        ),
        SystemQuirk(
            description="Passenger types MUST be GDS codes (ADT, CHD, INF). "
                        "Sending 'ADULT', 'CHILD', or 'INFANT' returns "
                        "cryptic 400 errors with no useful message.",
            category="encoding",
            severity="critical",
            workaround="Map human-readable types to GDS codes before API call.",
            discovered_by="mystes_internal",
        ),
        SystemQuirk(
            description="Fare types are PUB (published), NET (net), NEG "
                        "(negotiated). Using any other string silently returns "
                        "only PUB fares without error.",
            category="encoding",
            severity="warning",
            workaround="Validate fare type against [PUB, NET, NEG] enum.",
            discovered_by="mystes_internal",
        ),
    ]

    return SystemProfile(
        id=str(uuid.uuid5(uuid.NAMESPACE_DNS, "redbox.aerticket.picasso")),
        name="Redbox",
        vendor="AERTiCKET/Picasso Travel",
        version="1.0",
        vertical=VerticalType.FLIGHTS.value,
        protocol="rest",
        base_url="aerpackit.flightconex.de/redbox/",
        auth_method="session_cookie",
        auth_details={
            "token_endpoint": "Keycloak SSO via Cockpit redirect",
            "refresh_flow": "Playwright headless + TOTP (pyotp)",
            "scopes": [],
            "notes": "Token persisted to .picasso_token.json with 24h TTL. "
                     "Keycloak 2FA uses TOTP authenticator.",
        },
        booking_flow=booking_flow,
        endpoints=endpoints,
        data_schemas={
            "passenger": {
                "type_codes": ["ADT", "CHD", "INF"],
                "required_fields": [
                    "firstName", "lastName", "dateOfBirth", "gender",
                ],
            },
            "fare": {
                "fare_types": ["PUB", "NET", "NEG"],
                "cabin_classes": [
                    "ECONOMY", "PREMIUM_ECONOMY", "BUSINESS", "FIRST",
                ],
            },
        },
        quirks=quirks,
        adapters=[],
        readiness="production",
        confidence=0.95,
        installations=1,
        learned_from=["mystes_internal"],
        tags=[
            "flights", "gds", "consolidator", "102-country-pos",
            "amadeus-backend", "session-auth", "totp",
        ],
    )


def _build_amadeus_seed_profile() -> SystemProfile:
    """
    Seed profile for Amadeus GDS — the dominant global distribution system.

    Readiness: 'documented' — we know the API structure from public docs
    and Picasso's internal usage, but haven't connected directly.
    """
    return SystemProfile(
        id=str(uuid.uuid5(uuid.NAMESPACE_DNS, "amadeus.gds")),
        name="Amadeus",
        vendor="Amadeus IT Group",
        version="2.0",
        vertical=VerticalType.FLIGHTS.value,
        protocol="rest",
        base_url="api.amadeus.com/v2",
        auth_method="oauth2",
        auth_details={
            "token_endpoint": "/v1/security/oauth2/token",
            "grant_type": "client_credentials",
            "scopes": [],
            "notes": "Self-Service deprecated. Enterprise API only. "
                     "Picasso uses Amadeus internally — MYSTES does NOT connect directly.",
        },
        booking_flow=BookingFlow(
            steps=[
                {"order": 1, "name": "search", "endpoint": "/shopping/flight-offers", "method": "GET"},
                {"order": 2, "name": "price", "endpoint": "/shopping/flight-offers/pricing", "method": "POST"},
                {"order": 3, "name": "book", "endpoint": "/booking/flight-orders", "method": "POST"},
            ],
            total_steps=3,
            estimated_time_seconds=8.0,
            requires_auth=True,
            supports_guest=False,
        ),
        endpoints=[
            {"path": "/shopping/flight-offers", "method": "GET", "purpose": "Flight search"},
            {"path": "/shopping/flight-offers/pricing", "method": "POST", "purpose": "Price confirmation"},
            {"path": "/booking/flight-orders", "method": "POST", "purpose": "Create booking"},
            {"path": "/reference-data/locations", "method": "GET", "purpose": "Airport/city search"},
            {"path": "/shopping/seatmaps", "method": "GET", "purpose": "Seat map retrieval"},
        ],
        data_schemas={
            "passenger": {"type_codes": ["ADT", "CHD", "INF", "YTH", "STU"]},
            "cabin": {"classes": ["ECONOMY", "PREMIUM_ECONOMY", "BUSINESS", "FIRST"]},
        },
        quirks=[
            SystemQuirk(
                description="Self-Service tier discontinued in 2025. Enterprise-only access now.",
                category="access",
                severity="critical",
                workaround="Use Picasso/AERTiCKET as consolidator (they use Amadeus internally).",
                discovered_by="mystes_internal",
            ),
        ],
        adapters=[],
        readiness="documented",
        confidence=0.7,
        installations=0,
        learned_from=["public_docs", "picasso_integration"],
        tags=["flights", "gds", "enterprise", "oauth2", "global"],
    )


def _build_sabre_seed_profile() -> SystemProfile:
    """
    Seed profile for Sabre GDS — second-largest GDS globally.

    Readiness: 'documented' — known from public API docs and industry knowledge.
    """
    return SystemProfile(
        id=str(uuid.uuid5(uuid.NAMESPACE_DNS, "sabre.gds")),
        name="Sabre",
        vendor="Sabre Corporation",
        version="6.0",
        vertical=VerticalType.FLIGHTS.value,
        protocol="rest",
        base_url="api.sabre.com/v2",
        auth_method="oauth2",
        auth_details={
            "token_endpoint": "/v2/auth/token",
            "grant_type": "client_credentials",
            "scopes": [],
            "notes": "REST APIs available alongside legacy SOAP/XML. "
                     "PCC (Pseudo City Code) required for agency identification.",
        },
        booking_flow=BookingFlow(
            steps=[
                {"order": 1, "name": "search", "endpoint": "/shop/flights", "method": "POST"},
                {"order": 2, "name": "revalidate", "endpoint": "/book/flights/revalidate", "method": "POST"},
                {"order": 3, "name": "book", "endpoint": "/book/flights", "method": "POST"},
            ],
            total_steps=3,
            estimated_time_seconds=10.0,
            requires_auth=True,
            supports_guest=False,
        ),
        endpoints=[
            {"path": "/shop/flights", "method": "POST", "purpose": "Bargain Finder Max (flight search)"},
            {"path": "/book/flights/revalidate", "method": "POST", "purpose": "Price revalidation"},
            {"path": "/book/flights", "method": "POST", "purpose": "Create PNR"},
            {"path": "/lists/utilities/airlines", "method": "GET", "purpose": "Airline reference data"},
        ],
        data_schemas={
            "passenger": {"type_codes": ["ADT", "CNN", "INF"]},
            "note": "Sabre uses CNN (not CHD) for child passengers",
        },
        quirks=[
            SystemQuirk(
                description="Child passenger type is CNN (not CHD like Amadeus). "
                            "Using CHD returns cryptic error.",
                category="encoding",
                severity="critical",
                workaround="Map CHD -> CNN for Sabre requests.",
                discovered_by="industry_knowledge",
            ),
        ],
        adapters=[],
        readiness="documented",
        confidence=0.6,
        installations=0,
        learned_from=["public_docs"],
        tags=["flights", "gds", "enterprise", "oauth2", "north_america"],
    )


def _build_liteapi_seed_profile() -> SystemProfile:
    """
    Seed profile for liteAPI — hotel booking API used in MYSTES.

    Readiness: 'tested' — integrated and tested in MYSTES sandbox.
    """
    return SystemProfile(
        id=str(uuid.uuid5(uuid.NAMESPACE_DNS, "liteapi.hotels")),
        name="liteAPI",
        vendor="liteAPI",
        version="3.0",
        vertical=VerticalType.HOTELS.value,
        protocol="rest",
        base_url="api.liteapi.travel/v3.0",
        auth_method="api_key",
        auth_details={
            "header": "X-API-Key",
            "notes": "Sandbox key prefix: sand_. Production: self-serve upgrade. "
                     "No per-API-call fees — commission baked into net rate.",
        },
        booking_flow=BookingFlow(
            steps=[
                {"order": 1, "name": "search", "endpoint": "/hotels/rates", "method": "GET"},
                {"order": 2, "name": "prebook", "endpoint": "/rates/prebook", "method": "POST"},
                {"order": 3, "name": "book", "endpoint": "/rates/book", "method": "POST"},
            ],
            total_steps=3,
            estimated_time_seconds=6.0,
            requires_auth=True,
            supports_guest=True,
        ),
        endpoints=[
            {"path": "/hotels/rates", "method": "GET", "purpose": "Hotel rate search by city"},
            {"path": "/rates/prebook", "method": "POST", "purpose": "Validate rate before booking"},
            {"path": "/rates/book", "method": "POST", "purpose": "Confirm booking (needs prebookId)"},
            {"path": "/data/hotel", "method": "GET", "purpose": "Hotel details (name not in rates)"},
            {"path": "/bookings", "method": "GET", "purpose": "List bookings"},
        ],
        data_schemas={
            "search": {
                "required": ["cityName", "countryCode", "checkin", "checkout", "adults"],
                "notes": "Uses cityName+countryCode (resolved from IATA via airports.py). "
                         "Hotel names must be fetched separately from /data/hotel endpoint.",
            },
            "booking": {
                "no_passport": True,
                "flat_fee": 15.0,
                "notes": "No proxy needed (unlike flights).",
            },
        },
        quirks=[
            SystemQuirk(
                description="Hotel names are NOT included in rate responses. "
                            "Must call /data/hotel with hotelId to get the name.",
                category="api_design",
                severity="warning",
                workaround="Batch-fetch hotel names after rate search results.",
                discovered_by="mystes_internal",
            ),
            SystemQuirk(
                description="Prebook step is mandatory — booking without prebook fails. "
                            "prebookId from prebook response is required for book call.",
                category="flow",
                severity="critical",
                workaround="Always call prebook before book. Store prebookId.",
                discovered_by="mystes_internal",
            ),
            SystemQuirk(
                description="Some hotels have inverted margins (offerRetailRate > suggestedSellingPrice). "
                            "Need filtering logic to avoid negative-margin bookings.",
                category="pricing",
                severity="warning",
                workaround="Filter: only display hotels where offerRetailRate < suggestedSellingPrice.",
                discovered_by="mystes_internal",
            ),
        ],
        adapters=[],
        readiness="tested",
        confidence=0.85,
        installations=1,
        learned_from=["mystes_internal"],
        tags=["hotels", "api_key_auth", "no_passport", "flat_fee"],
    )


def _build_travelport_seed_profile() -> SystemProfile:
    """Seed profile for Travelport (Galileo/Apollo/Worldspan) — third major GDS."""
    return SystemProfile(
        id=str(uuid.uuid5(uuid.NAMESPACE_DNS, "travelport.gds")),
        name="Travelport",
        vendor="Travelport",
        version="21.1",
        vertical=VerticalType.FLIGHTS.value,
        protocol="soap",
        base_url="americas.universal-api.travelport.com",
        auth_method="basic",
        auth_details={
            "notes": "SOAP/XML based. Universal API covers flights, hotels, cars. "
                     "Uses Galileo (EMEA/APAC), Apollo (Americas), Worldspan (legacy). "
                     "Credentials: TargetBranch + username/password.",
        },
        booking_flow=BookingFlow(
            steps=[
                {"order": 1, "name": "search", "endpoint": "/LowFareSearchReq", "method": "POST"},
                {"order": 2, "name": "price", "endpoint": "/AirPriceReq", "method": "POST"},
                {"order": 3, "name": "book", "endpoint": "/AirCreateReservationReq", "method": "POST"},
            ],
            total_steps=3,
            estimated_time_seconds=15.0,
            requires_auth=True,
            supports_guest=False,
        ),
        endpoints=[
            {"path": "/LowFareSearchReq", "method": "POST", "purpose": "Low fare search"},
            {"path": "/AirPriceReq", "method": "POST", "purpose": "Price quote"},
            {"path": "/AirCreateReservationReq", "method": "POST", "purpose": "Create PNR"},
        ],
        data_schemas={},
        quirks=[
            SystemQuirk(
                description="SOAP/XML only — no REST API. Requires XML parsing.",
                category="protocol",
                severity="warning",
                workaround="Use zeep or suds-community for SOAP client generation.",
                discovered_by="industry_knowledge",
            ),
        ],
        adapters=[],
        readiness="documented",
        confidence=0.5,
        installations=0,
        learned_from=["public_docs"],
        tags=["flights", "hotels", "cars", "gds", "soap", "xml"],
    )


def _build_duffel_seed_profile() -> SystemProfile:
    """
    Seed profile for Duffel — NDC flight aggregator with 300+ airlines.

    Readiness: 'tested' — integrated and tested in MYSTES sandbox.
    Duffel bypasses GDS entirely, connecting directly to airline NDC APIs.
    Complements Picasso/Redbox (GDS + consolidator) with NDC-only fares.
    """
    endpoints = [
        {
            "path": "/air/offer_requests",
            "method": "POST",
            "purpose": "Search flights (create offer request, returns offers inline)",
            "notes": "Query params: return_offers=true, supplier_timeout=30000",
        },
        {
            "path": "/air/offers/{id}",
            "method": "GET",
            "purpose": "Get/refresh single offer (price may change)",
        },
        {
            "path": "/air/offers/{id}/available_services",
            "method": "GET",
            "purpose": "Get available ancillary services (baggage, seats, meals)",
        },
        {
            "path": "/air/seat_maps",
            "method": "GET",
            "purpose": "Get seat map for offer (query: offer_id)",
        },
        {
            "path": "/air/orders",
            "method": "POST",
            "purpose": "Create booking (purchase offer → confirmed order)",
        },
        {
            "path": "/air/orders/{id}",
            "method": "GET",
            "purpose": "Get order details (booking status, tickets, segments)",
        },
        {
            "path": "/air/order_cancellations",
            "method": "POST",
            "purpose": "Request order cancellation (two-step: request → confirm)",
        },
        {
            "path": "/air/order_cancellations/{id}/actions/confirm",
            "method": "POST",
            "purpose": "Confirm cancellation (finalizes refund)",
        },
        {
            "path": "/air/order_change_requests",
            "method": "POST",
            "purpose": "Request order change (date/route)",
        },
        {
            "path": "/air/order_changes",
            "method": "POST",
            "purpose": "Confirm order change with selected change offer",
        },
        {
            "path": "/places/suggestions",
            "method": "GET",
            "purpose": "Autocomplete airports/cities (query param: query)",
        },
        {
            "path": "/air/airlines",
            "method": "GET",
            "purpose": "List airlines available through Duffel",
        },
        {
            "path": "/air/webhooks",
            "method": "POST",
            "purpose": "Register webhook for order events",
        },
    ]

    booking_flow = BookingFlow(
        steps=[
            {
                "order": 1,
                "name": "search",
                "endpoint": "/air/offer_requests",
                "method": "POST",
                "required_fields": [
                    "slices", "passengers", "cabin_class",
                ],
                "notes": "Passenger types: adult, child (with age), "
                         "infant_without_seat. Cabin: economy, premium_economy, "
                         "business, first. Returns offers inline with "
                         "return_offers=true.",
            },
            {
                "order": 2,
                "name": "refresh_offer",
                "endpoint": "/air/offers/{offer_id}",
                "method": "GET",
                "required_fields": ["offer_id"],
                "notes": "Refresh to get current price. Offers expire "
                         "15-30 minutes after search.",
            },
            {
                "order": 3,
                "name": "create_order",
                "endpoint": "/air/orders",
                "method": "POST",
                "required_fields": [
                    "selected_offers", "passengers", "payments",
                ],
                "notes": "Single-step booking. Payment types: balance "
                         "(Duffel balance) or arc_bsp_cash (IATA). "
                         "Returns booking_reference (PNR) and documents.",
            },
        ],
        total_steps=3,
        estimated_time_seconds=8.0,
        requires_auth=True,
        supports_guest=False,
    )

    quirks = [
        SystemQuirk(
            description="Bearer token is permanent — no expiry, no refresh. "
                        "Rotation is manual via Duffel dashboard.",
            category="auth",
            severity="info",
            workaround="No action needed — token lasts until manually rotated.",
            discovered_by="mystes_internal",
        ),
        SystemQuirk(
            description="Offers expire 15-30 minutes after search. Booking an "
                        "expired offer returns 404/409. Always refresh before booking.",
            category="flow",
            severity="warning",
            workaround="Call GET /air/offers/{id} before POST /air/orders to "
                        "confirm current price and availability.",
            discovered_by="mystes_internal",
        ),
        SystemQuirk(
            description="Gender format is 'm'/'f' (NOT 'Male'/'Female' like Redbox). "
                        "Title is lowercase ('mr'/'mrs'/'ms', NOT 'MR'/'MRS'). "
                        "Using wrong format returns 422 validation error.",
            category="encoding",
            severity="critical",
            workaround="Map Redbox format to Duffel: Male→m, Female→f, MR→mr.",
            discovered_by="mystes_internal",
        ),
        SystemQuirk(
            description="Cancellation is two-step: POST /order_cancellations (request) "
                        "→ POST /order_cancellations/{id}/actions/confirm. First step "
                        "returns refund amount, second step finalizes.",
            category="flow",
            severity="warning",
            workaround="Always show refund amount to user before confirming.",
            discovered_by="mystes_internal",
        ),
        SystemQuirk(
            description="Single POS — no geographic price arbitrage. Duffel returns "
                        "the same price regardless of requester location.",
            category="pricing",
            severity="info",
            workaround="Use for NDC-exclusive fares, not for arbitrage. "
                        "Combine with Picasso for best-of-both pricing.",
            discovered_by="mystes_internal",
        ),
    ]

    return SystemProfile(
        id=str(uuid.uuid5(uuid.NAMESPACE_DNS, "duffel.ndc")),
        name="Duffel",
        vendor="Duffel",
        version="2.0",
        vertical=VerticalType.FLIGHTS.value,
        protocol="rest",
        base_url="api.duffel.com",
        auth_method="bearer_token",
        auth_details={
            "header": "Authorization: Bearer {token}",
            "version_header": "Duffel-Version: v2",
            "token_env_var": "DUFFEL_ACCESS_TOKEN",
            "test_prefix": "duffel_test_",
            "live_prefix": "duffel_live_",
            "notes": "Static Bearer token — no OAuth, no refresh, no expiry. "
                     "Test tokens return synthetic Duffel Airways data. "
                     "Live tokens connect to real airline inventory.",
        },
        booking_flow=booking_flow,
        endpoints=endpoints,
        data_schemas={
            "passenger": {
                "type_codes": ["adult", "child", "infant_without_seat"],
                "required_fields": [
                    "given_name", "family_name", "born_on", "gender",
                    "title", "email", "phone_number",
                ],
                "gender_values": ["m", "f"],
                "title_values": ["mr", "mrs", "ms", "miss", "dr"],
                "notes": "Children specify age (2-17). Infants are lap only. "
                         "Passport required for international (identity_documents array).",
            },
            "offer": {
                "pricing_fields": [
                    "total_amount", "total_currency", "base_amount",
                    "base_currency", "tax_amount", "tax_currency",
                ],
                "condition_fields": [
                    "change_before_departure", "refund_before_departure",
                ],
                "notes": "Offers expire 15-30 min. expires_at field indicates deadline.",
            },
            "payment": {
                "types": ["balance", "arc_bsp_cash"],
                "notes": "balance = Duffel account balance (test + live). "
                         "arc_bsp_cash = IATA agent settlement.",
            },
        },
        quirks=quirks,
        adapters=[],
        readiness="tested",
        confidence=0.90,
        installations=1,
        learned_from=["mystes_internal", "duffel_docs"],
        tags=[
            "flights", "ndc", "bearer_token", "300_airlines",
            "direct_connect", "no_arbitrage", "ancillaries",
        ],
    )


def _build_kiwi_seed_profile() -> SystemProfile:
    """
    Seed profile for Kiwi Tequila — flight aggregator with 750+ carriers.

    Readiness: 'tested' — integrated and tested in MYSTES.
    Kiwi's unique capability is virtual interlining — combining carriers
    that don't normally interline into single itineraries.
    """
    endpoints = [
        {
            "path": "/v2/search",
            "method": "GET",
            "purpose": "Search flights across 750+ carriers",
            "notes": "Date format DD/MM/YYYY. vehicle_type=aircraft for flights only.",
        },
        {
            "path": "/locations/query",
            "method": "GET",
            "purpose": "Autocomplete airports/cities (query param: term)",
        },
        {
            "path": "/v2/booking/check_flights",
            "method": "GET",
            "purpose": "Validate flight availability and current price",
            "notes": "Must call within 30 min of search. Returns session_id for booking.",
        },
        {
            "path": "/v2/booking/save_booking",
            "method": "POST",
            "purpose": "Create booking with passenger details",
            "notes": "Requires booking_token + session_id from check_flights.",
        },
        {
            "path": "/v2/booking/confirm_payment",
            "method": "POST",
            "purpose": "Confirm payment for booking",
            "notes": "Must call within 30 min of save_booking.",
        },
        {
            "path": "/v2/flights_multi",
            "method": "POST",
            "purpose": "Multi-city/segment search (max 9 segments)",
        },
    ]

    booking_flow = BookingFlow(
        steps=[
            {
                "order": 1,
                "name": "search",
                "endpoint": "/v2/search",
                "method": "GET",
                "required_fields": [
                    "fly_from", "fly_to", "date_from", "date_to",
                ],
                "notes": "Returns booking_token per itinerary. Date format DD/MM/YYYY.",
            },
            {
                "order": 2,
                "name": "validate",
                "endpoint": "/v2/booking/check_flights",
                "method": "GET",
                "required_fields": ["booking_token"],
                "notes": "Validates availability, returns session_id. "
                         "Must call within 30 min of search.",
            },
            {
                "order": 3,
                "name": "book",
                "endpoint": "/v2/booking/save_booking",
                "method": "POST",
                "required_fields": [
                    "booking_token", "session_id", "passengers",
                ],
                "notes": "Passenger birthday format DD/MM/YYYY. "
                         "Returns booking_id + transaction_id.",
            },
        ],
        total_steps=3,
        estimated_time_seconds=10.0,
        requires_auth=True,
        supports_guest=False,
    )

    quirks = [
        SystemQuirk(
            description="Date format is DD/MM/YYYY for ALL input parameters "
                        "(not ISO 8601). Responses use ISO 8601.",
            category="encoding",
            severity="critical",
            workaround="Convert YYYY-MM-DD to DD/MM/YYYY before sending.",
            discovered_by="mystes_internal",
        ),
        SystemQuirk(
            description="booking_token expires in ~30 minutes. Must call "
                        "check_flights within this window.",
            category="flow",
            severity="warning",
            workaround="Search again if token expired.",
            discovered_by="mystes_internal",
        ),
        SystemQuirk(
            description="No POS parameter — same price globally. No geographic "
                        "arbitrage possible through Kiwi API.",
            category="pricing",
            severity="info",
            workaround="Use for coverage and virtual interlining, not arbitrage. "
                        "Combine with Picasso for best pricing.",
            discovered_by="mystes_internal",
        ),
        SystemQuirk(
            description="Virtual interlining may require bag rechecks between "
                        "carriers. bags_recheck_required field indicates this.",
            category="flow",
            severity="warning",
            workaround="Always inform passengers about bag recheck requirements.",
            discovered_by="mystes_internal",
        ),
        SystemQuirk(
            description="Kiwi is merchant of record — passengers get Kiwi "
                        "booking_id, not airline PNR. Post-booking support via Kiwi.",
            category="flow",
            severity="info",
            workaround="Store Kiwi booking_id for reference.",
            discovered_by="mystes_internal",
        ),
    ]

    return SystemProfile(
        id=str(uuid.uuid5(uuid.NAMESPACE_DNS, "kiwi.tequila")),
        name="Kiwi Tequila",
        vendor="Kiwi.com",
        version="2.0",
        vertical=VerticalType.FLIGHTS.value,
        protocol="rest",
        base_url="tequila-api.kiwi.com",
        auth_method="api_key_header",
        auth_details={
            "header": "apikey: {key}",
            "key_env_var": "KIWI_API_KEY",
            "notes": "API key in 'apikey' header. Partnership-based access "
                     "(invitation-only since mid-2024). No OAuth, no refresh.",
        },
        booking_flow=booking_flow,
        endpoints=endpoints,
        data_schemas={
            "passenger": {
                "required_fields": [
                    "name", "surname", "birthday", "nationality",
                    "category", "email", "phone",
                ],
                "birthday_format": "DD/MM/YYYY",
                "category_values": ["adult", "child", "infant"],
                "passport_fields": ["cardno", "expiration"],
                "notes": "Name fields are 'name'+'surname' (not given_name/family_name). "
                         "Birthday and passport expiry in DD/MM/YYYY format.",
            },
            "itinerary": {
                "pricing_fields": ["price"],
                "currency_field": "curr",
                "notes": "Price is total including taxes. Currency set in search params. "
                         "Virtual interlining indicated by virtual_interlining field.",
            },
        },
        quirks=quirks,
        adapters=[],
        readiness="tested",
        confidence=0.85,
        installations=1,
        learned_from=["mystes_internal", "kiwi_tequila_docs"],
        tags=[
            "flights", "aggregator", "virtual_interlining", "api_key",
            "750_carriers", "ground_transport", "no_arbitrage",
        ],
    )


def _build_all_seed_profiles() -> List[SystemProfile]:
    """Build all seed profiles for initial knowledge base."""
    return [
        _build_redbox_seed_profile(),
        _build_amadeus_seed_profile(),
        _build_sabre_seed_profile(),
        _build_liteapi_seed_profile(),
        _build_travelport_seed_profile(),
        _build_duffel_seed_profile(),
        _build_kiwi_seed_profile(),
    ]


class ProfileStore:
    """
    Persistent storage and CRUD operations for SystemProfile objects.

    Profiles are stored as individual JSON files on disk in a configurable
    directory. An in-memory index provides fast lookups by ID, name, and
    search queries. All mutations are thread-safe (threading.Lock) and
    auto-persisted on every write.

    On first initialization (empty store directory), the Redbox profile
    is automatically seeded since that system is already known.

    Args:
        event_bus: EventBus instance for publishing profile change events.
        storage_dir: Path to the directory where profile JSON files are stored.
                     Defaults to ``~/.anastasia/profiles``.
    """

    def __init__(
        self,
        event_bus: EventBus,
        storage_dir: Optional[str] = None,
    ):
        self._event_bus = event_bus
        self._lock = threading.Lock()

        if storage_dir is None:
            storage_dir = os.path.join(
                os.path.expanduser("~"), ".anastasia", "profiles"
            )
        self._storage_dir = Path(storage_dir)
        self._storage_dir.mkdir(parents=True, exist_ok=True)

        # In-memory index: id -> SystemProfile
        self._profiles: Dict[str, SystemProfile] = {}
        # Name index: lowercase name -> id (for get_by_name lookups)
        self._name_index: Dict[str, str] = {}

        self._load_all()

        # Seed profiles if the store is completely empty
        if not self._profiles:
            logger.info("Empty profile store — seeding Redbox profile")
            for seed in _build_all_seed_profiles():
                self._profiles[seed.id] = seed
                self._name_index[seed.name.lower()] = seed.id
                self._save_profile(seed)

    # ------------------------------------------------------------------
    # CRUD operations
    # ------------------------------------------------------------------

    def create_profile(self, profile: SystemProfile) -> SystemProfile:
        """
        Create a new SystemProfile in the store.

        If the profile has no ``id``, one is generated automatically.
        Publishes ``SYSTEM_PROFILE_UPDATED`` on success.

        Args:
            profile: The SystemProfile to persist.

        Returns:
            The persisted SystemProfile (with id populated).

        Raises:
            ValueError: If a profile with the same ID already exists.
        """
        with self._lock:
            if not profile.id:
                profile.id = str(uuid.uuid4())

            if profile.id in self._profiles:
                raise ValueError(
                    f"Profile with id '{profile.id}' already exists. "
                    f"Use update_profile() to modify it."
                )

            profile.first_learned = time.time()
            profile.last_updated = time.time()

            self._profiles[profile.id] = profile
            if profile.name:
                self._name_index[profile.name.lower()] = profile.id
            self._save_profile(profile)

        self._publish_update(profile.id, "created")
        logger.info("Created profile: %s (%s)", profile.name, profile.id)
        return profile

    def get_profile(self, profile_id: str) -> Optional[SystemProfile]:
        """
        Retrieve a SystemProfile by its unique ID.

        Args:
            profile_id: The UUID of the profile.

        Returns:
            The SystemProfile if found, otherwise ``None``.
        """
        with self._lock:
            return self._profiles.get(profile_id)

    def update_profile(
        self,
        profile_id: str,
        data: Dict[str, Any],
    ) -> Optional[SystemProfile]:
        """
        Update an existing SystemProfile with partial data.

        Only the fields present in ``data`` are updated; all other fields
        are preserved. Nested objects (``booking_flow``, ``quirks``,
        ``adapters``) are replaced wholesale if provided.

        Publishes ``SYSTEM_PROFILE_UPDATED`` on success.

        Args:
            profile_id: The UUID of the profile to update.
            data: Dictionary of fields to update.

        Returns:
            The updated SystemProfile, or ``None`` if not found.
        """
        with self._lock:
            profile = self._profiles.get(profile_id)
            if profile is None:
                return None

            # Remove old name index entry if name is changing
            old_name = profile.name.lower() if profile.name else ""

            for key, value in data.items():
                if key == "id":
                    continue  # Never allow ID mutation
                if key == "booking_flow" and isinstance(value, dict):
                    profile.booking_flow = BookingFlow.from_dict(value)
                elif key == "quirks" and isinstance(value, list):
                    profile.quirks = [
                        SystemQuirk.from_dict(q) if isinstance(q, dict) else q
                        for q in value
                    ]
                elif key == "adapters" and isinstance(value, list):
                    profile.adapters = [
                        AdapterPattern.from_dict(a) if isinstance(a, dict) else a
                        for a in value
                    ]
                elif hasattr(profile, key):
                    setattr(profile, key, value)

            profile.last_updated = time.time()

            # Update name index
            new_name = profile.name.lower() if profile.name else ""
            if old_name and old_name != new_name:
                self._name_index.pop(old_name, None)
            if new_name:
                self._name_index[new_name] = profile.id

            self._save_profile(profile)

        self._publish_update(profile_id, "updated")
        logger.info("Updated profile: %s (%s)", profile.name, profile_id)
        return profile

    def delete_profile(self, profile_id: str) -> bool:
        """
        Delete a SystemProfile from the store and disk.

        Publishes ``SYSTEM_PROFILE_UPDATED`` with action ``deleted``.

        Args:
            profile_id: The UUID of the profile to delete.

        Returns:
            ``True`` if the profile was deleted, ``False`` if not found.
        """
        with self._lock:
            profile = self._profiles.pop(profile_id, None)
            if profile is None:
                return False

            if profile.name:
                self._name_index.pop(profile.name.lower(), None)

            # Remove file from disk
            file_path = self._storage_dir / f"{profile_id}.json"
            if file_path.exists():
                file_path.unlink()

        self._publish_update(profile_id, "deleted")
        logger.info("Deleted profile: %s (%s)", profile.name, profile_id)
        return True

    # ------------------------------------------------------------------
    # Search and lookup
    # ------------------------------------------------------------------

    def get_by_name(self, name: str) -> Optional[SystemProfile]:
        """
        Look up a SystemProfile by its system name (case-insensitive).

        Args:
            name: System name, e.g. ``"redbox"``, ``"sabre"``.

        Returns:
            The matching SystemProfile, or ``None`` if not found.
        """
        with self._lock:
            profile_id = self._name_index.get(name.lower())
            if profile_id:
                return self._profiles.get(profile_id)
        return None

    def search_profiles(
        self,
        query: Optional[str] = None,
        vertical: Optional[str] = None,
        vendor: Optional[str] = None,
    ) -> List[SystemProfile]:
        """
        Search and filter profiles by text query, vertical, or vendor.

        All filters are combined with AND logic. The text ``query``
        matches against name, vendor, tags, and base_url (case-insensitive).

        Args:
            query: Free-text search string (optional).
            vertical: Filter by VerticalType value, e.g. ``"flights"`` (optional).
            vendor: Filter by vendor name substring (optional).

        Returns:
            List of matching SystemProfile objects, sorted by confidence
            descending.
        """
        with self._lock:
            results = list(self._profiles.values())

        # Apply filters
        if vertical:
            vertical_lower = vertical.lower()
            results = [
                p for p in results
                if p.vertical and p.vertical.lower() == vertical_lower
            ]

        if vendor:
            vendor_lower = vendor.lower()
            results = [
                p for p in results
                if p.vendor and vendor_lower in p.vendor.lower()
            ]

        if query:
            query_lower = query.lower()
            filtered = []
            for p in results:
                searchable = " ".join([
                    p.name or "",
                    p.vendor or "",
                    p.base_url or "",
                    " ".join(p.tags),
                ]).lower()
                if query_lower in searchable:
                    filtered.append(p)
            results = filtered

        # Sort by confidence descending
        results.sort(key=lambda p: p.confidence, reverse=True)
        return results

    def list_all(self) -> List[SystemProfile]:
        """
        Return all profiles in the store, sorted by name.

        Returns:
            List of all SystemProfile objects.
        """
        with self._lock:
            profiles = list(self._profiles.values())
        profiles.sort(key=lambda p: (p.name or "").lower())
        return profiles

    @property
    def count(self) -> int:
        """Return the total number of stored profiles."""
        return len(self._profiles)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save_profile(self, profile: SystemProfile) -> None:
        """Persist a single profile to disk as JSON."""
        file_path = self._storage_dir / f"{profile.id}.json"
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(profile.to_dict(), f, indent=2, ensure_ascii=False)
        except OSError as e:
            logger.error("Failed to save profile %s: %s", profile.id, e)

    def _load_all(self) -> None:
        """Load all profile JSON files from the storage directory."""
        if not self._storage_dir.exists():
            return

        loaded = 0
        for file_path in self._storage_dir.glob("*.json"):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                profile = SystemProfile.from_dict(data)
                self._profiles[profile.id] = profile
                if profile.name:
                    self._name_index[profile.name.lower()] = profile.id
                loaded += 1
            except (json.JSONDecodeError, OSError, KeyError) as e:
                logger.warning("Failed to load profile from %s: %s", file_path, e)

        if loaded:
            logger.info("Loaded %d profiles from %s", loaded, self._storage_dir)

    # ------------------------------------------------------------------
    # Event publishing
    # ------------------------------------------------------------------

    def _publish_update(self, profile_id: str, action: str) -> None:
        """Publish a SYSTEM_PROFILE_UPDATED event."""
        self._event_bus.publish(Event(
            type=EventType.SYSTEM_PROFILE_UPDATED,
            data={"profile_id": profile_id, "action": action},
            source="knowledge.profiles",
        ))
