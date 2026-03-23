"""
ANASTASiA Dispatch — Card-guided booking + search dispatch engine.

Zero Anthropic API cost. Pure JSON knowledge cards + Python logic.
MYSTES calls this module for ALL booking execution and flight search.

Usage from MYSTES:
    from anastasia.dispatch import BookingDispatcher, SearchOrchestrator

    # Booking
    dispatcher = BookingDispatcher()
    result = dispatcher.dispatch(
        raw_offer={"source": "duffel_ndc", "offer_id": "off_xxx"},
        passenger_data={"first_name": "John", "last_name": "Doe", ...},
        clients={"duffel_ndc": duffel_client_instance},
    )

    # Search
    orchestrator = SearchOrchestrator()
    results = orchestrator.search(
        origin="JFK", destination="FCO", departure_date="2026-04-15",
        clients={"picasso": picasso_fn, "duffel_ndc": duffel_fn},
    )
"""

from .dispatcher import BookingDispatcher
from .transformer import PassengerTransformer
from .search_orchestrator import SearchOrchestrator
from .coordinator import VerticalSearchCoordinator

__all__ = ["BookingDispatcher", "PassengerTransformer", "SearchOrchestrator", "VerticalSearchCoordinator"]
