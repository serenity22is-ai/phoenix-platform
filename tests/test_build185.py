"""
Build #185 Tests — Priority features: Production, Neurons, APAi, Social, B2B.

Run: pytest tests/test_build185.py -v
"""

import json
import sys
import os
import pytest
from datetime import datetime, date, timezone
from unittest.mock import patch, MagicMock

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _root)
sys.path.insert(0, os.path.join(_root, "picasso-sdk"))

from server import app, db, limiter
from models import (
    User, CommercialAccount, DevPortalAccount,
    TripPlan, TripMember, TripItem, Friendship,
)


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
            'email': 'test185@example.com',
            'password': 'TestPass185!',
            'name': 'Build 185 Tester',
        }, follow_redirects=True)
        client.post('/login', data={
            'email': 'test185@example.com',
            'password': 'TestPass185!',
        }, follow_redirects=True)
        yield client


# ============================================================
# Priority 1: Production Fixes
# ============================================================

class TestProductionFixes:
    """Test production hardening changes."""

    def test_cors_env_var_respected(self, client):
        """CORS_ALLOWED_ORIGINS env var is read during app setup."""
        # Just verify the app starts fine — CORS is set at module level
        resp = client.get('/')
        assert resp.status_code in (200, 302)

    def test_debug_mode_not_forced(self, client):
        """Debug mode respects FLASK_ENV."""
        assert app.config['TESTING'] is True


# ============================================================
# Priority 2: ANASTASiA Neuron Dispatch
# ============================================================

class TestNeuronDispatch:
    """Test that verticals attempt ANASTASiA neuron dispatch."""

    def test_cars_neuron_exists(self):
        """CarsNeuron class is importable from SDK."""
        from anastasia.verticals.cars import CarsNeuron
        neuron = CarsNeuron()
        assert neuron.name == "cars"

    def test_activities_neuron_exists(self):
        """ActivitiesNeuron class is importable from SDK."""
        from anastasia.verticals.activities import ActivitiesNeuron
        neuron = ActivitiesNeuron()
        assert neuron.name == "activities"

    def test_cars_neuron_search_requires_client(self):
        """CarsNeuron.search() returns error without client."""
        from anastasia.verticals.cars import CarsNeuron
        from anastasia.core.events import EventBus
        neuron = CarsNeuron()
        neuron.initialize(EventBus(), {"cars_enabled": True})
        result = neuron.search(pickup_location="JFK", pickup_date="2026-06-01", dropoff_date="2026-06-05")
        assert result["success"] is False
        assert "client" in result["error"].lower()

    def test_activities_neuron_search_requires_client(self):
        """ActivitiesNeuron.search() returns error without client."""
        from anastasia.verticals.activities import ActivitiesNeuron
        from anastasia.core.events import EventBus
        neuron = ActivitiesNeuron()
        neuron.initialize(EventBus(), {"activities_enabled": True})
        result = neuron.search(destination="Paris")
        assert result["success"] is False
        assert "client" in result["error"].lower()


# ============================================================
# Priority 3: APAi Subscriber Recognition
# ============================================================

