"""
Data Exporter — Full data portability for agency bookings, configs, and code.

Ensures no vendor lock-in: agencies can export everything they paid for at
any time. Exports are timestamped, chunked for large datasets, and stored
locally for audit and re-download. Supports JSON, CSV, and XML formats.

If an agency leaves, they keep everything. That is the contract.

MYSTES KYRIOS LLC — Confidential.
"""

import json
import logging
import os
import time
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from ..core.events import Event, EventBus, EventType
from .formats import ExportFormats

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_CHUNK_BYTES = 50 * 1024 * 1024  # 50 MB per file chunk
SUPPORTED_FREQUENCIES = {"daily", "weekly", "monthly", "quarterly"}


class DataExporter:
    """
    Exports agency data in portable formats.

    Every agency-facing datum — bookings, configuration, generated
    integration code, analytics — can be exported as flat files.
    Exports are logged, stored in ``storage_dir``, and published
    to the event bus for auditing.

    Usage:
        exporter = DataExporter(event_bus, storage_dir="/exports")
        path = exporter.export_bookings("agency_123", format="csv")
    """

    def __init__(self, event_bus: EventBus, storage_dir: str):
        """
        Args:
            event_bus: Shared ANASTASiA event bus for publish/subscribe.
            storage_dir: Filesystem directory where export files are stored.
                         Created automatically if it does not exist.
        """
        self._event_bus = event_bus
        self._storage_dir = storage_dir
        self._export_history: Dict[str, List[dict]] = {}  # agency_id -> [records]
        self._scheduled_exports: Dict[str, dict] = {}     # agency_id -> schedule
        os.makedirs(storage_dir, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def export_bookings(
        self,
        agency_id: str,
        start_date: str = None,
        end_date: str = None,
        format: str = "json",
    ) -> str:
        """
        Export booking history for an agency.

        Args:
            agency_id: Agency whose bookings to export.
            start_date: Optional ISO-8601 date string (inclusive lower bound).
            end_date: Optional ISO-8601 date string (inclusive upper bound).
            format: Output format — "json", "csv", or "xml".

        Returns:
            Absolute path to the exported file.
        """
        logger.info(
            "Exporting bookings for agency %s (range: %s to %s, format: %s)",
            agency_id, start_date or "all", end_date or "all", format,
        )

        bookings = self._fetch_bookings(agency_id, start_date, end_date)

        file_path = self._write_export(
            agency_id=agency_id,
            data=bookings,
            export_type="bookings",
            format=format,
        )

        self._publish_export_event(agency_id, "bookings", file_path, len(bookings))
        return file_path

    def export_config(self, agency_id: str, format: str = "json") -> str:
        """
        Export agency configuration.

        Includes pricing rules, feature flags, notification settings,
        branding, and integration endpoints — everything needed to
        reconstruct the agency's setup on another platform.

        Args:
            agency_id: Agency whose config to export.
            format: Output format.

        Returns:
            Absolute path to the exported file.
        """
        logger.info("Exporting config for agency %s (format: %s)", agency_id, format)

        config = self._fetch_config(agency_id)

        file_path = self._write_export(
            agency_id=agency_id,
            data=config,
            export_type="config",
            format=format,
        )

        self._publish_export_event(agency_id, "config", file_path, 1)
        return file_path

    def export_integration_code(self, agency_id: str) -> str:
        """
        Export all generated integration code for an agency.

        Returns a JSON file containing a dict-of-dicts structure that
        mirrors the code tree:
            {
                "adapters/payment_adapter.py": "<source code>",
                "connectors/gds_connector.py": "<source code>",
                ...
            }

        This is not a binary zip — it is a JSON manifest of all generated
        source files so the agency can reconstruct them on any platform.

        Args:
            agency_id: Agency whose integration code to export.

        Returns:
            Absolute path to the exported JSON file.
        """
        logger.info("Exporting integration code for agency %s", agency_id)

        code_tree = self._fetch_integration_code(agency_id)

        file_path = self._write_export(
            agency_id=agency_id,
            data=code_tree,
            export_type="integration_code",
            format="json",
        )

        file_count = len(code_tree) if isinstance(code_tree, dict) else 0
        self._publish_export_event(agency_id, "integration_code", file_path, file_count)
        return file_path

    def export_analytics(
        self,
        agency_id: str,
        period_days: int = 90,
        format: str = "json",
    ) -> str:
        """
        Export analytics data for an agency.

        Covers search volume, booking conversion, revenue, arbitrage
        savings, and POS performance over the requested period.

        Args:
            agency_id: Agency whose analytics to export.
            period_days: Number of days of history to include.
            format: Output format.

        Returns:
            Absolute path to the exported file.
        """
        logger.info(
            "Exporting analytics for agency %s (period: %d days, format: %s)",
            agency_id, period_days, format,
        )

        analytics = self._fetch_analytics(agency_id, period_days)

        file_path = self._write_export(
            agency_id=agency_id,
            data=analytics,
            export_type="analytics",
            format=format,
        )

        record_count = len(analytics) if isinstance(analytics, list) else 1
        self._publish_export_event(agency_id, "analytics", file_path, record_count)
        return file_path

    def export_all(self, agency_id: str, format: str = "json") -> str:
        """
        Comprehensive export of all agency data.

        Combines bookings, configuration, integration code, and analytics
        into a single export file. This is the "take everything and go"
        option — the nuclear portability guarantee.

        Args:
            agency_id: Agency to export.
            format: Output format for the combined payload.

        Returns:
            Absolute path to the exported file.
        """
        logger.info("Exporting ALL data for agency %s (format: %s)", agency_id, format)

        full_export = {
            "export_metadata": {
                "agency_id": agency_id,
                "exported_at": datetime.utcnow().isoformat() + "Z",
                "format": format,
                "platform": "ANASTASiA",
                "version": "1.0.0",
            },
            "bookings": self._fetch_bookings(agency_id),
            "config": self._fetch_config(agency_id),
            "integration_code": self._fetch_integration_code(agency_id),
            "analytics": self._fetch_analytics(agency_id, period_days=365),
        }

        file_path = self._write_export(
            agency_id=agency_id,
            data=full_export,
            export_type="full_export",
            format=format,
        )

        self._publish_export_event(agency_id, "full_export", file_path, 1)
        return file_path

    def schedule_export(
        self,
        agency_id: str,
        frequency: str = "monthly",
    ) -> dict:
        """
        Schedule recurring automated exports.

        Args:
            agency_id: Agency to schedule exports for.
            frequency: One of "daily", "weekly", "monthly", "quarterly".

        Returns:
            Schedule record dict with id, frequency, next_run, and status.

        Raises:
            ValueError: If frequency is not one of the supported values.
        """
        if frequency not in SUPPORTED_FREQUENCIES:
            raise ValueError(
                f"Unsupported frequency '{frequency}'. "
                f"Must be one of: {', '.join(sorted(SUPPORTED_FREQUENCIES))}"
            )

        schedule_id = f"sched_{uuid.uuid4().hex[:12]}"
        now = datetime.utcnow()
        next_run = self._compute_next_run(now, frequency)

        record = {
            "schedule_id": schedule_id,
            "agency_id": agency_id,
            "frequency": frequency,
            "created_at": now.isoformat() + "Z",
            "next_run": next_run.isoformat() + "Z",
            "status": "active",
            "last_export_path": None,
        }

        self._scheduled_exports[agency_id] = record
        logger.info(
            "Scheduled %s export for agency %s (next run: %s)",
            frequency, agency_id, record["next_run"],
        )
        return record

    def get_export_history(self, agency_id: str) -> List[dict]:
        """
        List previous exports for an agency.

        Returns:
            List of export records, newest first.
        """
        history = self._export_history.get(agency_id, [])
        return list(reversed(history))

    # ------------------------------------------------------------------
    # Data fetching (integration points)
    # ------------------------------------------------------------------

    def _fetch_bookings(
        self,
        agency_id: str,
        start_date: str = None,
        end_date: str = None,
    ) -> List[dict]:
        """
        Retrieve booking records for an agency.

        In production this queries the database. The stub returns data
        from the event bus booking history as a stand-in.
        """
        bookings = []

        # Pull booking events from the event bus log
        for event in self._event_bus.get_recent_events(
            event_type=EventType.BOOKING_CONFIRMED,
            agency_id=agency_id,
            limit=10000,
        ):
            record = {
                "booking_id": event.data.get("booking_id", event.id),
                "agency_id": agency_id,
                "status": "confirmed",
                "created_at": datetime.utcfromtimestamp(event.timestamp).isoformat() + "Z",
                **{k: v for k, v in event.data.items() if k != "booking_id"},
            }
            bookings.append(record)

        # Apply date filters
        if start_date:
            bookings = [
                b for b in bookings
                if b.get("created_at", "") >= start_date
            ]
        if end_date:
            bookings = [
                b for b in bookings
                if b.get("created_at", "") <= end_date
            ]

        return bookings

    def _fetch_config(self, agency_id: str) -> dict:
        """
        Retrieve configuration for an agency.

        In production this pulls from the tenant config store.
        """
        return {
            "agency_id": agency_id,
            "agency_name": f"Agency {agency_id}",
            "created_at": datetime.utcnow().isoformat() + "Z",
            "default_currency": "USD",
            "default_language": "en",
            "timezone": "UTC",
            "pos_markets": [],
            "pricing_rules": {},
            "fee_config": {},
            "notification_settings": {},
            "api_keys_redacted": {},
            "integration_endpoints": [],
            "branding": {},
            "contact_info": {},
            "compliance_settings": {},
            "feature_flags": {},
        }

    def _fetch_integration_code(self, agency_id: str) -> dict:
        """
        Retrieve generated integration code for an agency.

        Returns a dict mapping file paths to source code strings.
        In production this reads from the code generation store.
        """
        return {
            "_metadata": {
                "agency_id": agency_id,
                "generated_at": datetime.utcnow().isoformat() + "Z",
                "file_count": 0,
                "note": "Integration code is populated by the integrator neuron.",
            }
        }

    def _fetch_analytics(self, agency_id: str, period_days: int = 90) -> dict:
        """
        Retrieve analytics data for an agency.

        In production this aggregates from the analytics store.
        """
        now = datetime.utcnow()
        return {
            "agency_id": agency_id,
            "period_start": (now - timedelta(days=period_days)).isoformat() + "Z",
            "period_end": now.isoformat() + "Z",
            "search_volume": 0,
            "bookings_total": 0,
            "bookings_confirmed": 0,
            "bookings_cancelled": 0,
            "revenue_total": 0.0,
            "revenue_currency": "USD",
            "arbitrage_savings_total": 0.0,
            "top_routes": [],
            "top_pos_markets": [],
            "conversion_rate": 0.0,
        }

    # ------------------------------------------------------------------
    # File writing with chunking
    # ------------------------------------------------------------------

    def _write_export(
        self,
        agency_id: str,
        data: Any,
        export_type: str,
        format: str,
    ) -> str:
        """
        Serialize and write data to disk with automatic chunking.

        Returns the path to the primary export file. If the data exceeds
        MAX_CHUNK_BYTES, multiple numbered chunk files are written and
        the primary file contains a manifest pointing to them.
        """
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        export_id = uuid.uuid4().hex[:8]
        base_name = f"{agency_id}_{export_type}_{timestamp}_{export_id}"

        # Serialize
        content = self._serialize(data, format)

        # Check if chunking is needed
        content_bytes = content.encode("utf-8")
        if len(content_bytes) > MAX_CHUNK_BYTES:
            file_path = self._write_chunked(base_name, content_bytes, format)
        else:
            extension = self._format_extension(format)
            file_path = os.path.join(self._storage_dir, f"{base_name}.{extension}")
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)

        # Record in history
        record = {
            "export_id": export_id,
            "export_type": export_type,
            "format": format,
            "file_path": os.path.abspath(file_path),
            "size_bytes": len(content_bytes),
            "exported_at": datetime.utcnow().isoformat() + "Z",
            "agency_id": agency_id,
        }
        if agency_id not in self._export_history:
            self._export_history[agency_id] = []
        self._export_history[agency_id].append(record)

        logger.info(
            "Export written: %s (%d bytes)", file_path, len(content_bytes)
        )
        return os.path.abspath(file_path)

    def _write_chunked(
        self,
        base_name: str,
        content_bytes: bytes,
        format: str,
    ) -> str:
        """
        Write large exports as numbered chunk files with a manifest.

        Each chunk is at most MAX_CHUNK_BYTES. The manifest file lists
        all chunks in order for reassembly.
        """
        extension = self._format_extension(format)
        chunks = []
        offset = 0
        chunk_index = 0

        while offset < len(content_bytes):
            chunk_data = content_bytes[offset:offset + MAX_CHUNK_BYTES]
            chunk_name = f"{base_name}_chunk{chunk_index:04d}.{extension}"
            chunk_path = os.path.join(self._storage_dir, chunk_name)

            with open(chunk_path, "wb") as f:
                f.write(chunk_data)

            chunks.append({
                "chunk_index": chunk_index,
                "file_name": chunk_name,
                "size_bytes": len(chunk_data),
            })
            offset += MAX_CHUNK_BYTES
            chunk_index += 1

        # Write manifest
        manifest_name = f"{base_name}_manifest.json"
        manifest_path = os.path.join(self._storage_dir, manifest_name)
        manifest = {
            "total_size_bytes": len(content_bytes),
            "chunk_count": len(chunks),
            "format": format,
            "chunks": chunks,
        }
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

        logger.info(
            "Large export chunked into %d files (manifest: %s)",
            len(chunks), manifest_path,
        )
        return os.path.abspath(manifest_path)

    # ------------------------------------------------------------------
    # Serialization helpers
    # ------------------------------------------------------------------

    def _serialize(self, data: Any, format: str) -> str:
        """Serialize data to the requested format string."""
        fmt = format.lower()
        if fmt == "json":
            return ExportFormats.to_json(data)
        elif fmt == "csv":
            if isinstance(data, list):
                return ExportFormats.to_csv(data)
            elif isinstance(data, dict):
                # Wrap single dict in a list for CSV
                return ExportFormats.to_csv([data])
            else:
                return ExportFormats.to_csv([{"value": data}])
        elif fmt == "xml":
            return ExportFormats.to_xml(data)
        else:
            raise ValueError(
                f"Unsupported export format '{format}'. "
                f"Use 'json', 'csv', or 'xml'."
            )

    @staticmethod
    def _format_extension(format: str) -> str:
        """Map format name to file extension."""
        return {"json": "json", "csv": "csv", "xml": "xml"}.get(
            format.lower(), "dat"
        )

    # ------------------------------------------------------------------
    # Scheduling helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_next_run(from_dt: datetime, frequency: str) -> datetime:
        """Compute the next run timestamp based on frequency."""
        if frequency == "daily":
            return from_dt + timedelta(days=1)
        elif frequency == "weekly":
            return from_dt + timedelta(weeks=1)
        elif frequency == "monthly":
            # Approximate: 30 days
            return from_dt + timedelta(days=30)
        elif frequency == "quarterly":
            return from_dt + timedelta(days=90)
        else:
            return from_dt + timedelta(days=30)

    # ------------------------------------------------------------------
    # Event publishing
    # ------------------------------------------------------------------

    def _publish_export_event(
        self,
        agency_id: str,
        export_type: str,
        file_path: str,
        record_count: int,
    ) -> None:
        """Publish an audit event for a completed export."""
        self._event_bus.publish(Event(
            type=EventType.AUDIT_ENTRY,
            source="portability",
            agency_id=agency_id,
            data={
                "action": "data_export",
                "export_type": export_type,
                "file_path": file_path,
                "record_count": record_count,
                "timestamp": datetime.utcnow().isoformat() + "Z",
            },
        ))
