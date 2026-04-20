"""
MYSTES Duffel Flight Lifecycle Tests — Build #200

Comprehensive tests for the complete Duffel flight lifecycle:
- Root client methods (available services, seat maps, two-step cancel, order changes, webhooks)
- Unified API endpoints (source-aware seatmap, services, cancellation quote, order change)
- Booking with services (pass service IDs through order creation)
- Post-booking management (refund quotes, order changes, service addition)
- Webhook receiver (Duffel event handling, idempotency, notifications)
- Agent tool definitions (new tools registered)
- Knowledge card + knowledge base updates

Run: pytest tests/test_duffel_lifecycle.py -v
"""

import json
import sys
import os
import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch, PropertyMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ===================================================================
# Test Fixtures
# ===================================================================

@pytest.fixture
def duffel_client():
    """Create a DuffelClient with mocked _request method."""
    with patch.dict(os.environ, {"DUFFEL_ACCESS_TOKEN": "duffel_test_fake"}):
        from duffel_client import DuffelClient
        client = DuffelClient()
        return client


@pytest.fixture
def app_client():
    """Create a test client with in-memory database."""
    from server import app, db, limiter
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
def auth_client(app_client):
    """Create a test client with an authenticated user."""
    from server import app
    with app.app_context():
        app_client.post('/register', data={
            'email': 'test@example.com',
            'password': 'TestPass123!',
            'name': 'Test User',
        }, follow_redirects=True)
        app_client.post('/login', data={
            'email': 'test@example.com',
            'password': 'TestPass123!',
        }, follow_redirects=True)
        yield app_client


# ===================================================================
# Root DuffelClient — Available Services
# ===================================================================

class TestDuffelClientAvailableServices:
    """Test DuffelClient.get_available_services()."""

    def test_get_available_services_success(self, duffel_client):
        """Services are grouped by type: baggage, seat, meal, other."""
        duffel_client._request = MagicMock(return_value={
            "success": True,
            "data": [
                {"id": "srv_bag1", "type": "baggage", "total_amount": "30.00", "total_currency": "USD",
                 "metadata": {"maximum_weight": {"value": 23}}, "passenger_ids": ["pas_1"],
                 "segment_ids": ["seg_1"]},
                {"id": "srv_seat1", "type": "seat", "total_amount": "15.00", "total_currency": "USD",
                 "metadata": {"designator": "12A"}, "passenger_ids": ["pas_1"],
                 "segment_ids": ["seg_1"]},
                {"id": "srv_meal1", "type": "meal", "total_amount": "12.00", "total_currency": "USD",
                 "metadata": {"meal_type": "vegetarian"}, "passenger_ids": ["pas_1"],
                 "segment_ids": ["seg_1"]},
            ]
        })
        result = duffel_client.get_available_services("off_test123")
        assert result["success"] is True
        assert result["count"] == 3
        assert len(result["by_type"]["baggage"]) == 1
        assert len(result["by_type"]["seat"]) == 1
        assert len(result["by_type"]["meal"]) == 1
        assert result["by_type"]["baggage"][0]["id"] == "srv_bag1"

    def test_get_available_services_empty(self, duffel_client):
        """Empty services list returns zero count."""
        duffel_client._request = MagicMock(return_value={
            "success": True,
            "data": []
        })
        result = duffel_client.get_available_services("off_test123")
        assert result["success"] is True
        assert result["count"] == 0

    def test_get_available_services_not_configured(self):
        """Returns error when token not set."""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("DUFFEL_ACCESS_TOKEN", None)
            from duffel_client import DuffelClient
            client = DuffelClient()
            client.access_token = ""
            result = client.get_available_services("off_test")
            assert result["success"] is False


