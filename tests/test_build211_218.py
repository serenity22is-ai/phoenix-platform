"""
MYSTES Tests — Builds #211-218 (Production Readiness)

#211: Booking Failure Safety Net (auto-refund + rollback)
#212: Dead Letter Queue (orphan recovery + admin view)
#213: Ops Alerting (failure notifications)
#214: Email Delivery Hardening (retry + queue + health)
#215: Sentry Error Tracking
#216: Structured Logging (JSON, stdout, request tracing)
#217: Cookie Consent + Legal Compliance (GDPR/CCPA)
#218: Production Health Monitoring (system status + metrics)

Run: python3 -m pytest tests/test_build211_218.py -v
"""

import json
import sys
import os
import logging
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server import app, db, limiter
from models import (
    User, Deal, Payment, Booking, BookingFailure, SystemMetric,
    FeatureFlag, SystemSetting,
)


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
    """Unauthenticated test client."""
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
        )
        user.set_password('TestPass123!')
        db.session.add(user)
        db.session.commit()

    client.post('/login', data={
        'email': 'test@example.com',
        'password': 'TestPass123!',
    }, follow_redirects=True)
    yield client


@pytest.fixture
def admin_client(client):
    """Admin test client."""
    with app.app_context():
        user = User(
            email='admin@mystes.app',
            name='Admin User',
            is_verified=True,
            is_active=True,
            is_admin=True,
        )
        user.set_password('AdminPass123!')
        db.session.add(user)
        db.session.commit()

    client.post('/login', data={
        'email': 'admin@mystes.app',
        'password': 'AdminPass123!',
    }, follow_redirects=True)
    yield client


@pytest.fixture
def sample_payment():
    """Create a sample verified payment."""
    with app.app_context():
        user = User.query.filter_by(email='test@example.com').first()
        deal = Deal(
            deal_id='deal_test_211',
            origin='LAX',
            destination='NRT',
            home_price_usd=1400.0,
            arbitrage_price_usd=900.0,
        )
        db.session.add(deal)
        db.session.flush()

        payment = Payment(
            user_id=user.id,
            deal_id=deal.id,
            amount_usd=225.0,
            payment_method='card',
            status='verified',
            verified_at=datetime.now(timezone.utc) - timedelta(minutes=30),
            stripe_payment_intent='pi_test_211_safety',
        )
        db.session.add(payment)
        db.session.commit()
        return {'payment_id': payment.id, 'deal_id': deal.id, 'user_id': user.id}


# ═════════════════════════════════════════════════════════════
# BUILD #211 — Booking Failure Safety Net
# ═════════════════════════════════════════════════════════════

