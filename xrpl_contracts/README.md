# XRPL Contracts Library

A reusable Python library for building trustless applications on the XRP Ledger.

## Features

- **Escrow Payments**: Conditional escrow with crypto-conditions (PREIMAGE-SHA-256)
- **Time-locked Transactions**: Cancel-after and finish-after constraints
- **Event Callbacks**: Hook into escrow lifecycle events
- **Multi-network Support**: Mainnet, testnet, and devnet

## Installation

```bash
# Install dependencies
pip install xrpl-py>=2.0.0

# Copy the xrpl_contracts folder to your project
cp -r xrpl_contracts /your/project/
```

## Quick Start

### Create an Escrow Payment

```python
from xrpl_contracts import XRPLEscrow

# Initialize escrow manager
escrow = XRPLEscrow(network="testnet")

# Configure wallet (for releasing/cancelling)
escrow.set_wallet(seed="sYourWalletSeed...")

# Create escrow payment
result = escrow.create(
    sender="rCustomerAddress...",
    destination="rMerchantAddress...",
    amount_xrp=100.0,
    cancel_after_hours=24,
)

print(f"Escrow ID: {result['escrow_id']}")
print(f"Condition: {result['condition']}")
print(f"Transaction: {result['transaction']}")

# Customer signs and submits the transaction using their wallet
# ...

# After customer submits, confirm on-chain
escrow.confirm_created(
    escrow_id=result["escrow_id"],
    tx_hash="TRANSACTION_HASH",
    sequence=12345,
)
```

### Release Escrow (After Service Delivered)

```python
# Release funds with the fulfillment
release_result = escrow.finish(
    escrow_id="ESC-ABC123",
    owner="rCustomerAddress...",
    sequence=12345,
    fulfillment=result["fulfillment"],
)

print(f"Released: {release_result['tx_hash']}")
```

### Cancel Escrow (After Timeout)

```python
# Cancel and refund (only after cancel_after time)
cancel_result = escrow.cancel(
    escrow_id="ESC-ABC123",
    owner="rCustomerAddress...",
    sequence=12345,
)

print(f"Cancelled: {cancel_result['tx_hash']}")
```

## Crypto-Conditions

The library uses PREIMAGE-SHA-256 crypto-conditions for trustless escrow:

```python
from xrpl_contracts import EscrowCondition

# Generate random condition
condition = EscrowCondition.generate()
print(f"Condition (public): {condition.condition}")
print(f"Fulfillment (secret): {condition.fulfillment}")

# Generate from secret string
condition = EscrowCondition.from_secret("my-secret-password")
```

**How it works:**
1. Merchant generates condition (public) and fulfillment (secret)
2. Customer creates escrow with the condition
3. Merchant delivers goods/services
4. Merchant releases escrow with fulfillment
5. XRP Ledger verifies fulfillment matches condition

## Event Callbacks

```python
escrow = XRPLEscrow(network="testnet")

# Register callbacks
escrow.on_create(lambda data: print(f"Created: {data['escrow_id']}"))
escrow.on_release(lambda data: print(f"Released: {data['tx_hash']}"))
escrow.on_cancel(lambda data: print(f"Cancelled: {data['refunded_to']}"))
```

## Network Configuration

```python
# Testnet (default)
escrow = XRPLEscrow(network="testnet")

# Mainnet
escrow = XRPLEscrow(network="mainnet")

# Devnet
escrow = XRPLEscrow(network="devnet")

# Custom endpoints
from xrpl_contracts.client import XRPLClient
client = XRPLClient(
    network="custom",
    json_rpc_url="https://your-node.example.com",
)
escrow = XRPLEscrow(client=client)
```

## Use Cases

### E-commerce Escrow
```python
# Buyer funds escrow, seller ships item
# On delivery confirmation, escrow releases to seller
# If not delivered, buyer cancels after timeout
```

### Service Payments
```python
# Client funds escrow for freelance work
# Freelancer completes work
# Client releases escrow (or freelancer uses fulfillment)
# If work not completed, client cancels after timeout
```

### Crowdfunding
```python
# Supporters create escrows with project wallet
# If funding goal met, project releases all escrows
# If goal not met, supporters cancel for refunds
```

## API Reference

### XRPLEscrow

| Method | Description |
|--------|-------------|
| `create()` | Create a new escrow payment |
| `confirm_created()` | Verify escrow exists on-chain |
| `finish()` | Release escrow with fulfillment |
| `cancel()` | Cancel escrow and refund owner |
| `get()` | Get escrow by ID |
| `get_status()` | Get escrow status |
| `list_escrows()` | List escrows with filters |
| `get_account_escrows()` | Get all escrows for an address from XRPL |

### EscrowCondition

| Method | Description |
|--------|-------------|
| `generate()` | Generate random condition/fulfillment pair |
| `from_secret()` | Generate from secret string |
| `verify()` | Verify fulfillment matches condition |

### XRPLClient

| Method | Description |
|--------|-------------|
| `get_balance()` | Get XRP balance for address |
| `get_transaction()` | Get transaction by hash |
| `get_account_info()` | Get account info |
| `get_explorer_url()` | Get block explorer URL for tx |

## License

MIT License - Use freely in your projects!

## Contributing

Contributions welcome! Please open issues or PRs on GitHub.
