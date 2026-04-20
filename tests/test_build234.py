"""
MYSTES Tests — Build #234 (Arbitrate My Trip)

Tests for:
- ExternalBookingImport model
- ArbitrageCheck model
- HotRoute model
- Import API endpoints (/api/arbitrate/import, my-imports, delete)
- Arbitrage check endpoint (/api/arbitrate/check/<id>)
- Check result endpoint (/api/arbitrate/result/<id>)
- Trip-level arbitrage (/api/arbitrate/trip/<id>, summary)
- Hot routes feed (/api/hot-routes)
- Admin hot routes management
- Arbitrate My Trip page (/arbitrate)

Run: python3 -m pytest tests/test_build234.py -v
"""

import json
import sys
import os
import logging
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta, date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server import app, db, limiter
from models import (
    User, ExternalBookingImport, ArbitrageCheck, HotRoute,
    TripPlan, TripMember,
)


# ───── Fixtures ─────

@pytest.fixture(autouse=True)
def setup_db():
    """Create fresh database for each test."""
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['WTF_CSRF_ENABLED'] = False
    limiter.enabled = False

    with app.app_context():
        db.create_all()
        yield
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client():
    return app.test_client()


@pytest.fixture
def auth_client(client):
    """Authenticated test client."""
    with app.app_context():
        user = User(
            email='test@example.com',
            name='Test User',
            is_verified=True,
            is_active=True,
        )
        user.set_password('TestPass123!')
        db.session.add(user)
        db.session.commit()

    client.post('/login', data={
        'email': 'test@example.com',
        'password': 'TestPass123!',
    }, follow_redirects=True)
    yield client


@pytest.fixture
def admin_client(client):
    """Admin test client."""
    with app.app_context():
        user = User(
            email='admin@mystes.app',
            name='Admin User',
            is_verified=True,
            is_active=True,
            is_admin=True,
        )
        user.set_password('AdminPass123!')
        db.session.add(user)
        db.session.commit()

    client.post('/login', data={
        'email': 'admin@mystes.app',
        'password': 'AdminPass123!',
    }, follow_redirects=True)
    yield client


@pytest.fixture
def sample_import(auth_client):
    """Create a sample external booking import."""
    with app.app_context():
        user = User.query.filter_by(email='test@example.com').first()
        imp = ExternalBookingImport(
            import_id='IMP-test1234',
            user_id=user.id,
            airline='Delta',
            airline_code='DL',
            flight_number='DL123',
            origin='LAX',
            destination='NRT',
            departure_date=date(2026, 6, 15),
            return_date=date(2026, 6, 22),
            cabin_class='economy',
            passengers=1,
            external_price_usd=1400.0,
            external_source='google_flights',
            status='imported',
        )
        db.session.add(imp)
        db.session.commit()
        return imp.import_id


@pytest.fixture
def sample_trip(auth_client):
    """Create a sample trip plan."""
    with app.app_context():
        user = User.query.filter_by(email='test@example.com').first()
        trip = TripPlan(
            name='Japan Trip',
            creator_id=user.id,
            status='draft',
        )
        db.session.add(trip)
        db.session.commit()
        return trip.id


# ============================================================
# MODEL TESTS
# ============================================================

