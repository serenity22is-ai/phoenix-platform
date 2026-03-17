"""
MYSTES Dispute Resolution System

Handles disputes for P2P transactions where buyer or helper contests the outcome.

Dispute Flow:
    1. Buyer or helper opens dispute with reason + description
    2. Status → "opened", P2P transaction → "disputed", escrow → "disputed"
    3. Admin reviews and assigns themselves
    4. Parties exchange messages (with optional attachments)
    5. Admin resolves:
       - resolved_buyer:  Full refund to buyer from escrow
       - resolved_helper: Helper keeps funds, no refund
       - resolved_split:  Partial refund, split escrow
       - escalated:       Flagged for manual off-platform resolution

Usage:
    from dispute_resolution import dispute_manager

    # Open a dispute
    result = dispute_manager.open_dispute(
        user_id=1,
        transaction_id="P2P-abc123",
        reason="wrong_ticket",
        description="Received ticket for wrong date",
    )

    # Admin resolve
    dispute_manager.resolve(
        dispute_id="DSP-xxx",
        admin_id=99,
        resolution_type="resolved_buyer",
        notes="Confirmed wrong date on e-ticket",
        refund_amount=450.00,
    )
"""

import json
import logging
import secrets
from datetime import datetime, timedelta
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

VALID_REASONS = [
    "wrong_ticket",      # Ticket details don't match request
    "no_ticket",         # Helper never provided a ticket
    "price_mismatch",    # Actual price different from quoted
    "fraud",             # Suspected fraudulent activity
    "quality",           # Service quality issue
    "timeout",           # Transaction timed out but escrow stuck
    "other",
]

VALID_RESOLUTIONS = [
    "resolved_buyer",    # Full refund to buyer
    "resolved_helper",   # Helper keeps funds
    "resolved_split",    # Partial refund
    "escalated",         # Needs manual intervention
]


# ---------------------------------------------------------------------------
# Configuration for automated arbitration
# ---------------------------------------------------------------------------
DISPUTE_CONFIG = {
    "auto_resolve_threshold": 0.75,   # Min confidence for auto-resolution
    "escalation_amount_usd": 500,     # Amount above which always escalate
    "max_resolution_hours": 72,       # Default deadline
    "repeat_disputer_threshold": 3,   # Disputes in 90 days to flag
    "stale_dispute_hours": 24,        # Hours before auto-evaluation kicks in
}


