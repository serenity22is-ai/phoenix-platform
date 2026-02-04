"""
PHOENIX Celery Application

Distributed task queue for background processing:
- Payment verification polling
- Deal expiration cleanup
- Price alert notifications
- P2P escrow monitoring
- P2P helper matching
- Session/token cleanup

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
    "phoenix",
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
    task_default_queue="phoenix",
    task_routes={
        "celery_app.verify_payments": {"queue": "payments"},
        "celery_app.monitor_p2p_escrows": {"queue": "payments"},
        "celery_app.match_pending_p2p": {"queue": "p2p"},
        "celery_app.expire_deals": {"queue": "maintenance"},
        "celery_app.check_price_alerts": {"queue": "maintenance"},
        "celery_app.cleanup_sessions": {"queue": "maintenance"},
        "celery_app.check_airline_alerts": {"queue": "maintenance"},
        "celery_app.calculate_competitor_pricing": {"queue": "maintenance"},
        "celery_app.generate_daily_airline_reports": {"queue": "maintenance"},
        "celery_app.generate_airline_pricing_report": {"queue": "maintenance"},
        "celery_app.snapshot_ancillary_data": {"queue": "maintenance"},
        "celery_app.record_node_heartbeats": {"queue": "p2p"},
        "celery_app.calculate_citizenserp_payouts": {"queue": "payments"},
        "celery_app.distribute_citizenserp_payouts": {"queue": "payments"},
        "celery_app.cleanup_stale_nodes": {"queue": "maintenance"},
        "celery_app.auto_resolve_stale_disputes": {"queue": "maintenance"},
        "celery_app.detect_feedback_patterns": {"queue": "maintenance"},
        "celery_app.check_feedback_triggered_alerts": {"queue": "maintenance"},
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
        "monitor-p2p-escrows-60s": {
            "task": "celery_app.monitor_p2p_escrows",
            "schedule": 60.0,
        },
        "match-pending-p2p-30s": {
            "task": "celery_app.match_pending_p2p",
            "schedule": 30.0,
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
        "record-node-heartbeats-5m": {
            "task": "celery_app.record_node_heartbeats",
            "schedule": 300.0,  # 5 minutes
        },
        "calculate-citizenserp-payouts-midnight": {
            "task": "celery_app.calculate_citizenserp_payouts",
            "schedule": crontab(hour=0, minute=0),  # Midnight UTC
        },
        "distribute-citizenserp-payouts-1am": {
            "task": "celery_app.distribute_citizenserp_payouts",
            "schedule": crontab(hour=1, minute=0),  # 1 AM UTC
        },
        "cleanup-stale-nodes-10m": {
            "task": "celery_app.cleanup_stale_nodes",
            "schedule": 600.0,  # 10 minutes
        },
        "auto-resolve-disputes-30m": {
            "task": "celery_app.auto_resolve_stale_disputes",
            "schedule": 1800.0,  # 30 minutes
        },
        "detect-feedback-patterns-6h": {
            "task": "celery_app.detect_feedback_patterns",
            "schedule": 21600.0,  # 6 hours
        },
        "check-triggered-alerts-10m": {
            "task": "celery_app.check_feedback_triggered_alerts",
            "schedule": 600.0,  # 10 minutes
        },
        "harvest-cycle-10m": {
            "task": "celery_app.run_harvest_cycle",
            "schedule": 600.0,  # 10 minutes
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
            except Exception as e:
                logger.error(f"Alert {alert.id} error: {e}")

        return {"alerts_sent": sent}


# ============================================================
# P2P Tasks
# ============================================================

@celery.task
def monitor_p2p_escrows():
    """Monitor on-chain escrow status for active P2P transactions."""
    app = _get_flask_app()
    with app.app_context():
        from models import db, P2PTransaction, P2PEscrow

        active_statuses = ["escrow_locked", "helper_accepted", "purchasing"]
        active_txs = P2PTransaction.query.filter(
            P2PTransaction.status.in_(active_statuses)
        ).all()

        checked = 0
        for tx in active_txs:
            try:
                escrow = P2PEscrow.query.filter_by(p2p_transaction_id=tx.id).first()
                if not escrow or not escrow.create_tx_hash:
                    continue

                # Check for timeout (24h from escrow creation)
                if escrow.cancel_after and datetime.utcnow() > escrow.cancel_after:
                    tx.status = "failed"
                    tx.failure_reason = "Escrow timed out"
                    tx.cancelled_at = datetime.utcnow()
                    escrow.status = "expired"
                    escrow.cancelled_at = datetime.utcnow()
                    db.session.commit()
                    logger.warning(f"P2P escrow timed out: {tx.transaction_id}")

                    emit_event.delay(
                        f"user:{tx.buyer_id}", "p2p_timeout",
                        {"transaction_id": tx.transaction_id},
                    )
                    continue

                checked += 1
            except Exception as e:
                logger.error(f"Escrow monitor error for {tx.transaction_id}: {e}")

        return {"checked": checked}


@celery.task
def match_pending_p2p():
    """Auto-match pending P2P requests with available helpers using smart scoring."""
    app = _get_flask_app()
    with app.app_context():
        from models import db, P2PTransaction
        from helper_matching import match_helper

        pending = P2PTransaction.query.filter_by(status="requested").filter(
            P2PTransaction.created_at > datetime.utcnow() - timedelta(hours=2)
        ).all()

        matched = 0
        for tx in pending:
            try:
                result = match_helper(
                    target_market=tx.target_market,
                    transaction_amount_usd=tx.us_price_usd,
                )
                if result:
                    tx.helper_id = result["helper_id"]
                    tx.status = "matched"
                    tx.matched_at = datetime.utcnow()
                    db.session.commit()
                    matched += 1
                    logger.info(
                        f"P2P matched: {tx.transaction_id} → helper {result['helper_id']} "
                        f"(score={result['score']})"
                    )

                    emit_event.delay(
                        f"user:{tx.buyer_id}", "p2p_matched",
                        {
                            "transaction_id": tx.transaction_id,
                            "helper_market": tx.target_market,
                            "match_score": result["score"],
                        },
                    )
            except Exception as e:
                logger.error(f"P2P match error for {tx.transaction_id}: {e}")

        return {"matched": matched}


# ============================================================
# One-off P2P Tasks (triggered by API)
# ============================================================

@celery.task
def process_p2p_booking(transaction_id):
    """Process a single P2P booking through the full workflow."""
    app = _get_flask_app()
    with app.app_context():
        from p2p_orchestrator import P2POrchestrator

        orchestrator = P2POrchestrator()
        try:
            result = orchestrator.run_full_workflow(transaction_id)
            return {"transaction_id": transaction_id, "result": str(result)}
        except Exception as e:
            logger.error(f"P2P booking failed: {transaction_id}: {e}")
            return {"transaction_id": transaction_id, "error": str(e)}


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
        r.publish(f"phoenix:events:{channel}", payload)
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
# CitizenSERP Payout Tasks
# ============================================================

@celery.task
def record_node_heartbeats():
    """Verify active nodes, close stale sessions, submit on-chain attestations (every 5 min)."""
    app = _get_flask_app()
    with app.app_context():
        from citizenserp_payouts import citizenserp_manager
        from models import HelperProfile

        # Get currently online helpers
        online_helpers = HelperProfile.query.filter_by(
            is_online=True, is_active=True, is_approved=True
        ).all()
        active_user_ids = [h.user_id for h in online_helpers]

        # Refresh heartbeats and close stale sessions
        citizenserp_manager.refresh_heartbeats(active_user_ids)
        stale_count = citizenserp_manager.close_stale_sessions()

        # Batch on-chain attestation
        attested = 0
        batch_size = citizenserp_manager.config["attestation_batch_size"]
        if active_user_ids:
            for i in range(0, len(active_user_ids), batch_size):
                batch = active_user_ids[i:i + batch_size]
                try:
                    citizenserp_manager.submit_uptime_attestation(batch)
                    attested += len(batch)
                except Exception as e:
                    logger.error(f"Attestation batch failed: {e}")

        return {"online": len(active_user_ids), "stale_closed": stale_count, "attested": attested}


@celery.task
def calculate_citizenserp_payouts():
    """Calculate previous day's CitizenSERP payout distribution (midnight UTC daily)."""
    app = _get_flask_app()
    with app.app_context():
        from citizenserp_payouts import citizenserp_manager
        result = citizenserp_manager.calculate_epoch_payouts()
        logger.info(f"CitizenSERP epoch calculated: {result}")
        return result


