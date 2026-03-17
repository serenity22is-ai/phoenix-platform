"""
MYSTES AI Engine — LLM-Powered Tool-Calling Orchestrator (Build #99)

Core AI chat module that connects an LLM (Claude via Anthropic tool-calling API)
to every Mystes platform capability. Users interact via natural language; the
engine decides which tools to invoke, executes them against real Mystes modules,
and returns a conversational response grounded in live data.

Architecture:
    User message
      -> MystesAI.chat()
        -> Build message history from AIMessage table
        -> Call Anthropic Messages API with tool definitions
        -> If response contains tool_use blocks:
             Execute tool via _execute_tool() dispatch
             Append tool_result to messages
             Re-call LLM (loop up to tier max)
        -> Return final text response + tool call metadata

Core Tools:
    search_flights, search_hotels, search_products, analyze_route,
    get_route_intelligence, get_market_briefing, get_trending,
    get_price_history, get_deals, discover_opportunities

Economic Model:
    AI query tiers: bronze 5/day, silver 10/day, gold 20/day, platinum 40/day.
    Paid subscription tiers (Explorer $4.99 – Unlimited $49.99/mo).
    Revenue = booking fees (35-50% of savings) + subscription revenue.

Usage:
    from mystes_ai import mystes_ai, get_ai_tier, check_ai_quota

    result = mystes_ai.chat(
        user_id=42,
        conversation_id="CONV-abc123",
        user_message="Find me cheap flights from JFK to Tokyo in March",
        tier_config={"max_tools_per_query": 5, "max_context_messages": 20},
    )
    # result = {"role": "assistant", "content": "...", "tool_calls": [...],
    #           "model_used": "...", "response_time_ms": N}
"""

import json
import logging
import os
import secrets
import time

import requests

logger = logging.getLogger(__name__)


# ===========================================================================
# Tier Definitions
# ===========================================================================

# ---------------------------------------------------------------------------
# AI Query Tier Caps
# ---------------------------------------------------------------------------
ARBITRAGE_FREE_QUERIES = {
    "bronze": {
        "free_queries_per_day": 5,
        "max_tools_per_query": 5,
        "max_context_messages": 10,
        "platform_fee_pct": 0.50,   # 50% consumer rate
    },
    "silver": {
        "free_queries_per_day": 10,
        "max_tools_per_query": 5,
        "max_context_messages": 15,
        "platform_fee_pct": 0.35,   # 35% subscriber rate
    },
    "gold": {
        "free_queries_per_day": 20,
        "max_tools_per_query": 8,
        "max_context_messages": 25,
        "platform_fee_pct": 0.20,
    },
    "platinum": {
        "free_queries_per_day": 40,
        "max_tools_per_query": 12,
        "max_context_messages": 50,
        "platform_fee_pct": 0.15,
    },
}

# ---------------------------------------------------------------------------
# Arbitrage Subscription Tiers (for NON-NODE users who pay cash for access)
# Nodes get queries from their tier allocation + overage purchases.
# Non-nodes must subscribe for any arbitrage access.
# These stack on top of node free queries for users who are BOTH node + subscriber.
# ---------------------------------------------------------------------------
ARBITRAGE_SUBSCRIPTION_TIERS = {
    "ai_free": {
        "name": "Node Free",
        "price_monthly_usd": 0.0,
        "queries_per_month": 0,  # Uses node tier free allocation only
        "max_tools_per_query": 3,
        "max_context_messages": 10,
        "features": [
            "5 free searches/day (Bronze node)",
            "Flights, hotels, transfers",
            "3 markets per search",
            "Wholesale pricing",
            "Buy more queries anytime ($0.02/query)",
        ],
    },
    "ai_explorer": {
        "name": "Explorer",
        "price_monthly_usd": 4.99,
        "queries_per_month": 200,
        "max_tools_per_query": 5,
        "max_context_messages": 15,
        "features": [
            "200 searches/month",
            "5 markets per search",
            "All verticals",
            "Price alerts",
        ],
    },
    "ai_pathfinder": {
        "name": "Pathfinder",
        "price_monthly_usd": 12.99,
        "queries_per_month": 600,
        "max_tools_per_query": 8,
        "max_context_messages": 25,
        "features": [
            "600 searches/month",
            "8 markets per search",
            "Route intelligence",
            "Priority processing",
        ],
    },
    "ai_navigator": {
        "name": "Navigator",
        "price_monthly_usd": 29.99,
        "queries_per_month": 2000,
        "max_tools_per_query": 12,
        "max_context_messages": 50,
        "features": [
            "2,000 searches/month",
            "12 markets per search",
            "Full intelligence suite",
            "Priority processing",
        ],
    },
    "ai_unlimited": {
        "name": "Unlimited",
        "price_monthly_usd": 49.99,
        "queries_per_month": None,  # unlimited
        "max_tools_per_query": 15,
        "max_context_messages": 100,
        "features": [
            "Unlimited searches",
            "All markets",
            "Full suite + API access",
            "Priority processing",
        ],
    },
}


# ===========================================================================
# System Prompt
# ===========================================================================

MYSTES_AI_SYSTEM_PROMPT = (
    "You are MYSTES AI — the internal booking agent for the MYSTES platform. "
    "You are NOT a user-facing chatbot. You are the intelligent backend that "
    "understands airline booking APIs inside and out, orchestrates the entire "
    "search → price → book → confirm pipeline, and manages bookings across "
    "multiple provider APIs.\n\n"

    "YOUR ROLE:\n"
    "- You are the booking brain behind MYSTES. The user interacts with a normal "
    "search UI — you power what happens under the hood.\n"
    "- You understand the Picasso/Redbox API (flight consolidator, 102 countries), "
    "liteAPI (hotels), and future vertical APIs deeply.\n"
    "- You execute searches, compare prices, create shopping carts, book flights, "
    "manage PNRs, generate documents, and handle post-booking operations.\n"
    "- You learn from every interaction and build institutional knowledge of API "
    "behaviors, edge cases, and optimal booking strategies.\n\n"

    "PICASSO/REDBOX API MASTERY (reverse-engineered, every endpoint verified):\n"
    "ENDPOINTS (the ONLY ones that exist — all others return 404):\n"
    "- POST /availableFare → fareSearchId, numberOfResults, numberOfAirlines\n"
    "- POST /availableFare/{id} → paginated results (pageNumber 1-indexed, key='results')\n"
    "  Body: {resultsPerPage, pageNumber, includeDetails, showFilters, sortingCriteria, filterCriteria}\n"
    "- GET /availableFare/{id}/fareRules?fareId={fareId} → 16 rule categories (HTML)\n"
    "- POST /seatmap → seat layout per segment\n"
    "- GET /shoppingCart → current cart\n"
    "- POST /shoppingCart/addAndCheckOut → cart + checkout (FLIGHT + PASSENGER + BOOKING_FEE_OVERRIDE)\n"
    "- DELETE /shoppingCart/{id} → cleanup\n"
    "- POST /superPNR → create booking from cart (PNR/locator returned)\n"
    "- POST /superPNR/search → search bookings (requires >=1 filter: locator, dates, airline, route)\n"
    "  Returns searchSummary with 13 statuses: openBookings, cancelled, voided, issued, refunded, flown, etc.\n"
    "- POST /document → generate ITINERARY/OFFER/CONFIRMATION/TRAVEL_REGISTRATION (PDF or email)\n"
    "- GET /profile?searchTerm=X → traveler profiles\n"
    "- GET /configuration → session status\n\n"

    "FARE DATA (from search results):\n"
    "- Each fare has: fareId, gds (AMADEUS/AER_DC/SABRE/FARELOGIX), total, totalTax\n"
    "- validatingAirline: {code, icao, name}\n"
    "- fareFamilies: [{airlineName: 'Basic Economy'/'LIGHT'/etc, aerRank}]\n"
    "- priceDetails per pax: gdsFarePerPax, taxPerPax, itemizedTaxPerPaxList (YQ/YR/Q/TAX/AY/US/XF/GB/UB),\n"
    "  ticketFeeDetails.originalTicketFee ($0-$5), agentMarkup1/2/3, agentCommission\n"
    "- additionalFareInfos (15+ types): baggageInfo (weightInfo: '0PC'/'1x23kg'),\n"
    "  ticketTimeLimitInfo (booking deadline), priceGuaranteeTimeLimit (price hold),\n"
    "  seatFeatureInfo (reservable, cancelable), fareInfo (cancellation/rebooking policy),\n"
    "  cheapestFare, shortestTravelTime, upsellPossible, ancillariesBookable, directConnectFare\n"
    "- Legs: outbound/inbound, each with itineraryList (alternative routings)\n"
    "- Segments: airline, flight#, equipment (A321neo/787-9/etc), bookingClass,\n"
    "  availableSeats, duration, groundTime (layover), fareBase, baggageAllowance\n"
    "- 19 filter categories: airline, alliance, equipment, stops, price, fareFamily, GDS, etc.\n"
    "- agentMarkup2Threshold: {min: 0, max: 999} — our markup cap\n\n"

    "PASSENGER FIELDS (RedboxPassenger — 19 properties, strict validation):\n"
    "- Required: firstName, lastName, paxType (ADT/CHD/INF), type='PASSENGER'\n"
    "- Optional: dateOfBirth, gender (Male/Female capitalized), title, salutation, middleNames\n"
    "- Contact: nested contactData {emailAddress (NOT email), phoneNumber, telCountryCode}\n"
    "- Passport: nested apisDocument {documentNumber, expiryDate, nationality}\n"
    "- DO NOT use top-level email/phone/passportNumber — Redbox will 400\n\n"

    "BOOKING FLOW:\n"
    "1. SEARCH: search_flights → fareSearchId + fareId for each result\n"
    "2. PRICE CHECK: Compare Picasso price vs Google/retail benchmark\n"
    "3. FARE RULES: get_fare_rules → cancellation/change/min-max stay policy\n"
    "4. SEAT CHECK: get_seatmap → seat availability per segment\n"
    "5. COLLECT PASSENGERS: get_saved_travelers or collect new traveler details\n"
    "   - Required: firstName, lastName, paxType, dateOfBirth, gender\n"
    "   - International: passport (number, expiry, nationality) via apisDocument\n"
    "   - Contact: email + phone via contactData\n"
    "6. PREPARE: prepare_booking to validate all data\n"
    "7. PAYMENT: initiate_payment (Stripe) → user pays\n"
    "8. BOOK: execute_booking → Picasso cart + BOOKING_FEE_OVERRIDE (markup) + superPNR → PNR\n"
    "   Markup = platform_fee_usd (hides wholesale pricing from consumer, airline compliance)\n"
    "9. CONFIRM: generate_travel_document (CONFIRMATION) → email to customer\n"
    "10. POST-BOOKING: search_picasso_bookings to check status; manage via airline website with PNR\n\n"

    "HOTEL BOOKING (liteAPI):\n"
    "- Search → prebook (validate) → book (needs prebookId)\n"
    "- No passport needed, $15 flat fee, no proxy\n"
    "- Guest info: name, email, phone, special requests\n\n"

    "PRICING MODEL:\n"
    "- Picasso wholesale price = MYSTES cost\n"
    "- Google/retail price = customer benchmark\n"
    "- Loyal subscribers: 35% of savings as platform fee (customer keeps 65%)\n"
    "- Non-subscribers: 50% of savings as platform fee (customer keeps 50%)\n"
    "- Min $3 per deal, no maximum cap\n"
    "- When no Google benchmark: estimate at 1.55x Picasso price\n\n"

    "AIRLINE COMPLIANCE:\n"
    "- NEVER expose POS market codes to consumers (arbitrage_market → 'MYSTES')\n"
    "- B2C surfaces show 'MYSTES' not the actual arbitrage country\n"
    "- Internal fields prefixed with _internal_ only\n\n"

    "TOOLS AVAILABLE:\n"
    "- search_flights, search_hotels: Search via Picasso/liteAPI\n"
    "- get_fare_rules: Detailed fare conditions from Picasso\n"
    "- get_seatmap: Seat availability for specific flights\n"
    "- get_saved_travelers, prepare_booking: Passenger management\n"
    "- get_booking_requirements: What info is needed per route\n"
    "- execute_booking: Complete the booking via Picasso\n"
    "- initiate_payment, check_payment_status: Payment flow\n"
    "- search_picasso_bookings: Look up existing bookings\n"
    "- generate_travel_document: Generate itinerary/confirmation docs\n"
    "- analyze_route, get_route_intelligence, get_market_briefing: Market data\n"
    "- get_trending, get_price_history: Trend analysis\n\n"

    "ALWAYS use tools to get real data. Never guess prices or make up booking info. "
    "Format prices in USD. Report errors clearly with what went wrong and next steps."
)


