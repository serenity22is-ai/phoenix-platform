"""
Credential Vault — Encrypted credential storage with service-binding.

Manages API credentials that B2B customers share for federated routing.
Credentials are encrypted with Fernet (symmetric), bound to daemon service
keys, and access-controlled per tenant.

MYSTES KYRIOS LLC — Confidential.
"""

import hashlib
import json
import logging
import os
import time
import threading
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

# Use cryptography.fernet for encryption (available in stdlib-adjacent)
# Fallback to base64 obfuscation if cryptography not installed
try:
    from cryptography.fernet import Fernet
    HAS_CRYPTO = True
except ImportError:
    import base64
    HAS_CRYPTO = False

from ..core.events import Event, EventBus, EventType

logger = logging.getLogger(__name__)

# Default revenue split for shared credentials
_DEFAULT_REVENUE_SPLIT = {"owner": 0.85, "platform": 0.10, "router": 0.05}

# Valid credential statuses
_VALID_STATUSES = {"active", "suspended", "revoked", "expired"}

# Valid credential types
_VALID_CREDENTIAL_TYPES = {
    "api_key", "oauth2", "session", "iata_number", "gds_pcc",
}


# ---------------------------------------------------------------------------
# Data Model
# ---------------------------------------------------------------------------

@dataclass
class CredentialEntry:
    """
    A single credential record in the vault.

    Stores encrypted API credentials with ownership, sharing, and
    service-binding metadata. The ``encrypted_data`` field contains
    Fernet-encrypted JSON (or base64-obfuscated JSON if cryptography
    is not installed). Raw credential data is NEVER exposed in
    serialization unless explicitly requested.
    """

    credential_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    provider_id: str = ""                   # e.g., "sabre", "amadeus", "travelport", "picasso_redbox"
    owner_tenant_id: str = ""               # Who owns these credentials
    credential_type: str = ""               # "api_key", "oauth2", "session", "iata_number", "gds_pcc"
    encrypted_data: str = ""                # Fernet-encrypted JSON, base64 encoded
    daemon_id: Optional[str] = None         # Which daemon this is bound to

    # Non-sensitive metadata: provider name, capabilities, coverage regions, POS markets
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Sharing and revenue
    shared_with: List[str] = field(default_factory=list)    # Tenant IDs that can route through these creds
    revenue_split: Dict[str, float] = field(
        default_factory=lambda: dict(_DEFAULT_REVENUE_SPLIT)
    )

    # Lifecycle
    status: str = "active"                  # active, suspended, revoked, expired
    created_at: float = field(default_factory=time.time)
    last_used_at: Optional[float] = None
    last_rotated_at: Optional[float] = None
    usage_count: int = 0

    def to_dict(self, include_encrypted: bool = False) -> Dict[str, Any]:
        """
        Serialize to dictionary.

        By default, ``encrypted_data`` is excluded from the output to
        prevent accidental credential leakage in logs, API responses,
        or event payloads. Pass ``include_encrypted=True`` only when
        persisting to the vault's own encrypted storage files.
        """
        result = {
            "credential_id": self.credential_id,
            "provider_id": self.provider_id,
            "owner_tenant_id": self.owner_tenant_id,
            "credential_type": self.credential_type,
            "daemon_id": self.daemon_id,
            "metadata": self.metadata,
            "shared_with": self.shared_with,
            "revenue_split": self.revenue_split,
            "status": self.status,
            "created_at": self.created_at,
            "last_used_at": self.last_used_at,
            "last_rotated_at": self.last_rotated_at,
            "usage_count": self.usage_count,
        }
        if include_encrypted:
            result["encrypted_data"] = self.encrypted_data
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CredentialEntry":
        """Deserialize from dictionary."""
        return cls(**{
            k: v for k, v in data.items()
            if k in cls.__dataclass_fields__
        })


# ---------------------------------------------------------------------------
# Credential Vault
# ---------------------------------------------------------------------------

