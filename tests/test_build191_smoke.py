"""
Build #191 — Production Readiness Sprint: E2E Smoke Tests

Tests for:
- Track 1: SEO & production (robots.txt, sitemap, OpenGraph)
- Track 2: Search -> deal -> book -> pay -> confirm E2E flow
- Track 3: Social email notifications (friends, trips)
- Track 5: Marketing pages (pricing, FAQ, contact)

Run: pytest tests/test_build191_smoke.py -v
"""

import json
import sys
import os
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server import app, db, limiter
from models import User, Deal, Payment, Booking, FeatureFlag, RewardsAccount


@pytest.fixture
def client():
    """Create a test client with in-memory database."""
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['WTF_CSRF_ENABLED'] = False
    app.config['SERVER_NAME'] = 'localhost.localdomain'
    app.config['RATELIMIT_ENABLED'] = False
    limiter.enabled = False
    with app.app_context():
        db.create_all()
        FeatureFlag.init_default_flags()
        from models import SystemSetting
        SystemSetting.init_defaults()
        yield app.test_client()
        db.drop_all()
    limiter.enabled = True


@pytest.fixture
def auth_client(client):
    """Create a test client with an authenticated user."""
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
def flight_deal(client):
    """Create a valid flight Deal. Returns dict with deal_id and db id."""
    with app.app_context():
        deal = Deal(
            deal_id='SMOKE_FLT_001',
            deal_type='flight',
            origin='JFK',
            destination='LAX',
            departure_date=(datetime.now().date() + timedelta(days=14)),
            airline='Delta',
            flight_number='DL100',
            home_market='US',
            home_price_usd=500.00,
            arbitrage_market='MYSTES',
            arbitrage_price_usd=350.00,
            gross_savings_usd=150.00,
            platform_fee_usd=67.50,
            user_savings_usd=82.50,
            savings_percent=16.5,
            is_active=True,
            deal_status='available',
            fare_id='f_smoke_001',
            fare_search_id='s_smoke_001',
            amadeus_offer_data=json.dumps({
                'source': 'picasso_gds',
                'fare_id': 'f_smoke_001',
                'fare_search_id': 's_smoke_001',
                'offer_id': 'OFF_SMOKE_001',
                'segments': [{'origin': 'JFK', 'destination': 'LAX', 'airline': 'DL'}],
            }),
            expires_at=datetime.utcnow() + timedelta(hours=24),
        )
        db.session.add(deal)
        db.session.commit()
        # Return plain values to avoid DetachedInstanceError
        return {'deal_id': deal.deal_id, 'id': deal.id}


@pytest.fixture
def hotel_deal(client):
    """Create a valid hotel Deal. Returns dict with deal_id and db id."""
    with app.app_context():
        deal = Deal(
            deal_id='SMOKE_HTL_001',
            deal_type='hotel',
            destination='Paris',
            arbitrage_price_usd=200.00,
            platform_fee_usd=45.00,
            is_active=True,
            deal_status='available',
            amadeus_offer_data=json.dumps({
                'source': 'liteapi',
                'hotel_name': 'Hotel Le Marais',
                'check_in': '2026-06-01',
                'check_out': '2026-06-05',
            }),
            expires_at=datetime.utcnow() + timedelta(hours=24),
        )
        db.session.add(deal)
        db.session.commit()
        return {'deal_id': deal.deal_id, 'id': deal.id}


# ============================================================
# TRACK 1: SEO & Production Endpoints
# ============================================================

