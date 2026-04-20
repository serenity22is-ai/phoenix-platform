"""
Booking Engine Neuron — Queue-based booking with Scraping Browser orchestration.

Manages the complete booking lifecycle:
1. Customer clicks "Book" → job enters priority queue
2. Queue assigns job to Scraping Browser session
3. Session connects to airline checkout via Bright Data CDP
4. Passenger info + card details filled programmatically
5. Booking confirmed → Stripe service fee captured
6. Card data wiped from memory immediately

Security architecture:
- User NEVER sees the browser session (fully backend)
- Card data is transient — enters memory, fills form, gets wiped
- No card data stored to disk/DB at any point
- Proxy session is NOT accessible to end users
- All booking UI rendered by MYSTES template (not airline page relay)

MYSTES KYRIOS LLC — Confidential.
"""

import logging
from typing import Any, Dict, List, Optional

from ..core.events import Event, EventBus, EventType
from ..core.registry import NeuronModule
from .queue import BookingJob, BookingPriority, BookingQueue, JobStatus
from .session_manager import BookingSession, SessionManager, SessionState

logger = logging.getLogger(__name__)

__all__ = [
    "BookingEngineModule",
    "BookingQueue",
    "BookingJob",
    "BookingPriority",
    "JobStatus",
    "SessionManager",
    "BookingSession",
    "SessionState",
]


