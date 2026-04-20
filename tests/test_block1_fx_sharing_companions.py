"""
MYSTES Tests — Block 1 (FX-Aware Pricing + Build #219 InviteLink + Build #220 Companions)

Tests for:
- SpreadResult.fx_adjusted() and to_display() FX fields
- User.no_fx_fee_card field
- InviteLink model (create, is_valid, is_expired, record_click, og_meta, to_dict)
- Share API endpoints (/api/share/create, my-links, revoke, stats)
- Invite link resolver (GET /i/<token>)
- OG meta generation per link_type
- Friendship companion fields (nickname, trips_together_count)
- Companion API endpoints (/api/friends/<id>/nickname, /api/friends/companions)

Run: python3 -m pytest tests/test_block1_fx_sharing_companions.py -v
"""

import json
import sys
import os
import pytest
from datetime import datetime, timezone, timedelta

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _root)
sys.path.insert(0, os.path.join(_root, 'picasso-sdk'))

from server import app, db, limiter
from models import User, InviteLink, Deal, TripPlan, Friendship, Collection


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
            referral_code='MYS-TEST1234',
        )
        user.set_password('TestPass123!')
        db.session.add(user)
        db.session.commit()

    client.post('/login', data={
        'email': 'test@example.com',
        'password': 'TestPass123!',
    }, follow_redirects=True)
    yield client


def _get_test_user():
    """Get the test user from database."""
    return User.query.filter_by(email='test@example.com').first()


# ================================================================
# Part 1: FX-Aware Pricing (SpreadResult)
# ================================================================

