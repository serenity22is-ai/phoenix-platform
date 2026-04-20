"""
Tests for the 6 new ANASTASiA neurons — Proxy, GeoIP, Arbitrage,
Verification, Booking Engine, and Google Search.

Tests cover:
- NeuronModule lifecycle (init, health_check, shutdown) for each neuron
- ProxyProvider ABC, BrightData + Webshare implementations
- MarketRouter POS selection, rotation, per-route learning
- GeoDetector modes (cloudflare, header, unknown)
- SpreadCalculator pricing math, minimum fee ($3), NO maximum cap
- USBaselineProvider caching and response parsing
- VerificationCodeManager (generate, verify, expire, rate limit)
- DisposableEmailChecker (blocklist, subdomain)
- BookingQueue priority ordering, enqueue/dequeue, card data wipe
- SessionManager lifecycle, timeout detection
- GoogleSearchModule URL builders, hotel normalization

MYSTES KYRIOS LLC — Confidential.
"""

import os
import time
from unittest.mock import patch, MagicMock

import pytest

from anastasia.core.events import EventBus, Event, EventType


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def event_bus():
    return EventBus()


@pytest.fixture
def config():
    """Minimal config for neuron initialization."""
    return {
        "proxy_provider": "brightdata",
        "proxy_priority_markets": ["DK", "DE", "PL"],
        "geoip_mode": "header",
        "geoip_arbitrage_countries": ["US"],
        "serpapi_key": "",
        "verification_code_ttl": 60,
        "verification_max_per_email": 5,
        "verification_max_per_ip": 20,
        "booking_max_queue_size": 50,
        "booking_max_concurrent_sessions": 5,
        "booking_session_timeout": 120,
    }


# ===========================================================================
# PROXY NEURON TESTS
# ===========================================================================


class TestBrightDataProvider:
    """Tests for BrightData residential proxy provider."""

    def test_not_configured_without_env(self):
        with patch.dict(os.environ, {}, clear=True):
            from anastasia.proxy.providers import BrightDataProvider
            bd = BrightDataProvider()
            # May pick up env from outer process; test the method
            if not os.environ.get("BRIGHTDATA_USERNAME"):
                assert bd.is_configured() is False

    def test_configured_with_env(self):
        env = {
            "BRIGHTDATA_USERNAME": "brd-customer-test-zone-res",
            "BRIGHTDATA_PASSWORD": "testpass123",
        }
        with patch.dict(os.environ, env, clear=False):
            from anastasia.proxy.providers import BrightDataProvider
            bd = BrightDataProvider()
            assert bd.is_configured() is True
            assert bd.name == "brightdata"
            assert bd.supports_scraping_browser() is True

    def test_get_proxy_country_targeting(self):
        env = {
            "BRIGHTDATA_USERNAME": "brd-customer-test-zone-res",
            "BRIGHTDATA_PASSWORD": "testpass123",
            "BRIGHTDATA_HOST": "brd.superproxy.io",
            "BRIGHTDATA_PORT": "22225",
        }
        with patch.dict(os.environ, env, clear=False):
            from anastasia.proxy.providers import BrightDataProvider
            bd = BrightDataProvider()
            proxy = bd.get_proxy("DK")

            assert proxy["country_code"] == "DK"
            assert "-country-dk" in proxy["username"]
            assert "brd.superproxy.io" in proxy["server"]
            assert proxy["password"] == "testpass123"

    def test_scraping_browser_url(self):
        env = {
            "BRIGHTDATA_USERNAME": "brd-customer-test-zone-res",
            "BRIGHTDATA_PASSWORD": "testpass123",
            "BRIGHTDATA_SB_HOST": "brd.superproxy.io",
            "BRIGHTDATA_SB_PORT": "9222",
        }
        with patch.dict(os.environ, env, clear=False):
            from anastasia.proxy.providers import BrightDataProvider
            bd = BrightDataProvider()
            url = bd.get_scraping_browser_url("DE")

            assert url.startswith("wss://")
            assert "-country-de" in url
            assert "testpass123" in url
            assert "9222" in url


class TestWebshareProvider:
    """Tests for Webshare fallback proxy provider."""

    def test_no_scraping_browser(self):
        env = {
            "WEBSHARE_USERNAME": "testuser",
            "WEBSHARE_PASSWORD": "testpass",
        }
        with patch.dict(os.environ, env, clear=False):
            from anastasia.proxy.providers import WebshareProvider
            ws = WebshareProvider()
            assert ws.supports_scraping_browser() is False

    def test_get_proxy_country_targeting(self):
        env = {
            "WEBSHARE_USERNAME": "testuser",
            "WEBSHARE_PASSWORD": "testpass",
            "WEBSHARE_HOST": "p.webshare.io",
            "WEBSHARE_HTTP_PORT": "80",
        }
        with patch.dict(os.environ, env, clear=False):
            from anastasia.proxy.providers import WebshareProvider
            ws = WebshareProvider()
            proxy = ws.get_proxy("PL")

            assert proxy["country_code"] == "PL"
            assert "-PL-rotate" in proxy["username"]