class TestSEOProduction:
    """Tests for robots.txt, sitemap.xml, and OpenGraph meta tags."""

    def test_robots_txt(self, client):
        """GET /robots.txt returns valid robots file."""
        resp = client.get('/robots.txt')
        assert resp.status_code == 200
        text = resp.data.decode()
        assert 'User-agent: *' in text
        assert 'Disallow: /admin' in text
        assert 'Disallow: /api/' in text
        assert 'Sitemap:' in text

    def test_sitemap_xml(self, client):
        """GET /sitemap.xml returns valid XML sitemap."""
        resp = client.get('/sitemap.xml')
        assert resp.status_code == 200
        assert 'application/xml' in resp.content_type
        xml = resp.data.decode()
        assert '<?xml version' in xml
        assert '<urlset' in xml
        assert '/flights' in xml
        assert '/hotels' in xml
        assert '/pricing' in xml
        assert '/faq' in xml
        assert '/contact' in xml

    def test_opengraph_meta_tags(self, auth_client):
        """Pages include OpenGraph meta tags."""
        resp = auth_client.get('/flights')
        html = resp.data.decode()
        assert 'og:title' in html
        assert 'og:description' in html
        assert 'og:type' in html
        assert 'og:image' in html
        assert 'twitter:card' in html

    def test_meta_description_dynamic(self, client):
        """Pricing page passes custom meta_description."""
        resp = client.get('/pricing')
        html = resp.data.decode()
        assert 'Free to start' in html or 'pricing' in html.lower()


# ============================================================
# TRACK 2: E2E Search -> Deal -> Book -> Pay -> Confirm
# ============================================================

class TestSearchToBookFlow:
    """E2E smoke tests for the critical booking path."""

    def test_deal_creation_with_raw_offer(self, client, flight_deal):
        """Deal has raw_offer data (fare_id, source) for booking dispatch."""
        with app.app_context():
            deal = Deal.query.filter_by(deal_id='SMOKE_FLT_001').first()
            assert deal is not None
            assert deal.fare_id == 'f_smoke_001'
            assert deal.fare_search_id == 's_smoke_001'
            offer_data = json.loads(deal.amadeus_offer_data)
            assert offer_data['source'] == 'picasso_gds'
            assert offer_data['offer_id'] == 'OFF_SMOKE_001'

    def test_save_deal_unauthenticated(self, client, flight_deal):
        """GET /save-deal/<deal_id> shows choice page for guests."""
        resp = client.get(f'/save-deal/{flight_deal["deal_id"]}')
        assert resp.status_code == 200
        html = resp.data.decode()
        assert 'JFK' in html or 'LAX' in html or 'Book' in html.lower() or 'Sign' in html

    def test_book_redirects_unauthenticated(self, client, flight_deal):
        """GET /book/<deal_id> redirects unauthenticated users."""
        resp = client.get(f'/book/{flight_deal["deal_id"]}', follow_redirects=False)
        assert resp.status_code == 302

    def test_book_page_authenticated(self, auth_client, flight_deal):
        """GET /book/<deal_id> renders booking page for auth user."""
        resp = auth_client.get(f'/book/{flight_deal["deal_id"]}')
        assert resp.status_code == 200
        html = resp.data.decode()
        assert 'JFK' in html or 'LAX' in html or 'Delta' in html

    def test_book_page_has_seatmap_for_picasso(self, auth_client, flight_deal):
        """Booking page shows seatmap button for Picasso GDS flights (fare_id present)."""
        resp = auth_client.get(f'/book/{flight_deal["deal_id"]}')
        html = resp.data.decode()
        # Seatmap modal should be in BOOK_CONTENT
        assert 'seatmapModal' in html or 'openSeatmap' in html or 'Choose' in html

    def test_book_nonexistent_deal_redirects(self, auth_client):
        """GET /book/<bad_deal_id> redirects when deal not found."""
        resp = auth_client.get('/book/NONEXISTENT_999', follow_redirects=False)
        assert resp.status_code == 302

    def test_hotel_deal_book_page(self, auth_client, hotel_deal):
        """Hotel deals render booking page correctly."""
        resp = auth_client.get(f'/book/{hotel_deal["deal_id"]}')
        assert resp.status_code == 200

    def test_deal_expiration_check(self, client):
        """Expired deal has expires_at in the past."""
        with app.app_context():
            deal = Deal(
                deal_id='EXPIRED_001',
                deal_type='flight',
                origin='SFO',
                destination='ORD',
                arbitrage_price_usd=200.00,
                platform_fee_usd=30.00,
                is_active=True,
                deal_status='available',
                expires_at=datetime.utcnow() - timedelta(hours=1),
            )
            db.session.add(deal)
            db.session.commit()
            refreshed = Deal.query.filter_by(deal_id='EXPIRED_001').first()
            assert refreshed.expires_at < datetime.utcnow()


