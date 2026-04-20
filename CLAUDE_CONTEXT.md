# MYSTES PROJECT — SESSION CONTEXT

**Read this file at session start. Full archive: `.context/CLAUDE_CONTEXT_FULL_ARCHIVE_2026-03-17.md`**
**Build logs: `.context/buildXXX_status.md` files (Builds #87-197)**

Last updated: 2026-04-16

---

## CURRENT STATE — Trip Planner Engine

### Latest Session (2026-04-16): Block 2 Complete
- **Block 1 DONE**: FX-aware pricing, InviteLink (#219), Companions (#220). 61 tests. Total: 1,816.
- **Block 2 DONE**: Trip Planner Engine (Builds #221-223). 66 tests. Total: 1,882.
  - **#221**: TripParty + TripGuest models + 9 API endpoints (routes_trip_planner.py)
  - **#222**: ItineraryItem model (stores SEARCH PARAMS, not static results) + 5 endpoints
  - **#223**: Scoping engine (trip/party/individual/custom cost allocation) + settlement calculator
  - **#224 prep**: ItineraryVote + ItemComment models (no routes yet)
- **Files created**: `routes_trip_planner.py` (16 endpoints), `tests/test_block2_trip_planner.py` (66 tests)
- **Files modified**: `models.py` (5 new models), `server.py` (route registration)
- **Key lesson**: Flask test clients with separate `app.test_client()` instances share session state when `auth_client` fixture is active. Use `session_transaction()` with `_user_id` injection on a single client for multi-user access control tests.
- **Next builds**: #224 (Voting + comments routes), #225+ per architecture doc

### Active Threads (2026-04-14)
- **LAUNCH TARGET: 2026-04-28** (2 weeks). Build plan: `.context/pre_launch_build_plan_2026-04-14.md`
- **ARCHITECTURE PIVOT**: Physical SIM farm DEFERRED. Bright Data residential proxy for BOTH search AND booking. No hardware.
- **Key Insight**: POS pricing = IP geolocation, NOT IP type. Residential proxy = same POS pricing as mobile SIM. SIM farm unnecessary for launch.
- **Bright Data**: PAYG $4/GB (promo RESIGB50), Enterprise $2.50/GB. Scraping Browser for booking (sticky sessions, CAPTCHA solving, CDP Playwright).
- **Build #202 EXECUTED** (2026-04-10): All `ESTIMATED_RETAIL_MARKUP = 1.55` blocks removed from search.py.
- **Build #203 BLOCKED**: Revenue model for credential routing. Under discussion.
- **Builds #204-213 PLANNED**: Pre-launch builds. See build plan.
- **US-First Geo-Targeting**: US IP → proxy-arbitraged pricing. Non-US IP → standard API pricing. No geo-blocking.
- **Bot Protection**: Email verification gate on live search. Guest checkout preserved. No KYC.
- **Clean Hands Confirmed**: Airline = MoR for ticket. KYRIOS = MoR for service fee only.
- **Launch Economics**: $473/mo fixed cost. Break-even = 1 international booking/day. Month 1 projected ~$800K revenue at 95.5% margin. See `.context/launch_economics_2026-04-14.md`
- **MYSTES Network** (Phase 2): Rework CitizenSerp (31K LOC) into KYRIOS-owned proxy network. Users become nodes, earn rewards. Replaces Bright Data at scale. Target: Month 3-6.
- **$1B Roadmap**: Flights ($522M) + Hotels ($270M) + Cars/Activities ($144M) + Subscriptions ($65M). Requires ~25M visitors/mo by Month 12. Multi-vertical POS arbitrage is the multiplier.

### Previous Builds (Complete)

### Build #201 Complete (2026-03-17)
- Credential network wiring: vault, network, revenue calculator, credential router
- Revenue model WRONG (flat $2.50 hardcoded — needs fix per discussion above)
- 28 integration tests, 1,301 total (775 consumer + 526 SDK), 0 failures
- See `.context/build201_status.md`

### Build #200 Complete (2026-03-17)
- Duffel lifecycle wiring (search → offer → order → payment)

### Build #199 Complete (2026-03-17)
- Duffel Stays integration (hotel pricing)

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
- **SerpAPI**: DEAD for POS pricing (gl=dk returns US prices). RETAINED for US baseline only.
- **DEAD**: Amadeus Self-Service, Sky Bird — permanently retired
- **SIM Farm**: CitizenSerp — DEFERRED to Phase 3 cost optimization. Not needed for launch.
- **Proxy (LAUNCH)**: Bright Data residential — BOTH search AND booking. PAYG $4/GB (promo). 150M+ IPs, 195 countries. Scraping Browser for booking (CDP + anti-detection).
- **Proxy (PHASE 2)**: MYSTES Network — reworked CitizenSerp (31K LOC). Users become nodes, earn rewards. Replaces Bright Data.
- **Proxy (LEGACY)**: Webshare.io — kept as fallback. 17-market residential.

### Knowledge Cards = Compiled Intelligence
- Claude is TEACHER not worker — cards handle 95%+ at zero Anthropic cost
- Dedup funnel: all sources -> ANASTASiA -> keep cheapest per unique itinerary -> one feed

### Payment System
- Stripe + MoonPay ONLY. Coinbase PERMANENTLY RETIRED.
- **Stripe Issuing virtual cards = ELIMINATED** (2026-04-14). Customer's real card used directly on airline checkout. Airline = MoR.
- KYRIOS charges separate service fee via Stripe. Fee = % of spread (US retail - foreign POS price).
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
- B2B on MYSTES = "gated APAi" with SIM farm pricing advantage
- B2B → APAi migration path when operator wants own brand (loses SIM pricing)

### APAi Strategy (PRICING LOCKED — ROUTING MODEL UNDER DISCUSSION)
- Pro $299/mo (500 queries, $0.12 overage)
- Enterprise $599/mo (2,000 queries, $0.08 overage)
- Scale $999/mo (5,000 queries, $0.05 overage)
- **Credential routing fee: UNDER DISCUSSION** — was percentage 5%/3%/2%, user disputes. May be $0 (subscription IS revenue). See strategy session archive.
- No volume minimums, no custom contracts
- Unlimited dev team seats — all queries aggregate to subscriber's pool
- ANASTASiA branding only — Claude/Anthropic NEVER exposed to customers
- APAi admin portal: `/apai/admin/*` (team management, terminal, API keys)
- APAi pitch page: `/apai` (public marketing)
- **Three value props**: (1) Infrastructure access (KYRIOS credentials), (2) ANASTASiA SDK automation of subscriber's own credentials, (3) Turnkey MYSTES template deployment
- **SIM stack exclusivity PROPOSED**: MYSTES gets SIM pricing, APAi OTAs do NOT. Not committed.

---

## USER EXPECTATIONS

- User relies on Claude as the memory and continuity layer — do NOT ask user to re-explain decisions
- Review prior work and context BEFORE making changes
- If unsure about a prior decision, check files — do not guess
- Take corrections seriously and update context files
- MYSTES = ALL CAPS in UI. Fonts: Space Grotesk (headings) + Outfit (body)

---

## SUPERSEDED SYSTEMS (archived, not active)

These were built in early sessions but are no longer the active architecture:
- P2P purchasing network / browser_control.py — superseded by ANASTASiA BookingDispatcher
- XRPL escrow / xrpl_monitor.py — replaced by Stripe-only payments
- CitizenSERP node network / payout system — evolved into SIM farm (KYRIOS-owned infrastructure). Changes credential network from "foundational" to "optional opsec". See strategy session 2026-04-08.
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
| Builds #198-201 | `.context/build{199,200,201}_status.md` |
| Strategy session 2026-04-08 | `.context/strategy_session_apai_sim_farm_2026-04-08.md` |
| Viral architecture 2026-04-14 | `.context/viral_architecture_session_2026-04-14.md` |
| Launch economics 2026-04-14 | `.context/launch_economics_2026-04-14.md` |
| Pre-launch build plan | `.context/pre_launch_build_plan_2026-04-14.md` |
| Full pre-trim context | `.context/CLAUDE_CONTEXT_FULL_ARCHIVE_2026-03-17.md` |
