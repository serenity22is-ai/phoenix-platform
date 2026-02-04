"""
PHOENIX XRPL Escrow Integration

This module integrates the reusable xrpl_contracts escrow library
with PHOENIX's booking system.

Flow:
1. Customer creates escrow with crypto-condition
2. PHOENIX books the flight
3. On success: PHOENIX provides fulfillment to release escrow
4. On failure: Escrow auto-cancels after timeout, funds return to customer

This provides:
- Trustless payments (customer funds protected until booking confirmed)
- Automatic refunds if booking fails
- Cryptographic proof of fulfillment
- No intermediary needed

Uses the standalone xrpl_contracts library for XRPL operations.
"""

import os
import secrets
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from dataclasses import dataclass
from enum import Enum

# Import from our reusable library
from xrpl_contracts import XRPLEscrow, EscrowCondition, EscrowStatus, EscrowTransaction
from xrpl_contracts.client import XRPLClient

logger = logging.getLogger(__name__)


# Re-export for backwards compatibility
EscrowCondition = EscrowCondition
EscrowStatus = EscrowStatus


@dataclass
class EscrowPayment:
    """
    PHOENIX-specific escrow payment record.

    Extends the base escrow with booking-specific fields.
    """
    escrow_id: str              # Unique identifier
    booking_id: int             # Associated booking
    deal_id: str                # Associated deal

    # XRPL details
    sender_address: str         # Customer's XRP address
    destination_address: str    # PHOENIX's address
    amount_xrp: float           # Amount in XRP
    amount_drops: str           # Amount in drops

    # Escrow details
    sequence: Optional[int]     # Transaction sequence (set after creation)
    condition: str              # Crypto-condition hex
    fulfillment: str            # Fulfillment hex (secret until release)

    # Timing
    cancel_after: datetime      # When escrow can be cancelled (refund)
    finish_after: Optional[datetime]  # Optional: earliest release time

    # Status
    status: EscrowStatus
    create_tx_hash: Optional[str]
    finish_tx_hash: Optional[str]
    cancel_tx_hash: Optional[str]

    created_at: datetime
    updated_at: datetime

    def to_dict(self) -> Dict[str, Any]:
        return {
            "escrow_id": self.escrow_id,
            "booking_id": self.booking_id,
            "deal_id": self.deal_id,
            "sender_address": self.sender_address,
            "destination_address": self.destination_address,
            "amount_xrp": self.amount_xrp,
            "sequence": self.sequence,
            "condition": self.condition,
            "status": self.status.value if hasattr(self.status, 'value') else str(self.status),
            "cancel_after": self.cancel_after.isoformat(),
            "create_tx_hash": self.create_tx_hash,
            "finish_tx_hash": self.finish_tx_hash,
            "created_at": self.created_at.isoformat(),
        }


