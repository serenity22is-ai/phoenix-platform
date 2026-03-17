# Build #168 — CitizenSERP Extraction (2026-03-12)

## Summary
Surgically removed ALL CitizenSERP/P2P/node/helper code from the active MYSTES codebase. Archived to `citizenserp/` directory. Codebase now focused exclusively on MYSTES OTA + ANASTASiA API.

## Results
- **93 tests passing, 0 skipped, 0 failed** (was 56 passing + 78 skipped)
- **~2700+ lines of dead code removed** from active files
- **~35 files archived** to `citizenserp/`
- Server imports cleanly, all pages load

## Phase Breakdown

### Phase 1: Archive (~35 files → citizenserp/)
- Python: p2p_orchestrator, routes_p2p, routes_xrpl, node_consent_economy, node_consent_api, node_service, node_service_api, node_registry, node_yield_dashboard, node_data_processor, node_antidilution, helper_matching, helper_client, citizenserp_tasks, citizenserp_payouts, payout_disbursement, harvest_scheduler, free_browse_portal, data_marketplace, ad_intelligence, browsing_tiers, build_extension, data_quality_feedback, data_source_resolver, dispute_resolution, geographic_zones, hot_zone_economics, intelligence_feedback, payment_ramps, payment_compatibility, payment_compatibility_api, pricing_zones, serp_api
- Tests: test_p2p.py, test_extension_pipeline.py
- JS: mystes-node-client.js, mystes-node-capture.js, mystes-node-bridge.js

### Phase 2: models.py (~1800 lines removed)
- 38 model classes removed (HelperProfile through ZoneSignal)
- User columns removed: is_helper_node, xrpl_wallet_seed_encrypted, xrpl_wallet_created_at, node_referral_code, total_node_referrals, active_node_referrals
- CommercialAccount.p2p_enabled removed
- Payment.p2p_transaction_id FK removed
- 11 feature flags removed from init_default_flags()

### Phase 3: server.py (~350 lines removed)
- Top-level imports cleaned (HelperProfile, P2PTransaction, etc.)
- _inject_node_context() deleted
- Feature flags cleaned from _inject_feature_flags()
- Registration: removed is_helper_node, HelperProfile creation, node_consent_economy
- OAuth: removed node/helper blocks from provisioning and success response
- Account export/delete: removed wallet, P2P, helper export sections
- Booking: removed node_consent_economy fee allocation + activity logging
- Admin: removed antidilution routes, admin_security dashboard, harvest scheduler routes

### Phase 4: base_template.py (~80 lines removed)
- Nav: removed Wallet, Nodes, Helper, Earn links
- Banners: removed "Join the Mystes Network" + "Activate Your Node" banners with CSS/JS
- Scripts: removed node JS script tags + __MYSTES_NODE_CONFIG__

### Phase 5: payments.py (~160 lines removed)
- Removed P2PEscrowStatus enum
- Removed calculate_p2p_splits(), create_p2p_escrow(), verify_p2p_escrow_on_chain(), release_p2p_escrow()

### Phase 6: Secondary files
- **mystes_ai.py** (~500 lines): 15 tool definitions, handlers, 3 formatters, 3-phase economic model → simplified ARBITRAGE_FREE_QUERIES
- **celery_app.py**: 9 task routes, 12 scheduled tasks, 15 task functions removed
- **arbitrage_api.py**: replaced node_consent_economy import with CommercialAPIKey validation
- **arbitrage_search.py**: removed 5 CitizenSERP import blocks, stubbed _search_via_nodes()
- **airline_auth.py**: removed 3 node operator routes
- **commercial_auth.py**: removed SERP API (6 routes), Node Yield Dashboard (4 routes), Node Payouts/Quality (2 routes), Ad Intelligence (3 routes), Browsing Data Intelligence (7 routes), _check_browsing_rate_limit function
- **mystes_intelligence.py**: removed get_node_network(), get_proxy_usage()
- **mystes_agent.py**: simplified select_zones(), stubbed CitizenSERP dispatch, removed geographic_zones
- **commercial.py**: removed activate_helper_node(), cleaned get_referral_stats()
- **seed_db.py**: removed HelperProfile/P2P imports, HELPERS constant, helper profiles section, P2P transactions section

### Phase 7: Tests
- test_integration.py: removed phase2 skip machinery, test_earn_page, wallet/helper/p2p authenticated tests, TestWalletManagement, TestHelperFlow, TestP2PAPI, TestP2PBookingFlow, admin wallet/p2p/helpers tests, escrow test
- test_api_clients.py: removed test_node_yield_dashboard_loads

### Phase 8: Verification
- `python3 -c "from server import app; print('OK')"` — PASS
- `python3 -m pytest tests/ -v` — **93 passed, 0 skipped, 0 failed** (15.24s)
- No orphaned imports in active codebase (all CitizenSERP references only in citizenserp/)

## User Note
- User mentioned renaming ANASTASiA API to "APAi" — acknowledged, not yet implemented
