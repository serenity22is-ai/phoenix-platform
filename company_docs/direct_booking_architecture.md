# Direct Booking Architecture — Booking Recipes + AI Self-Learning
> Session: 2026-04-21 | Status: LOCKED ARCHITECTURE | Core to MYSTES proxy booking channel

---

## Executive Summary

MYSTES's proxy booking channel uses **Bright Data Scraping Browser** (residential proxies + CDP) to access airline websites from foreign POS markets, obtaining cheaper geo-priced fares. Instead of fragile HTML form filling, bookings are executed by **intercepting and replaying the airline's own internal API calls** — structured JSON requests that the airline's SPA frontend makes to its backend.

Booking flows are captured as **Booking Recipe knowledge cards** — JSON templates that ANASTASiA compiles, maintains, and self-heals. Claude is the TEACHER (generates/repairs recipes). Recipes EXECUTE at zero AI cost. AI only activates for new airline discovery, recipe repair, and fallback booking.

---

## The Problem We Solved

### Why Not Form Filling?
- 800+ airlines with different HTML structures
- Airlines redesign checkout pages constantly
- Payment fields inside cross-origin iframes (Adyen, Cybersource)
- Anti-bot detection (PerimeterX, DataDome, Akamai) on checkout pages
- Foreign language sites when accessing from non-English POS markets
- Multi-step navigation (select → passengers → seats → bags → payment → confirm)
- Generic CSS selectors work ~60-70% — unacceptable for real bookings

### Why Not Browser Handoff?
- Exposes our proxy model to the customer
- Security risk — user could navigate anywhere in the proxied browser
- Still has language issues
- Customer experience is poor (unfamiliar airline site)

### The Solution: Booking Recipes (API Interception)
Modern airline websites are SPAs (React/Angular/Vue) that communicate with their backends via structured API calls (REST/GraphQL). When a customer fills a form and clicks "Continue", the browser sends a `POST /api/booking/passengers` with JSON — not an HTML form submission.

We skip the forms entirely and call the airline's APIs directly.

---

## Three-Tier Booking System

### Tier 1: Compiled Recipes (Zero AI Cost — 95% of Bookings)

Pre-built recipe knowledge cards for major airlines. Pure code execution:

1. Bright Data establishes geo-targeted session (residential IP in target POS country)
2. Playwright loads airline page → extracts session cookies, CSRF tokens, auth tokens
3. Recipe engine executes API calls in sequence, substituting customer data
4. Each response is validated
5. Confirmation code (PNR) extracted from final response

**Cost per booking**: $0 AI + ~$0.10-0.50 Bright Data session
**Speed**: 5-10 seconds
**Reliability**: 95%+ (APIs either work or return clear errors)

### Tier 2: AI Recipe Generator (One-Time AI Cost per Airline)

When adding a new airline:

1. Developer does a manual booking flow while Playwright records ALL network requests
2. Network capture (HAR-like format) is handed to ANASTASiA
3. AI analyzes the requests, identifies booking-relevant API calls, maps fields to our passenger data model
4. Outputs a compiled Booking Recipe knowledge card
5. Recipe is tested (dry run through steps 1-3, stopping before payment)
6. Recipe is deployed — all future bookings on that airline use Tier 1

**Cost**: ~$0.50 one-time per airline (one Opus API call)
**Time**: Minutes instead of 2-4 hours of manual developer mapping

### Tier 3: AI Live Executor (Per-Booking AI Cost — Rare Fallback)

For airlines with no existing recipe:

1. Customer wants to book on an airline we've never seen
2. Bright Data session established, Playwright loads the airline site
3. ANASTASiA intercepts network traffic in real-time
4. AI analyzes the live API calls, identifies the booking flow
5. AI executes the booking by replaying intercepted calls with customer data
6. On success: AI generates a recipe card from what it just did → future bookings drop to Tier 1

