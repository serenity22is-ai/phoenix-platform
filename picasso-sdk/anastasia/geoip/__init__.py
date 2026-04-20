"""
GeoIP Neuron — Customer location detection and arbitrage routing.

Determines customer's country from IP address to route them to the
correct search pipeline:
- US customers → POS arbitrage pipeline (proxy search + spread calc)
- Non-US customers → standard API pipeline (Duffel/Picasso, zero proxy cost)

Detection methods (in priority order):
1. Cloudflare CF-IPCountry header (free, no database needed)
2. X-Forwarded-For + MaxMind GeoLite2 (self-hosted fallback)
3. Direct IP + MaxMind (development mode)

MYSTES KYRIOS LLC — Confidential.
"""

import logging
import os
from typing import Any, Dict, List, Optional, Set

from ..core.events import Event, EventBus, EventType
from ..core.registry import NeuronModule
from .detector import GeoDetector

logger = logging.getLogger(__name__)

__all__ = ["GeoIPModule", "GeoDetector"]


class GeoIPModule(NeuronModule):
    """
    ANASTASiA GeoIP Neuron — customer geolocation and pipeline routing.

    Provides:
    - Country detection from HTTP request
    - Arbitrage eligibility check (Phase 1: US only)
    - Expandable to multi-country arbitrage markets
    """

    def __init__(self):
        self._event_bus: Optional[EventBus] = None
        self._detector: Optional[GeoDetector] = None
        self._arbitrage_countries: Set[str] = set()
        self._detection_count: int = 0
        self._arbitrage_eligible_count: int = 0
        self._initialized: bool = False

    @property
    def name(self) -> str:
        return "geoip"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def dependencies(self) -> List[str]:
        return []  # Foundational

    def initialize(self, event_bus: EventBus, config: Dict[str, Any]) -> None:
        self._event_bus = event_bus

        # Detection mode from config or env
        mode = config.get(
            "geoip_mode",
            os.environ.get("GEOIP_MODE", "cloudflare"),
        )

        # MaxMind database path (optional, for non-Cloudflare mode)
        db_path = config.get(
            "geoip_db_path",
            os.environ.get("GEOIP_DB_PATH"),
        )

        self._detector = GeoDetector(mode=mode, db_path=db_path)

        # Countries eligible for POS arbitrage
        # Phase 1: US only. Phase 3: expand to UK, AU, CA.
        arbitrage_raw = config.get(
            "geoip_arbitrage_countries",
            os.environ.get("GEOIP_ARBITRAGE_COUNTRIES", "US"),
        )
        # Accept list (from config dict) or comma-separated string (from env)
        if isinstance(arbitrage_raw, list):
            self._arbitrage_countries = {c.strip().upper() for c in arbitrage_raw if c.strip()}
        else:
            self._arbitrage_countries = {
                c.strip().upper()
                for c in str(arbitrage_raw).split(",")
                if c.strip()
            }

        self._initialized = True
        logger.info(
            "GeoIP neuron initialized: mode=%s, arbitrage_countries=%s",
            mode,
            self._arbitrage_countries,
        )

    def health_check(self) -> Dict[str, Any]:
        if not self._initialized:
            return {"healthy": False, "details": "Not initialized"}

        return {
            "healthy": True,
            "details": f"Mode: {self._detector.mode}, "
                       f"arbitrage countries: {self._arbitrage_countries}",
            "mode": self._detector.mode,
            "arbitrage_countries": sorted(self._arbitrage_countries),
            "detections": self._detection_count,
            "arbitrage_eligible": self._arbitrage_eligible_count,
        }

    def shutdown(self) -> None:
        self._initialized = False
        logger.info("GeoIP neuron shut down")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def detect_country(self, request_headers: Dict[str, str], remote_addr: str = "") -> str:
        """Detect customer's country from request.

        Args:
            request_headers: HTTP headers dict (case-insensitive keys)
            remote_addr: Client IP address (for MaxMind fallback)

        Returns:
            ISO 3166-1 alpha-2 country code (e.g., "US", "GB")
            Returns "XX" if detection fails.
        """
        if not self._initialized or not self._detector:
            return "XX"

        country = self._detector.detect(request_headers, remote_addr)
        self._detection_count += 1

        if self._event_bus:
            self._event_bus.publish(Event(
                type=EventType.GEOIP_COUNTRY_DETECTED,
                source="geoip",
                data={"country": country, "method": self._detector.mode},
            ))

        return country

    def should_use_arbitrage(self, country: str) -> bool:
        """Check if a customer's country is eligible for POS arbitrage.

        Phase 1: US only — US customers get proxy-arbitraged pricing.
        Non-US customers get standard Duffel/Picasso pricing (zero proxy cost).

        Args:
            country: ISO country code from detect_country()

        Returns:
            True if customer should use the arbitrage pipeline.
        """
        eligible = country.upper() in self._arbitrage_countries
        if eligible:
            self._arbitrage_eligible_count += 1

            if self._event_bus:
                self._event_bus.publish(Event(
                    type=EventType.GEOIP_ARBITRAGE_ELIGIBLE,
                    source="geoip",
                    data={"country": country},
                ))

        return eligible

    def detect_and_route(
        self, request_headers: Dict[str, str], remote_addr: str = ""
    ) -> Dict[str, Any]:
        """Convenience: detect country and determine routing in one call.

        Returns:
            {
                "country": "US",
                "use_arbitrage": True,
                "pipeline": "arbitrage" | "standard"
            }
        """
        country = self.detect_country(request_headers, remote_addr)
        use_arb = self.should_use_arbitrage(country)
        return {
            "country": country,
            "use_arbitrage": use_arb,
            "pipeline": "arbitrage" if use_arb else "standard",
        }

    def add_arbitrage_country(self, country: str) -> None:
        """Add a country to the arbitrage-eligible set (runtime expansion)."""
        self._arbitrage_countries.add(country.upper())
        logger.info("Added arbitrage country: %s", country.upper())

    def remove_arbitrage_country(self, country: str) -> None:
        """Remove a country from the arbitrage-eligible set."""
        self._arbitrage_countries.discard(country.upper())
        logger.info("Removed arbitrage country: %s", country.upper())
