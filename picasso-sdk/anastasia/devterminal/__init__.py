"""
DevTerminal Neuron — Developer workspace, module building, and marketplace.

The 17th neuron in the ANASTASiA network. Provides:
- Developer sessions with file ops, command execution, AI assistance
- Module scaffolding, auditing, and publishing pipeline
- Marketplace for module discovery and installation
- AI usage tracking for dev mode metering

MYSTES KYRIOS LLC — Confidential.
"""

import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..core.events import Event, EventBus, EventType
from ..core.registry import NeuronModule
from ..daemon.executor import DaemonExecutor
from ..daemon.permissions import PermissionManager
from .audit_pipeline import AuditPipeline, AuditResult
from .manifest import (
    MANIFEST_FILENAME,
    ModuleManifest,
    load_manifest,
    scaffold_module,
)
from .marketplace import Marketplace

logger = logging.getLogger(__name__)

__all__ = [
    "DevTerminalModule",
    "DevSession",
    "DevSessionManager",
]

# Default permission config for developer workspaces
DEV_PERMISSION_CONFIG = {
    "allowed_directories": ["."],
    "allowed_file_types": [
        ".py", ".js", ".ts", ".jsx", ".tsx", ".json", ".yaml", ".yml",
        ".toml", ".cfg", ".ini", ".md", ".txt", ".html", ".css", ".sql",
        ".sh", ".dockerfile", ".gitignore",
    ],
    "allowed_commands": [
        "python", "python3", "pip", "pip3", "pytest", "npm", "node",
        "git", "ls", "cat", "grep", "find", "which", "echo",
        "curl", "wget",
    ],
    "can_create_files": True,
    "can_delete_files": True,
    "can_run_tests": True,
    "command_timeout": 120,
}


@dataclass
class DevSession:
    """
    A developer session backed by a DaemonExecutor workspace.

    Wraps all DaemonExecutor capabilities with dev-specific features:
    AI usage tracking, module scaffolding, audit triggering.
    """

    session_id: str = ""
    agency_id: str = ""
    workspace_dir: str = ""
    created_at: float = 0.0
    last_active: float = 0.0
    executor: Optional[DaemonExecutor] = None

    # AI usage tracking for dev mode metering
    ai_input_tokens: int = 0
    ai_output_tokens: int = 0
    ai_requests: int = 0

    # Session metadata
    active_module: Optional[str] = None  # Currently active module name

    def to_dict(self) -> Dict[str, Any]:
        """Serialize session state for API responses."""
        return {
            "session_id": self.session_id,
            "agency_id": self.agency_id,
            "workspace_dir": self.workspace_dir,
            "created_at": self.created_at,
            "last_active": self.last_active,
            "ai_usage": {
                "input_tokens": self.ai_input_tokens,
                "output_tokens": self.ai_output_tokens,
                "requests": self.ai_requests,
                "estimated_cost_usd": self._estimated_cost(),
            },
            "active_module": self.active_module,
        }

    def _estimated_cost(self) -> float:
        """Estimate AI usage cost with 2-3x markup over Anthropic rates."""
        # Dev mode pricing: 2x Anthropic rates
        # Anthropic Opus 4.6: $0.80/M input, $4.00/M output
        # Dev mode: $2.00/M input, $10.00/M output
        input_cost = (self.ai_input_tokens / 1_000_000) * 2.00
        output_cost = (self.ai_output_tokens / 1_000_000) * 10.00
        return round(input_cost + output_cost, 4)

    def track_ai_usage(self, input_tokens: int, output_tokens: int) -> None:
        """Record AI token usage from a dev mode request."""
        self.ai_input_tokens += input_tokens
        self.ai_output_tokens += output_tokens
        self.ai_requests += 1
        self.last_active = time.time()

    def touch(self) -> None:
        """Update last active timestamp."""
        self.last_active = time.time()

    # ==================================================================
    # File Operations (delegate to executor)
    # ==================================================================

    def read_file(self, path: str) -> str:
        """Read a file from the workspace."""
        self.touch()
        return self.executor.read_file(path)

    def write_file(self, path: str, content: str) -> bool:
        """Write a file to the workspace."""
        self.touch()
        return self.executor.write_file(path, content)

    def list_directory(self, path: str = ".", recursive: bool = False) -> List[Dict]:
        """List directory contents."""
        self.touch()
        return self.executor.list_directory(path, recursive=recursive)

    def delete_file(self, path: str) -> bool:
        """Delete a file from the workspace."""
        self.touch()
        return self.executor.delete_file(path)

    def execute_command(self, cmd: str, timeout: int = 60) -> Dict[str, Any]:
        """Execute a shell command in the workspace."""
        self.touch()
        return self.executor.execute_command(cmd, timeout=timeout)

    def run_tests(self, test_command: Optional[str] = None) -> Dict[str, Any]:
        """Run the test suite."""
        self.touch()
        return self.executor.run_tests(test_command=test_command)

    # ==================================================================
    # Module Operations
    # ==================================================================

    def scaffold_module(
        self,
        name: str,
        module_type: str,
        author: str = "",
        description: str = "",
    ) -> Dict[str, str]:
        """
        Scaffold a new module in the workspace.

        Returns dict of created file paths -> descriptions.
        """
        self.touch()
        created = scaffold_module(
            name=name,
            module_type=module_type,
            workspace_dir=self.workspace_dir,
            author=author or self.agency_id,
            description=description,
        )
        self.active_module = name
        return created

    def load_module_manifest(self, module_name: Optional[str] = None) -> Optional[ModuleManifest]:
        """Load the manifest for a module in the workspace."""
        name = module_name or self.active_module
        if not name:
            return None

        manifest_path = os.path.join(self.workspace_dir, name, MANIFEST_FILENAME)
        if not os.path.isfile(manifest_path):
            return None

        return load_manifest(manifest_path)

    def get_module_dir(self, module_name: Optional[str] = None) -> Optional[str]:
        """Get the directory path for a module in the workspace."""
        name = module_name or self.active_module
        if not name:
            return None
        module_dir = os.path.join(self.workspace_dir, name)
        return module_dir if os.path.isdir(module_dir) else None


