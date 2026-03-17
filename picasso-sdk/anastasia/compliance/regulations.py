"""
Regulation Engine -- Regulatory awareness for PCI DSS, GDPR, IATA BSP, CCPA, PSD2.

Maps regulatory requirements to actionable compliance checks. Each regulation
is decomposed into discrete requirements that can be validated against
operational data structures (payment flows, user records, booking data).

The engine does NOT enforce compliance at the transport layer (TLS, encryption)
-- that's the responsibility of the infrastructure. This module tracks the
*business logic* compliance: what data can be stored, how long, who accesses
it, and whether consent has been properly captured.

MYSTES KYRIOS LLC -- Confidential.
"""

import logging
import time
from typing import Any, Dict, List, Optional

from ..core.events import EventBus, Event, EventType

logger = logging.getLogger(__name__)


class RegulationEngine:
    """
    Checks data handling practices against known regulatory frameworks.

    Supports PCI DSS (payment card), GDPR (EU data protection), IATA BSP
    (airline settlement), CCPA (California privacy), and PSD2 (EU payment
    authentication). Returns structured compliance reports with violation
    details and actionable recommendations.
    """

    # ------------------------------------------------------------------ #
    # Regulation definitions                                              #
    # ------------------------------------------------------------------ #

    REGULATIONS: Dict[str, Dict[str, Any]] = {
        "PCI_DSS": {
            "full_name": "Payment Card Industry Data Security Standard",
            "version": "4.0",
            "jurisdiction": "global",
            "verticals": ["payments"],
            "requirements": [
                {
                    "id": "PCI-1",
                    "rule": "no_full_card_storage",
                    "description": "Full card numbers (PAN) must not be stored after authorization.",
                    "severity": "critical",
                    "check_fields": ["card_number", "pan", "primary_account_number"],
                },
                {
                    "id": "PCI-2",
                    "rule": "cvv_never_stored",
                    "description": "CVV/CVC/CID must never be stored under any circumstance.",
                    "severity": "critical",
                    "check_fields": ["cvv", "cvc", "cid", "security_code", "card_verification"],
                },
                {
                    "id": "PCI-3",
                    "rule": "encryption_in_transit",
                    "description": "Card data must be encrypted during transmission (TLS 1.2+).",
                    "severity": "critical",
                    "check_fields": [],
                },
                {
                    "id": "PCI-4",
                    "rule": "access_logging",
                    "description": "All access to cardholder data must be logged and auditable.",
                    "severity": "high",
                    "check_fields": [],
                },
                {
                    "id": "PCI-5",
                    "rule": "truncation_masking",
                    "description": "Displayed card numbers must be truncated (first 6 / last 4 max).",
                    "severity": "high",
                    "check_fields": ["card_number", "pan", "display_card"],
                },
                {
                    "id": "PCI-6",
                    "rule": "strong_key_management",
                    "description": "Encryption keys must be rotated and access-controlled.",
                    "severity": "high",
                    "check_fields": [],
                },
            ],
        },
        "GDPR": {
            "full_name": "General Data Protection Regulation",
            "version": "2016/679",
            "jurisdiction": "EU/EEA",
            "verticals": ["all"],
            "requirements": [
                {
                    "id": "GDPR-1",
                    "rule": "right_to_erasure",
                    "description": "Users can request deletion of all personal data (Art. 17).",
                    "severity": "critical",
                    "check_fields": [],
                },
                {
                    "id": "GDPR-2",
                    "rule": "data_portability",
                    "description": "Users can export their personal data in machine-readable format (Art. 20).",
                    "severity": "high",
                    "check_fields": [],
                },
                {
                    "id": "GDPR-3",
                    "rule": "consent_tracking",
                    "description": "Explicit consent must be obtained and recorded for data processing (Art. 6-7).",
                    "severity": "critical",
                    "check_fields": ["consent_given", "consent_timestamp", "consent_purpose"],
                },
                {
                    "id": "GDPR-4",
                    "rule": "breach_notification_72h",
                    "description": "Data breaches must be reported to supervisory authority within 72 hours (Art. 33).",
                    "severity": "critical",
                    "check_fields": [],
                },
                {
                    "id": "GDPR-5",
                    "rule": "dpo_contact",
                    "description": "A Data Protection Officer must be designated and contactable (Art. 37-39).",
                    "severity": "medium",
                    "check_fields": [],
                },
                {
                    "id": "GDPR-6",
                    "rule": "purpose_limitation",
                    "description": "Personal data must only be processed for the stated purpose (Art. 5).",
                    "severity": "high",
                    "check_fields": [],
                },
                {
                    "id": "GDPR-7",
                    "rule": "data_minimization",
                    "description": "Only collect personal data that is necessary for the purpose (Art. 5).",
                    "severity": "high",
                    "check_fields": [],
                },
                {
                    "id": "GDPR-8",
                    "rule": "right_to_access",
                    "description": "Users can request a copy of all personal data held (Art. 15).",
                    "severity": "high",
                    "check_fields": [],
                },
            ],
        },
        "IATA_BSP": {
            "full_name": "IATA Billing and Settlement Plan",
            "version": "Resolution 890",
            "jurisdiction": "global",
            "verticals": ["flights"],
            "requirements": [
                {
                    "id": "IATA-1",
                    "rule": "booking_record_retention",
                    "description": "Booking records must be retained for a minimum of 2 years.",
                    "severity": "high",
                    "retention_days": 730,
                    "check_fields": [],
                },
                {
                    "id": "IATA-2",
                    "rule": "refund_processing_timeline",
                    "description": "Refund requests must be processed within 30 days of receipt.",
                    "severity": "high",
                    "max_refund_days": 30,
                    "check_fields": [],
                },
                {
                    "id": "IATA-3",
                    "rule": "gds_compliance",
                    "description": "GDS interactions must follow IATA Resolution 787 display requirements.",
                    "severity": "medium",
                    "check_fields": [],
                },
                {
                    "id": "IATA-4",
                    "rule": "ticketing_time_limit",
                    "description": "Tickets must be issued within the time limit specified by the airline.",
                    "severity": "high",
                    "check_fields": ["ticketing_deadline", "issued_at"],
                },
                {
                    "id": "IATA-5",
                    "rule": "passenger_data_accuracy",
                    "description": "Passenger names must match travel documents exactly (IATA Resolution 830d).",
                    "severity": "critical",
                    "check_fields": ["passenger_name", "document_name"],
                },
            ],
        },
        "CCPA": {
            "full_name": "California Consumer Privacy Act",
            "version": "AB 375 / CPRA amendments",
            "jurisdiction": "US-CA",
            "verticals": ["all"],
            "requirements": [
                {
                    "id": "CCPA-1",
                    "rule": "right_to_know",
                    "description": "Consumers can request disclosure of personal information collected.",
                    "severity": "high",
                    "check_fields": [],
                },
                {
                    "id": "CCPA-2",
                    "rule": "right_to_delete",
                    "description": "Consumers can request deletion of personal information.",
                    "severity": "high",
                    "check_fields": [],
                },
                {
                    "id": "CCPA-3",
                    "rule": "right_to_opt_out",
                    "description": "Consumers can opt out of the sale of personal information.",
                    "severity": "high",
                    "check_fields": [],
                },
                {
                    "id": "CCPA-4",
                    "rule": "non_discrimination",
                    "description": "Consumers must not be discriminated against for exercising CCPA rights.",
                    "severity": "medium",
                    "check_fields": [],
                },
                {
                    "id": "CCPA-5",
                    "rule": "privacy_notice",
                    "description": "A clear privacy notice must be provided at or before collection.",
                    "severity": "high",
                    "check_fields": [],
                },
            ],
        },
        "PSD2": {
            "full_name": "Payment Services Directive 2",
            "version": "EU 2015/2366",
            "jurisdiction": "EU/EEA",
            "verticals": ["payments"],
            "requirements": [
                {
                    "id": "PSD2-1",
                    "rule": "strong_customer_authentication",
                    "description": "SCA required for electronic payments over 30 EUR (two of: knowledge, possession, inherence).",
                    "severity": "critical",
                    "check_fields": ["sca_completed", "auth_factors"],
                },
                {
                    "id": "PSD2-2",
                    "rule": "transaction_risk_analysis",
                    "description": "Real-time transaction risk analysis for SCA exemptions.",
                    "severity": "high",
                    "check_fields": [],
                },
                {
                    "id": "PSD2-3",
                    "rule": "dynamic_linking",
                    "description": "Authentication must be dynamically linked to transaction amount and payee.",
                    "severity": "critical",
                    "check_fields": ["auth_amount", "auth_payee"],
                },
                {
                    "id": "PSD2-4",
                    "rule": "open_banking_access",
                    "description": "Account information and payment initiation APIs for licensed TPPs.",
                    "severity": "medium",
                    "check_fields": [],
                },
            ],
        },
    }

    # Country-to-jurisdiction mapping for regulation applicability
    _JURISDICTION_MAP: Dict[str, List[str]] = {
        # EU/EEA countries -> GDPR + PSD2
        "AT": ["GDPR", "PSD2"], "BE": ["GDPR", "PSD2"], "BG": ["GDPR", "PSD2"],
        "HR": ["GDPR", "PSD2"], "CY": ["GDPR", "PSD2"], "CZ": ["GDPR", "PSD2"],
        "DK": ["GDPR", "PSD2"], "EE": ["GDPR", "PSD2"], "FI": ["GDPR", "PSD2"],
        "FR": ["GDPR", "PSD2"], "DE": ["GDPR", "PSD2"], "GR": ["GDPR", "PSD2"],
        "HU": ["GDPR", "PSD2"], "IE": ["GDPR", "PSD2"], "IT": ["GDPR", "PSD2"],
        "LV": ["GDPR", "PSD2"], "LT": ["GDPR", "PSD2"], "LU": ["GDPR", "PSD2"],
        "MT": ["GDPR", "PSD2"], "NL": ["GDPR", "PSD2"], "PL": ["GDPR", "PSD2"],
        "PT": ["GDPR", "PSD2"], "RO": ["GDPR", "PSD2"], "SK": ["GDPR", "PSD2"],
        "SI": ["GDPR", "PSD2"], "ES": ["GDPR", "PSD2"], "SE": ["GDPR", "PSD2"],
        # EEA non-EU
        "IS": ["GDPR", "PSD2"], "LI": ["GDPR", "PSD2"], "NO": ["GDPR", "PSD2"],
        # UK post-Brexit has its own GDPR variant, PSD2 equivalent
        "GB": ["GDPR", "PSD2"],
        # US states
        "US": ["CCPA"],  # CCPA applies broadly; state-level nuance handled at check time
    }

    def __init__(self, event_bus: EventBus):
        """
        Initialize the regulation engine.

        Args:
            event_bus: Shared event bus for publishing compliance events.
        """
        self._event_bus = event_bus
        self._check_count = 0
        self._violation_count = 0
        logger.info(
            "RegulationEngine initialized with %d regulations",
            len(self.REGULATIONS),
        )

    # ------------------------------------------------------------------ #
    # Single regulation check                                             #
    # ------------------------------------------------------------------ #

    def check_compliance(self, data: dict, regulation: str) -> dict:
        """
        Check if data handling meets a specific regulation's requirements.

        Inspects ``data`` for fields that should not be present (e.g. raw
        card numbers for PCI DSS) and for fields that must be present
        (e.g. consent timestamps for GDPR). Returns a structured report.

        Args:
            data: Dictionary of data fields to validate.
            regulation: Regulation key (e.g. ``"PCI_DSS"``, ``"GDPR"``).

        Returns:
            Dictionary with keys:
            - ``compliant`` (bool): True if no violations found.
            - ``regulation`` (str): Regulation checked.
            - ``violations`` (List[str]): Human-readable violation descriptions.
            - ``recommendations`` (List[str]): Suggested remediation steps.
            - ``requirements_checked`` (int): Number of requirements evaluated.
        """
        reg_def = self.REGULATIONS.get(regulation)
        if not reg_def:
            return {
                "compliant": False,
                "regulation": regulation,
                "violations": [f"Unknown regulation: {regulation}"],
                "recommendations": ["Use one of: " + ", ".join(self.REGULATIONS.keys())],
                "requirements_checked": 0,
            }

        violations: List[str] = []
        recommendations: List[str] = []
        data_keys = set(self._flatten_keys(data))

        for req in reg_def["requirements"]:
            rule = req["rule"]
            check_fields = req.get("check_fields", [])

            if rule == "no_full_card_storage":
                for cf in check_fields:
                    if cf in data_keys:
                        val = self._get_nested(data, cf)
                        if val and isinstance(val, str) and len(val.replace(" ", "").replace("-", "")) >= 13:
                            violations.append(
                                f"[{req['id']}] Full card number detected in field '{cf}'. "
                                f"PAN must not be stored after authorization."
                            )
                            recommendations.append(
                                "Tokenize card numbers using Stripe tokens or store only last-4."
                            )

            elif rule == "cvv_never_stored":
                for cf in check_fields:
                    if cf in data_keys:
                        val = self._get_nested(data, cf)
                        if val is not None and str(val).strip():
                            violations.append(
                                f"[{req['id']}] CVV/CVC value found in field '{cf}'. "
                                f"Security codes must never be stored."
                            )
                            recommendations.append(
                                "Remove CVV from all stored data. Use Stripe PaymentIntents "
                                "which handle CVV in their PCI-compliant environment."
                            )

            elif rule == "consent_tracking":
                if "consent_given" not in data_keys and "consent_timestamp" not in data_keys:
                    if any(f in data_keys for f in ["email", "name", "phone", "user_id"]):
                        violations.append(
                            f"[{req['id']}] Personal data present without consent tracking fields. "
                            f"GDPR requires explicit consent records."
                        )
                        recommendations.append(
                            "Add 'consent_given', 'consent_timestamp', and 'consent_purpose' "
                            "fields alongside personal data."
                        )

            elif rule == "strong_customer_authentication":
                if "payment_amount" in data_keys or "amount" in data_keys:
                    if "sca_completed" not in data_keys:
                        violations.append(
                            f"[{req['id']}] Payment data present without SCA completion flag. "
                            f"Strong Customer Authentication required for EU transactions."
                        )
                        recommendations.append(
                            "Ensure Stripe handles SCA via 3D Secure. "
                            "Record 'sca_completed' flag for audit."
                        )

            elif rule == "booking_record_retention":
                if "created_at" in data_keys and "retention_policy" not in data_keys:
                    recommendations.append(
                        f"[{req['id']}] Consider adding explicit retention_policy field. "
                        f"IATA BSP requires 2-year minimum retention for booking records."
                    )

            elif rule == "passenger_data_accuracy":
                pax_name = self._get_nested(data, "passenger_name")
                doc_name = self._get_nested(data, "document_name")
                if pax_name and doc_name:
                    if self._normalize_name(pax_name) != self._normalize_name(doc_name):
                        violations.append(
                            f"[{req['id']}] Passenger name '{pax_name}' does not match "
                            f"document name '{doc_name}'. IATA Resolution 830d requires exact match."
                        )
                        recommendations.append(
                            "Verify passenger name matches travel document exactly. "
                            "Use the name as printed on passport/ID."
                        )

            elif rule == "truncation_masking":
                for cf in check_fields:
                    if cf in data_keys:
                        val = self._get_nested(data, cf)
                        if val and isinstance(val, str):
                            digits = val.replace(" ", "").replace("-", "")
                            if digits.isdigit() and len(digits) > 10:
                                violations.append(
                                    f"[{req['id']}] Field '{cf}' contains more than "
                                    f"first-6/last-4 digits. Card display must be truncated."
                                )
                                recommendations.append(
                                    "Display card numbers as '****-****-****-1234' or "
                                    "'411111-******-1234' (first-6/last-4 only)."
                                )

        self._check_count += 1
        self._violation_count += len(violations)

        result = {
            "compliant": len(violations) == 0,
            "regulation": regulation,
            "violations": violations,
            "recommendations": recommendations,
            "requirements_checked": len(reg_def["requirements"]),
        }

        # Publish compliance check event
        self._event_bus.publish(Event(
            type=EventType.REGULATION_CHECK,
            source="compliance.regulations",
            data={
                "regulation": regulation,
                "compliant": result["compliant"],
                "violation_count": len(violations),
                "requirements_checked": result["requirements_checked"],
            },
        ))

        if violations:
            logger.warning(
                "Compliance check FAILED for %s: %d violation(s)",
                regulation, len(violations),
            )
        else:
            logger.debug("Compliance check PASSED for %s", regulation)

        return result

    # ------------------------------------------------------------------ #
    # Check all regulations                                               #
    # ------------------------------------------------------------------ #

    def check_all_regulations(self, data: dict) -> dict:
        """
        Check data against all known regulations.

        Args:
            data: Dictionary of data fields to validate.

        Returns:
            Dictionary mapping regulation name to its compliance result,
            plus an ``overall_compliant`` key indicating whether all checks pass.
        """
        results: Dict[str, Any] = {}
        all_compliant = True

        for reg_name in self.REGULATIONS:
            result = self.check_compliance(data, reg_name)
            results[reg_name] = result
            if not result["compliant"]:
                all_compliant = False

        results["overall_compliant"] = all_compliant
        return results

    # ------------------------------------------------------------------ #
    # Requirement listing                                                 #
    # ------------------------------------------------------------------ #

    def get_requirements(self, regulation: str) -> List[dict]:
        """
        List all requirements for a regulation.

        Args:
            regulation: Regulation key (e.g. ``"PCI_DSS"``).

        Returns:
            List of requirement dictionaries. Empty list if regulation unknown.
        """
        reg_def = self.REGULATIONS.get(regulation)
        if not reg_def:
            logger.warning("Unknown regulation requested: %s", regulation)
            return []
        return list(reg_def["requirements"])

    # ------------------------------------------------------------------ #
    # Applicable regulations by geography and vertical                    #
    # ------------------------------------------------------------------ #

    def get_applicable_regulations(
        self, country: str, verticals: List[str]
    ) -> List[str]:
        """
        Determine which regulations apply based on geography and business type.

        PCI DSS and IATA BSP are global; GDPR/PSD2 apply to EU/EEA; CCPA
        applies to US (specifically California, but broadly applicable when
        California residents are customers).

        Args:
            country: ISO 3166-1 alpha-2 country code (e.g. ``"DE"``, ``"US"``).
            verticals: Business verticals (e.g. ``["flights", "payments"]``).

        Returns:
            List of applicable regulation keys.
        """
        applicable: List[str] = []
        country_upper = country.upper().strip()

        for reg_name, reg_def in self.REGULATIONS.items():
            jurisdiction = reg_def["jurisdiction"]
            reg_verticals = reg_def["verticals"]

            # Check vertical match
            vertical_match = "all" in reg_verticals or any(
                v in reg_verticals for v in verticals
            )
            if not vertical_match:
                continue

            # Check jurisdiction match
            if jurisdiction == "global":
                applicable.append(reg_name)
            elif jurisdiction == "EU/EEA":
                # Check if country is in EU/EEA map
                country_regs = self._JURISDICTION_MAP.get(country_upper, [])
                if reg_name in country_regs:
                    applicable.append(reg_name)
            elif jurisdiction == "US-CA":
                # CCPA applies if operating in the US (California residents may be customers)
                if country_upper == "US" or country_upper in self._JURISDICTION_MAP:
                    country_regs = self._JURISDICTION_MAP.get(country_upper, [])
                    if reg_name in country_regs:
                        applicable.append(reg_name)

        return sorted(set(applicable))

    # ------------------------------------------------------------------ #
    # Compliance report                                                   #
    # ------------------------------------------------------------------ #

    def generate_compliance_report(self, agency_id: str) -> dict:
        """
        Generate a full compliance status report for an agency.

        This is a summary report that lists all regulations, their
        requirements, and the engine's runtime statistics. For data-specific
        checks, use ``check_compliance()`` or ``check_all_regulations()``.

        Args:
            agency_id: Agency identifier for the report.

        Returns:
            Dictionary with report metadata, regulation summaries, and
            aggregate statistics.
        """
        report = {
            "agency_id": agency_id,
            "generated_at": time.time(),
            "report_type": "compliance_status",
            "engine_stats": {
                "total_checks_run": self._check_count,
                "total_violations_found": self._violation_count,
            },
            "regulations": {},
        }

        for reg_name, reg_def in self.REGULATIONS.items():
            report["regulations"][reg_name] = {
                "full_name": reg_def["full_name"],
                "version": reg_def["version"],
                "jurisdiction": reg_def["jurisdiction"],
                "verticals": reg_def["verticals"],
                "total_requirements": len(reg_def["requirements"]),
                "requirements": [
                    {
                        "id": req["id"],
                        "rule": req["rule"],
                        "description": req["description"],
                        "severity": req["severity"],
                    }
                    for req in reg_def["requirements"]
                ],
            }

        logger.info(
            "Generated compliance report for agency %s: %d regulations, %d total requirements",
            agency_id,
            len(self.REGULATIONS),
            sum(len(r["requirements"]) for r in self.REGULATIONS.values()),
        )

        return report

    # ------------------------------------------------------------------ #
    # Internal helpers                                                    #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _flatten_keys(data: dict, prefix: str = "") -> List[str]:
        """Recursively flatten dict keys to dot-notation and bare names."""
        keys: List[str] = []
        for k, v in data.items():
            full_key = f"{prefix}.{k}" if prefix else k
            keys.append(k)  # bare key for simple field matching
            keys.append(full_key)  # dotted key for nested matching
            if isinstance(v, dict):
                keys.extend(RegulationEngine._flatten_keys(v, full_key))
        return keys

    @staticmethod
    def _get_nested(data: dict, key: str) -> Optional[Any]:
        """Get a value by key, searching nested dicts."""
        if key in data:
            return data[key]
        for v in data.values():
            if isinstance(v, dict):
                result = RegulationEngine._get_nested(v, key)
                if result is not None:
                    return result
        return None

    @staticmethod
    def _normalize_name(name: str) -> str:
        """Normalize a name for comparison (uppercase, strip whitespace)."""
        return " ".join(name.upper().split())
