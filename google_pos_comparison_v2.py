#!/usr/bin/env python3
"""Google Flights POS Comparison v2 — Handle cookie consent, navigate to real search.

US: SerpAPI
DK/DE/IN: Bright Data residential IP → Google Flights with proper cookie acceptance
"""

import asyncio
import json
import os
import re
import time
import requests
from datetime import datetime
from pathlib import Path

SERPAPI_KEY = os.environ.get("SERPAPI_KEY", "")

BD_BASE = "wss://brd-customer-hl_890ca773-zone-scraping_browser1"
BD_AUTH = "xy22gst47vzm"
BD_HOST = "brd.superproxy.io:9222"

CDP_URLS = {
    "DK": f"{BD_BASE}-country-dk:{BD_AUTH}@{BD_HOST}",
    "DE": f"{BD_BASE}-country-de:{BD_AUTH}@{BD_HOST}",
    "IN": f"{BD_BASE}-country-in:{BD_AUTH}@{BD_HOST}",
}

ROUTES = [
    ("JFK", "MUC", "2026-05-21", "2026-05-28", "New York → Munich"),
    ("LAX", "NRT", "2026-06-10", "2026-06-17", "Los Angeles → Tokyo"),
    ("ORD", "LHR", "2026-06-15", "2026-06-22", "Chicago → London"),
]

TO_USD = {
    "USD": 1.0, "EUR": 1.08, "DKK": 0.145, "GBP": 1.27,
    "INR": 0.012, "CHF": 1.13, "JPY": 0.0067,
}


def serpapi_search(origin, dest, dep, ret):
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
                "price": price,
                "currency": "USD",
                "price_usd": price,
                "airlines": " / ".join(dict.fromkeys(airlines)),
                "flight_numbers": "+".join(fns),
                "stops": len(legs) - 1,
                "dep_time": legs[0].get("departure_airport", {}).get("time", ""),
            })
    return {"flights": flights}


async def accept_google_cookies(page):
    """Accept Google's cookie consent in EU countries."""
    # Wait for consent dialog
    await page.wait_for_timeout(3000)

    # Try various Accept All button selectors
    selectors = [
        "button#L2AGLb",                         # "Accept all" (English)
        "button:has-text('Accept all')",
        "button:has-text('Acceptér alle')",       # Danish
        "button:has-text('Alle akzeptieren')",    # German
        "button:has-text('Accept All')",
        "button:has-text('Godkend alle')",        # Danish alt
        "button:has-text('Accetta tutto')",       # Italian
        "button:has-text('Tout accepter')",       # French
        "button:has-text('स्वीकार करें')",          # Hindi
        "form:has(button) button:last-of-type",   # Last button in consent form
    ]

    for sel in selectors:
        try:
            btn = page.locator(sel).first
            if await btn.count() > 0 and await btn.is_visible():
                await btn.click(timeout=5000)
                print("cookies OK", end=" ", flush=True)
                await page.wait_for_timeout(2000)
                return True
        except Exception:
            continue

    # Fallback: try to find and click any button that looks like "accept"
    try:
        buttons = await page.evaluate("""() => {
            const btns = Array.from(document.querySelectorAll('button'));
            return btns.map(b => ({text: b.innerText, id: b.id, cls: b.className}))
                .filter(b => b.text.length > 0);
        }""")
        print(f"buttons: {[b['text'][:30] for b in buttons[:5]]}", end=" ", flush=True)

        # Click the accept/agree button
        for b in buttons:
            text = b["text"].lower()
            if any(w in text for w in ["accept", "agree", "godkend", "akzeptier", "accett"]):
                await page.click(f"button:has-text('{b['text'][:20]}')")
                print("clicked", end=" ", flush=True)
                await page.wait_for_timeout(2000)
                return True
    except Exception as e:
        print(f"cookie-err: {e}", end=" ", flush=True)

    return False


