"""
Structural Knowledge Extractor — Defines EXACTLY what crosses the bridge.

Extracts structural knowledge from a codebase: API patterns, data schemas,
auth flows, integration points, and tech stack information. This is the
"what" of a system — how it's structured — NOT the "why" (business logic).

What DOES cross the bridge:
- API endpoint patterns (paths, methods, request/response schemas)
- Data model structures (table names, column types, relationships)
- Authentication flows (type, token format, refresh mechanisms)
- Tech stack information (languages, frameworks, versions)
- Integration points (webhooks, event buses, message queues)

What NEVER crosses the bridge:
- Verbatim source code
- Business logic / algorithms
- Pricing formulas / markup calculations
- Credentials, API keys, tokens
- PII or customer data
- Trade secrets or competitive strategies

MYSTES KYRIOS LLC — Confidential.
"""

import hashlib
import json
import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from ..core.types import (
    KnowledgeClassification,
    StructuralKnowledge,
    TechStack,
)

logger = logging.getLogger(__name__)


# Patterns that indicate structural vs proprietary content
_STRUCTURAL_INDICATORS = [
    r"endpoint", r"route", r"path", r"url",
    r"schema", r"model", r"table", r"column",
    r"field", r"type", r"format",
    r"auth", r"token", r"session",
    r"request", r"response", r"header",
    r"method", r"GET|POST|PUT|DELETE|PATCH",
    r"webhook", r"callback", r"event",
    r"version", r"protocol",
]

_PROPRIETARY_INDICATORS = [
    r"price|pricing|markup|margin|discount|commission",
    r"algorithm|formula|calculate|compute",
    r"secret|private|confidential|internal",
    r"loyalty|reward|promotion|coupon",
    r"competitive|strategy|advantage",
]

_CREDENTIAL_PATTERNS = [
    r"(?:password|passwd|pwd)\s*[:=]",
    r"(?:api[_-]?key|apikey)\s*[:=]\s*['\"][^'\"]{8,}",
    r"(?:secret|token)\s*[:=]\s*['\"][^'\"]{8,}",
    r"Bearer\s+[A-Za-z0-9\-._~+/]+=*",
    r"-----BEGIN\s+(?:RSA\s+)?PRIVATE\s+KEY-----",
    r"(?:AWS|AZURE|GCP)_[A-Z_]*(?:KEY|SECRET|TOKEN)",
]

_PII_PATTERNS = [
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",  # emails
    r"\b\d{3}[-.]?\d{2}[-.]?\d{4}\b",  # SSN-like
    r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b",  # credit card-like
    r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b",  # phone numbers
]


