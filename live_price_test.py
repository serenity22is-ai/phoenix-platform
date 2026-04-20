#!/usr/bin/env python3
"""
MYSTES Live Price Comparison — SerpAPI (Google) vs Duffel vs Picasso
Run: python3 live_price_test.py

Tests current API access and compares pricing across all three sources.
SerpAPI = LIVE Google Flights prices (the consumer benchmark)
Duffel  = SANDBOX (test token) — shows API works but prices are synthetic
Picasso = Live if session is valid, otherwise shows auth status
"""

import sys
import os
import re
import json
import time
sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

# Fee tiers from payments.py
FEE_TIERS = {
    "Guest (no account)": 0.50,
    "Free tier": 0.45,
    "Travel+ ($9.99/mo)": 0.35,
    "B2B Starter ($49/mo)": 0.25,
    "B2B Growth ($99/mo)": 0.20,
    "B2B Volume ($199/mo)": 0.15,
}

ROUTES = [
    ("JFK", "LHR", "2026-04-15"),  # New York → London (transatlantic)
    ("LAX", "NRT", "2026-04-20"),  # Los Angeles → Tokyo (transpacific)
]


def search_serpapi(origin, dest, date):
    """Search Google Flights via SerpAPI — LIVE real prices."""
    try:
        from serpapi_client import SerpAPIClient
        client = SerpAPIClient()
        if not client.is_configured:
            return {"success": False, "error": "SERPAPI_KEY not set", "flights": []}
        result = client.search_google_flights(origin, dest, date)
        flights = result.get("flights", [])
        insights = result.get("price_insights", {})
        return {
            "success": len(flights) > 0,
            "flights": flights,
            "price_insights": insights,
            "source": result.get("source", "serpapi"),
            "count": len(flights),
            "is_live": True,
        }
    except Exception as e:
        return {"success": False, "error": str(e), "flights": []}


def search_duffel(origin, dest, date):
    """Search Duffel NDC — SANDBOX (test token, synthetic prices)."""
    try:
        from duffel_client import DuffelClient
        client = DuffelClient()
        if not client.is_configured():
            return {"success": False, "error": "DUFFEL_ACCESS_TOKEN not set", "flights": []}

        token = os.environ.get("DUFFEL_ACCESS_TOKEN", "")
        is_test = token.startswith("duffel_test_")

        result = client.search_flights(origin, dest, date)
        flights = result.get("flights", [])
        return {
            "success": result.get("success", False),
            "flights": flights,
            "source": "duffel_ndc",
            "count": len(flights),
            "is_live": not is_test,
            "mode": "SANDBOX (test data)" if is_test else "LIVE",
            "error": result.get("error"),
        }
    except Exception as e:
        return {"success": False, "error": str(e), "flights": []}


def search_picasso(origin, dest, date):
    """Search Picasso/Redbox GDS — depends on live session token."""
    try:
        from picasso_client import PicassoClient
        client = PicassoClient()
        if not client.is_configured():
            return {"success": False, "error": "Picasso session not configured", "flights": []}

        result = client.search_flights(origin, dest, date)
        flights = result.get("flights", [])
        return {
            "success": result.get("success", False),
            "flights": flights,
            "source": "picasso_gds",
            "count": len(flights),
            "is_live": True,
            "error": result.get("error"),
        }
    except Exception as e:
        return {"success": False, "error": str(e), "flights": []}


def norm_airline(name):
    """Normalize airline name for matching."""
    if not name:
        return ""
    n = name.strip().lower()
    for remove in ["airlines", "air lines", "airways", " intl"]:
        n = n.replace(remove, " ")
    n = " ".join(n.split())

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
        "korean": "korean", "ke": "korean",
        "cathay": "cathay", "cx": "cathay",
        "singapore": "singapore", "sq": "singapore",
        "zipair": "zipair",
        "norse atlantic": "norse", "norse": "norse",
        "icelandair": "icelandair", "fi": "icelandair",
        "aer lingus": "aer lingus", "ei": "aer lingus",
        "tap portugal": "tap", "tap": "tap",
        "condor": "condor", "de": "condor",
    }

    for key, val in mapping.items():
        if key in n or n in key:
            return val
    return n


