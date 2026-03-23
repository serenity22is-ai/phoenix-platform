# Build #185 Status — Priority Features Sprint
**Date**: 2026-03-17
**Tests**: 813 total (321 consumer + 492 SDK), 0 failures
**Previous**: Build #184 (795 tests, 0 failures)

---

## Summary

Build #185 addressed the top 5 gaps identified during a comprehensive codebase audit. All five priorities were built and tested in a single autonomous session.

---

## Priority 1: Production Hardening

### Debug Flag Fix
- **File**: `server.py` line 18039
- **Before**: `debug=True` (hardcoded — DANGEROUS in production)
- **After**: `debug=os.environ.get("FLASK_ENV") != "production"`

### CORS Whitelist
- **File**: `server.py` line 137
- Added `CORS_ALLOWED_ORIGINS` env var support (comma-separated)
- Falls back to permissive CORS in dev when unset
- Production should set: `CORS_ALLOWED_ORIGINS=https://mystes.app,https://www.mystes.app`

---

## Priority 2: Cars + Activities Through ANASTASiA Neurons

### CarsNeuron Dispatch
- **File**: `routes_cars.py` ~line 1078
- Search now tries `CarsNeuron` from SDK first
- Graceful fallback to direct `DiscoverCarsClient` if neuron unavailable
- Pattern: try neuron → check `result["success"]` → fallback to direct

### ActivitiesNeuron Dispatch
- **File**: `routes_activities.py` ~line 525
- Same pattern: try `ActivitiesNeuron` first, fallback to `ViatorClient`
- Neuron attaches `raw_offer` to results for BookingDispatcher passthrough

---

## Priority 3: APAi Subscriber Recognition

### Detection Helper
- **File**: `routes_devportal.py` line 50
- `_detect_apai_subscriber(email)` checks MYSTES User + CommercialAccount
- Returns `{is_subscriber, mystes_user_id, template_config}` with agency details
- Template config includes: agency_name, account_id, tier, fee_percent, referral_code

### Auto-Detection Wiring
- **Signup**: Auto-detects APAi status when dev portal account created
- **Login**: Refreshes APAi status on every login (catches newly created B2B accounts)
- **Manual**: `POST /api/dev/link-apai` endpoint for explicit refresh
- **Info**: `GET /api/dev/account` returns full account + APAi status

### Bug Fixed
- `json` module was not imported at module level in `routes_devportal.py`
- Caused silent `NameError` in `_detect_apai_subscriber()` → always returned False
- Fixed by adding `import json` to imports

---

## Priority 4: Trip Planner + Friends UI Polish

### Trip Planner (4 new endpoints in `routes_trips.py`)
- `POST /api/trips/<id>/duplicate` — Deep-copies trip + items, sets new owner
- `GET /api/trips/<id>/budget` — Per-member budget breakdown with cap enforcement
- `GET /api/trips/<id>/activity` — Activity feed (recent items + member joins)
- `PUT /api/trips/<id>/items/<item_id>/status` — Item status workflow (proposed → approved → booked → cancelled)

### Friends (3 new endpoints in `routes_friends.py`)
- `POST /api/friends/<id>/block` — Block a friend
- `POST /api/friends/<id>/unblock` — Unblock (deletes friendship)
- `GET /api/friends/activity` — Activity feed (friend bookings + shared collections)

---

## Priority 5: B2B Admin Dashboard + Markup Tools

### New Model Fields (`models.py`)
- `CommercialAccount.consumer_markup_percent` (0-50%)
- `CommercialAccount.consumer_markup_flat_usd` (flat per-ticket)
- `CommercialAccount.referral_link_enabled` (bool)

### New Routes (`routes_business.py`)
- `GET /api/business/analytics` — Full analytics JSON (monthly aggregation, route breakdown, tier progress)
- `GET/POST /business/markup` — Markup settings page with inline form
- `GET /ref/<code>` — Referral redirect (stores markup in session)

### Referral Route Fix
- **Problem**: Existing `/ref/<code>` in `server.py` (consumer referrals, Build #172) caught all requests, blocking B2B referrals in `routes_business.py`
- **Fix**: Added B2B referral fallback to existing `server.py` route (line 3073)
- Consumer codes checked first → B2B codes as fallback → `/register` if neither found

---

## Test Suite

### Build #185 Tests (`tests/test_build185.py`) — 18 tests
| Class | Tests | Status |
|-------|-------|--------|
| TestProductionFixes | 2 | PASS |
| TestNeuronDispatch | 4 | PASS |
| TestAPAiRecognition | 4 | PASS |
| TestTripPlannerEnhancements | 4 | PASS |
| TestFriendsEnhancements | 2 | PASS |
| TestB2BEnhancements | 2 | PASS |

### Full Suite
- Consumer: **321 passed**, 0 failed
- SDK: **492 passed**, 0 failed
- **Total: 813 tests, 0 failures** (+18 from Build #184)

---

## Files Modified

| File | Action | LOC Changed |
|------|--------|-------------|
| `server.py` | Debug fix, CORS whitelist, B2B referral fallback | ~25 |
| `routes_cars.py` | CarsNeuron dispatch wrapper | ~20 |
| `routes_activities.py` | ActivitiesNeuron dispatch wrapper | ~25 |
| `routes_devportal.py` | APAi subscriber detection + endpoints + json import | ~100 |
| `routes_trips.py` | 4 new trip planner endpoints | ~120 |
| `routes_friends.py` | 3 new friends endpoints | ~80 |
| `models.py` | 3 new CommercialAccount fields | ~5 |
| `routes_business.py` | Analytics API + markup page + referral redirect | ~250 |
| `tests/test_build185.py` | NEW — 18 tests across 6 classes | ~430 |

**Total: ~1,055 LOC across 9 files (1 new, 8 modified)**

---

## Bugs Found & Fixed

1. **`debug=True` in production** — Changed to env-var-based
2. **CORS wide open** — Added origin whitelist support
3. **`json` not imported in routes_devportal.py** — Silent APAi detection failure
4. **Route conflict `/ref/<code>`** — Consumer referral route shadowed B2B referral route
5. **SQLAlchemy DetachedInstanceError in tests** — Fixed test helpers to return scalar IDs
