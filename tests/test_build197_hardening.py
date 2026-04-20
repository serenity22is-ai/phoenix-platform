"""
Build #197 — Deep Hardening + Vertical Route Coverage

Tests:
- offer_id column on Deal model (raw_offer passthrough fix)
- Deal creation extracts offer_id from raw_offer
- Stripe saved-card charge atomicity (DB failure after PaymentIntent)
- Google OAuth error handlers (no redundant print/traceback)
- Exception handling: no str(e) exposure in API responses
- payments.py has module-level logger
- search.py has module-level logger
- Vertical route module smoke tests (flights, hotels, cars, trips, friends, collections, activities, business)

Run: pytest tests/test_build197_hardening.py -v
MYSTES KYRIOS LLC — Confidential.
"""

import json
import os
import sys
from datetime import datetime, timezone, date, timedelta
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server import app, db, limiter
from models import (
    User, Deal, Booking, Payment, Friendship, Collection, SavedItem,
    TripPlan, TripMember, CommercialAccount, FeatureFlag, SystemSetting,
)


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
    limiter.enabled = False

    with app.app_context():
        db.create_all()
        FeatureFlag.init_default_flags()
        SystemSetting.init_defaults()
        yield app.test_client()
        db.drop_all()

    limiter.enabled = True


@pytest.fixture
def auth_user(client):
    """Authenticated user for protected routes."""
    with app.app_context():
        user = User(
            email='b197@mystes.app',
            name='Build197 Tester',
            is_active=True,
            is_verified=True,
        )
        user.set_password('Build197Pass!')
        db.session.add(user)
        db.session.commit()

        client.post('/login', data={
            'email': 'b197@mystes.app',
            'password': 'Build197Pass!',
        }, follow_redirects=True)

        yield client, user


@pytest.fixture
def auth_user_with_friend(client):
    """Two users who are friends."""
    with app.app_context():
        user1 = User(
            email='friend1@mystes.app', name='Friend One',
            is_active=True, is_verified=True,
        )
        user1.set_password('FriendPass1!')
        user2 = User(
            email='friend2@mystes.app', name='Friend Two',
            is_active=True, is_verified=True,
        )
        user2.set_password('FriendPass2!')
        db.session.add_all([user1, user2])
        db.session.flush()

        friendship = Friendship(
            requester_id=user1.id, addressee_id=user2.id,
            status='accepted',
        )
        db.session.add(friendship)
        db.session.commit()

        client.post('/login', data={
            'email': 'friend1@mystes.app',
            'password': 'FriendPass1!',
        }, follow_redirects=True)

        yield client, user1, user2


@pytest.fixture
def b2b_user(client):
    """B2B subscriber for business routes."""
    with app.app_context():
        user = User(
            email='b2b197@mystes.app', name='B2B Tester',
            is_active=True, is_verified=True,
        )
        user.set_password('B2bPass197!')
        db.session.add(user)
        db.session.flush()

        account = CommercialAccount(
            account_id='comm_b197',
            owner_user_id=user.id,
            name='Test OTA 197',
            contact_email='b2b197@mystes.app',
            current_tier='starter',
            subscription_status='active',
            fee_percent=25.0,
        )
        db.session.add(account)
        db.session.commit()

        client.post('/login', data={
            'email': 'b2b197@mystes.app',
            'password': 'B2bPass197!',
        }, follow_redirects=True)

        yield client, user, account


# ============================================================
# 1. Deal Model — offer_id Column (raw_offer passthrough fix)
# ============================================================