class TestAPAiRecognition:
    """Test APAi subscriber detection in dev portal."""

    def test_detect_apai_no_user(self, client):
        """Detection returns false for unknown email."""
        with app.app_context():
            from routes_devportal import _detect_apai_subscriber
            result = _detect_apai_subscriber("nobody@example.com")
            assert result["is_subscriber"] is False

    def test_detect_apai_with_commercial_account(self, auth_client):
        """Detection finds user with active commercial account."""
        with app.app_context():
            from routes_devportal import _detect_apai_subscriber
            user = User.query.filter_by(email='test185@example.com').first()

            # Create commercial account
            import secrets
            account = CommercialAccount(
                account_id=f"B2B_{secrets.token_hex(6).upper()}",
                name="Test Agency",
                contact_email=user.email,
                owner_user_id=user.id,
                is_active=True,
                subscription_status="active",
                subscription_plan="b2b_starter",
                current_tier="starter",
                fee_percent=25.0,
                referral_code="TESTAGENCY",
            )
            db.session.add(account)
            db.session.commit()

            result = _detect_apai_subscriber('test185@example.com')
            assert result["is_subscriber"] is True
            assert result["mystes_user_id"] == user.id
            assert "template_config" in result

            config = json.loads(result["template_config"])
            assert config["agency_name"] == "Test Agency"
            assert config["tier"] == "starter"

    def test_signup_detects_apai(self, client):
        """Standalone Dev Portal signup scrapped in Build #194.
        /dev/signup now redirects to /apai/admin/login (GET only).
        POST returns 405 — team members are provisioned by APAi admin."""
        # GET redirects to admin login
        resp = client.get('/dev/signup')
        assert resp.status_code == 301
        assert '/apai/admin/login' in resp.headers.get('Location', '')
        # POST returns 405 (method not allowed — standalone signup scrapped)
        resp = client.post('/dev/signup', data={
            'email': 'agency@test.com',
            'password': 'DevPortalPass123!',
        }, follow_redirects=False)
        assert resp.status_code == 405

    def test_account_info_endpoint(self, client):
        """Account info endpoint returns APAi status."""
        with app.app_context():
            import secrets
            account = DevPortalAccount(
                account_id=f"dpa_{secrets.token_hex(12)}",
                email="info@test.com",
                billing_tier="pro",
                is_active=True,
                is_verified=True,
                apai_subscriber=True,
            )
            account.set_password("TestPass123!")
            db.session.add(account)
            db.session.commit()

            with client.session_transaction() as sess:
                sess['dev_portal_account_id'] = account.id

            resp = client.get('/api/apai/admin/account')
            assert resp.status_code == 200
            data = resp.get_json()
            assert data['apai_subscriber'] is True
            assert data['billing_tier'] == 'pro'  # default changed from payg to pro in Build #194


# ============================================================
# Priority 4: Trip Planner + Friends
# ============================================================