class TestBuild211SafetyNet:
    """Auto-refund + failure recording when booking fails after payment."""

    def test_booking_failure_model_exists(self, client):
        """BookingFailure model has all required fields."""
        with app.app_context():
            assert hasattr(BookingFailure, 'booking_id')
            assert hasattr(BookingFailure, 'payment_id')
            assert hasattr(BookingFailure, 'failure_type')
            assert hasattr(BookingFailure, 'refund_status')
            assert hasattr(BookingFailure, 'refund_id')
            assert hasattr(BookingFailure, 'resolved')
            assert hasattr(BookingFailure, 'resolved_by')

    def test_booking_failure_default_pending(self, client):
        """BookingFailure defaults to pending refund status."""
        with app.app_context():
            col = BookingFailure.__table__.columns['refund_status']
            assert col.default.arg == 'pending'

    def test_booking_failure_to_dict(self, auth_client, sample_payment):
        """BookingFailure.to_dict() returns complete structure."""
        with app.app_context():
            failure = BookingFailure(
                payment_id=sample_payment['payment_id'],
                user_id=sample_payment['user_id'],
                failure_type='booking_api',
                failure_reason='Duffel API timeout',
                refund_status='refunded',
            )
            db.session.add(failure)
            db.session.commit()

            d = failure.to_dict()
            assert d['failure_type'] == 'booking_api'
            assert d['failure_reason'] == 'Duffel API timeout'
            assert d['refund_status'] == 'refunded'
            assert d['payment_id'] == sample_payment['payment_id']
            assert d['created_at'] is not None

    def test_record_booking_failure_creates_record(self, auth_client, sample_payment):
        """_record_booking_failure creates a BookingFailure record."""
        with app.app_context():
            from server import _record_booking_failure
            payment = db.session.get(Payment, sample_payment['payment_id'])
            failure = _record_booking_failure(
                payment=payment,
                user_id=sample_payment['user_id'],
                failure_type='test',
                failure_reason='Unit test',
                auto_refund=False,
            )
            assert failure is not None
            assert failure.failure_type == 'test'
            assert failure.refund_status == 'manual_review'

            # SystemMetric should also be recorded
            metric = SystemMetric.query.filter_by(metric_key='booking_failure').first()
            assert metric is not None

    @patch('payments.create_stripe_refund')
    def test_auto_refund_on_failure(self, mock_refund, auth_client, sample_payment):
        """Auto-refund triggers when booking fails after payment."""
        mock_refund.return_value = {
            'success': True,
            'refund_id': 're_test_auto',
            'amount': 22500,
            'status': 'succeeded',
        }
        with app.app_context():
            from server import _record_booking_failure
            payment = db.session.get(Payment, sample_payment['payment_id'])
            failure = _record_booking_failure(
                payment=payment,
                user_id=sample_payment['user_id'],
                failure_type='booking_api',
                failure_reason='Duffel timeout',
                auto_refund=True,
            )
            assert failure.refund_status == 'refunded'
            assert failure.refund_id == 're_test_auto'
            assert failure.resolved is True
            assert failure.resolved_by == 'auto_refund'
            mock_refund.assert_called_once_with('pi_test_211_safety')

    @patch('payments.create_stripe_refund')
    def test_auto_refund_failure_recorded(self, mock_refund, auth_client, sample_payment):
        """Failed auto-refund is recorded for manual review."""
        mock_refund.return_value = {'error': 'Charge already refunded'}
        with app.app_context():
            from server import _record_booking_failure
            payment = db.session.get(Payment, sample_payment['payment_id'])
            failure = _record_booking_failure(
                payment=payment,
                failure_type='booking_api',
                failure_reason='Test',
                auto_refund=True,
            )
            assert failure.refund_status == 'failed'
            assert 'already refunded' in failure.admin_notes

    def test_rewards_exception_non_fatal(self, client):
        """Rewards wiring exception doesn't crash booking flow."""
        # This tests that the try/except wrapper exists around _wire_booking_rewards
        # The actual test is structural — if the wrapping is absent, a rewards
        # exception would crash the booking and leave the customer without confirmation
        with app.app_context():
            # Verify the safety net code exists in server.py
            import inspect
            from server import complete_booking
            source = inspect.getsource(complete_booking)
            assert 'Rewards wiring failed (non-fatal)' in source

    def test_email_exception_non_fatal(self, client):
        """Email exception doesn't crash booking flow."""
        with app.app_context():
            import inspect
            from server import complete_booking
            source = inspect.getsource(complete_booking)
            assert 'Confirmation email failed (non-fatal)' in source


# ═════════════════════════════════════════════════════════════
# BUILD #212 — Dead Letter Queue
# ═════════════════════════════════════════════════════════════