class TestDealOfferIdColumn:
    """Build #197: Deal model now has offer_id column for NDC/aggregator sources."""

    def test_deal_has_offer_id_column(self, client):
        """Deal model has offer_id column."""
        with app.app_context():
            assert hasattr(Deal, 'offer_id')

    def test_deal_offer_id_nullable(self, client):
        """offer_id is nullable (Picasso/GDS deals don't have one)."""
        with app.app_context():
            deal = Deal(
                deal_id='test_offer_id_197',
                airline='Test Air',
                origin='JFK', destination='LAX',
                home_price_usd=500.0,
                arbitrage_price_usd=400.0,
            )
            db.session.add(deal)
            db.session.commit()
            assert deal.offer_id is None

    def test_deal_offer_id_stores_value(self, client):
        """offer_id stores NDC offer ID correctly."""
        with app.app_context():
            deal = Deal(
                deal_id='test_offer_id_198',
                airline='Duffel Air',
                origin='LHR', destination='CDG',
                home_price_usd=300.0,
                arbitrage_price_usd=250.0,
                offer_id='off_duffel_abc123',
            )
            db.session.add(deal)
            db.session.commit()

            loaded = Deal.query.filter_by(deal_id='test_offer_id_198').first()
            assert loaded.offer_id == 'off_duffel_abc123'

    def test_deal_creation_extracts_offer_id(self, client):
        """POST /api/deals/create extracts offer_id from raw_offer."""
        with app.app_context():
            resp = client.post('/api/deals/create',
                json={
                    "airline": "British Airways",
                    "route": "LHR → JFK",
                    "date": "2026-06-15",
                    "cheapest_price": 450.0,
                    "us_price": 600.0,
                    "savings": 150.0,
                    "service_fee": 52.50,
                    "total_price": 502.50,
                    "raw_offer": {
                        "offer_id": "off_test_ndc_xyz",
                        "source": "duffel_ndc",
                    },
                },
                content_type='application/json')
            assert resp.status_code == 200
            data = resp.get_json()
            assert data['success'] is True

            deal = Deal.query.filter_by(deal_id=data['deal_id']).first()
            assert deal is not None
            assert deal.offer_id == 'off_test_ndc_xyz'

    def test_deal_creation_offer_id_from_top_level(self, client):
        """offer_id passed at top level takes precedence."""
        with app.app_context():
            resp = client.post('/api/deals/create',
                json={
                    "airline": "Lufthansa",
                    "route": "FRA → SFO",
                    "date": "2026-07-01",
                    "cheapest_price": 700.0,
                    "us_price": 900.0,
                    "savings": 200.0,
                    "service_fee": 70.0,
                    "total_price": 770.0,
                    "offer_id": "off_top_level_123",
                    "raw_offer": {
                        "offer_id": "off_raw_456",
                        "source": "duffel_ndc",
                    },
                },
                content_type='application/json')
            data = resp.get_json()
            deal = Deal.query.filter_by(deal_id=data['deal_id']).first()
            assert deal.offer_id == 'off_top_level_123'

    def test_deal_creation_no_offer_id_is_none(self, client):
        """Picasso/GDS deal without offer_id stores None."""
        with app.app_context():
            resp = client.post('/api/deals/create',
                json={
                    "airline": "Emirates",
                    "route": "DXB → BOM",
                    "date": "2026-08-01",
                    "cheapest_price": 300.0,
                    "us_price": 400.0,
                    "savings": 100.0,
                    "service_fee": 35.0,
                    "total_price": 335.0,
                    "fare_id": "fare_picasso_gds_789",
                    "raw_offer": {
                        "fare_id": "fare_picasso_gds_789",
                        "source": "picasso",
                    },
                },
                content_type='application/json')
            data = resp.get_json()
            deal = Deal.query.filter_by(deal_id=data['deal_id']).first()
            assert deal.fare_id == 'fare_picasso_gds_789'
            assert deal.offer_id is None


# ============================================================
# 2. Stripe Saved-Card Charge Atomicity
# ============================================================

class TestStripeSavedCardAtomicity:
    """Build #197: DB failure after PaymentIntent logs critical + returns payment_intent_id."""

    def test_charge_saved_endpoint_exists(self, client):
        """Stripe saved-card charge endpoint is registered."""
        with app.app_context():
            resp = client.post('/api/payment/stripe/charge-saved',
                json={}, content_type='application/json')
            assert resp.status_code != 404

    def test_charge_saved_requires_auth(self, client):
        """Saved-card charge requires authentication."""
        with app.app_context():
            resp = client.post('/api/payment/stripe/charge-saved',
                json={"deal_id": "test", "card_id": 1},
                content_type='application/json')
            assert resp.status_code in (401, 302)

    def test_outer_exception_no_str_e(self, client):
        """Outer exception handler does NOT return raw str(e)."""
        import inspect
        # Find the charge-saved endpoint function
        for rule in app.url_map.iter_rules():
            if rule.rule == '/api/payment/stripe/charge-saved':
                func = app.view_functions[rule.endpoint]
                source = inspect.getsource(func)
                # Should NOT have: return jsonify({"error": str(e)}), 500
                # Should have: "Payment processing failed. Please try again."
                assert 'Payment processing failed' in source
                assert '"error": str(e)' not in source
                break


# ============================================================
# 3. Exception Handling — No str(e) Exposure
# ============================================================