class TestSpreadResultFX:
    """Test FX-aware pricing methods on SpreadResult."""

    def test_fx_adjusted_default_fee(self):
        """fx_adjusted() applies 2.5% FX fee to foreign POS price."""
        from anastasia.arbitrage.spread import SpreadResult, DEFAULT_FX_FEE_PERCENT

        result = SpreadResult(
            us_retail_price=1400.0,
            foreign_pos_price=800.0,
            foreign_market="DK",
            spread=600.0,
            fee_percent=0.50,
            service_fee=300.0,
            customer_price=1100.0,
            customer_savings=300.0,
            savings_percent=21.4,
            has_arbitrage=True,
        )

        fx = result.fx_adjusted()
        assert DEFAULT_FX_FEE_PERCENT == 0.025
        assert fx['fx_fee_percent'] == 0.025
        # FX fee on foreign POS portion: $800 * 0.025 = $20
        assert fx['fx_fee_usd'] == 20.0
        # Price after FX: $1100 + $20 = $1120
        assert fx['price_after_fx'] == 1120.0
        # Savings after FX: $1400 - $1120 = $280
        assert fx['savings_after_fx'] == 280.0
        assert fx['has_savings_after_fx'] is True
        assert fx['savings_percent_after_fx'] == 20.0

    def test_fx_adjusted_no_fx_card(self):
        """fx_adjusted(0.0) shows zero FX impact."""
        from anastasia.arbitrage.spread import SpreadResult

        result = SpreadResult(
            us_retail_price=1400.0,
            foreign_pos_price=800.0,
            foreign_market="DK",
            spread=600.0,
            fee_percent=0.50,
            service_fee=300.0,
            customer_price=1100.0,
            customer_savings=300.0,
            savings_percent=21.4,
            has_arbitrage=True,
        )

        fx = result.fx_adjusted(fx_fee_percent=0.0)
        assert fx['fx_fee_usd'] == 0.0
        assert fx['price_after_fx'] == 1100.0
        assert fx['savings_after_fx'] == 300.0
        assert fx['has_savings_after_fx'] is True

    def test_fx_adjusted_high_fee_still_saves(self):
        """High FX fee (3%) still leaves savings on large spread."""
        from anastasia.arbitrage.spread import SpreadResult

        result = SpreadResult(
            us_retail_price=2000.0,
            foreign_pos_price=1000.0,
            foreign_market="IN",
            spread=1000.0,
            fee_percent=0.50,
            service_fee=500.0,
            customer_price=1500.0,
            customer_savings=500.0,
            savings_percent=25.0,
            has_arbitrage=True,
        )

        fx = result.fx_adjusted(fx_fee_percent=0.03)
        # FX: $1000 * 0.03 = $30
        assert fx['fx_fee_usd'] == 30.0
        assert fx['price_after_fx'] == 1530.0
        assert fx['savings_after_fx'] == 470.0
        assert fx['has_savings_after_fx'] is True

    def test_fx_adjusted_kills_savings(self):
        """When FX fee exceeds the savings, has_savings_after_fx = False."""
        from anastasia.arbitrage.spread import SpreadResult

        result = SpreadResult(
            us_retail_price=500.0,
            foreign_pos_price=480.0,
            foreign_market="GB",
            spread=20.0,
            fee_percent=0.50,
            service_fee=10.0,
            customer_price=490.0,
            customer_savings=10.0,
            savings_percent=2.0,
            has_arbitrage=True,
        )

        fx = result.fx_adjusted(fx_fee_percent=0.025)
        # FX: $480 * 0.025 = $12
        assert fx['fx_fee_usd'] == 12.0
        # Price after FX: $490 + $12 = $502 > $500 retail
        assert fx['price_after_fx'] == 502.0
        assert fx['savings_after_fx'] == -2.0
        assert fx['has_savings_after_fx'] is False

    def test_to_display_includes_fx_fields(self):
        """to_display() includes all FX-aware fields."""
        from anastasia.arbitrage.spread import SpreadResult

        result = SpreadResult(
            us_retail_price=1400.0,
            foreign_pos_price=800.0,
            foreign_market="DK",
            spread=600.0,
            fee_percent=0.50,
            service_fee=300.0,
            customer_price=1100.0,
            customer_savings=300.0,
            savings_percent=21.4,
            has_arbitrage=True,
        )

        display = result.to_display()
        # Standard fields
        assert display['google_price'] == 1400.0
        assert display['mystes_price'] == 1100.0
        assert display['you_save'] == 300.0
        assert display['has_savings'] is True
        # FX fields present
        assert 'fx_fee_usd' in display
        assert 'price_after_fx' in display
        assert 'savings_after_fx' in display
        assert 'savings_percent_after_fx' in display
        assert 'has_savings_after_fx' in display
        assert 'no_fx_fee_price' in display
        assert 'no_fx_fee_savings' in display
        # No-FX price == customer_price
        assert display['no_fx_fee_price'] == 1100.0
        assert display['no_fx_fee_savings'] == 300.0

    def test_to_display_no_pos_codes(self):
        """to_display() never exposes POS market codes (airline compliance)."""
        from anastasia.arbitrage.spread import SpreadResult

        result = SpreadResult(
            us_retail_price=1400.0,
            foreign_pos_price=800.0,
            foreign_market="DK",
            spread=600.0,
            fee_percent=0.50,
            service_fee=300.0,
            customer_price=1100.0,
            customer_savings=300.0,
            savings_percent=21.4,
            has_arbitrage=True,
        )

        display = result.to_display()
        # Must NOT contain market codes
        assert 'foreign_market' not in display
        assert 'DK' not in str(display.values())

    def test_to_internal_includes_pos_codes(self):
        """to_internal() includes POS market codes (admin only)."""
        from anastasia.arbitrage.spread import SpreadResult

        result = SpreadResult(
            us_retail_price=1400.0,
            foreign_pos_price=800.0,
            foreign_market="DK",
            spread=600.0,
            fee_percent=0.50,
            service_fee=300.0,
            customer_price=1100.0,
            customer_savings=300.0,
            savings_percent=21.4,
            has_arbitrage=True,
        )

        internal = result.to_internal()
        assert internal['foreign_market'] == 'DK'
        assert internal['kyrios_revenue'] > 0


class TestUserNoFxFeeCard:
    """Test User.no_fx_fee_card field."""

    def test_default_false(self):
        user = User(email='fx@test.com', name='FX User')
        user.set_password('Test1234!')
        db.session.add(user)
        db.session.commit()

        assert user.no_fx_fee_card is False

    def test_set_true(self):
        user = User(email='nofx@test.com', name='No FX User', no_fx_fee_card=True)
        user.set_password('Test1234!')
        db.session.add(user)
        db.session.commit()

        fetched = db.session.get(User, user.id)
        assert fetched.no_fx_fee_card is True


# ================================================================
# Part 2: InviteLink Model (Build #219)
# ================================================================

