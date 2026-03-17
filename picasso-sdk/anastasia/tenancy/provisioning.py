"""
Tenant Provisioning — Automated tenant lifecycle management.

Handles the full lifecycle of tenant onboarding and offboarding:
    - Consolidator provisioning (API key generation, default limits)
    - Agency provisioning under a consolidator (plan-based setup)
    - Trial tenants with automatic expiry
    - Graceful deprovisioning with data export scheduling
    - Plan upgrades and bulk provisioning

API keys use the ``ana_`` prefix followed by 48 hex characters, stored
as SHA-256 hashes for security.

MYSTES KYRIOS LLC — Confidential.
"""

import hashlib
import logging
import os
import secrets
import time
from typing import Any, Dict, List, Optional

from ..core.events import Event, EventBus, EventType
from ..core.types import TenantTier
from .hierarchy import MASTER_TENANT_ID, TenantHierarchy
from .isolation import DataIsolation

logger = logging.getLogger(__name__)

# API key format: ana_ prefix + 48 hex chars = 52 chars total
_API_KEY_PREFIX = "ana_"
_API_KEY_HEX_LENGTH = 48


class TenantProvisioning:
    """
    Automated tenant setup and teardown.

    Orchestrates the complete provisioning workflow for new tenants:
    creating the tenant record, generating API credentials, applying
    plan-specific resource limits, and publishing lifecycle events.

    Deprovisioning handles graceful shutdown: suspending the tenant,
    scheduling data export, and marking for deletion.

    Usage:
        provisioning = TenantProvisioning(event_bus, hierarchy, isolation)

        # Provision a new consolidator
        result = provisioning.provision_consolidator(
            name="AERTiCKET",
            admin_email="admin@aerticket.com",
        )
        print(result["api_key"])  # ana_<48 hex chars> — store securely!

        # Provision an agency under the consolidator
        agency = provisioning.provision_agency(
            name="Berlin Travel GmbH",
            consolidator_id=result["tenant_id"],
            plan="pro",
        )
    """

    def __init__(
        self,
        event_bus: EventBus,
        hierarchy: TenantHierarchy,
        isolation: DataIsolation,
    ) -> None:
        """
        Initialize the provisioning engine.

        Args:
            event_bus: Shared event bus for publishing lifecycle events.
            hierarchy: TenantHierarchy instance for tenant CRUD.
            isolation: DataIsolation instance for applying resource limits.
        """
        self._event_bus = event_bus
        self._hierarchy = hierarchy
        self._isolation = isolation

    # ------------------------------------------------------------------
    # Provisioning
    # ------------------------------------------------------------------

    def provision_consolidator(
        self,
        name: str,
        admin_email: str,
        config: Optional[Dict[str, Any]] = None,
    ) -> dict:
        """
        Provision a new consolidator tenant under the master.

        Creates the tenant, generates a master API key, applies default
        consolidator limits, and returns the credentials. The plaintext
        API key is returned exactly once; only the hash is stored.

        Args:
            name: Name of the consolidator (e.g., "AERTiCKET").
            admin_email: Email address of the consolidator admin.
            config: Optional configuration overrides. Merged with
                    consolidator defaults.

        Returns:
            Dictionary containing:
                - tenant_id: The new tenant's ID.
                - name: Tenant name.
                - tier: "consolidator".
                - api_key: Plaintext API key (store securely, shown once).
                - admin_email: The admin email provided.
                - status: "active".
                - limits: Applied resource limits dict.
                - created_at: Unix timestamp.
        """
        tenant_config = {
            "plan": "consolidator",
            "limits": {},
            "features": [
                "flights", "hotels", "analytics", "bulk_provisioning",
                "custom_branding", "webhook_events", "api_access",
            ],
            "branding": {},
            "admin_email": admin_email,
        }
        if config:
            tenant_config.update(config)

        tenant = self._hierarchy.create_tenant(
            name=name,
            tier=TenantTier.CONSOLIDATOR,
            parent_id=MASTER_TENANT_ID,
            config=tenant_config,
        )

        # Generate and store API key
        api_key = self.generate_api_key()
        key_hash = self._hash_key(api_key)
        self._hierarchy.update_tenant(tenant.id, {"api_key_hash": key_hash})

        limits = self._isolation.get_resource_limits(tenant.id)

        logger.info(
            "Provisioned consolidator '%s' (id=%s, email=%s)",
            name, tenant.id, admin_email,
        )

        return {
            "tenant_id": tenant.id,
            "name": tenant.name,
            "tier": "consolidator",
            "api_key": api_key,
            "admin_email": admin_email,
            "status": tenant.status,
            "limits": limits,
            "created_at": tenant.created_at,
        }

    def provision_agency(
        self,
        name: str,
        consolidator_id: str,
        plan: str = "pro",
        config: Optional[Dict[str, Any]] = None,
    ) -> dict:
        """
        Provision a new agency tenant under a consolidator.

        Creates the agency, generates an API key, applies plan-based
        resource limits, and returns the credentials.

        Args:
            name: Name of the agency.
            consolidator_id: ID of the parent consolidator tenant.
            plan: Subscription plan. One of "pro", "enterprise".
                  Defaults to "pro".
            config: Optional configuration overrides.

        Returns:
            Dictionary containing:
                - tenant_id: The new tenant's ID.
                - name: Tenant name.
                - tier: "agency".
                - api_key: Plaintext API key (shown once).
                - consolidator_id: Parent consolidator ID.
                - plan: Applied plan name.
                - status: "active".
                - limits: Applied resource limits dict.
                - created_at: Unix timestamp.

        Raises:
            KeyError: If the consolidator does not exist.
            ValueError: If the consolidator is not actually a consolidator
                        or if the plan name is invalid.
        """
        # Validate consolidator
        consolidator = self._hierarchy.get_tenant(consolidator_id)
        if consolidator.tier != TenantTier.CONSOLIDATOR.value:
            raise ValueError(
                f"Parent tenant {consolidator_id} is not a consolidator "
                f"(tier={consolidator.tier})"
            )

        valid_plans = {"pro", "enterprise"}
        if plan not in valid_plans:
            raise ValueError(
                f"Invalid plan '{plan}'. Must be one of: {', '.join(sorted(valid_plans))}"
            )

        tenant_config = {
            "plan": plan,
            "limits": {},
            "features": [],
            "branding": {},
        }
        if config:
            tenant_config.update(config)

        tenant = self._hierarchy.create_tenant(
            name=name,
            tier=TenantTier.AGENCY,
            parent_id=consolidator_id,
            config=tenant_config,
        )

        # Generate and store API key
        api_key = self.generate_api_key()
        key_hash = self._hash_key(api_key)
        self._hierarchy.update_tenant(tenant.id, {"api_key_hash": key_hash})

        limits = self._isolation.get_resource_limits(tenant.id)

        logger.info(
            "Provisioned agency '%s' (id=%s) under consolidator '%s' on plan '%s'",
            name, tenant.id, consolidator.name, plan,
        )

        return {
            "tenant_id": tenant.id,
            "name": tenant.name,
            "tier": "agency",
            "api_key": api_key,
            "consolidator_id": consolidator_id,
            "plan": plan,
            "status": tenant.status,
            "limits": limits,
            "created_at": tenant.created_at,
        }

    def provision_trial(
        self,
        name: str,
        email: str,
        plan: str = "pro",
        trial_days: int = 14,
    ) -> dict:
        """
        Provision a trial agency with automatic expiry.

        Trial agencies are created under the master tenant (not under a
        specific consolidator) with a "trial" status and an expiry
        timestamp. After the trial period, the agency should be
        suspended or converted to a paid plan.

        Args:
            name: Name of the trial agency.
            email: Contact email for the trial user.
            plan: Plan to apply during the trial period. Defaults to
                  "pro".
            trial_days: Number of days before the trial expires.
                        Defaults to 14.

        Returns:
            Dictionary containing:
                - tenant_id: The new tenant's ID.
                - name: Tenant name.
                - tier: "agency".
                - api_key: Plaintext API key (shown once).
                - plan: Applied plan.
                - status: "trial".
                - trial_expires_at: Unix timestamp of trial expiry.
                - limits: Applied resource limits dict.
                - created_at: Unix timestamp.

        Note:
            Trial tenants are parented to the master since they have no
            consolidator relationship yet. They can be re-parented to a
            consolidator upon conversion.
        """
        # Trials are created under the master with a trial consolidator
        # To allow this, we first need a trial-holding consolidator or
        # create them directly. For simplicity, trial agencies sit under
        # the master's first consolidator, or we create a special one.
        # Design decision: trials go under master directly? No -- agencies
        # must have a consolidator parent per hierarchy rules. We use a
        # dedicated "MYSTES Direct" consolidator for trial/direct agencies.
        trial_consolidator = self._ensure_trial_consolidator()

        tenant_config = {
            "plan": plan,
            "limits": {},
            "features": [],
            "branding": {},
            "admin_email": email,
            "trial": True,
            "trial_expires_at": time.time() + (trial_days * 86400),
        }

        tenant = self._hierarchy.create_tenant(
            name=name,
            tier=TenantTier.AGENCY,
            parent_id=trial_consolidator.id,
            config=tenant_config,
        )

        # Set trial status
        self._hierarchy.update_tenant(tenant.id, {"status": "trial"})

        # Generate and store API key
        api_key = self.generate_api_key()
        key_hash = self._hash_key(api_key)
        self._hierarchy.update_tenant(tenant.id, {"api_key_hash": key_hash})

        limits = self._isolation.get_resource_limits(tenant.id)

        logger.info(
            "Provisioned trial agency '%s' (id=%s, email=%s, expires in %d days)",
            name, tenant.id, email, trial_days,
        )

        return {
            "tenant_id": tenant.id,
            "name": tenant.name,
            "tier": "agency",
            "api_key": api_key,
            "plan": plan,
            "status": "trial",
            "trial_expires_at": tenant_config["trial_expires_at"],
            "limits": limits,
            "created_at": tenant.created_at,
        }

    # ------------------------------------------------------------------
    # Deprovisioning
    # ------------------------------------------------------------------

    def deprovision(self, tenant_id: str) -> dict:
        """
        Gracefully deprovision a tenant.

        The deprovisioning workflow:
        1. Suspend the tenant (and all descendants).
        2. Mark for data export.
        3. Schedule deletion (not immediate -- allows recovery).
        4. Revoke API key.

        Args:
            tenant_id: The ID of the tenant to deprovision.

        Returns:
            Dictionary containing:
                - tenant_id: The deprovisioned tenant's ID.
                - status: "suspended".
                - data_export_scheduled: Whether export was scheduled.
                - deletion_scheduled_at: Unix timestamp for planned
                  deletion (30 days from now).
                - descendants_affected: Number of child tenants suspended.

        Raises:
            KeyError: If the tenant does not exist.
            ValueError: If attempting to deprovision the master tenant.
        """
        tenant = self._hierarchy.get_tenant(tenant_id)

        if tenant.tier == TenantTier.MASTER.value:
            raise ValueError("Cannot deprovision the master tenant")

        # Count descendants before suspension
        descendants = self._hierarchy.get_descendants(tenant_id)
        descendants_count = len(descendants)

        # Suspend tenant and all children
        self._hierarchy.suspend_tenant(tenant_id)

        # Revoke API key
        self._hierarchy.update_tenant(tenant_id, {"api_key_hash": None})

        # Schedule deletion (30-day grace period)
        deletion_time = time.time() + (30 * 86400)
        self._hierarchy.update_tenant(tenant_id, {
            "metadata": {
                **tenant.metadata,
                "deprovisioned": True,
                "deprovisioned_at": time.time(),
                "deletion_scheduled_at": deletion_time,
                "data_export_scheduled": True,
            },
        })

        logger.info(
            "Deprovisioned tenant '%s' (id=%s), %d descendants affected",
            tenant.name, tenant_id, descendants_count,
        )

        return {
            "tenant_id": tenant_id,
            "status": "suspended",
            "data_export_scheduled": True,
            "deletion_scheduled_at": deletion_time,
            "descendants_affected": descendants_count,
        }

    # ------------------------------------------------------------------
    # Plan management
    # ------------------------------------------------------------------

    def upgrade_plan(self, tenant_id: str, new_plan: str) -> dict:
        """
        Upgrade (or change) a tenant's subscription plan.

        Updates the plan in the tenant's config and publishes a
        TENANT_UPGRADED event. The new resource limits take effect
        immediately.

        Args:
            tenant_id: The ID of the tenant to upgrade.
            new_plan: The new plan name. Must be one of "pro",
                      "enterprise", or "consolidator".

        Returns:
            Dictionary containing:
                - tenant_id: The tenant's ID.
                - previous_plan: The old plan name.
                - new_plan: The new plan name.
                - new_limits: The resource limits under the new plan.

        Raises:
            KeyError: If the tenant does not exist.
            ValueError: If the plan name is invalid.
        """
        valid_plans = {"pro", "enterprise", "consolidator"}
        if new_plan not in valid_plans:
            raise ValueError(
                f"Invalid plan '{new_plan}'. "
                f"Must be one of: {', '.join(sorted(valid_plans))}"
            )

        tenant = self._hierarchy.get_tenant(tenant_id)
        previous_plan = tenant.config.get("plan", "pro")

        updated_config = dict(tenant.config)
        updated_config["plan"] = new_plan

        # Clear trial flag on upgrade
        updated_config.pop("trial", None)
        updated_config.pop("trial_expires_at", None)

        self._hierarchy.update_tenant(tenant_id, {
            "config": updated_config,
            "status": "active",  # Activate if was trial
        })

        new_limits = self._isolation.get_resource_limits(tenant_id)

        self._event_bus.publish(Event(
            type=EventType.TENANT_UPGRADED,
            source="tenancy",
            data={
                "tenant_id": tenant_id,
                "previous_plan": previous_plan,
                "new_plan": new_plan,
                "new_limits": new_limits,
            },
        ))

        logger.info(
            "Upgraded tenant '%s' from '%s' to '%s'",
            tenant.name, previous_plan, new_plan,
        )

        return {
            "tenant_id": tenant_id,
            "previous_plan": previous_plan,
            "new_plan": new_plan,
            "new_limits": new_limits,
        }

    # ------------------------------------------------------------------
    # Bulk operations
    # ------------------------------------------------------------------

    def bulk_provision(
        self,
        agencies: List[dict],
        consolidator_id: str,
    ) -> List[dict]:
        """
        Provision multiple agencies under a consolidator in a single call.

        Each entry in the agencies list should be a dict with at least
        a ``name`` key. Optional keys: ``plan``, ``config``.

        Args:
            agencies: List of agency specification dicts. Each must
                      contain ``name`` (str). Optional: ``plan`` (str,
                      defaults to "pro"), ``config`` (dict).
            consolidator_id: ID of the parent consolidator.

        Returns:
            List of provisioning result dicts (same format as
            provision_agency return value). Failed provisions are
            included with an ``error`` key instead of credentials.
        """
        results: List[dict] = []

        for spec in agencies:
            name = spec.get("name")
            if not name:
                results.append({
                    "error": "Missing required 'name' field",
                    "spec": spec,
                })
                continue

            plan = spec.get("plan", "pro")
            config = spec.get("config")

            try:
                result = self.provision_agency(
                    name=name,
                    consolidator_id=consolidator_id,
                    plan=plan,
                    config=config,
                )
                results.append(result)
            except (KeyError, ValueError) as exc:
                logger.error(
                    "Bulk provision failed for '%s': %s", name, exc,
                )
                results.append({
                    "name": name,
                    "error": str(exc),
                })

        logger.info(
            "Bulk provisioned %d/%d agencies under consolidator %s",
            sum(1 for r in results if "error" not in r),
            len(agencies),
            consolidator_id,
        )

        return results

    # ------------------------------------------------------------------
    # Onboarding status
    # ------------------------------------------------------------------

    def get_onboarding_status(self, tenant_id: str) -> dict:
        """
        Check what onboarding steps a tenant has completed.

        Returns a checklist of setup steps with completion status.
        Useful for rendering an onboarding wizard in the admin dashboard.

        Args:
            tenant_id: The ID of the tenant to check.

        Returns:
            Dictionary with:
                - tenant_id: The tenant's ID.
                - steps: List of step dicts, each with ``name`` (str),
                  ``completed`` (bool), and ``description`` (str).
                - completion_pct: Overall completion percentage (0-100).

        Raises:
            KeyError: If the tenant does not exist.
        """
        tenant = self._hierarchy.get_tenant(tenant_id)

        steps = [
            {
                "name": "tenant_created",
                "description": "Tenant record created in hierarchy",
                "completed": True,  # Always true if we got here
            },
            {
                "name": "api_key_generated",
                "description": "API key generated and stored",
                "completed": tenant.api_key_hash is not None,
            },
            {
                "name": "plan_configured",
                "description": "Subscription plan selected",
                "completed": bool(tenant.config.get("plan")),
            },
            {
                "name": "branding_configured",
                "description": "Custom branding settings applied",
                "completed": bool(tenant.config.get("branding")),
            },
            {
                "name": "admin_email_set",
                "description": "Admin contact email configured",
                "completed": bool(tenant.config.get("admin_email")),
            },
            {
                "name": "first_api_call",
                "description": "Successfully made first API call",
                "completed": bool(tenant.metadata.get("first_api_call_at")),
            },
        ]

        # Add consolidator-specific steps
        if tenant.tier == TenantTier.CONSOLIDATOR.value:
            steps.append({
                "name": "first_agency_provisioned",
                "description": "First agency provisioned under consolidator",
                "completed": len(tenant.children_ids) > 0,
            })

        completed_count = sum(1 for s in steps if s["completed"])
        total_count = len(steps)
        completion_pct = round((completed_count / total_count) * 100) if total_count else 0

        return {
            "tenant_id": tenant_id,
            "steps": steps,
            "completion_pct": completion_pct,
        }

    # ------------------------------------------------------------------
    # Key generation
    # ------------------------------------------------------------------

    @staticmethod
    def generate_api_key() -> str:
        """
        Generate a secure API key with the ANASTASiA prefix.

        Format: ``ana_`` followed by 48 cryptographically random hex
        characters (192 bits of entropy).

        Returns:
            A new plaintext API key string (52 characters total).
        """
        hex_chars = secrets.token_hex(_API_KEY_HEX_LENGTH // 2)
        return f"{_API_KEY_PREFIX}{hex_chars}"

    @staticmethod
    def _hash_key(api_key: str) -> str:
        """
        Compute the SHA-256 hash of an API key for secure storage.

        Args:
            api_key: The plaintext API key.

        Returns:
            Hex-encoded SHA-256 digest.
        """
        return hashlib.sha256(api_key.encode("utf-8")).hexdigest()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _ensure_trial_consolidator(self):
        """
        Ensure a dedicated consolidator exists for trial/direct agencies.

        Trial agencies need a consolidator parent (hierarchy invariant).
        This method creates a "MYSTES Direct" consolidator under the
        master if one does not already exist.

        Returns:
            The trial consolidator Tenant instance.
        """
        # Look for existing trial consolidator
        master_children = self._hierarchy.get_children(MASTER_TENANT_ID)
        for child in master_children:
            if child.name == "MYSTES Direct":
                return child

        # Create the trial consolidator
        tenant = self._hierarchy.create_tenant(
            name="MYSTES Direct",
            tier=TenantTier.CONSOLIDATOR,
            parent_id=MASTER_TENANT_ID,
            config={
                "plan": "consolidator",
                "limits": {},
                "features": ["flights", "hotels"],
                "branding": {"company": "MYSTES Direct"},
                "is_trial_consolidator": True,
            },
        )

        logger.info("Created trial consolidator 'MYSTES Direct' (id=%s)", tenant.id)
        return tenant
