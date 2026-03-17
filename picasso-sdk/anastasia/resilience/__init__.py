"""
Resilience Neuron — Graceful degradation for ANASTASiA.

When APIs go down, connections fail, or services degrade, the resilience
neuron ensures ANASTASiA doesn't crash. Instead she:

  - **Circuit breaks** failing services to prevent cascading failures.
  - **Falls back** to cached results or alternative data sources.
  - **Queues** work (especially bookings) for retry when services recover.
  - **Monitors** dependency health continuously and publishes status changes.

This module is dependency-free within ANASTASiA (it initializes first) so
it can protect every other neuron.

Usage::

    from anastasia.resilience import (
        ResilienceModule,
        CircuitBreaker,
        FallbackManager,
        BookingQueue,
        HealthMonitor,
    )

MYSTES KYRIOS LLC — Confidential.
"""

import logging
import os
from typing import Any, Dict

from ..core.events import EventBus
from ..core.registry import NeuronModule

from .circuit_breaker import CircuitBreaker, CircuitBreakerRegistry, CircuitOpenError
from .fallback import FallbackManager
from .health import (
    HealthMonitor,
    http_health_check,
    database_health_check,
    redis_health_check,
)
from .queue import BookingQueue

logger = logging.getLogger(__name__)

__all__ = [
    "ResilienceModule",
    "CircuitBreaker",
    "CircuitBreakerRegistry",
    "CircuitOpenError",
    "FallbackManager",
    "BookingQueue",
    "HealthMonitor",
    "http_health_check",
    "database_health_check",
    "redis_health_check",
]


# ---------------------------------------------------------------------------
# ResilienceModule — NeuronModule subclass
# ---------------------------------------------------------------------------

class ResilienceModule(NeuronModule):
    """
    ANASTASiA neuron that wires together all resilience components.

    Initializes and exposes:
      - ``circuit_registry`` — :class:`CircuitBreakerRegistry`
      - ``fallback_manager`` — :class:`FallbackManager`
      - ``booking_queue``   — :class:`BookingQueue`
      - ``health_monitor``  — :class:`HealthMonitor`

    The health monitor's background thread starts on ``initialize()``
    and stops on ``shutdown()``.
    """

    @property
    def name(self) -> str:
        return "resilience"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def dependencies(self):
        # Resilience has no dependencies — it protects everything else.
        return []

    def __init__(self):
        self._event_bus: EventBus = None
        self.circuit_registry: CircuitBreakerRegistry = None
        self.fallback_manager: FallbackManager = None
        self.booking_queue: BookingQueue = None
        self.health_monitor: HealthMonitor = None

    def initialize(self, event_bus: EventBus, config: Dict[str, Any]) -> None:
        """
        Set up all resilience components.

        Config keys (all optional):
          - ``resilience_cache_dir`` — fallback cache directory
            (default: ``<data_dir>/resilience/cache``).
          - ``resilience_cache_ttl`` — default cache TTL in seconds
            (default: 3600).
          - ``resilience_cache_max_bytes`` — max cache size in bytes
            (default: 100 MB).
          - ``resilience_queue_dir`` — booking queue storage directory
            (default: ``<data_dir>/resilience/queue``).
          - ``resilience_queue_max_size`` — max queue items
            (default: 1000).
          - ``resilience_health_interval`` — health check interval in
            seconds (default: 30).
          - ``data_dir`` — base data directory (default: ``.anastasia``
            in current working directory).
        """
        self._event_bus = event_bus

        data_dir = config.get("data_dir", ".anastasia")

        # --- Circuit Breaker Registry ---
        self.circuit_registry = CircuitBreakerRegistry(event_bus=event_bus)

        # --- Fallback Manager ---
        cache_dir = config.get(
            "resilience_cache_dir",
            os.path.join(data_dir, "resilience", "cache"),
        )
        cache_ttl = config.get("resilience_cache_ttl", 3600)
        cache_max = config.get("resilience_cache_max_bytes", 100 * 1024 * 1024)

        self.fallback_manager = FallbackManager(
            event_bus=event_bus,
            cache_dir=cache_dir,
            cache_ttl=cache_ttl,
            max_cache_bytes=cache_max,
        )

        # --- Booking Queue ---
        queue_dir = config.get(
            "resilience_queue_dir",
            os.path.join(data_dir, "resilience", "queue"),
        )
        queue_max = config.get("resilience_queue_max_size", 1000)

        self.booking_queue = BookingQueue(
            event_bus=event_bus,
            storage_dir=queue_dir,
            max_size=queue_max,
        )

        # --- Health Monitor ---
        health_interval = config.get("resilience_health_interval", 30.0)

        self.health_monitor = HealthMonitor(
            event_bus=event_bus,
            check_interval=health_interval,
        )

        # Start background health monitoring
        self.health_monitor.start_monitoring()

        logger.info(
            "Resilience neuron initialized "
            "(cache_dir=%s, queue_dir=%s, health_interval=%.0fs)",
            cache_dir,
            queue_dir,
            health_interval,
        )

    def health_check(self) -> Dict[str, Any]:
        """
        Return health of the resilience neuron itself.

        Aggregates stats from all sub-components.
        """
        overall = "healthy"

        health_status = self.health_monitor.get_overall_status()
        queue_stats = self.booking_queue.get_queue_stats()
        cache_stats = self.fallback_manager.get_cache_stats()
        breaker_stats = self.circuit_registry.get_all_stats()

        # If the health monitor reports degraded/critical, reflect that
        if health_status in ("degraded", "critical"):
            overall = health_status

        # If any circuit breaker is open, we're at least degraded
        open_breakers = [
            name for name, stats in breaker_stats.items()
            if stats.get("state") == "OPEN"
        ]
        if open_breakers and overall == "healthy":
            overall = "degraded"

        return {
            "healthy": overall != "critical",
            "status": overall,
            "details": "Resilience neuron operational",
            "health_monitor": {
                "overall": health_status,
                "monitoring": self.health_monitor.is_monitoring,
            },
            "circuit_breakers": {
                "total": len(breaker_stats),
                "open": open_breakers,
            },
            "queue": queue_stats,
            "cache": cache_stats,
        }

    def shutdown(self) -> None:
        """Stop the health monitor background thread."""
        if self.health_monitor:
            self.health_monitor.stop_monitoring()
        logger.info("Resilience neuron shut down")
