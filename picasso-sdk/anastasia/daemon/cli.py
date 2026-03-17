"""
Daemon CLI -- Command-line interface for the ANASTASiA Daemon.

Provides the `anastasia` CLI entry point for initializing, connecting,
monitoring, and managing the daemon on customer infrastructure. All
configuration is stored in .anastasia/config.json and activity logs
in .anastasia/daemon.log.

Usage:
    anastasia init                         # Initialize daemon in current directory
    anastasia connect <cloud-url> <api-key> # Connect to ANASTASiA Cloud
    anastasia status                       # Show connection status and activity
    anastasia permissions                  # Show current permission config
    anastasia allow-dir <path>             # Add directory to allowed list
    anastasia logs                         # Show recent activity logs
    anastasia stop                         # Gracefully stop the daemon

MYSTES KYRIOS LLC -- Confidential.
"""

import argparse
import json
import logging
import os
import signal
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .executor import DaemonExecutor
from .permissions import PermissionManager
from .protocol import DaemonProtocol

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CONFIG_DIR = ".anastasia"
CONFIG_FILE = "config.json"
LOG_FILE = "daemon.log"
PID_FILE = "daemon.pid"

DEFAULT_CONFIG: Dict[str, Any] = {
    "daemon_id": "",
    "cloud_url": "",
    "api_key": "",
    "workspace": "",
    "initialized_at": "",
    "permissions": {
        "allowed_directories": [],
        "allowed_file_types": [
            ".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".yaml", ".yml",
            ".toml", ".cfg", ".ini", ".html", ".css", ".scss", ".less",
            ".md", ".txt", ".rst", ".xml", ".sql", ".sh", ".bash",
            ".dockerfile", ".java", ".go", ".rs", ".rb", ".php",
        ],
        "allowed_commands": [
            "python", "python3", "pip", "pip3",
            "node", "npm", "npx", "yarn", "pnpm",
            "git", "make", "cargo", "go",
            "pytest", "jest", "mocha", "vitest",
            "flake8", "mypy", "eslint", "tsc",
            "docker", "docker-compose",
            "cat", "ls", "find", "grep", "wc", "head", "tail", "diff",
        ],
        "can_create_files": True,
        "can_delete_files": False,
        "can_run_tests": True,
        "command_timeout": 300,
    },
    "heartbeat_interval": 60,
    "log_level": "INFO",
}


