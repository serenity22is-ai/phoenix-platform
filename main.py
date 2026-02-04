import os
import requests
import json
from datetime import datetime, timedelta
import hashlib

# Proxy manager for regional market access
try:
    from proxy_manager import get_proxy_for_market, is_proxy_configured
    PROXY_MANAGER_AVAILABLE = True
except ImportError:
    PROXY_MANAGER_AVAILABLE = False
    print("Note: proxy_manager not available, using manual proxy config")

# Direct Google Flights scraper (uses residential proxies)
try:
    from google_flights_scraper import scrape_flights_sync, scrape_flights_from_market
    DIRECT_SCRAPER_AVAILABLE = True
except ImportError:
    DIRECT_SCRAPER_AVAILABLE = False
    print("Note: Direct scraper requires playwright. Run: pip install playwright && playwright install chromium")

# Amadeus API client for rich flight details (flight numbers, layovers, aircraft)
try:
    from amadeus_client import AmadeusClient, search_with_amadeus
    AMADEUS_AVAILABLE = True
    _amadeus_client = AmadeusClient()
    AMADEUS_CONFIGURED = _amadeus_client.is_configured()
except ImportError:
    AMADEUS_AVAILABLE = False
    AMADEUS_CONFIGURED = False
    print("Note: Amadeus client not available")

# Scraping mode: "hybrid" (default, Amadeus + proxies), "direct" (proxies only)
SCRAPING_MODE = os.getenv("SCRAPING_MODE", "hybrid")

# XRPL imports - install with: pip install xrpl-py
try:
    from xrpl.clients import JsonRpcClient
    from xrpl.models import Payment, Memo
    from xrpl.wallet import Wallet
    from xrpl.transaction import submit_and_wait
    from xrpl.utils import xrp_to_drops, drops_to_xrp
    from xrpl.models.requests import AccountTx, Tx
    XRPL_AVAILABLE = True
except ImportError:
    XRPL_AVAILABLE = False
    print("WARNING: xrpl-py not installed. Run: pip install xrpl-py")

# --- CONFIGURATION ---
# Default search settings (can be overridden per search)
ORIGIN = "LAX"
DESTINATIONS = ["HND", "NRT"]
START_DATE = "2026-02-15"
END_DATE = "2026-03-01"

# User's preferred display currency - all prices will be converted to this
DISPLAY_CURRENCY = "USD"  # Options: "USD", "JPY", "EUR", "GBP", etc.

# --- ROUTE TYPES ---
# Domestic routes - popular US city pairs
DOMESTIC_ROUTES = [
    {"origin": "LAX", "destinations": ["JFK", "ORD", "SFO", "MIA", "DFW", "SEA", "BOS", "DEN"]},
    {"origin": "JFK", "destinations": ["LAX", "SFO", "MIA", "ORD", "DFW", "SEA", "LAS", "ATL"]},
    {"origin": "SFO", "destinations": ["LAX", "JFK", "SEA", "ORD", "DEN", "BOS", "MIA", "DFW"]},
    {"origin": "ORD", "destinations": ["LAX", "JFK", "SFO", "MIA", "DFW", "DEN", "ATL", "SEA"]},
    {"origin": "MIA", "destinations": ["LAX", "JFK", "ORD", "ATL", "DFW", "DEN", "SEA", "BOS"]},
]

# International routes - US to major international destinations
INTERNATIONAL_ROUTES = [
    {"origin": "LAX", "destinations": ["HND", "NRT", "LHR", "CDG", "FRA", "ICN", "SIN", "SYD"]},
    {"origin": "JFK", "destinations": ["LHR", "CDG", "FRA", "HND", "NRT", "FCO", "BCN", "DUB"]},
    {"origin": "SFO", "destinations": ["HND", "NRT", "ICN", "SIN", "SYD", "TPE", "HKG", "PVG"]},
    {"origin": "ORD", "destinations": ["LHR", "CDG", "FRA", "HND", "NRT", "ICN", "DUB", "MUC"]},
]

# --- PLATFORM FEE CONFIGURATION ---
# Your platform takes a percentage of the savings as a service fee
PLATFORM_FEE_CONFIG = {
    "savings_cut_pct": 25.0,         # Platform takes 25% of the user's savings
    "min_fee_usd": 3.00,             # Minimum fee charged
    "max_fee_usd": 50.00,            # Cap on fees
}

# Minimum savings to show a deal (after platform fee)
MIN_USER_SAVINGS_USD = 10.00

# --- XRPL CONFIGURATION ---
XRPL_CONFIG = {
    # Use testnet for development, mainnet for production
    "network": "testnet",  # "testnet" or "mainnet"
    "testnet_url": "https://s.altnet.rippletest.net:51234",
    "mainnet_url": "https://xrplcluster.com",

    # Your platform's receiving wallet address
    # TESTNET wallet (funded from faucet)
    "platform_wallet_address": "rBYk2nioyZGDndMqDSp2eMD22ZD9bNwM1d",

    # XRP/USD rate - will be fetched live by get_xrp_price()
    "xrp_usd_rate": 0.50,  # Fallback rate if API fails
}


def get_xrp_price():
    """
    Fetch live XRP/USD price from CoinGecko API (free, no auth required).
    Updates XRPL_CONFIG with the current rate.

    Returns:
        float: Current XRP price in USD
    """
    try:
        response = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": "ripple", "vs_currencies": "usd"},
            timeout=10
        )
        if response.status_code == 200:
            data = response.json()
            price = data.get("ripple", {}).get("usd")
            if price:
                XRPL_CONFIG["xrp_usd_rate"] = price
                print(f"Live XRP price: ${price} USD")
                return price
    except Exception as e:
        print(f"Warning: Could not fetch live XRP price: {e}")

    # Return fallback rate
    print(f"Using fallback XRP rate: ${XRPL_CONFIG['xrp_usd_rate']} USD")
    return XRPL_CONFIG["xrp_usd_rate"]


# --- AIRLINE BOOKING URLS ---
# Regional booking URLs for direct airline access
AIRLINE_BOOKING_URLS = {
    # Japanese Airlines
    "JAL": {
        "US": "https://www.jal.co.jp/en/",
        "JP": "https://www.jal.co.jp/jp/ja/",
        "UK": "https://www.jal.co.jp/en/",
    },
    "ANA": {
        "US": "https://www.ana.co.jp/en/us/",
        "JP": "https://www.ana.co.jp/ja/jp/",
        "UK": "https://www.ana.co.jp/en/gb/",
    },
    # US Airlines
    "United": {
        "US": "https://www.united.com/en/us",
        "UK": "https://www.united.com/en/gb",
        "JP": "https://www.united.com/ja/jp",
        "DE": "https://www.united.com/de/de",
    },
    "American": {
        "US": "https://www.aa.com/homePage.do?locale=en_US",
        "UK": "https://www.aa.com/homePage.do?locale=en_GB",
        "JP": "https://www.aa.com/homePage.do?locale=ja_JP",
        "DE": "https://www.aa.com/homePage.do?locale=de_DE",
    },
    "Delta": {
        "US": "https://www.delta.com/us/en",
        "UK": "https://www.delta.com/gb/en",
        "JP": "https://www.delta.com/jp/ja",
        "DE": "https://www.delta.com/de/de",
    },
    "Southwest": {
        "US": "https://www.southwest.com/",
    },
    "JetBlue": {
        "US": "https://www.jetblue.com/",
    },
    "Alaska": {
        "US": "https://www.alaskaair.com/",
    },
    # European Airlines
    "British Airways": {
        "US": "https://www.britishairways.com/travel/home/public/en_us",
        "UK": "https://www.britishairways.com/travel/home/public/en_gb",
        "DE": "https://www.britishairways.com/travel/home/public/de_de",
    },
    "Lufthansa": {
        "US": "https://www.lufthansa.com/us/en",
        "UK": "https://www.lufthansa.com/gb/en",
        "DE": "https://www.lufthansa.com/de/de",
    },
    "Air France": {
        "US": "https://www.airfrance.us/",
        "UK": "https://www.airfrance.co.uk/",
        "FR": "https://www.airfrance.fr/",
    },
    "KLM": {
        "US": "https://www.klm.us/",
        "UK": "https://www.klm.co.uk/",
        "NL": "https://www.klm.nl/",
    },
    # Asian Airlines
    "Singapore Airlines": {
        "US": "https://www.singaporeair.com/en_US/",
        "UK": "https://www.singaporeair.com/en_UK/",
        "SG": "https://www.singaporeair.com/en_SG/",
    },
    "Cathay Pacific": {
        "US": "https://www.cathaypacific.com/cx/en_US.html",
        "UK": "https://www.cathaypacific.com/cx/en_GB.html",
        "HK": "https://www.cathaypacific.com/cx/en_HK.html",
    },
    "Korean Air": {
        "US": "https://www.koreanair.com/us/en",
        "KR": "https://www.koreanair.com/kr/ko",
    },
    "Qantas": {
        "US": "https://www.qantas.com/us/en.html",
        "UK": "https://www.qantas.com/gb/en.html",
        "AU": "https://www.qantas.com/au/en.html",
    },
    # Default fallback
    "default": {
        "US": "https://www.google.com/travel/flights",
        "UK": "https://www.google.com/travel/flights?hl=en&gl=uk",
        "JP": "https://www.google.com/travel/flights?hl=ja&gl=jp",
        "DE": "https://www.google.com/travel/flights?hl=de&gl=de",
        "FR": "https://www.google.com/travel/flights?hl=fr&gl=fr",
        "CA": "https://www.google.com/travel/flights?hl=en&gl=ca",
        "AU": "https://www.google.com/travel/flights?hl=en&gl=au",
        "IN": "https://www.google.com/travel/flights?hl=en&gl=in",
    }
}


def fetch_live_currency_rates():
    """
    Fetch live currency rates from free API.
    Updates CURRENCY_RATES_TO_USD with current rates.
    """
    try:
        # Using exchangerate-api.com (free tier)
        response = requests.get(
            "https://api.exchangerate-api.com/v4/latest/USD",
            timeout=10
        )
        if response.status_code == 200:
            data = response.json()
            rates = data.get("rates", {})
            for currency, rate in rates.items():
                if currency in CURRENCY_RATES_TO_USD:
                    # Rate from API is USD->Currency, we need Currency->USD
                    CURRENCY_RATES_TO_USD[currency] = 1.0 / rate
            print(f"Updated {len(rates)} currency rates")
            return True
    except Exception as e:
        print(f"Warning: Could not fetch live currency rates: {e}")
    return False

# Proxy configuration - uses Webshare.io proxy manager or manual URLs
# Set WEBSHARE_USERNAME and WEBSHARE_PASSWORD in .env for auto country targeting
# Or set individual XX_PROXY_URL for manual configuration

def get_proxy_for_request(market_label: str):
    """
    Get proxy configuration for a market request.

    Uses proxy_manager (Webshare.io) if configured, otherwise falls back
    to manual XX_PROXY_URL environment variables.

    Returns:
        dict with 'http' and 'https' keys, or None
    """
    # Try proxy manager first (Webshare.io integration)
    if PROXY_MANAGER_AVAILABLE:
        proxy = get_proxy_for_market(market_label)
        if proxy:
            return proxy

    # Fallback to manual proxy URLs
    manual_url = os.getenv(f"{market_label}_PROXY_URL")
    if manual_url:
        return {"http": manual_url, "https": manual_url}

    return None

