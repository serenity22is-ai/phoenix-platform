"""
API Watchdog — Autonomous drift detection for all API providers.

Monitors every registered API provider for changes via 4 detection signals:

1. SCHEMA PROBING — Test queries against sandbox APIs, compare response
   schemas to stored baselines. If field names, types, or nesting change,
   drift is detected.

2. CHANGELOG MONITORING — Fetch provider documentation and changelog URLs.
   Claude Opus 4.6 reads the content and identifies what changed since the
   last check. Structured output: list of changes with severity.

3. ERROR-RATE DETECTION — Real-time EventBus subscriber. If a provider's
   error rate spikes (e.g., 3 failures in 5 min), trigger immediate
   re-analysis. Catches production-breaking changes that probing missed.

4. VERSION HEADER TRACKING — Extract API version headers from probe
   responses. Compare to stored version. If different, trigger analysis.

The Watchdog is part of the Knowledge neuron because keeping knowledge
current IS knowledge management. It feeds the UpdatePipeline when
drift is detected.

MYSTES KYRIOS LLC — Confidential.
"""

import hashlib
import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from ..core.events import Event, EventBus, EventType

logger = logging.getLogger("anastasia.knowledge.watchdog")


# =========================================================================
# DATA MODELS
# =========================================================================

@dataclass
class WatchdogConfig:
    """Configuration for monitoring a single API provider."""
    provider_id: str
    sandbox_credentials: Dict[str, str] = field(default_factory=dict)
    probe_endpoints: List[str] = field(default_factory=list)
    changelog_url: Optional[str] = None
    docs_url: Optional[str] = None
    check_interval_hours: int = 24
    error_rate_threshold: int = 3      # failures before alert
    error_rate_window_sec: int = 300   # 5 minutes


@dataclass
class SchemaSnapshot:
    """A snapshot of an API's response schema at a point in time."""
    provider_id: str
    endpoint: str
    captured_at: float = field(default_factory=time.time)
    schema_hash: str = ""
    field_names: List[str] = field(default_factory=list)
    field_types: Dict[str, str] = field(default_factory=dict)
    nested_paths: List[str] = field(default_factory=list)
    response_headers: Dict[str, str] = field(default_factory=dict)
    sample_keys: List[str] = field(default_factory=list)
    raw_schema: Dict[str, Any] = field(default_factory=dict)

    def compute_hash(self) -> str:
        """Compute a deterministic hash of the schema structure."""
        content = json.dumps({
            "fields": sorted(self.field_names),
            "types": dict(sorted(self.field_types.items())),
            "paths": sorted(self.nested_paths),
        }, sort_keys=True)
        self.schema_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
        return self.schema_hash

    def to_dict(self) -> dict:
        return {
            "provider_id": self.provider_id,
            "endpoint": self.endpoint,
            "captured_at": self.captured_at,
            "schema_hash": self.schema_hash,
            "field_names": self.field_names,
            "field_types": self.field_types,
            "nested_paths": self.nested_paths,
            "response_headers": self.response_headers,
            "sample_keys": self.sample_keys,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SchemaSnapshot":
        return cls(**{k: v for k, v in data.items()
                      if k in cls.__dataclass_fields__})


@dataclass
class SchemaDiff:
    """Differences between two schema snapshots."""
    provider_id: str
    endpoint: str
    fields_added: List[str] = field(default_factory=list)
    fields_removed: List[str] = field(default_factory=list)
    fields_type_changed: Dict[str, Tuple[str, str]] = field(default_factory=dict)
    paths_added: List[str] = field(default_factory=list)
    paths_removed: List[str] = field(default_factory=list)
    header_changes: Dict[str, Tuple[str, str]] = field(default_factory=dict)
    has_changes: bool = False

    @property
    def severity(self) -> str:
        """Classify change severity."""
        if self.fields_removed or self.fields_type_changed:
            return "breaking"
        if self.fields_added or self.paths_added:
            return "additive"
        if self.header_changes:
            return "cosmetic"
        return "none"


@dataclass
class ChangelogEntry:
    """A parsed changelog entry from a provider's docs."""
    date: str
    title: str
    description: str
    severity: str = "unknown"   # breaking, additive, cosmetic
    affected_endpoints: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "date": self.date,
            "title": self.title,
            "description": self.description,
            "severity": self.severity,
            "affected_endpoints": self.affected_endpoints,
        }