async def scrape_google_flights(cdp_url, country, origin, dest, dep_date, ret_date):
    """Scrape Google Flights through country-specific residential IP."""
    from playwright.async_api import async_playwright

    pw = await async_playwright().start()
    print(f"    [{country}] Connecting...", end=" ", flush=True)

    try:
        browser = await pw.chromium.connect_over_cdp(cdp_url)
    except Exception as e:
        print(f"FAIL: {e}")
        await pw.stop()
        return {"error": str(e)[:100]}

    page = await browser.new_page()

    # Verify IP
    try:
        await page.goto("https://ipinfo.io/json", timeout=20000)
        ip_data = json.loads(await page.evaluate("() => document.body.innerText"))
        print(f"IP={ip_data.get('ip','?')} ({ip_data.get('country','?')})", end=" ", flush=True)
    except:
        ip_data = {}

    # Step 1: Go to google.com first to handle cookies
    print(f"\n    [{country}] Cookie consent...", end=" ", flush=True)
    try:
        await page.goto("https://www.google.com/", timeout=30000, wait_until="domcontentloaded")
        await accept_google_cookies(page)
    except Exception as e:
        print(f"nav fail: {e}", end=" ", flush=True)

    # Step 2: Navigate to Google Flights search
    # Use the direct search URL with query parameters
    search_url = (
        f"https://www.google.com/travel/flights/search"
        f"?q=flights+from+{origin}+to+{dest}"
        f"+on+{dep_date}+return+{ret_date}"
        f"&curr=USD&hl=en"
    )

    print(f"\n    [{country}] Searching {origin}→{dest}...", end=" ", flush=True)
    try:
        await page.goto(search_url, timeout=60000, wait_until="domcontentloaded")
    except Exception as e:
        # Try with commit wait
        try:
            await page.goto(search_url, timeout=60000, wait_until="commit")
        except Exception as e2:
            print(f"search nav fail: {e2}")
            await browser.close()
            await pw.stop()
            return {"error": str(e2)[:100], "ip_info": ip_data}

    # May need to accept cookies again on flights subdomain
    await page.wait_for_timeout(3000)
    await accept_google_cookies(page)

    # Wait for flight results to load
    print("waiting for results...", end=" ", flush=True)
    await page.wait_for_timeout(12000)

    # Check current URL - did we get redirected?
    current_url = page.url
    print(f"\n    [{country}] URL: {current_url[:80]}")

    # If we're still on consent or wrong page, try direct URL format
    if "consent" in current_url.lower() or "travel/flights/search" not in current_url:
        # Try another URL format
        alt_url = f"https://www.google.com/travel/flights?q=Flights+from+{origin}+to+{dest}+departing+{dep_date}+returning+{ret_date}&curr=USD&hl=en"
        try:
            await page.goto(alt_url, timeout=60000, wait_until="domcontentloaded")
            await page.wait_for_timeout(8000)
            current_url = page.url
            print(f"    [{country}] Alt URL: {current_url[:80]}")
        except:
            pass

    # Extract flight data
    flights_data = await page.evaluate("""() => {
        const result = {url: window.location.href, title: document.title};
        const body = document.body?.innerText || '';
        result.page_length = body.length;

        // Detect currency used on page
        const currMatch = body.match(/[\$€£₹]|DKK|USD|EUR|INR|kr\\.?/) || [];
        result.detected_currency = currMatch[0] || 'unknown';

        // Extract ALL aria-label attributes that contain flight info
        const flights = [];
        document.querySelectorAll('[aria-label]').forEach(el => {
            const label = el.getAttribute('aria-label') || '';
            // Flight result labels typically contain: airline, time, duration, stops, price
            if (label.length > 50 && (
                /\\d+\\s*(hr|min|stop|nonstop)/.test(label) ||
                (label.includes(':') && /\\$|€|₹|kr|DKK|USD/.test(label))
            )) {
                flights.push(label);
            }
        });
        result.flight_labels = flights.slice(0, 40);

        // Also get raw price values from specific elements
        const priceEls = [];
        document.querySelectorAll('span, div').forEach(el => {
            const text = el.innerText?.trim() || '';
            if (/^[\\$€₹]\\s*[\\d,\\.]+$/.test(text) || /^(DKK|kr\\.?)\\s*[\\d,\\.]+$/.test(text) ||
                /^[\\d,\\.]+\\s*(DKK|kr\\.?|USD|EUR)$/.test(text)) {
                if (text.length < 30) {
                    priceEls.push(text);
                }
            }
        });
        result.price_elements = [...new Set(priceEls)].slice(0, 30);

        // Get text sections that look like flight listings
        const lines = body.split('\\n').filter(l => l.trim());
        const flightSections = [];
        for (let i = 0; i < lines.length; i++) {
            const line = lines[i].trim();
            // Look for airline names followed by times and prices
            if (/\\d{1,2}:\\d{2}/.test(line) && i + 5 < lines.length) {
                const section = lines.slice(i, i + 6).map(l => l.trim());
                if (section.some(s => /[\\$€₹]|kr|DKK/.test(s))) {
                    flightSections.push(section.join(' | '));
                    i += 5;
                }
            }
        }
        result.flight_sections = flightSections.slice(0, 25);

        return result;
    }""")

    # Screenshot
    try:
        ss_path = f"/tmp/gf_v2_{country}_{origin}_{dest}.png"
        await page.screenshot(path=ss_path, full_page=False)
        flights_data["screenshot"] = ss_path
    except:
        pass

    await browser.close()
    await pw.stop()

    # Parse extracted flights
    parsed = parse_google_flights_labels(flights_data.get("flight_labels", []),
                                         flights_data.get("price_elements", []),
                                         flights_data.get("detected_currency", "USD"))
    flights_data["parsed_flights"] = parsed

    return {"data": flights_data, "ip_info": ip_data}


