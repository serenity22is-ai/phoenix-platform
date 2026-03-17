"""
Credential Network Neuron — Federated credential sharing, encrypted vault,
booking routing, and revenue settlement.

This neuron implements the "Mother of All Consolidators" — a decentralized
network where B2B customers share API credentials for mutual revenue share.
ANASTASiA routes bookings to the optimal credential holder based on price,
availability, and coverage.

Components:
- **CredentialVault**: Encrypted storage for API credentials (Fernet symmetric).
  Credentials are service-bound to daemon instances and access-controlled.
- **CredentialNetwork**: Federated membership, discovery, and booking routing.
  Connects competing consolidators as partners through the daemon bridge.
- **RevenueCalculator**: Split calculations and settlement tracking.
  Default: 85% credential host, 10% platform, 5% routing agency.

MYSTES KYRIOS LLC — Confidential.
"""

import logging
from typing import Any, Dict, List, Optional

from ..core.events import EventBus, Event, EventType
from ..core.registry import NeuronModule

from .vault import CredentialVault
from .network import (
    CredentialNetwork,
    RoutingStrategy,
    RoutingTier,
    get_tier_revenue_split,
)
from .revenue import RevenueCalculator

logger = logging.getLogger(__name__)


class CredentialModule(NeuronModule):
    """
    ANASTASiA Credential Network neuron module.

    Orchestrates the vault, network, and revenue calculator. Registered
    with the ModuleRegistry and initialized during platform startup.

    Dependencies: None (standalone — other neurons reference it via EventBus).

    Usage::

        from anastasia.core import ModuleRegistry, EventBus
        from anastasia.credentials import CredentialModule

        bus = EventBus()
        registry = ModuleRegistry(bus)
        registry.register(CredentialModule())
        registry.initialize_all(config={"credentials_dir": "/data/creds"})
    """

    def __init__(self):
        self._vault: Optional[CredentialVault] = None
        self._network: Optional[CredentialNetwork] = None
        self._revenue: Optional[RevenueCalculator] = None
        self._event_bus: Optional[EventBus] = None
        self._initialized = False

    # ------------------------------------------------------------------
    # NeuronModule interface
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return "credentials"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def dependencies(self) -> List[str]:
        return []

    def initialize(self, event_bus: EventBus, config: Dict[str, Any]) -> None:
        """
        Initialize all credential sub-components.

        Config keys:
            - credentials_dir (str): Path to credential storage.
            - credentials_master_key (str): Master encryption key.
            - network_dir (str): Path to network data.
            - revenue_dir (str): Path to revenue records.
        """
        self._event_bus = event_bus

        # Stand up the vault (encrypted credential storage)
        self._vault = CredentialVault(
            event_bus=event_bus,
            storage_dir=config.get("credentials_dir"),
            master_key=config.get("credentials_master_key"),
        )

        # Stand up the network (federated sharing + routing)
        self._network = CredentialNetwork(
            event_bus=event_bus,
            vault=self._vault,
            storage_dir=config.get("network_dir"),
        )

        # Stand up the revenue calculator
        self._revenue = RevenueCalculator(
            storage_dir=config.get("revenue_dir"),
        )

        # Subscribe to booking events for revenue tracking
        event_bus.subscribe(EventType.BOOKING_CONFIRMED, self._on_booking_confirmed)

        self._initialized = True
        logger.info(
            "Credential neuron initialized: %d credentials, %d network members, "
            "%d revenue records",
            self._vault.count,
            self._network.member_count,
            self._revenue.record_count,
        )

    def health_check(self) -> Dict[str, Any]:
        """Return health status of the credential neuron."""
        if not self._initialized:
            return {
                "healthy": False,
                "details": "Credential module not initialized",
            }

        return {
            "healthy": True,
            "details": "Credential neuron operational",
            "vault": {
                "credentials_count": self._vault.count,
                "stats": self._vault.get_stats(),
            },
            "network": {
                "member_count": self._network.member_count,
                "stats": self._network.get_network_stats(),
            },
            "revenue": {
                "record_count": self._revenue.record_count,
                "stats": self._revenue.get_stats(),
            },
        }

    def shutdown(self) -> None:
        """Cleanup on platform shutdown."""
        self._initialized = False
        logger.info("Credential neuron shut down")

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_booking_confirmed(self, event: Event) -> None:
        """Track revenue when a routed booking confirms."""
        data = event.data
        route_result_id = data.get("route_result_id")
        if not route_result_id:
            return  # Not a routed booking

        self._revenue.record_revenue(
            route_result_id=route_result_id,
            credential_id=data.get("credential_id", ""),
            owner_tenant_id=data.get("owner_tenant_id", ""),
            router_tenant_id=data.get("router_tenant_id", ""),
            provider_id=data.get("provider_id", ""),
            transaction_amount=data.get("transaction_amount", 0.0),
            custom_split=data.get("revenue_split"),
        )

    # ------------------------------------------------------------------
    # Public accessors
    # ------------------------------------------------------------------

    @property
    def vault(self) -> CredentialVault:
        """Access the CredentialVault (encrypted storage)."""
        if self._vault is None:
            raise RuntimeError(
                "CredentialModule not initialized. "
                "Call initialize() first or register with ModuleRegistry."
            )
        return self._vault

    @property
    def network(self) -> CredentialNetwork:
        """Access the CredentialNetwork (federated sharing + routing)."""
        if self._network is None:
            raise RuntimeError(
                "CredentialModule not initialized. "
                "Call initialize() first or register with ModuleRegistry."
            )
        return self._network

    @property
    def revenue(self) -> RevenueCalculator:
        """Access the RevenueCalculator (split tracking)."""
        if self._revenue is None:
            raise RuntimeError(
                "CredentialModule not initialized. "
                "Call initialize() first or register with ModuleRegistry."
            )
        return self._revenue


__all__ = [
    "CredentialModule",
    "CredentialVault",
    "CredentialNetwork",
    "RevenueCalculator",
    "RoutingStrategy",
    "RoutingTier",
    "get_tier_revenue_split",
]
