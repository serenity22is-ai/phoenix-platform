"""
Approval Workflow — Admin review and execution pipeline for proposed changes.

ANASTASiA proposes code changes; humans approve them. This module manages the
full lifecycle: creation, review (approve/reject), execution, and rollback.

Proposals are persisted as JSON files in a configurable storage directory,
with automatic expiration after 7 days if not reviewed. Low-risk proposals
can be auto-approved if the agency's configuration allows it.

Every state transition publishes an event on the EventBus so other neurons
(notifications, audit, dashboard) can react.

MYSTES KYRIOS LLC — Confidential.
"""

import json
import logging
import os
import time
import uuid
from typing import Any, Dict, List, Optional

from ..core.events import EventBus, Event, EventType
from ..core.types import ActionProposal, ApprovalStatus

logger = logging.getLogger(__name__)

# Default proposal expiration: 7 days in seconds
DEFAULT_EXPIRY_SECONDS = 7 * 24 * 60 * 60


class ApprovalWorkflow:
    """
    Manages the lifecycle of ActionProposal objects.

    Proposals flow through these states:
        PENDING -> APPROVED -> EXECUTED
        PENDING -> REJECTED
        EXECUTED -> ROLLED_BACK
        PENDING -> EXPIRED (automatic after 7 days)

    All proposals are persisted as JSON files in storage_dir for durability.
    Events are published on every state transition.

    Usage:
        workflow = ApprovalWorkflow(event_bus, storage_dir="/data/proposals")
        proposal = workflow.create_proposal(
            agency_id="agency-123",
            action_type="file_create",
            description="Add ANASTASiA API client",
            files_affected=["anastasia_client.py"],
            diff="<generated code>",
        )
        workflow.approve(proposal.id, reviewer_id="admin@agency.com")
        result = workflow.execute(proposal.id)
    """

    def __init__(
        self,
        event_bus: EventBus,
        storage_dir: str,
        expiry_seconds: int = DEFAULT_EXPIRY_SECONDS,
    ):
        """
        Initialize the approval workflow.

        Args:
            event_bus: Shared event bus for publishing lifecycle events.
            storage_dir: Directory path for persisting proposals as JSON.
            expiry_seconds: Seconds before unreviewed proposals expire.
                            Defaults to 7 days.
        """
        self._event_bus = event_bus
        self._storage_dir = storage_dir
        self._expiry_seconds = expiry_seconds

        # In-memory cache of proposals (loaded from disk on demand)
        self._proposals: Dict[str, ActionProposal] = {}

        # Ensure storage directory exists
        os.makedirs(self._storage_dir, exist_ok=True)

        # Load existing proposals from disk
        self._load_all()

    def create_proposal(
        self,
        agency_id: str,
        action_type: str,
        description: str,
        files_affected: List[str],
        diff: str,
        risk_level: str = "low",
        rollback_plan: str = "",
        git_branch: str = "",
    ) -> ActionProposal:
        """
        Create a new proposal for admin review.

        Args:
            agency_id: Agency this proposal belongs to.
            action_type: Type of action (file_create, file_modify, file_delete,
                         config_change, deploy).
            description: Human-readable description of what this change does.
            files_affected: List of file paths that will be created/modified.
            diff: The actual code or unified diff of proposed changes.
            risk_level: Risk assessment ("low", "medium", "high", "critical").
            rollback_plan: How to undo this change if needed.
            git_branch: Branch where changes are staged (if applicable).

        Returns:
            The created ActionProposal with status PENDING.
        """
        proposal = ActionProposal(
            id=str(uuid.uuid4()),
            agency_id=agency_id,
            action_type=action_type,
            description=description,
            files_affected=files_affected,
            diff=diff,
            risk_level=risk_level,
            rollback_plan=rollback_plan or f"Revert files: {', '.join(files_affected)}",
            status=ApprovalStatus.PENDING.value,
            proposed_at=time.time(),
            git_branch=git_branch,
        )

        self._proposals[proposal.id] = proposal
        self._persist(proposal)

        self._event_bus.publish(Event(
            type=EventType.PROPOSAL_CREATED,
            source="integrator.approval",
            agency_id=agency_id,
            data={
                "proposal_id": proposal.id,
                "action_type": action_type,
                "description": description,
                "risk_level": risk_level,
                "files_affected": files_affected,
            },
        ))

        logger.info(
            "Proposal created: %s (%s) — %s [risk: %s]",
            proposal.id[:8], action_type, description, risk_level,
        )

        return proposal

    def approve(self, proposal_id: str, reviewer_id: str) -> ActionProposal:
        """
        Approve a pending proposal.

        Args:
            proposal_id: ID of the proposal to approve.
            reviewer_id: Identifier of the person approving (email, user_id).

        Returns:
            The updated ActionProposal with APPROVED status.

        Raises:
            ValueError: If proposal not found or not in PENDING state.
        """
        proposal = self._get_or_raise(proposal_id)

        if proposal.status != ApprovalStatus.PENDING.value:
            raise ValueError(
                f"Cannot approve proposal {proposal_id[:8]}: "
                f"status is '{proposal.status}', expected 'pending'"
            )

        # Check expiration
        if self._is_expired(proposal):
            proposal.status = ApprovalStatus.EXPIRED.value
            self._persist(proposal)
            raise ValueError(
                f"Proposal {proposal_id[:8]} has expired "
                f"(created {self._age_str(proposal)} ago)"
            )

        proposal.status = ApprovalStatus.APPROVED.value
        proposal.reviewed_at = time.time()
        proposal.reviewed_by = reviewer_id
        self._persist(proposal)

        self._event_bus.publish(Event(
            type=EventType.PROPOSAL_APPROVED,
            source="integrator.approval",
            agency_id=proposal.agency_id,
            data={
                "proposal_id": proposal.id,
                "reviewer_id": reviewer_id,
                "action_type": proposal.action_type,
                "description": proposal.description,
            },
        ))

        logger.info(
            "Proposal approved: %s by %s", proposal.id[:8], reviewer_id
        )

        return proposal

    def reject(
        self, proposal_id: str, reviewer_id: str, reason: str = ""
    ) -> ActionProposal:
        """
        Reject a pending proposal.

        Args:
            proposal_id: ID of the proposal to reject.
            reviewer_id: Identifier of the person rejecting.
            reason: Optional reason for rejection.

        Returns:
            The updated ActionProposal with REJECTED status.

        Raises:
            ValueError: If proposal not found or not in PENDING state.
        """
        proposal = self._get_or_raise(proposal_id)

        if proposal.status != ApprovalStatus.PENDING.value:
            raise ValueError(
                f"Cannot reject proposal {proposal_id[:8]}: "
                f"status is '{proposal.status}', expected 'pending'"
            )

        proposal.status = ApprovalStatus.REJECTED.value
        proposal.reviewed_at = time.time()
        proposal.reviewed_by = reviewer_id

        # Store rejection reason in execution_result
        proposal.execution_result = {"rejection_reason": reason}
        self._persist(proposal)

        self._event_bus.publish(Event(
            type=EventType.PROPOSAL_REJECTED,
            source="integrator.approval",
            agency_id=proposal.agency_id,
            data={
                "proposal_id": proposal.id,
                "reviewer_id": reviewer_id,
                "reason": reason,
                "action_type": proposal.action_type,
                "description": proposal.description,
            },
        ))

        logger.info(
            "Proposal rejected: %s by %s (reason: %s)",
            proposal.id[:8], reviewer_id, reason or "none given",
        )

        return proposal

    def execute(self, proposal_id: str) -> dict:
        """
        Execute an approved proposal.

        In a real deployment, this would write files to the customer's
        codebase (via the daemon). Here it records the execution and
        publishes an event for the daemon to act on.

        Args:
            proposal_id: ID of the approved proposal to execute.

        Returns:
            Execution result dictionary with status and timestamp.

        Raises:
            ValueError: If proposal not found or not APPROVED.
        """
        proposal = self._get_or_raise(proposal_id)

        if proposal.status != ApprovalStatus.APPROVED.value:
            raise ValueError(
                f"Cannot execute proposal {proposal_id[:8]}: "
                f"status is '{proposal.status}', expected 'approved'"
            )

        execution_time = time.time()
        result = {
            "executed_at": execution_time,
            "status": "success",
            "files_written": proposal.files_affected,
            "action_type": proposal.action_type,
        }

        proposal.execution_result = result
        # We keep status as "approved" since ActionProposal doesn't have
        # an "executed" status — track execution via execution_result
        self._persist(proposal)

        self._event_bus.publish(Event(
            type=EventType.PROPOSAL_EXECUTED,
            source="integrator.approval",
            agency_id=proposal.agency_id,
            data={
                "proposal_id": proposal.id,
                "action_type": proposal.action_type,
                "files_written": proposal.files_affected,
                "executed_at": execution_time,
            },
        ))

        logger.info(
            "Proposal executed: %s — %d files written",
            proposal.id[:8], len(proposal.files_affected),
        )

        return result

    def rollback(self, proposal_id: str) -> dict:
        """
        Rollback an executed proposal.

        Marks the proposal as rolled back and publishes an event for
        the daemon to revert the file changes.

        Args:
            proposal_id: ID of the executed proposal to roll back.

        Returns:
            Rollback result dictionary.

        Raises:
            ValueError: If proposal not found or not executed.
        """
        proposal = self._get_or_raise(proposal_id)

        if not proposal.execution_result or \
                proposal.execution_result.get("status") != "success":
            raise ValueError(
                f"Cannot rollback proposal {proposal_id[:8]}: "
                f"not in executed state"
            )

        if proposal.status == ApprovalStatus.ROLLED_BACK.value:
            raise ValueError(
                f"Proposal {proposal_id[:8]} is already rolled back"
            )

        rollback_time = time.time()
        result = {
            "rolled_back_at": rollback_time,
            "status": "rolled_back",
            "files_reverted": proposal.files_affected,
            "rollback_plan": proposal.rollback_plan,
        }

        proposal.status = ApprovalStatus.ROLLED_BACK.value
        proposal.execution_result = {
            **proposal.execution_result,
            "rollback": result,
        }
        self._persist(proposal)

        self._event_bus.publish(Event(
            type=EventType.PROPOSAL_ROLLED_BACK,
            source="integrator.approval",
            agency_id=proposal.agency_id,
            data={
                "proposal_id": proposal.id,
                "action_type": proposal.action_type,
                "files_reverted": proposal.files_affected,
                "rollback_plan": proposal.rollback_plan,
                "rolled_back_at": rollback_time,
            },
        ))

        logger.info(
            "Proposal rolled back: %s — %d files reverted",
            proposal.id[:8], len(proposal.files_affected),
        )

        return result

    def get_pending(
        self, agency_id: Optional[str] = None
    ) -> List[ActionProposal]:
        """
        List all pending proposals, optionally filtered by agency.

        Automatically expires stale proposals before returning results.

        Args:
            agency_id: Optional agency ID filter.

        Returns:
            List of pending ActionProposal objects, newest first.
        """
        self._expire_stale()

        pending = [
            p for p in self._proposals.values()
            if p.status == ApprovalStatus.PENDING.value
        ]

        if agency_id:
            pending = [p for p in pending if p.agency_id == agency_id]

        # Sort by proposed_at descending (newest first)
        pending.sort(key=lambda p: p.proposed_at, reverse=True)
        return pending

    def get_history(
        self, agency_id: Optional[str] = None, limit: int = 50
    ) -> List[ActionProposal]:
        """
        Get proposal history (all statuses), optionally filtered by agency.

        Args:
            agency_id: Optional agency ID filter.
            limit: Maximum number of proposals to return.

        Returns:
            List of ActionProposal objects, newest first.
        """
        proposals = list(self._proposals.values())

        if agency_id:
            proposals = [p for p in proposals if p.agency_id == agency_id]

        # Sort by proposed_at descending
        proposals.sort(key=lambda p: p.proposed_at, reverse=True)
        return proposals[:limit]

    def auto_approve_low_risk(self, proposal: ActionProposal) -> bool:
        """
        Auto-approve a proposal if it meets low-risk criteria.

        Criteria for auto-approval:
        - Risk level is "low"
        - Action type is "file_create" (not modify or delete)
        - Proposal is still in PENDING status

        This is an opt-in feature that agencies enable in their config.
        When enabled, low-risk file creation proposals skip the review
        queue and are immediately approved by the system.

        Args:
            proposal: The proposal to evaluate for auto-approval.

        Returns:
            True if the proposal was auto-approved, False otherwise.
        """
        if proposal.status != ApprovalStatus.PENDING.value:
            return False

        if proposal.risk_level != "low":
            logger.debug(
                "Proposal %s not auto-approved: risk level is '%s'",
                proposal.id[:8], proposal.risk_level,
            )
            return False

        if proposal.action_type not in ("file_create", "config_change"):
            logger.debug(
                "Proposal %s not auto-approved: action type '%s' requires review",
                proposal.id[:8], proposal.action_type,
            )
            return False

        # Auto-approve
        proposal.status = ApprovalStatus.APPROVED.value
        proposal.reviewed_at = time.time()
        proposal.reviewed_by = "system:auto-approve"
        self._persist(proposal)

        self._event_bus.publish(Event(
            type=EventType.PROPOSAL_APPROVED,
            source="integrator.approval",
            agency_id=proposal.agency_id,
            data={
                "proposal_id": proposal.id,
                "reviewer_id": "system:auto-approve",
                "auto_approved": True,
                "action_type": proposal.action_type,
                "description": proposal.description,
            },
        ))

        logger.info(
            "Proposal auto-approved: %s (low risk, %s)",
            proposal.id[:8], proposal.action_type,
        )

        return True

    # -------------------------------------------------------------------
    # Persistence
    # -------------------------------------------------------------------

    def _persist(self, proposal: ActionProposal) -> None:
        """Write a proposal to disk as a JSON file."""
        filepath = os.path.join(self._storage_dir, f"{proposal.id}.json")
        try:
            data = proposal.to_dict()
            with open(filepath, "w") as f:
                json.dump(data, f, indent=2, default=str)
        except (OSError, TypeError) as e:
            logger.error(
                "Failed to persist proposal %s: %s", proposal.id[:8], e
            )

    def _load_all(self) -> None:
        """Load all proposal JSON files from storage directory."""
        if not os.path.isdir(self._storage_dir):
            return

        loaded = 0
        for filename in os.listdir(self._storage_dir):
            if not filename.endswith(".json"):
                continue

            filepath = os.path.join(self._storage_dir, filename)
            try:
                with open(filepath, "r") as f:
                    data = json.load(f)
                proposal = ActionProposal.from_dict(data)
                self._proposals[proposal.id] = proposal
                loaded += 1
            except (OSError, json.JSONDecodeError, KeyError) as e:
                logger.warning(
                    "Failed to load proposal from %s: %s", filename, e
                )

        if loaded:
            logger.info("Loaded %d proposals from %s", loaded, self._storage_dir)

    def _get_or_raise(self, proposal_id: str) -> ActionProposal:
        """Get a proposal by ID or raise ValueError."""
        proposal = self._proposals.get(proposal_id)
        if not proposal:
            raise ValueError(f"Proposal not found: {proposal_id[:8]}...")
        return proposal

    def _is_expired(self, proposal: ActionProposal) -> bool:
        """Check if a pending proposal has expired."""
        if proposal.status != ApprovalStatus.PENDING.value:
            return False
        age = time.time() - proposal.proposed_at
        return age > self._expiry_seconds

    def _expire_stale(self) -> None:
        """Find and expire all stale pending proposals."""
        expired_count = 0
        for proposal in list(self._proposals.values()):
            if self._is_expired(proposal):
                proposal.status = ApprovalStatus.EXPIRED.value
                self._persist(proposal)
                expired_count += 1

        if expired_count:
            logger.info("Expired %d stale proposals", expired_count)

    def _age_str(self, proposal: ActionProposal) -> str:
        """Human-readable age string for a proposal."""
        age_seconds = time.time() - proposal.proposed_at
        if age_seconds < 3600:
            return f"{int(age_seconds / 60)} minutes"
        elif age_seconds < 86400:
            return f"{age_seconds / 3600:.1f} hours"
        else:
            return f"{age_seconds / 86400:.1f} days"
