"""
Build #194 — APAi Admin Portal Tests (repurposed from Dev Portal)

Standalone Dev Portal SCRAPPED. ANASTASiA is APAi-exclusive.
Tests multi-seat team management, ANASTASiA terminal, billing, opsec.

Run: pytest tests/test_build194_apai_admin.py -v
MYSTES KYRIOS LLC — Confidential.
"""

import json
import os
import sys
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server import app, db, limiter
from models import DevPortalAccount, DevPortalKey, DevPortalConversation, DevPortalMessage


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
def admin_account(client):
    """Create an APAi admin (subscriber) account."""
    with app.app_context():
        from models import CommercialAccount, User
        # Create a MYSTES user + commercial account for the subscriber
        user = User(
            email='admin@ota.com',
            name='OTA Admin',
            is_admin=False,
        )
        user.set_password('AdminPass123!')
        db.session.add(user)
        db.session.flush()

        comm = CommercialAccount(
            account_id='comm_test123',
            owner_user_id=user.id,
            name='Test OTA',
            contact_email='admin@ota.com',
            current_tier='apai_pro',
            subscription_status='active',
        )
        db.session.add(comm)
        db.session.flush()

        account = DevPortalAccount(
            account_id="dpa_admin123",
            email="admin@ota.com",
            name="OTA Admin",
            company="Test OTA",
            role='admin',
            commercial_account_id=comm.id,
            mystes_user_id=user.id,
            apai_subscriber=True,
            billing_tier='pro',
            subscription_status='active',
            queries_included=500,
            is_active=True,
            is_verified=True,
        )
        account.set_password("AdminPass123!")
        db.session.add(account)
        db.session.commit()

        # Set session
        with client.session_transaction() as sess:
            sess['dev_portal_account_id'] = account.id

        yield client, account, comm


@pytest.fixture
def member_account(admin_account):
    """Create a team member account under the admin."""
    client, admin, comm = admin_account
    with app.app_context():
        member = DevPortalAccount(
            account_id="dpa_member123",
            email="dev@ota.com",
            name="Team Dev",
            role='member',
            commercial_account_id=comm.id,
            added_by_id=admin.id,
            billing_tier='pro',
            apai_subscriber=True,
            is_active=True,
            is_verified=True,
        )
        member.set_password("MemberPass123!")
        db.session.add(member)
        db.session.commit()
        yield client, admin, member, comm


# ============================================================
# Auth Tests
# ============================================================

class TestApaiAdminAuth:
    """Tests for APAi admin portal authentication."""

    def test_login_page_renders(self, client):
        """GET /apai/admin/login returns 200."""
        resp = client.get('/apai/admin/login')
        assert resp.status_code == 200
        html = resp.data.decode()
        assert 'APAi Admin Portal' in html
        assert 'Log In' in html

    def test_login_valid_credentials(self, admin_account):
        """Valid login sets session and redirects to dashboard."""
        client, account, _ = admin_account
        # Clear session first
        with client.session_transaction() as sess:
            sess.pop('dev_portal_account_id', None)

        resp = client.post('/apai/admin/login', data={
            'email': 'admin@ota.com',
            'password': 'AdminPass123!',
        }, follow_redirects=False)

        assert resp.status_code in (302, 303)
        assert '/apai/admin' in resp.headers.get('Location', '')

    def test_login_invalid_password(self, admin_account):
        """Wrong password stays on login page."""
        client, _, _ = admin_account
        with client.session_transaction() as sess:
            sess.pop('dev_portal_account_id', None)

        resp = client.post('/apai/admin/login', data={
            'email': 'admin@ota.com',
            'password': 'WrongPassword!',
        }, follow_redirects=False)

        assert resp.status_code in (302, 303)
        assert '/apai/admin/login' in resp.headers.get('Location', '')

    def test_logout_clears_session(self, admin_account):
        """Logout redirects to login."""
        client, _, _ = admin_account
        resp = client.get('/apai/admin/logout', follow_redirects=False)
        assert resp.status_code in (302, 303)
        assert '/apai/admin/login' in resp.headers.get('Location', '')

    def test_dashboard_requires_auth(self, client):
        """Dashboard redirects unauthenticated users."""
        resp = client.get('/apai/admin', follow_redirects=False)
        assert resp.status_code in (302, 308)
        assert '/apai/admin/login' in resp.headers.get('Location', '')

    def test_terminal_requires_auth(self, client):
        """Terminal redirects unauthenticated users."""
        resp = client.get('/apai/admin/terminal', follow_redirects=False)
        assert resp.status_code in (302, 308)
        assert '/apai/admin/login' in resp.headers.get('Location', '')


