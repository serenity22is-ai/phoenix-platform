"""
MYSTES Direct Google Flights Scraper

Bypasses SerpAPI to get REAL regional pricing using residential proxies.
Uses Playwright for headless browser automation.

Usage:
    from google_flights_scraper import scrape_flights_from_market

    # Search from Spanish market
    flights = await scrape_flights_from_market(
        origin="LAX",
        destination="BCN",
        date="2026-03-15",
        market="ES"
    )
"""

import asyncio
import json
import re
import os
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from urllib.parse import urlencode

from dotenv import load_dotenv
load_dotenv()

from proxy_manager import get_proxy_for_market, get_timezone_for_market, MARKET_TO_COUNTRY_CODE

# Market configuration for Google Flights URLs
MARKET_CONFIG = {
    "US": {"domain": "google.com",    "hl": "en", "gl": "us", "currency": "USD"},
    "UK": {"domain": "google.co.uk",  "hl": "en", "gl": "uk", "currency": "GBP"},
    "GB": {"domain": "google.co.uk",  "hl": "en", "gl": "uk", "currency": "GBP"},
    "DE": {"domain": "google.de",     "hl": "de", "gl": "de", "currency": "EUR"},
    "FR": {"domain": "google.fr",     "hl": "fr", "gl": "fr", "currency": "EUR"},
    "ES": {"domain": "google.es",     "hl": "es", "gl": "es", "currency": "EUR"},
    "IT": {"domain": "google.it",     "hl": "it", "gl": "it", "currency": "EUR"},
    "JP": {"domain": "google.co.jp",  "hl": "ja", "gl": "jp", "currency": "JPY"},
    "AU": {"domain": "google.com.au", "hl": "en", "gl": "au", "currency": "AUD"},
    "CA": {"domain": "google.ca",     "hl": "en", "gl": "ca", "currency": "CAD"},
    "BR": {"domain": "google.com.br", "hl": "pt", "gl": "br", "currency": "BRL"},
    "IN": {"domain": "google.co.in",  "hl": "en", "gl": "in", "currency": "INR"},
    "KR": {"domain": "google.co.kr",  "hl": "ko", "gl": "kr", "currency": "KRW"},
    "MX": {"domain": "google.com.mx", "hl": "es", "gl": "mx", "currency": "MXN"},
    "NL": {"domain": "google.nl",     "hl": "nl", "gl": "nl", "currency": "EUR"},
    "SE": {"domain": "google.se",     "hl": "sv", "gl": "se", "currency": "SEK"},
    "TH": {"domain": "google.co.th",  "hl": "th", "gl": "th", "currency": "THB"},
    "PL": {"domain": "google.pl",     "hl": "pl", "gl": "pl", "currency": "PLN"},
}


def build_google_flights_url(origin: str, destination: str, date: str, market: str,
                              cabin_class: str = "economy", adults: int = 1,
                              return_date: str = None) -> str:
    """
    Build Google Flights URL for a specific market.

    One-way: https://www.google.com/travel/flights?q=Flights%20to%20BCN%20from%20LAX%20on%202026-03-15
    Round-trip: ...on%202026-03-15%20returning%202026-03-22
    """
    config = MARKET_CONFIG.get(market, MARKET_CONFIG["US"])
    domain = config["domain"]
    currency = config["currency"]

    if return_date:
        query = f"Flights from {origin} to {destination} on {date} returning {return_date}"
    else:
        query = f"Flights from {origin} to {destination} on {date}"

    params = {
        "hl": config["hl"],
        "gl": config["gl"],
        "curr": currency,
        "q": query,
    }

    return f"https://www.{domain}/travel/flights?{urlencode(params)}"


