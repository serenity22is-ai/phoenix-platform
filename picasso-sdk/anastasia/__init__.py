"""
ANASTASiA — Intelligent Integration Agent.

13-neuron architecture for autonomous travel system integration
and confidential collaborative development.

Each neuron is a specialized module communicating via EventBus.
The Bridge neuron enables bilateral IP-protected co-development
between proprietary codebases — ANASTASiA as the trusted intermediary.

Usage:
    from anastasia import AnastasiaPlatform
    platform = AnastasiaPlatform(config)
    platform.start()

    # Health check
    status = platform.health()

    # Graceful shutdown
    platform.stop()

MYSTES KYRIOS LLC — Confidential.
"""

from .core import (
    EventBus,
    Event,
    EventType,
    ModuleRegistry,
    NeuronModule,
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
from .platform import AnastasiaPlatform

__version__ = "1.2.0"
__all__ = [
    # Platform
    "AnastasiaPlatform",
    # Core types
    "EventBus",
    "Event",
    "EventType",
    "ModuleRegistry",
    "NeuronModule",
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
    # Bridge types
    "BridgeState",
    "KnowledgeClassification",
    "BridgeContract",
    "StructuralKnowledge",
    "BridgeProposal",
    "FirewallAuditEntry",
]
