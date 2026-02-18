"""
MYSTES P2P System Tests

Tests for the P2P orchestrator, escrow calculations, helper matching,
and browser control protocol.

Run: pytest tests/test_p2p.py -v
"""

import json
import sys
import os
import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from payments import calculate_p2p_amounts, create_p2p_escrow, P2P_FEE_CONFIG
from p2p_orchestrator import P2POrchestrator, P2PWorkflowStatus

# browser_control was removed in Build #89 — import conditionally
try:
    from browser_control import (
        BrowserControlServer, BrowserSession, BrowserCommand,
        CommandResponse, MessageProtocol, CommandType, SessionStatus
    )
    HAS_BROWSER_CONTROL = True
except ImportError:
    HAS_BROWSER_CONTROL = False


# ===================================================================
# Test Fixtures / Helpers
# ===================================================================

def _make_mock_helper(id=1, user_id=50, country_code="GB", is_active=True,
                      is_approved=True, transactions_today=0,
                      max_daily_transactions=10, average_rating=4.8,
                      successful_transactions=5, total_earned_rlusd=100.0):
    h = MagicMock()
    h.id = id
    h.user_id = user_id
    h.country_code = country_code
    h.is_active = is_active
    h.is_approved = is_approved
    h.transactions_today = transactions_today
    h.max_daily_transactions = max_daily_transactions
    h.average_rating = average_rating
    h.successful_transactions = successful_transactions
    h.total_earned_rlusd = total_earned_rlusd
    h.failed_transactions = 1
    h.total_transactions = successful_transactions + 1
    h.user = MagicMock(email="helper@example.com")
    return h


def _make_mock_transaction(status="requested", target_market="GB",
                           helper_id=None, browser_session_id=None):
    t = MagicMock()
    t.transaction_id = "p2p_abc123"
    t.status = status
    t.target_market = target_market
    t.helper_id = helper_id
    t.browser_session_id = browser_session_id
    t.buyer_id = 1
    t.origin = "JFK"
    t.destination = "LHR"
    t.target_price_usd = 600.0
    t.us_price_usd = 800.0
    t.savings_usd = 200.0
    t.escrow_amount_rlusd = 648.0
    t.created_at = datetime.utcnow()
    t.matched_at = None
    t.escrow_locked_at = None
    return t


def _make_mock_escrow(status="pending"):
    e = MagicMock()
    e.escrow_id = "esc_abc123"
    e.status = status
    e.total_rlusd = 648.0
    e.helper_amount_rlusd = 630.0
    e.platform_amount_rlusd = 18.0
    return e


def _make_mock_wallet(user_id=50):
    w = MagicMock()
    w.user_id = user_id
    w.wallet_address = "rTestWallet123"
    return w


def _make_mock_card(user_id=50):
    c = MagicMock()
    c.user_id = user_id
    c.card_last_four = "1234"
    c.is_active = True
    return c


# ===================================================================
# 1. TestP2PAmounts
# ===================================================================

