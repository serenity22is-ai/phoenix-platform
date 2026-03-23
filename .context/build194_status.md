# Build #194 — APAi Admin Portal (Dev Portal Repurposed)
**Date**: 2026-03-17
**Tests**: 1,065 (567 consumer + 498 SDK), 0 failed, 3 skipped
**Status**: COMPLETE

## What This Build Does
Repurposes the standalone ANASTASiA Dev Portal (Build #184) into the APAi Admin Portal — a multi-seat team management interface for APAi subscribers. Standalone ANASTASiA AI product SCRAPPED. ANASTASiA is now APAi-exclusive.

## Key Decisions (from strategy session)
1. **Standalone ANASTASiA AI = SCRAPPED** — Without the turnkey OTA, ANASTASiA is just a branded Claude wrapper = commodity = no moat
2. **ANASTASiA is APAi-exclusive** — Want ANASTASiA? Subscribe to APAi ($299/$599/$999)
3. **Unlimited dev team seats** — More devs = more queries = more revenue
4. **All queries count against subscriber's pool** — One subscription, one bill
5. **Opus 4.6 on everything** — No model downgrading. Branded as ANASTASiA, never expose Claude/Anthropic

## Changes

### Phase 1: dev_portal_ai.py — ANASTASiA Branding
- Removed "Claude Opus 4.6" from system prompt → branded as ANASTASiA
- Added IDENTITY section: "NEVER mention Claude, Opus, Sonnet, Haiku, Anthropic"
- Added underlying model to opsec deny list
- Updated class docstring

### Phase 2: dev_portal_billing.py — APAi Tier Config (Full Rewrite)
- Replaced standalone tiers (PAYG $0.15, Builder $49, Scale $99) with APAi tiers:
  - Pro: $299/mo, 500 queries, $0.12 overage, 5% routing
  - Enterprise: $599/mo, 2,000 queries, $0.08 overage, 3% routing
  - Scale: $999/mo, 5,000 queries, $0.05 overage, 2% routing
- `record_query_usage()` now supports multi-seat (increments both member + admin counters)
- `check_quota()` checks against subscriber's aggregate, supports per-member limits
- `get_usage_stats()` returns both aggregate and per-member stats
- Removed standalone checkout function

### Phase 3: models.py — Multi-Seat Fields
- Added `commercial_account_id` FK to CommercialAccount
- Added `role` field (admin/member)
- Added `added_by_id` FK to track who provisioned the member
- Added `query_limit` field (optional per-member cap, NULL = unlimited)
- Updated `to_dict()` to include role and query_limit
- Updated docstring and comments

### Phase 4: routes_devportal.py — Full Rewrite (~700 LOC)
URL prefix changed from `/dev/*` to `/apai/admin/*`:

**Removed (standalone scrapped):**
- Landing page (`/dev`)
- Pricing page (`/dev/pricing`)
- Standalone signup (`/dev/signup`)
- Standalone subscribe (`/dev/subscribe`)
- Billing success page (`/dev/billing/success`)
- APAi link endpoint (`/api/dev/link-apai`)

**Preserved (repurposed):**
- Login → `/apai/admin/login`
- Logout → `/apai/admin/logout`
- Terminal → `/apai/admin/terminal`
- Chat API → `/api/apai/admin/chat`
- Conversations API → `/api/apai/admin/conversations`
- Usage API → `/api/apai/admin/usage`
- Account info → `/api/apai/admin/account`
- API keys → `/apai/admin/api-keys`

**Added (new multi-seat features):**
- Dashboard → `/apai/admin` (team list, usage overview, stat cards)
- Add team member → `POST /api/apai/admin/team`
- Remove team member → `DELETE /api/apai/admin/team/<id>`
- Update team member → `PUT /api/apai/admin/team/<id>` (query limit, name)

**Legacy redirects:**
- `/dev`, `/dev/login`, `/dev/signup`, `/dev/pricing` → 301 → `/apai/admin/login`
- `/dev/terminal` → 301 → `/apai/admin/terminal`
- `/dev/logout` → 301 → `/apai/admin/logout`

### Phase 5: server.py — Integration Updates
- Route registration comment updated
- Webhook handler comment updated

### Phase 6: Tests
- **DELETED**: `tests/test_devportal.py` (17 tests — tested scrapped standalone)
- **DELETED**: `tests/test_build188_devportal.py` (20 tests — tested scrapped standalone)
- **CREATED**: `tests/test_build194_apai_admin.py` (48 tests across 12 classes)
- **FIXED**: `tests/test_build185.py` — Updated `test_signup_detects_apai` (standalone signup → 405/301), `test_account_info_endpoint` (URL + tier updates)

### Test Classes (48 tests)
| Class | Tests | Coverage |
|-------|-------|----------|
| TestApaiAdminAuth | 6 | Login, logout, auth guards |
| TestApaiAdminDashboard | 3 | Renders, usage display, team section |
| TestApaiAdminTerminal | 2 | Renders, chat input |
| TestApaiAdminTeam | 7 | Add/remove/update members, auth checks |
| TestApaiAdminChat | 3 | Chat, empty message, auth required |
| TestApaiAdminConversations | 3 | List, appear after chat, delete |
| TestApaiAdminUsage | 2 | Usage endpoint, account info |
| TestApaiAdminApiKeys | 3 | Page, generate, revoke |
| TestApaiAdminBilling | 7 | Tier configs, cost calc, quota, usage recording |
| TestApaiAdminOpsec | 3 | Deny list, no Claude exposure, engine branding |
| TestLegacyRedirects | 4 | Old /dev/* URLs redirect |
| TestDevPortalModels | 5 | New fields (role, commercial_account_id, query_limit) |

## Files Modified
| File | Action | LOC |
|------|--------|-----|
| `dev_portal_ai.py` | MODIFIED: ANASTASiA branding, opsec | ~10 |
| `dev_portal_billing.py` | REWRITTEN: APAi tiers, multi-seat billing | 196 |
| `models.py` | MODIFIED: 4 new fields, updated docstring/to_dict | ~20 |
| `routes_devportal.py` | REWRITTEN: APAi admin portal routes | ~700 |
| `server.py` | MODIFIED: registration + webhook comments | ~6 |
| `tests/test_devportal.py` | DELETED | -355 |
| `tests/test_build188_devportal.py` | DELETED | -512 |
| `tests/test_build194_apai_admin.py` | NEW | 607 |
| `tests/test_build185.py` | MODIFIED: cascading fixes | ~15 |

## Architecture Enforced
- **Standalone ANASTASiA AI** = SCRAPPED. No open access outside APAi ecosystem.
- **APAi admin portal** = Management interface for APAi subscribers' dev teams
- **Multi-seat** = Unlimited team seats. Admin provisions members. All queries aggregate to subscriber's pool.
- **ANASTASiA branding** = Customer NEVER sees Claude/Opus/Anthropic. ANASTASiA IS the product.
- **Per-member limits** = Optional per-member query caps set by admin (NULL = unlimited)

## APAi Tier Summary (ALL PROVISIONAL)
| | Pro ($299) | Enterprise ($599) | Scale ($999) |
|---|---|---|---|
| Queries/mo | 500 | 2,000 | 5,000 |
| Overage | $0.12 | $0.08 | $0.05 |
| Routing fee | 5% | 3% | 2% |

## Open Items
- APAi admin portal needs team member invitation flow (email with temp password)
- Per-member usage breakdown dashboard (currently tracked, not displayed per-member)
- Stripe metered billing integration for overage queries
- All APAi pricing is PROVISIONAL