@dataclass
class DetectedChange:
    """A detected API change with evidence."""
    change_type: str    # field_added, field_removed, field_renamed, auth_changed, etc.
    severity: str       # breaking, additive, cosmetic
    description: str
    affected_files: List[str] = field(default_factory=list)
    evidence: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "change_type": self.change_type,
            "severity": self.severity,
            "description": self.description,
            "affected_files": self.affected_files,
            "evidence": self.evidence,
        }


@dataclass
class WatchdogReport:
    """Complete report from a provider check."""
    provider_id: str
    checked_at: float = field(default_factory=time.time)
    changes_detected: List[DetectedChange] = field(default_factory=list)
    schema_diffs: List[SchemaDiff] = field(default_factory=list)
    changelog_entries: List[ChangelogEntry] = field(default_factory=list)
    version_change: Optional[Tuple[str, str]] = None
    error: Optional[str] = None

    @property
    def severity(self) -> str:
        if any(c.severity == "breaking" for c in self.changes_detected):
            return "breaking"
        if any(c.severity == "additive" for c in self.changes_detected):
            return "additive"
        if self.changes_detected:
            return "cosmetic"
        return "none"

    @property
    def has_changes(self) -> bool:
        return len(self.changes_detected) > 0

    def to_dict(self) -> dict:
        return {
            "provider_id": self.provider_id,
            "checked_at": self.checked_at,
            "severity": self.severity,
            "has_changes": self.has_changes,
            "changes": [c.to_dict() for c in self.changes_detected],
            "schema_diffs_count": len(self.schema_diffs),
            "changelog_entries": [e.to_dict() for e in self.changelog_entries],
            "version_change": self.version_change,
            "error": self.error,
        }


@dataclass
class ProviderStatus:
    """Current monitoring status for a provider."""
    provider_id: str
    config: WatchdogConfig
    last_checked: Optional[float] = None
    last_report: Optional[WatchdogReport] = None
    baseline_schemas: Dict[str, SchemaSnapshot] = field(default_factory=dict)
    known_version: Optional[str] = None
    error_count_recent: int = 0
    is_healthy: bool = True

    def to_dict(self) -> dict:
        return {
            "provider_id": self.provider_id,
            "last_checked": self.last_checked,
            "last_severity": self.last_report.severity if self.last_report else "unknown",
            "known_version": self.known_version,
            "error_count_recent": self.error_count_recent,
            "is_healthy": self.is_healthy,
            "baselines_stored": len(self.baseline_schemas),
            "check_interval_hours": self.config.check_interval_hours,
        }


# =========================================================================
# SCHEMA EXTRACTION
# =========================================================================

def extract_schema_from_response(data: Any, prefix: str = "") -> Tuple[List[str], Dict[str, str], List[str]]:
    """Extract field names, types, and nested paths from an API response.

    Returns (field_names, field_types, nested_paths).
    """
    field_names = []
    field_types = {}
    nested_paths = []

    if isinstance(data, dict):
        for key, value in data.items():
            full_path = f"{prefix}.{key}" if prefix else key
            field_names.append(full_path)
            field_types[full_path] = type(value).__name__

            if isinstance(value, dict):
                nested_paths.append(full_path)
                sub_names, sub_types, sub_paths = extract_schema_from_response(value, full_path)
                field_names.extend(sub_names)
                field_types.update(sub_types)
                nested_paths.extend(sub_paths)
            elif isinstance(value, list) and value and isinstance(value[0], dict):
                nested_paths.append(f"{full_path}[]")
                sub_names, sub_types, sub_paths = extract_schema_from_response(value[0], f"{full_path}[]")
                field_names.extend(sub_names)
                field_types.update(sub_types)
                nested_paths.extend(sub_paths)

    return field_names, field_types, nested_paths


