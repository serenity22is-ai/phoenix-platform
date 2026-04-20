"""
Google Search Neuron — Unified Google Flights + Hotels search engine.

Wraps the Google Flights and Hotels scrapers as an ANASTASiA neuron,
providing a unified search interface that the MYSTES template layer
renders seamlessly in the UI.

Architecture:
- GoogleFlightsScraper: Playwright + proxy → Google Flights DOM extraction
- GoogleHotelsScraper: Playwright + proxy → Google Hotels DOM extraction
- GoogleSearchModule: NeuronModule interface, coordinates with Proxy neuron

The MYSTES UI renders ALL search results — user never sees Google directly.
This neuron provides structured data; the template layer controls the UX.

Two search modes:
1. Live user search: User enters route → this neuron scrapes through proxy
   → returns structured JSON → MYSTES UI renders results
2. Cache warming: Background cron scrapes top 200 routes → results cached
   → subsequent user searches hit cache (zero proxy cost)

MYSTES KYRIOS LLC — Confidential.
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional

from ..core.events import Event, EventBus, EventType
from ..core.registry import NeuronModule
from .flights import (
    CURRENCY_RATES_TO_USD,
    GOOGLE_FLIGHTS_MARKETS,
    GoogleFlightsScraper,
    build_flights_url,
)
from .hotels import GoogleHotelsScraper, build_hotels_url

logger = logging.getLogger(__name__)

__all__ = [
    "GoogleSearchModule",
    "GoogleFlightsScraper",
    "GoogleHotelsScraper",
    "GOOGLE_FLIGHTS_MARKETS",
    "CURRENCY_RATES_TO_USD",
    "build_flights_url",
    "build_hotels_url",
]


class GoogleSearchModule(NeuronModule):
    """
    ANASTASiA Google Search Neuron — unified flights + hotels via Google.

    Provides:
    - Google Flights scraping with multi-POS support
    - Google Hotels scraping with multi-POS support
    - Bundled search (flights + hotels for same trip)
    - Integration with Proxy neuron for country-targeted IPs
    - Structured data output for MYSTES UI rendering
    """

    def __init__(self):
        self._event_bus: Optional[EventBus] = None
        self._flights_scraper: Optional[GoogleFlightsScraper] = None
        self._hotels_scraper: Optional[GoogleHotelsScraper] = None
        self._flight_searches: int = 0
        self._hotel_searches: int = 0
        self._initialized: bool = False

    @property
    def name(self) -> str:
        return "google_search"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def dependencies(self) -> List[str]:
        return ["proxy"]  # Needs proxy for country-targeted search

    def initialize(self, event_bus: EventBus, config: Dict[str, Any]) -> None:
        self._event_bus = event_bus
        self._flights_scraper = GoogleFlightsScraper()
        self._hotels_scraper = GoogleHotelsScraper()
        self._initialized = True
        logger.info(
            "Google Search neuron initialized: %d flight markets, hotels enabled",
            len(GOOGLE_FLIGHTS_MARKETS),
        )

    def health_check(self) -> Dict[str, Any]:
        if not self._initialized:
            return {"healthy": False, "details": "Not initialized"}

        return {
            "healthy": True,
            "details": (
                f"Flights: {self._flight_searches} searches, "
                f"Hotels: {self._hotel_searches} searches"
            ),
            "markets": len(GOOGLE_FLIGHTS_MARKETS),
            "flight_searches": self._flight_searches,
            "hotel_searches": self._hotel_searches,
        }

    def shutdown(self) -> None:
        self._initialized = False
        logger.info("Google Search neuron shut down")

    # ------------------------------------------------------------------
    # Flights API
    # ------------------------------------------------------------------

    async def search_flights(
        self,
        origin: str,
        destination: str,
        date: str,
        market: str,
        proxy_config: Optional[Dict] = None,
        cdp_url: Optional[str] = None,
        return_date: Optional[str] = None,
        timezone: str = "UTC",
    ) -> Dict[str, Any]:
        """Search Google Flights for a single market.

        Args:
            origin: IATA code
            destination: IATA code
            date: YYYY-MM-DD
            market: ISO country code (determines POS pricing)
            proxy_config: From Proxy neuron's get_proxy()
            cdp_url: From Proxy neuron's get_scraping_browser_url()
            return_date: Optional return date
            timezone: Browser timezone for fingerprint

        Returns:
            Structured flight results for MYSTES UI rendering
        """
        if not self._flights_scraper:
            raise RuntimeError("GoogleSearchModule not initialized")

        market_config = GOOGLE_FLIGHTS_MARKETS.get(market, {})
        result = await self._flights_scraper.scrape_market(
            origin=origin,
            destination=destination,
            date=date,
            market=market,
            proxy_config=proxy_config,
            cdp_url=cdp_url,
            timezone=timezone,
            locale=market_config.get("hl", "en"),
            return_date=return_date,
        )

        self._flight_searches += 1

        if self._event_bus:
            self._event_bus.publish(Event(
                type=EventType.SEARCH_COMPLETED,
                source="google_search",
                data={
                    "vertical": "flights",
                    "market": market,
                    "results": len(result.get("flights", [])),
                    "success": result.get("success", False),
                },
            ))

        return result

    async def search_flights_multi_market(
        self,
        origin: str,
        destination: str,
        date: str,
        markets: List[str],
        proxy_configs: Optional[Dict[str, Dict]] = None,
        max_concurrent: int = 3,
        return_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Search Google Flights across multiple POS markets in parallel.

        Returns combined results with cross-market price comparison.
        """
        if not self._flights_scraper:
            raise RuntimeError("GoogleSearchModule not initialized")

        result = await self._flights_scraper.scrape_multiple_markets(
            origin=origin,
            destination=destination,
            date=date,
            markets=markets,
            proxy_configs=proxy_configs,
            max_concurrent=max_concurrent,
            return_date=return_date,
        )

        self._flight_searches += len(markets)
        return result

    # ------------------------------------------------------------------
    # Hotels API
    # ------------------------------------------------------------------

    async def search_hotels(
        self,
        destination: str,
        check_in: str,
        check_out: str,
        market: str,
        proxy_config: Optional[Dict] = None,
        cdp_url: Optional[str] = None,
        guests: int = 2,
        timezone: str = "UTC",
    ) -> Dict[str, Any]:
        """Search Google Hotels for a single market.

        Args:
            destination: City/area name
            check_in: YYYY-MM-DD
            check_out: YYYY-MM-DD
            market: ISO country code
            proxy_config: From Proxy neuron
            cdp_url: Scraping Browser URL
            guests: Number of guests
            timezone: Browser timezone

        Returns:
            Structured hotel results for MYSTES UI rendering
        """
        if not self._hotels_scraper:
            raise RuntimeError("GoogleSearchModule not initialized")

        result = await self._hotels_scraper.scrape_market(
            destination=destination,
            check_in=check_in,
            check_out=check_out,
            market=market,
            proxy_config=proxy_config,
            cdp_url=cdp_url,
            guests=guests,
            timezone=timezone,
        )

        self._hotel_searches += 1

        if self._event_bus:
            self._event_bus.publish(Event(
                type=EventType.SEARCH_COMPLETED,
                source="google_search",
                data={
                    "vertical": "hotels",
                    "market": market,
                    "results": len(result.get("hotels", [])),
                    "success": result.get("success", False),
                },
            ))

        return result

    async def search_hotels_multi_market(
        self,
        destination: str,
        check_in: str,
        check_out: str,
        markets: List[str],
        proxy_configs: Optional[Dict[str, Dict]] = None,
        max_concurrent: int = 3,
    ) -> Dict[str, Any]:
        """Search Google Hotels across multiple POS markets."""
        if not self._hotels_scraper:
            raise RuntimeError("GoogleSearchModule not initialized")

        result = await self._hotels_scraper.scrape_multiple_markets(
            destination=destination,
            check_in=check_in,
            check_out=check_out,
            markets=markets,
            proxy_configs=proxy_configs,
            max_concurrent=max_concurrent,
        )

        self._hotel_searches += len(markets)
        return result

    # ------------------------------------------------------------------
    # Bundled Search (Flights + Hotels)
    # ------------------------------------------------------------------

    async def search_trip(
        self,
        origin: str,
        destination_city: str,
        destination_airport: str,
        departure_date: str,
        return_date: str,
        markets: List[str],
        proxy_configs: Optional[Dict[str, Dict]] = None,
        guests: int = 2,
    ) -> Dict[str, Any]:
        """Search flights AND hotels for a complete trip.

        Runs both searches in parallel for the same destination and
        POS markets. Returns bundled results for the MYSTES trip builder.

        Args:
            origin: IATA code (e.g., "LAX")
            destination_city: City name for hotels (e.g., "Barcelona")
            destination_airport: IATA code for flights (e.g., "BCN")
            departure_date: YYYY-MM-DD
            return_date: YYYY-MM-DD
            markets: POS markets to check
            proxy_configs: {market: proxy_config}
            guests: Number of guests

        Returns:
            {
                "flights": {multi-market flight results},
                "hotels": {multi-market hotel results},
                "cheapest_flight_market": "DK",
                "cheapest_hotel_market": "PL",
                "bundle_savings_usd": 450.00,
            }
        """
        # Run flights and hotels searches in parallel
        flights_task = self.search_flights_multi_market(
            origin=origin,
            destination=destination_airport,
            date=departure_date,
            markets=markets,
            proxy_configs=proxy_configs,
            return_date=return_date,
        )
        hotels_task = self.search_hotels_multi_market(
            destination=destination_city,
            check_in=departure_date,
            check_out=return_date,
            markets=markets,
            proxy_configs=proxy_configs,
        )

        flights_result, hotels_result = await asyncio.gather(
            flights_task, hotels_task, return_exceptions=True
        )

        if isinstance(flights_result, Exception):
            flights_result = {"error": str(flights_result), "price_comparison": []}
        if isinstance(hotels_result, Exception):
            hotels_result = {"error": str(hotels_result), "price_comparison": []}

        # Calculate bundle savings
        us_flight = next(
            (p for p in flights_result.get("price_comparison", []) if p["market"] == "US"),
            None,
        )
        us_hotel = next(
            (p for p in hotels_result.get("price_comparison", []) if p["market"] == "US"),
            None,
        )
        cheapest_flight = flights_result.get("price_comparison", [None])[0] if flights_result.get("price_comparison") else None
        cheapest_hotel = hotels_result.get("price_comparison", [None])[0] if hotels_result.get("price_comparison") else None

        bundle_savings = 0.0
        if us_flight and cheapest_flight:
            bundle_savings += us_flight["price_usd"] - cheapest_flight["price_usd"]
        if us_hotel and cheapest_hotel:
            bundle_savings += us_hotel["price_usd"] - cheapest_hotel["price_usd"]

        return {
            "flights": flights_result,
            "hotels": hotels_result,
            "cheapest_flight_market": flights_result.get("cheapest_market"),
            "cheapest_hotel_market": hotels_result.get("cheapest_market"),
            "bundle_savings_usd": round(max(0, bundle_savings), 2),
        }
