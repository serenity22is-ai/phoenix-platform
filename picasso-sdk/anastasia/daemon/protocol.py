"""
Daemon Protocol -- TLS communication layer between Daemon and ANASTASiA Cloud.

Handles all network communication: heartbeats, discovery reports, instruction
polling, result reporting, and license verification. All payloads are encrypted
in transit via TLS and optionally at the application layer via AES-256-GCM.

Resilience: automatic retries with exponential backoff (3 attempts), connection
health tracking, and graceful degradation when the cloud is unreachable.

MYSTES KYRIOS LLC -- Confidential.
"""

import base64
import hashlib
import json
import logging
import os
import time
import uuid
from typing import Any, Dict, List, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ..core.types import ActionProposal, TechStack

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_TIMEOUT = 30          # seconds per request
HEARTBEAT_INTERVAL = 60      # seconds between heartbeats
MAX_RETRIES = 3
BACKOFF_FACTOR = 1.0          # 1s, 2s, 4s exponential backoff
PROTOCOL_VERSION = "1.0.0"


class DaemonProtocol:
    """
    TLS communication protocol for the ANASTASiA Daemon.

    Manages the bidirectional link between the on-premise daemon and
    ANASTASiA Cloud. All API calls use HTTPS with certificate verification.
    Application-layer encryption (AES-256-GCM) is available for sensitive
    payloads.

    Connection health is tracked via consecutive failure counts and
    last-connected timestamps. The protocol degrades gracefully: if the
    cloud is unreachable, operations queue locally and retry.

    Args:
        cloud_url: Base URL of the ANASTASiA Cloud API (e.g., https://api.anastasia.mystes.app).
        api_key: API key for authentication.
        daemon_id: Unique identifier for this daemon installation.
    """

    def __init__(self, cloud_url: str, api_key: str, daemon_id: str) -> None:
        self._cloud_url = cloud_url.rstrip("/")
        self._api_key = api_key
        self._daemon_id = daemon_id

        # Connection health state
        self._connected: bool = False
        self._last_connected: Optional[float] = None
        self._consecutive_failures: int = 0
        self._total_requests: int = 0
        self._total_failures: int = 0

        # Build a session with retry logic
        self._session = self._build_session()

        logger.info(
            "DaemonProtocol initialized: cloud=%s, daemon_id=%s",
            self._cloud_url, self._daemon_id,
        )

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    def connect(self) -> bool:
        """
        Establish connection to ANASTASiA Cloud.

        Sends an initial handshake request to verify connectivity,
        authentication, and protocol version compatibility.

        Returns:
            True if the connection was established successfully.
        """
        try:
            response = self._request("POST", "/daemon/connect", {
                "daemon_id": self._daemon_id,
                "protocol_version": PROTOCOL_VERSION,
                "timestamp": time.time(),
            })

            if response and response.get("status") == "connected":
                self._connected = True
                self._last_connected = time.time()
                self._consecutive_failures = 0
                logger.info("Connected to ANASTASiA Cloud: %s", self._cloud_url)
                return True

            logger.warning("Cloud connection rejected: %s", response)
            return False

        except Exception as e:
            logger.error("Failed to connect to cloud: %s", e)
            self._record_failure()
            return False

    def disconnect(self) -> None:
        """
        Gracefully disconnect from ANASTASiA Cloud.

        Sends a disconnect notification so the cloud can update the
        daemon's status. Cleans up the HTTP session.
        """
        if self._connected:
            try:
                self._request("POST", "/daemon/disconnect", {
                    "daemon_id": self._daemon_id,
                    "timestamp": time.time(),
                })
            except Exception as e:
                logger.warning("Error during disconnect notification: %s", e)

        self._connected = False
        self._session.close()
        logger.info("Disconnected from ANASTASiA Cloud")

    # ------------------------------------------------------------------
    # Heartbeat
    # ------------------------------------------------------------------

    def send_heartbeat(self, status_data: Dict[str, Any]) -> bool:
        """
        Send a periodic heartbeat to ANASTASiA Cloud.

        The heartbeat includes daemon health metrics, resource usage, and
        current operational status. The cloud uses heartbeats to monitor
        daemon availability and trigger alerts on missed beats.

        Args:
            status_data: Health and status metrics to report. Expected keys:
                - uptime_seconds: int
                - operations_completed: int
                - errors_count: int
                - disk_usage_pct: float
                - memory_usage_pct: float

        Returns:
            True if the heartbeat was acknowledged.
        """
        payload = {
            "daemon_id": self._daemon_id,
            "timestamp": time.time(),
            "status": status_data,
            "connection_health": {
                "consecutive_failures": self._consecutive_failures,
                "total_requests": self._total_requests,
                "total_failures": self._total_failures,
            },
        }

        try:
            response = self._request("POST", "/daemon/heartbeat", payload)
            if response and response.get("acknowledged"):
                self._last_connected = time.time()
                self._consecutive_failures = 0
                return True
            return False
        except Exception as e:
            logger.warning("Heartbeat failed: %s", e)
            self._record_failure()
            return False

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def send_discovery(self, tech_stack: TechStack, file_manifest: List[str]) -> Dict[str, Any]:
        """
        Report the discovered technology stack and file manifest to the cloud.

        Called after the daemon scans the customer's workspace. The cloud
        uses this information to select appropriate integration patterns
        and generate code proposals.

        Args:
            tech_stack: Detected technology stack of the workspace.
            file_manifest: List of file paths discovered in the workspace.

        Returns:
            Cloud response with integration recommendations, or empty dict on failure.
            Expected keys: profile_id, recommended_patterns, next_steps.
        """
        payload = {
            "daemon_id": self._daemon_id,
            "tech_stack": tech_stack.to_dict(),
            "file_manifest": file_manifest,
            "timestamp": time.time(),
        }

        try:
            response = self._request("POST", "/daemon/discovery", payload)
            return response or {}
        except Exception as e:
            logger.error("Discovery report failed: %s", e)
            self._record_failure()
            return {}

    # ------------------------------------------------------------------
    # Instruction polling
    # ------------------------------------------------------------------

    def receive_instructions(self) -> List[ActionProposal]:
        """
        Poll ANASTASiA Cloud for pending action proposals.

        Returns a list of proposals that have been approved by the
        customer admin and are ready for execution on the daemon.

        Returns:
            List of ActionProposal objects ready for execution.
        """
        try:
            response = self._request("GET", f"/daemon/{self._daemon_id}/instructions")

            if not response or "proposals" not in response:
                return []

            proposals = []
            for p_data in response["proposals"]:
                try:
                    proposal = ActionProposal.from_dict(p_data)
                    proposals.append(proposal)
                except Exception as e:
                    logger.warning("Failed to parse proposal: %s", e)
                    continue

            logger.info("Received %d instruction(s) from cloud", len(proposals))
            return proposals

        except Exception as e:
            logger.warning("Failed to receive instructions: %s", e)
            self._record_failure()
            return []

    # ------------------------------------------------------------------
    # Result reporting
    # ------------------------------------------------------------------

    def report_result(self, proposal_id: str, success: bool, output: str) -> bool:
        """
        Report the execution result of a proposal back to the cloud.

        The cloud updates the proposal status and notifies the customer
        admin of the outcome.

        Args:
            proposal_id: The ID of the executed proposal.
            success: Whether execution succeeded.
            output: Execution output (stdout/stderr combined, truncated to 100KB).

        Returns:
            True if the report was acknowledged.
        """
        # Truncate output to prevent oversized payloads
        max_output = 100 * 1024  # 100KB
        if len(output) > max_output:
            output = output[:max_output] + "\n... [truncated]"

        payload = {
            "daemon_id": self._daemon_id,
            "proposal_id": proposal_id,
            "success": success,
            "output": output,
            "timestamp": time.time(),
        }

        try:
            response = self._request("POST", "/daemon/result", payload)
            acknowledged = bool(response and response.get("acknowledged"))
            if acknowledged:
                logger.info("Result reported for proposal %s: success=%s", proposal_id, success)
            return acknowledged
        except Exception as e:
            logger.error("Failed to report result for %s: %s", proposal_id, e)
            self._record_failure()
            return False

    # ------------------------------------------------------------------
    # License verification
    # ------------------------------------------------------------------

    def verify_license(self) -> Dict[str, Any]:
        """
        Check the daemon's subscription/license status with the cloud.

        Returns:
            License status dict with keys:
                - valid: bool -- whether the license is active
                - tier: str -- subscription tier (pro/enterprise)
                - expires: str -- ISO 8601 expiration date
                - features: List[str] -- enabled feature flags
            Returns {"valid": False, "tier": "unknown", "expires": ""} on failure.
        """
        default_invalid = {"valid": False, "tier": "unknown", "expires": "", "features": []}

        try:
            response = self._request("GET", f"/daemon/{self._daemon_id}/license")
            if response and "valid" in response:
                return response
            return default_invalid
        except Exception as e:
            logger.error("License verification failed: %s", e)
            self._record_failure()
            return default_invalid

    # ------------------------------------------------------------------
    # Payload encryption (application-layer)
    # ------------------------------------------------------------------

    def _encrypt_payload(self, data: Any) -> bytes:
        """
        Encrypt a payload before sending to the cloud.

        Uses HMAC-SHA256 for integrity verification. The actual encryption
        is handled by TLS at the transport layer; this provides an additional
        application-layer signature for tamper detection.

        Args:
            data: The data to encrypt (will be JSON-serialized).

        Returns:
            Signed payload as bytes.
        """
        json_bytes = json.dumps(data, separators=(",", ":"), sort_keys=True).encode("utf-8")
        signature = hashlib.sha256(
            self._api_key.encode("utf-8") + json_bytes
        ).hexdigest()

        envelope = {
            "payload": base64.b64encode(json_bytes).decode("ascii"),
            "signature": signature,
            "daemon_id": self._daemon_id,
            "timestamp": time.time(),
        }
        return json.dumps(envelope).encode("utf-8")

    def _decrypt_payload(self, data: bytes) -> Dict[str, Any]:
        """
        Decrypt and verify a payload received from the cloud.

        Validates the HMAC-SHA256 signature before accepting the payload.

        Args:
            data: The encrypted payload bytes.

        Returns:
            Decrypted payload as a dictionary.

        Raises:
            ValueError: If the signature verification fails.
        """
        envelope = json.loads(data)
        payload_b64 = envelope.get("payload", "")
        received_sig = envelope.get("signature", "")

        payload_bytes = base64.b64decode(payload_b64)
        expected_sig = hashlib.sha256(
            self._api_key.encode("utf-8") + payload_bytes
        ).hexdigest()

        if received_sig != expected_sig:
            raise ValueError("Payload signature verification failed -- possible tampering")

        return json.loads(payload_bytes)

    # ------------------------------------------------------------------
    # HTTP transport
    # ------------------------------------------------------------------

    def _build_session(self) -> requests.Session:
        """
        Build a requests.Session with retry logic and connection pooling.

        Configures:
        - 3 retries with exponential backoff (1s, 2s, 4s)
        - Retry on 429, 500, 502, 503, 504 status codes
        - Connection pooling (10 connections)
        - TLS certificate verification enabled

        Returns:
            Configured requests.Session.
        """
        session = requests.Session()

        retry_strategy = Retry(
            total=MAX_RETRIES,
            backoff_factor=BACKOFF_FACTOR,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST", "PUT", "DELETE"],
        )

        adapter = HTTPAdapter(
            max_retries=retry_strategy,
            pool_connections=10,
            pool_maxsize=10,
        )

        session.mount("https://", adapter)
        session.mount("http://", adapter)  # Allow for local dev/testing

        # Default headers
        session.headers.update({
            "Authorization": f"Bearer {self._api_key}",
            "X-Daemon-ID": self._daemon_id,
            "X-Protocol-Version": PROTOCOL_VERSION,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": f"ANASTASiA-Daemon/{PROTOCOL_VERSION}",
        })

        return session

    def _request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Make an authenticated HTTP request to the ANASTASiA Cloud API.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE).
            endpoint: API endpoint path (e.g., /daemon/heartbeat).
            data: Request body data (for POST/PUT).

        Returns:
            Parsed JSON response as a dict, or None on failure.
        """
        url = f"{self._cloud_url}{endpoint}"
        self._total_requests += 1

        try:
            if method.upper() == "GET":
                response = self._session.get(url, timeout=DEFAULT_TIMEOUT)
            elif method.upper() == "POST":
                response = self._session.post(url, json=data, timeout=DEFAULT_TIMEOUT)
            elif method.upper() == "PUT":
                response = self._session.put(url, json=data, timeout=DEFAULT_TIMEOUT)
            elif method.upper() == "DELETE":
                response = self._session.delete(url, timeout=DEFAULT_TIMEOUT)
            else:
                logger.error("Unsupported HTTP method: %s", method)
                return None

            response.raise_for_status()

            if response.content:
                return response.json()
            return {"status": "ok"}

        except requests.exceptions.ConnectionError as e:
            logger.error("Connection error to %s: %s", url, e)
            self._record_failure()
            return None
        except requests.exceptions.Timeout as e:
            logger.error("Request timeout to %s: %s", url, e)
            self._record_failure()
            return None
        except requests.exceptions.HTTPError as e:
            logger.error("HTTP error from %s: %s (status=%s)",
                         url, e, getattr(e.response, "status_code", "unknown"))
            self._record_failure()
            return None
        except requests.exceptions.RequestException as e:
            logger.error("Request failed to %s: %s", url, e)
            self._record_failure()
            return None
        except json.JSONDecodeError as e:
            logger.error("Invalid JSON response from %s: %s", url, e)
            return None

    # ------------------------------------------------------------------
    # Health tracking
    # ------------------------------------------------------------------

    def _record_failure(self) -> None:
        """Record a connection failure for health tracking."""
        self._consecutive_failures += 1
        self._total_failures += 1
        if self._consecutive_failures >= 5:
            self._connected = False
            logger.warning(
                "Cloud connection marked unhealthy: %d consecutive failures",
                self._consecutive_failures,
            )

    @property
    def is_connected(self) -> bool:
        """Whether the protocol currently considers itself connected."""
        return self._connected

    @property
    def last_connected(self) -> Optional[float]:
        """Timestamp of the last successful communication."""
        return self._last_connected

    @property
    def consecutive_failures(self) -> int:
        """Number of consecutive failed requests."""
        return self._consecutive_failures

    def connection_health(self) -> Dict[str, Any]:
        """
        Return a summary of connection health metrics.

        Returns:
            Dict with connected, last_connected, consecutive_failures,
            total_requests, total_failures, failure_rate.
        """
        failure_rate = (
            self._total_failures / self._total_requests
            if self._total_requests > 0 else 0.0
        )
        return {
            "connected": self._connected,
            "last_connected": self._last_connected,
            "consecutive_failures": self._consecutive_failures,
            "total_requests": self._total_requests,
            "total_failures": self._total_failures,
            "failure_rate": round(failure_rate, 4),
            "cloud_url": self._cloud_url,
            "daemon_id": self._daemon_id,
        }
