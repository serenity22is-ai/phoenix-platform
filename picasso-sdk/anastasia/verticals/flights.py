"""
Flights Vertical Neuron — ANASTASiA's flight search and booking orchestrator.

This neuron manages ALL flight API integrations as a single coordinated vertical:
- Picasso/Redbox (GDS, 102-country POS arbitrage)
- Duffel NDC (300+ airlines, NDC-direct)
- Kiwi Tequila (750+ carriers, virtual interlining)
- AirGateway NDC (25+ airlines NDC + AERTiCKET GDS, POS arbitrage)
- Mystifly (80+ POS, multi-GDS) — when credentials available
- Travelfusion (412+ airlines, direct) — when credentials available
- TripStack (250+ carriers, VI Guarantee) — when credentials available

The FlightsNeuron uses the Module Director to dynamically create search
pipelines based on which modules are configured (have credentials).
It deduplicates results across sources and routes bookings to the
module that provided the selected flight.

MYSTES KYRIOS LLC — Confidential.
"""

import logging
from typing import Any, Dict, List, Optional

from ..core.events import Event, EventBus, EventType
from ..core.registry import NeuronModule
from ..modules.registry import ModuleRegistry, VerticalType
from ..modules.director import ModuleDirector, SearchPlan
from ..modules.flight_modules import build_all_flight_modules

logger = logging.getLogger("anastasia.verticals.flights")


