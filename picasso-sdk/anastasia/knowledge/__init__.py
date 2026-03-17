"""
Knowledge Neuron — System profile storage, learning pipeline, catalog,
API watchdog, and autonomous update pipeline.

This neuron is ANASTASiA's core intellectual property layer. It manages:

- **ProfileStore**: Persistent CRUD for SystemProfile objects (JSON on disk).
  Seeded with the Redbox (AERTiCKET/Picasso Travel) profile since that
  system is already reverse-engineered and in production.

- **LearningPipeline**: Extracts tech stacks, API patterns, booking flows,
  and system quirks from customer installations. Each integration makes
  ANASTASiA smarter.

- **KnowledgeCatalog**: Marketplace view of all known systems with readiness
  badges, compatibility checks, and tech-stack-aware suggestions.

- **AutoLearner**: Autonomous API reverse-engineering engine powered by
  Claude Opus 4.6. When the daemon encounters an unknown API, the
  AutoLearner orchestrates: encounter → probe → analyze → profile → retain.
  Redbox was patient zero (manual). Every future API is automatic.

- **APIWatchdog**: Monitors all API providers for drift via 4 signals:
  schema probing, changelog monitoring, error-rate detection, version
  header tracking. Feeds the UpdatePipeline when changes are detected.

- **UpdatePipeline**: 7-stage autonomous update lifecycle:
  detect → analyze → generate → test → deploy → verify → monitor.
  Uses Claude Opus 4.6 to generate updated code and knowledge cards.
  Fully autonomous — tests validate, if tests pass it ships.

- **KnowledgeModule**: NeuronModule subclass that wires everything together
  and registers with the ModuleRegistry.

MYSTES KYRIOS LLC — Confidential.
"""

import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ..core.events import EventBus
from ..core.registry import NeuronModule

from .profiles import ProfileStore
from .learning import LearningPipeline
from .catalog import KnowledgeCatalog
from .auto_learner import AutoLearner
from .watchdog import APIWatchdog
from .update_pipeline import UpdatePipeline

logger = logging.getLogger(__name__)