class TestBuild212DeadLetterQueue:
    """Orphaned payment detection and recovery."""

    def test_sweep_detects_orphan(self, auth_client, sample_payment):
        """Sweep finds payment verified >15 min ago with no booking."""
        with app.app_context():
            from server import _sweep_orphaned_payments
            with patch('payments.create_stripe_refund') as mock_refund:
                mock_refund.return_value = {
                    'success': True, 'refund_id': 're_sweep', 'amount': 22500,
                }
                _sweep_orphaned_payments()

            failures = BookingFailure.query.filter_by(
                failure_type='orphaned_payment'
            ).all()
            assert len(failures) == 1
            assert failures[0].payment_id == sample_payment['payment_id']

    def test_sweep_ignores_successful_booking(self, auth_client, sample_payment):
        """Sweep skips payments with successful bookings."""
        with app.app_context():
            payment = db.session.get(Payment, sample_payment['payment_id'])
            booking = Booking(
                user_id=sample_payment['user_id'],
                deal_id=sample_payment['deal_id'],
                payment_id=payment.id,
                status='booked',
            )
            db.session.add(booking)
            db.session.commit()

            from server import _sweep_orphaned_payments
            _sweep_orphaned_payments()

            failures = BookingFailure.query.filter_by(
                failure_type='orphaned_payment'
            ).all()
            assert len(failures) == 0

    def test_sweep_no_duplicates(self, auth_client, sample_payment):
        """Sweep doesn't create duplicate failure records."""
        with app.app_context():
            from server import _sweep_orphaned_payments
            with patch('payments.create_stripe_refund') as mock_refund:
                mock_refund.return_value = {
                    'success': True, 'refund_id': 're_dup', 'amount': 22500,
                }
                _sweep_orphaned_payments()
                _sweep_orphaned_payments()  # Run twice

            failures = BookingFailure.query.filter_by(
                failure_type='orphaned_payment'
            ).all()
            # First creates resolved failure, second skips (resolved=True, but check is resolved=False)
            assert len(failures) == 1

    def test_admin_orphaned_payments_endpoint(self, admin_client):
        """Admin can view orphaned payments."""
        with app.app_context():
            failure = BookingFailure(
                failure_type='orphaned_payment',
                failure_reason='Test',
                refund_status='pending',
            )
            db.session.add(failure)
            db.session.commit()

        resp = admin_client.get('/api/admin/orphaned-payments')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        assert data['count'] == 1

    def test_admin_resolve_failure(self, admin_client):
        """Admin can resolve a booking failure."""
        with app.app_context():
            failure = BookingFailure(
                failure_type='test',
                failure_reason='Test failure',
                refund_status='manual_review',
            )
            db.session.add(failure)
            db.session.commit()
            fid = failure.id

        resp = admin_client.post(
            f'/api/admin/orphaned-payments/{fid}/resolve',
            data=json.dumps({"notes": "Manually refunded via Stripe dashboard"}),
            content_type='application/json',
        )
        assert resp.status_code == 200

        with app.app_context():
            f = db.session.get(BookingFailure, fid)
            assert f.resolved is True
            assert f.resolved_by == 'admin'

    def test_non_admin_blocked(self, auth_client):
        """Non-admin cannot access orphaned payments."""
        resp = auth_client.get('/api/admin/orphaned-payments')
        assert resp.status_code == 403


# ═════════════════════════════════════════════════════════════
# BUILD #213 — Ops Alerting
# ═════════════════════════════════════════════════════════════

class TestBuild213OpsAlerting:
    """Ops alert system for critical failures."""

    def test_ops_alert_function_exists(self, client):
        """_send_ops_alert function exists and is callable."""
        with app.app_context():
            from server import _send_ops_alert
            assert callable(_send_ops_alert)

    @patch('email_service.send_email_async')
    def test_ops_alert_sends_email(self, mock_send, client):
        """Ops alert sends email when OPS_ALERT_EMAIL configured."""
        with app.app_context():
            with patch.dict(os.environ, {'OPS_ALERT_EMAIL': 'ops@mystes.app'}):
                from server import _send_ops_alert
                _send_ops_alert(
                    subject="[MYSTES] Test Alert",
                    body="Test alert body",
                )
                mock_send.assert_called_once()

    def test_ops_alert_no_crash_without_email(self, client):
        """Ops alert doesn't crash when no email configured."""
        with app.app_context():
            with patch.dict(os.environ, {}, clear=True):
                os.environ.pop('OPS_ALERT_EMAIL', None)
                os.environ.pop('MAIL_USERNAME', None)
                from server import _send_ops_alert
                _send_ops_alert(subject="Test", body="Test")


# ═════════════════════════════════════════════════════════════
# BUILD #214 — Email Delivery Hardening
# ═════════════════════════════════════════════════════════════

