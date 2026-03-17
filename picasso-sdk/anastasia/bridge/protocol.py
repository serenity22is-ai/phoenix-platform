"""
Bilateral Bridge Protocol — Communication layer for the daemon bridge.

Manages the lifecycle of a bridge connection between two daemons through
the ANASTASiA Cloud. This is the transport layer — it handles:

1. Bridge establishment (handshake between both daemons via cloud)
2. Knowledge synchronization (structural knowledge flows through firewalls)
3. Proposal delivery (bridge proposals dispatched to correct entity)
4. Heartbeat and health monitoring (both sides stay connected)
5. Graceful shutdown and cleanup

Communication flow:
    Daemon A → Cloud → (Firewall A) → Bridge Orchestrator → (Firewall B) → Cloud → Daemon B
                                              ↓
                                    Proposals for A ← → Proposals for B

Neither daemon ever communicates directly with the other.
The cloud is the intermediary. The firewalls gate all traffic.

MYSTES KYRIOS LLC — Confidential.
"""

import hashlib
import hmac
import logging
import time
from typing import Any, Callable, Dict, List, Optional

from ..core.events import Event, EventBus, EventType
from ..core.types import BridgeState

from .registry import BridgeInstance, BridgeRegistry
from .orchestrator import BridgeOrchestrator

logger = logging.getLogger(__name__)


