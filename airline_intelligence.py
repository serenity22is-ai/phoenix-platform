"""
MYSTES Airline Intelligence Manager

Manages airline intelligence clients, competitive pricing reports,
ancillary optimization data, demand signals, and real-time alerts.

Airlines are a SEPARATE customer type from commercial accounts (agencies/OTAs).
- Flat subscription fee ($100K-500K/mo) vs percentage of savings
- Data-only service — NO booking capability
- Focus on competitive intelligence, ancillary optimization, demand signals

Usage:
    from airline_intelligence import airline_intel_manager

    # Onboard airline
    client = airline_intel_manager.create_client(
        iata_code="UA",
        airline_name="United Airlines",
        contact_email="intel@united.com",
        subscription_tier="pro",
    )

    # Competitive pricing analysis
    analysis = airline_intel_manager.get_competitor_analysis(
        client_id=client['client_id'],
        route="JFK-LHR",
        market="US",
    )

    # Set up competitive alert
    alert = airline_intel_manager.create_alert(
        client_id=client['client_id'],
        alert_type="price_drop",
        route_pattern="JFK-*",
        competitor_iata="AA",
        price_change_pct=5.0,
    )
"""

import json
import logging
import re
import secrets
from datetime import datetime, timedelta, date

import bcrypt

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Subscription tier configuration
# ---------------------------------------------------------------------------

AIRLINE_TIERS = {
    "basic": {
        "monthly_fee_usd": 100_000,
        "max_routes": 50,
        "max_markets": 10,
        "max_alerts": 50,
        "report_frequency": "weekly",
        "api_rate_limit": 1000,        # requests per hour
    },
    "pro": {
        "monthly_fee_usd": 250_000,
        "max_routes": 200,
        "max_markets": 30,
        "max_alerts": 200,
        "report_frequency": "daily",
        "api_rate_limit": 5000,
    },
    "enterprise": {
        "monthly_fee_usd": 500_000,
        "max_routes": None,            # unlimited
        "max_markets": None,
        "max_alerts": None,
        "report_frequency": "realtime",
        "api_rate_limit": 20000,
    },
}

AIRLINE_TIER_ORDER = ["enterprise", "pro", "basic"]


