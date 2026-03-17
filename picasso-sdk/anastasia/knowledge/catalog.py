"""
KnowledgeCatalog — Knowledge marketplace and system catalog.

Provides a queryable catalog of all known systems with readiness badges,
compatibility checks, and tech-stack-aware suggestions. Powers the admin
dashboard's "System Catalog" view and the integration wizard's system
selection step.

MYSTES KYRIOS LLC — Confidential.
"""

import logging
from typing import Any, Dict, List, Optional

from ..core.types import (
    AdapterPattern,
    SystemProfile,
    TechStack,
    VerticalType,
)
from ..core.events import Event, EventBus, EventType

from .profiles import ProfileStore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Readiness level configuration
# ---------------------------------------------------------------------------

_READINESS_CONFIG: Dict[str, Dict[str, Any]] = {
    "production": {
        "color": "green",
        "label": "Production Ready",
        "sort_order": 0,
        "description": "Fully tested and deployed in live installations.",
    },
    "tested": {
        "color": "blue",
        "label": "Tested",
        "sort_order": 1,
        "description": "Integration tested but not yet in production.",
    },
    "documented": {
        "color": "yellow",
        "label": "Documented",
        "sort_order": 2,
        "description": "API documented, booking flow mapped, awaiting testing.",
    },
    "probed": {
        "color": "orange",
        "label": "Probed",
        "sort_order": 3,
        "description": "Initial API exploration completed.",
    },
    "discovered": {
        "color": "gray",
        "label": "Discovered",
        "sort_order": 4,
        "description": "System identified but not yet explored.",
    },
}

# ---------------------------------------------------------------------------
# Known compatibility matrix: framework -> list of compatible adapters
# ---------------------------------------------------------------------------

_FRAMEWORK_ADAPTER_COMPAT: Dict[str, List[str]] = {
    "flask": ["python", "rest", "session_cookie", "jwt", "api_key"],
    "django": ["python", "rest", "session_cookie", "jwt", "api_key", "oauth2"],
    "fastapi": ["python", "rest", "jwt", "api_key", "oauth2"],
    "express": ["javascript", "rest", "jwt", "api_key", "oauth2", "session_cookie"],
    "nextjs": ["javascript", "rest", "jwt", "api_key", "oauth2"],
    "nestjs": ["typescript", "rest", "graphql", "jwt", "api_key", "oauth2"],
    "laravel": ["php", "rest", "session_cookie", "jwt", "api_key", "oauth2"],
    "symfony": ["php", "rest", "jwt", "api_key", "oauth2"],
    "spring": ["java", "rest", "soap", "jwt", "api_key", "oauth2", "saml"],
    "rails": ["ruby", "rest", "session_cookie", "jwt", "api_key", "oauth2"],
    "sinatra": ["ruby", "rest", "api_key", "jwt"],
    "gin": ["go", "rest", "jwt", "api_key"],
    "fiber": ["go", "rest", "jwt", "api_key"],
    "echo": ["go", "rest", "jwt", "api_key"],
    "actix": ["rust", "rest", "jwt", "api_key"],
    "axum": ["rust", "rest", "jwt", "api_key"],
    "rocket": ["rust", "rest", "jwt", "api_key"],
}


