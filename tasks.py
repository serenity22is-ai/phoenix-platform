"""
PHOENIX Background Tasks

Handles scheduled tasks:
- Payment verification polling
- Deal expiration cleanup
- Price alert checks
- Session cleanup
"""

import threading
import time
from datetime import datetime, timedelta
from typing import List, Optional
import logging

logger = logging.getLogger(__name__)

# Task control
_task_threads = {}
_stop_events = {}


def start_background_tasks(app):
    """Start all background tasks."""
    logger.info("Starting background tasks...")

    # Payment verification polling (every 30 seconds)
    start_task('payment_polling', payment_verification_task, app, interval=30)

    # Deal expiration cleanup (every 5 minutes)
    start_task('deal_cleanup', deal_expiration_task, app, interval=300)

    # Price alert checks (every 15 minutes)
    start_task('price_alerts', price_alert_task, app, interval=900)

    # Browsing event processing (every 15 seconds)
    start_task('browsing_events', browsing_event_processing_task, app, interval=15)

    # Payout disbursement (every 5 minutes)
    start_task('payout_disbursement', payout_disbursement_task, app, interval=300)

    # Payout verification (every 2 minutes)
    start_task('payout_verification', payout_verification_task, app, interval=120)

    # Autonomous harvest cycle (every 10 minutes)
    start_task('harvest_cycle', harvest_cycle_task, app, interval=600)

    # Build #80 — Strategy insight aggregation (every 6 hours)
    start_task('strategy_aggregation', strategy_aggregation_task, app, interval=21600)

    logger.info("Background tasks started")


def stop_background_tasks():
    """Stop all background tasks."""
    logger.info("Stopping background tasks...")
    for name, event in _stop_events.items():
        event.set()
    for name, thread in _task_threads.items():
        thread.join(timeout=5)
    logger.info("Background tasks stopped")


def start_task(name: str, func, app, interval: int):
    """Start a background task."""
    stop_event = threading.Event()
    _stop_events[name] = stop_event

    def task_wrapper():
        while not stop_event.is_set():
            try:
                with app.app_context():
                    func()
            except Exception as e:
                logger.error(f"Task {name} error: {e}")
            stop_event.wait(interval)

    thread = threading.Thread(target=task_wrapper, daemon=True, name=f"task_{name}")
    thread.start()
    _task_threads[name] = thread
    logger.info(f"Started task: {name} (interval: {interval}s)")


def payment_verification_task():
    """
    Poll XRPL for pending payments and verify them.
    Updates payment status when transactions are found.
    """
    from models import db, Payment, Deal
    from main import verify_payment as verify_xrp_payment, XRPL_CONFIG
    from email_service import send_booking_confirmation_email

    # Get pending payments that haven't expired
    pending = Payment.query.filter_by(status='pending').filter(
        Payment.expires_at > datetime.utcnow()
    ).all()

    for payment in pending:
        try:
            # Check XRPL for payment
            result = verify_xrp_payment(
                payment.destination_tag,
                payment.expected_xrp
            )

            if result.get('verified'):
                payment.status = 'verified'
                payment.received_xrp = result.get('amount_xrp')
                payment.tx_hash = result.get('tx_hash')
                payment.sender_address = result.get('sender')
                payment.verified_at = datetime.utcnow()

                db.session.commit()
                logger.info(f"Payment verified: {payment.id} (tx: {payment.tx_hash})")

                # Send confirmation email
                if payment.user and payment.deal:
                    send_booking_confirmation_email(
                        to=payment.user.email,
                        booking={
                            'deal_id': payment.deal.deal_id,
                            'route': f"{payment.deal.origin} → {payment.deal.destination}",
                            'airline': payment.deal.airline,
                            'date': payment.deal.departure_date.isoformat() if payment.deal.departure_date else 'N/A',
                            'fee_xrp': payment.received_xrp,
                            'savings': payment.deal.user_savings_usd or 0
                        },
                        name=payment.user.name
                    )

        except Exception as e:
            logger.error(f"Error verifying payment {payment.id}: {e}")

    # Mark expired payments
    expired = Payment.query.filter_by(status='pending').filter(
        Payment.expires_at <= datetime.utcnow()
    ).all()

    for payment in expired:
        payment.status = 'expired'
        logger.info(f"Payment expired: {payment.id}")

    if expired:
        db.session.commit()


def deal_expiration_task():
    """
    Mark expired deals as inactive.
    Deals expire after 24 hours or if the flight date has passed.
    """
    from models import db, Deal

    now = datetime.utcnow()

    # Mark deals with passed expiry time as inactive
    expired_by_time = Deal.query.filter(
        Deal.is_active == True,
        Deal.expires_at <= now
    ).all()

    for deal in expired_by_time:
        deal.is_active = False
        logger.info(f"Deal expired (time): {deal.deal_id}")

    # Mark deals with passed departure date as inactive
    today = now.date()
    expired_by_date = Deal.query.filter(
        Deal.is_active == True,
        Deal.departure_date < today
    ).all()

    for deal in expired_by_date:
        deal.is_active = False
        logger.info(f"Deal expired (date): {deal.deal_id}")

    if expired_by_time or expired_by_date:
        db.session.commit()
        logger.info(f"Expired {len(expired_by_time) + len(expired_by_date)} deals")


