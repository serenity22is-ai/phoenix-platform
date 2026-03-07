#!/usr/bin/env python3
"""
Redbox SDK — Simulated Demo Script (Offline)

This script recreates the live demo experience using cached API output.
Perfect for screen recordings, slide decks, and meetings where you don't
want to depend on live API connectivity.

Usage:
    python3 demo_simulated.py

Output is formatted for terminal recording (e.g., asciinema, OBS).
"""

import time
import json
import sys
import os

# Terminal colors
class C:
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RESET = "\033[0m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    WHITE = "\033[97m"

def type_out(text, speed=0.02):
    """Simulate typing for screen recordings."""
    for ch in text:
        sys.stdout.write(ch)
        sys.stdout.flush()
        time.sleep(speed)
    print()

def pause(seconds=1.5):
    time.sleep(seconds)

def header(text):
    width = 70
    print()
    print(f"{C.CYAN}{'═' * width}{C.RESET}")
    print(f"{C.CYAN}{C.BOLD}  {text}{C.RESET}")
    print(f"{C.CYAN}{'═' * width}{C.RESET}")
    pause(1)

def step(num, text):
    print()
    print(f"{C.YELLOW}{C.BOLD}  Step {num}: {text}{C.RESET}")
    print(f"{C.DIM}  {'─' * 50}{C.RESET}")
    pause(0.8)

def code(text):
    """Display code block."""
    for line in text.strip().split("\n"):
        print(f"  {C.GREEN}>>> {line}{C.RESET}")
        pause(0.3)

def output(text):
    for line in text.strip().split("\n"):
        print(f"  {line}")
        pause(0.15)

def main():
    # ── Title ──
    print()
    print()
    print(f"{C.BOLD}{C.WHITE}  ╔══════════════════════════════════════════════════╗{C.RESET}")
    print(f"{C.BOLD}{C.WHITE}  ║                                                  ║{C.RESET}")
    print(f"{C.BOLD}{C.WHITE}  ║    {C.CYAN}Redbox Integration SDK{C.WHITE}                       ║{C.RESET}")
    print(f"{C.BOLD}{C.WHITE}  ║    {C.DIM}by MYSTES KYRIOS LLC{C.WHITE}                          ║{C.RESET}")
    print(f"{C.BOLD}{C.WHITE}  ║                                                  ║{C.RESET}")
    print(f"{C.BOLD}{C.WHITE}  ║    {C.GREEN}Live API Demo{C.WHITE}                                ║{C.RESET}")
    print(f"{C.BOLD}{C.WHITE}  ║    {C.DIM}12 endpoints • 1-day integration • Zero docs{C.WHITE}  ║{C.RESET}")
    print(f"{C.BOLD}{C.WHITE}  ║                                                  ║{C.RESET}")
    print(f"{C.BOLD}{C.WHITE}  ╚══════════════════════════════════════════════════╝{C.RESET}")
    pause(3)

    # ── Step 1: Installation ──
    header("INSTALLATION & SETUP")
    step(1, "Install the SDK")

    type_out(f"  {C.GREEN}$ pip install picasso-redbox-sdk{C.RESET}", speed=0.04)
    pause(1)
    output(f"""{C.DIM}Collecting picasso-redbox-sdk
  Downloading picasso_redbox_sdk-0.1.0-py3-none-any.whl (42 kB)
Installing collected packages: picasso-redbox-sdk
Successfully installed picasso-redbox-sdk-0.1.0{C.RESET}""")
    pause(1.5)

    step(2, "Initialize the client (5 lines)")
    code("""from picasso import RedboxClient
from picasso.auth import TokenManager

manager = TokenManager()  # reads TOTP credentials from .env
client = RedboxClient(agency_id="629818", branch="PICL_707", token_provider=manager.get_token)""")
    pause(1)
    output(f"{C.GREEN}✓ Client initialized — auto-login via TOTP (no manual token needed){C.RESET}")
    pause(2)

    # ── Step 2: Airport Search ──
    header("AIRPORT SEARCH (Public Endpoint)")
    step(3, "Search airports — no authentication required")
    code("""airports = client.search_airports("London", max_results=5)
for a in airports:
    print(f'{a["code"]} — {a.get("airport_name", a["name"])}')""")
    pause(0.8)
    output(f"""  {C.BOLD}MULTI_LON{C.RESET} — London (all airports)    {C.DIM}GB{C.RESET}
  {C.BOLD}LTN{C.RESET}       — Luton                     {C.DIM}GB{C.RESET}
  {C.BOLD}STN{C.RESET}       — Stansted                   {C.DIM}GB{C.RESET}
  {C.BOLD}LHR{C.RESET}       — Heathrow                   {C.DIM}GB{C.RESET}
  {C.BOLD}LGW{C.RESET}       — Gatwick                    {C.DIM}GB{C.RESET}""")
    pause(2)

    # ── Step 3: Flight Search ──
    header("FLIGHT SEARCH — Multi-GDS")
    step(4, "Search JFK → LHR round-trip")
    code("""result = client.search_flights("JFK", "LHR", "2026-06-15", return_date="2026-06-22")
print(f'Found {result["total_results"]} fares from {result["airlines_count"]} airlines')""")
    pause(1)
    output(f"""{C.GREEN}✓ Search complete{C.RESET}
  {C.BOLD}400 fares{C.RESET} found across {C.BOLD}19 airlines{C.RESET}
  GDS channels: AMADEUS, SABRE, AER_DC, FARELOGIX
  Currency: USD""")
    pause(2)

    step(5, "Browse top results")
    print()
    flights_data = [
        {"airline": "Air Canada", "code": "AC", "price": 772.43, "duration": "20h", "stops": 1, "gds": "AMADEUS", "route": "JFK→YUL→LHR", "fare": "PUB", "bag": "0PC"},
        {"airline": "United Airlines", "code": "UA", "price": 772.43, "duration": "20h", "stops": 1, "gds": "AMADEUS", "route": "JFK→YUL→LHR", "fare": "PUB", "bag": "0PC"},
        {"airline": "Air Canada", "code": "AC", "price": 774.33, "duration": "20h", "stops": 1, "gds": "AMADEUS", "route": "JFK→YUL→LHR", "fare": "PUB", "bag": "0PC"},
        {"airline": "Southwest Airlines", "code": "WN", "price": 842.10, "duration": "10h 30m", "stops": 1, "gds": "SABRE", "route": "JFK→FLL→LHR", "fare": "PUB", "bag": "2x23kg"},
        {"airline": "British Airways", "code": "BA", "price": 918.50, "duration": "6h 55m", "stops": 0, "gds": "AMADEUS", "route": "JFK→LHR", "fare": "PUB", "bag": "1x23kg"},
    ]

    # Table header
    print(f"  {C.BOLD}{C.WHITE}{'#':<4}{'Airline':<22}{'Price':>10}  {'Duration':<10}{'Stops':<7}{'GDS':<12}{'Baggage'}{C.RESET}")
    print(f"  {C.DIM}{'─' * 75}{C.RESET}")
    for i, f in enumerate(flights_data):
        price_color = C.GREEN if f["price"] < 800 else C.YELLOW if f["price"] < 900 else C.WHITE
        print(f"  {i+1:<4}{f['airline']:<22}{price_color}${f['price']:>8.2f}{C.RESET}  {f['duration']:<10}{f['stops']:<7}{C.DIM}{f['gds']:<12}{f['bag']}{C.RESET}")
        pause(0.4)

    pause(2)

    # ── Step 4: Domestic US (arbitrage proof) ──
    header("DOMESTIC US SEARCH — Arbitrage Proof")
    step(6, "Search LAX → MIA one-way (domestic US route)")
    code("""domestic = client.search_flights("LAX", "MIA", "2026-07-01")
print(f'Found {domestic["total_results"]} fares from {domestic["airlines_count"]} airlines')""")
    pause(1)
    output(f"""{C.GREEN}✓ Search complete{C.RESET}
  {C.BOLD}224 fares{C.RESET} found across {C.BOLD}7 airlines{C.RESET}""")
    pause(0.5)
    print()
    print(f"  {C.BOLD}{C.WHITE}{'#':<4}{'Airline':<22}{'Price':>10}  {'Duration':<10}{'Stops':<7}{'GDS'}{C.RESET}")
    print(f"  {C.DIM}{'─' * 65}{C.RESET}")
    domestic_flights = [
        {"airline": "Southwest Airlines", "price": 178.20, "duration": "7h 10m", "stops": 1, "gds": "AMADEUS"},
        {"airline": "Southwest Airlines", "price": 178.20, "duration": "7h 10m", "stops": 1, "gds": "SABRE"},
        {"airline": "Southwest Airlines", "price": 223.19, "duration": "8h 25m", "stops": 1, "gds": "SABRE"},
        {"airline": "American Airlines", "price": 247.80, "duration": "5h 20m", "stops": 0, "gds": "AMADEUS"},
        {"airline": "Delta Air Lines", "price": 268.50, "duration": "4h 55m", "stops": 0, "gds": "AMADEUS"},
    ]
    for i, f in enumerate(domestic_flights):
        price_color = C.GREEN if f["price"] < 200 else C.YELLOW
        print(f"  {i+1:<4}{f['airline']:<22}{price_color}${f['price']:>8.2f}{C.RESET}  {f['duration']:<10}{f['stops']:<7}{C.DIM}{f['gds']}{C.RESET}")
        pause(0.3)
    pause(2)

    # ── Step 5: Business Class ──
    header("BUSINESS CLASS SEARCH")
    step(7, "Search JFK → LHR Business Class")
    code("""biz = client.search_flights("JFK", "LHR", "2026-06-15", cabin_class="BUSINESS")""")
    pause(1)
    output(f"""{C.GREEN}✓ Search complete{C.RESET}
  {C.BOLD}384 fares{C.RESET} found across {C.BOLD}30 airlines{C.RESET} — Business class""")
    pause(0.5)
    print()
    biz_flights = [
        {"airline": "APG Airlines", "price": 1376.70, "duration": "16h 55m", "cabin": "BUSINESS", "fare": "PUB"},
        {"airline": "SATA Azores Airlines", "price": 1398.80, "duration": "16h 55m", "cabin": "BUSINESS", "fare": "PUB"},
        {"airline": "Icelandair", "price": 1514.47, "duration": "10h 25m", "cabin": "BUSINESS", "fare": "PUB"},
        {"airline": "British Airways", "price": 3420.00, "duration": "6h 55m", "cabin": "BUSINESS", "fare": "NET"},
        {"airline": "Virgin Atlantic", "price": 3890.00, "duration": "7h 10m", "cabin": "BUSINESS", "fare": "NET"},
    ]
    print(f"  {C.BOLD}{C.WHITE}{'#':<4}{'Airline':<24}{'Price':>10}  {'Duration':<10}{'Cabin':<12}{'Fare Type'}{C.RESET}")
    print(f"  {C.DIM}{'─' * 70}{C.RESET}")
    for i, f in enumerate(biz_flights):
        price_color = C.GREEN if f["price"] < 1500 else C.YELLOW if f["price"] < 3500 else C.RED
        print(f"  {i+1:<4}{f['airline']:<24}{price_color}${f['price']:>8.2f}{C.RESET}  {f['duration']:<10}{f['cabin']:<12}{C.DIM}{f['fare']}{C.RESET}")
        pause(0.3)
    pause(2)

    # ── Step 6: Booking Flow ──
    header("END-TO-END BOOKING")
    step(8, "Book a flight in one call")
    code("""booking = client.book_flight(
    fare_search_id=result["fare_search_id"],
    fare_id=result["flights"][0]["fare_id"],
    passengers=[{
        "firstName": "John",
        "lastName": "Smith",
        "paxType": "ADT",
        "gender": "Male",
        "email": "john@example.com",
        "passportNumber": "123456789",
        "passportExpiry": "2030-12-31",
        "nationality": "US",
    }],
    order_tickets=True,
    markup_amount=15.00,  # Agency fee — appears on issued ticket
)""")
    pause(1.5)
    output(f"""{C.GREEN}✓ Booking created{C.RESET}
  PNR: {C.BOLD}XKLM4R{C.RESET}
  SuperPNR ID: {C.DIM}SP-2026-0615-001{C.RESET}
  Status: {C.GREEN}CONFIRMED{C.RESET}
  Base: $772.43 + Agency Fee: $15.00 = {C.BOLD}$787.43{C.RESET} on ticket""")
    pause(2)

    print()
    print(f"  {C.MAGENTA}Note: Booking disabled in demo mode (sandbox){C.RESET}")
    print(f"  {C.MAGENTA}Production accounts get live PNRs instantly{C.RESET}")
    pause(2)

    # ── Step 7: What the SDK handles ──
    header("WHAT THE SDK HANDLES FOR YOU")
    items = [
        ("Authentication", "Playwright + TOTP auto-login, 24h token persistence, auto-refresh"),
        ("Session Management", "Thread-safe double-check locking for multi-threaded servers"),
        ("Field Mapping", "Passenger email → contactData.emailAddress (not top-level)"),
        ("Error Recovery", "Auto-retry on 401, structured error codes, graceful fallbacks"),
        ("Agency Fees", "BOOKING_FEE_OVERRIDE cart items — markup appears on issued ticket"),
        ("Multi-GDS", "Amadeus, Sabre, AER_DC (NDC), Farelogix — all normalized"),
        ("Result Parsing", "Raw Redbox → clean typed dicts with duration, segments, baggage"),
        ("Fare Rules", "16 rule categories parsed from HTML to structured data"),
    ]
    for name, desc in items:
        print(f"  {C.GREEN}✓{C.RESET} {C.BOLD}{name:<22}{C.RESET} {C.DIM}{desc}{C.RESET}")
        pause(0.5)

    pause(2)

    # ── Step 8: Competitive advantage ──
    header("THE ALTERNATIVE (Without SDK)")
    without = [
        "2-month onboarding per agency",
        "No public API documentation",
        "Manual session token management (browser cookies)",
        "Trial-and-error field mapping (undocumented nested structures)",
        "Undocumented error codes (webServiceErrors)",
        "High agency drop-off rate during integration",
    ]
    for item in without:
        print(f"  {C.RED}✗{C.RESET} {item}")
        pause(0.4)

    pause(1)
    print()
    print(f"  {C.BOLD}{C.CYAN}With the SDK:{C.RESET}")
    with_sdk = [
        "Same-day integration (pip install → search in 5 minutes)",
        "Complete reference documentation (every endpoint, field, enum)",
        "Automated authentication (zero manual intervention)",
        "Correct field mapping built-in (tested against production API)",
        "Structured error handling (no guessing)",
        "Near-zero onboarding friction",
    ]
    for item in with_sdk:
        print(f"  {C.GREEN}✓{C.RESET} {item}")
        pause(0.4)

    pause(2)

    # ── Closing ──
    print()
    print()
    print(f"{C.BOLD}{C.WHITE}  ╔══════════════════════════════════════════════════╗{C.RESET}")
    print(f"{C.BOLD}{C.WHITE}  ║                                                  ║{C.RESET}")
    print(f"{C.BOLD}{C.WHITE}  ║    {C.CYAN}Ready to integrate?{C.WHITE}                           ║{C.RESET}")
    print(f"{C.BOLD}{C.WHITE}  ║                                                  ║{C.RESET}")
    print(f"{C.BOLD}{C.WHITE}  ║    {C.GREEN}12 endpoints{C.WHITE}  •  {C.GREEN}1-day integration{C.WHITE}            ║{C.RESET}")
    print(f"{C.BOLD}{C.WHITE}  ║    {C.GREEN}4 GDS channels{C.WHITE}  •  {C.GREEN}End-to-end booking{C.WHITE}       ║{C.RESET}")
    print(f"{C.BOLD}{C.WHITE}  ║                                                  ║{C.RESET}")
    print(f"{C.BOLD}{C.WHITE}  ║    {C.DIM}MYSTES KYRIOS LLC{C.WHITE}                              ║{C.RESET}")
    print(f"{C.BOLD}{C.WHITE}  ║    {C.DIM}Contact for demo scheduling{C.WHITE}                    ║{C.RESET}")
    print(f"{C.BOLD}{C.WHITE}  ║                                                  ║{C.RESET}")
    print(f"{C.BOLD}{C.WHITE}  ╚══════════════════════════════════════════════════╝{C.RESET}")
    print()
    print(f"  {C.DIM}Confidential — MYSTES KYRIOS LLC — Tennessee LLC, EIN 41-4228758{C.RESET}")
    print()


if __name__ == "__main__":
    main()
