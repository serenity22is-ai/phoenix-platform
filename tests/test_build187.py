"""
MYSTES Build #187 — raw_offer Passthrough + Collections Tests

Tests:
    - raw_offer safety guard in booking endpoint
    - picasso_gds passthrough in flight card data
    - raw_offer reconstruction from top-level fields
    - raw_offer chain: search → card → Deal record
    - Collections CRUD operations
    - Collections sharing (public slugs)
    - SavedItem across verticals

Run: pytest tests/test_build187.py -v
MYSTES KYRIOS LLC — Confidential.
"""

import json
import os
import sys
import secrets as _s
from datetime import datetime, timezone

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server import app, db, limiter
from models import User, Deal, Collection, SavedItem


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
            'email': 'booktest@example.com',
            'password': 'BookTest123!',
            'name': 'Booking Tester',
        }, follow_redirects=True)
        client.post('/login', data={
            'email': 'booktest@example.com',
            'password': 'BookTest123!',
        }, follow_redirects=True)
        yield client


# ============================================================
# raw_offer Safety Guard Tests
# ============================================================

class TestRawOfferSafetyGuard:
    """Tests for the raw_offer defense-in-depth guard in booking."""

    def test_booking_with_full_raw_offer(self, auth_client):
        """Booking with complete raw_offer stores correctly."""
        with app.app_context():
            resp = auth_client.post('/api/v1/ai/book-flight', json={
                'origin': 'JFK',
                'destination': 'CDG',
                'date': '2026-08-15',
                'price': 450,
                'title': 'Air France AF001',
                'airline': 'Air France',
                'flight_number': 'AF001',
                'home_price': 600,
                'arbitrage_price': 450,
                'savings': 150,
                'savings_pct': 25,
                'raw_offer': {
                    'fare_id': 'FARE_123',
                    'fare_search_id': 'SEARCH_456',
                    'source': 'picasso',
                },
            })
            data = resp.get_json()
            assert data.get('deal_id'), f"Expected deal_id, got: {data}"

            deal = Deal.query.filter_by(deal_id=data['deal_id']).first()
            assert deal is not None
            assert deal.fare_id == 'FARE_123'
            assert deal.fare_search_id == 'SEARCH_456'
            offer_data = json.loads(deal.amadeus_offer_data)
            assert offer_data['source'] == 'picasso'

    def test_booking_reconstructs_raw_offer_from_toplevel(self, auth_client):
        """When raw_offer is missing, fare_id/fare_search_id from top-level are used."""
        with app.app_context():
            resp = auth_client.post('/api/v1/ai/book-flight', json={
                'origin': 'LAX',
                'destination': 'NRT',
                'date': '2026-09-01',
                'price': 800,
                'title': 'Japan Airlines JL061',
                'airline': 'Japan Airlines',
                'flight_number': 'JL061',
                'home_price': 1000,
                'arbitrage_price': 800,
                'savings': 200,
                'savings_pct': 20,
                'fare_id': 'FARE_TOPLEVEL',
                'fare_search_id': 'SEARCH_TOPLEVEL',
                'source': 'picasso',
            })
            data = resp.get_json()
            assert data.get('deal_id')

            deal = Deal.query.filter_by(deal_id=data['deal_id']).first()
            assert deal is not None
            assert deal.fare_id == 'FARE_TOPLEVEL'
            assert deal.fare_search_id == 'SEARCH_TOPLEVEL'
            offer_data = json.loads(deal.amadeus_offer_data)
            assert offer_data.get('_reconstructed') is True
            assert offer_data['source'] == 'picasso'

    def test_booking_with_duffel_offer_id(self, auth_client):
        """Duffel flights pass offer_id through raw_offer."""
        with app.app_context():
            resp = auth_client.post('/api/v1/ai/book-flight', json={
                'origin': 'SFO',
                'destination': 'LHR',
                'date': '2026-07-20',
                'price': 650,
                'title': 'British Airways BA287',
                'airline': 'British Airways',
                'flight_number': 'BA287',
                'home_price': 850,
                'arbitrage_price': 650,
                'savings': 200,
                'savings_pct': 23,
                'raw_offer': {
                    'offer_id': 'off_DUFFEL_789',
                    'source': 'duffel_ndc',
                },
            })
            data = resp.get_json()
            assert data.get('deal_id')

            deal = Deal.query.filter_by(deal_id=data['deal_id']).first()
            assert deal is not None
            offer_data = json.loads(deal.amadeus_offer_data)
            assert offer_data['offer_id'] == 'off_DUFFEL_789'
            assert offer_data['source'] == 'duffel_ndc'

    def test_booking_no_offer_data_still_creates_deal(self, auth_client):
        """Booking without ANY offer references still creates a deal (graceful)."""
        with app.app_context():
            resp = auth_client.post('/api/v1/ai/book-flight', json={
                'origin': 'ORD',
                'destination': 'MIA',
                'date': '2026-06-15',
                'price': 200,
                'title': 'American AA1234',
                'airline': 'American',
                'flight_number': 'AA1234',
                'home_price': 250,
                'arbitrage_price': 200,
                'savings': 50,
                'savings_pct': 20,
            })
            data = resp.get_json()
            assert data.get('deal_id')

            deal = Deal.query.filter_by(deal_id=data['deal_id']).first()
            assert deal is not None
            assert deal.amadeus_offer_data is None

    def test_booking_kiwi_raw_offer(self, auth_client):
        """Kiwi flights pass booking_token through raw_offer."""
        with app.app_context():
            resp = auth_client.post('/api/v1/ai/book-flight', json={
                'origin': 'PRG',
                'destination': 'BCN',
                'date': '2026-10-01',
                'price': 120,
                'title': 'Vueling VY1234',
                'airline': 'Vueling',
                'flight_number': 'VY1234',
                'home_price': 180,
                'arbitrage_price': 120,
                'savings': 60,
                'savings_pct': 33,
                'raw_offer': {
                    'booking_token': 'kiwi_token_abc123',
                    'kiwi_id': 'kiwi_987',
                    'source': 'kiwi_tequila',
                },
            })
            data = resp.get_json()
            assert data.get('deal_id')

            deal = Deal.query.filter_by(deal_id=data['deal_id']).first()
            offer_data = json.loads(deal.amadeus_offer_data)
            assert offer_data['booking_token'] == 'kiwi_token_abc123'
            assert offer_data['source'] == 'kiwi_tequila'

    def test_booking_with_reconstructed_offer_id_only(self, auth_client):
        """Reconstruction works with offer_id alone (Duffel fallback)."""
        with app.app_context():
            resp = auth_client.post('/api/v1/ai/book-flight', json={
                'origin': 'EWR',
                'destination': 'FCO',
                'date': '2026-11-05',
                'price': 500,
                'title': 'United UA987',
                'airline': 'United',
                'flight_number': 'UA987',
                'home_price': 700,
                'arbitrage_price': 500,
                'savings': 200,
                'savings_pct': 28,
                'offer_id': 'off_DUFFEL_FALLBACK',
                'source': 'duffel_ndc',
            })
            data = resp.get_json()
            assert data.get('deal_id')

            deal = Deal.query.filter_by(deal_id=data['deal_id']).first()
            assert deal.amadeus_offer_data is not None
            offer_data = json.loads(deal.amadeus_offer_data)
            assert offer_data['offer_id'] == 'off_DUFFEL_FALLBACK'
            assert offer_data['_reconstructed'] is True

    def test_booking_requires_auth(self, client):
        """Booking endpoint requires authentication."""
        with app.app_context():
            resp = client.post('/api/v1/ai/book-flight', json={
                'origin': 'JFK',
                'destination': 'CDG',
                'date': '2026-08-15',
                'price': 450,
                'title': 'Air France AF001',
            })
            # Unauthenticated should get 401
            assert resp.status_code == 401

    def test_booking_rejects_empty_body(self, auth_client):
        """Empty request body returns 400."""
        with app.app_context():
            resp = auth_client.post(
                '/api/v1/ai/book-flight',
                data=json.dumps(None),
                content_type='application/json',
            )
            assert resp.status_code == 400