# ============================================================
# Dashboard Tests
# ============================================================

class TestApaiAdminDashboard:
    """Tests for APAi admin dashboard."""

    def test_dashboard_renders(self, admin_account):
        """Dashboard renders for authenticated admin."""
        client, _, _ = admin_account
        resp = client.get('/apai/admin')
        assert resp.status_code == 200
        html = resp.data.decode()
        assert 'APAi Admin' in html
        assert 'PRO' in html

    def test_dashboard_shows_usage(self, admin_account):
        """Dashboard shows usage stats."""
        client, _, _ = admin_account
        resp = client.get('/apai/admin')
        assert resp.status_code == 200
        html = resp.data.decode()
        assert 'Queries Used' in html

    def test_dashboard_shows_team_for_admin(self, admin_account):
        """Admin sees team management section."""
        client, _, _ = admin_account
        resp = client.get('/apai/admin')
        assert resp.status_code == 200
        html = resp.data.decode()
        assert 'Team Members' in html


# ============================================================
# Terminal Tests
# ============================================================

class TestApaiAdminTerminal:
    """Tests for ANASTASiA terminal."""

    def test_terminal_renders(self, admin_account):
        """Terminal renders for authenticated user."""
        client, _, _ = admin_account
        resp = client.get('/apai/admin/terminal')
        assert resp.status_code == 200
        html = resp.data.decode()
        assert 'ANASTASiA' in html
        assert 'Terminal' in html

    def test_terminal_has_chat_input(self, admin_account):
        """Terminal has chat input and send button."""
        client, _, _ = admin_account
        resp = client.get('/apai/admin/terminal')
        html = resp.data.decode()
        assert 'devInput' in html
        assert 'devSendBtn' in html


# ============================================================
# Team Management Tests
# ============================================================

class TestApaiAdminTeam:
    """Tests for multi-seat team management."""

    def test_add_team_member(self, admin_account):
        """Admin can add a team member."""
        client, admin, comm = admin_account
        resp = client.post('/api/apai/admin/team',
            data=json.dumps({
                "email": "newdev@ota.com",
                "name": "New Developer",
                "password": "NewDevPass123!",
            }),
            content_type='application/json')

        assert resp.status_code == 200
        data = resp.get_json()
        assert data['added'] is True
        assert data['member']['email'] == 'newdev@ota.com'
        assert data['member']['role'] == 'member'

    def test_add_member_duplicate_email_rejected(self, member_account):
        """Duplicate email is rejected."""
        client, _, member, _ = member_account
        resp = client.post('/api/apai/admin/team',
            data=json.dumps({
                "email": "dev@ota.com",  # already exists
                "password": "AnotherPass123!",
            }),
            content_type='application/json')

        assert resp.status_code == 409
        data = resp.get_json()
        assert 'already exists' in data['error']

    def test_add_member_no_password_needed(self, admin_account):
        """Server auto-generates temp password — no client-side password needed (Build #195)."""
        client, _, _ = admin_account
        resp = client.post('/api/apai/admin/team',
            data=json.dumps({
                "email": "nopass@ota.com",
            }),
            content_type='application/json')

        assert resp.status_code == 200
        data = resp.get_json()
        assert data.get('added') is True
        assert data.get('invitation_sent') is True

    def test_remove_team_member(self, member_account):
        """Admin can remove a team member."""
        client, _, member, _ = member_account
        resp = client.delete(f'/api/apai/admin/team/{member.account_id}')

        assert resp.status_code == 200
        data = resp.get_json()
        assert data['removed'] is True

    def test_cannot_remove_admin(self, admin_account):
        """Admin cannot remove themselves."""
        client, admin, _ = admin_account
        resp = client.delete(f'/api/apai/admin/team/{admin.account_id}')

        assert resp.status_code == 400
        data = resp.get_json()
        assert 'Cannot remove' in data['error']

    def test_update_member_query_limit(self, member_account):
        """Admin can set per-member query limit."""
        client, _, member, _ = member_account
        resp = client.put(f'/api/apai/admin/team/{member.account_id}',
            data=json.dumps({"query_limit": 100}),
            content_type='application/json')

        assert resp.status_code == 200
        data = resp.get_json()
        assert data['updated'] is True
        assert data['member']['query_limit'] == 100

    def test_member_cannot_add_team(self, member_account):
        """Non-admin cannot add team members."""
        client, _, member, _ = member_account
        # Switch session to member
        with client.session_transaction() as sess:
            sess['dev_portal_account_id'] = member.id

        resp = client.post('/api/apai/admin/team',
            data=json.dumps({
                "email": "hack@ota.com",
                "password": "HackPass123!",
            }),
            content_type='application/json')

        assert resp.status_code == 403


