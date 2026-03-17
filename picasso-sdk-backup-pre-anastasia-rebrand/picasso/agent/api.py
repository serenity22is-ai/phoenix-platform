"""
Hosted API — Complete OTA platform API.

Three endpoint groups:
1. AI Chat       — Conversational booking agent (Tier 2+)
2. Search        — Structured form-based search with agency pricing (Tier 2+)
3. Admin         — OTA owner configures pricing, display, branding (Tier 2+)
4. Booking       — Direct booking endpoints (Tier 2+)

Each agency authenticates with an API key (Bearer token).
Agency config controls pricing, display, and feature access.

MYSTES KYRIOS LLC — Confidential.
"""

import hashlib
import json
import logging
import os
import time
import uuid
from functools import wraps
from typing import Optional

from flask import Flask, jsonify, request

from ..auth import TokenManager
from ..client import RedboxClient
from .analytics import AnalyticsEngine, ErrorTracker
from .billing import BillingManager, UsageTracker, PLANS
from .config import AgencyConfig, ConfigStore
from .consumer_ui import CONSUMER_UI_HTML
from .dashboard import ADMIN_DASHBOARD_HTML
from .assist import AssistAgent
from .daemon import AutoHealDaemon
from .onboarding import OnboardingManager, SIGNUP_FORM_HTML
from .orchestrator import BookingAgent
from .pricing import PricingModel, apply_pricing_to_results
from .security import AdminAuth, AuditLog, ActionType, generate_admin_token, hash_token

logger = logging.getLogger(__name__)