class DisputeManager:
    """Manages the dispute lifecycle for P2P transactions."""

    def open_dispute(self, user_id, transaction_id, reason, description,
                     evidence_urls=None):
        """
        Open a new dispute on a P2P transaction.

        Args:
            user_id: ID of the user opening the dispute (buyer or helper's user).
            transaction_id: The P2PTransaction.transaction_id string.
            reason: One of VALID_REASONS.
            description: Free-text description of the issue.
            evidence_urls: Optional list of evidence file URLs.

        Returns:
            dict with dispute_id or error.
        """
        from models import db, P2PTransaction, P2PEscrow, Dispute

        if reason not in VALID_REASONS:
            return {"error": f"Invalid reason. Must be one of: {VALID_REASONS}"}

        # Find the P2P transaction
        p2p_tx = P2PTransaction.query.filter_by(transaction_id=transaction_id).first()
        if not p2p_tx:
            return {"error": "Transaction not found"}

        # Verify the user is a party to this transaction
        is_buyer = p2p_tx.buyer_id == user_id
        is_helper = False
        if p2p_tx.helper_id:
            from models import HelperProfile
            helper = HelperProfile.query.get(p2p_tx.helper_id)
            is_helper = helper and helper.user_id == user_id

        if not is_buyer and not is_helper:
            return {"error": "You are not a party to this transaction"}

        # Check if dispute already exists
        existing = Dispute.query.filter_by(
            p2p_transaction_id=p2p_tx.id,
        ).filter(Dispute.status.in_(["opened", "under_review"])).first()
        if existing:
            return {"error": "An active dispute already exists", "dispute_id": existing.dispute_id}

        # Only allow disputes on certain statuses
        disputable = {"purchasing", "confirmed", "completed", "failed"}
        if p2p_tx.status not in disputable:
            return {"error": f"Cannot dispute a transaction in '{p2p_tx.status}' status"}

        # Create dispute
        dispute_id = f"DSP-{secrets.token_hex(6).upper()}"
        dispute = Dispute(
            dispute_id=dispute_id,
            p2p_transaction_id=p2p_tx.id,
            opened_by_user_id=user_id,
            reason=reason,
            description=description,
            evidence_urls=json.dumps(evidence_urls) if evidence_urls else None,
            status="opened",
        )
        db.session.add(dispute)

        # Update transaction and escrow status
        p2p_tx.status = "disputed"
        escrow = P2PEscrow.query.filter_by(p2p_transaction_id=p2p_tx.id).first()
        if escrow and escrow.status in ("locked", "pending"):
            escrow.status = "disputed"

        db.session.commit()

        # Notify parties via SSE
        self._notify(p2p_tx.buyer_id, "dispute_opened", {
            "dispute_id": dispute_id,
            "transaction_id": transaction_id,
            "reason": reason,
            "opened_by": "buyer" if is_buyer else "helper",
        })
        if p2p_tx.helper_id:
            from models import HelperProfile
            helper = HelperProfile.query.get(p2p_tx.helper_id)
            if helper:
                self._notify(helper.user_id, "dispute_opened", {
                    "dispute_id": dispute_id,
                    "transaction_id": transaction_id,
                    "reason": reason,
                    "opened_by": "buyer" if is_buyer else "helper",
                })

        # Notify admins
        self._notify_admin("dispute_opened", {
            "dispute_id": dispute_id,
            "transaction_id": transaction_id,
            "reason": reason,
        })

        logger.info(f"Dispute {dispute_id} opened for {transaction_id} by user {user_id}")
        return {"dispute_id": dispute_id, "status": "opened"}

    def add_message(self, dispute_id, sender_id, message, attachment_url=None):
        """Add a message to a dispute thread."""
        from models import db, Dispute, DisputeMessage, User

        dispute = Dispute.query.filter_by(dispute_id=dispute_id).first()
        if not dispute:
            return {"error": "Dispute not found"}

        if dispute.status in ("resolved_buyer", "resolved_helper", "resolved_split"):
            return {"error": "Dispute is already resolved"}

        sender = User.query.get(sender_id)
        is_admin = sender and sender.is_admin

        msg = DisputeMessage(
            dispute_id=dispute.id,
            sender_id=sender_id,
            message=message,
            is_admin=is_admin,
            attachment_url=attachment_url,
        )
        db.session.add(msg)
        db.session.commit()

        return {"ok": True}

    def assign_admin(self, dispute_id, admin_id):
        """Assign an admin to review the dispute."""
        from models import db, Dispute

        dispute = Dispute.query.filter_by(dispute_id=dispute_id).first()
        if not dispute:
            return {"error": "Dispute not found"}

        dispute.assigned_admin_id = admin_id
        dispute.status = "under_review"
        dispute.updated_at = datetime.utcnow()
        db.session.commit()

        # Notify opener
        self._notify(dispute.opened_by_user_id, "dispute_under_review", {
            "dispute_id": dispute_id,
        })

        logger.info(f"Dispute {dispute_id} assigned to admin {admin_id}")
        return {"ok": True, "status": "under_review"}

    def resolve(self, dispute_id, admin_id, resolution_type, notes=None,
                refund_amount=None):
        """
        Resolve a dispute.

        Args:
            resolution_type: One of VALID_RESOLUTIONS.
            refund_amount: RLUSD amount to refund (for resolved_buyer or resolved_split).
        """
        from models import db, Dispute, P2PTransaction, P2PEscrow

        if resolution_type not in VALID_RESOLUTIONS:
            return {"error": f"Invalid resolution. Must be one of: {VALID_RESOLUTIONS}"}

        dispute = Dispute.query.filter_by(dispute_id=dispute_id).first()
        if not dispute:
            return {"error": "Dispute not found"}

        if dispute.status in ("resolved_buyer", "resolved_helper", "resolved_split"):
            return {"error": "Already resolved"}

        dispute.status = resolution_type
        dispute.resolution_type = resolution_type
        dispute.resolution_notes = notes
        dispute.refund_amount_rlusd = refund_amount
        dispute.assigned_admin_id = admin_id
        dispute.resolved_at = datetime.utcnow()
        dispute.updated_at = datetime.utcnow()

        # Update the P2P transaction based on resolution
        p2p_tx = P2PTransaction.query.get(dispute.p2p_transaction_id)
        if p2p_tx:
            if resolution_type == "resolved_buyer":
                p2p_tx.status = "cancelled"
                p2p_tx.failure_reason = f"Dispute resolved in buyer's favor: {notes or ''}"
                p2p_tx.cancelled_at = datetime.utcnow()
            elif resolution_type == "resolved_helper":
                p2p_tx.status = "completed"
                p2p_tx.completed_at = datetime.utcnow()
            elif resolution_type == "resolved_split":
                p2p_tx.status = "completed"
                p2p_tx.completed_at = datetime.utcnow()

        # Update escrow status
        escrow = P2PEscrow.query.filter_by(
            p2p_transaction_id=dispute.p2p_transaction_id
        ).first()
        if escrow and escrow.status == "disputed":
            if resolution_type == "resolved_buyer":
                escrow.status = "cancelled"
                escrow.cancelled_at = datetime.utcnow()
            elif resolution_type in ("resolved_helper", "resolved_split"):
                escrow.status = "released"
                escrow.released_at = datetime.utcnow()

        db.session.commit()

        # Notify both parties
        event_data = {
            "dispute_id": dispute_id,
            "resolution": resolution_type,
            "refund_amount": refund_amount,
        }
        if p2p_tx:
            self._notify(p2p_tx.buyer_id, "dispute_resolved", event_data)
            if p2p_tx.helper_id:
                from models import HelperProfile
                helper = HelperProfile.query.get(p2p_tx.helper_id)
                if helper:
                    self._notify(helper.user_id, "dispute_resolved", event_data)

        logger.info(
            f"Dispute {dispute_id} resolved: {resolution_type} "
            f"(refund={refund_amount})"
        )
        return {"ok": True, "resolution": resolution_type}

    def get_dispute(self, dispute_id):
        """Get dispute details with messages."""
        from models import Dispute

        dispute = Dispute.query.filter_by(dispute_id=dispute_id).first()
        if not dispute:
            return None

        data = dispute.to_dict()
        data["messages"] = [m.to_dict() for m in dispute.messages]
        return data

    def list_disputes(self, status=None, user_id=None, limit=50):
        """List disputes with optional filters."""
        from models import Dispute

        query = Dispute.query

        if status:
            query = query.filter_by(status=status)
        if user_id:
            query = query.filter_by(opened_by_user_id=user_id)

        disputes = (
            query
            .order_by(Dispute.created_at.desc())
            .limit(limit)
            .all()
        )
        return [d.to_dict() for d in disputes]

    # -------------------------------------------------------------------------
    # Automated Arbitration Logic
    # -------------------------------------------------------------------------

    def auto_evaluate(self, dispute_id) -> dict:
        """
        Automated dispute evaluation engine.

        Scores a dispute based on weighted evidence factors and returns a
        recommendation (auto_resolve_buyer, auto_resolve_helper, needs_review,
        or escalate) along with confidence scores.

        Returns:
            dict with recommendation, buyer_confidence, helper_confidence,
            factors breakdown, and dispute_id.
        """
        from models import (
            db, Dispute, P2PTransaction, P2PEscrow, HelperProfile,
        )

        try:
            dispute = Dispute.query.filter_by(dispute_id=dispute_id).first()
            if not dispute:
                return {"error": "Dispute not found"}

            p2p_tx = P2PTransaction.query.get(dispute.p2p_transaction_id)
            if not p2p_tx:
                return {"error": "Associated transaction not found"}

            escrow = P2PEscrow.query.filter_by(
                p2p_transaction_id=p2p_tx.id,
            ).first()

            factors = {}

            # --- timeout_score ---
            # If the transaction was in failed/timeout status before the
            # dispute was opened, it is a strong indicator for the buyer.
            if p2p_tx.failure_reason and any(
                kw in (p2p_tx.failure_reason or "").lower()
                for kw in ("timeout", "timed out", "failed")
            ):
                factors["timeout_score"] = 0.8
            else:
                factors["timeout_score"] = 0.0

            # --- evidence_score ---
            evidence_urls = []
            if dispute.evidence_urls:
                try:
                    evidence_urls = json.loads(dispute.evidence_urls)
                except (json.JSONDecodeError, TypeError):
                    evidence_urls = []
            evidence_count = len(evidence_urls) if isinstance(evidence_urls, list) else 0
            factors["evidence_score"] = min(evidence_count * 0.2, 0.6)

            # --- history_score ---
            # Frequent disputers (>3 disputes in 90 days) lose credibility.
            ninety_days_ago = datetime.utcnow() - timedelta(days=90)
            recent_disputes = Dispute.query.filter(
                Dispute.opened_by_user_id == dispute.opened_by_user_id,
                Dispute.created_at >= ninety_days_ago,
            ).count()
            if recent_disputes > 3:
                factors["history_score"] = -0.3
            else:
                factors["history_score"] = 0.0

            # --- helper_score ---
            helper_buyer_boost = 0.0
            if p2p_tx.helper_id:
                helper = HelperProfile.query.get(p2p_tx.helper_id)
                if helper:
                    avg_rating = getattr(helper, "avg_rating", None) or getattr(
                        helper, "rating", None
                    )
                    if avg_rating is not None and float(avg_rating) < 3.0:
                        helper_buyer_boost = 0.3
            factors["helper_score"] = helper_buyer_boost

            # --- amount_score ---
            tx_amount = float(p2p_tx.total_rlusd or p2p_tx.amount_rlusd or 0)
            factors["amount_score"] = tx_amount  # stored for threshold check

            # --- timing_score ---
            if dispute.created_at and p2p_tx.created_at:
                delta = dispute.created_at - p2p_tx.created_at
                delta_hours = delta.total_seconds() / 3600
                if delta_hours <= 1:
                    factors["timing_score"] = 0.2
                elif delta_hours >= 72:
                    factors["timing_score"] = -0.2
                else:
                    factors["timing_score"] = 0.0
            else:
                factors["timing_score"] = 0.0

            # --- combine scores ---
            buyer_confidence = max(0.0, min(1.0, (
                factors["timeout_score"]
                + factors["evidence_score"]
                + factors["history_score"]
                + factors["helper_score"]
                + factors["timing_score"]
            )))
            # Helper confidence is roughly the inverse (what's not in
            # buyer's favor defaults to helper's favor).
            helper_confidence = max(0.0, min(1.0, 1.0 - buyer_confidence))

            # --- recommendation ---
            threshold = DISPUTE_CONFIG["auto_resolve_threshold"]
            if tx_amount > DISPUTE_CONFIG["escalation_amount_usd"]:
                recommendation = "escalate"
            elif dispute.reason == "fraud":
                recommendation = "escalate"
            elif buyer_confidence >= threshold:
                recommendation = "auto_resolve_buyer"
            elif helper_confidence >= threshold:
                recommendation = "auto_resolve_helper"
            else:
                recommendation = "needs_review"

            result = {
                "recommendation": recommendation,
                "buyer_confidence": round(buyer_confidence, 3),
                "helper_confidence": round(helper_confidence, 3),
                "factors": factors,
                "dispute_id": dispute_id,
            }
            logger.info(
                f"Auto-evaluate {dispute_id}: {recommendation} "
                f"(buyer={buyer_confidence:.3f}, helper={helper_confidence:.3f})"
            )
            return result

        except Exception as exc:
            logger.exception(f"auto_evaluate failed for {dispute_id}: {exc}")
            return {"error": str(exc), "dispute_id": dispute_id}

    def auto_resolve(self, dispute_id) -> dict:
        """
        Execute automatic resolution if evaluation confidence is high enough.

        Calls auto_evaluate first, then resolves or escalates based on the
        recommendation.

        Returns:
            dict with resolution outcome.
        """
        from models import db, Dispute, P2PEscrow

        try:
            evaluation = self.auto_evaluate(dispute_id)
            if "error" in evaluation:
                return evaluation

            recommendation = evaluation["recommendation"]
            logger.info(
                f"Auto-resolve {dispute_id}: recommendation={recommendation}"
            )

            if recommendation == "auto_resolve_buyer":
                # Determine full escrow amount for refund
                dispute = Dispute.query.filter_by(dispute_id=dispute_id).first()
                refund_amount = None
                if dispute:
                    escrow = P2PEscrow.query.filter_by(
                        p2p_transaction_id=dispute.p2p_transaction_id,
                    ).first()
                    if escrow:
                        refund_amount = float(
                            escrow.amount_rlusd or escrow.amount or 0
                        )

                result = self.resolve(
                    dispute_id,
                    admin_id=0,
                    resolution_type="resolved_buyer",
                    notes="Auto-resolved: system evaluation favored buyer",
                    refund_amount=refund_amount,
                )
                result["auto"] = True
                result["evaluation"] = evaluation
                logger.info(f"Auto-resolved {dispute_id} in buyer's favor")
                return result

            elif recommendation == "auto_resolve_helper":
                result = self.resolve(
                    dispute_id,
                    admin_id=0,
                    resolution_type="resolved_helper",
                    notes="Auto-resolved: system evaluation favored helper",
                )
                result["auto"] = True
                result["evaluation"] = evaluation
                logger.info(f"Auto-resolved {dispute_id} in helper's favor")
                return result

            else:
                # needs_review or escalate — assign to admin pool
                self.assign_admin(dispute_id, admin_id=0)
                logger.info(
                    f"Dispute {dispute_id} escalated to admin pool "
                    f"(recommendation={recommendation})"
                )
                return {
                    "status": "escalated_to_admin",
                    "recommendation": recommendation,
                    "confidence": {
                        "buyer": evaluation["buyer_confidence"],
                        "helper": evaluation["helper_confidence"],
                    },
                    "dispute_id": dispute_id,
                }

        except Exception as exc:
            logger.exception(f"auto_resolve failed for {dispute_id}: {exc}")
            return {"error": str(exc), "dispute_id": dispute_id}

    def check_auto_resolvable(self) -> List[dict]:
        """
        Batch check: find all opened disputes older than the configured stale
        threshold (default 24 hours) that have not been reviewed, then run
        auto_resolve on each.

        Returns:
            List of auto_resolve result dicts.
        """
        from models import Dispute

        try:
            stale_hours = DISPUTE_CONFIG["stale_dispute_hours"]
            cutoff = datetime.utcnow() - timedelta(hours=stale_hours)

            stale_disputes = Dispute.query.filter(
                Dispute.status == "opened",
                Dispute.created_at < cutoff,
            ).all()

            results = []
            for dispute in stale_disputes:
                logger.info(
                    f"Auto-evaluating stale dispute {dispute.dispute_id}"
                )
                result = self.auto_resolve(dispute.dispute_id)
                result["dispute_id"] = dispute.dispute_id
                results.append(result)

            logger.info(
                f"check_auto_resolvable processed {len(results)} disputes"
            )
            return results

        except Exception as exc:
            logger.exception(f"check_auto_resolvable failed: {exc}")
            return [{"error": str(exc)}]

    def get_dispute_analytics(self, days_back: int = 30) -> dict:
        """
        Dispute analytics dashboard data.

        Returns:
            dict with totals by reason/resolution, average resolution time,
            auto vs manual counts, dispute rate, top routes, and repeat
            disputers.
        """
        from models import db, Dispute, P2PTransaction

        try:
            cutoff = datetime.utcnow() - timedelta(days=days_back)

            disputes = Dispute.query.filter(
                Dispute.created_at >= cutoff,
            ).all()

            total = len(disputes)
            by_reason: Dict[str, int] = {}
            by_resolution: Dict[str, int] = {}
            resolution_times: List[float] = []
            auto_resolved = 0
            manual_resolved = 0
            user_dispute_counts: Dict[int, int] = {}

            for d in disputes:
                # By reason
                by_reason[d.reason] = by_reason.get(d.reason, 0) + 1

                # By resolution
                if d.resolution_type:
                    by_resolution[d.resolution_type] = (
                        by_resolution.get(d.resolution_type, 0) + 1
                    )

                # Resolution time
                if d.resolved_at and d.created_at:
                    delta = (d.resolved_at - d.created_at).total_seconds()
                    resolution_times.append(delta / 3600)  # hours

                # Auto vs manual
                if d.resolved_at:
                    if d.assigned_admin_id == 0:
                        auto_resolved += 1
                    else:
                        manual_resolved += 1

                # Per-user counts
                uid = d.opened_by_user_id
                user_dispute_counts[uid] = user_dispute_counts.get(uid, 0) + 1

            avg_resolution_hours = (
                round(sum(resolution_times) / len(resolution_times), 2)
                if resolution_times else None
            )

            # Dispute rate = disputes / total P2P transactions in the period
            total_p2p = P2PTransaction.query.filter(
                P2PTransaction.created_at >= cutoff,
            ).count()
            dispute_rate = (
                round(total / total_p2p, 4) if total_p2p > 0 else None
            )

            # Top disputed routes/markets
            route_counts: Dict[str, int] = {}
            for d in disputes:
                tx = P2PTransaction.query.get(d.p2p_transaction_id)
                if tx:
                    route_key = getattr(tx, "route", None) or getattr(
                        tx, "market", None
                    ) or "unknown"
                    route_counts[route_key] = route_counts.get(route_key, 0) + 1
            top_routes = sorted(
                route_counts.items(), key=lambda x: x[1], reverse=True
            )[:10]

            # Repeat disputers (>2 disputes)
            repeat_disputers = [
                {"user_id": uid, "count": cnt}
                for uid, cnt in user_dispute_counts.items()
                if cnt > 2
            ]

            return {
                "period_days": days_back,
                "total_disputes": total,
                "by_reason": by_reason,
                "by_resolution": by_resolution,
                "avg_resolution_hours": avg_resolution_hours,
                "auto_resolved": auto_resolved,
                "manual_resolved": manual_resolved,
                "dispute_rate": dispute_rate,
                "top_routes": top_routes,
                "repeat_disputers": repeat_disputers,
            }

        except Exception as exc:
            logger.exception(f"get_dispute_analytics failed: {exc}")
            return {"error": str(exc)}

    def add_evidence(self, dispute_id, user_id, evidence_type, evidence_url,
                     description="") -> dict:
        """
        Add evidence to an open dispute.

        Args:
            dispute_id: The dispute's public ID.
            user_id: ID of the user submitting evidence.
            evidence_type: One of "screenshot", "email", "receipt",
                           "conversation", "other".
            evidence_url: URL/path of the evidence file.
            description: Optional description of what the evidence shows.

        Returns:
            dict with ok or error.
        """
        from models import db, Dispute, DisputeMessage

        valid_evidence_types = {
            "screenshot", "email", "receipt", "conversation", "other",
        }
        if evidence_type not in valid_evidence_types:
            return {
                "error": (
                    f"Invalid evidence type. Must be one of: "
                    f"{sorted(valid_evidence_types)}"
                )
            }

        try:
            dispute = Dispute.query.filter_by(dispute_id=dispute_id).first()
            if not dispute:
                return {"error": "Dispute not found"}

            if dispute.status in (
                "resolved_buyer", "resolved_helper", "resolved_split",
            ):
                return {"error": "Cannot add evidence to a resolved dispute"}

            # Store as a DisputeMessage with attachment
            msg_text = (
                f"[Evidence: {evidence_type}] {description}"
                if description
                else f"[Evidence: {evidence_type}]"
            )
            msg = DisputeMessage(
                dispute_id=dispute.id,
                sender_id=user_id,
                message=msg_text,
                is_admin=False,
                attachment_url=evidence_url,
            )
            db.session.add(msg)

            # Update evidence_urls JSON array on the dispute
            existing_urls = []
            if dispute.evidence_urls:
                try:
                    existing_urls = json.loads(dispute.evidence_urls)
                except (json.JSONDecodeError, TypeError):
                    existing_urls = []
            if not isinstance(existing_urls, list):
                existing_urls = []
            existing_urls.append(evidence_url)
            dispute.evidence_urls = json.dumps(existing_urls)
            dispute.updated_at = datetime.utcnow()

            db.session.commit()

            logger.info(
                f"Evidence added to {dispute_id} by user {user_id}: "
                f"{evidence_type}"
            )
            return {"ok": True}

        except Exception as exc:
            logger.exception(
                f"add_evidence failed for {dispute_id}: {exc}"
            )
            return {"error": str(exc)}

    def set_deadline(self, dispute_id, hours: int = 72) -> dict:
        """
        Set a resolution deadline on a dispute.

        If the deadline passes without resolution, the system will auto-resolve
        in the buyer's favor (escrow protection principle).

        Args:
            dispute_id: The dispute's public ID.
            hours: Number of hours until the deadline (default 72).

        Returns:
            dict with ok and the deadline ISO timestamp.
        """
        from models import db, Dispute

        try:
            dispute = Dispute.query.filter_by(dispute_id=dispute_id).first()
            if not dispute:
                return {"error": "Dispute not found"}

            if dispute.status in (
                "resolved_buyer", "resolved_helper", "resolved_split",
            ):
                return {"error": "Dispute is already resolved"}

            deadline = datetime.utcnow() + timedelta(hours=hours)
            deadline_iso = deadline.isoformat() + "Z"

            # Store deadline in resolution_notes as structured prefix so it
            # can be parsed later without requiring a schema migration.
            existing_notes = dispute.resolution_notes or ""
            deadline_tag = f"[DEADLINE:{deadline_iso}]"
            # Replace any existing deadline tag
            if "[DEADLINE:" in existing_notes:
                import re
                existing_notes = re.sub(
                    r"\[DEADLINE:[^\]]+\]\s*", "", existing_notes
                )
            dispute.resolution_notes = f"{deadline_tag} {existing_notes}".strip()
            dispute.updated_at = datetime.utcnow()

            db.session.commit()

            logger.info(
                f"Deadline set for {dispute_id}: {deadline_iso} "
                f"({hours} hours)"
            )
            return {"ok": True, "deadline": deadline_iso}

        except Exception as exc:
            logger.exception(
                f"set_deadline failed for {dispute_id}: {exc}"
            )
            return {"error": str(exc)}

    def _notify(self, user_id, event_type, data):
        """Push SSE event."""
        try:
            from event_stream import publish_event
            publish_event(f"user:{user_id}", event_type, data)
        except Exception:
            pass

    def _notify_admin(self, event_type, data):
        """Push SSE event to admin channel."""
        try:
            from event_stream import publish_event
            publish_event("admin", event_type, data)
        except Exception:
            pass


# Global dispute manager instance
dispute_manager = DisputeManager()
