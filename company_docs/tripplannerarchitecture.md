# MYSTES Trip Planner & Social Platform Architecture
## Design Session — April 15-16, 2026

### Session Context
This architecture was designed in a multi-round discussion between the founder and Claude (Build #219-233 scope). Starting from Builds #211-218 (production readiness), the conversation evolved into designing the most ambitious feature set in MYSTES history: a collaborative trip planner, social travel network, event platform, and universal sharing system — all built on top of the existing OTA with flight arbitrage as the sole profit center.

---

## 1. UNIVERSAL SHARE SYSTEM: `/i/<token>`

### Core Concept
One short URL pattern that resolves to different content types. Every shareable surface in MYSTES uses the same `/i/<token>` pattern.

### InviteLink Model
```
InviteLink
├── token (unique, 8-10 chars, URL-safe)
├── link_type (flight, hotel, itinerary, trip_invite, cart_checkout,
│              collection, referral, price_alert, wishlist,
│              booking_confirm, activity, car, settle_up,
│              trip_view, event_registration)
├── object_id (polymorphic — deal_id, trip_id, cart_id, etc.)
├── sender_user_id
├── recipient_email (optional — for targeted invites)
├── permissions (view_only, can_pay, can_join, can_adopt)
├── show_prices (boolean, default True)
├── message (optional personal note)
├── referral_code (auto-embedded — user's own or B2B upstream)
├── upstream_b2b_code (if user originally booked through a B2B)
├── click_count, unique_visitors, conversions
├── expires_at (nullable)
├── is_active (can be revoked)
├── created_at
```

### Shareable Surfaces
| link_type | What it shows | Guest can... | CTA |
|-----------|--------------|-------------|-----|
| trip_invite | Full itinerary + guest's assignments | View, RSVP | "Join Trip" (pre-filled signup) |
| trip_view | Read-only itinerary (no guest assignment) | View only | "Create Account to Plan Yours" |
| cart_checkout | Itemized cart + message + pay button | View + Pay | "Pay Now" (no account needed) |
| itinerary_share | Trip timeline with live search buttons | View, click to search | "Create Account to Save" |
| flight | Single flight card | View | "Search This Route" |
| hotel | Single hotel card | View | "Check Availability" |
| collection | Saved flights gallery | Browse | "Create Account to Save" |
| settle_up | Balance owed + pay button | View + Pay | "Pay Your Share" |
| referral | Discount landing page | Browse | "Search Flights with Discount" |
| price_alert | Route + current price | View | "Create Account for Alerts" |
| event_registration | Event details + ticket tiers | View + Register | "Register + Pay" |

### OG Meta Tags
Every `/i/<token>` URL generates rich OG meta for social previews:
- Destination photo
- Trip/event name
- Dates + traveler count
- Savings data (if flight)
- "Book this trip on MYSTES" CTA

### Referral Attribution Chain
Every link carries up to 2-level attribution:
```
mystes.app/i/abc123?ref=alexsmith&src=b2b_travelmax

- ref=alexsmith = direct sharer (earns points)
- src=b2b_travelmax = upstream B2B account (earns commission)
```
NOT MLM. Exactly 2 levels max. B2B seeded the customer, customer shared organically.

---

## 2. LIVE ITINERARY BUILDER

### Core Innovation: Save Search Queries, Not Results
An itinerary item stores the SEARCH PARAMETERS, not just a static result. Click "Refresh Prices" to re-execute against live inventory.

### ItineraryItem Model
```
ItineraryItem
├── id, trip_id
├── item_type (flight, hotel, activity, car, restaurant, custom)
├── scope (trip, party, individual, custom)
├── scope_party_id (if scope=party)
├── scope_guest_ids_json (if scope=custom — e.g. mom+aunt spa)
├── position (ordering within trip timeline)
├── date, start_time, end_time
├── search_params_json  <-- THE KEY FIELD
│   {origin: "LAX", destination: "NRT", date: "2027-06-05",
│    return_date: "2027-06-12", passengers: 2, cabin: "economy"}
├── cached_deal_id (last search result — may be stale)
├── cached_price_usd
├── cached_at (when last sourced)
├── status (suggested, approved, locked, booked, cancelled)
├── booking_source ('mystes' | 'external' | 'imported')
├── booking_mode (group, party, individual)
├── booking_id (after booking)
├── suggested_by_guest_id
├── assigned_to_guest_id
├── notes
├── is_private (hidden from non-assignees)
├── created_at
```

### External Booking Integration
Users can link Airbnb, externally-booked hotels, or any outside booking into the trip planner:
- Type, Name, Address, Check-in/Check-out, Confirmation #, Cost (optional), Link, Notes
- booking_source = 'external'
- Planner schedules around external items
- Subtle "Compare on MYSTES" for competing verticals (gentle upsell)
- External items appear in itinerary timeline, narrative pitch, and settlement

### Batch Live Reprice
"Check All Prices" button re-executes all search_params in parallel, returns updated totals.
Shows: "3 of 7 items booked | Estimated remaining: $1,400"

### Conflict Detection
- Time overlap warning
- Absent guest warning (guest hasn't arrived yet or already departed)
- Travel time warnings (optional)

---

## 3. SUB-PARTY MODEL

### Core Concept
A trip isn't flat — it has nested groups (families, couples, payment units).

```
Example: CANCUN TRIP 2027
├── The Smith Family (payer: Dad)
│   ├── Dad (June 1-10)
│   ├── Mom (June 1-10)
│   └── Daughter (June 1-12 <-- stays extra)
├── Jeff & Lisa (payer: Jeff)
│   ├── Uncle Jeff (June 2-8 <-- arrives late, leaves early)
│   └── Aunt Lisa (June 2-8)
└── Solo Marco (payer: himself)
    └── Marco (June 1-10)
```

### TripParty Model
```
TripParty
├── id, trip_id
├── name ("The Smiths")
├── party_type ('attendee' | 'sponsor')
├── payer_guest_id -> TripGuest
├── budget_usd (optional)
├── created_at
```

### TripGuest Model
```
TripGuest
├── id, trip_id
├── party_id -> TripParty (nullable)
├── user_id (nullable — linked if MYSTES member)
├── display_name
├── email, phone (nullable)
├── role (owner | admin | editor | viewer | payer)
├── arrival_date, departure_date (personal dates, may differ from trip)
├── rsvp_status (invited, viewed, attending, declined, maybe, waitlisted, expired)
├── payment_status
├── payment_deadline_override
├── invite_token (for /i/<token>)
├── ticket_tier_id (events only)
├── plus_one_of_guest_id (events only)
├── checked_in_at (events only)
├── nationality (for visa warnings)
├── custom_fields_json
├── created_at
```

### Flexible Dates Per Guest
Each guest has independent arrival_date and departure_date. The itinerary timeline shows who's present on each day. Items can only be assigned to guests present on that date.

### Scoping Model
| Scope | Who's involved | Who pays | Example |
|-------|---------------|----------|---------|
| trip | All guests present on that date | Split across all parties | Group dinner, shared Airbnb |
| party | One party's members | That party's payer | Family hotel room |
| individual | One person | Their party's payer | Spa appointment |
| custom | Arbitrary mix of guests | Split across their parties | Mom + Aunt Lisa spa |

### Autonomous Additions
- Personal items = instant, no approval
- Party items = party payer approves
- Group items = group vote
- Custom items = invitation to involved guests

---

## 4. SETTLEMENT ENGINE

### Per-Party Cost Breakdown
At checkout, the system calculates who owes what based on item scopes and party assignments.

### Group Item Split Modes
- Equal by party (each party pays 1/n)
- Per capita (by headcount)
- Custom (owner sets percentages)

### Payment Modes
- One person books all (trip splitting for reimbursement — Build #209)
- Each person books their own
- Mixed (one person books hotel, everyone books own flights)

---

## 5. COLLABORATIVE MODE

### Voting System
```
ItineraryVote
├── item_id -> ItineraryItem
├── guest_id -> TripGuest
├── vote (up, down, neutral)
├── comment (optional)
├── created_at
```

### Item-Level Comments (Threaded)
```
ItemComment
├── item_id -> ItineraryItem
├── guest_id -> TripGuest
├── body
├── parent_comment_id (threading)
├── created_at
```

### Suggestion Flow
Any guest can suggest items. Group suggestions go to vote queue. Majority approves. Owner can override.

---

## 6. MANAGED MODE

### Concept
One admin builds, guests can ONLY view + RSVP + pay. Used for school trips, corporate events, weddings.

### When mode = 'managed':
- No suggest, vote, or add personal items
- Admin gets roster dashboard
- Admin sends announcements (one-to-many, no replies)
- Guest actions: View, RSVP, Pay, Submit info

### TripAnnouncement Model
```
TripAnnouncement
├── trip_id
├── sender_guest_id (admin)
├── body
├── audience (all, confirmed_only, pending_only)
├── delivery_method (in_app, email, both)
├── sent_at
```

### Capacity + Waitlists
```
Trip additions:
├── capacity (nullable — null = unlimited)
├── waitlist_enabled
├── registration_deadline
├── payment_deadline
```

### Payment Deadlines + Auto-Cancel
If payment_deadline passes -> guest status = "expired" -> spot opens -> waitlist notified.

---

## 7. EVENT SYSTEM

### Core: Events = Managed Trips + Ticketing
```
Trip additions for events:
├── trip_type ('trip' | 'event')
├── event_name
├── venue_name, venue_address, venue_url
├── event_description
├── registration_type ('invite_only' | 'public')
├── ticket_tiers_json
├── organizer_stripe_connect_id
```

### TicketTier Model
```
TicketTier
├── trip_id
├── name ("Full Weekend Package")
├── description
├── price_usd
├── capacity (nullable)
├── includes_travel (boolean)
├── includes_accommodation (boolean)
├── included_items_json
├── position, sold_count, is_active
```

### Event Types Covered
- Destination weddings, corporate retreats, high school reunions
- Conferences/seminars, birthday parties, sports tournaments
- Family reunions, local parties, fundraiser galas
- Recurring events (monthly meetups, quarterly retreats)

### Revenue Split: Organizer vs MYSTES
- Event ticket revenue -> organizer via Stripe Connect (MYSTES takes $0 on ticket)
- Travel booking revenue -> MYSTES via flight arbitrage
- No per-ticket platform fee — event hosting included in Travel+ ($9.99/mo)

### EventSeries Model (Recurring Events)
```
EventSeries
├── name, organizer_user_id, frequency
├── template_trip_id, auto_create_next
├── series_page_url
```

### Plus-Ones
```
TripGuest.plus_one_of_guest_id — links to primary guest
```

### QR Check-In (reuses Build #206)
Organizer scans attendee QR -> marks checked_in_at -> dashboard shows "45/60 checked in"

### Tier Gating
| Tier | Can host events? | Payment collection? |
|------|-----------------|-------------------|
| Free | No | No |
| Travel+ ($9.99) | Yes | Yes, via Stripe Connect |
| B2B ($49-199) | Yes | Yes + referral commission |

---

## 8. GUEST INFO COLLECTION

### TripGuestInfo Model
```
TripGuestInfo
├── guest_id -> TripGuest
├── field_key ("emergency_contact", "dietary", "passport_no", "tshirt_size")
├── field_value
├── submitted_at
```

Admin defines required fields. Invite link includes form. Guest fills out alongside RSVP/payment.

---

## 9. NARRATIVE PITCH GENERATOR

### Template-Based, ZERO AI Cost
Personalized per-guest narrative using variable substitution from itinerary data:

What Dad sees:
"You, Mom, and Daughter arrive in Cancun on Saturday afternoon. Check into your oceanfront suite at the Grand Hyatt..."

What Jeff sees:
"You and Lisa arrive in Cancun on Sunday and meet up with the Smiths and Marco at a welcome dinner..."

### Data Sources (all from existing models):
- Guest names from TripGuest
- Destination from flight ItineraryItem
- Hotel name/description from hotel deal
- Activity names + times from activity items
- Dates computed from flight departure dates

### Template Types:
15-20 narrative templates per item type (arrival, hotel checkin, activity, free day, departure), randomized slightly, stitched into a day-by-day story.

---

## 10. SHARED CART (PAY-FOR-SOMEONE)

### SharedCart Model
```
SharedCart
├── cart_token
├── builder_user_id
├── title ("Summer Trip to Japan")
├── message ("Mom, can you pay for this?")
├── items_json (snapshot or references to ItineraryItems)
├── reprice_at_checkout (boolean, default true)
├── total_estimated_usd
├── payment_status (draft, shared, repriced, paid, expired)
├── payer_email, payer_name
├── stripe_session_id
├── paid_at, expires_at
```

### Guest Payment (No Account Required)
Parent/payer clicks link -> sees cart -> pays via Stripe -> no MYSTES account needed.
Booking executes under the builder's account. Payer gets receipt + soft CTA to create account.

---

## 11. SOCIAL LAYER

### TravelCompanion (Bidirectional Friendship)
```
TravelCompanion
├── user_id, companion_user_id
├── nickname ("Mom", "College Crew - Marcus")
├── status (pending, accepted, blocked)
├── trips_together_count (auto-incremented)
├── first_trip_together_at
├── created_at
```

### UserFollow (Unidirectional)
```
UserFollow
├── follower_user_id
├── followed_user_id
├── created_at
```

### TravelerProfile (Saved Details)
```
TravelerProfile
├── user_id
├── legal_first_name, legal_last_name
├── date_of_birth
├── passport_number, passport_expiry, passport_country
├── known_traveler_number (TSA PreCheck / Global Entry)
├── seat_preference (window, middle, aisle)
├── meal_preference, dietary_restrictions
├── emergency_contact_name, emergency_contact_phone
├── frequent_flyer_json ({"united": "MP12345", "delta": "SM67890"})
```

### Public Profile: mystes.app/@username
- Travel map (countries highlighted)
- Travel stats (countries, flights, savings)
- Badges (Globe Trotter, Deal Hunter, etc.)
- Trip posts (shareable travel stories)
- Reviews received
- Referral link embedded in every interaction

### TripPost Model
```
TripPost
├── trip_id, user_id
├── title, cover_photo_url, summary_text
├── highlight_items_json, photos_json, tips_json
├── visibility (public, companions_only, private)
├── show_prices (boolean)
├── referral_code (auto-embedded)
├── views_count, clones_count, bookings_count
├── created_at
```

### TripPhoto Model
```
TripPhoto
├── trip_post_id
├── itinerary_item_id (nullable)
├── photo_url, thumbnail_url
├── caption
├── uploaded_by_guest_id
├── position, created_at
```

### ProfileReview Model
```
ProfileReview
├── reviewer_user_id (or guest info)
├── reviewed_user_id (or reviewed_account_id for B2B)
├── trip_post_id (nullable)
├── booking_id (verified booking required)
├── rating (1-5), body
├── is_verified_booking (boolean)
├── is_public, created_at
```

### Travel Stats + Gamification
```
Countries visited, continents, flights booked, total saved, companions, trips
Badges: Globe Trotter, Deal Hunter, Social Butterfly, Trip Planner Pro, etc.
```

### Discovery Feed
- Trips by people you follow
- Trending destinations (aggregated from booking data)
- "Book Similar" clones any public trip

### Scrapbook / Travel Map
- Interactive world map with pins per trip
- Timeline view of all trips
- Shareable map image for social media
- Each pin links to Trip Post

---

## 12. TRIP LIFECYCLE

| Phase | What users see | Value |
|-------|---------------|-------|
| Planning | Search params, estimated prices, suggestions, votes | Dream + decide |
| Booking | Live prices, checkout buttons, payment tracking | Commit + pay |
| Pre-trip | Confirmation numbers, check-in links, document reminders | Prepare |
| Active trip | Day-by-day schedule, today's events highlighted | Navigate |
| Post-trip | Receipts, review prompts, "Trip Complete" badge | Remember + review |

### Trip Cloning / Reuse
"Save as template for next year" -> clones trip with same crew + search params, shifted dates.
"Fork this trip" -> copy a public trip into your own planner.

---

## 13. ECONOMICS: FLIGHTS-ONLY PROFIT MODEL

### Revenue Sources
| Vertical | Revenue | Strategy |
|----------|---------|----------|
| Flights | Arbitrage margin (POS differential) | ONLY profit center |
| Hotels | Break-even (cover Duffel API costs) | Engagement driver |
| Activities | Viator/partner commission, NO markup | Same price as direct |
| Events | $0 on tickets | User acquisition |
| External (Airbnb) | $0 | Keeps users in planner |

### Discount Rules (CRITICAL -- LOCKED)
- Discounts can ONLY come from arbitrage savings
- NO out-of-pocket subsidies
- NO markup on non-flight verticals
- If no arbitrage exists on a route, no discount offered
- B2B referral discounts carved FROM MYSTES fee, not additional funds

### Price Comparison via SerpAPI
- US baseline prices from Google Flights (SerpAPI)
- Shown in: search results, knowledge cards, trip posts, social shares, Google reviews
- "MYSTES: $1,050 | Google Flights: $1,420 | YOU SAVE: $370 (26%)"

### Knowledge Card Flywheel
```
User books -> ANASTASiA records route, POS, spread, timing
-> Knowledge card updates (rolling averages, confidence scores)
-> Next user gets better arbitrage routing
-> Zero AI cost (cards are compiled data, not live AI)
```

---

## 14. PLATFORM STRATEGY: STANDALONE

### Decision: Build own platform, NOT integrate into Facebook/X
Reasons:
1. Platform dependency risk (API changes, deplatforming)
2. Data ownership (user data, route intelligence on OUR servers)
3. Revenue control (no revenue sharing)
4. Feature freedom (not limited to third-party APIs)
5. Defensibility (they can copy UX, not the engine)

### What can't be copied:
- ANASTASiA knowledge cards (proprietary route intelligence)
- Proxy POS arbitrage infrastructure
- Credential routing network (APAi marketplace)
- Compounding data flywheel

### Social platforms as distribution:
- Share links with rich OG meta previews
- Deep links bring users BACK to MYSTES
- Every shared card = mini-ad with real savings data

---

## 15. NOTIFICATION INTELLIGENCE

| Event | Who | When |
|-------|-----|------|
| New item suggested | All members | Immediately |
| Vote threshold reached | Suggestor | When decided |
| Price drop on item | All members | Within 1 hour |
| Price increase | Owner only | Within 1 hour |
| Payment received | Admin only | Immediately |
| Payment deadline approaching | Unpaid guests | 7d, 3d, 1d before |
| Trip countdown | All members | 30d, 7d, 1d before |
| Companion added you | The added person | Immediately |

---

## 16. GUEST ACCESS RULES

| Action | Guest | Free | Travel+ | B2B |
|--------|-------|------|---------|-----|
| View shared content | Yes | Yes | Yes | Yes |
| Search flights | Yes | Yes | Yes | Yes |
| Book a flight | No | Yes | Yes | Yes |
| Pay a cart link | Yes (no account) | Yes | Yes | Yes |
| Join a trip | No (signup prompt) | Yes | Yes | Yes |
| Create trips | No | Yes (collab only, <=10) | Yes (all modes) | Yes |
| Host events | No | No | Yes | Yes |
| Collect payments | No | No | Yes (Stripe Connect) | Yes |
| Share trip posts | No | Yes | Yes | Yes |
| Set price alerts | No | Yes | Yes | Yes |

---

## 17. B2B REFERRAL CHAIN IN SOCIAL SHARING

```
B2B subscriber -> gives referral code to Customer A
Customer A books -> gets discounted fee rate
Customer A shares Trip Post on Instagram
Trip Post carries Customer A's ref + B2B upstream code
Customer B clicks -> books through MYSTES
Revenue: Customer A gets points, B2B gets commission, MYSTES gets arbitrage
```

Every happy customer becomes an unpaid marketing agent. The B2B's customers create content that carries the B2B's discount deeper into social networks. Free marketing from genuine experiences.

---

## 18. COMPLETE MODEL REFERENCE

### Social Layer
- TravelCompanion — bidirectional travel friendship
- UserFollow — unidirectional follow for feed
- TravelerProfile — passport, preferences, frequent flyer
- TravelStats — computed from booking data

### Content Layer
- TripPost — shareable trip summary with photos, tips
- TripPhoto — uploaded photos tied to items
- ProfileReview — verified booking reviews

### Trip Layer
- Trip — name, mode (collaborative/managed), type (trip/event), dates, budget
- TripParty — sub-groups with payer
- TripGuest — members with roles, dates, RSVP, payment
- TripGuestInfo — extensible field collection

### Itinerary Layer
- ItineraryItem — typed, scoped, search params OR external booking
- ItineraryVote — up/down per guest
- ItemComment — threaded per-item discussion
- TripAnnouncement — admin broadcasts

### Event Layer
- TicketTier — multiple pricing levels per event
- EventSeries — recurring events

### Sharing Layer
- InviteLink — universal /i/<token>
- SharedCart — pay-for-someone checkout

---

## 19. BUILD PLAN (Builds #219-233)

| Build | Feature | Models |
|-------|---------|--------|
| #219 | InviteLink + /i/<token> resolver + OG meta | InviteLink |
| #220 | TravelCompanion + TravelerProfile | TravelCompanion, TravelerProfile |
| #221 | TripParty + TripGuest + sub-parties + roles | TripParty, TripGuest |
| #222 | ItineraryItem + search params + external bookings | ItineraryItem |
| #223 | Scoping engine + settlement calculator | -- |
| #224 | Voting + comments + suggestions | ItineraryVote, ItemComment |
| #225 | Managed mode + roster + capacity + waitlist + deadlines | TripGuestInfo, TripAnnouncement |
| #226 | TicketTier + event mode + RSVP + Stripe Connect payout | TicketTier |
| #227 | Guest info collection + plus-ones + QR check-in | -- |
| #228 | Narrative pitch generator + per-guest personalization | -- |
| #229 | SharedCart + guest Stripe payment | SharedCart |
| #230 | TripPost + photos + scrapbook + trip cloning | TripPost, TripPhoto |
| #231 | Public profiles + travel map + stats + badges + follows | UserFollow, TravelStats |
| #232 | ProfileReview + verified reviews + B2B public pages | ProfileReview |
| #233 | Referral attribution chain + conversion tracking + rewards | -- |

### Dependency Order
- #219-225: Trip planner engine (functional MVP)
- #226-227: Event layer
- #228-229: Sharing + carts
- #230-232: Social network
- #233: Attribution + analytics

---

## 20. KEY ARCHITECTURAL DECISIONS (LOCKED)

1. Events are Trips with trip_type='event', NOT a separate system
2. Discounts ONLY from arbitrage — no out-of-pocket subsidies
3. No markup on hotels, activities, events — flights ONLY profit center
4. Travel+ ($9.99/mo) unlocks event hosting + payment collection
5. Standalone platform — no embedding in Facebook/X
6. Template-based narrative pitch — ZERO AI cost
7. 2-level referral attribution max — NOT MLM
8. External booking import supported — planner is the coordination hub regardless of booking source
9. SerpAPI for US baseline price comparison — shown everywhere
10. Knowledge cards power route intelligence at zero runtime AI cost
11. "Build anywhere, book cheaper through us" = actual product positioning
12. User-sourced research reduces MYSTES search costs to near-zero at scale
13. Browser extension = future distribution channel (not MVP)
14. 3 free arbitrage checks/month for free tier, unlimited for Travel+
15. Deal feed generated from cached knowledge cards (Scott's Cheap Flights model)

---

## 21. "ARBITRATE MY TRIP" MODEL

### Core Insight
The real product is NOT "search on MYSTES." It's **"build your trip anywhere you want, then book cheaper through us."** Users already know how to use Google Flights, Airbnb, Booking.com. We don't compete with their search UX — we compete on PRICE after they've already decided what they want.

### How It Works
1. **User builds trip anywhere** — Google Flights, Airbnb, Booking.com, Expedia, word of mouth, or within MYSTES UI
2. **User imports selections into MYSTES trip planner** — manual entry, URL paste, or in-app search
3. **MYSTES arbitrates every item** — proxy search for flights (multi-POS), Duffel for hotels (wholesale), activities at commission
4. **User sees side-by-side** — their original price vs MYSTES arbitrage price
5. **User books cheaper items through MYSTES** — we route via proxy or Duffel
6. **Items without savings stay as external bookings** — still tracked in trip planner for coordination

### Import Methods
- **Manual entry**: User types flight details (route, dates, airline, price they found)
- **URL paste**: User pastes Google Flights or Booking.com URL, we parse the itinerary
- **In-app search**: User searches within MYSTES using Google SerpAPI + Duffel + proxy
- **Browser extension** (future): Overlay on Google Flights showing "Save $X with MYSTES"

### Why This Wins
- **Zero friction adoption** — users don't change their research behavior
- **Provable value** — side-by-side price comparison, not vague promises
- **Cost efficiency** — user already did the research, we only run targeted arbitrage checks
- **Network effect** — every import teaches ANASTASiA about routes, prices, and seasonality
- **Conversion driver** — "you're already planning this trip, click here to save $374"

---

## 22. TRAVEL+ GATING STRATEGY ($9.99/mo)

### Free Tier (Guest + Free accounts)
- **Unlimited**: Trip planning, sharing, social features, external booking import, itinerary coordination
- **3 arbitrage checks/month**: User can arbitrate 3 items for free to prove value
- **Standard fees**: Guest=50%, Free=45% on any bookings
- **No deal alerts**: Cannot subscribe to proactive deal notifications

### Travel+ ($9.99/mo)
- **Unlimited arbitrage checks**: Every item in every trip gets arbitrated automatically
- **35% service fee** (down from 45% free tier)
- **Deal alerts**: Proactive notifications when cached knowledge cards find savings on saved routes
- **Event hosting**: Create managed trips, collect payments via Stripe Connect
- **Managed trip mode**: Lock itineraries, set deadlines, roster management
- **Priority search**: Arbitrage checks run with higher priority in queue
- **Full scrapbook + travel map**: Extended social features

### Gating Philosophy
- **FREE everything that drives growth**: Sharing, inviting, trip planning, social posts, profile building
- **GATE everything that costs us money**: Arbitrage checks (proxy queries), deal alerts (background searches), event payment processing
- **The funnel**: Free user builds trip → gets 3 free arbitrage checks → sees real savings → subscribes to Travel+ for unlimited

---

## 23. DEAL FEED (CACHED KNOWLEDGE INTELLIGENCE)

### Scott's Cheap Flights Model, Powered by ANASTASiA
Every arbitrage check feeds ANASTASiA's knowledge cards. Over time, the system accumulates:
- Route-level pricing intelligence (LAX-NRT averages $2,345 on Google, $1,016 via POS arbitrage)
- Seasonal patterns (Tokyo flights cheapest in February from Danish POS)
- Airline-specific arbitrage windows (ANA has 40% POS spread, Delta has 5%)

### Proactive Deal Generation
- Knowledge cards identify routes with consistent high spreads
- System generates "deal alerts" from CACHED DATA — no new searches required
- Travel+ subscribers get push notifications: "LAX→NRT is $1,329 cheaper than Google right now"
- Deals are validated with a single proxy check before alerting (minimal cost)

### Cost Structure
- **Initial learning**: Costs money (proxy queries from user arbitrage checks)
- **Steady state**: Near-zero marginal cost — deals generated from cached intelligence
- **Revenue**: Travel+ subscriptions ($9.99/mo) + booking fees on converted deals
- **Flywheel**: More users → more arbitrage checks → richer knowledge cards → better deals → more users

---

## 24. BROWSER EXTENSION (FUTURE DISTRIBUTION)

### Concept
Chrome/Firefox extension that activates on Google Flights, Booking.com, Expedia:
- Shows a small banner: "MYSTES found this flight for $374 less"
- One-click import to MYSTES trip planner
- Links to MYSTES checkout with arbitrage price

### Why Future (Not MVP)
- Extension store approval process adds friction
- Need proven arbitrage data before making public claims
- Core trip planner must be solid first
- Browser extensions have low install rates — focus on direct platform first

### When to Build
- After Trip Planner MVP (Builds #219-225) is live and tested
- After knowledge card cache has 10,000+ route-price data points
- After Travel+ has 100+ paying subscribers proving the model

---

## 25. COST OPTIMIZATION FROM USER-SOURCED RESEARCH

### The Economics Insight
Traditional OTA model: Platform pays for ALL searches, user pays nothing until booking.
MYSTES model: User does their own research (free for us), we only pay for targeted arbitrage checks.

### Cost Comparison
| Operation | Traditional OTA | MYSTES |
|-----------|----------------|--------|
| Flight search | Platform pays API per query | User searches Google (free for us) |
| Hotel search | Platform pays API per query | User searches Booking.com (free for us) |
| Price comparison | Platform runs multi-source queries | User tells us what they found, we run ONE check |
| Inventory browsing | Platform serves thousands of results | User narrows to specific items |

### What MYSTES Pays For
1. **Proxy query per flight arbitrage check** — Bright Data CDP + airline scrape (~$0.10-0.50/check)
2. **Duffel API call per hotel arbitrage check** — Duffel search (~$0.01/search)
3. **SerpAPI for US baseline** — Google Flights comparison (~$0.01/search)
4. **Knowledge card storage** — Negligible (SQLite/PostgreSQL)

### Scaling Math
- 1,000 Travel+ subscribers × $9.99/mo = $9,990/mo revenue
- Average 20 arbitrage checks/user/month = 20,000 proxy queries
- At $0.25/query average = $5,000/mo cost
- **Margin: ~50% on subscriptions alone, before booking fees**
- As knowledge cards grow, cache hit rate increases, fewer proxy queries needed
- At scale: 80%+ cache hits → cost drops to ~$1,000/mo for same 20,000 "checks"

---

## 26. COMPETITOR PRICE INTELLIGENCE FROM USER IMPORTS

### Free Market Research
Every time a user imports a price from Google/Expedia/Booking.com:
- We learn what competitors charge for that route/date
- We learn the user's price sensitivity threshold
- We learn which routes users actually care about (demand signal)

### Data Captured Per Import
```
{
  "source": "google_flights",
  "route": "LAX-NRT",
  "dates": "2026-06-15 to 2026-06-29",
  "airline": "ANA",
  "price_found": 2345.00,
  "currency": "USD",
  "imported_at": "2026-04-15T14:30:00Z"
}
```

### Intelligence Generated
- **Route demand heatmap** — which routes do users actually search?
- **Price tolerance bands** — at what price do users stop looking?
- **Competitor pricing database** — what Google/Expedia/Booking charge per route
- **Arbitrage opportunity scoring** — which routes have the biggest consistent spreads?

All of this feeds ANASTASiA's knowledge cards at ZERO additional search cost.

---

## 27. UPDATED BUILD PLAN (Builds #219-234)

Added Build #234 for the Arbitrate My Trip engine:

| Build | Feature | Models |
|-------|---------|--------|
| #219 | InviteLink + /i/<token> resolver + OG meta | InviteLink |
| #220 | TravelCompanion + TravelerProfile | TravelCompanion, TravelerProfile |
| #221 | TripParty + TripGuest + sub-parties + roles | TripParty, TripGuest |
| #222 | ItineraryItem + search params + external bookings | ItineraryItem |
| #223 | Scoping engine + settlement calculator | -- |
| #224 | Voting + comments + suggestions | ItineraryVote, ItemComment |
| #225 | Managed mode + roster + capacity + waitlist + deadlines | TripGuestInfo, TripAnnouncement |
| #226 | TicketTier + event mode + RSVP + Stripe Connect payout | TicketTier |
| #227 | Guest info collection + plus-ones + QR check-in | -- |
| #228 | Narrative pitch generator + per-guest personalization | -- |
| #229 | SharedCart + guest Stripe payment | SharedCart |
| #230 | TripPost + photos + scrapbook + trip cloning | TripPost, TripPhoto |
| #231 | Public profiles + travel map + stats + badges + follows | UserFollow, TravelStats |
| #232 | ProfileReview + verified reviews + B2B public pages | ProfileReview |
| #233 | Referral attribution chain + conversion tracking + rewards | -- |
| #234 | Arbitrate My Trip engine + import flow + side-by-side UI | ExternalBookingImport, ArbitrageCheck |

### Updated Dependency Order
- #219-225: Trip planner engine (functional MVP)
- #226-227: Event layer
- #228-229: Sharing + carts
- #230-232: Social network
- #233: Attribution + analytics
- #234: Arbitrate My Trip (can run parallel with #230-233, depends on #222)

---

## 28. TARGETED ARBITRAGE MODEL (QUERY COST ELIMINATION)

### Core Principle: User Selects, We Arbitrate
Traditional OTA: search 50+ airlines × multiple dates × multiple cabins = hundreds of API calls per search.
MYSTES model: User says "I want THIS specific ANA flight on June 15" → we check THAT flight across 3-5 POS markets with known spreads. **95%+ query reduction per booking.**

### Two User Personas

**Tool Users** — "I know what I want, just make it cheaper"
- Build trip on Google/Airbnb/anywhere
- Import specific selections into MYSTES
- Arbitrate → book → done
- Cost to serve: near-zero (targeted checks only)
- Highest profit margin per booking
- Volume base of the business

**Platform Users** — "I want to browse, discover, plan"
- Use full MYSTES search + trip planner + social features
- More expensive to serve (broader queries)
- Generate social content, referrals, reviews
- Bring in tool users through word-of-mouth
- Growth engine of the business

Both personas feed ANASTASiA. Both pay identical fees. Tool users are ~10x more profitable per booking.

### Airline Arbitrage Profiles (Knowledge Card per Airline)
ANASTASiA builds a profile for every airline:
```
{
  "airline": "ANA",
  "iata": "NH",
  "arbitrage_profile": {
    "transpacific": {"avg_spread": 0.35, "best_pos": ["DK", "BR", "IN"], "confidence": 0.92},
    "transatlantic": {"avg_spread": 0.15, "best_pos": ["DK", "SE"], "confidence": 0.74},
    "domestic_jp": {"avg_spread": 0.02, "best_pos": [], "confidence": 0.88}
  },
  "data_points": 342,
  "last_updated": "2026-04-15"
}
```

This means:
- User selects Delta domestic → ANASTASiA instantly says "low arbitrage probability, ~2% spread" → skip the check or set low expectations
- User selects ANA transpacific → ANASTASiA says "high savings likely, 35% avg spread from DK/BR POS" → run targeted check immediately
- **Saves queries on airlines/routes where arbitrage doesn't exist**

### Arbitrage Confidence Score
Before running a single proxy query, ANASTASiA returns a prediction:
```
"87% likely we can save you $200-400 on this flight
 Based on 342 previous checks on LAX-NRT with ANA
 Best POS: Denmark (35% avg spread)"
```

This serves three purposes:
1. **Sets expectations** — no disappointment on low-spread routes
2. **Prioritizes checks** — high confidence flights run first in the queue
3. **Converts Travel+** — "upgrade to check all your flights, starting with the highest savings potential"

### "Save for Later" Watchlist
When no arbitrage exists at time of check:
1. Store route + airline + target price + user's found price in watchlist
2. ANASTASiA knowledge cards already track seasonal patterns
3. When spread opens (POS pricing fluctuates daily): push notification
4. "That ANA LAX-NRT flight you saved? It's now $387 cheaper through us."
5. **Near-zero cost conversion** — knowledge card data already exists, no new search needed

### International-First Strategy
- **Domestic US**: Almost zero POS spread — airlines price uniformly
- **Transpacific**: 25-40% spreads (ANA, JAL, Korean Air, Cathay Pacific)
- **Transatlantic**: 15-30% spreads (Lufthansa, BA, Air France)
- **Intra-Asia**: 20-35% spreads (regional carriers with heavy local pricing)
- **Europe-Asia**: 15-25% spreads

Marketing push order: International → intercontinental → regional → domestic (only when spread exists).

### Knowledge Card Flywheel (Non-Linear Acceleration)
```
Stage 1 (0-10K checks):     Every check costs $0.25, cache hit 5%
Stage 2 (10K-50K checks):   Airline profiles forming, cache hit 30%
Stage 3 (50K-100K checks):  Seasonal patterns learned, cache hit 60%
Stage 4 (100K+ checks):     Predictive arbitrage, cache hit 80%+
                             Cost per "check" drops to ~$0.05
                             Confidence scores reliable to ±5%
```

At Stage 4, ANASTASiA can:
- Predict arbitrage probability without running a query
- Generate deal alerts from cached data alone
- Score every imported flight instantly
- Skip checks on routes with <5% historical spread
- This is a proprietary pricing intelligence database NO competitor can replicate

### Booking Layer Positioning (No Competition)
Google Flights, Kayak, Skyscanner = search engines.
MYSTES = the layer AFTER search.

"Use whatever search engine you want. We don't care. Just come to us when you're ready to save money."

Nobody else occupies this position because nobody else has:
1. Multi-POS proxy infrastructure
2. Compiled airline arbitrage profiles
3. Real-time POS spread intelligence
4. A booking channel that routes through cheaper markets invisibly

### Updated Scaling Math (Targeted Model)
- 1,000 Travel+ subscribers × $9.99/mo = $9,990/mo subscription revenue
- Average 20 imports/user/month = 20,000 imported items
- 60% are flights (12,000) — rest are hotels/activities (no proxy needed)
- ANASTASiA skips 40% (low confidence airlines/routes) = 7,200 actual proxy checks
- At $0.25/query = $1,800/mo (was $5,000 in broad search model)
- **Margin: 82% on subscriptions alone, before booking fees**
- At Stage 4 (80% cache hits): 1,440 actual queries × $0.25 = $360/mo
- **Margin: 96% on subscriptions**

---

## 29. KEY ARCHITECTURAL DECISIONS — ADDENDUM (LOCKED)

16. User selects airline → we check THAT flight across POS markets, NOT broad search
17. Two personas: tool users (import + arbitrate) and platform users (full search) — both pay same fees
18. Airline arbitrage profiles built per-carrier in knowledge cards
19. Arbitrage confidence score returned BEFORE running proxy queries
20. "Save for later" watchlist with knowledge-card-driven price alerts
21. International flights = primary marketing push (largest POS spreads)
22. Knowledge card flywheel: 0→10K checks = learning, 100K+ = predictive, 80%+ cache hits
23. MYSTES = booking layer AFTER search, not competing with search engines
24. Skip proxy checks on airlines/routes with <5% historical spread

---

## 30. DOMESTIC US ARBITRAGE — CORRECTION & STRATEGY

### Empirical Data Overrides Assumption
Previous assumption: "Domestic US flights have almost zero POS spread." WRONG.
User's live test data: Domestic US flights searched from DE and ES POS returned arbitrage results multiple times.
Only 2 POS markets tested — 193 more countries to check.

### Correction Applied
- Domestic US flights ARE arbitrageable — spread may be smaller than transpacific (29.6% avg) but volume is MASSIVE
- Even 10-15% spread on a $400 domestic flight = $40-60 savings
- Volume × small spread can beat frequency × large spread in total revenue
- Domestic US flight volume dwarfs international — millions of passengers per week on top routes

### Hot Routes Strategy
Top 20 US domestic routes handle 50M+ passengers/year combined:
- ATL-LAX, LAX-JFK, ATL-MCO, LAX-SFO, JFK-MIA, ORD-LAX, DFW-LAX, etc.
- Even $30 savings on ATL-LAX (3M+ annual pax) = massive addressable market
- Capture a fraction of a fraction = serious volume

### Arbitrage Mapping Sprint Plan
1. Take top 50 US domestic routes by passenger volume
2. Run each through 10-15 POS markets (DE, ES, DK, BR, IN, JP, SE, NO, MX, PH, NG, KE, TH, AR, PL)
3. Build heat map: route × POS → spread %
4. Store results as ANASTASiA knowledge cards permanently
5. Identify which POS markets to prioritize per route

### "Hot Routes" Homepage Feed
Not a search box — a FEED. Like Scott's Cheap Flights meets a stock ticker:
```
ATL → LAX: Save $47 (12% off Google) — 3 seats left at this price
JFK → MIA: Save $62 (18% off Google) — Book by Friday
ORD → SFO: Save $38 (10% off Google) — Weekend deal
```
- Real-time, cached from knowledge cards, updated as proxy checks run
- No search required — click → see deal → book
- The hook that converts casual browsers

### Location-Aware Hot Routes
- GeoIP (Build #202) determines user's nearest hub
- Guest users see local deals WITHOUT login
- Free tier users see more routes
- Travel+ users get push alerts on their saved routes
- Personalized without requiring account creation

---

## 31. ADVANCED ARBITRAGE FEATURES

### 1. Round-Trip Leg Splitting
Airlines price round trips and one-ways independently. Sometimes:
- Outbound ATL→LAX has 15% spread from DK POS
- Return LAX→ATL has 25% spread from BR POS

ANASTASiA should check each leg independently and potentially book from DIFFERENT POS markets.
Two proxy bookings instead of one, but savings stack. Nobody does this because nobody has multi-POS infrastructure.

### 2. Date Flex Arbitrage
User wants ATL-LAX on June 15. Proxy check shows 5% spread.
But June 17 shows 22% spread from the same POS.
ANASTASiA surfaces: "Fly 2 days later, save an extra $85."
- Already storing search params — add ±3 day flex check option
- One extra check per flex day
- Upsell conversion rate on "save more if you're flexible" is extremely high

### 3. Airline Credit Card Intelligence (Free Data)
Many users have airline credit cards (Delta Amex, United Chase) giving 2-5x miles.
If user tells MYSTES their card, ANASTASiA calculates:
"Book through us for $47 cash savings, OR book direct and earn 3,200 extra miles worth ~$48."
- Some users prefer cash, some prefer miles
- Either way, MYSTES helped them decide = engagement + trust
- Users who book through us were going to anyway (cash > miles for them)

### 4. Group Booking Arbitrage Multiplier
Family of 4 on ATL-LAX where each ticket saves $47 = $188 total savings.
Spring break group of 8 = $376 total savings.
- Savings multiply with group size
- Proxy cost stays roughly the same (one check per route, apply to all passengers)
- Surface prominently in trip planner: "Your group of 6 saves $282 total on this route"

### 5. Rebooking Arbitrage Alerts
User booked ATL-LAX at $380 through MYSTES (saved $40 off Google).
Three weeks later, same flight drops to $310 from BR POS.
Most airlines allow free cancellation within 24h, many allow changes for a fee.
ANASTASiA alerts: "Your ATL-LAX flight just dropped $70 more. Rebook and save?"
- Second bite at the same apple
- Builds insane loyalty — actively saving money AFTER the sale

### 6. Connecting Flight Arbitrage
ATL→LAX direct = $380. ATL→DEN→LAX = $220 with comfortable 2hr layover.
But what if ATL→DEN = $90 from DK POS and DEN→LAX = $85 from BR POS?
That's $175 vs $380 — 54% savings.
- Nobody else can do this (no multi-POS per-leg checking)
- ANASTASiA knowledge cards know which hubs have the best splits
- Advanced feature but genuine unique capability

---

## 32. THE CACHED DEAL NETWORK EFFECT — MOAT ANALYSIS

### This Is a Moat, Not a Feature
Every arbitrage check — whether the user books or not — teaches ANASTASiA:
- Route + airline + POS → spread exists (or doesn't)
- Time-of-booking patterns (spreads wider 60 days out vs 14 days)
- Seasonal windows (Tokyo cheapest from DK POS in Feb, from BR POS in Aug)

### After 6 Months of User Activity
- Pricing database covers top 500 US routes across 15+ POS markets with daily granularity
- This data doesn't exist ANYWHERE else — not Google, not Kayak, not any GDS
- You can PREDICT where arbitrage lives before running a single query
- Economics flip: stop paying for searches → start SELLING intelligence (deal feeds, alerts, B2B data)

### Replication Cost for Competitors
To replicate MYSTES's knowledge card database, a competitor would need:
1. Multi-POS proxy infrastructure (months to build)
2. Hundreds of thousands of proxy queries ($50K-$100K)
3. 6+ months of data collection
4. Real user behavior data (which routes people actually book)
By then, MYSTES has 12+ months of data and the flywheel is 10x ahead.

---

## 33. CORPORATE TRAVEL — TRAVEL+ BUSINESS

### The Opportunity
US corporate travel spend = $350B+/year. Companies have travel managers booking the same routes repeatedly.
This is NOT B2B (salesmen with referral codes). This is a COMPANY buying travel for its OWN employees.

- B2B = salesman selling to strangers via referral codes
- Travel+ Business = company buying for its own people
- Zero overlap. Zero cannibalization.

### Travel+ Business Tiers (Per-Seat Model)

Base = Travel+ ($9.99/mo) with team management. Per-seat pricing scales naturally:

**Travel+ Business Starter** — $9.99/mo + $4.99/seat/mo, up to 25 seats
- Admin dashboard, team roster, book-on-behalf
- Group itineraries via trip planner
- 35% service fee (same as Travel+ personal)

**Travel+ Business Pro** — $9.99/mo + $3.99/seat/mo, up to 100 seats
- Everything in Starter
- Travel policies (max flight cost, preferred airlines, approval workflows)
- Expense tagging, department grouping
- 30% service fee

**Travel+ Business Enterprise** — $9.99/mo + $2.99/seat/mo, unlimited seats
- Everything in Pro
- SSO/SAML integration
- Dedicated account manager
- Custom reporting, API for expense system integration
- 25% service fee

### Scaling Examples
- 5-person startup: $9.99 + $24.95 = $34.94/mo
- 50-person company: $9.99 + $199.50 = $209.49/mo
- Apple with 500 travelers: $9.99 + $1,495 = $1,504.99/mo
- Every seat = guaranteed MYSTES account = $0 CAC user acquisition

### The Workspace Model (Slack for Travel)
A business creates a **Workspace** with real admin controls:

**Admin Panel**
- Add/remove members (by email invite or invite link)
- Roles: Admin (full control), Travel Manager (book for others, approve), Member (book for self)
- Travel policies: max price, approved airlines, blackout dates, approval thresholds
- All-bookings dashboard across entire workspace
- Export booking data (CSV/PDF) for expense reporting
- Department/team grouping within workspace

**Member Experience**
- Employee gets invite link → creates MYSTES account (or links existing) → joins workspace
- Gets Travel+ features automatically (unlimited arbitrage, deal alerts)
- Gets workspace fee tier (30% or 25% vs individual 35%)
- Books personal flights at workspace rate — THE PERK that drives adoption
- Sees team trip planners they're assigned to
- Flags bookings as "business" (company pays) or "personal" (employee pays at group rate)

**Admin Booking on Behalf**
- Admin selects employee from roster → builds itinerary → arbitrates → books
- Employee gets notification: "Your travel to Chicago has been booked"
- Uses managed trip mode (Build #225) with corporate permissions
- Admin sees all PNRs, confirmations, costs in one view

**Corporate Contact Directory**
- Workspace members auto-appear in each other's travel network
- Admin builds corporate directory
- New hire onboarding: admin enters email → invite link → account creation → auto-join → in directory
- Integrates with existing friends/contacts feature

### Member Types Within Workspace
- **Employee** — full workspace member, company pays, full group rate
- **Contractor** — temporary access, time-limited, books at workspace rate
- **Affiliate** — external partner, reduced discount (one tier below employees)
Invite link carries workspace_id + member_type → auto-assigns on account creation

### The Personal Flight Perk (Viral Distribution)
Employee at Apple has Travel+ Business → gets 25% fee instead of 35%.
Can book PERSONAL flights at that rate.
- Employee tells friends: "Got my Hawaii flight $60 cheaper through MYSTES"
- Friends ask how → employee shares referral → friends sign up
- Company pays for Travel+ Business, employee does free marketing on personal time
- Personal bookings cost the company NOTHING — employee pays their own
- Every corporate account = viral distribution channel

### Guaranteed Booking Volume Economics
Corporate travel is recurring and predictable — same routes every week:
- Month 1: Run proxy checks on all 50 employees' flights
- Month 2: 60% of routes are repeats → cached knowledge cards → near-zero query cost
- Month 3: 80% cache hits → almost pure profit
- Month 6: ANASTASiA PREDICTS next month's travel before anyone books

Admin sees: "Based on your team's travel patterns, here are 12 flights next month where we can save $3,200 total. Pre-approve?"

### CFO Pitch
"Your team spends $50K/month on flights. We save you $5K-$15K of that. It costs you $500/mo."
That's a 10-30x ROI. CFOs sign that in their sleep.

---

## 34. UPDATED BUILD PLAN (Builds #219-237)

| Build | Feature | Models |
|-------|---------|--------|
| #219 | InviteLink + /i/<token> resolver + OG meta | InviteLink |
| #220 | TravelCompanion + TravelerProfile | TravelCompanion, TravelerProfile |
| #221 | TripParty + TripGuest + sub-parties + roles | TripParty, TripGuest |
| #222 | ItineraryItem + search params + external bookings | ItineraryItem |
| #223 | Scoping engine + settlement calculator | -- |
| #224 | Voting + comments + suggestions | ItineraryVote, ItemComment |
| #225 | Managed mode + roster + capacity + waitlist + deadlines | TripGuestInfo, TripAnnouncement |
| #226 | TicketTier + event mode + RSVP + Stripe Connect payout | TicketTier |
| #227 | Guest info collection + plus-ones + QR check-in | -- |
| #228 | Narrative pitch generator + per-guest personalization | -- |
| #229 | SharedCart + guest Stripe payment | SharedCart |
| #230 | TripPost + photos + scrapbook + trip cloning | TripPost, TripPhoto |
| #231 | Public profiles + travel map + stats + badges + follows | UserFollow, TravelStats |
| #232 | ProfileReview + verified reviews + B2B public pages | ProfileReview |
| #233 | Referral attribution chain + conversion tracking + rewards | -- |
| #234 | Arbitrate My Trip engine + import flow + side-by-side UI | ExternalBookingImport, ArbitrageCheck |
| #235 | Workspace model + admin panel + roles + invite flow | Workspace, WorkspaceMember |
| #236 | Travel policies + approval workflows + expense tagging | TravelPolicy, BookingApproval |
| #237 | Corporate dashboard + book-on-behalf + reporting + export | -- |

### Updated Dependency Order
- #219-225: Trip planner engine (functional MVP)
- #226-227: Event layer
- #228-229: Sharing + carts
- #230-232: Social network
- #233: Attribution + analytics
- #234: Arbitrate My Trip (depends on #222)
- #235-237: Corporate Travel+ Business (depends on #219, #222, #225)

---

## 35. KEY ARCHITECTURAL DECISIONS — ADDENDUM 2 (LOCKED)

25. Domestic US flights ARE arbitrageable — empirical test data from DE/ES POS confirms. Do NOT dismiss.
26. Hot routes homepage feed — cached deals displayed without search, location-aware via GeoIP
27. Round-trip legs can be booked from DIFFERENT POS markets to stack savings
28. Date flex arbitrage: ±3 day window check to find larger spreads on nearby dates
29. Rebooking alerts when price drops after purchase
30. Connecting flight arbitrage: per-leg POS optimization through hub airports
31. Travel+ Business = per-seat pricing, NOT flat tier. Scales from startups to enterprises.
32. Workspace model (not "group") — Admin/Travel Manager/Member roles
33. Personal flights at workspace rate = the adoption perk that drives viral distribution
34. Three workspace member types: Employee, Contractor, Affiliate
35. Corporate route repetition → knowledge card cache hits 80%+ by month 3
36. Predictive travel intelligence for corporate admins (pre-approve next month's savings)

---

## 36. HONEST PLATFORM ASSESSMENT & STRATEGIC CORRECTIONS

### What This Platform Actually Is
Not an OTA. Not a booking layer. A **credential marketplace with a consumer front-end.**
- MYSTES (OTA) = demand side
- APAi (credential marketplace) = supply side
- Proxy = proprietary supply that no competitor can bring
- ANASTASiA = routing intelligence matching demand to cheapest supply
- Trip planner, social tools, workspaces = engagement mechanisms generating demand

### Strengths (Genuine, Not Hype)
1. POS arbitrage positioning is REAL — structural to airline revenue management, not a loophole
2. "Booking layer after search" is a genuinely unoccupied market position
3. Knowledge card flywheel is an actual moat — 6 months of data = unreplicable
4. Per-seat corporate pricing scales naturally without negotiation
5. Platform features (trip planner, workspaces, events) are novel and valuable WITHOUT arbitrage
6. APAi credential marketplace makes GDS contracts irrelevant (see Section 39)

### Phased Launch Strategy (Revenue Gates)
**Phase A — "Arbitrage Engine" (MVP, revenue day 1)**
Core search + arbitrage check + proxy booking + Stripe. Most already built (Builds #202-207).
Add Build #234 (Arbitrate My Trip import + hot routes feed).
Ship first. Users search, see savings, book, pay. Revenue flows.
DO NOT BUILD Phase B until Phase A has 100 paid bookings.

**Phase B — "Trip Planner" (engagement, reduces churn)**
Builds #219-225. Trip planner turns one-time bookers into returning planners.
DO NOT BUILD Phase C until Phase B has 500 active trip planners.

**Phase C — "Platform" (expansion, network effects)**
Events, workspaces, social distribution, deal feeds. Only when Phase B proves stickiness.

### Hybrid Pricing Model (Travel+ + Pay-Per-Check)
Problem: Average US consumer books 2-4 flights/year. $120/yr subscription for quarterly use is hard.
Solution: Keep Travel+ BUT add pay-per-check for casual users.
- Guest/Free: 3 free arbitrage checks/month. Additional checks: $2.99 each.
- Travel+ ($9.99/mo): Unlimited checks, deal alerts, priority queue, event hosting.
- Travel+ Business: Per-seat pricing as designed.

Revenue math with hybrid model (10,000 registered users):
- 7,000 free tier (avg 0.5 paid checks/mo) = 3,500 × $2.99 = $10,465/mo
- 2,500 Travel+ × $9.99 = $24,975/mo
- 500 Travel+ Business (avg 15 seats × $4.99) = $37,425/mo
- **Total: $72,865/mo BEFORE booking fees**
- Without pay-per-check: $24,975/mo. Difference = $47,890/mo left on table.

### Cold Start Data Seeding ($1,125 one-time)
1. Top 150 routes (100 domestic + 50 international) from public DOT data
2. Check each across 15 POS markets = 2,250 checks × 2 runs = 4,500 data points
3. Cost: $1,125. Time: 3-5 days automated.
4. Ongoing: 50-100 checks/day keeping cards fresh = ~$500/mo
5. Day-one intelligence: airline profiles, confidence scores, hot routes feed populated

### Mobile-First Design Principle
Every feature must work as a single-screen card on mobile:
- Trip planner: Card-based vertical scroll, swipe actions
- Arbitrage results: Single comparison card with one green "Book" button
- Hot routes feed: Full-screen card carousel (TikTok-of-travel-deals UX)
- Workspace admin: Simplified to add/view/approve on mobile; full admin = desktop

---

## 37. SOCIAL LAYER CORRECTION — MARKETPLACE, NOT SOCIAL NETWORK

### Previous Position (WRONG): Kill internal social, use external platforms only.
### Corrected Position: Social layer IS the marketplace distribution engine. Build it.

The social features aren't for socializing — they're for SELLING:
- Every shared trip card carries a referral code
- Every itinerary share is a booking link with conversion tracking
- Every post is a peer-to-peer distribution funnel
- Users earn rewards/commission from bookings through their shared content
- It's a P2P distribution engine, not Instagram for travel

### Social Distribution Tools (KEEP all social builds, add distribution focus)
**Deal Cards Generator** — Auto-generated shareable cards on booking:
```
┌─────────────────────────────┐
│  MYSTES                     │
│  LAX → Tokyo  ✈             │
│  Saved $374 (29%)           │
│  "Flying to Tokyo for $374  │
│   less than Google Flights"  │
│  [Book yours → mystes.app]  │
│  ref: JAKE2026              │
└─────────────────────────────┘
```
- One-tap share to Instagram Stories, X, iMessage, WhatsApp, TikTok
- Referral code (B2B or personal) baked into every card
- Trip itinerary cards for group trips
- Post-trip summary cards with total savings

**Rich OG Previews** — Every trip/deal/itinerary gets a public share URL:
- Beautiful preview when pasted on Facebook/X/iMessage
- Public landing page with CTA to book (no account required to view)
- Travel stats exportable as images for social media bios

**B2B Share Kit** — Marketing material for B2B subscribers:
- Generated social media graphics, story templates, caption suggestions
- QR code posters (already built #206)
- Embeddable deal widget for blogs/websites (iframe with live hot routes)

### Feature Toggles
All social features behind feature flags. Enable per-feature as engagement data justifies.
Social builds stay in plan but ship AFTER Phase A/B prove revenue.

---

## 38. CANCELLED FLIGHT POLICY (LOCKED)

### Policy: Service Fee is NON-REFUNDABLE. MYSTES is NOT the airline.

**Rationale:**
- The service MYSTES delivered: "Found a fare $X cheaper and facilitated the booking"
- That service was completed at booking confirmation
- Airline cancellation is between customer and airline (airline = MoR)
- Travel agents don't refund booking fees when airlines cancel — industry standard

**Cost Exposure on Cancellation:**
- Proxy query cost (~$0.25-0.50): Sunk, non-recoverable — covered by collected service fee
- Service fee: Already collected via Stripe — KEEP IT
- Customer contacts airline directly for ticket refund/rebooking

**The Smart Play — Turn Cancellations into a SECOND Sale:**
1. Booking lifecycle monitor detects cancellation automatically
2. Notify customer instantly: "Your flight was cancelled by [airline]. Contact them at [number] for your refund."
3. Simultaneously: "We found 3 alternative flights with arbitrage savings:"
4. Customer gets ticket money back from airline
5. Customer rebooks through MYSTES at new arbitrage price
6. MYSTES earns SECOND service fee on rebooking
7. Cancellation becomes revenue-positive

**Checkout Terms (Required):**
"Service fee is non-refundable. MYSTES facilitates booking through airline websites.
Cancellations, changes, and refunds are handled directly with the carrier.
MYSTES is not the merchant of record for your ticket."

**Optional Goodwill:**
$5 booking credit toward rebooking. Costs $5, earns a full new service fee.

---

## 39. GDS AVOIDANCE — PROXY IS PERMANENT (LOCKED)

### Previous Position (WRONG): Use AirGateway/AERTiCKET as contracted fallback.
### Corrected Position: GDS aggregators CANNOT provide multi-POS. Proxy IS the product.

**Why GDS Doesn't Work for MYSTES:**
- NDC aggregator gives ONE contracted rate or limited POS markets
- That's not arbitrage — it's just another API with different prices
- The value prop requires 195-country POS access
- A GDS contract LIMITS you to negotiated markets
- Proxy gives you EVERY market without contracts

**Correct Architecture:**
- **Proxy = PRIMARY and PERMANENT.** Not a bootstrap. THE product.
- **Duffel = non-arbitrage channel.** Hotels (Stays), flights without POS spread, fallback.
- **GDS aggregators = NEVER.** Unless airline physically blocks proxy AND has significant volume. Case-by-case only.
- **APAi credential marketplace = THE GDS REPLACEMENT** (see below)

**Proxy Resilience Architecture:**
1. **Multi-provider redundancy**: Bright Data primary + Oxylabs/SmartProxy secondary. Rotate if one provider's IPs get flagged.
2. **Residential IP rotation**: Never reuse same IP for same airline within 24h. Millions of IPs available.
3. **Airline-specific booking profiles**: ANASTASiA learns each airline's detection patterns. Auto-rotate POS when blocks detected.
4. **Graceful degradation**: If proxy fails 3 attempts → fall back to Duffel at non-arbitrage price → notify user → refund fee difference.
5. **Volume distribution**: Never >0.1% of airline's daily bookings through any single POS. Auto-spread across secondary markets.
6. **Behavioral camouflage**: Randomized browsing, 45-90s booking duration, realistic mouse/scroll patterns.

---

## 40. APAi CREDENTIAL MARKETPLACE — OPEN P2P MODEL (CORRECTED)

### Previous Description (WRONG): MYSTES sets 70/30 splits and 5%/3%/2% routing fees on P2P transactions.
### Corrected Model: P2P terms set ENTIRELY by subscribers. MYSTES earns $0 from P2P credential sharing.

### The Elegant GDS Bypass
MYSTES doesn't need AirGateway because APAi subscribers ARE the GDS layer.

**Who subscribes to APAi:**
- Small travel agencies with Amadeus/Sabre access
- Consolidators with contracted airline rates
- NDC-connected agents with direct airline agreements
- Regional OTAs with local market credentials

### P2P Credential Economics (LOCKED)
- **Credential providers set their OWN terms.** Fee per booking, fee per search, margin %, flat monthly — whatever they want.
- **Credential consumers browse and accept terms they like.** Market forces optimize pricing.
- **MYSTES earns $0 from P2P transactions.** Revenue comes from APAi subscriptions ($299/$599/$999/mo).
- **MYSTES participates AS a credential provider** with its own proxy credentials and its own terms (5%/3%/2% + 70/30 split = MYSTES's terms, not platform rules).
- **Two agencies with same credentials → price competition.** One charges 50%, another 5%. Market decides who gets volume.

### Why MYSTES Stays Out of P2P Economics
1. **Complexity elimination**: Don't need to understand Amadeus vs Sabre vs NDC pricing models. Providers know their costs.
2. **No liability for API costs**: Provider sets per-query fee that covers THEIR API costs. Their margin calc, not ours.
3. **Natural price competition**: Market optimizes rates without platform intervention.
4. **Shopify model**: Charge for platform ACCESS, not a cut of every sale. More attractive marketplace.
5. **Clean revenue**: Subscription fees (predictable, recurring) + MYSTES's own credential routing (when proxy is used).

### Credential Provider Settings Panel
```
My Credential: Thai Airways NDC (Direct Agreement)
├── Markets Available: TH, SG, MY, ID, VN, PH
├── Pricing Model: [Per Booking ▼]
│   ├── Per Booking: $X flat fee per completed booking
│   ├── Per Search: $X per search query
│   ├── Margin Split: X% of price spread
│   └── Monthly Flat: $X/mo unlimited access
├── My Rate: $8.00 per booking
├── Minimum Spread Required: $20 (won't route if savings < $20)
├── Auto-Accept Routing: [Yes / Approval Required]
├── Max Daily Bookings: 50 (to control API costs)
├── Blackout Routes: [none]
└── Terms Note: "NDC direct, real PNR, 24h support"
```

Subscriber controls EVERYTHING. They know their API costs, set rates that cover costs + profit.
Price too high → nobody routes through them. Price too low → they eat their API costs. Market handles it.

### Routing Discovery Flow
APAi subscriber's OTA gets booking request for BKK→SIN on Thai Airways:
1. ANASTASiA queries marketplace: "Who has Thai Airways credentials covering TH POS?"
2. Returns providers with terms + quality metrics:
   - Agency A: $8/booking, 98.7% success rate, 4.2s avg completion
   - Agency B: 15% of margin, 95.1% success rate, 6.8s avg
   - MYSTES Proxy: 5% of margin (Pro tier), 97.3% success, 12s avg (proxy is slower)
3. Subscriber's ANASTASiA routes through cheapest option meeting quality threshold
4. OR subscriber pre-sets preferences: "always cheapest" / "highest success rate" / "specific providers only"

### Reputation System (System-Generated, Not Reviews)
- **Booking success rate**: "Agency X completes 98.7% of routed bookings"
- **Response time**: "Average booking completion: 4.2 seconds"
- **Credential uptime**: "Online 99.1% of last 30 days"
- **Volume handled**: "Processed 1,247 bookings this month"
All metrics tracked automatically by ANASTASiA from routing data. Objective, not subjective.

### MYSTES Revenue Sources (Clarified)
1. **APAi subscriptions**: $299/$599/$999/mo — recurring, predictable
2. **MYSTES's own credential routing**: When MYSTES proxy is used by APAi subscribers, MYSTES earns per its own terms
3. **Consumer booking fees**: Service fee on MYSTES OTA bookings (tier-based %)
4. **Pay-per-check**: $2.99 per arbitrage check for free-tier users
5. **Travel+ subscriptions**: $9.99/mo consumer, per-seat business
6. **$0 from P2P credential transactions**: Subscribers keep 100% of what they negotiate

### The Recursive Flywheel
Bangkok agency with Thai Airways creds joins APAi → sets $8/booking → creds get routed for BKK departures → earns passive income → tells other agencies → more creds join → MYSTES has deeper inventory than any single GDS without signing a single contract → more consumers → more routing volume → more agencies want in.

### Marketplace Trust Requirements
1. **Credential health checks**: Periodic test queries. Auto-disable after 3 consecutive failures. Provider notified.
2. **Routing transparency**: Real-time dashboard — bookings routed, routes served, revenue earned, utilization %.
3. **Dispute resolution**: Clear liability chain — provider (bad creds) vs consumer (bad routing config) vs platform (bug). Automated process with audit trail.
4. **Terms enforcement**: Platform escrows P2P payments. Provider terms are binding. No post-hoc renegotiation.

---

## 41. BOOKING LIFECYCLE MANAGEMENT (Build #238)

### BookingRecord Extensions
- `airline_confirmation`: PNR/confirmation code from proxy booking
- `booking_status`: confirmed / schedule_changed / cancelled / completed
- `check_in_opens`: datetime (24h before departure)
- `last_status_check`: datetime

### Automated Monitoring
- Worker checks booking status via airline website every 6h for flights within 14 days
- Schedule change → notify user with new times
- Cancellation → trigger alert + offer rebooking with current arbitrage prices
- Check-in open → push notification with airline check-in link

### Post-Booking Support Flow (Proxy Channel)
MYSTES not MoR → customer deals with airline directly for changes/refunds.
But MYSTES provides:
1. Automatic cancellation/change detection
2. Airline contact info + PNR ready in notification
3. Alternative flights with arbitrage if rebooking needed
4. Booking credit for rebooking goodwill ($5)
5. Full lifecycle tracking in user's booking history

---

## 42. FX-AWARE ARBITRAGE PRICING

### The Problem
Flight from DK POS priced in DKK. Customer charged in USD. Credit card FX fee (1-3%) eats savings.

### Solution: Show AFTER-FX Price
```
ANA LAX→NRT:
  Google Flights (US):  $2,345
  MYSTES (DK POS):      $1,016 (7,058 DKK)
  Est. FX fee (2.5%):   $25.40
  Your price:            $1,041.40
  You save:              $1,303.60 (55.6%)

  Have a no-FX-fee card? You save $1,329 (56.7%)
  [I have a no-FX-fee card] ← toggle (saved to profile)
```

- Real-time FX rates from free API (exchangerate.host or similar)
- 2.5% default FX buffer for standard cards, 0% for no-FX cards
- User sets FX preference once, applies to all future calculations
- Turns weakness into selling point — MORE transparent than any OTA
- Not a separate build — modification to ArbitrageModule (Build #202), ~50 LOC

---

## 43. REVISED FINAL BUILD PLAN (Builds #219-238)

| Phase | Build | Feature | Models |
|-------|-------|---------|--------|
| **A (MVP)** | #234 | Arbitrate My Trip + import + hot routes feed | ExternalBookingImport, ArbitrageCheck |
| A | -- | FX-aware pricing in ArbitrageModule | -- |
| A | -- | Data seeding sprint (150 routes × 15 POS) | -- |
| **B (Engage)** | #219 | InviteLink + /i/<token> + OG meta | InviteLink |
| B | #220 | TravelCompanion + contacts | TravelCompanion, TravelerProfile |
| B | #221 | TripParty + TripGuest + sub-parties | TripParty, TripGuest |
| B | #222 | ItineraryItem + search params + external bookings | ItineraryItem |
| B | #223 | Scoping engine + settlement calculator | -- |
| B | #224 | Voting + comments + suggestions | ItineraryVote, ItemComment |
| B | #238 | Booking lifecycle management | -- |
| **C (Platform)** | #225 | Managed mode + roster + deadlines | TripGuestInfo, TripAnnouncement |
| C | #226 | TicketTier + event mode + RSVP + payout | TicketTier |
| C | #227 | Guest info + plus-ones + QR check-in | -- |
| C | #228 | Narrative pitch generator | -- |
| C | #229 | SharedCart + guest Stripe payment | SharedCart |
| C | #230 | Deal cards + trip cards + social sharing | TripPost, TripPhoto |
| C | #231 | Share links + OG previews + exportable stats | UserFollow, TravelStats |
| C | #232 | B2B share kit + embeddable widget | ProfileReview |
| C | #233 | Referral attribution + conversion tracking | -- |
| C | #235 | Workspace model + admin + roles + invite | Workspace, WorkspaceMember |
| C | #236 | Travel policies + approvals + expense tags | TravelPolicy, BookingApproval |
| C | #237 | Corporate dashboard + book-on-behalf + export | -- |

### Revenue Gates
- Phase A → Phase B: 100 paid bookings
- Phase B → Phase C: 500 active trip planners
- All social features behind feature toggles

### Dependency Order
- Phase A: Ship immediately (most code exists)
- #219-224 + #238: Trip planner MVP
- #225-227: Managed mode + events
- #228-229: Sharing + carts
- #230-233: Social distribution + attribution
- #234: Already in Phase A
- #235-237: Corporate workspaces (parallel with #225+)

---

## 44. KEY ARCHITECTURAL DECISIONS — ADDENDUM 3 (LOCKED)

37. Social layer = marketplace distribution engine, NOT social network for socializing. Every share = booking funnel.
38. Service fee NON-REFUNDABLE on airline cancellations. Cancellations → rebooking opportunity (second sale).
39. GDS aggregators = NEVER. Proxy is PERMANENT, not bootstrap. Multi-POS is the product.
40. APAi credential marketplace = OPEN P2P. Subscribers set ALL their own terms. MYSTES earns $0 from P2P. Revenue = subscriptions only.
41. Credential health checks: periodic dummy searches, auto-disable after 3 failures.
42. Multi-proxy-provider redundancy: Bright Data primary + secondary provider. Never single-source.
43. Airline-specific booking profiles in knowledge cards: detection patterns, POS rotation triggers.
44. Volume distribution: never >0.1% of airline daily bookings through single POS market.
45. FX-aware pricing: show after-FX price, user sets card type once, 2.5% default buffer.
46. Booking lifecycle monitoring: status checks every 6h within 14 days, auto-detect cancellations/changes.
47. Revenue gates between launch phases: 100 bookings → trip planner, 500 planners → platform.
48. Pay-per-check ($2.99) for casual users alongside Travel+ subscription for power users.
49. All social/engagement features behind feature toggles. Enable based on data, not assumption.
50. Build everything, ship in phases. Architecture complete, execution gated by revenue milestones.
51. P2P credential terms set ENTIRELY by subscribers — fee/booking, fee/search, margin %, flat rate, whatever they want.
52. MYSTES participates as credential PROVIDER (proxy creds) with its own terms, NOT as marketplace price-setter.
53. Credential provider settings: pricing model, rate, min spread, auto-accept toggle, max daily volume, blackout routes.
54. System-generated reputation metrics (success rate, response time, uptime, volume) — NOT subjective reviews.
55. Routing preferences per subscriber: cheapest, highest success rate, specific providers, custom rules.
56. Platform escrows P2P payments. Provider terms binding. No post-hoc renegotiation.
57. 5%/3%/2% + 70/30 split = MYSTES's OWN terms when MYSTES proxy is used. NOT universal marketplace rules.

---

## 45. LIABILITY SHIELD — APAi SUBSCRIBERS AND PROXY PROTECTION (LOCKED)

### The Problem APAi Solves for OTAs
An OTA with an Amadeus/Sabre contract CANNOT do multi-POS proxy arbitrage. If their GDS provider
discovers they're scraping airline websites for cheaper POS pricing, they get deplatformed.
Their entire business evaporates. So they'd NEVER do it on their own — even though they know
the savings exist and their customers would benefit.

### How MYSTES Shields Them
1. **Subscriber brings the customer**: "I have a customer who wants LAX→NRT"
2. **ANASTASiA finds cheapest option**: Could be subscriber's own creds, another provider's, or MYSTES proxy
3. **If proxy wins, MYSTES routes through MYSTES's proxy**: MYSTES operates Bright Data, MYSTES hits the airline site, MYSTES books on customer's behalf
4. **Subscriber never touched the proxy**: They passed a customer into a marketplace and received commission
5. **Customer's card goes directly to airline**: Airline = MoR, not MYSTES, not the subscriber

### Clean Hands at Every Level

**From airline's perspective:**
A customer in Denmark bought a ticket on their website with their credit card. Normal sale.
No visibility into the OTA that orchestrated the customer reaching the Danish site.
PNR real. Payment real. Ticket real.

**From GDS's perspective:**
Subscriber didn't use their Amadeus credentials for this booking. Went through different channel.
Subscriber's Amadeus usage = exactly what it was before = legitimate contracted bookings.
Proxy booking exists in a parallel universe that never touches the GDS.

**From subscriber's perspective:**
"I earned money on a booking I couldn't have otherwise served at that price.
My contracts are intact. My credentials weren't used for the proxy. I just get a check."

### The APAi Pitch (Revised)
OLD: "Get your own OTA with ANASTASiA intelligence."
NEW: **"Access arbitrage savings you can't legally touch on your own. MYSTES handles the proxy.
You handle the customer. Your contracts stay clean. You get paid."**

This sells ACCESS TO REVENUE THEY CURRENTLY CANNOT CAPTURE because of contractual obligations.
The only way to offer POS-arbitraged pricing is through a third party operating proxy independently.
That third party is MYSTES.

### Why Open P2P Marketplace Reinforces Legal Protection
- MYSTES operates proxy credentials INDEPENDENTLY
- APAi subscribers operate their OWN credentials INDEPENDENTLY
- Marketplace transactions have subscriber-set terms
- MYSTES earns subscription fees, NOT routing commissions on P2P
- No "scheme" — independent parties transacting in an open marketplace

### Information Barrier (CRITICAL — Build into CredentialRouter)
The CredentialRouter MUST enforce an information barrier between MYSTES proxy operations
and APAi subscriber visibility:

- **MYSTES proxy module knows**: Which POS market, which airline site, booking method (operational necessity)
- **APAi subscriber dashboard shows**: "Booking completed. Customer saved $374. Your commission: $X."
- **APAi subscriber NEVER sees**: POS market used, proxy method, Bright Data details, airline site version
- **Deliberate plausible deniability**: Subscriber didn't know HOW the cheaper price was found. Just that it was found.

Same principle as stock broker dark pools: client says "buy at best price."
Broker finds price through mechanisms client doesn't see. Client gets result without knowing method.

### Legal Architecture Summary
```
┌─────────────────────────────────────────────────────────┐
│  CUSTOMER  →  pays airline directly (MoR = airline)     │
│                                                         │
│  APAi SUBSCRIBER (Router)                               │
│  - Brings customer to marketplace                       │
│  - Never touches proxy                                  │
│  - Never sees POS details                               │
│  - GDS contracts INTACT                                 │
│  - Earns commission                                     │
│                                                         │
│  MYSTES (Proxy Operator)                                │
│  - Operates Bright Data independently                   │
│  - Routes through optimal POS                           │
│  - Customer books on airline site                       │
│  - MYSTES not MoR                                       │
│  - Information barrier to subscribers                   │
│                                                         │
│  AIRLINE                                                │
│  - Sees normal booking from regional site               │
│  - Customer paid with their own card                    │
│  - No visibility into routing layer                     │
└─────────────────────────────────────────────────────────┘
```

---

## 46. KEY ARCHITECTURAL DECISIONS — ADDENDUM 4 (LOCKED)

58. APAi subscribers get arbitrage benefits WITHOUT proxy exposure. MYSTES handles proxy, subscriber handles customer. Clean hands.
59. Information barrier in CredentialRouter: subscribers NEVER see POS market, proxy method, or Bright Data details for proxy bookings.
60. Subscriber dashboard shows result only: "Saved $X. Commission: $Y." Method is opaque.
61. APAi pitch leads with liability shield: "Access revenue you can't legally touch on your own."
62. Open P2P marketplace structure reinforces legal separation — no "scheme," just independent marketplace participants.
63. Plausible deniability is ARCHITECTURAL, not accidental. Built into the information barrier by design.

---

## 47. PROXY DETECTION ANALYSIS — OPERATIONAL SECURITY

### One-Booking-Per-IP-Per-24h with Residential IPs
At the individual booking level: indistinguishable from a real customer.
- Residential IP in Copenhagen = real Danish household on real ISP
- Real Chrome instance via Bright Data CDP = genuine browser fingerprint
- 45-90 second session = normal human booking speed
- Real passenger info + real credit card = legitimate transaction
- Each booking: unique IP × unique customer × unique card × unique flight

### What Airlines CANNOT Detect
- No repeated IPs (each used once per 24h)
- No datacenter IP fingerprints (residential = real household)
- No bot-speed behavior (human-timed sessions)
- No automated browser signatures (real Chrome via CDP)

### What Airlines COULD Theoretically Detect at Scale (Unlikely)
1. **Billing address clustering**: Many Danish-IP bookings with US billing addresses. Mitigation: spread across 10+ POS markets so no single market shows anomaly.
2. **POS/billing mismatch rate**: Revenue management notices spike in foreign-billed cards from one POS. Mitigation: volume distribution rule (never >0.1% daily bookings per POS).
3. **Passenger nationality patterns**: Danish-IP bookings with US passport holders. Mitigation: millions of Americans live/travel abroad; airlines can't block without massive false positives.

### Threat Assessment Matrix
| Threat | Likelihood | Impact | Mitigation |
|--------|-----------|--------|------------|
| Airline detects individual booking | Near zero | Low | Residential IP + real Chrome + human timing |
| Airline notices POS/billing pattern | Low | Medium | 10+ POS markets, volume caps |
| Airline blocks Bright Data IP ranges | Very low | Medium | Residential IPs not in known ranges, secondary provider |
| Airline identifies MYSTES as entity | Low | High | No MYSTES fingerprint in transactions |
| Bright Data deplatforms MYSTES | Very low | High | Secondary provider, contractual terms |

### Key Insight: Attribution Problem
Airlines would need to identify MYSTES as an entity first. Each booking is a different IP, different customer, different card. No MYSTES signature in the transaction. Airlines see unrelated customers who happen to book from various countries. Connecting dots requires cross-referencing thousands of bookings by billing address correlation — expensive analysis that most airlines won't perform on revenue-generating bookings.

### Volume Scaling Safety
- Initial (tens-hundreds/month): Effectively undetectable
- Growth (thousands/month): Volume distribution across POS markets maintains per-market anonymity
- Scale (tens of thousands/month): Knowledge card cache reduces actual proxy bookings; 80%+ served from cached intelligence with fewer live proxy sessions

### Operational Rules (LOCKED)
1. One booking per IP per 24-hour cycle — NEVER reuse
2. Session duration: 45-90 seconds randomized — NEVER instant
3. Per-POS volume: never exceed 0.1% of airline's daily bookings in any single market
4. Residential IPs ONLY — never datacenter
5. Multi-provider: Bright Data primary + secondary provider ready
6. Airline-specific profiles: if carrier X starts blocking, auto-rotate to alternate POS markets for that carrier

---

## 48. FINAL PRODUCT ASSESSMENT — HONEST EVALUATION

### What MYSTES Actually Is (Revised Definition)
A **credential marketplace with a consumer front-end** that monetizes geographic pricing asymmetry
in airline ticketing through an invisible routing layer.

Four product axes, zero cannibalization:
1. **Travel+ Personal** ($9.99/mo) + pay-per-check ($2.99) — individual consumers
2. **Travel+ Business** ($9.99 + per-seat) — companies buying for employees
3. **B2B** ($49/$99/$199) — salesmen earning commission via referral codes
4. **APAi** ($299/$599/$999) — operators running their own OTA with liability-shielded arbitrage access

### Platform Features (Valuable WITHOUT Arbitrage)
- Trip planner with sub-parties, voting, flexible dates, managed mode
- Event hosting and ticketing (weddings, reunions, corporate)
- Corporate workspaces with travel policies and admin controls
- "Build anywhere, book cheaper through us" import model
- Social distribution engine (every share = booking funnel with referral attribution)
- Deal cards, trip cards, narrative pitch generators
- Hot routes feed, watchlists, rebooking alerts
- SharedCart for pay-for-someone checkout
- Booking lifecycle management with check-in reminders

### Arbitrage Edge (What NO Competitor Can Replicate)
- 195-country POS access via proxy — no GDS offers this
- Airline arbitrage profiles compiled from real booking data
- Confidence scoring before running proxy queries
- Round-trip leg splitting across different POS markets
- Connecting flight arbitrage with per-leg POS optimization
- Date flex arbitrage (±3 day spread optimization)
- Knowledge card flywheel: 100K+ checks = predictive, 80%+ cache hits, near-zero marginal cost
- Information barrier protecting APAi subscribers from proxy exposure
- Group booking savings multiplier
- Rebooking alerts when prices drop post-purchase

### Revenue Architecture
- Consumer booking fees (50%/45%/35%/30%/25%/20%/15% by tier)
- Travel+ subscriptions ($9.99/mo personal, per-seat business)
- Pay-per-check ($2.99) for casual users
- B2B subscriptions ($49/$99/$199/mo)
- APAi subscriptions ($299/$599/$999/mo)
- MYSTES proxy credential earnings (when proxy creds used via marketplace)
- $0 from P2P credential transactions (marketplace = subscription-only revenue)

### Moat Stack (5 Layers Deep)
1. **Data moat**: Knowledge cards from 100K+ arbitrage checks = unreplicable pricing intelligence
2. **Network moat**: APAi credential marketplace grows with every subscriber
3. **Infrastructure moat**: Multi-POS proxy + residential IP rotation = operational capability
4. **Engagement moat**: Trip planner + workspaces + social sharing = sticky user base
5. **Legal moat**: Information barrier architecture = only way for contracted OTAs to access arbitrage

---

## 49. KEY ARCHITECTURAL DECISIONS — FINAL ADDENDUM (LOCKED)

64. One booking per IP per 24h cycle, residential IPs only, 45-90s randomized sessions.
65. Per-POS volume never exceeds 0.1% of airline's daily bookings — enforced in BookingEngine.
66. Multi-proxy-provider: secondary ready for instant failover if primary blocked.
67. Airline-specific auto-rotation: if carrier blocks one POS, rotate to alternates automatically.
68. No MYSTES fingerprint in any proxy transaction — attribution problem is our protection.
69. All operational security rules LOCKED and enforced at infrastructure level, not optional.

---

## SESSION ARCHIVE TIMESTAMP
Archived: 2026-04-16 (FINAL — pre-build session)
Session: Complete Architecture Design — Trip Planner + Arbitrage Engine + Corporate + Legal
Document: 49 sections, 69 locked architectural decisions, 20 planned builds (#219-238)
Status: ARCHITECTURE COMPLETE — BUILD PHASE BEGINS
Tests at session start: 1,710 (842 SDK + 868 consumer), 0 failed

### Session Coverage (All Topics Discussed)
1. Universal share system (/i/<token>)
2. Live itinerary builder with saved search queries
3. Sub-party model for group trips
4. Managed/locked trip mode (school trips, corporate)
5. Social graph → corrected to social distribution engine
6. Event hosting with ticketing
7. "Build anywhere, book cheaper through us" model
8. Targeted arbitrage (user selects, we check)
9. Airline arbitrage profiles + confidence scoring
10. Hot routes homepage feed
11. Domestic US arbitrage confirmation (DE/ES POS test data)
12. Travel+ Business with per-seat workspace model
13. Corporate travel opportunity ($350B TAM)
14. Hybrid pricing (Travel+ subscription + $2.99 pay-per-check)
15. Cold start data seeding ($1,125 one-time)
16. Cancelled flight policy (non-refundable, rebooking opportunity)
17. GDS avoidance (proxy permanent, not bootstrap)
18. APAi as open P2P credential marketplace (subscriber-controlled terms)
19. Liability shield for APAi subscribers (information barrier)
20. Proxy operational security (IP rotation, volume distribution, detection analysis)
21. Advanced arbitrage: round-trip leg splitting, date flex, connecting flights, rebooking alerts
22. FX-aware pricing with card-type toggle
23. Revenue gates between launch phases
24. Booking lifecycle management
25. 5-layer moat analysis