# ============================================================
# Chat Tests
# ============================================================

class TestApaiAdminChat:
    """Tests for the admin portal chat endpoint."""

    @patch('dev_portal_ai.DevPortalAI._call_anthropic')
    def test_chat_creates_conversation(self, mock_anthropic, admin_account):
        """Chat creates a new conversation."""
        mock_anthropic.return_value = {
            "content": [{"type": "text", "text": "Hello! How can I help?"}],
            "usage": {"input_tokens": 50, "output_tokens": 25},
            "model": "claude-opus-4-6",
        }

        client, _, _ = admin_account
        resp = client.post('/api/apai/admin/chat',
            data=json.dumps({"message": "Hello ANASTASiA"}),
            content_type='application/json')

        assert resp.status_code == 200
        data = resp.get_json()
        assert 'conversation_id' in data
        assert data['conversation_id'].startswith('dpc_')
        assert data['response']['content'] == "Hello! How can I help?"

    def test_chat_empty_message_rejected(self, admin_account):
        """Empty message returns 400."""
        client, _, _ = admin_account
        resp = client.post('/api/apai/admin/chat',
            data=json.dumps({"message": ""}),
            content_type='application/json')

        assert resp.status_code == 400

    def test_chat_requires_auth(self, client):
        """Chat endpoint requires auth."""
        resp = client.post('/api/apai/admin/chat',
            data=json.dumps({"message": "Hello"}),
            content_type='application/json')

        assert resp.status_code == 401


# ============================================================
# Conversations API Tests
# ============================================================

class TestApaiAdminConversations:
    """Tests for conversation management."""

    def test_list_conversations_empty(self, admin_account):
        """Empty conversation list initially."""
        client, _, _ = admin_account
        resp = client.get('/api/apai/admin/conversations')
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data['conversations']) == 0

    @patch('dev_portal_ai.DevPortalAI._call_anthropic')
    def test_conversations_appear_after_chat(self, mock_anthropic, admin_account):
        """Conversations appear after chat."""
        mock_anthropic.return_value = {
            "content": [{"type": "text", "text": "Hi"}],
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }

        client, _, _ = admin_account
        client.post('/api/apai/admin/chat',
            data=json.dumps({"message": "Hello"}),
            content_type='application/json')

        resp = client.get('/api/apai/admin/conversations')
        data = resp.get_json()
        assert len(data['conversations']) == 1

    @patch('dev_portal_ai.DevPortalAI._call_anthropic')
    def test_delete_conversation(self, mock_anthropic, admin_account):
        """Soft-delete a conversation."""
        mock_anthropic.return_value = {
            "content": [{"type": "text", "text": "Done"}],
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }

        client, _, _ = admin_account
        resp = client.post('/api/apai/admin/chat',
            data=json.dumps({"message": "Create this"}),
            content_type='application/json')
        conv_id = resp.get_json()['conversation_id']

        resp = client.delete(f'/api/apai/admin/conversations/{conv_id}')
        assert resp.status_code == 200

        resp = client.get('/api/apai/admin/conversations')
        assert len(resp.get_json()['conversations']) == 0


# ============================================================
# Usage API Tests
# ============================================================

class TestApaiAdminUsage:
    """Tests for usage stats."""

    def test_usage_endpoint(self, admin_account):
        """Usage API returns billing stats."""
        client, _, _ = admin_account
        resp = client.get('/api/apai/admin/usage')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['tier'] == 'pro'
        assert 'queries_used' in data
        assert 'queries_included' in data

    def test_account_info(self, admin_account):
        """Account info returns role and tier."""
        client, _, _ = admin_account
        resp = client.get('/api/apai/admin/account')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['role'] == 'admin'
        assert data['billing_tier'] == 'pro'


# ============================================================
# API Keys Tests
# ============================================================

