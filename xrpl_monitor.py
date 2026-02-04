"""
PHOENIX XRPL Ledger Subscription Monitor

Subscribes to the XRPL WebSocket API for real-time escrow events instead
of polling. Detects EscrowCreate, EscrowFinish, and EscrowCancel transactions
targeting the platform wallet and updates the database + pushes SSE events.

Architecture:
    XRPL Ledger → WebSocket subscription → xrpl_monitor → DB update + SSE push

Usage:
    # As a standalone daemon process:
    python xrpl_monitor.py

    # From application code:
    from xrpl_monitor import LedgerMonitor
    monitor = LedgerMonitor()
    monitor.start()   # background thread
    monitor.stop()

    # Register Flask routes for status:
    from xrpl_monitor import register_monitor_routes
    register_monitor_routes(app)
"""

import asyncio
import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta
from typing import Dict, Optional, Set

logger = logging.getLogger(__name__)

XRPL_NETWORK = os.environ.get("XRPL_NETWORK", "testnet")

WEBSOCKET_URLS = {
    "mainnet": "wss://xrplcluster.com",
    "testnet": "wss://s.altnet.rippletest.net:51233",
    "devnet": "wss://s.devnet.rippletest.net:51233",
}

PLATFORM_WALLET = os.environ.get(
    "XRPL_WALLET_ADDRESS", "rBYk2nioyZGDndMqDSp2eMD22ZD9bNwM1d"
)

# Reconnect backoff
RECONNECT_MIN_DELAY = 2
RECONNECT_MAX_DELAY = 60


