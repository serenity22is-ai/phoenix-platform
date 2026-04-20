# MYSTES Launch Economics — Bright Data Proxy Model
**Date**: 2026-04-14
**Target Launch**: ~2026-04-28 (2 weeks from today)
**Model**: Residential proxy (Bright Data) for BOTH search AND booking. No physical SIM farm.

---

## ARCHITECTURE (REVISED)

```
SEARCH PIPELINE:
  google_flights_scraper.py → Bright Data residential proxy (DK/DE IP) → Google Flights
  → Foreign POS price (e.g. $800)

US BASELINE:
  SerpAPI → US retail price (e.g. $1,400)

SPREAD CALCULATION:
  Spread = US retail ($1,400) - Foreign POS ($800) = $600
  Service fee = Spread × Fee Tier %
  Customer pays = Foreign POS price + Service fee

BOOKING PIPELINE:
  airline_booker.py (Playwright) → Bright Data Scraping Browser (sticky DK IP) → Airline checkout
  Customer card entered → Airline charges customer at DK POS price ($800)
  KYRIOS charges service fee via Stripe ($300 for Guest at 50%)
```

---

## FIXED MONTHLY COSTS

| Component | Service | Monthly Cost | Notes |
|-----------|---------|-------------|-------|
| Proxy (search + booking) | Bright Data Enterprise | $1,999 | 798 GB included @ $2.50/GB (promo). Overage $5/GB. |
| CDN + DDoS | Cloudflare Pro | $25 | Absorbs 90% of traffic |
| Web server | Render Standard ×2 | $50 | 2 instances for redundancy |
| Background workers | Render Workers ×3 | $63 | Search + booking job processors |
| Cache | Redis (Render) | $30 | Route cache + session store |
| Database | PostgreSQL (Render) | $20 | Production backend |
| Email | SendGrid Essentials | $20 | Verification codes + confirmations |
| US baseline | SerpAPI | $50 | 5,000 searches/mo included |
| Domain + DNS | Cloudflare | $15 | mystes.com |
| **TOTAL FIXED** | | **$2,272/mo** | Before any bookings |

---

## VARIABLE COSTS PER TRANSACTION

| Cost Item | Per Search | Per Booking | Notes |
|-----------|-----------|-------------|-------|
| Bright Data proxy (search) | $0.013 | — | ~5 MB per Google Flights page @ $2.50/GB |
| Bright Data proxy (booking) | — | $0.050 | ~20 MB per Scraping Browser checkout session |
| SerpAPI baseline query | $0.010 | — | US price ceiling lookup |
| Stripe fee on service fee | — | 2.9% + $0.30 | On KYRIOS service fee only |
| SendGrid email | — | $0.001 | Verification + confirmation |
| **TOTAL VARIABLE** | **$0.023/search** | **~$0.35 + 2.9% of fee** | |

---

## REVENUE MODEL

### Fee Tiers (from payments.py — SOLE SOURCE OF TRUTH)
| Tier | Monthly Sub | Fee (% of spread) |
|------|------------|-------------------|
| Guest (anonymous) | $0 | 50% |
| Free (registered) | $0 | 45% |
| Travel+ | $9.99 | 35% |
| B2B Starter | $49 | 25% |
| B2B Growth | $99 | 20% |
| B2B Volume | $199 | 15% |

### Per-Booking Revenue (International with POS Arbitrage)
Based on Feb 24 proven data: avg $374 spread (29.6% below US retail)

| Tier | Avg Spread | Fee % | Service Fee | Stripe Cost | Net Revenue/Booking |
|------|-----------|-------|-------------|-------------|---------------------|
| Guest | $374 | 50% | $187.00 | $5.72 | **$181.28** |
| Free | $374 | 45% | $168.30 | $5.18 | **$163.12** |
| Travel+ | $374 | 35% | $130.90 | $4.10 | **$126.80** |
| B2B Starter | $374 | 25% | $93.50 | $3.01 | **$90.49** |
| B2B Growth | $374 | 20% | $74.80 | $2.47 | **$72.33** |
| B2B Volume | $374 | 15% | $56.10 | $1.93 | **$54.17** |

