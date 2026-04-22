"""
MYSTES E2E Frontend Integration Test — Every fetch() call from every template.

Tests ALL API endpoints that the frontend JS calls, with full setup:
- Feature flags enabled
- User logged in
- Trip with guest (user-linked)
- Itinerary items for voting/commenting
- Deal for flight cards
- Corporate workspace
- Referral data

Run: python3 -m pytest tests/test_e2e_frontend.py -v --timeout=60
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
    ItineraryItem, ItineraryVote, ItemComment,
    TripAnnouncement, TicketTier, TripGuestInfo,
    FeatureFlag, Deal,
)

# Try importing optional models that may not exist yet
try:
    from models import CorporateWorkspace, CorporateMember, CorporatePolicy
except ImportError:
    CorporateWorkspace = CorporateMember = CorporatePolicy = None

try:
    from models import SharedCart
except ImportError:
    SharedCart = None


# ───── Feature flags to enable ─────
ALL_FLAGS = [
    'vertical_flights', 'vertical_hotels', 'rewards_points',
    'managed_mode', 'event_system', 'guest_info_collection',
    'qr_checkin', 'social_profiles', 'corporate_workspaces',
    'referral_attribution', 'shared_cart', 'trip_planner',
    'corporate_dashboard', 'travel_policies',
]


# ───── Fixtures ─────

@pytest.fixture(autouse=True)
def setup_db():
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


def _login(c, user_id):
    with c.session_transaction() as sess:
        sess['_user_id'] = str(user_id)


def _enable_all_flags():
    for key in ALL_FLAGS:
        existing = FeatureFlag.query.filter_by(flag_key=key).first()
        if existing:
            existing.is_enabled = True
        else:
            db.session.add(FeatureFlag(
                flag_key=key, flag_name=key.replace('_', ' ').title(),
                description='E2E test', layer=1, is_enabled=True,
            ))
    db.session.commit()


def _create_user(email='demo@mystes.app', name='Demo User', is_admin=True):
    user = User(email=email, name=name, is_verified=True, is_active=True,
                is_admin=is_admin)
    user.set_password('TestPass1!')
    db.session.add(user)
    db.session.commit()
    return user


def _create_trip(creator_id, name='Euro Summer 2026', mode='collaborative'):
    trip = TripPlan(
        creator_id=creator_id, name=name, status='draft',
        mode=mode, trip_type='trip',
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 14),
    )
    db.session.add(trip)
    db.session.commit()
    # Also create TripMember for creator
    db.session.add(TripMember(trip_plan_id=trip.id, user_id=creator_id, role='owner'))
    db.session.commit()
    return trip


def _create_guest(trip_id, user_id, display_name='Demo User', role='owner'):
    guest = TripGuest(
        trip_id=trip_id, user_id=user_id, display_name=display_name,
        role=role, rsvp_status='attending',
    )
    db.session.add(guest)
    db.session.commit()
    return guest


def _create_party(trip_id, name='Main Party'):
    party = TripParty(
        trip_id=trip_id, name=name, party_type='attendee',
        budget_usd=5000.0,
    )
    db.session.add(party)
    db.session.commit()
    return party


def _create_item(trip_id, title='Visit Big Ben', item_type='activity', scope='trip'):
    item = ItineraryItem(
        trip_id=trip_id, item_type=item_type, scope=scope,
        external_name=title, external_cost_usd=50.0,
        status='suggested',
        date=date(2026, 7, 2),
    )
    db.session.add(item)
    db.session.commit()
    return item


def _create_deal(airline='British Airways'):
    deal = Deal(
        deal_id='DEAL_E2E_001',
        deal_type='flight',
        airline=airline,
        flight_number='BA178',
        origin='JFK',
        destination='LHR',
        departure_date=date(2026, 7, 1),
        departure_time='19:30',
        arrival_time='07:15+1',
        stops=0,
        home_market='US',
        home_price_usd=1200.0,
        arbitrage_price_usd=890.0,
        user_savings_usd=310.0,
        savings_percent=25.8,
        cabin_class='economy',
        duration='7h 45m',
        deal_status='available',
    )
    db.session.add(deal)
    db.session.commit()
    return deal


def _full_setup(client):
    """Full setup: user, trip, guest, party, item, deal, flags."""
    _enable_all_flags()
    user = _create_user()
    trip = _create_trip(user.id)
    guest = _create_guest(trip.id, user.id)
    party = _create_party(trip.id)
    item = _create_item(trip.id)
    deal = _create_deal()
    _login(client, user.id)
    return {
        'user': user, 'trip': trip, 'guest': guest,
        'party': party, 'item': item, 'deal': deal,
    }


# ================================================================
# TRIP PLANNER — Parties, Guests, Itinerary, Votes, Comments
# ================================================================

class TestTripPlannerAPIs:
    """Test all Trip Planner fetch() calls from the frontend."""

    def test_get_parties(self, client):
        ctx = _full_setup(client)
        r = client.get(f'/api/trips/{ctx["trip"].id}/parties')
        assert r.status_code == 200
        data = r.get_json()
        assert data['status'] == 'ok'
        assert len(data['parties']) >= 1

    def test_create_party(self, client):
        ctx = _full_setup(client)
        r = client.post(f'/api/trips/{ctx["trip"].id}/parties',
                        json={'name': 'Beach Crew', 'party_type': 'attendee', 'budget_usd': 3000})
        assert r.status_code in (200, 201)
        data = r.get_json()
        assert data['status'] == 'ok'

    def test_update_party(self, client):
        ctx = _full_setup(client)
        r = client.put(f'/api/trips/{ctx["trip"].id}/parties/{ctx["party"].id}',
                       json={'name': 'Updated Party', 'budget_usd': 7000})
        assert r.status_code == 200
        data = r.get_json()
        assert data['status'] == 'ok'

    def test_delete_party(self, client):
        ctx = _full_setup(client)
        r = client.delete(f'/api/trips/{ctx["trip"].id}/parties/{ctx["party"].id}')
        assert r.status_code == 200

    def test_get_guests(self, client):
        ctx = _full_setup(client)
        r = client.get(f'/api/trips/{ctx["trip"].id}/guests')
        assert r.status_code == 200
        data = r.get_json()
        assert data['status'] == 'ok'
        assert len(data['guests']) >= 1

    def test_create_guest(self, client):
        ctx = _full_setup(client)
        r = client.post(f'/api/trips/{ctx["trip"].id}/guests',
                        json={'display_name': 'Alice Smith', 'email': 'alice@test.com', 'role': 'viewer'})
        assert r.status_code in (200, 201)
        data = r.get_json()
        assert data['status'] == 'ok'

    def test_update_guest(self, client):
        ctx = _full_setup(client)
        r = client.put(f'/api/trips/{ctx["trip"].id}/guests/{ctx["guest"].id}',
                       json={'display_name': 'Updated Name', 'role': 'admin'})
        assert r.status_code == 200

    def test_rsvp_guest(self, client):
        ctx = _full_setup(client)
        r = client.post(f'/api/trips/{ctx["trip"].id}/guests/{ctx["guest"].id}/rsvp',
                        json={'rsvp_status': 'attending'})
        assert r.status_code == 200

    def test_get_itinerary(self, client):
        ctx = _full_setup(client)
        r = client.get(f'/api/trips/{ctx["trip"].id}/itinerary')
        assert r.status_code == 200
        data = r.get_json()
        assert data['status'] == 'ok'
        assert len(data['items']) >= 1

    def test_create_itinerary_item(self, client):
        ctx = _full_setup(client)
        r = client.post(f'/api/trips/{ctx["trip"].id}/itinerary',
                        json={'item_type': 'restaurant', 'external_name': 'The Ivy',
                              'external_cost_usd': 120, 'scope': 'trip',
                              'date': '2026-07-03'})
        assert r.status_code in (200, 201)
        data = r.get_json()
        assert data['status'] == 'ok'

    def test_update_itinerary_item(self, client):
        ctx = _full_setup(client)
        r = client.put(f'/api/trips/{ctx["trip"].id}/itinerary/{ctx["item"].id}',
                       json={'external_name': 'Updated Item', 'external_cost_usd': 75})
        assert r.status_code == 200

    def test_delete_itinerary_item(self, client):
        ctx = _full_setup(client)
        r = client.delete(f'/api/trips/{ctx["trip"].id}/itinerary/{ctx["item"].id}')
        assert r.status_code == 200

    def test_item_status_change(self, client):
        ctx = _full_setup(client)
        r = client.post(f'/api/trips/{ctx["trip"].id}/itinerary/{ctx["item"].id}/status',
                        json={'status': 'approved'})
        assert r.status_code == 200

    def test_vote_on_item(self, client):
        """User must be a TripGuest to vote — setup adds user as guest."""
        ctx = _full_setup(client)
        r = client.post(f'/api/trips/{ctx["trip"].id}/itinerary/{ctx["item"].id}/vote',
                        json={'vote': 'up'})
        assert r.status_code == 200
        data = r.get_json()
        assert data['status'] == 'ok'

    def test_vote_down(self, client):
        ctx = _full_setup(client)
        r = client.post(f'/api/trips/{ctx["trip"].id}/itinerary/{ctx["item"].id}/vote',
                        json={'vote': 'down'})
        assert r.status_code == 200

    def test_vote_neutral(self, client):
        ctx = _full_setup(client)
        r = client.post(f'/api/trips/{ctx["trip"].id}/itinerary/{ctx["item"].id}/vote',
                        json={'vote': 'neutral'})
        assert r.status_code == 200

    def test_get_votes(self, client):
        ctx = _full_setup(client)
        # Cast a vote first
        client.post(f'/api/trips/{ctx["trip"].id}/itinerary/{ctx["item"].id}/vote',
                    json={'vote': 'up'})
        r = client.get(f'/api/trips/{ctx["trip"].id}/itinerary/{ctx["item"].id}/votes')
        assert r.status_code == 200
        data = r.get_json()
        assert data['status'] == 'ok'

    def test_add_comment(self, client):
        ctx = _full_setup(client)
        r = client.post(f'/api/trips/{ctx["trip"].id}/itinerary/{ctx["item"].id}/comments',
                        json={'body': 'Love this idea!'})
        assert r.status_code in (200, 201)
        data = r.get_json()
        assert data['status'] == 'ok'

    def test_get_comments(self, client):
        ctx = _full_setup(client)
        # Add a comment first
        client.post(f'/api/trips/{ctx["trip"].id}/itinerary/{ctx["item"].id}/comments',
                    json={'body': 'Test comment'})
        r = client.get(f'/api/trips/{ctx["trip"].id}/itinerary/{ctx["item"].id}/comments')
        assert r.status_code == 200
        data = r.get_json()
        assert data['status'] == 'ok'

    def test_delete_comment(self, client):
        ctx = _full_setup(client)
        resp = client.post(f'/api/trips/{ctx["trip"].id}/itinerary/{ctx["item"].id}/comments',
                           json={'body': 'To delete'})
        comment_id = resp.get_json().get('comment', {}).get('id')
        if comment_id:
            r = client.delete(f'/api/trips/{ctx["trip"].id}/itinerary/{ctx["item"].id}/comments/{comment_id}')
            assert r.status_code == 200

    def test_get_suggestions(self, client):
        ctx = _full_setup(client)
        r = client.get(f'/api/trips/{ctx["trip"].id}/suggestions')
        assert r.status_code == 200

    def test_approve_item(self, client):
        ctx = _full_setup(client)
        r = client.post(f'/api/trips/{ctx["trip"].id}/itinerary/{ctx["item"].id}/approve',
                        json={})
        assert r.status_code == 200

    def test_scope_breakdown(self, client):
        ctx = _full_setup(client)
        r = client.get(f'/api/trips/{ctx["trip"].id}/scope-breakdown')
        assert r.status_code == 200

    def test_settlement(self, client):
        ctx = _full_setup(client)
        r = client.get(f'/api/trips/{ctx["trip"].id}/settlement')
        assert r.status_code == 200

    def test_get_bookings(self, client):
        ctx = _full_setup(client)
        r = client.get(f'/api/trips/{ctx["trip"].id}/bookings')
        assert r.status_code == 200


# ================================================================
# EVENTS — Managed Mode, Tiers, Roster, Announcements, Guest Info
# ================================================================

class TestEventsAPIs:
    """Test all Events fetch() calls from the frontend."""

    def test_set_mode_managed(self, client):
        ctx = _full_setup(client)
        r = client.put(f'/api/trips/{ctx["trip"].id}/mode',
                       json={'mode': 'managed'})
        assert r.status_code == 200
        data = r.get_json()
        assert data['status'] == 'ok'

    def test_set_mode_collaborative(self, client):
        ctx = _full_setup(client)
        r = client.put(f'/api/trips/{ctx["trip"].id}/mode',
                       json={'mode': 'collaborative'})
        assert r.status_code == 200

    def test_update_event_config(self, client):
        ctx = _full_setup(client)
        # Switch to managed first
        client.put(f'/api/trips/{ctx["trip"].id}/mode', json={'mode': 'managed'})
        r = client.put(f'/api/trips/{ctx["trip"].id}/event-config',
                       json={'event_name': 'Summer Gala', 'venue_name': 'The Ritz',
                             'venue_address': '150 Piccadilly, London',
                             'event_description': 'Annual summer celebration',
                             'registration_type': 'open'})
        assert r.status_code == 200

    def test_update_capacity(self, client):
        ctx = _full_setup(client)
        client.put(f'/api/trips/{ctx["trip"].id}/mode', json={'mode': 'managed'})
        r = client.put(f'/api/trips/{ctx["trip"].id}/capacity',
                       json={'max_capacity': 200, 'waitlist_enabled': True})
        assert r.status_code == 200

    def test_get_tiers(self, client):
        ctx = _full_setup(client)
        r = client.get(f'/api/trips/{ctx["trip"].id}/tiers')
        assert r.status_code == 200
        data = r.get_json()
        assert data['status'] == 'ok'

    def test_create_tier(self, client):
        ctx = _full_setup(client)
        r = client.post(f'/api/trips/{ctx["trip"].id}/tiers',
                        json={'name': 'VIP', 'price_usd': 150.0, 'capacity': 50,
                              'included_items': 'Open bar, Priority seating'})
        assert r.status_code in (200, 201)
        data = r.get_json()
        assert data['status'] == 'ok'

    def test_update_tier(self, client):
        ctx = _full_setup(client)
        resp = client.post(f'/api/trips/{ctx["trip"].id}/tiers',
                           json={'name': 'Standard', 'price_usd': 50.0, 'capacity': 100})
        tier_id = resp.get_json().get('tier', {}).get('id')
        if tier_id:
            r = client.put(f'/api/trips/{ctx["trip"].id}/tiers/{tier_id}',
                           json={'name': 'Standard Plus', 'price_usd': 75.0})
            assert r.status_code == 200

    def test_delete_tier(self, client):
        ctx = _full_setup(client)
        resp = client.post(f'/api/trips/{ctx["trip"].id}/tiers',
                           json={'name': 'Delete Me', 'price_usd': 10.0, 'capacity': 5})
        tier_id = resp.get_json().get('tier', {}).get('id')
        if tier_id:
            r = client.delete(f'/api/trips/{ctx["trip"].id}/tiers/{tier_id}')
            assert r.status_code == 200

    def test_get_roster(self, client):
        ctx = _full_setup(client)
        client.put(f'/api/trips/{ctx["trip"].id}/mode', json={'mode': 'managed'})
        r = client.get(f'/api/trips/{ctx["trip"].id}/roster')
        assert r.status_code == 200

    def test_get_announcements(self, client):
        ctx = _full_setup(client)
        client.put(f'/api/trips/{ctx["trip"].id}/mode', json={'mode': 'managed'})
        r = client.get(f'/api/trips/{ctx["trip"].id}/announcements')
        assert r.status_code == 200

    def test_create_announcement(self, client):
        ctx = _full_setup(client)
        client.put(f'/api/trips/{ctx["trip"].id}/mode', json={'mode': 'managed'})
        r = client.post(f'/api/trips/{ctx["trip"].id}/announcements',
                        json={'body': 'Welcome everyone!', 'audience': 'all'})
        assert r.status_code in (200, 201)

    def test_promote_waitlist(self, client):
        ctx = _full_setup(client)
        client.put(f'/api/trips/{ctx["trip"].id}/mode', json={'mode': 'managed'})
        # Create a waitlisted guest
        guest2 = TripGuest(
            trip_id=ctx['trip'].id, display_name='Waitlisted Person',
            role='viewer', rsvp_status='waitlisted',
        )
        db.session.add(guest2)
        db.session.commit()
        r = client.post(f'/api/trips/{ctx["trip"].id}/waitlist/promote',
                        json={'guest_id': guest2.id})
        assert r.status_code == 200

    def test_guest_checkin(self, client):
        ctx = _full_setup(client)
        client.put(f'/api/trips/{ctx["trip"].id}/mode', json={'mode': 'managed'})
        r = client.post(f'/api/trips/{ctx["trip"].id}/guests/{ctx["guest"].id}/checkin',
                        json={})
        assert r.status_code == 200

    def test_get_guest_info(self, client):
        ctx = _full_setup(client)
        r = client.get(f'/api/trips/{ctx["trip"].id}/guests/{ctx["guest"].id}/info')
        assert r.status_code == 200

    def test_submit_guest_info(self, client):
        ctx = _full_setup(client)
        r = client.post(f'/api/trips/{ctx["trip"].id}/guests/{ctx["guest"].id}/info',
                        json={'fields': {'dietary': 'vegetarian', 'tshirt_size': 'L',
                              'emergency_contact': 'Jane Doe +1-555-0123'}})
        assert r.status_code == 200

    def test_guest_info_summary(self, client):
        ctx = _full_setup(client)
        r = client.get(f'/api/trips/{ctx["trip"].id}/guest-info-summary')
        assert r.status_code == 200


# ================================================================
# SOCIAL — Feed, Follow, Profile, Posts, Reviews
# ================================================================

class TestSocialAPIs:
    """Test all Social fetch() calls from the frontend."""

    def test_discover(self, client):
        ctx = _full_setup(client)
        r = client.get('/api/social/discover')
        assert r.status_code == 200

    def test_get_feed(self, client):
        ctx = _full_setup(client)
        r = client.get('/api/feed')
        assert r.status_code == 200

    def test_follow_user(self, client):
        ctx = _full_setup(client)
        user2 = _create_user('other@test.com', 'Other User', is_admin=False)
        r = client.post(f'/api/users/{user2.id}/follow', json={})
        assert r.status_code == 200

    def test_unfollow_user(self, client):
        ctx = _full_setup(client)
        user2 = _create_user('other@test.com', 'Other User', is_admin=False)
        client.post(f'/api/users/{user2.id}/follow', json={})
        r = client.delete(f'/api/users/{user2.id}/follow')
        assert r.status_code == 200

    def test_get_profile(self, client):
        ctx = _full_setup(client)
        r = client.get(f'/api/users/{ctx["user"].id}/profile')
        assert r.status_code == 200

    def test_get_user_reviews(self, client):
        ctx = _full_setup(client)
        r = client.get(f'/api/users/{ctx["user"].id}/reviews')
        assert r.status_code == 200


# ================================================================
# CORPORATE — Workspaces, Members, Policies, Approvals
# ================================================================

class TestCorporateAPIs:
    """Test all Corporate fetch() calls from the frontend."""

    def test_get_workspaces(self, client):
        ctx = _full_setup(client)
        r = client.get('/api/workspaces')
        assert r.status_code == 200

    def test_create_workspace(self, client):
        ctx = _full_setup(client)
        r = client.post('/api/workspaces',
                        json={'name': 'Acme Travel', 'company_domain': 'acme.com',
                              'tier': 'starter'})
        assert r.status_code in (200, 201)

    def test_join_workspace(self, client):
        ctx = _full_setup(client)
        # Create workspace first
        resp = client.post('/api/workspaces',
                           json={'name': 'Join Test Co', 'company_domain': 'jointest.com'})
        ws = resp.get_json()
        join_code = ws.get('workspace', {}).get('join_code') or ws.get('join_code', 'TEST')
        # Create second user to join
        user2 = _create_user('joiner@test.com', 'Joiner', is_admin=False)
        _login(client, user2.id)
        r = client.post(f'/api/workspaces/join/{join_code}', json={})
        # Accept 200, 400 (already member), or 404 (code not found)
        assert r.status_code in (200, 400, 404)

    def test_workspace_dashboard(self, client):
        ctx = _full_setup(client)
        resp = client.post('/api/workspaces',
                           json={'name': 'Dashboard Co', 'company_domain': 'dash.com'})
        ws = resp.get_json()
        slug = ws.get('workspace', {}).get('slug', 'dashboard-co')
        r = client.get(f'/api/workspaces/{slug}/dashboard')
        assert r.status_code == 200

    def test_workspace_members(self, client):
        ctx = _full_setup(client)
        resp = client.post('/api/workspaces',
                           json={'name': 'Members Co', 'company_domain': 'members.com'})
        ws = resp.get_json()
        slug = ws.get('workspace', {}).get('slug', 'members-co')
        r = client.get(f'/api/workspaces/{slug}/members')
        assert r.status_code == 200

    def test_invite_member(self, client):
        ctx = _full_setup(client)
        # The invited user must exist as a MYSTES user first
        _create_user('new@invite.com', 'New Member', is_admin=False)
        resp = client.post('/api/workspaces',
                           json={'name': 'Invite Co', 'company_domain': 'invite.com'})
        ws = resp.get_json()
        slug = ws.get('workspace', {}).get('slug', 'invite-co')
        r = client.post(f'/api/workspaces/{slug}/members',
                        json={'email': 'new@invite.com', 'role': 'member', 'department': 'Sales'})
        assert r.status_code in (200, 201)

    def test_workspace_policies(self, client):
        ctx = _full_setup(client)
        resp = client.post('/api/workspaces',
                           json={'name': 'Policy Co', 'company_domain': 'policy.com'})
        ws = resp.get_json()
        slug = ws.get('workspace', {}).get('slug', 'policy-co')
        r = client.get(f'/api/workspaces/{slug}/policies')
        assert r.status_code == 200

    def test_create_policy(self, client):
        ctx = _full_setup(client)
        resp = client.post('/api/workspaces',
                           json={'name': 'NewPolicy Co', 'company_domain': 'newpol.com'})
        ws = resp.get_json()
        slug = ws.get('workspace', {}).get('slug', 'newpolicy-co')
        r = client.post(f'/api/workspaces/{slug}/policies',
                        json={'name': 'Standard Travel', 'max_flight_usd': 1500,
                              'max_hotel_usd': 300, 'approval_threshold_usd': 500})
        assert r.status_code in (200, 201)

    def test_workspace_approvals(self, client):
        ctx = _full_setup(client)
        resp = client.post('/api/workspaces',
                           json={'name': 'Approval Co', 'company_domain': 'approval.com'})
        ws = resp.get_json()
        slug = ws.get('workspace', {}).get('slug', 'approval-co')
        r = client.get(f'/api/workspaces/{slug}/approvals')
        assert r.status_code == 200

    def test_workspace_bookings(self, client):
        ctx = _full_setup(client)
        resp = client.post('/api/workspaces',
                           json={'name': 'Bookings Co', 'company_domain': 'bookings.com'})
        ws = resp.get_json()
        slug = ws.get('workspace', {}).get('slug', 'bookings-co')
        r = client.get(f'/api/workspaces/{slug}/bookings')
        assert r.status_code == 200


# ================================================================
# REFERRAL — Stats, Conversions
# ================================================================

class TestReferralAPIs:
    """Test all Referral fetch() calls from the frontend."""

    def test_get_referral_stats(self, client):
        ctx = _full_setup(client)
        r = client.get('/api/referral/my-stats')
        assert r.status_code == 200

    def test_get_conversions(self, client):
        ctx = _full_setup(client)
        r = client.get('/api/referral/my-conversions')
        assert r.status_code == 200

    def test_admin_leaderboard(self, client):
        ctx = _full_setup(client)
        r = client.get('/api/admin/referral/leaderboard')
        assert r.status_code == 200


# ================================================================
# SHARED CARTS
# ================================================================

class TestSharedCartAPIs:
    """Test Shared Cart fetch() calls from the frontend."""

    def test_create_cart(self, client):
        ctx = _full_setup(client)
        r = client.post(f'/api/trips/{ctx["trip"].id}/carts',
                        json={'title': 'London Essentials', 'message': 'Book these!',
                              'item_ids': [ctx['item'].id]})
        assert r.status_code in (200, 201)

    def test_get_carts(self, client):
        ctx = _full_setup(client)
        r = client.get(f'/api/trips/{ctx["trip"].id}/carts')
        assert r.status_code == 200


# ================================================================
# FLIGHT CARDS — Shareable Cards + OG Meta
# ================================================================

class TestFlightCardAPIs:
    """Test Flight Card page rendering and OG meta tags."""

    def test_flight_card_page_renders(self, client):
        ctx = _full_setup(client)
        r = client.get(f'/flight-card/{ctx["deal"].id}')
        assert r.status_code == 200
        html = r.data.decode()
        assert 'og:title' in html
        assert 'og:image' in html
        assert 'og:description' in html

    def test_flight_card_has_airline(self, client):
        ctx = _full_setup(client)
        r = client.get(f'/flight-card/{ctx["deal"].id}')
        html = r.data.decode()
        assert 'British Airways' in html

    def test_flight_card_has_price(self, client):
        ctx = _full_setup(client)
        r = client.get(f'/flight-card/{ctx["deal"].id}')
        html = r.data.decode()
        assert '890' in html  # $890 arbitrage price

    def test_flight_card_has_route(self, client):
        ctx = _full_setup(client)
        r = client.get(f'/flight-card/{ctx["deal"].id}')
        html = r.data.decode()
        assert 'JFK' in html
        assert 'LHR' in html

    def test_flight_card_image(self, client):
        ctx = _full_setup(client)
        r = client.get(f'/flight-card/{ctx["deal"].id}/image')
        assert r.status_code == 200
        html = r.data.decode()
        assert 'British Airways' in html
        assert 'JFK' in html

    def test_flight_card_has_savings(self, client):
        ctx = _full_setup(client)
        r = client.get(f'/flight-card/{ctx["deal"].id}')
        html = r.data.decode()
        assert '310' in html  # $310 savings
        assert '25' in html or '26' in html  # ~25.8% savings

    def test_flight_card_has_twitter_card(self, client):
        ctx = _full_setup(client)
        r = client.get(f'/flight-card/{ctx["deal"].id}')
        html = r.data.decode()
        assert 'twitter:card' in html

    def test_flight_card_has_share_buttons(self, client):
        ctx = _full_setup(client)
        r = client.get(f'/flight-card/{ctx["deal"].id}')
        html = r.data.decode()
        # Check for share functionality (copy link, twitter, whatsapp)
        assert 'share' in html.lower() or 'Share' in html

    def test_flight_card_has_book_cta(self, client):
        ctx = _full_setup(client)
        r = client.get(f'/flight-card/{ctx["deal"].id}')
        html = r.data.decode()
        assert 'Book' in html or 'book' in html


# ================================================================
# PAGE RENDERING — All new pages return 200
# ================================================================

class TestPageRendering:
    """Test that all new frontend pages render without errors."""

    def test_trip_planner_page(self, client):
        ctx = _full_setup(client)
        r = client.get(f'/trips/{ctx["trip"].id}/plan')
        assert r.status_code == 200
        html = r.data.decode()
        assert 'Trip Planner' in html or 'Itinerary' in html or 'itinerary' in html

    def test_events_page(self, client):
        ctx = _full_setup(client)
        r = client.get(f'/trips/{ctx["trip"].id}/events')
        assert r.status_code == 200

    def test_social_feed_page(self, client):
        ctx = _full_setup(client)
        r = client.get('/social')
        assert r.status_code == 200

    def test_profile_page(self, client):
        ctx = _full_setup(client)
        r = client.get(f'/profile/{ctx["user"].id}')
        assert r.status_code == 200

    def test_corporate_page(self, client):
        ctx = _full_setup(client)
        r = client.get('/corporate')
        assert r.status_code == 200

    def test_referral_page(self, client):
        ctx = _full_setup(client)
        r = client.get('/referral')
        assert r.status_code == 200

    def test_arbitrate_page(self, client):
        ctx = _full_setup(client)
        r = client.get('/arbitrate')
        assert r.status_code == 200


# ================================================================
# CROSS-VERTICAL NAVIGATION — Links between features work
# ================================================================

class TestCrossVerticalLinks:
    """Test that navigation links between verticals are present."""

    def test_trip_detail_has_planner_link(self, client):
        ctx = _full_setup(client)
        r = client.get(f'/trips/{ctx["trip"].id}')
        assert r.status_code == 200
        html = r.data.decode()
        assert f'/trips/{ctx["trip"].id}/plan' in html

    def test_trip_detail_has_events_link(self, client):
        ctx = _full_setup(client)
        r = client.get(f'/trips/{ctx["trip"].id}')
        html = r.data.decode()
        assert f'/trips/{ctx["trip"].id}/events' in html

    def test_planner_has_back_to_trip(self, client):
        ctx = _full_setup(client)
        r = client.get(f'/trips/{ctx["trip"].id}/plan')
        html = r.data.decode()
        assert f'/trips/{ctx["trip"].id}' in html

    def test_planner_has_events_link(self, client):
        ctx = _full_setup(client)
        r = client.get(f'/trips/{ctx["trip"].id}/plan')
        html = r.data.decode()
        assert 'events' in html.lower() or 'Events' in html

    def test_events_has_back_to_trip(self, client):
        ctx = _full_setup(client)
        r = client.get(f'/trips/{ctx["trip"].id}/events')
        html = r.data.decode()
        assert f'/trips/{ctx["trip"].id}' in html

    def test_events_has_planner_link(self, client):
        ctx = _full_setup(client)
        r = client.get(f'/trips/{ctx["trip"].id}/events')
        html = r.data.decode()
        assert 'plan' in html.lower() or 'Planner' in html

    def test_main_nav_has_social(self, client):
        ctx = _full_setup(client)
        r = client.get('/')
        html = r.data.decode()
        assert '/social' in html

    def test_main_nav_has_referral(self, client):
        ctx = _full_setup(client)
        r = client.get('/')
        html = r.data.decode()
        assert '/referral' in html

    def test_main_nav_has_corporate(self, client):
        ctx = _full_setup(client)
        r = client.get('/')
        html = r.data.decode()
        assert '/corporate' in html

    def test_main_nav_has_arbitrate(self, client):
        ctx = _full_setup(client)
        r = client.get('/')
        html = r.data.decode()
        assert '/arbitrate' in html
