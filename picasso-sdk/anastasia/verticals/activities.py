"""
Activities Vertical Neuron — ANASTASiA's tours and experiences orchestrator.

This neuron manages ALL activity/tour API integrations as a single coordinated vertical:
- Viator (300,000+ products, 200 countries, TripAdvisor reviews) — ACTIVE
- Future: GetYourGuide, Musement, Klook, etc.

The ActivitiesNeuron uses the Module Director to route activity searches and bookings.
Enabled by setting VIATOR_API_KEY environment variable and the vertical_activities flag.

MYSTES KYRIOS LLC — Confidential.
"""

import logging
from typing import Any, Dict, List, Optional

from ..core.events import Event, EventBus, EventType
from ..core.registry import NeuronModule
from ..modules.registry import ModuleRegistry, VerticalType
from ..modules.director import ModuleDirector, SearchPlan
from ..modules.activity_modules import build_all_activity_modules

logger = logging.getLogger("anastasia.verticals.activities")


class ActivitiesNeuron(NeuronModule):
    """
    ANASTASiA Activities vertical neuron.

    Orchestrates activity/tour search, pricing, booking, and management across
    all configured activity API modules.

    Currently supports Viator (300,000+ products).

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
        return "activities"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def dependencies(self) -> List[str]:
        return ["knowledge"]

    def initialize(self, event_bus: EventBus, config: Dict[str, Any]) -> None:
        self._event_bus = event_bus
        self._enabled = config.get("activities_enabled", True)

        self._registry = config.get("activities_registry")
        if not self._registry:
            self._registry = ModuleRegistry()
            for module in build_all_activity_modules():
                self._registry.register(module)
            self._registry.refresh_credentials()

        self._director = ModuleDirector(self._registry)
        event_bus.subscribe(EventType.BOOKING_CREATED, self._on_booking_created)

        configured = self._registry.list_configured(vertical=VerticalType.ACTIVITIES.value)
        module_names = [m.knowledge_card.name for m in configured]
        self._initialized = True

        status = "ENABLED" if self._enabled else "DISABLED"
        logger.info(
            "Activities neuron online (%s): %d/%d modules configured (%s)",
            status, len(configured),
            len(self._registry.list_modules(vertical=VerticalType.ACTIVITIES.value)),
            ", ".join(module_names) if module_names else "none",
        )

    def health_check(self) -> Dict[str, Any]:
        if not self._initialized or not self._registry:
            return {"healthy": False, "details": "Activities neuron not initialized"}

        all_mods = self._registry.list_modules(vertical=VerticalType.ACTIVITIES.value)
        configured = self._registry.list_configured(vertical=VerticalType.ACTIVITIES.value)
        can_search = self._director.can_search(VerticalType.ACTIVITIES.value)
        can_book = self._director.can_book(VerticalType.ACTIVITIES.value)

        if not self._enabled:
            details, healthy = "Activities vertical disabled", True
        elif configured:
            details, healthy = f"{len(configured)}/{len(all_mods)} activity modules active", can_search
        else:
            details, healthy = "No activity modules configured — set VIATOR_API_KEY", False

        return {
            "healthy": healthy, "details": details, "vertical": "activities",
            "enabled": self._enabled,
            "modules_configured": len(configured), "modules_total": len(all_mods),
            "module_names": [m.knowledge_card.name for m in configured],
            "can_search": can_search and self._enabled,
            "can_book": can_book and self._enabled,
            "total_products": sum(m.knowledge_card.carrier_count for m in configured),
            "searches_handled": self._search_count, "bookings_handled": self._booking_count,
        }

    def shutdown(self) -> None:
        self._initialized = False
        logger.info("Activities neuron shut down (%d searches, %d bookings)", self._search_count, self._booking_count)

    def plan_search(self, destination=None, date_from=None, date_to=None, requirements=None) -> SearchPlan:
        if not self._director or not self._enabled:
            return SearchPlan(modules=[], primary="none", notes=["Activities vertical disabled"] if not self._enabled else ["Not initialized"])
        return self._director.plan_search(vertical=VerticalType.ACTIVITIES.value, requirements=requirements)

    def get_search_modules(self) -> list:
        if not self._registry or not self._enabled:
            return []
        return self._registry.list_configured(vertical=VerticalType.ACTIVITIES.value)

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    def enable(self) -> None:
        self._enabled = True
        logger.info("Activities vertical ENABLED")

    def disable(self) -> None:
        self._enabled = False
        logger.info("Activities vertical DISABLED")

    @property
    def registry(self) -> Optional[ModuleRegistry]:
        return self._registry

    @property
    def director(self) -> Optional[ModuleDirector]:
        return self._director

    def search(self, destination, query=None, date_from=None, date_to=None, client=None):
        """
        Search activities/tours via injected client.

        MYSTES injects the client (viator_client) — neuron calls it,
        attaches raw_offer to each result for BookingDispatcher passthrough.

        Args:
            destination: Destination name or code
            query: Optional search query (e.g. "snorkeling")
            date_from: Start date (YYYY-MM-DD)
            date_to: End date (YYYY-MM-DD)
            client: Injected API client with search_freetext/search_products methods
        """
        if not self._enabled:
            return {"success": False, "error": "Activities vertical disabled", "activities": []}
        if not client:
            return {"success": False, "error": "No activities client provided", "activities": []}

        try:
            # Resolve destination
            dest_results = client.search_freetext(destination)
            if not dest_results:
                return {"success": False, "error": f"No destination found for '{destination}'", "activities": []}

            dest_id = dest_results[0].get("dest_id") or dest_results[0].get("id")

            # Search products
            results = client.search_products(
                dest_id=dest_id,
                query=query,
                date_from=date_from,
                date_to=date_to,
            )

            # Attach raw_offer to each result for dispatcher passthrough
            activities = []
            for activity in (results or []):
                activity["raw_offer"] = {
                    "source": "viator",
                    "product_code": activity.get("product_code") or activity.get("code"),
                    "dest_id": dest_id,
                    "date_from": date_from,
                    "date_to": date_to,
                }
                activities.append(activity)

            self._search_count += 1
            if self._event_bus:
                self._event_bus.publish(Event(
                    EventType.SEARCH_COMPLETED,
                    {"vertical": "activities", "results": len(activities), "destination": destination},
                ))

            return {"success": True, "activities": activities, "source": "viator"}

        except Exception as e:
            logger.error("Activity search failed: %s", e)
            return {"success": False, "error": str(e), "activities": []}

    def _on_booking_created(self, event: Event) -> None:
        if event.data.get("source", "") in {"viator"}:
            self._booking_count += 1
