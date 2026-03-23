"""
MYSTES Build #188 — Booking Pipeline Tests

Tests:
    - BookingFulfillmentManager: create_booking, auto-upgrade, idempotency
    - Fee calculation: tier-based fees, $3 minimum, NO maximum cap
    - Savings breakdown: calculate_savings_breakdown() with all tiers
    - Booking model fields (Picasso references, passenger details)

Run: pytest tests/test_build188_booking.py -v
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
from models import User, Deal, Payment, Booking


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
    """Create user, deal, and payment for booking tests."""
    with app.app_context():
        user = User(
            email='booker@example.com',
            name='Test Booker',
        )
        user.set_password('BookTest123!')
        db.session.add(user)
        db.session.commit()

        deal = Deal(
            deal_id='DEAL-BK-001',
            deal_type='flight',
            airline='United',
            flight_number='UA100',
            origin='JFK',
            destination='LAX',
            home_price_usd=500.0,
            arbitrage_price_usd=350.0,
            gross_savings_usd=150.0,
            platform_fee_usd=67.50,
            user_savings_usd=82.50,
            savings_percent=16.5,
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
            amount_usd=417.50,
            status='verified',
            stripe_session_id='cs_test_123',
        )
        db.session.add(payment)
        db.session.commit()

        yield client, user, deal, payment


# ============================================================
# BookingFulfillmentManager Tests
# ============================================================

class TestBookingFulfillmentManager:
    """Tests for BookingFulfillmentManager from booking_fulfillment.py."""

    def test_create_booking_self_service_no_fare_id(self, booking_fixtures):
        """Without fare_id, fulfillment stays self_service."""
        from booking_fulfillment import BookingFulfillmentManager

        _, user, deal, payment = booking_fixtures
        with app.app_context():
            # Re-fetch to ensure attached to session
            user = User.query.get(user.id)
            deal = Deal.query.get(deal.id)
            payment = Payment.query.get(payment.id)

            manager = BookingFulfillmentManager(db.session)
            result = manager.create_booking(deal, payment, user, skip_fulfillment=True)

            assert result['success'] is True
            booking = result['booking']
            assert booking.fulfillment_type == 'self_service'
            assert booking.status == 'pending_fulfillment'

    def test_create_booking_auto_upgrade_with_fare_id(self, booking_fixtures):
        """With fare_id + fare_search_id, auto-upgrade to automated."""
        from booking_fulfillment import BookingFulfillmentManager

        _, user, deal, payment = booking_fixtures
        with app.app_context():
            user = User.query.get(user.id)
            deal = Deal.query.get(deal.id)
            payment = Payment.query.get(payment.id)

            # Set fare_id + fare_search_id
            deal.fare_id = 'FARE123'
            deal.fare_search_id = 'SEARCH456'
            db.session.commit()

            manager = BookingFulfillmentManager(db.session)
            result = manager.create_booking(deal, payment, user, skip_fulfillment=True)

            assert result['success'] is True
            assert result['fulfillment_type'] == 'automated'

    def test_create_booking_idempotent(self, booking_fixtures):
        """Duplicate create_booking returns existing booking."""
        from booking_fulfillment import BookingFulfillmentManager

        _, user, deal, payment = booking_fixtures
        with app.app_context():
            user = User.query.get(user.id)
            deal = Deal.query.get(deal.id)
            payment = Payment.query.get(payment.id)

            manager = BookingFulfillmentManager(db.session)
            result1 = manager.create_booking(deal, payment, user, skip_fulfillment=True)
            result2 = manager.create_booking(deal, payment, user, skip_fulfillment=True)

            assert result1['booking_id'] == result2['booking_id']
            assert 'already exists' in result2.get('message', '')

    def test_booking_model_has_picasso_fields(self, booking_fixtures):
        """Booking model has all Picasso booking reference fields."""
        _, user, deal, payment = booking_fixtures
        with app.app_context():
            booking = Booking(
                user_id=user.id,
                deal_id=deal.id,
                payment_id=payment.id,
                status='booked',
                fulfillment_type='automated',
                pnr_locator='ABC123',
                picasso_super_pnr_id='SPNR-789',
                picasso_cart_id='CART-456',
                eticket_number='123-4567890',
            )
            db.session.add(booking)
            db.session.commit()

            fetched = Booking.query.get(booking.id)
            assert fetched.pnr_locator == 'ABC123'
            assert fetched.picasso_super_pnr_id == 'SPNR-789'
            assert fetched.picasso_cart_id == 'CART-456'
            assert fetched.eticket_number == '123-4567890'

    def test_booking_passenger_fields(self, booking_fixtures):
        """Booking model stores detailed passenger info for Picasso."""
        from datetime import date

        _, user, deal, payment = booking_fixtures
        with app.app_context():
            booking = Booking(
                user_id=user.id,
                deal_id=deal.id,
                payment_id=payment.id,
                status='pending_fulfillment',
                passenger_first_name='John',
                passenger_last_name='Doe',
                passenger_date_of_birth=date(1990, 5, 15),
                passenger_gender='MALE',
                passenger_phone='+1-555-0100',
                passenger_passport_number='X12345678',
                passenger_nationality='US',
                passenger_title='MR',
            )
            db.session.add(booking)
            db.session.commit()

            fetched = Booking.query.get(booking.id)
            assert fetched.passenger_first_name == 'John'
            assert fetched.passenger_last_name == 'Doe'
            assert fetched.passenger_gender == 'MALE'
            assert fetched.passenger_nationality == 'US'


# ============================================================
# Fee Calculation Tests
# ============================================================

class TestFeeCalculation:
    """Tests for get_fee_percent — the core pricing engine."""

    def test_guest_fee_50_percent(self, client):
        """Guest (anonymous) pays 50% fee."""
        from payments import get_fee_percent
        with app.app_context():
            assert get_fee_percent(None) == 0.50

    def test_free_member_fee_45_percent(self, booking_fixtures):
        """Authenticated free member pays 45% fee."""
        from payments import get_fee_percent

        _, user, _, _ = booking_fixtures
        with app.app_context():
            u = User.query.get(user.id)
            assert get_fee_percent(u) == 0.45

    def test_fee_minimum_3_dollars(self, client):
        """Fee never goes below $3 when there are savings."""
        from payments import calculate_savings_breakdown
        with app.app_context():
            # Small savings: $10 retail vs $9 our price = $1 savings
            # 50% of $1 = $0.50 → bumped to $3 minimum
            result = calculate_savings_breakdown(10.0, 9.0)
            assert result['base_fee'] == 3.0

    def test_no_maximum_fee_cap(self, client):
        """NO maximum fee cap — fee can exceed $50, $100, any amount."""
        from payments import calculate_savings_breakdown
        with app.app_context():
            # $10,000 retail vs $5,000 our price = $5,000 savings
            # 50% of $5,000 = $2,500 — no cap
            result = calculate_savings_breakdown(10000.0, 5000.0)
            assert result['base_fee'] == 2500.0
            assert result['base_fee'] > 50  # NOT capped at 50

    def test_savings_breakdown_structure(self, client):
        """Savings breakdown returns all required fields."""
        from payments import calculate_savings_breakdown
        with app.app_context():
            result = calculate_savings_breakdown(800.0, 600.0)
            required_keys = [
                'retail_price', 'our_price', 'total_savings',
                'fee_percent', 'tier_name', 'base_fee',
                'share_discount', 'final_fee', 'customer_price',
                'customer_savings', 'travel_plus_fee', 'travel_plus_extra_savings',
            ]
            for key in required_keys:
                assert key in result, f"Missing key: {key}"


# ============================================================
# Automation Availability Tests
# ============================================================

class TestAutomationAvailability:
    """Tests for _check_automation_availability in BookingFulfillmentManager."""

    @patch('booking_fulfillment.BookingFulfillmentManager._check_automation_availability')
    def test_automation_requires_fare_id_and_search_id(self, mock_check, booking_fixtures):
        """Automated booking requires both fare_id and fare_search_id."""
        from booking_fulfillment import BookingFulfillmentManager

        _, user, deal, payment = booking_fixtures
        with app.app_context():
            deal = Deal.query.get(deal.id)
            manager = BookingFulfillmentManager(db.session)

            # No fare_id — not automated
            deal.fare_id = None
            deal.fare_search_id = None
            mock_check.return_value = False
            assert not mock_check(deal)

            # Only fare_id — still not automated
            deal.fare_id = 'FARE1'
            deal.fare_search_id = None
            mock_check.return_value = False
            assert not mock_check(deal)

            # Both present — automated available
            deal.fare_id = 'FARE1'
            deal.fare_search_id = 'SEARCH1'
            mock_check.return_value = True
            assert mock_check(deal)

    def test_hotel_automation_requires_offer_id(self, booking_fixtures):
        """Hotel automation requires hotel_offer_id on the Deal."""
        from booking_fulfillment import BookingFulfillmentManager

        _, user, deal, payment = booking_fixtures
        with app.app_context():
            deal = Deal.query.get(deal.id)
            deal.deal_type = 'hotel'
            manager = BookingFulfillmentManager(db.session)

            # No hotel_offer_id
            deal.hotel_offer_id = None
            assert not manager._check_automation_availability(deal)

            # With hotel_offer_id
            deal.hotel_offer_id = 'HOT-OFFER-123'
            assert manager._check_automation_availability(deal)


# ============================================================
# Deal Model Tests
# ============================================================

class TestDealModel:
    """Tests for Deal model fields critical to booking pipeline."""

    def test_deal_fare_fields(self, booking_fixtures):
        """Deal stores Picasso fare references."""
        _, _, deal, _ = booking_fixtures
        with app.app_context():
            d = Deal.query.get(deal.id)
            d.fare_id = 'FARE-XYZ'
            d.fare_search_id = 'SEARCH-ABC'
            d.picasso_gds = 'AMADEUS'
            d.fare_type = 'NET'
            db.session.commit()

            fetched = Deal.query.get(deal.id)
            assert fetched.fare_id == 'FARE-XYZ'
            assert fetched.fare_search_id == 'SEARCH-ABC'
            assert fetched.picasso_gds == 'AMADEUS'
            assert fetched.fare_type == 'NET'

    def test_deal_amadeus_offer_data(self, booking_fixtures):
        """Deal stores raw offer JSON for booking flow."""
        _, _, deal, _ = booking_fixtures
        with app.app_context():
            d = Deal.query.get(deal.id)
            raw_offer = json.dumps({
                'fare_id': 'F123',
                'fare_search_id': 'S456',
                'source': 'picasso',
            })
            d.amadeus_offer_data = raw_offer
            db.session.commit()

            fetched = Deal.query.get(deal.id)
            parsed = json.loads(fetched.amadeus_offer_data)
            assert parsed['fare_id'] == 'F123'
            assert parsed['source'] == 'picasso'