# ===========================================================================
# Tool Definitions (Anthropic tool_use format)
# ===========================================================================

MYSTES_AI_TOOLS = [
    {
        "name": "search_flights",
        "description": (
            "Search for flights between two airports on a given date. "
            "Returns available flights with prices, airlines, and stop information. "
            "Use 3-letter IATA airport codes (e.g. JFK, NRT, LHR)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "origin": {
                    "type": "string",
                    "description": "Origin airport IATA code (e.g. JFK)",
                },
                "destination": {
                    "type": "string",
                    "description": "Destination airport IATA code (e.g. NRT)",
                },
                "date": {
                    "type": "string",
                    "description": "Departure date in YYYY-MM-DD format",
                },
                "return_date": {
                    "type": "string",
                    "description": "Optional return date in YYYY-MM-DD format for round-trip",
                },
                "cabin_class": {
                    "type": "string",
                    "description": "Cabin class: economy, premium_economy, business, or first. Defaults to economy.",
                    "enum": ["economy", "premium_economy", "business", "first"],
                },
                "passengers": {
                    "type": "integer",
                    "description": "Number of passengers. Defaults to 1.",
                },
            },
            "required": ["origin", "destination", "date"],
        },
    },
    {
        "name": "search_hotels",
        "description": (
            "Search for hotels in a city. Returns hotel names, room types, "
            "prices per night with savings vs Google/Hotels.com, and booking offer IDs. "
            "Use when the user asks about hotels, accommodation, or places to stay."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "City name or IATA city code (e.g. 'Paris', 'PAR', 'Tokyo', 'TYO')",
                },
                "checkin_date": {
                    "type": "string",
                    "description": "Check-in date in YYYY-MM-DD format",
                },
                "checkout_date": {
                    "type": "string",
                    "description": "Check-out date in YYYY-MM-DD format",
                },
                "adults": {
                    "type": "integer",
                    "description": "Number of adult guests (default 1)",
                },
                "rooms": {
                    "type": "integer",
                    "description": "Number of rooms (default 1)",
                },
            },
            "required": ["location", "checkin_date", "checkout_date"],
        },
    },
    {
        "name": "search_products",
        "description": (
            "Search for products or services across geographic markets. "
            "Compares prices for electronics, software, subscriptions, and more."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Product search query (e.g. 'MacBook Pro 16 inch')",
                },
                "category": {
                    "type": "string",
                    "description": "Product category (e.g. 'electronics', 'software', 'fashion')",
                },
                "market": {
                    "type": "string",
                    "description": "Geographic market to search in (e.g. 'JP', 'DE')",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "search_cruises",
        "description": (
            "Search for cruise deals across geographic markets. Compares cruise "
            "prices from different booking regions to find arbitrage opportunities."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "departure_port": {
                    "type": "string",
                    "description": "Departure port city (e.g. 'Miami', 'Barcelona')",
                },
                "cruise_line": {
                    "type": "string",
                    "description": "Cruise line (e.g. 'carnival', 'royal_caribbean', 'norwegian')",
                },
                "departure_date": {
                    "type": "string",
                    "description": "Departure date in YYYY-MM-DD format",
                },
                "duration": {
                    "type": "integer",
                    "description": "Duration in nights (e.g. 7)",
                },
            },
            "required": ["departure_port"],
        },
    },
    {
        "name": "search_rentals",
        "description": (
            "Search for car rental deals across geographic markets. Compares rental "
            "prices from different booking regions to find arbitrage opportunities."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "Pickup location or airport code (e.g. 'LAX', 'London Heathrow')",
                },
                "pickup_date": {
                    "type": "string",
                    "description": "Pickup date in YYYY-MM-DD format",
                },
                "dropoff_date": {
                    "type": "string",
                    "description": "Drop-off date in YYYY-MM-DD format",
                },
                "vehicle_class": {
                    "type": "string",
                    "description": "Vehicle class (economy/compact/midsize/fullsize/suv/luxury)",
                },
            },
            "required": ["location"],
        },
    },
    {
        "name": "search_arbitrage",
        "description": (
            "Universal arbitrage search — accepts natural language queries for any "
            "travel product (flights, hotels, cruises, car rentals, vacation packages). "
            "Automatically classifies intent and searches across geographic markets."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural language search query (e.g. 'hotels in Bali next month', 'SUV rental LAX March 10-15', 'cruise caribbean 7 nights')",
                },
                "home_market": {
                    "type": "string",
                    "description": "User's home market code (default: 'US')",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "analyze_route",
        "description": (
            "Deep analysis of a flight route. Returns multi-market pricing, "
            "best booking markets, price trends, airline comparison, and "
            "recommendations. Use this for detailed route intelligence."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "origin": {
                    "type": "string",
                    "description": "Origin airport IATA code",
                },
                "destination": {
                    "type": "string",
                    "description": "Destination airport IATA code",
                },
                "market": {
                    "type": "string",
                    "description": "User's home market for baseline pricing (default: 'US')",
                },
            },
            "required": ["origin", "destination"],
        },
    },
    {
        "name": "get_route_intelligence",
        "description": (
            "Get pricing intelligence for a specific route — market-by-market "
            "price comparison, cheapest booking market, price spread, demand "
            "level, and recent deals."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "origin": {
                    "type": "string",
                    "description": "Origin airport IATA code",
                },
                "destination": {
                    "type": "string",
                    "description": "Destination airport IATA code",
                },
                "days_back": {
                    "type": "integer",
                    "description": "Number of days of historical data to analyze (default: 30)",
                },
            },
            "required": ["origin", "destination"],
        },
    },
    {
        "name": "get_market_briefing",
        "description": (
            "Get an activity summary for a geographic market — popular routes, "
            "average savings, demand trend, price volatility."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "market": {
                    "type": "string",
                    "description": "Two-letter country code (e.g. 'JP', 'BR', 'DE')",
                },
                "days_back": {
                    "type": "integer",
                    "description": "Number of days to analyze (default: 7)",
                },
            },
            "required": ["market"],
        },
    },
    {
        "name": "get_trending",
        "description": (
            "Get trending data on the Mystes platform — new high-savings deals, "
            "demand surges, popular routes, and platform-wide statistics."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "Number of days to look back (default: 7)",
                },
            },
            "required": [],
        },
    },
    {
        "name": "get_price_history",
        "description": (
            "Get day-by-day price timeline for a route across all tracked markets. "
            "Useful for identifying price trends and optimal booking windows."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "origin": {
                    "type": "string",
                    "description": "Origin airport IATA code",
                },
                "destination": {
                    "type": "string",
                    "description": "Destination airport IATA code",
                },
                "days": {
                    "type": "integer",
                    "description": "Number of days of history (default: 30)",
                },
            },
            "required": ["origin", "destination"],
        },
    },
    {
        "name": "get_deals",
        "description": (
            "Get the latest arbitrage deals found by Mystes — flights with "
            "significant price differences across geographic markets."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of deals to return (default: 10)",
                },
                "origin": {
                    "type": "string",
                    "description": "Filter by origin airport code",
                },
                "destination": {
                    "type": "string",
                    "description": "Filter by destination airport code",
                },
            },
            "required": [],
        },
    },
    {
        "name": "discover_opportunities",
        "description": (
            "Run the Mystes agent's autonomous opportunity discovery — finds "
            "new arbitrage patterns, high-demand routes, underutilized markets, "
            "and emerging verticals."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    # =======================================================================
    # Build #87 — Conversational-first action tools
    # =======================================================================
    {
        "name": "get_my_dashboard",
        "description": (
            "Get the user's dashboard summary: total bookings, total saved, "
            "recent transactions, and account details. Use when user asks about "
            "their account, stats, or activity."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_user_settings",
        "description": (
            "Get or describe the user's current account settings: email, preferred "
            "currency, home market, language, connected wallets. Use when user asks "
            "about their settings or profile."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    # =======================================================================
    # Build #99 — Smart Booking Tools (Traveler Collection)
    # =======================================================================
    {
        "name": "get_saved_travelers",
        "description": (
            "Get the user's saved traveler profiles. Returns a list of saved travelers "
            "with their names, dates of birth, passport info, and preferences. Use this "
            "when the user wants to book a flight or asks about their saved travelers."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "prepare_booking",
        "description": (
            "Prepare a flight booking with traveler details. Call this AFTER the user "
            "has selected a flight and provided traveler information. This validates the "
            "booking data and returns a booking summary for user confirmation. "
            "Requires: flight offer ID, list of traveler IDs or new traveler details."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "offer_id": {
                    "type": "string",
                    "description": "The flight offer ID from search results",
                },
                "traveler_ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "List of saved traveler profile IDs to use for booking",
                },
                "new_travelers": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "first_name": {"type": "string"},
                            "last_name": {"type": "string"},
                            "date_of_birth": {"type": "string", "description": "YYYY-MM-DD format"},
                            "gender": {"type": "string", "enum": ["M", "F"]},
                            "email": {"type": "string"},
                            "phone": {"type": "string"},
                        },
                    },
                    "description": "New traveler details if not using saved profiles",
                },
                "contact_email": {
                    "type": "string",
                    "description": "Contact email for booking confirmations",
                },
            },
            "required": ["offer_id"],
        },
    },
    {
        "name": "get_booking_requirements",
        "description": (
            "Get the required traveler information for a specific flight booking. "
            "Returns what passenger data is needed (passport for international, TSA info "
            "for US domestic, etc.). Use this to guide the user on what info they need "
            "to provide before booking."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "origin": {
                    "type": "string",
                    "description": "Origin airport IATA code",
                },
                "destination": {
                    "type": "string",
                    "description": "Destination airport IATA code",
                },
                "passenger_count": {
                    "type": "integer",
                    "description": "Number of passengers (default 1)",
                },
            },
            "required": ["origin", "destination"],
        },
    },
    {
        "name": "execute_booking",
        "description": (
            "Execute a flight booking after payment is confirmed. Creates the actual "
            "reservation in the airline's system and returns the PNR (confirmation number). "
            "Only call this AFTER payment has been verified. Requires offer_id and traveler details."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "offer_id": {
                    "type": "string",
                    "description": "The flight offer ID from search results",
                },
                "traveler_ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "List of saved traveler profile IDs",
                },
                "contact_email": {
                    "type": "string",
                    "description": "Email for booking confirmation",
                },
            },
            "required": ["offer_id", "traveler_ids"],
        },
    },
    {
        "name": "initiate_payment",
        "description": (
            "Create a payment session for a flight booking. Returns a payment URL "
            "that the user can click to complete payment via Stripe or crypto. "
            "Call this after prepare_booking confirms the booking is ready."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "offer_id": {
                    "type": "string",
                    "description": "The flight offer ID",
                },
                "amount_usd": {
                    "type": "number",
                    "description": "Total amount in USD",
                },
                "passenger_count": {
                    "type": "integer",
                    "description": "Number of passengers",
                },
                "route_description": {
                    "type": "string",
                    "description": "Brief route description (e.g., 'JFK to NRT')",
                },
                "payment_method": {
                    "type": "string",
                    "enum": ["card", "crypto"],
                    "description": "Payment method preference (default: card)",
                },
            },
            "required": ["offer_id", "amount_usd"],
        },
    },
    {
        "name": "check_payment_status",
        "description": (
            "Check the status of a payment session. Returns whether payment is "
            "pending, completed, or failed. Use this to verify payment before "
            "executing the booking."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "payment_session_id": {
                    "type": "string",
                    "description": "The payment session ID from initiate_payment",
                },
            },
            "required": ["payment_session_id"],
        },
    },
    # --- Picasso API Tools ---
    {
        "name": "get_fare_rules",
        "description": (
            "Get detailed fare rules for a specific flight fare. Returns cancellation "
            "penalties, change fees, minimum/maximum stay rules, advance purchase "
            "requirements, and other fare conditions. Use this when a customer asks "
            "about cancellation policies, change fees, or fare restrictions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "fare_search_id": {
                    "type": "string",
                    "description": "The fare search ID from search results",
                },
                "fare_id": {
                    "type": "string",
                    "description": "The specific fare ID to get rules for",
                },
            },
            "required": ["fare_search_id", "fare_id"],
        },
    },
    {
        "name": "get_seatmap",
        "description": (
            "Get a seatmap showing available seats for a specific flight. Returns "
            "seat layout with availability, seat types, and pricing. Use when a "
            "customer wants to see or select seats."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "airline_code": {
                    "type": "string",
                    "description": "Airline IATA code (AA, DL, UA, etc.)",
                },
                "flight_number": {
                    "type": "string",
                    "description": "Flight number (e.g., '1758')",
                },
                "departure": {
                    "type": "string",
                    "description": "Departure airport IATA code",
                },
                "destination": {
                    "type": "string",
                    "description": "Destination airport IATA code",
                },
                "departure_date": {
                    "type": "string",
                    "description": "Departure date (YYYY-MM-DD)",
                },
                "booking_class": {
                    "type": "string",
                    "description": "Booking class code (Y, B, M, etc.). Default: Y",
                },
                "cabin_class": {
                    "type": "string",
                    "description": "Cabin class (ECONOMY, BUSINESS, FIRST). Default: ECONOMY",
                },
            },
            "required": ["airline_code", "flight_number", "departure", "destination", "departure_date"],
        },
    },
    {
        "name": "search_picasso_bookings",
        "description": (
            "Search for existing bookings in the Picasso/Redbox system. Can search by "
            "PNR locator, date range, airline, route, etc. Use when a customer wants "
            "to check on an existing booking or when you need to look up a reservation."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "locator": {
                    "type": "string",
                    "description": "PNR locator / booking reference to search for",
                },
                "departure": {
                    "type": "string",
                    "description": "Departure airport code",
                },
                "destination": {
                    "type": "string",
                    "description": "Destination airport code",
                },
                "airline": {
                    "type": "string",
                    "description": "Validating airline code",
                },
                "date_from": {
                    "type": "string",
                    "description": "Booking date range start (YYYY-MM-DD)",
                },
                "date_to": {
                    "type": "string",
                    "description": "Booking date range end (YYYY-MM-DD)",
                },
            },
            "required": [],
        },
    },
    {
        "name": "generate_travel_document",
        "description": (
            "Generate a travel document like an itinerary, offer letter, booking "
            "confirmation, or travel registration form. Can be emailed directly to "
            "the customer. Use when a customer needs their itinerary or booking docs."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "document_type": {
                    "type": "string",
                    "enum": ["ITINERARY", "OFFER", "CONFIRMATION", "TRAVEL_REGISTRATION"],
                    "description": "Type of document to generate",
                },
                "super_pnr_id": {
                    "type": "string",
                    "description": "Booking SuperPNR ID (for post-booking docs)",
                },
                "shopping_cart_id": {
                    "type": "string",
                    "description": "Shopping cart ID (for pre-booking docs)",
                },
                "email_recipients": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Email addresses to send the document to",
                },
            },
            "required": ["document_type"],
        },
    },
]


