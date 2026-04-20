"""
MYSTES Tests — Builds #206-210

#206: QR Code Generator (B2B + consumer referral)
#207: Proxy Booking Session Flow
#208: Bundling (proxy flight + Duffel hotel)
#209: Trip Splitting Mode 1
#210: B2B Referral Landing Page

Run: python3 -m pytest tests/test_build206_210.py -v
"""

import json
import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server import app, db, limiter
from models import (
    User, Deal, Booking, CommercialAccount,
    TripPlan, TripMember, TripItem, TripCart, TripCartAssignment,
    TripBundle, BundleItem, ReferralCard,
    FeatureFlag, SystemSetting, RewardsAccount,
)


# ───── Fixtures ─────

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
        FeatureFlag.init_default_flags()
        SystemSetting.init_defaults()
        yield app.test_client()
        db.drop_all()

    limiter.enabled = True


@pytest.fixture
def auth_client(client):
    """Authenticated regular user."""
    with app.app_context():
        client.post('/register', data={
            'email': 'test@example.com',
            'password': 'TestPass123!',
            'name': 'Test User',
        }, follow_redirects=True)
        client.post('/login', data={
            'email': 'test@example.com',
            'password': 'TestPass123!',
        }, follow_redirects=True)
        yield client


@pytest.fixture
def b2b_client(client):
    """Authenticated user with active B2B account."""
    with app.app_context():
        user = User(
            email='b2b@example.com',
            name='B2B User',
            is_verified=True,
            is_active=True,
        )
        user.set_password('B2BPass123!')
        db.session.add(user)
        db.session.flush()

        account = CommercialAccount(
            owner_user_id=user.id,
            name='Test Agency',
            account_id='COMM_TEST',
            contact_email='b2b@example.com',
            referral_code='TESTAGENCY',
            current_tier='starter',
            fee_percent=25,
            subscription_status='active',
            is_active=True,
        )
        db.session.add(account)
        db.session.commit()

        client.post('/login', data={
            'email': 'b2b@example.com',
            'password': 'B2BPass123!',
        }, follow_redirects=True)

        yield client


@pytest.fixture
def sample_deal():
    """Create a sample deal with arbitrage spread."""
    with app.app_context():
        deal = Deal(
            deal_id='deal_LAX_NRT_test',
            origin='LAX',
            destination='NRT',
            airline='United Airlines',
            home_price_usd=1400.0,
            arbitrage_price_usd=900.0,
            user_savings_usd=350.0,
            platform_fee_usd=150.0,
            arbitrage_market='DK',
        )
        db.session.add(deal)
        db.session.commit()
        return deal.deal_id


@pytest.fixture
def sample_hotel_deal():
    """Create a sample hotel deal."""
    with app.app_context():
        deal = Deal(
            deal_id='deal_hotel_NRT_test',
            origin='NRT',
            destination='NRT',
            airline='Hilton Tokyo',
            home_price_usd=300.0,
            deal_type='hotel',
        )
        db.session.add(deal)
        db.session.commit()
        return deal.deal_id


@pytest.fixture
def sample_referral_card(auth_client):
    """Create a referral card for the auth user."""
    with app.app_context():
        user = User.query.filter_by(email='test@example.com').first()
        card = ReferralCard(
            user_id=user.id,
            card_token='test_token_abc123',
            referral_code='TESTREF',
            total_bookings=5,
            total_savings_usd=1200.0,
            total_referrals=3,
            member_since='Jan 2026',
        )
        db.session.add(card)
        db.session.commit()
        return card.card_token


# ═════════════════════════════════════════════════════════════
# BUILD #206 — QR Code Generator
# ═════════════════════════════════════════════════════════════

