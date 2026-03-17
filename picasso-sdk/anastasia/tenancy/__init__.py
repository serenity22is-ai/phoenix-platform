"""
Tenancy Neuron — Hierarchical multi-tenant management for ANASTASiA.

This module implements the three-level tenant hierarchy:
    Master (MYSTES KYRIOS LLC) -> Consolidator (e.g., AERTiCKET) -> Agency

Each level has different permissions, data isolation boundaries, and
resource limits. The module provides:

    - **TenantHierarchy**: CRUD operations on the tenant tree with
      persistent storage and event-driven lifecycle management.

    - **DataIsolation**: Access control enforcement ensuring tenants
      can only see their own data and their descendants'. Also manages
      per-tenant rate limiting and resource quotas.

    - **TenantProvisioning**: Automated onboarding and offboarding
      workflows including API key generation, plan management, trial
      setup, and bulk provisioning.

    - **TenancyModule**: NeuronModule subclass that wires all three
      components together and registers with the ANASTASiA module
      registry.

MYSTES KYRIOS LLC — Confidential.
"""

import logging
import os
from typing import Any, Dict, List

from ..core.events import EventBus
from ..core.registry import NeuronModule
from .hierarchy import TenantHierarchy
from .isolation import DataIsolation
from .provisioning import TenantProvisioning

logger = logging.getLogger(__name__)

__all__ = [
    "TenancyModule",
    "TenantHierarchy",
    "DataIsolation",
    "TenantProvisioning",
]


class TenancyModule(NeuronModule):
    """
    ANASTASiA neuron module for hierarchical multi-tenancy.

    Manages the full lifecycle of tenants across three tiers:
    Master, Consolidator, and Agency. Wires together the hierarchy,
    data isolation, and provisioning subsystems during initialization.

    This module has no dependencies on other neurons and can be
    initialized first in the startup sequence.

    Attributes:
        hierarchy: TenantHierarchy instance (available after initialize).
        isolation: DataIsolation instance (available after initialize).
        provisioning: TenantProvisioning instance (available after initialize).

    Usage:
        module = TenancyModule()
        registry.register(module)
        # After registry.initialize_all(config):
        module.hierarchy.get_hierarchy_tree()
        module.provisioning.provision_agency(...)
    """

    def __init__(self) -> None:
        """Initialize the tenancy module (components created in initialize)."""
        self.hierarchy: TenantHierarchy = None  # type: ignore[assignment]
        self.isolation: DataIsolation = None  # type: ignore[assignment]
        self.provisioning: TenantProvisioning = None  # type: ignore[assignment]
        self._initialized = False

    @property
    def name(self) -> str:
        """Unique module name for registry identification."""
        return "tenancy"

    @property
    def version(self) -> str:
        """Module version following semantic versioning."""
        return "1.0.0"

    @property
    def dependencies(self) -> List[str]:
        """No dependencies -- tenancy is a foundational module."""
        return []

    def initialize(self, event_bus: EventBus, config: Dict[str, Any]) -> None:
        """
        Initialize all tenancy subsystems.

        Creates the tenant hierarchy (loading persisted state from disk),
        the data isolation layer, and the provisioning engine. The master
        tenant is auto-created if this is a fresh installation.

        Args:
            event_bus: Shared event bus for inter-neuron communication.
            config: Platform configuration dict. Recognized keys:
                - ``tenancy_storage_dir`` (str): Directory for tenant
                  JSON files. Defaults to ``"./data/tenants"``.
                - ``tenancy_usage_dir`` (str): Directory for usage
                  counter files. Defaults to ``"./data/tenancy_usage"``.
        """
        storage_dir = config.get("tenancy_storage_dir", "./data/tenants")
        usage_dir = config.get("tenancy_usage_dir", "./data/tenancy_usage")

        # 1. Hierarchy -- tenant CRUD + persistence
        self.hierarchy = TenantHierarchy(event_bus, storage_dir)

        # 2. Data isolation -- access control + rate limiting
        self.isolation = DataIsolation(self.hierarchy)
        self.isolation.load_from_disk(usage_dir)

        # 3. Provisioning -- automated tenant lifecycle
        self.provisioning = TenantProvisioning(
            event_bus, self.hierarchy, self.isolation,
        )

        self._initialized = True
        logger.info(
            "Tenancy module initialized: %d tenants loaded",
            len(self.hierarchy.get_all_tenants()),
        )

    def health_check(self) -> Dict[str, Any]:
        """
        Return health status for the tenancy module.

        Checks that the hierarchy is loaded and reports tenant counts
        per tier.

        Returns:
            Dictionary with:
                - healthy (bool): Whether the module is operational.
                - details (str): Human-readable status message.
                - tenant_count (int): Total number of tenants.
                - by_tier (dict): Count of tenants per tier.
        """
        if not self._initialized or self.hierarchy is None:
            return {
                "healthy": False,
                "details": "Tenancy module not initialized",
            }

        all_tenants = self.hierarchy.get_all_tenants()
        by_tier: Dict[str, int] = {}
        for tenant in all_tenants:
            by_tier[tenant.tier] = by_tier.get(tenant.tier, 0) + 1

        return {
            "healthy": True,
            "details": f"{len(all_tenants)} tenants loaded",
            "tenant_count": len(all_tenants),
            "by_tier": by_tier,
        }

    def shutdown(self) -> None:
        """
        Graceful shutdown: flush usage counters to disk.

        Persists in-memory usage data so it survives restarts.
        """
        if self._initialized and self.isolation is not None:
            # Determine usage dir from hierarchy storage dir sibling
            storage_dir = self.hierarchy._storage_dir
            usage_dir = os.path.join(
                os.path.dirname(storage_dir), "tenancy_usage",
            )
            self.isolation.flush_to_disk(usage_dir)
            logger.info("Tenancy module shut down, usage data flushed")

        self._initialized = False
