#!/usr/bin/env python3
"""Duffel NDC vs Google Flights — Same routes, side by side.

This is the test that matters. If Duffel prices are cheaper than Google,
there's a real business. If they're the same, there isn't.
"""

import json
import os
import time
import requests
from datetime import datetime

SERPAPI_KEY = os.environ.get("SERPAPI_KEY", "")
DUFFEL_TOKEN = os.environ.get("DUFFEL_LIVE_TOKEN", "")

ROUTES = [
    ("JFK", "MUC", "2026-05-21", "2026-05-28", "New York → Munich"),
    ("LAX", "NRT", "2026-06-10", "2026-06-17", "Los Angeles → Tokyo"),
    ("ORD", "LHR", "2026-06-15", "2026-06-22", "Chicago → London"),
    ("SFO", "CDG", "2026-07-01", "2026-07-08", "San Francisco → Paris"),
    ("JFK", "DEL", "2026-06-20", "2026-06-27", "New York → Delhi"),
]


def search_google(origin, dest, dep, ret):
    """SerpAPI Google Flights search."""
    params = {
        "engine": "google_flights",
        "departure_id": origin,
        "arrival_id": dest,
        "outbound_date": dep,
        "return_date": ret,
        "type": "1",
        "currency": "USD",
        "gl": "us",
        "hl": "en",
        "adults": "1",
        "api_key": SERPAPI_KEY,
    }
    resp = requests.get("https://serpapi.com/search", params=params, timeout=60)
    data = resp.json()
    if "error" in data:
        return {"error": data["error"]}

    flights = []
    for cat in ["best_flights", "other_flights"]:
        for f in data.get(cat, []):
            price = f.get("price")
            if not price:
                continue
            legs = f.get("flights", [])
            if not legs:
                continue
            airlines = []
            fns = []
            for leg in legs:
                airlines.append(leg.get("airline", ""))
                fns.append(leg.get("flight_number", ""))

            flights.append({
                "price": float(price),
                "currency": "USD",
                "airlines": " / ".join(dict.fromkeys(airlines)),
                "flight_numbers": "+".join(fns),
                "stops": len(legs) - 1,
                "dep_time": legs[0].get("departure_airport", {}).get("time", ""),
                "duration": f.get("total_duration", 0),
                "source": "google",
            })
    return {"flights": sorted(flights, key=lambda f: f["price"])}


