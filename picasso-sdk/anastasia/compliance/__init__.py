"""
Compliance Neuron -- Regulatory awareness, audit trails, and PII protection.

Handles PCI DSS (payment card security), GDPR (EU data protection), IATA BSP
(airline settlement), CCPA (California privacy), and PSD2 (EU payment
authentication). Provides three core capabilities:

- **RegulationEngine**: Checks data handling against regulatory requirements.
  Returns structured compliance reports with violations and recommendations.

- **ComplianceAudit**: Append-only, tamper-evident audit trail with SHA-256
  hash chain. Daily JSON log files with retention cleanup. Required for
  PCI DSS Requirement 10 and GDPR Art. 30.

- **PIIProtector**: Regex-based detection and masking of personally
  identifiable information (email, phone, credit card, SSN, passport, IP).
  Luhn-validated credit card detection. Sanitization for logging and export.

MYSTES KYRIOS LLC -- Confidential.
"""

import logging
import os
from typing import Any, Dict, List

from ..core.events import EventBus, Event, EventType
from ..core.registry import NeuronModule

from .regulations import RegulationEngine
from .audit import ComplianceAudit
from .pii import PIIProtector

logger = logging.getLogger(__name__)

__all__ = [
    "ComplianceModule",
    "RegulationEngine",
    "ComplianceAudit",
    "PIIProtector",
]


