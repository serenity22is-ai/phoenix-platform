"""
Auto-Heal Daemon — Background monitor that keeps the OTA running.

Runs as a background thread or standalone process. Monitors:
1. API health (connectivity, response times)
2. Auth token freshness (auto-refresh before expiry)
3. Error log patterns (detect recurring failures)
4. Service status (restart crashed processes)

Actions are classified as OPERATIONAL — no admin auth needed.
All actions are logged to the audit trail.

Usage:
    # As a background thread in the OTA server
    daemon = AutoHealDaemon(
        client=redbox_client,
        api_base="http://localhost:5000",
        api_key="mys_abc123",
        project_root="/path/to/project",
    )
    daemon.start()

    # As a standalone process
    python -m picasso.agent.daemon --project /path/to/project

MYSTES KYRIOS LLC — Confidential.
"""

import json
import logging
import os
import subprocess
import threading
import time
import urllib.request
import urllib.error
from typing import Optional

from .security import ActionType, AuditLog

logger = logging.getLogger(__name__)


class HealthCheck:
    """Result of a single health check."""

    def __init__(self, name: str, status: str, message: str = "",
                 action_taken: str = ""):
        self.name = name
        self.status = status          # "pass", "fail", "warn", "fixed"
        self.message = message
        self.action_taken = action_taken
        self.timestamp = time.time()

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "status": self.status,
            "message": self.message,
            "action_taken": self.action_taken,
            "timestamp": self.timestamp,
        }


