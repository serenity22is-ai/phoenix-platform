"""
Verification Code Manager — 6-digit code generation, storage, and validation.

Codes are stored in-memory with TTL. In production, this should be backed
by Redis for multi-instance deployment. The interface is designed for easy
Redis swap (get/set with TTL).

MYSTES KYRIOS LLC — Confidential.
"""

import hashlib
import logging
import secrets
import time
from collections import defaultdict
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class VerificationCodeManager:
    """
    Generates and validates 6-digit verification codes.

    Features:
    - Cryptographically random 6-digit codes
    - TTL-based expiry (default 5 minutes)
    - Rate limiting per email and per IP
    - Session token generation on successful verification
    - In-memory storage (swap to Redis for production scaling)
    """

    def __init__(
        self,
        code_ttl_seconds: int = 300,
        max_codes_per_email_per_hour: int = 3,
        max_codes_per_ip_per_hour: int = 10,
    ):
        self._code_ttl = code_ttl_seconds
        self._max_per_email = max_codes_per_email_per_hour
        self._max_per_ip = max_codes_per_ip_per_hour

        # Storage: {email: {"code": "123456", "created_at": float, "ip": str}}
        self._pending_codes: Dict[str, Dict[str, Any]] = {}

        # Rate tracking: {email: [timestamp, ...]} and {ip: [timestamp, ...]}
        self._email_rate: Dict[str, list] = defaultdict(list)
        self._ip_rate: Dict[str, list] = defaultdict(list)

        # Verified sessions: {email: {"token": str, "verified_at": float}}
        self._verified: Dict[str, Dict[str, Any]] = {}

    @property
    def code_ttl(self) -> int:
        return self._code_ttl

    def check_rate_limit(self, email: str, ip_address: str = "") -> Dict[str, Any]:
        """Check if a code can be sent (rate limit check).

        Returns:
            {"allowed": True} or {"allowed": False, "message": "..."}
        """
        now = time.time()
        hour_ago = now - 3600
        email_lower = email.lower()

        # Check email rate
        self._email_rate[email_lower] = [
            t for t in self._email_rate[email_lower] if t > hour_ago
        ]
        if len(self._email_rate[email_lower]) >= self._max_per_email:
            return {
                "allowed": False,
                "message": "Too many verification attempts. Please try again later.",
            }

        # Check IP rate
        if ip_address:
            self._ip_rate[ip_address] = [
                t for t in self._ip_rate[ip_address] if t > hour_ago
            ]
            if len(self._ip_rate[ip_address]) >= self._max_per_ip:
                return {
                    "allowed": False,
                    "message": "Too many requests from this location. Please try again later.",
                }

        return {"allowed": True}

    def generate_code(self, email: str, ip_address: str = "") -> str:
        """Generate a 6-digit verification code.

        Stores the code with TTL. Returns the plain code for delivery.

        Args:
            email: Email address
            ip_address: Client IP for rate tracking

        Returns:
            6-digit code string (e.g., "482931")
        """
        email_lower = email.lower()
        now = time.time()

        # Generate cryptographically random 6-digit code
        code = f"{secrets.randbelow(1000000):06d}"

        # Store pending code
        self._pending_codes[email_lower] = {
            "code": code,
            "created_at": now,
            "ip": ip_address,
            "attempts": 0,
        }

        # Track rate
        self._email_rate[email_lower].append(now)
        if ip_address:
            self._ip_rate[ip_address].append(now)

        logger.debug("Verification code generated for %s", email_lower)
        return code

    def verify_code(self, email: str, code: str) -> Dict[str, Any]:
        """Verify a submitted code.

        Args:
            email: Email address
            code: 6-digit code from user

        Returns:
            {"success": True, "email": str, "session_token": str}
            or {"success": False, "error": str, "message": str}
        """
        email_lower = email.lower()
        now = time.time()

        # Clean up expired codes first
        self._cleanup_expired()

        pending = self._pending_codes.get(email_lower)
        if not pending:
            return {
                "success": False,
                "error": "not_found",
                "message": "No verification code found. Please request a new one.",
            }

        # Check expiry
        if now - pending["created_at"] > self._code_ttl:
            del self._pending_codes[email_lower]
            return {
                "success": False,
                "error": "expired",
                "message": "Verification code expired. Please request a new one.",
            }

        # Track attempts (max 5 per code to prevent brute force)
        pending["attempts"] += 1
        if pending["attempts"] > 5:
            del self._pending_codes[email_lower]
            return {
                "success": False,
                "error": "max_attempts",
                "message": "Too many incorrect attempts. Please request a new code.",
            }

        # Verify code
        if pending["code"] != code.strip():
            return {
                "success": False,
                "error": "invalid_code",
                "message": "Incorrect code. Please try again.",
            }

        # Success — generate session token
        token = secrets.token_urlsafe(32)
        self._verified[email_lower] = {
            "token": token,
            "verified_at": now,
            "ip": pending.get("ip", ""),
        }

        # Remove pending code
        del self._pending_codes[email_lower]

        logger.info("Email verified: %s", email_lower)
        return {
            "success": True,
            "email": email_lower,
            "session_token": token,
        }

    def is_verified(self, email: str, token: Optional[str] = None) -> bool:
        """Check if an email has been verified.

        Args:
            email: Email address
            token: Optional session token for additional validation

        Returns:
            True if email was verified within the last 24 hours.
        """
        email_lower = email.lower()
        entry = self._verified.get(email_lower)
        if not entry:
            return False

        # Verification valid for 24 hours
        if time.time() - entry["verified_at"] > 86400:
            del self._verified[email_lower]
            return False

        if token and entry["token"] != token:
            return False

        return True

    def _cleanup_expired(self) -> None:
        """Remove expired pending codes."""
        now = time.time()
        expired = [
            email
            for email, data in self._pending_codes.items()
            if now - data["created_at"] > self._code_ttl
        ]
        for email in expired:
            del self._pending_codes[email]


__all__ = ["VerificationCodeManager"]