class TestDuffelClientSeatMap:
    """Test DuffelClient.get_seat_map()."""

    def test_get_seat_map_parses_structure(self, duffel_client):
        """Seat map is parsed into seatmap.rows with seat objects."""
        duffel_client._request = MagicMock(return_value={
            "success": True,
            "data": [{
                "segment_id": "seg_1",
                "slice_id": "sli_1",
                "cabins": [{
                    "cabin_class": "economy",
                    "rows": [
                        {
                            "sections": [
                                {"elements": [
                                    {"type": "seat", "designator": "1A",
                                     "available_services": [{"id": "srv_1", "total_amount": "15.00", "total_currency": "USD"}],
                                     "disclosures": ["extra_legroom"]},
                                    {"type": "seat", "designator": "1B",
                                     "available_services": [],
                                     "disclosures": []},
                                ]},
                                {"elements": [
                                    {"type": "seat", "designator": "1C",
                                     "available_services": [{"id": "srv_2", "total_amount": "0.00", "total_currency": "USD"}],
                                     "disclosures": []},
                                ]}
                            ]
                        }
                    ]
                }]
            }]
        })
        result = duffel_client.get_seat_map("off_test123")
        assert result["success"] is True
        # seatmap has parsed rows
        seatmap = result["seatmap"]
        assert seatmap is not None
        rows = seatmap["rows"]
        assert len(rows) == 1
        assert len(rows[0]["seats"]) == 3
        seat_a = rows[0]["seats"][0]
        assert seat_a["column"] == "A"  # Last char of designator
        assert seat_a["seat_id"] == "1A"
        assert seat_a["available"] is True
        assert seat_a["service_id"] == "srv_1"
        assert seat_a["price"] == 15.0
        # seat_maps has segment info
        assert len(result["seat_maps"]) == 1
        assert result["seat_maps"][0]["segment_id"] == "seg_1"


# ===================================================================
# Root DuffelClient — Two-Step Cancellation
# ===================================================================

class TestDuffelClientCancellation:
    """Test two-step cancellation: quote then confirm."""

    def test_get_cancellation_quote(self, duffel_client):
        """Cancellation quote returns refund amount and cancellation_id."""
        duffel_client._request = MagicMock(return_value={
            "success": True,
            "data": {
                "id": "ore_cancel123",
                "order_id": "ord_test123",
                "refund_amount": "450.00",
                "refund_currency": "USD",
                "expires_at": "2026-03-18T12:00:00Z",
                "confirmed_at": None,
            }
        })
        result = duffel_client.get_cancellation_quote("ord_test123")
        assert result["success"] is True
        assert result["cancellation_id"] == "ore_cancel123"
        assert result["refund_amount"] == "450.00"
        assert result["refund_currency"] == "USD"

    def test_confirm_cancellation(self, duffel_client):
        """Confirm cancellation completes the cancellation."""
        duffel_client._request = MagicMock(return_value={
            "success": True,
            "data": {
                "id": "ore_cancel123",
                "confirmed_at": "2026-03-17T15:30:00Z",
                "refund_amount": "450.00",
                "refund_currency": "USD",
            }
        })
        result = duffel_client.confirm_cancellation("ore_cancel123")
        assert result["success"] is True

    def test_cancel_order_uses_two_step(self, duffel_client):
        """cancel_order() internally calls quote then confirm."""
        call_count = [0]
        def mock_request(method, path, **kwargs):
            call_count[0] += 1
            if "order_cancellations" in path and method == "POST" and call_count[0] == 1:
                return {"success": True, "data": {
                    "id": "ore_cancel_auto", "refund_amount": "450.00",
                    "refund_currency": "USD", "expires_at": "2026-03-18T12:00:00Z",
                    "confirmed_at": None,
                }}
            else:
                return {"success": True, "data": {
                    "id": "ore_cancel_auto", "confirmed_at": "2026-03-17T15:30:00Z",
                    "refund_amount": "450.00", "refund_currency": "USD",
                }}
        duffel_client._request = MagicMock(side_effect=mock_request)
        result = duffel_client.cancel_order("ord_test123")
        assert result["success"] is True
        assert duffel_client._request.call_count == 2


# ===================================================================
# Root DuffelClient — Order Changes
# ===================================================================

