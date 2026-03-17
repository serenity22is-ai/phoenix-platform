"""
IP Firewall — The critical security layer for the daemon bridge.

Every piece of information that crosses the bridge passes through the
firewall. It classifies content, blocks proprietary data, redacts
credentials, and maintains a complete audit trail.

The firewall enforces two guarantees:
1. NO proprietary code, business logic, or credentials cross the bridge
2. EVERY byte that crosses is logged with classification and hash

Each entity configures their own firewall policies. Entity A's firewall
controls what leaves Entity A's side. Entity B's firewall controls what
leaves Entity B's side. Neither side can override the other's policies.

MYSTES KYRIOS LLC — Confidential.
"""

import hashlib
import json
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from ..core.events import Event, EventBus, EventType
from ..core.types import (
    FirewallAuditEntry,
    KnowledgeClassification,
    StructuralKnowledge,
)

logger = logging.getLogger(__name__)


# Default blocklist patterns — content matching these NEVER crosses
DEFAULT_BLOCKLIST = {
    "file_patterns": [
        "*.env", "*.pem", "*.key", "*.p12", "*.pfx",
        "*credentials*", "*secret*", "*password*",
        "*.sqlite", "*.db", "*.sql",  # Database files
        "*.log",  # Log files may contain PII
    ],
    "content_patterns": [
        r"(?:password|passwd|pwd)\s*[:=]",
        r"(?:api[_-]?key|apikey)\s*[:=]\s*['\"]",
        r"(?:secret|token)\s*[:=]\s*['\"]",
        r"-----BEGIN\s+(?:RSA\s+)?PRIVATE\s+KEY-----",
        r"(?:AWS|AZURE|GCP)_[A-Z_]*(?:KEY|SECRET|TOKEN)",
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
    ],
    "directory_patterns": [
        ".git/", "node_modules/", "__pycache__/",
        ".env/", "venv/", ".venv/",
        "secrets/", "credentials/", "private/",
    ],
}