class TestMarketRouter:
    """Tests for POS market selection and anti-detection routing."""

    def test_select_markets_returns_list(self):
        from anastasia.proxy.market_router import MarketRouter
        router = MarketRouter(
            priority_markets=["DK", "DE", "NL", "PL"],
            cooldown_seconds=0,
        )
        markets = router.select_markets("LAX", "NRT", max_markets=3)
        assert isinstance(markets, list)
        assert len(markets) <= 3
        assert all(m in ["DK", "DE", "NL", "PL"] for m in markets)

    def test_select_markets_respects_max(self):
        from anastasia.proxy.market_router import MarketRouter
        router = MarketRouter(
            priority_markets=["DK", "DE", "NL", "PL", "SE", "NO", "FI"],
            cooldown_seconds=0,
        )
        markets = router.select_markets("JFK", "CDG", max_markets=2)
        assert len(markets) <= 2

    def test_record_result_builds_performance(self):
        from anastasia.proxy.market_router import MarketRouter
        router = MarketRouter(cooldown_seconds=0)
        router.record_result("LAX", "NRT", "DK", 300.0)
        router.record_result("LAX", "NRT", "DE", 150.0)

        perf = router.get_performance_stats()
        assert "LAX-NRT" in perf
        assert "DK" in perf["LAX-NRT"]
        assert "DE" in perf["LAX-NRT"]
        assert perf["LAX-NRT"]["DK"] > perf["LAX-NRT"]["DE"]

    def test_rate_limiting(self):
        from anastasia.proxy.market_router import MarketRouter
        router = MarketRouter(
            priority_markets=["DK"],
            max_queries_per_market_per_min=2,
            cooldown_seconds=0,
        )
        router.record_query("DK")
        router.record_query("DK")
        # After 2 queries, DK should be rate limited
        assert router._is_available("DK") is False

    def test_cooldown_tracking(self):
        from anastasia.proxy.market_router import MarketRouter
        router = MarketRouter(
            priority_markets=["DK"],
            cooldown_seconds=5,
        )
        router.record_query("DK")
        # Immediately after, cooldown should block
        assert router._is_available("DK") is False

    def test_market_config_lookup(self):
        from anastasia.proxy.market_router import MarketRouter, MARKET_CONFIG
        router = MarketRouter()
        config = router.get_market_config("DK")
        assert config is not None
        assert config["currency"] == "DKK"
        assert config["google_domain"] == "google.dk"

    def test_all_markets_count(self):
        from anastasia.proxy.market_router import MARKET_CONFIG
        assert len(MARKET_CONFIG) >= 30

    def test_stats(self):
        from anastasia.proxy.market_router import MarketRouter
        router = MarketRouter()
        stats = router.stats
        assert "total_markets" in stats
        assert "priority_markets" in stats
        assert "routes_tracked" in stats


class TestProxyModule:
    """Tests for the Proxy NeuronModule."""

    def test_lifecycle(self, event_bus, config):
        from anastasia.proxy import ProxyModule
        mod = ProxyModule()
        assert mod.name == "proxy"
        assert mod.dependencies == []

        # Before init
        health = mod.health_check()
        assert health["healthy"] is False

        # Init (providers may or may not be configured)
        mod.initialize(event_bus, config)
        health = mod.health_check()
        assert "active_provider" in health

        # Shutdown
        mod.shutdown()

    def test_select_markets_delegates(self, event_bus, config):
        from anastasia.proxy import ProxyModule
        mod = ProxyModule()
        mod.initialize(event_bus, config)
        markets = mod.select_markets("LAX", "NRT", max_markets=2)
        assert isinstance(markets, list)
        assert len(markets) <= 2


# ===========================================================================
# GEOIP NEURON TESTS
# ===========================================================================


class TestGeoDetector:
    """Tests for GeoIP detection modes."""

    def test_cloudflare_detection(self):
        from anastasia.geoip.detector import GeoDetector
        det = GeoDetector(mode="cloudflare")
        country = det.detect({"CF-IPCountry": "DE"}, "1.2.3.4")
        assert country == "DE"

    def test_cloudflare_tor(self):
        from anastasia.geoip.detector import GeoDetector
        det = GeoDetector(mode="cloudflare")
        # T1 = Tor, should fall back to header
        country = det.detect({"CF-IPCountry": "T1"}, "")
        assert country == "XX"

    def test_header_detection(self):
        from anastasia.geoip.detector import GeoDetector
        det = GeoDetector(mode="header")
        country = det.detect({"X-Country-Code": "JP"}, "")
        assert country == "JP"

    def test_unknown_returns_xx(self):
        from anastasia.geoip.detector import GeoDetector
        det = GeoDetector(mode="header")
        country = det.detect({}, "")
        assert country == "XX"

    def test_case_insensitive_headers(self):
        from anastasia.geoip.detector import GeoDetector
        det = GeoDetector(mode="cloudflare")
        country = det.detect({"cf-ipcountry": "fr"}, "")
        assert country == "FR"

    def test_client_ip_extraction(self):
        from anastasia.geoip.detector import GeoDetector
        det = GeoDetector(mode="header")
        ip = det._get_client_ip(
            {"x-forwarded-for": "1.2.3.4, 5.6.7.8"},
            "10.0.0.1",
        )
        assert ip == "1.2.3.4"

    def test_x_real_ip(self):
        from anastasia.geoip.detector import GeoDetector
        det = GeoDetector(mode="header")
        ip = det._get_client_ip({"x-real-ip": "9.8.7.6"}, "10.0.0.1")
        assert ip == "9.8.7.6"


