#!/usr/bin/env python3
"""
LIVE DEMO SCRIPT — Redbox Integration SDK

Run this while screen recording for pitch to Anir / dev team / CTO.
Shows the full SDK capability against the real Redbox API.

Usage:
    python3 demo_live.py

Requirements:
    - Valid PICASSO_SESSION_TOKEN in .env (or auto-login configured)
    - pip install picasso-redbox-sdk (or run from picasso-sdk/ directory)

This script pauses between steps so you can narrate during recording.
"""

import sys
import os
import time
import json

# Add SDK to path if running from picasso-sdk/pitch/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Load env vars from parent project
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

from picasso import RedboxClient, __version__

# ─────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────

AGENCY_ID = os.environ.get("PICASSO_AGENCY_ID", "629818")
BRANCH = os.environ.get("PICASSO_BRANCH", "PICL_707")

# Demo routes
DEMO_ORIGIN = "JFK"
DEMO_DESTINATION = "LHR"
DEMO_DATE = "2026-06-15"
DEMO_RETURN = "2026-06-22"

# Pause between demo steps (seconds) — adjust for narration speed
PAUSE = 3


def banner(text):
    """Print a demo section banner."""
    width = 60
    print()
    print("=" * width)
    print(f"  {text}")
    print("=" * width)
    print()


def pause(msg="Press Enter to continue..."):
    """Pause for narration."""
    input(f"\n  >>> {msg}")
    print()


