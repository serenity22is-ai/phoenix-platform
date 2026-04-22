"""
MYSTES Tests — Block 7 (Build #233: Referral Attribution Chain + Conversion Tracking)

Tests for:
- ReferralClick model: create, to_dict, visitor dedup hash
- ConversionEvent model: create, to_dict, unique constraint
- Track Click API: record clicks, dedup within 24h, unknown code rejected
- Resolve API: resolve ref + src codes to display names
- Attribute API: record conversion events, award points, dedup, self-refer block
- My Stats API: referral dashboard with funnel counts
- My Conversions API: paginated conversion list
- Admin Leaderboard API: top referrers, summary stats
- Feature flag gating: all flagged endpoints return 403 when disabled

Run: python3 -m pytest tests/test_block7_referral.py -v
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
    User, CommercialAccount, Booking, ConsumerReferral,
    ReferralClick, ConversionEvent, FeatureFlag, RewardsAccount,
)


# ───── Fixtures ─────

@pytest.fixture(autouse=True)
def setup_db():
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['WTF_CSRF_ENABLED'] = False
    app.config['REFERRAL_SIGNUP_POINTS'] = 2000
    app.config['REFERRAL_FIRST_BOOKING_POINTS'] = 5000
    app.config['REFERRAL_TRAVEL_PLUS_POINTS'] = 10000
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
    with c.session_transaction() as sess:
        sess['_user_id'] = str(user_id)


def _create_user(email, name='Test User', referral_code=None):
    user = User(email=email, name=name, is_verified=True, is_active=True)
    user.set_password('TestPass1!')
    if referral_code:
        user.referral_code = referral_code
    db.session.add(user)
    db.session.commit()
    return user


def _create_b2b_account(name='TravelMax', referral_code='TRAVELMAX'):
    import secrets
    acct = CommercialAccount(
        account_id=f'acct_{secrets.token_hex(4)}',
        name=name,
        contact_email=f'{referral_code.lower()}@agency.com',
        referral_code=referral_code,
        current_tier='starter',
    )
    db.session.add(acct)
    db.session.commit()
    return acct


def _enable_flags(*keys):
    for key in keys:
        flag = FeatureFlag.query.filter_by(flag_key=key).first()
        if flag:
            flag.is_enabled = True
        else:
            flag = FeatureFlag(
                flag_key=key, flag_name=key, description='test',
                layer=3, is_enabled=True,
            )
            db.session.add(flag)
    db.session.commit()


# ================================================================
# Part 1: Model Tests
# ================================================================

class TestReferralClickModel:
    """Test ReferralClick model CRUD."""

    def test_create_click(self, client):
        with app.app_context():
            click = ReferralClick(
                referral_code='MYS-ABC123',
                upstream_b2b_code='TRAVELMAX',
                source_type='invite_link',
                source_id=42,
                landing_url='https://mystes.app/flights?ref=MYS-ABC123',
                visitor_hash='abcdef1234567890',
                ip_country='US',
            )
            db.session.add(click)
            db.session.commit()

            assert click.id is not None
            assert click.referral_code == 'MYS-ABC123'
            assert click.upstream_b2b_code == 'TRAVELMAX'
            assert click.converted_user_id is None

    def test_click_to_dict(self, client):
        with app.app_context():
            click = ReferralClick(
                referral_code='MYS-XYZ',
                source_type='trip_post',
                visitor_hash='hash123',
            )
            db.session.add(click)
            db.session.commit()

            d = click.to_dict()
            assert d['referral_code'] == 'MYS-XYZ'
            assert d['source_type'] == 'trip_post'
            assert d['created_at'] is not None

    def test_click_converted_user_link(self, client):
        with app.app_context():
            user = _create_user('convert@t.com')
            click = ReferralClick(
                referral_code='MYS-ABC',
                visitor_hash='hash456',
                converted_user_id=user.id,
            )
            db.session.add(click)
            db.session.commit()

            assert click.converted_user.email == 'convert@t.com'


class TestConversionEventModel:
    """Test ConversionEvent model CRUD + constraints."""

    def test_create_event(self, client):
        with app.app_context():
            user = _create_user('new@t.com')
            event = ConversionEvent(
                referral_code='MYS-ABC',
                user_id=user.id,
                event_type='signup',
                points_awarded=2000,
            )
            db.session.add(event)
            db.session.commit()

            assert event.id is not None
            assert event.event_type == 'signup'
            assert event.points_awarded == 2000

    def test_event_to_dict(self, client):
        with app.app_context():
            user = _create_user('new@t.com')
            event = ConversionEvent(
                referral_code='MYS-ABC',
                user_id=user.id,
                event_type='first_booking',
                booking_id=99,
                commission_usd=5.50,
            )
            db.session.add(event)
            db.session.commit()

            d = event.to_dict()
            assert d['event_type'] == 'first_booking'
            assert d['booking_id'] == 99
            assert d['commission_usd'] == 5.50

    def test_unique_constraint(self, client):
        """Cannot create duplicate (code, user, event_type)."""
        with app.app_context():
            user = _create_user('u@t.com')
            e1 = ConversionEvent(
                referral_code='MYS-DUP',
                user_id=user.id,
                event_type='signup',
            )
            db.session.add(e1)
            db.session.commit()

            e2 = ConversionEvent(
                referral_code='MYS-DUP',
                user_id=user.id,
                event_type='signup',
            )
            db.session.add(e2)
            with pytest.raises(Exception):
                db.session.commit()
            db.session.rollback()


# ================================================================
# Part 2: Feature Flag Gating
# ================================================================

class TestFeatureFlagGating:
    """All referral endpoints return 403 when flag is disabled."""

    def test_track_click_flag_disabled(self, client):
        r = client.post('/api/referral/track-click', json={'ref': 'X'})
        assert r.status_code == 403

    def test_resolve_flag_disabled(self, client):
        r = client.get('/api/referral/resolve?ref=X')
        assert r.status_code == 403

    def test_attribute_flag_disabled(self, client):
        with app.app_context():
            user = _create_user('u@t.com')
            _login_client_as(client, user.id)
        r = client.post('/api/referral/attribute', json={'ref': 'X', 'event_type': 'signup'})
        assert r.status_code == 403

    def test_my_stats_flag_disabled(self, client):
        with app.app_context():
            user = _create_user('u@t.com')
            _login_client_as(client, user.id)
        r = client.get('/api/referral/my-stats')
        assert r.status_code == 403

    def test_my_conversions_flag_disabled(self, client):
        with app.app_context():
            user = _create_user('u@t.com')
            _login_client_as(client, user.id)
        r = client.get('/api/referral/my-conversions')
        assert r.status_code == 403

    def test_admin_leaderboard_flag_disabled(self, client):
        with app.app_context():
            user = _create_user('admin@t.com')
            user.is_admin = True
            db.session.commit()
            _login_client_as(client, user.id)
        r = client.get('/api/admin/referral/leaderboard')
        assert r.status_code == 403

    def test_flag_registered(self, client):
        """referral_attribution flag exists in init_default_flags."""
        with app.app_context():
            FeatureFlag.init_default_flags()
            flag = FeatureFlag.query.filter_by(flag_key='referral_attribution').first()
            assert flag is not None
            assert flag.layer == 3
            assert flag.is_enabled is True


# ================================================================
# Part 3: Track Click API
# ================================================================

class TestTrackClickAPI:
    """Test POST /api/referral/track-click."""

    def test_track_click_basic(self, client):
        with app.app_context():
            _enable_flags('referral_attribution')
            referrer = _create_user('referrer@t.com', 'Jake', referral_code='JAKE2026')

        r = client.post('/api/referral/track-click', json={
            'ref': 'JAKE2026',
            'source_type': 'direct_url',
            'landing_url': 'https://mystes.app?ref=JAKE2026',
        })
        assert r.status_code == 200
        data = r.get_json()
        assert data['status'] == 'ok'
        assert data['click_id'] is not None
        assert data['deduplicated'] is False

    def test_track_click_with_b2b_src(self, client):
        with app.app_context():
            _enable_flags('referral_attribution')
            _create_user('referrer@t.com', 'Jake', referral_code='JAKE2026')
            _create_b2b_account('TravelMax', 'TRAVELMAX')

        r = client.post('/api/referral/track-click', json={
            'ref': 'JAKE2026',
            'src': 'TRAVELMAX',
        })
        assert r.status_code == 200
        data = r.get_json()
        assert data['deduplicated'] is False

        # Verify stored
        with app.app_context():
            click = ReferralClick.query.get(data['click_id'])
            assert click.upstream_b2b_code == 'TRAVELMAX'

    def test_track_click_dedup_within_24h(self, client):
        """Same visitor + code within 24h = deduplicated."""
        with app.app_context():
            _enable_flags('referral_attribution')
            _create_user('r@t.com', 'R', referral_code='RCODE')

        # First click
        r1 = client.post('/api/referral/track-click', json={'ref': 'RCODE'})
        assert r1.get_json()['deduplicated'] is False

        # Second click — same client = same IP + UA
        r2 = client.post('/api/referral/track-click', json={'ref': 'RCODE'})
        assert r2.get_json()['deduplicated'] is True
        assert r2.get_json()['click_id'] == r1.get_json()['click_id']

    def test_track_click_missing_ref(self, client):
        with app.app_context():
            _enable_flags('referral_attribution')

        r = client.post('/api/referral/track-click', json={})
        assert r.status_code == 400

    def test_track_click_unknown_code(self, client):
        with app.app_context():
            _enable_flags('referral_attribution')

        r = client.post('/api/referral/track-click', json={'ref': 'NONEXISTENT'})
        assert r.status_code == 404

    def test_track_click_b2b_code_as_ref(self, client):
        """B2B referral code also works as ref= param."""
        with app.app_context():
            _enable_flags('referral_attribution')
            _create_b2b_account('TravelMax', 'TRAVELMAX')

        r = client.post('/api/referral/track-click', json={'ref': 'TRAVELMAX'})
        assert r.status_code == 200
        assert r.get_json()['deduplicated'] is False


# ================================================================
# Part 4: Resolve API
# ================================================================

class TestResolveAPI:
    """Test GET /api/referral/resolve."""

    def test_resolve_user_code(self, client):
        with app.app_context():
            _enable_flags('referral_attribution')
            _create_user('jake@t.com', 'Jake Smith', referral_code='JAKE2026')

        r = client.get('/api/referral/resolve?ref=JAKE2026')
        assert r.status_code == 200
        data = r.get_json()
        assert data['ref']['type'] == 'user'
        assert data['ref']['name'] == 'Jake Smith'

    def test_resolve_b2b_code(self, client):
        with app.app_context():
            _enable_flags('referral_attribution')
            _create_b2b_account('TravelMax Agency', 'TRAVELMAX')

        r = client.get('/api/referral/resolve?src=TRAVELMAX')
        assert r.status_code == 200
        data = r.get_json()
        assert data['src']['type'] == 'b2b'
        assert data['src']['name'] == 'TravelMax Agency'

    def test_resolve_both_codes(self, client):
        with app.app_context():
            _enable_flags('referral_attribution')
            _create_user('j@t.com', 'Jake', referral_code='JAKE')
            _create_b2b_account('Agency', 'AGENCY1')

        r = client.get('/api/referral/resolve?ref=JAKE&src=AGENCY1')
        assert r.status_code == 200
        data = r.get_json()
        assert data['ref']['name'] == 'Jake'
        assert data['src']['name'] == 'Agency'

    def test_resolve_unknown_code(self, client):
        with app.app_context():
            _enable_flags('referral_attribution')

        r = client.get('/api/referral/resolve?ref=UNKNOWN')
        assert r.status_code == 200
        data = r.get_json()
        assert data['ref'] is None


# ================================================================
# Part 5: Attribute Conversion API
# ================================================================

class TestAttributeAPI:
    """Test POST /api/referral/attribute."""

    def test_attribute_signup(self, client):
        with app.app_context():
            _enable_flags('referral_attribution')
            referrer = _create_user('referrer@t.com', 'Referrer', referral_code='REF1')
            referee = _create_user('referee@t.com', 'Referee')
            _login_client_as(client, referee.id)

        r = client.post('/api/referral/attribute', json={
            'ref': 'REF1',
            'event_type': 'signup',
        })
        assert r.status_code == 200
        data = r.get_json()
        assert data['status'] == 'ok'
        assert data['deduplicated'] is False
        assert data['event']['event_type'] == 'signup'
        assert data['event']['points_awarded'] == 2000

    def test_attribute_awards_points_to_referrer(self, client):
        with app.app_context():
            _enable_flags('referral_attribution')
            referrer = _create_user('referrer@t.com', 'Referrer', referral_code='REF1')
            ra = RewardsAccount(user_id=referrer.id, points_balance=100, lifetime_earned=100)
            db.session.add(ra)
            db.session.commit()
            ref_id = referrer.id
            referee = _create_user('referee@t.com', 'Referee')
            _login_client_as(client, referee.id)

        r = client.post('/api/referral/attribute', json={
            'ref': 'REF1',
            'event_type': 'signup',
        })
        assert r.status_code == 200

        with app.app_context():
            ra = RewardsAccount.query.filter_by(user_id=ref_id).first()
            assert ra.points_balance == 2100  # 100 + 2000

    def test_attribute_first_booking(self, client):
        with app.app_context():
            _enable_flags('referral_attribution')
            referrer = _create_user('referrer@t.com', 'Referrer', referral_code='REF1')
            referee = _create_user('referee@t.com', 'Referee')
            _login_client_as(client, referee.id)

        r = client.post('/api/referral/attribute', json={
            'ref': 'REF1',
            'event_type': 'first_booking',
        })
        assert r.status_code == 200
        data = r.get_json()
        assert data['event']['points_awarded'] == 5000

    def test_attribute_dedup(self, client):
        """Same (code, user, event_type) returns deduplicated."""
        with app.app_context():
            _enable_flags('referral_attribution')
            _create_user('r@t.com', 'R', referral_code='R1')
            u = _create_user('u@t.com', 'U')
            _login_client_as(client, u.id)

        # First attribution
        r1 = client.post('/api/referral/attribute', json={
            'ref': 'R1', 'event_type': 'signup',
        })
        assert r1.get_json()['deduplicated'] is False

        # Second attribution — same event
        r2 = client.post('/api/referral/attribute', json={
            'ref': 'R1', 'event_type': 'signup',
        })
        assert r2.get_json()['deduplicated'] is True

    def test_attribute_self_refer_blocked(self, client):
        with app.app_context():
            _enable_flags('referral_attribution')
            user = _create_user('self@t.com', 'Self', referral_code='SELF1')
            _login_client_as(client, user.id)

        r = client.post('/api/referral/attribute', json={
            'ref': 'SELF1', 'event_type': 'signup',
        })
        assert r.status_code == 400
        assert 'self-refer' in r.get_json()['error'].lower()

    def test_attribute_invalid_event_type(self, client):
        with app.app_context():
            _enable_flags('referral_attribution')
            _create_user('r@t.com', referral_code='R1')
            u = _create_user('u@t.com')
            _login_client_as(client, u.id)

        r = client.post('/api/referral/attribute', json={
            'ref': 'R1', 'event_type': 'bogus',
        })
        assert r.status_code == 400

    def test_attribute_missing_ref(self, client):
        with app.app_context():
            _enable_flags('referral_attribution')
            u = _create_user('u@t.com')
            _login_client_as(client, u.id)

        r = client.post('/api/referral/attribute', json={
            'event_type': 'signup',
        })
        assert r.status_code == 400

    def test_attribute_updates_consumer_referral_milestones(self, client):
        """When ConsumerReferral exists, milestones are updated."""
        with app.app_context():
            _enable_flags('referral_attribution')
            referrer = _create_user('r@t.com', 'Referrer', referral_code='R1')
            referee = _create_user('u@t.com', 'Referee')
            cr = ConsumerReferral(
                referrer_id=referrer.id,
                referee_id=referee.id,
                referral_code_used='R1',
            )
            db.session.add(cr)
            db.session.commit()
            cr_id = cr.id
            _login_client_as(client, referee.id)

        # Signup attribution
        client.post('/api/referral/attribute', json={
            'ref': 'R1', 'event_type': 'signup',
        })

        with app.app_context():
            cr = ConsumerReferral.query.get(cr_id)
            assert cr.signup_rewarded is True
            assert cr.total_points_awarded == 2000

    def test_attribute_links_click(self, client):
        """Conversion event links back to the most recent unlinked click."""
        with app.app_context():
            _enable_flags('referral_attribution')
            referrer = _create_user('r@t.com', 'R', referral_code='R1')
            referee = _create_user('u@t.com', 'U')

            # Create a click record
            click = ReferralClick(
                referral_code='R1',
                visitor_hash='abc123',
            )
            db.session.add(click)
            db.session.commit()
            click_id = click.id
            _login_client_as(client, referee.id)

        r = client.post('/api/referral/attribute', json={
            'ref': 'R1', 'event_type': 'signup',
        })
        assert r.status_code == 200
        event_data = r.get_json()['event']
        assert event_data['click_id'] == click_id

    def test_attribute_unauthenticated(self, client):
        """Unauthenticated requests are rejected."""
        with app.app_context():
            _enable_flags('referral_attribution')
        r = client.post('/api/referral/attribute', json={
            'ref': 'X', 'event_type': 'signup',
        })
        assert r.status_code in (302, 401)


# ================================================================
# Part 6: My Stats API
# ================================================================

class TestMyStatsAPI:
    """Test GET /api/referral/my-stats."""

    def test_stats_no_referral_code(self, client):
        with app.app_context():
            _enable_flags('referral_attribution')
            user = _create_user('u@t.com')
            _login_client_as(client, user.id)

        r = client.get('/api/referral/my-stats')
        assert r.status_code == 200
        data = r.get_json()
        assert data['referral_code'] is None
        assert data['total_clicks'] == 0

    def test_stats_with_data(self, client):
        with app.app_context():
            _enable_flags('referral_attribution')
            referrer = _create_user('r@t.com', 'Referrer', referral_code='RSTAT')
            u1 = _create_user('u1@t.com', 'U1')
            u2 = _create_user('u2@t.com', 'U2')

            # Create clicks
            for i in range(5):
                click = ReferralClick(
                    referral_code='RSTAT',
                    visitor_hash=f'hash{i}',
                )
                db.session.add(click)

            # Create conversion events
            for u, etype in [(u1, 'signup'), (u2, 'signup'), (u1, 'first_booking')]:
                ev = ConversionEvent(
                    referral_code='RSTAT',
                    user_id=u.id,
                    event_type=etype,
                    points_awarded=1000,
                )
                db.session.add(ev)
            db.session.commit()

            _login_client_as(client, referrer.id)

        r = client.get('/api/referral/my-stats')
        assert r.status_code == 200
        data = r.get_json()
        assert data['referral_code'] == 'RSTAT'
        assert data['total_clicks'] == 5
        assert data['unique_visitors'] == 5
        assert data['funnel']['signup'] == 2
        assert data['funnel']['first_booking'] == 1
        assert data['total_points_earned'] == 3000
        assert len(data['recent_conversions']) == 3


# ================================================================
# Part 7: My Conversions API
# ================================================================

class TestMyConversionsAPI:
    """Test GET /api/referral/my-conversions."""

    def test_conversions_empty(self, client):
        with app.app_context():
            _enable_flags('referral_attribution')
            user = _create_user('u@t.com', referral_code='EMPTY')
            _login_client_as(client, user.id)

        r = client.get('/api/referral/my-conversions')
        assert r.status_code == 200
        data = r.get_json()
        assert data['conversions'] == []
        assert data['total'] == 0

    def test_conversions_with_data(self, client):
        with app.app_context():
            _enable_flags('referral_attribution')
            referrer = _create_user('r@t.com', referral_code='RCONV')
            u1 = _create_user('u1@t.com')
            u2 = _create_user('u2@t.com')

            for u in [u1, u2]:
                ev = ConversionEvent(
                    referral_code='RCONV',
                    user_id=u.id,
                    event_type='signup',
                    points_awarded=2000,
                )
                db.session.add(ev)
            db.session.commit()

            _login_client_as(client, referrer.id)

        r = client.get('/api/referral/my-conversions')
        assert r.status_code == 200
        data = r.get_json()
        assert data['total'] == 2
        assert len(data['conversions']) == 2

    def test_conversions_pagination(self, client):
        with app.app_context():
            _enable_flags('referral_attribution')
            referrer = _create_user('r@t.com', referral_code='RPAGE')
            for i in range(5):
                u = _create_user(f'u{i}@t.com')
                ev = ConversionEvent(
                    referral_code='RPAGE',
                    user_id=u.id,
                    event_type='signup',
                )
                db.session.add(ev)
            db.session.commit()
            _login_client_as(client, referrer.id)

        r = client.get('/api/referral/my-conversions?page=1&per_page=2')
        data = r.get_json()
        assert data['total'] == 5
        assert len(data['conversions']) == 2
        assert data['page'] == 1
        assert data['per_page'] == 2


# ================================================================
# Part 8: Admin Leaderboard API
# ================================================================

class TestAdminLeaderboardAPI:
    """Test GET /api/admin/referral/leaderboard."""

    def test_admin_required(self, client):
        with app.app_context():
            _enable_flags('referral_attribution')
            user = _create_user('u@t.com')
            _login_client_as(client, user.id)

        r = client.get('/api/admin/referral/leaderboard')
        assert r.status_code == 403

    def test_leaderboard_data(self, client):
        with app.app_context():
            _enable_flags('referral_attribution')
            admin = _create_user('admin@t.com', 'Admin')
            admin.is_admin = True
            db.session.commit()

            r1 = _create_user('r1@t.com', 'Referrer1', referral_code='R1')
            r2 = _create_user('r2@t.com', 'Referrer2', referral_code='R2')
            u1 = _create_user('u1@t.com')
            u2 = _create_user('u2@t.com')
            u3 = _create_user('u3@t.com')

            # R1 has 3 events, R2 has 1
            for u in [u1, u2, u3]:
                db.session.add(ConversionEvent(
                    referral_code='R1', user_id=u.id,
                    event_type='signup', points_awarded=2000,
                ))
            db.session.add(ConversionEvent(
                referral_code='R2', user_id=u1.id,
                event_type='first_booking', points_awarded=5000,
            ))

            # Add a click
            db.session.add(ReferralClick(referral_code='R1', visitor_hash='h1'))
            db.session.commit()

            _login_client_as(client, admin.id)

        r = client.get('/api/admin/referral/leaderboard')
        assert r.status_code == 200
        data = r.get_json()
        lb = data['leaderboard']
        assert len(lb) == 2
        assert lb[0]['referral_code'] == 'R1'
        assert lb[0]['event_count'] == 3
        assert lb[0]['owner_name'] == 'Referrer1'
        assert lb[1]['referral_code'] == 'R2'

        assert data['summary']['total_clicks'] == 1
        assert data['summary']['total_conversions'] == 4
        assert data['summary']['total_signups'] == 3
        assert data['summary']['total_bookings'] == 1

    def test_leaderboard_filter_by_event_type(self, client):
        with app.app_context():
            _enable_flags('referral_attribution')
            admin = _create_user('admin@t.com', 'Admin')
            admin.is_admin = True
            db.session.commit()

            r1 = _create_user('r1@t.com', 'R1', referral_code='R1')
            u1 = _create_user('u1@t.com')
            u2 = _create_user('u2@t.com')

            db.session.add(ConversionEvent(
                referral_code='R1', user_id=u1.id,
                event_type='signup', points_awarded=2000,
            ))
            db.session.add(ConversionEvent(
                referral_code='R1', user_id=u2.id,
                event_type='first_booking', points_awarded=5000,
            ))
            db.session.commit()

            _login_client_as(client, admin.id)

        r = client.get('/api/admin/referral/leaderboard?event_type=first_booking')
        data = r.get_json()
        lb = data['leaderboard']
        assert len(lb) == 1
        assert lb[0]['event_count'] == 1


# ================================================================
# Part 9: Access Control
# ================================================================

class TestAccessControl:
    """Unauthenticated access to auth-required endpoints."""

    def test_unauthenticated_attribute(self, client):
        with app.app_context():
            _enable_flags('referral_attribution')
        r = client.post('/api/referral/attribute', json={
            'ref': 'X', 'event_type': 'signup',
        })
        assert r.status_code in (302, 401)

    def test_unauthenticated_my_stats(self, client):
        with app.app_context():
            _enable_flags('referral_attribution')
        r = client.get('/api/referral/my-stats')
        assert r.status_code in (302, 401)

    def test_unauthenticated_my_conversions(self, client):
        with app.app_context():
            _enable_flags('referral_attribution')
        r = client.get('/api/referral/my-conversions')
        assert r.status_code in (302, 401)

    def test_unauthenticated_leaderboard(self, client):
        with app.app_context():
            _enable_flags('referral_attribution')
        r = client.get('/api/admin/referral/leaderboard')
        assert r.status_code in (302, 401)
