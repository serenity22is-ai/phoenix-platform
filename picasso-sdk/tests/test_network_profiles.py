"""
Tests for the APAi Credential Network Profile System.

Covers:
- DB model creation (ProviderProfile, RoutingTermsCard, NetworkConnection,
  RoutingEvent, TerminalSession, CustomModule)
- Network routes: directory browse, profile CRUD, terms CRUD,
  connection lifecycle (request→accept→pause→resume→disconnect, reject),
  audit trail, stats
- Query cost accounting in CredentialRouter (record_query, record_booking,
  health calculation)
- Edge cases: self-connect, duplicate connection, unpublished terms,
  connection count tracking

Run with: cd picasso-sdk && python3 -m pytest tests/test_network_profiles.py -v
"""

import json
import uuid
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Fixtures — In-memory Flask app with DB
# ---------------------------------------------------------------------------

@pytest.fixture
def app():
    """Create a minimal Flask app with SQLAlchemy and network models."""
    from flask import Flask
    from picasso.agent.db_models import db, init_db, Agency

    test_app = Flask(__name__)
    test_app.config["TESTING"] = True
    test_app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    test_app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(test_app)
    with test_app.app_context():
        db.create_all()
        yield test_app
        db.session.remove()


@pytest.fixture
def db_session(app):
    """Get a database session."""
    from picasso.agent.db_models import db
    with app.app_context():
        yield db.session


@pytest.fixture
def agency_a(db_session):
    """Create test agency A (router)."""
    from picasso.agent.db_models import Agency
    a = Agency(
        key_hash="a" * 64,
        api_key_prefix="ana_test_a",
        company_name="AlphaOTA",
        contact_email="alpha@test.com",
        tier="enterprise",
        is_active=True,
    )
    db_session.add(a)
    db_session.commit()
    return a


@pytest.fixture
def agency_b(db_session):
    """Create test agency B (host/provider)."""
    from picasso.agent.db_models import Agency
    b = Agency(
        key_hash="b" * 64,
        api_key_prefix="ana_test_b",
        company_name="BetaGDS",
        contact_email="beta@test.com",
        tier="pro",
        is_active=True,
    )
    db_session.add(b)
    db_session.commit()
    return b


@pytest.fixture
def profile_b(db_session, agency_b):
    """Create a ProviderProfile for agency B."""
    from picasso.agent.db_models import ProviderProfile
    p = ProviderProfile(
        key_hash=agency_b.key_hash,
        display_name="BetaGDS Credentials",
        description="Premium Amadeus GDS access across EU markets",
        apai_tier="pro",
        credentials_summary_json=[
            {"type": "gds", "system": "amadeus", "markets": ["DE", "GB", "FR"]},
        ],
        is_visible=True,
        is_accepting_connections=True,
    )
    db_session.add(p)
    db_session.commit()
    return p


@pytest.fixture
def terms_card(db_session, profile_b):
    """Create a published terms card for profile B."""
    from picasso.agent.db_models import RoutingTermsCard
    card = RoutingTermsCard(
        profile_id=profile_b.id,
        credential_label="Amadeus GDS — EU",
        credential_type="gds",
        provider_system="amadeus",
        per_query_fee_usd=0.05,
        revenue_split_router_pct=70.0,
        revenue_split_host_pct=30.0,
        markets_included_json=["DE", "GB", "FR"],
        cabin_classes_json=["economy", "business"],
        max_queries_per_day=5000,
        response_time_sla_sec=8.0,
        trial_period_days=14,
        allow_pos_arbitrage=True,
        is_published=True,
    )
    db_session.add(card)
    db_session.commit()
    return card


# ===================================================================
# MODEL TESTS
# ===================================================================