**Conservative estimate**: Use $150 avg spread (mix of high-spread intl + low-spread routes)

| Tier | Avg Spread | Fee % | Service Fee | Stripe Cost | Net Revenue/Booking |
|------|-----------|-------|-------------|-------------|---------------------|
| Guest | $150 | 50% | $75.00 | $2.48 | **$72.52** |
| Free | $150 | 45% | $67.50 | $2.26 | **$65.24** |
| Travel+ | $150 | 35% | $52.50 | $1.82 | **$50.68** |

### Domestic Routes (No/Minimal POS Arbitrage)
- Spread: $0-20 on domestic
- Fee: $3 minimum kicks in
- Net revenue: ~$2.61/booking after Stripe ($3 - $0.30 - $0.09)
- Still profitable but low margin — domestic is a funnel to international

---

## WEEK-BY-WEEK VIRAL PROJECTIONS

### Assumptions
- 2% search-to-booking conversion (industry standard for OTAs)
- 40% of bookings are international (where POS arbitrage applies)
- 60% of bookings are domestic ($3 minimum fee)
- Blended avg: 40% × $150 spread × 45% fee + 60% × $3 min = ~$28.80 avg net/booking
- Week 1 launch tier mix: 80% Guest, 15% Free, 5% Travel+
- Blended fee %: ~48%

### Week 1 — Launch (Soft Viral)
| Metric | Daily | Weekly |
|--------|-------|--------|
| Page views | 10,000 | 70,000 |
| Live searches | 2,000 | 14,000 |
| Bookings | 40 | 280 |
| Intl bookings (40%) | 16 | 112 |
| Domestic bookings (60%) | 24 | 168 |
| | | |
| **Revenue** | | |
| Intl (16 × $72 avg net) | $1,152 | $8,064 |
| Domestic (24 × $2.61 net) | $63 | $438 |
| **Daily revenue** | **$1,215** | **$8,502** |
| | | |
| **Costs** | | |
| Proxy search (2,000 × $0.023) | $46 | $322 |
| Proxy booking (40 × $0.05) | $2 | $14 |
| Fixed costs (daily share) | $76 | $530 |
| **Daily costs** | **$124** | **$866** |
| | | |
| **NET PROFIT** | **$1,091/day** | **$7,636/week** |

### Week 2 — Screenshots Spreading
| Metric | Daily | Weekly |
|--------|-------|--------|
| Page views | 50,000 | 350,000 |
| Live searches | 10,000 | 70,000 |
| Bookings | 200 | 1,400 |
| Intl bookings (40%) | 80 | 560 |
| Domestic bookings (60%) | 120 | 840 |
| | | |
| **Revenue** | | |
| Intl (80 × $72 avg net) | $5,760 | $40,320 |
| Domestic (120 × $2.61 net) | $313 | $2,191 |
| **Daily revenue** | **$6,073** | **$42,511** |
| | | |
| **Costs** | | |
| Proxy search (10,000 × $0.023) | $230 | $1,610 |
| Proxy booking (200 × $0.05) | $10 | $70 |
| Fixed costs (daily share) | $76 | $530 |
| **Daily costs** | **$316** | **$2,210** |
| | | |
| **NET PROFIT** | **$5,757/day** | **$40,301/week** |

