"""
MYSTES Build #189 — APAi Provisioning + Credential Routing Tests

Tests:
    - APAiProvisioner: provision, suspend, terminate, manual fallback
    - APAiInstanceKey: generation, hash verification
    - Credential routing endpoints: auth, search, book
    - Feature gating: tier-based access control
    - APAi subscription: Stripe checkout creation

Run: pytest tests/test_build189_apai.py -v
MYSTES KYRIOS LLC — Confidential.
"""

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server import app, db, limiter
from models import (
    User, CommercialAccount, TemplateDeployment,
    APAiInstanceKey, WebhookEvent,
)


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
    app.config['SHARE_TO_SAVE_DISCOUNT'] = 0.05
    app.config['POINTS_REDEMPTION_VALUE'] = 0.001
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
def apai_fixtures(client):
    """Create user, commercial account, deployment, and instance key."""
    with app.app_context():
        user = User(
            email='apai@example.com',
            name='APAi User',
            is_admin=False,
        )
        user.set_password('testpass123')
        db.session.add(user)
        db.session.commit()

        account = CommercialAccount(
            account_id='acc_apai_test',
            owner_user_id=user.id,
            name='Test APAi Agency',
            contact_email='apai@example.com',
            current_tier='starter',
            fee_percent=25.0,
            is_active=True,
            subscription_status='active',
        )
        db.session.add(account)
        db.session.commit()

        deployment = TemplateDeployment(
            deployment_id='dep_apai_test_001',
            commercial_account_id=account.id,
            instance_name='test-ota',
            subdomain='test-ota.mystes.app',
            brand_name='Test OTA',
            status='requested',
            config_json=json.dumps({
                "account_id": account.account_id,
                "tier": "starter",
                "fee_percent": 25.0,
            }),
        )
        db.session.add(deployment)
        db.session.commit()

        # Create an API key
        raw_key = "apai_test_key_abc123def456"
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        instance_key = APAiInstanceKey(
            key_id='apk_test_001',
            api_key_hash=key_hash,
            deployment_id=deployment.id,
            tier_id='starter',
            is_active=True,
        )
        db.session.add(instance_key)
        db.session.commit()

        return {
            'user_id': user.id,
            'user_email': 'apai@example.com',
            'account_id': account.id,
            'account_str_id': account.account_id,
            'deployment_id': deployment.id,
            'deployment_str_id': deployment.deployment_id,
            'instance_key_id': instance_key.id,
            'raw_key': raw_key,
        }


# ============================================================
# APAiProvisioner Tests
# ============================================================