class ComplianceModule(NeuronModule):
    """
    ANASTASiA neuron module for regulatory compliance.

    Wires together the RegulationEngine, ComplianceAudit, and PIIProtector
    into a single lifecycle-managed module. No dependencies on other neurons
    -- compliance is a foundational service that other modules consume.

    Configuration keys (passed via ``config`` in ``initialize()``):
        - ``compliance_audit_dir`` (str): Directory for audit log files.
          Defaults to ``./data/compliance_audit``.
    """

    @property
    def name(self) -> str:
        return "compliance"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def dependencies(self) -> List[str]:
        return []

    def __init__(self):
        self.regulation_engine: RegulationEngine | None = None
        self.audit: ComplianceAudit | None = None
        self.pii_protector: PIIProtector | None = None
        self._event_bus: EventBus | None = None

    def initialize(self, event_bus: EventBus, config: Dict[str, Any]) -> None:
        """
        Initialize all compliance subsystems.

        Creates the RegulationEngine, ComplianceAudit (with configured
        storage directory), and PIIProtector. Subscribes to relevant
        events for automatic compliance monitoring.

        Args:
            event_bus: Shared event bus for inter-module communication.
            config: Configuration dictionary. See class docstring for keys.
        """
        self._event_bus = event_bus

        # Determine audit storage directory
        audit_dir = config.get(
            "compliance_audit_dir",
            os.path.join(".", "data", "compliance_audit"),
        )

        # Initialize subsystems
        self.regulation_engine = RegulationEngine(event_bus)
        self.audit = ComplianceAudit(event_bus, storage_dir=audit_dir)
        self.pii_protector = PIIProtector(event_bus)

        # Subscribe to payment events for automatic PCI compliance checks
        event_bus.subscribe(EventType.PAYMENT_INITIATED, self._on_payment_initiated)
        event_bus.subscribe(EventType.PAYMENT_COMPLETED, self._on_payment_completed)

        # Subscribe to booking events for IATA audit trail
        event_bus.subscribe(EventType.BOOKING_CREATED, self._on_booking_created)
        event_bus.subscribe(EventType.BOOKING_CANCELLED, self._on_booking_cancelled)
        event_bus.subscribe(EventType.BOOKING_REFUNDED, self._on_booking_refunded)

        logger.info(
            "Compliance module initialized (audit_dir=%s, regulations=%d)",
            audit_dir,
            len(RegulationEngine.REGULATIONS),
        )

    def health_check(self) -> Dict[str, Any]:
        """
        Return health status of compliance subsystems.

        Checks that audit trail is writable and hash chain is valid
        for today's log.
        """
        details = []
        healthy = True

        # Check regulation engine
        if self.regulation_engine:
            details.append(
                f"RegulationEngine: {len(RegulationEngine.REGULATIONS)} regulations loaded"
            )
        else:
            healthy = False
            details.append("RegulationEngine: NOT INITIALIZED")

        # Check audit trail
        if self.audit:
            chain_status = self.audit.verify_chain()
            if chain_status["valid"]:
                details.append(
                    f"ComplianceAudit: chain valid ({chain_status['entries_checked']} entries)"
                )
            else:
                healthy = False
                details.append(f"ComplianceAudit: CHAIN INVALID - {chain_status['error']}")
        else:
            healthy = False
            details.append("ComplianceAudit: NOT INITIALIZED")

        # Check PII protector
        if self.pii_protector:
            details.append(
                f"PIIProtector: {len(PIIProtector._PATTERNS)} detection patterns"
            )
        else:
            healthy = False
            details.append("PIIProtector: NOT INITIALIZED")

        return {
            "healthy": healthy,
            "details": "; ".join(details),
            "subsystems": {
                "regulation_engine": self.regulation_engine is not None,
                "audit": self.audit is not None,
                "pii_protector": self.pii_protector is not None,
            },
        }

    def shutdown(self) -> None:
        """Graceful shutdown. Audit log files are flushed on every write."""
        logger.info("Compliance module shutting down")

    # ------------------------------------------------------------------ #
    # Event handlers for automatic compliance monitoring                  #
    # ------------------------------------------------------------------ #

    def _on_payment_initiated(self, event: Event) -> None:
        """Auto-check payment data for PCI compliance on initiation."""
        if not self.regulation_engine or not self.audit:
            return

        data = event.data or {}

        # Run PCI DSS check
        result = self.regulation_engine.check_compliance(data, "PCI_DSS")
        if not result["compliant"]:
            logger.warning(
                "PCI DSS violation detected in payment %s: %s",
                data.get("payment_id", "unknown"),
                result["violations"],
            )

        # Audit the payment initiation
        self.audit.log_action(
            actor=data.get("user_id", "system"),
            action="payment.initiated",
            resource=f"payment:{data.get('payment_id', 'unknown')}",
            details={"amount": data.get("amount"), "currency": data.get("currency")},
            agency_id=event.agency_id,
        )

    def _on_payment_completed(self, event: Event) -> None:
        """Audit payment completion."""
        if not self.audit:
            return

        data = event.data or {}
        self.audit.log_action(
            actor=data.get("user_id", "system"),
            action="payment.completed",
            resource=f"payment:{data.get('payment_id', 'unknown')}",
            details={"amount": data.get("amount"), "currency": data.get("currency")},
            agency_id=event.agency_id,
        )

    def _on_booking_created(self, event: Event) -> None:
        """Audit booking creation (IATA BSP retention starts here)."""
        if not self.audit:
            return

        data = event.data or {}
        self.audit.log_action(
            actor=data.get("user_id", "system"),
            action="booking.created",
            resource=f"booking:{data.get('booking_id', 'unknown')}",
            details={
                "route": data.get("route"),
                "passengers": data.get("passenger_count"),
            },
            agency_id=event.agency_id,
        )

    def _on_booking_cancelled(self, event: Event) -> None:
        """Audit booking cancellation."""
        if not self.audit:
            return

        data = event.data or {}
        self.audit.log_action(
            actor=data.get("user_id", "system"),
            action="booking.cancelled",
            resource=f"booking:{data.get('booking_id', 'unknown')}",
            details={"reason": data.get("reason")},
            agency_id=event.agency_id,
        )

    def _on_booking_refunded(self, event: Event) -> None:
        """Audit booking refund (IATA BSP 30-day refund processing requirement)."""
        if not self.audit:
            return

        data = event.data or {}
        self.audit.log_action(
            actor=data.get("user_id", "system"),
            action="booking.refunded",
            resource=f"booking:{data.get('booking_id', 'unknown')}",
            details={
                "refund_amount": data.get("refund_amount"),
                "original_amount": data.get("original_amount"),
            },
            agency_id=event.agency_id,
        )