# ============================================================
# Flight Card Data Tests
# ============================================================

class TestFlightCardData:
    """Tests for picasso_gds and booking reference passthrough in flight cards."""

    def test_flights_page_renders(self, client):
        """Flight search page loads."""
        with app.app_context():
            resp = client.get('/flights')
            assert resp.status_code == 200
            assert b'MYSTES' in resp.data

    def test_flight_card_includes_raw_offer_field(self, client):
        """Flight card JS includes raw_offer in card data."""
        with app.app_context():
            resp = client.get('/flights')
            assert b'raw_offer' in resp.data

    def test_flight_card_includes_picasso_gds(self, client):
        """Flight card JS includes picasso_gds in card data."""
        with app.app_context():
            resp = client.get('/flights')
            assert b'picasso_gds' in resp.data

    def test_flight_card_includes_fare_id(self, client):
        """Flight card JS includes fare_id in card data."""
        with app.app_context():
            resp = client.get('/flights')
            assert b'fare_id' in resp.data
            assert b'fareId' in resp.data

    def test_flight_card_includes_fare_search_id(self, client):
        """Flight card JS includes fare_search_id in card data."""
        with app.app_context():
            resp = client.get('/flights')
            assert b'fare_search_id' in resp.data
            assert b'fareSearchId' in resp.data

    def test_flight_card_includes_source(self, client):
        """Flight card JS includes source field in card data."""
        with app.app_context():
            resp = client.get('/flights')
            assert b'source: f.source' in resp.data


