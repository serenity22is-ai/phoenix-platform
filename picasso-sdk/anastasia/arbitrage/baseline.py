"""
US Baseline — Fetches US retail prices via SerpAPI for spread calculation.

SerpAPI returns real US retail prices from Google Flights. This is the
price CEILING — what US customers currently pay on Google. The spread
is calculated as: US retail - foreign POS price.

IMPORTANT: SerpAPI is DEAD for POS pricing (gl=dk returns US prices because
SerpAPI servers are in US — IP geolocation determines POS, not URL params).
SerpAPI is RETAINED ONLY for US baseline pricing.

MYSTES KYRIOS LLC — Confidential.
"""

import hashlib
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Cache US baseline prices to avoid redundant SerpAPI calls
_baseline_cache: Dict[str, Dict[str, Any]] = {}
CACHE_TTL_SECONDS = 1200  # 20 minutes


class USBaselineProvider:
    """
    Fetches US retail prices from SerpAPI Google Flights.

    SerpAPI key: SERPAPI_KEY env var.
    Pricing: $0.01/search (5,000/mo on $50 plan).
    """

    def __init__(self, api_key: Optional[str] = None):
        self._api_key = api_key or os.environ.get("SERPAPI_KEY", "")
        self._query_count: int = 0
        self._cache_hits: int = 0

    def is_configured(self) -> bool:
        return bool(self._api_key)

    def get_us_baseline(
        self,
        origin: str,
        destination: str,
        departure_date: str,
        return_date: Optional[str] = None,
        cabin_class: str = "economy",
    ) -> Optional[Dict[str, Any]]:
        """Fetch US retail price from SerpAPI Google Flights.

        Args:
            origin: IATA airport code (e.g., "LAX")
            destination: IATA airport code (e.g., "NRT")
            departure_date: Date string (YYYY-MM-DD)
            return_date: Optional return date
            cabin_class: economy, business, first

        Returns:
            {
                "price_usd": 1400.00,
                "airline": "Japan Airlines",
                "stops": 0,
                "duration_minutes": 720,
                "source": "serpapi",
                "cached": False,
            }
            or None if lookup fails.
        """
        if not self._api_key:
            logger.warning("SerpAPI key not configured")
            return None

        # Check cache
        cache_key = self._cache_key(
            origin, destination, departure_date, return_date, cabin_class
        )
        cached = self._get_cached(cache_key)
        if cached:
            self._cache_hits += 1
            cached["cached"] = True
            return cached

        # Call SerpAPI
        try:
            import requests

            params = {
                "engine": "google_flights",
                "departure_id": origin,
                "arrival_id": destination,
                "outbound_date": departure_date,
                "currency": "USD",
                "hl": "en",
                "gl": "us",
                "type": "2" if not return_date else "1",
                "api_key": self._api_key,
            }

            if return_date:
                params["return_date"] = return_date

            # Map cabin class
            cabin_map = {
                "economy": "1",
                "premium_economy": "2",
                "business": "3",
                "first": "4",
            }
            params["travel_class"] = cabin_map.get(cabin_class, "1")

            response = requests.get(
                "https://serpapi.com/search",
                params=params,
                timeout=15,
            )
            response.raise_for_status()
            data = response.json()

            self._query_count += 1

            # Extract cheapest price from results
            result = self._parse_response(data)
            if result:
                result["cached"] = False
                self._set_cached(cache_key, result)

            return result

        except Exception as e:
            logger.error(
                "SerpAPI baseline lookup failed for %s→%s: %s",
                origin, destination, e,
            )
            return None

    def _parse_response(self, data: Dict) -> Optional[Dict[str, Any]]:
        """Extract cheapest flight from SerpAPI response."""
        # SerpAPI returns best_flights and other_flights
        best_flights = data.get("best_flights", [])
        other_flights = data.get("other_flights", [])
        all_flights = best_flights + other_flights

        if not all_flights:
            return None

        cheapest = None
        cheapest_price = float("inf")

        for flight in all_flights:
            price = flight.get("price")
            if price is not None and price < cheapest_price:
                cheapest_price = price
                cheapest = flight

        if cheapest is None:
            return None

        # Extract details
        legs = cheapest.get("flights", [])
        airline = legs[0].get("airline", "Unknown") if legs else "Unknown"
        stops = len(legs) - 1 if legs else 0
        duration = cheapest.get("total_duration", 0)

        return {
            "price_usd": float(cheapest_price),
            "airline": airline,
            "stops": stops,
            "duration_minutes": duration,
            "source": "serpapi",
        }

    def _cache_key(self, origin, destination, departure_date, return_date, cabin_class):
        raw = f"{origin}:{destination}:{departure_date}:{return_date}:{cabin_class}"
        return hashlib.md5(raw.encode()).hexdigest()

    def _get_cached(self, key: str) -> Optional[Dict]:
        entry = _baseline_cache.get(key)
        if entry and time.time() - entry["ts"] < CACHE_TTL_SECONDS:
            return dict(entry["data"])
        return None

    def _set_cached(self, key: str, data: Dict) -> None:
        _baseline_cache[key] = {"data": data, "ts": time.time()}
        # Prune old entries
        if len(_baseline_cache) > 500:
            cutoff = time.time() - CACHE_TTL_SECONDS
            stale = [k for k, v in _baseline_cache.items() if v["ts"] < cutoff]
            for k in stale:
                del _baseline_cache[k]

    @property
    def stats(self) -> Dict:
        return {
            "queries": self._query_count,
            "cache_hits": self._cache_hits,
            "cache_size": len(_baseline_cache),
            "configured": self.is_configured(),
        }


__all__ = ["USBaselineProvider"]
