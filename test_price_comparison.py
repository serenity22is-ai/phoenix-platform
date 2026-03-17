#!/usr/bin/env python3
"""
Flight-by-flight price comparison: Picasso vs Google Flights.
Matches exact flights by airline + departure time, shows flight numbers for verification.
"""

import sys
import os
import re
sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

from picasso_client import search_with_picasso
from google_flights_scraper import scrape_flights_sync

MEMBER_FEE = 0.35
NON_MEMBER_FEE = 0.50

ROUTES = [
    ("JFK", "LHR", "2026-03-15"),  # New York → London
    ("LAX", "NRT", "2026-03-20"),  # Los Angeles → Tokyo
    ("ORD", "FCO", "2026-04-01"),  # Chicago → Rome
]


def extract_hhmm(time_str):
    if not time_str:
        return None
    m = re.search(r'(\d{1,2}):(\d{2})', time_str)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
        # Handle AM/PM
        ampm = re.search(r'(AM|PM)', time_str, re.IGNORECASE)
        if ampm:
            period = ampm.group(1).upper()
            if period == "PM" and h != 12:
                h += 12
            if period == "AM" and h == 12:
                h = 0
        return h * 60 + mi
    return None


def get_flight_number(flight):
    """Extract primary flight number from Picasso flight."""
    segs = flight.get("segments", [])
    if segs:
        return segs[0].get("flight_number", "")
    return ""


def get_operating_info(flight):
    """Get operating carrier if codeshare."""
    segs = flight.get("segments", [])
    if segs and segs[0].get("is_codeshare"):
        return f"(op. {segs[0].get('operating_carrier', '?')})"
    return ""


def norm_airline(name):
    """Normalize airline name for matching."""
    if not name:
        return ""
    n = name.strip().lower()
    # Strip common suffixes/prefixes
    for remove in ["airlines", "air lines", "airways", " air ", " intl"]:
        n = n.replace(remove, " ")
    n = " ".join(n.split())  # Collapse whitespace

    mapping = {
        "american": "american", "aa": "american",
        "delta": "delta", "dl": "delta",
        "united": "united", "ua": "united",
        "air france": "air france", "af": "air france",
        "british": "british", "ba": "british",
        "lufthansa": "lufthansa", "lh": "lufthansa",
        "virgin atlantic": "virgin", "virgin": "virgin", "vs": "virgin",
        "jetblue": "jetblue", "b6": "jetblue",
        "klm": "klm", "kl": "klm",
        "swiss": "swiss", "lx": "swiss",
        "iberia": "iberia", "ib": "iberia",
        "turkish": "turkish", "tk": "turkish",
        "ana": "ana", "nh": "ana", "all nippon": "ana",
        "jal": "jal", "jl": "jal", "japan": "jal",
        "tap portugal": "tap", "tap": "tap", "tp": "tap",
        "aer lingus": "aer lingus", "ei": "aer lingus",
        "lot": "lot", "lo": "lot", "lot polish": "lot",
        "ita": "ita", "az": "ita",
        "austrian": "austrian", "os": "austrian",
        "condor": "condor", "de": "condor",
        "icelandair": "icelandair", "fi": "icelandair",
        "norwegian": "norwegian", "dy": "norwegian",
        "air canada": "air canada", "ac": "air canada",
        "cathay": "cathay", "cx": "cathay",
        "singapore": "singapore", "sq": "singapore",
        "korean": "korean", "ke": "korean",
        "zipair": "zipair",
    }

    for key, val in mapping.items():
        if key in n or n in key:
            return val
    return n