class BookingEngineModule(NeuronModule):
    """
    ANASTASiA Booking Engine Neuron — queue + session orchestration.

    Provides:
    - Priority booking queue (Travel+ > Free > Guest)
    - Scraping Browser session management
    - Retry logic with different proxy IPs
    - Real-time status for frontend polling
    - Automatic card data wipe after booking
    """

    def __init__(self):
        self._event_bus: Optional[EventBus] = None
        self._queue: Optional[BookingQueue] = None
        self._session_mgr: Optional[SessionManager] = None
        self._initialized: bool = False

    @property
    def name(self) -> str:
        return "booking_engine"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def dependencies(self) -> List[str]:
        return ["proxy"]  # Needs proxy for Scraping Browser URLs

    def initialize(self, event_bus: EventBus, config: Dict[str, Any]) -> None:
        self._event_bus = event_bus

        self._queue = BookingQueue(
            max_queue_size=config.get("booking_max_queue_size", 100),
        )

        self._session_mgr = SessionManager(
            max_concurrent_sessions=config.get(
                "booking_max_concurrent_sessions", 10
            ),
            session_timeout_seconds=config.get(
                "booking_session_timeout", 300
            ),
        )

        # Subscribe to booking lifecycle events
        event_bus.subscribe(EventType.BOOKING_CONFIRMED, self._on_booking_confirmed)
        event_bus.subscribe(EventType.BOOKING_FAILED, self._on_booking_failed)

        self._initialized = True
        logger.info(
            "Booking engine initialized: "
            "max_queue=%d, max_concurrent=%d, timeout=%ds",
            self._queue._max_size,
            self._session_mgr._max_concurrent,
            self._session_mgr._session_timeout,
        )

    def health_check(self) -> Dict[str, Any]:
        if not self._initialized:
            return {"healthy": False, "details": "Not initialized"}

        return {
            "healthy": True,
            "details": (
                f"Queue: {self._queue.stats['pending']} pending, "
                f"Sessions: {self._session_mgr.stats['active_sessions']} active"
            ),
            "queue": self._queue.stats if self._queue else {},
            "sessions": self._session_mgr.stats if self._session_mgr else {},
        }

    def shutdown(self) -> None:
        self._initialized = False
        logger.info("Booking engine shut down")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def queue(self) -> BookingQueue:
        if self._queue is None:
            raise RuntimeError("BookingEngineModule not initialized")
        return self._queue

    @property
    def session_manager(self) -> SessionManager:
        if self._session_mgr is None:
            raise RuntimeError("BookingEngineModule not initialized")
        return self._session_mgr

    def enqueue_booking(
        self,
        deal_id: str,
        user_id: Optional[int],
        market: str,
        fee_tier: str = "guest",
        passenger_data: Optional[Dict] = None,
        payment_info: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """Submit a booking request to the queue.

        This is the primary entry point for the MYSTES template layer.
        Returns immediately with a job_id for status polling.

        Args:
            deal_id: Deal to book
            user_id: User ID (None for guest)
            market: POS market code (from arbitrage result)
            fee_tier: User's fee tier name for priority
            passenger_data: Passenger details dict
            payment_info: Card details dict

        Returns:
            {
                "job_id": "abc123",
                "status": "queued",
                "queue_position": 0,
                "estimated_wait": 180.0,
            }
        """
        # Map fee tier to queue priority
        priority_map = {
            "travel_plus": BookingPriority.TRAVEL_PLUS,
            "b2b_starter": BookingPriority.B2B,
            "b2b_growth": BookingPriority.B2B,
            "b2b_volume": BookingPriority.B2B,
            "free": BookingPriority.FREE,
            "guest": BookingPriority.GUEST,
        }
        priority = priority_map.get(fee_tier, BookingPriority.GUEST)

        job = self._queue.enqueue(
            deal_id=deal_id,
            user_id=user_id,
            market=market,
            priority=priority,
            passenger_data=passenger_data,
            payment_info=payment_info,
        )

        if self._event_bus:
            self._event_bus.publish(Event(
                type=EventType.BOOKING_QUEUED,
                source="booking_engine",
                data={
                    "job_id": job.job_id,
                    "deal_id": deal_id,
                    "priority": priority.name,
                    "market": market,
                },
            ))

        return {
            "job_id": job.job_id,
            "status": "queued",
            "queue_position": self._queue.get_queue_position(job.job_id),
            "estimated_wait": self._queue.get_estimated_wait(job.job_id),
        }

    def get_booking_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get current status of a booking job (for frontend polling).

        Returns:
            Job status dict, or None if job not found.
        """
        job = self._queue.get_job(job_id)
        if not job:
            return None

        status = job.to_status()

        # Add queue position if still waiting
        if job.status == JobStatus.QUEUED:
            status["queue_position"] = self._queue.get_queue_position(job_id)
            status["estimated_wait"] = self._queue.get_estimated_wait(job_id)

        # Add session status if in progress
        if job.session_id:
            session = self._session_mgr.get_session(job.session_id)
            if session:
                status["session"] = session.to_status()

        return status

    def process_next(self) -> Optional[str]:
        """Process the next job in the queue.

        Called by the background worker loop. Returns the job_id
        that was dequeued, or None if queue is empty or sessions full.

        The actual booking execution (Playwright + Scraping Browser)
        is handled by the MYSTES template layer's airline_booker.py,
        which calls back into session_manager to update state.
        """
        if not self._session_mgr.can_accept_session():
            return None

        job = self._queue.dequeue()
        if not job:
            return None

        # Create a Scraping Browser session for this job
        session = self._session_mgr.create_session(
            deal_id=job.deal_id,
            user_id=job.user_id,
            market=job.market,
        )
        job.session_id = session.session_id
        job.status = JobStatus.IN_PROGRESS

        if self._event_bus:
            self._event_bus.publish(Event(
                type=EventType.BOOKING_PROCESSING,
                source="booking_engine",
                data={
                    "job_id": job.job_id,
                    "session_id": session.session_id,
                    "market": job.market,
                },
            ))

        return job.job_id

    def complete_booking(
        self,
        job_id: str,
        confirmation_code: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        """Mark a booking as completed or failed.

        Called by airline_booker.py after checkout attempt.
        ALWAYS wipes card/passenger data from memory.
        """
        job = self._queue.get_job(job_id)
        if not job:
            return

        # Update session state
        if job.session_id:
            self._session_mgr.update_state(
                job.session_id,
                SessionState.COMPLETED if not error else SessionState.FAILED,
                error=error,
                confirmation_code=confirmation_code,
            )

        if error and job.status != JobStatus.CANCELLED:
            # Check if we can retry
            can_retry = (
                job.session_id
                and self._session_mgr.mark_retry(job.session_id)
            )
            if can_retry:
                # Re-queue with retry state
                job.status = JobStatus.QUEUED
                job.session_id = None

                if self._event_bus:
                    self._event_bus.publish(Event(
                        type=EventType.BOOKING_RETRY,
                        source="booking_engine",
                        data={
                            "job_id": job_id,
                            "retry_count": self._session_mgr.get_session(
                                job.session_id
                            ).retries if job.session_id else 0,
                            "error": error,
                        },
                    ))
                return

        # Final completion (success or exhausted retries)
        self._queue.complete_job(
            job_id,
            confirmation_code=confirmation_code,
            error=error,
        )

    def check_timeouts(self) -> List[str]:
        """Check for timed-out sessions and handle them.

        Called periodically by background worker.
        Returns list of job_ids that timed out.
        """
        timed_out_sessions = self._session_mgr.cleanup_expired()
        timed_out_jobs = []

        for session_id in timed_out_sessions:
            # Find the job for this session
            for job in self._queue._jobs.values():
                if job.session_id == session_id:
                    self.complete_booking(
                        job.job_id,
                        error="Booking session timed out",
                    )
                    timed_out_jobs.append(job.job_id)

                    if self._event_bus:
                        self._event_bus.publish(Event(
                            type=EventType.BOOKING_TIMEOUT,
                            source="booking_engine",
                            data={
                                "job_id": job.job_id,
                                "session_id": session_id,
                            },
                        ))
                    break

        return timed_out_jobs

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_booking_confirmed(self, event: Event) -> None:
        """Handle booking confirmation from airline_booker."""
        job_id = event.data.get("job_id")
        confirmation = event.data.get("confirmation_code")
        if job_id:
            self.complete_booking(job_id, confirmation_code=confirmation)

    def _on_booking_failed(self, event: Event) -> None:
        """Handle booking failure from airline_booker."""
        job_id = event.data.get("job_id")
        error = event.data.get("error", "Unknown booking error")
        if job_id:
            self.complete_booking(job_id, error=error)