class KnowledgeModule(NeuronModule):
    """
    ANASTASiA Knowledge neuron module.

    Manages the lifecycle of ProfileStore, LearningPipeline,
    KnowledgeCatalog, APIWatchdog, and UpdatePipeline. Registered
    with the ModuleRegistry and initialized during platform startup.

    Has no dependencies on other neuron modules -- it is a foundational
    layer that other neurons (payments, daemon, integration) depend on.

    Usage::

        from anastasia.core import ModuleRegistry, EventBus
        from anastasia.knowledge import KnowledgeModule

        bus = EventBus()
        registry = ModuleRegistry(bus)
        registry.register(KnowledgeModule())
        registry.initialize_all(config={"profiles_dir": "/data/profiles"})
    """

    def __init__(self):
        self._profile_store: ProfileStore | None = None
        self._learning_pipeline: LearningPipeline | None = None
        self._catalog: KnowledgeCatalog | None = None
        self._auto_learner: AutoLearner | None = None
        self._watchdog: APIWatchdog | None = None
        self._update_pipeline: UpdatePipeline | None = None
        self._event_bus: EventBus | None = None
        self._ai_analyze: Optional[Callable[[str], str]] = None
        self._initialized = False

    # ------------------------------------------------------------------
    # NeuronModule interface
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        """Unique module identifier."""
        return "knowledge"

    @property
    def version(self) -> str:
        """Module version."""
        return "1.0.0"

    @property
    def dependencies(self) -> List[str]:
        """No dependencies -- knowledge is foundational."""
        return []

    def initialize(self, event_bus: EventBus, config: Dict[str, Any]) -> None:
        """
        Initialize all knowledge sub-components.

        Reads the optional ``profiles_dir`` from config to set the
        storage directory for ProfileStore. If not provided, defaults
        to ``~/.anastasia/profiles``.

        Args:
            event_bus: Shared EventBus for inter-module communication.
            config: Platform configuration dict. Recognized keys:
                    - ``profiles_dir`` (str): Path to profile storage directory.
                    - ``watchdog_dir`` (str): Path to watchdog data directory.
                    - ``updates_dir`` (str): Path to update history directory.
                    - ``ai_analyze``: Callable for Claude analysis.
                    - ``http_probe``: Callable for HTTP probing.
                    - ``http_fetch``: Callable for fetching changelogs/docs.
                    - ``ai_generate``: Callable for Claude code generation.
                    - ``run_tests``: Callable for running test suite.
                    - ``git_commit``: Callable for git operations.
        """
        self._event_bus = event_bus
        profiles_dir = config.get("profiles_dir")

        # Stand up the profile store (loads existing profiles from disk)
        self._profile_store = ProfileStore(
            event_bus=event_bus,
            storage_dir=profiles_dir,
        )

        # Stand up the learning pipeline
        self._learning_pipeline = LearningPipeline(event_bus=event_bus)

        # Stand up the catalog (reads from profile store)
        self._catalog = KnowledgeCatalog(
            event_bus=event_bus,
            profile_store=self._profile_store,
        )

        # Stand up the auto-learner (Claude Opus 4.6 powered)
        self._ai_analyze = config.get("ai_analyze")
        self._auto_learner = AutoLearner(
            event_bus=event_bus,
            profile_store=self._profile_store,
            ai_analyze=self._ai_analyze,
            http_probe=config.get("http_probe"),
        )

        # Stand up the API Watchdog (drift detection)
        self._watchdog = APIWatchdog(
            event_bus=event_bus,
            storage_dir=config.get("watchdog_dir"),
            ai_analyze=self._ai_analyze,
            http_probe=config.get("http_probe"),
            http_fetch=config.get("http_fetch"),
        )

        # Auto-register providers from JSON knowledge cards
        cards_dir = Path(__file__).parent.parent / "modules" / "cards"
        if cards_dir.exists():
            registered = 0
            for card_path in sorted(cards_dir.glob("*.json")):
                if self._watchdog.register_from_card_json(card_path):
                    registered += 1
            logger.info("Watchdog: %d providers registered from cards", registered)

        # Stand up the Update Pipeline (autonomous maintenance)
        self._update_pipeline = UpdatePipeline(
            event_bus=event_bus,
            watchdog=self._watchdog,
            storage_dir=config.get("updates_dir"),
            ai_generate=config.get("ai_generate"),
            run_tests=config.get("run_tests"),
            file_reader=config.get("file_reader"),
            file_writer=config.get("file_writer"),
            git_commit=config.get("git_commit"),
        )

        self._initialized = True
        logger.info(
            "Knowledge neuron initialized: %d profiles, "
            "auto-learner=%s, watchdog=%d providers, update-pipeline=active",
            self._profile_store.count,
            "Claude" if self._ai_analyze else "rule-based",
            len(self._watchdog._providers),
        )

    def health_check(self) -> Dict[str, Any]:
        """
        Return health status of the knowledge neuron.

        Reports profile count, auto-learner status, watchdog status,
        update pipeline status, and whether the Redbox seed profile
        is present.
        """
        if not self._initialized or self._profile_store is None:
            return {
                "healthy": False,
                "details": "Knowledge module not initialized",
            }

        redbox = self._profile_store.get_by_name("Redbox")
        return {
            "healthy": True,
            "details": "Knowledge neuron operational",
            "profiles_count": self._profile_store.count,
            "storage_dir": str(self._profile_store._storage_dir),
            "redbox_seeded": redbox is not None,
            "redbox_readiness": redbox.readiness if redbox else None,
            "auto_learner": "claude" if self._ai_analyze else "rule-based",
            "pending_discoveries": len(
                self._auto_learner.pending_discoveries
            ) if self._auto_learner else 0,
            "watchdog": self._watchdog.get_status() if self._watchdog else None,
            "update_pipeline": self._update_pipeline.get_status() if self._update_pipeline else None,
        }

    def shutdown(self) -> None:
        """Cleanup on platform shutdown."""
        self._initialized = False
        logger.info("Knowledge neuron shut down")

    # ------------------------------------------------------------------
    # Public accessors
    # ------------------------------------------------------------------

    @property
    def profile_store(self) -> ProfileStore:
        """Access the ProfileStore instance.

        Raises:
            RuntimeError: If the module has not been initialized.
        """
        if self._profile_store is None:
            raise RuntimeError(
                "KnowledgeModule not initialized. "
                "Call initialize() first or register with ModuleRegistry."
            )
        return self._profile_store

    @property
    def learning_pipeline(self) -> LearningPipeline:
        """Access the LearningPipeline instance.

        Raises:
            RuntimeError: If the module has not been initialized.
        """
        if self._learning_pipeline is None:
            raise RuntimeError(
                "KnowledgeModule not initialized. "
                "Call initialize() first or register with ModuleRegistry."
            )
        return self._learning_pipeline

    @property
    def catalog(self) -> KnowledgeCatalog:
        """Access the KnowledgeCatalog instance.

        Raises:
            RuntimeError: If the module has not been initialized.
        """
        if self._catalog is None:
            raise RuntimeError(
                "KnowledgeModule not initialized. "
                "Call initialize() first or register with ModuleRegistry."
            )
        return self._catalog

    @property
    def auto_learner(self) -> AutoLearner:
        """Access the AutoLearner instance (Claude Opus 4.6 powered).

        Raises:
            RuntimeError: If the module has not been initialized.
        """
        if self._auto_learner is None:
            raise RuntimeError(
                "KnowledgeModule not initialized. "
                "Call initialize() first or register with ModuleRegistry."
            )
        return self._auto_learner

    @property
    def watchdog(self) -> APIWatchdog:
        """Access the APIWatchdog instance (drift detection).

        Raises:
            RuntimeError: If the module has not been initialized.
        """
        if self._watchdog is None:
            raise RuntimeError(
                "KnowledgeModule not initialized. "
                "Call initialize() first or register with ModuleRegistry."
            )
        return self._watchdog

    @property
    def update_pipeline(self) -> UpdatePipeline:
        """Access the UpdatePipeline instance (autonomous maintenance).

        Raises:
            RuntimeError: If the module has not been initialized.
        """
        if self._update_pipeline is None:
            raise RuntimeError(
                "KnowledgeModule not initialized. "
                "Call initialize() first or register with ModuleRegistry."
            )
        return self._update_pipeline


__all__ = [
    "KnowledgeModule",
    "ProfileStore",
    "LearningPipeline",
    "KnowledgeCatalog",
    "AutoLearner",
    "APIWatchdog",
    "UpdatePipeline",
]