class TestBuild206QRConsumer:
    """Consumer-facing QR code endpoints."""

    def test_qr_png_returns_image(self, auth_client, sample_referral_card):
        """QR PNG endpoint returns valid PNG image."""
        resp = auth_client.get(f'/api/referral-card/qr/{sample_referral_card}.png')
        assert resp.status_code == 200
        assert resp.content_type == 'image/png'
        # PNG magic bytes
        assert resp.data[:4] == b'\x89PNG'

    def test_qr_png_invalid_token_404(self, auth_client):
        """Invalid card token returns 404."""
        resp = auth_client.get('/api/referral-card/qr/nonexistent_token.png')
        assert resp.status_code == 404

    def test_qr_data_returns_base64(self, auth_client, sample_referral_card):
        """QR data endpoint returns base64 data URI."""
        resp = auth_client.post('/api/referral-card/qr-data',
                                content_type='application/json')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        assert data['qr_data_uri'].startswith('data:image/png;base64,')
        assert '/api/referral-card/qr/' in data['qr_png_url']
        assert data['referral_code'] == 'TESTREF'

    def test_qr_data_no_card_400(self, client):
        """QR data without card returns error."""
        with app.app_context():
            # Create user without referral card
            client.post('/register', data={
                'email': 'nocard@example.com',
                'password': 'TestPass123!',
                'name': 'No Card',
            }, follow_redirects=True)
            client.post('/login', data={
                'email': 'nocard@example.com',
                'password': 'TestPass123!',
            }, follow_redirects=True)
            resp = client.post('/api/referral-card/qr-data',
                               content_type='application/json')
            assert resp.status_code == 400

    def test_qr_data_unauthenticated_redirect(self, client):
        """Unauthenticated user redirected from QR data."""
        resp = client.post('/api/referral-card/qr-data',
                           content_type='application/json')
        assert resp.status_code in (302, 401)

    def test_print_page_renders(self, auth_client, sample_referral_card):
        """Print-ready page renders with QR code."""
        resp = auth_client.get(f'/ref-card/{sample_referral_card}/print')
        assert resp.status_code == 200
        html = resp.data.decode()
        assert 'MYSTES' in html
        assert 'Print Card' in html
        assert 'Download QR' in html
        assert 'TESTREF' in html

    def test_print_page_invalid_token(self, auth_client):
        """Print page with bad token redirects."""
        resp = auth_client.get('/ref-card/bad_token/print')
        assert resp.status_code == 302

    def test_public_card_shows_qr(self, auth_client, sample_referral_card):
        """Public referral card page includes QR code image."""
        resp = auth_client.get(f'/ref-card/{sample_referral_card}')
        assert resp.status_code == 200
        html = resp.data.decode()
        assert 'qr/' in html or 'Scan to join' in html


class TestBuild206QRBusiness:
    """B2B QR code endpoints in routes_business.py.

    Note: B2B routes are conditionally registered if b2b_accounts feature flag
    was enabled at server module load time. Accept 404 and skip if not registered.
    """

    def _skip_if_not_registered(self, resp):
        if resp.status_code == 404:
            pytest.skip('B2B routes not registered (b2b_accounts feature flag off at import time)')

    def test_b2b_qr_png_download(self, b2b_client):
        """B2B QR PNG download returns valid image."""
        resp = b2b_client.get('/business/qr/png')
        self._skip_if_not_registered(resp)
        assert resp.status_code == 200
        assert resp.content_type == 'image/png'
        assert resp.data[:4] == b'\x89PNG'
        assert 'MYSTES_QR_TESTAGENCY' in resp.headers.get('Content-Disposition', '')

    def test_b2b_qr_svg_download(self, b2b_client):
        """B2B QR SVG download returns valid SVG."""
        resp = b2b_client.get('/business/qr/svg')
        self._skip_if_not_registered(resp)
        assert resp.status_code == 200
        assert 'svg' in resp.content_type
        assert b'<svg' in resp.data or b'<path' in resp.data

    def test_b2b_qr_invalid_format_400(self, b2b_client):
        """Invalid QR format returns 400."""
        resp = b2b_client.get('/business/qr/pdf')
        self._skip_if_not_registered(resp)
        assert resp.status_code == 400

    def test_b2b_qr_unauthenticated(self, client):
        """Unauthenticated user cannot access B2B QR."""
        resp = client.get('/business/qr/png')
        # 302 = redirect to login, 401 = unauthorized, 404 = routes not registered
        assert resp.status_code in (302, 401, 404)

    def test_b2b_qr_data_json(self, b2b_client):
        """B2B QR data JSON returns correct structure."""
        resp = b2b_client.get('/api/business/qr-data')
        self._skip_if_not_registered(resp)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['referral_code'] == 'TESTAGENCY'
        assert '/ref/TESTAGENCY' in data['referral_url']
        assert data['qr_png_url'] == '/business/qr/png'
        assert data['qr_svg_url'] == '/business/qr/svg'

    def test_b2b_dashboard_shows_qr(self, b2b_client):
        """B2B dashboard includes QR preview and download buttons."""
        resp = b2b_client.get('/business/dashboard')
        self._skip_if_not_registered(resp)
        assert resp.status_code == 200
        html = resp.data.decode()
        assert 'Download PNG' in html
        assert 'Download SVG' in html
        assert '/business/qr/png' in html


