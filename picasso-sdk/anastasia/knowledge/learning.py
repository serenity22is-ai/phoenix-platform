"""
LearningPipeline — Pattern extraction from customer installations.

Analyzes codebases, HTTP traffic, and error logs to automatically build
SystemProfile objects. This is how ANASTASiA learns new systems: each
customer installation contributes functional knowledge that is retained
permanently (system patterns, NOT proprietary business logic).

Pipeline stages:
  1. extract_from_codebase()  -> TechStack (language, framework, payments)
  2. extract_api_patterns()   -> endpoint list from HTTP logs
  3. extract_booking_flow()   -> BookingFlow from ordered API calls
  4. discover_quirks()        -> SystemQuirk list from error patterns
  5. build_system_profile()   -> orchestrate all stages into a SystemProfile

MYSTES KYRIOS LLC — Confidential.
"""

import json
import logging
import re
import time
import uuid
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from ..core.types import (
    BookingFlow,
    SystemProfile,
    SystemQuirk,
    TechStack,
    VerticalType,
)
from ..core.events import Event, EventBus, EventType

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Detection rules
# ---------------------------------------------------------------------------

# Manifest file -> (language, package_manager)
_MANIFEST_MAP: Dict[str, Tuple[str, str]] = {
    "package.json": ("javascript", "npm"),
    "package-lock.json": ("javascript", "npm"),
    "yarn.lock": ("javascript", "yarn"),
    "pnpm-lock.yaml": ("javascript", "pnpm"),
    "requirements.txt": ("python", "pip"),
    "Pipfile": ("python", "pipenv"),
    "Pipfile.lock": ("python", "pipenv"),
    "pyproject.toml": ("python", "pip"),
    "setup.py": ("python", "pip"),
    "composer.json": ("php", "composer"),
    "composer.lock": ("php", "composer"),
    "pom.xml": ("java", "maven"),
    "build.gradle": ("java", "gradle"),
    "build.gradle.kts": ("kotlin", "gradle"),
    "Gemfile": ("ruby", "bundler"),
    "Gemfile.lock": ("ruby", "bundler"),
    "go.mod": ("go", "go-modules"),
    "go.sum": ("go", "go-modules"),
    "Cargo.toml": ("rust", "cargo"),
    "Cargo.lock": ("rust", "cargo"),
    "mix.exs": ("elixir", "hex"),
    "pubspec.yaml": ("dart", "pub"),
}

# Framework detection: pattern -> framework name
_FRAMEWORK_PATTERNS: Dict[str, str] = {
    # Python
    r"from\s+flask\b": "flask",
    r"import\s+flask\b": "flask",
    r"from\s+django\b": "django",
    r"import\s+django\b": "django",
    r"from\s+fastapi\b": "fastapi",
    r"import\s+fastapi\b": "fastapi",
    r"from\s+starlette\b": "starlette",
    r"from\s+tornado\b": "tornado",
    r"from\s+sanic\b": "sanic",
    # JavaScript / TypeScript
    r"""require\s*\(\s*['"]express['"]\s*\)""": "express",
    r"""from\s+['"]express['"]""": "express",
    r"""require\s*\(\s*['"]next['"]\s*\)""": "nextjs",
    r"""from\s+['"]next""": "nextjs",
    r"""require\s*\(\s*['"]nuxt['"]\s*\)""": "nuxt",
    r"""from\s+['"]@nestjs""": "nestjs",
    r"""require\s*\(\s*['"]koa['"]\s*\)""": "koa",
    r"""from\s+['"]hono['"]""": "hono",
    # PHP
    r"use\s+Illuminate\\": "laravel",
    r"use\s+Symfony\\": "symfony",
    # Java / Kotlin
    r"import\s+org\.springframework\b": "spring",
    r"import\s+io\.micronaut\b": "micronaut",
    r"import\s+io\.quarkus\b": "quarkus",
    # Ruby
    r"""require\s+['"]rails['"]""": "rails",
    r"class\s+\w+\s*<\s*(?:ApplicationController|ActionController)": "rails",
    r"""require\s+['"]sinatra['"]""": "sinatra",
    # Go
    r'"github\.com/gin-gonic/gin"': "gin",
    r'"github\.com/gofiber/fiber"': "fiber",
    r'"github\.com/labstack/echo"': "echo",
    # Rust
    r"use\s+actix_web\b": "actix",
    r"use\s+axum\b": "axum",
    r"use\s+rocket\b": "rocket",
}

