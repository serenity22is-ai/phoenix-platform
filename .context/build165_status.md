# Build #165 — Hotel Booking Pipeline + Production liteAPI

## Date: 2026-03-12

## Summary
Wired complete hotel booking pipeline with liteAPI, moved from sandbox to production, analyzed production margins.

## Changes Made

### models.py
- Added `hotel_prebook_id = db.Column(db.String(200), nullable=True)` to Deal model

### routes_hotels.py
- Fixed `/api/hotels/select` — real pricing from search cache instead of hardcoded $15
- Fixed "Searching hotels via Amadeus..." → "Searching hotels..."
- Fixed "Amadeus" badge → "liteAPI"

### liteapi_client.py
- Rewrote `create_booking()` with correct API format:
  - Old: `guestInfo` + raw card details (card_number, expiry_date, cvc)
  - New: `holder`/`guests`/`payment.method: ACC_CREDIT_CARD`
- ACC_CREDIT_CARD = charges card registered on liteAPI dashboard (no per-request card details)

### server.py
- Updated `execute_automated_hotel_booking`:
  - Stores prebook_id on deal for audit trail
  - Removed entire platform card env var section (PLATFORM_CARD_VENDOR/NUMBER/EXPIRY/CVC)
  - Now just calls create_booking() with guest info + client_reference

### tests/test_api_clients.py
- Updated `test_create_booking_success` to assert new payload format

### .env
- `LITEAPI_KEY` changed from sandbox to production: `prod_f1d18095-536d-4102-9e85-12ae48c3be03`

## Render Deployment
- Set LITEAPI_KEY on Render via API (service srv-d61a6f24d50c739nvb40)
- Production key confirmed active

## Key Discovery: ACC_CREDIT_CARD
liteAPI charges the card registered on the dashboard account. No per-request card details needed.
This eliminated the need for PLATFORM_CARD_* env vars entirely.

## Pipeline Test Results (Sandbox)
- Search: Paris hotels — real wholesale rates with suggestedSellingPrice benchmark
- Prebook: Got prebookId successfully
- Book: Got booking ID `EHIwietaA`

## Production Margin Analysis (6 cities, 4,104 offers)
| City | Avg Margin | Range |
|------|-----------|-------|
| Bangkok | 11.3% | 0.1-33.9% |
| Tokyo | 9.7% | 7.8-16.5% |
| Paris | 8.3% | 5.4-12.5% |
| Dubai | 7.7% | 5.4-7.8% |
| London | 7.5% | 4.8-7.8% |
| Barcelona | 6.0% | 0.2-7.8% |
| **Overall** | **8.7%** | **0.1-33.9%** |

- All rates: priceType=commission, supplier=nuitee
- rateTypes: standard + package (package often better margins)
- paymentTypes: NUITEE_PAY
- suggestedSellingPrice source: providerDirect

## Tests
- 99 passed, 0 failures

## Status: COMPLETE