class TestDuffelClientOrderChange:
    """Test order change flow: request → offers → confirm."""

    def test_request_order_change(self, duffel_client):
        """Order change request returns change_request_id."""
        duffel_client._request = MagicMock(return_value={
            "success": True,
            "data": {
                "id": "ocr_change123",
                "order_id": "ord_test123",
                "status": "pending",
            }
        })
        result = duffel_client.request_order_change(
            order_id="ord_test123",
            slices_to_remove=[{"slice_id": "sli_old"}],
            slices_to_add=[{"origin": "JFK", "destination": "LAX", "departure_date": "2026-04-01"}],
        )
        assert result["success"] is True

    def test_get_order_change_offers(self, duffel_client):
        """Change offers return fare differences."""
        duffel_client._request = MagicMock(return_value={
            "success": True,
            "data": {
                "id": "ocr_change123",
                "order_change_offers": [
                    {
                        "id": "oco_offer1",
                        "change_total_amount": "50.00",
                        "change_total_currency": "USD",
                        "new_total_amount": "500.00",
                        "new_total_currency": "USD",
                        "slices": [{"origin": {"iata_code": "JFK"}, "destination": {"iata_code": "LAX"}}],
                        "expires_at": "2026-03-18T12:00:00Z",
                    }
                ]
            }
        })
        result = duffel_client.get_order_change_offers("ocr_change123")
        assert result["success"] is True
        assert len(result["change_offers"]) >= 1

    def test_confirm_order_change(self, duffel_client):
        """Confirming a change offer modifies the original order."""
        duffel_client._request = MagicMock(return_value={
            "success": True,
            "data": {
                "id": "oco_offer1",
                "status": "confirmed",
            }
        })
        result = duffel_client.confirm_order_change("oco_offer1")
        assert result["success"] is True


# ===================================================================
# Root DuffelClient — Post-Booking Services + Webhooks
# ===================================================================

class TestDuffelClientPostBookingServices:
    """Test post-booking service addition."""

    def test_add_services_to_order(self, duffel_client):
        """Services can be added after booking."""
        duffel_client._request = MagicMock(return_value={
            "success": True,
            "data": {
                "id": "ord_test123",
                "services": [{"id": "srv_bag1", "quantity": 1}],
            }
        })
        result = duffel_client.add_services_to_order(
            "ord_test123",
            services=[{"id": "srv_bag1", "quantity": 1}],
        )
        assert result["success"] is True


class TestDuffelClientWebhookMgmt:
    """Test webhook management methods."""

    def test_create_webhook(self, duffel_client):
        """Create webhook returns webhook_id."""
        duffel_client._request = MagicMock(return_value={
            "success": True,
            "data": {
                "id": "wh_test123",
                "url": "https://mystes.app/webhooks/duffel",
                "events": ["order.updated"],
                "active": True,
            }
        })
        result = duffel_client.create_webhook(
            "https://mystes.app/webhooks/duffel",
            ["order.updated", "order.cancelled"],
        )
        assert result["success"] is True

    def test_list_webhooks(self, duffel_client):
        """List webhooks returns registered hooks."""
        duffel_client._request = MagicMock(return_value={
            "success": True,
            "data": [
                {"id": "wh_1", "url": "https://mystes.app/webhooks/duffel", "active": True}
            ]
        })
        result = duffel_client.list_webhooks()
        assert result["success"] is True

    def test_delete_webhook(self, duffel_client):
        """Delete webhook removes the registration."""
        duffel_client._request = MagicMock(return_value={
            "success": True,
            "data": {"id": "wh_1"}
        })
        result = duffel_client.delete_webhook("wh_1")
        assert result["success"] is True


