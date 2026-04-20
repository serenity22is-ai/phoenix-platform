"""
Tests for APAi Tier Feature Gating.

Covers:
    - Tier hierarchy and rank
    - Feature access per tier (Pro/Enterprise/Scale)
    - Vault limit checks (3/10/unlimited)
    - Team seat checks (1/5/unlimited)
    - Locked features list (taste strategy)
    - Tier summary generation
    - Tier aliases (starter → pro)
    - Network route tier gating (audit trail, vault limits)
"""

import json
import uuid

import pytest

from picasso.agent.tier_gating import (
    FEATURE_MIN_TIER,
    TIER_LIMITS,
    TIER_RANK,
    check_feature,
    check_team_seats,
    check_vault_limit,
    get_limits,
    get_locked_features,
    get_tier_summary,
    has_feature,
)


# ===================================================================
# Tier Hierarchy
# ===================================================================


class TestTierHierarchy:
    """Test tier rank ordering."""

    def test_pro_is_lowest(self):
        assert TIER_RANK["pro"] < TIER_RANK["enterprise"]
        assert TIER_RANK["pro"] < TIER_RANK["scale"]

    def test_enterprise_is_middle(self):
        assert TIER_RANK["enterprise"] > TIER_RANK["pro"]
        assert TIER_RANK["enterprise"] < TIER_RANK["scale"]

    def test_scale_is_highest(self):
        assert TIER_RANK["scale"] > TIER_RANK["pro"]
        assert TIER_RANK["scale"] > TIER_RANK["enterprise"]


# ===================================================================
# Feature Access
# ===================================================================


class TestFeatureAccess:
    """Test has_feature and check_feature for all tiers."""

    # --- Pro tier ---
    def test_pro_has_api_access(self):
        assert has_feature("pro", "api_access") is True

    def test_pro_has_terminal(self):
        assert has_feature("pro", "anastasia_terminal") is True

    def test_pro_has_network(self):
        assert has_feature("pro", "network_access") is True

    def test_pro_no_white_label(self):
        assert has_feature("pro", "white_label") is False

    def test_pro_no_audit(self):
        assert has_feature("pro", "transaction_audit_trail") is False

    def test_pro_no_webhooks(self):
        assert has_feature("pro", "webhook_system") is False

    def test_pro_no_intelligence_feed(self):
        assert has_feature("pro", "network_intelligence_feed") is False

    def test_pro_no_failure_recovery(self):
        assert has_feature("pro", "booking_failure_recovery") is False

    # --- Enterprise tier ---
    def test_enterprise_has_white_label(self):
        assert has_feature("enterprise", "white_label") is True

    def test_enterprise_has_audit(self):
        assert has_feature("enterprise", "transaction_audit_trail") is True

    def test_enterprise_has_webhooks(self):
        assert has_feature("enterprise", "webhook_system") is True

    def test_enterprise_has_dynamic_terms(self):
        assert has_feature("enterprise", "dynamic_terms") is True

    def test_enterprise_has_team_roles(self):
        assert has_feature("enterprise", "team_roles") is True

    def test_enterprise_has_custom_sdk(self):
        assert has_feature("enterprise", "custom_sdk_deploy") is True

    def test_enterprise_no_intelligence_feed(self):
        assert has_feature("enterprise", "network_intelligence_feed") is False

    def test_enterprise_no_bulk_ops(self):
        assert has_feature("enterprise", "bulk_operations") is False

    # --- Scale tier ---
    def test_scale_has_everything(self):
        for feature in FEATURE_MIN_TIER:
            assert has_feature("scale", feature) is True, f"Scale should have {feature}"

    def test_scale_has_intelligence_feed(self):
        assert has_feature("scale", "network_intelligence_feed") is True

    def test_scale_has_failure_recovery(self):
        assert has_feature("scale", "booking_failure_recovery") is True

    def test_scale_has_bulk_ops(self):
        assert has_feature("scale", "bulk_operations") is True

    def test_scale_has_data_export(self):
        assert has_feature("scale", "data_export") is True

    # --- Unknown features allow by default ---
    def test_unknown_feature_allows(self):
        assert has_feature("pro", "some_future_feature") is True

    # --- Tier aliases ---
    def test_starter_alias_is_pro(self):
        assert has_feature("starter", "api_access") is True
        assert has_feature("starter", "white_label") is False

    def test_case_insensitive(self):
        assert has_feature("PRO", "api_access") is True
        assert has_feature("Enterprise", "white_label") is True
        assert has_feature("SCALE", "network_intelligence_feed") is True

    def test_none_tier_defaults_to_pro(self):
        assert has_feature(None, "api_access") is True
        assert has_feature(None, "white_label") is False


class TestCheckFeature:
    """Test check_feature returns upgrade messages."""

    def test_allowed_returns_none_message(self):
        allowed, msg = check_feature("enterprise", "white_label")
        assert allowed is True
        assert msg is None

    def test_blocked_returns_message(self):
        allowed, msg = check_feature("pro", "white_label")
        assert allowed is False
        assert "Enterprise" in msg
        assert "White-Label" in msg

    def test_scale_only_returns_scale_message(self):
        allowed, msg = check_feature("pro", "network_intelligence_feed")
        assert allowed is False
        assert "Scale" in msg


