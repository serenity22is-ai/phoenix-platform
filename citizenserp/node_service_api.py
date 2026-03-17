"""
MYSTES Node Service API (Build #67)

REST API routes for browser extension local node service.
Handles authentication, heartbeat, data ingestion, configuration,
session management, and earnings queries.
"""

import json
import logging
import secrets
from datetime import datetime, timezone
from functools import wraps
from flask import request, jsonify, g

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Extraction / runtime configuration returned to connected nodes
# ---------------------------------------------------------------------------

NODE_CONFIG = {
    "extraction_rules": {
        "search_engines": [
            "google.com",
            "bing.com",
            "yahoo.com",
            "duckduckgo.com",
        ],
        "ad_selectors": [
            "[data-text-ad]",
            ".ads-ad",
            '[class*="sponsor"]',
        ],
        "price_selectors": [
            '[itemprop="price"]',
            ".price",
            ".product-price",
        ],
        "social_platforms": [
            "facebook.com",
            "twitter.com",
            "x.com",
            "reddit.com",
            "linkedin.com",
        ],
    },
    "intervals": {
        "heartbeat_s": 60,
        "batch_upload_s": 30,
        "config_refresh_s": 300,
    },
    "limits": {
        "max_events_per_batch": 500,
        "max_buffer_size": 2000,
        "max_url_length": 2000,
    },
    "version": "1.0.0",
}


# ---------------------------------------------------------------------------
# Auth decorator
# ---------------------------------------------------------------------------

def require_helper_token(f):
    """Validate X-Helper-Token header against HelperProfile.helper_token."""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get("X-Helper-Token")
        if not token:
            return jsonify({"error": "Missing X-Helper-Token header"}), 401

        from models import db, HelperProfile
        profile = HelperProfile.query.filter_by(helper_token=token).first()
        if not profile:
            return jsonify({"error": "Invalid helper token"}), 401
        if not profile.is_active:
            return jsonify({"error": "Helper profile is inactive"}), 403

        g.helper_profile = profile
        g.user_id = profile.user_id
        return f(*args, **kwargs)
    return decorated


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------

