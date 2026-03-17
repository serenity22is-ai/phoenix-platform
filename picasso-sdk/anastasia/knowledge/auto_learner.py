"""
AutoLearner — Autonomous API reverse-engineering engine.

When ANASTASiA's daemon encounters an unknown API in a customer's codebase,
the AutoLearner orchestrates the full learning cycle:

    1. ENCOUNTER  — Identify unknown external APIs from a codebase scan
    2. PROBE      — Generate safe read-only probes for discovered APIs
    3. ANALYZE    — Use Claude Opus 4.6 to reason about probe results
    4. PROFILE    — Convert Claude's analysis into a structured SystemProfile
    5. RETAIN     — Store permanently in ProfileStore (merged if existing)

Redbox/Cockpit was patient zero — reverse-engineered by hand. Every future
API gets learned automatically through this pipeline.

The ``ai_analyze`` callable is the key abstraction: it accepts a structured
prompt (str) and returns Claude's response (str). This decouples the
learning engine from any specific LLM transport (Anthropic SDK, API proxy,
local model, etc.). In production, this is Claude Opus 4.6.

Usage::

    from anastasia.knowledge.auto_learner import AutoLearner

    learner = AutoLearner(
        event_bus=bus,
        profile_store=store,
        ai_analyze=lambda prompt: anthropic_client.messages.create(
            model="claude-opus-4-6",
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        ).content[0].text,
    )

    # Full pipeline from daemon scan
    results = learner.learn(codebase_scan)

MYSTES KYRIOS LLC — Confidential.
"""

import json
import logging
import re
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Set
from urllib.parse import urlparse

from ..core.events import Event, EventBus, EventType
from ..core.types import (
    AuthMethod,
    SystemProfile,
    SystemQuirk,
    TechStack,
    VerticalType,
)
from .profiles import ProfileStore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Patterns for detecting external API calls in source code
# ---------------------------------------------------------------------------

# HTTP client libraries — presence means the code makes outbound HTTP calls
_HTTP_CLIENT_PATTERNS: Dict[str, str] = {
    # Python
    r"requests\.(?:get|post|put|delete|patch|head|options)\s*\(": "python-requests",
    r"httpx\.(?:get|post|put|delete|patch|head|options|AsyncClient|Client)\s*\(": "python-httpx",
    r"aiohttp\.ClientSession": "python-aiohttp",
    r"urllib\.request\.urlopen": "python-urllib",
    r"http\.client\.HTTPSConnection": "python-http",
    # JavaScript/TypeScript
    r"fetch\s*\(": "js-fetch",
    r"axios\.(?:get|post|put|delete|patch|head|options|create)\s*\(": "js-axios",
    r"got\s*\(": "js-got",
    r"superagent\.(?:get|post|put|delete|patch)": "js-superagent",
    r"node-fetch": "js-node-fetch",
    # Ruby
    r"Net::HTTP": "ruby-net-http",
    r"Faraday\.(?:get|post|put|delete|patch)": "ruby-faraday",
    r"HTTParty\.(?:get|post|put|delete|patch)": "ruby-httparty",
    # Go
    r"http\.(?:Get|Post|NewRequest)": "go-net-http",
    # Java
    r"HttpClient\.new": "java-httpclient",
    r"OkHttpClient": "java-okhttp",
    r"RestTemplate": "java-spring-rest",
    r"WebClient\.create": "java-spring-webclient",
    # PHP
    r"Guzzle": "php-guzzle",
    r"curl_init": "php-curl",
    # Rust
    r"reqwest::Client": "rust-reqwest",
    # .NET
    r"HttpClient\s*\(": "dotnet-httpclient",
}

# URL patterns in source code — captures base URLs of external APIs
_URL_EXTRACTION_PATTERN = re.compile(
    r"""(?:['"])(https?://[a-zA-Z0-9\-_.]+\.[a-zA-Z]{2,}(?:/[a-zA-Z0-9\-_./]*)?)(?:['"])""",
)

# URLs to skip (own infrastructure, CDNs, generic services)
_SKIP_DOMAINS: Set[str] = {
    "localhost", "127.0.0.1", "0.0.0.0",
    "fonts.googleapis.com", "fonts.gstatic.com",
    "cdn.jsdelivr.net", "unpkg.com", "cdnjs.cloudflare.com",
    "www.google.com", "www.googleapis.com",
    "github.com", "raw.githubusercontent.com",
    "registry.npmjs.org", "pypi.org",
    "sentry.io", "bugsnag.com",
    "newrelic.com", "datadoghq.com",
    "gravatar.com", "ui-avatars.com",
}

