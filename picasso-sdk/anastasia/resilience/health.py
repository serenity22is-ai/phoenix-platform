"""
Health Monitor — Continuous dependency health surveillance.

Runs a background daemon thread that periodically probes every registered
dependency (APIs, databases, caches, etc.) and maintains a rolling health
history. Aggregates individual results into an overall platform status:

  - **healthy** — all dependencies are up.
  - **degraded** — at least one non-critical dependency is down.
  - **critical** — at least one critical dependency is down.

Publishes ``INTEGRATION_HEALTH_CHANGED`` whenever a dependency flips between
healthy and unhealthy, so other neurons (circuit breakers, fallback manager,
alerting) can react immediately.

Built-in probe factories are provided for common dependency types:
HTTP endpoints, database connections, and Redis connections.

MYSTES KYRIOS LLC — Confidential.
"""

import logging
import threading
import time
from collections import deque
from typing import Any, Callable, Dict, List, Optional

from ..core.events import Event, EventBus, EventType

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Overall status constants
# ---------------------------------------------------------------------------

STATUS_HEALTHY = "healthy"
STATUS_DEGRADED = "degraded"
STATUS_CRITICAL = "critical"


# ---------------------------------------------------------------------------
# Built-in health check factories
# ---------------------------------------------------------------------------

def http_health_check(url: str, timeout: float = 5.0) -> Callable[[], bool]:
    """
    Return a health-check function that GETs *url* and expects a 2xx status.

    Uses ``urllib.request`` to avoid adding ``requests`` as a hard dependency
    of the resilience layer.
    """
    import urllib.request
    import urllib.error

    def _check() -> bool:
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return 200 <= resp.status < 300
        except (urllib.error.URLError, OSError):
            return False

    _check.__name__ = f"http_check_{url}"
    return _check


def database_health_check(get_connection: Callable) -> Callable[[], bool]:
    """
    Return a health-check function that executes ``SELECT 1`` on the
    connection returned by *get_connection*.

    Works with any DB-API 2.0 connection (psycopg2, sqlite3, etc.).
    """
    def _check() -> bool:
        try:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchone()
            cursor.close()
            return True
        except Exception:
            return False

    _check.__name__ = "database_check"
    return _check


def redis_health_check(get_redis: Callable) -> Callable[[], bool]:
    """
    Return a health-check function that PINGs the Redis client returned
    by *get_redis*.
    """
    def _check() -> bool:
        try:
            client = get_redis()
            return client.ping()
        except Exception:
            return False

    _check.__name__ = "redis_check"
    return _check


# ---------------------------------------------------------------------------
# Dependency record
# ---------------------------------------------------------------------------

class _Dependency:
    """Internal record for a monitored dependency."""

    __slots__ = (
        "name",
        "health_func",
        "critical",
        "healthy",
        "consecutive_failures",
        "last_check",
        "last_response_ms",
        "history",
    )

    def __init__(
        self,
        name: str,
        health_func: Callable[[], bool],
        critical: bool,
        history_limit: int = 100,
    ):
        self.name = name
        self.health_func = health_func
        self.critical = critical
        self.healthy: bool = True  # assume healthy until first check
        self.consecutive_failures: int = 0
        self.last_check: float = 0.0
        self.last_response_ms: float = 0.0
        self.history: deque = deque(maxlen=history_limit)


# ---------------------------------------------------------------------------
# HealthMonitor
# ---------------------------------------------------------------------------

