# Build #189 Status — MYSTES Live Flights Hardening + APAi Provisioning System

**Date**: 2026-03-17
**Tests**: 473 consumer + 498 SDK = **971 total**, 0 failures (+42 from Build #188)
**Status**: COMPLETE

---

## What Was Built

### Track 1: MYSTES Live Flights Hardening (~400 LOC)

**Phase 1: Passenger Data Validation** — `validation.py` (NEW, ~130 LOC)
- `validate_passenger_data(data, deal_type)` → `(bool, list[str])`
- Flight passengers: email regex, DOB in past, passport expiry ≥6 months, phone 7-15 digits, name no digits, gender M/F/X
- Hotels: name + email + optional phone
- Cars/activities: name + email + phone
- Wired into `server.py:6253` (complete_booking) — replaces basic missing-field check

**Phase 2: Webhook Idempotency** — `models.py` + `server.py` (~80 LOC)
- New `WebhookEvent` model: event_id (unique), event_type, processed_at, result_json
- Wired into `webhook_stripe()` (~line 8950) and `stripe_webhook()` (~line 16836)
- Duplicate event_id → immediate `{"received": True}` return
- Successful processing → WebhookEvent record inserted

**Phase 3: Booking Status API Enhancement** — `server.py` (~40 LOC)
- Enhanced existing `/api/v1/booking/<id>/status` with new fields:
  - `passenger_email`, `booked_at`, `created_at`, `deal_id`, `deal_type`
- Added admin override to security check (admins can view any booking)

**Phase 4: Production Environment Validation** — `scripts/validate_env.py` (NEW, ~130 LOC)
- Checks: SECRET_KEY, DATABASE_URL (PostgreSQL), Stripe keys, Picasso credentials, Duffel token, liteAPI, Redis, Anthropic, Render API key
- Database connectivity + table count verification
- Colored terminal output (pass/fail/warning)

**Phase 5: Health Monitor Enhancement** — `server.py` (~40 LOC)
- Picasso token health (age, validity, refresh time)
- Duffel API reachability status
- `"status": "degraded"` (200) for non-critical service failures
- Removed legacy Amadeus section
- Updated build number to 189

### Track 2: APAi Provisioning System (~500 LOC)

**Phase 6: Render API Provisioning** — `apai_provisioning.py` (NEW, ~280 LOC)
- `APAiProvisioner` class with full lifecycle:
  - `provision()` — Create PostgreSQL DB + web service on Render, set env vars, generate API key
  - `check_status()` — Poll Render service status
  - `suspend()` — Suspend deployment, deactivate API keys
  - `terminate()` — Terminate deployment permanently
- `verify_instance_key()` — SHA-256 hash lookup for credential routing auth
- Falls back to manual queuing when `RENDER_API_KEY` not set
- Replaced placeholder at `celery_app.py:757`

**Phase 7: Credential Auth Endpoints** — `server.py` + `models.py` (~150 LOC)
- New `APAiInstanceKey` model: key_id, api_key_hash (SHA-256), deployment_id (FK), tier_id, usage_count, last_used_at
- `POST /api/credential/search` — APAi instance flight search through MYSTES credential network
  - Auth: `X-APAi-Key` header → verify_instance_key()
  - Searches both Picasso (GDS) and Duffel (NDC)
  - No POS market codes returned (airline compliance)
- `POST /api/credential/book` — APAi instance booking through MYSTES credentials
  - Feature-gated via SDK FeatureGate
  - Routes to Duffel (NDC) or Picasso (GDS) based on source

**Phase 8: APAi Stripe Subscription** — `server.py` (~80 LOC)
- `POST /api/apai/subscribe` — Stripe checkout for APAi tiers (starter=$99, pro=$299, enterprise=$799)
- `GET /api/apai/billing` — Subscription status, tier info, API key usage stats, available tiers

**Phase 9: Admin Deployment Dashboard** — `server.py` (~80 LOC)
- `GET /admin/deployments` — List all TemplateDeployments with status badges
- `POST /admin/deployments/<id>/approve` — Trigger provisioning (Render API or manual fallback)
- `POST /admin/deployments/<id>/suspend` — Suspend active deployment

### Track 3: Tests (42 new tests)

**Phase 10: Validation Tests** — `tests/test_build189_validation.py` (NEW, 17 tests)
- TestFlightPassengerValidation (12): Valid data, missing fields, invalid email/DOB/gender/phone/passport
- TestHotelPassengerValidation (3): Valid guest, optional phone, no DOB required
- TestCarPassengerValidation (2): Valid driver, phone required

**Phase 11: Webhook + Booking Tests** — `tests/test_build189_webhook.py` (NEW, 7 tests)
- TestWebhookEvent (3): Create, duplicate rejection, lookup
- TestBookingStatusAPI (4): Authenticated access, enhanced fields, 404, unauthorized

**Phase 12: APAi Provisioning Tests** — `tests/test_build189_apai.py` (NEW, 18 tests)
- TestAPAiProvisioner (5): Manual fallback, available property, Render API mock, suspend, terminate
- TestAPAiInstanceKey (4): Hash verification, valid key, invalid key, usage tracking
- TestCredentialRoutingAPI (5): No key 401, invalid key 401, missing params 400, valid search, book 401
- TestAPAiSubscription (2): Invalid tier rejection, billing endpoint
- TestAdminDeployments (2): Admin auth guard, admin page render

---

## Files Changed

| File | Action | LOC | Track |
|------|--------|-----|-------|
| `validation.py` | NEW | ~130 | 1 |
| `apai_provisioning.py` | NEW | ~280 | 2 |
| `scripts/validate_env.py` | NEW | ~130 | 1 |
| `tests/test_build189_validation.py` | NEW | ~150 | 3 |
| `tests/test_build189_webhook.py` | NEW | ~220 | 3 |
| `tests/test_build189_apai.py` | NEW | ~430 | 3 |
| `models.py` | APPEND WebhookEvent + APAiInstanceKey | ~40 | 1+2 |
| `server.py` | MODIFY: validation, idempotency, booking API, credential endpoints, APAi subscription, admin, health, imports | ~300 | 1+2 |
| `celery_app.py` | MODIFY: replace provisioning placeholder | ~15 | 2 |

---

## Bugs Fixed During Build

1. **PicassoFlightClient → PicassoClient**: Credential endpoints referenced non-existent class names. Fixed in server.py (4 locations).
2. **DuffelFlightClient → DuffelClient**: Same issue. Fixed in server.py (4 locations).
3. **TemplateDeployment not imported**: Used in billing/admin endpoints but not in top-level import. Added to server.py imports.
4. **Test fixture DetachedInstanceError**: SQLAlchemy objects detached from session. Fixed by returning ID dicts from fixtures.
5. **CommercialAccount contact_email NOT NULL**: Test fixture missing required field. Added.

---

## Test Summary

| Suite | Count | Status |
|-------|-------|--------|
| Consumer (tests/) | 473 | 0 failures |
| SDK (picasso-sdk/tests/) | 498 | 0 failures |
| **Total** | **971** | **0 failures** |

New tests: 17 (validation) + 7 (webhook) + 18 (APAi) = **42 new tests**

---

## Architecture Delivered

```
APAi Instance (turnkey OTA)
    ↓ X-APAi-Key header
    ↓
POST /api/credential/search  ──→  PicassoClient (GDS) + DuffelClient (NDC)
POST /api/credential/book    ──→  Feature-gated by tier → route to provider
    ↑
    ↑ verify_instance_key() — SHA-256 hash lookup
    ↑
APAiInstanceKey model (per-deployment)
    ↑
APAiProvisioner → Render API (DB + service + env vars)
    ↑
Admin /admin/deployments → approve/suspend
    ↑
B2B subscriber → POST /api/commercial/deployment/request
```

Consumer MYSTES hardened with server-side validation, webhook idempotency, and enhanced health monitoring.