class TestGeoIPModule:
    """Tests for the GeoIP NeuronModule."""

    def test_lifecycle(self, event_bus, config):
        from anastasia.geoip import GeoIPModule
        mod = GeoIPModule()
        assert mod.name == "geoip"
        assert mod.dependencies == []

        mod.initialize(event_bus, config)
        health = mod.health_check()
        assert health["healthy"] is True

        mod.shutdown()

    def test_detect_country(self, event_bus, config):
        from anastasia.geoip import GeoIPModule
        mod = GeoIPModule()
        mod.initialize(event_bus, config)

        country = mod.detect_country({"X-Country-Code": "US"}, "1.2.3.4")
        assert country == "US"

    def test_arbitrage_eligibility_us(self, event_bus, config):
        from anastasia.geoip import GeoIPModule
        mod = GeoIPModule()
        mod.initialize(event_bus, config)

        assert mod.should_use_arbitrage("US") is True
        assert mod.should_use_arbitrage("DE") is False

    def test_detect_and_route(self, event_bus, config):
        from anastasia.geoip import GeoIPModule
        mod = GeoIPModule()
        mod.initialize(event_bus, config)

        result = mod.detect_and_route({"X-Country-Code": "US"}, "1.2.3.4")
        assert result["country"] == "US"
        assert result["use_arbitrage"] is True
        assert result["pipeline"] == "arbitrage"


# ===========================================================================
# ARBITRAGE NEURON TESTS
# ===========================================================================


class TestSpreadCalculator:
    """Tests for POS spread calculation math."""

    def test_basic_spread(self):
        from anastasia.arbitrage.spread import SpreadCalculator
        calc = SpreadCalculator()
        result = calc.calculate(
            us_retail_price=1400.0,
            foreign_pos_price=800.0,
            foreign_market="DK",
            fee_percent=0.50,
        )
        assert result.has_arbitrage is True
        assert result.spread == 600.0
        assert result.service_fee == 300.0   # 600 * 50%
        assert result.customer_price == 1100.0  # 800 + 300
        assert result.customer_savings == 300.0  # 1400 - 1100
        assert result.savings_percent == pytest.approx(21.43, abs=0.1)

    def test_no_spread(self):
        from anastasia.arbitrage.spread import SpreadCalculator
        calc = SpreadCalculator()
        result = calc.calculate(
            us_retail_price=500.0,
            foreign_pos_price=520.0,
            foreign_market="DE",
            fee_percent=0.50,
        )
        assert result.has_arbitrage is False
        assert result.spread == 0.0
        assert result.service_fee == 0.0

    def test_minimum_fee_enforced(self):
        """$3 minimum fee — NO MAXIMUM CAP."""
        from anastasia.arbitrage.spread import SpreadCalculator, MINIMUM_FEE_USD
        assert MINIMUM_FEE_USD == 3.00

        calc = SpreadCalculator()
        # Small spread where 50% < $3
        result = calc.calculate(
            us_retail_price=100.0,
            foreign_pos_price=96.0,
            foreign_market="PL",
            fee_percent=0.50,
        )
        # Spread is $4, 50% = $2, but minimum is $3
        assert result.service_fee == 3.0
        assert result.customer_price == 99.0  # 96 + 3

    def test_no_maximum_fee_cap(self):
        """There is NO maximum fee cap. Corrected 4+ times."""
        from anastasia.arbitrage.spread import SpreadCalculator
        calc = SpreadCalculator()
        # Massive spread
        result = calc.calculate(
            us_retail_price=10000.0,
            foreign_pos_price=2000.0,
            foreign_market="DK",
            fee_percent=0.50,
        )
        # Fee = 8000 * 50% = $4000 — no cap applied
        assert result.service_fee == 4000.0
        assert result.customer_price == 6000.0

    def test_travel_plus_tier(self):
        """Travel+ = 35% fee tier."""
        from anastasia.arbitrage.spread import SpreadCalculator
        calc = SpreadCalculator()
        result = calc.calculate(
            us_retail_price=1400.0,
            foreign_pos_price=800.0,
            foreign_market="DK",
            fee_percent=0.35,
        )
        assert result.service_fee == 210.0  # 600 * 35%
        assert result.customer_price == 1010.0
        assert result.customer_savings == 390.0

    def test_multi_market_selects_best(self):
        from anastasia.arbitrage.spread import SpreadCalculator
        calc = SpreadCalculator()
        result = calc.calculate_multi_market(
            us_retail_price=1400.0,
            market_prices={"DK": 800.0, "DE": 900.0, "PL": 750.0},
            fee_percent=0.50,
        )
        assert result is not None
        assert result.foreign_market == "PL"  # Cheapest
        assert result.foreign_pos_price == 750.0

    def test_multi_market_no_arbitrage(self):
        from anastasia.arbitrage.spread import SpreadCalculator
        calc = SpreadCalculator()
        result = calc.calculate_multi_market(
            us_retail_price=500.0,
            market_prices={"DK": 520.0, "DE": 510.0},
            fee_percent=0.50,
        )
        assert result is None

    def test_display_no_pos_codes(self):
        """to_display() MUST NOT include POS market codes (airline compliance)."""
        from anastasia.arbitrage.spread import SpreadCalculator
        calc = SpreadCalculator()
        result = calc.calculate(1400.0, 800.0, "DK", 0.50)
        display = result.to_display()

        assert "google_price" in display
        assert "mystes_price" in display
        assert "you_save" in display
        # NO market codes in display
        assert "DK" not in str(display)
        assert "market" not in display
        assert "foreign_market" not in display

    def test_internal_includes_pos(self):
        """to_internal() includes POS codes (admin only)."""
        from anastasia.arbitrage.spread import SpreadCalculator
        calc = SpreadCalculator()
        result = calc.calculate(1400.0, 800.0, "DK", 0.50)
        internal = result.to_internal()

        assert internal["foreign_market"] == "DK"
        assert "kyrios_revenue" in internal

    def test_kyrios_revenue_accounts_stripe(self):
        from anastasia.arbitrage.spread import SpreadCalculator
        calc = SpreadCalculator()
        result = calc.calculate(1400.0, 800.0, "DK", 0.50)
        # Stripe: 2.9% + $0.30
        expected_stripe = result.service_fee * 0.029 + 0.30
        expected_revenue = result.service_fee - expected_stripe
        assert result.kyrios_revenue == pytest.approx(expected_revenue, abs=0.01)


