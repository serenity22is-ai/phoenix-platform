"""
Node Yield Dashboard — Phoenix Platform
========================================

Provides per-node earnings visibility for CitizenSERP residential node operators.
Each node in the network runs tasks (flight searches, ad extraction, etc.), extracts
data across multiple categories, and earns RLUSD payouts proportional to their
contribution.

This module reads from NodeDataExtraction, NodePayout, NodeSession, and
NodePayoutEpoch to build a comprehensive yield picture including:

- Earnings breakdown by data category
- Real-time yield rates
- Extraction volume metrics
- Historical trends (daily, weekly)
- A yield optimizer that suggests additional data categories to increase earnings

Usage:
    from node_yield_dashboard import yield_dashboard

    summary = yield_dashboard.get_yield_summary(user_id=42)
    history = yield_dashboard.get_yield_history(user_id=42, days_back=30)
    breakdown = yield_dashboard.get_category_breakdown(user_id=42)
    optimization = yield_dashboard.get_yield_optimization(user_id=42)

    # Called internally by TaskDispatcher on task completion:
    record = yield_dashboard.record_extraction(
        user_id=42, session_id=10, task_id="TASK-abc",
        task_type="flight_search", records_extracted=150,
        data_points=3200, data_size_bytes=48000, quality_score=85
    )
"""

import json
import logging
import math
import os
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DATA_CATEGORY_VALUES = {
    "flight_pricing": {"base_value_usd": 0.002, "display_name": "Flight Pricing"},
    "hotel_pricing": {"base_value_usd": 0.002, "display_name": "Hotel Pricing"},
    "product_pricing": {"base_value_usd": 0.001, "display_name": "Product Pricing"},
    "ad_intelligence": {"base_value_usd": 0.005, "display_name": "Ad Intelligence"},
    "social_signals": {"base_value_usd": 0.003, "display_name": "Social Signals"},
    "audience_data": {"base_value_usd": 0.004, "display_name": "Audience Data"},
    "retail_shelf": {"base_value_usd": 0.003, "display_name": "Retail Shelf Data"},
    "competitor_ads": {"base_value_usd": 0.008, "display_name": "Competitor Ad Tracking"},
    "deep_pricing": {"base_value_usd": 0.004, "display_name": "Deep Pricing Intelligence"},
    "search_results": {"base_value_usd": 0.001, "display_name": "Search Results"},
    "browsing_data": {"base_value_usd": 0.0001, "display_name": "Browsing Data"},
}

TASK_CATEGORY_MAP = {
    "flight_search": "flight_pricing",
    "hotel_search": "hotel_pricing",
    "product_search": "product_pricing",
    "ecommerce_search": "product_pricing",
    "cruise_search": "flight_pricing",
    "digital_search": "product_pricing",
    "marketplace_browse": "product_pricing",
    "search_engine_extract": "search_results",
    "price_monitor": "product_pricing",
    "general_search": "search_results",
    "ad_intelligence": "ad_intelligence",
    "pricing_intelligence_deep": "deep_pricing",
    "social_signal_extract": "social_signals",
    "audience_profile_extract": "audience_data",
    "retail_shelf_monitor": "retail_shelf",
    "competitor_ad_track": "competitor_ads",
    "page_visit": "browsing_data",
    "ad_impression": "ad_intelligence",
    "price_observation": "product_pricing",
    "social_signal": "social_signals",
    "search_query": "search_results",
}


# ---------------------------------------------------------------------------
# Dashboard class
# ---------------------------------------------------------------------------

