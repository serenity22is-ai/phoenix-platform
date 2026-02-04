"""
XRPL Client - Base client for interacting with XRP Ledger

Provides connection management and common utilities for all XRPL operations.
"""

import os
import logging
from typing import Optional, Dict, Any
from datetime import datetime

from xrpl.clients import JsonRpcClient, WebsocketClient
from xrpl.wallet import Wallet
from xrpl.models.requests import AccountInfo, ServerInfo, Tx
from xrpl.utils import xrp_to_drops, drops_to_xrp

logger = logging.getLogger(__name__)


# XRPL Network Endpoints
NETWORKS = {
    "mainnet": {
        "json_rpc": "https://xrplcluster.com",
        "websocket": "wss://xrplcluster.com",
        "explorer": "https://livenet.xrpl.org",
    },
    "testnet": {
        "json_rpc": "https://s.altnet.rippletest.net:51234",
        "websocket": "wss://s.altnet.rippletest.net:51233",
        "explorer": "https://testnet.xrpl.org",
    },
    "devnet": {
        "json_rpc": "https://s.devnet.rippletest.net:51234",
        "websocket": "wss://s.devnet.rippletest.net:51233",
        "explorer": "https://devnet.xrpl.org",
    },
}

# Ripple Epoch: January 1, 2000 (00:00 UTC)
RIPPLE_EPOCH = datetime(2000, 1, 1)


class XRPLClient:
    """
    Base client for XRPL interactions.

    Handles:
    - Network connection (mainnet, testnet, devnet)
    - Wallet management
    - Transaction submission
    - Account queries

    Usage:
        client = XRPLClient(network="testnet")
        client.set_wallet(seed="sXXX...")

        # Check balance
        balance = client.get_balance("rAddress...")

        # Get transaction
        tx = client.get_transaction("HASH...")
    """

    def __init__(
        self,
        network: str = "testnet",
        json_rpc_url: Optional[str] = None,
        websocket_url: Optional[str] = None,
    ):
        """
        Initialize XRPL client.

        Args:
            network: Network name (mainnet, testnet, devnet)
            json_rpc_url: Custom JSON-RPC endpoint
            websocket_url: Custom WebSocket endpoint
        """
        self.network = network

        # Get network config
        if network in NETWORKS:
            config = NETWORKS[network]
            self.json_rpc_url = json_rpc_url or config["json_rpc"]
            self.websocket_url = websocket_url or config["websocket"]
            self.explorer_url = config["explorer"]
        else:
            self.json_rpc_url = json_rpc_url or NETWORKS["testnet"]["json_rpc"]
            self.websocket_url = websocket_url or NETWORKS["testnet"]["websocket"]
            self.explorer_url = NETWORKS["testnet"]["explorer"]

        # Initialize JSON-RPC client
        self._client = JsonRpcClient(self.json_rpc_url)

        # Wallet (set later)
        self._wallet: Optional[Wallet] = None

    @property
    def client(self) -> JsonRpcClient:
        """Get the underlying XRPL client."""
        return self._client

    @property
    def wallet(self) -> Optional[Wallet]:
        """Get the configured wallet."""
        return self._wallet

    @property
    def address(self) -> Optional[str]:
        """Get wallet address if configured."""
        return self._wallet.classic_address if self._wallet else None

    def set_wallet(
        self,
        seed: Optional[str] = None,
        wallet: Optional[Wallet] = None,
    ) -> None:
        """
        Configure the wallet for signing transactions.

        Args:
            seed: Wallet seed (sXXX...)
            wallet: Pre-configured Wallet object
        """
        if wallet:
            self._wallet = wallet
        elif seed:
            self._wallet = Wallet.from_seed(seed)
        else:
            raise ValueError("Must provide seed or wallet")

        logger.info(f"Wallet configured: {self._wallet.classic_address}")

    def set_wallet_from_env(
        self,
        seed_var: str = "XRPL_WALLET_SEED",
    ) -> None:
        """
        Configure wallet from environment variable.

        Args:
            seed_var: Environment variable name containing seed
        """
        seed = os.getenv(seed_var)
        if not seed:
            raise ValueError(f"Environment variable {seed_var} not set")
        self.set_wallet(seed=seed)

    # --- Account Queries ---

    def get_account_info(self, address: str) -> Dict[str, Any]:
        """
        Get account information.

        Args:
            address: XRP address to query

        Returns:
            Account info dict
        """
        request = AccountInfo(account=address, ledger_index="validated")
        response = self._client.request(request)
        return response.result

    def get_balance(self, address: str) -> float:
        """
        Get XRP balance for an address.

        Args:
            address: XRP address

        Returns:
            Balance in XRP
        """
        try:
            info = self.get_account_info(address)
            balance_drops = info.get("account_data", {}).get("Balance", "0")
            return float(drops_to_xrp(balance_drops))
        except Exception as e:
            logger.error(f"Error getting balance for {address}: {e}")
            return 0.0

    def get_transaction(self, tx_hash: str) -> Dict[str, Any]:
        """
        Get transaction details by hash.

        Args:
            tx_hash: Transaction hash

        Returns:
            Transaction dict
        """
        request = Tx(transaction=tx_hash)
        response = self._client.request(request)
        return response.result

    def get_server_info(self) -> Dict[str, Any]:
        """Get XRPL server information."""
        request = ServerInfo()
        response = self._client.request(request)
        return response.result

    # --- Utility Methods ---

    @staticmethod
    def xrp_to_drops(xrp: float) -> str:
        """Convert XRP to drops."""
        return xrp_to_drops(xrp)

    @staticmethod
    def drops_to_xrp(drops: str) -> float:
        """Convert drops to XRP."""
        return float(drops_to_xrp(drops))

    @staticmethod
    def datetime_to_ripple_time(dt: datetime) -> int:
        """
        Convert datetime to Ripple epoch time.

        Ripple time is seconds since January 1, 2000.
        """
        return int((dt - RIPPLE_EPOCH).total_seconds())

    @staticmethod
    def ripple_time_to_datetime(ripple_time: int) -> datetime:
        """Convert Ripple epoch time to datetime."""
        from datetime import timedelta
        return RIPPLE_EPOCH + timedelta(seconds=ripple_time)

    def get_explorer_url(self, tx_hash: str) -> str:
        """Get explorer URL for a transaction."""
        return f"{self.explorer_url}/transactions/{tx_hash}"

    def get_account_explorer_url(self, address: str) -> str:
        """Get explorer URL for an account."""
        return f"{self.explorer_url}/accounts/{address}"

    # --- Connection Management ---

    def is_connected(self) -> bool:
        """Check if connected to XRPL."""
        try:
            self.get_server_info()
            return True
        except Exception:
            return False

    def get_network_info(self) -> Dict[str, Any]:
        """Get current network configuration."""
        return {
            "network": self.network,
            "json_rpc_url": self.json_rpc_url,
            "websocket_url": self.websocket_url,
            "explorer_url": self.explorer_url,
            "wallet_configured": self._wallet is not None,
            "wallet_address": self.address,
        }


# --- Convenience Functions ---

def get_client(network: str = "testnet") -> XRPLClient:
    """Get a configured XRPL client."""
    client = XRPLClient(network=network)

    # Try to load wallet from environment
    seed = os.getenv("XRPL_WALLET_SEED")
    if seed:
        client.set_wallet(seed=seed)

    return client


def get_mainnet_client() -> XRPLClient:
    """Get a mainnet XRPL client."""
    return get_client("mainnet")


def get_testnet_client() -> XRPLClient:
    """Get a testnet XRPL client."""
    return get_client("testnet")
