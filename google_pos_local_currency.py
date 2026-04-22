#!/usr/bin/env python3
"""Google Flights LOCAL CURRENCY comparison.

Each country sees prices in their own currency.
DK → DKK, DE → EUR, IN → INR, US → USD via SerpAPI.
Convert everything to USD at market rates and compare.
"""

import asyncio
import json
import os
import re
import time
import requests
from datetime import datetime

SERPAPI_KEY = os.environ.get("SERPAPI_KEY", "")

BD_BASE = "wss://brd-customer-hl_890ca773-zone-scraping_browser1"
BD_AUTH = "xy22gst47vzm"
BD_HOST = "brd.superproxy.io:9222"

CDP_URLS = {
    "DK": f"{BD_BASE}-country-dk:{BD_AUTH}@{BD_HOST}",
    "DE": f"{BD_BASE}-country-de:{BD_AUTH}@{BD_HOST}",
    "IN": f"{BD_BASE}-country-in:{BD_AUTH}@{BD_HOST}",
}

LOCAL_CURRENCIES = {
    "DK": "DKK",
    "DE": "EUR",
    "IN": "INR",
}

ROUTES = [
    ("JFK", "MUC", "2026-05-21", "2026-05-28", "New York → Munich"),
    ("LAX", "NRT", "2026-06-10", "2026-06-17", "Los Angeles → Tokyo"),
    ("ORD", "LHR", "2026-06-15", "2026-06-22", "Chicago → London"),
]

# Fetch live FX rates
def get_fx_rates():
    """Try to get current FX rates."""
    rates = {"USD": 1.0, "EUR": 1.08, "DKK": 0.145, "INR": 0.012, "GBP": 1.27, "JPY": 0.0067}
    try:
        r = requests.get("https://open.er-api.com/v6/latest/USD", timeout=10)
        data = r.json()
        if data.get("result") == "success":
            for cur in ["EUR", "DKK", "INR", "GBP", "JPY"]:
                if cur in data["rates"]:
                    rates[cur] = round(1.0 / data["rates"][cur], 6)
            print(f"  Live FX: EUR={rates['EUR']}, DKK={rates['DKK']}, INR={rates['INR']}")
    except:
        print("  Using hardcoded FX rates")
    return rates

FX = {}


def to_usd(amount, currency):
    rate = FX.get(currency, 1.0)
    return round(amount * rate, 2)


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
        return []

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
                "price_usd": float(price),
                "airlines": " / ".join(dict.fromkeys(airlines)),
                "flight_numbers": "+".join(fns),
                "stops": len(legs) - 1,
                "dep_time": legs[0].get("departure_airport", {}).get("time", ""),
                "match_key": "+".join(fns),
            })
    return flights


async def accept_cookies(page):
    await page.wait_for_timeout(2000)
    selectors = [
        "button#L2AGLb",
        "button:has-text('Accept all')",
        "button:has-text('Acceptér alle')",
        "button:has-text('Alle akzeptieren')",
        "button:has-text('Alle accepteren')",
    ]
    for sel in selectors:
        try:
            btn = page.locator(sel).first
            if await btn.count() > 0 and await btn.is_visible():
                await btn.click(timeout=5000)
                await page.wait_for_timeout(2000)
                return True
        except:
            continue

    try:
        buttons = await page.evaluate("""() => {
            return Array.from(document.querySelectorAll('button'))
                .map(b => b.innerText.trim())
                .filter(t => t.length > 0 && t.length < 30);
        }""")
        for text in buttons:
            tl = text.lower()
            if any(w in tl for w in ["accept", "agree", "godkend", "akzeptier", "accett", "accepter"]):
                await page.click(f"button:has-text('{text}')")
                await page.wait_for_timeout(2000)
                return True
    except:
        pass
    return False


