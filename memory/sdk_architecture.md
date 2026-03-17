# ANASTASiA SDK Architecture — Quick Reference
**Updated**: Build #148 (2026-03-09)
**Total**: 62K LOC, 80+ Python files, 16 neuron modules
**Root**: `picasso-sdk/anastasia/` (neurons) + `picasso-sdk/picasso/` (agent/clients)

## Core Architecture Decisions
- **Sealed Daemon Runtime**: Daemon is an encrypted black box. All integration code lives inside, encrypted in ANASTASiA Native Format (ANF). Customer never sees daemon internals — only results.
- **ANF (ANASTASiA Native Format)**: Proprietary binary serialization + AES-256-GCM. Two layers: even if encryption is broken, binary format is meaningless without ANASTASiA's deserializer.
- **Dual-Split Key**: Decryption requires cloud_master_key + subscription_token + daemon_id. No single party can decrypt alone.
- **One sandbox per client**: ANASTASiA builds their system. 30-day cloud courtesy after sandbox ends. After that, customer holds their own encrypted ANF blob. Restore anytime with active subscription.
- **Customer codebase untouched**: ANASTASiA never modifies their code. She builds bridges INSIDE the daemon that connect to their systems from outside.

## Platform Bootstrap
- `platform.py` (344 LOC) — `AnastasiaPlatform`: registers 16 neurons, topological init
- `core/registry.py` (204 LOC) — `ModuleRegistry` + `NeuronModule` ABC
- `core/events.py` (244 LOC) — `EventBus` (pub/sub, 74 EventTypes), `Event` dataclass
- `core/types.py` (587 LOC) — Shared enums + 10 dataclasses (SystemProfile, TechStack, BridgeContract, etc.)

## 16 Neuron Modules (all zero inter-neuron dependencies)

### 1. Knowledge (`knowledge/`, 5 files, ~4.5K LOC)
- `profiles.py` (1250) — ProfileStore: CRUD for SystemProfile objects (JSON on disk)
- `learning.py` (929) — LearningPipeline: extract tech stacks, API patterns from codebases
- `catalog.py` (~400) — KnowledgeCatalog: queryable marketplace of known systems
- `auto_learner.py` (1380) — AutoLearner: 5-stage Claude-powered API reverse-engineering
- `watchdog.py` (780) — APIWatchdog: 4-signal drift detection (schema/changelog/errors/version)
- `update_pipeline.py` (936) — UpdatePipeline: 7-stage autonomous update lifecycle
- `card_security.py` — Card encryption, service-binding, churn protection

### 2. Bridge (`bridge/`, 6 files, ~2.3K LOC)
- `protocol.py` (360) — BridgeProtocol: full lifecycle (create/accept/sync/propose/terminate)
- `registry.py` (410) — BridgeRegistry + BridgeInstance: active bridge tracking
- `orchestrator.py` (540) — BridgeOrchestrator: generates entity-scoped integration proposals
- `firewall.py` (390) — IPFirewall: classify/sanitize/audit all bridge traffic
- `contracts.py` (326) — ContractManager: bilateral IP agreements
- `extractor.py` (~300) — StructuralKnowledgeExtractor: route/model/auth/integration extraction

### 3. Daemon (`daemon/`, 4 files, ~2.5K LOC)
- `executor.py` (1112) — DaemonExecutor: permission-checked file I/O, git, commands, codebase scan
- `permissions.py` (452) — PermissionManager: DENY-by-default, permanent blocklists
- `protocol.py` (~400) — DaemonProtocol: cloud ↔ daemon communication
- `cli.py` (612) — CLI for daemon management

### 4. Tenancy (`tenancy/`, 3 files, ~1.7K LOC)
- `hierarchy.py` (588) — TenantHierarchy: Master→Consolidator→Agency tree, JSON persistence
- `provisioning.py` (700) — TenantProvisioning: onboard/deprovision, API key gen (ana_ + 48 hex)
- `isolation.py` (443) — DataIsolation: access control, plan-based resource limits, usage tracking

### 5. Payments (`payments/`, 7 files, ~2K LOC)
- `detector.py` (562) — PaymentDetector: identify Stripe/Adyen/Square/etc from code/config/deps
- `adapter.py` — PaymentAdapter ABC
- `adapters/` — Stripe, Adyen, Square, PayPal, Braintree concrete adapters
- `reconciliation.py` (605) — ReconciliationEngine: transaction tracking

