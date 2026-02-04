"""
PHOENIX Intelligence Feedback Loop

Closes the data loop: search results and task outcomes feed back into
Phoenix's intelligence layer for pattern detection, price trend updates,
and autonomous opportunity creation.

Data Flow:
    Task dispatched -> Node executes -> Result returned -> THIS MODULE ->
    -> Updates price history
    -> Detects anomalies (price spikes/drops)
    -> Creates price alerts automatically
    -> Feeds market briefings with fresh data
    -> Triggers re-analysis of affected routes

Usage:
    from intelligence_feedback import feedback_engine

    # After a CitizenSERP task completes:
    feedback_engine.ingest_task_result(task, result)

    # After a user search:
    feedback_engine.ingest_search_result(search_data)

    # Run pattern detection:
    patterns = feedback_engine.detect_patterns(hours_back=24)
"""

import json
import logging
import secrets
import threading
import time
from collections import deque
from datetime import datetime, timedelta
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Anomaly detection thresholds
PRICE_DROP_THRESHOLD = 0.15   # 15% below average -> price_drop
PRICE_SPIKE_THRESHOLD = 0.20  # 20% above average -> price_spike
SAVINGS_OPPORTUNITY_PCT = 10  # Markets with >10% savings
VOLUME_SPIKE_MULTIPLIER = 2.0 # 2x average volume = spike
ANOMALY_LOG_MAX = 1000        # Circular buffer size


