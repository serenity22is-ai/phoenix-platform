"""
MYSTES Celery Application

Distributed task queue for background processing:
- Payment verification polling
- Deal expiration cleanup
- Price alert notifications
- Session/token cleanup
- Airline intelligence reports
- Strategy learning aggregation

Usage:
    # Start worker
    celery -A celery_app.celery worker --loglevel=info

    # Start beat scheduler (periodic tasks)
    celery -A celery_app.celery beat --loglevel=info

    # Combined (dev only)
    celery -A celery_app.celery worker --beat --loglevel=info
"""

import os
import logging
from datetime import datetime, timedelta
from celery import Celery
from celery.schedules import crontab

logger = logging.getLogger(__name__)

# --- Celery Configuration ---

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
CELERY_BROKER = os.environ.get("CELERY_BROKER_URL", f"{REDIS_URL}/2")
CELERY_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", f"{REDIS_URL}/3")

celery = Celery(
    "mystes",
    broker=CELERY_BROKER,
    backend=CELERY_BACKEND,
)

celery.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_soft_time_limit=120,
    task_time_limit=300,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_default_queue="mystes",
    task_routes={
        "celery_app.verify_payments": {"queue": "payments"},
        "celery_app.expire_deals": {"queue": "maintenance"},
        "celery_app.check_price_alerts": {"queue": "maintenance"},
        "celery_app.cleanup_sessions": {"queue": "maintenance"},
        "celery_app.check_airline_alerts": {"queue": "maintenance"},
        "celery_app.calculate_competitor_pricing": {"queue": "maintenance"},
        "celery_app.generate_daily_airline_reports": {"queue": "maintenance"},
        "celery_app.generate_airline_pricing_report": {"queue": "maintenance"},
        "celery_app.snapshot_ancillary_data": {"queue": "maintenance"},
    },
    beat_schedule={
        "verify-payments-30s": {
            "task": "celery_app.verify_payments",
            "schedule": 30.0,
        },
        "expire-deals-5m": {
            "task": "celery_app.expire_deals",
            "schedule": 300.0,
        },
        "check-price-alerts-15m": {
            "task": "celery_app.check_price_alerts",
            "schedule": 900.0,
        },
        "cleanup-sessions-hourly": {
            "task": "celery_app.cleanup_sessions",
            "schedule": 3600.0,
        },
        "recalculate-commercial-tiers-daily": {
            "task": "celery_app.recalculate_commercial_tiers",
            "schedule": 86400.0,  # 24 hours
        },
        "check-airline-alerts-5m": {
            "task": "celery_app.check_airline_alerts",
            "schedule": 300.0,  # 5 minutes
        },
        "snapshot-ancillary-data-hourly": {
            "task": "celery_app.snapshot_ancillary_data",
            "schedule": 3600.0,  # 1 hour
        },
        "generate-daily-airline-reports": {
            "task": "celery_app.generate_daily_airline_reports",
            "schedule": crontab(hour=6, minute=0),  # 6 AM UTC daily
        },
        "calculate-competitor-pricing-daily": {
            "task": "celery_app.calculate_competitor_pricing",
            "schedule": crontab(hour=4, minute=0),  # 4 AM UTC daily
        },
        # Build #80 — Strategy aggregation
        "aggregate-strategy-insights-6h": {
            "task": "celery_app.aggregate_strategy_insights",
            "schedule": 21600.0,  # 6 hours
        },
    },
)


def _get_flask_app():
    """Lazy import Flask app for task context."""
    from server import app
    return app


# ============================================================
# Payment Tasks
# ============================================================

