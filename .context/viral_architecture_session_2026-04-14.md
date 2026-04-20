# Viral Architecture Session — SIM Farm Operations + Infrastructure
**Date**: 2026-04-14
**Status**: STRATEGIC DECISIONS LOCKED — Ready for implementation
**Builds discussed**: None started — architecture planning only. No code changes.

---

## SESSION CONTEXT

Continuation of strategy session (2026-04-08 through 2026-04-14). This session covered:
1. Operational architecture for SIM farm + proxy search pipeline
2. Fraud/security model under "clean hands" (airline = MoR)
3. Bot protection and access gating
4. US-first geo-targeting strategy
5. SIM farm capacity math
6. Viral traffic infrastructure planning

All decisions below are user-approved strategic direction. Implementation builds TBD.

---

## DECISIONS LOCKED (2026-04-14)

### 1. Search/Booking Separation
- **SEARCH** = residential proxy (Webshare.io or Soax/IPRoyal). High volume, low stakes.
- **BOOKING** = SIM farm (real mobile devices). Low volume, high stakes.
- SIMs are NEVER used for search. Proxy is NEVER used for booking.
- Existing `google_flights_scraper.py` (671 LOC) + `proxy_manager.py` (145 LOC) = search engine. Already built.
- Existing `airline_booker.py` (1,106 LOC) = booking engine. Already built. Needs customer card swap.

### 2. SerpAPI Status
- **CONFIRMED DEAD for POS pricing** (live tested 2026-04-14): `gl=dk` returns IDENTICAL prices to `gl=us`. Google determines POS from requester IP, not URL parameter. SerpAPI servers are in US → always US prices.
- **RETAINED for US baseline pricing**: SerpAPI returns real US retail prices. This is the CEILING for spread calculation.
- SerpAPI key: in `.env` as `SERPAPI_KEY`

### 3. Stripe Issuing Virtual Cards = ELIMINATED
- Customer's real card entered at booking time
- ANASTASiA/airline_booker fills airline checkout with customer's card
- Airline is merchant of record — charges customer directly
- KYRIOS charges separate service fee via Stripe
- Saves: $20+/booking Stripe Issuing fee, $100K+/day cash float, faster SIM sessions
- `airline_booker.py` needs update: accept customer `PaymentInfo` at booking time instead of `PLATFORM_CARD_*` env vars
- PCI: SAQ C-VT level. Card data transient — encrypt at collection, decrypt during SIM session, wipe after. Never stored.

### 4. Fraud Detection = Mostly Not Our Problem
- **Ticket transaction**: Airline handles all fraud (3D Secure, AVS, velocity checks, chargebacks). Not MoR = not our liability.
- **Service fee**: Stripe Radar handles fraud detection. Our exposure = fee amount only (not ticket price).
- **Platform abuse**: Rate limiting + email verification. See bot protection below.
- **What we DON'T need**: PCI DSS Level 1, chargeback management, card verification, fraud scoring engine, refund processing for tickets, seller-of-travel license, IATA accreditation, money transmission license.

### 5. Bot Protection — Progressive Friction Model
- **NO mandatory accounts. NO KYC. Guest checkout preserved.**
- **Tier 0 — Browsing cached prices**: Zero friction. Free marketing. Cloudflare handles DDoS.
- **Tier 1 — Live search (proxy query)**: Email verification required. Enter email → 6-digit code → verify. Auto-creates lightweight account. Rate limited per verified email (X searches/day). Block disposable email domains (30K+ domain blocklist).
- **Tier 2 — Booking (SIM session)**: Email already verified + card details (natural friction). Optional SMS verification for additional security.
- Email verification is the SWEET SPOT: low friction for humans (30 sec), expensive for bots (need real email accounts at scale), creates persistent identity for rate limiting.

