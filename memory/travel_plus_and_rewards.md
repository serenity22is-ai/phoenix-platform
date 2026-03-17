# MYSTES Travel+ Subscription, B2B Tiers, Rewards & Data Strategy
> Build #166 (2026-03-12) — Locked decisions from strategy session

## THE COMPLETE PRICING PYRAMID (FINAL)

| Tier | Monthly | Annual | Platform Fee | AI Access | Target |
|------|---------|--------|-------------|-----------|--------|
| **Free** | $0 | $0 | 50% of savings | Knowledge cards only | Casual travelers |
| **Travel+** | $9.99 | $79.99 | 35% of savings | Unlimited ANASTASiA AI | Frequent travelers |
| **B2B Starter** | $49 | — | 25% of savings | Knowledge cards + live AI | Solo agents, testing |
| **B2B Growth** | $99 | — | 20% of savings | Knowledge cards + live AI | Small agencies, real volume |
| **B2B Volume** | $199 | — | 15% (floor) | Knowledge cards + live AI | High-volume, multi-agent |
| **ANASTASiA Starter** | $299 | — | Negotiated | Full API + turnkey | Agencies wanting own brand |
| **ANASTASiA Pro** | $599 | — | Negotiated | Full API + priority | Large agencies |
| **Enterprise** | Custom | — | Custom | Everything | Airlines, consolidators |

### Pricing Rules
- NO MAXIMUM FEE CAP — $3 minimum, no maximum
- B2B MUST have competitive advantage over Travel+ (25% vs 35%)
- Travel+ at 35% = same as old "loyal subscriber" rate
- Each tier step must justify itself economically (fee savings > subscription cost increase)
- ANASTASiA API products ($299+) are SEPARATE from MYSTES B2B — different product entirely
- Enterprise = sales conversation only, no published price

### Pay-Per-Session AI ($2.99)
- For free users who hit complexity and don't want to subscribe
- Stripe one-time payment → 30-minute session window → 30 message cap
- Model: `AISession(user_id, paid_at, expires_at, messages_used)`
- This is the "free sample at Costco" — gateway to Travel+ subscription
- First session can be offered FREE as conversion hook

### Travel+ Annual Plan
- Monthly: $9.99/mo ($120/yr)
- Annual: $79.99/yr ($6.67/mo) — "Save 33%"
- Annual = guaranteed revenue + lower churn
- Worth the discount: 12-month subscribers book more trips, generate more fee revenue

---

## MYSTES REWARDS POINTS SYSTEM (FINAL MATH)

### Core Economics
- **Earn**: 10 MYSTES Points per $1 spent on total booking value
- **Redeem**: 1,000 points = $1 credit (1 point = $0.001)
- **Target rebate**: 7-15% of fee revenue returned as future credits
- B2B earns at 1x base (their benefit = fee reduction, not gamification)

### Earning Points

| Action | Points Earned |
|--------|--------------|
| Every $1 spent on bookings | 10 points (base) |
| First booking ever | 5,000 bonus |
| Refer a friend who books | 2,000 bonus |
| Leave a review after trip | 500 bonus |
| 2-vertical bundle (flight + hotel) | 1.5x multiplier on entire bundle |
| 3+ vertical bundle | 2.0x multiplier on entire bundle |

### Tier Multipliers

| Tier | Points Multiplier | Rationale |
|------|------------------|-----------|
| Free | 1x | Base engagement |
| Travel+ | 1.5x | Subscriber perk |
| B2B (all tiers) | 1x | Their benefit is fee reduction, not gamification |

### Real Booking Math

$800 flight, $200 savings found:

| Tier | Fee | Fee Revenue | Points Earned | Credit Value | % Rebate |
|------|-----|-------------|---------------|-------------|----------|
| Free | 50% | $100 | 8,000 | $8 | 8% |
| Travel+ | 35% | $70 | 12,000 | $12 | 15% |
| B2B Starter | 25% | $50 | 8,000 | $8 | 16% |
| B2B Growth | 20% | $40 | 8,000 | $8 | 20% |
| B2B Volume | 15% | $30 | 8,000 | $8 | 27% |

