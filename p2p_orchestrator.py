"""
PHOENIX P2P Transaction Orchestrator

Workflow engine that manages the complete lifecycle of a P2P booking:
1. Buyer requests booking with arbitrage opportunity
2. System matches buyer to available helper in target market
3. Buyer's RLUSD locked in XRPL escrow
4. Helper verifies escrow on-chain
5. Phoenix creates browser control session
6. Phoenix automates purchase on helper's browser
7. Booking confirmed → escrow releases to helper + platform
8. On failure → escrow cancels → buyer refunded

This module ties together:
- models.py (P2PTransaction, P2PEscrow, HelperProfile)
- payments.py (P2P escrow functions)
- browser_control.py (remote browser sessions)
- email_service.py (notifications)
"""

import os
import secrets
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from enum import Enum

logger = logging.getLogger(__name__)


def _emit_p2p(buyer_id, helper_user_id, event_type, data):
    """Emit real-time P2P event (best-effort, never blocks)."""
    try:
        from event_stream import emit_p2p_update
        emit_p2p_update(buyer_id, helper_user_id, event_type, data)
    except Exception:
        pass  # SSE is best-effort; never block transaction flow


class P2PWorkflowStatus(Enum):
    """High-level workflow states."""
    INITIATED = "initiated"
    MATCHING = "matching"
    MATCHED = "matched"
    ESCROW_PENDING = "escrow_pending"
    ESCROW_LOCKED = "escrow_locked"
    HELPER_ACCEPTED = "helper_accepted"
    BROWSER_SESSION_CREATED = "browser_session_created"
    PURCHASING = "purchasing"
    BOOKING_CONFIRMED = "booking_confirmed"
    ESCROW_RELEASING = "escrow_releasing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    DISPUTED = "disputed"