# ============================================================
# Collections CRUD Tests
# ============================================================

class TestCollectionsCRUD:
    """Test collections creation, listing, and management."""

    def test_collections_page_loads(self, auth_client):
        """Collections page loads for authenticated user."""
        with app.app_context():
            resp = auth_client.get('/collections')
            assert resp.status_code == 200

    def test_create_collection(self, auth_client):
        """Create a new collection via API."""
        with app.app_context():
            resp = auth_client.post('/api/collections', json={
                'name': 'Summer Europe Trip',
            })
            data = resp.get_json()
            assert data.get('success') is True
            coll_id = data.get('collection_id')
            assert coll_id is not None

            coll = Collection.query.first()
            assert coll is not None
            assert coll.name == 'Summer Europe Trip'

    def test_create_collection_requires_name(self, auth_client):
        """Collection creation requires a name."""
        with app.app_context():
            resp = auth_client.post('/api/collections', json={})
            data = resp.get_json()
            assert data.get('success') is False

    def test_delete_collection(self, auth_client):
        """Delete a collection via API."""
        with app.app_context():
            resp = auth_client.post('/api/collections', json={
                'name': 'To Delete',
            })
            coll_id = resp.get_json().get('collection_id')
            assert coll_id

            resp = auth_client.delete(f'/api/collections/{coll_id}')
            assert resp.status_code == 200

    def test_collections_require_auth(self, client):
        """Collections endpoints require authentication."""
        with app.app_context():
            resp = client.get('/collections')
            assert resp.status_code in (302, 401)


# ============================================================
# Collections Saved Items Tests
# ============================================================