# Known API SDKs — import patterns that indicate a specific API is used
_SDK_PATTERNS: Dict[str, Dict[str, str]] = {
    # pattern → {name, vendor, vertical, base_url, auth_method}
    r"import\s+stripe\b|from\s+stripe\b|['\"]\s*stripe\s*['\"]": {
        "name": "Stripe", "vendor": "Stripe Inc",
        "vertical": "payments", "base_url": "https://api.stripe.com",
        "auth_method": "api_key",
    },
    r"['\"]\s*@adyen/|adyen\.checkout|adyen\.com/v\d+": {
        "name": "Adyen", "vendor": "Adyen NV",
        "vertical": "payments", "base_url": "https://checkout-test.adyen.com",
        "auth_method": "api_key",
    },
    r"amadeus|amadeusitgroup": {
        "name": "Amadeus", "vendor": "Amadeus IT Group",
        "vertical": "flights", "base_url": "https://api.amadeus.com",
        "auth_method": "oauth2",
    },
    r"sabre\.com|sabresonicweb": {
        "name": "Sabre", "vendor": "Sabre Corporation",
        "vertical": "flights", "base_url": "https://api.sabre.com",
        "auth_method": "oauth2",
    },
    r"travelport|galileo|worldspan": {
        "name": "Travelport", "vendor": "Travelport",
        "vertical": "flights", "base_url": "https://api.travelport.com",
        "auth_method": "basic",
    },
    r"hotelbeds|apitude\.com": {
        "name": "Hotelbeds", "vendor": "Hotelbeds Group",
        "vertical": "hotels", "base_url": "https://api.test.hotelbeds.com",
        "auth_method": "api_key",
    },
    r"booking\.com/api|bookingcom": {
        "name": "Booking.com", "vendor": "Booking Holdings",
        "vertical": "hotels", "base_url": "https://distribution-xml.booking.com",
        "auth_method": "basic",
    },
    r"expedia\.com/api|eps-rapid": {
        "name": "Expedia EPS", "vendor": "Expedia Group",
        "vertical": "hotels", "base_url": "https://test.ean.com",
        "auth_method": "api_key",
    },
    r"liteapi|lite-api": {
        "name": "liteAPI", "vendor": "liteAPI",
        "vertical": "hotels", "base_url": "https://api.liteapi.travel",
        "auth_method": "api_key",
    },
    r"mystifly|mystiflyapi": {
        "name": "Mystifly", "vendor": "Mystifly",
        "vertical": "flights", "base_url": "https://api.mystifly.com",
        "auth_method": "oauth2",
    },
    r"kiwi\.com|tequila": {
        "name": "Kiwi Tequila", "vendor": "Kiwi.com",
        "vertical": "flights", "base_url": "https://tequila-api.kiwi.com",
        "auth_method": "api_key",
    },
    r"duffel\.com|duffel": {
        "name": "Duffel", "vendor": "Duffel",
        "vertical": "flights", "base_url": "https://api.duffel.com",
        "auth_method": "api_key",
    },
    r"flightconex|aerticket|aerpackit|redbox": {
        "name": "Redbox", "vendor": "AERTiCKET",
        "vertical": "flights", "base_url": "https://aerpackit.flightconex.de/redbox",
        "auth_method": "session_cookie",
    },
    r"twilio|sendgrid": {
        "name": "Twilio/SendGrid", "vendor": "Twilio Inc",
        "vertical": "communications", "base_url": "https://api.twilio.com",
        "auth_method": "basic",
    },
}

# Standard probe endpoints — safe, read-only endpoints to try
_PROBE_ENDPOINTS: List[Dict[str, str]] = [
    {"path": "/", "purpose": "Root / landing page"},
    {"path": "/health", "purpose": "Health check endpoint"},
    {"path": "/api", "purpose": "API root / version info"},
    {"path": "/api/v1", "purpose": "API v1 root"},
    {"path": "/api/v2", "purpose": "API v2 root"},
    {"path": "/openapi.json", "purpose": "OpenAPI/Swagger spec (JSON)"},
    {"path": "/swagger.json", "purpose": "Swagger spec (JSON)"},
    {"path": "/docs", "purpose": "API documentation"},
    {"path": "/swagger-ui.html", "purpose": "Swagger UI"},
    {"path": "/.well-known/openapi.yaml", "purpose": "Well-known OpenAPI"},
    {"path": "/status", "purpose": "Service status"},
    {"path": "/version", "purpose": "Version info"},
    {"path": "/ping", "purpose": "Ping/alive check"},
    {"path": "/info", "purpose": "Service info"},
]

# Auth pattern probes — test what auth the API expects
_AUTH_PROBES: List[Dict[str, Any]] = [
    {
        "method": "api_key_header",
        "headers": {"X-API-Key": "test_probe_key"},
        "description": "API key in X-API-Key header",
    },
    {
        "method": "bearer_token",
        "headers": {"Authorization": "Bearer test_probe_token"},
        "description": "Bearer token in Authorization header",
    },
    {
        "method": "basic_auth",
        "headers": {"Authorization": "Basic dGVzdDp0ZXN0"},
        "description": "HTTP Basic auth",
    },
    {
        "method": "api_key_query",
        "params": {"api_key": "test_probe_key"},
        "description": "API key in query parameter",
    },
    {
        "method": "session_cookie",
        "headers": {"Cookie": "session=test_probe_session"},
        "description": "Session cookie auth",
    },
]