def compare_schemas(old: SchemaSnapshot, new: SchemaSnapshot) -> SchemaDiff:
    """Compare two schema snapshots and produce a diff."""
    old_fields = set(old.field_names)
    new_fields = set(new.field_names)

    diff = SchemaDiff(
        provider_id=old.provider_id,
        endpoint=old.endpoint,
        fields_added=sorted(new_fields - old_fields),
        fields_removed=sorted(old_fields - new_fields),
        paths_added=sorted(set(new.nested_paths) - set(old.nested_paths)),
        paths_removed=sorted(set(old.nested_paths) - set(new.nested_paths)),
    )

    # Check type changes for common fields
    common_fields = old_fields & new_fields
    for f in common_fields:
        old_type = old.field_types.get(f, "")
        new_type = new.field_types.get(f, "")
        if old_type and new_type and old_type != new_type:
            diff.fields_type_changed[f] = (old_type, new_type)

    # Check header changes
    for key in set(list(old.response_headers.keys()) + list(new.response_headers.keys())):
        old_val = old.response_headers.get(key, "")
        new_val = new.response_headers.get(key, "")
        if old_val != new_val:
            diff.header_changes[key] = (old_val, new_val)

    diff.has_changes = bool(
        diff.fields_added or diff.fields_removed or
        diff.fields_type_changed or diff.paths_added or
        diff.paths_removed or diff.header_changes
    )

    return diff


# =========================================================================
# API WATCHDOG
# =========================================================================

