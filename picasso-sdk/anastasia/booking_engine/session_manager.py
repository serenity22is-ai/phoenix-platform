"""
Scraping Browser Session Manager — CDP session lifecycle for airline checkout.

Manages Bright Data Scraping Browser sessions for booking execution:
- Connect Playwright to Scraping Browser via CDP
- Sticky session = same IP for entire checkout flow
- Country-targeted (same POS market used in search)
- Auto CAPTCHA solving, fingerprint randomization
- Session timeout and cleanup

CRITICAL SECURITY:
- User NEVER sees the browser session — fully backend
- Card data transits in memory only, wiped after booking
- No direct proxy access exposed to end users

MYSTES KYRIOS LLC — Confidential.
"""

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class SessionState(Enum):
    """Scraping Browser session states."""
    PENDING = "pending"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    FILLING_PASSENGER = "filling_passenger"
    FILLING_PAYMENT = "filling_payment"
    SUBMITTING = "submitting"
    CONFIRMING = "confirming"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"


@dataclass
class BookingSession:
    """Tracks a single Scraping Browser booking session."""

    session_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    deal_id: Optional[str] = None
    user_id: Optional[int] = None
    market: str = ""
    state: SessionState = SessionState.PENDING
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    error: Optional[str] = None
    confirmation_code: Optional[str] = None
    retries: int = 0
    max_retries: int = 2
    timeout_seconds: int = 300  # 5 min per attempt

    @property
    def elapsed_seconds(self) -> float:
        if self.started_at:
            end = self.completed_at or time.time()
            return end - self.started_at
        return 0.0

    @property
    def is_active(self) -> bool:
        return self.state in (
            SessionState.CONNECTING,
            SessionState.CONNECTED,
            SessionState.FILLING_PASSENGER,
            SessionState.FILLING_PAYMENT,
            SessionState.SUBMITTING,
            SessionState.CONFIRMING,
        )

    @property
    def is_timed_out(self) -> bool:
        if not self.started_at:
            return False
        return time.time() - self.started_at > self.timeout_seconds

    @property
    def can_retry(self) -> bool:
        return self.retries < self.max_retries

    def to_status(self) -> Dict[str, Any]:
        """Return status dict for frontend polling."""
        state_messages = {
            SessionState.PENDING: "Waiting in queue...",
            SessionState.CONNECTING: "Connecting to booking system...",
            SessionState.CONNECTED: "Connected, starting booking...",
            SessionState.FILLING_PASSENGER: "Entering passenger information...",
            SessionState.FILLING_PAYMENT: "Processing payment details...",
            SessionState.SUBMITTING: "Submitting booking...",
            SessionState.CONFIRMING: "Confirming reservation...",
            SessionState.COMPLETED: "Booking confirmed!",
            SessionState.FAILED: f"Booking failed: {self.error or 'Unknown error'}",
            SessionState.TIMEOUT: "Booking timed out. Retrying...",
        }

        return {
            "session_id": self.session_id,
            "state": self.state.value,
            "message": state_messages.get(self.state, "Processing..."),
            "elapsed_seconds": round(self.elapsed_seconds, 1),
            "retries": self.retries,
            "confirmation_code": self.confirmation_code,
        }


