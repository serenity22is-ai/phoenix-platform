"""
Arbitrage Neuron — POS spread calculation and pricing engine.

The core value proposition of MYSTES: airline prices vary by Point of Sale
(country of the requester). US customers pay the highest prices globally.
This neuron calculates the spread between US retail and foreign POS prices,
applies the user's fee tier, and determines the customer price.

Flow:
    1. GeoIP neuron detects US customer
    2. Proxy neuron provides foreign POS connection
    3. Google Search neuron fetches foreign prices via proxy
    4. US Baseline provider fetches US retail price via SerpAPI
    5. THIS NEURON calculates spread, fee, and customer price
    6. Result displayed in MYSTES UI (no POS codes — airline compliance)

MYSTES KYRIOS LLC — Confidential.
"""

import logging
from typing import Any, Dict, List, Optional

from ..core.events import Event, EventBus, EventType
from ..core.registry import NeuronModule
from .baseline import USBaselineProvider
from .spread import DEFAULT_FX_FEE_PERCENT, MINIMUM_FEE_USD, SpreadCalculator, SpreadResult

logger = logging.getLogger(__name__)

__all__ = [
    "ArbitrageModule",
    "SpreadCalculator",
    "SpreadResult",
    "USBaselineProvider",
    "MINIMUM_FEE_USD",
    "DEFAULT_FX_FEE_PERCENT",
]


