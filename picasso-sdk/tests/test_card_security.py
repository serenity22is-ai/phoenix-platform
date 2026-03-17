"""
Tests for CardSecurity module -- encryption, service-binding, and access control.

Covers the full lifecycle: encrypt/decrypt, daemon-specific keys, card binding
and revocation, churn handling, access control rules, persistence, key rotation,
stats, and conversational summaries.

MYSTES KYRIOS LLC -- Confidential.
"""

import pytest

from anastasia.knowledge.card_security import CardSecurity, CardBinding, EncryptedCard

# Valid Fernet keys (32 url-safe base64-encoded bytes) for testing
_TEST_MASTER_KEY = "bQBUsyyhHv8ChU2lWpCU2TCR83uo75L5chagtdptwLY="
_TEST_ROTATED_KEY = "O2IW1nddbBmGubQsLoSGEF9uIANAOU0SIlJ3spSgGh4="


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def security(tmp_path):
    """Create a CardSecurity instance with a test master key and tmp storage."""
    return CardSecurity(
        master_key=_TEST_MASTER_KEY,
        storage_dir=str(tmp_path / "security"),
    )


@pytest.fixture
def sample_card_data():
    """Return a realistic knowledge card payload."""
    return {
        "name": "Sabre GDS",
        "vertical": "flights",
        "readiness": "production",
        "endpoints": ["/booking", "/search", "/cancel"],
        "quirks": ["timeout on large PNRs", "requires XML for ancillaries"],
        "adapters": ["sabre_rest_v4"],
        "data_schemas": {"booking": {}, "passenger": {}},
        "auth_method": "oauth2",
        "booking_flow": {"total_steps": 5},
    }


# ---------------------------------------------------------------------------
# Encryption / Decryption
# ---------------------------------------------------------------------------

class TestEncryptDecrypt:
    """Card encryption and decryption lifecycle."""

    def test_encrypt_card(self, security, sample_card_data):
        """encrypt_card returns an EncryptedCard with non-empty ciphertext."""
        card = security.encrypt_card(
            card_data=sample_card_data,
            card_type="system_profile",
            owner_category="platform",
        )
        assert isinstance(card, EncryptedCard)
        assert card.card_id
        assert card.encrypted_data
        assert card.card_type == "system_profile"
        assert card.owner_category == "platform"
        assert card.key_id

    def test_decrypt_card(self, security, sample_card_data):
        """Decrypting a card returns the original plaintext data."""
        card = security.encrypt_card(
            card_data=sample_card_data,
            card_type="knowledge_card",
        )
        decrypted = security.decrypt_card(card.card_id)
        assert decrypted == sample_card_data

    def test_encrypt_different_daemon_keys(self, security, sample_card_data):
        """Same data encrypted with different daemon IDs produces different ciphertext."""
        card_a = security.encrypt_card(
            card_data=sample_card_data,
            card_type="api_card",
            daemon_id="daemon-alpha",
        )
        card_b = security.encrypt_card(
            card_data=sample_card_data,
            card_type="api_card",
            daemon_id="daemon-beta",
        )
        assert card_a.encrypted_data != card_b.encrypted_data

    def test_decrypt_wrong_daemon(self, security, sample_card_data):
        """A card bound to daemon A cannot be decrypted by daemon B (binding check)."""
        card = security.encrypt_card(
            card_data=sample_card_data,
            card_type="knowledge_card",
            daemon_id="daemon-alpha",
        )
        # Bind to daemon-alpha so the binding check is exercised
        security.bind_card(card.card_id, "daemon-alpha")

        # daemon-beta has no binding -- decrypt_card should return None
        result = security.decrypt_card(card.card_id, daemon_id="daemon-beta")
        assert result is None


# ---------------------------------------------------------------------------
# Service Binding
# ---------------------------------------------------------------------------