def create_app(config: Optional[dict] = None) -> Flask:
    """
    Create the hosted OTA platform API.

    Config keys:
        ANTHROPIC_API_KEY: str — Required. Anthropic API key.
        AGENT_MODEL: str — Claude model ID (default: claude-haiku-4-5-20251001)
        MASTER_KEY: str — Master admin key for registering new agencies
        CONFIG_DIR: str — Directory for agency config files (default: .agency_configs)
        API_KEYS: dict — Map of API key hash -> agency config (inline alternative to files)
        MAX_SESSIONS_PER_KEY: int — Max concurrent chat sessions per API key (default: 50)
        SESSION_TTL_SECONDS: int — Chat session expiry (default: 3600)

    Returns:
        Configured Flask app
    """
    app = Flask(__name__)

    # --- Core config ---
    app_config = config or {}
    anthropic_key = app_config.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
    if not anthropic_key:
        raise ValueError("ANTHROPIC_API_KEY is required (config or env var)")

    agent_model = app_config.get("AGENT_MODEL", "claude-haiku-4-5-20251001")
    max_sessions = app_config.get("MAX_SESSIONS_PER_KEY", 50)
    session_ttl = app_config.get("SESSION_TTL_SECONDS", 3600)
    master_key = app_config.get("MASTER_KEY") or os.environ.get("ANASTASIA_MASTER_KEY", "") or os.environ.get("MYSTES_MASTER_KEY", "")

    # --- Config store (persistent agency configs) ---
    config_dir = app_config.get("CONFIG_DIR", ".agency_configs")
    config_store = ConfigStore(config_dir)

    # --- Billing, Usage, Analytics ---
    data_dir = os.path.join(config_dir, ".data")
    usage_tracker = UsageTracker(os.path.join(data_dir, "usage"))
    error_tracker = ErrorTracker(os.path.join(data_dir, "errors"))
    stripe_key = app_config.get("STRIPE_SECRET_KEY") or os.environ.get("STRIPE_SECRET_KEY", "")
    billing_manager = BillingManager(
        usage_tracker=usage_tracker,
        stripe_api_key=stripe_key,
        data_dir=os.path.join(data_dir, "billing"),
    )
    analytics = AnalyticsEngine(usage_tracker, error_tracker, billing_manager)
    onboarding = OnboardingManager(config_store, billing_manager)
    webhook_secret = app_config.get("STRIPE_WEBHOOK_SECRET") or os.environ.get("STRIPE_WEBHOOK_SECRET", "")

    def _hash_key(api_key: str) -> str:
        return hashlib.sha256(api_key.encode()).hexdigest()

    # --- Legacy inline API_KEYS support (merged with config store) ---
    # Convert raw API keys to hash-keyed dict for lookup
    raw_inline = app_config.get("API_KEYS", {})
    inline_keys = {}
    for raw_key, cfg_data in raw_inline.items():
        inline_keys[_hash_key(raw_key)] = cfg_data

    # --- In-memory caches ---
    sessions: dict = {}       # session_id -> {agent, created_at, api_key_hash, last_used}
    client_cache: dict = {}   # api_key_hash -> RedboxClient
    config_cache: dict = {}   # api_key_hash -> AgencyConfig

    def _cleanup_expired():
        now = time.time()
        expired = [sid for sid, s in sessions.items()
                    if now - s["last_used"] > session_ttl]
        for sid in expired:
            del sessions[sid]

    def _get_agency_config(key_hash: str) -> Optional[AgencyConfig]:
        """Resolve agency config from cache, config store, or inline keys."""
        if key_hash in config_cache:
            return config_cache[key_hash]

        # Try config store (file-based)
        cfg = config_store.get(key_hash)
        if cfg:
            config_cache[key_hash] = cfg
            return cfg

        # Try inline keys (legacy/testing)
        if key_hash in inline_keys:
            cfg = AgencyConfig.from_dict(inline_keys[key_hash])
            config_cache[key_hash] = cfg
            return cfg

        return None

    def require_api_key(f):
        """Validate API key and attach agency config to request."""
        @wraps(f)
        def decorated(*args, **kwargs):
            auth = request.headers.get("Authorization", "")
            if not auth.startswith("Bearer "):
                return jsonify({"error": "Missing Authorization header. Use: Bearer <api_key>"}), 401

            api_key = auth[7:]
            key_hash = _hash_key(api_key)
            agency_cfg = _get_agency_config(key_hash)

            if not agency_cfg:
                return jsonify({"error": "Invalid API key"}), 403

            if not agency_cfg.active:
                return jsonify({"error": "Agency account is suspended"}), 403

            request.api_key_hash = key_hash
            request.agency_config = agency_cfg
            return f(*args, **kwargs)
        return decorated

    def require_master_key(f):
        """Validate master admin key."""
        @wraps(f)
        def decorated(*args, **kwargs):
            auth = request.headers.get("Authorization", "")
            if not auth.startswith("Bearer "):
                return jsonify({"error": "Missing Authorization header"}), 401
            if auth[7:] != master_key or not master_key:
                return jsonify({"error": "Invalid master key"}), 403
            return f(*args, **kwargs)
        return decorated

    def _get_or_create_client(key_hash: str, agency_cfg: AgencyConfig) -> RedboxClient:
        """Get or create a RedboxClient for this agency."""
        if key_hash not in client_cache:
            token_manager = TokenManager(
                username=agency_cfg.cockpit_username,
                password=agency_cfg.cockpit_password,
                totp_secret=agency_cfg.totp_secret,
                manual_token=agency_cfg.session_token,
            )
            client_cache[key_hash] = RedboxClient(
                agency_id=agency_cfg.agency_id,
                branch=agency_cfg.branch,
                token_provider=token_manager.get_token,
            )
        return client_cache[key_hash]

    # ================================================================
    # HEALTH + DASHBOARD
    # ================================================================

    @app.route("/api/v1/health", methods=["GET"])
    def health():
        """Health check — no auth required."""
        return jsonify({
            "status": "healthy",
            "active_sessions": len(sessions),
        })

    @app.route("/admin/dashboard")
    def admin_dashboard():
        """
        Serve the admin dashboard UI.

        Pass API key and base URL as query params:
            /admin/dashboard?key=ana_abc123&base=https://your-server.com
        """
        from flask import Response
        api_key_param = request.args.get("key", "")
        base_url = request.args.get("base", "")
        # Inject config into the HTML
        html = ADMIN_DASHBOARD_HTML.replace(
            "window.ADMIN_API_BASE || ''",
            f"'{base_url}'"
        ).replace(
            "window.ADMIN_API_KEY || ''",
            f"'{api_key_param}'"
        )
        return Response(html, mimetype="text/html")

    @app.route("/app")
    def consumer_app():
        """
        Serve the consumer-facing OTA UI (Tier 3 turnkey).

        This is the complete flight search + booking frontend.
        Pass API key and base URL as query params:
            /app?key=ana_abc123&base=https://your-server.com
        """
        from flask import Response
        api_key_param = request.args.get("key", "")
        base_url = request.args.get("base", "")
        html = CONSUMER_UI_HTML.replace(
            "window.OTA_API_BASE || ''",
            f"'{base_url}'"
        ).replace(
            "window.OTA_API_KEY || ''",
            f"'{api_key_param}'"
        )
        return Response(html, mimetype="text/html")

    @app.route("/api/v1/embed/config", methods=["GET"])
    @require_api_key
    def embed_config():
        """
        Returns the agency's public config for embedding in a frontend.

        The OTA's frontend calls this once on load to get display settings,
        branding, and feature flags — everything needed to render the UI.

        Response:
            {
                "agency_name": "Acme Travel",
                "branding": {...},
                "display": {...},
                "features": {"ai_chat": true, "booking_enabled": true, ...}
            }
        """
        return jsonify(request.agency_config.get_public_view())

    # ================================================================
    # AI CHAT (Tier 2+)
    # ================================================================

    @app.route("/api/v1/chat", methods=["POST"])
    @require_api_key
    def chat():
        """
        Conversational AI booking agent.

        Request:  {"message": "Find flights JFK to London", "session_id": "optional"}
        Response: {"response": "...", "session_id": "...", "usage": {...}}
        """
        agency_cfg = request.agency_config
        if not agency_cfg.features.get("ai_chat", True):
            return jsonify({"error": "AI chat is not enabled for this agency"}), 403

        data = request.get_json()
        if not data or "message" not in data:
            return jsonify({"error": "Request body must include 'message'"}), 400

        message = data["message"].strip()
        if not message:
            return jsonify({"error": "Message cannot be empty"}), 400

        session_id = data.get("session_id")
        key_hash = request.api_key_hash

        _cleanup_expired()

        if session_id and session_id in sessions:
            session = sessions[session_id]
            if session["api_key_hash"] != key_hash:
                return jsonify({"error": "Session belongs to a different API key"}), 403
            agent = session["agent"]
            session["last_used"] = time.time()
        else:
            active = sum(1 for s in sessions.values() if s["api_key_hash"] == key_hash)
            if active >= max_sessions:
                return jsonify({"error": f"Session limit reached ({max_sessions})"}), 429

            client = _get_or_create_client(key_hash, agency_cfg)
            agent = BookingAgent(
                client=client,
                anthropic_api_key=anthropic_key,
                model=agent_model,
                agency_name=agency_cfg.agency_name,
            )
            session_id = str(uuid.uuid4())
            sessions[session_id] = {
                "agent": agent,
                "created_at": time.time(),
                "last_used": time.time(),
                "api_key_hash": key_hash,
            }

        try:
            response_text = agent.chat(message)
        except Exception as e:
            logger.error(f"Agent chat error: {e}")
            return jsonify({"error": "Internal agent error. Please try again."}), 500

        return jsonify({
            "response": response_text,
            "session_id": session_id,
            "usage": agent.get_usage(),
        })

    @app.route("/api/v1/chat/reset", methods=["POST"])
    @require_api_key
    def chat_reset():
        """Reset a chat session."""
        data = request.get_json()
        if not data or "session_id" not in data:
            return jsonify({"error": "Request body must include 'session_id'"}), 400

        session_id = data["session_id"]
        if session_id in sessions:
            if sessions[session_id]["api_key_hash"] != request.api_key_hash:
                return jsonify({"error": "Session belongs to a different API key"}), 403
            sessions[session_id]["agent"].reset()
            sessions[session_id]["last_used"] = time.time()
            return jsonify({"success": True, "session_id": session_id})
        return jsonify({"error": "Session not found"}), 404

    # ================================================================
    # UNIFIED ASSISTANT (admin dashboard chat — booking + integration + config)
    # ================================================================

    # --- Security + Daemon ---
    audit_log = AuditLog(os.path.join(config_dir, ".mystes"))
    admin_auth_hash = app_config.get("ADMIN_AUTH_TOKEN_HASH") or os.environ.get("ADMIN_AUTH_TOKEN_HASH", "")
    admin_auth = AdminAuth(token_hash=admin_auth_hash or None)

    daemon_instance = None
    if app_config.get("ENABLE_DAEMON", True):
        daemon_instance = AutoHealDaemon(
            api_base=app_config.get("API_BASE", ""),
            project_root=config_dir,
            check_interval=app_config.get("DAEMON_INTERVAL", 60),
            audit_log=audit_log,
        )

    assist_sessions = {}  # session_id -> {"agent": AssistAgent, ...}

    @app.route("/api/v1/assist", methods=["POST"])
    @require_api_key
    def assist_chat():
        """
        Unified assistant — handles flights, config, troubleshooting, integration.

        This is the admin dashboard AI. Same session model as /chat but with
        additional capabilities: config management, error diagnosis, code generation.

        Request:  {"message": "Change markup to 15%", "session_id": "optional"}
        Response: {"response": "...", "session_id": "...", "usage": {...}, "config_changed": false}
        """
        agency_cfg = request.agency_config
        data = request.get_json()
        if not data or "message" not in data:
            return jsonify({"error": "Request body must include 'message'"}), 400

        message = data["message"].strip()
        if not message:
            return jsonify({"error": "Message cannot be empty"}), 400

        session_id = data.get("session_id")
        key_hash = request.api_key_hash

        # Find or create assist session
        if session_id and session_id in assist_sessions:
            session = assist_sessions[session_id]
            if session["api_key_hash"] != key_hash:
                return jsonify({"error": "Session belongs to a different API key"}), 403
            agent = session["agent"]
            session["last_used"] = time.time()
        else:
            client = _get_or_create_client(key_hash, agency_cfg)
            session_id = "assist_" + str(uuid.uuid4())
            agent = AssistAgent(
                client=client,
                anthropic_api_key=anthropic_key,
                model=agent_model,
                mode="web",
                agency_name=agency_cfg.agency_name,
                pricing=agency_cfg.pricing,
                agency_config=agency_cfg.to_dict(),
                admin_auth=admin_auth,
                audit_log=audit_log,
                session_id=session_id,
            )
            assist_sessions[session_id] = {
                "agent": agent,
                "created_at": time.time(),
                "last_used": time.time(),
                "api_key_hash": key_hash,
            }

        try:
            response_text = agent.chat(message)
        except Exception as e:
            logger.error(f"Assist agent error: {e}")
            return jsonify({"error": "Assistant error. Please try again."}), 500

        # Check if config was changed and persist
        config_changed = False
        pending = agent.get_pending_config_changes()
        if pending:
            config_changed = True
            # Apply changes to the actual agency config
            for change in pending:
                section = change["section"]
                updates = change["updates"]
                if section == "pricing":
                    for k, v in updates.items():
                        if hasattr(agency_cfg.pricing, k):
                            setattr(agency_cfg.pricing, k, v)
                elif section in ("display", "branding", "features"):
                    getattr(agency_cfg, section, {}).update(updates)
            # Persist to config store
            config_store.save(key_hash, agency_cfg)
            # Clear the change log
            agent.config_changes = []

        return jsonify({
            "response": response_text,
            "session_id": session_id,
            "usage": agent.get_usage(),
            "config_changed": config_changed,
        })

    @app.route("/api/v1/assist/reset", methods=["POST"])
    @require_api_key
    def assist_reset():
        """Reset an assist session."""
        data = request.get_json()
        if not data or "session_id" not in data:
            return jsonify({"error": "Request body must include 'session_id'"}), 400

        session_id = data["session_id"]
        if session_id in assist_sessions:
            if assist_sessions[session_id]["api_key_hash"] != request.api_key_hash:
                return jsonify({"error": "Session belongs to a different API key"}), 403
            assist_sessions[session_id]["agent"].reset()
            assist_sessions[session_id]["last_used"] = time.time()
            return jsonify({"success": True, "session_id": session_id})
        return jsonify({"error": "Session not found"}), 404

    # ================================================================
    # ADMIN AUTH + DAEMON CONTROL
    # ================================================================

    @app.route("/api/v1/assist/authorize", methods=["POST"])
    @require_api_key
    def assist_authorize():
        """
        Authorize a session for code mutation operations.

        Request: {"session_id": "assist_...", "admin_token": "adm_..."}
        """
        data = request.get_json()
        if not data or "session_id" not in data or "admin_token" not in data:
            return jsonify({"error": "session_id and admin_token required"}), 400

        session_id = data["session_id"]
        if session_id not in assist_sessions:
            return jsonify({"error": "Session not found"}), 404
        if assist_sessions[session_id]["api_key_hash"] != request.api_key_hash:
            return jsonify({"error": "Session belongs to a different API key"}), 403

        agent = assist_sessions[session_id]["agent"]
        if agent.authorize_admin(data["admin_token"]):
            return jsonify({"success": True, "message": "Session authorized for code changes (1hr)"})
        return jsonify({"error": "Invalid admin token"}), 401

    @app.route("/api/v1/admin/audit", methods=["GET"])
    @require_api_key
    def get_audit_log():
        """
        Get recent audit log entries.

        Query params: count=20, type=mutations|daemon|all
        """
        count = min(int(request.args.get("count", 20)), 100)
        log_type = request.args.get("type", "all")

        if log_type == "mutations":
            entries = audit_log.get_mutations(count)
        elif log_type == "daemon":
            entries = audit_log.get_daemon_actions(count)
        else:
            entries = audit_log.get_recent(count)

        return jsonify({"entries": entries, "count": len(entries)})

    @app.route("/api/v1/admin/daemon", methods=["GET"])
    @require_api_key
    def daemon_status():
        """Get auto-heal daemon status."""
        if not daemon_instance:
            return jsonify({"enabled": False, "message": "Daemon not configured"})
        return jsonify({"enabled": True, **daemon_instance.get_status()})

    @app.route("/api/v1/admin/daemon/start", methods=["POST"])
    @require_api_key
    def daemon_start():
        """Start the auto-heal daemon."""
        if not daemon_instance:
            return jsonify({"error": "Daemon not configured"}), 400
        daemon_instance.start()
        return jsonify({"success": True, "message": "Daemon started"})

    @app.route("/api/v1/admin/daemon/stop", methods=["POST"])
    @require_api_key
    def daemon_stop():
        """Stop the auto-heal daemon."""
        if not daemon_instance:
            return jsonify({"error": "Daemon not configured"}), 400
        daemon_instance.stop()
        return jsonify({"success": True, "message": "Daemon stopped"})

    @app.route("/api/v1/admin/generate-token", methods=["POST"])
    @require_master_key
    def admin_generate_token():
        """
        Generate a new admin auth token for an agency.

        Returns the token (plaintext) and its hash. The hash should be
        stored in the agency config. The token is given to the admin.
        """
        token = generate_admin_token()
        token_h = hash_token(token)
        return jsonify({
            "admin_token": token,
            "token_hash": token_h,
            "instructions": "Give the token to the agency admin. Store the hash in ADMIN_AUTH_TOKEN_HASH.",
        })

    # ================================================================
    # STRUCTURED SEARCH (Tier 2+) — No AI tokens, direct SDK calls
    # ================================================================

    @app.route("/api/v1/search/airports", methods=["GET"])
    @require_api_key
    def search_airports():
        """
        Search airports. No auth token needed (public endpoint).

        Query params: q=New+York&max=10
        Response: {"airports": [...], "count": 3}
        """
        query = request.args.get("q", "").strip()
        if not query:
            return jsonify({"error": "Query parameter 'q' is required"}), 400

        max_results = min(int(request.args.get("max", 10)), 50)
        client = _get_or_create_client(request.api_key_hash, request.agency_config)

        try:
            airports = client.search_airports(query, max_results=max_results)
        except Exception as e:
            logger.error(f"Airport search error: {e}")
            return jsonify({"error": "Airport search failed"}), 500

        return jsonify({"airports": airports, "count": len(airports)})

    @app.route("/api/v1/search/flights", methods=["POST"])
    @require_api_key
    def search_flights():
        """
        Structured flight search with agency pricing applied.

        Request:
            {
                "origin": "JFK",
                "destination": "LHR",
                "departure_date": "2026-03-15",
                "return_date": null,
                "adults": 1,
                "children": 0,
                "infants": 0,
                "cabin_class": "ECONOMY",
                "nonstop_only": false,
                "max_results": 20,
                "sort": "price"
            }

        Response:
            {
                "flights": [...with agency pricing applied...],
                "fare_search_id": "92",
                "total_results": 400,
                "display": {...agency display settings...}
            }
        """
        agency_cfg = request.agency_config
        if not agency_cfg.features.get("structured_search", True):
            return jsonify({"error": "Structured search not enabled"}), 403

        data = request.get_json()
        if not data:
            return jsonify({"error": "Request body required"}), 400

        # Validate required fields
        for field in ("origin", "destination", "departure_date"):
            if field not in data:
                return jsonify({"error": f"Missing required field: {field}"}), 400

        client = _get_or_create_client(request.api_key_hash, agency_cfg)

        try:
            result = client.search_flights(
                origin=data["origin"],
                destination=data["destination"],
                departure_date=data["departure_date"],
                return_date=data.get("return_date"),
                adults=data.get("adults", 1),
                children=data.get("children", 0),
                infants=data.get("infants", 0),
                cabin_class=data.get("cabin_class", "ECONOMY"),
                max_results=min(data.get("max_results", 20), 50),
                nonstop_only=data.get("nonstop_only", False),
            )
        except Exception as e:
            logger.error(f"Flight search error: {e}")
            return jsonify({"error": "Flight search failed"}), 500

        if not result.get("success"):
            return jsonify({"error": result.get("error", "Search failed")}), 502

        # Apply agency pricing
        flights = result.get("flights", [])
        priced_flights = apply_pricing_to_results(flights, agency_cfg.pricing)

        # Sort results
        sort_by = data.get("sort", "price")
        if sort_by == "price":
            priced_flights.sort(key=lambda f: f.get("consumer_price", 999999))
        elif sort_by == "duration":
            priced_flights.sort(key=lambda f: f.get("duration_minutes", 999999))
        elif sort_by == "departure":
            priced_flights.sort(key=lambda f: f.get("departure_time", ""))
        elif sort_by == "arrival":
            priced_flights.sort(key=lambda f: f.get("arrival_time", ""))

        # Filter result fields based on display settings
        display = agency_cfg.display
        if not display.get("show_gds_source", False):
            for f in priced_flights:
                f.pop("gds", None)

        return jsonify({
            "success": True,
            "flights": priced_flights,
            "fare_search_id": result.get("fare_search_id"),
            "total_results": result.get("total_results", len(priced_flights)),
            "airlines_count": result.get("airlines_count", 0),
            "currency": agency_cfg.pricing.display_currency,
            "display": {k: v for k, v in display.items()
                        if k in ("results_per_page", "show_baggage", "show_fare_family",
                                 "show_fare_rules_link", "show_seatmap_link", "show_savings",
                                 "show_benchmark_price", "currency_symbol", "date_format",
                                 "time_format")},
        })

    @app.route("/api/v1/search/results", methods=["POST"])
    @require_api_key
    def search_results():
        """
        Paginate/filter existing search results with agency pricing.

        Request: {"fare_search_id": "92", "page": 2, "sort": "price"}
        """
        data = request.get_json()
        if not data or "fare_search_id" not in data:
            return jsonify({"error": "fare_search_id is required"}), 400

        agency_cfg = request.agency_config
        client = _get_or_create_client(request.api_key_hash, agency_cfg)

        try:
            result = client.get_search_results(
                fare_search_id=data["fare_search_id"],
                page_number=data.get("page", 1),
                results_per_page=min(data.get("per_page", 20), 50),
                sorting_criteria=data.get("sorting_criteria"),
                filter_criteria=data.get("filters"),
            )
        except Exception as e:
            logger.error(f"Search results error: {e}")
            return jsonify({"error": "Failed to fetch results"}), 500

        if not result.get("success"):
            return jsonify({"error": result.get("error", "Failed")}), 502

        flights = result.get("flights", [])
        priced_flights = apply_pricing_to_results(flights, agency_cfg.pricing)

        return jsonify({
            "success": True,
            "flights": priced_flights,
            "fare_search_id": result.get("fare_search_id"),
            "page": data.get("page", 1),
            "total_results": result.get("total_results", 0),
            "currency": agency_cfg.pricing.display_currency,
        })

    @app.route("/api/v1/search/fare-rules", methods=["POST"])
    @require_api_key
    def fare_rules():
        """
        Get fare rules for a specific flight.

        Request: {"fare_search_id": "92", "fare_id": "abc123"}
        """
        data = request.get_json()
        if not data or "fare_search_id" not in data or "fare_id" not in data:
            return jsonify({"error": "fare_search_id and fare_id are required"}), 400

        client = _get_or_create_client(request.api_key_hash, request.agency_config)

        try:
            result = client.get_fare_rules(
                fare_search_id=data["fare_search_id"],
                fare_id=data["fare_id"],
            )
        except Exception as e:
            logger.error(f"Fare rules error: {e}")
            return jsonify({"error": "Failed to fetch fare rules"}), 500

        return jsonify(result)

    @app.route("/api/v1/search/seatmap", methods=["POST"])
    @require_api_key
    def seatmap():
        """
        Get seatmap for a specific flight segment.

        Request: {"airline_code": "AA", "flight_number": "104", "departure": "JFK",
                  "destination": "LHR", "departure_date": "2026-03-15"}
        """
        agency_cfg = request.agency_config
        if not agency_cfg.features.get("seatmap", True):
            return jsonify({"error": "Seatmap not enabled"}), 403

        data = request.get_json()
        for field in ("airline_code", "flight_number", "departure", "destination", "departure_date"):
            if field not in data:
                return jsonify({"error": f"Missing required field: {field}"}), 400

        client = _get_or_create_client(request.api_key_hash, agency_cfg)

        try:
            result = client.get_seatmap(
                airline_code=data["airline_code"],
                flight_number=data["flight_number"],
                departure=data["departure"],
                destination=data["destination"],
                departure_date=data["departure_date"],
                booking_class=data.get("booking_class", "Y"),
                cabin_class=data.get("cabin_class", "ECONOMY"),
            )
        except Exception as e:
            logger.error(f"Seatmap error: {e}")
            return jsonify({"error": "Failed to fetch seatmap"}), 500

        return jsonify(result)

    # ================================================================
    # BOOKING (Tier 2+)
    # ================================================================

    @app.route("/api/v1/booking/create", methods=["POST"])
    @require_api_key
    def create_booking():
        """
        Book a flight.

        Request:
            {
                "fare_search_id": "92",
                "fare_id": "abc123",
                "passengers": [
                    {
                        "firstName": "John",
                        "lastName": "Smith",
                        "paxType": "ADT",
                        "dateOfBirth": "1990-05-15",
                        "gender": "Male",
                        "email": "john@example.com",
                        "phone": "+12125551234"
                    }
                ],
                "order_tickets": true
            }
        """
        agency_cfg = request.agency_config
        if not agency_cfg.features.get("booking_enabled", True):
            return jsonify({"error": "Booking is not enabled for this agency"}), 403

        data = request.get_json()
        for field in ("fare_search_id", "fare_id", "passengers"):
            if field not in data:
                return jsonify({"error": f"Missing required field: {field}"}), 400

        if not data["passengers"] or not isinstance(data["passengers"], list):
            return jsonify({"error": "passengers must be a non-empty list"}), 400

        # Calculate agency markup from pricing model
        agency_cfg = request.agency_config
        markup = agency_cfg.pricing.markup_flat
        if agency_cfg.pricing.strategy in ("percent_base", "percent_total"):
            # For percentage-based, use the configured flat component
            markup = agency_cfg.pricing.markup_flat

        client = _get_or_create_client(request.api_key_hash, agency_cfg)

        try:
            result = client.book_flight(
                fare_search_id=data["fare_search_id"],
                fare_id=data["fare_id"],
                passengers=data["passengers"],
                order_tickets=data.get("order_tickets", True),
                markup_amount=markup,
            )
        except Exception as e:
            logger.error(f"Booking error: {e}")
            return jsonify({"error": "Booking failed"}), 500

        return jsonify(result)

    @app.route("/api/v1/booking/search", methods=["POST"])
    @require_api_key
    def search_bookings():
        """
        Search existing bookings.

        Request: {"locator": "ABC123"} or {"departure": "JFK", "date_from": "2026-03-01"}
        """
        agency_cfg = request.agency_config
        if not agency_cfg.features.get("booking_management", True):
            return jsonify({"error": "Booking management not enabled"}), 403

        data = request.get_json() or {}
        client = _get_or_create_client(request.api_key_hash, agency_cfg)

        try:
            result = client.search_bookings(
                locator=data.get("locator"),
                departure=data.get("departure"),
                destination=data.get("destination"),
                airline=data.get("airline"),
                date_from=data.get("date_from"),
                date_to=data.get("date_to"),
                travel_date_from=data.get("travel_date_from"),
                travel_date_to=data.get("travel_date_to"),
            )
        except Exception as e:
            logger.error(f"Booking search error: {e}")
            return jsonify({"error": "Booking search failed"}), 500

        return jsonify(result)

    @app.route("/api/v1/booking/document", methods=["POST"])
    @require_api_key
    def generate_document():
        """
        Generate a travel document.

        Request: {"document_type": "CONFIRMATION", "super_pnr_id": "12345"}
        """
        agency_cfg = request.agency_config
        if not agency_cfg.features.get("document_generation", True):
            return jsonify({"error": "Document generation not enabled"}), 403

        data = request.get_json()
        if not data or "document_type" not in data:
            return jsonify({"error": "document_type is required"}), 400

        client = _get_or_create_client(request.api_key_hash, agency_cfg)

        try:
            result = client.generate_document(
                document_type=data["document_type"],
                shopping_cart_id=data.get("shopping_cart_id"),
                super_pnr_id=data.get("super_pnr_id"),
                fare_search_id=data.get("fare_search_id"),
                fare_ids=data.get("fare_ids"),
                display_prices=data.get("display_prices", True),
                language=data.get("language", "en"),
                email_recipients=data.get("email_recipients"),
            )
        except Exception as e:
            logger.error(f"Document generation error: {e}")
            return jsonify({"error": "Document generation failed"}), 500

        return jsonify(result)

    # ================================================================
    # ADMIN — OTA owner configures their instance (Tier 2+)
    # ================================================================

    @app.route("/api/v1/admin/config", methods=["GET"])
    @require_api_key
    def get_config():
        """Get current agency configuration (admin view, no secrets)."""
        return jsonify(request.agency_config.get_admin_view())

    @app.route("/api/v1/admin/config/pricing", methods=["PUT"])
    @require_api_key
    def update_pricing():
        """
        Update agency pricing model.

        Request:
            {
                "strategy": "percent_total",
                "markup_percent": 12.0,
                "markup_flat": 5.0,
                "min_markup": 3.0,
                "max_markup": 100.0,
                "cabin_tiers": {
                    "BUSINESS": {"percent": 6.0},
                    "FIRST": {"percent": 4.0}
                }
            }
        """
        data = request.get_json()
        if not data:
            return jsonify({"error": "Request body required"}), 400

        agency_cfg = request.agency_config

        try:
            new_pricing = PricingModel.from_dict(data)
        except (ValueError, TypeError) as e:
            return jsonify({"error": f"Invalid pricing config: {e}"}), 400

        agency_cfg.pricing = new_pricing

        # Persist
        config_store.save(request.api_key_hash, agency_cfg)
        config_cache[request.api_key_hash] = agency_cfg

        return jsonify({
            "success": True,
            "pricing": new_pricing.to_dict(),
        })

    @app.route("/api/v1/admin/config/display", methods=["PUT"])
    @require_api_key
    def update_display():
        """
        Update display settings.

        Request: {"results_per_page": 25, "show_savings": true, "time_format": "24h"}
        """
        data = request.get_json()
        if not data:
            return jsonify({"error": "Request body required"}), 400

        agency_cfg = request.agency_config

        # Only update recognized keys
        valid_keys = set(agency_cfg.display.keys())
        for key, value in data.items():
            if key in valid_keys:
                agency_cfg.display[key] = value

        config_store.save(request.api_key_hash, agency_cfg)
        config_cache[request.api_key_hash] = agency_cfg

        return jsonify({
            "success": True,
            "display": agency_cfg.display,
        })

    @app.route("/api/v1/admin/config/branding", methods=["PUT"])
    @require_api_key
    def update_branding():
        """
        Update branding settings (Tier 3).

        Request: {"company_name": "Acme Travel", "primary_color": "#FF6600", "logo_url": "..."}
        """
        data = request.get_json()
        if not data:
            return jsonify({"error": "Request body required"}), 400

        agency_cfg = request.agency_config

        valid_keys = set(agency_cfg.branding.keys())
        for key, value in data.items():
            if key in valid_keys:
                agency_cfg.branding[key] = value

        config_store.save(request.api_key_hash, agency_cfg)
        config_cache[request.api_key_hash] = agency_cfg

        return jsonify({
            "success": True,
            "branding": agency_cfg.branding,
        })

    @app.route("/api/v1/admin/config/features", methods=["PUT"])
    @require_api_key
    def update_features():
        """
        Update feature flags.

        Request: {"ai_chat": true, "seatmap": false, "max_daily_searches": 1000}
        """
        data = request.get_json()
        if not data:
            return jsonify({"error": "Request body required"}), 400

        agency_cfg = request.agency_config

        valid_keys = set(agency_cfg.features.keys())
        for key, value in data.items():
            if key in valid_keys:
                agency_cfg.features[key] = value

        config_store.save(request.api_key_hash, agency_cfg)
        config_cache[request.api_key_hash] = agency_cfg

        return jsonify({
            "success": True,
            "features": agency_cfg.features,
        })

    # ================================================================
    # MASTER ADMIN — Register/manage agencies (ANASTASIA internal only)
    # ================================================================

    @app.route("/api/v1/master/agencies", methods=["GET"])
    @require_master_key
    def list_agencies():
        """List all registered agencies."""
        return jsonify({"agencies": config_store.list_all()})

    @app.route("/api/v1/master/agencies", methods=["POST"])
    @require_master_key
    def register_agency():
        """
        Register a new agency and generate their API key.

        Request:
            {
                "agency_id": "629818",
                "branch": "PICL_707",
                "agency_name": "Acme Travel",
                "cockpit_username": "...",
                "cockpit_password": "...",
                "totp_secret": "...",
                "tier": "tier2",
                "pricing": {"strategy": "percent_total", "markup_percent": 10}
            }

        Response:
            {
                "api_key": "ana_abc123...",
                "agency_name": "Acme Travel",
                "config": {...}
            }
        """
        data = request.get_json()
        if not data:
            return jsonify({"error": "Request body required"}), 400

        for field in ("agency_id", "branch", "agency_name"):
            if field not in data:
                return jsonify({"error": f"Missing required field: {field}"}), 400

        # Generate API key
        api_key, key_hash = generate_api_key()

        # Create config
        agency_cfg = AgencyConfig(
            agency_id=data["agency_id"],
            branch=data["branch"],
            agency_name=data["agency_name"],
            agency_slug=data.get("agency_slug", data["agency_name"].lower().replace(" ", "-")),
            cockpit_username=data.get("cockpit_username", ""),
            cockpit_password=data.get("cockpit_password", ""),
            totp_secret=data.get("totp_secret", ""),
            session_token=data.get("session_token", ""),
            pricing=data.get("pricing"),
            display=data.get("display"),
            branding=data.get("branding"),
            features=data.get("features"),
            tier=data.get("tier", "tier2"),
        )

        # Save
        config_store.save(key_hash, agency_cfg)
        config_cache[key_hash] = agency_cfg

        return jsonify({
            "api_key": api_key,
            "key_hash": key_hash,
            "agency_name": agency_cfg.agency_name,
            "config": agency_cfg.get_admin_view(),
        }), 201

    @app.route("/api/v1/master/agencies/<key_hash>", methods=["DELETE"])
    @require_master_key
    def deactivate_agency(key_hash):
        """Deactivate an agency (key stops working)."""
        cfg = config_store.get(key_hash)
        if not cfg:
            return jsonify({"error": "Agency not found"}), 404

        cfg.active = False
        config_store.save(key_hash, cfg)
        config_cache.pop(key_hash, None)
        client_cache.pop(key_hash, None)

        return jsonify({"success": True, "agency_name": cfg.agency_name, "status": "deactivated"})

    # ================================================================
    # ONBOARDING — Self-service signup (no auth required)
    # ================================================================

    @app.route("/signup")
    def signup_page():
        """Serve the self-service signup form."""
        from flask import Response
        html = SIGNUP_FORM_HTML.replace(
            "window.ONBOARD_API_BASE || ''",
            f"'{request.host_url.rstrip('/')}'",
        )
        return Response(html, mimetype="text/html")

    @app.route("/api/v1/onboard/wizard", methods=["GET"])
    def onboard_wizard():
        """Get wizard step definitions for rendering the signup form."""
        return jsonify({"steps": onboarding.get_wizard_steps()})

    @app.route("/api/v1/onboard/validate", methods=["POST"])
    def onboard_validate():
        """Validate a single wizard step."""
        data = request.get_json()
        if not data or "step" not in data:
            return jsonify({"error": "step and form data required"}), 400
        result = onboarding.validate_step(data["step"], data)
        return jsonify(result)

    @app.route("/api/v1/onboard/signup", methods=["POST"])
    def onboard_signup():
        """
        Complete agency signup in one call.

        Creates API key, agency config, and billing subscription.
        Returns the API key (show once, never stored in plaintext).
        """
        data = request.get_json()
        if not data:
            return jsonify({"error": "Request body required"}), 400
        result = onboarding.signup(data)
        status = 201 if result.get("success") else 400
        return jsonify(result), status

    # ================================================================
    # BILLING — Subscription management
    # ================================================================

    @app.route("/api/v1/billing/plans", methods=["GET"])
    def billing_plans():
        """Get available subscription plans."""
        return jsonify({"plans": billing_manager.get_plans()})

    @app.route("/api/v1/billing/subscription", methods=["GET"])
    @require_api_key
    def billing_subscription():
        """Get current subscription details + usage."""
        return jsonify(billing_manager.get_subscription(request.api_key_hash))

    @app.route("/api/v1/billing/subscribe", methods=["POST"])
    @require_api_key
    def billing_subscribe():
        """Create or update a subscription."""
        data = request.get_json()
        if not data or "plan_id" not in data:
            return jsonify({"error": "plan_id is required"}), 400

        result = billing_manager.create_subscription(
            key_hash=request.api_key_hash,
            plan_id=data["plan_id"],
            email=data.get("email", ""),
            agency_name=request.agency_config.agency_name,
            stripe_payment_method=data.get("payment_method", ""),
        )
        status = 201 if result.get("success") else 400
        return jsonify(result), status

    @app.route("/api/v1/billing/change-plan", methods=["POST"])
    @require_api_key
    def billing_change_plan():
        """Upgrade or downgrade subscription plan."""
        data = request.get_json()
        if not data or "plan_id" not in data:
            return jsonify({"error": "plan_id is required"}), 400
        return jsonify(billing_manager.change_plan(request.api_key_hash, data["plan_id"]))

    @app.route("/api/v1/billing/cancel", methods=["POST"])
    @require_api_key
    def billing_cancel():
        """Cancel subscription (end of billing period)."""
        data = request.get_json() or {}
        return jsonify(billing_manager.cancel_subscription(
            request.api_key_hash,
            reason=data.get("reason", ""),
        ))

    @app.route("/api/v1/billing/cost", methods=["GET"])
    @require_api_key
    def billing_cost():
        """Get estimated cost for current billing period."""
        return jsonify(billing_manager.estimate_cost(request.api_key_hash))

    @app.route("/api/v1/billing/webhook", methods=["POST"])
    def billing_webhook():
        """Stripe webhook handler."""
        if not webhook_secret:
            return jsonify({"error": "Webhooks not configured"}), 400
        payload = request.get_data()
        sig = request.headers.get("Stripe-Signature", "")
        result = billing_manager.handle_webhook(payload, sig, webhook_secret)
        return jsonify(result), 200 if result.get("handled") else 400

    # ================================================================
    # ANALYTICS — Usage dashboards
    # ================================================================

    @app.route("/api/v1/analytics/dashboard", methods=["GET"])
    @require_api_key
    def analytics_dashboard():
        """Get full analytics dashboard data for the agency."""
        return jsonify(analytics.agency_dashboard(request.api_key_hash))

    @app.route("/api/v1/analytics/export", methods=["GET"])
    @require_api_key
    def analytics_export():
        """Export usage data as CSV."""
        from flask import Response as FlaskResponse
        months = min(int(request.args.get("months", 6)), 24)
        csv_data = analytics.export_usage_csv(request.api_key_hash, months)
        return FlaskResponse(
            csv_data,
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=usage_export.csv"},
        )

    @app.route("/api/v1/master/analytics", methods=["GET"])
    @require_master_key
    def platform_analytics():
        """Platform-wide aggregate metrics (ANASTASIA internal only)."""
        return jsonify(analytics.platform_metrics(config_store))

    # ================================================================
    # USAGE TRACKING MIDDLEWARE
    # ================================================================

    @app.after_request
    def track_usage(response):
        """Track API usage after each request."""
        key_hash = getattr(request, "api_key_hash", None)
        if not key_hash:
            return response

        path = request.path
        status = response.status_code

        # Track errors
        if status >= 400:
            category = error_tracker.classify_http_error(status)
            error_tracker.record_error(
                key_hash=key_hash,
                category=category,
                endpoint=path,
                status_code=status,
                message=response.get_data(as_text=True)[:200],
            )
            usage_tracker.record_error(key_hash)

        # Track specific operations
        if status < 400:
            if "/search/flights" in path:
                usage_tracker.record_search(key_hash)
            elif "/booking/create" in path:
                usage_tracker.record_booking(key_hash)
            elif "/booking/document" in path:
                usage_tracker.record_document(key_hash)
            elif "/chat" in path or "/assist" in path:
                usage_tracker.record_ai_request(key_hash)

        return response

    return app


def generate_api_key() -> tuple:
    """
    Generate a new API key and its hash.

    Returns:
        (api_key, sha256_hash) — Give api_key to agency, store hash internally.
    """
    api_key = f"ana_{uuid.uuid4().hex}"
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()
    return api_key, key_hash
