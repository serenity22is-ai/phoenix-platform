"""
Unified Search Dispatcher — Cross-vertical search orchestration for ANASTASiA.

The Search Dispatcher fans out search requests across all configured verticals
(flights, hotels, cars, activities) and merges results into a unified response.
This powers the "unified search bar" where shared fields (destination, dates,
passengers) automatically query all enabled verticals simultaneously.

Search Architecture:
    SearchRequest → Dispatcher → [FlightsNeuron, HotelsNeuron, ...] → SearchResponse
                                 (parallel fan-out)

ALL search operations are deterministic — ZERO AI tokens consumed.
AI activates ONLY when programmatic paths fail or the user opens chat.

MYSTES KYRIOS LLC — Confidential.
"""

import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from ..core.events import Event, EventBus, EventType
from ..core.registry import NeuronModule

logger = logging.getLogger("anastasia.search")

# Maximum parallel search threads (one per vertical).
MAX_SEARCH_WORKERS = 4

# Default timeout per vertical search (seconds).
DEFAULT_SEARCH_TIMEOUT = 30


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class SearchRequest:
    """
    Unified search request that spans all verticals.

    Shared fields (destination, dates, passengers) are passed to every
    vertical. Vertical-specific params go in the vertical_params dict.
    """
    request_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    agency_id: str = ""
    # Shared fields (passed to all verticals)
    destination: str = ""        # IATA code or city name
    origin: str = ""             # IATA code or city name (primarily for flights)
    check_in: str = ""           # ISO date (YYYY-MM-DD)
    check_out: str = ""          # ISO date / return date for flights
    adults: int = 1
    children: int = 0
    infants: int = 0
    # Which verticals to search (empty = all enabled)
    verticals: List[str] = field(default_factory=list)
    # Vertical-specific params: {"flights": {"cabin": "ECONOMY"}, "hotels": {"stars": 4}}
    vertical_params: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    # Pricing context
    user_tier: str = "consumer"  # "consumer", "b2b", "starter", "pro", "enterprise"
    # Search strategy
    timeout_seconds: int = DEFAULT_SEARCH_TIMEOUT
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "request_id": self.request_id,
            "agency_id": self.agency_id,
            "destination": self.destination,
            "origin": self.origin,
            "check_in": self.check_in,
            "check_out": self.check_out,
            "adults": self.adults,
            "children": self.children,
            "infants": self.infants,
            "verticals": list(self.verticals),
            "vertical_params": dict(self.vertical_params),
            "user_tier": self.user_tier,
            "timeout_seconds": self.timeout_seconds,
            "created_at": self.created_at,
        }


@dataclass
class VerticalResult:
    """Results from a single vertical search."""
    vertical: str               # "flights", "hotels", "cars", etc.
    results: List[Dict[str, Any]] = field(default_factory=list)
    result_count: int = 0
    search_time_ms: float = 0.0
    source_modules: List[str] = field(default_factory=list)
    error: Optional[str] = None
    cached: bool = False

    def to_dict(self) -> dict:
        return {
            "vertical": self.vertical,
            "results": self.results,
            "result_count": self.result_count,
            "search_time_ms": round(self.search_time_ms, 1),
            "source_modules": self.source_modules,
            "error": self.error,
            "cached": self.cached,
        }


@dataclass
class SearchResponse:
    """
    Unified search response combining results from all verticals.

    Each vertical's results are separate (not merged across verticals).
    The Bundle Engine later combines selections from different verticals
    into a single booking package.
    """
    request_id: str = ""
    verticals: Dict[str, VerticalResult] = field(default_factory=dict)
    total_results: int = 0
    total_search_time_ms: float = 0.0
    verticals_searched: int = 0
    verticals_failed: int = 0

    def to_dict(self) -> dict:
        return {
            "request_id": self.request_id,
            "verticals": {k: v.to_dict() for k, v in self.verticals.items()},
            "total_results": self.total_results,
            "total_search_time_ms": round(self.total_search_time_ms, 1),
            "verticals_searched": self.verticals_searched,
            "verticals_failed": self.verticals_failed,
        }