class P2POrchestrator:
    """
    Orchestrates the full P2P transaction lifecycle.

    Each method handles one step and advances the transaction
    to the next state. The orchestrator is stateless — all state
    lives in the database via P2PTransaction and P2PEscrow models.
    """

    def __init__(self, db_session):
        self.db = db_session

    # === STEP 1: INITIATE ===

    def initiate_transaction(
        self,
        buyer_id: int,
        origin: str,
        destination: str,
        departure_date: str,
        airline: str,
        flight_number: str,
        us_price_usd: float,
        target_price_usd: float,
        target_price_local: float,
        target_currency: str,
        target_market: str,
    ) -> Dict[str, Any]:
        """
        Step 1: Buyer initiates a P2P booking request.

        Creates a P2PTransaction record and starts the matching process.
        """
        from models import P2PTransaction
        from payments import calculate_p2p_amounts

        # Calculate escrow amounts
        amounts = calculate_p2p_amounts(target_price_usd)

        transaction_id = f"p2p_{secrets.token_hex(10)}"

        transaction = P2PTransaction(
            transaction_id=transaction_id,
            buyer_id=buyer_id,
            origin=origin,
            destination=destination,
            departure_date=datetime.strptime(departure_date, "%Y-%m-%d").date(),
            airline=airline,
            flight_number=flight_number,
            us_price_usd=us_price_usd,
            target_price_usd=target_price_usd,
            target_price_local=target_price_local,
            target_currency=target_currency,
            target_market=target_market,
            savings_usd=round(us_price_usd - target_price_usd, 2),
            escrow_amount_rlusd=amounts["total_escrow_rlusd"],
            helper_reimbursement_rlusd=amounts["helper_reimbursement"],
            helper_earning_rlusd=amounts["helper_earning"],
            platform_fee_rlusd=amounts["platform_fee"],
            status="requested",
            created_at=datetime.utcnow(),
        )

        self.db.add(transaction)
        self.db.commit()

        logger.info(
            f"P2P transaction {transaction_id} initiated: "
            f"{origin}->{destination} on {departure_date}, "
            f"target market {target_market}, "
            f"savings ${transaction.savings_usd:.2f}"
        )

        return {
            "success": True,
            "transaction_id": transaction_id,
            "amounts": amounts,
            "status": "requested",
            "next_step": "match_helper",
        }

    # === STEP 2: MATCH HELPER ===

    def match_helper(self, transaction_id: str) -> Dict[str, Any]:
        """
        Step 2: Find and assign a helper in the target market.

        Searches for available helpers in the target market,
        ordered by rating and experience.
        """
        from models import P2PTransaction, HelperProfile, UserWallet, UserCard

        transaction = P2PTransaction.query.filter_by(
            transaction_id=transaction_id
        ).first()

        if not transaction:
            return {"success": False, "error": "Transaction not found"}

        if transaction.status not in ("requested", "matching"):
            return {"success": False, "error": f"Cannot match in status: {transaction.status}"}

        transaction.status = "matching"
        self.db.commit()

        # Find available helpers in the target market
        helpers = HelperProfile.query.filter_by(
            country_code=transaction.target_market,
            is_active=True,
            is_approved=True,
        ).order_by(
            HelperProfile.average_rating.desc(),
            HelperProfile.successful_transactions.desc(),
        ).all()

        # Filter: helper must have wallet + card, not maxed out for today
        eligible = []
        for helper in helpers:
            # Check daily limit
            if helper.transactions_today >= helper.max_daily_transactions:
                continue

            # Check wallet exists
            wallet = UserWallet.query.filter_by(
                user_id=helper.user_id, is_primary=True
            ).first()
            if not wallet:
                continue

            # Check card exists
            card = UserCard.query.filter_by(
                user_id=helper.user_id, is_active=True
            ).first()
            if not card:
                continue

            eligible.append({
                "helper": helper,
                "wallet": wallet,
                "card": card,
            })

        if not eligible:
            transaction.status = "requested"  # Revert to allow retry
            self.db.commit()
            return {
                "success": False,
                "error": f"No available helpers in {transaction.target_market}",
                "helpers_checked": len(helpers),
            }

        # Select best helper (first eligible — already sorted by rating)
        selected = eligible[0]
        helper = selected["helper"]

        transaction.helper_id = helper.id
        transaction.status = "matched"
        transaction.matched_at = datetime.utcnow()
        self.db.commit()

        _emit_p2p(transaction.buyer_id, helper.user_id, "p2p_matched", {
            "transaction_id": transaction_id,
            "helper_market": helper.country_code,
        })

        logger.info(
            f"Transaction {transaction_id} matched to helper {helper.id} "
            f"in {helper.country_code} (rating: {helper.average_rating})"
        )

        return {
            "success": True,
            "transaction_id": transaction_id,
            "helper_id": helper.id,
            "helper_market": helper.country_code,
            "helper_rating": helper.average_rating,
            "helper_wallet": selected["wallet"].wallet_address,
            "status": "matched",
            "next_step": "create_escrow",
        }

    # === STEP 3: CREATE ESCROW ===

    def create_escrow(
        self, transaction_id: str, buyer_wallet_address: str
    ) -> Dict[str, Any]:
        """
        Step 3: Create XRPL escrow to lock buyer's RLUSD.

        Buyer must have RLUSD in their wallet to fund the escrow.
        """
        from models import P2PTransaction, P2PEscrow, HelperProfile, UserWallet
        from payments import create_p2p_escrow

        transaction = P2PTransaction.query.filter_by(
            transaction_id=transaction_id
        ).first()

        if not transaction:
            return {"success": False, "error": "Transaction not found"}

        if transaction.status != "matched":
            return {"success": False, "error": f"Cannot create escrow in status: {transaction.status}"}

        if not transaction.helper_id:
            return {"success": False, "error": "No helper assigned"}

        # Get helper's wallet address
        helper = HelperProfile.query.get(transaction.helper_id)
        if not helper:
            return {"success": False, "error": "Helper not found"}

        helper_wallet = UserWallet.query.filter_by(
            user_id=helper.user_id, is_primary=True
        ).first()

        if not helper_wallet:
            return {"success": False, "error": "Helper has no wallet configured"}

        # Build amounts dict
        amounts = {
            "total_escrow_rlusd": transaction.escrow_amount_rlusd,
            "helper_total": transaction.helper_reimbursement_rlusd + transaction.helper_earning_rlusd,
            "platform_fee": transaction.platform_fee_rlusd,
        }

        # Create escrow on XRPL
        escrow_result = create_p2p_escrow(
            buyer_address=buyer_wallet_address,
            helper_address=helper_wallet.wallet_address,
            amounts=amounts,
        )

        if "error" in escrow_result:
            return {"success": False, "error": escrow_result["error"]}

        # Store escrow in database
        escrow = P2PEscrow(
            escrow_id=escrow_result["escrow_id"],
            p2p_transaction_id=transaction.id,
            buyer_address=buyer_wallet_address,
            helper_address=helper_wallet.wallet_address,
            platform_address=escrow_result["platform_address"],
            total_rlusd=escrow_result["total_rlusd"],
            helper_amount_rlusd=escrow_result["helper_amount_rlusd"],
            platform_amount_rlusd=escrow_result["platform_amount_rlusd"],
            condition=escrow_result["condition"],
            fulfillment=escrow_result["fulfillment"],
            cancel_after=datetime.fromisoformat(escrow_result["cancel_after"]),
            status="pending",
            created_at=datetime.utcnow(),
        )

        self.db.add(escrow)

        # Update transaction
        transaction.status = "escrow_locked"
        transaction.escrow_locked_at = datetime.utcnow()
        self.db.commit()

        helper = HelperProfile.query.get(transaction.helper_id)
        _emit_p2p(transaction.buyer_id, helper.user_id if helper else None, "p2p_escrow_locked", {
            "transaction_id": transaction_id,
            "escrow_id": escrow.escrow_id,
            "total_rlusd": str(escrow.total_rlusd),
        })

        logger.info(
            f"Escrow {escrow.escrow_id} created for transaction {transaction_id}: "
            f"{escrow.total_rlusd} RLUSD locked"
        )

        return {
            "success": True,
            "transaction_id": transaction_id,
            "escrow_id": escrow.escrow_id,
            "total_rlusd": escrow.total_rlusd,
            "helper_amount": escrow.helper_amount_rlusd,
            "platform_fee": escrow.platform_amount_rlusd,
            "cancel_after": escrow.cancel_after.isoformat(),
            "condition": escrow.condition,
            "status": "escrow_locked",
            "next_step": "helper_verify_escrow",
        }

    # === STEP 4: HELPER VERIFIES ESCROW ===

    def helper_verify_escrow(
        self, transaction_id: str, helper_user_id: int
    ) -> Dict[str, Any]:
        """
        Step 4: Helper verifies the escrow is locked on-chain.

        Helper calls this after seeing the escrow on XRPL ledger.
        This confirms they trust the payment and are ready to proceed.
        """
        from models import P2PTransaction, P2PEscrow, HelperProfile

        transaction = P2PTransaction.query.filter_by(
            transaction_id=transaction_id
        ).first()

        if not transaction:
            return {"success": False, "error": "Transaction not found"}

        if transaction.status != "escrow_locked":
            return {"success": False, "error": f"Cannot verify in status: {transaction.status}"}

        # Verify the caller is the assigned helper
        helper = HelperProfile.query.filter_by(user_id=helper_user_id).first()
        if not helper or helper.id != transaction.helper_id:
            return {"success": False, "error": "Not the assigned helper"}

        escrow = P2PEscrow.query.filter_by(
            p2p_transaction_id=transaction.id
        ).first()

        if not escrow:
            return {"success": False, "error": "Escrow record not found"}

        # If escrow has a tx hash, verify on-chain
        if escrow.create_tx_hash:
            from payments import verify_p2p_escrow_on_chain
            verification = verify_p2p_escrow_on_chain(escrow.create_tx_hash)

            if not verification.get("verified"):
                return {
                    "success": False,
                    "error": f"On-chain verification failed: {verification.get('error')}",
                }

            escrow.on_chain_verified = True
            escrow.ledger_index = verification.get("ledger_index")

        # Mark as accepted by helper
        transaction.escrow_verified_by_helper = True
        transaction.escrow_verified_at = datetime.utcnow()
        transaction.status = "helper_accepted"
        escrow.status = "locked"
        escrow.locked_at = datetime.utcnow()
        self.db.commit()

        logger.info(
            f"Helper {helper.id} accepted transaction {transaction_id}, "
            f"escrow verified"
        )

        return {
            "success": True,
            "transaction_id": transaction_id,
            "escrow_verified": True,
            "on_chain_verified": escrow.on_chain_verified,
            "status": "helper_accepted",
            "next_step": "create_browser_session",
        }

    # === STEP 5: CREATE BROWSER SESSION ===

    def create_browser_session(self, transaction_id: str) -> Dict[str, Any]:
        """
        Step 5: Create a remote browser control session.

        Phoenix generates a WebSocket session for the helper's client
        to connect to. Once connected, Phoenix can drive Playwright
        on the helper's device.
        """
        from models import P2PTransaction, HelperProfile, UserWallet
        from browser_control import create_browser_session

        transaction = P2PTransaction.query.filter_by(
            transaction_id=transaction_id
        ).first()

        if not transaction:
            return {"success": False, "error": "Transaction not found"}

        if transaction.status != "helper_accepted":
            return {"success": False, "error": f"Cannot create session in status: {transaction.status}"}

        helper = HelperProfile.query.get(transaction.helper_id)
        if not helper:
            return {"success": False, "error": "Helper not found"}

        helper_wallet = UserWallet.query.filter_by(
            user_id=helper.user_id, is_primary=True
        ).first()

        # Create the browser control session
        session_result = create_browser_session(
            transaction_id=transaction_id,
            helper_id=helper.id,
            helper_address=helper_wallet.wallet_address if helper_wallet else "",
        )

        # Store session ID on the transaction
        transaction.browser_session_id = session_result["session_id"]
        self.db.commit()

        logger.info(
            f"Browser session {session_result['session_id']} created "
            f"for transaction {transaction_id}"
        )

        return {
            "success": True,
            "transaction_id": transaction_id,
            "session": session_result,
            "status": "helper_accepted",
            "next_step": "helper_connect_browser",
        }

    # === STEP 6: EXECUTE PURCHASE ===

    def start_purchase(self, transaction_id: str) -> Dict[str, Any]:
        """
        Step 6: Begin the automated purchase on the helper's browser.

        Sends booking automation commands through the browser session.
        The helper's client executes them via local Playwright.
        """
        from models import P2PTransaction
        from browser_control import (
            get_browser_control_server,
            FlightBookingAutomation,
        )

        transaction = P2PTransaction.query.filter_by(
            transaction_id=transaction_id
        ).first()

        if not transaction:
            return {"success": False, "error": "Transaction not found"}

        if transaction.status != "helper_accepted":
            return {"success": False, "error": f"Cannot start purchase in status: {transaction.status}"}

        if not transaction.browser_session_id:
            return {"success": False, "error": "No browser session created"}

        server = get_browser_control_server()
        session = server.get_session(transaction.browser_session_id)

        if not session or not session.is_active():
            return {
                "success": False,
                "error": "Browser session not connected. Helper must connect first.",
            }

        # Update status
        transaction.status = "purchasing"
        transaction.purchase_started_at = datetime.utcnow()
        self.db.commit()

        # Generate the search commands for the target market
        commands = FlightBookingAutomation.search_google_flights(
            origin=transaction.origin,
            destination=transaction.destination,
            date=transaction.departure_date.isoformat(),
            market=transaction.target_market,
        )

        # Queue commands for sending
        queued = []
        for cmd in commands:
            server_cmd = server.create_command(
                session_id=transaction.browser_session_id,
                command_type=cmd.command_type,
                params=cmd.params,
                timeout_ms=cmd.timeout_ms,
            )
            if server_cmd:
                queued.append(server_cmd.command_id)

        logger.info(
            f"Purchase started for transaction {transaction_id}: "
            f"{len(queued)} commands queued"
        )

        return {
            "success": True,
            "transaction_id": transaction_id,
            "commands_queued": len(queued),
            "session_id": transaction.browser_session_id,
            "status": "purchasing",
            "next_step": "await_confirmation",
        }

    # === STEP 7: CONFIRM BOOKING ===

    def confirm_booking(
        self,
        transaction_id: str,
        confirmation_code: str,
        passenger_name: str = None,
        passenger_email: str = None,
        eticket_url: str = None,
    ) -> Dict[str, Any]:
        """
        Step 7: Confirm the booking was successful.

        Called after the automated purchase completes and a
        confirmation code is captured from the airline.
        """
        from models import P2PTransaction, HelperProfile
        from browser_control import get_browser_control_server

        transaction = P2PTransaction.query.filter_by(
            transaction_id=transaction_id
        ).first()

        if not transaction:
            return {"success": False, "error": "Transaction not found"}

        if transaction.status != "purchasing":
            return {"success": False, "error": f"Cannot confirm in status: {transaction.status}"}

        # Update transaction with confirmation
        transaction.confirmation_code = confirmation_code
        transaction.status = "confirmed"
        transaction.confirmed_at = datetime.utcnow()

        if passenger_name:
            transaction.passenger_name = passenger_name
        if passenger_email:
            transaction.passenger_email = passenger_email
        if eticket_url:
            transaction.eticket_url = eticket_url

        # Complete the browser session
        if transaction.browser_session_id:
            server = get_browser_control_server()
            server.complete_session(
                transaction.browser_session_id,
                confirmation_code=confirmation_code,
            )

        self.db.commit()

        helper = HelperProfile.query.get(transaction.helper_id)
        _emit_p2p(transaction.buyer_id, helper.user_id if helper else None, "p2p_booking_confirmed", {
            "transaction_id": transaction_id,
            "confirmation_code": confirmation_code,
        })

        logger.info(
            f"Booking confirmed for transaction {transaction_id}: "
            f"code {confirmation_code}"
        )

        return {
            "success": True,
            "transaction_id": transaction_id,
            "confirmation_code": confirmation_code,
            "status": "confirmed",
            "next_step": "release_escrow",
        }

    # === STEP 8: RELEASE ESCROW ===

    def release_escrow(self, transaction_id: str) -> Dict[str, Any]:
        """
        Step 8: Release the escrow, paying helper and platform.

        Called after booking is confirmed. Submits EscrowFinish
        transaction on XRPL to release funds.
        """
        from models import P2PTransaction, P2PEscrow, HelperProfile
        from payments import release_p2p_escrow

        transaction = P2PTransaction.query.filter_by(
            transaction_id=transaction_id
        ).first()

        if not transaction:
            return {"success": False, "error": "Transaction not found"}

        if transaction.status != "confirmed":
            return {"success": False, "error": f"Cannot release in status: {transaction.status}"}

        escrow = P2PEscrow.query.filter_by(
            p2p_transaction_id=transaction.id
        ).first()

        if not escrow:
            return {"success": False, "error": "Escrow not found"}

        amounts = {
            "helper_total": escrow.helper_amount_rlusd,
            "platform_fee": escrow.platform_amount_rlusd,
        }

        # Release escrow on XRPL
        release_result = release_p2p_escrow(
            escrow_tx_hash=escrow.create_tx_hash or "",
            fulfillment=escrow.fulfillment,
            helper_address=escrow.helper_address,
            amounts=amounts,
        )

        if "error" in release_result:
            return {"success": False, "error": release_result["error"]}

        # Update escrow
        escrow.status = "released"
        escrow.released_at = datetime.utcnow()
        if release_result.get("escrow_tx_hash"):
            escrow.helper_release_tx_hash = release_result.get("escrow_tx_hash")

        # Update transaction
        transaction.status = "completed"
        transaction.completed_at = datetime.utcnow()
        transaction.escrow_release_tx_hash = release_result.get("escrow_tx_hash", "")

        # Update helper stats
        helper = HelperProfile.query.get(transaction.helper_id)
        if helper:
            helper.total_transactions += 1
            helper.successful_transactions += 1
            helper.total_earned_rlusd += transaction.helper_earning_rlusd or 0
            helper.last_transaction = datetime.utcnow()
            helper.transactions_today += 1

        self.db.commit()

        _emit_p2p(transaction.buyer_id, helper.user_id if helper else None, "p2p_completed", {
            "transaction_id": transaction_id,
            "escrow_released": True,
            "helper_earned": str(escrow.helper_amount_rlusd),
        })
        try:
            from event_stream import emit_payment_event
            emit_payment_event(transaction.buyer_id, "escrow_released", {
                "escrow_id": escrow.escrow_id,
                "amount": str(escrow.total_rlusd),
            })
        except Exception:
            pass

        logger.info(
            f"Escrow released for transaction {transaction_id}: "
            f"helper gets {escrow.helper_amount_rlusd} RLUSD, "
            f"platform gets {escrow.platform_amount_rlusd} RLUSD"
        )

        # Send notifications
        self._notify_completion(transaction, escrow)

        return {
            "success": True,
            "transaction_id": transaction_id,
            "escrow_released": True,
            "helper_paid_rlusd": escrow.helper_amount_rlusd,
            "platform_fee_rlusd": escrow.platform_amount_rlusd,
            "confirmation_code": transaction.confirmation_code,
            "status": "completed",
        }

    # === FAILURE HANDLING ===

    def fail_transaction(
        self, transaction_id: str, reason: str
    ) -> Dict[str, Any]:
        """
        Handle a failed P2P transaction.

        Updates status, cancels browser session, and marks escrow
        for cancellation (buyer can cancel after timeout for refund).
        """
        from models import P2PTransaction, P2PEscrow, HelperProfile
        from browser_control import get_browser_control_server

        transaction = P2PTransaction.query.filter_by(
            transaction_id=transaction_id
        ).first()

        if not transaction:
            return {"success": False, "error": "Transaction not found"}

        # Cancel browser session if active
        if transaction.browser_session_id:
            server = get_browser_control_server()
            server.fail_session(transaction.browser_session_id, reason)

        # Update transaction
        transaction.status = "failed"
        transaction.failure_reason = reason
        transaction.cancelled_at = datetime.utcnow()

        # Update escrow status
        escrow = P2PEscrow.query.filter_by(
            p2p_transaction_id=transaction.id
        ).first()

        refund_available_at = None
        if escrow and escrow.status in ("pending", "locked"):
            escrow.status = "cancelled"
            escrow.cancelled_at = datetime.utcnow()
            refund_available_at = escrow.cancel_after.isoformat() if escrow.cancel_after else None

        # Update helper stats
        helper_user_id = None
        if transaction.helper_id:
            helper = HelperProfile.query.get(transaction.helper_id)
            if helper:
                helper.failed_transactions += 1
                helper_user_id = helper.user_id

        self.db.commit()

        _emit_p2p(transaction.buyer_id, helper_user_id, "p2p_failed", {
            "transaction_id": transaction_id,
            "reason": reason,
        })
        if escrow:
            try:
                from event_stream import emit_payment_event
                emit_payment_event(transaction.buyer_id, "escrow_cancelled", {
                    "escrow_id": escrow.escrow_id,
                    "refund_available_at": refund_available_at,
                })
            except Exception:
                pass

        logger.error(f"Transaction {transaction_id} failed: {reason}")

        # Notify parties
        self._notify_failure(transaction, reason)

        return {
            "success": True,
            "transaction_id": transaction_id,
            "status": "failed",
            "reason": reason,
            "refund_available_at": refund_available_at,
        }

    def cancel_transaction(
        self, transaction_id: str, cancelled_by: str = "buyer"
    ) -> Dict[str, Any]:
        """
        Cancel a P2P transaction before purchase is initiated.
        """
        from models import P2PTransaction, P2PEscrow

        transaction = P2PTransaction.query.filter_by(
            transaction_id=transaction_id
        ).first()

        if not transaction:
            return {"success": False, "error": "Transaction not found"}

        # Can only cancel before purchasing
        cancellable = ("requested", "matching", "matched", "escrow_locked", "helper_accepted")
        if transaction.status not in cancellable:
            return {
                "success": False,
                "error": f"Cannot cancel in status: {transaction.status}",
            }

        transaction.status = "cancelled"
        transaction.cancelled_at = datetime.utcnow()
        transaction.failure_reason = f"Cancelled by {cancelled_by}"

        # Cancel escrow if exists
        escrow = P2PEscrow.query.filter_by(
            p2p_transaction_id=transaction.id
        ).first()
        if escrow:
            escrow.status = "cancelled"
            escrow.cancelled_at = datetime.utcnow()

        # Cancel browser session if exists
        if transaction.browser_session_id:
            from browser_control import get_browser_control_server
            server = get_browser_control_server()
            server.cancel_session(transaction.browser_session_id)

        helper_user_id = None
        if transaction.helper_id:
            helper = HelperProfile.query.get(transaction.helper_id)
            if helper:
                helper_user_id = helper.user_id

        self.db.commit()

        _emit_p2p(transaction.buyer_id, helper_user_id, "p2p_cancelled", {
            "transaction_id": transaction_id,
            "cancelled_by": cancelled_by,
        })

        logger.info(f"Transaction {transaction_id} cancelled by {cancelled_by}")

        return {
            "success": True,
            "transaction_id": transaction_id,
            "status": "cancelled",
        }

    # === FULL WORKFLOW ===

    def run_full_workflow(
        self,
        buyer_id: int,
        buyer_wallet_address: str,
        origin: str,
        destination: str,
        departure_date: str,
        airline: str,
        flight_number: str,
        us_price_usd: float,
        target_price_usd: float,
        target_price_local: float,
        target_currency: str,
        target_market: str,
    ) -> Dict[str, Any]:
        """
        Execute the complete P2P workflow from initiation through matching
        and escrow creation. Returns after escrow is created — the remaining
        steps (helper verification, browser session, purchase) happen
        asynchronously.

        This is the main entry point for the API to start a P2P transaction.
        """
        # Step 1: Initiate
        init_result = self.initiate_transaction(
            buyer_id=buyer_id,
            origin=origin,
            destination=destination,
            departure_date=departure_date,
            airline=airline,
            flight_number=flight_number,
            us_price_usd=us_price_usd,
            target_price_usd=target_price_usd,
            target_price_local=target_price_local,
            target_currency=target_currency,
            target_market=target_market,
        )

        if not init_result.get("success"):
            return init_result

        transaction_id = init_result["transaction_id"]

        # Step 2: Match helper
        match_result = self.match_helper(transaction_id)

        if not match_result.get("success"):
            return {
                **match_result,
                "transaction_id": transaction_id,
                "status": "no_helpers_available",
            }

        # Step 3: Create escrow
        escrow_result = self.create_escrow(transaction_id, buyer_wallet_address)

        if not escrow_result.get("success"):
            self.cancel_transaction(transaction_id, "system")
            return escrow_result

        # Return — remaining steps are async (helper verifies, connects, etc.)
        return {
            "success": True,
            "transaction_id": transaction_id,
            "helper_id": match_result["helper_id"],
            "helper_market": match_result["helper_market"],
            "escrow_id": escrow_result["escrow_id"],
            "total_rlusd": escrow_result["total_rlusd"],
            "status": "escrow_locked",
            "next_steps": [
                "Helper verifies escrow on-chain",
                "Helper connects browser client",
                "Phoenix automates purchase",
                "Booking confirmed → escrow releases",
            ],
        }

    # === QUERY METHODS ===

    def get_transaction_status(self, transaction_id: str) -> Dict[str, Any]:
        """Get full status of a P2P transaction."""
        from models import P2PTransaction, P2PEscrow

        transaction = P2PTransaction.query.filter_by(
            transaction_id=transaction_id
        ).first()

        if not transaction:
            return {"error": "Transaction not found"}

        escrow = P2PEscrow.query.filter_by(
            p2p_transaction_id=transaction.id
        ).first()

        result = transaction.to_dict()
        if escrow:
            result["escrow"] = escrow.to_dict()

        # Add browser session status if active
        if transaction.browser_session_id:
            from browser_control import get_session_status
            result["browser_session"] = get_session_status(
                transaction.browser_session_id
            )

        return result

    def get_buyer_transactions(self, buyer_id: int) -> List[Dict]:
        """Get all P2P transactions for a buyer."""
        from models import P2PTransaction
        transactions = P2PTransaction.query.filter_by(
            buyer_id=buyer_id
        ).order_by(P2PTransaction.created_at.desc()).all()
        return [t.to_dict() for t in transactions]

    def get_helper_transactions(self, helper_id: int) -> List[Dict]:
        """Get all P2P transactions for a helper."""
        from models import P2PTransaction
        transactions = P2PTransaction.query.filter_by(
            helper_id=helper_id
        ).order_by(P2PTransaction.created_at.desc()).all()
        return [t.to_dict() for t in transactions]

    def get_pending_transactions(self) -> List[Dict]:
        """Get all pending P2P transactions awaiting action."""
        from models import P2PTransaction
        pending_statuses = (
            "requested", "matching", "matched", "escrow_locked",
            "helper_accepted", "purchasing",
        )
        transactions = P2PTransaction.query.filter(
            P2PTransaction.status.in_(pending_statuses)
        ).order_by(P2PTransaction.created_at.asc()).all()
        return [t.to_dict() for t in transactions]

    # === NOTIFICATIONS ===

    def _notify_completion(self, transaction, escrow):
        """Send completion notifications to buyer and helper."""
        try:
            from email_service import (
                send_p2p_booking_confirmed,
                send_p2p_helper_payment,
            )
            from models import User, HelperProfile

            # Notify buyer
            buyer = User.query.get(transaction.buyer_id)
            if buyer:
                send_p2p_booking_confirmed(
                    to=buyer.email,
                    name=buyer.name,
                    transaction={
                        "origin": transaction.origin,
                        "destination": transaction.destination,
                        "departure_date": transaction.departure_date.isoformat() if transaction.departure_date else "",
                        "airline": transaction.airline,
                        "confirmation_code": transaction.confirmation_code,
                        "savings_usd": transaction.savings_usd,
                    },
                )

            # Notify helper
            if transaction.helper_id:
                helper = HelperProfile.query.get(transaction.helper_id)
                if helper:
                    helper_user = User.query.get(helper.user_id)
                    if helper_user:
                        send_p2p_helper_payment(
                            to=helper_user.email,
                            name=helper_user.name,
                            transaction={
                                "transaction_id": transaction.transaction_id,
                                "earning_rlusd": transaction.helper_earning_rlusd,
                                "reimbursement_rlusd": transaction.helper_reimbursement_rlusd,
                                "total_rlusd": escrow.helper_amount_rlusd,
                            },
                        )

        except Exception as e:
            logger.error(f"Failed to send completion notifications: {e}")

    def _notify_failure(self, transaction, reason):
        """Send failure notifications."""
        try:
            from email_service import send_p2p_transaction_failed
            from models import User

            buyer = User.query.get(transaction.buyer_id)
            if buyer:
                send_p2p_transaction_failed(
                    to=buyer.email,
                    name=buyer.name,
                    transaction={
                        "origin": transaction.origin,
                        "destination": transaction.destination,
                        "reason": reason,
                    },
                )

        except Exception as e:
            logger.error(f"Failed to send failure notifications: {e}")


