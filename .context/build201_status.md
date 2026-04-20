# Build #201 — Credential Network Wiring (Duffel + Picasso)
**Date**: 2026-03-17
**Status**: COMPLETE
**Tests**: 1,301 (775 consumer + 526 SDK), 0 failures

## Summary
Wired the credential network neuron into the live search and booking pipeline. MYSTES can now route search and booking through vault-stored credentials from the federated network. Test case: Duffel NDC + Picasso GDS. This is the defensive armor — credential routing makes deplatforming MYSTES a mutiny against the network's own members.

## What Was Built

### Phase 0: raw_offer Passthrough Bug Fix
- **server.py** — 3 surgical fixes:
  - `execute_automated_booking()`: Added Duffel fallback for raw_offer reconstruction from `deal.offer_id`
  - Single-leg deal creation (`api_create_deal()`): Enhanced `amadeus_offer_data` with fallback construction for Picasso/Duffel/Kiwi when no explicit `raw_offer` provided
  - Multi-leg deal creation: Same fallback construction for multi-leg `raw_offer`

### Phase 1: Revenue Model Alignment
- **revenue.py** — Complete rewrite from percentage-based (85/10/5) to flat fee + 70/30:
  - `FLAT_PLATFORM_FEE_USD = $2.50` (flat per routed booking, NOT percentage)
  - `ROUTER_PCT = 0.70` (business owner who acquired the customer)
  - `HOST_PCT = 0.30` (credential host, passive income)
  - Own credentials = 100% to owner, zero fee
  - `MIN_PLATFORM_FEE_USD = $1.00` floor
- **vault.py** — Added `list()` alias for `list_credentials()` (used by CredentialNetwork)

### Phase 2: DB Schema Extension
- **models.py Booking**: +7 columns: `booking_source`, `credential_id`, `owner_tenant_id`, `router_tenant_id`, `routing_result_id`, `routing_tier`, `routing_fee_usd`
- **models.py Deal**: +1 column: `booking_source`
- All nullable — zero migration risk

### Phase 3: CredentialRouter (NEW — ~280 LOC)
- **credential_router.py** — Glue layer between CredentialNetwork and dispatch pipeline
  - `get_routed_clients()` — For each source, checks own creds (Tier 1) then routes through network (Tier 2/3)
  - `build_client()` — Instantiates API clients from decrypted vault data (Duffel, Picasso, Kiwi, AirGateway)
  - `confirm_booking()` / `fail_booking()` — Wraps network execution lifecycle
  - Provider mapping: source names ↔ network provider IDs
  - Composite credential ID resolution: `tenant:provider` → actual vault UUID

### Phase 4: SearchOrchestrator Wiring
- **search_orchestrator.py** — Added `credential_router` + `requester_tenant_id` params to `search()`
  - When provided, calls router for network-sourced clients, merges into `clients` dict
  - `_build_raw_offer()` injects `_routing` metadata dict (result_id, credential_id, owner_tenant_id, routing_tier)
  - Routing metadata survives dedup (winner's raw_offer replaces loser's)

### Phase 5: Booking Execution Wiring
- **server.py execute_automated_booking()** — Credential routing intercept:
  - Checks `raw_offer._routing` for network routing metadata
  - Builds vault-backed client via CredentialRouter
  - After successful booking: persists routing fields to Booking model
  - Calls `confirm_booking()` for revenue tracking
  - Graceful fallback to default clients on any routing failure

### Phase 6: Consumer Search Entry Point
- **search.py search_global()** — Optional credential routing for B2B/APAi tenants:
  - When `user.tenant_id` exists, initializes CredentialRouter
  - Passes to orchestrator search call
  - MYSTES consumer path unchanged (no tenant_id → no routing)

### Phase 7: Integration Tests (28 tests)
- **test_credential_routing.py** — 12 test classes covering:
  - Own credentials Tier 1 (zero fee, 100% owner)
  - Cross-provider routing (Duffel via Picasso holder and vice versa)
  - Revenue split: flat $2.50 + 70/30 (5 tests)
  - Client building from vault credentials
  - `_routing` metadata injection and dedup survival
  - Booking confirm/fail flows
  - Vault `list()` alias
  - raw_offer fallback construction (Picasso, Duffel, Kiwi)
  - SearchOrchestrator credential_router param
  - Provider mapping correctness
  - Composite credential ID resolution
  - End-to-end revenue flow with tenant summaries

## Files Changed

| File | Action | LOC Changed |
|------|--------|-------------|
| `server.py` | MODIFY: raw_offer fallback + credential routing in booking | +80 |
| `picasso-sdk/anastasia/credentials/revenue.py` | REWRITE: flat $2.50 + 70/30 model | +25, -15 |
| `picasso-sdk/anastasia/credentials/vault.py` | MODIFY: add list() alias | +15 |
| `models.py` | MODIFY: +7 Booking cols, +1 Deal col | +10 |
| `picasso-sdk/anastasia/dispatch/credential_router.py` | NEW: glue layer | ~280 |
| `picasso-sdk/anastasia/dispatch/__init__.py` | MODIFY: add export | +2 |
| `picasso-sdk/anastasia/dispatch/search_orchestrator.py` | MODIFY: credential_router param + _routing metadata | +30 |
| `search.py` | MODIFY: credential router for B2B tenants | +15 |
| `picasso-sdk/tests/test_credential_routing.py` | NEW: 28 integration tests | ~400 |
| `picasso-sdk/tests/test_credential_vault.py` | MODIFY: align revenue tests to new model | ~20 |

**Total: ~880 LOC new/changed across 10 files**

## What This Enables
1. **Deplatforming defense** — If AERTiCKET strips our Picasso credentials, network members with their own Picasso creds fill the gap. MYSTES keeps booking.
2. **Credential sharing revenue** — APAi subscribers earn passive income when their credentials route other members' bookings. 70/30 split incentivizes both customer acquisition and credential hosting.
3. **Multi-source arbitrage** — B2B tenants access providers they don't have direct credentials for. OTA with only Duffel can now search Picasso via the network.
4. **Consolidator infrastructure** — This is what makes MYSTES a consolidator, not just an OTA. The credential network IS the consolidation layer.

## What Was NOT Changed
- `picasso_client.py` — Root Picasso client untouched
- `duffel_client.py` — Root Duffel client untouched
- `payments.py` — Consumer fee calculation unchanged (credential routing fee is separate)
- `network.py` — Already complete, no changes needed
- `dispatcher.py` — No changes (routing happens ABOVE dispatcher via client injection)
- Existing consumer flow — Zero impact when no `tenant_id`