def price_alert_task():
    """
    Check for deals matching user price alerts.
    Sends email notifications when matching deals are found.
    """
    from models import db, PriceAlert, Deal, User
    from email_service import send_price_alert_email

    # Get active alerts
    active_alerts = PriceAlert.query.filter_by(is_active=True).all()

    for alert in active_alerts:
        try:
            # Find matching deals
            query = Deal.query.filter_by(is_active=True)

            if alert.origin:
                query = query.filter_by(origin=alert.origin)
            if alert.destination:
                query = query.filter_by(destination=alert.destination)

            deals = query.all()

            matching_deals = []
            for deal in deals:
                # Check price threshold
                if alert.max_price_usd and deal.arbitrage_price_usd:
                    if deal.arbitrage_price_usd > alert.max_price_usd:
                        continue

                # Check savings threshold
                if alert.min_savings_percent and deal.savings_percent:
                    if deal.savings_percent < alert.min_savings_percent:
                        continue

                # Check date range
                if alert.date_from and deal.departure_date:
                    if deal.departure_date < alert.date_from:
                        continue
                if alert.date_to and deal.departure_date:
                    if deal.departure_date > alert.date_to:
                        continue

                matching_deals.append({
                    'route': f"{deal.origin} → {deal.destination}",
                    'airline': deal.airline,
                    'savings': deal.user_savings_usd or 0,
                    'savings_pct': deal.savings_percent or 0,
                    'price': deal.arbitrage_price_usd or 0,
                    'market': deal.arbitrage_market
                })

            if matching_deals and alert.notify_email:
                # Don't spam - check last triggered
                if alert.last_triggered:
                    hours_since = (datetime.utcnow() - alert.last_triggered).total_seconds() / 3600
                    if hours_since < 6:  # Don't notify more than once per 6 hours
                        continue

                # Get user
                user = User.query.get(alert.user_id)
                if user and user.email:
                    send_price_alert_email(
                        to=user.email,
                        deals=matching_deals[:5],  # Limit to 5 deals
                        name=user.name
                    )

                    alert.last_triggered = datetime.utcnow()
                    db.session.commit()
                    logger.info(f"Sent price alert to {user.email}: {len(matching_deals)} deals")

        except Exception as e:
            logger.error(f"Error processing alert {alert.id}: {e}")


def cleanup_sessions_task():
    """Clean up expired sessions and tokens."""
    from models import db, User

    now = datetime.utcnow()

    # Clear expired verification tokens
    User.query.filter(
        User.verification_token_expires < now
    ).update({
        'verification_token': None,
        'verification_token_expires': None
    })

    # Clear expired reset tokens
    User.query.filter(
        User.reset_token_expires < now
    ).update({
        'reset_token': None,
        'reset_token_expires': None
    })

    db.session.commit()


def browsing_event_processing_task():
    """
    Process pending browsing events from the Chrome extension pipeline.
    Picks up unprocessed BrowsingEvents and routes them through downstream
    hooks (ad_intelligence, feedback_engine, yield_dashboard).
    """
    try:
        from node_data_processor import node_data_processor
        processed = node_data_processor.process_pending_events(batch_size=200)
        if processed > 0:
            logger.info(f"Browsing event worker: processed {processed} events")
    except Exception as e:
        logger.error(f"Browsing event processing error: {e}")


def payout_disbursement_task():
    """Process pending node payouts — submit XRPL RLUSD transactions."""
    try:
        from payout_disbursement import disbursement_worker
        result = disbursement_worker.process_pending_payouts(batch_size=50)
        if result.get("processed", 0) > 0:
            logger.info(f"Payout disbursement: {result}")
    except Exception as e:
        logger.error(f"Payout disbursement error: {e}")


def payout_verification_task():
    """Verify sent payouts — check XRPL for confirmation."""
    try:
        from payout_disbursement import disbursement_worker
        result = disbursement_worker.verify_sent_payouts(batch_size=100)
        if result.get("verified", 0) > 0:
            logger.info(f"Payout verification: {result}")
    except Exception as e:
        logger.error(f"Payout verification error: {e}")


def harvest_cycle_task():
    """Autonomous data harvesting — fill observation gaps (every 10 min)."""
    try:
        from harvest_scheduler import harvest_scheduler
        result = harvest_scheduler.run_harvest_cycle()
        if result.tasks_dispatched > 0:
            logger.info(f"Harvest: {result.tasks_dispatched} dispatched, {result.gaps_identified} gaps")
    except Exception as e:
        logger.error(f"Harvest cycle error: {e}")


def strategy_aggregation_task():
    """Build #80: Aggregate strategy observations into insights (every 6h)."""
    try:
        from strategy_learner import strategy_learner
        agg = strategy_learner.aggregate_insights(
            min_observations=5, lookback_hours=168
        )
        eff = strategy_learner.evaluate_strategy_effectiveness(hours_back=168)
        logger.info(
            f"Strategy aggregation: {agg.get('insights_created', 0)} new, "
            f"{agg.get('insights_updated', 0)} updated, "
            f"verdict={eff.get('verdict', 'unknown')}"
        )
    except Exception as e:
        logger.error(f"Strategy aggregation error: {e}")