class TestUSBaselineProvider:
    """Tests for SerpAPI US baseline price lookup."""

    def test_not_configured(self):
        from anastasia.arbitrage.baseline import USBaselineProvider
        provider = USBaselineProvider(api_key="")
        assert provider.is_configured() is False
        result = provider.get_us_baseline("LAX", "NRT", "2026-06-15")
        assert result is None

    def test_parse_response(self):
        from anastasia.arbitrage.baseline import USBaselineProvider
        provider = USBaselineProvider(api_key="test")

        mock_data = {
            "best_flights": [
                {
                    "price": 1400,
                    "total_duration": 720,
                    "flights": [
                        {"airline": "Japan Airlines", "departure_airport": {"id": "LAX"}},
                    ],
                },
            ],
            "other_flights": [
                {
                    "price": 1600,
                    "total_duration": 840,
                    "flights": [
                        {"airline": "ANA", "departure_airport": {"id": "LAX"}},
                    ],
                },
            ],
        }

        result = provider._parse_response(mock_data)
        assert result is not None
        assert result["price_usd"] == 1400.0
        assert result["airline"] == "Japan Airlines"
        assert result["stops"] == 0
        assert result["source"] == "serpapi"

    def test_parse_empty_response(self):
        from anastasia.arbitrage.baseline import USBaselineProvider
        provider = USBaselineProvider(api_key="test")
        result = provider._parse_response({"best_flights": [], "other_flights": []})
        assert result is None

    def test_cache_key_consistency(self):
        from anastasia.arbitrage.baseline import USBaselineProvider
        provider = USBaselineProvider(api_key="test")
        k1 = provider._cache_key("LAX", "NRT", "2026-06-15", None, "economy")
        k2 = provider._cache_key("LAX", "NRT", "2026-06-15", None, "economy")
        k3 = provider._cache_key("JFK", "NRT", "2026-06-15", None, "economy")
        assert k1 == k2
        assert k1 != k3

    def test_stats(self):
        from anastasia.arbitrage.baseline import USBaselineProvider
        provider = USBaselineProvider(api_key="test")
        stats = provider.stats
        assert stats["queries"] == 0
        assert stats["cache_hits"] == 0
        assert stats["configured"] is True


class TestArbitrageModule:
    """Tests for the Arbitrage NeuronModule."""

    def test_lifecycle(self, event_bus, config):
        from anastasia.arbitrage import ArbitrageModule
        mod = ArbitrageModule()
        assert mod.name == "arbitrage"
        assert "proxy" in mod.dependencies

        mod.initialize(event_bus, config)
        health = mod.health_check()
        assert health["healthy"] is True
        assert health["spreads_found"] == 0

        mod.shutdown()

    def test_calculate_spread_emits_event(self, event_bus, config):
        from anastasia.arbitrage import ArbitrageModule
        mod = ArbitrageModule()
        mod.initialize(event_bus, config)

        events_received = []
        event_bus.subscribe(
            EventType.ARBITRAGE_SPREAD_FOUND,
            lambda e: events_received.append(e),
        )

        result = mod.calculate_spread(1400.0, 800.0, "DK", 0.50)
        assert result.has_arbitrage is True
        assert len(events_received) == 1
        assert events_received[0].data["market"] == "DK"

    def test_calculate_best_spread(self, event_bus, config):
        from anastasia.arbitrage import ArbitrageModule
        mod = ArbitrageModule()
        mod.initialize(event_bus, config)

        result = mod.calculate_best_spread(
            us_retail_price=1400.0,
            market_prices={"DK": 800.0, "DE": 900.0, "PL": 750.0},
            fee_percent=0.45,
        )
        assert result is not None
        assert result.foreign_market == "PL"

    def test_health_tracks_metrics(self, event_bus, config):
        from anastasia.arbitrage import ArbitrageModule
        mod = ArbitrageModule()
        mod.initialize(event_bus, config)

        mod.calculate_spread(1400.0, 800.0, "DK", 0.50)
        mod.calculate_spread(500.0, 520.0, "DE", 0.50)

        health = mod.health_check()
        assert health["spreads_found"] == 1
        assert health["no_spread"] == 1


# ===========================================================================
# VERIFICATION NEURON TESTS
# ===========================================================================


