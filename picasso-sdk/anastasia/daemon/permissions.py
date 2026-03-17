"""
Permission Manager -- Scoped access control for the ANASTASiA Daemon.

Controls what the daemon can read, write, execute, and delete on customer
infrastructure. Every operation is checked against a configurable policy
before execution. All permission decisions are logged for audit compliance.

Security model: DENY by default. Only explicitly allowed paths, commands,
and file types are permitted. Sensitive files (.env, private keys, certs)
are permanently blocked regardless of configuration.

MYSTES KYRIOS LLC -- Confidential.
"""

import fnmatch
import logging
import os
import shlex
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Permanent blocklists -- cannot be overridden by configuration
# ---------------------------------------------------------------------------

PERMANENTLY_BLOCKED_PATTERNS: List[str] = [
    "*.pem",
    "*.key",
    "*.cert",
    "*.p12",
    "*.pfx",
    "*.jks",
    "*.keystore",
    ".env",
    ".env.*",
    ".env.local",
    ".env.production",
    "id_rsa",
    "id_ed25519",
    "*.secret",
    "credentials.json",
    "service-account*.json",
]

PERMANENTLY_BLOCKED_DIRS: List[str] = [
    ".git/objects",
    ".git/refs",
    ".git/logs",
    "node_modules",
    "__pycache__",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    "venv",
    ".venv",
    "env",
]

BLOCKED_COMMANDS: List[str] = [
    "rm -rf /",
    "rm -rf /*",
    "sudo",
    "shutdown",
    "reboot",
    "kill -9",
    "dd ",
    "mkfs",
    "fdisk",
    "mount",
    "umount",
    "chmod 777",
    "chown",
    "passwd",
    "useradd",
    "userdel",
    "groupadd",
    "iptables",
    "systemctl",
    "service ",
    ":(){:|:&};:",         # fork bomb
    "curl | sh",
    "curl | bash",
    "wget | sh",
    "wget | bash",
    "> /dev/sda",
    "mv / ",
]


