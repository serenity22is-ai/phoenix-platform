# Build #147 — Update Call System (Self-Maintaining SDK)
**Date**: 2026-03-09
**Status**: COMPLETE — 311 tests passing (90 new)

## What Was Built
ANASTASiA's Update Call System — autonomous SDK maintenance engine that detects API provider changes, updates knowledge cards and client code, tests everything, and deploys. Fully autonomous — no human approval gates.

## Components Created

### 1. JSON Knowledge Cards (8 files)
- `anastasia/modules/cards/picasso_redbox.json`
- `anastasia/modules/cards/duffel_ndc.json`
- `anastasia/modules/cards/kiwi_tequila.json`
- `anastasia/modules/cards/airgateway_ndc.json`
- `anastasia/modules/cards/mystifly.json`
- `anastasia/modules/cards/travelfusion.json`
- `anastasia/modules/cards/tripstack.json`
- `anastasia/modules/cards/liteapi_hotels.json`

Machine-readable, machine-writable. Enables autonomous updates without touching Python code. Extra fields (changelog_url, docs_url, sandbox_probe_endpoints) consumed by Watchdog.

### 2. APIWatchdog (`anastasia/knowledge/watchdog.py`, ~780 LOC)
4-signal drift detection engine:
- **Schema Probing**: Test queries against sandbox APIs, compare JSON schemas
- **Changelog Monitoring**: Fetch + Claude Opus 4.6 analysis of provider docs
- **Error-Rate Detection**: Real-time EventBus subscriber (BOOKING_FAILED, INTEGRATION_FAILED)
- **Version Header Tracking**: Extract API-Version headers from responses

Key classes: `APIWatchdog`, `WatchdogConfig`, `SchemaSnapshot`, `SchemaDiff`, `DetectedChange`, `WatchdogReport`, `ProviderStatus`

### 3. UpdatePipeline (`anastasia/knowledge/update_pipeline.py`, ~937 LOC)
7-stage autonomous lifecycle:
DETECT → ANALYZE → GENERATE → TEST → DEPLOY → VERIFY → MONITOR

Key classes: `UpdatePipeline`, `FileUpdate`, `UpdateAnalysis`, `TestResult`, `DeployResult`, `UpdateRecord`

`PROVIDER_FILE_MAP` maps each provider to its client/tools/knowledge/card files.

### 4. Knowledge Neuron Wiring (`anastasia/knowledge/__init__.py`)
- APIWatchdog + UpdatePipeline added as sub-components
- Auto-registers all providers from JSON cards on startup
- Health check includes watchdog status + pipeline status
- New public accessors: `mod.watchdog`, `mod.update_pipeline`

### 5. API Endpoints (10 new routes in `picasso/agent/api.py`)
- `GET /api/v1/updates/status` — Overall watchdog + pipeline status
- `GET /api/v1/updates/providers` — List all monitored providers
- `POST /api/v1/updates/check` — Trigger check for ALL providers
- `POST /api/v1/updates/check/<provider_id>` — Check specific provider
- `GET /api/v1/updates/history` — Full update history (with filters)
- `GET /api/v1/updates/pending` — In-progress updates
- `GET /api/v1/updates/<update_id>` — Specific update details
- `POST /api/v1/updates/<update_id>/rollback` — Rollback a specific update
- `POST /api/v1/updates/daily-cycle` — Trigger daily update cycle
- `GET /api/v1/updates/schemas` — Current schema baselines

### 6. New EventTypes (9 added to `anastasia/core/events.py`)
- API_DRIFT_DETECTED, API_UPDATE_STARTED, API_UPDATE_GENERATED
- API_UPDATE_TESTED, API_UPDATE_DEPLOYED, API_UPDATE_VERIFIED
- API_UPDATE_FAILED, API_UPDATE_ROLLED_BACK, API_ERROR_RATE_SPIKE

### 7. flight_modules.py Rewrite
- JSON loader functions: `load_card_from_json()`, `load_all_json_cards()`, `load_card_raw()`, `save_card_json()`, `get_card_path()`
- `CARDS_DIR = Path(__file__).parent / "cards"`
- Python builder functions retained as fallbacks
- `build_all_flight_modules(from_json=True)` loads from JSON first

### 8. Test Files (90 new tests)
- `tests/test_watchdog.py` — 39 tests (schema extraction, comparison, drift detection, persistence, events)
- `tests/test_update_pipeline.py` — 23 tests (analysis, generation, testing, deployment, rollback, history)
- `tests/test_card_json.py` — 28 tests (loading, saving, roundtrip, validation, builder parity)

## Test Results
311 passed, 0 failed, 1 warning (PytestCollectionWarning for TestResult dataclass), 0.48s

## Architecture Decision: Knowledge Cards Are Foundational
Knowledge cards are NOT just API client metadata — they're the pre-computed understanding layer for Claude Opus 4.6. Instead of re-reading 1000+ LOC per query, Claude reads a few KB of structured cards. This saves Anthropic API tokens, speeds up responses, and improves routing accuracy. The Update Call System keeps this knowledge current autonomously.

## Vision: Proprietary Knowledge Cards for Customers
Extending knowledge cards to customer codebases is the natural next step:
- Customer connects codebase via daemon/admin terminal
- ANASTASiA generates knowledge cards for their auth, payments, UI, DB schema
- Cards are tenant-scoped — stored locally on customer's server, never transmitted
- "Powered by ANASTASiA" = invisible infrastructure that adapts to any codebase
- SaaS tiering: premium subscribers get the Update Call System (auto-maintenance)