**Cost**: ~$0.10-0.15 per booking (one Opus call)
**Speed**: 30-60 seconds
**Coverage**: Every airline on Earth that has a website

### The Flywheel

```
New airline encountered
  → Tier 3: AI executes live booking ($0.15)
  → AI auto-generates recipe from the successful flow ($0)
  → Recipe saved as knowledge card
  → Next booking on same airline → Tier 1: $0 AI cost

Recipe fails (airline changed their API)
  → ANASTASiA watchdog detects failure
  → AI re-analyzes the site, updates the recipe ($0.15)
  → All future bookings work again → $0 AI cost
```

The system teaches itself. Every booking makes it smarter. Every failure it recovers from makes it more resilient. AI cost trends toward zero as recipes accumulate.

---

## Why API Interception Beats Form Filling

| Problem | Form Filling | Booking Recipes |
|---------|-------------|-----------------|
| Foreign language sites | Breaks on non-English text | API payloads are structured JSON — language-irrelevant |
| Payment iframes | Can't access cross-origin iframes | Direct API calls — no DOM interaction |
| CSS selectors | Break when airline redesigns | API endpoints/schemas change far less often |
| Anti-bot | CAPTCHAs on form pages | API calls with valid session cookies pass through |
| Multi-step navigation | Different buttons/modals per airline | Sequential API calls — deterministic |
| Reliability | 60-70% | 95%+ |
| Customer experience | Must stay in our UI regardless | Customer sees only MYSTES UI |
| AI cost per booking | Zero (but brittle) | Zero for Tier 1, $0.15 fallback |
| Maintenance | Constant CSS selector updates | Watchdog auto-repairs recipes via AI |

---

## Booking Recipe Card Schema

