# Picasso Redbox SDK

Python SDK for the [Picasso Travel / AERTiCKET](https://www.picassotravel.com) Redbox flight booking API.

Picasso is a 102-country POS consolidator with IATA subsidiaries in 25+ countries. The Redbox API powers their flight search, booking, and ticketing backend at `aerpackit.flightconex.de`.

This SDK provides:
- **Full API coverage** — all 12 Redbox endpoints wrapped and documented
- **Automatic auth** — Playwright + TOTP auto-login with token persistence
- **Parsed results** — raw Redbox responses parsed into clean, typed dicts
- **End-to-end booking** — search → select → book → confirm in one call
- **Thread-safe** — double-check locking for multi-threaded web servers
- **Zero platform dependencies** — standalone package, no external app required

## Installation

```bash
pip install picasso-redbox-sdk

# With auto-login support:
pip install picasso-redbox-sdk[auth]
```

## Quick Start

```python
from picasso import RedboxClient

client = RedboxClient(
    agency_id="YOUR_AGENCY_ID",
    branch="YOUR_BRANCH",
    session_token="YOUR_SESSION_TOKEN",
)

# Search flights
result = client.search_flights("JFK", "LHR", "2026-06-15")
for flight in result["flights"]:
    print(f"{flight['airline_name']} — ${flight['price']:.2f} ({flight['duration_formatted']})")

# Book a flight
booking = client.book_flight(
    fare_search_id=result["fare_search_id"],
    fare_id=result["flights"][0]["fare_id"],
    passengers=[{
        "firstName": "John",
        "lastName": "Smith",
        "paxType": "ADT",
        "gender": "Male",
        "email": "john@example.com",
    }],
)
print(f"PNR: {booking['pnr']}")
```

## Auto-Login

```python
from picasso import RedboxClient
from picasso.auth import TokenManager

manager = TokenManager()  # reads from .env
client = RedboxClient(
    agency_id="YOUR_AGENCY_ID",
    branch="YOUR_BRANCH",
    token_provider=manager.get_token,
)
```

Required `.env`:
```
PICASSO_USERNAME=your_cockpit_email@gmail.com
PICASSO_PASSWORD=your_cockpit_password
PICASSO_TOTP_SECRET=your_32_char_base32_secret
```

## API Coverage

| Endpoint | Method | SDK Method |
|----------|--------|------------|
| `/availableFare` | POST | `search_flights()` |
| `/availableFare/{id}` | POST | `get_search_results()` |
| `/availableFare/{id}/fareRules` | GET | `get_fare_rules()` |
| `/shoppingCart` | GET/POST | `get_shopping_cart()`, `create_shopping_cart()` |
| `/shoppingCart/addAndCheckOut` | POST | `add_to_cart_and_checkout()` |
| `/shoppingCart/{id}` | DELETE | `delete_shopping_cart()` |
| `/superPNR` | POST | `create_booking()` |
| `/superPNR/search` | POST | `search_bookings()` |
| `/seatmap` | POST | `get_seatmap()` |
| `/document` | POST | `generate_document()` |
| `/profile` | GET | `search_profiles()` |
| `/configuration` | GET | `get_configuration()` |

Plus high-level `book_flight()` orchestrator and public `search_airports()`.

## Documentation

- [API Reference](docs/api_reference.md) — complete endpoint docs, schemas, enums
- [examples/quickstart.py](examples/quickstart.py) — search and browse flights
- [examples/booking.py](examples/booking.py) — full booking flow

## License

Proprietary — MYSTES KYRIOS LLC
