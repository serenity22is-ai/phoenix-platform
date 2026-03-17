# Picasso Redbox SDK — API Reference

## Installation

```bash
pip install picasso-redbox-sdk

# With auto-login support (Playwright + TOTP):
pip install picasso-redbox-sdk[auth]
```

## Quick Start

```python
from picasso import RedboxClient

client = RedboxClient(
    agency_id="YOUR_AGENCY_ID",
    branch="YOUR_BRANCH",
    session_token="YOUR_TOKEN",
)

result = client.search_flights("JFK", "LHR", "2026-06-15")
for flight in result["flights"]:
    print(f"{flight['airline_name']} — ${flight['price']:.2f}")
```

---

## RedboxClient

### Constructor

```python
RedboxClient(
    agency_id: str,              # Required — your Picasso agency ID
    branch: str,                 # Required — your Picasso branch code
    session_token: str = None,   # Static session token
    token_provider: Callable = None,  # Dynamic token (e.g., TokenManager.get_token)
    base_url: str = None,        # Override Redbox API URL
)
```

Token resolution order:
1. `token_provider()` callable (if provided)
2. `session_token` parameter
3. `PICASSO_SESSION_TOKEN` environment variable

### Endpoints

The Redbox API has exactly **12 working endpoints**. This SDK wraps all of them.

---

## Flight Search

### `search_flights()`

Two-step search with automatic retry on token expiration.

```python
result = client.search_flights(
    origin="JFK",                    # IATA code
    destination="LHR",               # IATA code
    departure_date="2026-06-15",     # YYYY-MM-DD
    return_date="2026-06-22",        # Optional — omit for one-way
    adults=1,                        # ADT count
    children=0,                      # CHD count
    infants=0,                       # INF count
    cabin_class="ECONOMY",           # ECONOMY/PREMIUM_ECONOMY/BUSINESS/FIRST
    max_results=20,                  # Max per page (capped at 50)
    nonstop_only=False,              # Filter non-stop
    fare_types=["PUB", "NET"],       # PUB/NET/NEG/etc.
)
```

**Returns:**
```python
{
    "success": True,
    "flights": [...],          # Parsed flight objects (see below)
    "source": "redbox",
    "origin": "JFK",
    "destination": "LHR",
    "date": "2026-06-15",
    "return_date": "2026-06-22",
    "total_results": 156,      # Total fares found
    "airlines_count": 12,      # Airlines represented
    "currency": "USD",
    "fare_search_id": "J3684009732p",  # Use for pagination/booking
}
```

### Flight Object Schema

Each flight in `result["flights"]` has:

| Key | Type | Description |
|-----|------|-------------|
| `fare_id` | str | Unique fare identifier (use for booking) |
| `offer_id` | str | Alias for fare_id |
| `gds` | str | GDS channel: AMADEUS, AER_DC, SABRE, FARELOGIX |
| `airline` | str | Validating airline IATA code |
| `airline_name` | str | Full airline name |
| `origin` | str | Departure airport IATA |
| `destination` | str | Arrival airport IATA |
| `departure_time` | str | ISO timestamp |
| `arrival_time` | str | ISO timestamp |
| `duration` | str | ISO 8601 duration (PT10H25M) |
| `duration_minutes` | int | Total minutes |
| `duration_formatted` | str | Human-readable ("10h 25m") |
| `stops` | int | Number of stops |
| `stop_airports` | list | Stop airport IATA codes |
| `price` | float | Total price including taxes |
| `base_fare` | float | GDS base fare per pax |
| `tax` | float | Total tax |
| `ticket_fee` | float | Ticket issuance fee |
| `currency` | str | Currency code |
| `cabin_class` | str | ECONOMY/BUSINESS/etc. |
| `fare_family` | str | Airline fare family name |
| `fare_type` | str | PUB/NET/NEG |
| `baggage_info` | str | e.g., "0PC", "1x23kg" |
| `is_cheapest` | bool | Cheapest fare flag |
| `seat_selection` | dict | {available, seatmap, cancelable} |
| `cancellation_policy` | str | POSSIBLE/NOT_POSSIBLE/UNKNOWN |
| `rebooking_policy` | str | POSSIBLE/NOT_POSSIBLE/UNKNOWN |
| `ticket_deadline` | str | ISO timestamp for ticketing deadline |
| `legs` | list | Parsed leg objects |
| `segments` | list | Flat list of all segments |
| `return_departure_time` | str | Return leg departure (round-trip) |
| `return_stops` | int | Return leg stops |
| `price_details` | list | Raw Redbox priceDetails for advanced use |