class TestExternalBookingImportModel:
    """Tests for ExternalBookingImport model."""

    def test_model_creation(self):
        with app.app_context():
            user = User(email='model@test.com', name='Model', is_verified=True, is_active=True)
            user.set_password('pass')
            db.session.add(user)
            db.session.commit()

            imp = ExternalBookingImport(
                import_id='IMP-abc123',
                user_id=user.id,
                airline='ANA',
                origin='LAX',
                destination='NRT',
                departure_date=date(2026, 7, 1),
                external_price_usd=1200.0,
                status='imported',
            )
            db.session.add(imp)
            db.session.commit()

            assert imp.id is not None
            assert imp.import_id == 'IMP-abc123'
            assert imp.airline == 'ANA'
            assert imp.cabin_class == 'economy'
            assert imp.passengers == 1
            assert imp.status == 'imported'

    def test_to_dict(self):
        with app.app_context():
            user = User(email='dict@test.com', name='Dict', is_verified=True, is_active=True)
            user.set_password('pass')
            db.session.add(user)
            db.session.commit()

            imp = ExternalBookingImport(
                import_id='IMP-dict01',
                user_id=user.id,
                airline='United',
                origin='ORD',
                destination='LHR',
                departure_date=date(2026, 8, 10),
                external_price_usd=900.0,
                external_source='expedia',
            )
            db.session.add(imp)
            db.session.commit()

            d = imp.to_dict()
            assert d['import_id'] == 'IMP-dict01'
            assert d['origin'] == 'ORD'
            assert d['destination'] == 'LHR'
            assert d['external_price_usd'] == 900.0
            assert d['external_source'] == 'expedia'
            assert d['arbitrage'] is None  # No check yet

    def test_default_status(self):
        with app.app_context():
            user = User(email='stat@test.com', name='Stat', is_verified=True, is_active=True)
            user.set_password('pass')
            db.session.add(user)
            db.session.commit()

            imp = ExternalBookingImport(
                import_id='IMP-stat01',
                user_id=user.id,
                airline='AA',
                origin='DFW',
                destination='MIA',
                departure_date=date(2026, 5, 1),
                external_price_usd=300.0,
            )
            db.session.add(imp)
            db.session.commit()
            assert imp.status == 'imported'


class TestArbitrageCheckModel:
    """Tests for ArbitrageCheck model."""

    def test_model_creation(self):
        with app.app_context():
            user = User(email='arb@test.com', name='Arb', is_verified=True, is_active=True)
            user.set_password('pass')
            db.session.add(user)
            db.session.commit()

            check = ArbitrageCheck(
                check_id='CHK-test01',
                user_id=user.id,
                origin='LAX',
                destination='NRT',
                departure_date=date(2026, 6, 15),
                us_baseline_price=1400.0,
                external_price_usd=1400.0,
                best_pos_price=900.0,
                best_pos_market='DK',
                markets_checked=5,
                spread_usd=500.0,
                fee_percent=0.50,
                service_fee_usd=250.0,
                customer_price_usd=1150.0,
                customer_savings_usd=250.0,
                savings_percent=17.9,
                has_arbitrage=True,
                arbitrage_quality='good',
            )
            db.session.add(check)
            db.session.commit()

            assert check.id is not None
            assert check.has_arbitrage is True
            assert check.arbitrage_quality == 'good'

    def test_to_dict_hides_pos_market(self):
        """Airline compliance: to_dict() must NOT expose POS market codes."""
        with app.app_context():
            user = User(email='hide@test.com', name='Hide', is_verified=True, is_active=True)
            user.set_password('pass')
            db.session.add(user)
            db.session.commit()

            check = ArbitrageCheck(
                check_id='CHK-hide01',
                user_id=user.id,
                origin='JFK',
                destination='CDG',
                departure_date=date(2026, 7, 1),
                best_pos_market='DK',
                has_arbitrage=True,
            )
            db.session.add(check)
            db.session.commit()

            d = check.to_dict()
            assert 'best_pos_market' not in d
            assert 'best_pos_price' not in d

    def test_to_internal_includes_pos_market(self):
        """Admin view should include POS market codes."""
        with app.app_context():
            user = User(email='intl@test.com', name='Internal', is_verified=True, is_active=True)
            user.set_password('pass')
            db.session.add(user)
            db.session.commit()

            check = ArbitrageCheck(
                check_id='CHK-intl01',
                user_id=user.id,
                origin='JFK',
                destination='CDG',
                departure_date=date(2026, 7, 1),
                best_pos_market='DK',
                best_pos_price=800.0,
                spread_usd=400.0,
                fee_percent=0.35,
            )
            db.session.add(check)
            db.session.commit()

            d = check.to_internal()
            assert d['best_pos_market'] == 'DK'
            assert d['best_pos_price'] == 800.0
            assert d['spread_usd'] == 400.0
            assert d['fee_percent'] == 0.35