```json
{
  "recipe_version": "1.0",
  "airline_group": "lufthansa_group",
  "airlines": ["LH", "LX", "OS", "SN", "EW"],
  "base_url": "https://www.lufthansa.com",
  "language_path": "/en/",
  "session_setup": {
    "load_url": "https://www.lufthansa.com/en/homepage",
    "wait_for": "networkidle",
    "extract_tokens": {
      "csrf_token": {"source": "cookie", "name": "XSRF-TOKEN"},
      "session_id": {"source": "cookie", "name": "JSESSIONID"},
      "bearer_token": {"source": "header", "pattern": "Authorization: Bearer (.+)"}
    }
  },
  "steps": [
    {
      "name": "search_offers",
      "method": "POST",
      "url": "/api/offers/search",
      "headers": {
        "X-CSRF-Token": "${csrf_token}",
        "Content-Type": "application/json"
      },
      "body": {
        "origin": "${origin_iata}",
        "destination": "${destination_iata}",
        "departureDate": "${departure_date}",
        "passengers": [{"type": "ADT", "count": "${adult_count}"}],
        "cabinClass": "${cabin_class}"
      },
      "response_extract": {
        "offer_id": "$.offers[0].id",
        "price_total": "$.offers[0].price.total",
        "currency": "$.offers[0].price.currency"
      },
      "validation": {
        "status_code": 200,
        "required_fields": ["offer_id"]
      }
    },
    {
      "name": "select_offer",
      "method": "POST",
      "url": "/api/booking/select",
      "headers": {"X-CSRF-Token": "${csrf_token}"},
      "body": {"offerId": "${offer_id}"},
      "response_extract": {
        "booking_id": "$.bookingId",
        "booking_token": "$.token"
      },
      "validation": {"status_code": [200, 201]}
    },
    {
      "name": "add_passengers",
      "method": "PUT",
      "url": "/api/booking/${booking_id}/passengers",
      "headers": {
        "X-CSRF-Token": "${csrf_token}",
        "X-Booking-Token": "${booking_token}"
      },
      "body": {
        "passengers": [{
          "firstName": "${pax_first_name}",
          "lastName": "${pax_last_name}",
          "dateOfBirth": "${pax_dob}",
          "gender": "${pax_gender}",
          "email": "${pax_email}",
          "phone": "${pax_phone}",
          "passport": {
            "number": "${pax_passport_number}",
            "nationality": "${pax_nationality}",
            "expiry": "${pax_passport_expiry}"
          }
        }]
      },
      "validation": {"status_code": 200}
    },
    {
      "name": "submit_payment",
      "method": "POST",
      "url": "/api/booking/${booking_id}/payment",
      "headers": {
        "X-CSRF-Token": "${csrf_token}",
        "X-Booking-Token": "${booking_token}"
      },
      "body": {
        "paymentMethod": "creditCard",
        "card": {
          "number": "${card_number}",
          "expiryMonth": "${card_exp_month}",
          "expiryYear": "${card_exp_year}",
          "cvv": "${card_cvv}",
          "holderName": "${card_holder_name}"
        },
        "billingAddress": {
          "line1": "${billing_address_line1}",
          "city": "${billing_city}",
          "postalCode": "${billing_postal_code}",
          "country": "${billing_country}"
        }
      },
      "response_extract": {
        "payment_status": "$.status",
        "payment_id": "$.paymentId"
      },
      "validation": {
        "status_code": [200, 201],
        "required_fields": ["payment_status"]
      }
    },
    {
      "name": "confirm_booking",
      "method": "POST",
      "url": "/api/booking/${booking_id}/confirm",
      "headers": {
        "X-CSRF-Token": "${csrf_token}",
        "X-Booking-Token": "${booking_token}"
      },
      "body": {},
      "response_extract": {
        "pnr": "$.confirmationCode",
        "total_charged": "$.payment.amount",
        "charged_currency": "$.payment.currency",
        "e_ticket_number": "$.eTicket"
      },
      "validation": {
        "status_code": [200, 201],
        "required_fields": ["pnr"]
      }
    }
  ],
  "card_data_wipe": {
    "after_step": "submit_payment",
    "on_failure": true,
    "fields": ["card_number", "card_cvv", "card_exp_month", "card_exp_year"]
  },
  "error_patterns": {
    "session_expired": {"status": 401, "retry": true, "max_retries": 1},
    "offer_expired": {"body_contains": "no longer available", "abort": true},
    "payment_declined": {"body_contains": "declined", "abort": true},
    "rate_limited": {"status": 429, "retry": true, "delay_seconds": 5}
  },
  "metadata": {
    "created_by": "anastasia_recipe_generator",
    "created_at": "2026-04-21T00:00:00Z",
    "last_verified": "2026-04-21T00:00:00Z",
    "success_count": 0,
    "failure_count": 0,
    "avg_execution_time_seconds": null
  }
}
```

---

## Why Bright Data (Not SIM Farm)

| Factor | Mobile SIM Farm | Bright Data Scraping Browser |
|--------|----------------|------------------------------|
| Capex | $10K+ hardware | $0 |
| Country coverage | 20-50 SIMs max | 195+ countries |
| IP diversity | Dozens per country | Millions of residential IPs |
| Anti-detection | DIY | Professional (fingerprinting, CAPTCHA solving) |
| Maintenance | Dead SIMs, data plans, hardware | Zero — managed service |
| Scaling | Buy more hardware | Instant |
| Cost per session | ~$0.50+ (data plan amortized) | ~$0.10-0.50 |
| CDP support | No | Native (WebSocket port 9222) |

### Bright Data Configuration
```
BRIGHTDATA_USERNAME=brd-customer-XXXXXX-zone-residential
BRIGHTDATA_PASSWORD=XXXXXXXX
BRIGHTDATA_HOST=brd.superproxy.io
BRIGHTDATA_PORT=22225
BRIGHTDATA_SB_HOST=brd.superproxy.io
BRIGHTDATA_SB_PORT=9222
```

CDP WebSocket URL: `wss://{username}-country-{CC}:{password}@brd.superproxy.io:9222`

---

## Airline Group Coverage (10 Recipes = 18+ Airlines)