# Claude analysis prompt template
_ANALYSIS_PROMPT = """You are ANASTASiA's Knowledge Neuron — an autonomous API reverse-engineering engine.

You have been given raw data from probing an unknown API that was discovered in a customer's codebase. Your job is to analyze this data and produce a structured System Profile — the same kind of deep knowledge that was manually built for the Redbox/Cockpit API.

## DISCOVERED API
- **Name**: {api_name}
- **Base URL**: {base_url}
- **Vendor** (if known): {vendor}
- **Vertical** (if known): {vertical}
- **Discovered via**: {discovery_method}

## RAW PROBE DATA
{probe_data}

## SOURCE CODE CONTEXT
{source_context}

## EXISTING KNOWLEDGE
{existing_knowledge}

## YOUR TASK
Analyze ALL available data and produce a structured JSON response with the following fields. Reason carefully about what the API does, how it authenticates, what its endpoints are, and any quirks or gotchas you can identify.

Be thorough but honest — mark confidence levels accurately. If you can't determine something, say so. Never fabricate endpoint details that aren't supported by evidence.

Respond with ONLY valid JSON (no markdown, no explanation outside the JSON):

```json
{{
  "name": "Human-readable API name",
  "vendor": "Company/organization name",
  "vertical": "flights|hotels|payments|communications|custom",
  "protocol": "rest|soap|graphql|grpc|websocket|custom",
  "base_url": "https://api.example.com",
  "auth_method": "api_key|oauth2|session_cookie|jwt|basic|hmac|custom",
  "auth_details": {{
    "type": "description of auth mechanism",
    "token_endpoint": "URL if OAuth2",
    "header_format": "how to send credentials",
    "notes": "any quirks about auth"
  }},
  "endpoints": [
    {{
      "path": "/endpoint/path",
      "method": "GET|POST|PUT|DELETE",
      "purpose": "what this endpoint does",
      "request_schema": {{}},
      "response_schema": {{}},
      "notes": "any observations"
    }}
  ],
  "booking_flow": {{
    "steps": ["step1_name", "step2_name"],
    "description": "how booking works end-to-end",
    "required_fields": ["field1", "field2"]
  }},
  "quirks": [
    {{
      "description": "undocumented behavior or gotcha",
      "category": "auth|timeout|encoding|pagination|rate_limit|validation|server_error",
      "severity": "critical|warning|info",
      "workaround": "how to handle it"
    }}
  ],
  "data_schemas": {{
    "key_entities": ["list of main data objects"],
    "relationships": "how entities relate"
  }},
  "rate_limiting": {{
    "detected": true,
    "limits": "description of rate limits if known"
  }},
  "pagination": {{
    "style": "offset|cursor|page_number|link_header|none",
    "details": "how pagination works"
  }},
  "error_format": {{
    "style": "description of error response format",
    "sample": {{}}
  }},
  "confidence": 0.0,
  "confidence_reasoning": "why you assigned this confidence level",
  "tags": ["relevant", "tags"],
  "recommendations": ["what ANASTASiA should do next to learn more"]
}}
```"""


class APIDiscovery:
    """An unknown API found during codebase scanning."""

    __slots__ = (
        "id", "name", "base_url", "vendor", "vertical",
        "auth_method", "discovery_method", "source_files",
        "source_snippets", "http_client", "sdk_match",
        "discovered_at", "status",
    )

    def __init__(
        self,
        name: str,
        base_url: str,
        *,
        vendor: str = "",
        vertical: str = "",
        auth_method: str = "",
        discovery_method: str = "codebase_scan",
        source_files: Optional[List[str]] = None,
        source_snippets: Optional[List[str]] = None,
        http_client: str = "",
        sdk_match: str = "",
    ):
        self.id = str(uuid.uuid4())
        self.name = name
        self.base_url = base_url
        self.vendor = vendor
        self.vertical = vertical
        self.auth_method = auth_method
        self.discovery_method = discovery_method
        self.source_files = source_files or []
        self.source_snippets = source_snippets or []
        self.http_client = http_client
        self.sdk_match = sdk_match
        self.discovered_at = time.time()
        self.status = "discovered"  # discovered → probed → analyzed → profiled

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "base_url": self.base_url,
            "vendor": self.vendor,
            "vertical": self.vertical,
            "auth_method": self.auth_method,
            "discovery_method": self.discovery_method,
            "source_files": self.source_files,
            "http_client": self.http_client,
            "sdk_match": self.sdk_match,
            "discovered_at": self.discovered_at,
            "status": self.status,
        }


class ProbeResult:
    """Results from probing an API endpoint."""

    __slots__ = (
        "url", "method", "status_code", "headers", "body",
        "duration_ms", "error", "auth_probe", "timestamp",
    )

    def __init__(
        self,
        url: str,
        method: str = "GET",
        *,
        status_code: int = 0,
        headers: Optional[Dict[str, str]] = None,
        body: str = "",
        duration_ms: float = 0.0,
        error: str = "",
        auth_probe: str = "",
    ):
        self.url = url
        self.method = method
        self.status_code = status_code
        self.headers = headers or {}
        self.body = body[:2000]  # Truncate large bodies
        self.duration_ms = duration_ms
        self.error = error
        self.auth_probe = auth_probe
        self.timestamp = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "url": self.url,
            "method": self.method,
            "status_code": self.status_code,
            "headers": dict(self.headers),
            "body_preview": self.body[:500],
            "body_length": len(self.body),
            "duration_ms": self.duration_ms,
            "error": self.error,
            "auth_probe": self.auth_probe,
        }


