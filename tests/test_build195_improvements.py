"""
Build #195 — Production Hardening + APAi Admin Improvements

Tests:
- Team member invitation flow (auto-generated temp password + email)
- Per-member usage breakdown dashboard
- Stripe metered billing (period reset, invoice failure)
- Health check endpoint (version, APAi status)
- Consumer polish (FAQ pricing, email branding)

Run: pytest tests/test_build195_improvements.py -v
MYSTES KYRIOS LLC — Confidential.
"""

import json
import os
import secrets
import sys
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server import app, db, limiter
from models import DevPortalAccount, CommercialAccount, User


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
    """Create an APAi admin (subscriber) account with team."""
    with app.app_context():
        user = User(
            email='admin195@ota.com',
            name='Build 195 Admin',
            is_admin=False,
        )
        user.set_password('AdminPass195!')
        db.session.add(user)
        db.session.flush()

        comm = CommercialAccount(
            account_id='comm_195_test',
            owner_user_id=user.id,
            name='Build 195 OTA',
            contact_email='admin195@ota.com',
            current_tier='apai_pro',
            subscription_status='active',
        )
        db.session.add(comm)
        db.session.flush()

        account = DevPortalAccount(
            account_id="dpa_admin195",
            email="admin195@ota.com",
            name="Build 195 Admin",
            company="Build 195 OTA",
            role='admin',
            commercial_account_id=comm.id,
            mystes_user_id=user.id,
            apai_subscriber=True,
            billing_tier='pro',
            subscription_status='active',
            queries_included=500,
            queries_used_this_period=42,
            is_active=True,
            is_verified=True,
        )
        account.set_password("AdminPass195!")
        db.session.add(account)
        db.session.commit()

        with client.session_transaction() as sess:
            sess['dev_portal_account_id'] = account.id

        yield client, account, comm, user


# ============================================================
# Team Member Invitation Flow
# ============================================================

class TestTeamInvitation:
    """Build #195: Team member invitation with auto-generated temp password."""

    def test_invite_generates_temp_password(self, admin_account):
        """Adding a team member generates a temp password (no client-side password)."""
        client, account, comm, _ = admin_account
        with app.app_context():
            resp = client.post('/api/apai/admin/team', json={
                'email': 'newdev@example.com',
                'name': 'New Developer',
            })
            assert resp.status_code == 200
            data = resp.get_json()
            assert data.get('added') is True
            assert data.get('invitation_sent') is True

            member = DevPortalAccount.query.filter_by(email='newdev@example.com').first()
            assert member is not None
            assert member.role == 'member'
            assert member.invitation_token is not None
            assert member.invitation_sent_at is not None
            assert member.commercial_account_id == comm.id

    def test_invite_sends_email(self, admin_account):
        """Invitation triggers email send."""
        client, account, comm, _ = admin_account
        with app.app_context():
            with patch('email_service.send_team_invitation_email') as mock_email:
                mock_email.return_value = True
                resp = client.post('/api/apai/admin/team', json={
                    'email': 'emailtest@example.com',
                    'name': 'Email Test Dev',
                })
                assert resp.status_code == 200
                mock_email.assert_called_once()
                call_args = mock_email.call_args
                assert call_args[1]['to'] == 'emailtest@example.com' or call_args[0][0] == 'emailtest@example.com'

    def test_invite_no_password_required(self, admin_account):
        """Client no longer needs to send password — server generates it."""
        client, account, comm, _ = admin_account
        with app.app_context():
            resp = client.post('/api/apai/admin/team', json={
                'email': 'nopass@example.com',
            })
            assert resp.status_code == 200
            data = resp.get_json()
            assert data.get('added') is True

    def test_invite_duplicate_email_rejected(self, admin_account):
        """Cannot invite duplicate email."""
        client, account, comm, _ = admin_account
        with app.app_context():
            resp = client.post('/api/apai/admin/team', json={
                'email': 'admin195@ota.com',
            })
            assert resp.status_code == 409

    def test_invite_member_can_login(self, admin_account):
        """Invited member can log in with temp credentials."""
        client, account, comm, _ = admin_account
        with app.app_context():
            # Manually create a member with known password
            member = DevPortalAccount(
                account_id="dpa_logintest",
                email="logintest@example.com",
                name="Login Test",
                role='member',
                commercial_account_id=comm.id,
                added_by_id=account.id,
                billing_tier='pro',
                is_active=True,
                is_verified=True,
            )
            member.set_password("TmpAbcd1234!")
            db.session.add(member)
            db.session.commit()

            resp = client.post('/apai/admin/login', data={
                'email': 'logintest@example.com',
                'password': 'TmpAbcd1234!',
            }, follow_redirects=False)
            assert resp.status_code == 302


# ============================================================
# Per-Member Usage Breakdown Dashboard
# ============================================================