### 6. US-First Geo-Targeting (NOT Geo-Blocking)
- **DO NOT BLOCK non-US traffic.** Serve them standard Duffel/Picasso prices (zero SIM cost). Still revenue.
- **US IP → SIM-arbitraged pricing pipeline**: proxy scraper (DK POS) + SerpAPI (US baseline) → spread calculation → fee tier → display price.
- **Non-US IP → standard API pricing pipeline**: Duffel + Picasso only. No SIM queries burned.
- Phase 1: US customers only, single foreign POS (DK or DE)
- Phase 2: Expand foreign POS sources (DE, NL, SE, PL — test which is cheapest per route)
- Phase 3: Expand customer markets (UK, AU, CA — each needs own baseline)
- Phase 4: Per-route POS optimization (ANASTASiA learns best POS per route)

### 7. Margin Maximization via Fee Tiers
- Fee is % of SPREAD (not ticket price). Source: `payments.py:get_fee_percent()`
- Spread = US retail (SerpAPI) - foreign POS price (proxy/SIM)
- Customer pays: foreign POS price + (spread × fee %)
- Guest 50% of spread, Free 45%, Travel+ 35%, B2B Starter 25%, Growth 20%, Volume 15%
- $3 minimum fee, NO MAXIMUM CAP
- At Guest 50%: customer saves half the spread, KYRIOS keeps half. Both sides are happy.
- "Shock the market" = 15-25% below Google. Viral threshold.
- MYSTES ALWAYS wins on price vs APAi OTAs: KYRIOS charges itself $0 for SIM routing. Structural, permanent.

### 8. SIM Farm Capacity Math (Booking Only — Search on Proxy)
- Booking session: ~1-3 min average (navigate, fill passenger, fill card, confirm)
- Conservative 3 min/booking: 20 bookings/hour/SIM
- **10 SIMs** = 240 bookings/day (launch)
- **25 SIMs** = 600 bookings/day (traction)
- **50 SIMs** = 1,200 bookings/day (growth)
- **100 SIMs** = 2,400 bookings/day (scale)
- **200 SIMs** = 4,800 bookings/day (expand)
- 2,500 bookings/day needs each SIM to do only 25 bookings/day (one per 30 min over 12 hrs). SIMs are 96% idle.
- Scale SIMs with demand — never pay for idle capacity.

### 9. Viral Traffic Infrastructure
**Four critical components (must have before launch):**

#### A. Cloudflare CDN ($0-25/mo)
- Absorbs 90% of traffic at edge
- Static assets cached (HTML, CSS, JS, images)
- DDoS protection (free tier handles basic, Pro for advanced)
- "Under Attack" mode toggle during spikes
- Setup: 1 hour (DNS change + page rules)

#### B. Redis Cache Layer ($10-30/mo)
- Pre-warm top 200 US routes every 15-30 min via proxy scraper (background cron)
- Cache key: `{origin}:{dest}:{date}:{class}` → JSON with prices + TTL
- Cache hit = 1ms Redis lookup, zero proxy/SIM cost
- Cache miss = enqueue proxy search job, show "searching..." loading state
- Handles 100K+ reads/second

#### C. Async Search Queue (RQ or Celery + Redis broker)
- **CRITICAL**: Current `search_global()` is synchronous — blocks Flask thread. WILL crash under load.
- Fix: `POST /api/search` returns `{job_id}` immediately. Frontend polls `GET /api/search/{job_id}` for results.
- Dedup: same route searched by 50 people simultaneously → ONE proxy query, serve result to all 50.
- Rate governor: max N concurrent proxy sessions.
- Background workers on Render process search jobs.

#### D. Booking Queue + SIM Pool Manager
- Customer clicks "Book" → email verified → card collected → job enters booking queue
- SIM pool manager tracks idle/busy/cooldown per SIM
- If all SIMs busy: "Your booking is in queue, estimated wait: 2 minutes" (NOT an error)
- Priority: Travel+ subscribers > Free > Guest
- Success → capture Stripe hold → send confirmation email
- Failure → retry on different SIM → if still fails → release Stripe hold → notify customer
- Timeout: if SIM takes > 5 min, reassign to fresh SIM

