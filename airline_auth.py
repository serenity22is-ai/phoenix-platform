"""
MYSTES Airline Intelligence API Authentication Middleware

Authenticates airline intelligence API requests via API key.
Separate from commercial_auth.py — airlines are a different customer type.

Usage:
    from airline_auth import require_airline_api_key, get_airline_client

    @app.route("/api/v1/intel/pricing/<route>")
    @require_airline_api_key(scope="pricing")
    def get_route_pricing(route):
        client = get_airline_client()
        ...

Header format:
    Authorization: Bearer air_<key>
    — or —
    X-API-Key: air_<key>
"""

import functools
import json
import logging
from datetime import datetime

from flask import request, g, jsonify

logger = logging.getLogger(__name__)


def _extract_api_key():
    """Extract airline API key from request headers."""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:].strip()
    return request.headers.get("X-API-Key", "").strip() or None


def get_airline_client():
    """Get the authenticated airline client from request context."""
    return getattr(g, "airline_client", None)


def get_airline_scopes():
    """Get scopes of the authenticated airline API key."""
    return getattr(g, "airline_scopes", [])


def require_airline_api_key(scope=None):
    """
    Decorator requiring valid airline intelligence API key.

    Scopes: pricing, ancillary, demand, alerts, reports
    """
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            key_string = _extract_api_key()
            if not key_string:
                return jsonify({
                    "error": "API key required",
                    "hint": "Set Authorization: Bearer air_<key>",
                }), 401

            from airline_intelligence import airline_intel_manager
            result = airline_intel_manager.verify_api_key(key_string)

            if result is None:
                return jsonify({"error": "Invalid or expired API key"}), 401

            client, api_key, scopes = result

            if scope and scope not in scopes:
                return jsonify({
                    "error": f"Insufficient scope: '{scope}' required",
                    "your_scopes": scopes,
                }), 403

            if not client.is_active:
                return jsonify({"error": "Account suspended"}), 403

            g.airline_client = client
            g.airline_api_key = api_key
            g.airline_scopes = scopes

            return fn(*args, **kwargs)
        return wrapper
    return decorator