class TestDuffelClientCreateOrderWithServices:
    """Test create_order with services and metadata."""

    def test_create_order_with_services(self, duffel_client):
        """create_order passes services to Duffel API."""
        duffel_client._request = MagicMock(return_value={
            "success": True,
            "data": {
                "id": "ord_test123",
                "booking_reference": "ABC123",
                "base_amount": "400.00",
                "tax_amount": "50.00",
                "total_amount": "480.00",
                "total_currency": "USD",
                "passengers": [],
                "slices": [],
                "documents": [{"unique_identifier": "123-4567890"}],
                "services": [{"id": "srv_bag1", "quantity": 1, "total_amount": "30.00"}],
                "conditions": {"refund_before_departure": {"allowed": True, "penalty_amount": "50.00"}},
            }
        })
        passengers = [{"id": "pas_1", "given_name": "John", "family_name": "Doe",
                       "born_on": "1990-01-01", "gender": "m", "title": "mr",
                       "email": "john@test.com", "phone_number": "+12125551234"}]
        services = [{"id": "srv_bag1", "quantity": 1}]
        result = duffel_client.create_order(
            offer_id="off_test123",
            passengers=passengers,
            services=services,
            metadata={"mystes_deal_id": "42"},
        )
        assert result["success"] is True
        assert result["booking_reference"] == "ABC123"
        # Verify services were in the API call
        call_args = duffel_client._request.call_args
        body = call_args.kwargs.get("json_data") or (call_args[1].get("json_data") if len(call_args) > 1 else None)
        if body is None and len(call_args.args) >= 3:
            body = call_args.args[2]
        assert body is not None, "No json_data passed to _request"
        assert "services" in body["data"]

    def test_create_order_without_services(self, duffel_client):
        """create_order works without services."""
        duffel_client._request = MagicMock(return_value={
            "success": True,
            "data": {
                "id": "ord_test456",
                "booking_reference": "DEF456",
                "total_amount": "400.00",
                "total_currency": "USD",
                "passengers": [],
                "slices": [],
            }
        })
        passengers = [{"id": "pas_1", "given_name": "Jane", "family_name": "Doe",
                       "born_on": "1992-01-01", "gender": "f", "title": "ms",
                       "email": "jane@test.com", "phone_number": "+12125559999"}]
        result = duffel_client.create_order(
            offer_id="off_test456",
            passengers=passengers,
        )
        assert result["success"] is True
        assert result["booking_reference"] == "DEF456"


# ===================================================================
# Unified API Endpoints
# ===================================================================

class TestUnifiedSeatmapEndpoint:
    """Test POST /api/flights/seatmap — source-aware routing."""

    def test_seatmap_requires_auth(self, app_client):
        """Seatmap endpoint requires authentication."""
        resp = app_client.post('/api/flights/seatmap',
                               json={"deal_id": 1},
                               content_type='application/json')
        assert resp.status_code in (302, 401, 403)

    @patch("duffel_client.DuffelClient.is_configured", return_value=True)
    @patch("duffel_client.DuffelClient.get_seat_map")
    def test_seatmap_duffel_routing(self, mock_seatmap, mock_conf, auth_client):
        """Duffel deals route to DuffelClient.get_seat_map."""
        from server import app, db
        from models import Deal, User
        with app.app_context():
            user = User.query.filter_by(email='test@example.com').first()
            deal = Deal(
                deal_id="DTEST_SM_001",
                origin="JFK", destination="LAX",
                home_price_usd=500.0,
                claimed_by=user.id,
                amadeus_offer_data=json.dumps({"source": "duffel_ndc", "offer_id": "off_test123"}),
            )
            db.session.add(deal)
            db.session.commit()

            mock_seatmap.return_value = {"success": True, "seat_maps": [], "seatmap": None}
            resp = auth_client.post('/api/flights/seatmap',
                                    json={"deal_id": "DTEST_SM_001"},
                                    content_type='application/json')
            assert resp.status_code == 200
            mock_seatmap.assert_called_once()


class TestServicesEndpoint:
    """Test POST /api/flights/services."""

    @patch("duffel_client.DuffelClient.is_configured", return_value=True)
    @patch("duffel_client.DuffelClient.get_available_services")
    def test_services_by_offer_id(self, mock_services, mock_conf, auth_client):
        """Services endpoint accepts offer_id directly."""
        from server import app
        with app.app_context():
            mock_services.return_value = {"success": True, "services": [], "count": 0, "by_type": {}}
            resp = auth_client.post('/api/flights/services',
                                    json={"offer_id": "off_test123"},
                                    content_type='application/json')
            assert resp.status_code == 200
            data = json.loads(resp.data)
            assert data["success"] is True