### Week 3 — TikTok / Mainstream Pickup
| Metric | Daily | Weekly |
|--------|-------|--------|
| Page views | 250,000 | 1,750,000 |
| Live searches | 50,000 | 350,000 |
| Bookings | 1,000 | 7,000 |
| Intl bookings (40%) | 400 | 2,800 |
| Domestic bookings (60%) | 600 | 4,200 |
| | | |
| **Revenue** | | |
| Intl (400 × $72 avg net) | $28,800 | $201,600 |
| Domestic (600 × $2.61 net) | $1,566 | $10,962 |
| **Daily revenue** | **$30,366** | **$212,562** |
| | | |
| **Costs** | | |
| Proxy search (50,000 × $0.023) | $1,150 | $8,050 |
| Proxy booking (1,000 × $0.05) | $50 | $350 |
| Fixed costs (daily share) | $76 | $530 |
| Bright Data overage (est ~200GB over cap) | $143 | $1,000 |
| **Daily costs** | **$1,419** | **$9,930** |
| | | |
| **NET PROFIT** | **$28,947/day** | **$202,632/week** |

### Week 4 — Sustained Viral
| Metric | Daily | Weekly |
|--------|-------|--------|
| Page views | 1,000,000 | 7,000,000 |
| Live searches | 100,000 | 700,000 |
| Bookings | 2,500 | 17,500 |
| Intl bookings (40%) | 1,000 | 7,000 |
| Domestic bookings (60%) | 1,500 | 10,500 |
| | | |
| **Revenue** | | |
| Intl (1,000 × $72 avg net) | $72,000 | $504,000 |
| Domestic (1,500 × $2.61 net) | $3,915 | $27,405 |
| Travel+ subscriptions (~500 new) | — | $4,995 |
| **Daily revenue** | **$75,915** | **$536,400** |
| | | |
| **Costs** | | |
| Proxy search (100K × $0.023) | $2,300 | $16,100 |
| Proxy booking (2,500 × $0.05) | $125 | $875 |
| Fixed costs (daily share) | $76 | $530 |
| Bright Data overage (est ~1TB over cap) | $714 | $5,000 |
| Render scaling (extra instances) | $50 | $350 |
| SerpAPI overage | $30 | $210 |
| **Daily costs** | **$3,295** | **$23,065** |
| | | |
| **NET PROFIT** | **$72,620/day** | **$513,335/week** |

---

## MONTH 1 SUMMARY

| | Revenue | Costs | Profit | Margin |
|---|---------|-------|--------|--------|
| Week 1 | $8,502 | $866 | $7,636 | 89.8% |
| Week 2 | $42,511 | $2,210 | $40,301 | 94.8% |
| Week 3 | $212,562 | $9,930 | $202,632 | 95.3% |
| Week 4 | $536,400 | $23,065 | $513,335 | 95.7% |
| **MONTH 1 TOTAL** | **$799,975** | **$36,071** | **$763,904** | **95.5%** |

---

## COST AS % OF REVENUE

| Cost Category | Month 1 Total | % of Revenue |
|---------------|--------------|-------------|
| Bright Data proxy | ~$25,000 | 3.1% |
| Stripe processing | ~$8,000 | 1.0% |
| Infrastructure (Render, Redis, etc.) | ~$2,300 | 0.3% |
| SerpAPI | ~$300 | 0.04% |
| SendGrid | ~$50 | 0.01% |
| **TOTAL COGS** | **~$36,000** | **4.5%** |

**Gross margin: 95.5%**

---

## PROXY DATA BUDGET

### Bright Data Enterprise Plan: 798 GB/mo @ $2.50/GB = $1,999/mo

| Week | Search GB | Booking GB | Total GB | Within Cap? |
|------|----------|-----------|----------|-------------|
| Week 1 | 0.3 | 0.1 | 0.4 | Yes (798 GB cap) |
| Week 2 | 1.7 | 0.3 | 2.0 | Yes |
| Week 3 | 8.8 | 1.4 | 10.2 | Yes |
| Week 4 | 25.0 | 3.5 | 28.5 | Yes |
| **Month total** | **35.8** | **5.3** | **41.1 GB** | **Yes — 757 GB unused** |

Wait — at these volumes the Enterprise plan is overkill for Month 1. **Start with Pay-As-You-Go ($4/GB promo) and upgrade when volume justifies it.**

