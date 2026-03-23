# Build #184 — ANASTASiA Dev Portal Foundation + Launch Readiness
**Date**: 2026-03-17
**Tests**: 795 (303 consumer + 492 SDK), 0 failures
**Previous**: Build #183 — 768 tests

## What Was Built

### Track A: ANASTASiA Dev Portal

**Phase 1 — Data Models** (models.py)
- `DevPortalAccount` — separate from MYSTES User, bcrypt auth, billing tier (payg/builder/scale), Stripe metered billing fields, APAi subscriber flag + template config
- `DevPortalKey` — `dpt_` prefix API keys, bcrypt hashed, rate tracking
- `DevPortalConversation` — conversation container with token usage tracking
- `DevPortalMessage` — individual messages with model/timing metadata

**Phase 2 — AI Engine** (dev_portal_ai.py, NEW)
- `DevPortalAI` class — Claude Opus 4.6 terminal, raw HTTP to Anthropic API
- `ANASTASIA_DEVPORTAL_SYSTEM_PROMPT` — opsec-hardened deny list (fee structures, credential network, knowledge cards, internal architecture, business strategy, source code, customer data)
- `APAI_CONTEXT_TEMPLATE` — dynamic injection for APAi subscribers

**Phase 3 — Billing** (dev_portal_billing.py, NEW)
- PAYG: $0 + $0.15/query | Builder: $49/mo + 500 included ($0.12 overage) | Scale: $99/mo + 1500 included ($0.08 overage)
- `create_dev_portal_checkout()` — Stripe subscription checkout, dev mode fallback
- `record_query_usage()` — metered billing (every query PAYG, overage-only Builder/Scale)
- `check_quota()`, `get_usage_stats()` — usage dashboard data

**Phase 4-5 — Routes + Frontend** (routes_devportal.py, NEW ~800 LOC)
- Auth: `/dev/signup`, `/dev/login`, `/dev/logout` + `dev_portal_login_required` decorator
- Pages: `/dev` (landing), `/dev/terminal` (chat UI), `/dev/pricing` (tier cards), `/dev/api-keys`
- Chat API: `POST /api/dev/chat`, conversation CRUD, usage endpoint
- Billing: `/dev/subscribe`, `/dev/billing/success`, Stripe Customer Portal
- API Keys: generate `dpt_` keys, revoke
- Inline templates: dark terminal aesthetic, ANASTASiA branding, Cinzel/Outfit fonts

**Phase 6 — Webhooks** (server.py)
- Extended Stripe webhook handler with third branch for DevPortalAccount subscriptions
- Handles subscription lifecycle: active, cancelled, past_due

**Phase 7 — Config** (config.py)
- Dev portal pricing constants + Stripe Price ID env vars

### Track B: Launch Readiness

**Phase 8 — Booking Pipeline Smoke Tests** (tests/test_booking_pipeline.py, NEW)
- 5 tests: deal creation with raw offer, fare_id passthrough integrity, booking page, confirmation, Stripe checkout endpoint

**Phase 9 — Email Service** (email_service.py)
- `send_devportal_welcome()` — ANASTASiA-branded purple theme welcome email

**Phase 10 — Deployment Hardening** (server.py)
- Startup env var validation (warns, doesn't crash)

## Files Changed
| File | Action | LOC |
|------|--------|-----|
| models.py | Modified — 4 new models | +180 |
| dev_portal_ai.py | NEW — AI engine + system prompt | 201 |
| dev_portal_billing.py | NEW — Stripe metered billing | 267 |
| routes_devportal.py | NEW — Routes, auth, API, frontend | ~800 |
| server.py | Modified — webhooks + route registration | +70 |
| config.py | Modified — pricing config | +15 |
| email_service.py | Modified — welcome email | +30 |
| tests/test_devportal.py | NEW — 22 dev portal tests | 355 |
| tests/test_booking_pipeline.py | NEW — 5 booking tests | 140 |

**Total: ~2,058 LOC across 9 files (5 new, 4 modified)**

## Test Results
```
Consumer: 303 passed, 0 failed
SDK:      492 passed, 0 failed
Total:    795 passed, 0 failed (+27 from Build #183)
```

## Key Decisions
- DevPortalAccount is NOT linked to MYSTES User — anyone can use the terminal
- Opus 4.6 ONLY — no Sonnet option
- Opsec hardened — explicit deny list in system prompt
- APAi subscribers recognized via credentials, get contextual template help
- Dual auth: session (web) + dpt_ API keys (programmatic)
- Dev mode: billing works without Stripe keys (direct activation)

## Next Steps (Build #185)
- APAi template import and subscriber recognition flow
- Dev portal conversation persistence and export
- API key authentication for programmatic access testing
- App Store model: publish/review pipeline for ANASTASiA marketplace
