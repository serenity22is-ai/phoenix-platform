# Build #193 — APAi Pitch Page + B2B/APAi Boundary Fix
**Date**: 2026-03-17
**Tests**: 1,064 (566 consumer + 498 SDK), 0 failed, 3 skipped
**Status**: COMPLETE

## What This Build Does
Fixes the architectural violation from Build #186 where B2B subscribers ($49-$199/mo) had access to turnkey OTA deployment — which is APAi-only ($299-$599/mo). Adds a dedicated APAi pitch page on MYSTES for prospective OTA operators.

## Changes

### Phase 1: Deployment Removed from B2B (routes_business.py)
- Deleted entire deployment section (~260 lines): `business_deployment()`, `api_request_deployment()`, `api_deployment_status()`, `_render_deployment_page()`
- Replaced "Deploy Your OTA" button → "Upgrade to APAi" link pointing to `/apai`
- Fixed B2B tier table: Starter/Professional/Enterprise/Partner → Starter($49)/Growth($99)/Volume($199)
- Fixed "Need Full API Access?" link: external `anastasia-api.onrender.com` → internal `/apai`

### Phase 2: APAi Pitch Page (server.py)
- New `APAI_PITCH_CONTENT` template (~130 lines HTML/CSS)
- Public route `GET /apai` — no auth required (marketing page)
- Hero: "Launch Your Own Branded OTA" + "Click. Pay. Deploy."
- 6 value prop cards: No IATA, No Volume Minimums, No Consolidator Gatekeeping, ANASTASiA Dev Terminal, Immutable Core, Full Stack OTA
- 5-step deployment visualization
- Pricing cards: APAi Pro ($299/mo) + APAi Enterprise ($599/mo) — ALL PROVISIONAL
- B2B → APAi graduation section

### Phase 3: Deployment Routes Moved to APAi-Gated Flow (server.py)
- `GET /apai/deploy` — requires auth + APAi subscription
- `POST /api/apai/deploy` — request deployment (auth required)
- `GET /api/apai/deploy/status` — deployment status (auth required)
- Updated APAi subscribe success/cancel URLs: `/business/deployment` → `/apai/deploy`

### Phase 4: Pricing Page Fixed (server.py)
- Removed $600 APAi card from "For Businesses" grid
- Added separate "Launch Your Own OTA" section with APAi Pro ($299) + Enterprise ($599)
- B2B section shows ONLY: Starter ($49), Growth ($99), Volume ($199)

### Phase 5: Nav + Dashboard Wiring
- Added "APAi" link to nav More dropdown (base_template.py) with purple accent
- B2B dashboard "Deploy Your OTA" → "Upgrade to APAi" link

### Phase 6: Docstring Fixes
- models.py: TemplateDeployment docstring → "APAi subscribers" (was "B2B customers")
- routes_business.py: Module docstring clarified B2B = inside MYSTES only

### Phase 7: Tests (18 new)
- `test_build193_apai.py`: 5 classes, 18 tests (15 pass, 3 skip due to feature-flag gating)
- Fixed cascading test in `test_build189_apai.py`: `'starter'` → `'pro'` in tiers_available
- Fixed cascading test in `test_build191_smoke.py`: `'$600'` → `'$299'`/`'$599'`

### APAI_TIER_PRICES Updated
- Removed non-existent "starter" tier ($99)
- Set: Pro=$299, Enterprise=$599
- NOTE: Third APAi tier under discussion — future build

## Files Modified
| File | Action |
|------|--------|
| `models.py` | Docstring fix (TemplateDeployment) |
| `routes_business.py` | Removed deployment routes (~260 LOC), fixed tiers, fixed links |
| `server.py` | APAi pitch page, deploy routes, pricing page fix |
| `templates/base_template.py` | APAi nav link |
| `tests/test_build193_apai.py` | NEW (18 tests) |
| `tests/test_build189_apai.py` | Cascading fix (starter → pro) |
| `tests/test_build191_smoke.py` | Cascading fix ($600 → $299/$599) |

## Architectural Boundary Enforced
- **B2B** = power users INSIDE MYSTES. Starter($49)/Growth($99)/Volume($199). Reduced fees. NO turnkey.
- **APAi** = SEPARATE product. Deploy own branded OTA. Pro($299)/Enterprise($599). Third tier TBD.
- Deployment routes gated behind APAi subscription, NOT B2B account

## Open Items
- Third APAi tier — pricing discussion pending
- Install Wizard Knowledge Card — future build (ANASTASiA knowledge card architecture)
- All APAi pricing is PROVISIONAL / test models
