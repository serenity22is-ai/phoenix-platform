"""
PHOENIX Build #67 — Browser Extension Data Pipeline Tests

Tests the full node service API pipeline used by the browser extension:
helper token generation, node authentication, data ingestion, session
lifecycle, earnings queries, and configuration delivery.

Run: pytest tests/test_extension_pipeline.py -v
"""

import json
import secrets
import sys
import os

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server import app, db
from models import User, HelperProfile, UserWallet, UserCard, BrowsingEvent


# ===================================================================
# Fixtures
# ===================================================================

@pytest.fixture
def client():
    """Create a test client with in-memory database."""
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['WTF_CSRF_ENABLED'] = False
    app.config['SERVER_NAME'] = 'localhost.localdomain'
    app.config['RATELIMIT_ENABLED'] = False

    with app.app_context():
        db.create_all()
        yield app.test_client()
        db.drop_all()


@pytest.fixture
def auth_client(client):
    """Create a test client with an authenticated user."""
    with app.app_context():
        client.post('/register', data={
            'email': 'ext_test@example.com',
            'password': 'TestPass123!',
            'name': 'Extension Test User',
        }, follow_redirects=True)

        client.post('/login', data={
            'email': 'ext_test@example.com',
            'password': 'TestPass123!',
        }, follow_redirects=True)

        yield client


@pytest.fixture
def helper_client(client):
    """
    Create a test client with an authenticated user who has a fully
    provisioned helper profile, wallet, card, and helper_token.

    Yields (client, helper_token, user).
    """
    with app.app_context():
        # Register and log in
        client.post('/register', data={
            'email': 'helper_ext@example.com',
            'password': 'HelperPass123!',
            'name': 'Helper Node User',
        }, follow_redirects=True)

        client.post('/login', data={
            'email': 'helper_ext@example.com',
            'password': 'HelperPass123!',
        }, follow_redirects=True)

        user = User.query.filter_by(email='helper_ext@example.com').first()

        # Create active, approved helper profile
        helper = HelperProfile(
            user_id=user.id,
            is_active=True,
            is_approved=True,
            country_code='US',
            city='New York',
        )
        db.session.add(helper)
        db.session.flush()

        # Wallet (activation prerequisite)
        wallet = UserWallet(
            user_id=user.id,
            wallet_address='rHelperTestWallet1234567890',
            wallet_label='Helper Wallet',
            is_primary=True,
        )
        db.session.add(wallet)

        # Card (activation prerequisite)
        card = UserCard(
            user_id=user.id,
            card_label='Helper Visa',
            card_last_four='1234',
            card_brand='visa',
            card_exp_month=12,
            card_exp_year=2028,
            billing_name='Helper Node User',
            billing_country='US',
        )
        db.session.add(card)

        # Generate helper token
        helper_token = secrets.token_urlsafe(48)
        helper.helper_token = helper_token
        db.session.commit()

        yield client, helper_token, user


# ===================================================================
# Sample Event Payloads
# ===================================================================

SAMPLE_EVENTS_PAYLOAD = {
    "events": [
        {
            "event_id": "evt_test_001",
            "event_type": "page_visit",
            "url": "https://www.google.com/search?q=cheap+flights",
            "domain": "google.com",
            "title": "cheap flights - Google Search",
            "captured_at": "2026-01-30T12:00:00Z",
            "data": {"referrer": "direct"},
        },
        {
            "event_id": "evt_test_002",
            "event_type": "ad_impression",
            "url": "https://www.google.com/search?q=hotels",
            "domain": "google.com",
            "title": "hotels - Google Search",
            "captured_at": "2026-01-30T12:00:01Z",
            "data": {
                "advertiser": "Booking.com",
                "destination_url": "https://booking.com/deals",
                "position": 1,
                "ad_text": "Best Hotel Deals",
            },
        },
        {
            "event_id": "evt_test_003",
            "event_type": "price_observation",
            "url": "https://www.amazon.com/dp/B08N5WRWNW",
            "domain": "amazon.com",
            "title": "Echo Dot (4th Gen)",
            "captured_at": "2026-01-30T12:00:02Z",
            "data": {
                "product_name": "Echo Dot (4th Gen)",
                "price": "29.99",
                "currency": "USD",
                "seller": "Amazon",
            },
        },
    ],
    "session_id": "SES-test-123",
}


