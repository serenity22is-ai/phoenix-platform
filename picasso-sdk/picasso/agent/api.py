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
from ..duffel import DuffelNDCClient
from ..kiwi import KiwiTequilaClient
from ..airgateway import AirGatewayClient
from .analytics import AnalyticsEngine, ErrorTracker
from .billing import BillingManager, UsageTracker, PLANS
from .config import AgencyConfig, ConfigStore
from .db_stores import get_storage_backend, create_stores
from .consumer_ui import CONSUMER_UI_HTML
from .dashboard import ADMIN_DASHBOARD_HTML
from .assist import AssistAgent
from .daemon import AutoHealDaemon
from .onboarding import OnboardingManager, SIGNUP_FORM_HTML
from .orchestrator import BookingAgent
from .pricing import PricingModel, apply_pricing_to_results
from .security import AdminAuth, AuditLog, ActionType, generate_admin_token, hash_token

# ANASTASiA Neuron Network
from anastasia.platform import AnastasiaPlatform
from anastasia.core import EventBus, Event, EventType

# ANASTASiA Module Registry — Dynamic API integration system
from anastasia.modules import ModuleRegistry, ModuleDirector, APIModule
from anastasia.modules.flight_modules import (
    build_all_modules,
    build_picasso_card,
    build_duffel_card,
    build_kiwi_card,
)

logger = logging.getLogger(__name__)


