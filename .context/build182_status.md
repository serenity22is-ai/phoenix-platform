# Build #182 — raw_offer Fix + Vertical Search + CrossSell + Concierge Intelligence

**Date**: 2026-03-17
**Tests**: 762 (260 consumer + 488 SDK + 14 cross-sell), 0 failures
**Previous**: Build #181 (722 tests)

## What Was Built

### Phase 1: raw_offer Passthrough Fix (P0 CRITICAL BUG)
- **The Bug**: JavaScript in server.py stripped booking references (fare_id, offer_id, raw_offer) at 3 locations when encoding flight card data for checkout
- **Fix**: Added `fare_id`, `fare_search_id`, `offer_id`, `raw_offer`, `picasso_gds`, `fare_type`, `source` to:
  1. `flightData` encoding (line ~14074) — card click handler
  2. `proceedToPayment` flights.push (line ~14687) — payment builder
  3. `dealData` object (line ~14713) — deal creation payload
- **Result**: Deal.amadeus_offer_data now populated → `execute_automated_booking()` can dispatch → no more fallback to manual

### Phase 2: Vertical Neuron Search Methods
- `CarsNeuron.search()` — Takes injected client, calls search_locations → search_cars, attaches raw_offer with source="discover_cars"
- `ActivitiesNeuron.search()` — Takes injected client, calls search_freetext → search_products, attaches raw_offer with source="viator"
- `InsuranceNeuron.search()` — Takes injected client, calls get_quote, attaches raw_offer with source="safetywing"
- Pattern: MYSTES injects client → neuron calls it → neuron attaches raw_offer → returns normalized results

### Phase 3: CrossSellEngine
- New file: `cross_sell_engine.py` (~130 lines)
- Zero-cost deterministic recommendation engine — pure Python, no AI calls
- Rules: flight→hotel→car→activities→insurance, hotel→activities→car→insurance, car→insurance, activity→insurance→hotel, insurance→(terminal)
- Capability-aware: filters unavailable verticals via env-var check
- Destination-aware URLs: `/hotels?destination=FCO&check_in=2026-05-01`
- API: `recommend(vertical, destination, date, return_date)` and `for_concierge(vertical)` (single best)

### Phase 4: Concierge SDK Integration
- `GET /api/concierge/capabilities` — Returns which verticals have API credentials (5-min cache)
- Updated `ConciergeEngine` to accept optional `CrossSellEngine` parameter
- Dynamic cross-sell: CrossSellEngine provides intelligent recommendations, static JSON as fallback
- `_flow_to_vertical()` maps flow_ids to vertical names for engine lookup
- Updated `/api/concierge/message` to wire capabilities → CrossSellEngine → ConciergeEngine

### Phase 5: Tests (+40 new tests)
- `tests/test_cross_sell.py` (14 tests): rules, capabilities, URLs, concierge integration
- `tests/test_integration.py` (+7 tests): raw_offer passthrough (2), capabilities (3), cross-sell (1), updated cross_sell_present
- `picasso-sdk/tests/test_verticals.py` (+7 tests): CarsNeuronSearch (3), ActivitiesNeuronSearch (2), InsuranceNeuronSearch (2)

## Files Changed
| File | Action |
|------|--------|
| `server.py` | Fix 3 JS locations + add capabilities endpoint + wire CrossSellEngine |
| `picasso-sdk/anastasia/verticals/cars.py` | Add `search()` method |
| `picasso-sdk/anastasia/verticals/activities.py` | Add `search()` method |
| `picasso-sdk/anastasia/verticals/insurance.py` | Add `search()` method |
| `cross_sell_engine.py` | NEW — Zero-cost deterministic recommendation engine |
| `concierge_engine.py` | Accept CrossSellEngine, dynamic cross-sell in _render_flow() |
| `tests/test_cross_sell.py` | NEW — 14 tests |
| `tests/test_integration.py` | +7 tests for Build #182 |
| `picasso-sdk/tests/test_verticals.py` | +7 search method tests |

## What Still Needs Building
1. **Concierge chat bubble improvements** — Page-aware context (know which page user is on for smarter cross-sell)
2. **SearchOrchestrator multi-vertical** — Currently flight-specific; could add vertical-agnostic wrapper
3. **Booking confirmation cross-sell** — Show insurance/car/hotel after flight booking completes
4. **Analytics tracking** — Track cross-sell click-through rates for optimization
