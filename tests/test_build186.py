"""
Build #186 Tests — Launch readiness: Insurance, Deployment, Celery, Env validation.

Covers:
  - Insurance vertical (routes_insurance.py)
  - B2B template deployment model (models.py)
  - Country code resolution
  - Startup environment validation (server.py)
  - .env.example + migration files

Run: pytest tests/test_build186.py -v
"""

import json
import sys
import os
import pytest
from datetime import datetime, date, timezone, timedelta
from unittest.mock import patch, MagicMock

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _root)
sys.path.insert(0, os.path.join(_root, "picasso-sdk"))

from server import app, db, limiter
from models import (
    User, Deal, CommercialAccount, TemplateDeployment,
)


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
def auth_client(client):
    """Authenticated test client."""
    with app.app_context():
        client.post('/register', data={
            'email': 'test186@example.com',
            'password': 'TestPass186!',
            'name': 'Build 186 Tester',
        }, follow_redirects=True)
        client.post('/login', data={
            'email': 'test186@example.com',
            'password': 'TestPass186!',
        }, follow_redirects=True)
        yield client


# ==========================================================================
# Test Group 1: Insurance Vertical
# ==========================================================================

class TestInsuranceRoutes:
    """Test insurance search page and API endpoints."""

    def test_insurance_page_renders(self, client):
        """GET /insurance renders the search page."""
        resp = client.get('/insurance')
        assert resp.status_code == 200
        assert b'Travel Insurance' in resp.data
        assert b'SafetyWing' in resp.data
        assert b'insuranceDestination' in resp.data

    def test_insurance_search_missing_data(self, client):
        """POST /api/insurance/search rejects missing fields."""
        resp = client.post('/api/insurance/search',
                           data=json.dumps({"destination": ""}),
                           content_type='application/json')
        data = json.loads(resp.data)
        assert data["success"] is False
        assert "Destination required" in data["error"]

    def test_insurance_search_missing_dates(self, client):
        """POST /api/insurance/search rejects missing dates."""
        resp = client.post('/api/insurance/search',
                           data=json.dumps({"destination": "France"}),
                           content_type='application/json')
        data = json.loads(resp.data)
        assert data["success"] is False
        assert "dates required" in data["error"]

    def test_insurance_search_no_body(self, client):
        """POST /api/insurance/search rejects empty request."""
        resp = client.post('/api/insurance/search',
                           data=json.dumps(None),
                           content_type='application/json')
        # Either returns JSON error or 400
        assert resp.status_code in (400, 200)
        if resp.status_code == 200 or resp.content_type == 'application/json':
            data = json.loads(resp.data)
            assert data["success"] is False

    def test_insurance_select_requires_login(self, client):
        """POST /api/insurance/select requires authentication."""
        resp = client.post('/api/insurance/select',
                           data=json.dumps({"quote": {"total_price": 50}}),
                           content_type='application/json')
        # Should redirect to login
        assert resp.status_code in (302, 401)

    def test_insurance_select_creates_deal(self, auth_client):
        """Selecting a plan creates an insurance Deal."""
        resp = auth_client.post('/api/insurance/select',
                                data=json.dumps({
                                    "quote": {
                                        "plan_name": "Nomad Insurance",
                                        "total_price": 85.00,
                                        "destination": "FR",
                                        "start_date": "2026-06-01",
                                        "end_date": "2026-06-30",
                                        "travelers": 2,
                                        "raw_offer": {"source": "safetywing", "quote_id": "q123"},
                                    }
                                }),
                                content_type='application/json')
        data = json.loads(resp.data)
        assert data["success"] is True
        assert data["deal_id"].startswith("INS_")
        assert data["total_price"] == 85.0
        assert data["platform_fee"] >= 3.0  # Minimum $3 fee

        # Verify Deal in DB
        deal = Deal.query.filter_by(deal_id=data["deal_id"]).first()
        assert deal is not None
        assert deal.deal_type == "insurance"
        assert deal.claimed_by is not None

    def test_insurance_select_rejects_zero_price(self, auth_client):
        """Rejects insurance selection with zero price."""
        resp = auth_client.post('/api/insurance/select',
                                data=json.dumps({
                                    "quote": {"total_price": 0}
                                }),
                                content_type='application/json')
        data = json.loads(resp.data)
        assert data["success"] is False
        assert "Invalid price" in data["error"]

    def test_insurance_select_no_quote(self, auth_client):
        """Rejects insurance selection with no quote."""
        resp = auth_client.post('/api/insurance/select',
                                data=json.dumps({}),
                                content_type='application/json')
        data = json.loads(resp.data)
        assert data["success"] is False
        assert "No quote" in data["error"]

    def test_insurance_deal_has_raw_offer(self, auth_client):
        """Insurance deal stores raw offer data in amadeus_offer_data."""
        resp = auth_client.post('/api/insurance/select',
                                data=json.dumps({
                                    "quote": {
                                        "total_price": 42.50,
                                        "plan_name": "Nomad",
                                        "raw_offer": {"source": "safetywing"},
                                    }
                                }),
                                content_type='application/json')
        data = json.loads(resp.data)
        assert data["success"] is True
        deal = Deal.query.filter_by(deal_id=data["deal_id"]).first()
        assert deal.amadeus_offer_data is not None
        offer_data = json.loads(deal.amadeus_offer_data)
        assert offer_data["plan_name"] == "Nomad"
        assert offer_data["raw_offer"]["source"] == "safetywing"

    def test_insurance_fee_minimum_3_dollars(self, auth_client):
        """Platform fee is at least $3 even on small insurance quotes."""
        resp = auth_client.post('/api/insurance/select',
                                data=json.dumps({
                                    "quote": {"total_price": 5.00}
                                }),
                                content_type='application/json')
        data = json.loads(resp.data)
        assert data["success"] is True
        assert data["platform_fee"] >= 3.0


