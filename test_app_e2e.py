#!/usr/bin/env python3
"""
End-to-end test: Run a search through the actual MYSTES application code path.

Goes through: search_global() → Picasso (live) + Google Flights (live) → fee calculation → deal output
Shows exactly what the frontend would receive from /api/search.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

from search import search_global


def fmt_time(t):
    """Extract HH:MM from departure time string."""
    if not t:
        return "?"
    import re
    m = re.search(r'(\d{1,2}:\d{2})', str(t))
    return m.group(1) if m else "?"


def run_search(origin, dest, date, user=None):
    """Run a search and display results as the user would see them."""
    label = "MEMBER (25% fee)" if user else "NON-MEMBER (50% fee)"
    print(f"\n{'='*90}")
    print(f"  {origin} → {dest}  |  {date}  |  {label}")
    print(f"{'='*90}")

    results = search_global(origin, dest, date, fast_mode=True, user=user)

    if not results:
        print("  No results returned.")
        return []

    deals = results.get("deals", [])
    all_flights = results.get("flights", []) or results.get("all_flights", [])
    sources = results.get("data_sources", {})

    print(f"  Data sources: {sources.get('prices', '?')} (prices), {sources.get('flight_details', '?')} (details)")
    print(f"  Total flights: {len(all_flights)}, Deals (savings >= $10): {len(deals)}")

    if not deals:
        print("  No deals found with savings >= $10.")
        if all_flights:
            print(f"\n  Top 5 flights (no deal threshold met):")
            for i, f in enumerate(all_flights[:5], 1):
                fn = f.get("flight_number") or "?"
                airline = (f.get("airline") or "?")[:22]
                price = f.get("cheapest_price", 0)
                dep = fmt_time(f.get("departure_time"))
                print(f"    {i}. {fn:8s} {airline:22s} dep {dep}  ${price:.2f}")
        return []

    # --- Show deals exactly as the frontend sees them ---
    print(f"\n  {'#':<3} {'FLIGHT':8s} {'AIRLINE':20s} {'DEP':>6} {'STOPS':>5}  {'OUR PRICE':>10} {'GOOGLE':>10} {'YOU SAVE':>10} {'%':>6}")
    print(f"  {'-'*82}")

    output = []
    for i, flight in enumerate(deals[:10], 1):
        deal = flight.get("deal")
        if not deal:
            continue

        fn = (flight.get("flight_number") or "?")[:8]
        airline = (flight.get("airline") or "?")[:20]
        dep = fmt_time(flight.get("departure_time"))
        stops = flight.get("stops", "?")

        # These are the fields the frontend has access to
        google_price = deal.get("home_price", 0)
        our_cost = deal.get("arbitrage_price", 0)
        platform_fee = deal.get("platform_fee_usd", 0)
        mystes_price = our_cost + platform_fee  # What the user actually pays
        user_saves = deal.get("user_savings", 0)
        saves_pct = deal.get("user_saves_pct", 0)

        print(f"  {i:<3} {fn:8s} {airline:20s} {dep:>6} {stops:>5}  ${mystes_price:>8.2f}  ${google_price:>8.2f}  ${user_saves:>+8.2f} {saves_pct:>+5.1f}%")

        output.append({
            "flight": fn,
            "airline": airline,
            "mystes_price": mystes_price,
            "google_price": google_price,
            "user_saves": user_saves,
            "saves_pct": saves_pct,
            "platform_fee": platform_fee,
            "our_cost": our_cost,
        })

    print(f"  {'-'*82}")
    if output:
        avg_save = sum(d["user_saves"] for d in output) / len(output)
        avg_pct = sum(d["saves_pct"] for d in output) / len(output)
        avg_fee = sum(d["platform_fee"] for d in output) / len(output)
        print(f"  Avg user savings: ${avg_save:+.0f} ({avg_pct:+.1f}%)")
        print(f"  Avg platform fee: ${avg_fee:.2f}")
        all_positive = all(d["user_saves"] > 0 for d in output)
        print(f"  All profitable for user: {'YES' if all_positive else 'NO'}")

    return output


class MockMember:
    """Mock authenticated user for member pricing."""
    is_authenticated = True
    id = 1


def main():
    route = ("JFK", "LHR", "2026-03-15")

    print("\n" + "="*90)
    print("  MYSTES E2E TEST — /api/search code path")
    print("  Live Picasso + Google data → fee calculation → deal output")
    print("  Shows exactly what the frontend receives")
    print("="*90)

    # --- Non-member search (50% fee) ---
    nm_deals = run_search(*route, user=None)

    # --- Member search (25% fee) ---
    m_deals = run_search(*route, user=MockMember())

    # --- Side-by-side comparison ---
    if m_deals and nm_deals:
        print(f"\n{'='*90}")
        print(f"  MEMBER vs NON-MEMBER — Same flights, different pricing")
        print(f"{'='*90}")
        print(f"\n  {'FLIGHT':8s} {'AIRLINE':20s}  {'MEMBER':>10} {'NON-MBR':>10} {'GOOGLE':>10}  {'MBR SAVE':>10} {'NM SAVE':>10}")
        print(f"  {'-'*82}")

        for m, nm in zip(m_deals, nm_deals):
            print(f"  {m['flight']:8s} {m['airline']:20s}  ${m['mystes_price']:>8.2f} ${nm['mystes_price']:>8.2f} ${m['google_price']:>8.2f}  ${m['user_saves']:>+8.0f}   ${nm['user_saves']:>+8.0f}")

        print(f"  {'-'*82}")
        m_avg = sum(d["user_saves"] for d in m_deals) / len(m_deals)
        nm_avg = sum(d["user_saves"] for d in nm_deals) / len(nm_deals)
        print(f"  Member avg savings:     ${m_avg:+.0f}")
        print(f"  Non-member avg savings: ${nm_avg:+.0f}")
        print(f"  Upgrade incentive:      ${m_avg - nm_avg:+.0f} more per ticket as member")
        print()


if __name__ == "__main__":
    main()