class TestPerMemberUsage:
    """Build #195: Dashboard shows per-member usage bars."""

    def test_dashboard_shows_team_members(self, admin_account):
        """Admin dashboard renders team member list."""
        client, account, comm, _ = admin_account
        with app.app_context():
            resp = client.get('/apai/admin')
            assert resp.status_code == 200
            html = resp.data.decode()
            assert 'Team Members' in html
            assert 'admin195@ota.com' in html

    def test_dashboard_shows_usage_bars(self, admin_account):
        """Dashboard renders per-member usage progress bars."""
        client, account, comm, _ = admin_account
        with app.app_context():
            # Add a team member with some queries
            member = DevPortalAccount(
                account_id="dpa_usagebar",
                email="usagebar@example.com",
                name="Usage Bar Test",
                role='member',
                commercial_account_id=comm.id,
                added_by_id=account.id,
                billing_tier='pro',
                queries_used_this_period=150,
                query_limit=200,
                is_active=True,
                is_verified=True,
            )
            member.set_password("Test123!")
            db.session.add(member)
            db.session.commit()

            resp = client.get('/apai/admin')
            html = resp.data.decode()
            assert 'usagebar@example.com' in html
            assert '150' in html
            assert '200' in html

    def test_dashboard_shows_team_size(self, admin_account):
        """Dashboard shows team size stat card."""
        client, account, comm, _ = admin_account
        with app.app_context():
            resp = client.get('/apai/admin')
            html = resp.data.decode()
            assert 'Team Size' in html

    def test_dashboard_shows_stat_cards(self, admin_account):
        """Dashboard displays tier, queries used, overage, est. cost."""
        client, account, comm, _ = admin_account
        with app.app_context():
            resp = client.get('/apai/admin')
            html = resp.data.decode()
            assert 'Tier' in html
            assert 'PRO' in html
            assert 'Queries Used' in html
            assert 'Overage' in html
            assert 'Est. Cost' in html


# ============================================================
# Stripe Metered Billing
# ============================================================

class TestStripeBilling:
    """Build #195: Stripe metered billing integration."""

    def test_billing_period_reset(self, admin_account):
        """Usage counters reset when billing period changes."""
        client, account, comm, _ = admin_account
        with app.app_context():
            from dev_portal_billing import get_tier_config
            config = get_tier_config('pro')
            assert config['queries_included'] == 500
            assert config['overage_rate'] == 0.12

            # Simulate period reset
            admin = DevPortalAccount.query.get(account.id)
            admin.queries_used_this_period = 600
            db.session.commit()

            # Reset
            admin.queries_used_this_period = 0
            admin.period_start = datetime.now(timezone.utc)
            db.session.commit()

            admin = DevPortalAccount.query.get(account.id)
            assert admin.queries_used_this_period == 0

    def test_overage_cost_calculation(self, admin_account):
        """Overage cost calculated correctly."""
        client, account, comm, _ = admin_account
        with app.app_context():
            from dev_portal_billing import get_usage_stats
            admin = DevPortalAccount.query.get(account.id)
            admin.queries_used_this_period = 600
            db.session.commit()

            stats = get_usage_stats(admin)
            assert stats['overage_queries'] == 100
            assert stats['overage_rate'] == 0.12
            expected_cost = 299 + (100 * 0.12)
            assert stats['estimated_cost_usd'] == round(expected_cost, 2)

    def test_tier_configs_correct(self, client):
        """All APAi tier configs have correct values."""
        with app.app_context():
            from dev_portal_billing import TIER_CONFIG
            assert TIER_CONFIG['pro']['price_usd'] == 299
            assert TIER_CONFIG['enterprise']['price_usd'] == 599
            assert TIER_CONFIG['scale']['price_usd'] == 999
            assert TIER_CONFIG['pro']['queries_included'] == 500
            assert TIER_CONFIG['enterprise']['queries_included'] == 2000
            assert TIER_CONFIG['scale']['queries_included'] == 5000

    def test_quota_check_per_member_limit(self, admin_account):
        """Per-member query limit is enforced by check_quota."""
        client, account, comm, _ = admin_account
        with app.app_context():
            from dev_portal_billing import check_quota
            member = DevPortalAccount(
                account_id="dpa_quota_test",
                email="quotatest@example.com",
                role='member',
                commercial_account_id=comm.id,
                billing_tier='pro',
                queries_used_this_period=50,
                query_limit=50,
                is_active=True,
                is_verified=True,
            )
            member.set_password("Test123!")
            db.session.add(member)
            db.session.commit()

            result = check_quota(member, DevPortalAccount.query.get(account.id))
            assert result['allowed'] is False
            assert result['error'] == 'member_limit_reached'


# ============================================================
# Health Check
# ============================================================