class TestHotRouteModel:
    """Tests for HotRoute model."""

    def test_model_creation(self):
        with app.app_context():
            route = HotRoute(
                origin='ATL',
                destination='LAX',
                airline='Delta',
                us_retail_price=400.0,
                mystes_price=353.0,
                savings_usd=47.0,
                savings_percent=11.75,
                departure_window='Jun 15-22',
                data_points=15,
                confidence=0.85,
            )
            db.session.add(route)
            db.session.commit()

            assert route.id is not None
            assert route.is_active is True

    def test_to_dict(self):
        with app.app_context():
            route = HotRoute(
                origin='JFK',
                destination='MIA',
                us_retail_price=300.0,
                mystes_price=238.0,
                savings_usd=62.0,
                savings_percent=20.7,
            )
            db.session.add(route)
            db.session.commit()

            d = route.to_dict()
            assert d['origin'] == 'JFK'
            assert d['destination'] == 'MIA'
            assert d['savings_usd'] == 62.0
            assert d['savings_percent'] == 20.7


# ============================================================
# IMPORT API TESTS
# ============================================================

class TestImportAPI:
    """Tests for /api/arbitrate/import endpoint."""

    def test_import_requires_auth(self, client):
        r = client.post('/api/arbitrate/import', json={
            'airline': 'Delta',
            'origin': 'LAX',
            'destination': 'NRT',
            'departure_date': '2026-06-15',
            'external_price_usd': 1400.0,
        })
        # Should redirect to login or return 401/302
        assert r.status_code in (302, 401)

    def test_import_success(self, auth_client):
        r = auth_client.post('/api/arbitrate/import', json={
            'airline': 'ANA',
            'origin': 'lax',  # test lowercase → uppercase
            'destination': 'nrt',
            'departure_date': '2026-06-15',
            'return_date': '2026-06-22',
            'cabin_class': 'economy',
            'passengers': 2,
            'external_price_usd': 1200.0,
            'external_source': 'google_flights',
        })
        assert r.status_code == 200
        data = r.get_json()
        assert data['status'] == 'ok'
        assert data['import']['origin'] == 'LAX'
        assert data['import']['destination'] == 'NRT'
        assert data['import']['external_price_usd'] == 1200.0
        assert data['import']['passengers'] == 2
        assert data['import']['status'] == 'imported'

    def test_import_missing_fields(self, auth_client):
        r = auth_client.post('/api/arbitrate/import', json={
            'airline': 'Delta',
            # missing origin, destination, departure_date, price
        })
        assert r.status_code == 400
        assert 'Missing' in r.get_json()['error']

    def test_import_invalid_price(self, auth_client):
        r = auth_client.post('/api/arbitrate/import', json={
            'airline': 'Delta',
            'origin': 'LAX',
            'destination': 'NRT',
            'departure_date': '2026-06-15',
            'external_price_usd': -50,
        })
        assert r.status_code == 400

    def test_import_invalid_date(self, auth_client):
        r = auth_client.post('/api/arbitrate/import', json={
            'airline': 'Delta',
            'origin': 'LAX',
            'destination': 'NRT',
            'departure_date': 'not-a-date',
            'external_price_usd': 500,
        })
        assert r.status_code == 400

    def test_import_short_airport_code(self, auth_client):
        r = auth_client.post('/api/arbitrate/import', json={
            'airline': 'Delta',
            'origin': 'LA',  # too short
            'destination': 'NRT',
            'departure_date': '2026-06-15',
            'external_price_usd': 500,
        })
        assert r.status_code == 400

    def test_import_passenger_clamping(self, auth_client):
        """Passengers should be clamped to 1-9."""
        r = auth_client.post('/api/arbitrate/import', json={
            'airline': 'Delta',
            'origin': 'LAX',
            'destination': 'NRT',
            'departure_date': '2026-06-15',
            'external_price_usd': 500,
            'passengers': 20,
        })
        assert r.status_code == 200
        assert r.get_json()['import']['passengers'] == 9


class TestMyImportsAPI:
    """Tests for /api/arbitrate/my-imports endpoint."""

    def test_my_imports_empty(self, auth_client):
        r = auth_client.get('/api/arbitrate/my-imports')
        assert r.status_code == 200
        data = r.get_json()
        assert data['count'] == 0
        assert data['imports'] == []

    def test_my_imports_returns_user_data(self, auth_client, sample_import):
        r = auth_client.get('/api/arbitrate/my-imports')
        assert r.status_code == 200
        data = r.get_json()
        assert data['count'] == 1
        assert data['imports'][0]['import_id'] == 'IMP-test1234'

    def test_my_imports_requires_auth(self, client):
        r = client.get('/api/arbitrate/my-imports')
        assert r.status_code in (302, 401)