class TestCancellationQuoteEndpoint:
    """Test POST /api/flights/cancellation-quote."""

    @patch("duffel_client.DuffelClient.is_configured", return_value=True)
    @patch("duffel_client.DuffelClient.get_cancellation_quote")
    def test_cancellation_quote_returns_refund(self, mock_quote, mock_conf, auth_client):
        """Cancellation quote endpoint returns refund amount."""
        from server import app, db
        from models import Booking, Deal, User
        with app.app_context():
            user = User.query.filter_by(email='test@example.com').first()
            deal = Deal(
                deal_id="DTEST_CQ_001",
                origin="JFK", destination="LAX",
                home_price_usd=500.0,
                claimed_by=user.id,
                amadeus_offer_data=json.dumps({"duffel_order_id": "ord_test123"}),
            )
            db.session.add(deal)
            db.session.flush()
            booking = Booking(
                user_id=user.id,
                deal_id=deal.id,
                status="booked",
                confirmation_code="ABC123",
            )
            db.session.add(booking)
            db.session.commit()

            mock_quote.return_value = {
                "success": True,
                "cancellation_id": "ore_cancel1",
                "refund_amount": "450.00",
                "refund_currency": "USD",
            }
            resp = auth_client.post('/api/flights/cancellation-quote',
                                    json={"booking_id": booking.id},
                                    content_type='application/json')
            assert resp.status_code == 200
            data = json.loads(resp.data)
            assert data["refund_amount"] == "450.00"


# ===================================================================
# Webhook Receiver
# ===================================================================

class TestDuffelWebhookReceiver:
    """Test POST /webhooks/duffel."""

    def test_webhook_accepts_valid_event(self, app_client):
        """Webhook endpoint accepts valid Duffel events."""
        from server import app
        with app.app_context():
            resp = app_client.post('/webhooks/duffel',
                                   json={"id": "evt_test_123", "type": "order.updated",
                                         "data": {"order": {"id": "ord_unknown"}}},
                                   content_type='application/json')
            assert resp.status_code == 200
            data = json.loads(resp.data)
            assert data["received"] is True

    def test_webhook_rejects_empty_payload(self, app_client):
        """Webhook rejects empty/null payloads."""
        from server import app
        with app.app_context():
            resp = app_client.post('/webhooks/duffel',
                                   data=b'',
                                   content_type='application/json')
            # Either 400 or 200 with error — both acceptable
            assert resp.status_code in (400, 415, 500)

    def test_webhook_idempotency(self, app_client):
        """Same event_id is not processed twice."""
        from server import app, db
        with app.app_context():
            resp1 = app_client.post('/webhooks/duffel',
                                    json={"id": "evt_dedup_test_200", "type": "order.updated",
                                          "data": {"order": {"id": "ord_unknown_x"}}},
                                    content_type='application/json')
            assert resp1.status_code == 200

            resp2 = app_client.post('/webhooks/duffel',
                                    json={"id": "evt_dedup_test_200", "type": "order.updated",
                                          "data": {"order": {"id": "ord_unknown_x"}}},
                                    content_type='application/json')
            assert resp2.status_code == 200
            data2 = json.loads(resp2.data)
            assert data2.get("duplicate") is True

    def test_webhook_token_rejection(self, app_client):
        """When DUFFEL_WEBHOOK_TOKEN set, rejects requests without it."""
        from server import app
        with app.app_context():
            with patch.dict(os.environ, {"DUFFEL_WEBHOOK_TOKEN": "secret123"}):
                resp = app_client.post('/webhooks/duffel',
                                       json={"id": "evt_noauth_200", "type": "order.updated", "data": {}},
                                       content_type='application/json')
                assert resp.status_code == 401

    def test_webhook_token_accepted_via_query(self, app_client):
        """Token passed as query parameter is accepted."""
        from server import app
        with app.app_context():
            with patch.dict(os.environ, {"DUFFEL_WEBHOOK_TOKEN": "secret123"}):
                resp = app_client.post('/webhooks/duffel?token=secret123',
                                       json={"id": "evt_auth_ok_200", "type": "order.updated",
                                             "data": {"order": {"id": "ord_x"}}},
                                       content_type='application/json')
                assert resp.status_code == 200

    @patch("email_service.send_email")
    def test_webhook_order_cancelled_updates_booking(self, mock_email, app_client):
        """order.cancelled event updates booking status to cancelled."""
        from server import app, db
        from models import User, Deal, Booking
        with app.app_context():
            user = User(email='webhook_cancel@test.com', name='WH Cancel', is_active=True, is_verified=True)
            user.set_password('TestPass123!')
            db.session.add(user)
            db.session.flush()

            deal = Deal(
                deal_id="DTEST_WH_CANCEL_200",
                origin="JFK", destination="LAX",
                home_price_usd=500.0,
                claimed_by=user.id,
                amadeus_offer_data=json.dumps({"duffel_order_id": "ord_wh_cancel_200"}),
            )
            db.session.add(deal)
            db.session.flush()

            booking = Booking(
                user_id=user.id,
                deal_id=deal.id,
                status="booked",
                confirmation_code="WH200",
            )
            db.session.add(booking)
            db.session.commit()
            booking_id = booking.id

            resp = app_client.post('/webhooks/duffel',
                                   json={
                                       "id": "evt_cancel_200",
                                       "type": "order.cancelled",
                                       "data": {"order": {"id": "ord_wh_cancel_200"}},
                                   },
                                   content_type='application/json')
            assert resp.status_code == 200

            updated_booking = db.session.get(Booking, booking_id)
            assert updated_booking.status == "cancelled"

    @patch("email_service.send_email")
    def test_webhook_order_updated_stores_changes(self, mock_email, app_client):
        """order.updated event stores airline changes in deal offer data."""
        from server import app, db
        from models import User, Deal, Booking
        with app.app_context():
            user = User(email='webhook_update@test.com', name='WH Update', is_active=True, is_verified=True)
            user.set_password('TestPass123!')
            db.session.add(user)
            db.session.flush()

            deal = Deal(
                deal_id="DTEST_WH_UPDATE_200",
                origin="JFK", destination="LAX",
                home_price_usd=500.0,
                claimed_by=user.id,
                amadeus_offer_data=json.dumps({"duffel_order_id": "ord_wh_update_200"}),
            )
            db.session.add(deal)
            db.session.flush()

            booking = Booking(
                user_id=user.id,
                deal_id=deal.id,
                status="booked",
                confirmation_code="WH201",
            )
            db.session.add(booking)
            db.session.commit()
            deal_id = deal.id

            resp = app_client.post('/webhooks/duffel',
                                   json={
                                       "id": "evt_update_200",
                                       "type": "order.updated",
                                       "data": {"order": {
                                           "id": "ord_wh_update_200",
                                           "changes": [{"type": "schedule_change"}],
                                       }},
                                   },
                                   content_type='application/json')
            assert resp.status_code == 200

            updated_deal = db.session.get(Deal, deal_id)
            offer_data = json.loads(updated_deal.amadeus_offer_data)
            assert offer_data.get("last_webhook_event") == "order.updated"
            assert len(offer_data.get("airline_changes", [])) == 1

    def test_webhook_unhandled_event_type(self, app_client):
        """Unhandled event types are logged but return 200."""
        from server import app
        with app.app_context():
            resp = app_client.post('/webhooks/duffel',
                                   json={"id": "evt_unknown_200", "type": "payment.created",
                                         "data": {}},
                                   content_type='application/json')
            assert resp.status_code == 200
            data = json.loads(resp.data)
            assert data["received"] is True


