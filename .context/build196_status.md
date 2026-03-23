# Build #196 — Production Hardening
**Date**: 2026-03-17
**Status**: COMPLETE
**Tests**: 1,111 total (613 consumer + 498 SDK), 0 failed, 3 skipped

---

## What Was Done

### 1. Fixed `current_user.first_name` Crash (CRITICAL)
**File**: `server.py` (line ~4156)
- User model has `name`, NOT `first_name`/`last_name`
- Would crash with `AttributeError` during insurance purchase flow
- Fixed: split `current_user.name` into first/last safely

### 2. Config Cleanup
**File**: `config.py`
- Removed `COINBASE_ONRAMP_APP_ID` (Coinbase permanently retired)
- Removed `TRANSAK_API_KEY` (Transak retired)
- Replaced 11-line old Dev Portal pricing block with 3-line APAi Stripe price IDs
- Kept XRPL config (still referenced by payments.py)

### 3. Composite DB Indexes
**File**: `models.py`
- Added `ix_deals_route_date` — composite on `(origin, destination, departure_date)` for flight search
- Added `ix_deals_type_status` — composite on `(deal_type, deal_status)` for filtered queries
- Added `ix_bookings_user_status` — composite on `(user_id, status, created_at)` for "my bookings"

### 4. Cascade & Relationship Hardening
**File**: `models.py`
- Added `passive_deletes=True` to User → Payment and User → Booking relationships (prevents ORM cascade, DB FK RESTRICT is correct for financial records)
- Added `cascade='all, delete-orphan'` to PriceAlert relationship (ephemeral data, safe to cascade)

### 5. Exception Handling (6 Critical Fixes)
**Files**: `server.py`, `payments.py`

| Location | Before | After |
|----------|--------|-------|
| Webhook signature (server.py ~9695) | Silent `except Exception` → `raw_event = None` | `SignatureVerificationError` → return 400 |
| Webhook dedup (server.py ~9706) | `except Exception: pass` | Logged + rollback |
| Webhook event save (server.py ~10059) | `except Exception` (silent) | Logged with event ID |
| Escrow points (server.py ~7875) | Fallback to hardcoded 3500 | Fallback to 0 + logged |
| DNS registration (server.py ~3135) | `except Exception` blocks ALL signups | `ValueError` → block, other exceptions → allow + log |
| XRP/RLUSD verification (payments.py ~669, 728) | `return {"error": str(e)}` | Logged with stack trace + `type(e).__name__` |

### 6. Audit Results (False Alarms Cleared)
- `.first()` null guards: **ALL 143 calls properly guarded** — no fixes needed
- CSRF coverage: Properly managed by Flask-WTF global + selective `@csrf.exempt` on API routes
- `| safe` filter: Intentional — all content is server-generated HTML, not user input

---

## Files Modified

| File | Changes |
|------|---------|
| `server.py` | Fixed `current_user.first_name` crash, webhook signature validation, DNS graceful degradation, escrow fallback |
| `config.py` | Removed Coinbase/Transak, replaced old Dev Portal pricing with APAi Stripe IDs |
| `models.py` | 3 composite indexes, passive_deletes on financial relationships, cascade on PriceAlert |
| `payments.py` | XRP + RLUSD verification logging with stack traces |
| `tests/test_build196_hardening.py` | NEW — 22 tests |
| `CLAUDE_CONTEXT.md` | Updated to Build #196 |

## Test Results
```
Consumer: 613 passed, 3 skipped, 0 failed (207s)
SDK:      498 passed, 0 failed (1.07s)
Total:    1,111 passed, 3 skipped, 0 failed
```
