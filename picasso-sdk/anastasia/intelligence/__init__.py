"""
Intelligence Neuron — Competitive pricing intelligence for ANASTASiA.

Aggregates anonymized pricing data across all installations to provide
competitive intelligence: price trends, market analysis, anomaly detection,
and price alerts. All data is fully anonymized — no agency IDs, customer
data, or booking references are stored in the aggregation layer.

Components:
    - **PricingAggregator**: Collects and queries anonymized price observations
    - **TrendAnalyzer**: Detects trends, seasonality, anomalies, and predicts prices
    - **AlertEngine**: Creates and monitors price alerts with event-driven notifications

MYSTES KYRIOS LLC — Confidential.
"""

import logging
import os
from typing import Any, Dict, List

from ..core.events import EventBus, Event, EventType
from ..core.registry import NeuronModule

from .aggregator import PricingAggregator
from .trends import TrendAnalyzer
from .alerts import AlertEngine

logger = logging.getLogger(__name__)

__all__ = [
    "IntelligenceModule",
    "PricingAggregator",
    "TrendAnalyzer",
    "AlertEngine",
]


class IntelligenceModule(NeuronModule):
    """
    Intelligence neuron module for ANASTASiA.

    Provides competitive pricing intelligence by aggregating anonymized
    pricing data, analyzing trends and seasonality, detecting anomalies,
    and managing price alerts. Publishes ``PRICE_ALERT`` and ``PRICE_DROP``
    events on the shared event bus.

    No external dependencies — this module operates standalone using
    only data collected through its own ``PricingAggregator``.

    Configuration keys (passed via ``config`` dict):
        - ``intelligence_storage_dir``: Base directory for intelligence data.
          Defaults to ``~/.anastasia/intelligence``.

    Usage:
        from anastasia.intelligence import IntelligenceModule

        module = IntelligenceModule()
        registry.register(module)
        registry.initialize_all(config)

        # Access sub-components after initialization
        module.aggregator.record_price("JFK-LHR", 450.0, "USD", "picasso")
        trend = module.trend_analyzer.analyze_trend("JFK-LHR")
        alert = module.alert_engine.create_alert("agency_1", "JFK-LHR", 400.0)
    """

    def __init__(self):
        self._aggregator: PricingAggregator = None
        self._trend_analyzer: TrendAnalyzer = None
        self._alert_engine: AlertEngine = None
        self._event_bus: EventBus = None
        self._initialized = False

    # ------------------------------------------------------------------
    # NeuronModule interface
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        """Unique module identifier."""
        return "intelligence"

    @property
    def version(self) -> str:
        """Module version."""
        return "1.0.0"

    @property
    def dependencies(self) -> List[str]:
        """No dependencies — intelligence operates standalone."""
        return []

    def initialize(self, event_bus: EventBus, config: Dict[str, Any]) -> None:
        """
        Initialize the intelligence module and wire up all components.

        Creates the PricingAggregator, TrendAnalyzer, and AlertEngine,
        connecting them to the shared event bus. Subscribes to
        ``SEARCH_COMPLETED`` events to automatically record prices from
        search results.

        Args:
            event_bus: Shared event bus for inter-neuron communication.
            config: Configuration dict. Supports key
                    ``intelligence_storage_dir`` for custom data directory.
        """
        self._event_bus = event_bus

        # Resolve storage directories
        base_dir = config.get(
            "intelligence_storage_dir",
            os.path.join(
                os.path.expanduser("~"), ".anastasia", "intelligence"
            ),
        )
        prices_dir = os.path.join(base_dir, "prices")
        alerts_dir = os.path.join(base_dir, "alerts")

        # Initialize components
        self._aggregator = PricingAggregator(
            event_bus=event_bus,
            storage_dir=prices_dir,
        )

        self._trend_analyzer = TrendAnalyzer(
            aggregator=self._aggregator,
        )

        self._alert_engine = AlertEngine(
            event_bus=event_bus,
            storage_dir=alerts_dir,
        )

        # Subscribe to search events to auto-record prices
        event_bus.subscribe(
            EventType.SEARCH_COMPLETED,
            self._handle_search_completed,
        )

        self._initialized = True
        logger.info(
            "Intelligence module initialized (storage: %s)", base_dir
        )

    def health_check(self) -> Dict[str, Any]:
        """
        Return health status of the intelligence module.

        Checks that all three components are initialized and that the
        storage directories are writable.

        Returns:
            Dict with ``healthy`` bool and ``details`` string.
        """
        if not self._initialized:
            return {"healthy": False, "details": "Not initialized"}

        issues = []

        if self._aggregator is None:
            issues.append("PricingAggregator not initialized")
        if self._trend_analyzer is None:
            issues.append("TrendAnalyzer not initialized")
        if self._alert_engine is None:
            issues.append("AlertEngine not initialized")

        # Check storage directory accessibility
        if self._aggregator is not None:
            storage = self._aggregator._storage_dir
            if not storage.exists():
                issues.append(f"Price storage dir missing: {storage}")
            elif not os.access(str(storage), os.W_OK):
                issues.append(f"Price storage dir not writable: {storage}")

        if self._alert_engine is not None:
            storage = self._alert_engine._storage_dir
            if not storage.exists():
                issues.append(f"Alert storage dir missing: {storage}")
            elif not os.access(str(storage), os.W_OK):
                issues.append(f"Alert storage dir not writable: {storage}")

        if issues:
            return {
                "healthy": False,
                "details": "; ".join(issues),
            }

        return {
            "healthy": True,
            "details": "All intelligence components operational",
            "components": {
                "aggregator": "ok",
                "trend_analyzer": "ok",
                "alert_engine": "ok",
            },
        }

    def shutdown(self) -> None:
        """
        Graceful shutdown: flush aggregator cache to disk.
        """
        if self._aggregator is not None:
            self._aggregator.flush()
            logger.info("Intelligence module shut down — data flushed")

        self._initialized = False

    # ------------------------------------------------------------------
    # Public accessors for sub-components
    # ------------------------------------------------------------------

    @property
    def aggregator(self) -> PricingAggregator:
        """Access the PricingAggregator instance."""
        return self._aggregator

    @property
    def trend_analyzer(self) -> TrendAnalyzer:
        """Access the TrendAnalyzer instance."""
        return self._trend_analyzer

    @property
    def alert_engine(self) -> AlertEngine:
        """Access the AlertEngine instance."""
        return self._alert_engine

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _handle_search_completed(self, event: Event) -> None:
        """
        Handle SEARCH_COMPLETED events to auto-record prices.

        Extracts route and pricing data from search result events and
        records anonymized price observations. Expects event data to
        contain ``route`` (str) and ``results`` (list of dicts with
        ``price``, ``currency``, ``source``, and optionally ``cabin``).
        """
        if self._aggregator is None:
            return

        data = event.data
        route = data.get("route")
        results = data.get("results", [])

        if not route or not results:
            return

        recorded = 0
        for result in results:
            price = result.get("price")
            currency = result.get("currency", "USD")
            source = result.get("source", "unknown")
            cabin = result.get("cabin", "economy")

            if price is not None and price > 0:
                try:
                    self._aggregator.record_price(
                        route=route,
                        price=price,
                        currency=currency,
                        source=source,
                        cabin=cabin,
                    )
                    recorded += 1
                except Exception as e:
                    logger.warning(
                        "Failed to record price from search event: %s", e
                    )

        if recorded:
            logger.debug(
                "Auto-recorded %d prices from search event for %s",
                recorded, route,
            )
