"""
Network Routes — Credential Network API endpoints for the APAi marketplace.

Endpoints:
    GET    /api/v1/network/directory          — Browse visible providers
    GET    /api/v1/network/profile            — Get own profile
    PUT    /api/v1/network/profile            — Update own profile
    GET    /api/v1/network/profile/<id>       — View another provider's profile

    GET    /api/v1/network/terms              — List own terms cards
    POST   /api/v1/network/terms              — Create a terms card
    PUT    /api/v1/network/terms/<id>         — Update a terms card
    DELETE /api/v1/network/terms/<id>         — Delete a terms card

    GET    /api/v1/network/connections        — List connections (active/pending)
    POST   /api/v1/network/connections        — Request connection to a provider
    POST   /api/v1/network/connections/<id>/accept  — Accept a connection request
    POST   /api/v1/network/connections/<id>/reject  — Reject a connection request
    POST   /api/v1/network/connections/<id>/pause   — Pause an active connection
    POST   /api/v1/network/connections/<id>/resume  — Resume a paused connection
    DELETE /api/v1/network/connections/<id>   — Disconnect

    GET    /api/v1/network/audit              — Transaction audit trail
    GET    /api/v1/network/stats              — Network stats for own subscriber

MYSTES KYRIOS LLC — Confidential.
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Callable

from flask import Flask, jsonify, request

from .tier_gating import (
    check_feature,
    check_vault_limit,
    get_locked_features,
    get_tier_summary,
    has_feature,
)

logger = logging.getLogger(__name__)


def register_network_routes(app: Flask, require_api_key: Callable) -> None:
    """
    Register credential network API routes.

    Called from create_app() in api.py.

    Args:
        app: Flask app instance.
        require_api_key: API key validation decorator (attaches request.api_key_hash).
    """

    def _get_db():
        """Lazy import to avoid circular deps."""
        from .db_models import db
        return db

    def _get_models():
        """Lazy import all network models."""
        from .db_models import (
            Agency,
            NetworkConnection,
            ProviderProfile,
            RoutingEvent,
            RoutingTermsCard,
        )
        return {
            "Agency": Agency,
            "ProviderProfile": ProviderProfile,
            "RoutingTermsCard": RoutingTermsCard,
            "NetworkConnection": NetworkConnection,
            "RoutingEvent": RoutingEvent,
        }

    def _get_tier(key_hash):
        """Look up APAi tier for the subscriber."""
        m = _get_models()
        agency = m["Agency"].query.filter_by(key_hash=key_hash).first()
        return (agency.tier or "pro").lower() if agency else "pro"

    def _tier_gate(key_hash, feature):
        """Check tier access. Returns (allowed, error_response_or_None)."""
        tier = _get_tier(key_hash)
        allowed, msg = check_feature(tier, feature)
        if not allowed:
            return False, jsonify({"error": msg, "upgrade_required": True}), 403
        return True, None, None

    def _ensure_profile(key_hash):
        """Get or auto-create a provider profile for the subscriber."""
        m = _get_models()
        db = _get_db()
        profile = m["ProviderProfile"].query.filter_by(key_hash=key_hash).first()
        if not profile:
            agency = m["Agency"].query.filter_by(key_hash=key_hash).first()
            profile = m["ProviderProfile"](
                key_hash=key_hash,
                display_name=agency.company_name or f"Provider {key_hash[:8]}",
                contact_email=agency.contact_email,
                apai_tier=agency.tier or "pro",
            )
            db.session.add(profile)
            db.session.commit()
        return profile

    # ===================================================================
    # DIRECTORY — Browse providers
    # ===================================================================

    @app.route("/api/v1/network/directory", methods=["GET"])
    @require_api_key
    def network_directory():
        """
        Browse visible providers on the credential network.

        Query params:
            tier       — Filter by APAi tier (pro/enterprise/scale)
            market     — Filter by market coverage (e.g. "US", "DE")
            system     — Filter by provider system (amadeus/duffel/etc.)
            type       — Filter by credential type (gds/ndc/etc.)
            search     — Free-text search on display_name/description
            page       — Pagination (default 1)
            per_page   — Results per page (default 20, max 100)
        """
        m = _get_models()
        query = m["ProviderProfile"].query.filter_by(
            is_visible=True,
            is_accepting_connections=True,
        )

        # Filters
        tier = request.args.get("tier")
        if tier:
            query = query.filter(m["ProviderProfile"].apai_tier == tier)

        search_term = request.args.get("search")
        if search_term:
            like = f"%{search_term}%"
            query = query.filter(
                m["ProviderProfile"].display_name.ilike(like)
                | m["ProviderProfile"].description.ilike(like)
            )

        # Order by reputation desc
        query = query.order_by(m["ProviderProfile"].reputation_score.desc())

        # Pagination
        page = max(1, request.args.get("page", 1, type=int))
        per_page = min(100, max(1, request.args.get("per_page", 20, type=int)))
        paginated = query.paginate(page=page, per_page=per_page, error_out=False)

        # If market/system/type filters requested, post-filter on terms cards
        market = request.args.get("market")
        system = request.args.get("system")
        cred_type = request.args.get("type")

        results = []
        for profile in paginated.items:
            if market or system or cred_type:
                cards = m["RoutingTermsCard"].query.filter_by(
                    profile_id=profile.id, is_published=True
                ).all()
                match = False
                for card in cards:
                    if market and market not in (card.markets_included_json or []):
                        continue
                    if system and card.provider_system != system:
                        continue
                    if cred_type and card.credential_type != cred_type:
                        continue
                    match = True
                    break
                if not match:
                    continue

            results.append(profile.to_dict(include_stats=True))

        return jsonify({
            "providers": results,
            "page": page,
            "per_page": per_page,
            "total": paginated.total,
            "pages": paginated.pages,
        })

    # ===================================================================
    # PROFILE — Own profile CRUD
    # ===================================================================

    @app.route("/api/v1/network/profile", methods=["GET"])
    @require_api_key
    def network_get_own_profile():
        """Get the caller's own provider profile (auto-creates if missing)."""
        key_hash = request.api_key_hash
        profile = _ensure_profile(key_hash)

        m = _get_models()
        terms = m["RoutingTermsCard"].query.filter_by(
            profile_id=profile.id
        ).all()

        result = profile.to_dict(include_stats=True)
        result["terms_cards"] = [t.to_dict() for t in terms]
        return jsonify(result)

    @app.route("/api/v1/network/profile", methods=["PUT"])
    @require_api_key
    def network_update_profile():
        """
        Update own provider profile.

        Body (all optional):
            display_name, description, logo_url, website_url,
            contact_email, credentials_summary, is_visible,
            is_accepting_connections
        """
        key_hash = request.api_key_hash
        profile = _ensure_profile(key_hash)
        db = _get_db()

        data = request.get_json(silent=True) or {}

        updatable = [
            "display_name", "description", "logo_url", "website_url",
            "contact_email", "is_visible", "is_accepting_connections",
        ]
        for field in updatable:
            if field in data:
                setattr(profile, field, data[field])

        if "credentials_summary" in data:
            profile.credentials_summary_json = data["credentials_summary"]

        db.session.commit()
        return jsonify({"success": True, "profile": profile.to_dict()})

    @app.route("/api/v1/network/profile/<int:profile_id>", methods=["GET"])
    @require_api_key
    def network_view_profile(profile_id):
        """View another provider's profile (must be visible)."""
        m = _get_models()
        db = _get_db()
        profile = db.session.get(m["ProviderProfile"], profile_id)
        if not profile or not profile.is_visible:
            return jsonify({"error": "Profile not found"}), 404

        # Include published terms cards
        terms = m["RoutingTermsCard"].query.filter_by(
            profile_id=profile.id, is_published=True
        ).all()

        result = profile.to_dict(include_stats=True)
        result["terms_cards"] = [t.to_dict() for t in terms]
        return jsonify(result)

    # ===================================================================
    # TERMS CARDS — CRUD for routing terms
    # ===================================================================

    @app.route("/api/v1/network/terms", methods=["GET"])
    @require_api_key
    def network_list_terms():
        """List all terms cards for the caller's profile."""
        key_hash = request.api_key_hash
        profile = _ensure_profile(key_hash)
        m = _get_models()

        cards = m["RoutingTermsCard"].query.filter_by(
            profile_id=profile.id
        ).all()
        return jsonify({"terms_cards": [c.to_dict() for c in cards]})

    @app.route("/api/v1/network/terms", methods=["POST"])
    @require_api_key
    def network_create_terms():
        """
        Create a new terms card for a credential listing.

        Required: credential_label, credential_type, provider_system
        Optional: all 5 sections (pricing, coverage, limits, relationship, arbitrage)
        """
        key_hash = request.api_key_hash
        profile = _ensure_profile(key_hash)
        db = _get_db()
        m = _get_models()

        data = request.get_json(silent=True) or {}

        # Validate required fields
        for field in ("credential_label", "credential_type", "provider_system"):
            if not data.get(field):
                return jsonify({"error": f"Missing required field: {field}"}), 400

        # Tier gate: check vault limit (3 Pro / 10 Enterprise / unlimited Scale)
        tier = _get_tier(key_hash)
        current_cards = m["RoutingTermsCard"].query.filter_by(
            profile_id=profile.id
        ).count()
        allowed, max_allowed = check_vault_limit(tier, current_cards)
        if not allowed:
            return jsonify({
                "error": f"Credential vault limit reached ({max_allowed} credentials on {tier.title()} tier). Upgrade for more.",
                "upgrade_required": True,
                "current_count": current_cards,
                "max_allowed": max_allowed,
            }), 403

        card = m["RoutingTermsCard"](
            profile_id=profile.id,
            credential_label=data["credential_label"],
            credential_type=data["credential_type"],
            provider_system=data["provider_system"],
        )

        # Section 1: Pricing
        pricing = data.get("pricing", {})
        if pricing:
            card.per_query_fee_usd = pricing.get("per_query_fee_usd", 0.0)
            split = pricing.get("revenue_split", {})
            if split:
                card.revenue_split_router_pct = split.get("router_pct", 70.0)
                card.revenue_split_host_pct = split.get("host_pct", 30.0)
            card.min_booking_value_usd = pricing.get("min_booking_value_usd")
            card.min_margin_usd = pricing.get("min_margin_usd")
            card.pricing_currency = pricing.get("currency", "USD")

        # Section 2: Coverage
        coverage = data.get("coverage", {})
        if coverage:
            card.markets_included_json = coverage.get("markets_included", [])
            card.markets_excluded_json = coverage.get("markets_excluded", [])
            card.airlines_included_json = coverage.get("airlines_included", [])
            card.airlines_excluded_json = coverage.get("airlines_excluded", [])
            card.cabin_classes_json = coverage.get("cabin_classes", [])
            card.trip_types_json = coverage.get("trip_types", [])

        # Section 3: Limits
        limits = data.get("limits", {})
        if limits:
            card.max_queries_per_day = limits.get("max_queries_per_day")
            card.max_queries_per_hour = limits.get("max_queries_per_hour")
            card.max_bookings_per_day = limits.get("max_bookings_per_day")
            card.available_hours_utc = limits.get("available_hours_utc", "00:00-23:59")
            card.response_time_sla_sec = limits.get("response_time_sla_sec", 8.0)
            card.auto_pause_error_rate_pct = limits.get("auto_pause_error_rate_pct", 15.0)

        # Section 4: Relationship
        rel = data.get("relationship", {})
        if rel:
            card.is_exclusive = rel.get("is_exclusive", False)
            card.min_monthly_volume = rel.get("min_monthly_volume")
            card.notice_period_days = rel.get("notice_period_days", 30)
            card.trial_period_days = rel.get("trial_period_days", 0)
            card.auto_renew = rel.get("auto_renew", True)

        # Section 5: Arbitrage
        arb = data.get("arbitrage", {})
        if arb:
            card.allow_pos_arbitrage = arb.get("allow_pos_arbitrage", True)
            card.markup_cap_pct = arb.get("markup_cap_pct")
            card.price_visibility = arb.get("price_visibility", "blind")

        card.is_published = data.get("is_published", False)

        db.session.add(card)
        db.session.commit()

        return jsonify({"success": True, "terms_card": card.to_dict()}), 201

    @app.route("/api/v1/network/terms/<int:card_id>", methods=["PUT"])
    @require_api_key
    def network_update_terms(card_id):
        """Update a terms card. Only the owning profile can update."""
        key_hash = request.api_key_hash
        profile = _ensure_profile(key_hash)
        db = _get_db()
        m = _get_models()

        card = m["RoutingTermsCard"].query.filter_by(
            id=card_id, profile_id=profile.id
        ).first()
        if not card:
            return jsonify({"error": "Terms card not found"}), 404

        data = request.get_json(silent=True) or {}

        # Direct field updates
        direct_fields = [
            "credential_label", "credential_type", "provider_system",
            "is_published",
        ]
        for field in direct_fields:
            if field in data:
                setattr(card, field, data[field])

        # Section updates (same structure as create)
        pricing = data.get("pricing", {})
        if pricing:
            if "per_query_fee_usd" in pricing:
                card.per_query_fee_usd = pricing["per_query_fee_usd"]
            split = pricing.get("revenue_split", {})
            if "router_pct" in split:
                card.revenue_split_router_pct = split["router_pct"]
            if "host_pct" in split:
                card.revenue_split_host_pct = split["host_pct"]
            if "min_booking_value_usd" in pricing:
                card.min_booking_value_usd = pricing["min_booking_value_usd"]
            if "min_margin_usd" in pricing:
                card.min_margin_usd = pricing["min_margin_usd"]
            if "currency" in pricing:
                card.pricing_currency = pricing["currency"]

        coverage = data.get("coverage", {})
        if coverage:
            for field in ("markets_included", "markets_excluded",
                          "airlines_included", "airlines_excluded",
                          "cabin_classes", "trip_types"):
                if field in coverage:
                    setattr(card, f"{field}_json", coverage[field])

        limits = data.get("limits", {})
        if limits:
            for field in ("max_queries_per_day", "max_queries_per_hour",
                          "max_bookings_per_day", "available_hours_utc",
                          "response_time_sla_sec", "auto_pause_error_rate_pct"):
                if field in limits:
                    setattr(card, field, limits[field])

        rel = data.get("relationship", {})
        if rel:
            for field in ("is_exclusive", "min_monthly_volume",
                          "notice_period_days", "trial_period_days", "auto_renew"):
                if field in rel:
                    setattr(card, field, rel[field])

        arb = data.get("arbitrage", {})
        if arb:
            for field in ("allow_pos_arbitrage", "markup_cap_pct", "price_visibility"):
                if field in arb:
                    setattr(card, field, arb[field])

        db.session.commit()
        return jsonify({"success": True, "terms_card": card.to_dict()})

    @app.route("/api/v1/network/terms/<int:card_id>", methods=["DELETE"])
    @require_api_key
    def network_delete_terms(card_id):
        """Delete a terms card. Fails if active connections reference it."""
        key_hash = request.api_key_hash
        profile = _ensure_profile(key_hash)
        db = _get_db()
        m = _get_models()

        card = m["RoutingTermsCard"].query.filter_by(
            id=card_id, profile_id=profile.id
        ).first()
        if not card:
            return jsonify({"error": "Terms card not found"}), 404

        # Check for active connections using this card
        active = m["NetworkConnection"].query.filter_by(
            terms_card_id=card_id
        ).filter(
            m["NetworkConnection"].status.in_(["pending", "active"])
        ).count()
        if active > 0:
            return jsonify({
                "error": f"Cannot delete: {active} active connection(s) reference this terms card"
            }), 409

        db.session.delete(card)
        db.session.commit()
        return jsonify({"success": True})

    # ===================================================================
    # CONNECTIONS — Request, accept, reject, pause, resume, disconnect
    # ===================================================================

    @app.route("/api/v1/network/connections", methods=["GET"])
    @require_api_key
    def network_list_connections():
        """
        List connections where the caller is either requester or provider.

        Query params:
            role     — "requester" or "provider" (default: both)
            status   — Filter by status (pending/active/paused/disconnected)
        """
        key_hash = request.api_key_hash
        m = _get_models()

        role = request.args.get("role")
        status_filter = request.args.get("status")

        if role == "requester":
            query = m["NetworkConnection"].query.filter_by(
                requester_key_hash=key_hash)
        elif role == "provider":
            query = m["NetworkConnection"].query.filter_by(
                provider_key_hash=key_hash)
        else:
            query = m["NetworkConnection"].query.filter(
                (m["NetworkConnection"].requester_key_hash == key_hash)
                | (m["NetworkConnection"].provider_key_hash == key_hash)
            )

        if status_filter:
            query = query.filter(m["NetworkConnection"].status == status_filter)

        connections = query.order_by(
            m["NetworkConnection"].requested_at.desc()
        ).all()

        results = []
        for conn in connections:
            d = conn.to_dict()
            d["role"] = "requester" if conn.requester_key_hash == key_hash else "provider"
            # Include terms card summary
            if conn.terms_card:
                d["terms_summary"] = {
                    "credential_label": conn.terms_card.credential_label,
                    "credential_type": conn.terms_card.credential_type,
                    "provider_system": conn.terms_card.provider_system,
                    "per_query_fee_usd": conn.terms_card.per_query_fee_usd,
                }
            results.append(d)

        return jsonify({"connections": results, "count": len(results)})

    @app.route("/api/v1/network/connections", methods=["POST"])
    @require_api_key
    def network_request_connection():
        """
        Request a connection to a provider.

        Body:
            provider_profile_id — ID of the provider's profile
            terms_card_id       — ID of the terms card to use
            message             — Optional introduction message
        """
        key_hash = request.api_key_hash
        db = _get_db()
        m = _get_models()

        data = request.get_json(silent=True) or {}

        provider_id = data.get("provider_profile_id")
        terms_card_id = data.get("terms_card_id")

        if not provider_id or not terms_card_id:
            return jsonify({
                "error": "provider_profile_id and terms_card_id are required"
            }), 400

        # Look up provider
        provider_profile = db.session.get(m["ProviderProfile"], provider_id)
        if not provider_profile or not provider_profile.is_visible:
            return jsonify({"error": "Provider not found"}), 404

        if not provider_profile.is_accepting_connections:
            return jsonify({"error": "Provider is not accepting connections"}), 403

        # Can't connect to yourself
        if provider_profile.key_hash == key_hash:
            return jsonify({"error": "Cannot connect to yourself"}), 400

        # Check for existing connection
        existing = m["NetworkConnection"].query.filter_by(
            requester_key_hash=key_hash,
            provider_key_hash=provider_profile.key_hash,
        ).filter(
            m["NetworkConnection"].status.in_(["pending", "active", "paused"])
        ).first()
        if existing:
            return jsonify({
                "error": "Connection already exists",
                "existing_status": existing.status,
            }), 409

        # Verify terms card belongs to the provider
        card = m["RoutingTermsCard"].query.filter_by(
            id=terms_card_id,
            profile_id=provider_id,
            is_published=True,
        ).first()
        if not card:
            return jsonify({"error": "Terms card not found or not published"}), 404

        # Calculate trial end date if applicable
        trial_ends = None
        if card.trial_period_days and card.trial_period_days > 0:
            trial_ends = datetime.now(timezone.utc) + timedelta(days=card.trial_period_days)

        conn = m["NetworkConnection"](
            requester_key_hash=key_hash,
            provider_key_hash=provider_profile.key_hash,
            terms_card_id=terms_card_id,
            status="pending",
            request_message=data.get("message"),
            trial_ends_at=trial_ends,
        )
        db.session.add(conn)
        db.session.commit()

        return jsonify({
            "success": True,
            "connection": conn.to_dict(),
        }), 201

    @app.route("/api/v1/network/connections/<int:conn_id>/accept", methods=["POST"])
    @require_api_key
    def network_accept_connection(conn_id):
        """Accept a pending connection request. Only the provider can accept."""
        key_hash = request.api_key_hash
        db = _get_db()
        m = _get_models()

        conn = m["NetworkConnection"].query.filter_by(
            id=conn_id,
            provider_key_hash=key_hash,
            status="pending",
        ).first()
        if not conn:
            return jsonify({"error": "Pending connection not found"}), 404

        # Apply custom overrides if provided
        data = request.get_json(silent=True) or {}
        if "custom_query_fee_usd" in data:
            conn.custom_query_fee_usd = data["custom_query_fee_usd"]
        if "custom_router_pct" in data:
            conn.custom_router_pct = data["custom_router_pct"]
        if "custom_host_pct" in data:
            conn.custom_host_pct = data["custom_host_pct"]

        conn.status = "active"
        conn.accepted_at = datetime.now(timezone.utc)

        # Increment provider's connection count
        profile = m["ProviderProfile"].query.filter_by(
            key_hash=key_hash
        ).first()
        if profile:
            profile.total_connections = (profile.total_connections or 0) + 1

        db.session.commit()

        return jsonify({"success": True, "connection": conn.to_dict()})

    @app.route("/api/v1/network/connections/<int:conn_id>/reject", methods=["POST"])
    @require_api_key
    def network_reject_connection(conn_id):
        """Reject a pending connection request. Only the provider can reject."""
        key_hash = request.api_key_hash
        db = _get_db()
        m = _get_models()

        conn = m["NetworkConnection"].query.filter_by(
            id=conn_id,
            provider_key_hash=key_hash,
            status="pending",
        ).first()
        if not conn:
            return jsonify({"error": "Pending connection not found"}), 404

        data = request.get_json(silent=True) or {}
        conn.status = "disconnected"
        conn.disconnected_at = datetime.now(timezone.utc)

        db.session.commit()
        return jsonify({"success": True, "message": "Connection rejected"})

    @app.route("/api/v1/network/connections/<int:conn_id>/pause", methods=["POST"])
    @require_api_key
    def network_pause_connection(conn_id):
        """Pause an active connection. Either party can pause."""
        key_hash = request.api_key_hash
        db = _get_db()
        m = _get_models()

        conn = m["NetworkConnection"].query.filter_by(
            id=conn_id, status="active"
        ).filter(
            (m["NetworkConnection"].requester_key_hash == key_hash)
            | (m["NetworkConnection"].provider_key_hash == key_hash)
        ).first()
        if not conn:
            return jsonify({"error": "Active connection not found"}), 404

        conn.status = "paused"
        conn.paused_at = datetime.now(timezone.utc)
        db.session.commit()

        return jsonify({"success": True, "connection": conn.to_dict()})

    @app.route("/api/v1/network/connections/<int:conn_id>/resume", methods=["POST"])
    @require_api_key
    def network_resume_connection(conn_id):
        """Resume a paused connection. Either party can resume."""
        key_hash = request.api_key_hash
        db = _get_db()
        m = _get_models()

        conn = m["NetworkConnection"].query.filter_by(
            id=conn_id, status="paused"
        ).filter(
            (m["NetworkConnection"].requester_key_hash == key_hash)
            | (m["NetworkConnection"].provider_key_hash == key_hash)
        ).first()
        if not conn:
            return jsonify({"error": "Paused connection not found"}), 404

        conn.status = "active"
        conn.paused_at = None
        db.session.commit()

        return jsonify({"success": True, "connection": conn.to_dict()})

    @app.route("/api/v1/network/connections/<int:conn_id>", methods=["DELETE"])
    @require_api_key
    def network_disconnect(conn_id):
        """Disconnect a connection. Either party can disconnect."""
        key_hash = request.api_key_hash
        db = _get_db()
        m = _get_models()

        conn = m["NetworkConnection"].query.filter_by(id=conn_id).filter(
            m["NetworkConnection"].status.in_(["pending", "active", "paused"])
        ).filter(
            (m["NetworkConnection"].requester_key_hash == key_hash)
            | (m["NetworkConnection"].provider_key_hash == key_hash)
        ).first()
        if not conn:
            return jsonify({"error": "Connection not found"}), 404

        conn.status = "disconnected"
        conn.disconnected_at = datetime.now(timezone.utc)

        # Decrement provider connection count
        profile = m["ProviderProfile"].query.filter_by(
            key_hash=conn.provider_key_hash
        ).first()
        if profile and profile.total_connections and profile.total_connections > 0:
            profile.total_connections -= 1

        db.session.commit()
        return jsonify({"success": True, "message": "Disconnected"})

    # ===================================================================
    # AUDIT — Transaction audit trail
    # ===================================================================

    @app.route("/api/v1/network/audit", methods=["GET"])
    @require_api_key
    def network_audit_trail():
        """
        Query the transaction audit trail for routing events.

        Requires Enterprise tier or above.

        Query params:
            connection_id — Filter by connection
            event_type    — search/booking/failure/timeout
            start_date    — ISO date (YYYY-MM-DD)
            end_date      — ISO date (YYYY-MM-DD)
            page          — Pagination (default 1)
            per_page      — Results per page (default 50, max 200)
        """
        key_hash = request.api_key_hash

        # Tier gate: audit trail requires Enterprise+
        allowed, err, code = _tier_gate(key_hash, "transaction_audit_trail")
        if not allowed:
            return err, code

        m = _get_models()

        # Only show events where caller is router or host
        query = m["RoutingEvent"].query.filter(
            (m["RoutingEvent"].router_key_hash == key_hash)
            | (m["RoutingEvent"].host_key_hash == key_hash)
        )

        conn_id = request.args.get("connection_id", type=int)
        if conn_id:
            query = query.filter(m["RoutingEvent"].connection_id == conn_id)

        event_type = request.args.get("event_type")
        if event_type:
            query = query.filter(m["RoutingEvent"].event_type == event_type)

        start_date = request.args.get("start_date")
        if start_date:
            try:
                start = datetime.fromisoformat(start_date)
                query = query.filter(m["RoutingEvent"].created_at >= start)
            except ValueError:
                pass

        end_date = request.args.get("end_date")
        if end_date:
            try:
                end = datetime.fromisoformat(end_date)
                query = query.filter(m["RoutingEvent"].created_at <= end)
            except ValueError:
                pass

        query = query.order_by(m["RoutingEvent"].created_at.desc())

        page = max(1, request.args.get("page", 1, type=int))
        per_page = min(200, max(1, request.args.get("per_page", 50, type=int)))
        paginated = query.paginate(page=page, per_page=per_page, error_out=False)

        return jsonify({
            "events": [e.to_dict() for e in paginated.items],
            "page": page,
            "per_page": per_page,
            "total": paginated.total,
            "pages": paginated.pages,
        })

    # ===================================================================
    # STATS — Aggregate network stats for the subscriber
    # ===================================================================

    @app.route("/api/v1/network/stats", methods=["GET"])
    @require_api_key
    def network_stats():
        """
        Aggregate network statistics for the calling subscriber.

        Returns connection counts, routing volumes, revenue summary,
        and health overview.
        """
        key_hash = request.api_key_hash
        m = _get_models()
        db = _get_db()

        profile = _ensure_profile(key_hash)

        # Connection counts by status
        conn_query = m["NetworkConnection"].query.filter(
            (m["NetworkConnection"].requester_key_hash == key_hash)
            | (m["NetworkConnection"].provider_key_hash == key_hash)
        )

        active = conn_query.filter_by(status="active").count()
        pending = conn_query.filter_by(status="pending").count()
        paused = conn_query.filter_by(status="paused").count()

        # Revenue this month (as router and as host)
        as_router = m["NetworkConnection"].query.filter_by(
            requester_key_hash=key_hash, status="active"
        ).all()
        as_host = m["NetworkConnection"].query.filter_by(
            provider_key_hash=key_hash, status="active"
        ).all()

        revenue_as_router = sum(c.revenue_earned_this_month_usd for c in as_router)
        revenue_as_host = sum(c.revenue_earned_this_month_usd for c in as_host)
        queries_as_router = sum(c.queries_this_month for c in as_router)
        queries_as_host = sum(c.queries_this_month for c in as_host)
        bookings_as_router = sum(c.bookings_this_month for c in as_router)
        bookings_as_host = sum(c.bookings_this_month for c in as_host)

        # Health summary
        all_active = conn_query.filter_by(status="active").all()
        health_counts = {"green": 0, "yellow": 0, "red": 0}
        for c in all_active:
            h = c.health or "green"
            health_counts[h] = health_counts.get(h, 0) + 1

        # Published terms cards count
        terms_count = m["RoutingTermsCard"].query.filter_by(
            profile_id=profile.id, is_published=True
        ).count()

        # Tier info
        tier = _get_tier(key_hash)
        tier_info = get_tier_summary(tier)

        result = {
            "profile": profile.to_dict(include_stats=True),
            "connections": {
                "active": active,
                "pending": pending,
                "paused": paused,
            },
            "this_month": {
                "as_router": {
                    "queries": queries_as_router,
                    "bookings": bookings_as_router,
                    "revenue_usd": round(revenue_as_router, 2),
                },
                "as_host": {
                    "queries": queries_as_host,
                    "bookings": bookings_as_host,
                    "revenue_usd": round(revenue_as_host, 2),
                },
            },
            "health": health_counts,
            "published_terms_cards": terms_count,
            "tier": tier_info,
        }

        # Full analytics only for Enterprise+
        if has_feature(tier, "full_analytics"):
            result["analytics_depth"] = "full"
        else:
            result["analytics_depth"] = "basic"

        return jsonify(result)

    # ===================================================================
    # TIER INFO — What features are available / locked
    # ===================================================================

    @app.route("/api/v1/network/tier", methods=["GET"])
    @require_api_key
    def network_tier_info():
        """
        Get the caller's tier info including limits, available features,
        and locked features (for the taste strategy UI).
        """
        key_hash = request.api_key_hash
        tier = _get_tier(key_hash)
        return jsonify(get_tier_summary(tier))
