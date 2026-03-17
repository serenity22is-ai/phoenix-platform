"""
Trial Manager — Lifecycle management for agency trial periods.

Handles the complete trial lifecycle: creation, monitoring, conversion
to paid plans, and expiration. Publishes events for tenant creation
and suspension to enable downstream processing (billing, notifications,
analytics).

MYSTES KYRIOS LLC — Confidential.
"""

import logging
import time
import uuid
from typing import Any, Dict, List, Optional

from ..core.events import Event, EventBus, EventType
from .environment import SandboxEnvironment

logger = logging.getLogger(__name__)

# Trial status constants
STATUS_ACTIVE = "active"
STATUS_EXPIRED = "expired"
STATUS_CONVERTED = "converted"

# Default plan for new trials
DEFAULT_TRIAL_PLAN = "pro"


class TrialManager:
    """
    Manages the full lifecycle of agency trial periods.

    A trial wraps a sandbox environment with business-level concerns:
    onboarding, credential management, conversion tracking, expiration
    handling, and analytics.

    The manager publishes events:
    - ``TENANT_CREATED`` when a trial starts (data includes trial_id,
      agency_name, sandbox_id).
    - ``TENANT_SUSPENDED`` when a trial expires (data includes trial_id,
      reason).

    Usage::

        manager = TrialManager(event_bus, sandbox_env)
        trial = manager.start_trial("Acme Travel", "admin@acme.com")
        status = manager.get_trial_status(trial["trial_id"])
        manager.convert_trial(trial["trial_id"], "professional")
    """

    def __init__(self, event_bus: EventBus, sandbox_env: SandboxEnvironment) -> None:
        """
        Initialize the trial manager.

        Args:
            event_bus: Shared event bus for publishing lifecycle events.
            sandbox_env: SandboxEnvironment instance that manages the
                         underlying sandbox infrastructure.
        """
        self._event_bus = event_bus
        self._sandbox_env = sandbox_env
        self._trials: Dict[str, dict] = {}

        logger.info("TrialManager initialized")

    def start_trial(
        self,
        agency_name: str,
        email: str,
        plan: str = DEFAULT_TRIAL_PLAN,
    ) -> dict:
        """
        Start a full trial for an agency.

        Creates a sandbox environment, generates credentials, and returns
        complete onboarding information.

        Args:
            agency_name: Display name of the agency.
            email: Primary contact email for the agency.
            plan: Plan tier for the trial — ``"pro"`` or ``"enterprise"``.
                  Defaults to ``"pro"``.

        Returns:
            A dict containing:
            - ``trial_id``: Unique trial identifier.
            - ``agency_name``: Agency display name.
            - ``email``: Contact email.
            - ``status``: Always ``"active"`` for new trials.
            - ``sandbox_id``: Associated sandbox identifier.
            - ``api_key``: Sandbox API key for authentication.
            - ``endpoints``: Available API endpoints.
            - ``plan``: Selected plan tier.
            - ``started_at``: Unix timestamp of trial start.
            - ``expires_at``: Unix timestamp of trial expiry.
            - ``days_remaining``: Number of days until expiry.
            - ``onboarding``: Dict with getting-started instructions.
        """
        agency_id = str(uuid.uuid4())[:12]
        trial_id = f"trial_{uuid.uuid4().hex[:16]}"

        # Create the underlying sandbox
        sandbox = self._sandbox_env.create_sandbox(
            agency_id=agency_id,
            plan=plan,
        )

        now = time.time()
        trial = {
            "trial_id": trial_id,
            "agency_id": agency_id,
            "agency_name": agency_name,
            "email": email,
            "plan": plan,
            "status": STATUS_ACTIVE,
            "sandbox_id": sandbox["sandbox_id"],
            "api_key": sandbox["api_key"],
            "endpoints": sandbox["endpoints"],
            "started_at": now,
            "expires_at": sandbox["expires_at"],
            "converted_at": None,
            "converted_plan": None,
            "features_tested": [],
        }

        self._trials[trial_id] = trial

        # Publish tenant creation event
        self._event_bus.publish(Event(
            type=EventType.TENANT_CREATED,
            source="sandbox",
            agency_id=agency_id,
            data={
                "trial_id": trial_id,
                "agency_name": agency_name,
                "email": email,
                "sandbox_id": sandbox["sandbox_id"],
                "plan": plan,
                "expires_at": sandbox["expires_at"],
            },
        ))

        logger.info(
            "Trial started: %s for '%s' (%s), plan=%s, sandbox=%s",
            trial_id,
            agency_name,
            email,
            plan,
            sandbox["sandbox_id"],
        )

        days_remaining = max(0, round((sandbox["expires_at"] - now) / 86400, 1))

        return {
            "trial_id": trial_id,
            "agency_name": agency_name,
            "email": email,
            "status": STATUS_ACTIVE,
            "sandbox_id": sandbox["sandbox_id"],
            "api_key": sandbox["api_key"],
            "endpoints": sandbox["endpoints"],
            "plan": plan,
            "started_at": now,
            "expires_at": sandbox["expires_at"],
            "days_remaining": days_remaining,
            "onboarding": {
                "step_1": "Use the API key to authenticate all requests.",
                "step_2": "Try a flight search: POST to the /flights/search endpoint.",
                "step_3": "Create a test booking to see the full booking flow.",
                "step_4": "Explore seatmaps and fare rules for ancillary data.",
                "step_5": "Check /usage to monitor your API call consumption.",
                "documentation": "https://docs.mystes.app/sandbox/getting-started",
                "support": "sandbox-support@mystes.app",
            },
        }

    def get_trial_status(self, trial_id: str) -> Optional[dict]:
        """
        Get the current status of a trial.

        Checks sandbox state and updates trial status if the sandbox
        has expired since last check.

        Args:
            trial_id: The trial identifier.

        Returns:
            A dict containing:
            - ``trial_id``: Trial identifier.
            - ``status``: ``"active"``, ``"expired"``, or ``"converted"``.
            - ``days_remaining``: Days left (0 if expired/converted).
            - ``usage_pct``: Percentage of API call limit consumed.
            - ``features_tested``: List of feature names the agency tried.
            - ``agency_name``: Agency display name.
            - ``plan``: Plan tier.

            Returns None if the trial was not found.
        """
        trial = self._trials.get(trial_id)
        if not trial:
            return None

        # Sync status with sandbox state
        sandbox_active = self._sandbox_env.is_sandbox_active(trial["sandbox_id"])
        if trial["status"] == STATUS_ACTIVE and not sandbox_active:
            trial["status"] = STATUS_EXPIRED
            self._publish_suspension(trial)

        now = time.time()
        days_remaining = 0.0
        if trial["status"] == STATUS_ACTIVE:
            days_remaining = max(0, round((trial["expires_at"] - now) / 86400, 1))

        # Get usage stats from sandbox
        usage = self._sandbox_env.get_sandbox_usage(trial["sandbox_id"])
        usage_pct = usage.get("usage_pct", 0.0) if usage else 0.0
        features_tested = usage.get("features_tested", []) if usage else []

        # Update tracked features
        trial["features_tested"] = features_tested

        return {
            "trial_id": trial_id,
            "agency_name": trial["agency_name"],
            "email": trial["email"],
            "plan": trial["plan"],
            "status": trial["status"],
            "days_remaining": days_remaining,
            "usage_pct": usage_pct,
            "features_tested": features_tested,
            "started_at": trial["started_at"],
            "expires_at": trial["expires_at"],
            "sandbox_id": trial["sandbox_id"],
        }

    def convert_trial(self, trial_id: str, paid_plan: str) -> Optional[dict]:
        """
        Convert a trial to a paid plan.

        Marks the trial as converted and returns the information needed
        for billing setup. The sandbox remains active so the agency can
        continue working during the transition.

        Args:
            trial_id: The trial identifier.
            paid_plan: The paid plan the agency is upgrading to
                       (e.g., ``"professional"``, ``"enterprise"``).

        Returns:
            A dict containing:
            - ``trial_id``: Trial identifier.
            - ``status``: ``"converted"``.
            - ``paid_plan``: The selected paid plan.
            - ``converted_at``: Unix timestamp of conversion.
            - ``agency_id``: Agency identifier for billing setup.
            - ``trial_duration_days``: How long the trial lasted.
            - ``billing_info``: Placeholder for billing integration.

            Returns None if the trial was not found or was already converted.
        """
        trial = self._trials.get(trial_id)
        if not trial:
            return None

        if trial["status"] == STATUS_CONVERTED:
            logger.warning("Trial %s is already converted", trial_id)
            return None

        now = time.time()
        trial["status"] = STATUS_CONVERTED
        trial["converted_at"] = now
        trial["converted_plan"] = paid_plan

        # Extend the sandbox during transition
        self._sandbox_env.extend_sandbox(trial["sandbox_id"], days=30)

        # Publish tenant upgrade event
        self._event_bus.publish(Event(
            type=EventType.TENANT_UPGRADED,
            source="sandbox",
            agency_id=trial["agency_id"],
            data={
                "trial_id": trial_id,
                "agency_name": trial["agency_name"],
                "from_plan": trial["plan"],
                "to_plan": paid_plan,
                "converted_at": now,
            },
        ))

        trial_duration = round((now - trial["started_at"]) / 86400, 1)

        logger.info(
            "Trial %s converted to '%s' after %.1f days",
            trial_id,
            paid_plan,
            trial_duration,
        )

        return {
            "trial_id": trial_id,
            "status": STATUS_CONVERTED,
            "paid_plan": paid_plan,
            "converted_at": now,
            "agency_id": trial["agency_id"],
            "agency_name": trial["agency_name"],
            "email": trial["email"],
            "trial_duration_days": trial_duration,
            "features_tested": trial["features_tested"],
            "billing_info": {
                "agency_id": trial["agency_id"],
                "plan": paid_plan,
                "setup_url": f"https://billing.mystes.app/setup/{trial['agency_id']}",
                "note": "Complete billing setup to activate production access.",
            },
        }

    def expire_trial(self, trial_id: str) -> Optional[dict]:
        """
        Manually expire a trial.

        Deactivates the sandbox and publishes a suspension event.

        Args:
            trial_id: The trial identifier.

        Returns:
            A dict with the expired trial info, or None if not found
            or already in a terminal state.
        """
        trial = self._trials.get(trial_id)
        if not trial:
            return None

        if trial["status"] in (STATUS_EXPIRED, STATUS_CONVERTED):
            logger.warning(
                "Trial %s is already %s, cannot expire", trial_id, trial["status"]
            )
            return None

        trial["status"] = STATUS_EXPIRED

        # Deactivate the sandbox
        sandbox = self._sandbox_env.get_sandbox(trial["sandbox_id"])
        if sandbox:
            sandbox["active"] = False
            self._sandbox_env._persist(trial["sandbox_id"])

        self._publish_suspension(trial)

        logger.info("Trial %s manually expired", trial_id)

        return {
            "trial_id": trial_id,
            "status": STATUS_EXPIRED,
            "agency_name": trial["agency_name"],
            "expired_at": time.time(),
        }

    def get_expiring_trials(self, days_ahead: int = 3) -> List[dict]:
        """
        Find trials expiring within the specified number of days.

        Useful for sending reminder emails to agencies before their
        trial period ends.

        Args:
            days_ahead: Number of days to look ahead. Defaults to 3.

        Returns:
            List of trial status dicts for trials expiring soon.
        """
        cutoff = time.time() + (days_ahead * 86400)
        now = time.time()
        expiring = []

        for trial_id, trial in self._trials.items():
            if trial["status"] != STATUS_ACTIVE:
                continue
            if now < trial["expires_at"] <= cutoff:
                status = self.get_trial_status(trial_id)
                if status:
                    expiring.append(status)

        expiring.sort(key=lambda t: t.get("days_remaining", 0))

        logger.info(
            "Found %d trials expiring within %d days", len(expiring), days_ahead
        )

        return expiring

    def get_trial_analytics(self) -> dict:
        """
        Compute aggregate analytics across all trials.

        Returns:
            A dict containing:
            - ``total_trials``: Total number of trials created.
            - ``active_trials``: Currently active trials.
            - ``expired_trials``: Trials that expired without converting.
            - ``converted_trials``: Trials that converted to paid.
            - ``conversion_rate``: Percentage of completed trials that converted.
            - ``avg_trial_duration_days``: Average duration of completed trials.
            - ``most_tested_features``: Feature name to usage count mapping.
            - ``plan_distribution``: Plan tier to trial count mapping.
        """
        total = len(self._trials)
        active = 0
        expired = 0
        converted = 0
        durations = []
        feature_counts: Dict[str, int] = {}
        plan_counts: Dict[str, int] = {}

        now = time.time()

        for trial in self._trials.values():
            # Refresh status
            if trial["status"] == STATUS_ACTIVE:
                if not self._sandbox_env.is_sandbox_active(trial["sandbox_id"]):
                    trial["status"] = STATUS_EXPIRED

            if trial["status"] == STATUS_ACTIVE:
                active += 1
            elif trial["status"] == STATUS_EXPIRED:
                expired += 1
                duration = (trial["expires_at"] - trial["started_at"]) / 86400
                durations.append(duration)
            elif trial["status"] == STATUS_CONVERTED:
                converted += 1
                conv_time = trial.get("converted_at", trial["expires_at"])
                duration = (conv_time - trial["started_at"]) / 86400
                durations.append(duration)

            # Feature tracking
            for feature in trial.get("features_tested", []):
                feature_counts[feature] = feature_counts.get(feature, 0) + 1

            # Plan distribution
            plan = trial.get("plan", "pro")
            plan_counts[plan] = plan_counts.get(plan, 0) + 1

        # Conversion rate: of trials that reached a terminal state
        completed = expired + converted
        conversion_rate = (
            round((converted / completed) * 100, 1) if completed > 0 else 0.0
        )
        avg_duration = round(sum(durations) / len(durations), 1) if durations else 0.0

        # Sort features by count descending
        sorted_features = dict(
            sorted(feature_counts.items(), key=lambda x: x[1], reverse=True)
        )

        return {
            "total_trials": total,
            "active_trials": active,
            "expired_trials": expired,
            "converted_trials": converted,
            "conversion_rate": conversion_rate,
            "avg_trial_duration_days": avg_duration,
            "most_tested_features": sorted_features,
            "plan_distribution": plan_counts,
        }

    def check_expired_trials(self) -> List[dict]:
        """
        Scan all active trials and mark expired ones.

        Should be called periodically (e.g., via a cron job or scheduled
        task) to ensure trials are expired promptly even if no one
        accesses them.

        Returns:
            List of trial dicts that were newly expired by this check.
        """
        newly_expired = []
        now = time.time()

        for trial_id, trial in self._trials.items():
            if trial["status"] != STATUS_ACTIVE:
                continue

            if now > trial["expires_at"]:
                trial["status"] = STATUS_EXPIRED

                # Deactivate sandbox
                sandbox = self._sandbox_env.get_sandbox(trial["sandbox_id"])
                if sandbox:
                    sandbox["active"] = False
                    self._sandbox_env._persist(trial["sandbox_id"])

                self._publish_suspension(trial)
                newly_expired.append({
                    "trial_id": trial_id,
                    "agency_name": trial["agency_name"],
                    "email": trial["email"],
                    "expired_at": now,
                    "plan": trial["plan"],
                })

                logger.info(
                    "Auto-expired trial %s for '%s'",
                    trial_id,
                    trial["agency_name"],
                )

        if newly_expired:
            logger.info("Expired %d trials in batch check", len(newly_expired))

        return newly_expired

    def _publish_suspension(self, trial: dict) -> None:
        """Publish a TENANT_SUSPENDED event for a trial."""
        self._event_bus.publish(Event(
            type=EventType.TENANT_SUSPENDED,
            source="sandbox",
            agency_id=trial["agency_id"],
            data={
                "trial_id": trial["trial_id"],
                "agency_name": trial["agency_name"],
                "email": trial["email"],
                "reason": "trial_expired",
                "plan": trial["plan"],
            },
        ))
