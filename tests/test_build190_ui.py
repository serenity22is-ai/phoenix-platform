"""
Build #190 — UI Gap Closure Tests

Tests for Insurance page polish, Fare Rules modal, Seatmap modal,
Dashboard polish, and navigation Insurance link.

Run: pytest tests/test_build190_ui.py -v
"""

import json
import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server import app, db, limiter
from models import User, Deal, RewardsAccount, Booking, FeatureFlag


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
        from models import FeatureFlag, SystemSetting
        FeatureFlag.init_default_flags()
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


# ============================================================
# Insurance Page Tests
# ============================================================

class TestInsurancePage:
    """Tests for the polished insurance page (Build #190 Phase 1)."""

    def test_insurance_page_loads(self, auth_client):
        """GET /insurance returns 200."""
        resp = auth_client.get('/insurance')
        assert resp.status_code == 200

    def test_insurance_page_has_brand_header(self, auth_client):
        """Insurance page contains MYSTES brand and Cinzel typography."""
        resp = auth_client.get('/insurance')
        html = resp.data.decode()
        assert 'Travel Insurance' in html
        assert 'Cinzel' in html

    def test_insurance_page_has_datalist(self, auth_client):
        """Insurance page contains country datalist for autocomplete."""
        resp = auth_client.get('/insurance')
        html = resp.data.decode()
        assert 'datalist' in html.lower()
        assert 'United States' in html


# ============================================================
# Fare Rules Modal Tests
# ============================================================

class TestFareRulesModal:
    """Tests for fare rules modal on flight cards (Build #190 Phase 2)."""

    def test_flights_page_has_fare_rules_function(self, auth_client):
        """Flights page JS contains showFareRules function."""
        resp = auth_client.get('/flights')
        html = resp.data.decode()
        assert 'showFareRules' in html

    def test_flights_page_has_fare_rules_modal(self, auth_client):
        """Flights page contains fare rules modal element."""
        resp = auth_client.get('/flights')
        html = resp.data.decode()
        assert 'fareRulesModal' in html

    def test_fare_rules_api_exists(self, auth_client):
        """POST /api/picasso/fare-rules returns 400 with empty body (not 404)."""
        resp = auth_client.post('/api/picasso/fare-rules',
                                data=json.dumps({}),
                                content_type='application/json')
        assert resp.status_code != 404


# ============================================================
# Seatmap Modal Tests
# ============================================================

class TestSeatmapModal:
    """Tests for seat selection modal in booking flow (Build #190 Phase 3)."""

    def test_seatmap_api_exists(self, auth_client):
        """POST /api/picasso/seatmap returns 400 with empty body (not 404)."""
        resp = auth_client.post('/api/picasso/seatmap',
                                data=json.dumps({}),
                                content_type='application/json')
        assert resp.status_code != 404

    def test_seatmap_modal_html_present(self, auth_client):
        """BOOK_CONTENT template includes seatmap modal."""
        from server import BOOK_CONTENT
        assert 'seatmapModal' in BOOK_CONTENT
        assert 'openSeatmap' in BOOK_CONTENT
        assert 'confirmSeat' in BOOK_CONTENT

    def test_seatmap_only_for_picasso_flights(self, auth_client):
        """Seat selection section is gated behind deal.fare_id."""
        from server import BOOK_CONTENT
        assert 'deal.fare_id' in BOOK_CONTENT


# ============================================================
# Dashboard Polish Tests
# ============================================================

class TestDashboardPolish:
    """Tests for dashboard cinematic upgrade (Build #190 Phase 4)."""

    def test_dashboard_loads(self, auth_client):
        """GET /dashboard returns 200."""
        resp = auth_client.get('/dashboard')
        assert resp.status_code == 200

    def test_dashboard_has_gradient_cards(self, auth_client):
        """Dashboard contains gradient stat cards."""
        resp = auth_client.get('/dashboard')
        html = resp.data.decode()
        assert 'linear-gradient' in html

    def test_dashboard_has_quick_actions(self, auth_client):
        """Dashboard has quick action links to verticals."""
        resp = auth_client.get('/dashboard')
        html = resp.data.decode()
        assert '/flights' in html
        assert '/hotels' in html
        assert '/cars' in html
        assert '/activities' in html
        assert '/insurance' in html

    def test_dashboard_has_cinzel_heading(self, auth_client):
        """Dashboard uses Cinzel font for welcome heading."""
        resp = auth_client.get('/dashboard')
        html = resp.data.decode()
        assert 'Cinzel' in html
        assert 'Welcome back' in html

    def test_dashboard_has_points_balance(self, auth_client):
        """Dashboard displays points balance."""
        resp = auth_client.get('/dashboard')
        html = resp.data.decode()
        assert 'Points' in html

    def test_dashboard_has_fee_tier(self, auth_client):
        """Dashboard shows fee tier info."""
        resp = auth_client.get('/dashboard')
        html = resp.data.decode()
        assert 'Fee Tier' in html


# ============================================================
# Navigation Tests
# ============================================================

class TestNavInsurance:
    """Tests for insurance link in navigation (Build #190 Phase 5)."""

    def test_nav_has_insurance_link(self, auth_client):
        """Navigation More dropdown includes Insurance link."""
        resp = auth_client.get('/dashboard')
        html = resp.data.decode()
        assert 'href="/insurance"' in html
        assert '>Insurance<' in html
