"""
Bridge Contracts — Permission and agreement framework between entities.

A bridge contract defines the terms of the bilateral IP bridge:
- What structural knowledge each side agrees to share
- What operations the bridge can perform on each side
- IP ownership terms (bilateral by default — each side owns what's built on their code)
- Audit requirements
- Duration, renewal, and termination terms

Both entities must accept before the bridge activates.
Neither side can override the other's permissions.

MYSTES KYRIOS LLC — Confidential.
"""

import logging
import time
from typing import Any, Dict, List, Optional

from ..core.events import Event, EventBus, EventType
from ..core.types import BridgeContract, BridgeState

logger = logging.getLogger(__name__)


# Default sharing categories
DEFAULT_SHARES = [
    "api_patterns",
    "data_schemas",
    "auth_flows",
    "tech_stack",
    "integration_points",
]

# Default allowed actions
DEFAULT_ACTIONS = [
    "propose_file_create",
    "propose_file_modify",
    "propose_config_change",
]


class ContractManager:
    """
    Manages the lifecycle of bridge contracts.

    Contracts follow a strict lifecycle:
    1. PENDING — One entity proposes the bridge
    2. NEGOTIATING — Other entity reviews terms
    3. ACTIVE — Both accepted, bridge is live
    4. PAUSED — Temporarily suspended
    5. TERMINATED — Permanently ended
    """

    def __init__(self, event_bus: Optional[EventBus] = None):
        self._event_bus = event_bus
        self._contracts: Dict[str, BridgeContract] = {}

    def create_contract(
        self,
        entity_a_id: str,
        entity_b_id: str,
        entity_a_name: str = "",
        entity_b_name: str = "",
        entity_a_shares: Optional[List[str]] = None,
        entity_b_shares: Optional[List[str]] = None,
        entity_a_actions: Optional[List[str]] = None,
        entity_b_actions: Optional[List[str]] = None,
        ip_ownership: str = "bilateral",
    ) -> BridgeContract:
        """
        Create a new bridge contract between two entities.

        Args:
            entity_a_id: Unique ID for entity A (daemon ID or org ID).
            entity_b_id: Unique ID for entity B.
            entity_a_name: Human-readable name for entity A.
            entity_b_name: Human-readable name for entity B.
            entity_a_shares: What A agrees to share (defaults to structural knowledge).
            entity_b_shares: What B agrees to share.
            entity_a_actions: What the bridge can do on A's codebase.
            entity_b_actions: What the bridge can do on B's codebase.
            ip_ownership: IP terms — "bilateral" means each side owns their own.

        Returns:
            The created BridgeContract.
        """
        contract = BridgeContract(
            entity_a_id=entity_a_id,
            entity_b_id=entity_b_id,
            entity_a_name=entity_a_name,
            entity_b_name=entity_b_name,
            entity_a_shares=entity_a_shares or DEFAULT_SHARES.copy(),
            entity_b_shares=entity_b_shares or DEFAULT_SHARES.copy(),
            entity_a_allowed_actions=entity_a_actions or DEFAULT_ACTIONS.copy(),
            entity_b_allowed_actions=entity_b_actions or DEFAULT_ACTIONS.copy(),
            ip_ownership=ip_ownership,
            state=BridgeState.PENDING.value,
        )

        self._contracts[contract.id] = contract

        logger.info(
            "Bridge contract created: %s (%s <-> %s)",
            contract.id, entity_a_name or entity_a_id[:8],
            entity_b_name or entity_b_id[:8],
        )

        return contract

    def accept_contract(
        self,
        contract_id: str,
        entity_id: str,
    ) -> BridgeContract:
        """
        Accept a contract from one entity's side.

        When both sides accept, the contract transitions to ACTIVE.

        Args:
            contract_id: The contract to accept.
            entity_id: Which entity is accepting.

        Returns:
            Updated contract.

        Raises:
            ValueError: If contract not found or entity not part of contract.
        """
        contract = self._contracts.get(contract_id)
        if not contract:
            raise ValueError(f"Contract not found: {contract_id}")

        if entity_id == contract.entity_a_id:
            contract.entity_a_accepted = True
        elif entity_id == contract.entity_b_id:
            contract.entity_b_accepted = True
        else:
            raise ValueError(
                f"Entity {entity_id} is not part of contract {contract_id}"
            )

        # Check if both sides have accepted
        if contract.entity_a_accepted and contract.entity_b_accepted:
            contract.state = BridgeState.ACTIVE.value
            contract.activated_at = time.time()
            logger.info("Bridge contract ACTIVATED: %s", contract_id)

            if self._event_bus:
                self._event_bus.publish(Event(
                    type=EventType.BRIDGE_ACTIVATED,
                    source="bridge.contracts",
                    data={
                        "contract_id": contract_id,
                        "entity_a": contract.entity_a_id,
                        "entity_b": contract.entity_b_id,
                    },
                ))
        else:
            contract.state = BridgeState.NEGOTIATING.value
            logger.info(
                "Contract %s: %s accepted, waiting for other party",
                contract_id, entity_id[:8],
            )

        return contract

    def pause_contract(
        self,
        contract_id: str,
        reason: str = "",
    ) -> BridgeContract:
        """Temporarily pause a bridge contract."""
        contract = self._contracts.get(contract_id)
        if not contract:
            raise ValueError(f"Contract not found: {contract_id}")

        contract.state = BridgeState.PAUSED.value
        logger.info("Bridge contract PAUSED: %s (%s)", contract_id, reason)

        if self._event_bus:
            self._event_bus.publish(Event(
                type=EventType.BRIDGE_PAUSED,
                source="bridge.contracts",
                data={"contract_id": contract_id, "reason": reason},
            ))

        return contract

    def resume_contract(self, contract_id: str) -> BridgeContract:
        """Resume a paused contract."""
        contract = self._contracts.get(contract_id)
        if not contract:
            raise ValueError(f"Contract not found: {contract_id}")

        if contract.state != BridgeState.PAUSED.value:
            raise ValueError(f"Contract {contract_id} is not paused")

        contract.state = BridgeState.ACTIVE.value
        logger.info("Bridge contract RESUMED: %s", contract_id)

        if self._event_bus:
            self._event_bus.publish(Event(
                type=EventType.BRIDGE_ACTIVATED,
                source="bridge.contracts",
                data={"contract_id": contract_id, "resumed": True},
            ))

        return contract

    def terminate_contract(
        self,
        contract_id: str,
        reason: str = "",
    ) -> BridgeContract:
        """Permanently terminate a bridge contract."""
        contract = self._contracts.get(contract_id)
        if not contract:
            raise ValueError(f"Contract not found: {contract_id}")

        contract.state = BridgeState.TERMINATED.value
        contract.terminated_at = time.time()
        contract.termination_reason = reason

        logger.info(
            "Bridge contract TERMINATED: %s (%s)", contract_id, reason
        )

        if self._event_bus:
            self._event_bus.publish(Event(
                type=EventType.BRIDGE_TERMINATED,
                source="bridge.contracts",
                data={"contract_id": contract_id, "reason": reason},
            ))

        return contract

    def get_contract(self, contract_id: str) -> Optional[BridgeContract]:
        """Get a contract by ID."""
        return self._contracts.get(contract_id)

    def list_contracts(
        self,
        entity_id: Optional[str] = None,
        state: Optional[str] = None,
    ) -> List[BridgeContract]:
        """List contracts, optionally filtered by entity or state."""
        contracts = list(self._contracts.values())

        if entity_id:
            contracts = [
                c for c in contracts
                if c.entity_a_id == entity_id or c.entity_b_id == entity_id
            ]

        if state:
            contracts = [c for c in contracts if c.state == state]

        return contracts

    def get_partners(self, entity_id: str) -> List[str]:
        """Get all entity IDs that have active bridges with the given entity."""
        partners = []
        for contract in self._contracts.values():
            if contract.state != BridgeState.ACTIVE.value:
                continue
            if contract.entity_a_id == entity_id:
                partners.append(contract.entity_b_id)
            elif contract.entity_b_id == entity_id:
                partners.append(contract.entity_a_id)
        return partners

    def is_action_allowed(
        self,
        contract_id: str,
        entity_id: str,
        action: str,
    ) -> bool:
        """Check if an action is allowed on a specific entity within a contract."""
        contract = self._contracts.get(contract_id)
        if not contract:
            return False

        if contract.state != BridgeState.ACTIVE.value:
            return False

        if entity_id == contract.entity_a_id:
            return action in contract.entity_a_allowed_actions
        elif entity_id == contract.entity_b_id:
            return action in contract.entity_b_allowed_actions

        return False

    def is_share_allowed(
        self,
        contract_id: str,
        entity_id: str,
        category: str,
    ) -> bool:
        """Check if an entity has agreed to share a knowledge category."""
        contract = self._contracts.get(contract_id)
        if not contract:
            return False

        if entity_id == contract.entity_a_id:
            return category in contract.entity_a_shares
        elif entity_id == contract.entity_b_id:
            return category in contract.entity_b_shares

        return False

    @property
    def contract_count(self) -> int:
        """Total number of contracts."""
        return len(self._contracts)

    @property
    def active_count(self) -> int:
        """Number of active bridges."""
        return sum(
            1 for c in self._contracts.values()
            if c.state == BridgeState.ACTIVE.value
        )
