"""
MYSTES Tests — Block 8 (Builds #235-237: Corporate Workspaces)

Tests for:
- Workspace model (#235): create, to_dict, slug generation, tier methods
- WorkspaceMember model (#235): create, to_dict, unique constraint, role helpers
- TravelPolicy model (#236): create, to_dict, department scoping
- BookingApproval model (#236): create, to_dict, status lifecycle
- Workspace API (#235): create, list, get, update, member CRUD, invite code join
- Travel Policy API (#236): CRUD, approval workflow (request, list, decide)
- Corporate Dashboard API (#237): dashboard stats, book-on-behalf, bookings list, CSV export
- Feature flag gating: all flagged endpoints return 403 when disabled
- Access control: admin-only, manager roles, member visibility scoping

Run: python3 -m pytest tests/test_block8_corporate.py -v
"""

import csv
import io
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
    User, Booking, TripPlan, TripMember, FeatureFlag,
    Workspace, WorkspaceMember, TravelPolicy, BookingApproval,
)


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


def _login_client_as(c, user_id):
    with c.session_transaction() as sess:
        sess['_user_id'] = str(user_id)


def _create_user(email, name='Test User'):
    user = User(email=email, name=name, is_verified=True, is_active=True)
    user.set_password('TestPass1!')
    db.session.add(user)
    db.session.commit()
    return user


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


ALL_FLAGS = ('corporate_workspaces', 'travel_policies', 'corporate_dashboard')


def _create_workspace(owner_id, name='Acme Corp', tier='starter'):
    """Create a workspace + owner membership. Returns (workspace, owner_membership)."""
    import re
    slug = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')
    # Ensure unique slug
    base = slug
    counter = 1
    while Workspace.query.filter_by(slug=slug).first():
        slug = f"{base}-{counter}"
        counter += 1

    ws = Workspace(
        name=name, slug=slug, owner_user_id=owner_id,
        tier=tier, max_seats={'starter': 25, 'pro': 100, 'enterprise': 9999}.get(tier, 25),
        invite_code=f'WS-TEST-{slug[:6].upper()}',
    )
    db.session.add(ws)
    db.session.flush()

    member = WorkspaceMember(
        workspace_id=ws.id, user_id=owner_id,
        role='admin', member_type='employee',
    )
    db.session.add(member)
    db.session.commit()
    return ws, member


def _add_member(ws, user_id, role='member', member_type='employee', department=None):
    """Add a member to workspace."""
    m = WorkspaceMember(
        workspace_id=ws.id, user_id=user_id,
        role=role, member_type=member_type, department=department,
    )
    db.session.add(m)
    db.session.commit()
    return m


# ================================================================
# Part 1: Model Tests — Workspace (#235)
# ================================================================

class TestWorkspaceModel:

    def test_create_workspace(self, client):
        with app.app_context():
            owner = _create_user('owner@acme.com', 'CEO')
            ws, mem = _create_workspace(owner.id)
            assert ws.id is not None
            assert ws.slug == 'acme-corp'
            assert ws.tier == 'starter'
            assert mem.role == 'admin'

    def test_workspace_to_dict(self, client):
        with app.app_context():
            owner = _create_user('owner@t.com')
            ws, _ = _create_workspace(owner.id)
            d = ws.to_dict(include_stats=True)
            assert d['name'] == 'Acme Corp'
            assert d['fee_percent'] == 35.0
            assert d['per_seat_price'] == 4.99
            assert d['seat_count'] == 1

    def test_workspace_tier_methods(self, client):
        with app.app_context():
            owner = _create_user('owner@t.com')
            ws, _ = _create_workspace(owner.id, tier='pro')
            assert ws.fee_percent() == 30.0
            assert ws.per_seat_price() == 3.99
            ws.tier = 'enterprise'
            assert ws.fee_percent() == 25.0
            assert ws.per_seat_price() == 2.99

    def test_workspace_seat_count(self, client):
        with app.app_context():
            owner = _create_user('owner@t.com')
            ws, _ = _create_workspace(owner.id)
            assert ws.seat_count() == 1
            u2 = _create_user('u2@t.com')
            _add_member(ws, u2.id)
            assert ws.seat_count() == 2


class TestWorkspaceMemberModel:

    def test_create_member(self, client):
        with app.app_context():
            owner = _create_user('owner@t.com')
            ws, _ = _create_workspace(owner.id)
            emp = _create_user('emp@t.com', 'Employee')
            m = _add_member(ws, emp.id, role='member', department='Engineering')
            assert m.id is not None
            assert m.department == 'Engineering'

    def test_member_to_dict(self, client):
        with app.app_context():
            owner = _create_user('owner@t.com')
            ws, _ = _create_workspace(owner.id)
            emp = _create_user('emp@t.com', 'Jane')
            m = _add_member(ws, emp.id)
            d = m.to_dict()
            assert d['user_name'] == 'Jane'
            assert d['role'] == 'member'

    def test_unique_constraint(self, client):
        with app.app_context():
            owner = _create_user('owner@t.com')
            ws, _ = _create_workspace(owner.id)
            emp = _create_user('emp@t.com')
            _add_member(ws, emp.id)
            dup = WorkspaceMember(workspace_id=ws.id, user_id=emp.id, role='member')
            db.session.add(dup)
            with pytest.raises(Exception):
                db.session.commit()
            db.session.rollback()

    def test_admin_or_manager_helper(self, client):
        with app.app_context():
            owner = _create_user('o@t.com')
            ws, admin_m = _create_workspace(owner.id)
            mgr = _create_user('mgr@t.com')
            mgr_m = _add_member(ws, mgr.id, role='travel_manager')
            emp = _create_user('emp@t.com')
            emp_m = _add_member(ws, emp.id, role='member')

            assert admin_m.is_admin_or_manager() is True
            assert mgr_m.is_admin_or_manager() is True
            assert emp_m.is_admin_or_manager() is False


