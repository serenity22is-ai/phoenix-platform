"""
Cars Vertical Neuron — ANASTASiA's car rental search and booking orchestrator.

This neuron manages ALL car rental API integrations as a single coordinated vertical:
- Discover Cars (500+ suppliers, 145 countries, 10K+ locations) — ACTIVE
- Future: Kayak Cars, Rentalcars.com, Europcar Direct, etc.

The CarsNeuron uses the Module Director to route car searches and bookings.
Enabled by setting DISCOVER_CARS_USERNAME/PASSWORD/TOKEN environment variables
and the vertical_rentals feature flag.

MYSTES KYRIOS LLC — Confidential.
"""

import logging
from typing import Any, Dict, List, Optional

from ..core.events import Event, EventBus, EventType
from ..core.registry import NeuronModule
from ..modules.registry import ModuleRegistry, VerticalType
from ..modules.director import ModuleDirector, SearchPlan
from ..modules.car_modules import build_all_car_modules

logger = logging.getLogger("anastasia.verticals.cars")


class CarsNeuron(NeuronModule):
    """
    ANASTASiA Cars vertical neuron.

    Orchestrates car rental search, pricing, booking, and management across
    all configured car rental API modules.

    Currently supports Discover Cars (500+ suppliers).

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
        return "cars"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def dependencies(self) -> List[str]:
        return ["knowledge"]

    def initialize(self, event_bus: EventBus, config: Dict[str, Any]) -> None:
        self._event_bus = event_bus
        self._enabled = config.get("cars_enabled", True)

        self._registry = config.get("cars_registry")
        if not self._registry:
            self._registry = ModuleRegistry()
            for module in build_all_car_modules():
                self._registry.register(module)
            self._registry.refresh_credentials()

        self._director = ModuleDirector(self._registry)
        event_bus.subscribe(EventType.BOOKING_CREATED, self._on_booking_created)

        configured = self._registry.list_configured(vertical=VerticalType.CAR_RENTAL.value)
        module_names = [m.knowledge_card.name for m in configured]
        self._initialized = True

        status = "ENABLED" if self._enabled else "DISABLED"
        logger.info(
            "Cars neuron online (%s): %d/%d modules configured (%s)",
            status, len(configured),
            len(self._registry.list_modules(vertical=VerticalType.CAR_RENTAL.value)),
            ", ".join(module_names) if module_names else "none",
        )

    def health_check(self) -> Dict[str, Any]:
        if not self._initialized or not self._registry:
            return {"healthy": False, "details": "Cars neuron not initialized"}

        all_mods = self._registry.list_modules(vertical=VerticalType.CAR_RENTAL.value)
        configured = self._registry.list_configured(vertical=VerticalType.CAR_RENTAL.value)
        can_search = self._director.can_search(VerticalType.CAR_RENTAL.value)
        can_book = self._director.can_book(VerticalType.CAR_RENTAL.value)

        if not self._enabled:
            details, healthy = "Cars vertical disabled", True
        elif configured:
            details, healthy = f"{len(configured)}/{len(all_mods)} car modules active", can_search
        else:
            details, healthy = "No car modules configured — set DISCOVER_CARS_USERNAME/PASSWORD/TOKEN", False

        return {
            "healthy": healthy, "details": details, "vertical": "cars",
            "enabled": self._enabled,
            "modules_configured": len(configured), "modules_total": len(all_mods),
            "module_names": [m.knowledge_card.name for m in configured],
            "can_search": can_search and self._enabled,
            "can_book": can_book and self._enabled,
            "total_suppliers": sum(m.knowledge_card.carrier_count for m in configured),
            "searches_handled": self._search_count, "bookings_handled": self._booking_count,
        }

    def shutdown(self) -> None:
        self._initialized = False
        logger.info("Cars neuron shut down (%d searches, %d bookings)", self._search_count, self._booking_count)

    def plan_search(self, location=None, pickup_date=None, dropoff_date=None, requirements=None) -> SearchPlan:
        if not self._director or not self._enabled:
            return SearchPlan(modules=[], primary="none", notes=["Cars vertical disabled"] if not self._enabled else ["Not initialized"])
        return self._director.plan_search(vertical=VerticalType.CAR_RENTAL.value, requirements=requirements)

    def get_search_modules(self) -> list:
        if not self._registry or not self._enabled:
            return []
        return self._registry.list_configured(vertical=VerticalType.CAR_RENTAL.value)

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    def enable(self) -> None:
        self._enabled = True
        logger.info("Cars vertical ENABLED")

    def disable(self) -> None:
        self._enabled = False
        logger.info("Cars vertical DISABLED")

    @property
    def registry(self) -> Optional[ModuleRegistry]:
        return self._registry

    @property
    def director(self) -> Optional[ModuleDirector]:
        return self._director

    def search(self, pickup_location, pickup_date, dropoff_date, client=None):
        """
        Search car rentals via injected client.

        MYSTES injects the client (discover_cars_client) — neuron calls it,
        attaches raw_offer to each result for BookingDispatcher passthrough.

        Args:
            pickup_location: Location name or IATA code
            pickup_date: Pickup date (YYYY-MM-DD)
            dropoff_date: Dropoff date (YYYY-MM-DD)
            client: Injected API client with search_locations/search_cars methods
        """
        if not self._enabled:
            return {"success": False, "error": "Cars vertical disabled", "cars": []}
        if not client:
            return {"success": False, "error": "No car rental client provided", "cars": []}

        try:
            # Resolve location
            locations = client.search_locations(pickup_location)
            if not locations:
                return {"success": False, "error": f"No locations found for '{pickup_location}'", "cars": []}

            location_id = locations[0].get("id") or locations[0].get("location_id")

            # Search cars
            results = client.search_cars(
                pickup_location_id=location_id,
                pickup_date=pickup_date,
                dropoff_date=dropoff_date,
            )

            # Attach raw_offer to each result for dispatcher passthrough
            cars = []
            for car in (results or []):
                car["raw_offer"] = {
                    "source": "discover_cars",
                    "offer_id": car.get("offer_id") or car.get("id"),
                    "supplier": car.get("supplier"),
                    "pickup_location_id": location_id,
                    "pickup_date": pickup_date,
                    "dropoff_date": dropoff_date,
                }
                cars.append(car)

            self._search_count += 1
            if self._event_bus:
                self._event_bus.publish(Event(
                    EventType.SEARCH_COMPLETED,
                    {"vertical": "cars", "results": len(cars), "location": pickup_location},
                ))

            return {"success": True, "cars": cars, "source": "discover_cars"}

        except Exception as e:
            logger.error("Car search failed: %s", e)
            return {"success": False, "error": str(e), "cars": []}

    def _on_booking_created(self, event: Event) -> None:
        if event.data.get("source", "") in {"discover_cars"}:
            self._booking_count += 1