class TestDisposableEmailChecker:
    """Tests for disposable email blocking."""

    def test_detects_known_disposable(self):
        from anastasia.verification.disposable import DisposableEmailChecker
        checker = DisposableEmailChecker()
        assert checker.is_disposable("user@mailinator.com") is True
        assert checker.is_disposable("test@guerrillamail.com") is True
        assert checker.is_disposable("foo@10minutemail.com") is True

    def test_allows_legitimate(self):
        from anastasia.verification.disposable import DisposableEmailChecker
        checker = DisposableEmailChecker()
        assert checker.is_disposable("user@gmail.com") is False
        assert checker.is_disposable("user@outlook.com") is False
        assert checker.is_disposable("user@icloud.com") is False

    def test_protonmail_not_blocked(self):
        """ProtonMail is legitimate — must NOT be blocked."""
        from anastasia.verification.disposable import DisposableEmailChecker
        checker = DisposableEmailChecker()
        assert checker.is_disposable("user@protonmail.ch") is False

    def test_tutanota_not_blocked(self):
        """Tutanota is legitimate — must NOT be blocked."""
        from anastasia.verification.disposable import DisposableEmailChecker
        checker = DisposableEmailChecker()
        assert checker.is_disposable("user@tutanota.com") is False

    def test_subdomain_match(self):
        from anastasia.verification.disposable import DisposableEmailChecker
        checker = DisposableEmailChecker()
        # Subdomain of a blocked domain should also be blocked
        assert checker.is_disposable("user@sub.mailinator.com") is True

    def test_no_at_sign(self):
        from anastasia.verification.disposable import DisposableEmailChecker
        checker = DisposableEmailChecker()
        assert checker.is_disposable("notanemail") is False

    def test_add_remove_domain(self):
        from anastasia.verification.disposable import DisposableEmailChecker
        checker = DisposableEmailChecker()
        checker.add_domain("testdomain123.com")
        assert checker.is_disposable("user@testdomain123.com") is True
        checker.remove_domain("testdomain123.com")
        assert checker.is_disposable("user@testdomain123.com") is False

    def test_domain_count(self):
        from anastasia.verification.disposable import DisposableEmailChecker
        checker = DisposableEmailChecker()
        assert checker.domain_count > 50  # We have 500+ built-in


class TestVerificationCodeManager:
    """Tests for 6-digit code generation and verification."""

    def test_generate_code_format(self):
        from anastasia.verification.codes import VerificationCodeManager
        mgr = VerificationCodeManager(code_ttl_seconds=60)
        code = mgr.generate_code("test@example.com", "1.2.3.4")
        assert len(code) == 6
        assert code.isdigit()

    def test_verify_correct_code(self):
        from anastasia.verification.codes import VerificationCodeManager
        mgr = VerificationCodeManager(code_ttl_seconds=60)
        code = mgr.generate_code("test@example.com")
        result = mgr.verify_code("test@example.com", code)
        assert result["success"] is True
        assert "session_token" in result
        assert result["email"] == "test@example.com"

    def test_verify_incorrect_code(self):
        from anastasia.verification.codes import VerificationCodeManager
        mgr = VerificationCodeManager(code_ttl_seconds=60)
        mgr.generate_code("test@example.com")
        result = mgr.verify_code("test@example.com", "000000")
        assert result["success"] is False
        assert result["error"] == "invalid_code"

    def test_verify_expired_code(self):
        from anastasia.verification.codes import VerificationCodeManager
        mgr = VerificationCodeManager(code_ttl_seconds=1)
        code = mgr.generate_code("test@example.com")
        # Manually expire the code by backdating created_at
        mgr._pending_codes["test@example.com"]["created_at"] = time.time() - 5
        result = mgr.verify_code("test@example.com", code)
        assert result["success"] is False
        # After cleanup, either "expired" or "not_found" is acceptable
        assert result["error"] in ("expired", "not_found")

    def test_verify_not_found(self):
        from anastasia.verification.codes import VerificationCodeManager
        mgr = VerificationCodeManager()
        result = mgr.verify_code("nobody@example.com", "123456")
        assert result["success"] is False
        assert result["error"] == "not_found"

    def test_max_attempts(self):
        from anastasia.verification.codes import VerificationCodeManager
        mgr = VerificationCodeManager(code_ttl_seconds=60)
        mgr.generate_code("test@example.com")
        # 5 wrong attempts + 1 = 6 total, should hit max (>5)
        for _ in range(6):
            mgr.verify_code("test@example.com", "000000")
        result = mgr.verify_code("test@example.com", "000000")
        assert result["success"] is False
        assert result["error"] == "not_found"  # Code was deleted

    def test_rate_limit_per_email(self):
        from anastasia.verification.codes import VerificationCodeManager
        mgr = VerificationCodeManager(
            code_ttl_seconds=60,
            max_codes_per_email_per_hour=2,
        )
        mgr.generate_code("test@example.com", "1.2.3.4")
        mgr.generate_code("test@example.com", "1.2.3.4")
        # Third should be rate limited
        check = mgr.check_rate_limit("test@example.com", "1.2.3.4")
        assert check["allowed"] is False

    def test_rate_limit_per_ip(self):
        from anastasia.verification.codes import VerificationCodeManager
        mgr = VerificationCodeManager(
            code_ttl_seconds=60,
            max_codes_per_ip_per_hour=2,
        )
        mgr.generate_code("a@example.com", "1.2.3.4")
        mgr.generate_code("b@example.com", "1.2.3.4")
        check = mgr.check_rate_limit("c@example.com", "1.2.3.4")
        assert check["allowed"] is False

    def test_case_insensitive_email(self):
        from anastasia.verification.codes import VerificationCodeManager
        mgr = VerificationCodeManager(code_ttl_seconds=60)
        code = mgr.generate_code("Test@Example.COM")
        result = mgr.verify_code("test@example.com", code)
        assert result["success"] is True

    def test_is_verified(self):
        from anastasia.verification.codes import VerificationCodeManager
        mgr = VerificationCodeManager(code_ttl_seconds=60)
        code = mgr.generate_code("test@example.com")
        mgr.verify_code("test@example.com", code)
        assert mgr.is_verified("test@example.com") is True

    def test_is_verified_with_token(self):
        from anastasia.verification.codes import VerificationCodeManager
        mgr = VerificationCodeManager(code_ttl_seconds=60)
        code = mgr.generate_code("test@example.com")
        result = mgr.verify_code("test@example.com", code)
        token = result["session_token"]
        assert mgr.is_verified("test@example.com", token=token) is True
        assert mgr.is_verified("test@example.com", token="wrong") is False