class AutoLearner:
    """
    Autonomous API reverse-engineering engine powered by Claude Opus 4.6.

    Redbox/Cockpit was reverse-engineered by hand. Every future API gets
    learned automatically through this pipeline. Claude IS the analysis
    engine — it reasons about raw HTTP responses, error messages, auth
    patterns, and source code context to build structured SystemProfiles.

    The pipeline:
        encounter(scan) → probe(discovery) → analyze(probes) → profile → retain

    Or call ``learn(scan)`` to run the full pipeline in one shot.

    Args:
        event_bus: EventBus for publishing learning events.
        profile_store: ProfileStore for checking existing knowledge + storing new.
        ai_analyze: Callable that takes a prompt string and returns Claude's
                    response string. This is how ANASTASiA talks to Claude
                    Opus 4.6. If None, analysis stage returns raw probe data
                    without AI reasoning (useful for testing/offline).
        http_probe: Optional callable for making HTTP requests during probing.
                    Signature: (url, method, headers, timeout) → ProbeResult.
                    If None, probing is simulated from source code analysis only.
    """

    def __init__(
        self,
        event_bus: EventBus,
        profile_store: ProfileStore,
        ai_analyze: Optional[Callable[[str], str]] = None,
        http_probe: Optional[Callable[..., ProbeResult]] = None,
    ):
        self._event_bus = event_bus
        self._profile_store = profile_store
        self._ai_analyze = ai_analyze
        self._http_probe = http_probe
        self._discoveries: Dict[str, APIDiscovery] = {}
        self._probe_results: Dict[str, List[ProbeResult]] = {}

    # ------------------------------------------------------------------
    # Stage 1: ENCOUNTER — Identify unknown APIs in codebase scan
    # ------------------------------------------------------------------

    def encounter(
        self,
        codebase_scan: Dict[str, Any],
    ) -> List[APIDiscovery]:
        """
        Analyze a daemon codebase scan to find unknown external APIs.

        Examines source code for:
        - HTTP client library usage (requests, axios, fetch, etc.)
        - External API URLs (https://api.example.com/...)
        - Known SDK imports (stripe, amadeus, sabre, etc.)

        Filters out APIs that already have profiles in the ProfileStore.

        Args:
            codebase_scan: Output from DaemonExecutor.scan_codebase().
                           Expected keys: ``file_manifest``, ``routes``,
                           ``models``, ``auth_config``, ``codebase_info``,
                           ``tech_stack``, ``file_contents`` (optional).

        Returns:
            List of APIDiscovery objects for unknown APIs.
        """
        discoveries: List[APIDiscovery] = []
        seen_base_urls: Set[str] = set()
        file_contents = codebase_scan.get("file_contents", {})

        if not file_contents:
            logger.info("No file_contents in scan — cannot discover APIs")
            return discoveries

        all_content = "\n".join(file_contents.values())

        # --- Strategy 1: Known SDK pattern matching ---
        for pattern, sdk_info in _SDK_PATTERNS.items():
            if re.search(pattern, all_content, re.IGNORECASE):
                name = sdk_info["name"]
                base_url = sdk_info["base_url"]

                # Check if we already know this system
                existing = self._profile_store.get_by_name(name)
                if existing and existing.confidence >= 0.5:
                    logger.debug(
                        "Skipping '%s' — already profiled (confidence=%.2f)",
                        name, existing.confidence,
                    )
                    continue

                if base_url in seen_base_urls:
                    continue
                seen_base_urls.add(base_url)

                # Find which files contain this SDK
                source_files = [
                    fp for fp, content in file_contents.items()
                    if re.search(pattern, content, re.IGNORECASE)
                ]

                discovery = APIDiscovery(
                    name=name,
                    base_url=base_url,
                    vendor=sdk_info.get("vendor", ""),
                    vertical=sdk_info.get("vertical", ""),
                    auth_method=sdk_info.get("auth_method", ""),
                    discovery_method="sdk_pattern",
                    source_files=source_files[:10],
                    sdk_match=pattern,
                )
                discoveries.append(discovery)
                logger.info(
                    "ENCOUNTER: SDK match '%s' (%s) in %d files",
                    name, base_url, len(source_files),
                )

        # --- Strategy 2: URL extraction from source code ---
        for filepath, content in file_contents.items():
            urls = _URL_EXTRACTION_PATTERN.findall(content)
            for url in urls:
                parsed = urlparse(url)
                domain = parsed.hostname or ""

                # Skip known infrastructure
                if not domain or domain in _SKIP_DOMAINS:
                    continue
                # Skip own API URLs (from the codebase's own routes)
                own_routes = codebase_scan.get("routes", [])
                if any(url.endswith(r.get("path", "")) for r in own_routes):
                    continue

                # Normalize base URL
                base_url = f"{parsed.scheme}://{parsed.netloc}"
                if base_url in seen_base_urls:
                    continue
                seen_base_urls.add(base_url)

                # Check if we already know this API by URL
                existing_profiles = self._profile_store.list_all()
                known = any(
                    base_url in (p.base_url or "")
                    for p in existing_profiles
                    if p.confidence >= 0.5
                )
                if known:
                    continue

                # Extract context around the URL
                snippets = self._extract_context_snippets(content, url)

                # Infer name from domain
                name = self._infer_api_name(domain, parsed.path)

                discovery = APIDiscovery(
                    name=name,
                    base_url=base_url,
                    discovery_method="url_extraction",
                    source_files=[filepath],
                    source_snippets=snippets[:5],
                )
                discoveries.append(discovery)
                logger.info(
                    "ENCOUNTER: URL discovery '%s' (%s) in %s",
                    name, base_url, filepath,
                )

        # --- Strategy 3: HTTP client usage without clear URLs ---
        http_clients_found: Set[str] = set()
        for pattern, client_name in _HTTP_CLIENT_PATTERNS.items():
            if re.search(pattern, all_content):
                http_clients_found.add(client_name)

        # Store for later analysis
        if http_clients_found:
            logger.info(
                "ENCOUNTER: HTTP clients detected: %s",
                ", ".join(sorted(http_clients_found)),
            )

        # Publish SYSTEM_DISCOVERED events
        for discovery in discoveries:
            self._discoveries[discovery.id] = discovery
            self._event_bus.publish(Event(
                type=EventType.SYSTEM_DISCOVERED,
                source="knowledge.auto_learner",
                data=discovery.to_dict(),
            ))

        logger.info(
            "ENCOUNTER complete: %d unknown APIs discovered", len(discoveries),
        )
        return discoveries

    # ------------------------------------------------------------------
    # Stage 2: PROBE — Generate safe probes for discovered APIs
    # ------------------------------------------------------------------

    def probe(
        self,
        discovery: APIDiscovery,
    ) -> List[ProbeResult]:
        """
        Probe a discovered API with safe, read-only requests.

        Generates GET/HEAD/OPTIONS requests to standard endpoints
        (/health, /api, /docs, /openapi.json, etc.) and records every
        response. NEVER sends POST/PUT/DELETE to unknown APIs without
        explicit permission.

        If ``http_probe`` callable was provided at init, makes real HTTP
        calls. Otherwise, generates probe specifications that can be
        executed externally (by the daemon).

        Args:
            discovery: The APIDiscovery to probe.

        Returns:
            List of ProbeResult objects.
        """
        results: List[ProbeResult] = []
        base_url = discovery.base_url.rstrip("/")

        # --- Probe standard endpoints ---
        for probe_spec in _PROBE_ENDPOINTS:
            url = f"{base_url}{probe_spec['path']}"
            if self._http_probe:
                try:
                    result = self._http_probe(
                        url=url, method="GET", headers={}, timeout=10,
                    )
                    results.append(result)
                except Exception as e:
                    results.append(ProbeResult(
                        url=url, error=str(e),
                    ))
            else:
                # No HTTP callable — generate probe spec only
                results.append(ProbeResult(
                    url=url,
                    method="GET",
                    status_code=-1,  # -1 = not yet executed
                    error="probe_pending",
                ))

        # --- Auth detection probes ---
        # Send requests with different auth headers to root endpoint
        # to detect what auth method the API expects
        auth_url = f"{base_url}/api"
        for auth_probe in _AUTH_PROBES:
            if self._http_probe:
                try:
                    result = self._http_probe(
                        url=auth_url,
                        method="GET",
                        headers=auth_probe.get("headers", {}),
                        timeout=10,
                    )
                    result.auth_probe = auth_probe["method"]
                    results.append(result)
                except Exception as e:
                    results.append(ProbeResult(
                        url=auth_url,
                        error=str(e),
                        auth_probe=auth_probe["method"],
                    ))

        discovery.status = "probed"

        # Store results
        self._probe_results[discovery.id] = results

        # Count successful probes
        successes = sum(
            1 for r in results
            if 200 <= r.status_code < 400
        )

        # Publish SYSTEM_PROBED event
        self._event_bus.publish(Event(
            type=EventType.SYSTEM_PROBED,
            source="knowledge.auto_learner",
            data={
                "discovery_id": discovery.id,
                "api_name": discovery.name,
                "base_url": discovery.base_url,
                "total_probes": len(results),
                "successful_probes": successes,
                "probe_endpoints": [r.url for r in results if r.status_code > 0],
            },
        ))

        logger.info(
            "PROBE complete for '%s': %d/%d probes successful",
            discovery.name, successes, len(results),
        )
        return results

    # ------------------------------------------------------------------
    # Stage 3: ANALYZE — Use Claude Opus 4.6 to reason about probe data
    # ------------------------------------------------------------------

    def analyze(
        self,
        discovery: APIDiscovery,
        probe_results: List[ProbeResult],
    ) -> Dict[str, Any]:
        """
        Analyze probe results using Claude Opus 4.6.

        Constructs a detailed prompt with all available data (probe
        responses, source code context, existing knowledge) and asks
        Claude to reason about the API's structure, auth, endpoints,
        quirks, and booking flow.

        If no ``ai_analyze`` callable was provided, returns a structured
        analysis built from probe data alone (rule-based fallback).

        Args:
            discovery: The APIDiscovery being analyzed.
            probe_results: Results from the probe stage.

        Returns:
            Structured analysis dict (parsed from Claude's JSON response).
        """
        # Build probe data summary for the prompt
        probe_summary = self._format_probe_data(probe_results)

        # Build source context from discovery
        source_context = self._format_source_context(discovery)

        # Build existing knowledge context
        existing_knowledge = self._format_existing_knowledge(discovery)

        if self._ai_analyze:
            # --- Claude Opus 4.6 analysis ---
            prompt = _ANALYSIS_PROMPT.format(
                api_name=discovery.name,
                base_url=discovery.base_url,
                vendor=discovery.vendor or "Unknown",
                vertical=discovery.vertical or "Unknown",
                discovery_method=discovery.discovery_method,
                probe_data=probe_summary,
                source_context=source_context,
                existing_knowledge=existing_knowledge,
            )

            try:
                response = self._ai_analyze(prompt)
                analysis = self._parse_ai_response(response)
                discovery.status = "analyzed"
                logger.info(
                    "ANALYZE (Claude): '%s' → confidence=%.2f, %d endpoints, %d quirks",
                    discovery.name,
                    analysis.get("confidence", 0),
                    len(analysis.get("endpoints", [])),
                    len(analysis.get("quirks", [])),
                )
                return analysis
            except Exception as e:
                logger.warning(
                    "Claude analysis failed for '%s': %s — falling back to rule-based",
                    discovery.name, e,
                )
                # Fall through to rule-based analysis

        # --- Rule-based fallback (no AI available) ---
        analysis = self._rule_based_analysis(discovery, probe_results)
        discovery.status = "analyzed"
        logger.info(
            "ANALYZE (rule-based): '%s' → confidence=%.2f",
            discovery.name, analysis.get("confidence", 0),
        )
        return analysis

    # ------------------------------------------------------------------
    # Stage 4: PROFILE — Convert analysis into SystemProfile
    # ------------------------------------------------------------------

    def profile(
        self,
        discovery: APIDiscovery,
        analysis: Dict[str, Any],
    ) -> SystemProfile:
        """
        Convert a Claude analysis into a structured SystemProfile.

        Maps the AI-generated analysis into the SystemProfile dataclass
        format, calculates readiness, and assembles metadata.

        Args:
            discovery: The original APIDiscovery.
            analysis: The analysis dict from ``analyze()``.

        Returns:
            A SystemProfile ready for storage.
        """
        # Build endpoints list
        endpoints = []
        for ep in analysis.get("endpoints", []):
            endpoints.append({
                "path": ep.get("path", ""),
                "method": ep.get("method", "GET"),
                "purpose": ep.get("purpose", ""),
                "notes": ep.get("notes", ""),
            })

        # Build quirks list
        quirks = []
        for q in analysis.get("quirks", []):
            quirks.append(SystemQuirk(
                description=q.get("description", ""),
                category=q.get("category", "unknown"),
                severity=q.get("severity", "info"),
                workaround=q.get("workaround", ""),
                discovered_by="auto_learner",
            ))

        # Build booking flow
        booking_flow = None
        flow_data = analysis.get("booking_flow", {})
        if flow_data and flow_data.get("steps"):
            from ..core.types import BookingFlow
            steps = []
            for i, step_name in enumerate(flow_data["steps"], 1):
                steps.append({
                    "order": i,
                    "name": step_name,
                    "endpoint": "",
                    "method": "",
                    "required_fields": [],
                    "notes": "",
                })
            booking_flow = BookingFlow(
                steps=steps,
                total_steps=len(steps),
                estimated_time_seconds=len(steps) * 2.0,
            )

        # Build data schemas
        data_schemas = {}
        if analysis.get("data_schemas"):
            data_schemas["entities"] = analysis["data_schemas"]
        if analysis.get("auth_details"):
            data_schemas["auth"] = analysis["auth_details"]
        if analysis.get("pagination"):
            data_schemas["pagination"] = analysis["pagination"]
        if analysis.get("error_format"):
            data_schemas["error_format"] = analysis["error_format"]
        if analysis.get("rate_limiting"):
            data_schemas["rate_limiting"] = analysis["rate_limiting"]

        # Determine readiness
        evidence = sum([
            bool(endpoints),
            bool(quirks),
            bool(booking_flow),
            len(endpoints) >= 3,
            analysis.get("confidence", 0) >= 0.5,
        ])
        readiness_map = {0: "discovered", 1: "probed", 2: "documented",
                         3: "documented", 4: "tested", 5: "tested"}
        readiness = readiness_map.get(evidence, "documented")

        # Resolve confidence
        confidence = analysis.get("confidence", 0.15)
        if isinstance(confidence, str):
            try:
                confidence = float(confidence)
            except (ValueError, TypeError):
                confidence = 0.15

        # Assemble tags
        tags = list(analysis.get("tags", []))
        if discovery.vertical and discovery.vertical not in tags:
            tags.append(discovery.vertical)
        if discovery.discovery_method not in tags:
            tags.append(f"auto-learned:{discovery.discovery_method}")

        # Resolve auth method
        auth_method = (
            analysis.get("auth_method")
            or discovery.auth_method
            or "api_key"
        )

        sys_profile = SystemProfile(
            id=str(uuid.uuid4()),
            name=analysis.get("name", discovery.name),
            vendor=analysis.get("vendor", discovery.vendor),
            vertical=analysis.get("vertical", discovery.vertical) or "custom",
            protocol=analysis.get("protocol", "rest"),
            base_url=analysis.get("base_url", discovery.base_url),
            auth_method=auth_method,
            booking_flow=booking_flow,
            endpoints=endpoints,
            data_schemas=data_schemas,
            quirks=quirks,
            adapters=[],
            readiness=readiness,
            confidence=confidence,
            installations=1,
            learned_from=["auto_learner"],
            tags=tags,
        )

        discovery.status = "profiled"
        logger.info(
            "PROFILE: '%s' → readiness=%s, confidence=%.2f, %d endpoints, %d quirks",
            sys_profile.name, readiness, confidence,
            len(endpoints), len(quirks),
        )
        return sys_profile

    # ------------------------------------------------------------------
    # Stage 5: RETAIN — Store permanently in ProfileStore
    # ------------------------------------------------------------------

    def retain(
        self,
        sys_profile: SystemProfile,
        discovery: Optional[APIDiscovery] = None,
    ) -> SystemProfile:
        """
        Store a SystemProfile permanently in the ProfileStore.

        If a profile with the same name already exists, merges the new
        knowledge into it (adds new endpoints, updates confidence,
        increments installations). Knowledge is NEVER deleted — it
        accumulates.

        Args:
            sys_profile: The SystemProfile to store.
            discovery: Optional original discovery for event context.

        Returns:
            The stored (or merged) SystemProfile.
        """
        existing = self._profile_store.get_by_name(sys_profile.name)

        if existing:
            # Merge: add new endpoints, update confidence, append quirks
            merged_endpoints = list(existing.endpoints or [])
            existing_paths = {
                (e.get("path"), e.get("method"))
                for e in merged_endpoints
            }
            for ep in (sys_profile.endpoints or []):
                key = (ep.get("path"), ep.get("method"))
                if key not in existing_paths:
                    merged_endpoints.append(ep)

            merged_quirks = list(existing.quirks or [])
            existing_descs = {q.description for q in merged_quirks}
            for q in (sys_profile.quirks or []):
                if q.description not in existing_descs:
                    merged_quirks.append(q)

            # Update fields
            update_data: Dict[str, Any] = {
                "endpoints": merged_endpoints,
                "quirks": merged_quirks,
                "confidence": max(existing.confidence, sys_profile.confidence),
                "installations": (existing.installations or 0) + 1,
            }

            # Merge data schemas
            merged_schemas = dict(existing.data_schemas or {})
            merged_schemas.update(sys_profile.data_schemas or {})
            update_data["data_schemas"] = merged_schemas

            # Update readiness if improved
            readiness_order = [
                "discovered", "probed", "documented", "tested", "production",
            ]
            if readiness_order.index(sys_profile.readiness) > readiness_order.index(
                existing.readiness or "discovered"
            ):
                update_data["readiness"] = sys_profile.readiness

            # Merge learned_from
            learned = list(existing.learned_from or [])
            for src in (sys_profile.learned_from or []):
                if src not in learned:
                    learned.append(src)
            update_data["learned_from"] = learned

            # Merge tags
            tags = list(existing.tags or [])
            for tag in (sys_profile.tags or []):
                if tag not in tags:
                    tags.append(tag)
            update_data["tags"] = tags

            self._profile_store.update_profile(existing.id, update_data)
            stored = self._profile_store.get_profile(existing.id)
            logger.info(
                "RETAIN: Merged into existing profile '%s' "
                "(now %d endpoints, confidence=%.2f, %d installations)",
                existing.name, len(merged_endpoints),
                update_data["confidence"],
                update_data["installations"],
            )
        else:
            # New profile
            self._profile_store.create_profile(sys_profile)
            stored = sys_profile
            logger.info(
                "RETAIN: Created new profile '%s' "
                "(%d endpoints, confidence=%.2f)",
                sys_profile.name, len(sys_profile.endpoints or []),
                sys_profile.confidence,
            )

        # Publish SYSTEM_LEARNED event
        self._event_bus.publish(Event(
            type=EventType.SYSTEM_LEARNED,
            source="knowledge.auto_learner",
            data={
                "profile_id": stored.id if stored else sys_profile.id,
                "system_name": sys_profile.name,
                "readiness": stored.readiness if stored else sys_profile.readiness,
                "confidence": stored.confidence if stored else sys_profile.confidence,
                "endpoints_count": len(stored.endpoints if stored else sys_profile.endpoints or []),
                "merged": existing is not None,
                "discovery_id": discovery.id if discovery else None,
            },
        ))

        return stored or sys_profile

    # ------------------------------------------------------------------
    # Full pipeline: LEARN
    # ------------------------------------------------------------------

    def learn(
        self,
        codebase_scan: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Run the full auto-learning pipeline on a codebase scan.

        encounter → probe → analyze → profile → retain

        This is the primary entry point. Give it a daemon scan result
        and it will autonomously discover, probe, analyze (via Claude
        Opus 4.6), and permanently learn every unknown API it finds.

        Args:
            codebase_scan: Output from DaemonExecutor.scan_codebase().

        Returns:
            Summary dict with discoveries, profiles created, profiles
            merged, and any errors encountered.
        """
        summary: Dict[str, Any] = {
            "discoveries": [],
            "profiles_created": [],
            "profiles_merged": [],
            "errors": [],
            "skipped": [],
        }

        # Stage 1: Encounter
        discoveries = self.encounter(codebase_scan)
        summary["discoveries"] = [d.to_dict() for d in discoveries]

        if not discoveries:
            logger.info("LEARN: No unknown APIs found — nothing to learn")
            return summary

        # Stages 2-5: For each discovery
        for discovery in discoveries:
            try:
                # Stage 2: Probe
                probe_results = self.probe(discovery)

                # Stage 3: Analyze (Claude Opus 4.6 or rule-based fallback)
                analysis = self.analyze(discovery, probe_results)

                # Stage 4: Profile
                sys_profile = self.profile(discovery, analysis)

                # Stage 5: Retain
                existing = self._profile_store.get_by_name(discovery.name)
                stored = self.retain(sys_profile, discovery)

                if existing:
                    summary["profiles_merged"].append({
                        "name": discovery.name,
                        "profile_id": stored.id if stored else sys_profile.id,
                        "confidence": stored.confidence if stored else sys_profile.confidence,
                    })
                else:
                    summary["profiles_created"].append({
                        "name": discovery.name,
                        "profile_id": stored.id if stored else sys_profile.id,
                        "confidence": stored.confidence if stored else sys_profile.confidence,
                    })

            except Exception as e:
                logger.error(
                    "LEARN: Failed for '%s': %s", discovery.name, e,
                    exc_info=True,
                )
                summary["errors"].append({
                    "api_name": discovery.name,
                    "error": str(e),
                })

        total = len(summary["profiles_created"]) + len(summary["profiles_merged"])
        logger.info(
            "LEARN complete: %d discoveries → %d new profiles, %d merged, %d errors",
            len(discoveries), len(summary["profiles_created"]),
            len(summary["profiles_merged"]), len(summary["errors"]),
        )
        return summary

    # ------------------------------------------------------------------
    # Public accessors
    # ------------------------------------------------------------------

    @property
    def discoveries(self) -> Dict[str, APIDiscovery]:
        """All discoveries from this session."""
        return dict(self._discoveries)

    @property
    def pending_discoveries(self) -> List[APIDiscovery]:
        """Discoveries that haven't been fully processed yet."""
        return [
            d for d in self._discoveries.values()
            if d.status != "profiled"
        ]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_context_snippets(
        content: str, url: str, context_lines: int = 3,
    ) -> List[str]:
        """Extract source code lines around a URL mention."""
        snippets = []
        lines = content.split("\n")
        for i, line in enumerate(lines):
            if url in line:
                start = max(0, i - context_lines)
                end = min(len(lines), i + context_lines + 1)
                snippet = "\n".join(lines[start:end])
                snippets.append(snippet)
        return snippets

    @staticmethod
    def _infer_api_name(domain: str, path: str) -> str:
        """Infer a human-readable API name from its domain."""
        # Remove common prefixes/suffixes
        name = domain
        for prefix in ("api.", "www.", "test.", "sandbox.", "staging."):
            if name.startswith(prefix):
                name = name[len(prefix):]
        for suffix in (".com", ".io", ".org", ".net", ".co", ".dev", ".app"):
            if name.endswith(suffix):
                name = name[: -len(suffix)]

        # Capitalize nicely
        parts = name.replace("-", " ").replace("_", " ").split(".")
        name = " ".join(p.capitalize() for p in parts)

        return name or domain

    def _format_probe_data(self, results: List[ProbeResult]) -> str:
        """Format probe results for the Claude analysis prompt."""
        if not results:
            return "No probe data available."

        lines = []
        for r in results:
            if r.status_code <= 0 and not r.error:
                continue
            line = f"  {r.method} {r.url} → "
            if r.status_code > 0:
                line += f"HTTP {r.status_code}"
                if r.duration_ms:
                    line += f" ({r.duration_ms:.0f}ms)"
                if r.headers:
                    ct = r.headers.get("content-type", "")
                    if ct:
                        line += f" [{ct}]"
                if r.body:
                    line += f"\n    Body: {r.body[:300]}"
            elif r.error:
                line += f"ERROR: {r.error}"
            if r.auth_probe:
                line += f"\n    Auth probe: {r.auth_probe}"
            lines.append(line)

        return "\n".join(lines) if lines else "No successful probes."

    def _format_source_context(self, discovery: APIDiscovery) -> str:
        """Format source code context for the Claude analysis prompt."""
        parts = []
        if discovery.source_files:
            parts.append(
                f"Found in files: {', '.join(discovery.source_files[:5])}"
            )
        if discovery.http_client:
            parts.append(f"HTTP client: {discovery.http_client}")
        if discovery.sdk_match:
            parts.append(f"SDK pattern matched: {discovery.sdk_match}")
        if discovery.source_snippets:
            parts.append("Source code context:")
            for i, snippet in enumerate(discovery.source_snippets[:3], 1):
                parts.append(f"  Snippet {i}:\n    {snippet}")
        return "\n".join(parts) if parts else "No source code context available."

    def _format_existing_knowledge(self, discovery: APIDiscovery) -> str:
        """Format existing profile knowledge for the Claude prompt."""
        existing = self._profile_store.get_by_name(discovery.name)
        if not existing:
            return "No existing knowledge about this API."

        parts = [
            f"Existing profile: {existing.name} (confidence={existing.confidence:.2f})",
            f"  Vendor: {existing.vendor}",
            f"  Readiness: {existing.readiness}",
            f"  Known endpoints: {len(existing.endpoints or [])}",
            f"  Known quirks: {len(existing.quirks or [])}",
            f"  Auth method: {existing.auth_method}",
        ]
        return "\n".join(parts)

    def _parse_ai_response(self, response: str) -> Dict[str, Any]:
        """Parse Claude's JSON response, handling markdown code blocks."""
        text = response.strip()

        # Strip markdown code block if present
        if text.startswith("```"):
            # Remove opening ```json or ```
            first_newline = text.index("\n")
            text = text[first_newline + 1:]
            # Remove closing ```
            if text.endswith("```"):
                text = text[:-3].strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Try to find JSON object in the response
            match = re.search(r"\{[\s\S]*\}", text)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    pass

            logger.warning("Could not parse Claude response as JSON")
            return {
                "name": "Unknown",
                "confidence": 0.1,
                "raw_response": response[:1000],
                "parse_error": True,
            }

    def _rule_based_analysis(
        self,
        discovery: APIDiscovery,
        probe_results: List[ProbeResult],
    ) -> Dict[str, Any]:
        """
        Fallback analysis when Claude is unavailable.

        Uses probe results to build a basic profile from HTTP responses,
        status codes, headers, and content types.
        """
        endpoints = []
        auth_method = discovery.auth_method or "unknown"
        quirks = []

        # Analyze successful probes
        for r in probe_results:
            if r.status_code <= 0:
                continue

            if 200 <= r.status_code < 400:
                parsed = urlparse(r.url)
                endpoints.append({
                    "path": parsed.path,
                    "method": r.method,
                    "purpose": f"Responds with HTTP {r.status_code}",
                    "notes": f"Content-Type: {r.headers.get('content-type', 'unknown')}",
                })

            # Auth detection from 401/403 responses
            if r.status_code in (401, 403) and r.auth_probe:
                if r.auth_probe and r.status_code == 401:
                    pass  # Expected — auth probe with invalid creds
                elif r.status_code == 403:
                    quirks.append({
                        "description": f"403 Forbidden on {r.auth_probe} auth probe",
                        "category": "auth",
                        "severity": "info",
                        "workaround": f"Auth method '{r.auth_probe}' may not be supported",
                    })

            # Rate limit detection
            if r.status_code == 429:
                quirks.append({
                    "description": "Rate limiting detected",
                    "category": "rate_limit",
                    "severity": "warning",
                    "workaround": "Implement request throttling",
                })

        # Detect OpenAPI/Swagger availability
        for r in probe_results:
            if r.status_code == 200 and any(
                k in r.url for k in ("openapi", "swagger")
            ):
                quirks.append({
                    "description": "OpenAPI/Swagger spec available — can auto-discover all endpoints",
                    "category": "auth",
                    "severity": "info",
                    "workaround": "Fetch and parse the spec for complete endpoint mapping",
                })

        confidence = min(0.5, 0.05 + len(endpoints) * 0.05)

        return {
            "name": discovery.name,
            "vendor": discovery.vendor,
            "vertical": discovery.vertical or "custom",
            "protocol": "rest",
            "base_url": discovery.base_url,
            "auth_method": auth_method,
            "endpoints": endpoints,
            "quirks": quirks,
            "confidence": confidence,
            "confidence_reasoning": (
                f"Rule-based analysis only. {len(endpoints)} endpoints "
                f"responded. Claude analysis would improve confidence."
            ),
            "tags": [discovery.discovery_method],
            "recommendations": [
                "Run Claude Opus 4.6 analysis for deeper understanding",
                "Probe additional endpoints based on API documentation",
                "Monitor HTTP traffic during customer usage for pattern extraction",
            ],
        }


__all__ = ["AutoLearner", "APIDiscovery", "ProbeResult"]