async def scrape_local_currency(cdp_url, country, currency, origin, dest, dep, ret):
    from playwright.async_api import async_playwright

    pw = await async_playwright().start()
    print(f"    [{country}] Connecting...", end=" ", flush=True)

    try:
        browser = await pw.chromium.connect_over_cdp(cdp_url)
    except Exception as e:
        print(f"FAIL: {e}")
        await pw.stop()
        return []

    page = await browser.new_page()

    # Verify IP
    try:
        await page.goto("https://ipinfo.io/json", timeout=20000)
        ip_data = json.loads(await page.evaluate("() => document.body.innerText"))
        print(f"IP={ip_data.get('ip','?')} ({ip_data.get('country','?')}, {ip_data.get('city','?')})", end=" ", flush=True)
    except:
        ip_data = {}

    # Accept cookies on google.com
    try:
        await page.goto("https://www.google.com/", timeout=30000, wait_until="domcontentloaded")
        await accept_cookies(page)
    except:
        pass

    # Search in LOCAL currency — no curr= param, let Google decide
    # Also don't force hl=en — let it use local language
    search_url = (
        f"https://www.google.com/travel/flights/search"
        f"?q=flights+from+{origin}+to+{dest}"
        f"+on+{dep}+return+{ret}"
    )

    print(f"searching...", end=" ", flush=True)
    try:
        await page.goto(search_url, timeout=60000, wait_until="domcontentloaded")
    except:
        try:
            await page.goto(search_url, timeout=60000, wait_until="commit")
        except Exception as e:
            print(f"FAIL: {e}")
            await browser.close()
            await pw.stop()
            return []

    await page.wait_for_timeout(3000)
    await accept_cookies(page)
    await page.wait_for_timeout(12000)

    print(f"extracting...", end=" ", flush=True)

    # Extract flight data with local currency prices
    raw = await page.evaluate(r"""() => {
        const body = document.body?.innerText || '';
        const result = {url: window.location.href, title: document.title, bodyLen: body.length};

        // Get ALL aria labels with flight data
        const flights = [];
        document.querySelectorAll('[aria-label]').forEach(el => {
            const label = el.getAttribute('aria-label') || '';
            if (label.length > 40 && (
                /\d+\s*(hr|min|stop|nonstop)/i.test(label) ||
                /(?:From\s+)?\d[\d,.]+\s*(?:US dollar|Danish|euro|Indian|krone|rupee|pound)/i.test(label) ||
                /(?:From\s+)?[\$€₹£]\s*[\d,]+/.test(label) ||
                /(?:From\s+)?(?:DKK|kr\.?|EUR|INR|USD)\s*[\d,.]+/i.test(label) ||
                /(?:From\s+)?[\d,.]+\s*(?:DKK|kr\.?|EUR|INR|USD)/i.test(label)
            )) {
                flights.push(label.substring(0, 500));
            }
        });
        result.flight_labels = flights.slice(0, 50);

        // Get all price-looking text elements
        const priceEls = [];
        document.querySelectorAll('span, div').forEach(el => {
            const text = el.innerText?.trim() || '';
            if (text.length > 0 && text.length < 40 &&
                (/^[\$€₹£]\s*[\d,.]+/.test(text) ||
                 /^(?:DKK|kr\.?|EUR|INR)\s*[\d,.]+/i.test(text) ||
                 /^[\d,.]+\s*(?:DKK|kr\.?|EUR|INR|USD)/i.test(text))) {
                priceEls.push(text);
            }
        });
        result.prices = [...new Set(priceEls)].slice(0, 30);

        // Check what currency symbol appears most
        const dollarCount = (body.match(/\$/g) || []).length;
        const euroCount = (body.match(/€/g) || []).length;
        const krCount = (body.match(/kr\.?/gi) || []).length;
        const rupeeCount = (body.match(/₹/g) || []).length;
        const dkkCount = (body.match(/DKK/gi) || []).length;
        result.currency_counts = {dollar: dollarCount, euro: euroCount, kr: krCount, rupee: rupeeCount, dkk: dkkCount};

        return result;
    }""")

    # Screenshot
    try:
        ss = f"/tmp/gf_local_{country}_{origin}_{dest}.png"
        await page.screenshot(path=ss, full_page=False)
        raw["screenshot"] = ss
    except:
        pass

    await browser.close()
    await pw.stop()

    # Parse flights from labels
    flights = []
    for label in raw.get("flight_labels", []):
        flight = parse_flight_label(label, currency)
        if flight:
            flights.append(flight)

    print(f"{len(flights)} flights parsed")
    raw["parsed_count"] = len(flights)

    return flights, raw


