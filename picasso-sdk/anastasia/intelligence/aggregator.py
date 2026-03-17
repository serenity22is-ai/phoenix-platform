"""
Pricing Aggregator — Anonymized pricing data collection and analysis.

Collects and aggregates price observations across all ANASTASiA installations.
All data is fully anonymized: no agency IDs, no customer data, no booking
references. Only route + price + timestamp + cabin class are stored.

Data is persisted as daily JSON files and auto-cleaned after 365 days.
Provides statistical queries: averages, distributions, route comparisons,
cheapest routes, and market overviews.

MYSTES KYRIOS LLC — Confidential.
"""

import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.events import Event, EventBus, EventType

logger = logging.getLogger(__name__)

# Fields that must NEVER appear in stored data
_SENSITIVE_FIELDS = frozenset({
    "agency_id", "customer_id", "user_id", "booking_id", "pnr",
    "email", "phone", "name", "passport", "credit_card", "ip_address",
    "session_id", "token", "api_key",
})

# Maximum age for stored price data (days)
_MAX_DATA_AGE_DAYS = 365


class PricingAggregator:
    """
    Anonymized pricing data aggregation engine.

    Records price observations stripped of all identifying information and
    provides statistical analysis: averages, percentile distributions, route
    comparisons, cheapest-destination rankings, and market overviews.

    Data is stored as daily JSON files in the configured storage directory.
    Files older than 365 days are automatically purged on initialization and
    periodically during operation.

    Args:
        event_bus: EventBus instance for publishing pricing events.
        storage_dir: Path to the directory for storing daily price files.
                     Defaults to ``~/.anastasia/intelligence/prices``.

    Usage:
        aggregator = PricingAggregator(event_bus)
        aggregator.record_price("JFK-LHR", 450.0, "USD", "picasso")
        stats = aggregator.get_average_price("JFK-LHR", period_days=30)
    """

    def __init__(
        self,
        event_bus: EventBus,
        storage_dir: Optional[str] = None,
    ):
        self._event_bus = event_bus
        self._lock = threading.Lock()

        if storage_dir is None:
            storage_dir = os.path.join(
                os.path.expanduser("~"), ".anastasia", "intelligence", "prices"
            )
        self._storage_dir = Path(storage_dir)
        self._storage_dir.mkdir(parents=True, exist_ok=True)

        # In-memory cache of today's observations for fast writes
        self._today_key: str = self._date_key()
        self._today_cache: List[Dict[str, Any]] = []

        # Load today's data if it exists
        self._load_today()

        # Auto-cleanup old data
        self._cleanup_old_data()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record_price(
        self,
        route: str,
        price: float,
        currency: str,
        source: str,
        cabin: str = "economy",
        timestamp: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Record an anonymized price observation.

        No agency IDs, customer data, or booking references are stored.
        Only the route, price, currency, source identifier, cabin class,
        and timestamp are persisted.

        Args:
            route: Route identifier (e.g. ``"JFK-LHR"``).
            price: Observed price as a float.
            currency: ISO 4217 currency code (e.g. ``"USD"``).
            source: Data source identifier (e.g. ``"picasso"``, ``"liteapi"``).
            cabin: Cabin class (e.g. ``"economy"``, ``"business"``).
                   Defaults to ``"economy"``.
            timestamp: Unix timestamp of the observation. Defaults to now.

        Returns:
            The anonymized observation dict that was stored.
        """
        if timestamp is None:
            timestamp = time.time()

        observation = {
            "route": route.upper().strip(),
            "price": round(float(price), 2),
            "currency": currency.upper().strip(),
            "source": source.strip(),
            "cabin": cabin.lower().strip(),
            "timestamp": timestamp,
        }

        # Ensure anonymization
        observation = self._anonymize(observation)

        with self._lock:
            # Roll over to new day if needed
            current_key = self._date_key()
            if current_key != self._today_key:
                self._flush_today()
                self._today_key = current_key
                self._today_cache = []

            self._today_cache.append(observation)

            # Flush to disk every 100 observations for durability
            if len(self._today_cache) % 100 == 0:
                self._flush_today()

        logger.debug(
            "Recorded price: %s %s %.2f %s",
            observation["route"], observation["currency"],
            observation["price"], observation["cabin"],
        )
        return observation

    def get_average_price(
        self,
        route: str,
        period_days: int = 30,
    ) -> Dict[str, Any]:
        """
        Calculate average price statistics for a route over a time period.

        Args:
            route: Route identifier (e.g. ``"JFK-LHR"``).
            period_days: Number of days to look back. Defaults to 30.

        Returns:
            Dict with keys: ``route``, ``avg_price``, ``min``, ``max``,
            ``samples``, ``currency``. Returns zeros and ``samples=0``
            if no data is found.
        """
        route = route.upper().strip()
        observations = self._get_observations(route, period_days)

        if not observations:
            return {
                "route": route,
                "avg_price": 0.0,
                "min": 0.0,
                "max": 0.0,
                "samples": 0,
                "currency": "USD",
            }

        prices = [obs["price"] for obs in observations]
        # Use the most common currency in the dataset
        currency = self._most_common_currency(observations)

        return {
            "route": route,
            "avg_price": round(sum(prices) / len(prices), 2),
            "min": round(min(prices), 2),
            "max": round(max(prices), 2),
            "samples": len(prices),
            "currency": currency,
        }

    def get_price_distribution(
        self,
        route: str,
        period_days: int = 30,
    ) -> Dict[str, Any]:
        """
        Calculate price percentile distribution for a route.

        Args:
            route: Route identifier (e.g. ``"JFK-LHR"``).
            period_days: Number of days to look back. Defaults to 30.

        Returns:
            Dict with percentile keys: ``p10``, ``p25``, ``p50`` (median),
            ``p75``, ``p90``, plus ``route``, ``samples``, ``currency``.
        """
        route = route.upper().strip()
        observations = self._get_observations(route, period_days)

        if not observations:
            return {
                "route": route,
                "p10": 0.0,
                "p25": 0.0,
                "p50": 0.0,
                "p75": 0.0,
                "p90": 0.0,
                "samples": 0,
                "currency": "USD",
            }

        prices = sorted([obs["price"] for obs in observations])
        currency = self._most_common_currency(observations)

        return {
            "route": route,
            "p10": round(self._percentile(prices, 10), 2),
            "p25": round(self._percentile(prices, 25), 2),
            "p50": round(self._percentile(prices, 50), 2),
            "p75": round(self._percentile(prices, 75), 2),
            "p90": round(self._percentile(prices, 90), 2),
            "samples": len(prices),
            "currency": currency,
        }

    def get_route_comparison(
        self,
        routes: List[str],
    ) -> List[Dict[str, Any]]:
        """
        Compare pricing statistics across multiple routes.

        Calculates 30-day average, min, max, and sample count for each
        route. Results are sorted by average price ascending (cheapest first).

        Args:
            routes: List of route identifiers to compare.

        Returns:
            List of dicts, each containing route stats. Sorted by
            ``avg_price`` ascending.
        """
        results = []
        for route in routes:
            stats = self.get_average_price(route, period_days=30)
            results.append(stats)

        # Sort by average price ascending
        results.sort(key=lambda r: r["avg_price"])
        return results

    def get_cheapest_routes(
        self,
        origin: str,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Find the cheapest destination routes from a given origin.

        Scans all stored observations for routes originating from the
        specified airport code and returns the cheapest by average price.

        Args:
            origin: Origin airport code (e.g. ``"JFK"``).
            limit: Maximum number of routes to return. Defaults to 10.

        Returns:
            List of route stats dicts, sorted by average price ascending.
        """
        origin = origin.upper().strip()
        all_observations = self._get_all_observations(period_days=30)

        # Group by route, filtering for routes from this origin
        route_prices: Dict[str, List[Dict[str, Any]]] = {}
        for obs in all_observations:
            route = obs.get("route", "")
            # Match routes starting with the origin code
            if route.startswith(origin + "-") or route.startswith(origin + " "):
                if route not in route_prices:
                    route_prices[route] = []
                route_prices[route].append(obs)

        # Calculate stats per route
        results = []
        for route, observations in route_prices.items():
            prices = [obs["price"] for obs in observations]
            currency = self._most_common_currency(observations)
            results.append({
                "route": route,
                "avg_price": round(sum(prices) / len(prices), 2),
                "min": round(min(prices), 2),
                "max": round(max(prices), 2),
                "samples": len(prices),
                "currency": currency,
            })

        # Sort by average price ascending and limit
        results.sort(key=lambda r: r["avg_price"])
        return results[:limit]

    def get_market_overview(
        self,
        region: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Generate high-level market statistics.

        Provides an overview of all pricing data: total observations,
        unique routes, average prices by cabin class, and data coverage.
        Optionally filtered by region prefix (e.g. ``"US"`` for US origins).

        Args:
            region: Optional region prefix to filter routes (e.g. ``"US"``
                    would match routes like ``"JFK-..."``). If ``None``,
                    all routes are included.

        Returns:
            Dict with market statistics including ``total_observations``,
            ``unique_routes``, ``avg_by_cabin``, ``date_range``, and
            ``top_routes``.
        """
        all_observations = self._get_all_observations(period_days=90)

        if region:
            region = region.upper().strip()
            # US region matches common US airport prefixes
            us_airports = {
                "JFK", "LAX", "ORD", "ATL", "DFW", "DEN", "SFO", "SEA",
                "MIA", "BOS", "EWR", "IAH", "PHX", "MSP", "DTW", "FLL",
                "MCO", "CLT", "LGA", "IAD", "SLC", "SAN", "TPA", "BWI",
                "AUS", "STL", "HNL", "PDX", "MCI", "RDU", "CLE", "SMF",
                "SJC", "OAK", "PIT", "CVG", "IND", "CMH", "BNA", "MKE",
            }
            if region == "US":
                all_observations = [
                    obs for obs in all_observations
                    if obs.get("route", "").split("-")[0] in us_airports
                ]
            else:
                all_observations = [
                    obs for obs in all_observations
                    if obs.get("route", "").startswith(region)
                ]

        if not all_observations:
            return {
                "total_observations": 0,
                "unique_routes": 0,
                "avg_by_cabin": {},
                "date_range": {"start": None, "end": None},
                "top_routes": [],
                "region": region,
            }

        # Group by cabin class
        cabin_prices: Dict[str, List[float]] = {}
        route_counts: Dict[str, int] = {}
        timestamps = []

        for obs in all_observations:
            cabin = obs.get("cabin", "economy")
            price = obs.get("price", 0.0)
            route = obs.get("route", "")
            ts = obs.get("timestamp", 0)

            if cabin not in cabin_prices:
                cabin_prices[cabin] = []
            cabin_prices[cabin].append(price)

            route_counts[route] = route_counts.get(route, 0) + 1
            timestamps.append(ts)

        # Average by cabin
        avg_by_cabin = {}
        for cabin, prices in cabin_prices.items():
            avg_by_cabin[cabin] = round(sum(prices) / len(prices), 2)

        # Top routes by observation count
        top_routes = sorted(
            route_counts.items(), key=lambda x: x[1], reverse=True
        )[:10]

        return {
            "total_observations": len(all_observations),
            "unique_routes": len(route_counts),
            "avg_by_cabin": avg_by_cabin,
            "date_range": {
                "start": min(timestamps) if timestamps else None,
                "end": max(timestamps) if timestamps else None,
            },
            "top_routes": [
                {"route": r, "observations": c} for r, c in top_routes
            ],
            "region": region,
        }

    def flush(self) -> None:
        """Force flush the in-memory cache to disk."""
        with self._lock:
            self._flush_today()

    # ------------------------------------------------------------------
    # Anonymization
    # ------------------------------------------------------------------

    def _anonymize(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Strip any identifying information from a data dict.

        Removes all fields listed in ``_SENSITIVE_FIELDS`` and any field
        whose value looks like an email address or API key. This is the
        last line of defense — callers should not pass sensitive data in
        the first place, but this method ensures nothing leaks to disk.

        Args:
            data: The data dict to sanitize.

        Returns:
            A new dict with sensitive fields removed.
        """
        cleaned = {}
        for key, value in data.items():
            # Skip known sensitive field names
            if key.lower() in _SENSITIVE_FIELDS:
                continue

            # Skip values that look like emails
            if isinstance(value, str) and "@" in value and "." in value:
                continue

            # Skip values that look like API keys (long hex/base64 strings)
            if (
                isinstance(value, str)
                and len(value) > 30
                and not value.startswith("http")
            ):
                continue

            cleaned[key] = value

        return cleaned

    # ------------------------------------------------------------------
    # Storage internals
    # ------------------------------------------------------------------

    @staticmethod
    def _date_key(ts: Optional[float] = None) -> str:
        """Generate a date key string (YYYY-MM-DD) for file naming."""
        if ts is None:
            dt = datetime.now(timezone.utc)
        else:
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        return dt.strftime("%Y-%m-%d")

    def _file_path(self, date_key: str) -> Path:
        """Get the file path for a given date key."""
        return self._storage_dir / f"prices_{date_key}.json"

    def _flush_today(self) -> None:
        """Write today's cache to disk (must hold lock)."""
        if not self._today_cache:
            return

        file_path = self._file_path(self._today_key)

        # Load existing data for today if file exists
        existing: List[Dict[str, Any]] = []
        if file_path.exists():
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except (json.JSONDecodeError, OSError):
                existing = []

        # Merge and write
        merged = existing + self._today_cache
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(merged, f, ensure_ascii=False)
        except OSError as e:
            logger.error("Failed to flush price data to %s: %s", file_path, e)
            return

        # Clear the cache (data is now on disk)
        self._today_cache = []

    def _load_today(self) -> None:
        """Load today's data file into the cache."""
        file_path = self._file_path(self._today_key)
        if file_path.exists():
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    self._today_cache = json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Failed to load today's price data: %s", e)
                self._today_cache = []

    def _get_observations(
        self,
        route: str,
        period_days: int,
    ) -> List[Dict[str, Any]]:
        """
        Load all observations for a route within a time period.

        Reads from disk files for historical days and from the in-memory
        cache for today.
        """
        cutoff = time.time() - (period_days * 86400)
        observations = []

        # Flush current cache to ensure consistency
        with self._lock:
            self._flush_today()

        # Iterate over date files in the period
        for day_offset in range(period_days + 1):
            dt = datetime.now(timezone.utc) - timedelta(days=day_offset)
            date_key = dt.strftime("%Y-%m-%d")
            file_path = self._file_path(date_key)

            if not file_path.exists():
                continue

            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    day_data = json.load(f)
            except (json.JSONDecodeError, OSError):
                continue

            for obs in day_data:
                if (
                    obs.get("route") == route
                    and obs.get("timestamp", 0) >= cutoff
                ):
                    observations.append(obs)

        return observations

    def _get_all_observations(
        self,
        period_days: int,
    ) -> List[Dict[str, Any]]:
        """
        Load all observations across all routes within a time period.
        """
        cutoff = time.time() - (period_days * 86400)
        observations = []

        # Flush current cache to ensure consistency
        with self._lock:
            self._flush_today()

        for day_offset in range(period_days + 1):
            dt = datetime.now(timezone.utc) - timedelta(days=day_offset)
            date_key = dt.strftime("%Y-%m-%d")
            file_path = self._file_path(date_key)

            if not file_path.exists():
                continue

            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    day_data = json.load(f)
            except (json.JSONDecodeError, OSError):
                continue

            for obs in day_data:
                if obs.get("timestamp", 0) >= cutoff:
                    observations.append(obs)

        return observations

    def _cleanup_old_data(self) -> None:
        """Remove price data files older than _MAX_DATA_AGE_DAYS."""
        cutoff_date = datetime.now(timezone.utc) - timedelta(
            days=_MAX_DATA_AGE_DAYS
        )
        cutoff_str = cutoff_date.strftime("%Y-%m-%d")
        removed = 0

        try:
            for file_path in self._storage_dir.glob("prices_*.json"):
                # Extract date from filename: prices_YYYY-MM-DD.json
                name = file_path.stem  # prices_YYYY-MM-DD
                date_part = name.replace("prices_", "")
                if date_part < cutoff_str:
                    file_path.unlink()
                    removed += 1
        except OSError as e:
            logger.warning("Error during price data cleanup: %s", e)

        if removed:
            logger.info(
                "Cleaned up %d old price data files (>%d days)",
                removed, _MAX_DATA_AGE_DAYS,
            )

    # ------------------------------------------------------------------
    # Statistics helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _percentile(sorted_values: List[float], pct: int) -> float:
        """
        Calculate a percentile value from a sorted list.

        Uses linear interpolation between the two closest data points.

        Args:
            sorted_values: Pre-sorted list of floats.
            pct: Percentile to calculate (0-100).

        Returns:
            The interpolated percentile value.
        """
        if not sorted_values:
            return 0.0

        n = len(sorted_values)
        if n == 1:
            return sorted_values[0]

        # Linear interpolation
        k = (pct / 100.0) * (n - 1)
        lower = int(k)
        upper = lower + 1

        if upper >= n:
            return sorted_values[-1]

        fraction = k - lower
        return sorted_values[lower] + fraction * (
            sorted_values[upper] - sorted_values[lower]
        )

    @staticmethod
    def _most_common_currency(
        observations: List[Dict[str, Any]],
    ) -> str:
        """Return the most frequently occurring currency in observations."""
        counts: Dict[str, int] = {}
        for obs in observations:
            curr = obs.get("currency", "USD")
            counts[curr] = counts.get(curr, 0) + 1

        if not counts:
            return "USD"

        return max(counts, key=counts.get)
