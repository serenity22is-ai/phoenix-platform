#!/usr/bin/env python3
"""Google Flights POS Comparison — US (SerpAPI) vs DK (Bright Data residential IP).

US: SerpAPI google_flights engine
DK: Bright Data scraping browser with -country-dk residential IP → google.com/travel/flights
"""

import asyncio
import json
import os
import time
import requests
from datetime import datetime
from pathlib import Path

SERPAPI_KEY = os.environ.get("SERPAPI_KEY", "")

# Bright Data CDP URLs with country-targeted residential IPs
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
    "INR": 0.012, "CHF": 1.13, "JPY": 0.0067, "DKR": 0.145,
    "kr.": 0.145, "kr": 0.145,
}


def to_usd(price, currency):
    # Handle currency symbols
    c = currency.upper().strip().replace(",", "").replace(".", "")
    rate = TO_USD.get(currency, TO_USD.get(c, 1.0))
    return round(price * rate, 2)


# ═══════════════════════════════════════════════════════════
# PART 1: SerpAPI for US POS
# ═══════════════════════════════════════════════════════════

def serpapi_search(origin, dest, dep, ret):
    """US POS via SerpAPI."""
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
    for category in ["best_flights", "other_flights"]:
        for f in data.get(category, []):
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
                "duration": f.get("total_duration", 0),
                "dep_time": legs[0].get("departure_airport", {}).get("time", ""),
                "arr_time": legs[-1].get("arrival_airport", {}).get("time", ""),
                "category": category.replace("_flights", ""),
            })

    return {"flights": flights, "price_insights": data.get("price_insights", {})}


# ═══════════════════════════════════════════════════════════
# PART 2: Bright Data residential IP for foreign POS
# ═══════════════════════════════════════════════════════════

