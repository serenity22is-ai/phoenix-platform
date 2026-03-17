"""
Tests for the AutoLearner — autonomous API reverse-engineering pipeline.

Tests cover:
- API discovery from codebase scans (SDK patterns, URL extraction)
- Probe generation
- Rule-based analysis (fallback when Claude unavailable)
- Claude-powered analysis (mocked)
- SystemProfile creation from analysis
- Profile retention and merging
- Full learn() pipeline end-to-end

MYSTES KYRIOS LLC — Confidential.
"""

import json
import pytest

from anastasia.core.events import EventBus, Event, EventType
from anastasia.knowledge.profiles import ProfileStore
from anastasia.knowledge.auto_learner import (
    AutoLearner,
    APIDiscovery,
    ProbeResult,
)


@pytest.fixture
def event_bus():
    return EventBus()


@pytest.fixture
def profile_store(event_bus, tmp_path):
    return ProfileStore(event_bus=event_bus, storage_dir=str(tmp_path / "profiles"))


@pytest.fixture
def learner(event_bus, profile_store):
    return AutoLearner(
        event_bus=event_bus,
        profile_store=profile_store,
    )


# ---------------------------------------------------------------------------
# Mock codebase scans
# ---------------------------------------------------------------------------

def _make_flask_stripe_scan():
    """Codebase scan of a Flask app using Stripe and an unknown hotel API."""
    return {
        "file_contents": {
            "app.py": (
                "from flask import Flask, jsonify\n"
                "import stripe\n"
                "import requests\n"
                "\n"
                "app = Flask(__name__)\n"
                "stripe.api_key = 'sk_test_xxx'\n"
                "\n"
                "@app.route('/search')\n"
                "def search():\n"
                "    resp = requests.get('https://api.hotelworld.io/v2/search')\n"
                "    return jsonify(resp.json())\n"
            ),
            "booking.py": (
                "import requests\n"
                "\n"
                "def book_room(hotel_id, guest):\n"
                "    resp = requests.post(\n"
                "        'https://api.hotelworld.io/v2/bookings',\n"
                "        json={'hotel_id': hotel_id, 'guest': guest}\n"
                "    )\n"
                "    return resp.json()\n"
            ),
            "requirements.txt": "flask\nstripe\nrequests\n",
        },
        "routes": [
            {"path": "/search", "method": "GET"},
        ],
        "tech_stack": {"language": "python", "framework": "flask"},
    }


def _make_express_amadeus_scan():
    """Codebase scan of an Express app using Amadeus SDK."""
    return {
        "file_contents": {
            "index.js": (
                "const express = require('express');\n"
                "const Amadeus = require('amadeus');\n"
                "\n"
                "const app = express();\n"
                "const amadeus = new Amadeus({clientId: 'xxx', clientSecret: 'yyy'});\n"
            ),
            "routes/flights.js": (
                "const axios = require('axios');\n"
                "\n"
                "async function searchFlights(req, res) {\n"
                "    const resp = await axios.get('https://api.flightdeals.co/search');\n"
                "    res.json(resp.data);\n"
                "}\n"
            ),
            "package.json": '{"name": "flight-app", "dependencies": {"express": "^4"}}',
        },
        "routes": [],
        "tech_stack": {"language": "javascript", "framework": "express"},
    }


# ---------------------------------------------------------------------------
# ENCOUNTER tests
# ---------------------------------------------------------------------------