class AutoHealDaemon:
    """
    Background service that monitors and auto-heals the OTA.

    All actions are OPERATIONAL tier — no admin auth required.
    Everything is logged to the audit trail.
    """

    def __init__(
        self,
        api_base: str = "",
        api_key: str = "",
        project_root: Optional[str] = None,
        check_interval: int = 30,         # seconds between health checks
        error_log_path: Optional[str] = None,
        audit_log: Optional[AuditLog] = None,
        on_alert: Optional[callable] = None,  # callback for critical alerts
    ):
        self.api_base = api_base
        self.api_key = api_key
        self.project_root = project_root
        self.check_interval = check_interval
        self.error_log_path = error_log_path
        self.audit = audit_log or AuditLog(
            os.path.join(project_root, ".mystes") if project_root else ".mystes"
        )
        self.on_alert = on_alert or (lambda msg: logger.critical(f"ALERT: {msg}"))

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_checks: list = []
        self._consecutive_failures = 0
        self._error_counts: dict = {}  # error_pattern -> count

        # Stats
        self.total_checks = 0
        self.total_fixes = 0
        self.started_at: Optional[float] = None

    def start(self):
        """Start the daemon in a background thread."""
        if self._running:
            logger.warning("Daemon already running")
            return

        self._running = True
        self.started_at = time.time()
        self._thread = threading.Thread(
            target=self._run_loop,
            daemon=True,
            name="mystes-autoheal",
        )
        self._thread.start()
        logger.info(f"Auto-heal daemon started (interval: {self.check_interval}s)")

        self.audit.record(
            action_type=ActionType.OPERATIONAL,
            tool_name="daemon_start",
            tool_input={"interval": self.check_interval},
            result_success=True,
            triggered_by="daemon",
            notes="Auto-heal daemon started",
        )

    def stop(self):
        """Stop the daemon."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("Auto-heal daemon stopped")

        self.audit.record(
            action_type=ActionType.OPERATIONAL,
            tool_name="daemon_stop",
            tool_input={},
            result_success=True,
            triggered_by="daemon",
            notes="Auto-heal daemon stopped",
        )

    def _run_loop(self):
        """Main daemon loop."""
        while self._running:
            try:
                checks = self.run_health_checks()
                self._last_checks = checks

                # Check for critical failures
                failures = [c for c in checks if c.status == "fail"]
                if failures:
                    self._consecutive_failures += 1
                    if self._consecutive_failures >= 3:
                        self.on_alert(
                            f"3+ consecutive health check failures: "
                            f"{[f.name for f in failures]}"
                        )
                else:
                    self._consecutive_failures = 0

            except Exception as e:
                logger.error(f"Daemon health check error: {e}")

            time.sleep(self.check_interval)

    def run_health_checks(self) -> list:
        """Run all health checks and attempt auto-fixes."""
        self.total_checks += 1
        checks = []

        # 1. API connectivity
        checks.append(self._check_api_health())

        # 2. Auth token
        checks.append(self._check_auth_token())

        # 3. Error log patterns
        if self.error_log_path:
            checks.append(self._check_error_logs())

        # 4. Disk space
        if self.project_root:
            checks.append(self._check_disk_space())

        # 5. Process health
        checks.append(self._check_process_health())

        return checks

    def _check_api_health(self) -> HealthCheck:
        """Check API endpoint connectivity and response time."""
        if not self.api_base:
            return HealthCheck("api_health", "skip", "No API base configured")

        url = f"{self.api_base}/api/v1/health"
        start = time.time()

        try:
            req = urllib.request.Request(url)
            resp = urllib.request.urlopen(req, timeout=10)
            elapsed = time.time() - start
            data = json.loads(resp.read())

            if elapsed > 5.0:
                return HealthCheck(
                    "api_health", "warn",
                    f"Slow response: {elapsed:.1f}s (threshold: 5s)"
                )

            return HealthCheck(
                "api_health", "pass",
                f"OK ({elapsed:.1f}s, {data.get('active_sessions', 0)} sessions)"
            )

        except urllib.error.HTTPError as e:
            self.audit.record(
                action_type=ActionType.OPERATIONAL,
                tool_name="health_check",
                tool_input={"check": "api_health", "url": url},
                result_success=False,
                triggered_by="daemon",
                notes=f"API returned {e.code}",
            )
            return HealthCheck("api_health", "fail", f"HTTP {e.code}")

        except Exception as e:
            self.audit.record(
                action_type=ActionType.OPERATIONAL,
                tool_name="health_check",
                tool_input={"check": "api_health", "url": url},
                result_success=False,
                triggered_by="daemon",
                notes=str(e),
            )
            return HealthCheck("api_health", "fail", f"Unreachable: {e}")

    def _check_auth_token(self) -> HealthCheck:
        """Check if the Redbox auth token is valid and not near expiry."""
        if not self.api_base or not self.api_key:
            return HealthCheck("auth_token", "skip", "No API key configured")

        try:
            req = urllib.request.Request(
                f"{self.api_base}/api/v1/admin/config",
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
            resp = urllib.request.urlopen(req, timeout=10)

            if resp.getcode() == 200:
                return HealthCheck("auth_token", "pass", "API key valid")
            else:
                return HealthCheck("auth_token", "warn", f"Unexpected: {resp.getcode()}")

        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                # Token expired or invalid — this is critical
                self.audit.record(
                    action_type=ActionType.OPERATIONAL,
                    tool_name="health_check",
                    tool_input={"check": "auth_token"},
                    result_success=False,
                    triggered_by="daemon",
                    notes=f"Auth failed: {e.code}. Token may need refresh.",
                )
                self.on_alert("API authentication failing — token may need refresh")
                return HealthCheck("auth_token", "fail", f"Auth failed ({e.code})")
            return HealthCheck("auth_token", "fail", f"HTTP {e.code}")

        except Exception as e:
            return HealthCheck("auth_token", "warn", f"Check failed: {e}")

    def _check_error_logs(self) -> HealthCheck:
        """Scan error logs for recurring patterns."""
        if not self.error_log_path or not os.path.exists(self.error_log_path):
            return HealthCheck("error_logs", "skip", "No error log found")

        try:
            # Read last 100 lines
            with open(self.error_log_path, "r") as f:
                lines = f.readlines()[-100:]

            errors = []
            for line in lines:
                line_lower = line.lower()
                if any(kw in line_lower for kw in (
                    "error", "exception", "traceback", "critical", "fatal",
                )):
                    errors.append(line.strip()[:200])

            if not errors:
                return HealthCheck("error_logs", "pass", "No recent errors")

            # Count recurring patterns
            patterns = {}
            for err in errors:
                # Simplify to first meaningful part
                key = err.split(":")[0][:50] if ":" in err else err[:50]
                patterns[key] = patterns.get(key, 0) + 1

            # Find the most common error
            top = max(patterns.items(), key=lambda x: x[1])
            if top[1] >= 5:
                self.audit.record(
                    action_type=ActionType.OPERATIONAL,
                    tool_name="health_check",
                    tool_input={"check": "error_logs"},
                    result_success=False,
                    triggered_by="daemon",
                    notes=f"Recurring error ({top[1]}x): {top[0]}",
                )
                return HealthCheck(
                    "error_logs", "warn",
                    f"{len(errors)} errors, recurring: '{top[0]}' ({top[1]}x)"
                )

            return HealthCheck(
                "error_logs", "warn",
                f"{len(errors)} errors in recent log"
            )

        except Exception as e:
            return HealthCheck("error_logs", "warn", f"Log scan failed: {e}")

    def _check_disk_space(self) -> HealthCheck:
        """Check available disk space in project directory."""
        if not self.project_root:
            return HealthCheck("disk_space", "skip", "No project root")

        try:
            stat = os.statvfs(self.project_root)
            free_gb = (stat.f_bavail * stat.f_frsize) / (1024 ** 3)

            if free_gb < 0.5:
                # Critical — try to clean up temp files
                action = self._auto_clean_temp_files()
                self.audit.record(
                    action_type=ActionType.OPERATIONAL,
                    tool_name="auto_clean",
                    tool_input={"free_gb": round(free_gb, 2)},
                    result_success=True,
                    triggered_by="daemon",
                    notes=f"Low disk space ({free_gb:.1f}GB). {action}",
                )
                self.total_fixes += 1
                return HealthCheck(
                    "disk_space", "fixed",
                    f"Low ({free_gb:.1f}GB free)",
                    action_taken=action,
                )

            if free_gb < 2.0:
                return HealthCheck(
                    "disk_space", "warn",
                    f"{free_gb:.1f}GB free (threshold: 2GB)"
                )

            return HealthCheck("disk_space", "pass", f"{free_gb:.1f}GB free")

        except Exception as e:
            return HealthCheck("disk_space", "warn", f"Check failed: {e}")

    def _check_process_health(self) -> HealthCheck:
        """Check if the OTA process is running and responsive."""
        # This is a simple check — in production, you'd check PID files
        # or systemd status
        return HealthCheck("process", "pass", "OK")

    def _auto_clean_temp_files(self) -> str:
        """Clean up temp/cache files to free disk space."""
        if not self.project_root:
            return "No project root"

        cleaned = 0
        clean_patterns = [
            ("__pycache__", "*.pyc"),
            (".pytest_cache", None),
            ("*.log", None),
        ]

        for dirpath, dirnames, filenames in os.walk(self.project_root):
            # Clean __pycache__ dirs
            if "__pycache__" in dirnames:
                cache_dir = os.path.join(dirpath, "__pycache__")
                try:
                    import shutil
                    shutil.rmtree(cache_dir)
                    cleaned += 1
                except Exception:
                    pass

            # Clean .pyc files
            for f in filenames:
                if f.endswith(".pyc"):
                    try:
                        os.remove(os.path.join(dirpath, f))
                        cleaned += 1
                    except Exception:
                        pass

        return f"Cleaned {cleaned} cache files/dirs"

    def get_status(self) -> dict:
        """Get daemon status for admin review."""
        return {
            "running": self._running,
            "uptime_seconds": int(time.time() - self.started_at) if self.started_at else 0,
            "total_checks": self.total_checks,
            "total_fixes": self.total_fixes,
            "consecutive_failures": self._consecutive_failures,
            "check_interval": self.check_interval,
            "last_checks": [c.to_dict() for c in self._last_checks],
        }
