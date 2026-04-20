"""
Google Hotels Scraper — Proxy-routed Google Hotels search via Playwright.

Scrapes Google Hotels results through residential proxy for POS-based
hotel pricing. Extends the POS arbitrage model to hotels — same approach
as flights (foreign IP = foreign POS = potentially lower prices).

Google Hotels URL pattern:
    https://www.google.com/travel/hotels?q=Hotels+in+Barcelona&dates=2026-04-20,2026-04-25

MYSTES KYRIOS LLC — Confidential.
"""

import asyncio
import logging
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

from .flights import CONSENT_SELECTORS, CURRENCY_RATES_TO_USD, GOOGLE_FLIGHTS_MARKETS

logger = logging.getLogger(__name__)


def build_hotels_url(
    destination: str,
    check_in: str,
    check_out: str,
    market: str,
    guests: int = 2,
) -> str:
    """Build Google Hotels URL for a specific market.

    Args:
        destination: City or area name (e.g., "Barcelona")
        check_in: Check-in date YYYY-MM-DD
        check_out: Check-out date YYYY-MM-DD
        market: ISO country code
        guests: Number of guests
    """
    config = GOOGLE_FLIGHTS_MARKETS.get(market, GOOGLE_FLIGHTS_MARKETS["US"])
    params = {
        "q": f"Hotels in {destination}",
        "dates": f"{check_in},{check_out}",
        "hl": config["hl"],
        "gl": config["gl"],
        "curr": config["currency"],
    }
    return f"https://www.{config['domain']}/travel/hotels?{urlencode(params)}"