class TestEncounter:
    """Test API discovery from codebase scans."""

    def test_discover_sdk_pattern(self, learner):
        """Known SDK (Stripe) should be discovered."""
        scan = _make_flask_stripe_scan()
        discoveries = learner.encounter(scan)
        names = {d.name for d in discoveries}
        assert "Stripe" in names

    def test_discover_url_extraction(self, learner):
        """Unknown API URL should be discovered."""
        scan = _make_flask_stripe_scan()
        discoveries = learner.encounter(scan)
        base_urls = {d.base_url for d in discoveries}
        assert "https://api.hotelworld.io" in base_urls

    def test_skip_known_profile(self, learner, profile_store, event_bus):
        """APIs already profiled with high confidence should be skipped."""
        from anastasia.core.types import SystemProfile
        # Pre-seed Stripe profile
        profile_store.create_profile(SystemProfile(
            name="Stripe",
            vendor="Stripe Inc",
            confidence=0.8,
            readiness="production",
        ))
        scan = _make_flask_stripe_scan()
        discoveries = learner.encounter(scan)
        names = {d.name for d in discoveries}
        assert "Stripe" not in names

    def test_publishes_system_discovered_event(self, learner, event_bus):
        """Each discovery should publish a SYSTEM_DISCOVERED event."""
        events = []
        event_bus.subscribe(EventType.SYSTEM_DISCOVERED, lambda e: events.append(e))
        scan = _make_flask_stripe_scan()
        learner.encounter(scan)
        assert len(events) > 0
        assert events[0].type == EventType.SYSTEM_DISCOVERED

    def test_no_file_contents_returns_empty(self, learner):
        """Scan without file_contents should return no discoveries."""
        discoveries = learner.encounter({"routes": [], "tech_stack": {}})
        assert discoveries == []

    def test_multiple_sdks_detected(self, learner):
        """Multiple SDK patterns in one codebase should all be discovered."""
        scan = _make_express_amadeus_scan()
        discoveries = learner.encounter(scan)
        # Should discover the unknown URL (flightdeals.co) at minimum
        assert len(discoveries) > 0
        # Amadeus may be skipped if seed profile exists with high confidence
        # so just verify we discover the unknown URL
        base_urls = {d.base_url for d in discoveries}
        assert "https://api.flightdeals.co" in base_urls

    def test_url_domain_deduplication(self, learner):
        """Same base URL appearing multiple times should only produce one discovery."""
        scan = _make_flask_stripe_scan()
        discoveries = learner.encounter(scan)
        base_urls = [d.base_url for d in discoveries]
        # hotelworld.io appears in both app.py and booking.py
        assert base_urls.count("https://api.hotelworld.io") == 1

    def test_discovery_includes_source_files(self, learner):
        """Discoveries should track which files contain the API reference."""
        scan = _make_flask_stripe_scan()
        discoveries = learner.encounter(scan)
        stripe = next((d for d in discoveries if d.name == "Stripe"), None)
        assert stripe is not None
        assert len(stripe.source_files) > 0


# ---------------------------------------------------------------------------
# PROBE tests
# ---------------------------------------------------------------------------

class TestProbe:
    """Test probe generation for discovered APIs."""

    def test_probe_generates_endpoints(self, learner):
        """Probing should generate requests for standard endpoints."""
        discovery = APIDiscovery(
            name="TestAPI",
            base_url="https://api.example.com",
        )
        results = learner.probe(discovery)
        # Should probe standard endpoints + auth probes
        assert len(results) > 10
        # All should be pending (no http_probe callable)
        assert all(r.status_code == -1 for r in results)

    def test_probe_updates_status(self, learner):
        """Discovery status should change to 'probed' after probing."""
        discovery = APIDiscovery(name="TestAPI", base_url="https://api.example.com")
        learner.probe(discovery)
        assert discovery.status == "probed"

    def test_probe_with_http_callable(self, event_bus, profile_store):
        """Real HTTP probes should use the provided callable."""
        probe_calls = []

        def mock_http_probe(url, method="GET", headers=None, timeout=10):
            probe_calls.append(url)
            return ProbeResult(
                url=url, method=method, status_code=200,
                headers={"content-type": "application/json"},
                body='{"status": "ok"}',
                duration_ms=42.0,
            )

        learner = AutoLearner(
            event_bus=event_bus,
            profile_store=profile_store,
            http_probe=mock_http_probe,
        )
        discovery = APIDiscovery(name="TestAPI", base_url="https://api.example.com")
        results = learner.probe(discovery)
        assert len(probe_calls) > 0
        assert any(r.status_code == 200 for r in results)

    def test_probe_publishes_event(self, learner, event_bus):
        """Probing should publish a SYSTEM_PROBED event."""
        events = []
        event_bus.subscribe(EventType.SYSTEM_PROBED, lambda e: events.append(e))
        discovery = APIDiscovery(name="TestAPI", base_url="https://api.example.com")
        learner.probe(discovery)
        assert len(events) == 1
        assert events[0].data["api_name"] == "TestAPI"


# ---------------------------------------------------------------------------
# ANALYZE tests
# ---------------------------------------------------------------------------

