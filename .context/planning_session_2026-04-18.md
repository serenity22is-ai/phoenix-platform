# Planning Session — 2026-04-18
# APAi Credential Network, Tier Incentives, Platform Features
# ARCHIVE BEFORE BUILD — word for word decisions

---

## SESSION CONTEXT
- Font replacement: Cinzel → Space Grotesk completed across entire codebase (all active .py, .html files, tests, docs, memory)
- APAi website (apai.co) built and deployed: website.py with HOMEPAGE_HTML, PRICING_HTML, DOCS_HTML, DEMO_HTML
- MYSTES deployment readiness audit completed (P0/P1/P2 items identified)
- This session = pure planning for credential network system + tier restructuring

---

## 1. DIRECT BOOKING BRIDGE (renamed from "Proxy")

**Decision:** "Proxy" is renamed to "Direct Booking Bridge" across all user-facing contexts.
- User said: "calling it proxy isn't a good name and raises red flags"
- The tool bridges the consumer directly to the airline's own checkout
- Airline is MoR (merchant of record), not MYSTES
- On the credential network, this is listed as a credential TYPE alongside GDS/NDC:
  - Amadeus GDS
  - Sabre GDS
  - Duffel NDC
  - **Direct Booking Bridge** ← MYSTES's unique offering
- It is costly (Bright Data infra) but provides serious arbitrage
- MYSTES is the credential holder in the APAi ecosystem that provides this

---

## 2. P2P ROUTING — MYSTES TAKES $0

**Critical correction made during session:**

User said: "apai takes nothing between routers because they are paying a massive apai subscription fee to us already. they have 100% autonomy between one another. we dont need a piece of that. they are already paying for anastasia. we only take a piece of what we route for customers."

**TWO ROUTING CONTEXTS:**

### Context A: P2P (APAi subscriber ↔ APAi subscriber)
- MYSTES takes **$0**
- Full autonomy between subscribers
- They set their own query fees, revenue splits, terms
- They're already paying $299/$599/$999 subscription
- The credential network is an **amenity of the subscription**, not a revenue extraction point
- ANASTASiA enforces whatever terms they agreed to — she's the engine, not the toll booth

### Context B: MYSTES consumer path (MYSTES as router using network credentials)
- 5%/3%/2% routing fee by APAi tier
- $3 minimum, NO maximum cap
- Then split: 70% MYSTES (router) / 30% host (credential lender)
- This is MYSTES's cost as a network PARTICIPANT, not a platform tax
- Only applies when mystes.app consumer bookings use someone else's credentials

### Own credentials = 100% margin in EITHER context
No fee, no split, no routing charge.

**Memory updated with recurring mistake entry 6b to prevent future confusion.**

---

## 3. REVENUE SPLIT FLEXIBILITY

**Decision:** 70/30 is NOT hardcoded for P2P.
- User said: "the 70/30 split isn't in stone because we want providers to create their own terms"
- Providers can agree on whatever split they want: 50/50, 80/20, 90/10, 0/100
- The default template shows 70/30 as a suggested starting point but it's fully editable
- "they may find an agreement between ota a and ota b that is mutually exclusive and they want to be competitive"
- "we want to give the users full autonomy over pricing between each other"

---

## 4. ROUTING TERMS CARD — MACHINE-READABLE CONTRACT

User said: "we need to have denoted options that anastasia can execute with. so we need to think of them and have a card they fill out that anastasia can use or we will have information that does nothing."

Every field on the terms card must be **machine-executable** — ANASTASiA reads these in real-time when routing.

### Section 1: Pricing
| Field | Type | Example | ANASTASiA action |
|-------|------|---------|-----------------|
| Per-query fee | $/query | $0.02 | Charges router's account per search |
| Revenue split | % / % | 60 / 40 | Divides remaining margin |
| Minimum booking value | $ | $75 | Skips credential if ticket below threshold |
| Minimum margin | $ | $5 | Won't route if spread too thin |
| Currency | ISO code | USD | Converts all calculations |

### Section 2: Coverage
| Field | Type | Example | ANASTASiA action |
|-------|------|---------|-----------------|
| Credential type | Enum | GDS / NDC / Direct Booking Bridge | Determines booking pipeline |
| Provider system | Text | Amadeus, Duffel, etc. | Routes to correct API client |
| Markets included | Country codes | [US, GB, DE, JP] | Only routes for these POS markets |
| Markets excluded | Country codes | [RU, BY] | Never routes for these |
| Airlines included | IATA codes | [LH, BA, AA] or "ALL" | Filters by carrier |
| Airlines excluded | IATA codes | [FR, W6] | Blocks specific carriers |
| Cabin classes | Enum list | [Economy, Business] | Filters by cabin |
| Trip types | Enum list | [one-way, round-trip] | Filters by trip type |

