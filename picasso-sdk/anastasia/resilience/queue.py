"""
Booking Queue — Persistent priority queue for degraded / offline booking.

When a booking API is unavailable (circuit breaker open, network partition,
rate limit exceeded), requests are enqueued rather than dropped. The queue:

  - Persists to disk as a JSON file so it survives process restarts.
  - Orders by priority (1 = highest, 10 = lowest), then FIFO within priority.
  - Tracks each item through ``queued -> processing -> completed | failed``.
  - Supports retry of failed items with configurable max-retries.
  - Publishes ``QUEUE_OVERFLOW`` when the queue exceeds its size limit.

MYSTES KYRIOS LLC — Confidential.
"""

import json
import logging
import os
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

from ..core.events import Event, EventBus, EventType

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Item status constants
# ---------------------------------------------------------------------------

STATUS_QUEUED = "queued"
STATUS_PROCESSING = "processing"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"


# ---------------------------------------------------------------------------
# BookingQueue
# ---------------------------------------------------------------------------

class BookingQueue:
    """
    Persistent priority queue for booking requests.

    Parameters
    ----------
    event_bus : EventBus
        For publishing ``QUEUE_OVERFLOW`` events.
    storage_dir : str
        Directory for the queue persistence file. Created if missing.
    max_size : int
        Maximum number of items in the queue. Enqueue beyond this limit
        triggers a ``QUEUE_OVERFLOW`` event (the item is still accepted
        to avoid data loss, but the event signals that the system is
        under pressure).
    """

    PERSISTENCE_FILE = "booking_queue.json"

    def __init__(
        self,
        event_bus: EventBus,
        storage_dir: str,
        max_size: int = 1000,
    ):
        self._event_bus = event_bus
        self._storage_dir = storage_dir
        self._max_size = max_size
        self._lock = threading.Lock()

        # Items keyed by queue_id for O(1) lookup
        self._items: Dict[str, dict] = {}

        os.makedirs(self._storage_dir, exist_ok=True)
        self._persistence_path = os.path.join(
            self._storage_dir, self.PERSISTENCE_FILE
        )

        # Restore from disk
        self._load()

    # -----------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------

    def enqueue(self, booking_request: dict, priority: int = 5) -> str:
        """
        Add a booking request to the queue.

        Parameters
        ----------
        booking_request : dict
            Arbitrary booking payload (must be JSON-serializable).
        priority : int
            1 (highest) to 10 (lowest). Default 5.

        Returns
        -------
        str
            Unique queue ID for tracking.
        """
        priority = max(1, min(10, priority))
        queue_id = str(uuid.uuid4())[:12]

        item = {
            "id": queue_id,
            "request": booking_request,
            "priority": priority,
            "status": STATUS_QUEUED,
            "enqueued_at": time.time(),
            "processed_at": None,
            "attempts": 0,
            "error": None,
            "result": None,
        }

        with self._lock:
            self._items[queue_id] = item
            self._persist()

            queued_count = sum(
                1 for i in self._items.values() if i["status"] == STATUS_QUEUED
            )
            if queued_count > self._max_size:
                logger.warning(
                    "Queue overflow: %d items (max %d)",
                    queued_count,
                    self._max_size,
                )
                self._event_bus.publish(Event(
                    type=EventType.QUEUE_OVERFLOW,
                    source="resilience.queue",
                    data={
                        "queued": queued_count,
                        "max_size": self._max_size,
                    },
                ))

        logger.info(
            "Enqueued booking %s (priority=%d, queued=%d)",
            queue_id,
            priority,
            queued_count,
        )
        return queue_id

    def dequeue(self) -> Optional[dict]:
        """
        Remove and return the next item (highest priority, then oldest).

        Returns ``None`` if the queue is empty.
        """
        with self._lock:
            item = self._next_queued()
            if item is None:
                return None

            item["status"] = STATUS_PROCESSING
            item["attempts"] += 1
            self._persist()

            # Return a copy so callers can't mutate internal state
            return dict(item)

    def peek(self) -> Optional[dict]:
        """
        Return the next item without removing it.

        Returns ``None`` if the queue is empty.
        """
        with self._lock:
            item = self._next_queued()
            return dict(item) if item else None

    def get_status(self, queue_id: str) -> Optional[dict]:
        """
        Get tracking information for a queued item.

        Returns
        -------
        dict or None
            Contains ``status``, ``position`` (1-based, or ``None`` if not
            queued), and full item metadata.
        """
        with self._lock:
            item = self._items.get(queue_id)
            if item is None:
                return None

            position = None
            if item["status"] == STATUS_QUEUED:
                sorted_queued = self._sorted_queued()
                for idx, qi in enumerate(sorted_queued, 1):
                    if qi["id"] == queue_id:
                        position = idx
                        break

            return {
                "id": queue_id,
                "status": item["status"],
                "position": position,
                "priority": item["priority"],
                "enqueued_at": item["enqueued_at"],
                "processed_at": item["processed_at"],
                "attempts": item["attempts"],
                "error": item["error"],
            }

    def process_queue(self, processor_func: Callable[[dict], Any]) -> dict:
        """
        Process all queued items using *processor_func*.

        The processor receives the booking request dict and should either
        return a result (success) or raise an exception (failure).

        Parameters
        ----------
        processor_func : callable
            ``processor_func(booking_request) -> result``

        Returns
        -------
        dict
            ``{"processed": int, "succeeded": int, "failed": int}``
        """
        processed = 0
        succeeded = 0
        failed = 0

        while True:
            item = self.dequeue()
            if item is None:
                break

            queue_id = item["id"]
            processed += 1

            try:
                result = processor_func(item["request"])
                self._mark_completed(queue_id, result)
                succeeded += 1
            except Exception as exc:
                self._mark_failed(queue_id, str(exc))
                failed += 1

        summary = {
            "processed": processed,
            "succeeded": succeeded,
            "failed": failed,
        }
        logger.info("Queue processing complete: %s", summary)
        return summary

    def retry_failed(self, max_retries: int = 3) -> int:
        """
        Re-enqueue failed items that haven't exceeded *max_retries*.

        Returns
        -------
        int
            Number of items re-enqueued.
        """
        retried = 0
        with self._lock:
            for item in self._items.values():
                if item["status"] == STATUS_FAILED and item["attempts"] < max_retries:
                    item["status"] = STATUS_QUEUED
                    item["error"] = None
                    retried += 1

            if retried:
                self._persist()

        logger.info("Re-enqueued %d failed items for retry", retried)
        return retried

    def get_queue_stats(self) -> dict:
        """
        Return aggregate queue statistics.

        Returns
        -------
        dict
            Counts by status plus total.
        """
        with self._lock:
            statuses = [i["status"] for i in self._items.values()]
            return {
                "total": len(statuses),
                "queued": statuses.count(STATUS_QUEUED),
                "processing": statuses.count(STATUS_PROCESSING),
                "completed": statuses.count(STATUS_COMPLETED),
                "failed": statuses.count(STATUS_FAILED),
                "max_size": self._max_size,
            }

    def clear_completed(self, older_than: float = 86400) -> int:
        """
        Remove completed items older than *older_than* seconds.

        Parameters
        ----------
        older_than : float
            Age threshold in seconds (default 24 hours).

        Returns
        -------
        int
            Number of items removed.
        """
        cutoff = time.time() - older_than
        removed = 0

        with self._lock:
            to_remove = [
                qid for qid, item in self._items.items()
                if item["status"] == STATUS_COMPLETED
                and (item.get("processed_at") or 0) < cutoff
            ]
            for qid in to_remove:
                del self._items[qid]
                removed += 1

            if removed:
                self._persist()

        logger.info("Cleared %d completed queue items", removed)
        return removed

    # -----------------------------------------------------------------
    # Internal state mutations (called outside _lock by process_queue)
    # -----------------------------------------------------------------

    def _mark_completed(self, queue_id: str, result: Any = None) -> None:
        """Mark item as completed."""
        with self._lock:
            item = self._items.get(queue_id)
            if item:
                item["status"] = STATUS_COMPLETED
                item["processed_at"] = time.time()
                item["result"] = result
                self._persist()

    def _mark_failed(self, queue_id: str, error: str) -> None:
        """Mark item as failed."""
        with self._lock:
            item = self._items.get(queue_id)
            if item:
                item["status"] = STATUS_FAILED
                item["processed_at"] = time.time()
                item["error"] = error
                self._persist()

    # -----------------------------------------------------------------
    # Private helpers
    # -----------------------------------------------------------------

    def _sorted_queued(self) -> List[dict]:
        """
        Return queued items sorted by priority (ascending) then enqueue
        time (ascending = FIFO).  Must be called under ``_lock``.
        """
        return sorted(
            (i for i in self._items.values() if i["status"] == STATUS_QUEUED),
            key=lambda i: (i["priority"], i["enqueued_at"]),
        )

    def _next_queued(self) -> Optional[dict]:
        """Return the next item to process, or ``None``.  Under ``_lock``."""
        queued = self._sorted_queued()
        return queued[0] if queued else None

    def _persist(self) -> None:
        """Write the queue to disk.  Must be called under ``_lock``."""
        try:
            data = list(self._items.values())
            with open(self._persistence_path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, default=str, indent=2)
        except OSError as exc:
            logger.error("Failed to persist queue: %s", exc)

    def _load(self) -> None:
        """Restore queue from disk on startup."""
        if not os.path.exists(self._persistence_path):
            return

        try:
            with open(self._persistence_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)

            for item in data:
                qid = item.get("id")
                if qid:
                    # Items that were "processing" when we crashed are
                    # re-queued so they get retried
                    if item.get("status") == STATUS_PROCESSING:
                        item["status"] = STATUS_QUEUED
                    self._items[qid] = item

            logger.info(
                "Restored %d queue items from disk (%d queued)",
                len(self._items),
                sum(1 for i in self._items.values() if i["status"] == STATUS_QUEUED),
            )
        except (OSError, json.JSONDecodeError) as exc:
            logger.error("Failed to load queue from disk: %s", exc)
