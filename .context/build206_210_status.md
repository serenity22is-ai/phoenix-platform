# Builds #206-210 Status — 2026-04-15

## Status: COMPLETE
**Tests**: 1,663 (842 SDK + 821 consumer), 0 failed, 11 skipped

---

## Build #206: QR Code Generator
**Files**: `server.py`, `routes_business.py`
**Package**: `qrcode[pil]`

Consumer endpoints (server.py):
- `GET /api/referral-card/qr/<token>.png` — PNG download
- `POST /api/referral-card/qr-data` — base64 data URI for inline display
- `GET /api/business/referral-qr.png` — B2B referral QR
- `GET /ref-card/<token>/print` — print-ready page with REFERRAL_CARD_PRINT_TEMPLATE

B2B endpoints (routes_business.py):
- `GET /business/qr/<fmt>` — PNG or SVG download
- `GET /api/business/qr-data` — JSON metadata with referral_code, urls

UI updates:
- B2B dashboard: QR preview + PNG/SVG download buttons
- Consumer referral card: QR display + print/download buttons
- Public referral card: QR code image

---

## Build #207: Proxy Booking Session Flow
**Files**: `server.py`, `models.py`

New Booking model columns:
- `booking_channel` (default='api')
- `proxy_market` (nullable)
- `service_fee_stripe_pi` (nullable)

Endpoints:
- `POST /api/booking/proxy-session` — initiate proxy booking (validate spread, calc fee, Stripe authorize, enqueue)
- `POST /api/booking/proxy-complete` — capture Stripe, create Booking record
- `POST /api/booking/proxy-cancel` — release Stripe hold

Internal functions:
- `_get_proxy_module()` — lazy init proxy neuron
- `_execute_proxy_booking()` — Playwright through Bright Data CDP
- `_resolve_airline_booking_url()`, `_fill_passenger_form()`, `_fill_payment_form()`, `_submit_booking()`, `_extract_confirmation()`

Worker routing: `_worker_loop()` routes proxy vs API jobs based on `job.payment_info.get("booking_channel")`

---

## Build #208: Bundling (Proxy Flight + Duffel Hotel)
**Files**: `server.py`, `models.py`

New BundleItem column: `booking_channel` (default='api')

Endpoints:
- `POST /api/proxy-bundle/create` — create proxy flight + Duffel hotel bundle
- `POST /api/proxy-bundle/<id>/book` — execute both bookings
- `GET /api/proxy-bundle/<id>/status` — poll combined status

Note: Routes use `/api/proxy-bundle/*` prefix to avoid collision with existing `/api/bundle/*` routes.

---

## Build #209: Trip Splitting Mode 1
**Files**: `routes_trips.py`

Endpoints:
- `POST /api/trips/<id>/checkout` — one person pays full service fee via Stripe
- `POST /api/trips/<id>/settle-up/request` — mark assignments as 'requested'
- `POST /api/trips/<id>/settle-up/pay` — member pays their share via Stripe
- `GET /api/trips/<id>/balances` — who owes what

Creates TripCart + TripCartAssignment records. Payer auto-marked 'paid'. $3 minimum fee enforced.

UI: Enabled "Checkout All" button, added balances section with settle-up JS functions.

---

## Build #210: B2B Referral Landing Page
**Files**: `server.py`, `routes_business.py`

- Added `B2B_REFERRAL_LANDING_CONTENT` template
- Modified `referral_landing()` at `/ref/<code>` — B2B codes now show branded landing page (200) instead of blind redirect (302)
- Landing page shows: account name, savings example ($1,400 → $1,050), referral code, "Search Flights" CTA
- Sets session vars: `referral_source`, `referral_markup_pct`, `referral_markup_flat`
- Removed duplicate `/ref/<referral_code>` route from routes_business.py

---

## Test File
`tests/test_build206_210.py` — 52 tests (46 passed, 6 skipped)
- B2B QR tests skip when `b2b_accounts` feature flag not enabled at import time (expected)
- Updated `tests/test_build185.py::test_referral_redirect` for Build #210 behavior change (200 landing page instead of 302 redirect)