def parse_flight_label(label, expected_currency):
    """Parse a Google Flights aria-label into structured data."""
    flight = {}

    # Extract price — try multiple patterns
    # "From 8,234 Danish kroner"
    m = re.search(r'From\s+([\d,]+)\s+(?:US dollar|Danish krone|euro|Indian rupee|British pound)', label, re.I)
    if m:
        price_str = m.group(1).replace(",", "")
        try:
            flight["price"] = int(price_str)
        except:
            return None

        if "US dollar" in label.lower():
            flight["currency"] = "USD"
        elif "danish" in label.lower() or "krone" in label.lower():
            flight["currency"] = "DKK"
        elif "euro" in label.lower():
            flight["currency"] = "EUR"
        elif "indian" in label.lower() or "rupee" in label.lower():
            flight["currency"] = "INR"
        elif "pound" in label.lower():
            flight["currency"] = "GBP"
        else:
            flight["currency"] = expected_currency
    else:
        # Try symbol-based: "$1,234" or "€1,234" or "₹82,345" or "kr. 8.234"
        m2 = re.search(r'(?:From\s+)?([\$€₹£])\s*([\d,]+)', label)
        if m2:
            sym = m2.group(1)
            price_str = m2.group(2).replace(",", "")
            try:
                flight["price"] = int(price_str)
            except:
                return None
            flight["currency"] = {"$": "USD", "€": "EUR", "₹": "INR", "£": "GBP"}.get(sym, expected_currency)
        else:
            # Try "DKK 8,234" or "8.234 kr."
            m3 = re.search(r'(?:From\s+)?(?:DKK|kr\.?)\s*([\d,.]+)', label, re.I)
            if not m3:
                m3 = re.search(r'(?:From\s+)?([\d,.]+)\s*(?:DKK|kr\.?)', label, re.I)
            if m3:
                price_str = m3.group(1).replace(".", "").replace(",", "")
                try:
                    flight["price"] = int(price_str)
                except:
                    return None
                flight["currency"] = "DKK"
            else:
                return None

    flight["price_usd"] = to_usd(flight["price"], flight["currency"])

    # Extract airline
    m_airline = re.search(r'(?:with|Operated by)\s+([A-Z][a-zA-Z]+(?: [A-Z][a-zA-Z]+)*(?:\s+Airlines?)?)', label)
    if m_airline:
        flight["airline"] = m_airline.group(1)

    # Extract stops
    if "nonstop" in label.lower():
        flight["stops"] = 0
    else:
        m_stops = re.search(r'(\d+)\s*stop', label.lower())
        if m_stops:
            flight["stops"] = int(m_stops.group(1))

    # Extract departure info for matching
    m_dep = re.search(r'Leaves\s+.*?at\s+(\d{1,2}:\d{2}\s*[AP]M)', label)
    if m_dep:
        flight["dep_time"] = m_dep.group(1)

    flight["raw"] = label[:200]
    return flight