### Section 3: Operational Limits
| Field | Type | Example | ANASTASiA action |
|-------|------|---------|-----------------|
| Max queries/day | Number | 5,000 | Stops routing after limit |
| Max queries/hour | Number | 500 | Prevents burst abuse |
| Max bookings/day | Number | 100 | Caps booking volume |
| Available hours | Time range | 00:00-23:59 UTC | Only routes during windows |
| Response time SLA | Seconds | 8s | Falls back if exceeded |
| Auto-pause error rate | % | 15% | Disables if errors too high |

### Section 4: Relationship
| Field | Type | Example | ANASTASiA action |
|-------|------|---------|-----------------|
| Exclusive | Boolean | No | If yes, only this router |
| Minimum monthly volume | Queries | 500 | Alert if below commitment |
| Notice period | Days | 30 | Grace period for disconnect |
| Trial period | Days | 14 | Free queries before billing |
| Auto-renew | Boolean | Yes | Terms roll over monthly |

### Section 5: Arbitrage Permissions
| Field | Type | Example | ANASTASiA action |
|-------|------|---------|-----------------|
| Allow POS arbitrage | Boolean | Yes | Whether creds can be used for POS arbitrage |
| Markup cap | % | None | Maximum markup router can add |
| Price visibility | Enum | Blind / Transparent | Whether host sees final consumer price |

### ANASTASiA Routing Logic (when search comes in):
1. Identify all active connections covering requested route (market, airline, cabin)
2. Filter by operational limits (not over cap, within hours, not error-paused)
3. Rank by cost-effectiveness: query fee, success rate, response time, expected margin
4. Fan out to top N credentials in parallel (existing dedup funnel)
5. At booking: pick best price, apply revenue split per connection terms, charge query fee, log everything

### UX for filling out the card:
- Step 1: "Add a credential" — select type, system, markets, airlines
- Step 2: "Set your terms" — sliders for fees/splits, dropdowns for limits
- Step 3: "Publish to network" — preview card, publish button
- Two screens, maybe three. ANASTASiA handles the rest.

---

## 5. CREDENTIAL TYPE FILTERS

Network directory filters:
- **System type**: GDS / NDC / Direct Booking Bridge / Hotel API / Car API / Activity API
- **Specific provider**: Amadeus, Sabre, Travelport, Duffel, AirGateway, liteAPI, etc.
- **Market coverage**: EU, APAC, LATAM, NA, Middle East, Africa
- **Airline coverage**: Full-service, LCC, Alliance (Star/OneWorld/SkyTeam)
- **Query pricing**: Free / Under $0.05 / Under $0.10 / Any
- **Minimum rating**: Network uptime/reliability score

---

## 6. PROVIDER PROFILE CARD (public-facing)

```
┌─────────────────────────────────────────┐
│  ACME Travel Co.                    ★4.8│
│  APAi Enterprise • On network 8 months  │
│─────────────────────────────────────────│
│  CREDENTIALS                            │
│  ◉ Amadeus GDS — 38 markets (EU/APAC)  │
│  ◉ Duffel NDC  — 22 airlines           │
│  ◉ liteAPI     — 2.5M hotels           │
│─────────────────────────────────────────│
│  ROUTING TERMS                          │
│  Query fee:     $0.02/search            │
│  Min booking:   $50 ticket value        │
│  Markets:       Open (no restrictions)  │
│  Revenue split: Configurable            │
│─────────────────────────────────────────│
│  NETWORK STATS                          │
│  Uptime: 99.7% │ Avg resp: 1.2s        │
│  Bookings routed: 1,247 lifetime        │
│─────────────────────────────────────────│
│  [Request Connection]    [View Full]    │
└─────────────────────────────────────────┘
```

### MYSTES Card (unique):
```
┌─────────────────────────────────────────┐
│  MYSTES (Platform Provider)        ★───│
│  APAi Scale • Network Operator          │
│─────────────────────────────────────────│
│  CREDENTIALS                            │
│  ◉ Direct Booking Bridge — Any airline  │
│  ◉ Duffel NDC  — 22 airlines           │
│  ◉ Duffel Stays — Hotels               │
│─────────────────────────────────────────│
│  ROUTING TERMS                          │
│  Query fee:     At-cost (infra only)    │
│  Bridge fee:    Based on spread         │
│  Note:          Not MoR — airline       │
│                 issues ticket directly  │
│─────────────────────────────────────────│
│  [Auto-Connected]                       │
└─────────────────────────────────────────┘
```

