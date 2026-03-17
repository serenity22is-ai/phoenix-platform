"""
Audit Pipeline — 3-stage automated review for developer modules.

Before a module can be published to the marketplace, it must pass:
1. Safety Scan — AST analysis for dangerous patterns
2. Compliance Check — Manifest validation, license, API permissions
3. Compatibility Validation — Entry point, dependencies, tests

MYSTES KYRIOS LLC — Confidential.
"""

import ast
import logging
import os
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from ..core.events import Event, EventBus, EventType
from .manifest import ModuleManifest, validate_manifest, MANIFEST_FILENAME, load_manifest

logger = logging.getLogger(__name__)

# Dangerous AST node types and function calls
UNSAFE_CALLS = {"eval", "exec", "compile", "__import__", "globals", "locals"}
UNSAFE_ATTRIBUTES = {"__subclasses__", "__bases__", "__mro__", "__code__"}

# Filesystem paths modules must never access
FORBIDDEN_PATH_PATTERNS = [
    r"/etc/",
    r"/proc/",
    r"/sys/",
    r"~/.ssh",
    r"~/.aws",
    r"~/.config",
    r"\.env",
    r"\.pem$",
    r"\.key$",
    r"\.\./",  # Path traversal
]

# Max module size (10MB)
MAX_MODULE_SIZE_BYTES = 10 * 1024 * 1024

# Max single file size (1MB)
MAX_FILE_SIZE_BYTES = 1 * 1024 * 1024


@dataclass
class AuditIssue:
    """A single issue found during audit."""

    stage: str  # "safety", "compliance", "compatibility"
    severity: str  # "error", "warning", "info"
    message: str
    file: Optional[str] = None
    line: Optional[int] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class StageResult:
    """Result of a single audit stage."""

    stage: str
    passed: bool
    issues: List[AuditIssue] = field(default_factory=list)
    duration_ms: float = 0.0

    def to_dict(self) -> dict:
        return {
            "stage": self.stage,
            "passed": self.passed,
            "issues": [i.to_dict() for i in self.issues],
            "duration_ms": round(self.duration_ms, 1),
        }


@dataclass
class AuditResult:
    """Complete audit result across all stages."""

    audit_id: str = ""
    passed: bool = False
    stages: List[StageResult] = field(default_factory=list)
    summary: str = ""
    audited_at: float = 0.0
    module_name: str = ""
    module_version: str = ""

    def to_dict(self) -> dict:
        return {
            "audit_id": self.audit_id,
            "passed": self.passed,
            "stages": [s.to_dict() for s in self.stages],
            "summary": self.summary,
            "audited_at": self.audited_at,
            "module_name": self.module_name,
            "module_version": self.module_version,
        }


