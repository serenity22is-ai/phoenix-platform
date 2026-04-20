# Build #200 — Complete Duffel Flight Lifecycle Integration
**Date**: 2026-03-17
**Status**: COMPLETE
**Tests**: 1,244 (746 consumer + 498 SDK), 0 failed (43 new)

## What Was Built

Full Duffel NDC flight lifecycle integration — every feature, every step, no stone unturned.
From search to ancillary services to booking to refund quotes to order changes to webhooks.

ANASTASiA now knows Duffel backwards and forwards:
- **15 agent tools** (was 10) — complete booking lifecycle
- **Knowledge card at production/0.95** (was tested/0.90)
- **Root client with 30+ methods** — covers entire Duffel API surface

## Architecture Highlights

### Source-Aware Routing
One MYSTES UI regardless of source. ANASTASiA (brain) handles complexity:
- `/api/flights/seatmap` → resolves deal_id → detects source (Duffel/Picasso) → routes to correct API
- `/api/flights/services` → Duffel available services (bags, seats, meals)
- `/api/flights/cancellation-quote` → two-step cancel: quote first, confirm after user approval
- `/api/flights/order-change` → three-step change: request → offers with fare diff → confirm
- `/api/flights/confirm-change` → accept change offer with payment if needed
- `/api/flights/add-services` → post-booking service addition
- `/api/flights/order` → full order details with documents/conditions

### Two-Step Cancellation (Refund Preview)
1. User clicks "Cancel" → MYSTES calls `get_cancellation_quote()` → shows exact refund amount
2. User confirms → MYSTES calls `confirm_cancellation()` → refund processed
3. No more "cancel and hope" — users see their money before committing

### Three-Step Order Changes
1. User requests change → `request_order_change()` with new dates/routes
2. System presents options → `get_order_change_offers()` with fare differences
3. User picks option → `confirm_order_change()` with payment if needed

### Ancillary Services in Checkout
- Page loads → `loadAncillaryServices()` fetches bags/meals/seats from Duffel
- User selects extras via checkboxes → total updates in real-time
- Selections flow through: form → deal.amadeus_offer_data → dispatcher → create_order(services=[...])

### Webhook Receiver
- `POST /webhooks/duffel` — receives Duffel order events
- Handles: `order.updated`, `order.cancelled`, `order.airline_initiated_change`
- Features: idempotency (dedup via WebhookEvent), optional token auth, email notifications
- Airline cancels flight? → Booking auto-marked cancelled + passenger notified by email

## Files Modified (8)

| File | Changes |
|------|---------|
| `duffel_client.py` | +15 methods: available_services, seat_map parser, two-step cancel, order changes, post-booking services, webhooks, balance |
| `server.py` | +7 API endpoints (seatmap/services/cancel-quote/order-change/confirm-change/add-services/order), webhook receiver, checkout UI ancillaries, booking services passthrough, cancel refund preview |
| `picasso-sdk/anastasia/dispatch/dispatcher.py` | Updated `_book_duffel_ndc` to pass services + metadata through |
| `picasso-sdk/picasso/agent/duffel_tools.py` | +5 tools: get_cancellation_quote, confirm_cancellation, get_change_offers, confirm_change, add_services (15 total) |
| `picasso-sdk/picasso/agent/duffel_knowledge.py` | Updated: 15 capabilities, two-step cancel docs, three-step change docs, post-booking services, webhook events |
| `picasso-sdk/picasso/agent/orchestrator.py` | +5 tool handlers: routing new tools to SDK client methods |
| `picasso-sdk/anastasia/modules/cards/duffel_ndc.json` | +4 capabilities, cancellation_steps, change_steps, production/0.95 readiness |
| `picasso-sdk/anastasia/modules/flight_modules.py` | Python builder synced with JSON card |

## Files Created (1)

| File | LOC | Purpose |
|------|-----|---------|
| `tests/test_duffel_lifecycle.py` | ~600 | 43 tests across 15 test classes |

## Test Coverage (43 new tests)

