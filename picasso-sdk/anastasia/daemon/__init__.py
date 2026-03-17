"""
ANASTASiA Daemon -- Local executor for customer infrastructure.

The Daemon neuron is the on-premise agent that runs inside a customer's
environment. It provides:

- **Executor**: Permission-checked file I/O, shell commands, git operations,
  test execution, and diff/patch application with automatic backups.
- **Protocol**: TLS-secured communication with ANASTASiA Cloud for receiving
  instructions, reporting results, heartbeats, and license verification.
- **Permissions**: Scoped access control with permanent blocklists for
  sensitive files, dangerous commands, and system directories.
- **CLI**: Command-line interface (`anastasia`) for initializing, connecting,
  monitoring, and managing the daemon.

Security model: The daemon NEVER executes operations autonomously. All changes
are proposed by ANASTASiA Cloud, approved by customer admins, and only then
executed by the daemon. Every operation is permission-checked and audited.

MYSTES KYRIOS LLC -- Confidential.
"""

import logging
import os
import time
from typing import Any, Dict, List

from ..core.events import Event, EventBus, EventType
from ..core.registry import NeuronModule
from ..core.types import ActionProposal, ApprovalStatus, TechStack

from .cli import DaemonCLI, main as cli_main
from .executor import DaemonExecutor
from .permissions import PermissionManager
from .protocol import DaemonProtocol

logger = logging.getLogger(__name__)

__all__ = [
    "DaemonModule",
    "DaemonExecutor",
    "DaemonProtocol",
    "PermissionManager",
    "DaemonCLI",
]


