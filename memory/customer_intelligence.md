# Customer Intelligence Knowledge Cards — Data Strategy
> Build #166 (2026-03-12) — Core to MYSTES business model

## Principle
ANASTASiA generates knowledge cards on customers as NATURAL EXHAUST of operations.
Zero incremental cost. Every search, booking, interaction, and pattern becomes compiled intelligence.
Knowledge cards ARE the data product — structured, queryable, valuable.

## Knowledge Card Generation = Center of the Model
- Claude Opus 4.6 is the TEACHER — builds cards once (expensive), cards run forever (free)
- Customer intelligence cards follow the same pattern
- One-time analysis per customer segment → compiled card → referenced millions of times
- This is why COGS stay at $3-5/mo even as data value scales to millions

---

## B2C Customer Intelligence Cards

### Individual Customer Card (Privacy-Compliant)
```
Card: customer_{user_id}_profile
Generated: after 3+ bookings (enough data for pattern)
Updated: after each booking/search

Fields:
- preferred_destinations: [{city, frequency, avg_spend}]
- travel_style: budget|midrange|premium|luxury
- booking_lead_time: avg days before departure
- price_sensitivity: low|medium|high (based on search-to-book ratio)
- preferred_airlines: [carrier_codes]
- preferred_hotel_stars: [3,4,5]
- group_composition: solo|couple|family|group
- cross_vertical_engagement: {flights: high, hotels: medium, activities: low}
- seasonal_patterns: {peak: [months], shoulder: [months]}
- booking_day_of_week: [distribution]
- responds_to_deals: true/false (clicks deal alerts?)
- points_accrual_rate: points/month
- lifetime_value: total_bookings * avg_fee
- churn_risk: low|medium|high
```

### Use Cases for Individual Cards
- ANASTASiA proactive offers: "Flights to your favorite destination dropped 30%"
- Smart defaults: pre-fill search based on patterns
- Bundle recommendations: knows which verticals to cross-sell
- Churn prevention: detect declining engagement → offer incentive
- Points optimization: suggest best redemption based on travel style

---

## B2B Agency Intelligence Cards

### Agency Card
```
Card: agency_{account_id}_profile
Generated: after first month of activity
Updated: weekly

Fields:
- route_specialization: [{origin, dest, volume, avg_margin}]
- market_focus: domestic|international|mixed
- client_mix: business_pct|leisure_pct
- volume_trend: growing|stable|declining (3-month rolling)
- avg_transaction_value: $amount
- monthly_booking_count: count
- preferred_providers: [api_sources they book most from]
- vertical_mix: {flights: 80%, hotels: 15%, other: 5%}
- response_to_promotions: engagement_rate
- team_size_estimate: based on unique booker patterns
- upgrade_readiness: likelihood to move to next B2B tier
- seasonal_volume: {peak_months, low_months}
```

### Use Cases for Agency Cards
- Tier upgrade nudges: "Your volume qualifies for Growth tier — save 5% on fees"
- Route intelligence: suggest new profitable routes based on similar agencies
- Churn prediction: volume declining → proactive retention offer
- Cross-sell: agency only books flights → "Your clients need hotels too"
- Partner matching: connect agencies with complementary specializations

---

## Aggregated Intelligence Products (Anonymized)

### Market Intelligence Cards
```
Card: market_{route}_{period}
Example: market_BNA-CDG_2026-Q1

Fields:
- demand_score: 0-100 (relative to other routes)
- avg_booking_price: $amount
- price_trend: rising|stable|falling
- lead_time_distribution: [histogram]
- passenger_composition: {solo: 30%, couples: 40%, families: 30%}
- vertical_attachment_rate: {hotel_booked: 65%, activity: 20%}
- price_elasticity: coefficient
- seasonal_index: [monthly_multipliers]
- top_airlines_booked: [carriers with market share]
- competitive_landscape: {our_price vs google vs expedia}
```

### Segment Intelligence Cards
```
Card: segment_{segment_name}_{period}
Example: segment_budget-families_2026-Q1

Fields:
- segment_size: user_count
- avg_spend_per_trip: $amount
- top_destinations: [ranked]
- booking_triggers: [deal_alerts, price_drops, seasonal]
- cross_vertical_propensity: {vertical: likelihood}
- retention_rate: 3mo/6mo/12mo
- referral_rate: referred_friends_per_user
- channel_preference: mobile_vs_desktop
```

---

## Data Buyers & Revenue

| Buyer | What They Want | Value |
|-------|---------------|-------|
| **Airlines** | Route demand, pricing elasticity, competitor bookings | Premium — affects billion-dollar route decisions |
| **Hotels** | Market demand by city, seasonal patterns, traveler preferences | High — RevPar optimization |
| **Tourism boards** | Destination popularity trends, emerging markets, traveler demographics | Medium — marketing budget allocation |
| **OTA competitors** | Market intelligence, pricing benchmarks | Very high — competitive intel |
| **Travel investors** | Market trends, growth indicators, segment analysis | High — investment decisions |
| **Insurance companies** | Travel pattern data, risk profiles | Medium — underwriting |

### Revenue Model
- NOT a separate standalone product
- Delivered as:
  - Enterprise subscription add-on
  - Industry intelligence reports (quarterly)
  - API access for premium partners
  - Internal use for ANASTASiA's own recommendation engine (primary use)
- Pricing: custom per buyer, based on scope and exclusivity

---

## Data Moat Properties

1. **Unreplicable**: Requires our operational footprint across all providers + consumer base
2. **Compounds**: Every new user, booking, and search makes the data more valuable
3. **Cross-network**: We see patterns across ALL providers simultaneously (Picasso + Duffel + AirGateway + liteAPI)
4. **Real-time**: Not stale snapshots — live intelligence from active operations
5. **Multi-layer**: Consumer behavior + agency patterns + provider pricing + cross-vertical correlation
6. **Privacy-compliant**: Cards are compiled intelligence (patterns), not raw PII
7. **Self-improving**: Cards update automatically with each interaction — no manual curation

---

## Technical Implementation

### Card Generation Pipeline
1. **Event stream**: Every search, booking, click, session → event bus
2. **Accumulator**: Events collected per user/agency/route over time window
3. **Card compiler**: When enough data points → generate/update knowledge card
4. **Card store**: JSON cards in DB (CustomerIntelligenceCard model)
5. **Query engine**: ANASTASiA reads cards for personalization + proactive offers
6. **Aggregator**: Individual cards → anonymized segment/market cards
7. **Report generator**: Segment/market cards → sellable intelligence products

### Privacy Rules
- Individual cards: ONLY used for that user's personalization
- Never shared externally at individual level
- Aggregation minimum: 50+ users per segment before external reporting
- User can request card deletion (GDPR/CCPA compliance)
- B2B agency data: governed by agency agreement, agency owns their data
- MYSTES retains aggregated patterns even if individual data deleted

---

## Connection to Existing Architecture

- **Knowledge Cards architecture** (anastasia/knowledge/): Same pattern, new domain
- **Card Security** (card_security.py): Encryption and service-binding applies to customer cards
- **SaaS Feature Gating** (anastasia/saas/): Controls who can access intelligence features
- **Cross-GDS Intelligence** (memory/anastasia_platform_vision.md): Consumer intelligence is the B2C complement to B2B cross-GDS data
- **The Inevitability Loop**: More users → better cards → better personalization → more users
