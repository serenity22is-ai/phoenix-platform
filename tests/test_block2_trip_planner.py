"""
MYSTES Tests — Block 2 (Builds #221-223: Trip Planner Engine)

Tests for:
- TripParty model (Build #221): create, to_dict, party types
- TripGuest model (Build #221): create, roles, RSVP statuses, to_dict, flexible dates
- ItineraryItem model (Build #222): create, search params JSON, scopes, statuses, to_dict
- ItineraryVote + ItemComment models (Build #224 prep): create, unique constraint, threading
- Party API endpoints: POST/GET/PUT/DELETE /api/trips/<id>/parties
- Guest API endpoints: POST/GET/PUT/DELETE /api/trips/<id>/guests, RSVP
- Itinerary API endpoints: POST/GET/PUT/DELETE /api/trips/<id>/itinerary, status change
- Scope breakdown (Build #223): cost allocation across trip/party/individual/custom
- Settlement calculator (Build #223): who owes what per party

Run: python3 -m pytest tests/test_block2_trip_planner.py -v
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
    User, TripPlan, TripMember, TripParty, TripGuest,
    ItineraryItem, ItineraryVote, ItemComment,
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
    """Authenticated test client with a trip already created."""
    with app.app_context():
        user = User(
            email='planner@example.com',
            name='Trip Planner',
            is_verified=True,
            is_active=True,
        )
        user.set_password('PlannerPass1!')
        db.session.add(user)
        db.session.commit()

    client.post('/login', data={
        'email': 'planner@example.com',
        'password': 'PlannerPass1!',
    }, follow_redirects=True)
    yield client


def _get_user(email='planner@example.com'):
    return User.query.filter_by(email=email).first()


def _create_viewer_user():
    """Create a second user for access control tests."""
    user = User(email='viewer@example.com', name='Viewer User',
                is_verified=True, is_active=True)
    user.set_password('ViewerPass1!')
    db.session.add(user)
    db.session.commit()
    return user


def _login_client_as(c, user_id):
    """Log a test client in as a specific user via session injection."""
    with c.session_transaction() as sess:
        sess['_user_id'] = str(user_id)


def _create_trip(creator_id, name='Test Trip'):
    trip = TripPlan(creator_id=creator_id, name=name, status='draft')
    db.session.add(trip)
    db.session.commit()
    return trip


def _create_party(trip_id, name='The Smiths', party_type='attendee', budget_usd=None):
    party = TripParty(trip_id=trip_id, name=name, party_type=party_type, budget_usd=budget_usd)
    db.session.add(party)
    db.session.commit()
    return party


def _create_guest(trip_id, display_name='Alice', party_id=None, user_id=None, role='viewer'):
    guest = TripGuest(
        trip_id=trip_id, party_id=party_id, user_id=user_id,
        display_name=display_name, role=role,
    )
    db.session.add(guest)
    db.session.commit()
    return guest


# ================================================================
# Part 1: TripParty Model (Build #221)
# ================================================================

class TestTripPartyModel:
    """Test TripParty model creation and serialization."""

    def test_create_party(self):
        user = User(email='u@t.com', name='U', is_verified=True, is_active=True)
        user.set_password('x')
        db.session.add(user)
        db.session.commit()
        trip = _create_trip(user.id)

        party = TripParty(trip_id=trip.id, name='The Smiths', party_type='attendee')
        db.session.add(party)
        db.session.commit()

        assert party.id is not None
        assert party.name == 'The Smiths'
        assert party.party_type == 'attendee'
        assert party.payer_guest_id is None
        assert party.budget_usd is None

    def test_party_to_dict(self):
        user = User(email='u@t.com', name='U', is_verified=True, is_active=True)
        user.set_password('x')
        db.session.add(user)
        db.session.commit()
        trip = _create_trip(user.id)
        party = _create_party(trip.id, 'Family A', budget_usd=2000.0)

        d = party.to_dict()
        assert d['name'] == 'Family A'
        assert d['party_type'] == 'attendee'
        assert d['budget_usd'] == 2000.0
        assert d['guest_count'] == 0
        assert d['created_at'] is not None

    def test_party_sponsor_type(self):
        user = User(email='u@t.com', name='U', is_verified=True, is_active=True)
        user.set_password('x')
        db.session.add(user)
        db.session.commit()
        trip = _create_trip(user.id)

        party = TripParty(trip_id=trip.id, name='Corp Sponsor', party_type='sponsor')
        db.session.add(party)
        db.session.commit()

        assert party.party_type == 'sponsor'

    def test_party_guest_count(self):
        user = User(email='u@t.com', name='U', is_verified=True, is_active=True)
        user.set_password('x')
        db.session.add(user)
        db.session.commit()
        trip = _create_trip(user.id)
        party = _create_party(trip.id)

        _create_guest(trip.id, 'Alice', party_id=party.id)
        _create_guest(trip.id, 'Bob', party_id=party.id)

        d = party.to_dict()
        assert d['guest_count'] == 2

    def test_party_trip_relationship(self):
        user = User(email='u@t.com', name='U', is_verified=True, is_active=True)
        user.set_password('x')
        db.session.add(user)
        db.session.commit()
        trip = _create_trip(user.id)
        _create_party(trip.id, 'P1')
        _create_party(trip.id, 'P2')

        assert trip.parties.count() == 2


# ================================================================
# Part 2: TripGuest Model (Build #221)
# ================================================================

class TestTripGuestModel:
    """Test TripGuest model creation, roles, RSVP, and dates."""

    def test_create_guest_minimal(self):
        user = User(email='u@t.com', name='U', is_verified=True, is_active=True)
        user.set_password('x')
        db.session.add(user)
        db.session.commit()
        trip = _create_trip(user.id)

        guest = TripGuest(trip_id=trip.id, display_name='Alice')
        db.session.add(guest)
        db.session.commit()

        assert guest.id is not None
        assert guest.display_name == 'Alice'
        assert guest.role == 'viewer'
        assert guest.rsvp_status == 'invited'
        assert guest.payment_status == 'unpaid'
        assert guest.user_id is None  # non-MYSTES guest

    def test_guest_roles(self):
        assert 'owner' in TripGuest.ROLES
        assert 'admin' in TripGuest.ROLES
        assert 'editor' in TripGuest.ROLES
        assert 'viewer' in TripGuest.ROLES
        assert 'payer' in TripGuest.ROLES

    def test_guest_rsvp_statuses(self):
        expected = ('invited', 'viewed', 'attending', 'declined', 'maybe', 'waitlisted', 'expired')
        assert TripGuest.RSVP_STATUSES == expected

    def test_guest_with_flexible_dates(self):
        user = User(email='u@t.com', name='U', is_verified=True, is_active=True)
        user.set_password('x')
        db.session.add(user)
        db.session.commit()
        trip = _create_trip(user.id)

        guest = TripGuest(
            trip_id=trip.id,
            display_name='Late Alice',
            arrival_date=date(2027, 6, 7),
            departure_date=date(2027, 6, 10),
        )
        db.session.add(guest)
        db.session.commit()

        d = guest.to_dict()
        assert d['arrival_date'] == '2027-06-07'
        assert d['departure_date'] == '2027-06-10'

    def test_guest_linked_to_user(self):
        user = User(email='u@t.com', name='U', is_verified=True, is_active=True)
        user.set_password('x')
        db.session.add(user)
        db.session.commit()
        trip = _create_trip(user.id)

        guest = _create_guest(trip.id, 'U', user_id=user.id)
        assert guest.user_id == user.id
        assert guest.to_dict()['user_id'] == user.id

    def test_guest_party_relationship(self):
        user = User(email='u@t.com', name='U', is_verified=True, is_active=True)
        user.set_password('x')
        db.session.add(user)
        db.session.commit()
        trip = _create_trip(user.id)
        party = _create_party(trip.id)
        guest = _create_guest(trip.id, 'Alice', party_id=party.id)

        assert guest.party_id == party.id
        assert guest.party.name == party.name

    def test_guest_to_dict(self):
        user = User(email='u@t.com', name='U', is_verified=True, is_active=True)
        user.set_password('x')
        db.session.add(user)
        db.session.commit()
        trip = _create_trip(user.id)
        guest = _create_guest(trip.id, 'Alice')

        d = guest.to_dict()
        assert d['display_name'] == 'Alice'
        assert d['role'] == 'viewer'
        assert d['rsvp_status'] == 'invited'
        assert d['payment_status'] == 'unpaid'
        assert d['created_at'] is not None


# ================================================================
# Part 3: ItineraryItem Model (Build #222)
# ================================================================

class TestItineraryItemModel:
    """Test ItineraryItem model with search params and scoping."""

    def test_create_flight_item(self):
        user = User(email='u@t.com', name='U', is_verified=True, is_active=True)
        user.set_password('x')
        db.session.add(user)
        db.session.commit()
        trip = _create_trip(user.id)

        item = ItineraryItem(
            trip_id=trip.id,
            item_type='flight',
            search_params_json=json.dumps({
                'origin': 'LAX',
                'destination': 'NRT',
                'date': '2027-06-05',
                'passengers': 2,
                'cabin': 'economy',
            }),
        )
        db.session.add(item)
        db.session.commit()

        assert item.id is not None
        assert item.item_type == 'flight'
        assert item.status == 'suggested'
        assert item.scope == 'trip'

    def test_item_types(self):
        expected = ('flight', 'hotel', 'activity', 'car', 'restaurant', 'custom')
        assert ItineraryItem.ITEM_TYPES == expected

    def test_item_scopes(self):
        expected = ('trip', 'party', 'individual', 'custom')
        assert ItineraryItem.SCOPES == expected

    def test_item_statuses(self):
        expected = ('suggested', 'approved', 'locked', 'booked', 'cancelled')
        assert ItineraryItem.STATUSES == expected

    def test_item_search_params_roundtrip(self):
        user = User(email='u@t.com', name='U', is_verified=True, is_active=True)
        user.set_password('x')
        db.session.add(user)
        db.session.commit()
        trip = _create_trip(user.id)

        params = {'origin': 'JFK', 'destination': 'LHR', 'date': '2027-07-01'}
        item = ItineraryItem(
            trip_id=trip.id,
            item_type='flight',
            search_params_json=json.dumps(params),
        )
        db.session.add(item)
        db.session.commit()

        d = item.to_dict()
        assert d['search_params'] == params

    def test_item_external_booking(self):
        user = User(email='u@t.com', name='U', is_verified=True, is_active=True)
        user.set_password('x')
        db.session.add(user)
        db.session.commit()
        trip = _create_trip(user.id)

        item = ItineraryItem(
            trip_id=trip.id,
            item_type='hotel',
            booking_source='external',
            external_name='Airbnb Villa',
            external_url='https://airbnb.com/rooms/12345',
            external_confirmation='ABC123',
            external_cost_usd=1500.0,
        )
        db.session.add(item)
        db.session.commit()

        d = item.to_dict()
        assert d['booking_source'] == 'external'
        assert d['external_name'] == 'Airbnb Villa'
        assert d['external_cost_usd'] == 1500.0

    def test_item_scope_custom_guest_ids(self):
        user = User(email='u@t.com', name='U', is_verified=True, is_active=True)
        user.set_password('x')
        db.session.add(user)
        db.session.commit()
        trip = _create_trip(user.id)

        item = ItineraryItem(
            trip_id=trip.id,
            item_type='activity',
            scope='custom',
            scope_guest_ids_json=json.dumps([1, 3, 5]),
        )
        db.session.add(item)
        db.session.commit()

        d = item.to_dict()
        assert d['scope'] == 'custom'
        assert d['scope_guest_ids'] == [1, 3, 5]

    def test_item_to_dict_empty_scope_guest_ids(self):
        user = User(email='u@t.com', name='U', is_verified=True, is_active=True)
        user.set_password('x')
        db.session.add(user)
        db.session.commit()
        trip = _create_trip(user.id)

        item = ItineraryItem(trip_id=trip.id, item_type='flight')
        db.session.add(item)
        db.session.commit()

        d = item.to_dict()
        assert d['scope_guest_ids'] == []
        assert d['search_params'] is None

    def test_item_trip_relationship(self):
        user = User(email='u@t.com', name='U', is_verified=True, is_active=True)
        user.set_password('x')
        db.session.add(user)
        db.session.commit()
        trip = _create_trip(user.id)

        ItineraryItem(trip_id=trip.id, item_type='flight')
        ItineraryItem(trip_id=trip.id, item_type='hotel')
        db.session.add_all([
            ItineraryItem(trip_id=trip.id, item_type='flight'),
            ItineraryItem(trip_id=trip.id, item_type='hotel'),
        ])
        db.session.commit()

        assert trip.itinerary_items.count() == 2


# ================================================================
# Part 4: ItineraryVote + ItemComment Models (Build #224 prep)
# ================================================================

class TestVoteCommentModels:
    """Test ItineraryVote and ItemComment model creation."""

    def test_create_vote(self):
        user = User(email='u@t.com', name='U', is_verified=True, is_active=True)
        user.set_password('x')
        db.session.add(user)
        db.session.commit()
        trip = _create_trip(user.id)
        guest = _create_guest(trip.id, 'Alice')
        item = ItineraryItem(trip_id=trip.id, item_type='flight')
        db.session.add(item)
        db.session.commit()

        vote = ItineraryVote(item_id=item.id, guest_id=guest.id, vote='up', comment='Love it!')
        db.session.add(vote)
        db.session.commit()

        assert vote.id is not None
        assert vote.vote == 'up'
        assert item.votes.count() == 1

    def test_vote_unique_constraint(self):
        user = User(email='u@t.com', name='U', is_verified=True, is_active=True)
        user.set_password('x')
        db.session.add(user)
        db.session.commit()
        trip = _create_trip(user.id)
        guest = _create_guest(trip.id, 'Alice')
        item = ItineraryItem(trip_id=trip.id, item_type='flight')
        db.session.add(item)
        db.session.commit()

        vote1 = ItineraryVote(item_id=item.id, guest_id=guest.id, vote='up')
        db.session.add(vote1)
        db.session.commit()

        vote2 = ItineraryVote(item_id=item.id, guest_id=guest.id, vote='down')
        db.session.add(vote2)
        with pytest.raises(Exception):  # IntegrityError
            db.session.commit()

    def test_create_comment(self):
        user = User(email='u@t.com', name='U', is_verified=True, is_active=True)
        user.set_password('x')
        db.session.add(user)
        db.session.commit()
        trip = _create_trip(user.id)
        guest = _create_guest(trip.id, 'Alice')
        item = ItineraryItem(trip_id=trip.id, item_type='hotel')
        db.session.add(item)
        db.session.commit()

        comment = ItemComment(item_id=item.id, guest_id=guest.id, body='Great hotel!')
        db.session.add(comment)
        db.session.commit()

        assert comment.id is not None
        assert item.comments.count() == 1

    def test_comment_threading(self):
        user = User(email='u@t.com', name='U', is_verified=True, is_active=True)
        user.set_password('x')
        db.session.add(user)
        db.session.commit()
        trip = _create_trip(user.id)
        guest = _create_guest(trip.id, 'Alice')
        item = ItineraryItem(trip_id=trip.id, item_type='hotel')
        db.session.add(item)
        db.session.commit()

        parent = ItemComment(item_id=item.id, guest_id=guest.id, body='Parent')
        db.session.add(parent)
        db.session.commit()

        reply = ItemComment(item_id=item.id, guest_id=guest.id, body='Reply',
                            parent_comment_id=parent.id)
        db.session.add(reply)
        db.session.commit()

        assert reply.parent_comment_id == parent.id
        assert parent.replies.count() == 1


# ================================================================
# Part 5: Party API Endpoints
# ================================================================

class TestPartyAPI:
    """Test /api/trips/<id>/parties endpoints."""

    def test_create_party(self, auth_client):
        with app.app_context():
            user = _get_user()
            trip = _create_trip(user.id)
            tid = trip.id

        r = auth_client.post(f'/api/trips/{tid}/parties',
                             json={'name': 'The Smiths', 'party_type': 'attendee', 'budget_usd': 3000})
        assert r.status_code == 200
        data = r.get_json()
        assert data['status'] == 'ok'
        assert data['party']['name'] == 'The Smiths'
        assert data['party']['budget_usd'] == 3000

    def test_create_party_name_required(self, auth_client):
        with app.app_context():
            user = _get_user()
            trip = _create_trip(user.id)
            tid = trip.id

        r = auth_client.post(f'/api/trips/{tid}/parties', json={'party_type': 'attendee'})
        assert r.status_code == 400
        assert 'name' in r.get_json()['error'].lower()

    def test_list_parties(self, auth_client):
        with app.app_context():
            user = _get_user()
            trip = _create_trip(user.id)
            _create_party(trip.id, 'P1')
            _create_party(trip.id, 'P2')
            tid = trip.id

        r = auth_client.get(f'/api/trips/{tid}/parties')
        assert r.status_code == 200
        data = r.get_json()
        assert data['count'] == 2
        assert data['parties'][0]['name'] == 'P1'

    def test_update_party(self, auth_client):
        with app.app_context():
            user = _get_user()
            trip = _create_trip(user.id)
            party = _create_party(trip.id, 'Old Name')
            tid, pid = trip.id, party.id

        r = auth_client.put(f'/api/trips/{tid}/parties/{pid}',
                            json={'name': 'New Name', 'budget_usd': 5000})
        assert r.status_code == 200
        data = r.get_json()
        assert data['party']['name'] == 'New Name'
        assert data['party']['budget_usd'] == 5000

    def test_delete_party_unlinks_guests(self, auth_client):
        with app.app_context():
            user = _get_user()
            trip = _create_trip(user.id)
            party = _create_party(trip.id, 'Delete Me')
            guest = _create_guest(trip.id, 'Alice', party_id=party.id)
            tid, pid, gid = trip.id, party.id, guest.id

        r = auth_client.delete(f'/api/trips/{tid}/parties/{pid}')
        assert r.status_code == 200

        # Guest should still exist but unlinked from party
        with app.app_context():
            g = db.session.get(TripGuest, gid)
            assert g is not None
            assert g.party_id is None

    def test_party_not_found(self, auth_client):
        with app.app_context():
            user = _get_user()
            trip = _create_trip(user.id)
            tid = trip.id

        r = auth_client.put(f'/api/trips/{tid}/parties/9999', json={'name': 'x'})
        assert r.status_code == 404

    def test_party_access_denied(self, client):
        """Non-member gets 403 on view endpoints."""
        with app.app_context():
            owner = User(email='owner@t.com', name='Owner', is_verified=True, is_active=True)
            owner.set_password('x')
            outsider = User(email='outsider@t.com', name='Outsider', is_verified=True, is_active=True)
            outsider.set_password('x')
            db.session.add_all([owner, outsider])
            db.session.commit()
            trip = _create_trip(owner.id)
            tid = trip.id
            _login_client_as(client, outsider.id)

        r = client.get(f'/api/trips/{tid}/parties')
        assert r.status_code == 403


# ================================================================
# Part 6: Guest API Endpoints
# ================================================================

class TestGuestAPI:
    """Test /api/trips/<id>/guests endpoints."""

    def test_add_guest(self, auth_client):
        with app.app_context():
            user = _get_user()
            trip = _create_trip(user.id)
            party = _create_party(trip.id, 'P1')
            tid, pid = trip.id, party.id

        r = auth_client.post(f'/api/trips/{tid}/guests',
                             json={'display_name': 'Alice', 'party_id': pid,
                                   'email': 'alice@test.com', 'role': 'editor'})
        assert r.status_code == 200
        data = r.get_json()
        assert data['guest']['display_name'] == 'Alice'
        assert data['guest']['role'] == 'editor'
        assert data['guest']['party_id'] == pid

    def test_add_guest_name_required(self, auth_client):
        with app.app_context():
            user = _get_user()
            trip = _create_trip(user.id)
            tid = trip.id

        r = auth_client.post(f'/api/trips/{tid}/guests', json={'role': 'viewer'})
        assert r.status_code == 400

    def test_list_guests(self, auth_client):
        with app.app_context():
            user = _get_user()
            trip = _create_trip(user.id)
            _create_guest(trip.id, 'Alice')
            _create_guest(trip.id, 'Bob')
            _create_guest(trip.id, 'Charlie')
            tid = trip.id

        r = auth_client.get(f'/api/trips/{tid}/guests')
        assert r.status_code == 200
        data = r.get_json()
        assert data['count'] == 3

    def test_update_guest(self, auth_client):
        with app.app_context():
            user = _get_user()
            trip = _create_trip(user.id)
            guest = _create_guest(trip.id, 'Alice')
            tid, gid = trip.id, guest.id

        r = auth_client.put(f'/api/trips/{tid}/guests/{gid}',
                            json={'display_name': 'Alice Smith', 'role': 'admin',
                                  'arrival_date': '2027-06-07'})
        assert r.status_code == 200
        data = r.get_json()
        assert data['guest']['display_name'] == 'Alice Smith'
        assert data['guest']['role'] == 'admin'
        assert data['guest']['arrival_date'] == '2027-06-07'

    def test_delete_guest(self, auth_client):
        with app.app_context():
            user = _get_user()
            trip = _create_trip(user.id)
            guest = _create_guest(trip.id, 'Alice')
            tid, gid = trip.id, guest.id

        r = auth_client.delete(f'/api/trips/{tid}/guests/{gid}')
        assert r.status_code == 200

        with app.app_context():
            assert db.session.get(TripGuest, gid) is None

    def test_rsvp_by_admin(self, auth_client):
        """Trip creator (admin) can update any guest's RSVP."""
        with app.app_context():
            user = _get_user()
            trip = _create_trip(user.id)
            guest = _create_guest(trip.id, 'Alice')
            tid, gid = trip.id, guest.id

        r = auth_client.post(f'/api/trips/{tid}/guests/{gid}/rsvp',
                             json={'rsvp_status': 'attending'})
        assert r.status_code == 200
        assert r.get_json()['guest']['rsvp_status'] == 'attending'

    def test_rsvp_by_self(self, client):
        """A guest can update their own RSVP."""
        with app.app_context():
            owner = User(email='rsvpowner@t.com', name='Owner', is_verified=True, is_active=True)
            owner.set_password('x')
            viewer = User(email='rsvpviewer@t.com', name='Viewer', is_verified=True, is_active=True)
            viewer.set_password('x')
            db.session.add_all([owner, viewer])
            db.session.commit()
            trip = _create_trip(owner.id)
            member = TripMember(trip_plan_id=trip.id, user_id=viewer.id, role='viewer')
            db.session.add(member)
            db.session.commit()
            guest = _create_guest(trip.id, 'Viewer', user_id=viewer.id)
            tid, gid = trip.id, guest.id
            _login_client_as(client, viewer.id)

        r = client.post(f'/api/trips/{tid}/guests/{gid}/rsvp',
                        json={'rsvp_status': 'declined'})
        assert r.status_code == 200
        assert r.get_json()['guest']['rsvp_status'] == 'declined'

    def test_rsvp_invalid_status(self, auth_client):
        with app.app_context():
            user = _get_user()
            trip = _create_trip(user.id)
            guest = _create_guest(trip.id, 'Alice')
            tid, gid = trip.id, guest.id

        r = auth_client.post(f'/api/trips/{tid}/guests/{gid}/rsvp',
                             json={'rsvp_status': 'bogus'})
        assert r.status_code == 400

    def test_guest_with_flexible_dates_api(self, auth_client):
        with app.app_context():
            user = _get_user()
            trip = _create_trip(user.id)
            tid = trip.id

        r = auth_client.post(f'/api/trips/{tid}/guests',
                             json={'display_name': 'Late Bob',
                                   'arrival_date': '2027-06-08',
                                   'departure_date': '2027-06-11'})
        assert r.status_code == 200
        data = r.get_json()
        assert data['guest']['arrival_date'] == '2027-06-08'
        assert data['guest']['departure_date'] == '2027-06-11'


