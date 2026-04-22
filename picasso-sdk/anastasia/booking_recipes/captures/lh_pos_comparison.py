#!/usr/bin/env python3
"""Lufthansa POS Arbitrage Comparison — Denmark vs US vs DE vs IN.

Extracts cheapest prices directly in JS to avoid response truncation.
"""

import asyncio
import json
from pathlib import Path
from datetime import datetime

CDP_URL = "wss://brd-customer-hl_890ca773-zone-scraping_browser1:xy22gst47vzm@brd.superproxy.io:9222"
CAPTURE_DIR = Path(__file__).parent
BOUNDS_URL = "https://api-shop.lufthansa.com/v1/one-booking/search/air-bounds"

ROUTES = [
    ("JFK", "MUC", "2026-05-21", "2026-05-28"),
    ("LAX", "FRA", "2026-06-10", "2026-06-17"),
    ("ORD", "ZRH", "2026-06-15", "2026-06-22"),
]

POS_CONFIGS = [
    {"name": "US", "path": "/lh/us/en/homepage"},
    {"name": "DK", "path": "/lh/dk/en/homepage"},
    {"name": "DE", "path": "/lh/de/en/homepage"},
    {"name": "IN", "path": "/lh/in/en/homepage"},
]

CABINS = [
    ("ECONOMY", "DEMALLFPP"),
    ("BUSINESS", "DECALLFPP"),
]

TO_USD = {
    "USD": 1.0, "EUR": 1.08, "DKK": 0.145, "GBP": 1.27,
    "INR": 0.012, "CHF": 1.13, "SEK": 0.096, "NOK": 0.093,
}


def cents_to_usd(cents, currency):
    rate = TO_USD.get(currency, 1.0)
    return round(cents / 100 * rate, 2)


async def get_token(page, pos_config):
    """Navigate to POS-specific page and extract token."""
    url = f"https://shop.lufthansa.com{pos_config['path']}"
    print(f"\n  [{pos_config['name']}] Navigating to {url}...")

    try:
        await page.goto(url, timeout=90000, wait_until="domcontentloaded")
    except Exception as e:
        print(f"  [{pos_config['name']}] Navigation timeout, trying networkidle...")
        try:
            await page.goto(url, timeout=90000, wait_until="commit")
        except Exception as e2:
            print(f"  [{pos_config['name']}] Failed: {e2}")
            return None, None

    await page.wait_for_timeout(3000)
    try:
        btn = page.locator("#cm-acceptAll")
        if await btn.count() > 0:
            await btn.click(timeout=5000)
            await page.wait_for_timeout(2000)
    except Exception:
        pass
    await page.wait_for_timeout(6000)

    result = await page.evaluate("""async () => {
        let token = null;
        try {
            const d = JSON.parse(sessionStorage.getItem('gateway-auth-tokens'));
            for (const v of Object.values(d)) if (v.token) { token = v.token; break; }
        } catch(e) {}
        if (!token) {
            const r = await fetch('https://api-shop.lufthansa.com/v1/oauth2/token', {
                method: 'POST',
                headers: {'Content-Type': 'application/x-www-form-urlencoded'},
                body: 'client_id=k7zpj4s6k2qbrr4xhrzqa7yn&client_secret=rVXq%2305&fact=%7B%7D&grant_type=client_credentials'
            });
            token = (await r.json()).access_token;
        }
        return { token, amaRef: sessionStorage.getItem('Ama-Client-Ref') };
    }""")

    print(f"  [{pos_config['name']}] Token: {'OK' if result.get('token') else 'FAIL'}, URL: {page.url}")
    return result.get("token"), result.get("amaRef")


async def search_and_extract(page, token, ama_ref, origin, dest, dep, ret, cff):
    """Search air-bounds and extract cheapest price directly in JS (no truncation)."""
    result = await page.evaluate("""async (args) => {
        const {token, amaRef, url, origin, dest, dep, ret, cff} = args;
        const body = {
            itineraries: [
                {originLocationCode: origin, destinationLocationCode: dest,
                 departureDateTime: dep, isRequestedBound: true},
                {originLocationCode: dest, destinationLocationCode: origin,
                 departureDateTime: ret, isRequestedBound: false}
            ],
            travelers: [{passengerTypeCode: "ADT"}],
            commercialFareFamilies: [cff]
        };
        try {
            const resp = await fetch(url, {
                method: 'POST',
                headers: {
                    'Authorization': 'Bearer ' + token,
                    'Content-Type': 'application/json',
                    'Accept': 'application/json',
                    'Ama-Client-Ref': amaRef || '',
                },
                body: JSON.stringify(body),
            });
            const data = await resp.json();

            if (data.errors && !data.data) {
                return {error: data.errors[0]?.title || 'Unknown error', status: resp.status};
            }

            const groups = data.data?.airBoundGroups || [];
            let cheapest = null;
            let totalBounds = 0;

            for (const group of groups) {
                for (const bound of (group.airBounds || [])) {
                    totalBounds++;
                    const tp = bound.prices?.totalPrices?.[0];
                    if (!tp) continue;

                    if (!cheapest || tp.total < cheapest.total_cents) {
                        const segs = group.boundDetails?.segments || [];
                        const avail = bound.availabilityDetails?.[0] || {};
                        cheapest = {
                            total_cents: tp.total,
                            base_cents: tp.base,
                            taxes_cents: tp.totalTaxes,
                            currency: tp.currencyCode,
                            fare_family: bound.fareFamilyCode,
                            cabin: avail.cabin,
                            booking_class: avail.bookingClass,
                            quota: avail.quota,
                            flight_id: segs[0]?.flightId || '',
                            is_cheapest_flag: bound.isCheapestOffer || false,
                            num_groups: groups.length,
                            num_bounds: totalBounds,
                        };
                    }
                }
            }
            return cheapest || {error: 'No prices found', status: resp.status};
        } catch(e) {
            return {error: e.message};
        }
    }""", {
        "token": token, "amaRef": ama_ref, "url": BOUNDS_URL,
        "origin": origin, "dest": dest, "dep": dep, "ret": ret, "cff": cff,
    })
    return result


