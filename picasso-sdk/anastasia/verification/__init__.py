"""
Verification Neuron — Bot protection and email verification gate.

Prevents proxy abuse by requiring email verification before live search
(which costs proxy bandwidth). Progressive friction model:

    Tier 0 — Browse cached prices:  Zero friction (free marketing)
    Tier 1 — Live search (proxy):   Email verification required
    Tier 2 — Booking (Scraping Browser): Email verified + card (natural friction)

Anti-bot measures:
- 6-digit verification codes (not links — harder to automate)
- Disposable email domain blocklist (30K+ domains)
- Rate limiting per email and per IP
- Auto-creates lightweight account on verification

MYSTES KYRIOS LLC — Confidential.
"""

import logging
from typing import Any, Dict, List, Optional

from ..core.events import Event, EventBus, EventType
from ..core.registry import NeuronModule
from .codes import VerificationCodeManager
from .disposable import DisposableEmailChecker

logger = logging.getLogger(__name__)

__all__ = [
    "VerificationModule",
    "VerificationCodeManager",
    "DisposableEmailChecker",
]


class VerificationModule(NeuronModule):
    """
    ANASTASiA Verification Neuron — email verification + bot protection.

    Provides:
    - 6-digit code generation and verification
    - Disposable email domain blocking
    - Rate limiting per email and IP
    - Session token generation on successful verification
    """

    def __init__(self):
        self._event_bus: Optional[EventBus] = None
        self._code_manager: Optional[VerificationCodeManager] = None
        self._disposable_checker: Optional[DisposableEmailChecker] = None
        self._codes_sent: int = 0
        self._codes_verified: int = 0
        self._codes_failed: int = 0
        self._disposable_blocked: int = 0
        self._initialized: bool = False

    @property
    def name(self) -> str:
        return "verification"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def dependencies(self) -> List[str]:
        return []  # Foundational

    def initialize(self, event_bus: EventBus, config: Dict[str, Any]) -> None:
        self._event_bus = event_bus

        self._code_manager = VerificationCodeManager(
            code_ttl_seconds=config.get("verification_code_ttl", 300),
            max_codes_per_email_per_hour=config.get(
                "verification_max_per_email", 3
            ),
            max_codes_per_ip_per_hour=config.get(
                "verification_max_per_ip", 10
            ),
        )

        self._disposable_checker = DisposableEmailChecker(
            custom_blocklist_path=config.get("verification_blocklist_path"),
        )

        self._initialized = True
        logger.info(
            "Verification neuron initialized: "
            "code_ttl=%ds, disposable_domains=%d",
            self._code_manager.code_ttl,
            self._disposable_checker.domain_count,
        )

    def health_check(self) -> Dict[str, Any]:
        if not self._initialized:
            return {"healthy": False, "details": "Not initialized"}

        return {
            "healthy": True,
            "details": (
                f"Sent: {self._codes_sent}, "
                f"verified: {self._codes_verified}, "
                f"failed: {self._codes_failed}, "
                f"blocked: {self._disposable_blocked}"
            ),
            "codes_sent": self._codes_sent,
            "codes_verified": self._codes_verified,
            "codes_failed": self._codes_failed,
            "disposable_blocked": self._disposable_blocked,
            "disposable_domains": (
                self._disposable_checker.domain_count
                if self._disposable_checker
                else 0
            ),
        }

    def shutdown(self) -> None:
        self._initialized = False
        logger.info("Verification neuron shut down")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def send_code(self, email: str, ip_address: str = "") -> Dict[str, Any]:
        """Generate and return a verification code for an email.

        IMPORTANT: This method returns the code but does NOT send the email.
        The MYSTES template layer handles email delivery via its own
        email_service.py (SendGrid/SMTP).

        Args:
            email: Email address to verify
            ip_address: Client IP for rate limiting

        Returns:
            {
                "success": True,
                "code": "123456",  # 6-digit code
                "email": "user@example.com",
                "expires_in": 300,
            }
            or
            {
                "success": False,
                "error": "disposable_email" | "rate_limited" | "invalid_email",
                "message": "Human-readable error",
            }
        """
        if not self._initialized:
            return {"success": False, "error": "not_initialized"}

        # Validate email format
        if not self._is_valid_email(email):
            return {
                "success": False,
                "error": "invalid_email",
                "message": "Please enter a valid email address.",
            }

        # Check disposable email
        if self._disposable_checker.is_disposable(email):
            self._disposable_blocked += 1

            if self._event_bus:
                self._event_bus.publish(Event(
                    type=EventType.VERIFICATION_DISPOSABLE_BLOCKED,
                    source="verification",
                    data={"email_domain": email.split("@")[-1]},
                ))

            return {
                "success": False,
                "error": "disposable_email",
                "message": "Please use a non-disposable email address.",
            }

        # Check rate limits
        rate_check = self._code_manager.check_rate_limit(email, ip_address)
        if not rate_check["allowed"]:
            return {
                "success": False,
                "error": "rate_limited",
                "message": rate_check["message"],
            }

        # Generate code
        code = self._code_manager.generate_code(email, ip_address)
        self._codes_sent += 1

        if self._event_bus:
            self._event_bus.publish(Event(
                type=EventType.VERIFICATION_CODE_SENT,
                source="verification",
                data={"email_domain": email.split("@")[-1]},
            ))

        return {
            "success": True,
            "code": code,
            "email": email,
            "expires_in": self._code_manager.code_ttl,
        }

    def verify_code(self, email: str, code: str) -> Dict[str, Any]:
        """Verify a 6-digit code.

        Args:
            email: Email address
            code: 6-digit code entered by user

        Returns:
            {
                "success": True,
                "email": "user@example.com",
                "session_token": "abc123...",  # For subsequent requests
            }
            or
            {
                "success": False,
                "error": "invalid_code" | "expired" | "not_found",
                "message": "Human-readable error",
            }
        """
        if not self._initialized:
            return {"success": False, "error": "not_initialized"}

        result = self._code_manager.verify_code(email, code)

        if result["success"]:
            self._codes_verified += 1

            if self._event_bus:
                self._event_bus.publish(Event(
                    type=EventType.VERIFICATION_CODE_VERIFIED,
                    source="verification",
                    data={"email_domain": email.split("@")[-1]},
                ))
        else:
            self._codes_failed += 1

            if self._event_bus:
                self._event_bus.publish(Event(
                    type=EventType.VERIFICATION_CODE_FAILED,
                    source="verification",
                    data={
                        "email_domain": email.split("@")[-1],
                        "reason": result.get("error"),
                    },
                ))

        return result

    def is_disposable(self, email: str) -> bool:
        """Check if an email uses a disposable domain."""
        if not self._disposable_checker:
            return False
        return self._disposable_checker.is_disposable(email)

    def _is_valid_email(self, email: str) -> bool:
        """Basic email format validation."""
        if not email or "@" not in email:
            return False
        local, domain = email.rsplit("@", 1)
        if not local or not domain or "." not in domain:
            return False
        if len(email) > 254 or len(local) > 64:
            return False
        return True
