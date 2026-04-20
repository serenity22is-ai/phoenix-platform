"""
MYSTES Tests — Block 3 (Builds #224 + #238: Voting, Comments, Suggestions, Booking Lifecycle)

Tests for:
- Voting API: cast vote, upsert vote, vote tally, get votes (#224)
- Comments API: add comment, list comments, threaded replies, delete own, admin delete (#224)
- Suggestion flow: list suggestions, approve suggestion, reject non-owner (#224)
- Booking lifecycle: link booking to item, list trip bookings, update lifecycle (#238)
- _get_vote_tally helper: tallies up/down/neutral/score correctly

Run: python3 -m pytest tests/test_block3_voting_lifecycle.py -v
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
    ItineraryItem, ItineraryVote, ItemComment, Booking,
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
    """Authenticated test client with a user."""
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


def _create_trip(creator_id, name='Test Trip'):
    trip = TripPlan(creator_id=creator_id, name=name, status='draft')
    db.session.add(trip)
    db.session.commit()
    return trip


def _create_party(trip_id, name='The Smiths'):
    party = TripParty(trip_id=trip_id, name=name, party_type='attendee')
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


def _create_item(trip_id, item_type='flight', status='suggested', scope='trip'):
    item = ItineraryItem(
        trip_id=trip_id,
        item_type=item_type,
        status=status,
        scope=scope,
        position=0,
    )
    db.session.add(item)
    db.session.commit()
    return item


def _setup_trip_with_guest(auth_client):
    """Create a trip, party, and guest linked to the logged-in user."""
    user = _get_user()
    trip = _create_trip(user.id)
    party = _create_party(trip.id)
    guest = _create_guest(trip.id, 'Planner', party_id=party.id, user_id=user.id, role='editor')
    return user, trip, party, guest


# ================================================================
# Part 1: _get_vote_tally helper
# ================================================================

class TestVoteTallyHelper:
    """Test the _get_vote_tally function directly."""

    def test_empty_tally(self):
        from routes_trip_planner import _get_vote_tally
        user = _create_user('u@t.com')
        trip = _create_trip(user.id)
        item = _create_item(trip.id)
        tally = _get_vote_tally(item.id)
        assert tally == {'up': 0, 'down': 0, 'neutral': 0, 'total': 0, 'score': 0}

    def test_tally_counts(self):
        from routes_trip_planner import _get_vote_tally
        user = _create_user('u@t.com')
        trip = _create_trip(user.id)
        party = _create_party(trip.id)
        item = _create_item(trip.id)

        g1 = _create_guest(trip.id, 'G1', party_id=party.id, user_id=user.id)
        g2 = _create_guest(trip.id, 'G2', party_id=party.id)
        g3 = _create_guest(trip.id, 'G3', party_id=party.id)

        db.session.add_all([
            ItineraryVote(item_id=item.id, guest_id=g1.id, vote='up'),
            ItineraryVote(item_id=item.id, guest_id=g2.id, vote='up'),
            ItineraryVote(item_id=item.id, guest_id=g3.id, vote='down'),
        ])
        db.session.commit()

        tally = _get_vote_tally(item.id)
        assert tally['up'] == 2
        assert tally['down'] == 1
        assert tally['neutral'] == 0
        assert tally['total'] == 3
        assert tally['score'] == 1  # 2 - 1

    def test_tally_with_neutral(self):
        from routes_trip_planner import _get_vote_tally
        user = _create_user('u@t.com')
        trip = _create_trip(user.id)
        party = _create_party(trip.id)
        item = _create_item(trip.id)

        g1 = _create_guest(trip.id, 'G1', party_id=party.id)
        g2 = _create_guest(trip.id, 'G2', party_id=party.id)

        db.session.add_all([
            ItineraryVote(item_id=item.id, guest_id=g1.id, vote='neutral'),
            ItineraryVote(item_id=item.id, guest_id=g2.id, vote='down'),
        ])
        db.session.commit()

        tally = _get_vote_tally(item.id)
        assert tally['neutral'] == 1
        assert tally['down'] == 1
        assert tally['score'] == -1

    def test_tally_all_up(self):
        from routes_trip_planner import _get_vote_tally
        user = _create_user('u@t.com')
        trip = _create_trip(user.id)
        party = _create_party(trip.id)
        item = _create_item(trip.id)

        for i in range(5):
            g = _create_guest(trip.id, f'G{i}', party_id=party.id)
            db.session.add(ItineraryVote(item_id=item.id, guest_id=g.id, vote='up'))
        db.session.commit()

        tally = _get_vote_tally(item.id)
        assert tally['up'] == 5
        assert tally['score'] == 5
        assert tally['total'] == 5


# ================================================================
# Part 2: Voting API (Build #224)
# ================================================================

class TestVotingAPI:
    """Test voting endpoints."""

    def test_cast_vote_up(self, auth_client):
        user, trip, party, guest = _setup_trip_with_guest(auth_client)
        item = _create_item(trip.id)

        resp = auth_client.post(
            f'/api/trips/{trip.id}/itinerary/{item.id}/vote',
            json={'vote': 'up'},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['status'] == 'ok'
        assert data['tally']['up'] == 1
        assert data['tally']['score'] == 1

    def test_cast_vote_down(self, auth_client):
        user, trip, party, guest = _setup_trip_with_guest(auth_client)
        item = _create_item(trip.id)

        resp = auth_client.post(
            f'/api/trips/{trip.id}/itinerary/{item.id}/vote',
            json={'vote': 'down'},
        )
        assert resp.status_code == 200
        assert resp.get_json()['tally']['down'] == 1
        assert resp.get_json()['tally']['score'] == -1

    def test_vote_upsert(self, auth_client):
        """Voting again should update, not create duplicate."""
        user, trip, party, guest = _setup_trip_with_guest(auth_client)
        item = _create_item(trip.id)

        auth_client.post(
            f'/api/trips/{trip.id}/itinerary/{item.id}/vote',
            json={'vote': 'up'},
        )
        # Change vote
        resp = auth_client.post(
            f'/api/trips/{trip.id}/itinerary/{item.id}/vote',
            json={'vote': 'down'},
        )
        assert resp.status_code == 200
        tally = resp.get_json()['tally']
        assert tally['up'] == 0
        assert tally['down'] == 1
        assert tally['total'] == 1  # Still just one vote

    def test_vote_invalid_value(self, auth_client):
        user, trip, party, guest = _setup_trip_with_guest(auth_client)
        item = _create_item(trip.id)

        resp = auth_client.post(
            f'/api/trips/{trip.id}/itinerary/{item.id}/vote',
            json={'vote': 'maybe'},
        )
        assert resp.status_code == 400

    def test_vote_requires_guest_record(self, client):
        """User without a guest record cannot vote."""
        user = _create_user('voter@t.com')
        trip = _create_trip(user.id)
        item = _create_item(trip.id)
        # User is trip creator but NOT a guest
        _login_client_as(client, user.id)

        resp = client.post(
            f'/api/trips/{trip.id}/itinerary/{item.id}/vote',
            json={'vote': 'up'},
        )
        assert resp.status_code == 403

    def test_vote_nonexistent_item(self, auth_client):
        user, trip, party, guest = _setup_trip_with_guest(auth_client)

        resp = auth_client.post(
            f'/api/trips/{trip.id}/itinerary/9999/vote',
            json={'vote': 'up'},
        )
        assert resp.status_code == 404

    def test_vote_with_comment(self, auth_client):
        user, trip, party, guest = _setup_trip_with_guest(auth_client)
        item = _create_item(trip.id)

        resp = auth_client.post(
            f'/api/trips/{trip.id}/itinerary/{item.id}/vote',
            json={'vote': 'up', 'comment': 'Great option!'},
        )
        assert resp.status_code == 200
        vote = ItineraryVote.query.first()
        assert vote.comment == 'Great option!'

    def test_get_item_votes(self, auth_client):
        user, trip, party, guest = _setup_trip_with_guest(auth_client)
        item = _create_item(trip.id)

        # Cast a vote first
        auth_client.post(
            f'/api/trips/{trip.id}/itinerary/{item.id}/vote',
            json={'vote': 'up'},
        )

        resp = auth_client.get(f'/api/trips/{trip.id}/itinerary/{item.id}/votes')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['status'] == 'ok'
        assert len(data['votes']) == 1
        assert data['votes'][0]['vote'] == 'up'
        assert data['tally']['up'] == 1

    def test_get_votes_empty(self, auth_client):
        user, trip, party, guest = _setup_trip_with_guest(auth_client)
        item = _create_item(trip.id)

        resp = auth_client.get(f'/api/trips/{trip.id}/itinerary/{item.id}/votes')
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data['votes']) == 0
        assert data['tally']['total'] == 0

    def test_vote_access_denied(self, client):
        """User not in trip cannot vote."""
        owner = _create_user('owner@t.com')
        outsider = _create_user('outsider@t.com')
        trip = _create_trip(owner.id)
        item = _create_item(trip.id)

        _login_client_as(client, outsider.id)
        resp = client.post(
            f'/api/trips/{trip.id}/itinerary/{item.id}/vote',
            json={'vote': 'up'},
        )
        assert resp.status_code == 403


# ================================================================
# Part 3: Comments API (Build #224)
# ================================================================

class TestCommentsAPI:
    """Test comment endpoints."""

    def test_add_comment(self, auth_client):
        user, trip, party, guest = _setup_trip_with_guest(auth_client)
        item = _create_item(trip.id)

        resp = auth_client.post(
            f'/api/trips/{trip.id}/itinerary/{item.id}/comments',
            json={'body': 'Looks good!'},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['status'] == 'ok'
        assert data['comment']['body'] == 'Looks good!'
        assert data['comment']['guest_id'] == guest.id

    def test_add_comment_empty_body(self, auth_client):
        user, trip, party, guest = _setup_trip_with_guest(auth_client)
        item = _create_item(trip.id)

        resp = auth_client.post(
            f'/api/trips/{trip.id}/itinerary/{item.id}/comments',
            json={'body': ''},
        )
        assert resp.status_code == 400

    def test_add_comment_whitespace_body(self, auth_client):
        user, trip, party, guest = _setup_trip_with_guest(auth_client)
        item = _create_item(trip.id)

        resp = auth_client.post(
            f'/api/trips/{trip.id}/itinerary/{item.id}/comments',
            json={'body': '   '},
        )
        assert resp.status_code == 400

    def test_list_comments(self, auth_client):
        user, trip, party, guest = _setup_trip_with_guest(auth_client)
        item = _create_item(trip.id)

        auth_client.post(
            f'/api/trips/{trip.id}/itinerary/{item.id}/comments',
            json={'body': 'Comment 1'},
        )
        auth_client.post(
            f'/api/trips/{trip.id}/itinerary/{item.id}/comments',
            json={'body': 'Comment 2'},
        )

        resp = auth_client.get(f'/api/trips/{trip.id}/itinerary/{item.id}/comments')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['count'] == 2
        assert data['comments'][0]['body'] == 'Comment 1'

    def test_threaded_reply(self, auth_client):
        """Comments can reference a parent for threading."""
        user, trip, party, guest = _setup_trip_with_guest(auth_client)
        item = _create_item(trip.id)

        # Create parent comment
        resp1 = auth_client.post(
            f'/api/trips/{trip.id}/itinerary/{item.id}/comments',
            json={'body': 'Parent comment'},
        )
        parent_id = resp1.get_json()['comment']['id']

        # Create reply
        resp2 = auth_client.post(
            f'/api/trips/{trip.id}/itinerary/{item.id}/comments',
            json={'body': 'Reply to parent', 'parent_comment_id': parent_id},
        )
        assert resp2.status_code == 200
        assert resp2.get_json()['comment']['parent_comment_id'] == parent_id

    def test_reply_invalid_parent(self, auth_client):
        user, trip, party, guest = _setup_trip_with_guest(auth_client)
        item = _create_item(trip.id)

        resp = auth_client.post(
            f'/api/trips/{trip.id}/itinerary/{item.id}/comments',
            json={'body': 'Reply to nothing', 'parent_comment_id': 9999},
        )
        assert resp.status_code == 404

    def test_delete_own_comment(self, auth_client):
        user, trip, party, guest = _setup_trip_with_guest(auth_client)
        item = _create_item(trip.id)

        resp = auth_client.post(
            f'/api/trips/{trip.id}/itinerary/{item.id}/comments',
            json={'body': 'Delete me'},
        )
        cid = resp.get_json()['comment']['id']

        del_resp = auth_client.delete(
            f'/api/trips/{trip.id}/itinerary/{item.id}/comments/{cid}'
        )
        assert del_resp.status_code == 200

        # Verify deleted
        comments = auth_client.get(f'/api/trips/{trip.id}/itinerary/{item.id}/comments')
        assert comments.get_json()['count'] == 0

    def test_cannot_delete_others_comment(self, client):
        """A guest cannot delete another guest's comment."""
        owner = _create_user('owner@t.com')
        other = _create_user('other@t.com')
        trip = _create_trip(owner.id)
        party = _create_party(trip.id)
        item = _create_item(trip.id)

        # Owner creates a guest record for themselves and adds a comment
        owner_guest = _create_guest(trip.id, 'Owner', party_id=party.id, user_id=owner.id)
        comment = ItemComment(item_id=item.id, guest_id=owner_guest.id, body='Owner comment')
        db.session.add(comment)
        db.session.commit()
        comment_id = comment.id

        # Other user is a member with a guest record
        member = TripMember(trip_plan_id=trip.id, user_id=other.id, role='editor')
        db.session.add(member)
        other_guest = _create_guest(trip.id, 'Other', party_id=party.id, user_id=other.id)

        _login_client_as(client, other.id)
        resp = client.delete(
            f'/api/trips/{trip.id}/itinerary/{item.id}/comments/{comment_id}'
        )
        assert resp.status_code == 403

    def test_admin_can_delete_any_comment(self, client):
        """Trip creator can delete any comment."""
        owner = _create_user('owner@t.com')
        other = _create_user('other@t.com')
        trip = _create_trip(owner.id)
        party = _create_party(trip.id)
        item = _create_item(trip.id)

        # Other user creates a comment
        other_guest = _create_guest(trip.id, 'Other', party_id=party.id, user_id=other.id)
        member = TripMember(trip_plan_id=trip.id, user_id=other.id, role='editor')
        db.session.add(member)
        comment = ItemComment(item_id=item.id, guest_id=other_guest.id, body='Their comment')
        db.session.add(comment)
        db.session.commit()
        comment_id = comment.id

        # Owner (trip creator) deletes it
        _login_client_as(client, owner.id)
        resp = client.delete(
            f'/api/trips/{trip.id}/itinerary/{item.id}/comments/{comment_id}'
        )
        assert resp.status_code == 200

    def test_comment_requires_guest_record(self, client):
        """User without guest record cannot comment."""
        user = _create_user('noghost@t.com')
        trip = _create_trip(user.id)
        item = _create_item(trip.id)

        _login_client_as(client, user.id)
        resp = client.post(
            f'/api/trips/{trip.id}/itinerary/{item.id}/comments',
            json={'body': 'No guest record'},
        )
        assert resp.status_code == 403

    def test_comment_nonexistent_item(self, auth_client):
        user, trip, party, guest = _setup_trip_with_guest(auth_client)

        resp = auth_client.post(
            f'/api/trips/{trip.id}/itinerary/9999/comments',
            json={'body': 'Ghost item'},
        )
        assert resp.status_code == 404

    def test_delete_nonexistent_comment(self, auth_client):
        user, trip, party, guest = _setup_trip_with_guest(auth_client)
        item = _create_item(trip.id)

        resp = auth_client.delete(
            f'/api/trips/{trip.id}/itinerary/{item.id}/comments/9999'
        )
        assert resp.status_code == 404


