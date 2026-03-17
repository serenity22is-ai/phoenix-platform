# Build #164 (2026-03-12) — Activities Vertical + Viator Merchant Path

## What Was Built
- `routes_activities.py` NEW (~280 LOC) — Full activities vertical for MYSTES consumer OTA
  - GET /activities — Search page with form (destination, dates, travelers, filters, sort)
  - POST /api/activities/search — Search via Viator API (destination resolve → product search)
  - POST /api/activities/select — Availability check → Deal creation → checkout redirect
  - CSS: activity cards with thumbnails, badges (free cancel, skip line, private, sell out), star ratings
  - JS: async search, result rendering, activity selection flow
- `models.py` — Added `vertical_activities` feature flag (Layer 2, default false)
- `server.py` — Feature flag context processor, homepage chips + vertical icon, route registration
- Pattern follows exact hotel module structure (routes_hotels.py)

## Viator API Key Status
- Key: `ba96eb39-f669-40fc-9b8b-64f82146e15f` saved in `.env`
- Env: `VIATOR_ENV=sandbox`
- Status: **UNAUTHORIZED** — key still not propagated (or Basic Access doesn't include API)
- Auth header confirmed: `exp-api-key` is correct (other patterns return "Missing required header")

## Merchant vs Affiliate
- User wants MERCHANT access (sell directly on MYSTES, full booking flow)
- Basic Access affiliate = redirect links only (user leaves MYSTES → books on Viator)
- Merchant API needed for: hold, book, cancel, voucher generation
- **Action needed**: Email `affiliateapi@tripadvisor.com` for merchant API upgrade
- Also try: `apitechsupport@viator.com`

## Test Results
- 429 SDK tests PASSING (1.05s)
- Consumer tests: 89 passed, 78 skipped (12 pre-existing Picasso failures, unrelated)
- `routes_activities.py` imports clean, template renders

## Files Modified
- `routes_activities.py` NEW
- `models.py` — feature flag
- `server.py` — context processor, homepage, route registration

## Pending
- Viator merchant API key activation
- Enable `vertical_activities` feature flag in admin panel once key works
- Wire car rentals (Discover Cars) and insurance (SafetyWing) verticals next
- Email affiliateapi@tripadvisor.com if key doesn't work after 48 hours
