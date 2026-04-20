"""
Proxy Providers — Multi-vendor proxy abstraction for POS arbitrage.

Supported providers:
- Bright Data (PRIMARY): Residential proxy + Scraping Browser CDP
- Webshare.io (FALLBACK): Residential proxy only

Each provider implements country-targeted proxy routing for POS arbitrage.
The ProxyProvider ABC ensures consistent interface across vendors.

MYSTES KYRIOS LLC — Confidential.
"""

import logging
import os
from abc import ABC, abstractmethod
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class ProxyProvider(ABC):
    """Abstract base for proxy vendor integrations."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Vendor identifier."""
        ...

    @abstractmethod
    def is_configured(self) -> bool:
        """Return True if credentials are present."""
        ...

    @abstractmethod
    def get_proxy(self, market: str) -> Dict[str, str]:
        """Return proxy config for a market.

        Returns:
            dict with keys: server, username, password, country_code
        """
        ...

    @abstractmethod
    def supports_scraping_browser(self) -> bool:
        """Return True if provider supports CDP Scraping Browser."""
        ...

    def get_scraping_browser_url(self, market: str) -> str:
        """Return CDP WebSocket URL for Playwright connect_over_cdp().

        Raises NotImplementedError if provider doesn't support it.
        """
        raise NotImplementedError(
            f"{self.name} does not support Scraping Browser CDP"
        )


class BrightDataProvider(ProxyProvider):
    """
    Bright Data residential proxy + Scraping Browser.

    Residential proxy: 150M+ IPs, 195 countries, country targeting.
    Scraping Browser: Hosted headless Chrome via CDP, auto CAPTCHA solving,
    fingerprint randomization, sticky sessions (entire browser lifetime).

    Env vars:
        BRIGHTDATA_USERNAME  — Zone username (e.g., brd-customer-xxx-zone-residential)
        BRIGHTDATA_PASSWORD  — Zone password
        BRIGHTDATA_HOST      — Proxy host (default: brd.superproxy.io)
        BRIGHTDATA_PORT      — Proxy port (default: 22225)
        BRIGHTDATA_SB_HOST   — Scraping Browser host (default: brd.superproxy.io)
        BRIGHTDATA_SB_PORT   — Scraping Browser port (default: 9222)
    """

    def __init__(self):
        self._username = os.environ.get("BRIGHTDATA_USERNAME", "")
        self._password = os.environ.get("BRIGHTDATA_PASSWORD", "")
        self._host = os.environ.get("BRIGHTDATA_HOST", "brd.superproxy.io")
        self._port = int(os.environ.get("BRIGHTDATA_PORT", "22225"))
        self._sb_host = os.environ.get("BRIGHTDATA_SB_HOST", "brd.superproxy.io")
        self._sb_port = int(os.environ.get("BRIGHTDATA_SB_PORT", "9222"))

    @property
    def name(self) -> str:
        return "brightdata"

    def is_configured(self) -> bool:
        return bool(self._username and self._password)

    def supports_scraping_browser(self) -> bool:
        return True

    def get_proxy(self, market: str) -> Dict[str, str]:
        """Return Bright Data residential proxy for a country.

        Country targeting format: username-country-{cc}
        The proxy automatically rotates IPs within the target country.
        """
        if not self.is_configured():
            logger.warning("Bright Data credentials not configured")
            return {
                "server": "",
                "username": "",
                "password": "",
                "country_code": market.upper(),
            }

        country = market.lower()
        targeted_user = f"{self._username}-country-{country}"

        return {
            "server": f"http://{self._host}:{self._port}",
            "username": targeted_user,
            "password": self._password,
            "country_code": market.upper(),
        }

    def get_scraping_browser_url(self, market: str) -> str:
        """Return CDP WebSocket URL for Scraping Browser.

        Connect via: playwright.chromium.connect_over_cdp(url)

        Features:
        - Sticky session (entire browser lifetime on same IP)
        - Auto CAPTCHA solving (hCaptcha, reCAPTCHA, Cloudflare)
        - Fingerprint randomization (canvas, WebGL, fonts)
        - Country-targeted residential IP for POS pricing
        """
        if not self.is_configured():
            raise RuntimeError("Bright Data credentials not configured")

        country = market.lower()
        return (
            f"wss://{self._username}-country-{country}"
            f":{self._password}"
            f"@{self._sb_host}:{self._sb_port}"
        )

    def get_proxy_url(self, market: str) -> str:
        """Return full proxy URL string for requests/httpx."""
        if not self.is_configured():
            raise RuntimeError("Bright Data credentials not configured")

        country = market.lower()
        targeted_user = f"{self._username}-country-{country}"
        return (
            f"http://{targeted_user}:{self._password}"
            f"@{self._host}:{self._port}"
        )


class WebshareProvider(ProxyProvider):
    """
    Webshare.io residential proxy (FALLBACK).

    17-market residential proxy with country targeting and rotation.
    Does NOT support Scraping Browser CDP.

    Env vars:
        WEBSHARE_USERNAME — Proxy username
        WEBSHARE_PASSWORD — Proxy password
        WEBSHARE_HOST     — Proxy host (default: p.webshare.io)
        WEBSHARE_HTTP_PORT — Proxy port (default: 80)
    """

    def __init__(self):
        self._username = os.environ.get("WEBSHARE_USERNAME", "")
        self._password = os.environ.get("WEBSHARE_PASSWORD", "")
        self._host = os.environ.get("WEBSHARE_HOST", "p.webshare.io")
        self._port = os.environ.get("WEBSHARE_HTTP_PORT", "80")

    @property
    def name(self) -> str:
        return "webshare"

    def is_configured(self) -> bool:
        return bool(self._username and self._password)

    def supports_scraping_browser(self) -> bool:
        return False

    def get_proxy(self, market: str) -> Dict[str, str]:
        """Return Webshare residential proxy for a country.

        Country targeting format: username-{CC}-rotate
        """
        if not self.is_configured():
            logger.warning("Webshare credentials not configured")
            return {
                "server": "",
                "username": "",
                "password": "",
                "country_code": market.upper(),
            }

        country_code = market.upper()
        targeted_user = f"{self._username}-{country_code}-rotate"

        return {
            "server": f"http://{self._host}:{self._port}",
            "username": targeted_user,
            "password": self._password,
            "country_code": country_code,
        }


__all__ = ["ProxyProvider", "BrightDataProvider", "WebshareProvider"]
