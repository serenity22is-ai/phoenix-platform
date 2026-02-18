"""
MYSTES Redis Caching Layer

Provides application-level caching backed by Redis for expensive operations:
search results, exchange rates, airport lookups, and market data.

Redis DB allocation:
    DB 0 — Application cache (this module)
    DB 1 — Rate limiting (Flask-Limiter)
    DB 2 — Celery broker
    DB 3 — Celery results backend

Usage:
    from cache import cache

    # Simple key/value
    cache.set("key", {"data": 1}, ttl=300)
    val = cache.get("key")

    # Decorator for functions
    @cache.cached("flight_search", ttl=3600)
    def search_flights(origin, dest, date):
        ...

    # Specialized helpers
    cache.set_search_results(origin, dest, date, cabin, results, market=None)
    cache.get_search_results(origin, dest, date, cabin, market=None)
    cache.set_exchange_rate(currency_pair, rate)
    cache.get_exchange_rate(currency_pair)
"""

import functools
import hashlib
import json
import logging
import os
import time

logger = logging.getLogger(__name__)

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

# Default TTLs (seconds)
TTL_SEARCH_RESULTS = 4 * 3600       # 4 hours — full search results
TTL_PROXY_PRICES = 1 * 3600         # 1 hour  — proxy-scraped prices (volatile)
TTL_AMADEUS_RESULTS = 4 * 3600      # 4 hours — Amadeus API data
TTL_EXCHANGE_RATES = 2 * 3600       # 2 hours — fiat currency rates
TTL_XRP_PRICE = 600                 # 10 min  — XRP/USD price
TTL_AIRPORT_LOOKUP = 24 * 3600      # 24 hours — airport/market data
TTL_DEAL_LIST = 900                 # 15 min  — deal listings
TTL_DEFAULT = 3600                  # 1 hour  — fallback


def _get_redis():
    """Lazy Redis connection."""
    import redis
    return redis.from_url(REDIS_URL, decode_responses=True)