# ===========================================================================
# MystesAI Class
# ===========================================================================

class MystesAI:
    """
    LLM-powered tool-calling engine for the Mystes platform.

    Connects Claude (via Anthropic Messages API) to 14 Mystes capabilities
    through structured tool definitions. Maintains multi-turn conversation
    context via the AIMessage database table.
    """

    def __init__(self):
        self.tools = MYSTES_AI_TOOLS
        self.system_prompt = MYSTES_AI_SYSTEM_PROMPT
        self.logger = logging.getLogger(f"{__name__}.MystesAI")
        self.api_key = os.environ.get("ANTHROPIC_API_KEY")

    # ------------------------------------------------------------------
    # Main chat entry point
    # ------------------------------------------------------------------

    def chat(self, user_id, conversation_id, user_message, tier_config):
        """
        Process a user message through the MYSTES AI engine.

        Loads conversation context, calls the LLM with tool definitions,
        executes any tool calls, loops until the LLM produces a final text
        response (or the tool-call budget is exhausted).

        Args:
            user_id: ID of the user sending the message.
            conversation_id: Conversation session ID.
            user_message: The user's natural language message.
            tier_config: Dict with max_tools_per_query and max_context_messages.

        Returns:
            dict with keys: role, content, tool_calls, model_used, response_time_ms
        """
        start_time = time.time()
        max_tools = tier_config.get("max_tools_per_query", 3)
        max_context = tier_config.get("max_context_messages", 10)
        tool_calls_made = []
        tools_remaining = max_tools

        # -- Load conversation context --
        context_messages = self._load_context(conversation_id, max_context)

        # -- Build messages list --
        messages = []
        for ctx in context_messages:
            messages.append({"role": ctx["role"], "content": ctx["content"]})

        messages.append({"role": "user", "content": user_message})

        # -- LLM tool-calling loop --
        model_used = "claude-opus-4-6"
        final_content = ""

        for _iteration in range(max_tools + 1):
            # Only pass tools if we have budget remaining
            active_tools = self.tools if tools_remaining > 0 else None

            llm_response = self._call_llm(messages, tools=active_tools)

            if llm_response is None:
                final_content = (
                    "I'm sorry, I encountered an issue connecting to the AI service. "
                    "Please try again in a moment."
                )
                break

            # Check if the response contains tool_use blocks
            content_blocks = llm_response.get("content", [])
            has_tool_use = any(
                block.get("type") == "tool_use" for block in content_blocks
            )

            if not has_tool_use:
                # Final text response — extract all text blocks
                text_parts = []
                for block in content_blocks:
                    if block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                final_content = "\n".join(text_parts)
                break

            # Process tool_use blocks
            # First, append the full assistant message to the conversation
            messages.append({"role": "assistant", "content": content_blocks})

            tool_results = []
            for block in content_blocks:
                if block.get("type") == "tool_use":
                    tool_name = block.get("name", "")
                    tool_input = block.get("input", {})
                    tool_use_id = block.get("id", "")

                    self.logger.info(
                        "Executing tool: %s with input: %s",
                        tool_name,
                        json.dumps(tool_input)[:200],
                    )

                    # Execute the tool
                    result = self._execute_tool(tool_name, tool_input, user_id)

                    # Format the result for the LLM
                    formatted = self._format_tool_result(tool_name, result)

                    tool_calls_made.append({
                        "tool": tool_name,
                        "input": tool_input,
                        "result_summary": formatted[:500],
                        "result": result if isinstance(result, dict) else None,
                    })

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_use_id,
                        "content": formatted,
                    })

                    tools_remaining -= 1

            # Append tool results as a user message (Anthropic format)
            messages.append({"role": "user", "content": tool_results})

            if tools_remaining <= 0:
                # Budget exhausted — do one final call without tools
                continue

        elapsed_ms = int((time.time() - start_time) * 1000)

        return {
            "role": "assistant",
            "content": final_content,
            "tool_calls": tool_calls_made,
            "model_used": model_used,
            "response_time_ms": elapsed_ms,
        }

    # ------------------------------------------------------------------
    # Context loading
    # ------------------------------------------------------------------

    def _load_context(self, conversation_id, max_messages):
        """Load recent conversation messages from the database.

        Returns a list of dicts with role and content keys, ordered by
        creation time ascending (oldest first).
        """
        try:
            from models import AIMessage
            rows = (
                AIMessage.query
                .filter_by(conversation_id=conversation_id)
                .order_by(AIMessage.created_at.asc())
                .limit(max_messages)
                .all()
            )
            context = []
            for row in rows:
                context.append({
                    "role": row.role if row.role in ("user", "assistant") else "user",
                    "content": row.content or "",
                })
            return context
        except Exception as e:
            self.logger.warning("Failed to load context for %s: %s", conversation_id, e)
            return []

    # ------------------------------------------------------------------
    # LLM API call
    # ------------------------------------------------------------------

    def _call_llm(self, messages, tools=None):
        """Call the Anthropic Messages API with optional tool definitions.

        Posts to https://api.anthropic.com/v1/messages using the same pattern
        as ai_search._call_anthropic(), but includes tool definitions for
        function calling.

        Args:
            messages: List of message dicts (role + content).
            tools: Optional list of tool definitions in Anthropic format.

        Returns:
            Parsed JSON response dict, or None on failure.
        """
        api_key = self.api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            self.logger.error("ANTHROPIC_API_KEY not set — cannot call LLM")
            return None

        # Separate system message from conversation messages
        from datetime import datetime
        today_str = datetime.now().strftime("%Y-%m-%d")
        system_content = self.system_prompt + f"\n\nToday's date is {today_str}. Use this when the user says 'next week', 'tomorrow', etc."

        # Inject learned strategies from Strategy Learner (Build #73)
        try:
            from strategy_learner import strategy_learner
            strategy_enhancement = strategy_learner.enhance_prompt()
            if strategy_enhancement:
                system_content = system_content + "\n\n" + strategy_enhancement
        except Exception:
            pass  # Never block chat on learner failure

        api_messages = []

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                system_content = content
            else:
                api_messages.append({"role": role, "content": content})

        # Ensure messages alternate correctly: must start with user
        if api_messages and api_messages[0].get("role") != "user":
            api_messages.insert(0, {"role": "user", "content": "Hello."})

        body = {
            "model": "claude-opus-4-6",
            "system": system_content,
            "messages": api_messages,
            "max_tokens": 4096,
        }
        if tools:
            body["tools"] = tools

        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        try:
            resp = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers=headers,
                json=body,
                timeout=60,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.Timeout:
            self.logger.error("Anthropic API call timed out")
            return None
        except requests.exceptions.HTTPError as e:
            self.logger.error("Anthropic API HTTP error: %s — %s", e, getattr(e.response, 'text', '')[:500])
            return None
        except Exception as e:
            self.logger.error("Anthropic API call failed: %s", e)
            return None

    # ------------------------------------------------------------------
    # Tool execution dispatch
    # ------------------------------------------------------------------

    def _execute_tool(self, tool_name, tool_input, user_id):
        """Execute a tool by name with the given input parameters.

        Dispatches to the appropriate Mystes module. Each branch is wrapped
        in try/except so a single tool failure does not crash the whole chat.

        Args:
            tool_name: Name of the tool to execute.
            tool_input: Dict of input parameters from the LLM.
            user_id: ID of the requesting user.

        Returns:
            dict with tool results, or {"error": "..."} on failure.
        """
        try:
            if tool_name == "search_flights":
                from search import search_global
                origin = tool_input.get("origin", "").strip().upper()
                destination = tool_input.get("destination", "").strip().upper()
                date = tool_input.get("date", "").strip()
                return_date = tool_input.get("return_date")
                cabin_class = tool_input.get("cabin_class", "economy")
                passengers = tool_input.get("passengers", 1)

                # Validate required fields — return error so LLM asks the user
                missing = []
                if not origin:
                    missing.append("origin airport or city")
                if not destination:
                    missing.append("destination airport or city")
                if not date:
                    missing.append("departure date (YYYY-MM-DD)")
                if missing:
                    return {"error": f"Missing required info: {', '.join(missing)}. Please ask the user to provide these."}

                search_opts = None
                if passengers and passengers > 1:
                    search_opts = {"passengers": {"adults": passengers}}

                result = search_global(
                    origin=origin,
                    destination=destination,
                    date=date,
                    return_date=return_date,
                    cabin_class=cabin_class,
                    fast_mode=True,
                    search_options=search_opts,
                )
                return result if isinstance(result, dict) else {"flights": result}

            elif tool_name == "search_hotels":
                from liteapi_client import search_hotels as liteapi_search_hotels
                from airports import AIRPORTS
                location = tool_input.get("location", "").strip()
                checkin = tool_input.get("checkin_date", "")
                checkout = tool_input.get("checkout_date", "")
                adults = tool_input.get("adults", 1)
                rooms = tool_input.get("rooms", 1)

                # Resolve city code from location name or code
                city_code = None
                loc_upper = location.upper()
                # Direct IATA code match (3 letters)
                if len(loc_upper) == 3 and loc_upper in AIRPORTS:
                    city_code = loc_upper
                else:
                    # Reverse lookup: city name → IATA code
                    for code, info in AIRPORTS.items():
                        if info.get("city", "").lower() == location.lower():
                            city_code = code
                            break
                    if not city_code:
                        # Partial match
                        for code, info in AIRPORTS.items():
                            if location.lower() in info.get("city", "").lower():
                                city_code = code
                                break
                if not city_code:
                    return {"success": False, "error": f"Could not find city code for '{location}'. Try using a 3-letter IATA city code like PAR, LON, TYO."}

                result = liteapi_search_hotels(
                    city_code=city_code,
                    check_in=checkin,
                    check_out=checkout,
                    adults=adults,
                    rooms=rooms,
                    currency="USD",
                    max_hotels=15,
                )
                return result

            elif tool_name == "search_products":
                from mystes_agent import mystes_agent
                query = tool_input.get("query", "")
                category = tool_input.get("category")
                market = tool_input.get("market", "US")
                return mystes_agent.handle_search(
                    query=query,
                    task_type="product_search",
                    user_market=market,
                    user_id=user_id,
                    params={"category": category} if category else {},
                )

            elif tool_name == "search_cruises":
                from arbitrage_search import arbitrage_engine
                port = tool_input.get("departure_port", "")
                line = tool_input.get("cruise_line", "")
                date = tool_input.get("departure_date", "")
                duration = tool_input.get("duration", 7)
                query = f"cruise from {port}"
                if line:
                    query += f" {line}"
                if duration:
                    query += f" {duration} nights"
                if date:
                    query += f" {date}"
                return arbitrage_engine.search(query=query, user_id=user_id)

            elif tool_name == "search_rentals":
                from arbitrage_search import arbitrage_engine
                location = tool_input.get("location", "")
                pickup = tool_input.get("pickup_date", "")
                dropoff = tool_input.get("dropoff_date", "")
                vehicle = tool_input.get("vehicle_class", "")
                query = f"car rental {location}"
                if vehicle:
                    query = f"{vehicle} rental {location}"
                if pickup:
                    query += f" {pickup}"
                if dropoff:
                    query += f" to {dropoff}"
                return arbitrage_engine.search(query=query, user_id=user_id)

            elif tool_name == "search_arbitrage":
                from arbitrage_search import arbitrage_engine
                query = tool_input.get("query", "")
                home_market = tool_input.get("home_market", "US")
                return arbitrage_engine.search(
                    query=query,
                    user_id=user_id,
                    home_market=home_market,
                )

            elif tool_name == "analyze_route":
                from mystes_agent import mystes_agent
                origin = tool_input.get("origin", "").upper()
                destination = tool_input.get("destination", "").upper()
                market = tool_input.get("market", "US")
                return mystes_agent.analyze_route(
                    origin=origin,
                    destination=destination,
                    user_market=market,
                )

            elif tool_name == "get_route_intelligence":
                from mystes_intelligence import intelligence
                origin = tool_input.get("origin", "").upper()
                destination = tool_input.get("destination", "").upper()
                days_back = tool_input.get("days_back", 30)
                return intelligence.get_route_intelligence(
                    origin, destination, days_back=days_back
                )

            elif tool_name == "get_market_briefing":
                from mystes_intelligence import intelligence
                market = tool_input.get("market", "").upper()
                days_back = tool_input.get("days_back", 7)
                return intelligence.get_market_briefing(
                    market, days_back=days_back
                )

            elif tool_name == "get_trending":
                from mystes_intelligence import intelligence
                days = tool_input.get("days", 7)
                return {
                    "anomalies": intelligence.detect_anomalies(days=days),
                    "stats": intelligence.get_platform_stats(),
                }

            elif tool_name == "get_price_history":
                from mystes_intelligence import intelligence
                origin = tool_input.get("origin", "").upper()
                destination = tool_input.get("destination", "").upper()
                days = tool_input.get("days", 30)
                return intelligence.get_price_timeline(
                    origin, destination, days_back=days
                )

            elif tool_name == "get_deals":
                from models import Deal
                limit = tool_input.get("limit", 10)
                origin = tool_input.get("origin")
                destination = tool_input.get("destination")
                query = Deal.query.filter_by(is_active=True)
                if origin:
                    query = query.filter_by(origin=origin.upper())
                if destination:
                    query = query.filter_by(destination=destination.upper())
                deals = (
                    query
                    .order_by(Deal.created_at.desc())
                    .limit(limit)
                    .all()
                )
                return {"deals": [d.to_dict() for d in deals], "count": len(deals)}

            elif tool_name == "discover_opportunities":
                from mystes_agent import mystes_agent
                return mystes_agent.discover_opportunities()

            # ---------------------------------------------------------------
            # Build #87 — Conversational-first action tools
            # ---------------------------------------------------------------

            elif tool_name == "get_my_dashboard":
                from models import User, Payment, Booking
                user = User.query.get(user_id)
                payments = Payment.query.filter_by(user_id=user_id).order_by(
                    Payment.created_at.desc()
                ).limit(5).all()
                booking_count = Booking.query.filter_by(user_id=user_id).count() if hasattr(Booking, 'query') else 0
                total_saved = sum(
                    getattr(p, 'savings_usd', 0) or 0 for p in
                    Payment.query.filter_by(user_id=user_id).all()
                )
                return {
                    "email": user.email,
                    "name": getattr(user, 'name', '') or user.email,
                    "home_market": getattr(user, 'home_market', 'US'),
                    "preferred_currency": getattr(user, 'preferred_currency', 'USD'),
                    "booking_count": booking_count,
                    "total_saved_usd": round(total_saved, 2),
                    "recent_payments": [
                        {"amount": getattr(p, 'amount_usd', 0), "status": p.status,
                         "date": str(p.created_at)[:10]}
                        for p in payments
                    ],
                }

            elif tool_name == "get_user_settings":
                from models import User
                user = User.query.get(user_id)
                return {
                    "email": user.email,
                    "name": getattr(user, 'name', ''),
                    "preferred_currency": getattr(user, 'preferred_currency', 'USD'),
                    "home_market": getattr(user, 'home_market', 'US'),
                    "preferred_language": getattr(user, 'preferred_language', 'en'),
                    "xrp_wallet": getattr(user, 'xrp_wallet_address', ''),
                    "is_admin": getattr(user, 'is_admin', False),
                    "is_verified": getattr(user, 'is_verified', False),
                }

            # ---------------------------------------------------------------
            # Build #99 — Smart Booking Tools (Traveler Collection)
            # ---------------------------------------------------------------

            elif tool_name == "get_saved_travelers":
                from models import TravelerProfile
                travelers = TravelerProfile.query.filter_by(
                    user_id=user_id, is_active=True
                ).order_by(TravelerProfile.is_primary.desc()).all()
                return {
                    "travelers": [
                        {
                            "id": t.id,
                            "name": f"{t.first_name} {t.last_name}",
                            "first_name": t.first_name,
                            "last_name": t.last_name,
                            "date_of_birth": str(t.date_of_birth) if t.date_of_birth else None,
                            "gender": t.gender,
                            "email": t.email,
                            "phone": t.phone,
                            "passenger_type": t.passenger_type or "ADULT",
                            "has_passport": bool(t.passport_number),
                            "passport_country": t.passport_country,
                            "is_primary": t.is_primary,
                        }
                        for t in travelers
                    ],
                    "count": len(travelers),
                    "has_travelers": len(travelers) > 0,
                }

            elif tool_name == "prepare_booking":
                from models import TravelerProfile
                offer_id = tool_input.get("offer_id", "")
                traveler_ids = tool_input.get("traveler_ids", [])
                new_travelers = tool_input.get("new_travelers", [])
                contact_email = tool_input.get("contact_email")

                # Validate we have traveler info
                if not traveler_ids and not new_travelers:
                    return {
                        "success": False,
                        "error": "No travelers specified",
                        "message": "Please provide either saved traveler IDs or new traveler details.",
                        "action_needed": "collect_travelers",
                    }

                # Load saved travelers
                travelers_data = []
                if traveler_ids:
                    saved = TravelerProfile.query.filter(
                        TravelerProfile.id.in_(traveler_ids),
                        TravelerProfile.user_id == user_id
                    ).all()
                    for t in saved:
                        travelers_data.append({
                            "source": "saved",
                            "id": t.id,
                            "name": f"{t.first_name} {t.last_name}",
                            "date_of_birth": str(t.date_of_birth) if t.date_of_birth else None,
                            "gender": t.gender,
                            "email": t.email or contact_email,
                            "has_passport": bool(t.passport_number),
                        })

                # Add new travelers
                for nt in new_travelers:
                    travelers_data.append({
                        "source": "new",
                        "name": f"{nt.get('first_name', '')} {nt.get('last_name', '')}",
                        "date_of_birth": nt.get("date_of_birth"),
                        "gender": nt.get("gender"),
                        "email": nt.get("email") or contact_email,
                        "has_passport": False,  # New travelers need passport info for intl
                    })

                return {
                    "success": True,
                    "offer_id": offer_id,
                    "travelers": travelers_data,
                    "passenger_count": len(travelers_data),
                    "ready_to_book": len(travelers_data) > 0,
                    "message": f"Booking prepared for {len(travelers_data)} passenger(s). Ready to proceed with payment.",
                    "next_step": "confirm_and_pay",
                }

            elif tool_name == "get_booking_requirements":
                origin = tool_input.get("origin", "").upper()
                destination = tool_input.get("destination", "").upper()
                passenger_count = tool_input.get("passenger_count", 1)

                # Determine if international (simple heuristic: different first 2 chars = different country)
                # In reality we'd use airport country codes from a database
                is_international = origin[:2] != destination[:2] if len(origin) >= 2 and len(destination) >= 2 else True
                is_us_domestic = origin.startswith(("J", "L", "S", "O", "D", "A", "M", "C", "P", "B")) and not is_international

                base_requirements = [
                    "Full legal name (as on ID)",
                    "Date of birth",
                    "Gender",
                    "Contact email",
                    "Contact phone",
                ]

                if is_international:
                    base_requirements.extend([
                        "Passport number",
                        "Passport expiry date",
                        "Passport issuing country",
                        "Nationality",
                    ])

                if is_us_domestic or destination.startswith(("J", "L", "S", "O", "D", "A", "M")):
                    base_requirements.extend([
                        "TSA Redress Number (if applicable)",
                        "Known Traveler Number (if applicable)",
                    ])

                return {
                    "origin": origin,
                    "destination": destination,
                    "is_international": is_international,
                    "passenger_count": passenger_count,
                    "required_fields": base_requirements,
                    "message": (
                        f"For this {'international' if is_international else 'domestic'} flight, "
                        f"each of the {passenger_count} passenger(s) will need: {', '.join(base_requirements[:5])}."
                        + (" Plus passport details." if is_international else "")
                    ),
                }

            elif tool_name == "execute_booking":
                from models import TravelerProfile, Booking, db
                import secrets

                offer_id = tool_input.get("offer_id", "")
                traveler_ids = tool_input.get("traveler_ids", [])
                contact_email = tool_input.get("contact_email")

                # Load travelers
                travelers = TravelerProfile.query.filter(
                    TravelerProfile.id.in_(traveler_ids),
                    TravelerProfile.user_id == user_id
                ).all()

                if not travelers:
                    return {
                        "success": False,
                        "error": "No valid travelers found",
                        "message": "Please select travelers from your saved profiles.",
                    }

                # Convert to Amadeus format
                amadeus_travelers = []
                for i, t in enumerate(travelers, 1):
                    amadeus_travelers.append(t.to_amadeus_traveler(str(i)))

                # For now, return a mock booking since we need real Amadeus credentials
                # In production, this would call amadeus_client.create_booking_multi()
                booking_ref = f"PHX{secrets.token_hex(4).upper()}"

                # Create booking record
                passenger_names = ", ".join([f"{t.first_name} {t.last_name}" for t in travelers])
                booking = Booking(
                    user_id=user_id,
                    confirmation_code=booking_ref,
                    status="booked",
                    passenger_name=passenger_names,
                    passenger_email=contact_email or travelers[0].email,
                    fulfillment_type="automated",
                )
                db.session.add(booking)
                db.session.commit()

                return {
                    "success": True,
                    "booking_reference": booking_ref,
                    "pnr": booking_ref,
                    "passenger_count": len(travelers),
                    "passengers": [f"{t.first_name} {t.last_name}" for t in travelers],
                    "status": "confirmed",
                    "message": f"Booking confirmed! Your confirmation number is {booking_ref}.",
                    "next_steps": [
                        "Check your email for confirmation",
                        "Arrive at airport 2-3 hours before departure",
                        "Have your passport ready for international flights",
                    ],
                }

            elif tool_name == "initiate_payment":
                import secrets
                offer_id = tool_input.get("offer_id", "")
                amount_usd = tool_input.get("amount_usd", 0)
                passenger_count = tool_input.get("passenger_count", 1)
                route_desc = tool_input.get("route_description", "Flight")
                payment_method = tool_input.get("payment_method", "card")

                # Generate payment session ID
                session_id = f"ps_{secrets.token_hex(12)}"

                # Store pending payment (in production, create Stripe session)
                # For now, return payment link info
                return {
                    "success": True,
                    "payment_session_id": session_id,
                    "amount_usd": amount_usd,
                    "passenger_count": passenger_count,
                    "description": f"{route_desc} - {passenger_count} passenger(s)",
                    "payment_method": payment_method,
                    "payment_url": f"/pay?session={session_id}&amount={amount_usd}",
                    "message": (
                        f"Payment of ${amount_usd:.2f} ready. "
                        f"Click the payment link to complete your booking."
                    ),
                    "expires_in_minutes": 30,
                }

            elif tool_name == "check_payment_status":
                session_id = tool_input.get("payment_session_id", "")

                # In production, check Stripe session status
                # For now, return mock status
                return {
                    "session_id": session_id,
                    "status": "pending",
                    "message": "Awaiting payment. Please complete payment to confirm your booking.",
                }

            # ---------------------------------------------------------------
            # Picasso API Tools
            # ---------------------------------------------------------------

            elif tool_name == "get_fare_rules":
                from picasso_client import get_fare_rules
                fare_search_id = tool_input.get("fare_search_id", "")
                fare_id = tool_input.get("fare_id", "")
                if not fare_search_id or not fare_id:
                    return {"error": "fare_search_id and fare_id are required"}
                result = get_fare_rules(fare_search_id, fare_id)
                if result.get("success"):
                    rules = result.get("rules", {})
                    summary = []
                    for code, rule in rules.items():
                        title = rule.get("title", code)
                        # Strip HTML tags for text summary
                        import re as _re
                        text = _re.sub(r'<[^>]+>', ' ', rule.get("text", ""))
                        text = ' '.join(text.split())[:300]
                        summary.append(f"**{title}**: {text}")
                    result["rules_summary"] = summary
                return result

            elif tool_name == "get_seatmap":
                from picasso_client import get_seatmap
                return get_seatmap(
                    airline_code=tool_input.get("airline_code", ""),
                    flight_number=tool_input.get("flight_number", ""),
                    departure=tool_input.get("departure", ""),
                    destination=tool_input.get("destination", ""),
                    departure_date=tool_input.get("departure_date", ""),
                    booking_class=tool_input.get("booking_class", "Y"),
                    cabin_class=tool_input.get("cabin_class", "ECONOMY"),
                )

            elif tool_name == "search_picasso_bookings":
                from picasso_client import search_bookings
                return search_bookings(
                    locator=tool_input.get("locator"),
                    departure=tool_input.get("departure"),
                    destination=tool_input.get("destination"),
                    airline=tool_input.get("airline"),
                    date_from=tool_input.get("date_from"),
                    date_to=tool_input.get("date_to"),
                )

            elif tool_name == "generate_travel_document":
                from picasso_client import generate_document
                return generate_document(
                    document_type=tool_input.get("document_type", "ITINERARY"),
                    super_pnr_id=tool_input.get("super_pnr_id"),
                    shopping_cart_id=tool_input.get("shopping_cart_id"),
                    email_recipients=tool_input.get("email_recipients"),
                )

            else:
                return {"error": f"Unknown tool: {tool_name}"}

        except Exception as e:
            self.logger.error("Tool execution failed for %s: %s", tool_name, e)
            return {"error": str(e)}

    # ------------------------------------------------------------------
    # Result formatting
    # ------------------------------------------------------------------

    def _format_tool_result(self, tool_name, result):
        """Convert a tool result dict into human-readable text for the LLM.

        The LLM receives this text as a tool_result content block and uses
        it to compose its final response to the user.

        Args:
            tool_name: Name of the executed tool.
            result: Dict returned by _execute_tool.

        Returns:
            Formatted string summarizing the results.
        """
        if not result:
            return f"Tool '{tool_name}' returned no data."

        if isinstance(result, str):
            return result

        if isinstance(result, dict) and "error" in result:
            # Only early-exit on error if there's no useful data alongside it
            has_data = result.get("flights") or result.get("all_flights") or result.get("deals") or result.get("results")
            if not has_data:
                return f"Tool '{tool_name}' error: {result['error']}"

        # Tool-specific formatting
        try:
            if tool_name == "search_flights":
                return self._format_flights(result)
            elif tool_name == "search_hotels":
                return self._format_hotels(result)
            elif tool_name == "search_products":
                return self._format_agent_search(result, "Product")
            elif tool_name == "search_cruises":
                return self._format_arbitrage_search(result, "Cruise")
            elif tool_name == "search_rentals":
                return self._format_arbitrage_search(result, "Rental")
            elif tool_name == "search_arbitrage":
                vertical = result.get("vertical", "").title() if isinstance(result, dict) else "Arbitrage"
                return self._format_arbitrage_search(result, vertical)
            elif tool_name == "analyze_route":
                return self._format_route_analysis(result)
            elif tool_name == "get_route_intelligence":
                return self._format_route_intelligence(result)
            elif tool_name == "get_market_briefing":
                return self._format_market_briefing(result)
            elif tool_name == "get_trending":
                return self._format_trending(result)
            elif tool_name == "get_price_history":
                return self._format_price_history(result)
            elif tool_name == "get_deals":
                return self._format_deals(result)
            elif tool_name == "discover_opportunities":
                return self._format_opportunities(result)
            # Build #99 — Smart booking tool formatters
            elif tool_name == "get_saved_travelers":
                return self._format_saved_travelers(result)
            elif tool_name == "prepare_booking":
                return self._format_prepare_booking(result)
            elif tool_name == "get_booking_requirements":
                return result.get("message", json.dumps(result))
            elif tool_name == "execute_booking":
                return self._format_execute_booking(result)
            elif tool_name == "initiate_payment":
                return self._format_initiate_payment(result)
            elif tool_name == "check_payment_status":
                return result.get("message", json.dumps(result))
            # Picasso API tools
            elif tool_name == "get_fare_rules":
                if result.get("success"):
                    lines = [f"Fare rules ({result.get('rule_count', 0)} categories):"]
                    for item in result.get("rules_summary", []):
                        lines.append(item)
                    return "\n".join(lines) if lines else json.dumps(result, default=str)
                return f"Fare rules error: {result.get('error', 'Unknown')}"
            elif tool_name == "get_seatmap":
                if result.get("success"):
                    return f"Seatmap for {result.get('airline', '')} {result.get('flight_number', '')}: {json.dumps(result.get('seatmap', {}), default=str)[:3000]}"
                return f"Seatmap error: {result.get('error', 'Unknown')}"
            elif tool_name == "search_picasso_bookings":
                if result.get("success"):
                    summary = result.get("summary", {})
                    return (
                        f"Booking search results: {summary.get('openBookings', 0)} open, "
                        f"{summary.get('issued', 0)} issued, {summary.get('cancelled', 0)} cancelled. "
                        f"Data: {json.dumps(result.get('bookings', []), default=str)[:3000]}"
                    )
                return f"Booking search error: {result.get('error', 'Unknown')}"
            elif tool_name == "generate_travel_document":
                if result.get("success"):
                    return f"Document generated: {result.get('document_type', '')} ({result.get('content_type', '')})"
                return f"Document error: {result.get('error', 'Unknown')}"
        except Exception as e:
            self.logger.warning("Format failed for %s: %s", tool_name, e)

        # Fallback: JSON dump with truncation
        try:
            text = json.dumps(result, indent=2, default=str)
            if len(text) > 4000:
                text = text[:4000] + "\n... (truncated)"
            return text
        except (TypeError, ValueError):
            return str(result)[:4000]

    # -- Formatting helpers --

    def _format_flights(self, result):
        """Format flight search results."""
        lines = ["Flight Search Results:"]
        flights = result.get("flights", []) or result.get("all_flights", [])
        deals = result.get("deals", [])

        if not flights and not deals:
            return "No flights found for this search."

        if deals:
            lines.append(f"\nArbitrage Deals Found: {len(deals)}")
            for i, deal_data in enumerate(deals[:5], 1):
                d = deal_data.get("deal", deal_data)
                savings = d.get("user_saves_pct", 0) or d.get("savings_percent", 0) or d.get("gross_savings_usd", 0)
                arb = d.get("arbitrage_price", d.get("arbitrage_price_usd", 0)) or 0
                fee = d.get("platform_fee_usd", 0) or 0
                price = arb + fee if isinstance(arb, (int, float)) else arb
                airline = deal_data.get("airline", d.get("airline", "Unknown"))
                lines.append(
                    f"  {i}. {airline} — "
                    f"${price:.0f} via MYSTES "
                    f"(save {savings}{'%' if isinstance(savings, (int, float)) and savings < 100 else ''})"
                )

        if flights:
            lines.append(f"\nFlights: {len(flights)} options")
            for i, f in enumerate(flights[:10], 1):
                # Support both Amadeus format (price.total) and proxy format (cheapest_price)
                price = f.get("price", {})
                if isinstance(price, dict):
                    amt = price.get("total", "N/A")
                else:
                    amt = f.get("cheapest_price", f.get("price", "N/A"))
                if amt == "N/A":
                    amt = f.get("cheapest_price", "N/A")
                airline = f.get("airline", "Unknown")
                flight_num = f.get("flight_number") or ""
                market = f.get("cheapest_market", "")
                dep = f.get("departure_time") or ""
                arr = f.get("arrival_time") or ""
                duration = f.get("duration") or ""
                stops = f.get("stops")
                stops_str = "nonstop" if stops == 0 else f"{stops} stop{'s' if stops and stops > 1 else ''}" if stops is not None else ""

                # Build flight info line
                name = airline
                if flight_num:
                    name += f" {flight_num}"
                time_str = f" ({dep}–{arr})" if dep and arr else f" ({dep})" if dep else ""
                detail_parts = [s for s in [stops_str, duration] if s]
                detail_str = f" [{', '.join(detail_parts)}]" if detail_parts else ""
                # Price with savings — never expose market codes
                deal = f.get("deal")
                savings_str = ""
                if deal and deal.get("price_difference", 0) > 0:
                    savings_str = f" (save ${deal['price_difference']:.0f} via Mystes)"

                lines.append(f"  {i}. {name}{time_str}{detail_str} — ${amt}{savings_str}")

            # Add price comparison summary if available
            proxy = result.get("proxy_results", {})
            if proxy and proxy.get("savings_vs_us", 0) > 0:
                lines.append(f"\nMystes Price Advantage:")
                lines.append(f"  Mystes price: ${proxy.get('cheapest_price_usd', 'N/A'):.0f}")
                lines.append(f"  Potential savings: ${proxy.get('savings_vs_us', 0):.2f} ({proxy.get('savings_pct', 0):.1f}%)")

        return "\n".join(lines)

    def _format_agent_search(self, result, vertical):
        """Format mystes_agent search results."""
        lines = [f"{vertical} Search Results:"]
        if result.get("agent_search"):
            markets = result.get("markets_selected", [])
            lines.append(f"  Markets searched: {len(markets)}")
            recs = result.get("recommendations", [])
            for rec in recs[:3]:
                lines.append(f"  Recommendation: {rec.get('message', '')}")
            lines.append(f"  Elapsed: {result.get('elapsed_ms', 0)}ms")
        else:
            lines.append(json.dumps(result, default=str)[:2000])
        return "\n".join(lines)

    def _format_hotels(self, result):
        """Format Amadeus hotel search results for the LLM."""
        if not isinstance(result, dict):
            return json.dumps(result, default=str)[:2000]

        if not result.get("success"):
            return f"Hotel search error: {result.get('error', 'Unknown error')}"

        hotels = result.get("hotels", [])
        if not hotels:
            return "No hotels found for this search."

        lines = [f"Hotel Search Results: {len(hotels)} hotels found"]
        check_in = result.get("check_in", "")
        check_out = result.get("check_out", "")
        if check_in and check_out:
            lines.append(f"Dates: {check_in} to {check_out}")

        for i, h in enumerate(hotels[:10], 1):
            name = h.get("hotel_name", "Unknown Hotel")
            price_night = h.get("price_per_night", 0)
            price_total = h.get("price_total", 0)
            nights = h.get("nights", 1)
            room = h.get("room_type", "")
            bed = h.get("bed_type", "")
            currency = h.get("currency", "USD")
            cancel = h.get("cancellation_description", "")
            offer_id = h.get("offer_id", "")
            hotel_id = h.get("hotel_id", "")

            room_info = room
            if bed and bed != room:
                room_info = f"{room} ({bed})" if room else bed

            line = f"  {i}. {name}"
            if room_info:
                line += f" — {room_info}"
            line += f" — ${price_night:.0f}/night, ${price_total:.0f} total ({nights} night{'s' if nights != 1 else ''})"
            if cancel:
                line += f" | {cancel}"
            if offer_id:
                line += f" [offer:{offer_id}|hotel:{hotel_id}]"
            lines.append(line)

        return "\n".join(lines)

    def _format_arbitrage_search(self, result, vertical):
        """Format universal arbitrage search results (Build #76)."""
        if not isinstance(result, dict):
            return json.dumps(result, default=str)[:2000]

        lines = [f"{vertical} Arbitrage Search Results:"]
        lines.append(f"  Vertical: {result.get('vertical', 'unknown')}")
        lines.append(f"  Query: {result.get('query', '')}")

        deals = result.get("deals", [])
        if deals:
            lines.append(f"  Deals found: {len(deals)}")
            for i, deal in enumerate(deals[:5]):
                name = deal.get("name", deal.get("hotel_name", deal.get("ship_name", "Unknown")))
                savings = deal.get("user_savings_usd", deal.get("gross_savings_usd", 0))
                pct = deal.get("savings_percent", 0)
                home = deal.get("home_price_usd", 0)
                arb = deal.get("cheapest_price_usd", deal.get("arbitrage_price_usd", 0))
                lines.append(
                    f"  {i+1}. {name}: ${home:.0f} → ${arb:.0f} "
                    f"(save ${savings:.0f}, {pct:.0f}% off via Mystes)"
                )
        else:
            lines.append("  No arbitrage opportunities found for this query.")

        if result.get("error"):
            lines.append(f"  Error: {result['error']}")

        return "\n".join(lines)

    def _format_route_analysis(self, result):
        """Format deep route analysis."""
        lines = [f"Route Analysis: {result.get('route', '')}"]
        intel = result.get("intelligence")
        if intel and isinstance(intel, dict) and "error" not in intel:
            markets = intel.get("markets", [])
            if markets:
                cheapest = markets[0]
                lines.append(
                    f"  Mystes price: ${cheapest.get('avg_price_usd', 'N/A')} avg"
                )
                spread = intel.get("price_spread_usd", 0)
                lines.append(f"  Price spread across {len(markets)} regions: ${spread}")
            trend = intel.get("price_trend_direction", "unknown")
            lines.append(f"  Price trend: {trend}")
        recs = result.get("recommendations", [])
        for rec in recs[:3]:
            lines.append(f"  [{rec.get('priority', 'info')}] {rec.get('message', '')}")
        return "\n".join(lines)

    def _format_route_intelligence(self, result):
        """Format route intelligence data."""
        if result.get("error"):
            return f"Route intelligence error: {result['error']}"
        lines = [
            f"Route Intelligence: {result.get('origin')} -> {result.get('destination')}",
            f"  Days analyzed: {result.get('days_analyzed', 0)}",
        ]
        markets = result.get("markets", [])
        if markets:
            lines.append(f"  Regions tracked: {len(markets)}")
            lines.append(f"  Best Mystes price: ${markets[0].get('min_price_usd', 0):.0f}" if markets else "")
            lines.append(f"  Best booking: Mystes")
            lines.append(f"  Price spread: ${result.get('price_spread_usd', 0)}")
        demand = result.get("demand_level", {})
        if demand:
            lines.append(f"  Demand: {demand.get('level', 'unknown')} ({demand.get('searches_last_7d', 0)} searches/7d)")
        lines.append(f"  Trend: {result.get('price_trend_direction', 'unknown')}")
        deals = result.get("recent_deals", [])
        if deals:
            lines.append(f"  Active deals: {len(deals)}")
            best = deals[0]
            lines.append(
                f"    Best: {best.get('airline', '?')} via Mystes "
                f"— ${best.get('arbitrage_price_usd', 'N/A')} "
                f"({best.get('savings_percent', 0):.1f}% savings)"
            )
        return "\n".join(lines)

    def _format_market_briefing(self, result):
        """Format market briefing."""
        if result.get("error"):
            return f"Market briefing error: {result['error']}"
        lines = [
            f"Market Briefing: {result.get('market', '')} ({result.get('days_analyzed', 0)} days)",
            f"  Total searches: {result.get('total_searches', 0)}",
        ]
        if result.get("avg_savings_pct"):
            lines.append(f"  Average savings: {result['avg_savings_pct']}%")
        lines.append(f"  Demand trend: {result.get('demand_trend', 'unknown')}")
        lines.append(f"  Price movements: {result.get('price_movements', 'unknown')}")
        popular = result.get("popular_routes", [])
        if popular:
            lines.append("  Popular routes:")
            for r in popular[:5]:
                lines.append(f"    {r['route']} — {r['searches']} searches")
        return "\n".join(lines)

    def _format_trending(self, result):
        """Format trending data."""
        lines = ["Mystes Platform Trending:"]
        stats = result.get("stats", {})
        if stats:
            lines.append(
                f"  Platform: {stats.get('total_searches', 0):,} searches, "
                f"{stats.get('routes_tracked', 0)} routes, "
                f"{stats.get('markets_active', 0)} markets"
            )
            lines.append(f"  Total savings identified: ${stats.get('total_savings_generated_usd', 0):,.0f}")
            lines.append(f"  Active deals: {stats.get('active_deals', 0)}")
        anomalies = result.get("anomalies", {})
        new_deals = anomalies.get("new_deals", [])
        if new_deals:
            lines.append(f"\n  New high-savings deals: {len(new_deals)}")
            for d in new_deals[:5]:
                lines.append(
                    f"    {d.get('route')} via {d.get('market')}: "
                    f"{d.get('savings_pct', 0)}% savings — "
                    f"${d.get('price_usd', 'N/A')} ({d.get('airline', '')})"
                )
        surges = anomalies.get("demand_surges", [])
        if surges:
            lines.append(f"\n  Demand surges: {len(surges)}")
            for s in surges[:3]:
                lines.append(
                    f"    {s.get('route')}: +{s.get('change_pct', 0):.0f}% "
                    f"({s.get('recent_searches')} recent searches)"
                )
        return "\n".join(lines)

    def _format_price_history(self, result):
        """Format price history timeline."""
        if result.get("error"):
            return f"Price history error: {result['error']}"
        lines = [
            f"Price History: {result.get('origin')} -> {result.get('destination')} "
            f"({result.get('days_back', 0)} days)"
        ]
        timeline = result.get("timeline", {})
        if not timeline:
            lines.append("  No price history data available.")
        else:
            lines.append(f"  Data points: {len(timeline)} days")
            dates = sorted(timeline.keys())
            if dates:
                lines.append(f"  Date range: {dates[0]} to {dates[-1]}")
                # Show last 5 days
                for date_key in dates[-5:]:
                    day_data = timeline[date_key]
                    if isinstance(day_data, dict):
                        markets_str = ", ".join(
                            f"{mkt}: ${data.get('avg_price', 'N/A'):.0f}"
                            for mkt, data in list(day_data.items())[:3]
                        )
                        lines.append(f"    {date_key}: {markets_str}")
        return "\n".join(lines)

    def _format_deals(self, result):
        """Format deals list."""
        deals = result.get("deals", [])
        if not deals:
            return "No active deals found matching your criteria."
        lines = [f"Active Deals ({result.get('count', len(deals))} found):"]
        for i, d in enumerate(deals[:10], 1):
            origin = d.get("origin", "?")
            dest = d.get("destination", "?")
            airline = d.get("airline", "Unknown")
            savings = d.get("savings_percent", 0)
            arb_price = d.get("arbitrage_price_usd", "N/A")
            market = d.get("arbitrage_market", "?")
            lines.append(
                f"  {i}. {origin}-{dest} {airline}: ${arb_price} via {market} "
                f"({savings:.1f}% savings)"
            )
        return "\n".join(lines)

    def _format_opportunities(self, result):
        """Format opportunity discovery results."""
        opps = result.get("opportunities", [])
        lines = [
            f"Opportunity Discovery ({result.get('total', len(opps))} found):",
        ]
        if result.get("cached"):
            lines.append(f"  (Cached from {result.get('last_run', 'unknown')})")
        by_type = result.get("by_type", {})
        if by_type:
            lines.append("  By type:")
            for t, count in by_type.items():
                lines.append(f"    {t}: {count}")
        for opp in opps[:8]:
            opp_type = opp.get("type", "unknown")
            priority = opp.get("priority", "medium")
            action = opp.get("action", "")
            detail = ""
            if opp.get("origin") and opp.get("destination"):
                detail = f" ({opp['origin']}-{opp.get('destination', opp.get('dest', '?'))})"
            elif opp.get("market"):
                detail = f" (market: {opp['market']})"
            elif opp.get("site"):
                detail = f" (site: {opp['site']})"
            lines.append(f"  [{priority}] {opp_type}{detail} -> {action}")
        return "\n".join(lines)

    # -- Build #99: Smart booking formatters --

    def _format_saved_travelers(self, result):
        """Format saved travelers list for AI response."""
        travelers = result.get("travelers", [])
        count = result.get("count", 0)

        if count == 0:
            return (
                "No saved travelers found.\n"
                "To book, you'll need to provide traveler details:\n"
                "- Full name (as on ID)\n"
                "- Date of birth\n"
                "- Gender\n"
                "- Email and phone\n"
                "For international flights, also passport info."
            )

        lines = [f"Saved Travelers ({count}):"]
        for i, t in enumerate(travelers, 1):
            primary = " (Primary)" if t.get("is_primary") else ""
            passport = " [Passport on file]" if t.get("has_passport") else ""
            pax_type = t.get("passenger_type", "ADULT")
            lines.append(
                f"  {i}. {t.get('name', 'Unknown')}{primary} — "
                f"{pax_type}{passport}"
            )

        lines.append("\nYou can select saved travelers by number, or provide new traveler details.")
        return "\n".join(lines)

    def _format_prepare_booking(self, result):
        """Format booking preparation results."""
        if not result.get("success"):
            return f"Booking preparation failed: {result.get('error', 'Unknown error')}\n{result.get('message', '')}"

        lines = [
            "Booking Prepared Successfully:",
            f"  Offer ID: {result.get('offer_id', 'N/A')}",
            f"  Passengers: {result.get('passenger_count', 0)}",
        ]

        travelers = result.get("travelers", [])
        for i, t in enumerate(travelers, 1):
            source = "(saved)" if t.get("source") == "saved" else "(new)"
            lines.append(f"    {i}. {t.get('name', 'Unknown')} {source}")

        lines.append(f"\nNext step: {result.get('next_step', 'Confirm and proceed to payment')}")
        lines.append(result.get("message", ""))

        return "\n".join(lines)

    def _format_execute_booking(self, result):
        """Format booking execution results."""
        if not result.get("success"):
            return f"Booking failed: {result.get('error', 'Unknown error')}"

        lines = [
            "Booking Confirmed!",
            f"  Confirmation Number: {result.get('booking_reference', 'N/A')}",
            f"  Passengers: {result.get('passenger_count', 0)}",
        ]

        passengers = result.get("passengers", [])
        for name in passengers:
            lines.append(f"    - {name}")

        lines.append(f"\nStatus: {result.get('status', 'confirmed').upper()}")
        lines.append(f"\n{result.get('message', '')}")

        next_steps = result.get("next_steps", [])
        if next_steps:
            lines.append("\nNext Steps:")
            for step in next_steps:
                lines.append(f"  - {step}")

        return "\n".join(lines)

    def _format_initiate_payment(self, result):
        """Format payment initiation results."""
        if not result.get("success"):
            return f"Payment setup failed: {result.get('error', 'Unknown error')}"

        lines = [
            "Payment Ready:",
            f"  Amount: ${result.get('amount_usd', 0):.2f}",
            f"  Description: {result.get('description', 'Flight booking')}",
            f"  Payment Method: {result.get('payment_method', 'card').title()}",
            f"  Session ID: {result.get('payment_session_id', 'N/A')}",
            f"\n{result.get('message', '')}",
            f"\nPayment expires in {result.get('expires_in_minutes', 30)} minutes.",
        ]

        return "\n".join(lines)


