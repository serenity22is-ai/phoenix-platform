"""
XRPL Escrow Smart Contract

Implements trustless conditional payments using XRPL's native Escrow feature.

Features:
- Crypto-condition based release (PREIMAGE-SHA-256)
- Time-based cancellation for refunds
- Multi-party escrow support
- Event callbacks for integration

Use Cases:
- E-commerce escrow (pay on delivery)
- Service payments (pay on completion)
- Crowdfunding (release when goal met)
- Atomic swaps

Example:
    from xrpl_contracts import XRPLEscrow

    escrow = XRPLEscrow(network="mainnet")
    escrow.set_wallet(seed="sXXX...")

    # Create escrow
    result = escrow.create(
        sender="rCustomer...",
        destination="rMerchant...",
        amount_xrp=100,
        timeout_hours=24,
    )

    # Customer signs and submits the transaction
    # ...

    # After service delivered, release escrow
    release = escrow.finish(
        owner="rCustomer...",
        sequence=result["sequence"],
        fulfillment=result["fulfillment"],
    )
"""

import os
import hashlib
import secrets
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, Callable, List
from dataclasses import dataclass, field
from enum import Enum

from xrpl.models.transactions import EscrowCreate, EscrowFinish, EscrowCancel
from xrpl.models.requests import AccountObjects
from xrpl.transaction import submit_and_wait, autofill_and_sign
from xrpl.utils import xrp_to_drops, drops_to_xrp

from .client import XRPLClient, RIPPLE_EPOCH

logger = logging.getLogger(__name__)


class EscrowStatus(Enum):
    """Escrow payment status."""
    CREATED = "created"           # Escrow created, funds locked
    PENDING = "pending"           # Waiting for condition
    RELEASED = "released"         # Funds released to destination
    CANCELLED = "cancelled"       # Funds returned to owner
    EXPIRED = "expired"           # Past cancel time, awaiting cancel tx


@dataclass
class EscrowCondition:
    """
    Crypto-condition for escrow release.

    Uses PREIMAGE-SHA-256 (type 0) condition.
    The fulfillment (preimage) must be provided to release funds.
    """
    condition: str      # Hex-encoded condition (public)
    fulfillment: str    # Hex-encoded fulfillment (secret)
    preimage: bytes     # Raw preimage bytes

    @classmethod
    def generate(cls, preimage: Optional[bytes] = None) -> 'EscrowCondition':
        """
        Generate a new crypto-condition pair.

        Args:
            preimage: Optional custom preimage (32 bytes). Random if not provided.

        Returns:
            EscrowCondition with condition and fulfillment
        """
        # Generate or use provided preimage
        if preimage is None:
            preimage = secrets.token_bytes(32)
        elif len(preimage) != 32:
            raise ValueError("Preimage must be exactly 32 bytes")

        # Hash the preimage
        preimage_hash = hashlib.sha256(preimage).digest()

        # Build PREIMAGE-SHA-256 condition
        # Structure: A0 25 80 20 <32-byte-hash> 81 01 20
        condition_bytes = bytes([
            0xA0, 0x25,  # Compound-SHA-256 condition, 37 bytes total
            0x80, 0x20,  # Fingerprint: 32-byte SHA-256 hash
        ]) + preimage_hash + bytes([
            0x81, 0x01, 0x20,  # Cost: 32 bytes
        ])

        # Build fulfillment
        # Structure: A0 22 80 20 <32-byte-preimage>
        fulfillment_bytes = bytes([
            0xA0, 0x22,  # Compound-SHA-256 fulfillment, 34 bytes
            0x80, 0x20,  # Preimage: 32 bytes
        ]) + preimage

        return cls(
            condition=condition_bytes.hex().upper(),
            fulfillment=fulfillment_bytes.hex().upper(),
            preimage=preimage,
        )

    @classmethod
    def from_secret(cls, secret: str) -> 'EscrowCondition':
        """
        Generate condition from a secret string.

        The secret is hashed to create a deterministic 32-byte preimage.
        Useful for creating conditions from passwords or known values.

        Args:
            secret: Secret string to derive preimage from

        Returns:
            EscrowCondition
        """
        preimage = hashlib.sha256(secret.encode()).digest()
        return cls.generate(preimage=preimage)

    def verify(self, fulfillment: str) -> bool:
        """Verify a fulfillment matches this condition."""
        return fulfillment.upper() == self.fulfillment.upper()