class TestCollectionsSavedItems:
    """Test saving items to collections across verticals."""

    def test_save_flight_to_collection(self, auth_client):
        """Save a flight item to a collection."""
        with app.app_context():
            resp = auth_client.post('/api/collections', json={
                'name': 'Best Flights',
            })
            coll_id = resp.get_json().get('collection_id')
            assert coll_id

            resp = auth_client.post(f'/api/collections/{coll_id}/items', json={
                'vertical': 'flight',
                'item_data_json': {
                    'airline': 'Air France',
                    'flight_number': 'AF001',
                    'origin': 'JFK',
                    'destination': 'CDG',
                    'departure_date': '2026-08-15',
                },
                'price_at_save': 450.00,
            })
            data = resp.get_json()
            assert data.get('success') is True
            assert data.get('item_id') is not None

    def test_save_hotel_to_collection(self, auth_client):
        """Save a hotel item to a collection."""
        with app.app_context():
            resp = auth_client.post('/api/collections', json={
                'name': 'Hotels Wishlist',
            })
            coll_id = resp.get_json().get('collection_id')

            resp = auth_client.post(f'/api/collections/{coll_id}/items', json={
                'vertical': 'hotel',
                'item_data_json': {
                    'hotel_name': 'Grand Hotel Paris',
                    'city': 'Paris',
                    'check_in': '2026-08-15',
                    'check_out': '2026-08-20',
                },
                'price_at_save': 220.00,
            })
            data = resp.get_json()
            assert data.get('success') is True

    def test_quick_save_to_favorites(self, auth_client):
        """Quick-save creates a Favorites collection if needed."""
        with app.app_context():
            resp = auth_client.post('/api/save-item', json={
                'vertical': 'flight',
                'item_data_json': {'origin': 'LAX', 'destination': 'HNL'},
                'price_at_save': 300.00,
            })
            data = resp.get_json()
            assert data.get('success') is True
            assert data.get('collection_name') == 'Favorites'

    def test_remove_item_from_collection(self, auth_client):
        """Remove a saved item from a collection."""
        with app.app_context():
            resp = auth_client.post('/api/collections', json={
                'name': 'Removal Test',
            })
            coll_id = resp.get_json().get('collection_id')

            resp = auth_client.post(f'/api/collections/{coll_id}/items', json={
                'vertical': 'flight',
                'item_data_json': '{}',
                'price_at_save': 100.00,
            })
            item_id = resp.get_json().get('item_id')
            assert item_id

            resp = auth_client.delete(f'/api/collections/{coll_id}/items/{item_id}')
            assert resp.status_code == 200

    def test_save_car_to_collection(self, auth_client):
        """Save a car rental to a collection."""
        with app.app_context():
            resp = auth_client.post('/api/collections', json={
                'name': 'Car Rentals',
            })
            coll_id = resp.get_json().get('collection_id')

            resp = auth_client.post(f'/api/collections/{coll_id}/items', json={
                'vertical': 'car',
                'item_data_json': {
                    'vehicle_name': 'Toyota Camry',
                    'pickup_location': 'CDG Airport',
                },
                'price_at_save': 45.00,
            })
            data = resp.get_json()
            assert data.get('success') is True

    def test_save_activity_to_collection(self, auth_client):
        """Save an activity to a collection."""
        with app.app_context():
            resp = auth_client.post('/api/collections', json={
                'name': 'Activities',
            })
            coll_id = resp.get_json().get('collection_id')

            resp = auth_client.post(f'/api/collections/{coll_id}/items', json={
                'vertical': 'activity',
                'item_data_json': {
                    'activity_name': 'Eiffel Tower Tour',
                    'city': 'Paris',
                },
                'price_at_save': 35.00,
            })
            data = resp.get_json()
            assert data.get('success') is True

    def test_invalid_vertical_rejected(self, auth_client):
        """Invalid vertical is rejected."""
        with app.app_context():
            resp = auth_client.post('/api/collections', json={
                'name': 'Test',
            })
            coll_id = resp.get_json().get('collection_id')

            resp = auth_client.post(f'/api/collections/{coll_id}/items', json={
                'vertical': 'spaceship',
                'item_data_json': '{}',
            })
            data = resp.get_json()
            assert data.get('success') is False


# ============================================================
# Collections Sharing Tests
# ============================================================