class TestInviteLinkModel:
    """Test InviteLink model creation, validation, and lifecycle."""

    def test_create_invite_link(self):
        user = User(email='sender@test.com', name='Sender')
        user.set_password('Test1234!')
        db.session.add(user)
        db.session.commit()

        link = InviteLink(
            token='abc12345',
            link_type='flight',
            object_id=1,
            sender_user_id=user.id,
        )
        db.session.add(link)
        db.session.commit()

        assert link.id is not None
        assert link.token == 'abc12345'
        assert link.link_type == 'flight'
        assert link.is_active is True
        assert link.click_count == 0
        assert link.permissions == 'view_only'

    def test_is_valid_active(self):
        user = User(email='sender@test.com', name='Sender')
        user.set_password('Test1234!')
        db.session.add(user)
        db.session.commit()

        link = InviteLink(
            token='valid123',
            link_type='referral',
            object_id=1,
            sender_user_id=user.id,
            is_active=True,
        )
        db.session.add(link)
        db.session.commit()

        assert link.is_valid() is True

    def test_is_valid_deactivated(self):
        user = User(email='sender@test.com', name='Sender')
        user.set_password('Test1234!')
        db.session.add(user)
        db.session.commit()

        link = InviteLink(
            token='dead1234',
            link_type='referral',
            object_id=1,
            sender_user_id=user.id,
            is_active=False,
        )
        db.session.add(link)
        db.session.commit()

        assert link.is_valid() is False

    def test_is_expired(self):
        user = User(email='sender@test.com', name='Sender')
        user.set_password('Test1234!')
        db.session.add(user)
        db.session.commit()

        link = InviteLink(
            token='exp12345',
            link_type='referral',
            object_id=1,
            sender_user_id=user.id,
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        db.session.add(link)
        db.session.commit()

        assert link.is_expired() is True
        assert link.is_valid() is False

    def test_not_expired_future(self):
        user = User(email='sender@test.com', name='Sender')
        user.set_password('Test1234!')
        db.session.add(user)
        db.session.commit()

        link = InviteLink(
            token='fut12345',
            link_type='referral',
            object_id=1,
            sender_user_id=user.id,
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        )
        db.session.add(link)
        db.session.commit()

        assert link.is_expired() is False
        assert link.is_valid() is True

    def test_record_click(self):
        user = User(email='sender@test.com', name='Sender')
        user.set_password('Test1234!')
        db.session.add(user)
        db.session.commit()

        link = InviteLink(
            token='clk12345',
            link_type='referral',
            object_id=1,
            sender_user_id=user.id,
        )
        db.session.add(link)
        db.session.commit()

        assert link.click_count == 0
        link.record_click()
        assert link.click_count == 1
        link.record_click()
        link.record_click()
        assert link.click_count == 3

    def test_record_conversion(self):
        user = User(email='sender@test.com', name='Sender')
        user.set_password('Test1234!')
        db.session.add(user)
        db.session.commit()

        link = InviteLink(
            token='con12345',
            link_type='referral',
            object_id=1,
            sender_user_id=user.id,
        )
        db.session.add(link)
        db.session.commit()

        link.record_conversion()
        assert link.conversions == 1

    def test_to_dict(self):
        user = User(email='sender@test.com', name='Sender')
        user.set_password('Test1234!')
        db.session.add(user)
        db.session.commit()

        link = InviteLink(
            token='dict1234',
            link_type='flight',
            object_id=42,
            sender_user_id=user.id,
            message='Check this deal!',
            referral_code='MYS-REF123',
        )
        db.session.add(link)
        db.session.commit()

        d = link.to_dict()
        assert d['token'] == 'dict1234'
        assert d['link_type'] == 'flight'
        assert d['object_id'] == 42
        assert d['message'] == 'Check this deal!'
        assert d['referral_code'] == 'MYS-REF123'

    def test_og_meta_default(self):
        user = User(email='sender@test.com', name='Sender')
        user.set_password('Test1234!')
        db.session.add(user)
        db.session.commit()

        link = InviteLink(
            token='ogde1234',
            link_type='flight',
            object_id=1,
            sender_user_id=user.id,
        )
        db.session.add(link)
        db.session.commit()

        og = link.og_meta()
        assert 'og:title' in og
        assert og['og:site_name'] == 'MYSTES'
        assert og['og:url'] == '/i/ogde1234'
        assert og['og:type'] == 'website'

    def test_og_meta_override(self):
        user = User(email='sender@test.com', name='Sender')
        user.set_password('Test1234!')
        db.session.add(user)
        db.session.commit()

        link = InviteLink(
            token='ogov1234',
            link_type='flight',
            object_id=1,
            sender_user_id=user.id,
            og_title='Custom Title',
            og_description='Custom desc',
            og_image_url='https://example.com/img.png',
        )
        db.session.add(link)
        db.session.commit()

        og = link.og_meta()
        assert og['og:title'] == 'Custom Title'
        assert og['og:description'] == 'Custom desc'
        assert og['og:image'] == 'https://example.com/img.png'

    def test_all_link_types_valid(self):
        """All 15 link types are valid."""
        assert len(InviteLink.LINK_TYPES) == 15
        for lt in ('flight', 'hotel', 'itinerary', 'trip_invite', 'cart_checkout',
                    'collection', 'referral', 'price_alert', 'wishlist',
                    'booking_confirm', 'activity', 'car', 'settle_up',
                    'trip_view', 'event_registration'):
            assert lt in InviteLink.LINK_TYPES

    def test_all_permissions_valid(self):
        """All 4 permissions are valid."""
        assert len(InviteLink.PERMISSIONS) == 4
        for p in ('view_only', 'can_pay', 'can_join', 'can_adopt'):
            assert p in InviteLink.PERMISSIONS


# ================================================================
# Part 3: Share API Endpoints (Build #219)
# ================================================================

class TestCreateShareLink:
    """POST /api/share/create"""

    def test_create_flight_link(self, auth_client):
        resp = auth_client.post('/api/share/create',
            data=json.dumps({
                'link_type': 'flight',
                'object_id': 1,
                'message': 'Amazing deal!',
            }),
            content_type='application/json',
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['status'] == 'ok'
        assert 'link' in data
        assert data['link']['link_type'] == 'flight'
        assert data['link']['message'] == 'Amazing deal!'
        assert data['full_url'].startswith('/i/')

    def test_create_referral_link(self, auth_client):
        resp = auth_client.post('/api/share/create',
            data=json.dumps({
                'link_type': 'referral',
                'object_id': 0,
            }),
            content_type='application/json',
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['link']['referral_code'] == 'MYS-TEST1234'

    def test_create_invalid_link_type(self, auth_client):
        resp = auth_client.post('/api/share/create',
            data=json.dumps({
                'link_type': 'INVALID',
                'object_id': 1,
            }),
            content_type='application/json',
        )
        assert resp.status_code == 400

    def test_create_missing_object_id(self, auth_client):
        resp = auth_client.post('/api/share/create',
            data=json.dumps({
                'link_type': 'flight',
            }),
            content_type='application/json',
        )
        assert resp.status_code == 400

    def test_create_with_permissions(self, auth_client):
        resp = auth_client.post('/api/share/create',
            data=json.dumps({
                'link_type': 'trip_invite',
                'object_id': 1,
                'permissions': 'can_join',
            }),
            content_type='application/json',
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['link']['permissions'] == 'can_join'

    def test_create_with_og_overrides(self, auth_client):
        resp = auth_client.post('/api/share/create',
            data=json.dumps({
                'link_type': 'flight',
                'object_id': 1,
                'og_title': 'Custom Share Title',
                'og_description': 'Custom description',
            }),
            content_type='application/json',
        )
        assert resp.status_code == 200

    def test_unauthenticated_rejected(self, client):
        resp = client.post('/api/share/create',
            data=json.dumps({'link_type': 'flight', 'object_id': 1}),
            content_type='application/json',
        )
        # login_required redirects to login
        assert resp.status_code in (302, 401)


class TestMyShareLinks:
    """GET /api/share/my-links"""

    def test_list_empty(self, auth_client):
        resp = auth_client.get('/api/share/my-links')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['count'] == 0
        assert data['links'] == []

    def test_list_own_links(self, auth_client):
        # Create two links
        auth_client.post('/api/share/create',
            data=json.dumps({'link_type': 'flight', 'object_id': 1}),
            content_type='application/json',
        )
        auth_client.post('/api/share/create',
            data=json.dumps({'link_type': 'referral', 'object_id': 0}),
            content_type='application/json',
        )

        resp = auth_client.get('/api/share/my-links')
        data = resp.get_json()
        assert data['count'] == 2
        assert len(data['links']) == 2


class TestRevokeShareLink:
    """POST /api/share/<token>/revoke"""

    def test_revoke_own_link(self, auth_client):
        # Create a link
        create_resp = auth_client.post('/api/share/create',
            data=json.dumps({'link_type': 'flight', 'object_id': 1}),
            content_type='application/json',
        )
        token = create_resp.get_json()['link']['token']

        # Revoke it
        resp = auth_client.post(f'/api/share/{token}/revoke')
        assert resp.status_code == 200
        assert resp.get_json()['status'] == 'ok'

        # Verify revoked
        with app.app_context():
            link = InviteLink.query.filter_by(token=token).first()
            assert link.is_active is False

    def test_revoke_nonexistent(self, auth_client):
        resp = auth_client.post('/api/share/FAKE_TOKEN/revoke')
        assert resp.status_code == 404


class TestShareLinkStats:
    """GET /api/share/<token>/stats"""

    def test_stats_own_link(self, auth_client):
        # Create a link
        create_resp = auth_client.post('/api/share/create',
            data=json.dumps({'link_type': 'flight', 'object_id': 1}),
            content_type='application/json',
        )
        token = create_resp.get_json()['link']['token']

        resp = auth_client.get(f'/api/share/{token}/stats')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['stats']['clicks'] == 0
        assert data['stats']['is_active'] is True
        assert data['stats']['link_type'] == 'flight'

    def test_stats_nonexistent(self, auth_client):
        resp = auth_client.get('/api/share/FAKE_TOKEN/stats')
        assert resp.status_code == 404


# ================================================================
# Part 4: Invite Link Resolver (GET /i/<token>)
# ================================================================

class TestInviteLinkResolver:
    """GET /i/<token> — resolve and render shared content."""

    def test_resolve_valid_referral(self, client):
        with app.app_context():
            user = User(email='sharer@test.com', name='Sharer')
            user.set_password('Test1234!')
            db.session.add(user)
            db.session.commit()

            link = InviteLink(
                token='ref12345',
                link_type='referral',
                object_id=0,
                sender_user_id=user.id,
                referral_code='MYS-SHARE99',
            )
            db.session.add(link)
            db.session.commit()

        resp = client.get('/i/ref12345')
        assert resp.status_code == 200
        html = resp.data.decode()
        assert 'MYSTES' in html
        assert 'SEARCH FLIGHTS WITH DISCOUNT' in html

    def test_resolve_expired_link(self, client):
        with app.app_context():
            user = User(email='sharer@test.com', name='Sharer')
            user.set_password('Test1234!')
            db.session.add(user)
            db.session.commit()

            link = InviteLink(
                token='exp99999',
                link_type='referral',
                object_id=0,
                sender_user_id=user.id,
                expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
            )
            db.session.add(link)
            db.session.commit()

        resp = client.get('/i/exp99999')
        assert resp.status_code == 404
        html = resp.data.decode()
        assert 'LINK EXPIRED' in html

    def test_resolve_deactivated_link(self, client):
        with app.app_context():
            user = User(email='sharer@test.com', name='Sharer')
            user.set_password('Test1234!')
            db.session.add(user)
            db.session.commit()

            link = InviteLink(
                token='dead9999',
                link_type='referral',
                object_id=0,
                sender_user_id=user.id,
                is_active=False,
            )
            db.session.add(link)
            db.session.commit()

        resp = client.get('/i/dead9999')
        assert resp.status_code == 404

    def test_resolve_nonexistent_token(self, client):
        resp = client.get('/i/DOESNOTEXIST')
        assert resp.status_code == 404

    def test_resolve_increments_click_count(self, client):
        with app.app_context():
            user = User(email='sharer@test.com', name='Sharer')
            user.set_password('Test1234!')
            db.session.add(user)
            db.session.commit()

            link = InviteLink(
                token='clk99999',
                link_type='referral',
                object_id=0,
                sender_user_id=user.id,
            )
            db.session.add(link)
            db.session.commit()

        # Visit 3 times
        client.get('/i/clk99999')
        client.get('/i/clk99999')
        client.get('/i/clk99999')

        with app.app_context():
            link = InviteLink.query.filter_by(token='clk99999').first()
            assert link.click_count == 3

    def test_resolve_sets_referral_session(self, client):
        with app.app_context():
            user = User(email='sharer@test.com', name='Sharer')
            user.set_password('Test1234!')
            db.session.add(user)
            db.session.commit()

            link = InviteLink(
                token='ses12345',
                link_type='referral',
                object_id=0,
                sender_user_id=user.id,
                referral_code='MYS-SESREF',
                upstream_b2b_code='B2B-UPSTREAM',
            )
            db.session.add(link)
            db.session.commit()

        with client.session_transaction() as sess:
            assert 'referral_source' not in sess

        client.get('/i/ses12345')

        with client.session_transaction() as sess:
            assert sess.get('referral_source') == 'MYS-SESREF'
            assert sess.get('b2b_source') == 'B2B-UPSTREAM'

    def test_resolve_with_message(self, client):
        with app.app_context():
            user = User(email='sharer@test.com', name='Sharer')
            user.set_password('Test1234!')
            db.session.add(user)
            db.session.commit()

            link = InviteLink(
                token='msg12345',
                link_type='referral',
                object_id=0,
                sender_user_id=user.id,
                message='You need to see this!',
            )
            db.session.add(link)
            db.session.commit()

        resp = client.get('/i/msg12345')
        assert resp.status_code == 200
        html = resp.data.decode()
        assert 'You need to see this!' in html

    def test_resolve_settle_up(self, client):
        with app.app_context():
            user = User(email='sharer@test.com', name='Sharer')
            user.set_password('Test1234!')
            db.session.add(user)
            db.session.commit()

            link = InviteLink(
                token='stl12345',
                link_type='settle_up',
                object_id=1,
                sender_user_id=user.id,
            )
            db.session.add(link)
            db.session.commit()

        resp = client.get('/i/stl12345')
        assert resp.status_code == 200
        html = resp.data.decode()
        assert 'PAY YOUR SHARE' in html


# ================================================================
# Part 5: OG Meta Generation
# ================================================================

class TestOGMetaGeneration:
    """Test OG meta tag generation for different link types."""

    def _make_invite(self, link_type, user_id, **kwargs):
        link = InviteLink(
            token=f'og_{link_type[:4]}',
            link_type=link_type,
            object_id=kwargs.get('object_id', 1),
            sender_user_id=user_id,
            **{k: v for k, v in kwargs.items() if k != 'object_id'},
        )
        db.session.add(link)
        db.session.commit()
        return link

    def test_og_referral_type(self):
        from routes_sharing import _build_og_meta
        user = User(email='og@test.com', name='OG Tester')
        user.set_password('Test1234!')
        db.session.add(user)
        db.session.commit()

        invite = self._make_invite('referral', user.id)
        og = _build_og_meta(invite)
        assert 'OG Tester invited you to MYSTES' in og['og:title']
        assert og['og:site_name'] == 'MYSTES'

    def test_og_settle_up_type(self):
        from routes_sharing import _build_og_meta
        user = User(email='og@test.com', name='OG Tester')
        user.set_password('Test1234!')
        db.session.add(user)
        db.session.commit()

        invite = self._make_invite('settle_up', user.id)
        og = _build_og_meta(invite)
        assert 'Pay Your Share' in og['og:title']

    def test_og_with_override(self):
        from routes_sharing import _build_og_meta
        user = User(email='og@test.com', name='OG Tester')
        user.set_password('Test1234!')
        db.session.add(user)
        db.session.commit()

        invite = self._make_invite('flight', user.id, og_title='Custom OG Title')
        og = _build_og_meta(invite)
        assert og['og:title'] == 'Custom OG Title'

    def test_og_fallback_unknown_type(self):
        """Unknown resolved type falls back to generic MYSTES branding."""
        from routes_sharing import _build_og_meta
        user = User(email='og@test.com', name='OG Tester')
        user.set_password('Test1234!')
        db.session.add(user)
        db.session.commit()

        invite = self._make_invite('car', user.id)
        og = _build_og_meta(invite)
        assert 'MYSTES' in og['og:title']


# ================================================================
# Part 6: Friendship Companion Features (Build #220)
# ================================================================

class TestFriendshipCompanionModel:
    """Test enhanced Friendship fields."""

    def test_nickname_field(self):
        user1 = User(email='u1@test.com', name='User1')
        user1.set_password('Test1234!')
        user2 = User(email='u2@test.com', name='User2')
        user2.set_password('Test1234!')
        db.session.add_all([user1, user2])
        db.session.commit()

        friendship = Friendship(
            requester_id=user1.id,
            addressee_id=user2.id,
            status='accepted',
            nickname='Travel Buddy',
        )
        db.session.add(friendship)
        db.session.commit()

        fetched = db.session.get(Friendship, friendship.id)
        assert fetched.nickname == 'Travel Buddy'

    def test_trips_together_count(self):
        user1 = User(email='u1@test.com', name='User1')
        user1.set_password('Test1234!')
        user2 = User(email='u2@test.com', name='User2')
        user2.set_password('Test1234!')
        db.session.add_all([user1, user2])
        db.session.commit()

        friendship = Friendship(
            requester_id=user1.id,
            addressee_id=user2.id,
            status='accepted',
            trips_together_count=5,
            first_trip_together_at=datetime.now(timezone.utc),
        )
        db.session.add(friendship)
        db.session.commit()

        fetched = db.session.get(Friendship, friendship.id)
        assert fetched.trips_together_count == 5
        assert fetched.first_trip_together_at is not None

    def test_companion_fields_default_null(self):
        user1 = User(email='u1@test.com', name='User1')
        user1.set_password('Test1234!')
        user2 = User(email='u2@test.com', name='User2')
        user2.set_password('Test1234!')
        db.session.add_all([user1, user2])
        db.session.commit()

        friendship = Friendship(
            requester_id=user1.id,
            addressee_id=user2.id,
            status='pending',
        )
        db.session.add(friendship)
        db.session.commit()

        assert friendship.nickname is None
        assert friendship.trips_together_count == 0
        assert friendship.first_trip_together_at is None


class TestCompanionNicknameAPI:
    """POST /api/friends/<id>/nickname"""

    def _create_friendship(self, user_id):
        """Create a second user and an accepted friendship."""
        friend = User(email='friend@test.com', name='Friend User')
        friend.set_password('Test1234!')
        db.session.add(friend)
        db.session.commit()

        friendship = Friendship(
            requester_id=user_id,
            addressee_id=friend.id,
            status='accepted',
        )
        db.session.add(friendship)
        db.session.commit()
        return friendship

    def test_set_nickname(self, auth_client):
        with app.app_context():
            user = _get_test_user()
            friendship = self._create_friendship(user.id)
            fid = friendship.id

        resp = auth_client.post(f'/api/friends/{fid}/nickname',
            data=json.dumps({'nickname': 'Mom'}),
            content_type='application/json',
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        assert data['nickname'] == 'Mom'

    def test_clear_nickname(self, auth_client):
        with app.app_context():
            user = _get_test_user()
            friendship = self._create_friendship(user.id)
            friendship.nickname = 'Old Nick'
            db.session.commit()
            fid = friendship.id

        resp = auth_client.post(f'/api/friends/{fid}/nickname',
            data=json.dumps({'nickname': ''}),
            content_type='application/json',
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['nickname'] is None

    def test_truncate_long_nickname(self, auth_client):
        with app.app_context():
            user = _get_test_user()
            friendship = self._create_friendship(user.id)
            fid = friendship.id

        long_name = 'A' * 100
        resp = auth_client.post(f'/api/friends/{fid}/nickname',
            data=json.dumps({'nickname': long_name}),
            content_type='application/json',
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data['nickname']) == 50

    def test_not_found(self, auth_client):
        resp = auth_client.post('/api/friends/99999/nickname',
            data=json.dumps({'nickname': 'Test'}),
            content_type='application/json',
        )
        assert resp.status_code == 404

    def test_not_your_friendship(self, auth_client):
        with app.app_context():
            # Create two other users and a friendship between them
            other1 = User(email='other1@test.com', name='Other1')
            other1.set_password('Test1234!')
            other2 = User(email='other2@test.com', name='Other2')
            other2.set_password('Test1234!')
            db.session.add_all([other1, other2])
            db.session.commit()

            friendship = Friendship(
                requester_id=other1.id,
                addressee_id=other2.id,
                status='accepted',
            )
            db.session.add(friendship)
            db.session.commit()
            fid = friendship.id

        resp = auth_client.post(f'/api/friends/{fid}/nickname',
            data=json.dumps({'nickname': 'Hack'}),
            content_type='application/json',
        )
        assert resp.status_code == 403


class TestCompanionsListAPI:
    """GET /api/friends/companions"""

    def test_empty_list(self, auth_client):
        resp = auth_client.get('/api/friends/companions')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['count'] == 0
        assert data['companions'] == []

    def test_list_with_companions(self, auth_client):
        with app.app_context():
            user = _get_test_user()
            friend1 = User(email='f1@test.com', name='Friend One')
            friend1.set_password('Test1234!')
            friend2 = User(email='f2@test.com', name='Friend Two')
            friend2.set_password('Test1234!')
            db.session.add_all([friend1, friend2])
            db.session.commit()

            f1 = Friendship(
                requester_id=user.id,
                addressee_id=friend1.id,
                status='accepted',
                nickname='Bestie',
                trips_together_count=3,
            )
            f2 = Friendship(
                requester_id=friend2.id,
                addressee_id=user.id,
                status='accepted',
                trips_together_count=1,
            )
            db.session.add_all([f1, f2])
            db.session.commit()

        resp = auth_client.get('/api/friends/companions')
        data = resp.get_json()
        assert data['count'] == 2

        # Sorted by trips_together descending
        assert data['companions'][0]['name'] == 'Friend One'
        assert data['companions'][0]['nickname'] == 'Bestie'
        assert data['companions'][0]['trips_together'] == 3
        assert data['companions'][1]['name'] == 'Friend Two'
        assert data['companions'][1]['trips_together'] == 1

    def test_pending_excluded(self, auth_client):
        """Pending friendships not in companions list."""
        with app.app_context():
            user = _get_test_user()
            pending_friend = User(email='pend@test.com', name='Pending')
            pending_friend.set_password('Test1234!')
            db.session.add(pending_friend)
            db.session.commit()

            f = Friendship(
                requester_id=user.id,
                addressee_id=pending_friend.id,
                status='pending',
            )
            db.session.add(f)
            db.session.commit()

        resp = auth_client.get('/api/friends/companions')
        data = resp.get_json()
        assert data['count'] == 0


# ================================================================
# Part 7: Cross-Build Integration
# ================================================================

class TestCrossBuildIntegration:
    """Test features work together across Block 1 builds."""

    def test_create_share_then_resolve(self, auth_client):
        """Create a share link via API, then resolve it as anonymous user."""
        # Create a link
        resp = auth_client.post('/api/share/create',
            data=json.dumps({
                'link_type': 'referral',
                'object_id': 0,
                'message': 'Join me on MYSTES!',
            }),
            content_type='application/json',
        )
        assert resp.status_code == 200
        token = resp.get_json()['link']['token']

        # Anonymous client resolves it
        anon_client = app.test_client()
        resolve_resp = anon_client.get(f'/i/{token}')
        assert resolve_resp.status_code == 200
        html = resolve_resp.data.decode()
        assert 'Join me on MYSTES!' in html

        # Click was tracked
        with app.app_context():
            link = InviteLink.query.filter_by(token=token).first()
            assert link.click_count == 1

    def test_create_revoke_then_resolve_fails(self, auth_client):
        """Create, revoke, then resolution returns 404."""
        resp = auth_client.post('/api/share/create',
            data=json.dumps({'link_type': 'flight', 'object_id': 1}),
            content_type='application/json',
        )
        token = resp.get_json()['link']['token']

        # Revoke
        auth_client.post(f'/api/share/{token}/revoke')

        # Anonymous resolution fails
        anon_client = app.test_client()
        resolve_resp = anon_client.get(f'/i/{token}')
        assert resolve_resp.status_code == 404

    def test_fx_display_no_market_leak(self):
        """FX-aware display never leaks POS market codes."""
        from anastasia.arbitrage.spread import SpreadResult

        result = SpreadResult(
            us_retail_price=1400.0,
            foreign_pos_price=800.0,
            foreign_market="DK",
            spread=600.0,
            fee_percent=0.35,
            service_fee=210.0,
            customer_price=1010.0,
            customer_savings=390.0,
            savings_percent=27.9,
            has_arbitrage=True,
        )

        display = result.to_display()
        display_str = json.dumps(display)
        assert 'DK' not in display_str
        assert 'foreign_market' not in display_str

    def test_spread_no_max_cap(self):
        """Service fee has $3 min, NO max cap — even on massive spread."""
        from anastasia.arbitrage.spread import SpreadCalculator

        calc = SpreadCalculator()
        # $10,000 spread at 50% = $5,000 fee — NO cap
        result = calc.calculate(15000.0, 5000.0, "IN", 0.50)
        assert result.service_fee == 5000.0
        assert result.has_arbitrage is True
        assert result.customer_savings == 5000.0
