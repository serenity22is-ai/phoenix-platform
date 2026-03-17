"""
Tests for the ANASTASiA Bridge — Confidential Collaborative Development Protocol.

Covers:
- IP Firewall: content classification, blocking, redaction, audit trail
- Structural Knowledge Extractor: API patterns, schemas, auth flows
- Bridge Contracts: lifecycle (create, accept, pause, terminate)
- Bridge Registry: bridge CRUD, knowledge sync
- Bridge Orchestrator: opportunity analysis, proposal generation
- Bridge Protocol: end-to-end bridge lifecycle
- BridgeModule: neuron integration, platform startup
- Full end-to-end: create bridge → sync both sides → analyze → proposals

Run with: cd picasso-sdk && python3 -m pytest tests/test_bridge.py -v
"""

import os
import shutil
import tempfile

import pytest

from anastasia.core import EventBus, Event, EventType
from anastasia.core.types import (
    BridgeState,
    KnowledgeClassification,
    BridgeContract,
    StructuralKnowledge,
    BridgeProposal,
    FirewallAuditEntry,
)
from anastasia.bridge.extractor import StructuralKnowledgeExtractor
from anastasia.bridge.firewall import IPFirewall
from anastasia.bridge.contracts import ContractManager
from anastasia.bridge.registry import BridgeRegistry
from anastasia.bridge.orchestrator import BridgeOrchestrator
from anastasia.bridge.protocol import BridgeProtocol
from anastasia.bridge import BridgeModule
from anastasia.platform import AnastasiaPlatform


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def event_bus():
    return EventBus()


@pytest.fixture
def extractor():
    return StructuralKnowledgeExtractor()


@pytest.fixture
def firewall(event_bus):
    return IPFirewall(
        entity_id="entity_a",
        bridge_id="bridge_001",
        event_bus=event_bus,
    )


@pytest.fixture
def contract_manager(event_bus):
    return ContractManager(event_bus)


@pytest.fixture
def bridge_registry(event_bus):
    return BridgeRegistry(event_bus)


@pytest.fixture
def orchestrator(event_bus):
    return BridgeOrchestrator(event_bus)


@pytest.fixture
def protocol(event_bus):
    return BridgeProtocol(event_bus)


