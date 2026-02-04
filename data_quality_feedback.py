"""
PHOENIX Data Quality Feedback Engine (Build #69)

Allows commercial data buyers to rate the quality of browsing data records.
Feedback adjusts node-level quality baselines so future events from nodes
with consistently good/bad data are scored accordingly.

Flow:
    Buyer rates events via API -> feedback stored -> node scores adjusted
    -> future events from that node get quality bonus/penalty
"""

import logging
import threading
import uuid
from datetime import datetime, timedelta

from sqlalchemy import func

logger = logging.getLogger(__name__)


class DataQualityFeedbackEngine:
    """
    Core engine for processing buyer quality feedback on browsing data.

    Maintains an in-memory cache of per-node quality adjustments that get
    recalculated whenever new feedback arrives.  Adjustments range from
    -20 (consistently poor) to +20 (consistently good) and are intended
    to be applied as a bonus/penalty to future BrowsingEvent.quality_score
    values for the corresponding node.
    """

    VALID_RATINGS = {"good", "neutral", "poor"}
    MAX_ADJUSTMENT = 20
    RECALC_WINDOW_DAYS = 30

    def __init__(self):
        # node_id -> quality_adjustment (int, -20..+20)
        self._node_adjustments = {}
        # node_id -> {"positive": N, "negative": N, "neutral": N}
        self._feedback_counts = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def submit_feedback(self, account_id, feedbacks):
        """
        Process a batch of quality feedback from a commercial buyer.

        Args:
            account_id: The commercial account submitting feedback.
            feedbacks: List of dicts, each with:
                - event_id (str): The BrowsingEvent.event_id being rated.
                - rating (str): One of "good", "neutral", "poor".
                - comment (str|None): Optional free-text comment.

        Returns:
            dict with keys processed, skipped, node_adjustments_updated.
        """
        from models import db, BrowsingEvent, DataQualityFeedback

        processed = 0
        skipped = 0
        affected_node_ids = set()

        for item in feedbacks:
            event_id = item.get("event_id")
            rating = item.get("rating")
            comment = item.get("comment")

            # Validate rating
            if rating not in self.VALID_RATINGS:
                skipped += 1
                continue

            # Look up the event
            event = BrowsingEvent.query.filter_by(event_id=event_id).first()
            if event is None:
                skipped += 1
                continue

            # Create feedback record
            feedback_record = DataQualityFeedback(
                feedback_id=f"dqf_{uuid.uuid4().hex[:16]}",
                event_id=event.event_id,
                account_id=account_id,
                node_id=event.node_id,
                rating=rating,
                comment=comment,
                created_at=datetime.utcnow(),
            )
            db.session.add(feedback_record)
            processed += 1

            if event.node_id:
                affected_node_ids.add(event.node_id)

        # Commit all feedback records
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            logger.exception("Failed to commit quality feedback batch")
            return {"processed": 0, "skipped": len(feedbacks), "node_adjustments_updated": 0}

        # Recalculate adjustments for affected nodes
        updated = 0
        if affected_node_ids:
            updated = self._recalculate_node_adjustments(affected_node_ids)

        logger.info(
            "Quality feedback: processed=%d skipped=%d nodes_updated=%d account=%s",
            processed, skipped, updated, account_id,
        )

        return {
            "processed": processed,
            "skipped": skipped,
            "node_adjustments_updated": updated,
        }

    def get_node_adjustment(self, node_id):
        """
        Return the current quality adjustment for a node.

        Returns:
            int in range [-20, +20], default 0 if no feedback exists.
        """
        return self._node_adjustments.get(node_id, 0)

    def get_feedback_stats(self, account_id=None, days_back=30):
        """
        Return aggregate feedback statistics.

        Args:
            account_id: If provided, filter to this buyer's feedback only.
            days_back: Number of days to look back (default 30).

        Returns:
            dict with total, by_rating, by_node, top_rated_nodes,
            worst_rated_nodes.
        """
        from models import db, DataQualityFeedback, BrowsingEvent

        cutoff = datetime.utcnow() - timedelta(days=days_back)

        base_query = DataQualityFeedback.query.filter(
            DataQualityFeedback.created_at >= cutoff
        )
        if account_id is not None:
            base_query = base_query.filter(
                DataQualityFeedback.account_id == account_id
            )

        total = base_query.count()

        # Breakdown by rating
        rating_counts = (
            db.session.query(
                DataQualityFeedback.rating,
                func.count(DataQualityFeedback.id),
            )
            .filter(DataQualityFeedback.created_at >= cutoff)
        )
        if account_id is not None:
            rating_counts = rating_counts.filter(
                DataQualityFeedback.account_id == account_id
            )
        rating_counts = rating_counts.group_by(DataQualityFeedback.rating).all()
        by_rating = {r: c for r, c in rating_counts}

        # Breakdown by node
        node_counts = (
            db.session.query(
                DataQualityFeedback.node_id,
                func.count(DataQualityFeedback.id),
            )
            .filter(
                DataQualityFeedback.created_at >= cutoff,
                DataQualityFeedback.node_id.isnot(None),
            )
        )
        if account_id is not None:
            node_counts = node_counts.filter(
                DataQualityFeedback.account_id == account_id
            )
        node_counts = node_counts.group_by(DataQualityFeedback.node_id).all()
        by_node = {n: c for n, c in node_counts}

        # Top-rated nodes (highest good-rate)
        top_rated = self._get_ranked_nodes(cutoff, account_id, best=True)
        worst_rated = self._get_ranked_nodes(cutoff, account_id, best=False)

        return {
            "days_back": days_back,
            "total_feedbacks": total,
            "by_rating": by_rating,
            "by_node": by_node,
            "top_rated_nodes": top_rated,
            "worst_rated_nodes": worst_rated,
        }

    def get_node_quality_report(self, node_id, days_back=30):
        """
        Detailed quality report for a specific node.

        Args:
            node_id: The node identifier.
            days_back: Number of days to look back.

        Returns:
            dict with feedback_breakdown, current_adjustment, recent_comments.
        """
        from models import db, DataQualityFeedback

        cutoff = datetime.utcnow() - timedelta(days=days_back)

        base = DataQualityFeedback.query.filter(
            DataQualityFeedback.node_id == node_id,
            DataQualityFeedback.created_at >= cutoff,
        )

        total = base.count()

        # Rating breakdown
        rating_rows = (
            db.session.query(
                DataQualityFeedback.rating,
                func.count(DataQualityFeedback.id),
            )
            .filter(
                DataQualityFeedback.node_id == node_id,
                DataQualityFeedback.created_at >= cutoff,
            )
            .group_by(DataQualityFeedback.rating)
            .all()
        )
        breakdown = {r: c for r, c in rating_rows}

        # Positive rate
        good_count = breakdown.get("good", 0)
        positive_rate = round(good_count / total, 4) if total > 0 else 0.0

        # Current adjustment
        adjustment = self.get_node_adjustment(node_id)

        # Recent comments (last 20)
        recent_comments = (
            DataQualityFeedback.query
            .filter(
                DataQualityFeedback.node_id == node_id,
                DataQualityFeedback.created_at >= cutoff,
                DataQualityFeedback.comment.isnot(None),
                DataQualityFeedback.comment != "",
            )
            .order_by(DataQualityFeedback.created_at.desc())
            .limit(20)
            .all()
        )

        comments_list = [
            {
                "feedback_id": fb.feedback_id,
                "rating": fb.rating,
                "comment": fb.comment,
                "created_at": fb.created_at.isoformat() if fb.created_at else None,
            }
            for fb in recent_comments
        ]

        return {
            "node_id": node_id,
            "days_back": days_back,
            "total_feedbacks": total,
            "feedback_breakdown": breakdown,
            "positive_rate": positive_rate,
            "current_adjustment": adjustment,
            "recent_comments": comments_list,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _recalculate_node_adjustments(self, node_ids):
        """
        Recalculate quality adjustments for the given set of nodes.

        For each node, queries all feedback from the last 30 days and
        computes:
            positive_rate = good_count / total_count
            adjustment = (positive_rate - 0.5) * 40   # range [-20, +20]

        Thread-safe — acquires self._lock before modifying caches.

        Args:
            node_ids: iterable of node_id strings.

        Returns:
            int — number of nodes whose adjustment was updated.
        """
        from models import db, DataQualityFeedback

        cutoff = datetime.utcnow() - timedelta(days=self.RECALC_WINDOW_DAYS)
        updated = 0

        for node_id in node_ids:
            # Query feedback counts per rating for this node
            rows = (
                db.session.query(
                    DataQualityFeedback.rating,
                    func.count(DataQualityFeedback.id),
                )
                .filter(
                    DataQualityFeedback.node_id == node_id,
                    DataQualityFeedback.created_at >= cutoff,
                )
                .group_by(DataQualityFeedback.rating)
                .all()
            )

            counts = {r: c for r, c in rows}
            good_count = counts.get("good", 0)
            neutral_count = counts.get("neutral", 0)
            poor_count = counts.get("poor", 0)
            total_count = good_count + neutral_count + poor_count

            if total_count == 0:
                continue

            positive_rate = good_count / total_count
            adjustment = int(round((positive_rate - 0.5) * 40))
            # Clamp to [-20, +20]
            adjustment = max(-self.MAX_ADJUSTMENT, min(self.MAX_ADJUSTMENT, adjustment))

            with self._lock:
                self._node_adjustments[node_id] = adjustment
                self._feedback_counts[node_id] = {
                    "positive": good_count,
                    "negative": poor_count,
                    "neutral": neutral_count,
                }

            updated += 1

        return updated

    def _get_ranked_nodes(self, cutoff, account_id, best=True, limit=10):
        """
        Return the top or bottom ranked nodes by positive feedback rate.

        Args:
            cutoff: datetime — only consider feedback after this time.
            account_id: filter to this buyer, or None for all.
            best: if True return highest-rated, else lowest-rated.
            limit: max nodes to return.

        Returns:
            list of dicts with node_id, total, good_count, positive_rate.
        """
        from models import db, DataQualityFeedback

        # Get all (node_id, rating, count) tuples
        q = (
            db.session.query(
                DataQualityFeedback.node_id,
                DataQualityFeedback.rating,
                func.count(DataQualityFeedback.id),
            )
            .filter(
                DataQualityFeedback.created_at >= cutoff,
                DataQualityFeedback.node_id.isnot(None),
            )
        )
        if account_id is not None:
            q = q.filter(DataQualityFeedback.account_id == account_id)

        q = q.group_by(DataQualityFeedback.node_id, DataQualityFeedback.rating)
        rows = q.all()

        # Aggregate per node
        node_data = {}
        for node_id, rating, count in rows:
            if node_id not in node_data:
                node_data[node_id] = {"good": 0, "neutral": 0, "poor": 0, "total": 0}
            node_data[node_id][rating] = count
            node_data[node_id]["total"] += count

        # Compute positive rate and sort
        ranked = []
        for node_id, data in node_data.items():
            total = data["total"]
            if total < 3:
                continue  # Skip nodes with very few feedbacks
            good_count = data["good"]
            positive_rate = round(good_count / total, 4)
            ranked.append({
                "node_id": node_id,
                "total_feedbacks": total,
                "good_count": good_count,
                "positive_rate": positive_rate,
            })

        ranked.sort(key=lambda x: x["positive_rate"], reverse=best)
        return ranked[:limit]


# Module-level singleton
quality_feedback_engine = DataQualityFeedbackEngine()
