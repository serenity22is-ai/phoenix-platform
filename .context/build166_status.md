# Build #166 (2026-03-12) — Hotels UI + Full B2C/B2B Strategy Session

## Hotels Vertical UI (COMPLETE)
- **`routes_hotels.py`** — COMPLETE REWRITE of HOTELS_SEARCH_CONTENT
  - Premium MYSTES glass morphism design matching flights aesthetic
  - Cinzel "HOTELS" header, Outfit body text
  - Glass morphism search card (blur, dark bg, purple accents)
  - Star rating toggle chips, guest/room selectors
  - Skeleton loading animation during search
  - Sort controls (price low→high, high→low, best savings)
  - Free cancellation filter chip
  - Hotel result cards: image area, room type, tags, MYSTES price, Google price strikethrough, savings badge, deal badges
  - API response now includes `google_price`, `user_savings`, `savings_pct`
  - Deep link support via URL params (?city=PAR&checkin=...)
- **`templates/base_template.py`** — "Hotels" nav link added (authenticated + non-authenticated)
- **`models.py`** — `vertical_hotels` feature flag default changed to `True`
- **Feature flag enabled** in production DB
- **Tests**: 72 passed (29 integration + 43 API client), 7 hotel-specific all passing

## Strategy Session — Travel+ Subscription (LOCKED DECISIONS)
- **Travel+ B2C subscription**: $9.99/mo ($79.99/yr annual), 35% platform fee, unlimited ANASTASiA AI
- **Pay-per-session AI**: $2.99 for free users, 30-min window, 30 message cap
- **B2B 3-tier pricing**:
  - Starter: $49/mo, 25%
  - Growth: $99/mo, 20%
  - Volume: $199/mo, 15% (floor)
- **B2B MUST beat Travel+** on pricing — this is non-negotiable

## Strategy Session — MYSTES Rewards Points (LOCKED DECISIONS)
- 10 points per $1 spent on bookings
- Tier multipliers: Free=1x, Travel+=1.5x, B2B=2x/2.5x/3x
- Redemption: booking credits, free subscription months, extra % discounts
- Streak bonuses: Gold (6mo), Platinum (12mo)
- **Cross-vertical currency**: points redeem for experiences in ANY vertical
- **Commission waiver model**: "free with points" = waive commission, $0 actual cost
- B2B team points pool for agencies

## Strategy Session — ANASTASiA Chat Architecture (LOCKED DECISIONS)
- **Two-tier chat**: Knowledge cards (free) + Live Claude (subscribers)
- **Chat bubble on every page**: knowledge card concierge, zero API cost
- **Proactive deal engine**: dashboard personalized offers, cross-sell bundles
- **Seamless handoff**: cards → Claude when complexity exceeds cards + user is subscriber
- **Natural upsell**: free users hit limitation → offered Travel+ subscription

## Strategy Session — Customer Intelligence (LOCKED DECISIONS)
- ANASTASiA builds knowledge cards on individual customers AND agencies
- B2C cards: preferences, patterns, price sensitivity, cross-vertical behavior
- B2B cards: route specialization, volume patterns, growth trajectory
- Anonymized + aggregated = sellable data products
- Buyers: airlines, hotels, tourism boards, analysts, investors
- Natural exhaust of operations — zero incremental cost
- Data moat: gets more valuable with scale

## Strategy Session — Homepage Restructure (AGREED)
- Flights moves OFF homepage to `/flights`
- New MYSTES homepage: brand launchpad + vertical cards grid
- ANASTASiA chat bubble floating on every page
- Build order: homepage → extract flights → chat engine → bubble UI → Claude escalation

## Files Changed
- `routes_hotels.py` — Complete UI rewrite
- `templates/base_template.py` — Hotels nav link
- `models.py` — vertical_hotels default True

## Full Strategy Reference
- See `memory/travel_plus_and_rewards.md` for complete pricing, rewards, data strategy
- See `memory/endgame_strategy.md` for industry capture vision
- See `memory/business_pyramid.md` for previous pyramid (now superseded by travel_plus_and_rewards.md)

## Strategy Session — Trip Planner (LOCKED DECISIONS)
- **Collaborative trip planning**: shared workspace, multi-destination, multi-member
- **Friends system**: add friends in dashboard, suggest trips, activity feed
- **Roles**: Owner (subscriber) / Editor (member) / Viewer
- **Shared cart with flexible split**: even/custom/single-payer/percentage
- **Assignment vs Payment separation**: user_id (who uses) vs payer_id (who pays)
- **Group discounting**: ANASTASiA surfaces group rates automatically
- **Business use case**: corporate travel, local events, dinner reservations, expense receipts
- **Non-member referral**: invite link → create account to join → 2,000 pts referral bonus
- **Decline/partial refund**: members can back out, ANASTASiA recalculates splits
- **Reusable plans**: repeat trips, add members, publish as public templates
- **Receipt management**: structured receipts, PDF export, expense categories
- See `memory/trip_planner.md` for full architecture

## Strategy Session — Guest Points Escrow (LOCKED)
- Guest bookings earn points in escrow (tied to email)
- 90-day claim window to create account and redeem
- Reminder emails at 30/60/80 days
- Points expire at 90 days if unclaimed (zero liability)
- "PayPal growth model" — claim your money by signing up

## Strategy Session — Point Gifting (LOCKED)
- Any member → any member, in-app only (NO email confirmation)
- 20K/month send limit, 50K/month receive limit
- 5,000+ balance required to gift, 1,000 minimum gift
- No trading, no selling, no cash-out
- Family pooling: max 5 members in household
- Fraud detection: flag bidirectional cycling

## CONTINUE FROM HERE
- Build new MYSTES homepage with vertical cards
- Extract flights to /flights
- Build knowledge card chat engine (ANASTASiA concierge)
- Wire rewards points models (RewardsPoints, PointsTransaction, PointGift)
- Wire trip planner models (TripPlan, TripMember, TripItem, TripCart, TripCartAssignment)
- Wire wishlist models (SavedItem, Collection)
- Update payments.py with new tier structure (Travel+ $9.99, B2B $49/$99/$199)
- Build Trip Planner UI
- Build Friends system
- Build Receipt management
