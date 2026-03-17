"""
MYSTES Commercial API Authentication Middleware

Authenticates commercial API requests via API key in the Authorization header
or X-API-Key header. Enforces rate limits, scope checks, and account status.

Usage:
    from commercial_auth import require_api_key, get_commercial_account

    @app.route("/api/v1/search", methods=["POST"])
    @require_api_key(scope="search")
    def commercial_search():
        account = get_commercial_account()
        # account is the authenticated CommercialAccount
        ...

Header format:
    Authorization: Bearer phx_<key>
    — or —
    X-API-Key: phx_<key>
"""

import functools
import logging
from datetime import datetime, timedelta

from flask import request, g, jsonify

logger = logging.getLogger(__name__)


def _extract_api_key():
    """Extract API key from request headers."""
    # Try Authorization: Bearer phx_xxx
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:].strip()

    # Try X-API-Key: phx_xxx
    return request.headers.get("X-API-Key", "").strip() or None


def get_commercial_account():
    """Get the authenticated commercial account from the request context."""
    return getattr(g, "commercial_account", None)


def get_commercial_scopes():
    """Get the scopes of the authenticated API key."""
    return getattr(g, "commercial_scopes", [])


def require_api_key(scope=None):
    """
    Decorator that requires a valid commercial API key.

    Args:
        scope: Optional required scope (e.g. "search", "book", "p2p", "analytics").
               If None, any valid key is accepted.
    """
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            key_string = _extract_api_key()
            if not key_string:
                return jsonify({"error": "API key required", "hint": "Set Authorization: Bearer phx_<key>"}), 401

            from commercial import commercial_manager
            result = commercial_manager.verify_api_key(key_string)

            if result is None:
                return jsonify({"error": "Invalid or expired API key"}), 401

            account, api_key, scopes = result

            # Check scope
            if scope and scope not in scopes:
                return jsonify({
                    "error": f"Insufficient scope: '{scope}' required",
                    "your_scopes": scopes,
                }), 403

            # Check account is active
            if not account.is_active:
                return jsonify({"error": "Account suspended"}), 403

            # Store in request context
            g.commercial_account = account
            g.commercial_api_key = api_key
            g.commercial_scopes = scopes

            return fn(*args, **kwargs)
        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# Browsing API Rate Limiter (Build #71)
# ---------------------------------------------------------------------------