class PermissionManager:
    """
    Scoped access control for all daemon filesystem and command operations.

    Enforces a layered permission model:
    1. Permanently blocked items (hardcoded, cannot be overridden)
    2. Configurable allowlists (directories, file types, commands)
    3. Capability flags (can_create, can_delete, can_run_tests)

    Every permission decision is logged with timestamp, path/command,
    and result (allowed/denied) for audit trail purposes.

    Args:
        config: Permission configuration dictionary with keys:
            - allowed_directories: List[str] -- directories the daemon can access
            - allowed_file_types: List[str] -- file extensions that can be modified
            - allowed_commands: List[str] -- command prefixes that are permitted
            - can_create_files: bool -- whether new files can be created
            - can_delete_files: bool -- whether files can be deleted
            - can_run_tests: bool -- whether test commands can be executed
            - command_timeout: int -- max seconds for any command execution
    """

    def __init__(self, config: Dict[str, Any]) -> None:
        self._allowed_directories: List[str] = [
            os.path.abspath(d) for d in config.get("allowed_directories", [])
        ]
        self._allowed_file_types: List[str] = config.get("allowed_file_types", [
            ".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".yaml", ".yml",
            ".toml", ".cfg", ".ini", ".html", ".css", ".scss", ".less",
            ".md", ".txt", ".rst", ".xml", ".sql", ".sh", ".bash",
            ".dockerfile", ".java", ".go", ".rs", ".rb", ".php",
            ".c", ".cpp", ".h", ".hpp", ".cs", ".swift", ".kt",
        ])
        self._allowed_commands: List[str] = config.get("allowed_commands", [
            "python", "python3", "pip", "pip3",
            "node", "npm", "npx", "yarn", "pnpm",
            "git", "make", "cargo", "go",
            "pytest", "jest", "mocha", "vitest",
            "flake8", "mypy", "eslint", "tsc",
            "docker", "docker-compose",
            "cat", "ls", "find", "grep", "wc", "head", "tail", "diff",
            "echo", "printf", "touch", "mkdir",
            "curl", "wget",
        ])
        self._can_create: bool = config.get("can_create_files", True)
        self._can_delete: bool = config.get("can_delete_files", False)
        self._can_run_tests: bool = config.get("can_run_tests", True)
        self._command_timeout: int = config.get("command_timeout", 300)

        self._audit_log: List[Dict[str, Any]] = []
        self._max_audit_entries: int = 50000

        logger.info(
            "PermissionManager initialized: %d allowed dirs, %d allowed types, "
            "create=%s, delete=%s, tests=%s",
            len(self._allowed_directories),
            len(self._allowed_file_types),
            self._can_create, self._can_delete, self._can_run_tests,
        )

    # ------------------------------------------------------------------
    # Path permissions
    # ------------------------------------------------------------------

    def is_path_allowed(self, path: str) -> bool:
        """
        Check if a filesystem path is within allowed directories.

        Resolves the path to an absolute, canonicalized form and checks it
        against allowed directories. Permanently blocked directories and
        file patterns are always denied regardless of allowlist.

        Args:
            path: The filesystem path to check (absolute or relative).

        Returns:
            True if the path is allowed for access, False otherwise.
        """
        abs_path = os.path.abspath(path)
        basename = os.path.basename(abs_path)

        # Check permanently blocked file patterns
        for pattern in PERMANENTLY_BLOCKED_PATTERNS:
            if fnmatch.fnmatch(basename, pattern):
                self._log_decision("path_check", abs_path, False, f"Blocked pattern: {pattern}")
                return False

        # Check permanently blocked directory components
        path_parts = abs_path.replace("\\", "/").split("/")
        for blocked_dir in PERMANENTLY_BLOCKED_DIRS:
            blocked_parts = blocked_dir.split("/")
            for i in range(len(path_parts) - len(blocked_parts) + 1):
                if path_parts[i:i + len(blocked_parts)] == blocked_parts:
                    self._log_decision("path_check", abs_path, False, f"Blocked dir: {blocked_dir}")
                    return False

        # Check against allowed directories
        if not self._allowed_directories:
            self._log_decision("path_check", abs_path, False, "No allowed directories configured")
            return False

        for allowed_dir in self._allowed_directories:
            try:
                # Use os.path.commonpath to check containment
                if abs_path.startswith(allowed_dir + os.sep) or abs_path == allowed_dir:
                    self._log_decision("path_check", abs_path, True, f"Within: {allowed_dir}")
                    return True
            except ValueError:
                continue

        self._log_decision("path_check", abs_path, False, "Outside allowed directories")
        return False

    def is_file_type_allowed(self, path: str) -> bool:
        """
        Check if a file's extension is in the modifiable types list.

        Files without extensions are denied by default. The check is
        case-insensitive.

        Args:
            path: The file path to check.

        Returns:
            True if the file type is allowed for modification, False otherwise.
        """
        abs_path = os.path.abspath(path)
        _, ext = os.path.splitext(abs_path)

        if not ext:
            # Allow Dockerfile, Makefile, etc. (no extension but valid)
            basename = os.path.basename(abs_path)
            extensionless_allowed = {
                "Dockerfile", "Makefile", "Procfile", "Gemfile",
                "Rakefile", "Vagrantfile", "Brewfile",
                ".gitignore", ".dockerignore", ".editorconfig",
                ".flake8", ".pylintrc", ".prettierrc",
            }
            allowed = basename in extensionless_allowed
            self._log_decision("file_type_check", abs_path, allowed,
                               f"No extension, basename={basename}")
            return allowed

        ext_lower = ext.lower()
        allowed = ext_lower in self._allowed_file_types
        self._log_decision("file_type_check", abs_path, allowed, f"Extension: {ext_lower}")
        return allowed

    # ------------------------------------------------------------------
    # Command permissions
    # ------------------------------------------------------------------

    def is_command_allowed(self, command: str) -> bool:
        """
        Check if a shell command is permitted for execution.

        Validates against:
        1. Permanently blocked dangerous commands
        2. Configured allowlist of command prefixes

        The command is normalized (stripped, lowered for blocklist check)
        before validation.

        Args:
            command: The full shell command string to validate.

        Returns:
            True if the command is allowed, False otherwise.
        """
        cmd_stripped = command.strip()
        cmd_lower = cmd_stripped.lower()

        # Check permanently blocked commands
        for blocked in BLOCKED_COMMANDS:
            if blocked.lower() in cmd_lower:
                self._log_decision("command_check", cmd_stripped, False,
                                   f"Blocked command pattern: {blocked}")
                return False

        # Extract the base command (first token)
        try:
            tokens = shlex.split(cmd_stripped)
            if not tokens:
                self._log_decision("command_check", cmd_stripped, False, "Empty command")
                return False
            base_cmd = os.path.basename(tokens[0])
        except ValueError:
            # shlex.split can fail on malformed strings
            base_cmd = cmd_stripped.split()[0] if cmd_stripped.split() else ""

        # Check against allowed command prefixes
        for allowed in self._allowed_commands:
            if base_cmd == allowed or base_cmd.startswith(allowed + "."):
                self._log_decision("command_check", cmd_stripped, True,
                                   f"Matched allowed: {allowed}")
                return True

        self._log_decision("command_check", cmd_stripped, False,
                           f"Base command '{base_cmd}' not in allowlist")
        return False

    # ------------------------------------------------------------------
    # Capability flags
    # ------------------------------------------------------------------

    def can_create_files(self) -> bool:
        """Check if the daemon is allowed to create new files."""
        return self._can_create

    def can_delete_files(self) -> bool:
        """Check if the daemon is allowed to delete files."""
        return self._can_delete

    def can_run_tests(self) -> bool:
        """Check if the daemon is allowed to execute test commands."""
        return self._can_run_tests

    @property
    def command_timeout(self) -> int:
        """Maximum seconds allowed for any single command execution."""
        return self._command_timeout

    # ------------------------------------------------------------------
    # Directory management
    # ------------------------------------------------------------------

    def get_allowed_directories(self) -> List[str]:
        """
        Return the list of directories the daemon is allowed to access.

        Returns:
            List of absolute directory paths.
        """
        return list(self._allowed_directories)

    def set_allowed_directories(self, dirs: List[str]) -> None:
        """
        Update the list of allowed directories.

        All paths are resolved to absolute form. Permanently blocked
        directory patterns are filtered out.

        Args:
            dirs: List of directory paths to allow.
        """
        resolved = []
        for d in dirs:
            abs_d = os.path.abspath(d)
            # Ensure we're not allowing permanently blocked dirs
            parts = abs_d.replace("\\", "/").split("/")
            blocked = False
            for blocked_dir in PERMANENTLY_BLOCKED_DIRS:
                if abs_d.endswith("/" + blocked_dir) or abs_d.endswith("\\" + blocked_dir):
                    logger.warning("Cannot allow permanently blocked directory: %s", abs_d)
                    blocked = True
                    break
            if not blocked:
                resolved.append(abs_d)

        self._allowed_directories = resolved
        logger.info("Updated allowed directories: %s", resolved)
        self._log_decision("set_allowed_dirs", str(resolved), True,
                           f"Set {len(resolved)} directories")

    def add_allowed_directory(self, directory: str) -> bool:
        """
        Add a single directory to the allowed list.

        Args:
            directory: Directory path to add.

        Returns:
            True if added successfully, False if blocked.
        """
        abs_dir = os.path.abspath(directory)
        for blocked_dir in PERMANENTLY_BLOCKED_DIRS:
            if abs_dir.endswith("/" + blocked_dir) or abs_dir.endswith("\\" + blocked_dir):
                logger.warning("Cannot allow permanently blocked directory: %s", abs_dir)
                return False

        if abs_dir not in self._allowed_directories:
            self._allowed_directories.append(abs_dir)
            logger.info("Added allowed directory: %s", abs_dir)
            self._log_decision("add_allowed_dir", abs_dir, True, "Directory added")
        return True

    # ------------------------------------------------------------------
    # Audit log
    # ------------------------------------------------------------------

    def _log_decision(self, check_type: str, target: str, allowed: bool, reason: str) -> None:
        """
        Record a permission decision in the audit log.

        Args:
            check_type: The type of check (path_check, command_check, etc.)
            target: The path or command being checked.
            allowed: Whether the operation was permitted.
            reason: Human-readable reason for the decision.
        """
        entry = {
            "timestamp": time.time(),
            "check_type": check_type,
            "target": target,
            "allowed": allowed,
            "reason": reason,
        }
        self._audit_log.append(entry)

        # Trim audit log if it exceeds maximum size
        if len(self._audit_log) > self._max_audit_entries:
            self._audit_log = self._audit_log[-self._max_audit_entries:]

        level = logging.DEBUG if allowed else logging.WARNING
        logger.log(level, "Permission %s: %s [%s] -- %s",
                   "ALLOWED" if allowed else "DENIED", check_type, target, reason)

    def get_audit_log(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Retrieve recent permission decisions from the audit log.

        Args:
            limit: Maximum number of entries to return.

        Returns:
            List of audit log entries, most recent last.
        """
        return self._audit_log[-limit:]

    def get_denied_operations(self, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Retrieve recent denied permission decisions.

        Useful for identifying misconfigured permissions or unauthorized
        access attempts.

        Args:
            limit: Maximum number of entries to return.

        Returns:
            List of denied audit log entries.
        """
        denied = [e for e in self._audit_log if not e["allowed"]]
        return denied[-limit:]

    def to_dict(self) -> Dict[str, Any]:
        """Serialize current permission configuration to a dictionary."""
        return {
            "allowed_directories": self._allowed_directories,
            "allowed_file_types": self._allowed_file_types,
            "allowed_commands": self._allowed_commands,
            "can_create_files": self._can_create,
            "can_delete_files": self._can_delete,
            "can_run_tests": self._can_run_tests,
            "command_timeout": self._command_timeout,
            "audit_entries": len(self._audit_log),
        }
