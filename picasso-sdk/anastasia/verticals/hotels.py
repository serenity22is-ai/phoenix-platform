"""
Hotels Vertical Neuron — ANASTASiA's hotel search and booking orchestrator.

This neuron manages ALL hotel API integrations as a single coordinated vertical:
- liteAPI (2M+ properties, wholesaler net rates, self-serve) — ACTIVE
- Future: Hotelbeds, Expedia Rapid, Booking.com Connectivity, etc.

The HotelsNeuron uses the Module Director to route hotel searches and bookings.
Currently flights-only demo, but hotels can be enabled by setting the
LITEAPI_KEY environment variable and enabling the vertical_hotels feature flag.

Hotel booking flow is simpler than flights:
- No passport required for domestic hotels
- No POS arbitrage (wholesaler rates are global)
- Requires prebook validation before booking
- $15 flat fee (vs percentage for flights)

MYSTES KYRIOS LLC — Confidential.
"""

import logging
from typing import Any, Dict, List, Optional

from ..core.events import Event, EventBus, EventType
from ..core.registry import NeuronModule
from ..modules.registry import ModuleRegistry, VerticalType
from ..modules.director import ModuleDirector, SearchPlan
from ..modules.flight_modules import build_all_hotel_modules

logger = logging.getLogger("anastasia.verticals.hotels")


class HotelsNeuron(NeuronModule):
    """
    ANASTASiA Hotels vertical neuron.

    Orchestrates hotel search, pricing, booking, and management across
    all configured hotel API modules.

    Currently supports liteAPI (2M+ properties, wholesaler rates).
    Designed to expand to Hotelbeds, Expedia Rapid, and others as
    ANASTASiA learns their systems through customer integrations.

    Dependencies:
        - knowledge: System profiles for customer API integration
    """

    def __init__(self):
        self._event_bus: Optional[EventBus] = None
        self._registry: Optional[ModuleRegistry] = None
        self._director: Optional[ModuleDirector] = None
        self._search_count: int = 0
        self._booking_count: int = 0
        self._enabled: bool = False
        self._initialized: bool = False

    @property
    def name(self) -> str:
        return "hotels"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def dependencies(self) -> List[str]:
        return ["knowledge"]

    def initialize(self, event_bus: EventBus, config: Dict[str, Any]) -> None:
        """
        Initialize the hotels vertical.

        Creates a Module Registry with all known hotel API modules,
        checks credentials, and sets up the Director for routing.

        The hotels vertical is GATED — it requires explicit enablement
        via the vertical_hotels feature flag (default: disabled for Phase 1).

        Args:
            event_bus: Platform event bus
            config: Platform config — may include pre-built registry
        """
        self._event_bus = event_bus

        # Check if hotels vertical is enabled
        self._enabled = config.get("hotels_enabled", False)

        # Use pre-built registry if provided, otherwise create our own
        self._registry = config.get("hotels_registry")
        if not self._registry:
            self._registry = ModuleRegistry()
            for module in build_all_hotel_modules():
                self._registry.register(module)
            self._registry.refresh_credentials()

        self._director = ModuleDirector(self._registry)

        # Subscribe to hotel-relevant events
        event_bus.subscribe(EventType.BOOKING_CREATED, self._on_booking_created)

        configured = self._registry.list_configured(vertical=VerticalType.HOTELS.value)
        module_names = [m.knowledge_card.name for m in configured]

        self._initialized = True

        status = "ENABLED" if self._enabled else "DISABLED (Phase 1 — flights only)"
        logger.info(
            "Hotels neuron online (%s): %d/%d modules configured (%s)",
            status,
            len(configured),
            len(self._registry.list_modules(vertical=VerticalType.HOTELS.value)),
            ", ".join(module_names) if module_names else "none",
        )

    def health_check(self) -> Dict[str, Any]:
        """Return hotels vertical health status."""
        if not self._initialized or not self._registry:
            return {
                "healthy": False,
                "details": "Hotels neuron not initialized",
            }

        all_hotel_modules = self._registry.list_modules(
            vertical=VerticalType.HOTELS.value,
        )
        configured = self._registry.list_configured(
            vertical=VerticalType.HOTELS.value,
        )

        can_search = self._director.can_search(VerticalType.HOTELS.value)
        can_book = self._director.can_book(VerticalType.HOTELS.value)

        if not self._enabled:
            details = "Hotels vertical disabled (Phase 1 — flights only)"
            healthy = True  # Neuron itself is healthy, just gated
        elif configured:
            details = f"{len(configured)}/{len(all_hotel_modules)} hotel modules active"
            healthy = can_search
        else:
            details = "No hotel modules configured — set LITEAPI_KEY"
            healthy = False

        return {
            "healthy": healthy,
            "details": details,
            "vertical": "hotels",
            "enabled": self._enabled,
            "modules_configured": len(configured),
            "modules_total": len(all_hotel_modules),
            "module_names": [m.knowledge_card.name for m in configured],
            "can_search": can_search and self._enabled,
            "can_book": can_book and self._enabled,
            "total_properties": sum(
                m.knowledge_card.carrier_count for m in configured
            ),
            "searches_handled": self._search_count,
            "bookings_handled": self._booking_count,
        }

    def shutdown(self) -> None:
        """Clean up hotels resources."""
        self._initialized = False
        logger.info(
            "Hotels neuron shut down (handled %d searches, %d bookings)",
            self._search_count,
            self._booking_count,
        )

    # =========================================================================
    # SEARCH ORCHESTRATION
    # =========================================================================

    def plan_search(
        self,
        city: Optional[str] = None,
        country: Optional[str] = None,
        requirements: Optional[Dict[str, Any]] = None,
    ) -> SearchPlan:
        """Create an optimal search plan for hotel modules."""
        if not self._director or not self._enabled:
            notes = ["Hotels vertical disabled"] if not self._enabled else ["Not initialized"]
            return SearchPlan(modules=[], primary="none", notes=notes)

        return self._director.plan_search(
            vertical=VerticalType.HOTELS.value,
            requirements=requirements,
        )

    def get_search_modules(self) -> list:
        """Get configured hotel modules sorted by priority."""
        if not self._registry or not self._enabled:
            return []
        return self._registry.list_configured(vertical=VerticalType.HOTELS.value)

    # =========================================================================
    # VERTICAL GATING
    # =========================================================================

    @property
    def is_enabled(self) -> bool:
        """Check if the hotels vertical is enabled."""
        return self._enabled

    def enable(self) -> None:
        """Enable the hotels vertical (requires configured modules)."""
        self._enabled = True
        logger.info("Hotels vertical ENABLED")

    def disable(self) -> None:
        """Disable the hotels vertical."""
        self._enabled = False
        logger.info("Hotels vertical DISABLED")

    # =========================================================================
    # MODULE ACCESS
    # =========================================================================

    @property
    def registry(self) -> Optional[ModuleRegistry]:
        """Access the hotels module registry."""
        return self._registry

    @property
    def director(self) -> Optional[ModuleDirector]:
        """Access the hotels module director."""
        return self._director

    # =========================================================================
    # EVENT HANDLERS
    # =========================================================================

    def _on_booking_created(self, event: Event) -> None:
        """Track hotel bookings."""
        source = event.data.get("source", "")
        if source in {"liteapi"}:
            self._booking_count += 1
