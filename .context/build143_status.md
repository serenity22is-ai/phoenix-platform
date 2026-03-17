# Build #143 — Duffel NDC Wired Into MYSTES Consumer OTA
**Date**: 2026-03-09
**Status**: COMPLETE
**Tests**: 56 passed (consumer) + 120 passed (SDK) = 176 total, 0 failures

## What This Build Does
Wires Duffel NDC (300+ airline direct connections) into the MYSTES consumer search pipeline
alongside Picasso/Redbox (GDS consolidator). Users now see flights from BOTH distribution
channels in a single unified result set — no UI changes, just more flights at better prices.

## Architecture — Dual-Source Consumer Search
```
User → MYSTES AI Chat → search_global()
    ├── Picasso/Redbox (GDS) → consolidator fares, 102-country POS arbitrage
    ├── Duffel (NDC) → NDC-direct fares, 300+ airlines
    ├── Google Flights → US retail price benchmark
    └── Smart Merge:
        ├── NDC matches GDS flight (airline+time ±15min)?
        │   ├── NDC cheaper → replace GDS price silently
        │   └── NDC more expensive → drop
        └── Unique NDC flight → add to results with estimated deal
```

## Files Modified

### 1. `main.py`
- Added `DUFFEL_AVAILABLE` / `DUFFEL_CONFIGURED` flags (same pattern as PICASSO_*)
- Imports `DuffelClient` from `duffel_client.py`

### 2. `search.py` — Core Integration (~120 LOC added)
- Added `DUFFEL_AVAILABLE`, `DUFFEL_CONFIGURED` to imports from main
- **Picasso+Duffel path** (when Picasso has results):
  - After Picasso search + Google comparison, fires Duffel search
  - Deduplicates by airline + departure time (±15 min window)
  - If NDC price < GDS price → replaces price, updates source to "ndc"
  - Unique NDC flights added with estimated markup deals
  - `source` field: "gds" (Picasso) or "ndc" (Duffel) on every flight
- **Duffel-only fallback** (when Picasso unavailable):
  - New standalone Duffel search path between Picasso and Amadeus fallback
  - Full flight formatting with estimated markup deals
  - Returns results with `data_sources: "duffel_ndc"`
- `data_sources` field now shows which sources contributed (e.g., "picasso_redbox+duffel_ndc")

### 3. `server.py` — UI (minimal)
- Deal payload includes `source` and `offer_id` for booking routing
- No visual source labels (user's request — flights just appear with same deal format)

### 4. `duffel_client.py` — Bug fix
- Added `None` check for outbound slice in `_parse_offer()` (some offers return None slices)

## Live Test Results
```
JFK → LAX, 2026-04-15:
  PICASSO: 20 flights from 8 airlines (GDS consolidator)
  GOOGLE:  15 US flights (price benchmark)
  MATCHED: 5 flights by airline+time
  DUFFEL:  7 NDC offers
    → 1 NDC price cheaper than GDS (Hawaiian: NDC $141 < GDS $198)
    → 1 unique NDC flight added
  TOTAL:   21 flights (19 GDS + 2 NDC), all with deal cards
```

## Key Design Decisions
1. **No UI source labels** — user doesn't need to know GDS vs NDC. Just sees more flights.
2. **Internal `source` field preserved** — for booking routing (Picasso vs Duffel booking flow)
3. **Duffel fires AFTER Picasso** — GDS is primary (arbitrage value), NDC supplements
4. **Smart dedup, not naive** — same airline within 15 min = same flight, keep cheaper
5. **Estimated markup for NDC** — 1.55x multiplier same as GDS flights without Google match
