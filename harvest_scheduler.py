"""
harvest_scheduler.py — Autonomous Data Harvesting Scheduler (Build #79)

Transforms Phoenix from reactive (responds to user searches) to proactive
(continuously harvests pricing data to build a proprietary dataset).

The scheduler:
1. Identifies observation gaps in pricing zones
2. Scores gaps by priority (density, staleness, commercial value)
3. Generates scrape tasks and routes them to consented nodes
4. Processes commercial buyer standing orders
5. Tracks harvest performance and budget utilization

Integration points:
- citizenserp_tasks: task_registry.create_task(), task_dispatcher.dispatch()
- pricing_zones: zone_engine.get_observation_gaps()
- node_registry: node_registry.discover_nodes()
- node_consent_economy: NodeConsentProfile consent checks
"""

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CONSENT_MAP = {
    "flight_search": "consent_price_observations",
    "hotel_search": "consent_price_observations",
    "cruise_search": "consent_price_observations",
    "rental_search": "consent_price_observations",
    "price_monitor": "consent_price_observations",
    "ad_intelligence": "consent_ad_impressions",
    "social_signal_extract": "consent_social_signals",
    "pricing_intelligence_deep": "consent_business_data",
}

VERTICAL_CONFIG = {
    "flight": {
        "task_type": "flight_search",
        "min_observations": 10,
        "stale_hours": 12,
        "max_per_hour": 20,
        "max_per_day": 200,
    },
    "hotel": {
        "task_type": "hotel_search",
        "min_observations": 8,
        "stale_hours": 24,
        "max_per_hour": 15,
        "max_per_day": 150,
    },
    "cruise": {
        "task_type": "cruise_search",
        "min_observations": 5,
        "stale_hours": 48,
        "max_per_hour": 10,
        "max_per_day": 100,
    },
    "rental": {
        "task_type": "rental_search",
        "min_observations": 5,
        "stale_hours": 24,
        "max_per_hour": 10,
        "max_per_day": 100,
    },
}

HIGH_VALUE_ZONES = [
    "US-NE", "US-SC", "US-NW", "US-SE", "US-MW",
    "GB-LN", "GB-SE",
    "JP-KT", "JP-KN",
    "DE-NW", "DE-BY",
    "FR-IF",
    "AU-NS", "AU-VI",
    "KR-SL",
    "SG",
    "AE-DU",
]

# Popular origin airports per zone for flight harvesting
ZONE_AIRPORTS = {
    "US-NE": ["JFK", "EWR", "BOS", "PHL"],
    "US-SE": ["MIA", "ATL", "MCO", "FLL"],
    "US-SC": ["DFW", "IAH", "AUS"],
    "US-NW": ["SEA", "PDX", "SFO"],
    "US-SW": ["LAX", "SAN", "PHX", "LAS"],
    "US-MW": ["ORD", "DTW", "MSP"],
    "US-MT": ["DEN", "SLC"],
    "US-NC": ["CLT", "RDU"],
    "GB-LN": ["LHR", "LGW", "STN"],
    "GB-SE": ["LHR", "LGW"],
    "JP-KT": ["NRT", "HND"],
    "JP-KN": ["KIX", "ITM"],
    "DE-NW": ["FRA", "DUS"],
    "DE-BY": ["MUC"],
    "FR-IF": ["CDG", "ORY"],
    "AU-NS": ["SYD"],
    "AU-VI": ["MEL"],
    "KR-SL": ["ICN"],
    "SG": ["SIN"],
    "AE-DU": ["DXB"],
    "BR-SE": ["GRU"],
    "IN-WE": ["BOM"],
    "IN-NC": ["DEL"],
    "CA-ON": ["YYZ"],
    "CA-BC": ["YVR"],
}

# Popular cruise departure ports per zone
ZONE_CRUISE_PORTS = {
    "US-SE": ["Miami", "Fort Lauderdale", "Tampa"],
    "US-NE": ["New York", "Cape Liberty"],
    "US-SC": ["Galveston", "New Orleans"],
    "US-NW": ["Seattle"],
    "US-SW": ["Los Angeles", "San Francisco"],
    "GB-LN": ["Southampton"],
    "AU-NS": ["Sydney"],
    "SG": ["Singapore"],
    "AE-DU": ["Dubai"],
}

# Major cities per zone for hotel/rental harvesting
ZONE_CITIES = {
    "US-NE": ["New York", "Boston", "Philadelphia"],
    "US-SE": ["Miami", "Atlanta", "Orlando"],
    "US-SC": ["Dallas", "Houston", "Austin"],
    "US-NW": ["Seattle", "Portland", "San Francisco"],
    "US-SW": ["Los Angeles", "San Diego", "Las Vegas", "Phoenix"],
    "US-MW": ["Chicago", "Detroit", "Minneapolis"],
    "US-MT": ["Denver", "Salt Lake City"],
    "GB-LN": ["London"],
    "GB-SE": ["London", "Brighton"],
    "JP-KT": ["Tokyo", "Yokohama"],
    "JP-KN": ["Osaka", "Kyoto"],
    "DE-NW": ["Frankfurt", "Düsseldorf", "Cologne"],
    "DE-BY": ["Munich"],
    "FR-IF": ["Paris"],
    "AU-NS": ["Sydney"],
    "AU-VI": ["Melbourne"],
    "KR-SL": ["Seoul"],
    "SG": ["Singapore"],
    "AE-DU": ["Dubai"],
    "BR-SE": ["São Paulo", "Rio de Janeiro"],
    "IN-WE": ["Mumbai"],
    "IN-NC": ["Delhi"],
    "CA-ON": ["Toronto"],
    "CA-BC": ["Vancouver"],
}