Credentials are OPAQUE — you never see actual login credentials, only metadata (type, coverage, terms).

---

## 7. DASHBOARD — MY NETWORK PAGE

Every APAi subscriber gets a "My Network" section:

### Active Connections tab:
- Cards for each provider they're routing through
- Cards for each OTA routing through THEM
- Per-connection stats: queries this month, bookings, revenue earned/paid, avg response time
- Connection health indicator (green/yellow/red)
- "Disconnect" option with notice period

### Directory tab:
- Searchable grid of all providers with filters
- Provider profile cards
- "Request Connection" button

### Pending tab:
- Incoming requests
- Outgoing requests
- Terms review before accepting

---

## 8. QUERY COST PROTECTION (TWO-LAYER TERMS)

**Problem identified:** If Provider A has Duffel credentials and Duffel charges $0.01/query after their limit, and 50 OTAs route searches through Provider A's Duffel, Provider A subsidizes everyone's search costs. They'd leave the network.

**Solution:** Per-query fee set by the HOST (credential owner):
- $0.00 — free (loss leader for volume → more bookings)
- At-cost — e.g., $0.01 if that's what Duffel charges
- Marked up — e.g., $0.03 (covers cost + profit per query)

**This creates the sub-API provider model:**
- OTA with Amadeus contract paying $X/query can resell at $X+margin
- User: "this essentially lets otas become sub-api providers where they can charge the same way a traditional api provider does. an entirely new market."
- An asset that was a pure cost center becomes a revenue stream

---

## 9. API-ONLY INTEGRATION (EXISTING STACKS)

**Decision:** One product, two delivery modes, same API key.
- NOT separate products for API vs turnkey
- Same key works everywhere: turnkey template OR your own stack
- Turnkey is a free bonus / reference implementation
- Integration options: Python SDK, JS SDK, raw REST, webhooks
- "Get your API key. Drop it into our turnkey OTA and you're live in 5 minutes. Or call the same endpoints from your existing stack. Same key, same intelligence, same credential network."

---

## 10. DEPLOYMENT READINESS — P0 FIXES (from audit)

### P0 — Must fix before deploy:
1. **Alembic migrations missing** — 30+ models from builds #199-237 have no migration files. Dockerfile runs `flask db upgrade` → tables never created.
2. **Missing Python deps** — `qrcode[pil]`, `sentry-sdk[flask]`, `Pillow` not in requirements.txt
3. **Missing env vars** — SENTRY_DSN, BRIGHTDATA_*, WEBSHARE_*, DUFFEL_WEBHOOK_TOKEN, OPS_ALERT_EMAIL

### P1 — Should fix:
4. **BookingWorker starts at import** — crashes tests. Gate behind `if not app.config.get('TESTING')`
5. **citizenserp/ routes not registered** — legacy P2P code, reference models that don't exist
6. **No HTML pages for API-only routes** — Corporate, Social, Referral, Events, SharedCarts all API-only
7. **Phase C features all disabled** — by design, gated behind 500 active planners

### P2 — Nice to have:
8. Duplicate `/arbitrage-search` route (old) vs `/arbitrate` (correct)
9. 111+ uncommitted files

---

## 11. APAi TIER RESTRUCTURING — CAPABILITY TIERS

**Problem identified:** Current tiers only differentiate on query volume/overage. No feature pull to upgrade. Enterprise doesn't beat Pro until ~3,000 queries/month. Weak incentive.

**Solution:** Feature-differentiated tiers. Core engine same everywhere, tiers unlock operational tools.

### Pro ($299/mo) — "I'm getting started"
- 500 queries/mo, $0.12 overage
- Full API access (111+ endpoints)
- Turnkey template — basic branding (logo, colors, company name)
- Credential vault — up to 3 credentials
- Network access — can route and be routed through
- 1 team seat (owner only)
- Basic analytics — total bookings, total revenue, monthly summary
- Community support + docs
- Default notification templates
- Sandbox environment

