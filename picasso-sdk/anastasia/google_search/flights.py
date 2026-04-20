"""
Google Flights Scraper — Proxy-routed Google Flights search via Playwright.

Scrapes real Google Flights results through residential proxy to get
foreign POS pricing. This is the core data source for POS arbitrage.

Two modes:
1. Standard Playwright (search): headless browser → proxy → Google Flights
2. Scraping Browser CDP (booking-adjacent): Bright Data hosted Chrome → Google

The existing root-level google_flights_scraper.py is the MYSTES template
wrapper. This neuron-level module is the ANASTASiA engine that powers it.

MYSTES KYRIOS LLC — Confidential.
"""

import asyncio
import logging
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

logger = logging.getLogger(__name__)

# Market-specific Google Flights config
GOOGLE_FLIGHTS_MARKETS = {
    "US": {"domain": "google.com",    "hl": "en", "gl": "us", "currency": "USD"},
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
    "DK": {"domain": "google.dk",     "hl": "da", "gl": "dk", "currency": "DKK"},
    "NO": {"domain": "google.no",     "hl": "no", "gl": "no", "currency": "NOK"},
    "FI": {"domain": "google.fi",     "hl": "fi", "gl": "fi", "currency": "EUR"},
    "CH": {"domain": "google.ch",     "hl": "de", "gl": "ch", "currency": "CHF"},
    "AT": {"domain": "google.at",     "hl": "de", "gl": "at", "currency": "EUR"},
    "BE": {"domain": "google.be",     "hl": "nl", "gl": "be", "currency": "EUR"},
    "PT": {"domain": "google.pt",     "hl": "pt", "gl": "pt", "currency": "EUR"},
    "IE": {"domain": "google.ie",     "hl": "en", "gl": "ie", "currency": "EUR"},
}

# Approximate rates to USD for cross-market comparison
CURRENCY_RATES_TO_USD = {
    "USD": 1.0, "EUR": 1.08, "GBP": 1.27, "JPY": 0.0067,
    "AUD": 0.65, "CAD": 0.74, "BRL": 0.20, "INR": 0.012,
    "KRW": 0.00075, "MXN": 0.058, "SEK": 0.096, "THB": 0.028,
    "PLN": 0.25, "DKK": 0.145, "NOK": 0.094, "CHF": 1.13,
    "CZK": 0.044, "HUF": 0.0028, "RON": 0.22, "SGD": 0.74,
    "HKD": 0.13,
}

# EU consent button selectors (multi-language)
CONSENT_SELECTORS = [
    'button:has-text("Accept all")',
    'button:has-text("Aceptar todo")',
    'button:has-text("Alle akzeptieren")',
    'button:has-text("Tout accepter")',
    'button:has-text("Aceitar tudo")',
    'button:has-text("Accetta tutto")',
    'button:has-text("Alles accepteren")',
    'button:has-text("Acceptera alla")',
    'button:has-text("Zaakceptuj wszystko")',
    'button:has-text("Accepter alle")',
    'button:has-text("Godkjenn alle")',
    'button:has-text("Hyväksy kaikki")',
]


def build_flights_url(
    origin: str,
    destination: str,
    date: str,
    market: str,
    return_date: Optional[str] = None,
) -> str:
    """Build Google Flights URL for a specific market."""
    config = GOOGLE_FLIGHTS_MARKETS.get(market, GOOGLE_FLIGHTS_MARKETS["US"])
    query = f"Flights from {origin} to {destination} on {date}"
    if return_date:
        query += f" returning {return_date}"
    params = {
        "hl": config["hl"],
        "gl": config["gl"],
        "curr": config["currency"],
        "q": query,
    }
    return f"https://www.{config['domain']}/travel/flights?{urlencode(params)}"