# --- EXPANDED MARKET CONFIGURATIONS ---
# Each market represents a different regional pricing zone
# More markets = more chances to find price discrepancies

MARKETS = [
    # North America
    {"label": "US", "currency": "USD", "gl": "us", "hl": "en", "region": "NA"},
    {"label": "CA", "currency": "CAD", "gl": "ca", "hl": "en", "region": "NA"},
    {"label": "MX", "currency": "MXN", "gl": "mx", "hl": "es", "region": "NA"},

    # Europe - Western
    {"label": "UK", "currency": "GBP", "gl": "uk", "hl": "en", "region": "EU"},
    {"label": "DE", "currency": "EUR", "gl": "de", "hl": "de", "region": "EU"},
    {"label": "FR", "currency": "EUR", "gl": "fr", "hl": "fr", "region": "EU"},
    {"label": "IT", "currency": "EUR", "gl": "it", "hl": "it", "region": "EU"},
    {"label": "ES", "currency": "EUR", "gl": "es", "hl": "es", "region": "EU"},
    {"label": "NL", "currency": "EUR", "gl": "nl", "hl": "nl", "region": "EU"},
    {"label": "IE", "currency": "EUR", "gl": "ie", "hl": "en", "region": "EU"},
    {"label": "PT", "currency": "EUR", "gl": "pt", "hl": "pt", "region": "EU"},
    {"label": "BE", "currency": "EUR", "gl": "be", "hl": "fr", "region": "EU"},
    {"label": "AT", "currency": "EUR", "gl": "at", "hl": "de", "region": "EU"},
    {"label": "CH", "currency": "CHF", "gl": "ch", "hl": "de", "region": "EU"},
    {"label": "GR", "currency": "EUR", "gl": "gr", "hl": "el", "region": "EU"},

    # Europe - Scandinavia
    {"label": "SE", "currency": "SEK", "gl": "se", "hl": "sv", "region": "EU"},
    {"label": "NO", "currency": "NOK", "gl": "no", "hl": "no", "region": "EU"},
    {"label": "DK", "currency": "DKK", "gl": "dk", "hl": "da", "region": "EU"},
    {"label": "FI", "currency": "EUR", "gl": "fi", "hl": "fi", "region": "EU"},

    # Europe - Eastern
    {"label": "PL", "currency": "PLN", "gl": "pl", "hl": "pl", "region": "EU"},
    {"label": "CZ", "currency": "CZK", "gl": "cz", "hl": "cs", "region": "EU"},
    {"label": "HU", "currency": "HUF", "gl": "hu", "hl": "hu", "region": "EU"},
    {"label": "TR", "currency": "TRY", "gl": "tr", "hl": "tr", "region": "EU"},

    # Asia Pacific
    {"label": "JP", "currency": "JPY", "gl": "jp", "hl": "ja", "region": "APAC"},
    {"label": "KR", "currency": "KRW", "gl": "kr", "hl": "ko", "region": "APAC"},
    {"label": "AU", "currency": "AUD", "gl": "au", "hl": "en", "region": "APAC"},
    {"label": "NZ", "currency": "NZD", "gl": "nz", "hl": "en", "region": "APAC"},
    {"label": "SG", "currency": "SGD", "gl": "sg", "hl": "en", "region": "APAC"},
    {"label": "HK", "currency": "HKD", "gl": "hk", "hl": "en", "region": "APAC"},
    {"label": "TW", "currency": "TWD", "gl": "tw", "hl": "zh-TW", "region": "APAC"},
    {"label": "IN", "currency": "INR", "gl": "in", "hl": "en", "region": "APAC"},
    {"label": "TH", "currency": "THB", "gl": "th", "hl": "th", "region": "APAC"},
    {"label": "MY", "currency": "MYR", "gl": "my", "hl": "en", "region": "APAC"},
    {"label": "PH", "currency": "PHP", "gl": "ph", "hl": "en", "region": "APAC"},
    {"label": "ID", "currency": "IDR", "gl": "id", "hl": "id", "region": "APAC"},
    {"label": "VN", "currency": "VND", "gl": "vn", "hl": "vi", "region": "APAC"},

    # South America
    {"label": "BR", "currency": "BRL", "gl": "br", "hl": "pt", "region": "SA"},
    {"label": "AR", "currency": "ARS", "gl": "ar", "hl": "es", "region": "SA"},
    {"label": "CL", "currency": "CLP", "gl": "cl", "hl": "es", "region": "SA"},
    {"label": "CO", "currency": "COP", "gl": "co", "hl": "es", "region": "SA"},

    # Middle East / Africa
    {"label": "AE", "currency": "AED", "gl": "ae", "hl": "en", "region": "ME"},
    {"label": "SA", "currency": "SAR", "gl": "sa", "hl": "ar", "region": "ME"},
    {"label": "IL", "currency": "ILS", "gl": "il", "hl": "en", "region": "ME"},
    {"label": "ZA", "currency": "ZAR", "gl": "za", "hl": "en", "region": "AF"},
    {"label": "EG", "currency": "EGP", "gl": "eg", "hl": "ar", "region": "AF"},
]

# Subset of markets for faster searches (best arbitrage opportunities)
PRIORITY_MARKETS = [
    # North America
    {"label": "US", "currency": "USD", "gl": "us", "hl": "en", "region": "NA"},
    {"label": "CA", "currency": "CAD", "gl": "ca", "hl": "en", "region": "NA"},
    {"label": "MX", "currency": "MXN", "gl": "mx", "hl": "es", "region": "NA"},
    # Europe - Major markets with different pricing
    {"label": "UK", "currency": "GBP", "gl": "uk", "hl": "en", "region": "EU"},
    {"label": "DE", "currency": "EUR", "gl": "de", "hl": "de", "region": "EU"},
    {"label": "FR", "currency": "EUR", "gl": "fr", "hl": "fr", "region": "EU"},
    {"label": "ES", "currency": "EUR", "gl": "es", "hl": "es", "region": "EU"},
    {"label": "IT", "currency": "EUR", "gl": "it", "hl": "it", "region": "EU"},
    {"label": "NL", "currency": "EUR", "gl": "nl", "hl": "nl", "region": "EU"},
    {"label": "SE", "currency": "SEK", "gl": "se", "hl": "sv", "region": "EU"},
    {"label": "NO", "currency": "NOK", "gl": "no", "hl": "no", "region": "EU"},
    {"label": "CH", "currency": "CHF", "gl": "ch", "hl": "de", "region": "EU"},
    {"label": "PL", "currency": "PLN", "gl": "pl", "hl": "pl", "region": "EU"},
    {"label": "TR", "currency": "TRY", "gl": "tr", "hl": "tr", "region": "EU"},
    # Asia Pacific
    {"label": "JP", "currency": "JPY", "gl": "jp", "hl": "ja", "region": "APAC"},
    {"label": "KR", "currency": "KRW", "gl": "kr", "hl": "ko", "region": "APAC"},
    {"label": "AU", "currency": "AUD", "gl": "au", "hl": "en", "region": "APAC"},
    {"label": "SG", "currency": "SGD", "gl": "sg", "hl": "en", "region": "APAC"},
    {"label": "IN", "currency": "INR", "gl": "in", "hl": "en", "region": "APAC"},
    {"label": "HK", "currency": "HKD", "gl": "hk", "hl": "en", "region": "APAC"},
    {"label": "TH", "currency": "THB", "gl": "th", "hl": "th", "region": "APAC"},
    # South America
    {"label": "BR", "currency": "BRL", "gl": "br", "hl": "pt", "region": "SA"},
    {"label": "CO", "currency": "COP", "gl": "co", "hl": "es", "region": "SA"},
    # Middle East
    {"label": "AE", "currency": "AED", "gl": "ae", "hl": "en", "region": "ME"},
    {"label": "SA", "currency": "SAR", "gl": "sa", "hl": "ar", "region": "ME"},
]

# User agents for different device types (prices sometimes vary by device)
USER_AGENTS = {
    "desktop": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "mobile": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
    "android": "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
}

# Demo mode flag - set to True to use sample data instead of API
DEMO_MODE = False

# Sample airlines for demo data
DEMO_AIRLINES = {
    "US": [
        {"airline": "American Airlines", "code": "AA", "base_price": 380},
        {"airline": "United Airlines", "code": "UA", "base_price": 395},
        {"airline": "Delta Air Lines", "code": "DL", "base_price": 410},
        {"airline": "JetBlue", "code": "B6", "base_price": 350},
    ],
    "EU": [
        {"airline": "British Airways", "code": "BA", "base_price": 420},
        {"airline": "Lufthansa", "code": "LH", "base_price": 390},
        {"airline": "Air France", "code": "AF", "base_price": 385},
        {"airline": "LEVEL", "code": "LL", "base_price": 320},
        {"airline": "Norwegian", "code": "DY", "base_price": 290},
    ],
    "ASIA": [
        {"airline": "Japan Airlines", "code": "JL", "base_price": 850},
        {"airline": "ANA", "code": "NH", "base_price": 870},
        {"airline": "Singapore Airlines", "code": "SQ", "base_price": 920},
        {"airline": "Cathay Pacific", "code": "CX", "base_price": 780},
    ],
}

def generate_demo_flights(departure, arrival, outbound_date, market, search_options=None):
    """
    Generate demo flight data when API is unavailable.
    Creates realistic-looking flight options with regional pricing variations.
    """
    import random

    # Determine region for airline selection
    market_label = market.get("label", "US")
    currency = market.get("currency", "USD")

    # Select airlines based on route
    if market_label in ["UK", "DE", "FR", "ES", "IT", "NL"]:
        airlines = DEMO_AIRLINES["EU"]
        price_modifier = 0.85 + random.uniform(-0.05, 0.1)  # EU often cheaper
    elif market_label in ["JP", "KR", "SG", "AU", "IN", "HK"]:
        airlines = DEMO_AIRLINES["ASIA"]
        price_modifier = 0.9 + random.uniform(-0.05, 0.15)
    else:
        airlines = DEMO_AIRLINES["US"]
        price_modifier = 1.0 + random.uniform(-0.02, 0.08)  # US baseline

    # Currency conversion factors (approximate)
    currency_factors = {
        "USD": 1.0, "EUR": 0.92, "GBP": 0.79, "JPY": 150.0, "AUD": 1.55,
        "CAD": 1.36, "INR": 83.0, "KRW": 1320.0, "SGD": 1.34, "MXN": 17.2,
        "BRL": 4.95, "CHF": 0.88, "HKD": 7.82, "NZD": 1.62
    }

    factor = currency_factors.get(currency, 1.0)

    # Generate flight results
    flights = []
    flight_times = [
        ("06:30", "14:45", "11h 15m"),
        ("08:15", "16:30", "11h 15m"),
        ("10:00", "20:15", "13h 15m"),
        ("14:30", "22:45", "11h 15m"),
        ("17:00", "01:30+1", "11h 30m"),
        ("21:45", "08:00+1", "13h 15m"),
    ]

    for i, airline_info in enumerate(random.sample(airlines, min(4, len(airlines)))):
        base = airline_info["base_price"]
        # Apply market modifier and add randomness
        price_usd = base * price_modifier * (1 + random.uniform(-0.1, 0.1))
        local_price = round(price_usd * factor)

        times = flight_times[i % len(flight_times)]
        stops = random.choice([0, 0, 0, 1, 1, 2])  # Favor nonstop

        flights.append({
            "flights": [{
                "airline": airline_info["airline"],
                "flight_number": f"{airline_info['code']} {random.randint(100, 9999)}",
                "departure": {"time": times[0]},
                "arrival": {"time": times[1]},
            }],
            "price": local_price,
            "duration": times[2],
            "stops": stops,
            "type": "Round trip" if search_options and search_options.get("trip_type") == "round_trip" else "One way",
        })

    return {
        "best_flights": flights[:2] if flights else [],
        "other_flights": flights[2:] if len(flights) > 2 else [],
        "demo_mode": True,
    }