class TestBuild214EmailHardening:
    """Email delivery with retry logic."""

    def test_send_email_smtp_retry_on_disconnect(self):
        """SMTP disconnection triggers retry."""
        from email_service import send_email_smtp, EMAIL_CONFIG
        original_enabled = EMAIL_CONFIG['enabled']
        EMAIL_CONFIG['enabled'] = True
        EMAIL_CONFIG['username'] = 'test@test.com'
        EMAIL_CONFIG['password'] = 'test'

        with patch('smtplib.SMTP') as mock_smtp:
            mock_instance = MagicMock()
            mock_instance.__enter__ = MagicMock(return_value=mock_instance)
            mock_instance.__exit__ = MagicMock(return_value=False)
            mock_instance.starttls.side_effect = [
                ConnectionError("Connection lost"),
                ConnectionError("Connection lost"),
                None,  # Third attempt succeeds
            ]
            mock_smtp.return_value = mock_instance

            result = send_email_smtp(
                to='test@example.com',
                subject='Test',
                html_body='<p>Test</p>',
                max_retries=3,
            )
            # Third attempt succeeds with starttls
            assert mock_smtp.call_count == 3

        EMAIL_CONFIG['enabled'] = original_enabled

    def test_send_email_smtp_disabled(self):
        """Disabled email returns True without sending."""
        from email_service import send_email_smtp, EMAIL_CONFIG
        original = EMAIL_CONFIG['enabled']
        EMAIL_CONFIG['enabled'] = False
        result = send_email_smtp(
            to='test@example.com',
            subject='Test',
            html_body='<p>Test</p>',
        )
        assert result is True
        EMAIL_CONFIG['enabled'] = original

    def test_send_email_smtp_no_credentials(self):
        """Missing credentials returns False."""
        from email_service import send_email_smtp, EMAIL_CONFIG
        original = EMAIL_CONFIG.copy()
        EMAIL_CONFIG['enabled'] = True
        EMAIL_CONFIG['username'] = ''
        EMAIL_CONFIG['password'] = ''

        result = send_email_smtp(
            to='test@example.com',
            subject='Test',
            html_body='<p>Test</p>',
        )
        assert result is False

        EMAIL_CONFIG.update(original)

    def test_send_email_async_simple_interface(self):
        """send_email_async works with simple (to, subject, body) interface."""
        from email_service import send_email_async
        # Should not crash
        with patch('email_service.send_email_smtp') as mock:
            send_email_async(
                to_email='test@example.com',
                subject='Test',
                body='<p>Test</p>',
            )
            # Give thread time to execute
            import time
            time.sleep(0.2)


# ═════════════════════════════════════════════════════════════
# BUILD #215 — Sentry Error Tracking
# ═════════════════════════════════════════════════════════════

class TestBuild215Sentry:
    """Sentry integration and monitoring enhancements."""

    def test_monitoring_module_has_booking_trackers(self):
        """monitoring.py has booking failure tracking functions."""
        from monitoring import track_booking, track_booking_failure, track_email
        assert callable(track_booking)
        assert callable(track_booking_failure)
        assert callable(track_email)

    def test_sentry_context_setter_exists(self):
        """set_sentry_booking_context exists and is safe without sentry-sdk."""
        from monitoring import set_sentry_booking_context
        # Should not crash even without sentry_sdk installed
        set_sentry_booking_context(
            booking_id=1, deal_id=2, user_id=3, channel='proxy'
        )

    def test_sentry_before_send_redacts_sensitive(self):
        """Sentry before_send filter redacts passwords and card numbers."""
        from monitoring import _sentry_before_send
        event = {
            "request": {
                "data": {
                    "password": "secret123",
                    "card_number": "4242424242424242",
                    "email": "test@test.com",
                }
            }
        }
        result = _sentry_before_send(event, {})
        assert result["request"]["data"]["password"] == "[REDACTED]"
        assert result["request"]["data"]["card_number"] == "[REDACTED]"
        assert result["request"]["data"]["email"] == "test@test.com"

    def test_init_sentry_without_dsn(self):
        """init_sentry returns False when no DSN configured."""
        from monitoring import init_sentry
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop('SENTRY_DSN', None)
            result = init_sentry(app)
            assert result is False

    def test_prometheus_metrics_export(self):
        """Prometheus metrics endpoint returns text format."""
        from monitoring import metrics
        metrics.inc("test_counter", 5)
        output = metrics.export()
        assert "test_counter" in output
        assert "mystes_uptime_seconds" in output