def search_duffel(origin, dest, dep, ret):
    """Duffel NDC search."""
    headers = {
        "Authorization": f"Bearer {DUFFEL_TOKEN}",
        "Duffel-Version": "v2",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    body = {
        "data": {
            "slices": [
                {"origin": origin, "destination": dest, "departure_date": dep},
                {"origin": dest, "destination": origin, "departure_date": ret},
            ],
            "passengers": [{"type": "adult"}],
            "cabin_class": "economy",
        }
    }

    try:
        resp = requests.post(
            "https://api.duffel.com/air/offer_requests",
            headers=headers,
            json=body,
            params={"return_offers": "true", "supplier_timeout": "30000"},
            timeout=90,
        )

        if resp.status_code >= 400:
            error = resp.json().get("errors", [{}])[0].get("message", resp.text[:200])
            return {"error": f"HTTP {resp.status_code}: {error}"}

        data = resp.json().get("data", {})
        offers = data.get("offers", [])

        flights = []
        for offer in offers:
            slices = offer.get("slices", [])
            if not slices:
                continue

            total = float(offer.get("total_amount", 0))
            currency = offer.get("total_currency", "USD")

            # Get airline info from first slice
            outbound = slices[0]
            segments = outbound.get("segments", [])
            if not segments:
                continue

            airlines = []
            fns = []
            for seg in segments:
                carrier = seg.get("marketing_carrier", {})
                airlines.append(carrier.get("name", ""))
                fns.append(f"{carrier.get('iata_code', '')}{seg.get('marketing_carrier_flight_number', '')}")

            # Duration
            dep_time = segments[0].get("departing_at", "")
            arr_time = segments[-1].get("arriving_at", "")

            flights.append({
                "price": total,
                "currency": currency,
                "airlines": " / ".join(dict.fromkeys(airlines)),
                "flight_numbers": "+".join(fns),
                "stops": len(segments) - 1,
                "dep_time": dep_time[11:16] if len(dep_time) > 16 else dep_time,
                "source": "duffel",
                "offer_id": offer.get("id", "")[:20],
            })

        return {"flights": sorted(flights, key=lambda f: f["price"]),
                "total_offers": len(offers)}

    except Exception as e:
        return {"error": str(e)}


def make_match_key(flight):
    """Match flights by flight numbers."""
    return flight["flight_numbers"]


def main():
    print("=" * 100)
    print("  DUFFEL NDC vs GOOGLE FLIGHTS — PRICE COMPARISON")
    print("  Same routes, same dates, same passenger. Which is cheaper?")
    print("=" * 100)

    all_results = {}

    for origin, dest, dep, ret, name in ROUTES:
        rk = f"{origin}-{dest}"
        print(f"\n{'─'*100}")
        print(f"  {name} ({dep} → {ret})")
        print(f"{'─'*100}")

        # Google
        print(f"  [Google] Searching...", end=" ", flush=True)
        g_result = search_google(origin, dest, dep, ret)
        if "error" in g_result:
            print(f"ERROR: {g_result['error']}")
            g_flights = []
        else:
            g_flights = g_result["flights"]
            cheapest = g_flights[0] if g_flights else None
            print(f"{len(g_flights)} flights | Cheapest: ${cheapest['price']:,.0f} — {cheapest['airlines']}" if cheapest else "No flights")
        time.sleep(2)

        # Duffel
        print(f"  [Duffel] Searching...", end=" ", flush=True)
        d_result = search_duffel(origin, dest, dep, ret)
        if "error" in d_result:
            print(f"ERROR: {d_result['error']}")
            d_flights = []
        else:
            d_flights = d_result["flights"]
            cheapest = d_flights[0] if d_flights else None
            total = d_result.get("total_offers", 0)
            print(f"{len(d_flights)} flights ({total} offers) | Cheapest: ${cheapest['price']:,.0f} — {cheapest['airlines']}" if cheapest else "No flights")

        all_results[rk] = {"google": g_flights, "duffel": d_flights}

        # ── Side by side comparison ──
        print(f"\n  {'Airline':<30} {'Google':>10} {'Duffel':>10} {'Diff':>10} {'%':>8} {'Winner':>8}")
        print(f"  {'─'*30} {'─'*10} {'─'*10} {'─'*10} {'─'*8} {'─'*8}")

        # Index Google flights by airline
        g_by_airline = {}
        for f in g_flights:
            key = f["airlines"]
            if key not in g_by_airline or f["price"] < g_by_airline[key]["price"]:
                g_by_airline[key] = f

        # Index Duffel flights by airline
        d_by_airline = {}
        for f in d_flights:
            key = f["airlines"]
            if key not in d_by_airline or f["price"] < d_by_airline[key]["price"]:
                d_by_airline[key] = f

        # Merge airline names
        all_airlines = list(dict.fromkeys(list(g_by_airline.keys()) + list(d_by_airline.keys())))

        duffel_wins = 0
        google_wins = 0
        matched = 0

        for airline in all_airlines[:20]:
            g = g_by_airline.get(airline)
            d = d_by_airline.get(airline)

            g_str = f"${g['price']:>8,.0f}" if g else f"{'—':>9}"
            d_str = f"${d['price']:>8,.0f}" if d else f"{'—':>9}"

            if g and d:
                diff = g["price"] - d["price"]
                pct = (diff / g["price"] * 100) if g["price"] else 0
                diff_str = f"${abs(diff):>8,.0f}"
                pct_str = f"{abs(pct):>6.1f}%"
                if diff > 5:
                    winner = "DUFFEL"
                    duffel_wins += 1
                elif diff < -5:
                    winner = "GOOGLE"
                    google_wins += 1
                else:
                    winner = "TIE"
                matched += 1
            else:
                diff_str = f"{'—':>9}"
                pct_str = f"{'—':>7}"
                winner = "—"

            print(f"  {airline:<30} {g_str:>10} {d_str:>10} {diff_str:>10} {pct_str:>8} {winner:>8}")

        # Route summary
        if matched > 0:
            print(f"\n  Route summary: {matched} airlines compared | "
                  f"Duffel cheaper: {duffel_wins} | Google cheaper: {google_wins} | Tie: {matched - duffel_wins - google_wins}")

        g_cheapest = g_flights[0]["price"] if g_flights else None
        d_cheapest = d_flights[0]["price"] if d_flights else None

        if g_cheapest and d_cheapest:
            diff = g_cheapest - d_cheapest
            print(f"  Overall cheapest: Google ${g_cheapest:,.0f} vs Duffel ${d_cheapest:,.0f} → ", end="")
            if diff > 5:
                print(f"DUFFEL WINS by ${diff:,.0f} ({diff/g_cheapest*100:.1f}%)")
            elif diff < -5:
                print(f"GOOGLE WINS by ${abs(diff):,.0f} ({abs(diff)/g_cheapest*100:.1f}%)")
            else:
                print(f"TIE (${abs(diff):,.0f} diff)")

        time.sleep(3)

    # ═══ GRAND SUMMARY ═══
    print(f"\n\n{'='*100}")
    print("  GRAND SUMMARY")
    print(f"{'='*100}")

    total_duffel_wins = 0
    total_google_wins = 0
    total_ties = 0
    total_duffel_only = 0
    savings = []

    for rk, data in all_results.items():
        g_by = {}
        for f in data["google"]:
            key = f["airlines"]
            if key not in g_by or f["price"] < g_by[key]["price"]:
                g_by[key] = f

        d_by = {}
        for f in data["duffel"]:
            key = f["airlines"]
            if key not in d_by or f["price"] < d_by[key]["price"]:
                d_by[key] = f

        for airline in set(list(g_by.keys()) + list(d_by.keys())):
            g = g_by.get(airline)
            d = d_by.get(airline)

            if g and d:
                diff = g["price"] - d["price"]
                if diff > 5:
                    total_duffel_wins += 1
                    savings.append({"route": rk, "airline": airline, "google": g["price"],
                                   "duffel": d["price"], "saving": diff,
                                   "pct": diff/g["price"]*100})
                elif diff < -5:
                    total_google_wins += 1
                else:
                    total_ties += 1
            elif d and not g:
                total_duffel_only += 1

    total = total_duffel_wins + total_google_wins + total_ties
    print(f"\n  Airlines compared across all routes: {total}")
    print(f"  Duffel cheaper: {total_duffel_wins}")
    print(f"  Google cheaper: {total_google_wins}")
    print(f"  Same price (±$5): {total_ties}")
    print(f"  Duffel-only (not on Google): {total_duffel_only}")

    if total > 0:
        print(f"\n  Duffel win rate: {total_duffel_wins/total*100:.1f}%")
        print(f"  Google win rate: {total_google_wins/total*100:.1f}%")

    if savings:
        print(f"\n  DUFFEL SAVINGS:")
        savings.sort(key=lambda s: s["saving"], reverse=True)
        for s in savings[:20]:
            print(f"    {s['route']} {s['airline']:<30}: Google ${s['google']:,.0f} → Duffel ${s['duffel']:,.0f} = ${s['saving']:,.0f} ({s['pct']:.1f}%) savings")

        avg = sum(s["saving"] for s in savings) / len(savings)
        avg_pct = sum(s["pct"] for s in savings) / len(savings)
        print(f"\n  Average saving when Duffel wins: ${avg:,.0f} ({avg_pct:.1f}%)")

    # Save
    output = {
        "date": datetime.now().isoformat(),
        "routes": [{"origin": o, "dest": d, "dep": dp, "ret": r, "name": n}
                   for o, d, dp, r, n in ROUTES],
        "results": all_results,
        "summary": {
            "duffel_wins": total_duffel_wins,
            "google_wins": total_google_wins,
            "ties": total_ties,
            "duffel_only": total_duffel_only,
            "savings": savings,
        },
    }
    out_path = f"duffel_vs_google_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\n  Saved to {out_path}")


if __name__ == "__main__":
    main()