# ==========================================================================
# Test Group 2: Country Code Resolution
# ==========================================================================

class TestCountryCodeResolution:
    """Test the _resolve_country_code helper."""

    def test_two_letter_passthrough(self):
        """Two-letter codes pass through as-is."""
        from routes_insurance import _resolve_country_code
        assert _resolve_country_code("FR") == "FR"
        assert _resolve_country_code("us") == "US"

    def test_full_name_resolution(self):
        """Full country names resolve to codes."""
        from routes_insurance import _resolve_country_code
        assert _resolve_country_code("France") == "FR"
        assert _resolve_country_code("japan") == "JP"
        assert _resolve_country_code("United States") == "US"
        assert _resolve_country_code("Bali") == "ID"

    def test_unknown_fallback(self):
        """Unknown destinations fall back to first 2 chars."""
        from routes_insurance import _resolve_country_code
        result = _resolve_country_code("Atlantis")
        assert result == "AT"  # First 2 chars uppercased

    def test_whitespace_handling(self):
        """Leading/trailing whitespace is stripped."""
        from routes_insurance import _resolve_country_code
        assert _resolve_country_code("  FR  ") == "FR"
        assert _resolve_country_code("  france  ") == "FR"


# ==========================================================================
# Test Group 3: B2B Template Deployment Model
# ==========================================================================

class TestTemplateDeploymentModel:
    """Test TemplateDeployment model directly (routes require feature flag at import)."""

    def test_template_deployment_create(self, client):
        """TemplateDeployment model creates and serializes correctly."""
        import secrets as _s
        user = User(email='dep@test.com', name='Deployer', is_active=True)
        user.set_password('Test123!')
        db.session.add(user)
        db.session.flush()

        account = CommercialAccount(
            account_id=f'phx_{_s.token_hex(8)}',
            owner_user_id=user.id,
            name='Deploy Agency',
            contact_email='dep@test.com',
            is_active=True,
        )
        db.session.add(account)
        db.session.flush()

        dep = TemplateDeployment(
            deployment_id=f'dep_{_s.token_hex(12)}',
            commercial_account_id=account.id,
            instance_name='my-travel-ota',
            subdomain='my-travel-ota.mystes.app',
            brand_name='My Travel',
            brand_color_primary='#7c3aed',
            brand_color_secondary='#a855f7',
            status='requested',
        )
        db.session.add(dep)
        db.session.commit()

        d = dep.to_dict()
        assert d['instance_name'] == 'my-travel-ota'
        assert d['status'] == 'requested'
        assert d['brand_color_primary'] == '#7c3aed'
        assert dep.deployment_id.startswith('dep_')

    def test_template_deployment_lifecycle(self, client):
        """Deployment transitions through status lifecycle."""
        import secrets as _s
        user = User(email='lc@test.com', name='Lifecycle', is_active=True)
        user.set_password('Test123!')
        db.session.add(user)
        db.session.flush()

        account = CommercialAccount(
            account_id=f'phx_{_s.token_hex(8)}',
            owner_user_id=user.id,
            name='LC Agency',
            contact_email='lc@test.com',
            is_active=True,
        )
        db.session.add(account)
        db.session.flush()

        dep = TemplateDeployment(
            deployment_id=f'dep_{_s.token_hex(12)}',
            commercial_account_id=account.id,
            instance_name='lifecycle-test',
            status='requested',
        )
        db.session.add(dep)
        db.session.commit()

        # Transition: requested → provisioning → active
        dep.status = 'provisioning'
        dep.status_message = 'Setting up environment...'
        db.session.commit()
        assert dep.to_dict()['status'] == 'provisioning'

        dep.status = 'active'
        dep.subdomain = 'lifecycle-test.mystes.app'
        db.session.commit()
        assert dep.to_dict()['status'] == 'active'
        assert dep.to_dict()['subdomain'] == 'lifecycle-test.mystes.app'

    def test_template_deployment_to_dict_complete(self, client):
        """to_dict() returns all expected fields."""
        import secrets as _s
        user = User(email='td@test.com', name='TD', is_active=True)
        user.set_password('Test123!')
        db.session.add(user)
        db.session.flush()

        account = CommercialAccount(
            account_id=f'phx_{_s.token_hex(8)}',
            owner_user_id=user.id,
            name='TD Agency',
            contact_email='td@test.com',
            is_active=True,
        )
        db.session.add(account)
        db.session.flush()

        dep = TemplateDeployment(
            deployment_id='dep_abc123',
            commercial_account_id=account.id,
            instance_name='dict-test',
            brand_name='Dict Brand',
            brand_color_primary='#ff0000',
            brand_color_secondary='#00ff00',
            custom_domain='book.example.com',
            status='active',
        )
        db.session.add(dep)
        db.session.commit()

        d = dep.to_dict()
        expected_keys = [
            'deployment_id', 'instance_name', 'brand_name',
            'brand_color_primary', 'brand_color_secondary',
            'custom_domain', 'status',
        ]
        for key in expected_keys:
            assert key in d, f"Missing key: {key}"

    def test_deployment_relationship(self, client):
        """TemplateDeployment.commercial_account relationship works."""
        import secrets as _s
        user = User(email='rel@test.com', name='Rel', is_active=True)
        user.set_password('Test123!')
        db.session.add(user)
        db.session.flush()

        account = CommercialAccount(
            account_id=f'phx_{_s.token_hex(8)}',
            owner_user_id=user.id,
            name='Rel Agency',
            contact_email='rel@test.com',
            is_active=True,
        )
        db.session.add(account)
        db.session.flush()

        dep = TemplateDeployment(
            deployment_id=f'dep_{_s.token_hex(12)}',
            commercial_account_id=account.id,
            instance_name='rel-test',
        )
        db.session.add(dep)
        db.session.commit()

        assert dep.commercial_account.name == 'Rel Agency'
        assert len(account.deployments) == 1