def fetch_flights_direct(departure, arrival, outbound_date, market, search_options=None):
    """
    Fetch flights using direct Google Flights scraping with residential proxies.

    This bypasses SerpAPI and gets REAL regional pricing by routing through
    country-specific proxies. Requires playwright to be installed.

    Returns data in the same format as SerpAPI for compatibility.
    """
    if not DIRECT_SCRAPER_AVAILABLE:
        print(f"  -> Direct scraper not available, falling back to demo mode")
        return generate_demo_flights(departure, arrival, outbound_date, market, search_options)

    import asyncio
    from google_flights_scraper import scrape_flights_from_market

    market_code = market.get("label", "US")
    cabin_class = "economy"
    if search_options:
        cabin_class = search_options.get("cabin_class", "economy")

    print(f"  -> Direct scraping {departure} → {arrival} from {market_code}...")

    try:
        # Run the async scraper
        result = asyncio.run(scrape_flights_from_market(
            origin=departure,
            destination=arrival,
            date=outbound_date,
            market=market_code,
            cabin_class=cabin_class
        ))

        if result.get("success") and result.get("flights"):
            # Convert to SerpAPI-compatible format
            flights = []
            for f in result["flights"]:
                flights.append({
                    "flights": [{
                        "airline": f.get("airline", "Unknown"),
                        "flight_number": f"XX {f.get('index', 0) + 100}",
                        "departure": {"time": f.get("departure_time")},
                        "arrival": {"time": f.get("arrival_time")},
                    }],
                    "price": f.get("price"),
                    "duration": f.get("duration"),
                    "stops": f.get("stops", 0),
                    "type": "One way",
                })

            return {
                "best_flights": flights[:3],
                "other_flights": flights[3:],
                "direct_scrape": True,
                "market": market_code,
                "proxy_used": result.get("proxy_used", False)
            }
        else:
            error = result.get("error", "No flights found")
            print(f"  -> Direct scrape failed: {error}")
            return generate_demo_flights(departure, arrival, outbound_date, market, search_options)

    except Exception as e:
        print(f"  -> Direct scrape error: {e}")
        return generate_demo_flights(departure, arrival, outbound_date, market, search_options)


def search_with_direct_scraping(origin, destination, date, markets, cabin_class="economy", return_date=None):
    """
    Search multiple markets using direct Google Flights scraping.

    This is the main entry point for direct scraping across multiple markets.
    Uses residential proxies to get real regional pricing.

    Args:
        origin: Origin airport code (e.g., "LAX")
        destination: Destination airport code (e.g., "BCN")
        date: Flight date (YYYY-MM-DD)
        markets: List of market codes (e.g., ["US", "ES", "UK", "DE"])
        cabin_class: Cabin class (economy, premium_economy, business, first)
        return_date: Return date for round-trip (YYYY-MM-DD), None for one-way

    Returns:
        Dict with price comparison across all markets
    """
    if not DIRECT_SCRAPER_AVAILABLE:
        return {
            "error": "Direct scraper not available. Install playwright: pip install playwright && playwright install chromium",
            "flights": []
        }

    from google_flights_scraper import scrape_flights_sync

    trip_type = "round-trip" if return_date else "one-way"
    print(f"\n{'='*50}")
    print(f"DIRECT SCRAPING ({trip_type.upper()}): {origin} → {destination}")
    print(f"Outbound: {date}")
    if return_date:
        print(f"Return: {return_date}")
    print(f"Markets: {', '.join(markets)}")
    print(f"{'='*50}")

    result = scrape_flights_sync(origin, destination, date, markets, cabin_class, return_date=return_date)

    # Add trip type info
    result["is_round_trip"] = bool(return_date)
    result["return_date"] = return_date

    # Add savings calculation
    if result.get("price_comparison") and len(result["price_comparison"]) > 1:
        cheapest = result["price_comparison"][0]["price_usd"]
        us_price = None
        for item in result["price_comparison"]:
            if item["market"] == "US":
                us_price = item["price_usd"]
                break

        if us_price and cheapest < us_price:
            result["savings_vs_us"] = round(us_price - cheapest, 2)
            result["savings_pct"] = round((us_price - cheapest) / us_price * 100, 1)

    return result


def search_hybrid(origin, destination, date, cabin_class="economy", return_date=None, search_options=None):
    """
    HYBRID SEARCH: Combines proxy scraping (real prices) with SerpAPI (flight details).

    Runs TWO parallel searches:
    1. Proxy scraping → Real regional prices from US, ES, PT markets
    2. SerpAPI → Full flight details (airline, times, stops, duration)

    Then merges them to give users:
    - Accurate price arbitrage data (from proxies)
    - Complete flight information (from SerpAPI)

    Args:
        origin: Origin airport code
        destination: Destination airport code
        date: Outbound date (YYYY-MM-DD)
        cabin_class: Cabin class
        return_date: Return date for round-trip (optional)
        search_options: Additional search options

    Returns:
        Dict with merged flight details + regional prices
    """
    import concurrent.futures

    trip_type = "round-trip" if return_date else "one-way"
    print(f"\n{'='*60}")
    print(f"HYBRID SEARCH ({trip_type.upper()}): {origin} → {destination}")
    print(f"Date: {date}" + (f" returning {return_date}" if return_date else ""))
    print(f"{'='*60}")
    print(f"\nRunning parallel searches:")
    print(f"  1. Proxy scraping → Real regional prices")
    print(f"  2. Amadeus API → Flight details (airline, times, stops, aircraft)")

    proxy_result = None
    amadeus_flights = []

    # Define the search tasks
    def run_proxy_search():
        """Run proxy-based price scraping"""
        if not DIRECT_SCRAPER_AVAILABLE:
            return None
        try:
            from google_flights_scraper import scrape_flights_sync
            markets = ["DE", "ES", "IT", "CA", "NL"]
            return scrape_flights_sync(origin, destination, date, markets, cabin_class, return_date)
        except Exception as e:
            print(f"  [PROXY] Error: {e}")
            return None

    def run_amadeus_search():
        """Run Amadeus API for flight details"""
        if not AMADEUS_AVAILABLE or not AMADEUS_CONFIGURED:
            print(f"  [AMADEUS] Not configured - skipping flight details")
            return []

        try:
            print(f"  [AMADEUS] Fetching flight details...")
            amadeus_result = search_with_amadeus(
                origin=origin,
                destination=destination,
                departure_date=date,
                return_date=return_date,
                cabin_class=cabin_class,
                max_results=20,
            )

            if amadeus_result and amadeus_result.get("flights"):
                flights = amadeus_result["flights"]
                print(f"  [AMADEUS] Found {len(flights)} flights with full details")
                return flights
            else:
                print(f"  [AMADEUS] No flights returned")
                return []
        except Exception as e:
            print(f"  [AMADEUS] Error: {e}")
            return []

    # Run both searches in parallel using ThreadPoolExecutor
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        proxy_future = executor.submit(run_proxy_search)
        amadeus_future = executor.submit(run_amadeus_search)

        # Wait for both to complete
        proxy_result = proxy_future.result()
        amadeus_flights = amadeus_future.result()

    # Merge results
    print(f"\nMerging results...")

    result = {
        "origin": origin,
        "destination": destination,
        "date": date,
        "return_date": return_date,
        "is_round_trip": bool(return_date),
        "flights": [],  # Full flight details from Amadeus
        "price_comparison": [],  # Regional prices from proxies
        "cheapest_market": None,
        "cheapest_price_usd": None,
        "us_price_usd": None,
        "savings_vs_us": 0,
        "savings_pct": 0,
        "data_sources": {
            "prices": "proxy_scraping" if proxy_result else "amadeus",
            "flight_details": "amadeus" if amadeus_flights else "proxy_scraping"
        }
    }

    # Add flight details from Amadeus
    if amadeus_flights:
        result["flights"] = amadeus_flights

    # Add price comparison from proxy scraping
    if proxy_result and proxy_result.get("price_comparison"):
        result["price_comparison"] = proxy_result["price_comparison"]
        result["cheapest_market"] = "Phoenix"  # Never expose proxy market codes
        result["cheapest_price_usd"] = proxy_result.get("cheapest_price_usd")
        result["savings_vs_us"] = proxy_result.get("savings_vs_us", 0)
        result["savings_pct"] = proxy_result.get("savings_pct", 0)

        # Find US price for reference
        for price in proxy_result["price_comparison"]:
            if price["market"] == "US":
                result["us_price_usd"] = price["price_usd"]
                break

        # Include raw proxy flight data per market for per-flight matching
        # This allows search.py to match specific flights to their real prices
        if proxy_result.get("all_results"):
            result["proxy_flights_by_market"] = {}
            for market, market_data in proxy_result["all_results"].items():
                if market_data.get("flights"):
                    result["proxy_flights_by_market"][market] = {
                        "flights": market_data["flights"],
                        "currency": market_data.get("currency", "USD")
                    }

    # If we have both, try to match prices to flights
    if amadeus_flights and proxy_result and proxy_result.get("price_comparison"):
        # Add price arbitrage info to each flight
        cheapest_market = proxy_result.get("cheapest_market", "US")
        cheapest_price = proxy_result.get("cheapest_price_usd", 0)
        us_price = result.get("us_price_usd", 0)

        for flight in result["flights"]:
            # Add regional price info
            flight["regional_prices"] = {
                "us_price": us_price,
                "cheapest_market": "Phoenix",
                "cheapest_price": cheapest_price,
                "savings": round(us_price - cheapest_price, 2) if us_price and cheapest_price else 0
            }

    # Summary
    print(f"\n{'='*60}")
    print(f"HYBRID SEARCH COMPLETE")
    print(f"{'='*60}")
    print(f"  Flights with details: {len(result['flights'])}")
    print(f"  Price comparisons: {len(result['price_comparison'])}")
    if result["savings_vs_us"] > 0:
        print(f"  ARBITRAGE FOUND: Save ${result['savings_vs_us']:.2f} ({result['savings_pct']:.1f}%) via {result['cheapest_market']}")

    return result


