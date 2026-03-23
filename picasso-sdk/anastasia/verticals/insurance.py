"""
Insurance Vertical Neuron — ANASTASiA's travel insurance orchestrator.

This neuron manages ALL insurance API integrations as a single coordinated vertical:
- SafetyWing (Nomad Insurance + Remote Health) — ACTIVE
- Future: World Nomads, Allianz Travel, AXA, etc.

Insurance is primarily a cross-sell on flight/hotel/car bookings. It surfaces on
the booking confirmation page, not as a standalone search vertical.

MYSTES KYRIOS LLC — Confidential.
"""

import logging
from typing import Any, Dict, List, Optional

from ..core.events import Event, EventBus, EventType
from ..core.registry import NeuronModule
from ..modules.registry import ModuleRegistry, VerticalType
from ..modules.director import ModuleDirector, SearchPlan
from ..modules.insurance_modules import build_all_insurance_modules

logger = logging.getLogger("anastasia.verticals.insurance")


class InsuranceNeuron(NeuronModule):
    """
    ANASTASiA Insurance vertical neuron.

    Orchestrates travel insurance quotes, policy creation, and management
    across all configured insurance API modules.

    Currently supports SafetyWing (Nomad Insurance + Remote Health).

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
        return "insurance"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def dependencies(self) -> List[str]:
        return ["knowledge"]

    def initialize(self, event_bus: EventBus, config: Dict[str, Any]) -> None:
        self._event_bus = event_bus
        self._enabled = config.get("insurance_enabled", True)

        self._registry = config.get("insurance_registry")
        if not self._registry:
            self._registry = ModuleRegistry()
            for module in build_all_insurance_modules():
                self._registry.register(module)
            self._registry.refresh_credentials()

        self._director = ModuleDirector(self._registry)
        event_bus.subscribe(EventType.BOOKING_CREATED, self._on_booking_created)

        configured = self._registry.list_configured(vertical=VerticalType.INSURANCE.value)
        module_names = [m.knowledge_card.name for m in configured]
        self._initialized = True

        status = "ENABLED" if self._enabled else "DISABLED"
        logger.info(
            "Insurance neuron online (%s): %d/%d modules configured (%s)",
            status, len(configured),
            len(self._registry.list_modules(vertical=VerticalType.INSURANCE.value)),
            ", ".join(module_names) if module_names else "none",
        )

    def health_check(self) -> Dict[str, Any]:
        if not self._initialized or not self._registry:
            return {"healthy": False, "details": "Insurance neuron not initialized"}

        all_mods = self._registry.list_modules(vertical=VerticalType.INSURANCE.value)
        configured = self._registry.list_configured(vertical=VerticalType.INSURANCE.value)
        can_search = self._director.can_search(VerticalType.INSURANCE.value)
        can_book = self._director.can_book(VerticalType.INSURANCE.value)

        if not self._enabled:
            details, healthy = "Insurance vertical disabled", True
        elif configured:
            details, healthy = f"{len(configured)}/{len(all_mods)} insurance modules active", can_search
        else:
            details, healthy = "No insurance modules configured — set SAFETYWING_API_KEY", False

        return {
            "healthy": healthy, "details": details, "vertical": "insurance",
            "enabled": self._enabled,
            "modules_configured": len(configured), "modules_total": len(all_mods),
            "module_names": [m.knowledge_card.name for m in configured],
            "can_search": can_search and self._enabled,
            "can_book": can_book and self._enabled,
            "total_plans": sum(m.knowledge_card.carrier_count for m in configured),
            "searches_handled": self._search_count, "bookings_handled": self._booking_count,
        }

    def shutdown(self) -> None:
        self._initialized = False
        logger.info("Insurance neuron shut down (%d searches, %d bookings)", self._search_count, self._booking_count)

    def plan_search(self, destination_country=None, start_date=None, end_date=None, travelers=1, requirements=None) -> SearchPlan:
        if not self._director or not self._enabled:
            return SearchPlan(modules=[], primary="none", notes=["Insurance vertical disabled"] if not self._enabled else ["Not initialized"])
        return self._director.plan_search(vertical=VerticalType.INSURANCE.value, requirements=requirements)

    def get_search_modules(self) -> list:
        if not self._registry or not self._enabled:
            return []
        return self._registry.list_configured(vertical=VerticalType.INSURANCE.value)

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    def enable(self) -> None:
        self._enabled = True
        logger.info("Insurance vertical ENABLED")

    def disable(self) -> None:
        self._enabled = False
        logger.info("Insurance vertical DISABLED")

    @property
    def registry(self) -> Optional[ModuleRegistry]:
        return self._registry

    @property
    def director(self) -> Optional[ModuleDirector]:
        return self._director

    def search(self, destination_country, start_date, end_date, travelers=1, client=None):
        """
        Get insurance quotes via injected client.

        MYSTES injects the client (safetywing_client) — neuron calls it,
        attaches raw_offer to each result for BookingDispatcher passthrough.

        Args:
            destination_country: ISO country code (e.g. "US", "FR")
            start_date: Coverage start date (YYYY-MM-DD)
            end_date: Coverage end date (YYYY-MM-DD)
            travelers: Number of travelers (default 1)
            client: Injected API client with get_quote method
        """
        if not self._enabled:
            return {"success": False, "error": "Insurance vertical disabled", "quotes": []}
        if not client:
            return {"success": False, "error": "No insurance client provided", "quotes": []}

        try:
            result = client.get_quote(
                destination=destination_country,
                start_date=start_date,
                end_date=end_date,
                travelers=travelers,
            )

            # Attach raw_offer to each quote for dispatcher passthrough
            quotes = []
            for quote in (result if isinstance(result, list) else [result] if result else []):
                quote["raw_offer"] = {
                    "source": "safetywing",
                    "plan_id": quote.get("plan_id") or quote.get("id"),
                    "destination": destination_country,
                    "start_date": start_date,
                    "end_date": end_date,
                    "travelers": travelers,
                }
                quotes.append(quote)

            self._search_count += 1
            if self._event_bus:
                self._event_bus.publish(Event(
                    EventType.SEARCH_COMPLETED,
                    {"vertical": "insurance", "results": len(quotes), "destination": destination_country},
                ))

            return {"success": True, "quotes": quotes, "source": "safetywing"}

        except Exception as e:
            logger.error("Insurance quote failed: %s", e)
            return {"success": False, "error": str(e), "quotes": []}

    def _on_booking_created(self, event: Event) -> None:
        if event.data.get("source", "") in {"safetywing"}:
            self._booking_count += 1