# ================================================================
# Part 2: Model Tests — Travel Policy + Approval (#236)
# ================================================================

class TestTravelPolicyModel:

    def test_create_policy(self, client):
        with app.app_context():
            owner = _create_user('o@t.com')
            ws, _ = _create_workspace(owner.id)
            p = TravelPolicy(
                workspace_id=ws.id, name='Standard Policy',
                max_flight_usd=500.0, approval_threshold_usd=300.0,
                preferred_airlines='AA,UA,DL', preferred_cabin='economy',
            )
            db.session.add(p)
            db.session.commit()
            assert p.id is not None

    def test_policy_to_dict(self, client):
        with app.app_context():
            owner = _create_user('o@t.com')
            ws, _ = _create_workspace(owner.id)
            p = TravelPolicy(
                workspace_id=ws.id, name='Eng Policy',
                max_flight_usd=1000.0, applies_to_department='Engineering',
            )
            db.session.add(p)
            db.session.commit()
            d = p.to_dict()
            assert d['name'] == 'Eng Policy'
            assert d['max_flight_usd'] == 1000.0
            assert d['applies_to_department'] == 'Engineering'


class TestBookingApprovalModel:

    def test_create_approval(self, client):
        with app.app_context():
            owner = _create_user('o@t.com')
            ws, _ = _create_workspace(owner.id)
            emp = _create_user('emp@t.com', 'Jane')
            a = BookingApproval(
                workspace_id=ws.id, requester_user_id=emp.id,
                booking_type='flight', estimated_cost_usd=800.0,
                expense_tag='Q4 Conference', status='pending',
            )
            db.session.add(a)
            db.session.commit()
            assert a.id is not None
            assert a.status == 'pending'

    def test_approval_to_dict(self, client):
        with app.app_context():
            owner = _create_user('o@t.com')
            ws, _ = _create_workspace(owner.id)
            emp = _create_user('emp@t.com', 'Jane')
            a = BookingApproval(
                workspace_id=ws.id, requester_user_id=emp.id,
                booking_type='hotel', estimated_cost_usd=250.0,
                policy_reason='Exceeds max hotel per night ($200)',
            )
            db.session.add(a)
            db.session.commit()
            d = a.to_dict()
            assert d['requester_name'] == 'Jane'
            assert d['booking_type'] == 'hotel'
            assert 'Exceeds' in d['policy_reason']


# ================================================================
# Part 3: Feature Flag Gating
# ================================================================

class TestFeatureFlagGating:

    def test_create_workspace_flag_disabled(self, client):
        with app.app_context():
            u = _create_user('u@t.com')
            _login_client_as(client, u.id)
        r = client.post('/api/workspaces', json={'name': 'X'})
        assert r.status_code == 403

    def test_list_workspaces_flag_disabled(self, client):
        with app.app_context():
            u = _create_user('u@t.com')
            _login_client_as(client, u.id)
        r = client.get('/api/workspaces')
        assert r.status_code == 403

    def test_create_policy_flag_disabled(self, client):
        with app.app_context():
            u = _create_user('u@t.com')
            _login_client_as(client, u.id)
        r = client.post('/api/workspaces/acme/policies', json={'name': 'X'})
        assert r.status_code == 403

    def test_dashboard_flag_disabled(self, client):
        with app.app_context():
            u = _create_user('u@t.com')
            _login_client_as(client, u.id)
        r = client.get('/api/workspaces/acme/dashboard')
        assert r.status_code == 403

    def test_approval_flag_disabled(self, client):
        with app.app_context():
            u = _create_user('u@t.com')
            _login_client_as(client, u.id)
        r = client.post('/api/workspaces/acme/approvals', json={'booking_type': 'flight', 'estimated_cost_usd': 100})
        assert r.status_code == 403

    def test_export_flag_disabled(self, client):
        with app.app_context():
            u = _create_user('u@t.com')
            _login_client_as(client, u.id)
        r = client.get('/api/workspaces/acme/export')
        assert r.status_code == 403

    def test_new_flags_registered(self, client):
        with app.app_context():
            FeatureFlag.init_default_flags()
            for key in ALL_FLAGS:
                flag = FeatureFlag.query.filter_by(flag_key=key).first()
                assert flag is not None, f"Flag {key} not found"
                assert flag.layer == 3


# ================================================================
# Part 4: Workspace API — Build #235
# ================================================================