# Popular international destination airports for flight gap-filling
POPULAR_DESTINATIONS = [
    "LHR", "CDG", "NRT", "HND", "FCO", "BCN", "AMS",
    "SIN", "BKK", "HKG", "DXB", "ICN", "SYD", "MEL",
    "CUN", "GRU", "LIS", "ATH", "IST", "MUC", "ZRH",
]

GLOBAL_MAX_TASKS_PER_HOUR = 500
GLOBAL_MAX_TASKS_PER_DAY = 5000
HARVEST_CYCLE_INTERVAL = 600  # 10 minutes
MAX_TARGETS_PER_CYCLE = 50

# Priority scoring weights
WEIGHT_DENSITY = 0.35
WEIGHT_STALENESS = 0.30
WEIGHT_HIGH_VALUE = 0.20
WEIGHT_NODE_AVAILABILITY = 0.15


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ObservationGap:
    """A zone × vertical pair with insufficient recent observations."""
    zone_id: str
    vertical: str
    observation_count: int
    staleness_hours: float
    density_score: float
    active_node_count: int
    priority_score: float = 0.0


@dataclass
class HarvestTarget:
    """A specific harvest task to dispatch."""
    source: str  # "gap_fill" | "standing_order" | "popular_route"
    zone_id: str
    vertical: str
    task_type: str
    params: Dict[str, Any]
    priority_score: float
    order_id: Optional[str] = None


@dataclass
class HarvestCycleResult:
    """Summary of a single harvest cycle execution."""
    cycle_id: str
    standing_orders_processed: int = 0
    gaps_identified: int = 0
    targets_generated: int = 0
    tasks_dispatched: int = 0
    tasks_skipped_no_node: int = 0
    tasks_skipped_no_consent: int = 0
    tasks_skipped_budget: int = 0
    duration_ms: float = 0.0


# ---------------------------------------------------------------------------
# HarvestScheduler
# ---------------------------------------------------------------------------

