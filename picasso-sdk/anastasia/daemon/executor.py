"""
Daemon Executor -- Command execution engine for customer infrastructure.

The executor is the hands of the daemon: it reads files, writes changes,
runs builds/tests, and manages git operations on behalf of ANASTASiA Cloud.
Every operation is permission-checked, audited, and backed up before
modification.

Security invariants:
- No operation proceeds without PermissionManager approval.
- All file modifications create timestamped backups in .anastasia-backups/.
- Shell commands are sandboxed to a configurable timeout.
- Git operations happen on isolated branches, never directly on main/master.

MYSTES KYRIOS LLC -- Confidential.
"""

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .permissions import PermissionManager

logger = logging.getLogger(__name__)


class DaemonExecutor:
    """
    Command execution engine for the ANASTASiA Daemon.

    Provides permission-checked file I/O, shell command execution, git
    operations, and test running within a designated workspace. All
    mutations are audited and reversible.

    Args:
        workspace_dir: Root directory of the customer's codebase.
        permissions: PermissionManager instance controlling access scope.
    """

    def __init__(self, workspace_dir: str, permissions: PermissionManager) -> None:
        self._workspace = os.path.abspath(workspace_dir)
        self._permissions = permissions
        self._backup_dir = os.path.join(self._workspace, ".anastasia-backups")
        self._audit_trail: List[Dict[str, Any]] = []
        self._max_audit_entries: int = 50000

        # Ensure backup directory exists
        os.makedirs(self._backup_dir, exist_ok=True)

        logger.info("DaemonExecutor initialized: workspace=%s", self._workspace)

    # ------------------------------------------------------------------
    # File operations
    # ------------------------------------------------------------------

    def read_file(self, path: str) -> str:
        """
        Read a file within the workspace, subject to permission checks.

        Args:
            path: Path to the file (absolute or relative to workspace).

        Returns:
            The file contents as a string.

        Raises:
            PermissionError: If the path is not allowed.
            FileNotFoundError: If the file does not exist.
            IOError: If the file cannot be read.
        """
        abs_path = self._resolve_path(path)

        if not self._permissions.is_path_allowed(abs_path):
            self._audit("read_file", abs_path, success=False, detail="Permission denied")
            raise PermissionError(f"Read access denied: {abs_path}")

        if not os.path.isfile(abs_path):
            self._audit("read_file", abs_path, success=False, detail="File not found")
            raise FileNotFoundError(f"File not found: {abs_path}")

        try:
            with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            self._audit("read_file", abs_path, success=True,
                        detail=f"Read {len(content)} chars")
            return content
        except Exception as e:
            self._audit("read_file", abs_path, success=False, detail=str(e))
            raise IOError(f"Failed to read {abs_path}: {e}") from e

    def write_file(self, path: str, content: str) -> bool:
        """
        Write content to a file, creating a backup of any existing file first.

        Args:
            path: Path to the file (absolute or relative to workspace).
            content: The content to write.

        Returns:
            True if the write succeeded.

        Raises:
            PermissionError: If the path or file type is not allowed.
        """
        abs_path = self._resolve_path(path)

        if not self._permissions.is_path_allowed(abs_path):
            self._audit("write_file", abs_path, success=False, detail="Path permission denied")
            raise PermissionError(f"Write access denied: {abs_path}")

        if not self._permissions.is_file_type_allowed(abs_path):
            self._audit("write_file", abs_path, success=False, detail="File type not allowed")
            raise PermissionError(f"File type not allowed: {abs_path}")

        is_new = not os.path.exists(abs_path)

        if is_new and not self._permissions.can_create_files():
            self._audit("write_file", abs_path, success=False,
                        detail="File creation not permitted")
            raise PermissionError("File creation is not permitted")

        # Backup existing file before overwriting
        if os.path.isfile(abs_path):
            self._create_backup(abs_path)

        try:
            # Ensure parent directory exists
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)

            with open(abs_path, "w", encoding="utf-8") as f:
                f.write(content)

            action = "created" if is_new else "modified"
            self._audit("write_file", abs_path, success=True,
                        detail=f"File {action}, {len(content)} chars")
            return True
        except Exception as e:
            self._audit("write_file", abs_path, success=False, detail=str(e))
            logger.error("Failed to write %s: %s", abs_path, e)
            return False

    def list_directory(self, path: str, recursive: bool = False) -> List[Dict[str, Any]]:
        """
        List files in a directory with metadata.

        Args:
            path: Directory path (absolute or relative to workspace).
            recursive: If True, list all files recursively.

        Returns:
            List of dicts, each with keys: name, path, type (file/dir),
            size, modified, extension.

        Raises:
            PermissionError: If the path is not allowed.
            FileNotFoundError: If the directory does not exist.
        """
        abs_path = self._resolve_path(path)

        if not self._permissions.is_path_allowed(abs_path):
            self._audit("list_directory", abs_path, success=False, detail="Permission denied")
            raise PermissionError(f"List access denied: {abs_path}")

        if not os.path.isdir(abs_path):
            self._audit("list_directory", abs_path, success=False, detail="Not a directory")
            raise FileNotFoundError(f"Directory not found: {abs_path}")

        entries: List[Dict[str, Any]] = []

        try:
            if recursive:
                for root, dirs, files in os.walk(abs_path):
                    # Skip hidden and blocked directories
                    dirs[:] = [
                        d for d in dirs
                        if not d.startswith(".") and
                        self._permissions.is_path_allowed(os.path.join(root, d))
                    ]
                    for name in files:
                        full_path = os.path.join(root, name)
                        if self._permissions.is_path_allowed(full_path):
                            entries.append(self._file_metadata(full_path))
            else:
                for name in sorted(os.listdir(abs_path)):
                    full_path = os.path.join(abs_path, name)
                    if self._permissions.is_path_allowed(full_path):
                        entries.append(self._file_metadata(full_path))

            self._audit("list_directory", abs_path, success=True,
                        detail=f"{len(entries)} entries, recursive={recursive}")
            return entries
        except Exception as e:
            self._audit("list_directory", abs_path, success=False, detail=str(e))
            raise

    # ------------------------------------------------------------------
    # Command execution
    # ------------------------------------------------------------------

    def execute_command(self, cmd: str, timeout: int = 60) -> Dict[str, Any]:
        """
        Execute a shell command within the workspace.

        The command is validated against the permission manager's command
        allowlist before execution. Runs with a configurable timeout and
        captures stdout, stderr, and exit code.

        Args:
            cmd: Shell command string to execute.
            timeout: Maximum seconds to wait (overridden by permissions if lower).

        Returns:
            Dict with keys: stdout, stderr, exit_code, duration_ms.

        Raises:
            PermissionError: If the command is not allowed.
        """
        if not self._permissions.is_command_allowed(cmd):
            self._audit("execute_command", cmd, success=False, detail="Command not allowed")
            raise PermissionError(f"Command not allowed: {cmd}")

        effective_timeout = min(timeout, self._permissions.command_timeout)
        start_time = time.monotonic()

        try:
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=effective_timeout,
                cwd=self._workspace,
                env=self._sanitized_env(),
            )
            duration_ms = int((time.monotonic() - start_time) * 1000)

            output = {
                "stdout": result.stdout,
                "stderr": result.stderr,
                "exit_code": result.returncode,
                "duration_ms": duration_ms,
            }

            self._audit("execute_command", cmd, success=(result.returncode == 0),
                        detail=f"exit={result.returncode}, {duration_ms}ms")
            return output

        except subprocess.TimeoutExpired:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            self._audit("execute_command", cmd, success=False,
                        detail=f"Timeout after {effective_timeout}s")
            return {
                "stdout": "",
                "stderr": f"Command timed out after {effective_timeout} seconds",
                "exit_code": -1,
                "duration_ms": duration_ms,
            }
        except Exception as e:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            self._audit("execute_command", cmd, success=False, detail=str(e))
            return {
                "stdout": "",
                "stderr": str(e),
                "exit_code": -1,
                "duration_ms": duration_ms,
            }

    # ------------------------------------------------------------------
    # Diff / patch operations
    # ------------------------------------------------------------------

    def apply_diff(self, file_path: str, diff_content: str) -> bool:
        """
        Apply a unified diff patch to a file.

        Creates a backup of the original file before applying the patch.
        Uses the system `patch` command with --dry-run validation first.

        Args:
            file_path: Path to the file to patch.
            diff_content: Unified diff content to apply.

        Returns:
            True if the patch was applied successfully.

        Raises:
            PermissionError: If the file path or type is not allowed.
        """
        abs_path = self._resolve_path(file_path)

        if not self._permissions.is_path_allowed(abs_path):
            self._audit("apply_diff", abs_path, success=False, detail="Permission denied")
            raise PermissionError(f"Patch access denied: {abs_path}")

        if not self._permissions.is_file_type_allowed(abs_path):
            self._audit("apply_diff", abs_path, success=False, detail="File type not allowed")
            raise PermissionError(f"File type not allowed for patching: {abs_path}")

        # Backup before patching
        if os.path.isfile(abs_path):
            self._create_backup(abs_path)

        # Write diff to a temporary file
        try:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".patch", delete=False) as tmp:
                tmp.write(diff_content)
                patch_file = tmp.name

            # Dry run first
            dry_run = subprocess.run(
                ["patch", "--dry-run", "-p0", abs_path],
                input=diff_content,
                capture_output=True,
                text=True,
                cwd=self._workspace,
                timeout=30,
            )

            if dry_run.returncode != 0:
                self._audit("apply_diff", abs_path, success=False,
                            detail=f"Dry run failed: {dry_run.stderr}")
                return False

            # Apply the patch
            result = subprocess.run(
                ["patch", "-p0", abs_path],
                input=diff_content,
                capture_output=True,
                text=True,
                cwd=self._workspace,
                timeout=30,
            )

            success = result.returncode == 0
            self._audit("apply_diff", abs_path, success=success,
                        detail=result.stderr if not success else "Patch applied")
            return success

        except Exception as e:
            self._audit("apply_diff", abs_path, success=False, detail=str(e))
            logger.error("Failed to apply diff to %s: %s", abs_path, e)
            return False
        finally:
            # Clean up temp patch file
            if "patch_file" in locals():
                try:
                    os.unlink(patch_file)
                except OSError:
                    pass

    # ------------------------------------------------------------------
    # Git operations
    # ------------------------------------------------------------------

    def create_git_branch(self, branch_name: str) -> bool:
        """
        Create and checkout a new git branch in the workspace.

        Args:
            branch_name: Name of the branch to create (sanitized).

        Returns:
            True if the branch was created and checked out.

        Raises:
            PermissionError: If git commands are not allowed.
        """
        # Sanitize branch name
        safe_name = branch_name.replace(" ", "-").replace("..", "").strip("/")

        if not self._permissions.is_command_allowed("git checkout"):
            self._audit("create_git_branch", safe_name, success=False,
                        detail="Git commands not allowed")
            raise PermissionError("Git commands are not allowed")

        result = self.execute_command(f"git checkout -b {safe_name}")
        success = result["exit_code"] == 0

        self._audit("create_git_branch", safe_name, success=success,
                    detail=result["stderr"] if not success else f"Branch created: {safe_name}")
        return success

    def commit_changes(self, message: str, files: List[str]) -> str:
        """
        Stage specified files and create a git commit.

        Args:
            message: Commit message.
            files: List of file paths to stage (relative or absolute).

        Returns:
            The commit SHA if successful, empty string on failure.

        Raises:
            PermissionError: If git commands are not allowed.
        """
        if not self._permissions.is_command_allowed("git add"):
            self._audit("commit_changes", message, success=False,
                        detail="Git commands not allowed")
            raise PermissionError("Git commands are not allowed")

        # Stage files individually
        for f in files:
            abs_f = self._resolve_path(f)
            if not self._permissions.is_path_allowed(abs_f):
                logger.warning("Skipping disallowed file in commit: %s", abs_f)
                continue

            # Make path relative to workspace for git
            try:
                rel_path = os.path.relpath(abs_f, self._workspace)
            except ValueError:
                rel_path = abs_f

            add_result = self.execute_command(f'git add "{rel_path}"')
            if add_result["exit_code"] != 0:
                logger.warning("git add failed for %s: %s", rel_path, add_result["stderr"])

        # Commit
        # Escape double quotes in commit message
        safe_msg = message.replace('"', '\\"')
        commit_result = self.execute_command(f'git commit -m "{safe_msg}"')

        if commit_result["exit_code"] != 0:
            self._audit("commit_changes", message, success=False,
                        detail=commit_result["stderr"])
            return ""

        # Extract commit SHA
        sha_result = self.execute_command("git rev-parse HEAD")
        sha = sha_result["stdout"].strip() if sha_result["exit_code"] == 0 else ""

        self._audit("commit_changes", message, success=True,
                    detail=f"SHA: {sha}, files: {len(files)}")
        return sha

    def run_tests(self, test_command: Optional[str] = None) -> Dict[str, Any]:
        """
        Run the project's test suite and return results.

        If no test command is provided, attempts to auto-detect the test
        framework by checking for common config files (pytest.ini, package.json,
        Cargo.toml, etc.).

        Args:
            test_command: Explicit test command to run. If None, auto-detect.

        Returns:
            Dict with keys: passed (bool), exit_code, stdout, stderr,
            duration_ms, command.

        Raises:
            PermissionError: If test execution is not allowed.
        """
        if not self._permissions.can_run_tests():
            self._audit("run_tests", test_command or "auto", success=False,
                        detail="Test execution not permitted")
            raise PermissionError("Test execution is not permitted")

        cmd = test_command or self._detect_test_command()

        if not cmd:
            self._audit("run_tests", "auto", success=False,
                        detail="Could not detect test framework")
            return {
                "passed": False,
                "exit_code": -1,
                "stdout": "",
                "stderr": "Could not detect test framework",
                "duration_ms": 0,
                "command": "",
            }

        # Run with extended timeout for test suites
        result = self.execute_command(cmd, timeout=self._permissions.command_timeout)

        test_result = {
            "passed": result["exit_code"] == 0,
            "exit_code": result["exit_code"],
            "stdout": result["stdout"],
            "stderr": result["stderr"],
            "duration_ms": result["duration_ms"],
            "command": cmd,
        }

        self._audit("run_tests", cmd, success=test_result["passed"],
                    detail=f"exit={result['exit_code']}, {result['duration_ms']}ms")
        return test_result

    def rollback_to(self, commit_sha: str) -> bool:
        """
        Rollback the workspace to a specific commit.

        Uses `git checkout <sha>` for a safe, detached-HEAD rollback.
        Does NOT use `git reset --hard` to avoid data loss.

        Args:
            commit_sha: The commit SHA to rollback to.

        Returns:
            True if the rollback succeeded.

        Raises:
            PermissionError: If git commands are not allowed.
        """
        if not self._permissions.is_command_allowed("git checkout"):
            self._audit("rollback_to", commit_sha, success=False,
                        detail="Git commands not allowed")
            raise PermissionError("Git commands are not allowed")

        # Validate SHA format (basic check)
        if not commit_sha or len(commit_sha) < 7:
            self._audit("rollback_to", commit_sha, success=False, detail="Invalid SHA")
            return False

        result = self.execute_command(f"git checkout {commit_sha}")
        success = result["exit_code"] == 0

        self._audit("rollback_to", commit_sha, success=success,
                    detail=result["stderr"] if not success else f"Rolled back to {commit_sha[:8]}")
        return success

    # ------------------------------------------------------------------
    # Codebase scanning
    # ------------------------------------------------------------------

    def scan_codebase(self) -> Dict[str, Any]:
        """
        Scan the workspace codebase and produce structured knowledge
        suitable for the bridge extractor.

        Walks the directory tree and extracts:
        - Tech stack (languages, frameworks, dependencies)
        - Route patterns (API endpoints)
        - Data model patterns
        - Auth configuration patterns
        - Integration points (webhooks, external APIs)

        Returns:
            Dict with keys: tech_stack, routes, models, auth_config,
            codebase_info, file_manifest.
        """
        self._audit("scan_codebase", self._workspace, success=True,
                    detail="Starting codebase scan")

        file_manifest = self._build_file_manifest()
        tech_stack = self._detect_tech_stack(file_manifest)
        routes = self._extract_routes(file_manifest, tech_stack)
        models = self._extract_models(file_manifest, tech_stack)
        auth_config = self._detect_auth(file_manifest)
        codebase_info = self._detect_integration_points(file_manifest)

        result = {
            "tech_stack": tech_stack,
            "routes": routes,
            "models": models,
            "auth_config": auth_config,
            "codebase_info": codebase_info,
            "file_manifest": {
                "total_files": len(file_manifest),
                "extensions": self._count_extensions(file_manifest),
                "total_size_bytes": sum(f.get("size", 0) for f in file_manifest),
            },
        }

        self._audit("scan_codebase", self._workspace, success=True,
                    detail=f"Scan complete: {len(file_manifest)} files, "
                           f"{len(routes)} routes, {len(models)} models")
        return result

    def delete_file(self, path: str) -> bool:
        """
        Delete a file within the workspace, with backup and permission check.

        Args:
            path: Path to the file (absolute or relative to workspace).

        Returns:
            True if the file was deleted.

        Raises:
            PermissionError: If the path is not allowed.
            FileNotFoundError: If the file does not exist.
        """
        abs_path = self._resolve_path(path)

        if not self._permissions.is_path_allowed(abs_path):
            self._audit("delete_file", abs_path, success=False,
                        detail="Permission denied")
            raise PermissionError(f"Delete access denied: {abs_path}")

        if not os.path.isfile(abs_path):
            self._audit("delete_file", abs_path, success=False,
                        detail="File not found")
            raise FileNotFoundError(f"File not found: {abs_path}")

        self._create_backup(abs_path)

        try:
            os.remove(abs_path)
            self._audit("delete_file", abs_path, success=True, detail="File deleted")
            return True
        except Exception as e:
            self._audit("delete_file", abs_path, success=False, detail=str(e))
            logger.error("Failed to delete %s: %s", abs_path, e)
            return False

    def _build_file_manifest(self) -> List[Dict[str, Any]]:
        """Walk workspace and build a file manifest with metadata."""
        manifest: List[Dict[str, Any]] = []
        skip_dirs = {
            ".git", "node_modules", "__pycache__", ".venv", "venv",
            ".anastasia-backups", ".tox", ".mypy_cache", "dist", "build",
            ".next", ".nuxt", "vendor", "target",
        }

        for root, dirs, files in os.walk(self._workspace):
            dirs[:] = [d for d in dirs if d not in skip_dirs and not d.startswith(".")]

            for name in files:
                full_path = os.path.join(root, name)
                rel_path = os.path.relpath(full_path, self._workspace)
                _, ext = os.path.splitext(name)

                try:
                    stat = os.stat(full_path)
                    manifest.append({
                        "name": name,
                        "path": rel_path,
                        "abs_path": full_path,
                        "extension": ext.lower(),
                        "size": stat.st_size,
                        "modified": stat.st_mtime,
                    })
                except OSError:
                    pass

        return manifest

    def _detect_tech_stack(self, manifest: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Detect languages, frameworks, and dependencies from file patterns."""
        extensions = self._count_extensions(manifest)
        filenames = {f["name"] for f in manifest}

        stack: Dict[str, Any] = {
            "languages": [],
            "frameworks": [],
            "databases": [],
            "dependencies": {},
        }

        lang_map = {
            ".py": "python", ".js": "javascript", ".ts": "typescript",
            ".rb": "ruby", ".go": "go", ".java": "java",
            ".rs": "rust", ".php": "php", ".cs": "csharp",
        }
        for ext, lang in lang_map.items():
            if extensions.get(ext, 0) > 0:
                stack["languages"].append(lang)

        # Parse dependency files
        dep_files = {
            "requirements.txt", "Pipfile", "pyproject.toml",
            "package.json", "Cargo.toml", "go.mod", "Gemfile",
            "composer.json", "pom.xml", "build.gradle",
        }
        for fname in dep_files:
            if fname in filenames:
                dep_file = next(
                    (f["abs_path"] for f in manifest if f["name"] == fname), None
                )
                if dep_file:
                    stack["dependencies"][fname] = self._parse_dependency_file(
                        dep_file, fname
                    )

        # Framework detection from file contents
        py_files = [f for f in manifest if f["extension"] == ".py"]
        js_files = [f for f in manifest if f["extension"] in (".js", ".ts")]

        py_sample = self._sample_file_contents(py_files, limit=10)
        js_sample = self._sample_file_contents(js_files, limit=10)

        for kw, fw in [("flask", "flask"), ("django", "django"), ("fastapi", "fastapi")]:
            if any(kw in c.lower() for c in py_sample):
                stack["frameworks"].append(fw)
        for kw, fw in [("express", "express"), ("next", "nextjs"), ("react", "react")]:
            if any(kw in c.lower() for c in js_sample):
                stack["frameworks"].append(fw)

        # Database detection
        all_sample = self._sample_file_contents(manifest, limit=20)
        combined = " ".join(all_sample).lower()
        for kw, db in [
            ("sqlalchemy", "postgresql"), ("mongoose", "mongodb"),
            ("sequelize", "postgresql"), ("prisma", "postgresql"),
            ("sqlite", "sqlite"), ("redis", "redis"),
        ]:
            if kw in combined and db not in stack["databases"]:
                stack["databases"].append(db)

        return stack

    def _extract_routes(
        self, manifest: List[Dict[str, Any]], tech_stack: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Extract API route patterns from source files."""
        routes: List[Dict[str, Any]] = []
        frameworks = tech_stack.get("frameworks", [])

        if any(fw in frameworks for fw in ("flask", "fastapi", "django")):
            for finfo in [f for f in manifest if f["extension"] == ".py"]:
                try:
                    with open(finfo["abs_path"], "r", encoding="utf-8", errors="replace") as f:
                        content = f.read()
                    routes.extend(self._parse_python_routes(content, finfo["path"]))
                except (IOError, OSError):
                    pass

        if "express" in frameworks:
            for finfo in [f for f in manifest if f["extension"] in (".js", ".ts")]:
                try:
                    with open(finfo["abs_path"], "r", encoding="utf-8", errors="replace") as f:
                        content = f.read()
                    routes.extend(self._parse_js_routes(content, finfo["path"]))
                except (IOError, OSError):
                    pass

        return routes

    def _extract_models(
        self, manifest: List[Dict[str, Any]], tech_stack: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Extract data model patterns from source files."""
        models: List[Dict[str, Any]] = []

        for finfo in [f for f in manifest if f["extension"] == ".py"]:
            try:
                with open(finfo["abs_path"], "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
                models.extend(self._parse_python_models(content, finfo["path"]))
            except (IOError, OSError):
                pass

        return models

    def _detect_auth(self, manifest: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Detect authentication configuration patterns."""
        auth: Dict[str, Any] = {"type": "unknown", "flow": "", "scopes": []}
        combined = " ".join(self._sample_file_contents(manifest, limit=20)).lower()

        if "oauth2" in combined or "oauth" in combined:
            auth["type"] = "oauth2"
            if "authorization_code" in combined:
                auth["flow"] = "authorization_code"
            elif "client_credentials" in combined:
                auth["flow"] = "client_credentials"
        elif "jwt" in combined or "jsonwebtoken" in combined:
            auth["type"] = "jwt"
            auth["flow"] = "bearer_token"
        elif "api_key" in combined or "apikey" in combined or "x-api-key" in combined:
            auth["type"] = "api_key"
            auth["flow"] = "header"
        elif "session" in combined and ("login" in combined or "cookie" in combined):
            auth["type"] = "session"
            auth["flow"] = "cookie"

        return auth

    def _detect_integration_points(
        self, manifest: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Detect integration points: webhooks, external APIs, queues."""
        info: Dict[str, Any] = {"webhooks": [], "external_apis": [], "queues": []}
        combined = " ".join(self._sample_file_contents(manifest, limit=30)).lower()

        if "webhook" in combined:
            info["webhooks"].append({
                "path": "/webhook", "events": ["payment", "booking"], "method": "POST",
            })

        for service, base_url in [
            ("stripe", "https://api.stripe.com"),
            ("paypal", "https://api.paypal.com"),
            ("twilio", "https://api.twilio.com"),
        ]:
            if service in combined:
                info["external_apis"].append({
                    "service": service, "base_url": base_url, "endpoints": [],
                })

        for pattern, provider in [
            ("rabbitmq", "rabbitmq"), ("celery", "celery"),
            ("sqs", "aws-sqs"), ("kafka", "kafka"),
        ]:
            if re.search(pattern, combined):
                info["queues"].append({"provider": provider, "topics": []})

        return info

    @staticmethod
    def _count_extensions(manifest: List[Dict[str, Any]]) -> Dict[str, int]:
        """Count files by extension."""
        counts: Dict[str, int] = {}
        for f in manifest:
            ext = f.get("extension", "")
            if ext:
                counts[ext] = counts.get(ext, 0) + 1
        return counts

    def _sample_file_contents(
        self, files: List[Dict[str, Any]], limit: int = 10
    ) -> List[str]:
        """Read the first 2KB of up to `limit` files for content analysis."""
        samples: List[str] = []
        for finfo in files[:limit]:
            abs_path = finfo.get("abs_path", "")
            if not abs_path or not os.path.isfile(abs_path):
                continue
            try:
                with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                    samples.append(f.read(2048))
            except (IOError, OSError):
                pass
        return samples

    def _parse_dependency_file(self, path: str, filename: str) -> List[str]:
        """Parse a dependency file and return package names."""
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except (IOError, OSError):
            return []

        if filename == "requirements.txt":
            return [
                line.split("==")[0].split(">=")[0].split("<=")[0].strip()
                for line in content.splitlines()
                if line.strip() and not line.startswith("#")
            ]
        elif filename == "package.json":
            try:
                data = json.loads(content)
                deps = list(data.get("dependencies", {}).keys())
                deps += list(data.get("devDependencies", {}).keys())
                return deps
            except (json.JSONDecodeError, ValueError):
                return []
        return []

    @staticmethod
    def _parse_python_routes(content: str, source_file: str) -> List[Dict[str, Any]]:
        """Extract Flask/FastAPI route definitions from Python source."""
        routes: List[Dict[str, Any]] = []

        flask_pattern = re.compile(
            r'@\w+\.route\(\s*["\']([^"\']+)["\']'
            r'(?:.*?methods\s*=\s*\[([^\]]+)\])?',
            re.DOTALL,
        )
        for match in flask_pattern.finditer(content):
            path = match.group(1)
            methods_str = match.group(2)
            methods = (
                [m.strip().strip("'\"") for m in methods_str.split(",")]
                if methods_str else ["GET"]
            )
            for method in methods:
                routes.append({
                    "path": path, "method": method.upper(),
                    "source_file": source_file, "purpose": "",
                    "auth_required": True,
                })

        fastapi_pattern = re.compile(
            r'@\w+\.(get|post|put|delete|patch)\(\s*["\']([^"\']+)["\']'
        )
        for match in fastapi_pattern.finditer(content):
            routes.append({
                "path": match.group(2), "method": match.group(1).upper(),
                "source_file": source_file, "purpose": "",
                "auth_required": True,
            })

        return routes

    @staticmethod
    def _parse_js_routes(content: str, source_file: str) -> List[Dict[str, Any]]:
        """Extract Express route definitions from JS/TS source."""
        routes: List[Dict[str, Any]] = []

        express_pattern = re.compile(
            r'(?:app|router)\.(get|post|put|delete|patch|all)'
            r'\(\s*["\']([^"\']+)["\']'
        )
        for match in express_pattern.finditer(content):
            routes.append({
                "path": match.group(2), "method": match.group(1).upper(),
                "source_file": source_file, "purpose": "",
                "auth_required": True,
            })

        return routes

    @staticmethod
    def _parse_python_models(content: str, source_file: str) -> List[Dict[str, Any]]:
        """Extract SQLAlchemy/Django model definitions from Python source."""
        models: List[Dict[str, Any]] = []

        model_pattern = re.compile(
            r'class\s+(\w+)\s*\([^)]*(?:db\.Model|Base|Model)[^)]*\)\s*:',
        )
        column_pattern = re.compile(
            r'(\w+)\s*=\s*(?:db\.)?Column\(\s*(?:db\.)?(\w+)',
        )

        for model_match in model_pattern.finditer(content):
            model_name = model_match.group(1)
            start = model_match.end()
            block = content[start:start + 3000]

            columns = []
            for col_match in column_pattern.finditer(block):
                col_name = col_match.group(1)
                col_type = col_match.group(2).lower()
                pk_check = block[col_match.start():col_match.end() + 100]
                columns.append({
                    "name": col_name, "type": col_type,
                    "nullable": True,
                    "primary_key": "primary_key" in pk_check,
                })

            if columns:
                models.append({
                    "name": model_name, "columns": columns,
                    "relationships": [], "source_file": source_file,
                })

        return models

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_path(self, path: str) -> str:
        """Resolve a path relative to the workspace, or return absolute as-is."""
        if os.path.isabs(path):
            return os.path.abspath(path)
        return os.path.abspath(os.path.join(self._workspace, path))

    def _create_backup(self, abs_path: str) -> Optional[str]:
        """
        Create a timestamped backup of a file in .anastasia-backups/.

        Preserves directory structure under the backup directory. Backup
        filenames include ISO timestamps for easy identification.

        Args:
            abs_path: Absolute path to the file to back up.

        Returns:
            Path to the backup file, or None if backup failed.
        """
        try:
            # Compute relative path from workspace for directory structure
            rel_path = os.path.relpath(abs_path, self._workspace)
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
            file_hash = hashlib.md5(abs_path.encode()).hexdigest()[:6]

            backup_name = f"{rel_path}.{timestamp}.{file_hash}.bak"
            backup_path = os.path.join(self._backup_dir, backup_name)

            # Ensure parent dir exists
            os.makedirs(os.path.dirname(backup_path), exist_ok=True)

            shutil.copy2(abs_path, backup_path)
            logger.debug("Backup created: %s -> %s", abs_path, backup_path)
            self._audit("backup", abs_path, success=True, detail=f"Backup: {backup_path}")
            return backup_path
        except Exception as e:
            logger.error("Backup failed for %s: %s", abs_path, e)
            self._audit("backup", abs_path, success=False, detail=str(e))
            return None

    def _file_metadata(self, path: str) -> Dict[str, Any]:
        """Build metadata dict for a file or directory."""
        try:
            stat = os.stat(path)
            _, ext = os.path.splitext(path)
            return {
                "name": os.path.basename(path),
                "path": path,
                "type": "dir" if os.path.isdir(path) else "file",
                "size": stat.st_size,
                "modified": stat.st_mtime,
                "extension": ext.lower() if ext else "",
            }
        except OSError:
            return {
                "name": os.path.basename(path),
                "path": path,
                "type": "unknown",
                "size": 0,
                "modified": 0,
                "extension": "",
            }

    def _detect_test_command(self) -> str:
        """
        Auto-detect the appropriate test command for the workspace.

        Checks for common test framework configuration files and returns
        the corresponding command.

        Returns:
            Test command string, or empty string if not detected.
        """
        checks = [
            ("pytest.ini", "pytest"),
            ("setup.cfg", "pytest"),
            ("pyproject.toml", "pytest"),
            ("tox.ini", "pytest"),
            ("package.json", "npm test"),
            ("jest.config.js", "npx jest"),
            ("jest.config.ts", "npx jest"),
            ("vitest.config.ts", "npx vitest run"),
            ("vitest.config.js", "npx vitest run"),
            ("Cargo.toml", "cargo test"),
            ("go.mod", "go test ./..."),
            ("Makefile", "make test"),
            ("Gemfile", "bundle exec rspec"),
            ("build.gradle", "./gradlew test"),
            ("pom.xml", "mvn test"),
        ]

        for config_file, command in checks:
            if os.path.isfile(os.path.join(self._workspace, config_file)):
                logger.info("Auto-detected test framework: %s -> %s", config_file, command)
                return command

        return ""

    def _sanitized_env(self) -> Dict[str, str]:
        """
        Create a sanitized environment for subprocess execution.

        Inherits the current environment but removes sensitive variables
        that should not be leaked to arbitrary commands.

        Returns:
            Sanitized environment dictionary.
        """
        env = os.environ.copy()
        sensitive_keys = [
            "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
            "STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET",
            "DATABASE_URL", "DATABASE_PASSWORD",
            "LITEAPI_KEY", "PICASSO_SESSION_TOKEN",
            "PICASSO_PASSWORD", "PICASSO_TOTP_SECRET",
            "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
            "GITHUB_TOKEN", "GITLAB_TOKEN",
            "SLACK_TOKEN", "DISCORD_TOKEN",
            "SENDGRID_API_KEY", "MAILGUN_API_KEY",
            "TWILIO_AUTH_TOKEN",
        ]
        for key in sensitive_keys:
            env.pop(key, None)
        return env

    # ------------------------------------------------------------------
    # Audit trail
    # ------------------------------------------------------------------

    def _audit(self, operation: str, target: str, success: bool, detail: str) -> None:
        """Record an operation in the audit trail."""
        entry = {
            "timestamp": time.time(),
            "operation": operation,
            "target": target,
            "success": success,
            "detail": detail,
        }
        self._audit_trail.append(entry)
        if len(self._audit_trail) > self._max_audit_entries:
            self._audit_trail = self._audit_trail[-self._max_audit_entries:]

        level = logging.INFO if success else logging.WARNING
        logger.log(level, "[AUDIT] %s %s: %s -- %s",
                   "OK" if success else "FAIL", operation, target, detail)

    def get_audit_trail(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Retrieve recent audit trail entries."""
        return self._audit_trail[-limit:]

    @property
    def workspace(self) -> str:
        """Return the workspace directory path."""
        return self._workspace

    @property
    def backup_dir(self) -> str:
        """Return the backup directory path."""
        return self._backup_dir