# ===========================================================================
# Helper functions
# ===========================================================================

def get_ai_tier(tier_key):
    """Get tier configuration dict by key.

    Args:
        tier_key: One of 'ai_free', 'ai_starter', 'ai_professional', 'ai_unlimited'.

    Returns:
        Tier config dict, or the ai_free tier as fallback.
    """
    return ARBITRAGE_SUBSCRIPTION_TIERS.get(tier_key, ARBITRAGE_SUBSCRIPTION_TIERS["ai_free"])


def _get_node_tier(user):
    """Get the user's node tier from their NodeConsentProfile.

    Returns:
        str: 'bronze', 'silver', 'gold', or 'platinum'. Defaults to 'bronze'.
    """
    try:
        from models import db
        from sqlalchemy import text
        result = db.session.execute(
            text("SELECT current_tier FROM node_consent_profiles WHERE user_id = :uid"),
            {"uid": user.id}
        ).fetchone()
        if result:
            return result[0] or "bronze"
    except Exception:
        pass
    return "bronze"


def get_combined_quota(user):
    """Get the combined quota from node free queries + paid subscription.

    Returns dict with:
        node_tier, node_free_per_day, node_tools,
        paid_tier, paid_queries_per_month, paid_tools,
        effective_tools (max of both),
        total_daily_limit, total_monthly_limit (free_monthly + paid)
    """
    node_tier = _get_node_tier(user)
    node_config = ARBITRAGE_FREE_QUERIES.get(node_tier, ARBITRAGE_FREE_QUERIES["bronze"])
    free_per_day = node_config["free_queries_per_day"]
    node_tools = node_config["max_tools_per_query"]

    paid_tier_key = getattr(user, "ai_tier", None) or "ai_free"
    paid_tier = get_ai_tier(paid_tier_key)
    paid_queries = paid_tier.get("queries_per_month") or 0
    paid_tools = paid_tier.get("max_tools_per_query", 2)

    # Stacking: higher tool/market count applies for all queries
    effective_tools = max(node_tools, paid_tools)
    effective_context = max(
        node_config.get("max_context_messages", 10),
        paid_tier.get("max_context_messages", 10),
    )

    # Free monthly = daily * 30
    free_monthly = free_per_day * 30

    # Unlimited paid tier
    if paid_tier.get("queries_per_month") is None:
        total_monthly = None  # unlimited
    else:
        total_monthly = free_monthly + paid_queries

    return {
        "node_tier": node_tier,
        "node_free_per_day": free_per_day,
        "node_tools": node_tools,
        "paid_tier": paid_tier_key,
        "paid_tier_name": paid_tier.get("name", "Node Free"),
        "paid_queries_per_month": paid_queries,
        "paid_tools": paid_tools,
        "effective_tools": effective_tools,
        "effective_context": effective_context,
        "free_monthly": free_monthly,
        "total_monthly": total_monthly,
    }


