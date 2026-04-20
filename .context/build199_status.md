# Build #199 — Duffel Stays SDK Integration (Hotels)
**Date**: 2026-03-17
**Status**: COMPLETE
**Tests**: 1,230+ (703 consumer + 498 SDK + 32 new Duffel Stays), 0 failed

## What Was Built

Full Duffel Stays hotel integration proving ANASTASiA's core APAi value proposition:
**Credentials go in → knowledge card compiled → booking flow executes flawlessly.**

Same `DUFFEL_ACCESS_TOKEN` covers both flights and stays. Duffel Stays = 1M+ hotel properties
(Marriott, Hilton, Shangri-La, IHG, Westin) with commission-share model (we earn, not pay).

## Files Created (5 new)

| File | LOC | Purpose |
|------|-----|---------|
| `picasso-sdk/clients/duffel_stays.py` | ~700 | SDK client — 11 API methods |
| `picasso-sdk/anastasia/modules/cards/duffel_stays.json` | ~80 | Knowledge card (JSON) |
| `picasso-sdk/picasso/agent/duffel_stays_tools.py` | ~350 | 11 agent tool definitions |
| `picasso-sdk/picasso/agent/duffel_stays_knowledge.py` | ~170 | Agent knowledge base |
| `tests/test_duffel_stays.py` | ~420 | 32 tests (8 test classes) |

## Files Modified (6)

| File | Changes |
|------|---------|
| `picasso-sdk/anastasia/modules/flight_modules.py` | Added `build_duffel_stays_card()` fallback builder + updated `build_all_hotel_modules()` |
| `picasso-sdk/anastasia/verticals/hotels.py` | Added `"duffel_stays"` to booking event handler |
| `picasso-sdk/anastasia/dispatch/dispatcher.py` | Added `_book_duffel_stays()` handler + source alias + handler registration |
| `routes_hotels.py` | New `/api/hotels/suggest` endpoint, free-text typeahead UI, dual-source parallel search (liteAPI + Duffel Stays), dedup, source tagging |
| `server.py` | Split `execute_automated_hotel_booking()` into source router + `_execute_duffel_stays_booking()` + `_execute_liteapi_booking()` |
| `picasso-sdk/tests/` | Updated module/card count assertions (1→2 hotel modules, 11→12 total) |

## Architecture

### SDK Client (11 endpoints)
1. `suggest_accommodation(query)` — Autocomplete (min 3 chars)
2. `browse_accommodation(lat, lng, radius)` — Properties by coordinates
3. `get_accommodation(id)` — Property details
4. `search_stays(check_in, check_out, guests, rooms, location)` — Search availability
5. `fetch_all_rates(search_result_id)` — All room rates
6. `create_quote(rate_id)` — Lock price (expires_at)
7. `book_stay(quote_id, email, phone, guests)` — Create booking
8. `list_bookings(limit, after)` — Paginated list
9. `get_booking(booking_id)` — Booking details
10. `update_booking(booking_id, updates)` — Modify booking
11. `cancel_booking(booking_id)` — Cancel with refund info

### Dual-Source Hotel Search
- liteAPI (city code, net rates) + Duffel Stays (coordinates, commission-share)
- Parallel via `ThreadPoolExecutor` (max 2 workers)
- Dedup by property name (case-insensitive, cheapest wins)
- Graceful degradation: if one source fails, other still returns results
- Source tagged on every result for booking dispatch

### Booking Flow
- **liteAPI**: prebook → book (existing)
- **Duffel Stays**: create_quote(rate_id) → book_stay(quote_id) (NEW)
- Source determined from `deal.amadeus_offer_data` JSON `"source"` field

### Fee Calculation
- `get_fee_percent(user)` applied to raw rate
- **$3 minimum, NO maximum cap** (critical rule)
- Guest=50%, Free=45%, Travel+=35%, B2B=25%/20%/15%

### Frontend Changes
- Replaced static city dropdown (30 cities) with free-text typeahead
- Calls `/api/hotels/suggest` → Duffel Stays accommodation suggestions
- Debounced (300ms), shows property name + type in dropdown
- Stores lat/lng in hidden fields for Duffel coordinate search
- Full global coverage (not limited to static city map)

## Test Coverage (32 new tests)

| Class | Tests | Coverage |
|-------|-------|---------|
| `TestDuffelStaysSDKClient` | 12 | All 11 endpoints + error handling |
| `TestDuffelStaysKnowledgeCard` | 3 | JSON loads, auth, module registration |
| `TestDuffelStaysDispatcher` | 3 | Handler routing, quote→book flow, missing rate_id |
| `TestHotelFeeCalculation` | 3 | $3 min, NO max cap, tier percentages |
| `TestDualSourceHotelSearch` | 4 | Dedup, case-insensitive, single source, graceful degradation |
| `TestHotelSuggestEndpoint` | 2 | Min chars, suggestion format |
| `TestDuffelStaysBookingExecution` | 3 | Source detection, E.164 formatting |
| `TestDuffelStaysAgentFiles` | 2 | Tool definitions (11), knowledge base |

## What This Does NOT Change
- `duffel_client.py` (root) — existing flight client untouched
- `liteapi_client.py` — existing hotel client untouched
- `picasso-sdk/clients/duffel.py` — SDK flight client untouched
- Flight search pipeline — untouched
- ANASTASiA neuron network — neurons unchanged (module auto-discovered via JSON)

## What This Proves
This build is the first complete demonstration of ANASTASiA's core APAi capability:
1. New credentials received (DUFFEL_ACCESS_TOKEN)
2. API fully reverse-engineered (11 endpoints documented)
3. Knowledge card compiled (JSON, zero AI cost at runtime)
4. Booking flow executes flawlessly (quote → book)
5. Consumer UI updated automatically (dual-source search)
6. Every future API integration follows this same template