class TestWorkspaceAPI:

    def test_create_workspace(self, client):
        with app.app_context():
            _enable_flags('corporate_workspaces')
            user = _create_user('ceo@acme.com', 'CEO')
            _login_client_as(client, user.id)

        r = client.post('/api/workspaces', json={
            'name': 'Acme Corporation',
            'tier': 'pro',
            'company_domain': 'acme.com',
            'industry': 'Technology',
        })
        assert r.status_code == 200
        data = r.get_json()
        ws = data['workspace']
        assert ws['name'] == 'Acme Corporation'
        assert ws['tier'] == 'pro'
        assert ws['fee_percent'] == 30.0
        assert ws['per_seat_price'] == 3.99
        assert ws['seat_count'] == 1
        assert ws['invite_code'] is not None

    def test_create_workspace_no_name(self, client):
        with app.app_context():
            _enable_flags('corporate_workspaces')
            u = _create_user('u@t.com')
            _login_client_as(client, u.id)
        r = client.post('/api/workspaces', json={})
        assert r.status_code == 400

    def test_create_workspace_invalid_tier(self, client):
        with app.app_context():
            _enable_flags('corporate_workspaces')
            u = _create_user('u@t.com')
            _login_client_as(client, u.id)
        r = client.post('/api/workspaces', json={'name': 'X', 'tier': 'bogus'})
        assert r.status_code == 400

    def test_list_workspaces(self, client):
        with app.app_context():
            _enable_flags('corporate_workspaces')
            user = _create_user('u@t.com')
            ws1, _ = _create_workspace(user.id, 'Corp A')
            ws2, _ = _create_workspace(user.id, 'Corp B')
            _login_client_as(client, user.id)

        r = client.get('/api/workspaces')
        assert r.status_code == 200
        data = r.get_json()
        assert len(data['workspaces']) == 2

    def test_get_workspace(self, client):
        with app.app_context():
            _enable_flags('corporate_workspaces')
            owner = _create_user('o@t.com')
            ws, _ = _create_workspace(owner.id)
            slug = ws.slug
            _login_client_as(client, owner.id)

        r = client.get(f'/api/workspaces/{slug}')
        assert r.status_code == 200
        d = r.get_json()['workspace']
        assert d['my_role'] == 'admin'

    def test_get_workspace_non_member(self, client):
        with app.app_context():
            _enable_flags('corporate_workspaces')
            owner = _create_user('o@t.com')
            ws, _ = _create_workspace(owner.id)
            slug = ws.slug
            outsider = _create_user('outsider@t.com')
            _login_client_as(client, outsider.id)

        r = client.get(f'/api/workspaces/{slug}')
        assert r.status_code == 403

    def test_update_workspace(self, client):
        with app.app_context():
            _enable_flags('corporate_workspaces')
            owner = _create_user('o@t.com')
            ws, _ = _create_workspace(owner.id)
            slug = ws.slug
            _login_client_as(client, owner.id)

        r = client.put(f'/api/workspaces/{slug}', json={
            'name': 'Acme Inc',
            'industry': 'Finance',
            'tier': 'enterprise',
        })
        assert r.status_code == 200
        d = r.get_json()['workspace']
        assert d['name'] == 'Acme Inc'
        assert d['industry'] == 'Finance'
        assert d['tier'] == 'enterprise'
        assert d['fee_percent'] == 25.0

    def test_update_workspace_non_admin(self, client):
        with app.app_context():
            _enable_flags('corporate_workspaces')
            owner = _create_user('o@t.com')
            ws, _ = _create_workspace(owner.id)
            slug = ws.slug
            emp = _create_user('emp@t.com')
            _add_member(ws, emp.id, role='member')
            _login_client_as(client, emp.id)

        r = client.put(f'/api/workspaces/{slug}', json={'name': 'Hacked'})
        assert r.status_code == 403


