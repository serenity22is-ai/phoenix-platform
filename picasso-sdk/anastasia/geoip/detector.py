"""
GeoIP Detector — Country detection from IP addresses.

Supports multiple detection backends:
- cloudflare: Reads CF-IPCountry header (zero cost, production default)
- maxmind: Uses MaxMind GeoLite2 database (self-hosted fallback)
- header: Reads X-Country-Code header (for testing/load balancer)

MYSTES KYRIOS LLC — Confidential.
"""

import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class GeoDetector:
    """Detects country from HTTP request metadata."""

    def __init__(self, mode: str = "cloudflare", db_path: Optional[str] = None):
        """
        Args:
            mode: Detection method — "cloudflare", "maxmind", or "header"
            db_path: Path to MaxMind GeoLite2-Country.mmdb (required for maxmind mode)
        """
        self._mode = mode
        self._db_path = db_path
        self._reader = None

        if mode == "maxmind" and db_path:
            try:
                import geoip2.database
                self._reader = geoip2.database.Reader(db_path)
                logger.info("MaxMind GeoLite2 loaded from %s", db_path)
            except ImportError:
                logger.warning(
                    "geoip2 package not installed. "
                    "Run: pip install geoip2. Falling back to header mode."
                )
                self._mode = "header"
            except Exception as e:
                logger.error("Failed to load MaxMind database: %s", e)
                self._mode = "header"

    @property
    def mode(self) -> str:
        return self._mode

    def detect(self, headers: Dict[str, str], remote_addr: str = "") -> str:
        """Detect country from request context.

        Args:
            headers: HTTP headers (case-insensitive lookup)
            remote_addr: Client IP address

        Returns:
            ISO 3166-1 alpha-2 country code, or "XX" if unknown.
        """
        # Normalize headers to lowercase keys
        h = {k.lower(): v for k, v in headers.items()}

        if self._mode == "cloudflare":
            return self._detect_cloudflare(h)
        elif self._mode == "maxmind":
            return self._detect_maxmind(h, remote_addr)
        elif self._mode == "header":
            return self._detect_header(h)
        else:
            logger.warning("Unknown GeoIP mode: %s", self._mode)
            return "XX"

    def _detect_cloudflare(self, headers: Dict[str, str]) -> str:
        """Read Cloudflare CF-IPCountry header.

        Cloudflare sets this header on every request when proxying.
        Values: ISO country code, "T1" for Tor, "XX" for unknown.
        Free tier — no configuration needed beyond DNS setup.
        """
        country = headers.get("cf-ipcountry", "").upper()
        if country and country not in ("T1", "XX", ""):
            return country

        # Fallback: check X-Forwarded-For chain for Cloudflare
        # (shouldn't be needed if CF is configured correctly)
        return self._detect_header(headers)

    def _detect_maxmind(self, headers: Dict[str, str], remote_addr: str) -> str:
        """Look up IP in MaxMind GeoLite2 database."""
        if not self._reader:
            return self._detect_header(headers)

        # Get the real client IP
        ip = self._get_client_ip(headers, remote_addr)
        if not ip:
            return "XX"

        try:
            response = self._reader.country(ip)
            country = response.country.iso_code
            return country.upper() if country else "XX"
        except Exception as e:
            logger.debug("MaxMind lookup failed for %s: %s", ip, e)
            return "XX"

    def _detect_header(self, headers: Dict[str, str]) -> str:
        """Read from custom header (testing / load balancer mode)."""
        # Check common country headers
        for header_name in (
            "x-country-code",
            "x-geo-country",
            "x-client-geo-location",
            "cf-ipcountry",
        ):
            value = headers.get(header_name, "").upper()
            if value and len(value) == 2 and value.isalpha():
                return value

        return "XX"

    def _get_client_ip(self, headers: Dict[str, str], remote_addr: str) -> str:
        """Extract real client IP from request.

        Handles proxy chains (X-Forwarded-For, X-Real-IP).
        """
        # X-Forwarded-For: client, proxy1, proxy2
        xff = headers.get("x-forwarded-for", "")
        if xff:
            # First IP in chain is the client
            client_ip = xff.split(",")[0].strip()
            if client_ip:
                return client_ip

        # X-Real-IP (single IP, set by reverse proxy)
        xri = headers.get("x-real-ip", "")
        if xri:
            return xri.strip()

        return remote_addr

    def close(self) -> None:
        """Close MaxMind database reader."""
        if self._reader:
            self._reader.close()
            self._reader = None


__all__ = ["GeoDetector"]