class GoogleHotelsScraper:
    """
    Scrapes Google Hotels via Playwright + residential proxy.

    Returns structured hotel data: name, price, rating, amenities.
    """

    # DOM extraction JavaScript for Google Hotels
    EXTRACT_HOTELS_JS = """
    () => {
        const hotels = [];
        // Google Hotels renders results as card-like containers
        // Try multiple selectors to find hotel listings
        let cards = document.querySelectorAll('[data-hveid]');
        if (cards.length === 0) cards = document.querySelectorAll('[class*="hotel"]');
        if (cards.length === 0) cards = document.querySelectorAll('div[role="listitem"]');
        if (cards.length === 0) {
            // Fallback: find containers with both a name-like text and a price
            const allDivs = document.querySelectorAll('div');
            const priceRe = /[$€£¥₹₩฿]\\s*[\\d,.]+|[\\d,.]+\\s*[$€£¥₹₩฿]/;
            cards = Array.from(allDivs).filter(d => {
                const t = d.innerText || '';
                return priceRe.test(t) && t.length < 500 && t.length > 20;
            });
        }

        for (const card of cards) {
            const text = card.innerText || '';
            const lines = text.split('\\n').map(l => l.trim()).filter(Boolean);
            if (lines.length < 2) continue;

            let name = null, price = null, rating = null, stars = null;
            let reviewCount = null, amenities = [];

            for (const line of lines) {
                // Price extraction
                let priceMatch = line.match(/[$€£¥₹₩฿]\\s*([\\d,.\\s]+)/) ||
                                 line.match(/([\\d,.\\s]+)\\s*[$€£¥₹₩฿]/) ||
                                 line.match(/([\\d,.]+)\\s*(?:zł|kr|MX\\$|R\\$|C\\$|A\\$|DKK|NOK|CHF)/);
                if (priceMatch && !price) {
                    let raw = (priceMatch[1] || priceMatch[0]).replace(/[^0-9.,]/g, '');
                    if (raw.includes('.') && raw.includes(',')) raw = raw.replace('.', '').replace(',', '.');
                    else raw = raw.replace(',', '');
                    let p = parseFloat(raw);
                    if (p > 10 && p < 100000) price = p;
                    continue;
                }

                // Rating (e.g., "4.5", "4.5/5", "4,5 out of 5")
                let ratingMatch = line.match(/(\\d[.,]\\d)\\s*(?:\\/5|out of 5|von 5|sur 5|su 5|de 5)?/);
                if (ratingMatch && !rating) {
                    let r = parseFloat(ratingMatch[1].replace(',', '.'));
                    if (r >= 1.0 && r <= 5.0) { rating = r; continue; }
                }

                // Star rating (e.g., "4-star hotel", "★★★★")
                let starMatch = line.match(/(\\d)[-\\s]*(?:star|étoile|Sterne|stelle|estrella|stjärnor)/i);
                if (starMatch && !stars) { stars = parseInt(starMatch[1]); continue; }
                let starSymbols = (line.match(/★/g) || []).length;
                if (starSymbols >= 1 && starSymbols <= 5 && !stars) { stars = starSymbols; continue; }

                // Review count (e.g., "(1,234 reviews)", "(1.234 Bewertungen)")
                let reviewMatch = line.match(/\\(([\\d,.]+)\\s*(?:review|reseñ|Bewertung|avis|recension|anmeld)/i);
                if (reviewMatch && !reviewCount) {
                    reviewCount = parseInt(reviewMatch[1].replace(/[.,]/g, ''));
                    continue;
                }

                // Amenities (common keywords)
                const amenityKeywords = /(?:free )?wi-?fi|pool|breakfast|parking|gym|spa|restaurant|air conditioning|kitchen|balcony|pet.friendly/i;
                if (amenityKeywords.test(line)) {
                    amenities.push(line);
                    continue;
                }

                // Hotel name: first substantial text line that isn't a price/rating/amenity
                if (!name && line.length > 3 && line.length < 80 &&
                    /[A-Za-zÀ-ÿ]/.test(line) && !line.match(/[$€£¥₹₩฿]/) &&
                    !/^\\d[.,]\\d/.test(line) && !amenityKeywords.test(line)) {
                    name = line;
                }
            }

            if (name && price) {
                hotels.push({
                    name: name,
                    price: price,
                    rating: rating,
                    stars: stars,
                    review_count: reviewCount,
                    amenities: amenities.slice(0, 5),
                });
            }
        }

        // Deduplicate by name
        const seen = new Set();
        return hotels.filter(h => {
            if (seen.has(h.name)) return false;
            seen.add(h.name);
            return true;
        });
    }
    """

    async def scrape_market(
        self,
        destination: str,
        check_in: str,
        check_out: str,
        market: str,
        proxy_config: Optional[Dict[str, str]] = None,
        timezone: str = "UTC",
        locale: str = "en",
        guests: int = 2,
        timeout_ms: int = 45000,
        cdp_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Scrape Google Hotels for a single market.

        Args:
            destination: City/area name
            check_in: YYYY-MM-DD
            check_out: YYYY-MM-DD
            market: ISO country code
            proxy_config: From Proxy neuron
            timezone: Browser timezone
            locale: Browser locale
            guests: Number of guests
            timeout_ms: Page load timeout
            cdp_url: Scraping Browser CDP URL

        Returns:
            {success, market, currency, hotels[], error}
        """
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            return {
                "success": False,
                "market": market,
                "error": "Playwright not installed",
                "hotels": [],
            }

        config = GOOGLE_FLIGHTS_MARKETS.get(market, GOOGLE_FLIGHTS_MARKETS["US"])
        url = build_hotels_url(destination, check_in, check_out, market, guests)

        result = {
            "success": False,
            "market": market,
            "currency": config["currency"],
            "hotels": [],
            "error": None,
            "proxy_used": bool(proxy_config) or bool(cdp_url),
        }

        async with async_playwright() as p:
            try:
                if cdp_url:
                    browser = await p.chromium.connect_over_cdp(cdp_url)
                    context = browser.contexts[0] if browser.contexts else await browser.new_context(
                        viewport={"width": 1920, "height": 1080},
                        locale=locale,
                        timezone_id=timezone,
                    )
                else:
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

                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                except Exception:
                    await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms + 15000)

                await page.wait_for_timeout(2000)

                # Handle EU consent
                for selector in CONSENT_SELECTORS:
                    try:
                        btn = page.locator(selector).first
                        if await btn.count() > 0:
                            await btn.click()
                            await page.wait_for_timeout(3000)
                            break
                    except Exception:
                        pass

                await page.wait_for_timeout(5000)

                raw_hotels = await page.evaluate(self.EXTRACT_HOTELS_JS)

                hotels = self._normalize_hotels(raw_hotels, market, config["currency"])
                result["success"] = True
                result["hotels"] = hotels

                await browser.close()

            except Exception as e:
                result["error"] = str(e)
                logger.warning("[%s] Google Hotels scrape failed: %s", market, e)

        return result

    async def scrape_multiple_markets(
        self,
        destination: str,
        check_in: str,
        check_out: str,
        markets: List[str],
        proxy_configs: Optional[Dict[str, Dict]] = None,
        max_concurrent: int = 3,
    ) -> Dict[str, Any]:
        """Scrape Google Hotels from multiple markets in parallel."""
        semaphore = asyncio.Semaphore(max_concurrent)

        async def scrape_with_limit(market):
            async with semaphore:
                proxy = (proxy_configs or {}).get(market)
                return await self.scrape_market(
                    destination, check_in, check_out, market,
                    proxy_config=proxy,
                )

        tasks = [scrape_with_limit(m) for m in markets]
        market_results = await asyncio.gather(*tasks, return_exceptions=True)

        combined = {
            "destination": destination,
            "check_in": check_in,
            "check_out": check_out,
            "markets_checked": [],
            "all_results": {},
            "cheapest_market": None,
            "cheapest_price_usd": None,
            "price_comparison": [],
        }

        for market, mresult in zip(markets, market_results):
            if isinstance(mresult, Exception):
                combined["all_results"][market] = {"error": str(mresult), "hotels": []}
            else:
                combined["all_results"][market] = mresult
                if mresult.get("success"):
                    combined["markets_checked"].append(market)

        for market, data in combined["all_results"].items():
            for hotel in data.get("hotels", []):
                currency = data.get("currency", "USD")
                rate = CURRENCY_RATES_TO_USD.get(currency, 1.0)
                combined["price_comparison"].append({
                    "market": market,
                    "name": hotel.get("name", "Unknown"),
                    "local_price": hotel["price"],
                    "currency": currency,
                    "price_usd": round(hotel["price"] * rate, 2),
                    "rating": hotel.get("rating"),
                    "stars": hotel.get("stars"),
                })

        combined["price_comparison"].sort(key=lambda x: x["price_usd"])
        if combined["price_comparison"]:
            cheapest = combined["price_comparison"][0]
            combined["cheapest_market"] = cheapest["market"]
            combined["cheapest_price_usd"] = cheapest["price_usd"]

        return combined

    def _normalize_hotels(
        self, raw: List[Dict], market: str, currency: str
    ) -> List[Dict]:
        """Normalize and filter hotel data."""
        min_price, max_price = 20, 50000
        if currency == "JPY":
            min_price, max_price = 2000, 500000
        elif currency == "KRW":
            min_price, max_price = 20000, 5000000

        hotels = []
        for h in raw[:20]:
            price = h.get("price", 0)
            if min_price < price < max_price:
                hotels.append({
                    "name": h.get("name", "Unknown Hotel"),
                    "price": float(price),
                    "currency": currency,
                    "rating": h.get("rating"),
                    "stars": h.get("stars"),
                    "review_count": h.get("review_count"),
                    "amenities": h.get("amenities", []),
                    "market": market,
                })

        hotels.sort(key=lambda x: x["price"])
        return hotels


__all__ = ["GoogleHotelsScraper", "build_hotels_url"]