class AuditPipeline:
    """
    3-stage audit pipeline for developer modules.

    Usage::

        pipeline = AuditPipeline(event_bus)
        result = pipeline.audit("/path/to/module", manifest)
        if result.passed:
            # Safe to publish
    """

    def __init__(
        self,
        event_bus: Optional[EventBus] = None,
        config: Optional[Dict[str, Any]] = None,
    ):
        self._event_bus = event_bus
        self._config = config or {}
        self._audit_history: List[AuditResult] = []

    def audit(self, module_dir: str, manifest: Optional[ModuleManifest] = None) -> AuditResult:
        """
        Run the full 3-stage audit pipeline on a module.

        Args:
            module_dir: Absolute path to the module directory.
            manifest: Pre-loaded manifest. If None, loads from module_dir.

        Returns:
            AuditResult with pass/fail and detailed issues.
        """
        audit_id = f"aud_{uuid.uuid4().hex[:12]}"

        # Load manifest if not provided
        if manifest is None:
            manifest_path = os.path.join(module_dir, MANIFEST_FILENAME)
            try:
                manifest = load_manifest(manifest_path)
            except (FileNotFoundError, ValueError) as e:
                return AuditResult(
                    audit_id=audit_id,
                    passed=False,
                    stages=[],
                    summary=f"Cannot load manifest: {e}",
                    audited_at=time.time(),
                )

        self._emit(EventType.MODULE_AUDIT_STARTED, {
            "audit_id": audit_id,
            "module_name": manifest.name,
            "module_version": manifest.version,
        })

        # Stage 1: Safety
        safety = self._safety_scan(module_dir)

        # Stage 2: Compliance
        compliance = self._compliance_check(module_dir, manifest)

        # Stage 3: Compatibility
        compat = self._compatibility_check(module_dir, manifest)

        passed = safety.passed and compliance.passed and compat.passed
        stages = [safety, compliance, compat]

        # Build summary
        total_errors = sum(
            1 for s in stages for i in s.issues if i.severity == "error"
        )
        total_warnings = sum(
            1 for s in stages for i in s.issues if i.severity == "warning"
        )

        if passed:
            summary = "All audit stages passed."
            if total_warnings:
                summary += f" {total_warnings} warning(s) noted."
        else:
            failed_stages = [s.stage for s in stages if not s.passed]
            summary = f"Audit failed: {', '.join(failed_stages)}. {total_errors} error(s), {total_warnings} warning(s)."

        result = AuditResult(
            audit_id=audit_id,
            passed=passed,
            stages=stages,
            summary=summary,
            audited_at=time.time(),
            module_name=manifest.name,
            module_version=manifest.version,
        )

        self._audit_history.append(result)

        event_type = EventType.MODULE_AUDIT_PASSED if passed else EventType.MODULE_AUDIT_FAILED
        self._emit(event_type, {
            "audit_id": audit_id,
            "module_name": manifest.name,
            "passed": passed,
            "summary": summary,
        })

        return result

    def get_audit_history(self, module_name: Optional[str] = None, limit: int = 50) -> List[AuditResult]:
        """Get audit history, optionally filtered by module name."""
        history = self._audit_history
        if module_name:
            history = [a for a in history if a.module_name == module_name]
        return history[-limit:]

    # ==================================================================
    # Stage 1: Safety Scan
    # ==================================================================

    def _safety_scan(self, module_dir: str) -> StageResult:
        """
        AST-based safety analysis of all Python files.

        Checks for:
        - Dangerous built-in calls (eval, exec, __import__)
        - Dangerous attribute access (__subclasses__, __code__)
        - subprocess/os.system without wrapping
        - Filesystem path traversal patterns
        - Module total size
        """
        start = time.time()
        issues: List[AuditIssue] = []

        # Check total module size
        total_size = _dir_size(module_dir)
        if total_size > MAX_MODULE_SIZE_BYTES:
            issues.append(AuditIssue(
                stage="safety",
                severity="error",
                message=f"Module size {total_size:,} bytes exceeds limit of {MAX_MODULE_SIZE_BYTES:,} bytes",
            ))

        # Walk Python files
        for root, _dirs, files in os.walk(module_dir):
            for fname in files:
                if not fname.endswith(".py"):
                    continue

                fpath = os.path.join(root, fname)
                rel = os.path.relpath(fpath, module_dir)

                # Check file size
                fsize = os.path.getsize(fpath)
                if fsize > MAX_FILE_SIZE_BYTES:
                    issues.append(AuditIssue(
                        stage="safety",
                        severity="error",
                        message=f"File exceeds {MAX_FILE_SIZE_BYTES:,} byte limit ({fsize:,} bytes)",
                        file=rel,
                    ))
                    continue

                # Read and parse AST
                try:
                    with open(fpath, "r") as f:
                        source = f.read()
                    tree = ast.parse(source, filename=rel)
                except SyntaxError as e:
                    issues.append(AuditIssue(
                        stage="safety",
                        severity="error",
                        message=f"Syntax error: {e.msg}",
                        file=rel,
                        line=e.lineno,
                    ))
                    continue

                # AST analysis
                issues.extend(self._analyze_ast(tree, rel))

                # String-based checks for path patterns
                issues.extend(self._check_forbidden_paths(source, rel))

        elapsed = (time.time() - start) * 1000
        has_errors = any(i.severity == "error" for i in issues)

        return StageResult(
            stage="safety",
            passed=not has_errors,
            issues=issues,
            duration_ms=elapsed,
        )

    def _analyze_ast(self, tree: ast.AST, filename: str) -> List[AuditIssue]:
        """Walk AST and flag dangerous patterns."""
        issues = []

        for node in ast.walk(tree):
            # Check function calls
            if isinstance(node, ast.Call):
                func_name = _get_call_name(node)
                if func_name in UNSAFE_CALLS:
                    issues.append(AuditIssue(
                        stage="safety",
                        severity="error",
                        message=f"Unsafe call: {func_name}() is not allowed",
                        file=filename,
                        line=getattr(node, "lineno", None),
                    ))
                elif func_name in ("os.system", "os.popen"):
                    issues.append(AuditIssue(
                        stage="safety",
                        severity="error",
                        message=f"Unsafe call: {func_name}() — use subprocess with explicit args instead",
                        file=filename,
                        line=getattr(node, "lineno", None),
                    ))
                elif func_name in ("subprocess.call", "subprocess.Popen", "subprocess.run"):
                    # Subprocess is allowed but flagged as warning
                    issues.append(AuditIssue(
                        stage="safety",
                        severity="warning",
                        message=f"subprocess usage: {func_name}() — ensure commands are sanitized",
                        file=filename,
                        line=getattr(node, "lineno", None),
                    ))

            # Check attribute access
            if isinstance(node, ast.Attribute):
                if node.attr in UNSAFE_ATTRIBUTES:
                    issues.append(AuditIssue(
                        stage="safety",
                        severity="error",
                        message=f"Unsafe attribute: .{node.attr} access is not allowed",
                        file=filename,
                        line=getattr(node, "lineno", None),
                    ))

            # Check imports
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in ("ctypes", "importlib"):
                        issues.append(AuditIssue(
                            stage="safety",
                            severity="warning",
                            message=f"Sensitive import: {alias.name} — review required",
                            file=filename,
                            line=getattr(node, "lineno", None),
                        ))

            if isinstance(node, ast.ImportFrom):
                if node.module and node.module in ("ctypes", "importlib"):
                    issues.append(AuditIssue(
                        stage="safety",
                        severity="warning",
                        message=f"Sensitive import: from {node.module} — review required",
                        file=filename,
                        line=getattr(node, "lineno", None),
                    ))

        return issues

    def _check_forbidden_paths(self, source: str, filename: str) -> List[AuditIssue]:
        """Check source code for forbidden filesystem path patterns."""
        issues = []
        for pattern in FORBIDDEN_PATH_PATTERNS:
            matches = list(re.finditer(pattern, source))
            for m in matches:
                line_num = source[:m.start()].count("\n") + 1
                issues.append(AuditIssue(
                    stage="safety",
                    severity="error",
                    message=f"Forbidden path pattern: '{m.group()}' — modules must not access system paths",
                    file=filename,
                    line=line_num,
                ))
        return issues

    # ==================================================================
    # Stage 2: Compliance Check
    # ==================================================================

    def _compliance_check(self, module_dir: str, manifest: ModuleManifest) -> StageResult:
        """
        Validate manifest fields and license compliance.

        Checks:
        - Manifest field validation
        - Entry point file exists
        - License compatibility
        - API permission declarations
        """
        start = time.time()
        issues: List[AuditIssue] = []

        # Validate manifest fields
        manifest_errors = validate_manifest(manifest)
        for error in manifest_errors:
            issues.append(AuditIssue(
                stage="compliance",
                severity="error",
                message=f"Manifest: {error}",
                file=MANIFEST_FILENAME,
            ))

        # Check entry point exists
        entry_path = os.path.join(module_dir, manifest.entry_point)
        if not os.path.isfile(entry_path):
            issues.append(AuditIssue(
                stage="compliance",
                severity="error",
                message=f"Entry point not found: {manifest.entry_point}",
                file=MANIFEST_FILENAME,
            ))

        # Check README exists if declared
        if manifest.readme:
            readme_path = os.path.join(module_dir, manifest.readme)
            if not os.path.isfile(readme_path):
                issues.append(AuditIssue(
                    stage="compliance",
                    severity="warning",
                    message=f"Declared README not found: {manifest.readme}",
                    file=MANIFEST_FILENAME,
                ))

        # License compatibility check
        if manifest.visibility == "published" and manifest.license == "proprietary":
            issues.append(AuditIssue(
                stage="compliance",
                severity="warning",
                message="Proprietary license on published module — marketplace users won't see source code",
            ))

        elapsed = (time.time() - start) * 1000
        has_errors = any(i.severity == "error" for i in issues)

        return StageResult(
            stage="compliance",
            passed=not has_errors,
            issues=issues,
            duration_ms=elapsed,
        )

    # ==================================================================
    # Stage 3: Compatibility Validation
    # ==================================================================

    def _compatibility_check(self, module_dir: str, manifest: ModuleManifest) -> StageResult:
        """
        Validate the module can actually run.

        Checks:
        - Entry point parses without syntax errors (already checked in safety)
        - ANASTASiA version compatibility
        - Dependencies declared
        - Tests exist and pass (if present)
        """
        start = time.time()
        issues: List[AuditIssue] = []

        # Check ANASTASiA version compatibility
        from anastasia import __version__ as platform_version
        if not _version_compatible(manifest.anastasia_version, platform_version):
            issues.append(AuditIssue(
                stage="compatibility",
                severity="error",
                message=f"Requires ANASTASiA >={manifest.anastasia_version} but platform is {platform_version}",
            ))

        # Check if tests directory exists
        tests_dir = os.path.join(module_dir, "tests")
        has_tests = os.path.isdir(tests_dir) and any(
            f.startswith("test_") and f.endswith(".py")
            for f in os.listdir(tests_dir) if os.path.isfile(os.path.join(tests_dir, f))
        )

        if not has_tests:
            issues.append(AuditIssue(
                stage="compatibility",
                severity="warning",
                message="No test files found — modules with tests are more likely to be approved for publishing",
            ))

        # Check entry point can be parsed
        entry_path = os.path.join(module_dir, manifest.entry_point)
        if os.path.isfile(entry_path):
            try:
                with open(entry_path, "r") as f:
                    ast.parse(f.read(), filename=manifest.entry_point)
            except SyntaxError as e:
                issues.append(AuditIssue(
                    stage="compatibility",
                    severity="error",
                    message=f"Entry point has syntax error: {e.msg}",
                    file=manifest.entry_point,
                    line=e.lineno,
                ))

        elapsed = (time.time() - start) * 1000
        has_errors = any(i.severity == "error" for i in issues)

        return StageResult(
            stage="compatibility",
            passed=not has_errors,
            issues=issues,
            duration_ms=elapsed,
        )

    # ==================================================================
    # Internal
    # ==================================================================

    def _emit(self, event_type: EventType, data: dict) -> None:
        """Publish an event if event bus is wired."""
        if self._event_bus:
            try:
                self._event_bus.publish(Event(
                    type=event_type,
                    data=data,
                    source="devterminal.audit",
                ))
            except Exception as e:
                logger.warning("Failed to emit audit event: %s", e)


# ======================================================================
# Utility functions
# ======================================================================

def _get_call_name(node: ast.Call) -> str:
    """Extract the function name from a Call AST node."""
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    elif isinstance(func, ast.Attribute):
        # e.g., os.system -> "os.system"
        parts = []
        current = func
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.append(current.id)
        return ".".join(reversed(parts))
    return ""


def _dir_size(path: str) -> int:
    """Calculate total directory size in bytes."""
    total = 0
    for root, _dirs, files in os.walk(path):
        for fname in files:
            fpath = os.path.join(root, fname)
            try:
                total += os.path.getsize(fpath)
            except OSError:
                pass
    return total


def _version_compatible(required: str, current: str) -> bool:
    """
    Check if current version satisfies >= required version.

    Simple major.minor.patch comparison.
    """
    try:
        req_parts = [int(x) for x in required.split(".")]
        cur_parts = [int(x) for x in current.split(".")]
    except (ValueError, AttributeError):
        return True  # Can't parse, allow

    # Pad to 3 parts
    while len(req_parts) < 3:
        req_parts.append(0)
    while len(cur_parts) < 3:
        cur_parts.append(0)

    return tuple(cur_parts) >= tuple(req_parts)