async def brightdata_google_flights(cdp_url, country, origin, dest, dep, ret):
    """Search Google Flights through country-specific residential IP."""
    from playwright.async_api import async_playwright

    pw = await async_playwright().start()
    print(f"    [{country}] Connecting via residential IP...", end=" ", flush=True)

    try:
        browser = await pw.chromium.connect_over_cdp(cdp_url)
    except Exception as e:
        print(f"CDP FAIL: {e}")
        await pw.stop()
        return {"error": f"CDP connection failed: {str(e)[:100]}"}

    page = await browser.new_page()

    # First verify our IP location
    try:
        await page.goto("https://ipinfo.io/json", timeout=30000)
        ip_info = await page.evaluate("() => document.body.innerText")
        ip_data = json.loads(ip_info)
        print(f"IP: {ip_data.get('ip', '?')} ({ip_data.get('country', '?')}, {ip_data.get('city', '?')})", end=" ", flush=True)
    except Exception as e:
        print(f"IP check failed: {e}", end=" ", flush=True)
        ip_data = {}

    # Build Google Flights URL
    # Format: google.com/travel/flights/search?tfs=...
    # Simpler: use the direct URL format
    gf_url = (
        f"https://www.google.com/travel/flights?q=Flights+to+{dest}+from+{origin}"
        f"+departing+{dep}+returning+{ret}&curr=USD"
    )

    print(f"\n    [{country}] Loading Google Flights...")
    try:
        await page.goto(gf_url, timeout=60000, wait_until="domcontentloaded")
        await page.wait_for_timeout(5000)
    except Exception as e:
        print(f"    [{country}] Nav failed: {e}")
        # Try alternative URL
        gf_url2 = f"https://www.google.com/travel/flights/search?tfs=CBwQAhoeEgoyMDI2LTA1LTIxagcIARIDSkZLcgcIARIDTVVDGh4SCjIwMjYtMDUtMjhqBwgBEgNNVUNyBwgBEgNKRktAAUgBcAGCAQsI____________AZgBAQ&curr=USD"
        try:
            await page.goto(gf_url2, timeout=60000, wait_until="domcontentloaded")
            await page.wait_for_timeout(5000)
        except:
            pass

    await page.wait_for_timeout(8000)

    # Extract flight data from the page
    flights_data = await page.evaluate("""() => {
        const results = [];
        const pageText = document.body?.innerText || '';
        const pageHtml = document.body?.innerHTML || '';

        // Try to find flight cards
        // Google Flights uses various selectors
        const selectors = [
            'li.pIav2d',           // flight result items
            '[data-ved] li',        // alternative
            '.nrc6c',              // another pattern
            'div[class*="flight"]', // generic
            'ul.Rk10dc li',        // results list
        ];

        let cards = [];
        for (const sel of selectors) {
            const found = document.querySelectorAll(sel);
            if (found.length > 0) {
                cards = Array.from(found);
                results.push({_selector: sel, _count: cards.length});
                break;
            }
        }

        // Try extracting prices from the page text
        // Look for price patterns like $XXX, kr. X.XXX, €XXX
        const pricePatterns = [
            /\$[\d,]+/g,
            /kr\.?\s*[\d.,]+/g,
            /€[\d.,]+/g,
            /₹[\d.,]+/g,
            /DKK\s*[\d.,]+/g,
            /USD\s*[\d.,]+/g,
            /EUR\s*[\d.,]+/g,
        ];

        const prices = [];
        for (const pat of pricePatterns) {
            const matches = pageText.match(pat) || [];
            prices.push(...matches.slice(0, 20));
        }

        // Try to get structured data from aria labels
        const ariaFlights = [];
        document.querySelectorAll('[aria-label]').forEach(el => {
            const label = el.getAttribute('aria-label');
            if (label && (label.includes('flight') || label.includes('price') ||
                label.includes('airline') || label.includes('depart') ||
                label.includes('$') || label.includes('kr'))) {
                ariaFlights.push(label.substring(0, 300));
            }
        });

        // Get the page title and URL for context
        return {
            url: window.location.href,
            title: document.title,
            prices: [...new Set(prices)].slice(0, 30),
            ariaFlights: ariaFlights.slice(0, 50),
            cards_found: cards.length,
            page_text_length: pageText.length,
            has_results: pageText.includes('price') || pageText.includes('$') ||
                        pageText.includes('kr') || pageText.includes('€'),
            first_500_text: pageText.substring(0, 500),
            // Look for specific price elements
            priceElements: Array.from(document.querySelectorAll('[data-price], [aria-label*="$"], [aria-label*="kr"], span')).slice(0, 100).map(el => ({
                tag: el.tagName,
                text: el.innerText?.substring(0, 100),
                ariaLabel: el.getAttribute('aria-label')?.substring(0, 200),
                dataPrice: el.getAttribute('data-price'),
            })).filter(el => el.text && /[\$€₹]|kr|USD|DKK/.test(el.text + (el.ariaLabel || ''))),
        };
    }""")

    # Also try to extract from a cleaner Google Flights URL approach
    # Use the encoded tfs parameter for precise route control
    print(f"    [{country}] Extracting data...")

    # Try the proper Google Flights search URL
    proper_url = f"https://www.google.com/travel/flights/search?tfs=CBwQAhoeEgoyMDI2LTA1LTIxagcIARID{origin}cgcIARID{dest}Gh4SCjIwMjYtMDUtMjhqBwgBEgN{dest}cgcIARID{origin}QAFIAXABggELCP___________wGYAQE&curr=USD"

    try:
        await page.goto(proper_url, timeout=60000, wait_until="domcontentloaded")
        await page.wait_for_timeout(10000)

        flights_data2 = await page.evaluate("""() => {
            const results = {url: window.location.href, title: document.title};

            // Get ALL text content that looks like flight info
            const allText = document.body.innerText;
            results.page_length = allText.length;

            // Extract lines that contain prices
            const lines = allText.split('\\n');
            const flightLines = [];
            for (let i = 0; i < lines.length; i++) {
                const line = lines[i].trim();
                if (/[\$€₹]|kr\.?\s*\d|USD|DKK|EUR/.test(line)) {
                    // Get context: 2 lines before and 2 after
                    const context = lines.slice(Math.max(0, i-3), i+3).map(l => l.trim()).filter(l => l);
                    flightLines.push({line, context, index: i});
                }
            }
            results.price_lines = flightLines.slice(0, 40);

            // Get aria labels with flight info
            const ariaLabels = [];
            document.querySelectorAll('[aria-label]').forEach(el => {
                const label = el.getAttribute('aria-label') || '';
                if (label.length > 20 && (
                    label.includes('Depart') || label.includes('price') ||
                    label.includes('$') || label.includes('kr') || label.includes('€') ||
                    label.includes('nonstop') || label.includes('stop') ||
                    label.includes('hr') || label.includes('min')
                )) {
                    ariaLabels.push(label.substring(0, 500));
                }
            });
            results.aria_flights = ariaLabels.slice(0, 30);

            return results;
        }""")

        flights_data["proper_url_data"] = flights_data2
    except Exception as e:
        flights_data["proper_url_error"] = str(e)

    # Take a screenshot for debugging
    try:
        screenshot_path = f"/tmp/gf_{country}_{origin}_{dest}.png"
        await page.screenshot(path=screenshot_path, full_page=False)
        flights_data["screenshot"] = screenshot_path
    except:
        pass

    await browser.close()
    await pw.stop()

    return {"raw": flights_data, "ip_info": ip_data}