class GoogleFlightsScraper:
    """
    Scrapes Google Flights via Playwright + residential proxy.

    This class does NOT import proxy_manager directly. It receives
    proxy config from the GoogleSearchModule (which gets it from
    the Proxy neuron), keeping the dependency chain clean.
    """

    # DOM extraction JavaScript — adapted from google_flights_scraper.py
    EXTRACT_FLIGHTS_JS = """
    () => {
        const flights = [];
        let rows = document.querySelectorAll('ul > li[class]');
        if (rows.length === 0) rows = document.querySelectorAll('ol > li');
        if (rows.length === 0) rows = document.querySelectorAll('li');
        const priceRe = /[$€£¥₹₩฿]\s*[\\d,.\\s]+|[\\d,.\\s]+\\s*[$€£¥₹₩฿]|[\\d,.]+\\s*(?:zł|kr|MX\\$|R\\$|C\\$|A\\$|DKK|NOK|CHF)/;
        const filteredRows = Array.from(rows).filter(r => priceRe.test(r.innerText || ''));
        const useRows = filteredRows.length > 0 ? filteredRows : rows;

        for (const row of useRows) {
            const text = row.innerText || '';
            const rawLines = text.split('\\n').map(l => l.trim()).filter(Boolean);
            const lines = [];
            for (let i = 0; i < rawLines.length; i++) {
                if ((rawLines[i] === '–' || rawLines[i] === '—' || rawLines[i] === '-') &&
                    lines.length > 0 && i + 1 < rawLines.length) {
                    lines[lines.length - 1] += ' – ' + rawLines[i + 1];
                    i++;
                    continue;
                }
                lines.push(rawLines[i]);
            }

            const timePattern = /(\\d{1,2}:\\d{2})\\s*[–—-]\\s*(\\d{1,2}:\\d{2})/;
            const ampmPattern = /(\\d{1,2}:\\d{2}\\s*[APap][Mm])\\s*[–—-]\\s*(\\d{1,2}:\\d{2}\\s*[APap][Mm])/;

            let depTime = null, arrTime = null, airline = null, duration = null;
            let stops = null, price = null;

            for (const line of lines) {
                let tm = line.match(ampmPattern) || line.match(timePattern);
                if (tm && !depTime) { depTime = tm[1].trim(); arrTime = tm[2].trim(); continue; }
                let dur = line.match(/(\\d+)\\s*(?:hr|h|Std)\\s*(?:(\\d+)\\s*(?:min|m|Min))?/i);
                if (dur && !duration) { duration = dur[0]; continue; }
                if (/nonstop|direct|directo|sans escale|ohne Umstieg/i.test(line) && stops === null) { stops = 0; continue; }
                let stopMatch = line.match(/(\\d+)\\s*(?:stop|escala|Stopp|arrêt|parada)/i);
                if (stopMatch && stops === null) { stops = parseInt(stopMatch[1]); continue; }
                let priceMatch = line.match(/[$€£¥₹₩฿]\\s*([\\d,.\\s]+)/) ||
                                 line.match(/([\\d,.\\s]+)\\s*[$€£¥₹₩฿]/) ||
                                 line.match(/([\\d,.]+)\\s*(?:zł|kr|MX\\$|R\\$|C\\$|A\\$|DKK|NOK|CHF)/);
                if (priceMatch && !price) {
                    let raw = (priceMatch[1] || priceMatch[0]).replace(/[^0-9.,]/g, '');
                    if (raw.includes('.') && raw.includes(',')) { raw = raw.replace('.', '').replace(',', '.'); }
                    else { raw = raw.replace(',', ''); }
                    let p = parseFloat(raw);
                    if (p > 0) { price = p; }
                    continue;
                }
            }

            if (depTime || price) {
                for (const line of lines) {
                    if (line.match(timePattern) || line.match(ampmPattern)) continue;
                    if (line.match(/(\\d+)\\s*(?:hr|h|Std)/i)) continue;
                    if (line.match(/nonstop|direct|\\d+\\s*stop/i)) continue;
                    if (line.match(/[$€£¥₹₩฿]|zł|kr|DKK|NOK|CHF/)) continue;
                    const skipTerms = /^(round trip|ida y vuelta|hin und rück|retourticket|return|Roundtrip)$/i;
                    const envTerms = /emission|carbon|co2|avg |average|footprint|separate tickets/i;
                    if (!airline && line.length > 2 && line.length < 60 && /[A-Za-zÀ-ÿ]/.test(line) && !skipTerms.test(line) && !envTerms.test(line)) {
                        const known = ['American Airlines','Delta Air Lines','Delta','United Airlines','United','Air France','British Airways','Lufthansa','JetBlue','KLM','SWISS','Iberia','Turkish Airlines','ANA','JAL','Japan Airlines','LOT','ITA Airways','Condor','Icelandair','Norwegian','Air Canada','Cathay Pacific','Singapore Airlines','Korean Air','SAS','Finnair','PLAY','Norse Atlantic','Zipair'];
                        let found = null;
                        const ll = line.toLowerCase();
                        for (const k of known) { if (ll.includes(k.toLowerCase()) && (!found || k.length > found.length)) found = k; }
                        airline = found || ((/^[A-Za-zÀ-ÿ\\s\\-\\.]+$/.test(line) && line.length < 40) ? line : null);
                    }
                }
            }

            if (price && (depTime || airline)) {
                flights.push({ airline: airline || 'Unknown Airline', departure_time: depTime, arrival_time: arrTime, duration: duration, stops: stops, price: price });
            }
        }

        const seen = new Set();
        return flights.filter(f => {
            const key = (f.departure_time || '') + '_' + f.price;
            if (seen.has(key)) return false;
            seen.add(key);
            return true;
        });
    }
    """

    async def scrape_market(
        self,
        origin: str,
        destination: str,
        date: str,
        market: str,
        proxy_config: Optional[Dict[str, str]] = None,
        timezone: str = "UTC",
        locale: str = "en",
        return_date: Optional[str] = None,
        timeout_ms: int = 45000,
        cdp_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Scrape Google Flights for a single market.

        Args:
            origin: IATA code
            destination: IATA code
            date: YYYY-MM-DD
            market: ISO country code
            proxy_config: {server, username, password} from Proxy neuron
            timezone: Timezone string for browser fingerprint
            locale: Locale for browser fingerprint
            return_date: Optional return date
            timeout_ms: Page load timeout
            cdp_url: Scraping Browser CDP URL (if using Bright Data SB)

        Returns:
            {success, market, currency, flights[], error}
        """
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            return {
                "success": False,
                "market": market,
                "error": "Playwright not installed",
                "flights": [],
            }

        config = GOOGLE_FLIGHTS_MARKETS.get(market, GOOGLE_FLIGHTS_MARKETS["US"])
        url = build_flights_url(origin, destination, date, market, return_date)

        result = {
            "success": False,
            "market": market,
            "currency": config["currency"],
            "flights": [],
            "error": None,
            "proxy_used": bool(proxy_config) or bool(cdp_url),
        }

        async with async_playwright() as p:
            try:
                if cdp_url:
                    # Connect to Bright Data Scraping Browser via CDP
                    browser = await p.chromium.connect_over_cdp(cdp_url)
                    context = browser.contexts[0] if browser.contexts else await browser.new_context(
                        viewport={"width": 1920, "height": 1080},
                        locale=locale,
                        timezone_id=timezone,
                    )
                else:
                    # Standard Playwright with proxy
                    launch_args = {
                        "headless": True,
                        "args": [
                            "--disable-blink-features=AutomationControlled",
                            "--disable-dev-shm-usage",
                            "--no-sandbox",
                        ],
                    }
                    if proxy_config and proxy_config.get("server"):
                        launch_args["proxy"] = {
                            "server": proxy_config["server"],
                            "username": proxy_config.get("username", ""),
                            "password": proxy_config.get("password", ""),
                        }

                    browser = await p.chromium.launch(**launch_args)
                    context = await browser.new_context(
                        viewport={"width": 1920, "height": 1080},
                        user_agent=(
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/121.0.0.0 Safari/537.36"
                        ),
                        locale=locale,
                        timezone_id=timezone,
                    )

                page = await context.new_page()

                # Navigate
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                except Exception:
                    await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms + 15000)

                await page.wait_for_timeout(2000)

                # Handle EU consent dialog
                for selector in CONSENT_SELECTORS:
                    try:
                        btn = page.locator(selector).first
                        if await btn.count() > 0:
                            await btn.click()
                            await page.wait_for_timeout(3000)
                            break
                    except Exception:
                        pass

                # Wait for results
                await page.wait_for_timeout(5000)

                # Extract flights via DOM
                raw_flights = await page.evaluate(self.EXTRACT_FLIGHTS_JS)

                # Filter and normalize
                flights = self._normalize_flights(raw_flights, market, config["currency"])
                result["success"] = True
                result["flights"] = flights

                await browser.close()

            except Exception as e:
                result["error"] = str(e)
                logger.warning("[%s] Google Flights scrape failed: %s", market, e)

        return result

    async def scrape_multiple_markets(
        self,
        origin: str,
        destination: str,
        date: str,
        markets: List[str],
        proxy_configs: Optional[Dict[str, Dict]] = None,
        max_concurrent: int = 3,
        return_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Scrape Google Flights from multiple markets in parallel.

        Args:
            origin: IATA code
            destination: IATA code
            date: YYYY-MM-DD
            markets: List of market codes
            proxy_configs: {market: proxy_config_dict}
            max_concurrent: Max parallel scrapes
            return_date: Optional return date

        Returns:
            {
                origin, destination, date, markets_checked,
                all_results: {market: result},
                cheapest_market, cheapest_price_usd,
                price_comparison: [{market, price_usd, ...}],
            }
        """
        semaphore = asyncio.Semaphore(max_concurrent)

        async def scrape_with_limit(market):
            async with semaphore:
                proxy = (proxy_configs or {}).get(market)
                tz_map = {m: GOOGLE_FLIGHTS_MARKETS.get(m, {}).get("hl", "en") for m in markets}
                return await self.scrape_market(
                    origin, destination, date, market,
                    proxy_config=proxy,
                    locale=tz_map.get(market, "en"),
                    return_date=return_date,
                )

        tasks = [scrape_with_limit(m) for m in markets]
        market_results = await asyncio.gather(*tasks, return_exceptions=True)

        combined = {
            "origin": origin,
            "destination": destination,
            "date": date,
            "return_date": return_date,
            "markets_checked": [],
            "all_results": {},
            "cheapest_market": None,
            "cheapest_price_usd": None,
            "price_comparison": [],
        }

        for market, mresult in zip(markets, market_results):
            if isinstance(mresult, Exception):
                combined["all_results"][market] = {
                    "error": str(mresult), "flights": [],
                }
            else:
                combined["all_results"][market] = mresult
                if mresult.get("success"):
                    combined["markets_checked"].append(market)

        # Build price comparison in USD
        for market, data in combined["all_results"].items():
            for flight in data.get("flights", []):
                currency = data.get("currency", "USD")
                rate = CURRENCY_RATES_TO_USD.get(currency, 1.0)
                price_usd = flight["price"] * rate
                combined["price_comparison"].append({
                    "market": market,
                    "local_price": flight["price"],
                    "currency": currency,
                    "price_usd": round(price_usd, 2),
                    "airline": flight.get("airline", "Unknown"),
                })

        combined["price_comparison"].sort(key=lambda x: x["price_usd"])
        if combined["price_comparison"]:
            cheapest = combined["price_comparison"][0]
            combined["cheapest_market"] = cheapest["market"]
            combined["cheapest_price_usd"] = cheapest["price_usd"]

        return combined

    def _normalize_flights(
        self, raw: List[Dict], market: str, currency: str
    ) -> List[Dict]:
        """Normalize and filter extracted flight data."""
        min_price, max_price = 30, 50000
        if currency == "JPY":
            min_price, max_price = 3000, 500000
        elif currency == "KRW":
            min_price, max_price = 30000, 5000000
        elif currency in ("INR", "THB"):
            min_price, max_price = 500, 200000

        flights = []
        for f in raw[:15]:
            price = f.get("price", 0)
            if min_price < price < max_price:
                flights.append({
                    "airline": f.get("airline", "Unknown Airline"),
                    "price": float(price),
                    "currency": currency,
                    "stops": f.get("stops"),
                    "duration": f.get("duration"),
                    "departure_time": f.get("departure_time"),
                    "arrival_time": f.get("arrival_time"),
                    "market": market,
                })

        flights.sort(key=lambda x: x["price"])
        return flights


__all__ = [
    "GoogleFlightsScraper",
    "GOOGLE_FLIGHTS_MARKETS",
    "CURRENCY_RATES_TO_USD",
    "build_flights_url",
]