def search_proxy_only(origin, destination, date, cabin_class="economy", return_date=None, markets=None):
    """
    PURE PROXY SEARCH: Opens parallel browser windows through proxies to scrape Google Flights.

    NO SerpAPI - all data comes from live proxy scraping:
    - US proxy → google.com/travel/flights (USD prices)
    - ES proxy → google.es/travel/flights (EUR prices)
    - PT proxy → google.pt/travel/flights (EUR prices)

    Each proxy captures full flight details: airline, times, duration, stops, price.
    Results are matched by airline + departure time to show per-flight price comparison.

    Args:
        origin: Origin airport code (e.g., "JFK")
        destination: Destination airport code (e.g., "BCN")
        date: Outbound date (YYYY-MM-DD)
        cabin_class: Cabin class (economy, premium_economy, business, first)
        return_date: Return date for round-trip (optional)
        markets: List of markets to scrape (default: ["US", "ES", "PT"])

    Returns:
        Dict with:
        - proxy_flights_by_market: Raw flight data per market
        - matched_flights: Flights matched across markets with price comparison
        - cheapest_market: Market with lowest overall prices
        - arbitrage_opportunities: Flights with significant price differences
    """
    if markets is None:
        markets = ["DE", "ES", "IT", "CA", "NL"]

    trip_type = "round-trip" if return_date else "one-way"
    print(f"\n{'='*70}")
    print(f"PROXY-ONLY SEARCH ({trip_type.upper()}): {origin} → {destination}")
    print(f"Date: {date}" + (f" returning {return_date}" if return_date else ""))
    print(f"Markets: {', '.join(markets)}")
    print(f"{'='*70}")
    print(f"\nOpening {len(markets)} parallel browser windows through proxies...")

    # Run proxy scraping (this opens parallel Playwright browsers)
    try:
        from google_flights_scraper import scrape_flights_sync
        proxy_result = scrape_flights_sync(origin, destination, date, markets, cabin_class, return_date)
    except Exception as e:
        print(f"  [ERROR] Proxy scraping failed: {e}")
        return {"error": str(e), "flights": [], "proxy_flights_by_market": {}}

    if not proxy_result or not proxy_result.get("all_results"):
        print("  [ERROR] No results from proxy scraping")
        return {"error": "No proxy results", "flights": [], "proxy_flights_by_market": {}}

    # Build result structure
    result = {
        "origin": origin,
        "destination": destination,
        "date": date,
        "return_date": return_date,
        "is_round_trip": bool(return_date),
        "markets_scraped": markets,
        "proxy_flights_by_market": {},
        "price_comparison": proxy_result.get("price_comparison", []),
        "cheapest_market": proxy_result.get("cheapest_market"),
        "cheapest_price_usd": proxy_result.get("cheapest_price_usd"),
        "us_price_usd": None,
        "savings_vs_us": proxy_result.get("savings_vs_us", 0),
        "savings_pct": proxy_result.get("savings_pct", 0),
        "data_source": "proxy_scraping_only",
    }

    # Extract flight data per market
    for market, market_data in proxy_result.get("all_results", {}).items():
        if market_data.get("flights"):
            result["proxy_flights_by_market"][market] = {
                "flights": market_data["flights"],
                "currency": market_data.get("currency", "USD"),
                "flight_count": len(market_data["flights"])
            }
            # Get US price for reference
            if market == "US" and market_data["flights"]:
                cheapest_us = min(f.get("price", 9999) for f in market_data["flights"])
                result["us_price_usd"] = cheapest_us

    # Log results
    print(f"\n[PROXY RESULTS]")
    for market, data in result["proxy_flights_by_market"].items():
        print(f"  {market}: {data['flight_count']} flights scraped ({data['currency']})")

    if result["savings_vs_us"] > 0:
        print(f"\n[ARBITRAGE] Save ${result['savings_vs_us']:.2f} ({result['savings_pct']:.1f}%) via {result['cheapest_market']}")

    return result


def search_amadeus_with_proxy_prices(origin, destination, date, cabin_class="economy", return_date=None, markets=None):
    """
    BEST OF BOTH WORLDS: Amadeus flight details + Proxy price arbitrage.

    This function:
    1. Fetches DETAILED flight info from Amadeus API (flight numbers, layovers, aircraft)
    2. Fetches REAL prices from multiple markets via residential proxies
    3. Matches flights by airline + departure time
    4. Returns complete flight data with per-market price comparison

    Args:
        origin: Origin airport code (e.g., "JFK")
        destination: Destination airport code (e.g., "BCN")
        date: Outbound date (YYYY-MM-DD)
        cabin_class: economy, premium_economy, business, first
        return_date: Return date for round-trip (optional)
        markets: List of markets to scrape for prices (default: ["US", "ES", "UK"])

    Returns:
        Dict with:
        - flights: List of flights with full details AND multi-market prices
        - cheapest_market: Market with best prices
        - savings: Potential savings vs US prices
    """
    if markets is None:
        markets = ["DE", "ES", "IT", "CA", "NL"]

    trip_type = "round-trip" if return_date else "one-way"
    print(f"\n{'='*70}")
    print(f"AMADEUS + PROXY SEARCH ({trip_type.upper()}): {origin} → {destination}")
    print(f"Date: {date}" + (f" returning {return_date}" if return_date else ""))
    print(f"Markets for pricing: {', '.join(markets)}")
    print(f"{'='*70}")

    result = {
        "origin": origin,
        "destination": destination,
        "date": date,
        "return_date": return_date,
        "is_round_trip": bool(return_date),
        "flights": [],
        "price_comparison": [],
        "cheapest_market": None,
        "cheapest_price_usd": None,
        "us_price_usd": None,
        "savings_vs_us": 0,
        "savings_pct": 0,
        "data_sources": [],
        "proxy_flights_by_market": {},
    }

    # --- STEP 1: Get detailed flight info from Amadeus ---
    amadeus_flights = []
    if AMADEUS_AVAILABLE and AMADEUS_CONFIGURED:
        print(f"\n[STEP 1] Fetching flight details from Amadeus API...")
        amadeus_result = search_with_amadeus(
            origin=origin,
            destination=destination,
            departure_date=date,
            return_date=return_date,
            cabin_class=cabin_class
        )
        if amadeus_result.get("success"):
            amadeus_flights = amadeus_result.get("flights", [])
            result["data_sources"].append("amadeus")
            print(f"  [AMADEUS] Found {len(amadeus_flights)} flights with full details")
        else:
            print(f"  [AMADEUS] Error: {amadeus_result.get('error', 'Unknown error')}")
    else:
        print(f"\n[STEP 1] Amadeus API not configured - skipping detailed flight info")
        print(f"         To enable: Add AMADEUS_API_KEY and AMADEUS_API_SECRET to .env")

    # --- STEP 2: Get prices from multiple markets via proxies ---
    proxy_result = None
    if DIRECT_SCRAPER_AVAILABLE:
        print(f"\n[STEP 2] Scraping prices from {len(markets)} markets via proxies...")
        try:
            from google_flights_scraper import scrape_flights_sync
            proxy_result = scrape_flights_sync(origin, destination, date, markets, cabin_class, return_date)
            if proxy_result and proxy_result.get("all_results"):
                result["data_sources"].append("proxy_scraping")

                # Store raw proxy data
                for market, market_data in proxy_result.get("all_results", {}).items():
                    if market_data.get("flights"):
                        result["proxy_flights_by_market"][market] = {
                            "flights": market_data["flights"],
                            "currency": market_data.get("currency", "USD"),
                            "flight_count": len(market_data["flights"])
                        }

                # Copy price comparison data from proxy markets
                result["price_comparison"] = proxy_result.get("price_comparison", [])

                # Cheapest proxy market price
                proxy_cheapest_market = proxy_result.get("cheapest_market")
                proxy_cheapest_price = proxy_result.get("cheapest_price_usd", 0)

                # Amadeus (booking) price is the user's actual cost
                if amadeus_flights:
                    amadeus_prices = [f.get("price", 0) for f in amadeus_flights if f.get("price")]
                    amadeus_cheapest = min(amadeus_prices) if amadeus_prices else 0
                    result["us_price_usd"] = amadeus_cheapest

                    # The real savings: cheapest proxy market vs Amadeus booking price
                    # If Amadeus is cheaper, the savings come from Phoenix's booking engine
                    # If proxy is cheaper, there's geographic arbitrage on top
                    if proxy_cheapest_price and proxy_cheapest_price > 0:
                        if amadeus_cheapest < proxy_cheapest_price:
                            # Amadeus beats all markets — Phoenix is the best deal
                            # Show savings vs cheapest Google market
                            result["cheapest_market"] = "Phoenix"
                            result["cheapest_price_usd"] = amadeus_cheapest
                            savings = proxy_cheapest_price - amadeus_cheapest
                            result["savings_vs_us"] = round(savings, 2)
                            result["savings_pct"] = round((savings / proxy_cheapest_price) * 100, 1)
                        else:
                            # Foreign market is cheaper — still brand as Phoenix
                            result["cheapest_market"] = "Phoenix"
                            result["cheapest_price_usd"] = proxy_cheapest_price
                            result["_internal_cheapest_market"] = proxy_cheapest_market
                            savings = amadeus_cheapest - proxy_cheapest_price
                            result["savings_vs_us"] = round(savings, 2)
                            result["savings_pct"] = round((savings / amadeus_cheapest) * 100, 1)
                    else:
                        result["cheapest_market"] = "Phoenix"
                        result["cheapest_price_usd"] = amadeus_cheapest
                        result["savings_vs_us"] = 0
                        result["savings_pct"] = 0

                print(f"  [PROXY] Scraped prices from {len(result['proxy_flights_by_market'])} markets")
        except Exception as e:
            print(f"  [PROXY] Error: {e}")
    else:
        print(f"\n[STEP 2] Proxy scraper not available - skipping price arbitrage")

    # --- STEP 3: Merge Amadeus details with proxy prices ---
    print(f"\n[STEP 3] Merging flight details with prices...")

    if amadeus_flights:
        # Use Amadeus flights as the base (they have the best details)
        for flight in amadeus_flights:
            merged_flight = {
                # Core identification
                "airline": flight.get("airline_name") or flight.get("airline"),
                "airline_code": flight.get("airline"),
                "flight_number": flight.get("flight_number"),

                # Times and route
                "departure_airport": flight.get("departure_airport"),
                "arrival_airport": flight.get("arrival_airport"),
                "departure_time": flight.get("departure_time"),
                "arrival_time": flight.get("arrival_time"),
                "duration": flight.get("duration_formatted"),
                "duration_minutes": flight.get("duration_minutes"),

                # Stops and connections
                "stops": flight.get("stops", 0),
                "layovers": flight.get("layovers", []),

                # Rich details from Amadeus
                "aircraft": flight.get("aircraft"),
                "cabin_class": flight.get("cabin_class"),
                "baggage_info": flight.get("baggage_info"),
                "segments": flight.get("segments", []),
                "is_codeshare": flight.get("is_codeshare", False),
                "operating_carrier": flight.get("operating_carrier"),

                # Return flight info (for round-trips)
                "return_flight": flight.get("return_flight"),
                "is_round_trip": flight.get("is_round_trip", False),

                # Pricing (will be enriched with proxy data)
                "amadeus_price": flight.get("price"),
                "amadeus_currency": flight.get("currency", "USD"),
                "prices_by_market": {},
                "cheapest_price_usd": None,
                "cheapest_market": None,
                "us_price_usd": None,

                # Matching key for proxy price lookup
                "match_key": flight.get("match_key"),

                # Raw Amadeus offer for booking API
                "raw_offer": flight.get("raw_offer"),
            }

            # Amadeus price = actual booking price (what user pays through Phoenix)
            # This is separate from Google Flights prices used for arbitrage comparison
            amadeus_price = flight.get("price", 0)
            merged_flight["us_price_usd"] = amadeus_price

            # Match this flight with proxy price data from foreign markets
            if result["proxy_flights_by_market"]:
                matched_prices = _match_flight_to_proxy_prices(
                    merged_flight,
                    result["proxy_flights_by_market"]
                )
                merged_flight["prices_by_market"] = matched_prices

                # Find cheapest foreign market for this flight
                if matched_prices:
                    cheapest = min(matched_prices.items(), key=lambda x: x[1].get("price_usd", 9999))
                    cheapest_proxy_usd = cheapest[1].get("price_usd", 9999)

                    # Use Amadeus as booking price — it's the actual cost to user
                    # Compare: Amadeus (booking) vs cheapest proxy market
                    if amadeus_price and amadeus_price < cheapest_proxy_usd:
                        # Amadeus is cheapest — user gets the best deal through Phoenix directly
                        merged_flight["cheapest_market"] = "Phoenix"
                        merged_flight["cheapest_price_usd"] = amadeus_price
                    else:
                        # Foreign market is cheaper than Amadeus — still brand as Phoenix
                        merged_flight["cheapest_market"] = "Phoenix"
                        merged_flight["cheapest_price_usd"] = cheapest_proxy_usd
                        merged_flight["_internal_market"] = cheapest[0]  # Internal only, never sent to frontend

                    # Inject Amadeus as "US" for display so user sees the comparison
                    merged_flight["prices_by_market"]["US"] = {
                        "price": amadeus_price,
                        "currency": "USD",
                        "price_usd": amadeus_price,
                        "match_score": 100,
                        "matched_airline": "Amadeus",
                        "matched_time": flight.get("departure_time"),
                    }

            # Fallback if no proxy matches
            if not merged_flight["cheapest_price_usd"] and amadeus_price:
                merged_flight["cheapest_price_usd"] = amadeus_price
                merged_flight["cheapest_market"] = "Phoenix"

            result["flights"].append(merged_flight)

    elif result["proxy_flights_by_market"]:
        # Fallback: No Amadeus data, use proxy data only (less detailed)
        print(f"  [MERGE] Using proxy data only (no Amadeus details available)")

        # Use US market as primary (or first available market)
        primary_market = "US" if "US" in result["proxy_flights_by_market"] else list(result["proxy_flights_by_market"].keys())[0]
        primary_flights = result["proxy_flights_by_market"][primary_market]["flights"]

        for flight in primary_flights:
            merged_flight = {
                "airline": flight.get("airline", "Various"),
                "airline_code": None,
                "flight_number": None,  # Not available from proxy scraping

                "departure_airport": origin,
                "arrival_airport": destination,
                "departure_time": flight.get("departure_time"),
                "arrival_time": flight.get("arrival_time"),
                "duration": flight.get("duration"),
                "duration_minutes": None,

                "stops": flight.get("stops"),
                "layovers": [],

                "aircraft": None,
                "cabin_class": cabin_class.title(),
                "baggage_info": None,
                "segments": [],
                "is_codeshare": False,
                "operating_carrier": None,

                "return_flight": None,
                "is_round_trip": bool(return_date),

                "amadeus_price": None,
                "amadeus_currency": None,
                "prices_by_market": {},
                "cheapest_price_usd": None,
                "cheapest_market": None,
                "us_price_usd": None,

                "match_key": f"{flight.get('airline', 'unknown')}_{flight.get('departure_time', '')}",
            }

            # Match with other markets
            matched_prices = _match_flight_to_proxy_prices(
                merged_flight,
                result["proxy_flights_by_market"]
            )
            merged_flight["prices_by_market"] = matched_prices

            if matched_prices:
                cheapest = min(matched_prices.items(), key=lambda x: x[1].get("price_usd", 9999))
                merged_flight["cheapest_market"] = "Phoenix"  # Never expose market codes
                merged_flight["cheapest_price_usd"] = cheapest[1].get("price_usd")
                merged_flight["_internal_market"] = cheapest[0]

                if "US" in matched_prices:
                    merged_flight["us_price_usd"] = matched_prices["US"].get("price_usd")

            result["flights"].append(merged_flight)

    # Sort flights by cheapest price
    result["flights"].sort(key=lambda x: x.get("cheapest_price_usd") or 9999)

    # --- Summary ---
    print(f"\n{'='*70}")
    print(f"SEARCH COMPLETE")
    print(f"{'='*70}")
    print(f"Data sources: {', '.join(result['data_sources']) or 'None'}")
    print(f"Total flights: {len(result['flights'])}")
    if result["savings_vs_us"] > 0:
        print(f"Best arbitrage: Save ${result['savings_vs_us']:.2f} ({result['savings_pct']:.1f}%) via {result['cheapest_market']}")

    return result