class TestVerificationModule:
    """Tests for the Verification NeuronModule."""

    def test_lifecycle(self, event_bus, config):
        from anastasia.verification import VerificationModule
        mod = VerificationModule()
        assert mod.name == "verification"
        assert mod.dependencies == []

        mod.initialize(event_bus, config)
        health = mod.health_check()
        assert health["healthy"] is True
        assert health["codes_sent"] == 0

        mod.shutdown()

    def test_send_code(self, event_bus, config):
        from anastasia.verification import VerificationModule
        mod = VerificationModule()
        mod.initialize(event_bus, config)

        result = mod.send_code("user@gmail.com", "1.2.3.4")
        assert result["success"] is True
        assert len(result["code"]) == 6
        assert result["email"] == "user@gmail.com"

    def test_verify_code(self, event_bus, config):
        from anastasia.verification import VerificationModule
        mod = VerificationModule()
        mod.initialize(event_bus, config)

        send = mod.send_code("user@gmail.com", "1.2.3.4")
        verify = mod.verify_code("user@gmail.com", send["code"])
        assert verify["success"] is True
        assert "session_token" in verify

    def test_disposable_blocked(self, event_bus, config):
        from anastasia.verification import VerificationModule
        mod = VerificationModule()
        mod.initialize(event_bus, config)

        result = mod.send_code("bot@mailinator.com", "1.2.3.4")
        assert result["success"] is False
        assert result["error"] == "disposable_email"

    def test_invalid_email(self, event_bus, config):
        from anastasia.verification import VerificationModule
        mod = VerificationModule()
        mod.initialize(event_bus, config)

        result = mod.send_code("not-an-email", "1.2.3.4")
        assert result["success"] is False
        assert result["error"] == "invalid_email"

    def test_event_emission(self, event_bus, config):
        from anastasia.verification import VerificationModule
        mod = VerificationModule()
        mod.initialize(event_bus, config)

        events = []
        event_bus.subscribe(
            EventType.VERIFICATION_CODE_SENT,
            lambda e: events.append(e),
        )

        mod.send_code("user@gmail.com", "1.2.3.4")
        assert len(events) == 1


# ===========================================================================
# BOOKING ENGINE NEURON TESTS
# ===========================================================================


class TestBookingQueue:
    """Tests for the booking priority queue."""

    def test_enqueue_returns_job(self):
        from anastasia.booking_engine.queue import BookingQueue, BookingPriority
        q = BookingQueue()
        job = q.enqueue("deal-1", 42, "DK", BookingPriority.FREE)
        assert job.deal_id == "deal-1"
        assert job.user_id == 42
        assert job.market == "DK"
        assert job.status.value == "queued"

    def test_priority_ordering(self):
        """Travel+ jobs dequeue before Free, Free before Guest."""
        from anastasia.booking_engine.queue import BookingQueue, BookingPriority
        q = BookingQueue()

        q.enqueue("guest-deal", None, "DK", BookingPriority.GUEST)
        q.enqueue("plus-deal", 1, "DK", BookingPriority.TRAVEL_PLUS)
        q.enqueue("free-deal", 2, "DK", BookingPriority.FREE)

        first = q.dequeue()
        assert first.deal_id == "plus-deal"
        second = q.dequeue()
        assert second.deal_id == "free-deal"
        third = q.dequeue()
        assert third.deal_id == "guest-deal"

    def test_fifo_within_same_priority(self):
        from anastasia.booking_engine.queue import BookingQueue, BookingPriority
        q = BookingQueue()
        q.enqueue("deal-a", None, "DK", BookingPriority.GUEST)
        time.sleep(0.01)
        q.enqueue("deal-b", None, "DK", BookingPriority.GUEST)

        first = q.dequeue()
        assert first.deal_id == "deal-a"

    def test_dequeue_empty_queue(self):
        from anastasia.booking_engine.queue import BookingQueue
        q = BookingQueue()
        assert q.dequeue() is None

    def test_complete_job_wipes_data(self):
        """CRITICAL: Card data must be wiped after completion."""
        from anastasia.booking_engine.queue import BookingQueue, BookingPriority
        q = BookingQueue()
        job = q.enqueue(
            "deal-1", 42, "DK", BookingPriority.GUEST,
            passenger_data={"name": "John Doe"},
            payment_info={"card_number": "4111111111111111"},
        )
        assert job.payment_info is not None
        assert job.passenger_data is not None

        q.complete_job(job.job_id, confirmation_code="ABC123")

        assert job.payment_info is None
        assert job.passenger_data is None
        assert job.confirmation_code == "ABC123"

    def test_complete_failed_wipes_data(self):
        from anastasia.booking_engine.queue import BookingQueue, BookingPriority
        q = BookingQueue()
        job = q.enqueue(
            "deal-1", 42, "DK", BookingPriority.GUEST,
            payment_info={"card_number": "4111"},
        )
        q.complete_job(job.job_id, error="Checkout failed")

        assert job.payment_info is None
        assert job.error == "Checkout failed"

    def test_cancel_job(self):
        from anastasia.booking_engine.queue import BookingQueue, BookingPriority, JobStatus
        q = BookingQueue()
        job = q.enqueue("deal-1", None, "DK")
        assert q.cancel_job(job.job_id) is True
        assert job.status == JobStatus.CANCELLED
        assert job.payment_info is None

    def test_queue_full_raises(self):
        from anastasia.booking_engine.queue import BookingQueue, BookingPriority
        q = BookingQueue(max_queue_size=2)
        q.enqueue("deal-1", None, "DK")
        q.enqueue("deal-2", None, "DK")
        with pytest.raises(RuntimeError, match="queue is full"):
            q.enqueue("deal-3", None, "DK")

    def test_queue_position(self):
        from anastasia.booking_engine.queue import BookingQueue, BookingPriority
        q = BookingQueue()
        j1 = q.enqueue("deal-1", None, "DK")
        j2 = q.enqueue("deal-2", None, "DK")
        assert q.get_queue_position(j1.job_id) == 0
        assert q.get_queue_position(j2.job_id) == 1

    def test_stats(self):
        from anastasia.booking_engine.queue import BookingQueue
        q = BookingQueue()
        q.enqueue("deal-1", None, "DK")
        stats = q.stats
        assert stats["pending"] == 1
        assert stats["total_completed"] == 0