def register_commercial_routes(app):
    """Register commercial API endpoints on the Flask app."""
    from flask_login import login_required, current_user

    # ------------------------------------------------------------------
    # Account management (authenticated via session — account owner/admin)
    # ------------------------------------------------------------------

    @app.route("/api/commercial/accounts", methods=["POST"])
    @login_required
    def create_commercial_account():
        """Create a new commercial account."""
        if not current_user.is_admin:
            return jsonify({"error": "Admin only"}), 403

        data = request.get_json()
        if not data:
            return jsonify({"error": "JSON body required"}), 400

        from commercial import commercial_manager
        result = commercial_manager.create_account(
            name=data.get("name"),
            contact_email=data.get("contact_email"),
            owner_user_id=data.get("owner_user_id", current_user.id),
            contact_name=data.get("contact_name"),
            company_website=data.get("company_website"),
        )
        return jsonify(result), 201

    @app.route("/api/commercial/accounts", methods=["GET"])
    @login_required
    def list_commercial_accounts():
        """List commercial accounts (admin only)."""
        if not current_user.is_admin:
            return jsonify({"error": "Admin only"}), 403

        from commercial import commercial_manager
        accounts = commercial_manager.list_accounts()
        return jsonify({"accounts": accounts})

    @app.route("/api/commercial/accounts/<account_id>", methods=["GET"])
    @login_required
    def get_commercial_account_detail(account_id):
        """Get commercial account details and stats."""
        from commercial import commercial_manager

        account = commercial_manager.get_account(account_id)
        if not account:
            return jsonify({"error": "Not found"}), 404

        if not current_user.is_admin and account.owner_user_id != current_user.id:
            return jsonify({"error": "Forbidden"}), 403

        stats = commercial_manager.get_account_stats(account_id)
        return jsonify(stats)

    @app.route("/api/commercial/accounts/<account_id>/suspend", methods=["POST"])
    @login_required
    def suspend_commercial_account(account_id):
        """Suspend a commercial account (admin only)."""
        if not current_user.is_admin:
            return jsonify({"error": "Admin only"}), 403

        from commercial import commercial_manager
        data = request.get_json() or {}
        result = commercial_manager.suspend_account(account_id, reason=data.get("reason"))
        return jsonify(result)

    @app.route("/api/commercial/accounts/<account_id>/reactivate", methods=["POST"])
    @login_required
    def reactivate_commercial_account(account_id):
        """Reactivate a suspended account (admin only)."""
        if not current_user.is_admin:
            return jsonify({"error": "Admin only"}), 403

        from commercial import commercial_manager
        result = commercial_manager.reactivate_account(account_id)
        return jsonify(result)

    # ------------------------------------------------------------------
    # API key management
    # ------------------------------------------------------------------

    @app.route("/api/commercial/accounts/<account_id>/keys", methods=["POST"])
    @login_required
    def create_api_key(account_id):
        """Generate a new API key for a commercial account."""
        from commercial import commercial_manager

        account = commercial_manager.get_account(account_id)
        if not account:
            return jsonify({"error": "Not found"}), 404
        if not current_user.is_admin and account.owner_user_id != current_user.id:
            return jsonify({"error": "Forbidden"}), 403

        data = request.get_json() or {}
        result = commercial_manager.create_api_key(
            account_id=account_id,
            label=data.get("label", "Default"),
            scopes=data.get("scopes"),
            expires_days=data.get("expires_days"),
        )
        return jsonify(result), 201

    @app.route("/api/commercial/accounts/<account_id>/keys/<int:key_id>", methods=["DELETE"])
    @login_required
    def revoke_api_key_route(account_id, key_id):
        """Revoke an API key."""
        from commercial import commercial_manager

        account = commercial_manager.get_account(account_id)
        if not account:
            return jsonify({"error": "Not found"}), 404
        if not current_user.is_admin and account.owner_user_id != current_user.id:
            return jsonify({"error": "Forbidden"}), 403

        result = commercial_manager.revoke_api_key(key_id, account_id)
        return jsonify(result)

    # ------------------------------------------------------------------
    # Commercial API endpoints (authenticated via API key)
    # ------------------------------------------------------------------

    @app.route("/api/v1/search", methods=["POST"])
    @require_api_key(scope="search")
    def commercial_search():
        """
        Commercial search endpoint — returns arbitrage opportunities.

        POST body: {"origin": "JFK", "destination": "NRT", "date": "2026-03-15"}
        """
        account = get_commercial_account()
        data = request.get_json()
        if not data:
            return jsonify({"error": "JSON body required"}), 400

        origin = data.get("origin")
        destination = data.get("destination")
        date = data.get("date")
        cabin = data.get("cabin_class", "economy")
        return_date = data.get("return_date")

        if not all([origin, destination, date]):
            return jsonify({"error": "origin, destination, and date required"}), 400

        try:
            from search import search_global
            results = search_global(
                origin=origin,
                destination=destination,
                date=date,
                return_date=return_date,
                fast_mode=True,
            )

            # Record search for data pipeline
            try:
                from search_tracker import tracker
                tracker.record_search(
                    user_id=None,
                    origin=origin,
                    destination=destination,
                    departure_date=date,
                    results=results.get("deals", []) if isinstance(results, dict) else results,
                    method="commercial_api",
                )
            except Exception:
                pass  # Non-blocking

            # Calculate savings for each deal
            flights = results if isinstance(results, list) else results.get("flights", [])
            deals = results.get("deals", []) if isinstance(results, dict) else []
            enriched_deals = []
            for deal_data in deals:
                deal_info = deal_data.get("deal", {})
                home_price = deal_info.get("home_price", 0) or 0
                arb_price = deal_info.get("arbitrage_price", 0) or 0
                if home_price > 0 and arb_price > 0 and home_price > arb_price:
                    gross_savings = home_price - arb_price
                    fee_amount = gross_savings * (account.fee_percent / 100)
                    net_savings = gross_savings - fee_amount
                    deal_data["savings"] = {
                        "home_price_usd": home_price,
                        "arbitrage_price_usd": arb_price,
                        "gross_savings_usd": round(gross_savings, 2),
                        "fee_percent": account.fee_percent,
                        "fee_usd": round(fee_amount, 2),
                        "net_savings_usd": round(net_savings, 2),
                        "savings_percent": round((gross_savings / home_price) * 100, 1),
                    }
                enriched_deals.append(deal_data)

            return jsonify({
                "account_id": account.account_id,
                "tier": account.current_tier,
                "fee_percent": account.fee_percent,
                "results": flights,
                "deals": enriched_deals,
            })
        except Exception as e:
            logger.error(f"Commercial search error: {e}")
            return jsonify({"error": "Search failed"}), 500

    @app.route("/api/v1/account/stats", methods=["GET"])
    @require_api_key(scope="analytics")
    def commercial_my_stats():
        """Get usage stats for the authenticated commercial account."""
        account = get_commercial_account()
        from commercial import commercial_manager
        stats = commercial_manager.get_account_stats(account.account_id)
        return jsonify(stats)

    @app.route("/api/v1/account/tier", methods=["GET"])
    @require_api_key()
    def commercial_my_tier():
        """Get current tier info for the authenticated account."""
        account = get_commercial_account()
        from commercial import TIERS, TIER_ORDER

        current = account.current_tier
        tier_info = TIERS[current]

        # Find next tier
        current_idx = TIER_ORDER.index(current) if current in TIER_ORDER else len(TIER_ORDER) - 1
        next_tier = TIER_ORDER[current_idx - 1] if current_idx > 0 else None

        return jsonify({
            "current_tier": current,
            "fee_percent": account.fee_percent,
            "tickets_last_30d": account.tickets_last_30d,
            "next_tier": next_tier,
            "next_tier_threshold": TIERS[next_tier]["min_tickets_30d"] if next_tier else None,
            "tickets_needed": max(0, TIERS[next_tier]["min_tickets_30d"] - (account.tickets_last_30d or 0)) if next_tier else 0,
            "all_tiers": {name: {"fee_percent": t["fee_percent"], "min_tickets": t["min_tickets_30d"]} for name, t in TIERS.items()},
        })

    # ------------------------------------------------------------------
    # Referral routes
    # ------------------------------------------------------------------

    @app.route("/join/<referral_code>")
    def agency_portal_redirect(referral_code):
        """
        Agency-branded signup redirect.

        /join/APEXTRAVEL → validates code, stores in session, redirects to signup.
        The signup handler reads the code from session and calls attribute_referral().
        """
        from flask import redirect, session, url_for
        from commercial import commercial_manager

        account = commercial_manager.get_account_by_referral_code(referral_code)
        if not account:
            return jsonify({"error": "Invalid referral code"}), 404

        # Store in session so the signup flow can attribute it
        session["referral_code"] = account.referral_code
        session["referral_account_id"] = account.account_id
        session["referral_agency_name"] = account.name

        # Redirect to signup page (frontend will show agency branding)
        return redirect(f"/signup?ref={account.referral_code}")

    @app.route("/api/referral/validate/<referral_code>", methods=["GET"])
    def validate_referral_code(referral_code):
        """Validate a referral code and return the agency name (public endpoint)."""
        from commercial import commercial_manager

        account = commercial_manager.get_account_by_referral_code(referral_code)
        if not account:
            return jsonify({"valid": False}), 404

        return jsonify({
            "valid": True,
            "agency_name": account.name,
            "referral_code": account.referral_code,
        })

    @app.route("/api/commercial/accounts/<account_id>/referrals", methods=["GET"])
    @login_required
    def get_referral_stats(account_id):
        """Get referral stats for a commercial account."""
        from commercial import commercial_manager

        account = commercial_manager.get_account(account_id)
        if not account:
            return jsonify({"error": "Not found"}), 404
        if not current_user.is_admin and account.owner_user_id != current_user.id:
            return jsonify({"error": "Forbidden"}), 403

        stats = commercial_manager.get_referral_stats(account_id)
        if not stats:
            return jsonify({"error": "Not found"}), 404
        return jsonify(stats)

    @app.route("/api/commercial/accounts/<account_id>/referral-code", methods=["PUT"])
    @login_required
    def update_referral_code(account_id):
        """Update an account's referral code."""
        from commercial import commercial_manager

        account = commercial_manager.get_account(account_id)
        if not account:
            return jsonify({"error": "Not found"}), 404
        if not current_user.is_admin and account.owner_user_id != current_user.id:
            return jsonify({"error": "Forbidden"}), 403

        data = request.get_json()
        if not data or not data.get("referral_code"):
            return jsonify({"error": "referral_code required"}), 400

        result = commercial_manager.update_referral_code(account_id, data["referral_code"])
        if "error" in result:
            return jsonify(result), 400
        return jsonify(result)

    @app.route("/api/v1/account/referrals", methods=["GET"])
    @require_api_key(scope="analytics")
    def commercial_my_referrals():
        """Get referral stats for the authenticated commercial account (via API key)."""
        account = get_commercial_account()
        from commercial import commercial_manager
        stats = commercial_manager.get_referral_stats(account.account_id)
        return jsonify(stats)

    @app.route("/api/v1/account/share-links", methods=["GET"])
    @require_api_key(scope="analytics")
    def commercial_share_links():
        """Get multi-platform share links for the commercial account's referral code."""
        account = get_commercial_account()
        if not account.referral_code:
            return jsonify({"error": "No referral code set for this account"}), 400

        from share_links import generate_referral_share_links
        import os
        base_url = os.environ.get("BASE_URL", "http://localhost:5001")
        share = generate_referral_share_links(
            account.referral_code,
            account.company_name or "",
            base_url,
        )
        return jsonify({
            "referral_code": account.referral_code,
            "referral_url": f"{base_url}/join/{account.referral_code}",
            "share_links": share,
        })

    # ------------------------------------------------------------------
    # Commercial Account Self-Service Onboarding (Build #71)
    # ------------------------------------------------------------------

    @app.route("/api/commercial/signup", methods=["POST"])
    def commercial_signup():
        """Self-service commercial account signup.

        POST body: {
            "company_name": "Apex Travel Co",
            "contact_email": "api@apextravel.com",
            "contact_name": "Jane Smith",
            "company_website": "https://apextravel.com"
        }

        Returns account_id and a starter API key (scope: search, analytics).
        Account is created in pending state until email verification.
        """
        data = request.get_json()
        if not data:
            return jsonify({"error": "JSON body required"}), 400

        company_name = (data.get("company_name") or "").strip()
        contact_email = (data.get("contact_email") or "").strip()
        contact_name = (data.get("contact_name") or "").strip()
        company_website = (data.get("company_website") or "").strip()

        # Validation
        if not company_name or len(company_name) < 2:
            return jsonify({"error": "company_name is required (min 2 chars)"}), 400
        if not contact_email or "@" not in contact_email:
            return jsonify({"error": "Valid contact_email is required"}), 400
        if len(company_name) > 200:
            return jsonify({"error": "company_name too long (max 200 chars)"}), 400

        # Check for duplicate email
        from models import CommercialAccount
        existing = CommercialAccount.query.filter_by(contact_email=contact_email).first()
        if existing:
            return jsonify({"error": "An account with this email already exists"}), 409

        from commercial import commercial_manager
        import secrets

        try:
            # Create the account
            result = commercial_manager.create_account(
                name=company_name,
                contact_email=contact_email,
                owner_user_id=None,
                contact_name=contact_name,
                company_website=company_website,
            )

            account_id = result.get("account_id")
            if not account_id:
                return jsonify({"error": "Failed to create account"}), 500

            # Generate a starter API key with basic scopes
            key_result = commercial_manager.create_api_key(
                account_id=account_id,
                label="Starter Key (auto-generated)",
                scopes=["search", "analytics", "data_marketplace"],
                expires_days=365,
            )

            # Generate verification token
            verification_token = secrets.token_urlsafe(32)

            logger.info(
                "Commercial signup: %s (%s) — account_id=%s",
                company_name, contact_email, account_id,
            )

            return jsonify({
                "status": "created",
                "account_id": account_id,
                "company_name": company_name,
                "contact_email": contact_email,
                "api_key": key_result.get("api_key"),
                "api_key_prefix": key_result.get("prefix"),
                "scopes": ["search", "analytics"],
                "tier": "starter",
                "message": "Account created. Your API key is shown once — save it securely.",
                "next_steps": [
                    "Save your API key — it will not be shown again",
                    "Set Authorization: Bearer <your-key> in API requests",
                    "Start with POST /api/v1/search to find arbitrage deals",
                    "Check GET /api/v1/account/tier for your current pricing tier",
                ],
            }), 201

        except Exception as e:
            logger.exception("Commercial signup failed for %s", contact_email)
            return jsonify({"error": "Signup failed. Please try again or contact support."}), 500

    # --- Intelligence API Routes (Commercial) ---

    @app.route("/api/v1/intelligence/route/<origin>/<destination>")
    @require_api_key(scope="analytics")
    def commercial_intelligence_route(origin, destination):
        """Route intelligence profile via commercial API."""
        from mystes_intelligence import intelligence
        data = intelligence.get_route_intelligence(
            origin.upper(), destination.upper(),
            days_back=int(request.args.get("days", 30)),
        )
        return jsonify(data)

    @app.route("/api/v1/intelligence/market/<market>")
    @require_api_key(scope="analytics")
    def commercial_intelligence_market(market):
        """Market briefing via commercial API."""
        from mystes_intelligence import intelligence
        data = intelligence.get_market_briefing(
            market.upper(),
            days_back=int(request.args.get("days", 7)),
        )
        return jsonify(data)

    @app.route("/api/v1/intelligence/trending")
    @require_api_key(scope="analytics")
    def commercial_intelligence_trending():
        """Trending routes and anomalies via commercial API."""
        from mystes_intelligence import intelligence
        anomalies = intelligence.detect_anomalies(
            days=int(request.args.get("days", 7)),
        )
        stats = intelligence.get_platform_stats()
        return jsonify({"anomalies": anomalies, "platform": stats})

    # --- Phase 2 Commercial Intelligence Routes ---

    @app.route("/api/v1/intelligence/p2p/network")
    @require_api_key(scope="analytics")
    def commercial_intelligence_p2p_network():
        """P2P network health via commercial API."""
        from mystes_intelligence import intelligence
        days = int(request.args.get("days", 30))
        return jsonify(intelligence.get_p2p_network(days_back=days))

    @app.route("/api/v1/intelligence/p2p/savings")
    @require_api_key(scope="analytics")
    def commercial_intelligence_p2p_savings():
        """Top P2P savings routes via commercial API."""
        from mystes_intelligence import intelligence
        days = int(request.args.get("days", 30))
        limit = int(request.args.get("limit", 10))
        return jsonify(intelligence.get_p2p_savings(days_back=days, limit=limit))

    @app.route("/api/v1/intelligence/nodes")
    @require_api_key(scope="analytics")
    def commercial_intelligence_nodes():
        """CitizenSERP node network via commercial API."""
        from mystes_intelligence import intelligence
        return jsonify(intelligence.get_node_network())

    @app.route("/api/v1/intelligence/proxy")
    @require_api_key(scope="analytics")
    def commercial_intelligence_proxy():
        """Proxy portal usage via commercial API."""
        from mystes_intelligence import intelligence
        days = int(request.args.get("days", 7))
        return jsonify(intelligence.get_proxy_usage(days_back=days))

    @app.route("/api/v1/intelligence/ai")
    @require_api_key(scope="analytics")
    def commercial_intelligence_ai():
        """AI analytics via commercial API."""
        from mystes_intelligence import intelligence
        days = int(request.args.get("days", 30))
        return jsonify(intelligence.get_ai_analytics(days_back=days))

    @app.route("/api/v1/intelligence/price-history/<origin>/<dest>")
    @require_api_key(scope="analytics")
    def commercial_intelligence_price_history(origin, dest):
        """Price timeline via commercial API."""
        from mystes_intelligence import intelligence
        days = int(request.args.get("days", 30))
        return jsonify(intelligence.get_price_timeline(origin.upper(), dest.upper(), days_back=days))

    @app.route("/api/v1/intelligence/airlines/<origin>/<dest>")
    @require_api_key(scope="analytics")
    def commercial_intelligence_airlines(origin, dest):
        """Airline competitive pricing via commercial API."""
        from mystes_intelligence import intelligence
        days = int(request.args.get("days", 7))
        return jsonify(intelligence.get_airline_comparison(origin.upper(), dest.upper(), days_back=days))

    # --- Commercial Agent Routes ---

    @app.route("/api/v1/agent/search", methods=["POST"])
    @require_api_key(scope="search")
    def commercial_agent_search():
        """Agent-orchestrated search via commercial API."""
        from mystes_agent import mystes_agent
        data = request.get_json() or {}
        query = data.get("query", "")
        if not query:
            return jsonify({"error": "query is required"}), 400
        task_type = data.get("task_type", "flight_search")
        user_market = data.get("market", "US")
        result = mystes_agent.handle_search(
            query=query,
            user_id=None,
            task_type=task_type,
            user_market=user_market,
            params=data.get("params", {}),
        )
        return jsonify(result)

    @app.route("/api/v1/agent/analyze/<origin>/<destination>")
    @require_api_key(scope="analytics")
    def commercial_agent_analyze(origin, destination):
        """Agent route analysis via commercial API."""
        from mystes_agent import mystes_agent
        user_market = request.args.get("market", "US")
        return jsonify(mystes_agent.analyze_route(
            origin.upper(), destination.upper(), user_market=user_market
        ))

    @app.route("/api/v1/agent/discover")
    @require_api_key(scope="analytics")
    def commercial_agent_discover():
        """Agent opportunity discovery via commercial API."""
        from mystes_agent import mystes_agent
        force = request.args.get("force", "false").lower() == "true"
        return jsonify(mystes_agent.discover_opportunities(force=force))

    @app.route("/api/v1/agent/status")
    @require_api_key(scope="analytics")
    def commercial_agent_status():
        """Agent status via commercial API."""
        from mystes_agent import mystes_agent
        return jsonify(mystes_agent.get_agent_status())






    # ==================================================================
    # Marketplace Commercial API (Build #66)
    # ==================================================================

    @app.route("/api/v1/marketplace/listings", methods=["GET"])
    @require_api_key(scope="analytics")
    def marketplace_listings():
        """Query marketplace listing records. Filter by market, location, bargains."""
        from models import MarketplaceListingRecord
        query = MarketplaceListingRecord.query
        market = request.args.get("market")
        location = request.args.get("location")
        bargains_only = request.args.get("bargains_only", "false").lower() == "true"
        days = int(request.args.get("days", 7))
        limit = min(int(request.args.get("limit", 100)), 1000)
        offset = int(request.args.get("offset", 0))

        cutoff = datetime.utcnow() - timedelta(days=days)
        query = query.filter(MarketplaceListingRecord.observed_at >= cutoff)
        if market:
            query = query.filter(MarketplaceListingRecord.market == market)
        if location:
            query = query.filter(MarketplaceListingRecord.location.ilike(f"%{location}%"))
        if bargains_only:
            query = query.filter(MarketplaceListingRecord.is_bargain == True)

        total = query.count()
        records = query.order_by(MarketplaceListingRecord.observed_at.desc()).offset(offset).limit(limit).all()
        return jsonify({
            "total": total,
            "limit": limit,
            "offset": offset,
            "listings": [r.to_dict() for r in records],
        })

    @app.route("/api/v1/marketplace/stats", methods=["GET"])
    @require_api_key(scope="analytics")
    def marketplace_stats():
        """Marketplace listing statistics — volume, price distribution, bargain rates."""
        from models import MarketplaceListingRecord, db
        days = int(request.args.get("days", 7))
        market = request.args.get("market")

        cutoff = datetime.utcnow() - timedelta(days=days)
        base = MarketplaceListingRecord.query.filter(
            MarketplaceListingRecord.observed_at >= cutoff
        )
        if market:
            base = base.filter(MarketplaceListingRecord.market == market)

        total = base.count()
        bargains = base.filter(MarketplaceListingRecord.is_bargain == True).count()
        avg_price = db.session.query(db.func.avg(MarketplaceListingRecord.price_usd)).filter(
            MarketplaceListingRecord.observed_at >= cutoff
        )
        if market:
            avg_price = avg_price.filter(MarketplaceListingRecord.market == market)
        avg_price = avg_price.scalar() or 0

        # Per-market breakdown
        from sqlalchemy import func
        market_counts = db.session.query(
            MarketplaceListingRecord.market,
            func.count(MarketplaceListingRecord.id),
        ).filter(
            MarketplaceListingRecord.observed_at >= cutoff
        ).group_by(MarketplaceListingRecord.market).all()

        return jsonify({
            "days": days,
            "total_listings": total,
            "total_bargains": bargains,
            "bargain_rate": round(bargains / total * 100, 1) if total > 0 else 0,
            "avg_price_usd": round(avg_price, 2),
            "by_market": {m: c for m, c in market_counts},
        })

    @app.route("/api/v1/vertical/prices", methods=["GET"])
    @require_api_key(scope="analytics")
    def vertical_price_query():
        """Query structured price records across verticals (flights, hotels, cruises, products)."""
        vertical = request.args.get("vertical", "flights")
        market = request.args.get("market")
        days = int(request.args.get("days", 7))
        limit = min(int(request.args.get("limit", 100)), 1000)
        offset = int(request.args.get("offset", 0))

        cutoff = datetime.utcnow() - timedelta(days=days)

        from models import FlightPriceRecord, HotelPriceRecord, CruisePriceRecord, ProductPriceRecord
        model_map = {
            "flights": FlightPriceRecord,
            "hotels": HotelPriceRecord,
            "cruises": CruisePriceRecord,
            "products": ProductPriceRecord,
        }
        model = model_map.get(vertical)
        if not model:
            return jsonify({"error": f"Unknown vertical: {vertical}. Use: {', '.join(model_map.keys())}"}), 400

        query = model.query.filter(model.observed_at >= cutoff)
        if market:
            query = query.filter(model.market == market)

        # Vertical-specific filters
        if vertical == "flights":
            origin = request.args.get("origin")
            destination = request.args.get("destination")
            airline = request.args.get("airline")
            if origin:
                query = query.filter(model.origin == origin.upper())
            if destination:
                query = query.filter(model.destination == destination.upper())
            if airline:
                query = query.filter(model.airline.ilike(f"%{airline}%"))
        elif vertical == "hotels":
            hotel_name = request.args.get("hotel_name")
            location = request.args.get("location")
            if hotel_name:
                query = query.filter(model.hotel_name.ilike(f"%{hotel_name}%"))
            if location:
                query = query.filter(model.location.ilike(f"%{location}%"))
        elif vertical == "cruises":
            cruise_line = request.args.get("cruise_line")
            departure_port = request.args.get("departure_port")
            if cruise_line:
                query = query.filter(model.cruise_line.ilike(f"%{cruise_line}%"))
            if departure_port:
                query = query.filter(model.departure_port.ilike(f"%{departure_port}%"))
        elif vertical == "products":
            category = request.args.get("category")
            platform = request.args.get("platform")
            if category:
                query = query.filter(model.category == category)
            if platform:
                query = query.filter(model.platform.ilike(f"%{platform}%"))

        total = query.count()
        records = query.order_by(model.observed_at.desc()).offset(offset).limit(limit).all()
        return jsonify({
            "vertical": vertical,
            "total": total,
            "limit": limit,
            "offset": offset,
            "records": [r.to_dict() for r in records],
        })