class XRPLEscrowManager:
    """
    PHOENIX-specific escrow manager.

    Wraps the reusable XRPLEscrow library with PHOENIX-specific
    business logic and database integration.

    Provides trustless booking payments:
    - Customer funds held in escrow until booking confirmed
    - Automatic refund if booking fails or times out
    - Cryptographic proof required to release funds
    """

    def __init__(self):
        # XRPL configuration from environment
        self.network = os.getenv("XRPL_NETWORK", "testnet")

        # Initialize the reusable escrow library
        self._escrow = XRPLEscrow(network=self.network)

        # Platform wallet configuration
        self.wallet_seed = os.getenv("XRPL_WALLET_SEED")
        self.wallet_address = os.getenv("XRPL_WALLET_ADDRESS")

        if self.wallet_seed:
            self._escrow.set_wallet(seed=self.wallet_seed)

        # Escrow settings
        self.default_timeout_hours = int(os.getenv("ESCROW_TIMEOUT_HOURS", "24"))

        # PHOENIX-specific escrow storage (maps to database in production)
        self._escrows: Dict[str, EscrowPayment] = {}

        # Register callbacks for escrow events
        self._escrow.on_release(self._on_escrow_released)
        self._escrow.on_cancel(self._on_escrow_cancelled)

    def _on_escrow_released(self, data: Dict[str, Any]) -> None:
        """Handle escrow release events."""
        escrow_id = data.get("escrow_id")
        logger.info(f"Escrow released: {escrow_id} - Amount: {data.get('amount_xrp')} XRP")

    def _on_escrow_cancelled(self, data: Dict[str, Any]) -> None:
        """Handle escrow cancellation events."""
        escrow_id = data.get("escrow_id")
        logger.info(f"Escrow cancelled: {escrow_id} - Refunded to: {data.get('refunded_to')}")

    def create_escrow_payment(
        self,
        booking_id: int,
        deal_id: str,
        amount_xrp: float,
        sender_address: str,
        timeout_hours: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Generate escrow payment details for a customer.

        This creates the crypto-condition and returns the EscrowCreate
        transaction that the customer should sign and submit.

        Args:
            booking_id: The booking this payment is for
            deal_id: The deal ID
            amount_xrp: Amount to escrow
            sender_address: Customer's XRP address
            timeout_hours: Hours before escrow can be cancelled

        Returns:
            Dict with escrow details and unsigned transaction
        """
        if not self.wallet_address:
            raise ValueError("Platform wallet not configured")

        timeout_hours = timeout_hours or self.default_timeout_hours

        # Generate PHOENIX-specific escrow ID
        escrow_id = f"ESC-{booking_id}-{secrets.token_hex(4).upper()}"

        # Use the reusable library to create the escrow
        result = self._escrow.create(
            sender=sender_address,
            destination=self.wallet_address,
            amount_xrp=amount_xrp,
            cancel_after_hours=timeout_hours,
            escrow_id=escrow_id,
            memo=f"PHOENIX booking: {deal_id}",
        )

        if result.get("success"):
            # Create PHOENIX-specific escrow record
            now = datetime.utcnow()
            cancel_after = datetime.fromisoformat(result.get("cancel_after"))

            escrow_payment = EscrowPayment(
                escrow_id=escrow_id,
                booking_id=booking_id,
                deal_id=deal_id,
                sender_address=sender_address,
                destination_address=self.wallet_address,
                amount_xrp=amount_xrp,
                amount_drops=result.get("amount_drops"),
                sequence=None,
                condition=result.get("condition"),
                fulfillment=result.get("fulfillment"),  # Keep secret!
                cancel_after=cancel_after,
                finish_after=None,
                status=EscrowStatus.PENDING,
                create_tx_hash=None,
                finish_tx_hash=None,
                cancel_tx_hash=None,
                created_at=now,
                updated_at=now,
            )

            # Store locally
            self._escrows[escrow_id] = escrow_payment

            # Return customer-facing response (no fulfillment!)
            return {
                "success": True,
                "escrow_id": escrow_id,
                "amount_xrp": amount_xrp,
                "amount_drops": result.get("amount_drops"),
                "destination": self.wallet_address,
                "condition": result.get("condition"),
                "cancel_after": result.get("cancel_after"),
                "cancel_after_ripple": result.get("cancel_after_ripple"),
                "timeout_hours": timeout_hours,
                "transaction": result.get("transaction"),
                "instructions": {
                    "step1": "Sign and submit the EscrowCreate transaction using your XRPL wallet",
                    "step2": "Save the transaction hash and sequence number",
                    "step3": "Call /api/escrow/confirm with the transaction details",
                    "step4": "PHOENIX will book your flight automatically",
                    "step5": "On success, escrow releases to PHOENIX",
                    "step6": "On failure, cancel escrow after timeout to get full refund",
                }
            }

        return result

    def confirm_escrow_created(
        self,
        escrow_id: str,
        tx_hash: str,
        sequence: int,
    ) -> Dict[str, Any]:
        """
        Confirm that customer has created the escrow on-chain.

        Args:
            escrow_id: Our escrow reference
            tx_hash: The EscrowCreate transaction hash
            sequence: The transaction sequence number

        Returns:
            Confirmation result
        """
        escrow = self._escrows.get(escrow_id)
        if not escrow:
            return {"success": False, "error": "Escrow not found"}

        # Use the reusable library to confirm on-chain
        result = self._escrow.confirm_created(
            escrow_id=escrow_id,
            tx_hash=tx_hash,
            sequence=sequence,
        )

        if result.get("success"):
            # Update local record
            escrow.create_tx_hash = tx_hash
            escrow.sequence = sequence
            escrow.updated_at = datetime.utcnow()

            logger.info(f"Escrow {escrow_id} confirmed on-chain: {tx_hash}")

            return {
                "success": True,
                "escrow_id": escrow_id,
                "status": "confirmed",
                "tx_hash": tx_hash,
                "sequence": sequence,
                "explorer_url": result.get("explorer_url"),
                "message": "Escrow created successfully. Booking will proceed.",
            }

        return result

    def release_escrow(
        self,
        escrow_id: str,
        confirmation_code: str,
    ) -> Dict[str, Any]:
        """
        Release escrow funds after successful booking.

        This submits an EscrowFinish transaction with the fulfillment
        to release the funds to PHOENIX.

        Args:
            escrow_id: The escrow to release
            confirmation_code: Airline confirmation code (for record)

        Returns:
            Release result
        """
        escrow = self._escrows.get(escrow_id)
        if not escrow:
            return {"success": False, "error": "Escrow not found"}

        if escrow.status != EscrowStatus.PENDING:
            return {"success": False, "error": f"Escrow already {escrow.status.value}"}

        if not escrow.sequence:
            return {"success": False, "error": "Escrow not yet created on-chain"}

        # Use the reusable library to release
        result = self._escrow.finish(
            escrow_id=escrow_id,
            owner=escrow.sender_address,
            sequence=escrow.sequence,
            fulfillment=escrow.fulfillment,
        )

        if result.get("success"):
            escrow.status = EscrowStatus.RELEASED
            escrow.finish_tx_hash = result.get("tx_hash")
            escrow.updated_at = datetime.utcnow()

            logger.info(f"Escrow {escrow_id} released: {escrow.finish_tx_hash}")

            return {
                "success": True,
                "escrow_id": escrow_id,
                "status": "released",
                "tx_hash": escrow.finish_tx_hash,
                "amount_xrp": escrow.amount_xrp,
                "confirmation_code": confirmation_code,
                "explorer_url": result.get("explorer_url"),
                "message": "Payment released successfully!",
            }

        return result

    def cancel_escrow(
        self,
        escrow_id: str,
        reason: str = "Booking failed",
    ) -> Dict[str, Any]:
        """
        Cancel escrow and return funds to customer.

        Can only be called after cancel_after time has passed.

        Args:
            escrow_id: The escrow to cancel
            reason: Reason for cancellation

        Returns:
            Cancellation result
        """
        escrow = self._escrows.get(escrow_id)
        if not escrow:
            return {"success": False, "error": "Escrow not found"}

        if escrow.status != EscrowStatus.PENDING:
            return {"success": False, "error": f"Escrow already {escrow.status.value}"}

        # Check if cancel time has passed
        if datetime.utcnow() < escrow.cancel_after:
            time_remaining = escrow.cancel_after - datetime.utcnow()
            return {
                "success": False,
                "error": f"Cannot cancel yet. {time_remaining} remaining.",
                "cancel_after": escrow.cancel_after.isoformat(),
            }

        if not escrow.sequence:
            return {"success": False, "error": "Escrow not yet created on-chain"}

        # Use the reusable library to cancel
        result = self._escrow.cancel(
            escrow_id=escrow_id,
            owner=escrow.sender_address,
            sequence=escrow.sequence,
        )

        if result.get("success"):
            escrow.status = EscrowStatus.CANCELLED
            escrow.cancel_tx_hash = result.get("tx_hash")
            escrow.updated_at = datetime.utcnow()

            logger.info(f"Escrow {escrow_id} cancelled: {escrow.cancel_tx_hash}")

            return {
                "success": True,
                "escrow_id": escrow_id,
                "status": "cancelled",
                "tx_hash": escrow.cancel_tx_hash,
                "amount_xrp": escrow.amount_xrp,
                "refunded_to": escrow.sender_address,
                "reason": reason,
                "explorer_url": result.get("explorer_url"),
                "message": "Escrow cancelled. Funds returned to customer.",
            }

        return result

    def get_escrow_status(self, escrow_id: str) -> Dict[str, Any]:
        """Get current status of an escrow."""
        escrow = self._escrows.get(escrow_id)
        if not escrow:
            return {"success": False, "error": "Escrow not found"}

        # Check if expired
        if escrow.status == EscrowStatus.PENDING and datetime.utcnow() > escrow.cancel_after:
            escrow.status = EscrowStatus.EXPIRED

        return {
            "success": True,
            "escrow": escrow.to_dict(),
        }

    def get_pending_escrows_for_booking(self, booking_id: int) -> list:
        """Get all pending escrows for a booking."""
        return [
            e.to_dict() for e in self._escrows.values()
            if e.booking_id == booking_id and e.status == EscrowStatus.PENDING
        ]


# --- INTEGRATION WITH BOOKING SYSTEM ---

class EscrowBookingFlow:
    """
    Integrates escrow payments with the PHOENIX booking flow.

    Flow:
    1. Customer initiates booking
    2. System creates escrow payment details
    3. Customer signs and submits EscrowCreate via wallet
    4. System confirms escrow on-chain
    5. System proceeds with automated booking
    6. On success: Release escrow with fulfillment
    7. On failure: Cancel escrow (after timeout) for full refund
    """

    def __init__(self):
        self.escrow_manager = XRPLEscrowManager()

    def initiate_escrow_payment(
        self,
        booking_id: int,
        deal_id: str,
        amount_xrp: float,
        customer_address: str,
    ) -> Dict[str, Any]:
        """
        Start the escrow payment flow.

        Returns transaction details for customer to sign.
        """
        return self.escrow_manager.create_escrow_payment(
            booking_id=booking_id,
            deal_id=deal_id,
            amount_xrp=amount_xrp,
            sender_address=customer_address,
        )

    def confirm_payment(
        self,
        escrow_id: str,
        tx_hash: str,
        sequence: int,
    ) -> Dict[str, Any]:
        """
        Confirm customer has created escrow.

        After this, proceed with booking automation.
        """
        result = self.escrow_manager.confirm_escrow_created(
            escrow_id=escrow_id,
            tx_hash=tx_hash,
            sequence=sequence,
        )

        if result.get("success"):
            # Trigger booking automation
            # This integrates with the airline_booker module
            logger.info(f"Escrow confirmed, triggering booking for {escrow_id}")

        return result

    def complete_booking(
        self,
        escrow_id: str,
        confirmation_code: str,
    ) -> Dict[str, Any]:
        """
        Complete booking and release escrow.

        Called after airline booking is successful.
        """
        return self.escrow_manager.release_escrow(
            escrow_id=escrow_id,
            confirmation_code=confirmation_code,
        )

    def fail_booking(
        self,
        escrow_id: str,
        reason: str,
    ) -> Dict[str, Any]:
        """
        Mark booking as failed.

        Escrow will be cancellable after timeout for customer refund.
        """
        escrow = self.escrow_manager._escrows.get(escrow_id)
        if escrow:
            escrow.status = EscrowStatus.EXPIRED
            return {
                "success": True,
                "message": f"Booking failed: {reason}. Customer can cancel escrow after {escrow.cancel_after.isoformat()}",
                "refund_available_at": escrow.cancel_after.isoformat(),
            }
        return {"success": False, "error": "Escrow not found"}


# --- XUMM WALLET INTEGRATION ---

def generate_xumm_payload(escrow_details: Dict[str, Any]) -> Dict[str, Any]:
    """
    Generate a XUMM wallet payload for the escrow transaction.

    XUMM is a popular XRP wallet app that can sign transactions via QR code.
    This creates a payload for easy mobile signing.
    """
    tx = escrow_details.get("transaction", {})

    return {
        "txjson": tx,
        "options": {
            "submit": True,
            "expire": 60,  # 60 minutes to sign
        },
        "custom_meta": {
            "identifier": escrow_details.get("escrow_id"),
            "instruction": "Sign to create escrow for your flight booking. Funds will be released when booking is confirmed, or refunded if booking fails."
        }
    }


def generate_crossmark_payload(escrow_details: Dict[str, Any]) -> Dict[str, Any]:
    """
    Generate a Crossmark wallet payload for browser-based signing.

    Crossmark is a browser extension wallet for XRP Ledger.
    """
    tx = escrow_details.get("transaction", {})

    return {
        "TransactionType": tx.get("TransactionType"),
        "Account": tx.get("Account"),
        "Destination": tx.get("Destination"),
        "Amount": tx.get("Amount"),
        "Condition": tx.get("Condition"),
        "CancelAfter": tx.get("CancelAfter"),
        "Memos": tx.get("Memos", []),
    }


# --- CLI FOR TESTING ---

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()

    print("PHOENIX XRPL Escrow System")
    print("=" * 50)
    print("Using xrpl_contracts library v1.0.0")
    print()

    manager = XRPLEscrowManager()

    print(f"Network: {manager.network}")
    print(f"Platform wallet: {manager.wallet_address}")
    print(f"Default timeout: {manager.default_timeout_hours} hours")

    # Test escrow creation
    print("\n--- Test Escrow Creation ---")

    test_result = manager.create_escrow_payment(
        booking_id=12345,
        deal_id="DEAL-LAX-NRT-001",
        amount_xrp=100.0,
        sender_address="rTestCustomerAddress123",
    )

    print(f"Escrow ID: {test_result.get('escrow_id')}")
    print(f"Amount: {test_result.get('amount_xrp')} XRP")
    print(f"Destination: {test_result.get('destination')}")
    print(f"Condition: {test_result.get('condition')[:40]}...")
    print(f"Cancel after: {test_result.get('cancel_after')}")

    print("\nTransaction to sign:")
    print(json.dumps(test_result.get("transaction"), indent=2))

    print("\n--- XUMM Payload ---")
    xumm_payload = generate_xumm_payload(test_result)
    print(json.dumps(xumm_payload, indent=2))
