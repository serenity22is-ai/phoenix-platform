"""
Tests for CredentialVault and RevenueCalculator.

Tests cover:
- CredentialVault: store, retrieve, access control, sharing, revocation,
  rotation, daemon binding, persistence, usage tracking, stats, events.
- RevenueCalculator: split calculation (default/custom), platform fee
  floor/cap, record creation, settlement, tenant summary, network revenue,
  filtered queries, persistence.

MYSTES KYRIOS LLC — Confidential.
"""

import time

import pytest

from anastasia.core.events import EventBus, Event, EventType
from anastasia.credentials.vault import CredentialVault, CredentialEntry
from anastasia.credentials.revenue import (
    RevenueCalculator,
    RevenueRecord,
    DEFAULT_SPLIT,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def event_bus():
    return EventBus()


@pytest.fixture
def vault_dir(tmp_path):
    d = tmp_path / "vault_storage"
    d.mkdir()
    return d


@pytest.fixture
def vault(event_bus, vault_dir):
    return CredentialVault(
        event_bus=event_bus,
        storage_dir=str(vault_dir),
    )


@pytest.fixture
def revenue_dir(tmp_path):
    d = tmp_path / "revenue_storage"
    d.mkdir()
    return d


@pytest.fixture
def calculator(revenue_dir):
    return RevenueCalculator(storage_dir=str(revenue_dir))


def _store_sample(vault, owner="tenant-a", provider="sabre", cred_type="api_key"):
    """Helper to store a credential and return the entry."""
    return vault.store(
        owner_tenant_id=owner,
        provider_id=provider,
        credential_type=cred_type,
        raw_data={"api_key": "secret-123", "endpoint": "https://api.sabre.com"},
    )


# ===========================================================================
# CredentialVault Tests
# ===========================================================================


class TestCredentialVaultStore:
    """Tests for storing credentials."""

    def test_store_credential(self, vault):
        """Storing a credential adds it to the vault."""
        entry = _store_sample(vault)
        assert entry.credential_id, "credential_id should be set"
        assert entry.provider_id == "sabre", "provider_id should match"
        assert entry.owner_tenant_id == "tenant-a", "owner_tenant_id should match"
        assert entry.credential_type == "api_key", "credential_type should match"
        assert entry.status == "active", "status should default to active"
        assert vault.count == 1, "vault should contain one credential"

    def test_store_publishes_event(self, vault, event_bus):
        """Storing a credential publishes a credential.stored event."""
        received = []
        event_bus.subscribe(EventType.CUSTOM, lambda e: received.append(e))

        _store_sample(vault)

        assert len(received) == 1, "should publish exactly one event"
        assert received[0].data["event"] == "credential.stored", (
            "event name should be credential.stored"
        )
        assert received[0].data["provider_id"] == "sabre", (
            "event should include provider_id"
        )

    def test_multiple_credentials(self, vault):
        """Storing multiple credentials tracks all of them."""
        _store_sample(vault, owner="tenant-a", provider="sabre")
        _store_sample(vault, owner="tenant-b", provider="amadeus")
        _store_sample(vault, owner="tenant-a", provider="travelport")

        assert vault.count == 3, "vault should contain three credentials"
        all_creds = vault.list_credentials()
        assert len(all_creds) == 3, "list_credentials should return all three"


class TestCredentialVaultRetrieve:
    """Tests for retrieving (decrypting) credentials."""

    def test_retrieve_by_owner(self, vault):
        """Owner can retrieve and decrypt their own credential."""
        entry = _store_sample(vault, owner="tenant-a")
        raw = vault.retrieve(entry.credential_id, "tenant-a")

        assert raw is not None, "owner should be able to retrieve their credential"
        assert raw["api_key"] == "secret-123", "decrypted data should match original"
        assert raw["endpoint"] == "https://api.sabre.com", (
            "decrypted data should include all fields"
        )

    def test_retrieve_access_denied(self, vault):
        """Non-owner, non-shared tenant cannot retrieve."""
        entry = _store_sample(vault, owner="tenant-a")
        raw = vault.retrieve(entry.credential_id, "tenant-intruder")

        assert raw is None, "non-owner should be denied access"

    def test_retrieve_shared(self, vault):
        """Shared tenant can retrieve the credential."""
        entry = _store_sample(vault, owner="tenant-a")
        vault.share(entry.credential_id, "tenant-b")

        raw = vault.retrieve(entry.credential_id, "tenant-b")
        assert raw is not None, "shared tenant should be able to retrieve"
        assert raw["api_key"] == "secret-123", "shared tenant gets correct data"

    def test_retrieve_revoked(self, vault):
        """Revoked credential returns None even for owner."""
        entry = _store_sample(vault, owner="tenant-a")
        vault.revoke(entry.credential_id)

        raw = vault.retrieve(entry.credential_id, "tenant-a")
        assert raw is None, "revoked credential should not be retrievable"

    def test_usage_tracking(self, vault):
        """Retrieve updates last_used_at and increments usage_count."""
        entry = _store_sample(vault, owner="tenant-a")
        assert entry.usage_count == 0, "usage_count should start at 0"
        assert entry.last_used_at is None, "last_used_at should start as None"

        vault.retrieve(entry.credential_id, "tenant-a")
        vault.retrieve(entry.credential_id, "tenant-a")

        # Re-fetch the entry from the vault's internal state
        creds = vault.list_credentials(tenant_id="tenant-a")
        updated = [c for c in creds if c.credential_id == entry.credential_id][0]

        assert updated.usage_count == 2, "usage_count should be 2 after two retrievals"
        assert updated.last_used_at is not None, "last_used_at should be set"


class TestCredentialVaultSharing:
    """Tests for credential sharing and unsharing."""

    def test_share_credential(self, vault):
        """Sharing adds the target tenant to the shared_with list."""
        entry = _store_sample(vault, owner="tenant-a")
        result = vault.share(entry.credential_id, "tenant-b")

        assert result is True, "share should return True on success"
        creds = vault.list_credentials(tenant_id="tenant-a")
        updated = [c for c in creds if c.credential_id == entry.credential_id][0]
        assert "tenant-b" in updated.shared_with, (
            "tenant-b should be in shared_with list"
        )

    def test_unshare_credential(self, vault):
        """Unsharing removes the target tenant from shared_with."""
        entry = _store_sample(vault, owner="tenant-a")
        vault.share(entry.credential_id, "tenant-b")
        result = vault.unshare(entry.credential_id, "tenant-b")

        assert result is True, "unshare should return True on success"
        creds = vault.list_credentials(tenant_id="tenant-a")
        updated = [c for c in creds if c.credential_id == entry.credential_id][0]
        assert "tenant-b" not in updated.shared_with, (
            "tenant-b should be removed from shared_with"
        )

        # Verify access is actually revoked
        raw = vault.retrieve(entry.credential_id, "tenant-b")
        assert raw is None, "unshared tenant should no longer have access"


class TestCredentialVaultLifecycle:
    """Tests for revoke, rotate, bind, unbind, update_metadata."""

    def test_revoke_credential(self, vault):
        """Revoking sets status to 'revoked'."""
        entry = _store_sample(vault, owner="tenant-a")
        result = vault.revoke(entry.credential_id)

        assert result is True, "revoke should return True on success"
        creds = vault.list_credentials()
        updated = [c for c in creds if c.credential_id == entry.credential_id][0]
        assert updated.status == "revoked", "status should be revoked"

    def test_revoke_publishes_event(self, vault, event_bus):
        """Revoking a credential publishes a credential.revoked event."""
        received = []
        event_bus.subscribe(EventType.CUSTOM, lambda e: received.append(e))

        entry = _store_sample(vault)
        received.clear()  # Discard the credential.stored event

        vault.revoke(entry.credential_id)

        assert len(received) == 1, "should publish exactly one event"
        assert received[0].data["event"] == "credential.revoked", (
            "event name should be credential.revoked"
        )

    def test_rotate_credential(self, vault):
        """Rotating re-encrypts with new data and updates last_rotated_at."""
        entry = _store_sample(vault, owner="tenant-a")
        new_data = {"api_key": "rotated-key-456", "endpoint": "https://api.sabre.com/v2"}

        rotated = vault.rotate(entry.credential_id, new_data)
        assert rotated is not None, "rotate should return the updated entry"
        assert rotated.last_rotated_at is not None, "last_rotated_at should be set"

        # Verify new data is retrievable
        raw = vault.retrieve(entry.credential_id, "tenant-a")
        assert raw["api_key"] == "rotated-key-456", "rotated data should be retrievable"
        assert raw["endpoint"] == "https://api.sabre.com/v2", (
            "all rotated fields should be correct"
        )

    def test_bind_to_daemon(self, vault):
        """Binding sets daemon_id on the credential."""
        entry = _store_sample(vault, owner="tenant-a")
        result = vault.bind_to_daemon(entry.credential_id, "daemon-xyz")

        assert result is True, "bind_to_daemon should return True"
        creds = vault.list_credentials(tenant_id="tenant-a")
        updated = [c for c in creds if c.credential_id == entry.credential_id][0]
        assert updated.daemon_id == "daemon-xyz", "daemon_id should be set"

    def test_unbind_daemon(self, vault):
        """Unbinding clears daemon_id."""
        entry = _store_sample(vault, owner="tenant-a")
        vault.bind_to_daemon(entry.credential_id, "daemon-xyz")
        result = vault.unbind_daemon(entry.credential_id)

        assert result is True, "unbind_daemon should return True"
        creds = vault.list_credentials(tenant_id="tenant-a")
        updated = [c for c in creds if c.credential_id == entry.credential_id][0]
        assert updated.daemon_id is None, "daemon_id should be None after unbind"

    def test_update_metadata(self, vault):
        """Updating metadata merges new key-value pairs."""
        entry = vault.store(
            owner_tenant_id="tenant-a",
            provider_id="sabre",
            credential_type="api_key",
            raw_data={"api_key": "secret-123"},
            metadata={"region": "US", "version": "1.0"},
        )

        updated = vault.update_metadata(
            entry.credential_id,
            {"version": "2.0", "capabilities": ["search", "book"]},
        )

        assert updated is not None, "update_metadata should return the entry"
        assert updated.metadata["region"] == "US", "existing metadata should be preserved"
        assert updated.metadata["version"] == "2.0", "updated key should have new value"
        assert updated.metadata["capabilities"] == ["search", "book"], (
            "new metadata key should be added"
        )


class TestCredentialVaultListAndStats:
    """Tests for list_credentials, count, and get_stats."""

    def test_list_credentials_no_encrypted_data(self, vault):
        """to_dict() on listed entries does not include encrypted_data."""
        entry = _store_sample(vault)
        creds = vault.list_credentials()
        as_dict = creds[0].to_dict()

        assert "encrypted_data" not in as_dict, (
            "to_dict() should not include encrypted_data by default"
        )

    def test_list_credentials_filtered_by_tenant(self, vault):
        """list_credentials filters to owned + shared credentials."""
        _store_sample(vault, owner="tenant-a", provider="sabre")
        entry_b = _store_sample(vault, owner="tenant-b", provider="amadeus")
        _store_sample(vault, owner="tenant-c", provider="travelport")

        # Share tenant-b's credential with tenant-a
        vault.share(entry_b.credential_id, "tenant-a")

        creds_a = vault.list_credentials(tenant_id="tenant-a")
        assert len(creds_a) == 2, (
            "tenant-a should see 1 owned + 1 shared = 2 credentials"
        )

        creds_c = vault.list_credentials(tenant_id="tenant-c")
        assert len(creds_c) == 1, "tenant-c should see only their own credential"

    def test_count_property(self, vault):
        """count returns total number of stored credentials."""
        assert vault.count == 0, "empty vault should have count 0"
        _store_sample(vault, owner="tenant-a")
        _store_sample(vault, owner="tenant-b")
        assert vault.count == 2, "vault should have count 2 after storing two"

    def test_stats(self, vault):
        """get_stats returns counts grouped by status, provider, and type."""
        _store_sample(vault, owner="tenant-a", provider="sabre", cred_type="api_key")
        _store_sample(vault, owner="tenant-b", provider="amadeus", cred_type="oauth2")
        entry_c = _store_sample(
            vault, owner="tenant-c", provider="sabre", cred_type="api_key"
        )
        vault.revoke(entry_c.credential_id)

        stats = vault.get_stats()

        assert stats["total"] == 3, "total should be 3"
        assert stats["by_status"]["active"] == 2, "2 credentials should be active"
        assert stats["by_status"]["revoked"] == 1, "1 credential should be revoked"
        assert stats["by_provider"]["sabre"] == 2, "2 credentials from sabre"
        assert stats["by_provider"]["amadeus"] == 1, "1 credential from amadeus"
        assert stats["by_type"]["api_key"] == 2, "2 api_key credentials"
        assert stats["by_type"]["oauth2"] == 1, "1 oauth2 credential"


class TestCredentialVaultPersistence:
    """Tests for persistence across vault instances."""

    def test_persistence(self, event_bus, vault_dir):
        """Credentials survive vault recreation from the same storage directory."""
        # Store a credential in the first vault instance
        vault1 = CredentialVault(
            event_bus=event_bus,
            storage_dir=str(vault_dir),
        )
        entry = vault1.store(
            owner_tenant_id="tenant-a",
            provider_id="sabre",
            credential_type="api_key",
            raw_data={"api_key": "persist-me-123"},
        )
        cred_id = entry.credential_id

        # Create a fresh vault from the same directory
        vault2 = CredentialVault(
            event_bus=event_bus,
            storage_dir=str(vault_dir),
        )

        assert vault2.count == 1, "reloaded vault should have 1 credential"

        # Verify the credential is retrievable with correct data
        raw = vault2.retrieve(cred_id, "tenant-a")
        assert raw is not None, "persisted credential should be retrievable"
        assert raw["api_key"] == "persist-me-123", (
            "persisted credential data should match original"
        )


# ===========================================================================
# RevenueCalculator Tests
# ===========================================================================


class TestRevenueCalculatorSplit:
    """Tests for calculate_split with percentage fee + 70/30 model (Build #203)."""

    def test_calculate_split_default(self, calculator):
        """Default split: Pro tier 5% fee + 70/30 router/host on remainder."""
        result = calculator.calculate_split(100.0)

        assert result["transaction_amount"] == 100.0, "transaction_amount should match"
        # Pro tier: 5% of $100 = $5 platform fee, remainder = $95
        # Router gets 70% of $95 = $66.50, Host gets 30% of $95 = $28.50
        assert result["platform_amount"] == 5.0, "platform should get $5.00 (5% Pro)"
        assert result["router_amount"] == 66.5, "router should get $66.50 (70% of $95)"
        assert result["owner_amount"] == 28.5, "owner should get $28.50 (30% of $95)"

    def test_calculate_split_custom(self, calculator):
        """Custom split ratios override the 70/30 default."""
        custom = {
            "credential_host": 0.60,
            "routing_agency": 0.40,
        }
        result = calculator.calculate_split(200.0, custom_split=custom, apai_tier="enterprise")

        # Enterprise tier: 3% of $200 = $6 platform fee, remainder = $194
        assert result["platform_amount"] == 6.0, "platform should get $6.00 (3% Enterprise)"
        assert result["router_amount"] == 77.6, "router should get $77.60 (40% of $194)"
        assert result["owner_amount"] == 116.4, "owner should get $116.40 (60% of $194)"

    def test_platform_fee_floor(self, calculator):
        """Platform fee has a minimum floor of $3.00."""
        # $5 at Scale (2%) = $0.10 raw → floored to $3
        result = calculator.calculate_split(5.0, apai_tier="scale")

        assert result["platform_amount"] == 3.0, (
            "platform fee should be floored to $3.00"
        )
        # Remainder = max(5.0 - 3.0, 0) = $2.00, router = 70% = $1.40, host = 30% = $0.60
        assert result["router_amount"] == 1.4, "router should get $1.40"
        assert result["owner_amount"] == 0.6, (
            "owner should get remainder after floor adjustment"
        )

    def test_platform_fee_scales_with_transaction(self, calculator):
        """Platform fee scales as percentage — NO cap. $5000 Pro = $250."""
        result = calculator.calculate_split(5000.0)

        assert result["platform_amount"] == 250.0, (
            "platform fee should be $250.00 (5% of $5000, NO cap)"
        )
        # Remainder = $4750, router = 70% = $3325.00, host = 30% = $1425.00
        assert result["router_amount"] == 3325.0, "router should get $3325.00"
        assert result["owner_amount"] == 1425.0, (
            "owner should get $1425.00"
        )


class TestRevenueCalculatorRecords:
    """Tests for recording, settling, and querying revenue records."""

    def test_record_revenue(self, calculator):
        """record_revenue creates a persisted record with correct amounts."""
        record = calculator.record_revenue(
            route_result_id="route-001",
            credential_id="cred-abc",
            owner_tenant_id="tenant-host",
            router_tenant_id="tenant-router",
            provider_id="sabre",
            transaction_amount=100.0,
            apai_tier="pro",
        )

        assert record.record_id, "record_id should be set"
        assert record.transaction_amount_usd == 100.0, "transaction amount should match"
        # Pro 5% of $100 = $5 platform, remainder $95: host=30%=$28.50, router=70%=$66.50
        assert record.owner_amount_usd == 28.5, "owner amount should be $28.50"
        assert record.platform_amount_usd == 5.0, "platform amount should be $5.00"
        assert record.router_amount_usd == 66.5, "router amount should be $66.50"
        assert record.status == "pending", "status should default to pending"
        assert record.period, "period should be set (YYYY-MM)"
        assert calculator.record_count == 1, "calculator should have 1 record"

    def test_settle_record(self, calculator):
        """settle_record marks the record status as settled."""
        record = calculator.record_revenue(
            route_result_id="route-002",
            credential_id="cred-abc",
            owner_tenant_id="tenant-host",
            router_tenant_id="tenant-router",
            provider_id="sabre",
            transaction_amount=50.0,
        )

        settled = calculator.settle_record(record.record_id)
        assert settled is not None, "settle_record should return the record"
        assert settled.status == "settled", "status should be settled"

    def test_tenant_summary(self, calculator):
        """get_tenant_summary aggregates revenue by tenant role."""
        current_period = time.strftime("%Y-%m")

        calculator.record_revenue(
            route_result_id="route-001",
            credential_id="cred-abc",
            owner_tenant_id="tenant-host",
            router_tenant_id="tenant-router",
            provider_id="sabre",
            transaction_amount=100.0,
        )
        calculator.record_revenue(
            route_result_id="route-002",
            credential_id="cred-abc",
            owner_tenant_id="tenant-host",
            router_tenant_id="tenant-router",
            provider_id="sabre",
            transaction_amount=200.0,
        )

        summary = calculator.get_tenant_summary("tenant-host", period=current_period)

        assert summary["tenant_id"] == "tenant-host", "tenant_id should match"
        assert summary["transactions"] == 2, "should have 2 transactions as host"
        assert summary["earned_as_host"] > 0, "should have positive host earnings"
        # Pro 5% platform + 70/30 on remainder:
        # $100: platform=$5, remainder=$95, host=30%=$28.50
        # $200: platform=$10, remainder=$190, host=30%=$57.00
        # Total host = $28.50 + $57.00 = $85.50
        assert summary["earned_as_host"] == 85.50, "host earnings should be $85.50"

    def test_network_revenue(self, calculator):
        """get_network_revenue aggregates platform-wide metrics."""
        current_period = time.strftime("%Y-%m")

        calculator.record_revenue(
            route_result_id="route-001",
            credential_id="cred-abc",
            owner_tenant_id="tenant-a",
            router_tenant_id="tenant-b",
            provider_id="sabre",
            transaction_amount=100.0,
        )
        calculator.record_revenue(
            route_result_id="route-002",
            credential_id="cred-def",
            owner_tenant_id="tenant-c",
            router_tenant_id="tenant-d",
            provider_id="amadeus",
            transaction_amount=300.0,
        )

        network = calculator.get_network_revenue(period=current_period)

        assert network["total_volume_usd"] == 400.0, "total volume should be $400"
        assert network["transactions"] == 2, "should have 2 transactions"
        assert network["platform_revenue_usd"] > 0, (
            "platform should have positive revenue"
        )
        # Pro 5%: $100 * 5% = $5 + $300 * 5% = $15 → total $20
        assert network["platform_revenue_usd"] == 20.0, (
            "platform revenue should be $20.00 (5% Pro on $100 + $300)"
        )
        assert network["avg_transaction_usd"] == 200.0, (
            "average transaction should be $200"
        )

    def test_get_records_filtered(self, calculator):
        """get_records filters by tenant, period, and status."""
        current_period = time.strftime("%Y-%m")

        r1 = calculator.record_revenue(
            route_result_id="route-001",
            credential_id="cred-abc",
            owner_tenant_id="tenant-a",
            router_tenant_id="tenant-b",
            provider_id="sabre",
            transaction_amount=100.0,
        )
        calculator.record_revenue(
            route_result_id="route-002",
            credential_id="cred-def",
            owner_tenant_id="tenant-c",
            router_tenant_id="tenant-d",
            provider_id="amadeus",
            transaction_amount=200.0,
        )
        calculator.settle_record(r1.record_id)

        # Filter by tenant
        by_tenant = calculator.get_records(tenant_id="tenant-a")
        assert len(by_tenant) == 1, "should find 1 record for tenant-a"
        assert by_tenant[0].owner_tenant_id == "tenant-a", (
            "filtered record should belong to tenant-a"
        )

        # Filter by status
        settled = calculator.get_records(status="settled")
        assert len(settled) == 1, "should find 1 settled record"
        assert settled[0].status == "settled", "filtered record should be settled"

        pending = calculator.get_records(status="pending")
        assert len(pending) == 1, "should find 1 pending record"

        # Filter by period
        by_period = calculator.get_records(period=current_period)
        assert len(by_period) == 2, "should find 2 records in current period"

        wrong_period = calculator.get_records(period="1999-01")
        assert len(wrong_period) == 0, "should find 0 records for a past period"


class TestRevenueCalculatorPersistence:
    """Tests for revenue record persistence across instances."""

    def test_persistence(self, revenue_dir):
        """Revenue records survive calculator recreation from same storage."""
        calc1 = RevenueCalculator(storage_dir=str(revenue_dir))
        record = calc1.record_revenue(
            route_result_id="route-persist",
            credential_id="cred-xyz",
            owner_tenant_id="tenant-a",
            router_tenant_id="tenant-b",
            provider_id="sabre",
            transaction_amount=150.0,
        )
        record_id = record.record_id

        # Create a fresh calculator from the same directory
        calc2 = RevenueCalculator(storage_dir=str(revenue_dir))

        assert calc2.record_count == 1, "reloaded calculator should have 1 record"

        records = calc2.get_records(tenant_id="tenant-a")
        assert len(records) == 1, "persisted record should be queryable"
        assert records[0].record_id == record_id, "record_id should match"
        assert records[0].transaction_amount_usd == 150.0, (
            "persisted transaction amount should match"
        )