@dataclass
class EscrowTransaction:
    """
    Represents an escrow transaction record.
    """
    escrow_id: str
    owner: str                          # Account that created escrow
    destination: str                    # Account to receive funds
    amount_xrp: float
    amount_drops: str

    # Crypto-condition
    condition: str
    fulfillment: str                    # Keep secret until release!

    # Timing
    cancel_after: Optional[datetime]    # When escrow can be cancelled
    finish_after: Optional[datetime]    # Earliest release time

    # On-chain data
    sequence: Optional[int] = None      # EscrowCreate sequence
    create_tx_hash: Optional[str] = None
    finish_tx_hash: Optional[str] = None
    cancel_tx_hash: Optional[str] = None

    # Status
    status: EscrowStatus = EscrowStatus.PENDING

    # Metadata
    memo: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary (excludes fulfillment for security)."""
        return {
            "escrow_id": self.escrow_id,
            "owner": self.owner,
            "destination": self.destination,
            "amount_xrp": self.amount_xrp,
            "condition": self.condition,
            "sequence": self.sequence,
            "status": self.status.value,
            "cancel_after": self.cancel_after.isoformat() if self.cancel_after else None,
            "finish_after": self.finish_after.isoformat() if self.finish_after else None,
            "create_tx_hash": self.create_tx_hash,
            "finish_tx_hash": self.finish_tx_hash,
            "cancel_tx_hash": self.cancel_tx_hash,
            "created_at": self.created_at.isoformat(),
        }

    def to_dict_with_fulfillment(self) -> Dict[str, Any]:
        """Convert to dictionary including fulfillment (use carefully!)."""
        d = self.to_dict()
        d["fulfillment"] = self.fulfillment
        return d


class XRPLEscrow:
    """
    XRPL Escrow Manager for trustless conditional payments.

    This class provides a complete interface for creating, releasing,
    and cancelling escrow payments on the XRP Ledger.

    Escrow Flow:
    1. Seller/platform generates condition (keeps fulfillment secret)
    2. Buyer creates escrow with condition and cancel_after time
    3. Seller delivers goods/services
    4. Seller releases escrow with fulfillment
    5. OR: After cancel_after, buyer can cancel for refund

    Thread Safety: Not thread-safe. Use separate instances per thread.
    """

    def __init__(
        self,
        network: str = "testnet",
        client: Optional[XRPLClient] = None,
    ):
        """
        Initialize XRPL Escrow manager.

        Args:
            network: XRPL network (mainnet, testnet, devnet)
            client: Optional pre-configured XRPLClient
        """
        self._client = client or XRPLClient(network=network)
        self._escrows: Dict[str, EscrowTransaction] = {}
        self._callbacks: Dict[str, List[Callable]] = {
            "on_create": [],
            "on_release": [],
            "on_cancel": [],
        }

    @property
    def client(self) -> XRPLClient:
        """Get the underlying XRPL client."""
        return self._client

    def set_wallet(self, seed: Optional[str] = None, **kwargs) -> None:
        """Configure wallet for signing transactions."""
        self._client.set_wallet(seed=seed, **kwargs)

    # --- Event Callbacks ---

    def on_create(self, callback: Callable) -> None:
        """Register callback for escrow creation."""
        self._callbacks["on_create"].append(callback)

    def on_release(self, callback: Callable) -> None:
        """Register callback for escrow release."""
        self._callbacks["on_release"].append(callback)

    def on_cancel(self, callback: Callable) -> None:
        """Register callback for escrow cancellation."""
        self._callbacks["on_cancel"].append(callback)

    def _emit(self, event: str, data: Dict[str, Any]) -> None:
        """Emit event to registered callbacks."""
        for callback in self._callbacks.get(event, []):
            try:
                callback(data)
            except Exception as e:
                logger.error(f"Callback error for {event}: {e}")

    # --- Escrow Operations ---

    def generate_condition(self, secret: Optional[str] = None) -> EscrowCondition:
        """
        Generate a new crypto-condition.

        Args:
            secret: Optional secret to derive condition from

        Returns:
            EscrowCondition with condition and fulfillment
        """
        if secret:
            return EscrowCondition.from_secret(secret)
        return EscrowCondition.generate()

    def create(
        self,
        sender: str,
        destination: str,
        amount_xrp: float,
        condition: Optional[EscrowCondition] = None,
        cancel_after_hours: float = 24,
        finish_after_hours: Optional[float] = None,
        memo: Optional[str] = None,
        escrow_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create an escrow payment.

        This generates the EscrowCreate transaction that the sender
        must sign and submit to the XRPL.

        Args:
            sender: Address creating the escrow (funds come from here)
            destination: Address to receive funds on release
            amount_xrp: Amount to escrow in XRP
            condition: Optional pre-generated condition
            cancel_after_hours: Hours until escrow can be cancelled
            finish_after_hours: Optional minimum hours before release
            memo: Optional memo/reference
            escrow_id: Optional custom escrow ID

        Returns:
            Dict with escrow details and unsigned transaction
        """
        # Generate condition if not provided
        if condition is None:
            condition = self.generate_condition()

        # Generate escrow ID
        if escrow_id is None:
            escrow_id = f"ESC-{secrets.token_hex(8).upper()}"

        # Calculate timestamps
        now = datetime.utcnow()
        cancel_after = now + timedelta(hours=cancel_after_hours)
        cancel_after_ripple = self._client.datetime_to_ripple_time(cancel_after)

        finish_after = None
        finish_after_ripple = None
        if finish_after_hours:
            finish_after = now + timedelta(hours=finish_after_hours)
            finish_after_ripple = self._client.datetime_to_ripple_time(finish_after)

        # Amount in drops
        amount_drops = xrp_to_drops(amount_xrp)

        # Build transaction
        tx_dict = {
            "TransactionType": "EscrowCreate",
            "Account": sender,
            "Destination": destination,
            "Amount": amount_drops,
            "Condition": condition.condition,
            "CancelAfter": cancel_after_ripple,
        }

        if finish_after_ripple:
            tx_dict["FinishAfter"] = finish_after_ripple

        # Add memo if provided
        if memo:
            tx_dict["Memos"] = [{
                "Memo": {
                    "MemoType": bytes("escrow_id", "utf-8").hex().upper(),
                    "MemoData": bytes(escrow_id, "utf-8").hex().upper(),
                }
            }]

        # Create escrow record
        escrow = EscrowTransaction(
            escrow_id=escrow_id,
            owner=sender,
            destination=destination,
            amount_xrp=amount_xrp,
            amount_drops=amount_drops,
            condition=condition.condition,
            fulfillment=condition.fulfillment,
            cancel_after=cancel_after,
            finish_after=finish_after,
            memo=memo,
            status=EscrowStatus.PENDING,
        )

        # Store locally
        self._escrows[escrow_id] = escrow

        result = {
            "success": True,
            "escrow_id": escrow_id,
            "owner": sender,
            "destination": destination,
            "amount_xrp": amount_xrp,
            "amount_drops": amount_drops,
            "condition": condition.condition,
            "fulfillment": condition.fulfillment,  # KEEP SECRET!
            "cancel_after": cancel_after.isoformat(),
            "cancel_after_ripple": cancel_after_ripple,
            "finish_after": finish_after.isoformat() if finish_after else None,
            "transaction": tx_dict,
        }

        self._emit("on_create", result)
        return result

    def confirm_created(
        self,
        escrow_id: str,
        tx_hash: str,
        sequence: int,
    ) -> Dict[str, Any]:
        """
        Confirm escrow was created on-chain.

        Call this after the sender has signed and submitted the
        EscrowCreate transaction.

        Args:
            escrow_id: The escrow ID
            tx_hash: Transaction hash from submission
            sequence: Sequence number from transaction

        Returns:
            Confirmation result
        """
        escrow = self._escrows.get(escrow_id)
        if not escrow:
            return {"success": False, "error": "Escrow not found"}

        # Verify on chain
        try:
            tx = self._client.get_transaction(tx_hash)

            # Validate transaction
            if tx.get("TransactionType") != "EscrowCreate":
                return {"success": False, "error": "Not an EscrowCreate transaction"}

            if tx.get("Destination") != escrow.destination:
                return {"success": False, "error": "Destination mismatch"}

            if tx.get("Condition") != escrow.condition:
                return {"success": False, "error": "Condition mismatch"}

            # Update record
            escrow.create_tx_hash = tx_hash
            escrow.sequence = sequence
            escrow.status = EscrowStatus.CREATED
            escrow.updated_at = datetime.utcnow()

            return {
                "success": True,
                "escrow_id": escrow_id,
                "status": "created",
                "tx_hash": tx_hash,
                "sequence": sequence,
                "explorer_url": self._client.get_explorer_url(tx_hash),
            }

        except Exception as e:
            logger.error(f"Error confirming escrow: {e}")
            return {"success": False, "error": str(e)}

    def finish(
        self,
        escrow_id: str,
        owner: Optional[str] = None,
        sequence: Optional[int] = None,
        fulfillment: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Release escrow funds to destination.

        This submits an EscrowFinish transaction with the fulfillment
        to release funds. Requires wallet to be configured.

        Args:
            escrow_id: The escrow to release
            owner: Escrow owner address (optional if stored)
            sequence: Escrow sequence (optional if stored)
            fulfillment: Fulfillment hex (optional if stored)

        Returns:
            Release result with transaction hash
        """
        if not self._client.wallet:
            return {"success": False, "error": "Wallet not configured"}

        escrow = self._escrows.get(escrow_id)

        # Get values from escrow or parameters
        owner = owner or (escrow.owner if escrow else None)
        sequence = sequence or (escrow.sequence if escrow else None)
        fulfillment = fulfillment or (escrow.fulfillment if escrow else None)
        condition = escrow.condition if escrow else None

        if not all([owner, sequence, fulfillment]):
            return {"success": False, "error": "Missing owner, sequence, or fulfillment"}

        try:
            # Build EscrowFinish transaction
            tx_params = {
                "account": self._client.address,
                "owner": owner,
                "offer_sequence": sequence,
                "fulfillment": fulfillment,
            }

            if condition:
                tx_params["condition"] = condition

            finish_tx = EscrowFinish(**tx_params)

            # Sign and submit
            signed = autofill_and_sign(finish_tx, self._client.client, self._client.wallet)
            response = submit_and_wait(signed, self._client.client)
            result = response.result

            tx_result = result.get("meta", {}).get("TransactionResult")

            if tx_result == "tesSUCCESS":
                tx_hash = result.get("hash")

                if escrow:
                    escrow.finish_tx_hash = tx_hash
                    escrow.status = EscrowStatus.RELEASED
                    escrow.updated_at = datetime.utcnow()

                release_result = {
                    "success": True,
                    "escrow_id": escrow_id,
                    "status": "released",
                    "tx_hash": tx_hash,
                    "amount_xrp": escrow.amount_xrp if escrow else None,
                    "explorer_url": self._client.get_explorer_url(tx_hash),
                }

                self._emit("on_release", release_result)
                return release_result

            else:
                return {
                    "success": False,
                    "error": f"Transaction failed: {tx_result}",
                }

        except Exception as e:
            logger.error(f"Error releasing escrow: {e}")
            return {"success": False, "error": str(e)}

    def cancel(
        self,
        escrow_id: str,
        owner: Optional[str] = None,
        sequence: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Cancel escrow and return funds to owner.

        Can only be executed after cancel_after time has passed.
        Requires wallet to be configured.

        Args:
            escrow_id: The escrow to cancel
            owner: Escrow owner address
            sequence: Escrow sequence number

        Returns:
            Cancellation result
        """
        if not self._client.wallet:
            return {"success": False, "error": "Wallet not configured"}

        escrow = self._escrows.get(escrow_id)

        owner = owner or (escrow.owner if escrow else None)
        sequence = sequence or (escrow.sequence if escrow else None)

        if not owner or not sequence:
            return {"success": False, "error": "Missing owner or sequence"}

        # Check cancel time
        if escrow and escrow.cancel_after:
            if datetime.utcnow() < escrow.cancel_after:
                remaining = escrow.cancel_after - datetime.utcnow()
                return {
                    "success": False,
                    "error": f"Cannot cancel yet. {remaining} remaining.",
                    "cancel_after": escrow.cancel_after.isoformat(),
                }

        try:
            # Build EscrowCancel transaction
            cancel_tx = EscrowCancel(
                account=self._client.address,
                owner=owner,
                offer_sequence=sequence,
            )

            # Sign and submit
            signed = autofill_and_sign(cancel_tx, self._client.client, self._client.wallet)
            response = submit_and_wait(signed, self._client.client)
            result = response.result

            tx_result = result.get("meta", {}).get("TransactionResult")

            if tx_result == "tesSUCCESS":
                tx_hash = result.get("hash")

                if escrow:
                    escrow.cancel_tx_hash = tx_hash
                    escrow.status = EscrowStatus.CANCELLED
                    escrow.updated_at = datetime.utcnow()

                cancel_result = {
                    "success": True,
                    "escrow_id": escrow_id,
                    "status": "cancelled",
                    "tx_hash": tx_hash,
                    "refunded_to": owner,
                    "amount_xrp": escrow.amount_xrp if escrow else None,
                    "explorer_url": self._client.get_explorer_url(tx_hash),
                }

                self._emit("on_cancel", cancel_result)
                return cancel_result

            else:
                return {
                    "success": False,
                    "error": f"Transaction failed: {tx_result}",
                }

        except Exception as e:
            logger.error(f"Error cancelling escrow: {e}")
            return {"success": False, "error": str(e)}

    # --- Query Methods ---

    def get(self, escrow_id: str) -> Optional[EscrowTransaction]:
        """Get escrow by ID."""
        return self._escrows.get(escrow_id)

    def get_status(self, escrow_id: str) -> Dict[str, Any]:
        """Get escrow status."""
        escrow = self._escrows.get(escrow_id)
        if not escrow:
            return {"success": False, "error": "Escrow not found"}

        # Check if expired
        if escrow.status == EscrowStatus.CREATED and escrow.cancel_after:
            if datetime.utcnow() > escrow.cancel_after:
                escrow.status = EscrowStatus.EXPIRED

        return {
            "success": True,
            "escrow": escrow.to_dict(),
        }

    def list_escrows(
        self,
        status: Optional[EscrowStatus] = None,
        owner: Optional[str] = None,
        destination: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        List escrows with optional filters.

        Args:
            status: Filter by status
            owner: Filter by owner address
            destination: Filter by destination address

        Returns:
            List of escrow dicts
        """
        escrows = list(self._escrows.values())

        if status:
            escrows = [e for e in escrows if e.status == status]
        if owner:
            escrows = [e for e in escrows if e.owner == owner]
        if destination:
            escrows = [e for e in escrows if e.destination == destination]

        return [e.to_dict() for e in escrows]

    def get_account_escrows(self, address: str) -> List[Dict[str, Any]]:
        """
        Get all escrows for an account from XRPL.

        Args:
            address: XRP address to query

        Returns:
            List of on-chain escrow objects
        """
        try:
            request = AccountObjects(
                account=address,
                type="escrow",
                ledger_index="validated",
            )
            response = self._client.client.request(request)
            return response.result.get("account_objects", [])
        except Exception as e:
            logger.error(f"Error fetching account escrows: {e}")
            return []


# --- Convenience Functions ---

def create_escrow(
    sender: str,
    destination: str,
    amount_xrp: float,
    network: str = "testnet",
    timeout_hours: float = 24,
) -> Dict[str, Any]:
    """
    Quick escrow creation.

    Returns transaction for sender to sign.
    """
    escrow = XRPLEscrow(network=network)
    return escrow.create(
        sender=sender,
        destination=destination,
        amount_xrp=amount_xrp,
        cancel_after_hours=timeout_hours,
    )
