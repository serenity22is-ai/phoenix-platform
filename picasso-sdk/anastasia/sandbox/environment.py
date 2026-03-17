"""
Sandbox Environment — Isolated trial environment provisioning for agencies.

Provides time-limited, self-contained sandbox environments where agencies
can test ANASTASiA capabilities with simulated data before committing to
a paid plan. Each sandbox gets a unique API key, isolated configuration,
and usage tracking.

MYSTES KYRIOS LLC — Confidential.
"""

import json
import logging
import os
import secrets
import time
import uuid
from typing import Any, Dict, List, Optional

from ..core.events import Event, EventBus, EventType

logger = logging.getLogger(__name__)

# Default sandbox limits
DEFAULT_TRIAL_DAYS = 14
DEFAULT_API_CALL_LIMIT = 500
DEFAULT_PLAN = "pro"

# Plan configurations
PLAN_CONFIGS = {
    "pro": {
        "api_call_limit": 2000,
        "trial_days": 14,
        "features": [
            "flight_search",
            "booking_simulation",
            "price_alerts",
            "seatmap_view",
            "fare_rules",
            "multi_pnr",
            "queue_management",
            "reporting",
        ],
        "max_concurrent_searches": 20,
        "max_bookings": 200,
    },
    "enterprise": {
        "api_call_limit": 10000,
        "trial_days": 14,
        "features": [
            "flight_search",
            "booking_simulation",
            "price_alerts",
            "seatmap_view",
            "fare_rules",
            "multi_pnr",
            "queue_management",
            "reporting",
            "api_webhooks",
            "white_label",
            "bulk_operations",
            "dedicated_support",
        ],
        "max_concurrent_searches": 100,
        "max_bookings": 1000,
    },
}

# Sandbox API endpoint descriptions
SANDBOX_ENDPOINTS = {
    "search": "/api/sandbox/{sandbox_id}/flights/search",
    "book": "/api/sandbox/{sandbox_id}/bookings",
    "seatmap": "/api/sandbox/{sandbox_id}/seatmap/{flight_number}",
    "fare_rules": "/api/sandbox/{sandbox_id}/fare-rules/{fare_id}",
    "booking_detail": "/api/sandbox/{sandbox_id}/bookings/{pnr}",
    "price_alerts": "/api/sandbox/{sandbox_id}/alerts",
    "usage": "/api/sandbox/{sandbox_id}/usage",
}


