"""
Tests for CredentialNetwork and CredentialModule (credentials neuron).

Covers:
- Network membership (join, leave, rejoin, list, get)
- Network discovery (query routes, coverage map)
- Booking routing (route, confirm, fail, history)
- Revenue calculations and summaries
- Data model serialization (to_dict / from_dict roundtrips)
- Member persistence across recreations
- CredentialModule lifecycle (name, version, initialize, health_check)

Run with: cd picasso-sdk && python3 -m pytest tests/test_credential_network.py -v
"""

import time
from unittest.mock import MagicMock, patch

import pytest

from anastasia.core.events import EventBus, Event, EventType
from anastasia.credentials.vault import CredentialVault
from anastasia.credentials.network import (
    CredentialNetwork,
    NetworkMember,
    RoutingRequest,
    RoutingResult,
    DEFAULT_REVENUE_SPLIT,
)
from anastasia.credentials import CredentialModule


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def bus():
    return EventBus()


@pytest.fixture
def vault(bus, tmp_path):
    return CredentialVault(event_bus=bus, storage_dir=str(tmp_path / "vault"))


@pytest.fixture
def network(bus, vault, tmp_path):
    return CredentialNetwork(
        event_bus=bus, vault=vault, storage_dir=str(tmp_path / "network")
    )


def _add_vault_list_method(vault, entries):
    """
    Attach a ``list`` method to the vault that returns dicts matching
    what ``_update_coverage_from_vault`` expects.

    The real vault exposes ``list_credentials`` which returns CredentialEntry
    objects, but the network calls ``vault.list(tenant_id=...)``. In tests
    we patch the vault with a simple callable that returns the desired
    credential metadata dicts.
    """
    def _list(tenant_id=None):
        if tenant_id is None:
            return entries
        return [e for e in entries if e.get("owner_tenant_id") == tenant_id]

    vault.list = _list


# ---------------------------------------------------------------------------
# CredentialNetwork — Membership
# ---------------------------------------------------------------------------

class TestNetworkMembership:

    def test_join_network(self, network):
        member = network.join_network("t1", "Agency Alpha")
        assert isinstance(member, NetworkMember)
        assert member.tenant_id == "t1"
        assert member.tenant_name == "Agency Alpha"
        assert member.status == "active"

    def test_join_network_publishes_event(self, bus, network):
        received = []
        bus.subscribe(EventType.CUSTOM, lambda e: received.append(e))

        network.join_network("t1", "Agency Alpha")

        join_events = [
            e for e in received
            if e.data.get("action") == "network.member_joined"
        ]
        assert len(join_events) == 1
        assert join_events[0].data["tenant_id"] == "t1"
        assert join_events[0].data["tenant_name"] == "Agency Alpha"

    def test_leave_network(self, network):
        network.join_network("t1", "Agency Alpha")
        result = network.leave_network("t1")
        assert result is True

        member = network.get_member("t1")
        assert member.status == "left"
        assert member.coverage == {}

    def test_leave_network_unknown_tenant(self, network):
        result = network.leave_network("nonexistent")
        assert result is False

    def test_get_member(self, network):
        network.join_network("t1", "Agency Alpha")
        member = network.get_member("t1")
        assert member is not None
        assert member.tenant_id == "t1"

    def test_get_member_not_found(self, network):
        assert network.get_member("nonexistent") is None

    def test_list_members_active_only(self, network):
        network.join_network("t1", "Alpha")
        network.join_network("t2", "Beta")
        network.leave_network("t2")

        active = network.list_members(status="active")
        assert len(active) == 1
        assert active[0].tenant_id == "t1"

    def test_list_members_all(self, network):
        network.join_network("t1", "Alpha")
        network.join_network("t2", "Beta")
        network.leave_network("t2")

        all_members = network.list_members(status="all")
        assert len(all_members) == 2

    def test_rejoin_network(self, network):
        network.join_network("t1", "Alpha")
        network.leave_network("t1")

        member = network.get_member("t1")
        assert member.status == "left"

        reactivated = network.join_network("t1", "Alpha Reborn")
        assert reactivated.status == "active"
        assert reactivated.tenant_name == "Alpha Reborn"


# ---------------------------------------------------------------------------
# CredentialNetwork — Discovery
# ---------------------------------------------------------------------------

