# Build #180 — ANASTASiA Integration Architecture Decision
**Date**: 2026-03-17
**Status**: DISCUSSION ONLY — interrupted by API 500/529 errors (context too heavy)

---

## Context
User performed an audit of what ANASTASiA SDK already provides vs what MYSTES consumer has, and asked whether to wire MYSTES through ANASTASiA rather than building parallel routes.

## The Audit Results

### ANASTASiA Already Has (SDK Layer — ALL BUILT)
| Feature | SDK Component | Status |
|---------|--------------|--------|
| Unified Search | SearchDispatcher — fans out to all verticals in parallel | Built |
| Flight Orchestration | FlightsNeuron — 7 API sources, module routing | Built |
| Hotel Orchestration | HotelsNeuron — liteAPI + extensible | Built |
| Bundle Engine | BundleBuilder — multi-vertical packages with tier pricing | Built |
| Booking Dispatch | BookingDispatcher — routes via knowledge cards, zero AI cost | Built |
| Passenger Transform | PassengerTransformer — MYSTES format → provider format | Built |
| 91+ API Endpoints | POST /api/v1/search, bundles, chat, assist | Built |

### MYSTES Consumer Social Features (DON'T belong in SDK)
| Feature | DB Models | Routes | Status |
|---------|-----------|--------|--------|
| Trip Planner | 6 tables (TripPlan, TripMember, TripItem, TripCart, TripCartAssignment, TripReceipt) | 0 routes | Needs UI routes |
| Collections/Wishlist | 2 tables (Collection, SavedItem) | 0 routes | Needs UI routes |
| Friends | 1 table (Friendship) | 0 routes | Needs UI routes |
| Google Reviews | Built (Build #178) | Built | DONE |
| Referral Cards | Built (Build #179) | Built | DONE |

### What Needs Rethinking (from Build #174 plan)
- **Car Rentals** — Don't build routes_cars.py with direct discover_cars_client calls. Create CarsNeuron in ANASTASiA SDK, then MYSTES calls SearchDispatcher
- **Activities** — routes_activities.py already calls Viator directly. Should be wrapped as ActivitiesNeuron
- **Insurance** — Same: InsuranceNeuron wrapping safetywing_client.py
- **Automated Booking** — Instead of ad-hoc Duffel/Picasso paths in server.py, route through BookingDispatcher
- **Search** — MYSTES's search.py:search_global() duplicates what SearchDispatcher already does

### What Genuinely Needs Building at MYSTES Layer
1. Trip Planner UI routes (consumer social feature)
2. Collections/Wishlist UI routes (consumer social feature)
3. Friends UI routes (consumer social feature)
4. 3 new ANASTASiA neurons (Cars, Activities, Insurance) wrapping existing clients
5. MYSTES search/booking integration with ANASTASiA SDK instead of direct client calls

## Decision Direction (agreed before API errors)
- **YES, integrate through ANASTASiA** — user confirmed wanting to make it work with ANASTASiA
- Product boundary holds: MYSTES = face, ANASTASiA = brain
- Build #174's approach of building parallel routes was wrong direction
- The raw_offer passthrough bug (flight cards don't send fare_id/offer_id to Deal record) blocks automated booking regardless — needs fixing first

## Critical Bug Identified
**raw_offer passthrough**: Flight search results don't carry fare_id/offer_id into the Deal record, so when user clicks "Book", the booking system has no reference to pass to BookingDispatcher/Duffel/Picasso. This must be fixed before automated booking works.

## Next Steps (for Build #180 proper)
1. Fix raw_offer passthrough bug (fare_id/offer_id into Deal records)
2. Wire MYSTES search to call ANASTASiA SearchOrchestrator (already partially done in Build #176)
3. Wire MYSTES booking to call ANASTASiA BookingDispatcher
4. Build Trip Planner UI routes (consumer social — MYSTES only)
5. Build Collections/Wishlist UI routes (consumer social — MYSTES only)
6. Build Friends UI routes (consumer social — MYSTES only)
7. Create CarsNeuron, ActivitiesNeuron, InsuranceNeuron in ANASTASiA SDK

## API Error Notes
- Session crashed with repeated 500s and 529 (overloaded) errors
- Cause: context window too heavy — MEMORY.md alone is 450+ lines (limit 200), plus multiple large system-reminder injections per message
- MEMORY.md needs trimming: move detailed content to topic files, keep index under 200 lines

---

## Current Test Count: 611 (182 consumer + 429 SDK), 0 failed
## Current Build Number: #179 (last completed code build)
