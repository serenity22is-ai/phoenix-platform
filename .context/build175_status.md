# Build #175 — ANASTASiA BookingDispatcher (Intelligence Layer)
**Date**: 2026-03-12
**Status**: COMPLETE
**Tests**: 138 consumer + 429 SDK = 567 total, 0 failed

---

## What Was Built

The first ANASTASiA intelligence layer integration into MYSTES. Replaces the hardcoded if/else booking chain with card-guided dispatch. Zero Anthropic API cost — pure JSON knowledge cards + Python logic.

### Product Boundary (LOCKED DECISION)
- **MYSTES = the face** (template, UI, user features, payments)
- **ANASTASiA APAi = the brain** (API intelligence, dispatch, knowledge cards, credentials)
- **MYSTES calls ANASTASiA** — never the other way around
- Documented in `memory/product_boundary.md`

### BookingDispatcher (`picasso-sdk/anastasia/dispatch/dispatcher.py`)
- Reads knowledge cards (JSON) from `modules/cards/`
- Routes bookings by `raw_offer.source` → knowledge card → API client
- Source aliasing: "picasso" → "picasso_redbox" (search.py uses short names)
- Clients injected by MYSTES — dispatcher never imports them directly
- 4 source handlers: Picasso, Duffel NDC, Kiwi Tequila, AirGateway NDC
- Each handler knows its provider's booking API signature
- Standardized return: `{success, confirmation_code, booking_source}`

### PassengerTransformer (`picasso-sdk/anastasia/dispatch/transformer.py`)
- Converts MYSTES standard form data → any provider's format using card's `passenger_format`
- Name fields: firstName/given_name/name/nameGiven → mapped from first_name
- Gender values: Male/Female, m/f, null → mapped from M/F
- Title casing: mr/MR/Mr → per provider
- Date format: YYYY-MM-DD → DD/MM/YYYY (Kiwi) → mapped automatically
- Type codes: ADT/adult → mapped from passenger_type hint
- Contact fields: email/emailContact, phone/phone_number → per provider
- Handles primary + additional passengers in one call

### Data Flow Fix
- `/api/search` Deal creation now stores `amadeus_offer_data=json.dumps(raw_offer)` for ALL sources
- Previously only fare_id/fare_search_id (Picasso) were stored — Duffel offer_id and Kiwi booking_token were lost

### server.py Rewire
- `execute_automated_booking()` now uses ANASTASiA BookingDispatcher as Path 1
- Fallback chain: ANASTASiA dispatch → airline_booker (Playwright) → manual agent
- Legacy Picasso support: if no amadeus_offer_data but fare_id exists, builds Picasso raw_offer
- SDK path added to sys.path for import

### Feature Flags Updated
- Core always enabled: `vertical_flights`, `vertical_hotels`, `rewards_points`, `travel_plus`, `tier_system`, `b2b_accounts`
- Hidden behind admin flags: `trip_planner`, `wishlist`, `friends_system`, `vertical_activities`, `vertical_rentals`
- Admins can enable any feature — code still exists, just not visible to consumers

---

## Files Created

| File | LOC | Purpose |
|------|-----|---------|
| `picasso-sdk/anastasia/dispatch/__init__.py` | 20 | Package exports |
| `picasso-sdk/anastasia/dispatch/dispatcher.py` | 310 | BookingDispatcher + 4 source handlers |
| `picasso-sdk/anastasia/dispatch/transformer.py` | 170 | PassengerTransformer (card-guided format conversion) |

## Files Modified

| File | Changes |
|------|---------|
| `server.py` | `execute_automated_booking()` rewired to ANASTASiA dispatcher; `/api/search` stores amadeus_offer_data for all sources |
| `models.py` | Feature flags: trip_planner/wishlist/friends/activities/rentals set to disabled (admin-only) |
| `tests/test_integration.py` | +19 new tests (5 transformer + 7 dispatcher + 3 server integration + 4 updated) |

## Test Results: 567 total (138 consumer + 429 SDK)

### New Tests (Build #175)
- `TestBuild175PassengerTransformer` (5 tests): Picasso format, Duffel format, Kiwi date conversion, AirGateway format, additional passengers
- `TestBuild175BookingDispatcher` (7 tests): card loading, unknown source, missing client, no source, missing fare_id, Duffel mock booking, available sources
- `TestBuild175ServerIntegration` (3 tests): function exists, raw_offer stored, core flags enabled

## Architecture After This Build

```
MYSTES (server.py)
  └── execute_automated_booking(booking, deal, passenger_data)
       ├── Builds raw_offer from deal.amadeus_offer_data
       ├── Imports ANASTASiA BookingDispatcher
       ├── Injects API client instances
       └── dispatcher.dispatch(raw_offer, passenger_data, clients)
            ├── Loads knowledge card for raw_offer.source
            ├── PassengerTransformer converts form → provider format
            ├── Routes to source handler (_book_picasso, _book_duffel_ndc, etc.)
            └── Returns standardized {success, confirmation_code, booking_source}
```

## What This Enables
- **Any new API** = add knowledge card JSON + client SDK + handler function → works
- **Zero AI cost** for all standard bookings — cards are pure JSON, transformer is pure Python
- **Turnkey ready** — agency template gets dispatcher + cards, their credentials go in vault
- **Testable** — mock clients injected, no real API calls needed for testing

## NOT in this build (deferred):
- SearchDispatcher (search.py still has inline multi-source orchestration)
- Moving API clients from MYSTES root to picasso-sdk/clients/ (backward compat stubs exist)
- Wiring dispatcher into hotel/car booking paths (hotels use liteAPI directly, cars use Discover Cars directly)