class DaemonModule(NeuronModule):
    """
    Daemon neuron module -- orchestrates the local execution environment.

    Wires together the executor, protocol, and permission manager into a
    cohesive module that integrates with the ANASTASiA neuron registry.
    Subscribes to proposal events and publishes daemon lifecycle events.

    Dependencies:
        - knowledge: Required for tech stack detection and system profiles.
    """

    @property
    def name(self) -> str:
        return "daemon"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def dependencies(self) -> List[str]:
        return ["knowledge"]

    def __init__(self) -> None:
        self._event_bus: EventBus = None  # type: ignore[assignment]
        self._config: Dict[str, Any] = {}
        self._executor: DaemonExecutor = None  # type: ignore[assignment]
        self._protocol: DaemonProtocol = None  # type: ignore[assignment]
        self._permissions: PermissionManager = None  # type: ignore[assignment]
        self._initialized: bool = False
        self._start_time: float = 0.0
        self._operations_completed: int = 0
        self._errors_count: int = 0

    def initialize(self, event_bus: EventBus, config: Dict[str, Any]) -> None:
        """
        Initialize the daemon module with all sub-components.

        Sets up:
        1. PermissionManager with configured access policies
        2. DaemonExecutor bound to the workspace directory
        3. DaemonProtocol for cloud communication
        4. Event subscriptions for proposal lifecycle events

        Args:
            event_bus: Shared event bus for inter-neuron communication.
            config: Configuration dict. Expected daemon-specific keys:
                - daemon.workspace: str -- workspace directory path
                - daemon.cloud_url: str -- ANASTASiA Cloud API URL
                - daemon.api_key: str -- API key for cloud auth
                - daemon.daemon_id: str -- unique daemon identifier
                - daemon.permissions: dict -- permission config
        """
        self._event_bus = event_bus
        self._config = config
        self._start_time = time.time()

        daemon_config = config.get("daemon", {})

        # 1. Initialize permission manager
        perm_config = daemon_config.get("permissions", {})
        workspace = daemon_config.get("workspace", os.getcwd())

        if not perm_config.get("allowed_directories"):
            perm_config["allowed_directories"] = [workspace]

        self._permissions = PermissionManager(perm_config)

        # 2. Initialize executor
        self._executor = DaemonExecutor(
            workspace_dir=workspace,
            permissions=self._permissions,
        )

        # 3. Initialize protocol (if cloud credentials provided)
        cloud_url = daemon_config.get("cloud_url", "")
        api_key = daemon_config.get("api_key", "")
        daemon_id = daemon_config.get("daemon_id", "")

        if cloud_url and api_key and daemon_id:
            self._protocol = DaemonProtocol(
                cloud_url=cloud_url,
                api_key=api_key,
                daemon_id=daemon_id,
            )
        else:
            logger.warning(
                "Daemon protocol not configured -- "
                "cloud_url, api_key, or daemon_id missing"
            )

        # 4. Subscribe to proposal events
        event_bus.subscribe(EventType.PROPOSAL_APPROVED, self._handle_approved_proposal)
        event_bus.subscribe(EventType.PROPOSAL_ROLLED_BACK, self._handle_rollback)

        self._initialized = True
        logger.info("DaemonModule initialized: workspace=%s", workspace)

        # Publish connected event
        event_bus.publish(Event(
            type=EventType.DAEMON_CONNECTED,
            source=self.name,
            data={
                "workspace": workspace,
                "daemon_id": daemon_id,
                "permissions": self._permissions.to_dict(),
            },
        ))

    def health_check(self) -> Dict[str, Any]:
        """
        Return daemon health status.

        Checks:
        - Module initialization state
        - Cloud connectivity (if protocol configured)
        - Workspace accessibility
        - Permission manager state

        Returns:
            Health status dict with "healthy" bool and diagnostic details.
        """
        if not self._initialized:
            return {"healthy": False, "details": "Not initialized"}

        issues: List[str] = []

        # Check workspace exists
        workspace = self._executor.workspace if self._executor else ""
        if not os.path.isdir(workspace):
            issues.append(f"Workspace not found: {workspace}")

        # Check cloud connectivity
        if self._protocol:
            health = self._protocol.connection_health()
            if health["consecutive_failures"] > 3:
                issues.append(
                    f"Cloud connectivity degraded: {health['consecutive_failures']} failures"
                )

        uptime = time.time() - self._start_time

        return {
            "healthy": len(issues) == 0,
            "details": "; ".join(issues) if issues else "All systems operational",
            "uptime_seconds": int(uptime),
            "operations_completed": self._operations_completed,
            "errors_count": self._errors_count,
            "workspace": workspace,
            "cloud_connected": (
                self._protocol.is_connected if self._protocol else False
            ),
            "permissions": self._permissions.to_dict() if self._permissions else {},
        }

    def shutdown(self) -> None:
        """
        Gracefully shutdown the daemon module.

        Disconnects from the cloud and publishes a disconnect event.
        """
        logger.info("Shutting down DaemonModule...")

        if self._protocol and self._protocol.is_connected:
            self._protocol.disconnect()

        if self._event_bus:
            self._event_bus.publish(Event(
                type=EventType.DAEMON_DISCONNECTED,
                source=self.name,
                data={
                    "uptime_seconds": int(time.time() - self._start_time),
                    "operations_completed": self._operations_completed,
                },
            ))

        self._initialized = False
        logger.info("DaemonModule shutdown complete")

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _handle_approved_proposal(self, event: Event) -> None:
        """
        Handle an approved proposal by executing it via the executor.

        Reads the proposal from the event data, executes the prescribed
        actions (file writes, diffs, commands), and reports results back
        to the cloud.

        Args:
            event: Event with proposal data in event.data.
        """
        proposal_data = event.data.get("proposal", {})
        if not proposal_data:
            logger.warning("Approved proposal event missing proposal data")
            return

        try:
            proposal = ActionProposal.from_dict(proposal_data)
        except Exception as e:
            logger.error("Failed to parse proposal from event: %s", e)
            self._errors_count += 1
            return

        logger.info("Executing approved proposal: %s (%s)",
                     proposal.id[:8], proposal.action_type)

        success = False
        output = ""

        try:
            if proposal.action_type == "file_modify" and proposal.diff:
                # Apply diff to each affected file
                results = []
                for file_path in proposal.files_affected:
                    result = self._executor.apply_diff(file_path, proposal.diff)
                    results.append(f"{file_path}: {'OK' if result else 'FAILED'}")
                success = all("OK" in r for r in results)
                output = "\n".join(results)

            elif proposal.action_type == "file_create":
                # Create files from proposal description (content in diff field)
                for file_path in proposal.files_affected:
                    self._executor.write_file(file_path, proposal.diff)
                success = True
                output = f"Created {len(proposal.files_affected)} file(s)"

            elif proposal.action_type == "config_change":
                # Execute config change commands
                result = self._executor.execute_command(proposal.description)
                success = result["exit_code"] == 0
                output = result["stdout"] + result["stderr"]

            else:
                output = f"Unknown action type: {proposal.action_type}"
                logger.warning(output)

            self._operations_completed += 1

        except PermissionError as e:
            output = f"Permission denied: {e}"
            self._errors_count += 1
            logger.error("Proposal execution denied: %s", e)
        except Exception as e:
            output = f"Execution error: {e}"
            self._errors_count += 1
            logger.exception("Proposal execution failed: %s", proposal.id[:8])

        # Report result to cloud
        if self._protocol:
            self._protocol.report_result(proposal.id, success, output)

        # Publish execution event
        self._event_bus.publish(Event(
            type=EventType.PROPOSAL_EXECUTED,
            source=self.name,
            agency_id=proposal.agency_id,
            data={
                "proposal_id": proposal.id,
                "success": success,
                "output": output[:1000],  # Truncate for event bus
            },
        ))

    def _handle_rollback(self, event: Event) -> None:
        """
        Handle a rollback request by reverting to a specified commit.

        Args:
            event: Event with rollback data (commit_sha) in event.data.
        """
        commit_sha = event.data.get("commit_sha", "")
        proposal_id = event.data.get("proposal_id", "")

        if not commit_sha:
            logger.warning("Rollback event missing commit_sha")
            return

        logger.info("Rolling back to commit %s (proposal %s)",
                     commit_sha[:8], proposal_id[:8])

        try:
            success = self._executor.rollback_to(commit_sha)
            if success:
                logger.info("Rollback successful: %s", commit_sha[:8])
            else:
                logger.error("Rollback failed: %s", commit_sha[:8])
                self._errors_count += 1

            # Report to cloud
            if self._protocol:
                self._protocol.report_result(
                    proposal_id, success,
                    f"Rollback to {commit_sha[:8]}: {'success' if success else 'failed'}",
                )
        except Exception as e:
            logger.exception("Rollback error: %s", e)
            self._errors_count += 1

    # ------------------------------------------------------------------
    # Public accessors
    # ------------------------------------------------------------------

    @property
    def executor(self) -> DaemonExecutor:
        """Access the daemon's executor instance."""
        return self._executor

    @property
    def protocol(self) -> DaemonProtocol:
        """Access the daemon's protocol instance."""
        return self._protocol

    @property
    def permissions(self) -> PermissionManager:
        """Access the daemon's permission manager."""
        return self._permissions