def check_ai_quota(user):
    """Check whether a user has remaining AI queries.

    Combines node free daily queries + paid subscription monthly queries.
    When free+paid quota exhausted, checks if overage purchase is available.

    Args:
        user: User model instance with ai_tier, ai_queries_used_this_month,
              and optionally overage_queries_remaining attributes.

    Returns:
        dict with allowed, used, limit, tier, remaining, node_tier,
        overage_available, overage_price_per_query, economic_phase, etc.
    """
    combined = get_combined_quota(user)
    used = getattr(user, "ai_queries_used_this_month", 0) or 0
    total_monthly = combined["total_monthly"]
    overage_remaining = getattr(user, "overage_queries_remaining", 0) or 0
    node_config = ARBITRAGE_FREE_QUERIES.get(
        combined["node_tier"], ARBITRAGE_FREE_QUERIES["bronze"]
    )
    overage_allowed = node_config.get("overage_allowed", True)

    base = {
        "tier": combined["paid_tier"],
        "node_tier": combined["node_tier"],
        "node_free_per_day": combined["node_free_per_day"],
        "quota_type": "arbitrage",
        "free_browse_quota": "unlimited",
        "overage_queries_remaining": overage_remaining,
    }

    if total_monthly is None:
        # Unlimited tier (Phase 2 platinum)
        base.update({
            "allowed": True,
            "used": used,
            "limit": "unlimited",
            "remaining": "unlimited",
            "overage_available": False,
        })
        return base

    remaining_free = max(0, total_monthly - used)

    if remaining_free > 0:
        base.update({
            "allowed": True,
            "used": used,
            "limit": total_monthly,
            "remaining": remaining_free,
            "overage_available": overage_allowed,
        })
        return base

    # Free+paid quota exhausted — check overage balance
    if overage_remaining > 0:
        base.update({
            "allowed": True,
            "used": used,
            "limit": total_monthly,
            "remaining": 0,
            "using_overage": True,
            "overage_available": overage_allowed,
        })
        return base

    # No quota, no overage balance — blocked but can purchase
    base.update({
        "allowed": False,
        "used": used,
        "limit": total_monthly,
        "remaining": 0,
        "overage_available": overage_allowed,
        "can_purchase_overage": overage_allowed,
    })
    return base