class TestCollectionsSharing:
    """Test collection sharing via public slugs."""

    def test_update_collection_sharing(self, auth_client):
        """Toggle collection to public/shared."""
        with app.app_context():
            resp = auth_client.post('/api/collections', json={
                'name': 'Share Test',
            })
            coll_id = resp.get_json().get('collection_id')

            resp = auth_client.put(f'/api/collections/{coll_id}', json={
                'is_public': True,
            })
            data = resp.get_json()
            assert data.get('success') is True

    def test_collection_model_fields(self, client):
        """Collection model has required fields."""
        with app.app_context():
            user = User(
                email='coll_model@test.com',
                name='Model Test',
                is_active=True,
            )
            user.set_password('Test123!')
            db.session.add(user)
            db.session.commit()

            coll = Collection(
                user_id=user.id,
                name='Model Test Collection',
            )
            db.session.add(coll)
            db.session.commit()

            assert coll.id is not None
            assert coll.user_id == user.id
            assert coll.name == 'Model Test Collection'
            assert coll.is_shared is False

    def test_saved_item_model_fields(self, client):
        """SavedItem model has required fields."""
        with app.app_context():
            user = User(
                email='item_model@test.com',
                name='Item Test',
                is_active=True,
            )
            user.set_password('Test123!')
            db.session.add(user)
            db.session.commit()

            coll = Collection(user_id=user.id, name='Items Test')
            db.session.add(coll)
            db.session.commit()

            item = SavedItem(
                user_id=user.id,
                collection_id=coll.id,
                vertical='flight',
                item_data_json=json.dumps({'origin': 'JFK', 'destination': 'CDG'}),
                price_at_save=450.0,
            )
            db.session.add(item)
            db.session.commit()

            assert item.id is not None
            assert item.vertical == 'flight'
            assert item.collection_id == coll.id


# ============================================================
# Deal Model raw_offer Storage Tests
# ============================================================

class TestDealRawOfferStorage:
    """Test Deal model stores and retrieves raw_offer correctly."""

    def test_deal_stores_amadeus_offer_data(self, client):
        """Deal.amadeus_offer_data stores JSON string correctly."""
        with app.app_context():
            raw_offer = {
                'fare_id': 'FARE_TEST',
                'fare_search_id': 'SEARCH_TEST',
                'source': 'picasso',
            }
            deal = Deal(
                deal_id=f'PX_TEST_{_s.token_hex(6).upper()}',
                origin='JFK',
                destination='CDG',
                departure_date=datetime(2026, 8, 15).date(),
                arbitrage_price_usd=450.0,
                home_price_usd=600.0,
                fare_id='FARE_TEST',
                fare_search_id='SEARCH_TEST',
                amadeus_offer_data=json.dumps(raw_offer),
                is_active=True,
            )
            db.session.add(deal)
            db.session.commit()

            loaded = Deal.query.filter_by(deal_id=deal.deal_id).first()
            assert loaded.fare_id == 'FARE_TEST'
            assert loaded.fare_search_id == 'SEARCH_TEST'
            parsed = json.loads(loaded.amadeus_offer_data)
            assert parsed['source'] == 'picasso'

    def test_deal_without_offer_data(self, client):
        """Deal can be created without amadeus_offer_data."""
        with app.app_context():
            deal = Deal(
                deal_id=f'PX_NORAW_{_s.token_hex(6).upper()}',
                origin='ORD',
                destination='MIA',
                arbitrage_price_usd=200.0,
                is_active=True,
            )
            db.session.add(deal)
            db.session.commit()

            loaded = Deal.query.filter_by(deal_id=deal.deal_id).first()
            assert loaded is not None
            assert loaded.amadeus_offer_data is None
            assert loaded.fare_id is None

    def test_deal_with_duffel_offer(self, client):
        """Deal stores Duffel offer_id in amadeus_offer_data JSON."""
        with app.app_context():
            raw_offer = {
                'offer_id': 'off_DUFFEL_XYZ',
                'source': 'duffel_ndc',
            }
            deal = Deal(
                deal_id=f'PX_DUF_{_s.token_hex(6).upper()}',
                origin='SFO',
                destination='LHR',
                arbitrage_price_usd=650.0,
                amadeus_offer_data=json.dumps(raw_offer),
                is_active=True,
            )
            db.session.add(deal)
            db.session.commit()

            parsed = json.loads(deal.amadeus_offer_data)
            assert parsed['offer_id'] == 'off_DUFFEL_XYZ'
            assert parsed['source'] == 'duffel_ndc'