class TestNetworkDiscovery:

    def test_query_available_routes_empty(self, network):
        """No members means no routes."""
        routes = network.query_available_routes(provider_id="redbox")
        assert routes == []

    def test_query_available_routes_with_credentials(self, bus, vault, tmp_path):
        """Store a credential in the vault, patch vault.list, and query."""
        # Patch vault with a list method returning credential metadata
        _add_vault_list_method(vault, [
            {
                "owner_tenant_id": "t1",
                "provider_id": "redbox",
                "pos_markets": ["DK", "ES"],
                "vertical": "flights",
            },
        ])

        net = CredentialNetwork(
            event_bus=bus, vault=vault,
            storage_dir=str(tmp_path / "net_discovery"),
        )
        net.join_network("t1", "Nordic Agency")

        routes = net.query_available_routes(provider_id="redbox")
        assert len(routes) == 1
        assert routes[0]["owner_tenant_id"] == "t1"
        assert "DK" in routes[0]["pos_markets"]
        assert "ES" in routes[0]["pos_markets"]

    def test_query_available_routes_filters_by_pos(self, bus, vault, tmp_path):
        _add_vault_list_method(vault, [
            {
                "owner_tenant_id": "t1",
                "provider_id": "redbox",
                "pos_markets": ["DK", "ES", "FR"],
                "vertical": "flights",
            },
        ])

        net = CredentialNetwork(
            event_bus=bus, vault=vault,
            storage_dir=str(tmp_path / "net_pos_filter"),
        )
        net.join_network("t1", "Nordic Agency")

        routes = net.query_available_routes(
            provider_id="redbox", pos_market="DK"
        )
        assert len(routes) == 1
        assert routes[0]["pos_markets"] == ["DK"]

    def test_get_coverage_map(self, bus, vault, tmp_path):
        _add_vault_list_method(vault, [
            {
                "owner_tenant_id": "t1",
                "provider_id": "redbox",
                "pos_markets": ["DK"],
                "vertical": "flights",
            },
            {
                "owner_tenant_id": "t2",
                "provider_id": "redbox",
                "pos_markets": ["DK", "ES"],
                "vertical": "flights",
            },
        ])

        net = CredentialNetwork(
            event_bus=bus, vault=vault,
            storage_dir=str(tmp_path / "net_coverage"),
        )
        net.join_network("t1", "Agency A")
        net.join_network("t2", "Agency B")

        coverage = net.get_coverage_map()
        assert "redbox" in coverage
        assert "t1" in coverage["redbox"]["DK"]
        assert "t2" in coverage["redbox"]["DK"]
        assert "t2" in coverage["redbox"]["ES"]


# ---------------------------------------------------------------------------
# CredentialNetwork — Booking Routing
# ---------------------------------------------------------------------------