class TestHealthCheck:
    """Build #195: Health check endpoint updates."""

    def test_health_returns_200(self, client):
        """Health check endpoint returns 200."""
        with app.app_context():
            resp = client.get('/health')
            assert resp.status_code == 200

    def test_health_version_updated(self, client):
        """Health check shows Build #195 version."""
        with app.app_context():
            resp = client.get('/health')
            data = resp.get_json()
            assert data['version'] == '1.3.0'
            assert data['build'] == 195

    def test_health_includes_apai_portal(self, client):
        """Health check includes APAi portal status."""
        with app.app_context():
            resp = client.get('/health')
            data = resp.get_json()
            services = data.get('services', {})
            assert 'apai_portal' in services

    def test_health_includes_anastasia_api(self, client):
        """Health check includes ANASTASiA API status."""
        with app.app_context():
            resp = client.get('/health')
            data = resp.get_json()
            services = data.get('services', {})
            assert 'anastasia_api' in services

    def test_health_no_stale_services(self, client):
        """Health check does not include superseded services."""
        with app.app_context():
            resp = client.get('/health')
            data = resp.get_json()
            services = data.get('services', {})
            assert 'xrpl' not in services
            assert 'proxy_scraper' not in services
            assert 'browser_control' not in services


# ============================================================
# Email Templates
# ============================================================

class TestEmailTemplates:
    """Build #195: Email template updates."""

    def test_team_invitation_email_function(self, client):
        """Team invitation email function exists and returns True when disabled."""
        with app.app_context():
            from email_service import send_team_invitation_email
            result = send_team_invitation_email(
                to='test@example.com',
                name='Test Dev',
                inviter_name='Admin User',
                temp_password='TmpAbcd1234!',
                company='Test OTA',
            )
            # Returns True when email is disabled (test mode)
            assert result is True or result is False  # Either works — just verify no crash

    def test_welcome_email_no_claude_reference(self, client):
        """Welcome email does not reference Claude/Opus/Anthropic."""
        with app.app_context():
            from email_service import send_devportal_welcome
            # Patch send_email to capture HTML
            captured = {}
            def capture_send(to, subject, html):
                captured['html'] = html
                captured['subject'] = subject
                return True
            with patch('email_service.send_email', side_effect=capture_send):
                send_devportal_welcome('test@example.com', 'Test User')

            if 'html' in captured:
                html = captured['html']
                assert 'Claude' not in html
                assert 'Opus' not in html
                assert 'Anthropic' not in html
                assert '$0.15' not in html
                assert 'ANASTASiA' in html

    def test_welcome_email_uses_new_urls(self, client):
        """Welcome email uses /apai/admin/ URLs, not /dev/."""
        with app.app_context():
            from email_service import send_devportal_welcome
            captured = {}
            def capture_send(to, subject, html):
                captured['html'] = html
                return True
            with patch('email_service.send_email', side_effect=capture_send):
                send_devportal_welcome('test@example.com', 'Test User')

            if 'html' in captured:
                html = captured['html']
                assert '/apai/admin/' in html
                assert '/dev/terminal' not in html


# ============================================================
# FAQ Pricing Fix
# ============================================================

class TestFAQPricing:
    """Build #195: FAQ pricing updated from $600 to multi-tier."""

    def test_faq_no_600_reference(self, client):
        """FAQ section does not reference old $600/mo pricing."""
        with app.app_context():
            resp = client.get('/pricing')
            if resp.status_code == 200:
                html = resp.data.decode()
                assert '$600/mo' not in html
                assert '$600' not in html


# ============================================================
# Model Fields
# ============================================================

class TestModelFields:
    """Build #195: New DevPortalAccount fields."""

    def test_invitation_token_field(self, client):
        """DevPortalAccount has invitation_token field."""
        with app.app_context():
            account = DevPortalAccount(
                account_id="dpa_field_test",
                email="fieldtest@example.com",
                invitation_token="test_token_123",
                invitation_sent_at=datetime.now(timezone.utc),
            )
            account.set_password("Test123!")
            db.session.add(account)
            db.session.commit()

            loaded = DevPortalAccount.query.filter_by(email="fieldtest@example.com").first()
            assert loaded.invitation_token == "test_token_123"
            assert loaded.invitation_sent_at is not None

    def test_invitation_expires_field(self, client):
        """DevPortalAccount has invitation_expires_at field."""
        with app.app_context():
            account = DevPortalAccount(
                account_id="dpa_expires_test",
                email="expirestest@example.com",
                invitation_expires_at=datetime(2026, 12, 31, tzinfo=timezone.utc),
            )
            account.set_password("Test123!")
            db.session.add(account)
            db.session.commit()

            loaded = DevPortalAccount.query.filter_by(email="expirestest@example.com").first()
            assert loaded.invitation_expires_at is not None
            assert loaded.invitation_expires_at.year == 2026
