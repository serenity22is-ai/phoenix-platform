# Build #171 — Google One Tap + Cross-Sell + Booking Polish
**Date**: 2026-03-12
**Status**: COMPLETE
**Tests**: 73 passed, 0 failed, 0 errors, 0 skipped

---

## What Was Built

### P1-#3: Google One Tap + Post-Booking Account Creation
- **templates/base_template.py**: Loads Google Identity Services library (`accounts.google.com/gsi/client`) conditionally when `google_client_id` is set
- **templates/base_template.py**: Auto-initializes One Tap prompt for logged-out users on every page (`google.accounts.id.prompt()`)
- **server.py LOGIN_CONTENT**: Google Sign-In button with "Sign in with Google" text + "or sign in with email" divider
- **server.py REGISTER_CONTENT**: Google Sign-In button with "Sign up with Google" text + "or sign up with email" divider
- **server.py BOOKING_CONFIRMATION_CONTENT**: Guest signup card with:
  - "You Earned MYSTES Points!" banner showing escrowed points count
  - Google One Tap `renderButton()` in confirmation context
  - "or" divider + "Create Account & Claim Points" CTA
  - "Points expire in 90 days if unclaimed" warning
- **server.py booking_confirmation()**: Passes `is_authenticated`, `escrow_points`, `google_client_id` to template
- Removed XRP wallet field from registration (unnecessary for consumer signup)
- Backend `/auth/google/callback` already handles GSI JWT credentials — zero backend changes needed

### P2-#14: Cross-Sell Cards on Booking Confirmation
- **Flight confirmations**: "Complete Your Trip" section with:
  - "Find Hotels" card → links to `/hotels?destination={dest}&check_in={date}`
  - "Return Flight" card → links to `/flights?origin={dest}&destination={origin}`
- **Hotel confirmations**: "Need a Flight?" section with:
  - "Search Flights" card → links to `/flights?destination={city_code}`
- Cards use MYSTES glass morphism design with hover effects
- Footer adapts: authenticated users see "View My Bookings", guests see "Create Account to Track Bookings"

### Polish: Multi-Passenger Support
- **server.py BOOK_CONTENT**: "Add Another Passenger" button (max 9 passengers)
- Dynamic JS form generation with required fields (name, DOB, gender, passport)
- "Remove" button per additional passenger
- `serializeAdditionalPassengers()` → JSON array in hidden form field
- **server.py /complete-booking**: Parses `additional_passengers_json` and stores in `passenger_data`
- Primary passenger (Passenger 1) still uses named form fields for backwards compatibility

### Polish: Review & Pay Modal
- **server.py BOOK_CONTENT**: Modal overlay appears when user clicks "Pay with Card"
- Shows order summary: airline/flight, route, dates, base fare, MYSTES fee, savings, total
- "Confirm & Pay $X.XX" button → then redirects to Stripe Checkout
- Close button (X) returns to payment selection
- Prevents accidental Stripe redirects — user sees exact charges first

---

## Files Modified

| File | Changes |
|------|---------|
| `templates/base_template.py` | +GSI library loading, +One Tap auto-prompt JS |
| `server.py` | +Google Sign-In on login/register, +guest signup card on confirmation, +cross-sell cards, +multi-pax form, +review modal, +escrow points lookup in confirmation route |
| `tests/test_integration.py` | +8 Build #171 tests |

## Test Results: 73 passed (65 prior + 8 new)
