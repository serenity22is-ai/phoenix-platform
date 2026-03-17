# Build #145 — Module Registry + Director Architecture
**Date**: 2026-03-09
**Status**: COMPLETE
**Tests**: 176 passed (SDK) + 90 passed (consumer, 13 pre-existing failures) = 266 passing

## What This Build Does

### ANASTASiA Module Registry — Dynamic API Integration System
Built the core architecture for ANASTASiA's universal API module system. Instead of
hardcoded client wiring, APIs are now registered as **modules** with **knowledge cards**
that ANASTASiA reads to dynamically create search/booking pipelines.

This is the foundation for the user's vision: "ANASTASiA can integrate ANY API call
system through our single directory."

## Architecture

```
Customer Credentials → Module Registry → Module Director → BookingAgent
                          │                    │
                          │                    ├── plan_search() → SearchPlan
                          │                    ├── route_booking() → BookingRoute
                          │                    └── generate_system_prompt() → Claude KB
                          │
                          ├── Knowledge Cards (8 systems)
                          │   ├── Picasso/Redbox (GDS, priority 100)
                          │   ├── Duffel NDC (NDC, priority 80)
                          │   ├── Kiwi Tequila (Aggregator, priority 60)
                          │   ├── Mystifly OnePoint (GDS, priority 90)
                          │   ├── AirGateway NDC (NDC, priority 50)
                          │   ├── Travelfusion (Direct, priority 55)
                          │   ├── TripStack (Aggregator, priority 45)
                          │   └── liteAPI Hotels (Wholesaler, priority 80)
                          │
                          └── Client Factories (auto-instantiate when credentials set)
```

## Files Created

### 1. `picasso-sdk/anastasia/modules/__init__.py`
- Package init with exports: ModuleRegistry, APIModule, KnowledgeCard, ModuleDirector

### 2. `picasso-sdk/anastasia/modules/registry.py` (~400 LOC)
- **KnowledgeCard** dataclass — structured metadata per API
  - to_dict(), from_dict(), to_prompt() (generates Claude-readable summary)
  - Fields: module_id, name, vendor, vertical, source_type, auth_type, credential_env_vars,
    capabilities, carrier_count, passenger_format, date_format, priority, strengths,
    weaknesses, best_for, quirks, booking_steps, readiness, confidence
- **APIModule** — bundles knowledge card + client factory + tools + knowledge prompt
  - check_configured() — verifies all env vars are set (min 5 chars)
  - load() / unload() — instantiate/release client via factory
- **ModuleRegistry** — thread-safe central module management
  - register(), unregister(), get(), list_modules() (filterable by vertical/source_type/configured)
  - refresh_credentials(), load_all_configured(), get_tools(), get_knowledge_prompts()
  - get_status(), to_dashboard(), persistence (save/load cards to JSON files)
- **Enums**: VerticalType (7), SourceType (6), AuthType (6)

### 3. `picasso-sdk/anastasia/modules/director.py` (~340 LOC)
- **ModuleDirector** — ANASTASiA's intelligent API orchestration engine
  - plan_search() → SearchPlan (prioritized module list + merge strategy)
  - route_booking() → BookingRoute (which module handles a specific booking)
  - can_search() / can_book() — per-vertical capability queries
  - get_capabilities() — capability matrix across all modules
  - get_verticals() — status of all verticals with configured/total counts
  - generate_system_prompt() — synthesizes Claude prompts from all knowledge cards
  - generate_dashboard() — admin-facing text dashboard
- **SearchPlan** dataclass — modules, primary, benchmark, merge_strategy, dedup_window
- **BookingRoute** dataclass — module_id, booking_steps, passenger_format, date_format

### 4. `picasso-sdk/anastasia/modules/flight_modules.py` (~470 LOC)
- Knowledge cards for 8 API systems across 2 verticals:
  - **Flights (7)**: Picasso, Duffel, Kiwi, Mystifly, AirGateway, Travelfusion, TripStack
  - **Hotels (1)**: liteAPI
- Each card includes full metadata: capabilities, auth, passenger format, quirks, booking flow
- Factory functions: build_all_flight_modules(), build_all_hotel_modules(), build_all_modules()

### 5. `picasso-sdk/tests/test_modules.py` (~56 tests)
- TestKnowledgeCard: creation, serialization, roundtrip, prompt generation
- TestAPIModule: configured/unconfigured, load/unload, short credential rejection
- TestModuleRegistry: register, list, filter, refresh, tools, persistence
- TestModuleDirector: plan search, route booking, capabilities, dashboard
- TestFlightModules: all cards validated, unique IDs, unique priorities
- TestEndToEnd: full pipeline with single/multi/all sources configured

## Files Modified

### 6. `picasso-sdk/picasso/agent/api.py`
- Added imports for Module Registry
- Initialize ModuleRegistry + ModuleDirector after client creation
- Register all 8 known modules with client factories and tool/knowledge bindings
- Pass module_director to BookingAgent
- 4 new API endpoints:
  - `GET /api/v1/modules` — list all modules with credential status
  - `GET /api/v1/modules/dashboard` — Director's dashboard + capabilities
  - `POST /api/v1/modules/search-plan` — optimal search plan for a vertical
  - `POST /api/v1/modules/refresh` — re-check all credentials

### 7. `picasso-sdk/picasso/agent/orchestrator.py`
- Added `module_director` parameter to BookingAgent.__init__()
- Director's generated system prompt appended to knowledge base when available
- Backward compatible — director is optional

## API Endpoints Added
| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | /api/v1/modules | Master | List all modules + credential status |
| GET | /api/v1/modules/dashboard | Master | Director dashboard + capabilities |
| POST | /api/v1/modules/search-plan | API Key | Optimal search plan for a vertical |
| POST | /api/v1/modules/refresh | Master | Re-check all credentials |

## Metrics
- **8 knowledge cards** across 2 verticals (7 flights + 1 hotel)
- **56 new tests** — all passing
- **176 total SDK tests** — all passing, 0 regressions
- **48 API endpoints** (was 44)
- **~1,200 LOC** new code (registry + director + cards + tests)
- **3 production-ready modules** (Picasso, Duffel, Kiwi) + 4 discovered + 1 hotel

## Key Design Decisions
1. **KnowledgeCard is the unit of intelligence** — everything ANASTASiA knows about an API
2. **Credential-driven activation** — set env vars → module goes live instantly
3. **Director reads cards, doesn't hardcode** — adding a new API = adding a knowledge card
4. **Priority-based routing** — GDS arbitrage (100) > multi-GDS (90) > NDC (80) > aggregator (60)
5. **Merge strategy adapts** — "cheapest_wins_with_arbitrage" when POS module is configured
6. **Thread-safe registry** — concurrent access supported for multi-agency server
7. **Backward compatible** — module_director is optional on BookingAgent