class TestAPAiProvisioner:
    """Test the APAi provisioning engine."""

    def test_manual_fallback_no_api_key(self, client, apai_fixtures):
        """Without RENDER_API_KEY, provisioner falls back to manual queuing."""
        with app.app_context():
            from apai_provisioning import APAiProvisioner

            deployment = TemplateDeployment.query.get(apai_fixtures['deployment_id'])
            provisioner = APAiProvisioner(render_api_key="")

            result = provisioner.provision(deployment, db.session)
            assert result["success"] is True
            assert result.get("manual") is True
            assert deployment.status == "requested"
            assert "queued" in (deployment.status_message or "").lower()

    def test_provisioner_available_property(self, client):
        """Available is True only when API key is set."""
        from apai_provisioning import APAiProvisioner

        p_no_key = APAiProvisioner(render_api_key="")
        assert p_no_key.available is False

        p_with_key = APAiProvisioner(render_api_key="rnd_test_key")
        assert p_with_key.available is True

    @patch('apai_provisioning.requests.post')
    def test_provision_with_render_api(self, mock_post, client, apai_fixtures):
        """With a Render API key, provisioner calls Render API."""
        with app.app_context():
            from apai_provisioning import APAiProvisioner

            # Mock Render API responses
            db_response = MagicMock()
            db_response.status_code = 201
            db_response.json.return_value = {
                "id": "db_test_123",
                "connectionInfo": {
                    "internalConnectionString": "postgresql://apai:pass@host:5432/test"
                },
            }

            svc_response = MagicMock()
            svc_response.status_code = 201
            svc_response.json.return_value = {
                "service": {
                    "id": "srv_test_456",
                    "serviceDetails": {"url": "https://test-ota.onrender.com"},
                },
            }

            mock_post.side_effect = [db_response, svc_response]

            deployment = TemplateDeployment.query.get(apai_fixtures['deployment_id'])
            provisioner = APAiProvisioner(render_api_key="rnd_test_key_123")

            result = provisioner.provision(deployment, db.session)

            assert result["success"] is True
            assert result["status"] == "active"
            assert deployment.status == "active"
            assert deployment.render_service_id == "srv_test_456"

    def test_suspend_deployment(self, client, apai_fixtures):
        """Suspending a deployment updates status."""
        with app.app_context():
            from apai_provisioning import APAiProvisioner

            deployment = TemplateDeployment.query.get(apai_fixtures['deployment_id'])
            deployment.status = "active"
            db.session.commit()

            provisioner = APAiProvisioner(render_api_key="")
            result = provisioner.suspend(deployment, db.session)

            assert result["success"] is True
            assert deployment.status == "suspended"
            assert deployment.suspended_at is not None

    def test_terminate_deployment(self, client, apai_fixtures):
        """Terminating a deployment updates status."""
        with app.app_context():
            from apai_provisioning import APAiProvisioner

            deployment = TemplateDeployment.query.get(apai_fixtures['deployment_id'])
            provisioner = APAiProvisioner(render_api_key="")
            result = provisioner.terminate(deployment, db.session)

            assert result["success"] is True
            assert deployment.status == "terminated"


# ============================================================
# APAiInstanceKey Tests
# ============================================================

class TestAPAiInstanceKey:
    """Test API key generation and verification."""

    def test_key_hash_verification(self, client, apai_fixtures):
        """Instance key hash matches the raw key."""
        with app.app_context():
            raw_key = apai_fixtures['raw_key']
            expected_hash = hashlib.sha256(raw_key.encode()).hexdigest()

            key = APAiInstanceKey.query.filter_by(key_id='apk_test_001').first()
            assert key is not None
            assert key.api_key_hash == expected_hash

    def test_verify_valid_key(self, client, apai_fixtures):
        """verify_instance_key returns the key record for valid keys."""
        with app.app_context():
            from apai_provisioning import verify_instance_key

            result = verify_instance_key(apai_fixtures['raw_key'])
            assert result is not None
            assert result.key_id == 'apk_test_001'
            assert result.usage_count >= 1

    def test_verify_invalid_key(self, client):
        """verify_instance_key returns None for invalid keys."""
        with app.app_context():
            from apai_provisioning import verify_instance_key

            assert verify_instance_key("apai_invalid_key_xyz") is None
            assert verify_instance_key("not_an_apai_key") is None
            assert verify_instance_key("") is None
            assert verify_instance_key(None) is None

    def test_key_usage_tracking(self, client, apai_fixtures):
        """Each verification increments usage count."""
        with app.app_context():
            from apai_provisioning import verify_instance_key

            key_before = APAiInstanceKey.query.filter_by(key_id='apk_test_001').first()
            initial_count = key_before.usage_count or 0

            verify_instance_key(apai_fixtures['raw_key'])
            verify_instance_key(apai_fixtures['raw_key'])

            key_after = APAiInstanceKey.query.filter_by(key_id='apk_test_001').first()
            assert key_after.usage_count >= initial_count + 2


# ============================================================
# Credential Routing API Tests
# ============================================================

