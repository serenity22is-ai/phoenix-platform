"""
ANASTASiA Platform — Bootstrap and lifecycle management for the neuron network.

This is the ignition system. It creates the EventBus, registers all 18 neurons
in dependency order, initializes them, and provides health/shutdown lifecycle.

Usage:
    from anastasia import AnastasiaPlatform

    platform = AnastasiaPlatform({
        "data_dir": "/var/anastasia",
        "daemon.cloud_url": "https://anastasia-api.onrender.com",
        "daemon.api_key": "ana_...",
    })
    platform.start()

    # Check health of all neurons
    health = platform.health()

    # Access individual neurons
    knowledge = platform.get_module("knowledge")

    # Graceful shutdown
    platform.stop()

MYSTES KYRIOS LLC — Confidential.
"""

import atexit
import logging
import os
import time
from typing import Any, Dict, List, Optional

from .core import EventBus, Event, EventType, ModuleRegistry, NeuronModule

logger = logging.getLogger(__name__)


# Default config — sensible defaults for all neurons
DEFAULT_CONFIG = {
    # Base data directory (all neurons store data under this)
    "data_dir": os.path.expanduser("~/.anastasia"),

    # Knowledge
    "profiles_dir": None,  # Falls back to data_dir/profiles

    # Daemon
    "daemon.workspace": ".",
    "daemon.cloud_url": "",
    "daemon.api_key": "",
    "daemon.daemon_id": "",
    "daemon.permissions": {},

    # Integrator
    "integrator_storage_dir": None,  # Falls back to data_dir/integrator/proposals
    "integrator_proposal_expiry": 604800,  # 7 days

    # Payments
    "payments.log_dir": None,  # Falls back to data_dir/payments/logs

    # Intelligence
    "intelligence_storage_dir": None,  # Falls back to data_dir/intelligence

    # Resilience
    "resilience_cache_dir": None,
    "resilience_cache_ttl": 3600,
    "resilience_cache_max_bytes": 100 * 1024 * 1024,  # 100MB
    "resilience_queue_dir": None,
    "resilience_queue_max_size": 1000,
    "resilience_health_interval": 30,

    # Tenancy
    "tenancy_storage_dir": None,
    "tenancy_usage_dir": None,

    # Compliance
    "compliance_audit_dir": None,

    # Credits
    "credits_storage_dir": None,

    # Portability
    "portability_storage_dir": None,

    # Sandbox
    "sandbox_storage_dir": None,

    # Credentials (federated credential network)
    "credentials_dir": None,
    "credentials_master_key": None,
    "network_dir": None,
    "revenue_dir": None,
}


