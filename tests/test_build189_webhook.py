"""
MYSTES Build #189 — Webhook Idempotency + Booking Status Tests

Tests:
    - WebhookEvent model creation
    - Webhook idempotency (duplicate detection)
    - Booking status API endpoint (/api/v1/booking/<id>/status)
    - Enhanced booking status fields (Build #189 additions)

Run: pytest tests/test_build189_webhook.py -v
MYSTES KYRIOS LLC — Confidential.
"""

import json
import os
import sys
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server import app, db, limiter
from models import User, Deal, Payment, Booking, WebhookEvent


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def client():
    """Test client with in-memory database."""
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['WTF_CSRF_ENABLED'] = False
    app.config['SERVER_NAME'] = 'localhost.localdomain'
    app.config['RATELIMIT_ENABLED'] = False
    app.config['SHARE_TO_SAVE_DISCOUNT'] = 0.05
    app.config['POINTS_REDEMPTION_VALUE'] = 0.001
    limiter.enabled = False

    with app.app_context():
        db.create_all()
        from models import FeatureFlag, SystemSetting
        FeatureFlag.init_default_flags()
        SystemSetting.init_defaults()
        yield app.test_client()
        db.drop_all()

    limiter.enabled = True


@pytest.fixture
def booking_fixtures(client):
    """Create user, deal, payment, and booking for tests. Returns IDs."""
    with app.app_context():
        user = User(
            email='test@webhook.com',
            name='Webhook Test',
        )
        user.set_password('testpass123')
        db.session.add(user)
        db.session.commit()

        deal = Deal(
            deal_id='deal_webhook_test',
            deal_type='flight',
            origin='JFK',
            destination='LAX',
            airline='Test Air',
            home_price_usd=350.00,
            arbitrage_price_usd=250.00,
            gross_savings_usd=100.00,
            platform_fee_usd=45.00,
            user_savings_usd=55.00,
            savings_percent=28.57,
            is_active=True,
            deal_status='claimed',
            claimed_by=user.id,
        )
        db.session.add(deal)
        db.session.commit()

        payment = Payment(
            user_id=user.id,
            deal_id=deal.id,
            payment_method='card',
            amount_usd=250.00,
            status='verified',
            stripe_payment_intent='pi_test_123',
            stripe_session_id='cs_test_123',
            verified_at=datetime.now(timezone.utc),
        )
        db.session.add(payment)
        db.session.commit()

        booking = Booking(
            user_id=user.id,
            deal_id=deal.id,
            payment_id=payment.id,
            status='pending_fulfillment',
            fulfillment_type='automated',
            passenger_email='test@webhook.com',
        )
        db.session.add(booking)
        db.session.commit()

        return {
            'user_id': user.id,
            'deal_id': deal.id,
            'booking_id': booking.id,
            'payment_id': payment.id,
            'email': 'test@webhook.com',
        }


# ============================================================
# WebhookEvent Model Tests
# ============================================================

class TestWebhookEvent:
    """Test WebhookEvent model for idempotency tracking."""

    def test_create_webhook_event(self, client):
        """Can create a WebhookEvent record."""
        with app.app_context():
            evt = WebhookEvent(
                event_id='evt_test_123',
                event_type='checkout.session.completed',
            )
            db.session.add(evt)
            db.session.commit()

            saved = WebhookEvent.query.filter_by(event_id='evt_test_123').first()
            assert saved is not None
            assert saved.event_type == 'checkout.session.completed'
            assert saved.processed_at is not None

    def test_duplicate_event_id_rejected(self, client):
        """Duplicate event_id violates unique constraint."""
        with app.app_context():
            evt1 = WebhookEvent(event_id='evt_dup_1', event_type='test')
            db.session.add(evt1)
            db.session.commit()

            evt2 = WebhookEvent(event_id='evt_dup_1', event_type='test')
            db.session.add(evt2)
            with pytest.raises(Exception):
                db.session.commit()
            db.session.rollback()

    def test_event_lookup_by_id(self, client):
        """Can look up webhook event by event_id."""
        with app.app_context():
            evt = WebhookEvent(event_id='evt_lookup_test', event_type='invoice.paid')
            db.session.add(evt)
            db.session.commit()

            found = WebhookEvent.query.filter_by(event_id='evt_lookup_test').first()
            assert found is not None

            not_found = WebhookEvent.query.filter_by(event_id='evt_nonexistent').first()
            assert not_found is None


# ============================================================
# Booking Status API Tests (existing /api/v1/booking route, enhanced Build #189)
# ============================================================

class TestBookingStatusAPI:
    """Test booking status endpoint."""

    def test_booking_status_authenticated(self, client, booking_fixtures):
        """Authenticated user can get their booking status."""
        booking_id = booking_fixtures['booking_id']

        client.post('/login', data={
            'email': 'test@webhook.com',
            'password': 'testpass123',
        })

        resp = client.get(f'/api/v1/booking/{booking_id}/status')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['status'] == 'pending_fulfillment'
        assert data['fulfillment_type'] == 'automated'
        assert data['booking_id'] == booking_id

    def test_booking_status_includes_enhanced_fields(self, client, booking_fixtures):
        """Build #189: status response includes passenger_email, deal_id, deal_type."""
        booking_id = booking_fixtures['booking_id']

        client.post('/login', data={
            'email': 'test@webhook.com',
            'password': 'testpass123',
        })

        resp = client.get(f'/api/v1/booking/{booking_id}/status')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'passenger_email' in data
        assert data['passenger_email'] == 'test@webhook.com'
        assert 'deal_id' in data
        assert data['deal_id'] == 'deal_webhook_test'
        assert 'deal_type' in data
        assert data['deal_type'] == 'flight'

    def test_booking_status_not_found(self, client):
        """Requesting non-existent booking returns 404."""
        resp = client.get('/api/v1/booking/99999/status')
        assert resp.status_code == 404

    def test_booking_status_unauthorized(self, client, booking_fixtures):
        """User cannot access another user's booking without session."""
        booking_id = booking_fixtures['booking_id']

        # No login, no session — should get 403
        resp = client.get(f'/api/v1/booking/{booking_id}/status')
        assert resp.status_code == 403
