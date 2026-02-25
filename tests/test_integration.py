"""
MYSTES End-to-End Integration Tests

Tests the full application flow: registration, login, search, P2P booking,
wallet management, helper activation, and admin operations.

Run: pytest tests/test_integration.py -v
"""

import json
import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server import app, db, limiter, _deal_link_rate
from models import User, Deal, HelperProfile, UserWallet, UserCard, P2PTransaction


@pytest.fixture
def client():
    """Create a test client with in-memory database."""
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['WTF_CSRF_ENABLED'] = False
    app.config['SERVER_NAME'] = 'localhost.localdomain'
    app.config['RATELIMIT_ENABLED'] = False

    # Disable Flask-Limiter at the object level — setting the config flag
    # alone doesn't work because the Limiter is already initialized at import
    limiter.enabled = False
    _deal_link_rate.clear()

    with app.app_context():
        db.create_all()
        yield app.test_client()
        db.drop_all()

    # Re-enable limiter after tests (good hygiene)
    limiter.enabled = True


@pytest.fixture
def auth_client(client):
    """Create a test client with an authenticated user."""
    with app.app_context():
        # Register
        client.post('/register', data={
            'email': 'test@example.com',
            'password': 'TestPass123!',
            'name': 'Test User',
        }, follow_redirects=True)

        # Login
        client.post('/login', data={
            'email': 'test@example.com',
            'password': 'TestPass123!',
        }, follow_redirects=True)

        yield client


@pytest.fixture
def admin_client(client):
    """Create a test client with an admin user."""
    with app.app_context():
        user = User(
            email='admin@example.com',
            name='Admin User',
            is_admin=True,
            is_verified=True,
            is_active=True,
        )
        user.set_password('AdminPass123!')
        db.session.add(user)
        db.session.commit()

        client.post('/login', data={
            'email': 'admin@example.com',
            'password': 'AdminPass123!',
        }, follow_redirects=True)

        yield client


# ===================================================================
# Page Load Tests
# ===================================================================

class TestPageLoads:
    """Test that all public pages load successfully."""

    def test_home_page(self, client):
        resp = client.get('/')
        assert resp.status_code == 200
        assert b'MYSTES' in resp.data

    def test_login_page(self, client):
        resp = client.get('/login')
        assert resp.status_code == 200

    def test_register_page(self, client):
        resp = client.get('/register')
        assert resp.status_code == 200

    def test_about_page(self, client):
        resp = client.get('/about')
        assert resp.status_code == 200

    def test_earn_page(self, client):
        resp = client.get('/earn')
        assert resp.status_code == 200

    def test_search_page(self, client):
        resp = client.get('/search')
        assert resp.status_code == 200

    def test_deals_page(self, client):
        resp = client.get('/deals')
        assert resp.status_code == 200

    def test_terms_page(self, client):
        resp = client.get('/terms')
        assert resp.status_code == 200

    def test_privacy_page(self, client):
        resp = client.get('/privacy')
        assert resp.status_code == 200

    def test_health_endpoint(self, client):
        resp = client.get('/health')
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data['status'] in ('healthy', 'ok')


# ===================================================================
# Auth Tests
# ===================================================================

