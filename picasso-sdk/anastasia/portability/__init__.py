"""
Portability Neuron — Ensures zero vendor lock-in for ANASTASiA agencies.

Agencies can export their data, bookings, configurations, and generated
integration code at any time. If they leave the platform, they keep
everything they paid for. Migration tools transform data between
ANASTASiA's internal format and industry-standard GDS/NDC formats.

Components:
    DataExporter   — Export bookings, configs, code, analytics to files.
    MigrationTool  — Transform data between systems (Amadeus, Sabre, etc.).
    ExportFormats  — JSON/CSV/XML serialization and schema validation.

Module registration:
    PortabilityModule subclasses NeuronModule and wires all three
    components together during initialize().

MYSTES KYRIOS LLC — Confidential.
"""

import logging
import os
from typing import Any, Dict, List

from ..core.events import EventBus, Event, EventType
from ..core.registry import NeuronModule
from .export import DataExporter
from .formats import ExportFormats
from .migration import MigrationTool

logger = logging.getLogger(__name__)

__all__ = [
    "PortabilityModule",
    "DataExporter",
    "MigrationTool",
    "ExportFormats",
]


class PortabilityModule(NeuronModule):
    """
    ANASTASiA neuron for data portability and migration.

    Wires together the DataExporter, MigrationTool, and ExportFormats
    into a single registrable neuron that the ModuleRegistry can
    initialize alongside all other neurons.

    This module has no dependencies on other neurons — portability
    is a standalone guarantee that works regardless of which other
    modules are active.

    Usage:
        from anastasia.portability import PortabilityModule

        registry.register(PortabilityModule())
        registry.initialize_all(config)

        module = registry.get("portability")
        module.exporter.export_all("agency_123")
    """

    def __init__(self):
        self._event_bus: EventBus = None
        self._exporter: DataExporter = None
        self._migration_tool: MigrationTool = None
        self._initialized: bool = False

    # ------------------------------------------------------------------
    # NeuronModule interface
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        """Unique module identifier."""
        return "portability"

    @property
    def version(self) -> str:
        """Module version."""
        return "1.0.0"

    @property
    def dependencies(self) -> List[str]:
        """No dependencies — portability is a standalone guarantee."""
        return []

    def initialize(self, event_bus: EventBus, config: Dict[str, Any]) -> None:
        """
        Initialize the portability neuron.

        Creates the DataExporter and MigrationTool, wiring both to the
        shared event bus. The storage directory for exports defaults to
        ``./exports`` but can be overridden via config.

        Args:
            event_bus: Shared ANASTASiA event bus.
            config: Platform configuration dict. Recognized keys:
                - ``portability_storage_dir``: Filesystem path for export
                  files (default: ``"./exports"``).
        """
        self._event_bus = event_bus

        # Resolve storage directory
        storage_dir = config.get("portability_storage_dir", "./exports")
        storage_dir = os.path.abspath(storage_dir)

        # Wire up components
        self._exporter = DataExporter(
            event_bus=event_bus,
            storage_dir=storage_dir,
        )

        self._migration_tool = MigrationTool(
            event_bus=event_bus,
        )

        self._initialized = True

        logger.info(
            "Portability neuron initialized (storage: %s)", storage_dir
        )

    def health_check(self) -> Dict[str, Any]:
        """
        Return health status of the portability neuron.

        Checks:
            - Module is initialized.
            - Storage directory exists and is writable.
            - Exporter and migration tool are instantiated.
        """
        if not self._initialized:
            return {
                "healthy": False,
                "details": "Portability module not initialized.",
            }

        issues = []

        # Check storage directory
        if self._exporter:
            storage = self._exporter._storage_dir
            if not os.path.isdir(storage):
                issues.append(f"Storage directory does not exist: {storage}")
            elif not os.access(storage, os.W_OK):
                issues.append(f"Storage directory not writable: {storage}")

        if self._exporter is None:
            issues.append("DataExporter not instantiated.")
        if self._migration_tool is None:
            issues.append("MigrationTool not instantiated.")

        if issues:
            return {
                "healthy": False,
                "details": "; ".join(issues),
                "issues": issues,
            }

        return {
            "healthy": True,
            "details": "Portability neuron operational.",
            "storage_dir": self._exporter._storage_dir,
            "known_migration_targets": self._list_known_targets(),
        }

    def shutdown(self) -> None:
        """Cleanup on platform shutdown."""
        logger.info("Portability neuron shutting down.")
        self._initialized = False

    # ------------------------------------------------------------------
    # Convenience accessors
    # ------------------------------------------------------------------

    @property
    def exporter(self) -> DataExporter:
        """Access the DataExporter instance."""
        if self._exporter is None:
            raise RuntimeError(
                "PortabilityModule not initialized. "
                "Call initialize() first."
            )
        return self._exporter

    @property
    def migration_tool(self) -> MigrationTool:
        """Access the MigrationTool instance."""
        if self._migration_tool is None:
            raise RuntimeError(
                "PortabilityModule not initialized. "
                "Call initialize() first."
            )
        return self._migration_tool

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _list_known_targets() -> List[str]:
        """List known migration target system identifiers."""
        from .migration import KNOWN_TARGETS
        return list(KNOWN_TARGETS.keys())