class LedgerMonitor:
    """
    Real-time XRPL ledger monitor using WebSocket subscriptions.

    Subscribes to:
    - accounts: Platform wallet — detects incoming/outgoing escrow txns
    - ledger: Closed ledgers — detects escrow expirations via cancel_after

    On relevant transaction:
    1. Updates P2PEscrow / P2PTransaction / Escrow in the database
    2. Publishes SSE event for the affected user
    """

    def __init__(self, network=None, wallet_address=None, flask_app=None):
        self.network = network or XRPL_NETWORK
        self.ws_url = WEBSOCKET_URLS.get(self.network, WEBSOCKET_URLS["testnet"])
        self.wallet_address = wallet_address or PLATFORM_WALLET
        self.flask_app = flask_app

        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._connected = False
        self._last_ledger_index = 0
        self._stats = {
            "started_at": None,
            "escrow_creates_seen": 0,
            "escrow_finishes_seen": 0,
            "escrow_cancels_seen": 0,
            "ledgers_processed": 0,
            "reconnects": 0,
            "errors": 0,
        }

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self):
        """Start the monitor in a background thread."""
        if self._running:
            return
        self._running = True
        self._stats["started_at"] = datetime.utcnow().isoformat()
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="xrpl_monitor"
        )
        self._thread.start()
        logger.info(
            f"XRPL ledger monitor started (network={self.network}, "
            f"wallet={self.wallet_address})"
        )

    def stop(self):
        """Stop the monitor."""
        self._running = False
        self._connected = False
        logger.info("XRPL ledger monitor stopping")

    @property
    def is_running(self):
        return self._running and self._connected

    @property
    def stats(self):
        return {**self._stats, "connected": self._connected}

    # ------------------------------------------------------------------
    # Main loop (runs in background thread)
    # ------------------------------------------------------------------

    def _run_loop(self):
        """Reconnection wrapper around the async WebSocket loop."""
        delay = RECONNECT_MIN_DELAY
        while self._running:
            try:
                asyncio.run(self._ws_loop())
            except Exception as e:
                self._connected = False
                self._stats["errors"] += 1
                logger.error(f"XRPL monitor error: {e}")

            if not self._running:
                break

            self._stats["reconnects"] += 1
            logger.info(f"XRPL monitor reconnecting in {delay}s")
            time.sleep(delay)
            delay = min(delay * 2, RECONNECT_MAX_DELAY)

        self._connected = False

    async def _ws_loop(self):
        """Connect to XRPL WebSocket and process subscription messages."""
        import websockets

        async with websockets.connect(
            self.ws_url,
            ping_interval=30,
            ping_timeout=10,
            close_timeout=5,
        ) as ws:
            self._connected = True
            logger.info(f"Connected to XRPL WebSocket: {self.ws_url}")

            # Subscribe to platform wallet account and ledger stream
            subscribe_msg = {
                "id": 1,
                "command": "subscribe",
                "accounts": [self.wallet_address],
                "streams": ["ledger"],
            }
            await ws.send(json.dumps(subscribe_msg))
            resp = await ws.recv()
            sub_result = json.loads(resp)
            if sub_result.get("status") == "success":
                self._last_ledger_index = sub_result.get("result", {}).get(
                    "ledger_index", 0
                )
                logger.info(
                    f"Subscribed to XRPL (ledger_index={self._last_ledger_index})"
                )
            else:
                logger.warning(f"Subscription response: {sub_result}")

            # Message loop
            while self._running:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=60)
                except asyncio.TimeoutError:
                    # No message in 60s — send ping to keep alive
                    continue

                msg = json.loads(raw)
                msg_type = msg.get("type")

                if msg_type == "transaction":
                    self._handle_transaction(msg)
                elif msg_type == "ledgerClosed":
                    self._handle_ledger_closed(msg)

    # ------------------------------------------------------------------
    # Transaction handlers
    # ------------------------------------------------------------------

    def _handle_transaction(self, msg):
        """Process a transaction notification from the subscription."""
        tx = msg.get("transaction", {})
        tx_type = tx.get("TransactionType")
        validated = msg.get("validated", False)

        if not validated:
            return

        if tx_type == "EscrowCreate":
            self._on_escrow_create(tx, msg)
        elif tx_type == "EscrowFinish":
            self._on_escrow_finish(tx, msg)
        elif tx_type == "EscrowCancel":
            self._on_escrow_cancel(tx, msg)
        elif tx_type == "Payment":
            self._on_payment(tx, msg)

    def _handle_ledger_closed(self, msg):
        """Track ledger index for logging and timeouts."""
        self._last_ledger_index = msg.get("ledger_index", self._last_ledger_index)
        self._stats["ledgers_processed"] += 1

    # ------------------------------------------------------------------
    # Escrow event handlers
    # ------------------------------------------------------------------

    def _on_escrow_create(self, tx, msg):
        """An EscrowCreate targeting our wallet was detected on-chain."""
        self._stats["escrow_creates_seen"] += 1

        destination = tx.get("Destination")
        sender = tx.get("Account")
        tx_hash = tx.get("hash")
        sequence = tx.get("Sequence")
        amount_drops = tx.get("Amount")
        condition = tx.get("Condition")

        logger.info(
            f"EscrowCreate detected: sender={sender} dest={destination} "
            f"hash={tx_hash} seq={sequence}"
        )

        if destination != self.wallet_address:
            return

        self._run_in_app_context(
            self._process_escrow_create,
            sender=sender,
            tx_hash=tx_hash,
            sequence=sequence,
            amount_drops=amount_drops,
            condition=condition,
        )

    def _on_escrow_finish(self, tx, msg):
        """An EscrowFinish for our wallet was detected."""
        self._stats["escrow_finishes_seen"] += 1

        owner = tx.get("Owner")
        offer_sequence = tx.get("OfferSequence")
        tx_hash = tx.get("hash")

        logger.info(
            f"EscrowFinish detected: owner={owner} seq={offer_sequence} "
            f"hash={tx_hash}"
        )

        self._run_in_app_context(
            self._process_escrow_finish,
            owner=owner,
            offer_sequence=offer_sequence,
            tx_hash=tx_hash,
        )

    def _on_escrow_cancel(self, tx, msg):
        """An EscrowCancel for our wallet was detected."""
        self._stats["escrow_cancels_seen"] += 1

        owner = tx.get("Owner")
        offer_sequence = tx.get("OfferSequence")
        tx_hash = tx.get("hash")

        logger.info(
            f"EscrowCancel detected: owner={owner} seq={offer_sequence} "
            f"hash={tx_hash}"
        )

        self._run_in_app_context(
            self._process_escrow_cancel,
            owner=owner,
            offer_sequence=offer_sequence,
            tx_hash=tx_hash,
        )

    def _on_payment(self, tx, msg):
        """A Payment to our wallet was detected (for direct XRP payments)."""
        destination = tx.get("Destination")
        if destination != self.wallet_address:
            return

        tx_hash = tx.get("hash")
        sender = tx.get("Account")
        dest_tag = tx.get("DestinationTag")
        amount = tx.get("Amount")

        logger.info(
            f"Payment received: sender={sender} hash={tx_hash} "
            f"dest_tag={dest_tag} amount={amount}"
        )

        self._run_in_app_context(
            self._process_payment,
            sender=sender,
            tx_hash=tx_hash,
            dest_tag=dest_tag,
            amount=amount,
        )

    # ------------------------------------------------------------------
    # Database + SSE processing (runs inside Flask app context)
    # ------------------------------------------------------------------

    def _run_in_app_context(self, func, **kwargs):
        """Execute a function inside the Flask app context."""
        app = self.flask_app
        if app is None:
            try:
                from server import app as flask_app
                app = flask_app
            except ImportError:
                logger.warning("No Flask app available for DB operations")
                return

        try:
            with app.app_context():
                func(**kwargs)
        except Exception as e:
            logger.error(f"Error in app context handler: {e}")
            self._stats["errors"] += 1

    def _process_escrow_create(self, sender, tx_hash, sequence, amount_drops, condition):
        """Update DB when a new escrow is created targeting our wallet."""
        from models import db, Escrow, P2PEscrow

        # Check standard escrows
        escrow = Escrow.query.filter_by(
            sender_address=sender,
            status="pending",
        ).filter(Escrow.create_tx_hash.is_(None)).first()

        if escrow and escrow.condition == condition:
            escrow.create_tx_hash = tx_hash
            escrow.sequence = sequence
            db.session.commit()
            logger.info(f"Escrow {escrow.escrow_id} confirmed on-chain: {tx_hash}")

            self._emit_event(
                escrow.user_id,
                "escrow_confirmed",
                {
                    "escrow_id": escrow.escrow_id,
                    "tx_hash": tx_hash,
                    "amount_xrp": escrow.amount_xrp,
                },
            )
            return

        # Check P2P escrows
        p2p_escrow = P2PEscrow.query.filter_by(
            buyer_address=sender,
            status="pending",
        ).filter(P2PEscrow.create_tx_hash.is_(None)).first()

        if p2p_escrow and p2p_escrow.condition == condition:
            p2p_escrow.create_tx_hash = tx_hash
            p2p_escrow.create_sequence = sequence
            p2p_escrow.on_chain_verified = True
            p2p_escrow.status = "locked"
            p2p_escrow.locked_at = datetime.utcnow()
            db.session.commit()

            # Also update the P2P transaction status
            from models import P2PTransaction
            p2p_tx = P2PTransaction.query.get(p2p_escrow.p2p_transaction_id)
            if p2p_tx and p2p_tx.status == "matched":
                p2p_tx.status = "escrow_locked"
                p2p_tx.escrow_locked_at = datetime.utcnow()
                p2p_tx.escrow_tx_hash = tx_hash
                p2p_tx.escrow_sequence = sequence
                p2p_tx.escrow_verified_by_helper = True
                p2p_tx.escrow_verified_at = datetime.utcnow()
                db.session.commit()

                self._emit_event(
                    p2p_tx.buyer_id,
                    "p2p_escrow_locked",
                    {
                        "transaction_id": p2p_tx.transaction_id,
                        "escrow_id": p2p_escrow.escrow_id,
                        "tx_hash": tx_hash,
                    },
                )
            logger.info(
                f"P2P Escrow {p2p_escrow.escrow_id} confirmed on-chain: {tx_hash}"
            )
            return

        # Check private market deals
        try:
            from models import PrivateMarketDeal
            pm_deal = PrivateMarketDeal.query.filter_by(
                status="escrow_funded",
            ).filter(
                PrivateMarketDeal.escrow_condition == condition,
                PrivateMarketDeal.escrow_tx_hash.is_(None),
            ).first()

            if pm_deal:
                pm_deal.escrow_tx_hash = tx_hash
                pm_deal.escrow_sequence = sequence
                db.session.commit()
                logger.info(f"Private deal {pm_deal.id} escrow confirmed on-chain: {tx_hash}")

                self._emit_event(
                    pm_deal.buyer_id,
                    "deal_escrow_confirmed",
                    {
                        "deal_id": pm_deal.id,
                        "tx_hash": tx_hash,
                        "amount_rlusd": pm_deal.agreed_price_rlusd,
                    },
                )
        except Exception as e:
            logger.debug(f"Private market deal check skipped: {e}")

    def _process_escrow_finish(self, owner, offer_sequence, tx_hash):
        """Update DB when an escrow is finished (funds released)."""
        from models import db, Escrow, P2PEscrow, P2PTransaction

        # Check standard escrows
        escrow = Escrow.query.filter_by(
            sender_address=owner,
            sequence=offer_sequence,
            status="pending",
        ).first()

        if escrow:
            escrow.status = "released"
            escrow.finish_tx_hash = tx_hash
            escrow.released_at = datetime.utcnow()
            db.session.commit()
            logger.info(f"Escrow {escrow.escrow_id} released on-chain: {tx_hash}")

            self._emit_event(
                escrow.user_id,
                "escrow_released",
                {
                    "escrow_id": escrow.escrow_id,
                    "tx_hash": tx_hash,
                },
            )
            return

        # Check P2P escrows
        p2p_escrow = P2PEscrow.query.filter_by(
            buyer_address=owner,
            create_sequence=offer_sequence,
        ).filter(P2PEscrow.status.in_(["locked", "pending"])).first()

        if p2p_escrow:
            p2p_escrow.status = "released"
            p2p_escrow.helper_release_tx_hash = tx_hash
            p2p_escrow.released_at = datetime.utcnow()
            db.session.commit()

            p2p_tx = P2PTransaction.query.get(p2p_escrow.p2p_transaction_id)
            if p2p_tx:
                p2p_tx.escrow_release_tx_hash = tx_hash
                if p2p_tx.status in ("confirmed", "purchasing"):
                    p2p_tx.status = "completed"
                    p2p_tx.completed_at = datetime.utcnow()
                db.session.commit()

                self._emit_event(
                    p2p_tx.buyer_id,
                    "p2p_completed",
                    {
                        "transaction_id": p2p_tx.transaction_id,
                        "tx_hash": tx_hash,
                    },
                )
            logger.info(
                f"P2P Escrow {p2p_escrow.escrow_id} released on-chain: {tx_hash}"
            )
            return

        # Check private market deals
        try:
            from models import PrivateMarketDeal
            pm_deal = PrivateMarketDeal.query.filter_by(
                escrow_sequence=offer_sequence,
            ).filter(PrivateMarketDeal.status.in_(["escrow_funded"])).first()

            if pm_deal:
                pm_deal.status = "completed"
                pm_deal.completed_at = datetime.utcnow()
                db.session.commit()
                logger.info(f"Private deal {pm_deal.id} escrow released on-chain: {tx_hash}")

                self._emit_event(
                    pm_deal.buyer_id,
                    "deal_completed",
                    {
                        "deal_id": pm_deal.id,
                        "tx_hash": tx_hash,
                        "amount_rlusd": pm_deal.agreed_price_rlusd,
                    },
                )
        except Exception as e:
            logger.debug(f"Private market deal finish check skipped: {e}")

    def _process_escrow_cancel(self, owner, offer_sequence, tx_hash):
        """Update DB when an escrow is cancelled (funds returned)."""
        from models import db, Escrow, P2PEscrow, P2PTransaction

        escrow = Escrow.query.filter_by(
            sender_address=owner,
            sequence=offer_sequence,
        ).filter(Escrow.status.in_(["pending"])).first()

        if escrow:
            escrow.status = "cancelled"
            escrow.cancel_tx_hash = tx_hash
            escrow.cancelled_at = datetime.utcnow()
            db.session.commit()
            logger.info(f"Escrow {escrow.escrow_id} cancelled on-chain: {tx_hash}")

            self._emit_event(
                escrow.user_id,
                "escrow_cancelled",
                {"escrow_id": escrow.escrow_id, "tx_hash": tx_hash},
            )
            return

        p2p_escrow = P2PEscrow.query.filter_by(
            buyer_address=owner,
            create_sequence=offer_sequence,
        ).filter(P2PEscrow.status.in_(["locked", "pending"])).first()

        if p2p_escrow:
            p2p_escrow.status = "cancelled"
            p2p_escrow.cancel_tx_hash = tx_hash
            p2p_escrow.cancelled_at = datetime.utcnow()
            db.session.commit()

            p2p_tx = P2PTransaction.query.get(p2p_escrow.p2p_transaction_id)
            if p2p_tx and p2p_tx.status not in ("completed", "cancelled"):
                p2p_tx.status = "cancelled"
                p2p_tx.cancelled_at = datetime.utcnow()
                p2p_tx.failure_reason = "Escrow cancelled on-chain"
                db.session.commit()

                self._emit_event(
                    p2p_tx.buyer_id,
                    "p2p_cancelled",
                    {
                        "transaction_id": p2p_tx.transaction_id,
                        "tx_hash": tx_hash,
                    },
                )
            logger.info(
                f"P2P Escrow {p2p_escrow.escrow_id} cancelled on-chain: {tx_hash}"
            )
            return

        # Check private market deals
        try:
            from models import PrivateMarketDeal
            pm_deal = PrivateMarketDeal.query.filter_by(
                escrow_sequence=offer_sequence,
            ).filter(PrivateMarketDeal.status.in_(["escrow_funded", "disputed"])).first()

            if pm_deal:
                pm_deal.status = "cancelled"
                db.session.commit()
                logger.info(f"Private deal {pm_deal.id} escrow cancelled on-chain: {tx_hash}")

                self._emit_event(
                    pm_deal.buyer_id,
                    "deal_cancelled",
                    {
                        "deal_id": pm_deal.id,
                        "tx_hash": tx_hash,
                    },
                )
        except Exception as e:
            logger.debug(f"Private market deal cancel check skipped: {e}")

    def _process_payment(self, sender, tx_hash, dest_tag, amount):
        """Update DB when a direct payment is received."""
        from models import db, Booking
        from xrpl.utils import drops_to_xrp

        if dest_tag is None:
            return

        booking = Booking.query.filter_by(
            destination_tag=dest_tag,
            payment_status="pending",
        ).first()

        if not booking:
            return

        amount_xrp = float(drops_to_xrp(str(amount))) if isinstance(amount, (int, str)) else 0

        booking.payment_tx_hash = tx_hash
        booking.payment_verified = True
        booking.payment_verified_at = datetime.utcnow()
        booking.payment_status = "verified"
        db.session.commit()

        logger.info(
            f"Payment verified for booking {booking.id}: "
            f"{amount_xrp} XRP from {sender}"
        )

        self._emit_event(
            booking.user_id,
            "payment_verified",
            {
                "booking_id": booking.id,
                "tx_hash": tx_hash,
                "amount_xrp": amount_xrp,
            },
        )

    # ------------------------------------------------------------------
    # SSE event emission
    # ------------------------------------------------------------------

    def _emit_event(self, user_id, event_type, data):
        """Push an SSE event to the affected user."""
        try:
            from event_stream import publish_event
            publish_event(f"user:{user_id}", event_type, data)
        except Exception as e:
            logger.debug(f"Could not emit SSE event: {e}")


# Global monitor instance
ledger_monitor = LedgerMonitor()


def register_monitor_routes(app):
    """Register monitoring status endpoint."""
    from flask_login import login_required, current_user

    @app.route("/api/xrpl/monitor/status")
    @login_required
    def xrpl_monitor_status():
        if not current_user.is_admin:
            return {"error": "Admin only"}, 403
        return {
            "monitor": ledger_monitor.stats,
            "network": ledger_monitor.network,
            "wallet": ledger_monitor.wallet_address,
            "last_ledger": ledger_monitor._last_ledger_index,
        }


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    logger.info("Starting XRPL Ledger Monitor as standalone daemon")
    monitor = LedgerMonitor()
    try:
        monitor.start()
        while monitor._running:
            time.sleep(1)
    except KeyboardInterrupt:
        monitor.stop()
        logger.info("Monitor stopped")