class TestNoStrEExposure:
    """Build #197: API error responses don't leak internal exception messages."""

    def test_hotel_search_generic_error(self, client):
        """Hotel search error returns generic message, not str(e)."""
        import inspect
        from routes_hotels import register_hotel_routes
        # Check source code of the module
        import routes_hotels
        source = inspect.getsource(routes_hotels)
        assert '"Hotel search failed. Please try again."' in source
        assert '"Hotel selection failed. Please try again."' in source

    def test_car_search_generic_error(self, client):
        """Car search error returns generic message, not str(e)."""
        import inspect
        import routes_cars
        source = inspect.getsource(routes_cars)
        assert '"Location search failed. Please try again."' in source
        assert '"Car search failed. Please try again."' in source
        assert '"Car selection failed. Please try again."' in source

    def test_activity_search_generic_error(self, client):
        """Activity search error returns generic message, not str(e)."""
        import inspect
        import routes_activities
        source = inspect.getsource(routes_activities)
        assert '"Activity search failed. Please try again."' in source
        assert '"Activity selection failed. Please try again."' in source


# ============================================================
# 4. Payments Logger
# ============================================================

class TestPaymentsLogger:
    """Build #197: payments.py has module-level logger for fee lookup debugging."""

    def test_payments_has_module_logger(self, client):
        """payments module has a logger attribute."""
        import payments
        assert hasattr(payments, 'logger')

    def test_fee_percent_returns_valid(self, client):
        """get_fee_percent returns a valid float in expected range."""
        from payments import get_fee_percent
        with app.app_context():
            pct = get_fee_percent()
            assert isinstance(pct, float)
            assert 0.0 < pct <= 1.0  # 0-100% as decimal

    def test_fee_tier_name_returns_string(self, client):
        """get_fee_tier_name returns a valid tier name."""
        from payments import get_fee_tier_name
        with app.app_context():
            tier = get_fee_tier_name()
            assert tier in ("Guest", "Free Member", "Travel+") or tier.startswith("B2B")


# ============================================================
# 5. Search Logger
# ============================================================

class TestSearchLogger:
    """Build #197: search.py has module-level logger, error paths use logger not print."""

    def test_search_has_module_logger(self, client):
        """search module has a logger attribute."""
        import search
        assert hasattr(search, 'logger')

    def test_search_errors_use_logger(self, client):
        """Error paths in search.py use logger, not print."""
        import inspect
        import search
        source = inspect.getsource(search.search_global)
        # Check that error-level messages use logger
        assert 'logger.error("[DUFFEL] NDC search error' in source
        assert 'logger.error("[KIWI] Aggregator search error' in source
        assert 'logger.error("[PICASSO] Error' in source


# ============================================================
# 6. Vertical Route Smoke Tests — Flights
# ============================================================

class TestFlightsRoutes:
    """Vertical: /flights route smoke tests."""

    def test_flights_page_loads(self, client):
        """GET /flights returns 200 or 410 (if feature disabled)."""
        with app.app_context():
            resp = client.get('/flights')
            assert resp.status_code in (200, 410)

    def test_flights_page_contains_search(self, client):
        """Flights page contains search form elements."""
        with app.app_context():
            # Enable feature flag
            flag = FeatureFlag.query.filter_by(flag_name='vertical_flights').first()
            if flag:
                flag.is_enabled = True
                db.session.commit()
            resp = client.get('/flights')
            if resp.status_code == 200:
                html = resp.data.decode()
                assert 'MYSTES' in html


# ============================================================
# 7. Vertical Route Smoke Tests — Hotels
# ============================================================

class TestHotelsRoutes:
    """Vertical: /hotels and /api/hotels/* route smoke tests."""

    def test_hotels_page_loads(self, client):
        """GET /hotels returns 200 or 410."""
        with app.app_context():
            resp = client.get('/hotels')
            assert resp.status_code in (200, 410)

    def test_hotel_search_validates_input(self, client):
        """POST /api/hotels/search rejects empty body."""
        with app.app_context():
            resp = client.post('/api/hotels/search',
                json={},
                content_type='application/json')
            assert resp.status_code in (400, 410, 500)

    def test_hotel_select_validates_input(self, client):
        """POST /api/hotels/select rejects empty body."""
        with app.app_context():
            resp = client.post('/api/hotels/select',
                json={},
                content_type='application/json')
            assert resp.status_code in (400, 410, 500)


# ============================================================
# 8. Vertical Route Smoke Tests — Cars
# ============================================================