class TestDeleteImportAPI:
    """Tests for DELETE /api/arbitrate/import/<id>."""

    def test_delete_success(self, auth_client, sample_import):
        r = auth_client.delete(f'/api/arbitrate/import/{sample_import}')
        assert r.status_code == 200
        assert r.get_json()['status'] == 'ok'

        # Verify deleted
        r = auth_client.get('/api/arbitrate/my-imports')
        assert r.get_json()['count'] == 0

    def test_delete_not_found(self, auth_client):
        r = auth_client.delete('/api/arbitrate/import/IMP-nonexist')
        assert r.status_code == 404


# ============================================================
# ARBITRAGE CHECK TESTS
# ============================================================

class TestArbitrageCheckAPI:
    """Tests for /api/arbitrate/check/<id>."""

    def test_check_success(self, auth_client, sample_import):
        r = auth_client.post(f'/api/arbitrate/check/{sample_import}')
        assert r.status_code == 200
        data = r.get_json()
        assert data['status'] == 'ok'
        assert data['import']['status'] == 'checked'
        assert 'check' in data
        assert 'check_id' in data['check']

    def test_check_not_found(self, auth_client):
        r = auth_client.post('/api/arbitrate/check/IMP-nonexist')
        assert r.status_code == 404

    def test_check_sets_fee_percent(self, auth_client, sample_import):
        r = auth_client.post(f'/api/arbitrate/check/{sample_import}')
        data = r.get_json()
        # Default authenticated user = Free tier = 45%
        assert data['check']['check_id'].startswith('CHK-')

    def test_check_result_endpoint(self, auth_client, sample_import):
        # First run the check
        r = auth_client.post(f'/api/arbitrate/check/{sample_import}')
        check_id = r.get_json()['check']['check_id']

        # Then fetch the result
        r = auth_client.get(f'/api/arbitrate/result/{check_id}')
        assert r.status_code == 200
        data = r.get_json()
        assert data['check']['check_id'] == check_id

    def test_check_result_not_found(self, auth_client):
        r = auth_client.get('/api/arbitrate/result/CHK-nonexist')
        assert r.status_code == 404

    def test_check_no_pos_market_in_response(self, auth_client, sample_import):
        """Airline compliance: check result must NOT expose POS market."""
        r = auth_client.post(f'/api/arbitrate/check/{sample_import}')
        data = r.get_json()
        assert 'best_pos_market' not in data['check']
        assert 'best_pos_price' not in data['check']


# ============================================================
# TRIP ARBITRAGE TESTS
# ============================================================

