# MYSTES Trip Planner — Collaborative Travel Planning
> Build #166 (2026-03-12) — Flagship feature, locked decisions

## OVERVIEW
Google Docs meets Airbnb meets Splitwise, for travel.
Collaborative trip planning with shared cart, split payments, group discounts.
Also works for local events, business meetings, dinner reservations.
The invitation IS the marketing — network effect growth built into the product.

## ACCESS MODEL
- **Travel+ subscriber**: Can CREATE and lead trip plans
- **Free members**: Can JOIN plans (if invited by subscriber)
- **Non-members**: Receive invite link → must create free account to join
- ONE subscriber unlocks the feature for the entire group

---

## CORE FEATURES

### Trip Plan (Collaborative Workspace)
- Named plans: "Japan 2027", "Bachelor Party Miami", "Q3 Team Offsite"
- Multi-destination support: Tokyo (3n) → Kyoto (2n) → Osaka (2n)
- Timeline view showing each day's flights, hotels, activities
- Any editor can add items, suggest alternatives, vote, leave notes
- ANASTASiA assists via knowledge cards (zero AI cost)
- Status flow: Draft → Finalized → Booked → Completed

### Friends System
- Add friends via username/email in dashboard
- Friend activity feed (opt-in): "Sarah saved a trip to Bali"
- Trip suggestions: "Hey Mike, want to do Cancun?" → creates shared plan
- Friend leaderboards (optional gamification)

### Roles & Permissions