# ===================================================================
# Helper Token Generation Flow
# ===================================================================

class TestHelperTokenGeneration:
    """Test helper token generation and retrieval endpoints."""

    def test_generate_token_requires_active_helper_profile(self, auth_client):
        """POST /helper/token/generate redirects with warning when user has no helper profile."""
        resp = auth_client.post('/helper/token/generate', follow_redirects=True)
        assert resp.status_code == 200
        assert b'Activate' in resp.data or b'helper profile' in resp.data.lower()

    def test_generate_token_with_active_helper_succeeds(self, helper_client):
        """POST /helper/token/generate creates a new token and redirects with success flash."""
        client, _token, _user = helper_client
        resp = client.post('/helper/token/generate', follow_redirects=True)
        assert resp.status_code == 200
        assert b'token' in resp.data.lower() or b'generated' in resp.data.lower()

    def test_get_token_returns_404_when_no_token(self, auth_client):
        """GET /helper/token returns 404 if the user has no helper token."""
        resp = auth_client.get('/helper/token')
        assert resp.status_code == 404
        data = json.loads(resp.data)
        assert 'error' in data

    def test_get_token_returns_json_after_generation(self, helper_client):
        """GET /helper/token returns the helper token as JSON."""
        client, expected_token, _user = helper_client
        resp = client.get('/helper/token')
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert 'helper_token' in data
        assert data['helper_token'] == expected_token


# ===================================================================
# Node Service API Authentication
# ===================================================================

class TestNodeServiceAuth:
    """Test node authentication via X-Helper-Token header."""

    def test_node_auth_with_valid_token_returns_node_id(self, helper_client):
        """POST /api/v1/node/auth with valid helper_token returns node_id and config."""
        client, token, _user = helper_client
        resp = client.post(
            '/api/v1/node/auth',
            headers={'X-Helper-Token': token},
            content_type='application/json',
            data=json.dumps({"helper_token": token}),
        )
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert 'node_id' in data
        assert data['node_id'].startswith('NOD-')
        assert 'config' in data
        assert 'user_id' in data

    def test_node_auth_with_invalid_token_returns_401(self, client):
        """POST /api/v1/node/auth with bogus token returns 401."""
        resp = client.post(
            '/api/v1/node/auth',
            headers={'X-Helper-Token': 'invalid-token-abc'},
            content_type='application/json',
            data=json.dumps({"helper_token": "invalid-token-abc"}),
        )
        assert resp.status_code == 401
        data = json.loads(resp.data)
        assert 'error' in data

    def test_node_auth_without_token_returns_401(self, client):
        """POST /api/v1/node/auth with no token at all returns 401."""
        resp = client.post(
            '/api/v1/node/auth',
            content_type='application/json',
            data=json.dumps({}),
        )
        assert resp.status_code == 401

    def test_node_heartbeat_with_valid_token(self, helper_client):
        """POST /api/v1/node/heartbeat with valid token returns status ok."""
        client, token, _user = helper_client

        # First authenticate to get a node_id
        auth_resp = client.post(
            '/api/v1/node/auth',
            headers={'X-Helper-Token': token},
            content_type='application/json',
            data=json.dumps({"helper_token": token}),
        )
        node_id = json.loads(auth_resp.data)['node_id']

        # Now send heartbeat
        resp = client.post(
            '/api/v1/node/heartbeat',
            headers={'X-Helper-Token': token},
            content_type='application/json',
            data=json.dumps({
                "node_id": node_id,
                "uptime_s": 120,
                "events_buffered": 5,
                "version": "1.0.0",
            }),
        )
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data['status'] == 'ok'
        assert 'server_time' in data

    def test_node_heartbeat_without_token_returns_401(self, client):
        """POST /api/v1/node/heartbeat without token returns 401."""
        resp = client.post(
            '/api/v1/node/heartbeat',
            content_type='application/json',
            data=json.dumps({"node_id": "NOD-fake"}),
        )
        assert resp.status_code == 401


# ===================================================================
# Data Ingestion Pipeline
# ===================================================================