@pytest.fixture
def temp_dir():
    d = tempfile.mkdtemp(prefix="anastasia_bridge_test_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


# Sample data for tests
SAMPLE_ROUTES = [
    {
        "path": "/api/bookings",
        "method": "POST",
        "purpose": "Create a booking",
        "auth_required": True,
        "parameters": [
            {"name": "flight_id", "type": "string", "in": "body", "required": True},
        ],
        "request_schema": {"flight_id": {"type": "string"}, "passengers": {"type": "array"}},
        "response_schema": {"booking_id": {"type": "string"}, "status": {"type": "string"}},
    },
    {
        "path": "/api/search",
        "method": "GET",
        "purpose": "Search flights",
        "auth_required": True,
        "parameters": [
            {"name": "origin", "type": "string", "in": "query", "required": True},
            {"name": "destination", "type": "string", "in": "query", "required": True},
        ],
    },
]

SAMPLE_MODELS = [
    {
        "name": "Booking",
        "columns": [
            {"name": "id", "type": "integer", "primary_key": True},
            {"name": "flight_id", "type": "string"},
            {"name": "status", "type": "string"},
            {"name": "created_at", "type": "datetime"},
        ],
        "relationships": [
            {"target": "Flight", "type": "many_to_one"},
        ],
    },
    {
        "name": "Flight",
        "columns": [
            {"name": "id", "type": "integer", "primary_key": True},
            {"name": "origin", "type": "string"},
            {"name": "destination", "type": "string"},
            {"name": "price", "type": "float"},
        ],
    },
]

SAMPLE_AUTH = {
    "type": "oauth2",
    "flow": "authorization_code",
    "token_endpoint": "/oauth/token",
    "refresh_supported": True,
    "scopes": ["bookings:read", "bookings:write"],
    "header_format": "Bearer {token}",
    "expiry_seconds": 3600,
}


# ---------------------------------------------------------------------------
# Extractor Tests
# ---------------------------------------------------------------------------

class TestStructuralKnowledgeExtractor:
    def test_extract_api_patterns(self, extractor):
        patterns = extractor.extract_api_patterns(SAMPLE_ROUTES, "entity_a")
        assert len(patterns) == 2
        assert patterns[0]["endpoint"] == "/api/bookings"
        assert patterns[0]["method"] == "POST"
        assert patterns[1]["endpoint"] == "/api/search"

    def test_extract_data_schemas(self, extractor):
        schemas = extractor.extract_data_schemas(SAMPLE_MODELS, "entity_a")
        assert "Booking" in schemas
        assert "Flight" in schemas
        assert len(schemas["Booking"]["columns"]) == 4
        assert schemas["Booking"]["relationships"][0]["target"] == "Flight"

    def test_extract_auth_flows(self, extractor):
        flows = extractor.extract_auth_flows(SAMPLE_AUTH, "entity_a")
        assert len(flows) == 1
        assert flows[0]["type"] == "oauth2"
        assert flows[0]["refresh_supported"] is True

    def test_build_structural_knowledge(self, extractor):
        sk = extractor.build_structural_knowledge(
            entity_id="entity_a",
            bridge_id="bridge_001",
            routes=SAMPLE_ROUTES,
            models=SAMPLE_MODELS,
            auth_config=SAMPLE_AUTH,
        )
        assert isinstance(sk, StructuralKnowledge)
        assert sk.entity_id == "entity_a"
        assert len(sk.api_patterns) == 2
        assert len(sk.data_schemas) == 2
        assert len(sk.auth_flows) == 1

    def test_classify_structural_content(self, extractor):
        result = extractor.classify_content(
            "endpoint: /api/bookings, method: POST, schema: {id: string}"
        )
        assert result == KnowledgeClassification.STRUCTURAL

    def test_classify_credential_content(self, extractor):
        result = extractor.classify_content(
            'api_key = "sk_live_abc123def456"'
        )
        assert result == KnowledgeClassification.CREDENTIAL

    def test_classify_pii_content(self, extractor):
        result = extractor.classify_content(
            "user email: john@example.com, phone: 555-123-4567"
        )
        assert result == KnowledgeClassification.PII

    def test_content_hash(self, extractor):
        h1 = extractor.content_hash({"a": 1, "b": 2})
        h2 = extractor.content_hash({"a": 1, "b": 2})
        h3 = extractor.content_hash({"a": 1, "b": 3})
        assert h1 == h2
        assert h1 != h3


# ---------------------------------------------------------------------------
# Firewall Tests
# ---------------------------------------------------------------------------

class TestIPFirewall:
    def test_allow_structural_content(self, firewall):
        ok, clean, reason = firewall.inspect(
            {"endpoint": "/api/search", "method": "GET"},
            "api_patterns",
            "outbound",
        )
        assert ok is True
        assert clean is not None
        assert reason == ""

    def test_block_unlisted_content_type(self, firewall):
        ok, clean, reason = firewall.inspect(
            {"source_code": "def secret_algo(): ..."},
            "raw_source_code",
            "outbound",
        )
        assert ok is False
        assert clean is None
        assert "not allowed" in reason

    def test_redact_credentials(self, firewall):
        ok, clean, reason = firewall.inspect(
            {"config": 'api_key = "sk_live_secret123"'},
            "api_patterns",
            "outbound",
        )
        assert ok is True
        assert "[REDACTED]" in str(clean)

    def test_audit_trail(self, firewall):
        firewall.inspect({"test": True}, "api_patterns", "outbound")
        firewall.inspect({"bad": True}, "raw_code", "outbound")

        audit = firewall.get_audit_log()
        assert len(audit) >= 2

        stats = firewall.get_stats()
        assert stats["allowed"] >= 1
        assert stats["blocked"] >= 1

    def test_inspect_structural_knowledge(self, firewall, extractor):
        sk = extractor.build_structural_knowledge(
            entity_id="entity_a",
            bridge_id="bridge_001",
            routes=SAMPLE_ROUTES,
            models=SAMPLE_MODELS,
        )
        passed, sanitized, blocked = firewall.inspect_structural_knowledge(
            sk, "outbound", extractor
        )
        assert passed is True
        assert sanitized is not None
        assert len(sanitized.api_patterns) == 2
        assert len(blocked) == 0

    def test_firewall_publishes_block_event(self, firewall, event_bus):
        """Blocked content types should still fire a block event."""
        received = []
        event_bus.subscribe(
            EventType.BRIDGE_FIREWALL_BLOCKED,
            lambda e: received.append(e),
        )

        # Use an allowlisted content type with credential content
        # The classifier will detect the credential and block it
        from anastasia.bridge.extractor import StructuralKnowledgeExtractor
        classifier = StructuralKnowledgeExtractor()

        firewall.inspect(
            'password = "super_secret_123" api_key = "sk_live_abc"',
            "api_patterns",
            "outbound",
            classifier=classifier,
        )

        assert len(received) == 1
        assert received[0].data["classification"] == "credential"


# ---------------------------------------------------------------------------
# Contract Tests
# ---------------------------------------------------------------------------

class TestContractManager:
    def test_create_contract(self, contract_manager):
        contract = contract_manager.create_contract(
            entity_a_id="mystes",
            entity_b_id="aerticket",
            entity_a_name="MYSTES KYRIOS",
            entity_b_name="AERTiCKET",
        )
        assert isinstance(contract, BridgeContract)
        assert contract.entity_a_id == "mystes"
        assert contract.entity_b_id == "aerticket"
        assert contract.state == BridgeState.PENDING.value

    def test_accept_both_sides_activates(self, contract_manager):
        contract = contract_manager.create_contract(
            entity_a_id="mystes",
            entity_b_id="aerticket",
        )

        # Side A accepts
        contract = contract_manager.accept_contract(contract.id, "mystes")
        assert contract.state == BridgeState.NEGOTIATING.value

        # Side B accepts → ACTIVE
        contract = contract_manager.accept_contract(contract.id, "aerticket")
        assert contract.state == BridgeState.ACTIVE.value
        assert contract.activated_at is not None

    def test_pause_and_resume(self, contract_manager):
        contract = contract_manager.create_contract("a", "b")
        contract_manager.accept_contract(contract.id, "a")
        contract_manager.accept_contract(contract.id, "b")

        contract = contract_manager.pause_contract(contract.id, "maintenance")
        assert contract.state == BridgeState.PAUSED.value

        contract = contract_manager.resume_contract(contract.id)
        assert contract.state == BridgeState.ACTIVE.value

    def test_terminate(self, contract_manager):
        contract = contract_manager.create_contract("a", "b")
        contract = contract_manager.terminate_contract(contract.id, "expired")
        assert contract.state == BridgeState.TERMINATED.value
        assert contract.termination_reason == "expired"

    def test_list_contracts_by_entity(self, contract_manager):
        contract_manager.create_contract("a", "b")
        contract_manager.create_contract("a", "c")
        contract_manager.create_contract("b", "c")

        a_contracts = contract_manager.list_contracts(entity_id="a")
        assert len(a_contracts) == 2

    def test_get_partners(self, contract_manager):
        c1 = contract_manager.create_contract("a", "b")
        contract_manager.accept_contract(c1.id, "a")
        contract_manager.accept_contract(c1.id, "b")

        partners = contract_manager.get_partners("a")
        assert "b" in partners

    def test_is_action_allowed(self, contract_manager):
        contract = contract_manager.create_contract("a", "b")
        contract_manager.accept_contract(contract.id, "a")
        contract_manager.accept_contract(contract.id, "b")

        assert contract_manager.is_action_allowed(
            contract.id, "a", "propose_file_create"
        ) is True
        assert contract_manager.is_action_allowed(
            contract.id, "a", "delete_database"
        ) is False

    def test_wrong_entity_raises(self, contract_manager):
        contract = contract_manager.create_contract("a", "b")
        with pytest.raises(ValueError, match="not part of contract"):
            contract_manager.accept_contract(contract.id, "c")


# ---------------------------------------------------------------------------
# Registry Tests
# ---------------------------------------------------------------------------

class TestBridgeRegistry:
    def test_create_bridge(self, bridge_registry):
        bridge = bridge_registry.create_bridge(
            entity_a_id="mystes",
            entity_b_id="aerticket",
            entity_a_name="MYSTES KYRIOS",
            entity_b_name="AERTiCKET",
        )
        assert bridge.bridge_id is not None
        assert bridge.is_active is False

    def test_activate_and_sync(self, bridge_registry):
        bridge = bridge_registry.create_bridge("a", "b")
        bridge_registry.accept_bridge(bridge.bridge_id, "a")
        bridge_registry.accept_bridge(bridge.bridge_id, "b")

        assert bridge.is_active is True

        # Sync knowledge from entity A
        result = bridge_registry.sync_knowledge(
            bridge_id=bridge.bridge_id,
            entity_id="a",
            routes=SAMPLE_ROUTES,
            models=SAMPLE_MODELS,
        )
        assert result["synced"] is True
        assert result["patterns_synced"] == 2
        assert result["schemas_synced"] == 2

    def test_list_and_health(self, bridge_registry):
        bridge_registry.create_bridge("a", "b")
        bridge_registry.create_bridge("a", "c")

        bridges = bridge_registry.list_bridges()
        assert len(bridges) == 2

        health = bridge_registry.health()
        assert health["total_bridges"] == 2
        assert health["active_bridges"] == 0

    def test_pause_resume_terminate(self, bridge_registry):
        bridge = bridge_registry.create_bridge("a", "b")
        bridge_registry.accept_bridge(bridge.bridge_id, "a")
        bridge_registry.accept_bridge(bridge.bridge_id, "b")

        bridge_registry.pause_bridge(bridge.bridge_id, "test pause")
        assert bridge.contract.state == BridgeState.PAUSED.value

        bridge_registry.resume_bridge(bridge.bridge_id)
        assert bridge.contract.state == BridgeState.ACTIVE.value

        bridge_registry.terminate_bridge(bridge.bridge_id, "done")
        assert bridge.contract.state == BridgeState.TERMINATED.value


# ---------------------------------------------------------------------------
# Orchestrator Tests
# ---------------------------------------------------------------------------

class TestBridgeOrchestrator:
    def test_analyze_finds_opportunities(self, orchestrator, extractor):
        ka = extractor.build_structural_knowledge(
            "a", "bridge1",
            routes=SAMPLE_ROUTES,
            models=SAMPLE_MODELS,
            auth_config=SAMPLE_AUTH,
        )
        kb = extractor.build_structural_knowledge(
            "b", "bridge1",
            routes=[
                {"path": "/api/payments", "method": "POST", "purpose": "Process payment"},
            ],
            models=[
                {"name": "Payment", "columns": [
                    {"name": "id", "type": "integer", "primary_key": True},
                    {"name": "amount", "type": "float"},
                ]},
            ],
            auth_config={"type": "api_key"},
        )

        opportunities = orchestrator.analyze_integration_opportunities("bridge1", ka, kb)
        assert len(opportunities) >= 1

    def test_generate_proposals(self, orchestrator, extractor):
        ka = extractor.build_structural_knowledge(
            "a", "bridge1",
            routes=SAMPLE_ROUTES,
            auth_config=SAMPLE_AUTH,
        )
        kb = extractor.build_structural_knowledge(
            "b", "bridge1",
            routes=[
                {"path": "/api/payments", "method": "POST", "purpose": "Process payment"},
            ],
            auth_config={"type": "api_key"},
        )

        proposals = orchestrator.generate_proposals(
            "bridge1", "a", ka, kb,
        )
        assert len(proposals) >= 1
        for p in proposals:
            assert isinstance(p, BridgeProposal)
            assert p.target_entity_id == "a"
            assert p.bridge_id == "bridge1"

    def test_approve_reject_proposals(self, orchestrator, extractor):
        ka = extractor.build_structural_knowledge("a", "b1", routes=SAMPLE_ROUTES)
        kb = extractor.build_structural_knowledge("b", "b1", routes=[
            {"path": "/api/pay", "method": "POST", "purpose": "Pay"},
        ])

        proposals = orchestrator.generate_proposals("b1", "a", ka, kb)
        if proposals:
            p = proposals[0]
            approved = orchestrator.approve_proposal(p.id, "admin_a")
            assert approved.status == "approved"


# ---------------------------------------------------------------------------
# Protocol Tests (end-to-end)
# ---------------------------------------------------------------------------

class TestBridgeProtocol:
    def test_full_lifecycle(self, protocol):
        """End-to-end: create → accept → sync → analyze → proposals."""
        # 1. Create bridge
        result = protocol.create_bridge(
            entity_a_id="mystes",
            entity_b_id="aerticket",
            entity_a_name="MYSTES KYRIOS",
            entity_b_name="AERTiCKET",
        )
        bridge_id = result["bridge_id"]
        assert result["state"] == BridgeState.PENDING.value

        # 2. Both sides accept
        protocol.accept_bridge(bridge_id, "mystes")
        result = protocol.accept_bridge(bridge_id, "aerticket")
        assert result["active"] is True

        # 3. Entity A syncs knowledge
        sync_a = protocol.sync_knowledge(
            bridge_id=bridge_id,
            entity_id="mystes",
            routes=SAMPLE_ROUTES,
            models=SAMPLE_MODELS,
            auth_config=SAMPLE_AUTH,
        )
        assert sync_a["synced"] is True

        # 4. Entity B syncs knowledge
        sync_b = protocol.sync_knowledge(
            bridge_id=bridge_id,
            entity_id="aerticket",
            routes=[
                {"path": "/redbox/search", "method": "POST", "purpose": "Search flights"},
                {"path": "/redbox/book", "method": "POST", "purpose": "Book flight"},
                {"path": "/redbox/rules", "method": "GET", "purpose": "Fare rules"},
            ],
            models=[
                {"name": "Booking", "columns": [
                    {"name": "id", "type": "integer", "primary_key": True},
                    {"name": "pnr", "type": "string"},
                ]},
            ],
            auth_config={"type": "session_cookie", "flow": "keycloak_sso"},
        )
        assert sync_b["synced"] is True

        # 5. Analyze and generate proposals
        analysis = protocol.analyze_and_propose(bridge_id)
        assert analysis["opportunities_found"] >= 1

        # 6. Get proposals per entity (entity-scoped)
        mystes_proposals = protocol.get_proposals_for_entity(bridge_id, "mystes")
        aerticket_proposals = protocol.get_proposals_for_entity(bridge_id, "aerticket")

        # Each side gets their own proposals
        for p in mystes_proposals:
            assert p["target_entity_id"] == "mystes"
        for p in aerticket_proposals:
            assert p["target_entity_id"] == "aerticket"

    def test_bridge_status(self, protocol):
        result = protocol.create_bridge("a", "b")
        status = protocol.get_bridge_status(result["bridge_id"])
        assert status["bridge_id"] == result["bridge_id"]
        assert status["is_active"] is False

    def test_list_bridges(self, protocol):
        protocol.create_bridge("a", "b")
        protocol.create_bridge("a", "c")

        all_bridges = protocol.list_bridges()
        assert len(all_bridges) == 2

        a_bridges = protocol.list_bridges(entity_id="a")
        assert len(a_bridges) == 2

    def test_pause_resume_terminate(self, protocol):
        result = protocol.create_bridge("a", "b")
        bid = result["bridge_id"]
        protocol.accept_bridge(bid, "a")
        protocol.accept_bridge(bid, "b")

        protocol.pause_bridge(bid, "testing")
        status = protocol.get_bridge_status(bid)
        assert status["contract"]["state"] == BridgeState.PAUSED.value

        protocol.resume_bridge(bid)
        status = protocol.get_bridge_status(bid)
        assert status["contract"]["state"] == BridgeState.ACTIVE.value

        protocol.terminate_bridge(bid, "done")
        status = protocol.get_bridge_status(bid)
        assert status["contract"]["state"] == BridgeState.TERMINATED.value

    def test_daemon_registration(self, protocol):
        protocol.register_daemon("daemon_001", "entity_a")
        assert protocol.daemon_heartbeat("daemon_001") is True
        assert protocol.daemon_heartbeat("nonexistent") is False

        protocol.unregister_daemon("daemon_001")
        assert protocol.daemon_heartbeat("daemon_001") is False


# ---------------------------------------------------------------------------
# BridgeModule Tests (neuron integration)
# ---------------------------------------------------------------------------

class TestBridgeModule:
    def test_module_properties(self):
        mod = BridgeModule()
        assert mod.name == "bridge"
        assert mod.version == "1.0.0"
        assert "knowledge" in mod.dependencies
        assert "daemon" in mod.dependencies

    def test_initialize_and_health(self, event_bus):
        mod = BridgeModule()
        mod.initialize(event_bus, {})

        health = mod.health_check()
        assert health["healthy"] is True
        assert health["active_bridges"] == 0

    def test_shutdown(self, event_bus):
        mod = BridgeModule()
        mod.initialize(event_bus, {})
        mod.shutdown()

        health = mod.health_check()
        assert health["healthy"] is False


# ---------------------------------------------------------------------------
# Platform Integration Tests
# ---------------------------------------------------------------------------

class TestBridgePlatformIntegration:
    def test_platform_starts_with_bridge(self, temp_dir):
        """Platform should start all 14 neurons including bridge + verticals."""
        platform = AnastasiaPlatform({"data_dir": temp_dir})
        results = platform.start()

        assert "bridge" in results
        assert results["bridge"] is True

        health = platform.health()
        # 14 total neurons; flights neuron may report unhealthy without API credentials
        assert health["neurons_online"] >= 13
        # May be "degraded" if flights neuron has no credentials (expected in tests)
        assert health["platform"] in ("healthy", "degraded")

        # Verify bridge module is accessible
        bridge_mod = platform.get_module("bridge")
        assert bridge_mod is not None
        assert bridge_mod.name == "bridge"

        bridge_health = bridge_mod.health_check()
        assert bridge_health["healthy"] is True
        assert bridge_health["protocol_version"] == "1.0.0"

        platform.stop()

    def test_selective_loading_with_bridge(self, temp_dir):
        """Can selectively load just the bridge and its deps."""
        platform = AnastasiaPlatform({"data_dir": temp_dir})
        results = platform.start(modules=["knowledge", "daemon", "bridge"])

        assert len(results) == 3
        assert all(v is True for v in results.values())

        platform.stop()

    def test_bridge_in_module_list(self, temp_dir):
        """Bridge should appear in the module list."""
        platform = AnastasiaPlatform({"data_dir": temp_dir})
        platform.start()

        modules = platform.list_modules()
        names = {m["name"] for m in modules}
        assert "bridge" in names

        platform.stop()