### Enterprise ($599/mo) — "I'm running a business"
Everything in Pro, plus:
- 2,000 queries/mo, $0.08 overage
- Credential vault — up to 10 credentials
- 5 team seats with roles (admin, operations, finance, developer, read-only)
- Full revenue analytics — P&L per connection, per route, per market, trend lines
- Webhook system — real-time callbacks for booking events, credential alerts, terms changes
- Custom notification templates — full HTML control over every customer email
- White-label turnkey — remove all APAi/MYSTES branding, custom domain
- Dynamic terms — seasonal pricing, time-based query limits, calendar rules
- Query budget controls — monthly spend caps with auto-pause
- Transaction audit trail — immutable ledger of every routing event
- Email support — 24h response

### Scale ($999/mo) — "I'm building an empire"
Everything in Enterprise, plus:
- 5,000 queries/mo, $0.05 overage
- Credential vault — unlimited credentials
- Unlimited team seats
- Network intelligence feed — anonymized market data, hot routes, supply/demand gaps, arbitrage opportunities
- Provider reputation dashboard — data-driven reliability scores
- Credential health monitoring — real-time status, automated alerts, stale detection
- Booking failure recovery — automatic fallback chain across credentials
- Revenue forecasting — projected earnings based on volume/terms
- Bulk operations — change terms across all connections at once
- API batch endpoints — bulk search, bulk status, streaming
- Data export — full booking/customer/credential data on demand
- Priority support — 4h response, dedicated channel

### Upgrade Triggers:
**Pro → Enterprise:** "I hired my second person" / "I can't tell which connections are profitable" / "Customers ask why emails say APAi" / "I need seasonal terms"
**Enterprise → Scale:** "I have 12 GDS contracts" / "I want market intelligence" / "A booking failed at 2am and nobody caught it" / "Overage math makes Scale cheaper"

### The "Taste" Strategy:
Pro users can SEE greyed-out Enterprise features in their dashboard. Blurred analytics preview, greyed webhook config. Not a paywall — a window. "Here's what you're not using yet."

### What is NOT tier-gated (core promises):
- ANASTASiA intelligence quality — Opus 4.6 at every tier
- Full API access — same 111+ endpoints
- Network access — everyone can route
- Turnkey template — everyone gets it
- Sandbox — everyone can test
- Security — same encryption, same vault

---

## 12. PLATFORM FEATURES BRAINSTORM — "WOW THEY THOUGHT OF EVERYTHING"

### Must-have features:
1. **Revenue analytics per connection** — P&L per route, per credential, per market
2. **Booking failure recovery / fallback chain** — auto-retry with different credential
3. **Credential health monitoring + alerts** — real-time status, stale detection
4. **Transaction audit trail** — immutable ledger, dispute prevention
5. **Query budget controls** — monthly spend caps, auto-pause

### High-value features:
6. **Network intelligence feed** — anonymized hot routes, supply/demand, arbitrage opportunities
7. **Dynamic/seasonal terms** — calendar-based rule switching
8. **Provider reputation scores** — data-driven, auto-calculated from routing performance (not user reviews)
9. **Team roles for network features** — extend existing team management
10. **Ticketing status tracking** — PNR ticketing status for GDS bookings, time-limit alerts

### Wow-factor features:
11. **Credential onboarding wizard** — ANASTASiA-guided, detects credential type, validates with test search, one-screen publish
12. **White-label notification chain** — entire customer lifecycle branded (confirmations, alerts, feedback)
13. **No lock-in data export** — one-click export of all data. Easy to leave = trust = they stay.
14. **Credential cost calculator** — pre-signup widget on apai.co showing "your GDS goes from cost center to revenue source"
15. **Query budget visualization** — "you've spent $340 of your $500 budget this month, 12 days remaining"

### Key insight from user:
"we want to give the users full autonomy over pricing between each other and we need to think of all the terms they would like to be able to address that anastasia can intelligently route with"

---

## 13. APAI.CO WEBSITE REFRESH NEEDED

Current site needs new/revised sections:
1. **"The Credential Network"** — directory preview, provider cards, terms transparency, connect flow
2. **"Integration Options"** — turnkey vs API side by side, same key
3. **Enhanced pricing** — new tier features (not just query volume), capability comparison table
4. **MYSTES positioning** — unique Direct Booking Bridge provider, auto-connected
5. **Sub-API provider pitch** — "turn your credentials into a revenue stream"
6. **Credential cost calculator widget** — pre-signup ROI demonstration
7. **Ecosystem pitch** — "every OTA that joins makes the network stronger for everyone"

---

## 14. REVISED SEGMENT BUILD PLAN

