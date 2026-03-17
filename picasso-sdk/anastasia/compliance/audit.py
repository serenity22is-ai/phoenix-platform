"""
Compliance Audit Trail -- Append-only, tamper-evident audit logging.

Every auditable action (data access, consent changes, booking operations,
payment processing) is recorded as an immutable entry in daily JSON log
files. Entries are chained with SHA-256 hashes so any tampering (insertion,
deletion, or modification of entries) breaks the hash chain and is
detectable during verification.

Storage is local filesystem (one JSON-lines file per day). In production,
these files should be replicated to immutable storage (S3 with Object Lock,
or equivalent) for regulatory defensibility.

Retention default is 730 days (2 years) per IATA BSP Resolution 890
booking record requirements.

MYSTES KYRIOS LLC -- Confidential.
"""

import hashlib
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..core.events import EventBus, Event, EventType

logger = logging.getLogger(__name__)


class ComplianceAudit:
    """
    Append-only audit trail with SHA-256 hash chain for tamper detection.

    Each audit entry includes a ``prev_hash`` field containing the SHA-256
    digest of the preceding entry's JSON representation. The first entry
    of each daily log uses a genesis hash. Verification walks the chain
    and confirms every hash matches.
    """

    GENESIS_HASH = "0" * 64  # SHA-256 zero hash for first entry in a log file

    def __init__(self, event_bus: EventBus, storage_dir: str):
        """
        Initialize the audit trail.

        Args:
            event_bus: Shared event bus for publishing audit events.
            storage_dir: Filesystem directory for audit log files.
                         Created if it does not exist.
        """
        self._event_bus = event_bus
        self._storage_dir = storage_dir
        self._last_hash: str = self.GENESIS_HASH
        self._entry_count = 0

        os.makedirs(self._storage_dir, exist_ok=True)

        # Recover hash chain state from today's log if it exists
        self._recover_chain_state()

        logger.info(
            "ComplianceAudit initialized, storage_dir=%s, chain_state=%s...%s",
            self._storage_dir,
            self._last_hash[:8],
            self._last_hash[-8:],
        )

    # ------------------------------------------------------------------ #
    # Public API                                                          #
    # ------------------------------------------------------------------ #

    def log_action(
        self,
        actor: str,
        action: str,
        resource: str,
        details: Optional[dict] = None,
        agency_id: Optional[str] = None,
    ) -> str:
        """
        Log an auditable action.

        Args:
            actor: Identity of who performed the action (user ID, service name).
            action: Action performed (e.g. ``"booking.create"``, ``"payment.charge"``).
            resource: Resource acted upon (e.g. ``"booking:12345"``, ``"user:789"``).
            details: Optional additional context.
            agency_id: Agency scope for multi-tenant filtering.

        Returns:
            Unique audit entry ID.
        """
        return self._append_entry(
            actor=actor,
            action=action,
            resource=resource,
            entry_type="action",
            details=details or {},
            agency_id=agency_id,
        )

    def log_data_access(
        self,
        actor: str,
        data_type: str,
        purpose: str,
        agency_id: Optional[str] = None,
    ) -> str:
        """
        Log who accessed what data and why.

        Required for GDPR Art. 30 records of processing activities and
        PCI DSS Requirement 10 (access logging).

        Args:
            actor: Identity of who accessed the data.
            data_type: Category of data accessed (e.g. ``"payment_card"``, ``"pii"``).
            purpose: Stated purpose for access (e.g. ``"booking_fulfillment"``).
            agency_id: Agency scope.

        Returns:
            Unique audit entry ID.
        """
        return self._append_entry(
            actor=actor,
            action="data_access",
            resource=f"data_type:{data_type}",
            entry_type="data_access",
            details={"data_type": data_type, "purpose": purpose},
            agency_id=agency_id,
        )

    def log_consent(
        self,
        user_id: str,
        consent_type: str,
        granted: bool,
        agency_id: Optional[str] = None,
    ) -> str:
        """
        Log a consent decision.

        GDPR Art. 7 requires demonstrable proof that consent was given.
        This creates an immutable record of consent grants and withdrawals.

        Args:
            user_id: User who gave or withdrew consent.
            consent_type: Type of consent (e.g. ``"marketing_email"``, ``"data_processing"``).
            granted: True if consent was given, False if withdrawn.
            agency_id: Agency scope.

        Returns:
            Unique audit entry ID.
        """
        return self._append_entry(
            actor=user_id,
            action="consent_granted" if granted else "consent_withdrawn",
            resource=f"consent:{consent_type}",
            entry_type="consent",
            details={
                "user_id": user_id,
                "consent_type": consent_type,
                "granted": granted,
            },
            agency_id=agency_id,
        )

    def get_audit_trail(
        self,
        agency_id: Optional[str] = None,
        actor: Optional[str] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        limit: int = 100,
    ) -> List[dict]:
        """
        Query the audit trail with optional filters.

        Reads from daily log files within the time range and applies
        filters. Results are ordered chronologically (oldest first).

        Args:
            agency_id: Filter by agency.
            actor: Filter by actor.
            start_time: Unix timestamp lower bound.
            end_time: Unix timestamp upper bound.
            limit: Maximum entries to return.

        Returns:
            List of audit entry dictionaries.
        """
        entries: List[dict] = []
        log_files = self._get_log_files_in_range(start_time, end_time)

        for log_file in log_files:
            file_path = os.path.join(self._storage_dir, log_file)
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            entry = json.loads(line)
                        except json.JSONDecodeError:
                            logger.warning("Corrupt audit line in %s", log_file)
                            continue

                        # Apply filters
                        if agency_id and entry.get("agency_id") != agency_id:
                            continue
                        if actor and entry.get("actor") != actor:
                            continue
                        if start_time and entry.get("timestamp", 0) < start_time:
                            continue
                        if end_time and entry.get("timestamp", 0) > end_time:
                            continue

                        entries.append(entry)

                        if len(entries) >= limit:
                            return entries
            except FileNotFoundError:
                continue
            except OSError as e:
                logger.error("Error reading audit log %s: %s", log_file, e)

        return entries

    def export_audit_trail(
        self, agency_id: str, format: str = "json"
    ) -> str:
        """
        Export the full audit trail for an agency for compliance review.

        Args:
            agency_id: Agency to export trail for.
            format: Export format. Currently supports ``"json"`` and ``"csv"``.

        Returns:
            File path of the exported audit trail.
        """
        entries = self.get_audit_trail(agency_id=agency_id, limit=1_000_000)

        timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        export_dir = os.path.join(self._storage_dir, "exports")
        os.makedirs(export_dir, exist_ok=True)

        if format == "csv":
            export_path = os.path.join(
                export_dir, f"audit_{agency_id}_{timestamp_str}.csv"
            )
            self._export_csv(entries, export_path)
        else:
            export_path = os.path.join(
                export_dir, f"audit_{agency_id}_{timestamp_str}.json"
            )
            with open(export_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "agency_id": agency_id,
                        "exported_at": time.time(),
                        "entry_count": len(entries),
                        "entries": entries,
                    },
                    f,
                    indent=2,
                )

        logger.info(
            "Exported %d audit entries for agency %s to %s",
            len(entries), agency_id, export_path,
        )
        return export_path

    def get_data_access_report(
        self, agency_id: str, period_days: int = 30
    ) -> dict:
        """
        Generate a data access report showing who accessed what data.

        Useful for GDPR Art. 30 compliance and internal security reviews.

        Args:
            agency_id: Agency to report on.
            period_days: Number of days to look back.

        Returns:
            Report dictionary with access counts by actor and data type.
        """
        start_time = time.time() - (period_days * 86400)
        entries = self.get_audit_trail(
            agency_id=agency_id,
            start_time=start_time,
            limit=1_000_000,
        )

        # Filter to data access entries only
        access_entries = [
            e for e in entries if e.get("entry_type") == "data_access"
        ]

        # Aggregate by actor
        by_actor: Dict[str, int] = {}
        by_data_type: Dict[str, int] = {}
        by_purpose: Dict[str, int] = {}

        for entry in access_entries:
            actor = entry.get("actor", "unknown")
            details = entry.get("details", {})
            data_type = details.get("data_type", "unknown")
            purpose = details.get("purpose", "unknown")

            by_actor[actor] = by_actor.get(actor, 0) + 1
            by_data_type[data_type] = by_data_type.get(data_type, 0) + 1
            by_purpose[purpose] = by_purpose.get(purpose, 0) + 1

        return {
            "agency_id": agency_id,
            "period_days": period_days,
            "period_start": start_time,
            "period_end": time.time(),
            "total_access_events": len(access_entries),
            "by_actor": by_actor,
            "by_data_type": by_data_type,
            "by_purpose": by_purpose,
        }

    def retention_cleanup(self, max_age_days: int = 730) -> int:
        """
        Delete audit log files older than the retention period.

        Default is 730 days (2 years) per IATA BSP booking record
        retention requirements. Logs a warning before deletion.

        Args:
            max_age_days: Maximum age in days. Files older than this are deleted.

        Returns:
            Number of files deleted.
        """
        cutoff = time.time() - (max_age_days * 86400)
        cutoff_date = datetime.fromtimestamp(cutoff, tz=timezone.utc).strftime(
            "%Y-%m-%d"
        )
        deleted = 0

        try:
            for filename in sorted(os.listdir(self._storage_dir)):
                if not filename.startswith("audit_") or not filename.endswith(".jsonl"):
                    continue

                # Parse date from filename: audit_YYYY-MM-DD.jsonl
                try:
                    file_date = filename.replace("audit_", "").replace(".jsonl", "")
                    if file_date < cutoff_date:
                        file_path = os.path.join(self._storage_dir, filename)
                        logger.warning(
                            "Retention cleanup: deleting %s (older than %d days)",
                            filename, max_age_days,
                        )
                        os.remove(file_path)
                        deleted += 1
                except (ValueError, OSError) as e:
                    logger.error("Error during retention cleanup of %s: %s", filename, e)
        except OSError as e:
            logger.error("Error listing audit directory: %s", e)

        if deleted:
            logger.info(
                "Retention cleanup complete: deleted %d file(s) older than %d days",
                deleted, max_age_days,
            )

        return deleted

    def verify_chain(self, date: Optional[str] = None) -> dict:
        """
        Verify the hash chain integrity of a daily log file.

        Args:
            date: Date string ``YYYY-MM-DD``. Defaults to today.

        Returns:
            Dictionary with ``valid`` (bool), ``entries_checked`` (int),
            and ``error`` (str or None).
        """
        if date is None:
            date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        filename = f"audit_{date}.jsonl"
        file_path = os.path.join(self._storage_dir, filename)

        if not os.path.exists(file_path):
            return {"valid": True, "entries_checked": 0, "error": None}

        expected_hash = self.GENESIS_HASH
        entries_checked = 0

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue

                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        return {
                            "valid": False,
                            "entries_checked": entries_checked,
                            "error": f"Corrupt JSON at line {line_num}",
                        }

                    if entry.get("prev_hash") != expected_hash:
                        return {
                            "valid": False,
                            "entries_checked": entries_checked,
                            "error": (
                                f"Hash chain broken at line {line_num}: "
                                f"expected {expected_hash[:16]}..., "
                                f"got {entry.get('prev_hash', 'MISSING')[:16]}..."
                            ),
                        }

                    expected_hash = self._hash_entry(entry)
                    entries_checked += 1

        except OSError as e:
            return {
                "valid": False,
                "entries_checked": entries_checked,
                "error": f"File read error: {e}",
            }

        return {"valid": True, "entries_checked": entries_checked, "error": None}

    # ------------------------------------------------------------------ #
    # Internal methods                                                    #
    # ------------------------------------------------------------------ #

    def _append_entry(
        self,
        actor: str,
        action: str,
        resource: str,
        entry_type: str,
        details: dict,
        agency_id: Optional[str],
    ) -> str:
        """Create and append an audit entry to today's log file."""
        audit_id = f"aud_{uuid.uuid4().hex[:16]}"
        now = time.time()

        entry = {
            "audit_id": audit_id,
            "timestamp": now,
            "actor": actor,
            "action": action,
            "resource": resource,
            "entry_type": entry_type,
            "details": details,
            "agency_id": agency_id,
            "ip_address": None,  # Set by caller if available
            "prev_hash": self._last_hash,
        }

        # Write to daily log file
        log_file = self._get_today_log_path()
        try:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, separators=(",", ":")) + "\n")
        except OSError as e:
            logger.error("Failed to write audit entry: %s", e)
            raise

        # Update hash chain
        self._last_hash = self._hash_entry(entry)
        self._entry_count += 1

        # Publish event
        self._event_bus.publish(Event(
            type=EventType.AUDIT_ENTRY,
            source="compliance.audit",
            agency_id=agency_id,
            data={
                "audit_id": audit_id,
                "action": action,
                "actor": actor,
                "resource": resource,
                "entry_type": entry_type,
            },
        ))

        logger.debug(
            "Audit entry %s: %s by %s on %s",
            audit_id, action, actor, resource,
        )

        return audit_id

    def _get_today_log_path(self) -> str:
        """Get the file path for today's audit log."""
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return os.path.join(self._storage_dir, f"audit_{date_str}.jsonl")

    def _get_log_files_in_range(
        self,
        start_time: Optional[float],
        end_time: Optional[float],
    ) -> List[str]:
        """List audit log filenames that fall within the time range."""
        try:
            all_files = sorted(
                f for f in os.listdir(self._storage_dir)
                if f.startswith("audit_") and f.endswith(".jsonl")
            )
        except OSError:
            return []

        if not start_time and not end_time:
            return all_files

        start_date = (
            datetime.fromtimestamp(start_time, tz=timezone.utc).strftime("%Y-%m-%d")
            if start_time
            else "0000-00-00"
        )
        end_date = (
            datetime.fromtimestamp(end_time, tz=timezone.utc).strftime("%Y-%m-%d")
            if end_time
            else "9999-99-99"
        )

        filtered = []
        for f in all_files:
            file_date = f.replace("audit_", "").replace(".jsonl", "")
            if start_date <= file_date <= end_date:
                filtered.append(f)

        return filtered

    def _recover_chain_state(self) -> None:
        """Recover the last hash from today's log file if it exists."""
        log_path = self._get_today_log_path()
        if not os.path.exists(log_path):
            self._last_hash = self.GENESIS_HASH
            return

        last_entry = None
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            last_entry = json.loads(line)
                        except json.JSONDecodeError:
                            continue
        except OSError:
            self._last_hash = self.GENESIS_HASH
            return

        if last_entry:
            self._last_hash = self._hash_entry(last_entry)
            logger.debug("Recovered chain state from existing log")
        else:
            self._last_hash = self.GENESIS_HASH

    @staticmethod
    def _hash_entry(entry: dict) -> str:
        """
        Compute SHA-256 hash of an audit entry.

        The hash covers all fields including ``prev_hash``, creating the
        chain. Fields are serialized with sorted keys and compact separators
        for deterministic output.
        """
        canonical = json.dumps(entry, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _export_csv(entries: List[dict], path: str) -> None:
        """Export entries as CSV."""
        if not entries:
            with open(path, "w", encoding="utf-8") as f:
                f.write("audit_id,timestamp,actor,action,resource,agency_id\n")
            return

        with open(path, "w", encoding="utf-8") as f:
            f.write("audit_id,timestamp,actor,action,resource,agency_id,details\n")
            for entry in entries:
                details_str = json.dumps(entry.get("details", {})).replace('"', '""')
                f.write(
                    f'"{entry.get("audit_id", "")}",{entry.get("timestamp", 0)},'
                    f'"{entry.get("actor", "")}","{entry.get("action", "")}",'
                    f'"{entry.get("resource", "")}","{entry.get("agency_id", "")}",'
                    f'"{details_str}"\n'
                )
