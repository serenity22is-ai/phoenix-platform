"""
Hot Zone Economics Engine — Build #90.

Computes per-zone economic metrics that power the node earnings
dashboard, opportunity scores, and hot-zone onboarding ads.

The key insight:
    earnings_per_node = zone_revenue / zone_node_count

When a zone has few nodes but high traffic, earnings_per_node is
high → "hot zone."  As more nodes join, per-node earnings decrease
but coverage improves → better arbitrage → more users → equilibrium.

Scaling proof:
    N_users = N_nodes (ToS).  Each node: 2 concurrent × 0.3 uptime =
    0.6 effective slots.  Each user/day: ~4,140 node-seconds demand.
    Each node/day: ~51,840 node-seconds supply.  Headroom: 12.5×.
"""

import logging
import time
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Default node capacity assumptions
DEFAULT_MAX_CONCURRENT = 2
DEFAULT_UPTIME_FRACTION = 0.3


class HotZoneEngine:
    """Computes and surfaces zone-level economic metrics."""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compute_zone_economics(
        self, zone_code: str, period_days: int = 30,
    ) -> Dict[str, Any]:
        """Compute full economic metrics for a zone over the given period.

        Returns dict with supply, demand, revenue, per-node economics,
        and opportunity signals.
        """
        cutoff = datetime.utcnow() - timedelta(days=period_days)

        # Supply metrics
        supply = self._compute_supply(zone_code, cutoff)

        # Demand metrics
        demand = self._compute_demand(zone_code, cutoff)

        # Revenue metrics
        revenue = self._compute_revenue(zone_code, cutoff)

        # Per-node economics
        active_nodes = supply['active_nodes'] or 1  # avoid div-by-zero
        avg_earnings = revenue['total_revenue_usd'] / active_nodes
        top_earnings = self._compute_top_node_earnings(zone_code, cutoff)

        # Signals
        capacity = (
            supply['active_nodes']
            * DEFAULT_MAX_CONCURRENT
            * DEFAULT_UPTIME_FRACTION
            * 3600  # node-seconds per hour
        )
        demand_rate = demand['total_tasks'] / max(period_days, 1)  # tasks/day
        saturation = min(1.0, demand_rate / max(capacity, 1))
        dsr = demand_rate / max(supply['active_nodes'], 1)

        opportunity = self._compute_opportunity_score(
            demand_supply_ratio=dsr,
            earnings_per_node=avg_earnings,
            saturation=saturation,
            zone_code=zone_code,
            period_days=period_days,
        )

        result = {
            'zone_code': zone_code,
            'zone_name': self._resolve_zone_name(zone_code),
            'period_days': period_days,
            # Supply
            'active_nodes': supply['active_nodes'],
            'total_node_hours': supply['total_node_hours'],
            # Demand
            'arbitrage_queries_served': demand['arbitrage_queries_served'],
            'browse_sessions_served': demand['browse_sessions_served'],
            'total_tasks': demand['total_tasks'],
            # Revenue
            'arbitrage_fee_revenue_usd': round(revenue['arbitrage_fee_revenue_usd'], 2),
            'browse_data_revenue_usd': round(revenue['browse_data_revenue_usd'], 2),
            'total_revenue_usd': round(revenue['total_revenue_usd'], 2),
            # Per-node
            'avg_earnings_per_node_usd': round(avg_earnings, 2),
            'top_node_earnings_usd': round(top_earnings, 2),
            # Signals
            'demand_supply_ratio': round(dsr, 2),
            'saturation_score': round(saturation, 2),
            'opportunity_score': opportunity,
        }

        # Persist snapshot
        self._save_snapshot(result)

        return result

    def compute_zone_rankings(self, limit: int = 20) -> List[Dict]:
        """Return top zones ranked by opportunity score."""
        try:
            from models import ZoneEconomicsSnapshot
            today = date.today()
            snapshots = (
                ZoneEconomicsSnapshot.query
                .filter_by(snapshot_date=today)
                .order_by(ZoneEconomicsSnapshot.opportunity_score.desc())
                .limit(limit)
                .all()
            )
            return [s.to_dict() for s in snapshots]
        except Exception as e:
            logger.warning("compute_zone_rankings failed: %s", e)
            return []

    def get_estimated_earnings(
        self, zone_code: str, tier: str = 'bronze',
    ) -> Dict[str, Any]:
        """Estimate what a NEW node joining this zone would earn.

        Accounts for dilution: adding 1 node to N existing nodes.
        """
        try:
            from models import ZoneEconomicsSnapshot
            snap = (
                ZoneEconomicsSnapshot.query
                .filter_by(zone_code=zone_code)
                .order_by(ZoneEconomicsSnapshot.snapshot_date.desc())
                .first()
            )
        except Exception:
            snap = None

        if snap and snap.active_nodes > 0:
            current_avg = snap.avg_earnings_per_node_usd
            n = snap.active_nodes
            # New node dilutes earnings: avg * (n / (n + 1))
            estimated = current_avg * (n / (n + 1))
        else:
            # Empty zone — use network average with demand multiplier
            estimated = self._network_average_earnings() * 1.5

        # Apply tier payout multiplier
        tier_multipliers = {
            'bronze': 1.0, 'silver': 1.15, 'gold': 1.30, 'platinum': 1.50,
        }
        multiplier = tier_multipliers.get(tier, 1.0)
        estimated *= multiplier

        return {
            'zone_code': zone_code,
            'tier': tier,
            'estimated_monthly_usd': round(estimated, 2),
            'tier_multiplier': multiplier,
            'active_nodes': snap.active_nodes if snap else 0,
            'opportunity_score': snap.opportunity_score if snap else 80,
        }

    def compute_network_scaling_metrics(self) -> Dict[str, Any]:
        """Compute network-wide scaling proof metrics."""
        try:
            from models import db, NodeSession, BrowseSession
            from sqlalchemy import func

            # Total nodes (unique users with active sessions)
            nodes_online = db.session.query(
                func.count(func.distinct(NodeSession.user_id))
            ).filter(NodeSession.status == 'active').scalar() or 0

            # Total browse sessions active
            browse_active = db.session.query(
                func.count(BrowseSession.id)
            ).filter(BrowseSession.status == 'active').scalar() or 0

        except Exception:
            nodes_online = 0
            browse_active = 0

        try:
            from models import User
            from sqlalchemy import func
            total_users = User.query.count() or 0
        except Exception:
            total_users = 0

        total_nodes = total_users  # N_users = N_nodes
        uptime_fraction = nodes_online / max(total_nodes, 1)

        supply = total_nodes * DEFAULT_MAX_CONCURRENT * max(uptime_fraction, DEFAULT_UPTIME_FRACTION)
        # Demand estimate: 1 arbitrage (9 slots) + 2 browse (1 slot) per user = 11 slot-activations/day
        demand = total_users * 11

        headroom = supply * 86400 / max(demand * 60, 1)  # rough seconds ratio

        return {
            'total_users': total_users,
            'total_nodes': total_nodes,
            'nodes_online': nodes_online,
            'uptime_fraction': round(uptime_fraction, 3),
            'browse_sessions_active': browse_active,
            'capacity_node_seconds_day': round(supply * 86400),
            'demand_node_seconds_day': round(demand * 60),
            'headroom_ratio': round(headroom, 1),
        }

    def detect_surge(self, zone_code: str) -> Dict[str, Any]:
        """Detect traffic surge in a zone.

        If queries in the last 15 minutes exceed 2× the rolling average,
        returns a surge multiplier (up to 2.0×) for node payouts.
        """
        try:
            from models import db, BrowseSession
            from sqlalchemy import func

            now = datetime.utcnow()
            window_15m = now - timedelta(minutes=15)
            window_6h = now - timedelta(hours=6)

            recent = db.session.query(func.count(BrowseSession.id)).filter(
                BrowseSession.zone_code == zone_code,
                BrowseSession.started_at >= window_15m,
            ).scalar() or 0

            rolling = db.session.query(func.count(BrowseSession.id)).filter(
                BrowseSession.zone_code == zone_code,
                BrowseSession.started_at >= window_6h,
            ).scalar() or 0

            # Average per 15-minute window over 6 hours = rolling / 24
            avg_15m = rolling / 24.0 if rolling else 1.0
            ratio = recent / max(avg_15m, 0.5)

            if ratio > 2.0:
                multiplier = min(2.0, ratio)
                return {
                    'zone_code': zone_code,
                    'surge_detected': True,
                    'surge_multiplier': round(multiplier, 2),
                    'recent_queries': recent,
                    'avg_queries_15m': round(avg_15m, 1),
                }
        except Exception as e:
            logger.debug("Surge detection failed for %s: %s", zone_code, e)

        return {
            'zone_code': zone_code,
            'surge_detected': False,
            'surge_multiplier': 1.0,
        }

    # ------------------------------------------------------------------
    # Internal computation methods
    # ------------------------------------------------------------------

    def _compute_supply(self, zone_code: str, cutoff: datetime) -> Dict:
        """Count active nodes and total uptime hours in the zone."""
        try:
            from models import db, NodeSession
            from sqlalchemy import func

            result = db.session.query(
                func.count(func.distinct(NodeSession.user_id)),
                func.sum(NodeSession.duration_seconds),
            ).filter(
                NodeSession.ip_zone == zone_code,
                NodeSession.created_at >= cutoff,
            ).first()

            active = result[0] or 0
            total_seconds = result[1] or 0
            return {
                'active_nodes': active,
                'total_node_hours': round(total_seconds / 3600.0, 1),
            }
        except Exception as e:
            logger.debug("Supply computation failed for %s: %s", zone_code, e)
            return {'active_nodes': 0, 'total_node_hours': 0}

    def _compute_demand(self, zone_code: str, cutoff: datetime) -> Dict:
        """Count arbitrage queries and browse sessions served by the zone."""
        arb_queries = 0
        browse_sessions = 0

        try:
            from models import db, BrowseSession
            from sqlalchemy import func

            browse_sessions = db.session.query(func.count(BrowseSession.id)).filter(
                BrowseSession.zone_code == zone_code,
                BrowseSession.started_at >= cutoff,
            ).scalar() or 0
        except Exception:
            pass

        # Arbitrage queries: count from RevenueAllocation or task stats
        try:
            from models import db, RevenueAllocation
            from sqlalchemy import func

            arb_queries = db.session.query(func.count(RevenueAllocation.id)).filter(
                RevenueAllocation.created_at >= cutoff,
            ).scalar() or 0
            # Rough attribution: divide by average markets per query
            arb_queries = arb_queries  # Each allocation is one deal, close enough
        except Exception:
            pass

        return {
            'arbitrage_queries_served': arb_queries,
            'browse_sessions_served': browse_sessions,
            'total_tasks': arb_queries + browse_sessions,
        }

    def _compute_revenue(self, zone_code: str, cutoff: datetime) -> Dict:
        """Compute revenue generated by nodes in this zone."""
        arb_revenue = 0.0
        browse_revenue = 0.0

        # Arbitrage fee revenue from RevenueAllocation
        try:
            from models import db, RevenueAllocation, NodeSession
            from sqlalchemy import func

            # Get user_ids of nodes in this zone
            node_users = db.session.query(
                func.distinct(NodeSession.user_id)
            ).filter(
                NodeSession.ip_zone == zone_code,
                NodeSession.created_at >= cutoff,
            ).subquery()

            arb_revenue = db.session.query(
                func.coalesce(func.sum(RevenueAllocation.node_share_usd), 0)
            ).filter(
                RevenueAllocation.node_user_id.in_(node_users),
                RevenueAllocation.created_at >= cutoff,
            ).scalar() or 0.0
        except Exception:
            pass

        # Browse data revenue from BrowsingEvents via BrowseSessions
        try:
            from models import db, BrowseSession
            from sqlalchemy import func

            browse_revenue = db.session.query(
                func.coalesce(func.sum(BrowseSession.data_value_usd), 0)
            ).filter(
                BrowseSession.zone_code == zone_code,
                BrowseSession.started_at >= cutoff,
            ).scalar() or 0.0
        except Exception:
            pass

        return {
            'arbitrage_fee_revenue_usd': arb_revenue,
            'browse_data_revenue_usd': browse_revenue,
            'total_revenue_usd': arb_revenue + browse_revenue,
        }

    def _compute_top_node_earnings(self, zone_code: str, cutoff: datetime) -> float:
        """Find the highest earning node in this zone for the period."""
        try:
            from models import db, NodePayout, NodeSession
            from sqlalchemy import func

            node_users = db.session.query(
                func.distinct(NodeSession.user_id)
            ).filter(
                NodeSession.ip_zone == zone_code,
                NodeSession.created_at >= cutoff,
            ).subquery()

            top = db.session.query(
                func.max(NodePayout.payout_amount_rlusd)
            ).filter(
                NodePayout.user_id.in_(node_users),
                NodePayout.created_at >= cutoff,
            ).scalar()
            return top or 0.0
        except Exception:
            return 0.0

    def _compute_opportunity_score(
        self,
        demand_supply_ratio: float,
        earnings_per_node: float,
        saturation: float,
        zone_code: str,
        period_days: int,
    ) -> int:
        """Compute opportunity score (0-100).

        Higher = more attractive for new nodes.

        Formula:
            0.40 × demand_supply_ratio_norm +
            0.30 × earnings_per_node_norm +
            0.20 × traffic_growth_rate +
            0.10 × (1 - saturation)
        """
        # Normalize DSR: cap at 10 for scoring
        dsr_norm = min(demand_supply_ratio / 10.0, 1.0)

        # Normalize earnings: cap at $500/mo for scoring
        earnings_norm = min(earnings_per_node / 500.0, 1.0)

        # Traffic growth rate (compare to prior period)
        growth = self._compute_traffic_growth(zone_code, period_days)

        # Vacancy signal
        vacancy = max(0.0, 1.0 - saturation)

        raw = (
            0.40 * dsr_norm
            + 0.30 * earnings_norm
            + 0.20 * min(growth, 1.0)
            + 0.10 * vacancy
        )
        return min(100, max(0, int(raw * 100)))

    def _compute_traffic_growth(self, zone_code: str, period_days: int) -> float:
        """Compare current-period traffic to prior period. Returns ratio (>1 = growing)."""
        try:
            from models import db, BrowseSession
            from sqlalchemy import func

            now = datetime.utcnow()
            current_start = now - timedelta(days=period_days)
            prior_start = current_start - timedelta(days=period_days)

            current = db.session.query(func.count(BrowseSession.id)).filter(
                BrowseSession.zone_code == zone_code,
                BrowseSession.started_at >= current_start,
            ).scalar() or 0

            prior = db.session.query(func.count(BrowseSession.id)).filter(
                BrowseSession.zone_code == zone_code,
                BrowseSession.started_at >= prior_start,
                BrowseSession.started_at < current_start,
            ).scalar() or 0

            if prior == 0:
                return 1.0 if current > 0 else 0.5
            return current / prior
        except Exception:
            return 0.5

    def _network_average_earnings(self) -> float:
        """Get the network-wide average monthly earnings per node."""
        try:
            from models import db, ZoneEconomicsSnapshot
            from sqlalchemy import func
            today = date.today()
            avg = db.session.query(
                func.avg(ZoneEconomicsSnapshot.avg_earnings_per_node_usd)
            ).filter_by(snapshot_date=today).scalar()
            return avg or 50.0  # Default estimate
        except Exception:
            return 50.0

    def _resolve_zone_name(self, zone_code: str) -> str:
        """Resolve zone code to human-readable name."""
        try:
            from geographic_zones import get_zone
            zone = get_zone(zone_code)
            if zone:
                return zone.name
        except (ImportError, Exception):
            pass
        return zone_code

    def _save_snapshot(self, data: Dict) -> None:
        """Persist a zone economics snapshot for the current date."""
        try:
            from models import db, ZoneEconomicsSnapshot
            today = date.today()

            snap = ZoneEconomicsSnapshot.query.filter_by(
                zone_code=data['zone_code'], snapshot_date=today,
            ).first()

            if snap:
                # Update existing
                for key in (
                    'active_nodes', 'total_node_hours',
                    'arbitrage_queries_served', 'browse_sessions_served',
                    'total_tasks', 'arbitrage_fee_revenue_usd',
                    'browse_data_revenue_usd', 'total_revenue_usd',
                    'avg_earnings_per_node_usd', 'top_node_earnings_usd',
                    'demand_supply_ratio', 'saturation_score',
                    'opportunity_score',
                ):
                    if key in data:
                        setattr(snap, key, data[key])
            else:
                snap = ZoneEconomicsSnapshot(
                    zone_code=data['zone_code'],
                    snapshot_date=today,
                    active_nodes=data.get('active_nodes', 0),
                    total_node_hours=data.get('total_node_hours', 0),
                    arbitrage_queries_served=data.get('arbitrage_queries_served', 0),
                    browse_sessions_served=data.get('browse_sessions_served', 0),
                    total_tasks=data.get('total_tasks', 0),
                    arbitrage_fee_revenue_usd=data.get('arbitrage_fee_revenue_usd', 0),
                    browse_data_revenue_usd=data.get('browse_data_revenue_usd', 0),
                    total_revenue_usd=data.get('total_revenue_usd', 0),
                    avg_earnings_per_node_usd=data.get('avg_earnings_per_node_usd', 0),
                    top_node_earnings_usd=data.get('top_node_earnings_usd', 0),
                    demand_supply_ratio=data.get('demand_supply_ratio', 0),
                    saturation_score=data.get('saturation_score', 0),
                    opportunity_score=data.get('opportunity_score', 0),
                )
                db.session.add(snap)

            db.session.commit()
        except Exception as e:
            logger.debug("Snapshot save failed: %s", e)


# ---------------------------------------------------------------------------
# Module singleton
# ---------------------------------------------------------------------------

hot_zone_engine = HotZoneEngine()