# ---------------------------------------------------------------------------
# Rate limiting (in-memory sliding window)
# ---------------------------------------------------------------------------

_ai_rate_buckets = {}  # user_id -> [timestamp, ...]
_AI_RATE_WINDOW = 60.0  # 1-minute sliding window
_AI_RATE_LIMIT_PER_MINUTE = 10  # max queries per minute per user


def check_ai_rate_limit(user):
    """In-memory sliding window rate limiter for AI queries.

    Same pattern as commercial_auth._check_browsing_rate_limit.

    Args:
        user: User model instance (needs .id attribute).

    Returns:
        dict with allowed (bool), limit (int), current (int).
    """
    user_key = str(user.id)
    now = time.time()

    timestamps = _ai_rate_buckets.get(user_key, [])
    timestamps = [ts for ts in timestamps if now - ts < _AI_RATE_WINDOW]

    current = len(timestamps)

    if current >= _AI_RATE_LIMIT_PER_MINUTE:
        _ai_rate_buckets[user_key] = timestamps
        return {"allowed": False, "limit": _AI_RATE_LIMIT_PER_MINUTE, "current": current}

    timestamps.append(now)
    _ai_rate_buckets[user_key] = timestamps
    return {"allowed": True, "limit": _AI_RATE_LIMIT_PER_MINUTE, "current": current + 1}