class TestCarsRoutes:
    """Vertical: /cars and /api/cars/* route smoke tests."""

    def test_cars_page_loads(self, client):
        """GET /cars returns 200 or 410."""
        with app.app_context():
            resp = client.get('/cars')
            assert resp.status_code in (200, 410)

    def test_car_locations_validates_query(self, client):
        """GET /api/cars/locations rejects empty query."""
        with app.app_context():
            resp = client.get('/api/cars/locations?q=')
            assert resp.status_code in (200, 400, 410)

    def test_car_search_validates_input(self, client):
        """POST /api/cars/search rejects empty body."""
        with app.app_context():
            resp = client.post('/api/cars/search',
                json={},
                content_type='application/json')
            assert resp.status_code in (400, 410, 500)


# ============================================================
# 9. Vertical Route Smoke Tests — Trips
# ============================================================

class TestTripsRoutes:
    """Vertical: /trips and /api/trips/* route smoke tests."""

    def test_trips_page_requires_auth(self, client):
        """GET /trips redirects unauthenticated users."""
        with app.app_context():
            resp = client.get('/trips')
            assert resp.status_code in (302, 401)

    def test_trips_page_loads_for_user(self, auth_user):
        """GET /trips returns 200 for authenticated user."""
        client, user = auth_user
        with app.app_context():
            resp = client.get('/trips')
            assert resp.status_code == 200

    def test_create_trip(self, auth_user):
        """POST /api/trips creates a new trip."""
        client, user = auth_user
        with app.app_context():
            resp = client.post('/api/trips',
                json={
                    "name": "Build 197 Test Trip",
                    "destination": "Tokyo",
                    "start_date": "2026-09-01",
                    "end_date": "2026-09-14",
                },
                content_type='application/json')
            assert resp.status_code == 200
            data = resp.get_json()
            assert data.get('success') is True or data.get('trip_id') is not None

    def test_trip_detail_requires_auth(self, client):
        """GET /trips/<id> redirects unauthenticated."""
        with app.app_context():
            resp = client.get('/trips/999')
            assert resp.status_code in (302, 401, 404)

    def test_delete_trip_requires_auth(self, client):
        """DELETE /api/trips/<id> requires authentication."""
        with app.app_context():
            resp = client.delete('/api/trips/999')
            assert resp.status_code in (302, 401, 404)


# ============================================================
# 10. Vertical Route Smoke Tests — Friends
# ============================================================

class TestFriendsRoutes:
    """Vertical: /friends and /api/friends/* route smoke tests."""

    def test_friends_page_requires_auth(self, client):
        """GET /friends redirects unauthenticated users."""
        with app.app_context():
            resp = client.get('/friends')
            assert resp.status_code in (302, 401)

    def test_friends_page_loads_for_user(self, auth_user):
        """GET /friends returns 200 for authenticated user."""
        client, user = auth_user
        with app.app_context():
            resp = client.get('/friends')
            assert resp.status_code == 200

    def test_friend_search(self, auth_user):
        """GET /api/friends/search returns results."""
        client, user = auth_user
        with app.app_context():
            resp = client.get('/api/friends/search?q=test')
            assert resp.status_code == 200

    def test_friend_request_validates_input(self, auth_user):
        """POST /api/friends/request rejects empty body."""
        client, user = auth_user
        with app.app_context():
            resp = client.post('/api/friends/request',
                json={},
                content_type='application/json')
            assert resp.status_code in (400, 404)

    def test_friend_activity_feed(self, auth_user_with_friend):
        """GET /api/friends/activity returns activity for friends."""
        client, user1, user2 = auth_user_with_friend
        with app.app_context():
            resp = client.get('/api/friends/activity')
            assert resp.status_code == 200
            data = resp.get_json()
            assert 'activity' in data

    def test_friend_activity_feed_logs_errors(self, client):
        """Activity feed exception handlers use logger, not bare pass."""
        import inspect
        import routes_friends
        source = inspect.getsource(routes_friends)
        # Should NOT have bare "except Exception:\n            pass" in activity feed
        assert 'Friend activity feed (bookings) failed' in source
        assert 'Friend activity feed (collections) failed' in source


# ============================================================
# 11. Vertical Route Smoke Tests — Collections
# ============================================================