class AnastasiaPlatform:
    """
    ANASTASiA Platform — Orchestrates the 18-neuron intelligent integration network.

    Lifecycle:
        1. __init__() — Creates EventBus, prepares config
        2. start() — Registers and initializes all neurons in dependency order
        3. health() — Returns health status of all neurons
        4. stop() — Graceful shutdown in reverse order

    The platform can also be used as a context manager:
        with AnastasiaPlatform(config) as platform:
            # neurons are running
            pass
        # neurons are shut down
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self._config = {**DEFAULT_CONFIG, **(config or {})}
        self._resolve_paths()
        self._event_bus = EventBus()
        self._registry = ModuleRegistry(self._event_bus)
        self._started = False
        self._start_time: Optional[float] = None

        # Register shutdown hook
        atexit.register(self._atexit_shutdown)

    def _resolve_paths(self):
        """Resolve None paths to data_dir-relative defaults."""
        data_dir = self._config["data_dir"]
        os.makedirs(data_dir, exist_ok=True)

        path_defaults = {
            "profiles_dir": "profiles",
            "integrator_storage_dir": "integrator/proposals",
            "payments.log_dir": "payments/logs",
            "intelligence_storage_dir": "intelligence",
            "resilience_cache_dir": "resilience/cache",
            "resilience_queue_dir": "resilience/queue",
            "tenancy_storage_dir": "tenants",
            "tenancy_usage_dir": "tenancy_usage",
            "compliance_audit_dir": "compliance_audit",
            "credits_storage_dir": "credits",
            "portability_storage_dir": "exports",
            "sandbox_storage_dir": "sandboxes",
            "credentials_dir": "credentials",
            "network_dir": "network",
            "revenue_dir": "revenue",
        }

        for key, subdir in path_defaults.items():
            if self._config.get(key) is None:
                self._config[key] = os.path.join(data_dir, subdir)

    def start(self, modules: Optional[List[str]] = None) -> Dict[str, bool]:
        """
        Start the neuron network.

        Args:
            modules: Optional list of module names to start. If None, starts all 12.
                     Use this for lightweight deployments (e.g., API-only doesn't
                     need daemon or sandbox).

        Returns:
            Dict of module_name -> initialized (True/False)
        """
        if self._started:
            logger.warning("Platform already started")
            return {}

        logger.info("=" * 60)
        logger.info("ANASTASiA Platform starting...")
        logger.info("=" * 60)

        start = time.time()

        # Register neurons
        registered = self._register_neurons(modules)
        logger.info("Registered %d neurons", len(registered))

        # Initialize all in dependency order
        results = self._registry.initialize_all(self._config)

        # Log results
        succeeded = sum(1 for v in results.values() if v)
        failed = sum(1 for v in results.values() if not v)

        elapsed = time.time() - start
        self._started = True
        self._start_time = time.time()

        logger.info("-" * 60)
        logger.info(
            "ANASTASiA Platform started: %d/%d neurons online (%.1fms)",
            succeeded, succeeded + failed, elapsed * 1000
        )
        if failed:
            failed_names = [k for k, v in results.items() if not v]
            logger.warning("Failed neurons: %s", ", ".join(failed_names))
        logger.info("=" * 60)

        # Publish platform started event
        self._event_bus.publish(Event(
            type=EventType.CUSTOM,
            source="platform",
            data={
                "action": "platform_started",
                "neurons_online": succeeded,
                "neurons_failed": failed,
                "startup_ms": round(elapsed * 1000, 1),
            },
        ))

        return results

    def _register_neurons(self, module_filter: Optional[List[str]] = None) -> List[str]:
        """Register neuron modules. Import each lazily to avoid import errors."""
        registered = []

        # Define all neurons and their import paths
        # Core neurons (platform infrastructure):
        neuron_specs = [
            ("knowledge", "anastasia.knowledge", "KnowledgeModule"),
            ("daemon", "anastasia.daemon", "DaemonModule"),
            ("integrator", "anastasia.integrator", "IntegratorModule"),
            ("payments", "anastasia.payments", "PaymentsModule"),
            ("intelligence", "anastasia.intelligence", "IntelligenceModule"),
            ("resilience", "anastasia.resilience", "ResilienceModule"),
            ("tenancy", "anastasia.tenancy", "TenancyModule"),
            ("compliance", "anastasia.compliance", "ComplianceModule"),
            ("credits", "anastasia.credits", "CreditsModule"),
            ("portability", "anastasia.portability", "PortabilityModule"),
            ("sandbox", "anastasia.sandbox", "SandboxModule"),
            ("bridge", "anastasia.bridge", "BridgeModule"),
            ("credentials", "anastasia.credentials", "CredentialModule"),
            ("saas", "anastasia.saas", "SaaSModule"),
            ("devterminal", "anastasia.devterminal", "DevTerminalModule"),
            # Cross-vertical orchestration:
            ("search", "anastasia.search", "SearchModule"),
            # Vertical neurons (travel verticals — each manages its own API modules):
            ("flights", "anastasia.verticals.flights", "FlightsNeuron"),
            ("hotels", "anastasia.verticals.hotels", "HotelsNeuron"),
        ]

        for name, module_path, class_name in neuron_specs:
            if module_filter and name not in module_filter:
                continue

            try:
                import importlib
                mod = importlib.import_module(module_path)
                cls = getattr(mod, class_name)
                instance = cls()
                self._registry.register(instance)
                registered.append(name)
            except Exception as e:
                logger.error("Failed to register neuron '%s': %s", name, e)

        return registered

    def stop(self):
        """Graceful shutdown of all neurons in reverse order."""
        if not self._started:
            return

        logger.info("ANASTASiA Platform shutting down...")

        # Publish shutdown event before stopping
        self._event_bus.publish(Event(
            type=EventType.CUSTOM,
            source="platform",
            data={"action": "platform_stopping"},
        ))

        self._registry.shutdown_all()
        self._started = False

        uptime = time.time() - self._start_time if self._start_time else 0
        logger.info(
            "ANASTASiA Platform stopped (uptime: %.1f minutes)",
            uptime / 60
        )

    def health(self) -> Dict[str, Any]:
        """
        Get health status of all neurons.

        Returns:
            {
                "platform": "healthy" | "degraded" | "critical",
                "uptime_seconds": 3600,
                "neurons": {
                    "knowledge": {"healthy": True, "details": "..."},
                    ...
                }
            }
        """
        if not self._started:
            return {
                "platform": "stopped",
                "uptime_seconds": 0,
                "neurons": {},
            }

        neuron_health = self._registry.health_check_all()

        total = len(neuron_health)
        healthy_count = sum(1 for v in neuron_health.values() if v.get("healthy"))

        if healthy_count == total:
            status = "healthy"
        elif healthy_count >= total * 0.5:
            status = "degraded"
        else:
            status = "critical"

        return {
            "platform": status,
            "uptime_seconds": round(time.time() - self._start_time, 1) if self._start_time else 0,
            "neurons_online": healthy_count,
            "neurons_total": total,
            "neurons": neuron_health,
        }

    def get_module(self, name: str) -> Optional[NeuronModule]:
        """Get a specific neuron module by name."""
        return self._registry.get(name)

    def get_event_bus(self) -> EventBus:
        """Get the shared event bus."""
        return self._event_bus

    def get_registry(self) -> ModuleRegistry:
        """Get the module registry."""
        return self._registry

    def list_modules(self) -> List[Dict[str, Any]]:
        """List all registered modules with status."""
        return self._registry.list_modules()

    @property
    def is_running(self) -> bool:
        """Whether the platform is currently running."""
        return self._started

    def _atexit_shutdown(self):
        """Ensure clean shutdown on process exit."""
        if self._started:
            try:
                self.stop()
            except Exception:
                pass

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
        return False
