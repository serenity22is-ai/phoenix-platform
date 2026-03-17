"""
Tests for the APIWatchdog — autonomous drift detection for all API providers.

Tests cover:
- Schema extraction from response data (flat and nested)
- Schema comparison (no changes, additions, removals, type changes)
- SchemaSnapshot hash determinism and serialization round-trip
- SchemaDiff severity classification
- WatchdogReport severity and has_changes properties
- Provider registration (direct and from JSON knowledge card)
- Schema probing with mock HTTP callables
- Baseline persistence (save/load cycle)
- check_all respecting check_interval
- Error-rate detection via EventBus
- Changelog analysis with mock AI
- Drift event publication on detected changes

MYSTES KYRIOS LLC — Confidential.
"""

import json
import time

import pytest

from anastasia.core.events import EventBus, Event, EventType
from anastasia.knowledge.watchdog import (
    APIWatchdog,
    WatchdogConfig,
    SchemaSnapshot,
    SchemaDiff,
    WatchdogReport,
    DetectedChange,
    ChangelogEntry,
    extract_schema_from_response,
    compare_schemas,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def event_bus():
    return EventBus()


@pytest.fixture
def storage_dir(tmp_path):
    d = tmp_path / "watchdog_storage"
    d.mkdir()
    return d


@pytest.fixture
def watchdog(event_bus, storage_dir):
    return APIWatchdog(
        event_bus=event_bus,
        storage_dir=str(storage_dir),
    )


def _mock_http_probe(provider_id, endpoint):
    """Mock HTTP probe that returns a realistic flight search response."""
    return {
        "data": {
            "flights": [{"id": 1, "price": 100}],
        },
        "headers": {"API-Version": "2.0"},
    }


def _make_watchdog_config(provider_id="test_provider", **kwargs):
    """Helper to create a WatchdogConfig with sensible defaults."""
    defaults = {
        "provider_id": provider_id,
        "probe_endpoints": ["search"],
        "changelog_url": "https://example.com/changelog",
        "docs_url": "https://example.com/docs",
        "check_interval_hours": 24,
        "error_rate_threshold": 3,
        "error_rate_window_sec": 300,
    }
    defaults.update(kwargs)
    return WatchdogConfig(**defaults)


# ---------------------------------------------------------------------------
# Schema extraction tests
# ---------------------------------------------------------------------------

class TestExtractSchema:
    """Test extract_schema_from_response() for flat and nested data."""

    def test_extract_schema_simple(self):
        """Flat dict response should extract top-level field names and types."""
        data = {"id": 1, "name": "Test Flight", "price": 99.50, "available": True}
        field_names, field_types, nested_paths = extract_schema_from_response(data)

        assert sorted(field_names) == ["available", "id", "name", "price"]
        assert field_types["id"] == "int"
        assert field_types["name"] == "str"
        assert field_types["price"] == "float"
        assert field_types["available"] == "bool"
        assert nested_paths == []

    def test_extract_schema_nested(self):
        """Nested dict with arrays should produce dotted paths and array markers."""
        data = {
            "status": "ok",
            "data": {
                "flights": [
                    {"id": 1, "price": 100, "airline": "AA"},
                ],
                "count": 1,
            },
        }
        field_names, field_types, nested_paths = extract_schema_from_response(data)

        # Top-level fields
        assert "status" in field_names
        assert "data" in field_names

        # Nested dict path
        assert "data" in nested_paths

        # Array path
        assert "data.flights[]" in nested_paths

        # Fields inside array items
        assert "data.flights[].id" in field_names
        assert "data.flights[].price" in field_names
        assert "data.flights[].airline" in field_names

        # Nested field inside dict
        assert "data.count" in field_names

        # Types
        assert field_types["status"] == "str"
        assert field_types["data.count"] == "int"
        assert field_types["data.flights[].id"] == "int"


# ---------------------------------------------------------------------------
# Schema comparison tests
# ---------------------------------------------------------------------------

class TestCompareSchemas:
    """Test compare_schemas() for various diff scenarios."""

    def _make_snapshot(self, field_names, field_types, nested_paths=None,
                       response_headers=None):
        """Helper to create a SchemaSnapshot for comparison."""
        snap = SchemaSnapshot(
            provider_id="test",
            endpoint="search",
            field_names=field_names,
            field_types=field_types,
            nested_paths=nested_paths or [],
            response_headers=response_headers or {},
        )
        snap.compute_hash()
        return snap

    def test_compare_schemas_no_changes(self):
        """Identical schemas should produce a diff with no changes."""
        old = self._make_snapshot(
            field_names=["id", "name", "price"],
            field_types={"id": "int", "name": "str", "price": "float"},
        )
        new = self._make_snapshot(
            field_names=["id", "name", "price"],
            field_types={"id": "int", "name": "str", "price": "float"},
        )
        diff = compare_schemas(old, new)

        assert diff.has_changes is False
        assert diff.fields_added == []
        assert diff.fields_removed == []
        assert diff.fields_type_changed == {}
        assert diff.severity == "none"

    def test_compare_schemas_field_added(self):
        """New field in response should be detected as additive change."""
        old = self._make_snapshot(
            field_names=["id", "name"],
            field_types={"id": "int", "name": "str"},
        )
        new = self._make_snapshot(
            field_names=["id", "name", "currency"],
            field_types={"id": "int", "name": "str", "currency": "str"},
        )
        diff = compare_schemas(old, new)

        assert diff.has_changes is True
        assert "currency" in diff.fields_added
        assert diff.fields_removed == []
        assert diff.severity == "additive"

    def test_compare_schemas_field_removed(self):
        """Removed field should be detected as breaking change."""
        old = self._make_snapshot(
            field_names=["id", "name", "legacy_code"],
            field_types={"id": "int", "name": "str", "legacy_code": "str"},
        )
        new = self._make_snapshot(
            field_names=["id", "name"],
            field_types={"id": "int", "name": "str"},
        )
        diff = compare_schemas(old, new)

        assert diff.has_changes is True
        assert "legacy_code" in diff.fields_removed
        assert diff.severity == "breaking"

    def test_compare_schemas_type_changed(self):
        """Field type change should be detected as breaking change."""
        old = self._make_snapshot(
            field_names=["id", "price"],
            field_types={"id": "int", "price": "str"},
        )
        new = self._make_snapshot(
            field_names=["id", "price"],
            field_types={"id": "int", "price": "float"},
        )
        diff = compare_schemas(old, new)

        assert diff.has_changes is True
        assert "price" in diff.fields_type_changed
        assert diff.fields_type_changed["price"] == ("str", "float")
        assert diff.severity == "breaking"


# ---------------------------------------------------------------------------
# SchemaSnapshot tests
# ---------------------------------------------------------------------------

class TestSchemaSnapshot:
    """Test SchemaSnapshot hash and serialization."""

    def test_schema_snapshot_hash_deterministic(self):
        """Same data should always produce the same hash."""
        snap_a = SchemaSnapshot(
            provider_id="provider_x",
            endpoint="/search",
            field_names=["id", "name", "price"],
            field_types={"id": "int", "name": "str", "price": "float"},
            nested_paths=["data"],
        )
        snap_b = SchemaSnapshot(
            provider_id="provider_x",
            endpoint="/search",
            field_names=["price", "id", "name"],  # Different order
            field_types={"price": "float", "name": "str", "id": "int"},
            nested_paths=["data"],
        )
        hash_a = snap_a.compute_hash()
        hash_b = snap_b.compute_hash()

        assert hash_a == hash_b
        assert len(hash_a) == 16  # SHA-256 truncated to 16 chars

    def test_schema_snapshot_roundtrip(self):
        """to_dict/from_dict should produce an equivalent snapshot."""
        original = SchemaSnapshot(
            provider_id="provider_y",
            endpoint="/bookings",
            captured_at=1700000000.0,
            field_names=["booking_id", "status", "total"],
            field_types={"booking_id": "str", "status": "str", "total": "float"},
            nested_paths=["passengers[]"],
            response_headers={"API-Version": "3.1"},
            sample_keys=["booking_id", "status", "total"],
        )
        original.compute_hash()

        serialized = original.to_dict()
        restored = SchemaSnapshot.from_dict(serialized)

        assert restored.provider_id == original.provider_id
        assert restored.endpoint == original.endpoint
        assert restored.captured_at == original.captured_at
        assert restored.schema_hash == original.schema_hash
        assert restored.field_names == original.field_names
        assert restored.field_types == original.field_types
        assert restored.nested_paths == original.nested_paths
        assert restored.response_headers == original.response_headers
        assert restored.sample_keys == original.sample_keys


# ---------------------------------------------------------------------------
# SchemaDiff severity tests
# ---------------------------------------------------------------------------

class TestSchemaDiffSeverity:
    """Test SchemaDiff severity property classification."""

    def test_schema_diff_severity_none(self):
        """No changes should report severity 'none'."""
        diff = SchemaDiff(provider_id="test", endpoint="search")
        assert diff.severity == "none"
        assert diff.has_changes is False

    def test_schema_diff_severity_additive(self):
        """Added fields only should report severity 'additive'."""
        diff = SchemaDiff(
            provider_id="test",
            endpoint="search",
            fields_added=["new_field"],
            has_changes=True,
        )
        assert diff.severity == "additive"

    def test_schema_diff_severity_breaking(self):
        """Removed fields should report severity 'breaking'."""
        diff = SchemaDiff(
            provider_id="test",
            endpoint="search",
            fields_removed=["old_field"],
            has_changes=True,
        )
        assert diff.severity == "breaking"

    def test_schema_diff_severity_type_change_is_breaking(self):
        """Type changes should also report severity 'breaking'."""
        diff = SchemaDiff(
            provider_id="test",
            endpoint="search",
            fields_type_changed={"price": ("str", "float")},
            has_changes=True,
        )
        assert diff.severity == "breaking"

    def test_schema_diff_severity_header_only_is_cosmetic(self):
        """Header-only changes should report severity 'cosmetic'."""
        diff = SchemaDiff(
            provider_id="test",
            endpoint="search",
            header_changes={"X-Request-Id": ("abc", "def")},
            has_changes=True,
        )
        assert diff.severity == "cosmetic"


# ---------------------------------------------------------------------------
# WatchdogReport tests
# ---------------------------------------------------------------------------

class TestWatchdogReport:
    """Test WatchdogReport severity and has_changes properties."""

    def test_report_no_changes(self):
        """Empty report should have no changes and severity 'none'."""
        report = WatchdogReport(provider_id="test")
        assert report.has_changes is False
        assert report.severity == "none"

    def test_report_with_breaking_change(self):
        """Report with a breaking change should report severity 'breaking'."""
        report = WatchdogReport(
            provider_id="test",
            changes_detected=[
                DetectedChange(
                    change_type="field_removed",
                    severity="breaking",
                    description="Field removed",
                ),
            ],
        )
        assert report.has_changes is True
        assert report.severity == "breaking"


# ---------------------------------------------------------------------------
# APIWatchdog — provider registration tests
# ---------------------------------------------------------------------------

class TestWatchdogRegistration:
    """Test provider registration and listing."""

    def test_watchdog_register_provider(self, watchdog):
        """register_provider should add the provider to the list."""
        config = _make_watchdog_config("picasso")
        watchdog.register_provider(config)
        providers = watchdog.list_providers()

        assert "picasso" in providers
        assert providers["picasso"]["provider_id"] == "picasso"
        assert providers["picasso"]["check_interval_hours"] == 24

    def test_watchdog_register_from_json_card(self, watchdog, tmp_path):
        """register_from_card_json should parse a JSON knowledge card and register."""
        card_data = {
            "module_id": "test_provider",
            "name": "Test Provider",
            "credential_env_vars": ["TEST_API_KEY"],
            "sandbox_probe_endpoints": ["search"],
            "changelog_url": "https://example.com/changelog",
            "docs_url": "https://example.com/docs",
        }
        card_path = tmp_path / "test_card.json"
        card_path.write_text(json.dumps(card_data), encoding="utf-8")

        config = watchdog.register_from_card_json(card_path)

        assert config is not None
        assert config.provider_id == "test_provider"
        assert config.probe_endpoints == ["search"]
        assert config.changelog_url == "https://example.com/changelog"
        assert config.docs_url == "https://example.com/docs"
        assert "TEST_API_KEY" in config.sandbox_credentials

        providers = watchdog.list_providers()
        assert "test_provider" in providers

    def test_watchdog_register_from_invalid_json(self, watchdog, tmp_path):
        """register_from_card_json should return None for invalid JSON."""
        card_path = tmp_path / "bad_card.json"
        card_path.write_text("not valid json", encoding="utf-8")
        config = watchdog.register_from_card_json(card_path)
        assert config is None

    def test_watchdog_list_providers_empty(self, watchdog):
        """list_providers should return empty dict when no providers registered."""
        assert watchdog.list_providers() == {}


# ---------------------------------------------------------------------------
# APIWatchdog — check provider tests
# ---------------------------------------------------------------------------

class TestWatchdogCheckProvider:
    """Test provider checking with mock probes."""

    def test_watchdog_check_provider_no_probes(self, event_bus, storage_dir):
        """check_provider with no probe endpoints should return clean report."""
        watchdog = APIWatchdog(
            event_bus=event_bus,
            storage_dir=str(storage_dir),
        )
        config = _make_watchdog_config("no_probes", probe_endpoints=[])
        watchdog.register_provider(config)

        report = watchdog.check_provider("no_probes")

        assert report.provider_id == "no_probes"
        assert report.has_changes is False
        assert report.severity == "none"
        assert report.error is None

    def test_watchdog_check_provider_not_registered(self, watchdog):
        """check_provider for unknown provider should return error report."""
        report = watchdog.check_provider("unknown_provider")
        assert report.error is not None
        assert "not registered" in report.error

    def test_watchdog_check_provider_with_probe(self, event_bus, storage_dir):
        """check_provider with mock HTTP probe should extract schema baseline."""
        watchdog = APIWatchdog(
            event_bus=event_bus,
            storage_dir=str(storage_dir),
            http_probe=_mock_http_probe,
        )
        config = _make_watchdog_config("probed_provider")
        watchdog.register_provider(config)

        # First check — stores baseline
        report = watchdog.check_provider("probed_provider")

        assert report.provider_id == "probed_provider"
        assert report.error is None
        # First probe stores baseline, no drift expected
        assert report.has_changes is False

        # Verify baseline was stored
        status = watchdog.get_provider_status("probed_provider")
        assert len(status.baseline_schemas) == 1
        baseline_key = "probed_provider:search"
        assert baseline_key in status.baseline_schemas

    def test_watchdog_check_provider_detects_drift(self, event_bus, storage_dir):
        """Second check with changed response should detect schema drift."""
        call_count = {"n": 0}

        def evolving_probe(provider_id, endpoint):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return {
                    "data": {"flights": [{"id": 1, "price": 100}]},
                    "headers": {"API-Version": "2.0"},
                }
            else:
                # Response has changed — new field, removed field
                return {
                    "data": {"flights": [{"id": 1, "cost": 95.0, "currency": "USD"}]},
                    "headers": {"API-Version": "2.1"},
                }

        watchdog = APIWatchdog(
            event_bus=event_bus,
            storage_dir=str(storage_dir),
            http_probe=evolving_probe,
        )
        config = _make_watchdog_config("evolving")
        watchdog.register_provider(config)

        # First check — baseline
        report1 = watchdog.check_provider("evolving")
        assert report1.has_changes is False

        # Manually reset last_checked to allow second check
        status = watchdog.get_provider_status("evolving")
        status.last_checked = None

        # Second check — drift detected
        report2 = watchdog.check_provider("evolving")
        assert report2.has_changes is True
        assert len(report2.schema_diffs) > 0
        assert len(report2.changes_detected) > 0


# ---------------------------------------------------------------------------
# APIWatchdog — baseline persistence tests
# ---------------------------------------------------------------------------

class TestWatchdogPersistence:
    """Test schema baseline persistence (save/load cycle)."""

    def test_watchdog_schema_baseline_persistence(self, event_bus, storage_dir):
        """Baselines should survive save/load cycle."""
        # Create watchdog, register provider, store a baseline
        watchdog1 = APIWatchdog(
            event_bus=event_bus,
            storage_dir=str(storage_dir),
            http_probe=_mock_http_probe,
        )
        config = _make_watchdog_config("persist_test")
        watchdog1.register_provider(config)

        # Run a check to store baseline
        watchdog1.check_provider("persist_test")

        # Verify baseline file exists
        baselines_path = storage_dir / "baselines.json"
        assert baselines_path.exists()

        # Read and verify the persisted data
        saved_data = json.loads(baselines_path.read_text(encoding="utf-8"))
        assert "persist_test" in saved_data
        assert "baselines" in saved_data["persist_test"]
        assert len(saved_data["persist_test"]["baselines"]) == 1

        # Create a new watchdog that loads baselines
        event_bus2 = EventBus()
        watchdog2 = APIWatchdog(
            event_bus=event_bus2,
            storage_dir=str(storage_dir),
        )
        # Register the same provider so baselines can be loaded
        watchdog2.register_provider(config)
        watchdog2._load_baselines()

        status = watchdog2.get_provider_status("persist_test")
        assert len(status.baseline_schemas) == 1
        baseline_key = "persist_test:search"
        assert baseline_key in status.baseline_schemas
        assert status.baseline_schemas[baseline_key].provider_id == "persist_test"


# ---------------------------------------------------------------------------
# APIWatchdog — check_all interval tests
# ---------------------------------------------------------------------------

class TestWatchdogCheckAll:
    """Test check_all respecting check_interval."""

    def test_watchdog_check_all_skips_recently_checked(self, event_bus, storage_dir):
        """check_all should skip providers checked within their interval."""
        watchdog = APIWatchdog(
            event_bus=event_bus,
            storage_dir=str(storage_dir),
        )
        config = _make_watchdog_config("interval_test", check_interval_hours=24)
        watchdog.register_provider(config)

        # Simulate a recent check
        status = watchdog.get_provider_status("interval_test")
        status.last_checked = time.time()  # Just checked

        reports = watchdog.check_all()

        # Should be skipped — checked recently
        assert "interval_test" not in reports

    def test_watchdog_check_all_includes_due_providers(self, event_bus, storage_dir):
        """check_all should include providers that are due for a check."""
        watchdog = APIWatchdog(
            event_bus=event_bus,
            storage_dir=str(storage_dir),
        )
        config = _make_watchdog_config("due_test", check_interval_hours=1)
        watchdog.register_provider(config)

        # Simulate a check from 2 hours ago
        status = watchdog.get_provider_status("due_test")
        status.last_checked = time.time() - 7200  # 2 hours ago

        reports = watchdog.check_all()

        assert "due_test" in reports

    def test_watchdog_check_all_includes_never_checked(self, event_bus, storage_dir):
        """check_all should include providers that have never been checked."""
        watchdog = APIWatchdog(
            event_bus=event_bus,
            storage_dir=str(storage_dir),
        )
        config = _make_watchdog_config("never_checked")
        watchdog.register_provider(config)

        reports = watchdog.check_all()

        assert "never_checked" in reports


# ---------------------------------------------------------------------------
# APIWatchdog — error rate detection tests
# ---------------------------------------------------------------------------

class TestWatchdogErrorRate:
    """Test error-rate detection via EventBus."""

    def test_watchdog_error_rate_detection(self, event_bus, storage_dir):
        """Simulated API errors should increment the error rate counter."""
        watchdog = APIWatchdog(
            event_bus=event_bus,
            storage_dir=str(storage_dir),
        )
        config = _make_watchdog_config(
            "error_test",
            error_rate_threshold=3,
            error_rate_window_sec=300,
        )
        watchdog.register_provider(config)

        # Simulate 4 API errors via EventBus
        for i in range(4):
            event_bus.publish(Event(
                type=EventType.INTEGRATION_FAILED,
                source="test",
                data={"provider_id": "error_test", "error": f"Timeout #{i}"},
            ))

        rate = watchdog._get_error_rate("error_test")
        assert rate == 4

    def test_watchdog_error_rate_window_expiry(self, event_bus, storage_dir):
        """Errors outside the window should not be counted."""
        watchdog = APIWatchdog(
            event_bus=event_bus,
            storage_dir=str(storage_dir),
        )
        config = _make_watchdog_config(
            "expiry_test",
            error_rate_threshold=3,
            error_rate_window_sec=60,
        )
        watchdog.register_provider(config)

        # Inject old errors directly (before the window)
        old_time = time.time() - 120  # 2 minutes ago
        watchdog._error_log["expiry_test"] = [old_time, old_time + 1, old_time + 2]

        rate = watchdog._get_error_rate("expiry_test")
        assert rate == 0  # All expired

    def test_watchdog_error_rate_zero_for_unknown(self, watchdog):
        """Error rate for unknown provider should be 0."""
        rate = watchdog._get_error_rate("nonexistent")
        assert rate == 0

    def test_watchdog_check_provider_reports_error_spike(self, event_bus, storage_dir):
        """check_provider should detect error rate spike and report it."""
        watchdog = APIWatchdog(
            event_bus=event_bus,
            storage_dir=str(storage_dir),
        )
        config = _make_watchdog_config(
            "spike_test",
            probe_endpoints=[],  # No probes, just error-rate signal
            error_rate_threshold=3,
            error_rate_window_sec=300,
        )
        watchdog.register_provider(config)

        # Inject recent errors
        now = time.time()
        watchdog._error_log["spike_test"] = [now - 10, now - 5, now - 1]

        report = watchdog.check_provider("spike_test")

        assert report.has_changes is True
        assert any(c.change_type == "error_rate_spike" for c in report.changes_detected)
        assert report.severity == "breaking"


# ---------------------------------------------------------------------------
# APIWatchdog — changelog analysis tests
# ---------------------------------------------------------------------------

class TestWatchdogChangelog:
    """Test changelog monitoring with mock AI."""

    def test_watchdog_changelog_analysis(self, event_bus, storage_dir):
        """check_changelog should fetch content and parse AI analysis."""
        fetch_calls = []
        ai_calls = []

        def mock_http_fetch(url):
            fetch_calls.append(url)
            return "<html><h2>2026-03-01: New endpoint /v3/search</h2></html>"

        def mock_ai_analyze(prompt, content):
            ai_calls.append(prompt)
            return json.dumps([
                {
                    "date": "2026-03-01",
                    "title": "New search endpoint",
                    "description": "Added /v3/search with improved filtering",
                    "severity": "additive",
                    "affected_endpoints": ["/v3/search"],
                },
            ])

        watchdog = APIWatchdog(
            event_bus=event_bus,
            storage_dir=str(storage_dir),
            ai_analyze=mock_ai_analyze,
            http_fetch=mock_http_fetch,
        )
        config = _make_watchdog_config(
            "changelog_test",
            changelog_url="https://example.com/changelog",
        )
        watchdog.register_provider(config)

        entries = watchdog.check_changelog("changelog_test")

        assert len(fetch_calls) == 1
        assert len(ai_calls) == 1
        assert len(entries) == 1
        assert entries[0].title == "New search endpoint"
        assert entries[0].severity == "additive"
        assert "/v3/search" in entries[0].affected_endpoints

    def test_watchdog_changelog_no_ai(self, event_bus, storage_dir):
        """check_changelog without AI callable should return empty list."""
        watchdog = APIWatchdog(
            event_bus=event_bus,
            storage_dir=str(storage_dir),
            http_fetch=lambda url: "some content",
            # No ai_analyze
        )
        config = _make_watchdog_config(
            "no_ai_test",
            changelog_url="https://example.com/changelog",
        )
        watchdog.register_provider(config)

        entries = watchdog.check_changelog("no_ai_test")
        assert entries == []

    def test_watchdog_changelog_no_url(self, watchdog):
        """check_changelog for provider with no changelog_url should return empty."""
        config = _make_watchdog_config("no_url", changelog_url=None)
        watchdog.register_provider(config)
        entries = watchdog.check_changelog("no_url")
        assert entries == []


# ---------------------------------------------------------------------------
# APIWatchdog — drift event publication tests
# ---------------------------------------------------------------------------

class TestWatchdogDriftEvents:
    """Test that drift detection publishes events on the EventBus."""

    def test_watchdog_drift_event_published(self, event_bus, storage_dir):
        """When schema drift is detected, an API_DRIFT_DETECTED event should be emitted."""
        call_count = {"n": 0}

        def changing_probe(provider_id, endpoint):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return {
                    "data": {"result": "ok", "count": 5},
                    "headers": {},
                }
            else:
                return {
                    "data": {"result": "ok", "count": 5, "new_field": "surprise"},
                    "headers": {},
                }

        watchdog = APIWatchdog(
            event_bus=event_bus,
            storage_dir=str(storage_dir),
            http_probe=changing_probe,
        )
        config = _make_watchdog_config("drift_test")
        watchdog.register_provider(config)

        # First check — baseline
        watchdog.check_provider("drift_test")

        # Capture events
        drift_events = []
        event_bus.subscribe(
            EventType.API_DRIFT_DETECTED,
            lambda e: drift_events.append(e),
        )

        # Reset last_checked so second check runs
        status = watchdog.get_provider_status("drift_test")
        status.last_checked = None

        # Second check — drift
        report = watchdog.check_provider("drift_test")

        assert report.has_changes is True
        assert len(drift_events) == 1
        assert drift_events[0].type == EventType.API_DRIFT_DETECTED
        assert drift_events[0].data["provider_id"] == "drift_test"
        assert drift_events[0].data["severity"] == "additive"
        assert drift_events[0].data["changes_count"] > 0

    def test_watchdog_no_event_when_no_drift(self, event_bus, storage_dir):
        """When no drift is detected, no API_DRIFT_DETECTED event should be emitted."""
        watchdog = APIWatchdog(
            event_bus=event_bus,
            storage_dir=str(storage_dir),
        )
        config = _make_watchdog_config("stable", probe_endpoints=[])
        watchdog.register_provider(config)

        drift_events = []
        event_bus.subscribe(
            EventType.API_DRIFT_DETECTED,
            lambda e: drift_events.append(e),
        )

        watchdog.check_provider("stable")

        assert len(drift_events) == 0

    def test_watchdog_error_spike_publishes_event(self, event_bus, storage_dir):
        """Error rate spike should publish API_ERROR_RATE_SPIKE event."""
        spike_events = []
        event_bus.subscribe(
            EventType.API_ERROR_RATE_SPIKE,
            lambda e: spike_events.append(e),
        )

        watchdog = APIWatchdog(
            event_bus=event_bus,
            storage_dir=str(storage_dir),
        )
        config = _make_watchdog_config(
            "spike_event_test",
            probe_endpoints=[],
            error_rate_threshold=2,
            error_rate_window_sec=300,
        )
        watchdog.register_provider(config)

        # Inject errors above threshold
        now = time.time()
        watchdog._error_log["spike_event_test"] = [now - 5, now - 3, now - 1]

        watchdog.check_provider("spike_event_test")

        assert len(spike_events) == 1
        assert spike_events[0].data["provider_id"] == "spike_event_test"
        assert spike_events[0].data["error_count"] == 3


# ---------------------------------------------------------------------------
# APIWatchdog — version header tracking tests
# ---------------------------------------------------------------------------

class TestWatchdogVersionTracking:
    """Test API version header detection."""

    def test_version_header_stored(self, event_bus, storage_dir):
        """API-Version header should be stored on the provider status."""
        watchdog = APIWatchdog(
            event_bus=event_bus,
            storage_dir=str(storage_dir),
            http_probe=_mock_http_probe,  # Returns API-Version: 2.0
        )
        config = _make_watchdog_config("version_test")
        watchdog.register_provider(config)

        watchdog.check_provider("version_test")

        status = watchdog.get_provider_status("version_test")
        assert status.known_version == "2.0"

    def test_version_change_detected(self, event_bus, storage_dir):
        """Version header change should be reported in the check."""
        call_count = {"n": 0}

        def version_changing_probe(provider_id, endpoint):
            call_count["n"] += 1
            version = "2.0" if call_count["n"] == 1 else "3.0"
            return {
                "data": {"status": "ok"},
                "headers": {"API-Version": version},
            }

        watchdog = APIWatchdog(
            event_bus=event_bus,
            storage_dir=str(storage_dir),
            http_probe=version_changing_probe,
        )
        config = _make_watchdog_config("ver_change")
        watchdog.register_provider(config)

        # First check — sets version baseline
        watchdog.check_provider("ver_change")

        status = watchdog.get_provider_status("ver_change")
        status.last_checked = None

        # Second check — version changed
        report = watchdog.check_provider("ver_change")

        assert report.version_change == ("2.0", "3.0")
        assert report.has_changes is True
        assert any(c.change_type == "version_bumped" for c in report.changes_detected)