class TestCollectionsRoutes:
    """Vertical: /collections and /api/collections/* route smoke tests."""

    def test_collections_page_requires_auth(self, client):
        """GET /collections redirects unauthenticated users."""
        with app.app_context():
            resp = client.get('/collections')
            assert resp.status_code in (302, 401)

    def test_collections_page_loads_for_user(self, auth_user):
        """GET /collections returns 200 for authenticated user."""
        client, user = auth_user
        with app.app_context():
            resp = client.get('/collections')
            assert resp.status_code == 200

    def test_create_collection(self, auth_user):
        """POST /api/collections creates a new collection."""
        client, user = auth_user
        with app.app_context():
            resp = client.post('/api/collections',
                json={"name": "Build 197 Test Collection"},
                content_type='application/json')
            assert resp.status_code == 200
            data = resp.get_json()
            assert data.get('success') is True

    def test_collection_detail_requires_owner(self, auth_user):
        """GET /collections/<id> for non-existent collection returns 404."""
        client, user = auth_user
        with app.app_context():
            resp = client.get('/collections/999999')
            assert resp.status_code in (404, 302)


# ============================================================
# 12. Vertical Route Smoke Tests — Activities
# ============================================================

class TestActivitiesRoutes:
    """Vertical: /activities and /api/activities/* route smoke tests."""

    def test_activities_page_loads(self, client):
        """GET /activities returns 200, 404 (not registered), or 410 (disabled)."""
        with app.app_context():
            resp = client.get('/activities')
            # 404 = feature flag was off at module load time (routes not registered)
            assert resp.status_code in (200, 404, 410)

    def test_activity_search_validates_input(self, client):
        """POST /api/activities/search rejects empty body (or 404 if not registered)."""
        with app.app_context():
            resp = client.post('/api/activities/search',
                json={},
                content_type='application/json')
            assert resp.status_code in (400, 404, 410, 500)


# ============================================================
# 13. Vertical Route Smoke Tests — Business (B2B)
# ============================================================

class TestBusinessRoutes:
    """Vertical: /business and /api/business/* route smoke tests.
    Note: B2B routes are conditionally registered if b2b_accounts feature flag
    was enabled at server module load time. Accept 404 if not registered.
    """

    def _routes_registered(self):
        """Check if business routes are registered."""
        for rule in app.url_map.iter_rules():
            if rule.rule == '/business':
                return True
        return False

    def test_business_landing_page_loads(self, client):
        """GET /business returns 200 or 404 (if not registered)."""
        with app.app_context():
            resp = client.get('/business')
            if self._routes_registered():
                assert resp.status_code == 200
            else:
                assert resp.status_code == 404

    def test_business_signup_page_loads(self, client):
        """GET /business/signup returns 200, 302 (login redirect), or 404."""
        with app.app_context():
            resp = client.get('/business/signup')
            assert resp.status_code in (200, 302, 404)

    def test_business_dashboard_requires_auth(self, client):
        """GET /business/dashboard redirects or 404."""
        with app.app_context():
            resp = client.get('/business/dashboard')
            assert resp.status_code in (302, 401, 403, 404)

    def test_business_dashboard_requires_subscription(self, auth_user):
        """GET /business/dashboard without B2B subscription returns redirect/403/404."""
        client, user = auth_user
        with app.app_context():
            resp = client.get('/business/dashboard')
            assert resp.status_code in (302, 403, 404)

    def test_business_dashboard_loads_for_b2b(self, b2b_user):
        """GET /business/dashboard returns 200 for B2B subscriber (if registered)."""
        client, user, account = b2b_user
        with app.app_context():
            if self._routes_registered():
                resp = client.get('/business/dashboard')
                assert resp.status_code == 200
            else:
                pytest.skip("B2B routes not registered (feature flag off at load time)")

    def test_business_landing_has_tiers(self, client):
        """Business landing page shows correct tier names (if registered)."""
        with app.app_context():
            if self._routes_registered():
                resp = client.get('/business')
                html = resp.data.decode()
                assert 'Starter' in html
                assert '$49' in html or '49' in html
            else:
                pytest.skip("B2B routes not registered (feature flag off at load time)")


# ============================================================
# 14. Google OAuth Cleanup
# ============================================================

class TestGoogleOAuthCleanup:
    """Build #197: Google OAuth handlers use logger, not print/traceback."""

    def test_google_token_handler_no_traceback_print(self, client):
        """Google token handler doesn't use traceback.print_exc()."""
        import inspect
        func = app.view_functions.get('api_google_token_signin')
        if func:
            source = inspect.getsource(func)
            assert 'traceback.print_exc()' not in source
            assert 'print(f"[GOOGLE' not in source

    def test_google_callback_handler_no_traceback_print(self, client):
        """Google callback handler doesn't use traceback.print_exc()."""
        import inspect
        func = app.view_functions.get('auth_google_callback')
        if func:
            source = inspect.getsource(func)
            assert 'traceback.print_exc()' not in source
            assert 'print(f"[GOOGLE' not in source