# ===================================================================
# Resource Limits
# ===================================================================


class TestVaultLimits:
    """Test credential vault limit checks."""

    def test_pro_limit_is_3(self):
        limits = get_limits("pro")
        assert limits["credential_vault_max"] == 3

    def test_enterprise_limit_is_10(self):
        limits = get_limits("enterprise")
        assert limits["credential_vault_max"] == 10

    def test_scale_is_unlimited(self):
        limits = get_limits("scale")
        assert limits["credential_vault_max"] == 0  # 0 = unlimited

    def test_pro_vault_under_limit(self):
        allowed, max_val = check_vault_limit("pro", 2)
        assert allowed is True
        assert max_val == 3

    def test_pro_vault_at_limit(self):
        allowed, max_val = check_vault_limit("pro", 3)
        assert allowed is False
        assert max_val == 3

    def test_pro_vault_over_limit(self):
        allowed, max_val = check_vault_limit("pro", 5)
        assert allowed is False
        assert max_val == 3

    def test_enterprise_vault_at_9(self):
        allowed, _ = check_vault_limit("enterprise", 9)
        assert allowed is True

    def test_enterprise_vault_at_10(self):
        allowed, _ = check_vault_limit("enterprise", 10)
        assert allowed is False

    def test_scale_vault_always_allowed(self):
        allowed, max_val = check_vault_limit("scale", 100)
        assert allowed is True
        assert max_val == 0  # unlimited


class TestTeamSeats:
    """Test team seat limit checks."""

    def test_pro_limit_is_1(self):
        limits = get_limits("pro")
        assert limits["team_seats_max"] == 1

    def test_enterprise_limit_is_5(self):
        limits = get_limits("enterprise")
        assert limits["team_seats_max"] == 5

    def test_scale_is_unlimited(self):
        limits = get_limits("scale")
        assert limits["team_seats_max"] == 0

    def test_pro_seat_at_limit(self):
        allowed, _ = check_team_seats("pro", 1)
        assert allowed is False

    def test_enterprise_seat_under_limit(self):
        allowed, _ = check_team_seats("enterprise", 3)
        assert allowed is True

    def test_scale_seat_always_allowed(self):
        allowed, _ = check_team_seats("scale", 50)
        assert allowed is True


# ===================================================================
# Taste Strategy
# ===================================================================


class TestTasteStrategy:
    """Test locked features list for UI greyed-out previews."""

    def test_pro_has_locked_features(self):
        locked = get_locked_features("pro")
        assert len(locked) > 0
        labels = [f["label"] for f in locked]
        assert "White-Label Branding" in labels
        assert "Webhook System" in labels
        assert "Network Intelligence Feed" in labels

    def test_enterprise_has_scale_locked(self):
        locked = get_locked_features("enterprise")
        labels = [f["label"] for f in locked]
        assert "White-Label Branding" not in labels  # enterprise has it
        assert "Webhook System" not in labels  # enterprise has it
        assert "Network Intelligence Feed" in labels  # scale only

    def test_scale_has_nothing_locked(self):
        locked = get_locked_features("scale")
        assert len(locked) == 0

    def test_locked_features_have_requires_field(self):
        locked = get_locked_features("pro")
        for f in locked:
            assert "requires" in f
            assert f["requires"] in ("enterprise", "scale")


# ===================================================================
# Tier Summary
# ===================================================================


class TestTierSummary:
    """Test get_tier_summary for dashboard rendering."""

    def test_pro_summary(self):
        s = get_tier_summary("pro")
        assert s["tier"] == "pro"
        assert s["limits"]["credential_vault_max"] == 3
        assert s["limits"]["team_seats_max"] == 1
        assert "api_access" in s["features_available"]
        assert len(s["features_locked"]) > 0
        assert s["upgrade_target"] == "enterprise"

    def test_enterprise_summary(self):
        s = get_tier_summary("enterprise")
        assert s["tier"] == "enterprise"
        assert s["limits"]["credential_vault_max"] == 10
        assert "white_label" in s["features_available"]
        assert s["upgrade_target"] == "scale"

    def test_scale_summary(self):
        s = get_tier_summary("scale")
        assert s["tier"] == "scale"
        assert s["limits"]["credential_vault_max"] == 0
        assert len(s["features_locked"]) == 0
        assert s["upgrade_target"] is None


# ===================================================================
# Network Route Tier Gating (Integration Tests)
# ===================================================================


@pytest.fixture
def app():
    """Create a test Flask app with in-memory SQLite."""
    from flask import Flask
    from picasso.agent.db_models import db

    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["TESTING"] = True

    db.init_app(app)
    with app.app_context():
        db.create_all()
    return app


@pytest.fixture
def db_session(app):
    from picasso.agent.db_models import db
    with app.app_context():
        yield db.session
        db.session.rollback()