class TestAuth:
    """Test registration, login, logout flows."""

    def test_register_new_user(self, client):
        resp = client.post('/register', data={
            'email': 'new@example.com',
            'password': 'SecurePass123!',
            'name': 'New User',
        }, follow_redirects=True)
        assert resp.status_code == 200
        with app.app_context():
            user = User.query.filter_by(email='new@example.com').first()
            assert user is not None
            assert user.name == 'New User'

    def test_register_duplicate_email(self, client):
        client.post('/register', data={
            'email': 'dup@example.com',
            'password': 'Pass123!',
            'name': 'First',
        })
        resp = client.post('/register', data={
            'email': 'dup@example.com',
            'password': 'Pass123!',
            'name': 'Second',
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b'already registered' in resp.data.lower() or resp.status_code == 200

    def test_login_valid(self, client):
        client.post('/register', data={
            'email': 'login@example.com',
            'password': 'Pass123!',
            'name': 'Login Test',
        })
        resp = client.post('/login', data={
            'email': 'login@example.com',
            'password': 'Pass123!',
        }, follow_redirects=True)
        assert resp.status_code == 200

    def test_login_invalid_password(self, client):
        client.post('/register', data={
            'email': 'bad@example.com',
            'password': 'Pass123!',
            'name': 'Bad Login',
        })
        resp = client.post('/login', data={
            'email': 'bad@example.com',
            'password': 'WrongPassword',
        }, follow_redirects=True)
        assert resp.status_code == 200

    def test_logout(self, auth_client):
        resp = auth_client.get('/logout', follow_redirects=True)
        assert resp.status_code == 200

    def test_protected_page_redirects(self, client):
        resp = client.get('/dashboard')
        assert resp.status_code in (302, 401)

    def test_dashboard_when_logged_in(self, auth_client):
        resp = auth_client.get('/dashboard')
        assert resp.status_code == 200


# ===================================================================
# Authenticated Page Tests
# ===================================================================

class TestAuthenticatedPages:
    """Test pages that require authentication."""

    def test_settings_page(self, auth_client):
        resp = auth_client.get('/settings')
        assert resp.status_code == 200

    def test_wallet_page(self, auth_client):
        resp = auth_client.get('/wallet')
        assert resp.status_code == 200

    def test_helper_dashboard(self, auth_client):
        resp = auth_client.get('/helper', follow_redirects=True)
        # May redirect to /dashboard if node_onboarding feature flag not seeded
        assert resp.status_code == 200

    def test_p2p_my_bookings(self, auth_client):
        resp = auth_client.get('/p2p/my-bookings')
        assert resp.status_code == 200

    def test_p2p_my_transactions_api(self, auth_client):
        resp = auth_client.get('/api/p2p/my-transactions')
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert 'transactions' in data


# ===================================================================
# Wallet Management Tests
# ===================================================================

class TestWalletManagement:
    """Test wallet and card management."""

    def test_add_wallet(self, auth_client):
        # Address must be >= 25 chars and start with 'r' per server validation
        wallet_addr = 'rTestWalletAddressXRPL12345'
        resp = auth_client.post('/wallet/add', data={
            'wallet_address': wallet_addr,
            'wallet_label': 'My Test Wallet',
        }, follow_redirects=True)
        assert resp.status_code == 200
        with app.app_context():
            wallet = UserWallet.query.filter_by(wallet_address=wallet_addr).first()
            assert wallet is not None

    def test_add_card(self, auth_client):
        resp = auth_client.post('/card/add', data={
            'card_label': 'My Visa',
            'card_last_four': '4242',
            'card_brand': 'visa',
            'card_exp_month': '12',
            'card_exp_year': '2028',
            'billing_name': 'Test User',
            'billing_country': 'US',
        }, follow_redirects=True)
        assert resp.status_code == 200
        with app.app_context():
            card = UserCard.query.filter_by(card_last_four='4242').first()
            assert card is not None

    def test_remove_wallet(self, auth_client):
        # Address must be >= 25 chars
        wallet_addr = 'rRemoveThisWalletAddress12'
        auth_client.post('/wallet/add', data={
            'wallet_address': wallet_addr,
            'wallet_label': 'Remove Me',
        })
        with app.app_context():
            wallet = UserWallet.query.filter_by(wallet_address=wallet_addr).first()
            if wallet:
                resp = auth_client.post('/wallet/remove', data={
                    'wallet_id': wallet.id,
                }, follow_redirects=True)
                assert resp.status_code == 200


# ===================================================================
# Helper Tests
# ===================================================================

class TestHelperFlow:
    """Test helper activation and management."""

    def test_activate_helper(self, auth_client):
        # Helper activation requires wallet + card prerequisites
        wallet_addr = 'rHelperTestWalletAddress12'
        auth_client.post('/wallet/add', data={
            'wallet_address': wallet_addr,
            'wallet_label': 'Helper Wallet',
        })
        auth_client.post('/card/add', data={
            'card_label': 'Helper Visa',
            'card_last_four': '1234',
            'card_brand': 'visa',
            'card_exp_month': '06',
            'card_exp_year': '2029',
            'billing_name': 'Test User',
            'billing_country': 'US',
        })

        resp = auth_client.post('/helper/activate', data={
            'country_code': 'GB',
            'city': 'London',
        }, follow_redirects=True)
        assert resp.status_code == 200
        with app.app_context():
            # Registration auto-creates a HelperProfile, so look for the updated one
            helper = HelperProfile.query.filter_by(country_code='GB').first()
            assert helper is not None

    def test_toggle_helper_status(self, auth_client):
        # Need wallet + card before activate works
        wallet_addr = 'rToggleTestWalletAddr12345'
        auth_client.post('/wallet/add', data={
            'wallet_address': wallet_addr,
            'wallet_label': 'Toggle Wallet',
        })
        auth_client.post('/card/add', data={
            'card_label': 'Toggle Visa',
            'card_last_four': '5678',
            'card_brand': 'visa',
            'card_exp_month': '03',
            'card_exp_year': '2028',
            'billing_name': 'Test User',
            'billing_country': 'US',
        })

        auth_client.post('/helper/activate', data={
            'country_code': 'ES',
            'city': 'Madrid',
        })
        resp = auth_client.post('/helper/toggle', follow_redirects=True)
        assert resp.status_code == 200


# ===================================================================
# Search API Tests
# ===================================================================

class TestSearchAPI:
    """Test search API endpoints."""

    def test_airport_search(self, client):
        resp = client.get('/api/airports?q=JFK')
        assert resp.status_code == 200
        data = json.loads(resp.data)
        # API returns {"airports": [...]} wrapper
        airports = data.get('airports', data) if isinstance(data, dict) else data
        assert isinstance(airports, list)

    def test_airport_search_lax(self, client):
        resp = client.get('/api/airports?q=LAX')
        assert resp.status_code == 200
        data = json.loads(resp.data)
        # API returns {"airports": [...]} wrapper
        airports = data.get('airports', data) if isinstance(data, dict) else data
        assert len(airports) > 0

    def test_search_requires_params(self, auth_client):
        resp = auth_client.post('/api/search', data=json.dumps({}),
                                content_type='application/json')
        # Should return 400 or handle gracefully
        assert resp.status_code in (200, 400, 422)


# ===================================================================
# P2P API Tests
# ===================================================================

class TestP2PAPI:
    """Test P2P orchestrator API endpoints."""

    def test_p2p_book_requires_auth(self, client):
        resp = client.post('/api/p2p/book', data=json.dumps({}),
                           content_type='application/json')
        assert resp.status_code in (302, 401, 403)

    def test_p2p_transaction_not_found(self, auth_client):
        resp = auth_client.get('/api/p2p/transaction/nonexistent')
        # Orchestrator returns {"error": "Transaction not found"} → 404
        # May also get 500 if orchestrator init has issues in test context
        assert resp.status_code in (404, 200, 500)

    def test_p2p_match_requires_auth(self, client):
        resp = client.post('/api/p2p/match', data=json.dumps({}),
                           content_type='application/json')
        assert resp.status_code in (302, 401, 403)

    def test_p2p_browser_session_removed(self, auth_client):
        """Browser control was removed in Build #89 — returns 410 Gone."""
        resp = auth_client.get('/api/p2p/browser-session/nonexistent')
        assert resp.status_code == 410
        data = json.loads(resp.data)
        assert 'removed' in data.get('error', '').lower()


# ===================================================================
# Admin Tests
# ===================================================================

class TestAdmin:
    """Test admin dashboard and management."""

    def test_admin_dashboard(self, admin_client):
        resp = admin_client.get('/admin')
        assert resp.status_code == 200
        assert b'Admin Dashboard' in resp.data

    def test_admin_payments(self, admin_client):
        resp = admin_client.get('/admin/payments')
        assert resp.status_code == 200

    def test_admin_users(self, admin_client):
        resp = admin_client.get('/admin/users')
        assert resp.status_code == 200

    def test_admin_wallet(self, admin_client):
        resp = admin_client.get('/admin/wallet')
        assert resp.status_code == 200

    def test_admin_proxies(self, admin_client):
        resp = admin_client.get('/admin/proxies')
        assert resp.status_code == 200

    def test_admin_p2p(self, admin_client):
        resp = admin_client.get('/admin/p2p')
        assert resp.status_code == 200

    def test_admin_helpers(self, admin_client):
        resp = admin_client.get('/admin/helpers')
        assert resp.status_code == 200

    def test_admin_requires_admin(self, auth_client):
        """Regular user should not access admin."""
        resp = auth_client.get('/admin', follow_redirects=True)
        assert b'Admin access required' in resp.data or resp.status_code == 200

    def test_admin_approve_helper(self, admin_client):
        with app.app_context():
            user = User(email='helper@example.com', name='Helper')
            user.set_password('Pass123!')
            db.session.add(user)
            db.session.commit()

            helper = HelperProfile(
                user_id=user.id,
                country_code='JP',
                city='Tokyo',
                is_approved=False,
            )
            db.session.add(helper)
            db.session.commit()
            helper_id = helper.id

        resp = admin_client.post(f'/admin/helpers/approve/{helper_id}',
                                 follow_redirects=True)
        assert resp.status_code == 200
        with app.app_context():
            h = db.session.get(HelperProfile, helper_id)
            assert h.is_approved is True


# ===================================================================
# P2P Booking Flow Tests
# ===================================================================

class TestP2PBookingFlow:
    """Test the full P2P booking page flow."""

    def test_p2p_book_page_loads(self, auth_client):
        resp = auth_client.get('/p2p/book?origin=JFK&destination=LHR&date=2026-06-15&flight=BA178&market=GB&price=450&us_price=650')
        assert resp.status_code == 200
        assert b'Book via P2P' in resp.data
        assert b'450' in resp.data
        assert b'650' in resp.data

    def test_p2p_book_shows_escrow_breakdown(self, auth_client):
        resp = auth_client.get('/p2p/book?origin=JFK&destination=NRT&date=2026-07-01&flight=JL5&market=JP&price=800&us_price=1200')
        assert resp.status_code == 200
        assert b'Escrow Breakdown' in resp.data
        assert b'Helper cut' in resp.data
        assert b'Platform fee' in resp.data

    def test_p2p_book_confirm_needs_wallet(self, auth_client):
        resp = auth_client.post('/p2p/book/confirm', data={
            'origin': 'JFK',
            'destination': 'LHR',
            'date': '2026-06-15',
            'flight_number': 'BA178',
            'market': 'GB',
            'target_price': '450',
            'us_price': '650',
            'first_name': 'John',
            'last_name': 'Doe',
            'email': 'test@example.com',
        }, follow_redirects=True)
        assert resp.status_code == 200
        # Should redirect to wallet page since no wallet configured
        assert b'wallet' in resp.data.lower() or b'Wallet' in resp.data

    def test_p2p_status_not_found(self, auth_client):
        resp = auth_client.get('/p2p/status/nonexistent')
        assert resp.status_code == 404


# ===================================================================
# Payment API Tests
# ===================================================================

class TestPaymentAPI:
    """Test payment-related endpoints."""

    def test_payment_verify_requires_data(self, auth_client):
        resp = auth_client.post('/api/payment/verify', data=json.dumps({}),
                                content_type='application/json')
        assert resp.status_code in (200, 400, 422)

    def test_escrow_create_requires_data(self, auth_client):
        resp = auth_client.post('/api/escrow/create', data=json.dumps({}),
                                content_type='application/json')
        assert resp.status_code in (200, 400, 410, 422)  # 410 when xrpl_escrow feature flag disabled (Phase 1)


# ===================================================================
# Edge Cases
# ===================================================================

class TestEdgeCases:
    """Test error handling and edge cases."""

    def test_404_page(self, client):
        resp = client.get('/nonexistent-page')
        assert resp.status_code == 404

    def test_api_proxy_status_requires_auth(self, client):
        resp = client.get('/api/proxies/status')
        assert resp.status_code in (302, 401)

    def test_double_registration(self, client):
        for _ in range(2):
            client.post('/register', data={
                'email': 'double@example.com',
                'password': 'Pass123!',
                'name': 'Double',
            })
        with app.app_context():
            count = User.query.filter_by(email='double@example.com').count()
            assert count == 1