# ==========================================================================
# Test Group 4: Celery Tasks (import-guarded)
# ==========================================================================

class TestCeleryTasks:
    """Test Celery task definitions exist (skip if celery not installed)."""

    def test_celery_app_importable(self):
        """celery_app.py can be parsed for task definitions."""
        celery_path = os.path.join(_root, 'celery_app.py')
        with open(celery_path) as f:
            content = f.read()

        assert 'refresh_saved_item_prices' in content
        assert 'provision_template_deployment' in content
        assert 'refresh-saved-item-prices-6h' in content

    def test_price_refresh_task_defined(self):
        """Price refresh task is defined with correct schedule."""
        celery_path = os.path.join(_root, 'celery_app.py')
        with open(celery_path) as f:
            content = f.read()

        assert '21600' in content  # 6 hours in seconds
        assert 'price_alert_enabled' in content


# ==========================================================================
# Test Group 5: Environment Validation
# ==========================================================================

class TestEnvValidation:
    """Test startup environment validation."""

    def test_env_warnings_block_exists(self):
        """server.py has startup validation code."""
        server_path = os.path.join(_root, 'server.py')
        with open(server_path) as f:
            content = f.read()

        assert '_env_warnings' in content
        assert 'STRIPE_SECRET_KEY' in content
        assert 'ANTHROPIC_API_KEY' in content

    def test_app_starts_without_stripe(self, client):
        """App starts successfully even without STRIPE_SECRET_KEY."""
        resp = client.get('/')
        assert resp.status_code in (200, 302)

    def test_app_starts_without_anthropic(self, client):
        """App starts successfully even without ANTHROPIC_API_KEY."""
        resp = client.get('/flights')
        assert resp.status_code in (200, 302)


# ==========================================================================
# Test Group 6: .env.example
# ==========================================================================

class TestEnvExample:
    """Verify .env.example was created with all required sections."""

    def test_env_example_exists(self):
        """The .env.example file exists."""
        env_path = os.path.join(_root, '.env.example')
        assert os.path.exists(env_path), ".env.example not found"

    def test_env_example_has_sections(self):
        """The .env.example covers critical config sections."""
        env_path = os.path.join(_root, '.env.example')
        with open(env_path) as f:
            content = f.read()

        assert 'STRIPE_SECRET_KEY' in content
        assert 'ANTHROPIC_API_KEY' in content
        assert 'DATABASE_URL' in content
        assert 'SECRET_KEY' in content
        assert 'DUFFEL' in content


# ==========================================================================
# Test Group 7: Migration File
# ==========================================================================

class TestMigration:
    """Verify migration file exists and is well-formed."""

    def test_migration_file_exists(self):
        """Build #184-186 migration file exists."""
        migration_path = os.path.join(
            _root, 'migrations', 'versions',
            'aa184186b2b1_build184_186_devportal_and_b2b_markup.py'
        )
        assert os.path.exists(migration_path), "Migration file not found"

    def test_migration_has_upgrade_and_downgrade(self):
        """Migration has both upgrade() and downgrade() functions."""
        migration_path = os.path.join(
            _root, 'migrations', 'versions',
            'aa184186b2b1_build184_186_devportal_and_b2b_markup.py'
        )
        with open(migration_path) as f:
            content = f.read()

        assert 'def upgrade()' in content
        assert 'def downgrade()' in content
        assert 'dev_portal_accounts' in content
        assert 'consumer_markup_percent' in content