@celery.task(bind=True, max_retries=3)
def distribute_citizenserp_payouts(self):
    """Execute XRPL RLUSD payments to all eligible nodes (1 AM UTC daily)."""
    app = _get_flask_app()
    with app.app_context():
        from citizenserp_payouts import citizenserp_manager
        from models import NodePayoutEpoch

        # Find latest calculated epoch
        epoch = NodePayoutEpoch.query.filter_by(
            status='calculated'
        ).order_by(NodePayoutEpoch.created_at.desc()).first()

        if not epoch:
            return {"status": "no_epoch_to_distribute"}

        try:
            result = citizenserp_manager.distribute_payouts(epoch.epoch_id)
            logger.info(f"CitizenSERP distribution: {result}")
            return result
        except Exception as e:
            logger.error(f"CitizenSERP distribution failed: {e}")
            raise self.retry(exc=e, countdown=300)


# ============================================================
# Node Registry Tasks
# ============================================================

@celery.task
def cleanup_stale_nodes():
    """Mark stale nodes as offline and emit SSE events (every 10 min)."""
    app = _get_flask_app()
    with app.app_context():
        try:
            from node_registry import node_registry
            cleaned = node_registry.cleanup_stale_nodes()
            if cleaned:
                logger.info(f"Cleaned {len(cleaned)} stale nodes: {cleaned}")
            return {"stale_cleaned": len(cleaned), "node_ids": cleaned}
        except Exception as e:
            logger.error(f"Stale node cleanup failed: {e}")
            return {"error": str(e)}