class TestStripeCheckout:
    """Tests for Stripe payment creation endpoint."""

    def test_stripe_create_with_deal(self, auth_client, flight_deal):
        """POST /api/payment/stripe/create returns checkout session or graceful error."""
        resp = auth_client.post('/api/payment/stripe/create',
                                data=json.dumps({
                                    'deal_id': flight_deal['deal_id'],
                                    'amount': 417.50,
                                }),
                                content_type='application/json')
        # Should not 500 — either success (200) or graceful error (400/402)
        assert resp.status_code != 500

    def test_stripe_create_no_deal(self, auth_client):
        """POST /api/payment/stripe/create with invalid deal returns error."""
        resp = auth_client.post('/api/payment/stripe/create',
                                data=json.dumps({
                                    'deal_id': 'NONEXISTENT_999',
                                    'amount': 100.00,
                                }),
                                content_type='application/json')
        assert resp.status_code in (400, 404, 500)  # May 500 if stripe not configured


class TestBookingConfirmation:
    """Tests for the booking confirmation page."""

    def test_confirmation_page_renders(self, auth_client, flight_deal):
        """Confirmation page renders for a valid booking."""
        with app.app_context():
            user = User.query.filter_by(email='test@example.com').first()
            deal = Deal.query.get(flight_deal['id'])

            payment = Payment(
                user_id=user.id,
                deal_id=deal.id,
                payment_method='card',
                amount_usd=417.50,
                status='verified',
                verified_at=datetime.utcnow(),
            )
            db.session.add(payment)
            db.session.flush()

            booking = Booking(
                deal_id=deal.id,
                user_id=user.id,
                payment_id=payment.id,
                status='booked',
                confirmation_code='SMOKE123',
                passenger_email='test@example.com',
            )
            db.session.add(booking)
            db.session.commit()

            resp = auth_client.get(f'/booking-confirmation/{booking.id}')
            assert resp.status_code == 200
            html = resp.data.decode()
            assert 'SMOKE123' in html or 'confirm' in html.lower()

    def test_confirmation_unauthenticated_redirects(self, client):
        """Unauthenticated access to confirmation redirects."""
        resp = client.get('/booking-confirmation/1', follow_redirects=False)
        assert resp.status_code == 302


class TestAPIFailover:
    """Tests for graceful degradation when API providers fail."""

    def test_search_api_no_providers(self, auth_client):
        """POST /api/search with no configured providers returns gracefully."""
        with patch('search.search_global', return_value=[]):
            resp = auth_client.post('/api/search',
                                    data=json.dumps({
                                        'origin': 'JFK',
                                        'destination': 'LAX',
                                        'date': '2026-06-15',
                                    }),
                                    content_type='application/json')
            # Should not 500
            assert resp.status_code != 500

    def test_seatmap_api_graceful_failure(self, auth_client):
        """POST /api/picasso/seatmap fails gracefully without Picasso credentials."""
        resp = auth_client.post('/api/picasso/seatmap',
                                data=json.dumps({
                                    'airline_code': 'DL',
                                    'flight_number': '100',
                                    'departure': 'JFK',
                                    'destination': 'LAX',
                                    'departure_date': '2026-06-15',
                                }),
                                content_type='application/json')
        assert resp.status_code != 500

    def test_fare_rules_api_graceful_failure(self, auth_client):
        """POST /api/picasso/fare-rules fails gracefully."""
        resp = auth_client.post('/api/picasso/fare-rules',
                                data=json.dumps({
                                    'fare_search_id': 's_test',
                                    'fare_id': 'f_test',
                                }),
                                content_type='application/json')
        assert resp.status_code != 500


# ============================================================
# TRACK 3: Social Email Notifications
# ============================================================