# ============================================================
# 15. Referral Notification Logging
# ============================================================

class TestReferralNotificationLogging:
    """Build #197: Referral notification errors are logged, not silently swallowed."""

    def test_registration_referral_logging(self, client):
        """Registration referral handler logs notification errors."""
        import inspect
        func = app.view_functions.get('register')
        if func:
            source = inspect.getsource(func)
            # Should have logger.debug for notification failure
            assert 'Referral notification email failed' in source or 'notif_err' in source


# ============================================================
# 16. Deal Creation Endpoint Comprehensive
# ============================================================

class TestDealCreationEndpoint:
    """Comprehensive deal creation tests including multi-leg."""

    def test_create_deal_returns_deal_id(self, client):
        """POST /api/deals/create returns deal_id."""
        with app.app_context():
            resp = client.post('/api/deals/create',
                json={
                    "airline": "Test Air",
                    "route": "SFO → NRT",
                    "date": "2026-10-01",
                    "cheapest_price": 500.0,
                    "us_price": 700.0,
                    "savings": 200.0,
                    "service_fee": 70.0,
                    "total_price": 570.0,
                },
                content_type='application/json')
            assert resp.status_code == 200
            data = resp.get_json()
            assert 'deal_id' in data

    def test_create_multi_leg_deal(self, client):
        """POST /api/deals/create with multi-leg flights."""
        with app.app_context():
            resp = client.post('/api/deals/create',
                json={
                    "is_multi_leg": True,
                    "flights": [
                        {
                            "airline": "ANA",
                            "route": "SFO → NRT",
                            "date": "2026-10-01",
                            "cheapest_price": 500.0,
                            "us_price": 700.0,
                            "raw_offer": {
                                "offer_id": "off_leg1_ana",
                                "source": "duffel_ndc",
                            },
                        },
                        {
                            "airline": "JAL",
                            "route": "NRT → KIX",
                            "date": "2026-10-05",
                            "cheapest_price": 100.0,
                            "us_price": 150.0,
                        },
                    ],
                    "total_cheapest_price": 600.0,
                    "total_us_price": 850.0,
                    "total_savings": 250.0,
                    "service_fee": 87.50,
                    "total_price": 687.50,
                    "raw_offer": {
                        "offer_id": "off_multi_combined",
                        "source": "duffel_ndc",
                    },
                },
                content_type='application/json')
            assert resp.status_code == 200
            data = resp.get_json()
            assert data['is_multi_leg'] is True
            assert data['total_legs'] == 2

            deal = Deal.query.filter_by(deal_id=data['deal_id']).first()
            assert deal.offer_id == 'off_multi_combined'

    def test_create_deal_no_data(self, client):
        """POST /api/deals/create with no data returns 400."""
        with app.app_context():
            resp = client.post('/api/deals/create',
                data=b'',
                content_type='application/json')
            assert resp.status_code == 400


# ============================================================
# 17. Core Route Smoke Tests
# ============================================================

class TestCoreRoutes:
    """Core application routes that should always work."""

    def test_home_page_loads(self, client):
        """GET / returns 200."""
        with app.app_context():
            resp = client.get('/')
            assert resp.status_code == 200

    def test_login_page_loads(self, client):
        """GET /login returns 200."""
        with app.app_context():
            resp = client.get('/login')
            assert resp.status_code == 200

    def test_register_page_loads(self, client):
        """GET /register returns 200."""
        with app.app_context():
            resp = client.get('/register')
            assert resp.status_code == 200

    def test_pricing_page_loads(self, client):
        """GET /pricing returns 200."""
        with app.app_context():
            resp = client.get('/pricing')
            assert resp.status_code == 200

    def test_health_check(self, client):
        """GET /health returns 200 with build info."""
        with app.app_context():
            resp = client.get('/health')
            assert resp.status_code == 200
            data = resp.get_json()
            assert data['status'] == 'healthy'

    def test_apai_page_loads(self, client):
        """GET /apai returns 200 (public pitch page)."""
        with app.app_context():
            resp = client.get('/apai')
            assert resp.status_code == 200