class TestMemberManagementAPI:

    def test_invite_member(self, client):
        with app.app_context():
            _enable_flags('corporate_workspaces')
            owner = _create_user('o@t.com', 'Admin')
            ws, _ = _create_workspace(owner.id)
            slug = ws.slug
            emp = _create_user('emp@acme.com', 'Jane')
            _login_client_as(client, owner.id)

        r = client.post(f'/api/workspaces/{slug}/members', json={
            'email': 'emp@acme.com',
            'role': 'member',
            'member_type': 'employee',
            'department': 'Engineering',
        })
        assert r.status_code == 200
        d = r.get_json()['member']
        assert d['user_name'] == 'Jane'
        assert d['role'] == 'member'
        assert d['department'] == 'Engineering'

    def test_invite_nonexistent_user(self, client):
        with app.app_context():
            _enable_flags('corporate_workspaces')
            owner = _create_user('o@t.com')
            ws, _ = _create_workspace(owner.id)
            slug = ws.slug
            _login_client_as(client, owner.id)

        r = client.post(f'/api/workspaces/{slug}/members', json={
            'email': 'nobody@acme.com',
        })
        assert r.status_code == 404

    def test_invite_duplicate_member(self, client):
        with app.app_context():
            _enable_flags('corporate_workspaces')
            owner = _create_user('o@t.com')
            ws, _ = _create_workspace(owner.id)
            slug = ws.slug
            emp = _create_user('emp@t.com')
            _add_member(ws, emp.id)
            _login_client_as(client, owner.id)

        r = client.post(f'/api/workspaces/{slug}/members', json={
            'email': 'emp@t.com',
        })
        assert r.status_code == 409

    def test_invite_seat_limit(self, client):
        """Inviting beyond max_seats is rejected."""
        with app.app_context():
            _enable_flags('corporate_workspaces')
            owner = _create_user('o@t.com')
            ws, _ = _create_workspace(owner.id)
            ws.max_seats = 1  # Owner already fills the 1 seat
            db.session.commit()
            slug = ws.slug
            emp = _create_user('emp@t.com')
            _login_client_as(client, owner.id)

        r = client.post(f'/api/workspaces/{slug}/members', json={
            'email': 'emp@t.com',
        })
        assert r.status_code == 400
        assert 'limit' in r.get_json()['error'].lower()

    def test_invite_member_only_denied(self, client):
        """Regular member cannot invite others."""
        with app.app_context():
            _enable_flags('corporate_workspaces')
            owner = _create_user('o@t.com')
            ws, _ = _create_workspace(owner.id)
            slug = ws.slug
            emp = _create_user('emp@t.com')
            _add_member(ws, emp.id, role='member')
            target = _create_user('target@t.com')
            _login_client_as(client, emp.id)

        r = client.post(f'/api/workspaces/{slug}/members', json={
            'email': 'target@t.com',
        })
        assert r.status_code == 403

    def test_travel_manager_can_invite(self, client):
        """Travel manager can invite members."""
        with app.app_context():
            _enable_flags('corporate_workspaces')
            owner = _create_user('o@t.com')
            ws, _ = _create_workspace(owner.id)
            slug = ws.slug
            mgr = _create_user('mgr@t.com')
            _add_member(ws, mgr.id, role='travel_manager')
            target = _create_user('target@t.com')
            _login_client_as(client, mgr.id)

        r = client.post(f'/api/workspaces/{slug}/members', json={
            'email': 'target@t.com',
        })
        assert r.status_code == 200

    def test_list_members(self, client):
        with app.app_context():
            _enable_flags('corporate_workspaces')
            owner = _create_user('o@t.com')
            ws, _ = _create_workspace(owner.id)
            slug = ws.slug
            for i in range(3):
                u = _create_user(f'u{i}@t.com', f'User {i}')
                _add_member(ws, u.id)
            _login_client_as(client, owner.id)

        r = client.get(f'/api/workspaces/{slug}/members')
        assert r.status_code == 200
        assert r.get_json()['total'] == 4  # owner + 3

    def test_update_member_role(self, client):
        with app.app_context():
            _enable_flags('corporate_workspaces')
            owner = _create_user('o@t.com')
            ws, _ = _create_workspace(owner.id)
            slug = ws.slug
            emp = _create_user('emp@t.com')
            m = _add_member(ws, emp.id, role='member')
            mid = m.id
            _login_client_as(client, owner.id)

        r = client.put(f'/api/workspaces/{slug}/members/{mid}', json={
            'role': 'travel_manager',
            'department': 'Sales',
        })
        assert r.status_code == 200
        d = r.get_json()['member']
        assert d['role'] == 'travel_manager'
        assert d['department'] == 'Sales'

    def test_cannot_demote_owner(self, client):
        with app.app_context():
            _enable_flags('corporate_workspaces')
            owner = _create_user('o@t.com')
            ws, owner_m = _create_workspace(owner.id)
            slug = ws.slug
            mid = owner_m.id
            _login_client_as(client, owner.id)

        r = client.put(f'/api/workspaces/{slug}/members/{mid}', json={
            'role': 'member',
        })
        assert r.status_code == 400

    def test_remove_member(self, client):
        with app.app_context():
            _enable_flags('corporate_workspaces')
            owner = _create_user('o@t.com')
            ws, _ = _create_workspace(owner.id)
            slug = ws.slug
            emp = _create_user('emp@t.com')
            m = _add_member(ws, emp.id)
            mid = m.id
            _login_client_as(client, owner.id)

        r = client.delete(f'/api/workspaces/{slug}/members/{mid}')
        assert r.status_code == 200

        # Verify member is deactivated
        with app.app_context():
            m = WorkspaceMember.query.get(mid)
            assert m.is_active is False

    def test_cannot_remove_owner(self, client):
        with app.app_context():
            _enable_flags('corporate_workspaces')
            owner = _create_user('o@t.com')
            ws, owner_m = _create_workspace(owner.id)
            slug = ws.slug
            mid = owner_m.id
            _login_client_as(client, owner.id)

        r = client.delete(f'/api/workspaces/{slug}/members/{mid}')
        assert r.status_code == 400

    def test_join_by_invite_code(self, client):
        with app.app_context():
            _enable_flags('corporate_workspaces')
            owner = _create_user('o@t.com')
            ws, _ = _create_workspace(owner.id)
            code = ws.invite_code
            joiner = _create_user('joiner@t.com')
            _login_client_as(client, joiner.id)

        r = client.post(f'/api/workspaces/join/{code}')
        assert r.status_code == 200
        d = r.get_json()
        assert d['member']['role'] == 'member'
        assert d['workspace']['name'] == 'Acme Corp'

    def test_join_invalid_code(self, client):
        with app.app_context():
            _enable_flags('corporate_workspaces')
            u = _create_user('u@t.com')
            _login_client_as(client, u.id)
        r = client.post('/api/workspaces/join/BOGUS')
        assert r.status_code == 404

    def test_join_already_member(self, client):
        with app.app_context():
            _enable_flags('corporate_workspaces')
            owner = _create_user('o@t.com')
            ws, _ = _create_workspace(owner.id)
            code = ws.invite_code
            _login_client_as(client, owner.id)

        r = client.post(f'/api/workspaces/join/{code}')
        assert r.status_code == 409

    def test_reactivate_removed_member(self, client):
        """A removed member can rejoin via invite code."""
        with app.app_context():
            _enable_flags('corporate_workspaces')
            owner = _create_user('o@t.com')
            ws, _ = _create_workspace(owner.id)
            code = ws.invite_code
            emp = _create_user('emp@t.com')
            m = _add_member(ws, emp.id)
            m.is_active = False
            db.session.commit()
            _login_client_as(client, emp.id)

        r = client.post(f'/api/workspaces/join/{code}')
        assert r.status_code == 200