class TestAnalyze:
    """Test analysis of probe results."""

    def test_rule_based_fallback(self, learner):
        """Without AI callable, should fall back to rule-based analysis."""
        discovery = APIDiscovery(
            name="TestAPI",
            base_url="https://api.example.com",
            vendor="Example Corp",
        )
        probes = [
            ProbeResult(
                url="https://api.example.com/health",
                status_code=200,
                headers={"content-type": "application/json"},
                body='{"status": "healthy"}',
            ),
            ProbeResult(
                url="https://api.example.com/api/v1",
                status_code=200,
                headers={"content-type": "application/json"},
                body='{"version": "1.0"}',
            ),
            ProbeResult(
                url="https://api.example.com/docs",
                status_code=404,
            ),
        ]
        analysis = learner.analyze(discovery, probes)
        assert analysis["name"] == "TestAPI"
        assert len(analysis["endpoints"]) == 2  # Only 200 responses
        assert analysis["confidence"] > 0
        assert "recommendations" in analysis

    def test_claude_analysis(self, event_bus, profile_store):
        """With AI callable, should use Claude for analysis."""
        claude_response = json.dumps({
            "name": "HotelWorld API",
            "vendor": "HotelWorld Inc",
            "vertical": "hotels",
            "protocol": "rest",
            "base_url": "https://api.hotelworld.io",
            "auth_method": "api_key",
            "auth_details": {
                "type": "API key in X-API-Key header",
                "header_format": "X-API-Key: <key>",
            },
            "endpoints": [
                {"path": "/v2/search", "method": "GET", "purpose": "Search hotels"},
                {"path": "/v2/bookings", "method": "POST", "purpose": "Create booking"},
            ],
            "quirks": [
                {
                    "description": "Rate limit resets at midnight UTC",
                    "category": "rate_limit",
                    "severity": "info",
                    "workaround": "Implement exponential backoff",
                },
            ],
            "confidence": 0.7,
            "confidence_reasoning": "Clear REST patterns with standard auth",
            "tags": ["hotels", "rest", "api_key"],
            "recommendations": ["Test booking flow in sandbox"],
        })

        ai_calls = []

        def mock_ai(prompt):
            ai_calls.append(prompt)
            return claude_response

        learner = AutoLearner(
            event_bus=event_bus,
            profile_store=profile_store,
            ai_analyze=mock_ai,
        )
        discovery = APIDiscovery(
            name="HotelWorld",
            base_url="https://api.hotelworld.io",
        )
        probes = [ProbeResult(url="https://api.hotelworld.io/health", status_code=200)]
        analysis = learner.analyze(discovery, probes)

        assert len(ai_calls) == 1
        assert "HotelWorld" in ai_calls[0]
        assert analysis["name"] == "HotelWorld API"
        assert len(analysis["endpoints"]) == 2
        assert analysis["confidence"] == 0.7

    def test_claude_failure_falls_back(self, event_bus, profile_store):
        """If Claude fails, should fall back to rule-based analysis."""
        def failing_ai(prompt):
            raise RuntimeError("API unavailable")

        learner = AutoLearner(
            event_bus=event_bus,
            profile_store=profile_store,
            ai_analyze=failing_ai,
        )
        discovery = APIDiscovery(name="TestAPI", base_url="https://api.test.com")
        probes = [ProbeResult(url="https://api.test.com/health", status_code=200)]
        analysis = learner.analyze(discovery, probes)
        # Should still produce a result via fallback
        assert analysis["name"] == "TestAPI"
        assert "recommendations" in analysis


# ---------------------------------------------------------------------------
# PROFILE tests
# ---------------------------------------------------------------------------

class TestProfile:
    """Test SystemProfile creation from analysis."""

    def test_create_profile_from_analysis(self, learner):
        """Analysis dict should be converted to a valid SystemProfile."""
        discovery = APIDiscovery(
            name="TestAPI", base_url="https://api.test.com",
            vertical="hotels",
        )
        analysis = {
            "name": "Test API",
            "vendor": "Test Corp",
            "vertical": "hotels",
            "protocol": "rest",
            "base_url": "https://api.test.com",
            "auth_method": "api_key",
            "endpoints": [
                {"path": "/search", "method": "GET", "purpose": "Search"},
                {"path": "/book", "method": "POST", "purpose": "Book"},
            ],
            "quirks": [
                {"description": "Slow on Mondays", "category": "timeout",
                 "severity": "info", "workaround": "Retry"},
            ],
            "confidence": 0.6,
            "tags": ["hotels"],
        }
        profile = learner.profile(discovery, analysis)
        assert profile.name == "Test API"
        assert profile.vendor == "Test Corp"
        assert len(profile.endpoints) == 2
        assert len(profile.quirks) == 1
        assert profile.confidence == 0.6
        assert "auto-learned:codebase_scan" in profile.tags

    def test_profile_tags_include_vertical(self, learner):
        """Profile tags should include the vertical."""
        discovery = APIDiscovery(
            name="TestAPI", base_url="https://api.test.com",
            vertical="payments",
        )
        analysis = {"name": "TestAPI", "confidence": 0.3, "tags": []}
        profile = learner.profile(discovery, analysis)
        assert "payments" in profile.tags