class StructuralKnowledgeExtractor:
    """
    Extracts structural knowledge from codebase artifacts.

    This is the daemon's eyes — it reads the codebase and extracts
    structural patterns that can safely cross the bridge. The firewall
    validates everything before it actually crosses.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self._config = config or {}
        self._extractions: List[StructuralKnowledge] = []

    def extract_api_patterns(
        self,
        routes: List[Dict[str, Any]],
        entity_id: str,
        bridge_id: str = "",
    ) -> List[Dict[str, Any]]:
        """
        Extract API patterns from route definitions.

        Takes a list of route dicts (as reported by the daemon's codebase
        scanner) and produces sanitized structural patterns.

        Args:
            routes: List of route dicts with path, method, handler info.
            entity_id: Which entity owns these routes.
            bridge_id: Which bridge this extraction is for.

        Returns:
            List of sanitized API pattern dicts.
        """
        patterns = []
        for route in routes:
            pattern = {
                "endpoint": route.get("path", ""),
                "method": route.get("method", "GET").upper(),
                "purpose": route.get("purpose", ""),
                "parameters": self._extract_parameters(route),
                "request_schema": self._sanitize_schema(
                    route.get("request_schema", {})
                ),
                "response_schema": self._sanitize_schema(
                    route.get("response_schema", {})
                ),
                "auth_required": route.get("auth_required", True),
            }
            patterns.append(pattern)

        logger.info(
            "Extracted %d API patterns for entity %s",
            len(patterns), entity_id[:8] if entity_id else "unknown",
        )
        return patterns

    def extract_data_schemas(
        self,
        models: List[Dict[str, Any]],
        entity_id: str,
    ) -> Dict[str, Any]:
        """
        Extract data model schemas from model definitions.

        Captures table/collection names, column types, and relationships.
        Strips default values, constraints with business logic, and any
        data samples.

        Args:
            models: List of model dicts with name, columns, relationships.
            entity_id: Which entity owns these models.

        Returns:
            Dict of model_name -> sanitized schema.
        """
        schemas = {}
        for model in models:
            name = model.get("name", "")
            if not name:
                continue

            columns = []
            for col in model.get("columns", []):
                sanitized = {
                    "name": col.get("name", ""),
                    "type": col.get("type", "string"),
                    "nullable": col.get("nullable", True),
                    "primary_key": col.get("primary_key", False),
                    "foreign_key": col.get("foreign_key", ""),
                }
                columns.append(sanitized)

            schemas[name] = {
                "columns": columns,
                "relationships": [
                    {"target": r.get("target", ""), "type": r.get("type", "")}
                    for r in model.get("relationships", [])
                ],
            }

        logger.info(
            "Extracted %d data schemas for entity %s",
            len(schemas), entity_id[:8] if entity_id else "unknown",
        )
        return schemas

    def extract_auth_flows(
        self,
        auth_config: Dict[str, Any],
        entity_id: str,
    ) -> List[Dict[str, Any]]:
        """
        Extract authentication flow patterns.

        Captures the TYPE of auth (OAuth2, API key, session, etc.),
        the flow (authorization code, client credentials, etc.),
        and structural details. NEVER captures actual credentials.
        """
        flows = []

        auth_type = auth_config.get("type", "unknown")
        flow = {
            "type": auth_type,
            "flow": auth_config.get("flow", ""),
            "token_endpoint": auth_config.get("token_endpoint", ""),
            "refresh_supported": auth_config.get("refresh_supported", False),
            "scopes": auth_config.get("scopes", []),
            "header_format": auth_config.get("header_format", "Bearer {token}"),
            "expiry_seconds": auth_config.get("expiry_seconds", 0),
        }

        # Strip any actual credentials that might have leaked in
        for key in list(flow.keys()):
            if isinstance(flow[key], str):
                flow[key] = self._redact_credentials(flow[key])

        flows.append(flow)
        return flows

    def extract_integration_points(
        self,
        codebase_info: Dict[str, Any],
        entity_id: str,
    ) -> List[Dict[str, Any]]:
        """
        Extract integration points — where systems connect.

        Identifies webhooks, event subscriptions, message queues,
        scheduled jobs, and external API calls.
        """
        points = []

        for webhook in codebase_info.get("webhooks", []):
            points.append({
                "type": "webhook",
                "url_pattern": webhook.get("path", ""),
                "events": webhook.get("events", []),
                "method": webhook.get("method", "POST"),
            })

        for ext_api in codebase_info.get("external_apis", []):
            points.append({
                "type": "external_api",
                "service": ext_api.get("service", ""),
                "base_url_pattern": self._redact_credentials(
                    ext_api.get("base_url", "")
                ),
                "endpoints_used": ext_api.get("endpoints", []),
            })

        for queue in codebase_info.get("queues", []):
            points.append({
                "type": "message_queue",
                "provider": queue.get("provider", ""),
                "topics": queue.get("topics", []),
            })

        return points

    def build_structural_knowledge(
        self,
        entity_id: str,
        bridge_id: str,
        routes: Optional[List[Dict[str, Any]]] = None,
        models: Optional[List[Dict[str, Any]]] = None,
        auth_config: Optional[Dict[str, Any]] = None,
        codebase_info: Optional[Dict[str, Any]] = None,
        tech_stack: Optional[Dict[str, Any]] = None,
    ) -> StructuralKnowledge:
        """
        Build a complete StructuralKnowledge object from codebase artifacts.

        This is the main entry point. Daemon calls this with whatever
        it has discovered, and gets back a sanitized, bridge-safe
        StructuralKnowledge object.
        """
        sk = StructuralKnowledge(
            entity_id=entity_id,
            bridge_id=bridge_id,
        )

        classification_results = {"structural": 0, "blocked": 0}

        if routes:
            sk.api_patterns = self.extract_api_patterns(
                routes, entity_id, bridge_id
            )
            classification_results["structural"] += len(sk.api_patterns)

        if models:
            sk.data_schemas = self.extract_data_schemas(models, entity_id)
            classification_results["structural"] += len(sk.data_schemas)

        if auth_config:
            sk.auth_flows = self.extract_auth_flows(auth_config, entity_id)
            classification_results["structural"] += len(sk.auth_flows)

        if codebase_info:
            sk.integration_points = self.extract_integration_points(
                codebase_info, entity_id
            )
            classification_results["structural"] += len(sk.integration_points)

        if tech_stack:
            sk.tech_stack = tech_stack

        sk.classification_results = classification_results
        sk.extracted_at = time.time()

        self._extractions.append(sk)

        logger.info(
            "Built structural knowledge for entity %s: %d patterns, "
            "%d schemas, %d auth flows, %d integration points",
            entity_id[:8] if entity_id else "unknown",
            len(sk.api_patterns),
            len(sk.data_schemas),
            len(sk.auth_flows),
            len(sk.integration_points),
        )

        return sk

    def classify_content(self, content: str) -> KnowledgeClassification:
        """
        Classify a piece of content as structural, proprietary, etc.

        Used by the firewall to decide whether content can cross the bridge.
        """
        # Check for credentials first (highest priority block)
        for pattern in _CREDENTIAL_PATTERNS:
            if re.search(pattern, content, re.IGNORECASE):
                return KnowledgeClassification.CREDENTIAL

        # Check for PII
        for pattern in _PII_PATTERNS:
            if re.search(pattern, content):
                return KnowledgeClassification.PII

        # Check for source code indicators (function bodies, class implementations)
        source_indicators = [
            r"def\s+\w+\s*\(.*\)\s*:",         # Python function
            r"function\s+\w+\s*\(.*\)\s*\{",    # JS function
            r"public\s+\w+\s+\w+\s*\(.*\)\s*\{",  # Java method
            r"func\s+\w+\s*\(.*\)\s*\{",        # Go function
        ]
        source_matches = sum(
            1 for p in source_indicators if re.search(p, content)
        )
        if source_matches >= 2:  # Multiple function bodies = source code
            return KnowledgeClassification.SOURCE_CODE

        # Check for proprietary indicators
        proprietary_score = sum(
            1 for p in _PROPRIETARY_INDICATORS
            if re.search(p, content, re.IGNORECASE)
        )
        structural_score = sum(
            1 for p in _STRUCTURAL_INDICATORS
            if re.search(p, content, re.IGNORECASE)
        )

        if proprietary_score > structural_score:
            return KnowledgeClassification.PROPRIETARY

        return KnowledgeClassification.STRUCTURAL

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _extract_parameters(self, route: Dict[str, Any]) -> List[Dict[str, str]]:
        """Extract parameter definitions from a route."""
        params = []
        for p in route.get("parameters", []):
            params.append({
                "name": p.get("name", ""),
                "type": p.get("type", "string"),
                "location": p.get("in", "query"),  # query, path, body, header
                "required": p.get("required", False),
            })
        return params

    def _sanitize_schema(self, schema: Dict[str, Any]) -> Dict[str, Any]:
        """Remove any actual data values from a schema, keeping only structure."""
        if not schema:
            return {}

        sanitized = {}
        for key, value in schema.items():
            if key in ("example", "default", "enum_values", "sample"):
                continue  # Strip examples and defaults (could contain business logic)
            if isinstance(value, dict):
                sanitized[key] = self._sanitize_schema(value)
            elif isinstance(value, list) and value and isinstance(value[0], dict):
                sanitized[key] = [self._sanitize_schema(v) for v in value]
            elif isinstance(value, str):
                sanitized[key] = self._redact_credentials(value)
            else:
                sanitized[key] = value

        return sanitized

    def _redact_credentials(self, text: str) -> str:
        """Remove anything that looks like a credential from text."""
        if not isinstance(text, str):
            return text

        for pattern in _CREDENTIAL_PATTERNS:
            text = re.sub(pattern, "[REDACTED]", text, flags=re.IGNORECASE)

        return text

    def content_hash(self, content: Any) -> str:
        """Generate SHA-256 hash of content for audit trail."""
        if isinstance(content, (dict, list)):
            content = json.dumps(content, sort_keys=True, default=str)
        return hashlib.sha256(str(content).encode()).hexdigest()

    @property
    def extraction_count(self) -> int:
        """Number of extractions performed."""
        return len(self._extractions)