# ================================================================
# Part 5: Travel Policy API — Build #236
# ================================================================

class TestTravelPolicyAPI:

    def test_create_policy(self, client):
        with app.app_context():
            _enable_flags(*ALL_FLAGS)
            owner = _create_user('o@t.com')
            ws, _ = _create_workspace(owner.id)
            slug = ws.slug
            _login_client_as(client, owner.id)

        r = client.post(f'/api/workspaces/{slug}/policies', json={
            'name': 'Standard Travel',
            'max_flight_usd': 500.0,
            'max_hotel_per_night_usd': 200.0,
            'preferred_airlines': 'AA,UA,DL',
            'preferred_cabin': 'economy',
            'approval_threshold_usd': 300.0,
            'advance_booking_days': 7,
        })
        assert r.status_code == 200
        p = r.get_json()['policy']
        assert p['name'] == 'Standard Travel'
        assert p['max_flight_usd'] == 500.0
        assert p['approval_threshold_usd'] == 300.0

    def test_create_policy_no_name(self, client):
        with app.app_context():
            _enable_flags(*ALL_FLAGS)
            owner = _create_user('o@t.com')
            ws, _ = _create_workspace(owner.id)
            slug = ws.slug
            _login_client_as(client, owner.id)
        r = client.post(f'/api/workspaces/{slug}/policies', json={})
        assert r.status_code == 400

    def test_create_policy_non_admin(self, client):
        with app.app_context():
            _enable_flags(*ALL_FLAGS)
            owner = _create_user('o@t.com')
            ws, _ = _create_workspace(owner.id)
            slug = ws.slug
            emp = _create_user('emp@t.com')
            _add_member(ws, emp.id, role='member')
            _login_client_as(client, emp.id)
        r = client.post(f'/api/workspaces/{slug}/policies', json={'name': 'Hack Policy'})
        assert r.status_code == 403

    def test_list_policies(self, client):
        with app.app_context():
            _enable_flags(*ALL_FLAGS)
            owner = _create_user('o@t.com')
            ws, _ = _create_workspace(owner.id)
            slug = ws.slug
            for i in range(3):
                db.session.add(TravelPolicy(workspace_id=ws.id, name=f'Policy {i}'))
            db.session.commit()
            _login_client_as(client, owner.id)

        r = client.get(f'/api/workspaces/{slug}/policies')
        assert r.status_code == 200
        assert len(r.get_json()['policies']) == 3

    def test_update_policy(self, client):
        with app.app_context():
            _enable_flags(*ALL_FLAGS)
            owner = _create_user('o@t.com')
            ws, _ = _create_workspace(owner.id)
            slug = ws.slug
            p = TravelPolicy(workspace_id=ws.id, name='Old Name', max_flight_usd=500)
            db.session.add(p)
            db.session.commit()
            pid = p.id
            _login_client_as(client, owner.id)

        r = client.put(f'/api/workspaces/{slug}/policies/{pid}', json={
            'name': 'Updated Policy',
            'max_flight_usd': 800.0,
            'blackout_dates': [{'start': '2027-12-20', 'end': '2028-01-05'}],
        })
        assert r.status_code == 200
        d = r.get_json()['policy']
        assert d['name'] == 'Updated Policy'
        assert d['max_flight_usd'] == 800.0
        assert d['blackout_dates_json'] is not None

    def test_delete_policy(self, client):
        with app.app_context():
            _enable_flags(*ALL_FLAGS)
            owner = _create_user('o@t.com')
            ws, _ = _create_workspace(owner.id)
            slug = ws.slug
            p = TravelPolicy(workspace_id=ws.id, name='Delete Me')
            db.session.add(p)
            db.session.commit()
            pid = p.id
            _login_client_as(client, owner.id)

        r = client.delete(f'/api/workspaces/{slug}/policies/{pid}')
        assert r.status_code == 200

        # Verify soft delete
        with app.app_context():
            p = TravelPolicy.query.get(pid)
            assert p.is_active is False


# ================================================================
# Part 6: Approval Workflow API — Build #236
# ================================================================

