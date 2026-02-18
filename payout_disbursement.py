"""
MYSTES Automated RLUSD Disbursement (Build #69)

Processes pending NodePayout records by submitting XRPL Payment transactions.
Runs as a background task via tasks.py.

Flow:
    1. Query NodePayout with status='pending'
    2. Submit XRPL Payment (or simulate in dev)
    3. Update status='sent', tx_hash, sent_at
    4. Verify sent transactions → status='confirmed'
"""

import json
import logging
import os
import secrets
from datetime import datetime, timedelta
from uuid import uuid4

logger = logging.getLogger(__name__)


DUST_THRESHOLD_RLUSD = 0.0001
MAX_BATCH_SIZE = 50
MAX_RETRIES = 3


class PayoutDisbursementWorker:

    def __init__(self, treasury_address, treasury_secret, rlusd_issuer, xrpl_url):
        self.treasury_address = treasury_address
        self.treasury_secret = treasury_secret
        self.rlusd_issuer = rlusd_issuer
        self.xrpl_url = xrpl_url
        self._simulated = (treasury_secret == "SIMULATED")

    def process_pending_payouts(self, batch_size=50):
        """Process pending NodePayout records. Returns stats dict."""
        from models import db, NodePayout

        pending = (
            NodePayout.query
            .filter_by(status='pending')
            .order_by(NodePayout.id.asc())
            .limit(min(batch_size, MAX_BATCH_SIZE))
            .all()
        )

        if not pending:
            return {"processed": 0, "sent": 0, "failed": 0, "skipped": 0}

        sent = 0
        failed = 0
        skipped = 0

        for payout in pending:
            if payout.payout_amount_rlusd < DUST_THRESHOLD_RLUSD:
                payout.status = 'skipped'
                skipped += 1
                continue

            if not payout.wallet_address:
                payout.status = 'failed'
                failed += 1
                continue

            result = self._submit_payment(payout)

            if result["success"]:
                payout.status = 'sent'
                payout.tx_hash = result["tx_hash"]
                payout.paid_at = datetime.utcnow()
                sent += 1
            else:
                retry_count = getattr(payout, '_retry_count', 0) + 1
                if retry_count >= MAX_RETRIES:
                    payout.status = 'failed'
                    failed += 1
                    logger.warning(
                        "Payout %s failed after %d retries: %s",
                        payout.id, MAX_RETRIES, result.get("error"),
                    )
                else:
                    failed += 1
                    logger.warning(
                        "Payout %s attempt failed: %s", payout.id, result.get("error"),
                    )

        try:
            db.session.commit()
            logger.info(
                "Disbursement batch: %d sent, %d failed, %d skipped (of %d)",
                sent, failed, skipped, len(pending),
            )
        except Exception as exc:
            db.session.rollback()
            logger.exception("Disbursement commit failed: %s", exc)
            return {"processed": len(pending), "sent": 0, "failed": len(pending), "skipped": 0}

        return {
            "processed": len(pending),
            "sent": sent,
            "failed": failed,
            "skipped": skipped,
        }

    def _submit_payment(self, payout):
        """Submit an XRPL RLUSD payment for a single payout."""
        if self._simulated:
            tx_hash = f"SIM-{uuid4().hex[:16]}"
            logger.debug("Simulated payout %s → %s: %s RLUSD (tx=%s)",
                         payout.id, payout.wallet_address,
                         payout.payout_amount_rlusd, tx_hash)
            return {"success": True, "tx_hash": tx_hash, "error": None}

        try:
            from xrpl.clients import JsonRpcClient
            from xrpl.wallet import Wallet
            from xrpl.models.transactions import Payment
            from xrpl.models.amounts import IssuedCurrencyAmount
            from xrpl.transaction import sign, submit_and_wait

            client = JsonRpcClient(self.xrpl_url)
            wallet = Wallet.from_seed(self.treasury_secret)

            payment_tx = Payment(
                account=wallet.address,
                destination=payout.wallet_address,
                amount=IssuedCurrencyAmount(
                    currency="RLUSD",
                    issuer=self.rlusd_issuer,
                    value=str(round(payout.payout_amount_rlusd, 6)),
                ),
                destination_tag=payout.user_id,
            )
            signed_tx = sign(payment_tx, wallet)
            response = submit_and_wait(signed_tx, client)

            tx_hash = response.result.get("hash", "")
            return {"success": True, "tx_hash": tx_hash, "error": None}

        except ImportError:
            tx_hash = f"SIM-{uuid4().hex[:16]}"
            logger.warning("xrpl library not available, simulating payout %s", payout.id)
            return {"success": True, "tx_hash": tx_hash, "error": None}

        except Exception as exc:
            logger.exception("XRPL payment failed for payout %s: %s", payout.id, exc)
            return {"success": False, "tx_hash": None, "error": str(exc)[:200]}

    def verify_sent_payouts(self, batch_size=100):
        """Check 'sent' payouts for XRPL confirmation."""
        from models import db, NodePayout, NodePayoutEpoch, HelperProfile

        one_min_ago = datetime.utcnow() - timedelta(minutes=1)
        sent = (
            NodePayout.query
            .filter_by(status='sent')
            .filter(NodePayout.paid_at <= one_min_ago)
            .limit(batch_size)
            .all()
        )

        if not sent:
            return {"verified": 0, "still_pending": 0}

        verified = 0
        still_pending = 0

        for payout in sent:
            if self._simulated or (payout.tx_hash and payout.tx_hash.startswith("SIM-")):
                # Auto-confirm simulated payouts after 30 seconds
                if payout.paid_at and (datetime.utcnow() - payout.paid_at).total_seconds() >= 30:
                    payout.status = 'confirmed'
                    payout.paid_at = payout.paid_at  # keep original
                    verified += 1

                    # Update helper earnings
                    try:
                        helper = HelperProfile.query.filter_by(user_id=payout.user_id).first()
                        if helper:
                            helper.total_earned_rlusd = (
                                (helper.total_earned_rlusd or 0) + payout.payout_amount_rlusd
                            )
                    except Exception:
                        pass
                else:
                    still_pending += 1
            else:
                # Real XRPL verification
                confirmed = self._check_xrpl_confirmation(payout.tx_hash)
                if confirmed:
                    payout.status = 'confirmed'
                    verified += 1
                    try:
                        helper = HelperProfile.query.filter_by(user_id=payout.user_id).first()
                        if helper:
                            helper.total_earned_rlusd = (
                                (helper.total_earned_rlusd or 0) + payout.payout_amount_rlusd
                            )
                    except Exception:
                        pass
                else:
                    still_pending += 1

        # Check if any epochs are now fully confirmed
        if verified > 0:
            epoch_ids = set()
            for p in sent:
                if p.status == 'confirmed' and p.epoch_id:
                    epoch_ids.add(p.epoch_id)

            for eid in epoch_ids:
                remaining = NodePayout.query.filter(
                    NodePayout.epoch_id == eid,
                    NodePayout.status.notin_(['confirmed', 'skipped', 'failed']),
                ).count()
                if remaining == 0:
                    epoch = NodePayoutEpoch.query.get(eid)
                    if epoch and epoch.status != 'completed':
                        epoch.status = 'completed'
                        epoch.completed_at = datetime.utcnow()
                        logger.info("Epoch %s fully distributed", epoch.epoch_id)

        try:
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            logger.exception("Verification commit failed: %s", exc)
            return {"verified": 0, "still_pending": len(sent)}

        return {"verified": verified, "still_pending": still_pending}

    def _check_xrpl_confirmation(self, tx_hash):
        """Check XRPL ledger for transaction confirmation."""
        try:
            import requests
            resp = requests.post(self.xrpl_url, json={
                "method": "tx",
                "params": [{"transaction": tx_hash}],
            }, timeout=10)
            data = resp.json()
            result = data.get("result", {})
            return result.get("validated", False)
        except Exception as exc:
            logger.debug("XRPL tx check failed for %s: %s", tx_hash, exc)
            return False

    def get_disbursement_stats(self):
        """Return overall disbursement statistics."""
        from models import db, NodePayout, NodePayoutEpoch
        from sqlalchemy import func

        total_sent = NodePayout.query.filter(
            NodePayout.status.in_(['sent', 'confirmed'])
        ).count()
        total_confirmed = NodePayout.query.filter_by(status='confirmed').count()
        total_failed = NodePayout.query.filter_by(status='failed').count()
        pending_count = NodePayout.query.filter_by(status='pending').count()

        total_value = db.session.query(
            func.sum(NodePayout.payout_amount_rlusd)
        ).filter(
            NodePayout.status.in_(['sent', 'confirmed'])
        ).scalar() or 0

        recent = (
            NodePayout.query
            .filter(NodePayout.status.in_(['sent', 'confirmed', 'failed']))
            .order_by(NodePayout.paid_at.desc())
            .limit(20)
            .all()
        )

        epochs_total = NodePayoutEpoch.query.count()
        epochs_completed = NodePayoutEpoch.query.filter_by(status='completed').count()

        return {
            "total_sent": total_sent,
            "total_confirmed": total_confirmed,
            "total_failed": total_failed,
            "pending_count": pending_count,
            "total_value_rlusd": round(float(total_value), 6),
            "epoch_completion_rate": round(
                epochs_completed / max(epochs_total, 1) * 100, 1
            ),
            "recent_payouts": [
                {
                    "user_id": p.user_id,
                    "amount": round(p.payout_amount_rlusd, 6),
                    "status": p.status,
                    "tx_hash": p.tx_hash,
                    "paid_at": p.paid_at.isoformat() if p.paid_at else None,
                }
                for p in recent
            ],
        }

    def process_revenue_allocations(self, batch_size=50):
        """
        Process pending RevenueAllocation records — pay node shares and referral shares.
        Runs alongside process_pending_payouts() for the fee-allocation vertical.
        """
        from models import db, RevenueAllocation, User

        pending = (
            RevenueAllocation.query
            .filter_by(node_payout_status='pending')
            .order_by(RevenueAllocation.id.asc())
            .limit(batch_size)
            .all()
        )

        if not pending:
            return {"processed": 0, "node_paid": 0, "referral_paid": 0, "failed": 0}

        node_paid = 0
        referral_paid = 0
        failed = 0

        for alloc in pending:
            # --- Node share payout ---
            if alloc.node_share_usd and alloc.node_share_usd > 0:
                node_user = User.query.get(alloc.node_user_id)
                if node_user and getattr(node_user, 'xrpl_wallet_address', None):
                    # Create a lightweight payout object for _submit_payment
                    class _AllocPayout:
                        pass
                    payout_obj = _AllocPayout()
                    payout_obj.id = f"ALLOC-{alloc.allocation_id}"
                    payout_obj.wallet_address = node_user.xrpl_wallet_address
                    payout_obj.payout_amount_rlusd = alloc.node_share_usd
                    payout_obj.user_id = alloc.node_user_id

                    result = self._submit_payment(payout_obj)
                    if result["success"]:
                        alloc.node_payout_status = 'paid'
                        alloc.node_payout_tx_hash = result.get("tx_hash")
                        node_paid += 1
                    else:
                        alloc.node_payout_status = 'failed'
                        failed += 1
                else:
                    alloc.node_payout_status = 'failed'
                    failed += 1

            # --- Referral share payout ---
            if (alloc.referrer_user_id and alloc.referral_share_usd
                    and alloc.referral_share_usd > 0
                    and alloc.referrer_payout_status == 'pending'):
                ref_user = User.query.get(alloc.referrer_user_id)
                if ref_user and getattr(ref_user, 'xrpl_wallet_address', None):
                    class _RefPayout:
                        pass
                    ref_obj = _RefPayout()
                    ref_obj.id = f"REF-{alloc.allocation_id}"
                    ref_obj.wallet_address = ref_user.xrpl_wallet_address
                    ref_obj.payout_amount_rlusd = alloc.referral_share_usd
                    ref_obj.user_id = alloc.referrer_user_id

                    result = self._submit_payment(ref_obj)
                    if result["success"]:
                        alloc.referrer_payout_status = 'paid'
                        referral_paid += 1
                    else:
                        alloc.referrer_payout_status = 'failed'
                else:
                    alloc.referrer_payout_status = 'na'

        try:
            db.session.commit()
            logger.info(
                "Revenue allocation batch: %d node paid, %d referral paid, %d failed (of %d)",
                node_paid, referral_paid, failed, len(pending),
            )
        except Exception as exc:
            db.session.rollback()
            logger.exception("Revenue allocation commit failed: %s", exc)
            return {"processed": len(pending), "node_paid": 0, "referral_paid": 0, "failed": len(pending)}

        return {
            "processed": len(pending),
            "node_paid": node_paid,
            "referral_paid": referral_paid,
            "failed": failed,
        }

    def trigger_epoch_and_disburse(self, target_date=None):
        """Calculate epoch payouts + queue for disbursement."""
        from citizenserp_payouts import citizenserp_manager
        result = citizenserp_manager.calculate_epoch_payouts(target_date=target_date)
        if "error" not in result:
            logger.info("Epoch calculated: %s — now pending disbursement", result.get("epoch_id"))
        return result


# Module-level singleton
disbursement_worker = PayoutDisbursementWorker(
    treasury_address=os.environ.get("MYSTES_TREASURY_WALLET", "rTreasurySimulated"),
    treasury_secret=os.environ.get("MYSTES_TREASURY_SECRET", "SIMULATED"),
    rlusd_issuer=os.environ.get("RLUSD_ISSUER", "rRLUSDIssuerSimulated"),
    xrpl_url=os.environ.get("XRPL_URL", "https://s1.ripple.com:51234/"),
)