@celery.task(bind=True, max_retries=3)
def verify_payments(self):
    """Poll XRPL for pending payments and verify them."""
    app = _get_flask_app()
    with app.app_context():
        from models import db, Payment, Deal
        from main import verify_payment as verify_xrp_payment
        from email_service import send_booking_confirmation_email

        pending = Payment.query.filter_by(status="pending").filter(
            Payment.expires_at > datetime.utcnow()
        ).all()

        verified_count = 0
        for payment in pending:
            try:
                result = verify_xrp_payment(
                    payment.destination_tag, payment.expected_xrp
                )
                if result.get("verified"):
                    payment.status = "verified"
                    payment.received_xrp = result.get("amount_xrp")
                    payment.tx_hash = result.get("tx_hash")
                    payment.sender_address = result.get("sender")
                    payment.verified_at = datetime.utcnow()
                    db.session.commit()
                    verified_count += 1
                    logger.info(f"Payment verified: {payment.id}")

                    # Emit SSE event
                    emit_event.delay(
                        f"user:{payment.user_id}",
                        "payment_verified",
                        {"payment_id": payment.id, "tx_hash": payment.tx_hash},
                    )

                    if payment.user and payment.deal:
                        send_booking_confirmation_email(
                            to=payment.user.email,
                            booking={
                                "deal_id": payment.deal.deal_id,
                                "route": f"{payment.deal.origin} → {payment.deal.destination}",
                                "airline": payment.deal.airline,
                                "date": (
                                    payment.deal.departure_date.isoformat()
                                    if payment.deal.departure_date
                                    else "N/A"
                                ),
                                "fee_xrp": payment.received_xrp,
                                "savings": payment.deal.user_savings_usd or 0,
                            },
                            name=payment.user.name,
                        )
            except Exception as e:
                logger.error(f"Error verifying payment {payment.id}: {e}")

        # Expire old payments
        expired = Payment.query.filter_by(status="pending").filter(
            Payment.expires_at <= datetime.utcnow()
        ).all()
        for payment in expired:
            payment.status = "expired"
        if expired:
            db.session.commit()

        return {"verified": verified_count, "expired": len(expired)}


# ============================================================
# Deal Tasks
# ============================================================

@celery.task
def expire_deals():
    """Mark expired deals as inactive."""
    app = _get_flask_app()
    with app.app_context():
        from models import db, Deal

        now = datetime.utcnow()
        today = now.date()

        expired_time = Deal.query.filter(
            Deal.is_active == True, Deal.expires_at <= now
        ).all()
        for deal in expired_time:
            deal.is_active = False

        expired_date = Deal.query.filter(
            Deal.is_active == True, Deal.departure_date < today
        ).all()
        for deal in expired_date:
            deal.is_active = False

        total = len(expired_time) + len(expired_date)
        if total:
            db.session.commit()
            logger.info(f"Expired {total} deals")
        return {"expired": total}


# ============================================================
# Price Alert Tasks
# ============================================================

@celery.task
def check_price_alerts():
    """Check for deals matching user price alerts."""
    app = _get_flask_app()
    with app.app_context():
        from models import db, PriceAlert, Deal, User
        from email_service import send_price_alert_email

        alerts = PriceAlert.query.filter_by(is_active=True).all()
        sent = 0

        for alert in alerts:
            try:
                if alert.last_triggered:
                    hours = (datetime.utcnow() - alert.last_triggered).total_seconds() / 3600
                    if hours < 6:
                        continue

                query = Deal.query.filter_by(is_active=True)
                if alert.origin:
                    query = query.filter_by(origin=alert.origin)
                if alert.destination:
                    query = query.filter_by(destination=alert.destination)

                matching = []
                for deal in query.all():
                    if alert.max_price_usd and deal.arbitrage_price_usd:
                        if deal.arbitrage_price_usd > alert.max_price_usd:
                            continue
                    if alert.min_savings_percent and deal.savings_percent:
                        if deal.savings_percent < alert.min_savings_percent:
                            continue
                    if alert.date_from and deal.departure_date and deal.departure_date < alert.date_from:
                        continue
                    if alert.date_to and deal.departure_date and deal.departure_date > alert.date_to:
                        continue
                    matching.append({
                        "route": f"{deal.origin} → {deal.destination}",
                        "airline": deal.airline,
                        "savings": deal.user_savings_usd or 0,
                        "savings_pct": deal.savings_percent or 0,
                        "price": deal.arbitrage_price_usd or 0,
                        "market": deal.arbitrage_market,
                    })

                if matching and alert.notify_email:
                    user = User.query.get(alert.user_id)
                    if user and user.email:
                        send_price_alert_email(to=user.email, deals=matching[:5], name=user.name)
                        alert.last_triggered = datetime.utcnow()
                        db.session.commit()
                        sent += 1

                        emit_event.delay(
                            f"user:{user.id}", "price_alert",
                            {"count": len(matching), "route": f"{alert.origin}→{alert.destination}"},
                        )

                        # Emit typed SSE price alert for real-time UI
                        try:
                            from event_stream import emit_price_alert
                            emit_price_alert(user.id, {
                                "alert_id": alert.id,
                                "origin": alert.origin,
                                "destination": alert.destination,
                                "deals_found": len(matching),
                                "top_savings": matching[0].get("savings", 0) if matching else 0,
                            })
                        except Exception:
                            pass
            except Exception as e:
                logger.error(f"Alert {alert.id} error: {e}")

        return {"alerts_sent": sent}


