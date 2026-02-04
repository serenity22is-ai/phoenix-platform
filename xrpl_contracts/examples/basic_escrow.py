#!/usr/bin/env python3
"""
Basic Escrow Example

Demonstrates creating, confirming, and releasing an escrow payment
using the XRPL Contracts library.

Usage:
    python examples/basic_escrow.py
"""

import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from xrpl_contracts import XRPLEscrow, EscrowCondition
from xrpl_contracts.client import XRPLClient


def main():
    print("=" * 60)
    print("XRPL Escrow Example")
    print("=" * 60)

    # Initialize on testnet
    print("\n1. Initializing escrow manager on testnet...")
    escrow = XRPLEscrow(network="testnet")

    # Check connection
    if escrow.client.is_connected():
        print("   Connected to XRPL testnet!")
    else:
        print("   Warning: Could not connect to XRPL testnet")

    # Generate a crypto-condition
    print("\n2. Generating crypto-condition...")
    condition = EscrowCondition.generate()
    print(f"   Condition (public):     {condition.condition[:40]}...")
    print(f"   Fulfillment (secret):   {condition.fulfillment[:40]}...")

    # Create escrow payment
    print("\n3. Creating escrow payment...")
    result = escrow.create(
        sender="rCustomerTestAddress123",      # Customer's address
        destination="rMerchantTestAddress456", # Merchant's address
        amount_xrp=50.0,
        condition=condition,
        cancel_after_hours=24,
        memo="Test escrow payment",
    )

    if result.get("success"):
        print(f"   Escrow ID:      {result['escrow_id']}")
        print(f"   Amount:         {result['amount_xrp']} XRP")
        print(f"   Destination:    {result['destination']}")
        print(f"   Cancel after:   {result['cancel_after']}")

        print("\n4. Transaction for customer to sign:")
        tx = result.get("transaction", {})
        print(f"   TransactionType: {tx.get('TransactionType')}")
        print(f"   Account:         {tx.get('Account')}")
        print(f"   Destination:     {tx.get('Destination')}")
        print(f"   Amount:          {tx.get('Amount')} drops")

        print("\n5. Next steps:")
        print("   a) Customer signs the transaction with their XRP wallet")
        print("   b) Customer submits the signed transaction to XRPL")
        print("   c) Customer provides tx_hash and sequence to merchant")
        print("   d) Merchant confirms escrow exists on-chain")
        print("   e) Merchant delivers goods/services")
        print("   f) Merchant releases escrow with fulfillment")

        print("\n6. Escrow status:")
        status = escrow.get_status(result["escrow_id"])
        if status.get("success"):
            print(f"   Status: {status['escrow']['status']}")
            print(f"   Owner:  {status['escrow']['owner']}")

    else:
        print(f"   Error: {result.get('error')}")

    print("\n" + "=" * 60)
    print("Example complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