class TestApaiAdminApiKeys:
    """Tests for API key management."""

    def test_api_keys_page(self, admin_account):
        """API keys page renders."""
        client, _, _ = admin_account
        resp = client.get('/apai/admin/api-keys')
        assert resp.status_code == 200
        assert b'API Keys' in resp.data

    def test_generate_api_key(self, admin_account):
        """Generate API key redirects with flash."""
        client, _, _ = admin_account
        resp = client.post('/apai/admin/api-keys', data={
            'label': 'Test Key',
        }, follow_redirects=False)
        assert resp.status_code == 302

    def test_revoke_api_key(self, admin_account):
        """Revoke API key returns success."""
        client, account, _ = admin_account
        # Create a key first
        import bcrypt as bcrypt_mod
        with app.app_context():
            raw = "dpt_testapikey12345678"
            kh = bcrypt_mod.hashpw(raw.encode(), bcrypt_mod.gensalt()).decode()
            key = DevPortalKey(
                account_id=account.id,
                key_prefix=raw[:8],
                key_hash=kh,
                label="Revoke Test",
            )
            db.session.add(key)
            db.session.commit()
            key_id = key.id

        resp = client.delete(f'/api/apai/admin/api-keys/{key_id}')
        assert resp.status_code == 200
        assert resp.get_json()['revoked'] is True


# ============================================================
# Billing Tests
# ============================================================

class TestApaiAdminBilling:
    """Tests for APAi tier configuration."""

    def test_pro_tier_config(self):
        """Pro tier: $299, 500 queries, $0.12 overage."""
        from dev_portal_billing import get_tier_config
        cfg = get_tier_config('pro')
        assert cfg['price_usd'] == 299
        assert cfg['queries_included'] == 500
        assert cfg['overage_rate'] == 0.12

    def test_enterprise_tier_config(self):
        """Enterprise tier: $599, 2000 queries, $0.08 overage."""
        from dev_portal_billing import get_tier_config
        cfg = get_tier_config('enterprise')
        assert cfg['price_usd'] == 599
        assert cfg['queries_included'] == 2000
        assert cfg['overage_rate'] == 0.08

    def test_scale_tier_config(self):
        """Scale tier: $999, 5000 queries, $0.05 overage."""
        from dev_portal_billing import get_tier_config
        cfg = get_tier_config('scale')
        assert cfg['price_usd'] == 999
        assert cfg['queries_included'] == 5000
        assert cfg['overage_rate'] == 0.05

    def test_usage_stats_cost_calculation(self, admin_account):
        """Cost = subscription + overage."""
        from dev_portal_billing import get_usage_stats
        _, account, _ = admin_account
        with app.app_context():
            acct = DevPortalAccount.query.get(account.id)
            acct.queries_used_this_period = 550
            acct.queries_included = 500
            db.session.commit()

            stats = get_usage_stats(acct)
            assert stats['tier'] == 'pro'
            assert stats['overage_queries'] == 50
            # $299 + 50 * $0.12 = $305
            assert stats['estimated_cost_usd'] == 305.0

    def test_quota_check_active(self, admin_account):
        """Active subscription allows queries."""
        from dev_portal_billing import check_quota
        _, account, _ = admin_account
        with app.app_context():
            acct = DevPortalAccount.query.get(account.id)
            result = check_quota(acct)
            assert result['allowed'] is True

    def test_quota_check_member_limit(self, member_account):
        """Member with exceeded query limit is blocked."""
        from dev_portal_billing import check_quota
        _, _, member, _ = member_account
        with app.app_context():
            m = DevPortalAccount.query.get(member.id)
            m.query_limit = 10
            m.queries_used_this_period = 10
            db.session.commit()

            result = check_quota(m)
            assert result['allowed'] is False
            assert result['error'] == 'member_limit_reached'

    def test_record_usage_increments(self, admin_account):
        """Usage recording increments counters."""
        from dev_portal_billing import record_query_usage
        _, account, _ = admin_account
        with app.app_context():
            acct = DevPortalAccount.query.get(account.id)
            assert acct.queries_used_this_period == 0
            record_query_usage(acct)
            assert acct.queries_used_this_period == 1
            assert acct.total_queries_lifetime == 1


# ============================================================
# Opsec Tests
# ============================================================

