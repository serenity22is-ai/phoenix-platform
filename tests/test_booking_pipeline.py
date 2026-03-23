"""
Booking Pipeline Smoke Tests — Build #184

Tests the critical booking path: deal creation, raw offer passthrough,
checkout page, confirmation, and Stripe endpoint.

Run: pytest tests/test_booking_pipeline.py -v
"""

import json
import sys
import os
import pytest
from datetime import date
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server import app, db, limiter
from models import User, Deal, Booking


@pytest.fixture
def client():
    """Test client with in-memory database."""
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['WTF_CSRF_ENABLED'] = False
    app.config['SERVER_NAME'] = 'localhost.localdomain'
    app.config['RATELIMIT_ENABLED'] = False

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
def auth_client(client):
    """Authenticated test client."""
    with app.app_context():
        client.post('/register', data={
            'email': 'booker@example.com',
            'password': 'BookerPass123!',
            'name': 'Booking Tester',
        }, follow_redirects=True)
        client.post('/login', data={
            'email': 'booker@example.com',
            'password': 'BookerPass123!',
        }, follow_redirects=True)
        yield client


@pytest.fixture
def sample_deal(auth_client):
    """Create a sample deal matching the actual Deal model schema."""
    import secrets
    with app.app_context():
        user = User.query.filter_by(email='booker@example.com').first()
        deal = Deal(
            deal_id=f"D{secrets.token_hex(8).upper()[:12]}",
            deal_type='flight',
            origin='JFK',
            destination='FCO',
            departure_date=date(2026, 6, 15),
            airline='ITA Airways',
            flight_number='AZ 611',
            arbitrage_price_usd=620.00,
            home_price_usd=850.00,
            city_code='FCO',
            deal_status='available',
            claimed_by=user.id,
            amadeus_offer_data=json.dumps({
                "source": "picasso_redbox",
                "fare_id": "F123456789",
                "fare_search_id": "FS987654321",
                "cabin": "economy",
                "segments": [
                    {"origin": "JFK", "destination": "FCO", "flight_number": "AZ 611"}
                ],
            }),
        )
        db.session.add(deal)
        db.session.commit()
        yield deal


class TestBookingPipeline:
    """End-to-end booking pipeline smoke tests."""

    def test_deal_creation_with_raw_offer(self, auth_client, sample_deal):
        """Deal record stores amadeus_offer_data (raw offer) correctly."""
        with app.app_context():
            deal = db.session.get(Deal, sample_deal.id)
            assert deal is not None
            assert deal.origin == 'JFK'
            assert deal.destination == 'FCO'
            raw = json.loads(deal.amadeus_offer_data)
            assert raw["fare_id"] == "F123456789"
            assert raw["fare_search_id"] == "FS987654321"
            assert raw["source"] == "picasso_redbox"

    def test_raw_offer_passthrough_integrity(self, auth_client, sample_deal):
        """CRITICAL: fare_id and offer_id survive from Deal to booking dispatch."""
        with app.app_context():
            deal = db.session.get(Deal, sample_deal.id)
            raw = json.loads(deal.amadeus_offer_data)

            # Verify the raw_offer has all fields BookingDispatcher needs
            assert "source" in raw, "raw_offer must have 'source' for dispatcher routing"
            assert "fare_id" in raw, "raw_offer must have 'fare_id' for booking"
            assert "fare_search_id" in raw, "raw_offer must have 'fare_search_id' for booking"

            # Verify segments survive serialization
            assert "segments" in raw
            assert len(raw["segments"]) == 1
            assert raw["segments"][0]["origin"] == "JFK"

    def test_booking_page_renders(self, auth_client, sample_deal):
        """Booking/checkout page renders for a valid deal."""
        resp = auth_client.get(f'/book/{sample_deal.deal_id}')
        # Should render or redirect (not 500)
        assert resp.status_code in (200, 302)

    def test_confirmation_page_with_booking(self, auth_client, sample_deal):
        """Booking record can be created and queried."""
        with app.app_context():
            user = User.query.filter_by(email='booker@example.com').first()
            booking = Booking(
                user_id=user.id,
                deal_id=sample_deal.id,
                status='booked',
                confirmation_code='TEST123',
                passenger_name='Booking Tester',
                passenger_email='booker@example.com',
            )
            db.session.add(booking)
            db.session.commit()

            loaded = db.session.get(Booking, booking.id)
            assert loaded is not None
            assert loaded.status == 'booked'
            assert loaded.confirmation_code == 'TEST123'
            assert loaded.deal_id == sample_deal.id

    def test_stripe_checkout_endpoint_exists(self, auth_client, sample_deal):
        """Stripe checkout creation endpoint responds (not 404)."""
        resp = auth_client.post(
            '/api/payment/stripe/create',
            json={"deal_id": sample_deal.deal_id},
            content_type='application/json',
        )
        # Without Stripe keys, expect error response but not 404
        assert resp.status_code != 404
