"""
Reconciliation Engine — Payment tracking, logging, and discrepancy detection.

Tracks every payment transaction ANASTASiA processes, stores daily logs as
JSON files, and provides reconciliation tools to compare internal records
against processor records.

Publishes PAYMENT_COMPLETED and PAYMENT_FAILED events to the event bus
so other neurons can react to payment outcomes.

MYSTES KYRIOS LLC — Confidential.
"""

import json
import logging
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ..core.events import Event, EventBus, EventType

logger = logging.getLogger(__name__)


class ReconciliationEngine:
    """
    Tracks, logs, and reconciles payment transactions.

    Every charge, refund, and payment intent that flows through ANASTASiA
    adapters is recorded here. Transaction logs are persisted as JSON files
    (one per day) for audit and reconciliation.

    Reconciliation compares our internal transaction records against what
    the payment processor reports, flagging discrepancies for human review.

    Usage:
        engine = ReconciliationEngine(
            event_bus=bus,
            log_dir="/var/data/anastasia/payments/logs",
        )
        engine.record_transaction(
            charge_id="ch_abc123",
            amount=5000,
            currency="usd",
            processor="stripe",
            agency_id="agency_42",
            booking_ref="BK-2026-0308",
        )
        summary = engine.get_revenue_summary(agency_id="agency_42")
    """

    def __init__(
        self,
        event_bus: Optional[EventBus] = None,
        log_dir: str = "data/payments/logs",
    ):
        """
        Initialize the reconciliation engine.

        Args:
            event_bus: EventBus instance for publishing payment events.
                       If None, events are not published (testing mode).
            log_dir: Directory where daily transaction JSON files are stored.
        """
        self._event_bus = event_bus
        self._log_dir = Path(log_dir)
        self._log_dir.mkdir(parents=True, exist_ok=True)

        # In-memory transaction buffer (flushed to disk periodically)
        self._buffer: List[Dict[str, Any]] = []
        self._buffer_max = 100
        self._discrepancies: List[Dict[str, Any]] = []

        logger.info(
            "ReconciliationEngine initialized, log_dir=%s", self._log_dir
        )

    def record_transaction(
        self,
        charge_id: str,
        amount: int,
        currency: str,
        processor: str,
        agency_id: str,
        booking_ref: str,
        status: str = "completed",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Record a payment transaction.

        Logs the transaction to the daily file and publishes the appropriate
        event (PAYMENT_COMPLETED or PAYMENT_FAILED) to the event bus.

        Args:
            charge_id: Payment processor's charge/payment identifier.
            amount: Amount in smallest currency unit (cents).
            currency: ISO 4217 currency code.
            processor: Name of the payment processor (e.g., 'stripe').
            agency_id: Agency that initiated this transaction.
            booking_ref: Internal booking reference.
            status: Transaction status — 'completed', 'failed', 'pending', 'refunded'.
            metadata: Optional additional data to attach.

        Returns:
            The recorded transaction dict with generated transaction_id.
        """
        transaction = {
            "transaction_id": str(uuid.uuid4()),
            "charge_id": charge_id,
            "amount": amount,
            "currency": currency.upper(),
            "processor": processor,
            "agency_id": agency_id,
            "booking_ref": booking_ref,
            "status": status,
            "metadata": metadata or {},
            "recorded_at": time.time(),
            "recorded_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        }

        # Buffer and flush
        self._buffer.append(transaction)
        if len(self._buffer) >= self._buffer_max:
            self._flush_buffer()
        else:
            # Always persist immediately for durability
            self._append_to_daily_log(transaction)

        # Publish event
        if self._event_bus:
            event_type = (
                EventType.PAYMENT_COMPLETED
                if status == "completed"
                else EventType.PAYMENT_FAILED
                if status == "failed"
                else EventType.PAYMENT_INITIATED
            )
            self._event_bus.publish(Event(
                type=event_type,
                data={
                    "transaction_id": transaction["transaction_id"],
                    "charge_id": charge_id,
                    "amount": amount,
                    "currency": currency,
                    "processor": processor,
                    "booking_ref": booking_ref,
                    "status": status,
                },
                source="payments.reconciliation",
                agency_id=agency_id,
            ))

        logger.info(
            "Recorded transaction %s: %s %d %s via %s [%s]",
            transaction["transaction_id"],
            charge_id, amount, currency, processor, status,
        )
        return transaction

    def get_transactions(
        self,
        agency_id: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        processor: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve transaction records with optional filters.

        Args:
            agency_id: Filter by agency.
            start_date: Start date (YYYY-MM-DD), inclusive.
            end_date: End date (YYYY-MM-DD), inclusive.
            processor: Filter by processor name.
            status: Filter by transaction status.

        Returns:
            List of matching transaction dicts, newest first.
        """
        transactions = []

        # Determine date range
        if start_date:
            start = datetime.strptime(start_date, "%Y-%m-%d").date()
        else:
            start = (datetime.now(timezone.utc) - timedelta(days=30)).date()

        if end_date:
            end = datetime.strptime(end_date, "%Y-%m-%d").date()
        else:
            end = datetime.now(timezone.utc).date()

        # Read daily log files
        current = start
        while current <= end:
            date_str = current.strftime("%Y-%m-%d")
            log_file = self._log_dir / f"transactions_{date_str}.json"
            if log_file.exists():
                try:
                    with open(log_file, "r") as f:
                        daily_records = json.load(f)
                    transactions.extend(daily_records)
                except (json.JSONDecodeError, IOError) as e:
                    logger.error(
                        "Failed to read transaction log %s: %s", log_file, e
                    )
            current += timedelta(days=1)

        # Apply filters
        if agency_id:
            transactions = [
                t for t in transactions if t.get("agency_id") == agency_id
            ]
        if processor:
            transactions = [
                t for t in transactions if t.get("processor") == processor
            ]
        if status:
            transactions = [
                t for t in transactions if t.get("status") == status
            ]

        # Sort newest first
        transactions.sort(
            key=lambda t: t.get("recorded_at", 0), reverse=True
        )
        return transactions

    def reconcile(
        self,
        agency_id: str,
        period_start: str,
        period_end: str,
        processor_records: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Compare internal records with processor records for a time period.

        If processor_records is provided, cross-references against internal
        logs. Otherwise, performs internal-only reconciliation (totals,
        counts, status breakdown).

        Args:
            agency_id: Agency to reconcile.
            period_start: Start date (YYYY-MM-DD).
            period_end: End date (YYYY-MM-DD).
            processor_records: Optional list of dicts from the processor
                               with at least {"charge_id", "amount", "status"}.

        Returns:
            {
                "agency_id": str,
                "period_start": str,
                "period_end": str,
                "internal_count": int,
                "internal_total": int,
                "processor_count": int or None,
                "processor_total": int or None,
                "matched": int,
                "unmatched_internal": List[str],
                "unmatched_processor": List[str],
                "amount_mismatches": List[dict],
                "status_mismatches": List[dict],
                "discrepancies": int,
                "reconciled_at": str,
            }
        """
        internal = self.get_transactions(
            agency_id=agency_id,
            start_date=period_start,
            end_date=period_end,
        )

        result = {
            "agency_id": agency_id,
            "period_start": period_start,
            "period_end": period_end,
            "internal_count": len(internal),
            "internal_total": sum(t.get("amount", 0) for t in internal),
            "processor_count": None,
            "processor_total": None,
            "matched": 0,
            "unmatched_internal": [],
            "unmatched_processor": [],
            "amount_mismatches": [],
            "status_mismatches": [],
            "discrepancies": 0,
            "reconciled_at": datetime.now(timezone.utc).isoformat(),
        }

        if processor_records is None:
            # Internal-only reconciliation
            result["processor_count"] = 0
            result["processor_total"] = 0
            logger.info(
                "Internal-only reconciliation for %s: %d transactions, "
                "total %d",
                agency_id, result["internal_count"], result["internal_total"],
            )
            return result

        # Cross-reference
        result["processor_count"] = len(processor_records)
        result["processor_total"] = sum(
            r.get("amount", 0) for r in processor_records
        )

        # Build lookup by charge_id
        internal_by_id = {t["charge_id"]: t for t in internal}
        processor_by_id = {r["charge_id"]: r for r in processor_records}

        all_charge_ids = set(internal_by_id.keys()) | set(processor_by_id.keys())

        for charge_id in all_charge_ids:
            int_rec = internal_by_id.get(charge_id)
            proc_rec = processor_by_id.get(charge_id)

            if int_rec and proc_rec:
                # Both sides have this charge — check for mismatches
                result["matched"] += 1

                if int_rec.get("amount") != proc_rec.get("amount"):
                    mismatch = {
                        "charge_id": charge_id,
                        "internal_amount": int_rec.get("amount"),
                        "processor_amount": proc_rec.get("amount"),
                    }
                    result["amount_mismatches"].append(mismatch)
                    result["discrepancies"] += 1

                if int_rec.get("status") != proc_rec.get("status"):
                    mismatch = {
                        "charge_id": charge_id,
                        "internal_status": int_rec.get("status"),
                        "processor_status": proc_rec.get("status"),
                    }
                    result["status_mismatches"].append(mismatch)
                    result["discrepancies"] += 1

            elif int_rec and not proc_rec:
                result["unmatched_internal"].append(charge_id)
                result["discrepancies"] += 1

            elif proc_rec and not int_rec:
                result["unmatched_processor"].append(charge_id)
                result["discrepancies"] += 1

        logger.info(
            "Reconciliation for %s (%s to %s): %d matched, %d discrepancies",
            agency_id, period_start, period_end,
            result["matched"], result["discrepancies"],
        )
        return result

    def get_revenue_summary(
        self,
        agency_id: Optional[str] = None,
        period: str = "month",
    ) -> Dict[str, Any]:
        """
        Generate revenue breakdown for a time period.

        Args:
            agency_id: Filter to a specific agency. None for all agencies.
            period: Time period — 'day', 'week', 'month', 'quarter', 'year'.

        Returns:
            {
                "period": str,
                "start_date": str,
                "end_date": str,
                "total_amount": int,
                "total_transactions": int,
                "by_currency": {currency: {"amount": int, "count": int}},
                "by_processor": {processor: {"amount": int, "count": int}},
                "by_status": {status: {"amount": int, "count": int}},
                "by_day": [{date, amount, count}, ...],
            }
        """
        now = datetime.now(timezone.utc)
        end_date = now.strftime("%Y-%m-%d")

        period_days = {
            "day": 1,
            "week": 7,
            "month": 30,
            "quarter": 90,
            "year": 365,
        }
        days = period_days.get(period, 30)
        start = (now - timedelta(days=days)).strftime("%Y-%m-%d")

        transactions = self.get_transactions(
            agency_id=agency_id,
            start_date=start,
            end_date=end_date,
        )

        # Build breakdowns
        by_currency: Dict[str, Dict[str, int]] = {}
        by_processor: Dict[str, Dict[str, int]] = {}
        by_status: Dict[str, Dict[str, int]] = {}
        by_day: Dict[str, Dict[str, int]] = {}

        total_amount = 0
        for t in transactions:
            amount = t.get("amount", 0)
            currency = t.get("currency", "USD")
            proc = t.get("processor", "unknown")
            status = t.get("status", "unknown")
            date = t.get("recorded_date", "unknown")

            total_amount += amount

            # By currency
            if currency not in by_currency:
                by_currency[currency] = {"amount": 0, "count": 0}
            by_currency[currency]["amount"] += amount
            by_currency[currency]["count"] += 1

            # By processor
            if proc not in by_processor:
                by_processor[proc] = {"amount": 0, "count": 0}
            by_processor[proc]["amount"] += amount
            by_processor[proc]["count"] += 1

            # By status
            if status not in by_status:
                by_status[status] = {"amount": 0, "count": 0}
            by_status[status]["amount"] += amount
            by_status[status]["count"] += 1

            # By day
            if date not in by_day:
                by_day[date] = {"amount": 0, "count": 0}
            by_day[date]["amount"] += amount
            by_day[date]["count"] += 1

        # Sort daily data
        daily_list = [
            {"date": d, "amount": v["amount"], "count": v["count"]}
            for d, v in sorted(by_day.items())
        ]

        return {
            "period": period,
            "start_date": start,
            "end_date": end_date,
            "agency_id": agency_id,
            "total_amount": total_amount,
            "total_transactions": len(transactions),
            "by_currency": by_currency,
            "by_processor": by_processor,
            "by_status": by_status,
            "by_day": daily_list,
        }

    def flag_discrepancy(
        self,
        transaction_id: str,
        reason: str,
    ) -> None:
        """
        Flag a transaction as having a discrepancy.

        Stores the discrepancy in the daily discrepancy log and publishes
        a PAYMENT_FAILED event to alert other neurons.

        Args:
            transaction_id: The internal transaction_id to flag.
            reason: Human-readable reason for the discrepancy.
        """
        discrepancy = {
            "discrepancy_id": str(uuid.uuid4())[:12],
            "transaction_id": transaction_id,
            "reason": reason,
            "flagged_at": time.time(),
            "flagged_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "resolved": False,
        }

        self._discrepancies.append(discrepancy)
        self._save_discrepancy(discrepancy)

        # Publish alert event
        if self._event_bus:
            self._event_bus.publish(Event(
                type=EventType.PAYMENT_FAILED,
                data={
                    "discrepancy_id": discrepancy["discrepancy_id"],
                    "transaction_id": transaction_id,
                    "reason": reason,
                    "type": "discrepancy",
                },
                source="payments.reconciliation",
            ))

        logger.warning(
            "Discrepancy flagged for transaction %s: %s",
            transaction_id, reason,
        )

    def get_discrepancies(
        self,
        resolved: Optional[bool] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get all flagged discrepancies.

        Args:
            resolved: Filter by resolution status. None returns all.

        Returns:
            List of discrepancy dicts.
        """
        if resolved is None:
            return list(self._discrepancies)
        return [
            d for d in self._discrepancies if d.get("resolved") == resolved
        ]

    def flush(self) -> None:
        """Force-flush the transaction buffer to disk."""
        self._flush_buffer()

    # -------------------------------------------------------------------
    # Internal persistence
    # -------------------------------------------------------------------

    def _append_to_daily_log(self, transaction: Dict[str, Any]) -> None:
        """Append a single transaction to the daily JSON log file."""
        date_str = transaction.get(
            "recorded_date",
            datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        )
        log_file = self._log_dir / f"transactions_{date_str}.json"

        existing: List[Dict[str, Any]] = []
        if log_file.exists():
            try:
                with open(log_file, "r") as f:
                    existing = json.load(f)
            except (json.JSONDecodeError, IOError):
                existing = []

        existing.append(transaction)

        try:
            with open(log_file, "w") as f:
                json.dump(existing, f, indent=2, default=str)
        except IOError as e:
            logger.error("Failed to write transaction log %s: %s", log_file, e)

    def _flush_buffer(self) -> None:
        """Flush the in-memory buffer to daily log files."""
        if not self._buffer:
            return

        # Group by date
        by_date: Dict[str, List[Dict[str, Any]]] = {}
        for t in self._buffer:
            date = t.get(
                "recorded_date",
                datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            )
            if date not in by_date:
                by_date[date] = []
            by_date[date].append(t)

        # Note: Individual transactions are already appended in
        # record_transaction, so we just clear the buffer here.
        count = len(self._buffer)
        self._buffer.clear()
        logger.debug("Flushed %d transactions from buffer", count)

    def _save_discrepancy(self, discrepancy: Dict[str, Any]) -> None:
        """Persist a discrepancy to the daily discrepancy log."""
        date_str = discrepancy.get(
            "flagged_date",
            datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        )
        log_file = self._log_dir / f"discrepancies_{date_str}.json"

        existing: List[Dict[str, Any]] = []
        if log_file.exists():
            try:
                with open(log_file, "r") as f:
                    existing = json.load(f)
            except (json.JSONDecodeError, IOError):
                existing = []

        existing.append(discrepancy)

        try:
            with open(log_file, "w") as f:
                json.dump(existing, f, indent=2, default=str)
        except IOError as e:
            logger.error(
                "Failed to write discrepancy log %s: %s", log_file, e
            )
