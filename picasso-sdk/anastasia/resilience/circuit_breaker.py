"""
Circuit Breaker — Prevents cascading failures by short-circuiting calls to failing services.

Implements the classic circuit breaker pattern with three states:
  CLOSED  — Normal operation. Calls pass through. Failures are counted.
  OPEN    — Service is down. Calls are immediately rejected without being made.
  HALF_OPEN — Recovery testing. A limited number of calls are allowed through.

When a service behind a circuit breaker starts failing, the breaker trips OPEN
to protect the rest of the system. After a recovery timeout it transitions to
HALF_OPEN and lets a few probe calls through. If those succeed, it closes again.
If they fail, it reopens.

MYSTES KYRIOS LLC — Confidential.
"""

import logging
import threading
import time
from typing import Any, Callable, Dict, Optional

from ..core.events import Event, EventBus, EventType

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# States
# ---------------------------------------------------------------------------

CLOSED = "CLOSED"
OPEN = "OPEN"
HALF_OPEN = "HALF_OPEN"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class CircuitOpenError(Exception):
    """Raised when a call is attempted on an open circuit breaker."""

    def __init__(self, name: str, retry_after: float = 0.0):
        self.name = name
        self.retry_after = retry_after
        super().__init__(
            f"Circuit breaker '{name}' is OPEN. "
            f"Retry after {retry_after:.1f}s."
        )


# ---------------------------------------------------------------------------
# CircuitBreaker
# ---------------------------------------------------------------------------

