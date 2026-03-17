"""
MYSTES Competitive Price Intelligence — SerpAPI Google Flights Integration

Fetches Google Flights prices and competitor booking options via SerpAPI.
Provides the benchmark pricing data that proves MYSTES beats every retail competitor.

Architecture:
    1. search_google_flights() — Get Google's best prices for a route (1 credit)
    2. get_booking_options() — Get full competitor breakdown for a specific flight (1 credit)
    3. Redis-cached via cache.py — 6hr TTL per route+date, minimizes SerpAPI spend

Cost model:
    - Developer plan: $75/mo = 5,000 searches @ $0.015/each
    - With 6hr cache: 5,000 unique routes covers 50,000-100,000+ user searches
    - Booking options: lazy-loaded on flight selection only

MYSTES KYRIOS LLC — Confidential.
"""

import hashlib
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple

import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

SERPAPI_BASE_URL = "https://serpapi.com/search"
SERPAPI_KEY = os.environ.get("SERPAPI_KEY", "")

# Cache TTLs
TTL_GOOGLE_PRICES = 6 * 3600      # 6 hours — Google Flights prices per route
TTL_BOOKING_OPTIONS = 12 * 3600   # 12 hours — competitor breakdown per flight
TTL_MARKUP_INDEX = 7 * 24 * 3600  # 7 days — learned markup patterns per route

# Cabin class mapping (MYSTES → SerpAPI)
CABIN_MAP = {
    "economy": 1,
    "premium_economy": 2,
    "business": 3,
    "first": 4,
    "ECONOMY": 1,
    "PREMIUM_ECONOMY": 2,
    "BUSINESS": 3,
    "FIRST": 4,
}


def _get_cache():
    """Get the MYSTES cache service (lazy import to avoid circular deps)."""
    try:
        from cache import cache
        return cache
    except Exception:
        return None


def _cache_key(prefix: str, *parts) -> str:
    """Build a deterministic cache key from parts."""
    raw = ":".join(str(p) for p in parts if p)
    return f"serpapi:{prefix}:{hashlib.md5(raw.encode()).hexdigest()[:16]}"