class TestApaiAdminOpsec:
    """Tests for AI opsec hardening."""

    def test_system_prompt_deny_list(self):
        """System prompt has opsec deny list."""
        from dev_portal_ai import ANASTASIA_DEVPORTAL_SYSTEM_PROMPT
        prompt = ANASTASIA_DEVPORTAL_SYSTEM_PROMPT.lower()
        assert "never disclose" in prompt
        assert "fee structures" in prompt
        assert "credential network" in prompt
        assert "knowledge card" in prompt

    def test_system_prompt_no_claude_exposure(self):
        """System prompt instructs ANASTASiA to never mention Claude."""
        from dev_portal_ai import ANASTASIA_DEVPORTAL_SYSTEM_PROMPT
        assert "NEVER mention Claude" in ANASTASIA_DEVPORTAL_SYSTEM_PROMPT
        assert "You are ANASTASiA" in ANASTASIA_DEVPORTAL_SYSTEM_PROMPT

    def test_engine_branding(self):
        """AI engine class exists and uses correct model."""
        from dev_portal_ai import DevPortalAI
        engine = DevPortalAI()
        assert engine.model == "claude-opus-4-6"


# ============================================================
# Legacy Redirect Tests
# ============================================================

class TestLegacyRedirects:
    """Old /dev/* URLs redirect to new /apai/admin/*."""

    def test_dev_redirects_to_admin_login(self, client):
        """GET /dev redirects to /apai/admin/login."""
        resp = client.get('/dev')
        assert resp.status_code == 301
        assert '/apai/admin/login' in resp.headers.get('Location', '')

    def test_dev_login_redirects(self, client):
        """GET /dev/login redirects."""
        resp = client.get('/dev/login')
        assert resp.status_code == 301

    def test_dev_signup_redirects(self, client):
        """GET /dev/signup redirects (standalone signup scrapped)."""
        resp = client.get('/dev/signup')
        assert resp.status_code == 301

    def test_dev_terminal_redirects(self, client):
        """GET /dev/terminal redirects to admin terminal."""
        resp = client.get('/dev/terminal')
        assert resp.status_code == 301
        assert '/apai/admin/terminal' in resp.headers.get('Location', '')


# ============================================================
# Model Tests
# ============================================================

class TestDevPortalModels:
    """Tests for updated DevPortalAccount model."""

    def test_account_has_role_field(self, client):
        """DevPortalAccount has role field."""
        with app.app_context():
            account = DevPortalAccount(
                account_id="dpa_roletest",
                email="role@test.com",
                role='admin',
                is_active=True,
            )
            db.session.add(account)
            db.session.commit()

            loaded = DevPortalAccount.query.filter_by(email="role@test.com").first()
            assert loaded.role == 'admin'

    def test_account_has_commercial_account_id(self, client):
        """DevPortalAccount can link to CommercialAccount."""
        with app.app_context():
            account = DevPortalAccount(
                account_id="dpa_commtest",
                email="comm@test.com",
                commercial_account_id=None,
                is_active=True,
            )
            db.session.add(account)
            db.session.commit()
            assert account.commercial_account_id is None

    def test_account_has_query_limit(self, client):
        """DevPortalAccount has optional query_limit."""
        with app.app_context():
            account = DevPortalAccount(
                account_id="dpa_limittest",
                email="limit@test.com",
                query_limit=100,
                is_active=True,
            )
            db.session.add(account)
            db.session.commit()

            loaded = DevPortalAccount.query.filter_by(email="limit@test.com").first()
            assert loaded.query_limit == 100

    def test_to_dict_includes_new_fields(self, client):
        """to_dict() includes role and query_limit."""
        with app.app_context():
            account = DevPortalAccount(
                account_id="dpa_dicttest",
                email="dict@test.com",
                role='member',
                query_limit=50,
                is_active=True,
            )
            db.session.add(account)
            db.session.commit()

            d = account.to_dict()
            assert d['role'] == 'member'
            assert d['query_limit'] == 50

    def test_password_hashing(self, client):
        """Password hashing works."""
        with app.app_context():
            account = DevPortalAccount(
                account_id="dpa_pwdtest",
                email="pwd@test.com",
            )
            account.set_password("SecurePass123!")
            db.session.add(account)
            db.session.commit()

            loaded = DevPortalAccount.query.filter_by(email="pwd@test.com").first()
            assert loaded.check_password("SecurePass123!") is True
            assert loaded.check_password("Wrong") is False