# ================================================================
# Part 7: Itinerary API Endpoints
# ================================================================

class TestItineraryAPI:
    """Test /api/trips/<id>/itinerary endpoints."""

    def test_add_flight_item(self, auth_client):
        with app.app_context():
            user = _get_user()
            trip = _create_trip(user.id)
            tid = trip.id

        r = auth_client.post(f'/api/trips/{tid}/itinerary',
                             json={
                                 'item_type': 'flight',
                                 'date': '2027-06-05',
                                 'search_params': {
                                     'origin': 'LAX',
                                     'destination': 'NRT',
                                     'date': '2027-06-05',
                                     'passengers': 2,
                                 },
                             })
        assert r.status_code == 200
        data = r.get_json()
        assert data['item']['item_type'] == 'flight'
        assert data['item']['search_params']['origin'] == 'LAX'
        assert data['item']['status'] == 'suggested'

    def test_add_external_booking(self, auth_client):
        with app.app_context():
            user = _get_user()
            trip = _create_trip(user.id)
            tid = trip.id

        r = auth_client.post(f'/api/trips/{tid}/itinerary',
                             json={
                                 'item_type': 'hotel',
                                 'booking_source': 'external',
                                 'external_name': 'Airbnb Loft',
                                 'external_url': 'https://airbnb.com/rooms/99',
                                 'external_cost_usd': 800.0,
                             })
        assert r.status_code == 200
        data = r.get_json()
        assert data['item']['booking_source'] == 'external'
        assert data['item']['external_name'] == 'Airbnb Loft'
        assert data['item']['external_cost_usd'] == 800.0

    def test_add_item_invalid_type(self, auth_client):
        with app.app_context():
            user = _get_user()
            trip = _create_trip(user.id)
            tid = trip.id

        r = auth_client.post(f'/api/trips/{tid}/itinerary',
                             json={'item_type': 'spaceship'})
        assert r.status_code == 400

    def test_list_itinerary(self, auth_client):
        with app.app_context():
            user = _get_user()
            trip = _create_trip(user.id)
            item1 = ItineraryItem(trip_id=trip.id, item_type='flight',
                                  cached_price_usd=900.0, status='booked',
                                  date=date(2027, 6, 5))
            item2 = ItineraryItem(trip_id=trip.id, item_type='hotel',
                                  external_cost_usd=500.0,
                                  date=date(2027, 6, 5), position=1)
            item3 = ItineraryItem(trip_id=trip.id, item_type='activity',
                                  date=date(2027, 6, 6))
            db.session.add_all([item1, item2, item3])
            db.session.commit()
            tid = trip.id

        r = auth_client.get(f'/api/trips/{tid}/itinerary')
        assert r.status_code == 200
        data = r.get_json()
        assert data['count'] == 3
        assert data['booked_count'] == 1
        assert data['total_estimated_usd'] == 1400.0  # 900 + 500

    def test_update_itinerary_item(self, auth_client):
        with app.app_context():
            user = _get_user()
            trip = _create_trip(user.id)
            item = ItineraryItem(trip_id=trip.id, item_type='flight')
            db.session.add(item)
            db.session.commit()
            tid, iid = trip.id, item.id

        r = auth_client.put(f'/api/trips/{tid}/itinerary/{iid}',
                            json={
                                'notes': 'Updated note',
                                'search_params': {'origin': 'SFO', 'destination': 'CDG'},
                                'cached_price_usd': 1200.0,
                            })
        assert r.status_code == 200
        data = r.get_json()
        assert data['item']['notes'] == 'Updated note'
        assert data['item']['search_params']['origin'] == 'SFO'
        assert data['item']['cached_price_usd'] == 1200.0

    def test_delete_itinerary_item(self, auth_client):
        with app.app_context():
            user = _get_user()
            trip = _create_trip(user.id)
            item = ItineraryItem(trip_id=trip.id, item_type='hotel')
            db.session.add(item)
            db.session.commit()
            tid, iid = trip.id, item.id

        r = auth_client.delete(f'/api/trips/{tid}/itinerary/{iid}')
        assert r.status_code == 200

        with app.app_context():
            assert db.session.get(ItineraryItem, iid) is None

    def test_update_itinerary_status(self, auth_client):
        with app.app_context():
            user = _get_user()
            trip = _create_trip(user.id)
            item = ItineraryItem(trip_id=trip.id, item_type='flight')
            db.session.add(item)
            db.session.commit()
            tid, iid = trip.id, item.id

        r = auth_client.post(f'/api/trips/{tid}/itinerary/{iid}/status',
                             json={'status': 'approved'})
        assert r.status_code == 200
        assert r.get_json()['item']['status'] == 'approved'

    def test_update_status_invalid(self, auth_client):
        with app.app_context():
            user = _get_user()
            trip = _create_trip(user.id)
            item = ItineraryItem(trip_id=trip.id, item_type='flight')
            db.session.add(item)
            db.session.commit()
            tid, iid = trip.id, item.id

        r = auth_client.post(f'/api/trips/{tid}/itinerary/{iid}/status',
                             json={'status': 'invalid'})
        assert r.status_code == 400

    def test_add_item_with_scope(self, auth_client):
        with app.app_context():
            user = _get_user()
            trip = _create_trip(user.id)
            party = _create_party(trip.id, 'Family A')
            tid, pid = trip.id, party.id

        r = auth_client.post(f'/api/trips/{tid}/itinerary',
                             json={
                                 'item_type': 'activity',
                                 'scope': 'party',
                                 'scope_party_id': pid,
                                 'external_name': 'Snorkeling',
                                 'external_cost_usd': 200.0,
                                 'booking_source': 'external',
                             })
        assert r.status_code == 200
        data = r.get_json()
        assert data['item']['scope'] == 'party'
        assert data['item']['scope_party_id'] == pid


