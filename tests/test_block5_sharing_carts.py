"""
MYSTES Tests — Block 5 (Builds #228-229: Narrative Pitch + SharedCart)

Tests for:
- Narrative Pitch (#228): template-based per-guest personalization, scope handling,
  empty trips, admin-only guest narrative view
- SharedCart model (#229): create, to_dict, status flow, expiry
- SharedCart API (#229): create, list, view by token (no auth), update, share,
  pay (no auth), delete, access control, expiry handling
- Feature flag gating: all endpoints return 403 when flags disabled

Run: python3 -m pytest tests/test_block5_sharing_carts.py -v
"""

import json
import sys
import os
import pytest
from datetime import date, datetime, timezone, timedelta

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _root)
sys.path.insert(0, os.path.join(_root, 'picasso-sdk'))

from server import app, db, limiter
from models import (
    User, TripPlan, TripMember, TripGuest, TripParty,
    ItineraryItem, SharedCart, InviteLink, FeatureFlag,
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


def _login_client_as(c, user_id):
    """Log a test client in as a specific user via session injection."""
    with c.session_transaction() as sess:
        sess['_user_id'] = str(user_id)


def _create_user(email, name='Test User'):
    user = User(email=email, name=name, is_verified=True, is_active=True)
    user.set_password('TestPass1!')
    db.session.add(user)
    db.session.commit()
    return user


def _create_trip(creator_id, name='Test Trip', mode='collaborative', trip_type='trip'):
    trip = TripPlan(creator_id=creator_id, name=name, status='draft',
                    mode=mode, trip_type=trip_type)
    db.session.add(trip)
    db.session.commit()
    return trip


def _create_guest(trip_id, display_name='Alice', party_id=None,
                   user_id=None, role='viewer', rsvp_status='invited'):
    guest = TripGuest(
        trip_id=trip_id, party_id=party_id, user_id=user_id,
        display_name=display_name, role=role, rsvp_status=rsvp_status,
    )
    db.session.add(guest)
    db.session.commit()
    return guest


def _create_party(trip_id, name='The Smiths'):
    party = TripParty(trip_id=trip_id, name=name)
    db.session.add(party)
    db.session.commit()
    return party


def _create_item(trip_id, item_type='flight', date_val=None, position=0,
                  search_params=None, external_name=None, notes=None,
                  cached_price_usd=None, external_cost_usd=None,
                  scope='trip', scope_party_id=None, assigned_to_guest_id=None,
                  start_time=None):
    item = ItineraryItem(
        trip_id=trip_id, item_type=item_type,
        date=date_val, position=position,
        search_params_json=json.dumps(search_params) if search_params else None,
        external_name=external_name, notes=notes,
        cached_price_usd=cached_price_usd,
        external_cost_usd=external_cost_usd,
        scope=scope, scope_party_id=scope_party_id,
        assigned_to_guest_id=assigned_to_guest_id,
        start_time=start_time,
    )
    db.session.add(item)
    db.session.commit()
    return item


def _enable_flags(*flag_keys):
    """Enable feature flags for testing."""
    for key in flag_keys:
        existing = FeatureFlag.query.filter_by(flag_key=key).first()
        if existing:
            existing.is_enabled = True
        else:
            flag = FeatureFlag(
                flag_key=key, flag_name=key, description='test',
                layer=3, is_enabled=True,
            )
            db.session.add(flag)
    db.session.commit()


def _setup_trip_with_items(client_obj):
    """Create a user, trip, guests, items for narrative/cart tests. Return dict of IDs."""
    user = _create_user('builder@t.com', 'Builder')
    trip = _create_trip(user.id, name='Cancun Trip')
    trip.start_date = date(2027, 6, 5)
    trip.end_date = date(2027, 6, 8)
    db.session.commit()

    party = _create_party(trip.id, 'The Smiths')
    dad = _create_guest(trip.id, 'Dad', party_id=party.id, user_id=user.id, role='owner')

    mom_user = _create_user('mom@t.com', 'Mom User')
    mom = _create_guest(trip.id, 'Mom', party_id=party.id, user_id=mom_user.id)

    kid = _create_guest(trip.id, 'Daughter', party_id=party.id)

    # Day 1: Arrival flight
    flight = _create_item(trip.id, 'flight', date(2027, 6, 5), 0,
                          search_params={'origin': 'LAX', 'destination': 'CUN',
                                         'date': '2027-06-05', 'passengers': 3},
                          cached_price_usd=800.0)
    # Day 1: Hotel check-in
    hotel = _create_item(trip.id, 'hotel', date(2027, 6, 5), 1,
                         external_name='Grand Hyatt Cancun',
                         cached_price_usd=350.0)
    # Day 2: Activity
    activity = _create_item(trip.id, 'activity', date(2027, 6, 6), 0,
                            external_name='Snorkeling at Isla Mujeres',
                            cached_price_usd=120.0, start_time='09:00')
    # Day 2: Restaurant
    restaurant = _create_item(trip.id, 'restaurant', date(2027, 6, 6), 1,
                              external_name='La Habichuela', start_time='19:00')
    # Day 3: Departure
    departure = _create_item(trip.id, 'flight', date(2027, 6, 8), 0,
                             search_params={'origin': 'CUN', 'destination': 'LAX',
                                            'date': '2027-06-08', 'passengers': 3},
                             cached_price_usd=750.0)

    db.session.commit()
    _login_client_as(client_obj, user.id)

    return {
        'user_id': user.id, 'trip_id': trip.id, 'party_id': party.id,
        'dad_id': dad.id, 'mom_id': mom.id, 'mom_user_id': mom_user.id, 'kid_id': kid.id,
        'flight_id': flight.id, 'hotel_id': hotel.id, 'activity_id': activity.id,
        'restaurant_id': restaurant.id, 'departure_id': departure.id,
    }


# ================================================================
# Part 1: Narrative Pitch Generator — Build #228
# ================================================================

class TestNarrativeEngine:
    """Test the template-based narrative builder logic."""

    def test_narrative_empty_trip(self, client):
        """Empty trip returns placeholder narrative."""
        with app.app_context():
            _enable_flags('narrative_pitch')
            user = _create_user('u@t.com')
            trip = _create_trip(user.id, name='Empty Trip')
            tid = trip.id
            _login_client_as(client, user.id)

        r = client.get(f'/api/trips/{tid}/narrative')
        assert r.status_code == 200
        data = r.get_json()
        assert data['status'] == 'ok'
        assert 'being planned' in data['narrative']
        assert data['item_count'] == 0
        assert data['days'] == []

    def test_narrative_with_items(self, client):
        """Full trip generates day-by-day narrative."""
        with app.app_context():
            _enable_flags('narrative_pitch')
            ctx = _setup_trip_with_items(client)
            tid = ctx['trip_id']

        r = client.get(f'/api/trips/{tid}/narrative')
        assert r.status_code == 200
        data = r.get_json()
        assert data['status'] == 'ok'
        assert data['item_count'] == 5
        assert len(data['days']) >= 3
        # Narrative text should mention the destination
        assert 'CUN' in data['narrative'] or 'destination' in data['narrative'].lower() or 'Day 1' in data['narrative']

    def test_narrative_perspective_you(self, client):
        """Current user's name replaced with 'You' in narrative."""
        with app.app_context():
            _enable_flags('narrative_pitch')
            ctx = _setup_trip_with_items(client)
            tid = ctx['trip_id']

        r = client.get(f'/api/trips/{tid}/narrative')
        data = r.get_json()
        assert data['perspective'] == 'Dad'
        # The builder is "Dad" guest — should see "You" in narrative
        assert 'You' in data['narrative']

    def test_narrative_guest_perspective(self, client):
        """Admin can view narrative from another guest's perspective."""
        with app.app_context():
            _enable_flags('narrative_pitch')
            ctx = _setup_trip_with_items(client)
            tid = ctx['trip_id']
            mom_gid = ctx['mom_id']

        r = client.get(f'/api/trips/{tid}/narrative/{mom_gid}')
        assert r.status_code == 200
        data = r.get_json()
        assert data['perspective'] == 'Mom'
        assert data['guest_id'] == mom_gid

    def test_narrative_guest_perspective_non_admin(self, client):
        """Non-admin cannot view other guest's narrative."""
        with app.app_context():
            _enable_flags('narrative_pitch')
            ctx = _setup_trip_with_items(client)
            tid = ctx['trip_id']
            dad_gid = ctx['dad_id']
            # Login as mom (not the creator)
            _login_client_as(client, ctx['mom_user_id'])

        r = client.get(f'/api/trips/{tid}/narrative/{dad_gid}')
        assert r.status_code == 403

    def test_narrative_guest_not_found(self, client):
        """Invalid guest_id returns 404."""
        with app.app_context():
            _enable_flags('narrative_pitch')
            ctx = _setup_trip_with_items(client)
            tid = ctx['trip_id']

        r = client.get(f'/api/trips/{tid}/narrative/9999')
        assert r.status_code == 404

    def test_narrative_trip_not_found(self, client):
        """Non-existent trip returns 404."""
        with app.app_context():
            _enable_flags('narrative_pitch')
            user = _create_user('u@t.com')
            _login_client_as(client, user.id)

        r = client.get('/api/trips/9999/narrative')
        assert r.status_code == 404

    def test_narrative_party_scoped_item(self, client):
        """Party-scoped item mentions only party members."""
        with app.app_context():
            _enable_flags('narrative_pitch')
            user = _create_user('u@t.com', 'Planner')
            trip = _create_trip(user.id)
            party = _create_party(trip.id, 'Spa Group')
            g1 = _create_guest(trip.id, 'Alice', party_id=party.id, user_id=user.id)
            g2 = _create_guest(trip.id, 'Bob')  # Not in party

            _create_item(trip.id, 'activity', date(2027, 6, 5), 0,
                         external_name='Couples Spa', scope='party',
                         scope_party_id=party.id)
            tid = trip.id
            _login_client_as(client, user.id)

        r = client.get(f'/api/trips/{tid}/narrative')
        data = r.get_json()
        # Party-scoped item should mention Alice (as "You") but not Bob
        narrative = data['narrative']
        assert 'Bob' not in narrative

    def test_narrative_individual_scoped_item(self, client):
        """Individual-scoped item mentions only the assigned guest."""
        with app.app_context():
            _enable_flags('narrative_pitch')
            user = _create_user('u@t.com', 'Planner')
            trip = _create_trip(user.id)
            alice = _create_guest(trip.id, 'Alice', user_id=user.id)
            bob = _create_guest(trip.id, 'Bob')

            _create_item(trip.id, 'custom', date(2027, 6, 5), 0,
                         external_name='Solo Hiking Trail', scope='individual',
                         assigned_to_guest_id=bob.id)
            tid = trip.id
            _login_client_as(client, user.id)

        r = client.get(f'/api/trips/{tid}/narrative')
        data = r.get_json()
        # Individual item assigned to Bob — planner sees "Bob" not "You"
        assert 'Bob' in data['narrative']

    def test_narrative_car_item(self, client):
        """Car rental item gets car template."""
        with app.app_context():
            _enable_flags('narrative_pitch')
            user = _create_user('u@t.com')
            trip = _create_trip(user.id)
            _create_guest(trip.id, 'Driver', user_id=user.id)
            _create_item(trip.id, 'car', date(2027, 6, 5), 0)
            tid = trip.id
            _login_client_as(client, user.id)

        r = client.get(f'/api/trips/{tid}/narrative')
        data = r.get_json()
        assert 'rental' in data['narrative'].lower()

    def test_narrative_dateless_items(self, client):
        """Items without dates appear in an 'Anytime' section."""
        with app.app_context():
            _enable_flags('narrative_pitch')
            user = _create_user('u@t.com')
            trip = _create_trip(user.id)
            _create_guest(trip.id, 'Traveler', user_id=user.id)
            _create_item(trip.id, 'custom', external_name='Pack sunscreen')
            tid = trip.id
            _login_client_as(client, user.id)

        r = client.get(f'/api/trips/{tid}/narrative')
        data = r.get_json()
        assert 'Anytime' in data['narrative'] or 'Pack sunscreen' in data['narrative']

    def test_narrative_destination_extraction(self, client):
        """Narrative extracts destination from flight search params."""
        with app.app_context():
            _enable_flags('narrative_pitch')
            user = _create_user('u@t.com')
            trip = _create_trip(user.id)
            _create_guest(trip.id, 'Flyer', user_id=user.id)
            _create_item(trip.id, 'flight', date(2027, 6, 5), 0,
                         search_params={'origin': 'JFK', 'destination': 'NRT'})
            tid = trip.id
            _login_client_as(client, user.id)

        r = client.get(f'/api/trips/{tid}/narrative')
        data = r.get_json()
        assert data['destination'] == 'NRT'


# ================================================================
# Part 2: Feature Flag Gating
# ================================================================

class TestFeatureFlagGating:
    """All endpoints return 403 when flags are disabled."""

    def test_narrative_flag_disabled(self, client):
        with app.app_context():
            user = _create_user('u@t.com')
            trip = _create_trip(user.id)
            tid = trip.id
            _login_client_as(client, user.id)

        r = client.get(f'/api/trips/{tid}/narrative')
        assert r.status_code == 403

    def test_narrative_guest_flag_disabled(self, client):
        with app.app_context():
            user = _create_user('u@t.com')
            trip = _create_trip(user.id)
            guest = _create_guest(trip.id, 'Alice')
            tid, gid = trip.id, guest.id
            _login_client_as(client, user.id)

        r = client.get(f'/api/trips/{tid}/narrative/{gid}')
        assert r.status_code == 403

    def test_create_cart_flag_disabled(self, client):
        with app.app_context():
            user = _create_user('u@t.com')
            trip = _create_trip(user.id)
            tid = trip.id
            _login_client_as(client, user.id)

        r = client.post(f'/api/trips/{tid}/carts', json={'title': 'Test'})
        assert r.status_code == 403

    def test_list_carts_flag_disabled(self, client):
        with app.app_context():
            user = _create_user('u@t.com')
            trip = _create_trip(user.id)
            tid = trip.id
            _login_client_as(client, user.id)

        r = client.get(f'/api/trips/{tid}/carts')
        assert r.status_code == 403

    def test_update_cart_flag_disabled(self, client):
        with app.app_context():
            user = _create_user('u@t.com')
            _login_client_as(client, user.id)

        r = client.put('/api/carts/sometoken', json={'title': 'X'})
        assert r.status_code == 403

    def test_share_cart_flag_disabled(self, client):
        with app.app_context():
            user = _create_user('u@t.com')
            _login_client_as(client, user.id)

        r = client.post('/api/carts/sometoken/share')
        assert r.status_code == 403

    def test_delete_cart_flag_disabled(self, client):
        with app.app_context():
            user = _create_user('u@t.com')
            _login_client_as(client, user.id)

        r = client.delete('/api/carts/sometoken')
        assert r.status_code == 403


# ================================================================
# Part 3: SharedCart Model
# ================================================================

class TestSharedCartModel:
    """Test SharedCart model creation and to_dict."""

    def test_create_shared_cart(self):
        user = _create_user('u@t.com')
        trip = _create_trip(user.id)
        cart = SharedCart(
            cart_token='test123',
            trip_id=trip.id,
            builder_user_id=user.id,
            title='Japan Trip',
            message='Mom, can you pay?',
            items_json='[]',
            total_estimated_usd=1500.0,
        )
        db.session.add(cart)
        db.session.commit()
        assert cart.id is not None
        assert cart.payment_status == 'draft'
        assert cart.cart_token == 'test123'

    def test_shared_cart_to_dict(self):
        user = _create_user('u@t.com')
        trip = _create_trip(user.id)
        items = [{'item_id': 1, 'name': 'Flight', 'price_usd': 800}]
        cart = SharedCart(
            cart_token='abc123',
            trip_id=trip.id,
            builder_user_id=user.id,
            title='Test Cart',
            message='Please pay',
            items_json=json.dumps(items),
            total_estimated_usd=800.0,
        )
        db.session.add(cart)
        db.session.commit()

        d = cart.to_dict()
        assert d['cart_token'] == 'abc123'
        assert d['title'] == 'Test Cart'
        assert d['total_estimated_usd'] == 800.0
        assert len(d['items']) == 1
        # Message NOT included by default
        assert 'message' not in d

    def test_shared_cart_to_dict_with_message(self):
        user = _create_user('u@t.com')
        trip = _create_trip(user.id)
        cart = SharedCart(
            cart_token='msg123',
            trip_id=trip.id,
            builder_user_id=user.id,
            title='Cart With Message',
            message='Hey Mom!',
            items_json='[]',
        )
        db.session.add(cart)
        db.session.commit()

        d = cart.to_dict(include_message=True)
        assert d['message'] == 'Hey Mom!'

    def test_shared_cart_status_constants(self):
        assert 'draft' in SharedCart.STATUSES
        assert 'shared' in SharedCart.STATUSES
        assert 'paid' in SharedCart.STATUSES
        assert 'expired' in SharedCart.STATUSES


# ================================================================
# Part 4: SharedCart Create + List API
# ================================================================

class TestCreateSharedCartAPI:
    """Test creating shared carts from trip items."""

    def test_create_cart_basic(self, client):
        with app.app_context():
            _enable_flags('shared_cart')
            user = _create_user('u@t.com')
            trip = _create_trip(user.id)
            item = _create_item(trip.id, 'flight', cached_price_usd=800.0)
            tid, iid = trip.id, item.id
            _login_client_as(client, user.id)

        r = client.post(f'/api/trips/{tid}/carts', json={
            'title': 'Flights for Mom',
            'message': 'Can you pay for this?',
            'item_ids': [iid],
        })
        assert r.status_code == 200
        data = r.get_json()
        assert data['status'] == 'ok'
        assert data['cart']['title'] == 'Flights for Mom'
        assert data['cart']['total_estimated_usd'] == 800.0
        assert data['cart']['payment_status'] == 'draft'
        assert len(data['cart']['items']) == 1

    def test_create_cart_no_title(self, client):
        with app.app_context():
            _enable_flags('shared_cart')
            user = _create_user('u@t.com')
            trip = _create_trip(user.id)
            tid = trip.id
            _login_client_as(client, user.id)

        r = client.post(f'/api/trips/{tid}/carts', json={})
        assert r.status_code == 400

    def test_create_cart_empty_items(self, client):
        """Cart with no items is allowed (items added later)."""
        with app.app_context():
            _enable_flags('shared_cart')
            user = _create_user('u@t.com')
            trip = _create_trip(user.id)
            tid = trip.id
            _login_client_as(client, user.id)

        r = client.post(f'/api/trips/{tid}/carts', json={'title': 'Placeholder Cart'})
        assert r.status_code == 200
        data = r.get_json()
        assert data['cart']['total_estimated_usd'] == 0.0

    def test_create_cart_multiple_items(self, client):
        with app.app_context():
            _enable_flags('shared_cart')
            user = _create_user('u@t.com')
            trip = _create_trip(user.id)
            i1 = _create_item(trip.id, 'flight', cached_price_usd=800.0)
            i2 = _create_item(trip.id, 'hotel', external_cost_usd=350.0)
            tid, iid1, iid2 = trip.id, i1.id, i2.id
            _login_client_as(client, user.id)

        r = client.post(f'/api/trips/{tid}/carts', json={
            'title': 'Full Trip',
            'item_ids': [iid1, iid2],
        })
        assert r.status_code == 200
        data = r.get_json()
        assert data['cart']['total_estimated_usd'] == 1150.0
        assert len(data['cart']['items']) == 2

    def test_create_cart_ignores_wrong_trip_items(self, client):
        """Items from a different trip are silently ignored."""
        with app.app_context():
            _enable_flags('shared_cart')
            user = _create_user('u@t.com')
            trip1 = _create_trip(user.id, name='Trip 1')
            trip2 = _create_trip(user.id, name='Trip 2')
            item_other = _create_item(trip2.id, 'flight', cached_price_usd=999.0)
            tid1, other_iid = trip1.id, item_other.id
            _login_client_as(client, user.id)

        r = client.post(f'/api/trips/{tid1}/carts', json={
            'title': 'Wrong Items',
            'item_ids': [other_iid],
        })
        assert r.status_code == 200
        data = r.get_json()
        assert data['cart']['total_estimated_usd'] == 0.0
        assert len(data['cart']['items']) == 0

    def test_create_cart_viewer_denied(self, client):
        """Viewer cannot create carts (requires edit access)."""
        with app.app_context():
            _enable_flags('shared_cart')
            owner = _create_user('owner@t.com', 'Owner')
            viewer = _create_user('viewer@t.com', 'Viewer')
            trip = _create_trip(owner.id)
            TripMember(trip_plan_id=trip.id, user_id=viewer.id, role='viewer')
            member = TripMember(trip_plan_id=trip.id, user_id=viewer.id, role='viewer')
            db.session.add(member)
            db.session.commit()
            tid = trip.id
            _login_client_as(client, viewer.id)

        r = client.post(f'/api/trips/{tid}/carts', json={'title': 'Nope'})
        assert r.status_code == 403


class TestListSharedCartsAPI:
    """Test listing shared carts for a trip."""

    def test_list_carts_empty(self, client):
        with app.app_context():
            _enable_flags('shared_cart')
            user = _create_user('u@t.com')
            trip = _create_trip(user.id)
            tid = trip.id
            _login_client_as(client, user.id)

        r = client.get(f'/api/trips/{tid}/carts')
        assert r.status_code == 200
        data = r.get_json()
        assert data['count'] == 0
        assert data['carts'] == []

    def test_list_carts_with_data(self, client):
        with app.app_context():
            _enable_flags('shared_cart')
            user = _create_user('u@t.com')
            trip = _create_trip(user.id)
            c1 = SharedCart(cart_token='tok1', trip_id=trip.id,
                            builder_user_id=user.id, title='Cart 1', items_json='[]')
            c2 = SharedCart(cart_token='tok2', trip_id=trip.id,
                            builder_user_id=user.id, title='Cart 2', items_json='[]')
            db.session.add_all([c1, c2])
            db.session.commit()
            tid = trip.id
            _login_client_as(client, user.id)

        r = client.get(f'/api/trips/{tid}/carts')
        assert r.status_code == 200
        data = r.get_json()
        assert data['count'] == 2


# ================================================================
# Part 5: SharedCart View by Token (No Auth)
# ================================================================

class TestViewCartByTokenAPI:
    """Test viewing a shared cart by token — no auth required."""

    def test_view_shared_cart(self, client):
        with app.app_context():
            user = _create_user('u@t.com')
            trip = _create_trip(user.id)
            cart = SharedCart(
                cart_token='viewme', trip_id=trip.id,
                builder_user_id=user.id, title='Shared Cart',
                message='Pay this!', items_json='[]',
                payment_status='shared',
                expires_at=datetime.now(timezone.utc) + timedelta(hours=72),
            )
            db.session.add(cart)
            db.session.commit()

        # Anonymous client — no login
        anon = app.test_client()
        r = anon.get('/api/carts/viewme')
        assert r.status_code == 200
        data = r.get_json()
        assert data['cart']['title'] == 'Shared Cart'
        assert data['cart']['message'] == 'Pay this!'

    def test_view_draft_cart_anon_denied(self, client):
        """Anonymous users cannot see draft carts."""
        with app.app_context():
            user = _create_user('u@t.com')
            trip = _create_trip(user.id)
            cart = SharedCart(
                cart_token='draftonly', trip_id=trip.id,
                builder_user_id=user.id, title='Draft',
                items_json='[]', payment_status='draft',
            )
            db.session.add(cart)
            db.session.commit()

        anon = app.test_client()
        r = anon.get('/api/carts/draftonly')
        assert r.status_code == 403

    def test_view_draft_cart_builder_ok(self, client):
        """Builder can view their own draft cart."""
        with app.app_context():
            user = _create_user('u@t.com')
            trip = _create_trip(user.id)
            cart = SharedCart(
                cart_token='mydraft', trip_id=trip.id,
                builder_user_id=user.id, title='My Draft',
                items_json='[]', payment_status='draft',
            )
            db.session.add(cart)
            db.session.commit()
            _login_client_as(client, user.id)

        r = client.get('/api/carts/mydraft')
        assert r.status_code == 200

    def test_view_expired_cart(self, client):
        """Expired cart returns 410 Gone."""
        with app.app_context():
            user = _create_user('u@t.com')
            trip = _create_trip(user.id)
            cart = SharedCart(
                cart_token='expired1', trip_id=trip.id,
                builder_user_id=user.id, title='Old Cart',
                items_json='[]', payment_status='shared',
                expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
            )
            db.session.add(cart)
            db.session.commit()

        anon = app.test_client()
        r = anon.get('/api/carts/expired1')
        assert r.status_code == 410

    def test_view_nonexistent_cart(self, client):
        r = client.get('/api/carts/doesnotexist')
        assert r.status_code == 404


# ================================================================
# Part 6: SharedCart Update API
# ================================================================

class TestUpdateCartAPI:
    """Test updating a shared cart."""

    def test_update_cart_title(self, client):
        with app.app_context():
            _enable_flags('shared_cart')
            user = _create_user('u@t.com')
            trip = _create_trip(user.id)
            cart = SharedCart(
                cart_token='upd1', trip_id=trip.id,
                builder_user_id=user.id, title='Original',
                items_json='[]',
            )
            db.session.add(cart)
            db.session.commit()
            _login_client_as(client, user.id)

        r = client.put('/api/carts/upd1', json={'title': 'Updated Title'})
        assert r.status_code == 200
        data = r.get_json()
        assert data['cart']['title'] == 'Updated Title'

    def test_update_cart_items(self, client):
        with app.app_context():
            _enable_flags('shared_cart')
            user = _create_user('u@t.com')
            trip = _create_trip(user.id)
            item = _create_item(trip.id, 'hotel', external_cost_usd=500.0,
                                external_name='Beach Resort')
            cart = SharedCart(
                cart_token='upd2', trip_id=trip.id,
                builder_user_id=user.id, title='Cart',
                items_json='[]', total_estimated_usd=0.0,
            )
            db.session.add(cart)
            db.session.commit()
            iid = item.id
            _login_client_as(client, user.id)

        r = client.put('/api/carts/upd2', json={'item_ids': [iid]})
        assert r.status_code == 200
        data = r.get_json()
        assert data['cart']['total_estimated_usd'] == 500.0
        assert len(data['cart']['items']) == 1

    def test_update_cart_not_builder(self, client):
        """Non-builder cannot update cart."""
        with app.app_context():
            _enable_flags('shared_cart')
            builder = _create_user('builder@t.com')
            other = _create_user('other@t.com')
            trip = _create_trip(builder.id)
            cart = SharedCart(
                cart_token='upd3', trip_id=trip.id,
                builder_user_id=builder.id, title='X',
                items_json='[]',
            )
            db.session.add(cart)
            db.session.commit()
            _login_client_as(client, other.id)

        r = client.put('/api/carts/upd3', json={'title': 'Hacked'})
        assert r.status_code == 403

    def test_update_paid_cart_rejected(self, client):
        """Paid carts cannot be updated."""
        with app.app_context():
            _enable_flags('shared_cart')
            user = _create_user('u@t.com')
            trip = _create_trip(user.id)
            cart = SharedCart(
                cart_token='upd4', trip_id=trip.id,
                builder_user_id=user.id, title='Paid',
                items_json='[]', payment_status='paid',
            )
            db.session.add(cart)
            db.session.commit()
            _login_client_as(client, user.id)

        r = client.put('/api/carts/upd4', json={'title': 'Too Late'})
        assert r.status_code == 400


# ================================================================
# Part 7: Share Cart + InviteLink Generation
# ================================================================

class TestShareCartAPI:
    """Test sharing a cart and generating InviteLink."""

    def test_share_cart_creates_invite(self, client):
        with app.app_context():
            _enable_flags('shared_cart')
            user = _create_user('u@t.com')
            trip = _create_trip(user.id)
            cart = SharedCart(
                cart_token='share1', trip_id=trip.id,
                builder_user_id=user.id, title='Share Me',
                message='Pay up!', items_json='[]',
            )
            db.session.add(cart)
            db.session.commit()
            _login_client_as(client, user.id)

        r = client.post('/api/carts/share1/share')
        assert r.status_code == 200
        data = r.get_json()
        assert data['cart']['payment_status'] == 'shared'
        assert 'share_token' in data
        assert data['share_url'].startswith('/i/')

        # Verify InviteLink was created
        with app.app_context():
            invite = InviteLink.query.filter_by(link_type='cart_checkout').first()
            assert invite is not None
            assert invite.permissions == 'can_pay'

    def test_share_cart_already_shared(self, client):
        """Re-sharing a shared cart is allowed (idempotent)."""
        with app.app_context():
            _enable_flags('shared_cart')
            user = _create_user('u@t.com')
            trip = _create_trip(user.id)
            cart = SharedCart(
                cart_token='share2', trip_id=trip.id,
                builder_user_id=user.id, title='Already Shared',
                items_json='[]', payment_status='shared',
            )
            db.session.add(cart)
            db.session.commit()
            _login_client_as(client, user.id)

        r = client.post('/api/carts/share2/share')
        assert r.status_code == 200

    def test_share_paid_cart_rejected(self, client):
        """Cannot share a paid cart."""
        with app.app_context():
            _enable_flags('shared_cart')
            user = _create_user('u@t.com')
            trip = _create_trip(user.id)
            cart = SharedCart(
                cart_token='share3', trip_id=trip.id,
                builder_user_id=user.id, title='Paid',
                items_json='[]', payment_status='paid',
            )
            db.session.add(cart)
            db.session.commit()
            _login_client_as(client, user.id)

        r = client.post('/api/carts/share3/share')
        assert r.status_code == 400

    def test_share_cart_not_builder(self, client):
        """Non-builder cannot share."""
        with app.app_context():
            _enable_flags('shared_cart')
            builder = _create_user('builder@t.com')
            other = _create_user('other@t.com')
            trip = _create_trip(builder.id)
            cart = SharedCart(
                cart_token='share4', trip_id=trip.id,
                builder_user_id=builder.id, title='X',
                items_json='[]',
            )
            db.session.add(cart)
            db.session.commit()
            _login_client_as(client, other.id)

        r = client.post('/api/carts/share4/share')
        assert r.status_code == 403


# ================================================================
# Part 8: Pay Cart (No Auth — Guest Access)
# ================================================================

class TestPayCartAPI:
    """Test paying for a shared cart — no auth required."""

    def test_pay_shared_cart(self, client):
        with app.app_context():
            user = _create_user('u@t.com')
            trip = _create_trip(user.id)
            cart = SharedCart(
                cart_token='pay1', trip_id=trip.id,
                builder_user_id=user.id, title='Pay Me',
                items_json='[]', payment_status='shared',
                total_estimated_usd=800.0,
                expires_at=datetime.now(timezone.utc) + timedelta(hours=72),
            )
            db.session.add(cart)
            db.session.commit()

        anon = app.test_client()
        r = anon.post('/api/carts/pay1/pay', json={
            'payer_email': 'mom@gmail.com',
            'payer_name': 'Mom',
        })
        assert r.status_code == 200
        data = r.get_json()
        assert data['cart']['payment_status'] == 'paid'
        assert data['cart']['payer_email'] == 'mom@gmail.com'

    def test_pay_cart_no_email(self, client):
        with app.app_context():
            user = _create_user('u@t.com')
            trip = _create_trip(user.id)
            cart = SharedCart(
                cart_token='pay2', trip_id=trip.id,
                builder_user_id=user.id, title='X',
                items_json='[]', payment_status='shared',
                expires_at=datetime.now(timezone.utc) + timedelta(hours=72),
            )
            db.session.add(cart)
            db.session.commit()

        anon = app.test_client()
        r = anon.post('/api/carts/pay2/pay', json={})
        assert r.status_code == 400

    def test_pay_draft_cart_rejected(self, client):
        """Cannot pay for a draft (unshared) cart."""
        with app.app_context():
            user = _create_user('u@t.com')
            trip = _create_trip(user.id)
            cart = SharedCart(
                cart_token='pay3', trip_id=trip.id,
                builder_user_id=user.id, title='Draft',
                items_json='[]', payment_status='draft',
            )
            db.session.add(cart)
            db.session.commit()

        anon = app.test_client()
        r = anon.post('/api/carts/pay3/pay', json={'payer_email': 'x@x.com'})
        assert r.status_code == 400

    def test_pay_expired_cart(self, client):
        """Expired cart returns 410 on payment attempt."""
        with app.app_context():
            user = _create_user('u@t.com')
            trip = _create_trip(user.id)
            cart = SharedCart(
                cart_token='pay4', trip_id=trip.id,
                builder_user_id=user.id, title='Expired',
                items_json='[]', payment_status='shared',
                expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
            )
            db.session.add(cart)
            db.session.commit()

        anon = app.test_client()
        r = anon.post('/api/carts/pay4/pay', json={'payer_email': 'x@x.com'})
        assert r.status_code == 410

    def test_pay_already_paid_cart(self, client):
        """Cannot double-pay a cart."""
        with app.app_context():
            user = _create_user('u@t.com')
            trip = _create_trip(user.id)
            cart = SharedCart(
                cart_token='pay5', trip_id=trip.id,
                builder_user_id=user.id, title='Already Paid',
                items_json='[]', payment_status='paid',
            )
            db.session.add(cart)
            db.session.commit()

        anon = app.test_client()
        r = anon.post('/api/carts/pay5/pay', json={'payer_email': 'x@x.com'})
        assert r.status_code == 400


# ================================================================
# Part 9: Delete Cart API
# ================================================================

class TestDeleteCartAPI:
    """Test deleting draft carts."""

    def test_delete_draft_cart(self, client):
        with app.app_context():
            _enable_flags('shared_cart')
            user = _create_user('u@t.com')
            trip = _create_trip(user.id)
            cart = SharedCart(
                cart_token='del1', trip_id=trip.id,
                builder_user_id=user.id, title='Delete Me',
                items_json='[]',
            )
            db.session.add(cart)
            db.session.commit()
            _login_client_as(client, user.id)

        r = client.delete('/api/carts/del1')
        assert r.status_code == 200

        with app.app_context():
            assert SharedCart.query.filter_by(cart_token='del1').first() is None

    def test_delete_shared_cart_rejected(self, client):
        """Cannot delete a shared (non-draft) cart."""
        with app.app_context():
            _enable_flags('shared_cart')
            user = _create_user('u@t.com')
            trip = _create_trip(user.id)
            cart = SharedCart(
                cart_token='del2', trip_id=trip.id,
                builder_user_id=user.id, title='Shared',
                items_json='[]', payment_status='shared',
            )
            db.session.add(cart)
            db.session.commit()
            _login_client_as(client, user.id)

        r = client.delete('/api/carts/del2')
        assert r.status_code == 400

    def test_delete_cart_not_builder(self, client):
        """Non-builder cannot delete cart."""
        with app.app_context():
            _enable_flags('shared_cart')
            builder = _create_user('builder@t.com')
            other = _create_user('other@t.com')
            trip = _create_trip(builder.id)
            cart = SharedCart(
                cart_token='del3', trip_id=trip.id,
                builder_user_id=builder.id, title='X',
                items_json='[]',
            )
            db.session.add(cart)
            db.session.commit()
            _login_client_as(client, other.id)

        r = client.delete('/api/carts/del3')
        assert r.status_code == 403


# ================================================================
# Part 10: Access Control
# ================================================================

class TestAccessControl:
    """Cross-cutting access control tests."""

    def test_unauthenticated_create_cart(self, client):
        """Unauthenticated user cannot create carts."""
        r = client.post('/api/trips/1/carts', json={'title': 'Test'})
        assert r.status_code in (302, 401)

    def test_unauthenticated_narrative(self, client):
        """Unauthenticated user cannot access narrative."""
        r = client.get('/api/trips/1/narrative')
        assert r.status_code in (302, 401)

    def test_nonmember_cannot_create_cart(self, client):
        """User not in trip cannot create carts."""
        with app.app_context():
            _enable_flags('shared_cart')
            owner = _create_user('owner@t.com')
            outsider = _create_user('outsider@t.com')
            trip = _create_trip(owner.id)
            tid = trip.id
            _login_client_as(client, outsider.id)

        r = client.post(f'/api/trips/{tid}/carts', json={'title': 'Hack'})
        assert r.status_code == 403

    def test_nonmember_cannot_view_narrative(self, client):
        """User not in trip cannot view narrative."""
        with app.app_context():
            _enable_flags('narrative_pitch')
            owner = _create_user('owner@t.com')
            outsider = _create_user('outsider@t.com')
            trip = _create_trip(owner.id)
            tid = trip.id
            _login_client_as(client, outsider.id)

        r = client.get(f'/api/trips/{tid}/narrative')
        assert r.status_code == 403

    def test_trip_not_found_cart(self, client):
        with app.app_context():
            _enable_flags('shared_cart')
            user = _create_user('u@t.com')
            _login_client_as(client, user.id)

        r = client.post('/api/trips/9999/carts', json={'title': 'X'})
        assert r.status_code == 404


# ================================================================
# Part 11: Feature Flag Registration
# ================================================================

class TestFeatureFlagRegistration:
    """Test that new feature flags are registered."""

    def test_narrative_pitch_flag_exists(self):
        from models import FeatureFlag
        FeatureFlag.init_default_flags()
        flag = FeatureFlag.query.filter_by(flag_key='narrative_pitch').first()
        assert flag is not None
        assert flag.layer == 3
        assert flag.is_enabled is False

    def test_shared_cart_flag_exists(self):
        from models import FeatureFlag
        FeatureFlag.init_default_flags()
        flag = FeatureFlag.query.filter_by(flag_key='shared_cart').first()
        assert flag is not None
        assert flag.layer == 3
        assert flag.is_enabled is False