class CacheService:
    """Centralized Redis cache with typed helpers for Mystes data."""

    PREFIX = "mystes:cache:"

    def __init__(self):
        self._redis = None
        self._enabled = True

    @property
    def redis(self):
        if self._redis is None:
            try:
                self._redis = _get_redis()
                self._redis.ping()
            except Exception as e:
                logger.warning(f"Redis unavailable, caching disabled: {e}")
                self._enabled = False
                self._redis = None
        return self._redis

    # ------------------------------------------------------------------
    # Core get / set / delete
    # ------------------------------------------------------------------

    def get(self, key):
        """Get a cached value. Returns None on miss or error."""
        if not self._enabled:
            return None
        try:
            raw = self.redis.get(f"{self.PREFIX}{key}")
            if raw is None:
                return None
            return json.loads(raw)
        except Exception as e:
            logger.debug(f"Cache get error ({key}): {e}")
            return None

    def set(self, key, value, ttl=TTL_DEFAULT):
        """Set a cached value with TTL in seconds."""
        if not self._enabled:
            return
        try:
            self.redis.setex(
                f"{self.PREFIX}{key}",
                ttl,
                json.dumps(value, default=str),
            )
        except Exception as e:
            logger.debug(f"Cache set error ({key}): {e}")

    def delete(self, key):
        """Delete a cached key."""
        if not self._enabled:
            return
        try:
            self.redis.delete(f"{self.PREFIX}{key}")
        except Exception:
            pass

    def delete_pattern(self, pattern):
        """Delete all keys matching a pattern (use sparingly)."""
        if not self._enabled:
            return
        try:
            full_pattern = f"{self.PREFIX}{pattern}"
            cursor = 0
            while True:
                cursor, keys = self.redis.scan(cursor, match=full_pattern, count=100)
                if keys:
                    self.redis.delete(*keys)
                if cursor == 0:
                    break
        except Exception as e:
            logger.debug(f"Cache delete_pattern error ({pattern}): {e}")

    # ------------------------------------------------------------------
    # Decorator
    # ------------------------------------------------------------------

    def cached(self, namespace, ttl=TTL_DEFAULT, key_func=None):
        """Decorator that caches function return values.

        Args:
            namespace: Cache key prefix (e.g. "flight_search").
            ttl: Time-to-live in seconds.
            key_func: Optional callable(args, kwargs) -> str for custom keys.
                      Defaults to hashing all arguments.
        """
        def decorator(fn):
            @functools.wraps(fn)
            def wrapper(*args, **kwargs):
                if key_func:
                    cache_key = f"{namespace}:{key_func(args, kwargs)}"
                else:
                    raw = json.dumps(
                        {"a": args, "k": kwargs}, sort_keys=True, default=str
                    )
                    h = hashlib.md5(raw.encode()).hexdigest()
                    cache_key = f"{namespace}:{h}"

                hit = self.get(cache_key)
                if hit is not None:
                    logger.debug(f"Cache HIT: {cache_key}")
                    return hit

                result = fn(*args, **kwargs)
                if result is not None:
                    self.set(cache_key, result, ttl=ttl)
                return result
            return wrapper
        return decorator

    # ------------------------------------------------------------------
    # Flight search results
    # ------------------------------------------------------------------

    def _search_key(self, origin, destination, date, cabin, market=None):
        parts = [origin.upper(), destination.upper(), str(date), cabin.lower()]
        if market:
            parts.append(market.upper())
        return "search:" + ":".join(parts)

    def get_search_results(self, origin, destination, date, cabin="economy", market=None):
        """Retrieve cached search results for a route."""
        return self.get(self._search_key(origin, destination, date, cabin, market))

    def set_search_results(self, origin, destination, date, cabin, results,
                           market=None, ttl=None):
        """Cache search results. Uses shorter TTL for proxy-only results."""
        if ttl is None:
            ttl = TTL_PROXY_PRICES if market else TTL_SEARCH_RESULTS
        self.set(
            self._search_key(origin, destination, date, cabin, market),
            results,
            ttl=ttl,
        )

    def invalidate_search(self, origin=None, destination=None):
        """Invalidate cached searches. If no args, clears all search cache."""
        if origin and destination:
            self.delete_pattern(
                f"search:{origin.upper()}:{destination.upper()}:*"
            )
        else:
            self.delete_pattern("search:*")

    # ------------------------------------------------------------------
    # Exchange rates
    # ------------------------------------------------------------------

    def get_exchange_rate(self, pair):
        """Get cached exchange rate (e.g. 'EUR_USD')."""
        return self.get(f"forex:{pair}")

    def set_exchange_rate(self, pair, rate, ttl=TTL_EXCHANGE_RATES):
        """Cache an exchange rate."""
        self.set(f"forex:{pair}", rate, ttl=ttl)

    def get_all_exchange_rates(self):
        """Get cached full currency rate map."""
        return self.get("forex:all_rates")

    def set_all_exchange_rates(self, rates, ttl=TTL_EXCHANGE_RATES):
        """Cache entire currency rate map."""
        self.set("forex:all_rates", rates, ttl=ttl)

    def get_xrp_price(self):
        """Get cached XRP/USD price."""
        return self.get("crypto:xrp_usd")

    def set_xrp_price(self, price, ttl=TTL_XRP_PRICE):
        """Cache XRP/USD price."""
        self.set("crypto:xrp_usd", price, ttl=ttl)

    # ------------------------------------------------------------------
    # Airport / market data
    # ------------------------------------------------------------------

    def get_airport_search(self, query):
        """Get cached airport search results."""
        return self.get(f"airport:search:{query.lower().strip()}")

    def set_airport_search(self, query, results, ttl=TTL_AIRPORT_LOOKUP):
        """Cache airport search results."""
        self.set(f"airport:search:{query.lower().strip()}", results, ttl=ttl)

    def get_market_config(self, country_code):
        """Get cached market configuration."""
        return self.get(f"market:config:{country_code.upper()}")

    def set_market_config(self, country_code, config, ttl=TTL_AIRPORT_LOOKUP):
        """Cache market configuration."""
        self.set(f"market:config:{country_code.upper()}", config, ttl=ttl)

    # ------------------------------------------------------------------
    # Deal listings
    # ------------------------------------------------------------------

    def get_deals(self, filter_key="all"):
        """Get cached deal listing."""
        return self.get(f"deals:{filter_key}")

    def set_deals(self, deals, filter_key="all", ttl=TTL_DEAL_LIST):
        """Cache deal listing."""
        self.set(f"deals:{filter_key}", deals, ttl=ttl)

    def invalidate_deals(self):
        """Clear all deal caches (call after deal creation/update)."""
        self.delete_pattern("deals:*")

    # ------------------------------------------------------------------
    # Stats / diagnostics
    # ------------------------------------------------------------------

    def stats(self):
        """Return basic cache statistics."""
        if not self._enabled:
            return {"enabled": False}
        try:
            info = self.redis.info("keyspace")
            db_info = info.get("db0", {})
            keys_count = db_info.get("keys", 0) if isinstance(db_info, dict) else 0

            # Count mystes cache keys specifically
            cursor, mystes_keys = 0, 0
            while True:
                cursor, keys = self.redis.scan(
                    cursor, match=f"{self.PREFIX}*", count=500
                )
                mystes_keys += len(keys)
                if cursor == 0:
                    break

            return {
                "enabled": True,
                "total_db0_keys": keys_count,
                "mystes_cache_keys": mystes_keys,
                "redis_url": REDIS_URL.split("@")[-1] if "@" in REDIS_URL else REDIS_URL,
            }
        except Exception as e:
            return {"enabled": True, "error": str(e)}

    def flush(self):
        """Remove ALL mystes cache keys (not other Redis data)."""
        self.delete_pattern("*")


# Global cache instance
cache = CacheService()