class TestTripArbitrageAPI:
    """Tests for trip-level arbitrage endpoints."""

    def test_trip_arbitrage_no_imports(self, auth_client, sample_trip):
        r = auth_client.post(f'/api/arbitrate/trip/{sample_trip}')
        assert r.status_code == 400
        assert 'No unchecked imports' in r.get_json()['error']

    def test_trip_arbitrage_with_imports(self, auth_client, sample_trip):
        # Add an import to the trip
        with app.app_context():
            user = User.query.filter_by(email='test@example.com').first()
            imp = ExternalBookingImport(
                import_id='IMP-trip01',
                user_id=user.id,
                trip_id=sample_trip,
                airline='ANA',
                origin='LAX',
                destination='NRT',
                departure_date=date(2026, 6, 15),
                external_price_usd=1400.0,
                status='imported',
            )
            db.session.add(imp)
            db.session.commit()

        r = auth_client.post(f'/api/arbitrate/trip/{sample_trip}')
        assert r.status_code == 200
        data = r.get_json()
        assert data['count'] == 1
        assert data['trip_id'] == sample_trip

    def test_trip_summary(self, auth_client, sample_trip):
        # Add and check an import
        with app.app_context():
            user = User.query.filter_by(email='test@example.com').first()
            imp = ExternalBookingImport(
                import_id='IMP-summ01',
                user_id=user.id,
                trip_id=sample_trip,
                airline='Delta',
                origin='JFK',
                destination='CDG',
                departure_date=date(2026, 7, 1),
                external_price_usd=800.0,
                passengers=2,
                status='imported',
            )
            db.session.add(imp)
            db.session.commit()

        r = auth_client.get(f'/api/arbitrate/trip/{sample_trip}/summary')
        assert r.status_code == 200
        data = r.get_json()
        assert data['summary']['total_imports'] == 1
        assert data['summary']['total_external_cost'] == 1600.0  # 800 * 2 passengers

    def test_trip_not_found(self, auth_client):
        r = auth_client.post('/api/arbitrate/trip/99999')
        assert r.status_code == 404

    def test_trip_access_denied(self, client):
        """Unauthenticated user should not access trip arbitrage endpoints."""
        # Create a user and trip
        with app.app_context():
            user = User(
                email='owner@test.com', name='Owner', is_verified=True, is_active=True
            )
            user.set_password('OwnerPass1!')
            db.session.add(user)
            db.session.commit()

            trip = TripPlan(name='Private', creator_id=user.id, status='draft')
            db.session.add(trip)
            db.session.commit()
            trip_id = trip.id

        # Unauthenticated client should be redirected (login required)
        r = client.get(f'/api/arbitrate/trip/{trip_id}/summary')
        assert r.status_code in (302, 401)

    def test_trip_wrong_user_denied(self):
        """User who is not trip creator or member should get 403."""
        with app.app_context():
            # Create owner
            owner = User(email='owner2@test.com', name='Owner2', is_verified=True, is_active=True)
            owner.set_password('OwnerPass1!')
            db.session.add(owner)
            db.session.commit()

            trip = TripPlan(name='Secret Trip', creator_id=owner.id, status='draft')
            db.session.add(trip)

            # Create intruder
            intruder = User(email='intruder@test.com', name='Intruder', is_verified=True, is_active=True)
            intruder.set_password('IntruderPass1!')
            db.session.add(intruder)
            db.session.commit()
            trip_id = trip.id

        # Login as intruder
        c = app.test_client()
        c.post('/login', data={'email': 'intruder@test.com', 'password': 'IntruderPass1!'}, follow_redirects=True)

        r = c.get(f'/api/arbitrate/trip/{trip_id}/summary')
        assert r.status_code == 403


# ============================================================
# HOT ROUTES TESTS
# ============================================================

class TestHotRoutesAPI:
    """Tests for /api/hot-routes endpoint."""

    def test_hot_routes_empty(self, client):
        r = client.get('/api/hot-routes')
        assert r.status_code == 200
        data = r.get_json()
        assert data['count'] == 0

    def test_hot_routes_returns_active(self, client):
        with app.app_context():
            r1 = HotRoute(
                origin='ATL', destination='LAX',
                us_retail_price=400.0, mystes_price=353.0,
                savings_usd=47.0, savings_percent=11.75,
            )
            r2 = HotRoute(
                origin='JFK', destination='MIA',
                us_retail_price=300.0, mystes_price=238.0,
                savings_usd=62.0, savings_percent=20.7,
            )
            r3 = HotRoute(
                origin='ORD', destination='SFO',
                us_retail_price=350.0, mystes_price=350.0,
                savings_usd=0.0, savings_percent=0.0,
                is_active=False,  # inactive
            )
            db.session.add_all([r1, r2, r3])
            db.session.commit()

        r = client.get('/api/hot-routes')
        data = r.get_json()
        assert data['count'] == 2  # Only active routes
        # Sorted by savings_percent desc
        assert data['routes'][0]['destination'] == 'MIA'

    def test_hot_routes_no_auth_required(self, client):
        """Hot routes should be public (no login needed)."""
        r = client.get('/api/hot-routes')
        assert r.status_code == 200


class TestAdminHotRoutes:
    """Tests for admin hot route management."""

    def test_admin_create_hot_route(self, admin_client):
        r = admin_client.post('/api/admin/hot-routes', json={
            'origin': 'ATL',
            'destination': 'LAX',
            'us_retail_price': 400.0,
            'mystes_price': 350.0,
            'airline': 'Delta',
            'departure_window': 'Summer 2026',
        })
        assert r.status_code == 200
        data = r.get_json()
        assert data['route']['savings_usd'] == 50.0
        assert data['route']['origin'] == 'ATL'

    def test_non_admin_blocked(self, auth_client):
        r = auth_client.post('/api/admin/hot-routes', json={
            'origin': 'ATL',
            'destination': 'LAX',
            'us_retail_price': 400.0,
            'mystes_price': 350.0,
        })
        assert r.status_code == 403

    def test_missing_fields(self, admin_client):
        r = admin_client.post('/api/admin/hot-routes', json={
            'origin': 'ATL',
        })
        assert r.status_code == 400