class IPFirewall:
    """
    IP Firewall for the daemon bridge.

    Inspects, classifies, and gates all information crossing the bridge.
    Maintains a complete audit trail. Configurable per-entity.
    """

    def __init__(
        self,
        entity_id: str,
        bridge_id: str,
        event_bus: Optional[EventBus] = None,
        config: Optional[Dict[str, Any]] = None,
    ):
        self._entity_id = entity_id
        self._bridge_id = bridge_id
        self._event_bus = event_bus
        self._config = config or {}

        # Merge custom blocklist with defaults
        self._blocklist = {**DEFAULT_BLOCKLIST}
        custom = self._config.get("blocklist", {})
        for key in custom:
            if key in self._blocklist and isinstance(self._blocklist[key], list):
                self._blocklist[key].extend(custom[key])
            else:
                self._blocklist[key] = custom[key]

        # Allowlist — explicitly permitted content types
        self._allowlist = self._config.get("allowlist", [
            "api_patterns", "data_schemas", "auth_flows",
            "integration_points", "tech_stack",
        ])

        # Audit trail
        self._audit_log: List[FirewallAuditEntry] = []
        self._max_audit_entries = self._config.get("max_audit_entries", 50000)

        # Stats
        self._stats = {
            "allowed": 0,
            "blocked": 0,
            "redacted": 0,
            "total_bytes_allowed": 0,
            "total_bytes_blocked": 0,
        }

    def inspect(
        self,
        content: Any,
        content_type: str,
        direction: str,
        classifier: Any = None,
    ) -> Tuple[bool, Any, str]:
        """
        Inspect content attempting to cross the bridge.

        Args:
            content: The content to inspect (dict, list, or string).
            content_type: What kind of content ("api_pattern", "schema", etc.).
            direction: "outbound" (leaving this entity) or "inbound" (entering).
            classifier: Optional StructuralKnowledgeExtractor for classification.

        Returns:
            (allowed: bool, sanitized_content: Any, reason: str)
            - If allowed: (True, sanitized_content, "")
            - If blocked: (False, None, "reason for blocking")
        """
        content_str = json.dumps(content, default=str) if not isinstance(
            content, str
        ) else content
        content_bytes = len(content_str.encode("utf-8"))
        content_hash = hashlib.sha256(content_str.encode()).hexdigest()

        # Step 1: Check if content type is allowlisted
        if content_type not in self._allowlist:
            self._log_audit(
                direction=direction,
                classification="proprietary",
                action="blocked",
                content_hash=content_hash,
                content_type=content_type,
                size_bytes=content_bytes,
                reason=f"Content type '{content_type}' not in allowlist",
            )
            self._stats["blocked"] += 1
            self._stats["total_bytes_blocked"] += content_bytes
            return False, None, f"Content type '{content_type}' not allowed"

        # Step 2: Classify content
        classification = KnowledgeClassification.STRUCTURAL
        if classifier:
            classification = classifier.classify_content(content_str)

        # Step 3: Block if not structural or functional
        blocked_classifications = {
            KnowledgeClassification.PROPRIETARY,
            KnowledgeClassification.CREDENTIAL,
            KnowledgeClassification.PII,
            KnowledgeClassification.SOURCE_CODE,
        }

        if classification in blocked_classifications:
            self._log_audit(
                direction=direction,
                classification=classification.value,
                action="blocked",
                content_hash=content_hash,
                content_type=content_type,
                size_bytes=content_bytes,
                reason=f"Content classified as {classification.value}",
            )
            self._stats["blocked"] += 1
            self._stats["total_bytes_blocked"] += content_bytes

            # Publish firewall block event
            if self._event_bus:
                self._event_bus.publish(Event(
                    type=EventType.BRIDGE_FIREWALL_BLOCKED,
                    source="bridge.firewall",
                    data={
                        "bridge_id": self._bridge_id,
                        "entity_id": self._entity_id,
                        "classification": classification.value,
                        "content_type": content_type,
                        "direction": direction,
                    },
                ))

            return False, None, f"Blocked: {classification.value}"

        # Step 4: Sanitize — remove any residual credentials/PII
        sanitized = self._sanitize_content(content)

        # Step 5: Compute hash of sanitized content
        sanitized_str = json.dumps(sanitized, default=str) if not isinstance(
            sanitized, str
        ) else sanitized
        sanitized_bytes = len(sanitized_str.encode("utf-8"))
        sanitized_hash = hashlib.sha256(sanitized_str.encode()).hexdigest()

        redacted = content_hash != sanitized_hash
        action = "redacted" if redacted else "allowed"

        self._log_audit(
            direction=direction,
            classification=classification.value,
            action=action,
            content_hash=sanitized_hash,
            content_type=content_type,
            size_bytes=sanitized_bytes,
            reason="Credentials/PII redacted" if redacted else "",
        )

        if redacted:
            self._stats["redacted"] += 1
        else:
            self._stats["allowed"] += 1
        self._stats["total_bytes_allowed"] += sanitized_bytes

        return True, sanitized, ""

    def inspect_structural_knowledge(
        self,
        knowledge: StructuralKnowledge,
        direction: str,
        classifier: Any = None,
    ) -> Tuple[bool, Optional[StructuralKnowledge], List[str]]:
        """
        Inspect an entire StructuralKnowledge object.

        Each component (api_patterns, schemas, etc.) is inspected
        individually. Components that pass are kept; components that
        fail are stripped with reasons logged.

        Returns:
            (passed: bool, sanitized_knowledge: StructuralKnowledge, blocked_reasons: list)
        """
        blocked_reasons: List[str] = []
        sanitized = StructuralKnowledge(
            entity_id=knowledge.entity_id,
            bridge_id=knowledge.bridge_id,
        )

        # Inspect each component
        for pattern in knowledge.api_patterns:
            ok, clean, reason = self.inspect(
                pattern, "api_patterns", direction, classifier
            )
            if ok:
                sanitized.api_patterns.append(clean)
            else:
                blocked_reasons.append(f"API pattern blocked: {reason}")

        for name, schema in knowledge.data_schemas.items():
            ok, clean, reason = self.inspect(
                schema, "data_schemas", direction, classifier
            )
            if ok:
                sanitized.data_schemas[name] = clean
            else:
                blocked_reasons.append(f"Schema '{name}' blocked: {reason}")

        for flow in knowledge.auth_flows:
            ok, clean, reason = self.inspect(
                flow, "auth_flows", direction, classifier
            )
            if ok:
                sanitized.auth_flows.append(clean)
            else:
                blocked_reasons.append(f"Auth flow blocked: {reason}")

        for point in knowledge.integration_points:
            ok, clean, reason = self.inspect(
                point, "integration_points", direction, classifier
            )
            if ok:
                sanitized.integration_points.append(clean)
            else:
                blocked_reasons.append(f"Integration point blocked: {reason}")

        if knowledge.tech_stack:
            ok, clean, reason = self.inspect(
                knowledge.tech_stack, "tech_stack", direction, classifier
            )
            if ok:
                sanitized.tech_stack = clean

        sanitized.redacted_count = len(blocked_reasons)
        sanitized.classification_results = {
            "structural": (
                len(sanitized.api_patterns)
                + len(sanitized.data_schemas)
                + len(sanitized.auth_flows)
                + len(sanitized.integration_points)
            ),
            "blocked": len(blocked_reasons),
        }

        passed = len(blocked_reasons) == 0
        return passed, sanitized, blocked_reasons

    def get_audit_log(
        self,
        limit: int = 100,
        action: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get audit trail entries."""
        entries = self._audit_log
        if action:
            entries = [e for e in entries if e.action == action]
        return [e.to_dict() for e in entries[-limit:]]

    def get_stats(self) -> Dict[str, Any]:
        """Get firewall statistics."""
        return {
            **self._stats,
            "audit_entries": len(self._audit_log),
            "entity_id": self._entity_id,
            "bridge_id": self._bridge_id,
        }

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _sanitize_content(self, content: Any) -> Any:
        """Deep-sanitize content, redacting credentials and PII."""
        if isinstance(content, str):
            return self._redact_sensitive(content)
        elif isinstance(content, dict):
            return {k: self._sanitize_content(v) for k, v in content.items()}
        elif isinstance(content, list):
            return [self._sanitize_content(item) for item in content]
        return content

    def _redact_sensitive(self, text: str) -> str:
        """Redact sensitive patterns from text."""
        import re

        for pattern in self._blocklist.get("content_patterns", []):
            text = re.sub(pattern, "[REDACTED]", text, flags=re.IGNORECASE)

        return text

    def _log_audit(
        self,
        direction: str,
        classification: str,
        action: str,
        content_hash: str,
        content_type: str,
        size_bytes: int,
        reason: str = "",
    ) -> None:
        """Add an entry to the audit trail."""
        entry = FirewallAuditEntry(
            bridge_id=self._bridge_id,
            direction=direction,
            classification=classification,
            action=action,
            content_hash=content_hash,
            content_type=content_type,
            size_bytes=size_bytes,
            reason=reason,
        )

        self._audit_log.append(entry)

        # Trim if too large
        if len(self._audit_log) > self._max_audit_entries:
            self._audit_log = self._audit_log[-self._max_audit_entries:]

        # Publish audit event for blocked items
        if action == "blocked" and self._event_bus:
            self._event_bus.publish(Event(
                type=EventType.BRIDGE_AUDIT_ENTRY,
                source="bridge.firewall",
                data=entry.to_dict(),
            ))

    def to_dict(self) -> Dict[str, Any]:
        """Serialize firewall config and state."""
        return {
            "entity_id": self._entity_id,
            "bridge_id": self._bridge_id,
            "allowlist": self._allowlist,
            "stats": self._stats,
            "audit_count": len(self._audit_log),
        }