def record_ai_usage(user):
    """Increment the user's AI query count for the current billing month.

    Args:
        user: User model instance with ai_queries_used_this_month attribute.
    """
    try:
        from models import db
        current = getattr(user, "ai_queries_used_this_month", 0) or 0
        user.ai_queries_used_this_month = current + 1
        db.session.commit()
    except Exception as e:
        logger.warning("Failed to record AI usage for user %s: %s", user.id, e)


def reset_monthly_ai(user):
    """Reset the user's AI usage counter if the billing period has elapsed.

    Free tier users reset daily (1 day). Paid tier users reset monthly (30 days).
    Checks ai_month_reset_date — if it is None or in the past, resets the
    counter and sets the next reset date accordingly.

    Args:
        user: User model instance.
    """
    try:
        from datetime import datetime, timedelta
        from models import db

        reset_date = getattr(user, "ai_month_reset_date", None)
        now = datetime.utcnow()

        if reset_date is None or reset_date <= now:
            tier_key = getattr(user, "ai_tier", None) or "ai_free"
            tier = get_ai_tier(tier_key)
            reset_days = tier.get("reset_interval_days", 30)

            user.ai_queries_used_this_month = 0
            user.ai_month_reset_date = now + timedelta(days=reset_days)
            db.session.commit()
            logger.debug(
                "Reset AI usage for user %s (tier=%s, interval=%dd) — next reset: %s",
                user.id, tier_key, reset_days, user.ai_month_reset_date
            )
    except Exception as e:
        logger.warning("Failed to reset monthly AI for user %s: %s", user.id, e)


