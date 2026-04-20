#!/usr/bin/env python3
"""
LIVE Picasso vs SerpAPI (Google Flights) price comparison.
Domestic US routes. Raw numbers. No estimates. No markup.

Tests whether Picasso prices are genuinely cheaper than Google.
"""
import sys
import os
import re
import json
import time
sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

from picasso_client import PicassoClient
from serpapi_client import SerpAPIClient

# Domestic routes — 3-4 weeks out for stable pricing
ROUTES = [
    ("JFK", "LAX", "2026-04-15"),
    ("ORD", "MIA", "2026-04-15"),
    ("ATL", "SFO", "2026-04-15"),
    ("DFW", "BOS", "2026-04-15"),
]

# Also test international for comparison
INTL_ROUTES = [
    ("JFK", "LHR", "2026-04-15"),
    ("LAX", "NRT", "2026-04-20"),
]

ALL_ROUTES = ROUTES + INTL_ROUTES


def extract_hhmm(time_str):
    if not time_str:
        return None
    m = re.search(r'(\d{1,2}):(\d{2})', str(time_str))
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
        ampm = re.search(r'(AM|PM)', str(time_str), re.IGNORECASE)
        if ampm:
            period = ampm.group(1).upper()
            if period == "PM" and h != 12:
                h += 12
            if period == "AM" and h == 12:
                h = 0
        return h * 60 + mi
    return None


def norm_airline(name):
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
        "southwest": "southwest", "wn": "southwest",
        "jetblue": "jetblue", "b6": "jetblue",
        "spirit": "spirit", "nk": "spirit",
        "frontier": "frontier", "f9": "frontier",
        "alaska": "alaska", "as": "alaska",
        "air france": "air france", "af": "air france",
        "british": "british", "ba": "british",
        "virgin atlantic": "virgin", "vs": "virgin",
        "ana": "ana", "nh": "ana", "all nippon": "ana",
        "jal": "jal", "jl": "jal", "japan": "jal",
        "lufthansa": "lufthansa", "lh": "lufthansa",
    }
    for key, val in mapping.items():
        if key in n or n in key:
            return val
    return n