def match_flights(picasso_flights, google_flights, max_matches=5):
    """Match flights by airline + departure time. Return up to max_matches."""
    matches = []
    used_google = set()

    for pf in picasso_flights:
        p_airline = norm_airline(pf.get("airline_name") or pf.get("airline", ""))
        p_time = extract_hhmm(pf.get("departure_time", ""))
        if not p_time or not p_airline:
            continue

        best_match = None
        best_idx = None
        best_diff = 999

        for i, gf in enumerate(google_flights):
            if i in used_google:
                continue
            g_airline = norm_airline(gf.get("airline", ""))
            g_time = extract_hhmm(gf.get("departure_time", ""))
            if not g_time or not g_airline:
                continue

            # Must match airline
            if p_airline != g_airline:
                continue

            # Time within 15 min
            diff = abs(p_time - g_time)
            if diff > 15:
                continue

            if diff < best_diff:
                best_diff = diff
                best_match = gf
                best_idx = i

        if best_match:
            matches.append((pf, best_match))
            used_google.add(best_idx)
            if len(matches) >= max_matches:
                break

    return matches


def run_route(origin, dest, date):
    """Run comparison for a single route."""
    print(f"\n{'='*90}")
    print(f"  {origin} → {dest}  |  {date}  |  Economy  |  One-way")
    print(f"{'='*90}")

    # --- Picasso ---
    print(f"\n  Searching Picasso...")
    picasso = search_with_picasso(origin=origin, destination=dest, departure_date=date, adults=1, cabin_class="ECONOMY")

    if not picasso.get("success") or not picasso.get("flights"):
        print(f"  Picasso failed: {picasso.get('error', 'No results')}")
        return []

    p_flights = sorted(picasso["flights"], key=lambda f: f.get("price", 9999))
    print(f"  Found {len(p_flights)} fares")

    # --- Google ---
    print(f"  Scraping Google Flights (US)...")
    google = scrape_flights_sync(origin=origin, destination=dest, date=date, markets=["US"], cabin_class="economy")
    us_result = google.get("all_results", {}).get("US", {})
    g_flights = us_result.get("flights", [])

    if not g_flights:
        print(f"  Google scraping failed: {us_result.get('error', 'No flights')}")
        return []

    print(f"  Found {len(g_flights)} fares")

    # --- Match ---
    matches = match_flights(p_flights, g_flights, max_matches=5)

    if not matches:
        print(f"\n  No exact matches found by airline+time.")
        # Show unmatched for manual comparison
        print(f"\n  Top 5 Picasso fares:")
        for i, f in enumerate(p_flights[:5], 1):
            fn = get_flight_number(f)
            dep = re.search(r'(\d{2}:\d{2})', f.get("departure_time", "") or "")
            dep_str = dep.group(1) if dep else "?"
            print(f"    {i}. {fn:8s} {f.get('airline_name','?'):22s} dep {dep_str}  ${f['price']:.2f}")
        print(f"\n  Top 5 Google fares:")
        for i, f in enumerate(g_flights[:5], 1):
            dep = f.get("departure_time", "?")
            print(f"    {i}. {'':8s} {f.get('airline','?'):22s} dep {dep:>10s}  ${f['price']:.2f}")
        return []

    # --- Display ---
    print(f"\n  {'#':<3} {'FLIGHT':8s} {'AIRLINE':18s} {'DEP':>6}  {'PICASSO':>9} {'MEMBER':>9} {'NON-MBR':>9} {'GOOGLE':>9}  {'MBR SAVE':>9} {'NON SAVE':>9}")
    print(f"  {'':3s} {'':8s} {'':18s} {'':>6}  {'(cost)':>9} {'(25%)':>9} {'(50%)':>9} {'(retail)':>9}  {'':>9} {'':>9}")
    print(f"  {'-'*105}")

    route_data = []
    for i, (pf, gf) in enumerate(matches, 1):
        fn = get_flight_number(pf)
        op = get_operating_info(pf)
        airline = (pf.get("airline_name") or pf.get("airline", "?"))[:18]
        dep = re.search(r'(\d{2}:\d{2})', pf.get("departure_time", "") or "")
        dep_str = dep.group(1) if dep else "?"

        p_price = pf["price"]
        g_price = gf["price"]
        gross = g_price - p_price

        # Member pricing (25% fee)
        m_fee = round(gross * MEMBER_FEE, 2) if gross > 0 else 0
        m_price = p_price + m_fee
        m_save = g_price - m_price
        m_pct = (m_save / g_price * 100) if g_price > 0 else 0

        # Non-member pricing (50% fee)
        nm_fee = round(gross * NON_MEMBER_FEE, 2) if gross > 0 else 0
        nm_price = p_price + nm_fee
        nm_save = g_price - nm_price
        nm_pct = (nm_save / g_price * 100) if g_price > 0 else 0

        print(f"  {i:<3} {fn:8s} {airline:18s} {dep_str:>6}  ${p_price:>7.2f}  ${m_price:>7.2f}  ${nm_price:>7.2f}  ${g_price:>7.2f}  ${m_save:>+7.0f} {m_pct:>+4.1f}%  ${nm_save:>+7.0f} {nm_pct:>+4.1f}%")
        if op:
            print(f"      {op}")

        route_data.append({
            "flight": fn, "airline": airline, "dep": dep_str,
            "picasso": p_price, "member_price": m_price, "non_member_price": nm_price,
            "google": g_price, "member_save": m_save, "member_pct": m_pct,
            "non_member_save": nm_save, "non_member_pct": nm_pct,
        })

    print(f"  {'-'*105}")
    if route_data:
        avg_m_save = sum(d["member_save"] for d in route_data) / len(route_data)
        avg_m_pct = sum(d["member_pct"] for d in route_data) / len(route_data)
        avg_nm_save = sum(d["non_member_save"] for d in route_data) / len(route_data)
        avg_nm_pct = sum(d["non_member_pct"] for d in route_data) / len(route_data)
        print(f"  Member avg savings:     ${avg_m_save:+.0f} ({avg_m_pct:+.1f}%)")
        print(f"  Non-member avg savings: ${avg_nm_save:+.0f} ({avg_nm_pct:+.1f}%)")

    return route_data


