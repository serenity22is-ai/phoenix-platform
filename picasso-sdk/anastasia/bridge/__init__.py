"""
ANASTASiA Bridge — Confidential Collaborative Development Protocol.

The Bridge neuron enables bilateral IP-protected co-development between
proprietary codebases. ANASTASiA sits between entities as the trusted
intermediary, understanding both sides' architecture and generating
integration proposals — without either side seeing the other's code.

Components:
- **Extractor**: Extracts structural knowledge (API patterns, schemas,
  auth flows) from codebases. Never extracts source code or business logic.
- **Firewall**: Gates ALL information crossing the bridge. Classifies
  content, blocks proprietary data, redacts credentials, full audit trail.
- **Contracts**: Permission framework between entities. Both sides must
  accept before the bridge activates. Neither overrides the other.
- **Registry**: Tracks all bridges, their states, knowledge stores, and
  firewall instances.
- **Orchestrator**: The brain. Analyzes structural knowledge from both
  sides and generates entity-scoped integration proposals.
- **Protocol**: Top-level coordinator managing the full bridge lifecycle.

Security guarantees:
1. NO source code crosses the bridge — only structural patterns
2. NO credentials, PII, or business logic crosses
3. EVERY byte is classified, gated, and audit-logged
4. Each entity controls their own firewall policies
5. Admin approval gates on BOTH sides — no autonomous changes
6. IP ownership: bilateral by default (each side owns their own)

Network effect:
    N daemons = N*(N-1)/2 possible bridges
    10 daemons = 45 bridges | 100 daemons = 4,950 bridges

MYSTES KYRIOS LLC — Confidential.
"""

import logging
import time
from typing import Any, Dict, List

from ..core.events import Event, EventBus, EventType
from ..core.registry import NeuronModule

from .contracts import ContractManager
from .extractor import StructuralKnowledgeExtractor
from .firewall import IPFirewall
from .orchestrator import BridgeOrchestrator
from .protocol import BridgeProtocol
from .registry import BridgeInstance, BridgeRegistry

logger = logging.getLogger(__name__)

__all__ = [
    "BridgeModule",
    "BridgeProtocol",
    "BridgeRegistry",
    "BridgeOrchestrator",
    "BridgeInstance",
    "IPFirewall",
    "StructuralKnowledgeExtractor",
    "ContractManager",
]


class BridgeModule(NeuronModule):
    """
    Bridge neuron module — the Confidential Collaborative Development Protocol.

    Orchestrates bilateral IP-protected co-development between proprietary
    codebases via the daemon bridge. Integrates with the ANASTASiA neuron
    network via EventBus.

    Dependencies:
        - knowledge: Uses system profiles for integration analysis.
        - daemon: Uses daemon connections for knowledge extraction.
    """

    @property
    def name(self) -> str:
        return "bridge"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def dependencies(self) -> List[str]:
        return ["knowledge", "daemon"]

    def __init__(self) -> None:
        self._event_bus: EventBus = None  # type: ignore[assignment]
        self._config: Dict[str, Any] = {}
        self._protocol: BridgeProtocol = None  # type: ignore[assignment]
        self._initialized: bool = False
        self._start_time: float = 0.0

    def initialize(self, event_bus: EventBus, config: Dict[str, Any]) -> None:
        """
        Initialize the bridge module.

        Sets up the BridgeProtocol (which creates the registry,
        orchestrator, and extractor) and subscribes to daemon events.
        """
        self._event_bus = event_bus
        self._config = config
        self._start_time = time.time()

        # Initialize the bridge protocol
        bridge_config = {}
        for key, val in config.items():
            if key.startswith("bridge."):
                bridge_config[key[7:]] = val

        self._protocol = BridgeProtocol(
            event_bus=event_bus,
            config=bridge_config,
        )

        # Subscribe to daemon events — when a daemon connects,
        # check if it has pending bridge contracts
        event_bus.subscribe(
            EventType.DAEMON_CONNECTED, self._handle_daemon_connected
        )
        event_bus.subscribe(
            EventType.SYSTEM_DISCOVERED, self._handle_system_discovered
        )

        self._initialized = True
        logger.info("BridgeModule initialized — Collaborative Development Protocol ready")

    def health_check(self) -> Dict[str, Any]:
        """Return bridge neuron health status."""
        if not self._initialized:
            return {"healthy": False, "details": "Not initialized"}

        protocol_health = self._protocol.health()

        return {
            "healthy": True,
            "details": "Bridge protocol operational",
            "uptime_seconds": int(time.time() - self._start_time),
            "protocol_version": protocol_health["protocol_version"],
            "active_bridges": protocol_health["active_bridges"],
            "total_bridges": protocol_health["total_bridges"],
            "connected_daemons": protocol_health["connected_daemons"],
            "total_proposals": protocol_health["total_proposals"],
            "possible_cross_bridges": protocol_health["possible_cross_bridges"],
        }

    def shutdown(self) -> None:
        """Graceful shutdown of the bridge module."""
        logger.info("Shutting down BridgeModule...")

        # Terminate all active bridges gracefully
        for bridge in self._protocol.registry.list_bridges():
            if bridge.is_active:
                try:
                    self._protocol.pause_bridge(
                        bridge.bridge_id,
                        reason="Platform shutdown",
                    )
                except Exception as e:
                    logger.error(
                        "Failed to pause bridge %s: %s", bridge.bridge_id, e
                    )

        self._initialized = False
        logger.info("BridgeModule shutdown complete")

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _handle_daemon_connected(self, event: Event) -> None:
        """When a daemon connects, register it with the bridge protocol."""
        daemon_id = event.data.get("daemon_id", "")
        if not daemon_id:
            return

        # Register daemon for bridge protocol
        self._protocol.register_daemon(
            daemon_id=daemon_id,
            entity_id=daemon_id,  # In simple case, daemon_id == entity_id
            metadata=event.data,
        )

    def _handle_system_discovered(self, event: Event) -> None:
        """When a system is discovered, check for active bridges that need syncing."""
        daemon_id = event.data.get("daemon_id", "")
        tech_stack = event.data.get("tech_stack", {})

        if not daemon_id or not tech_stack:
            return

        # Check if this daemon has any active bridges
        bridges = self._protocol.registry.list_bridges(entity_id=daemon_id)
        active_bridges = [b for b in bridges if b.is_active]

        if active_bridges:
            logger.info(
                "System discovered for daemon %s — %d active bridges may need syncing",
                daemon_id[:8], len(active_bridges),
            )

    # ------------------------------------------------------------------
    # Public accessors
    # ------------------------------------------------------------------

    @property
    def protocol(self) -> BridgeProtocol:
        """Access the bridge protocol."""
        return self._protocol

    @property
    def registry(self) -> BridgeRegistry:
        """Access the bridge registry."""
        return self._protocol.registry

    @property
    def orchestrator(self) -> BridgeOrchestrator:
        """Access the bridge orchestrator."""
        return self._protocol.orchestrator