def run_comparison(origin, dest, date):
    print(f"\n{'='*100}")
    print(f"  {origin} -> {dest}  |  {date}  |  Economy  |  One-way  |  1 Adult")
    print(f"{'='*100}")

    # --- PICASSO ---
    print(f"\n  [PICASSO] Searching Redbox sandbox...")
    try:
        pc = PicassoClient()
        picasso_result = pc.search_flights(
            origin=origin, destination=dest,
            departure_date=date, adults=1,
            cabin_class="ECONOMY"
        )
        if not picasso_result.get("success"):
            print(f"  [PICASSO] FAILED: {picasso_result.get('error', 'Unknown')}")
            return None
        p_flights = picasso_result.get("flights", [])
        print(f"  [PICASSO] Got {len(p_flights)} results")
    except Exception as e:
        print(f"  [PICASSO] ERROR: {e}")
        return None

    # --- SERPAPI ---
    print(f"  [SERPAPI] Fetching Google Flights prices...")
    try:
        serp = SerpAPIClient()
        serp_result = serp.search_google_flights(
            origin=origin, destination=dest,
            date=date, cabin_class="economy",
            adults=1
        )
        g_flights = serp_result.get("flights", [])
        cached = "CACHE" if serp_result.get("cached") else "LIVE"
        print(f"  [SERPAPI] {cached}: Got {len(g_flights)} results")

        # Price insights
        insights = serp_result.get("price_insights", {})
        if insights.get("lowest_price"):
            print(f"  [SERPAPI] Google price insights: lowest=${insights['lowest_price']}, "
                  f"typical={insights.get('typical_range', 'N/A')}, "
                  f"level={insights.get('price_level', 'N/A')}")
    except Exception as e:
        print(f"  [SERPAPI] ERROR: {e}")
        return None

    if not p_flights or not g_flights:
        print(f"  No data from one or both sources.")
        return None

    # --- MATCH ---
    matches = []
    used_google = set()
    for pf in sorted(p_flights, key=lambda f: f.get("price", 9999)):
        p_airline = norm_airline(pf.get("airline_name") or pf.get("airline", ""))
        p_time = extract_hhmm(pf.get("departure_time", ""))
        if not p_time or not p_airline:
            continue

        best_match = None
        best_idx = None
        best_diff = 999

        for i, gf in enumerate(g_flights):
            if i in used_google:
                continue
            g_airline = norm_airline(gf.get("airline", ""))
            g_time = extract_hhmm(gf.get("departure_time", ""))
            if not g_time or not g_airline:
                continue
            if p_airline != g_airline:
                continue
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

    print(f"\n  Matched {len(matches)} flights by airline + departure time (±15 min)")

    if not matches:
        # Show top 5 from each for manual comparison
        print(f"\n  TOP 5 PICASSO (sorted by price):")
        for i, f in enumerate(sorted(p_flights, key=lambda x: x.get("price", 9999))[:5], 1):
            dep = extract_hhmm(f.get("departure_time", ""))
            dep_str = f"{dep//60:02d}:{dep%60:02d}" if dep else "?"
            fare_type = f.get("fare_type", "?")
            print(f"    {i}. {f.get('airline_name','?'):20s} dep {dep_str}  "
                  f"total=${f.get('price',0):>7.2f}  base=${f.get('base_fare',0):>7.2f}  "
                  f"tax=${f.get('tax',0):>7.2f}  fee=${f.get('ticket_fee',0):>5.2f}  [{fare_type}]")

        print(f"\n  TOP 5 GOOGLE (sorted by price):")
        for i, f in enumerate(sorted(g_flights, key=lambda x: x.get("price", 9999))[:5], 1):
            print(f"    {i}. {f.get('airline','?'):20s} dep {f.get('departure_time','?'):>10s}  "
                  f"price=${f.get('price',0):>7.2f}  stops={f.get('stops',0)}")
        return None

    # --- DISPLAY MATCHES ---
    print(f"\n  {'#':<3} {'AIRLINE':20s} {'DEP':>6}  {'PIC TOTAL':>10} {'PIC BASE':>10} {'PIC TAX':>10} {'PIC FEE':>8} {'TYPE':>5}  {'GOOGLE':>10}  {'DIFF':>10}")
    print(f"  {'-'*115}")

    results = []
    for i, (pf, gf) in enumerate(matches, 1):
        airline = (pf.get("airline_name") or pf.get("airline", "?"))[:20]
        dep = extract_hhmm(pf.get("departure_time", ""))
        dep_str = f"{dep//60:02d}:{dep%60:02d}" if dep else "?"

        p_total = pf.get("price", 0)
        p_base = pf.get("base_fare", 0)
        p_tax = pf.get("tax", 0)
        p_fee = pf.get("ticket_fee", 0)
        fare_type = pf.get("fare_type", "?")
        g_price = gf.get("price", 0)

        diff = g_price - p_total
        diff_pct = (diff / g_price * 100) if g_price > 0 else 0

        indicator = "CHEAPER" if diff > 5 else ("SAME" if abs(diff) <= 5 else "MORE EXPENSIVE")

        print(f"  {i:<3} {airline:20s} {dep_str:>6}  ${p_total:>8.2f}  ${p_base:>8.2f}  ${p_tax:>8.2f}  ${p_fee:>6.2f}  {fare_type:>5}  ${g_price:>8.2f}  ${diff:>+8.2f} ({diff_pct:>+5.1f}%) {indicator}")

        results.append({
            "airline": airline.strip(),
            "departure": dep_str,
            "picasso_total": p_total,
            "picasso_base_fare": p_base,
            "picasso_tax": p_tax,
            "picasso_ticket_fee": p_fee,
            "fare_type": fare_type,
            "google_price": g_price,
            "difference": round(diff, 2),
            "diff_pct": round(diff_pct, 1),
            "picasso_cheaper": diff > 5,
        })

    print(f"  {'-'*115}")

    if results:
        cheaper = sum(1 for r in results if r["picasso_cheaper"])
        same = sum(1 for r in results if abs(r["difference"]) <= 5)
        more_exp = sum(1 for r in results if r["difference"] < -5)
        avg_diff = sum(r["difference"] for r in results) / len(results)

        print(f"\n  SUMMARY: {cheaper} cheaper, {same} same (±$5), {more_exp} more expensive")
        print(f"  AVG DIFFERENCE: ${avg_diff:+.2f} (positive = Picasso cheaper)")

        # Check if base_fare vs total tells us something
        for r in results:
            base_vs_google = r["google_price"] - r["picasso_base_fare"]
            tax_component = r["picasso_tax"] + r["picasso_ticket_fee"]
            if abs(base_vs_google) <= 10:
                print(f"  ** {r['airline']}: Google ${r['google_price']:.0f} ≈ Picasso base ${r['picasso_base_fare']:.0f} (tax gap = ${tax_component:.0f})")

    return results


