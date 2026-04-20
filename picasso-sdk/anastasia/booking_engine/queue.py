"""
Booking Queue — Priority queue for booking job management.

Manages the flow of booking requests from customer submission
through to airline checkout execution. Handles:
- Priority ordering (Travel+ > Free > Guest)
- Estimated wait times
- Job lifecycle tracking
- Integration with SessionManager for execution

MYSTES KYRIOS LLC — Confidential.
"""

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class BookingPriority(Enum):
    """Booking queue priority levels. Lower value = higher priority."""
    TRAVEL_PLUS = 1     # Travel+ subscribers ($9.99/mo)
    B2B = 2             # B2B operators (Starter/Growth/Volume)
    FREE = 3            # Free registered members
    GUEST = 4           # Anonymous guests


class JobStatus(Enum):
    """Booking job lifecycle states."""
    QUEUED = "queued"
    ASSIGNED = "assigned"      # Assigned to a Scraping Browser session
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class BookingJob:
    """A booking request in the queue."""

    job_id: str = field(default_factory=lambda: str(uuid.uuid4())[:16])
    deal_id: str = ""
    user_id: Optional[int] = None
    priority: BookingPriority = BookingPriority.GUEST
    status: JobStatus = JobStatus.QUEUED
    created_at: float = field(default_factory=time.time)
    assigned_at: Optional[float] = None
    completed_at: Optional[float] = None
    session_id: Optional[str] = None   # Scraping Browser session ID
    market: str = ""                    # POS market for booking
    error: Optional[str] = None
    confirmation_code: Optional[str] = None

    # Passenger and payment data — transient, wiped after completion
    passenger_data: Optional[Dict] = None
    payment_info: Optional[Dict] = None

    @property
    def wait_seconds(self) -> float:
        """Time spent waiting in queue."""
        if self.assigned_at:
            return self.assigned_at - self.created_at
        return time.time() - self.created_at

    @property
    def total_seconds(self) -> float:
        """Total time from creation to completion."""
        end = self.completed_at or time.time()
        return end - self.created_at

    def wipe_sensitive_data(self) -> None:
        """Wipe card and passenger data from memory after booking.

        CRITICAL: Called after booking completes (success or failure).
        Card data must never persist beyond the booking session.
        """
        self.payment_info = None
        self.passenger_data = None

    def to_status(self) -> Dict[str, Any]:
        """Return status for API response (no sensitive data)."""
        return {
            "job_id": self.job_id,
            "deal_id": self.deal_id,
            "status": self.status.value,
            "priority": self.priority.name.lower(),
            "wait_seconds": round(self.wait_seconds, 1),
            "total_seconds": round(self.total_seconds, 1),
            "confirmation_code": self.confirmation_code,
            "error": self.error,
        }