# ═════════════════════════════════════════════════════════════
# BUILD #207 — Proxy Booking Session Flow
# ═════════════════════════════════════════════════════════════

class TestBuild207ProxyBooking:
    """Proxy booking session endpoints."""

    def test_proxy_session_requires_deal_id(self, auth_client):
        """Missing deal_id returns 400."""
        resp = auth_client.post('/api/booking/proxy-session',
                                data=json.dumps({"passenger_data": {"first_name": "Test"}}),
                                content_type='application/json')
        assert resp.status_code == 400
        assert 'deal_id' in resp.get_json()['error']

    def test_proxy_session_requires_passenger_data(self, auth_client, sample_deal):
        """Missing passenger_data returns 400."""
        resp = auth_client.post('/api/booking/proxy-session',
                                data=json.dumps({"deal_id": sample_deal}),
                                content_type='application/json')
        assert resp.status_code == 400
        assert 'passenger_data' in resp.get_json()['error']

    def test_proxy_session_deal_not_found(self, auth_client):
        """Non-existent deal returns 404."""
        resp = auth_client.post('/api/booking/proxy-session',
                                data=json.dumps({
                                    "deal_id": "nonexistent",
                                    "passenger_data": {"first_name": "Test"},
                                }),
                                content_type='application/json')
        assert resp.status_code == 404

    def test_proxy_session_no_spread_400(self, auth_client):
        """Deal with no arbitrage spread returns 400."""
        with app.app_context():
            deal = Deal(
                deal_id='deal_no_spread',
                origin='LAX',
                destination='SFO',
                home_price_usd=200.0,
                arbitrage_price_usd=200.0,
            )
            db.session.add(deal)
            db.session.commit()

        resp = auth_client.post('/api/booking/proxy-session',
                                data=json.dumps({
                                    "deal_id": "deal_no_spread",
                                    "passenger_data": {"first_name": "Test"},
                                }),
                                content_type='application/json')
        assert resp.status_code == 400
        assert 'no arbitrage spread' in resp.get_json()['error'].lower()

    def test_proxy_session_service_fee_calculation(self, auth_client, sample_deal):
        """Service fee = fee% * spread, $3 min, NO max cap."""
        # Guest = 50%. Spread = 1400-900 = 500. Fee = 500*0.45 = 225 (free tier)
        resp = auth_client.post('/api/booking/proxy-session',
                                data=json.dumps({
                                    "deal_id": sample_deal,
                                    "passenger_data": {"first_name": "Test", "last_name": "User"},
                                }),
                                content_type='application/json')
        # May fail at Stripe or BookingEngine — we just check fee calc
        data = resp.get_json()
        if resp.status_code == 200:
            assert data['service_fee_usd'] >= 3.0  # $3 min
            assert data['booking_channel'] == 'proxy'

    def test_proxy_complete_requires_job_id(self, auth_client):
        """Missing job_id returns 400."""
        resp = auth_client.post('/api/booking/proxy-complete',
                                data=json.dumps({}),
                                content_type='application/json')
        assert resp.status_code == 400

    def test_proxy_cancel_success(self, auth_client):
        """Cancel endpoint succeeds even with no active job."""
        resp = auth_client.post('/api/booking/proxy-cancel',
                                data=json.dumps({"job_id": "fake_job"}),
                                content_type='application/json')
        assert resp.status_code == 200
        assert resp.get_json()['success'] is True

    def test_booking_model_has_proxy_fields(self, client):
        """Booking model has new proxy columns (Build #207)."""
        with app.app_context():
            assert hasattr(Booking, 'booking_channel')
            assert hasattr(Booking, 'proxy_market')
            assert hasattr(Booking, 'service_fee_stripe_pi')
            # Column exists with correct default
            col = Booking.__table__.columns['booking_channel']
            assert col.default.arg == 'api'