class SandboxEnvironment:
    """
    Manages isolated sandbox environments for agency trials.

    Each sandbox provides:
    - A unique API key (prefixed with ``sandbox_``) for authentication
    - Isolated configuration based on the selected plan
    - Usage tracking (API calls, features tested, bookings simulated)
    - Automatic expiration after the trial period
    - Persistent storage as JSON files in the configured storage directory

    Usage::

        env = SandboxEnvironment(event_bus, "/data/sandboxes")
        sandbox = env.create_sandbox("agency-123", plan="professional")
        print(sandbox["api_key"])  # sandbox_a1b2c3...
        print(sandbox["expires_at"])  # Unix timestamp 14 days from now
    """

    def __init__(self, event_bus: EventBus, storage_dir: str) -> None:
        """
        Initialize the sandbox environment manager.

        Args:
            event_bus: Shared event bus for publishing lifecycle events.
            storage_dir: Directory path where sandbox JSON configs are stored.
        """
        self._event_bus = event_bus
        self._storage_dir = storage_dir
        self._sandboxes: Dict[str, dict] = {}

        os.makedirs(storage_dir, exist_ok=True)
        self._load_all()
        logger.info(
            "SandboxEnvironment initialized — %d sandboxes loaded from %s",
            len(self._sandboxes),
            storage_dir,
        )

    def _load_all(self) -> None:
        """Load all sandbox configurations from the storage directory."""
        for filename in os.listdir(self._storage_dir):
            if filename.startswith("sandbox_") and filename.endswith(".json"):
                filepath = os.path.join(self._storage_dir, filename)
                try:
                    with open(filepath, "r") as f:
                        data = json.load(f)
                    sandbox_id = data.get("sandbox_id")
                    if sandbox_id:
                        self._sandboxes[sandbox_id] = data
                except (json.JSONDecodeError, IOError) as e:
                    logger.warning("Failed to load sandbox file %s: %s", filepath, e)

    def _persist(self, sandbox_id: str) -> None:
        """Write a sandbox configuration to disk."""
        data = self._sandboxes.get(sandbox_id)
        if not data:
            return
        filepath = os.path.join(self._storage_dir, f"sandbox_{sandbox_id}.json")
        try:
            with open(filepath, "w") as f:
                json.dump(data, f, indent=2)
        except IOError as e:
            logger.error("Failed to persist sandbox %s: %s", sandbox_id, e)

    def _remove_file(self, sandbox_id: str) -> None:
        """Remove a sandbox configuration file from disk."""
        filepath = os.path.join(self._storage_dir, f"sandbox_{sandbox_id}.json")
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
        except IOError as e:
            logger.warning("Failed to remove sandbox file %s: %s", filepath, e)

    def _generate_api_key(self) -> str:
        """Generate a unique sandbox API key with ``sandbox_`` prefix."""
        return f"sandbox_{secrets.token_hex(24)}"

    def _build_endpoints(self, sandbox_id: str) -> Dict[str, str]:
        """Build the API endpoint map for a sandbox."""
        return {
            name: template.format(
                sandbox_id=sandbox_id,
                flight_number="{flight_number}",
                fare_id="{fare_id}",
                pnr="{pnr}",
            )
            for name, template in SANDBOX_ENDPOINTS.items()
        }

    def create_sandbox(
        self,
        agency_id: str,
        plan: str = DEFAULT_PLAN,
        config: Optional[dict] = None,
    ) -> dict:
        """
        Create an isolated sandbox environment for an agency.

        Args:
            agency_id: The agency's unique identifier.
            plan: Plan tier — one of ``"pro"`` or ``"enterprise"``.
                  Defaults to ``"pro"``.
            config: Optional overrides merged into the plan configuration.

        Returns:
            A dict containing:
            - ``sandbox_id``: Unique sandbox identifier.
            - ``api_key``: Authentication key (``sandbox_`` prefix).
            - ``expires_at``: Unix timestamp when the trial expires.
            - ``endpoints``: Dict of available API endpoints.
            - Plus full sandbox metadata.

        Raises:
            ValueError: If the plan name is not recognized.
        """
        if plan not in PLAN_CONFIGS:
            raise ValueError(
                f"Unknown plan '{plan}'. Valid plans: {list(PLAN_CONFIGS.keys())}"
            )

        plan_config = PLAN_CONFIGS[plan].copy()
        if config:
            plan_config.update(config)

        sandbox_id = str(uuid.uuid4())[:12]
        api_key = self._generate_api_key()
        now = time.time()
        trial_days = plan_config.get("trial_days", DEFAULT_TRIAL_DAYS)
        expires_at = now + (trial_days * 86400)

        sandbox = {
            "sandbox_id": sandbox_id,
            "agency_id": agency_id,
            "api_key": api_key,
            "plan": plan,
            "created_at": now,
            "expires_at": expires_at,
            "trial_days": trial_days,
            "active": True,
            "endpoints": self._build_endpoints(sandbox_id),
            "config": plan_config,
            "usage": {
                "api_calls": 0,
                "api_call_limit": plan_config["api_call_limit"],
                "bookings_created": 0,
                "searches_performed": 0,
                "features_tested": [],
                "last_activity": None,
            },
        }

        self._sandboxes[sandbox_id] = sandbox
        self._persist(sandbox_id)

        logger.info(
            "Created sandbox %s for agency %s (plan=%s, expires in %d days)",
            sandbox_id,
            agency_id,
            plan,
            trial_days,
        )

        return sandbox

    def get_sandbox(self, sandbox_id: str) -> Optional[dict]:
        """
        Retrieve a sandbox by its ID.

        Automatically marks expired sandboxes as inactive upon access.

        Args:
            sandbox_id: The sandbox identifier.

        Returns:
            The sandbox dict, or None if not found.
        """
        sandbox = self._sandboxes.get(sandbox_id)
        if not sandbox:
            return None

        # Auto-expire check
        if sandbox["active"] and time.time() > sandbox["expires_at"]:
            sandbox["active"] = False
            self._persist(sandbox_id)
            logger.info("Sandbox %s auto-expired on access", sandbox_id)

        return sandbox

    def destroy_sandbox(self, sandbox_id: str) -> bool:
        """
        Permanently destroy a sandbox and remove its data.

        Args:
            sandbox_id: The sandbox identifier.

        Returns:
            True if the sandbox was found and destroyed, False otherwise.
        """
        if sandbox_id not in self._sandboxes:
            return False

        del self._sandboxes[sandbox_id]
        self._remove_file(sandbox_id)
        logger.info("Destroyed sandbox %s", sandbox_id)
        return True

    def is_sandbox_active(self, sandbox_id: str) -> bool:
        """
        Check whether a sandbox is active (not expired and not destroyed).

        Triggers auto-expiration if the trial period has elapsed.

        Args:
            sandbox_id: The sandbox identifier.

        Returns:
            True if the sandbox exists and is still within its trial period.
        """
        sandbox = self.get_sandbox(sandbox_id)
        if not sandbox:
            return False
        return sandbox["active"]

    def list_sandboxes(self, agency_id: Optional[str] = None) -> List[dict]:
        """
        List all sandboxes, optionally filtered by agency.

        Runs expiration checks on every sandbox before returning.

        Args:
            agency_id: If provided, return only sandboxes belonging to
                       this agency.

        Returns:
            List of sandbox dicts.
        """
        # Trigger auto-expire on all sandboxes
        now = time.time()
        for sid, sandbox in self._sandboxes.items():
            if sandbox["active"] and now > sandbox["expires_at"]:
                sandbox["active"] = False
                self._persist(sid)

        sandboxes = list(self._sandboxes.values())
        if agency_id:
            sandboxes = [s for s in sandboxes if s["agency_id"] == agency_id]

        return sandboxes

    def extend_sandbox(self, sandbox_id: str, days: int = 7) -> Optional[dict]:
        """
        Extend a sandbox's trial period.

        Can be used to grant additional time to promising leads or
        agencies that need more evaluation time.

        Args:
            sandbox_id: The sandbox identifier.
            days: Number of days to extend. Defaults to 7.

        Returns:
            The updated sandbox dict, or None if the sandbox was not found.

        Raises:
            ValueError: If days is not a positive integer.
        """
        if days <= 0:
            raise ValueError("Extension days must be a positive integer")

        sandbox = self._sandboxes.get(sandbox_id)
        if not sandbox:
            return None

        sandbox["expires_at"] += days * 86400
        sandbox["trial_days"] += days
        sandbox["active"] = True  # Reactivate if previously expired
        self._persist(sandbox_id)

        logger.info(
            "Extended sandbox %s by %d days (new expiry: %.0f)",
            sandbox_id,
            days,
            sandbox["expires_at"],
        )

        return sandbox

    def get_sandbox_usage(self, sandbox_id: str) -> Optional[dict]:
        """
        Get detailed usage statistics for a sandbox.

        Args:
            sandbox_id: The sandbox identifier.

        Returns:
            A dict containing:
            - ``api_calls``: Total API calls made.
            - ``api_call_limit``: Maximum allowed API calls.
            - ``usage_pct``: Percentage of API call limit used.
            - ``bookings_created``: Number of simulated bookings.
            - ``searches_performed``: Number of flight searches.
            - ``features_tested``: List of feature names tested.
            - ``last_activity``: Unix timestamp of most recent activity.
            - ``days_remaining``: Days left in the trial.
            - ``active``: Whether the sandbox is currently active.

            Returns None if the sandbox was not found.
        """
        sandbox = self.get_sandbox(sandbox_id)
        if not sandbox:
            return None

        usage = sandbox["usage"].copy()
        limit = usage.get("api_call_limit", DEFAULT_API_CALL_LIMIT)
        calls = usage.get("api_calls", 0)
        usage["usage_pct"] = round((calls / limit) * 100, 1) if limit > 0 else 0.0
        usage["days_remaining"] = max(
            0, round((sandbox["expires_at"] - time.time()) / 86400, 1)
        )
        usage["active"] = sandbox["active"]

        return usage

    def record_api_call(self, sandbox_id: str, feature: str = "") -> bool:
        """
        Record an API call against a sandbox's usage quota.

        Args:
            sandbox_id: The sandbox identifier.
            feature: Optional feature name to track (e.g., ``"flight_search"``).

        Returns:
            True if the call was recorded (sandbox active and within limits),
            False otherwise.
        """
        sandbox = self.get_sandbox(sandbox_id)
        if not sandbox or not sandbox["active"]:
            return False

        usage = sandbox["usage"]

        # Check API call limit
        if usage["api_calls"] >= usage["api_call_limit"]:
            logger.warning(
                "Sandbox %s has exceeded its API call limit (%d/%d)",
                sandbox_id,
                usage["api_calls"],
                usage["api_call_limit"],
            )
            return False

        usage["api_calls"] += 1
        usage["last_activity"] = time.time()

        if feature and feature not in usage["features_tested"]:
            usage["features_tested"].append(feature)

        self._persist(sandbox_id)
        return True

    def record_search(self, sandbox_id: str) -> bool:
        """
        Record a search operation against a sandbox.

        Args:
            sandbox_id: The sandbox identifier.

        Returns:
            True if recorded successfully.
        """
        sandbox = self._sandboxes.get(sandbox_id)
        if not sandbox:
            return False
        sandbox["usage"]["searches_performed"] += 1
        return self.record_api_call(sandbox_id, feature="flight_search")

    def record_booking(self, sandbox_id: str) -> bool:
        """
        Record a simulated booking against a sandbox.

        Args:
            sandbox_id: The sandbox identifier.

        Returns:
            True if recorded successfully.
        """
        sandbox = self._sandboxes.get(sandbox_id)
        if not sandbox:
            return False
        sandbox["usage"]["bookings_created"] += 1
        return self.record_api_call(sandbox_id, feature="booking_simulation")