class TestSessionManager:
    """Tests for Scraping Browser session lifecycle."""

    def test_create_session(self):
        from anastasia.booking_engine.session_manager import (
            SessionManager, SessionState,
        )
        mgr = SessionManager()
        session = mgr.create_session("deal-1", 42, "DK")
        assert session.deal_id == "deal-1"
        assert session.user_id == 42
        assert session.market == "DK"
        assert session.state == SessionState.PENDING

    def test_update_state(self):
        from anastasia.booking_engine.session_manager import (
            SessionManager, SessionState,
        )
        mgr = SessionManager()
        session = mgr.create_session("deal-1", 42, "DK")
        mgr.update_state(session.session_id, SessionState.CONNECTING)
        assert session.state == SessionState.CONNECTING
        assert session.started_at is not None

    def test_session_timeout(self):
        from anastasia.booking_engine.session_manager import (
            SessionManager, SessionState,
        )
        mgr = SessionManager(session_timeout_seconds=1)
        session = mgr.create_session("deal-1", 42, "DK")
        mgr.update_state(session.session_id, SessionState.CONNECTING)
        time.sleep(1.1)
        timed_out = mgr.cleanup_expired()
        assert session.session_id in timed_out
        assert session.state == SessionState.TIMEOUT

    def test_max_concurrent_sessions(self):
        from anastasia.booking_engine.session_manager import (
            SessionManager, SessionState,
        )
        mgr = SessionManager(max_concurrent_sessions=2)
        s1 = mgr.create_session("d-1", 1, "DK")
        s2 = mgr.create_session("d-2", 2, "DK")
        mgr.update_state(s1.session_id, SessionState.CONNECTING)
        mgr.update_state(s2.session_id, SessionState.CONNECTING)
        assert mgr.can_accept_session() is False

    def test_retry_logic(self):
        from anastasia.booking_engine.session_manager import (
            SessionManager, SessionState,
        )
        mgr = SessionManager()
        session = mgr.create_session("d-1", 1, "DK")
        mgr.update_state(session.session_id, SessionState.CONNECTING)
        assert mgr.mark_retry(session.session_id) is True
        assert session.retries == 1
        assert session.state == SessionState.PENDING

    def test_to_status(self):
        from anastasia.booking_engine.session_manager import (
            SessionManager, SessionState,
        )
        mgr = SessionManager()
        session = mgr.create_session("d-1", 1, "DK")
        status = session.to_status()
        assert status["state"] == "pending"
        assert "message" in status

    def test_stats(self):
        from anastasia.booking_engine.session_manager import SessionManager
        mgr = SessionManager()
        mgr.create_session("d-1", 1, "DK")
        stats = mgr.stats
        assert stats["total_tracked"] == 1


class TestBookingEngineModule:
    """Tests for the Booking Engine NeuronModule."""

    def test_lifecycle(self, event_bus, config):
        from anastasia.booking_engine import BookingEngineModule
        mod = BookingEngineModule()
        assert mod.name == "booking_engine"
        assert "proxy" in mod.dependencies

        mod.initialize(event_bus, config)
        health = mod.health_check()
        assert health["healthy"] is True

        mod.shutdown()

    def test_enqueue_booking(self, event_bus, config):
        from anastasia.booking_engine import BookingEngineModule
        mod = BookingEngineModule()
        mod.initialize(event_bus, config)

        result = mod.enqueue_booking(
            deal_id="deal-1",
            user_id=42,
            market="DK",
            fee_tier="travel_plus",
            passenger_data={"name": "Test"},
            payment_info={"card": "4111"},
        )
        assert "job_id" in result
        assert result["status"] == "queued"
        assert result["queue_position"] == 0

    def test_process_next(self, event_bus, config):
        from anastasia.booking_engine import BookingEngineModule
        mod = BookingEngineModule()
        mod.initialize(event_bus, config)

        mod.enqueue_booking("deal-1", 42, "DK")
        job_id = mod.process_next()
        assert job_id is not None

        status = mod.get_booking_status(job_id)
        assert status is not None
        assert status["status"] == "in_progress"

    def test_complete_booking_wipes_data(self, event_bus, config):
        from anastasia.booking_engine import BookingEngineModule
        mod = BookingEngineModule()
        mod.initialize(event_bus, config)

        result = mod.enqueue_booking(
            "deal-1", 42, "DK",
            payment_info={"card": "4111111111111111"},
        )
        job_id = result["job_id"]
        mod.process_next()
        mod.complete_booking(job_id, confirmation_code="XYZ789")

        job = mod.queue.get_job(job_id)
        assert job.payment_info is None  # WIPED

    def test_event_emission_on_enqueue(self, event_bus, config):
        from anastasia.booking_engine import BookingEngineModule
        mod = BookingEngineModule()
        mod.initialize(event_bus, config)

        events = []
        event_bus.subscribe(
            EventType.BOOKING_QUEUED,
            lambda e: events.append(e),
        )

        mod.enqueue_booking("deal-1", 42, "DK")
        assert len(events) == 1
        assert events[0].data["deal_id"] == "deal-1"