class TestP2PAmounts:

    def test_standard_ticket_price(self):
        result = calculate_p2p_amounts(600.0)
        assert result["ticket_price_usd"] == 600.0
        assert result["helper_reimbursement"] == 600.0
        assert result["helper_earning"] == 30.0  # 5% of 600
        assert result["platform_fee"] == 18.0  # 3% of 600
        assert result["helper_total"] == 630.0
        assert result["total_escrow_rlusd"] == 648.0

    def test_helper_gets_reimbursement_plus_five_percent(self):
        for price in [200, 500, 1000, 2500]:
            r = calculate_p2p_amounts(float(price))
            expected_cut = max(price * 0.05, P2P_FEE_CONFIG["min_helper_earning_usd"])
            assert r["helper_total"] == round(price + expected_cut, 2)

    def test_platform_gets_three_percent(self):
        for price in [100, 350, 999.99]:
            r = calculate_p2p_amounts(price)
            assert r["platform_fee"] == round(price * 0.03, 2)

    def test_total_escrow_equals_sum(self):
        r = calculate_p2p_amounts(450.0)
        assert r["total_escrow_rlusd"] == pytest.approx(
            r["helper_reimbursement"] + r["helper_earning"] + r["platform_fee"]
        )

    def test_minimum_helper_earning(self):
        r = calculate_p2p_amounts(50.0)
        assert r["helper_earning"] == P2P_FEE_CONFIG["min_helper_earning_usd"]

    def test_very_small_amount(self):
        r = calculate_p2p_amounts(1.0)
        assert r["helper_earning"] == P2P_FEE_CONFIG["min_helper_earning_usd"]
        assert r["platform_fee"] == round(1.0 * 0.03, 2)
        assert r["total_escrow_rlusd"] > 0

    def test_very_large_amount(self):
        r = calculate_p2p_amounts(15000.0)
        assert r["helper_earning"] == 750.0
        assert r["platform_fee"] == 450.0
        assert r["total_escrow_rlusd"] == 16200.0

    def test_all_values_rounded(self):
        r = calculate_p2p_amounts(333.33)
        for key in ("ticket_price_usd", "helper_reimbursement",
                     "helper_earning", "helper_total",
                     "platform_fee", "total_escrow_rlusd"):
            val = r[key]
            assert val == round(val, 2), f"{key} not rounded: {val}"

    def test_zero_price(self):
        r = calculate_p2p_amounts(0.0)
        assert r["helper_earning"] == P2P_FEE_CONFIG["min_helper_earning_usd"]
        assert r["platform_fee"] == 0.0


# ===================================================================
# 2. TestP2POrchestrator
# ===================================================================

class TestP2POrchestrator:

    def _make_orchestrator(self):
        db = MagicMock()
        return P2POrchestrator(db), db

    @patch("payments.calculate_p2p_amounts")
    @patch("models.P2PTransaction")
    def test_initiate_creates_record(self, MockTxn, mock_calc):
        mock_calc.return_value = {
            "total_escrow_rlusd": 648.0,
            "helper_reimbursement": 600.0,
            "helper_earning": 30.0,
            "platform_fee": 18.0,
        }
        mock_instance = MagicMock()
        mock_instance.savings_usd = 200.0
        MockTxn.return_value = mock_instance
        orch, db = self._make_orchestrator()
        result = orch.initiate_transaction(
            buyer_id=10, origin="JFK", destination="LHR",
            departure_date="2026-06-15", airline="BA",
            flight_number="BA178", us_price_usd=800.0,
            target_price_usd=600.0, target_price_local=480.0,
            target_currency="GBP", target_market="GB",
        )
        assert result["success"] is True
        assert result["status"] == "requested"
        db.add.assert_called_once()
        db.commit.assert_called_once()

    @patch("models.P2PTransaction")
    def test_match_not_found(self, MockTxn):
        MockTxn.query.filter_by.return_value.first.return_value = None
        orch, _ = self._make_orchestrator()
        result = orch.match_helper("nonexistent")
        assert result["success"] is False

    @patch("models.P2PTransaction")
    def test_match_wrong_status(self, MockTxn):
        txn = _make_mock_transaction(status="completed")
        MockTxn.query.filter_by.return_value.first.return_value = txn
        orch, _ = self._make_orchestrator()
        result = orch.match_helper("p2p_abc123")
        assert result["success"] is False

    @patch.dict("sys.modules", {"browser_control": MagicMock()})
    @patch("models.HelperProfile")
    @patch("models.P2PEscrow")
    @patch("models.P2PTransaction")
    def test_fail_transaction(self, MockTxn, MockEscrow, MockHelper):
        txn = _make_mock_transaction(status="purchasing", helper_id=100,
                                     browser_session_id="bcs_test")
        MockTxn.query.filter_by.return_value.first.return_value = txn
        escrow = _make_mock_escrow(status="locked")
        MockEscrow.query.filter_by.return_value.first.return_value = escrow
        MockHelper.query.get.return_value = _make_mock_helper()
        orch, db = self._make_orchestrator()
        result = orch.fail_transaction("p2p_abc123", "Browser disconnected")
        assert result["success"] is True
        assert txn.status == "failed"
        assert escrow.status == "cancelled"

    @patch("models.P2PEscrow")
    @patch("models.P2PTransaction")
    def test_cancel_before_purchase(self, MockTxn, MockEscrow):
        txn = _make_mock_transaction(status="matched")
        MockTxn.query.filter_by.return_value.first.return_value = txn
        MockEscrow.query.filter_by.return_value.first.return_value = None
        orch, db = self._make_orchestrator()
        result = orch.cancel_transaction("p2p_abc123", cancelled_by="buyer")
        assert result["success"] is True
        assert txn.status == "cancelled"

    @patch("models.P2PTransaction")
    def test_cancel_after_purchase_fails(self, MockTxn):
        txn = _make_mock_transaction(status="purchasing")
        MockTxn.query.filter_by.return_value.first.return_value = txn
        orch, _ = self._make_orchestrator()
        result = orch.cancel_transaction("p2p_abc123")
        assert result["success"] is False

    @patch("models.P2PTransaction")
    def test_cancel_nonexistent(self, MockTxn):
        MockTxn.query.filter_by.return_value.first.return_value = None
        orch, _ = self._make_orchestrator()
        assert orch.cancel_transaction("nope")["success"] is False

    @patch.dict("sys.modules", {"browser_control": MagicMock()})
    @patch("models.P2PTransaction")
    def test_fail_nonexistent(self, MockTxn):
        MockTxn.query.filter_by.return_value.first.return_value = None
        orch, _ = self._make_orchestrator()
        assert orch.fail_transaction("nope", "r")["success"] is False