class TestApprovalWorkflowAPI:

    def test_request_approval(self, client):
        with app.app_context():
            _enable_flags(*ALL_FLAGS)
            owner = _create_user('o@t.com')
            ws, _ = _create_workspace(owner.id)
            slug = ws.slug
            emp = _create_user('emp@t.com', 'Jane')
            _add_member(ws, emp.id, department='Sales')
            _login_client_as(client, emp.id)

        r = client.post(f'/api/workspaces/{slug}/approvals', json={
            'booking_type': 'flight',
            'estimated_cost_usd': 800.0,
            'description': 'Client meeting in Chicago',
            'expense_tag': 'Q4 Sales',
        })
        assert r.status_code == 200
        a = r.get_json()['approval']
        assert a['booking_type'] == 'flight'
        assert a['estimated_cost_usd'] == 800.0
        assert a['expense_tag'] == 'Q4 Sales'
        assert a['status'] == 'pending'

    def test_approval_auto_links_policy(self, client):
        """When a policy threshold is exceeded, the approval links to the policy."""
        with app.app_context():
            _enable_flags(*ALL_FLAGS)
            owner = _create_user('o@t.com')
            ws, _ = _create_workspace(owner.id)
            slug = ws.slug
            p = TravelPolicy(workspace_id=ws.id, name='Limit',
                             approval_threshold_usd=300.0)
            db.session.add(p)
            db.session.commit()
            pid = p.id
            emp = _create_user('emp@t.com')
            _add_member(ws, emp.id)
            _login_client_as(client, emp.id)

        r = client.post(f'/api/workspaces/{slug}/approvals', json={
            'booking_type': 'flight',
            'estimated_cost_usd': 500.0,
        })
        assert r.status_code == 200
        a = r.get_json()['approval']
        assert a['policy_id'] == pid
        assert 'threshold' in a['policy_reason'].lower()

    def test_list_approvals_admin_sees_all(self, client):
        with app.app_context():
            _enable_flags(*ALL_FLAGS)
            owner = _create_user('o@t.com')
            ws, _ = _create_workspace(owner.id)
            slug = ws.slug
            e1 = _create_user('e1@t.com')
            e2 = _create_user('e2@t.com')
            _add_member(ws, e1.id)
            _add_member(ws, e2.id)
            for u in [e1, e2]:
                db.session.add(BookingApproval(
                    workspace_id=ws.id, requester_user_id=u.id,
                    booking_type='flight', estimated_cost_usd=500.0,
                ))
            db.session.commit()
            _login_client_as(client, owner.id)

        r = client.get(f'/api/workspaces/{slug}/approvals')
        assert r.status_code == 200
        assert len(r.get_json()['approvals']) == 2

    def test_list_approvals_member_sees_own(self, client):
        with app.app_context():
            _enable_flags(*ALL_FLAGS)
            owner = _create_user('o@t.com')
            ws, _ = _create_workspace(owner.id)
            slug = ws.slug
            e1 = _create_user('e1@t.com')
            e2 = _create_user('e2@t.com')
            _add_member(ws, e1.id)
            _add_member(ws, e2.id)
            for u in [e1, e2]:
                db.session.add(BookingApproval(
                    workspace_id=ws.id, requester_user_id=u.id,
                    booking_type='flight', estimated_cost_usd=500.0,
                ))
            db.session.commit()
            _login_client_as(client, e1.id)

        r = client.get(f'/api/workspaces/{slug}/approvals')
        assert r.status_code == 200
        assert len(r.get_json()['approvals']) == 1

    def test_approve_booking(self, client):
        with app.app_context():
            _enable_flags(*ALL_FLAGS)
            owner = _create_user('o@t.com', 'Boss')
            ws, _ = _create_workspace(owner.id)
            slug = ws.slug
            emp = _create_user('emp@t.com')
            _add_member(ws, emp.id)
            a = BookingApproval(
                workspace_id=ws.id, requester_user_id=emp.id,
                booking_type='flight', estimated_cost_usd=800.0,
            )
            db.session.add(a)
            db.session.commit()
            aid = a.id
            _login_client_as(client, owner.id)

        r = client.put(f'/api/workspaces/{slug}/approvals/{aid}', json={
            'decision': 'approved',
            'note': 'Go ahead, important client.',
        })
        assert r.status_code == 200
        d = r.get_json()['approval']
        assert d['status'] == 'approved'
        assert d['approver_name'] == 'Boss'
        assert d['approver_note'] == 'Go ahead, important client.'
        assert d['decided_at'] is not None

    def test_deny_booking(self, client):
        with app.app_context():
            _enable_flags(*ALL_FLAGS)
            owner = _create_user('o@t.com')
            ws, _ = _create_workspace(owner.id)
            slug = ws.slug
            emp = _create_user('emp@t.com')
            _add_member(ws, emp.id)
            a = BookingApproval(
                workspace_id=ws.id, requester_user_id=emp.id,
                booking_type='flight', estimated_cost_usd=5000.0,
            )
            db.session.add(a)
            db.session.commit()
            aid = a.id
            _login_client_as(client, owner.id)

        r = client.put(f'/api/workspaces/{slug}/approvals/{aid}', json={
            'decision': 'denied',
            'note': 'Too expensive. Find a cheaper option.',
        })
        assert r.status_code == 200
        assert r.get_json()['approval']['status'] == 'denied'

    def test_cannot_decide_already_decided(self, client):
        with app.app_context():
            _enable_flags(*ALL_FLAGS)
            owner = _create_user('o@t.com')
            ws, _ = _create_workspace(owner.id)
            slug = ws.slug
            emp = _create_user('emp@t.com')
            _add_member(ws, emp.id)
            a = BookingApproval(
                workspace_id=ws.id, requester_user_id=emp.id,
                booking_type='flight', estimated_cost_usd=800.0,
                status='approved',
            )
            db.session.add(a)
            db.session.commit()
            aid = a.id
            _login_client_as(client, owner.id)

        r = client.put(f'/api/workspaces/{slug}/approvals/{aid}', json={
            'decision': 'denied',
        })
        assert r.status_code == 400

    def test_member_cannot_approve(self, client):
        with app.app_context():
            _enable_flags(*ALL_FLAGS)
            owner = _create_user('o@t.com')
            ws, _ = _create_workspace(owner.id)
            slug = ws.slug
            emp = _create_user('emp@t.com')
            _add_member(ws, emp.id, role='member')
            a = BookingApproval(
                workspace_id=ws.id, requester_user_id=emp.id,
                booking_type='flight', estimated_cost_usd=800.0,
            )
            db.session.add(a)
            db.session.commit()
            aid = a.id
            _login_client_as(client, emp.id)

        r = client.put(f'/api/workspaces/{slug}/approvals/{aid}', json={
            'decision': 'approved',
        })
        assert r.status_code == 403

    def test_travel_manager_can_approve(self, client):
        with app.app_context():
            _enable_flags(*ALL_FLAGS)
            owner = _create_user('o@t.com')
            ws, _ = _create_workspace(owner.id)
            slug = ws.slug
            mgr = _create_user('mgr@t.com', 'Manager')
            _add_member(ws, mgr.id, role='travel_manager')
            emp = _create_user('emp@t.com')
            _add_member(ws, emp.id)
            a = BookingApproval(
                workspace_id=ws.id, requester_user_id=emp.id,
                booking_type='flight', estimated_cost_usd=800.0,
            )
            db.session.add(a)
            db.session.commit()
            aid = a.id
            _login_client_as(client, mgr.id)

        r = client.put(f'/api/workspaces/{slug}/approvals/{aid}', json={
            'decision': 'approved',
        })
        assert r.status_code == 200
        assert r.get_json()['approval']['approver_name'] == 'Manager'

    def test_approval_status_filter(self, client):
        with app.app_context():
            _enable_flags(*ALL_FLAGS)
            owner = _create_user('o@t.com')
            ws, _ = _create_workspace(owner.id)
            slug = ws.slug
            emp = _create_user('emp@t.com')
            _add_member(ws, emp.id)
            for status in ['pending', 'approved', 'denied']:
                db.session.add(BookingApproval(
                    workspace_id=ws.id, requester_user_id=emp.id,
                    booking_type='flight', estimated_cost_usd=100,
                    status=status,
                ))
            db.session.commit()
            _login_client_as(client, owner.id)

        r = client.get(f'/api/workspaces/{slug}/approvals?status=pending')
        assert r.status_code == 200
        assert len(r.get_json()['approvals']) == 1


