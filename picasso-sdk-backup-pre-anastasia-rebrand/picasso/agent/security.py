"""
Security — Admin auth, action classification, and audit logging.

Two tiers of action:
1. OPERATIONAL (autonomous) — Claude auto-fixes without human intervention.
   Restart services, reconnect auth, clear caches, fix config drift.
2. CODE MUTATION (admin-gated) — Requires admin auth token.
   Edit files, update dependencies, apply SDK patches, run destructive commands.

Security flow:
- At install, ADMIN_AUTH_TOKEN is generated and stored in .env
- Operational actions always allowed (daemon handles these)
- Code mutations require the token (provided by admin via CLI or dashboard)
- Every action is logged to an audit trail

MYSTES KYRIOS LLC — Confidential.
"""

import hashlib
import json
import logging
import os
import secrets
import time
from typing import Optional

logger = logging.getLogger(__name__)


# ================================================================
# ACTION CLASSIFICATION
# ================================================================

class ActionType:
    """Classifies agent actions into security tiers."""

    # Tier 1: Always allowed — no auth needed
    OPERATIONAL = "operational"

    # Tier 2: Requires admin auth token
    CODE_MUTATION = "code_mutation"

    # Tier 3: Read-only — no auth needed
    READ_ONLY = "read_only"


# Map tool names to action types
TOOL_ACTION_MAP = {
    # Booking tools — operational (no code changes)
    "search_airports": ActionType.OPERATIONAL,
    "search_flights": ActionType.OPERATIONAL,
    "get_search_results": ActionType.OPERATIONAL,
    "get_fare_rules": ActionType.OPERATIONAL,
    "get_seatmap": ActionType.OPERATIONAL,
    "book_flight": ActionType.OPERATIONAL,
    "search_bookings": ActionType.OPERATIONAL,
    "generate_document": ActionType.OPERATIONAL,
    "search_profiles": ActionType.OPERATIONAL,
    "get_shopping_cart": ActionType.OPERATIONAL,

    # File operations — read vs write
    "read_file": ActionType.READ_ONLY,
    "search_code": ActionType.READ_ONLY,
    "list_files": ActionType.READ_ONLY,
    "write_file": ActionType.CODE_MUTATION,
    "edit_file": ActionType.CODE_MUTATION,
    "run_command": ActionType.CODE_MUTATION,  # Elevated to mutation (commands can change state)

    # Diagnostics — read-only
    "diagnose_error": ActionType.READ_ONLY,
    "generate_integration_code": ActionType.READ_ONLY,
    "check_integration_health": ActionType.READ_ONLY,

    # Config — operational (API-level config, not code)
    "update_agency_config": ActionType.OPERATIONAL,
    "get_agency_config": ActionType.READ_ONLY,
    "get_sdk_version": ActionType.READ_ONLY,

    # Extras discovery — read-only
    "get_extras": ActionType.READ_ONLY,

    # Enhanced booking — operational (same as book_flight)
    "book_flight_with_extras": ActionType.OPERATIONAL,

    # Booking management — operational (agent manages bookings autonomously)
    "get_booking_details": ActionType.READ_ONLY,
    "cancel_booking": ActionType.OPERATIONAL,
    "void_ticket": ActionType.OPERATIONAL,
    "request_refund": ActionType.OPERATIONAL,
}

# Commands that are operational even in run_command context
# (auto-heal can run these without admin auth)
OPERATIONAL_COMMANDS = [
    "systemctl restart",
    "systemctl reload",
    "service restart",
    "kill -HUP",
    "pip install --upgrade picasso",
    "npm restart",
    "pm2 restart",
    "supervisorctl restart",
    "docker restart",
    "redis-cli ping",
    "curl",
    "wget",
    "python3 -c",
    "python -c",
    "pip list",
    "pip show",
    "npm list",
    "npm outdated",
    "git status",
    "git log",
    "git diff",
    "ls",
    "cat",
    "head",
    "tail",
    "df",
    "free",
    "ps",
    "top -bn1",
    "uptime",
]


def classify_action(tool_name: str, tool_input: dict = None) -> str:
    """
    Classify a tool call into an action type.

    Special case: run_command is classified based on the actual command.
    Read-only commands (ls, cat, git status) are operational.
    State-changing commands (pip install, rm, etc.) are code_mutation.
    """
    if tool_name == "run_command" and tool_input:
        cmd = tool_input.get("command", "").strip().lower()
        # Check if it's an operational command
        for safe_cmd in OPERATIONAL_COMMANDS:
            if cmd.startswith(safe_cmd.lower()):
                return ActionType.OPERATIONAL
        return ActionType.CODE_MUTATION

    return TOOL_ACTION_MAP.get(tool_name, ActionType.CODE_MUTATION)


# ================================================================
# ADMIN AUTH TOKEN
# ================================================================

def generate_admin_token() -> str:
    """Generate a cryptographically secure admin auth token."""
    return f"adm_{secrets.token_hex(24)}"


def hash_token(token: str) -> str:
    """Hash an admin token for storage (never store plaintext)."""
    return hashlib.sha256(token.encode()).hexdigest()


def verify_token(provided: str, stored_hash: str) -> bool:
    """Verify a provided token against the stored hash."""
    return hashlib.sha256(provided.encode()).hexdigest() == stored_hash