class TestProviderProfile:
    """Tests for the ProviderProfile model."""

    def test_create_profile(self, db_session, agency_a):
        from picasso.agent.db_models import ProviderProfile
        p = ProviderProfile(
            key_hash=agency_a.key_hash,
            display_name="AlphaOTA Network",
            apai_tier="enterprise",
        )
        db_session.add(p)
        db_session.commit()

        assert p.id is not None
        assert p.display_name == "AlphaOTA Network"
        assert p.apai_tier == "enterprise"
        assert p.reputation_score == 5.0
        assert p.is_visible is True

    def test_to_dict_with_stats(self, profile_b):
        d = profile_b.to_dict(include_stats=True)
        assert d["display_name"] == "BetaGDS Credentials"
        assert "total_connections" in d
        assert "reputation_score" in d
        assert d["credentials_summary"][0]["system"] == "amadeus"

    def test_to_dict_without_stats(self, profile_b):
        d = profile_b.to_dict(include_stats=False)
        assert "total_connections" not in d
        assert "display_name" in d

    def test_unique_key_hash(self, db_session, agency_a):
        from picasso.agent.db_models import ProviderProfile
        p1 = ProviderProfile(key_hash=agency_a.key_hash, display_name="First")
        db_session.add(p1)
        db_session.commit()

        p2 = ProviderProfile(key_hash=agency_a.key_hash, display_name="Dup")
        db_session.add(p2)
        with pytest.raises(Exception):
            db_session.commit()
        db_session.rollback()


class TestRoutingTermsCard:
    """Tests for the RoutingTermsCard model."""

    def test_create_terms_card(self, terms_card):
        assert terms_card.credential_label == "Amadeus GDS — EU"
        assert terms_card.per_query_fee_usd == 0.05
        assert terms_card.revenue_split_router_pct == 70.0
        assert terms_card.is_published is True

    def test_to_dict_5_sections(self, terms_card):
        d = terms_card.to_dict()
        assert "pricing" in d
        assert "coverage" in d
        assert "limits" in d
        assert "relationship" in d
        assert "arbitrage" in d

        assert d["pricing"]["per_query_fee_usd"] == 0.05
        assert d["pricing"]["revenue_split"]["router_pct"] == 70.0
        assert d["coverage"]["markets_included"] == ["DE", "GB", "FR"]
        assert d["limits"]["max_queries_per_day"] == 5000
        assert d["relationship"]["trial_period_days"] == 14
        assert d["arbitrage"]["allow_pos_arbitrage"] is True


class TestNetworkConnection:
    """Tests for the NetworkConnection model."""

    def test_create_connection(self, db_session, agency_a, agency_b, terms_card):
        from picasso.agent.db_models import NetworkConnection
        conn = NetworkConnection(
            requester_key_hash=agency_a.key_hash,
            provider_key_hash=agency_b.key_hash,
            terms_card_id=terms_card.id,
            status="pending",
            request_message="Would like to use your Amadeus access",
        )
        db_session.add(conn)
        db_session.commit()

        assert conn.id is not None
        assert conn.status == "pending"
        assert conn.queries_this_month == 0
        assert conn.health == "green"

    def test_to_dict_truncates_key_hash(self, db_session, agency_a, agency_b, terms_card):
        from picasso.agent.db_models import NetworkConnection
        conn = NetworkConnection(
            requester_key_hash=agency_a.key_hash,
            provider_key_hash=agency_b.key_hash,
            terms_card_id=terms_card.id,
        )
        db_session.add(conn)
        db_session.commit()

        d = conn.to_dict()
        assert d["requester_key_hash"] == "aaaaaaaa..."
        assert d["provider_key_hash"] == "bbbbbbbb..."
        assert "stats" in d

    def test_unique_constraint(self, db_session, agency_a, agency_b, terms_card):
        from picasso.agent.db_models import NetworkConnection
        c1 = NetworkConnection(
            requester_key_hash=agency_a.key_hash,
            provider_key_hash=agency_b.key_hash,
        )
        db_session.add(c1)
        db_session.commit()

        c2 = NetworkConnection(
            requester_key_hash=agency_a.key_hash,
            provider_key_hash=agency_b.key_hash,
        )
        db_session.add(c2)
        with pytest.raises(Exception):
            db_session.commit()
        db_session.rollback()


