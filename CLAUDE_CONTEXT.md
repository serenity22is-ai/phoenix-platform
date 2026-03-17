# MYSTES PROJECT — SESSION CONTEXT

**Read this file at session start. Full archive: `.context/CLAUDE_CONTEXT_FULL_ARCHIVE_2026-03-17.md`**
**Build logs: `.context/buildXXX_status.md` files (Builds #87-180)**

Last updated: 2026-03-17

---

## CURRENT STATE — Build #180

### Status: ANASTASiA Integration Architecture (discussion interrupted by API 500s)

### Key Decision: Wire MYSTES Through ANASTASiA (NOT parallel routes)
- ANASTASiA already has: SearchDispatcher, BookingDispatcher, BundleBuilder, FlightsNeuron, HotelsNeuron, PassengerTransformer, 91+ API endpoints
- Build #174's approach of building parallel routes was WRONG — new verticals should be ANASTASiA Neurons
- MYSTES search/booking should call ANASTASiA SDK, not duplicate it

### Critical Bug: raw_offer passthrough
- Flight cards don't carry fare_id/offer_id into Deal records
- Automated booking broken — no reference to pass to BookingDispatcher
- Must fix before booking pipeline works end-to-end

### Consumer Social Features (MYSTES-only, need routes)
- Trip Planner (6 tables exist, 0 routes)
- Collections/Wishlist (2 tables exist, 0 routes)
- Friends (1 table exists, 0 routes)

### Next Steps
1. Fix raw_offer passthrough bug
2. Wire MYSTES search -> ANASTASiA SearchOrchestrator (partially done Build #176)
3. Wire MYSTES booking -> ANASTASiA BookingDispatcher
4. Build Trip Planner/Collections/Friends UI routes
5. Create CarsNeuron, ActivitiesNeuron, InsuranceNeuron

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
- APAi $600/mo flat — no volume minimums, no custom contracts
- Credential network: Own=100%, Borrowed=70% owner/30% host + $2-3 fee
- NO VOLUME PRICING — same ticket price for every OTA

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
| Builds #142-179 | `memory/build_log_recent.md` |
| Build #180 | `.context/build180_status.md` |
| Full pre-trim context | `.context/CLAUDE_CONTEXT_FULL_ARCHIVE_2026-03-17.md` |