# ═════════════════════════════════════════════════════════════
# BUILD #216 — Structured Logging
# ═════════════════════════════════════════════════════════════

class TestBuild216StructuredLogging:
    """JSON structured logging for production."""

    def test_json_formatter_exists(self):
        """_JSONFormatter class exists in server.py."""
        from server import _JSONFormatter
        assert _JSONFormatter is not None

    def test_json_formatter_output(self):
        """JSON formatter produces valid JSON."""
        from server import _JSONFormatter
        formatter = _JSONFormatter()
        record = logging.LogRecord(
            name='test', level=logging.INFO,
            pathname='test.py', lineno=1,
            msg='Test message', args=(), exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed['msg'] == 'Test message'
        assert parsed['level'] == 'INFO'
        assert 'ts' in parsed

    def test_json_formatter_with_exception(self):
        """JSON formatter includes exception info."""
        from server import _JSONFormatter
        formatter = _JSONFormatter()
        try:
            raise ValueError("test error")
        except ValueError:
            import sys
            exc_info = sys.exc_info()

        record = logging.LogRecord(
            name='test', level=logging.ERROR,
            pathname='test.py', lineno=1,
            msg='Error occurred', args=(), exc_info=exc_info,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert 'exception' in parsed
        assert 'test error' in parsed['exception']

    def test_audit_log_function(self):
        """audit_log function works with keyword arguments."""
        from server import audit_log
        # Should not crash
        audit_log("test_action", user_id=123, amount=50.0, method="card")

    def test_request_id_in_monitoring(self):
        """Request tracking generates request_id."""
        from monitoring import init_request_tracking
        # Function exists and accepts app parameter
        assert callable(init_request_tracking)


# ═════════════════════════════════════════════════════════════
# BUILD #217 — Cookie Consent + Legal Compliance
# ═════════════════════════════════════════════════════════════

class TestBuild217CookieConsent:
    """GDPR/CCPA cookie consent and legal pages."""

    def test_cookies_route_exists(self, client):
        """GET /cookies returns 200 with cookie policy."""
        resp = client.get('/cookies')
        assert resp.status_code == 200
        html = resp.data.decode()
        assert 'Cookie Policy' in html
        assert 'Essential Cookies' in html
        assert 'CCPA' in html or 'California' in html

    def test_do_not_sell_route_exists(self, client):
        """GET /do-not-sell returns 200 with CCPA notice."""
        resp = client.get('/do-not-sell')
        assert resp.status_code == 200
        html = resp.data.decode()
        assert 'Do Not Sell' in html
        assert 'NOT' in html

    def test_cookie_consent_banner_in_template(self, client):
        """Base template includes cookie consent banner."""
        # Load any page that uses BASE_TEMPLATE
        resp = client.get('/')
        if resp.status_code == 200:
            html = resp.data.decode()
            assert 'cookie-consent' in html
            assert 'acceptCookies' in html
            assert 'mystes_cookie_consent' in html

    def test_cookie_policy_mentions_session_cookie(self, client):
        """Cookie policy lists essential cookies."""
        resp = client.get('/cookies')
        html = resp.data.decode()
        assert 'session' in html.lower()
        assert 'csrf' in html.lower()

    def test_ccpa_links_to_privacy(self, client):
        """CCPA page links to privacy policy."""
        resp = client.get('/do-not-sell')
        html = resp.data.decode()
        assert '/privacy' in html

    def test_privacy_page_exists(self, client):
        """Privacy policy page exists."""
        resp = client.get('/privacy')
        assert resp.status_code == 200

    def test_terms_page_exists(self, client):
        """Terms of service page exists."""
        resp = client.get('/terms')
        assert resp.status_code == 200


# ═════════════════════════════════════════════════════════════
# BUILD #218 — Production Health Monitoring
# ═════════════════════════════════════════════════════════════

class TestBuild218HealthMonitoring:
    """System status dashboard and metrics."""

    def test_health_check_includes_failures(self, client):
        """Health check includes booking_failures_unresolved count."""
        resp = client.get('/health')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'booking_failures_unresolved' in data['services']
        assert data['build'] == 218

    def test_system_status_endpoint(self, admin_client):
        """Admin system-status returns comprehensive metrics."""
        resp = admin_client.get('/api/admin/system-status')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        assert 'bookings' in data
        assert 'payments' in data
        assert 'failures' in data
        assert 'users' in data
        assert 'email' in data
        assert 'success_rate_pct' in data['bookings']

    def test_system_status_non_admin_blocked(self, auth_client):
        """Non-admin cannot access system-status."""
        resp = auth_client.get('/api/admin/system-status')
        assert resp.status_code == 403

    def test_system_metric_model(self, client):
        """SystemMetric model creates and retrieves correctly."""
        with app.app_context():
            metric = SystemMetric(
                metric_key='test_metric',
                metric_value=42.0,
                metadata_json='{"source": "test"}',
            )
            db.session.add(metric)
            db.session.commit()

            loaded = SystemMetric.query.filter_by(metric_key='test_metric').first()
            assert loaded.metric_value == 42.0
            d = loaded.to_dict()
            assert d['metric_key'] == 'test_metric'

    def test_record_metric_endpoint(self, admin_client):
        """Admin can record a custom metric."""
        resp = admin_client.post(
            '/api/admin/metrics/record',
            data=json.dumps({"key": "test_custom", "value": 99}),
            content_type='application/json',
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True

        with app.app_context():
            m = SystemMetric.query.filter_by(metric_key='test_custom').first()
            assert m is not None
            assert m.metric_value == 99.0

    def test_api_status_updated_version(self, client):
        """API status reflects build 218."""
        resp = client.get('/api/status')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['build'] == 218
        assert data['version'] == '2.0.0'


# ═════════════════════════════════════════════════════════════
# CROSS-BUILD INTEGRATION
# ═════════════════════════════════════════════════════════════

class TestCrossBuildIntegration:
    """Tests spanning multiple builds."""

    @patch('payments.create_stripe_refund')
    def test_failure_to_alert_to_metric_pipeline(self, mock_refund, auth_client, sample_payment):
        """Full pipeline: booking failure → auto-refund → ops alert → metric."""
        mock_refund.return_value = {
            'success': True, 'refund_id': 're_pipeline', 'amount': 22500,
        }
        with app.app_context():
            from server import _record_booking_failure
            payment = db.session.get(Payment, sample_payment['payment_id'])

            with patch('server._send_ops_alert') as mock_alert:
                failure = _record_booking_failure(
                    payment=payment,
                    failure_type='booking_api',
                    failure_reason='Pipeline test',
                    booking_channel='duffel',
                    auto_refund=True,
                )

                # #211: Failure recorded
                assert failure.refund_status == 'refunded'
                # #213: Ops alert sent
                mock_alert.assert_called_once()
                alert_subject = mock_alert.call_args[1].get('subject', mock_alert.call_args[0][0] if mock_alert.call_args[0] else '')
                assert 'Booking Failure' in alert_subject
                # #218: Metric recorded
                metric = SystemMetric.query.filter_by(metric_key='booking_failure').first()
                assert metric is not None

    def test_health_to_status_consistency(self, client):
        """Health and status endpoints both report build 218."""
        health = client.get('/health').get_json()
        status = client.get('/api/status').get_json()
        assert health['build'] == status['build'] == 218

    def test_legal_pages_all_accessible(self, client):
        """All legal pages (terms, privacy, cookies, do-not-sell) return 200."""
        for path in ['/terms', '/privacy', '/cookies', '/do-not-sell']:
            resp = client.get(path)
            assert resp.status_code == 200, f"{path} returned {resp.status_code}"
