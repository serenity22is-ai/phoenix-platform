"""
Dev Routes — API endpoints for the Developer Terminal.

17 new routes for dev sessions, module management, marketplace, and feedback.
Registered by calling register_dev_routes(app, ...) from create_app().

MYSTES KYRIOS LLC — Confidential.
"""

import json
import logging
import os
import time
from typing import Callable

from flask import Flask, jsonify, request

logger = logging.getLogger(__name__)


def register_dev_routes(
    app: Flask,
    require_api_key: Callable,
    require_master_key: Callable,
) -> None:
    """
    Register all developer terminal API routes.

    Called from create_app() with the auth decorators defined there.

    Args:
        app: Flask app instance (must have app.anastasia_platform set).
        require_api_key: API key validation decorator.
        require_master_key: Master key validation decorator.
    """

    def _get_devterminal():
        """Get the DevTerminal neuron module from the platform."""
        platform = getattr(app, "anastasia_platform", None)
        if not platform or not platform.is_running:
            return None
        return platform.get_module("devterminal")

    # ================================================================
    # DEV SESSIONS
    # ================================================================

    @app.route("/api/v1/dev/sessions", methods=["POST"])
    @require_api_key
    def dev_create_session():
        """
        Create a new dev session.

        Request:
            {"workspace_dir": "/optional/custom/path"}

        Response:
            {"session": {...}, "session_id": "dev_..."}
        """
        devterm = _get_devterminal()
        if not devterm:
            return jsonify({"error": "DevTerminal neuron not available"}), 503

        data = request.get_json(silent=True) or {}
        workspace_dir = data.get("workspace_dir")

        agency_id = getattr(request.agency_config, "agency_id", "unknown")

        try:
            session = devterm.session_manager.create_session(
                agency_id=agency_id,
                workspace_dir=workspace_dir,
            )
        except Exception as e:
            logger.error("Failed to create dev session: %s", e)
            return jsonify({"error": f"Session creation failed: {e}"}), 500

        return jsonify({
            "success": True,
            "session_id": session.session_id,
            "session": session.to_dict(),
        }), 201

    @app.route("/api/v1/dev/sessions", methods=["GET"])
    @require_api_key
    def dev_list_sessions():
        """List active dev sessions for the current agency."""
        devterm = _get_devterminal()
        if not devterm:
            return jsonify({"error": "DevTerminal neuron not available"}), 503

        agency_id = getattr(request.agency_config, "agency_id", "unknown")
        sessions = devterm.session_manager.list_sessions(agency_id=agency_id)

        return jsonify({
            "sessions": [s.to_dict() for s in sessions],
            "count": len(sessions),
        })

    @app.route("/api/v1/dev/sessions/<session_id>", methods=["GET"])
    @require_api_key
    def dev_get_session(session_id):
        """Get details of a specific dev session."""
        devterm = _get_devterminal()
        if not devterm:
            return jsonify({"error": "DevTerminal neuron not available"}), 503

        session = devterm.session_manager.get_session(session_id)
        if not session:
            return jsonify({"error": f"Session '{session_id}' not found"}), 404

        return jsonify({"session": session.to_dict()})

    @app.route("/api/v1/dev/sessions/<session_id>", methods=["DELETE"])
    @require_api_key
    def dev_close_session(session_id):
        """Close a dev session."""
        devterm = _get_devterminal()
        if not devterm:
            return jsonify({"error": "DevTerminal neuron not available"}), 503

        closed = devterm.session_manager.close_session(session_id)
        if not closed:
            return jsonify({"error": f"Session '{session_id}' not found"}), 404

        return jsonify({"success": True, "message": f"Session {session_id} closed"})

    @app.route("/api/v1/dev/sessions/<session_id>/chat", methods=["POST"])
    @require_api_key
    def dev_session_chat(session_id):
        """
        Dev mode AI chat within a session.

        Request:
            {"message": "Help me build a loyalty points module"}

        Response:
            {"response": "...", "session_id": "dev_...", "ai_usage": {...}}
        """
        devterm = _get_devterminal()
        if not devterm:
            return jsonify({"error": "DevTerminal neuron not available"}), 503

        session = devterm.session_manager.get_session(session_id)
        if not session:
            return jsonify({"error": f"Session '{session_id}' not found"}), 404

        data = request.get_json(silent=True) or {}
        message = data.get("message", "").strip()
        if not message:
            return jsonify({"error": "message is required"}), 400

        # Dev mode chat uses AssistAgent with mode="dev"
        # The actual AssistAgent instantiation happens in the calling context
        # Here we track usage and return the response
        try:
            from .assist import AssistAgent
            from .dev_tools import DEV_MODE_SYSTEM_PROMPT

            anthropic_key = app.config.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_API_KEY", "")
            if not anthropic_key:
                return jsonify({"error": "ANTHROPIC_API_KEY not configured"}), 500

            # Get or create client for this agency
            agency_cfg = request.agency_config
            from ..auth import TokenManager
            from ..client import RedboxClient

            token_manager = TokenManager(
                username=getattr(agency_cfg, "cockpit_username", ""),
                password=getattr(agency_cfg, "cockpit_password", ""),
                totp_secret=getattr(agency_cfg, "totp_secret", ""),
                manual_token=getattr(agency_cfg, "session_token", ""),
            )
            client = RedboxClient(
                agency_id=getattr(agency_cfg, "agency_id", ""),
                branch=getattr(agency_cfg, "branch", ""),
                token_provider=token_manager.get_token,
            )

            agent = AssistAgent(
                client=client,
                anthropic_api_key=anthropic_key,
                mode="dev",
                agency_name=getattr(agency_cfg, "agency_name", ""),
                project_root=session.workspace_dir,
                session_id=session_id,
                system_prompt_extra=DEV_MODE_SYSTEM_PROMPT,
            )

            response_text = agent.chat(message)

            # Track AI usage on the session
            session.track_ai_usage(
                agent.total_input_tokens,
                agent.total_output_tokens,
            )

        except Exception as e:
            logger.error("Dev chat error: %s", e)
            return jsonify({"error": f"Chat failed: {e}"}), 500

        return jsonify({
            "response": response_text,
            "session_id": session_id,
            "ai_usage": {
                "input_tokens": session.ai_input_tokens,
                "output_tokens": session.ai_output_tokens,
                "requests": session.ai_requests,
                "estimated_cost_usd": session._estimated_cost(),
            },
        })

    # ================================================================
    # MODULE MANAGEMENT
    # ================================================================

    @app.route("/api/v1/dev/modules/scaffold", methods=["POST"])
    @require_api_key
    def dev_scaffold_module():
        """
        Scaffold a new module in a dev session.

        Request:
            {
                "session_id": "dev_...",
                "name": "loyalty-points",
                "module_type": "extension",
                "description": "Loyalty points tracking"
            }
        """
        devterm = _get_devterminal()
        if not devterm:
            return jsonify({"error": "DevTerminal neuron not available"}), 503

        data = request.get_json(silent=True) or {}
        session_id = data.get("session_id", "")
        name = data.get("name", "").strip()
        module_type = data.get("module_type", "extension")
        description = data.get("description", "")

        if not session_id:
            return jsonify({"error": "session_id is required"}), 400
        if not name:
            return jsonify({"error": "name is required"}), 400

        session = devterm.session_manager.get_session(session_id)
        if not session:
            return jsonify({"error": f"Session '{session_id}' not found"}), 404

        try:
            created = session.scaffold_module(
                name=name,
                module_type=module_type,
                description=description,
            )
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            logger.error("Scaffold error: %s", e)
            return jsonify({"error": f"Scaffold failed: {e}"}), 500

        return jsonify({
            "success": True,
            "module_name": name,
            "module_type": module_type,
            "files_created": {
                os.path.relpath(k, session.workspace_dir): v
                for k, v in created.items()
            },
        }), 201

    @app.route("/api/v1/dev/modules", methods=["GET"])
    @require_api_key
    def dev_list_modules():
        """
        List modules in a dev session workspace.

        Query params: session_id=dev_...
        """
        devterm = _get_devterminal()
        if not devterm:
            return jsonify({"error": "DevTerminal neuron not available"}), 503

        session_id = request.args.get("session_id", "")
        if not session_id:
            return jsonify({"error": "session_id query param required"}), 400

        session = devterm.session_manager.get_session(session_id)
        if not session:
            return jsonify({"error": f"Session '{session_id}' not found"}), 404

        # List directories in workspace that have anastasia-module.json
        modules = []
        workspace = session.workspace_dir
        try:
            for entry in os.listdir(workspace):
                entry_path = os.path.join(workspace, entry)
                manifest_path = os.path.join(entry_path, "anastasia-module.json")
                if os.path.isdir(entry_path) and os.path.isfile(manifest_path):
                    try:
                        from anastasia.devterminal.manifest import load_manifest
                        manifest = load_manifest(manifest_path)
                        modules.append(manifest.to_dict())
                    except Exception:
                        modules.append({"name": entry, "error": "invalid manifest"})
        except OSError:
            pass

        return jsonify({"modules": modules, "count": len(modules)})

    @app.route("/api/v1/dev/modules/<module_name>", methods=["GET"])
    @require_api_key
    def dev_get_module(module_name):
        """Get details of a module in the workspace."""
        devterm = _get_devterminal()
        if not devterm:
            return jsonify({"error": "DevTerminal neuron not available"}), 503

        session_id = request.args.get("session_id", "")
        if not session_id:
            return jsonify({"error": "session_id query param required"}), 400

        session = devterm.session_manager.get_session(session_id)
        if not session:
            return jsonify({"error": f"Session '{session_id}' not found"}), 404

        manifest = session.load_module_manifest(module_name)
        if not manifest:
            return jsonify({"error": f"Module '{module_name}' not found in workspace"}), 404

        return jsonify({"module": manifest.to_dict()})

    @app.route("/api/v1/dev/modules/<module_name>/audit", methods=["POST"])
    @require_api_key
    def dev_audit_module(module_name):
        """
        Run the 3-stage audit pipeline on a workspace module.

        Response: Full AuditResult with pass/fail and per-stage issues.
        """
        devterm = _get_devterminal()
        if not devterm:
            return jsonify({"error": "DevTerminal neuron not available"}), 503

        session_id = (request.get_json(silent=True) or {}).get(
            "session_id", request.args.get("session_id", "")
        )
        if not session_id:
            return jsonify({"error": "session_id is required"}), 400

        session = devterm.session_manager.get_session(session_id)
        if not session:
            return jsonify({"error": f"Session '{session_id}' not found"}), 404

        module_dir = session.get_module_dir(module_name)
        if not module_dir:
            return jsonify({"error": f"Module '{module_name}' not found in workspace"}), 404

        manifest = session.load_module_manifest(module_name)
        result = devterm.audit_pipeline.audit(module_dir, manifest)

        return jsonify({"audit": result.to_dict()})

    # ================================================================
    # MARKETPLACE
    # ================================================================

    @app.route("/api/v1/marketplace", methods=["GET"])
    @require_api_key
    def marketplace_browse():
        """
        Browse the module marketplace.

        Query params: q=search_text, tags=tag1,tag2, type=extension, page=1
        """
        devterm = _get_devterminal()
        if not devterm:
            return jsonify({"error": "DevTerminal neuron not available"}), 503

        query = request.args.get("q")
        tags_str = request.args.get("tags", "")
        tags = [t.strip() for t in tags_str.split(",") if t.strip()] if tags_str else None
        module_type = request.args.get("type")
        page = int(request.args.get("page", 1))

        if query or tags or module_type:
            listings = devterm.marketplace.search(
                query=query, tags=tags, module_type=module_type
            )
        else:
            listings = devterm.marketplace.list_all(page=page)

        return jsonify({
            "modules": [l.to_dict() for l in listings],
            "count": len(listings),
            "total": devterm.marketplace.module_count(),
        })

    @app.route("/api/v1/marketplace/<module_name>", methods=["GET"])
    @require_api_key
    def marketplace_get_module(module_name):
        """Get details of a marketplace module."""
        devterm = _get_devterminal()
        if not devterm:
            return jsonify({"error": "DevTerminal neuron not available"}), 503

        version = request.args.get("version")
        listing = devterm.marketplace.get_module(module_name, version=version)
        if not listing:
            return jsonify({"error": f"Module '{module_name}' not found"}), 404

        stats = devterm.marketplace.get_stats(module_name)
        return jsonify({
            "module": listing.to_dict(),
            "stats": stats.to_dict() if stats else None,
        })

    @app.route("/api/v1/marketplace/publish", methods=["POST"])
    @require_api_key
    def marketplace_publish():
        """
        Publish a module to the marketplace.

        Request:
            {
                "session_id": "dev_...",
                "module_name": "loyalty-points",
                "visibility": "published"
            }
        """
        devterm = _get_devterminal()
        if not devterm:
            return jsonify({"error": "DevTerminal neuron not available"}), 503

        data = request.get_json(silent=True) or {}
        session_id = data.get("session_id", "")
        module_name = data.get("module_name", "")
        visibility = data.get("visibility", "private")

        if not session_id:
            return jsonify({"error": "session_id is required"}), 400
        if not module_name:
            return jsonify({"error": "module_name is required"}), 400

        session = devterm.session_manager.get_session(session_id)
        if not session:
            return jsonify({"error": f"Session '{session_id}' not found"}), 404

        module_dir = session.get_module_dir(module_name)
        if not module_dir:
            return jsonify({"error": f"Module '{module_name}' not found in workspace"}), 404

        manifest = session.load_module_manifest(module_name)
        if not manifest:
            return jsonify({"error": "Cannot load module manifest"}), 400

        # Update visibility
        manifest.visibility = visibility

        # Run audit first
        audit_result = devterm.audit_pipeline.audit(module_dir, manifest)
        if not audit_result.passed:
            return jsonify({
                "success": False,
                "error": "Module did not pass audit",
                "audit": audit_result.to_dict(),
            }), 400

        # Publish
        result = devterm.marketplace.publish(module_dir, manifest, audit_result)
        return jsonify({"publish": result.to_dict()})

    @app.route("/api/v1/marketplace/<module_name>", methods=["DELETE"])
    @require_api_key
    def marketplace_unpublish(module_name):
        """Remove a module from the marketplace."""
        devterm = _get_devterminal()
        if not devterm:
            return jsonify({"error": "DevTerminal neuron not available"}), 503

        version = (request.get_json(silent=True) or {}).get("version")
        removed = devterm.marketplace.unpublish(module_name, version=version)
        if not removed:
            return jsonify({"error": f"Module '{module_name}' not found"}), 404

        return jsonify({"success": True, "message": f"Unpublished {module_name}"})

    @app.route("/api/v1/marketplace/install", methods=["POST"])
    @require_api_key
    def marketplace_install():
        """
        Install a marketplace module into a dev session workspace.

        Request:
            {
                "session_id": "dev_...",
                "module_name": "loyalty-points",
                "version": "1.0.0"
            }
        """
        devterm = _get_devterminal()
        if not devterm:
            return jsonify({"error": "DevTerminal neuron not available"}), 503

        data = request.get_json(silent=True) or {}
        session_id = data.get("session_id", "")
        module_name = data.get("module_name", "")
        version = data.get("version")

        if not session_id:
            return jsonify({"error": "session_id is required"}), 400
        if not module_name:
            return jsonify({"error": "module_name is required"}), 400

        session = devterm.session_manager.get_session(session_id)
        if not session:
            return jsonify({"error": f"Session '{session_id}' not found"}), 404

        result = devterm.marketplace.install(
            module_name=module_name,
            target_dir=session.workspace_dir,
            version=version,
        )

        return jsonify({"install": result.to_dict()})

    # ================================================================
    # FEEDBACK
    # ================================================================

    @app.route("/api/v1/feedback", methods=["POST"])
    @require_api_key
    def submit_feedback():
        """
        Submit developer/customer feedback.

        Request:
            {
                "type": "feature",
                "message": "Would love seat map integration for...",
                "metadata": {"module": "seat-selector"}
            }
        """
        devterm = _get_devterminal()
        if not devterm:
            return jsonify({"error": "DevTerminal neuron not available"}), 503

        data = request.get_json(silent=True) or {}
        feedback_type = data.get("type", "general")
        message = data.get("message", "").strip()
        metadata = data.get("metadata")

        if not message:
            return jsonify({"error": "message is required"}), 400

        agency_id = getattr(request.agency_config, "agency_id", "unknown")

        entry = devterm.submit_feedback(
            agency_id=agency_id,
            feedback_type=feedback_type,
            message=message,
            metadata=metadata,
        )

        return jsonify({"success": True, "feedback": entry}), 201

    @app.route("/api/v1/feedback", methods=["GET"])
    @require_master_key
    def list_feedback():
        """
        List feedback entries (admin only).

        Query params: type=bug, status=new, limit=50
        """
        devterm = _get_devterminal()
        if not devterm:
            return jsonify({"error": "DevTerminal neuron not available"}), 503

        feedback_type = request.args.get("type")
        status = request.args.get("status")
        limit = int(request.args.get("limit", 50))

        entries = devterm.list_feedback(
            feedback_type=feedback_type,
            status=status,
            limit=limit,
        )

        return jsonify({"feedback": entries, "count": len(entries)})