# --- CONVENIENCE FUNCTIONS ---

def get_orchestrator(db_session=None) -> P2POrchestrator:
    """Get a P2P orchestrator with the current database session."""
    if db_session is None:
        from models import db
        db_session = db.session
    return P2POrchestrator(db_session)


def start_p2p_booking(
    buyer_id: int,
    buyer_wallet_address: str,
    flight_data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    High-level entry point for starting a P2P booking.

    Args:
        buyer_id: The buyer's user ID
        buyer_wallet_address: Buyer's XRPL wallet address
        flight_data: Dict with flight details and pricing

    Returns:
        Dict with transaction details
    """
    orchestrator = get_orchestrator()

    return orchestrator.run_full_workflow(
        buyer_id=buyer_id,
        buyer_wallet_address=buyer_wallet_address,
        origin=flight_data.get("origin", ""),
        destination=flight_data.get("destination", ""),
        departure_date=flight_data.get("departure_date", ""),
        airline=flight_data.get("airline", ""),
        flight_number=flight_data.get("flight_number", ""),
        us_price_usd=flight_data.get("us_price_usd", 0),
        target_price_usd=flight_data.get("target_price_usd", 0),
        target_price_local=flight_data.get("target_price_local", 0),
        target_currency=flight_data.get("target_currency", ""),
        target_market=flight_data.get("target_market", ""),
    )


# --- CLI FOR TESTING ---

if __name__ == "__main__":
    print("PHOENIX P2P Transaction Orchestrator")
    print("=" * 50)
    print()
    print("Workflow Steps:")
    for i, status in enumerate(P2PWorkflowStatus, 1):
        print(f"  {i:2}. {status.value}")
    print()
    print("Entry point: start_p2p_booking(buyer_id, wallet, flight_data)")
    print("Full workflow: initiate -> match -> escrow -> verify -> browser -> purchase -> confirm -> release")