### 6. Intelligence (`intelligence/`, 3 files, ~1.7K LOC)
- `aggregator.py` (668) — PricingAggregator: anonymized price observations
- `trends.py` (712) — TrendAnalyzer: seasonality, anomalies, predictions
- `alerts.py` (~300) — AlertEngine: price drop notifications

### 7. Integrator (`integrator/`, 4 files, ~2.8K LOC)
- `analyzer.py` (931) — CodebaseAnalyzer: scans customer code for integration points
- `generator.py` (1271) — CodeGenerator: produces integration code
- `templates.py` (639) — IntegrationTemplates: reusable patterns
- `approval.py` (~400) — ApprovalGate: admin approval before execution

### 8. Compliance (`compliance/`, 3 files, ~1.5K LOC)
- `regulations.py` (665) — RegulationEngine: PCI DSS, GDPR, IATA BSP, CCPA, PSD2
- `audit.py` (604) — ComplianceAudit: append-only SHA-256 hash chain
- `pii.py` (~300) — PIIProtector: regex detection/masking

### 9. Resilience (`resilience/`, 4 files, ~1.2K LOC)
- `circuit_breaker.py` — CircuitBreaker + CircuitBreakerRegistry
- `fallback.py` — FallbackManager: cached results + alternatives
- `queue.py` — BookingQueue: retry on recovery
- `health.py` — HealthMonitor: background health checks

### 10. Portability (`portability/`, 2 files, ~1.5K LOC)
- `migration.py` (924) — MigrationTool: transform between GDS formats
- `export.py` (591) — DataExporter: bookings/configs to JSON/CSV/XML

### 11. Sandbox (`sandbox/`, 2 files, ~1.1K LOC)
- `mock_data.py` (914) — MockDataProvider: deterministic test data
- Trial management, isolated environments

### 12. Credits — Booking fee accounting
### 13. Credential Network (`credentials/`, NEW Build #148)
### 14. SaaS Tiering (`saas/`, Build #148, Starter scrapped #149 — 3 tiers: Free/Pro/Enterprise)

## Agent Layer (`picasso/agent/`, 15 files, ~10K LOC)
- `api.py` (2592) — 54+ REST endpoints (largest file — needs breakup)
- `billing.py` (1050) — BillingManager: Stripe subscriptions, 2 plans (Pro/Enterprise), usage metering
- `pricing.py` (243) — PricingModel: 5 markup strategies
- `config.py` (236) — AgencyConfig: per-tenant OTA settings
- `orchestrator.py` (925) — AgentOrchestrator: routes user intents to tools
- `assist.py` (1146) — AssistEngine: Claude Opus 4.6 AI agent
- `dashboard.py` (1342) — Dashboard HTML + admin views
- `consumer_ui.py` (1123) — Consumer-facing OTA UI
- `onboarding.py` (857) — Guided setup wizard
- `tools.py` (586) — 16 Picasso Redbox tools
- `duffel_tools.py` — Duffel-specific tools
- `kiwi_tools.py` — Kiwi-specific tools
- `airgateway_tools.py` — AirGateway-specific tools
- `analytics.py` (605) — Usage/revenue analytics

## Client Layer (`picasso/`, 4 files)
- `client.py` (1876) — PicassoClient: Redbox API wrapper
- `duffel.py` (822) — DuffelClient: NDC API wrapper
- `kiwi.py` (~400) — KiwiClient: Tequila API wrapper
- `airgateway.py` (~300) — AirGatewayClient: NDC wrapper
- `auth.py` (680) — PicassoAuth: Keycloak + TOTP auto-login

## Knowledge Cards (JSON, machine-updatable)
- `modules/cards/` — 8 provider cards: picasso_redbox, duffel_ndc, kiwi_tequila, airgateway_ndc, mystifly, travelfusion, tripstack, liteapi_hotels

## Test Suite
- `tests/` — 311+ tests (0.48s), pytest
- Key test files: test_modules, test_bridge, test_bridge_simulation, test_auto_learner, test_watchdog, test_update_pipeline, test_card_json

## Key Patterns
- All neurons: NeuronModule ABC → register with ModuleRegistry → initialize via EventBus
- All comms: EventBus pub/sub (63 EventTypes across 11 categories)
- Storage: JSON files on disk (~/.anastasia/), not database
- Security: DENY-by-default permissions, encrypted credentials, firewall on all bridge traffic
- API keys: "ana_" + 48 hex (192-bit), SHA-256 hashed for storage