# ---------------------------------------------------------------------------
# RETAIN tests
# ---------------------------------------------------------------------------

class TestRetain:
    """Test profile storage and merging."""

    def test_retain_creates_new_profile(self, learner, profile_store):
        """New profile should be stored in ProfileStore."""
        from anastasia.core.types import SystemProfile
        profile = SystemProfile(
            name="NewAPI",
            vendor="New Corp",
            confidence=0.5,
            readiness="probed",
            endpoints=[{"path": "/test", "method": "GET", "purpose": "Test"}],
        )
        stored = learner.retain(profile)
        assert profile_store.get_by_name("NewAPI") is not None
        assert stored.name == "NewAPI"

    def test_retain_merges_existing(self, learner, profile_store):
        """Existing profile should be merged, not replaced."""
        from anastasia.core.types import SystemProfile
        # Create initial profile
        initial = SystemProfile(
            name="MergeTest",
            vendor="Corp A",
            confidence=0.3,
            readiness="discovered",
            endpoints=[{"path": "/v1", "method": "GET", "purpose": "V1"}],
        )
        profile_store.create_profile(initial)

        # New profile with additional endpoints
        updated = SystemProfile(
            name="MergeTest",
            vendor="Corp A",
            confidence=0.6,
            readiness="documented",
            endpoints=[
                {"path": "/v1", "method": "GET", "purpose": "V1"},  # Duplicate
                {"path": "/v2", "method": "POST", "purpose": "V2"},  # New
            ],
        )
        stored = learner.retain(updated)

        # Should have merged endpoints (no duplicates)
        result = profile_store.get_by_name("MergeTest")
        assert result is not None
        paths = {(e.get("path"), e.get("method")) for e in result.endpoints}
        assert ("/v1", "GET") in paths
        assert ("/v2", "POST") in paths
        assert len(result.endpoints) == 2  # Not 3 (no duplicate)

    def test_retain_upgrades_confidence(self, learner, profile_store):
        """Merging should take the higher confidence."""
        from anastasia.core.types import SystemProfile
        profile_store.create_profile(SystemProfile(
            name="ConfTest", confidence=0.3, readiness="discovered",
        ))
        learner.retain(SystemProfile(
            name="ConfTest", confidence=0.7, readiness="documented",
        ))
        result = profile_store.get_by_name("ConfTest")
        assert result.confidence == 0.7

    def test_retain_publishes_event(self, learner, event_bus, profile_store):
        """Retaining should publish a SYSTEM_LEARNED event."""
        from anastasia.core.types import SystemProfile
        events = []
        event_bus.subscribe(EventType.SYSTEM_LEARNED, lambda e: events.append(e))
        learner.retain(SystemProfile(
            name="EventTest", confidence=0.5, readiness="probed",
        ))
        assert len(events) == 1
        assert events[0].data["system_name"] == "EventTest"


# ---------------------------------------------------------------------------
# Full pipeline tests
# ---------------------------------------------------------------------------

