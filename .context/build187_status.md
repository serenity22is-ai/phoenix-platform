# Build #187 — raw_offer Passthrough Hardening + Collections Tests

**Date**: 2026-03-17
**Tests**: 884 (392 consumer + 492 SDK), 0 failed
**New tests**: 44 (in tests/test_build187.py)

## What Was Done

### Investigation: raw_offer Passthrough Chain
Deep audit of the entire search → deal → booking pipeline. Found all 4 items from Build #180 roadmap are already implemented:
- SearchOrchestrator: wired in search.py:489
- BookingDispatcher: wired in server.py:6544
- Collections: routes_collections.py with 8 endpoints, registered at server.py:18008
- raw_offer: present on all 4 active search paths

### Bug Fix: AI Routes Registration (CRITICAL)
**`server.py`** — Restored `register_mystes_ai_routes()` call lost during server.py modularization (Build #167). The `/api/v1/ai/book-flight` endpoint was returning 404 in production — flight cards clicked by users couldn't create Deal records. Fixed by adding registration block after dev portal routes.

### Safety Guard: raw_offer Reconstruction
**`mystes_ai_api.py`** — Added defense-in-depth for missing `raw_offer` in `/api/v1/ai/book-flight`:
- If `raw_offer` dict is missing but top-level `fare_id`/`fare_search_id`/`offer_id` are present, reconstructs a minimal raw_offer with `_reconstructed: true` flag
- Logs warning-level message for monitoring
- If no booking references at all, logs warning but still creates Deal (graceful degradation)

### Frontend: Extended Flight Card Data
**`routes_flights.py`** — Added `picasso_gds`, `fare_id`, `fare_search_id`, `offer_id`, and `source` to the flight card JSON data passed to `bookThisFlight()`. Previously only `raw_offer` was forwarded — now the safety guard has fallback fields to reconstruct from.

### Tests: 44 New Tests
**`tests/test_build187.py`** — 9 test groups:
- `TestRawOfferSafetyGuard` (8): Full raw_offer, top-level reconstruction, Duffel offer_id, Kiwi booking_token, no-offer graceful, auth required, empty body
- `TestFlightCardData` (6): Page render, raw_offer, picasso_gds, fare_id, fare_search_id, source in card JS
- `TestCollectionsCRUD` (5): Page load, create, require name, delete, auth required
- `TestCollectionsSavedItems` (7): Flight, hotel, car, activity save, quick-save favorites, remove item, invalid vertical rejection
- `TestCollectionsSharing` (3): Toggle sharing, Collection model fields, SavedItem model fields
- `TestDealRawOfferStorage` (3): Picasso raw_offer, no offer data, Duffel offer
- `TestSearchPipelineOffers` (5): Path 1-4 raw_offer presence, safety guard source verification
- `TestFrontendPassthrough` (5): picasso_gds, fare_id, fare_search_id, offer_id, bookThisFlight API call
- `TestAIRoutesRegistration` (2): server.py registration, endpoint not-404

## Files Changed

| File | Change |
|------|--------|
| `server.py` | +6 LOC — AI routes registration (from mystes_ai_api) |
| `mystes_ai_api.py` | +18 LOC — raw_offer safety guard with reconstruction |
| `routes_flights.py` | +4 LOC — picasso_gds, fare_id, fare_search_id, offer_id, source in card data |
| `tests/test_build187.py` | +510 LOC — 44 tests across 9 groups |

## raw_offer Passthrough Status: RESOLVED

The chain is verified working on all active search paths:
- **Path 1** (ANASTASiA SearchOrchestrator): search.py:553 `"raw_offer": raw`
- **Path 2** (Picasso): search.py:771 `"raw_offer": {"fare_id": ..., "fare_search_id": ..., "source": "picasso"}`
- **Path 3** (Duffel): search.py:1223 `"raw_offer": {"offer_id": ..., "source": "duffel_ndc"}`
- **Path 4** (Kiwi): search.py:1344 `"raw_offer": {"booking_token": ..., "source": "kiwi_tequila"}`
- **Frontend**: routes_flights.py:416-421 forwards raw_offer + all booking refs in card data
- **Booking API**: mystes_ai_api.py:585-615 extracts + stores on Deal record
- **Safety guard**: mystes_ai_api.py reconstructs from top-level fields if raw_offer missing

## Build #180 Roadmap: ALL ITEMS COMPLETE

| Item | Status | Where |
|------|--------|-------|
| SearchOrchestrator wiring | Done (pre-existing) | search.py:489 |
| BookingDispatcher wiring | Done (pre-existing) | server.py:6544 |
| Collections/Wishlist routes | Done (pre-existing) | routes_collections.py, server.py:18008 |
| raw_offer passthrough | Verified + hardened | All 4 search paths + safety guard |
| AI routes registration | Fixed (was broken) | server.py |