# ============================================================
# Dispute Arbitration Tasks
# ============================================================

@celery.task
def auto_resolve_stale_disputes():
    """Auto-evaluate and resolve stale disputes (every 30 min)."""
    app = _get_flask_app()
    with app.app_context():
        try:
            from dispute_resolution import dispute_manager
            results = dispute_manager.check_auto_resolvable()
            resolved = [r for r in results if r.get("auto")]
            escalated = [r for r in results if r.get("status") == "escalated_to_admin"]
            logger.info(
                f"Auto-dispute: {len(results)} evaluated, "
                f"{len(resolved)} resolved, {len(escalated)} escalated"
            )
            return {
                "evaluated": len(results),
                "auto_resolved": len(resolved),
                "escalated": len(escalated),
            }
        except Exception as e:
            logger.error(f"Auto-dispute resolution failed: {e}")
            return {"error": str(e)}


# ============================================================
# Intelligence Feedback Tasks
# ============================================================

@celery.task
def detect_feedback_patterns():
    """Run pattern detection on accumulated price data (every 6 hours)."""
    app = _get_flask_app()
    with app.app_context():
        try:
            from intelligence_feedback import feedback_engine
            patterns = feedback_engine.detect_patterns(hours_back=6)
            logger.info(
                f"Feedback patterns: {len(patterns.get('anomalies', []))} anomalies, "
                f"{len(patterns.get('opportunities', []))} opportunities"
            )
            return patterns
        except Exception as e:
            logger.error(f"Feedback pattern detection failed: {e}")
            return {"error": str(e)}


@celery.task
def check_feedback_triggered_alerts():
    """Check if recent prices trigger any user price alerts (every 10 min)."""
    app = _get_flask_app()
    with app.app_context():
        try:
            from intelligence_feedback import feedback_engine
            triggered = feedback_engine.check_triggered_alerts()
            if triggered:
                logger.info(f"Triggered {len(triggered)} price alerts")
            return {"triggered": len(triggered)}
        except Exception as e:
            logger.error(f"Alert check failed: {e}")
            return {"error": str(e)}


# ============================================================
# Harvest Scheduler Tasks (Build #79)
# ============================================================

@celery.task(name="celery_app.run_harvest_cycle")
def run_harvest_cycle():
    """Autonomous data harvesting — identify gaps and dispatch tasks (every 10 min)."""
    app = _get_flask_app()
    with app.app_context():
        try:
            from harvest_scheduler import harvest_scheduler
            result = harvest_scheduler.run_harvest_cycle()
            if result.tasks_dispatched > 0:
                logger.info(
                    f"Harvest cycle: {result.tasks_dispatched} dispatched, "
                    f"{result.gaps_identified} gaps"
                )
            return {
                "cycle_id": result.cycle_id,
                "dispatched": result.tasks_dispatched,
                "gaps": result.gaps_identified,
                "standing_orders": result.standing_orders_processed,
            }
        except Exception as e:
            logger.error(f"Harvest cycle error: {e}")
            return {"error": str(e)}


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