# ===================================================================
# 3. TestBrowserControl
# ===================================================================

@pytest.mark.skipif(not HAS_BROWSER_CONTROL, reason="browser_control module removed in Build #89")
class TestBrowserControl:

    def test_create_session(self):
        srv = BrowserControlServer()
        s = srv.create_session("tx1", helper_id=5, helper_address="rA")
        assert s.session_id.startswith("bcs_")
        assert s.transaction_id == "tx1"
        assert s.status == SessionStatus.PENDING.value
        assert s.session_id in srv.sessions

    def test_auth_token_maps(self):
        srv = BrowserControlServer()
        s = srv.create_session("tx1", 1, "rA")
        assert srv.auth_tokens[s.auth_token] == s.session_id

    def test_authenticate_valid(self):
        srv = BrowserControlServer()
        s = srv.create_session("tx1", 1, "rA")
        a = srv.authenticate_connection(s.auth_token)
        assert a is not None
        assert a.status == SessionStatus.CONNECTED.value

    def test_authenticate_invalid(self):
        assert BrowserControlServer().authenticate_connection("bad") is None

    def test_authenticate_expired(self):
        srv = BrowserControlServer()
        s = srv.create_session("tx1", 1, "rA")
        s.token_expires_at = (datetime.utcnow() - timedelta(minutes=1)).isoformat()
        assert srv.authenticate_connection(s.auth_token) is None
        assert s.status == SessionStatus.TIMED_OUT.value

    def test_authenticate_already_connected(self):
        srv = BrowserControlServer()
        s = srv.create_session("tx1", 1, "rA")
        srv.authenticate_connection(s.auth_token)
        assert srv.authenticate_connection(s.auth_token) is None

    def test_create_command_active(self):
        srv = BrowserControlServer()
        s = srv.create_session("tx1", 1, "rA")
        srv.authenticate_connection(s.auth_token)
        cmd = srv.create_command(s.session_id, CommandType.NAVIGATE.value,
                                 {"url": "https://example.com"})
        assert cmd is not None
        assert s.commands_sent == 1
        assert s.status == SessionStatus.ACTIVE.value

    def test_create_command_inactive_none(self):
        srv = BrowserControlServer()
        s = srv.create_session("tx1", 1, "rA")
        assert srv.create_command(s.session_id, "click", {"sel": "#x"}) is None

    def test_handle_response_success(self):
        srv = BrowserControlServer()
        s = srv.create_session("tx1", 1, "rA")
        srv.authenticate_connection(s.auth_token)
        cmd = srv.create_command(s.session_id, CommandType.NAVIGATE.value, {"url": "u"})
        srv.handle_response(s.session_id, CommandResponse(
            command_id=cmd.command_id, success=True, data={"url": "u"}
        ))
        assert s.commands_completed == 1

    def test_handle_response_failure(self):
        srv = BrowserControlServer()
        s = srv.create_session("tx1", 1, "rA")
        srv.authenticate_connection(s.auth_token)
        cmd = srv.create_command(s.session_id, "click", {"sel": "#x"})
        srv.handle_response(s.session_id, CommandResponse(
            command_id=cmd.command_id, success=False, error="Not found"
        ))
        assert s.commands_failed == 1

    def test_complete_session(self):
        srv = BrowserControlServer()
        s = srv.create_session("tx1", 1, "rA")
        srv.authenticate_connection(s.auth_token)
        srv.complete_session(s.session_id, confirmation_code="ABC123")
        assert s.status == SessionStatus.COMPLETED.value
        assert s.confirmation_code == "ABC123"

    def test_fail_session(self):
        srv = BrowserControlServer()
        s = srv.create_session("tx1", 1, "rA")
        srv.fail_session(s.session_id, "err")
        assert s.status == SessionStatus.FAILED.value

    def test_cancel_removes_token(self):
        srv = BrowserControlServer()
        s = srv.create_session("tx1", 1, "rA")
        tok = s.auth_token
        srv.cancel_session(s.session_id)
        assert s.status == SessionStatus.CANCELLED.value
        assert tok not in srv.auth_tokens

    def test_ping(self):
        srv = BrowserControlServer()
        s = srv.create_session("tx1", 1, "rA")
        pong = srv.handle_ping(s.session_id)
        assert pong["type"] == "pong"

    def test_ping_unknown(self):
        assert BrowserControlServer().handle_ping("x")["status"] == "unknown"

    # MessageProtocol tests

    def test_auth_request_msg(self):
        msg = json.loads(MessageProtocol.auth_request("tok"))
        assert msg["type"] == "auth" and msg["token"] == "tok"

    def test_auth_response_ok(self):
        msg = json.loads(MessageProtocol.auth_response(True, session_id="s1"))
        assert msg["success"] is True and msg["session_id"] == "s1"

    def test_auth_response_fail(self):
        msg = json.loads(MessageProtocol.auth_response(False, error="bad"))
        assert msg["success"] is False and msg["error"] == "bad"

    def test_command_msg(self):
        cmd = BrowserCommand(command_id="c1", command_type="navigate",
                             params={"url": "u"}, timeout_ms=5000)
        msg = json.loads(MessageProtocol.command_message(cmd))
        assert msg["type"] == "command" and msg["command"] == "navigate"

    def test_response_msg(self):
        msg = json.loads(MessageProtocol.response_message(
            "c1", True, data={"ok": 1}, execution_time_ms=42
        ))
        assert msg["success"] is True and msg["execution_time_ms"] == 42

    def test_ping_pong_msgs(self):
        assert json.loads(MessageProtocol.ping_message())["type"] == "ping"
        p = json.loads(MessageProtocol.pong_message(session_status="active"))
        assert p["type"] == "pong" and p["session_status"] == "active"

    def test_parse_valid(self):
        assert MessageProtocol.parse_message('{"type":"ping"}')["type"] == "ping"

    def test_parse_invalid(self):
        assert MessageProtocol.parse_message("bad")["type"] == "error"

    def test_status_msg(self):
        msg = json.loads(MessageProtocol.status_message("s1", "completed", {"code": "X"}))
        assert msg["type"] == "status" and msg["details"]["code"] == "X"

    def test_error_msg(self):
        msg = json.loads(MessageProtocol.error_message("broke", fatal=True))
        assert msg["fatal"] is True

    def test_cmd_auto_id(self):
        cmd = BrowserCommand(command_id="", command_type="nav", params={})
        assert cmd.command_id.startswith("cmd_")

    def test_resp_from_message(self):
        r = CommandResponse.from_message({"command_id": "c", "success": True, "data": {"a": 1}})
        assert r.success is True and r.data["a"] == 1

    def test_session_is_active_states(self):
        s = BrowserSession(session_id="s", transaction_id="t", helper_id=1, helper_address="r")
        for st, exp in [("connected", True), ("active", True), ("paused", True),
                        ("completed", False), ("failed", False)]:
            s.status = st
            assert s.is_active() is exp, f"status={st}"

    def test_session_expiry(self):
        s = BrowserSession(session_id="s", transaction_id="t", helper_id=1,
                           helper_address="r", timeout_minutes=30)
        assert s.is_expired() is False
        s.token_expires_at = (datetime.utcnow() - timedelta(minutes=5)).isoformat()
        assert s.is_expired() is True


