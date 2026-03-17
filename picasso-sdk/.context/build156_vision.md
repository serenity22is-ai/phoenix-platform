# Build #156 — Business Architecture Vision (2026-03-10)

## THE PYRAMID — Complete Revenue Model

```
                        ▲
                       /E\         ENTERPRISE ($799/mo)
                      /   \        High volume, bulk provisioning, dedicated credentials
                     /─────\
                    / PRO   \      PRO ($299/mo)
                   /         \     Own credentials (100%), dev terminal, modules
                  /───────────\
                 / STARTER     \   STARTER ($99/mo)
                /               \  Turnkey template, credential portal, own brand
               /─────────────────\
              / MYSTES B2B        \  B2B ($49/mo or volume threshold)
             /                     \ Use MYSTES directly, B2B rates, our credentials
            /───────────────────────\
           / MYSTES CONSUMER         \  FREE (no subscription)
          /                           \ Browse, book at consumer rates, highest markup
         /─────────────────────────────\
```

## Key Decisions (DO NOT REVERSE)

### Revenue Channels
1. **MYSTES B2C** — consumer bookings, highest markup (35-50% of savings)
2. **MYSTES B2B** — agencies use MYSTES directly, B2B rates, $49/mo or volume threshold
3. **ANASTASiA SaaS** — Starter/Pro/Enterprise platform subscriptions

### Credential Network
- ALL purchases route through MYSTES KYRIOS — customers never interact directly
- Own credentials = 100% of booking margin, subscription only revenue for us
- Our credentials = we take margin on fare spread
- Cross-network credentials = routing fee when booking through another member's credentials
- Credential providers earn per-booking fee for shared credential usage

### Template Architecture
- MYSTES IS the template — one codebase, configurable
- Consumer view = search + book (same for everyone)
- Admin view = pricing rules + credentials + analytics + branding
- No separate agent desktop, B2B interface, or D2C template — ONE template
- Template works anywhere: cloud (Render), local terminal, laptop, kiosk

### Search Tools (Zero AI Cost)
- Traditional form-based search per vertical (dropdowns, date pickers)
- Unified search form: shared fields (destination, dates, passengers) fan out to all verticals
- Staged selection: flights → hotels → cars → activities → bundle
- Bundle builder: combine selections + customer markup rules = vacation package
- ALL search/browse/book flows are deterministic — zero AI tokens

### AI Architecture
- AI is the EXCEPTION HANDLER, not the standard path
- 99% of interactions: form → API call → result cards (zero AI cost)
- AI activates ONLY when: programmatic paths fail, consumer opens chat, complex rebooking
- Suite COGS drops from ~$40/month to ~$3-5/month per customer

### Pricing Tiers (Revised from Build #155)
| Tier | Price | Key Features | Dev AI | Suite AI |
|------|-------|-------------|--------|----------|
| Free | $0 | API sandbox, 500 calls/mo | 0 | 100 |
| Starter | $99 | Template, credential portal, all verticals | 0 | 500 |
| Pro | $299 | Dev terminal, own credentials, modules | 2,000 | 2,000 |
| Enterprise | $799 | Bulk provisioning, dedicated credentials | 5,000 | 5,000 |

### B2B MYSTES Channel
- $49/month subscription OR meet volume threshold (30+ bookings/month)
- B2B rates (15-25% of savings vs 35-50% consumer)
- Business account dashboard (booking history, client management)
- THIS IS THE SANDBOX — agencies experience full technology before ANASTASiA commitment
- Natural graduation: "I want better rates and my own brand" → ANASTASiA Starter

### MYSTES B2B as Sandbox
- Zero friction trial for ANASTASiA
- No API keys, no deployment, no configuration
- Just sign up and start booking at B2B rates
- Every booking during evaluation earns us revenue
- Graduation path: B2B → Starter → Pro → Enterprise

### Deployment Models (Same Product)
- Cloud (Render, AWS) — consumer OTA
- Local terminal (localhost:5001) — travel agency desk
- Hybrid (local + cloud) — both channels
- API-only (headless) — custom frontend