| Recipe | Airlines | Booking Platform |
|--------|----------|-----------------|
| Lufthansa Group | LH, LX, OS, SN, EW | Shared |
| Air France-KLM | AF, KL | Shared |
| IAG | BA, IB, VY | Shared |
| ANA | NH | Own |
| JAL | JL | Own |
| Korean Air Group | KE, OZ | Shared |
| Emirates | EK | Own |
| Qatar Airways | QR | Own |
| Turkish Airlines | TK | Own |
| Singapore Airlines | SQ | Own |

These cover the vast majority of international routes with significant POS arbitrage spreads. Tier 3 AI fallback covers every other airline automatically.

---

## Cost Analysis

| Scenario | AI Cost | Bright Data | Revenue (service fee) |
|----------|---------|-------------|----------------------|
| Tier 1 recipe booking | $0.00 | $0.10-0.50 | $50-200+ |
| Tier 3 first booking (new airline) | $0.15 | $0.10-0.50 | $50-200+ |
| Recipe generation from capture | $0.50 once | — | Covers airline forever |
| Recipe auto-repair | $0.15 | — | Saves all future bookings |
| Price discovery (search, no booking) | $0.00 | $0.05-0.10 | Informs arbitrage display |

AI cost is negligible relative to revenue. Trends toward zero as recipe library grows.

---

## End-to-End Customer Flow

```
1. Customer searches on MYSTES
   └─ ANASTASiA knowledge cards identify POS arbitrage opportunity
   └─ Display: "Save $374 on LAX-NRT — Book at this price"

2. Customer clicks "Book at This Price"
   └─ Customer fills passenger details + card in MYSTES UI
   └─ MYSTES server handles everything — customer sees progress bar

3. Stripe authorizes service fee (hold, NOT capture)
   └─ Hold = spread * tier fee percentage, $3 minimum, NO maximum

4. BookingEngine selects execution method:
   └─ Recipe exists for airline? → Tier 1 (compiled recipe)
   └─ No recipe? → Tier 3 (AI live executor)

5. Bright Data session established
   └─ Residential IP in target POS country (e.g., Denmark)
   └─ Playwright loads airline page → extracts session tokens

6. Recipe executes (or AI analyzes live)
   └─ API calls in sequence: search → select → passengers → payment → confirm
   └─ Card data wiped immediately after payment step
   └─ PNR extracted from confirmation response

7. On success:
   └─ Stripe captures service fee
   └─ Booking record created in DB
   └─ Customer sees confirmation + PNR in MYSTES UI
   └─ MYSTES Rewards points awarded
   └─ If Tier 3: auto-generate recipe for next time

8. On failure:
   └─ Stripe hold released immediately
   └─ Customer notified with clear explanation
   └─ Offered standard (non-arbitrage) Duffel booking as fallback
   └─ Failure logged for recipe improvement
```

---

## Security Model

1. **Customer never sees airline site** — all interaction happens server-side via Playwright
2. **Card data auto-wipe** — cleared from memory immediately after payment step or on any failure
3. **Stripe authorize-then-capture** — customer is never charged unless booking succeeds
4. **Airline is MoR** — customer's card is charged by the airline directly; MYSTES only charges the service fee via Stripe
5. **No PCI scope for card storage** — card data is transient (in-memory during booking execution only, never persisted)
6. **Proxied browser is server-side only** — no WebView, no iframe, no customer browser exposure
7. **Our model is invisible** — customer sees MYSTES UI; airline sees a residential IP from the target country

---

## Integration with Existing Architecture

### Existing Components (Reused)
- `anastasia/proxy/` — ProxyModule neuron (Bright Data + Webshare providers, market routing)
- `anastasia/booking_engine/` — BookingQueue + SessionManager (priority queue, job tracking)
- `server.py` — `/api/booking/proxy-session`, `/proxy-complete`, `/proxy-cancel` endpoints
- `server.py` — `_worker_loop()` background thread (dequeues jobs, routes to booking channel)
- `anastasia/knowledge/watchdog.py` — Drift detection (extended to monitor recipe health)
- `anastasia/modules/flight_modules.py` — Knowledge card infrastructure