### 10. Infrastructure Stack (Pre-Launch)

| Component | Service | Cost | Handles |
|-----------|---------|------|---------|
| CDN + DDoS | Cloudflare Pro | $25/mo | 10M+ page views |
| Web server | Render Standard (2+ instances) | $50/mo | 50K+ requests/day |
| Cache | Redis (Render or Upstash) | $10-30/mo | 100K+ price lookups |
| Job queue | RQ + Redis broker | $0 (same Redis) | 20K searches + 2.5K bookings |
| Background workers | Render Workers (2-3) | $21-42/mo | Proxy scrapes + booking jobs |
| Database | PostgreSQL (Render) | $7-20/mo | Writes + audit trail |
| Email | SendGrid | $0-20/mo | Verification codes |
| Proxy | Webshare/Soax | $100-300/mo | Price scraping |
| SIM farm | CitizenSerp | TBD | Booking execution |
| **Total (before SIMs)** | | **~$200-500/mo** | |

---

## EXISTING CODE ASSETS (Already Built)

| File | LOC | Role in New Architecture |
|------|-----|--------------------------|
| `google_flights_scraper.py` | 671 | SEARCH: Multi-market Google Flights scraper with proxy. 17 markets, DOM extraction, parallel scraping. |
| `proxy_manager.py` | 145 | SEARCH: Webshare.io integration, 17 markets, per-country proxy routing. |
| `airline_booker.py` | 1,106 | BOOKING: Playwright booking automation, 12 airline handlers, passenger/payment filling. Needs customer card swap. |
| `citizenserp/helper_client.py` | 150+ | BOOKING: WebSocket remote browser control for SIM farm nodes. |
| `search.py:search_global()` | — | Entry point for consumer search. Needs async conversion. |
| `payments.py:get_fee_percent()` | — | Fee tier calculation. Works as-is. |

---

## CODE CHANGES NEEDED (Pre-Launch)

### Must Have (viral survival):
1. **Redis cache layer** — new module. Cache warmer cron + cache-first search.
2. **Async search** — refactor `search_global()` to return job ID, add polling endpoint.
3. **Booking queue** — new module. SIM pool manager + booking job processor.
4. **Email verification gate** — new endpoint. 6-digit code, disposable domain blocklist.
5. **GeoIP routing** — middleware. US IP → SIM pipeline, non-US → API pipeline.

### Should Have (margin optimization):
6. **Spread calculator** — new module. SerpAPI US baseline + proxy foreign price → fee calculation.
7. **`airline_booker.py` card swap** — accept customer PaymentInfo instead of PLATFORM_CARD env vars.
8. **Customer card collection UI** — secure form at booking time. Encrypt on collection, wipe after use.

### Nice to Have (quality of life):
9. **Booking status page** — real-time "your booking is being processed" with progress stages.
10. **Cache warming dashboard** — monitor cache hit rates, staleness, popular routes.

---

## VIRAL TIMELINE

### Pre-Launch Checklist:
- [ ] Cloudflare in front of everything
- [ ] Redis cache + top 200 route warming
- [ ] Async search (job queue + polling)
- [ ] Email verification gate
- [ ] Booking queue + SIM pool manager
- [ ] PostgreSQL confirmed as production backend
- [ ] GeoIP routing (US → SIM, non-US → API)
- [ ] 10 SIMs deployed + 15 staged for rapid deployment
- [ ] Spread calculator (SerpAPI ceiling + proxy cost basis)
- [ ] Customer card collection (replace platform card)
- [ ] SendGrid email service for verification codes

### During Viral Spike:
- Cloudflare absorbs 90% at edge
- Redis serves 80% of searches from cache
- Proxy workers handle 20% cache misses async
- SIM pool processes bookings in queue order
- If overwhelmed: increase cache TTL from 20→60 min (staler but alive)