class HarvestScheduler:
    """
    Autonomous data harvesting scheduler.

    Runs on a 10-minute cycle to:
    1. Process commercial buyer standing orders (highest priority)
    2. Identify and fill observation gaps in pricing zones
    3. Respect consent, budgets, and node capacity
    4. Track performance metrics
    """

    def __init__(self):
        self._global_tasks_this_hour = 0
        self._global_tasks_today = 0
        self._global_hour_reset = datetime.utcnow().replace(
            minute=0, second=0, microsecond=0
        ) + timedelta(hours=1)
        self._global_day_reset = (datetime.utcnow() + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        self._last_cycle_result: Optional[HarvestCycleResult] = None

    # ------------------------------------------------------------------
    # Main cycle
    # ------------------------------------------------------------------

    def run_harvest_cycle(self) -> HarvestCycleResult:
        """Execute one full harvest cycle. Called every 10 minutes."""
        start = time.time()
        cycle_id = f"HRV-{os.urandom(6).hex()}"

        result = HarvestCycleResult(cycle_id=cycle_id)

        try:
            # 1. Reset expired budgets
            self._reset_global_counters()
            self.reset_expired_budgets()

            # 2. Execute standing orders (commercial priority)
            order_targets = self.execute_standing_orders()
            result.standing_orders_processed = len(order_targets)

            # 3. Identify observation gaps
            gaps = self.identify_observation_gaps()
            result.gaps_identified = len(gaps)

            # 4. Score and generate tasks for gaps
            gap_targets = self._generate_gap_targets(gaps)

            # 5. Merge all targets, sort by priority
            all_targets = order_targets + gap_targets
            all_targets.sort(key=lambda t: t.priority_score, reverse=True)

            # Cap at max per cycle
            all_targets = all_targets[:MAX_TARGETS_PER_CYCLE]
            result.targets_generated = len(all_targets)

            # 6. Dispatch
            dispatch_result = self.dispatch_targets(all_targets)
            result.tasks_dispatched = dispatch_result["dispatched"]
            result.tasks_skipped_no_node = dispatch_result["skipped_no_node"]
            result.tasks_skipped_no_consent = dispatch_result["skipped_no_consent"]
            result.tasks_skipped_budget = dispatch_result["skipped_budget"]

            # 7. Record execution
            self._record_execution(result, all_targets)

        except Exception as e:
            logger.error(f"Harvest cycle {cycle_id} failed: {e}")

        result.duration_ms = round((time.time() - start) * 1000, 1)
        self._last_cycle_result = result

        if result.tasks_dispatched > 0:
            logger.info(
                f"Harvest {cycle_id}: {result.tasks_dispatched} dispatched, "
                f"{result.gaps_identified} gaps, "
                f"{result.standing_orders_processed} standing orders"
            )

        return result

    # ------------------------------------------------------------------
    # Standing orders
    # ------------------------------------------------------------------

    def execute_standing_orders(self) -> List[HarvestTarget]:
        """Process active standing orders that are due for refresh."""
        targets = []
        try:
            from models import StandingOrder, db

            now = datetime.utcnow()
            orders = StandingOrder.query.filter_by(is_active=True).all()

            for order in orders:
                # Check if refresh interval has elapsed
                if order.last_executed_at:
                    next_run = order.last_executed_at + timedelta(
                        hours=order.refresh_interval_hours
                    )
                    if now < next_run:
                        continue

                # Check daily spend cap
                today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
                if order.last_executed_at and order.last_executed_at >= today_start:
                    estimated_cost = (
                        order.max_tasks_per_cycle * order.price_per_observation_usd
                    )
                    if order.total_spent_usd + estimated_cost > order.max_spend_per_day_usd:
                        logger.debug(
                            f"Standing order {order.order_id} daily spend cap reached"
                        )
                        continue

                # Generate tasks from order
                order_targets = self.generate_tasks_for_order(order)
                targets.extend(order_targets)

                # Update execution timestamp
                order.last_executed_at = now
                db.session.commit()

        except ImportError:
            logger.debug("models not available for standing orders")
        except Exception as e:
            logger.error(f"Standing order execution error: {e}")

        return targets

    def generate_tasks_for_order(self, order) -> List[HarvestTarget]:
        """Generate harvest targets from a standing order's filters."""
        targets = []
        try:
            filters = json.loads(order.filters) if order.filters else {}
            zone_ids = json.loads(order.zone_ids) if order.zone_ids else []

            vertical = order.vertical
            config = VERTICAL_CONFIG.get(vertical)
            if not config:
                return targets

            task_type = config["task_type"]

            for zone_id in zone_ids[:order.max_tasks_per_cycle]:
                params = self._build_params_from_filters(
                    vertical, zone_id, filters
                )
                if params:
                    targets.append(
                        HarvestTarget(
                            source="standing_order",
                            zone_id=zone_id,
                            vertical=vertical,
                            task_type=task_type,
                            params=params,
                            priority_score=95.0,  # Standing orders get near-max priority
                            order_id=order.order_id,
                        )
                    )
        except Exception as e:
            logger.error(f"Error generating tasks for order {order.order_id}: {e}")

        return targets

    def _build_params_from_filters(
        self, vertical: str, zone_id: str, filters: dict
    ) -> Optional[dict]:
        """Build task params from order filters, falling back to zone defaults."""
        params = dict(filters)
        params["market"] = zone_id[:2]  # Country code from zone_id

        if vertical == "flight":
            if "origin" not in params:
                airports = ZONE_AIRPORTS.get(zone_id, [])
                if airports:
                    params["origin"] = airports[0]
            if "destination" not in params:
                params["destination"] = POPULAR_DESTINATIONS[0]
            if "date" not in params:
                params["date"] = (
                    datetime.utcnow() + timedelta(days=14)
                ).strftime("%Y-%m-%d")

        elif vertical == "hotel":
            if "city" not in params:
                cities = ZONE_CITIES.get(zone_id, [])
                if cities:
                    params["city"] = cities[0]
            if "check_in" not in params:
                params["check_in"] = (
                    datetime.utcnow() + timedelta(days=14)
                ).strftime("%Y-%m-%d")
            if "nights" not in params:
                params["nights"] = 2

        elif vertical == "cruise":
            if "departure_port" not in params:
                ports = ZONE_CRUISE_PORTS.get(zone_id, [])
                if ports:
                    params["departure_port"] = ports[0]
            if "departure_date" not in params:
                params["departure_date"] = (
                    datetime.utcnow() + timedelta(days=30)
                ).strftime("%Y-%m-%d")

        elif vertical == "rental":
            if "pickup_location" not in params:
                cities = ZONE_CITIES.get(zone_id, [])
                if cities:
                    params["pickup_location"] = cities[0]
            if "pickup_date" not in params:
                params["pickup_date"] = (
                    datetime.utcnow() + timedelta(days=14)
                ).strftime("%Y-%m-%d")
            if "rental_days" not in params:
                params["rental_days"] = 5

        return params

    # ------------------------------------------------------------------
    # Gap detection & scoring
    # ------------------------------------------------------------------

    def identify_observation_gaps(self, hours_back: int = 24) -> List[ObservationGap]:
        """Identify zones × verticals with insufficient recent observations."""
        gaps = []
        try:
            from pricing_zones import zone_engine

            raw_gaps = zone_engine.get_observation_gaps(
                hours_back=hours_back,
                min_observations=5,
                verticals=list(VERTICAL_CONFIG.keys()),
            )

            for g in raw_gaps:
                # Skip zones with no nodes (can't dispatch there)
                if g.get("active_node_count", 0) < 1:
                    continue

                gap = ObservationGap(
                    zone_id=g["zone_id"],
                    vertical=g["vertical"],
                    observation_count=g.get("observation_count", 0),
                    staleness_hours=g.get("staleness_hours", hours_back),
                    density_score=g.get("density_score", 0.0),
                    active_node_count=g.get("active_node_count", 0),
                )
                gap.priority_score = self.score_gap(gap)
                gaps.append(gap)

        except ImportError:
            logger.debug("pricing_zones not available for gap detection")
        except Exception as e:
            logger.error(f"Gap detection error: {e}")

        # Sort by priority descending
        gaps.sort(key=lambda g: g.priority_score, reverse=True)
        return gaps

    def score_gap(self, gap: ObservationGap) -> float:
        """Calculate 0-100 priority score for an observation gap."""
        # Zone density: higher density = more reliable data = worth harvesting
        density_score = min(gap.density_score, 1.0) * 100 * WEIGHT_DENSITY

        # Staleness: older data = higher priority
        stale_config = VERTICAL_CONFIG.get(gap.vertical, {})
        stale_threshold = stale_config.get("stale_hours", 24)
        staleness_score = (
            min(gap.staleness_hours / (stale_threshold * 2), 1.0) * 100 * WEIGHT_STALENESS
        )

        # High-value zone bonus
        is_high_value = gap.zone_id in HIGH_VALUE_ZONES
        high_value_score = (1.0 if is_high_value else 0.3) * 100 * WEIGHT_HIGH_VALUE

        # Node availability
        has_nodes = gap.active_node_count > 0
        node_score = (1.0 if has_nodes else 0.0) * 100 * WEIGHT_NODE_AVAILABILITY

        return round(density_score + staleness_score + high_value_score + node_score, 1)

    # ------------------------------------------------------------------
    # Task generation
    # ------------------------------------------------------------------

    def _generate_gap_targets(self, gaps: List[ObservationGap]) -> List[HarvestTarget]:
        """Convert observation gaps into dispatchable harvest targets."""
        targets = []
        for gap in gaps:
            gap_targets = self.generate_tasks_for_gap(gap)
            targets.extend(gap_targets)
        return targets

    def generate_tasks_for_gap(self, gap: ObservationGap) -> List[HarvestTarget]:
        """Generate 1-3 harvest targets for a single observation gap."""
        targets = []
        config = VERTICAL_CONFIG.get(gap.vertical)
        if not config:
            return targets

        task_type = config["task_type"]

        if gap.vertical == "flight":
            targets.extend(self._generate_flight_targets(gap, task_type))
        elif gap.vertical == "hotel":
            targets.extend(self._generate_hotel_targets(gap, task_type))
        elif gap.vertical == "cruise":
            targets.extend(self._generate_cruise_targets(gap, task_type))
        elif gap.vertical == "rental":
            targets.extend(self._generate_rental_targets(gap, task_type))

        return targets

    def _generate_flight_targets(
        self, gap: ObservationGap, task_type: str
    ) -> List[HarvestTarget]:
        """Generate flight search targets for a zone gap."""
        targets = []
        airports = ZONE_AIRPORTS.get(gap.zone_id, [])
        if not airports:
            # Fallback: use zone's country code to find any airports
            country = gap.zone_id[:2]
            for zid, apts in ZONE_AIRPORTS.items():
                if zid.startswith(country):
                    airports = apts
                    break

        if not airports:
            return targets

        origin = airports[0]

        # Build #80: Blend learned destinations with popular defaults
        learned_dests = []
        try:
            from strategy_learner import strategy_learner
            learned_dests = strategy_learner.get_learned_destinations(limit=10)
        except Exception:
            pass

        import hashlib
        zone_hash = int(hashlib.md5(gap.zone_id.encode()).hexdigest()[:8], 16)

        if learned_dests:
            # Use learned destinations for first pick, popular for second
            l_idx = zone_hash % len(learned_dests)
            p_idx = zone_hash % len(POPULAR_DESTINATIONS)
            destinations = [
                learned_dests[l_idx],
                POPULAR_DESTINATIONS[p_idx],
            ]
        else:
            dest_idx = zone_hash % len(POPULAR_DESTINATIONS)
            destinations = [
                POPULAR_DESTINATIONS[dest_idx],
                POPULAR_DESTINATIONS[(dest_idx + 3) % len(POPULAR_DESTINATIONS)],
            ]

        # Generate for 14 days out
        search_date = (datetime.utcnow() + timedelta(days=14)).strftime("%Y-%m-%d")

        for dest in destinations[:2]:
            if dest == origin:
                continue
            targets.append(
                HarvestTarget(
                    source="gap_fill",
                    zone_id=gap.zone_id,
                    vertical="flight",
                    task_type=task_type,
                    params={
                        "origin": origin,
                        "destination": dest,
                        "date": search_date,
                        "market": gap.zone_id[:2],
                    },
                    priority_score=gap.priority_score,
                )
            )

        return targets

    def _generate_hotel_targets(
        self, gap: ObservationGap, task_type: str
    ) -> List[HarvestTarget]:
        """Generate hotel search targets for a zone gap."""
        targets = []
        cities = ZONE_CITIES.get(gap.zone_id, [])
        if not cities:
            return targets

        check_in = (datetime.utcnow() + timedelta(days=14)).strftime("%Y-%m-%d")

        for city in cities[:2]:
            targets.append(
                HarvestTarget(
                    source="gap_fill",
                    zone_id=gap.zone_id,
                    vertical="hotel",
                    task_type=task_type,
                    params={
                        "city": city,
                        "check_in": check_in,
                        "nights": 2,
                        "guests": 2,
                        "market": gap.zone_id[:2],
                    },
                    priority_score=gap.priority_score,
                )
            )

        return targets

    def _generate_cruise_targets(
        self, gap: ObservationGap, task_type: str
    ) -> List[HarvestTarget]:
        """Generate cruise search targets for a zone gap."""
        targets = []
        ports = ZONE_CRUISE_PORTS.get(gap.zone_id, [])
        if not ports:
            return targets

        departure_date = (datetime.utcnow() + timedelta(days=60)).strftime("%Y-%m-%d")

        targets.append(
            HarvestTarget(
                source="gap_fill",
                zone_id=gap.zone_id,
                vertical="cruise",
                task_type=task_type,
                params={
                    "departure_port": ports[0],
                    "departure_date": departure_date,
                    "duration_nights": 7,
                    "market": gap.zone_id[:2],
                },
                priority_score=gap.priority_score,
            )
        )

        return targets

    def _generate_rental_targets(
        self, gap: ObservationGap, task_type: str
    ) -> List[HarvestTarget]:
        """Generate rental car search targets for a zone gap."""
        targets = []
        cities = ZONE_CITIES.get(gap.zone_id, [])
        if not cities:
            return targets

        pickup_date = (datetime.utcnow() + timedelta(days=14)).strftime("%Y-%m-%d")

        targets.append(
            HarvestTarget(
                source="gap_fill",
                zone_id=gap.zone_id,
                vertical="rental",
                task_type=task_type,
                params={
                    "pickup_location": cities[0],
                    "pickup_date": pickup_date,
                    "rental_days": 5,
                    "vehicle_class": "economy",
                    "market": gap.zone_id[:2],
                },
                priority_score=gap.priority_score,
            )
        )

        return targets

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def dispatch_targets(self, targets: List[HarvestTarget]) -> dict:
        """Dispatch harvest targets to consented nodes."""
        result = {
            "dispatched": 0,
            "skipped_budget": 0,
            "skipped_no_node": 0,
            "skipped_no_consent": 0,
        }

        if not targets:
            return result

        try:
            from citizenserp_tasks import task_registry, task_dispatcher
        except ImportError:
            logger.debug("citizenserp_tasks not available for dispatch")
            return result

        for target in targets:
            # 1. Check budget
            if not self.check_budget(target.zone_id, target.vertical):
                result["skipped_budget"] += 1
                continue

            # 2. Find available node
            node = self._find_node_for_target(target)
            if not node:
                result["skipped_no_node"] += 1
                continue

            # 3. Check consent
            user_id = node.get("user_id")
            if user_id and not self.check_node_consent(user_id, target.task_type):
                result["skipped_no_consent"] += 1
                continue

            # 4. Create and dispatch task
            try:
                task = task_registry.create_task(
                    task_type=target.task_type,
                    params=target.params,
                    market=target.zone_id,
                    priority=9,  # BACKGROUND priority
                    requester_type="system",
                )

                dispatch_ok = task_dispatcher.dispatch(task)
                if dispatch_ok:
                    result["dispatched"] += 1
                    self.increment_budget(target.zone_id, target.vertical)

                    # Update standing order spend if applicable
                    if target.order_id:
                        self._update_standing_order_spend(target.order_id)
                else:
                    result["skipped_no_node"] += 1

            except Exception as e:
                logger.debug(f"Dispatch error for {target.zone_id}/{target.vertical}: {e}")

        return result

    def _find_node_for_target(self, target: HarvestTarget) -> Optional[dict]:
        """Find an available node for a harvest target."""
        try:
            from node_registry import node_registry

            nodes = node_registry.discover_nodes(
                market=target.zone_id,
                task_type=target.task_type,
                require_browser=True,
                min_rating=0.6,
                limit=1,
            )
            return nodes[0] if nodes else None

        except ImportError:
            return None
        except Exception:
            return None

    def _update_standing_order_spend(self, order_id: str):
        """Update standing order spend tracking after dispatch."""
        try:
            from models import StandingOrder, db

            order = StandingOrder.query.filter_by(order_id=order_id).first()
            if order:
                order.total_spent_usd = (order.total_spent_usd or 0) + order.price_per_observation_usd
                order.total_observations_delivered = (order.total_observations_delivered or 0) + 1
                db.session.commit()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Consent checking
    # ------------------------------------------------------------------

    def check_node_consent(self, user_id: int, task_type: str) -> bool:
        """Check if node has consent for the given task type."""
        consent_field = CONSENT_MAP.get(task_type)
        if not consent_field:
            return True  # Unknown task type, allow by default

        try:
            from models import NodeConsentProfile

            profile = NodeConsentProfile.query.filter_by(user_id=user_id).first()
            if not profile:
                return False

            return bool(getattr(profile, consent_field, False))

        except ImportError:
            return True  # Models not available, allow
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Budget management
    # ------------------------------------------------------------------

    def check_budget(self, zone_id: str, vertical: str) -> bool:
        """Check if budget allows another task for this zone × vertical."""
        # Check global limits first
        if self._global_tasks_this_hour >= GLOBAL_MAX_TASKS_PER_HOUR:
            return False
        if self._global_tasks_today >= GLOBAL_MAX_TASKS_PER_DAY:
            return False

        try:
            from models import HarvestBudget

            budget = HarvestBudget.query.filter_by(
                zone_id=zone_id, vertical=vertical
            ).first()

            if budget:
                if budget.tasks_this_hour >= budget.max_tasks_per_hour:
                    return False
                if budget.tasks_today >= budget.max_tasks_per_day:
                    return False

        except ImportError:
            pass
        except Exception:
            pass

        return True

    def increment_budget(self, zone_id: str, vertical: str):
        """Increment budget counters after dispatching a task."""
        self._global_tasks_this_hour += 1
        self._global_tasks_today += 1

        try:
            from models import HarvestBudget, db

            budget = HarvestBudget.query.filter_by(
                zone_id=zone_id, vertical=vertical
            ).first()

            if not budget:
                config = VERTICAL_CONFIG.get(vertical, {})
                now = datetime.utcnow()
                budget = HarvestBudget(
                    zone_id=zone_id,
                    vertical=vertical,
                    max_tasks_per_hour=config.get("max_per_hour", 20),
                    max_tasks_per_day=config.get("max_per_day", 200),
                    tasks_this_hour=0,
                    tasks_today=0,
                    hour_reset_at=now.replace(minute=0, second=0, microsecond=0)
                    + timedelta(hours=1),
                    day_reset_at=(now + timedelta(days=1)).replace(
                        hour=0, minute=0, second=0, microsecond=0
                    ),
                )
                db.session.add(budget)

            budget.tasks_this_hour = (budget.tasks_this_hour or 0) + 1
            budget.tasks_today = (budget.tasks_today or 0) + 1
            db.session.commit()

        except ImportError:
            pass
        except Exception as e:
            logger.debug(f"Budget increment error: {e}")

    def reset_expired_budgets(self) -> int:
        """Reset hourly/daily budget counters that have expired."""
        reset_count = 0
        try:
            from models import HarvestBudget, db

            now = datetime.utcnow()

            # Reset hourly counters
            expired_hourly = HarvestBudget.query.filter(
                HarvestBudget.hour_reset_at <= now
            ).all()

            for budget in expired_hourly:
                budget.tasks_this_hour = 0
                budget.hour_reset_at = now.replace(
                    minute=0, second=0, microsecond=0
                ) + timedelta(hours=1)
                reset_count += 1

            # Reset daily counters
            expired_daily = HarvestBudget.query.filter(
                HarvestBudget.day_reset_at <= now
            ).all()

            for budget in expired_daily:
                budget.tasks_today = 0
                budget.day_reset_at = (now + timedelta(days=1)).replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
                reset_count += 1

            if reset_count > 0:
                db.session.commit()

        except ImportError:
            pass
        except Exception as e:
            logger.debug(f"Budget reset error: {e}")

        return reset_count

    def _reset_global_counters(self):
        """Reset global rate limit counters if time windows have passed."""
        now = datetime.utcnow()

        if now >= self._global_hour_reset:
            self._global_tasks_this_hour = 0
            self._global_hour_reset = now.replace(
                minute=0, second=0, microsecond=0
            ) + timedelta(hours=1)

        if now >= self._global_day_reset:
            self._global_tasks_today = 0
            self._global_day_reset = (now + timedelta(days=1)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )

    # ------------------------------------------------------------------
    # Execution recording
    # ------------------------------------------------------------------

    def _record_execution(
        self, result: HarvestCycleResult, targets: List[HarvestTarget]
    ):
        """Record harvest execution in the database."""
        try:
            from models import HarvestExecution, db

            zones = list({t.zone_id for t in targets})
            verticals = list({t.vertical for t in targets})

            # Build #80: Check if learned destinations were used
            strategy_enhanced = any(
                t.source == "gap_fill" and hasattr(t, 'params')
                and t.params.get("origin") for t in targets
            )
            try:
                from strategy_learner import strategy_learner as sl
                learned = sl.get_learned_destinations(limit=5)
                strategy_enhanced = any(
                    t.params.get("destination") in learned
                    for t in targets if hasattr(t, 'params')
                ) if learned else False
            except Exception:
                strategy_enhanced = False

            metadata = json.dumps({
                "strategy_enhanced": strategy_enhanced,
                "gaps_identified": result.gaps_identified,
            })

            execution = HarvestExecution(
                batch_id=result.cycle_id,
                execution_type="mixed" if len(verticals) > 1 else (verticals[0] if verticals else "none"),
                vertical=verticals[0] if len(verticals) == 1 else None,
                zones_targeted=json.dumps(zones),
                tasks_generated=result.targets_generated,
                tasks_dispatched=result.tasks_dispatched,
                metadata=metadata,
                started_at=datetime.utcnow() - timedelta(
                    milliseconds=result.duration_ms
                ),
                created_at=datetime.utcnow(),
            )
            db.session.add(execution)
            db.session.commit()

            # Build #80: Record harvest observations for strategy learning
            self._record_strategy_observations(result, targets)

        except ImportError:
            pass
        except Exception as e:
            logger.debug(f"Execution recording error: {e}")

    # ------------------------------------------------------------------
    # Performance tracking
    # ------------------------------------------------------------------

    def get_harvest_performance(self, hours_back: int = 24) -> dict:
        """Get harvest performance summary for the given time window."""
        try:
            from models import HarvestExecution

            cutoff = datetime.utcnow() - timedelta(hours=hours_back)
            executions = HarvestExecution.query.filter(
                HarvestExecution.created_at >= cutoff
            ).order_by(HarvestExecution.created_at.desc()).all()

            total_generated = sum(e.tasks_generated or 0 for e in executions)
            total_dispatched = sum(e.tasks_dispatched or 0 for e in executions)
            total_completed = sum(e.tasks_completed or 0 for e in executions)
            total_failed = sum(e.tasks_failed or 0 for e in executions)
            total_observations = sum(e.observations_collected or 0 for e in executions)
            total_payout = sum(e.total_payout_usd or 0 for e in executions)

            # Zone breakdown
            zone_counts: Dict[str, int] = {}
            for e in executions:
                try:
                    zones = json.loads(e.zones_targeted) if e.zones_targeted else []
                    for z in zones:
                        zone_counts[z] = zone_counts.get(z, 0) + 1
                except (json.JSONDecodeError, TypeError):
                    pass

            top_zones = sorted(
                zone_counts.items(), key=lambda x: x[1], reverse=True
            )[:10]

            completion_rate = 0.0
            if total_dispatched > 0:
                completion_rate = round(
                    total_completed / total_dispatched * 100, 1
                )

            return {
                "hours_back": hours_back,
                "total_cycles": len(executions),
                "total_tasks_generated": total_generated,
                "total_tasks_dispatched": total_dispatched,
                "total_tasks_completed": total_completed,
                "total_tasks_failed": total_failed,
                "completion_rate_pct": completion_rate,
                "total_observations_collected": total_observations,
                "total_payout_usd": round(total_payout, 4),
                "top_zones": [{"zone_id": z, "count": c} for z, c in top_zones],
                "global_budget": {
                    "tasks_this_hour": self._global_tasks_this_hour,
                    "max_per_hour": GLOBAL_MAX_TASKS_PER_HOUR,
                    "tasks_today": self._global_tasks_today,
                    "max_per_day": GLOBAL_MAX_TASKS_PER_DAY,
                },
                "last_cycle": self._last_cycle_result.__dict__ if self._last_cycle_result else None,
            }

        except ImportError:
            return {"error": "models not available"}
        except Exception as e:
            return {"error": str(e)}

    def get_standing_order_status(self, order_id: str) -> dict:
        """Get status of a specific standing order."""
        try:
            from models import StandingOrder

            order = StandingOrder.query.filter_by(order_id=order_id).first()
            if not order:
                return {"error": "not_found"}
            return order.to_dict()

        except ImportError:
            return {"error": "models not available"}
        except Exception as e:
            return {"error": str(e)}

    def get_budget_utilization(self) -> dict:
        """Get current budget utilization across all zones and verticals."""
        try:
            from models import HarvestBudget

            budgets = HarvestBudget.query.all()
            utilization = []

            for b in budgets:
                hour_pct = 0.0
                if b.max_tasks_per_hour > 0:
                    hour_pct = round(
                        (b.tasks_this_hour or 0) / b.max_tasks_per_hour * 100, 1
                    )
                day_pct = 0.0
                if b.max_tasks_per_day > 0:
                    day_pct = round(
                        (b.tasks_today or 0) / b.max_tasks_per_day * 100, 1
                    )

                utilization.append({
                    "zone_id": b.zone_id,
                    "vertical": b.vertical,
                    "hour_usage": f"{b.tasks_this_hour or 0}/{b.max_tasks_per_hour}",
                    "hour_pct": hour_pct,
                    "day_usage": f"{b.tasks_today or 0}/{b.max_tasks_per_day}",
                    "day_pct": day_pct,
                })

            utilization.sort(key=lambda u: u["day_pct"], reverse=True)

            return {
                "budgets": utilization,
                "global": {
                    "hour_usage": f"{self._global_tasks_this_hour}/{GLOBAL_MAX_TASKS_PER_HOUR}",
                    "day_usage": f"{self._global_tasks_today}/{GLOBAL_MAX_TASKS_PER_DAY}",
                },
            }

        except ImportError:
            return {"error": "models not available"}
        except Exception as e:
            return {"error": str(e)}

    # ------------------------------------------------------------------
    # Admin operations
    # ------------------------------------------------------------------

    def create_standing_order(
        self,
        account_id: int,
        vertical: str,
        filters: dict,
        zone_ids: list,
        refresh_interval_hours: int = 6,
        max_tasks_per_cycle: int = 10,
        price_per_observation_usd: float = 0.01,
        max_spend_per_day_usd: float = 50.0,
    ) -> dict:
        """Create a new standing order for a commercial buyer."""
        try:
            from models import StandingOrder, db

            order_id = f"SO-{os.urandom(6).hex()}"

            order = StandingOrder(
                order_id=order_id,
                account_id=account_id,
                vertical=vertical,
                filters=json.dumps(filters),
                zone_ids=json.dumps(zone_ids),
                refresh_interval_hours=refresh_interval_hours,
                max_tasks_per_cycle=max_tasks_per_cycle,
                price_per_observation_usd=price_per_observation_usd,
                max_spend_per_day_usd=max_spend_per_day_usd,
                is_active=True,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            db.session.add(order)
            db.session.commit()

            return {"created": True, "order_id": order_id, "order": order.to_dict()}

        except ImportError:
            return {"error": "models not available"}
        except Exception as e:
            return {"error": str(e)}

    def pause_standing_order(self, order_id: str) -> bool:
        """Pause an active standing order."""
        try:
            from models import StandingOrder, db

            order = StandingOrder.query.filter_by(order_id=order_id).first()
            if order:
                order.is_active = False
                order.updated_at = datetime.utcnow()
                db.session.commit()
                return True
            return False

        except Exception:
            return False

    def resume_standing_order(self, order_id: str) -> bool:
        """Resume a paused standing order."""
        try:
            from models import StandingOrder, db

            order = StandingOrder.query.filter_by(order_id=order_id).first()
            if order:
                order.is_active = True
                order.updated_at = datetime.utcnow()
                db.session.commit()
                return True
            return False

        except Exception:
            return False

    def update_budget(
        self,
        zone_id: str,
        vertical: str,
        max_tasks_per_hour: Optional[int] = None,
        max_tasks_per_day: Optional[int] = None,
    ) -> dict:
        """Update harvest budget limits for a zone × vertical."""
        try:
            from models import HarvestBudget, db

            budget = HarvestBudget.query.filter_by(
                zone_id=zone_id, vertical=vertical
            ).first()

            if not budget:
                now = datetime.utcnow()
                budget = HarvestBudget(
                    zone_id=zone_id,
                    vertical=vertical,
                    hour_reset_at=now.replace(minute=0, second=0, microsecond=0)
                    + timedelta(hours=1),
                    day_reset_at=(now + timedelta(days=1)).replace(
                        hour=0, minute=0, second=0, microsecond=0
                    ),
                )
                db.session.add(budget)

            if max_tasks_per_hour is not None:
                budget.max_tasks_per_hour = max_tasks_per_hour
            if max_tasks_per_day is not None:
                budget.max_tasks_per_day = max_tasks_per_day

            db.session.commit()
            return {"updated": True, "budget": budget.to_dict()}

        except ImportError:
            return {"error": "models not available"}
        except Exception as e:
            return {"error": str(e)}

    # ------------------------------------------------------------------
    # Build #80 — Strategy observation bridge
    # ------------------------------------------------------------------

    def _record_strategy_observations(
        self, result: HarvestCycleResult, targets: List[HarvestTarget]
    ):
        """Feed harvest results back to strategy_learner as observations."""
        try:
            from strategy_learner import strategy_learner

            for target in targets:
                if not target.params:
                    continue
                origin = target.params.get("origin", "")
                dest = target.params.get("destination", "")
                market = target.params.get("market", "")
                if not origin or not dest:
                    continue

                strategy_learner.record_observation(
                    query_type="harvest_" + target.vertical,
                    query_category=target.vertical,
                    query_structure=json.dumps({
                        "origin": origin,
                        "destination": dest,
                        "market": market,
                        "source": target.source,
                    }),
                    result_count=result.tasks_dispatched,
                    result_quality_score=(
                        0.8 if result.tasks_dispatched > 0 else 0.2
                    ),
                    markets_found=json.dumps([market]) if market else "[]",
                    source_sites=json.dumps([]),
                )

        except Exception as exc:
            logger.debug(f"_record_strategy_observations failed: {exc}")

    def create_ai_strategy(
        self, destinations: list, markets: list = None,
        vertical: str = "flight", priority: float = 0.7
    ) -> dict:
        """
        Build #80: Allow PhoenixAI to deploy a strategy by creating
        targeted harvest tasks for specific destination+market combos.

        Args:
            destinations: List of IATA airport codes to target.
            markets: Optional list of market codes (default: ["US"]).
            vertical: Travel vertical (default: "flight").
            priority: Priority score for generated targets.

        Returns:
            Summary dict of what was scheduled.
        """
        if not destinations:
            return {"error": "no_destinations"}

        markets = markets or ["US"]
        created = 0

        try:
            from models import StandingOrder, db
            import secrets

            for dest in destinations[:10]:
                dest = str(dest).upper().strip()
                if len(dest) != 3:
                    continue
                for market in markets[:3]:
                    market = str(market).upper().strip()
                    order_id = f"AI-{secrets.token_hex(4).upper()}"
                    order = StandingOrder(
                        order_id=order_id,
                        order_type="ai_strategy",
                        vertical=vertical,
                        origin=None,
                        destination=dest,
                        market=market,
                        frequency_hours=6,
                        priority_score=priority,
                        max_executions=12,
                        is_active=True,
                        created_at=datetime.utcnow(),
                    )
                    db.session.add(order)
                    created += 1

            if created:
                db.session.commit()
                logger.info(
                    f"AI strategy deployed: {created} standing orders "
                    f"for {destinations[:5]} x {markets[:3]}"
                )

            return {
                "orders_created": created,
                "destinations": destinations[:10],
                "markets": markets[:3],
                "vertical": vertical,
            }

        except Exception as exc:
            logger.warning(f"create_ai_strategy failed: {exc}")
            try:
                from models import db
                db.session.rollback()
            except Exception:
                pass
            return {"error": str(exc)}


# ---------------------------------------------------------------------------
# Module singleton
# ---------------------------------------------------------------------------

harvest_scheduler = HarvestScheduler()