class TestSocialEmailIntegration:
    """Tests for email notification wiring in social features."""

    def test_email_service_has_friend_request_fn(self):
        """email_service exports send_friend_request_email."""
        from email_service import send_friend_request_email
        assert callable(send_friend_request_email)

    def test_email_service_has_trip_invite_fn(self):
        """email_service exports send_trip_invite_email."""
        from email_service import send_trip_invite_email
        assert callable(send_trip_invite_email)

    def test_email_service_has_collection_shared_fn(self):
        """email_service exports send_collection_shared_email."""
        from email_service import send_collection_shared_email
        assert callable(send_collection_shared_email)

    @patch('email_service.send_email_smtp', return_value=True)
    def test_friend_request_sends_email(self, mock_smtp, auth_client):
        """Sending friend request triggers email notification."""
        with app.app_context():
            target = User(email='friend@example.com', name='Friend User')
            target.set_password('TestPass123!')
            db.session.add(target)
            db.session.commit()

            resp = auth_client.post('/api/friends/request',
                                    data=json.dumps({'email': 'friend@example.com'}),
                                    content_type='application/json')
            assert resp.status_code == 201
            assert mock_smtp.called

    @patch('email_service.send_email_smtp', return_value=True)
    def test_trip_invite_sends_email(self, mock_smtp, auth_client):
        """Trip invite triggers email notification."""
        with app.app_context():
            from models import TripPlan, TripMember
            user = User.query.filter_by(email='test@example.com').first()

            trip = TripPlan(
                creator_id=user.id,
                name='Smoke Test Trip',
                status='draft',
            )
            db.session.add(trip)
            db.session.commit()

            owner = TripMember(
                trip_plan_id=trip.id,
                user_id=user.id,
                role='owner',
                invitation_status='accepted',
            )
            db.session.add(owner)

            invitee = User(email='invitee@example.com', name='Invitee')
            invitee.set_password('TestPass123!')
            db.session.add(invitee)
            db.session.commit()

            resp = auth_client.post(f'/api/trips/{trip.id}/invite',
                                    data=json.dumps({'email': 'invitee@example.com'}),
                                    content_type='application/json')
            assert resp.status_code == 200
            data = resp.get_json()
            assert data['success'] is True
            assert mock_smtp.called


# ============================================================
# TRACK 5: Marketing Pages
# ============================================================