class SerpAPIClient:
    """
    SerpAPI Google Flights client for competitive price intelligence.

    Usage:
        client = SerpAPIClient()
        prices = client.search_google_flights("JFK", "LHR", "2026-04-01")
        # prices = {
        #     "flights": [{"airline": "BA", "price": 465, "booking_token": "...", ...}],
        #     "price_insights": {"lowest_price": 420, "typical_range": [400, 550]},
        #     "source": "serpapi",
        #     "cached": False,
        # }
    """

    def __init__(self, api_key: str = ""):
        self.api_key = api_key or SERPAPI_KEY
        self.cache = _get_cache()

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    def search_google_flights(
        self,
        origin: str,
        destination: str,
        date: str,
        return_date: str = None,
        cabin_class: str = "economy",
        adults: int = 1,
        currency: str = "USD",
    ) -> Dict[str, Any]:
        """
        Search Google Flights via SerpAPI for a route.

        Returns Google's best prices — the consumer benchmark.
        Results cached for 6 hours per route+date+cabin combo.

        Args:
            origin: IATA code (e.g., "JFK")
            destination: IATA code (e.g., "LHR")
            date: Departure date "YYYY-MM-DD"
            return_date: Optional return date
            cabin_class: economy/premium_economy/business/first
            adults: Number of adult passengers
            currency: Currency code

        Returns:
            Dict with 'flights' list, 'price_insights', metadata
        """
        if not self.is_configured:
            logger.debug("SerpAPI not configured (no SERPAPI_KEY)")
            return {"flights": [], "source": "unconfigured", "cached": False}

        # Check cache first
        cache_key = _cache_key("flights", origin, destination, date,
                               return_date or "", cabin_class, adults, currency)
        if self.cache:
            cached = self.cache.get(cache_key)
            if cached:
                cached["cached"] = True
                logger.info("SerpAPI cache HIT: %s→%s %s", origin, destination, date)
                return cached

        # Build SerpAPI request
        trip_type = 1 if return_date else 2  # 1=round trip, 2=one way
        params = {
            "engine": "google_flights",
            "departure_id": origin.upper(),
            "arrival_id": destination.upper(),
            "outbound_date": date,
            "type": trip_type,
            "travel_class": CABIN_MAP.get(cabin_class, 1),
            "adults": adults,
            "currency": currency,
            "hl": "en",
            "api_key": self.api_key,
        }
        if return_date:
            params["return_date"] = return_date

        try:
            logger.info("SerpAPI search: %s→%s %s (1 credit)", origin, destination, date)
            resp = requests.get(SERPAPI_BASE_URL, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            if "error" in data:
                logger.error("SerpAPI error: %s", data["error"])
                return {"flights": [], "source": "serpapi_error",
                        "error": data["error"], "cached": False}

            result = self._parse_flight_results(data)
            result["source"] = "serpapi"
            result["cached"] = False
            result["timestamp"] = time.time()

            # Cache the result
            if self.cache and result["flights"]:
                self.cache.set(cache_key, result, ttl=TTL_GOOGLE_PRICES)
                logger.info("SerpAPI cached: %s→%s %s (%d flights)",
                            origin, destination, date, len(result["flights"]))

            return result

        except requests.Timeout:
            logger.warning("SerpAPI timeout: %s→%s %s", origin, destination, date)
            return {"flights": [], "source": "timeout", "cached": False}
        except requests.RequestException as e:
            logger.error("SerpAPI request failed: %s", e)
            return {"flights": [], "source": "error", "error": str(e), "cached": False}

    def get_booking_options(self, booking_token: str) -> Dict[str, Any]:
        """
        Get competitor booking options for a specific flight.

        This shows prices from airlines, Expedia, Priceline, and other OTAs.
        Called lazily when user selects/expands a flight card (1 credit per call).

        Args:
            booking_token: Token from search results (per flight group)

        Returns:
            Dict with 'options' list of {name, price, is_airline, url}
        """
        if not self.is_configured or not booking_token:
            return {"options": [], "source": "unconfigured"}

        # Check cache
        cache_key = _cache_key("booking", booking_token)
        if self.cache:
            cached = self.cache.get(cache_key)
            if cached:
                cached["cached"] = True
                return cached

        params = {
            "engine": "google_flights",
            "booking_token": booking_token,
            "currency": "USD",
            "hl": "en",
            "api_key": self.api_key,
        }

        try:
            logger.info("SerpAPI booking options (1 credit)")
            resp = requests.get(SERPAPI_BASE_URL, params=params, timeout=20)
            resp.raise_for_status()
            data = resp.json()

            options = self._parse_booking_options(data)
            result = {
                "options": options,
                "source": "serpapi",
                "cached": False,
                "timestamp": time.time(),
            }

            if self.cache and options:
                self.cache.set(cache_key, result, ttl=TTL_BOOKING_OPTIONS)

            return result

        except Exception as e:
            logger.error("SerpAPI booking options failed: %s", e)
            return {"options": [], "source": "error", "error": str(e)}

    def _parse_flight_results(self, data: dict) -> dict:
        """Parse SerpAPI Google Flights response into normalized format."""
        flights = []

        # Process best_flights and other_flights
        for group_key in ("best_flights", "other_flights"):
            for group in data.get(group_key, []):
                flight_info = self._parse_flight_group(group)
                if flight_info:
                    flights.append(flight_info)

        # Price insights
        insights = data.get("price_insights", {})
        price_insights = {}
        if insights:
            price_insights = {
                "lowest_price": insights.get("lowest_price"),
                "typical_range": [
                    insights.get("typical_price_range", [None, None])[0],
                    insights.get("typical_price_range", [None, None])[1],
                ] if insights.get("typical_price_range") else None,
                "price_level": insights.get("price_level"),
            }

        return {
            "flights": flights,
            "price_insights": price_insights,
            "total_flights": len(flights),
        }

    def _parse_flight_group(self, group: dict) -> Optional[dict]:
        """Parse a single flight group from SerpAPI results."""
        legs = group.get("flights", [])
        if not legs:
            return None

        first_leg = legs[0]
        last_leg = legs[-1]

        # Extract airline name
        airline = first_leg.get("airline", "")

        # Build departure/arrival times
        dep_time = first_leg.get("departure_airport", {}).get("time", "")
        arr_time = last_leg.get("arrival_airport", {}).get("time", "")

        # Flight number
        flight_number = first_leg.get("flight_number", "")

        # Stops
        stops = len(legs) - 1

        # Layover info
        layovers = []
        for layover in group.get("layovers", []):
            airport = layover.get("name", "")
            duration = layover.get("duration")
            dur_str = f"{duration // 60}h {duration % 60}m" if duration else ""
            layovers.append(f"{airport} ({dur_str})" if dur_str else airport)

        # Duration
        total_duration = group.get("total_duration", 0)
        dur_h = total_duration // 60
        dur_m = total_duration % 60
        duration_str = f"{dur_h}h {dur_m}m" if total_duration else ""

        # Price
        price = group.get("price")
        if price is None:
            return None

        return {
            "airline": airline,
            "flight_number": flight_number,
            "departure_time": dep_time,
            "arrival_time": arr_time,
            "duration": duration_str,
            "total_duration_min": total_duration,
            "stops": stops,
            "layovers": layovers,
            "price": price,
            "booking_token": group.get("booking_token", ""),
            "carbon_emissions": group.get("carbon_emissions", {}).get("this_flight"),
            "extensions": group.get("extensions", []),
            "airline_logo": first_leg.get("airline_logo", ""),
        }

    def _parse_booking_options(self, data: dict) -> List[dict]:
        """Parse booking options into normalized competitor prices."""
        options = []

        for bo in data.get("booking_options", []):
            # Can have multiple tickets for split bookings
            for ticket_group in [bo] if "book_with" in bo else []:
                name = ticket_group.get("book_with", "Unknown")
                price = ticket_group.get("price")
                if price is None:
                    continue

                options.append({
                    "name": name,
                    "price": price,
                    "is_airline": ticket_group.get("airline", False),
                    "extensions": ticket_group.get("extensions", []),
                })

            # Also handle nested together/departing/returning structure
            for key in ("together", "departing", "returning"):
                for nested in bo.get(key, []) if isinstance(bo.get(key), list) else []:
                    name = nested.get("book_with", "Unknown")
                    price = nested.get("price")
                    if price is not None:
                        options.append({
                            "name": name,
                            "price": price,
                            "is_airline": nested.get("airline", False),
                            "extensions": nested.get("extensions", []),
                        })

        # Sort by price ascending
        options.sort(key=lambda x: x.get("price", float("inf")))
        return options


def build_competitor_comparison(
    mystes_price: float,
    google_flights: List[dict],
    booking_options: List[dict] = None,
) -> dict:
    """
    Build the competitive price comparison object for a deal card.

    Args:
        mystes_price: MYSTES final price (wholesale + platform fee)
        google_flights: Google Flights results for matching
        booking_options: Optional booking options from get_booking_options()

    Returns:
        Dict with competitor prices and comparison metrics.
    """
    comparison = {
        "mystes_price": round(mystes_price, 2),
        "competitors": [],
        "beats_all": True,
        "savings_vs_cheapest": 0,
        "savings_vs_google": 0,
    }

    # Add Google Flights as a competitor
    if google_flights:
        # Find cheapest Google price
        cheapest_google = min(
            (f.get("price", float("inf")) for f in google_flights),
            default=None,
        )
        if cheapest_google and cheapest_google < float("inf"):
            comparison["competitors"].append({
                "name": "Google Flights",
                "price": round(cheapest_google, 2),
                "is_airline": False,
                "is_google": True,
            })
            comparison["savings_vs_google"] = round(cheapest_google - mystes_price, 2)

    # Add booking options as competitors
    if booking_options:
        seen_names = {"Google Flights"}
        for opt in booking_options:
            name = opt.get("name", "")
            if name in seen_names:
                continue
            seen_names.add(name)
            price = opt.get("price")
            if price and price > 0:
                comparison["competitors"].append({
                    "name": name,
                    "price": round(price, 2),
                    "is_airline": opt.get("is_airline", False),
                    "is_google": False,
                })

    # Sort competitors by price
    comparison["competitors"].sort(key=lambda x: x["price"])

    # Calculate if MYSTES beats all
    if comparison["competitors"]:
        cheapest_competitor = comparison["competitors"][0]["price"]
        comparison["beats_all"] = mystes_price < cheapest_competitor
        comparison["savings_vs_cheapest"] = round(cheapest_competitor - mystes_price, 2)

    return comparison


# Module-level singleton
_client = None


def get_serpapi_client() -> SerpAPIClient:
    """Get or create the SerpAPI client singleton."""
    global _client
    if _client is None:
        _client = SerpAPIClient()
    return _client