### Segment Object Schema

Each segment in `flight["segments"]`:

| Key | Type | Description |
|-----|------|-------------|
| `carrier` | str | Marketing airline IATA |
| `carrier_name` | str | Marketing airline name |
| `flight_number` | str | Full flight number (e.g., "BA178") |
| `departure_airport` | str | Departure IATA |
| `arrival_airport` | str | Arrival IATA |
| `departure_time` | str | ISO timestamp |
| `arrival_time` | str | ISO timestamp |
| `duration` | str | ISO 8601 segment duration |
| `cabin_class` | str | ECONOMY/BUSINESS/etc. |
| `booking_class` | str | GDS booking class (Y, B, M, etc.) |
| `fare_base` | str | Fare basis code |
| `equipment` | str | Aircraft type code (32Q, 77W, etc.) |
| `equipment_name` | str | Aircraft name (Airbus A321neo) |
| `available_seats` | int | Seats remaining (may be None for NDC) |
| `baggage_allowance` | str | Segment-level baggage |
| `ground_time` | str | Layover time (connecting segments) |
| `operating_carrier` | str | Operating airline IATA |
| `is_codeshare` | bool | True if codeshare flight |

### `get_search_results()`

Paginate or filter an existing search.

```python
page2 = client.get_search_results(
    fare_search_id="J3684009732p",
    page_number=2,              # 1-indexed (MUST be >= 1)
    results_per_page=20,
    include_details=True,       # Include additionalFareInfos
    show_filters=True,          # Include 19 filter categories
    sorting_criteria="PRICE",
    filter_criteria={},
)
```

### `search_airports()`

Public endpoint — no auth required.

```python
airports = client.search_airports("London", max_results=10)
# Returns: [{"code": "LHR", "name": "London", "airport_name": "Heathrow", ...}]
```

---

## Fare Rules

### `get_fare_rules()`

```python
rules = client.get_fare_rules(
    fare_search_id="J3684009732p",
    fare_id="J3684009732p_ROUNDTRIP_0",
)
# Returns: {"success": True, "rules": {"PE": {"title": "Penalties", "text": "..."}, ...}}
```

**Rule categories:** RU, FL, AP, MN, MX, PE, SR, and more. Text is HTML-formatted.

---

## Seatmap

### `get_seatmap()`

```python
seatmap = client.get_seatmap(
    airline_code="AA",
    flight_number="1758",
    departure="JFK",
    destination="LHR",
    departure_date="2026-06-15",
    booking_class="Y",
    cabin_class="ECONOMY",
    reservation_system="AMADEUS",  # AMADEUS/SABRE/AER_DC/FARELOGIX
)
```

---

## Booking

### `book_flight()` — High-Level (Recommended)

End-to-end booking in one call: cart + checkout + superPNR.