### Annual Projections

| User Type | Annual Bookings | Avg Booking | Points Earned | Credit Value |
|-----------|----------------|-------------|---------------|-------------|
| Casual (Free, 3 trips) | 3 | $600 | 18,000 | $18 |
| Frequent (Travel+, 12 trips) | 12 w/ bundles | $700-1,200 | ~192,000 | ~$192 |
| B2B Agency (Growth, 50/mo) | 600 | $650 | 3,900,000 | $3,900 |

### Redemption Caps (CRITICAL — Margin Protection)

| Vertical | Max Points Credit Per Booking |
|----------|------------------------------|
| Flights | 30% of booking value |
| Hotels | 30% of booking value |
| Activities/Experiences | **100% (full cover)** — commission waiver, costs $0 |
| Subscription month | 1 free month per quarter max |
| Minimum redemption | 1,000 points ($1) |

### Streak Bonuses

| Streak | Bonus |
|--------|-------|
| Book 2 months in a row | 500 bonus points |
| Book 3 months in a row | 1,000 bonus points |
| Book 6 months in a row | 5,000 bonus + "Gold" badge |
| Book 12 months in a row | 15,000 bonus + "Platinum" badge |

### Points Expiration

| Rule | Details |
|------|---------|
| Expiration window | 12 months from last EARNING activity |
| Reset trigger | ANY new booking resets clock on ALL points |
| Warnings | ANASTASiA alerts at 60, 30, 7, 1 days before expiry |
| Grace period | 30 days after expiry — reactivate with a booking |

### Point Gifting (In-App Only)

| Rule | Limit |
|------|-------|
| Who can gift | Any user with 5,000+ points balance |
| Who can receive | Any registered MYSTES user (by username/email) |
| Monthly send limit | 20,000 points per sender |
| Monthly receive limit | 50,000 points per recipient |
| Minimum gift | 1,000 points ($1) |
| Fee | None — free gifting |
| Verification | In-app dashboard only — NO email confirmation required |
| Notification | In-app notification to recipient + optional email alert |
| Family pooling | Shared household, max 5 members |
| Fraud detection | Flag bidirectional cycling between same accounts |

**Gifting flow**: Sender taps "Gift Points" → selects recipient → enters amount → confirms → instant delivery. Recipient sees in-app notification. Points land immediately.

**PROHIBITED**: Open trading, point selling, cash-out, point brokers.

### B2B Team Points Pool
- Agencies accumulate points across ALL bookings into shared team pool
- Can use for: subscription credits, client incentives, team agent rewards, booking discounts
- High-volume agencies earn free subscription months automatically
- Deepens lock-in: switching platforms = abandoning accrued rewards

### Points as Cross-Vertical Currency
- Points can be redeemed for experiences in ANY vertical
- "Free with points" = MYSTES waives its commission (costs $0 cash)
- Commission waiver on verticals user wouldn't have booked otherwise = free customer acquisition
- Example: User has flight points → redeem for free Viator tour → discovers activities vertical → books paid activities next trip

### Commission Waiver Economics

| Vertical | Typical Commission | "Free" Cost to MYSTES |
|----------|-------------------|----------------------|
| Viator experience ($50 tour) | ~8-15% = $4-7 | $0 cash, $4-7 forgone |
| Hotel upgrade (liteAPI) | ~8% margin | $0 cash, forgone margin |
| Travel insurance (SafetyWing) | ~20-30% = $10-15 | $0 cash, forgone |
| Airport transfer (Mozio) | ~10-15% | $0 cash, forgone |

Never spending real money. Trading forgone commission on bookings that wouldn't have happened otherwise.

---

## ANASTASiA CHAT ARCHITECTURE (TWO-TIER)

