"""
Sandbox Neuron Module — Trial environments for agency onboarding.

Provides isolated, time-limited sandbox environments where agencies
can test ANASTASiA for 14 days with simulated flight data before
committing to a paid plan. Includes realistic mock data generation,
usage tracking, and trial lifecycle management.

Components:
    SandboxModule       NeuronModule subclass — wires up all components.
    SandboxEnvironment  Isolated sandbox provisioning and management.
    MockDataProvider    Deterministic mock flight/booking data generation.
    TrialManager        Trial lifecycle: start, monitor, convert, expire.

MYSTES KYRIOS LLC — Confidential.
"""

import logging
import os
from typing import Any, Dict, List

from ..core.events import EventBus
from ..core.registry import NeuronModule
from .environment import SandboxEnvironment
from .mock_data import MockDataProvider
from .trial import TrialManager

logger = logging.getLogger(__name__)

__all__ = [
    "SandboxModule",
    "SandboxEnvironment",
    "MockDataProvider",
    "TrialManager",
]


class SandboxModule(NeuronModule):
    """
    ANASTASiA neuron module for sandbox trial environments.

    Wires together the sandbox environment, mock data provider, and
    trial manager into a single registrable neuron. Has no dependencies
    on other neuron modules.

    Configuration keys (passed via ``config`` in ``initialize``):
        ``sandbox_storage_dir`` (str):
            Directory for persisting sandbox JSON files.
            Defaults to ``"./data/sandboxes"``.

    After initialization, the component instances are available as:
        - ``module.sandbox_env``   — :class:`SandboxEnvironment`
        - ``module.mock_data``     — :class:`MockDataProvider`
        - ``module.trial_manager`` — :class:`TrialManager`

    Usage::

        from anastasia.sandbox import SandboxModule
        module = SandboxModule()
        registry.register(module)
        registry.initialize_all({"sandbox_storage_dir": "/data/sandboxes"})

        trial = module.trial_manager.start_trial("Acme Travel", "a@acme.com")
        flights = module.mock_data.search_flights("JFK", "LHR", "2026-04-15")
    """

    def __init__(self) -> None:
        """Initialize the sandbox module (components are wired in ``initialize``)."""
        self.sandbox_env: SandboxEnvironment = None  # type: ignore[assignment]
        self.mock_data: MockDataProvider = None  # type: ignore[assignment]
        self.trial_manager: TrialManager = None  # type: ignore[assignment]

    @property
    def name(self) -> str:
        """Unique module identifier."""
        return "sandbox"

    @property
    def version(self) -> str:
        """Module version."""
        return "1.0.0"

    @property
    def dependencies(self) -> List[str]:
        """No dependencies on other neuron modules."""
        return []

    def initialize(self, event_bus: EventBus, config: Dict[str, Any]) -> None:
        """
        Initialize all sandbox components.

        Creates the storage directory if it does not exist, then wires
        up the SandboxEnvironment, MockDataProvider, and TrialManager.

        Args:
            event_bus: Shared event bus for inter-neuron communication.
            config: Configuration dict. Recognized keys:
                    - ``sandbox_storage_dir``: Path for sandbox JSON storage.
        """
        storage_dir = config.get("sandbox_storage_dir", "./data/sandboxes")
        os.makedirs(storage_dir, exist_ok=True)

        self.sandbox_env = SandboxEnvironment(
            event_bus=event_bus,
            storage_dir=storage_dir,
        )
        self.mock_data = MockDataProvider()
        self.trial_manager = TrialManager(
            event_bus=event_bus,
            sandbox_env=self.sandbox_env,
        )

        logger.info(
            "Sandbox neuron initialized (storage=%s)", storage_dir
        )

    def health_check(self) -> Dict[str, Any]:
        """
        Return the health status of the sandbox module.

        Checks that all components are instantiated and reports
        the count of active sandboxes and trials.

        Returns:
            A dict with ``healthy`` (bool), ``details`` (str), and
            component-level status information.
        """
        components_ok = all([
            self.sandbox_env is not None,
            self.mock_data is not None,
            self.trial_manager is not None,
        ])

        if not components_ok:
            return {
                "healthy": False,
                "details": "One or more sandbox components not initialized",
            }

        sandboxes = self.sandbox_env.list_sandboxes()
        active_count = sum(1 for s in sandboxes if s.get("active"))
        analytics = self.trial_manager.get_trial_analytics()

        return {
            "healthy": True,
            "details": "Sandbox neuron operational",
            "total_sandboxes": len(sandboxes),
            "active_sandboxes": active_count,
            "total_trials": analytics.get("total_trials", 0),
            "active_trials": analytics.get("active_trials", 0),
            "conversion_rate": analytics.get("conversion_rate", 0.0),
        }

    def shutdown(self) -> None:
        """
        Clean up sandbox module resources.

        Runs a final expired-trial check before shutting down.
        """
        if self.trial_manager:
            expired = self.trial_manager.check_expired_trials()
            if expired:
                logger.info(
                    "Expired %d trials during shutdown", len(expired)
                )

        logger.info("Sandbox neuron shut down")