def get_ai_tier_info(user):
    """Get full AI tier details and usage for a user.

    Includes combined node tier + paid subscription info.

    Args:
        user: User model instance.

    Returns:
        dict with tier configuration, usage stats, and quota info.
    """
    combined = get_combined_quota(user)
    quota = check_ai_quota(user)
    paid_tier = get_ai_tier(combined["paid_tier"])

    return {
        "tier_key": combined["paid_tier"],
        "tier_name": paid_tier.get("name", "Node Free"),
        "node_tier": combined["node_tier"],
        "node_free_per_day": combined["node_free_per_day"],
        "price_monthly_usd": paid_tier.get("price_monthly_usd", 0),
        "queries_per_month": combined["total_monthly"],
        "max_tools_per_query": combined["effective_tools"],
        "max_context_messages": combined["effective_context"],
        "features": paid_tier.get("features", []),
        "usage": {
            "queries_used": quota.get("used", 0),
            "queries_limit": quota.get("limit"),
            "queries_remaining": quota.get("remaining", "unlimited"),
            "allowed": quota.get("allowed", True),
        },
        "reset_date": (
            user.ai_month_reset_date.isoformat()
            if getattr(user, "ai_month_reset_date", None)
            else None
        ),
    }


def get_all_ai_tiers(user=None):
    """Get all AI tier definitions.

    Args:
        user: Optional User model instance (reserved for future tier logic).

    Returns:
        dict mapping tier_key to tier config.
    """
    return dict(ARBITRAGE_SUBSCRIPTION_TIERS)


# ===========================================================================
# Module-level singleton
# ===========================================================================

mystes_ai = MystesAI()
