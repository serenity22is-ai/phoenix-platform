# Build #128 — Redbox API Deep Reconnaissance + AI Mastery
**Date**: 2026-02-27
**Status**: COMPLETE
**Commit**: 4a725b9

## What Was Done

### 1. Full API Surface Probe (60+ endpoints tested)
Probed every plausible Redbox endpoint systematically. Confirmed the API has exactly **12 working endpoints** — everything else returns 404:
- `/availableFare` (POST), `/availableFare/{id}` (POST), `/availableFare/{id}/fareRules` (GET)
- `/shoppingCart` (GET/POST), `/shoppingCart/addAndCheckOut` (POST), `/shoppingCart/{id}` (DELETE)
- `/superPNR` (POST), `/superPNR/search` (POST)
- `/seatmap` (POST), `/document` (POST), `/profile` (GET), `/configuration` (GET)

NOT found (all 404): clientSession, session, user, account, agency, branch, airline, airport, ancillary, baggage, insurance, reshop, exchange, refund, void, reissue, report, queue, notification, version, health, status, and 30+ others.

### 2. Keycloak JWT Decoded
- `admin-cli` ROPC grant returns a **bare JWT** with only `profile email` scope
- NO subject, NO audience, NO realm roles, NO resource access, NO custom claims
- Token TTL: 300 seconds (5 minutes)
- Confirms: Redbox permissions are server-side in the session, not JWT-encoded
- Single token architecture — NO separate auth for search vs booking

### 3. RedboxGetAvailableFareRequest Schema Discovered
Error messages revealed exact Java class: **6 known properties**:
- `resultsPerPage` (int, required)
- `pageNumber` (int >= 1, required, **1-indexed not 0**)
- `includeDetails` (boolean)
- `showFilters` (boolean)
- `sortingCriteria` (string)
- `filterCriteria` (object)

### 4. Complete Fare Object Schema Documented
From live API dump of cheapest JFK→LHR fare ($465.93 Icelandair via KEF):
- **Fare-level**: fareId, gds, total, totalTax, validatingAirline, fareFamilies, cabinClassList, fareCharacteristicList, baggageAllowance, cancellationInfo, rebookingInfo
- **priceDetails**: 30+ pricing fields per pax type including gdsFarePerPax, taxPerPax, itemized taxes (YQ/YR/Q/TAX/AY/US/XF/GB/UB/XA/XY/YC), ticketFeeDetails, markupDetails
- **Legs**: direction (outbound/inbound), subFareId, reservationSystem, itineraryList with alternative routings
- **Segments**: 20 fields — airline, flight#, equipment, bookingClass, availableSeats, duration, groundTime, fareBase, baggageAllowance, infantBaggageAllowance, numberOfTechnicalStops
- **additionalFareInfos**: 15+ types documented with fields
- **19 filter categories**: airlines, alliances, equipment, stops, price, fareFamily, GDS, and more
- **agentMarkup2Threshold**: {minValue: 0.0, maxValue: 999}

### 5. Booking Search Working
- Requires at least 1 filter parameter (locator, date range, airline, route)
- Returns `searchSummary` with 13 status fields (openBookings, cancelled, voided, issued, refunded, flown, partiallyFlown, archived, notifications, etc.)
- Paginated results via `_next` link
- Current account: 0 bookings (expected — sandbox)

### 6. MYSTES AI Enhanced
Updated system prompt with complete Redbox API knowledge:
- All 12 endpoints with parameters
- Full fare data schema (segments, pricing, taxes)
- 15+ additionalFareInfos types
- Correct passenger field mapping (contactData, apisDocument)
- Markup mechanism (BOOKING_FEE_OVERRIDE)
- 19 filter categories
- Booking flow with compliance requirements

### 7. picasso_api.md Rewritten
Complete reference updated from 254 lines to comprehensive documentation with:
- Verified endpoint map (404 results documented)
- Complete fare object schema with all nested structures
- Segment, itinerary, leg structures with every field
- priceDetails with all 30+ pricing calculations
- Filter categories and GDS types from live data
- Tax codes explained
- Auth architecture confirmed (single token, no JWT roles)

## Key Findings
1. **Redbox API is surgical** — exactly 12 endpoints, no extras
2. **No hidden booking portal** — same token, same endpoints for everything
3. **FARE_VERIFICATION_FAILED is subscription-gated**, not auth-gated
4. **pageNumber is 1-indexed** (was previously 0-indexed in some attempts)
5. **Results key is `results`** not `fareList`
6. **4 GDS channels**: AMADEUS, AER_DC, SABRE, FARELOGIX
7. **NDC fares**: AA via AER_DC (directConnectFare flag) — often cheaper base fare but higher taxes

## Files Modified
- `mystes_ai.py` — Enhanced Picasso API knowledge in system prompt
- `memory/picasso_api.md` — Complete API reference rewrite

## Files in Commit (Builds #124-128 combined)
- `picasso_client.py` — Full API client (+852 lines)
- `booking_fulfillment.py` — Picasso automated booking (+162 lines)
- `models.py` — Deal +10 cols, Booking +14 cols
- `server.py` — Confirmation page + 6 API routes (+521 lines)
- `mystes_ai.py` — 4 new tools + enhanced prompt (+428 lines)
- `main.py` — 26 airline URLs (+40 lines)
- `email_service.py` — Enhanced confirmations (+88 lines)
- `search.py` — fare_id persistence (+56 lines)
- `templates/base_template.py` — UI enhancements (+454 lines)
