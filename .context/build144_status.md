# Build #144 — Kiwi Tequila + Vertical Plugin Architecture
**Date**: 2026-03-09
**Status**: COMPLETE
**Tests**: 56 passed (consumer) + 120 passed (SDK) = 176 total, 0 failures

## What This Build Does

### 1. Product Model Update — Vertical Plugin Architecture
Updated ANASTASiA platform vision to reflect modular vertical plugin architecture:
- MYSTES is a **modular vertical platform**, not a monolithic OTA
- Each vertical (flights, hotels, cars, cruises) = separate plugin module
- All plugins follow the `X_CONFIGURED` credential-driven pattern
- ANASTASiA powers all plugins, learns new systems through daemon installations
- Plugin marketplace model: more plugins = more capable turnkey OTA
- Client-authorized access unlocks high-threshold APIs (Hotelbeds, Sabre, etc.)

### 2. Kiwi Tequila Integration — 3rd Flight Source
Added Kiwi Tequila as third flight search source in the MYSTES consumer search pipeline
alongside Picasso/Redbox (GDS) and Duffel (NDC). Kiwi adds 750+ carriers with virtual
interlining capability.

## Architecture — Triple-Source Consumer Search
```
User → MYSTES AI Chat → search_global()
    ├── Picasso/Redbox (GDS) → consolidator fares, 102-country POS arbitrage
    ├── Duffel (NDC) → NDC-direct fares, 300+ airlines
    ├── Kiwi Tequila (Aggregator) → 750+ carriers, virtual interlining
    ├── Google Flights → US retail price benchmark
    └── Smart Merge:
        ├── Same airline+time ±15min found in multiple sources?
        │   └── Keep cheapest price from any source
        └── Unique flight? → add to results with estimated deal
```

## Files Created

### Consumer OTA
1. `kiwi_client.py` (~350 LOC) — Kiwi Tequila API client
   - `KiwiClient` class with search, booking (3-phase), location search
   - `search_with_kiwi()` convenience function matching picasso/duffel pattern
   - Date conversion YYYY-MM-DD → DD/MM/YYYY (Kiwi format)
   - Vehicle type filter (aircraft only, no buses/trains)

### ANASTASiA SDK
2. `picasso-sdk/picasso/kiwi.py` (~380 LOC) — KiwiTequilaClient SDK
   - Mirrors DuffelNDCClient pattern for consistency
   - search_places(), search_flights(), check_flights(), save_booking(), confirm_payment()

3. `picasso-sdk/picasso/agent/kiwi_tools.py` (~200 LOC) — 5 Claude tool definitions
   - kiwi_search_places, kiwi_search_flights, kiwi_check_flights
   - kiwi_book_flight, kiwi_confirm_payment

4. `picasso-sdk/picasso/agent/kiwi_knowledge.py` (~120 LOC) — Kiwi knowledge base
   - When to use Kiwi vs Redbox vs Duffel
   - 3-phase booking flow, passenger data format (DD/MM/YYYY dates)
   - Virtual interlining awareness, Kiwi as merchant of record

## Files Modified

### Consumer OTA
5. `main.py` — Added KIWI_AVAILABLE/KIWI_CONFIGURED flags
6. `search.py` — Kiwi wired into search_global():
   - In Picasso block: Kiwi fires after Duffel, smart merge with dedup
   - Standalone fallback: Kiwi-only when Picasso+Duffel unavailable
   - Source tracking: "aggregator" source field, kiwi_tequila in data_sources

### ANASTASiA SDK
7. `picasso-sdk/picasso/agent/orchestrator.py`
   - Added kiwi_client parameter to BookingAgent.__init__()
   - Knowledge base auto-extends with Kiwi KB when client configured
   - Tool list auto-extends with 5 Kiwi tools when client configured
   - 5 kiwi_* tool handlers in _execute_tool()
   - All Kiwi operations publish events to neuron network

8. `picasso-sdk/picasso/agent/api.py`
   - KiwiTequilaClient import and shared client creation
   - Passed to BookingAgent alongside duffel_client

9. `picasso-sdk/anastasia/knowledge/profiles.py`
   - Added _build_kiwi_seed_profile() — 6 endpoints, 3-step booking flow, 5 quirks
   - Added to _build_all_seed_profiles() → 7 total seed profiles (was 6)

### Platform Vision
10. `memory/anastasia_platform_vision.md`
    - Added "Vertical Plugin Architecture" section with full diagram
    - Flights, Hotels, Cars, Cruises as separate vertical plugins
    - Plugin marketplace model, resellable turnkey OTA model
    - Tandem system — plugins expand template capabilities

## Source Priority in search_global()
```
1. Picasso/Redbox (GDS) — primary (POS arbitrage value)
2. Duffel (NDC) — supplement (NDC-exclusive fares)
3. Kiwi Tequila (Aggregator) — supplement (carrier coverage, virtual interlining)
4. Google Flights — price benchmark only
5. Amadeus + Proxy — legacy fallback
```

## Kiwi API Key Status
- **Invitation-only** since mid-2024 (was self-service)
- Apply via partnerships team: partners.kiwi.com
- When key is obtained: set KIWI_API_KEY in .env → source goes live
- No code changes needed — `KIWI_CONFIGURED` flag activates automatically

## Metrics
- **7 seed SystemProfiles** (was 6): Redbox, Amadeus, Sabre, liteAPI, Travelport, Duffel, Kiwi
- **31 agent tools** (16 Redbox + 10 Duffel + 5 Kiwi)
- **176 tests** — all passing (56 consumer + 120 SDK)
- **3 flight search sources** in consumer pipeline (Picasso + Duffel + Kiwi)
- **~350 LOC** new KiwiClient (consumer)
- **~380 LOC** new KiwiTequilaClient (SDK)
- **~320 LOC** new tool definitions + knowledge base
- **~160 LOC** new SystemProfile
- **~90 LOC** new orchestrator routing
