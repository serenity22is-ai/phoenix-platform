# PHOENIX PLATFORM — STRUCTURAL REFERENCE v2

**Last Updated:** 2026-02-05
**Purpose:** Concise reference for session continuity. Read this FIRST before making changes.
**Note:** This supersedes previous model docs. Old files kept for reference if needed.

---

## WHAT PHOENIX IS

A universal arbitrage search engine. Flights are vertical #1. Expands to hotels, cruises, e-commerce, software — any good/service with geographic pricing differences. Same search bar, same node network, different scraping targets per vertical.

**Phoenix is NOT a flight app.** Flights are the entry point. The platform becomes infrastructure for all arbitrage discovery.

---

## THE CORE ARBITRAGE (Phase 1)

**Amadeus wholesale pricing vs Google consumer pricing.**

- Amadeus (GDS) returns wholesale flight prices — single API call
- Google Flights is where consumers compare prices
- The arbitrage = Amadeus price is lower than what Google shows consumers
- **No proxy network needed for this to work**
- **No multi-market searches needed**
- Phoenix books via Amadeus, user saves money, Phoenix takes a cut

**Example:**
- Amadeus prices flight at $600
- Google shows consumers $750
- User saves $150
- Phoenix takes 25% ($37.50)
- User keeps $112.50

**Amadeus Regional Arbitrage (To Be Tested):**
- Amadeus MAY return different prices based on point-of-sale or geographic query origin
- This needs testing via paid proxy portals against Amadeus LIVE pricing
- If confirmed → save for Phase 2 rollout via CitizenSERP node network
- If not → doesn't matter, wholesale vs consumer arbitrage still works

---

## PHASE SYSTEM

### Phase 1 — Bootstrap (CURRENT)

**Product:** Travel search app offering wholesale flight pricing via Amadeus.

**Arbitrage Model:**
- Amadeus wholesale price < Google consumer price = arbitrage window
- Phoenix takes 25% of savings (or less based on tier)
- User keeps the rest

**Tier System:**
- Users get better tiers by running nodes
- Better tier = Phoenix takes smaller cut = user keeps more savings
- Tier rewards are arbitrage discounts, NOT cash payments

**Node Network:**
- Builds in background
- NOT monetized yet
- Users run nodes to get better tier benefits
- No proxy sales, no direct payments to nodes

**Testing:**
- Test Amadeus live pricing to confirm arbitrage exists
- Test Amadeus regional pricing via PAID proxies (Webshare etc.)
- If regional arbitrage exists → document for Phase 2

**Costs:**
- Amadeus API charges per search
- Booking fees (% of savings) must cover search costs
- Conversion rate matters (searches vs bookings)

**User-Facing:**
- Clean travel search UI
- No nodes/network/credits/payouts visible
- Tier benefits framed as "get better rates"

### Phase 2 — Commercially Viable (500 nodes)

**Trigger:** 500 registered nodes, 15+ zones, 12+ countries

**Proxy Sales Begin:**
- Sell residential proxy bandwidth per GB to external customers
- Target: SEO agencies, price comparison services, ad verification, market research
- Revenue distributed directly to ALL nodes based on usage/uptime

**Pricing Strategy:**
- Competitive pricing — do NOT dramatically undercut market
- Stay competitive to win business without drawing attention
- Quiet market entry
- Maximize margin flowing to node operators
- Happy nodes → network grows → more capacity → more sales

**Amadeus Regional Arbitrage (if confirmed in Phase 1 testing):**
- Roll into arbitrage model
- Node network routes Amadeus queries through residential IPs
- Phoenix finds cheapest regional price
- Phoenix ALWAYS handles the booking — user never interacts with nodes

**Node Role:**
- Provide residential IP as proxy endpoint
- That's it
- Nodes do NOT make purchases
- Nodes do NOT interact with users
- Nodes do NOT handle bookings

**Two Income Streams for Nodes:**
1. Direct payments from proxy sales per GB
2. Future: CitizenSERP micropayments from data product revenue

### Phase 3 — Defensible (2000+ nodes)

**Trigger:** 2000+ nodes, 25+ zones, 20+ countries

