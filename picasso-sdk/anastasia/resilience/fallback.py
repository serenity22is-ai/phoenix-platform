"""
Fallback Manager — Cached results and graceful degradation for service failures.

When a primary data source is unavailable, the FallbackManager provides:
  1. Transparent cache layer — results are cached to disk as JSON with TTL.
  2. Named fallback functions — register alternative data sources per service.
  3. ``with_fallback()`` combinator — try primary, then fallback, then cache.
  4. LRU eviction — disk cache stays bounded (default 100 MB).
  5. Hit/miss tracking — monitor cache effectiveness over time.

Cache entries are stored as individual JSON files in ``cache_dir``, each
containing the payload plus expiry metadata. This survives process restarts
and is easy to inspect for debugging.

MYSTES KYRIOS LLC — Confidential.
"""

import fnmatch
import hashlib
import json
import logging
import os
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from ..core.events import Event, EventBus, EventType

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_key(key: str) -> str:
    """
    Convert an arbitrary cache key into a filesystem-safe filename.

    Uses SHA-256 so keys of any length/content map to a fixed-length
    hex string. The original key is stored inside the JSON envelope
    for human readability.
    """
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# FallbackManager
# ---------------------------------------------------------------------------

class FallbackManager:
    """
    Manages fallback strategies and a persistent disk cache.

    Parameters
    ----------
    event_bus : EventBus
        Used to publish ``FALLBACK_ACTIVATED`` events.
    cache_dir : str
        Directory for JSON cache files.  Created automatically if missing.
    cache_ttl : int
        Default time-to-live for cache entries, in seconds (default 3600).
    max_cache_bytes : int
        Maximum total size of cache files on disk.  When exceeded, the
        least-recently-used entries are evicted (default 100 MB).
    """

    def __init__(
        self,
        event_bus: EventBus,
        cache_dir: str,
        cache_ttl: int = 3600,
        max_cache_bytes: int = 100 * 1024 * 1024,
    ):
        self._event_bus = event_bus
        self._cache_dir = cache_dir
        self._default_ttl = cache_ttl
        self._max_cache_bytes = max_cache_bytes

        # Named fallback functions keyed by service name
        self._fallbacks: Dict[str, Callable] = {}
        self._lock = threading.Lock()

        # Hit/miss counters
        self._hits: int = 0
        self._misses: int = 0

        # Ensure cache directory exists
        os.makedirs(self._cache_dir, exist_ok=True)

    # -----------------------------------------------------------------
    # Cache operations
    # -----------------------------------------------------------------

    def cache_result(self, key: str, data: Any, ttl: int = None) -> None:
        """
        Store *data* in the cache under *key*.

        Parameters
        ----------
        key : str
            Logical cache key (hashed for the filename).
        data : Any
            JSON-serializable payload.
        ttl : int, optional
            Override the default TTL for this entry.
        """
        ttl = ttl if ttl is not None else self._default_ttl
        envelope = {
            "key": key,
            "data": data,
            "created_at": time.time(),
            "expires_at": time.time() + ttl,
            "ttl": ttl,
        }
        filepath = self._key_path(key)
        try:
            with open(filepath, "w", encoding="utf-8") as fh:
                json.dump(envelope, fh, default=str)
            logger.debug("Cached result for key '%s' (ttl=%ds)", key, ttl)
        except (OSError, TypeError) as exc:
            logger.error("Failed to cache result for '%s': %s", key, exc)

        # Evict if over budget
        self._evict_if_needed()

    def get_cached(self, key: str) -> Any:
        """
        Return the cached value for *key*, or ``None`` if expired / missing.
        """
        filepath = self._key_path(key)
        if not os.path.exists(filepath):
            self._misses += 1
            return None

        try:
            with open(filepath, "r", encoding="utf-8") as fh:
                envelope = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Corrupt cache entry '%s': %s", key, exc)
            self._misses += 1
            return None

        if time.time() > envelope.get("expires_at", 0):
            # Expired — clean up
            self._remove_file(filepath)
            self._misses += 1
            return None

        # Touch the file so LRU eviction keeps it around
        try:
            os.utime(filepath, None)
        except OSError:
            pass

        self._hits += 1
        return envelope.get("data")

    def clear_cache(self, pattern: str = None) -> int:
        """
        Clear cache entries.

        Parameters
        ----------
        pattern : str, optional
            If provided, only entries whose original key matches this
            ``fnmatch`` pattern are removed.  If ``None``, **all** entries
            are removed.

        Returns
        -------
        int
            Number of entries removed.
        """
        removed = 0
        for filename in self._list_cache_files():
            filepath = os.path.join(self._cache_dir, filename)
            if pattern is not None:
                # Need to read the envelope to check the original key
                try:
                    with open(filepath, "r", encoding="utf-8") as fh:
                        envelope = json.load(fh)
                    original_key = envelope.get("key", "")
                    if not fnmatch.fnmatch(original_key, pattern):
                        continue
                except (OSError, json.JSONDecodeError):
                    pass  # Remove corrupt files regardless
            self._remove_file(filepath)
            removed += 1

        logger.info(
            "Cleared %d cache entries%s",
            removed,
            f" matching '{pattern}'" if pattern else "",
        )
        return removed

    def get_cache_stats(self) -> dict:
        """
        Return cache statistics.

        Returns
        -------
        dict
            ``entries``: number of cache files,
            ``size_bytes``: total size on disk,
            ``hit_rate``: float between 0.0 and 1.0 (or 0.0 if no lookups).
        """
        files = self._list_cache_files()
        total_size = 0
        for filename in files:
            try:
                total_size += os.path.getsize(
                    os.path.join(self._cache_dir, filename)
                )
            except OSError:
                pass

        total_lookups = self._hits + self._misses
        hit_rate = self._hits / total_lookups if total_lookups > 0 else 0.0

        return {
            "entries": len(files),
            "size_bytes": total_size,
            "max_size_bytes": self._max_cache_bytes,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(hit_rate, 4),
        }

    # -----------------------------------------------------------------
    # Fallback registration
    # -----------------------------------------------------------------

    def register_fallback(self, service_name: str, fallback_func: Callable) -> None:
        """
        Register a named fallback function for a service.

        Parameters
        ----------
        service_name : str
            Identifier for the service (e.g. ``"picasso"``, ``"liteapi"``).
        fallback_func : callable
            Called with the same arguments as the primary function when the
            primary fails.
        """
        with self._lock:
            self._fallbacks[service_name] = fallback_func
            logger.info("Registered fallback for service '%s'", service_name)

    def get_fallback(self, service_name: str) -> Optional[Callable]:
        """Return the registered fallback for *service_name*, or ``None``."""
        with self._lock:
            return self._fallbacks.get(service_name)

    # -----------------------------------------------------------------
    # Composite execution
    # -----------------------------------------------------------------

    def with_fallback(
        self,
        primary_func: Callable,
        fallback_func: Callable = None,
        cache_key: str = None,
    ) -> Any:
        """
        Execute *primary_func* with automatic fallback.

        Strategy (in order):
          1. Call ``primary_func()``.  If it succeeds, cache the result
             (when *cache_key* is provided) and return it.
          2. If ``primary_func`` raises, try ``fallback_func()`` if given.
          3. If ``fallback_func`` also fails (or is ``None``), try the cache.
          4. If the cache is also empty, re-raise the original exception.

        Parameters
        ----------
        primary_func : callable
            The preferred data source.
        fallback_func : callable, optional
            Alternative data source.
        cache_key : str, optional
            If provided, successful results are cached and stale cache is
            used as a last-resort fallback.

        Returns
        -------
        Any
            The result from whichever source succeeded.

        Raises
        ------
        Exception
            The original exception from ``primary_func`` if all fallbacks
            also fail.
        """
        # --- Attempt 1: primary ---
        try:
            result = primary_func()
            if cache_key:
                self.cache_result(cache_key, result)
            return result
        except Exception as primary_exc:
            logger.warning(
                "Primary function failed: %s — trying fallback",
                primary_exc,
            )

        # --- Attempt 2: explicit fallback ---
        if fallback_func is not None:
            try:
                result = fallback_func()
                self._publish_fallback_activated(
                    "explicit_fallback", str(primary_exc)
                )
                if cache_key:
                    self.cache_result(cache_key, result)
                return result
            except Exception as fallback_exc:
                logger.warning(
                    "Fallback function also failed: %s — trying cache",
                    fallback_exc,
                )

        # --- Attempt 3: stale cache ---
        if cache_key:
            cached = self._get_cached_stale(cache_key)
            if cached is not None:
                self._publish_fallback_activated("stale_cache", str(primary_exc))
                logger.info(
                    "Serving stale cache for key '%s' after all sources failed",
                    cache_key,
                )
                return cached

        # --- Nothing worked ---
        raise primary_exc  # noqa: F821 — re-raise original

    # -----------------------------------------------------------------
    # Private helpers
    # -----------------------------------------------------------------

    def _key_path(self, key: str) -> str:
        """Filesystem path for a cache key."""
        return os.path.join(self._cache_dir, _safe_key(key) + ".json")

    def _list_cache_files(self) -> List[str]:
        """List all ``.json`` files in the cache directory."""
        try:
            return [
                f for f in os.listdir(self._cache_dir)
                if f.endswith(".json")
            ]
        except OSError:
            return []

    @staticmethod
    def _remove_file(path: str) -> None:
        try:
            os.remove(path)
        except OSError:
            pass

    def _get_cached_stale(self, key: str) -> Any:
        """
        Get a cached value even if it is expired (stale cache for last-resort
        fallback).  Returns ``None`` if the file doesn't exist at all.
        """
        filepath = self._key_path(key)
        if not os.path.exists(filepath):
            return None
        try:
            with open(filepath, "r", encoding="utf-8") as fh:
                envelope = json.load(fh)
            return envelope.get("data")
        except (OSError, json.JSONDecodeError):
            return None

    def _evict_if_needed(self) -> None:
        """
        If total cache size exceeds ``_max_cache_bytes``, delete the
        oldest-accessed files until we're under budget.
        """
        files_with_info: List[tuple] = []
        total_size = 0

        for filename in self._list_cache_files():
            filepath = os.path.join(self._cache_dir, filename)
            try:
                stat = os.stat(filepath)
                files_with_info.append((filepath, stat.st_size, stat.st_atime))
                total_size += stat.st_size
            except OSError:
                continue

        if total_size <= self._max_cache_bytes:
            return

        # Sort by access time ascending (oldest accessed first)
        files_with_info.sort(key=lambda x: x[2])

        evicted = 0
        for filepath, size, _ in files_with_info:
            if total_size <= self._max_cache_bytes:
                break
            self._remove_file(filepath)
            total_size -= size
            evicted += 1

        if evicted:
            logger.info(
                "Evicted %d cache entries to stay under %d bytes",
                evicted,
                self._max_cache_bytes,
            )

    def _publish_fallback_activated(self, strategy: str, reason: str) -> None:
        """Publish a FALLBACK_ACTIVATED event."""
        self._event_bus.publish(Event(
            type=EventType.FALLBACK_ACTIVATED,
            source="resilience.fallback",
            data={
                "strategy": strategy,
                "reason": reason,
                "timestamp": time.time(),
            },
        ))