async def main():
    from playwright.async_api import async_playwright

    pw = await async_playwright().start()
    print("[POS Compare] Connecting to Bright Data...")
    browser = await pw.chromium.connect_over_cdp(CDP_URL)

    all_results = {}

    for pos in POS_CONFIGS:
        print(f"\n{'='*60}")
        print(f"  POS: {pos['name']} ({pos['path']})")
        print(f"{'='*60}")

        # Fresh page for each POS to get clean session
        page = await browser.new_page()
        token, ama_ref = await get_token(page, pos)

        if not token:
            print(f"  [{pos['name']}] SKIP — no token")
            await page.close()
            continue

        pos_results = {}

        for origin, dest, dep, ret in ROUTES:
            route_key = f"{origin}-{dest}"
            pos_results[route_key] = {}

            for cabin_name, cff in CABINS:
                print(f"  [{pos['name']}] {route_key} {cabin_name}...", end=" ")
                result = await search_and_extract(page, token, ama_ref, origin, dest, dep, ret, cff)

                if "error" in result:
                    print(f"ERR: {result['error']}")
                    pos_results[route_key][cabin_name] = result
                else:
                    usd = cents_to_usd(result["total_cents"], result["currency"])
                    result["total_usd"] = usd
                    result["base_usd"] = cents_to_usd(result["base_cents"], result["currency"])
                    result["taxes_usd"] = cents_to_usd(result["taxes_cents"], result["currency"])
                    pos_results[route_key][cabin_name] = result
                    print(f"{result['currency']} {result['total_cents']/100:,.2f} (~${usd:,.2f}) | "
                          f"{result['flight_id']} | {result['num_groups']} groups")

                await page.wait_for_timeout(600)

        all_results[pos["name"]] = pos_results
        await page.close()

    # === COMPARISON TABLE ===
    print(f"\n\n{'='*80}")
    print("  LUFTHANSA POS ARBITRAGE COMPARISON")
    print(f"  All prices = cheapest one-way outbound fare, converted to USD")
    print(f"  FX rates: EUR=1.08, DKK=0.145, INR=0.012")
    print(f"{'='*80}")

    for origin, dest, dep, ret in ROUTES:
        route_key = f"{origin}-{dest}"
        print(f"\n  Route: {route_key} (out {dep}, return {ret})")

        for cabin_name, _ in CABINS:
            print(f"\n    {cabin_name}:")
            print(f"    {'POS':<6} {'Native Price':>16} {'Currency':>8} {'USD Equiv':>12} {'vs US':>12}")
            print(f"    {'-'*60}")

            us_usd = None
            pos_prices = []

            for pos in POS_CONFIGS:
                pos_name = pos["name"]
                if pos_name not in all_results:
                    continue

                data = all_results[pos_name].get(route_key, {}).get(cabin_name, {})
                if "error" in data:
                    print(f"    {pos_name:<6} {'ERROR':>16} {'':>8} {'':>12} {'':>12}")
                    continue

                native = data["total_cents"] / 100
                currency = data["currency"]
                usd = data["total_usd"]

                if pos_name == "US":
                    us_usd = usd

                pos_prices.append((pos_name, native, currency, usd))

            for pos_name, native, currency, usd in pos_prices:
                vs_us = ""
                if us_usd and pos_name != "US":
                    diff = us_usd - usd
                    pct = (diff / us_usd) * 100 if us_usd else 0
                    if diff > 0:
                        vs_us = f"-${diff:,.0f} ({pct:.1f}%)"
                    else:
                        vs_us = f"+${abs(diff):,.0f} ({abs(pct):.1f}%)"

                print(f"    {pos_name:<6} {native:>13,.2f} {currency:>8} ${usd:>10,.2f} {vs_us:>12}")

    # Save
    output = {
        "comparison_date": datetime.now().isoformat(),
        "routes": [{"origin": o, "dest": d, "dep": dp, "ret": r} for o, d, dp, r in ROUTES],
        "pos_configs": [p["name"] for p in POS_CONFIGS],
        "fx_rates_to_usd": TO_USD,
        "results": all_results,
    }
    out_path = CAPTURE_DIR / f"pos_comparison_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    out_path.write_text(json.dumps(output, indent=2, default=str))
    print(f"\n[POS Compare] Saved to {out_path}")

    await browser.close()
    await pw.stop()
    print("[POS Compare] Done.")


if __name__ == "__main__":
    asyncio.run(main())