# ============================================================
# Search Pipeline raw_offer Completeness Tests
# ============================================================

class TestSearchPipelineOffers:
    """Verify search.py includes raw_offer in all active paths."""

    def test_path2_picasso_includes_raw_offer(self):
        """Path 2 (Picasso) formatted_flight includes raw_offer with fare_id."""
        src = open(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'search.py')).read()
        assert '"raw_offer": {"fare_id":' in src or "'raw_offer': {" in src
        assert 'fare_search_id' in src

    def test_path3_duffel_includes_raw_offer(self):
        """Path 3 (Duffel) formatted_flight includes raw_offer with offer_id."""
        src = open(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'search.py')).read()
        assert 'offer_id' in src
        assert 'duffel_ndc' in src

    def test_path4_kiwi_includes_raw_offer(self):
        """Path 4 (Kiwi) formatted_flight includes raw_offer with booking_token."""
        src = open(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'search.py')).read()
        assert 'booking_token' in src
        assert 'kiwi_tequila' in src

    def test_path1_orchestrator_includes_raw_offer(self):
        """Path 1 (ANASTASiA) passes through raw_offer from orchestrator."""
        src = open(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'search.py')).read()
        assert '"raw_offer": raw' in src

    def test_safety_guard_exists_in_booking(self):
        """Safety guard for missing raw_offer exists in mystes_ai_api.py."""
        src = open(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'mystes_ai_api.py')).read()
        assert '_reconstructed' in src
        assert 'raw_offer missing from booking request' in src


# ============================================================
# Frontend Passthrough Verification
# ============================================================

class TestFrontendPassthrough:
    """Verify routes_flights.py passes all booking references to card data."""

    def test_card_data_has_picasso_gds(self):
        """renderFlightCards includes picasso_gds in card data."""
        src = open(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'routes_flights.py')).read()
        assert 'picassoGds' in src
        assert 'picasso_gds: picassoGds' in src

    def test_card_data_has_fare_id(self):
        """renderFlightCards includes fare_id in card data."""
        src = open(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'routes_flights.py')).read()
        assert 'fare_id: fareId' in src

    def test_card_data_has_fare_search_id(self):
        """renderFlightCards includes fare_search_id in card data."""
        src = open(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'routes_flights.py')).read()
        assert 'fare_search_id: fareSearchId' in src

    def test_card_data_has_offer_id(self):
        """renderFlightCards includes offer_id in card data."""
        src = open(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'routes_flights.py')).read()
        assert 'offer_id: offerId' in src

    def test_book_flight_posts_to_api(self):
        """bookThisFlight POSTs to /api/v1/ai/book-flight."""
        src = open(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'routes_flights.py')).read()
        assert '/api/v1/ai/book-flight' in src
        assert 'JSON.stringify(d)' in src


# ============================================================
# AI Routes Registration Test
# ============================================================

class TestAIRoutesRegistration:
    """Verify AI routes are properly registered in server.py."""

    def test_ai_routes_registration_in_server(self):
        """server.py registers mystes_ai_api routes."""
        src = open(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'server.py')).read()
        assert 'register_mystes_ai_routes' in src
        assert 'from mystes_ai_api import' in src

    def test_book_flight_endpoint_exists(self, client):
        """The /api/v1/ai/book-flight endpoint exists (not 404)."""
        with app.app_context():
            # POST without auth should return 401, not 404
            resp = client.post('/api/v1/ai/book-flight', json={'test': True})
            assert resp.status_code != 404, f"book-flight endpoint returned 404 — AI routes not registered"
