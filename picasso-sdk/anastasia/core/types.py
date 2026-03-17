"""
Core Types — Data models for ANASTASiA's intelligence platform.

These types are the shared vocabulary across all neurons. Every module
that stores, processes, or transmits system knowledge uses these types.

MYSTES KYRIOS LLC — Confidential.
"""

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class IntegrationMode(Enum):
    """How ANASTASiA connects to a customer's platform."""
    API_ONLY = "api_only"           # Free/Trial — REST endpoints, they build UI
    EMBED_WIDGET = "embed_widget"   # Pro — drop-in widget + managed service
    CODEBASE_AI = "codebase_ai"     # Enterprise — daemon + AI code generation


class TenantTier(Enum):
    """Hierarchy levels in multi-tenant architecture."""
    MASTER = "master"               # MYSTES KYRIOS LLC
    CONSOLIDATOR = "consolidator"   # e.g., AERTiCKET
    AGENCY = "agency"               # Individual travel agency


class ApprovalStatus(Enum):
    """Status of a proposed change."""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    ROLLED_BACK = "rolled_back"


class PaymentProcessor(Enum):
    """Known payment processors ANASTASiA can adapt to."""
    STRIPE = "stripe"
    ADYEN = "adyen"
    SQUARE = "square"
    PAYPAL = "paypal"
    BRAINTREE = "braintree"
    WORLDPAY = "worldpay"
    CHECKOUT_COM = "checkout_com"
    RAZORPAY = "razorpay"
    MOLLIE = "mollie"
    CUSTOM = "custom"
    UNKNOWN = "unknown"


class SystemProtocol(Enum):
    """API protocol types."""
    REST = "rest"
    SOAP = "soap"
    GRAPHQL = "graphql"
    GRPC = "grpc"
    WEBSOCKET = "websocket"
    CUSTOM = "custom"


class AuthMethod(Enum):
    """Authentication methods."""
    API_KEY = "api_key"
    OAUTH2 = "oauth2"
    SESSION_COOKIE = "session_cookie"
    JWT = "jwt"
    BASIC = "basic"
    HMAC = "hmac"
    SAML = "saml"
    CUSTOM = "custom"


class VerticalType(Enum):
    """Travel vertical types ANASTASiA can learn."""
    FLIGHTS = "flights"
    HOTELS = "hotels"
    CAR_RENTAL = "car_rental"
    CRUISES = "cruises"
    INSURANCE = "insurance"
    TRANSFERS = "transfers"
    ACTIVITIES = "activities"
    RAIL = "rail"
    CUSTOM = "custom"


class BridgeState(Enum):
    """Lifecycle states of a daemon bridge."""
    PENDING = "pending"             # Contract created, awaiting both parties
    NEGOTIATING = "negotiating"     # One side accepted, waiting for other
    ACTIVE = "active"               # Both daemons connected, bridge operational
    PAUSED = "paused"               # Temporarily suspended (maintenance, dispute)
    TERMINATED = "terminated"       # Permanently ended