| Class | Tests | Coverage |
|-------|-------|---------|
| `TestDuffelClientAvailableServices` | 3 | Services grouped by type, empty list, not configured |
| `TestDuffelClientSeatMap` | 1 | Cabin/row/section parsing into renderSeatmap format |
| `TestDuffelClientCancellation` | 3 | Quote, confirm, cancel_order uses two-step |
| `TestDuffelClientOrderChange` | 3 | Request change, get offers, confirm change |
| `TestDuffelClientPostBookingServices` | 1 | Add services to existing order |
| `TestDuffelClientWebhookMgmt` | 3 | Create, list, delete webhooks |
| `TestDuffelClientCreateOrderWithServices` | 2 | Order with services, order without services |
| `TestUnifiedSeatmapEndpoint` | 2 | Auth required, Duffel routing |
| `TestServicesEndpoint` | 1 | Services by offer_id |
| `TestCancellationQuoteEndpoint` | 1 | Returns refund amount via booking_id |
| `TestDuffelWebhookReceiver` | 8 | Valid event, empty payload, idempotency, token auth, order cancelled, order updated, unhandled type |
| `TestDuffelAgentTools` | 3 | Tool count >= 15, new tools present, all have schemas |
| `TestDuffelKnowledgeCard` | 5 | Loads, new capabilities, cancel steps, change steps, production ready |
| `TestDuffelKnowledgeBase` | 5 | Two-step cancel, three-step change, post-booking services, webhooks, 15 capabilities |
| `TestDuffelFeeCalculation` | 2 | NO max cap, $3 minimum |

## Root Client Methods (DuffelClient — 30+ methods)

### Pre-Existing
search_flights, get_offer, create_offer_request, search_places, suggest_places, list_airlines, get_airline, list_airports, get_airport

### New/Updated in Build #200
| Method | Purpose |
|--------|---------|
| `get_available_services(offer_id)` | Grouped by type: baggage/seat/meal/other |
| `get_seat_map(offer_id)` | Full cabin parser → renderSeatmap() format |
| `create_order(offer_id, passengers, services, metadata)` | Now accepts services + metadata |
| `get_order(order_id)` | Enriched: documents, services, conditions |
| `list_orders(limit, after)` | Paginated order listing |
| `get_cancellation_quote(order_id)` | Returns cancellation_id + refund amount |
| `confirm_cancellation(cancellation_id)` | Executes the cancellation |
| `cancel_order(order_id)` | Two-step internally (quote + confirm) |
| `get_cancellation(cancellation_id)` | Cancellation details |
| `request_order_change(order_id, slices_to_remove, slices_to_add)` | Creates change request |
| `get_order_change_offers(change_request_id)` | Alternatives with fare differences |
| `confirm_order_change(change_offer_id, payment)` | Accepts a change offer |
| `add_services_to_order(order_id, services)` | Post-booking service addition |
| `create_webhook(url, events)` | Register webhook |
| `list_webhooks()` | List registered webhooks |
| `delete_webhook(webhook_id)` | Remove webhook |
| `get_balance()` | Account balance |

## Agent Tools (15 total)

| # | Tool | Purpose |
|---|------|---------|
| 1 | `duffel_search_places` | Airport/city autocomplete |
| 2 | `duffel_search_flights` | Flight search (300+ airlines) |
| 3 | `duffel_get_offer` | Refresh offer pricing |
| 4 | `duffel_get_services` | Available ancillary services |
| 5 | `duffel_get_seat_map` | Cabin seat layout |
| 6 | `duffel_book_flight` | Create order with services |
| 7 | `duffel_get_order` | Order details |
| 8 | `duffel_list_orders` | Paginated order list |
| 9 | `duffel_cancel_order` | One-step cancel |
| 10 | `duffel_change_order` | Request order change |
| 11 | `duffel_get_cancellation_quote` | **NEW** — Refund preview |
| 12 | `duffel_confirm_cancellation` | **NEW** — Execute cancellation |
| 13 | `duffel_get_change_offers` | **NEW** — Change alternatives |
| 14 | `duffel_confirm_change` | **NEW** — Accept change |
| 15 | `duffel_add_services` | **NEW** — Post-booking services |

## What This Does NOT Change
- `picasso_client.py` — Picasso/Redbox GDS client untouched
- `liteapi_client.py` — Hotel client untouched
- `picasso-sdk/clients/duffel.py` — SDK flight client (already complete)
- `picasso-sdk/clients/duffel_stays.py` — SDK hotel client (Build #199)
- Flight search pipeline — untouched
- Hotel search pipeline — untouched
- Existing 498 SDK tests — all pass unchanged

## What This Proves

Build #200 is the complete Duffel flight lifecycle. From initial search through ancillary services to booking to post-booking management:

1. **Search** → offers with pricing + conditions
2. **Enrich** → available services (bags, seats, meals) + seat maps
3. **Checkout** → user selects ancillaries, sees exact totals
4. **Book** → order created with selected services
5. **Manage** → get order details, add more services
6. **Cancel** → see exact refund BEFORE committing
7. **Change** → see fare differences, choose alternative, confirm
8. **Webhooks** → airline changes auto-reflected, passengers notified

Every MYSTES consumer and turnkey OTA user gets the same seamless experience regardless of whether their flight was sourced from Duffel NDC or Picasso GDS. ANASTASiA handles the complexity invisibly.