# ===================================================================
# 4. TestEscrowCalculations
# ===================================================================

class TestEscrowCalculations:

    def test_three_way_split(self):
        r = calculate_p2p_amounts(500.0)
        assert r["total_escrow_rlusd"] == pytest.approx(r["helper_total"] + r["platform_fee"])

    def test_rlusd_one_to_one(self):
        r = calculate_p2p_amounts(750.0)
        assert r["total_escrow_rlusd"] == r["helper_total"] + r["platform_fee"]

    def test_create_escrow_structure(self):
        a = calculate_p2p_amounts(400.0)
        r = create_p2p_escrow("rB", "rH", a)
        assert r["total_rlusd"] == a["total_escrow_rlusd"]
        assert r["helper_amount_rlusd"] == a["helper_total"]
        assert r["platform_amount_rlusd"] == a["platform_fee"]
        assert r["status"] == "pending"

    def test_condition_fulfillment_hex(self):
        r = create_p2p_escrow("rB", "rH", calculate_p2p_amounts(300.0))
        assert len(r["condition"]) == 64
        assert len(r["fulfillment"]) == 64

    def test_cancel_after_future(self):
        r = create_p2p_escrow("rB", "rH", calculate_p2p_amounts(200.0))
        assert datetime.fromisoformat(r["cancel_after"]) > datetime.utcnow()

    def test_helper_amount(self):
        r = create_p2p_escrow("rB", "rH", calculate_p2p_amounts(800.0))
        assert r["helper_amount_rlusd"] == 800.0 + 800.0 * 0.05

    def test_platform_fee(self):
        r = create_p2p_escrow("rB", "rH", calculate_p2p_amounts(800.0))
        assert r["platform_amount_rlusd"] == 800.0 * 0.03

    def test_unique_ids(self):
        a = calculate_p2p_amounts(100.0)
        ids = {create_p2p_escrow("rB", "rH", a)["escrow_id"] for _ in range(20)}
        assert len(ids) == 20

    def test_multiple_prices(self):
        for p in [50, 100, 250, 500, 1000, 2000, 5000, 10000]:
            r = calculate_p2p_amounts(float(p))
            assert r["total_escrow_rlusd"] == pytest.approx(r["helper_total"] + r["platform_fee"])
            assert r["helper_reimbursement"] == float(p)


