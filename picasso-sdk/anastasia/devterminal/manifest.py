"""
Module Manifest — Metadata format for developer-built ANASTASiA modules.

Every developer module contains an `anastasia-module.json` manifest that
declares its identity, dependencies, permissions, and compatibility.
ANASTASiA uses this manifest to validate, audit, and publish modules.

MYSTES KYRIOS LLC — Confidential.
"""

import json
import logging
import os
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Valid module types
MODULE_TYPES = ("extension", "integration", "vertical", "tool")

# Valid licenses
VALID_LICENSES = ("proprietary", "MIT", "Apache-2.0", "BSD-3-Clause", "GPL-3.0")

# Valid visibility settings
VALID_VISIBILITY = ("private", "published")

# Semver pattern
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")

# Module name pattern: lowercase, hyphens, no spaces
MODULE_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{1,62}[a-z0-9]$")

MANIFEST_FILENAME = "anastasia-module.json"


@dataclass
class ModuleManifest:
    """
    Metadata for a developer-built ANASTASiA module.

    Serialized as ``anastasia-module.json`` in the module root.
    """

    name: str = ""
    version: str = "1.0.0"
    description: str = ""
    author: str = ""
    module_type: str = "extension"
    entry_point: str = "main.py"
    dependencies: List[str] = field(default_factory=list)
    anastasia_version: str = "1.0.0"
    api_permissions: List[str] = field(default_factory=list)
    license: str = "proprietary"
    visibility: str = "private"
    tags: List[str] = field(default_factory=list)
    readme: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a plain dict for JSON/API responses."""
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        """Serialize to pretty-printed JSON string."""
        return json.dumps(self.to_dict(), indent=indent)


def load_manifest(manifest_path: str) -> ModuleManifest:
    """
    Load a manifest from a JSON file.

    Args:
        manifest_path: Path to ``anastasia-module.json``.

    Returns:
        Parsed ModuleManifest.

    Raises:
        FileNotFoundError: If the manifest file doesn't exist.
        ValueError: If JSON is malformed or fields are invalid.
    """
    if not os.path.isfile(manifest_path):
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")

    with open(manifest_path, "r") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in manifest: {e}") from e

    if not isinstance(data, dict):
        raise ValueError("Manifest must be a JSON object")

    return ModuleManifest(
        name=data.get("name", ""),
        version=data.get("version", "1.0.0"),
        description=data.get("description", ""),
        author=data.get("author", ""),
        module_type=data.get("module_type", "extension"),
        entry_point=data.get("entry_point", "main.py"),
        dependencies=data.get("dependencies", []),
        anastasia_version=data.get("anastasia_version", "1.0.0"),
        api_permissions=data.get("api_permissions", []),
        license=data.get("license", "proprietary"),
        visibility=data.get("visibility", "private"),
        tags=data.get("tags", []),
        readme=data.get("readme"),
    )


def validate_manifest(manifest: ModuleManifest) -> List[str]:
    """
    Validate a manifest and return a list of errors.

    Returns:
        Empty list if valid, otherwise a list of error strings.
    """
    errors = []

    # Name
    if not manifest.name:
        errors.append("name is required")
    elif not MODULE_NAME_RE.match(manifest.name):
        errors.append(
            f"name '{manifest.name}' is invalid — must be lowercase, "
            f"3-64 chars, hyphens allowed, no spaces"
        )

    # Version
    if not SEMVER_RE.match(manifest.version):
        errors.append(
            f"version '{manifest.version}' is not valid semver (expected X.Y.Z)"
        )

    # Description
    if not manifest.description:
        errors.append("description is required")
    elif len(manifest.description) > 500:
        errors.append("description must be 500 characters or less")

    # Author
    if not manifest.author:
        errors.append("author is required")

    # Module type
    if manifest.module_type not in MODULE_TYPES:
        errors.append(
            f"module_type '{manifest.module_type}' is invalid — "
            f"must be one of: {', '.join(MODULE_TYPES)}"
        )

    # Entry point
    if not manifest.entry_point:
        errors.append("entry_point is required")

    # anastasia_version
    if not SEMVER_RE.match(manifest.anastasia_version):
        errors.append(
            f"anastasia_version '{manifest.anastasia_version}' is not valid semver"
        )

    # License
    if manifest.license not in VALID_LICENSES:
        errors.append(
            f"license '{manifest.license}' is invalid — "
            f"must be one of: {', '.join(VALID_LICENSES)}"
        )

    # Visibility
    if manifest.visibility not in VALID_VISIBILITY:
        errors.append(
            f"visibility '{manifest.visibility}' is invalid — "
            f"must be one of: {', '.join(VALID_VISIBILITY)}"
        )

    # Tags
    if len(manifest.tags) > 10:
        errors.append("maximum 10 tags allowed")

    return errors


def scaffold_module(
    name: str,
    module_type: str,
    workspace_dir: str,
    author: str = "",
    description: str = "",
) -> Dict[str, str]:
    """
    Create a new module directory with boilerplate.

    Args:
        name: Module name (lowercase, hyphens).
        module_type: One of MODULE_TYPES.
        workspace_dir: Parent directory where the module will be created.
        author: Author name or agency ID.
        description: Short description.

    Returns:
        Dict of created file paths -> descriptions.

    Raises:
        ValueError: If the module directory already exists.
    """
    module_dir = os.path.join(workspace_dir, name)
    if os.path.exists(module_dir):
        raise ValueError(f"Directory already exists: {module_dir}")

    os.makedirs(module_dir, exist_ok=True)
    os.makedirs(os.path.join(module_dir, "tests"), exist_ok=True)

    created = {}

    # Manifest
    manifest = ModuleManifest(
        name=name,
        version="0.1.0",
        description=description or f"ANASTASiA {module_type} module: {name}",
        author=author,
        module_type=module_type,
        entry_point="main.py",
        anastasia_version="1.0.0",
        license="proprietary",
        visibility="private",
        tags=[],
    )
    manifest_path = os.path.join(module_dir, MANIFEST_FILENAME)
    with open(manifest_path, "w") as f:
        f.write(manifest.to_json())
    created[manifest_path] = "Module manifest"

    # Entry point
    entry_path = os.path.join(module_dir, "main.py")
    entry_content = _generate_entry_point(name, module_type)
    with open(entry_path, "w") as f:
        f.write(entry_content)
    created[entry_path] = "Entry point"

    # README
    readme_path = os.path.join(module_dir, "README.md")
    with open(readme_path, "w") as f:
        f.write(f"# {name}\n\n{manifest.description}\n\n## Usage\n\nTODO\n")
    created[readme_path] = "README"

    # Test file
    test_path = os.path.join(module_dir, "tests", "test_main.py")
    with open(test_path, "w") as f:
        f.write(_generate_test_file(name))
    created[test_path] = "Test file"

    # .gitignore
    gitignore_path = os.path.join(module_dir, ".gitignore")
    with open(gitignore_path, "w") as f:
        f.write("__pycache__/\n*.pyc\n.env\n*.egg-info/\ndist/\nbuild/\n")
    created[gitignore_path] = ".gitignore"

    logger.info("Scaffolded module '%s' (%s) at %s", name, module_type, module_dir)
    return created


def _generate_entry_point(name: str, module_type: str) -> str:
    """Generate the main.py entry point for a module."""
    safe_name = name.replace("-", "_")
    return f'''"""
{name} — ANASTASiA {module_type} module.

This module extends the ANASTASiA platform. It runs within the
module sandbox and communicates with the core through the ANASTASiA API.
"""


def initialize(config: dict) -> dict:
    """
    Called when the module is loaded.

    Args:
        config: Module configuration from the host platform.

    Returns:
        Status dict with at minimum {{"ready": True/False}}.
    """
    return {{"ready": True, "module": "{name}"}}


def health_check() -> dict:
    """Return module health status."""
    return {{"healthy": True, "module": "{name}"}}
'''


def _generate_test_file(name: str) -> str:
    """Generate a basic test file for the module."""
    return f'''"""Tests for {name} module."""

from main import initialize, health_check


def test_initialize():
    result = initialize({{}})
    assert result["ready"] is True
    assert result["module"] == "{name}"


def test_health_check():
    result = health_check()
    assert result["healthy"] is True
'''