class SessionManager:
    """
    Manages Scraping Browser sessions for booking execution.

    Tracks active sessions, enforces concurrency limits, handles
    timeouts, and provides session state for frontend polling.
    """

    def __init__(
        self,
        max_concurrent_sessions: int = 10,
        session_timeout_seconds: int = 300,
    ):
        self._max_concurrent = max_concurrent_sessions
        self._session_timeout = session_timeout_seconds
        self._sessions: Dict[str, BookingSession] = {}
        self._total_completed: int = 0
        self._total_failed: int = 0

    def create_session(
        self,
        deal_id: str,
        user_id: Optional[int],
        market: str,
    ) -> BookingSession:
        """Create a new booking session.

        Returns:
            BookingSession in PENDING state
        """
        session = BookingSession(
            deal_id=deal_id,
            user_id=user_id,
            market=market,
            timeout_seconds=self._session_timeout,
        )
        self._sessions[session.session_id] = session
        logger.info(
            "Booking session created: %s (deal=%s, market=%s)",
            session.session_id, deal_id, market,
        )
        return session

    def get_session(self, session_id: str) -> Optional[BookingSession]:
        """Get a session by ID."""
        return self._sessions.get(session_id)

    def update_state(
        self,
        session_id: str,
        state: SessionState,
        error: Optional[str] = None,
        confirmation_code: Optional[str] = None,
    ) -> None:
        """Update session state."""
        session = self._sessions.get(session_id)
        if not session:
            logger.warning("Session not found: %s", session_id)
            return

        old_state = session.state
        session.state = state

        if state == SessionState.CONNECTING and not session.started_at:
            session.started_at = time.time()
        elif state in (SessionState.COMPLETED, SessionState.FAILED):
            session.completed_at = time.time()
        if error:
            session.error = error
        if confirmation_code:
            session.confirmation_code = confirmation_code

        if state == SessionState.COMPLETED:
            self._total_completed += 1
        elif state == SessionState.FAILED:
            self._total_failed += 1

        logger.info(
            "Session %s: %s → %s%s",
            session_id,
            old_state.value,
            state.value,
            f" (error: {error})" if error else "",
        )

    def mark_retry(self, session_id: str) -> bool:
        """Mark session for retry. Returns True if retry is allowed."""
        session = self._sessions.get(session_id)
        if not session:
            return False

        if not session.can_retry:
            return False

        session.retries += 1
        session.state = SessionState.PENDING
        session.started_at = None
        session.error = None
        logger.info(
            "Session %s: retry %d/%d",
            session_id, session.retries, session.max_retries,
        )
        return True

    def get_active_count(self) -> int:
        """Return number of currently active sessions."""
        return sum(1 for s in self._sessions.values() if s.is_active)

    def can_accept_session(self) -> bool:
        """Check if we can accept a new booking session."""
        return self.get_active_count() < self._max_concurrent

    def get_queue_position(self, session_id: str) -> int:
        """Get queue position for a pending session (0 = next up)."""
        pending = [
            s for s in self._sessions.values()
            if s.state == SessionState.PENDING
        ]
        pending.sort(key=lambda s: s.created_at)
        for i, s in enumerate(pending):
            if s.session_id == session_id:
                return i
        return -1

    def cleanup_expired(self) -> List[str]:
        """Check for timed-out sessions and mark them.

        Returns list of session IDs that timed out.
        """
        timed_out = []
        for session_id, session in self._sessions.items():
            if session.is_active and session.is_timed_out:
                session.state = SessionState.TIMEOUT
                session.completed_at = time.time()
                timed_out.append(session_id)
                logger.warning(
                    "Session %s timed out after %.0fs",
                    session_id, session.elapsed_seconds,
                )
        return timed_out

    def cleanup_old_sessions(self, max_age_hours: int = 24) -> int:
        """Remove completed/failed sessions older than max_age_hours."""
        cutoff = time.time() - (max_age_hours * 3600)
        to_remove = [
            sid for sid, s in self._sessions.items()
            if not s.is_active
            and s.created_at < cutoff
        ]
        for sid in to_remove:
            del self._sessions[sid]
        return len(to_remove)

    @property
    def stats(self) -> Dict[str, Any]:
        return {
            "active_sessions": self.get_active_count(),
            "pending_sessions": sum(
                1 for s in self._sessions.values()
                if s.state == SessionState.PENDING
            ),
            "max_concurrent": self._max_concurrent,
            "total_completed": self._total_completed,
            "total_failed": self._total_failed,
            "total_tracked": len(self._sessions),
        }


__all__ = ["SessionManager", "BookingSession", "SessionState"]
