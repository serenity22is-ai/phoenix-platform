# MYSTES Pre-Launch Build Plan — 2 Weeks to Launch
**Created**: 2026-04-14
**Target Launch**: 2026-04-28
**Architecture**: Bright Data residential proxy (search + booking). No physical SIM farm.
**Economics**: See `.context/launch_economics_2026-04-14.md`

---

## EXISTING CODEBASE (What We're Building On)

| File | LOC | Status | Role |
|------|-----|--------|------|
| `search.py` | 2,290 | Working | Flight search orchestrator (Picasso, Duffel, Kiwi, AirGateway) |
| `google_flights_scraper.py` | 671 | Working | Playwright Google Flights scraper, multi-market |
| `airline_booker.py` | 1,106 | Working | Playwright airline checkout, 12 airline handlers |
| `proxy_manager.py` | 145 | Working | Webshare.io proxy routing, 17 markets |
| `payments.py` | 916 | Working | Fee tiers, Stripe, spread calculation |
| `server.py` | 21,394 | Working | All routes, booking flow, API endpoints |
| `models.py` | 4,000+ | Working | 75+ DB models including Deal, Booking |
| `citizenserp/` | 31,353 | Dormant | Full node network (Phase 2 rework) |

**Key Integration Points:**
- `search_global()` → SearchOrchestrator → multi-source parallel search → returns deals[]
- `/api/search` POST → calls search_global() → stores Deal records → returns JSON
- `/complete-booking/{deal_id}` POST → collects passenger data → calls book_flight_sync()
- `airline_booker.py` takes PaymentInfo dataclass (card details) — already accepts customer card
- `proxy_manager.py` → get_proxy_for_market(market) → returns {server, username, password}
- `get_fee_percent(user)` → 0.50/0.45/0.35/0.25/0.20/0.15 (sole source of truth)

---

## WEEK 1 (Apr 14-21): Foundation + Validation