def create_app(config: Optional[dict] = None) -> Flask:
    """
    Create the hosted OTA platform API.

    Config keys:
        ANTHROPIC_API_KEY: str — Required. Anthropic API key.
        AGENT_MODEL: str — Claude model ID (default: claude-opus-4-6)
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

    agent_model = app_config.get("AGENT_MODEL", "claude-opus-4-6")
    max_sessions = app_config.get("MAX_SESSIONS_PER_KEY", 50)
    session_ttl = app_config.get("SESSION_TTL_SECONDS", 3600)
    master_key = app_config.get("MASTER_KEY") or os.environ.get("ANASTASIA_MASTER_KEY", "") or os.environ.get("MYSTES_MASTER_KEY", "")

    # --- Storage backend (file or db) ---
    config_dir = app_config.get("CONFIG_DIR", ".agency_configs")
    storage_backend = get_storage_backend()

    if storage_backend == "db":
        from .db_models import init_db
        init_db(app)

    config_store, usage_tracker, billing_manager = create_stores(app_config)

    # Error tracker stays file-based (lightweight, non-critical)
    data_dir = os.path.join(config_dir, ".data")
    error_tracker = ErrorTracker(os.path.join(data_dir, "errors"))
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

    # --- ANASTASiA Neuron Network ---
    neuron_modules = app_config.get("NEURON_MODULES", None)  # None = all, or list like ["knowledge", "intelligence"]
    neuron_data_dir = app_config.get("NEURON_DATA_DIR") or os.path.join(config_dir, ".neuron_data")
    neuron_config = {
        "data_dir": neuron_data_dir,
        "daemon.cloud_url": app_config.get("API_BASE", ""),
        "daemon.api_key": master_key,
    }
    # Merge any neuron-specific config from app_config
    for key, val in app_config.items():
        if key.startswith("NEURON_") and key not in ("NEURON_MODULES", "NEURON_DATA_DIR"):
            # Convert NEURON_PROFILES_DIR -> profiles_dir
            neuron_key = key[7:].lower()
            neuron_config[neuron_key] = val

    platform = AnastasiaPlatform(neuron_config)
    try:
        platform.start(modules=neuron_modules)
        logger.info("ANASTASiA neuron network online")
    except Exception as e:
        logger.error("Neuron network startup failed (non-fatal): %s", e)

    # Store platform on app for access in routes
    app.anastasia_platform = platform

    # --- Duffel NDC Client (shared across all agencies) ---
    duffel_token = app_config.get("DUFFEL_ACCESS_TOKEN") or os.environ.get("DUFFEL_ACCESS_TOKEN", "")
    duffel_client = DuffelNDCClient(access_token=duffel_token) if duffel_token else None
    if duffel_client and duffel_client.is_configured():
        logger.info("Duffel NDC client configured — NDC tools enabled")
    else:
        duffel_client = None
        logger.info("Duffel NDC not configured — NDC tools disabled")

    # --- Kiwi Tequila Client (shared across all agencies) ---
    kiwi_key = app_config.get("KIWI_API_KEY") or os.environ.get("KIWI_API_KEY", "")
    kiwi_client = KiwiTequilaClient(api_key=kiwi_key) if kiwi_key else None
    if kiwi_client and kiwi_client.is_configured():
        logger.info("Kiwi Tequila client configured — aggregator tools enabled")
    else:
        kiwi_client = None
        logger.info("Kiwi Tequila not configured — aggregator tools disabled")

    # --- AirGateway NDC Client (shared across all agencies) ---
    agw_key = app_config.get("AIRGATEWAY_API_KEY") or os.environ.get("AIRGATEWAY_API_KEY", "")
    agw_sandbox = app_config.get("AIRGATEWAY_SANDBOX", True)
    airgateway_client = AirGatewayClient(api_key=agw_key, sandbox=agw_sandbox) if agw_key else None
    if airgateway_client and airgateway_client.is_configured():
        logger.info("AirGateway NDC client configured — NDC + POS arbitrage tools enabled")
    else:
        airgateway_client = None
        logger.info("AirGateway NDC not configured — NDC arbitrage tools disabled")

    # --- ANASTASiA Module Registry — Dynamic API Integration ---
    # The Module Registry + Director replaces hardcoded client wiring.
    # Each API source is a module with a knowledge card. The Director reads
    # cards and dynamically creates search/booking pipelines.
    module_registry = ModuleRegistry()

    # Register all known modules with client factories + tool/knowledge bindings
    from .tools import TOOL_DEFINITIONS
    from .knowledge_base import KNOWLEDGE_BASE
    from .duffel_tools import DUFFEL_TOOL_DEFINITIONS
    from .duffel_knowledge import DUFFEL_KNOWLEDGE_BASE
    from .kiwi_tools import KIWI_TOOL_DEFINITIONS
    from .kiwi_knowledge import KIWI_KNOWLEDGE_BASE
    from .airgateway_tools import AIRGATEWAY_TOOL_DEFINITIONS
    from .airgateway_knowledge import AIRGATEWAY_KNOWLEDGE_BASE

    # Build all module cards and register with factories
    for api_module in build_all_modules():
        mid = api_module.knowledge_card.module_id
        # Wire client factories + tools for modules we have clients for
        if mid == "picasso_redbox":
            api_module.tools = list(TOOL_DEFINITIONS)
            api_module.knowledge_prompt = KNOWLEDGE_BASE
        elif mid == "duffel_ndc":
            api_module.client_factory = lambda: DuffelNDCClient(
                access_token=os.environ.get("DUFFEL_ACCESS_TOKEN", "")
            )
            if duffel_client:
                api_module.client_instance = duffel_client
                api_module.is_loaded = True
            api_module.tools = list(DUFFEL_TOOL_DEFINITIONS)
            api_module.knowledge_prompt = DUFFEL_KNOWLEDGE_BASE
        elif mid == "kiwi_tequila":
            api_module.client_factory = lambda: KiwiTequilaClient(
                api_key=os.environ.get("KIWI_API_KEY", "")
            )
            if kiwi_client:
                api_module.client_instance = kiwi_client
                api_module.is_loaded = True
            api_module.tools = list(KIWI_TOOL_DEFINITIONS)
            api_module.knowledge_prompt = KIWI_KNOWLEDGE_BASE
        elif mid == "airgateway_ndc":
            api_module.client_factory = lambda: AirGatewayClient(
                api_key=os.environ.get("AIRGATEWAY_API_KEY", ""),
                sandbox=bool(os.environ.get("AIRGATEWAY_SANDBOX", "1")),
            )
            if airgateway_client:
                api_module.client_instance = airgateway_client
                api_module.is_loaded = True
            api_module.tools = list(AIRGATEWAY_TOOL_DEFINITIONS)
            api_module.knowledge_prompt = AIRGATEWAY_KNOWLEDGE_BASE
        # Discovered modules (Mystifly, Travelfusion, TripStack) have no client yet —
        # they register with just a knowledge card so the Director knows they exist
        module_registry.register(api_module)

    module_director = ModuleDirector(module_registry)
    app.module_registry = module_registry
    app.module_director = module_director

    configured_count = len(module_registry.list_configured())
    total_count = len(module_registry.list_modules())
    logger.info(
        "Module Registry online: %d/%d modules configured (%s)",
        configured_count, total_count,
        ", ".join(m.knowledge_card.name for m in module_registry.list_configured()),
    )

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
        neuron_health = platform.health() if platform.is_running else {"platform": "stopped"}
        return jsonify({
            "status": "healthy",
            "active_sessions": len(sessions),
            "neuron_network": neuron_health.get("platform", "stopped"),
            "neurons_online": neuron_health.get("neurons_online", 0),
        })

    @app.route("/api/v1/neurons", methods=["GET"])
    @require_master_key
    def neuron_status():
        """Detailed neuron network status — master key required."""
        return jsonify(platform.health())

    @app.route("/api/v1/neurons/modules", methods=["GET"])
    @require_master_key
    def neuron_modules_list():
        """List all registered neuron modules."""
        return jsonify({"modules": platform.list_modules()})

    @app.route("/api/v1/neurons/events", methods=["GET"])
    @require_master_key
    def neuron_events():
        """Get recent neuron events for debugging."""
        limit = min(int(request.args.get("limit", 50)), 500)
        event_type_str = request.args.get("type")

        from anastasia.core import EventType
        event_type = None
        if event_type_str:
            try:
                event_type = EventType(event_type_str)
            except ValueError:
                return jsonify({"error": f"Unknown event type: {event_type_str}"}), 400

        events = platform.get_event_bus().get_recent_events(
            event_type=event_type,
            limit=limit,
        )
        return jsonify({
            "events": [e.to_dict() for e in events],
            "count": len(events),
        })

    # =========================================================================
    # MODULE REGISTRY ENDPOINTS — API module management
    # =========================================================================

    @app.route("/api/v1/modules", methods=["GET"])
    @require_master_key
    def list_api_modules():
        """List all registered API modules and their credential status."""
        vertical = request.args.get("vertical")
        configured_only = request.args.get("configured_only", "false").lower() == "true"
        modules = module_registry.list_modules(
            vertical=vertical,
            configured_only=configured_only,
        )
        return jsonify({
            "modules": [
                {
                    **m.knowledge_card.to_dict(),
                    "configured": m.is_configured,
                    "loaded": m.is_loaded,
                    "has_tools": len(m.tools) > 0,
                    "has_knowledge": bool(m.knowledge_prompt),
                }
                for m in modules
            ],
            "total": len(modules),
            "configured": sum(1 for m in modules if m.is_configured),
        })

    @app.route("/api/v1/modules/dashboard", methods=["GET"])
    @require_master_key
    def module_dashboard():
        """Get the Module Director's text dashboard."""
        return jsonify({
            "dashboard": module_director.generate_dashboard(),
            "verticals": module_director.get_verticals(),
            "capabilities": module_director.get_capabilities(),
        })

    @app.route("/api/v1/modules/search-plan", methods=["POST"])
    @require_api_key
    def module_search_plan():
        """Get the Director's optimal search plan for a vertical."""
        data = request.get_json(silent=True) or {}
        vertical = data.get("vertical", "flights")
        origin = data.get("origin")
        destination = data.get("destination")
        plan = module_director.plan_search(
            vertical=vertical,
            origin=origin,
            destination=destination,
        )
        return jsonify(plan.to_dict())

    @app.route("/api/v1/modules/refresh", methods=["POST"])
    @require_master_key
    def refresh_module_credentials():
        """Re-check all module credentials and return updated status."""
        results = module_registry.refresh_credentials()
        return jsonify({
            "credentials": results,
            "configured_count": sum(1 for v in results.values() if v),
            "total_count": len(results),
        })

    @app.route("/admin/dashboard")
    def admin_dashboard():
        """
        Serve the admin dashboard UI.

        Pass API key and base URL as query params:
            /admin/dashboard?key=ana_abc123&base=https://your-server.com
        """
        from flask import Response
        from .network_ui import inject_network_ui
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
        # Inject Network, Terminal, and Modules tabs
        html = inject_network_ui(html)
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
                duffel_client=duffel_client,
                kiwi_client=kiwi_client,
                airgateway_client=airgateway_client,
                event_bus=platform.event_bus if platform.is_running else None,
                agency_id=agency_cfg.agency_id,
                module_director=module_director,
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
    # MASTER ADMIN — Register/manage agencies (ANASTASiA internal only)
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
        """Platform-wide aggregate metrics (ANASTASiA internal only)."""
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

    # ================================================================
    # DAEMON CLOUD ENDPOINTS — Receive communications from remote daemons
    # ================================================================

    # In-memory daemon registry (production would use Redis/DB)
    daemon_registry: dict = {}  # daemon_id -> {status, last_heartbeat, ...}

    @app.route("/api/v1/daemon/connect", methods=["POST"])
    @require_master_key
    def daemon_connect():
        """Accept a daemon connection handshake."""
        data = request.get_json() or {}
        daemon_id = data.get("daemon_id", "")
        if not daemon_id:
            return jsonify({"error": "daemon_id required"}), 400

        daemon_registry[daemon_id] = {
            "status": "connected",
            "connected_at": time.time(),
            "last_heartbeat": time.time(),
            "protocol_version": data.get("protocol_version", "unknown"),
        }

        # Publish event to neuron network
        platform.get_event_bus().publish(Event(
            type=EventType.DAEMON_CONNECTED,
            source="cloud",
            data={"daemon_id": daemon_id},
        ))

        logger.info("Daemon connected: %s", daemon_id)
        return jsonify({"status": "connected", "daemon_id": daemon_id})

    @app.route("/api/v1/daemon/disconnect", methods=["POST"])
    @require_master_key
    def daemon_cloud_disconnect():
        """Accept a daemon disconnect notification."""
        data = request.get_json() or {}
        daemon_id = data.get("daemon_id", "")
        if daemon_id in daemon_registry:
            daemon_registry[daemon_id]["status"] = "disconnected"

        platform.get_event_bus().publish(Event(
            type=EventType.DAEMON_DISCONNECTED,
            source="cloud",
            data={"daemon_id": daemon_id},
        ))

        return jsonify({"status": "disconnected"})

    @app.route("/api/v1/daemon/heartbeat", methods=["POST"])
    @require_master_key
    def daemon_heartbeat_recv():
        """Accept a daemon heartbeat and return acknowledgment."""
        data = request.get_json() or {}
        daemon_id = data.get("daemon_id", "")

        if daemon_id in daemon_registry:
            daemon_registry[daemon_id]["last_heartbeat"] = time.time()
            daemon_registry[daemon_id]["status_data"] = data.get("status", {})
            daemon_registry[daemon_id]["connection_health"] = data.get("connection_health", {})

        platform.get_event_bus().publish(Event(
            type=EventType.DAEMON_HEARTBEAT,
            source="cloud",
            data={"daemon_id": daemon_id, "status": data.get("status", {})},
        ))

        return jsonify({"acknowledged": True})

    @app.route("/api/v1/daemon/discovery", methods=["POST"])
    @require_master_key
    def daemon_discovery():
        """Receive a tech stack discovery report from a daemon."""
        data = request.get_json() or {}
        daemon_id = data.get("daemon_id", "")
        tech_stack = data.get("tech_stack", {})
        file_manifest = data.get("file_manifest", [])

        # Store discovery on the daemon record
        if daemon_id in daemon_registry:
            daemon_registry[daemon_id]["tech_stack"] = tech_stack
            daemon_registry[daemon_id]["file_count"] = len(file_manifest)

        platform.get_event_bus().publish(Event(
            type=EventType.SYSTEM_DISCOVERED,
            source="cloud",
            data={
                "daemon_id": daemon_id,
                "tech_stack": tech_stack,
                "file_count": len(file_manifest),
            },
        ))

        # Feed to knowledge module if available
        knowledge = platform.get_module("knowledge")
        profile_id = None
        if knowledge and hasattr(knowledge, "_learning") and knowledge._learning:
            from anastasia.core.types import TechStack as TechStackType
            try:
                ts = TechStackType.from_dict(tech_stack)
                profile_id = f"daemon_{daemon_id}"
            except Exception:
                pass

        return jsonify({
            "status": "received",
            "profile_id": profile_id,
            "file_count": len(file_manifest),
        })

    @app.route("/api/v1/daemon/<daemon_id>/instructions", methods=["GET"])
    @require_master_key
    def daemon_instructions(daemon_id):
        """Serve pending approved proposals to a daemon."""
        # Get integrator module for pending proposals
        integrator = platform.get_module("integrator")
        proposals = []
        if integrator and hasattr(integrator, "_approval"):
            pending = integrator._approval.list_proposals(status="approved")
            proposals = [p.to_dict() for p in pending if not getattr(p, '_executed', False)]

        return jsonify({"proposals": proposals})

    @app.route("/api/v1/daemon/result", methods=["POST"])
    @require_master_key
    def daemon_result():
        """Receive execution results from a daemon."""
        data = request.get_json() or {}
        proposal_id = data.get("proposal_id", "")
        success = data.get("success", False)

        platform.get_event_bus().publish(Event(
            type=EventType.PROPOSAL_EXECUTED,
            source="cloud",
            data={
                "daemon_id": data.get("daemon_id"),
                "proposal_id": proposal_id,
                "success": success,
                "output": data.get("output", "")[:1000],
            },
        ))

        return jsonify({"acknowledged": True})

    @app.route("/api/v1/daemon/<daemon_id>/license", methods=["GET"])
    @require_master_key
    def daemon_license(daemon_id):
        """Verify daemon license status."""
        # Check if daemon is registered
        if daemon_id not in daemon_registry:
            return jsonify({"valid": False, "tier": "unknown", "expires": "", "features": []})

        return jsonify({
            "valid": True,
            "tier": "enterprise",
            "expires": "2027-03-08T00:00:00Z",
            "features": [
                "file_operations", "git_operations", "command_execution",
                "test_execution", "code_generation",
            ],
        })

    @app.route("/api/v1/daemon/registry", methods=["GET"])
    @require_master_key
    def daemon_registry_list():
        """List all known daemons and their status."""
        daemons = []
        now = time.time()
        for did, info in daemon_registry.items():
            last_hb = info.get("last_heartbeat", 0)
            daemons.append({
                "daemon_id": did,
                "status": info.get("status", "unknown"),
                "last_heartbeat_ago": f"{int(now - last_hb)}s" if last_hb else "never",
                "protocol_version": info.get("protocol_version", "unknown"),
                "tech_stack": info.get("tech_stack"),
            })
        return jsonify({"daemons": daemons, "count": len(daemons)})

    # ================================================================
    # BRIDGE ENDPOINTS — Confidential Collaborative Development Protocol
    # ================================================================

    @app.route("/api/v1/bridge/create", methods=["POST"])
    @require_master_key
    def bridge_create():
        """Create a new bridge between two entities."""
        data = request.get_json() or {}
        entity_a_id = data.get("entity_a_id", "")
        entity_b_id = data.get("entity_b_id", "")
        if not entity_a_id or not entity_b_id:
            return jsonify({"error": "entity_a_id and entity_b_id required"}), 400

        bridge_mod = platform.get_module("bridge")
        if not bridge_mod:
            return jsonify({"error": "Bridge module not available"}), 503

        result = bridge_mod.protocol.create_bridge(
            entity_a_id=entity_a_id,
            entity_b_id=entity_b_id,
            entity_a_name=data.get("entity_a_name", ""),
            entity_b_name=data.get("entity_b_name", ""),
            entity_a_shares=data.get("entity_a_shares"),
            entity_b_shares=data.get("entity_b_shares"),
            ip_ownership=data.get("ip_ownership", "bilateral"),
        )
        return jsonify(result), 201

    @app.route("/api/v1/bridge/<bridge_id>/accept", methods=["POST"])
    @require_master_key
    def bridge_accept(bridge_id):
        """Accept a bridge from one entity's side."""
        data = request.get_json() or {}
        entity_id = data.get("entity_id", "")
        if not entity_id:
            return jsonify({"error": "entity_id required"}), 400

        bridge_mod = platform.get_module("bridge")
        if not bridge_mod:
            return jsonify({"error": "Bridge module not available"}), 503

        try:
            result = bridge_mod.protocol.accept_bridge(bridge_id, entity_id)
            return jsonify(result)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/api/v1/bridge/<bridge_id>/sync", methods=["POST"])
    @require_master_key
    def bridge_sync_knowledge(bridge_id):
        """Sync structural knowledge from one entity to the bridge."""
        data = request.get_json() or {}
        entity_id = data.get("entity_id", "")
        if not entity_id:
            return jsonify({"error": "entity_id required"}), 400

        bridge_mod = platform.get_module("bridge")
        if not bridge_mod:
            return jsonify({"error": "Bridge module not available"}), 503

        try:
            result = bridge_mod.protocol.sync_knowledge(
                bridge_id=bridge_id,
                entity_id=entity_id,
                routes=data.get("routes"),
                models=data.get("models"),
                auth_config=data.get("auth_config"),
                codebase_info=data.get("codebase_info"),
                tech_stack=data.get("tech_stack"),
            )
            return jsonify(result)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/api/v1/bridge/<bridge_id>/analyze", methods=["POST"])
    @require_master_key
    def bridge_analyze(bridge_id):
        """Analyze both sides and generate integration proposals."""
        bridge_mod = platform.get_module("bridge")
        if not bridge_mod:
            return jsonify({"error": "Bridge module not available"}), 503

        try:
            result = bridge_mod.protocol.analyze_and_propose(bridge_id)
            return jsonify(result)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/api/v1/bridge/<bridge_id>/proposals", methods=["GET"])
    @require_master_key
    def bridge_proposals(bridge_id):
        """Get proposals for a specific entity on a bridge."""
        entity_id = request.args.get("entity_id", "")
        if not entity_id:
            return jsonify({"error": "entity_id query param required"}), 400

        bridge_mod = platform.get_module("bridge")
        if not bridge_mod:
            return jsonify({"error": "Bridge module not available"}), 503

        proposals = bridge_mod.protocol.get_proposals_for_entity(bridge_id, entity_id)
        return jsonify({"proposals": proposals, "count": len(proposals)})

    @app.route("/api/v1/bridge/proposal/<proposal_id>/approve", methods=["POST"])
    @require_master_key
    def bridge_proposal_approve(proposal_id):
        """Approve a bridge proposal."""
        data = request.get_json() or {}
        approved_by = data.get("approved_by", "admin")

        bridge_mod = platform.get_module("bridge")
        if not bridge_mod:
            return jsonify({"error": "Bridge module not available"}), 503

        try:
            result = bridge_mod.protocol.approve_proposal(proposal_id, approved_by)
            return jsonify(result)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/api/v1/bridge/proposal/<proposal_id>/reject", methods=["POST"])
    @require_master_key
    def bridge_proposal_reject(proposal_id):
        """Reject a bridge proposal."""
        data = request.get_json() or {}
        reason = data.get("reason", "")

        bridge_mod = platform.get_module("bridge")
        if not bridge_mod:
            return jsonify({"error": "Bridge module not available"}), 503

        try:
            result = bridge_mod.protocol.reject_proposal(proposal_id, reason)
            return jsonify(result)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/api/v1/bridge/<bridge_id>", methods=["GET"])
    @require_master_key
    def bridge_status(bridge_id):
        """Get detailed bridge status."""
        bridge_mod = platform.get_module("bridge")
        if not bridge_mod:
            return jsonify({"error": "Bridge module not available"}), 503

        try:
            result = bridge_mod.protocol.get_bridge_status(bridge_id)
            return jsonify(result)
        except ValueError as e:
            return jsonify({"error": str(e)}), 404

    @app.route("/api/v1/bridges", methods=["GET"])
    @require_master_key
    def bridge_list():
        """List all bridges."""
        entity_id = request.args.get("entity_id")

        bridge_mod = platform.get_module("bridge")
        if not bridge_mod:
            return jsonify({"error": "Bridge module not available"}), 503

        bridges = bridge_mod.protocol.list_bridges(entity_id=entity_id)
        return jsonify({"bridges": bridges, "count": len(bridges)})

    @app.route("/api/v1/bridge/<bridge_id>/pause", methods=["POST"])
    @require_master_key
    def bridge_pause(bridge_id):
        """Pause a bridge."""
        data = request.get_json() or {}
        reason = data.get("reason", "")

        bridge_mod = platform.get_module("bridge")
        if not bridge_mod:
            return jsonify({"error": "Bridge module not available"}), 503

        try:
            result = bridge_mod.protocol.pause_bridge(bridge_id, reason)
            return jsonify(result)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/api/v1/bridge/<bridge_id>/resume", methods=["POST"])
    @require_master_key
    def bridge_resume(bridge_id):
        """Resume a paused bridge."""
        bridge_mod = platform.get_module("bridge")
        if not bridge_mod:
            return jsonify({"error": "Bridge module not available"}), 503

        try:
            result = bridge_mod.protocol.resume_bridge(bridge_id)
            return jsonify(result)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/api/v1/bridge/<bridge_id>/terminate", methods=["POST"])
    @require_master_key
    def bridge_terminate(bridge_id):
        """Terminate a bridge permanently."""
        data = request.get_json() or {}
        reason = data.get("reason", "")

        bridge_mod = platform.get_module("bridge")
        if not bridge_mod:
            return jsonify({"error": "Bridge module not available"}), 503

        try:
            result = bridge_mod.protocol.terminate_bridge(bridge_id, reason)
            return jsonify(result)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/api/v1/bridge/<bridge_id>/audit", methods=["GET"])
    @require_master_key
    def bridge_audit(bridge_id):
        """Get firewall audit log for one side of a bridge."""
        entity_id = request.args.get("entity_id", "")
        limit = min(int(request.args.get("limit", 100)), 1000)

        if not entity_id:
            return jsonify({"error": "entity_id query param required"}), 400

        bridge_mod = platform.get_module("bridge")
        if not bridge_mod:
            return jsonify({"error": "Bridge module not available"}), 503

        try:
            audit = bridge_mod.protocol.get_firewall_audit(
                bridge_id, entity_id, limit
            )
            return jsonify({"audit": audit, "count": len(audit)})
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/api/v1/bridge/partners/<entity_id>", methods=["GET"])
    @require_master_key
    def bridge_partners(entity_id):
        """Get all active bridge partners for an entity."""
        bridge_mod = platform.get_module("bridge")
        if not bridge_mod:
            return jsonify({"error": "Bridge module not available"}), 503

        partners = bridge_mod.protocol.get_partners(entity_id)
        return jsonify({"partners": partners, "count": len(partners)})

    # =================================================================
    # NEURON API ENDPOINTS — Every neuron gets a real API surface
    # =================================================================

    # --- Payments Neuron ---

    @app.route("/api/v1/payments/adapters", methods=["GET"])
    @require_master_key
    def payments_adapters():
        """List all registered payment adapters and their health."""
        mod = platform.get_module("payments")
        if not mod:
            return jsonify({"error": "Payments module not available"}), 503
        adapters = mod.registry.list_adapters()
        return jsonify({"adapters": adapters, "count": len(adapters)})

    @app.route("/api/v1/payments/charge", methods=["POST"])
    @require_master_key
    def payments_charge():
        """Process a payment through a registered adapter."""
        mod = platform.get_module("payments")
        if not mod:
            return jsonify({"error": "Payments module not available"}), 503
        data = request.get_json(silent=True) or {}
        required = ["processor", "amount_cents", "currency", "description"]
        missing = [f for f in required if f not in data]
        if missing:
            return jsonify({"error": f"Missing fields: {missing}"}), 400
        try:
            result = mod.process_payment(
                processor_name=data["processor"],
                amount_cents=data["amount_cents"],
                currency=data["currency"],
                description=data["description"],
                metadata=data.get("metadata"),
                agency_id=data.get("agency_id"),
            )
            return jsonify(result)
        except Exception as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/api/v1/payments/refund", methods=["POST"])
    @require_master_key
    def payments_refund():
        """Process a refund through a registered adapter."""
        mod = platform.get_module("payments")
        if not mod:
            return jsonify({"error": "Payments module not available"}), 503
        data = request.get_json(silent=True) or {}
        if not data.get("processor") or not data.get("charge_id"):
            return jsonify({"error": "Missing processor or charge_id"}), 400
        try:
            result = mod.process_refund(
                processor_name=data["processor"],
                charge_id=data["charge_id"],
                amount_cents=data.get("amount_cents"),
                agency_id=data.get("agency_id"),
            )
            return jsonify(result)
        except Exception as e:
            return jsonify({"error": str(e)}), 400

    # --- Intelligence Neuron ---

    @app.route("/api/v1/intelligence/record-price", methods=["POST"])
    @require_master_key
    def intelligence_record_price():
        """Record a price observation for trend analysis."""
        mod = platform.get_module("intelligence")
        if not mod or not mod.aggregator:
            return jsonify({"error": "Intelligence module not available"}), 503
        data = request.get_json(silent=True) or {}
        if not data.get("route") or data.get("price") is None:
            return jsonify({"error": "Missing route or price"}), 400
        mod.aggregator.record_price(
            route=data["route"],
            price=data["price"],
            currency=data.get("currency", "USD"),
            source=data.get("source", "api"),
            cabin=data.get("cabin", "economy"),
        )
        return jsonify({"recorded": True, "route": data["route"]})

    @app.route("/api/v1/intelligence/trends/<route>", methods=["GET"])
    @require_master_key
    def intelligence_trends(route):
        """Get trend analysis for a route."""
        mod = platform.get_module("intelligence")
        if not mod or not mod.trend_analyzer:
            return jsonify({"error": "Intelligence module not available"}), 503
        trend = mod.trend_analyzer.analyze_trend(route)
        return jsonify({"route": route, "trend": trend})

    @app.route("/api/v1/intelligence/alerts", methods=["GET"])
    @require_master_key
    def intelligence_alerts():
        """List active price alerts."""
        mod = platform.get_module("intelligence")
        if not mod or not mod.alert_engine:
            return jsonify({"error": "Intelligence module not available"}), 503
        agency_id = request.args.get("agency_id", "")
        alerts = mod.alert_engine.get_alerts(agency_id) if agency_id else []
        return jsonify({"alerts": alerts, "count": len(alerts)})

    @app.route("/api/v1/intelligence/alerts", methods=["POST"])
    @require_master_key
    def intelligence_create_alert():
        """Create a price alert for a route."""
        mod = platform.get_module("intelligence")
        if not mod or not mod.alert_engine:
            return jsonify({"error": "Intelligence module not available"}), 503
        data = request.get_json(silent=True) or {}
        required = ["agency_id", "route", "threshold_price"]
        missing = [f for f in required if f not in data]
        if missing:
            return jsonify({"error": f"Missing fields: {missing}"}), 400
        alert = mod.alert_engine.create_alert(
            agency_id=data["agency_id"],
            route=data["route"],
            threshold_price=data["threshold_price"],
            currency=data.get("currency", "USD"),
        )
        return jsonify(alert), 201

    # --- Resilience Neuron ---

    @app.route("/api/v1/resilience/status", methods=["GET"])
    @require_master_key
    def resilience_status():
        """Get circuit breaker and health monitor status."""
        mod = platform.get_module("resilience")
        if not mod:
            return jsonify({"error": "Resilience module not available"}), 503
        health = mod.health_check()
        return jsonify(health)

    # --- Tenancy Neuron ---

    @app.route("/api/v1/tenancy/tenants", methods=["GET"])
    @require_master_key
    def tenancy_list():
        """List all tenants."""
        mod = platform.get_module("tenancy")
        if not mod:
            return jsonify({"error": "Tenancy module not available"}), 503
        health = mod.health_check()
        return jsonify(health)

    @app.route("/api/v1/tenancy/tenants", methods=["POST"])
    @require_master_key
    def tenancy_create():
        """Provision a new tenant."""
        mod = platform.get_module("tenancy")
        if not mod:
            return jsonify({"error": "Tenancy module not available"}), 503
        data = request.get_json(silent=True) or {}
        if not data.get("tenant_id") or not data.get("name"):
            return jsonify({"error": "Missing tenant_id or name"}), 400
        try:
            result = mod.provision(
                tenant_id=data["tenant_id"],
                name=data["name"],
                tier=data.get("tier", "standard"),
            )
            return jsonify(result), 201
        except Exception as e:
            return jsonify({"error": str(e)}), 400

    # --- Compliance Neuron ---

    @app.route("/api/v1/compliance/audit", methods=["GET"])
    @require_master_key
    def compliance_audit_log():
        """Query the compliance audit trail."""
        mod = platform.get_module("compliance")
        if not mod or not mod.audit:
            return jsonify({"error": "Compliance module not available"}), 503
        limit = request.args.get("limit", 100, type=int)
        agency_id = request.args.get("agency_id")
        entries = mod.audit.get_recent(limit=limit, agency_id=agency_id)
        return jsonify({"entries": entries, "count": len(entries)})

    @app.route("/api/v1/compliance/check", methods=["POST"])
    @require_master_key
    def compliance_check():
        """Run a compliance check against a regulation."""
        mod = platform.get_module("compliance")
        if not mod or not mod.regulation_engine:
            return jsonify({"error": "Compliance module not available"}), 503
        data = request.get_json(silent=True) or {}
        regulation = data.get("regulation", "PCI_DSS")
        result = mod.regulation_engine.check_compliance(
            data.get("payload", {}), regulation
        )
        return jsonify(result)

    @app.route("/api/v1/compliance/pii/scan", methods=["POST"])
    @require_master_key
    def compliance_pii_scan():
        """Scan text for PII and return detected entities."""
        mod = platform.get_module("compliance")
        if not mod or not mod.pii_protector:
            return jsonify({"error": "Compliance module not available"}), 503
        data = request.get_json(silent=True) or {}
        text = data.get("text", "")
        detected = mod.pii_protector.detect(text)
        sanitized = mod.pii_protector.sanitize(text)
        return jsonify({
            "detected": detected,
            "sanitized": sanitized,
            "pii_found": len(detected) > 0,
        })

    # --- Credits Neuron ---

    @app.route("/api/v1/credits/balance/<agency_id>", methods=["GET"])
    @require_master_key
    def credits_balance(agency_id):
        """Get credit balance for an agency."""
        mod = platform.get_module("credits")
        if not mod:
            return jsonify({"error": "Credits module not available"}), 503
        health = mod.health_check()
        return jsonify({"agency_id": agency_id, "module_health": health})

    @app.route("/api/v1/credits/earn", methods=["POST"])
    @require_master_key
    def credits_earn():
        """Award credits to an agency."""
        mod = platform.get_module("credits")
        if not mod:
            return jsonify({"error": "Credits module not available"}), 503
        data = request.get_json(silent=True) or {}
        if not data.get("agency_id") or data.get("amount") is None:
            return jsonify({"error": "Missing agency_id or amount"}), 400
        try:
            result = mod.earn(
                agency_id=data["agency_id"],
                amount=data["amount"],
                reason=data.get("reason", "api_award"),
            )
            return jsonify(result)
        except Exception as e:
            return jsonify({"error": str(e)}), 400

    # --- Portability Neuron ---

    @app.route("/api/v1/portability/targets", methods=["GET"])
    @require_master_key
    def portability_targets():
        """List available migration targets."""
        mod = platform.get_module("portability")
        if not mod:
            return jsonify({"error": "Portability module not available"}), 503
        from anastasia.portability.migration import KNOWN_TARGETS
        targets = {
            k: {"label": v.get("label", k), "description": v.get("description", "")}
            for k, v in KNOWN_TARGETS.items()
        }
        return jsonify({"targets": targets, "count": len(targets)})

    @app.route("/api/v1/portability/migrate", methods=["POST"])
    @require_master_key
    def portability_migrate():
        """Migrate booking data to a target format."""
        mod = platform.get_module("portability")
        if not mod:
            return jsonify({"error": "Portability module not available"}), 503
        data = request.get_json(silent=True) or {}
        target = data.get("target_format")
        bookings = data.get("bookings", [])
        if not target or not bookings:
            return jsonify({"error": "Missing target_format or bookings"}), 400
        try:
            result = mod.migration_tool.migrate_bookings(bookings, target)
            return jsonify({
                "migrated": result,
                "count": len(result),
                "target": target,
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/api/v1/portability/export", methods=["POST"])
    @require_master_key
    def portability_export():
        """Export data in CSV/XML/JSON format."""
        mod = platform.get_module("portability")
        if not mod:
            return jsonify({"error": "Portability module not available"}), 503
        data = request.get_json(silent=True) or {}
        fmt = data.get("format", "json")
        records = data.get("records", [])
        if not records:
            return jsonify({"error": "Missing records"}), 400
        try:
            result = mod.format_converter.convert(records, fmt)
            return jsonify({"format": fmt, "output": result})
        except Exception as e:
            return jsonify({"error": str(e)}), 400

    # --- Sandbox Neuron ---

    @app.route("/api/v1/sandbox/environments", methods=["GET"])
    @require_master_key
    def sandbox_list():
        """List sandbox environments."""
        mod = platform.get_module("sandbox")
        if not mod:
            return jsonify({"error": "Sandbox module not available"}), 503
        health = mod.health_check()
        return jsonify(health)

    @app.route("/api/v1/sandbox/environments", methods=["POST"])
    @require_master_key
    def sandbox_create():
        """Create a new sandbox environment for testing."""
        mod = platform.get_module("sandbox")
        if not mod:
            return jsonify({"error": "Sandbox module not available"}), 503
        data = request.get_json(silent=True) or {}
        if not data.get("agency_id"):
            return jsonify({"error": "Missing agency_id"}), 400
        try:
            result = mod.create_sandbox(
                agency_id=data["agency_id"],
                config=data.get("config", {}),
            )
            return jsonify(result), 201
        except Exception as e:
            return jsonify({"error": str(e)}), 400

    # --- Daemon Neuron ---

    @app.route("/api/v1/daemon/status", methods=["GET"])
    @require_master_key
    def daemon_status():
        """Get daemon neuron health and capabilities."""
        mod = platform.get_module("daemon")
        if not mod:
            return jsonify({"error": "Daemon module not available"}), 503
        health = mod.health_check()
        return jsonify(health)

    # --- Per-Neuron Health Endpoint ---

    # ------------------------------------------------------------------
    # Knowledge — Auto-Learning Pipeline (Claude Opus 4.6 powered)
    # ------------------------------------------------------------------

    @app.route("/api/v1/knowledge/learn", methods=["POST"])
    @require_master_key
    def knowledge_learn():
        """Run the full auto-learning pipeline on a codebase scan.

        Accepts a daemon codebase scan and autonomously discovers,
        probes, analyzes (via Claude Opus 4.6), and permanently
        learns every unknown API it finds.

        Body: {"codebase_scan": {...}} — output from daemon.scan_codebase()
        """
        mod = platform.get_module("knowledge")
        if not mod:
            return jsonify({"error": "Knowledge neuron not available"}), 503
        data = request.get_json(silent=True) or {}
        scan = data.get("codebase_scan", {})
        if not scan:
            return jsonify({"error": "codebase_scan required"}), 400
        result = mod.auto_learner.learn(scan)
        return jsonify(result)

    @app.route("/api/v1/knowledge/encounter", methods=["POST"])
    @require_master_key
    def knowledge_encounter():
        """Discover unknown APIs from a codebase scan (stage 1 only).

        Body: {"codebase_scan": {...}}
        Returns: list of APIDiscovery objects.
        """
        mod = platform.get_module("knowledge")
        if not mod:
            return jsonify({"error": "Knowledge neuron not available"}), 503
        data = request.get_json(silent=True) or {}
        scan = data.get("codebase_scan", {})
        if not scan:
            return jsonify({"error": "codebase_scan required"}), 400
        discoveries = mod.auto_learner.encounter(scan)
        return jsonify({
            "discoveries": [d.to_dict() for d in discoveries],
            "count": len(discoveries),
        })

    @app.route("/api/v1/knowledge/discoveries", methods=["GET"])
    @require_master_key
    def knowledge_discoveries():
        """List all discoveries from the current session."""
        mod = platform.get_module("knowledge")
        if not mod:
            return jsonify({"error": "Knowledge neuron not available"}), 503
        all_disc = mod.auto_learner.discoveries
        return jsonify({
            "discoveries": [d.to_dict() for d in all_disc.values()],
            "pending": len(mod.auto_learner.pending_discoveries),
            "total": len(all_disc),
        })

    @app.route("/api/v1/knowledge/catalog", methods=["GET"])
    @require_master_key
    def knowledge_catalog():
        """Export the full knowledge catalog (all known systems)."""
        mod = platform.get_module("knowledge")
        if not mod:
            return jsonify({"error": "Knowledge neuron not available"}), 503
        return jsonify(mod.catalog.export_catalog())

    @app.route("/api/v1/knowledge/catalog/search", methods=["GET"])
    @require_master_key
    def knowledge_catalog_search():
        """Search the knowledge catalog.

        Query params: q (search query)
        """
        mod = platform.get_module("knowledge")
        if not mod:
            return jsonify({"error": "Knowledge neuron not available"}), 503
        query = request.args.get("q", "")
        if not query:
            return jsonify({"error": "q query parameter required"}), 400
        results = mod.catalog.search_catalog(query)
        return jsonify({"results": results, "query": query})

    @app.route("/api/v1/knowledge/compatibility", methods=["POST"])
    @require_master_key
    def knowledge_compatibility():
        """Check system compatibility with a tech stack.

        Body: {"system_name": "Redbox", "tech_stack": {"language": "python", ...}}
        """
        mod = platform.get_module("knowledge")
        if not mod:
            return jsonify({"error": "Knowledge neuron not available"}), 503
        data = request.get_json(silent=True) or {}
        system_name = data.get("system_name", "")
        tech_stack = data.get("tech_stack", {})
        if not system_name:
            return jsonify({"error": "system_name required"}), 400
        result = mod.catalog.get_compatibility(system_name, tech_stack)
        return jsonify(result)

    # ================================================================
    # UPDATE CALL SYSTEM — Self-maintaining SDK endpoints
    # ================================================================

    @app.route("/api/v1/updates/status", methods=["GET"])
    @require_master_key
    def updates_status():
        """Overall watchdog + pipeline status."""
        mod = platform.get_module("knowledge")
        if not mod:
            return jsonify({"error": "Knowledge neuron not available"}), 503
        return jsonify({
            "watchdog": mod.watchdog.get_status(),
            "pipeline": mod.update_pipeline.get_status(),
        })

    @app.route("/api/v1/updates/providers", methods=["GET"])
    @require_master_key
    def updates_providers():
        """List all monitored providers and their status."""
        mod = platform.get_module("knowledge")
        if not mod:
            return jsonify({"error": "Knowledge neuron not available"}), 503
        return jsonify({"providers": mod.watchdog.list_providers()})

    @app.route("/api/v1/updates/check", methods=["POST"])
    @require_master_key
    def updates_check_all():
        """Trigger drift check for ALL providers now."""
        mod = platform.get_module("knowledge")
        if not mod:
            return jsonify({"error": "Knowledge neuron not available"}), 503
        reports = mod.watchdog.check_all()
        return jsonify({
            "checked": len(reports),
            "reports": {pid: r.to_dict() for pid, r in reports.items()},
        })

    @app.route("/api/v1/updates/check/<provider_id>", methods=["POST"])
    @require_master_key
    def updates_check_provider(provider_id):
        """Check a specific provider for drift."""
        mod = platform.get_module("knowledge")
        if not mod:
            return jsonify({"error": "Knowledge neuron not available"}), 503
        report = mod.watchdog.check_provider(provider_id)
        return jsonify(report.to_dict())

    @app.route("/api/v1/updates/history", methods=["GET"])
    @require_master_key
    def updates_history():
        """Full update history (with optional provider_id filter)."""
        mod = platform.get_module("knowledge")
        if not mod:
            return jsonify({"error": "Knowledge neuron not available"}), 503
        provider_id = request.args.get("provider_id")
        limit = min(int(request.args.get("limit", 50)), 200)
        history = mod.update_pipeline.get_update_history(
            provider_id=provider_id, limit=limit,
        )
        return jsonify({"history": history, "count": len(history)})

    @app.route("/api/v1/updates/pending", methods=["GET"])
    @require_master_key
    def updates_pending():
        """Get updates that are in progress or pending."""
        mod = platform.get_module("knowledge")
        if not mod:
            return jsonify({"error": "Knowledge neuron not available"}), 503
        pending = mod.update_pipeline.get_pending_updates()
        return jsonify({"pending": pending, "count": len(pending)})

    @app.route("/api/v1/updates/<update_id>", methods=["GET"])
    @require_master_key
    def updates_detail(update_id):
        """Get a specific update record with full diff details."""
        mod = platform.get_module("knowledge")
        if not mod:
            return jsonify({"error": "Knowledge neuron not available"}), 503
        record = mod.update_pipeline.get_record(update_id)
        if not record:
            return jsonify({"error": f"Update {update_id} not found"}), 404
        return jsonify(record)

    @app.route("/api/v1/updates/<update_id>/rollback", methods=["POST"])
    @require_master_key
    def updates_rollback(update_id):
        """Rollback a specific update by restoring original file contents."""
        mod = platform.get_module("knowledge")
        if not mod:
            return jsonify({"error": "Knowledge neuron not available"}), 503
        success = mod.update_pipeline.rollback(update_id)
        if success:
            return jsonify({"success": True, "message": f"Update {update_id} rolled back"})
        return jsonify({"error": f"Rollback failed for {update_id}"}), 400

    @app.route("/api/v1/updates/daily-cycle", methods=["POST"])
    @require_master_key
    def updates_daily_cycle():
        """Trigger the daily update cycle (check all + process updates)."""
        mod = platform.get_module("knowledge")
        if not mod:
            return jsonify({"error": "Knowledge neuron not available"}), 503
        results = mod.update_pipeline.run_daily_cycle()
        return jsonify({
            "providers_updated": len(results),
            "results": {pid: r.to_dict() for pid, r in results.items()},
        })

    @app.route("/api/v1/updates/schemas", methods=["GET"])
    @require_master_key
    def updates_schemas():
        """Get current schema baselines for all providers."""
        mod = platform.get_module("knowledge")
        if not mod:
            return jsonify({"error": "Knowledge neuron not available"}), 503
        providers = mod.watchdog.list_providers()
        schemas = {}
        for pid in providers:
            status = mod.watchdog.get_provider_status(pid)
            if status:
                schemas[pid] = {
                    key: snap.to_dict()
                    for key, snap in status.baseline_schemas.items()
                }
        return jsonify({"schemas": schemas})

    @app.route("/api/v1/neurons/<neuron_name>/health", methods=["GET"])
    @require_master_key
    def neuron_health(neuron_name):
        """Get health status of a specific neuron."""
        mod = platform.get_module(neuron_name)
        if not mod:
            return jsonify({"error": f"Neuron '{neuron_name}' not found"}), 404
        health = mod.health_check()
        return jsonify({"neuron": neuron_name, **health})

    # --- Dev Terminal Routes ---
    from .dev_routes import register_dev_routes
    register_dev_routes(app, require_api_key, require_master_key)

    # --- Search & Bundle Routes ---
    from .search_routes import register_search_routes
    register_search_routes(app, require_api_key)

    # --- Credential Network Routes ---
    from .network_routes import register_network_routes
    register_network_routes(app, require_api_key)

    # --- Marketing Website ---
    from .website import register_website_routes
    register_website_routes(app, onboarding, billing_manager)

    # --- Shutdown hook ---
    @app.teardown_appcontext
    def shutdown_neurons(exception=None):
        """Ensure neuron network shuts down cleanly."""
        if platform.is_running:
            platform.stop()

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