**Market Position:**
- Market velocity achieved
- When competitors try to race to bottom on pricing, Phoenix wins
- Traditional proxy providers have fixed cost floor (infrastructure, IP leases, bandwidth)
- Phoenix cost basis is near-zero (infrastructure = users' devices)
- Phoenix can pay nodes MORE while charging customers LESS than competitors can break even

**Data Products Layer On:**
- Airline Intelligence SaaS: $100K-500K/mo per airline
- Competitive pricing intelligence
- Ancillary optimization data (bags, seats, meals by geography)
- Route-level market positioning
- Commercial Intelligence API

**Multi-Vertical Expansion:**
- Hotels → Cruises → E-Commerce → Software → Universal search
- Same search bar, same node network
- Different scraping targets and fulfillment per vertical
- Each vertical adds data subscribers without proportional node growth

**Endgame:**
- Phoenix becomes infrastructure — immovable part of data industry
- Structural cost advantage cannot be replicated
- Incumbents either adapt (wrong cost structure, they can't) or die
- "A new king"

---

## TIER SYSTEM (User-Facing)

Tiers determine Phoenix's cut of arbitrage savings. Better tier = user keeps more.

| Tier | Phoenix Takes | User Keeps | How to Achieve |
|------|---------------|------------|----------------|
| Bronze | 25% | 75% | Sign up (free) |
| Silver | ~20% | ~80% | Run a node |
| Gold | ~15% | ~85% | Node + data sharing |
| Platinum | ~10% | ~90% | High uptime node |

**Key Points:**
- Tier rewards are ARBITRAGE DISCOUNTS, not cash
- Users run nodes to get better deals on the platform
- Direct node payments come in Phase 2 from proxy sales
- This is the onboarding model — tier exclusivity incentivizes node operation

**Queries/Markets per Tier (TBD):**
- Bronze: 3 searches/day, 2 markets
- Silver: More queries, more markets
- Gold: Even more
- Platinum: Unlimited / priority

---

## NODE OPERATOR MODEL

### Phase 1 (Now)
- Running a node = better tier = smaller Phoenix cut on your bookings
- No direct payments
- Nodes build the network for Phase 2

### Phase 2+ (500 nodes)
**What nodes do:**
- Provide residential IP as proxy endpoint
- That's it

**What nodes DON'T do:**
- Make purchases for users
- Interact with users
- Handle bookings
- Make decisions

**Payment Flow:**
1. Phoenix sells proxy bandwidth per GB to external customers
2. Revenue distributed directly to all nodes
3. Based on usage/uptime
4. Competitive pricing → more margin to nodes → happy nodes → network grows

**The Structural Moat:**
- Traditional proxy providers: Pay for data centers, IP leases, bandwidth. High fixed cost floor.
- Phoenix: Infrastructure is users' devices. Cost basis near-zero.
- Phoenix can ALWAYS undercut competitors while paying nodes more
- Race to bottom = Phoenix wins, competitors bleed

---

## REVENUE MODEL

### Consumer Revenue
- 25% of realized savings (reduced by tier)
- Only charged on completed bookings
- Searches are free (within tier limits)
- Must cover Amadeus API costs
- Conversion rate critical: if 1 in 20 searches books, booking fee covers 20 searches

### Commercial API Revenue (Phase 2+)
- Agencies/OTAs access Phoenix arbitrage via API
- Fee = % of savings, tier-based on volume:
  - Starter: 20% (0+ tickets/30d)
  - Professional: 15% (50+ tickets/30d)
  - Enterprise: 10% (500+ tickets/30d)
  - Partner: 7% (5000+ tickets/30d)
- Use-it-or-lose-it: Drop below tier threshold for 2 consecutive periods → downgrade

### Proxy Sales Revenue (Phase 2+)
- Sell residential proxy bandwidth per GB
- External customers: SEO agencies, price comparison, ad verification, market research
- Competitive pricing (don't undercut dramatically)
- Revenue pays nodes directly

### Airline SaaS Revenue (Phase 3)
- $100K-500K/mo per airline subscriber
- Competitive pricing intelligence
- Ancillary optimization data (bags, seats, meals by geography)
- Route-level market positioning
- Data-only product, NOT booking
- Creates strategic relationships + legal/regulatory cover

---

## THREE-SIDED MARKET

1. **Consumers** — Get wholesale pricing access, pay % of savings based on tier
2. **Agencies/Commercial** — API access to arbitrage engine, volume-based fee tiers
3. **Airlines** — SaaS intelligence product, $100K-500K/mo

**MAD (Mutually Assured Destruction) Position:**
- Airlines that subscribe get competitive data edge
- Airlines that don't subscribe get exposed — Phoenix offers their passengers better pricing through competitors
- Phoenix earns either way
- This hedges revenue across all scenarios

---

## P2P PURCHASING NETWORK (System 2)

**Status:** RESERVE — not primary model

**Purpose:** Fallback for when corporations block proxy-booked Amadeus tickets

**How it works:**
1. Helper in foreign market grants Phoenix browser control via client app (helper_client.py)
2. Phoenix automates purchase on helper's device via Playwright (browser_control.py)
3. Helper's device = real IP, real Google account, real browser fingerprint = undetectable
4. Buyer deposits RLUSD into XRPL escrow
5. Helper verifies escrow on-chain
6. Helper fronts purchase with their credit card
7. Booking confirmed → escrow releases RLUSD to helper (reimbursement + cut)

**Key Points:**
- No Phoenix seed capital needed — buyer's RLUSD locked before helper purchases
- Helper verifies on-chain — trustless
- Active helpers earn 10% of realized savings (15-20% during bootstrap)
- This is NOT the primary model
- Primary model: Phoenix books via Amadeus, no helper involvement
- System 2 only activates if primary path gets blocked

---

## CITIZENSERP

The decentralized residential proxy network. Infrastructure layer INSIDE Phoenix, not a separate product.

**What it is:**
- Network of user devices providing residential proxy access
- Powers all data products across all verticals
- Nodes get paid from proxy sales and data product revenue

**Milestones (from node_registry.py):**

| Milestone | Nodes | Zones | Countries | Trigger |
|-----------|-------|-------|-----------|---------|
| Pilot Ready | 100 | 10 | 8 | Internal testing |
| Commercially Viable | 500 | 15 | 12 | Phase 2 auto-flip |
| Defensible | 2000 | 25 | 20 | Enterprise ready |

**Data Products (Phase 3):**
- Proxy bandwidth sales per GB
- Airline intelligence SaaS
- Multi-vertical market data (hotels, products, etc.)
- Commercial intelligence API
- "Citizen API" — people-powered honest market data layer

**The Flywheel:**
More nodes → better coverage → more data → better products → more revenue → higher node payouts → more nodes join

---

## TECHNICAL ARCHITECTURE

### Data Sources
| Source | Purpose |
|--------|---------|
| Amadeus API | Flight details, booking, wholesale pricing (GDS) |
| Residential proxies | Geo-specific price discovery (paid now, CitizenSERP Phase 2+) |
| Google Flights scraping | Consumer price benchmarks via Playwright |

### Search Priority Chain
```
1. Amadeus + Proxy → search_amadeus_with_proxy_prices()
2. Proxy-only (if no Amadeus) → search_proxy_only()
3. Error with config guidance (NO silent fallback)
```

### Key Files
| File | Purpose |
|------|---------|
| server.py (~19000 lines) | Flask app, all routes, inline HTML templates |
| amadeus_client.py | Amadeus API client |
| google_flights_scraper.py | Playwright + proxy Google Flights scraper |
| node_service.py | Desktop node daemon (port 19750) |
| node_registry.py | Node registration, discovery, CitizenSERP milestones |
| citizenserp_payouts.py | Node payout infrastructure |
| citizenserp_tasks.py | Typed task dispatch system |
| phoenix_agent.py | AI orchestration layer |
| phoenix_intelligence.py | Data-aware AI context building |
| vertical_pipelines.py | Multi-vertical processing (flights, hotels, products) |
| browser_control.py | WebSocket remote browser control (System 2) |
| helper_client.py | Helper CLI app (System 2) |
| p2p_orchestrator.py | P2P transaction workflow engine |
| geographic_zones.py | Sub-regional zone system (~75 zones, 45 countries) |
| commercial.py | Commercial account management |
| commercial_auth.py | Commercial API authentication |
| airline_intelligence.py | Airline SaaS data products |
| airline_auth.py | Airline API authentication |

### Deployment
| Component | Service |
|-----------|---------|
| Web | Render: srv-d61a6f24d50c739nvb40 |
| Database | Render PostgreSQL: dpg-d61a5ikhg0os73cht7j0-a |
| Redis | Render: red-d61a5r3uibrs73dgtb10 |
| URL | https://phoenix-web-nj67.onrender.com |
| Repo | https://github.com/serenity22is-ai/phoenix-platform (private) |

### Mobile
- Capacitor 6 (iOS + Android)
- WebView wrapping production URL
- Native apps installed on iPhone 16 Pro + Samsung Galaxy S24 Ultra

---

## USER INTERFACE STATE

### Visible to All Users (Phase 1)
- /ai — AI chat search
- /search — Flight search
- /deals — Deal listings
- /wallet — XRPL wallet management
- /dashboard — User dashboard
- /register, /login — Auth

### Hidden from Users (Admin-Only)
- /nodes, /install — Node dashboard
- /helper — Helper dashboard
- /earn — Earn page (node recruitment)
- /setup — Setup guides (node installation)
- /portal — Proxy portal
- /admin — Admin dashboard

### Navigation (Phase 1)
**Authenticated:** Chat, Flights, Deals, Wallet, More → [Dashboard, admin-only items]
**Unauthenticated:** Flights, Deals, Login, Get Started

---

## RENDER RESOURCES

| Resource | ID |
|----------|-----|
| Web Service | srv-d61a6f24d50c739nvb40 |
| PostgreSQL | dpg-d61a5ikhg0os73cht7j0-a |
| Redis | red-d61a5r3uibrs73dgtb10 |
| API Key | rnd_pKi2yjSs1whtfn2u0bgFtc9XweXm |
| Workspace | tea-d619u0p4tr6s73c5hlpg |

**Database:** phoenix_db_5717, user: phoenix
**Connection:** Internal with sslmode=disable

---

## AMADEUS CONFIGURATION

| Setting | Value |
|---------|-------|
| Environment | Test (switch to production for live pricing) |
| Endpoint | https://test.api.amadeus.com (test) / https://api.amadeus.com (prod) |
| Auth | OAuth2: /v1/security/oauth2/token |
| Flight Search | /v2/shopping/flight-offers |
| Booking | /v1/booking/flight-orders |
| Limit | 2,000 requests/month (free tier) |

**To test live pricing:** Set AMADEUS_ENV=production with production API credentials

---

## CRITICAL RULES

### DO
- Keep user UI clean for Phase 1 (travel search only)
- Test Amadeus live pricing before assuming arbitrage exists
- Build node network in background
- Stay competitive on proxy pricing (Phase 2)
- Maximize node payouts within competitive pricing
- Let tier discounts drive node adoption (Phase 1)

### DO NOT
- Expose node/network/credits/payout language to users in Phase 1
- Promise earnings before Phase 2 proxy sales exist
- Undercut proxy market dramatically (quiet entry)
- Frame Phoenix as adversarial to airlines
- Build features requiring node network before 500 nodes
- Forget: Amadeus wholesale vs Google consumer IS the Phase 1 arbitrage
- Use CitizenSERP for arbitrage before testing confirms regional pricing exists

---

## IMMEDIATE NEXT STEPS

1. **Amadeus Live Pricing Test**
   - Switch to production Amadeus credentials
   - Run searches and compare to Google consumer prices
   - Confirm arbitrage window exists and its typical size

2. **Amadeus Regional Pricing Test**
   - Use paid proxy portals (Webshare etc.)
   - Query Amadeus from different geographic IPs
   - Check if prices differ by origin
   - Document findings for Phase 2 decision

3. **Tier System Implementation**
   - Define exact query limits per tier
   - Define exact Phoenix cut per tier
   - Build tier upgrade logic (node detection)
   - Wire tier benefits into search/booking flow

---

## UPDATE LOG

| Date | Change |
|------|--------|
| 2026-02-05 | Initial v2 creation after full model clarification |

---

## SUMMARY

**Phase 1:** Amadeus wholesale arbitrage. Tier discounts (not payments) incentivize node operation. Build network quietly.

**Phase 2:** Proxy sales per GB. Direct node payments. Regional arbitrage if confirmed. Competitive pricing, quiet entry.

**Phase 3:** Market velocity. Win race to bottom. Data products. Multi-vertical. Become infrastructure.

**The moat:** Structural cost advantage. Users' devices = infrastructure. Near-zero cost basis. Can always undercut competitors while paying nodes more. Immovable.