def extract_time_minutes(time_str):
    """Extract time as minutes since midnight from various formats."""
    if not time_str:
        return None
    # ISO format: 2026-04-15T14:30:00
    m = re.search(r'(\d{1,2}):(\d{2})', time_str)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
        # Handle AM/PM if present
        ampm = re.search(r'(AM|PM)', time_str, re.IGNORECASE)
        if ampm:
            period = ampm.group(1).upper()
            if period == "PM" and h != 12:
                h += 12
            if period == "AM" and h == 12:
                h = 0
        return h * 60 + mi
    return None


def match_flights(source_flights, google_flights, max_matches=8):
    """Match flights from a source against Google Flights by airline + departure time."""
    matches = []
    used_google = set()

    for sf in source_flights:
        s_airline = norm_airline(sf.get("airline") or sf.get("airline_name", ""))
        s_time = extract_time_minutes(sf.get("departure_time", ""))
        if not s_time or not s_airline:
            continue

        best_match = None
        best_idx = None
        best_diff = 999

        for i, gf in enumerate(google_flights):
            if i in used_google:
                continue
            g_airline = norm_airline(gf.get("airline", ""))
            g_time = extract_time_minutes(gf.get("departure_time", ""))
            if not g_time or not g_airline:
                continue
            if s_airline != g_airline:
                continue
            diff = abs(s_time - g_time)
            if diff > 15:
                continue
            if diff < best_diff:
                best_diff = diff
                best_match = gf
                best_idx = i

        if best_match:
            matches.append((sf, best_match))
            used_google.add(best_idx)
            if len(matches) >= max_matches:
                break

    return matches


def display_source_status(name, result, elapsed):
    """Display source search status."""
    status = "LIVE" if result.get("is_live") else "SANDBOX"
    mode = result.get("mode", status)
    if result["success"]:
        print(f"    {name:12s}: {result['count']:3d} flights  [{mode}]  ({elapsed:.1f}s)")
    else:
        print(f"    {name:12s}: FAILED — {result.get('error', 'Unknown')}  ({elapsed:.1f}s)")


def get_price(flight):
    """Extract numeric price from a flight dict."""
    p = flight.get("price", 0)
    try:
        return float(p)
    except (ValueError, TypeError):
        return 0