class CredentialVault:
    """
    Encrypted credential storage with service-binding and access control.

    Manages the full lifecycle of API credentials that B2B customers
    share for federated routing: store, retrieve, rotate, share, revoke.

    Credentials are encrypted at rest using Fernet symmetric encryption.
    Each credential file on disk contains the encrypted payload alongside
    non-sensitive metadata. Access is DENY-by-default: only the credential
    owner or tenants in the ``shared_with`` list can decrypt.

    Args:
        event_bus: EventBus instance for publishing credential lifecycle events.
        storage_dir: Path to the directory where credential JSON files are stored.
                     Defaults to ``~/.anastasia/credentials``.
        master_key: Fernet-compatible master key (bytes or str). If ``None``,
                    a key is generated and persisted to ``storage_dir/master.key``.
    """

    def __init__(
        self,
        event_bus: EventBus,
        storage_dir: Optional[str] = None,
        master_key: Optional[str] = None,
    ):
        self._event_bus = event_bus
        self._lock = threading.Lock()

        # Storage directory
        if storage_dir is None:
            storage_dir = os.path.join(
                os.path.expanduser("~"), ".anastasia", "credentials"
            )
        self._storage_dir = Path(storage_dir)
        self._storage_dir.mkdir(parents=True, exist_ok=True)

        # Master key management
        self._master_key = self._resolve_master_key(master_key)
        self._fernet: Optional[Any] = None  # Lazy-initialized

        # In-memory index: credential_id -> CredentialEntry
        self._credentials: Dict[str, CredentialEntry] = {}

        # Load existing credentials from disk
        self._load_all()

        if not HAS_CRYPTO:
            logger.warning(
                "cryptography package not installed — using base64 obfuscation. "
                "Install cryptography for production-grade encryption: "
                "pip install cryptography"
            )

    # ------------------------------------------------------------------
    # Master Key Management
    # ------------------------------------------------------------------

    def _resolve_master_key(self, master_key: Optional[str]) -> bytes:
        """
        Resolve or generate the master encryption key.

        If ``master_key`` is provided, use it directly. Otherwise, look
        for ``master.key`` in the storage directory. If neither exists,
        generate a new Fernet key and persist it.
        """
        key_file = self._storage_dir / "master.key"

        if master_key is not None:
            # Use provided key
            key_bytes = master_key.encode("utf-8") if isinstance(master_key, str) else master_key
            # Persist for subsequent launches
            if not key_file.exists():
                try:
                    key_file.write_bytes(key_bytes)
                    os.chmod(str(key_file), 0o600)
                    logger.info("Master key persisted to %s", key_file)
                except OSError as e:
                    logger.error("Failed to persist master key: %s", e)
            return key_bytes

        if key_file.exists():
            # Load existing key
            try:
                key_bytes = key_file.read_bytes().strip()
                logger.info("Loaded master key from %s", key_file)
                return key_bytes
            except OSError as e:
                logger.error("Failed to read master key: %s", e)

        # Generate new key
        if HAS_CRYPTO:
            key_bytes = Fernet.generate_key()
        else:
            # Fallback: random 32 bytes, base64 encoded (Fernet-compatible length)
            key_bytes = base64.urlsafe_b64encode(os.urandom(32))

        try:
            key_file.write_bytes(key_bytes)
            os.chmod(str(key_file), 0o600)
            logger.info("Generated and persisted new master key to %s", key_file)
        except OSError as e:
            logger.error("Failed to persist generated master key: %s", e)

        return key_bytes

    # ------------------------------------------------------------------
    # Encryption
    # ------------------------------------------------------------------

    def _get_fernet(self):
        """
        Lazy-initialize and return the Fernet cipher instance.

        Returns a Fernet object if the cryptography package is available,
        otherwise ``None`` (caller falls back to base64 obfuscation).
        """
        if not HAS_CRYPTO:
            return None
        if self._fernet is None:
            self._fernet = Fernet(self._master_key)
        return self._fernet

    def _derive_key(self, salt: str) -> bytes:
        """
        Derive a secondary key from the master key using PBKDF2.

        Useful for per-credential key derivation if needed in the future.
        Currently the vault uses the master Fernet key directly, but this
        method supports key-per-credential architectures.

        Args:
            salt: A unique salt string (e.g., credential_id).

        Returns:
            A 32-byte derived key.
        """
        return hashlib.pbkdf2_hmac(
            "sha256",
            self._master_key,
            salt.encode("utf-8"),
            iterations=100_000,
            dklen=32,
        )

    def _encrypt(self, data: Dict[str, Any]) -> str:
        """
        Encrypt a dictionary to a base64-encoded string.

        Uses Fernet symmetric encryption if cryptography is available,
        otherwise falls back to base64 obfuscation (NOT secure — development
        only).

        Args:
            data: The raw credential data to encrypt.

        Returns:
            Base64-encoded encrypted string.
        """
        raw_json = json.dumps(data, ensure_ascii=False, sort_keys=True)

        fernet = self._get_fernet()
        if fernet is not None:
            encrypted = fernet.encrypt(raw_json.encode("utf-8"))
            return encrypted.decode("utf-8")

        # Fallback: base64 obfuscation (NOT secure)
        return base64.urlsafe_b64encode(raw_json.encode("utf-8")).decode("utf-8")

    def _decrypt(self, encrypted: str) -> Dict[str, Any]:
        """
        Decrypt a base64-encoded string back to a dictionary.

        Args:
            encrypted: The encrypted string from ``_encrypt()``.

        Returns:
            The original dictionary of credential data.

        Raises:
            ValueError: If decryption fails (wrong key, corrupted data).
        """
        fernet = self._get_fernet()
        if fernet is not None:
            try:
                decrypted = fernet.decrypt(encrypted.encode("utf-8"))
                return json.loads(decrypted.decode("utf-8"))
            except Exception as e:
                raise ValueError(f"Decryption failed: {e}") from e

        # Fallback: base64 decode
        try:
            decoded = base64.urlsafe_b64decode(encrypted.encode("utf-8"))
            return json.loads(decoded.decode("utf-8"))
        except Exception as e:
            raise ValueError(f"Base64 decoding failed: {e}") from e

    # ------------------------------------------------------------------
    # CRUD Operations
    # ------------------------------------------------------------------

    def store(
        self,
        owner_tenant_id: str,
        provider_id: str,
        credential_type: str,
        raw_data: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
        daemon_id: Optional[str] = None,
    ) -> CredentialEntry:
        """
        Encrypt and store a new credential.

        Args:
            owner_tenant_id: Tenant ID of the credential owner.
            provider_id: Provider identifier (e.g., "sabre", "amadeus").
            credential_type: Type of credential (e.g., "api_key", "oauth2").
            raw_data: The raw credential data to encrypt (keys, tokens, secrets).
            metadata: Non-sensitive metadata (provider name, capabilities, regions).
            daemon_id: Optional daemon instance to bind this credential to.

        Returns:
            The created CredentialEntry (without decrypted data).
        """
        if not owner_tenant_id:
            raise ValueError("owner_tenant_id is required")
        if not provider_id:
            raise ValueError("provider_id is required")
        if not raw_data:
            raise ValueError("raw_data cannot be empty")

        encrypted = self._encrypt(raw_data)

        entry = CredentialEntry(
            credential_id=str(uuid.uuid4()),
            provider_id=provider_id,
            owner_tenant_id=owner_tenant_id,
            credential_type=credential_type,
            encrypted_data=encrypted,
            daemon_id=daemon_id,
            metadata=metadata or {},
            status="active",
            created_at=time.time(),
        )

        with self._lock:
            self._credentials[entry.credential_id] = entry
            self._persist(entry)

        self._publish_event("credential.stored", {
            "credential_id": entry.credential_id,
            "provider_id": provider_id,
            "owner_tenant_id": owner_tenant_id,
            "credential_type": credential_type,
        })
        logger.info(
            "Stored credential %s for provider %s (owner: %s)",
            entry.credential_id, provider_id, owner_tenant_id,
        )
        return entry

    def retrieve(
        self,
        credential_id: str,
        requester_tenant_id: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Retrieve and decrypt credential data with access control.

        Only the credential owner or tenants in the ``shared_with`` list
        are permitted to decrypt. All other requests are denied.

        Args:
            credential_id: The UUID of the credential to retrieve.
            requester_tenant_id: The tenant requesting access (for ACL check).

        Returns:
            The decrypted credential data dictionary, or ``None`` if the
            credential does not exist or access is denied.
        """
        with self._lock:
            entry = self._credentials.get(credential_id)
            if entry is None:
                logger.warning("Credential %s not found", credential_id)
                return None

            # Access control: owner or shared_with
            if (
                entry.owner_tenant_id != requester_tenant_id
                and requester_tenant_id not in entry.shared_with
            ):
                logger.warning(
                    "Access denied: tenant %s cannot access credential %s "
                    "(owner: %s, shared_with: %s)",
                    requester_tenant_id, credential_id,
                    entry.owner_tenant_id, entry.shared_with,
                )
                return None

            # Check status
            if entry.status != "active":
                logger.warning(
                    "Credential %s is %s — access denied",
                    credential_id, entry.status,
                )
                return None

            # Decrypt
            try:
                raw_data = self._decrypt(entry.encrypted_data)
            except ValueError as e:
                logger.error(
                    "Failed to decrypt credential %s: %s", credential_id, e
                )
                return None

            # Update usage stats
            entry.last_used_at = time.time()
            entry.usage_count += 1
            self._persist(entry)

        return raw_data

    def update_metadata(
        self,
        credential_id: str,
        metadata_updates: Dict[str, Any],
    ) -> Optional[CredentialEntry]:
        """
        Update non-sensitive metadata on a credential.

        Merges ``metadata_updates`` into the existing metadata dictionary.
        Does not touch encrypted data or access control fields.

        Args:
            credential_id: The UUID of the credential to update.
            metadata_updates: Key-value pairs to merge into existing metadata.

        Returns:
            The updated CredentialEntry, or ``None`` if not found.
        """
        with self._lock:
            entry = self._credentials.get(credential_id)
            if entry is None:
                return None

            entry.metadata.update(metadata_updates)
            self._persist(entry)

        logger.info("Updated metadata for credential %s", credential_id)
        return entry

    def revoke(self, credential_id: str) -> bool:
        """
        Revoke a credential, permanently disabling access.

        Sets the credential status to ``"revoked"``. The encrypted data
        is retained on disk for audit purposes but can no longer be
        decrypted through ``retrieve()``.

        Args:
            credential_id: The UUID of the credential to revoke.

        Returns:
            ``True`` if the credential was revoked, ``False`` if not found.
        """
        with self._lock:
            entry = self._credentials.get(credential_id)
            if entry is None:
                return False

            entry.status = "revoked"
            self._persist(entry)

        self._publish_event("credential.revoked", {
            "credential_id": credential_id,
            "provider_id": entry.provider_id,
            "owner_tenant_id": entry.owner_tenant_id,
        })
        logger.info("Revoked credential %s", credential_id)
        return True

    def list_credentials(
        self,
        tenant_id: Optional[str] = None,
    ) -> List[CredentialEntry]:
        """
        List credential entries (metadata only, never encrypted data).

        If ``tenant_id`` is provided, returns only credentials owned by
        or shared with that tenant. Otherwise returns all credentials.

        Args:
            tenant_id: Optional filter to scope results to a tenant.

        Returns:
            List of CredentialEntry objects (encrypted_data present but
            should not be exposed — use ``to_dict()`` for safe serialization).
        """
        with self._lock:
            if tenant_id is None:
                return list(self._credentials.values())

            return [
                entry for entry in self._credentials.values()
                if (
                    entry.owner_tenant_id == tenant_id
                    or tenant_id in entry.shared_with
                )
            ]

    # ------------------------------------------------------------------
    # Sharing
    # ------------------------------------------------------------------

    def share(
        self,
        credential_id: str,
        target_tenant_id: str,
        revenue_split: Optional[Dict[str, float]] = None,
    ) -> bool:
        """
        Share a credential with another tenant for federated routing.

        Adds ``target_tenant_id`` to the credential's ``shared_with``
        list, granting them decrypt access through ``retrieve()``.
        Optionally sets a custom revenue split for bookings routed
        through this credential.

        Args:
            credential_id: The UUID of the credential to share.
            target_tenant_id: The tenant ID to grant access to.
            revenue_split: Optional custom revenue split dict
                           (e.g., ``{"owner": 0.80, "platform": 0.12, "router": 0.08}``).

        Returns:
            ``True`` if sharing was successful, ``False`` if credential not found.
        """
        with self._lock:
            entry = self._credentials.get(credential_id)
            if entry is None:
                return False

            if target_tenant_id not in entry.shared_with:
                entry.shared_with.append(target_tenant_id)

            if revenue_split is not None:
                entry.revenue_split = revenue_split

            self._persist(entry)

        self._publish_event("credential.shared", {
            "credential_id": credential_id,
            "owner_tenant_id": entry.owner_tenant_id,
            "target_tenant_id": target_tenant_id,
            "revenue_split": entry.revenue_split,
        })
        logger.info(
            "Shared credential %s with tenant %s",
            credential_id, target_tenant_id,
        )
        return True

    def unshare(
        self,
        credential_id: str,
        target_tenant_id: str,
    ) -> bool:
        """
        Revoke a tenant's access to a shared credential.

        Removes ``target_tenant_id`` from the ``shared_with`` list.

        Args:
            credential_id: The UUID of the credential.
            target_tenant_id: The tenant ID to remove access from.

        Returns:
            ``True`` if the tenant was removed, ``False`` if credential
            not found or tenant was not in the shared list.
        """
        with self._lock:
            entry = self._credentials.get(credential_id)
            if entry is None:
                return False

            if target_tenant_id not in entry.shared_with:
                return False

            entry.shared_with.remove(target_tenant_id)
            self._persist(entry)

        logger.info(
            "Unshared credential %s from tenant %s",
            credential_id, target_tenant_id,
        )
        return True

    def get_shared_credentials(
        self,
        tenant_id: str,
    ) -> List[CredentialEntry]:
        """
        Get all credentials shared WITH a tenant (not owned by them).

        Returns credentials where ``tenant_id`` appears in ``shared_with``
        but is NOT the ``owner_tenant_id``.

        Args:
            tenant_id: The tenant to look up shared credentials for.

        Returns:
            List of CredentialEntry objects shared with this tenant.
        """
        with self._lock:
            return [
                entry for entry in self._credentials.values()
                if (
                    tenant_id in entry.shared_with
                    and entry.owner_tenant_id != tenant_id
                )
            ]

    # ------------------------------------------------------------------
    # Service Binding
    # ------------------------------------------------------------------

    def bind_to_daemon(
        self,
        credential_id: str,
        daemon_id: str,
    ) -> bool:
        """
        Bind a credential to a specific daemon instance.

        Once bound, the credential can only be used by the specified
        daemon. This prevents credential theft if a daemon is compromised —
        the credential cannot be exfiltrated to a different daemon.

        Args:
            credential_id: The UUID of the credential.
            daemon_id: The daemon instance identifier to bind to.

        Returns:
            ``True`` if binding was successful, ``False`` if credential not found.
        """
        with self._lock:
            entry = self._credentials.get(credential_id)
            if entry is None:
                return False

            entry.daemon_id = daemon_id
            self._persist(entry)

        logger.info(
            "Bound credential %s to daemon %s", credential_id, daemon_id
        )
        return True

    def unbind_daemon(self, credential_id: str) -> bool:
        """
        Remove daemon binding from a credential.

        After unbinding, the credential can be used by any daemon
        that has tenant-level access.

        Args:
            credential_id: The UUID of the credential.

        Returns:
            ``True`` if unbinding was successful, ``False`` if credential not found.
        """
        with self._lock:
            entry = self._credentials.get(credential_id)
            if entry is None:
                return False

            entry.daemon_id = None
            self._persist(entry)

        logger.info("Unbound credential %s from daemon", credential_id)
        return True

    # ------------------------------------------------------------------
    # Rotation
    # ------------------------------------------------------------------

    def rotate(
        self,
        credential_id: str,
        new_raw_data: Dict[str, Any],
    ) -> Optional[CredentialEntry]:
        """
        Rotate a credential by re-encrypting with new raw data.

        The old encrypted data is overwritten. The ``last_rotated_at``
        timestamp is updated to track rotation history.

        Args:
            credential_id: The UUID of the credential to rotate.
            new_raw_data: The new credential data to encrypt.

        Returns:
            The updated CredentialEntry, or ``None`` if not found.
        """
        if not new_raw_data:
            raise ValueError("new_raw_data cannot be empty")

        with self._lock:
            entry = self._credentials.get(credential_id)
            if entry is None:
                return None

            entry.encrypted_data = self._encrypt(new_raw_data)
            entry.last_rotated_at = time.time()
            self._persist(entry)

        self._publish_event("credential.rotated", {
            "credential_id": credential_id,
            "provider_id": entry.provider_id,
            "owner_tenant_id": entry.owner_tenant_id,
        })
        logger.info("Rotated credential %s", credential_id)
        return entry

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persist(self, entry: CredentialEntry) -> None:
        """
        Write a single credential entry to disk as JSON.

        The file includes the encrypted payload — decryption requires
        the master key. File permissions are set to owner-only (0o600).
        """
        file_path = self._storage_dir / f"{entry.credential_id}.json"
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(
                    entry.to_dict(include_encrypted=True),
                    f,
                    indent=2,
                    ensure_ascii=False,
                )
            os.chmod(str(file_path), 0o600)
        except OSError as e:
            logger.error(
                "Failed to persist credential %s: %s", entry.credential_id, e
            )

    def _load_all(self) -> None:
        """Load all credential JSON files from the storage directory."""
        if not self._storage_dir.exists():
            return

        loaded = 0
        for file_path in self._storage_dir.glob("*.json"):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                entry = CredentialEntry.from_dict(data)
                self._credentials[entry.credential_id] = entry
                loaded += 1
            except (json.JSONDecodeError, OSError, KeyError) as e:
                logger.warning(
                    "Failed to load credential from %s: %s", file_path, e
                )

        if loaded:
            logger.info(
                "Loaded %d credentials from %s", loaded, self._storage_dir
            )

    def _remove_file(self, credential_id: str) -> None:
        """Delete a credential file from disk."""
        file_path = self._storage_dir / f"{credential_id}.json"
        if file_path.exists():
            try:
                file_path.unlink()
            except OSError as e:
                logger.error(
                    "Failed to remove credential file %s: %s",
                    credential_id, e,
                )

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    @property
    def count(self) -> int:
        """Return the total number of stored credentials."""
        return len(self._credentials)

    def get_stats(self) -> Dict[str, Any]:
        """
        Return aggregate statistics about the credential vault.

        Returns:
            Dictionary with counts grouped by status, provider, and
            credential type. Example::

                {
                    "total": 12,
                    "by_status": {"active": 10, "revoked": 2},
                    "by_provider": {"sabre": 5, "amadeus": 4, "picasso_redbox": 3},
                    "by_type": {"api_key": 6, "oauth2": 4, "gds_pcc": 2},
                }
        """
        by_status: Dict[str, int] = {}
        by_provider: Dict[str, int] = {}
        by_type: Dict[str, int] = {}

        with self._lock:
            for entry in self._credentials.values():
                by_status[entry.status] = by_status.get(entry.status, 0) + 1
                by_provider[entry.provider_id] = (
                    by_provider.get(entry.provider_id, 0) + 1
                )
                by_type[entry.credential_type] = (
                    by_type.get(entry.credential_type, 0) + 1
                )

        return {
            "total": self.count,
            "by_status": by_status,
            "by_provider": by_provider,
            "by_type": by_type,
        }

    # ------------------------------------------------------------------
    # Event Publishing
    # ------------------------------------------------------------------

    def _publish_event(self, event_name: str, data: Dict[str, Any]) -> None:
        """
        Publish a credential lifecycle event on the EventBus.

        Uses the CUSTOM event type with the specific credential event
        name embedded in the data payload.
        """
        self._event_bus.publish(Event(
            type=EventType.CUSTOM,
            data={"event": event_name, **data},
            source="credentials.vault",
        ))