### Build #204: Bright Data Proxy Integration
**Scope**: Swap Webshare for Bright Data in proxy_manager.py. Add Scraping Browser support.
**Files**: `proxy_manager.py`, `.env`
**Tasks**:
1. Add Bright Data credentials to `.env` (BRIGHTDATA_USERNAME, BRIGHTDATA_PASSWORD, BRIGHTDATA_HOST)
2. Update `get_proxy_for_market()` to use Bright Data residential proxy endpoint
3. Add `get_scraping_browser_url(market)` function for Playwright CDP connection (booking)
4. Add `PROXY_PROVIDER` env toggle: `webshare` (legacy) or `brightdata` (new)
5. Keep Webshare code as fallback (don't delete)
**Tests**: Proxy config returns valid Bright Data URL for each market
**Estimate**: 1-2 hours

### Build #205: Multi-POS Search Pipeline
**Scope**: Wire google_flights_scraper.py through Bright Data to query multiple POS markets per search.
**Files**: `google_flights_scraper.py`, `search.py`, new `pos_arbitrage.py`
**Tasks**:
1. Create `pos_arbitrage.py` — new module:
   - `get_cheapest_pos(origin, destination, date, markets=['DK','DE','NL','PL','SE'])` — queries Google Flights through multiple POS proxies in parallel, returns cheapest price + market
   - `get_us_baseline(origin, destination, date)` — calls SerpAPI for US retail price
   - `calculate_spread(us_price, foreign_price)` — returns spread amount
   - `calculate_service_fee(spread, user)` — calls get_fee_percent(), applies $3 minimum, returns fee
   - `get_customer_price(foreign_price, spread, user)` — foreign + fee = what customer pays
2. Update `google_flights_scraper.py`:
   - Use Bright Data proxy from `proxy_manager.get_proxy_for_market()`
   - Return structured price data with market identifier
3. Update `search.py:search_global()`:
   - For US IP requests: call pos_arbitrage pipeline FIRST, then fall back to Duffel/Picasso for non-arbitrage routes
   - For non-US IP requests: standard Duffel/Picasso only (no proxy cost)
   - Merge results: cheapest price wins regardless of source
4. Wire SerpAPI call for US baseline pricing
**Tests**: Multi-POS search returns prices from different markets, spread calculation correct
**Estimate**: 4-6 hours

### Build #206: Redis Cache Layer
**Scope**: Add Redis caching for flight search results. Cache-first search pattern.
**Files**: new `cache.py`, `search.py`, `server.py`
**Tasks**:
1. Create `cache.py`:
   - `get_cached_search(origin, dest, date, cabin)` → returns cached results or None
   - `set_cached_search(origin, dest, date, cabin, results, ttl=1200)` → stores results (20 min TTL)
   - `warm_popular_routes()` → background task to pre-warm top 200 US routes
   - Uses Redis (REDIS_URL env var, falls back to in-memory dict for dev)
2. Update `search.py:search_global()`:
   - Check cache FIRST before hitting proxies
   - Cache results after successful search
   - Return cache hit indicator in response (for monitoring)
3. Add cache warming cron to server startup (every 15-30 min)
4. Add `/api/admin/cache/stats` endpoint (hit rate, size, staleness)
**Tests**: Cache hit returns instantly, cache miss triggers search, TTL expiry works
**Estimate**: 3-4 hours

### Build #207: Async Search Queue
**Scope**: Convert synchronous search_global() to async job queue. Frontend polls for results.
**Files**: `server.py`, `search.py`, new `job_queue.py`
**Tasks**:
1. Create `job_queue.py`:
   - Uses RQ (Redis Queue) with Redis broker
   - `enqueue_search(params)` → returns job_id
   - `get_search_result(job_id)` → returns status + results
   - Search dedup: same route by multiple users → ONE search job, all get result
   - Rate governor: max N concurrent proxy sessions
2. Update `server.py`:
   - `POST /api/search` → returns `{job_id, status: "searching"}` immediately
   - `GET /api/search/{job_id}` → returns `{status: "searching"|"complete"|"failed", results: [...]}`
   - Keep synchronous path for cached results (no queue needed)
3. Update frontend JS to poll for results (loading spinner → results when ready)
4. Add RQ worker configuration for Render deployment
**Tests**: Job enqueue returns ID, polling returns results, dedup prevents duplicate searches
**Estimate**: 4-6 hours

### Build #208: Email Verification Gate
**Scope**: Require email verification before live search (proxy queries). Cached results = free.
**Files**: `server.py`, `models.py`, new `email_verification.py`
**Tasks**:
1. Create `email_verification.py`:
   - `send_verification_code(email)` → generates 6-digit code, sends via SendGrid, stores in Redis (5 min TTL)
   - `verify_code(email, code)` → returns True/False, auto-creates lightweight user account on success
   - `is_disposable_email(email)` → checks against 30K+ domain blocklist
   - Rate limit: 3 codes per email per hour, 10 per IP per hour
2. Add DB model: `EmailVerification(email, code, created_at, verified_at, ip_address)`
3. Update `server.py`:
   - `POST /api/verify/send` → sends code
   - `POST /api/verify/check` → verifies code, returns session token
   - `POST /api/search` → check: if cached result available, return immediately. If live search needed, require verified email.
4. Add disposable email domain blocklist (static file or package like `disposable-email-domains`)
5. Frontend: email input modal before live search, 6-digit code entry
**Tests**: Code generation, verification, disposable domain blocking, rate limiting
**Estimate**: 3-4 hours

### Validation Test (Do FIRST — before any builds)
**Scope**: Confirm Bright Data residential proxy triggers foreign POS pricing on Google Flights.
**Tasks**:
1. Sign up Bright Data PAYG (promo code RESIGB50)
2. Use curl or simple Playwright script to load Google Flights through DK residential IP
3. Search LAX-NRT (same route as Feb 24 data) — compare price to US Google Flights
4. If different: POS arbitrage confirmed. Proceed with all builds.
5. If same: test DE, NL, PL, SE. If none work: STOP. Re-evaluate.
6. Test Scraping Browser sticky session — connect Playwright via CDP, load airline site, confirm session holds
**Budget**: $20-50
**Estimate**: 1-2 hours

---

## WEEK 2 (Apr 21-28): Booking Pipeline + Launch

### Build #209: Booking Queue + Proxy Pool Manager
**Scope**: Queue-based booking with Bright Data Scraping Browser. Customer card → airline checkout.
**Files**: `server.py`, `airline_booker.py`, new `booking_queue.py`
**Tasks**:
1. Create `booking_queue.py`:
   - `enqueue_booking(deal_id, passenger_data, payment_info, user_id)` → returns booking_job_id
   - `process_booking_job(job)` → connects to Bright Data Scraping Browser, runs airline_booker
   - Pool manager: tracks active sessions, queue depth, estimated wait time
   - Priority: Travel+ > Free > Guest (queue ordering)
   - Retry: if booking fails, retry on different proxy IP (max 2 retries)
   - Timeout: 5 min per booking attempt
2. Update `airline_booker.py`:
   - Add `book_via_scraping_browser(deal_data, passenger_data, payment_info, market)` function
   - Connect Playwright to Bright Data CDP endpoint (sticky session for entire checkout)
   - Use market from POS arbitrage result (book through same POS that gave cheapest price)
3. Update `server.py`:
   - `/complete-booking/{deal_id}` → enqueue booking job instead of synchronous call
   - Return booking status page with real-time progress
   - `GET /api/booking/{booking_id}/status` → poll for booking progress
4. Frontend: booking progress page ("Searching for best price... Filling details... Processing payment... Confirmed!")
**Tests**: Booking enqueue, status polling, retry on failure, queue priority
**Estimate**: 6-8 hours

### Build #210: Customer Card Collection + Stripe Service Fee
**Scope**: Secure card form at booking time. Two charges: airline gets ticket price, KYRIOS gets service fee.
**Files**: `server.py`, `payments.py`, templates
**Tasks**:
1. Update booking flow:
   - After deal selection, show card collection form (Stripe Elements for PCI compliance)
   - Collect card details via Stripe.js (never touches our server — tokenized)
   - Create Stripe PaymentIntent for service fee ONLY (not ticket price)
   - Place hold on service fee (capture after booking confirmed)
2. Pass card token to airline_booker via secure channel:
   - Stripe token → decrypt card details server-side (Stripe API)
   - Pass to Playwright session → fill airline checkout form
   - Wipe card data from memory after booking completes
3. On booking success:
   - Capture Stripe hold (service fee)
   - Send confirmation email
4. On booking failure:
   - Release Stripe hold
   - Notify customer
5. Add `calculate_service_fee(us_price, foreign_price, user)` to payments.py if not already present
**Tests**: Stripe hold/capture/release, fee calculation, card data wiped after use
**Estimate**: 4-6 hours

### Build #211: GeoIP Routing Middleware
**Scope**: Detect customer's country from IP. Route US customers to arbitrage pipeline, others to standard.
**Files**: `server.py`, new `geoip.py`
**Tasks**:
1. Create `geoip.py`:
   - Use MaxMind GeoLite2 (free) or Cloudflare CF-IPCountry header
   - `get_customer_country(request)` → returns ISO country code
   - `should_use_arbitrage(country)` → True for US (Phase 1), expandable later
2. Update search flow:
   - If US customer: trigger POS arbitrage pipeline (proxy search + SerpAPI baseline + spread calc)
   - If non-US customer: standard Duffel/Picasso search only (zero proxy cost)
   - Response includes `arbitrage_available: true/false` flag
3. Cloudflare integration: read `CF-IPCountry` header (free, no database needed)
**Tests**: US IP → arbitrage path, non-US IP → standard path, header parsing
**Estimate**: 1-2 hours

### Build #212: Spread Calculator + Price Display
**Scope**: Calculate and display the spread, fee, and customer savings in the UI.
**Files**: `pos_arbitrage.py`, `payments.py`, templates, frontend JS
**Tasks**:
1. Price display for arbitrage results:
   - Show: "Google price: $1,400" (SerpAPI US baseline)
   - Show: "MYSTES price: $1,100" (foreign POS + service fee)
   - Show: "You save: $300 (21%)"
   - DO NOT show: foreign POS price or market code (airline compliance)
2. Fee breakdown in checkout:
   - "Flight cost: $800" (what airline charges via foreign POS)
   - "Service fee: $300" (what KYRIOS charges via Stripe)
   - "Total: $1,100"
   - "Google would charge: $1,400"
   - "Your savings: $300"
3. Wire `calculate_savings_breakdown()` from payments.py to use real spread data
4. Enforce $3 minimum fee display
**Tests**: Spread calculation accuracy, UI display correct, $3 minimum enforced
**Estimate**: 3-4 hours

### Build #213: Production Deployment + Cloudflare
**Scope**: Deploy to production with Cloudflare CDN in front.
**Files**: `render.yaml`, Cloudflare config, `.env.production`
**Tasks**:
1. Cloudflare setup:
   - DNS change: point mystes.com to Cloudflare
   - Page rules: cache static assets (HTML, CSS, JS, images)
   - Enable DDoS protection (free tier)
   - Enable "Under Attack" mode toggle
   - SSL: Full (strict)
2. Redis provisioning:
   - Render Redis or Upstash
   - Set REDIS_URL in production env
3. RQ Worker deployment:
   - Add worker process to render.yaml
   - Configure search worker + booking worker
4. Environment variables:
   - BRIGHTDATA_USERNAME, BRIGHTDATA_PASSWORD
   - REDIS_URL
   - SERPAPI_KEY (already set)
   - SENDGRID_API_KEY
   - GEOIP_MODE=cloudflare
5. End-to-end test on production:
   - Search through arbitrage pipeline
   - Verify prices display correctly
   - Test booking flow (use test card)
   - Verify Stripe service fee capture
6. Launch checklist sign-off
**Estimate**: 3-4 hours

---

## BUILD DEPENDENCY ORDER

```
Week 1 (Foundation):
  Validation Test ──→ #204 (Bright Data proxy) ──→ #205 (Multi-POS search)
                                                      ↓
                      #206 (Redis cache) ←────────────┘
                         ↓
                      #207 (Async search queue)
                         ↓
                      #208 (Email verification)

Week 2 (Booking + Launch):
  #209 (Booking queue) ──→ #210 (Card collection + Stripe)
                              ↓
  #211 (GeoIP routing) ──→ #212 (Spread display)
                              ↓
                           #213 (Production deploy)
```

---

## TOTAL EFFORT ESTIMATE

| Build | Hours | Priority |
|-------|-------|----------|
| Validation test | 1-2 | P0 (do first) |
| #204 Bright Data proxy | 1-2 | P0 |
| #205 Multi-POS search | 4-6 | P0 |
| #206 Redis cache | 3-4 | P0 |
| #207 Async search queue | 4-6 | P1 |
| #208 Email verification | 3-4 | P1 |
| #209 Booking queue | 6-8 | P0 |
| #210 Card collection | 4-6 | P0 |
| #211 GeoIP routing | 1-2 | P1 |
| #212 Spread display | 3-4 | P0 |
| #213 Production deploy | 3-4 | P0 |
| **TOTAL** | **34-48 hours** | |

---

## LAUNCH DAY CHECKLIST

- [ ] Bright Data PAYG active, DK POS pricing validated
- [ ] Cloudflare in front of mystes.com
- [ ] Redis cache running, top 200 routes warming
- [ ] Async search queue processing
- [ ] Email verification gate live
- [ ] Booking queue + Scraping Browser tested
- [ ] Customer card collection via Stripe Elements
- [ ] GeoIP routing (US → arbitrage, non-US → standard)
- [ ] Spread calculation + price display correct
- [ ] Stripe service fee hold/capture working
- [ ] End-to-end booking tested on production
- [ ] "Under Attack" mode ready (Cloudflare toggle)
- [ ] Monitoring: cache hit rate, queue depth, booking success rate
- [ ] Error alerting: Sentry or Render logs

---

## POST-LAUNCH (Month 1-3)

- [ ] MYSTES Network rework (CitizenSerp → Stripe payouts, mobile app)
- [ ] Hotel POS arbitrage (liteAPI + Duffel Stays through proxy)
- [ ] Multi-POS optimization (ANASTASiA learns best POS per route)
- [ ] Travel+ upsell after first booking ("Save 15% more with Travel+")
- [ ] B2B onboarding ("Sell these prices under your brand")
- [ ] APAi pitch to early operators