# ---------------------------------------------------------------------------
# Search Dispatcher
# ---------------------------------------------------------------------------

# Type for vertical search functions registered with the dispatcher.
# Takes (SearchRequest, vertical_params) -> List[Dict]
VerticalSearchFn = Callable[[SearchRequest, Dict[str, Any]], List[Dict[str, Any]]]


class SearchDispatcher:
    """
    Fans out search requests across all configured verticals.

    Each vertical registers a search function. When a unified search
    comes in, the dispatcher calls all enabled verticals in parallel
    (via ThreadPoolExecutor) and collects results.

    Usage::

        dispatcher = SearchDispatcher(event_bus)

        # Register vertical search handlers
        dispatcher.register_vertical("flights", flights_search_fn)
        dispatcher.register_vertical("hotels", hotels_search_fn)

        # Execute unified search
        response = dispatcher.search(SearchRequest(
            origin="JFK", destination="LHR",
            check_in="2026-04-01", check_out="2026-04-07",
            adults=2,
        ))

        # Results organized by vertical
        for vertical_name, result in response.verticals.items():
            print(f"{vertical_name}: {result.result_count} results")
    """

    def __init__(
        self,
        event_bus: Optional[EventBus] = None,
        max_workers: int = MAX_SEARCH_WORKERS,
    ):
        self._event_bus = event_bus
        self._max_workers = max_workers
        self._verticals: Dict[str, VerticalSearchFn] = {}
        self._search_count: int = 0
        self._total_results: int = 0

    def register_vertical(
        self,
        vertical_name: str,
        search_fn: VerticalSearchFn,
    ) -> None:
        """
        Register a vertical's search function.

        Args:
            vertical_name: Vertical identifier (e.g., "flights", "hotels").
            search_fn: Callable that takes (SearchRequest, vertical_params)
                       and returns a list of result dicts.
        """
        self._verticals[vertical_name] = search_fn
        logger.info("Registered search vertical: %s", vertical_name)

    def unregister_vertical(self, vertical_name: str) -> None:
        """Remove a vertical from the dispatcher."""
        self._verticals.pop(vertical_name, None)

    @property
    def available_verticals(self) -> List[str]:
        """List of registered vertical names."""
        return list(self._verticals.keys())

    def search(self, request: SearchRequest) -> SearchResponse:
        """
        Execute a unified search across all requested verticals.

        If request.verticals is empty, searches ALL registered verticals.
        Each vertical runs in its own thread with the specified timeout.

        Args:
            request: Unified search request.

        Returns:
            SearchResponse with results organized by vertical.
        """
        start = time.time()
        self._search_count += 1

        # Determine which verticals to search
        target_verticals = request.verticals or list(self._verticals.keys())
        target_verticals = [
            v for v in target_verticals if v in self._verticals
        ]

        if not target_verticals:
            logger.warning("No verticals available for search")
            return SearchResponse(
                request_id=request.request_id,
                total_search_time_ms=0,
            )

        logger.info(
            "Unified search [%s]: %s→%s, %s, verticals=%s",
            request.request_id,
            request.origin,
            request.destination,
            request.check_in,
            ", ".join(target_verticals),
        )

        response = SearchResponse(request_id=request.request_id)

        # Fan out to all verticals in parallel
        with ThreadPoolExecutor(max_workers=self._max_workers) as executor:
            futures = {}
            for vertical in target_verticals:
                vertical_params = request.vertical_params.get(vertical, {})
                future = executor.submit(
                    self._search_vertical,
                    vertical,
                    request,
                    vertical_params,
                )
                futures[future] = vertical

            # Collect results with timeout
            for future in as_completed(
                futures, timeout=request.timeout_seconds + 5,
            ):
                vertical = futures[future]
                try:
                    result = future.result(timeout=request.timeout_seconds)
                    response.verticals[vertical] = result
                    response.total_results += result.result_count
                    response.verticals_searched += 1
                    if result.error:
                        response.verticals_failed += 1
                except Exception as e:
                    logger.error("Vertical '%s' search failed: %s", vertical, e)
                    response.verticals[vertical] = VerticalResult(
                        vertical=vertical,
                        error=str(e),
                    )
                    response.verticals_searched += 1
                    response.verticals_failed += 1

        elapsed_ms = (time.time() - start) * 1000
        response.total_search_time_ms = elapsed_ms

        self._total_results += response.total_results

        # Publish search completed event
        if self._event_bus:
            self._event_bus.publish(Event(
                type=EventType.SEARCH_COMPLETED,
                source="search_dispatcher",
                agency_id=request.agency_id,
                data={
                    "request_id": request.request_id,
                    "verticals_searched": response.verticals_searched,
                    "verticals_failed": response.verticals_failed,
                    "total_results": response.total_results,
                    "search_time_ms": round(elapsed_ms, 1),
                    "user_tier": request.user_tier,
                },
            ))

        logger.info(
            "Unified search complete [%s]: %d results across %d verticals "
            "(%.0fms, %d failed)",
            request.request_id,
            response.total_results,
            response.verticals_searched,
            elapsed_ms,
            response.verticals_failed,
        )

        return response

    def _search_vertical(
        self,
        vertical: str,
        request: SearchRequest,
        vertical_params: Dict[str, Any],
    ) -> VerticalResult:
        """
        Execute a single vertical's search with timing and error handling.
        """
        start = time.time()
        try:
            search_fn = self._verticals[vertical]
            results = search_fn(request, vertical_params)

            elapsed_ms = (time.time() - start) * 1000
            return VerticalResult(
                vertical=vertical,
                results=results,
                result_count=len(results),
                search_time_ms=elapsed_ms,
                source_modules=[vertical],
            )
        except Exception as e:
            elapsed_ms = (time.time() - start) * 1000
            logger.error(
                "Vertical '%s' search error (%.0fms): %s",
                vertical, elapsed_ms, e,
            )
            return VerticalResult(
                vertical=vertical,
                error=str(e),
                search_time_ms=elapsed_ms,
            )

    def get_stats(self) -> Dict[str, Any]:
        """Return search dispatcher statistics."""
        return {
            "registered_verticals": list(self._verticals.keys()),
            "vertical_count": len(self._verticals),
            "total_searches": self._search_count,
            "total_results_returned": self._total_results,
        }