# ================================================================
# Part 8: Scope Breakdown (Build #223)
# ================================================================

class TestScopeBreakdown:
    """Test GET /api/trips/<id>/scope-breakdown cost allocation logic."""

    def _setup_trip_with_parties(self):
        """Create a trip with 2 parties and 4 guests."""
        user = _get_user()
        trip = _create_trip(user.id)

        p1 = _create_party(trip.id, 'Family A', budget_usd=2000)
        p2 = _create_party(trip.id, 'Couple B', budget_usd=1000)

        g1 = _create_guest(trip.id, 'Dad', party_id=p1.id)
        g2 = _create_guest(trip.id, 'Mom', party_id=p1.id)
        g3 = _create_guest(trip.id, 'Jeff', party_id=p2.id)
        g4 = _create_guest(trip.id, 'Lisa', party_id=p2.id)

        return trip, p1, p2, g1, g2, g3, g4

    def test_trip_scope_splits_equally(self, auth_client):
        """trip scope items split cost equally across all parties."""
        with app.app_context():
            trip, p1, p2, g1, g2, g3, g4 = self._setup_trip_with_parties()

            # Flight for entire trip: $1000 split across 2 parties = $500 each
            item = ItineraryItem(
                trip_id=trip.id, item_type='flight', scope='trip',
                cached_price_usd=1000.0,
            )
            db.session.add(item)
            db.session.commit()
            tid = trip.id

        r = auth_client.get(f'/api/trips/{tid}/scope-breakdown')
        assert r.status_code == 200
        data = r.get_json()
        assert data['total_cost'] == 1000.0
        assert len(data['breakdown']) == 2
        for b in data['breakdown']:
            assert b['total_cost'] == 500.0

    def test_party_scope_charges_one_party(self, auth_client):
        """party scope items charge cost to one specific party."""
        with app.app_context():
            trip, p1, p2, g1, g2, g3, g4 = self._setup_trip_with_parties()

            item = ItineraryItem(
                trip_id=trip.id, item_type='activity', scope='party',
                scope_party_id=p1.id, external_cost_usd=300.0,
                booking_source='external',
            )
            db.session.add(item)
            db.session.commit()
            tid, pid1, pid2 = trip.id, p1.id, p2.id

        r = auth_client.get(f'/api/trips/{tid}/scope-breakdown')
        data = r.get_json()
        costs = {b['party_id']: b['total_cost'] for b in data['breakdown']}
        assert costs[pid1] == 300.0
        assert costs[pid2] == 0.0

    def test_individual_scope_charges_guests_party(self, auth_client):
        """individual scope charges cost to the assigned guest's party."""
        with app.app_context():
            trip, p1, p2, g1, g2, g3, g4 = self._setup_trip_with_parties()

            # Individual item for Jeff (in Couple B)
            item = ItineraryItem(
                trip_id=trip.id, item_type='activity', scope='individual',
                assigned_to_guest_id=g3.id, external_cost_usd=150.0,
                booking_source='external',
            )
            db.session.add(item)
            db.session.commit()
            tid, pid1, pid2 = trip.id, p1.id, p2.id

        r = auth_client.get(f'/api/trips/{tid}/scope-breakdown')
        data = r.get_json()
        costs = {b['party_id']: b['total_cost'] for b in data['breakdown']}
        assert costs[pid1] == 0.0
        assert costs[pid2] == 150.0

    def test_custom_scope_splits_across_involved_parties(self, auth_client):
        """custom scope splits cost across parties of the specified guests."""
        with app.app_context():
            trip, p1, p2, g1, g2, g3, g4 = self._setup_trip_with_parties()

            # Custom item for Dad (Family A) + Jeff (Couple B) = split across 2 parties
            item = ItineraryItem(
                trip_id=trip.id, item_type='restaurant', scope='custom',
                scope_guest_ids_json=json.dumps([g1.id, g3.id]),
                external_cost_usd=200.0,
                booking_source='external',
            )
            db.session.add(item)
            db.session.commit()
            tid, pid1, pid2 = trip.id, p1.id, p2.id

        r = auth_client.get(f'/api/trips/{tid}/scope-breakdown')
        data = r.get_json()
        costs = {b['party_id']: b['total_cost'] for b in data['breakdown']}
        assert costs[pid1] == 100.0  # $200 / 2 parties
        assert costs[pid2] == 100.0

    def test_mixed_scopes(self, auth_client):
        """Multiple items with different scopes accumulate correctly."""
        with app.app_context():
            trip, p1, p2, g1, g2, g3, g4 = self._setup_trip_with_parties()

            # Trip-scope flight: $1000 / 2 = $500 each
            i1 = ItineraryItem(trip_id=trip.id, item_type='flight', scope='trip',
                               cached_price_usd=1000.0)
            # Party-scope activity for Family A: $300
            i2 = ItineraryItem(trip_id=trip.id, item_type='activity', scope='party',
                               scope_party_id=p1.id, external_cost_usd=300.0,
                               booking_source='external')
            # Individual for Lisa (Couple B): $50
            i3 = ItineraryItem(trip_id=trip.id, item_type='custom', scope='individual',
                               assigned_to_guest_id=g4.id, external_cost_usd=50.0,
                               booking_source='external')
            db.session.add_all([i1, i2, i3])
            db.session.commit()
            tid, pid1, pid2 = trip.id, p1.id, p2.id

        r = auth_client.get(f'/api/trips/{tid}/scope-breakdown')
        data = r.get_json()
        costs = {b['party_id']: b['total_cost'] for b in data['breakdown']}
        assert costs[pid1] == 800.0   # 500 (flight) + 300 (activity)
        assert costs[pid2] == 550.0   # 500 (flight) + 50 (individual)
        assert data['total_cost'] == 1350.0

    def test_over_budget_flag(self, auth_client):
        """over_budget is True when party cost exceeds budget."""
        with app.app_context():
            trip, p1, p2, g1, g2, g3, g4 = self._setup_trip_with_parties()
            # p2 has budget $1000. Give it $1500 in costs.
            item = ItineraryItem(trip_id=trip.id, item_type='hotel', scope='party',
                                 scope_party_id=p2.id, cached_price_usd=1500.0)
            db.session.add(item)
            db.session.commit()
            tid, pid2 = trip.id, p2.id

        r = auth_client.get(f'/api/trips/{tid}/scope-breakdown')
        data = r.get_json()
        for b in data['breakdown']:
            if b['party_id'] == pid2:
                assert b['over_budget'] is True
                assert b['total_cost'] == 1500.0

    def test_no_parties_unassigned_cost(self, auth_client):
        """When no parties exist, all cost goes to unassigned."""
        with app.app_context():
            user = _get_user()
            trip = _create_trip(user.id)
            item = ItineraryItem(trip_id=trip.id, item_type='flight',
                                 scope='trip', cached_price_usd=600.0)
            db.session.add(item)
            db.session.commit()
            tid = trip.id

        r = auth_client.get(f'/api/trips/{tid}/scope-breakdown')
        data = r.get_json()
        assert data['party_count'] == 0
        assert data['unassigned_cost'] == 600.0