async def run_all():
    # ═══ PART 1: US via SerpAPI ═══
    print("\n" + "=" * 70)
    print("  US POS — SerpAPI (google_flights engine)")
    print("=" * 70)

    us_results = {}
    for origin, dest, dep, ret, name in ROUTES:
        route_key = f"{origin}-{dest}"
        print(f"\n  [US] {name}...", end=" ", flush=True)
        result = serpapi_search(origin, dest, dep, ret)

        if "error" in result:
            print(f"ERROR: {result['error']}")
        else:
            flights = result["flights"]
            if flights:
                cheapest = min(flights, key=lambda f: f["price_usd"])
                print(f"{len(flights)} flights | Cheapest: ${cheapest['price']:,} "
                      f"— {cheapest['airlines']} {cheapest['flight_numbers']}")
            else:
                print("No flights")
        us_results[route_key] = result
        time.sleep(2)

    # ═══ PART 2: DK/DE/IN via Bright Data residential IPs ═══
    foreign_results = {}

    for country, cdp_url in CDP_URLS.items():
        print(f"\n{'='*70}")
        print(f"  {country} POS — Bright Data residential IP")
        print(f"{'='*70}")

        country_results = {}
        for origin, dest, dep, ret, name in ROUTES:
            route_key = f"{origin}-{dest}"
            print(f"\n  {name}:")
            result = await brightdata_google_flights(cdp_url, country, origin, dest, dep, ret)
            country_results[route_key] = result

        foreign_results[country] = country_results

    # ═══ RESULTS ═══
    print(f"\n\n{'='*90}")
    print("  RESULTS — US (SerpAPI) vs Foreign POS (Bright Data Residential)")
    print(f"{'='*90}")

    for origin, dest, dep, ret, name in ROUTES:
        route_key = f"{origin}-{dest}"
        print(f"\n{'─'*90}")
        print(f"  {name} ({dep} → {ret})")
        print(f"{'─'*90}")

        # US flights
        us_data = us_results.get(route_key, {})
        us_flights = us_data.get("flights", [])
        if us_flights:
            print(f"\n  US (SerpAPI) — {len(us_flights)} flights:")
            for f in sorted(us_flights, key=lambda x: x["price_usd"])[:10]:
                print(f"    ${f['price']:>6,} | {f['airlines']:<25} {f['flight_numbers']:<20} "
                      f"| {f['stops']} stop{'s' if f['stops'] != 1 else ''} | {f['dep_time']}")

        # Foreign results
        for country in CDP_URLS:
            c_data = foreign_results.get(country, {}).get(route_key, {})
            ip = c_data.get("ip_info", {})
            raw = c_data.get("raw", {})

            print(f"\n  {country} (Bright Data, IP country: {ip.get('country', '?')}):")

            # Print aria flight labels (most structured data we can get)
            proper = raw.get("proper_url_data", {})
            aria = proper.get("aria_flights", [])
            if aria:
                print(f"    Found {len(aria)} flight entries:")
                for a in aria[:15]:
                    print(f"      {a[:120]}")
            else:
                # Fallback to price lines
                price_lines = proper.get("price_lines", raw.get("price_lines", []))
                if price_lines:
                    print(f"    Found {len(price_lines)} price lines:")
                    for pl in price_lines[:10]:
                        ctx = " | ".join(pl.get("context", []))
                        print(f"      {ctx[:150]}")

            prices = raw.get("prices", [])
            if prices:
                print(f"    Raw prices found on page: {', '.join(prices[:15])}")

            if raw.get("screenshot"):
                print(f"    Screenshot: {raw['screenshot']}")

    # Save
    output = {
        "date": datetime.now().isoformat(),
        "us_results": us_results,
        "foreign_results": foreign_results,
    }
    out_path = f"pos_google_comparison_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\n  Saved to {out_path}")


if __name__ == "__main__":
    asyncio.run(run_all())