class TestRoutingEvent:
    """Tests for the RoutingEvent model."""

    def test_create_event(self, db_session, agency_a, agency_b, terms_card):
        from picasso.agent.db_models import NetworkConnection, RoutingEvent
        conn = NetworkConnection(
            requester_key_hash=agency_a.key_hash,
            provider_key_hash=agency_b.key_hash,
            terms_card_id=terms_card.id,
            status="active",
        )
        db_session.add(conn)
        db_session.commit()

        event = RoutingEvent(
            event_id=str(uuid.uuid4()),
            connection_id=conn.id,
            event_type="search",
            router_key_hash=agency_a.key_hash,
            host_key_hash=agency_b.key_hash,
            query_fee_usd=0.05,
            route_origin="JFK",
            route_destination="LHR",
            response_time_ms=1200,
            success=True,
        )
        db_session.add(event)
        db_session.commit()

        d = event.to_dict()
        assert d["event_type"] == "search"
        assert d["route"] == "JFK-LHR"
        assert d["success"] is True


class TestTerminalSession:
    """Tests for the TerminalSession model."""

    def test_create_session(self, db_session, agency_a):
        from picasso.agent.db_models import TerminalSession
        s = TerminalSession(
            session_id=str(uuid.uuid4()),
            key_hash=agency_a.key_hash,
            developer_email="dev@alpha.com",
            title="Setting up Duffel integration",
            status="active",
        )
        db_session.add(s)
        db_session.commit()

        d = s.to_dict()
        assert d["status"] == "active"
        assert d["developer_email"] == "dev@alpha.com"
        assert d["queries_used"] == 0


class TestCustomModule:
    """Tests for the CustomModule model."""

    def test_create_module(self, db_session, agency_a):
        from picasso.agent.db_models import CustomModule
        m = CustomModule(
            module_id=str(uuid.uuid4()),
            key_hash=agency_a.key_hash,
            name="Hotel Price Alert",
            description="Custom webhook for hotel price drops",
            module_type="webhook",
            status="draft",
        )
        db_session.add(m)
        db_session.commit()

        d = m.to_dict()
        assert d["name"] == "Hotel Price Alert"
        assert d["status"] == "draft"
        assert d["module_type"] == "webhook"

    def test_lifecycle_progression(self, db_session, agency_a):
        from picasso.agent.db_models import CustomModule
        m = CustomModule(
            module_id=str(uuid.uuid4()),
            key_hash=agency_a.key_hash,
            name="POS Widget",
            module_type="feature",
        )
        db_session.add(m)
        db_session.commit()

        for status in ("auditing", "sandbox", "deployed", "published"):
            m.status = status
            db_session.commit()
            assert m.status == status


# ===================================================================
# CREDENTIAL ROUTER ACCOUNTING TESTS
# ===================================================================