# ============================================================
# Maintenance Tasks
# ============================================================

@celery.task
def cleanup_sessions():
    """Clean up expired tokens."""
    app = _get_flask_app()
    with app.app_context():
        from models import db, User

        now = datetime.utcnow()
        v = User.query.filter(User.verification_token_expires < now).update(
            {"verification_token": None, "verification_token_expires": None}
        )
        r = User.query.filter(User.reset_token_expires < now).update(
            {"reset_token": None, "reset_token_expires": None}
        )
        db.session.commit()
        return {"verification_tokens_cleared": v, "reset_tokens_cleared": r}


# ============================================================
# Commercial Tier Recalculation (daily)
# ============================================================

@celery.task
def recalculate_commercial_tiers():
    """Recalculate fee tiers for all commercial accounts based on 30-day volume."""
    app = _get_flask_app()
    with app.app_context():
        from commercial import commercial_manager
        result = commercial_manager.recalculate_tiers()
        logger.info(f"Commercial tier recalculation: {result}")
        return result




# ============================================================
# SSE Event Emission (bridges to event_stream.py)
# ============================================================

@celery.task
def emit_event(channel, event_type, data):
    """Publish an event to Redis pub/sub for SSE delivery."""
    import json
    import redis as redis_lib

    try:
        r = redis_lib.from_url(REDIS_URL)
        payload = json.dumps({"event": event_type, "data": data})
        r.publish(f"mystes:events:{channel}", payload)
    except Exception as e:
        logger.error(f"Failed to emit event {event_type} to {channel}: {e}")


# ============================================================
# Airline Intelligence Tasks
# ============================================================

@celery.task
def check_airline_alerts():
    """Check all active airline competitive alerts (every 5 minutes)."""
    app = _get_flask_app()
    with app.app_context():
        from airline_intelligence import airline_intel_manager
        result = airline_intel_manager.check_alerts()
        if result.get("alerts_triggered"):
            logger.info(f"Airline alerts: {result}")
        return result


