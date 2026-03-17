"""
Tenant Hierarchy — Master -> Consolidator -> Agency multi-tenancy.

Manages the hierarchical relationship between tenant levels in ANASTASiA's
multi-tenant architecture. The master tenant (MYSTES KYRIOS LLC) sits at the
root, consolidators (e.g., AERTiCKET) operate beneath it, and individual
travel agencies operate under their consolidators.

Each tenant has its own configuration, status, and API credentials. The
hierarchy is persisted as JSON files on disk and events are emitted for
all lifecycle transitions.

MYSTES KYRIOS LLC — Confidential.
"""

import hashlib
import json
import logging
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from ..core.events import Event, EventBus, EventType
from ..core.types import TenantTier

logger = logging.getLogger(__name__)

# Master tenant identity
MASTER_TENANT_NAME = "MYSTES KYRIOS LLC"
MASTER_TENANT_ID = "master-mystes-kyrios"


@dataclass
class Tenant:
    """
    A tenant in the ANASTASiA hierarchy.

    Tenants are organized in a tree: Master -> Consolidator -> Agency.
    Each tenant has isolated configuration, resource limits, and API
    credentials. Status changes propagate downward (suspending a
    consolidator suspends all its agencies).

    Attributes:
        id: Unique identifier for the tenant.
        name: Human-readable tenant name.
        tier: Hierarchy level (MASTER, CONSOLIDATOR, AGENCY).
        parent_id: ID of the parent tenant, or None for the master.
        children_ids: List of direct child tenant IDs.
        api_key_hash: SHA-256 hash of the tenant's API key.
        config: Tenant-specific configuration including plan, limits,
                features, and branding.
        status: Current lifecycle status (active, suspended, trial).
        created_at: Unix timestamp of creation.
        metadata: Arbitrary key-value metadata for extensibility.
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    tier: str = "agency"  # TenantTier value string
    parent_id: Optional[str] = None
    children_ids: List[str] = field(default_factory=list)
    api_key_hash: Optional[str] = None
    config: Dict[str, Any] = field(default_factory=lambda: {
        "plan": "pro",
        "limits": {},
        "features": [],
        "branding": {},
    })
    status: str = "active"  # active, suspended, trial
    created_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Serialize tenant to a plain dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "tier": self.tier,
            "parent_id": self.parent_id,
            "children_ids": list(self.children_ids),
            "api_key_hash": self.api_key_hash,
            "config": dict(self.config),
            "status": self.status,
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Tenant":
        """Deserialize a tenant from a plain dictionary."""
        known_fields = {f for f in cls.__dataclass_fields__}
        filtered = {k: v for k, v in data.items() if k in known_fields}
        return cls(**filtered)


class TenantHierarchy:
    """
    Manages the hierarchical tree of tenants.

    The hierarchy is a rooted tree with the master tenant at the root.
    All CRUD operations on tenants go through this class, which handles
    persistence (JSON files on disk) and event publishing.

    Invariants:
        - Exactly one master tenant exists at all times.
        - Consolidators are children of the master.
        - Agencies are children of a consolidator.
        - Suspending a tenant recursively suspends all descendants.
        - Tenant IDs are globally unique.

    Usage:
        hierarchy = TenantHierarchy(event_bus, "/data/tenants")
        consolidator = hierarchy.create_tenant(
            name="AERTiCKET",
            tier=TenantTier.CONSOLIDATOR,
            parent_id="master-mystes-kyrios",
        )
    """

    def __init__(self, event_bus: EventBus, storage_dir: str) -> None:
        """
        Initialize the tenant hierarchy.

        Args:
            event_bus: Shared event bus for publishing tenant lifecycle events.
            storage_dir: Directory path for persisting tenant JSON files.
                         Created automatically if it does not exist.
        """
        self._event_bus = event_bus
        self._storage_dir = storage_dir
        self._tenants: Dict[str, Tenant] = {}
        self._api_key_index: Dict[str, str] = {}  # api_key_hash -> tenant_id

        os.makedirs(self._storage_dir, exist_ok=True)
        self._load_all()
        self._ensure_master()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_tenant(
        self,
        name: str,
        tier: TenantTier,
        parent_id: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> Tenant:
        """
        Create a new tenant in the hierarchy.

        The tenant is persisted to disk immediately and a TENANT_CREATED
        event is published on the event bus.

        Args:
            name: Human-readable tenant name.
            tier: Hierarchy level for this tenant.
            parent_id: ID of the parent tenant. Required for CONSOLIDATOR
                       (parent must be MASTER) and AGENCY (parent must be
                       CONSOLIDATOR). Must be None for MASTER.
            config: Optional configuration dict. Merged with defaults if
                    provided. Keys: plan, limits, features, branding.

        Returns:
            The newly created Tenant instance.

        Raises:
            ValueError: If parent_id is invalid, parent tenant does not
                        exist, or tier/parent combination is not allowed.
        """
        self._validate_parent(tier, parent_id)

        tenant_config = {
            "plan": "pro",
            "limits": {},
            "features": [],
            "branding": {},
        }
        if config:
            tenant_config.update(config)

        tenant = Tenant(
            id=str(uuid.uuid4()),
            name=name,
            tier=tier.value,
            parent_id=parent_id,
            children_ids=[],
            config=tenant_config,
            status="active",
            created_at=time.time(),
            metadata={},
        )

        # Register in parent's children list
        if parent_id and parent_id in self._tenants:
            parent = self._tenants[parent_id]
            parent.children_ids.append(tenant.id)
            self._persist(parent)

        self._tenants[tenant.id] = tenant
        self._persist(tenant)

        self._event_bus.publish(Event(
            type=EventType.TENANT_CREATED,
            source="tenancy",
            data={
                "tenant_id": tenant.id,
                "name": tenant.name,
                "tier": tenant.tier,
                "parent_id": tenant.parent_id,
            },
        ))

        logger.info(
            "Created tenant '%s' (%s) under parent %s",
            tenant.name, tenant.tier, tenant.parent_id,
        )
        return tenant

    def get_tenant(self, tenant_id: str) -> Tenant:
        """
        Retrieve a tenant by its ID.

        Args:
            tenant_id: The unique identifier of the tenant.

        Returns:
            The Tenant instance.

        Raises:
            KeyError: If no tenant exists with the given ID.
        """
        if tenant_id not in self._tenants:
            raise KeyError(f"Tenant not found: {tenant_id}")
        return self._tenants[tenant_id]

    def get_by_api_key(self, api_key_hash: str) -> Tenant:
        """
        Look up a tenant by the SHA-256 hash of its API key.

        Args:
            api_key_hash: SHA-256 hex digest of the API key.

        Returns:
            The Tenant instance associated with the key.

        Raises:
            KeyError: If no tenant is associated with the given key hash.
        """
        tenant_id = self._api_key_index.get(api_key_hash)
        if not tenant_id:
            raise KeyError("No tenant found for the given API key")
        return self.get_tenant(tenant_id)

    def update_tenant(self, tenant_id: str, updates: dict) -> Tenant:
        """
        Apply partial updates to a tenant's mutable fields.

        Only the following fields may be updated: name, config, metadata,
        api_key_hash, and status. Structural fields (id, tier, parent_id,
        children_ids, created_at) are immutable after creation.

        Args:
            tenant_id: The ID of the tenant to update.
            updates: Dictionary of field names to new values.

        Returns:
            The updated Tenant instance.

        Raises:
            KeyError: If the tenant does not exist.
            ValueError: If an immutable field is included in updates.
        """
        tenant = self.get_tenant(tenant_id)
        immutable = {"id", "tier", "parent_id", "children_ids", "created_at"}
        bad_keys = set(updates.keys()) & immutable
        if bad_keys:
            raise ValueError(f"Cannot update immutable fields: {bad_keys}")

        for key, value in updates.items():
            if hasattr(tenant, key):
                setattr(tenant, key, value)

        # Rebuild API key index if key changed
        if "api_key_hash" in updates:
            self._rebuild_api_key_index()

        self._persist(tenant)
        logger.info("Updated tenant '%s': %s", tenant.name, list(updates.keys()))
        return tenant

    def suspend_tenant(self, tenant_id: str) -> Tenant:
        """
        Suspend a tenant and all of its descendants recursively.

        Suspended tenants cannot make API calls or process bookings.
        A TENANT_SUSPENDED event is published for each affected tenant.

        Args:
            tenant_id: The ID of the tenant to suspend.

        Returns:
            The suspended Tenant instance (top-level).

        Raises:
            KeyError: If the tenant does not exist.
            ValueError: If attempting to suspend the master tenant.
        """
        tenant = self.get_tenant(tenant_id)

        if tenant.tier == TenantTier.MASTER.value:
            raise ValueError("Cannot suspend the master tenant")

        self._suspend_recursive(tenant)
        return tenant

    def activate_tenant(self, tenant_id: str) -> Tenant:
        """
        Re-activate a suspended tenant.

        Only activates the specified tenant, not its children. Children
        must be individually activated if they were suspended.

        A TENANT_ACTIVATED event is published.

        Args:
            tenant_id: The ID of the tenant to activate.

        Returns:
            The activated Tenant instance.

        Raises:
            KeyError: If the tenant does not exist.
        """
        tenant = self.get_tenant(tenant_id)
        tenant.status = "active"
        self._persist(tenant)

        self._event_bus.publish(Event(
            type=EventType.TENANT_ACTIVATED,
            source="tenancy",
            data={
                "tenant_id": tenant.id,
                "name": tenant.name,
                "tier": tenant.tier,
            },
        ))

        logger.info("Activated tenant '%s'", tenant.name)
        return tenant

    def get_children(self, tenant_id: str) -> List[Tenant]:
        """
        Get the direct children of a tenant.

        Args:
            tenant_id: The ID of the parent tenant.

        Returns:
            List of direct child Tenant instances.

        Raises:
            KeyError: If the tenant does not exist.
        """
        tenant = self.get_tenant(tenant_id)
        children = []
        for child_id in tenant.children_ids:
            try:
                children.append(self.get_tenant(child_id))
            except KeyError:
                logger.warning(
                    "Orphaned child reference %s in tenant %s",
                    child_id, tenant_id,
                )
        return children

    def get_descendants(self, tenant_id: str) -> List[Tenant]:
        """
        Get all descendants of a tenant recursively (breadth-first).

        Args:
            tenant_id: The ID of the ancestor tenant.

        Returns:
            List of all descendant Tenant instances, in breadth-first order.

        Raises:
            KeyError: If the tenant does not exist.
        """
        descendants: List[Tenant] = []
        queue = list(self.get_children(tenant_id))
        while queue:
            current = queue.pop(0)
            descendants.append(current)
            queue.extend(self.get_children(current.id))
        return descendants

    def get_ancestors(self, tenant_id: str) -> List[Tenant]:
        """
        Get the parent chain from this tenant up to (and including) the master.

        Args:
            tenant_id: The ID of the starting tenant.

        Returns:
            List of ancestor Tenant instances, ordered from immediate parent
            to root (master).

        Raises:
            KeyError: If the tenant does not exist.
        """
        ancestors: List[Tenant] = []
        current = self.get_tenant(tenant_id)
        while current.parent_id is not None:
            parent = self.get_tenant(current.parent_id)
            ancestors.append(parent)
            current = parent
        return ancestors

    def get_hierarchy_tree(self) -> dict:
        """
        Build the full tenant hierarchy tree for admin dashboard rendering.

        Returns:
            Nested dictionary representing the tree structure. Each node
            contains the tenant's data and a ``children`` list of subtrees.

        Example return::

            {
                "id": "master-mystes-kyrios",
                "name": "MYSTES KYRIOS LLC",
                "tier": "master",
                "status": "active",
                "children": [
                    {
                        "id": "...",
                        "name": "AERTiCKET",
                        "tier": "consolidator",
                        "status": "active",
                        "children": [...]
                    }
                ]
            }
        """
        master = self._tenants.get(MASTER_TENANT_ID)
        if not master:
            return {}
        return self._build_subtree(master)

    def get_all_tenants(self) -> List[Tenant]:
        """
        Return all tenants in the system.

        Returns:
            List of every Tenant instance, in no guaranteed order.
        """
        return list(self._tenants.values())

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _validate_parent(self, tier: TenantTier, parent_id: Optional[str]) -> None:
        """Validate that the tier/parent combination is allowed."""
        if tier == TenantTier.MASTER:
            if parent_id is not None:
                raise ValueError("Master tenant cannot have a parent")
            return

        if parent_id is None:
            raise ValueError(f"{tier.value} tenant requires a parent_id")

        if parent_id not in self._tenants:
            raise ValueError(f"Parent tenant not found: {parent_id}")

        parent = self._tenants[parent_id]

        if tier == TenantTier.CONSOLIDATOR:
            if parent.tier != TenantTier.MASTER.value:
                raise ValueError(
                    "Consolidator parent must be the master tenant"
                )
        elif tier == TenantTier.AGENCY:
            if parent.tier != TenantTier.CONSOLIDATOR.value:
                raise ValueError(
                    "Agency parent must be a consolidator tenant"
                )

    def _suspend_recursive(self, tenant: Tenant) -> None:
        """Suspend a tenant and all descendants, emitting events for each."""
        tenant.status = "suspended"
        self._persist(tenant)

        self._event_bus.publish(Event(
            type=EventType.TENANT_SUSPENDED,
            source="tenancy",
            data={
                "tenant_id": tenant.id,
                "name": tenant.name,
                "tier": tenant.tier,
            },
        ))

        logger.info("Suspended tenant '%s'", tenant.name)

        for child in self.get_children(tenant.id):
            self._suspend_recursive(child)

    def _build_subtree(self, tenant: Tenant) -> dict:
        """Recursively build a tree node from a tenant and its children."""
        node = {
            "id": tenant.id,
            "name": tenant.name,
            "tier": tenant.tier,
            "status": tenant.status,
            "created_at": tenant.created_at,
            "config": tenant.config,
            "children": [],
        }
        for child in self.get_children(tenant.id):
            node["children"].append(self._build_subtree(child))
        return node

    def _ensure_master(self) -> None:
        """Create the master tenant if it does not already exist."""
        if MASTER_TENANT_ID in self._tenants:
            return

        master = Tenant(
            id=MASTER_TENANT_ID,
            name=MASTER_TENANT_NAME,
            tier=TenantTier.MASTER.value,
            parent_id=None,
            children_ids=[],
            config={
                "plan": "master",
                "limits": {},
                "features": ["all"],
                "branding": {"company": MASTER_TENANT_NAME},
            },
            status="active",
            created_at=time.time(),
            metadata={"auto_created": True},
        )

        self._tenants[master.id] = master
        self._persist(master)
        logger.info("Auto-created master tenant: %s", MASTER_TENANT_NAME)

    def _persist(self, tenant: Tenant) -> None:
        """Write a tenant's state to its JSON file on disk."""
        filepath = os.path.join(self._storage_dir, f"{tenant.id}.json")
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(tenant.to_dict(), f, indent=2, ensure_ascii=False)
        except OSError as exc:
            logger.error("Failed to persist tenant '%s': %s", tenant.id, exc)

    def _load_all(self) -> None:
        """Load all tenant JSON files from the storage directory."""
        if not os.path.isdir(self._storage_dir):
            return

        for filename in os.listdir(self._storage_dir):
            if not filename.endswith(".json"):
                continue
            filepath = os.path.join(self._storage_dir, filename)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                tenant = Tenant.from_dict(data)
                self._tenants[tenant.id] = tenant
                if tenant.api_key_hash:
                    self._api_key_index[tenant.api_key_hash] = tenant.id
            except (json.JSONDecodeError, OSError) as exc:
                logger.error("Failed to load tenant file '%s': %s", filename, exc)

        logger.info("Loaded %d tenants from disk", len(self._tenants))

    def _rebuild_api_key_index(self) -> None:
        """Rebuild the api_key_hash -> tenant_id lookup index."""
        self._api_key_index.clear()
        for tenant in self._tenants.values():
            if tenant.api_key_hash:
                self._api_key_index[tenant.api_key_hash] = tenant.id