class FlightsNeuron(NeuronModule):
    """
    ANASTASiA Flights vertical neuron.

    Orchestrates flight search, pricing, booking, and management across
    all configured flight API modules. Uses the Module Director to create
    optimal search pipelines dynamically.

    The flights neuron is the PRIMARY vertical for ANASTASiA — it handles
    the core value proposition of geographic price arbitrage on flights.

    Dependencies:
        - knowledge: System profiles for customer API integration
    """

    def __init__(self):
        self._event_bus: Optional[EventBus] = None
        self._registry: Optional[ModuleRegistry] = None
        self._director: Optional[ModuleDirector] = None
        self._search_count: int = 0
        self._booking_count: int = 0
        self._initialized: bool = False

    @property
    def name(self) -> str:
        return "flights"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def dependencies(self) -> List[str]:
        return ["knowledge"]

    def initialize(self, event_bus: EventBus, config: Dict[str, Any]) -> None:
        """
        Initialize the flights vertical.

        Creates a Module Registry with all known flight API modules,
        checks credentials, and sets up the Director for dynamic routing.

        Args:
            event_bus: Platform event bus for inter-neuron communication
            config: Platform config — may include pre-built registry
        """
        self._event_bus = event_bus

        # Use pre-built registry if provided (from api.py), otherwise create our own
        self._registry = config.get("flights_registry")
        if not self._registry:
            self._registry = ModuleRegistry()
            # Register all known flight modules
            for module in build_all_flight_modules():
                self._registry.register(module)
            # Auto-detect configured modules from environment
            self._registry.refresh_credentials()

        # Create the Director for intelligent routing
        self._director = ModuleDirector(self._registry)

        # Subscribe to events that affect flights
        event_bus.subscribe(EventType.SEARCH_COMPLETED, self._on_search_completed)
        event_bus.subscribe(EventType.BOOKING_CREATED, self._on_booking_created)
        event_bus.subscribe(EventType.BOOKING_CANCELLED, self._on_booking_cancelled)

        configured = self._registry.list_configured(vertical=VerticalType.FLIGHTS.value)
        module_names = [m.knowledge_card.name for m in configured]

        self._initialized = True
        logger.info(
            "Flights neuron online: %d/%d modules configured (%s)",
            len(configured),
            len(self._registry.list_modules(vertical=VerticalType.FLIGHTS.value)),
            ", ".join(module_names) if module_names else "none",
        )

    def health_check(self) -> Dict[str, Any]:
        """Return flights vertical health status."""
        if not self._initialized or not self._registry:
            return {
                "healthy": False,
                "details": "Flights neuron not initialized",
            }

        all_flight_modules = self._registry.list_modules(
            vertical=VerticalType.FLIGHTS.value,
        )
        configured = self._registry.list_configured(
            vertical=VerticalType.FLIGHTS.value,
        )

        can_search = self._director.can_search(VerticalType.FLIGHTS.value)
        can_book = self._director.can_book(VerticalType.FLIGHTS.value)

        return {
            "healthy": can_search,
            "details": (
                f"{len(configured)}/{len(all_flight_modules)} flight modules active"
                if configured
                else "No flight modules configured — set API credentials"
            ),
            "vertical": "flights",
            "modules_configured": len(configured),
            "modules_total": len(all_flight_modules),
            "module_names": [m.knowledge_card.name for m in configured],
            "can_search": can_search,
            "can_book": can_book,
            "has_arbitrage": any(
                "pos_arbitrage" in m.knowledge_card.strengths
                for m in configured
            ),
            "total_carriers": sum(
                m.knowledge_card.carrier_count for m in configured
            ),
            "searches_handled": self._search_count,
            "bookings_handled": self._booking_count,
        }

    def shutdown(self) -> None:
        """Clean up flights resources."""
        self._initialized = False
        logger.info(
            "Flights neuron shut down (handled %d searches, %d bookings)",
            self._search_count,
            self._booking_count,
        )

    # =========================================================================
    # SEARCH ORCHESTRATION
    # =========================================================================

    def plan_search(
        self,
        origin: Optional[str] = None,
        destination: Optional[str] = None,
        requirements: Optional[Dict[str, Any]] = None,
    ) -> SearchPlan:
        """
        Create an optimal search plan across all configured flight modules.

        The Director reads knowledge cards, checks credentials, and returns
        a prioritized list of modules to search with merge strategy.

        Args:
            origin: Origin IATA code (for geographic optimization)
            destination: Destination IATA code
            requirements: Optional constraints (nonstop_only, cabin_class, etc.)

        Returns:
            SearchPlan with modules to search and merge strategy
        """
        if not self._director:
            return SearchPlan(modules=[], primary="none", notes=["Not initialized"])

        return self._director.plan_search(
            vertical=VerticalType.FLIGHTS.value,
            origin=origin,
            destination=destination,
            requirements=requirements,
        )

    def get_search_modules(self) -> list:
        """Get configured flight modules sorted by priority."""
        if not self._registry:
            return []
        return self._registry.list_configured(vertical=VerticalType.FLIGHTS.value)

    # =========================================================================
    # BOOKING ROUTING
    # =========================================================================

    def route_booking(
        self,
        source: str,
        module_id: Optional[str] = None,
    ):
        """Route a booking to the correct flight module."""
        if not self._director:
            return None
        return self._director.route_booking(source=source, module_id=module_id)

    # =========================================================================
    # KNOWLEDGE SYNTHESIS
    # =========================================================================

    def generate_system_prompt(self) -> str:
        """Generate the system prompt section for flight capabilities."""
        if not self._director:
            return ""
        return self._director.generate_system_prompt(
            vertical=VerticalType.FLIGHTS.value,
        )

    def get_capabilities(self) -> Dict[str, List[str]]:
        """Get capability matrix for flight modules."""
        if not self._director:
            return {}
        return self._director.get_capabilities(
            vertical=VerticalType.FLIGHTS.value,
        )

    # =========================================================================
    # MODULE ACCESS
    # =========================================================================

    @property
    def registry(self) -> Optional[ModuleRegistry]:
        """Access the flights module registry."""
        return self._registry

    @property
    def director(self) -> Optional[ModuleDirector]:
        """Access the flights module director."""
        return self._director

    # =========================================================================
    # EVENT HANDLERS
    # =========================================================================

    def _on_search_completed(self, event: Event) -> None:
        """Track flight searches for analytics."""
        source = event.data.get("source", "")
        # Only count our vertical's searches
        flight_sources = {"picasso", "duffel_ndc", "kiwi_tequila", "airgateway_ndc"}
        if source in flight_sources or event.source == "booking_agent":
            self._search_count += 1

    def _on_booking_created(self, event: Event) -> None:
        """Track flight bookings for analytics."""
        source = event.data.get("source", "")
        flight_sources = {"picasso", "duffel_ndc", "kiwi_tequila", "airgateway_ndc"}
        if source in flight_sources or event.source == "booking_agent":
            self._booking_count += 1

    def _on_booking_cancelled(self, event: Event) -> None:
        """Track cancellations."""
        source = event.data.get("source", "")
        flight_sources = {"picasso", "duffel_ndc", "kiwi_tequila", "airgateway_ndc"}
        if source in flight_sources:
            logger.info(
                "Flight booking cancelled: %s (source: %s)",
                event.data.get("booking_id", "unknown"),
                source,
            )