# Payment SDK detection: pattern -> processor name
_PAYMENT_PATTERNS: Dict[str, str] = {
    r"""['"]stripe['"]""": "stripe",
    r"import\s+stripe\b": "stripe",
    r"from\s+stripe\b": "stripe",
    r"Stripe\s*\(": "stripe",
    r"""['"]@adyen/""": "adyen",
    r"adyen\.checkout": "adyen",
    r"""['"]square['"]""": "square",
    r"squareup\.com": "square",
    r"""['"]@paypal/""": "paypal",
    r"paypal\.com": "paypal",
    r"""['"]braintree['"]""": "braintree",
    r"braintree\.com": "braintree",
}

# UI framework detection
_UI_FRAMEWORK_PATTERNS: Dict[str, str] = {
    r"""from\s+['"]react['"]""": "react",
    r"""require\s*\(\s*['"]react['"]\s*\)""": "react",
    r"""from\s+['"]vue['"]""": "vue",
    r"""from\s+['"]@angular/""": "angular",
    r"""from\s+['"]svelte['"]""": "svelte",
    r"""from\s+['"]solid-js['"]""": "solid",
    r"""from\s+['"]preact['"]""": "preact",
    r"\$\s*\(": "jquery",
    r"""require\s*\(\s*['"]jquery['"]\s*\)""": "jquery",
}

# CSS framework detection
_CSS_FRAMEWORK_PATTERNS: Dict[str, str] = {
    r"@tailwind\b": "tailwind",
    r"""['"]tailwindcss['"]""": "tailwind",
    r"""['"]bootstrap['"]""": "bootstrap",
    r"class\s*=\s*['\"].*\bcol-(?:xs|sm|md|lg)-": "bootstrap",
    r"""['"]@mui/""": "material-ui",
    r"""['"]@chakra-ui/""": "chakra-ui",
    r"""['"]antd['"]""": "ant-design",
}

# Database detection
_DATABASE_PATTERNS: Dict[str, str] = {
    r"psycopg2": "postgresql",
    r"asyncpg": "postgresql",
    r"pg-promise": "postgresql",
    r"""['"]pg['"]""": "postgresql",
    r"mysql2?\b": "mysql",
    r"pymysql": "mysql",
    r"mongodb": "mongodb",
    r"mongoose": "mongodb",
    r"pymongo": "mongodb",
    r"sqlite3?\b": "sqlite",
    r"redis\b": "redis",
}

# CI/CD detection by filename
_CICD_FILES: Dict[str, str] = {
    ".github/workflows": "github-actions",
    ".gitlab-ci.yml": "gitlab-ci",
    "Jenkinsfile": "jenkins",
    ".circleci": "circleci",
    "bitbucket-pipelines.yml": "bitbucket-pipelines",
    ".travis.yml": "travis-ci",
    "azure-pipelines.yml": "azure-devops",
}

# Containerization detection by filename
_CONTAINER_FILES = {"Dockerfile", "docker-compose.yml", "docker-compose.yaml"}

# Hosting detection
_HOSTING_PATTERNS: Dict[str, str] = {
    r"render\.com": "render",
    r"vercel\.com": "vercel",
    r"netlify\.com": "netlify",
    r"heroku\.com": "heroku",
    r"aws\.amazon\.com": "aws",
    r"cloud\.google\.com": "gcp",
    r"azure\.microsoft\.com": "azure",
    r"fly\.io": "fly",
    r"railway\.app": "railway",
}

# ---------------------------------------------------------------------------
# Booking-related keywords for flow inference
# ---------------------------------------------------------------------------

