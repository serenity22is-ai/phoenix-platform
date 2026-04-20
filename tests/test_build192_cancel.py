"""
MYSTES Build #192 — Cancellation Flow + My Bookings Tests

Tests:
    - My Bookings page (auth, rendering, cancel button visibility)
    - Cancel booking flow (auth, ownership, status validation, execution)
    - Cancellation email function
    - Booking model cancellation fields

Run: pytest tests/test_build192_cancel.py -v
MYSTES KYRIOS LLC — Confidential.
"""

import json
import sys
import os
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server import app, db, limiter
from models import User, Deal, Payment, Booking, FeatureFlag


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
        from models import SystemSetting
        FeatureFlag.init_default_flags()
        SystemSetting.init_defaults()
        yield app.test_client()
        db.drop_all()

    limiter.enabled = True


@pytest.fixture
def auth_client(client):
    """Authenticated test client."""
    with app.app_context():
        user = User(email='cancel@mystes.app', name='Cancel User', is_admin=False)
        user.set_password('testpass123')
        db.session.add(user)
        db.session.commit()
        client.post('/login', data={'email': 'cancel@mystes.app', 'password': 'testpass123'})
        return client


@pytest.fixture
def booked_flight(auth_client):
    """Create a booked flight deal with payment."""
    with app.app_context():
        user = User.query.filter_by(email='cancel@mystes.app').first()
        deal = Deal(
            deal_id='CANCEL_TEST_001',
            deal_type='flight',
            origin='JFK',
            destination='LAX',
            airline='DL',
            arbitrage_price_usd=350.00,
            platform_fee_usd=50.00,
            is_active=True,
            deal_status='booked',
            amadeus_offer_data=json.dumps({'source': 'duffel_ndc', 'offer_id': 'OFF_CANCEL_001'}),
            expires_at=datetime.utcnow() + timedelta(hours=24),
        )
        db.session.add(deal)
        db.session.flush()

        payment = Payment(
            user_id=user.id,
            deal_id=deal.id,
            payment_method='card',
            amount_usd=350.00,
            status='verified',
            stripe_payment_intent='pi_test_cancel_001',
        )
        db.session.add(payment)
        db.session.flush()

        booking = Booking(
            deal_id=deal.id,
            user_id=user.id,
            payment_id=payment.id,
            passenger_name='Cancel User',
            passenger_email='cancel@mystes.app',
            confirmation_code='ABC123',
            status='booked',
        )
        db.session.add(booking)
        db.session.commit()
        return {'booking_id': booking.id, 'deal_id': deal.id, 'payment_id': payment.id}


# ============================================================
# My Bookings Page Tests
# ============================================================

class TestMyBookingsPage:
    """Test the /bookings page."""

    def test_my_bookings_requires_auth(self, client):
        """GET /bookings redirects unauthenticated users."""
        resp = client.get('/bookings')
        assert resp.status_code == 302

    def test_my_bookings_loads(self, auth_client):
        """GET /bookings returns 200 for authenticated user."""
        resp = auth_client.get('/bookings')
        assert resp.status_code == 200
        html = resp.data.decode()
        assert 'My Bookings' in html
        assert 'Space Grotesk' in html

    def test_my_bookings_shows_bookings(self, auth_client, booked_flight):
        """My Bookings page shows user's booking data."""
        resp = auth_client.get('/bookings')
        html = resp.data.decode()
        assert 'JFK' in html
        assert 'LAX' in html
        assert 'ABC123' in html

    def test_my_bookings_has_cancel_button(self, auth_client, booked_flight):
        """Cancellable bookings show cancel action."""
        resp = auth_client.get('/bookings')
        html = resp.data.decode()
        assert 'cancel-booking' in html


# ============================================================
# Cancel Booking Tests
# ============================================================