### Markup By Level
| Level | Markup | Revenue Source |
|-------|--------|---------------|
| Consumer | 35-50% of savings | Per-booking margin |
| B2B | 15-25% of savings | Per-booking + optional sub |
| Starter | Credential routing fee | Subscription + routing |
| Pro | 0% own / routing on network | Subscription + network fees |
| Enterprise | 0% + volume discounts | Subscription + volume |

### Routing Fees & Three-Way Split
- **Pro**: 5% routing fee on every routed transaction
- **Enterprise**: 3% routing fee on every routed transaction
- Own credentials = 0% routing fee (subscription only)
- Our fee comes off the TOP, then: 70% Client Provisionary / 30% Portal Host
- Example ($1K ticket, $200 savings, Pro): $10 us, $133 client, $57 portal host

### Credential Operational Control
- ANASTASiA has FULL operational control over all network credentials
- Portal Hosts lend API access — they do NOT operate bookings
- ANASTASiA books, records issue prices, handles refund chains
- Single source of truth for issue prices — no discrepancy risk
- Automated settlement: ANASTASiA settles with Portal Host at issue price
- Refund chain: consumer → us → Portal Host API → refund back through us
- Portal Hosts never see consumer identity or final sale price

## Sandbox Economics (DO NOT REVERSE)
- **Full suite access in sandbox** — every feature, every service, pay-per-query
- Template preview + branding config = free (zero AI cost)
- Past free limits: $0.02/API, $0.10/suite AI, $0.15/dev AI, $0.25/credential query
- Bookings at B2C consumer rates (35-50% of savings)
- Sandbox is INDEFINITE — no time limit, no feature gate, only price gate
- Economics force graduation: Starter ($99) < sandbox cost at any real volume

## Implementation Status (Build #156-157)
1. ~~Revised SaaS tier structure~~ — DONE (`saas/__init__.py` updated)
2. ~~Billing plan pricing~~ — DONE (`billing.py` updated with Starter, routing fees, split calc)
3. ~~Sandbox pay-per-query rates~~ — DONE (`billing.py` SANDBOX_OVERAGE_RATES)
4. ~~Sandbox full suite access~~ — DONE (`saas/__init__.py` free tier enabled)
5. B2B account type on MYSTES — PENDING (needs MYSTES server.py changes)
6. ~~Unified search dispatcher~~ — DONE (`anastasia/search/__init__.py`, Build #157)
7. ~~Bundle engine~~ — DONE (`anastasia/bundles/__init__.py`, Build #157)
8. ~~Credential routing engine~~ — DONE (`anastasia/credentials/network.py` expanded, Build #157)
9. ~~Pricing rule engine~~ — DONE (`anastasia/bundles/` TIER_PRICING_RULES + existing `pricing.py`)

## Files Modified (Build #157 — 2026-03-10)
- `anastasia/credentials/network.py` — Tiered fallback chain, RoutingStrategy/RoutingTier enums, recency-weighted scoring, retry_routing(), tier-aware revenue splits aligned with billing.py
- `anastasia/credentials/__init__.py` — Export new types (RoutingStrategy, RoutingTier, get_tier_revenue_split)
- `anastasia/search/__init__.py` — NEW: SearchDispatcher (parallel fan-out), SearchRequest/SearchResponse, SearchModule (18th neuron)
- `anastasia/bundles/__init__.py` — NEW: BundleBuilder, BundleItem, PricingRules, TIER_PRICING_RULES, Bundle
- `anastasia/platform.py` — Registered search neuron (18 neurons total)
- `picasso/agent/search_routes.py` — NEW: 8 API endpoints (unified search + bundle CRUD)
- `picasso/agent/api.py` — Wired search_routes registration
- `tests/test_credential_network.py` — Updated revenue split assertions for pyramid model
- `tests/test_neuron_network.py` — Updated neuron count assertions (17→18)

## Revenue Split Alignment (Build #157)
- OLD: DEFAULT_REVENUE_SPLIT = {owner: 85%, platform: 10%, router: 5%}
- NEW: get_tier_revenue_split("pro") = {platform: 5%, router: 66.5%, owner: 28.5%}
- Aligned with billing.py: 5% Pro / 3% Enterprise routing fee, then 70/30 split
- owner = Portal Host (credential provider), router = Client Provisionary (agency bringing sale)

## Files Still Needed
- `models.py` — B2B account type, bundle model
- `server.py` — B2B login, business account dashboard