# ===================================================================
# 5. TestWorkflowStatus
# ===================================================================

class TestWorkflowStatus:

    def test_all_statuses_exist(self):
        expected = [
            "initiated", "matching", "matched", "escrow_pending",
            "escrow_locked", "helper_accepted", "browser_session_created",
            "purchasing", "booking_confirmed", "escrow_releasing",
            "completed", "failed", "cancelled", "disputed",
        ]
        actual = [s.value for s in P2PWorkflowStatus]
        for st in expected:
            assert st in actual

    @pytest.mark.skipif(not HAS_BROWSER_CONTROL, reason="browser_control module removed in Build #89")
    def test_command_types_exist(self):
        expected = [
            "navigate", "wait_for", "wait_timeout", "click", "type_text",
            "select", "scroll", "extract_text", "extract_all", "screenshot",
            "get_url", "check_exists", "get_attribute", "ping", "close",
        ]
        actual = [c.value for c in CommandType]
        for ct in expected:
            assert ct in actual

    @pytest.mark.skipif(not HAS_BROWSER_CONTROL, reason="browser_control module removed in Build #89")
    def test_session_statuses_exist(self):
        expected = ["pending", "connected", "active", "paused",
                    "completed", "failed", "timed_out", "cancelled"]
        actual = [s.value for s in SessionStatus]
        for st in expected:
            assert st in actual