@pytest.fixture
def pro_agency(app, db_session):
    """Create a Pro-tier agency."""
    from picasso.agent.db_models import Agency, db
    with app.app_context():
        a = Agency(
            key_hash="pro_" + uuid.uuid4().hex[:60],
            company_name="Pro Travel",
            contact_email="pro@test.com",
            tier="pro",
            is_active=True,
        )
        db.session.add(a)
        db.session.commit()
        return a.key_hash


@pytest.fixture
def enterprise_agency(app, db_session):
    """Create an Enterprise-tier agency."""
    from picasso.agent.db_models import Agency, db
    with app.app_context():
        a = Agency(
            key_hash="ent_" + uuid.uuid4().hex[:60],
            company_name="Enterprise Travel",
            contact_email="ent@test.com",
            tier="enterprise",
            is_active=True,
        )
        db.session.add(a)
        db.session.commit()
        return a.key_hash


@pytest.fixture
def client(app, db_session):
    """Flask test client with mocked require_api_key."""
    from picasso.agent.network_routes import register_network_routes
    from functools import wraps

    def mock_require_api_key(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            from flask import request as req
            req.api_key_hash = req.headers.get("X-Test-Key-Hash", "test_hash")
            return f(*args, **kwargs)
        decorated.__name__ = f.__name__
        return decorated

    register_network_routes(app, mock_require_api_key)
    with app.app_context():
        yield app.test_client()


class TestNetworkRouteGating:
    """Test tier gates on network API endpoints."""

    def test_audit_blocked_for_pro(self, client, pro_agency):
        resp = client.get(
            "/api/v1/network/audit",
            headers={"X-Test-Key-Hash": pro_agency},
        )
        assert resp.status_code == 403
        data = resp.get_json()
        assert data["upgrade_required"] is True
        assert "Enterprise" in data["error"]

    def test_audit_allowed_for_enterprise(self, client, enterprise_agency):
        resp = client.get(
            "/api/v1/network/audit",
            headers={"X-Test-Key-Hash": enterprise_agency},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert "events" in data

    def test_vault_limit_blocks_pro_at_3(self, client, pro_agency):
        """Pro tier can't create more than 3 terms cards."""
        from picasso.agent.db_models import ProviderProfile, RoutingTermsCard, db

        with client.application.app_context():
            profile = ProviderProfile(
                key_hash=pro_agency,
                display_name="Pro Travel",
                apai_tier="pro",
            )
            db.session.add(profile)
            db.session.flush()

            # Add 3 existing cards
            for i in range(3):
                card = RoutingTermsCard(
                    profile_id=profile.id,
                    credential_label=f"Cred {i}",
                    credential_type="gds",
                    provider_system="amadeus",
                )
                db.session.add(card)
            db.session.commit()

        # Try to create a 4th — should be blocked
        resp = client.post(
            "/api/v1/network/terms",
            headers={"X-Test-Key-Hash": pro_agency},
            json={
                "credential_label": "Cred 4",
                "credential_type": "ndc",
                "provider_system": "duffel",
            },
        )
        assert resp.status_code == 403
        data = resp.get_json()
        assert data["upgrade_required"] is True
        assert data["max_allowed"] == 3

    def test_vault_limit_allows_enterprise_at_3(self, client, enterprise_agency):
        """Enterprise tier can create more than 3."""
        from picasso.agent.db_models import ProviderProfile, RoutingTermsCard, db

        with client.application.app_context():
            profile = ProviderProfile(
                key_hash=enterprise_agency,
                display_name="Enterprise Travel",
                apai_tier="enterprise",
            )
            db.session.add(profile)
            db.session.flush()

            for i in range(3):
                card = RoutingTermsCard(
                    profile_id=profile.id,
                    credential_label=f"Cred {i}",
                    credential_type="gds",
                    provider_system="amadeus",
                )
                db.session.add(card)
            db.session.commit()

        # Should succeed — enterprise has 10 limit
        resp = client.post(
            "/api/v1/network/terms",
            headers={"X-Test-Key-Hash": enterprise_agency},
            json={
                "credential_label": "Cred 4",
                "credential_type": "ndc",
                "provider_system": "duffel",
            },
        )
        assert resp.status_code == 201

    def test_tier_info_endpoint(self, client, pro_agency):
        resp = client.get(
            "/api/v1/network/tier",
            headers={"X-Test-Key-Hash": pro_agency},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["tier"] == "pro"
        assert data["limits"]["credential_vault_max"] == 3
        assert len(data["features_locked"]) > 0
        assert data["upgrade_target"] == "enterprise"

    def test_stats_includes_tier_info(self, client, pro_agency):
        resp = client.get(
            "/api/v1/network/stats",
            headers={"X-Test-Key-Hash": pro_agency},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert "tier" in data
        assert data["tier"]["tier"] == "pro"
        assert data["analytics_depth"] == "basic"

    def test_stats_enterprise_full_analytics(self, client, enterprise_agency):
        resp = client.get(
            "/api/v1/network/stats",
            headers={"X-Test-Key-Hash": enterprise_agency},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["analytics_depth"] == "full"