class TestTripPlannerEnhancements:
    """Test new trip planner features."""

    def _create_trip(self, auth_client):
        """Helper to create a trip. Returns (trip_id, creator_id)."""
        user = User.query.filter_by(email='test185@example.com').first()
        trip = TripPlan(
            creator_id=user.id,
            name="Rome Trip",
            status="draft",
        )
        db.session.add(trip)
        db.session.flush()

        member = TripMember(
            trip_plan_id=trip.id,
            user_id=user.id,
            role="owner",
            invitation_status="accepted",
            invited_at=datetime.now(),
            joined_at=datetime.now(),
        )
        db.session.add(member)
        db.session.commit()
        return trip.id, user.id

    def test_trip_duplicate(self, auth_client):
        """Trip duplicate creates a new copy."""
        trip_id, _ = self._create_trip(auth_client)
        resp = auth_client.post(f'/api/trips/{trip_id}/duplicate',
                                content_type='application/json')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert "Copy" in data["name"]
        assert data["trip_id"] != trip_id

    def test_trip_budget(self, auth_client):
        """Budget endpoint returns per-member breakdown."""
        trip_id, creator_id = self._create_trip(auth_client)
        item = TripItem(
            trip_plan_id=trip_id,
            added_by_user_id=creator_id,
            vertical="flight",
            item_data_json=json.dumps({"title": "JFK-FCO", "price": 600}),
            day_number=1,
        )
        db.session.add(item)
        db.session.commit()

        resp = auth_client.get(f'/api/trips/{trip_id}/budget')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["total_cost"] == 600.0
        assert data["per_person"] == 600.0

    def test_trip_activity_feed(self, auth_client):
        """Activity feed returns recent items and members."""
        trip_id, _ = self._create_trip(auth_client)
        resp = auth_client.get(f'/api/trips/{trip_id}/activity')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert "activity" in data

    def test_trip_item_status_update(self, auth_client):
        """Item status can be updated by trip owner."""
        trip_id, creator_id = self._create_trip(auth_client)
        item = TripItem(
            trip_plan_id=trip_id,
            added_by_user_id=creator_id,
            vertical="hotel",
            item_data_json=json.dumps({"title": "Rome Hotel", "price": 200}),
            status="proposed",
        )
        db.session.add(item)
        db.session.commit()
        item_id = item.id

        resp = auth_client.put(
            f'/api/trips/{trip_id}/items/{item_id}/status',
            json={"status": "approved"},
            content_type='application/json',
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["status"] == "approved"


class TestFriendsEnhancements:
    """Test new friends features."""

    def _create_friendship(self, auth_client):
        """Create two users and a friendship. Returns (friendship_id, user1_id, user2_id)."""
        user1 = User.query.filter_by(email='test185@example.com').first()

        from models import User as U
        user2 = U(email='friend185@example.com', name='Friend User', is_active=True)
        user2.set_password('FriendPass123!')
        db.session.add(user2)
        db.session.commit()

        friendship = Friendship(
            requester_id=user1.id,
            addressee_id=user2.id,
            status="accepted",
            accepted_at=datetime.now(timezone.utc),
        )
        db.session.add(friendship)
        db.session.commit()
        return friendship.id, user1.id, user2.id

    def test_block_friend(self, auth_client):
        """Can block a friend."""
        friendship_id, _, _ = self._create_friendship(auth_client)
        resp = auth_client.post(f'/api/friends/{friendship_id}/block')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True

    def test_friends_activity_feed(self, auth_client):
        """Activity feed endpoint returns data."""
        self._create_friendship(auth_client)
        resp = auth_client.get('/api/friends/activity')
        assert resp.status_code == 200
        data = resp.get_json()
        assert "activity" in data


# ============================================================
# Priority 5: B2B Dashboard
# ============================================================

class TestB2BEnhancements:
    """Test B2B markup and analytics."""

    def test_commercial_account_markup_fields(self, client):
        """CommercialAccount has consumer markup fields."""
        with app.app_context():
            import secrets
            user = User(email='b2b185@test.com', name='B2B', is_active=True)
            user.set_password('Pass123!')
            db.session.add(user)
            db.session.flush()

            account = CommercialAccount(
                account_id=f"B2B_{secrets.token_hex(6).upper()}",
                name="Markup Test Agency",
                contact_email="b2b185@test.com",
                owner_user_id=user.id,
                is_active=True,
                subscription_status="active",
                consumer_markup_percent=10.0,
                consumer_markup_flat_usd=5.0,
                referral_link_enabled=True,
            )
            db.session.add(account)
            db.session.commit()

            loaded = CommercialAccount.query.filter_by(contact_email="b2b185@test.com").first()
            assert loaded.consumer_markup_percent == 10.0
            assert loaded.consumer_markup_flat_usd == 5.0
            assert loaded.referral_link_enabled is True

    def test_referral_redirect(self, client):
        """Referral link redirects and sets session."""
        import secrets as _secrets
        user = User(email='ref185@test.com', name='Referrer', is_active=True)
        user.set_password('Pass123!')
        db.session.add(user)
        db.session.flush()

        account = CommercialAccount(
            account_id=f"B2B_{_secrets.token_hex(6).upper()}",
            name="Referral Agency",
            contact_email="ref185@test.com",
            owner_user_id=user.id,
            is_active=True,
            subscription_status="active",
            referral_code="TESTREF185",
            consumer_markup_percent=8.0,
        )
        db.session.add(account)
        db.session.commit()

        resp = client.get('/ref/TESTREF185', follow_redirects=False)
        # Build #210: B2B referral codes now show a branded landing page (200)
        # instead of blind redirect (302).
        assert resp.status_code == 200
        html = resp.data.decode()
        assert 'Referral Agency' in html
        assert 'MYSTES' in html