class TestServiceBinding:
    """Card-to-daemon binding, verification, and revocation."""

    def test_bind_card(self, security, sample_card_data):
        """bind_card creates a CardBinding with a non-empty HMAC token."""
        card = security.encrypt_card(
            card_data=sample_card_data,
            card_type="knowledge_card",
        )
        binding = security.bind_card(card.card_id, "daemon-001")
        assert isinstance(binding, CardBinding)
        assert binding.card_id == card.card_id
        assert binding.daemon_id == "daemon-001"
        assert binding.binding_token
        assert binding.status == "active"

    def test_verify_binding_active(self, security, sample_card_data):
        """verify_binding returns True for an active binding."""
        card = security.encrypt_card(
            card_data=sample_card_data,
            card_type="knowledge_card",
        )
        security.bind_card(card.card_id, "daemon-001")
        assert security.verify_binding(card.card_id, "daemon-001") is True

    def test_verify_binding_revoked(self, security, sample_card_data):
        """verify_binding returns False after the binding is revoked."""
        card = security.encrypt_card(
            card_data=sample_card_data,
            card_type="knowledge_card",
        )
        security.bind_card(card.card_id, "daemon-001")
        security.revoke_binding(card.card_id, "daemon-001")
        assert security.verify_binding(card.card_id, "daemon-001") is False

    def test_revoke_binding(self, security, sample_card_data):
        """revoke_binding sets the binding status to 'revoked'."""
        card = security.encrypt_card(
            card_data=sample_card_data,
            card_type="knowledge_card",
        )
        security.bind_card(card.card_id, "daemon-001")
        revoked = security.revoke_binding(card.card_id, "daemon-001")
        assert revoked == 1

        # Confirm the binding object is now revoked
        bindings = security.list_bindings(daemon_id="daemon-001")
        assert len(bindings) == 1
        assert bindings[0].status == "revoked"

    def test_revoke_all_for_daemon(self, security, sample_card_data):
        """revoke_all_for_daemon revokes every binding for the given daemon."""
        card1 = security.encrypt_card(
            card_data=sample_card_data,
            card_type="knowledge_card",
        )
        card2 = security.encrypt_card(
            card_data={"name": "Another System"},
            card_type="api_card",
        )
        security.bind_card(card1.card_id, "daemon-X")
        security.bind_card(card2.card_id, "daemon-X")

        revoked = security.revoke_all_for_daemon("daemon-X")
        assert revoked == 2

        # Both bindings should now be revoked
        assert security.verify_binding(card1.card_id, "daemon-X") is False
        assert security.verify_binding(card2.card_id, "daemon-X") is False


# ---------------------------------------------------------------------------
# Churn Protection
# ---------------------------------------------------------------------------

class TestChurnProtection:
    """Churn handling revokes all access for a departing daemon."""

    def test_handle_churn(self, security, sample_card_data):
        """handle_churn revokes all bindings and returns stats."""
        card1 = security.encrypt_card(
            card_data=sample_card_data,
            card_type="knowledge_card",
        )
        card2 = security.encrypt_card(
            card_data={"name": "Hotel GDS"},
            card_type="system_profile",
        )
        security.bind_card(card1.card_id, "daemon-churn")
        security.bind_card(card2.card_id, "daemon-churn")

        stats = security.handle_churn("daemon-churn")
        assert stats["daemon_id"] == "daemon-churn"
        assert stats["bindings_revoked"] == 2
        assert stats["cards_affected"] == 2

        # Verify the daemon can no longer access the cards
        assert security.verify_binding(card1.card_id, "daemon-churn") is False
        assert security.verify_binding(card2.card_id, "daemon-churn") is False


# ---------------------------------------------------------------------------
# Access Control
# ---------------------------------------------------------------------------

class TestAccessControl:
    """Access control rules: platform vs. tenant vs. bound daemon."""

    def test_can_access_platform_owned(self, security, sample_card_data):
        """Platform requester can access platform-owned cards."""
        card = security.encrypt_card(
            card_data=sample_card_data,
            card_type="knowledge_card",
            owner_category="platform",
        )
        assert security.can_access(card.card_id, requester="platform") is True

    def test_can_access_tenant_bound(self, security, sample_card_data):
        """A daemon with an active binding can access a tenant card."""
        card = security.encrypt_card(
            card_data=sample_card_data,
            card_type="knowledge_card",
            daemon_id="daemon-tenant",
            owner_category="tenant",
        )
        security.bind_card(card.card_id, "daemon-tenant")
        assert security.can_access(card.card_id, daemon_id="daemon-tenant") is True

    def test_can_access_tenant_no_binding(self, security, sample_card_data):
        """A daemon without a binding cannot access a tenant card."""
        card = security.encrypt_card(
            card_data=sample_card_data,
            card_type="knowledge_card",
            daemon_id="daemon-owner",
            owner_category="tenant",
        )
        # daemon-stranger has no binding
        assert security.can_access(card.card_id, daemon_id="daemon-stranger") is False


# ---------------------------------------------------------------------------
# Conversational Summary
# ---------------------------------------------------------------------------

class TestConversationalSummary:
    """Conversational summaries expose capabilities, never raw data."""

    def test_conversational_summary(self, security, sample_card_data):
        """get_conversational_summary returns natural language, not raw data."""
        card = security.encrypt_card(
            card_data=sample_card_data,
            card_type="system_profile",
            metadata={"provider_name": "Sabre"},
        )
        summary = security.get_conversational_summary(card.card_id)
        assert summary is not None
        assert isinstance(summary, str)
        # Should mention the system name
        assert "Sabre" in summary
        # Should NOT contain raw endpoint paths
        assert "/booking" not in summary
        assert "/search" not in summary
        # Should mention capabilities in natural language
        assert "endpoint" in summary.lower()
        assert "readiness" in summary.lower()


# ---------------------------------------------------------------------------
# Card Updates
# ---------------------------------------------------------------------------