class ArbitrageModule(NeuronModule):
    """
    ANASTASiA Arbitrage Neuron — POS pricing engine.

    Provides:
    - Spread calculation (US retail vs foreign POS price)
    - US baseline price lookup via SerpAPI
    - Multi-market best-price selection
    - Fee tier application (sole source: payments.py:get_fee_percent)
    - Display-safe pricing data (no POS codes exposed)
    """

    def __init__(self):
        self._event_bus: Optional[EventBus] = None
        self._calculator: Optional[SpreadCalculator] = None
        self._baseline: Optional[USBaselineProvider] = None
        self._spread_count: int = 0
        self._no_spread_count: int = 0
        self._total_spread_usd: float = 0.0
        self._initialized: bool = False

    @property
    def name(self) -> str:
        return "arbitrage"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def dependencies(self) -> List[str]:
        return ["proxy"]  # Needs proxy for market routing context

    def initialize(self, event_bus: EventBus, config: Dict[str, Any]) -> None:
        self._event_bus = event_bus

        self._calculator = SpreadCalculator()

        # SerpAPI key from config or env
        serpapi_key = config.get("serpapi_key")
        self._baseline = USBaselineProvider(api_key=serpapi_key)

        self._initialized = True
        logger.info(
            "Arbitrage neuron initialized: SerpAPI=%s",
            "configured" if self._baseline.is_configured() else "NOT configured",
        )

    def health_check(self) -> Dict[str, Any]:
        if not self._initialized:
            return {"healthy": False, "details": "Not initialized"}

        return {
            "healthy": True,
            "details": (
                f"Spreads found: {self._spread_count}, "
                f"no spread: {self._no_spread_count}, "
                f"total spread: ${self._total_spread_usd:,.2f}"
            ),
            "serpapi": self._baseline.stats if self._baseline else {},
            "spreads_found": self._spread_count,
            "no_spread": self._no_spread_count,
            "total_spread_usd": round(self._total_spread_usd, 2),
        }

    def shutdown(self) -> None:
        self._initialized = False
        logger.info("Arbitrage neuron shut down")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def calculator(self) -> SpreadCalculator:
        if self._calculator is None:
            raise RuntimeError("ArbitrageModule not initialized")
        return self._calculator

    @property
    def baseline(self) -> USBaselineProvider:
        if self._baseline is None:
            raise RuntimeError("ArbitrageModule not initialized")
        return self._baseline

    def calculate_spread(
        self,
        us_retail_price: float,
        foreign_pos_price: float,
        foreign_market: str,
        fee_percent: float,
    ) -> SpreadResult:
        """Calculate spread for a single market comparison.

        This is the primary entry point for pricing. The MYSTES template
        layer calls this after obtaining prices from proxy search and
        SerpAPI baseline.

        Args:
            us_retail_price: US retail price from SerpAPI
            foreign_pos_price: Foreign POS price from proxy search
            foreign_market: ISO code (e.g., "DK") — INTERNAL ONLY, never shown to user
            fee_percent: From payments.py:get_fee_percent(user)

        Returns:
            SpreadResult with full pricing breakdown
        """
        result = self._calculator.calculate(
            us_retail_price, foreign_pos_price, foreign_market, fee_percent
        )

        # Track metrics
        if result.has_arbitrage:
            self._spread_count += 1
            self._total_spread_usd += result.spread
        else:
            self._no_spread_count += 1

        # Publish event
        if self._event_bus:
            event_type = (
                EventType.ARBITRAGE_SPREAD_FOUND
                if result.has_arbitrage
                else EventType.ARBITRAGE_NO_SPREAD
            )
            self._event_bus.publish(Event(
                type=event_type,
                source="arbitrage",
                data={
                    "spread": result.spread,
                    "fee": result.service_fee,
                    "savings_percent": result.savings_percent,
                    "market": foreign_market,
                },
            ))

        return result

    def calculate_best_spread(
        self,
        us_retail_price: float,
        market_prices: Dict[str, float],
        fee_percent: float,
    ) -> Optional[SpreadResult]:
        """Calculate spread across multiple markets, return best.

        Used when the proxy neuron queries multiple POS markets in parallel.
        Returns the result with the highest customer savings.

        Args:
            us_retail_price: US retail from SerpAPI
            market_prices: {market_code: price_usd}
            fee_percent: From payments.py:get_fee_percent(user)

        Returns:
            Best SpreadResult or None if no arbitrage found
        """
        result = self._calculator.calculate_multi_market(
            us_retail_price, market_prices, fee_percent
        )

        if result and result.has_arbitrage:
            self._spread_count += 1
            self._total_spread_usd += result.spread

            if self._event_bus:
                self._event_bus.publish(Event(
                    type=EventType.ARBITRAGE_SPREAD_FOUND,
                    source="arbitrage",
                    data={
                        "spread": result.spread,
                        "fee": result.service_fee,
                        "savings_percent": result.savings_percent,
                        "market": result.foreign_market,
                        "markets_checked": len(market_prices),
                    },
                ))
        else:
            self._no_spread_count += 1

        return result

    def get_us_baseline(
        self,
        origin: str,
        destination: str,
        departure_date: str,
        return_date: Optional[str] = None,
        cabin_class: str = "economy",
    ) -> Optional[Dict[str, Any]]:
        """Fetch US retail price via SerpAPI.

        This is the price ceiling for spread calculation.

        Returns:
            {"price_usd": 1400.0, "airline": "...", "stops": 0, ...}
            or None if lookup fails.
        """
        result = self._baseline.get_us_baseline(
            origin, destination, departure_date, return_date, cabin_class
        )

        if result and self._event_bus:
            self._event_bus.publish(Event(
                type=EventType.ARBITRAGE_BASELINE_FETCHED,
                source="arbitrage",
                data={
                    "origin": origin,
                    "destination": destination,
                    "price_usd": result.get("price_usd"),
                    "cached": result.get("cached", False),
                },
            ))

        return result

    def full_arbitrage_check(
        self,
        origin: str,
        destination: str,
        departure_date: str,
        market_prices: Dict[str, float],
        fee_percent: float,
        return_date: Optional[str] = None,
        cabin_class: str = "economy",
    ) -> Optional[SpreadResult]:
        """Complete arbitrage check: fetch US baseline + calculate best spread.

        Convenience method that combines baseline lookup and spread calculation.

        Args:
            origin: IATA code
            destination: IATA code
            departure_date: YYYY-MM-DD
            market_prices: {market_code: price_usd} from proxy searches
            fee_percent: From get_fee_percent(user)
            return_date: Optional
            cabin_class: economy/business/first

        Returns:
            Best SpreadResult or None
        """
        baseline = self.get_us_baseline(
            origin, destination, departure_date, return_date, cabin_class
        )

        if not baseline or not baseline.get("price_usd"):
            logger.info(
                "No US baseline for %s→%s on %s",
                origin, destination, departure_date,
            )
            return None

        return self.calculate_best_spread(
            us_retail_price=baseline["price_usd"],
            market_prices=market_prices,
            fee_percent=fee_percent,
        )