**Segment 1 — MYSTES P0 Deploy Fixes** (foundation)
- Add missing deps to requirements.txt
- Generate Alembic migration for 30+ new models
- Gate BookingWorker behind TESTING check
- Document missing env vars
- Remove duplicate /arbitrage-search route

**Segment 2 — Network Profile System (APAi SDK backend)**
- ProviderProfile model with credential listings, terms, stats
- RoutingTerms model with all 5 sections (pricing, coverage, limits, relationship, arbitrage)
- NetworkConnection model with status, accepted terms, stats tracking
- API endpoints: directory, profile CRUD, connect/disconnect, terms
- Query cost accounting in credential router
- Transaction audit trail logging

**Segment 3 — Network UI (APAi dashboard)**
- My Network page (active connections, directory, pending)
- Provider profile cards with credential listings
- Terms card editor (sliders, dropdowns, publish flow)
- Connection request/accept flow
- Revenue analytics (tier-gated: basic for Pro, full for Enterprise+)

**Segment 4 — apai.co Website Refresh**
- New credential network section
- New integration options section
- Updated pricing with feature comparison table
- MYSTES positioning, ecosystem pitch
- Credential cost calculator widget

**Segment 5 — Tier Feature Gating**
- Implement tier checks for: vault limits (3/10/unlimited), team seats (1/5/unlimited)
- Analytics depth gating (basic/full/intelligence)
- Webhook system (Enterprise+)
- White-label controls (Enterprise+)
- Network intelligence feed (Scale only)
- Failure recovery automation (Scale only)
- "Taste" strategy — greyed-out previews for lower tiers

**Segment 6 — Commit + Deploy**
- Commit all 111+ files + new network system
- Deploy MYSTES to mystes.app
- Deploy APAi to apai.co

---

## 15. LOCKED DECISIONS FROM THIS SESSION

1. "Proxy" → "Direct Booking Bridge" in all user-facing contexts
2. P2P routing = MYSTES takes $0. Subscription fee is the revenue.
3. Revenue splits are fully configurable P2P, no default imposed
4. Terms card has 5 sections with machine-executable fields ANASTASiA can route on
5. Credential type filters on network directory (GDS/NDC/Direct Booking Bridge/Hotel/Car)
6. Query cost protection via per-query fees set by credential holder
7. Sub-API provider model = OTAs reselling API access through the network
8. One product, two delivery modes (API + turnkey), same key
9. Tier restructuring: Pro = engine, Enterprise = cockpit, Scale = control tower
10. Feature-differentiated tiers, not just volume-differentiated
11. Vault limits: 3 (Pro) / 10 (Enterprise) / unlimited (Scale)
12. Team seats: 1 / 5 / unlimited
13. "Taste" strategy for upgrade motivation (greyed-out previews)
14. No lock-in guarantee with data export
15. Font: Space Grotesk (headings) + Outfit (body) — Cinzel fully removed
16. ANASTASiA Terminal ships with every turnkey deployment — built-in AI architect
17. Terminal is the overage revenue engine — dev sessions = billed queries
18. Custom SDK development: build → ANASTASiA audit → sandbox test → deploy → optional marketplace publish
19. Admin mode on every turnkey: consumer frontend + admin dashboard + ANASTASiA Terminal
20. Per-tenant sandboxed context — ANASTASiA knows only that tenant's customizations
21. ANASTASiA = sole qualified architect (she built the codebase, knows the internals)
22. Proprietary privacy — external AI can't match her internal knowledge card context

---

## 16. ANASTASiA TERMINAL — BUILT-IN AI ARCHITECT

User said: "we have admin mode on the turnkey models and all models come with an anastasia terminal for troubleshooting and building products. whether creating your own custom model that anastasia builds and implements or just developing to build intelligently edit your own model the way you see fit as the user. we want them to be using ai queries we sell and we want them using the anastasia for live api calls as we make money on query overages. especially if they have dev teams working to make the product better."

User said: "they have proprietary privacy as well using our developer portal because anastasia knows the turnkey model inside and out and is the perfect ai sourcing her own knowledge cards and only qualified architect. they can build as they see fit within the ecosystem custom sdks and anastasia will audit and deploy them."

### Three Layers Per Turnkey Deployment:
1. **Consumer Frontend** — the OTA that end-users see and book through
2. **Admin Dashboard** — analytics, credentials, network, terms, team management
3. **ANASTASiA Terminal** — development environment, troubleshooting, custom modules

### Terminal Capabilities:

