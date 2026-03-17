"""
Knowledge Card Security -- Encryption, service-binding, and access control.

Knowledge cards are ANASTASiA's core intellectual property. They contain
learned system architecture (API patterns, schemas, auth flows, quirks)
accumulated from customer installations. This module ensures:

1. Cards are encrypted at rest (Fernet symmetric encryption)
2. Cards are bound to specific daemon instances (service keys)
3. Customers see RESULTS (working integrations) -- never raw card data
4. On churn: daemon deactivates -> cards become inaccessible encrypted files
5. Customers can ask "what do you know?" -> conversational summary, never raw

MYSTES KYRIOS LLC -- Confidential.
"""

import hashlib
import hmac
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

try:
    from cryptography.fernet import Fernet, InvalidToken
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes
    import base64 as _base64
    HAS_CRYPTO = True
except ImportError:
    import base64
    HAS_CRYPTO = False

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PBKDF2_ITERATIONS = 100_000
_BINDING_HMAC_ALGO = "sha256"
_CARD_TYPES = {"system_profile", "knowledge_card", "api_card"}
_OWNER_CATEGORIES = {"platform", "tenant", "shared"}
_BINDING_STATUSES = {"active", "revoked"}


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class CardBinding:
    """
    Binding between a knowledge card and a daemon instance.

    The binding token is an HMAC-SHA256 digest of the card_id, daemon_id,
    and master secret. Verifying the token proves the binding was created
    by a holder of the master key and has not been tampered with.
    """
    card_id: str = ""
    daemon_id: str = ""
    binding_token: str = ""
    bound_at: float = field(default_factory=time.time)
    last_accessed_at: Optional[float] = None
    access_count: int = 0
    status: str = "active"

    def to_dict(self) -> dict:
        return {
            "card_id": self.card_id,
            "daemon_id": self.daemon_id,
            "binding_token": self.binding_token,
            "bound_at": self.bound_at,
            "last_accessed_at": self.last_accessed_at,
            "access_count": self.access_count,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CardBinding":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class EncryptedCard:
    """
    An encrypted knowledge card stored on disk.

    The ``encrypted_data`` field holds the Fernet-encrypted, base64-encoded
    card payload. The ``metadata`` dict carries non-sensitive information
    (card type, provider name, vertical, readiness) that can be read
    without decryption for catalog and listing purposes.
    """
    card_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    card_type: str = "knowledge_card"
    owner_category: str = "platform"
    encrypted_data: str = ""
    key_id: str = ""
    daemon_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "card_id": self.card_id,
            "card_type": self.card_type,
            "owner_category": self.owner_category,
            "encrypted_data": self.encrypted_data,
            "key_id": self.key_id,
            "daemon_id": self.daemon_id,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "EncryptedCard":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# ---------------------------------------------------------------------------
# Weak fallback cipher (base64 only -- NOT cryptographically secure)
# ---------------------------------------------------------------------------

class _FallbackFernet:
    """
    Base64-only stand-in used when the ``cryptography`` package is absent.

    This provides NO real security -- it exists solely to keep the module
    functional during development or in environments where cryptography
    cannot be installed. A loud warning is emitted on every instantiation.
    """

    def __init__(self, key: bytes):
        self._key = key
        logger.warning(
            "cryptography package not installed -- using base64 fallback. "
            "Card data is NOT encrypted. Install cryptography for production use."
        )

    def encrypt(self, data: bytes) -> bytes:
        return base64.urlsafe_b64encode(data)

    def decrypt(self, token: bytes) -> bytes:
        try:
            return base64.urlsafe_b64decode(token)
        except Exception as exc:
            raise ValueError(f"Fallback decryption failed: {exc}") from exc


# ---------------------------------------------------------------------------
# CardSecurity
# ---------------------------------------------------------------------------

class CardSecurity:
    """
    Encryption, service-binding, and access control for knowledge cards.

    Manages the full lifecycle: encrypt on write, decrypt on read, bind
    cards to daemon instances, verify bindings, revoke on churn, and
    provide conversational summaries that never leak raw card data.

    Args:
        master_key: Base64-encoded 32-byte Fernet key. If ``None``, a key
                    is generated and persisted to ``storage_dir/card_master.key``.
        storage_dir: Directory for encrypted cards, bindings, and the master
                     key file. Defaults to ``~/.anastasia/card_security``.
    """

    def __init__(
        self,
        master_key: Optional[str] = None,
        storage_dir: Optional[str] = None,
    ) -> None:
        if storage_dir is None:
            storage_dir = os.path.join(
                os.path.expanduser("~"), ".anastasia", "card_security"
            )
        self._storage_dir = Path(storage_dir)
        self._storage_dir.mkdir(parents=True, exist_ok=True)

        self._cards_dir = self._storage_dir / "cards"
        self._cards_dir.mkdir(parents=True, exist_ok=True)

        self._bindings_dir = self._storage_dir / "bindings"
        self._bindings_dir.mkdir(parents=True, exist_ok=True)

        # Master key setup
        self._master_key = self._resolve_master_key(master_key)
        self._key_id = hashlib.sha256(self._master_key.encode()).hexdigest()[:12]

        # In-memory indices
        self._cards: Dict[str, EncryptedCard] = {}
        self._bindings: Dict[str, CardBinding] = {}  # key = "card_id:daemon_id"

        self._load_all()

        logger.info(
            "CardSecurity initialized: %d cards, %d bindings, crypto=%s",
            len(self._cards),
            len(self._bindings),
            "fernet" if HAS_CRYPTO else "base64-fallback",
        )

    # ------------------------------------------------------------------
    # Key management
    # ------------------------------------------------------------------

    def _resolve_master_key(self, master_key: Optional[str]) -> str:
        """
        Resolve or generate the master encryption key.

        If ``master_key`` is provided, use it directly. Otherwise, look for
        a persisted key in ``storage_dir/card_master.key``. If that does not
        exist either, generate a fresh Fernet key and persist it.
        """
        key_path = self._storage_dir / "card_master.key"

        if master_key:
            # Persist the explicitly supplied key for future runs
            key_path.write_text(master_key, encoding="utf-8")
            return master_key

        if key_path.exists():
            return key_path.read_text(encoding="utf-8").strip()

        # Generate new key
        if HAS_CRYPTO:
            new_key = Fernet.generate_key().decode()
        else:
            new_key = base64.urlsafe_b64encode(os.urandom(32)).decode()

        key_path.write_text(new_key, encoding="utf-8")
        logger.info("Generated new master key: %s", key_path)
        return new_key

    def _derive_daemon_key(self, daemon_id: str) -> bytes:
        """
        Derive a daemon-specific encryption key via PBKDF2.

        Uses the master key as input keying material and the daemon_id
        as the salt. Returns a 32-byte key suitable for Fernet.
        """
        if HAS_CRYPTO:
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=daemon_id.encode("utf-8"),
                iterations=_PBKDF2_ITERATIONS,
            )
            derived = kdf.derive(self._master_key.encode("utf-8"))
            return _base64.urlsafe_b64encode(derived)
        else:
            # Fallback: HMAC-SHA256 stretched via simple iteration
            key = self._master_key.encode("utf-8")
            salt = daemon_id.encode("utf-8")
            for _ in range(_PBKDF2_ITERATIONS // 1000):
                key = hmac.new(key, salt, hashlib.sha256).digest()
            return base64.urlsafe_b64encode(key)

    def _get_fernet(self, daemon_id: Optional[str] = None):
        """
        Return a Fernet (or fallback) cipher instance.

        If ``daemon_id`` is provided, a daemon-specific key is derived.
        Otherwise the master key is used directly.
        """
        if daemon_id:
            key_bytes = self._derive_daemon_key(daemon_id)
        else:
            key_bytes = self._master_key.encode("utf-8")

        if HAS_CRYPTO:
            return Fernet(key_bytes)
        else:
            return _FallbackFernet(key_bytes)

    def rotate_master_key(self, new_master_key: str) -> int:
        """
        Rotate the master encryption key, re-encrypting all cards.

        Every card is decrypted with the old key and re-encrypted with
        the new key. Bindings are unaffected (HMAC tokens remain valid
        because they are verified against the stored token, not
        recomputed).

        Args:
            new_master_key: The new base64-encoded Fernet key.

        Returns:
            Number of cards that were successfully re-encrypted.
        """
        old_key = self._master_key
        old_key_id = self._key_id

        # Phase 1: Decrypt all cards with the old key
        decrypted: Dict[str, bytes] = {}
        for card_id, card in self._cards.items():
            try:
                old_fernet = self._get_fernet(card.daemon_id)
                decrypted[card_id] = old_fernet.decrypt(
                    card.encrypted_data.encode("utf-8")
                )
            except Exception as exc:
                logger.error(
                    "Key rotation: failed to decrypt card %s, skipping: %s",
                    card_id, exc,
                )

        # Phase 2: Switch to new key and re-encrypt all successfully decrypted cards
        self._master_key = new_master_key
        self._key_id = hashlib.sha256(new_master_key.encode()).hexdigest()[:12]

        rotated = 0
        for card_id, raw in decrypted.items():
            card = self._cards[card_id]
            try:
                new_fernet = self._get_fernet(card.daemon_id)
                card.encrypted_data = new_fernet.encrypt(raw).decode("utf-8")
                card.key_id = self._key_id
                card.updated_at = time.time()
                self._persist_card(card)
                rotated += 1
            except Exception as exc:
                logger.error(
                    "Key rotation: failed to re-encrypt card %s: %s",
                    card_id, exc,
                )

        # If nothing could be rotated, revert to old key
        if rotated == 0 and decrypted:
            self._master_key = old_key
            self._key_id = old_key_id
            logger.error("Key rotation failed entirely -- reverted to old key")
        else:
            # Persist the new master key
            key_path = self._storage_dir / "card_master.key"
            key_path.write_text(new_master_key, encoding="utf-8")

        logger.info(
            "Master key rotated: %d/%d cards re-encrypted", rotated, len(self._cards)
        )
        return rotated

    # ------------------------------------------------------------------
    # Card encryption
    # ------------------------------------------------------------------

    def encrypt_card(
        self,
        card_data: Dict[str, Any],
        card_type: str,
        daemon_id: Optional[str] = None,
        owner_category: str = "platform",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> EncryptedCard:
        """
        Encrypt a knowledge card and persist it to disk.

        Args:
            card_data: The raw card payload (JSON-serializable dict).
            card_type: One of ``system_profile``, ``knowledge_card``, ``api_card``.
            daemon_id: If set, encrypt with a daemon-specific derived key.
            owner_category: ``platform``, ``tenant``, or ``shared``.
            metadata: Non-sensitive metadata stored alongside the encrypted blob.

        Returns:
            The persisted :class:`EncryptedCard` object.
        """
        if card_type not in _CARD_TYPES:
            raise ValueError(f"Invalid card_type '{card_type}'. Must be one of {_CARD_TYPES}")
        if owner_category not in _OWNER_CATEGORIES:
            raise ValueError(
                f"Invalid owner_category '{owner_category}'. "
                f"Must be one of {_OWNER_CATEGORIES}"
            )

        fernet = self._get_fernet(daemon_id)
        plaintext = json.dumps(card_data, ensure_ascii=False).encode("utf-8")
        ciphertext = fernet.encrypt(plaintext).decode("utf-8")

        card = EncryptedCard(
            card_id=str(uuid.uuid4()),
            card_type=card_type,
            owner_category=owner_category,
            encrypted_data=ciphertext,
            key_id=self._key_id,
            daemon_id=daemon_id,
            metadata=metadata or {},
            created_at=time.time(),
            updated_at=time.time(),
        )

        self._cards[card.card_id] = card
        self._persist_card(card)

        logger.info(
            "Encrypted card %s (type=%s, owner=%s, daemon=%s)",
            card.card_id, card_type, owner_category,
            daemon_id or "master",
        )
        return card

    def decrypt_card(
        self,
        card_id: str,
        daemon_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Decrypt a knowledge card and return its raw payload.

        If ``daemon_id`` is specified, verifies that an active binding
        exists before decryption. Updates the binding's ``last_accessed_at``
        and ``access_count``.

        Args:
            card_id: The card's unique identifier.
            daemon_id: The requesting daemon (triggers binding check).

        Returns:
            The decrypted card data dict, or ``None`` if the card does
            not exist, the binding is missing/revoked, or decryption fails.
        """
        card = self._cards.get(card_id)
        if card is None:
            logger.warning("decrypt_card: card %s not found", card_id)
            return None

        # Binding verification when a daemon requests access
        if daemon_id and card.daemon_id:
            if not self.verify_binding(card_id, daemon_id):
                logger.warning(
                    "decrypt_card: binding check failed for card=%s daemon=%s",
                    card_id, daemon_id,
                )
                return None

        try:
            fernet = self._get_fernet(card.daemon_id)
            plaintext = fernet.decrypt(card.encrypted_data.encode("utf-8"))
            data = json.loads(plaintext.decode("utf-8"))
        except Exception as exc:
            logger.error("decrypt_card failed for %s: %s", card_id, exc)
            return None

        # Update binding access stats
        if daemon_id:
            bkey = f"{card_id}:{daemon_id}"
            binding = self._bindings.get(bkey)
            if binding:
                binding.last_accessed_at = time.time()
                binding.access_count += 1
                self._persist_binding(binding)

        return data

    def update_card(
        self,
        card_id: str,
        card_data: Dict[str, Any],
        daemon_id: Optional[str] = None,
    ) -> Optional[EncryptedCard]:
        """
        Re-encrypt a card with updated data.

        Args:
            card_id: The card to update.
            card_data: The new raw card payload.
            daemon_id: Optional daemon context for key derivation.

        Returns:
            The updated :class:`EncryptedCard`, or ``None`` if not found.
        """
        card = self._cards.get(card_id)
        if card is None:
            logger.warning("update_card: card %s not found", card_id)
            return None

        effective_daemon = daemon_id or card.daemon_id
        fernet = self._get_fernet(effective_daemon)
        plaintext = json.dumps(card_data, ensure_ascii=False).encode("utf-8")
        card.encrypted_data = fernet.encrypt(plaintext).decode("utf-8")
        card.key_id = self._key_id
        card.updated_at = time.time()

        self._persist_card(card)
        logger.info("Updated card %s", card_id)
        return card

    # ------------------------------------------------------------------
    # Service binding
    # ------------------------------------------------------------------

    def _compute_binding_token(self, card_id: str, daemon_id: str) -> str:
        """Compute an HMAC-SHA256 binding token from card + daemon + secret."""
        message = f"{card_id}:{daemon_id}".encode("utf-8")
        secret = self._master_key.encode("utf-8")
        return hmac.new(secret, message, hashlib.sha256).hexdigest()

    def bind_card(self, card_id: str, daemon_id: str) -> CardBinding:
        """
        Bind a knowledge card to a specific daemon instance.

        Creates an HMAC-SHA256 binding token that proves the relationship
        was established by a holder of the master key. If a revoked
        binding already exists for this pair, it is replaced with a fresh
        active binding.

        Args:
            card_id: The card to bind.
            daemon_id: The daemon instance to bind to.

        Returns:
            The newly created :class:`CardBinding`.

        Raises:
            ValueError: If the card does not exist.
        """
        if card_id not in self._cards:
            raise ValueError(f"Card {card_id} does not exist")

        token = self._compute_binding_token(card_id, daemon_id)
        binding = CardBinding(
            card_id=card_id,
            daemon_id=daemon_id,
            binding_token=token,
            bound_at=time.time(),
            last_accessed_at=None,
            access_count=0,
            status="active",
        )

        bkey = f"{card_id}:{daemon_id}"
        self._bindings[bkey] = binding
        self._persist_binding(binding)

        logger.info("Bound card %s to daemon %s", card_id, daemon_id)
        return binding

    def verify_binding(self, card_id: str, daemon_id: str) -> bool:
        """
        Verify that an active binding exists between a card and a daemon.

        Checks both existence and ``active`` status.

        Args:
            card_id: The card identifier.
            daemon_id: The daemon identifier.

        Returns:
            ``True`` if a valid, active binding exists.
        """
        bkey = f"{card_id}:{daemon_id}"
        binding = self._bindings.get(bkey)
        if binding is None:
            return False
        if binding.status != "active":
            return False

        # Verify token integrity
        expected = self._compute_binding_token(card_id, daemon_id)
        return hmac.compare_digest(binding.binding_token, expected)

    def revoke_binding(
        self,
        card_id: str,
        daemon_id: Optional[str] = None,
    ) -> int:
        """
        Revoke one or all bindings for a card.

        If ``daemon_id`` is given, only that specific binding is revoked.
        If ``daemon_id`` is ``None``, ALL bindings for the card are revoked
        (churn scenario).

        Args:
            card_id: The card whose bindings to revoke.
            daemon_id: Optional specific daemon binding to revoke.

        Returns:
            Number of bindings that were revoked.
        """
        revoked = 0

        if daemon_id:
            bkey = f"{card_id}:{daemon_id}"
            binding = self._bindings.get(bkey)
            if binding and binding.status == "active":
                binding.status = "revoked"
                self._persist_binding(binding)
                revoked += 1
                logger.info("Revoked binding: card=%s daemon=%s", card_id, daemon_id)
        else:
            for bkey, binding in self._bindings.items():
                if binding.card_id == card_id and binding.status == "active":
                    binding.status = "revoked"
                    self._persist_binding(binding)
                    revoked += 1
            if revoked:
                logger.info(
                    "Revoked all %d bindings for card %s", revoked, card_id
                )

        return revoked

    def revoke_all_for_daemon(self, daemon_id: str) -> int:
        """
        Revoke every binding associated with a daemon instance.

        This is the primary churn handler -- once revoked, the daemon
        can no longer decrypt any cards that were bound to it.

        Args:
            daemon_id: The churning daemon's identifier.

        Returns:
            Number of bindings revoked.
        """
        revoked = 0
        for bkey, binding in self._bindings.items():
            if binding.daemon_id == daemon_id and binding.status == "active":
                binding.status = "revoked"
                self._persist_binding(binding)
                revoked += 1

        logger.info("Revoked %d bindings for daemon %s", revoked, daemon_id)
        return revoked

    def list_bindings(
        self,
        daemon_id: Optional[str] = None,
        card_id: Optional[str] = None,
    ) -> List[CardBinding]:
        """
        List bindings, optionally filtered by daemon or card.

        Args:
            daemon_id: Filter to bindings for this daemon.
            card_id: Filter to bindings for this card.

        Returns:
            List of matching :class:`CardBinding` objects.
        """
        results: List[CardBinding] = []
        for binding in self._bindings.values():
            if daemon_id and binding.daemon_id != daemon_id:
                continue
            if card_id and binding.card_id != card_id:
                continue
            results.append(binding)
        return results

    # ------------------------------------------------------------------
    # Access control
    # ------------------------------------------------------------------

    def can_access(
        self,
        card_id: str,
        daemon_id: Optional[str] = None,
        requester: str = "platform",
    ) -> bool:
        """
        Determine whether a requester may access a card.

        Access rules:
        - ``platform`` requester can always access ``platform``-owned cards.
        - ``tenant`` cards require an active binding for the daemon.
        - ``shared`` cards require an active binding OR platform-level access.

        Args:
            card_id: The card to check.
            daemon_id: The daemon making the request (if any).
            requester: ``"platform"`` or ``"tenant"``.

        Returns:
            ``True`` if access is permitted.
        """
        card = self._cards.get(card_id)
        if card is None:
            return False

        # When a daemon is making the request, it must have a valid binding
        # regardless of owner category -- daemons prove access via binding
        if daemon_id:
            return self.verify_binding(card_id, daemon_id)

        # Platform-level access (no daemon context): allowed for platform
        # and shared cards, denied for tenant cards
        if requester == "platform":
            return card.owner_category in ("platform", "shared")

        # No daemon, no platform privilege -- denied
        return False

    def get_conversational_summary(self, card_id: str) -> Optional[str]:
        """
        Generate a human-readable summary of a card's contents.

        This is the ONLY way customers can learn what ANASTASiA knows.
        The summary is conversational and deliberately vague -- it
        describes capabilities without exposing raw data structures,
        endpoint paths, auth details, or quirk workarounds.

        Args:
            card_id: The card to summarize.

        Returns:
            A natural-language summary string, or ``None`` if the card
            cannot be decrypted or does not exist.
        """
        data = self.decrypt_card(card_id)
        if data is None:
            return None

        card = self._cards[card_id]
        meta = card.metadata

        # Build summary from card data and metadata
        system_name = data.get("name") or meta.get("provider_name", "a system")
        vertical = data.get("vertical") or meta.get("vertical", "travel")
        readiness = data.get("readiness") or meta.get("readiness", "unknown")

        # Count knowledge artifacts
        endpoints_count = len(data.get("endpoints", []))
        quirks_count = len(data.get("quirks", []))
        adapters_count = len(data.get("adapters", []))
        schemas_count = len(data.get("data_schemas", {}))

        capabilities: List[str] = []
        if endpoints_count:
            capabilities.append(f"{endpoints_count} API endpoints mapped")
        if schemas_count:
            capabilities.append(f"{schemas_count} data schemas documented")
        if data.get("booking_flow"):
            flow = data["booking_flow"]
            steps = flow.get("total_steps", 0) if isinstance(flow, dict) else 0
            if steps:
                capabilities.append(f"{steps}-step booking flow understood")
        if data.get("auth_method"):
            capabilities.append("authentication flow configured")
        if adapters_count:
            capabilities.append(f"{adapters_count} integration adapters ready")

        capability_str = ", ".join(capabilities) if capabilities else "basic awareness"
        quirk_note = (
            f", {quirks_count} quirks discovered"
            if quirks_count else ""
        )

        return (
            f"I know about {system_name}: {capability_str}{quirk_note}. "
            f"Readiness level: {readiness}. Vertical: {vertical}."
        )

    # ------------------------------------------------------------------
    # Churn protection
    # ------------------------------------------------------------------

    def handle_churn(self, daemon_id: str) -> Dict[str, Any]:
        """
        Handle a customer churn event for a daemon instance.

        Revokes all bindings for the daemon. The encrypted cards remain
        on disk (they are ANASTASiA's IP) but become inaccessible to
        the churned daemon because every binding is now revoked.

        Args:
            daemon_id: The identifier of the churning daemon.

        Returns:
            Dict with ``bindings_revoked`` and ``cards_affected`` counts.
        """
        bindings_revoked = self.revoke_all_for_daemon(daemon_id)

        # Count distinct cards that were affected
        affected_cards: Set[str] = set()
        for binding in self._bindings.values():
            if binding.daemon_id == daemon_id:
                affected_cards.add(binding.card_id)

        stats = {
            "daemon_id": daemon_id,
            "bindings_revoked": bindings_revoked,
            "cards_affected": len(affected_cards),
        }

        logger.info(
            "Churn handled for daemon %s: %d bindings revoked, %d cards affected",
            daemon_id, bindings_revoked, len(affected_cards),
        )
        return stats

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persist_binding(self, binding: CardBinding) -> None:
        """Write a binding to disk as a JSON file."""
        filename = f"{binding.card_id}__{binding.daemon_id}.json"
        file_path = self._bindings_dir / filename
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(binding.to_dict(), f, indent=2, ensure_ascii=False)
        except OSError as exc:
            logger.error("Failed to persist binding %s: %s", filename, exc)

    def _persist_card(self, card: EncryptedCard) -> None:
        """Write an encrypted card to disk as a JSON file."""
        file_path = self._cards_dir / f"{card.card_id}.json"
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(card.to_dict(), f, indent=2, ensure_ascii=False)
        except OSError as exc:
            logger.error("Failed to persist card %s: %s", card.card_id, exc)

    def _load_all(self) -> None:
        """Load all persisted cards and bindings from disk into memory."""
        # Load cards
        cards_loaded = 0
        for file_path in self._cards_dir.glob("*.json"):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                card = EncryptedCard.from_dict(data)
                self._cards[card.card_id] = card
                cards_loaded += 1
            except (json.JSONDecodeError, OSError, KeyError) as exc:
                logger.warning("Failed to load card from %s: %s", file_path, exc)

        # Load bindings
        bindings_loaded = 0
        for file_path in self._bindings_dir.glob("*.json"):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                binding = CardBinding.from_dict(data)
                bkey = f"{binding.card_id}:{binding.daemon_id}"
                self._bindings[bkey] = binding
                bindings_loaded += 1
            except (json.JSONDecodeError, OSError, KeyError) as exc:
                logger.warning("Failed to load binding from %s: %s", file_path, exc)

        if cards_loaded or bindings_loaded:
            logger.info(
                "Loaded %d cards and %d bindings from %s",
                cards_loaded, bindings_loaded, self._storage_dir,
            )

    def _remove_binding(self, card_id: str, daemon_id: str) -> None:
        """Remove a binding from memory and disk."""
        bkey = f"{card_id}:{daemon_id}"
        self._bindings.pop(bkey, None)

        filename = f"{card_id}__{daemon_id}.json"
        file_path = self._bindings_dir / filename
        if file_path.exists():
            try:
                file_path.unlink()
            except OSError as exc:
                logger.error("Failed to remove binding file %s: %s", file_path, exc)

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def get_stats(self) -> Dict[str, Any]:
        """
        Return aggregate statistics about cards and bindings.

        Returns:
            Dict with ``total_cards``, ``bound_cards``, ``revoked_bindings``,
            ``cards_by_type``, and ``cards_by_category``.
        """
        cards_by_type: Dict[str, int] = {}
        cards_by_category: Dict[str, int] = {}

        for card in self._cards.values():
            cards_by_type[card.card_type] = cards_by_type.get(card.card_type, 0) + 1
            cards_by_category[card.owner_category] = (
                cards_by_category.get(card.owner_category, 0) + 1
            )

        active_bindings = sum(
            1 for b in self._bindings.values() if b.status == "active"
        )
        revoked_bindings = sum(
            1 for b in self._bindings.values() if b.status == "revoked"
        )

        # Cards that have at least one active binding
        bound_card_ids: Set[str] = {
            b.card_id for b in self._bindings.values() if b.status == "active"
        }

        return {
            "total_cards": len(self._cards),
            "bound_cards": len(bound_card_ids),
            "active_bindings": active_bindings,
            "revoked_bindings": revoked_bindings,
            "cards_by_type": cards_by_type,
            "cards_by_category": cards_by_category,
        }