async def scrape_flights_from_market(
    origin: str,
    destination: str,
    date: str,
    market: str,
    cabin_class: str = "economy",
    adults: int = 1,
    timeout: int = 45000,
    return_date: str = None
) -> Dict[str, Any]:
    """
    Scrape Google Flights from a specific market using residential proxy.

    Args:
        origin: Origin airport code (e.g., "LAX")
        destination: Destination airport code (e.g., "BCN")
        date: Flight date (YYYY-MM-DD)
        market: Market code (e.g., "ES", "UK", "DE")
        cabin_class: Cabin class (economy, premium_economy, business, first)
        adults: Number of passengers
        timeout: Page load timeout in ms
        return_date: Return date for round-trip (YYYY-MM-DD), None for one-way

    Returns:
        Dict with flights, market info, and any errors
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return {
            "success": False,
            "market": market,
            "error": "Playwright not installed. Run: pip install playwright && playwright install chromium",
            "flights": []
        }

    # Get proxy for this market
    proxy_info = get_proxy_for_market(market)
    proxy_config = None
    if proxy_info and proxy_info.get("server") and proxy_info.get("username"):
        proxy_config = {
            "server": proxy_info["server"],
            "username": proxy_info["username"],
            "password": proxy_info.get("password", ""),
        }

    config = MARKET_CONFIG.get(market, MARKET_CONFIG["US"])
    url = build_google_flights_url(origin, destination, date, market, cabin_class, adults, return_date)

    result = {
        "success": False,
        "market": market,
        "currency": config["currency"],
        "url": url,
        "proxy_used": bool(proxy_config),
        "is_round_trip": bool(return_date),
        "flights": [],
        "error": None
    }

    async with async_playwright() as p:
        try:
            # Launch browser with proxy if available
            browser_args = {
                "headless": True,
                "args": [
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--no-sandbox"
                ]
            }

            if proxy_config:
                browser_args["proxy"] = proxy_config
                print(f"  [{market}] Using proxy: {proxy_config['server']}")

            browser = await p.chromium.launch(**browser_args)

            # Create context with realistic browser fingerprint
            tz = get_timezone_for_market(market)
            context = await browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                locale=config["hl"],
                timezone_id=tz,
            )

            page = await context.new_page()

            # Navigate to Google Flights
            print(f"  [{market}] Loading: {url[:80]}...")
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=timeout)
            except Exception:
                # Retry once with longer timeout if first attempt fails
                print(f"  [{market}] Retrying with longer timeout...")
                await page.goto(url, wait_until="domcontentloaded", timeout=timeout + 15000)

            # Wait for initial load
            await page.wait_for_timeout(2000)

            # Handle Google consent dialog (appears in EU markets)
            consent_buttons = [
                'button:has-text("Aceptar todo")',      # Spanish
                'button:has-text("Accept all")',        # English
                'button:has-text("Alle akzeptieren")',  # German
                'button:has-text("Tout accepter")',     # French
                'button:has-text("Aceitar tudo")',      # Portuguese
                'button:has-text("Accetta tutto")',     # Italian
                'button:has-text("Alles accepteren")',  # Dutch
                'button:has-text("Acceptera alla")',    # Swedish
                'button:has-text("Zaakceptuj wszystko")',# Polish
            ]
            for btn_selector in consent_buttons:
                try:
                    btn = page.locator(btn_selector).first
                    if await btn.count() > 0:
                        await btn.click()
                        print(f"  [{market}] Accepted consent dialog")
                        await page.wait_for_timeout(3000)
                        break
                except:
                    pass

            # Wait for flight results to fully load
            await page.wait_for_timeout(5000)

            # Try structured DOM extraction first, then fall back to price-only regex
            flights = await extract_flights_from_dom(page, market, config["currency"])
            if not flights:
                # Fallback: extract prices from raw text
                page_text = await page.inner_text('body')
                flights = extract_prices_from_text(page_text, market, config["currency"])

            result["success"] = True
            result["flights"] = flights
            print(f"  [{market}] Found {len(flights)} flights")

            await browser.close()

        except Exception as e:
            result["error"] = str(e)
            print(f"  [{market}] Error: {e}")

    return result


async def extract_flights_from_dom(page, market: str, currency: str) -> List[Dict]:
    """
    Extract structured flight data from the Google Flights page DOM.

    Google Flights renders flight results as list items (li elements) within
    an ordered list. Each flight row contains departure/arrival times, airline,
    duration, stops, and price in a structured layout.

    Returns list of flight dicts with airline, times, duration, stops, price.
    """
    try:
        flights = await page.evaluate("""
        () => {
            const flights = [];
            // Google Flights uses list items within specific containers for results.
            // Try multiple selectors in order of specificity.
            let rows = document.querySelectorAll('ul > li[class]');
            if (rows.length === 0) rows = document.querySelectorAll('ol > li');
            if (rows.length === 0) rows = document.querySelectorAll('li');
            // Filter to only li elements that contain a price pattern
            const priceRe = /[$€£¥₹₩฿]\s*[\d,.\s]+|[\d,.\s]+\s*[$€£¥₹₩฿]|[\d,.]+\s*(?:zł|kr|MX\$|R\$|C\$|A\$)/;
            const filteredRows = Array.from(rows).filter(r => priceRe.test(r.innerText || ''));
            const useRows = filteredRows.length > 0 ? filteredRows : rows;

            for (const row of useRows) {
                const text = row.innerText || '';
                const rawLines = text.split('\\n').map(l => l.trim()).filter(Boolean);

                // Join lines that form a time range (Google splits "6:00 AM" "–" "2:17 PM")
                const lines = [];
                for (let i = 0; i < rawLines.length; i++) {
                    if (rawLines[i] === '–' || rawLines[i] === '—' || rawLines[i] === '-') {
                        // Merge prev + dash + next into one line
                        if (lines.length > 0 && i + 1 < rawLines.length) {
                            lines[lines.length - 1] += ' – ' + rawLines[i + 1];
                            i++; // skip next
                            continue;
                        }
                    }
                    lines.push(rawLines[i]);
                }

                // A flight row typically has: times, airline, duration, stops, price
                // Minimum viable: must have a time pattern and a price
                const timePattern = /(\d{1,2}:\d{2})\s*[–—-]\s*(\d{1,2}:\d{2})/;
                const ampmPattern = /(\d{1,2}:\d{2}\s*[APap][Mm])\s*[–—-]\s*(\d{1,2}:\d{2}\s*[APap][Mm])/;

                let depTime = null, arrTime = null, airline = null, duration = null;
                let stops = null, price = null, priceRaw = null;

                for (const line of lines) {
                    // Match time range (24h or AM/PM)
                    let tm = line.match(ampmPattern) || line.match(timePattern);
                    if (tm && !depTime) {
                        depTime = tm[1].trim();
                        arrTime = tm[2].trim();
                        continue;
                    }

                    // Also try standalone time pattern (single time on a line)
                    if (!depTime) {
                        let singleTime = line.match(/^(\d{1,2}:\d{2}\s*(?:[APap][Mm])?)\s*$/);
                        if (singleTime) {
                            depTime = singleTime[1].trim();
                            continue;
                        }
                    } else if (depTime && !arrTime) {
                        let singleTime = line.match(/^(\d{1,2}:\d{2}\s*(?:[APap][Mm])?)\s*$/);
                        if (singleTime) {
                            arrTime = singleTime[1].trim();
                            continue;
                        }
                    }

                    // Match duration (e.g., "5 hr 30 min", "5h 30m", "2 hr")
                    let dur = line.match(/(\d+)\s*(?:hr|h|Std)\s*(?:(\d+)\s*(?:min|m|Min))?/i);
                    if (dur && !duration) {
                        duration = dur[0];
                        continue;
                    }

                    // Match stops
                    if (/nonstop|direct|directo|sans escale|ohne Umstieg|Nonstop/i.test(line) && stops === null) {
                        stops = 0;
                        continue;
                    }
                    let stopMatch = line.match(/(\d+)\s*(?:stop|escala|Stopp|arrêt|parada)/i);
                    if (stopMatch && stops === null) {
                        stops = parseInt(stopMatch[1]);
                        continue;
                    }

                    // Match price (currency symbols)
                    let priceMatch = line.match(/[$€£¥₹₩฿]\s*([\d,.\s]+)/) ||
                                     line.match(/([\d,.\s]+)\s*[$€£¥₹₩฿]/) ||
                                     line.match(/([\d,.]+)\s*(?:zł|kr|MX\$|R\$|C\$|A\$)/);
                    if (priceMatch && !price) {
                        let raw = (priceMatch[1] || priceMatch[0]).replace(/[^0-9.,]/g, '');
                        // Handle thousands separators
                        if (raw.includes('.') && raw.includes(',')) {
                            raw = raw.replace('.', '').replace(',', '.');
                        } else {
                            raw = raw.replace(',', '');
                        }
                        let p = parseFloat(raw);
                        if (p > 0) {
                            price = p;
                            priceRaw = line;
                        }
                        continue;
                    }
                }

                // Infer airline and flight number from remaining lines
                let flightNumber = null;
                if (depTime || price) {
                    for (const line of lines) {
                        if (line.match(timePattern) || line.match(ampmPattern)) continue;
                        if (line.match(/(\d+)\s*(?:hr|h|Std)/i)) continue;
                        if (line.match(/nonstop|direct|\d+\s*stop/i)) continue;
                        if (line.match(/[$€£¥₹₩฿]|zł|kr/)) continue;

                        // Flight number patterns: "AA 1234", "DL 456", "UA1234", "B6 683"
                        let fnMatch = line.match(/\b([A-Z]{2}|[A-Z]\d|\d[A-Z])\s*(\d{1,4})\b/);
                        if (fnMatch && !flightNumber) {
                            flightNumber = fnMatch[1] + ' ' + fnMatch[2];
                            // Don't continue — the same line might also contain the airline name
                        }

                        // Airline name extraction with known-airline matching
                        const skipTerms = /^(round trip|ida y vuelta|hin und r[üu]ck|retourticket|w obie strony|andata e ritorno|aller[- ]retour|viaje redondo|tur.retur|往復|왕복|ไปกลับ|ida e volta|return|Roundtrip)$/i;
                        const envTerms = /emission|carbon|co2|avg |average|footprint|less than|typical|separate tickets/i;
                        if (!airline && line.length > 2 && line.length < 60 && /[A-Za-zÀ-ÿ]/.test(line) && !skipTerms.test(line) && !envTerms.test(line)) {
                            // Known airlines — longest match wins (handles "JetBlue", "Air France", etc.)
                            const knownAirlines = [
                                'American Airlines', 'American', 'Delta Air Lines', 'Delta',
                                'United Airlines', 'United', 'Air France', 'British Airways',
                                'Lufthansa', 'Virgin Atlantic', 'JetBlue', 'KLM',
                                'SWISS', 'Swiss International', 'Iberia', 'Turkish Airlines',
                                'ANA', 'All Nippon', 'JAL', 'Japan Airlines',
                                'TAP Air Portugal', 'Tap Air Portugal', 'Aer Lingus',
                                'LOT', 'LOT Polish', 'ITA Airways', 'Austrian',
                                'Condor', 'Icelandair', 'Norwegian', 'Air Canada',
                                'WestJet', 'Cathay Pacific', 'Singapore Airlines',
                                'Korean Air', 'EVA Air', 'STARLUX', 'STARLUX Airlines',
                                'China Airlines', 'Finnair', 'SAS', 'Eurowings',
                                'PLAY', 'French Bee', 'Norse Atlantic', 'Zipair',
                                'Edelweiss', 'Air Europa', 'LATAM', 'Avianca',
                                'Copa Airlines', 'Volaris', 'Aeromexico',
                            ];
                            // Try to find a known airline name in the line
                            let found = null;
                            for (const known of knownAirlines) {
                                const idx = line.indexOf(known);
                                if (idx >= 0) {
                                    // Prefer longer matches
                                    if (!found || known.length > found.length) {
                                        found = known;
                                    }
                                }
                            }
                            // Also try case-insensitive match
                            if (!found) {
                                const lineLower = line.toLowerCase();
                                for (const known of knownAirlines) {
                                    if (lineLower.includes(known.toLowerCase())) {
                                        if (!found || known.length > found.length) {
                                            found = known;
                                        }
                                    }
                                }
                            }
                            if (found) {
                                airline = found;
                            } else if (/^[A-Za-zÀ-ÿ\s\-\.]+$/.test(line) && line.length < 40) {
                                // Fallback: use the line if it's purely alphabetic
                                airline = line;
                            }
                        }
                    }
                }

                // Only include if we have at least a price and some identifying info
                if (price && (depTime || airline)) {
                    flights.push({
                        airline: airline || 'Unknown Airline',
                        flight_number: flightNumber || null,
                        departure_time: depTime || null,
                        arrival_time: arrTime || null,
                        duration: duration || null,
                        stops: stops,
                        price: price,
                    });
                }
            }

            // Deduplicate by departure_time + price
            const seen = new Set();
            return flights.filter(f => {
                const key = (f.departure_time || '') + '_' + f.price;
                if (seen.has(key)) return false;
                seen.add(key);
                return true;
            });
        }
        """)

        result = []
        for i, f in enumerate(flights[:15]):
            price = f.get("price", 0)
            # Filter reasonable price range
            min_price, max_price = 30, 50000
            if currency == "JPY":
                min_price, max_price = 3000, 500000
            elif currency == "KRW":
                min_price, max_price = 30000, 5000000
            elif currency in ("INR", "THB"):
                min_price, max_price = 500, 200000

            if min_price < price < max_price:
                result.append({
                    "airline": f.get("airline", "Unknown Airline"),
                    "flight_number": f.get("flight_number"),
                    "price": float(price),
                    "currency": currency,
                    "stops": f.get("stops"),
                    "duration": f.get("duration"),
                    "departure_time": f.get("departure_time"),
                    "arrival_time": f.get("arrival_time"),
                    "market": market,
                    "index": i,
                })

        # Sort by price
        result.sort(key=lambda x: x["price"])
        if result:
            airlines = set(f["airline"] for f in result if f["airline"] != "Unknown Airline")
            has_times = sum(1 for f in result if f.get("departure_time"))
            print(f"  [{market}] DOM extraction: {len(result)} flights, {has_times} with times, airlines: {', '.join(airlines) or 'unknown'}")
        else:
            print(f"  [{market}] DOM extraction: 0 flights (raw JS returned {len(flights)} candidates)")
        return result

    except Exception as e:
        print(f"  [{market}] DOM extraction failed: {e}, falling back to text extraction")
        return []


def extract_prices_from_text(text: str, market: str, currency: str) -> List[Dict]:
    """
    Extract flight prices from visible page text.
    This is more reliable than parsing raw HTML.
    """
    flights = []
    seen_prices = set()

    # Currency-specific patterns
    patterns_by_currency = {
        "EUR": [r'(\d{1,3}(?:[.,]\d{3})*)\s*€', r'€\s*(\d{1,3}(?:[.,]\d{3})*)'],
        "USD": [r'\$\s*(\d{1,3}(?:,\d{3})*)', r'(\d{1,3}(?:,\d{3})*)\s*\$'],
        "GBP": [r'£\s*(\d{1,3}(?:,\d{3})*)', r'(\d{1,3}(?:,\d{3})*)\s*£'],
        "JPY": [r'¥\s*([\d,]+)', r'([\d,]+)\s*¥', r'￥\s*([\d,]+)'],
        "AUD": [r'A\$\s*(\d{1,3}(?:,\d{3})*)', r'\$\s*(\d{1,3}(?:,\d{3})*)'],
        "CAD": [r'C\$\s*(\d{1,3}(?:,\d{3})*)', r'\$\s*(\d{1,3}(?:,\d{3})*)'],
        "BRL": [r'R\$\s*([\d.,]+)'],
        "INR": [r'₹\s*([\d,]+)', r'([\d,]+)\s*₹'],
        "KRW": [r'₩\s*([\d,]+)', r'([\d,]+)\s*₩'],
        "MXN": [r'MX\$\s*([\d,]+)', r'\$\s*([\d,]+)'],
        "SEK": [r'(\d{1,3}(?:\s?\d{3})*)\s*kr', r'SEK\s*(\d+)'],
        "THB": [r'฿\s*([\d,]+)', r'(\d+)\s*฿'],
        "PLN": [r'(\d+)\s*zł', r'zł\s*(\d+)'],
    }

    patterns = patterns_by_currency.get(currency, patterns_by_currency["USD"])

    for pattern in patterns:
        matches = re.findall(pattern, text)
        for match in matches:
            try:
                # Normalize number: remove spaces, dots as thousands sep, commas as thousands sep
                clean = match.replace(" ", "").replace("\u00a0", "")
                # Handle European format (1.234 or 1,234)
                if "." in clean and "," in clean:
                    # e.g. 1.234,56 -> 1234.56
                    clean = clean.replace(".", "").replace(",", ".")
                elif "," in clean:
                    # Could be thousands separator (1,234) or decimal (123,45)
                    # For flight prices, assume thousands separator
                    clean = clean.replace(",", "")
                elif "." in clean and len(clean.split(".")[-1]) == 3:
                    # Dot as thousands separator (1.234)
                    clean = clean.replace(".", "")

                price = int(float(clean))

                # Filter to reasonable flight price range
                min_price = 50
                max_price = 50000
                if currency == "JPY":
                    min_price = 5000
                    max_price = 500000
                elif currency == "KRW":
                    min_price = 50000
                    max_price = 5000000
                elif currency in ("INR", "THB"):
                    min_price = 1000
                    max_price = 200000

                if min_price < price < max_price and price not in seen_prices:
                    seen_prices.add(price)
                    flights.append({
                        "airline": "Various Airlines",
                        "price": float(price),
                        "currency": currency,
                        "stops": None,
                        "duration": None,
                        "departure_time": None,
                        "arrival_time": None,
                        "market": market,
                        "index": len(flights)
                    })
            except (ValueError, IndexError):
                continue

    # Sort by price and re-index
    flights.sort(key=lambda x: x["price"])
    for i, f in enumerate(flights[:15]):
        f["index"] = i
    return flights[:15]


async def scrape_multiple_markets(
    origin: str,
    destination: str,
    date: str,
    markets: List[str],
    cabin_class: str = "economy",
    max_concurrent: int = 3,
    return_date: str = None
) -> Dict[str, Any]:
    """
    Scrape Google Flights from multiple markets in parallel.

    Returns combined results with price comparison across all markets.
    """
    print(f"\nScraping {origin} -> {destination} on {date} from {len(markets)} markets...")

    results = {
        "origin": origin,
        "destination": destination,
        "date": date,
        "return_date": return_date,
        "is_round_trip": bool(return_date),
        "markets_checked": [],
        "all_results": {},
        "cheapest_market": None,
        "cheapest_price_usd": None,
        "price_comparison": [],
        "savings_vs_us": 0,
        "savings_pct": 0,
    }

    # Process markets in batches with semaphore
    semaphore = asyncio.Semaphore(max_concurrent)

    async def scrape_with_limit(market):
        async with semaphore:
            return await scrape_flights_from_market(
                origin, destination, date, market, cabin_class,
                return_date=return_date
            )

    # Run all scrapes in parallel
    tasks = [scrape_with_limit(m) for m in markets]
    market_results = await asyncio.gather(*tasks, return_exceptions=True)

    # Process results and find cheapest
    for market, mresult in zip(markets, market_results):
        if isinstance(mresult, Exception):
            results["all_results"][market] = {"error": str(mresult), "flights": [], "currency": "USD", "flight_count": 0}
        else:
            results["all_results"][market] = mresult
            results["all_results"][market]["flight_count"] = len(mresult.get("flights", []))
            results["markets_checked"].append(market)

    # Find cheapest across all markets (convert to USD for comparison)
    # Import currency rates from main if available, else use defaults
    try:
        from main import CURRENCY_RATES_TO_USD
    except ImportError:
        CURRENCY_RATES_TO_USD = {
            "USD": 1.0, "EUR": 1.08, "GBP": 1.27, "JPY": 0.0067,
            "AUD": 0.65, "CAD": 0.74, "BRL": 0.20, "INR": 0.012,
            "KRW": 0.00075, "MXN": 0.058, "SEK": 0.096, "THB": 0.028,
            "PLN": 0.25,
        }

    for market, data in results["all_results"].items():
        if not data.get("flights"):
            continue

        currency = data.get("currency", "USD")
        rate = CURRENCY_RATES_TO_USD.get(currency, 1.0)

        for flight in data["flights"]:
            price = flight.get("price")
            if price:
                price_usd = price * rate
                results["price_comparison"].append({
                    "market": market,
                    "local_price": price,
                    "currency": currency,
                    "price_usd": round(price_usd, 2),
                    "airline": flight.get("airline", "Unknown"),
                    "flight_count": len(data["flights"]),
                })

    # Sort by USD price
    results["price_comparison"].sort(key=lambda x: x["price_usd"])

    if results["price_comparison"]:
        cheapest = results["price_comparison"][0]
        results["cheapest_market"] = cheapest["market"]
        results["cheapest_price_usd"] = cheapest["price_usd"]

        # Calculate savings vs US market
        us_prices = [p for p in results["price_comparison"] if p["market"] == "US"]
        if us_prices:
            us_cheapest = us_prices[0]["price_usd"]
            savings = us_cheapest - cheapest["price_usd"]
            results["savings_vs_us"] = round(savings, 2)
            results["savings_pct"] = round((savings / us_cheapest) * 100, 1) if us_cheapest > 0 else 0

    return results


def scrape_flights_sync(origin, destination, date, markets, cabin_class="economy", return_date=None):
    """Synchronous wrapper for scraping flights from multiple markets."""
    return asyncio.run(scrape_multiple_markets(
        origin, destination, date, markets, cabin_class,
        max_concurrent=len(markets), return_date=return_date
    ))