class KnowledgeClassification(Enum):
    """Classification of information crossing the bridge."""
    STRUCTURAL = "structural"       # Safe: API patterns, schemas, auth flows
    FUNCTIONAL = "functional"       # Safe: how the system works (not WHY)
    PROPRIETARY = "proprietary"     # BLOCKED: business logic, algorithms, trade secrets
    CREDENTIAL = "credential"       # BLOCKED: passwords, keys, tokens
    PII = "pii"                     # BLOCKED: personal identifiable information
    SOURCE_CODE = "source_code"     # BLOCKED: verbatim source code


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class TechStack:
    """Detected technology stack of a customer's platform."""
    language: str = ""                          # python, javascript, java, php, etc.
    framework: str = ""                         # flask, django, nextjs, laravel, spring, etc.
    database: str = ""                          # postgresql, mysql, mongodb, etc.
    cache: str = ""                             # redis, memcached, etc.
    ui_framework: str = ""                      # react, vue, angular, jquery, etc.
    css_framework: str = ""                     # tailwind, bootstrap, material-ui, etc.
    package_manager: str = ""                   # pip, npm, yarn, composer, maven, etc.
    containerized: bool = False                 # docker, kubernetes
    ci_cd: str = ""                             # github-actions, gitlab-ci, jenkins, etc.
    hosting: str = ""                           # aws, gcp, azure, vercel, heroku, etc.
    detected_files: Dict[str, str] = field(default_factory=dict)  # filename -> purpose
    confidence: float = 0.0                     # 0.0-1.0 detection confidence

    def to_dict(self) -> dict:
        return {
            "language": self.language,
            "framework": self.framework,
            "database": self.database,
            "cache": self.cache,
            "ui_framework": self.ui_framework,
            "css_framework": self.css_framework,
            "package_manager": self.package_manager,
            "containerized": self.containerized,
            "ci_cd": self.ci_cd,
            "hosting": self.hosting,
            "detected_files": self.detected_files,
            "confidence": self.confidence,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TechStack":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class BookingFlow:
    """Documented booking flow for a system."""
    steps: List[Dict[str, Any]] = field(default_factory=list)
    # Each step: {"order": 1, "name": "search", "endpoint": "/api/search",
    #             "method": "POST", "required_fields": [...], "notes": "..."}
    total_steps: int = 0
    estimated_time_seconds: float = 0.0
    requires_auth: bool = True
    supports_guest: bool = False

    def to_dict(self) -> dict:
        return {
            "steps": self.steps,
            "total_steps": self.total_steps,
            "estimated_time_seconds": self.estimated_time_seconds,
            "requires_auth": self.requires_auth,
            "supports_guest": self.supports_guest,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "BookingFlow":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class SystemQuirk:
    """Undocumented behavior or gotcha discovered during integration."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    description: str = ""
    category: str = ""              # auth, pagination, encoding, timeout, etc.
    severity: str = "info"          # info, warning, critical
    workaround: str = ""
    discovered_at: float = field(default_factory=time.time)
    discovered_by: str = ""         # agency_id that first encountered it

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "description": self.description,
            "category": self.category,
            "severity": self.severity,
            "workaround": self.workaround,
            "discovered_at": self.discovered_at,
            "discovered_by": self.discovered_by,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SystemQuirk":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class AdapterPattern:
    """Tested integration adapter for a specific system + payment/auth combo."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    system_name: str = ""           # e.g., "redbox", "sabre", "hotelbeds"
    component: str = ""             # "payment", "auth", "booking", "search"
    target: str = ""                # e.g., "stripe", "oauth2", "react"
    pattern_code: str = ""          # Template/pseudocode for the adapter
    language: str = ""              # What language the adapter is in
    tested: bool = False
    test_results: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "system_name": self.system_name,
            "component": self.component,
            "target": self.target,
            "pattern_code": self.pattern_code,
            "language": self.language,
            "tested": self.tested,
            "test_results": self.test_results,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AdapterPattern":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class SystemProfile:
    """
    Complete learned profile of an external system.

    This is ANASTASiA's core IP — the accumulated knowledge of how a system
    works, gathered through customer installations. Retained permanently
    regardless of customer status.

    Stores FUNCTIONAL KNOWLEDGE (API patterns, schemas, auth flows, quirks),
    NOT proprietary business logic or source code.
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""                              # e.g., "Redbox", "Sabre", "Hotelbeds"
    vendor: str = ""                            # e.g., "AERTiCKET", "Sabre Corp"
    version: str = ""                           # API version if known
    vertical: str = "flights"                   # VerticalType value
    protocol: str = "rest"                      # SystemProtocol value
    base_url: str = ""                          # API base URL pattern
    auth_method: str = "api_key"                # AuthMethod value
    auth_details: Dict[str, Any] = field(default_factory=dict)
    # {"token_endpoint": "...", "refresh_flow": "...", "scopes": [...]}

    booking_flow: Optional[BookingFlow] = None
    endpoints: List[Dict[str, Any]] = field(default_factory=list)
    # Each: {"path": "/api/...", "method": "POST", "purpose": "...",
    #        "request_schema": {...}, "response_schema": {...}, "notes": "..."}

    data_schemas: Dict[str, Any] = field(default_factory=dict)
    # Key data structures: {"flight": {...}, "booking": {...}, "passenger": {...}}

    quirks: List[SystemQuirk] = field(default_factory=list)
    adapters: List[AdapterPattern] = field(default_factory=list)

    # Metadata
    readiness: str = "discovered"               # discovered, probed, documented, tested, production
    confidence: float = 0.0                     # 0.0-1.0 overall confidence
    installations: int = 0                      # How many agencies use this profile
    first_learned: float = field(default_factory=time.time)
    last_updated: float = field(default_factory=time.time)
    learned_from: List[str] = field(default_factory=list)  # agency_ids (anonymized)
    tags: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "vendor": self.vendor,
            "version": self.version,
            "vertical": self.vertical,
            "protocol": self.protocol,
            "base_url": self.base_url,
            "auth_method": self.auth_method,
            "auth_details": self.auth_details,
            "booking_flow": self.booking_flow.to_dict() if self.booking_flow else None,
            "endpoints": self.endpoints,
            "data_schemas": self.data_schemas,
            "quirks": [q.to_dict() for q in self.quirks],
            "adapters": [a.to_dict() for a in self.adapters],
            "readiness": self.readiness,
            "confidence": self.confidence,
            "installations": self.installations,
            "first_learned": self.first_learned,
            "last_updated": self.last_updated,
            "learned_from": self.learned_from,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SystemProfile":
        profile = cls()
        for key, value in data.items():
            if key == "booking_flow" and value:
                profile.booking_flow = BookingFlow.from_dict(value)
            elif key == "quirks" and isinstance(value, list):
                profile.quirks = [SystemQuirk.from_dict(q) for q in value]
            elif key == "adapters" and isinstance(value, list):
                profile.adapters = [AdapterPattern.from_dict(a) for a in value]
            elif hasattr(profile, key):
                setattr(profile, key, value)
        return profile


@dataclass
class BridgeContract:
    """
    Agreement between two entities for a daemon bridge.

    Defines what structural knowledge each side shares, what operations
    the bridge can perform, IP ownership terms, and audit requirements.
    Both entities must accept before the bridge activates.
    """
    id: str = field(default_factory=lambda: f"bc_{uuid.uuid4().hex[:16]}")
    entity_a_id: str = ""               # Daemon ID / org ID for side A
    entity_b_id: str = ""               # Daemon ID / org ID for side B
    entity_a_name: str = ""             # Human-readable name (e.g., "MYSTES KYRIOS")
    entity_b_name: str = ""             # Human-readable name (e.g., "AERTiCKET")

    # What each side agrees to share (structural knowledge categories)
    entity_a_shares: List[str] = field(default_factory=lambda: [
        "api_patterns", "data_schemas", "auth_flows", "tech_stack",
    ])
    entity_b_shares: List[str] = field(default_factory=lambda: [
        "api_patterns", "data_schemas", "auth_flows", "tech_stack",
    ])

    # What the bridge can do on each side
    entity_a_allowed_actions: List[str] = field(default_factory=lambda: [
        "propose_file_create", "propose_file_modify", "propose_config_change",
    ])
    entity_b_allowed_actions: List[str] = field(default_factory=lambda: [
        "propose_file_create", "propose_file_modify", "propose_config_change",
    ])

    # IP ownership: code built on side A belongs to entity A, and vice versa
    ip_ownership: str = "bilateral"     # bilateral | entity_a | entity_b | shared
    audit_required: bool = True
    staging_required: bool = True       # All changes go to staging first

    # Contract status
    state: str = "pending"              # BridgeState value
    entity_a_accepted: bool = False
    entity_b_accepted: bool = False
    created_at: float = field(default_factory=time.time)
    activated_at: Optional[float] = None
    terminated_at: Optional[float] = None
    termination_reason: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "entity_a_id": self.entity_a_id,
            "entity_b_id": self.entity_b_id,
            "entity_a_name": self.entity_a_name,
            "entity_b_name": self.entity_b_name,
            "entity_a_shares": self.entity_a_shares,
            "entity_b_shares": self.entity_b_shares,
            "entity_a_allowed_actions": self.entity_a_allowed_actions,
            "entity_b_allowed_actions": self.entity_b_allowed_actions,
            "ip_ownership": self.ip_ownership,
            "audit_required": self.audit_required,
            "staging_required": self.staging_required,
            "state": self.state,
            "entity_a_accepted": self.entity_a_accepted,
            "entity_b_accepted": self.entity_b_accepted,
            "created_at": self.created_at,
            "activated_at": self.activated_at,
            "terminated_at": self.terminated_at,
            "termination_reason": self.termination_reason,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "BridgeContract":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class StructuralKnowledge:
    """
    Structural knowledge extracted from a codebase — what crosses the bridge.

    This is FUNCTIONAL knowledge: how a system works, what APIs exist,
    what data structures are used. NOT proprietary logic, source code, or secrets.
    """
    id: str = field(default_factory=lambda: f"sk_{uuid.uuid4().hex[:12]}")
    entity_id: str = ""                 # Who this knowledge belongs to
    bridge_id: str = ""                 # Which bridge this is for

    # Structural artifacts
    api_patterns: List[Dict[str, Any]] = field(default_factory=list)
    # Each: {"endpoint": "/api/...", "method": "POST", "purpose": "...",
    #        "request_schema": {...}, "response_schema": {...}}

    data_schemas: Dict[str, Any] = field(default_factory=dict)
    # Table/model structures: {"users": {"columns": [...]}, "bookings": {...}}

    auth_flows: List[Dict[str, Any]] = field(default_factory=list)
    # {"type": "oauth2", "token_endpoint": "...", "refresh": True}

    integration_points: List[Dict[str, Any]] = field(default_factory=list)
    # Where systems connect: {"type": "webhook", "url": "/hooks/...", "events": [...]}

    tech_stack: Optional[Dict[str, Any]] = None
    # Language, framework, database, etc.

    # Metadata
    extracted_at: float = field(default_factory=time.time)
    classification_results: Dict[str, int] = field(default_factory=dict)
    # {"structural": 45, "blocked_proprietary": 3, "blocked_credential": 1}
    redacted_count: int = 0             # How many items were redacted by firewall

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "entity_id": self.entity_id,
            "bridge_id": self.bridge_id,
            "api_patterns": self.api_patterns,
            "data_schemas": self.data_schemas,
            "auth_flows": self.auth_flows,
            "integration_points": self.integration_points,
            "tech_stack": self.tech_stack,
            "extracted_at": self.extracted_at,
            "classification_results": self.classification_results,
            "redacted_count": self.redacted_count,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "StructuralKnowledge":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class BridgeProposal:
    """
    A proposed change generated by the bridge for ONE side of the bridge.

    Entity A only sees proposals for their codebase.
    Entity B only sees proposals for their codebase.
    Neither side ever sees the other's proposals or source code.
    """
    id: str = field(default_factory=lambda: f"bp_{uuid.uuid4().hex[:16]}")
    bridge_id: str = ""
    target_entity_id: str = ""          # WHO this proposal is for
    source_context: str = ""            # WHY (integration need), not HOW the other side works

    action_type: str = ""               # file_create, file_modify, config_change
    description: str = ""               # Human-readable: "Add webhook handler for booking events"
    files_affected: List[str] = field(default_factory=list)
    diff: str = ""                      # Proposed changes (for target entity's codebase)
    rationale: str = ""                 # Why this change improves the integration

    # Entity-scoped approval
    status: str = "pending"             # pending, approved, rejected, executed, rolled_back
    approved_by: Optional[str] = None
    approved_at: Optional[float] = None
    executed_at: Optional[float] = None
    execution_result: Optional[Dict[str, Any]] = None

    # Safety
    risk_level: str = "low"             # low, medium, high
    staging_branch: str = ""            # Git branch for staging
    rollback_commit: str = ""           # Commit SHA for rollback

    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "bridge_id": self.bridge_id,
            "target_entity_id": self.target_entity_id,
            "source_context": self.source_context,
            "action_type": self.action_type,
            "description": self.description,
            "files_affected": self.files_affected,
            "diff": self.diff,
            "rationale": self.rationale,
            "status": self.status,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at,
            "executed_at": self.executed_at,
            "execution_result": self.execution_result,
            "risk_level": self.risk_level,
            "staging_branch": self.staging_branch,
            "rollback_commit": self.rollback_commit,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "BridgeProposal":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class FirewallAuditEntry:
    """Audit trail entry for the IP firewall — every byte crossing the bridge is logged."""
    id: str = field(default_factory=lambda: f"fa_{uuid.uuid4().hex[:12]}")
    bridge_id: str = ""
    direction: str = ""                 # "a_to_cloud" | "b_to_cloud" | "cloud_to_a" | "cloud_to_b"
    classification: str = ""            # KnowledgeClassification value
    action: str = ""                    # "allowed" | "blocked" | "redacted"
    content_hash: str = ""              # SHA-256 hash of what crossed (not the content itself)
    content_type: str = ""              # "api_pattern" | "schema" | "auth_flow" | etc.
    size_bytes: int = 0
    reason: str = ""                    # Why it was blocked/redacted (if applicable)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "bridge_id": self.bridge_id,
            "direction": self.direction,
            "classification": self.classification,
            "action": self.action,
            "content_hash": self.content_hash,
            "content_type": self.content_type,
            "size_bytes": self.size_bytes,
            "reason": self.reason,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "FirewallAuditEntry":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class ActionProposal:
    """
    A proposed change that requires admin approval before execution.

    ANASTASiA proposes, humans approve. Never autonomous without oversight.
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    agency_id: str = ""
    action_type: str = ""           # file_create, file_modify, file_delete, config_change, deploy
    description: str = ""           # Human-readable description
    files_affected: List[str] = field(default_factory=list)
    diff: str = ""                  # Unified diff of proposed changes
    rollback_plan: str = ""         # How to undo this change
    risk_level: str = "low"         # low, medium, high, critical
    status: str = "pending"         # ApprovalStatus value
    proposed_at: float = field(default_factory=time.time)
    reviewed_at: Optional[float] = None
    reviewed_by: Optional[str] = None
    execution_result: Optional[Dict[str, Any]] = None
    git_branch: str = ""            # Branch where changes are staged
    git_commit: str = ""            # Commit SHA after staging

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "agency_id": self.agency_id,
            "action_type": self.action_type,
            "description": self.description,
            "files_affected": self.files_affected,
            "diff": self.diff,
            "rollback_plan": self.rollback_plan,
            "risk_level": self.risk_level,
            "status": self.status,
            "proposed_at": self.proposed_at,
            "reviewed_at": self.reviewed_at,
            "reviewed_by": self.reviewed_by,
            "execution_result": self.execution_result,
            "git_branch": self.git_branch,
            "git_commit": self.git_commit,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ActionProposal":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
