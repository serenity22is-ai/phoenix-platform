"""
PII Protector -- Detection, masking, and sanitization of personally identifiable information.

Provides regex-based detection of PII types (email, phone, credit card, SSN,
passport, IP address) and utilities for masking PII before logging, export,
or display. Designed for use by other neurons that need to sanitize data
before publishing events or writing to non-secure storage.

Credit card detection includes Luhn algorithm validation to reduce false
positives on arbitrary digit sequences.

MYSTES KYRIOS LLC -- Confidential.
"""

import copy
import logging
import re
from typing import Any, Dict, List, Optional

from ..core.events import EventBus, Event, EventType

logger = logging.getLogger(__name__)


class PIIProtector:
    """
    Detects and masks personally identifiable information in text and
    structured data.

    All detection is regex-based with domain-specific validation (Luhn
    for credit cards, format checks for passports). No ML models or
    external services required.
    """

    # ------------------------------------------------------------------ #
    # PII field name patterns                                             #
    # ------------------------------------------------------------------ #

    _SENSITIVE_FIELD_NAMES: List[str] = [
        "password", "passwd", "pwd", "secret",
        "ssn", "social_security", "social_security_number",
        "passport", "passport_number", "passport_no",
        "card_number", "card_num", "pan", "primary_account_number",
        "cvv", "cvc", "cid", "security_code", "card_verification",
        "credit_card", "debit_card",
        "bank_account", "account_number", "routing_number",
        "tax_id", "ein", "tin",
        "drivers_license", "driver_license", "dl_number",
        "date_of_birth", "dob", "birth_date",
        "mothers_maiden_name", "maiden_name",
        "pin", "access_code",
        "api_key", "api_secret", "token", "auth_token",
        "private_key", "encryption_key",
    ]

    # ------------------------------------------------------------------ #
    # Regex patterns for PII detection                                    #
    # ------------------------------------------------------------------ #

    _PATTERNS: Dict[str, re.Pattern] = {
        "email": re.compile(
            r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
        ),
        "phone": re.compile(
            r"(?<!\d)"  # no digit before
            r"(?:"
            r"\+?1[\s\-.]?\(?\d{3}\)?[\s\-.]?\d{3}[\s\-.]?\d{4}"  # US: +1 (555) 123-4567
            r"|"
            r"\+\d{1,3}[\s\-.]?\d{1,4}[\s\-.]?\d{3,4}[\s\-.]?\d{3,4}"  # International
            r"|"
            r"\(?\d{3}\)?[\s\-.]?\d{3}[\s\-.]?\d{4}"  # US without country code
            r")"
            r"(?!\d)",  # no digit after
        ),
        "credit_card": re.compile(
            r"(?<!\d)"
            r"(?:"
            r"4\d{3}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4}"  # Visa 16
            r"|"
            r"4\d{3}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{1}"  # Visa 13
            r"|"
            r"5[1-5]\d{2}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4}"  # Mastercard
            r"|"
            r"3[47]\d{1}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{3}"  # Amex (15 digits)
            r"|"
            r"6(?:011|5\d{2})[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4}"  # Discover
            r"|"
            r"3(?:0[0-5]|[68]\d)\d[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{2}"  # Diners
            r"|"
            r"(?:2131|1800|35\d{3})[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{3}"  # JCB
            r")"
            r"(?!\d)",
        ),
        "ssn": re.compile(
            r"(?<!\d)"
            r"(?!000|666|9\d{2})"  # SSN rules: no 000, 666, or 9xx in area
            r"\d{3}"
            r"[\s\-]"
            r"(?!00)\d{2}"  # No 00 in group
            r"[\s\-]"
            r"(?!0000)\d{4}"  # No 0000 in serial
            r"(?!\d)",
        ),
        "passport": re.compile(
            r"(?<!\w)"
            r"(?:"
            r"[A-Z]{1,2}\d{6,9}"  # US, UK, etc.: 1-2 letters + 6-9 digits
            r"|"
            r"\d{2}[A-Z]{2}\d{5}"  # Indian: 2 digits + 2 letters + 5 digits
            r"|"
            r"[A-Z]\d{8}"  # Canadian: 1 letter + 8 digits
            r"|"
            r"[CEGJK]\d{8}"  # Chinese: 1 letter (E/G/etc.) + 8 digits
            r")"
            r"(?!\w)",
        ),
        "ipv4": re.compile(
            r"(?<!\d)"
            r"(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\."
            r"(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\."
            r"(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\."
            r"(?:25[0-5]|2[0-4]\d|[01]?\d\d?)"
            r"(?!\d)",
        ),
        "ipv6": re.compile(
            r"(?:(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}"
            r"|(?:[0-9a-fA-F]{1,4}:){1,7}:"
            r"|(?:[0-9a-fA-F]{1,4}:){1,6}:[0-9a-fA-F]{1,4}"
            r"|::(?:[fF]{4}:)?(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.(?:25[0-5]|2[0-4]\d|[01]?\d\d?)"
            r"|::)",
        ),
    }

    def __init__(self, event_bus: EventBus):
        """
        Initialize the PII protector.

        Args:
            event_bus: Shared event bus for publishing PII detection events.
        """
        self._event_bus = event_bus
        self._detection_count = 0
        logger.info("PIIProtector initialized with %d pattern types", len(self._PATTERNS))

    # ------------------------------------------------------------------ #
    # Detection                                                           #
    # ------------------------------------------------------------------ #

    def detect_pii(self, text: str) -> List[dict]:
        """
        Detect PII in free text.

        Scans for emails, phone numbers, credit card numbers (Luhn-validated),
        SSNs, passport numbers, and IP addresses.

        Args:
            text: Text to scan.

        Returns:
            List of detection results, each with ``type``, ``value``,
            ``start``, and ``end`` keys.
        """
        if not text or not isinstance(text, str):
            return []

        detections: List[dict] = []

        for pii_type, pattern in self._PATTERNS.items():
            for match in pattern.finditer(text):
                value = match.group()

                # Credit card: validate with Luhn algorithm
                if pii_type == "credit_card":
                    digits = re.sub(r"[\s\-]", "", value)
                    if not self._luhn_check(digits):
                        continue

                # Map IPv4/IPv6 to unified "ip_address" type
                detection_type = pii_type
                if pii_type in ("ipv4", "ipv6"):
                    detection_type = "ip_address"

                detections.append({
                    "type": detection_type,
                    "value": value,
                    "start": match.start(),
                    "end": match.end(),
                })

        self._detection_count += len(detections)

        if detections:
            logger.debug(
                "Detected %d PII instance(s) in text (%d chars)",
                len(detections), len(text),
            )

        return detections

    # ------------------------------------------------------------------ #
    # Masking                                                             #
    # ------------------------------------------------------------------ #

    def mask_pii(self, text: str, mask_char: str = "*") -> str:
        """
        Replace detected PII in text with masked versions.

        Masking preserves enough structure for humans to identify the type
        (e.g. ``j***@***.com`` for emails, ``****-****-****-1234`` for cards).

        Args:
            text: Text to mask.
            mask_char: Character used for masking.

        Returns:
            Text with PII replaced by masked equivalents.
        """
        if not text or not isinstance(text, str):
            return text

        detections = self.detect_pii(text)
        if not detections:
            return text

        # Process detections in reverse order to preserve positions
        result = text
        for det in sorted(detections, key=lambda d: d["start"], reverse=True):
            masked = self._mask_value(det["value"], det["type"], mask_char)
            result = result[:det["start"]] + masked + result[det["end"]:]

        return result

    def mask_dict(
        self,
        data: dict,
        fields_to_mask: Optional[List[str]] = None,
    ) -> dict:
        """
        Mask PII in dictionary values, recursively.

        If ``fields_to_mask`` is provided, only those fields are masked.
        Otherwise, all fields with sensitive names are masked, plus a PII
        scan is run on string values.

        Args:
            data: Dictionary to mask (not modified in place).
            fields_to_mask: Explicit list of field names to mask. If None,
                            uses automatic detection.

        Returns:
            Deep copy of ``data`` with PII masked.
        """
        if not isinstance(data, dict):
            return data

        result = {}

        for key, value in data.items():
            should_mask = False

            if fields_to_mask:
                should_mask = key in fields_to_mask
            else:
                should_mask = self.is_sensitive_field(key)

            if isinstance(value, dict):
                result[key] = self.mask_dict(value, fields_to_mask)
            elif isinstance(value, list):
                result[key] = [
                    self.mask_dict(item, fields_to_mask)
                    if isinstance(item, dict)
                    else (self.mask_pii(item) if isinstance(item, str) else item)
                    for item in value
                ]
            elif should_mask and value is not None:
                result[key] = self._mask_field_value(str(value))
            elif isinstance(value, str) and not fields_to_mask:
                # Auto-detect PII in string values even if field name isn't sensitive
                result[key] = self.mask_pii(value)
            else:
                result[key] = value

        return result

    # ------------------------------------------------------------------ #
    # Field name analysis                                                 #
    # ------------------------------------------------------------------ #

    def is_sensitive_field(self, field_name: str) -> bool:
        """
        Check if a field name suggests it contains PII.

        Uses a curated list of known sensitive field name patterns.
        Case-insensitive matching.

        Args:
            field_name: Field name to check.

        Returns:
            True if the field name is recognized as sensitive.
        """
        normalized = field_name.lower().strip()
        return normalized in self._SENSITIVE_FIELD_NAMES

    # ------------------------------------------------------------------ #
    # Sanitization for logging and export                                 #
    # ------------------------------------------------------------------ #

    def sanitize_for_logging(self, data: dict) -> dict:
        """
        Create a deep copy of data with all PII masked, safe for logs.

        More aggressive than ``mask_dict``: also masks any string value
        longer than 6 characters that contains detected PII, and redacts
        all sensitive field names.

        Args:
            data: Dictionary to sanitize.

        Returns:
            Deep copy with PII removed, safe for application logs.
        """
        sanitized = copy.deepcopy(data)
        return self._recursive_sanitize(sanitized)

    def sanitize_for_export(
        self, data: dict, regulation: str = "gdpr"
    ) -> dict:
        """
        Prepare data for export in compliance with a specific regulation.

        For GDPR: masks all PII fields, removes non-essential identifiers.
        For PCI_DSS: removes all payment card data entirely (not just masked).
        For CCPA: similar to GDPR but retains more aggregate data.

        Args:
            data: Dictionary to sanitize for export.
            regulation: Regulation to comply with (``"gdpr"``, ``"pci_dss"``, ``"ccpa"``).

        Returns:
            Sanitized deep copy safe for export under the specified regulation.
        """
        result = copy.deepcopy(data)
        regulation_lower = regulation.lower().replace("-", "_")

        if regulation_lower == "pci_dss":
            # PCI: completely remove all payment card fields
            pci_fields = {
                "card_number", "pan", "primary_account_number",
                "cvv", "cvc", "cid", "security_code",
                "card_verification", "expiry", "expiration_date",
                "card_exp", "cardholder_name",
            }
            result = self._remove_fields(result, pci_fields)

        elif regulation_lower in ("gdpr", "ccpa"):
            # GDPR/CCPA: mask PII but retain structure
            result = self.mask_dict(result)

            # For GDPR, also apply data minimization: remove unnecessary fields
            if regulation_lower == "gdpr":
                unnecessary = {"ip_address", "user_agent", "browser_fingerprint"}
                result = self._remove_fields(result, unnecessary)

        # Publish event about the sanitization
        self._event_bus.publish(Event(
            type=EventType.PII_DETECTED,
            source="compliance.pii",
            data={
                "action": "sanitize_for_export",
                "regulation": regulation,
                "fields_processed": len(data) if isinstance(data, dict) else 0,
            },
        ))

        return result

    def get_pii_fields(self) -> List[str]:
        """
        Get the list of known PII-sensitive field names.

        Returns:
            Sorted list of field names considered PII.
        """
        return sorted(self._SENSITIVE_FIELD_NAMES)

    def scan_and_alert(self, data: dict, context: str = "") -> List[dict]:
        """
        Scan a dictionary for unexpected PII and publish alerts.

        Use this at data ingestion points (API responses, webhook payloads)
        to detect PII that shouldn't be present. Publishes a PII_DETECTED
        event if any PII is found.

        Args:
            data: Dictionary to scan.
            context: Description of where this data came from.

        Returns:
            List of PII detections found.
        """
        all_detections: List[dict] = []

        def _scan_recursive(obj: Any, path: str = "") -> None:
            if isinstance(obj, dict):
                for key, value in obj.items():
                    current_path = f"{path}.{key}" if path else key

                    # Check field name
                    if self.is_sensitive_field(key) and value is not None:
                        all_detections.append({
                            "type": "sensitive_field",
                            "field": current_path,
                            "value_type": type(value).__name__,
                        })

                    _scan_recursive(value, current_path)

            elif isinstance(obj, str) and len(obj) >= 5:
                detections = self.detect_pii(obj)
                for det in detections:
                    det["field"] = path
                    all_detections.append(det)

            elif isinstance(obj, list):
                for i, item in enumerate(obj):
                    _scan_recursive(item, f"{path}[{i}]")

        _scan_recursive(data)

        if all_detections:
            self._event_bus.publish(Event(
                type=EventType.PII_DETECTED,
                source="compliance.pii",
                data={
                    "context": context,
                    "detection_count": len(all_detections),
                    "types_found": list({d.get("type", "unknown") for d in all_detections}),
                },
            ))
            logger.warning(
                "PII detected in %s: %d instance(s) of types %s",
                context or "data",
                len(all_detections),
                [d.get("type") for d in all_detections],
            )

        return all_detections

    # ------------------------------------------------------------------ #
    # Internal helpers                                                    #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _luhn_check(digits: str) -> bool:
        """
        Validate a credit card number using the Luhn algorithm.

        Args:
            digits: String of digits (no spaces or dashes).

        Returns:
            True if the number passes the Luhn check.
        """
        if not digits.isdigit() or len(digits) < 13:
            return False

        total = 0
        reverse_digits = digits[::-1]

        for i, digit in enumerate(reverse_digits):
            n = int(digit)
            if i % 2 == 1:
                n *= 2
                if n > 9:
                    n -= 9
            total += n

        return total % 10 == 0

    @staticmethod
    def _mask_value(value: str, pii_type: str, mask_char: str = "*") -> str:
        """
        Mask a detected PII value while preserving enough structure
        for type identification.
        """
        if pii_type == "email":
            # j***@***.com
            parts = value.split("@")
            if len(parts) == 2:
                local = parts[0]
                domain_parts = parts[1].rsplit(".", 1)
                masked_local = local[0] + mask_char * 3 if local else mask_char * 4
                masked_domain = mask_char * 3
                tld = domain_parts[1] if len(domain_parts) == 2 else "com"
                return f"{masked_local}@{masked_domain}.{tld}"
            return mask_char * len(value)

        elif pii_type == "credit_card":
            # ****-****-****-1234
            digits = re.sub(r"[\s\-]", "", value)
            last4 = digits[-4:] if len(digits) >= 4 else digits
            masked_prefix = mask_char * 4
            return f"{masked_prefix}-{masked_prefix}-{masked_prefix}-{last4}"

        elif pii_type == "ssn":
            # ***-**-1234
            digits = re.sub(r"[\s\-]", "", value)
            last4 = digits[-4:] if len(digits) >= 4 else digits
            return f"{mask_char * 3}-{mask_char * 2}-{last4}"

        elif pii_type == "phone":
            # (***) ***-1234
            digits = re.sub(r"[^\d]", "", value)
            last4 = digits[-4:] if len(digits) >= 4 else digits
            return f"({mask_char * 3}) {mask_char * 3}-{last4}"

        elif pii_type == "passport":
            # **********
            return mask_char * len(value)

        elif pii_type in ("ip_address", "ipv4", "ipv6"):
            # ***.***.***.***
            if "." in value and ":" not in value:
                # IPv4
                return f"{mask_char * 3}.{mask_char * 3}.{mask_char * 3}.{mask_char * 3}"
            else:
                # IPv6
                return mask_char * len(value)

        # Fallback: mask everything
        return mask_char * len(value)

    @staticmethod
    def _mask_field_value(value: str, mask_char: str = "*") -> str:
        """Mask a field value when we know it's sensitive but don't know the type."""
        if len(value) <= 2:
            return mask_char * len(value)
        return value[0] + mask_char * (len(value) - 2) + value[-1]

    def _recursive_sanitize(self, obj: Any) -> Any:
        """Recursively sanitize a data structure for logging."""
        if isinstance(obj, dict):
            result = {}
            for key, value in obj.items():
                if self.is_sensitive_field(key):
                    if value is not None:
                        result[key] = "[REDACTED]"
                    else:
                        result[key] = None
                elif isinstance(value, str):
                    result[key] = self.mask_pii(value)
                elif isinstance(value, (dict, list)):
                    result[key] = self._recursive_sanitize(value)
                else:
                    result[key] = value
            return result
        elif isinstance(obj, list):
            return [self._recursive_sanitize(item) for item in obj]
        elif isinstance(obj, str):
            return self.mask_pii(obj)
        return obj

    @staticmethod
    def _remove_fields(data: dict, fields_to_remove: set) -> dict:
        """Recursively remove specified fields from a dictionary."""
        if not isinstance(data, dict):
            return data

        result = {}
        for key, value in data.items():
            if key.lower() in fields_to_remove:
                continue
            if isinstance(value, dict):
                result[key] = PIIProtector._remove_fields(value, fields_to_remove)
            elif isinstance(value, list):
                result[key] = [
                    PIIProtector._remove_fields(item, fields_to_remove)
                    if isinstance(item, dict) else item
                    for item in value
                ]
            else:
                result[key] = value
        return result