def _normalize_time_to_24h(time_str: str) -> str:
    """Convert any time format to HH:MM 24-hour format."""
    if not time_str:
        return ""
    time_str = time_str.strip()

    # Already 24h format like "08:30" or from ISO "2026-02-15T08:30:00"
    if "T" in time_str:
        time_str = time_str.split("T")[1][:5]
    elif " " in time_str and "-" in time_str.split(" ")[0]:
        # "2026-02-15 08:30" format
        time_str = time_str.split(" ")[1][:5]

    # Handle AM/PM
    upper = time_str.upper().strip()
    is_pm = "PM" in upper
    is_am = "AM" in upper
    cleaned = upper.replace("AM", "").replace("PM", "").strip()

    match = __import__("re").match(r"(\d{1,2}):(\d{2})", cleaned)
    if not match:
        return time_str[:5] if len(time_str) >= 5 else time_str

    hour = int(match.group(1))
    minute = match.group(2)

    if is_pm and hour < 12:
        hour += 12
    elif is_am and hour == 12:
        hour = 0

    return f"{hour:02d}:{minute}"


def _normalize_airline(name: str) -> str:
    """Normalize airline name for matching."""
    if not name:
        return ""
    name = name.lower().strip()
    # Remove common suffixes/prefixes
    for suffix in [" airlines", " airways", " air lines", " air"]:
        if name.endswith(suffix):
            name = name[:-len(suffix)]
    # Common abbreviation mappings
    aliases = {
        "american": "american",
        "aa": "american",
        "delta": "delta",
        "dl": "delta",
        "united": "united",
        "ua": "united",
        "southwest": "southwest",
        "wn": "southwest",
        "jetblue": "jetblue",
        "b6": "jetblue",
        "jet blue": "jetblue",
        "alaska": "alaska",
        "as": "alaska",
        "hawaiian": "hawaiian",
        "ha": "hawaiian",
        "spirit": "spirit",
        "nk": "spirit",
        "frontier": "frontier",
        "f9": "frontier",
        "allegiant": "allegiant",
        "g4": "allegiant",
    }
    return aliases.get(name, name)


def _match_flight_to_proxy_prices(flight: dict, proxy_flights_by_market: dict) -> dict:
    """
    Match a flight to prices from different markets.

    Matching strategy:
    1. Exact match: Same airline + same departure time
    2. Fuzzy match: Same airline + departure time within 30 minutes
    3. Time-only match: Exact departure time (different airline name format)

    Returns dict of market -> {price, currency, price_usd}
    """
    prices_by_market = {}

    flight_airline = _normalize_airline(flight.get("airline") or "")
    flight_time = _normalize_time_to_24h(flight.get("departure_time") or "")

    for market, market_data in proxy_flights_by_market.items():
        currency = market_data.get("currency", "USD")
        proxy_flights = market_data.get("flights", [])

        best_match = None
        best_score = 0

        for proxy_flight in proxy_flights:
            proxy_airline = _normalize_airline(proxy_flight.get("airline") or "")
            proxy_time = _normalize_time_to_24h(proxy_flight.get("departure_time") or "")

            score = 0

            # Airline matching
            if flight_airline and proxy_airline:
                if flight_airline == proxy_airline:
                    score += 50
                elif flight_airline in proxy_airline or proxy_airline in flight_airline:
                    score += 35

            # Time matching (24h normalized)
            if flight_time and proxy_time:
                if flight_time == proxy_time:
                    score += 50
                else:
                    try:
                        fh, fm = int(flight_time[:2]), int(flight_time[3:5])
                        ph, pm = int(proxy_time[:2]), int(proxy_time[3:5])
                        diff_min = abs((fh * 60 + fm) - (ph * 60 + pm))
                        if diff_min <= 15:
                            score += 40  # Very close
                        elif diff_min <= 30:
                            score += 25
                        elif diff_min <= 60:
                            score += 10
                    except (ValueError, IndexError):
                        pass

            if score > best_score and proxy_flight.get("price"):
                best_score = score
                best_match = proxy_flight

        # Require airline+time match (100), or strong airline+close time (75+),
        # or exact time match (50) as minimum
        if best_match and best_score >= 50:
            price = best_match.get("price", 0)
            rate = CURRENCY_RATES_TO_USD.get(currency, 1.0)
            price_usd = price * rate

            prices_by_market[market] = {
                "price": price,
                "currency": currency,
                "price_usd": round(price_usd, 2),
                "match_score": best_score,
                "matched_airline": best_match.get("airline"),
                "matched_time": best_match.get("departure_time"),
            }

    return prices_by_market


