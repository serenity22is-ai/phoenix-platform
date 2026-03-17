"""
Search & Bundle API Routes — Unified search and vacation package endpoints.

Endpoints:
    POST /api/v1/search           — Unified cross-vertical search
    POST /api/v1/bundles          — Create a new bundle
    GET  /api/v1/bundles          — List bundles for agency
    GET  /api/v1/bundles/<id>     — Get bundle details
    POST /api/v1/bundles/<id>/items — Add item to bundle
    DELETE /api/v1/bundles/<id>/items/<item_id> — Remove item
    POST /api/v1/bundles/<id>/price — Apply pricing rules
    DELETE /api/v1/bundles/<id>   — Delete bundle

MYSTES KYRIOS LLC — Confidential.
"""

import logging

from flask import Flask, jsonify, request

logger = logging.getLogger(__name__)


def register_search_routes(app: Flask, require_api_key):
    """Register search and bundle API routes."""

    # Lazy-init: dispatcher and builder created on first use.
    _state = {"dispatcher": None, "builder": None}

    def _get_dispatcher():
        if _state["dispatcher"] is None:
            from anastasia.search import SearchDispatcher
            _state["dispatcher"] = SearchDispatcher()
        return _state["dispatcher"]

    def _get_builder():
        if _state["builder"] is None:
            from anastasia.bundles import BundleBuilder
            _state["builder"] = BundleBuilder()
        return _state["builder"]

    # ===================================================================
    # UNIFIED SEARCH
    # ===================================================================

    @app.route("/api/v1/search", methods=["POST"])
    @require_api_key
    def unified_search():
        """
        Unified cross-vertical search.

        POST body:
        {
            "origin": "JFK",
            "destination": "LHR",
            "check_in": "2026-04-01",
            "check_out": "2026-04-07",
            "adults": 2,
            "children": 0,
            "verticals": ["flights", "hotels"],   // optional, default all
            "vertical_params": {                   // optional
                "flights": {"cabin": "ECONOMY"},
                "hotels": {"stars_min": 4}
            }
        }
        """
        from anastasia.search import SearchRequest

        data = request.get_json(force=True, silent=True) or {}
        agency_id = getattr(request, "agency_id", "")

        req = SearchRequest(
            agency_id=agency_id,
            origin=data.get("origin", ""),
            destination=data.get("destination", ""),
            check_in=data.get("check_in", ""),
            check_out=data.get("check_out", data.get("return_date", "")),
            adults=data.get("adults", 1),
            children=data.get("children", 0),
            infants=data.get("infants", 0),
            verticals=data.get("verticals", []),
            vertical_params=data.get("vertical_params", {}),
            user_tier=data.get("user_tier", "consumer"),
            timeout_seconds=data.get("timeout", 30),
        )

        dispatcher = _get_dispatcher()
        response = dispatcher.search(req)

        return jsonify(response.to_dict())

    # ===================================================================
    # BUNDLES
    # ===================================================================

    @app.route("/api/v1/bundles", methods=["POST"])
    @require_api_key
    def create_bundle():
        """Create a new empty bundle."""
        from anastasia.bundles import PricingRules

        data = request.get_json(force=True, silent=True) or {}
        agency_id = getattr(request, "agency_id", "")

        rules = None
        if "pricing_rules" in data:
            pr = data["pricing_rules"]
            rules = PricingRules(
                markup_pct_by_vertical=pr.get("markup_pct_by_vertical", {}),
                flat_markup_usd=pr.get("flat_markup_usd"),
                bundle_discount_pct=pr.get("bundle_discount_pct", 0.0),
                bundle_discount_min_items=pr.get("bundle_discount_min_items", 3),
                min_markup_usd=pr.get("min_markup_usd", 3.0),
                max_markup_usd=pr.get("max_markup_usd", 50.0),
                tier=pr.get("tier", "consumer"),
            )

        builder = _get_builder()
        bundle = builder.create_bundle(
            agency_id=agency_id,
            pricing_rules=rules,
        )

        return jsonify(bundle.to_dict()), 201

    @app.route("/api/v1/bundles", methods=["GET"])
    @require_api_key
    def list_bundles():
        """List bundles for the authenticated agency."""
        agency_id = getattr(request, "agency_id", "")
        builder = _get_builder()
        bundles = builder.list_bundles(agency_id=agency_id)
        return jsonify({
            "bundles": [b.to_dict() for b in bundles],
            "count": len(bundles),
        })

    @app.route("/api/v1/bundles/<bundle_id>", methods=["GET"])
    @require_api_key
    def get_bundle(bundle_id):
        """Get bundle details."""
        builder = _get_builder()
        bundle = builder.get_bundle(bundle_id)
        if not bundle:
            return jsonify({"error": "Bundle not found"}), 404
        return jsonify(bundle.to_dict())

    @app.route("/api/v1/bundles/<bundle_id>/items", methods=["POST"])
    @require_api_key
    def add_bundle_item(bundle_id):
        """
        Add an item to a bundle.

        POST body:
        {
            "vertical": "flights",
            "provider": "picasso",
            "description": "JFK→LHR roundtrip",
            "base_price_usd": 450.00,
            "retail_price_usd": 650.00,
            "details": {
                "airline": "BA",
                "departure": "2026-04-01T10:00",
                "arrival": "2026-04-01T22:00"
            },
            "search_result_id": "abc123"
        }
        """
        from anastasia.bundles import BundleItem

        data = request.get_json(force=True, silent=True) or {}

        item = BundleItem(
            vertical=data.get("vertical", ""),
            provider=data.get("provider", ""),
            description=data.get("description", ""),
            base_price_usd=float(data.get("base_price_usd", 0)),
            retail_price_usd=float(data.get("retail_price_usd", 0)),
            details=data.get("details", {}),
            search_result_id=data.get("search_result_id"),
        )

        builder = _get_builder()
        bundle = builder.add_item(bundle_id, item)
        if not bundle:
            return jsonify({"error": "Bundle not found"}), 404

        return jsonify(bundle.to_dict())

    @app.route("/api/v1/bundles/<bundle_id>/items/<item_id>", methods=["DELETE"])
    @require_api_key
    def remove_bundle_item(bundle_id, item_id):
        """Remove an item from a bundle."""
        builder = _get_builder()
        bundle = builder.remove_item(bundle_id, item_id)
        if not bundle:
            return jsonify({"error": "Bundle not found"}), 404
        return jsonify(bundle.to_dict())

    @app.route("/api/v1/bundles/<bundle_id>/price", methods=["POST"])
    @require_api_key
    def price_bundle(bundle_id):
        """
        Apply pricing rules to a bundle.

        POST body (option A — explicit rules):
        {
            "pricing_rules": {
                "markup_pct_by_vertical": {"flights": 0.25, "hotels": 0.20},
                "bundle_discount_pct": 0.05
            }
        }

        POST body (option B — tier-based):
        {
            "tier": "b2b"
        }
        """
        data = request.get_json(force=True, silent=True) or {}
        builder = _get_builder()

        tier = data.get("tier")
        if tier:
            bundle = builder.apply_tier_pricing(bundle_id, tier)
        else:
            from anastasia.bundles import PricingRules
            pr_data = data.get("pricing_rules", {})
            rules = PricingRules(
                markup_pct_by_vertical=pr_data.get("markup_pct_by_vertical", {}),
                flat_markup_usd=pr_data.get("flat_markup_usd"),
                bundle_discount_pct=pr_data.get("bundle_discount_pct", 0.0),
                bundle_discount_min_items=pr_data.get("bundle_discount_min_items", 3),
                min_markup_usd=pr_data.get("min_markup_usd", 3.0),
                max_markup_usd=pr_data.get("max_markup_usd", 50.0),
                tier=pr_data.get("tier", "consumer"),
            )
            bundle = builder.apply_pricing(bundle_id, rules)

        if not bundle:
            return jsonify({"error": "Bundle not found"}), 404

        return jsonify(bundle.to_dict())

    @app.route("/api/v1/bundles/<bundle_id>", methods=["DELETE"])
    @require_api_key
    def delete_bundle(bundle_id):
        """Delete a bundle."""
        builder = _get_builder()
        if builder.delete_bundle(bundle_id):
            return jsonify({"deleted": True, "bundle_id": bundle_id})
        return jsonify({"error": "Bundle not found"}), 404