_BOOKING_STEP_KEYWORDS: Dict[str, List[str]] = {
    "search": ["search", "avail", "query", "find", "lookup", "browse"],
    "select": ["select", "detail", "offer", "price", "fare", "rate", "quote"],
    "add_to_cart": ["cart", "basket", "add", "reserve"],
    "passenger_info": ["passenger", "traveler", "guest", "pax", "contact"],
    "payment": ["pay", "charge", "checkout", "invoice", "billing", "purchase"],
    "confirm": ["confirm", "book", "create", "finalize", "complete", "commit"],
    "ticket": ["ticket", "voucher", "document", "eticket", "itinerary", "pnr"],
}


class LearningPipeline:
    """
    Extracts system knowledge from customer installations.

    Analyzes codebases, HTTP traffic logs, and error logs to automatically
    detect tech stacks, API patterns, booking flows, and system quirks.
    The extracted knowledge is assembled into a SystemProfile that becomes
    part of ANASTASiA's permanent knowledge base.

    Args:
        event_bus: EventBus instance for publishing learning events.
    """

    def __init__(self, event_bus: EventBus):
        self._event_bus = event_bus

    # ------------------------------------------------------------------
    # Stage 1: Tech stack detection
    # ------------------------------------------------------------------

    def extract_from_codebase(
        self,
        file_contents: Dict[str, str],
    ) -> TechStack:
        """
        Analyze a set of files to detect the technology stack.

        Examines filenames (manifests, config files) and file contents
        (import statements, SDK usage) to identify:
        - Programming language and package manager
        - Web framework (Flask, Django, Express, Laravel, Spring, etc.)
        - Payment processors (Stripe, Adyen, Square, PayPal, etc.)
        - UI framework (React, Vue, Angular, etc.)
        - CSS framework (Tailwind, Bootstrap, MUI, etc.)
        - Database (PostgreSQL, MySQL, MongoDB, etc.)
        - CI/CD (GitHub Actions, GitLab CI, Jenkins, etc.)
        - Containerization (Docker)
        - Hosting provider (Render, Vercel, AWS, etc.)

        Args:
            file_contents: Dictionary mapping relative file paths to their
                           text content. Paths should use forward slashes.

        Returns:
            A TechStack dataclass with detected technologies and a
            confidence score (0.0-1.0).
        """
        stack = TechStack()
        signals: Dict[str, int] = Counter()
        detected_files: Dict[str, str] = {}

        # --- Pass 1: Filename-based detection ---
        for filepath in file_contents:
            basename = filepath.rsplit("/", 1)[-1] if "/" in filepath else filepath

            # Manifest files -> language + package manager
            if basename in _MANIFEST_MAP:
                lang, pm = _MANIFEST_MAP[basename]
                signals[f"lang:{lang}"] += 2  # Strong signal
                stack.package_manager = pm
                detected_files[filepath] = f"{lang} manifest ({pm})"

            # CI/CD
            for cicd_path, cicd_name in _CICD_FILES.items():
                if cicd_path in filepath:
                    stack.ci_cd = cicd_name
                    detected_files[filepath] = f"CI/CD config ({cicd_name})"
                    break

            # Container files
            if basename in _CONTAINER_FILES:
                stack.containerized = True
                detected_files[filepath] = "Container config"

        # --- Pass 2: Content-based detection ---
        all_content = "\n".join(file_contents.values())

        # Framework detection
        framework_hits: Counter = Counter()
        for pattern, framework in _FRAMEWORK_PATTERNS.items():
            matches = re.findall(pattern, all_content)
            if matches:
                framework_hits[framework] += len(matches)

        if framework_hits:
            best_framework = framework_hits.most_common(1)[0][0]
            stack.framework = best_framework

        # Payment processor detection
        payment_hits: Counter = Counter()
        for pattern, processor in _PAYMENT_PATTERNS.items():
            matches = re.findall(pattern, all_content)
            if matches:
                payment_hits[processor] += len(matches)

        # UI framework detection
        ui_hits: Counter = Counter()
        for pattern, ui_fw in _UI_FRAMEWORK_PATTERNS.items():
            matches = re.findall(pattern, all_content)
            if matches:
                ui_hits[ui_fw] += len(matches)

        if ui_hits:
            stack.ui_framework = ui_hits.most_common(1)[0][0]

        # CSS framework detection
        css_hits: Counter = Counter()
        for pattern, css_fw in _CSS_FRAMEWORK_PATTERNS.items():
            matches = re.findall(pattern, all_content)
            if matches:
                css_hits[css_fw] += len(matches)

        if css_hits:
            stack.css_framework = css_hits.most_common(1)[0][0]

        # Database detection
        db_hits: Counter = Counter()
        for pattern, db in _DATABASE_PATTERNS.items():
            matches = re.findall(pattern, all_content)
            if matches:
                db_hits[db] += len(matches)

        if db_hits:
            stack.database = db_hits.most_common(1)[0][0]

        # Cache detection (subset of database patterns)
        if "redis" in db_hits:
            stack.cache = "redis"

        # Hosting detection
        for pattern, host in _HOSTING_PATTERNS.items():
            if re.search(pattern, all_content):
                stack.hosting = host
                break

        # --- Resolve language ---
        # Language may have been set by manifests; also infer from framework
        framework_languages: Dict[str, str] = {
            "flask": "python", "django": "python", "fastapi": "python",
            "starlette": "python", "tornado": "python", "sanic": "python",
            "express": "javascript", "nextjs": "javascript", "nuxt": "javascript",
            "nestjs": "typescript", "koa": "javascript", "hono": "javascript",
            "laravel": "php", "symfony": "php",
            "spring": "java", "micronaut": "java", "quarkus": "java",
            "rails": "ruby", "sinatra": "ruby",
            "gin": "go", "fiber": "go", "echo": "go",
            "actix": "rust", "axum": "rust", "rocket": "rust",
        }
        if not stack.language and stack.framework:
            stack.language = framework_languages.get(stack.framework, "")
        elif not stack.language and signals:
            lang_signals = {
                k.split(":")[1]: v for k, v in signals.items()
                if k.startswith("lang:")
            }
            if lang_signals:
                stack.language = max(lang_signals, key=lang_signals.get)

        stack.detected_files = detected_files

        # --- Confidence ---
        evidence_count = sum([
            bool(stack.language),
            bool(stack.framework),
            bool(stack.database),
            bool(stack.ui_framework),
            bool(stack.package_manager),
            bool(stack.ci_cd),
            stack.containerized,
            bool(stack.hosting),
        ])
        # Scale: 1 signal = 0.2, 4+ = 0.8, 6+ = 0.95
        stack.confidence = min(0.95, 0.15 + evidence_count * 0.12)

        logger.info(
            "Tech stack detected: lang=%s, framework=%s, db=%s (confidence=%.2f)",
            stack.language, stack.framework, stack.database, stack.confidence,
        )
        return stack

    # ------------------------------------------------------------------
    # Stage 2: API pattern extraction
    # ------------------------------------------------------------------

    def extract_api_patterns(
        self,
        http_logs: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Identify API endpoints from HTTP traffic logs.

        Groups HTTP requests by (method, path_template) and extracts:
        - Endpoint path (with path parameters generalized, e.g. ``/api/users/{id}``)
        - HTTP method
        - Request/response content types
        - Average response time
        - Success rate
        - Sample request/response bodies (if provided in the logs)

        Args:
            http_logs: List of HTTP log entries. Each entry should contain
                       at minimum ``method``, ``url`` or ``path``, and
                       ``status_code``. Optional fields: ``request_body``,
                       ``response_body``, ``duration_ms``, ``content_type``,
                       ``timestamp``.

        Returns:
            List of endpoint pattern dicts, sorted by call frequency.
        """
        if not http_logs:
            return []

        # Group by (method, generalized_path)
        endpoint_groups: Dict[Tuple[str, str], List[Dict]] = defaultdict(list)

        for log_entry in http_logs:
            method = log_entry.get("method", "GET").upper()
            raw_path = log_entry.get("path") or log_entry.get("url", "")

            # Extract path from full URL if needed
            if raw_path.startswith("http"):
                parsed = urlparse(raw_path)
                raw_path = parsed.path

            # Generalize path parameters (UUIDs, numeric IDs)
            generalized = self._generalize_path(raw_path)
            endpoint_groups[(method, generalized)].append(log_entry)

        # Build endpoint patterns
        patterns = []
        for (method, path), entries in endpoint_groups.items():
            status_codes = [e.get("status_code", 0) for e in entries]
            durations = [
                e.get("duration_ms", 0) for e in entries
                if e.get("duration_ms")
            ]
            success_count = sum(1 for s in status_codes if 200 <= s < 400)
            content_types = set(
                e.get("content_type", "") for e in entries
                if e.get("content_type")
            )

            pattern: Dict[str, Any] = {
                "path": path,
                "method": method,
                "call_count": len(entries),
                "success_rate": (
                    success_count / len(entries) if entries else 0.0
                ),
                "avg_duration_ms": (
                    sum(durations) / len(durations) if durations else None
                ),
                "content_types": sorted(content_types) if content_types else [],
                "status_codes": sorted(set(status_codes)),
                "purpose": self._infer_purpose(method, path),
            }

            # Include sample request/response bodies (first success)
            for entry in entries:
                sc = entry.get("status_code", 0)
                if 200 <= sc < 400:
                    if entry.get("request_body"):
                        pattern["sample_request"] = self._truncate_sample(
                            entry["request_body"]
                        )
                    if entry.get("response_body"):
                        pattern["sample_response"] = self._truncate_sample(
                            entry["response_body"]
                        )
                    break

            patterns.append(pattern)

        # Sort by frequency (most called first)
        patterns.sort(key=lambda p: p["call_count"], reverse=True)

        logger.info(
            "Extracted %d API patterns from %d HTTP log entries",
            len(patterns), len(http_logs),
        )
        return patterns

    # ------------------------------------------------------------------
    # Stage 3: Booking flow inference
    # ------------------------------------------------------------------

    def extract_booking_flow(
        self,
        api_patterns: List[Dict[str, Any]],
    ) -> BookingFlow:
        """
        Infer a booking flow from a set of API endpoint patterns.

        Uses keyword matching against endpoint paths to identify
        booking-related steps (search, select, cart, payment, confirm)
        and orders them into a coherent flow.

        Args:
            api_patterns: Output from ``extract_api_patterns()``.

        Returns:
            A BookingFlow with ordered steps. If no booking-related
            endpoints are detected, returns an empty BookingFlow.
        """
        if not api_patterns:
            return BookingFlow()

        # Score each API pattern against booking step keywords
        step_candidates: Dict[str, List[Dict]] = defaultdict(list)

        for pattern in api_patterns:
            path_lower = pattern.get("path", "").lower()
            purpose_lower = pattern.get("purpose", "").lower()
            combined = f"{path_lower} {purpose_lower}"

            for step_name, keywords in _BOOKING_STEP_KEYWORDS.items():
                score = sum(1 for kw in keywords if kw in combined)
                if score > 0:
                    step_candidates[step_name].append({
                        "pattern": pattern,
                        "score": score,
                    })

        if not step_candidates:
            logger.info("No booking-related endpoints detected")
            return BookingFlow()

        # Pick the best candidate for each step
        step_order = [
            "search", "select", "add_to_cart", "passenger_info",
            "payment", "confirm", "ticket",
        ]
        steps = []
        order_num = 0

        for step_name in step_order:
            candidates = step_candidates.get(step_name, [])
            if not candidates:
                continue
            # Pick highest-scored candidate
            candidates.sort(key=lambda c: c["score"], reverse=True)
            best = candidates[0]["pattern"]
            order_num += 1
            steps.append({
                "order": order_num,
                "name": step_name,
                "endpoint": best.get("path", ""),
                "method": best.get("method", ""),
                "required_fields": [],
                "notes": best.get("purpose", ""),
            })

        requires_auth = any(
            p.get("status_codes") and 401 in p["status_codes"]
            for p in api_patterns
        )

        flow = BookingFlow(
            steps=steps,
            total_steps=len(steps),
            estimated_time_seconds=len(steps) * 2.0,
            requires_auth=requires_auth,
            supports_guest=not requires_auth,
        )

        logger.info("Inferred booking flow with %d steps", len(steps))
        return flow

    # ------------------------------------------------------------------
    # Stage 4: Quirk discovery
    # ------------------------------------------------------------------

    def discover_quirks(
        self,
        error_logs: List[Dict[str, Any]],
    ) -> List[SystemQuirk]:
        """
        Identify system quirks from error log patterns.

        Analyzes error frequency, categories, and messages to surface
        undocumented behaviors and gotchas. Groups similar errors and
        assigns severity based on frequency and HTTP status codes.

        Args:
            error_logs: List of error log entries. Each should contain
                        at minimum ``message`` or ``error``. Optional:
                        ``status_code``, ``endpoint``, ``timestamp``,
                        ``category``.

        Returns:
            List of SystemQuirk objects, sorted by severity
            (critical first).
        """
        if not error_logs:
            return []

        # Group errors by normalized message pattern
        error_groups: Dict[str, List[Dict]] = defaultdict(list)

        for entry in error_logs:
            message = entry.get("message") or entry.get("error", "")
            if not message:
                continue
            # Normalize: strip UUIDs, numbers, timestamps for grouping
            normalized = self._normalize_error(str(message))
            error_groups[normalized].append(entry)

        quirks = []
        for normalized_msg, entries in error_groups.items():
            if len(entries) < 2:
                # Single occurrence is noise, not a pattern
                continue

            # Determine category from error content
            category = self._categorize_error(normalized_msg, entries)

            # Determine severity from status codes and frequency
            status_codes = [e.get("status_code", 0) for e in entries]
            severity = self._assess_severity(status_codes, len(entries))

            # Get a representative raw message
            raw_message = entries[0].get("message") or entries[0].get("error", "")
            affected_endpoints = sorted(set(
                e.get("endpoint", "") for e in entries if e.get("endpoint")
            ))

            description = (
                f"Recurring error ({len(entries)}x): {raw_message}"
            )
            if affected_endpoints:
                description += (
                    f" — affects endpoint(s): {', '.join(affected_endpoints)}"
                )

            quirk = SystemQuirk(
                description=description,
                category=category,
                severity=severity,
                workaround="",
                discovered_by="learning_pipeline",
            )
            quirks.append(quirk)

        # Sort by severity: critical > warning > info
        severity_order = {"critical": 0, "warning": 1, "info": 2}
        quirks.sort(key=lambda q: severity_order.get(q.severity, 3))

        logger.info("Discovered %d quirks from %d error logs", len(quirks), len(error_logs))
        return quirks

    # ------------------------------------------------------------------
    # Stage 5: Orchestrator
    # ------------------------------------------------------------------

    def build_system_profile(
        self,
        name: str,
        raw_data: Dict[str, Any],
    ) -> SystemProfile:
        """
        Orchestrate all extraction stages into a complete SystemProfile.

        Accepts raw data from a customer installation and runs it through
        the full learning pipeline. Publishes ``SYSTEM_LEARNED`` when
        the profile is successfully built.

        Args:
            name: Human-readable name for the system (e.g. "Sabre", "Hotelbeds").
            raw_data: Dictionary that may contain:
                - ``file_contents``: Dict[str, str] — files for tech stack analysis
                - ``http_logs``: List[dict] — HTTP traffic logs
                - ``error_logs``: List[dict] — Error logs
                - ``vendor``: str — vendor/company name
                - ``vertical``: str — VerticalType value
                - ``base_url``: str — API base URL
                - ``auth_method``: str — AuthMethod value
                - ``tags``: List[str] — descriptive tags
                - ``agency_id``: str — the agency contributing this data

        Returns:
            A fully assembled SystemProfile.
        """
        logger.info("Building system profile for '%s'", name)

        # Tech stack extraction
        tech_stack = TechStack()
        file_contents = raw_data.get("file_contents", {})
        if file_contents:
            tech_stack = self.extract_from_codebase(file_contents)

        # API pattern extraction
        http_logs = raw_data.get("http_logs", [])
        api_patterns = self.extract_api_patterns(http_logs)

        # Booking flow inference
        booking_flow = self.extract_booking_flow(api_patterns)

        # Quirk discovery
        error_logs = raw_data.get("error_logs", [])
        quirks = self.discover_quirks(error_logs)

        # Build endpoint list from API patterns
        endpoints = [
            {
                "path": p.get("path", ""),
                "method": p.get("method", ""),
                "purpose": p.get("purpose", ""),
                "notes": (
                    f"Called {p.get('call_count', 0)}x, "
                    f"success rate {p.get('success_rate', 0):.0%}"
                ),
            }
            for p in api_patterns
        ]

        # Determine readiness level
        evidence_count = sum([
            bool(endpoints),
            bool(booking_flow.steps),
            bool(quirks),
            bool(tech_stack.language),
        ])
        readiness_levels = ["discovered", "probed", "documented", "tested", "production"]
        readiness = readiness_levels[min(evidence_count, len(readiness_levels) - 1)]

        # Confidence based on data quality
        confidence = min(0.95, 0.1 + evidence_count * 0.15 + min(
            len(api_patterns) * 0.02, 0.3
        ))

        # Resolve vertical
        vertical = raw_data.get("vertical", VerticalType.FLIGHTS.value)

        # Assemble tags
        tags = list(raw_data.get("tags", []))
        if tech_stack.language and tech_stack.language not in tags:
            tags.append(tech_stack.language)
        if tech_stack.framework and tech_stack.framework not in tags:
            tags.append(tech_stack.framework)
        if vertical and vertical not in tags:
            tags.append(vertical)

        # Build the profile
        agency_id = raw_data.get("agency_id", "")
        profile = SystemProfile(
            id=str(uuid.uuid4()),
            name=name,
            vendor=raw_data.get("vendor", ""),
            vertical=vertical,
            protocol="rest",
            base_url=raw_data.get("base_url", ""),
            auth_method=raw_data.get("auth_method", "api_key"),
            booking_flow=booking_flow if booking_flow.steps else None,
            endpoints=endpoints,
            data_schemas={
                "tech_stack": tech_stack.to_dict(),
            },
            quirks=quirks,
            adapters=[],
            readiness=readiness,
            confidence=confidence,
            installations=1,
            learned_from=[agency_id] if agency_id else [],
            tags=tags,
        )

        # Publish SYSTEM_LEARNED event
        self._event_bus.publish(Event(
            type=EventType.SYSTEM_LEARNED,
            data={
                "profile_id": profile.id,
                "system_name": name,
                "readiness": readiness,
                "confidence": confidence,
                "endpoints_count": len(endpoints),
                "quirks_count": len(quirks),
                "has_booking_flow": bool(booking_flow.steps),
            },
            source="knowledge.learning",
            agency_id=agency_id or None,
        ))

        logger.info(
            "Built profile for '%s': readiness=%s, confidence=%.2f, "
            "%d endpoints, %d quirks",
            name, readiness, confidence, len(endpoints), len(quirks),
        )
        return profile

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _generalize_path(path: str) -> str:
        """
        Replace path parameters with placeholders.

        Transforms ``/api/users/550e8400-e29b-41d4-a716/orders/42``
        into ``/api/users/{id}/orders/{id}``.
        """
        parts = path.strip("/").split("/")
        generalized = []
        for part in parts:
            # UUID pattern
            if re.match(
                r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}(-[0-9a-f]{12})?$",
                part, re.IGNORECASE,
            ):
                generalized.append("{id}")
            # Pure numeric
            elif re.match(r"^\d+$", part):
                generalized.append("{id}")
            # Hex hash (8+ chars)
            elif re.match(r"^[0-9a-f]{8,}$", part, re.IGNORECASE) and len(part) >= 8:
                generalized.append("{id}")
            else:
                generalized.append(part)
        return "/" + "/".join(generalized) if generalized else "/"

    @staticmethod
    def _infer_purpose(method: str, path: str) -> str:
        """Infer a human-readable purpose from HTTP method + path."""
        path_lower = path.lower()
        last_segment = path.rstrip("/").rsplit("/", 1)[-1].replace("{id}", "").strip("/")

        # Common REST patterns
        if method == "GET" and "{id}" in path:
            return f"Get {last_segment or 'resource'} by ID"
        elif method == "GET":
            return f"List/query {last_segment or 'resources'}"
        elif method == "POST" and "search" in path_lower:
            return f"Search {last_segment or 'resources'}"
        elif method == "POST" and "login" in path_lower:
            return "Authentication/login"
        elif method == "POST":
            return f"Create {last_segment or 'resource'}"
        elif method == "PUT" or method == "PATCH":
            return f"Update {last_segment or 'resource'}"
        elif method == "DELETE":
            return f"Delete {last_segment or 'resource'}"
        return f"{method} {last_segment or path}"

    @staticmethod
    def _truncate_sample(body: Any, max_length: int = 500) -> Any:
        """Truncate a sample body to avoid storing huge payloads."""
        if isinstance(body, str):
            return body[:max_length] + ("..." if len(body) > max_length else "")
        if isinstance(body, dict):
            serialized = json.dumps(body, default=str)
            if len(serialized) > max_length:
                return json.loads(serialized[:max_length - 4] + "...}")
            return body
        return body

    @staticmethod
    def _normalize_error(message: str) -> str:
        """
        Normalize an error message for grouping similar errors.

        Strips UUIDs, numeric IDs, timestamps, and IP addresses.
        """
        # Remove UUIDs
        normalized = re.sub(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
            "{UUID}", message, flags=re.IGNORECASE,
        )
        # Remove standalone numbers (IDs, ports, etc.)
        normalized = re.sub(r"\b\d{2,}\b", "{NUM}", normalized)
        # Remove IP addresses
        normalized = re.sub(r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}", "{IP}", normalized)
        # Remove timestamps (ISO format)
        normalized = re.sub(
            r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}", "{TIMESTAMP}", normalized,
        )
        # Collapse whitespace
        normalized = re.sub(r"\s+", " ", normalized).strip()
        return normalized

    @staticmethod
    def _categorize_error(
        normalized_msg: str,
        entries: List[Dict],
    ) -> str:
        """Categorize an error group based on message content and status codes."""
        msg_lower = normalized_msg.lower()
        status_codes = set(e.get("status_code", 0) for e in entries)

        if 401 in status_codes or 403 in status_codes:
            return "auth"
        if "timeout" in msg_lower or "timed out" in msg_lower or 408 in status_codes:
            return "timeout"
        if "connection" in msg_lower or "connect" in msg_lower:
            return "connection"
        if "encoding" in msg_lower or "decode" in msg_lower or "charset" in msg_lower:
            return "encoding"
        if "pagination" in msg_lower or "offset" in msg_lower or "cursor" in msg_lower:
            return "pagination"
        if 429 in status_codes or "rate" in msg_lower:
            return "rate_limit"
        if 400 in status_codes or "validation" in msg_lower or "invalid" in msg_lower:
            return "validation"
        if any(s >= 500 for s in status_codes):
            return "server_error"
        return "unknown"

    @staticmethod
    def _assess_severity(
        status_codes: List[int],
        frequency: int,
    ) -> str:
        """Determine quirk severity from HTTP status codes and error frequency."""
        has_5xx = any(s >= 500 for s in status_codes if s > 0)
        has_auth = any(s in (401, 403) for s in status_codes)

        # Critical: server errors or auth failures that happen frequently
        if (has_5xx or has_auth) and frequency >= 5:
            return "critical"
        # Warning: moderate frequency or client errors
        if frequency >= 3 or has_5xx or has_auth:
            return "warning"
        return "info"
