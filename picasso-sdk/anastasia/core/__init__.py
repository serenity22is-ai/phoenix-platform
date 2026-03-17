"""
Core — Foundation types, event bus, and module registry.

Every ANASTASiA neuron depends on this module. It provides:
- EventBus: Publish/subscribe system for inter-module communication
- SystemProfile: Data model for learned system architectures
- ModuleRegistry: Registration and discovery of neuron modules
- Shared enums and type definitions

MYSTES KYRIOS LLC — Confidential.
"""

from .types import (
    SystemProfile,
    IntegrationMode,
    TechStack,
    PaymentProcessor,
    BookingFlow,
    SystemQuirk,
    AdapterPattern,
    TenantTier,
    ActionProposal,
    ApprovalStatus,
    BridgeState,
    KnowledgeClassification,
    BridgeContract,
    StructuralKnowledge,
    BridgeProposal,
    FirewallAuditEntry,
)
from .events import EventBus, Event, EventType
from .registry import ModuleRegistry, NeuronModule

__all__ = [
    "SystemProfile",
    "IntegrationMode",
    "TechStack",
    "PaymentProcessor",
    "BookingFlow",
    "SystemQuirk",
    "AdapterPattern",
    "TenantTier",
    "ActionProposal",
    "ApprovalStatus",
    "BridgeState",
    "KnowledgeClassification",
    "BridgeContract",
    "StructuralKnowledge",
    "BridgeProposal",
    "FirewallAuditEntry",
    "EventBus",
    "Event",
    "EventType",
    "ModuleRegistry",
    "NeuronModule",
]
