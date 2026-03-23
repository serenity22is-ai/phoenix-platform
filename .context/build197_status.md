# Build #197 — Deep Hardening + Vertical Route Coverage
**Date**: 2026-03-17
**Status**: COMPLETE
**Tests**: 1,169 total (671 consumer + 498 SDK), 0 failed, 5 skipped

---

## What Was Done

### 1. raw_offer Passthrough Fix (CRITICAL BUG)
**Files**: `models.py`, `server.py`
- Added `offer_id` column to Deal model — NDC/aggregator offer IDs now stored explicitly
- Multi-leg deal creation extracts `offer_id` from raw_offer
- Single-leg deal creation extracts `offer_id` from raw_offer
- Picasso/GDS deals (no offer_id) store NULL — correct behavior
- **This was flagged as critical since Build #179**

### 2. Stripe Saved-Card Charge Atomicity (FINANCIAL SAFETY)
**File**: `server.py` (~line 9438)
- Wrapped Payment record creation + Deal status update in try/except
- If DB commit fails after PaymentIntent succeeds → `logger.critical()` with PaymentIntent ID for manual reconciliation
- Returns `payment_intent_id` to client so customer can contact support
- Outer exception handler sanitized: returns generic message instead of `str(e)`

### 3. Exception Handling — No str(e) Exposure (SECURITY)
**Files**: `routes_hotels.py`, `routes_cars.py`, `routes_activities.py`
- Hotel search: `str(e)` → `"Hotel search failed. Please try again."`
- Hotel select: `str(e)` → `"Hotel selection failed. Please try again."`
- Car location search: `str(e)` → `"Location search failed. Please try again."`
- Car search: `str(e)` → `"Car search failed. Please try again."`
- Car select: `str(e)` → `"Car selection failed. Please try again."`
- Activity search: `str(e)` → `"Activity search failed. Please try again."`
- Activity select: `str(e)` → `"Activity selection failed. Please try again."`
- All handlers now use `exc_info=True` for full stack traces in server logs

### 4. Silent Exception Swallow Fixes
**Files**: `payments.py`, `routes_friends.py`, `server.py`
- payments.py: Added module-level logger, B2B fee lookup failures now logged
- payments.py: Subscription tier lookup failures now logged
- payments.py: XRP price fetch failures now logged
- routes_friends.py: Activity feed (bookings) exception → `logger.debug()`
- routes_friends.py: Activity feed (collections) exception → `logger.debug()`
- server.py: Referral notification email failure → `logger.debug()`
- server.py: Referral setup failure → `logger.warning()` (was f-string, now %-format)

### 5. Google OAuth Cleanup
**File**: `server.py`
- `/auth/google/token`: Removed redundant `import traceback` + `traceback.print_exc()` — `logger.exception()` already includes traceback
- `/auth/google/callback`: Removed redundant `traceback.print_exc()` + `print()` — `logger.exception()` handles it

### 6. search.py Logger Conversion
**File**: `search.py`
- Added `import logging` + `logger = logging.getLogger(__name__)` at module level
- Converted all error-level `print()` to `logger.error()`/`logger.warning()`:
  - SERPAPI failures → `logger.warning()`
  - ANASTASiA orchestrator fallback → `logger.warning()`
  - Picasso errors → `logger.error()`
  - Duffel NDC search errors → `logger.error()`
  - Kiwi aggregator search errors → `logger.error()`
  - Search mode errors → `logger.error()`
  - Google Flights scraper failures → `logger.warning()`
- Key info-level progress messages also converted to `logger.info()`

### 7. Vertical Route Module Tests (58 NEW tests)
**File**: `tests/test_build197_hardening.py`

| Test Class | Tests | Coverage |
|------------|-------|----------|
| TestDealOfferIdColumn | 6 | offer_id column, storage, extraction from raw_offer |
| TestStripeSavedCardAtomicity | 3 | Endpoint exists, auth required, no str(e) in source |
| TestNoStrEExposure | 3 | Hotels, cars, activities generic error messages |
| TestPaymentsLogger | 3 | Module logger, fee_percent, tier_name |
| TestSearchLogger | 2 | Module logger, error paths use logger |
| TestFlightsRoutes | 2 | Page loads, contains MYSTES |
| TestHotelsRoutes | 3 | Page loads, search validates, select validates |
| TestCarsRoutes | 3 | Page loads, locations validates, search validates |
| TestTripsRoutes | 5 | Auth required, page loads, create trip, detail auth, delete auth |
| TestFriendsRoutes | 6 | Auth, page loads, search, request validates, activity feed, logger check |
| TestCollectionsRoutes | 4 | Auth, page loads, create collection, detail owner |
| TestActivitiesRoutes | 2 | Page loads, search validates |
| TestBusinessRoutes | 6 | Landing, signup, dashboard auth, subscription, B2B, tiers |
| TestGoogleOAuthCleanup | 2 | No traceback.print_exc, no print() |
| TestReferralNotificationLogging | 1 | Logs notification errors |
| TestDealCreationEndpoint | 3 | Single deal, multi-leg, no data |
| TestCoreRoutes | 5 | Home, login, register, pricing, health, APAi |

---

## Files Modified

| File | Changes |
|------|---------|
| `models.py` | Added `offer_id` column to Deal model |
| `server.py` | offer_id extraction in deal creation, Stripe atomicity, OAuth cleanup, referral logging |
| `payments.py` | Module-level logger, debug logging on fee/tier lookups, XRP price fetch |
| `search.py` | Module-level logger, error/warning/info print→logger conversion |
| `routes_hotels.py` | Sanitized str(e) exposure (search + select) |
| `routes_cars.py` | Sanitized str(e) exposure (location, search, select) |
| `routes_activities.py` | Sanitized str(e) exposure (search + select) |
| `routes_friends.py` | Activity feed exception logging |
| `tests/test_build197_hardening.py` | NEW — 58 tests |

## Test Results
```
Consumer: 671 passed, 5 skipped, 0 failed (168s)
SDK:      498 passed, 0 failed (1.06s)
Total:    1,169 passed, 5 skipped, 0 failed
```