class TestCredentialRouterAccounting:
    """Tests for the query cost accounting in CredentialRouter."""

    def test_record_query_creates_event(self, app, db_session, agency_a, agency_b, terms_card):
        from picasso.agent.db_models import NetworkConnection, RoutingEvent
        from anastasia.dispatch.credential_router import CredentialRouter

        conn = NetworkConnection(
            requester_key_hash=agency_a.key_hash,
            provider_key_hash=agency_b.key_hash,
            terms_card_id=terms_card.id,
            status="active",
        )
        db_session.add(conn)
        db_session.commit()

        router = CredentialRouter(network=None, vault=None, db_session=db_session)

        with app.app_context():
            event_id = router.record_query(
                connection_id=conn.id,
                router_key_hash=agency_a.key_hash,
                host_key_hash=agency_b.key_hash,
                credential_type="gds",
                provider_system="amadeus",
                origin="FRA",
                destination="NRT",
                response_time_ms=1500,
                success=True,
                query_fee_usd=0.05,
            )

        assert event_id is not None
        event = RoutingEvent.query.filter_by(event_id=event_id).first()
        assert event is not None
        assert event.event_type == "search"
        assert event.route_origin == "FRA"

    def test_record_query_updates_connection_stats(self, app, db_session, agency_a, agency_b, terms_card):
        from picasso.agent.db_models import NetworkConnection
        from anastasia.dispatch.credential_router import CredentialRouter

        conn = NetworkConnection(
            requester_key_hash=agency_a.key_hash,
            provider_key_hash=agency_b.key_hash,
            terms_card_id=terms_card.id,
            status="active",
        )
        db_session.add(conn)
        db_session.commit()

        router = CredentialRouter(network=None, vault=None, db_session=db_session)

        with app.app_context():
            router.record_query(
                connection_id=conn.id,
                router_key_hash=agency_a.key_hash,
                host_key_hash=agency_b.key_hash,
                response_time_ms=2000,
                success=True,
            )

        db_session.refresh(conn)
        assert conn.queries_this_month == 1
        assert conn.total_queries_lifetime == 1
        assert conn.avg_response_time_ms == 2000.0

    def test_record_query_failure_increments_errors(self, app, db_session, agency_a, agency_b, terms_card):
        from picasso.agent.db_models import NetworkConnection
        from anastasia.dispatch.credential_router import CredentialRouter

        conn = NetworkConnection(
            requester_key_hash=agency_a.key_hash,
            provider_key_hash=agency_b.key_hash,
            terms_card_id=terms_card.id,
            status="active",
        )
        db_session.add(conn)
        db_session.commit()

        router = CredentialRouter(network=None, vault=None, db_session=db_session)

        with app.app_context():
            router.record_query(
                connection_id=conn.id,
                router_key_hash=agency_a.key_hash,
                host_key_hash=agency_b.key_hash,
                success=False,
                error_message="Timeout",
            )

        db_session.refresh(conn)
        assert conn.error_count_this_month == 1

    def test_record_booking_creates_event_with_financials(self, app, db_session, agency_a, agency_b, terms_card):
        from picasso.agent.db_models import NetworkConnection, RoutingEvent
        from anastasia.dispatch.credential_router import CredentialRouter

        conn = NetworkConnection(
            requester_key_hash=agency_a.key_hash,
            provider_key_hash=agency_b.key_hash,
            terms_card_id=terms_card.id,
            status="active",
        )
        db_session.add(conn)
        db_session.commit()

        router = CredentialRouter(network=None, vault=None, db_session=db_session)

        with app.app_context():
            event_id = router.record_booking(
                connection_id=conn.id,
                router_key_hash=agency_a.key_hash,
                host_key_hash=agency_b.key_hash,
                transaction_amount_usd=500.00,
                router_amount_usd=332.50,
                host_amount_usd=142.50,
                query_fee_usd=25.00,
                origin="JFK",
                destination="LHR",
                success=True,
            )

        assert event_id is not None
        event = RoutingEvent.query.filter_by(event_id=event_id).first()
        assert event.event_type == "booking"
        assert event.transaction_amount_usd == 500.00
        assert event.router_amount_usd == 332.50

    def test_record_booking_updates_revenue_stats(self, app, db_session, agency_a, agency_b, terms_card):
        from picasso.agent.db_models import NetworkConnection
        from anastasia.dispatch.credential_router import CredentialRouter

        conn = NetworkConnection(
            requester_key_hash=agency_a.key_hash,
            provider_key_hash=agency_b.key_hash,
            terms_card_id=terms_card.id,
            status="active",
        )
        db_session.add(conn)
        db_session.commit()

        router = CredentialRouter(network=None, vault=None, db_session=db_session)

        with app.app_context():
            router.record_booking(
                connection_id=conn.id,
                router_key_hash=agency_a.key_hash,
                host_key_hash=agency_b.key_hash,
                transaction_amount_usd=1000.00,
                router_amount_usd=665.00,
                host_amount_usd=285.00,
                success=True,
            )

        db_session.refresh(conn)
        assert conn.bookings_this_month == 1
        assert conn.total_bookings_lifetime == 1
        assert conn.revenue_earned_this_month_usd == 665.00
        assert conn.revenue_paid_this_month_usd == 285.00

    def test_health_calculation_green(self):
        from anastasia.dispatch.credential_router import CredentialRouter
        conn = MagicMock()
        conn.queries_this_month = 100
        conn.error_count_this_month = 2
        conn.avg_response_time_ms = 3000
        assert CredentialRouter._calculate_health(conn) == "green"

    def test_health_calculation_yellow(self):
        from anastasia.dispatch.credential_router import CredentialRouter
        conn = MagicMock()
        conn.queries_this_month = 100
        conn.error_count_this_month = 8  # 8% error rate > 5%
        conn.avg_response_time_ms = 3000
        assert CredentialRouter._calculate_health(conn) == "yellow"

    def test_health_calculation_red(self):
        from anastasia.dispatch.credential_router import CredentialRouter
        conn = MagicMock()
        conn.queries_this_month = 100
        conn.error_count_this_month = 20  # 20% error rate > 15%
        conn.avg_response_time_ms = 3000
        assert CredentialRouter._calculate_health(conn) == "red"

    def test_health_red_from_slow_response(self):
        from anastasia.dispatch.credential_router import CredentialRouter
        conn = MagicMock()
        conn.queries_this_month = 100
        conn.error_count_this_month = 0
        conn.avg_response_time_ms = 20000  # 20s > 15s threshold
        assert CredentialRouter._calculate_health(conn) == "red"

    def test_no_db_session_returns_none(self):
        from anastasia.dispatch.credential_router import CredentialRouter
        router = CredentialRouter(network=None, vault=None, db_session=None)
        assert router.record_query(
            connection_id=1,
            router_key_hash="x",
            host_key_hash="y",
        ) is None
        assert router.record_booking(
            connection_id=1,
            router_key_hash="x",
            host_key_hash="y",
            transaction_amount_usd=100,
            router_amount_usd=70,
            host_amount_usd=30,
        ) is None