class TestBookingRouting:

    def _setup_routable_network(self, bus, vault, tmp_path, subdir="routing"):
        """Helper: create a network with one routable member."""
        _add_vault_list_method(vault, [
            {
                "owner_tenant_id": "host1",
                "provider_id": "redbox",
                "pos_markets": ["DK"],
                "vertical": "flights",
            },
        ])

        net = CredentialNetwork(
            event_bus=bus, vault=vault,
            storage_dir=str(tmp_path / subdir),
        )
        net.join_network("host1", "Nordic Host")
        net.join_network("requester1", "Requesting Agency")
        return net

    def test_route_booking_no_candidates(self, network):
        """No members with matching credentials returns None."""
        req = RoutingRequest(
            requester_tenant_id="t1",
            provider_id="redbox",
            pos_market="DK",
        )
        result = network.route_booking(req)
        assert result is None

    def test_route_booking_with_candidate(self, bus, vault, tmp_path):
        net = self._setup_routable_network(bus, vault, tmp_path)

        req = RoutingRequest(
            requester_tenant_id="requester1",
            provider_id="redbox",
            pos_market="DK",
        )
        result = net.route_booking(req)

        assert result is not None
        assert isinstance(result, RoutingResult)
        assert result.owner_tenant_id == "host1"
        assert result.provider_id == "redbox"
        assert result.pos_market == "DK"
        assert result.status == "pending"
        assert 0.0 <= result.confidence <= 1.0

    def test_route_booking_excludes_self(self, bus, vault, tmp_path):
        """A requester cannot route to their own credentials."""
        _add_vault_list_method(vault, [
            {
                "owner_tenant_id": "self_agency",
                "provider_id": "redbox",
                "pos_markets": ["DK"],
                "vertical": "flights",
            },
        ])
        net = CredentialNetwork(
            event_bus=bus, vault=vault,
            storage_dir=str(tmp_path / "route_self"),
        )
        net.join_network("self_agency", "Self Agency")

        req = RoutingRequest(
            requester_tenant_id="self_agency",
            provider_id="redbox",
            pos_market="DK",
        )
        result = net.route_booking(req)
        assert result is None

    def test_confirm_execution(self, bus, vault, tmp_path):
        net = self._setup_routable_network(bus, vault, tmp_path, "confirm")

        req = RoutingRequest(
            requester_tenant_id="requester1",
            provider_id="redbox",
            pos_market="DK",
        )
        result = net.route_booking(req)
        assert result is not None

        confirmed = net.confirm_execution(
            result.result_id,
            {"pnr": "ABC123", "transaction_amount_usd": 500.0},
        )
        assert confirmed is not None
        assert confirmed.status == "completed"
        assert confirmed.executed_at is not None
        assert confirmed.execution_result["pnr"] == "ABC123"

        # Owner stats should be updated
        owner = net.get_member("host1")
        assert owner.bookings_routed == 1
        assert owner.revenue_earned_usd > 0

    def test_confirm_execution_unknown_id(self, network):
        result = network.confirm_execution("nonexistent", {"pnr": "XYZ"})
        assert result is None

    def test_fail_execution(self, bus, vault, tmp_path):
        net = self._setup_routable_network(bus, vault, tmp_path, "fail")

        req = RoutingRequest(
            requester_tenant_id="requester1",
            provider_id="redbox",
            pos_market="DK",
        )
        result = net.route_booking(req)
        assert result is not None

        failed = net.fail_execution(result.result_id, "GDS timeout")
        assert failed is not None
        assert failed.status == "failed"
        assert failed.execution_result == {"error": "GDS timeout"}

    def test_fail_execution_unknown_id(self, network):
        result = network.fail_execution("nonexistent", "some reason")
        assert result is None

    def test_get_routing_history(self, bus, vault, tmp_path):
        net = self._setup_routable_network(bus, vault, tmp_path, "history")

        # Route two bookings
        for _ in range(2):
            req = RoutingRequest(
                requester_tenant_id="requester1",
                provider_id="redbox",
                pos_market="DK",
            )
            net.route_booking(req)

        history = net.get_routing_history()
        assert len(history) == 2
        # Most recent first
        assert history[0].request_id != history[1].request_id

    def test_get_routing_history_filtered_by_owner(self, bus, vault, tmp_path):
        net = self._setup_routable_network(bus, vault, tmp_path, "hist_owner")

        req = RoutingRequest(
            requester_tenant_id="requester1",
            provider_id="redbox",
            pos_market="DK",
        )
        net.route_booking(req)

        # host1 is the owner
        history = net.get_routing_history(tenant_id="host1")
        assert len(history) == 1
        assert history[0].owner_tenant_id == "host1"

        # Unknown tenant has no history
        history = net.get_routing_history(tenant_id="unknown")
        assert len(history) == 0


# ---------------------------------------------------------------------------
# CredentialNetwork — Revenue
# ---------------------------------------------------------------------------

class TestRevenue:

    def test_calculate_split(self, network):
        # Pyramid model (Build #156): Pro tier default split
        # platform=5%, router=66.5% (client provisionary), owner=28.5% (portal host)
        result = RoutingResult(
            revenue_split=dict(DEFAULT_REVENUE_SPLIT),
        )
        split = network.calculate_split(result, 1000.0)

        assert split["platform_amount"] == 50.0
        assert split["router_amount"] == 665.0
        assert split["owner_amount"] == 285.0
        assert split["transaction_amount"] == 1000.0

    def test_calculate_split_custom_ratios(self, network):
        result = RoutingResult(
            revenue_split={"owner": 0.70, "platform": 0.20, "router": 0.10},
        )
        split = network.calculate_split(result, 200.0)

        assert split["owner_amount"] == 140.0
        assert split["platform_amount"] == 40.0
        assert split["router_amount"] == 20.0

    def test_get_revenue_summary(self, bus, vault, tmp_path):
        _add_vault_list_method(vault, [
            {
                "owner_tenant_id": "host1",
                "provider_id": "redbox",
                "pos_markets": ["DK"],
                "vertical": "flights",
            },
        ])
        net = CredentialNetwork(
            event_bus=bus, vault=vault,
            storage_dir=str(tmp_path / "rev_summary"),
        )
        net.join_network("host1", "Host")
        net.join_network("req1", "Requester")

        # Route and confirm a booking
        req = RoutingRequest(
            requester_tenant_id="req1",
            provider_id="redbox",
            pos_market="DK",
        )
        result = net.route_booking(req)
        net.confirm_execution(
            result.result_id,
            {"transaction_amount_usd": 1000.0},
        )

        summary = net.get_revenue_summary("host1", period="all")
        assert summary["tenant_id"] == "host1"
        assert summary["bookings_in_period"] == 1
        assert summary["earned_usd"] > 0
        assert summary["lifetime_earned_usd"] > 0

    def test_get_revenue_summary_unknown_tenant(self, network):
        summary = network.get_revenue_summary("nonexistent")
        assert summary == {"error": "tenant_not_found"}


