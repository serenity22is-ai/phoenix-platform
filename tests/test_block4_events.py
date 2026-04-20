"""
MYSTES Tests — Block 4 (Builds #225-227: Managed Mode, Events, Guest Info, QR Check-In)

Tests for:
- Models: TripAnnouncement, TicketTier, TripGuestInfo, TripPlan managed/event fields
- Managed mode (#225): set mode, roster, announcements, capacity, waitlist promotion
- Event system (#226): event config, ticket tiers CRUD, purchase/sold-out/waitlist
- Guest info (#227): submit/read info, admin summary, plus-ones, QR check-in
- Feature flag gating: all endpoints return 403 when flags disabled
- Access control: admin-only operations, self-service guest info

Run: python3 -m pytest tests/test_block4_events.py -v
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
    User, TripPlan, TripMember, TripGuest,
    TripAnnouncement, TicketTier, TripGuestInfo,
    FeatureFlag,
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


def _setup_admin_trip(client):
    """Create a user logged in as trip admin, return (user, trip)."""
    user = _create_user('admin@t.com', 'Admin')
    trip = _create_trip(user.id)
    _login_client_as(client, user.id)
    return user, trip


# ================================================================
# Part 1: Model Tests
# ================================================================

class TestTripPlanExtensions:
    """Test new fields on TripPlan model."""

    def test_default_mode_collaborative(self):
        user = _create_user('u@t.com')
        trip = _create_trip(user.id)
        assert trip.mode == 'collaborative'
        assert trip.trip_type == 'trip'
        assert trip.capacity is None
        assert trip.waitlist_enabled is False

    def test_managed_trip_fields(self):
        user = _create_user('u@t.com')
        trip = _create_trip(user.id, mode='managed')
        trip.capacity = 50
        trip.waitlist_enabled = True
        trip.payment_deadline = datetime(2026, 6, 1, tzinfo=timezone.utc)
        db.session.commit()
        assert trip.mode == 'managed'
        assert trip.capacity == 50
        assert trip.waitlist_enabled is True

    def test_event_trip_to_dict(self):
        user = _create_user('u@t.com')
        trip = _create_trip(user.id, trip_type='event')
        trip.event_name = 'Summer Reunion'
        trip.venue_name = 'Beachside Resort'
        trip.registration_type = 'public'
        db.session.commit()
        d = trip.to_dict()
        assert d['trip_type'] == 'event'
        assert d['event_name'] == 'Summer Reunion'
        assert d['venue_name'] == 'Beachside Resort'
        assert d['registration_type'] == 'public'

    def test_trip_to_dict_no_event_fields_for_trip(self):
        user = _create_user('u@t.com')
        trip = _create_trip(user.id)
        d = trip.to_dict()
        assert 'event_name' not in d


class TestTripAnnouncementModel:
    """Test TripAnnouncement model."""

    def test_create_announcement(self):
        user = _create_user('u@t.com')
        trip = _create_trip(user.id)
        a = TripAnnouncement(trip_id=trip.id, sender_user_id=user.id,
                              body='Hello everyone!', audience='all')
        db.session.add(a)
        db.session.commit()
        assert a.id is not None
        assert a.body == 'Hello everyone!'

    def test_announcement_to_dict(self):
        user = _create_user('u@t.com')
        trip = _create_trip(user.id)
        a = TripAnnouncement(trip_id=trip.id, sender_user_id=user.id, body='Test')
        db.session.add(a)
        db.session.commit()
        d = a.to_dict()
        assert d['body'] == 'Test'
        assert d['sender_name'] == 'Test User'
        assert d['audience'] == 'all'

    def test_announcement_audiences(self):
        assert 'confirmed_only' in TripAnnouncement.AUDIENCES
        assert 'pending_only' in TripAnnouncement.AUDIENCES
        assert 'waitlisted_only' in TripAnnouncement.AUDIENCES


class TestTicketTierModel:
    """Test TicketTier model."""

    def test_create_tier(self):
        user = _create_user('u@t.com')
        trip = _create_trip(user.id, trip_type='event')
        tier = TicketTier(trip_id=trip.id, name='VIP', price_usd=99.0, capacity=50)
        db.session.add(tier)
        db.session.commit()
        assert tier.spots_remaining == 50
        assert tier.is_sold_out is False

    def test_tier_sold_out(self):
        user = _create_user('u@t.com')
        trip = _create_trip(user.id, trip_type='event')
        tier = TicketTier(trip_id=trip.id, name='GA', price_usd=25.0,
                          capacity=2, sold_count=2)
        db.session.add(tier)
        db.session.commit()
        assert tier.is_sold_out is True
        assert tier.spots_remaining == 0

    def test_tier_unlimited_capacity(self):
        user = _create_user('u@t.com')
        trip = _create_trip(user.id)
        tier = TicketTier(trip_id=trip.id, name='Free', price_usd=0.0, capacity=None)
        db.session.add(tier)
        db.session.commit()
        assert tier.spots_remaining is None
        assert tier.is_sold_out is False

    def test_tier_to_dict(self):
        user = _create_user('u@t.com')
        trip = _create_trip(user.id)
        tier = TicketTier(trip_id=trip.id, name='Standard', price_usd=50.0,
                          capacity=100, sold_count=10, includes_travel=True)
        db.session.add(tier)
        db.session.commit()
        d = tier.to_dict()
        assert d['name'] == 'Standard'
        assert d['price_usd'] == 50.0
        assert d['spots_remaining'] == 90
        assert d['includes_travel'] is True


class TestTripGuestInfoModel:
    """Test TripGuestInfo model."""

    def test_create_info(self):
        user = _create_user('u@t.com')
        trip = _create_trip(user.id)
        guest = _create_guest(trip.id, 'Alice', user_id=user.id)
        info = TripGuestInfo(guest_id=guest.id, field_key='dietary', field_value='Vegetarian')
        db.session.add(info)
        db.session.commit()
        assert info.id is not None
        assert info.field_key == 'dietary'

    def test_info_unique_constraint(self):
        user = _create_user('u@t.com')
        trip = _create_trip(user.id)
        guest = _create_guest(trip.id, 'Alice')
        info1 = TripGuestInfo(guest_id=guest.id, field_key='dietary', field_value='Vegan')
        db.session.add(info1)
        db.session.commit()
        info2 = TripGuestInfo(guest_id=guest.id, field_key='dietary', field_value='Gluten-free')
        db.session.add(info2)
        with pytest.raises(Exception):
            db.session.commit()
        db.session.rollback()

    def test_info_to_dict(self):
        user = _create_user('u@t.com')
        trip = _create_trip(user.id)
        guest = _create_guest(trip.id, 'Alice')
        info = TripGuestInfo(guest_id=guest.id, field_key='tshirt_size', field_value='L')
        db.session.add(info)
        db.session.commit()
        d = info.to_dict()
        assert d['field_key'] == 'tshirt_size'
        assert d['field_value'] == 'L'


# ================================================================
# Part 2: Feature Flag Gating
# ================================================================

class TestFeatureFlagGating:
    """All Phase C endpoints return 403 when flags are disabled."""

    def test_mode_gated(self, client):
        user, trip = _setup_admin_trip(client)
        r = client.put(f'/api/trips/{trip.id}/mode', json={'mode': 'managed'})
        assert r.status_code == 403
        assert 'not enabled' in r.get_json()['error']

    def test_roster_gated(self, client):
        user, trip = _setup_admin_trip(client)
        r = client.get(f'/api/trips/{trip.id}/roster')
        assert r.status_code == 403

    def test_announcements_gated(self, client):
        user, trip = _setup_admin_trip(client)
        r = client.post(f'/api/trips/{trip.id}/announcements', json={'body': 'Test'})
        assert r.status_code == 403

    def test_tiers_gated(self, client):
        user, trip = _setup_admin_trip(client)
        _enable_flags('managed_mode')  # managed is enabled but NOT event_system
        r = client.post(f'/api/trips/{trip.id}/tiers',
                        json={'name': 'VIP', 'price_usd': 100})
        assert r.status_code == 403

    def test_guest_info_gated(self, client):
        user, trip = _setup_admin_trip(client)
        guest = _create_guest(trip.id, 'Alice', user_id=user.id)
        r = client.post(f'/api/trips/{trip.id}/guests/{guest.id}/info',
                        json={'fields': {'dietary': 'Vegan'}})
        assert r.status_code == 403

    def test_checkin_gated(self, client):
        user, trip = _setup_admin_trip(client)
        guest = _create_guest(trip.id, 'Alice')
        r = client.post(f'/api/trips/{trip.id}/guests/{guest.id}/checkin')
        assert r.status_code == 403


# ================================================================
# Part 3: Managed Mode API (#225)
# ================================================================

class TestManagedModeAPI:
    """Test managed mode endpoints."""

    def test_set_mode_managed(self, client):
        user, trip = _setup_admin_trip(client)
        _enable_flags('managed_mode')
        r = client.put(f'/api/trips/{trip.id}/mode', json={'mode': 'managed'})
        assert r.status_code == 200
        assert r.get_json()['mode'] == 'managed'

    def test_set_mode_collaborative(self, client):
        user, trip = _setup_admin_trip(client)
        trip.mode = 'managed'
        db.session.commit()
        _enable_flags('managed_mode')
        r = client.put(f'/api/trips/{trip.id}/mode', json={'mode': 'collaborative'})
        assert r.status_code == 200
        assert r.get_json()['mode'] == 'collaborative'

    def test_set_mode_invalid(self, client):
        user, trip = _setup_admin_trip(client)
        _enable_flags('managed_mode')
        r = client.put(f'/api/trips/{trip.id}/mode', json={'mode': 'chaos'})
        assert r.status_code == 400

    def test_set_mode_non_admin(self, client):
        owner = _create_user('owner@t.com')
        viewer = _create_user('viewer@t.com')
        trip = _create_trip(owner.id)
        member = TripMember(trip_plan_id=trip.id, user_id=viewer.id, role='viewer')
        db.session.add(member)
        db.session.commit()
        _enable_flags('managed_mode')
        _login_client_as(client, viewer.id)
        r = client.put(f'/api/trips/{trip.id}/mode', json={'mode': 'managed'})
        assert r.status_code == 403

    def test_roster_dashboard(self, client):
        user, trip = _setup_admin_trip(client)
        _enable_flags('managed_mode')
        g1 = _create_guest(trip.id, 'Alice', user_id=user.id, rsvp_status='attending')
        g2 = _create_guest(trip.id, 'Bob', rsvp_status='waitlisted')
        g3 = _create_guest(trip.id, 'Carol', rsvp_status='invited')

        r = client.get(f'/api/trips/{trip.id}/roster')
        assert r.status_code == 200
        data = r.get_json()
        assert len(data['roster']) == 3
        assert data['summary']['confirmed'] == 1
        assert data['summary']['waitlisted'] == 1
        assert data['summary']['total'] == 3

    def test_set_capacity(self, client):
        user, trip = _setup_admin_trip(client)
        _enable_flags('managed_mode')

        r = client.put(f'/api/trips/{trip.id}/capacity', json={
            'capacity': 100,
            'waitlist_enabled': True,
            'payment_deadline': '2026-06-01T00:00:00',
        })
        assert r.status_code == 200
        data = r.get_json()
        assert data['capacity'] == 100
        assert data['waitlist_enabled'] is True
        assert '2026-06-01' in data['payment_deadline']

    def test_set_capacity_unlimited(self, client):
        user, trip = _setup_admin_trip(client)
        trip.capacity = 50
        db.session.commit()
        _enable_flags('managed_mode')

        r = client.put(f'/api/trips/{trip.id}/capacity', json={'capacity': None})
        assert r.status_code == 200
        assert r.get_json()['capacity'] is None


class TestAnnouncementsAPI:
    """Test announcement endpoints."""

    def test_send_announcement(self, client):
        user, trip = _setup_admin_trip(client)
        _enable_flags('managed_mode')

        r = client.post(f'/api/trips/{trip.id}/announcements',
                        json={'body': 'Welcome to the trip!'})
        assert r.status_code == 200
        data = r.get_json()
        assert data['announcement']['body'] == 'Welcome to the trip!'
        assert data['announcement']['audience'] == 'all'

    def test_send_announcement_empty_body(self, client):
        user, trip = _setup_admin_trip(client)
        _enable_flags('managed_mode')
        r = client.post(f'/api/trips/{trip.id}/announcements', json={'body': ''})
        assert r.status_code == 400

    def test_send_announcement_with_audience(self, client):
        user, trip = _setup_admin_trip(client)
        _enable_flags('managed_mode')
        r = client.post(f'/api/trips/{trip.id}/announcements',
                        json={'body': 'Pay up!', 'audience': 'pending_only'})
        assert r.status_code == 200
        assert r.get_json()['announcement']['audience'] == 'pending_only'

    def test_send_announcement_non_admin(self, client):
        owner = _create_user('owner@t.com')
        viewer = _create_user('viewer@t.com')
        trip = _create_trip(owner.id)
        member = TripMember(trip_plan_id=trip.id, user_id=viewer.id, role='viewer')
        db.session.add(member)
        db.session.commit()
        _enable_flags('managed_mode')
        _login_client_as(client, viewer.id)
        r = client.post(f'/api/trips/{trip.id}/announcements',
                        json={'body': 'Unauthorized!'})
        assert r.status_code == 403

    def test_list_announcements(self, client):
        user, trip = _setup_admin_trip(client)
        _enable_flags('managed_mode')

        client.post(f'/api/trips/{trip.id}/announcements', json={'body': 'First'})
        client.post(f'/api/trips/{trip.id}/announcements', json={'body': 'Second'})

        r = client.get(f'/api/trips/{trip.id}/announcements')
        assert r.status_code == 200
        assert r.get_json()['count'] == 2

    def test_list_announcements_empty(self, client):
        user, trip = _setup_admin_trip(client)
        _enable_flags('managed_mode')
        r = client.get(f'/api/trips/{trip.id}/announcements')
        assert r.status_code == 200
        assert r.get_json()['count'] == 0


class TestWaitlistAPI:
    """Test waitlist promotion."""

    def test_promote_from_waitlist(self, client):
        user, trip = _setup_admin_trip(client)
        _enable_flags('managed_mode')
        g = _create_guest(trip.id, 'Waiter', rsvp_status='waitlisted')

        r = client.post(f'/api/trips/{trip.id}/waitlist/promote', json={})
        assert r.status_code == 200
        assert r.get_json()['guest']['rsvp_status'] == 'attending'

    def test_promote_specific_guest(self, client):
        user, trip = _setup_admin_trip(client)
        _enable_flags('managed_mode')
        g1 = _create_guest(trip.id, 'First', rsvp_status='waitlisted')
        g2 = _create_guest(trip.id, 'Second', rsvp_status='waitlisted')

        r = client.post(f'/api/trips/{trip.id}/waitlist/promote',
                        json={'guest_id': g2.id})
        assert r.status_code == 200
        assert r.get_json()['guest']['display_name'] == 'Second'

    def test_promote_no_waitlisted(self, client):
        user, trip = _setup_admin_trip(client)
        _enable_flags('managed_mode')
        r = client.post(f'/api/trips/{trip.id}/waitlist/promote', json={})
        assert r.status_code == 404

    def test_promote_at_capacity(self, client):
        user, trip = _setup_admin_trip(client)
        trip.capacity = 1
        db.session.commit()
        _enable_flags('managed_mode')
        _create_guest(trip.id, 'Full', rsvp_status='attending')
        _create_guest(trip.id, 'Waiter', rsvp_status='waitlisted')

        r = client.post(f'/api/trips/{trip.id}/waitlist/promote', json={})
        assert r.status_code == 400
        assert 'capacity' in r.get_json()['error']


# ================================================================
# Part 4: Event System API (#226)
# ================================================================

class TestEventConfigAPI:
    """Test event configuration."""

    def test_configure_event(self, client):
        user, trip = _setup_admin_trip(client)
        _enable_flags('event_system')

        r = client.put(f'/api/trips/{trip.id}/event-config', json={
            'event_name': 'Summer BBQ',
            'venue_name': 'Central Park',
            'registration_type': 'public',
        })
        assert r.status_code == 200
        data = r.get_json()
        assert data['trip']['trip_type'] == 'event'
        assert data['trip']['event_name'] == 'Summer BBQ'

    def test_event_forces_managed_mode(self, client):
        user, trip = _setup_admin_trip(client)
        assert trip.mode == 'collaborative'
        _enable_flags('event_system')

        client.put(f'/api/trips/{trip.id}/event-config', json={
            'event_name': 'Test Event',
        })
        db.session.refresh(trip)
        assert trip.mode == 'managed'

    def test_configure_event_non_admin(self, client):
        owner = _create_user('owner@t.com')
        viewer = _create_user('viewer@t.com')
        trip = _create_trip(owner.id)
        member = TripMember(trip_plan_id=trip.id, user_id=viewer.id, role='viewer')
        db.session.add(member)
        db.session.commit()
        _enable_flags('event_system')
        _login_client_as(client, viewer.id)
        r = client.put(f'/api/trips/{trip.id}/event-config',
                       json={'event_name': 'Nope'})
        assert r.status_code == 403


class TestTicketTierAPI:
    """Test ticket tier CRUD."""

    def test_create_tier(self, client):
        user, trip = _setup_admin_trip(client)
        _enable_flags('event_system')

        r = client.post(f'/api/trips/{trip.id}/tiers', json={
            'name': 'VIP',
            'price_usd': 150.0,
            'capacity': 20,
            'includes_travel': True,
        })
        assert r.status_code == 200
        data = r.get_json()
        assert data['tier']['name'] == 'VIP'
        assert data['tier']['price_usd'] == 150.0
        assert data['tier']['spots_remaining'] == 20

    def test_create_tier_missing_name(self, client):
        user, trip = _setup_admin_trip(client)
        _enable_flags('event_system')
        r = client.post(f'/api/trips/{trip.id}/tiers', json={'price_usd': 50})
        assert r.status_code == 400

    def test_create_tier_negative_price(self, client):
        user, trip = _setup_admin_trip(client)
        _enable_flags('event_system')
        r = client.post(f'/api/trips/{trip.id}/tiers',
                        json={'name': 'Bad', 'price_usd': -10})
        assert r.status_code == 400

    def test_list_tiers(self, client):
        user, trip = _setup_admin_trip(client)
        _enable_flags('event_system')

        client.post(f'/api/trips/{trip.id}/tiers',
                    json={'name': 'GA', 'price_usd': 25, 'position': 1})
        client.post(f'/api/trips/{trip.id}/tiers',
                    json={'name': 'VIP', 'price_usd': 100, 'position': 0})

        r = client.get(f'/api/trips/{trip.id}/tiers')
        assert r.status_code == 200
        data = r.get_json()
        assert data['count'] == 2
        # Ordered by position
        assert data['tiers'][0]['name'] == 'VIP'

    def test_update_tier(self, client):
        user, trip = _setup_admin_trip(client)
        _enable_flags('event_system')
        resp = client.post(f'/api/trips/{trip.id}/tiers',
                           json={'name': 'Basic', 'price_usd': 30})
        tier_id = resp.get_json()['tier']['id']

        r = client.put(f'/api/trips/{trip.id}/tiers/{tier_id}',
                       json={'name': 'Standard', 'price_usd': 45})
        assert r.status_code == 200
        assert r.get_json()['tier']['name'] == 'Standard'
        assert r.get_json()['tier']['price_usd'] == 45

    def test_update_tier_not_found(self, client):
        user, trip = _setup_admin_trip(client)
        _enable_flags('event_system')
        r = client.put(f'/api/trips/{trip.id}/tiers/9999',
                       json={'name': 'Ghost'})
        assert r.status_code == 404

    def test_deactivate_tier(self, client):
        user, trip = _setup_admin_trip(client)
        _enable_flags('event_system')
        resp = client.post(f'/api/trips/{trip.id}/tiers',
                           json={'name': 'Temp', 'price_usd': 10})
        tier_id = resp.get_json()['tier']['id']

        r = client.delete(f'/api/trips/{trip.id}/tiers/{tier_id}')
        assert r.status_code == 200

        # Tier still exists but is inactive
        tier = db.session.get(TicketTier, tier_id)
        assert tier.is_active is False

    def test_free_tier(self, client):
        user, trip = _setup_admin_trip(client)
        _enable_flags('event_system')
        r = client.post(f'/api/trips/{trip.id}/tiers',
                        json={'name': 'Free Entry', 'price_usd': 0})
        assert r.status_code == 200
        assert r.get_json()['tier']['price_usd'] == 0.0


class TestTicketPurchaseAPI:
    """Test ticket purchase/registration flow."""

    def test_purchase_ticket(self, client):
        user, trip = _setup_admin_trip(client)
        _enable_flags('event_system')
        guest = _create_guest(trip.id, 'Buyer', user_id=user.id)

        resp = client.post(f'/api/trips/{trip.id}/tiers',
                           json={'name': 'GA', 'price_usd': 25, 'capacity': 10})
        tier_id = resp.get_json()['tier']['id']

        r = client.post(f'/api/trips/{trip.id}/tiers/{tier_id}/purchase',
                        json={'guest_id': guest.id})
        assert r.status_code == 200
        data = r.get_json()
        assert data['guest']['rsvp_status'] == 'attending'
        assert data['tier']['sold_count'] == 1
        assert data['tier']['spots_remaining'] == 9

    def test_purchase_auto_detect_guest(self, client):
        user, trip = _setup_admin_trip(client)
        _enable_flags('event_system')
        guest = _create_guest(trip.id, 'Self', user_id=user.id)

        resp = client.post(f'/api/trips/{trip.id}/tiers',
                           json={'name': 'GA', 'price_usd': 25, 'capacity': 10})
        tier_id = resp.get_json()['tier']['id']

        r = client.post(f'/api/trips/{trip.id}/tiers/{tier_id}/purchase', json={})
        assert r.status_code == 200

    def test_purchase_sold_out(self, client):
        user, trip = _setup_admin_trip(client)
        _enable_flags('event_system')
        guest = _create_guest(trip.id, 'Late', user_id=user.id)

        tier = TicketTier(trip_id=trip.id, name='Limited', price_usd=50,
                          capacity=1, sold_count=1, is_active=True)
        db.session.add(tier)
        db.session.commit()

        r = client.post(f'/api/trips/{trip.id}/tiers/{tier.id}/purchase',
                        json={'guest_id': guest.id})
        assert r.status_code == 400
        assert 'sold out' in r.get_json()['error']

    def test_purchase_sold_out_waitlist(self, client):
        """Sold out tier with waitlist enabled should waitlist the guest."""
        user, trip = _setup_admin_trip(client)
        trip.waitlist_enabled = True
        db.session.commit()
        _enable_flags('event_system')
        guest = _create_guest(trip.id, 'Waiter', user_id=user.id)

        tier = TicketTier(trip_id=trip.id, name='Limited', price_usd=50,
                          capacity=1, sold_count=1, is_active=True)
        db.session.add(tier)
        db.session.commit()

        r = client.post(f'/api/trips/{trip.id}/tiers/{tier.id}/purchase',
                        json={'guest_id': guest.id})
        assert r.status_code == 200
        assert r.get_json()['waitlisted'] is True

    def test_purchase_inactive_tier(self, client):
        user, trip = _setup_admin_trip(client)
        _enable_flags('event_system')
        guest = _create_guest(trip.id, 'Late', user_id=user.id)

        tier = TicketTier(trip_id=trip.id, name='Dead', price_usd=50,
                          is_active=False)
        db.session.add(tier)
        db.session.commit()

        r = client.post(f'/api/trips/{trip.id}/tiers/{tier.id}/purchase',
                        json={'guest_id': guest.id})
        assert r.status_code == 404

    def test_purchase_guest_not_found(self, client):
        user, trip = _setup_admin_trip(client)
        _enable_flags('event_system')

        tier = TicketTier(trip_id=trip.id, name='GA', price_usd=25, is_active=True)
        db.session.add(tier)
        db.session.commit()

        r = client.post(f'/api/trips/{trip.id}/tiers/{tier.id}/purchase',
                        json={'guest_id': 9999})
        assert r.status_code == 404


# ================================================================
# Part 5: Guest Info Collection API (#227)
# ================================================================

class TestGuestInfoAPI:
    """Test guest info submission and retrieval."""

    def test_submit_guest_info(self, client):
        user, trip = _setup_admin_trip(client)
        _enable_flags('guest_info_collection')
        guest = _create_guest(trip.id, 'Alice', user_id=user.id)

        r = client.post(f'/api/trips/{trip.id}/guests/{guest.id}/info', json={
            'fields': {
                'dietary': 'Vegetarian',
                'tshirt_size': 'M',
                'emergency_contact': 'Mom: 555-1234',
            },
        })
        assert r.status_code == 200
        assert r.get_json()['count'] == 3

    def test_submit_empty_fields(self, client):
        user, trip = _setup_admin_trip(client)
        _enable_flags('guest_info_collection')
        guest = _create_guest(trip.id, 'Alice', user_id=user.id)

        r = client.post(f'/api/trips/{trip.id}/guests/{guest.id}/info',
                        json={'fields': {}})
        assert r.status_code == 400

    def test_get_guest_info(self, client):
        user, trip = _setup_admin_trip(client)
        _enable_flags('guest_info_collection')
        guest = _create_guest(trip.id, 'Alice', user_id=user.id)

        # Submit info first
        client.post(f'/api/trips/{trip.id}/guests/{guest.id}/info', json={
            'fields': {'dietary': 'Vegan', 'passport_no': 'AB123456'},
        })

        r = client.get(f'/api/trips/{trip.id}/guests/{guest.id}/info')
        assert r.status_code == 200
        data = r.get_json()
        assert data['fields']['dietary'] == 'Vegan'
        assert data['fields']['passport_no'] == 'AB123456'
        assert data['count'] == 2

    def test_update_existing_info(self, client):
        """Submitting same field_key should update, not duplicate."""
        user, trip = _setup_admin_trip(client)
        _enable_flags('guest_info_collection')
        guest = _create_guest(trip.id, 'Alice', user_id=user.id)

        client.post(f'/api/trips/{trip.id}/guests/{guest.id}/info',
                    json={'fields': {'dietary': 'Vegan'}})
        client.post(f'/api/trips/{trip.id}/guests/{guest.id}/info',
                    json={'fields': {'dietary': 'Pescatarian'}})

        r = client.get(f'/api/trips/{trip.id}/guests/{guest.id}/info')
        assert r.get_json()['fields']['dietary'] == 'Pescatarian'
        assert r.get_json()['count'] == 1

    def test_guest_info_summary(self, client):
        user, trip = _setup_admin_trip(client)
        _enable_flags('guest_info_collection')
        g1 = _create_guest(trip.id, 'Alice', user_id=user.id)
        g2 = _create_guest(trip.id, 'Bob')

        # Add info for both
        info1 = TripGuestInfo(guest_id=g1.id, field_key='dietary', field_value='Vegan')
        info2 = TripGuestInfo(guest_id=g2.id, field_key='dietary', field_value='Halal')
        db.session.add_all([info1, info2])
        db.session.commit()

        r = client.get(f'/api/trips/{trip.id}/guest-info-summary')
        assert r.status_code == 200
        data = r.get_json()
        assert data['guest_count'] == 2
        diets = {s['display_name']: s['fields'].get('dietary') for s in data['summary']}
        assert diets['Alice'] == 'Vegan'
        assert diets['Bob'] == 'Halal'

    def test_guest_info_summary_non_admin(self, client):
        owner = _create_user('owner@t.com')
        viewer = _create_user('viewer@t.com')
        trip = _create_trip(owner.id)
        member = TripMember(trip_plan_id=trip.id, user_id=viewer.id, role='viewer')
        db.session.add(member)
        db.session.commit()
        _enable_flags('guest_info_collection')
        _login_client_as(client, viewer.id)
        r = client.get(f'/api/trips/{trip.id}/guest-info-summary')
        assert r.status_code == 403

    def test_guest_info_self_only(self, client):
        """Non-admin can only submit their own guest info."""
        owner = _create_user('owner@t.com')
        other = _create_user('other@t.com')
        trip = _create_trip(owner.id)
        member = TripMember(trip_plan_id=trip.id, user_id=other.id, role='viewer')
        db.session.add(member)
        db.session.commit()
        guest_other = _create_guest(trip.id, 'Other', user_id=other.id)
        guest_owner = _create_guest(trip.id, 'Owner', user_id=owner.id)

        _enable_flags('guest_info_collection')
        _login_client_as(client, other.id)

        # Can submit own info
        r = client.post(f'/api/trips/{trip.id}/guests/{guest_other.id}/info',
                        json={'fields': {'dietary': 'None'}})
        assert r.status_code == 200

        # Cannot submit owner's info
        r = client.post(f'/api/trips/{trip.id}/guests/{guest_owner.id}/info',
                        json={'fields': {'dietary': 'None'}})
        assert r.status_code == 403


# ================================================================
# Part 6: Plus-One API (#227)
# ================================================================

class TestPlusOneAPI:
    """Test plus-one functionality."""

    def test_add_plus_one(self, client):
        user, trip = _setup_admin_trip(client)
        _enable_flags('guest_info_collection')
        guest = _create_guest(trip.id, 'Alice', user_id=user.id, rsvp_status='attending')

        r = client.post(f'/api/trips/{trip.id}/guests/{guest.id}/plus-one',
                        json={'display_name': 'Alice Guest'})
        assert r.status_code == 200
        data = r.get_json()
        assert data['guest']['display_name'] == 'Alice Guest'
        assert data['guest']['rsvp_status'] == 'attending'

    def test_plus_one_missing_name(self, client):
        user, trip = _setup_admin_trip(client)
        _enable_flags('guest_info_collection')
        guest = _create_guest(trip.id, 'Alice', user_id=user.id)
        r = client.post(f'/api/trips/{trip.id}/guests/{guest.id}/plus-one', json={})
        assert r.status_code == 400

    def test_plus_one_at_capacity(self, client):
        user, trip = _setup_admin_trip(client)
        trip.capacity = 1
        db.session.commit()
        _enable_flags('guest_info_collection')
        guest = _create_guest(trip.id, 'Alice', user_id=user.id, rsvp_status='attending')

        r = client.post(f'/api/trips/{trip.id}/guests/{guest.id}/plus-one',
                        json={'display_name': 'No Room'})
        assert r.status_code == 400

    def test_plus_one_non_self(self, client):
        """Non-admin cannot add plus-one for someone else's guest record."""
        owner = _create_user('owner@t.com')
        other = _create_user('other@t.com')
        trip = _create_trip(owner.id)
        member = TripMember(trip_plan_id=trip.id, user_id=other.id, role='viewer')
        db.session.add(member)
        db.session.commit()
        owner_guest = _create_guest(trip.id, 'Owner', user_id=owner.id)
        _enable_flags('guest_info_collection')
        _login_client_as(client, other.id)

        r = client.post(f'/api/trips/{trip.id}/guests/{owner_guest.id}/plus-one',
                        json={'display_name': 'Intruder Guest'})
        assert r.status_code == 403