class DevSessionManager:
    """
    Manages active developer sessions.

    Each session gets its own DaemonExecutor-backed workspace.
    Sessions are ephemeral (in-memory) and cleaned up on close.
    """

    def __init__(
        self,
        event_bus: Optional[EventBus] = None,
        config: Optional[Dict[str, Any]] = None,
    ):
        self._event_bus = event_bus
        self._config = config or {}
        self._sessions: Dict[str, DevSession] = {}
        self._workspaces_dir = os.path.join(
            self._config.get("data_dir", "."),
            "dev_workspaces",
        )
        os.makedirs(self._workspaces_dir, exist_ok=True)

    def create_session(
        self,
        agency_id: str,
        workspace_dir: Optional[str] = None,
    ) -> DevSession:
        """
        Create a new developer session.

        Args:
            agency_id: Agency identifier.
            workspace_dir: Custom workspace directory.
                          If None, creates one under dev_workspaces/.

        Returns:
            New DevSession.
        """
        session_id = f"dev_{uuid.uuid4().hex[:16]}"
        now = time.time()

        # Create or use workspace
        if workspace_dir is None:
            workspace_dir = os.path.join(
                self._workspaces_dir,
                f"{agency_id}_{session_id}",
            )
        os.makedirs(workspace_dir, exist_ok=True)

        # Create executor with dev permissions
        permissions = PermissionManager(DEV_PERMISSION_CONFIG)
        executor = DaemonExecutor(
            workspace_dir=workspace_dir,
            permissions=permissions,
        )

        session = DevSession(
            session_id=session_id,
            agency_id=agency_id,
            workspace_dir=workspace_dir,
            created_at=now,
            last_active=now,
            executor=executor,
        )

        self._sessions[session_id] = session

        if self._event_bus:
            self._event_bus.publish(Event(
                type=EventType.DEV_SESSION_STARTED,
                data={
                    "session_id": session_id,
                    "agency_id": agency_id,
                    "workspace": workspace_dir,
                },
                source="devterminal",
                agency_id=agency_id,
            ))

        logger.info("Created dev session %s for agency %s", session_id, agency_id)
        return session

    def get_session(self, session_id: str) -> Optional[DevSession]:
        """Get a session by ID."""
        return self._sessions.get(session_id)

    def close_session(self, session_id: str) -> bool:
        """
        Close a session and clean up.

        Does NOT delete the workspace directory (preserves work).
        """
        session = self._sessions.pop(session_id, None)
        if not session:
            return False

        if self._event_bus:
            self._event_bus.publish(Event(
                type=EventType.DEV_SESSION_CLOSED,
                data={
                    "session_id": session_id,
                    "agency_id": session.agency_id,
                    "ai_usage": {
                        "input_tokens": session.ai_input_tokens,
                        "output_tokens": session.ai_output_tokens,
                        "requests": session.ai_requests,
                    },
                },
                source="devterminal",
                agency_id=session.agency_id,
            ))

        logger.info("Closed dev session %s", session_id)
        return True

    def list_sessions(self, agency_id: Optional[str] = None) -> List[DevSession]:
        """List active sessions, optionally filtered by agency."""
        sessions = list(self._sessions.values())
        if agency_id:
            sessions = [s for s in sessions if s.agency_id == agency_id]
        return sessions

    def active_count(self) -> int:
        """Count active sessions."""
        return len(self._sessions)


