"""
Module Registry — Registration and lifecycle management for neuron modules.

Each neuron registers itself with the registry on initialization. The
registry handles startup order, dependency resolution, health checks,
and graceful shutdown.

MYSTES KYRIOS LLC — Confidential.
"""

import logging
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Type

from .events import EventBus

logger = logging.getLogger(__name__)


class NeuronModule(ABC):
    """
    Base class for all ANASTASiA neuron modules.

    Every neuron must subclass this and implement:
    - name: Unique module identifier
    - initialize(): Setup logic (called on registration)
    - health_check(): Returns health status dict
    - shutdown(): Cleanup logic
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique module name (e.g., 'knowledge', 'payments', 'daemon')."""
        ...

    @property
    def version(self) -> str:
        """Module version."""
        return "1.0.0"

    @property
    def dependencies(self) -> List[str]:
        """List of module names this neuron depends on."""
        return []

    @abstractmethod
    def initialize(self, event_bus: EventBus, config: Dict[str, Any]) -> None:
        """
        Initialize the module with shared event bus and config.

        Called once during platform startup. Dependencies are guaranteed
        to be initialized before this module.
        """
        ...

    @abstractmethod
    def health_check(self) -> Dict[str, Any]:
        """
        Return health status.

        Must return: {"healthy": bool, "details": str, ...}
        """
        ...

    def shutdown(self) -> None:
        """Cleanup on platform shutdown. Override if needed."""
        pass


class ModuleRegistry:
    """
    Central registry for all ANASTASiA neuron modules.

    Manages module lifecycle:
    1. Registration (register)
    2. Dependency resolution (topological sort)
    3. Initialization (initialize_all)
    4. Health monitoring (health_check_all)
    5. Graceful shutdown (shutdown_all)

    Usage:
        registry = ModuleRegistry(event_bus)
        registry.register(KnowledgeModule())
        registry.register(PaymentsModule())
        registry.initialize_all(config)
    """

    def __init__(self, event_bus: EventBus):
        self._event_bus = event_bus
        self._modules: Dict[str, NeuronModule] = {}
        self._initialized: Dict[str, bool] = {}
        self._init_order: List[str] = []

    def register(self, module: NeuronModule) -> None:
        """Register a neuron module."""
        if module.name in self._modules:
            logger.warning("Module '%s' already registered, replacing", module.name)
        self._modules[module.name] = module
        self._initialized[module.name] = False
        logger.info("Registered neuron: %s v%s", module.name, module.version)

    def get(self, name: str) -> Optional[NeuronModule]:
        """Get a registered module by name."""
        return self._modules.get(name)

    def list_modules(self) -> List[Dict[str, Any]]:
        """List all registered modules with status."""
        return [
            {
                "name": m.name,
                "version": m.version,
                "initialized": self._initialized.get(m.name, False),
                "dependencies": m.dependencies,
            }
            for m in self._modules.values()
        ]

    def _resolve_order(self) -> List[str]:
        """Topological sort of modules by dependencies."""
        visited = set()
        order = []
        visiting = set()  # cycle detection

        def visit(name: str):
            if name in visited:
                return
            if name in visiting:
                raise ValueError(f"Circular dependency detected involving '{name}'")
            visiting.add(name)

            module = self._modules.get(name)
            if module:
                for dep in module.dependencies:
                    if dep not in self._modules:
                        logger.warning(
                            "Module '%s' depends on '%s' which is not registered",
                            name, dep
                        )
                    else:
                        visit(dep)

            visiting.discard(name)
            visited.add(name)
            order.append(name)

        for name in self._modules:
            visit(name)

        return order

    def initialize_all(self, config: Dict[str, Any]) -> Dict[str, bool]:
        """
        Initialize all modules in dependency order.

        Returns dict of module_name -> success.
        """
        self._init_order = self._resolve_order()
        results = {}

        for name in self._init_order:
            module = self._modules[name]
            try:
                start = time.time()
                module.initialize(self._event_bus, config)
                elapsed = time.time() - start
                self._initialized[name] = True
                results[name] = True
                logger.info(
                    "Initialized neuron '%s' in %.1fms", name, elapsed * 1000
                )
            except Exception as e:
                self._initialized[name] = False
                results[name] = False
                logger.error("Failed to initialize neuron '%s': %s", name, e)

        return results

    def health_check_all(self) -> Dict[str, Dict[str, Any]]:
        """Run health checks on all initialized modules."""
        results = {}
        for name, module in self._modules.items():
            if not self._initialized.get(name, False):
                results[name] = {"healthy": False, "details": "Not initialized"}
                continue
            try:
                results[name] = module.health_check()
            except Exception as e:
                results[name] = {"healthy": False, "details": f"Health check error: {e}"}
        return results

    def shutdown_all(self) -> None:
        """Shutdown all modules in reverse initialization order."""
        for name in reversed(self._init_order):
            module = self._modules.get(name)
            if module and self._initialized.get(name, False):
                try:
                    module.shutdown()
                    logger.info("Shutdown neuron: %s", name)
                except Exception as e:
                    logger.error("Error shutting down '%s': %s", name, e)
                self._initialized[name] = False
