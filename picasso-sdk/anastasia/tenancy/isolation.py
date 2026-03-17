"""
Data Isolation — Tenant-scoped access control and resource limits.

Enforces that tenants can only access data belonging to themselves or their
descendants in the hierarchy. Also manages per-tenant rate limiting and
resource quotas with in-memory tracking and periodic disk flush.

Each tenant tier has default resource limits:
    - MASTER: Unlimited across all dimensions.
    - CONSOLIDATOR: Up to 10,000 agencies, 100,000 API calls/day.
    - AGENCY: Tiered by plan (Pro, Enterprise).

MYSTES KYRIOS LLC — Confidential.
"""

import functools
import json
import logging
import os
import time
from collections import defaultdict
from typing import Any, Callable, Dict, List, Optional

from ..core.types import TenantTier
from .hierarchy import TenantHierarchy

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Default resource limits per tier and plan
# ---------------------------------------------------------------------------

_MASTER_LIMITS: Dict[str, Any] = {
    "max_api_calls": -1,             # -1 = unlimited
    "max_agencies": -1,
    "max_bookings_per_day": -1,
    "max_storage_mb": -1,
    "features": ["all"],
}

_CONSOLIDATOR_LIMITS: Dict[str, Any] = {
    "max_api_calls": 100_000,        # per day
    "max_agencies": 10_000,
    "max_bookings_per_day": 50_000,
    "max_storage_mb": 10_000,
    "features": [
        "flights", "hotels", "analytics", "bulk_provisioning",
        "custom_branding", "webhook_events", "api_access",
    ],
}

_AGENCY_PLAN_LIMITS: Dict[str, Dict[str, Any]] = {
    "pro": {
        "max_api_calls": 10_000,
        "max_agencies": 0,
        "max_bookings_per_day": 200,
        "max_storage_mb": 500,
        "features": [
            "flights", "hotels", "analytics", "webhook_events",
            "custom_branding",
        ],
    },
    "enterprise": {
        "max_api_calls": 50_000,
        "max_agencies": 0,
        "max_bookings_per_day": 1_000,
        "max_storage_mb": 2_000,
        "features": [
            "flights", "hotels", "analytics", "webhook_events",
            "custom_branding", "api_access", "priority_support",
        ],
    },
}