### Tier 1: Knowledge Card Concierge (Free — Zero Anthropic Cost)
- Chat bubble on every page
- NOT an AI — structured decision tree powered by knowledge cards
- Guided questions that route through verticals
- Manages guest profiles, builds bundles, cross-sells
- "What are you looking for?" → "Where?" → "When?" → "Who's going?" → "Want to add a hotel?"
- User thinks they're chatting. They're actually filling forms through conversation.
- Handles 95%+ of all interactions at zero API cost

### Tier 2: ANASTASiA AI (Subscribers — Live Claude Calls)
- Same chat interface, seamless handoff from knowledge cards
- Full conversational AI travel planner
- "Plan a 10-day trip to Italy for 4 people, mid-range, food and history focus"
- Claude uses knowledge cards as context (cheaper — fewer tokens)
- Builds multi-city itinerary with live pricing → one-click "book entire trip"
- ~$3-5/mo COGS per subscriber (cards do 80% of work)

### Handoff Logic
- Knowledge cards handle everything by default
- When query exceeds card capability → check if subscriber
- If subscriber → seamless escalation to live Claude
- If free user → "This kind of planning is available with Travel+" → natural upsell
- User FEELS the limitation → WANTS the upgrade → no hard sell

### Proactive Deal Engine (Knowledge Cards)
- ANASTASiA doesn't wait — generates personalized offers in dashboard
- "While you're shopping" bundle suggestions in sidebar
- "Deals For You" section based on browsing history + saved travelers
- Post-booking cross-sell: "Want me to find hotels for your flight to Rome?"
- All knowledge card operations — zero AI cost

---

## CUSTOMER INTELLIGENCE KNOWLEDGE CARDS (DATA ASSET)

### What ANASTASiA Learns About Customers
ANASTASiA builds knowledge cards on individual customers and agencies:

#### B2C Customer Cards
- Travel preferences (destinations, budget range, travel style)
- Booking patterns (lead time, day-of-week, seasonal trends)
- Price sensitivity (accept first result vs compare extensively)
- Cross-vertical behavior (flights-only vs multi-vertical)
- Group travel patterns (solo, couples, families, groups)
- Loyalty and engagement (streak, points accrual rate, feature usage)

#### B2B Agency Cards
- Route specialization (which corridors they book most)
- Volume patterns (monthly booking count, average transaction size)
- Client demographics (business vs leisure, domestic vs international)
- Vertical mix (flights-only vs multi-vertical agencies)
- Growth trajectory (increasing/decreasing volume over time)
- Response to pricing changes (elastic vs inelastic demand)

### Data Products (Anonymized & Aggregated)
This data is extremely valuable to:
- **Airlines**: route demand intelligence, pricing optimization, customer segmentation
- **Hotels**: market demand patterns, pricing strategy, seasonal trends
- **Tourism boards**: destination popularity, emerging trends, traveler demographics
- **Destination marketing orgs**: where travelers are going, what they're spending
- **Travel industry analysts/investors**: market intelligence reports

### How It's Built
- Knowledge cards generated as natural exhaust of operations (zero incremental cost)
- Cards are compiled intelligence — structured, queryable, not raw data
- Anonymized at the individual level, aggregated at the segment level
- Same architecture as cross-GDS intelligence but for consumer/agency behavior
- Data gets MORE valuable with scale — classic data moat

### Revenue Model for Data
- NOT a separate product — subscription add-on or premium report
- Could be bundled into Enterprise tier
- Or sold as industry intelligence reports
- Or used internally to improve ANASTASiA's own recommendations

---

## HOMEPAGE RESTRUCTURE (AGREED)