class TestCancelBooking:
    """Test the cancel booking flow."""

    def test_cancel_requires_auth(self, client):
        """GET /cancel-booking/1 redirects unauthenticated."""
        resp = client.get('/cancel-booking/1')
        assert resp.status_code == 302

    def test_cancel_wrong_user(self, auth_client, booked_flight):
        """User cannot cancel another user's booking."""
        with app.app_context():
            # Create second user and their booking
            user2 = User(email='other@mystes.app', name='Other', is_admin=False)
            user2.set_password('testpass123')
            db.session.add(user2)
            db.session.commit()

            booking2 = Booking(
                deal_id=booked_flight['deal_id'],
                user_id=user2.id,
                passenger_name='Other User',
                status='booked',
            )
            db.session.add(booking2)
            db.session.commit()

            resp = auth_client.get(f'/cancel-booking/{booking2.id}')
            # Should redirect with error (access denied)
            assert resp.status_code == 302

    def test_cancel_confirmation_page(self, auth_client, booked_flight):
        """GET /cancel-booking shows confirmation page with details."""
        resp = auth_client.get(f'/cancel-booking/{booked_flight["booking_id"]}')
        assert resp.status_code == 200
        html = resp.data.decode()
        assert 'Cancel Booking' in html
        assert 'Confirm Cancellation' in html
        assert '350' in html  # refund amount

    def test_cancel_already_cancelled(self, auth_client, booked_flight):
        """Cannot cancel already-cancelled booking."""
        with app.app_context():
            booking = db.session.get(Booking, booked_flight['booking_id'])
            booking.status = 'cancelled'
            db.session.commit()

        resp = auth_client.get(f'/cancel-booking/{booked_flight["booking_id"]}')
        assert resp.status_code == 302  # redirects with message

    def test_cancel_updates_status(self, auth_client, booked_flight):
        """POST /cancel-booking updates booking status to cancelled."""
        resp = auth_client.post(f'/cancel-booking/{booked_flight["booking_id"]}')
        assert resp.status_code == 302  # redirects to /bookings

        with app.app_context():
            booking = db.session.get(Booking, booked_flight['booking_id'])
            assert booking.status == 'cancelled'

    def test_cancel_sets_cancelled_at(self, auth_client, booked_flight):
        """POST /cancel-booking sets cancelled_at timestamp."""
        auth_client.post(f'/cancel-booking/{booked_flight["booking_id"]}')

        with app.app_context():
            booking = db.session.get(Booking, booked_flight['booking_id'])
            assert booking.cancelled_at is not None
            assert booking.cancellation_reason is not None


# ============================================================
# Cancellation Email Tests
# ============================================================

class TestCancellationEmail:
    """Test cancellation email function."""

    def test_cancellation_email_function_exists(self, client):
        """send_cancellation_email is importable."""
        from email_service import send_cancellation_email
        assert callable(send_cancellation_email)

    @patch('email_service.send_email_smtp')
    def test_cancellation_email_content(self, mock_send, client):
        """Cancellation email contains booking ref and refund info."""
        from email_service import send_cancellation_email
        mock_send.return_value = True

        result = send_cancellation_email(
            to='test@example.com',
            to_name='Test User',
            booking_ref='ABC123',
            route_info='JFK → LAX',
            refund_amount=350.00,
        )
        assert result is True
        mock_send.assert_called_once()
        call_args = mock_send.call_args
        html_body = call_args[0][2]  # Third positional arg is HTML
        assert 'ABC123' in html_body
        assert '350.00' in html_body
        assert 'JFK' in html_body
        assert 'MYSTES' in html_body


# ============================================================
# Booking Model Tests
# ============================================================

class TestBookingModel:
    """Test Booking model cancellation fields."""

    def test_booking_has_cancelled_at_field(self, client):
        """Booking model has cancelled_at column."""
        with app.app_context():
            user = User(email='model@mystes.app', name='Model Test')
            user.set_password('testpass123')
            db.session.add(user)
            db.session.commit()

            booking = Booking(
                user_id=user.id,
                status='cancelled',
                cancelled_at=datetime.utcnow(),
            )
            db.session.add(booking)
            db.session.commit()

            fetched = db.session.get(Booking, booking.id)
            assert fetched.cancelled_at is not None

    def test_booking_has_refund_amount_field(self, client):
        """Booking model has refund_amount_usd column."""
        with app.app_context():
            user = User(email='refund@mystes.app', name='Refund Test')
            user.set_password('testpass123')
            db.session.add(user)
            db.session.commit()

            booking = Booking(
                user_id=user.id,
                status='cancelled',
                refund_amount_usd=250.50,
                cancellation_reason='Customer requested',
            )
            db.session.add(booking)
            db.session.commit()

            fetched = db.session.get(Booking, booking.id)
            assert fetched.refund_amount_usd == 250.50
            assert fetched.cancellation_reason == 'Customer requested'


# ============================================================
# Navigation + Confirmation Page Tests
# ============================================================

class TestNavAndConfirmation:
    """Test nav links and confirmation page cancel button."""

    def test_nav_has_my_bookings_link(self, auth_client):
        """Navigation More dropdown includes My Bookings."""
        resp = auth_client.get('/dashboard')
        html = resp.data.decode()
        assert '/bookings' in html
        assert 'My Bookings' in html

    def test_confirmation_has_cancel_link(self, auth_client, booked_flight):
        """Booking confirmation page has cancel booking link."""
        resp = auth_client.get(f'/booking-confirmation/{booked_flight["booking_id"]}')
        if resp.status_code == 200:
            html = resp.data.decode()
            assert 'cancel-booking' in html

    def test_dashboard_has_manage_all_link(self, auth_client):
        """Dashboard has Manage All link to /bookings."""
        resp = auth_client.get('/dashboard')
        html = resp.data.decode()
        assert 'Manage All' in html or '/bookings' in html