class BookingQueue:
    """
    Priority queue for booking jobs.

    Jobs are ordered by priority (Travel+ first) then by creation time
    (FIFO within same priority). The queue provides estimated wait times
    and integrates with the SessionManager for execution.
    """

    def __init__(self, max_queue_size: int = 100):
        self._max_size = max_queue_size
        self._jobs: Dict[str, BookingJob] = {}
        self._total_completed: int = 0
        self._total_failed: int = 0
        self._avg_booking_seconds: float = 180.0  # 3 min default estimate

    def enqueue(
        self,
        deal_id: str,
        user_id: Optional[int],
        market: str,
        priority: BookingPriority = BookingPriority.GUEST,
        passenger_data: Optional[Dict] = None,
        payment_info: Optional[Dict] = None,
    ) -> BookingJob:
        """Add a booking job to the queue.

        Args:
            deal_id: Deal to book
            user_id: User ID (or None for guest)
            market: POS market code for booking
            priority: Queue priority based on user tier
            passenger_data: Passenger info dict
            payment_info: Card details dict (encrypted)

        Returns:
            BookingJob with job_id for tracking

        Raises:
            RuntimeError: If queue is full
        """
        if len(self._pending_jobs()) >= self._max_size:
            raise RuntimeError(
                f"Booking queue is full ({self._max_size} pending jobs). "
                "Please try again in a few minutes."
            )

        job = BookingJob(
            deal_id=deal_id,
            user_id=user_id,
            market=market,
            priority=priority,
            passenger_data=passenger_data,
            payment_info=payment_info,
        )

        self._jobs[job.job_id] = job
        logger.info(
            "Booking job queued: %s (deal=%s, priority=%s, market=%s)",
            job.job_id, deal_id, priority.name, market,
        )
        return job

    def dequeue(self) -> Optional[BookingJob]:
        """Get the next job to process (highest priority, oldest first).

        Returns:
            Next BookingJob to process, or None if queue empty.
        """
        pending = self._pending_jobs()
        if not pending:
            return None

        # Sort by priority (lower = higher priority), then by creation time
        pending.sort(key=lambda j: (j.priority.value, j.created_at))
        job = pending[0]
        job.status = JobStatus.ASSIGNED
        job.assigned_at = time.time()
        return job

    def get_job(self, job_id: str) -> Optional[BookingJob]:
        """Get a job by ID."""
        return self._jobs.get(job_id)

    def complete_job(
        self,
        job_id: str,
        confirmation_code: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        """Mark a job as completed or failed.

        ALWAYS wipes sensitive data after completion.
        """
        job = self._jobs.get(job_id)
        if not job:
            return

        job.completed_at = time.time()

        if error:
            job.status = JobStatus.FAILED
            job.error = error
            self._total_failed += 1
        else:
            job.status = JobStatus.COMPLETED
            job.confirmation_code = confirmation_code
            self._total_completed += 1
            # Update average booking time
            if job.assigned_at:
                booking_time = job.completed_at - job.assigned_at
                self._avg_booking_seconds = (
                    0.2 * booking_time + 0.8 * self._avg_booking_seconds
                )

        # CRITICAL: wipe sensitive data
        job.wipe_sensitive_data()

        logger.info(
            "Booking job %s: %s%s (%.1fs)",
            job_id,
            "completed" if not error else "failed",
            f" — {confirmation_code}" if confirmation_code else "",
            job.total_seconds,
        )

    def cancel_job(self, job_id: str) -> bool:
        """Cancel a queued job. Returns True if cancelled."""
        job = self._jobs.get(job_id)
        if not job:
            return False
        if job.status not in (JobStatus.QUEUED, JobStatus.ASSIGNED):
            return False

        job.status = JobStatus.CANCELLED
        job.completed_at = time.time()
        job.wipe_sensitive_data()
        return True

    def get_queue_position(self, job_id: str) -> int:
        """Get position in queue (0 = next up, -1 = not in queue)."""
        job = self._jobs.get(job_id)
        if not job or job.status != JobStatus.QUEUED:
            return -1

        pending = self._pending_jobs()
        pending.sort(key=lambda j: (j.priority.value, j.created_at))
        for i, j in enumerate(pending):
            if j.job_id == job_id:
                return i
        return -1

    def get_estimated_wait(self, job_id: str) -> float:
        """Estimated wait time in seconds for a queued job."""
        pos = self.get_queue_position(job_id)
        if pos < 0:
            return 0.0
        return pos * self._avg_booking_seconds

    def cleanup_old_jobs(self, max_age_hours: int = 24) -> int:
        """Remove completed/failed/cancelled jobs older than max_age."""
        cutoff = time.time() - (max_age_hours * 3600)
        terminal_states = (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED)
        to_remove = [
            jid for jid, j in self._jobs.items()
            if j.status in terminal_states and j.created_at < cutoff
        ]
        for jid in to_remove:
            del self._jobs[jid]
        return len(to_remove)

    def _pending_jobs(self) -> List[BookingJob]:
        return [j for j in self._jobs.values() if j.status == JobStatus.QUEUED]

    @property
    def stats(self) -> Dict[str, Any]:
        pending = self._pending_jobs()
        in_progress = [
            j for j in self._jobs.values()
            if j.status in (JobStatus.ASSIGNED, JobStatus.IN_PROGRESS)
        ]
        return {
            "pending": len(pending),
            "in_progress": len(in_progress),
            "total_completed": self._total_completed,
            "total_failed": self._total_failed,
            "total_tracked": len(self._jobs),
            "max_queue_size": self._max_size,
            "avg_booking_seconds": round(self._avg_booking_seconds, 1),
        }


__all__ = ["BookingQueue", "BookingJob", "BookingPriority", "JobStatus"]