class APIWatchdog:
    """
    Autonomous API drift detection engine.

    Monitors all registered API providers for changes and publishes
    events when drift is detected. The UpdatePipeline subscribes to
    these events and orchestrates the update lifecycle.

    Part of the Knowledge neuron — keeping knowledge current IS
    knowledge management.
    """

    def __init__(
        self,
        event_bus: EventBus,
        storage_dir: Optional[str] = None,
        ai_analyze: Optional[Callable] = None,
        http_probe: Optional[Callable] = None,
        http_fetch: Optional[Callable] = None,
    ):
        """
        Args:
            event_bus: For publishing drift events and subscribing to errors.
            storage_dir: Where to persist schema baselines and history.
            ai_analyze: Callable(prompt, data) -> str. Claude Opus 4.6 analysis.
            http_probe: Callable(url, method, headers, body) -> dict. For probing APIs.
            http_fetch: Callable(url) -> str. For fetching changelogs/docs.
        """
        self._event_bus = event_bus
        self._storage_dir = Path(storage_dir) if storage_dir else Path("~/.anastasia/watchdog").expanduser()
        self._storage_dir.mkdir(parents=True, exist_ok=True)

        self._ai_analyze = ai_analyze
        self._http_probe = http_probe
        self._http_fetch = http_fetch

        # Provider registry
        self._providers: Dict[str, ProviderStatus] = {}

        # Error rate tracking (real-time)
        self._error_log: Dict[str, List[float]] = defaultdict(list)

        # Subscribe to API error events for real-time detection
        self._event_bus.subscribe(EventType.BOOKING_FAILED, self._on_api_error)
        self._event_bus.subscribe(EventType.INTEGRATION_FAILED, self._on_api_error)

        # Load persisted baselines
        self._load_baselines()

        logger.info("APIWatchdog initialized — storage: %s", self._storage_dir)

    # -----------------------------------------------------------------
    # PROVIDER REGISTRATION
    # -----------------------------------------------------------------

    def register_provider(self, config: WatchdogConfig) -> None:
        """Register a provider for monitoring."""
        self._providers[config.provider_id] = ProviderStatus(
            provider_id=config.provider_id,
            config=config,
        )
        logger.info("Watchdog monitoring: %s (interval: %dh)",
                     config.provider_id, config.check_interval_hours)

    def register_from_card_json(self, card_path: Path) -> Optional[WatchdogConfig]:
        """Register a provider from its JSON knowledge card.

        Reads the watchdog-specific fields (changelog_url, docs_url,
        sandbox_probe_endpoints) from the JSON card.
        """
        try:
            data = json.loads(card_path.read_text(encoding="utf-8"))
            config = WatchdogConfig(
                provider_id=data.get("module_id", ""),
                sandbox_credentials={
                    var: "" for var in data.get("credential_env_vars", [])
                },
                probe_endpoints=data.get("sandbox_probe_endpoints", []),
                changelog_url=data.get("changelog_url"),
                docs_url=data.get("docs_url"),
            )
            if config.provider_id:
                self.register_provider(config)
                return config
        except Exception as e:
            logger.error("Failed to register from card %s: %s", card_path, e)
        return None

    def get_provider_status(self, provider_id: str) -> Optional[ProviderStatus]:
        """Get current status for a provider."""
        return self._providers.get(provider_id)

    def list_providers(self) -> Dict[str, dict]:
        """List all monitored providers and their status."""
        return {pid: ps.to_dict() for pid, ps in self._providers.items()}

    # -----------------------------------------------------------------
    # SCHEDULED CHECKS
    # -----------------------------------------------------------------

    def check_all(self) -> Dict[str, WatchdogReport]:
        """Run checks for all registered providers.

        Returns a report for each provider. Only providers that are
        due for a check (based on check_interval_hours) are checked.
        """
        reports = {}
        now = time.time()

        for pid, status in self._providers.items():
            # Check if due
            if status.last_checked:
                hours_since = (now - status.last_checked) / 3600
                if hours_since < status.config.check_interval_hours:
                    logger.debug("Skipping %s — checked %.1fh ago", pid, hours_since)
                    continue

            report = self.check_provider(pid)
            reports[pid] = report

        return reports

    def check_provider(self, provider_id: str) -> WatchdogReport:
        """Run a full check on a specific provider.

        Combines all 4 detection signals:
        1. Schema probing (if http_probe available)
        2. Changelog monitoring (if http_fetch + ai_analyze available)
        3. Error-rate check (always — from EventBus data)
        4. Version header tracking (piggyback on schema probe)
        """
        status = self._providers.get(provider_id)
        if not status:
            return WatchdogReport(
                provider_id=provider_id,
                error=f"Provider {provider_id} not registered",
            )

        report = WatchdogReport(provider_id=provider_id)
        changes: List[DetectedChange] = []

        # Signal 1: Schema probing
        if self._http_probe and status.config.probe_endpoints:
            for endpoint in status.config.probe_endpoints:
                try:
                    new_schema = self.probe_schema(provider_id, endpoint)
                    baseline_key = f"{provider_id}:{endpoint}"
                    old_schema = status.baseline_schemas.get(baseline_key)

                    if old_schema:
                        diff = compare_schemas(old_schema, new_schema)
                        if diff.has_changes:
                            report.schema_diffs.append(diff)
                            changes.extend(
                                self._schema_diff_to_changes(diff, provider_id)
                            )
                    else:
                        # First probe — store as baseline
                        self.store_baseline(provider_id, endpoint, new_schema)

                    # Signal 4: Version header tracking
                    api_version = (
                        new_schema.response_headers.get("API-Version") or
                        new_schema.response_headers.get("X-API-Version") or
                        new_schema.response_headers.get("Duffel-Version") or
                        new_schema.response_headers.get("X-Version")
                    )
                    if api_version and status.known_version:
                        if api_version != status.known_version:
                            report.version_change = (status.known_version, api_version)
                            changes.append(DetectedChange(
                                change_type="version_bumped",
                                severity="additive",
                                description=f"API version changed: {status.known_version} → {api_version}",
                                evidence={"old": status.known_version, "new": api_version},
                            ))
                    if api_version:
                        status.known_version = api_version

                except Exception as e:
                    logger.warning("Schema probe failed for %s/%s: %s",
                                   provider_id, endpoint, e)

        # Signal 2: Changelog monitoring
        if self._http_fetch and self._ai_analyze and status.config.changelog_url:
            try:
                entries = self.check_changelog(provider_id)
                report.changelog_entries = entries
                for entry in entries:
                    if entry.severity in ("breaking", "additive"):
                        changes.append(DetectedChange(
                            change_type="changelog_update",
                            severity=entry.severity,
                            description=f"[{entry.date}] {entry.title}: {entry.description}",
                            affected_files=entry.affected_endpoints,
                            evidence={"source": "changelog", "date": entry.date},
                        ))
            except Exception as e:
                logger.warning("Changelog check failed for %s: %s", provider_id, e)

        # Signal 3: Error-rate detection
        error_rate = self._get_error_rate(provider_id)
        if error_rate >= status.config.error_rate_threshold:
            changes.append(DetectedChange(
                change_type="error_rate_spike",
                severity="breaking",
                description=f"Error rate spike: {error_rate} failures in "
                            f"{status.config.error_rate_window_sec}s",
                evidence={"error_count": error_rate,
                          "window_sec": status.config.error_rate_window_sec},
            ))
            self._event_bus.publish(Event(
                type=EventType.API_ERROR_RATE_SPIKE,
                source="watchdog",
                data={"provider_id": provider_id, "error_count": error_rate},
            ))

        report.changes_detected = changes

        # Update status
        status.last_checked = time.time()
        status.last_report = report
        status.is_healthy = report.severity == "none"

        # Persist baselines
        self._save_baselines()

        # Publish drift event if changes detected
        if report.has_changes:
            self._event_bus.publish(Event(
                type=EventType.API_DRIFT_DETECTED,
                source="watchdog",
                data={
                    "provider_id": provider_id,
                    "severity": report.severity,
                    "changes_count": len(changes),
                    "report": report.to_dict(),
                },
            ))
            logger.info(
                "API drift detected for %s: %d changes (%s)",
                provider_id, len(changes), report.severity,
            )

        return report

    # -----------------------------------------------------------------
    # SCHEMA PROBING
    # -----------------------------------------------------------------

    def probe_schema(self, provider_id: str, endpoint: str) -> SchemaSnapshot:
        """Probe an API endpoint and extract its response schema.

        Uses the configured http_probe callable to make a test request
        and extracts the JSON schema from the response.
        """
        if not self._http_probe:
            raise RuntimeError("No http_probe callable configured")

        # Make the probe request
        response = self._http_probe(provider_id, endpoint)

        # Extract schema from response
        response_data = response.get("data", response.get("body", {}))
        headers = response.get("headers", {})

        field_names, field_types, nested_paths = extract_schema_from_response(response_data)

        snapshot = SchemaSnapshot(
            provider_id=provider_id,
            endpoint=endpoint,
            field_names=field_names,
            field_types=field_types,
            nested_paths=nested_paths,
            response_headers=headers,
            sample_keys=list(response_data.keys()) if isinstance(response_data, dict) else [],
            raw_schema={"field_count": len(field_names), "nested_count": len(nested_paths)},
        )
        snapshot.compute_hash()

        return snapshot

    def store_baseline(self, provider_id: str, endpoint: str,
                       schema: SchemaSnapshot) -> None:
        """Store a schema snapshot as the baseline for future comparisons."""
        status = self._providers.get(provider_id)
        if status:
            baseline_key = f"{provider_id}:{endpoint}"
            status.baseline_schemas[baseline_key] = schema
            self._save_baselines()
            logger.info("Stored baseline for %s/%s (hash: %s)",
                        provider_id, endpoint, schema.schema_hash)

    # -----------------------------------------------------------------
    # CHANGELOG MONITORING
    # -----------------------------------------------------------------

    def check_changelog(self, provider_id: str) -> List[ChangelogEntry]:
        """Fetch and analyze a provider's changelog for recent changes."""
        status = self._providers.get(provider_id)
        if not status or not status.config.changelog_url:
            return []

        if not self._http_fetch or not self._ai_analyze:
            return []

        # Fetch the changelog page
        content = self._http_fetch(status.config.changelog_url)
        if not content:
            return []

        # Ask Claude to analyze it
        last_check = status.last_checked or (time.time() - 86400 * 30)
        prompt = (
            f"Analyze this API changelog for {provider_id}. "
            f"Identify changes since timestamp {last_check} "
            f"(approximately {time.strftime('%Y-%m-%d', time.localtime(last_check))}). "
            f"For each change, provide: date, title, description, severity "
            f"(breaking/additive/cosmetic), and affected endpoints. "
            f"Return as JSON array."
        )

        analysis = self._ai_analyze(prompt, content)

        # Parse the AI response
        entries = []
        try:
            if isinstance(analysis, str):
                analysis = json.loads(analysis)
            if isinstance(analysis, list):
                for item in analysis:
                    entries.append(ChangelogEntry(
                        date=item.get("date", ""),
                        title=item.get("title", ""),
                        description=item.get("description", ""),
                        severity=item.get("severity", "unknown"),
                        affected_endpoints=item.get("affected_endpoints", []),
                    ))
        except (json.JSONDecodeError, TypeError, AttributeError):
            logger.warning("Failed to parse changelog analysis for %s", provider_id)

        return entries

    # -----------------------------------------------------------------
    # ERROR-RATE DETECTION (REAL-TIME)
    # -----------------------------------------------------------------

    def _on_api_error(self, event: Event) -> None:
        """Handle API error events for real-time drift detection."""
        provider_id = event.data.get("provider_id", "")
        if not provider_id or provider_id not in self._providers:
            # Try to extract from source or module info
            provider_id = event.data.get("module_id", event.data.get("source", ""))

        if provider_id and provider_id in self._providers:
            now = time.time()
            self._error_log[provider_id].append(now)

            # Check if threshold exceeded
            status = self._providers[provider_id]
            rate = self._get_error_rate(provider_id)
            if rate >= status.config.error_rate_threshold:
                logger.warning(
                    "Error rate spike for %s: %d in %ds — triggering analysis",
                    provider_id, rate, status.config.error_rate_window_sec,
                )
                # Don't trigger full check here to avoid recursion —
                # the event is published and the UpdatePipeline handles it

    def _get_error_rate(self, provider_id: str) -> int:
        """Get recent error count for a provider within its window."""
        status = self._providers.get(provider_id)
        if not status:
            return 0

        window = status.config.error_rate_window_sec
        cutoff = time.time() - window

        # Clean old entries
        self._error_log[provider_id] = [
            t for t in self._error_log[provider_id] if t > cutoff
        ]

        return len(self._error_log[provider_id])

    # -----------------------------------------------------------------
    # HELPERS
    # -----------------------------------------------------------------

    def _schema_diff_to_changes(self, diff: SchemaDiff,
                                provider_id: str) -> List[DetectedChange]:
        """Convert a SchemaDiff into DetectedChange objects."""
        changes = []

        for f in diff.fields_added:
            changes.append(DetectedChange(
                change_type="field_added",
                severity="additive",
                description=f"New field in response: {f}",
                evidence={"field": f, "endpoint": diff.endpoint},
            ))

        for f in diff.fields_removed:
            changes.append(DetectedChange(
                change_type="field_removed",
                severity="breaking",
                description=f"Field removed from response: {f}",
                evidence={"field": f, "endpoint": diff.endpoint},
            ))

        for f, (old_t, new_t) in diff.fields_type_changed.items():
            changes.append(DetectedChange(
                change_type="field_type_changed",
                severity="breaking",
                description=f"Field type changed: {f} ({old_t} → {new_t})",
                evidence={"field": f, "old_type": old_t, "new_type": new_t},
            ))

        for key, (old_v, new_v) in diff.header_changes.items():
            changes.append(DetectedChange(
                change_type="header_changed",
                severity="cosmetic",
                description=f"Response header changed: {key} ({old_v} → {new_v})",
                evidence={"header": key, "old": old_v, "new": new_v},
            ))

        return changes

    # -----------------------------------------------------------------
    # PERSISTENCE
    # -----------------------------------------------------------------

    def _save_baselines(self) -> None:
        """Persist schema baselines to disk."""
        data = {}
        for pid, status in self._providers.items():
            data[pid] = {
                "known_version": status.known_version,
                "last_checked": status.last_checked,
                "baselines": {
                    key: snap.to_dict()
                    for key, snap in status.baseline_schemas.items()
                },
            }
        path = self._storage_dir / "baselines.json"
        try:
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as e:
            logger.error("Failed to save baselines: %s", e)

    def _load_baselines(self) -> None:
        """Load persisted schema baselines."""
        path = self._storage_dir / "baselines.json"
        if not path.exists():
            return

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            for pid, pdata in data.items():
                if pid in self._providers:
                    status = self._providers[pid]
                    status.known_version = pdata.get("known_version")
                    status.last_checked = pdata.get("last_checked")
                    for key, snap_data in pdata.get("baselines", {}).items():
                        status.baseline_schemas[key] = SchemaSnapshot.from_dict(snap_data)
        except Exception as e:
            logger.warning("Failed to load baselines: %s", e)

    def get_status(self) -> dict:
        """Get overall watchdog status."""
        return {
            "providers_monitored": len(self._providers),
            "providers": self.list_providers(),
            "storage_dir": str(self._storage_dir),
        }