class KnowledgeCatalog:
    """
    Queryable catalog of all known travel systems.

    Wraps the ProfileStore with catalog-specific functionality:
    readiness badges, full-text search, compatibility checks, and
    tech-stack-aware suggestions.

    Args:
        event_bus: EventBus for publishing catalog events.
        profile_store: ProfileStore instance for accessing system profiles.
    """

    def __init__(self, event_bus: EventBus, profile_store: ProfileStore):
        self._event_bus = event_bus
        self._profile_store = profile_store

    # ------------------------------------------------------------------
    # Catalog listing
    # ------------------------------------------------------------------

    def list_systems(
        self,
        vertical: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        List all known systems with readiness badges.

        Returns a lightweight summary for each system suitable for
        rendering in the admin dashboard's catalog view.

        Args:
            vertical: Optional VerticalType value to filter by
                      (e.g. ``"flights"``, ``"hotels"``).

        Returns:
            List of system summary dicts, sorted by readiness level
            (production first) then alphabetically by name.
        """
        profiles = self._profile_store.search_profiles(vertical=vertical)
        systems = []

        for profile in profiles:
            badge = self.get_readiness_badge(profile)
            systems.append({
                "id": profile.id,
                "name": profile.name,
                "vendor": profile.vendor,
                "vertical": profile.vertical,
                "readiness": profile.readiness,
                "badge": badge,
                "confidence": profile.confidence,
                "installations": profile.installations,
                "endpoints_count": len(profile.endpoints),
                "quirks_count": len(profile.quirks),
                "adapters_count": len(profile.adapters),
                "tags": profile.tags,
                "last_updated": profile.last_updated,
            })

        # Sort by readiness (production first), then alphabetically
        systems.sort(key=lambda s: (
            _READINESS_CONFIG.get(
                s["readiness"], {"sort_order": 99}
            )["sort_order"],
            (s.get("name") or "").lower(),
        ))

        return systems

    # ------------------------------------------------------------------
    # Readiness badges
    # ------------------------------------------------------------------

    def get_readiness_badge(
        self,
        profile: SystemProfile,
    ) -> Dict[str, Any]:
        """
        Generate a readiness badge for a system profile.

        The badge includes a color code, human-readable label, and
        key metrics (endpoint count, quirk count, adapter count).

        Args:
            profile: The SystemProfile to badge.

        Returns:
            Badge dict with ``level``, ``color``, ``label``,
            ``endpoints``, ``quirks``, ``adapters``, ``confidence``,
            and ``description``.
        """
        readiness = profile.readiness or "discovered"
        config = _READINESS_CONFIG.get(readiness, _READINESS_CONFIG["discovered"])

        return {
            "level": readiness,
            "color": config["color"],
            "label": config["label"],
            "description": config["description"],
            "endpoints": len(profile.endpoints),
            "quirks": len(profile.quirks),
            "adapters": len(profile.adapters),
            "confidence": profile.confidence,
            "installations": profile.installations,
        }

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search_catalog(self, query: str) -> List[Dict[str, Any]]:
        """
        Full-text search across system names, vendors, tags, and URLs.

        Searches are case-insensitive and match partial strings. Results
        include readiness badges and are ranked by relevance (number of
        field matches) then confidence.

        Args:
            query: Search string (e.g. ``"picasso"``, ``"flights soap"``).

        Returns:
            List of matching system summary dicts with a ``relevance``
            score, sorted by relevance descending.
        """
        if not query or not query.strip():
            return self.list_systems()

        query_lower = query.lower().strip()
        query_terms = query_lower.split()

        all_profiles = self._profile_store.list_all()
        scored_results = []

        for profile in all_profiles:
            # Build searchable fields
            searchable_fields = {
                "name": (profile.name or "").lower(),
                "vendor": (profile.vendor or "").lower(),
                "vertical": (profile.vertical or "").lower(),
                "base_url": (profile.base_url or "").lower(),
                "protocol": (profile.protocol or "").lower(),
                "auth_method": (profile.auth_method or "").lower(),
                "tags": " ".join(profile.tags).lower(),
                "readiness": (profile.readiness or "").lower(),
            }

            # Score: count how many query terms match across fields
            relevance = 0
            for term in query_terms:
                for field_name, field_value in searchable_fields.items():
                    if term in field_value:
                        # Name matches are worth more
                        weight = 3 if field_name == "name" else 1
                        relevance += weight

            if relevance > 0:
                badge = self.get_readiness_badge(profile)
                scored_results.append({
                    "id": profile.id,
                    "name": profile.name,
                    "vendor": profile.vendor,
                    "vertical": profile.vertical,
                    "readiness": profile.readiness,
                    "badge": badge,
                    "confidence": profile.confidence,
                    "installations": profile.installations,
                    "endpoints_count": len(profile.endpoints),
                    "quirks_count": len(profile.quirks),
                    "adapters_count": len(profile.adapters),
                    "tags": profile.tags,
                    "last_updated": profile.last_updated,
                    "relevance": relevance,
                })

        # Sort by relevance descending, then confidence descending
        scored_results.sort(
            key=lambda s: (s["relevance"], s["confidence"]),
            reverse=True,
        )

        return scored_results

    # ------------------------------------------------------------------
    # Compatibility checks
    # ------------------------------------------------------------------

    def get_compatibility(
        self,
        system_name: str,
        tech_stack: TechStack,
    ) -> Dict[str, Any]:
        """
        Check whether ANASTASiA has adapters for a system + tech stack combo.

        Evaluates compatibility across three dimensions:
        - **Language**: Does the system have adapters in the customer's language?
        - **Protocol**: Can the customer's framework speak the system's protocol?
        - **Auth**: Can the customer's stack handle the system's auth method?

        Args:
            system_name: Name of the system to check (e.g. ``"Redbox"``).
            tech_stack: Detected TechStack of the customer's platform.

        Returns:
            Compatibility report with ``compatible`` (bool),
            ``score`` (0.0-1.0), ``checks`` (list of individual
            compatibility checks), and ``recommendations``.
        """
        profile = self._profile_store.get_by_name(system_name)
        if profile is None:
            return {
                "compatible": False,
                "score": 0.0,
                "system_found": False,
                "checks": [],
                "recommendations": [
                    f"System '{system_name}' not found in catalog. "
                    f"Use the learning pipeline to add it."
                ],
            }

        checks = []
        framework = tech_stack.framework.lower() if tech_stack.framework else ""
        language = tech_stack.language.lower() if tech_stack.language else ""

        # Get the compatibility set for the customer's framework
        compat_set = set(
            _FRAMEWORK_ADAPTER_COMPAT.get(framework, [])
        )
        # Also consider raw language compatibility
        if language:
            for fw, capabilities in _FRAMEWORK_ADAPTER_COMPAT.items():
                if language in capabilities:
                    compat_set.update(capabilities)
                    break

        # Check 1: Language compatibility
        lang_compatible = language in compat_set if language else False
        checks.append({
            "dimension": "language",
            "compatible": lang_compatible,
            "customer": language or "unknown",
            "system_requires": profile.protocol,
            "notes": (
                f"Language '{language}' is supported"
                if lang_compatible
                else f"No known adapter for '{language}' detected"
            ),
        })

        # Check 2: Protocol compatibility
        system_protocol = (profile.protocol or "rest").lower()
        protocol_compatible = system_protocol in compat_set if compat_set else (
            system_protocol == "rest"
        )
        checks.append({
            "dimension": "protocol",
            "compatible": protocol_compatible,
            "customer_framework": framework or "unknown",
            "system_protocol": system_protocol,
            "notes": (
                f"Framework '{framework}' supports {system_protocol}"
                if protocol_compatible
                else f"Framework '{framework}' may not natively support {system_protocol}"
            ),
        })

        # Check 3: Auth method compatibility
        system_auth = (profile.auth_method or "api_key").lower()
        auth_compatible = system_auth in compat_set if compat_set else (
            system_auth in ("api_key", "basic")
        )
        checks.append({
            "dimension": "auth",
            "compatible": auth_compatible,
            "customer_framework": framework or "unknown",
            "system_auth": system_auth,
            "notes": (
                f"Auth method '{system_auth}' is compatible with '{framework}'"
                if auth_compatible
                else f"Auth method '{system_auth}' may require custom adapter"
            ),
        })

        # Check 4: Existing adapters
        existing_adapters = [
            a for a in profile.adapters
            if a.language.lower() == language or a.target.lower() == framework
        ]
        has_adapters = bool(existing_adapters)
        checks.append({
            "dimension": "adapters",
            "compatible": has_adapters,
            "existing_count": len(existing_adapters),
            "notes": (
                f"{len(existing_adapters)} existing adapter(s) match your stack"
                if has_adapters
                else "No pre-built adapters for this stack yet"
            ),
        })

        # Calculate overall score
        compat_scores = [c["compatible"] for c in checks]
        score = sum(compat_scores) / len(compat_scores) if compat_scores else 0.0
        overall_compatible = score >= 0.5

        # Recommendations
        recommendations = []
        if not lang_compatible and language:
            recommendations.append(
                f"Consider building a {language} adapter for {profile.name}."
            )
        if not protocol_compatible:
            recommendations.append(
                f"A {system_protocol} client library may be needed for "
                f"{framework or language}."
            )
        if not auth_compatible:
            recommendations.append(
                f"Custom auth handler needed for '{system_auth}' with "
                f"{framework or language}."
            )
        if not has_adapters:
            recommendations.append(
                f"No pre-built adapters exist. ANASTASiA can generate one "
                f"during integration."
            )
        if overall_compatible and not recommendations:
            recommendations.append(
                f"Full compatibility detected. Integration should be straightforward."
            )

        return {
            "compatible": overall_compatible,
            "score": round(score, 2),
            "system_found": True,
            "system_name": profile.name,
            "system_readiness": profile.readiness,
            "checks": checks,
            "recommendations": recommendations,
        }

    # ------------------------------------------------------------------
    # Suggestions
    # ------------------------------------------------------------------

    def suggest_systems(
        self,
        tech_stack: TechStack,
    ) -> List[Dict[str, Any]]:
        """
        Suggest systems that work well with a detected tech stack.

        Runs compatibility checks against all cataloged systems and
        returns those with a compatibility score above 0.25, sorted
        by score descending.

        Args:
            tech_stack: Detected TechStack of the customer's platform.

        Returns:
            List of suggestion dicts with system info, compatibility
            score, and integration recommendations.
        """
        all_profiles = self._profile_store.list_all()
        suggestions = []

        for profile in all_profiles:
            compat = self.get_compatibility(profile.name, tech_stack)

            if compat.get("score", 0) < 0.25:
                continue

            badge = self.get_readiness_badge(profile)
            suggestions.append({
                "id": profile.id,
                "name": profile.name,
                "vendor": profile.vendor,
                "vertical": profile.vertical,
                "readiness": profile.readiness,
                "badge": badge,
                "compatibility_score": compat["score"],
                "compatible": compat["compatible"],
                "recommendations": compat.get("recommendations", []),
                "endpoints_count": len(profile.endpoints),
                "has_booking_flow": profile.booking_flow is not None,
            })

        # Sort by compatibility score descending, then readiness
        suggestions.sort(
            key=lambda s: (
                s["compatibility_score"],
                -_READINESS_CONFIG.get(
                    s["readiness"], {"sort_order": 99}
                )["sort_order"],
            ),
            reverse=True,
        )

        logger.info(
            "Suggested %d systems for stack: %s/%s",
            len(suggestions),
            tech_stack.language,
            tech_stack.framework,
        )
        return suggestions

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def export_catalog(self) -> Dict[str, Any]:
        """
        Export the full catalog for admin dashboard or backup.

        Returns a complete snapshot of all system profiles with badges,
        statistics, and metadata.

        Returns:
            Dict with ``systems`` (list of full profile dicts with badges),
            ``stats`` (aggregate statistics), and ``exported_at`` timestamp.
        """
        all_profiles = self._profile_store.list_all()
        systems = []
        readiness_counts: Dict[str, int] = {}
        vertical_counts: Dict[str, int] = {}
        total_endpoints = 0
        total_quirks = 0
        total_adapters = 0

        for profile in all_profiles:
            badge = self.get_readiness_badge(profile)
            profile_dict = profile.to_dict()
            profile_dict["badge"] = badge
            systems.append(profile_dict)

            # Aggregate stats
            readiness = profile.readiness or "discovered"
            readiness_counts[readiness] = readiness_counts.get(readiness, 0) + 1

            vertical = profile.vertical or "unknown"
            vertical_counts[vertical] = vertical_counts.get(vertical, 0) + 1

            total_endpoints += len(profile.endpoints)
            total_quirks += len(profile.quirks)
            total_adapters += len(profile.adapters)

        import time as _time

        return {
            "systems": systems,
            "stats": {
                "total_systems": len(all_profiles),
                "total_endpoints": total_endpoints,
                "total_quirks": total_quirks,
                "total_adapters": total_adapters,
                "by_readiness": readiness_counts,
                "by_vertical": vertical_counts,
                "avg_confidence": (
                    sum(p.confidence for p in all_profiles) / len(all_profiles)
                    if all_profiles else 0.0
                ),
            },
            "exported_at": _time.time(),
        }