def parse_google_flights_labels(labels, price_elements, currency):
    """Parse aria-label flight entries into structured data."""
    flights = []
    for label in labels:
        flight = {"raw": label[:200]}

        # Extract price: $1,234 or kr. 8.234 or €1,234 or ₹82,345
        price_match = re.search(r'[\$€₹]\s*([\d,]+)', label)
        if not price_match:
            price_match = re.search(r'([\d,.]+)\s*(?:kr\.?|DKK|USD|EUR)', label)
        if not price_match:
            price_match = re.search(r'(?:kr\.?|DKK)\s*([\d,.]+)', label)

        if price_match:
            price_str = price_match.group(1).replace(",", "")
            try:
                flight["price"] = int(float(price_str))
            except:
                continue
        else:
            continue

        # Detect currency from label
        if "$" in label:
            flight["currency"] = "USD"
        elif "€" in label:
            flight["currency"] = "EUR"
        elif "₹" in label:
            flight["currency"] = "INR"
        elif "kr" in label.lower() or "DKK" in label:
            flight["currency"] = "DKK"
        else:
            flight["currency"] = currency

        # Convert to USD
        rate = TO_USD.get(flight["currency"], 1.0)
        flight["price_usd"] = round(flight["price"] * rate, 2)

        # Extract airline
        airline_match = re.search(r'(?:Operated by |with )?([A-Z][a-z]+(?: [A-Z][a-z]+)*(?:\s+Airlines?)?)', label)
        if airline_match:
            flight["airline"] = airline_match.group(1)

        # Extract stops
        if "nonstop" in label.lower() or "Nonstop" in label:
            flight["stops"] = 0
        else:
            stops_match = re.search(r'(\d+)\s*stop', label.lower())
            if stops_match:
                flight["stops"] = int(stops_match.group(1))

        flights.append(flight)

    return flights


