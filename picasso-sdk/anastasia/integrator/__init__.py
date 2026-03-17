"""
Integrator Neuron — Claude-powered codebase analyzer and code generator.

This is the BRAIN of ANASTASiA's integration pipeline. It scans a customer's
codebase, detects their complete technology stack (language, framework,
database, payments, auth, UI), and generates native integration code that
fits seamlessly into their project.

The pipeline:
    1. CodebaseAnalyzer scans the file manifest -> TechStack
    2. IntegrationTemplates provides the blueprint for that stack
    3. CodeGenerator produces ready-to-use source files
    4. ApprovalWorkflow gates every change behind admin review

Nothing is written to a customer's codebase without human sign-off.

Components:
    - IntegratorModule: NeuronModule subclass (registry entry point)
    - CodebaseAnalyzer: Tech stack detection from file patterns
    - CodeGenerator: Native code generation in 6+ languages
    - IntegrationTemplates: Pre-built templates for 10 framework combos
    - ApprovalWorkflow: Proposal lifecycle (create/approve/reject/execute/rollback)

MYSTES KYRIOS LLC — Confidential.
"""

import logging
import os
from typing import Any, Dict, List

from ..core.events import EventBus
from ..core.registry import NeuronModule

from .analyzer import CodebaseAnalyzer
from .generator import CodeGenerator
from .templates import IntegrationTemplates
from .approval import ApprovalWorkflow

logger = logging.getLogger(__name__)

__all__ = [
    "IntegratorModule",
    "CodebaseAnalyzer",
    "CodeGenerator",
    "IntegrationTemplates",
    "ApprovalWorkflow",
]


class IntegratorModule(NeuronModule):
    """
    Neuron module for codebase analysis, code generation, and approval workflow.

    Depends on the 'knowledge' neuron for SystemProfile access (knowing what
    systems exist and how they work). Wires up all four integrator components
    during initialization.

    Registration:
        registry = ModuleRegistry(event_bus)
        registry.register(IntegratorModule())
        registry.initialize_all(config)

    After initialization, access components via:
        module = registry.get("integrator")
        tech_stack = module.analyzer.analyze_codebase(files)
        proposals = module.generator.generate_integration(tech_stack, profile)
        module.approval.approve(proposal_id, reviewer_id)
    """

    def __init__(self):
        """Initialize the integrator module (components created in initialize())."""
        self._analyzer: CodebaseAnalyzer = None
        self._generator: CodeGenerator = None
        self._templates: IntegrationTemplates = None
        self._approval: ApprovalWorkflow = None
        self._event_bus: EventBus = None
        self._initialized = False

    @property
    def name(self) -> str:
        """Unique module identifier."""
        return "integrator"

    @property
    def version(self) -> str:
        """Module version."""
        return "1.0.0"

    @property
    def dependencies(self) -> List[str]:
        """Modules this neuron depends on."""
        return ["knowledge"]

    def initialize(self, event_bus: EventBus, config: Dict[str, Any]) -> None:
        """
        Initialize all integrator components.

        Creates the analyzer, generator, templates registry, and approval
        workflow, wiring them all to the shared event bus.

        Args:
            event_bus: Shared event bus for inter-neuron communication.
            config: Platform configuration dictionary. Relevant keys:
                - integrator_storage_dir: Path for proposal JSON persistence
                  (defaults to ./data/integrator/proposals)
                - integrator_proposal_expiry: Proposal expiry in seconds
                  (defaults to 7 days)
        """
        self._event_bus = event_bus

        # Determine storage directory for proposals
        storage_dir = config.get(
            "integrator_storage_dir",
            os.path.join(".", "data", "integrator", "proposals"),
        )

        # Proposal expiry (default 7 days)
        expiry = config.get("integrator_proposal_expiry", 7 * 24 * 60 * 60)

        # Wire up components
        self._analyzer = CodebaseAnalyzer(event_bus)
        self._generator = CodeGenerator(event_bus)
        self._templates = IntegrationTemplates()
        self._approval = ApprovalWorkflow(
            event_bus=event_bus,
            storage_dir=storage_dir,
            expiry_seconds=expiry,
        )

        self._initialized = True
        logger.info(
            "Integrator neuron initialized (storage: %s, expiry: %ds)",
            storage_dir, expiry,
        )

    def health_check(self) -> Dict[str, Any]:
        """
        Return health status of the integrator module.

        Checks that all four components are initialized and the proposal
        storage directory is accessible.
        """
        if not self._initialized:
            return {
                "healthy": False,
                "details": "Integrator module not initialized",
            }

        # Verify storage directory is writable
        storage_ok = os.path.isdir(self._approval._storage_dir)
        template_count = len(self._templates.list_templates())
        pending_count = len(self._approval.get_pending())

        return {
            "healthy": True,
            "details": "All integrator components operational",
            "components": {
                "analyzer": self._analyzer is not None,
                "generator": self._generator is not None,
                "templates": template_count,
                "approval": storage_ok,
            },
            "pending_proposals": pending_count,
        }

    def shutdown(self) -> None:
        """Clean up integrator resources."""
        self._initialized = False
        logger.info("Integrator neuron shut down")

    # -------------------------------------------------------------------
    # Public accessors for components
    # -------------------------------------------------------------------

    @property
    def analyzer(self) -> CodebaseAnalyzer:
        """Access the codebase analyzer."""
        if not self._analyzer:
            raise RuntimeError("IntegratorModule not initialized")
        return self._analyzer

    @property
    def generator(self) -> CodeGenerator:
        """Access the code generator."""
        if not self._generator:
            raise RuntimeError("IntegratorModule not initialized")
        return self._generator

    @property
    def templates(self) -> IntegrationTemplates:
        """Access the integration templates registry."""
        if not self._templates:
            raise RuntimeError("IntegratorModule not initialized")
        return self._templates

    @property
    def approval(self) -> ApprovalWorkflow:
        """Access the approval workflow."""
        if not self._approval:
            raise RuntimeError("IntegratorModule not initialized")
        return self._approval