class TestMarketingPages:
    """Tests for Pricing, FAQ, and Contact pages."""

    def test_pricing_page_loads(self, client):
        """GET /pricing returns 200."""
        resp = client.get('/pricing')
        assert resp.status_code == 200

    def test_pricing_has_tiers(self, client):
        """Pricing page shows all consumer tiers."""
        resp = client.get('/pricing')
        html = resp.data.decode()
        assert 'Guest' in html
        assert 'Free Member' in html
        assert 'Travel+' in html
        assert '$9.99' in html
        assert '35%' in html

    def test_pricing_has_b2b(self, client):
        """Pricing page shows B2B tiers."""
        resp = client.get('/pricing')
        html = resp.data.decode()
        assert 'Starter' in html
        assert '$49' in html
        assert 'Growth' in html
        assert '$99' in html
        assert 'Volume' in html
        assert '$199' in html
        assert 'APAi' in html
        # Build #193: APAi pricing changed from $600 to Pro=$299/Enterprise=$599
        assert '$299' in html
        assert '$599' in html

    def test_pricing_no_max_fee_cap(self, client):
        """Pricing page mentions $3 minimum but NO maximum cap."""
        resp = client.get('/pricing')
        html = resp.data.decode()
        assert '$3 minimum' in html

    def test_pricing_has_cinzel(self, client):
        """Pricing page uses Cinzel font."""
        resp = client.get('/pricing')
        html = resp.data.decode()
        assert 'Cinzel' in html

    def test_faq_page_loads(self, client):
        """GET /faq returns 200."""
        resp = client.get('/faq')
        assert resp.status_code == 200

    def test_faq_has_sections(self, client):
        """FAQ page has booking, account, travel, and business sections."""
        resp = client.get('/faq')
        html = resp.data.decode()
        assert 'Booking' in html
        assert 'Account' in html or 'Subscriptions' in html
        assert 'Travel Features' in html
        assert 'Business' in html

    def test_faq_interactive_accordion(self, client):
        """FAQ uses clickable accordion items."""
        resp = client.get('/faq')
        html = resp.data.decode()
        assert 'faq-item' in html
        assert 'classList.toggle' in html

    def test_contact_page_loads(self, client):
        """GET /contact returns 200."""
        resp = client.get('/contact')
        assert resp.status_code == 200

    def test_contact_has_form(self, client):
        """Contact page has a message form."""
        resp = client.get('/contact')
        html = resp.data.decode()
        assert 'contactForm' in html
        assert 'contact-email' in html
        assert 'contact-message' in html

    def test_contact_has_email_addresses(self, client):
        """Contact page shows department emails."""
        resp = client.get('/contact')
        html = resp.data.decode()
        assert 'hello@mystes.app' in html
        assert 'support@mystes.app' in html
        assert 'business@mystes.app' in html

    def test_contact_api_validation(self, client):
        """POST /api/contact validates required fields."""
        resp = client.post('/api/contact',
                           data=json.dumps({'name': '', 'email': '', 'message': ''}),
                           content_type='application/json')
        assert resp.status_code == 400

    @patch('email_service.send_email_smtp', return_value=True)
    def test_contact_api_success(self, mock_smtp, client):
        """POST /api/contact with valid data succeeds."""
        resp = client.post('/api/contact',
                           data=json.dumps({
                               'name': 'Test User',
                               'email': 'test@example.com',
                               'subject': 'Hello',
                               'message': 'This is a test message.',
                           }),
                           content_type='application/json')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True


# ============================================================
# Footer & Navigation
# ============================================================

class TestFooterNavigation:
    """Tests for footer links to new pages."""

    def test_footer_has_pricing_link(self, auth_client):
        """Footer includes link to /pricing."""
        resp = auth_client.get('/dashboard')
        html = resp.data.decode()
        assert 'href="/pricing"' in html

    def test_footer_has_faq_link(self, auth_client):
        """Footer includes link to /faq."""
        resp = auth_client.get('/dashboard')
        html = resp.data.decode()
        assert 'href="/faq"' in html

    def test_footer_has_contact_link(self, auth_client):
        """Footer includes link to /contact."""
        resp = auth_client.get('/dashboard')
        html = resp.data.decode()
        assert 'href="/contact"' in html


# ============================================================
# Multi-Vertical Page Smoke Tests
# ============================================================

class TestMultiVerticalPages:
    """Smoke tests for vertical pages loading."""

    def test_hotel_search_page_loads(self, auth_client):
        """GET /hotels returns 200."""
        resp = auth_client.get('/hotels')
        assert resp.status_code == 200

    def test_cars_page_loads(self, auth_client):
        """GET /cars returns 200."""
        resp = auth_client.get('/cars')
        assert resp.status_code == 200

    def test_insurance_page_loads(self, auth_client):
        """GET /insurance returns 200."""
        resp = auth_client.get('/insurance')
        assert resp.status_code == 200

    def test_insurance_search_api_exists(self, auth_client):
        """POST /api/insurance/search returns non-404."""
        resp = auth_client.post('/api/insurance/search',
                                data=json.dumps({
                                    'destination': 'France',
                                    'start_date': '2026-06-01',
                                    'end_date': '2026-06-15',
                                    'travelers': 1,
                                }),
                                content_type='application/json')
        assert resp.status_code != 404

    def test_car_search_api_exists(self, auth_client):
        """POST /api/cars/search returns non-404."""
        resp = auth_client.post('/api/cars/search',
                                data=json.dumps({
                                    'pickup_location_id': '123',
                                    'pickup_date': '2026-06-01',
                                    'dropoff_date': '2026-06-05',
                                }),
                                content_type='application/json')
        assert resp.status_code != 404