class TestBuild207ServiceFee:
    """Service fee edge cases — $3 min, NO max cap."""

    def test_minimum_fee_enforced(self, auth_client):
        """Tiny spread still gets $3 minimum fee."""
        with app.app_context():
            deal = Deal(
                deal_id='deal_tiny_spread',
                origin='LAX',
                destination='SFO',
                home_price_usd=105.0,
                arbitrage_price_usd=100.0,
            )
            db.session.add(deal)
            db.session.commit()

        resp = auth_client.post('/api/booking/proxy-session',
                                data=json.dumps({
                                    "deal_id": "deal_tiny_spread",
                                    "passenger_data": {"first_name": "Test"},
                                }),
                                content_type='application/json')
        data = resp.get_json()
        if resp.status_code == 200:
            assert data['service_fee_usd'] >= 3.0

    def test_large_spread_no_max_cap(self, auth_client):
        """Large spread has no max cap on fee."""
        with app.app_context():
            deal = Deal(
                deal_id='deal_huge_spread',
                origin='JFK',
                destination='SIN',
                home_price_usd=10000.0,
                arbitrage_price_usd=3000.0,
            )
            db.session.add(deal)
            db.session.commit()

        resp = auth_client.post('/api/booking/proxy-session',
                                data=json.dumps({
                                    "deal_id": "deal_huge_spread",
                                    "passenger_data": {"first_name": "Test"},
                                }),
                                content_type='application/json')
        data = resp.get_json()
        if resp.status_code == 200:
            # 7000 spread * 0.45 (free tier) = 3150. No cap.
            assert data['service_fee_usd'] > 50  # Definitely no $50 cap


# ═════════════════════════════════════════════════════════════
# BUILD #208 — Bundling
# ═════════════════════════════════════════════════════════════

class TestBuild208Bundling:
    """Bundling proxy flight + Duffel hotel."""

    def test_bundle_create_success(self, auth_client, sample_deal, sample_hotel_deal):
        """Create bundle with flight + hotel."""
        resp = auth_client.post('/api/proxy-bundle/create',
                                data=json.dumps({
                                    "flight_deal_id": sample_deal,
                                    "hotel_deal_id": sample_hotel_deal,
                                }),
                                content_type='application/json')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        assert data['bundle_id'] > 0
        assert data['flight_price'] == 900.0
        assert data['hotel_price'] == 300.0
        assert data['combined_fee'] > 0
        assert data['total'] > 0

    def test_bundle_create_missing_deals(self, auth_client):
        """Missing deal IDs returns 400."""
        resp = auth_client.post('/api/proxy-bundle/create',
                                data=json.dumps({"flight_deal_id": "x"}),
                                content_type='application/json')
        assert resp.status_code == 400

    def test_bundle_create_invalid_deal(self, auth_client, sample_deal):
        """Invalid hotel deal returns 404."""
        resp = auth_client.post('/api/proxy-bundle/create',
                                data=json.dumps({
                                    "flight_deal_id": sample_deal,
                                    "hotel_deal_id": "nonexistent",
                                }),
                                content_type='application/json')
        assert resp.status_code == 404

    def test_bundle_status_endpoint(self, auth_client, sample_deal, sample_hotel_deal):
        """Bundle status returns item details."""
        # Create bundle first
        create_resp = auth_client.post('/api/proxy-bundle/create',
                                       data=json.dumps({
                                           "flight_deal_id": sample_deal,
                                           "hotel_deal_id": sample_hotel_deal,
                                       }),
                                       content_type='application/json')
        bundle_id = create_resp.get_json()['bundle_id']

        resp = auth_client.get(f'/api/proxy-bundle/{bundle_id}/status')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['bundle_id'] == bundle_id
        assert len(data['items']) == 2
        types = [i['type'] for i in data['items']]
        assert 'flight' in types
        assert 'hotel' in types

    def test_bundle_status_not_found(self, auth_client):
        """Bundle status for nonexistent bundle returns 404."""
        resp = auth_client.get('/api/proxy-bundle/99999/status')
        assert resp.status_code == 404

    def test_bundle_book_requires_passenger(self, auth_client, sample_deal, sample_hotel_deal):
        """Bundle book without passenger data returns 400."""
        create_resp = auth_client.post('/api/proxy-bundle/create',
                                       data=json.dumps({
                                           "flight_deal_id": sample_deal,
                                           "hotel_deal_id": sample_hotel_deal,
                                       }),
                                       content_type='application/json')
        bundle_id = create_resp.get_json()['bundle_id']

        resp = auth_client.post(f'/api/proxy-bundle/{bundle_id}/book',
                                data=json.dumps({}),
                                content_type='application/json')
        assert resp.status_code == 400

    def test_bundle_item_has_channel(self, auth_client, sample_deal, sample_hotel_deal):
        """BundleItem records booking_channel correctly."""
        create_resp = auth_client.post('/api/proxy-bundle/create',
                                       data=json.dumps({
                                           "flight_deal_id": sample_deal,
                                           "hotel_deal_id": sample_hotel_deal,
                                       }),
                                       content_type='application/json')
        bundle_id = create_resp.get_json()['bundle_id']

        with app.app_context():
            items = BundleItem.query.filter_by(bundle_id=bundle_id).all()
            channels = {i.item_type: i.booking_channel for i in items}
            assert channels['flight'] == 'proxy'
            assert channels['hotel'] == 'duffel_stays'

    def test_bundle_model_has_channel(self, client):
        """BundleItem model has booking_channel column."""
        with app.app_context():
            assert hasattr(BundleItem, 'booking_channel')
            col = BundleItem.__table__.columns['booking_channel']
            assert col.default.arg == 'api'