@celery.task
def snapshot_ancillary_data():
    """
    Capture ancillary pricing from recent searches into AncillarySnapshot.

    Runs hourly. Queries recent SearchHistory, fetches Amadeus baggage data,
    and persists it for airline intelligence analytics.
    """
    app = _get_flask_app()
    with app.app_context():
        from models import db, AncillarySnapshot, SearchHistory

        cutoff = datetime.utcnow() - timedelta(hours=24)
        recent = SearchHistory.query.filter(
            SearchHistory.created_at >= cutoff,
        ).order_by(SearchHistory.created_at.desc()).limit(50).all()

        snapshots_created = 0

        for search in recent:
            try:
                # Skip if we already have recent ancillary data for this route
                existing = AncillarySnapshot.query.filter_by(
                    origin=search.origin,
                    destination=search.destination,
                    market=search.best_market or "US",
                ).filter(AncillarySnapshot.recorded_at >= cutoff).first()

                if existing:
                    continue

                # Try Amadeus for baggage data
                try:
                    from amadeus_client import AmadeusClient
                    amadeus = AmadeusClient()
                    if not amadeus.is_configured():
                        continue

                    dep_date = search.departure_date
                    if not dep_date:
                        continue

                    result = amadeus.search_flights(
                        origin=search.origin,
                        destination=search.destination,
                        departure_date=dep_date.isoformat() if hasattr(dep_date, 'isoformat') else str(dep_date),
                        max_results=5,
                    )

                    if not result or "error" in result:
                        continue

                    for flight in result.get("flights", [])[:3]:
                        baggage = flight.get("baggage", {})
                        airline = flight.get("airline")
                        if not airline:
                            continue

                        snapshot = AncillarySnapshot(
                            origin=search.origin,
                            destination=search.destination,
                            departure_date=dep_date if hasattr(dep_date, 'year') else None,
                            market=search.best_market or "US",
                            airline=airline,
                            checked_bag_count_included=baggage.get("included_count", 0),
                            checked_bag_weight_kg=baggage.get("weight_kg"),
                            carry_on_included=baggage.get("carry_on_included", True),
                            source="amadeus",
                            data_quality="partial",
                        )
                        db.session.add(snapshot)
                        snapshots_created += 1

                    db.session.commit()

                except ImportError:
                    logger.debug("Amadeus client not available for ancillary snapshots")
                    break

            except Exception as e:
                logger.error(f"Ancillary snapshot error for {search.origin}-{search.destination}: {e}")
                db.session.rollback()

        return {"snapshots_created": snapshots_created}


@celery.task
def generate_daily_airline_reports():
    """
    Generate daily reports for enterprise-tier airline clients.

    Runs at 6 AM UTC daily. Pro clients get weekly reports (checked separately).
    """
    app = _get_flask_app()
    with app.app_context():
        import json as json_lib
        from models import AirlineClient
        from airline_intelligence import airline_intel_manager

        # Enterprise: daily reports
        clients = AirlineClient.query.filter_by(
            is_active=True,
        ).filter(
            AirlineClient.subscription_tier.in_(["enterprise", "pro"])
        ).all()

        reports_generated = 0
        for client in clients:
            try:
                # Enterprise = daily, Pro = only on Mondays (weekly)
                if client.subscription_tier == "pro":
                    from datetime import date
                    if date.today().weekday() != 0:  # Monday = 0
                        continue

                routes = json_lib.loads(client.routes_subscribed) if client.routes_subscribed else []
                if not routes:
                    continue

                period_days = 1 if client.subscription_tier == "enterprise" else 7

                result = airline_intel_manager.generate_pricing_report(
                    client_id=client.client_id,
                    report_type="daily" if period_days == 1 else "weekly",
                    period_days=period_days,
                    routes=routes,
                )

                if "error" not in result:
                    reports_generated += 1

            except Exception as e:
                logger.error(f"Daily report error for {client.client_id}: {e}")

        logger.info(f"Airline reports generated: {reports_generated}/{len(clients)}")
        return {"clients_processed": len(clients), "reports_generated": reports_generated}


@celery.task(bind=True, max_retries=3)
def generate_airline_pricing_report(self, report_id, routes):
    """
    Build a pricing report asynchronously.

    Called by airline_intel_manager.generate_pricing_report().
    """
    app = _get_flask_app()
    with app.app_context():
        from airline_intelligence import airline_intel_manager
        try:
            airline_intel_manager._build_report_sync(report_id, routes)
            return {"report_id": report_id, "status": "completed"}
        except Exception as e:
            logger.error(f"Report generation failed (id={report_id}): {e}")
            raise self.retry(exc=e, countdown=60)