async def main():
    global FX
    print("=" * 80)
    print("  GOOGLE FLIGHTS LOCAL CURRENCY POS COMPARISON")
    print("  US=USD (SerpAPI) | DK=DKK | DE=EUR | IN=INR (Bright Data residential)")
    print("=" * 80)

    FX = get_fx_rates()

    # US via SerpAPI
    print(f"\n{'─'*80}")
    print("  US POS (SerpAPI, USD)")
    print(f"{'─'*80}")

    us_results = {}
    for origin, dest, dep, ret, name in ROUTES:
        rk = f"{origin}-{dest}"
        print(f"  {name}...", end=" ", flush=True)
        flights = serpapi_search(origin, dest, dep, ret)
        if flights:
            cheapest = min(flights, key=lambda f: f["price_usd"])
            print(f"{len(flights)} flights | Cheapest: ${cheapest['price']:,} — {cheapest['airlines']}")
        else:
            print("No flights")
        us_results[rk] = flights
        time.sleep(2)

    # Foreign POS with local currencies
    foreign_results = {}
    foreign_raw = {}

    for country, cdp_url in CDP_URLS.items():
        currency = LOCAL_CURRENCIES[country]
        print(f"\n{'─'*80}")
        print(f"  {country} POS (Bright Data residential, {currency})")
        print(f"{'─'*80}")

        country_flights = {}
        country_raw = {}

        for origin, dest, dep, ret, name in ROUTES:
            rk = f"{origin}-{dest}"
            print(f"  {name}:")
            result = await scrape_local_currency(cdp_url, country, currency, origin, dest, dep, ret)
            if isinstance(result, tuple):
                flights, raw = result
                country_flights[rk] = flights
                country_raw[rk] = raw
            else:
                country_flights[rk] = []
                country_raw[rk] = {}

        foreign_results[country] = country_flights
        foreign_raw[country] = country_raw

    # ═══ COMPARISON TABLE ═══
    print(f"\n\n{'='*100}")
    print("  PRICE COMPARISON — LOCAL CURRENCIES CONVERTED TO USD")
    print(f"  FX: 1 EUR = ${FX.get('EUR',0):.4f} | 1 DKK = ${FX.get('DKK',0):.4f} | 1 INR = ${FX.get('INR',0):.6f}")
    print(f"{'='*100}")

    for origin, dest, dep, ret, name in ROUTES:
        rk = f"{origin}-{dest}"
        print(f"\n{'─'*100}")
        print(f"  {name} ({dep} → {ret})")
        print(f"{'─'*100}")

        us_flights = us_results.get(rk, [])
        us_cheapest = min(us_flights, key=lambda f: f["price_usd"]) if us_flights else None

        # Header
        print(f"\n  {'Airline':<25} {'US (USD)':>12} {'DK (DKK→USD)':>16} {'DE (EUR→USD)':>16} {'IN (INR→USD)':>16} {'Best Δ vs US':>14}")
        print(f"  {'─'*25} {'─'*12} {'─'*16} {'─'*16} {'─'*16} {'─'*14}")

        # Build airline index from US results
        seen_airlines = {}
        for f in sorted(us_flights, key=lambda x: x["price_usd"]):
            airline = f["airlines"]
            if airline not in seen_airlines:
                seen_airlines[airline] = f

        # Also add airlines from foreign results
        for country in ["DK", "DE", "IN"]:
            for f in foreign_results.get(country, {}).get(rk, []):
                airline = f.get("airline", "Unknown")
                if airline not in seen_airlines:
                    seen_airlines[airline] = None

        # Print comparison
        for airline in list(seen_airlines.keys())[:15]:
            us_f = seen_airlines.get(airline)
            us_str = f"${us_f['price_usd']:>8,.0f}" if us_f else f"{'—':>9}"
            us_usd = us_f["price_usd"] if us_f else None

            best_foreign_usd = None
            cells = []

            for country in ["DK", "DE", "IN"]:
                currency = LOCAL_CURRENCIES[country]
                c_flights = foreign_results.get(country, {}).get(rk, [])

                # Find matching airline
                match = None
                for f in c_flights:
                    if f.get("airline", "").lower() in airline.lower() or airline.lower() in f.get("airline", "").lower():
                        match = f
                        break

                if match:
                    native = match["price"]
                    cur = match["currency"]
                    usd = match["price_usd"]
                    cells.append(f"{cur} {native:>7,}=${usd:>6,.0f}")

                    if best_foreign_usd is None or usd < best_foreign_usd:
                        best_foreign_usd = usd
                else:
                    cells.append(f"{'—':>16}")

            # Delta vs US
            delta_str = ""
            if us_usd and best_foreign_usd:
                diff = us_usd - best_foreign_usd
                pct = (diff / us_usd * 100) if us_usd else 0
                if abs(diff) > 1:
                    arrow = "SAVE" if diff > 0 else "MORE"
                    delta_str = f"${abs(diff):>5,.0f} ({abs(pct):.0f}%) {arrow}"

            print(f"  {airline:<25} {us_str:>12} {cells[0]:>16} {cells[1]:>16} {cells[2]:>16} {delta_str:>14}")

        # Summary for route
        if us_cheapest:
            print(f"\n  US cheapest: ${us_cheapest['price_usd']:,.0f} ({us_cheapest['airlines']})")

        for country in ["DK", "DE", "IN"]:
            c_flights = foreign_results.get(country, {}).get(rk, [])
            if c_flights:
                cheapest = min(c_flights, key=lambda f: f["price_usd"])
                cur = cheapest["currency"]
                print(f"  {country} cheapest: {cur} {cheapest['price']:,} (${cheapest['price_usd']:,.0f}) — {cheapest.get('airline','?')}")

                if us_cheapest:
                    diff = us_cheapest["price_usd"] - cheapest["price_usd"]
                    if abs(diff) > 1:
                        pct = abs(diff) / us_cheapest["price_usd"] * 100
                        direction = "CHEAPER" if diff > 0 else "MORE EXPENSIVE"
                        print(f"    → ${abs(diff):,.0f} ({pct:.1f}%) {direction} than US")

    # Show raw data for debugging
    print(f"\n\n{'='*80}")
    print("  RAW EXTRACTION DATA")
    print(f"{'='*80}")
    for country in ["DK", "DE", "IN"]:
        for origin, dest, dep, ret, name in ROUTES:
            rk = f"{origin}-{dest}"
            raw = foreign_raw.get(country, {}).get(rk, {})
            labels = raw.get("flight_labels", [])
            prices = raw.get("prices", [])
            cc = raw.get("currency_counts", {})
            print(f"\n  [{country}] {name}:")
            print(f"    Currency counts: $ {cc.get('dollar',0)} | € {cc.get('euro',0)} | kr {cc.get('kr',0)} | ₹ {cc.get('rupee',0)} | DKK {cc.get('dkk',0)}")
            print(f"    Price elements: {prices[:10]}")
            print(f"    Labels ({len(labels)}):")
            for l in labels[:5]:
                print(f"      {l[:150]}")
            if raw.get("screenshot"):
                print(f"    Screenshot: {raw['screenshot']}")

    # Save
    output = {
        "date": datetime.now().isoformat(),
        "fx_rates": FX,
        "us_results": us_results,
        "foreign_results": {k: {rk: [f for f in flights] for rk, flights in v.items()} for k, v in foreign_results.items()},
        "foreign_raw": foreign_raw,
    }
    out_path = f"pos_local_currency_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\n  Saved to {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