class FeedbackEngine:
    """
    Main feedback processor. Ingests task results and search data,
    detects price anomalies, auto-creates opportunities, and triggers
    alerts. All methods are non-blocking with try/except guards.
    """

    def __init__(self):
        self._route_cache: Dict[str, dict] = {}
        self._anomaly_log: deque = deque(maxlen=ANOMALY_LOG_MAX)
        self._stats = {
            "total_ingested": 0,
            "task_results_ingested": 0,
            "search_results_ingested": 0,
            "anomalies_detected": 0,
            "opportunities_created": 0,
            "alerts_triggered": 0,
            "last_ingestion_at": None,
            "started_at": datetime.utcnow().isoformat(),
        }
        self._lock = threading.Lock()

    # -----------------------------------------------------------------
    # Ingest: CitizenSERP Task Results
    # -----------------------------------------------------------------

    def ingest_task_result(self, task_dict: dict, result_dict: dict) -> dict:
        """
        Process a completed CitizenSERP task result.

        Extracts structured price data, records price snapshots, detects
        anomalies, and auto-creates deals when significant drops found.

        Args:
            task_dict: Task definition with origin, destination, market, etc.
            result_dict: Extraction result with prices, status, etc.

        Returns:
            Summary dict of what was processed.
        """
        summary = {
            "ingested": False,
            "prices_recorded": 0,
            "anomalies": [],
            "opportunities": [],
            "alerts_triggered": [],
        }

        try:
            task_type = task_dict.get("task_type", "unknown")
            status = result_dict.get("status", "unknown")

            if status not in ("completed", "success"):
                logger.debug(f"Skipping non-success task result: {status}")
                return summary

            origin = (task_dict.get("origin") or "").upper()
            destination = (task_dict.get("destination") or "").upper()
            market = (task_dict.get("market") or "").upper()

            if not origin or not destination:
                logger.debug("Task result missing origin/destination, skipping")
                return summary

            # Extract price data from result
            prices = self._extract_prices(result_dict)
            if not prices:
                logger.debug(f"No prices extracted from {task_type} result")
                return summary

            # Record price snapshots via search_tracker
            recorded = self._record_price_snapshots(
                origin, destination, market, prices, task_type
            )
            summary["prices_recorded"] = recorded

            # Check each price for anomalies
            for price_entry in prices:
                price_val = price_entry.get("price_usd")
                price_market = price_entry.get("market", market)
                if price_val is None or not price_market:
                    continue

                anomaly = self.detect_price_anomaly(
                    route=(origin, destination),
                    market=price_market,
                    current_price=price_val,
                    currency=price_entry.get("currency", "USD"),
                )
                if anomaly:
                    summary["anomalies"].append(anomaly)

                    # Auto-create opportunity for significant drops
                    if anomaly["direction"] == "price_drop":
                        opp = self.auto_create_opportunity({
                            **anomaly,
                            "origin": origin,
                            "destination": destination,
                            "market": price_market,
                            "price_usd": price_val,
                            "airline": price_entry.get("airline"),
                            "task_type": task_type,
                        })
                        if opp:
                            summary["opportunities"].append(opp)

                # Check price alerts
                triggered = self.check_triggered_alerts(
                    route=(origin, destination),
                    market=price_market,
                    price=price_val,
                )
                summary["alerts_triggered"].extend(triggered)

                # Update route cache
                self.update_route_cache(origin, destination, price_market, {
                    "price_usd": price_val,
                    "airline": price_entry.get("airline"),
                    "source": task_type,
                })

            summary["ingested"] = True

            # Update stats
            with self._lock:
                self._stats["total_ingested"] += 1
                self._stats["task_results_ingested"] += 1
                self._stats["last_ingestion_at"] = datetime.utcnow().isoformat()

            # Emit SSE event for dashboard
            self._emit_event("admin", "task_result_ingested", {
                "route": f"{origin}-{destination}",
                "market": market,
                "prices_recorded": recorded,
                "anomalies_count": len(summary["anomalies"]),
            })

        except Exception as e:
            logger.error(f"ingest_task_result failed: {e}")

        return summary

    # -----------------------------------------------------------------
    # Ingest: User Search Results
    # -----------------------------------------------------------------

    def ingest_search_result(self, search_data: dict) -> dict:
        """
        Process a user search result.

        Args:
            search_data: Dict with origin, destination, market, prices[],
                         savings_percent, searched_at.

        Returns:
            Processing summary dict.
        """
        summary = {
            "ingested": False,
            "recorded": False,
            "cache_updated": False,
            "alerts_triggered": [],
        }

        try:
            origin = (search_data.get("origin") or "").upper()
            destination = (search_data.get("destination") or "").upper()
            market = (search_data.get("market") or "").upper()
            prices = search_data.get("prices", [])

            if not origin or not destination:
                return summary

            # Record in SearchHistory if user_id present
            user_id = search_data.get("user_id")
            if user_id and prices:
                try:
                    from search_tracker import tracker
                    tracker.record_search(
                        user_id=user_id,
                        origin=origin,
                        destination=destination,
                        departure_date=search_data.get("departure_date",
                                                       datetime.utcnow().date().isoformat()),
                        results=prices,
                        method=search_data.get("method", "feedback_ingest"),
                        markets_searched=search_data.get("markets_searched"),
                    )
                    summary["recorded"] = True
                except Exception as e:
                    logger.debug(f"Failed to record search via tracker: {e}")

            # Update route cache with best price
            best_price = None
            best_market = market
            for p in prices:
                price_val = p.get("price_usd") or p.get("price")
                if price_val is not None:
                    price_val = float(price_val)
                    p_market = p.get("market", market)
                    if best_price is None or price_val < best_price:
                        best_price = price_val
                        best_market = p_market

                    # Check alerts for each price point
                    triggered = self.check_triggered_alerts(
                        route=(origin, destination),
                        market=p_market,
                        price=price_val,
                    )
                    summary["alerts_triggered"].extend(triggered)

            if best_price is not None:
                self.update_route_cache(origin, destination, best_market, {
                    "price_usd": best_price,
                    "source": "user_search",
                })
                summary["cache_updated"] = True

            summary["ingested"] = True

            with self._lock:
                self._stats["total_ingested"] += 1
                self._stats["search_results_ingested"] += 1
                self._stats["last_ingestion_at"] = datetime.utcnow().isoformat()

        except Exception as e:
            logger.error(f"ingest_search_result failed: {e}")

        return summary

    # -----------------------------------------------------------------
    # Pattern Detection
    # -----------------------------------------------------------------

    def detect_patterns(self, hours_back: int = 24) -> dict:
        """
        Run pattern detection on recent data.

        Returns categorized pattern dict with:
        - price_trends: rising/falling/stable per route per market
        - volume_spikes: routes with sudden search volume increases
        - savings_opportunities: markets with >10% savings appearing
        - new_routes: routes with searches but no price history
        """
        patterns = {
            "price_trends": [],
            "volume_spikes": [],
            "savings_opportunities": [],
            "new_routes": [],
            "analyzed_at": datetime.utcnow().isoformat(),
            "hours_back": hours_back,
        }

        try:
            from models import db, SearchHistory, PriceHistory

            cutoff = datetime.utcnow() - timedelta(hours=hours_back)

            # --- Price trends: aggregate recent prices by route+market ---
            try:
                recent_prices = db.session.query(
                    PriceHistory.origin,
                    PriceHistory.destination,
                    PriceHistory.market,
                    db.func.avg(PriceHistory.price_usd).label("avg_price"),
                    db.func.min(PriceHistory.price_usd).label("min_price"),
                    db.func.max(PriceHistory.price_usd).label("max_price"),
                    db.func.count(PriceHistory.id).label("samples"),
                ).filter(
                    PriceHistory.recorded_at >= cutoff,
                ).group_by(
                    PriceHistory.origin, PriceHistory.destination, PriceHistory.market,
                ).having(db.func.count(PriceHistory.id) >= 2).all()

                for row in recent_prices:
                    # Compare to 7-day average for trend direction
                    week_cutoff = datetime.utcnow() - timedelta(days=7)
                    week_avg = db.session.query(
                        db.func.avg(PriceHistory.price_usd)
                    ).filter(
                        PriceHistory.origin == row.origin,
                        PriceHistory.destination == row.destination,
                        PriceHistory.market == row.market,
                        PriceHistory.recorded_at >= week_cutoff,
                        PriceHistory.recorded_at < cutoff,
                    ).scalar()

                    direction = "stable"
                    if week_avg and row.avg_price:
                        change_pct = ((row.avg_price - week_avg) / week_avg) * 100
                        if change_pct > 5:
                            direction = "rising"
                        elif change_pct < -5:
                            direction = "falling"

                    patterns["price_trends"].append({
                        "route": f"{row.origin}-{row.destination}",
                        "market": row.market,
                        "direction": direction,
                        "avg_price": round(row.avg_price, 2),
                        "min_price": round(row.min_price, 2),
                        "samples": row.samples,
                    })
            except Exception as e:
                logger.debug(f"Price trend detection failed: {e}")

            # --- Volume spikes: compare recent search volume to baseline ---
            try:
                baseline_start = cutoff - timedelta(hours=hours_back * 7)
                recent_volume = db.session.query(
                    SearchHistory.origin,
                    SearchHistory.destination,
                    db.func.count(SearchHistory.id).label("recent_count"),
                ).filter(
                    SearchHistory.created_at >= cutoff,
                ).group_by(
                    SearchHistory.origin, SearchHistory.destination,
                ).all()

                for row in recent_volume:
                    baseline_count = db.session.query(
                        db.func.count(SearchHistory.id)
                    ).filter(
                        SearchHistory.origin == row.origin,
                        SearchHistory.destination == row.destination,
                        SearchHistory.created_at >= baseline_start,
                        SearchHistory.created_at < cutoff,
                    ).scalar() or 0

                    # Normalize baseline to same time window
                    baseline_avg = baseline_count / 7.0 if baseline_count > 0 else 0
                    if baseline_avg > 0 and row.recent_count > baseline_avg * VOLUME_SPIKE_MULTIPLIER:
                        patterns["volume_spikes"].append({
                            "route": f"{row.origin}-{row.destination}",
                            "recent_searches": row.recent_count,
                            "baseline_avg": round(baseline_avg, 1),
                            "spike_ratio": round(row.recent_count / baseline_avg, 1),
                        })
            except Exception as e:
                logger.debug(f"Volume spike detection failed: {e}")

            # --- Savings opportunities: markets showing >10% savings ---
            try:
                savings_rows = db.session.query(
                    SearchHistory.origin,
                    SearchHistory.destination,
                    SearchHistory.best_market,
                    db.func.avg(SearchHistory.max_savings_percent).label("avg_savings"),
                    db.func.count(SearchHistory.id).label("count"),
                ).filter(
                    SearchHistory.created_at >= cutoff,
                    SearchHistory.max_savings_percent >= SAVINGS_OPPORTUNITY_PCT,
                    SearchHistory.best_market.isnot(None),
                ).group_by(
                    SearchHistory.origin, SearchHistory.destination,
                    SearchHistory.best_market,
                ).order_by(
                    db.func.avg(SearchHistory.max_savings_percent).desc()
                ).limit(20).all()

                for row in savings_rows:
                    patterns["savings_opportunities"].append({
                        "route": f"{row.origin}-{row.destination}",
                        "market": row.best_market,
                        "avg_savings_pct": round(row.avg_savings, 1),
                        "occurrences": row.count,
                    })
            except Exception as e:
                logger.debug(f"Savings opportunity detection failed: {e}")

            # --- New routes: searched but no price history ---
            try:
                searched_routes = db.session.query(
                    SearchHistory.origin,
                    SearchHistory.destination,
                ).filter(
                    SearchHistory.created_at >= cutoff,
                ).distinct().limit(50).all()

                for row in searched_routes:
                    price_count = PriceHistory.query.filter_by(
                        origin=row.origin,
                        destination=row.destination,
                    ).limit(1).count()
                    if price_count == 0:
                        patterns["new_routes"].append({
                            "route": f"{row.origin}-{row.destination}",
                            "origin": row.origin,
                            "destination": row.destination,
                        })
            except Exception as e:
                logger.debug(f"New route detection failed: {e}")

        except Exception as e:
            logger.error(f"detect_patterns failed: {e}")

        # Build #80: Bridge patterns into strategy_learner
        self._feed_patterns_to_strategy(patterns)

        return patterns

    def _feed_patterns_to_strategy(self, patterns: dict) -> None:
        """
        Build #80: Convert detected patterns into strategy observations.

        Feeds volume spikes, price trends, and savings opportunities into
        the strategy learner so it can aggregate them into insights.
        """
        try:
            from strategy_learner import strategy_learner

            # Volume spikes → high-demand route observations
            for spike in patterns.get("volume_spikes", []):
                route = spike.get("route", "")
                if "-" not in route:
                    continue
                origin, dest = route.split("-", 1)
                strategy_learner.record_observation(
                    query_type="demand_signal",
                    query_category="flight",
                    query_structure=json.dumps({
                        "origin": origin,
                        "destination": dest,
                        "signal": "volume_spike",
                        "spike_ratio": spike.get("spike_ratio", 1),
                    }),
                    result_count=spike.get("recent_searches", 0),
                    result_quality_score=min(spike.get("spike_ratio", 1) / 5.0, 1.0),
                    markets_found="[]",
                    source_sites="[]",
                )

            # Price trends → market intelligence observations
            for trend in patterns.get("price_trends", []):
                if trend.get("direction") == "stable":
                    continue
                route = trend.get("route", "")
                if "-" not in route:
                    continue
                origin, dest = route.split("-", 1)
                strategy_learner.record_observation(
                    query_type="price_trend",
                    query_category="flight",
                    query_structure=json.dumps({
                        "origin": origin,
                        "destination": dest,
                        "direction": trend["direction"],
                        "avg_price": trend.get("avg_price"),
                        "top_routes": [route],
                    }),
                    result_count=trend.get("samples", 0),
                    result_quality_score=0.7 if trend["direction"] == "falling" else 0.5,
                    markets_found=json.dumps([trend.get("market", "")]),
                    source_sites="[]",
                )

            # Savings opportunities → high-value market observations
            for opp in patterns.get("savings_opportunities", []):
                route = opp.get("route", "")
                if "-" not in route:
                    continue
                origin, dest = route.split("-", 1)
                strategy_learner.record_observation(
                    query_type="savings_signal",
                    query_category="flight",
                    query_structure=json.dumps({
                        "origin": origin,
                        "destination": dest,
                        "market": opp.get("market", ""),
                        "avg_savings_pct": opp.get("avg_savings_pct", 0),
                        "destinations": [dest],
                    }),
                    result_count=opp.get("occurrences", 0),
                    result_quality_score=min(opp.get("avg_savings_pct", 0) / 30.0, 1.0),
                    markets_found=json.dumps([opp.get("market", "")]),
                    source_sites="[]",
                )

        except Exception as e:
            logger.debug(f"_feed_patterns_to_strategy failed: {e}")

    # -----------------------------------------------------------------
    # Price Anomaly Detection
    # -----------------------------------------------------------------

    def detect_price_anomaly(self, route, market, current_price,
                             currency="USD") -> Optional[dict]:
        """
        Check if a price is anomalous vs 7-day average for route+market.

        Args:
            route: Tuple of (origin, destination) or string "JFK-NRT".
            market: Market code (e.g. "JP").
            current_price: Current price in USD.
            currency: Price currency (informational).

        Returns:
            Anomaly dict or None if price is within normal range.
        """
        try:
            from models import db, PriceHistory

            if isinstance(route, str):
                parts = route.split("-")
                origin, destination = parts[0].upper(), parts[1].upper()
            else:
                origin, destination = route[0].upper(), route[1].upper()

            market = market.upper()
            current_price = float(current_price)

            week_cutoff = datetime.utcnow() - timedelta(days=7)

            avg_price = db.session.query(
                db.func.avg(PriceHistory.price_usd)
            ).filter(
                PriceHistory.origin == origin,
                PriceHistory.destination == destination,
                PriceHistory.market == market,
                PriceHistory.recorded_at >= week_cutoff,
            ).scalar()

            if avg_price is None or avg_price <= 0:
                return None

            avg_price = float(avg_price)
            deviation = (current_price - avg_price) / avg_price

            anomaly = None
            if deviation <= -PRICE_DROP_THRESHOLD:
                anomaly = {
                    "type": "price_anomaly",
                    "direction": "price_drop",
                    "severity": "high" if deviation <= -0.25 else "medium",
                    "route": f"{origin}-{destination}",
                    "market": market,
                    "current_price": round(current_price, 2),
                    "avg_price_7d": round(avg_price, 2),
                    "deviation_pct": round(deviation * 100, 1),
                    "currency": currency,
                    "detected_at": datetime.utcnow().isoformat(),
                }
            elif deviation >= PRICE_SPIKE_THRESHOLD:
                anomaly = {
                    "type": "price_anomaly",
                    "direction": "price_spike",
                    "severity": "high" if deviation >= 0.35 else "medium",
                    "route": f"{origin}-{destination}",
                    "market": market,
                    "current_price": round(current_price, 2),
                    "avg_price_7d": round(avg_price, 2),
                    "deviation_pct": round(deviation * 100, 1),
                    "currency": currency,
                    "detected_at": datetime.utcnow().isoformat(),
                }

            if anomaly:
                with self._lock:
                    self._anomaly_log.append(anomaly)
                    self._stats["anomalies_detected"] += 1
                logger.info(
                    f"Anomaly detected: {anomaly['direction']} on "
                    f"{origin}-{destination} ({market}): "
                    f"${current_price:.0f} vs ${avg_price:.0f} avg "
                    f"({anomaly['deviation_pct']}%)"
                )

            return anomaly

        except Exception as e:
            logger.debug(f"detect_price_anomaly failed: {e}")
            return None

    # -----------------------------------------------------------------
    # Auto-create Opportunities
    # -----------------------------------------------------------------

    def auto_create_opportunity(self, anomaly_data: dict) -> Optional[dict]:
        """
        Auto-create a Deal record from a significant price anomaly.

        Only creates if no existing deal for this route+market in last 24h.

        Args:
            anomaly_data: Dict with origin, destination, market, price_usd,
                          avg_price_7d, deviation_pct, airline, etc.

        Returns:
            Deal info dict or None.
        """
        try:
            from models import db, Deal

            origin = anomaly_data.get("origin", "").upper()
            destination = anomaly_data.get("destination", "").upper()
            market = anomaly_data.get("market", "").upper()
            price_usd = anomaly_data.get("price_usd")
            avg_price = anomaly_data.get("avg_price_7d")

            if not origin or not destination or not market or price_usd is None:
                return None

            # Check for existing recent deal on same route+market
            day_ago = datetime.utcnow() - timedelta(hours=24)
            existing = Deal.query.filter(
                Deal.origin == origin,
                Deal.destination == destination,
                Deal.arbitrage_market == market,
                Deal.is_active == True,
                Deal.created_at >= day_ago,
            ).first()

            if existing:
                logger.debug(
                    f"Deal already exists for {origin}-{destination} ({market}), "
                    f"deal_id={existing.deal_id}"
                )
                return None

            # Calculate savings vs average (treated as "home" price)
            home_price = avg_price if avg_price else price_usd * 1.2
            savings_usd = round(home_price - price_usd, 2)
            savings_pct = round((savings_usd / home_price) * 100, 1) if home_price > 0 else 0

            deal_id = f"PX-{secrets.token_hex(4).upper()}"

            deal = Deal(
                deal_id=deal_id,
                origin=origin,
                destination=destination,
                home_market="US",
                home_price_usd=round(home_price, 2),
                arbitrage_market=market,
                arbitrage_price_usd=round(price_usd, 2),
                gross_savings_usd=savings_usd,
                savings_percent=savings_pct,
                airline=anomaly_data.get("airline"),
                is_active=True,
                expires_at=datetime.utcnow() + timedelta(hours=24),
            )

            db.session.add(deal)
            db.session.commit()

            with self._lock:
                self._stats["opportunities_created"] += 1

            logger.info(
                f"Auto-created opportunity {deal_id}: {origin}-{destination} "
                f"via {market} at ${price_usd:.0f} ({savings_pct}% savings)"
            )

            # Emit SSE event
            self._emit_event("admin", "opportunity_detected", {
                "deal_id": deal_id,
                "route": f"{origin}-{destination}",
                "market": market,
                "price_usd": round(price_usd, 2),
                "savings_pct": savings_pct,
                "source": anomaly_data.get("task_type", "feedback"),
            })

            return {
                "deal_id": deal_id,
                "origin": origin,
                "destination": destination,
                "market": market,
                "price_usd": round(price_usd, 2),
                "savings_pct": savings_pct,
                "created_at": datetime.utcnow().isoformat(),
            }

        except Exception as e:
            logger.error(f"auto_create_opportunity failed: {e}")
            try:
                from models import db
                db.session.rollback()
            except Exception:
                pass
            return None

    # -----------------------------------------------------------------
    # Alert Checking
    # -----------------------------------------------------------------

    def check_triggered_alerts(self, route, market, price) -> List[dict]:
        """
        Check if a price triggers any active PriceAlerts for this route.

        Args:
            route: Tuple (origin, dest) or string "JFK-NRT".
            market: Market code.
            price: Current price USD.

        Returns:
            List of triggered alert dicts.
        """
        triggered = []
        try:
            from models import db, PriceAlert

            if isinstance(route, str):
                parts = route.split("-")
                origin, destination = parts[0].upper(), parts[1].upper()
            else:
                origin, destination = route[0].upper(), route[1].upper()

            price = float(price)

            # Find active alerts for this route where price meets threshold
            alerts = PriceAlert.query.filter(
                PriceAlert.origin == origin,
                PriceAlert.destination == destination,
                PriceAlert.is_active == True,
                PriceAlert.max_price_usd >= price,
            ).all()

            for alert in alerts:
                alert_info = {
                    "alert_id": alert.id,
                    "user_id": alert.user_id,
                    "route": f"{origin}-{destination}",
                    "market": market,
                    "triggered_price": round(price, 2),
                    "max_price_threshold": alert.max_price_usd,
                    "triggered_at": datetime.utcnow().isoformat(),
                }
                triggered.append(alert_info)

                # Update last_triggered timestamp
                try:
                    alert.last_triggered = datetime.utcnow()
                    db.session.commit()
                except Exception:
                    try:
                        db.session.rollback()
                    except Exception:
                        pass

                # Emit SSE notification to alert owner
                self._emit_event(f"user:{alert.user_id}", "price_alert_triggered", {
                    "alert_id": alert.id,
                    "route": f"{origin}-{destination}",
                    "market": market,
                    "price_usd": round(price, 2),
                    "your_threshold": alert.max_price_usd,
                })

                logger.info(
                    f"Price alert triggered: alert={alert.id} "
                    f"user={alert.user_id} {origin}-{destination} "
                    f"${price:.0f} <= ${alert.max_price_usd:.0f}"
                )

            if triggered:
                with self._lock:
                    self._stats["alerts_triggered"] += len(triggered)

        except Exception as e:
            logger.debug(f"check_triggered_alerts failed: {e}")

        return triggered

    # -----------------------------------------------------------------
    # Route Cache
    # -----------------------------------------------------------------

    def update_route_cache(self, origin: str, dest: str, market: str,
                           price_data: dict) -> None:
        """
        Update in-memory route intelligence cache.

        Used by phoenix_intelligence.get_route_intelligence() for fast
        lookups without hitting the database.
        """
        try:
            origin = origin.upper()
            dest = dest.upper()
            market = market.upper()
            route_key = f"{origin}-{dest}:{market}"

            with self._lock:
                existing = self._route_cache.get(route_key, {})
                prev_price = existing.get("price_usd")
                new_price = price_data.get("price_usd")

                # Determine trend direction from cache history
                trend = existing.get("trend", "stable")
                if prev_price and new_price:
                    change = (new_price - prev_price) / prev_price
                    if change > 0.03:
                        trend = "rising"
                    elif change < -0.03:
                        trend = "falling"
                    else:
                        trend = "stable"

                self._route_cache[route_key] = {
                    "origin": origin,
                    "destination": dest,
                    "market": market,
                    "price_usd": new_price,
                    "prev_price_usd": prev_price,
                    "trend": trend,
                    "airline": price_data.get("airline"),
                    "source": price_data.get("source"),
                    "last_updated": datetime.utcnow().isoformat(),
                }
        except Exception as e:
            logger.debug(f"update_route_cache failed: {e}")

    def get_route_cache(self, origin: str = None, dest: str = None) -> dict:
        """
        Read from the route cache. If origin/dest given, filter to that route.
        Otherwise return the full cache.
        """
        with self._lock:
            if origin and dest:
                prefix = f"{origin.upper()}-{dest.upper()}:"
                return {
                    k: v for k, v in self._route_cache.items()
                    if k.startswith(prefix)
                }
            return dict(self._route_cache)

    # -----------------------------------------------------------------
    # Stats and Reporting
    # -----------------------------------------------------------------

    def get_feedback_stats(self) -> dict:
        """
        Stats on feedback processing over last 24h.

        Returns counters for ingested results, anomalies detected,
        opportunities created, and alerts triggered.
        """
        with self._lock:
            stats = dict(self._stats)
            stats["route_cache_size"] = len(self._route_cache)
            stats["anomaly_log_size"] = len(self._anomaly_log)
        return stats

    def get_recent_anomalies(self, hours_back: int = 24,
                             limit: int = 20) -> List[dict]:
        """
        List recent anomalies detected within the given time window.
        """
        cutoff = datetime.utcnow() - timedelta(hours=hours_back)
        cutoff_iso = cutoff.isoformat()

        with self._lock:
            results = []
            for anomaly in reversed(self._anomaly_log):
                if len(results) >= limit:
                    break
                detected_at = anomaly.get("detected_at", "")
                if detected_at >= cutoff_iso:
                    results.append(dict(anomaly))

        return results

    # -----------------------------------------------------------------
    # Internal Helpers
    # -----------------------------------------------------------------

    def _extract_prices(self, result_dict: dict) -> List[dict]:
        """
        Extract structured price entries from a task result.

        Handles multiple result formats from CitizenSERP tasks.
        """
        prices = []

        # Format 1: Direct prices list
        if "prices" in result_dict:
            for p in result_dict["prices"]:
                price_val = p.get("price_usd") or p.get("price")
                if price_val is not None:
                    prices.append({
                        "price_usd": float(price_val),
                        "market": p.get("market", ""),
                        "airline": p.get("airline", ""),
                        "currency": p.get("currency", "USD"),
                    })

        # Format 2: Extracted data with price field
        elif "extracted_data" in result_dict:
            data = result_dict["extracted_data"]
            if isinstance(data, dict):
                price_val = data.get("price_usd") or data.get("price")
                if price_val is not None:
                    prices.append({
                        "price_usd": float(price_val),
                        "market": data.get("market", ""),
                        "airline": data.get("airline", ""),
                        "currency": data.get("currency", "USD"),
                    })
            elif isinstance(data, list):
                for item in data:
                    price_val = item.get("price_usd") or item.get("price")
                    if price_val is not None:
                        prices.append({
                            "price_usd": float(price_val),
                            "market": item.get("market", ""),
                            "airline": item.get("airline", ""),
                            "currency": item.get("currency", "USD"),
                        })

        # Format 3: Single result with price at top level
        elif "price_usd" in result_dict or "price" in result_dict:
            price_val = result_dict.get("price_usd") or result_dict.get("price")
            if price_val is not None:
                prices.append({
                    "price_usd": float(price_val),
                    "market": result_dict.get("market", ""),
                    "airline": result_dict.get("airline", ""),
                    "currency": result_dict.get("currency", "USD"),
                })

        return prices

    def _record_price_snapshots(self, origin: str, destination: str,
                                market: str, prices: List[dict],
                                source: str) -> int:
        """
        Record extracted prices as PriceHistory snapshots.

        Returns count of records saved.
        """
        recorded = 0
        try:
            from models import db, PriceHistory

            for entry in prices:
                price_val = entry.get("price_usd")
                if price_val is None:
                    continue

                ph = PriceHistory(
                    origin=origin.upper(),
                    destination=destination.upper(),
                    departure_date=None,
                    cabin_class="economy",
                    market=(entry.get("market") or market).upper(),
                    price_usd=float(price_val),
                    price_local=entry.get("price_local"),
                    local_currency=entry.get("currency"),
                    airline=entry.get("airline", "")[:50] if entry.get("airline") else None,
                    source=source,
                )
                db.session.add(ph)
                recorded += 1

            if recorded > 0:
                db.session.commit()

        except Exception as e:
            logger.error(f"_record_price_snapshots failed: {e}")
            try:
                from models import db
                db.session.rollback()
            except Exception:
                pass

        return recorded

    def _emit_event(self, channel: str, event_type: str, data: dict) -> None:
        """Publish an SSE event (non-blocking, fire-and-forget)."""
        try:
            from event_stream import publish_event
            publish_event(channel, event_type, data)
        except Exception as e:
            logger.debug(f"Failed to emit SSE event {event_type}: {e}")


    # ------------------------------------------------------------------
    # Build #78 — Zone-aware anomaly detection
    # ------------------------------------------------------------------

    def detect_zone_anomalies(
        self, zone_id: str, vertical: str = None, hours_back: int = 6
    ) -> list:
        """Compare zone prices to parent/sibling zones to find anomalies.

        Returns list of anomaly dicts when a zone's price for an item is
        significantly different from its sibling zones (>15% deviation).
        """
        anomalies = []
        try:
            from pricing_zones import zone_engine
            from models import PricingZone

            zone = PricingZone.query.filter_by(zone_id=zone_id, is_active=True).first()
            if not zone or not zone.parent_zone_id:
                return anomalies

            # Get sibling zones (same parent)
            siblings = PricingZone.query.filter_by(
                parent_zone_id=zone.parent_zone_id, is_active=True
            ).all()
            sibling_ids = [s.zone_id for s in siblings if s.zone_id != zone_id]

            if not sibling_ids:
                return anomalies

            # Get prices in target zone
            target_prices = zone_engine.get_zone_prices(
                zone_id=zone_id, vertical=vertical, hours_back=hours_back
            )
            target_items = target_prices.get("price_by_item", {})

            # Get average sibling prices per item
            sibling_item_prices = {}
            for sid in sibling_ids:
                sp = zone_engine.get_zone_prices(
                    zone_id=sid, vertical=vertical, hours_back=hours_back
                )
                for item_key, item_data in sp.get("price_by_item", {}).items():
                    avg_p = item_data.get("avg_price", 0)
                    if avg_p > 0:
                        sibling_item_prices.setdefault(item_key, []).append(avg_p)

            # Compare
            for item_key, item_data in target_items.items():
                target_avg = item_data.get("avg_price", 0)
                if target_avg <= 0:
                    continue
                sibling_vals = sibling_item_prices.get(item_key, [])
                if not sibling_vals:
                    continue
                sibling_avg = sum(sibling_vals) / len(sibling_vals)
                if sibling_avg <= 0:
                    continue
                deviation_pct = ((target_avg - sibling_avg) / sibling_avg) * 100
                if abs(deviation_pct) > 15:
                    anomalies.append({
                        "zone_id": zone_id,
                        "item_key": item_key,
                        "vertical": vertical,
                        "zone_avg_price": round(target_avg, 2),
                        "sibling_avg_price": round(sibling_avg, 2),
                        "deviation_pct": round(deviation_pct, 1),
                        "type": "geo_price_anomaly" if deviation_pct < 0 else "geo_premium",
                        "sibling_zones_compared": len(sibling_vals),
                    })

        except ImportError:
            logger.debug("pricing_zones not available for zone anomaly detection")
        except Exception as e:
            logger.warning("detect_zone_anomalies failed: %s", e)

        return anomalies


# =====================================================================
# Module Singleton
# =====================================================================

feedback_engine = FeedbackEngine()