class DataIsolation:
    """
    Enforces tenant data isolation, access control, and resource limits.

    Access rules:
        - A tenant can always access its own data.
        - A tenant can access data of any descendant in the hierarchy.
        - A tenant CANNOT access data of its siblings, ancestors, or
          unrelated tenants.

    Resource limits are determined by the tenant's tier and plan. Usage
    counters are tracked in memory with periodic flush to disk for
    durability across restarts.

    Usage:
        isolation = DataIsolation(hierarchy)
        if isolation.check_access(requester_id, target_id):
            # allow the operation
            ...
        if isolation.check_rate_limit(tenant_id, "api_calls"):
            isolation.record_usage(tenant_id, "api_calls")
        else:
            # reject: rate limit exceeded
            ...
    """

    def __init__(self, hierarchy: TenantHierarchy) -> None:
        """
        Initialize data isolation with a reference to the tenant hierarchy.

        Args:
            hierarchy: The TenantHierarchy instance used for ancestry
                       lookups and tier resolution.
        """
        self._hierarchy = hierarchy

        # In-memory usage counters: {tenant_id: {resource: {period: count}}}
        self._usage: Dict[str, Dict[str, Dict[str, int]]] = defaultdict(
            lambda: defaultdict(lambda: defaultdict(int))
        )

        # Timestamp tracking for period resets
        self._period_start: Dict[str, Dict[str, float]] = defaultdict(
            lambda: defaultdict(time.time)
        )

    # ------------------------------------------------------------------
    # Access control
    # ------------------------------------------------------------------

    def check_access(self, requester_tenant_id: str, target_tenant_id: str) -> bool:
        """
        Determine whether a requester tenant may access the target's data.

        A tenant can see its own data or the data of any of its descendants
        in the hierarchy. This means:
            - Master can see everything.
            - A consolidator can see its own data and all its agencies' data.
            - An agency can only see its own data.

        Args:
            requester_tenant_id: The tenant requesting access.
            target_tenant_id: The tenant whose data is being accessed.

        Returns:
            True if access is permitted, False otherwise.
        """
        # Same tenant — always allowed
        if requester_tenant_id == target_tenant_id:
            return True

        try:
            requester = self._hierarchy.get_tenant(requester_tenant_id)
        except KeyError:
            logger.warning("Access check: requester %s not found", requester_tenant_id)
            return False

        # Master can see everything
        if requester.tier == TenantTier.MASTER.value:
            return True

        # Check if target is a descendant of requester
        try:
            descendants = self._hierarchy.get_descendants(requester_tenant_id)
            descendant_ids = {d.id for d in descendants}
            return target_tenant_id in descendant_ids
        except KeyError:
            return False

    # ------------------------------------------------------------------
    # Resource limits
    # ------------------------------------------------------------------

    def get_resource_limits(self, tenant_id: str) -> Dict[str, Any]:
        """
        Return the effective resource limits for a tenant.

        Limits are determined by the tenant's tier. For agencies, limits
        depend on the plan specified in the tenant's config. If a custom
        ``limits`` override is present in the tenant config, those values
        take precedence over tier defaults.

        Args:
            tenant_id: The ID of the tenant.

        Returns:
            Dictionary with keys: max_api_calls, max_agencies,
            max_bookings_per_day, max_storage_mb, features.

        Raises:
            KeyError: If the tenant does not exist.
        """
        tenant = self._hierarchy.get_tenant(tenant_id)

        if tenant.tier == TenantTier.MASTER.value:
            base_limits = dict(_MASTER_LIMITS)
        elif tenant.tier == TenantTier.CONSOLIDATOR.value:
            base_limits = dict(_CONSOLIDATOR_LIMITS)
        else:
            plan = tenant.config.get("plan", "pro")
            base_limits = dict(_AGENCY_PLAN_LIMITS.get(plan, _AGENCY_PLAN_LIMITS["pro"]))

        # Apply per-tenant overrides from config
        custom_limits = tenant.config.get("limits", {})
        if custom_limits:
            base_limits.update(custom_limits)

        return base_limits

    def check_rate_limit(self, tenant_id: str, resource: str) -> bool:
        """
        Check whether a tenant is within its rate limit for a resource.

        Compares the current usage counter for the resource against the
        tenant's configured limit. A limit of -1 means unlimited.

        Args:
            tenant_id: The ID of the tenant.
            resource: The resource name (e.g., ``"api_calls"``,
                      ``"bookings"``).

        Returns:
            True if the tenant is within limits (operation allowed),
            False if the limit has been exceeded.
        """
        limits = self.get_resource_limits(tenant_id)
        limit_key = f"max_{resource}"
        max_allowed = limits.get(limit_key, -1)

        # -1 means unlimited
        if max_allowed == -1:
            return True

        tenant = self._hierarchy.get_tenant(tenant_id)
        period = self._get_limit_period(tenant, resource)
        current = self._usage[tenant_id][resource][period]
        return current < max_allowed

    def record_usage(self, tenant_id: str, resource: str, count: int = 1) -> None:
        """
        Record resource usage for a tenant.

        Increments the in-memory counter for the given resource by the
        specified count. Usage is partitioned by time period (day for
        daily limits, month for monthly limits).

        Args:
            tenant_id: The ID of the tenant.
            resource: The resource name (e.g., ``"api_calls"``).
            count: Number of units to record (default 1).
        """
        tenant = self._hierarchy.get_tenant(tenant_id)
        period = self._get_limit_period(tenant, resource)
        self._usage[tenant_id][resource][period] += count

    def get_usage(
        self,
        tenant_id: str,
        resource: str,
        period: str = "day",
    ) -> int:
        """
        Get current usage for a tenant and resource within a time period.

        Args:
            tenant_id: The ID of the tenant.
            resource: The resource name.
            period: Time period key. Use ``"day"`` for daily counters
                    or ``"month"`` for monthly counters. If ``"day"``,
                    the current day key is computed automatically.

        Returns:
            The current usage count for the resource in the given period.
        """
        if period == "day":
            period_key = self._day_key()
        elif period == "month":
            period_key = self._month_key()
        else:
            period_key = period

        return self._usage[tenant_id][resource].get(period_key, 0)

    def reset_usage(self, tenant_id: str, resource: str) -> None:
        """
        Reset the usage counter for a tenant and resource.

        Clears all period buckets for the given resource. Typically
        called by a scheduled job at the start of a new billing period.

        Args:
            tenant_id: The ID of the tenant.
            resource: The resource name to reset.
        """
        if tenant_id in self._usage and resource in self._usage[tenant_id]:
            self._usage[tenant_id][resource].clear()
            logger.info("Reset usage for tenant %s resource %s", tenant_id, resource)

    # ------------------------------------------------------------------
    # Decorator for query-level isolation
    # ------------------------------------------------------------------

    def enforce_isolation(self, query_func: Callable) -> Callable:
        """
        Decorator that filters query results by tenant scope.

        The decorated function must accept ``tenant_id`` as its first
        positional argument. Results are filtered to include only items
        that belong to the requesting tenant or its descendants.

        The decorated function must return a list of dicts, each with a
        ``tenant_id`` key indicating ownership.

        Args:
            query_func: The function to wrap.

        Returns:
            Wrapped function with tenant-scoped filtering applied.

        Example::

            @isolation.enforce_isolation
            def list_bookings(tenant_id: str) -> List[dict]:
                return all_bookings  # unfiltered

            # When called, only returns bookings visible to the tenant
            visible = list_bookings("agency-123")
        """
        @functools.wraps(query_func)
        def wrapper(tenant_id: str, *args: Any, **kwargs: Any) -> list:
            results = query_func(tenant_id, *args, **kwargs)

            # Build the set of visible tenant IDs
            visible_ids = {tenant_id}
            try:
                descendants = self._hierarchy.get_descendants(tenant_id)
                visible_ids.update(d.id for d in descendants)
            except KeyError:
                pass

            # Filter results
            filtered = [
                item for item in results
                if item.get("tenant_id") in visible_ids
            ]
            return filtered

        return wrapper

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def flush_to_disk(self, storage_dir: str) -> None:
        """
        Persist current usage counters to disk.

        Writes a JSON file per tenant containing all resource usage data.
        Intended to be called periodically (e.g., every 5 minutes) by a
        background task.

        Args:
            storage_dir: Directory to write usage JSON files into.
        """
        os.makedirs(storage_dir, exist_ok=True)
        for tenant_id, resources in self._usage.items():
            filepath = os.path.join(storage_dir, f"usage_{tenant_id}.json")
            serializable = {
                res: dict(periods) for res, periods in resources.items()
            }
            try:
                with open(filepath, "w", encoding="utf-8") as f:
                    json.dump(serializable, f, indent=2)
            except OSError as exc:
                logger.error(
                    "Failed to flush usage for tenant %s: %s",
                    tenant_id, exc,
                )

    def load_from_disk(self, storage_dir: str) -> None:
        """
        Restore usage counters from disk.

        Args:
            storage_dir: Directory containing usage JSON files.
        """
        if not os.path.isdir(storage_dir):
            return

        for filename in os.listdir(storage_dir):
            if not filename.startswith("usage_") or not filename.endswith(".json"):
                continue
            tenant_id = filename[len("usage_"):-len(".json")]
            filepath = os.path.join(storage_dir, filename)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for resource, periods in data.items():
                    for period_key, count in periods.items():
                        self._usage[tenant_id][resource][period_key] = count
            except (json.JSONDecodeError, OSError) as exc:
                logger.error(
                    "Failed to load usage from '%s': %s", filename, exc,
                )

        logger.info("Loaded usage data from disk")

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_limit_period(self, tenant: Any, resource: str) -> str:
        """
        Determine the appropriate time period key for a resource.

        Agencies use monthly periods for api_calls (matching their
        monthly quotas). All other resources and tiers use daily periods.

        Args:
            tenant: Tenant instance.
            resource: Resource name.

        Returns:
            A string key representing the current time period bucket
            (e.g., ``"2026-03-08"`` or ``"2026-03"``).
        """
        if tenant.tier == TenantTier.AGENCY.value and resource == "api_calls":
            return self._month_key()
        return self._day_key()

    @staticmethod
    def _day_key() -> str:
        """Return today's date as a period key (YYYY-MM-DD)."""
        return time.strftime("%Y-%m-%d", time.gmtime())

    @staticmethod
    def _month_key() -> str:
        """Return the current month as a period key (YYYY-MM)."""
        return time.strftime("%Y-%m", time.gmtime())