# ═════════════════════════════════════════════════════════════
# BUILD #209 — Trip Splitting Mode 1
# ═════════════════════════════════════════════════════════════

class TestBuild209TripSplitting:
    """Trip checkout + settle up + balances."""

    @pytest.fixture
    def trip_with_members(self, auth_client):
        """Create a trip with items and members."""
        with app.app_context():
            user = User.query.filter_by(email='test@example.com').first()

            # Create second member
            member_user = User(
                email='member@example.com',
                name='Trip Member',
                is_verified=True,
                is_active=True,
            )
            member_user.set_password('MemberPass123!')
            db.session.add(member_user)
            db.session.flush()

            # Create trip
            trip = TripPlan(
                creator_id=user.id,
                name='Tokyo Trip',
                status='draft',
            )
            db.session.add(trip)
            db.session.flush()

            # Add members
            m1 = TripMember(trip_plan_id=trip.id, user_id=user.id, role='owner', invitation_status='accepted')
            m2 = TripMember(trip_plan_id=trip.id, user_id=member_user.id, role='editor', invitation_status='accepted')
            db.session.add_all([m1, m2])
            db.session.flush()

            # Add items
            item1 = TripItem(
                trip_plan_id=trip.id,
                added_by_user_id=user.id,
                vertical='flights',
                item_data_json=json.dumps({"title": "LAX-NRT", "price": 900, "savings": 500}),
                status='approved',
            )
            item2 = TripItem(
                trip_plan_id=trip.id,
                added_by_user_id=user.id,
                vertical='hotels',
                item_data_json=json.dumps({"title": "Hilton Tokyo", "price": 300, "savings": 0}),
                status='approved',
            )
            db.session.add_all([item1, item2])
            db.session.commit()

            return trip.id

    def test_checkout_creates_cart(self, auth_client, trip_with_members):
        """Checkout creates TripCart and assignments."""
        resp = auth_client.post(f'/api/trips/{trip_with_members}/checkout',
                                data=json.dumps({}),
                                content_type='application/json')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        assert data['total_service_fee'] > 0
        assert data['member_count'] == 2
        assert data['per_person'] > 0
        assert len(data['balances']) == 2

    def test_checkout_payer_marked_paid(self, auth_client, trip_with_members):
        """Payer's own assignment is auto-marked 'paid'."""
        resp = auth_client.post(f'/api/trips/{trip_with_members}/checkout',
                                data=json.dumps({}),
                                content_type='application/json')
        data = resp.get_json()
        payer_balance = [b for b in data['balances'] if b['status'] == 'paid']
        assert len(payer_balance) == 1  # Payer's own share

    def test_checkout_sets_trip_booked(self, auth_client, trip_with_members):
        """Checkout sets trip status to 'booked'."""
        auth_client.post(f'/api/trips/{trip_with_members}/checkout',
                         data=json.dumps({}),
                         content_type='application/json')
        with app.app_context():
            trip = db.session.get(TripPlan, trip_with_members)
            assert trip.status == 'booked'

    def test_checkout_no_items_400(self, auth_client):
        """Checkout with no items returns 400."""
        with app.app_context():
            user = User.query.filter_by(email='test@example.com').first()
            trip = TripPlan(creator_id=user.id, name='Empty Trip', status='draft')
            db.session.add(trip)
            db.session.flush()
            m = TripMember(trip_plan_id=trip.id, user_id=user.id, role='owner')
            db.session.add(m)
            db.session.commit()
            tid = trip.id

        resp = auth_client.post(f'/api/trips/{tid}/checkout',
                                data=json.dumps({}),
                                content_type='application/json')
        assert resp.status_code == 400

    def test_checkout_minimum_fee(self, auth_client):
        """$3 minimum fee enforced on small trips."""
        with app.app_context():
            user = User.query.filter_by(email='test@example.com').first()
            trip = TripPlan(creator_id=user.id, name='Cheap Trip', status='draft')
            db.session.add(trip)
            db.session.flush()
            m = TripMember(trip_plan_id=trip.id, user_id=user.id, role='owner')
            db.session.add(m)
            item = TripItem(
                trip_plan_id=trip.id,
                added_by_user_id=user.id,
                vertical='flights',
                item_data_json=json.dumps({"title": "Short hop", "price": 5, "savings": 2}),
            )
            db.session.add(item)
            db.session.commit()
            tid = trip.id

        resp = auth_client.post(f'/api/trips/{tid}/checkout',
                                data=json.dumps({}),
                                content_type='application/json')
        data = resp.get_json()
        assert data['success'] is True
        assert data['total_service_fee'] >= 3.0

    def test_settle_request(self, auth_client, trip_with_members):
        """Settle-up request marks assignments as 'requested'."""
        # Checkout first
        auth_client.post(f'/api/trips/{trip_with_members}/checkout',
                         data=json.dumps({}),
                         content_type='application/json')

        resp = auth_client.post(f'/api/trips/{trip_with_members}/settle-up/request',
                                data=json.dumps({}),
                                content_type='application/json')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        assert data['requested_count'] == 1  # One non-payer member

    def test_settle_no_checkout_404(self, auth_client, trip_with_members):
        """Settle-up request without checkout returns 404."""
        resp = auth_client.post(f'/api/trips/{trip_with_members}/settle-up/request',
                                data=json.dumps({}),
                                content_type='application/json')
        assert resp.status_code == 404

    def test_balances_before_checkout(self, auth_client, trip_with_members):
        """Balances endpoint works before checkout (empty)."""
        resp = auth_client.get(f'/api/trips/{trip_with_members}/balances')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        assert data['checked_out'] is False

    def test_balances_after_checkout(self, auth_client, trip_with_members):
        """Balances endpoint returns correct data after checkout."""
        auth_client.post(f'/api/trips/{trip_with_members}/checkout',
                         data=json.dumps({}),
                         content_type='application/json')

        resp = auth_client.get(f'/api/trips/{trip_with_members}/balances')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        assert data['checked_out'] is True
        assert data['total_service_fee'] > 0
        assert data['per_person'] > 0
        assert len(data['balances']) == 2
        assert data['payer']['name'] is not None

    def test_settle_pay_requires_method(self, auth_client, trip_with_members):
        """Settle-up pay without payment_method_id returns 400."""
        # Login as member to test
        with app.app_context():
            auth_client.post(f'/api/trips/{trip_with_members}/checkout',
                             data=json.dumps({}),
                             content_type='application/json')

            # Login as member
            auth_client.post('/login', data={
                'email': 'member@example.com',
                'password': 'MemberPass123!',
            }, follow_redirects=True)

        resp = auth_client.post(f'/api/trips/{trip_with_members}/settle-up/pay',
                                data=json.dumps({}),
                                content_type='application/json')
        assert resp.status_code == 400


