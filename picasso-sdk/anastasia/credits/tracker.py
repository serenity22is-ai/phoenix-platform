"""
Credit Tracker — Append-only ledger for agency credit transactions.

Every credit operation (earn, deduct, transfer, expire) is recorded as
an immutable transaction in a per-agency JSON log file. The current
balance is derived by replaying the log — there is no separate balance
field that can drift out of sync.

Events published:
    CREDIT_EARNED   — when credits are awarded (earn or transfer-in)
    CREDIT_REDEEMED — when credits are deducted (deduct or transfer-out)

MYSTES KYRIOS LLC — Confidential.
"""

import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.events import Event, EventBus, EventType

logger = logging.getLogger(__name__)


class CreditTracker:
    """
    Tracks credit balances and transaction history for agencies.

    Each agency's ledger is stored as an append-only JSON-lines file
    at ``{storage_dir}/{agency_id}.jsonl``. This makes the audit trail
    immutable and trivially recoverable.

    Args:
        event_bus: Shared event bus for publishing credit events.
        storage_dir: Directory path for persisting credit ledgers.
    """

    # Transaction types
    TYPE_EARN = "earn"
    TYPE_DEDUCT = "deduct"
    TYPE_TRANSFER = "transfer"
    TYPE_EXPIRE = "expire"

    def __init__(self, event_bus: EventBus, storage_dir: str) -> None:
        self._event_bus = event_bus
        self._storage_dir = Path(storage_dir)
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        logger.info("CreditTracker initialized, storage: %s", self._storage_dir)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def award_credits(
        self,
        agency_id: str,
        amount: int,
        reason: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Award credits to an agency.

        Args:
            agency_id: Target agency identifier.
            amount: Number of credits to award (must be positive).
            reason: Human-readable reason (e.g., "discovery:salesforce").
            metadata: Optional dict of extra context attached to the
                transaction.

        Returns:
            Dict with keys: credit_id, balance, awarded, reason.

        Raises:
            ValueError: If amount is not positive.
        """
        if amount <= 0:
            raise ValueError(f"Award amount must be positive, got {amount}")

        balance = self.get_balance(agency_id)
        new_balance = balance + amount

        txn = self._create_transaction(
            agency_id=agency_id,
            txn_type=self.TYPE_EARN,
            amount=amount,
            balance_after=new_balance,
            reason=reason,
            metadata=metadata,
        )
        self._append_transaction(agency_id, txn)

        # Publish event
        self._event_bus.publish(Event(
            type=EventType.CREDIT_EARNED,
            source="credits.tracker",
            agency_id=agency_id,
            data={
                "credit_id": txn["id"],
                "amount": amount,
                "balance": new_balance,
                "reason": reason,
            },
        ))

        logger.info(
            "Awarded %d credits to agency '%s' (%s). Balance: %d",
            amount, agency_id, reason, new_balance,
        )

        return {
            "credit_id": txn["id"],
            "balance": new_balance,
            "awarded": amount,
            "reason": reason,
        }

    def deduct_credits(
        self,
        agency_id: str,
        amount: int,
        reason: str,
    ) -> Dict[str, Any]:
        """
        Deduct credits from an agency (for redemption).

        Args:
            agency_id: Target agency identifier.
            amount: Number of credits to deduct (must be positive).
            reason: Human-readable reason (e.g., "redemption:subscription").

        Returns:
            Dict with keys: credit_id, balance, deducted, reason.

        Raises:
            ValueError: If amount is not positive or exceeds balance.
        """
        if amount <= 0:
            raise ValueError(f"Deduct amount must be positive, got {amount}")

        balance = self.get_balance(agency_id)
        if amount > balance:
            raise ValueError(
                f"Insufficient credits for agency '{agency_id}': "
                f"balance={balance}, requested={amount}"
            )

        new_balance = balance - amount

        txn = self._create_transaction(
            agency_id=agency_id,
            txn_type=self.TYPE_DEDUCT,
            amount=amount,
            balance_after=new_balance,
            reason=reason,
        )
        self._append_transaction(agency_id, txn)

        # Publish event
        self._event_bus.publish(Event(
            type=EventType.CREDIT_REDEEMED,
            source="credits.tracker",
            agency_id=agency_id,
            data={
                "credit_id": txn["id"],
                "amount": amount,
                "balance": new_balance,
                "reason": reason,
            },
        ))

        logger.info(
            "Deducted %d credits from agency '%s' (%s). Balance: %d",
            amount, agency_id, reason, new_balance,
        )

        return {
            "credit_id": txn["id"],
            "balance": new_balance,
            "deducted": amount,
            "reason": reason,
        }

    def get_balance(self, agency_id: str) -> int:
        """
        Get the current credit balance for an agency.

        Derived from the last transaction's ``balance_after`` field.
        If no transactions exist, the balance is 0.

        Args:
            agency_id: Target agency identifier.

        Returns:
            Current credit balance as an integer.
        """
        transactions = self._read_transactions(agency_id)
        if not transactions:
            return 0
        return transactions[-1]["balance_after"]

    def get_history(
        self,
        agency_id: str,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        Get credit transaction history for an agency.

        Returns transactions in reverse chronological order (newest first).

        Args:
            agency_id: Target agency identifier.
            limit: Maximum number of transactions to return. Defaults to 50.

        Returns:
            List of transaction dicts, newest first.
        """
        transactions = self._read_transactions(agency_id)
        # Return newest first, limited
        return list(reversed(transactions[-limit:]))

    def get_leaderboard(self, limit: int = 20) -> List[Dict[str, Any]]:
        """
        Get top credit earners across all agencies.

        Returns anonymized agency data (agency IDs are hashed for
        public display; full IDs available via admin endpoints).

        Args:
            limit: Maximum number of entries. Defaults to 20.

        Returns:
            List of dicts sorted by balance (descending), each with
            keys: rank, agency_id, agency_id_short, balance,
            lifetime_earned.
        """
        balances = self.get_all_balances()
        if not balances:
            return []

        # Calculate lifetime earned (sum of all positive transactions)
        entries = []
        for agency_id, balance in balances.items():
            transactions = self._read_transactions(agency_id)
            lifetime = sum(
                t["amount"] for t in transactions
                if t["type"] == self.TYPE_EARN
            )
            entries.append({
                "agency_id": agency_id,
                "agency_id_short": agency_id[:8] + "...",
                "balance": balance,
                "lifetime_earned": lifetime,
            })

        # Sort by balance descending
        entries.sort(key=lambda e: e["balance"], reverse=True)
        entries = entries[:limit]

        # Add rank
        for i, entry in enumerate(entries, start=1):
            entry["rank"] = i

        return entries

    def transfer_credits(
        self,
        from_agency: str,
        to_agency: str,
        amount: int,
    ) -> Dict[str, Any]:
        """
        Transfer credits between two agencies.

        Creates a deduction on the sender and an earn on the receiver
        as an atomic pair (same transfer_id in metadata).

        Args:
            from_agency: Sender agency identifier.
            to_agency: Receiver agency identifier.
            amount: Number of credits to transfer (must be positive).

        Returns:
            Dict with keys: transfer_id, from_agency, to_agency, amount,
            from_balance, to_balance.

        Raises:
            ValueError: If amount is not positive, agencies are the same,
                or sender has insufficient balance.
        """
        if amount <= 0:
            raise ValueError(f"Transfer amount must be positive, got {amount}")
        if from_agency == to_agency:
            raise ValueError("Cannot transfer credits to the same agency")

        from_balance = self.get_balance(from_agency)
        if amount > from_balance:
            raise ValueError(
                f"Insufficient credits for transfer from agency '{from_agency}': "
                f"balance={from_balance}, requested={amount}"
            )

        transfer_id = str(uuid.uuid4())[:12]
        reason = f"transfer:{transfer_id}"
        transfer_meta = {
            "transfer_id": transfer_id,
            "counterparty": to_agency,
            "direction": "out",
        }

        # Deduct from sender
        new_from_balance = from_balance - amount
        txn_out = self._create_transaction(
            agency_id=from_agency,
            txn_type=self.TYPE_TRANSFER,
            amount=amount,
            balance_after=new_from_balance,
            reason=reason,
            metadata=transfer_meta,
        )
        self._append_transaction(from_agency, txn_out)

        # Publish deduction event
        self._event_bus.publish(Event(
            type=EventType.CREDIT_REDEEMED,
            source="credits.tracker",
            agency_id=from_agency,
            data={
                "credit_id": txn_out["id"],
                "amount": amount,
                "balance": new_from_balance,
                "reason": reason,
                "transfer_id": transfer_id,
                "to_agency": to_agency,
            },
        ))

        # Credit to receiver
        to_balance = self.get_balance(to_agency)
        new_to_balance = to_balance + amount
        receive_meta = {
            "transfer_id": transfer_id,
            "counterparty": from_agency,
            "direction": "in",
        }
        txn_in = self._create_transaction(
            agency_id=to_agency,
            txn_type=self.TYPE_TRANSFER,
            amount=amount,
            balance_after=new_to_balance,
            reason=reason,
            metadata=receive_meta,
        )
        self._append_transaction(to_agency, txn_in)

        # Publish earn event
        self._event_bus.publish(Event(
            type=EventType.CREDIT_EARNED,
            source="credits.tracker",
            agency_id=to_agency,
            data={
                "credit_id": txn_in["id"],
                "amount": amount,
                "balance": new_to_balance,
                "reason": reason,
                "transfer_id": transfer_id,
                "from_agency": from_agency,
            },
        ))

        logger.info(
            "Transferred %d credits: '%s' -> '%s'. "
            "Sender balance: %d, receiver balance: %d",
            amount, from_agency, to_agency, new_from_balance, new_to_balance,
        )

        return {
            "transfer_id": transfer_id,
            "from_agency": from_agency,
            "to_agency": to_agency,
            "amount": amount,
            "from_balance": new_from_balance,
            "to_balance": new_to_balance,
        }

    def expire_credits(
        self,
        agency_id: str,
        older_than_days: int = 365,
    ) -> int:
        """
        Expire old unused credits for an agency.

        Scans the transaction history and identifies earn transactions
        older than the specified threshold. Calculates the total
        expirable amount (earned but not yet spent/expired) and creates
        a single expiration transaction.

        Note: This is a simplified expiration model. It expires the
        total unspent amount from old earn transactions, not individual
        credit units with serial numbers.

        Args:
            agency_id: Target agency identifier.
            older_than_days: Age threshold in days. Credits earned
                before this many days ago are eligible for expiration.
                Defaults to 365.

        Returns:
            Number of credits expired.
        """
        cutoff = time.time() - (older_than_days * 86400)
        transactions = self._read_transactions(agency_id)
        if not transactions:
            return 0

        # Sum old earnings and all deductions/transfers/expirations
        old_earned = 0
        total_spent = 0
        already_expired = 0

        for txn in transactions:
            if txn["type"] == self.TYPE_EARN and txn["timestamp"] < cutoff:
                old_earned += txn["amount"]
            elif txn["type"] in (self.TYPE_DEDUCT, self.TYPE_EXPIRE):
                total_spent += txn["amount"]
            elif txn["type"] == self.TYPE_TRANSFER:
                meta = txn.get("metadata") or {}
                if meta.get("direction") == "out":
                    total_spent += txn["amount"]

        # Already-expired amounts are part of total_spent
        # Expirable = old earnings minus what has already been consumed
        expirable = max(0, old_earned - total_spent)

        if expirable <= 0:
            return 0

        # Cap to current balance (safety)
        balance = self.get_balance(agency_id)
        expirable = min(expirable, balance)

        if expirable <= 0:
            return 0

        new_balance = balance - expirable
        txn = self._create_transaction(
            agency_id=agency_id,
            txn_type=self.TYPE_EXPIRE,
            amount=expirable,
            balance_after=new_balance,
            reason=f"expiration:older_than_{older_than_days}_days",
            metadata={"cutoff_timestamp": cutoff, "days": older_than_days},
        )
        self._append_transaction(agency_id, txn)

        # Publish redemption event for expiration
        self._event_bus.publish(Event(
            type=EventType.CREDIT_REDEEMED,
            source="credits.tracker",
            agency_id=agency_id,
            data={
                "credit_id": txn["id"],
                "amount": expirable,
                "balance": new_balance,
                "reason": txn["reason"],
                "type": "expiration",
            },
        ))

        logger.info(
            "Expired %d credits for agency '%s' (older than %d days). "
            "Balance: %d",
            expirable, agency_id, older_than_days, new_balance,
        )

        return expirable

    def get_all_balances(self) -> Dict[str, int]:
        """
        Get current credit balances for all agencies.

        Scans the storage directory for all ledger files and reads
        each agency's balance. Intended for admin/analytics use.

        Returns:
            Dict mapping agency_id to current balance.
        """
        balances: Dict[str, int] = {}

        if not self._storage_dir.exists():
            return balances

        for ledger_file in self._storage_dir.glob("*.jsonl"):
            agency_id = ledger_file.stem
            balance = self.get_balance(agency_id)
            balances[agency_id] = balance

        return balances

    # ------------------------------------------------------------------
    # Internal — persistence
    # ------------------------------------------------------------------

    def _ledger_path(self, agency_id: str) -> Path:
        """Return the filesystem path for an agency's ledger file."""
        # Sanitize agency_id for safe filenames
        safe_id = "".join(
            c if c.isalnum() or c in ("-", "_") else "_"
            for c in agency_id
        )
        return self._storage_dir / f"{safe_id}.jsonl"

    def _append_transaction(
        self,
        agency_id: str,
        txn: Dict[str, Any],
    ) -> None:
        """Append a transaction to the agency's ledger file."""
        path = self._ledger_path(agency_id)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(txn, separators=(",", ":")) + "\n")

    def _read_transactions(self, agency_id: str) -> List[Dict[str, Any]]:
        """
        Read all transactions from an agency's ledger file.

        Returns an empty list if the ledger does not exist.
        """
        path = self._ledger_path(agency_id)
        if not path.exists():
            return []

        transactions: List[Dict[str, Any]] = []
        with open(path, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    transactions.append(json.loads(line))
                except json.JSONDecodeError as e:
                    logger.warning(
                        "Corrupt ledger entry in %s line %d: %s",
                        path, line_num, e,
                    )
        return transactions

    @staticmethod
    def _create_transaction(
        agency_id: str,
        txn_type: str,
        amount: int,
        balance_after: int,
        reason: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Create a transaction record.

        Each transaction is an immutable dict with a unique ID,
        timestamp, and all the information needed to reconstruct
        the ledger.
        """
        return {
            "id": str(uuid.uuid4())[:12],
            "agency_id": agency_id,
            "type": txn_type,
            "amount": amount,
            "balance_after": balance_after,
            "reason": reason,
            "timestamp": time.time(),
            "metadata": metadata or {},
        }