def register_airline_routes(app):
    """Register airline intelligence API endpoints on the Flask app."""
    from flask_login import login_required, current_user

    # ------------------------------------------------------------------
    # Admin Routes — Client Management (session auth)
    # ------------------------------------------------------------------

    @app.route("/api/airline/clients", methods=["POST"])
    @login_required
    def create_airline_client():
        """Create new airline intelligence client (admin only)."""
        if not current_user.is_admin:
            return jsonify({"error": "Admin only"}), 403

        data = request.get_json()
        if not data:
            return jsonify({"error": "JSON body required"}), 400

        required = ["iata_code", "airline_name", "contact_email"]
        missing = [f for f in required if not data.get(f)]
        if missing:
            return jsonify({"error": f"Missing required fields: {', '.join(missing)}"}), 400

        from airline_intelligence import airline_intel_manager
        result = airline_intel_manager.create_client(
            iata_code=data["iata_code"],
            airline_name=data["airline_name"],
            contact_email=data["contact_email"],
            contact_name=data.get("contact_name"),
            subscription_tier=data.get("subscription_tier", "basic"),
            routes_subscribed=data.get("routes_subscribed"),
            markets_subscribed=data.get("markets_subscribed"),
            competitor_airlines=data.get("competitor_airlines"),
            contract_months=data.get("contract_months", 12),
        )

        if "error" in result:
            return jsonify(result), 400
        return jsonify(result), 201

    @app.route("/api/airline/clients", methods=["GET"])
    @login_required
    def list_airline_clients():
        """List airline clients (admin only)."""
        if not current_user.is_admin:
            return jsonify({"error": "Admin only"}), 403

        from airline_intelligence import airline_intel_manager
        clients = airline_intel_manager.list_clients()
        return jsonify({"clients": clients})

    @app.route("/api/airline/clients/<client_id>", methods=["GET"])
    @login_required
    def get_airline_client_detail(client_id):
        """Get airline client details (admin only)."""
        if not current_user.is_admin:
            return jsonify({"error": "Admin only"}), 403

        from airline_intelligence import airline_intel_manager
        client = airline_intel_manager.get_client(client_id)
        if not client:
            return jsonify({"error": "Not found"}), 404
        return jsonify(client.to_dict())

    @app.route("/api/airline/clients/<client_id>/suspend", methods=["POST"])
    @login_required
    def suspend_airline_client(client_id):
        """Suspend an airline client (admin only)."""
        if not current_user.is_admin:
            return jsonify({"error": "Admin only"}), 403

        data = request.get_json() or {}
        from airline_intelligence import airline_intel_manager
        result = airline_intel_manager.suspend_client(client_id, reason=data.get("reason"))
        return jsonify(result)

    @app.route("/api/airline/clients/<client_id>/reactivate", methods=["POST"])
    @login_required
    def reactivate_airline_client(client_id):
        """Reactivate a suspended airline client (admin only)."""
        if not current_user.is_admin:
            return jsonify({"error": "Admin only"}), 403

        from airline_intelligence import airline_intel_manager
        result = airline_intel_manager.reactivate_client(client_id)
        return jsonify(result)

    @app.route("/api/airline/clients/<client_id>/keys", methods=["POST"])
    @login_required
    def create_airline_api_key(client_id):
        """Generate API key for airline client (admin only)."""
        if not current_user.is_admin:
            return jsonify({"error": "Admin only"}), 403

        data = request.get_json() or {}
        from airline_intelligence import airline_intel_manager
        result = airline_intel_manager.create_api_key(
            client_id=client_id,
            label=data.get("label", "Production"),
            scopes=data.get("scopes"),
            expires_days=data.get("expires_days"),
        )

        if "error" in result:
            return jsonify(result), 400
        return jsonify(result), 201

    @app.route("/api/airline/clients/<client_id>/keys/<int:key_id>", methods=["DELETE"])
    @login_required
    def revoke_airline_api_key_route(client_id, key_id):
        """Revoke an airline API key (admin only)."""
        if not current_user.is_admin:
            return jsonify({"error": "Admin only"}), 403

        from airline_intelligence import airline_intel_manager
        result = airline_intel_manager.revoke_api_key(key_id, client_id)
        return jsonify(result)

    # ------------------------------------------------------------------
    # Intelligence API — Authenticated via API Key
    # ------------------------------------------------------------------

    @app.route("/api/v1/intel/pricing/<route>", methods=["GET"])
    @require_airline_api_key(scope="pricing")
    def intel_route_pricing(route):
        """
        Competitive pricing analysis for a route.

        GET /api/v1/intel/pricing/JFK-LHR?market=US&days=30
        """
        client = get_airline_client()
        market = request.args.get("market", "US")
        days = min(int(request.args.get("days", 30)), 365)

        from airline_intelligence import airline_intel_manager
        result = airline_intel_manager.get_competitor_analysis(
            client_id=client.client_id,
            route=route,
            market=market,
            days_back=days,
        )
        if "error" in result:
            return jsonify(result), 400
        return jsonify(result)

    @app.route("/api/v1/intel/pricing/<route>/history", methods=["GET"])
    @require_airline_api_key(scope="pricing")
    def intel_route_price_history(route):
        """
        Historical price trend for a route.

        GET /api/v1/intel/pricing/JFK-LHR/history?market=US&days=90
        """
        client = get_airline_client()
        market = request.args.get("market", "US")
        days = min(int(request.args.get("days", 90)), 365)

        from airline_intelligence import airline_intel_manager
        result = airline_intel_manager.get_route_pricing_history(
            client_id=client.client_id,
            route=route,
            market=market,
            days_back=days,
        )
        if "error" in result:
            return jsonify(result), 400
        return jsonify(result)

    @app.route("/api/v1/intel/pricing/<route>/summary", methods=["GET"])
    @require_airline_api_key(scope="pricing")
    def intel_route_summary(route):
        """
        Multi-market route summary with cheapest/most expensive markets.

        GET /api/v1/intel/pricing/JFK-LHR/summary?days=30
        """
        client = get_airline_client()
        days = min(int(request.args.get("days", 30)), 365)

        from airline_intelligence import airline_intel_manager
        result = airline_intel_manager.get_route_summary(
            client_id=client.client_id,
            route=route,
            days_back=days,
        )
        if "error" in result:
            return jsonify(result), 400
        return jsonify(result)

    @app.route("/api/v1/intel/ancillary/<route>", methods=["GET"])
    @require_airline_api_key(scope="ancillary")
    def intel_route_ancillary(route):
        """
        Ancillary pricing (bags, seats) for a route.

        GET /api/v1/intel/ancillary/JFK-LHR?market=US&days=30
        """
        client = get_airline_client()
        market = request.args.get("market", "US")
        days = min(int(request.args.get("days", 30)), 365)

        from airline_intelligence import airline_intel_manager
        result = airline_intel_manager.get_ancillary_analysis(
            client_id=client.client_id,
            route=route,
            market=market,
            days_back=days,
        )
        if "error" in result:
            return jsonify(result), 400
        return jsonify(result)

    @app.route("/api/v1/intel/demand/<route>", methods=["GET"])
    @require_airline_api_key(scope="demand")
    def intel_route_demand(route):
        """
        Search demand signals for a route.

        GET /api/v1/intel/demand/JFK-LHR?days=30
        """
        client = get_airline_client()
        days = min(int(request.args.get("days", 30)), 365)

        from airline_intelligence import airline_intel_manager
        result = airline_intel_manager.get_demand_analysis(
            client_id=client.client_id,
            route=route,
            days_back=days,
        )
        if "error" in result:
            return jsonify(result), 400
        return jsonify(result)

    @app.route("/api/v1/intel/competitors/<airline_iata>", methods=["GET"])
    @require_airline_api_key(scope="pricing")
    def intel_competitor_routes(airline_iata):
        """
        All routes where a specific competitor operates.

        GET /api/v1/intel/competitors/AA?market=US&days=30
        """
        client = get_airline_client()
        market = request.args.get("market", "US")
        days = min(int(request.args.get("days", 30)), 365)

        from models import db, PriceHistory
        from datetime import timedelta

        cutoff = datetime.utcnow() - timedelta(days=days)

        routes = db.session.query(
            PriceHistory.origin,
            PriceHistory.destination,
            db.func.count(PriceHistory.id).label("sample_count"),
            db.func.avg(PriceHistory.price_usd).label("avg_price"),
            db.func.min(PriceHistory.price_usd).label("min_price"),
        ).filter(
            PriceHistory.airline.contains(airline_iata.upper()),
            PriceHistory.market == market.upper(),
            PriceHistory.recorded_at >= cutoff,
        ).group_by(
            PriceHistory.origin,
            PriceHistory.destination,
        ).all()

        route_list = sorted([
            {
                "route": f"{r.origin}-{r.destination}",
                "sample_count": r.sample_count,
                "avg_price_usd": round(r.avg_price, 2),
                "min_price_usd": round(r.min_price, 2),
            }
            for r in routes
        ], key=lambda x: x["avg_price_usd"])

        return jsonify({
            "competitor_iata": airline_iata.upper(),
            "market": market.upper(),
            "days_analyzed": days,
            "routes": route_list,
            "total_routes": len(route_list),
        })

    # ------------------------------------------------------------------
    # Alerts (API key auth)
    # ------------------------------------------------------------------

    @app.route("/api/v1/intel/alerts", methods=["POST"])
    @require_airline_api_key(scope="alerts")
    def intel_create_alert():
        """
        Create a competitive alert.

        POST /api/v1/intel/alerts
        {"alert_type": "price_drop", "route_pattern": "JFK-*",
         "competitor_iata": "AA", "price_change_pct": 5.0}
        """
        client = get_airline_client()
        data = request.get_json()
        if not data:
            return jsonify({"error": "JSON body required"}), 400

        if not data.get("alert_type"):
            return jsonify({"error": "alert_type required"}), 400

        from airline_intelligence import airline_intel_manager
        result = airline_intel_manager.create_alert(
            client_id=client.client_id,
            alert_type=data["alert_type"],
            route_pattern=data.get("route_pattern"),
            competitor_iata=data.get("competitor_iata"),
            market=data.get("market"),
            price_change_pct=data.get("price_change_pct"),
            price_change_usd=data.get("price_change_usd"),
            demand_change_pct=data.get("demand_change_pct"),
            notify_email=data.get("notify_email", True),
            notify_webhook=data.get("notify_webhook"),
        )
        if "error" in result:
            return jsonify(result), 400
        return jsonify(result), 201

    @app.route("/api/v1/intel/alerts", methods=["GET"])
    @require_airline_api_key(scope="alerts")
    def intel_list_alerts():
        """List active alerts for the authenticated client."""
        client = get_airline_client()
        from airline_intelligence import airline_intel_manager
        alerts = airline_intel_manager.list_alerts(client.client_id)
        if isinstance(alerts, dict) and "error" in alerts:
            return jsonify(alerts), 400
        return jsonify({"alerts": alerts, "total": len(alerts)})

    @app.route("/api/v1/intel/alerts/<alert_id>", methods=["DELETE"])
    @require_airline_api_key(scope="alerts")
    def intel_delete_alert(alert_id):
        """Deactivate an alert."""
        client = get_airline_client()
        from airline_intelligence import airline_intel_manager
        result = airline_intel_manager.delete_alert(client.client_id, alert_id)
        if "error" in result:
            return jsonify(result), 404
        return jsonify(result)

    # ------------------------------------------------------------------
    # Reports (API key auth)
    # ------------------------------------------------------------------

    @app.route("/api/v1/intel/reports", methods=["POST"])
    @require_airline_api_key(scope="reports")
    def intel_generate_report():
        """
        Request a pricing report.

        POST /api/v1/intel/reports
        {"report_type": "weekly", "routes": ["JFK-LHR", "LAX-NRT"]}
        """
        client = get_airline_client()
        data = request.get_json() or {}

        from airline_intelligence import airline_intel_manager
        result = airline_intel_manager.generate_pricing_report(
            client_id=client.client_id,
            report_type=data.get("report_type", "weekly"),
            period_days=data.get("period_days", 7),
            routes=data.get("routes"),
        )
        if "error" in result:
            return jsonify(result), 400
        return jsonify(result), 201

    @app.route("/api/v1/intel/reports", methods=["GET"])
    @require_airline_api_key(scope="reports")
    def intel_list_reports():
        """List all reports for client."""
        client = get_airline_client()
        from airline_intelligence import airline_intel_manager
        reports = airline_intel_manager.list_reports(client.client_id)
        if isinstance(reports, dict) and "error" in reports:
            return jsonify(reports), 400
        return jsonify({"reports": reports, "total": len(reports)})

    @app.route("/api/v1/intel/reports/latest", methods=["GET"])
    @require_airline_api_key(scope="reports")
    def intel_latest_report():
        """Get most recent completed report."""
        client = get_airline_client()
        from models import AirlineReport

        report = AirlineReport.query.filter_by(
            client_id=client.id, status="completed"
        ).order_by(AirlineReport.generated_at.desc()).first()

        if not report:
            return jsonify({"error": "No reports available"}), 404

        result = report.to_dict()
        if report.report_data:
            result["data"] = json.loads(report.report_data)
        return jsonify(result)

    @app.route("/api/v1/intel/reports/<report_id>", methods=["GET"])
    @require_airline_api_key(scope="reports")
    def intel_get_report(report_id):
        """Get specific report by ID."""
        client = get_airline_client()
        from airline_intelligence import airline_intel_manager
        result = airline_intel_manager.get_report(client.client_id, report_id)
        if "error" in result:
            return jsonify(result), 404
        return jsonify(result)

    # ------------------------------------------------------------------
    # Account Info (API key auth)
    # ------------------------------------------------------------------

    @app.route("/api/v1/intel/account", methods=["GET"])
    @require_airline_api_key()
    def intel_my_account():
        """Get account info for the authenticated airline client."""
        client = get_airline_client()
        from airline_intelligence import AIRLINE_TIERS

        tier_config = AIRLINE_TIERS.get(client.subscription_tier, {})
        return jsonify({
            "client_id": client.client_id,
            "iata_code": client.iata_code,
            "airline_name": client.airline_name,
            "subscription_tier": client.subscription_tier,
            "monthly_fee_usd": client.monthly_fee_usd,
            "api_calls_this_month": client.api_calls_this_month or 0,
            "api_rate_limit": tier_config.get("api_rate_limit"),
            "contract_end": client.contract_end.isoformat() if client.contract_end else None,
            "reports_generated": client.reports_generated or 0,
        })

    # ------------------------------------------------------------------
    # CitizenSERP Node Operator Routes (session auth)
    # ------------------------------------------------------------------

    @app.route("/api/v1/node/stats", methods=["GET"])
    @login_required
    def get_node_stats():
        """Node operator's uptime and earnings dashboard."""
        if not current_user.is_helper_node:
            return jsonify({"error": "Not a registered node operator"}), 403

        days = min(int(request.args.get("days", 30)), 365)
        from citizenserp_payouts import citizenserp_manager
        result = citizenserp_manager.get_node_uptime(current_user.id, days_back=days)
        return jsonify(result)

    @app.route("/api/v1/node/payouts", methods=["GET"])
    @login_required
    def get_node_payouts():
        """Node operator's payout history."""
        if not current_user.is_helper_node:
            return jsonify({"error": "Not a registered node operator"}), 403

        limit = min(int(request.args.get("limit", 30)), 100)
        from citizenserp_payouts import citizenserp_manager
        result = citizenserp_manager.get_payout_history(current_user.id, limit=limit)
        return jsonify({"payouts": result, "total": len(result)})

    @app.route("/api/v1/network/stats", methods=["GET"])
    def get_network_stats():
        """Public network statistics (no auth required)."""
        from citizenserp_payouts import citizenserp_manager
        result = citizenserp_manager.get_network_stats()
        return jsonify(result)