class TestDataIngestion:
    """Test the batch event ingestion endpoint."""

    def _get_node_id(self, client, token):
        """Authenticate and return a valid node_id."""
        resp = client.post(
            '/api/v1/node/auth',
            headers={'X-Helper-Token': token},
            content_type='application/json',
            data=json.dumps({"helper_token": token}),
        )
        return json.loads(resp.data)['node_id']

    def test_ingest_valid_events_returns_accepted_count(self, helper_client):
        """POST /api/v1/node/data/ingest with valid events returns accepted count."""
        client, token, _user = helper_client
        node_id = self._get_node_id(client, token)

        payload = dict(SAMPLE_EVENTS_PAYLOAD)
        payload['node_id'] = node_id

        resp = client.post(
            '/api/v1/node/data/ingest',
            headers={'X-Helper-Token': token},
            content_type='application/json',
            data=json.dumps(payload),
        )
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert 'accepted' in data
        assert data['accepted'] == 3

    def test_ingest_missing_events_returns_error(self, helper_client):
        """POST /api/v1/node/data/ingest with no events field returns error."""
        client, token, _user = helper_client
        node_id = self._get_node_id(client, token)

        resp = client.post(
            '/api/v1/node/data/ingest',
            headers={'X-Helper-Token': token},
            content_type='application/json',
            data=json.dumps({
                "node_id": node_id,
                "session_id": "SES-test-empty",
                "events": "not_a_list",
            }),
        )
        assert resp.status_code == 400
        data = json.loads(resp.data)
        assert 'error' in data

    def test_ingest_missing_session_id_returns_error(self, helper_client):
        """POST /api/v1/node/data/ingest without session_id returns error."""
        client, token, _user = helper_client
        node_id = self._get_node_id(client, token)

        resp = client.post(
            '/api/v1/node/data/ingest',
            headers={'X-Helper-Token': token},
            content_type='application/json',
            data=json.dumps({
                "node_id": node_id,
                "events": [],
            }),
        )
        assert resp.status_code == 400
        data = json.loads(resp.data)
        assert 'error' in data

    def test_ingest_too_many_events_returns_413(self, helper_client):
        """POST /api/v1/node/data/ingest with >500 events returns 413."""
        client, token, _user = helper_client
        node_id = self._get_node_id(client, token)

        oversized_events = [
            {
                "event_id": f"evt_bulk_{i:04d}",
                "event_type": "page_visit",
                "url": f"https://example.com/page/{i}",
                "domain": "example.com",
                "title": f"Page {i}",
                "captured_at": "2026-01-30T12:00:00Z",
                "data": {},
            }
            for i in range(501)
        ]

        resp = client.post(
            '/api/v1/node/data/ingest',
            headers={'X-Helper-Token': token},
            content_type='application/json',
            data=json.dumps({
                "node_id": node_id,
                "session_id": "SES-test-bulk",
                "events": oversized_events,
            }),
        )
        assert resp.status_code == 413
        data = json.loads(resp.data)
        assert 'Too many events' in data.get('error', '')

    def test_ingest_without_token_returns_401(self, client):
        """POST /api/v1/node/data/ingest without auth returns 401."""
        resp = client.post(
            '/api/v1/node/data/ingest',
            content_type='application/json',
            data=json.dumps(SAMPLE_EVENTS_PAYLOAD),
        )
        assert resp.status_code == 401

    def test_ingest_missing_node_id_returns_400(self, helper_client):
        """POST /api/v1/node/data/ingest without node_id returns 400."""
        client, token, _user = helper_client

        resp = client.post(
            '/api/v1/node/data/ingest',
            headers={'X-Helper-Token': token},
            content_type='application/json',
            data=json.dumps({
                "session_id": "SES-test-no-node",
                "events": SAMPLE_EVENTS_PAYLOAD['events'],
            }),
        )
        assert resp.status_code == 400
        data = json.loads(resp.data)
        assert 'error' in data


# ===================================================================
# Node Session Lifecycle
# ===================================================================