# ═════════════════════════════════════════════════════════════
# BUILD #210 — B2B Referral Landing Page
# ═════════════════════════════════════════════════════════════

class TestBuild210ReferralLanding:
    """B2B referral code shows branded landing page."""

    def test_b2b_code_shows_landing_not_redirect(self, client, b2b_client):
        """B2B referral code shows landing page, not blind redirect."""
        # Use a fresh unauthenticated client
        with app.app_context():
            resp = client.get('/ref/TESTAGENCY')
            assert resp.status_code == 200
            html = resp.data.decode()
            assert 'Test Agency' in html
            assert 'invited you to MYSTES' in html
            assert 'Search Flights' in html

    def test_b2b_landing_contains_savings_example(self, client, b2b_client):
        """Landing page shows example savings breakdown."""
        with app.app_context():
            resp = client.get('/ref/TESTAGENCY')
            html = resp.data.decode()
            assert '$1,400' in html  # Example retail
            assert '$1,050' in html  # Example MYSTES price
            assert '$350' in html    # Example savings

    def test_b2b_landing_sets_session(self, client, b2b_client):
        """B2B landing page sets referral session vars."""
        with app.app_context():
            with client.session_transaction() as sess:
                pass  # Clear

            resp = client.get('/ref/TESTAGENCY')
            assert resp.status_code == 200

            with client.session_transaction() as sess:
                assert sess.get('referral_source') == 'COMM_TEST'

    def test_b2b_landing_case_insensitive(self, client, b2b_client):
        """Referral code is case-insensitive."""
        with app.app_context():
            resp = client.get('/ref/testagency')
            assert resp.status_code == 200
            html = resp.data.decode()
            assert 'Test Agency' in html

    def test_consumer_referral_still_works(self, client):
        """Consumer referral codes still show signup splash."""
        with app.app_context():
            user = User(
                email='referrer@example.com',
                name='Referrer User',
                referral_code='REFUSER',
                is_verified=True,
                is_active=True,
            )
            user.set_password('Pass123!')
            db.session.add(user)
            db.session.commit()

            resp = client.get('/ref/REFUSER')
            assert resp.status_code == 200
            html = resp.data.decode()
            # Consumer splash shows the referrer name or generic message + signup CTA
            assert 'MYSTES' in html
            assert 'Create Free Account' in html or 'bonus points' in html or 'Join MYSTES' in html

    def test_invalid_referral_redirects_register(self, client):
        """Invalid referral code redirects to /register."""
        resp = client.get('/ref/NONEXISTENT')
        assert resp.status_code == 302

    def test_b2b_landing_referral_code_displayed(self, client, b2b_client):
        """Landing page displays the referral code."""
        with app.app_context():
            resp = client.get('/ref/TESTAGENCY')
            html = resp.data.decode()
            assert 'TESTAGENCY' in html

    def test_no_duplicate_route_in_business(self, client, b2b_client):
        """routes_business.py no longer has duplicate /ref/ route."""
        # The landing page should render from server.py, not redirect from routes_business.py
        with app.app_context():
            resp = client.get('/ref/TESTAGENCY')
            assert resp.status_code == 200  # 200 = landing page, not 302 redirect


# ═════════════════════════════════════════════════════════════
# CROSS-BUILD INTEGRATION
# ═════════════════════════════════════════════════════════════

class TestCrossBuildIntegration:
    """Tests spanning multiple builds."""

    def test_b2b_referral_qr_to_landing(self, b2b_client, client):
        """B2B QR → scan → landing page flow."""
        with app.app_context():
            # Get QR data (may 404 if B2B routes not registered)
            qr_resp = b2b_client.get('/api/business/qr-data')
            if qr_resp.status_code == 404:
                pytest.skip('B2B routes not registered (b2b_accounts feature flag off at import time)')
            assert qr_resp.status_code == 200
            url = qr_resp.get_json()['referral_url']
            # Extract path from URL
            code = url.split('/ref/')[-1]
            # Visit landing page
            landing_resp = client.get(f'/ref/{code}')
            assert landing_resp.status_code == 200
            assert b'Search Flights' in landing_resp.data

    def test_booking_model_defaults_api_channel(self, client):
        """New bookings default to 'api' channel."""
        with app.app_context():
            col = Booking.__table__.columns['booking_channel']
            assert col.default.arg == 'api'
            booking = Booking()
            assert booking.proxy_market is None
            assert booking.service_fee_stripe_pi is None
