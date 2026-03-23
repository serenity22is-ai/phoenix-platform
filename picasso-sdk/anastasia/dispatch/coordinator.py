"""
VerticalSearchCoordinator — Thin wrapper that routes search requests
to the correct vertical neuron's search() method.

NOT a replacement for SearchOrchestrator (which is flight-specific with
airline dedup, cabin maps, etc). This is a simple router for non-flight
verticals (cars, activities, insurance) that have search() methods.

Usage:
    coordinator = VerticalSearchCoordinator(platform)
    results = coordinator.search("cars", client=discover_cars, pickup_location="LAX", ...)

MYSTES KYRIOS LLC — Confidential.
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("anastasia.dispatch.coordinator")


class VerticalSearchCoordinator:
    """Routes search requests to the correct vertical neuron."""

    def __init__(self, platform=None):
        """
        Args:
            platform: AnastasiaPlatform instance with registered neuron modules.
        """
        self._platform = platform

    def search(self, vertical: str, client=None, **params) -> Dict[str, Any]:
        """
        Route search to correct neuron's search() method.

        Args:
            vertical: Neuron name — "cars", "activities", "insurance"
            client: Injected API client for the neuron
            **params: Vertical-specific search parameters

        Returns:
            Dict with search results from the neuron, or error dict.
        """
        neuron = self._platform.get_module(vertical) if self._platform else None
        if not neuron:
            logger.warning("Neuron '%s' not found", vertical)
            return {"success": False, "error": f"Neuron '{vertical}' not found"}

        if not hasattr(neuron, 'search'):
            logger.warning("Neuron '%s' has no search method", vertical)
            return {"success": False, "error": f"Neuron '{vertical}' has no search method"}

        try:
            return neuron.search(client=client, **params)
        except Exception as e:
            logger.error("Search failed for '%s': %s", vertical, e)
            return {"success": False, "error": str(e)}

    def search_multiple(self, requests: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Execute multiple vertical searches sequentially.

        Args:
            requests: [{"vertical": "cars", "client": ..., "params": {...}}, ...]

        Returns:
            {"cars": {...results...}, "activities": {...results...}}
        """
        results = {}
        for req in requests:
            vertical = req["vertical"]
            results[vertical] = self.search(
                vertical=vertical,
                client=req.get("client"),
                **req.get("params", {}),
            )
        return results

    @property
    def available_verticals(self) -> List[str]:
        """List verticals that have a search() capability."""
        if not self._platform:
            return []
        return [
            m["name"] for m in self._platform.list_modules()
            if hasattr(self._platform.get_module(m["name"]), 'search')
        ]
