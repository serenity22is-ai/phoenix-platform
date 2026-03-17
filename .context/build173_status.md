# Build #173 — Production Polish: Pricing, XRP Removal, Fulfillment Wiring
**Date**: 2026-03-12
**Status**: COMPLETE
**Tests**: 132 passed, 0 failed, 0 errors, 0 skipped

---

## What Was Built

Critical production polish: pricing display corrected (NEVER show wholesale/fee), XRP/XRPL removed entirely, Picasso API wired into automated fulfillment, and booking UX hardened.

### 1. Pricing Display Fix (CRITICAL — User Directive)
**Rule**: Customer sees ONE price (MYSTES Price = wholesale + fee). Never show wholesale, fee %, fee $, or tier name.

- **Flight search cards** (`routes_flights.py`): Inject `fee_pct` from backend, pre-calculate `_mystesPrice` per flight, show savings as "Save $X (X%) vs Google Flights"
- **Flight booking page** (`server.py` BOOK_CONTENT): Show "MYSTES Price" total, "You save vs Google Flights" badge
- **Hotel booking page** (`routes_hotels.py`): Replaced "Hotel (X nights)" + "Service Fee" + "Total Due" with single "MYSTES Price" + optional savings
- **Review modal** (`server.py`): "MYSTES Price" + savings vs Google only

### 2. XRP/XRPL Removal (Stripe + MoonPay Only)
Removed all user-facing XRP/XRPL code:
- **Nav**: Removed `<span class="xrpl-badge">XRPL Secured</span>` from navbar
- **Footer**: Removed "Powered by XRP Ledger"
- **Meta**: Updated description (removed "Pay with crypto. Powered by XRPL.")
- **CSS**: Removed `.xrpl-badge`, `@keyframes pulse`, mobile override (~35 lines)
- **Dashboard**: Removed XRP Wallet display
- **Settings**: Removed XRP wallet input + update handler
- **Registration**: Removed `xrp_wallet` field extraction + model assignment
- **Booking page**: Removed `get_xrp_price()`, `refresh_xrp_price()`, XRP/RLUSD payment blocks, destination tag logic
- **Hotel booking**: Removed XRP Direct + RLUSD Stablecoin payment options
- **Data export**: Removed `xrp_wallet_address` field
- **Account deletion**: Removed XRP wallet clearing
- Note: Backend `payments.py` XRP/RLUSD verification functions retained as dead code (no UI calls them)

### 3. Placeholder Deal Removal
- Removed auto-creation of JAL demo flight deal when deal_id not found
- Now returns proper 404: `flash("Deal not found or expired. Please search again.")` → redirect to /flights

### 4. Deal Expiration Countdown Warning
- Live countdown timer on booking page: "This deal expires in Xh Xm Xs"
- Turns red when < 10 minutes remaining
- Shows "This deal has expired" with search-again link when expired
- Conditional: only renders when `deal.expires_at` is set
- Added `expires_at`, `origin`, `destination`, `arrival_time` to `Deal.to_dict()` (were missing — latent bug fix)

### 5. Guest Email Validation
- Enhanced `validateGuestEmail()` with regex: `/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/`
- Validates format before allowing Stripe checkout to proceed
- Clear error message: "Please enter a valid email address (e.g. name@example.com)"

### 6. Picasso API Wired into Automated Fulfillment
`execute_automated_booking()` now has 3-path fallback chain:
1. **Picasso/Redbox API** (preferred) — when deal has `fare_id` + `fare_search_id` from GDS search
   - Maps passenger data to Picasso format (firstName/lastName, Male/Female, paxType ADT)
   - Handles additional passengers
   - Passes `markup_amount` = platform fee (so issued ticket matches MYSTES price)
   - Maps PNR result to `confirmation_code`
2. **airline_booker** (Playwright) — fallback for non-GDS deals
3. **Manual agent** — final fallback with logging

### 7. XRPL Config Cleanup
- Removed `platform_wallet` and `network` XRPL template variables from book route

---

## Files Modified

| File | Changes |
|------|---------|
| `models.py` | Add `origin`, `destination`, `arrival_time`, `expires_at` to Deal.to_dict() |
| `server.py` | +expiration countdown, +email validation regex, +Picasso booking path, -XRP wallet fields, -XRP payment verification, -placeholder deal, -XRPL config refs |
| `routes_flights.py` | +fee_pct injection, +MYSTES price calculation, +updated renderFlightCards(), +sort by MYSTES price |
| `routes_hotels.py` | +MYSTES Price display, -XRP/RLUSD payment blocks |
| `templates/base_template.py` | -XRPL badge, -XRP footer, -XRPL CSS, -meta description XRP refs |

## Test Results: 132 passed (same count as Build #172 — no regressions)

## Architecture Notes
- **Picasso booking flow**: `picasso_client.book_flight()` → `addToCart` → `checkout` → `createBooking` (superPNR). Returns PNR as confirmation_code.
- **Passenger mapping**: Form fields (`first_name`, `gender: M/F`) → Picasso format (`firstName`, `gender: Male/Female`)
- **Markup**: Platform fee baked into ticket via `BOOKING_FEE_OVERRIDE` so issued ticket price = MYSTES Price

## NOT in this build (deferred):
- Remove XRP columns from models.py (DB migration needed)
- Remove dead XRP functions from payments.py
- Remove XRPL_CONFIG from config.py
- Trip Planner (full build)
- Background price alert checker
- SerpAPI lazy-load refactor