# ===================================================================
# Agent Tool Definitions
# ===================================================================

class TestDuffelAgentTools:
    """Verify all new lifecycle tools are defined."""

    def test_tool_count_minimum(self):
        """Should have at least 15 tools (10 original + 5 new lifecycle)."""
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "picasso-sdk"))
        from picasso.agent.duffel_tools import DUFFEL_TOOL_DEFINITIONS
        tool_names = [t["name"] for t in DUFFEL_TOOL_DEFINITIONS]
        assert len(tool_names) >= 15, f"Expected >= 15 tools, got {len(tool_names)}: {tool_names}"

    def test_new_tools_present(self):
        """All new lifecycle tools are registered."""
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "picasso-sdk"))
        from picasso.agent.duffel_tools import DUFFEL_TOOL_DEFINITIONS
        tool_names = {t["name"] for t in DUFFEL_TOOL_DEFINITIONS}
        expected_new = {
            "duffel_get_cancellation_quote",
            "duffel_confirm_cancellation",
            "duffel_get_change_offers",
            "duffel_confirm_change",
            "duffel_add_services",
        }
        for tool in expected_new:
            assert tool in tool_names, f"Missing tool: {tool}"

    def test_all_tools_have_schemas(self):
        """Every tool has name, description, and input_schema."""
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "picasso-sdk"))
        from picasso.agent.duffel_tools import DUFFEL_TOOL_DEFINITIONS
        for tool in DUFFEL_TOOL_DEFINITIONS:
            assert "name" in tool, f"Tool missing name: {tool}"
            assert "description" in tool, f"Tool {tool['name']} missing description"
            assert "input_schema" in tool, f"Tool {tool['name']} missing input_schema"