async def main():
    # ═══ US via SerpAPI ═══
    print("=" * 70)
    print("  US POS — SerpAPI")
    print("=" * 70)

    us_results = {}
    for origin, dest, dep, ret, name in ROUTES:
        rk = f"{origin}-{dest}"
        print(f"  [US] {name}...", end=" ", flush=True)
        result = serpapi_search(origin, dest, dep, ret)
        if "error" in result:
            print(f"ERROR: {result['error']}")
        else:
            flights = result["flights"]
            if flights:
                cheapest = min(flights, key=lambda f: f["price_usd"])
                print(f"{len(flights)} flights | Cheapest: ${cheapest['price']:,} — {cheapest['airlines']}")
            else:
                print("No flights")
        us_results[rk] = result
        time.sleep(2)

    # ═══ Foreign POS via Bright Data ═══
    foreign_results = {}

    for country, cdp_url in CDP_URLS.items():
        print(f"\n{'='*70}")
        print(f"  {country} POS — Bright Data Residential IP")
        print(f"{'='*70}")

        country_results = {}
        for origin, dest, dep, ret, name in ROUTES:
            rk = f"{origin}-{dest}"
            result = await scrape_google_flights(cdp_url, country, origin, dest, dep, ret)
            country_results[rk] = result
            print()

        foreign_results[country] = country_results

    # ═══ COMPARISON ═══
    print(f"\n\n{'='*90}")
    print("  GOOGLE FLIGHTS POS COMPARISON — RESIDENTIAL IP VERIFIED")
    print(f"{'='*90}")

    for origin, dest, dep, ret, name in ROUTES:
        rk = f"{origin}-{dest}"
        print(f"\n{'─'*90}")
        print(f"  {name} ({dep} → {ret})")
        print(f"{'─'*90}")

        # US flights
        us_flights = us_results.get(rk, {}).get("flights", [])
        us_cheapest = min(us_flights, key=lambda f: f["price_usd"]) if us_flights else None

        print(f"\n  US (SerpAPI): {len(us_flights)} flights")
        for f in sorted(us_flights, key=lambda x: x["price_usd"])[:8]:
            print(f"    ${f['price']:>6,} | {f['airlines']:<30} | {f['stops']} stop{'s' if f['stops']!=1 else ''} | {f['dep_time']}")

        # Foreign
        for country in CDP_URLS:
            c_data = foreign_results.get(country, {}).get(rk, {})
            ip_info = c_data.get("ip_info", {})
            data = c_data.get("data", {})
            parsed = data.get("parsed_flights", [])
            labels = data.get("flight_labels", [])
            prices = data.get("price_elements", [])
            currency = data.get("detected_currency", "?")

            print(f"\n  {country} (IP: {ip_info.get('country','?')}/{ip_info.get('city','?')}) "
                  f"| Currency on page: {currency}")

            if parsed:
                for f in sorted(parsed, key=lambda x: x.get("price_usd", 99999))[:8]:
                    stops_str = f"{f.get('stops','?')} stop" if 'stops' in f else "? stops"
                    airline = f.get("airline", "Unknown")[:30]
                    p = f["price"]
                    cur = f["currency"]
                    usd = f["price_usd"]

                    vs_us = ""
                    if us_cheapest:
                        diff = us_cheapest["price_usd"] - usd
                        pct = (diff / us_cheapest["price_usd"] * 100) if us_cheapest["price_usd"] else 0
                        if abs(diff) > 1:
                            vs_us = f"  {'↓' if diff>0 else '↑'}${abs(diff):,.0f} ({abs(pct):.0f}%)"

                    print(f"    {cur} {p:>8,} (~${usd:>8,.0f}) | {airline:<30} | {stops_str}{vs_us}")
            elif labels:
                print(f"    {len(labels)} flight labels found:")
                for l in labels[:5]:
                    print(f"      {l[:120]}")
            elif prices:
                print(f"    Prices found: {', '.join(prices[:10])}")
            else:
                print(f"    No flight data extracted")
                if data.get("screenshot"):
                    print(f"    Screenshot: {data['screenshot']}")

    # Save
    output = {
        "date": datetime.now().isoformat(),
        "us_results": us_results,
        "foreign_results": foreign_results,
    }
    out_path = f"pos_google_comparison_v2_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\n  Saved to {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