### Revised Month 1 Proxy Cost (Pay-As-You-Go @ $4/GB promo):
- 41 GB × $4 = **$164/mo** (not $1,999)

### When to Upgrade to Enterprise:
- Enterprise = $1,999/mo for 798 GB = break-even at 500 GB/mo
- At $4/GB PAYG: 500 GB = $2,000 → same cost
- You need 500+ GB/month to justify Enterprise
- That's ~2.5M searches/month or ~25K bookings/month
- Roughly 83K searches/day = Week 4+ territory
- **Upgrade at Week 4, not at launch**

---

## REVISED FIXED COSTS (LAUNCH — PAYG PROXY)

| Component | Monthly Cost |
|-----------|-------------|
| Bright Data PAYG (est 50GB) | $200 |
| Cloudflare Pro | $25 |
| Render Standard ×2 | $50 |
| Render Workers ×3 | $63 |
| Redis | $30 |
| PostgreSQL | $20 |
| SendGrid | $20 |
| SerpAPI | $50 |
| Domain | $15 |
| **TOTAL LAUNCH COST** | **$473/mo** |

Upgrade path as volume grows:
- $473/mo → $1,000/mo (add workers) → $2,500/mo (Enterprise proxy) → $5,000/mo (max scale)

---

## BREAK-EVEN ANALYSIS

### At launch fixed cost of $473/mo ($16/day):
- Need $16/day in service fees to break even
- At $72 avg net per intl booking: **1 international booking per day = profitable**
- At $3 domestic minimum: 6 domestic bookings per day = profitable

### Day 1 break-even: 1 international booking with POS arbitrage.

---

## CRITICAL RISKS

1. **Bright Data DK residential IPs might not trigger DK POS pricing** — MUST validate before launch. Budget $20 for test.
2. **Airline checkout might detect Scraping Browser** — MUST test one real booking. Budget $50 for test flight.
3. **3D Secure challenges** — need real-time relay to customer. Not yet built.
4. **IP/billing address mismatch** — customer has US billing, IP is DK. Some airlines may flag. Test per-airline.
5. **Spread variance** — $374 avg is from Feb 24 data (international only). Real mix will be lower. Conservative $150 used in projections.
6. **Bright Data promo expires in 3 months** — costs double after promo ($4→$8/GB PAYG or $2.50→$5/GB Enterprise).

---

## PRE-LAUNCH CHECKLIST (2 weeks)

### Week 1 (Apr 14-21): Validate + Infrastructure
- [ ] Sign up Bright Data PAYG (promo code RESIGB50)
- [ ] Test DK residential proxy on Google Flights — confirm POS pricing
- [ ] Test Scraping Browser sticky session on one airline checkout
- [ ] Set up Cloudflare in front of Render
- [ ] Set up Redis cache + route warming cron
- [ ] Build async search (job queue + polling endpoint)
- [ ] Build email verification gate

### Week 2 (Apr 21-28): Integration + Launch
- [ ] Wire google_flights_scraper.py to Bright Data proxy
- [ ] Wire airline_booker.py to Scraping Browser (customer card swap)
- [ ] Build spread calculator (SerpAPI ceiling + proxy foreign price)
- [ ] Build booking queue + pool manager
- [ ] GeoIP routing middleware
- [ ] End-to-end test: search → price display → booking → Stripe fee
- [ ] Production deploy
- [ ] LAUNCH

---

## DECISION: SIM FARM STATUS

**Physical SIM farm (CitizenSerp) = DEFERRED.** Not eliminated — deferred to Phase 3.

- Phase 1: Bright Data residential proxy (search + booking). Validate model.
- Phase 2: Scale proxy. Optimize per-booking costs. Multi-POS testing.
- Phase 3: IF proxy costs exceed 10% of revenue at scale, THEN build physical SIM farm to reduce per-booking cost from ~$0.05 to ~$0.005.

At current projections, proxy costs are 3.1% of revenue. Physical SIM farm is a cost optimization, not a necessity.
