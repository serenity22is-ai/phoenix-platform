"""
Proxy Manager — Webshare.io residential proxy integration.

Provides per-market proxy URLs for the Google Flights scraper
and other data collection modules.
"""

import os
import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Market configuration
# ---------------------------------------------------------------------------

MARKET_CONFIG = {
    "US": {"country_code": "US", "timezone": "America/New_York",   "google_domain": "google.com",    "currency": "USD", "language": "en"},
    "GB": {"country_code": "GB", "timezone": "Europe/London",      "google_domain": "google.co.uk",  "currency": "GBP", "language": "en"},
    "DE": {"country_code": "DE", "timezone": "Europe/Berlin",      "google_domain": "google.de",     "currency": "EUR", "language": "de"},
    "FR": {"country_code": "FR", "timezone": "Europe/Paris",       "google_domain": "google.fr",     "currency": "EUR", "language": "fr"},
    "JP": {"country_code": "JP", "timezone": "Asia/Tokyo",         "google_domain": "google.co.jp",  "currency": "JPY", "language": "ja"},
    "AU": {"country_code": "AU", "timezone": "Australia/Sydney",   "google_domain": "google.com.au", "currency": "AUD", "language": "en"},
    "CA": {"country_code": "CA", "timezone": "America/Toronto",    "google_domain": "google.ca",     "currency": "CAD", "language": "en"},
    "BR": {"country_code": "BR", "timezone": "America/Sao_Paulo",  "google_domain": "google.com.br", "currency": "BRL", "language": "pt"},
    "IN": {"country_code": "IN", "timezone": "Asia/Kolkata",       "google_domain": "google.co.in",  "currency": "INR", "language": "en"},
    "KR": {"country_code": "KR", "timezone": "Asia/Seoul",         "google_domain": "google.co.kr",  "currency": "KRW", "language": "ko"},
    "MX": {"country_code": "MX", "timezone": "America/Mexico_City","google_domain": "google.com.mx", "currency": "MXN", "language": "es"},
    "ES": {"country_code": "ES", "timezone": "Europe/Madrid",      "google_domain": "google.es",     "currency": "EUR", "language": "es"},
    "IT": {"country_code": "IT", "timezone": "Europe/Rome",        "google_domain": "google.it",     "currency": "EUR", "language": "it"},
    "NL": {"country_code": "NL", "timezone": "Europe/Amsterdam",   "google_domain": "google.nl",     "currency": "EUR", "language": "nl"},
    "SE": {"country_code": "SE", "timezone": "Europe/Stockholm",   "google_domain": "google.se",     "currency": "SEK", "language": "sv"},
    "TH": {"country_code": "TH", "timezone": "Asia/Bangkok",       "google_domain": "google.co.th",  "currency": "THB", "language": "th"},
    "PL": {"country_code": "PL", "timezone": "Europe/Warsaw",      "google_domain": "google.pl",     "currency": "PLN", "language": "pl"},
}

MARKET_TO_COUNTRY_CODE = {k: v["country_code"] for k, v in MARKET_CONFIG.items()}


def get_proxy_for_market(market: str) -> dict:
    """Return a proxy configuration dict for the given market.

    Uses Webshare.io rotating residential proxies with country targeting.
    Falls back to non-targeted proxy if the market is unknown.

    Returns:
        dict with keys: server, username, password, country_code
    """
    # Check for manual market-specific override in env
    env_key = f"{market.upper()}_PROXY_URL"
    manual_url = os.environ.get(env_key)
    if manual_url:
        parsed = parse_proxy_url(manual_url)
        parsed["country_code"] = market.upper()
        return parsed

    # Use Webshare rotating residential proxy with country targeting
    host = os.environ.get("WEBSHARE_HOST", "p.webshare.io")
    port = os.environ.get("WEBSHARE_HTTP_PORT", "80")
    username = os.environ.get("WEBSHARE_USERNAME", "")
    password = os.environ.get("WEBSHARE_PASSWORD", "")

    if not username or not password:
        logger.warning("Webshare credentials not configured")
        return {"server": "", "username": "", "password": "", "country_code": market.upper()}

    country_code = MARKET_CONFIG.get(market, {}).get("country_code", market.upper())

    # Webshare residential country targeting + rotation
    # Format: username-XX-rotate
    targeted_username = f"{username}-{country_code}-rotate"

    return {
        "server": f"http://{host}:{port}",
        "username": targeted_username,
        "password": password,
        "country_code": country_code,
    }


def get_timezone_for_market(market: str) -> str:
    """Return the timezone string for a given market code."""
    config = MARKET_CONFIG.get(market.upper())
    if config:
        return config["timezone"]
    return "UTC"


def parse_proxy_url(url: str) -> dict:
    """Parse a proxy URL into component parts.

    Supports formats:
        http://user:pass@host:port
        host:port:user:pass
        host:port
    """
    if not url:
        return {"server": "", "username": "", "password": ""}

    # Standard URL format
    if "://" in url:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        return {
            "server": f"{parsed.scheme}://{parsed.hostname}:{parsed.port or 80}",
            "username": parsed.username or "",
            "password": parsed.password or "",
        }

    # host:port:user:pass format
    parts = url.split(":")
    if len(parts) == 4:
        return {
            "server": f"http://{parts[0]}:{parts[1]}",
            "username": parts[2],
            "password": parts[3],
        }
    if len(parts) == 2:
        return {
            "server": f"http://{parts[0]}:{parts[1]}",
            "username": "",
            "password": "",
        }

    return {"server": url, "username": "", "password": ""}


def is_proxy_configured() -> bool:
    """Return True if Webshare proxy credentials are configured."""
    return bool(os.environ.get("WEBSHARE_USERNAME") and os.environ.get("WEBSHARE_PASSWORD"))


def get_all_markets():
    """Return list of all configured market codes."""
    return list(MARKET_CONFIG.keys())


# Module-level convenience
proxy_manager = {
    "get_proxy_for_market": get_proxy_for_market,
    "get_timezone_for_market": get_timezone_for_market,
    "parse_proxy_url": parse_proxy_url,
    "MARKET_CONFIG": MARKET_CONFIG,
    "MARKET_TO_COUNTRY_CODE": MARKET_TO_COUNTRY_CODE,
}
