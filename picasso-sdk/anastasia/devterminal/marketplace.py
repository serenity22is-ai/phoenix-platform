"""
Marketplace — Module publishing, discovery, and installation.

Filesystem-based module registry. Published modules are stored in
a marketplace directory with a JSON index for fast lookup. No external
database needed.

MYSTES KYRIOS LLC — Confidential.
"""

import json
import logging
import os
import shutil
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from ..core.events import Event, EventBus, EventType
from .audit_pipeline import AuditResult
from .manifest import MANIFEST_FILENAME, ModuleManifest, load_manifest

logger = logging.getLogger(__name__)

INDEX_FILENAME = "marketplace_index.json"


@dataclass
class ModuleListing:
    """A published module in the marketplace."""

    name: str = ""
    version: str = ""
    description: str = ""
    author: str = ""
    module_type: str = ""
    license: str = ""
    tags: List[str] = field(default_factory=list)
    published_at: float = 0.0
    download_count: int = 0
    audit_id: str = ""
    versions: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PublishResult:
    """Result of publishing a module."""

    success: bool = False
    module_name: str = ""
    version: str = ""
    marketplace_path: str = ""
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class InstallResult:
    """Result of installing a module."""

    success: bool = False
    module_name: str = ""
    version: str = ""
    installed_path: str = ""
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ModuleStats:
    """Usage statistics for a module."""

    name: str = ""
    total_downloads: int = 0
    versions: int = 0
    latest_version: str = ""
    published_at: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class Marketplace:
    """
    Module marketplace — publishing, discovery, and installation.

    Uses a filesystem-based storage model:
    - marketplace_dir/index.json — master index of all modules
    - marketplace_dir/{name}/{version}/ — module files per version

    Usage::

        marketplace = Marketplace(event_bus, config)
        result = marketplace.publish(module_dir, manifest, audit_result)
        listings = marketplace.search(query="loyalty")
        install = marketplace.install("loyalty-points", target_dir)
    """

    def __init__(
        self,
        event_bus: Optional[EventBus] = None,
        config: Optional[Dict[str, Any]] = None,
    ):
        self._event_bus = event_bus
        self._config = config or {}
        self._storage_dir = self._config.get(
            "marketplace_dir",
            os.path.join(self._config.get("data_dir", "."), "marketplace"),
        )
        self._index_path = os.path.join(self._storage_dir, INDEX_FILENAME)
        self._index: Dict[str, Dict[str, Any]] = {}

        # Ensure storage directory exists
        os.makedirs(self._storage_dir, exist_ok=True)

        # Load existing index
        self._load_index()

    # ==================================================================
    # Publishing
    # ==================================================================

    def publish(
        self,
        module_dir: str,
        manifest: ModuleManifest,
        audit_result: AuditResult,
    ) -> PublishResult:
        """
        Publish a module to the marketplace.

        Requires a passing audit result. Copies module files to the
        marketplace storage directory.

        Args:
            module_dir: Source module directory.
            manifest: Module manifest.
            audit_result: Passing AuditResult.

        Returns:
            PublishResult with success/failure details.
        """
        if not audit_result.passed:
            return PublishResult(
                success=False,
                module_name=manifest.name,
                version=manifest.version,
                error="Cannot publish: audit did not pass",
            )

        # Create versioned storage path
        version_dir = os.path.join(
            self._storage_dir, manifest.name, manifest.version
        )

        if os.path.exists(version_dir):
            return PublishResult(
                success=False,
                module_name=manifest.name,
                version=manifest.version,
                error=f"Version {manifest.version} already published. Bump the version number.",
            )

        try:
            # Copy module files to marketplace storage
            shutil.copytree(module_dir, version_dir)
        except Exception as e:
            return PublishResult(
                success=False,
                module_name=manifest.name,
                version=manifest.version,
                error=f"Failed to copy module: {e}",
            )

        # Update index
        now = time.time()
        if manifest.name in self._index:
            entry = self._index[manifest.name]
            if manifest.version not in entry.get("versions", []):
                entry["versions"].append(manifest.version)
            entry["latest_version"] = manifest.version
            entry["description"] = manifest.description
            entry["author"] = manifest.author
            entry["module_type"] = manifest.module_type
            entry["license"] = manifest.license
            entry["tags"] = manifest.tags
            entry["updated_at"] = now
            entry["audit_id"] = audit_result.audit_id
        else:
            self._index[manifest.name] = {
                "name": manifest.name,
                "latest_version": manifest.version,
                "versions": [manifest.version],
                "description": manifest.description,
                "author": manifest.author,
                "module_type": manifest.module_type,
                "license": manifest.license,
                "tags": manifest.tags,
                "published_at": now,
                "updated_at": now,
                "download_count": 0,
                "audit_id": audit_result.audit_id,
            }

        self._save_index()

        self._emit(EventType.MODULE_PUBLISHED, {
            "module_name": manifest.name,
            "version": manifest.version,
            "author": manifest.author,
            "audit_id": audit_result.audit_id,
        })

        logger.info("Published module '%s' v%s", manifest.name, manifest.version)

        return PublishResult(
            success=True,
            module_name=manifest.name,
            version=manifest.version,
            marketplace_path=version_dir,
        )

    def unpublish(self, module_name: str, version: Optional[str] = None) -> bool:
        """
        Remove a module or specific version from the marketplace.

        Args:
            module_name: Module name.
            version: Specific version to remove. If None, removes all versions.

        Returns:
            True if removed, False if not found.
        """
        if module_name not in self._index:
            return False

        if version:
            # Remove specific version
            version_dir = os.path.join(self._storage_dir, module_name, version)
            if os.path.exists(version_dir):
                shutil.rmtree(version_dir)

            entry = self._index[module_name]
            if version in entry.get("versions", []):
                entry["versions"].remove(version)

            # If no versions left, remove from index
            if not entry.get("versions"):
                del self._index[module_name]
                # Clean up module directory
                module_base = os.path.join(self._storage_dir, module_name)
                if os.path.exists(module_base):
                    shutil.rmtree(module_base)
            else:
                entry["latest_version"] = entry["versions"][-1]
        else:
            # Remove entire module
            module_base = os.path.join(self._storage_dir, module_name)
            if os.path.exists(module_base):
                shutil.rmtree(module_base)
            del self._index[module_name]

        self._save_index()

        self._emit(EventType.MODULE_UNPUBLISHED, {
            "module_name": module_name,
            "version": version,
        })

        logger.info("Unpublished module '%s' version=%s", module_name, version or "all")
        return True

    # ==================================================================
    # Discovery
    # ==================================================================

    def search(
        self,
        query: Optional[str] = None,
        tags: Optional[List[str]] = None,
        module_type: Optional[str] = None,
        author: Optional[str] = None,
    ) -> List[ModuleListing]:
        """
        Search published modules.

        Args:
            query: Text search in name and description.
            tags: Filter by tags (any match).
            module_type: Filter by type.
            author: Filter by author.

        Returns:
            List of matching ModuleListings.
        """
        results = []

        self._emit(EventType.MARKETPLACE_SEARCH, {
            "query": query,
            "tags": tags,
            "module_type": module_type,
        })

        for name, entry in self._index.items():
            # Text search
            if query:
                q_lower = query.lower()
                if (q_lower not in name.lower()
                        and q_lower not in entry.get("description", "").lower()):
                    continue

            # Tag filter
            if tags:
                entry_tags = set(entry.get("tags", []))
                if not entry_tags.intersection(set(tags)):
                    continue

            # Type filter
            if module_type and entry.get("module_type") != module_type:
                continue

            # Author filter
            if author and entry.get("author") != author:
                continue

            results.append(ModuleListing(
                name=name,
                version=entry.get("latest_version", ""),
                description=entry.get("description", ""),
                author=entry.get("author", ""),
                module_type=entry.get("module_type", ""),
                license=entry.get("license", ""),
                tags=entry.get("tags", []),
                published_at=entry.get("published_at", 0),
                download_count=entry.get("download_count", 0),
                audit_id=entry.get("audit_id", ""),
                versions=entry.get("versions", []),
            ))

        # Sort by download count descending
        results.sort(key=lambda x: x.download_count, reverse=True)

        return results

    def get_module(self, name: str, version: Optional[str] = None) -> Optional[ModuleListing]:
        """
        Get details for a specific module.

        Args:
            name: Module name.
            version: Specific version (default: latest).

        Returns:
            ModuleListing or None if not found.
        """
        entry = self._index.get(name)
        if not entry:
            return None

        return ModuleListing(
            name=name,
            version=version or entry.get("latest_version", ""),
            description=entry.get("description", ""),
            author=entry.get("author", ""),
            module_type=entry.get("module_type", ""),
            license=entry.get("license", ""),
            tags=entry.get("tags", []),
            published_at=entry.get("published_at", 0),
            download_count=entry.get("download_count", 0),
            audit_id=entry.get("audit_id", ""),
            versions=entry.get("versions", []),
        )

    def list_all(self, page: int = 1, per_page: int = 20) -> List[ModuleListing]:
        """List all published modules with pagination."""
        all_listings = self.search()
        start = (page - 1) * per_page
        return all_listings[start:start + per_page]

    # ==================================================================
    # Installation
    # ==================================================================

    def install(
        self,
        module_name: str,
        target_dir: str,
        version: Optional[str] = None,
    ) -> InstallResult:
        """
        Install a marketplace module to a target directory.

        Args:
            module_name: Module name.
            target_dir: Directory to install into.
            version: Specific version (default: latest).

        Returns:
            InstallResult with success/failure details.
        """
        entry = self._index.get(module_name)
        if not entry:
            return InstallResult(
                success=False,
                module_name=module_name,
                error=f"Module '{module_name}' not found in marketplace",
            )

        version = version or entry.get("latest_version", "")
        if version not in entry.get("versions", []):
            return InstallResult(
                success=False,
                module_name=module_name,
                version=version,
                error=f"Version '{version}' not found. Available: {', '.join(entry.get('versions', []))}",
            )

        source_dir = os.path.join(self._storage_dir, module_name, version)
        if not os.path.isdir(source_dir):
            return InstallResult(
                success=False,
                module_name=module_name,
                version=version,
                error="Module files not found in marketplace storage",
            )

        install_path = os.path.join(target_dir, module_name)
        if os.path.exists(install_path):
            # Remove existing installation
            shutil.rmtree(install_path)

        try:
            shutil.copytree(source_dir, install_path)
        except Exception as e:
            return InstallResult(
                success=False,
                module_name=module_name,
                version=version,
                error=f"Installation failed: {e}",
            )

        # Increment download count
        entry["download_count"] = entry.get("download_count", 0) + 1
        self._save_index()

        self._emit(EventType.MODULE_INSTALLED, {
            "module_name": module_name,
            "version": version,
            "installed_path": install_path,
        })

        logger.info("Installed module '%s' v%s to %s", module_name, version, install_path)

        return InstallResult(
            success=True,
            module_name=module_name,
            version=version,
            installed_path=install_path,
        )

    def uninstall(self, module_name: str, target_dir: str) -> bool:
        """
        Remove an installed module from a target directory.

        Returns True if removed, False if not found.
        """
        install_path = os.path.join(target_dir, module_name)
        if not os.path.exists(install_path):
            return False

        shutil.rmtree(install_path)

        self._emit(EventType.MODULE_UNINSTALLED, {
            "module_name": module_name,
            "target_dir": target_dir,
        })

        logger.info("Uninstalled module '%s' from %s", module_name, target_dir)
        return True

    # ==================================================================
    # Stats
    # ==================================================================

    def module_count(self) -> int:
        """Total number of published modules."""
        return len(self._index)

    def get_stats(self, module_name: str) -> Optional[ModuleStats]:
        """Get statistics for a module."""
        entry = self._index.get(module_name)
        if not entry:
            return None

        return ModuleStats(
            name=module_name,
            total_downloads=entry.get("download_count", 0),
            versions=len(entry.get("versions", [])),
            latest_version=entry.get("latest_version", ""),
            published_at=entry.get("published_at", 0),
        )

    # ==================================================================
    # Internal
    # ==================================================================

    def _load_index(self) -> None:
        """Load the marketplace index from disk."""
        if os.path.isfile(self._index_path):
            try:
                with open(self._index_path, "r") as f:
                    self._index = json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Failed to load marketplace index: %s", e)
                self._index = {}
        else:
            self._index = {}

    def _save_index(self) -> None:
        """Persist the marketplace index to disk."""
        try:
            with open(self._index_path, "w") as f:
                json.dump(self._index, f, indent=2)
        except OSError as e:
            logger.error("Failed to save marketplace index: %s", e)

    def _emit(self, event_type: EventType, data: dict) -> None:
        """Publish an event if event bus is wired."""
        if self._event_bus:
            try:
                self._event_bus.publish(Event(
                    type=event_type,
                    data=data,
                    source="devterminal.marketplace",
                ))
            except Exception as e:
                logger.warning("Failed to emit marketplace event: %s", e)