| Role | Capabilities |
|------|-------------|
| **Owner** (creator, must be subscriber) | Full control: build, edit, invite, remove, finalize, checkout |
| **Editor** (invited member) | Add items, suggest alternatives, vote, set personal budget cap |
| **Viewer** (invited, hasn't joined) | See plan, accept or decline invitation |

### Alternative Options & Voting
- Add multiple options for same slot: "Hotel A vs Hotel B vs Hotel C"
- Members vote thumbs up/down on each option
- Owner can set deadline: "Vote by Friday, then I'm booking the winner"
- ANASTASiA: "Based on votes and budget caps, Option B works best for everyone"

---

## SHARED CART & PAYMENT SPLITTING

### Guest Assignment Tool
Every item gets flexible assignment — WHO uses it AND WHO pays:

| Split Method | Use Case |
|-------------|----------|
| **Even split** | Default. Room for 2 = 50/50. Tour for 4 = 25 each. |
| **Custom amounts** | "I'll cover $600, you do $420" |
| **One person pays** | Parent treating family, corporate card, partner gift |
| **Percentage** | "60/40 split" with slider interface |

### Key Distinction: Assignment vs Payment
- `user_id` = who's USING the item (whose ticket, whose room)
- `payer_id` = who's PAYING (can differ from user_id)
- Examples:
  - Couple's room: assigned to both, split 50/50
  - Mom treats family: assigned to kids, 100% Mom pays
  - Corporate flight: assigned to employee, corporate card pays

### Checkout Flow
1. Owner taps "Finalize" → cart generates per-person breakdown
2. Each member sees ONLY their portion with full transparency
3. Each member approves → pays from their own payment method
4. OR one person can "treat" selected items for others
5. Confirmations sent to each person's individual dashboard

### Per-Person Cart View
- Shows all items assigned to that person
- MYSTES savings highlighted
- Points applied (if any)
- Total due from their payment method
- Nobody sees anyone else's payment details

---

## DECLINE & CANCELLATION

| Scenario | What Happens |
|----------|-------------|
| Decline invitation (before booking) | Removed from plan, assignments auto-redistribute |
| Back out after booking | Per-item cancellation policy applies |
| Partial cancellation | Member's items refunded, remaining splits recalculated |
| Full group cancel | Standard cancellation per item, refunds to each payer |

ANASTASiA handles redistribution: "Jessica backed out. Room split changes from $340 to $510 each. OR I found a cheaper room for 2 at $420. Switch?"

---

## GROUP DISCOUNTING

| Vertical | Group Discount |
|----------|---------------|
| Activities (Viator) | 10%+ off for groups of 6+ on many tours |
| Hotels (liteAPI) | Group block rates, meeting room packages |
| Flights | Group booking fares (10+ pax on many airlines) |
| Transfers | Private van vs individual taxis — savings at 4+ |

ANASTASiA surfaces automatically: "Your group of 8 qualifies for 15% group discount on Colosseum tour — saving $96"

---

## BUSINESS USE CASE — MYSTES FOR TEAMS

### Corporate Travel
- Manager creates Trip Plan for team conference
- Assigns flights, hotel rooms, meeting space per employee
- Company card pays → receipts split per employee in dashboard
- Expense reporting built in: itemized receipts with dates, amounts, categories

### Local Events (Not Just Travel)
- Dinner reservations for client meetings
- Private event space for team offsites
- Group cooking class for team building
- Conference room booking for professional meetings
- Bill splitting with custom pay designations

### Receipt Management
Every booking generates structured receipt in dashboard:
- Exportable as PDF
- Categorized for expense reports (flight, hotel, meals, activities)
- Searchable and filterable
- Tax-deductible categories tagged
- Company name / billing address on business receipts

---

## NON-MEMBER REFERRAL FUNNEL

1. Travel+ member creates Trip Plan
2. Invites friends not on MYSTES
3. Friends get invite link: "Sarah invited you to plan Japan 2027"
4. Must create free MYSTES account to join
5. **Referrer gets**: 2,000 points per friend who signs up
6. **New member gets**: 1,000 welcome points
7. Friends experience Trip Planner → see savings → subscribe themselves
8. Each of THEM invites friends on next trip → exponential growth

### Viral Properties
- Product requires inviting others → invitation IS the distribution
- WhatsApp growth model: can't use without bringing people in
- Zero advertising spend needed — social utility drives adoption
- Each subscriber potentially onboards 3-7 new users per trip plan

---

## ANASTASiA IN TRIP PLANS (Knowledge Cards, Zero Cost)

### Smart Defaults
- Add "King Room" → auto-assigns to couple (reads traveler profiles)
- Add group activity → auto-assigns to all, split evenly
- Add single experience → assigns to person who saved it

### Budget Awareness
- "Jessica's portion is $400 over her budget cap — suggest alternatives?"
- "If you switch to this hotel, everyone saves $50/night"
- "Flight prices drop 20% on Tuesday vs Thursday — shift dates?"

### Group Optimization
- "Your group qualifies for group rate — saving $96"
- "I found a private van transfer for $80 total vs $35/person taxi = save $60"
- Bundle cross-sell: "Add airport pickup for the whole group — $15/person"

---

## DATA MODELS

### TripPlan
```python
class TripPlan(db.Model):
    id, creator_id (must be subscriber), name, description,
    cover_image, status (draft/finalized/booked/completed),
    destinations_json, start_date, end_date,
    is_template (for reusable plans), template_copies_count,
    created_at, updated_at
```

### TripMember
```python
class TripMember(db.Model):
    id, trip_plan_id, user_id, role (owner/editor/viewer),
    budget_cap (optional), invitation_status (pending/accepted/declined),
    invited_at, joined_at
```

### TripItem
```python
class TripItem(db.Model):
    id, trip_plan_id, added_by_user_id, vertical (flight/hotel/activity/car/event),
    item_data (JSON — provider data, pricing, details),
    destination_index, day_number (optional),
    is_alternative, alternative_group_id,
    votes_json ({user_id: up/down}),
    status (proposed/approved/booked/cancelled),
    created_at
```

### TripCart
```python
class TripCart(db.Model):
    id, trip_plan_id, status (open/checkout/paid/partial),
    total_amount, currency, per_person_breakdown_json,
    finalized_at
```

### TripCartAssignment
```python
class TripCartAssignment(db.Model):
    id, trip_cart_id, trip_item_id,
    user_id,            # who's USING this item
    payer_id,           # who's PAYING (can differ)
    split_method (even/custom/single/percentage),
    amount_owed, percentage (nullable),
    payment_status (pending/approved/paid/refunded),
    stripe_payment_intent_id,
    receipt_pdf_url (nullable)
```

### TripReceipt
```python
class TripReceipt(db.Model):
    id, trip_plan_id, user_id, trip_cart_assignment_id,
    receipt_number (MYS-YYYY-NNNNN),
    items_json, subtotal, savings, points_applied, total_charged,
    payment_method_last4, company_name (nullable for business),
    pdf_url, created_at
```

---

## REUSABLE PLANS & TEMPLATES

### After Booking
- Trip Plan structure saved permanently (even after completion)
- "Repeat This Trip" → creates new plan with same structure, refreshed prices
- "Add Members" → invite new people to existing plan
- "Copy as Template" → strip personal details, make shareable

### Public Templates
- Users can publish trip plans as templates
- "1,200 people copied this 10-day Japan itinerary"
- Template creator earns 100 points per copy (passive rewards)
- Popular templates featured on homepage / vertical pages
- ANASTASiA suggests relevant templates: "Planning Tokyo? Here are top-rated itineraries"

### Template Marketplace (Future)
- Power users / travel bloggers create and share plans
- Potential for premium templates (paid, revenue share)
- B2B agencies can publish curated packages as templates
