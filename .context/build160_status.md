# Build #160 — Production Readiness Sprint: Three-Layer Architecture + PostgreSQL
# Date: 2026-03-11
# Type: ARCHITECTURE + INFRASTRUCTURE

## Summary
Restructured ANASTASiA SDK into clean three-layer architecture (clients / intelligence / API)
and added PostgreSQL support with STORAGE_BACKEND toggle. Email + Stripe are config-only.
Google Flights alternative already solved.

## What Changed

### 1. Three-Layer Architecture (clients/ package)
Created `picasso-sdk/clients/` — Layer 1 (dumb pipe API client SDKs):
- `clients/__init__.py` — re-exports all client classes
- `clients/redbox.py` — Picasso/Cockpit/Redbox client (moved from picasso/client.py)
- `clients/redbox_auth.py` — Redbox auth/TokenManager (moved from picasso/auth.py)
- `clients/duffel.py` — Duffel NDC client (moved from picasso/duffel.py)
- `clients/airgateway.py` — AirGateway client (moved from picasso/airgateway.py)
- `clients/kiwi.py` — Kiwi Tequila client (moved from picasso/kiwi.py)

Backward-compat stubs at old locations (`picasso/client.py`, etc.) — all existing
imports continue to work. New code should import from `clients/` directly.

### 2. PostgreSQL Support (STORAGE_BACKEND toggle)
- `db_models.py` (NEW) — SQLAlchemy ORM: Agency, UsageRecord, Subscription, AuditEntry
- `db_stores.py` (NEW) — DB-backed implementations: DBConfigStore, DBUsageTracker, DBBillingManager
- `db_stores.py:create_stores()` — factory function returns file or DB stores based on env
- `api.py` — updated to use `create_stores()` factory, conditional `init_db(app)`
- `scripts/migrate_to_db.py` (NEW) — one-time JSON→DB migration script
- `pyproject.toml` — added `db` optional dependency group (flask-sqlalchemy, psycopg2-binary)

**STORAGE_BACKEND=file (default)**: Uses existing file-based JSON stores. Zero change.
**STORAGE_BACKEND=db**: Uses PostgreSQL via SQLAlchemy. Set DATABASE_URL env var.

### 3. Memory Updates
- Added 4 critical rules to MEMORY.md: three-layer architecture, knowledge cards as
  compiled intelligence, deduplication funnel, Anthropic API cost centers

## Files Changed (picasso-sdk/)
| File | Action | LOC |
|------|--------|-----|
| `clients/__init__.py` | NEW | 36 |
| `clients/redbox.py` | NEW (moved from picasso/client.py) | ~2000 |
| `clients/redbox_auth.py` | NEW (moved from picasso/auth.py) | ~600 |
| `clients/duffel.py` | NEW (moved from picasso/duffel.py) | ~800 |
| `clients/airgateway.py` | NEW (moved from picasso/airgateway.py) | ~400 |
| `clients/kiwi.py` | NEW (moved from picasso/kiwi.py) | ~400 |
| `picasso/client.py` | REPLACED with stub | 13 |
| `picasso/auth.py` | REPLACED with stub | 8 |
| `picasso/duffel.py` | REPLACED with stub | 8 |
| `picasso/airgateway.py` | REPLACED with stub | 8 |
| `picasso/kiwi.py` | REPLACED with stub | 8 |
| `picasso/__init__.py` | UPDATED (version + docstring) | 20 |
| `picasso/agent/db_models.py` | NEW | 150 |
| `picasso/agent/db_stores.py` | NEW | 320 |
| `picasso/agent/api.py` | MODIFIED (store factory) | +10 |
| `scripts/migrate_to_db.py` | NEW | 130 |
| `pyproject.toml` | MODIFIED (packages, deps, description) | +8 |

## Tests
- **429 SDK tests PASSING** (0 failures, 1 warning)
- **56 consumer tests PASSING** (0 failures)
- **6 DB backend smoke tests PASSING** (DBConfigStore, DBUsageTracker, create_stores, delete, list_all)

## Config-Only Items (no code changes)
### Email Activation
`email_service.py` (777 lines) already fully built. Set these env vars on Render:
```
MAIL_ENABLED=true
MAIL_SERVER=smtp.gmail.com
MAIL_PORT=587
MAIL_USE_TLS=true
MAIL_USERNAME=<gmail>
MAIL_PASSWORD=<app password>
MAIL_DEFAULT_SENDER=noreply@mystes.app
```

### Stripe Live
Swap test keys for live in Render env vars:
```
STRIPE_SECRET_KEY=sk_live_...
STRIPE_PUBLISHABLE_KEY=pk_live_...
STRIPE_WEBHOOK_SECRET=whsec_... (new webhook for live)
B2B_STARTER_STRIPE_PRICE_ID=price_... (create $49/mo product)
```

## Deployment Steps (when ready)
1. Provision PostgreSQL for ANASTASiA on Render (or share phoenix-db)
2. Add env vars: `STORAGE_BACKEND=db`, `DATABASE_URL=postgresql://...`
3. Deploy new code
4. Run migration: `python scripts/migrate_to_db.py`
5. Remove Render disk (no longer needed)

## Architectural Insights Archived
- Three-layer architecture: clients (dumb pipes) / intelligence (knowledge cards) / MYSTES model
- Knowledge cards = compiled Claude intelligence — 95%+ operations at near-zero AI cost
- Deduplication funnel: all APIs → deduplicate → best price per itinerary → one MYSTES API feed
- Anthropic API only called for: dev terminal + admin troubleshooting