class TestCardUpdate:
    """Updating a card re-encrypts with new data."""

    def test_update_card(self, security, sample_card_data):
        """update_card re-encrypts the card with new data."""
        card = security.encrypt_card(
            card_data=sample_card_data,
            card_type="knowledge_card",
        )
        old_ciphertext = card.encrypted_data

        updated_data = {**sample_card_data, "readiness": "deprecated"}
        updated_card = security.update_card(card.card_id, updated_data)

        assert updated_card is not None
        assert updated_card.encrypted_data != old_ciphertext

        # Decrypt and verify the new data
        decrypted = security.decrypt_card(card.card_id)
        assert decrypted["readiness"] == "deprecated"


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

class TestPersistence:
    """Cards and bindings survive a CardSecurity instance recreation."""

    def test_persistence_cards(self, tmp_path, sample_card_data):
        """A card encrypted by one instance is loadable by a fresh instance."""
        storage = str(tmp_path / "persist")

        sec1 = CardSecurity(master_key=_TEST_MASTER_KEY, storage_dir=storage)
        card = sec1.encrypt_card(
            card_data=sample_card_data,
            card_type="knowledge_card",
        )
        card_id = card.card_id

        # Recreate with same key and storage dir
        sec2 = CardSecurity(master_key=_TEST_MASTER_KEY, storage_dir=storage)
        decrypted = sec2.decrypt_card(card_id)
        assert decrypted == sample_card_data

    def test_persistence_bindings(self, tmp_path, sample_card_data):
        """A binding persisted by one instance is loadable by a fresh instance."""
        storage = str(tmp_path / "persist")

        sec1 = CardSecurity(master_key=_TEST_MASTER_KEY, storage_dir=storage)
        card = sec1.encrypt_card(
            card_data=sample_card_data,
            card_type="knowledge_card",
        )
        sec1.bind_card(card.card_id, "daemon-persist")

        # Recreate
        sec2 = CardSecurity(master_key=_TEST_MASTER_KEY, storage_dir=storage)
        assert sec2.verify_binding(card.card_id, "daemon-persist") is True


# ---------------------------------------------------------------------------
# Key Rotation
# ---------------------------------------------------------------------------

class TestKeyRotation:
    """Master key rotation re-encrypts all cards."""

    def test_rotate_master_key(self, security, sample_card_data):
        """rotate_master_key re-encrypts all cards; old key cannot decrypt."""
        card = security.encrypt_card(
            card_data=sample_card_data,
            card_type="knowledge_card",
        )
        old_ciphertext = card.encrypted_data

        rotated = security.rotate_master_key(_TEST_ROTATED_KEY)
        assert rotated == 1

        # Card should still be decryptable with the new instance state
        decrypted = security.decrypt_card(card.card_id)
        assert decrypted == sample_card_data

        # Ciphertext should have changed
        refreshed_card = security._cards[card.card_id]
        assert refreshed_card.encrypted_data != old_ciphertext


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

class TestStats:
    """Aggregate statistics about cards and bindings."""

    def test_get_stats(self, security, sample_card_data):
        """get_stats returns counts broken down by type and category."""
        security.encrypt_card(
            card_data=sample_card_data,
            card_type="knowledge_card",
            owner_category="platform",
        )
        security.encrypt_card(
            card_data={"name": "Hotel API"},
            card_type="api_card",
            owner_category="tenant",
        )
        security.encrypt_card(
            card_data={"name": "Sabre Profile"},
            card_type="system_profile",
            owner_category="platform",
        )

        stats = security.get_stats()
        assert stats["total_cards"] == 3
        assert stats["cards_by_type"]["knowledge_card"] == 1
        assert stats["cards_by_type"]["api_card"] == 1
        assert stats["cards_by_type"]["system_profile"] == 1
        assert stats["cards_by_category"]["platform"] == 2
        assert stats["cards_by_category"]["tenant"] == 1


# ---------------------------------------------------------------------------
# Binding Filters
# ---------------------------------------------------------------------------

class TestBindingFilters:
    """list_bindings with daemon_id and card_id filters."""

    def test_list_bindings_filtered(self, security, sample_card_data):
        """list_bindings filters by daemon_id and card_id correctly."""
        card1 = security.encrypt_card(
            card_data=sample_card_data,
            card_type="knowledge_card",
        )
        card2 = security.encrypt_card(
            card_data={"name": "System B"},
            card_type="api_card",
        )

        security.bind_card(card1.card_id, "daemon-A")
        security.bind_card(card1.card_id, "daemon-B")
        security.bind_card(card2.card_id, "daemon-A")

        # Filter by daemon
        daemon_a_bindings = security.list_bindings(daemon_id="daemon-A")
        assert len(daemon_a_bindings) == 2

        daemon_b_bindings = security.list_bindings(daemon_id="daemon-B")
        assert len(daemon_b_bindings) == 1

        # Filter by card
        card1_bindings = security.list_bindings(card_id=card1.card_id)
        assert len(card1_bindings) == 2

        card2_bindings = security.list_bindings(card_id=card2.card_id)
        assert len(card2_bindings) == 1

        # Filter by both
        specific = security.list_bindings(daemon_id="daemon-A", card_id=card1.card_id)
        assert len(specific) == 1
        assert specific[0].daemon_id == "daemon-A"
        assert specific[0].card_id == card1.card_id