class DaemonCLI:
    """
    Command-line interface for the ANASTASiA Daemon.

    Provides subcommands for initialization, cloud connection, status
    monitoring, permission management, and log viewing. Configuration
    is persisted in .anastasia/config.json relative to the working directory.
    """

    def __init__(self) -> None:
        self._parser = self._build_parser()
        self._config: Dict[str, Any] = {}
        self._config_dir: str = ""
        self._config_path: str = ""
        self._log_path: str = ""

    # ------------------------------------------------------------------
    # Argument parser
    # ------------------------------------------------------------------

    def _build_parser(self) -> argparse.ArgumentParser:
        """Build the argparse argument parser with all subcommands."""
        parser = argparse.ArgumentParser(
            prog="anastasia",
            description="ANASTASiA Daemon -- Local executor for customer infrastructure",
            epilog="MYSTES KYRIOS LLC -- Confidential",
        )

        parser.add_argument(
            "--version", action="version",
            version="%(prog)s 1.0.0",
        )
        parser.add_argument(
            "--verbose", "-v", action="store_true",
            help="Enable verbose (DEBUG) logging",
        )

        subparsers = parser.add_subparsers(dest="command", help="Available commands")

        # init
        init_parser = subparsers.add_parser(
            "init", help="Initialize daemon in current directory",
        )
        init_parser.add_argument(
            "--workspace", "-w", default=".",
            help="Workspace directory (default: current directory)",
        )

        # connect
        connect_parser = subparsers.add_parser(
            "connect", help="Connect to ANASTASiA Cloud",
        )
        connect_parser.add_argument("cloud_url", help="ANASTASiA Cloud API URL")
        connect_parser.add_argument("api_key", help="API key for authentication")

        # status
        subparsers.add_parser("status", help="Show connection status and recent activity")

        # permissions
        subparsers.add_parser("permissions", help="Show current permission configuration")

        # allow-dir
        allow_dir_parser = subparsers.add_parser(
            "allow-dir", help="Add directory to allowed list",
        )
        allow_dir_parser.add_argument("path", help="Directory path to allow")

        # logs
        logs_parser = subparsers.add_parser("logs", help="Show recent activity logs")
        logs_parser.add_argument(
            "--lines", "-n", type=int, default=50,
            help="Number of log lines to show (default: 50)",
        )
        logs_parser.add_argument(
            "--follow", "-f", action="store_true",
            help="Follow log output (like tail -f)",
        )

        # stop
        subparsers.add_parser("stop", help="Gracefully stop the daemon")

        return parser

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def run(self, args: Optional[List[str]] = None) -> int:
        """
        Parse arguments and dispatch to the appropriate command handler.

        Args:
            args: Command-line arguments (defaults to sys.argv[1:]).

        Returns:
            Exit code (0 for success, non-zero for failure).
        """
        parsed = self._parser.parse_args(args)

        # Configure logging
        log_level = logging.DEBUG if parsed.verbose else logging.INFO
        logging.basicConfig(
            level=log_level,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        if not parsed.command:
            self._parser.print_help()
            return 1

        # Dispatch to command handler
        handlers = {
            "init": self._cmd_init,
            "connect": self._cmd_connect,
            "status": self._cmd_status,
            "permissions": self._cmd_permissions,
            "allow-dir": self._cmd_allow_dir,
            "logs": self._cmd_logs,
            "stop": self._cmd_stop,
        }

        handler = handlers.get(parsed.command)
        if handler:
            try:
                return handler(parsed)
            except KeyboardInterrupt:
                print("\nInterrupted.")
                return 130
            except Exception as e:
                print(f"Error: {e}", file=sys.stderr)
                logger.exception("Command '%s' failed", parsed.command)
                return 1
        else:
            self._parser.print_help()
            return 1

    # ------------------------------------------------------------------
    # Command handlers
    # ------------------------------------------------------------------

    def _cmd_init(self, args: argparse.Namespace) -> int:
        """
        Initialize the daemon in the current directory.

        Creates .anastasia/ config directory with default configuration
        and generates a unique daemon ID.
        """
        workspace = os.path.abspath(args.workspace)
        self._config_dir = os.path.join(workspace, CONFIG_DIR)
        self._config_path = os.path.join(self._config_dir, CONFIG_FILE)
        self._log_path = os.path.join(self._config_dir, LOG_FILE)

        if os.path.exists(self._config_path):
            print(f"ANASTASiA daemon already initialized in {workspace}")
            print(f"Config: {self._config_path}")
            return 0

        # Create config directory
        os.makedirs(self._config_dir, exist_ok=True)

        # Generate config with unique daemon ID
        config = dict(DEFAULT_CONFIG)
        config["daemon_id"] = str(uuid.uuid4())
        config["workspace"] = workspace
        config["initialized_at"] = datetime.utcnow().isoformat() + "Z"
        config["permissions"]["allowed_directories"] = [workspace]

        # Write config
        with open(self._config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)

        # Create empty log file
        Path(self._log_path).touch()

        # Create .gitignore for .anastasia directory
        gitignore_path = os.path.join(self._config_dir, ".gitignore")
        with open(gitignore_path, "w", encoding="utf-8") as f:
            f.write("# ANASTASiA Daemon -- ignore all runtime data\n")
            f.write("*\n")
            f.write("!.gitignore\n")
            f.write("!config.json\n")

        print("ANASTASiA Daemon initialized successfully.")
        print(f"  Workspace:  {workspace}")
        print(f"  Daemon ID:  {config['daemon_id']}")
        print(f"  Config:     {self._config_path}")
        print(f"  Logs:       {self._log_path}")
        print()
        print("Next steps:")
        print("  1. anastasia connect <cloud-url> <api-key>")
        print("  2. anastasia allow-dir <path>  (optional: add more directories)")
        print("  3. anastasia status")
        return 0

    def _cmd_connect(self, args: argparse.Namespace) -> int:
        """Connect the daemon to ANASTASiA Cloud."""
        config = self._load_config()
        if config is None:
            return 1

        cloud_url = args.cloud_url.rstrip("/")
        api_key = args.api_key

        # Update config
        config["cloud_url"] = cloud_url
        config["api_key"] = api_key
        self._save_config(config)

        # Attempt connection
        protocol = DaemonProtocol(
            cloud_url=cloud_url,
            api_key=api_key,
            daemon_id=config["daemon_id"],
        )

        print(f"Connecting to {cloud_url}...")

        if protocol.connect():
            print("Connected to ANASTASiA Cloud.")

            # Verify license
            license_info = protocol.verify_license()
            if license_info.get("valid"):
                print(f"  License:  Valid ({license_info.get('tier', 'unknown')} tier)")
                print(f"  Expires:  {license_info.get('expires', 'N/A')}")
            else:
                print("  License:  Not verified (check API key)")

            protocol.disconnect()
            self._append_log("connect", f"Connected to {cloud_url}")
            return 0
        else:
            print("Failed to connect. Check your cloud URL and API key.", file=sys.stderr)
            self._append_log("connect", f"FAILED to connect to {cloud_url}")
            return 1

    def _cmd_status(self, args: argparse.Namespace) -> int:
        """Show connection status, permissions, and recent activity."""
        config = self._load_config()
        if config is None:
            return 1

        print("=" * 60)
        print("  ANASTASiA Daemon Status")
        print("=" * 60)
        print()

        # Daemon info
        print(f"  Daemon ID:     {config.get('daemon_id', 'N/A')}")
        print(f"  Workspace:     {config.get('workspace', 'N/A')}")
        print(f"  Initialized:   {config.get('initialized_at', 'N/A')}")
        print()

        # Connection info
        cloud_url = config.get("cloud_url", "")
        if cloud_url:
            print(f"  Cloud URL:     {cloud_url}")
            api_key = config.get("api_key", "")
            masked_key = f"{api_key[:8]}...{api_key[-4:]}" if len(api_key) > 12 else "***"
            print(f"  API Key:       {masked_key}")
        else:
            print("  Cloud:         Not configured (run: anastasia connect)")
        print()

        # Permissions summary
        perms = config.get("permissions", {})
        allowed_dirs = perms.get("allowed_directories", [])
        print(f"  Allowed dirs:  {len(allowed_dirs)}")
        for d in allowed_dirs[:5]:
            print(f"                 - {d}")
        if len(allowed_dirs) > 5:
            print(f"                 ... and {len(allowed_dirs) - 5} more")
        print(f"  Create files:  {perms.get('can_create_files', False)}")
        print(f"  Delete files:  {perms.get('can_delete_files', False)}")
        print(f"  Run tests:     {perms.get('can_run_tests', False)}")
        print()

        # Recent log entries
        print("  Recent Activity:")
        logs = self._read_recent_logs(10)
        if logs:
            for line in logs:
                print(f"    {line}")
        else:
            print("    No recent activity.")

        print()
        print("=" * 60)
        return 0

    def _cmd_permissions(self, args: argparse.Namespace) -> int:
        """Show the current permission configuration in detail."""
        config = self._load_config()
        if config is None:
            return 1

        perms = config.get("permissions", {})

        print("=" * 60)
        print("  ANASTASiA Daemon Permissions")
        print("=" * 60)
        print()

        # Allowed directories
        print("  Allowed Directories:")
        for d in perms.get("allowed_directories", []):
            exists = "[OK]" if os.path.isdir(d) else "[MISSING]"
            print(f"    {exists} {d}")
        if not perms.get("allowed_directories"):
            print("    (none)")
        print()

        # Allowed file types
        print("  Allowed File Types:")
        types = perms.get("allowed_file_types", [])
        # Display in columns
        cols = 8
        for i in range(0, len(types), cols):
            row = types[i:i + cols]
            print(f"    {', '.join(row)}")
        print()

        # Allowed commands
        print("  Allowed Commands:")
        commands = perms.get("allowed_commands", [])
        cols = 6
        for i in range(0, len(commands), cols):
            row = commands[i:i + cols]
            print(f"    {', '.join(row)}")
        print()

        # Capability flags
        print("  Capabilities:")
        print(f"    Create files:    {perms.get('can_create_files', False)}")
        print(f"    Delete files:    {perms.get('can_delete_files', False)}")
        print(f"    Run tests:       {perms.get('can_run_tests', False)}")
        print(f"    Command timeout: {perms.get('command_timeout', 300)}s")
        print()

        # Blocked patterns (always enforced)
        print("  Permanently Blocked Patterns:")
        print("    .env, *.pem, *.key, *.cert, credentials.json")
        print("  Permanently Blocked Directories:")
        print("    .git/objects, node_modules, __pycache__, venv")
        print("  Permanently Blocked Commands:")
        print("    rm -rf /, sudo, shutdown, reboot, kill -9, dd, mkfs")
        print()

        print("=" * 60)
        return 0

    def _cmd_allow_dir(self, args: argparse.Namespace) -> int:
        """Add a directory to the allowed list."""
        config = self._load_config()
        if config is None:
            return 1

        abs_path = os.path.abspath(args.path)

        if not os.path.isdir(abs_path):
            print(f"Error: Directory does not exist: {abs_path}", file=sys.stderr)
            return 1

        perms = config.setdefault("permissions", {})
        allowed = perms.setdefault("allowed_directories", [])

        if abs_path in allowed:
            print(f"Directory already allowed: {abs_path}")
            return 0

        allowed.append(abs_path)
        self._save_config(config)

        print(f"Added allowed directory: {abs_path}")
        self._append_log("allow-dir", f"Added: {abs_path}")
        return 0

    def _cmd_logs(self, args: argparse.Namespace) -> int:
        """Show recent activity logs."""
        config = self._load_config()
        if config is None:
            return 1

        log_path = os.path.join(self._config_dir, LOG_FILE)

        if not os.path.isfile(log_path):
            print("No log file found.")
            return 0

        if args.follow:
            print(f"Following {log_path} (Ctrl+C to stop)...")
            try:
                with open(log_path, "r", encoding="utf-8") as f:
                    # Seek to end
                    f.seek(0, 2)
                    while True:
                        line = f.readline()
                        if line:
                            print(line, end="")
                        else:
                            time.sleep(0.5)
            except KeyboardInterrupt:
                print("\nStopped.")
                return 0
        else:
            logs = self._read_recent_logs(args.lines)
            if logs:
                for line in logs:
                    print(line)
            else:
                print("No log entries.")

        return 0

    def _cmd_stop(self, args: argparse.Namespace) -> int:
        """Gracefully stop the daemon."""
        config = self._load_config()
        if config is None:
            return 1

        pid_path = os.path.join(self._config_dir, PID_FILE)

        if os.path.isfile(pid_path):
            try:
                with open(pid_path, "r") as f:
                    pid = int(f.read().strip())

                os.kill(pid, signal.SIGTERM)
                print(f"Sent SIGTERM to daemon process (PID {pid})")
                self._append_log("stop", f"Stopped daemon PID {pid}")

                # Clean up PID file
                os.unlink(pid_path)
                return 0
            except ProcessLookupError:
                print(f"Daemon process (PID {pid}) is not running. Cleaning up.")
                os.unlink(pid_path)
                return 0
            except ValueError:
                print("Invalid PID file. Removing.", file=sys.stderr)
                os.unlink(pid_path)
                return 1
        else:
            print("No daemon PID file found. Daemon may not be running.")
            return 0

    # ------------------------------------------------------------------
    # Config management
    # ------------------------------------------------------------------

    def _load_config(self) -> Optional[Dict[str, Any]]:
        """
        Load configuration from .anastasia/config.json.

        Searches the current directory and parent directories for the
        .anastasia config directory.

        Returns:
            Configuration dict, or None if not found.
        """
        # Search upward for .anastasia directory
        search_dir = os.getcwd()
        for _ in range(20):  # Max 20 levels up
            candidate = os.path.join(search_dir, CONFIG_DIR, CONFIG_FILE)
            if os.path.isfile(candidate):
                self._config_dir = os.path.join(search_dir, CONFIG_DIR)
                self._config_path = candidate
                self._log_path = os.path.join(self._config_dir, LOG_FILE)

                with open(candidate, "r", encoding="utf-8") as f:
                    self._config = json.load(f)
                return self._config

            parent = os.path.dirname(search_dir)
            if parent == search_dir:
                break
            search_dir = parent

        print(
            "Error: ANASTASiA daemon not initialized in this directory.\n"
            "Run: anastasia init",
            file=sys.stderr,
        )
        return None

    def _save_config(self, config: Dict[str, Any]) -> None:
        """Save configuration to .anastasia/config.json."""
        with open(self._config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
        self._config = config

    # ------------------------------------------------------------------
    # Logging helpers
    # ------------------------------------------------------------------

    def _append_log(self, action: str, detail: str) -> None:
        """Append an entry to the daemon log file."""
        if not self._log_path:
            return

        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        entry = f"[{timestamp}] {action}: {detail}\n"

        try:
            with open(self._log_path, "a", encoding="utf-8") as f:
                f.write(entry)
        except IOError as e:
            logger.warning("Failed to write to daemon log: %s", e)

    def _read_recent_logs(self, count: int = 50) -> List[str]:
        """Read the most recent log entries."""
        if not self._log_path or not os.path.isfile(self._log_path):
            return []

        try:
            with open(self._log_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            return [line.rstrip() for line in lines[-count:]]
        except IOError:
            return []


def main() -> None:
    """Entry point for the anastasia CLI command."""
    cli = DaemonCLI()
    sys.exit(cli.run())


if __name__ == "__main__":
    main()