class BridgeProtocol:
    """
    Bilateral Bridge Protocol — orchestrates the full bridge lifecycle.

    This is the top-level coordinator. It uses:
    - BridgeRegistry for bridge CRUD and knowledge storage
    - BridgeOrchestrator for integration analysis and proposal generation
    - Firewalls (via registry) for all content gating
    - EventBus for inter-neuron communication
    """

    def __init__(
        self,
        event_bus: Optional[EventBus] = None,
        config: Optional[Dict[str, Any]] = None,
    ):
        self._event_bus = event_bus
        self._config = config or {}
        self._registry = BridgeRegistry(event_bus, config)
        self._orchestrator = BridgeOrchestrator(event_bus)

        # Protocol state
        self._connected_daemons: Dict[str, Dict[str, Any]] = {}
        self._protocol_version = "1.0.0"

    # ------------------------------------------------------------------
    # Bridge lifecycle
    # ------------------------------------------------------------------

    def create_bridge(
        self,
        entity_a_id: str,
        entity_b_id: str,
        entity_a_name: str = "",
        entity_b_name: str = "",
        entity_a_shares: Optional[List[str]] = None,
        entity_b_shares: Optional[List[str]] = None,
        ip_ownership: str = "bilateral",
    ) -> Dict[str, Any]:
        """
        Create a new bridge between two entities.

        Returns bridge details. Both entities must accept before it activates.
        """
        bridge = self._registry.create_bridge(
            entity_a_id=entity_a_id,
            entity_b_id=entity_b_id,
            entity_a_name=entity_a_name,
            entity_b_name=entity_b_name,
            entity_a_shares=entity_a_shares,
            entity_b_shares=entity_b_shares,
            ip_ownership=ip_ownership,
        )

        return {
            "bridge_id": bridge.bridge_id,
            "state": bridge.contract.state,
            "entity_a": entity_a_id,
            "entity_b": entity_b_id,
            "requires_acceptance_from": [entity_a_id, entity_b_id],
        }

    def accept_bridge(
        self,
        bridge_id: str,
        entity_id: str,
    ) -> Dict[str, Any]:
        """Accept a bridge from one entity's side."""
        bridge = self._registry.accept_bridge(bridge_id, entity_id)

        return {
            "bridge_id": bridge_id,
            "state": bridge.contract.state,
            "entity_a_accepted": bridge.contract.entity_a_accepted,
            "entity_b_accepted": bridge.contract.entity_b_accepted,
            "active": bridge.is_active,
        }

    def sync_knowledge(
        self,
        bridge_id: str,
        entity_id: str,
        routes: Optional[List[Dict[str, Any]]] = None,
        models: Optional[List[Dict[str, Any]]] = None,
        auth_config: Optional[Dict[str, Any]] = None,
        codebase_info: Optional[Dict[str, Any]] = None,
        tech_stack: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Sync structural knowledge from one entity to the bridge.

        Knowledge passes through the entity's firewall before being stored.
        The partner never sees raw knowledge — only the orchestrator uses it.
        """
        return self._registry.sync_knowledge(
            bridge_id=bridge_id,
            entity_id=entity_id,
            routes=routes,
            models=models,
            auth_config=auth_config,
            codebase_info=codebase_info,
            tech_stack=tech_stack,
        )

    def analyze_and_propose(
        self,
        bridge_id: str,
    ) -> Dict[str, Any]:
        """
        Analyze both sides of a bridge and generate proposals.

        Requires both sides to have synced their structural knowledge.
        Generates proposals for BOTH sides independently.

        Returns:
            Dict with proposals_for_a, proposals_for_b, and opportunities.
        """
        bridge = self._registry.get_bridge(bridge_id)
        if not bridge:
            raise ValueError(f"Bridge not found: {bridge_id}")

        if not bridge.is_active:
            raise ValueError(f"Bridge {bridge_id} is not active")

        if not bridge.knowledge_a or not bridge.knowledge_b:
            missing = []
            if not bridge.knowledge_a:
                missing.append(bridge.contract.entity_a_id)
            if not bridge.knowledge_b:
                missing.append(bridge.contract.entity_b_id)
            raise ValueError(
                f"Knowledge not synced from: {', '.join(missing)}"
            )

        # Analyze integration opportunities
        opportunities = self._orchestrator.analyze_integration_opportunities(
            bridge_id, bridge.knowledge_a, bridge.knowledge_b
        )

        # Generate proposals for entity A
        proposals_a = self._orchestrator.generate_proposals(
            bridge_id=bridge_id,
            target_entity_id=bridge.contract.entity_a_id,
            knowledge_a=bridge.knowledge_a,
            knowledge_b=bridge.knowledge_b,
            opportunities=opportunities,
        )

        # Generate proposals for entity B
        proposals_b = self._orchestrator.generate_proposals(
            bridge_id=bridge_id,
            target_entity_id=bridge.contract.entity_b_id,
            knowledge_a=bridge.knowledge_a,
            knowledge_b=bridge.knowledge_b,
            opportunities=opportunities,
        )

        # Store on bridge instance
        bridge.proposals_for_a = [p.to_dict() for p in proposals_a]
        bridge.proposals_for_b = [p.to_dict() for p in proposals_b]
        bridge.last_proposal_at = time.time()

        return {
            "bridge_id": bridge_id,
            "opportunities_found": len(opportunities),
            "opportunities": opportunities,
            "proposals_for_a": len(proposals_a),
            "proposals_for_b": len(proposals_b),
        }

    def get_proposals_for_entity(
        self,
        bridge_id: str,
        entity_id: str,
    ) -> List[Dict[str, Any]]:
        """
        Get proposals for a specific entity.

        Entity-scoped: entity A can ONLY see proposals targeting entity A.
        Entity B can ONLY see proposals targeting entity B.
        """
        proposals = self._orchestrator.get_proposals(
            bridge_id, target_entity_id=entity_id
        )
        return [p.to_dict() for p in proposals]

    def approve_proposal(
        self,
        proposal_id: str,
        approved_by: str,
    ) -> Dict[str, Any]:
        """Approve a proposal (entity-scoped)."""
        proposal = self._orchestrator.approve_proposal(proposal_id, approved_by)
        if not proposal:
            raise ValueError(f"Proposal not found: {proposal_id}")
        return proposal.to_dict()

    def reject_proposal(
        self,
        proposal_id: str,
        reason: str = "",
    ) -> Dict[str, Any]:
        """Reject a proposal."""
        proposal = self._orchestrator.reject_proposal(proposal_id, reason)
        if not proposal:
            raise ValueError(f"Proposal not found: {proposal_id}")
        return proposal.to_dict()

    # ------------------------------------------------------------------
    # Bridge management
    # ------------------------------------------------------------------

    def pause_bridge(self, bridge_id: str, reason: str = "") -> Dict[str, Any]:
        """Pause a bridge."""
        bridge = self._registry.pause_bridge(bridge_id, reason)
        return {"bridge_id": bridge_id, "state": bridge.contract.state}

    def resume_bridge(self, bridge_id: str) -> Dict[str, Any]:
        """Resume a paused bridge."""
        bridge = self._registry.resume_bridge(bridge_id)
        return {"bridge_id": bridge_id, "state": bridge.contract.state}

    def terminate_bridge(self, bridge_id: str, reason: str = "") -> Dict[str, Any]:
        """Terminate a bridge permanently."""
        bridge = self._registry.terminate_bridge(bridge_id, reason)
        return {"bridge_id": bridge_id, "state": bridge.contract.state}

    def get_bridge_status(self, bridge_id: str) -> Dict[str, Any]:
        """Get detailed bridge status."""
        bridge = self._registry.get_bridge(bridge_id)
        if not bridge:
            raise ValueError(f"Bridge not found: {bridge_id}")
        return bridge.to_dict()

    def list_bridges(
        self,
        entity_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List all bridges, optionally filtered by entity."""
        bridges = self._registry.list_bridges(entity_id=entity_id)
        return [b.to_dict() for b in bridges]

    def get_partners(self, entity_id: str) -> List[Dict[str, str]]:
        """Get all active bridge partners for an entity."""
        return self._registry.get_partners(entity_id)

    def get_firewall_audit(
        self,
        bridge_id: str,
        entity_id: str,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Get firewall audit log for one side of a bridge."""
        bridge = self._registry.get_bridge(bridge_id)
        if not bridge:
            raise ValueError(f"Bridge not found: {bridge_id}")

        if entity_id == bridge.contract.entity_a_id:
            return bridge.firewall_a.get_audit_log(limit=limit)
        elif entity_id == bridge.contract.entity_b_id:
            return bridge.firewall_b.get_audit_log(limit=limit)
        else:
            raise ValueError(f"Entity {entity_id} not part of bridge {bridge_id}")

    # ------------------------------------------------------------------
    # Daemon connection tracking
    # ------------------------------------------------------------------

    def register_daemon(
        self,
        daemon_id: str,
        entity_id: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Register a daemon as connected to the protocol."""
        self._connected_daemons[daemon_id] = {
            "entity_id": entity_id,
            "connected_at": time.time(),
            "last_heartbeat": time.time(),
            "metadata": metadata or {},
        }
        logger.info("Daemon %s registered for entity %s", daemon_id, entity_id[:8])

    def daemon_heartbeat(self, daemon_id: str) -> bool:
        """Record a daemon heartbeat."""
        if daemon_id not in self._connected_daemons:
            return False
        self._connected_daemons[daemon_id]["last_heartbeat"] = time.time()
        return True

    def unregister_daemon(self, daemon_id: str) -> None:
        """Unregister a daemon."""
        self._connected_daemons.pop(daemon_id, None)
        logger.info("Daemon %s unregistered", daemon_id)

    # ------------------------------------------------------------------
    # Health and stats
    # ------------------------------------------------------------------

    def health(self) -> Dict[str, Any]:
        """Protocol-level health and statistics."""
        registry_health = self._registry.health()
        return {
            "protocol_version": self._protocol_version,
            "connected_daemons": len(self._connected_daemons),
            "total_bridges": registry_health["total_bridges"],
            "active_bridges": registry_health["active_bridges"],
            "fully_synced": registry_health["fully_synced"],
            "possible_cross_bridges": registry_health["possible_cross_bridges"],
            "total_proposals": self._orchestrator.total_proposals,
        }

    @property
    def registry(self) -> BridgeRegistry:
        """Access the bridge registry."""
        return self._registry

    @property
    def orchestrator(self) -> BridgeOrchestrator:
        """Access the bridge orchestrator."""
        return self._orchestrator