# ================================================================
# Part 7: QR Check-In API (#227)
# ================================================================

class TestQRCheckInAPI:
    """Test QR check-in endpoints."""

    def test_checkin_guest(self, client):
        user, trip = _setup_admin_trip(client)
        _enable_flags('qr_checkin')
        guest = _create_guest(trip.id, 'Alice', rsvp_status='attending')

        r = client.post(f'/api/trips/{trip.id}/guests/{guest.id}/checkin')
        assert r.status_code == 200
        data = r.get_json()
        assert data['checked_in_at'] is not None
        assert data['checkin_progress'] == '1/1'

    def test_checkin_already_checked_in(self, client):
        user, trip = _setup_admin_trip(client)
        _enable_flags('qr_checkin')
        guest = _create_guest(trip.id, 'Alice', rsvp_status='attending')
        guest.checked_in_at = datetime.now(timezone.utc)
        db.session.commit()

        r = client.post(f'/api/trips/{trip.id}/guests/{guest.id}/checkin')
        assert r.status_code == 200
        assert r.get_json()['already_checked_in'] is True

    def test_checkin_progress(self, client):
        user, trip = _setup_admin_trip(client)
        _enable_flags('qr_checkin')
        g1 = _create_guest(trip.id, 'Alice', rsvp_status='attending')
        g2 = _create_guest(trip.id, 'Bob', rsvp_status='attending')
        g3 = _create_guest(trip.id, 'Carol', rsvp_status='attending')

        # Check in 2 of 3
        client.post(f'/api/trips/{trip.id}/guests/{g1.id}/checkin')
        r = client.post(f'/api/trips/{trip.id}/guests/{g2.id}/checkin')
        assert r.get_json()['checkin_progress'] == '2/3'

    def test_checkin_non_admin(self, client):
        owner = _create_user('owner@t.com')
        viewer = _create_user('viewer@t.com')
        trip = _create_trip(owner.id)
        member = TripMember(trip_plan_id=trip.id, user_id=viewer.id, role='viewer')
        db.session.add(member)
        db.session.commit()
        guest = _create_guest(trip.id, 'Alice', rsvp_status='attending')
        _enable_flags('qr_checkin')
        _login_client_as(client, viewer.id)

        r = client.post(f'/api/trips/{trip.id}/guests/{guest.id}/checkin')
        assert r.status_code == 403

    def test_checkin_guest_not_found(self, client):
        user, trip = _setup_admin_trip(client)
        _enable_flags('qr_checkin')
        r = client.post(f'/api/trips/{trip.id}/guests/9999/checkin')
        assert r.status_code == 404