**Troubleshooting (all tiers):**
- Trace booking failures through the pipeline
- Diagnose credential routing errors
- Check connection health and SLA compliance
- Live analytics queries

**Configuration (all tiers):**
- Modify notification templates
- Add seasonal pricing rules
- Update routing terms
- Configure branding and UI

**Custom Development (the overage revenue engine):**
- Build custom feature modules via natural language
- Create custom reports and dashboards
- Build webhook integrations
- Develop customer-facing pages

**Custom SDK Development (Enterprise/Scale):**
- Build vertical-specific modules (cruise booking, visa assistance, group travel, etc.)
- ANASTASiA audits code against internal APIs
- Security scan, compatibility check, performance audit
- Sandbox test deploy with mock data
- Production deploy with 24h error monitoring + auto-rollback
- Optional: publish to APAi marketplace for other subscribers

### Revenue Alignment:
- Every terminal interaction = billed ANASTASiA query
- Solo founder troubleshooting: 5-10 queries/session
- 3-person dev team building features: 50-100 queries/day
- 5-person team in active sprint: 200+ queries/day
- Pro tier (500 queries/mo) exhausted in ~1 week by active dev team
- Remaining 3 weeks at $0.12/query = $135+ overage = pure revenue
- This is what naturally pushes subscribers to Enterprise/Scale tiers

### Privacy Architecture:
- Tenant-specific knowledge cards (their customizations, their SDK, their config)
- No cross-tenant data leakage
- Dev team conversations private to their account
- Custom code stored in isolated deployment
- ANASTASiA sees ONLY what belongs to that tenant

### Why ANASTASiA Is the Only Qualified Architect:
- She compiled the knowledge cards that power the system
- She designed the booking pipeline
- She wrote the credential router
- External AI needs the entire codebase fed each session — she has persistent context
- External AI doesn't know the ANASTASiA SDK internals, credential routing protocol, or knowledge card format

### Custom SDK Audit + Deploy Pipeline:
```
Developer writes module (or asks ANASTASiA to build it)
    ↓
ANASTASiA Code Review
    - Security scan (injection, credential exposure, PII)
    - API compatibility (correct use of internal APIs)
    - Performance audit (won't slow booking pipeline)
    - Dependency check (no unapproved external libs)
    ↓
Sandbox Test Deploy
    - Module runs in sandbox environment
    - Verifies no existing route breakage
    - Tests with mock bookings
    ↓
Production Deploy
    - Deployed to live instance
    - 24h error monitoring
    - Auto-rollback if error rate spikes
    ↓
Optional: Marketplace Publish
    - ANASTASiA generates documentation
    - Module available for other APAi subscribers
```

---

## 17. UPDATED SEGMENT BUILD PLAN (with Terminal additions)

**Segment 1 — MYSTES P0 Deploy Fixes** ✅ COMPLETE
- requirements.txt, Dockerfile, BookingWorker gate, env vars, duplicate route, migration chain

**Segment 2 — Network Profile System (APAi SDK backend)**
- ProviderProfile, RoutingTerms, NetworkConnection models
- API endpoints: directory, profile CRUD, connect/disconnect, terms
- Query cost accounting in credential router
- Transaction audit trail logging
- Terminal session model (conversation context per developer per tenant)
- Per-developer query tracking
- Custom module storage + audit trail

**Segment 3 — Network UI + Terminal (APAi dashboard)**
- My Network page (active connections, directory, pending)
- Provider profile cards with credential listings
- Terms card editor (sliders, dropdowns, publish flow)
- Connection request/accept flow
- Revenue analytics (tier-gated)
- ANASTASiA Terminal panel in admin dashboard
- Deploy status + history view
- Team query usage breakdown

**Segment 4 — apai.co Website Refresh**
- New credential network section
- New integration options section
- Updated pricing with feature comparison table
- "Built-In AI Architect" section with terminal demo
- "Your dev team's best hire costs $0.05/query" pitch
- Custom SDK development flow diagram
- Credential cost calculator widget

**Segment 5 — Tier Feature Gating**
- Vault limits (3/10/unlimited), team seats (1/5/unlimited)
- Analytics depth gating (basic/full/intelligence)
- Webhook system (Enterprise+), white-label (Enterprise+)
- Network intelligence feed (Scale), failure recovery (Scale)
- "Taste" strategy (greyed-out previews)
- Custom SDK audit+deploy pipeline (Enterprise/Scale gate)

**Segment 6 — Commit + Deploy**
- Commit all files
- Deploy MYSTES to mystes.app
- Deploy APAi to apai.co
