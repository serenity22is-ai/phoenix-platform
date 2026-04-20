"""
Market Router — POS market selection and anti-detection routing.

Determines which foreign POS markets to query for a given route,
manages rotation patterns to avoid detection, and tracks market
performance for per-route optimization (Phase 4: ANASTASiA learns
cheapest POS per route over time).

MYSTES KYRIOS LLC — Confidential.
"""

import logging
import random
import time
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# Full market config — shared reference for proxy, scraper, and arbitrage neurons
MARKET_CONFIG = {
    "US": {"timezone": "America/New_York",    "google_domain": "google.com",    "currency": "USD", "language": "en"},
    "GB": {"timezone": "Europe/London",       "google_domain": "google.co.uk",  "currency": "GBP", "language": "en"},
    "DE": {"timezone": "Europe/Berlin",       "google_domain": "google.de",     "currency": "EUR", "language": "de"},
    "FR": {"timezone": "Europe/Paris",        "google_domain": "google.fr",     "currency": "EUR", "language": "fr"},
    "JP": {"timezone": "Asia/Tokyo",          "google_domain": "google.co.jp",  "currency": "JPY", "language": "ja"},
    "AU": {"timezone": "Australia/Sydney",    "google_domain": "google.com.au", "currency": "AUD", "language": "en"},
    "CA": {"timezone": "America/Toronto",     "google_domain": "google.ca",     "currency": "CAD", "language": "en"},
    "BR": {"timezone": "America/Sao_Paulo",   "google_domain": "google.com.br", "currency": "BRL", "language": "pt"},
    "IN": {"timezone": "Asia/Kolkata",        "google_domain": "google.co.in",  "currency": "INR", "language": "en"},
    "KR": {"timezone": "Asia/Seoul",          "google_domain": "google.co.kr",  "currency": "KRW", "language": "ko"},
    "MX": {"timezone": "America/Mexico_City", "google_domain": "google.com.mx", "currency": "MXN", "language": "es"},
    "ES": {"timezone": "Europe/Madrid",       "google_domain": "google.es",     "currency": "EUR", "language": "es"},
    "IT": {"timezone": "Europe/Rome",         "google_domain": "google.it",     "currency": "EUR", "language": "it"},
    "NL": {"timezone": "Europe/Amsterdam",    "google_domain": "google.nl",     "currency": "EUR", "language": "nl"},
    "SE": {"timezone": "Europe/Stockholm",    "google_domain": "google.se",     "currency": "SEK", "language": "sv"},
    "TH": {"timezone": "Asia/Bangkok",        "google_domain": "google.co.th",  "currency": "THB", "language": "th"},
    "PL": {"timezone": "Europe/Warsaw",       "google_domain": "google.pl",     "currency": "PLN", "language": "pl"},
    "DK": {"timezone": "Europe/Copenhagen",   "google_domain": "google.dk",     "currency": "DKK", "language": "da"},
    "NO": {"timezone": "Europe/Oslo",         "google_domain": "google.no",     "currency": "NOK", "language": "no"},
    "FI": {"timezone": "Europe/Helsinki",     "google_domain": "google.fi",     "currency": "EUR", "language": "fi"},
    "CH": {"timezone": "Europe/Zurich",       "google_domain": "google.ch",     "currency": "CHF", "language": "de"},
    "AT": {"timezone": "Europe/Vienna",       "google_domain": "google.at",     "currency": "EUR", "language": "de"},
    "BE": {"timezone": "Europe/Brussels",     "google_domain": "google.be",     "currency": "EUR", "language": "nl"},
    "PT": {"timezone": "Europe/Lisbon",       "google_domain": "google.pt",     "currency": "EUR", "language": "pt"},
    "IE": {"timezone": "Europe/Dublin",       "google_domain": "google.ie",     "currency": "EUR", "language": "en"},
    "CZ": {"timezone": "Europe/Prague",       "google_domain": "google.cz",     "currency": "CZK", "language": "cs"},
    "RO": {"timezone": "Europe/Bucharest",    "google_domain": "google.ro",     "currency": "RON", "language": "ro"},
    "HU": {"timezone": "Europe/Budapest",     "google_domain": "google.hu",     "currency": "HUF", "language": "hu"},
    "SG": {"timezone": "Asia/Singapore",      "google_domain": "google.com.sg", "currency": "SGD", "language": "en"},
    "HK": {"timezone": "Asia/Hong_Kong",      "google_domain": "google.com.hk", "currency": "HKD", "language": "en"},
}

# Priority markets for POS arbitrage — proven cheapest for US-origin international flights
# Phase 1: DK (proven Feb 24 data). Phase 2: expand based on live testing.
ARBITRAGE_PRIORITY_MARKETS = ["DK", "DE", "NL", "PL", "SE", "NO", "FI"]