class AdminAuth:
    """
    Manages admin authentication for code mutation operations.

    Usage:
        auth = AdminAuth(token_hash="sha256_of_adm_token")

        # Check if a session is authorized
        if auth.is_authorized(session_id):
            # Allow code changes
            pass

        # Authorize a session with token
        if auth.authorize(session_id, "adm_the_actual_token"):
            # Session now authorized for 1 hour
            pass
    """

    def __init__(
        self,
        token_hash: Optional[str] = None,
        session_ttl: int = 3600,  # 1 hour default
    ):
        self.token_hash = token_hash
        self.session_ttl = session_ttl
        self._authorized_sessions: dict = {}  # session_id -> expiry timestamp

    def authorize(self, session_id: str, token: str) -> bool:
        """
        Authorize a session with the admin token.
        Returns True if token is valid.
        """
        if not self.token_hash:
            # No token configured — all sessions authorized (dev mode)
            logger.warning("No admin token configured — all code changes allowed")
            return True

        if verify_token(token, self.token_hash):
            self._authorized_sessions[session_id] = time.time() + self.session_ttl
            logger.info(f"Session {session_id[:8]}... authorized for {self.session_ttl}s")
            return True

        logger.warning(f"Failed auth attempt for session {session_id[:8]}...")
        return False

    def is_authorized(self, session_id: str) -> bool:
        """Check if a session has active admin authorization."""
        if not self.token_hash:
            return True  # No token = dev mode

        expiry = self._authorized_sessions.get(session_id)
        if expiry and time.time() < expiry:
            return True

        # Clean expired
        if expiry:
            del self._authorized_sessions[session_id]
        return False

    def revoke(self, session_id: str):
        """Revoke a session's authorization."""
        self._authorized_sessions.pop(session_id, None)

    def cleanup(self):
        """Remove expired authorizations."""
        now = time.time()
        expired = [s for s, exp in self._authorized_sessions.items() if now >= exp]
        for s in expired:
            del self._authorized_sessions[s]


# ================================================================
# AUDIT LOG
# ================================================================

class AuditLog:
    """
    Records every action the agent takes for admin review.

    Stored as a JSON-lines file in the project root.
    """

    def __init__(self, log_dir: str = ".mystes"):
        self.log_dir = log_dir
        os.makedirs(log_dir, exist_ok=True)
        self.log_path = os.path.join(log_dir, "audit.jsonl")

    def record(
        self,
        action_type: str,
        tool_name: str,
        tool_input: dict,
        result_success: bool,
        session_id: Optional[str] = None,
        triggered_by: str = "user",  # "user", "daemon", "system"
        notes: Optional[str] = None,
    ):
        """Record an action to the audit log."""
        entry = {
            "timestamp": time.time(),
            "iso_time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "action_type": action_type,
            "tool": tool_name,
            "input_summary": self._summarize_input(tool_name, tool_input),
            "success": result_success,
            "session_id": session_id[:12] + "..." if session_id else None,
            "triggered_by": triggered_by,
            "notes": notes,
        }

        try:
            with open(self.log_path, "a") as f:
                f.write(json.dumps(entry, default=str) + "\n")
        except Exception as e:
            logger.error(f"Audit log write failed: {e}")

    def _summarize_input(self, tool_name: str, tool_input: dict) -> str:
        """Create a safe summary of tool input (no secrets)."""
        if tool_name == "read_file":
            return f"read {tool_input.get('path', '?')}"
        elif tool_name == "write_file":
            return f"write {tool_input.get('path', '?')} ({len(tool_input.get('content', ''))} chars)"
        elif tool_name == "edit_file":
            return f"edit {tool_input.get('path', '?')}"
        elif tool_name == "run_command":
            return tool_input.get("command", "?")[:100]
        elif tool_name == "search_code":
            return f"search '{tool_input.get('pattern', '?')}'"
        elif tool_name == "search_flights":
            return f"{tool_input.get('origin', '?')}->{tool_input.get('destination', '?')} {tool_input.get('departure_date', '?')}"
        elif tool_name == "update_agency_config":
            return f"update {tool_input.get('section', '?')}: {list(tool_input.get('updates', {}).keys())}"
        elif tool_name == "diagnose_error":
            return tool_input.get("error_text", "?")[:80]
        else:
            return str(tool_input)[:100]

    def get_recent(self, count: int = 50) -> list:
        """Get the most recent audit entries."""
        if not os.path.exists(self.log_path):
            return []

        entries = []
        try:
            with open(self.log_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        entries.append(json.loads(line))
        except Exception as e:
            logger.error(f"Audit log read failed: {e}")
            return []

        return entries[-count:]

    def get_mutations(self, count: int = 20) -> list:
        """Get recent code mutation actions only."""
        all_entries = self.get_recent(200)
        mutations = [e for e in all_entries if e.get("action_type") == ActionType.CODE_MUTATION]
        return mutations[-count:]

    def get_daemon_actions(self, count: int = 20) -> list:
        """Get recent daemon/auto-heal actions only."""
        all_entries = self.get_recent(200)
        daemon = [e for e in all_entries if e.get("triggered_by") == "daemon"]
        return daemon[-count:]