def run_route(origin, dest, date):
    """Run tri-source comparison for a single route."""
    print(f"\n{'='*100}")
    print(f"  {origin} -> {dest}  |  {date}  |  Economy  |  One-way  |  1 adult")
    print(f"{'='*100}")

    # Search all three sources
    print(f"\n  Searching...")

    t0 = time.time()
    google = search_serpapi(origin, dest, date)
    t_google = time.time() - t0

    t0 = time.time()
    duffel = search_duffel(origin, dest, date)
    t_duffel = time.time() - t0

    t0 = time.time()
    picasso = search_picasso(origin, dest, date)
    t_picasso = time.time() - t0

    display_source_status("Google", google, t_google)
    display_source_status("Duffel", duffel, t_duffel)
    display_source_status("Picasso", picasso, t_picasso)

    # Google price insights
    insights = google.get("price_insights", {})
    if insights:
        low = insights.get("lowest_price")
        typical = insights.get("typical_range")
        level = insights.get("price_level")
        parts = []
        if low:
            parts.append(f"lowest: ${low}")
        if typical and typical[0]:
            parts.append(f"typical: ${typical[0]}-${typical[1]}")
        if level:
            parts.append(f"level: {level}")
        if parts:
            print(f"\n  Google Insights: {' | '.join(parts)}")

    # -----------------------------------------------------------------------
    # Show Google top fares (the consumer benchmark)
    # -----------------------------------------------------------------------
    g_flights = sorted(google.get("flights", []), key=lambda f: get_price(f))
    if g_flights:
        print(f"\n  --- Google Flights (LIVE — what consumers see) ---")
        print(f"  {'#':>3}  {'AIRLINE':22s}  {'DEP':>8}  {'STOPS':>5}  {'DUR':>7}  {'PRICE':>8}")
        print(f"  {'-'*62}")
        for i, f in enumerate(g_flights[:10], 1):
            airline = (f.get("airline", "?"))[:22]
            dep = f.get("departure_time", "?")
            if "T" in dep:
                dep = dep.split("T")[1][:5]
            stops = f.get("stops", "?")
            dur = f.get("duration", "?")
            price = get_price(f)
            print(f"  {i:3d}  {airline:22s}  {dep:>8}  {stops:>5}  {dur:>7}  ${price:>7.0f}")

    # -----------------------------------------------------------------------
    # Show Duffel fares (SANDBOX)
    # -----------------------------------------------------------------------
    d_flights = sorted(duffel.get("flights", []), key=lambda f: get_price(f))
    if d_flights:
        print(f"\n  --- Duffel NDC ({duffel.get('mode', 'SANDBOX')}) ---")
        print(f"  {'#':>3}  {'AIRLINE':22s}  {'DEP':>8}  {'STOPS':>5}  {'DUR':>7}  {'PRICE':>8}")
        print(f"  {'-'*62}")
        for i, f in enumerate(d_flights[:10], 1):
            airline = (f.get("airline", "?"))[:22]
            dep = f.get("departure_time", "?")
            if "T" in dep:
                dep = dep.split("T")[1][:5]
            stops = f.get("stops", "?")
            dur = f.get("duration", "?")
            price = get_price(f)
            print(f"  {i:3d}  {airline:22s}  {dep:>8}  {stops:>5}  {dur:>7}  ${price:>7.0f}")

    # -----------------------------------------------------------------------
    # Show Picasso fares (if available)
    # -----------------------------------------------------------------------
    p_flights = sorted(picasso.get("flights", []), key=lambda f: get_price(f))
    if p_flights:
        print(f"\n  --- Picasso GDS (LIVE wholesale) ---")
        print(f"  {'#':>3}  {'AIRLINE':22s}  {'DEP':>8}  {'STOPS':>5}  {'DUR':>7}  {'PRICE':>8}")
        print(f"  {'-'*62}")
        for i, f in enumerate(p_flights[:10], 1):
            airline = (f.get("airline_name") or f.get("airline", "?"))[:22]
            dep = f.get("departure_time", "?")
            if "T" in dep:
                dep = dep.split("T")[1][:5]
            stops = f.get("stops", "?")
            dur = f.get("duration", "?")
            price = get_price(f)
            print(f"  {i:3d}  {airline:22s}  {dep:>8}  {stops:>5}  {dur:>7}  ${price:>7.0f}")

    # -----------------------------------------------------------------------
    # Flight-by-flight comparison: Duffel vs Google
    # -----------------------------------------------------------------------
    if d_flights and g_flights and duffel.get("success"):
        matches = match_flights(d_flights, g_flights)
        if matches:
            print(f"\n  --- MATCHED FLIGHTS: Duffel vs Google ({duffel.get('mode', 'SANDBOX')}) ---")
            print(f"  {'#':>3}  {'AIRLINE':18s}  {'DEP':>6}  {'DUFFEL':>9}  {'GOOGLE':>9}  {'DIFF':>9}  {'MYSTES':>9}  {'SAVE':>9}")
            print(f"  {'':>3}  {'':18s}  {'':>6}  {'(source)':>9}  {'(retail)':>9}  {'':>9}  {'(T+35%)':>9}  {'vs Goog':>9}")
            print(f"  {'-'*90}")
            for i, (df, gf) in enumerate(matches, 1):
                airline = (df.get("airline", "?"))[:18]
                dep = df.get("departure_time", "?")
                if "T" in dep:
                    dep = dep.split("T")[1][:5]
                d_price = get_price(df)
                g_price = get_price(gf)
                diff = g_price - d_price
                # MYSTES Travel+ price: source + 35% of margin (min $3)
                margin = max(0, diff)
                fee = max(3.0, margin * 0.35)
                mystes_price = d_price + fee
                save = g_price - mystes_price
                save_pct = (save / g_price * 100) if g_price > 0 else 0
                print(f"  {i:3d}  {airline:18s}  {dep:>6}  ${d_price:>7.0f}  ${g_price:>7.0f}  ${diff:>+7.0f}  ${mystes_price:>7.0f}  ${save:>+7.0f} ({save_pct:>+.1f}%)")

    # -----------------------------------------------------------------------
    # Flight-by-flight comparison: Picasso vs Google
    # -----------------------------------------------------------------------
    if p_flights and g_flights and picasso.get("success"):
        matches = match_flights(p_flights, g_flights)
        if matches:
            print(f"\n  --- MATCHED FLIGHTS: Picasso vs Google (LIVE WHOLESALE) ---")
            print(f"  {'#':>3}  {'AIRLINE':18s}  {'DEP':>6}  {'PICASSO':>9}  {'GOOGLE':>9}  {'DIFF':>9}  {'MYSTES':>9}  {'SAVE':>9}")
            print(f"  {'':>3}  {'':18s}  {'':>6}  {'(source)':>9}  {'(retail)':>9}  {'':>9}  {'(T+35%)':>9}  {'vs Goog':>9}")
            print(f"  {'-'*90}")
            for i, (pf, gf) in enumerate(matches, 1):
                airline = (pf.get("airline_name") or pf.get("airline", "?"))[:18]
                dep = pf.get("departure_time", "?")
                if "T" in dep:
                    dep = dep.split("T")[1][:5]
                p_price = get_price(pf)
                g_price = get_price(gf)
                diff = g_price - p_price
                margin = max(0, diff)
                fee = max(3.0, margin * 0.35)
                mystes_price = p_price + fee
                save = g_price - mystes_price
                save_pct = (save / g_price * 100) if g_price > 0 else 0
                print(f"  {i:3d}  {airline:18s}  {dep:>6}  ${p_price:>7.0f}  ${g_price:>7.0f}  ${diff:>+7.0f}  ${mystes_price:>7.0f}  ${save:>+7.0f} ({save_pct:>+.1f}%)")

    # -----------------------------------------------------------------------
    # MYSTES fee tier breakdown for cheapest Google flight
    # -----------------------------------------------------------------------
    if g_flights:
        cheapest_google = get_price(g_flights[0])
        # Estimate source cost (use cheapest available source)
        source_price = None
        source_name = None
        if p_flights and picasso.get("success"):
            source_price = get_price(p_flights[0])
            source_name = "Picasso GDS"
        elif d_flights and duffel.get("success"):
            source_price = get_price(d_flights[0])
            source_name = f"Duffel ({duffel.get('mode', 'SANDBOX')})"

        if source_price and source_price > 0:
            margin = cheapest_google - source_price
            print(f"\n  --- MYSTES PRICING ACROSS ALL TIERS ---")
            print(f"  Google cheapest: ${cheapest_google:.0f}  |  {source_name} cheapest: ${source_price:.0f}  |  Gross margin: ${margin:.0f}")
            print(f"  {'TIER':30s}  {'FEE%':>5}  {'FEE $':>7}  {'MYSTES':>8}  {'SAVE':>8}  {'SAVE%':>6}")
            print(f"  {'-'*75}")
            for tier_name, fee_pct in FEE_TIERS.items():
                if margin > 0:
                    fee = max(3.0, margin * fee_pct)
                else:
                    fee = 3.0
                mystes = source_price + fee
                save = cheapest_google - mystes
                save_pct = (save / cheapest_google * 100) if cheapest_google > 0 else 0
                marker = " <-- YOU" if "Travel+" in tier_name else ""
                print(f"  {tier_name:30s}  {fee_pct*100:>4.0f}%  ${fee:>6.0f}  ${mystes:>7.0f}  ${save:>+7.0f}  {save_pct:>+5.1f}%{marker}")

    return {
        "google": google,
        "duffel": duffel,
        "picasso": picasso,
    }