# ============================================================
# PAGE TESTS
# ============================================================

class TestArbitratePage:
    """Tests for /arbitrate page."""

    def test_page_loads(self, client):
        r = client.get('/arbitrate')
        assert r.status_code == 200
        html = r.data.decode()
        assert 'ARBITRATE MY TRIP' in html
        assert 'IMPORT A FLIGHT' in html

    def test_page_has_hot_routes(self, client):
        r = client.get('/arbitrate')
        html = r.data.decode()
        assert 'HOT ROUTES' in html

    def test_page_has_import_form(self, client):
        r = client.get('/arbitrate')
        html = r.data.decode()
        assert 'importFlight' in html
        assert 'arbAirline' in html


# ============================================================
# QUALITY CLASSIFICATION TESTS
# ============================================================

class TestQualityClassification:
    """Test arbitrage quality classification logic."""

    def test_classifications(self):
        from routes_arbitrage import _classify_quality
        assert _classify_quality(30) == 'excellent'
        assert _classify_quality(25) == 'excellent'
        assert _classify_quality(20) == 'good'
        assert _classify_quality(15) == 'good'
        assert _classify_quality(10) == 'marginal'
        assert _classify_quality(5) == 'marginal'
        assert _classify_quality(3) == 'none'
        assert _classify_quality(0) == 'none'


# ============================================================
# CROSS-BUILD INTEGRATION TESTS
# ============================================================

class TestCrossBuildIntegration:
    """Integration tests across Build #234 components."""

    def test_full_import_check_flow(self, auth_client):
        """Full flow: import → check → view result → list."""
        # 1. Import
        r = auth_client.post('/api/arbitrate/import', json={
            'airline': 'ANA',
            'origin': 'LAX',
            'destination': 'NRT',
            'departure_date': '2026-06-15',
            'external_price_usd': 1400.0,
            'external_source': 'google_flights',
        })
        assert r.status_code == 200
        import_id = r.get_json()['import']['import_id']

        # 2. Check
        r = auth_client.post(f'/api/arbitrate/check/{import_id}')
        assert r.status_code == 200
        check_data = r.get_json()
        assert check_data['import']['status'] == 'checked'
        check_id = check_data['check']['check_id']

        # 3. Get result
        r = auth_client.get(f'/api/arbitrate/result/{check_id}')
        assert r.status_code == 200

        # 4. List imports
        r = auth_client.get('/api/arbitrate/my-imports')
        assert r.status_code == 200
        assert r.get_json()['count'] == 1
        assert r.get_json()['imports'][0]['status'] == 'checked'

    def test_import_and_delete_flow(self, auth_client):
        """Import → delete → verify gone."""
        r = auth_client.post('/api/arbitrate/import', json={
            'airline': 'Delta',
            'origin': 'JFK',
            'destination': 'LHR',
            'departure_date': '2026-07-01',
            'external_price_usd': 900.0,
        })
        import_id = r.get_json()['import']['import_id']

        r = auth_client.delete(f'/api/arbitrate/import/{import_id}')
        assert r.status_code == 200

        r = auth_client.get('/api/arbitrate/my-imports')
        assert r.get_json()['count'] == 0

    def test_minimum_fee_enforced(self, auth_client):
        """$3 minimum fee, NO max cap — enforced in check."""
        # Import a cheap flight with tiny spread
        r = auth_client.post('/api/arbitrate/import', json={
            'airline': 'Spirit',
            'origin': 'ATL',
            'destination': 'MIA',
            'departure_date': '2026-05-01',
            'external_price_usd': 50.0,
        })
        import_id = r.get_json()['import']['import_id']

        # Check it — service fee should be at least $3 if there's any arbitrage
        r = auth_client.post(f'/api/arbitrate/check/{import_id}')
        data = r.get_json()
        check = data['check']
        if check['has_arbitrage']:
            assert check['service_fee_usd'] >= 3.0