# ================================================================
# Part 9: Settlement Calculator (Build #223)
# ================================================================

class TestSettlement:
    """Test GET /api/trips/<id>/settlement."""

    def test_settlement_basic(self, auth_client):
        """Settlement shows each party's payer and amount owed."""
        with app.app_context():
            user = _get_user()
            trip = _create_trip(user.id)

            p1 = _create_party(trip.id, 'Family A')
            p2 = _create_party(trip.id, 'Couple B')

            dad = _create_guest(trip.id, 'Dad', party_id=p1.id)
            jeff = _create_guest(trip.id, 'Jeff', party_id=p2.id)

            # Set payers
            p1.payer_guest_id = dad.id
            p2.payer_guest_id = jeff.id
            db.session.commit()

            # Trip-scope flight: $1000 / 2 = $500 each
            item = ItineraryItem(trip_id=trip.id, item_type='flight', scope='trip',
                                 cached_price_usd=1000.0)
            db.session.add(item)
            db.session.commit()
            tid = trip.id

        r = auth_client.get(f'/api/trips/{tid}/settlement')
        assert r.status_code == 200
        data = r.get_json()
        assert data['total_trip_cost'] == 1000.0
        assert len(data['settlements']) == 2
        for s in data['settlements']:
            assert s['total_owed'] == 500.0

    def test_settlement_with_payment_status(self, auth_client):
        """Settlement includes payment_status from payer guest."""
        with app.app_context():
            user = _get_user()
            trip = _create_trip(user.id)

            p1 = _create_party(trip.id, 'Solo Marco')
            marco = _create_guest(trip.id, 'Marco', party_id=p1.id)
            marco.payment_status = 'paid'
            p1.payer_guest_id = marco.id
            db.session.commit()

            item = ItineraryItem(trip_id=trip.id, item_type='hotel', scope='party',
                                 scope_party_id=p1.id, cached_price_usd=400.0)
            db.session.add(item)
            db.session.commit()
            tid = trip.id

        r = auth_client.get(f'/api/trips/{tid}/settlement')
        data = r.get_json()
        assert len(data['settlements']) == 1
        assert data['settlements'][0]['payer_name'] == 'Marco'
        assert data['settlements'][0]['payment_status'] == 'paid'
        assert data['settlements'][0]['total_owed'] == 400.0

    def test_settlement_no_payer(self, auth_client):
        """Settlement works with no payer assigned (shows 'Unassigned')."""
        with app.app_context():
            user = _get_user()
            trip = _create_trip(user.id)

            p1 = _create_party(trip.id, 'Unassigned Party')
            item = ItineraryItem(trip_id=trip.id, item_type='flight', scope='party',
                                 scope_party_id=p1.id, cached_price_usd=500.0)
            db.session.add(item)
            db.session.commit()
            tid = trip.id

        r = auth_client.get(f'/api/trips/{tid}/settlement')
        data = r.get_json()
        assert data['settlements'][0]['payer_name'] == 'Unassigned'