### Emergency Scaling:
- Render auto-scale adds web instances
- Add proxy workers (one click)
- Deploy staged SIMs
- If STILL overwhelmed: temporarily pause non-US traffic (serve "coming soon to your region")

---

## ARCHITECTURE PIVOT (2026-04-14, later in session)

### Physical SIM Farm → Bright Data Residential Proxy
- **SIM farm DEFERRED** — not eliminated, deferred to Phase 3 cost optimization
- **Bright Data residential proxy** replaces BOTH Webshare (search) AND SIM farm (booking)
- Mobile proxies sunset by Bright Data (new customers can't get them) — residential is the product
- **Key insight**: POS pricing is based on IP GEOLOCATION, not IP TYPE. Danish residential IP triggers same DK POS pricing as Danish mobile IP.
- Scraping Browser product: hosted headless Chrome via CDP, auto CAPTCHA solving, fingerprint randomization, sticky sessions (entire browser lifetime)
- Playwright integration: native CDP connect — `airline_booker.py` plugs right in
- **Pricing**: PAYG $4/GB (promo), Enterprise $2.50/GB (promo). Promo lasts 3 months.
- **Full economics**: See `.context/launch_economics_2026-04-14.md`

### Cost Comparison
| | Physical SIM Farm | Bright Data Proxy |
|---|---|---|
| Setup cost | $5,000+ (hardware, SIMs, colo) | $0 (API key) |
| Per-search cost | $0.01 | $0.013 |
| Per-booking cost | $0.05 | $0.05 |
| Scaling speed | Days (buy SIMs, deploy) | Instant (spend more) |
| Month 1 total cost | ~$3,000+ | ~$200-500 |
| Maintenance | Hardware, SIM rotation, failures | Zero |

### When to Build Physical SIM Farm
- Phase 3 cost optimization: when proxy costs exceed 10% of revenue
- At current projections (3.1% of revenue), not needed
- Physical farm reduces per-booking proxy cost from $0.05 to $0.005 — irrelevant until 10K+ bookings/day

## OPEN ITEMS (revised)

1. ~~Residential proxy validation~~ → **VALIDATE WITH BRIGHT DATA** — sign up PAYG, test DK residential IP on Google Flights. Budget: $20.
2. **Which foreign POS market is optimal** — DK vs DE vs NL vs PL? Test via Bright Data multi-country targeting.
3. ~~SIM farm hardware/hosting~~ → **DEFERRED to Phase 3.**
4. **3D Secure handling** — stream challenge back to customer in MYSTES UI when triggered by airline checkout.
5. **Per-route POS optimization** — Phase 4 item. ANASTASiA learns cheapest POS per route over time.
6. ~~Larger SIM farm scaling~~ → **SOLVED by proxy model. Infinite scaling via spend.**

---

## STILL TBD (carried forward from 2026-04-08 session)

1. **SIM arbitrage percentage for APAi** — what % of arbitrage does KYRIOS take from APAi OTAs?
2. **Duffel passthrough cost model** — opaque or passed through?
3. **Peer-to-peer split defaults** — 70/30 template or fully negotiated?
4. **Build #203 scope** — revenue.py rewrite blocked until APAi routing model locked.

---

## KEY QUOTES (user, this session)

- "if we are merely a tool for routing and not the merchant of record, then do we need to worry about fraud detection and such?" → Led to fraud model simplification.
- "what stops scrapers from creating multiple browser sessions to keep searching?" → Led to email verification gate decision.
- "i want to start by providing the us pos customers the lowest fares in the us" → Led to US-first geo-targeting strategy.
- "i want to maximize our profits" → Led to margin optimization discussion.
- "if we are undercutting the lowest google price we absolutely will be blowing up viral overnight" → Led to viral infrastructure planning.
- "we also already built a proxy scraper for google flights in playwright" → Discovered existing 1,900+ LOC scraping stack.