# ================================================================
# Part 7: Corporate Dashboard — Build #237
# ================================================================

class TestDashboardAPI:

    def test_dashboard_basic(self, client):
        with app.app_context():
            _enable_flags(*ALL_FLAGS)
            owner = _create_user('o@t.com')
            ws, _ = _create_workspace(owner.id, tier='pro')
            slug = ws.slug
            for i in range(4):
                u = _create_user(f'e{i}@t.com')
                _add_member(ws, u.id, department=f'Dept {i % 2}')
            _login_client_as(client, owner.id)

        r = client.get(f'/api/workspaces/{slug}/dashboard')
        assert r.status_code == 200
        d = r.get_json()['dashboard']
        assert d['members']['total'] == 5  # owner + 4
        assert d['tier_info']['tier'] == 'pro'
        assert d['tier_info']['fee_percent'] == 30.0
        assert d['tier_info']['base_cost'] == 9.99
        assert d['tier_info']['per_seat_price'] == 3.99

    def test_dashboard_non_member(self, client):
        with app.app_context():
            _enable_flags(*ALL_FLAGS)
            owner = _create_user('o@t.com')
            ws, _ = _create_workspace(owner.id)
            slug = ws.slug
            outsider = _create_user('outsider@t.com')
            _login_client_as(client, outsider.id)

        r = client.get(f'/api/workspaces/{slug}/dashboard')
        assert r.status_code == 403


class TestBookOnBehalfAPI:

    def test_book_on_behalf(self, client):
        with app.app_context():
            _enable_flags(*ALL_FLAGS)
            owner = _create_user('admin@acme.com', 'Admin')
            ws, _ = _create_workspace(owner.id)
            slug = ws.slug
            emp = _create_user('emp@acme.com', 'Jane')
            _add_member(ws, emp.id)
            emp_id = emp.id
            _login_client_as(client, owner.id)

        r = client.post(f'/api/workspaces/{slug}/book-on-behalf', json={
            'for_user_id': emp_id,
            'trip_name': 'Chicago Client Meeting',
        })
        assert r.status_code == 200
        d = r.get_json()
        assert d['trip_name'] == 'Chicago Client Meeting'
        assert d['for_user_name'] == 'Jane'
        assert d['trip_id'] is not None

        # Verify trip was created with correct ownership
        with app.app_context():
            trip = TripPlan.query.get(d['trip_id'])
            assert trip.creator_id == emp_id

            # Target is owner
            owner_m = TripMember.query.filter_by(
                trip_plan_id=trip.id, user_id=emp_id
            ).first()
            assert owner_m.role == 'owner'

    def test_book_on_behalf_non_member_target(self, client):
        with app.app_context():
            _enable_flags(*ALL_FLAGS)
            owner = _create_user('o@t.com')
            ws, _ = _create_workspace(owner.id)
            slug = ws.slug
            outsider = _create_user('out@t.com')
            _login_client_as(client, owner.id)

        r = client.post(f'/api/workspaces/{slug}/book-on-behalf', json={
            'for_user_id': 9999,
            'trip_name': 'Test',
        })
        assert r.status_code == 404

    def test_book_on_behalf_member_denied(self, client):
        """Regular member cannot book on behalf."""
        with app.app_context():
            _enable_flags(*ALL_FLAGS)
            owner = _create_user('o@t.com')
            ws, _ = _create_workspace(owner.id)
            slug = ws.slug
            emp = _create_user('emp@t.com')
            _add_member(ws, emp.id, role='member')
            target = _create_user('target@t.com')
            _add_member(ws, target.id)
            target_id = target.id
            _login_client_as(client, emp.id)

        r = client.post(f'/api/workspaces/{slug}/book-on-behalf', json={
            'for_user_id': target_id,
            'trip_name': 'Test',
        })
        assert r.status_code == 403

    def test_book_on_behalf_missing_fields(self, client):
        with app.app_context():
            _enable_flags(*ALL_FLAGS)
            owner = _create_user('o@t.com')
            ws, _ = _create_workspace(owner.id)
            slug = ws.slug
            _login_client_as(client, owner.id)
        r = client.post(f'/api/workspaces/{slug}/book-on-behalf', json={})
        assert r.status_code == 400


