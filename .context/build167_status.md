# Build #167 (2026-03-12) — Feature Foundation: Models, Pricing, Homepage, Flights Extraction

## Summary
Data foundation for all Build #166 strategy decisions. 16 new DB models, pricing constants, new homepage, flights extraction.

## What Was Built

### Phase 1A: 16 New Database Models (`models.py`)
1. **Subscription** — Travel+ and B2B subscription tracking (tier, status, billing_cycle, Stripe IDs)
2. **AISession** — Pay-per-session AI ($2.99, 30-min window, 30 message cap)
3. **RewardsAccount** — Points balance, streaks, badges (one per user)
4. **PointsTransaction** — Ledger of all point movements (earn/redeem/bonus/expire/gift)
5. **PointGift** — Gift transfers between members (sender/recipient/amount/message)
6. **PointsEscrow** — Guest booking point holds (90-day claim window, reminder flags)
7. **TripPlan** — Collaborative planning workspace (name, status, destinations, template support)
8. **TripMember** — Trip membership (role: owner/editor/viewer, budget cap, RSVP)
9. **TripItem** — Items in trip (vertical, data, alternatives, voting)
10. **TripCart** — Checkout state (total, per-person breakdown)
11. **TripCartAssignment** — Split payment (user_id vs payer_id, split method, amount)
12. **TripReceipt** — Structured receipts (MYS-YYYY-NNNNN, PDF export, company name)
13. **Friendship** — Social graph (requester/addressee, status, unique constraint)
14. **Collection** — Wishlist folders (shareable via slug)
15. **SavedItem** — Saved search results (price tracking, alerts)
16. **LocalBusiness** — Restaurant/venue listings (free, 15% booking commission)

### Phase 1B: Feature Flags + Pricing
- **6 new feature flags**: travel_plus (enabled), rewards_points, trip_planner, wishlist, friends_system, local_businesses
- **20+ pricing constants** in config.py: Travel+ ($9.99/$79.99), B2B Growth ($99/20%), B2B Volume ($199/15%), AI session ($2.99), points system params, local business commission
- **payments.py**: `get_fee_percent()` now checks Subscription model for Travel+ tier
- **commercial.py**: Tiers renamed (professional→growth, enterprise→volume), partner tier removed, 15% floor at volume

### Phase 2A: Flights Extraction
- **`routes_flights.py` NEW** — Flights search at `/flights` (extracted from homepage)
- Same glass morphism UI, trip type toggle, passenger selectors
- Registered in server.py alongside hotel routes
- Feature-flagged behind `vertical_flights`

### Phase 2B: New MYSTES Homepage
- **`templates/base_template.py`**: HOME_HERO replaced with brand launchpad
  - Large MYSTES brand moment (Cinzel, "Travel Intelligence" tagline)
  - 4 vertical cards grid: Flights (live), Hotels (live), Activities (coming soon), Cars (coming soon)
  - "Powered by ANASTASiA" badge
  - Glass morphism design matching existing aesthetic
- **Nav updated**: Flights + Hotels as top-level links, AI Search moved to More dropdown

### Phase 2C: Tests
- **18 new tests** covering all models, page loads, feature flags, pricing
- **120 passed, 1 pre-existing failure (unrelated), 78 skipped**

## Strategic Note: Feature Tools = Sellable Verticals
- Every feature tool (Trip Planner, Rewards, Wishlist, Friends, Receipts, Local Business) is a **pluggable module**
- Each can be sold separately in ANASTASiA turnkey tiers: Starter (core only) → Pro (+ tools) → Enterprise (everything)
- Models are designed to be portable across any ANASTASiA-powered deployment

## Files Changed
| File | Change |
|------|--------|
| `models.py` | +16 new models (~300 LOC), +7 feature flags |
| `config.py` | +20 pricing constants |
| `payments.py` | `get_fee_percent()` — Subscription awareness |
| `commercial.py` | Tiers renamed: professional→growth, enterprise→volume, partner removed |
| `templates/base_template.py` | HOME_HERO → brand launchpad, nav updated |
| `server.py` | Flight routes registration, +6 feature flag context vars |
| `routes_flights.py` | **NEW** — Flights page at /flights |
| `tests/test_integration.py` | +18 new tests, fixture initializes flags |

## Tests
- 120 passed, 1 pre-existing failure, 78 skipped
- All 18 Build #167 tests passing

## CONTINUE FROM HERE
- Start server: `python3 server.py` → visit localhost:5001 to see new homepage
- Build Rewards UI (dashboard section: balance, streaks, transactions, gifting)
- Build Wishlist UI (heart icons on search results, collection management)
- Build Trip Planner UI (create plan, invite members, add items, split checkout)
- Build Friends system UI (add friends, activity feed)
- Build ANASTASiA chat bubble (knowledge card concierge)
- Wire Stripe products for Travel+ ($9.99 monthly, $79.99 annual)
- Wire Stripe products for B2B Growth ($99) and Volume ($199)