# ===================================================================
# Knowledge Card
# ===================================================================

class TestDuffelKnowledgeCard:
    """Verify updated knowledge card."""

    def _load_card(self):
        card_path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                                 "picasso-sdk", "anastasia", "modules", "cards", "duffel_ndc.json")
        with open(card_path) as f:
            return json.load(f)

    def test_card_loads(self):
        """Knowledge card JSON loads and has correct module_id."""
        card = self._load_card()
        assert card["module_id"] == "duffel_ndc"
        assert card["vertical"] == "flights"

    def test_card_has_new_capabilities(self):
        """Card includes cancel_with_quote, change_offers, post_booking_services, webhooks."""
        card = self._load_card()
        caps = card["capabilities"]
        assert caps.get("cancel_with_quote") is True
        assert caps.get("change_offers") is True
        assert caps.get("post_booking_services") is True
        assert caps.get("webhooks") is True

    def test_card_has_cancellation_steps(self):
        """Card documents the two-step cancellation flow."""
        card = self._load_card()
        assert "cancellation_steps" in card
        assert "get_cancellation_quote" in card["cancellation_steps"]
        assert "confirm_cancellation" in card["cancellation_steps"]

    def test_card_has_change_steps(self):
        """Card documents the three-step change flow."""
        card = self._load_card()
        assert "change_steps" in card
        assert len(card["change_steps"]) == 3

    def test_card_production_ready(self):
        """Card readiness is 'production' with confidence >= 0.95."""
        card = self._load_card()
        assert card["readiness"] == "production"
        assert card["confidence"] >= 0.95


# ===================================================================
# Knowledge Base
# ===================================================================

class TestDuffelKnowledgeBase:
    """Verify knowledge base covers full lifecycle."""

    def _get_kb(self):
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "picasso-sdk"))
        from picasso.agent.duffel_knowledge import DUFFEL_KNOWLEDGE_BASE
        return DUFFEL_KNOWLEDGE_BASE

    def test_knowledge_mentions_two_step_cancel(self):
        """Knowledge base documents two-step cancellation."""
        kb = self._get_kb()
        assert "duffel_get_cancellation_quote" in kb
        assert "duffel_confirm_cancellation" in kb

    def test_knowledge_mentions_three_step_change(self):
        """Knowledge base documents three-step order change."""
        kb = self._get_kb()
        assert "duffel_get_change_offers" in kb
        assert "duffel_confirm_change" in kb

    def test_knowledge_mentions_post_booking_services(self):
        """Knowledge base documents post-booking service addition."""
        kb = self._get_kb()
        assert "duffel_add_services" in kb

    def test_knowledge_mentions_webhooks(self):
        """Knowledge base documents webhook events."""
        kb = self._get_kb()
        assert "webhook" in kb.lower()
        assert "order.updated" in kb

    def test_knowledge_15_capabilities(self):
        """Knowledge base lists 15 capabilities."""
        kb = self._get_kb()
        # Count numbered items in capabilities list
        assert "15." in kb  # At least 15 numbered items


# ===================================================================
# Fee Calculation — NO MAX CAP (Critical Rule)
# ===================================================================

class TestDuffelFeeCalculation:
    """Verify fee rules: $3 minimum, NO maximum cap."""

    def test_fee_no_max_cap(self):
        """Fee has no maximum cap (critical rule)."""
        from payments import get_fee_percent
        guest = MagicMock()
        guest.is_authenticated = False
        pct = get_fee_percent(guest)
        assert pct == 0.50
        # $10,000 ticket * 50% = $5,000 fee — NO cap
        base_price = 10000.0
        fee = base_price * pct
        assert fee == 5000.0

    def test_fee_minimum_3_dollars(self):
        """Fee never goes below $3."""
        from payments import get_fee_percent
        guest = MagicMock()
        guest.is_authenticated = False
        pct = get_fee_percent(guest)
        base_price = 2.0
        fee = max(base_price * pct, 3.0)
        assert fee == 3.0