class NodeYieldDashboard:
    """Aggregates node yield data across payouts, extractions, and sessions
    to provide operators with a comprehensive earnings picture and
    optimisation suggestions."""

    def __init__(self):
        self.logger = logging.getLogger("phoenix.node_yield_dashboard")

    # ------------------------------------------------------------------
    # 1. Yield Summary
    # ------------------------------------------------------------------

    def get_yield_summary(self, user_id: int) -> Dict:
        """Return current yield summary for a node operator.

        Includes today/week/month/total earnings, current hourly rate,
        task counts, active categories, and a composite yield score.
        """
        from models import db, NodeDataExtraction, NodeSession, NodePayout, NodePayoutEpoch
        from sqlalchemy import func

        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = today_start - timedelta(days=7)
        month_start = today_start - timedelta(days=30)

        # Active session check
        active_session = (
            NodeSession.query
            .filter_by(user_id=user_id, status="active")
            .first()
        )
        is_online = active_session is not None

        # --- Earnings windows ---------------------------------------------------

        def _sum_payouts(since=None, status_filter=None):
            q = db.session.query(func.coalesce(func.sum(NodePayout.payout_amount_rlusd), 0.0))
            q = q.filter(NodePayout.user_id == user_id)
            if since is not None:
                q = q.filter(NodePayout.created_at >= since)
            if status_filter is not None:
                q = q.filter(NodePayout.status == status_filter)
            return float(q.scalar())

        earnings_today = _sum_payouts(since=today_start)
        earnings_this_week = _sum_payouts(since=week_start)
        earnings_this_month = _sum_payouts(since=month_start)
        earnings_total = _sum_payouts(status_filter="confirmed")

        # --- Current rate per hour from latest epoch ----------------------------

        latest_epoch = (
            NodePayoutEpoch.query
            .order_by(NodePayoutEpoch.created_at.desc())
            .first()
        )
        current_rate_per_hour = latest_epoch.rate_per_hour_usd if latest_epoch else 0.0

        # --- Today's extraction metrics -----------------------------------------

        tasks_completed_today = (
            db.session.query(func.count(NodeDataExtraction.id))
            .filter(
                NodeDataExtraction.user_id == user_id,
                NodeDataExtraction.created_at >= today_start,
            )
            .scalar()
        ) or 0

        data_points_extracted_today = (
            db.session.query(func.coalesce(func.sum(NodeDataExtraction.data_points), 0))
            .filter(
                NodeDataExtraction.user_id == user_id,
                NodeDataExtraction.created_at >= today_start,
            )
            .scalar()
        ) or 0

        # --- Active data categories (last 7 days) ------------------------------

        active_cats_rows = (
            db.session.query(NodeDataExtraction.data_category)
            .filter(
                NodeDataExtraction.user_id == user_id,
                NodeDataExtraction.created_at >= week_start,
            )
            .distinct()
            .all()
        )
        active_data_categories = [r[0] for r in active_cats_rows if r[0]]

        # --- Yield score (0-100) ------------------------------------------------
        # 30 % uptime consistency  — fraction of last 30 days with at least one session
        session_days = (
            db.session.query(func.date(NodeSession.start_time))
            .filter(
                NodeSession.user_id == user_id,
                NodeSession.start_time >= month_start,
            )
            .distinct()
            .count()
        )
        uptime_score = min(session_days / 30.0, 1.0) * 100

        # 30 % data diversity — fraction of all 10 categories the user has touched
        diversity_score = (len(active_data_categories) / len(DATA_CATEGORY_VALUES)) * 100

        # 20 % quality — avg quality_score across last 30 days
        avg_quality = (
            db.session.query(func.coalesce(func.avg(NodeDataExtraction.quality_score), 50))
            .filter(
                NodeDataExtraction.user_id == user_id,
                NodeDataExtraction.created_at >= month_start,
            )
            .scalar()
        ) or 50
        quality_component = float(avg_quality)

        # 20 % volume — tasks last 30d relative to benchmark of 500 tasks/month
        tasks_month = (
            db.session.query(func.count(NodeDataExtraction.id))
            .filter(
                NodeDataExtraction.user_id == user_id,
                NodeDataExtraction.created_at >= month_start,
            )
            .scalar()
        ) or 0
        volume_score = min(tasks_month / 500.0, 1.0) * 100

        yield_score = round(
            0.30 * uptime_score
            + 0.30 * diversity_score
            + 0.20 * quality_component
            + 0.20 * volume_score
        )
        yield_score = max(0, min(yield_score, 100))

        return {
            "user_id": user_id,
            "is_online": is_online,
            "session_id": active_session.session_id if active_session else None,
            "earnings_today_rlusd": round(earnings_today, 6),
            "earnings_this_week_rlusd": round(earnings_this_week, 6),
            "earnings_this_month_rlusd": round(earnings_this_month, 6),
            "earnings_total_rlusd": round(earnings_total, 6),
            "current_rate_per_hour_usd": round(current_rate_per_hour, 6),
            "tasks_completed_today": tasks_completed_today,
            "data_points_extracted_today": int(data_points_extracted_today),
            "active_data_categories": active_data_categories,
            "yield_score": yield_score,
            "generated_at": now.isoformat(),
        }

    # ------------------------------------------------------------------
    # 2. Yield History
    # ------------------------------------------------------------------

    def get_yield_history(self, user_id: int, days_back: int = 30) -> Dict:
        """Return historical yield data bucketed by day.

        Includes daily earnings, weekly totals, trend direction,
        best day, and average daily RLUSD.
        """
        from models import db, NodeDataExtraction, NodePayout, NodePayoutEpoch
        from sqlalchemy import func

        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        range_start = today_start - timedelta(days=days_back)

        # --- Daily payout sums --------------------------------------------------

        payout_rows = (
            db.session.query(
                func.date(NodePayout.created_at).label("day"),
                func.coalesce(func.sum(NodePayout.payout_amount_rlusd), 0.0),
            )
            .filter(
                NodePayout.user_id == user_id,
                NodePayout.created_at >= range_start,
            )
            .group_by(func.date(NodePayout.created_at))
            .all()
        )
        payout_by_day = {str(r[0]): float(r[1]) for r in payout_rows}

        # --- Daily extraction counts --------------------------------------------

        extraction_rows = (
            db.session.query(
                func.date(NodeDataExtraction.created_at).label("day"),
                func.count(NodeDataExtraction.id),
                func.coalesce(func.sum(NodeDataExtraction.data_points), 0),
            )
            .filter(
                NodeDataExtraction.user_id == user_id,
                NodeDataExtraction.created_at >= range_start,
            )
            .group_by(func.date(NodeDataExtraction.created_at))
            .all()
        )
        tasks_by_day = {str(r[0]): int(r[1]) for r in extraction_rows}
        dp_by_day = {str(r[0]): int(r[2]) for r in extraction_rows}

        # --- Build daily_earnings array -----------------------------------------

        daily_earnings = []
        for offset in range(days_back):
            day = (range_start + timedelta(days=offset)).date()
            day_str = str(day)
            daily_earnings.append({
                "date": day_str,
                "rlusd": round(payout_by_day.get(day_str, 0.0), 6),
                "tasks": tasks_by_day.get(day_str, 0),
                "data_points": dp_by_day.get(day_str, 0),
            })

        # --- Weekly totals ------------------------------------------------------

        weekly_totals = []
        for week_idx in range(0, days_back, 7):
            week_slice = daily_earnings[week_idx : week_idx + 7]
            if not week_slice:
                continue
            weekly_totals.append({
                "week_start": week_slice[0]["date"],
                "week_end": week_slice[-1]["date"],
                "rlusd": round(sum(d["rlusd"] for d in week_slice), 6),
                "tasks": sum(d["tasks"] for d in week_slice),
                "data_points": sum(d["data_points"] for d in week_slice),
            })

        # --- Trend: last 7d vs prior 7d ----------------------------------------

        last_7 = daily_earnings[-7:]
        prior_7 = daily_earnings[-14:-7] if len(daily_earnings) >= 14 else []

        last_7_total = sum(d["rlusd"] for d in last_7)
        prior_7_total = sum(d["rlusd"] for d in prior_7) if prior_7 else last_7_total

        if prior_7_total == 0:
            trend = "stable"
        elif last_7_total > prior_7_total * 1.05:
            trend = "up"
        elif last_7_total < prior_7_total * 0.95:
            trend = "down"
        else:
            trend = "stable"

        # --- Best day & average -------------------------------------------------

        best_day_entry = max(daily_earnings, key=lambda d: d["rlusd"]) if daily_earnings else None
        total_rlusd = sum(d["rlusd"] for d in daily_earnings)
        avg_daily_rlusd = total_rlusd / max(len(daily_earnings), 1)

        return {
            "user_id": user_id,
            "days_back": days_back,
            "daily_earnings": daily_earnings,
            "weekly_totals": weekly_totals,
            "trend": trend,
            "last_7d_rlusd": round(last_7_total, 6),
            "prior_7d_rlusd": round(prior_7_total, 6),
            "best_day": {
                "date": best_day_entry["date"],
                "rlusd": best_day_entry["rlusd"],
            } if best_day_entry else None,
            "avg_daily_rlusd": round(avg_daily_rlusd, 6),
            "total_rlusd": round(total_rlusd, 6),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    # ------------------------------------------------------------------
    # 3. Category Breakdown
    # ------------------------------------------------------------------

    def get_category_breakdown(self, user_id: int, days_back: int = 30) -> Dict:
        """Return per-category earnings breakdown.

        Every category in DATA_CATEGORY_VALUES is included — those with
        no extraction data show zeroes.  Sorted by earnings descending.
        """
        from models import db, NodeDataExtraction
        from sqlalchemy import func

        now = datetime.now(timezone.utc)
        range_start = now - timedelta(days=days_back)

        # Aggregate extractions grouped by category
        rows = (
            db.session.query(
                NodeDataExtraction.data_category,
                func.coalesce(func.sum(NodeDataExtraction.payout_earned_rlusd), 0.0),
                func.coalesce(func.sum(NodeDataExtraction.records_extracted), 0),
                func.coalesce(func.sum(NodeDataExtraction.data_points), 0),
                func.coalesce(func.avg(NodeDataExtraction.quality_score), 0),
                func.count(NodeDataExtraction.id),
            )
            .filter(
                NodeDataExtraction.user_id == user_id,
                NodeDataExtraction.created_at >= range_start,
            )
            .group_by(NodeDataExtraction.data_category)
            .all()
        )

        cat_data = {}
        for row in rows:
            cat_data[row[0]] = {
                "earnings_rlusd": float(row[1]),
                "records_extracted": int(row[2]),
                "data_points": int(row[3]),
                "avg_quality_score": round(float(row[4]), 1),
                "extraction_count": int(row[5]),
            }

        total_earnings = sum(v["earnings_rlusd"] for v in cat_data.values())

        categories = []
        for cat_key, cat_meta in DATA_CATEGORY_VALUES.items():
            entry = cat_data.get(cat_key)
            if entry:
                pct = (entry["earnings_rlusd"] / total_earnings * 100) if total_earnings > 0 else 0.0
                categories.append({
                    "category": cat_key,
                    "display_name": cat_meta["display_name"],
                    "base_value_usd": cat_meta["base_value_usd"],
                    "enabled": True,
                    "earnings_rlusd": round(entry["earnings_rlusd"], 6),
                    "records_extracted": entry["records_extracted"],
                    "data_points": entry["data_points"],
                    "avg_quality_score": entry["avg_quality_score"],
                    "extraction_count": entry["extraction_count"],
                    "percentage_of_total": round(pct, 2),
                })
            else:
                categories.append({
                    "category": cat_key,
                    "display_name": cat_meta["display_name"],
                    "base_value_usd": cat_meta["base_value_usd"],
                    "enabled": False,
                    "earnings_rlusd": 0.0,
                    "records_extracted": 0,
                    "data_points": 0,
                    "avg_quality_score": 0.0,
                    "extraction_count": 0,
                    "percentage_of_total": 0.0,
                })

        categories.sort(key=lambda c: c["earnings_rlusd"], reverse=True)

        active_count = sum(1 for c in categories if c["enabled"])
        top_category = categories[0]["category"] if categories and categories[0]["enabled"] else None

        return {
            "user_id": user_id,
            "days_back": days_back,
            "categories": categories,
            "total_earnings_rlusd": round(total_earnings, 6),
            "total_categories_active": active_count,
            "top_category": top_category,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    # ------------------------------------------------------------------
    # 4. Yield Optimization
    # ------------------------------------------------------------------

    def get_yield_optimization(self, user_id: int) -> Dict:
        """Suggest how to earn more by enabling additional data categories.

        Compares the operator's active categories against network-wide
        averages and estimates the additional daily RLUSD they could earn
        by enabling categories they have not yet tried.
        """
        from models import db, NodeDataExtraction
        from sqlalchemy import func

        now = datetime.now(timezone.utc)
        thirty_days_ago = now - timedelta(days=30)
        seven_days_ago = now - timedelta(days=7)

        # --- User's active categories (last 30 days) ---------------------------

        user_cats_rows = (
            db.session.query(NodeDataExtraction.data_category)
            .filter(
                NodeDataExtraction.user_id == user_id,
                NodeDataExtraction.created_at >= thirty_days_ago,
            )
            .distinct()
            .all()
        )
        user_active_categories = {r[0] for r in user_cats_rows if r[0]}

        # --- Network averages per category (daily avg earnings per user) --------
        # For each category, compute total earnings / distinct users / 30 days
        network_avg_rows = (
            db.session.query(
                NodeDataExtraction.data_category,
                func.coalesce(func.sum(NodeDataExtraction.payout_earned_rlusd), 0.0),
                func.count(func.distinct(NodeDataExtraction.user_id)),
            )
            .filter(NodeDataExtraction.created_at >= thirty_days_ago)
            .group_by(NodeDataExtraction.data_category)
            .all()
        )

        network_avg_daily = {}
        for row in network_avg_rows:
            cat = row[0]
            total_earned = float(row[1])
            distinct_users = int(row[2]) or 1
            network_avg_daily[cat] = total_earned / distinct_users / 30.0

        # --- User's current estimated daily (last 7 days average) ---------------

        user_7d_total = (
            db.session.query(
                func.coalesce(func.sum(NodeDataExtraction.payout_earned_rlusd), 0.0)
            )
            .filter(
                NodeDataExtraction.user_id == user_id,
                NodeDataExtraction.created_at >= seven_days_ago,
            )
            .scalar()
        )
        current_estimated_daily = float(user_7d_total) / 7.0

        # --- Build suggestions for inactive categories --------------------------

        suggestions = []
        total_additional = 0.0

        for cat_key, cat_meta in DATA_CATEGORY_VALUES.items():
            if cat_key not in user_active_categories:
                est_daily = network_avg_daily.get(cat_key, cat_meta["base_value_usd"] * 100 * 0.10)
                est_daily = round(est_daily, 6)
                total_additional += est_daily

                suggestions.append({
                    "category": cat_key,
                    "display_name": cat_meta["display_name"],
                    "base_value_usd": cat_meta["base_value_usd"],
                    "estimated_additional_daily_rlusd": est_daily,
                    "recommendation": (
                        f"Enable {cat_meta['display_name'].lower()} extraction to earn "
                        f"an estimated ${est_daily:.2f} more per day"
                    ),
                })

        suggestions.sort(key=lambda s: s["estimated_additional_daily_rlusd"], reverse=True)

        potential_daily = current_estimated_daily + total_additional
        uplift_pct = (
            (total_additional / current_estimated_daily * 100)
            if current_estimated_daily > 0
            else 0.0
        )

        # --- Network benchmarks -------------------------------------------------

        # Average daily earnings across all nodes (last 30 days)
        network_total_row = (
            db.session.query(
                func.coalesce(func.sum(NodeDataExtraction.payout_earned_rlusd), 0.0),
                func.count(func.distinct(NodeDataExtraction.user_id)),
            )
            .filter(NodeDataExtraction.created_at >= thirty_days_ago)
            .first()
        )
        network_total_earned = float(network_total_row[0]) if network_total_row else 0.0
        network_distinct_users = int(network_total_row[1]) if network_total_row else 1
        network_avg_daily_rlusd = network_total_earned / max(network_distinct_users, 1) / 30.0

        # Top earner daily (anonymised)
        top_earner_row = (
            db.session.query(
                func.sum(NodeDataExtraction.payout_earned_rlusd).label("total")
            )
            .filter(NodeDataExtraction.created_at >= thirty_days_ago)
            .group_by(NodeDataExtraction.user_id)
            .order_by(func.sum(NodeDataExtraction.payout_earned_rlusd).desc())
            .first()
        )
        top_earner_daily = float(top_earner_row[0]) / 30.0 if top_earner_row else 0.0

        return {
            "user_id": user_id,
            "current_estimated_daily_rlusd": round(current_estimated_daily, 6),
            "potential_daily_rlusd": round(potential_daily, 6),
            "uplift_percentage": round(uplift_pct, 2),
            "suggestions": suggestions,
            "network_avg_daily_rlusd": round(network_avg_daily_rlusd, 6),
            "top_earner_daily_rlusd": round(top_earner_daily, 6),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    # ------------------------------------------------------------------
    # 5. Record Extraction
    # ------------------------------------------------------------------

    def record_extraction(
        self,
        user_id: int,
        session_id: int = None,
        task_id: str = "",
        task_type: str = "",
        records_extracted: int = 0,
        data_points: int = 0,
        data_size_bytes: int = 0,
        quality_score: int = 50,
        metadata: dict = None,
    ) -> Dict:
        """Record a data extraction event.

        Called by TaskDispatcher when a task completes.  Maps the task type
        to a data category, calculates commercial value and payout earned,
        persists a NodeDataExtraction row, and returns the serialised record.
        """
        from models import db, NodeDataExtraction, NodeSession

        # --- Resolve data category ----------------------------------------------

        data_category = TASK_CATEGORY_MAP.get(task_type, "search_results")

        # --- Look up base value -------------------------------------------------

        cat_info = DATA_CATEGORY_VALUES.get(data_category, DATA_CATEGORY_VALUES["search_results"])
        base_value = cat_info["base_value_usd"]

        # --- Payout multiplier from citizenserp task config ---------------------

        payout_multiplier = 1.0
        try:
            from citizenserp_tasks import CITIZENSERP_TASKS
            for task_cfg in CITIZENSERP_TASKS:
                if task_cfg.get("task_type") == task_type:
                    payout_multiplier = task_cfg.get("payout_multiplier", 1.0)
                    break
        except (ImportError, Exception):
            payout_multiplier = 1.0

        # --- Calculate values ---------------------------------------------------

        quality_factor = max(0, min(quality_score, 100)) / 100.0
        commercial_value = base_value * records_extracted * quality_factor
        payout_earned = commercial_value * 0.10  # 10 % payout percentage

        # --- Node Consent Economy: Apply tier payout multiplier ---
        try:
            from models import NodeConsentProfile
            consent_profile = NodeConsentProfile.query.filter_by(user_id=user_id).first()
            if consent_profile and consent_profile.payout_multiplier:
                payout_earned *= consent_profile.payout_multiplier
        except Exception:
            pass  # Graceful fallback — no multiplier applied

        # --- Resolve session if not provided ------------------------------------

        if session_id is None:
            active_session = (
                NodeSession.query
                .filter_by(user_id=user_id, status="active")
                .order_by(NodeSession.start_time.desc())
                .first()
            )
            if active_session:
                session_id = active_session.id

        # --- Serialise metadata -------------------------------------------------

        metadata_json = None
        if metadata is not None:
            try:
                metadata_json = json.dumps(metadata)
            except (TypeError, ValueError):
                self.logger.warning("Failed to serialise extraction metadata for user %s", user_id)
                metadata_json = None

        # --- Persist record -----------------------------------------------------

        extraction = NodeDataExtraction(
            session_id=session_id,
            user_id=user_id,
            task_id=task_id,
            task_type=task_type,
            data_category=data_category,
            records_extracted=records_extracted,
            data_points=data_points,
            data_size_bytes=data_size_bytes,
            commercial_value_usd=round(commercial_value, 8),
            payout_multiplier=payout_multiplier,
            payout_earned_rlusd=round(payout_earned, 8),
            quality_score=quality_score,
            extraction_metadata=metadata_json,
            created_at=datetime.now(timezone.utc),
        )

        db.session.add(extraction)
        db.session.commit()

        self.logger.info(
            "Recorded extraction user=%s task=%s category=%s records=%d payout=%.6f RLUSD",
            user_id, task_id, data_category, records_extracted, payout_earned,
        )

        # --- Return serialised record -------------------------------------------

        try:
            return extraction.to_dict()
        except AttributeError:
            return {
                "id": extraction.id,
                "session_id": extraction.session_id,
                "user_id": extraction.user_id,
                "task_id": extraction.task_id,
                "task_type": extraction.task_type,
                "data_category": extraction.data_category,
                "records_extracted": extraction.records_extracted,
                "data_points": extraction.data_points,
                "data_size_bytes": extraction.data_size_bytes,
                "commercial_value_usd": extraction.commercial_value_usd,
                "payout_multiplier": extraction.payout_multiplier,
                "payout_earned_rlusd": extraction.payout_earned_rlusd,
                "quality_score": extraction.quality_score,
                "created_at": extraction.created_at.isoformat() if extraction.created_at else None,
            }


    # ------------------------------------------------------------------
    # Build #90 — Zone economics integration
    # ------------------------------------------------------------------

    def get_zone_earnings_leaderboard(self, limit: int = 20) -> Dict:
        """Public-facing zone leaderboard by avg earnings per node.

        Powers the onboarding ad: "Nodes in Tokyo earned $X this month."
        """
        try:
            from hot_zone_economics import hot_zone_engine
            rankings = hot_zone_engine.compute_zone_rankings(limit=limit)
        except (ImportError, Exception):
            rankings = []

        # Network totals
        try:
            from models import db, ZoneEconomicsSnapshot
            from sqlalchemy import func
            from datetime import date

            today = date.today()
            totals = db.session.query(
                func.sum(ZoneEconomicsSnapshot.active_nodes),
                func.count(func.distinct(ZoneEconomicsSnapshot.zone_code)),
                func.sum(ZoneEconomicsSnapshot.total_revenue_usd),
            ).filter_by(snapshot_date=today).first()

            network = {
                'total_nodes': totals[0] or 0,
                'total_zones_covered': totals[1] or 0,
                'total_revenue_usd': round(totals[2] or 0, 2),
                'avg_earnings_per_node_usd': round(
                    (totals[2] or 0) / max(totals[0] or 1, 1), 2
                ),
            }
        except Exception:
            network = {
                'total_nodes': 0,
                'total_zones_covered': 0,
                'total_revenue_usd': 0,
                'avg_earnings_per_node_usd': 0,
            }

        return {
            'zones': rankings,
            'network_totals': network,
        }

    def get_zone_earnings_detail(self, zone_code: str) -> Dict:
        """Detailed zone economics with 30-day trend."""
        try:
            from hot_zone_economics import hot_zone_engine
            current = hot_zone_engine.compute_zone_economics(zone_code, period_days=30)
        except (ImportError, Exception):
            current = {'zone_code': zone_code, 'error': 'Zone economics unavailable'}

        # 30-day history
        try:
            from models import ZoneEconomicsSnapshot
            from datetime import date, timedelta

            cutoff = date.today() - timedelta(days=30)
            history = (
                ZoneEconomicsSnapshot.query
                .filter(
                    ZoneEconomicsSnapshot.zone_code == zone_code,
                    ZoneEconomicsSnapshot.snapshot_date >= cutoff,
                )
                .order_by(ZoneEconomicsSnapshot.snapshot_date.asc())
                .all()
            )
            trend = [s.to_dict() for s in history]
        except Exception:
            trend = []

        current['history'] = trend
        return current

    def get_estimated_earnings(
        self, zone_code: str, tier: str = 'bronze',
    ) -> Dict:
        """Estimated earnings for a new node in a zone."""
        try:
            from hot_zone_economics import hot_zone_engine
            return hot_zone_engine.get_estimated_earnings(zone_code, tier)
        except (ImportError, Exception):
            return {
                'zone_code': zone_code,
                'tier': tier,
                'estimated_monthly_usd': 0,
                'error': 'Estimation unavailable',
            }

    def get_network_heatmap(self) -> List[Dict]:
        """Zone data formatted for map visualization."""
        try:
            from models import ZoneEconomicsSnapshot
            from datetime import date

            today = date.today()
            snapshots = (
                ZoneEconomicsSnapshot.query
                .filter_by(snapshot_date=today)
                .all()
            )

            result = []
            for s in snapshots:
                lat, lon = self._get_zone_coordinates(s.zone_code)
                result.append({
                    'zone_code': s.zone_code,
                    'lat': lat,
                    'lon': lon,
                    'active_nodes': s.active_nodes,
                    'avg_earnings': round(s.avg_earnings_per_node_usd, 2),
                    'opportunity_score': s.opportunity_score,
                    'saturation': round(s.saturation_score, 2),
                    'total_revenue': round(s.total_revenue_usd, 2),
                })
            return result
        except Exception:
            return []

    def _get_zone_coordinates(self, zone_code: str) -> tuple:
        """Get lat/lon center for a zone."""
        try:
            from geographic_zones import get_zone
            zone = get_zone(zone_code)
            if zone:
                return (zone.lat_center, zone.lon_center)
        except (ImportError, Exception):
            pass
        return (0.0, 0.0)


# ---------------------------------------------------------------------------
# Earnings Projection Engine
# ---------------------------------------------------------------------------
# Projects per-node earnings at any network size.  Two revenue types:
#
#   1. Pool revenue — divided across all nodes weighted by tier/uptime.
#      Dilutes as network grows, but total pool grows with new data products.
#
#   2. Per-node exclusive revenue — tied to the individual node's unique
#      geographic/behavioral context.  Does NOT dilute with network size.
#      This is the key to keeping payouts high at scale.
#
# Data products unlock at different network sizes (phases).
# ---------------------------------------------------------------------------

# Per-node exclusive data products — value comes from YOUR unique context
# These don't dilute because a node in Lagos produces different data than Oslo
PER_NODE_DATA_PRODUCTS = {
    "price_observation": {
        "display_name": "Location-Verified Price Observation",
        "description": "Real product/service price seen from your real IP in your real city",
        "value_per_event": 0.005,
        "events_per_node_per_day": 100,
        "min_network_nodes": 0,       # Available from day 1
    },
    "purchase_intent": {
        "display_name": "Purchase Intent Signal",
        "description": "You searched, compared, and clicked 'buy' on a product",
        "value_per_event": 0.05,
        "events_per_node_per_day": 5,
        "min_network_nodes": 0,
    },
    "ad_render_verification": {
        "display_name": "Ad Render Verification",
        "description": "An ad was served to your real browser, verified not fraud",
        "value_per_event": 0.003,
        "events_per_node_per_day": 200,
        "min_network_nodes": 500,     # Need coverage for ad networks to care
    },
    "local_inventory": {
        "display_name": "Local Inventory Verification",
        "description": "Your browser confirmed stock/availability at a local retailer",
        "value_per_event": 0.01,
        "events_per_node_per_day": 20,
        "min_network_nodes": 500,
    },
    "search_personalization_delta": {
        "display_name": "Search Result Personalization Delta",
        "description": "How Google/Amazon results differ for YOU vs baseline",
        "value_per_event": 0.01,
        "events_per_node_per_day": 40,
        "min_network_nodes": 10000,
    },
    "local_service_pricing": {
        "display_name": "Local Service Pricing",
        "description": "Uber, DoorDash, insurance quotes from your real location",
        "value_per_event": 0.02,
        "events_per_node_per_day": 10,
        "min_network_nodes": 10000,
    },
    "network_quality": {
        "display_name": "Network Quality Measurement",
        "description": "Connection speed, latency, ISP performance from your location",
        "value_per_event": 0.002,
        "events_per_node_per_day": 50,
        "min_network_nodes": 0,
    },
    "content_accessibility": {
        "display_name": "Content Accessibility Audit",
        "description": "What content is accessible/blocked from your country",
        "value_per_event": 0.004,
        "events_per_node_per_day": 30,
        "min_network_nodes": 100000,
    },
    "streaming_availability": {
        "display_name": "Streaming Availability Map",
        "description": "What's on Netflix/Spotify from your country, verified live",
        "value_per_event": 0.005,
        "events_per_node_per_day": 20,
        "min_network_nodes": 100000,
    },
    "isp_behavior_audit": {
        "display_name": "Carrier/ISP Behavior Audit",
        "description": "Throttling, zero-rating, traffic shaping detection",
        "value_per_event": 0.003,
        "events_per_node_per_day": 50,
        "min_network_nodes": 100000,
    },
}

# Pool-based B2B data products — revenue divided across network
# Total pool grows with network size but per-node share dilutes
POOL_DATA_PRODUCTS = {
    "serp_api": {
        "display_name": "SERP API (Proxy Services)",
        "description": "Web scraping and search engine result page collection for B2B clients",
        "price_per_1k_requests": 1.50,
        # Demand scales sub-linearly — more nodes don't create proportionally more demand
        # Formula: base_requests_per_day * (network_nodes / reference_nodes) ^ elasticity
        "base_requests_per_day": 50000,
        "reference_nodes": 500,
        "demand_elasticity": 0.7,     # <1 = demand grows slower than supply
        "min_network_nodes": 500,
    },
    "ad_fraud_detection": {
        "display_name": "Ad Fraud Detection",
        "description": "Every ad impression verified from real residential browsers",
        "price_per_1k_requests": 2.00,
        "base_requests_per_day": 30000,
        "reference_nodes": 500,
        "demand_elasticity": 0.8,
        "min_network_nodes": 500,
    },
    "price_intelligence": {
        "display_name": "Price Intelligence",
        "description": "Global product/service pricing across geographies",
        "price_per_1k_requests": 2.50,
        "base_requests_per_day": 20000,
        "reference_nodes": 2000,
        "demand_elasticity": 0.75,
        "min_network_nodes": 2000,
    },
    "market_research": {
        "display_name": "Market Research & Consumer Panels",
        "description": "Real browsing/purchasing behavior data for enterprise research",
        "price_per_1k_requests": 3.00,
        "base_requests_per_day": 10000,
        "reference_nodes": 10000,
        "demand_elasticity": 0.65,
        "min_network_nodes": 10000,
    },
    "predictive_demand": {
        "display_name": "Predictive Consumer Demand",
        "description": "Search and click behavior predicting purchasing trends",
        "price_per_1k_requests": 5.00,
        "base_requests_per_day": 50000,
        "reference_nodes": 100000,
        "demand_elasticity": 0.6,
        "min_network_nodes": 100000,
    },
    "consumer_index": {
        "display_name": "Global Real-Time Consumer Index",
        "description": "Real browsing behavior of massive user base — sold to financial institutions",
        "price_per_1k_requests": 4.00,
        "base_requests_per_day": 500000,
        "reference_nodes": 1000000,
        "demand_elasticity": 0.5,
        "min_network_nodes": 1000000,
    },
    "internet_observatory": {
        "display_name": "Internet Health Observatory",
        "description": "Real-time censorship, outage, throttling detection globally",
        "price_per_1k_requests": 2.00,
        "base_requests_per_day": 100000,
        "reference_nodes": 1000000,
        "demand_elasticity": 0.55,
        "min_network_nodes": 1000000,
    },
}

# Browse data — passive monitoring during Free Browse sessions
BROWSE_DATA_MONTHLY_PER_NODE = 8.70  # Based on event values in free_browse_portal.py

# Tier distribution assumptions (what % of network is at each tier)
TIER_DISTRIBUTION = {
    "bronze":   0.50,
    "silver":   0.30,
    "gold":     0.15,
    "platinum": 0.05,
}

# Tier payout multipliers (from node_consent_economy Phase 2)
TIER_PAYOUT_MULTIPLIERS = {
    "bronze":   1.0,
    "silver":   1.25,
    "gold":     1.50,
    "platinum": 2.0,
}

# Average daily uptime hours by tier
TIER_UPTIME_HOURS = {
    "bronze":   2.0,
    "silver":   4.0,
    "gold":     8.0,
    "platinum": 12.0,
}


def project_node_earnings(
    network_nodes: int,
    tier: str = "bronze",
    uptime_hours: Optional[float] = None,
    _include_comparison: bool = True,
) -> Dict:
    """Project per-node monthly earnings at a given network size and tier.

    This is the core projection model. It computes:
    1. Per-node exclusive revenue (doesn't dilute)
    2. Pool revenue share (dilutes but pool grows)
    3. Browse data revenue (flat per node)

    Args:
        network_nodes: Total nodes in the network.
        tier: Node tier (bronze/silver/gold/platinum).
        uptime_hours: Daily uptime hours. If None, uses tier default.

    Returns:
        Dict with detailed earnings breakdown by product and revenue type.
    """
    tier = tier.lower()
    if tier not in TIER_PAYOUT_MULTIPLIERS:
        tier = "bronze"

    if uptime_hours is None:
        uptime_hours = TIER_UPTIME_HOURS.get(tier, 2.0)

    payout_mult = TIER_PAYOUT_MULTIPLIERS[tier]
    uptime_fraction = min(uptime_hours / 24.0, 1.0)

    # --- Preference routing: task volume multiplier ---
    # Higher tiers get dispatched more tasks via priority routing.
    # This multiplies the number of extraction events a node processes.
    try:
        from node_consent_economy import (
            TIER_PREFERENCE_MULTIPLIERS,
            compute_pool_richness_multiplier,
        )
        task_volume_mult = TIER_PREFERENCE_MULTIPLIERS.get(
            tier, {}
        ).get('task_volume_mult', 1.0)
        pool_richness_mult = compute_pool_richness_multiplier()
    except ImportError:
        task_volume_mult = {"bronze": 1.0, "silver": 1.5, "gold": 2.5, "platinum": 4.0}.get(tier, 1.0)
        pool_richness_mult = 1.36  # default for typical tier mix

    # --- 1. Per-node exclusive revenue (doesn't dilute) ---
    # Task volume multiplier: more tasks dispatched = more extraction events
    # A platinum node processes 4x the extraction volume of a bronze node.

    exclusive_products = []
    exclusive_monthly_total = 0.0

    for key, product in PER_NODE_DATA_PRODUCTS.items():
        if network_nodes >= product["min_network_nodes"]:
            daily_value = product["value_per_event"] * product["events_per_node_per_day"]
            # Uptime scales events linearly (more hours online = more events)
            daily_value *= uptime_fraction / (TIER_UPTIME_HOURS["bronze"] / 24.0)
            # Cap at 1.0 — can't produce more than max events per product
            daily_value = min(daily_value, product["value_per_event"] * product["events_per_node_per_day"])
            # Preference routing: higher tiers get dispatched more tasks
            daily_value *= task_volume_mult
            monthly = daily_value * 30
            exclusive_monthly_total += monthly
            exclusive_products.append({
                "key": key,
                "display_name": product["display_name"],
                "description": product["description"],
                "monthly_usd": round(monthly, 2),
                "daily_usd": round(daily_value, 4),
                "unlocked": True,
            })
        else:
            exclusive_products.append({
                "key": key,
                "display_name": product["display_name"],
                "description": product["description"],
                "monthly_usd": 0,
                "daily_usd": 0,
                "unlocked": False,
                "unlocks_at_nodes": product["min_network_nodes"],
            })

    # --- 2. Pool revenue share (dilutes but pool grows) ---
    # Data richness multiplier: when higher tiers share more data categories,
    # the combined dataset is richer, B2B clients pay more, pool grows for ALL.
    # This is the positive-sum effect — everyone benefits from better data.

    pool_products = []
    pool_monthly_total = 0.0

    for key, product in POOL_DATA_PRODUCTS.items():
        if network_nodes >= product["min_network_nodes"]:
            # Demand grows with network size but sub-linearly
            scale_factor = (network_nodes / product["reference_nodes"]) ** product["demand_elasticity"]
            daily_requests = product["base_requests_per_day"] * scale_factor
            daily_pool_revenue = daily_requests * product["price_per_1k_requests"] / 1000.0
            # Data richness: richer dataset = higher B2B prices = bigger pool for ALL
            daily_pool_revenue *= pool_richness_mult
            monthly_pool_revenue = daily_pool_revenue * 30

            # Compute weighted share for this tier
            # Weight = payout_multiplier * uptime_fraction
            # Total weight = sum of all nodes' weights
            total_weight = sum(
                TIER_DISTRIBUTION[t] * network_nodes * TIER_PAYOUT_MULTIPLIERS[t] * (TIER_UPTIME_HOURS[t] / 24.0)
                for t in TIER_DISTRIBUTION
            )
            my_weight = payout_mult * uptime_fraction
            my_share = my_weight / total_weight if total_weight > 0 else 0
            my_monthly = monthly_pool_revenue * my_share

            pool_monthly_total += my_monthly
            pool_products.append({
                "key": key,
                "display_name": product["display_name"],
                "description": product["description"],
                "network_monthly_revenue_usd": round(monthly_pool_revenue, 0),
                "your_monthly_share_usd": round(my_monthly, 2),
                "daily_requests": int(daily_requests),
                "unlocked": True,
            })
        else:
            pool_products.append({
                "key": key,
                "display_name": product["display_name"],
                "description": product["description"],
                "network_monthly_revenue_usd": 0,
                "your_monthly_share_usd": 0,
                "unlocked": False,
                "unlocks_at_nodes": product["min_network_nodes"],
            })

    # --- 3. Browse data revenue (flat per node) ---

    browse_monthly = BROWSE_DATA_MONTHLY_PER_NODE

    # --- 4. Arbitrage rewards ---
    # Phase 1-2: static tier-dependent bonus.
    # Phase 3: DYNAMIC — nodes earn a % of Phoenix's booking fee cut
    #   when their search activity discovers arbitrage leading to bookings.
    #   Formula: avg_booking_value × fee_pct × arbitrage_reward_pct × bookings_per_node
    #   Zero external query costs in Phase 3 (we own the SERP).

    phase = int(os.environ.get("PHOENIX_ECONOMIC_PHASE", "1"))

    if phase >= 3:
        # Phase 3 dynamic arbitrage rewards
        # Conservative assumptions:
        #   avg booking value: $450 (flights/hotels/transfers blended)
        #   platform fee: tier-dependent (10-25%)
        #   arbitrage reward: tier-dependent % of the fee
        #   bookings influenced per node/month: scales with queries and tier
        avg_booking_value = 450.0
        phase3_fee_pcts = {"bronze": 0.25, "silver": 0.20, "gold": 0.15, "platinum": 0.10}
        phase3_reward_pcts = {"bronze": 0.02, "silver": 0.05, "gold": 0.10, "platinum": 0.15}
        # Bookings influenced per node per month — higher tiers run more searches,
        # discover more arbitrage, influence more bookings
        phase3_bookings_per_node = {"bronze": 2, "silver": 5, "gold": 12, "platinum": 30}

        fee_pct = phase3_fee_pcts.get(tier, 0.25)
        reward_pct = phase3_reward_pcts.get(tier, 0.02)
        bookings = phase3_bookings_per_node.get(tier, 2)

        # Per booking: avg_value × fee × reward_share
        reward_per_booking = avg_booking_value * fee_pct * reward_pct
        arbitrage_monthly = reward_per_booking * bookings

        # Phase 3 bonus: zero query costs means more searches = more discoveries.
        # Network effect: larger network finds more arbitrage opportunities.
        # Scale bonus: sqrt(network_nodes / 500) capped at 3x
        scale_bonus = min(3.0, math.sqrt(max(network_nodes, 500) / 500))
        arbitrage_monthly *= scale_bonus
    else:
        # Phase 1-2: static bonus
        arbitrage_rewards = {
            "bronze": 0.0,
            "silver": 2.0,
            "gold": 5.0,
            "platinum": 12.0,
        }
        arbitrage_monthly = arbitrage_rewards.get(tier, 0.0)

    # --- Total ---

    total_monthly = exclusive_monthly_total + pool_monthly_total + browse_monthly + arbitrage_monthly

    # --- Network-wide stats ---

    total_network_pool_revenue = sum(
        p["network_monthly_revenue_usd"] for p in pool_products if p["unlocked"]
    )
    total_network_exclusive_revenue = exclusive_monthly_total * network_nodes
    total_network_revenue = total_network_pool_revenue + total_network_exclusive_revenue + (browse_monthly * network_nodes)

    # Count unlocked products
    unlocked_exclusive = sum(1 for p in exclusive_products if p.get("unlocked"))
    unlocked_pool = sum(1 for p in pool_products if p.get("unlocked"))
    total_products = len(PER_NODE_DATA_PRODUCTS) + len(POOL_DATA_PRODUCTS)
    unlocked_products = unlocked_exclusive + unlocked_pool

    # Next unlock
    next_unlock = None
    all_thresholds = []
    for p in PER_NODE_DATA_PRODUCTS.values():
        if p["min_network_nodes"] > network_nodes:
            all_thresholds.append(p["min_network_nodes"])
    for p in POOL_DATA_PRODUCTS.values():
        if p["min_network_nodes"] > network_nodes:
            all_thresholds.append(p["min_network_nodes"])
    if all_thresholds:
        next_unlock = min(all_thresholds)

    return {
        "network_nodes": network_nodes,
        "tier": tier,
        "uptime_hours_per_day": uptime_hours,
        "payout_multiplier": payout_mult,
        "task_volume_multiplier": task_volume_mult,
        "pool_richness_multiplier": round(pool_richness_mult, 2),

        "earnings": {
            "exclusive_monthly_usd": round(exclusive_monthly_total, 2),
            "pool_share_monthly_usd": round(pool_monthly_total, 2),
            "browse_data_monthly_usd": round(browse_monthly, 2),
            "arbitrage_rewards_monthly_usd": round(arbitrage_monthly, 2),
            "total_monthly_usd": round(total_monthly, 2),
            "total_annual_usd": round(total_monthly * 12, 2),
        },

        "exclusive_products": exclusive_products,
        "pool_products": pool_products,

        "network_stats": {
            "total_network_monthly_revenue_usd": round(total_network_revenue, 0),
            "total_network_annual_revenue_usd": round(total_network_revenue * 12, 0),
            "total_pool_monthly_usd": round(total_network_pool_revenue, 0),
        },

        "data_products": {
            "unlocked": unlocked_products,
            "total": total_products,
            "next_unlock_at_nodes": next_unlock,
        },

        "comparison": {
            "all_tiers": {
                t: round(
                    _quick_tier_total(network_nodes, t), 2
                )
                for t in TIER_PAYOUT_MULTIPLIERS
            } if _include_comparison else {},
        },
    }


def _quick_tier_total(network_nodes: int, tier: str) -> float:
    """Quick total monthly earnings for comparison table."""
    result = project_node_earnings(network_nodes, tier, _include_comparison=False)
    return result["earnings"]["total_monthly_usd"]


def project_all_scales(tier: str = "platinum") -> List[Dict]:
    """Project earnings across all meaningful network scales.

    Returns a list of projections at key milestones for dashboard/pitch deck.
    """
    scales = [10, 100, 500, 2000, 10000, 100000, 1000000, 10000000, 72000000, 1000000000]
    results = []
    for n in scales:
        proj = project_node_earnings(n, tier)
        results.append({
            "network_nodes": n,
            "tier": tier,
            "monthly_usd": proj["earnings"]["total_monthly_usd"],
            "annual_usd": proj["earnings"]["total_annual_usd"],
            "network_annual_revenue_usd": proj["network_stats"]["total_network_annual_revenue_usd"],
            "unlocked_products": proj["data_products"]["unlocked"],
            "total_products": proj["data_products"]["total"],
            "breakdown": {
                "exclusive": proj["earnings"]["exclusive_monthly_usd"],
                "pool_share": proj["earnings"]["pool_share_monthly_usd"],
                "browse": proj["earnings"]["browse_data_monthly_usd"],
                "arbitrage": proj["earnings"]["arbitrage_rewards_monthly_usd"],
            },
        })
    return results


def project_all_phases(network_nodes: int = 10000, tier: str = "platinum") -> Dict:
    """Compare per-node earnings across all 3 economic phases at a given scale.

    Temporarily sets PHOENIX_ECONOMIC_PHASE to simulate each phase.
    Restores original phase when done.

    Returns:
        Dict with phase1, phase2, phase3 projections side by side.
    """
    original_phase = os.environ.get("PHOENIX_ECONOMIC_PHASE", "1")
    results = {}

    for phase in [1, 2, 3]:
        os.environ["PHOENIX_ECONOMIC_PHASE"] = str(phase)
        proj = project_node_earnings(network_nodes, tier, _include_comparison=False)
        results[f"phase{phase}"] = {
            "phase": phase,
            "tier": tier,
            "network_nodes": network_nodes,
            "monthly_usd": proj["earnings"]["total_monthly_usd"],
            "annual_usd": proj["earnings"]["total_annual_usd"],
            "breakdown": {
                "exclusive": proj["earnings"]["exclusive_monthly_usd"],
                "pool_share": proj["earnings"]["pool_share_monthly_usd"],
                "browse": proj["earnings"]["browse_data_monthly_usd"],
                "arbitrage": proj["earnings"]["arbitrage_rewards_monthly_usd"],
            },
        }

    # Restore
    os.environ["PHOENIX_ECONOMIC_PHASE"] = original_phase
    return results


def project_all_scales_all_phases(tier: str = "platinum") -> List[Dict]:
    """Full matrix: every scale × every phase × specified tier.

    Returns list of rows, each with phase1/phase2/phase3 monthly earnings.
    """
    scales = [100, 500, 2000, 10000, 100000, 1000000, 10000000, 72000000, 1000000000]
    original_phase = os.environ.get("PHOENIX_ECONOMIC_PHASE", "1")
    results = []

    for n in scales:
        row = {"network_nodes": n, "tier": tier}
        for phase in [1, 2, 3]:
            os.environ["PHOENIX_ECONOMIC_PHASE"] = str(phase)
            proj = project_node_earnings(n, tier, _include_comparison=False)
            row[f"phase{phase}_monthly"] = proj["earnings"]["total_monthly_usd"]
            row[f"phase{phase}_arbitrage"] = proj["earnings"]["arbitrage_rewards_monthly_usd"]
            row[f"phase{phase}_annual"] = proj["earnings"]["total_annual_usd"]
        results.append(row)

    os.environ["PHOENIX_ECONOMIC_PHASE"] = original_phase
    return results


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

yield_dashboard = NodeYieldDashboard()