# ================================================================
# Part 10: Access Control
# ================================================================

class TestAccessControl:
    """Test trip access control across all endpoints."""

    def test_unauthenticated_access(self, client):
        """Unauthenticated requests should be rejected."""
        r = client.get('/api/trips/1/parties')
        # Flask-Login redirects to login page (302) or returns 401
        assert r.status_code in (302, 401)

    def test_non_member_cannot_edit(self, client):
        """Non-member gets 403 on edit endpoints."""
        with app.app_context():
            owner = User(email='owner2@t.com', name='Owner', is_verified=True, is_active=True)
            owner.set_password('x')
            outsider = User(email='outsider2@t.com', name='Outsider', is_verified=True, is_active=True)
            outsider.set_password('x')
            db.session.add_all([owner, outsider])
            db.session.commit()
            trip = _create_trip(owner.id)
            tid = trip.id
            _login_client_as(client, outsider.id)

        r = client.post(f'/api/trips/{tid}/parties',
                        json={'name': 'Hacker Party'})
        assert r.status_code == 403

    def test_viewer_cannot_edit(self, client):
        """Viewer member gets 403 on edit-required endpoints."""
        with app.app_context():
            owner = User(email='owner3@t.com', name='Owner', is_verified=True, is_active=True)
            owner.set_password('x')
            viewer = User(email='viewer3@t.com', name='Viewer', is_verified=True, is_active=True)
            viewer.set_password('x')
            db.session.add_all([owner, viewer])
            db.session.commit()
            trip = _create_trip(owner.id)
            member = TripMember(trip_plan_id=trip.id, user_id=viewer.id, role='viewer')
            db.session.add(member)
            db.session.commit()
            tid = trip.id
            _login_client_as(client, viewer.id)

        r = client.post(f'/api/trips/{tid}/parties',
                        json={'name': 'No Access'})
        assert r.status_code == 403

    def test_editor_can_edit(self, client):
        """Editor member can create parties."""
        with app.app_context():
            owner = User(email='owner4@t.com', name='Owner', is_verified=True, is_active=True)
            owner.set_password('x')
            editor = User(email='editor4@t.com', name='Editor', is_verified=True, is_active=True)
            editor.set_password('x')
            db.session.add_all([owner, editor])
            db.session.commit()
            trip = _create_trip(owner.id)
            member = TripMember(trip_plan_id=trip.id, user_id=editor.id, role='editor')
            db.session.add(member)
            db.session.commit()
            tid = trip.id
            _login_client_as(client, editor.id)

        r = client.post(f'/api/trips/{tid}/parties',
                        json={'name': 'Editor Party'})
        assert r.status_code == 200

    def test_trip_not_found(self, client):
        """Non-existent trip returns 404."""
        with app.app_context():
            user = User(email='finder@t.com', name='Finder', is_verified=True, is_active=True)
            user.set_password('x')
            db.session.add(user)
            db.session.commit()
            _login_client_as(client, user.id)

        r = client.get('/api/trips/9999/parties')
        assert r.status_code == 404

    def test_guest_role_viewer_read_access(self, client):
        """A viewer guest can read but not edit."""
        with app.app_context():
            owner = User(email='owner5@t.com', name='Owner', is_verified=True, is_active=True)
            owner.set_password('x')
            viewer = User(email='viewer5@t.com', name='Viewer', is_verified=True, is_active=True)
            viewer.set_password('x')
            db.session.add_all([owner, viewer])
            db.session.commit()
            trip = _create_trip(owner.id)
            guest = _create_guest(trip.id, 'Viewer', user_id=viewer.id, role='viewer')
            db.session.commit()
            tid = trip.id
            _login_client_as(client, viewer.id)

        # Read should work (viewer guest has read access)
        r = client.get(f'/api/trips/{tid}/parties')
        assert r.status_code == 200

        # Edit should fail (viewer cannot edit)
        r = client.post(f'/api/trips/{tid}/parties',
                        json={'name': 'Nope'})
        assert r.status_code == 403
