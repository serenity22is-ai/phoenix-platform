"""
XRPL Smart Contracts Library

A reusable library for building trustless applications on the XRP Ledger.

Modules:
- escrow: Conditional escrow payments with crypto-conditions
- payment_channel: Streaming payments for subscriptions
- multisig: Multi-signature transactions
- nft: NFT minting and trading (future)

Usage:
    from xrpl_contracts import Escrow, PaymentChannel

    # Create escrow for service payment
    escrow = Escrow(network="mainnet")
    result = escrow.create(
        sender="rCustomer...",
        destination="rMerchant...",
        amount_xrp=100,
        timeout_hours=24
    )
"""

from .escrow import (
    XRPLEscrow,
    EscrowCondition,
    EscrowStatus,
    EscrowTransaction,
)

from .client import XRPLClient

__version__ = "1.0.0"
__all__ = [
    "XRPLEscrow",
    "EscrowCondition",
    "EscrowStatus",
    "EscrowTransaction",
    "XRPLClient",
]