# ---------------------------------------------------------------------------
# CredentialNetwork — Stats & Persistence
# ---------------------------------------------------------------------------

class TestNetworkStats:

    def test_network_stats(self, bus, vault, tmp_path):
        _add_vault_list_method(vault, [
            {
                "owner_tenant_id": "t1",
                "provider_id": "redbox",
                "pos_markets": ["DK", "ES"],
                "vertical": "flights",
            },
        ])
        net = CredentialNetwork(
            event_bus=bus, vault=vault,
            storage_dir=str(tmp_path / "stats"),
        )
        net.join_network("t1", "Alpha")
        net.join_network("t2", "Beta")
        net.leave_network("t2")

        stats = net.get_network_stats()
        assert stats["total_members"] == 2
        assert stats["active_members"] == 1
        assert stats["unique_providers"] >= 1
        assert stats["unique_pos_markets"] >= 1

    def test_member_persistence(self, bus, vault, tmp_path):
        """Member data should survive a network recreation from the same dir."""
        storage = str(tmp_path / "persist")

        net1 = CredentialNetwork(
            event_bus=bus, vault=vault, storage_dir=storage
        )
        net1.join_network("t1", "Alpha")
        assert net1.member_count == 1

        # Recreate from the same storage directory
        net2 = CredentialNetwork(
            event_bus=bus, vault=vault, storage_dir=storage
        )
        assert net2.member_count == 1
        member = net2.get_member("t1")
        assert member is not None
        assert member.tenant_name == "Alpha"
        assert member.status == "active"

    def test_member_count_property(self, network):
        assert network.member_count == 0
        network.join_network("t1", "A")
        assert network.member_count == 1
        network.leave_network("t1")
        assert network.member_count == 0

    def test_active_routes_property(self, bus, vault, tmp_path):
        _add_vault_list_method(vault, [
            {
                "owner_tenant_id": "host1",
                "provider_id": "redbox",
                "pos_markets": ["DK"],
                "vertical": "flights",
            },
        ])
        net = CredentialNetwork(
            event_bus=bus, vault=vault,
            storage_dir=str(tmp_path / "active_routes"),
        )
        net.join_network("host1", "Host")
        net.join_network("req1", "Requester")

        assert net.active_routes == 0

        req = RoutingRequest(
            requester_tenant_id="req1",
            provider_id="redbox",
            pos_market="DK",
        )
        net.route_booking(req)
        assert net.active_routes == 1


# ---------------------------------------------------------------------------
# Data Model Serialization
# ---------------------------------------------------------------------------