# ===========================================================================
# GOOGLE SEARCH NEURON TESTS
# ===========================================================================


class TestGoogleFlightsURL:
    """Tests for Google Flights URL building."""

    def test_build_flights_url(self):
        from anastasia.google_search.flights import build_flights_url
        url = build_flights_url("LAX", "NRT", "2026-06-15", "US")
        assert "google.com/travel/flights" in url
        assert "LAX" in url
        assert "NRT" in url
        assert "2026-06-15" in url

    def test_build_flights_url_dk_market(self):
        from anastasia.google_search.flights import build_flights_url
        url = build_flights_url("LAX", "NRT", "2026-06-15", "DK")
        assert "google.dk" in url
        assert "DKK" in url

    def test_build_flights_url_roundtrip(self):
        from anastasia.google_search.flights import build_flights_url
        url = build_flights_url(
            "LAX", "NRT", "2026-06-15", "US", return_date="2026-06-22"
        )
        assert "2026-06-22" in url


class TestGoogleHotelsURL:
    """Tests for Google Hotels URL building."""

    def test_build_hotels_url(self):
        from anastasia.google_search.hotels import build_hotels_url
        url = build_hotels_url("Barcelona", "2026-06-20", "2026-06-25", "US")
        assert "google.com/travel/hotels" in url
        assert "Barcelona" in url

    def test_build_hotels_url_de_market(self):
        from anastasia.google_search.hotels import build_hotels_url
        url = build_hotels_url("Paris", "2026-07-01", "2026-07-05", "DE")
        assert "google.de" in url
        assert "EUR" in url


class TestGoogleHotelsScraper:
    """Tests for hotel data normalization."""

    def test_normalize_hotels_filters_prices(self):
        from anastasia.google_search.hotels import GoogleHotelsScraper
        scraper = GoogleHotelsScraper()
        raw = [
            {"name": "Hotel A", "price": 150.0},
            {"name": "Hotel B", "price": 5.0},      # Too cheap
            {"name": "Hotel C", "price": 60000.0},   # Too expensive
            {"name": "Hotel D", "price": 250.0},
        ]
        result = scraper._normalize_hotels(raw, "US", "USD")
        names = [h["name"] for h in result]
        assert "Hotel A" in names
        assert "Hotel D" in names
        assert "Hotel B" not in names
        assert "Hotel C" not in names

    def test_normalize_hotels_sorted_by_price(self):
        from anastasia.google_search.hotels import GoogleHotelsScraper
        scraper = GoogleHotelsScraper()
        raw = [
            {"name": "Expensive", "price": 500.0},
            {"name": "Cheap", "price": 80.0},
            {"name": "Mid", "price": 200.0},
        ]
        result = scraper._normalize_hotels(raw, "US", "USD")
        prices = [h["price"] for h in result]
        assert prices == sorted(prices)

    def test_normalize_hotels_jpy_range(self):
        from anastasia.google_search.hotels import GoogleHotelsScraper
        scraper = GoogleHotelsScraper()
        raw = [
            {"name": "Tokyo Hotel", "price": 15000.0},   # Valid JPY
            {"name": "Too Cheap", "price": 500.0},        # Under JPY min
        ]
        result = scraper._normalize_hotels(raw, "JP", "JPY")
        assert len(result) == 1
        assert result[0]["name"] == "Tokyo Hotel"


class TestGoogleFlightsConfig:
    """Tests for flight market configuration."""

    def test_markets_have_required_keys(self):
        from anastasia.google_search.flights import GOOGLE_FLIGHTS_MARKETS
        required_keys = {"hl", "gl", "currency", "domain"}
        for market, config in GOOGLE_FLIGHTS_MARKETS.items():
            for key in required_keys:
                assert key in config, f"Market {market} missing key {key}"

    def test_currency_rates(self):
        from anastasia.google_search.flights import CURRENCY_RATES_TO_USD
        assert "USD" in CURRENCY_RATES_TO_USD
        assert CURRENCY_RATES_TO_USD["USD"] == 1.0
        assert "EUR" in CURRENCY_RATES_TO_USD
        assert "DKK" in CURRENCY_RATES_TO_USD


class TestGoogleSearchModule:
    """Tests for the Google Search NeuronModule."""

    def test_lifecycle(self, event_bus, config):
        from anastasia.google_search import GoogleSearchModule
        mod = GoogleSearchModule()
        assert mod.name == "google_search"
        assert "proxy" in mod.dependencies

        mod.initialize(event_bus, config)
        health = mod.health_check()
        assert health["healthy"] is True
        assert health["flight_searches"] == 0

        mod.shutdown()

    def test_not_initialized_raises(self):
        from anastasia.google_search import GoogleSearchModule
        mod = GoogleSearchModule()
        with pytest.raises(RuntimeError):
            import asyncio
            asyncio.get_event_loop().run_until_complete(
                mod.search_flights("LAX", "NRT", "2026-06-15", "US")
            )