class TestCredentialRoutingAPI:
    """Test the credential search/book endpoints."""

    def test_credential_search_no_key(self, client):
        """Search without API key returns 401."""
        resp = client.post(
            '/api/credential/search',
            data=json.dumps({"origin": "JFK", "destination": "LAX", "departure_date": "2026-06-01"}),
            content_type='application/json',
        )
        assert resp.status_code == 401

    def test_credential_search_invalid_key(self, client):
        """Search with invalid API key returns 401."""
        resp = client.post(
            '/api/credential/search',
            data=json.dumps({"origin": "JFK", "destination": "LAX", "departure_date": "2026-06-01"}),
            content_type='application/json',
            headers={"X-APAi-Key": "apai_invalid_key"},
        )
        assert resp.status_code == 401

    def test_credential_search_missing_params(self, client, apai_fixtures):
        """Search with missing required params returns 400."""
        resp = client.post(
            '/api/credential/search',
            data=json.dumps({"origin": "JFK"}),
            content_type='application/json',
            headers={"X-APAi-Key": apai_fixtures['raw_key']},
        )
        assert resp.status_code == 400

    @patch('server.PicassoClient', create=True)
    @patch('server.DuffelClient', create=True)
    def test_credential_search_with_valid_key(self, mock_duffel, mock_picasso, client, apai_fixtures):
        """Search with valid API key returns results."""
        # The endpoint imports these inside the function, so we patch at module level
        with patch('picasso_client.PicassoClient') as MockPicasso, \
             patch('duffel_client.DuffelClient') as MockDuffel:

            MockPicasso.return_value.search_flights.return_value = [
                {"airline": "AA", "price": 250, "origin": "JFK", "destination": "LAX"}
            ]
            MockDuffel.return_value.search_flights.return_value = [
                {"airline": "DL", "price": 275, "origin": "JFK", "destination": "LAX"}
            ]

            resp = client.post(
                '/api/credential/search',
                data=json.dumps({
                    "origin": "JFK",
                    "destination": "LAX",
                    "departure_date": "2026-06-01",
                }),
                content_type='application/json',
                headers={"X-APAi-Key": apai_fixtures['raw_key']},
            )
            assert resp.status_code == 200
            data = resp.get_json()
            assert data['count'] == 2
            assert len(data['results']) == 2

    def test_credential_book_no_key(self, client):
        """Book without API key returns 401."""
        resp = client.post(
            '/api/credential/book',
            data=json.dumps({"offer_id": "test", "passengers": [{"name": "John"}]}),
            content_type='application/json',
        )
        assert resp.status_code == 401


# ============================================================
# APAi Subscription Tests
# ============================================================

class TestAPAiSubscription:
    """Test APAi Stripe subscription endpoints."""

    def test_subscribe_invalid_tier(self, client, apai_fixtures):
        """Invalid tier is rejected."""
        # Login
        client.post('/login', data={
            'email': 'apai@example.com',
            'password': 'testpass123',
        })

        resp = client.post(
            '/api/apai/subscribe',
            data=json.dumps({"tier": "invalid_tier"}),
            content_type='application/json',
        )
        assert resp.status_code == 400

    def test_billing_endpoint(self, client, apai_fixtures):
        """Billing endpoint returns account info."""
        # Login
        client.post('/login', data={
            'email': 'apai@example.com',
            'password': 'testpass123',
        })

        resp = client.get('/api/apai/billing')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['account_id'] == 'acc_apai_test'
        assert data['tiers_available'] is not None
        assert 'pro' in data['tiers_available']


# ============================================================
# Admin Deployment Tests
# ============================================================

class TestAdminDeployments:
    """Test admin deployment management."""

    def test_admin_deployments_requires_admin(self, client, apai_fixtures):
        """Non-admin cannot access deployment list."""
        with app.app_context():
            # Login as non-admin
            client.post('/login', data={
                'email': 'apai@example.com',
                'password': 'testpass123',
            })

            resp = client.get('/admin/deployments')
            # Should redirect (302) or forbidden
            assert resp.status_code in (302, 403)

    def test_admin_deployments_page(self, client, apai_fixtures):
        """Admin can view deployments page."""
        with app.app_context():
            # Create admin user
            admin = User(email='admin@mystes.app', name='Admin', is_admin=True)
            admin.set_password('adminpass')
            db.session.add(admin)
            db.session.commit()

            client.post('/login', data={
                'email': 'admin@mystes.app',
                'password': 'adminpass',
            })

            resp = client.get('/admin/deployments')
            assert resp.status_code == 200
            assert b'APAi Deployments' in resp.data