# ===================================================================
# NETWORK ROUTES INTEGRATION TESTS
# ===================================================================


@pytest.fixture
def client_app(app, agency_a, agency_b, profile_b, terms_card):
    """Flask app with network routes registered and test data seeded."""
    from picasso.agent.db_models import db

    # Register network routes with a mock require_api_key
    def mock_require_api_key(f):
        from functools import wraps
        @wraps(f)
        def decorated(*args, **kwargs):
            from flask import request as req
            # Read api key hash from header for test flexibility
            req.api_key_hash = req.headers.get("X-Test-Key-Hash", agency_a.key_hash)
            return f(*args, **kwargs)
        return decorated

    from picasso.agent.network_routes import register_network_routes
    register_network_routes(app, mock_require_api_key)

    return app


@pytest.fixture
def client(client_app):
    return client_app.test_client()


class TestNetworkDirectory:
    """Tests for GET /api/v1/network/directory."""

    def test_browse_directory(self, client, profile_b):
        resp = client.get("/api/v1/network/directory")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "providers" in data
        assert len(data["providers"]) >= 1
        assert data["providers"][0]["display_name"] == "BetaGDS Credentials"

    def test_filter_by_tier(self, client, profile_b):
        resp = client.get("/api/v1/network/directory?tier=pro")
        data = resp.get_json()
        assert len(data["providers"]) >= 1

        resp2 = client.get("/api/v1/network/directory?tier=scale")
        data2 = resp2.get_json()
        assert len(data2["providers"]) == 0

    def test_search_filter(self, client, profile_b):
        resp = client.get("/api/v1/network/directory?search=BetaGDS")
        data = resp.get_json()
        assert len(data["providers"]) >= 1

        resp2 = client.get("/api/v1/network/directory?search=nonexistent")
        data2 = resp2.get_json()
        assert len(data2["providers"]) == 0

    def test_pagination(self, client):
        resp = client.get("/api/v1/network/directory?page=1&per_page=1")
        data = resp.get_json()
        assert data["page"] == 1
        assert data["per_page"] == 1