# ---------------------------------------------------------------------------
# SearchModule — NeuronModule wrapper (optional — for platform registration)
# ---------------------------------------------------------------------------

class SearchModule(NeuronModule):
    """
    ANASTASiA Search neuron — unified search across all verticals.

    This is a thin wrapper that registers the SearchDispatcher with
    the platform's neuron lifecycle. The actual search logic lives
    in SearchDispatcher.

    The dispatcher does NOT register itself as a neuron by default
    (it's used directly from API routes). This module is provided
    for completeness if platform-level lifecycle is needed.
    """

    def __init__(self):
        self._dispatcher: Optional[SearchDispatcher] = None

    @property
    def name(self) -> str:
        return "search"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def dependencies(self) -> List[str]:
        return ["flights", "hotels"]

    @property
    def dispatcher(self) -> SearchDispatcher:
        if self._dispatcher is None:
            raise RuntimeError("SearchModule not initialized")
        return self._dispatcher

    def initialize(self, event_bus: EventBus, config: Dict[str, Any]) -> None:
        self._dispatcher = SearchDispatcher(event_bus=event_bus)
        logger.info("Search neuron initialized (dispatcher ready)")

    def health_check(self) -> Dict[str, Any]:
        if self._dispatcher is None:
            return {"healthy": False, "details": "Not initialized"}
        stats = self._dispatcher.get_stats()
        return {
            "healthy": True,
            "details": f"{stats['vertical_count']} verticals registered",
            **stats,
        }

    def shutdown(self) -> None:
        logger.info("Search neuron shut down")


__all__ = [
    "SearchRequest",
    "SearchResponse",
    "VerticalResult",
    "SearchDispatcher",
    "SearchModule",
]