### New Components (To Build)
- `anastasia/booking_recipes/` — Recipe Engine module
  - `engine.py` — Recipe executor (loads card, establishes session, runs API calls)
  - `recorder.py` — Network capture tool (Playwright request interception → HAR-like output)
  - `generator.py` — AI recipe generator (ANASTASiA analyzes captures → recipe card)
  - `live_executor.py` — AI live fallback (real-time API interception + execution)
  - `cards/` — Directory of compiled booking recipe JSON cards
  - `validator.py` — Recipe dry-run tester (executes through passengers step, stops before payment)

### Modified Components
- `anastasia/booking_engine/__init__.py` — Route to recipe engine instead of form filler
- `server.py:_execute_proxy_booking()` — Delegate to recipe engine
- `anastasia/knowledge/watchdog.py` — Add recipe health monitoring

---

## ANASTASiA Knowledge Card Pattern (Consistency)

This architecture follows the EXACT pattern established for flight search:

| Aspect | Flight Search Cards | Booking Recipe Cards |
|--------|-------------------|---------------------|
| Purpose | API integration intelligence | Booking flow intelligence |
| Format | JSON knowledge cards | JSON recipe cards |
| Creation | Claude teaches, cards compile | Claude analyzes captures, recipes compile |
| Runtime cost | Zero AI (card-based dispatch) | Zero AI (recipe-based execution) |
| AI activation | Drift detection, updates | Recipe repair, new airline discovery |
| Storage | `anastasia/modules/cards/` | `anastasia/booking_recipes/cards/` |
| Watchdog | API schema drift detection | Recipe health monitoring |

---

## Locked Decisions (DO NOT REVERSE)

1. **Booking Recipes over form filling** — API interception is the primary mechanism
2. **Three-tier system** — Compiled recipes → AI generator → AI live fallback
3. **Customer NEVER sees airline site** — all server-side via Playwright
4. **Card data auto-wipe** — immediately after payment step or on failure
5. **Airline is MoR** — customer's card charged by airline, MYSTES charges service fee via Stripe
6. **Bright Data over SIM farm** — residential proxies, CDP, zero hardware
7. **10 recipes cover 18+ airlines** — airline groups share booking platforms
8. **AI cost trends to zero** — recipes accumulate, AI only for discovery/repair
9. **Recipe self-healing via watchdog** — ANASTASiA auto-repairs broken recipes
10. **Tier 3 auto-generates recipes** — every first booking on a new airline creates a recipe for next time

---

## POS Arbitrage Proof Points

- LAX-NRT: $1,016 (Danish POS via Picasso) vs $2,345 (US POS via Google) — **57% savings**
- Average POS arbitrage spread: $374 (29.6%) across tested routes
- Global arbitrage — ALL markets, not just US
- Knowledge cards track which routes have biggest spreads by POS market

---

## Environment Variables Required

```bash
# Bright Data (required for proxy bookings)
BRIGHTDATA_USERNAME=brd-customer-XXXXXX-zone-residential
BRIGHTDATA_PASSWORD=XXXXXXXX

# Optional overrides (defaults shown)
BRIGHTDATA_HOST=brd.superproxy.io
BRIGHTDATA_PORT=22225
BRIGHTDATA_SB_HOST=brd.superproxy.io
BRIGHTDATA_SB_PORT=9222

# AI (for Tier 2 recipe generation + Tier 3 fallback)
ANTHROPIC_API_KEY=sk-ant-...

# Stripe (for service fee authorize/capture)
STRIPE_SECRET_KEY=sk_live_...
```

---

*Architecture designed 2026-04-21. This document is the source of truth for the direct booking system.*
*Part of the MYSTES KYRIOS LLC proprietary technology stack.*