class TestNodeSessionLifecycle:
    """Test session start, end, and earnings endpoints."""

    def _get_node_id(self, client, token):
        """Authenticate and return a valid node_id."""
        resp = client.post(
            '/api/v1/node/auth',
            headers={'X-Helper-Token': token},
            content_type='application/json',
            data=json.dumps({"helper_token": token}),
        )
        return json.loads(resp.data)['node_id']

    def test_session_start_returns_session_id(self, helper_client):
        """POST /api/v1/node/session/start returns a session_id."""
        client, token, _user = helper_client
        node_id = self._get_node_id(client, token)

        resp = client.post(
            '/api/v1/node/session/start',
            headers={'X-Helper-Token': token},
            content_type='application/json',
            data=json.dumps({"node_id": node_id}),
        )
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert 'session_id' in data
        assert data['session_id'].startswith('SES-')
        assert 'started_at' in data

    def test_session_start_without_node_id_returns_400(self, helper_client):
        """POST /api/v1/node/session/start without node_id returns 400."""
        client, token, _user = helper_client

        resp = client.post(
            '/api/v1/node/session/start',
            headers={'X-Helper-Token': token},
            content_type='application/json',
            data=json.dumps({}),
        )
        assert resp.status_code == 400

    def test_session_end_returns_success(self, helper_client):
        """POST /api/v1/node/session/end returns closed status."""
        client, token, _user = helper_client
        node_id = self._get_node_id(client, token)

        # Start a session first
        start_resp = client.post(
            '/api/v1/node/session/start',
            headers={'X-Helper-Token': token},
            content_type='application/json',
            data=json.dumps({"node_id": node_id}),
        )
        session_id = json.loads(start_resp.data)['session_id']

        # End the session
        resp = client.post(
            '/api/v1/node/session/end',
            headers={'X-Helper-Token': token},
            content_type='application/json',
            data=json.dumps({
                "node_id": node_id,
                "session_id": session_id,
            }),
        )
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data['status'] == 'closed'
        assert 'ended_at' in data

    def test_session_end_without_session_id_returns_400(self, helper_client):
        """POST /api/v1/node/session/end without session_id returns 400."""
        client, token, _user = helper_client
        node_id = self._get_node_id(client, token)

        resp = client.post(
            '/api/v1/node/session/end',
            headers={'X-Helper-Token': token},
            content_type='application/json',
            data=json.dumps({"node_id": node_id}),
        )
        assert resp.status_code == 400

    def test_earnings_returns_summary(self, helper_client):
        """GET /api/v1/node/earnings returns an earnings summary."""
        client, token, _user = helper_client

        resp = client.get(
            '/api/v1/node/earnings',
            headers={'X-Helper-Token': token},
        )
        assert resp.status_code == 200
        data = json.loads(resp.data)
        # Should contain earnings or yield info (may fall back to warning if
        # node_yield_dashboard is not available)
        assert 'total_earned' in data or 'earnings' in data or 'warning' in data

    def test_earnings_without_token_returns_401(self, client):
        """GET /api/v1/node/earnings without token returns 401."""
        resp = client.get('/api/v1/node/earnings')
        assert resp.status_code == 401


# ===================================================================
# Config Endpoint
# ===================================================================

class TestNodeConfig:
    """Test the node configuration endpoint."""

    def test_config_returns_extraction_rules_and_intervals(self, helper_client):
        """GET /api/v1/node/config returns extraction_rules and intervals."""
        client, token, _user = helper_client

        resp = client.get(
            '/api/v1/node/config',
            headers={'X-Helper-Token': token},
        )
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert 'extraction_rules' in data
        assert 'intervals' in data
        assert 'search_engines' in data['extraction_rules']
        assert 'ad_selectors' in data['extraction_rules']
        assert 'price_selectors' in data['extraction_rules']
        assert 'heartbeat_s' in data['intervals']
        assert 'batch_upload_s' in data['intervals']

    def test_config_includes_limits_and_version(self, helper_client):
        """GET /api/v1/node/config includes limits and version."""
        client, token, _user = helper_client

        resp = client.get(
            '/api/v1/node/config',
            headers={'X-Helper-Token': token},
        )
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert 'limits' in data
        assert data['limits']['max_events_per_batch'] == 500
        assert 'version' in data

    def test_config_without_token_returns_401(self, client):
        """GET /api/v1/node/config without token returns 401."""
        resp = client.get('/api/v1/node/config')
        assert resp.status_code == 401