# --- UTILITY FUNCTIONS ---
def generate_dates(start, end):
    start_dt = datetime.strptime(start, "%Y-%m-%d")
    end_dt = datetime.strptime(end, "%Y-%m-%d")
    delta = end_dt - start_dt
    return [(start_dt + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(delta.days + 1)]


def extract_flights(results, market, departure, arrival, outbound_date):
    flights = []
    if not results:
        return flights
    keys = ["best_flights", "other_flights", "flights_results", "results", "organic_results", "flight_results"]
    items = []
    for k in keys:
        if k in results and isinstance(results[k], list):
            items.extend(results[k])
    for item in items:
        segment = item.get("flights", [{}])[0]
        price = item.get("price")
        if not price:
            continue
        flight_id = f"{segment.get('airline')}_{segment.get('flight_number')}_{departure}_{arrival}_{outbound_date}"
        flights.append({
            "flight_id": flight_id,
            "market": market["label"],
            "currency": market["currency"],  # Store the currency for conversion
            "departure": departure,
            "arrival": arrival,
            "outbound_date": outbound_date,
            "airline": segment.get("airline"),
            "flight_number": segment.get("flight_number"),
            "price": price,
            "departure_time": segment.get("departure", {}).get("time"),
            "arrival_time": segment.get("arrival", {}).get("time"),
            "stops": item.get("stops")
        })
    return flights

# --- CURRENCY CONVERSION ---
# Rates relative to USD (1 of each currency = X USD)
# These are approximate - in production, fetch live rates
CURRENCY_RATES_TO_USD = {
    # Major currencies
    "USD": 1.0,
    "EUR": 1.08,      # 1 EUR ≈ 1.08 USD
    "GBP": 1.26,      # 1 GBP ≈ 1.26 USD
    "PLN": 0.25,      # 1 PLN ≈ 0.25 USD (Polish Złoty)
    "JPY": 0.0067,    # 1 JPY ≈ 0.0067 USD
    "CAD": 0.74,      # 1 CAD ≈ 0.74 USD
    "AUD": 0.65,      # 1 AUD ≈ 0.65 USD
    "NZD": 0.60,      # 1 NZD ≈ 0.60 USD
    "CHF": 1.12,      # 1 CHF ≈ 1.12 USD

    # Asia Pacific
    "KRW": 0.00075,   # 1 KRW ≈ 0.00075 USD
    "CNY": 0.14,      # 1 CNY ≈ 0.14 USD
    "HKD": 0.13,      # 1 HKD ≈ 0.13 USD
    "TWD": 0.031,     # 1 TWD ≈ 0.031 USD
    "SGD": 0.74,      # 1 SGD ≈ 0.74 USD
    "THB": 0.028,     # 1 THB ≈ 0.028 USD
    "INR": 0.012,     # 1 INR ≈ 0.012 USD
    "MYR": 0.21,      # 1 MYR ≈ 0.21 USD
    "PHP": 0.018,     # 1 PHP ≈ 0.018 USD
    "IDR": 0.000063,  # 1 IDR ≈ 0.000063 USD
    "VND": 0.00004,   # 1 VND ≈ 0.00004 USD

    # Americas
    "MXN": 0.058,     # 1 MXN ≈ 0.058 USD
    "BRL": 0.20,      # 1 BRL ≈ 0.20 USD
    "ARS": 0.0012,    # 1 ARS ≈ 0.0012 USD
    "CLP": 0.0011,    # 1 CLP ≈ 0.0011 USD
    "COP": 0.00025,   # 1 COP ≈ 0.00025 USD

    # Europe
    "PLN": 0.25,      # 1 PLN ≈ 0.25 USD
    "CZK": 0.043,     # 1 CZK ≈ 0.043 USD
    "HUF": 0.0027,    # 1 HUF ≈ 0.0027 USD
    "SEK": 0.095,     # 1 SEK ≈ 0.095 USD
    "NOK": 0.092,     # 1 NOK ≈ 0.092 USD
    "DKK": 0.145,     # 1 DKK ≈ 0.145 USD
    "TRY": 0.031,     # 1 TRY ≈ 0.031 USD
    "RUB": 0.011,     # 1 RUB ≈ 0.011 USD

    # Middle East / Africa
    "AED": 0.27,      # 1 AED ≈ 0.27 USD
    "SAR": 0.27,      # 1 SAR ≈ 0.27 USD
    "ILS": 0.27,      # 1 ILS ≈ 0.27 USD
    "ZAR": 0.055,     # 1 ZAR ≈ 0.055 USD
    "EGP": 0.032,     # 1 EGP ≈ 0.032 USD
}

CURRENCY_SYMBOLS = {
    "USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥",
    "CAD": "C$", "AUD": "A$", "NZD": "NZ$", "CHF": "CHF",
    "KRW": "₩", "CNY": "¥", "HKD": "HK$", "TWD": "NT$",
    "SGD": "S$", "THB": "฿", "INR": "₹", "MYR": "RM",
    "PHP": "₱", "IDR": "Rp", "VND": "₫",
    "MXN": "MX$", "BRL": "R$", "ARS": "AR$", "CLP": "CL$", "COP": "CO$",
    "PLN": "zł", "CZK": "Kč", "HUF": "Ft", "SEK": "kr", "NOK": "kr",
    "DKK": "kr", "TRY": "₺", "RUB": "₽",
    "AED": "د.إ", "SAR": "﷼", "ILS": "₪", "ZAR": "R", "EGP": "E£",
}

def convert_price(price, from_currency, to_currency):
    """Convert price from one currency to the display currency."""
    # Clean the price string (e.g., "$542.00" or "¥83,000")
    if isinstance(price, str):
        price = price.replace('$', '').replace('¥', '').replace('€', '')
        price = price.replace('£', '').replace('₩', '').replace(',', '')
    try:
        price_float = float(price)
    except (ValueError, TypeError):
        return None

    # Convert: from_currency -> USD -> to_currency
    usd_rate = CURRENCY_RATES_TO_USD.get(from_currency, 1.0)
    target_rate = CURRENCY_RATES_TO_USD.get(to_currency, 1.0)

    price_in_usd = price_float * usd_rate
    return price_in_usd / target_rate

def format_price(amount, currency):
    """Format price with currency symbol."""
    symbol = CURRENCY_SYMBOLS.get(currency, currency + " ")
    if currency == "JPY" or currency == "KRW":
        return f"{symbol}{amount:,.0f}"  # No decimals for JPY/KRW
    return f"{symbol}{amount:,.2f}"


# --- XRPL PAYMENT FUNCTIONS ---
def get_xrpl_client():
    """Get XRPL client for the configured network."""
    if not XRPL_AVAILABLE:
        return None

    if XRPL_CONFIG["network"] == "testnet":
        return JsonRpcClient(XRPL_CONFIG["testnet_url"])
    return JsonRpcClient(XRPL_CONFIG["mainnet_url"])


def usd_to_xrp(usd_amount):
    """Convert USD to XRP based on current rate."""
    rate = XRPL_CONFIG["xrp_usd_rate"]
    if rate <= 0:
        return None
    return round(usd_amount / rate, 6)


def generate_payment_request(deal_id, fee_usd, user_id=None):
    """
    Generate a payment request for the platform fee.

    Args:
        deal_id: Unique identifier for this deal/transaction
        fee_usd: Platform fee in USD
        user_id: Optional user identifier

    Returns:
        dict with payment details for the user
    """
    xrp_amount = usd_to_xrp(fee_usd)
    if xrp_amount is None:
        return {"error": "Could not calculate XRP amount"}

    # Create a unique memo/tag for this transaction
    # This helps identify which payment is for which deal
    memo_data = f"PHOENIX:{deal_id}"
    if user_id:
        memo_data += f":{user_id}"

    # Generate destination tag (numeric identifier for this transaction)
    # In production, store this in your database to match payments
    destination_tag = abs(hash(deal_id)) % 2147483647  # Keep within uint32 range

    return {
        "payment_request": {
            "destination": XRPL_CONFIG["platform_wallet_address"],
            "destination_tag": destination_tag,
            "amount_xrp": xrp_amount,
            "amount_usd": fee_usd,
            "memo": memo_data,
            "network": XRPL_CONFIG["network"],
        },
        "qr_data": f"xrpl:{XRPL_CONFIG['platform_wallet_address']}?amount={xrp_amount}&dt={destination_tag}",
        "expires_in_minutes": 15,
        "deal_id": deal_id,
    }


def verify_payment(destination_tag, expected_xrp, tolerance=0.01):
    """
    Verify that a payment was received for a specific deal.

    Args:
        destination_tag: The destination tag from the payment request
        expected_xrp: Expected XRP amount
        tolerance: Acceptable variance (for rounding/fees)

    Returns:
        dict with verification result
    """
    if not XRPL_AVAILABLE:
        return {"verified": False, "error": "XRPL library not available"}

    client = get_xrpl_client()
    if not client:
        return {"verified": False, "error": "Could not connect to XRPL"}

    try:
        # Query recent transactions to our wallet
        request = AccountTx(
            account=XRPL_CONFIG["platform_wallet_address"],
            limit=50  # Check last 50 transactions
        )
        response = client.request(request)

        if not response.is_successful():
            return {"verified": False, "error": "Failed to query transactions"}

        # Look for matching payment
        for tx in response.result.get("transactions", []):
            tx_data = tx.get("tx", {})

            # Check if it's a payment to us with matching destination tag
            if tx_data.get("TransactionType") != "Payment":
                continue
            if tx_data.get("Destination") != XRPL_CONFIG["platform_wallet_address"]:
                continue
            if tx_data.get("DestinationTag") != destination_tag:
                continue

            # Check amount (convert drops to XRP)
            amount_drops = tx_data.get("Amount")
            if isinstance(amount_drops, str):
                amount_xrp = float(drops_to_xrp(amount_drops))
                if abs(amount_xrp - expected_xrp) <= tolerance:
                    return {
                        "verified": True,
                        "tx_hash": tx_data.get("hash"),
                        "amount_xrp": amount_xrp,
                        "sender": tx_data.get("Account"),
                    }

        return {"verified": False, "error": "Payment not found"}

    except Exception as e:
        return {"verified": False, "error": str(e)}


# --- CURRENCY ARBITRAGE ANALYSIS ---

def analyze_currency_options(original_prices, converted_prices):
    """
    Analyze which currency offers the best value for payment.

    Some airlines/OTAs have internal exchange rates that differ from
    market rates. This function identifies when paying in a specific
    currency saves money.

    Args:
        original_prices: Dict of {market: {amount, currency}}
        converted_prices: Dict of {market: usd_value}

    Returns:
        dict with currency analysis
    """
    if not original_prices or not converted_prices:
        return None

    currency_options = []

    for market, orig in original_prices.items():
        if market not in converted_prices:
            continue

        currency = orig.get("currency", "USD")
        amount = orig.get("amount", 0)

        # Clean the amount
        if isinstance(amount, str):
            amount = float(amount.replace(',', '').replace('$', '').replace('¥', '').replace('€', '').replace('£', ''))

        usd_value = converted_prices[market]

        # Calculate what the market rate SHOULD give us
        market_rate = CURRENCY_RATES_TO_USD.get(currency, 1.0)
        expected_usd = amount * market_rate

        # If site's USD value differs from market rate conversion,
        # there's a currency advantage/disadvantage
        rate_difference = usd_value - expected_usd
        rate_advantage_pct = (rate_difference / expected_usd * 100) if expected_usd > 0 else 0

        currency_options.append({
            "market": market,
            "currency": currency,
            "original_amount": amount,
            "usd_value": usd_value,
            "expected_usd": round(expected_usd, 2),
            "rate_advantage": round(rate_difference, 2),
            "rate_advantage_pct": round(rate_advantage_pct, 1),
        })

    # Sort by USD value (cheapest first)
    currency_options.sort(key=lambda x: x["usd_value"])

    if not currency_options:
        return None

    best = currency_options[0]
    worst = currency_options[-1]

    # Calculate currency savings (best vs worst)
    currency_savings = worst["usd_value"] - best["usd_value"] if len(currency_options) > 1 else 0

    return {
        "best_currency": best["currency"],
        "best_market": best["market"],
        "best_price_usd": best["usd_value"],
        "worst_price_usd": worst["usd_value"] if len(currency_options) > 1 else best["usd_value"],
        "currency_savings_usd": round(currency_savings, 2),
        "all_options": currency_options,
        "recommendation": f"Pay in {best['currency']} ({best['market']} market)" if currency_savings > 5 else None,
    }


def get_payment_currency_tip(currency_analysis, cheapest_market):
    """
    Generate a user-friendly tip about payment currency.

    Args:
        currency_analysis: Result from analyze_currency_options
        cheapest_market: The market where the deal is being booked

    Returns:
        str with payment tip or None
    """
    if not currency_analysis:
        return None

    best = currency_analysis.get("best_currency", "USD")
    savings = currency_analysis.get("currency_savings_usd", 0)

    if savings < 5:
        return None

    return f"TIP: Pay in {best} to save ${savings:.2f} more"


# --- DEAL CALCULATOR ---
def calculate_deal(home_price, arbitrage_price, airline, cheapest_market,
                   original_prices=None, converted_prices=None):
    """
    Calculate the deal breakdown for the user.

    Args:
        home_price: Price in user's home market (what they'd normally pay)
        arbitrage_price: Price in cheaper foreign market
        airline: Airline name for booking URL
        cheapest_market: Market code (e.g., "JP") for booking
        original_prices: Dict of original prices by market (for currency analysis)
        converted_prices: Dict of USD-converted prices by market

    Returns:
        dict with deal analysis
    """
    # Gross savings before platform fee
    gross_savings = home_price - arbitrage_price

    if gross_savings <= 0:
        return None

    # Platform fee: percentage of savings, with min/max caps
    platform_fee = gross_savings * (PLATFORM_FEE_CONFIG["savings_cut_pct"] / 100)
    platform_fee = max(platform_fee, PLATFORM_FEE_CONFIG["min_fee_usd"])
    platform_fee = min(platform_fee, PLATFORM_FEE_CONFIG["max_fee_usd"])

    # User's net savings after our fee
    user_savings = gross_savings - platform_fee

    # Is this deal worth showing?
    is_good_deal = user_savings >= MIN_USER_SAVINGS_USD

    # Get booking URL for this airline/market
    airline_urls = AIRLINE_BOOKING_URLS.get(airline, AIRLINE_BOOKING_URLS["default"])
    booking_url = airline_urls.get(cheapest_market, airline_urls.get("JP", ""))

    # Generate unique deal ID
    deal_id = hashlib.md5(f"{airline}:{cheapest_market}:{home_price}:{arbitrage_price}".encode()).hexdigest()[:12]

    # Generate payment request for the platform fee
    payment_request = generate_payment_request(deal_id, platform_fee)

    # Analyze currency options
    currency_analysis = None
    payment_tip = None
    if original_prices and converted_prices:
        currency_analysis = analyze_currency_options(original_prices, converted_prices)
        payment_tip = get_payment_currency_tip(currency_analysis, cheapest_market)

    return {
        "deal_id": deal_id,
        "home_price": round(home_price, 2),
        "arbitrage_price": round(arbitrage_price, 2),
        "gross_savings": round(gross_savings, 2),
        "platform_fee_usd": round(platform_fee, 2),
        "platform_fee_xrp": payment_request.get("payment_request", {}).get("amount_xrp"),
        "user_savings": round(user_savings, 2),
        "user_saves_pct": round((user_savings / home_price) * 100, 1) if home_price > 0 else 0,
        "is_good_deal": is_good_deal,
        "booking_url": booking_url,
        "booking_market": cheapest_market,
        "payment": payment_request,
        # Currency arbitrage info
        "currency_analysis": currency_analysis,
        "payment_tip": payment_tip,
        "best_payment_currency": currency_analysis.get("best_currency") if currency_analysis else None,
        "currency_savings_usd": currency_analysis.get("currency_savings_usd", 0) if currency_analysis else 0,
    }


# --- MARKET COMPARISON ---
def compare_markets(all_flights):
    flights_by_id = {}
    for f in all_flights:
        flights_by_id.setdefault(f["flight_id"], []).append(f)
    comparison = []
    for flight_id, entries in flights_by_id.items():
        converted_prices = {}
        original_prices = {}
        for e in entries:
            converted = convert_price(e["price"], e["currency"], DISPLAY_CURRENCY)
            if converted:
                converted_prices[e["market"]] = round(converted, 2)
                original_prices[e["market"]] = {"amount": e["price"], "currency": e["currency"]}
        if not converted_prices:
            continue
        cheapest_market = min(converted_prices, key=converted_prices.get)

        # Calculate savings if buying from cheaper market
        savings = None
        savings_pct = None
        if len(converted_prices) > 1:
            most_expensive = max(converted_prices.values())
            cheapest = converted_prices[cheapest_market]
            savings = round(most_expensive - cheapest, 2)
            savings_pct = round((savings / most_expensive) * 100, 1)

        # Calculate deal if there's an arbitrage opportunity
        deal = None
        if len(converted_prices) > 1 and savings and savings > 0:
            home_market_price = most_expensive
            arbitrage_price = converted_prices[cheapest_market]
            deal = calculate_deal(
                home_market_price,
                arbitrage_price,
                entries[0]["airline"],
                cheapest_market,
                original_prices=original_prices,
                converted_prices=converted_prices
            )

        comparison.append({
            "flight_id": flight_id,
            "airline": entries[0]["airline"],
            "flight_number": entries[0]["flight_number"],
            "route": f"{entries[0]['departure']} → {entries[0]['arrival']}",
            "date": entries[0]["outbound_date"],
            "original_prices": original_prices,
            "converted_prices": converted_prices,
            "display_currency": DISPLAY_CURRENCY,
            "cheapest_market": cheapest_market,
            "cheapest_price": converted_prices[cheapest_market],
            "savings": savings,
            "savings_pct": savings_pct,
            "deal": deal,
        })
    return comparison

# --- COMPREHENSIVE SEARCH FUNCTIONS ---

def search_route(origin, destination, date, markets=None, fast_mode=True):
    """
    Search a single route across multiple markets.

    Args:
        origin: Origin airport code (e.g., "LAX")
        destination: Destination airport code (e.g., "JFK")
        date: Date string (e.g., "2026-02-15")
        markets: List of market configs to check (default: PRIORITY_MARKETS)
        fast_mode: If True, use priority markets only

    Returns:
        list of flight results with market comparisons
    """
    if markets is None:
        markets = PRIORITY_MARKETS if fast_mode else MARKETS

    all_flights = []
    for market in markets:
        print(f"  Checking {origin}→{destination} in {market['label']} market...")
        results = fetch_flights_direct(origin, destination, date, market)
        flights = extract_flights(results, market, origin, destination, date)
        all_flights.extend(flights)

    return compare_markets(all_flights)


def search_flight_number(flight_number, origin, destination, date, markets=None):
    """
    Search for a specific flight number across multiple markets.

    Compares prices for the exact same flight from different regional markets.

    Args:
        flight_number: Flight number (e.g., "AA 123", "AA123", "American Airlines 123")
        origin: Origin airport code
        destination: Destination airport code
        date: Date string (YYYY-MM-DD)
        markets: List of market configs to check (default: all priority markets)

    Returns:
        dict with flight details and market price comparison
    """
    import re

    # Parse flight number - extract airline code and number
    # Supports: "AA 123", "AA123", "American Airlines 123", "LL 2624"
    flight_number = flight_number.strip().upper()

    # Try to match various formats
    match = re.match(r'^([A-Z]{2,3})\s*(\d+)$', flight_number)
    if not match:
        # Try extracting from longer format like "AMERICAN AIRLINES 123"
        match = re.match(r'^.*?([A-Z]{2,3})\s*(\d+)$', flight_number)

    if match:
        airline_code = match.group(1)
        flight_num = match.group(2)
        search_pattern = f"{airline_code} {flight_num}"
    else:
        search_pattern = flight_number

    print(f"\n{'='*60}")
    print(f"FLIGHT NUMBER SEARCH: {search_pattern}")
    print(f"Route: {origin} → {destination}")
    print(f"Date: {date}")
    print(f"{'='*60}")

    if markets is None:
        markets = PRIORITY_MARKETS

    # Fetch flights from all markets
    market_prices = {}
    flight_details = None

    for market in markets:
        print(f"\n  Checking {market['label']} market...")
        results = fetch_flights_direct(origin, destination, date, market)
        flights = extract_flights(results, market, origin, destination, date)

        # Find the specific flight
        for f in flights:
            fn = f.get('flight_number', '').upper()
            # Match flight number (handle formats like "LL 2624" or "LL2624")
            if fn and (fn == search_pattern or fn.replace(' ', '') == search_pattern.replace(' ', '')):
                # Store price for this market
                price_usd = convert_price(f['price'], f['currency'], 'USD')
                market_prices[market['label']] = {
                    'original_price': f['price'],
                    'original_currency': f['currency'],
                    'price_usd': round(price_usd, 2) if price_usd else None,
                    'market': market['label'],
                }

                # Store flight details (from first match)
                if not flight_details:
                    flight_details = {
                        'airline': f.get('airline'),
                        'flight_number': f.get('flight_number'),
                        'origin': origin,
                        'destination': destination,
                        'date': date,
                        'departure_time': f.get('departure_time'),
                        'arrival_time': f.get('arrival_time'),
                        'stops': f.get('stops'),
                    }

                print(f"    Found: {f['price']} {f['currency']} (${price_usd:.2f} USD)")
                break
        else:
            print(f"    Flight not found in this market")

    if not flight_details:
        return {
            'found': False,
            'search_query': search_pattern,
            'error': f'Flight {search_pattern} not found on {date} for {origin}→{destination}'
        }

    # Calculate comparison
    if market_prices:
        prices_usd = {k: v['price_usd'] for k, v in market_prices.items() if v['price_usd']}

        if prices_usd:
            cheapest_market = min(prices_usd, key=prices_usd.get)
            most_expensive_market = max(prices_usd, key=prices_usd.get)
            cheapest_price = prices_usd[cheapest_market]
            most_expensive_price = prices_usd[most_expensive_market]
            max_savings = round(most_expensive_price - cheapest_price, 2)
            savings_pct = round((max_savings / most_expensive_price) * 100, 1) if most_expensive_price > 0 else 0

            # Calculate deal with platform fee
            deal = None
            if max_savings > 0:
                deal = calculate_deal(most_expensive_price, cheapest_price, flight_details['airline'], cheapest_market)

            return {
                'found': True,
                'flight': flight_details,
                'market_prices': market_prices,
                'comparison': {
                    'cheapest_market': 'Phoenix',
                    'cheapest_price_usd': cheapest_price,
                    'most_expensive_market': 'Standard',
                    'most_expensive_price_usd': most_expensive_price,
                    'max_savings_usd': max_savings,
                    'savings_percent': savings_pct,
                    'markets_checked': len(market_prices),
                },
                'deal': deal,
                'google_flights_url': f"https://www.google.com/travel/flights?q=flights%20{origin}%20to%20{destination}%20on%20{date}",
            }

    return {
        'found': True,
        'flight': flight_details,
        'market_prices': market_prices,
        'comparison': None,
        'error': 'Not enough market data for comparison'
    }


def search_domestic_deals(origin=None, dates=None, markets=None, limit_destinations=3):
    """
    Search for domestic flight deals.

    Domestic flights often have smaller discrepancies, but checking
    international versions of Google Flights can still reveal savings.

    Args:
        origin: Origin airport code (default: first in DOMESTIC_ROUTES)
        dates: List of dates to check
        markets: Markets to compare
        limit_destinations: Max destinations to check per origin

    Returns:
        list of deals found
    """
    print("\n" + "="*60)
    print("SEARCHING DOMESTIC ROUTES")
    print("="*60)

    if markets is None:
        # For domestic, check US plus international perspectives
        markets = [
            {"label": "US", "currency": "USD", "gl": "us", "hl": "en", "region": "NA"},
            {"label": "UK", "currency": "GBP", "gl": "uk", "hl": "en", "region": "EU"},
            {"label": "CA", "currency": "CAD", "gl": "ca", "hl": "en", "region": "NA"},
            {"label": "DE", "currency": "EUR", "gl": "de", "hl": "de", "region": "EU"},
            {"label": "IN", "currency": "INR", "gl": "in", "hl": "en", "region": "APAC"},
        ]

    routes = DOMESTIC_ROUTES
    if origin:
        routes = [r for r in routes if r["origin"] == origin]

    if not dates:
        dates = generate_dates(START_DATE, END_DATE)[:5]  # Limit dates

    all_deals = []

    for route in routes:
        orig = route["origin"]
        destinations = route["destinations"][:limit_destinations]

        for dest in destinations:
            for date in dates:
                print(f"\nSearching {orig} → {dest} on {date}")
                comparison = search_route(orig, dest, date, markets)

                # Filter for good deals
                for flight in comparison:
                    if flight.get('deal') and flight['deal']['is_good_deal']:
                        flight['route_type'] = 'domestic'
                        all_deals.append(flight)

    print(f"\n{'='*60}")
    print(f"Found {len(all_deals)} domestic deals")
    print(f"{'='*60}")

    return all_deals


def search_international_deals(origin=None, dates=None, markets=None, limit_destinations=3):
    """
    Search for international flight deals.

    International flights typically have larger price discrepancies
    due to regional pricing strategies.

    Args:
        origin: Origin airport code (default: first in INTERNATIONAL_ROUTES)
        dates: List of dates to check
        markets: Markets to compare
        limit_destinations: Max destinations to check per origin

    Returns:
        list of deals found
    """
    print("\n" + "="*60)
    print("SEARCHING INTERNATIONAL ROUTES")
    print("="*60)

    if markets is None:
        markets = PRIORITY_MARKETS

    routes = INTERNATIONAL_ROUTES
    if origin:
        routes = [r for r in routes if r["origin"] == origin]

    if not dates:
        dates = generate_dates(START_DATE, END_DATE)[:5]

    all_deals = []

    for route in routes:
        orig = route["origin"]
        destinations = route["destinations"][:limit_destinations]

        for dest in destinations:
            for date in dates:
                print(f"\nSearching {orig} → {dest} on {date}")
                comparison = search_route(orig, dest, date, markets)

                for flight in comparison:
                    if flight.get('deal') and flight['deal']['is_good_deal']:
                        flight['route_type'] = 'international'
                        all_deals.append(flight)

    print(f"\n{'='*60}")
    print(f"Found {len(all_deals)} international deals")
    print(f"{'='*60}")

    return all_deals


def search_all_deals(fast_mode=True, include_domestic=True, include_international=True):
    """
    Comprehensive search across all routes and markets.

    Args:
        fast_mode: If True, use fewer markets for faster results
        include_domestic: Search domestic routes
        include_international: Search international routes

    Returns:
        dict with categorized deals
    """
    print("\n" + "="*70)
    print("PHOENIX - COMPREHENSIVE PRICE COMPARISON")
    print("="*70)
    print(f"Mode: {'Fast (priority markets)' if fast_mode else 'Full (all markets)'}")
    print(f"Searching: {', '.join(filter(None, ['Domestic' if include_domestic else '', 'International' if include_international else '']))}")
    print("="*70)

    # Fetch live rates
    print("\nUpdating exchange rates...")
    fetch_live_currency_rates()
    get_xrp_price()

    all_deals = []

    if include_domestic:
        domestic = search_domestic_deals(
            markets=PRIORITY_MARKETS[:5] if fast_mode else None,
            limit_destinations=2 if fast_mode else 4
        )
        all_deals.extend(domestic)

    if include_international:
        international = search_international_deals(
            markets=PRIORITY_MARKETS if fast_mode else MARKETS,
            limit_destinations=2 if fast_mode else 4
        )
        all_deals.extend(international)

    # Sort by user savings
    all_deals.sort(
        key=lambda x: x['deal']['user_savings'] if x.get('deal') else 0,
        reverse=True
    )

    # Categorize results
    results = {
        'domestic_deals': [d for d in all_deals if d.get('route_type') == 'domestic'],
        'international_deals': [d for d in all_deals if d.get('route_type') == 'international'],
        'all_deals': all_deals,
        'total_count': len(all_deals),
        'xrp_rate': XRPL_CONFIG['xrp_usd_rate'],
    }

    return results


def custom_search(origin, destination, date, all_markets=False):
    """
    Search a specific route with maximum market coverage.

    Args:
        origin: Origin airport code
        destination: Destination airport code
        date: Date string
        all_markets: If True, check ALL markets (slower but thorough)

    Returns:
        comparison results with deals
    """
    print(f"\n{'='*60}")
    print(f"CUSTOM SEARCH: {origin} → {destination} on {date}")
    print(f"{'='*60}")

    get_xrp_price()
    fetch_live_currency_rates()

    markets = MARKETS if all_markets else PRIORITY_MARKETS
    print(f"Checking {len(markets)} markets...")

    comparison = search_route(origin, destination, date, markets, fast_mode=not all_markets)

    # Print results
    deals = [f for f in comparison if f.get('deal') and f['deal']['is_good_deal']]
    no_arbitrage = [f for f in comparison if not f.get('deal') or not f['deal']['is_good_deal']]

    print(f"\n{'='*60}")
    print(f"RESULTS: {len(deals)} deals found / {len(comparison)} flights checked")
    print(f"{'='*60}")

    for flight in deals:
        deal = flight['deal']
        print(f"\n{flight['airline']} {flight['flight_number']} | {flight['route']}")
        print(f"  Cheapest: {flight['cheapest_market']} at ${flight['cheapest_price']:.2f}")
        print(f"  You save: ${deal['user_savings']:.2f} ({deal['user_saves_pct']}%)")
        print(f"  Platform fee: ${deal['platform_fee_usd']:.2f} ({deal['platform_fee_xrp']:.4f} XRP)")
        if deal.get('payment_tip'):
            print(f"  {deal['payment_tip']}")

    return comparison


# --- MAIN EXECUTION ---
def run():
    # Fetch live XRP price before processing
    print("Fetching live XRP price...")
    get_xrp_price()
    print()

    all_flights = []
    outbound_dates = generate_dates(START_DATE, END_DATE)
    for market in MARKETS:
        for outbound_date in outbound_dates:
            for dest in DESTINATIONS:
                print(f"Fetching {ORIGIN} → {dest} on {outbound_date} for market: {market['label']}")
                results = fetch_flights_direct(ORIGIN, dest, outbound_date, market)
                flights = extract_flights(results, market, ORIGIN, dest, outbound_date)
                all_flights.extend(flights)
                if not flights:
                    print(f"  -> No flights found. Raw JSON:")
                    print(json.dumps(results, indent=2, ensure_ascii=False))
    
    comparison = compare_markets(all_flights)

    # Sort by user savings (best deals first)
    comparison.sort(
        key=lambda x: x['deal']['user_savings'] if x.get('deal') else 0,
        reverse=True
    )

    # Separate good deals vs not worth it
    good_deals = [f for f in comparison if f.get('deal') and f['deal']['is_good_deal']]
    other_flights = [f for f in comparison if not f.get('deal') or not f['deal']['is_good_deal']]

    print("\n" + "="*70)
    print(f"FLIGHT DEALS - Save by booking from cheaper markets")
    print(f"Platform fee: {PLATFORM_FEE_CONFIG['savings_cut_pct']}% of savings (min ${PLATFORM_FEE_CONFIG['min_fee_usd']}, max ${PLATFORM_FEE_CONFIG['max_fee_usd']})")
    print(f"Showing deals with ${MIN_USER_SAVINGS_USD}+ savings")
    print("="*70)

    if not good_deals:
        print("\nNo deals found meeting the minimum savings threshold.")
    else:
        for flight in good_deals:
            deal = flight['deal']
            print(f"\n{flight['airline']} {flight['flight_number']} | {flight['route']} | {flight['date']}")
            print("-" * 60)

            # Show price comparison
            for market, orig in flight['original_prices'].items():
                converted = flight['converted_prices'][market]
                orig_formatted = format_price(float(str(orig['amount']).replace(',', '').replace('$', '').replace('¥', '').replace('€', '').replace('£', '')), orig['currency'])
                converted_formatted = format_price(converted, DISPLAY_CURRENCY)
                if market == flight['cheapest_market']:
                    print(f"  {market} MARKET: {orig_formatted} = {converted_formatted} <- BOOK HERE")
                else:
                    print(f"  {market} MARKET: {orig_formatted} = {converted_formatted} (normal price)")

            print(f"  ---")
            print(f"  Your savings:     {format_price(deal['gross_savings'], DISPLAY_CURRENCY)} gross")
            print(f"  Platform fee:    -{format_price(deal['platform_fee_usd'], DISPLAY_CURRENCY)} ({deal['platform_fee_xrp']} XRP)")
            print(f"  YOU SAVE:         {format_price(deal['user_savings'], DISPLAY_CURRENCY)} ({deal['user_saves_pct']}%)")

            # Show currency arbitrage tip if available
            if deal.get('payment_tip'):
                print(f"  ---")
                print(f"  💡 {deal['payment_tip']}")
                if deal.get('currency_analysis'):
                    analysis = deal['currency_analysis']
                    print(f"     Best payment: {analysis['best_currency']} ({analysis['best_market']} market)")
                    if analysis.get('currency_savings_usd', 0) > 0:
                        print(f"     Currency savings: ${analysis['currency_savings_usd']:.2f}")

            print(f"  ---")
            print(f"  Book at: {deal['booking_url']}")
            print(f"  ---")
            print(f"  PAYMENT (Deal ID: {deal['deal_id']}):")
            payment = deal['payment'].get('payment_request', {})
            print(f"    Send {payment.get('amount_xrp')} XRP to: {payment.get('destination')}")
            print(f"    Destination Tag: {payment.get('destination_tag')}")
            print(f"    Network: {payment.get('network', 'testnet').upper()}")

    print("\n" + "="*70)
    print(f"SUMMARY: {len(good_deals)} deals found / {len(comparison)} flights checked")
    print("="*70)

    # Also save full JSON for further analysis
    with open("flight_comparison.json", "w") as f:
        json.dump(comparison, f, indent=2, ensure_ascii=False)
    print("Full results saved to flight_comparison.json")

if __name__ == "__main__":
    run()