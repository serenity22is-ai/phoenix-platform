# Build #195 — Production Hardening + APAi Admin Improvements
**Date**: 2026-03-17
**Status**: COMPLETE
**Tests**: 1,089 total (591 consumer + 498 SDK), 0 failed, 3 skipped

---

## What Was Done

### 1. CLAUDE_CONTEXT.md Update
- Updated current state from Build #192 to Build #194
- Corrected APAi pricing from "$600/mo flat" to multi-tier ($299/$599/$999)
- Added dedicated "APAi Strategy (LOCKED)" section with tier details
- Added note about standalone ANASTASiA being SCRAPPED
- Updated build log range from "#142-189" to "#142-194"

### 2. raw_offer Passthrough Verification
- **Result**: FIXED since Build #187 — production-ready
- All 4 search paths (ANASTASiA, Picasso, Duffel, Kiwi) emit raw_offer
- Safety guard reconstruction from top-level fields as fallback
- 44 existing tests validate the chain
- No code changes needed

### 3. Team Member Invitation Flow (APAi Admin Portal)
**Files**: `models.py`, `routes_devportal.py`, `email_service.py`

- Added 3 new fields to `DevPortalAccount`: `invitation_token`, `invitation_sent_at`, `invitation_expires_at`
- Server auto-generates temp password (`Tmp{token_hex(4)}!`) — no client-side password needed
- Generates invitation token (`token_urlsafe(32)`) for secure onboarding
- New `send_team_invitation_email()` function with branded ANASTASiA template
- Dashboard JS updated: "Add" → "Invite" button with loading state

### 4. Per-Member Usage Breakdown Dashboard
**File**: `routes_devportal.py`

- Enhanced team member cards with per-member usage progress bars
- Color-coded: green (< 70%), yellow (< 90%), red (>= 90%)
- Shows `{queries_used} / {limit}` per member
- Added "Team Size" stat card to dashboard grid

### 5. Stripe Metered Billing Webhooks
**File**: `server.py`

- New `checkout.session.completed` handler for APAi subscriptions:
  - Creates DevPortalAccount (admin) with correct tier, Stripe IDs, period info
  - Sets queries_included from tier config
  - Sends welcome email
- New `invoice.payment_failed` handler for APAi accounts → sets `subscription_status = 'past_due'`
- Enhanced subscription webhook: billing period reset for admin + ALL team members

### 6. Health Check Hardening
**File**: `server.py`

- Removed stale services: XRPL, proxy_scraper, browser_control
- Added: `apai_portal` (admin/member counts), `anastasia_api` (configured status)
- Updated version: `1.3.0`, build: `195`

### 7. Consumer Polish
**Files**: `server.py`, `email_service.py`

- FAQ: Changed "$600/mo" to multi-tier description with `/apai` link
- Welcome email: Removed "Claude Opus 4.6" and "$0.15/query" references
- Welcome email: Updated URLs from `/dev/terminal` to `/apai/admin/terminal`
- Welcome email: Rebranded to "APAi Admin Portal"

### 8. Tests
**File**: `tests/test_build195_improvements.py` (NEW — 24 tests)

| Class | Tests | Coverage |
|-------|-------|----------|
| TestTeamInvitation | 5 | Invite flow, email, no password, duplicate, login |
| TestPerMemberUsage | 4 | Dashboard members, usage bars, team size, stat cards |
| TestStripeBilling | 4 | Period reset, overage calc, tier configs, quota check |
| TestHealthCheck | 5 | 200, version, APAi portal, ANASTASiA API, no stale |
| TestEmailTemplates | 3 | Invitation func, no Claude refs, new URLs |
| TestFAQPricing | 1 | No $600 reference |
| TestModelFields | 2 | invitation_token, invitation_expires_at |

**Cascading fix**: Updated `test_build194_apai_admin.py::test_add_member_short_password_rejected` → `test_add_member_no_password_needed` (reflects new auto-generated password flow)

---

## Files Modified

| File | Changes |
|------|---------|
| `CLAUDE_CONTEXT.md` | Updated state, APAi pricing, build log |
| `models.py` | +3 fields on DevPortalAccount (invitation flow) |
| `routes_devportal.py` | Invitation flow, usage bars, team size card, JS updates |
| `email_service.py` | New `send_team_invitation_email()`, fixed welcome email branding |
| `server.py` | APAi webhooks, health check, FAQ fix |
| `tests/test_build195_improvements.py` | NEW — 24 tests |
| `tests/test_build194_apai_admin.py` | Fixed cascading test (password → invitation) |

## Test Results
```
Consumer: 591 passed, 3 skipped, 0 failed (161.75s)
SDK:      498 passed, 0 failed (1.08s)
Total:    1,089 passed, 3 skipped, 0 failed
```

## Next Build (#196) Candidates
- ANASTASiA integration architecture (Build #180 topic, deferred)
- Install Wizard Knowledge Card
- APAi deployment pipeline end-to-end testing
- Consumer social features polish
- Mobile (Capacitor) deployment prep