```python
booking = client.book_flight(
    fare_search_id="J3684009732p",
    fare_id="J3684009732p_ROUNDTRIP_0",
    passengers=[
        {
            "firstName": "John",
            "lastName": "Smith",
            "paxType": "ADT",        # ADT/CHD/INF
            "dateOfBirth": "1990-05-15",
            "gender": "Male",         # Male/Female (capitalized!)
            "title": "MR",
            "email": "john@example.com",
            "phone": "+12125551234",
            # For international flights:
            "passportNumber": "123456789",
            "passportExpiry": "2030-12-31",
            "nationality": "US",
        }
    ],
    order_tickets=True,
    markup_amount=15.00,  # BOOKING_FEE_OVERRIDE (max $999)
)

if booking["success"]:
    print(f"PNR: {booking['pnr']}")
    print(f"SuperPNR ID: {booking['super_pnr_id']}")
```

### Passenger Field Mapping

Redbox uses specific field structures. The SDK handles mapping automatically:

| Your Input | Redbox Field | Notes |
|------------|-------------|-------|
| `email` | `contactData.emailAddress` | NOT top-level `email` |
| `phone` | `contactData.phoneNumber` | NOT top-level `phone` |
| `passportNumber` | `apisDocument.documentNumber` | Nested, NOT top-level |
| `passportExpiry` | `apisDocument.expiryDate` | ISO date |
| `nationality` | `apisDocument.nationality` | Country code |
| `gender` | `gender` | Must be "Male"/"Female" (capitalized) |
| `paxType` | `paxType` | GDS codes: ADT/CHD/INF/YTH/STU/SEN |

### BOOKING_FEE_OVERRIDE

The `markup_amount` parameter adds a BOOKING_FEE_OVERRIDE cart item that increases
the ticket's displayed price. This is how agencies add their margin — the issued
ticket shows the customer-facing price, not the wholesale fare.

- `agentMarkup2Threshold`: min 0.0, max 999
- Proven: base $303.50 + $15 override = $318.50 on ticket

### Lower-Level Booking Methods

```python
# Step 1: Add to cart + checkout
cart = client.add_to_cart_and_checkout(
    fare_search_id, fare_id, passengers,
    markup_amount=15.00,
)

# Step 2: Create booking
booking = client.create_booking(
    shopping_cart_id=cart["cart_id"],
    order_tickets=True,
)

# Cart management
client.get_shopping_cart()
client.create_shopping_cart(items=[...])
client.delete_shopping_cart(cart_id)
```

### Cart Item Types (25 known)

All require a `type` discriminator:

| Type | Status | Purpose |
|------|--------|---------|
| FLIGHT | Implemented | Flight selection (fareSearchId, fareIds, itineraryIds) |
| PASSENGER | Implemented | Passenger data (name, DOB, contact, passport) |
| BOOKING_FEE_OVERRIDE | Implemented | Agency markup (value, flightIdList) |
| INSURANCE | Implemented | Travel insurance (insuranceId, planName, passengerIndices) |
| ANCILLARY | Implemented | Ancillary services (ancillaryId, serviceType, segmentIds) |
| SEAT | Implemented | Seat selection (seatNumber, segmentId, passengerIndex) |
| FREQUENT_FLYER | Implemented | Loyalty program (frequentFlyerNumber, airlineCode) |
| HOTEL | Known | Hotel room |
| PAYMENT | Known | Payment method |

### Cart Item Builders

The SDK provides static methods to build cart items:

```python
# Travel insurance
item = RedboxClient.build_insurance_item(
    insurance_id="INS_123",
    plan_name="Travel Protection Plus",
    passenger_indices=[0, 1],  # Which passengers (None = all)
    fare_id="J3684009732p_ROUNDTRIP_0",
    price=29.99,
    provider="Allianz",
    coverage_type="COMPREHENSIVE",
)

# Ancillary service (baggage, meal, etc.)
item = RedboxClient.build_ancillary_item(
    ancillary_id="ANC_456",
    service_type="BAGGAGE",
    segment_ids=["seg1", "seg2"],
    passenger_indices=[0],
    quantity=1,
    price=35.00,
    description="1 checked bag 23kg",
)

# Seat selection
item = RedboxClient.build_seat_item(
    seat_number="14A",
    segment_id="seg1",
    passenger_index=0,
    price=15.00,
)

# Frequent flyer
item = RedboxClient.build_frequent_flyer_item(
    ff_number="AA12345678",
    airline_code="AA",
    passenger_index=0,
)
```