class TestNetworkProfile:
    """Tests for profile CRUD endpoints."""

    def test_get_own_profile_auto_creates(self, client, agency_a):
        resp = client.get("/api/v1/network/profile")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["display_name"] == "AlphaOTA"  # from agency company_name

    def test_update_profile(self, client):
        # First auto-create
        client.get("/api/v1/network/profile")

        # Then update
        resp = client.put(
            "/api/v1/network/profile",
            json={
                "display_name": "AlphaOTA Premium",
                "description": "Top-tier NDC credentials",
                "is_accepting_connections": False,
            },
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["profile"]["display_name"] == "AlphaOTA Premium"
        assert data["profile"]["is_accepting_connections"] is False

    def test_view_other_profile(self, client, profile_b):
        resp = client.get(f"/api/v1/network/profile/{profile_b.id}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["display_name"] == "BetaGDS Credentials"
        assert "terms_cards" in data

    def test_view_nonexistent_profile(self, client):
        resp = client.get("/api/v1/network/profile/99999")
        assert resp.status_code == 404


class TestTermsCards:
    """Tests for terms card CRUD endpoints."""

    def test_create_terms_card(self, client):
        # Auto-create profile first
        client.get("/api/v1/network/profile")

        resp = client.post(
            "/api/v1/network/terms",
            json={
                "credential_label": "Duffel NDC — Global",
                "credential_type": "ndc",
                "provider_system": "duffel",
                "pricing": {
                    "per_query_fee_usd": 0.02,
                    "revenue_split": {"router_pct": 65, "host_pct": 35},
                },
                "coverage": {
                    "markets_included": ["US", "GB"],
                    "airlines_included": ["BA", "AA"],
                },
                "is_published": True,
            },
            content_type="application/json",
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["terms_card"]["credential_label"] == "Duffel NDC — Global"
        assert data["terms_card"]["pricing"]["per_query_fee_usd"] == 0.02

    def test_create_terms_card_missing_required(self, client):
        client.get("/api/v1/network/profile")
        resp = client.post(
            "/api/v1/network/terms",
            json={"credential_label": "Missing fields"},
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_list_terms_cards(self, client):
        client.get("/api/v1/network/profile")
        resp = client.get("/api/v1/network/terms")
        assert resp.status_code == 200
        assert "terms_cards" in resp.get_json()

    def test_update_terms_card(self, client):
        client.get("/api/v1/network/profile")

        # Create one
        create = client.post(
            "/api/v1/network/terms",
            json={
                "credential_label": "Test Card",
                "credential_type": "gds",
                "provider_system": "amadeus",
            },
            content_type="application/json",
        )
        card_id = create.get_json()["terms_card"]["id"]

        # Update it
        resp = client.put(
            f"/api/v1/network/terms/{card_id}",
            json={
                "pricing": {"per_query_fee_usd": 0.10},
                "is_published": True,
            },
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert resp.get_json()["terms_card"]["pricing"]["per_query_fee_usd"] == 0.10
        assert resp.get_json()["terms_card"]["is_published"] is True

    def test_delete_terms_card(self, client):
        client.get("/api/v1/network/profile")

        create = client.post(
            "/api/v1/network/terms",
            json={
                "credential_label": "Deletable",
                "credential_type": "ndc",
                "provider_system": "duffel",
            },
            content_type="application/json",
        )
        card_id = create.get_json()["terms_card"]["id"]

        resp = client.delete(f"/api/v1/network/terms/{card_id}")
        assert resp.status_code == 200


class TestConnections:
    """Tests for the connection lifecycle endpoints."""

    def test_request_connection(self, client, profile_b, terms_card, agency_a):
        resp = client.post(
            "/api/v1/network/connections",
            json={
                "provider_profile_id": profile_b.id,
                "terms_card_id": terms_card.id,
                "message": "Want to access your EU credentials",
            },
            content_type="application/json",
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["connection"]["status"] == "pending"

    def test_cannot_self_connect(self, client, agency_b, profile_b, terms_card):
        # Switch to agency B requesting to connect to their own profile
        resp = client.post(
            "/api/v1/network/connections",
            headers={"X-Test-Key-Hash": agency_b.key_hash},
            json={
                "provider_profile_id": profile_b.id,
                "terms_card_id": terms_card.id,
            },
            content_type="application/json",
        )
        assert resp.status_code == 400
        assert "yourself" in resp.get_json()["error"].lower()

    def test_duplicate_connection_rejected(self, client, profile_b, terms_card):
        client.post(
            "/api/v1/network/connections",
            json={
                "provider_profile_id": profile_b.id,
                "terms_card_id": terms_card.id,
            },
            content_type="application/json",
        )
        resp = client.post(
            "/api/v1/network/connections",
            json={
                "provider_profile_id": profile_b.id,
                "terms_card_id": terms_card.id,
            },
            content_type="application/json",
        )
        assert resp.status_code == 409

    def test_accept_connection(self, client, db_session, profile_b, terms_card, agency_a, agency_b):
        # A requests connection
        create_resp = client.post(
            "/api/v1/network/connections",
            json={
                "provider_profile_id": profile_b.id,
                "terms_card_id": terms_card.id,
            },
            content_type="application/json",
        )
        conn_id = create_resp.get_json()["connection"]["id"]

        # B accepts (switch to agency B)
        resp = client.post(
            f"/api/v1/network/connections/{conn_id}/accept",
            headers={"X-Test-Key-Hash": agency_b.key_hash},
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert resp.get_json()["connection"]["status"] == "active"

    def test_reject_connection(self, client, profile_b, terms_card, agency_b):
        create_resp = client.post(
            "/api/v1/network/connections",
            json={
                "provider_profile_id": profile_b.id,
                "terms_card_id": terms_card.id,
            },
            content_type="application/json",
        )
        conn_id = create_resp.get_json()["connection"]["id"]

        resp = client.post(
            f"/api/v1/network/connections/{conn_id}/reject",
            headers={"X-Test-Key-Hash": agency_b.key_hash},
            content_type="application/json",
        )
        assert resp.status_code == 200

    def test_pause_resume_connection(self, client, profile_b, terms_card, agency_b):
        # Create + accept
        create_resp = client.post(
            "/api/v1/network/connections",
            json={
                "provider_profile_id": profile_b.id,
                "terms_card_id": terms_card.id,
            },
            content_type="application/json",
        )
        conn_id = create_resp.get_json()["connection"]["id"]
        client.post(
            f"/api/v1/network/connections/{conn_id}/accept",
            headers={"X-Test-Key-Hash": agency_b.key_hash},
            content_type="application/json",
        )

        # Pause
        resp = client.post(f"/api/v1/network/connections/{conn_id}/pause")
        assert resp.status_code == 200
        assert resp.get_json()["connection"]["status"] == "paused"

        # Resume
        resp = client.post(f"/api/v1/network/connections/{conn_id}/resume")
        assert resp.status_code == 200
        assert resp.get_json()["connection"]["status"] == "active"

    def test_disconnect(self, client, profile_b, terms_card, agency_b):
        create_resp = client.post(
            "/api/v1/network/connections",
            json={
                "provider_profile_id": profile_b.id,
                "terms_card_id": terms_card.id,
            },
            content_type="application/json",
        )
        conn_id = create_resp.get_json()["connection"]["id"]
        client.post(
            f"/api/v1/network/connections/{conn_id}/accept",
            headers={"X-Test-Key-Hash": agency_b.key_hash},
            content_type="application/json",
        )

        resp = client.delete(f"/api/v1/network/connections/{conn_id}")
        assert resp.status_code == 200

    def test_list_connections(self, client, profile_b, terms_card):
        client.post(
            "/api/v1/network/connections",
            json={
                "provider_profile_id": profile_b.id,
                "terms_card_id": terms_card.id,
            },
            content_type="application/json",
        )

        resp = client.get("/api/v1/network/connections")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["count"] >= 1

    def test_list_connections_filter_role(self, client, profile_b, terms_card):
        client.post(
            "/api/v1/network/connections",
            json={
                "provider_profile_id": profile_b.id,
                "terms_card_id": terms_card.id,
            },
            content_type="application/json",
        )

        resp = client.get("/api/v1/network/connections?role=requester")
        data = resp.get_json()
        for conn in data["connections"]:
            assert conn["role"] == "requester"

    def test_delete_terms_card_with_active_connection_fails(
        self, client, profile_b, terms_card, agency_b
    ):
        # Create connection using that terms card
        client.post(
            "/api/v1/network/connections",
            json={
                "provider_profile_id": profile_b.id,
                "terms_card_id": terms_card.id,
            },
            content_type="application/json",
        )

        # Try to delete the terms card as the provider
        resp = client.delete(
            f"/api/v1/network/terms/{terms_card.id}",
            headers={"X-Test-Key-Hash": agency_b.key_hash},
        )
        assert resp.status_code == 409
        assert "active connection" in resp.get_json()["error"].lower()


class TestAuditTrail:
    """Tests for GET /api/v1/network/audit."""

    def test_audit_trail_empty(self, client):
        resp = client.get("/api/v1/network/audit")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["events"] == []
        assert data["total"] == 0

    def test_audit_trail_with_events(self, client, db_session, agency_a, agency_b, terms_card):
        from picasso.agent.db_models import NetworkConnection, RoutingEvent

        conn = NetworkConnection(
            requester_key_hash=agency_a.key_hash,
            provider_key_hash=agency_b.key_hash,
            terms_card_id=terms_card.id,
            status="active",
        )
        db_session.add(conn)
        db_session.commit()

        for i in range(3):
            event = RoutingEvent(
                event_id=str(uuid.uuid4()),
                connection_id=conn.id,
                event_type="search",
                router_key_hash=agency_a.key_hash,
                host_key_hash=agency_b.key_hash,
                query_fee_usd=0.05,
                success=True,
            )
            db_session.add(event)
        db_session.commit()

        resp = client.get("/api/v1/network/audit")
        data = resp.get_json()
        assert data["total"] == 3

    def test_audit_filter_by_type(self, client, db_session, agency_a, agency_b, terms_card):
        from picasso.agent.db_models import NetworkConnection, RoutingEvent

        conn = NetworkConnection(
            requester_key_hash=agency_a.key_hash,
            provider_key_hash=agency_b.key_hash,
            terms_card_id=terms_card.id,
            status="active",
        )
        db_session.add(conn)
        db_session.commit()

        for etype in ("search", "search", "booking"):
            event = RoutingEvent(
                event_id=str(uuid.uuid4()),
                connection_id=conn.id,
                event_type=etype,
                router_key_hash=agency_a.key_hash,
                host_key_hash=agency_b.key_hash,
            )
            db_session.add(event)
        db_session.commit()

        resp = client.get("/api/v1/network/audit?event_type=booking")
        data = resp.get_json()
        assert data["total"] == 1


class TestNetworkStats:
    """Tests for GET /api/v1/network/stats."""

    def test_stats_empty(self, client):
        resp = client.get("/api/v1/network/stats")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["connections"]["active"] == 0
        assert "profile" in data
        assert "this_month" in data

    def test_stats_with_active_connections(self, client, db_session, agency_a, agency_b, terms_card):
        from picasso.agent.db_models import NetworkConnection

        conn = NetworkConnection(
            requester_key_hash=agency_a.key_hash,
            provider_key_hash=agency_b.key_hash,
            terms_card_id=terms_card.id,
            status="active",
            queries_this_month=150,
            bookings_this_month=5,
            revenue_earned_this_month_usd=250.00,
        )
        db_session.add(conn)
        db_session.commit()

        resp = client.get("/api/v1/network/stats")
        data = resp.get_json()
        assert data["connections"]["active"] == 1
        assert data["this_month"]["as_router"]["queries"] == 150
        assert data["this_month"]["as_router"]["revenue_usd"] == 250.00