### Current State
- Flights IS the homepage (single-vertical mindset)
- Hotels at /hotels (just built, Build #166)

### New Architecture
- **New MYSTES Homepage (`/`)**: Brand launchpad with vertical cards grid
  - Big MYSTES brand moment (logo, tagline "Travel Intelligence")
  - Vertical cards: Flights, Hotels, Activities, Cars, Insurance (coming soon badges)
  - Each card clickable → routes to /flights, /hotels, etc.
  - Future: cached deal previews per vertical
- **Flights moves to `/flights`**: Same search UI, own URL, same pattern as /hotels
- **ANASTASiA chat bubble**: Floating on every page for all users
- **Nav updated**: "Flights" and "Hotels" as top-level links

### Build Order (Agreed)
1. New MYSTES homepage (vertical cards grid)
2. Extract flights to /flights
3. Knowledge card chat engine (concierge)
4. Chat bubble UI
5. Claude escalation layer (subscriber-only)

---

## IMPLEMENTATION MODELS

### RewardsPoints Model
```python
class RewardsPoints(db.Model):
    id, user_id, points_balance, lifetime_earned, current_streak_months,
    longest_streak_months, badge_level (none/gold/platinum)
```

### PointsTransaction Model
```python
class PointsTransaction(db.Model):
    id, user_id, amount (+/-), transaction_type (earn/redeem/bonus/expire),
    source (booking/referral/review/streak), booking_id (nullable),
    description, created_at
```

### AISession Model (Pay-Per-Session)
```python
class AISession(db.Model):
    id, user_id, stripe_payment_id, paid_at, expires_at,
    messages_used, max_messages (30), is_active
```

### CustomerIntelligence Model (Knowledge Card)
```python
class CustomerIntelligenceCard(db.Model):
    id, user_id (nullable for aggregate), card_type (individual/segment/aggregate),
    preferences_json, patterns_json, segments_json,
    last_updated, data_points_count
```

### PointGift Model
```python
class PointGift(db.Model):
    id, sender_id, recipient_id, amount, message (optional),
    created_at
```

### SavedItem Model (Wishlist)
```python
class SavedItem(db.Model):
    id, user_id, collection_id, vertical (flight/hotel/activity/car),
    item_data (JSON — route, hotel_id, dates, price, provider),
    price_at_save, current_price, price_alert_enabled,
    created_at, updated_at
```

### Collection Model (Wishlist Folders)
```python
class Collection(db.Model):
    id, user_id, name, cover_image (optional),
    is_shared, share_url (unique slug),
    created_at, updated_at
```

---

## WISHLIST / SAVED ITEMS SYSTEM (Airbnb Model)

### Save Anything From Any Vertical
- Heart/bookmark icon on every search result card
- Tap to save → pick existing collection or create new
- Collections = user-created folders: "Tokyo Trip 2027", "Anniversary Ideas", "Work Trips"

### What ANASTASiA Does With Saved Items (Knowledge Cards, Zero Cost)
- **Price tracking**: "Your saved Park Hyatt Tokyo dropped $40/night"
- **Availability alerts**: "Your saved villa in Santorini opened up for your dates"
- **Bundle suggestions**: "Package your 3 saved items for $2,340 — save $380"
- **Repeat booking**: "Rebook your Chicago work trip? Same hotel, same car, updated flights" — one tap
- **Seasonal nudges**: "Saved Tokyo flights cheapest in March — 6 weeks out is your sweet spot"

### Dashboard Layout (Travel Command Center)
- **Upcoming Trips** — booked itineraries with countdown
- **Saved Collections** — wishlist folders (heart icon)
- **Price Watches** — saved items with price tracking graphs
- **Travelers** — saved guest profiles (already at /travelers)
- **Rewards** — points balance, streak, next milestone, gift history
- **Booking History** — past trips with "rebook" button

### Retention Properties
- Saved items = sunk cost (won't switch to Expedia — research is here)
- Price alerts = weekly re-engagement (zero marketing spend)
- Shareable collections = referral engine ("Check out my Japan plan" → friend signs up)
- Saved items feed intelligence cards (even browsing intent = data)
- Repeat bookings = zero acquisition cost revenue