@celery.task
def calculate_competitor_pricing():
    """
    Materialize daily CompetitorPricing from PriceHistory.

    Runs at 4 AM UTC daily. Creates aggregated airline-vs-airline pricing
    snapshots for fast competitive intelligence queries.
    """
    app = _get_flask_app()
    with app.app_context():
        import re as re_lib
        from models import db, PriceHistory, CompetitorPricing
        from datetime import date

        snapshot_date = date.today() - timedelta(days=1)
        cutoff_start = datetime.combine(snapshot_date, datetime.min.time())
        cutoff_end = cutoff_start + timedelta(days=1)

        # Aggregate by route/market/airline
        results = db.session.query(
            PriceHistory.origin,
            PriceHistory.destination,
            PriceHistory.market,
            PriceHistory.airline,
            db.func.avg(PriceHistory.price_usd).label("avg_price"),
            db.func.min(PriceHistory.price_usd).label("min_price"),
            db.func.max(PriceHistory.price_usd).label("max_price"),
            db.func.count(PriceHistory.id).label("sample_count"),
        ).filter(
            PriceHistory.recorded_at >= cutoff_start,
            PriceHistory.recorded_at < cutoff_end,
            PriceHistory.airline.isnot(None),
        ).group_by(
            PriceHistory.origin,
            PriceHistory.destination,
            PriceHistory.market,
            PriceHistory.airline,
        ).all()

        if not results:
            return {"snapshot_date": snapshot_date.isoformat(), "records_created": 0}

        # Group by route+market for ranking
        route_groups = {}
        for r in results:
            key = (r.origin, r.destination, r.market)
            if key not in route_groups:
                route_groups[key] = []
            route_groups[key].append(r)

        records_created = 0
        for key, group in route_groups.items():
            # Calculate market avg
            all_avgs = [g.avg_price for g in group]
            market_avg = sum(all_avgs) / len(all_avgs) if all_avgs else 0

            # Rank by price (cheapest = rank 1)
            sorted_group = sorted(group, key=lambda x: x.avg_price)

            for rank, r in enumerate(sorted_group, 1):
                # Extract IATA from airline string
                iata_match = re_lib.match(r'^([A-Z]{2,3})', (r.airline or "").upper())
                airline_iata = iata_match.group(1) if iata_match else (r.airline or "UNK")[:3].upper()

                price_vs_avg = ((r.avg_price - market_avg) / market_avg * 100) if market_avg > 0 else 0

                comp = CompetitorPricing(
                    origin=r.origin,
                    destination=r.destination,
                    market=r.market,
                    snapshot_date=snapshot_date,
                    airline_iata=airline_iata,
                    avg_price_usd=r.avg_price,
                    min_price_usd=r.min_price,
                    max_price_usd=r.max_price,
                    sample_count=r.sample_count,
                    market_rank=rank,
                    price_vs_market_avg_pct=price_vs_avg,
                )
                db.session.add(comp)
                records_created += 1

        db.session.commit()
        logger.info(f"Competitor pricing: {records_created} records for {snapshot_date}")
        return {"snapshot_date": snapshot_date.isoformat(), "records_created": records_created}




# ============================================================
# Strategy Learning Tasks (Build #80)
# ============================================================

@celery.task(name="celery_app.aggregate_strategy_insights")
def aggregate_strategy_insights():
    """Aggregate strategy observations into insights and evaluate effectiveness (every 6h)."""
    app = _get_flask_app()
    with app.app_context():
        try:
            from strategy_learner import strategy_learner
            agg_result = strategy_learner.aggregate_insights(
                min_observations=5, lookback_hours=168
            )
            eff_result = strategy_learner.evaluate_strategy_effectiveness(
                hours_back=168
            )
            logger.info(
                f"Strategy aggregation: {agg_result.get('insights_created', 0)} new, "
                f"{agg_result.get('insights_updated', 0)} updated, "
                f"{agg_result.get('insights_retired', 0)} retired, "
                f"effectiveness: {eff_result.get('verdict', 'unknown')}"
            )
            return {**agg_result, "effectiveness": eff_result}
        except Exception as e:
            logger.error(f"Strategy aggregation error: {e}")
            return {"error": str(e)}