def register_node_service_routes(app):
    """Register all node-service REST API routes on *app*."""

    # ------------------------------------------------------------------
    # POST /api/v1/node/auth — Authenticate and register node
    # ------------------------------------------------------------------
    @app.route("/api/v1/node/auth", methods=["POST"])
    def node_auth():
        try:
            from models import db, HelperProfile

            data = request.get_json(silent=True) or {}

            # Accept token from body OR header
            token = data.get("helper_token") or request.headers.get("X-Helper-Token")
            if not token:
                return jsonify({
                    "error": "Missing helper_token in body or X-Helper-Token header"
                }), 401

            profile = HelperProfile.query.filter_by(helper_token=token).first()
            if not profile:
                return jsonify({"error": "Invalid helper token"}), 401
            if not profile.is_active:
                return jsonify({"error": "Helper profile is inactive"}), 403

            # Update last_seen timestamp
            profile.last_seen = datetime.now(timezone.utc)

            # Generate node_id if this profile does not already have one
            if not getattr(profile, "node_id", None):
                profile.node_id = f"NOD-{secrets.token_hex(8)}"

            db.session.commit()

            # Anti-dilution check before registration (Build #107)
            try:
                from node_antidilution import check_onboarding_allowed, classify_node_type
                capabilities = data.get("capabilities", {})
                allowed, reason = check_onboarding_allowed(capabilities, profile.user_id)
                node_type = classify_node_type(capabilities)
                if not allowed:
                    logger.warning("Node onboarding blocked by anti-dilution: %s (user %d)", reason, profile.user_id)
                    return jsonify({
                        "error": "node_cap_reached",
                        "message": reason,
                        "node_type": node_type,
                    }), 429
            except ImportError:
                node_type = "unknown"
            except Exception as exc:
                logger.debug("Anti-dilution check skipped: %s", exc)
                node_type = "unknown"

            # Register with node registry (lazy import)
            newly_registered = False
            try:
                from node_registry import node_registry
                if not node_registry.is_registered(profile.node_id):
                    node_registry.register(profile.node_id, profile.user_id)
                    newly_registered = True
            except ImportError:
                logger.debug("node_registry not available; skipping registration")
            except Exception as exc:
                logger.warning("node_registry.register failed: %s", exc)

            # Emit SSE node event for real-time dashboard
            if newly_registered:
                try:
                    from event_stream import emit_node_event
                    emit_node_event("node_registered", {
                        "node_id": profile.node_id,
                        "user_id": profile.user_id,
                        "country_code": profile.country_code,
                    })
                except Exception:
                    pass

            return jsonify({
                "node_id": profile.node_id,
                "user_id": profile.user_id,
                "config": NODE_CONFIG,
            }), 200

        except Exception as exc:
            logger.exception("node_auth error")
            return jsonify({"error": "Internal server error", "detail": str(exc)}), 500

    # ------------------------------------------------------------------
    # POST /api/v1/node/heartbeat — Periodic heartbeat from node
    # ------------------------------------------------------------------
    @app.route("/api/v1/node/heartbeat", methods=["POST"])
    @require_helper_token
    def node_heartbeat():
        try:
            from models import db

            data = request.get_json(silent=True) or {}
            node_id = data.get("node_id")
            uptime_s = data.get("uptime_s", 0)
            events_buffered = data.get("events_buffered", 0)
            version = data.get("version", "unknown")

            if not node_id:
                return jsonify({"error": "Missing node_id"}), 400

            # Update last_seen on helper profile
            profile = g.helper_profile
            profile.last_seen = datetime.now(timezone.utc)
            db.session.commit()

            # Notify node registry
            try:
                from node_registry import node_registry
                node_registry.heartbeat(node_id)
            except ImportError:
                logger.debug("node_registry not available; skipping heartbeat")
            except Exception as exc:
                logger.warning("node_registry.heartbeat failed: %s", exc)

            # Build #78 — Record node location if provided
            zone_id = None
            location = data.get("location")
            if location and isinstance(location, dict):
                loc_lat = location.get("lat")
                loc_lon = location.get("lon")
                if loc_lat is not None and loc_lon is not None:
                    try:
                        from pricing_zones import zone_engine
                        loc_result = zone_engine.record_node_location(
                            node_id=node_id,
                            user_id=profile.user_id,
                            lat=float(loc_lat),
                            lon=float(loc_lon),
                            accuracy_m=location.get("accuracy_m"),
                            source=location.get("source", "ip_geolocation"),
                        )
                        zone_id = loc_result.get("zone_id")
                    except ImportError:
                        logger.debug("pricing_zones not available")
                    except Exception as exc:
                        logger.warning("zone_engine.record_node_location failed: %s", exc)

            server_time = datetime.now(timezone.utc).isoformat()

            resp = {
                "status": "ok",
                "server_time": server_time,
                "commands": [],
            }
            if zone_id:
                resp["zone_id"] = zone_id

            return jsonify(resp), 200

        except Exception as exc:
            logger.exception("node_heartbeat error")
            return jsonify({"error": "Internal server error", "detail": str(exc)}), 500

    # ------------------------------------------------------------------
    # POST /api/v1/node/data/ingest — Batch event ingestion
    # ------------------------------------------------------------------
    @app.route("/api/v1/node/data/ingest", methods=["POST"])
    @require_helper_token
    def node_data_ingest():
        try:
            data = request.get_json(silent=True) or {}
            node_id = data.get("node_id")
            session_id = data.get("session_id")
            events = data.get("events", [])

            if not node_id:
                return jsonify({"error": "Missing node_id"}), 400
            if not session_id:
                return jsonify({"error": "Missing session_id"}), 400
            if not isinstance(events, list):
                return jsonify({"error": "events must be a list"}), 400
            if len(events) > 500:
                return jsonify({
                    "error": "Too many events",
                    "detail": f"Received {len(events)} events; maximum is 500 per batch",
                }), 413

            user_id = g.user_id

            # Delegate to node data processor (lazy import)
            try:
                from node_data_processor import node_data_processor
                result = node_data_processor.ingest_batch(
                    user_id, node_id, session_id, events
                )
            except ImportError:
                logger.warning("node_data_processor not available")
                result = {
                    "accepted": len(events),
                    "rejected": 0,
                    "warning": "data processor unavailable; events queued in-memory",
                }
            except Exception as exc:
                logger.exception("ingest_batch failed")
                return jsonify({
                    "error": "Ingestion failed",
                    "detail": str(exc),
                }), 500

            # Emit SSE extension event for real-time dashboard
            try:
                from event_stream import emit_extension_event
                emit_extension_event(user_id, "extension_data_ingested", {
                    "node_id": node_id,
                    "accepted": result.get("accepted", 0),
                    "rejected": result.get("rejected", 0),
                })
            except Exception:
                pass

            return jsonify(result), 200

        except Exception as exc:
            logger.exception("node_data_ingest error")
            return jsonify({"error": "Internal server error", "detail": str(exc)}), 500

    # ------------------------------------------------------------------
    # GET /api/v1/node/config — Return extraction configuration
    # ------------------------------------------------------------------
    @app.route("/api/v1/node/config", methods=["GET"])
    @require_helper_token
    def node_config():
        try:
            return jsonify(NODE_CONFIG), 200
        except Exception as exc:
            logger.exception("node_config error")
            return jsonify({"error": "Internal server error", "detail": str(exc)}), 500

    # ------------------------------------------------------------------
    # POST /api/v1/node/session/start — Start a browsing session
    # ------------------------------------------------------------------
    @app.route("/api/v1/node/session/start", methods=["POST"])
    @require_helper_token
    def node_session_start():
        try:
            from models import db

            data = request.get_json(silent=True) or {}
            node_id = data.get("node_id")

            if not node_id:
                return jsonify({"error": "Missing node_id"}), 400

            profile = g.helper_profile
            session_id = f"SES-{secrets.token_hex(12)}"
            started_at = datetime.now(timezone.utc)

            # Optional citizenserp integration
            try:
                from citizenserp_manager import citizenserp_manager
                citizenserp_manager.on_session_start(
                    node_id=node_id,
                    session_id=session_id,
                    user_id=g.user_id,
                )
            except ImportError:
                logger.debug("citizenserp_manager not available; skipping session hook")
            except Exception as exc:
                logger.warning("citizenserp on_session_start failed: %s", exc)

            # Mark helper as online
            profile.is_online = True
            profile.last_seen = started_at
            db.session.commit()

            return jsonify({
                "session_id": session_id,
                "started_at": started_at.isoformat(),
            }), 200

        except Exception as exc:
            logger.exception("node_session_start error")
            return jsonify({"error": "Internal server error", "detail": str(exc)}), 500

    # ------------------------------------------------------------------
    # POST /api/v1/node/session/end — End a browsing session
    # ------------------------------------------------------------------
    @app.route("/api/v1/node/session/end", methods=["POST"])
    @require_helper_token
    def node_session_end():
        try:
            from models import db

            data = request.get_json(silent=True) or {}
            node_id = data.get("node_id")
            session_id = data.get("session_id")

            if not node_id:
                return jsonify({"error": "Missing node_id"}), 400
            if not session_id:
                return jsonify({"error": "Missing session_id"}), 400

            profile = g.helper_profile
            ended_at = datetime.now(timezone.utc)

            # Optional citizenserp integration
            try:
                from citizenserp_manager import citizenserp_manager
                citizenserp_manager.on_session_end(
                    node_id=node_id,
                    session_id=session_id,
                    user_id=g.user_id,
                )
            except ImportError:
                logger.debug("citizenserp_manager not available; skipping session hook")
            except Exception as exc:
                logger.warning("citizenserp on_session_end failed: %s", exc)

            # Mark helper as offline
            profile.is_online = False
            profile.last_seen = ended_at
            db.session.commit()

            return jsonify({
                "ended_at": ended_at.isoformat(),
                "status": "closed",
            }), 200

        except Exception as exc:
            logger.exception("node_session_end error")
            return jsonify({"error": "Internal server error", "detail": str(exc)}), 500

    # ------------------------------------------------------------------
    # GET /api/v1/node/earnings — Earnings / yield summary
    # ------------------------------------------------------------------
    @app.route("/api/v1/node/earnings", methods=["GET"])
    @require_helper_token
    def node_earnings():
        try:
            days_back = request.args.get("days_back", 7, type=int)
            user_id = g.user_id

            earnings_summary = {}
            ingestion_stats = {}

            # Yield dashboard (lazy import)
            try:
                from node_yield_dashboard import node_yield_dashboard
                earnings_summary = node_yield_dashboard.get_yield_summary(
                    user_id, days_back
                )
            except ImportError:
                logger.debug("node_yield_dashboard not available")
                earnings_summary = {
                    "total_earned": 0,
                    "days_back": days_back,
                    "warning": "yield dashboard unavailable",
                }
            except Exception as exc:
                logger.warning("get_yield_summary failed: %s", exc)
                earnings_summary = {
                    "total_earned": 0,
                    "days_back": days_back,
                    "error": str(exc),
                }

            # Ingestion stats (lazy import)
            try:
                from node_data_processor import node_data_processor
                ingestion_stats = node_data_processor.get_ingestion_stats(user_id)
            except ImportError:
                logger.debug("node_data_processor not available for stats")
                ingestion_stats = {"warning": "data processor unavailable"}
            except Exception as exc:
                logger.warning("get_ingestion_stats failed: %s", exc)
                ingestion_stats = {"error": str(exc)}

            return jsonify({
                "earnings": earnings_summary,
                "ingestion": ingestion_stats,
                "queried_at": datetime.now(timezone.utc).isoformat(),
            }), 200

        except Exception as exc:
            logger.exception("node_earnings error")
            return jsonify({"error": "Internal server error", "detail": str(exc)}), 500

    # ------------------------------------------------------------------
    # GET /api/v1/node/tasks/poll — Poll for pending tasks (Build #107)
    # ------------------------------------------------------------------
    @app.route("/api/v1/node/tasks/poll", methods=["GET"])
    @require_helper_token
    def node_tasks_poll():
        try:
            node_id = request.args.get("node_id")
            if not node_id:
                return jsonify({"error": "Missing node_id"}), 400

            profile = g.helper_profile
            market = profile.country_code or "US"
            tasks_to_send = []

            try:
                from citizenserp_tasks import task_dispatcher
                # Find tasks dispatched to this node's user_id that are pending
                for task_id, task in list(task_dispatcher._active_tasks.items()):
                    if task.node_user_id == profile.user_id and task.status == "dispatched":
                        tasks_to_send.append(task.to_node_message())
                        task.status = "executing"
            except ImportError:
                logger.debug("citizenserp_tasks not available")
            except Exception as exc:
                logger.warning("task poll error: %s", exc)

            return jsonify({
                "tasks": tasks_to_send,
                "count": len(tasks_to_send),
            }), 200

        except Exception as exc:
            logger.exception("node_tasks_poll error")
            return jsonify({"error": "Internal server error", "detail": str(exc)}), 500

    # ------------------------------------------------------------------
    # POST /api/v1/node/tasks/result — Submit task result (Build #107)
    # ------------------------------------------------------------------
    @app.route("/api/v1/node/tasks/result", methods=["POST"])
    @require_helper_token
    def node_tasks_result():
        try:
            data = request.get_json(silent=True) or {}
            task_id = data.get("task_id")
            success = data.get("success", False)
            result_data = data.get("data", {})
            error = data.get("error")
            execution_time_ms = data.get("execution_time_ms", 0)

            if not task_id:
                return jsonify({"error": "Missing task_id"}), 400

            profile = g.helper_profile

            try:
                from citizenserp_tasks import task_dispatcher, TaskResult
                result = TaskResult(
                    task_id=task_id,
                    success=success,
                    data=result_data,
                    error=error,
                    execution_time_ms=execution_time_ms,
                    node_user_id=profile.user_id,
                    node_country=profile.country_code,
                    extracted_items=len(result_data.get("results", [])) if isinstance(result_data, dict) else 0,
                )
                task_dispatcher.record_result(task_id, result)
            except ImportError:
                logger.warning("citizenserp_tasks not available — result discarded")
                return jsonify({"warning": "task system unavailable"}), 200
            except Exception as exc:
                logger.warning("task result recording failed: %s", exc)
                return jsonify({"error": "Failed to record result", "detail": str(exc)}), 500

            # Emit SSE event for task completion
            try:
                from event_stream import emit_node_event
                emit_node_event("node_task_completed", {
                    "task_id": task_id,
                    "node_id": request.args.get("node_id", ""),
                    "user_id": profile.user_id,
                    "success": success,
                    "execution_time_ms": execution_time_ms,
                })
            except Exception:
                pass

            return jsonify({"status": "recorded", "task_id": task_id}), 200

        except Exception as exc:
            logger.exception("node_tasks_result error")
            return jsonify({"error": "Internal server error", "detail": str(exc)}), 500

    logger.info("Node service API routes registered")
