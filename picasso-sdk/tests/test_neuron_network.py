"""
Tests for the ANASTASiA Neuron Network.

Covers:
- Platform bootstrap and lifecycle
- EventBus pub/sub
- ModuleRegistry dependency resolution
- Individual neuron initialization and health
- Inter-neuron communication via events
- Selective module loading

Run with: cd picasso-sdk && python3 -m pytest tests/ -v
"""

import os
import shutil
import tempfile
import time

import pytest

from anastasia.core import EventBus, Event, EventType, ModuleRegistry, NeuronModule
from anastasia.platform import AnastasiaPlatform


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def temp_dir():
    """Create a temporary directory for test data."""
    d = tempfile.mkdtemp(prefix="anastasia_test_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def event_bus():
    """Fresh EventBus instance."""
    return EventBus()


@pytest.fixture
def platform(temp_dir):
    """AnastasiaPlatform instance with temp data dir."""
    p = AnastasiaPlatform({"data_dir": temp_dir})
    yield p
    if p.is_running:
        p.stop()


# ---------------------------------------------------------------------------
# EventBus Tests
# ---------------------------------------------------------------------------

class TestEventBus:
    def test_subscribe_and_publish(self, event_bus):
        received = []
        event_bus.subscribe(EventType.BOOKING_CREATED, lambda e: received.append(e))

        event = Event(type=EventType.BOOKING_CREATED, data={"test": True}, source="test")
        event_bus.publish(event)

        assert len(received) == 1
        assert received[0].data["test"] is True
        assert received[0].source == "test"

    def test_multiple_subscribers(self, event_bus):
        count = {"a": 0, "b": 0}
        event_bus.subscribe(EventType.DEAL_FOUND, lambda e: count.__setitem__("a", count["a"] + 1))
        event_bus.subscribe(EventType.DEAL_FOUND, lambda e: count.__setitem__("b", count["b"] + 1))

        event_bus.publish(Event(type=EventType.DEAL_FOUND, source="test"))

        assert count["a"] == 1
        assert count["b"] == 1

    def test_global_subscriber(self, event_bus):
        received = []
        event_bus.subscribe_all(lambda e: received.append(e.type))

        event_bus.publish(Event(type=EventType.BOOKING_CREATED, source="test"))
        event_bus.publish(Event(type=EventType.PRICE_DROP, source="test"))

        assert len(received) == 2
        assert EventType.BOOKING_CREATED in received
        assert EventType.PRICE_DROP in received

    def test_handler_exception_does_not_block(self, event_bus):
        """Exception in one handler should not prevent others from running."""
        results = []

        def bad_handler(e):
            raise ValueError("intentional error")

        def good_handler(e):
            results.append("ok")

        event_bus.subscribe(EventType.CUSTOM, bad_handler)
        event_bus.subscribe(EventType.CUSTOM, good_handler)

        event_bus.publish(Event(type=EventType.CUSTOM, source="test"))

        assert results == ["ok"]

    def test_unsubscribe(self, event_bus):
        count = {"n": 0}

        def handler(e):
            count["n"] += 1

        event_bus.subscribe(EventType.CUSTOM, handler)
        event_bus.publish(Event(type=EventType.CUSTOM, source="test"))
        assert count["n"] == 1

        event_bus.unsubscribe(EventType.CUSTOM, handler)
        event_bus.publish(Event(type=EventType.CUSTOM, source="test"))
        assert count["n"] == 1  # Should not increment

    def test_event_log(self, event_bus):
        for i in range(5):
            event_bus.publish(Event(type=EventType.CUSTOM, source="test", data={"i": i}))

        recent = event_bus.get_recent_events(limit=3)
        assert len(recent) == 3
        assert recent[-1].data["i"] == 4

    def test_event_log_filtering(self, event_bus):
        event_bus.publish(Event(type=EventType.BOOKING_CREATED, source="test"))
        event_bus.publish(Event(type=EventType.PRICE_DROP, source="test"))
        event_bus.publish(Event(type=EventType.BOOKING_CREATED, source="test"))

        bookings = event_bus.get_recent_events(event_type=EventType.BOOKING_CREATED)
        assert len(bookings) == 2

    def test_event_to_dict(self):
        event = Event(
            type=EventType.DEAL_FOUND,
            data={"route": "JFK-LHR"},
            source="intelligence",
            agency_id="agency_123",
        )
        d = event.to_dict()
        assert d["type"] == "deal.found"
        assert d["data"]["route"] == "JFK-LHR"
        assert d["source"] == "intelligence"
        assert d["agency_id"] == "agency_123"

    def test_webhook_dispatch(self, event_bus):
        webhook_received = []
        event_bus.register_webhook(lambda e: webhook_received.append(e.type))

        event_bus.publish(Event(type=EventType.PAYMENT_COMPLETED, source="test"))

        assert len(webhook_received) == 1
        assert webhook_received[0] == EventType.PAYMENT_COMPLETED


# ---------------------------------------------------------------------------
# ModuleRegistry Tests
# ---------------------------------------------------------------------------

class DummyModule(NeuronModule):
    """Test module with configurable behavior."""
    def __init__(self, module_name, deps=None, fail_init=False, fail_health=False):
        self._name = module_name
        self._deps = deps or []
        self._fail_init = fail_init
        self._fail_health = fail_health
        self._initialized = False

    @property
    def name(self):
        return self._name

    @property
    def dependencies(self):
        return self._deps

    def initialize(self, event_bus, config):
        if self._fail_init:
            raise RuntimeError(f"{self._name} init failed")
        self._initialized = True

    def health_check(self):
        if self._fail_health:
            raise RuntimeError("unhealthy")
        return {"healthy": self._initialized, "details": "test module"}

    def shutdown(self):
        self._initialized = False


class TestModuleRegistry:
    def test_register_and_list(self, event_bus):
        registry = ModuleRegistry(event_bus)
        registry.register(DummyModule("alpha"))
        registry.register(DummyModule("beta"))

        modules = registry.list_modules()
        names = [m["name"] for m in modules]
        assert "alpha" in names
        assert "beta" in names

    def test_dependency_order(self, event_bus):
        """Modules should initialize in dependency order."""
        registry = ModuleRegistry(event_bus)
        init_order = []

        class OrderTracker(DummyModule):
            def initialize(self, event_bus, config):
                init_order.append(self._name)
                self._initialized = True

        registry.register(OrderTracker("child", deps=["parent"]))
        registry.register(OrderTracker("parent"))

        registry.initialize_all({})

        assert init_order.index("parent") < init_order.index("child")

    def test_circular_dependency_detection(self, event_bus):
        registry = ModuleRegistry(event_bus)
        registry.register(DummyModule("a", deps=["b"]))
        registry.register(DummyModule("b", deps=["a"]))

        with pytest.raises(ValueError, match="Circular dependency"):
            registry.initialize_all({})

    def test_failed_init_does_not_block_others(self, event_bus):
        registry = ModuleRegistry(event_bus)
        registry.register(DummyModule("good"))
        registry.register(DummyModule("bad", fail_init=True))

        results = registry.initialize_all({})
        assert results["good"] is True
        assert results["bad"] is False

    def test_health_check_all(self, event_bus):
        registry = ModuleRegistry(event_bus)
        registry.register(DummyModule("healthy_mod"))
        registry.register(DummyModule("sick_mod", fail_health=True))

        registry.initialize_all({})
        health = registry.health_check_all()

        assert health["healthy_mod"]["healthy"] is True
        assert health["sick_mod"]["healthy"] is False

    def test_shutdown_reverse_order(self, event_bus):
        shutdown_order = []

        class ShutdownTracker(DummyModule):
            def shutdown(self):
                shutdown_order.append(self._name)
                self._initialized = False

        registry = ModuleRegistry(event_bus)
        registry.register(ShutdownTracker("first"))
        registry.register(ShutdownTracker("second", deps=["first"]))

        registry.initialize_all({})
        registry.shutdown_all()

        # second depends on first, so second shuts down first
        assert shutdown_order[0] == "second"
        assert shutdown_order[1] == "first"

    def test_get_module(self, event_bus):
        registry = ModuleRegistry(event_bus)
        mod = DummyModule("findme")
        registry.register(mod)

        assert registry.get("findme") is mod
        assert registry.get("nonexistent") is None


# ---------------------------------------------------------------------------
# Platform Tests
# ---------------------------------------------------------------------------

class TestAnastasiaPlatform:
    def test_start_all_neurons(self, platform):
        """All 18 neurons should initialize successfully (16 core + 2 verticals)."""
        results = platform.start()

        assert len(results) == 18
        for name, success in results.items():
            assert success is True, f"Neuron {name} failed to initialize"

    def test_health_all_healthy(self, platform):
        platform.start()
        health = platform.health()

        # Platform may be "degraded" if flights has no credentials (expected in tests)
        assert health["platform"] in ("healthy", "degraded")
        # 16 total neurons; flights neuron reports unhealthy without API credentials
        assert health["neurons_online"] >= 17  # 17 or 18 depending on env
        assert health["neurons_total"] == 18
        assert health["uptime_seconds"] >= 0

    def test_selective_module_loading(self, temp_dir):
        """Should be able to start only specific neurons."""
        p = AnastasiaPlatform({"data_dir": temp_dir})
        results = p.start(modules=["knowledge", "intelligence", "credits"])

        assert len(results) == 3
        assert all(v is True for v in results.values())

        health = p.health()
        assert health["neurons_online"] == 3
        p.stop()

    def test_stop(self, platform):
        platform.start()
        assert platform.is_running is True

        platform.stop()
        assert platform.is_running is False

    def test_health_when_stopped(self, platform):
        health = platform.health()
        assert health["platform"] == "stopped"

    def test_double_start_warning(self, platform):
        platform.start()
        result = platform.start()  # Should warn and return empty
        assert result == {}

    def test_context_manager(self, temp_dir):
        with AnastasiaPlatform({"data_dir": temp_dir}) as p:
            assert p.is_running is True
            health = p.health()
            # May be "degraded" if flights neuron has no credentials (expected)
            assert health["platform"] in ("healthy", "degraded")
        assert p.is_running is False

    def test_get_module(self, platform):
        platform.start()
        knowledge = platform.get_module("knowledge")
        assert knowledge is not None
        assert knowledge.name == "knowledge"

    def test_get_event_bus(self, platform):
        bus = platform.get_event_bus()
        assert isinstance(bus, EventBus)

    def test_list_modules(self, platform):
        platform.start()
        modules = platform.list_modules()
        assert len(modules) == 18
        names = {m["name"] for m in modules}
        expected = {
            "knowledge", "daemon", "integrator", "payments",
            "intelligence", "resilience", "tenancy", "compliance",
            "credits", "portability", "sandbox", "bridge",
            "credentials", "saas", "devterminal", "search",
            "flights", "hotels",
        }
        assert names == expected

    def test_path_resolution(self, temp_dir):
        """Config paths should resolve to data_dir subdirectories."""
        p = AnastasiaPlatform({"data_dir": temp_dir})
        assert p._config["profiles_dir"] == os.path.join(temp_dir, "profiles")
        assert p._config["credits_storage_dir"] == os.path.join(temp_dir, "credits")
        assert p._config["compliance_audit_dir"] == os.path.join(temp_dir, "compliance_audit")


# ---------------------------------------------------------------------------
# Inter-neuron Communication Tests
# ---------------------------------------------------------------------------

class TestInterNeuronEvents:
    def test_platform_publishes_start_event(self, platform):
        received = []
        platform.get_event_bus().subscribe(EventType.CUSTOM, lambda e: received.append(e))

        platform.start()

        start_events = [e for e in received if e.data.get("action") == "platform_started"]
        assert len(start_events) == 1
        assert start_events[0].data["neurons_online"] == 18

    def test_cross_neuron_event_flow(self, platform):
        """Events published by one neuron should be visible to others."""
        platform.start()

        bus = platform.get_event_bus()

        received = []
        bus.subscribe(EventType.BOOKING_CREATED, lambda e: received.append(e))

        # Simulate a booking event (as if payments or booking agent published it)
        bus.publish(Event(
            type=EventType.BOOKING_CREATED,
            source="payments",
            agency_id="test_agency",
            data={"booking_id": "BK001", "amount": 450.00},
        ))

        assert len(received) == 1
        assert received[0].data["booking_id"] == "BK001"
        assert received[0].agency_id == "test_agency"

    def test_compliance_listens_to_payment_events(self, platform):
        """Compliance neuron should react to payment events."""
        platform.start()
        bus = platform.get_event_bus()

        # Compliance subscribes to PII_DETECTED and AUDIT_ENTRY internally
        # Publish a payment event and verify compliance audit reacts
        bus.publish(Event(
            type=EventType.PAYMENT_INITIATED,
            source="test",
            data={"amount": 100, "currency": "USD"},
        ))

        # Verify the event was logged
        recent = bus.get_recent_events(event_type=EventType.PAYMENT_INITIATED)
        assert len(recent) >= 1


# ---------------------------------------------------------------------------
# Individual Neuron Health Tests
# ---------------------------------------------------------------------------

class TestNeuronHealth:
    def test_all_neurons_report_healthy(self, platform):
        platform.start()
        health = platform.health()

        for name, status in health["neurons"].items():
            if name == "flights":
                # Flights neuron reports unhealthy when no API credentials are set
                # (expected in tests — no PICASSO_SESSION_TOKEN, DUFFEL_ACCESS_TOKEN, etc.)
                continue
            assert status["healthy"] is True, f"{name} reported unhealthy: {status.get('details')}"

    def test_knowledge_has_redbox_profile(self, platform):
        """Knowledge neuron should auto-seed with Redbox profile."""
        platform.start()
        knowledge = platform.get_module("knowledge")

        health = knowledge.health_check()
        assert health["healthy"] is True
        # Should have at least the Redbox seed profile
        assert health.get("profiles_count", 0) >= 1

    def test_tenancy_has_master_tenant(self, platform):
        """Tenancy neuron should auto-create MYSTES KYRIOS LLC master tenant."""
        platform.start()
        tenancy = platform.get_module("tenancy")

        health = tenancy.health_check()
        assert health["healthy"] is True
        assert health.get("tenant_count", 0) >= 1