class DevTerminalModule(NeuronModule):
    """
    ANASTASiA DevTerminal Neuron — Developer workspace and module ecosystem.

    Manages:
    - Developer sessions (DaemonExecutor-backed workspaces)
    - Module scaffolding, auditing, publishing
    - Marketplace discovery and installation
    - Feedback collection
    """

    def __init__(self):
        self._event_bus: Optional[EventBus] = None
        self._config: Dict[str, Any] = {}
        self._session_manager: Optional[DevSessionManager] = None
        self._audit_pipeline: Optional[AuditPipeline] = None
        self._marketplace: Optional[Marketplace] = None
        self._feedback: List[Dict[str, Any]] = []

    @property
    def name(self) -> str:
        return "devterminal"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def dependencies(self) -> List[str]:
        return ["daemon", "compliance", "saas"]

    def initialize(self, event_bus: EventBus, config: Dict[str, Any]) -> None:
        """Initialize dev terminal components."""
        self._event_bus = event_bus
        self._config = config

        self._session_manager = DevSessionManager(event_bus, config)
        self._audit_pipeline = AuditPipeline(event_bus, config)
        self._marketplace = Marketplace(event_bus, config)

        logger.info("DevTerminal neuron initialized")

    def health_check(self) -> Dict[str, Any]:
        return {
            "healthy": True,
            "details": "DevTerminal operational",
            "active_sessions": self._session_manager.active_count() if self._session_manager else 0,
            "published_modules": self._marketplace.module_count() if self._marketplace else 0,
            "feedback_count": len(self._feedback),
        }

    def shutdown(self) -> None:
        """Graceful shutdown — close all sessions."""
        if self._session_manager:
            for session in self._session_manager.list_sessions():
                self._session_manager.close_session(session.session_id)
        logger.info("DevTerminal neuron shut down")

    # ==================================================================
    # Accessors (for API routes)
    # ==================================================================

    @property
    def session_manager(self) -> DevSessionManager:
        if not self._session_manager:
            raise RuntimeError("DevTerminal not initialized")
        return self._session_manager

    @property
    def audit_pipeline(self) -> AuditPipeline:
        if not self._audit_pipeline:
            raise RuntimeError("DevTerminal not initialized")
        return self._audit_pipeline

    @property
    def marketplace(self) -> Marketplace:
        if not self._marketplace:
            raise RuntimeError("DevTerminal not initialized")
        return self._marketplace

    # ==================================================================
    # Feedback
    # ==================================================================

    def submit_feedback(
        self,
        agency_id: str,
        feedback_type: str,
        message: str,
        metadata: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """
        Submit feedback from a developer/customer.

        Args:
            agency_id: Who submitted it.
            feedback_type: "bug", "feature", "recommendation", "integration"
            message: Feedback text.
            metadata: Optional context (module name, endpoint, etc.)

        Returns:
            Feedback entry with ID.
        """
        entry = {
            "feedback_id": f"fb_{uuid.uuid4().hex[:12]}",
            "agency_id": agency_id,
            "type": feedback_type,
            "message": message,
            "metadata": metadata or {},
            "submitted_at": time.time(),
            "status": "new",
        }

        self._feedback.append(entry)

        if self._event_bus:
            self._event_bus.publish(Event(
                type=EventType.FEEDBACK_SUBMITTED,
                data=entry,
                source="devterminal",
                agency_id=agency_id,
            ))

        logger.info("Feedback submitted: %s from %s", entry["feedback_id"], agency_id)
        return entry

    def list_feedback(
        self,
        feedback_type: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """List feedback entries with optional filtering."""
        entries = self._feedback
        if feedback_type:
            entries = [e for e in entries if e["type"] == feedback_type]
        if status:
            entries = [e for e in entries if e["status"] == status]
        return entries[-limit:]