class MarketRouter:
    """
    Selects POS markets for arbitrage queries and manages rotation.

    Anti-detection strategy:
    - Never query the same market more than N times per minute
    - Rotate across priority markets to distribute traffic
    - Track per-route best market for optimization (Phase 4)
    - Cooldown tracking per market to avoid IP blocks
    """

    def __init__(
        self,
        priority_markets: Optional[List[str]] = None,
        max_queries_per_market_per_min: int = 30,
        cooldown_seconds: int = 2,
    ):
        self._priority_markets = priority_markets or ARBITRAGE_PRIORITY_MARKETS
        self._max_per_min = max_queries_per_market_per_min
        self._cooldown_seconds = cooldown_seconds

        # Tracking state
        self._query_counts: Dict[str, List[float]] = defaultdict(list)
        self._last_query_time: Dict[str, float] = {}
        self._route_performance: Dict[str, Dict[str, float]] = {}

    def select_markets(
        self,
        origin: str,
        destination: str,
        max_markets: int = 3,
    ) -> List[str]:
        """Select best POS markets to query for a route.

        Phase 1: Return priority markets with rotation.
        Phase 4: ANASTASiA learns cheapest POS per route.

        Args:
            origin: IATA airport code
            destination: IATA airport code
            max_markets: Max markets to query in parallel

        Returns:
            List of market codes (e.g., ["DK", "DE", "PL"])
        """
        route_key = f"{origin}-{destination}"

        # Check if we have learned performance data for this route
        if route_key in self._route_performance:
            perf = self._route_performance[route_key]
            # Sort markets by historical savings (highest first)
            ranked = sorted(perf.keys(), key=lambda m: perf[m], reverse=True)
            # Take top performers but include one random for exploration
            best = ranked[:max_markets - 1]
            # Add one unexplored market for learning
            unexplored = [
                m for m in self._priority_markets
                if m not in best and self._is_available(m)
            ]
            if unexplored:
                best.append(random.choice(unexplored))
            return best[:max_markets]

        # Phase 1: Rotate through priority markets
        available = [m for m in self._priority_markets if self._is_available(m)]
        if not available:
            # All markets on cooldown — reset and use anyway
            available = list(self._priority_markets)

        # Shuffle for distribution, take up to max_markets
        selected = random.sample(available, min(len(available), max_markets))
        return selected

    def record_result(
        self,
        origin: str,
        destination: str,
        market: str,
        spread_usd: float,
    ) -> None:
        """Record arbitrage result for per-route optimization.

        Over time, this builds a map of which POS market yields
        the best spread for each route. Phase 4: ANASTASiA uses
        this data to auto-select optimal markets.
        """
        route_key = f"{origin}-{destination}"
        if route_key not in self._route_performance:
            self._route_performance[route_key] = {}

        # Exponential moving average (alpha=0.3 for recency bias)
        alpha = 0.3
        prev = self._route_performance[route_key].get(market, spread_usd)
        self._route_performance[route_key][market] = (
            alpha * spread_usd + (1 - alpha) * prev
        )

    def record_query(self, market: str) -> None:
        """Record that a query was made to a market (for rate tracking)."""
        now = time.time()
        self._query_counts[market].append(now)
        self._last_query_time[market] = now

        # Prune old entries (older than 60 seconds)
        cutoff = now - 60
        self._query_counts[market] = [
            t for t in self._query_counts[market] if t > cutoff
        ]

    def _is_available(self, market: str) -> bool:
        """Check if a market is available (not rate-limited or on cooldown)."""
        now = time.time()

        # Check cooldown
        last = self._last_query_time.get(market, 0)
        if now - last < self._cooldown_seconds:
            return False

        # Check rate limit
        cutoff = now - 60
        recent = [t for t in self._query_counts.get(market, []) if t > cutoff]
        if len(recent) >= self._max_per_min:
            return False

        return True

    def get_market_config(self, market: str) -> Optional[Dict]:
        """Return full config for a market code."""
        return MARKET_CONFIG.get(market.upper())

    def get_all_markets(self) -> List[str]:
        """Return all configured market codes."""
        return list(MARKET_CONFIG.keys())

    def get_priority_markets(self) -> List[str]:
        """Return priority markets for arbitrage."""
        return list(self._priority_markets)

    def get_performance_stats(self) -> Dict:
        """Return per-route market performance data."""
        return dict(self._route_performance)

    @property
    def stats(self) -> Dict:
        """Return routing statistics."""
        return {
            "total_markets": len(MARKET_CONFIG),
            "priority_markets": len(self._priority_markets),
            "routes_tracked": len(self._route_performance),
            "active_queries": sum(
                len(v) for v in self._query_counts.values()
            ),
        }


__all__ = ["MarketRouter", "MARKET_CONFIG", "ARBITRAGE_PRIORITY_MARKETS"]