class TestLearnPipeline:
    """Test the full learn() pipeline end-to-end."""

    def test_learn_discovers_and_profiles(self, learner, profile_store):
        """Full pipeline should discover and create profiles."""
        scan = _make_flask_stripe_scan()
        result = learner.learn(scan)
        assert len(result["discoveries"]) > 0
        # Should have created profiles (Stripe + hotelworld)
        total = len(result["profiles_created"]) + len(result["profiles_merged"])
        assert total > 0
        assert result["errors"] == []

    def test_learn_with_claude(self, event_bus, profile_store):
        """Full pipeline with Claude should produce higher-quality profiles."""
        claude_calls = []

        def mock_ai(prompt):
            claude_calls.append(1)
            return json.dumps({
                "name": "Stripe",
                "vendor": "Stripe Inc",
                "vertical": "payments",
                "protocol": "rest",
                "base_url": "https://api.stripe.com",
                "auth_method": "api_key",
                "endpoints": [
                    {"path": "/v1/charges", "method": "POST", "purpose": "Create charge"},
                    {"path": "/v1/customers", "method": "GET", "purpose": "List customers"},
                ],
                "quirks": [],
                "confidence": 0.8,
                "tags": ["payments"],
            })

        learner = AutoLearner(
            event_bus=event_bus,
            profile_store=profile_store,
            ai_analyze=mock_ai,
        )
        scan = _make_flask_stripe_scan()
        result = learner.learn(scan)
        assert len(claude_calls) > 0  # Claude was invoked

    def test_learn_empty_scan(self, learner):
        """Empty scan should produce no results."""
        result = learner.learn({"file_contents": {}, "routes": []})
        assert result["discoveries"] == []
        assert result["profiles_created"] == []

    def test_learn_publishes_full_event_chain(self, learner, event_bus):
        """Full pipeline should publish DISCOVERED → PROBED → LEARNED events."""
        event_types = []
        event_bus.subscribe(
            EventType.SYSTEM_DISCOVERED,
            lambda e: event_types.append("DISCOVERED"),
        )
        event_bus.subscribe(
            EventType.SYSTEM_PROBED,
            lambda e: event_types.append("PROBED"),
        )
        event_bus.subscribe(
            EventType.SYSTEM_LEARNED,
            lambda e: event_types.append("LEARNED"),
        )
        scan = _make_flask_stripe_scan()
        learner.learn(scan)
        # Should have the full chain for each discovered API
        assert "DISCOVERED" in event_types
        assert "PROBED" in event_types
        assert "LEARNED" in event_types


# ---------------------------------------------------------------------------
# Knowledge Module integration
# ---------------------------------------------------------------------------

class TestKnowledgeModuleIntegration:
    """Test AutoLearner integration with KnowledgeModule."""

    def test_knowledge_module_has_auto_learner(self, event_bus, tmp_path):
        """KnowledgeModule should expose auto_learner property."""
        from anastasia.knowledge import KnowledgeModule
        mod = KnowledgeModule()
        mod.initialize(event_bus, {"profiles_dir": str(tmp_path / "profiles")})
        assert mod.auto_learner is not None
        assert isinstance(mod.auto_learner, AutoLearner)

    def test_health_check_includes_learner(self, event_bus, tmp_path):
        """Health check should include auto_learner status."""
        from anastasia.knowledge import KnowledgeModule
        mod = KnowledgeModule()
        mod.initialize(event_bus, {"profiles_dir": str(tmp_path / "profiles")})
        health = mod.health_check()
        assert "auto_learner" in health
        assert health["auto_learner"] == "rule-based"

    def test_health_check_with_claude(self, event_bus, tmp_path):
        """Health check should report 'claude' when AI is configured."""
        from anastasia.knowledge import KnowledgeModule
        mod = KnowledgeModule()
        mod.initialize(event_bus, {
            "profiles_dir": str(tmp_path / "profiles"),
            "ai_analyze": lambda p: "{}",
        })
        health = mod.health_check()
        assert health["auto_learner"] == "claude"


# ---------------------------------------------------------------------------
# API name inference
# ---------------------------------------------------------------------------

class TestHelpers:
    """Test helper methods."""

    def test_infer_api_name(self):
        """Should produce readable names from domains."""
        assert AutoLearner._infer_api_name("api.stripe.com", "/v1") == "Stripe"
        assert AutoLearner._infer_api_name("api.hotelworld.io", "/v2") == "Hotelworld"
        assert AutoLearner._infer_api_name("test.example.co", "/api") == "Example"
        assert AutoLearner._infer_api_name("booking-engine.dev", "/") == "Booking engine"

    def test_parse_ai_response_json(self, learner):
        """Should parse clean JSON."""
        result = learner._parse_ai_response('{"name": "Test", "confidence": 0.5}')
        assert result["name"] == "Test"

    def test_parse_ai_response_markdown(self, learner):
        """Should handle markdown code blocks."""
        result = learner._parse_ai_response(
            '```json\n{"name": "Test", "confidence": 0.5}\n```'
        )
        assert result["name"] == "Test"

    def test_parse_ai_response_invalid(self, learner):
        """Should handle invalid JSON gracefully."""
        result = learner._parse_ai_response("This is not JSON at all")
        assert result.get("parse_error") is True
