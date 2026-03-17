# Build #142 — Duffel NDC Full Integration into ANASTASiA
**Date**: 2026-03-09
**Status**: COMPLETE
**Tests**: 120/120 passing (0.27s)

## What This Build Does
Adds Duffel NDC as a second flight source alongside Picasso/Redbox in ANASTASiA.
The BookingAgent now has dual-source intelligence — GDS via Redbox + NDC via Duffel.
Claude decides which tools to use based on context, and can search both simultaneously.

## Files Created

### 1. `picasso-sdk/picasso/duffel.py` — DuffelNDCClient SDK (~550 LOC)
Complete Duffel NDC API client mirroring RedboxClient pattern:
- `search_places()` — Airport/city autocomplete
- `search_flights()` — NDC flight search with normalized output
- `get_offer()` — Refresh offer pricing (offers expire 15-30 min)
- `get_available_services()` — Ancillary services (baggage, seats, meals)
- `get_seat_map()` — Cabin layout with seat availability
- `book_flight()` — Create order with passengers, services, metadata
- `get_order()` / `list_orders()` — Booking management
- `cancel_order()` — Two-step cancellation (request → confirm)
- `request_order_change()` / `confirm_order_change()` — Date/route changes
- `list_airlines()` / `get_airline()` — Reference data
- `get_balance()` — Duffel account balance
- `create_webhook()` / `list_webhooks()` — Event notifications

### 2. `picasso-sdk/picasso/agent/duffel_tools.py` — 10 Claude Tool Definitions
All prefixed with `duffel_` to distinguish from Redbox tools:
- `duffel_search_places`, `duffel_search_flights`, `duffel_get_offer`
- `duffel_get_services`, `duffel_get_seat_map`
- `duffel_book_flight` (with passport, loyalty, services)
- `duffel_get_order`, `duffel_list_orders`
- `duffel_cancel_order`, `duffel_change_order`

### 3. `picasso-sdk/picasso/agent/duffel_knowledge.py` — Duffel Knowledge Base (~6.4K chars)
System prompt addendum teaching Claude:
- When to use Duffel vs Redbox (NDC vs GDS)
- Complete booking flow (search → refresh → services → seats → book → manage)
- Duffel-specific data formats (gender: m/f, title: lowercase, born_on not dateOfBirth)
- Offer expiry handling
- Conditions (changeable/refundable with penalties)
- Error handling
- What Duffel cannot do

### 4. `memory/duffel_api.md` — Complete API Reference (~350 lines)
Comprehensive Duffel API documentation:
- All endpoints with methods, paths, purposes
- Full request/response schemas with examples
- Booking flow sequence (search → offer → order → manage)
- Payment types (balance, arc_bsp_cash)
- Cancellation/change flows
- Conditions schema
- Duffel vs Picasso comparison table
- Error codes and rate limits

## Files Modified

### 5. `picasso-sdk/anastasia/knowledge/profiles.py`
- Added `_build_duffel_seed_profile()` — 13 endpoints, 3-step booking flow, 5 quirks
- Added to `_build_all_seed_profiles()` → 6 total seed profiles (was 5)
- Readiness: "tested", confidence: 0.90

### 6. `picasso-sdk/picasso/agent/orchestrator.py`
- Added `duffel_client` parameter to `BookingAgent.__init__()`
- Knowledge base auto-extends with Duffel KB when client is configured
- Tool list auto-extends with 10 Duffel tools when client is configured
- Added 10 `duffel_*` tool handlers in `_execute_tool()`
- All Duffel operations publish events to neuron network:
  - `duffel_search_flights` → SEARCH_COMPLETED (Intelligence neuron)
  - `duffel_book_flight` → BOOKING_CREATED (Compliance neuron)
  - `duffel_cancel_order` → BOOKING_CANCELLED (Compliance neuron)
- Passenger data transformation: Duffel format (m/f, lowercase titles, identity_documents, loyalty_programme_accounts)

### 7. `picasso-sdk/picasso/agent/api.py`
- Added `DuffelNDCClient` import
- Shared Duffel client created in app factory (from `DUFFEL_ACCESS_TOKEN` env var)
- Passed to BookingAgent alongside event_bus and agency_id

## Architecture — Dual Source Intelligence
```
User Message
    ↓
BookingAgent (Claude Opus 4.6)
    ├── Redbox Tools (16 tools) → RedboxClient → Picasso/AERTiCKET GDS
    │   └── 102-country POS, consolidator fares, PUB/NET/NEG
    └── Duffel Tools (10 tools) → DuffelNDCClient → 300+ Airline NDC APIs
        └── Direct airline connections, NDC-exclusive fares
    ↓
Neuron Network (EventBus)
    ├── Intelligence: price aggregation from both sources
    ├── Compliance: audit trail for all bookings
    └── Credits: rewards for completed bookings
```

## Live Verification
- Places autocomplete: "New York" → 4 results (NYC, SWF, JFK)
- JFK→LAX search: 11 offers (Hawaiian Airlines $140-$246)
- Conditions parsed: changeable, refundable, penalties
- Passenger IDs preserved for booking linkage

## Metrics
- **6 seed SystemProfiles** (was 5)
- **26 agent tools** (16 Redbox + 10 Duffel)
- **120 tests** — all passing (0.27s)
- **~550 LOC** new DuffelNDCClient
- **~350 lines** new tool definitions
- **~180 lines** new knowledge base
- **~150 lines** new SystemProfile
- **~100 lines** new orchestrator routing