### Booking with Extras

```python
# Build extra items
extras = [
    RedboxClient.build_insurance_item("INS_123", plan_name="Comprehensive"),
    RedboxClient.build_ancillary_item("BAG_001", "BAGGAGE", price=35.00),
    RedboxClient.build_seat_item("14A", "seg1", passenger_index=0),
]

# Book with extras in one call
booking = client.book_flight(
    fare_search_id="J3684009732p",
    fare_id="J3684009732p_ROUNDTRIP_0",
    passengers=[...],
    markup_amount=15.00,
    extra_cart_items=extras,  # All extras added to cart
)
```

---

## Extras Discovery

### `get_extras()`

Discover available insurance, ancillaries, and seats for a specific fare.

```python
extras = client.get_extras(
    fare_search_id="J3684009732p",
    fare_id="J3684009732p_ROUNDTRIP_0",
)

# Insurance plans
for plan in extras["insurance_options"]:
    print(f"  {plan['plan_name']} — ${plan['price_per_pax']}/person ({plan['coverage_type']})")

# Ancillary services
for anc in extras["ancillary_options"]:
    print(f"  {anc['service_type']}: {anc['description']} — ${anc['price']}")
```

---

## Booking Management

### `get_booking_details()`

Get full details for a booking.

```python
details = client.get_booking_details(super_pnr_id="SPR123")
print(f"Status: {details['status']}")
print(f"PNR: {details['pnr']}")
print(f"Tickets: {details['tickets']}")
print(f"Insurance: {details['insurance']}")
```

### `cancel_booking()`

Cancel a booking. Check fare rules first for penalty information.

```python
result = client.cancel_booking(
    super_pnr_id="SPR123",
    reason="Customer requested cancellation",
)
if result["success"]:
    print(f"Cancelled. Refund eligible: {result['refund_eligible']}")
    print(f"Penalty: ${result['penalty_amount']}")
```

### `void_ticket()`

Void tickets within the airline void window (typically 24 hours).
No penalties — full refund.

```python
result = client.void_ticket(super_pnr_id="SPR123")
if result["success"]:
    print("Tickets voided — full refund")
```

### `request_refund()`

Request a refund for a cancelled booking.

```python
result = client.request_refund(
    super_pnr_id="SPR123",
    refund_type="FULL",
    reason="Trip cancellation",
)
if result["success"]:
    print(f"Refund ref: {result['refund_reference']}")
    print(f"Amount: ${result['refund_amount']}")
    print(f"Processing: {result['estimated_processing']}")
```

---

## Booking Search

### `search_bookings()`

At least one filter parameter required.

```python
bookings = client.search_bookings(
    locator="ABC123",          # PNR/record locator
    departure="JFK",           # Airport code
    airline="AA",              # Validating airline
    date_from="2026-01-01",    # Booking creation date
    date_to="2026-12-31",
)
```

**Response includes searchSummary with 13 status fields:**
openBookings, cancelled, voided, openOrders, issued, refunded,
flown, partiallyFlown, archived, notifications, totalPnr, totalSuperPnr.

---

## Documents

### `generate_document()`

```python
doc = client.generate_document(
    document_type="CONFIRMATION",  # ITINERARY/OFFER/CONFIRMATION/TRAVEL_REGISTRATION
    super_pnr_id="...",
    display_prices=True,
    language="en",
    email_recipients=["customer@example.com"],
    hide_agency_fees=True,
)
```

Returns PDF bytes or JSON depending on the response content type.

---

## Profiles & Configuration

```python
# Search traveler profiles
profiles = client.search_profiles("John Smith")

# Get session configuration
config = client.get_configuration()
```