# ================================================================
# Part 4: Suggestion Flow (Build #224)
# ================================================================

class TestSuggestionFlow:
    """Test suggestion listing and approval."""

    def test_list_suggestions(self, auth_client):
        user, trip, party, guest = _setup_trip_with_guest(auth_client)
        _create_item(trip.id, status='suggested')
        _create_item(trip.id, status='suggested')
        _create_item(trip.id, status='approved')  # Should not appear

        resp = auth_client.get(f'/api/trips/{trip.id}/suggestions')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['count'] == 2
        # Each suggestion should have a tally
        for s in data['suggestions']:
            assert 'tally' in s

    def test_list_suggestions_empty(self, auth_client):
        user, trip, party, guest = _setup_trip_with_guest(auth_client)

        resp = auth_client.get(f'/api/trips/{trip.id}/suggestions')
        assert resp.status_code == 200
        assert resp.get_json()['count'] == 0

    def test_approve_suggestion(self, auth_client):
        """Trip owner can approve a suggested item."""
        user, trip, party, guest = _setup_trip_with_guest(auth_client)
        item = _create_item(trip.id, status='suggested')

        resp = auth_client.post(
            f'/api/trips/{trip.id}/itinerary/{item.id}/approve'
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['item']['status'] == 'approved'

    def test_approve_already_approved(self, auth_client):
        """Cannot approve an item that's not in 'suggested' status."""
        user, trip, party, guest = _setup_trip_with_guest(auth_client)
        item = _create_item(trip.id, status='approved')

        resp = auth_client.post(
            f'/api/trips/{trip.id}/itinerary/{item.id}/approve'
        )
        assert resp.status_code == 400

    def test_approve_booked_item(self, auth_client):
        """Cannot approve an item that's already booked."""
        user, trip, party, guest = _setup_trip_with_guest(auth_client)
        item = _create_item(trip.id, status='booked')

        resp = auth_client.post(
            f'/api/trips/{trip.id}/itinerary/{item.id}/approve'
        )
        assert resp.status_code == 400

    def test_non_owner_cannot_approve(self, client):
        """Only trip owner/admin can approve suggestions."""
        owner = _create_user('owner@t.com')
        viewer = _create_user('viewer@t.com')
        trip = _create_trip(owner.id)
        item = _create_item(trip.id, status='suggested')

        # Viewer has member record but viewer role
        member = TripMember(trip_plan_id=trip.id, user_id=viewer.id, role='viewer')
        db.session.add(member)
        db.session.commit()

        _login_client_as(client, viewer.id)
        resp = client.post(
            f'/api/trips/{trip.id}/itinerary/{item.id}/approve'
        )
        assert resp.status_code == 403

    def test_editor_can_approve(self, client):
        """Editor role can approve suggestions."""
        owner = _create_user('owner@t.com')
        editor = _create_user('editor@t.com')
        trip = _create_trip(owner.id)
        item = _create_item(trip.id, status='suggested')

        member = TripMember(trip_plan_id=trip.id, user_id=editor.id, role='editor')
        db.session.add(member)
        db.session.commit()

        _login_client_as(client, editor.id)
        resp = client.post(
            f'/api/trips/{trip.id}/itinerary/{item.id}/approve'
        )
        assert resp.status_code == 200

    def test_suggestions_include_vote_tally(self, auth_client):
        """Suggestions list should include vote tallies."""
        user, trip, party, guest = _setup_trip_with_guest(auth_client)
        item = _create_item(trip.id, status='suggested')

        # Cast a vote
        auth_client.post(
            f'/api/trips/{trip.id}/itinerary/{item.id}/vote',
            json={'vote': 'up'},
        )

        resp = auth_client.get(f'/api/trips/{trip.id}/suggestions')
        data = resp.get_json()
        assert data['suggestions'][0]['tally']['up'] == 1
        assert data['suggestions'][0]['tally']['score'] == 1


# ================================================================
# Part 5: Booking Lifecycle (Build #238)
# ================================================================

class TestBookingLinkage:
    """Test linking bookings to itinerary items."""

    def test_link_booking_to_item(self, auth_client):
        user, trip, party, guest = _setup_trip_with_guest(auth_client)
        item = _create_item(trip.id, status='approved')

        # Create a booking
        booking = Booking(
            user_id=user.id,
            status='booked',
            vendor_payment_amount=450.0,
        )
        db.session.add(booking)
        db.session.commit()

        resp = auth_client.post(
            f'/api/trips/{trip.id}/itinerary/{item.id}/link-booking',
            json={'booking_id': booking.id},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['item']['status'] == 'booked'

        # Verify the item was updated
        updated_item = db.session.get(ItineraryItem, item.id)
        assert updated_item.booking_id == booking.id
        assert updated_item.cached_price_usd == 450.0

    def test_link_booking_missing_id(self, auth_client):
        user, trip, party, guest = _setup_trip_with_guest(auth_client)
        item = _create_item(trip.id)

        resp = auth_client.post(
            f'/api/trips/{trip.id}/itinerary/{item.id}/link-booking',
            json={},
        )
        assert resp.status_code == 400

    def test_link_booking_not_found(self, auth_client):
        user, trip, party, guest = _setup_trip_with_guest(auth_client)
        item = _create_item(trip.id)

        resp = auth_client.post(
            f'/api/trips/{trip.id}/itinerary/{item.id}/link-booking',
            json={'booking_id': 9999},
        )
        assert resp.status_code == 404

    def test_link_booking_nonexistent_item(self, auth_client):
        user, trip, party, guest = _setup_trip_with_guest(auth_client)

        resp = auth_client.post(
            f'/api/trips/{trip.id}/itinerary/9999/link-booking',
            json={'booking_id': 1},
        )
        assert resp.status_code == 404


class TestTripBookings:
    """Test listing bookings attached to a trip."""

    def test_list_trip_bookings(self, auth_client):
        user, trip, party, guest = _setup_trip_with_guest(auth_client)
        item = _create_item(trip.id, status='booked')

        booking = Booking(
            user_id=user.id,
            status='booked',
            confirmation_code='ABC123',
            vendor_payment_amount=500.0,
            booking_lifecycle_status='active',
        )
        db.session.add(booking)
        db.session.commit()

        item.booking_id = booking.id
        db.session.commit()

        resp = auth_client.get(f'/api/trips/{trip.id}/bookings')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['count'] == 1
        assert data['bookings'][0]['confirmation_code'] == 'ABC123'
        assert data['bookings'][0]['lifecycle_status'] == 'active'

    def test_list_trip_bookings_empty(self, auth_client):
        user, trip, party, guest = _setup_trip_with_guest(auth_client)

        resp = auth_client.get(f'/api/trips/{trip.id}/bookings')
        assert resp.status_code == 200
        assert resp.get_json()['count'] == 0

    def test_list_trip_bookings_multiple(self, auth_client):
        user, trip, party, guest = _setup_trip_with_guest(auth_client)

        for i in range(3):
            item = _create_item(trip.id, item_type='flight', status='booked')
            booking = Booking(
                user_id=user.id,
                status='booked',
                confirmation_code=f'CODE{i}',
            )
            db.session.add(booking)
            db.session.commit()
            item.booking_id = booking.id
            db.session.commit()

        resp = auth_client.get(f'/api/trips/{trip.id}/bookings')
        assert resp.get_json()['count'] == 3


class TestBookingLifecycle:
    """Test booking lifecycle status updates."""

    def test_update_lifecycle_status(self, auth_client):
        user = _get_user()
        booking = Booking(
            user_id=user.id,
            status='booked',
            booking_lifecycle_status='active',
        )
        db.session.add(booking)
        db.session.commit()

        resp = auth_client.put(
            f'/api/bookings/{booking.id}/lifecycle',
            json={'lifecycle_status': 'schedule_changed'},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['booking']['lifecycle_status'] == 'schedule_changed'
        assert data['booking']['status_check_count'] == 1
        assert data['booking']['last_status_check'] is not None

    def test_update_lifecycle_invalid_status(self, auth_client):
        user = _get_user()
        booking = Booking(user_id=user.id, status='booked')
        db.session.add(booking)
        db.session.commit()

        resp = auth_client.put(
            f'/api/bookings/{booking.id}/lifecycle',
            json={'lifecycle_status': 'invalid_status'},
        )
        assert resp.status_code == 400

    def test_update_airline_confirmation(self, auth_client):
        user = _get_user()
        booking = Booking(user_id=user.id, status='booked')
        db.session.add(booking)
        db.session.commit()

        resp = auth_client.put(
            f'/api/bookings/{booking.id}/lifecycle',
            json={'airline_confirmation': 'XYZABC'},
        )
        assert resp.status_code == 200
        assert resp.get_json()['booking']['airline_confirmation'] == 'XYZABC'

    def test_update_check_in_opens(self, auth_client):
        user = _get_user()
        booking = Booking(user_id=user.id, status='booked')
        db.session.add(booking)
        db.session.commit()

        check_in_time = '2026-05-01T10:00:00'
        resp = auth_client.put(
            f'/api/bookings/{booking.id}/lifecycle',
            json={'check_in_opens': check_in_time},
        )
        assert resp.status_code == 200
        assert '2026-05-01' in resp.get_json()['booking']['check_in_opens']

    def test_update_rebooking_credit(self, auth_client):
        user = _get_user()
        booking = Booking(user_id=user.id, status='booked')
        db.session.add(booking)
        db.session.commit()

        resp = auth_client.put(
            f'/api/bookings/{booking.id}/lifecycle',
            json={'rebooking_credit_usd': 5.0, 'lifecycle_status': 'cancelled'},
        )
        assert resp.status_code == 200
        data = resp.get_json()['booking']
        assert data['rebooking_credit_usd'] == 5.0
        assert data['lifecycle_status'] == 'cancelled'

    def test_lifecycle_status_check_count_increments(self, auth_client):
        user = _get_user()
        booking = Booking(user_id=user.id, status='booked', status_check_count=0)
        db.session.add(booking)
        db.session.commit()

        # First update
        auth_client.put(
            f'/api/bookings/{booking.id}/lifecycle',
            json={'lifecycle_status': 'active'},
        )
        # Second update
        resp = auth_client.put(
            f'/api/bookings/{booking.id}/lifecycle',
            json={'lifecycle_status': 'completed'},
        )
        assert resp.get_json()['booking']['status_check_count'] == 2

    def test_lifecycle_access_denied(self, client):
        """Non-owner cannot update booking lifecycle."""
        owner = _create_user('owner@t.com')
        other = _create_user('other@t.com')
        booking = Booking(user_id=owner.id, status='booked')
        db.session.add(booking)
        db.session.commit()

        _login_client_as(client, other.id)
        resp = client.put(
            f'/api/bookings/{booking.id}/lifecycle',
            json={'lifecycle_status': 'cancelled'},
        )
        assert resp.status_code == 403

    def test_lifecycle_admin_override(self, client):
        """Admin user can update any booking lifecycle."""
        owner = _create_user('owner@t.com')
        admin = _create_user('admin@t.com')
        admin.is_admin = True
        db.session.commit()

        booking = Booking(user_id=owner.id, status='booked')
        db.session.add(booking)
        db.session.commit()

        _login_client_as(client, admin.id)
        resp = client.put(
            f'/api/bookings/{booking.id}/lifecycle',
            json={'lifecycle_status': 'cancelled'},
        )
        assert resp.status_code == 200

    def test_lifecycle_booking_not_found(self, auth_client):
        resp = auth_client.put(
            '/api/bookings/9999/lifecycle',
            json={'lifecycle_status': 'cancelled'},
        )
        assert resp.status_code == 404

    def test_lifecycle_complete_flow(self, auth_client):
        """Full lifecycle: active → schedule_changed → completed."""
        user = _get_user()
        booking = Booking(user_id=user.id, status='booked')
        db.session.add(booking)
        db.session.commit()

        # Start active
        resp1 = auth_client.put(
            f'/api/bookings/{booking.id}/lifecycle',
            json={'lifecycle_status': 'active', 'airline_confirmation': 'PNR123'},
        )
        assert resp1.status_code == 200

        # Schedule change
        resp2 = auth_client.put(
            f'/api/bookings/{booking.id}/lifecycle',
            json={'lifecycle_status': 'schedule_changed'},
        )
        assert resp2.status_code == 200

        # Complete
        resp3 = auth_client.put(
            f'/api/bookings/{booking.id}/lifecycle',
            json={'lifecycle_status': 'completed'},
        )
        assert resp3.status_code == 200
        assert resp3.get_json()['booking']['lifecycle_status'] == 'completed'
        assert resp3.get_json()['booking']['status_check_count'] == 3