class TestDataModels:

    def test_network_member_roundtrip(self):
        member = NetworkMember(
            tenant_id="t1",
            tenant_name="Test Agency",
            status="active",
            credentials_shared=3,
            bookings_routed=10,
            bookings_received=5,
            revenue_earned_usd=1200.50,
            revenue_paid_usd=150.00,
            coverage={"redbox": ["DK", "ES"]},
            capabilities=["flights", "hotels"],
        )
        d = member.to_dict()
        restored = NetworkMember.from_dict(d)

        assert restored.tenant_id == member.tenant_id
        assert restored.tenant_name == member.tenant_name
        assert restored.status == member.status
        assert restored.credentials_shared == member.credentials_shared
        assert restored.bookings_routed == member.bookings_routed
        assert restored.revenue_earned_usd == member.revenue_earned_usd
        assert restored.coverage == member.coverage
        assert restored.capabilities == member.capabilities

    def test_network_member_to_dict_keys(self):
        member = NetworkMember(tenant_id="t1", tenant_name="Test")
        d = member.to_dict()
        expected_keys = {
            "tenant_id", "tenant_name", "joined_at", "status",
            "credentials_shared", "bookings_routed", "bookings_received",
            "revenue_earned_usd", "revenue_paid_usd", "coverage",
            "capabilities",
        }
        assert set(d.keys()) == expected_keys

    def test_routing_request_roundtrip(self):
        req = RoutingRequest(
            requester_tenant_id="t1",
            provider_id="redbox",
            pos_market="DK",
            vertical="flights",
            search_params={"origin": "JFK", "destination": "CPH"},
            priority="price",
        )
        d = req.to_dict()
        restored = RoutingRequest.from_dict(d)

        assert restored.requester_tenant_id == req.requester_tenant_id
        assert restored.provider_id == req.provider_id
        assert restored.pos_market == req.pos_market
        assert restored.vertical == req.vertical
        assert restored.search_params == req.search_params
        assert restored.priority == req.priority

    def test_routing_result_roundtrip(self):
        result = RoutingResult(
            request_id="req-123",
            credential_id="host1:redbox",
            owner_tenant_id="host1",
            provider_id="redbox",
            pos_market="DK",
            estimated_price=450.0,
            confidence=0.87,
            status="completed",
            executed_at=time.time(),
            execution_result={"pnr": "ABC123"},
        )
        d = result.to_dict()
        restored = RoutingResult.from_dict(d)

        assert restored.request_id == result.request_id
        assert restored.credential_id == result.credential_id
        assert restored.owner_tenant_id == result.owner_tenant_id
        assert restored.confidence == result.confidence
        assert restored.status == result.status
        assert restored.execution_result == result.execution_result

    def test_routing_result_default_revenue_split(self):
        result = RoutingResult()
        assert result.revenue_split == DEFAULT_REVENUE_SPLIT

    def test_network_member_from_dict_ignores_unknown_keys(self):
        data = {
            "tenant_id": "t1",
            "tenant_name": "Test",
            "unknown_field": "should_be_ignored",
        }
        member = NetworkMember.from_dict(data)
        assert member.tenant_id == "t1"
        assert not hasattr(member, "unknown_field") or "unknown_field" not in member.__dict__


# ---------------------------------------------------------------------------
# CredentialModule (__init__.py NeuronModule)
# ---------------------------------------------------------------------------

class TestCredentialModule:

    def test_module_name(self):
        mod = CredentialModule()
        assert mod.name == "credentials"

    def test_module_version(self):
        mod = CredentialModule()
        assert mod.version == "1.0.0"

    def test_module_no_dependencies(self):
        mod = CredentialModule()
        assert mod.dependencies == []

    def test_initialize(self, bus, tmp_path):
        mod = CredentialModule()
        config = {
            "credentials_dir": str(tmp_path / "creds"),
            "network_dir": str(tmp_path / "network"),
            "revenue_dir": str(tmp_path / "revenue"),
        }
        mod.initialize(event_bus=bus, config=config)

        assert mod.vault is not None
        assert mod.network is not None
        assert mod.revenue is not None

    def test_health_check(self, bus, tmp_path):
        mod = CredentialModule()
        config = {
            "credentials_dir": str(tmp_path / "creds"),
            "network_dir": str(tmp_path / "network"),
            "revenue_dir": str(tmp_path / "revenue"),
        }
        mod.initialize(event_bus=bus, config=config)

        health = mod.health_check()
        assert health["healthy"] is True
        assert "vault" in health
        assert "network" in health
        assert "revenue" in health
        assert health["vault"]["credentials_count"] == 0
        assert health["network"]["member_count"] == 0

    def test_health_check_before_init(self):
        mod = CredentialModule()
        health = mod.health_check()
        assert health["healthy"] is False

    def test_shutdown(self, bus, tmp_path):
        mod = CredentialModule()
        config = {
            "credentials_dir": str(tmp_path / "creds"),
            "network_dir": str(tmp_path / "network"),
            "revenue_dir": str(tmp_path / "revenue"),
        }
        mod.initialize(event_bus=bus, config=config)
        mod.shutdown()

        # After shutdown, health_check should report unhealthy
        health = mod.health_check()
        assert health["healthy"] is False

    def test_vault_accessor_before_init(self):
        mod = CredentialModule()
        with pytest.raises(RuntimeError, match="not initialized"):
            _ = mod.vault

    def test_network_accessor_before_init(self):
        mod = CredentialModule()
        with pytest.raises(RuntimeError, match="not initialized"):
            _ = mod.network

    def test_revenue_accessor_before_init(self):
        mod = CredentialModule()
        with pytest.raises(RuntimeError, match="not initialized"):
            _ = mod.revenue