def main():
    print("\n" + "=" * 110)
    print("  LIVE PRICE COMPARISON: Picasso Sandbox vs Google Flights (SerpAPI)")
    print("  NO estimates, NO markup, NO 1.55x. Raw prices only.")
    print("=" * 110)

    all_results = []
    for origin, dest, date in ALL_ROUTES:
        results = run_comparison(origin, dest, date)
        if results:
            all_results.extend(results)
        time.sleep(1)  # Be polite to APIs

    if all_results:
        print(f"\n{'='*110}")
        print(f"  GRAND SUMMARY: {len(all_results)} matched flights")
        print(f"{'='*110}")
        cheaper = sum(1 for r in all_results if r["picasso_cheaper"])
        same = sum(1 for r in all_results if abs(r["difference"]) <= 5)
        more_exp = sum(1 for r in all_results if r["difference"] < -5)
        avg_diff = sum(r["difference"] for r in all_results) / len(all_results)
        net_count = sum(1 for r in all_results if r["fare_type"] == "NET")
        pub_count = sum(1 for r in all_results if r["fare_type"] == "PUB")

        print(f"  Picasso cheaper:      {cheaper}/{len(all_results)}")
        print(f"  About the same (±$5): {same}/{len(all_results)}")
        print(f"  Picasso more expensive:{more_exp}/{len(all_results)}")
        print(f"  Average difference:    ${avg_diff:+.2f}")
        print(f"  Fare types:            {pub_count} PUB, {net_count} NET")

        if cheaper > 0:
            cheaper_results = [r for r in all_results if r["picasso_cheaper"]]
            avg_savings = sum(r["difference"] for r in cheaper_results) / len(cheaper_results)
            print(f"\n  CHEAPER FLIGHTS avg savings: ${avg_savings:.2f}")
            for r in cheaper_results:
                print(f"    {r['airline']:20s} Picasso ${r['picasso_total']:.0f} vs Google ${r['google_price']:.0f} = ${r['difference']:+.0f} [{r['fare_type']}]")

        # KEY DIAGNOSTIC: Check if Picasso base_fare ≈ Google price (tax gap theory)
        base_matches = 0
        for r in all_results:
            if abs(r["google_price"] - r["picasso_base_fare"]) <= 15:
                base_matches += 1

        if base_matches > 0:
            print(f"\n  *** TAX GAP DIAGNOSTIC ***")
            print(f"  {base_matches}/{len(all_results)} flights where Google price ≈ Picasso BASE FARE (not total)")
            print(f"  This would mean Picasso 'total' INCLUDES something Google doesn't, or vice versa")

        total_matches = 0
        for r in all_results:
            if abs(r["google_price"] - r["picasso_total"]) <= 10:
                total_matches += 1
        print(f"  {total_matches}/{len(all_results)} flights where Google price ≈ Picasso TOTAL (±$10)")

    # Save raw results
    output_file = f"price_comparison_live_{time.strftime('%Y%m%d_%H%M%S')}.json"
    with open(output_file, "w") as f:
        json.dump({"timestamp": time.time(), "results": all_results}, f, indent=2)
    print(f"\n  Results saved to: {output_file}")


if __name__ == "__main__":
    main()
