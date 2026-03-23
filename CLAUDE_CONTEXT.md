# MYSTES PROJECT — SESSION CONTEXT

**Read this file at session start. Full archive: `.context/CLAUDE_CONTEXT_FULL_ARCHIVE_2026-03-17.md`**
**Build logs: `.context/buildXXX_status.md` files (Builds #87-197)**

Last updated: 2026-03-17

---

## CURRENT STATE — Build #197 COMPLETE — LAUNCH READY

### Status: Zero code gaps remaining. Deep hardened. All vertical routes tested.

### Build #197 Complete (2026-03-17)
- **raw_offer passthrough FIXED** — `offer_id` column added to Deal model, explicitly extracted from raw_offer in deal creation (critical bug since Build #179)
- Stripe saved-card atomicity: DB failure after PaymentIntent → `logger.critical()` with intent ID for reconciliation
- Exception sanitization: 7 API endpoints no longer return `str(e)` — generic error messages instead
- Silent exception fixes: payments.py fee lookups, friends activity feed, referral notifications — all now logged
- Google OAuth cleanup: removed redundant `traceback.print_exc()` / `print()` from both handlers
- search.py: module-level logger added, 15+ error/warning `print()` calls converted to `logger`
- **58 new tests** covering all 8 vertical route modules + all code fixes
- 671 consumer + 498 SDK = **1,169 tests, 0 failures, 5 skipped**

### Build #196 Complete (2026-03-17)
- Production hardening: fixed `current_user.first_name` crash in insurance booking
- Config cleanup: removed Coinbase/Transak dead refs, replaced old Dev Portal pricing with APAi tier Stripe IDs
- Composite DB indexes: `(origin, destination, departure_date)` on Deal, `(user_id, status, created_at)` on Booking
- Stripe webhook security: signature verification failures return 400 (not silently swallowed)
- DNS registration: graceful degradation — DNS failures allow signup (verify via email)
- Escrow points: no false 3500 fallback — shows 0 on lookup failure
- Payment verification: XRP/RLUSD errors logged with stack trace + exception type
- 613 consumer + 498 SDK = **1,111 tests, 0 failures, 3 skipped**

### Build #195 Complete (2026-03-17)
- Team member invitation flow (auto temp password + email), per-member usage bars
- Stripe metered billing webhooks, health check hardening, consumer polish
- 591 consumer + 498 SDK = **1,089 tests, 0 failures, 3 skipped**

### Build #194 Complete (2026-03-17)
- APAi Admin Portal: Dev Portal repurposed into multi-seat team management for APAi subscribers
- URLs migrated: `/dev/*` → `/apai/admin/*` with 301 legacy redirects
- Multi-seat: unlimited team seats, aggregate billing against subscriber's pool
- Per-member query limits (optional caps set by admin)
- ANASTASiA branding hardened: underlying model NEVER exposed to customers
- Standalone ANASTASiA AI = **SCRAPPED** — ANASTASiA is APAi-exclusive only
- 567 consumer + 498 SDK = **1,065 tests, 0 failures, 3 skipped**
- See `.context/build194_status.md` for full details

### Build #193 Complete (2026-03-17)
- APAi pitch page (`/apai`): public marketing page for prospective OTA operators
- B2B/APAi boundary fix: deployment routes removed from B2B, moved to APAi-gated flow
- Pricing page fixed: B2B section shows Starter/Growth/Volume only, APAi in separate section
- APAi nav link added, B2B dashboard "Upgrade to APAi" link
- 566 consumer + 498 SDK = **1,064 tests, 0 failures, 3 skipped**

### Completed (Builds #181-192)
- Build #192: My Bookings page, cancel booking flow, cancellation email (1,049 tests)
- Build #191: SEO, marketing pages, social email, 45 E2E smoke tests (1,032 tests)
- Build #190: Insurance polish, fare rules modal, seatmap modal, dashboard cinematic (987 tests)
- Build #189: APAi provisioning, credential routing, Stripe subscription (971 tests)
- Build #188: Mobile native bridge, push backend, production deploy (929 tests)
- Build #187: raw_offer passthrough hardened, AI routes restored (884 tests)
- All neurons, devportal AI, booking tests, mobile, deploy — COMPLETE
- Version 1.2.0, render.yaml PostgreSQL, CI fixed

### Product Model (CRITICAL — CORRECTED MULTIPLE TIMES)
- **B2B** = inside MYSTES. Starter($49)/Growth($99)/Volume($199). Reduced fees. NO turnkey. NO separate site.
- **APAi** = MULTI-TIER: Pro($299)/Enterprise($599)/Scale($999). ALL tiers get turnkey code copy of MYSTES OTA. Own brand/domain. NOT literally MYSTES.
- **Standalone ANASTASiA AI = SCRAPPED** — ANASTASiA is APAi-exclusive. Want ANASTASiA? Subscribe to APAi.
- **NEVER call B2B "turnkey"**.

---

## ARCHITECTURAL DECISIONS (ACTIVE — DO NOT REVERSE)

### Three-Layer Architecture
- L1: API Clients (dumb pipes) — `picasso-sdk/clients/`
- L2: ANASTASiA Intelligence (cards, dedup, dispatch) — `picasso-sdk/anastasia/`
- L3: MYSTES Template (Flask app) — root dir + `picasso-sdk/picasso/agent/`

### Product Boundary
- MYSTES calls ANASTASiA, never reverse
- SDK clients = ANASTASiA strategy. Root clients = MYSTES wrappers. Don't consolidate.
- Template core immutable — customer modules on TOP, never inside

### API Providers (Current)
- **Flights**: Picasso/Redbox (GDS, 102-country POS) + Duffel (NDC, 300+ airlines)
- **Hotels**: liteAPI (2M+ hotels, self-serve)
- **Cars**: DiscoverCars client built
- **Activities**: Viator client built
- **Insurance**: SafetyWing client built
- **DEAD**: SerpAPI, Amadeus Self-Service, Sky Bird — permanently retired

### Knowledge Cards = Compiled Intelligence
- Claude is TEACHER not worker — cards handle 95%+ at zero Anthropic cost
- Dedup funnel: all sources -> ANASTASiA -> keep cheapest per unique itinerary -> one feed

### Payment System
- Stripe + MoonPay ONLY. Coinbase PERMANENTLY RETIRED.
- Fee tiers: Guest=50%, Free=45%, Travel+=35%, B2B Starter=25%, Growth=20%, Volume=15%
- $3 minimum fee, NO MAXIMUM CAP (corrected 4+ times — never add a cap)

### Consumer Strategy (LOCKED)
- Travel+ $9.99/mo, 35% fee, unlimited ANASTASiA AI
- MYSTES Rewards: 10pts/$1, tier multipliers (1x-3x), cross-vertical currency
- Two-tier chat: Knowledge cards (free) + Live Claude (subscribers)
- Homepage = brand launchpad + vertical cards. Flights at /flights.
- Three-tool marketing ($0 ad budget): Google Reviews, Social Share, Referral Cards

### B2B Strategy (LOCKED)
- Starter $49/25%, Growth $99/20%, Volume $199/15%
- NO VOLUME PRICING — same ticket price for every OTA
- Credential network: Own=100%, Borrowed=70% owner/30% host + $2-3 fee

### APAi Strategy (LOCKED — ALL PRICING PROVISIONAL)
- Pro $299/mo (500 queries, $0.12 overage, 5% routing)
- Enterprise $599/mo (2,000 queries, $0.08 overage, 3% routing)
- Scale $999/mo (5,000 queries, $0.05 overage, 2% routing)
- No volume minimums, no custom contracts
- Unlimited dev team seats — all queries aggregate to subscriber's pool
- ANASTASiA branding only — Claude/Anthropic NEVER exposed to customers
- APAi admin portal: `/apai/admin/*` (team management, terminal, API keys)
- APAi pitch page: `/apai` (public marketing)

---

## USER EXPECTATIONS

- User relies on Claude as the memory and continuity layer — do NOT ask user to re-explain decisions
- Review prior work and context BEFORE making changes
- If unsure about a prior decision, check files — do not guess
- Take corrections seriously and update context files
- MYSTES = ALL CAPS in UI. Fonts: Cinzel (headings) + Outfit (body)

---

## SUPERSEDED SYSTEMS (archived, not active)

These were built in early sessions but are no longer the active architecture:
- P2P purchasing network / browser_control.py — superseded by ANASTASiA BookingDispatcher
- XRPL escrow / xrpl_monitor.py — replaced by Stripe-only payments
- CitizenSERP node network / payout system — folded into ANASTASiA credential network
- Proxy portal / geographic zones — replaced by API-based credential routing
- AI ensemble search (9-provider) — replaced by ANASTASiA knowledge cards + Claude subscriber tier
- Commercial tiered API (savings %) — replaced by flat B2B subscription pricing

Full details of these systems preserved in `.context/CLAUDE_CONTEXT_FULL_ARCHIVE_2026-03-17.md`

---

## BUILD HISTORY REFERENCE

| Range | File |
|-------|------|
| Builds #87-141 | `memory/build_log.md` |
| Builds #142-197 | `memory/build_log_recent.md` |
| Full pre-trim context | `.context/CLAUDE_CONTEXT_FULL_ARCHIVE_2026-03-17.md` |