class AirlineIntelligenceManager:
    """Manages airline intelligence clients and intelligence operations."""

    # ------------------------------------------------------------------
    # Client Management
    # ------------------------------------------------------------------

    def create_client(self, iata_code, airline_name, contact_email,
                      subscription_tier="basic", contact_name=None,
                      routes_subscribed=None, markets_subscribed=None,
                      competitor_airlines=None, contract_months=12):
        """Onboard a new airline intelligence client."""
        from models import db, AirlineClient

        if subscription_tier not in AIRLINE_TIERS:
            return {"error": f"Invalid tier: {subscription_tier}"}

        tier = AIRLINE_TIERS[subscription_tier]
        client_id = f"AIR-{iata_code.upper()}-{secrets.token_hex(3).upper()}"

        data_scopes = ["pricing", "ancillary", "demand", "alerts", "reports"]

        client = AirlineClient(
            client_id=client_id,
            iata_code=iata_code.upper(),
            airline_name=airline_name,
            contact_email=contact_email,
            contact_name=contact_name,
            subscription_tier=subscription_tier,
            monthly_fee_usd=tier["monthly_fee_usd"],
            routes_subscribed=json.dumps(routes_subscribed or []),
            data_scopes=json.dumps(data_scopes),
            competitor_airlines=json.dumps(competitor_airlines or []),
            markets_subscribed=json.dumps(markets_subscribed or []),
            contract_start=date.today(),
            contract_end=date.today() + timedelta(days=contract_months * 30),
            activated_at=datetime.utcnow(),
        )

        db.session.add(client)
        db.session.commit()

        logger.info(f"Airline client created: {client_id} ({airline_name}) tier={subscription_tier}")
        return {
            "client_id": client_id,
            "tier": subscription_tier,
            "monthly_fee_usd": tier["monthly_fee_usd"],
            "contract_end": client.contract_end.isoformat(),
        }

    def get_client(self, client_id):
        """Get airline client by ID."""
        from models import AirlineClient
        return AirlineClient.query.filter_by(client_id=client_id).first()

    def get_client_by_iata(self, iata_code):
        """Get active airline client by IATA code."""
        from models import AirlineClient
        return AirlineClient.query.filter_by(
            iata_code=iata_code.upper(), is_active=True
        ).first()

    def suspend_client(self, client_id, reason=None):
        """Suspend an airline client."""
        from models import db
        client = self.get_client(client_id)
        if not client:
            return {"error": "Client not found"}

        client.is_active = False
        client.suspended_at = datetime.utcnow()
        db.session.commit()

        logger.info(f"Airline client suspended: {client_id} ({reason})")
        return {"ok": True}

    def reactivate_client(self, client_id):
        """Reactivate a suspended airline client."""
        from models import db
        client = self.get_client(client_id)
        if not client:
            return {"error": "Client not found"}

        client.is_active = True
        client.suspended_at = None
        db.session.commit()

        logger.info(f"Airline client reactivated: {client_id}")
        return {"ok": True}

    def list_clients(self, active_only=True, limit=100):
        """List airline intelligence clients."""
        from models import AirlineClient
        query = AirlineClient.query
        if active_only:
            query = query.filter_by(is_active=True)
        clients = query.order_by(AirlineClient.created_at.desc()).limit(limit).all()
        return [c.to_dict() for c in clients]

    # ------------------------------------------------------------------
    # API Key Management
    # ------------------------------------------------------------------

    def create_api_key(self, client_id, label="Production", scopes=None,
                       expires_days=None):
        """
        Generate API key for airline client.

        Key format: air_{64 hex chars}
        Scopes: pricing, ancillary, demand, alerts, reports
        """
        from models import db, AirlineAPIKey

        client = self.get_client(client_id)
        if not client:
            return {"error": "Client not found"}

        raw_key = secrets.token_hex(32)
        full_key = f"air_{raw_key}"
        prefix = raw_key[:8]

        key_hash = bcrypt.hashpw(raw_key.encode(), bcrypt.gensalt()).decode()

        if scopes is None:
            scopes = json.loads(client.data_scopes) if client.data_scopes else \
                     ["pricing", "ancillary", "demand", "alerts", "reports"]

        expires_at = None
        if expires_days:
            expires_at = datetime.utcnow() + timedelta(days=expires_days)

        api_key = AirlineAPIKey(
            client_id=client.id,
            key_prefix=prefix,
            key_hash=key_hash,
            label=label,
            scopes=json.dumps(scopes),
            expires_at=expires_at,
        )
        db.session.add(api_key)
        db.session.commit()

        logger.info(f"Airline API key created: {client_id} air_{prefix}...")
        return {
            "api_key": full_key,
            "key_id": api_key.id,
            "prefix": f"air_{prefix}...",
            "scopes": scopes,
            "expires_at": expires_at.isoformat() if expires_at else None,
            "warning": "Store this key securely — it cannot be retrieved again.",
        }

    def verify_api_key(self, key_string):
        """
        Verify airline API key.

        Returns (AirlineClient, AirlineAPIKey, scopes) or None.
        """
        from models import db, AirlineAPIKey, AirlineClient

        if not key_string or not key_string.startswith("air_"):
            return None

        raw_key = key_string[4:]
        prefix = raw_key[:8]

        candidates = AirlineAPIKey.query.filter_by(
            key_prefix=prefix, is_active=True
        ).all()

        for api_key in candidates:
            if bcrypt.checkpw(raw_key.encode(), api_key.key_hash.encode()):
                # Expiration check
                if api_key.expires_at and datetime.utcnow() > api_key.expires_at:
                    return None

                client = AirlineClient.query.get(api_key.client_id)
                if not client or not client.is_active:
                    return None

                # Contract validity
                if client.contract_end and date.today() > client.contract_end:
                    logger.warning(f"Airline client contract expired: {client.client_id}")
                    return None

                # Update usage
                api_key.last_used_at = datetime.utcnow()
                api_key.total_requests = (api_key.total_requests or 0) + 1
                client.api_calls_this_month = (client.api_calls_this_month or 0) + 1
                client.api_calls_total = (client.api_calls_total or 0) + 1
                db.session.commit()

                scopes = json.loads(api_key.scopes) if api_key.scopes else []
                return (client, api_key, scopes)

        return None

    def revoke_api_key(self, key_id, client_id):
        """Revoke an airline API key."""
        from models import db, AirlineAPIKey

        client = self.get_client(client_id)
        if not client:
            return {"error": "Client not found"}

        api_key = AirlineAPIKey.query.filter_by(
            id=key_id, client_id=client.id
        ).first()

        if not api_key:
            return {"error": "Key not found"}

        api_key.is_active = False
        db.session.commit()
        return {"ok": True}

    # ------------------------------------------------------------------
    # Competitive Pricing Intelligence
    # ------------------------------------------------------------------

    def _parse_route(self, route):
        """Parse route string into (origin, destination). Returns None on error."""
        parts = route.upper().split("-")
        if len(parts) != 2:
            return None
        return parts[0], parts[1]

    def get_competitor_analysis(self, client_id, route, market="US", days_back=30):
        """
        Competitive pricing analysis for a specific route.

        Returns airline-by-airline pricing with market positioning and ranks.
        """
        from models import db, PriceHistory

        client = self.get_client(client_id)
        if not client:
            return {"error": "Client not found"}

        parsed = self._parse_route(route)
        if not parsed:
            return {"error": "Invalid route format. Use: JFK-LHR"}
        origin, destination = parsed

        cutoff = datetime.utcnow() - timedelta(days=days_back)

        price_data = db.session.query(
            PriceHistory.airline,
            db.func.avg(PriceHistory.price_usd).label("avg_price"),
            db.func.min(PriceHistory.price_usd).label("min_price"),
            db.func.max(PriceHistory.price_usd).label("max_price"),
            db.func.count(PriceHistory.id).label("sample_count"),
        ).filter(
            PriceHistory.origin == origin,
            PriceHistory.destination == destination,
            PriceHistory.market == market.upper(),
            PriceHistory.recorded_at >= cutoff,
            PriceHistory.airline.isnot(None),
        ).group_by(PriceHistory.airline).all()

        if not price_data:
            return {
                "route": route.upper(),
                "market": market.upper(),
                "days_analyzed": days_back,
                "airlines": [],
                "message": "No pricing data available for this route/market",
            }

        all_avgs = [r.avg_price for r in price_data]
        market_avg = sum(all_avgs) / len(all_avgs)

        airlines = []
        for rank, row in enumerate(sorted(price_data, key=lambda x: x.avg_price), 1):
            pct = ((row.avg_price - market_avg) / market_avg * 100) if market_avg > 0 else 0
            airlines.append({
                "airline": row.airline,
                "avg_price_usd": round(row.avg_price, 2),
                "min_price_usd": round(row.min_price, 2),
                "max_price_usd": round(row.max_price, 2),
                "sample_count": row.sample_count,
                "market_rank": rank,
                "price_vs_market_avg_pct": round(pct, 1),
                "is_your_airline": bool(row.airline and client.iata_code in row.airline.upper()),
            })

        return {
            "route": route.upper(),
            "market": market.upper(),
            "days_analyzed": days_back,
            "market_avg_price_usd": round(market_avg, 2),
            "airlines": airlines,
            "total_airlines": len(airlines),
            "your_rank": next((a["market_rank"] for a in airlines if a["is_your_airline"]), None),
        }

    def get_route_pricing_history(self, client_id, route, market="US", days_back=90):
        """Historical daily price trend for a specific route."""
        from models import db, PriceHistory

        client = self.get_client(client_id)
        if not client:
            return {"error": "Client not found"}

        parsed = self._parse_route(route)
        if not parsed:
            return {"error": "Invalid route format"}
        origin, destination = parsed

        cutoff = datetime.utcnow() - timedelta(days=days_back)

        daily = db.session.query(
            db.func.date(PriceHistory.recorded_at).label("day"),
            db.func.avg(PriceHistory.price_usd).label("avg_price"),
            db.func.min(PriceHistory.price_usd).label("min_price"),
            db.func.count(PriceHistory.id).label("samples"),
        ).filter(
            PriceHistory.origin == origin,
            PriceHistory.destination == destination,
            PriceHistory.market == market.upper(),
            PriceHistory.recorded_at >= cutoff,
        ).group_by(
            db.func.date(PriceHistory.recorded_at)
        ).order_by(db.text("day ASC")).all()

        trend = [
            {
                "date": str(r.day),
                "avg_price_usd": round(r.avg_price, 2),
                "min_price_usd": round(r.min_price, 2),
                "samples": r.samples,
            }
            for r in daily
        ]

        return {
            "route": route.upper(),
            "market": market.upper(),
            "days_analyzed": days_back,
            "data_points": len(trend),
            "trend": trend,
        }

    # ------------------------------------------------------------------
    # Ancillary Intelligence
    # ------------------------------------------------------------------

    def get_ancillary_analysis(self, client_id, route, market="US", days_back=30):
        """Ancillary pricing analysis (bags, seats) for a route by airline."""
        from models import db, AncillarySnapshot

        client = self.get_client(client_id)
        if not client:
            return {"error": "Client not found"}

        parsed = self._parse_route(route)
        if not parsed:
            return {"error": "Invalid route format"}
        origin, destination = parsed

        cutoff = datetime.utcnow() - timedelta(days=days_back)

        snapshots = db.session.query(
            AncillarySnapshot.airline,
            db.func.avg(AncillarySnapshot.checked_bag_1_price_usd).label("avg_bag1"),
            db.func.avg(AncillarySnapshot.checked_bag_2_price_usd).label("avg_bag2"),
            db.func.avg(AncillarySnapshot.seat_selection_min_price_usd).label("avg_seat_min"),
            db.func.avg(AncillarySnapshot.seat_selection_max_price_usd).label("avg_seat_max"),
            db.func.count(AncillarySnapshot.id).label("sample_count"),
        ).filter(
            AncillarySnapshot.origin == origin,
            AncillarySnapshot.destination == destination,
            AncillarySnapshot.market == market.upper(),
            AncillarySnapshot.recorded_at >= cutoff,
            AncillarySnapshot.airline.isnot(None),
        ).group_by(AncillarySnapshot.airline).all()

        if not snapshots:
            return {
                "route": route.upper(),
                "market": market.upper(),
                "airlines": [],
                "message": "No ancillary data available",
            }

        airlines = []
        for row in snapshots:
            airlines.append({
                "airline": row.airline,
                "avg_checked_bag_1_usd": round(row.avg_bag1, 2) if row.avg_bag1 else None,
                "avg_checked_bag_2_usd": round(row.avg_bag2, 2) if row.avg_bag2 else None,
                "avg_seat_selection_min_usd": round(row.avg_seat_min, 2) if row.avg_seat_min else None,
                "avg_seat_selection_max_usd": round(row.avg_seat_max, 2) if row.avg_seat_max else None,
                "sample_count": row.sample_count,
                "is_your_airline": bool(row.airline and client.iata_code in row.airline.upper()),
            })

        return {
            "route": route.upper(),
            "market": market.upper(),
            "days_analyzed": days_back,
            "airlines": airlines,
        }

    # ------------------------------------------------------------------
    # Demand Intelligence
    # ------------------------------------------------------------------

    def get_demand_analysis(self, client_id, route, days_back=30):
        """Search demand signals for a route using SearchHistory."""
        from models import db, SearchHistory

        client = self.get_client(client_id)
        if not client:
            return {"error": "Client not found"}

        parsed = self._parse_route(route)
        if not parsed:
            return {"error": "Invalid route format"}
        origin, destination = parsed

        cutoff = datetime.utcnow() - timedelta(days=days_back)

        volume = db.session.query(
            db.func.date(SearchHistory.created_at).label("day"),
            db.func.count(SearchHistory.id).label("searches"),
            db.func.avg(SearchHistory.best_price_usd).label("avg_best_price"),
        ).filter(
            SearchHistory.origin == origin,
            SearchHistory.destination == destination,
            SearchHistory.created_at >= cutoff,
        ).group_by(
            db.func.date(SearchHistory.created_at)
        ).order_by(db.text("day ASC")).all()

        trend = [
            {
                "date": str(r.day),
                "search_count": r.searches,
                "avg_best_price_usd": round(r.avg_best_price, 2) if r.avg_best_price else None,
            }
            for r in volume
        ]

        total = sum(d["search_count"] for d in trend)

        return {
            "route": route.upper(),
            "days_analyzed": days_back,
            "total_searches": total,
            "avg_daily_searches": round(total / max(days_back, 1), 1),
            "demand_trend": trend,
        }

    # ------------------------------------------------------------------
    # Alert Management
    # ------------------------------------------------------------------

    def create_alert(self, client_id, alert_type, route_pattern=None,
                     competitor_iata=None, market=None,
                     price_change_pct=None, price_change_usd=None,
                     demand_change_pct=None,
                     notify_email=True, notify_webhook=None):
        """
        Create a competitive alert.

        Alert types: price_drop, price_spike, demand_surge, new_route, ancillary_change
        """
        from models import db, AirlineAlert

        client = self.get_client(client_id)
        if not client:
            return {"error": "Client not found"}

        valid_types = {"price_drop", "price_spike", "demand_surge", "new_route", "ancillary_change"}
        if alert_type not in valid_types:
            return {"error": f"Invalid alert_type. Must be one of: {', '.join(sorted(valid_types))}"}

        alert_id = f"ALERT-{secrets.token_hex(6).upper()}"

        alert = AirlineAlert(
            alert_id=alert_id,
            client_id=client.id,
            alert_type=alert_type,
            route_pattern=route_pattern.upper() if route_pattern else None,
            competitor_iata=competitor_iata.upper() if competitor_iata else None,
            market=market.upper() if market else None,
            price_change_pct=price_change_pct,
            price_change_usd=price_change_usd,
            demand_change_pct=demand_change_pct,
            notify_email=notify_email,
            notify_webhook=notify_webhook,
        )

        db.session.add(alert)
        db.session.commit()

        logger.info(f"Airline alert created: {alert_id} for {client_id} ({alert_type})")
        return {"alert_id": alert_id, "status": "active"}

    def list_alerts(self, client_id, active_only=True):
        """List alerts for a client."""
        from models import AirlineAlert

        client = self.get_client(client_id)
        if not client:
            return {"error": "Client not found"}

        query = AirlineAlert.query.filter_by(client_id=client.id)
        if active_only:
            query = query.filter_by(is_active=True)
        alerts = query.order_by(AirlineAlert.created_at.desc()).all()
        return [a.to_dict() for a in alerts]

    def delete_alert(self, client_id, alert_id):
        """Deactivate an alert."""
        from models import db, AirlineAlert

        client = self.get_client(client_id)
        if not client:
            return {"error": "Client not found"}

        alert = AirlineAlert.query.filter_by(
            alert_id=alert_id, client_id=client.id
        ).first()
        if not alert:
            return {"error": "Alert not found"}

        alert.is_active = False
        db.session.commit()
        return {"ok": True}

    def check_alerts(self):
        """
        Check all active alerts and trigger notifications.
        Called by Celery task every 5 minutes.
        """
        from models import db, AirlineAlert

        alerts = AirlineAlert.query.filter_by(is_active=True).all()
        triggered = 0

        for alert in alerts:
            try:
                # Minimum 6-hour gap between triggers
                if alert.last_triggered:
                    hours_since = (datetime.utcnow() - alert.last_triggered).total_seconds() / 3600
                    if hours_since < 6:
                        continue

                if alert.alert_type in ("price_drop", "price_spike"):
                    if self._check_price_alert(alert):
                        self._trigger_alert(alert)
                        triggered += 1
                elif alert.alert_type == "demand_surge":
                    if self._check_demand_alert(alert):
                        self._trigger_alert(alert)
                        triggered += 1

            except Exception as e:
                logger.error(f"Alert check error {alert.alert_id}: {e}")

        return {"alerts_checked": len(alerts), "alerts_triggered": triggered}

    def _check_price_alert(self, alert):
        """Check if competitor price changed beyond threshold."""
        from models import db, PriceHistory

        if not alert.route_pattern or not alert.competitor_iata:
            return False

        parts = alert.route_pattern.split("-")
        if len(parts) != 2:
            return False
        origin, dest_pattern = parts

        # Compare last 24h average vs prior 7-day average
        now = datetime.utcnow()
        recent_cutoff = now - timedelta(hours=24)
        baseline_start = now - timedelta(days=7)

        base_filter = [
            PriceHistory.origin == origin,
            PriceHistory.airline.contains(alert.competitor_iata),
        ]
        if dest_pattern != "*":
            base_filter.append(PriceHistory.destination == dest_pattern)
        if alert.market:
            base_filter.append(PriceHistory.market == alert.market)

        # Baseline average (7 days)
        baseline = db.session.query(
            db.func.avg(PriceHistory.price_usd)
        ).filter(
            *base_filter,
            PriceHistory.recorded_at >= baseline_start,
            PriceHistory.recorded_at < recent_cutoff,
        ).scalar()

        # Recent average (24h)
        recent = db.session.query(
            db.func.avg(PriceHistory.price_usd)
        ).filter(
            *base_filter,
            PriceHistory.recorded_at >= recent_cutoff,
        ).scalar()

        if not baseline or not recent:
            return False

        change_pct = ((recent - baseline) / baseline) * 100

        if alert.alert_type == "price_drop" and alert.price_change_pct:
            return change_pct <= -abs(alert.price_change_pct)
        elif alert.alert_type == "price_spike" and alert.price_change_pct:
            return change_pct >= abs(alert.price_change_pct)

        if alert.price_change_usd:
            change_usd = recent - baseline
            if alert.alert_type == "price_drop":
                return change_usd <= -abs(alert.price_change_usd)
            elif alert.alert_type == "price_spike":
                return change_usd >= abs(alert.price_change_usd)

        return False

    def _check_demand_alert(self, alert):
        """Check if search demand surged beyond threshold."""
        from models import db, SearchHistory

        if not alert.route_pattern or not alert.demand_change_pct:
            return False

        parts = alert.route_pattern.split("-")
        if len(parts) != 2:
            return False
        origin, dest_pattern = parts

        now = datetime.utcnow()
        recent_cutoff = now - timedelta(hours=24)
        baseline_start = now - timedelta(days=7)

        base_filter = [SearchHistory.origin == origin]
        if dest_pattern != "*":
            base_filter.append(SearchHistory.destination == dest_pattern)

        baseline_daily = db.session.query(
            db.func.count(SearchHistory.id)
        ).filter(
            *base_filter,
            SearchHistory.created_at >= baseline_start,
            SearchHistory.created_at < recent_cutoff,
        ).scalar() or 0

        baseline_avg = baseline_daily / 6  # 6-day baseline

        recent_count = db.session.query(
            db.func.count(SearchHistory.id)
        ).filter(
            *base_filter,
            SearchHistory.created_at >= recent_cutoff,
        ).scalar() or 0

        if baseline_avg <= 0:
            return recent_count > 0

        change_pct = ((recent_count - baseline_avg) / baseline_avg) * 100
        return change_pct >= abs(alert.demand_change_pct)

    def _trigger_alert(self, alert):
        """Fire an alert notification via SSE (and optionally webhook)."""
        from models import db

        alert.last_triggered = datetime.utcnow()
        alert.trigger_count = (alert.trigger_count or 0) + 1
        db.session.commit()

        # SSE event
        try:
            from event_stream import publish_event
            client = alert.client
            publish_event(
                f"airline:{client.client_id if client else 'unknown'}",
                "competitive_alert",
                {
                    "alert_id": alert.alert_id,
                    "alert_type": alert.alert_type,
                    "route_pattern": alert.route_pattern,
                    "competitor": alert.competitor_iata,
                },
            )
        except Exception:
            pass

        logger.info(f"Alert triggered: {alert.alert_id} ({alert.alert_type})")

    # ------------------------------------------------------------------
    # Report Generation
    # ------------------------------------------------------------------

    def generate_pricing_report(self, client_id, report_type="weekly",
                                period_days=7, routes=None):
        """
        Queue a pricing intelligence report for async generation.

        Report types: daily, weekly, monthly, competitor_analysis
        """
        from models import db, AirlineReport

        client = self.get_client(client_id)
        if not client:
            return {"error": "Client not found"}

        report_id = f"RPT-{secrets.token_hex(6).upper()}"
        period_end = date.today()
        period_start = period_end - timedelta(days=period_days)

        report = AirlineReport(
            report_id=report_id,
            client_id=client.id,
            report_type=f"pricing_{report_type}",
            period_start=period_start,
            period_end=period_end,
            status="generating",
        )
        db.session.add(report)
        db.session.commit()

        # Queue async generation
        try:
            from celery_app import generate_airline_pricing_report
            generate_airline_pricing_report.delay(report.id, routes or [])
        except Exception as e:
            logger.warning(f"Celery not available, generating synchronously: {e}")
            self._build_report_sync(report.id, routes or [])

        client.reports_generated = (client.reports_generated or 0) + 1
        db.session.commit()

        logger.info(f"Report queued: {report_id} for {client_id}")
        return {
            "report_id": report_id,
            "status": "generating",
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
        }

    def _build_report_sync(self, report_id, routes):
        """Synchronous report builder (fallback when Celery unavailable)."""
        from models import db, AirlineReport, PriceHistory

        report = AirlineReport.query.get(report_id)
        if not report:
            return

        try:
            cutoff = datetime.utcnow() - timedelta(days=7)
            report_data = {
                "generated_at": datetime.utcnow().isoformat(),
                "period_start": report.period_start.isoformat(),
                "period_end": report.period_end.isoformat(),
                "routes": [],
            }

            total_routes = 0
            total_markets = set()
            total_data_points = 0

            for route_pattern in routes:
                parts = route_pattern.upper().split("-")
                if len(parts) != 2:
                    continue
                origin, destination = parts

                prices = PriceHistory.query.filter_by(
                    origin=origin, destination=destination
                ).filter(PriceHistory.recorded_at >= cutoff).all()

                if not prices:
                    continue

                airlines = {}
                for p in prices:
                    if not p.airline:
                        continue
                    if p.airline not in airlines:
                        airlines[p.airline] = {"prices": [], "markets": set()}
                    airlines[p.airline]["prices"].append(p.price_usd)
                    airlines[p.airline]["markets"].add(p.market)
                    total_data_points += 1

                route_summary = {"route": route_pattern, "airlines": []}
                for airline, data in airlines.items():
                    avg_p = sum(data["prices"]) / len(data["prices"]) if data["prices"] else 0
                    route_summary["airlines"].append({
                        "airline": airline,
                        "avg_price_usd": round(avg_p, 2),
                        "min_price_usd": round(min(data["prices"]), 2) if data["prices"] else 0,
                        "max_price_usd": round(max(data["prices"]), 2) if data["prices"] else 0,
                        "sample_count": len(data["prices"]),
                        "markets": list(data["markets"]),
                    })
                    total_markets.update(data["markets"])

                report_data["routes"].append(route_summary)
                total_routes += 1

            report.report_data = json.dumps(report_data)
            report.summary = f"Pricing analysis for {total_routes} routes across {len(total_markets)} markets"
            report.routes_analyzed = total_routes
            report.markets_analyzed = len(total_markets)
            report.data_points = total_data_points
            report.status = "completed"
            db.session.commit()

        except Exception as e:
            logger.error(f"Sync report generation failed: {e}")
            report.status = "failed"
            report.error_message = str(e)
            db.session.commit()

    def get_report(self, client_id, report_id):
        """Retrieve a generated report."""
        from models import AirlineReport

        client = self.get_client(client_id)
        if not client:
            return {"error": "Client not found"}

        report = AirlineReport.query.filter_by(
            report_id=report_id, client_id=client.id
        ).first()
        if not report:
            return {"error": "Report not found"}

        result = report.to_dict()
        if report.status == "completed" and report.report_data:
            result["data"] = json.loads(report.report_data)
        return result

    def list_reports(self, client_id, limit=50):
        """List reports for a client."""
        from models import AirlineReport

        client = self.get_client(client_id)
        if not client:
            return {"error": "Client not found"}

        reports = AirlineReport.query.filter_by(
            client_id=client.id
        ).order_by(AirlineReport.generated_at.desc()).limit(limit).all()
        return [r.to_dict() for r in reports]

    # ------------------------------------------------------------------
    # Multi-market Route Summary
    # ------------------------------------------------------------------

    def get_route_summary(self, client_id, route, days_back=30):
        """
        Complete intelligence summary for a route across all markets.

        Combines pricing, ancillary, and demand data.
        """
        from models import db, PriceHistory

        client = self.get_client(client_id)
        if not client:
            return {"error": "Client not found"}

        parsed = self._parse_route(route)
        if not parsed:
            return {"error": "Invalid route format"}
        origin, destination = parsed

        cutoff = datetime.utcnow() - timedelta(days=days_back)

        # Market-by-market pricing
        market_data = db.session.query(
            PriceHistory.market,
            db.func.avg(PriceHistory.price_usd).label("avg_price"),
            db.func.min(PriceHistory.price_usd).label("min_price"),
            db.func.count(PriceHistory.id).label("samples"),
        ).filter(
            PriceHistory.origin == origin,
            PriceHistory.destination == destination,
            PriceHistory.recorded_at >= cutoff,
        ).group_by(PriceHistory.market).all()

        markets = [
            {
                "market": r.market,
                "avg_price_usd": round(r.avg_price, 2),
                "min_price_usd": round(r.min_price, 2),
                "samples": r.samples,
            }
            for r in sorted(market_data, key=lambda x: x.avg_price)
        ]

        cheapest = markets[0] if markets else None
        most_expensive = markets[-1] if markets else None
        spread_usd = round(most_expensive["avg_price_usd"] - cheapest["avg_price_usd"], 2) if cheapest and most_expensive else 0

        return {
            "route": route.upper(),
            "days_analyzed": days_back,
            "markets_analyzed": len(markets),
            "cheapest_market": cheapest,
            "most_expensive_market": most_expensive,
            "price_spread_usd": spread_usd,
            "markets": markets,
        }


# Global instance
airline_intel_manager = AirlineIntelligenceManager()