def main():
    print("\n" + "="*110)
    print("  MYSTES vs GOOGLE FLIGHTS — Member / Non-Member Pricing")
    print("  Members: 25% platform fee (save 75% of arbitrage)")
    print("  Non-members: 50% platform fee (save 50% of arbitrage)")
    print("="*110)

    all_data = []
    for origin, dest, date in ROUTES:
        data = run_route(origin, dest, date)
        all_data.extend(data)

    if all_data:
        print(f"\n{'='*110}")
        print(f"  SUMMARY ACROSS ALL {len(all_data)} MATCHED FLIGHTS")
        print(f"{'='*110}")
        avg_m_save = sum(d["member_save"] for d in all_data) / len(all_data)
        avg_m_pct = sum(d["member_pct"] for d in all_data) / len(all_data)
        avg_nm_save = sum(d["non_member_save"] for d in all_data) / len(all_data)
        avg_nm_pct = sum(d["non_member_pct"] for d in all_data) / len(all_data)
        best_m = max(all_data, key=lambda d: d["member_save"])
        print(f"  Member avg savings:     ${avg_m_save:+.0f} ({avg_m_pct:+.1f}%) per ticket")
        print(f"  Non-member avg savings: ${avg_nm_save:+.0f} ({avg_nm_pct:+.1f}%) per ticket")
        print(f"  Best member deal:       {best_m['flight']} {best_m['airline']} — ${best_m['member_save']:+.0f}")
        all_m_positive = all(d["member_save"] > 0 for d in all_data)
        all_nm_positive = all(d["non_member_save"] > 0 for d in all_data)
        print(f"  All member profitable:      {'YES' if all_m_positive else 'NO'}")
        print(f"  All non-member profitable:  {'YES' if all_nm_positive else 'NO'}")
        print()


if __name__ == "__main__":
    main()