def demo():
    banner("REDBOX INTEGRATION SDK — LIVE DEMO")
    print(f"  Version: {__version__}")
    print(f"  Agency:  {AGENCY_ID}")
    print(f"  Branch:  {BRANCH}")
    print()

    # ─────────────────────────────────────────────────────────
    # Step 0: Show how simple setup is
    # ─────────────────────────────────────────────────────────
    banner("STEP 0: Setup — 3 Lines of Code")
    print("  from picasso import RedboxClient")
    print()
    print(f'  client = RedboxClient(')
    print(f'      agency_id="{AGENCY_ID}",')
    print(f'      branch="{BRANCH}",')
    print(f'  )')
    print()
    print("  That's it. Client is ready.")

    # Actually create it
    try:
        from picasso.auth import TokenManager
        manager = TokenManager()
        client = RedboxClient(
            agency_id=AGENCY_ID,
            branch=BRANCH,
            token_provider=manager.get_token,
        )
        print(f"  ✓ Client configured: {client.is_configured()}")
    except Exception:
        client = RedboxClient(
            agency_id=AGENCY_ID,
            branch=BRANCH,
        )
        print(f"  ✓ Client configured: {client.is_configured()}")

    pause()

    # ─────────────────────────────────────────────────────────
    # Step 1: Airport search (public, no auth)
    # ─────────────────────────────────────────────────────────
    banner("STEP 1: Airport Search (Public — No Auth Required)")
    print("  client.search_airports('London')")
    print()

    airports = client.search_airports("London", max_results=8)
    print(f"  Found {len(airports)} results:\n")
    for apt in airports:
        multi = " [MULTI-AIRPORT]" if apt.get("is_multi") else ""
        print(f"    {apt['code']:6s}  {apt['name'][:40]:40s}  {apt['country_name']}{multi}")

    pause()

    # ─────────────────────────────────────────────────────────
    # Step 2: Flight search
    # ─────────────────────────────────────────────────────────
    banner(f"STEP 2: Flight Search — {DEMO_ORIGIN} → {DEMO_DESTINATION}")
    print(f"  client.search_flights(")
    print(f'      origin="{DEMO_ORIGIN}",')
    print(f'      destination="{DEMO_DESTINATION}",')
    print(f'      departure_date="{DEMO_DATE}",')
    print(f'      return_date="{DEMO_RETURN}",')
    print(f"      adults=1,")
    print(f'      cabin_class="ECONOMY",')
    print(f"  )")
    print()
    print("  Searching...")

    result = client.search_flights(
        origin=DEMO_ORIGIN,
        destination=DEMO_DESTINATION,
        departure_date=DEMO_DATE,
        return_date=DEMO_RETURN,
        adults=1,
        cabin_class="ECONOMY",
        max_results=10,
    )

    if not result["success"]:
        print(f"\n  ✗ Search failed: {result.get('error')}")
        print("  (This may be a token issue — check .env)")
        pause()
        return

    flights = result["flights"]
    fare_search_id = result["fare_search_id"]

    print(f"\n  ✓ {result['total_results']} fares found from {result['airlines_count']} airlines")
    print(f"  ✓ Currency: {result['currency']}")
    print(f"  ✓ fare_search_id: {fare_search_id}")
    print(f"\n  Top {len(flights)} results:\n")

    print(f"  {'#':>3}  {'Airline':<25} {'Route':<12} {'Duration':<10} {'Stops':<6} {'GDS':<10} {'Price':>10}")
    print(f"  {'—'*3}  {'—'*25} {'—'*12} {'—'*10} {'—'*6} {'—'*10} {'—'*10}")

    for i, f in enumerate(flights, 1):
        airline = f"{f['airline_name'][:22]} ({f['airline']})"
        route = f"{f['origin']}→{f['destination']}"
        dur = f['duration_formatted'] or "—"
        stops = str(f['stops'])
        if f['stop_airports']:
            stops += f" ({','.join(f['stop_airports'])})"
        price = f"${f['price']:,.2f}"
        gds = f['gds']

        print(f"  {i:>3}  {airline:<25} {route:<12} {dur:<10} {stops:<6} {gds:<10} {price:>10}")

    pause()

    # ─────────────────────────────────────────────────────────
    # Step 3: Deep dive on cheapest flight
    # ─────────────────────────────────────────────────────────
    cheapest = flights[0]
    banner(f"STEP 3: Flight Details — {cheapest['airline_name']} ${cheapest['price']:.2f}")

    print(f"  Fare ID:      {cheapest['fare_id']}")
    print(f"  GDS:          {cheapest['gds']}")
    print(f"  Cabin:        {cheapest['cabin_class']}")
    print(f"  Fare Family:  {cheapest['fare_family']}")
    print(f"  Fare Type:    {cheapest['fare_type']}")
    print(f"  Baggage:      {cheapest['baggage_info'] or 'Not specified'}")
    print(f"  Cancel:       {cheapest['cancellation_policy'] or 'Unknown'}")
    print(f"  Rebook:       {cheapest['rebooking_policy'] or 'Unknown'}")
    print(f"  Deadline:     {cheapest['ticket_deadline'] or 'Not specified'}")
    print(f"  Seat Select:  {cheapest['seat_selection'] or 'Unknown'}")
    print()

    print(f"  Pricing Breakdown:")
    print(f"    Base Fare:   ${cheapest['base_fare']:,.2f}")
    print(f"    Tax:         ${cheapest['tax']:,.2f}")
    print(f"    Ticket Fee:  ${cheapest['ticket_fee']:,.2f}")
    print(f"    Total:       ${cheapest['price']:,.2f}")
    print()

    if cheapest.get("segments"):
        print(f"  Segments ({len(cheapest['segments'])}):")
        for j, seg in enumerate(cheapest["segments"], 1):
            codeshare = f" (operated by {seg['operating_carrier']})" if seg.get("is_codeshare") else ""
            equip = f" [{seg.get('equipment_name') or seg.get('equipment', '?')}]" if seg.get("equipment") else ""
            print(f"    {j}. {seg['flight_number']}  {seg['departure_airport']}→{seg['arrival_airport']}  {seg['cabin_class']}  class:{seg['booking_class']}{codeshare}{equip}")

    pause()

    # ─────────────────────────────────────────────────────────
    # Step 4: Fare rules
    # ─────────────────────────────────────────────────────────
    banner("STEP 4: Fare Rules")
    print(f"  client.get_fare_rules('{fare_search_id}', '{cheapest['fare_id']}')")
    print()

    rules = client.get_fare_rules(fare_search_id, cheapest["fare_id"])
    if rules["success"]:
        print(f"  ✓ {rules['rule_count']} rule categories returned:\n")
        for code, rule in list(rules["rules"].items())[:8]:
            title = rule["title"][:50]
            has_text = "✓" if rule.get("text") else "—"
            print(f"    [{code:3s}] {title:<50} content: {has_text}")
        if rules["rule_count"] > 8:
            print(f"    ... and {rules['rule_count'] - 8} more categories")
    else:
        print(f"  ✗ {rules.get('error')}")

    pause()

    # ─────────────────────────────────────────────────────────
    # Step 5: Pagination & Filters
    # ─────────────────────────────────────────────────────────
    banner("STEP 5: Pagination & Filters")
    print(f"  client.get_search_results(fare_search_id, page_number=2, show_filters=True)")
    print()

    page2 = client.get_search_results(
        fare_search_id=fare_search_id,
        page_number=2,
        results_per_page=5,
        show_filters=True,
    )
    if page2["success"]:
        print(f"  ✓ Page 2: {len(page2['flights'])} more flights")
        if page2.get("filters"):
            filter_names = list(page2["filters"].keys())
            print(f"  ✓ {len(filter_names)} filter categories available:")
            for fn in filter_names:
                opts = page2["filters"][fn]
                count = len(opts) if isinstance(opts, list) else "—"
                print(f"      {fn} ({count} options)")
        if page2.get("markup_threshold"):
            print(f"  ✓ Markup threshold: {page2['markup_threshold']}")
    else:
        print(f"  ✗ {page2.get('error')}")

    pause()

    # ─────────────────────────────────────────────────────────
    # Step 6: Booking flow (DRY RUN — shows the code, doesn't execute)
    # ─────────────────────────────────────────────────────────
    banner("STEP 6: Booking Flow (Code Preview — Not Executed)")

    print("  # One-call booking: search → cart → checkout → PNR")
    print()
    print("  booking = client.book_flight(")
    print(f'      fare_search_id="{fare_search_id}",')
    print(f'      fare_id="{cheapest["fare_id"]}",')
    print('      passengers=[{')
    print('          "firstName": "John",')
    print('          "lastName": "Smith",')
    print('          "paxType": "ADT",')
    print('          "dateOfBirth": "1990-05-15",')
    print('          "gender": "Male",')
    print('          "email": "john@example.com",')
    print('          "passportNumber": "123456789",')
    print('          "passportExpiry": "2030-12-31",')
    print('          "nationality": "US",')
    print("      }],")
    print("      order_tickets=True,")
    print("      markup_amount=15.00,  # Agency fee baked into ticket")
    print("  )")
    print()
    print('  print(f"PNR: {booking[\'pnr\']}")')
    print('  print(f"Status: {booking[\'status\']}")')
    print()
    print("  # The SDK handles:")
    print("  #   ✓ contactData.emailAddress mapping (not top-level email)")
    print("  #   ✓ apisDocument for passport (not top-level passportNumber)")
    print('  #   ✓ Gender capitalization (Male/Female, not MALE/FEMALE)')
    print("  #   ✓ BOOKING_FEE_OVERRIDE for agency markup")
    print("  #   ✓ Cart cleanup on failure")
    print("  #   ✓ SuperPNR creation with ticket issuance")
    print()
    print("  [Not executing — this would create a real booking]")

    pause()

    # ─────────────────────────────────────────────────────────
    # Step 7: Session health check
    # ─────────────────────────────────────────────────────────
    banner("STEP 7: Session & Configuration")

    config = client.get_configuration()
    if config["success"]:
        print(f"  ✓ Session active")
        conf_data = config.get("config", {})
        if conf_data:
            print(f"    Inactivity timeout: {conf_data.get('sessionInactivityTimestamp', 'N/A')}")
    else:
        print(f"  Session info: {config.get('error', 'N/A')}")

    pause()

    # ─────────────────────────────────────────────────────────
    # Summary
    # ─────────────────────────────────────────────────────────
    banner("DEMO COMPLETE")
    print("  What you just saw:")
    print()
    print("  ✓ Airport search (public, no auth)")
    print(f"  ✓ Flight search across {result['airlines_count']} airlines, {result['total_results']} fares")
    print(f"  ✓ Parsed results with pricing, segments, baggage, policies")
    print(f"  ✓ Fare rules ({rules.get('rule_count', 0)} categories)")
    print(f"  ✓ Pagination with {len(page2.get('filters', {}))} filter categories")
    print(f"  ✓ End-to-end booking code (cart → PNR)")
    print(f"  ✓ Automated session management")
    print()
    print("  Total setup: pip install + 3 lines of code")
    print("  Total time:  Under 5 minutes to first search")
    print()
    print("  ─────────────────────────────────────────────")
    print("  MYSTES KYRIOS LLC")
    print("  Redbox Integration SDK v" + __version__)
    print("  ─────────────────────────────────────────────")
    print()


if __name__ == "__main__":
    demo()