class CircuitBreaker:
    """
    Circuit breaker for a single dependency / service.

    Parameters
    ----------
    name : str
        Human-readable identifier (e.g. ``"picasso_api"``).
    failure_threshold : int
        Number of consecutive failures before the circuit opens.
    recovery_timeout : float
        Seconds to wait in OPEN state before transitioning to HALF_OPEN.
    half_open_max : int
        Maximum number of probe calls allowed in HALF_OPEN state.
    event_bus : EventBus, optional
        If provided, publishes ``CIRCUIT_OPENED`` / ``CIRCUIT_CLOSED`` events.
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        half_open_max: int = 3,
        event_bus: Optional[EventBus] = None,
    ):
        self._name = name
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._half_open_max = half_open_max
        self._event_bus = event_bus

        # Internal state — guarded by _lock
        self._lock = threading.Lock()
        self._state: str = CLOSED
        self._failure_count: int = 0
        self._success_count: int = 0
        self._half_open_calls: int = 0
        self._last_failure_time: float = 0.0
        self._last_success_time: float = 0.0
        self._opened_at: float = 0.0  # timestamp when circuit last opened
        self._total_calls: int = 0
        self._total_failures: int = 0
        self._total_successes: int = 0
        self._total_rejected: int = 0

    # ----- public interface ------------------------------------------------

    @property
    def name(self) -> str:
        return self._name

    def call(self, func: Callable, *args: Any, **kwargs: Any) -> Any:
        """
        Execute *func* through the circuit breaker.

        Raises
        ------
        CircuitOpenError
            If the circuit is OPEN and the recovery timeout has not elapsed.
        """
        with self._lock:
            self._total_calls += 1
            state = self._evaluate_state()

            if state == OPEN:
                self._total_rejected += 1
                retry_after = max(
                    0.0,
                    self._recovery_timeout - (time.time() - self._opened_at),
                )
                raise CircuitOpenError(self._name, retry_after)

            if state == HALF_OPEN:
                if self._half_open_calls >= self._half_open_max:
                    # Already exhausted probe budget — stay open
                    self._total_rejected += 1
                    raise CircuitOpenError(self._name, self._recovery_timeout)
                self._half_open_calls += 1

        # Execute outside the lock so we don't hold it during I/O
        try:
            result = func(*args, **kwargs)
        except Exception as exc:
            self._record_failure(exc)
            raise
        else:
            self._record_success()
            return result

    def get_state(self) -> str:
        """Return the current circuit breaker state."""
        with self._lock:
            return self._evaluate_state()

    def get_stats(self) -> dict:
        """Return a snapshot of circuit breaker statistics."""
        with self._lock:
            return {
                "name": self._name,
                "state": self._evaluate_state(),
                "failures": self._failure_count,
                "successes": self._success_count,
                "last_failure": self._last_failure_time,
                "last_success": self._last_success_time,
                "total_calls": self._total_calls,
                "total_failures": self._total_failures,
                "total_successes": self._total_successes,
                "total_rejected": self._total_rejected,
                "failure_threshold": self._failure_threshold,
                "recovery_timeout": self._recovery_timeout,
            }

    def reset(self) -> None:
        """Force-reset the circuit breaker to CLOSED."""
        with self._lock:
            prev = self._state
            self._state = CLOSED
            self._failure_count = 0
            self._half_open_calls = 0
            logger.info("Circuit breaker '%s' force-reset to CLOSED", self._name)
            if prev == OPEN:
                self._publish_closed()

    # ----- internal helpers ------------------------------------------------

    def _evaluate_state(self) -> str:
        """
        Determine the effective state, possibly transitioning OPEN -> HALF_OPEN
        if the recovery timeout has elapsed.  Must be called under ``_lock``.
        """
        if self._state == OPEN:
            elapsed = time.time() - self._opened_at
            if elapsed >= self._recovery_timeout:
                self._state = HALF_OPEN
                self._half_open_calls = 0
                logger.info(
                    "Circuit breaker '%s' transitioning OPEN -> HALF_OPEN "
                    "(recovery timeout %.1fs elapsed)",
                    self._name,
                    elapsed,
                )
        return self._state

    def _record_failure(self, exc: Exception) -> None:
        """Record a call failure.  Opens the circuit if threshold is reached."""
        with self._lock:
            self._failure_count += 1
            self._total_failures += 1
            self._last_failure_time = time.time()
            self._success_count = 0  # reset consecutive successes

            logger.debug(
                "Circuit '%s' failure #%d/%d: %s",
                self._name,
                self._failure_count,
                self._failure_threshold,
                exc,
            )

            if self._state == HALF_OPEN:
                # Any failure in HALF_OPEN reopens the circuit
                self._open_circuit()
            elif self._state == CLOSED:
                if self._failure_count >= self._failure_threshold:
                    self._open_circuit()

    def _record_success(self) -> None:
        """Record a call success.  Closes the circuit if in HALF_OPEN."""
        with self._lock:
            self._success_count += 1
            self._total_successes += 1
            self._last_success_time = time.time()

            if self._state == HALF_OPEN:
                # Success in HALF_OPEN -> close the circuit
                self._state = CLOSED
                self._failure_count = 0
                self._half_open_calls = 0
                logger.info(
                    "Circuit breaker '%s' recovered — HALF_OPEN -> CLOSED",
                    self._name,
                )
                self._publish_closed()
            elif self._state == CLOSED:
                # Successful call resets consecutive failure counter
                self._failure_count = 0

    def _open_circuit(self) -> None:
        """Transition to OPEN state.  Must be called under ``_lock``."""
        self._state = OPEN
        self._opened_at = time.time()
        self._half_open_calls = 0
        logger.warning(
            "Circuit breaker '%s' OPENED after %d failures",
            self._name,
            self._failure_count,
        )
        self._publish_opened()

    # ----- event publishing ------------------------------------------------

    def _publish_opened(self) -> None:
        if self._event_bus:
            self._event_bus.publish(Event(
                type=EventType.CIRCUIT_OPENED,
                source="resilience.circuit_breaker",
                data={
                    "breaker": self._name,
                    "failures": self._failure_count,
                    "opened_at": self._opened_at,
                },
            ))

    def _publish_closed(self) -> None:
        if self._event_bus:
            self._event_bus.publish(Event(
                type=EventType.CIRCUIT_CLOSED,
                source="resilience.circuit_breaker",
                data={
                    "breaker": self._name,
                    "closed_at": time.time(),
                },
            ))


# ---------------------------------------------------------------------------
# CircuitBreakerRegistry
# ---------------------------------------------------------------------------

class CircuitBreakerRegistry:
    """
    Singleton registry for all circuit breakers in the system.

    Use ``get_or_create`` to obtain a breaker by name. If it doesn't exist
    yet it will be created with the supplied kwargs. If it already exists
    the existing instance is returned (kwargs are ignored).
    """

    def __init__(self, event_bus: Optional[EventBus] = None):
        self._breakers: Dict[str, CircuitBreaker] = {}
        self._lock = threading.Lock()
        self._event_bus = event_bus

    def get_or_create(self, name: str, **kwargs: Any) -> CircuitBreaker:
        """
        Get an existing circuit breaker or create a new one.

        Parameters
        ----------
        name : str
            Unique identifier for the breaker.
        **kwargs
            Forwarded to ``CircuitBreaker.__init__`` if a new breaker is
            created.  ``event_bus`` defaults to the registry's event bus
            if not explicitly provided.
        """
        with self._lock:
            if name not in self._breakers:
                kwargs.setdefault("event_bus", self._event_bus)
                self._breakers[name] = CircuitBreaker(name=name, **kwargs)
                logger.info("Created circuit breaker '%s'", name)
            return self._breakers[name]

    def get(self, name: str) -> Optional[CircuitBreaker]:
        """Return a breaker by name, or ``None`` if it doesn't exist."""
        with self._lock:
            return self._breakers.get(name)

    def get_all_stats(self) -> Dict[str, dict]:
        """Return stats from every registered circuit breaker."""
        with self._lock:
            return {name: cb.get_stats() for name, cb in self._breakers.items()}

    def reset_all(self) -> None:
        """Force-reset every circuit breaker to CLOSED."""
        with self._lock:
            for cb in self._breakers.values():
                cb.reset()
            logger.info("All circuit breakers reset to CLOSED")