class TestWorkspaceBookingsAPI:

    def test_list_workspace_bookings(self, client):
        with app.app_context():
            _enable_flags(*ALL_FLAGS)
            owner = _create_user('o@t.com')
            ws, _ = _create_workspace(owner.id)
            slug = ws.slug
            emp = _create_user('emp@t.com', 'Jane')
            _add_member(ws, emp.id, department='Sales')
            # Create a booking for the employee
            b = Booking(user_id=emp.id, status='booked',
                        vendor_payment_amount=450.0)
            db.session.add(b)
            db.session.commit()
            _login_client_as(client, owner.id)

        r = client.get(f'/api/workspaces/{slug}/bookings')
        assert r.status_code == 200
        bookings = r.get_json()['bookings']
        assert len(bookings) >= 1
        assert bookings[0]['department'] == 'Sales'

    def test_member_sees_only_own_bookings(self, client):
        with app.app_context():
            _enable_flags(*ALL_FLAGS)
            owner = _create_user('o@t.com')
            ws, _ = _create_workspace(owner.id)
            slug = ws.slug
            e1 = _create_user('e1@t.com')
            e2 = _create_user('e2@t.com')
            _add_member(ws, e1.id)
            _add_member(ws, e2.id)
            db.session.add(Booking(user_id=e1.id, status='booked'))
            db.session.add(Booking(user_id=e2.id, status='booked'))
            db.session.commit()
            _login_client_as(client, e1.id)

        r = client.get(f'/api/workspaces/{slug}/bookings')
        assert r.status_code == 200
        assert r.get_json()['total'] == 1


class TestExportAPI:

    def test_export_csv(self, client):
        with app.app_context():
            _enable_flags(*ALL_FLAGS)
            owner = _create_user('o@t.com', 'Admin')
            ws, _ = _create_workspace(owner.id)
            slug = ws.slug
            emp = _create_user('emp@t.com', 'Jane')
            _add_member(ws, emp.id, department='Engineering')
            b = Booking(user_id=emp.id, status='completed',
                        confirmation_code='ABC123',
                        vendor_payment_amount=800.0)
            db.session.add(b)
            db.session.commit()
            _login_client_as(client, owner.id)

        r = client.get(f'/api/workspaces/{slug}/export')
        assert r.status_code == 200
        assert r.content_type == 'text/csv; charset=utf-8'
        assert 'attachment' in r.headers.get('Content-Disposition', '')

        # Parse CSV
        csv_text = r.data.decode('utf-8')
        reader = csv.reader(io.StringIO(csv_text))
        rows = list(reader)
        assert rows[0][0] == 'Booking ID'  # header
        assert len(rows) == 2  # header + 1 booking
        assert rows[1][1] == 'Jane'  # Employee name
        assert rows[1][3] == 'Engineering'  # Department
        assert rows[1][5] == 'ABC123'  # Confirmation code

    def test_export_member_denied(self, client):
        """Regular member cannot export."""
        with app.app_context():
            _enable_flags(*ALL_FLAGS)
            owner = _create_user('o@t.com')
            ws, _ = _create_workspace(owner.id)
            slug = ws.slug
            emp = _create_user('emp@t.com')
            _add_member(ws, emp.id, role='member')
            _login_client_as(client, emp.id)

        r = client.get(f'/api/workspaces/{slug}/export')
        assert r.status_code == 403


# ================================================================
# Part 8: Access Control
# ================================================================

class TestAccessControl:

    def test_unauthenticated_create_workspace(self, client):
        with app.app_context():
            _enable_flags(*ALL_FLAGS)
        r = client.post('/api/workspaces', json={'name': 'X'})
        assert r.status_code in (302, 401)

    def test_unauthenticated_list_workspaces(self, client):
        with app.app_context():
            _enable_flags(*ALL_FLAGS)
        r = client.get('/api/workspaces')
        assert r.status_code in (302, 401)

    def test_unauthenticated_dashboard(self, client):
        with app.app_context():
            _enable_flags(*ALL_FLAGS)
        r = client.get('/api/workspaces/test/dashboard')
        assert r.status_code in (302, 401)

    def test_unauthenticated_export(self, client):
        with app.app_context():
            _enable_flags(*ALL_FLAGS)
        r = client.get('/api/workspaces/test/export')
        assert r.status_code in (302, 401)

    def test_workspace_not_found(self, client):
        with app.app_context():
            _enable_flags(*ALL_FLAGS)
            u = _create_user('u@t.com')
            _login_client_as(client, u.id)
        r = client.get('/api/workspaces/nonexistent')
        assert r.status_code == 404