def main():
    print("\n" + "=" * 100)
    print("  MYSTES TRI-SOURCE PRICE COMPARISON")
    print("  Google Flights (SerpAPI) vs Duffel NDC vs Picasso GDS")
    print("  " + "-" * 60)
    token = os.environ.get("DUFFEL_ACCESS_TOKEN", "")
    duffel_mode = "SANDBOX (test data)" if token.startswith("duffel_test_") else "LIVE"
    print(f"  SerpAPI:  {'CONFIGURED' if os.environ.get('SERPAPI_KEY') else 'MISSING'}  (Google Flights = LIVE)")
    print(f"  Duffel:   {'CONFIGURED' if token else 'MISSING'}  ({duffel_mode})")
    print(f"  Picasso:  {'CONFIGURED' if os.environ.get('PICASSO_SESSION_TOKEN') else 'MISSING'}  (waiting on live access)")
    print("=" * 100)

    all_results = {}
    for origin, dest, date in ROUTES:
        result = run_route(origin, dest, date)
        all_results[f"{origin}-{dest}"] = result

    print(f"\n{'='*100}")
    print("  CONCLUSIONS")
    print(f"{'='*100}")
    print("  1. SerpAPI Google Flights = REAL consumer benchmark prices")
    print("  2. Duffel sandbox = proves API works, prices are synthetic")
    print("  3. Picasso = waiting on AERTiCKET live access")
    print("  4. To go live: swap duffel_test_ token for duffel_live_ token")
    print("  5. Picasso live = immediate wholesale pricing advantage")
    print(f"{'='*100}\n")


if __name__ == "__main__":
    main()