class HealthMonitor:
    """
    Monitors the health of external dependencies.

    Parameters
    ----------
    event_bus : EventBus
        For publishing ``INTEGRATION_HEALTH_CHANGED`` events.
    check_interval : float
        Seconds between automatic health-check sweeps (default 30).
    history_limit : int
        Number of historical check results to keep per dependency.
    """

    def __init__(
        self,
        event_bus: EventBus,
        check_interval: float = 30.0,
        history_limit: int = 100,
    ):
        self._event_bus = event_bus
        self._check_interval = check_interval
        self._history_limit = history_limit

        self._dependencies: Dict[str, _Dependency] = {}
        self._lock = threading.Lock()

        # Background monitoring thread
        self._monitor_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # Status-change callbacks
        self._status_callbacks: List[Callable[[str, dict], None]] = []

        # Track overall status for change detection
        self._last_overall: str = STATUS_HEALTHY

    # -----------------------------------------------------------------
    # Dependency registration
    # -----------------------------------------------------------------

    def register_dependency(
        self,
        name: str,
        health_func: Callable[[], bool],
        critical: bool = False,
    ) -> None:
        """
        Register a dependency for monitoring.

        Parameters
        ----------
        name : str
            Human-readable identifier (e.g. ``"picasso_api"``).
        health_func : callable
            Zero-argument function returning ``True`` (healthy) or
            ``False`` (unhealthy). Should be fast (< 5s).
        critical : bool
            If ``True``, failure of this dependency puts the overall
            system in ``critical`` status.
        """
        with self._lock:
            self._dependencies[name] = _Dependency(
                name=name,
                health_func=health_func,
                critical=critical,
                history_limit=self._history_limit,
            )
        logger.info(
            "Registered dependency '%s' (critical=%s)", name, critical
        )

    def unregister_dependency(self, name: str) -> None:
        """Remove a dependency from monitoring."""
        with self._lock:
            self._dependencies.pop(name, None)
        logger.info("Unregistered dependency '%s'", name)

    # -----------------------------------------------------------------
    # Health checks
    # -----------------------------------------------------------------

    def check_dependency(self, name: str) -> Optional[dict]:
        """
        Check a single dependency immediately.

        Returns
        -------
        dict or None
            Health result dict, or ``None`` if the dependency is not
            registered.
        """
        with self._lock:
            dep = self._dependencies.get(name)
            if dep is None:
                return None

        return self._probe(dep)

    def check_all(self) -> dict:
        """
        Check all registered dependencies.

        Returns
        -------
        dict
            ``{"overall": str, "dependencies": {name: result_dict, ...}}``
        """
        with self._lock:
            deps = list(self._dependencies.values())

        results = {}
        for dep in deps:
            results[dep.name] = self._probe(dep)

        overall = self._compute_overall(results)

        # Detect overall status change
        if overall != self._last_overall:
            self._last_overall = overall
            for cb in self._status_callbacks:
                try:
                    cb(overall, results)
                except Exception as exc:
                    logger.error("Status change callback failed: %s", exc)

        return {
            "overall": overall,
            "dependencies": results,
            "checked_at": time.time(),
        }

    def get_overall_status(self) -> str:
        """
        Return the current overall status without running new checks.

        Uses the most recent check results for each dependency.

        Returns ``"healthy"``, ``"degraded"``, or ``"critical"``.
        """
        with self._lock:
            deps = list(self._dependencies.values())

        has_critical_failure = False
        has_non_critical_failure = False

        for dep in deps:
            if not dep.healthy:
                if dep.critical:
                    has_critical_failure = True
                else:
                    has_non_critical_failure = True

        if has_critical_failure:
            return STATUS_CRITICAL
        if has_non_critical_failure:
            return STATUS_DEGRADED
        return STATUS_HEALTHY

    # -----------------------------------------------------------------
    # Health history
    # -----------------------------------------------------------------

    def get_health_history(
        self, name: str, limit: int = 100
    ) -> List[dict]:
        """
        Return recent health check results for a dependency.

        Parameters
        ----------
        name : str
            Dependency name.
        limit : int
            Maximum number of results to return (most recent first).
        """
        with self._lock:
            dep = self._dependencies.get(name)
            if dep is None:
                return []
            # deque is ordered oldest-first; return newest-first
            history = list(dep.history)

        history.reverse()
        return history[:limit]

    # -----------------------------------------------------------------
    # Status-change callbacks
    # -----------------------------------------------------------------

    def on_status_change(self, callback: Callable[[str, dict], None]) -> None:
        """
        Register a callback for overall status changes.

        The callback receives ``(new_status: str, results: dict)``.
        """
        self._status_callbacks.append(callback)

    # -----------------------------------------------------------------
    # Background monitoring
    # -----------------------------------------------------------------

    def start_monitoring(self) -> None:
        """Start the background health-check thread."""
        if self._monitor_thread is not None and self._monitor_thread.is_alive():
            logger.warning("Health monitor already running")
            return

        self._stop_event.clear()
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            name="anastasia-health-monitor",
            daemon=True,
        )
        self._monitor_thread.start()
        logger.info(
            "Health monitor started (interval=%.1fs, deps=%d)",
            self._check_interval,
            len(self._dependencies),
        )

    def stop_monitoring(self) -> None:
        """Stop the background health-check thread."""
        self._stop_event.set()
        if self._monitor_thread is not None:
            self._monitor_thread.join(timeout=self._check_interval + 5)
            self._monitor_thread = None
        logger.info("Health monitor stopped")

    @property
    def is_monitoring(self) -> bool:
        """Whether the background thread is running."""
        return (
            self._monitor_thread is not None
            and self._monitor_thread.is_alive()
        )

    # -----------------------------------------------------------------
    # Private helpers
    # -----------------------------------------------------------------

    def _probe(self, dep: _Dependency) -> dict:
        """
        Execute a single health check and record the result.

        Also publishes ``INTEGRATION_HEALTH_CHANGED`` if the dependency's
        healthy status flips.
        """
        start = time.time()
        try:
            healthy = bool(dep.health_func())
        except Exception as exc:
            logger.debug("Health check for '%s' raised: %s", dep.name, exc)
            healthy = False

        elapsed_ms = (time.time() - start) * 1000
        prev_healthy = dep.healthy

        # Update dependency state
        dep.last_check = time.time()
        dep.last_response_ms = elapsed_ms
        dep.healthy = healthy

        if healthy:
            dep.consecutive_failures = 0
        else:
            dep.consecutive_failures += 1

        # Record to history
        record = {
            "healthy": healthy,
            "response_time_ms": round(elapsed_ms, 2),
            "checked_at": dep.last_check,
            "consecutive_failures": dep.consecutive_failures,
        }
        dep.history.append(record)

        # Publish event on status change
        if healthy != prev_healthy:
            logger.info(
                "Dependency '%s' status changed: %s -> %s",
                dep.name,
                "healthy" if prev_healthy else "unhealthy",
                "healthy" if healthy else "unhealthy",
            )
            self._event_bus.publish(Event(
                type=EventType.INTEGRATION_HEALTH_CHANGED,
                source="resilience.health",
                data={
                    "dependency": dep.name,
                    "healthy": healthy,
                    "critical": dep.critical,
                    "response_time_ms": round(elapsed_ms, 2),
                    "consecutive_failures": dep.consecutive_failures,
                },
            ))

        return {
            "name": dep.name,
            "healthy": healthy,
            "critical": dep.critical,
            "response_time_ms": round(elapsed_ms, 2),
            "last_check": dep.last_check,
            "consecutive_failures": dep.consecutive_failures,
        }

    @staticmethod
    def _compute_overall(results: Dict[str, dict]) -> str:
        """Compute overall status from individual dependency results."""
        has_critical = False
        has_non_critical = False

        for result in results.values():
            if not result.get("healthy", True):
                if result.get("critical", False):
                    has_critical = True
                else:
                    has_non_critical = True

        if has_critical:
            return STATUS_CRITICAL
        if has_non_critical:
            return STATUS_DEGRADED
        return STATUS_HEALTHY

    def _monitor_loop(self) -> None:
        """Background loop that runs check_all periodically."""
        logger.debug("Health monitor loop started")
        while not self._stop_event.is_set():
            try:
                self.check_all()
            except Exception as exc:
                logger.error("Health monitor sweep failed: %s", exc)

            # Sleep in small increments so stop_event is responsive
            self._stop_event.wait(timeout=self._check_interval)

        logger.debug("Health monitor loop exiting")