---

## TokenManager (Auto-Login)

Requires `pip install picasso-redbox-sdk[auth]`.

```python
from picasso.auth import TokenManager

manager = TokenManager(
    username="your@email.com",         # or PICASSO_USERNAME env
    password="your_password",          # or PICASSO_PASSWORD env
    totp_secret="YOUR_BASE32_SECRET",  # or PICASSO_TOTP_SECRET env
)

# Get token (auto-refreshes when expired)
token = manager.get_token()

# Check token health
health = manager.check_token_health()
print(health)  # {"healthy": True, "detail": "Token valid — 156 fares returned"}

# Invalidate (forces refresh on next call)
manager.invalidate()

# Diagnostics
status = manager.get_status()
```

### Auth Strategies

1. **Playwright + TOTP** (primary): Headless browser login with TOTP 2FA code generated
   locally via pyotp. No email needed. Fastest strategy.

2. **Playwright + Email OTP** (fallback): Headless browser login with email OTP read via
   Gmail IMAP. Requires `PICASSO_GMAIL_APP_PASSWORD`.

3. **Manual token** (last resort): Static `PICASSO_SESSION_TOKEN` from .env.

### Token Persistence

Tokens are persisted to `.picasso_token.json` with 24-hour TTL:
```json
{
  "token": "abc123...",
  "obtained_at": 1709000000.0,
  "expires_at": 1709086400.0,
  "strategy": "playwright_totp"
}
```

---

## GDS Channels

| Channel | Type | Notes |
|---------|------|-------|
| AMADEUS | Traditional GDS | Often lowest prices |
| SABRE | Traditional GDS | Major US GDS |
| AER_DC | AERTiCKET Direct Connect | NDC channels (AA, UA, etc.) |
| FARELOGIX | NDC aggregator | Alternative NDC path |

NDC fares (AER_DC/FARELOGIX) may have cheaper base fares but higher taxes.
They may also omit `availableSeats` data.

---

## Enums Reference

### Passenger Types
ADT (adult), CHD (child), INF (infant), YTH (youth), STU (student),
SEN (senior), MIL (military), EMI, LBR, SEA, TEA

### Cabin Classes
ECONOMY, PREMIUM_ECONOMY, BUSINESS, FIRST

### Fare Characteristics
PUB, NET, NEG, PUBNEG, LOW, MIX, COR, WEB, TOP, DIR, STA, VFR,
CRU, SEA, STU, PEP, CHA, INT, MIL, NGO, RAIL

### Document Types
ITINERARY, OFFER, CONFIRMATION, TRAVEL_REGISTRATION

### Alliances
STARALLIANCE, ONEWORLD, SKYTEAM, A++ (multi-alliance)

---

## Utilities

```python
# Parse ISO 8601 duration to minutes
minutes = RedboxClient.parse_iso_duration("PT10H25M")  # 625

# Format ISO 8601 duration to human-readable
formatted = RedboxClient.format_iso_duration("PT10H25M")  # "10h 25m"
```

---

## Error Handling

All methods return a dict with `"success": True/False`. On failure:

```python
result = client.search_flights("JFK", "LHR", "2026-06-15")
if not result["success"]:
    print(f"Error: {result['error']}")
```

Common Redbox errors:
- `FARE_VERIFICATION_FAILED`: Sandbox limitation — cart operations need active subscription
- `401/403`: Token expired — SDK auto-retries once on search
- `webServiceErrors`: API-level errors with description + detailMessages

---

## Sandbox vs Production

| Feature | Sandbox | Production |
|---------|---------|------------|
| Flight search | Works | Works |
| Fare rules | Works | Works |
| Seatmap | Works | Works |
| Cart creation (empty) | Works | Works |
| Cart + flight items | FARE_VERIFICATION_FAILED | Works |
| Booking (superPNR) | Requires active subscription | Works |
| Documents | Requires booking | Works |
