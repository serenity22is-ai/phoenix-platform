# Build #176 — SearchOrchestrator + Watchdog Endpoints
**Date**: 2026-03-12
**Status**: COMPLETE
**Tests**: 154 consumer + 429 SDK = 583 total, 0 failed

---

## What Was Built

The second ANASTASiA intelligence layer integration into MYSTES. Replaces the inline multi-source flight search orchestration with card-guided parallel dispatch + cross-source deduplication. Plus admin Watchdog endpoints for monitoring API health.

### SearchOrchestrator (`picasso-sdk/anastasia/dispatch/search_orchestrator.py`)
- Card-guided multi-source flight search with `ThreadPoolExecutor` parallelism
- Searches all available API sources simultaneously (Picasso, Duffel, Kiwi, AirGateway)
- Cross-source deduplication: same airline + departure ±15 min = keep cheapest
- Normalizes all results into standard MYSTES format with `raw_offer` booking references
- Source-specific cabin class mapping (ECONOMY/economy/M/7)
- Airline normalization for dedup (IATA codes + name variants → canonical form)
- Zero Anthropic API cost — pure Python + JSON knowledge cards

### search.py Wiring (Path 1 = ANASTASiA)
- `search_global()` now tries ANASTASiA SearchOrchestrator FIRST
- Builds adapter classes (`_PicassoAdapter`, `_DuffelAdapter`, `_KiwiAdapter`) that bridge MYSTES client functions to the orchestrator's `search_flights()` interface
- Orchestrator results converted to MYSTES display format (flight_id, deal objects, etc.)
- SerpAPI Google Flights comparison applied to orchestrator results for real deal pricing
- Estimated markup (1.55x) applied to unmatched flights
- Full MYSTES return format preserved (flights, deals, all_flights, proxy_results)
- Falls through to legacy per-source code if orchestrator fails

### Watchdog Admin Endpoints
- `GET /admin/watchdog` — Dashboard showing registered API providers
- `POST /admin/watchdog/run` — Trigger full sweep across all providers
- `POST /admin/watchdog/check/<provider_id>` — Check single provider
- All require admin authentication
- Returns JSON with change detection reports

---

## Files Created

| File | LOC | Purpose |
|------|-----|---------|
| `picasso-sdk/anastasia/dispatch/search_orchestrator.py` | 539 | Card-guided multi-source search + dedup |

## Files Modified

| File | Changes |
|------|---------|
| `picasso-sdk/anastasia/dispatch/__init__.py` | Added SearchOrchestrator export |
| `search.py` | Path 1 = ANASTASiA orchestrator, adapters for each client, deal calc on orchestrator results |
| `server.py` | 3 Watchdog admin endpoints (GET dashboard, POST run, POST check one) |
| `tests/test_integration.py` | +16 new tests (7 orchestrator + 5 wiring + 4 watchdog) |

## Test Results: 583 total (154 consumer + 429 SDK)

### New Tests (Build #176)
- `TestBuild176SearchOrchestrator` (7 tests): card loading, aliases, empty clients, mock search, dedup keeps cheapest, different airlines not deduped, failed source tracked
- `TestBuild176SearchWiring` (5 tests): orchestrator import in search_global, adapter classes, export, airline normalization, time extraction
- `TestBuild176WatchdogEndpoints` (4 tests): admin auth required for all 3 endpoints, route registration

## Architecture After This Build

```
MYSTES (search.py)
  └── search_global(origin, destination, date, ...)
       ├── Path 1: ANASTASiA SearchOrchestrator
       │    ├── Build client adapters (Picasso, Duffel, Kiwi)
       │    ├── orchestrator.search() → parallel execution + dedup
       │    ├── Convert to MYSTES display format
       │    ├── SerpAPI comparison → real deals
       │    ├── Estimated markup → estimated deals
       │    └── Return unified results
       └── Fallback: Legacy per-source code (Picasso → Duffel → Kiwi)

MYSTES (server.py) — Admin
  ├── GET  /admin/watchdog           → Provider health dashboard
  ├── POST /admin/watchdog/run       → Full sweep (all providers)
  └── POST /admin/watchdog/check/<id> → Single provider check
```

## What This Enables
- **Parallel multi-source search** — all APIs searched simultaneously instead of sequentially
- **Cross-source deduplication** — same flight from 3 providers = keep cheapest, user sees ONE result
- **Card-guided dispatch** — adding new API = add knowledge card + client adapter → works
- **Admin API monitoring** — daily watchdog sweep from admin panel, detect API drift before it breaks bookings
- **Graceful degradation** — orchestrator failure → existing code still works

## NOT in this build (deferred):
- Client consolidation (root clients → SDK clients delegation)
- Cron-based automatic watchdog scheduling (manual trigger via admin for now)
- AirGateway adapter in search.py (no client available yet in MYSTES)
- Hotel/car search through orchestrator (flights only for now)

## AI Cost Architecture Documented
- `memory/ai_cost_architecture.md` — Complete reference for when AI is/isn't used
- 6 cost centers: Trip Planner AI Pitch, Admin Portal, Dev Portal, AutoLearner, UpdatePipeline, Daily Watchdog
- Consumer NEVER triggers AI — form-based search → cards → booking = zero AI
- Trip planner: card templates (free) → AI pitch (Travel+ 5/month) → $0.99 microtransaction extras

## Strategy Discussion Captured
- B2B markup engine: subscriber sets price, customer books, spread routed back as cash
- OTA conversion model: traditional OTAs must adopt MYSTES model or lose to phone-only competitors
- "The High Schooler" use case validated: $49/mo + phone + debit card = vacation package business
- All documented in `memory/ai_cost_architecture.md`
