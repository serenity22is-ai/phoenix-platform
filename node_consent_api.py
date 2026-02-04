"""
Node Consent Economy API Routes (Build #75)

REST API for consent management, tier assessment, referrals, fleet enrollment,
wallet info, revenue allocation history, and crypto conversion.
"""

import logging
from flask import request, jsonify
from flask_login import login_required, current_user

logger = logging.getLogger(__name__)


def register_node_consent_routes(app):
    """Register node consent economy API endpoints on the Flask app."""

    from node_consent_economy import node_consent_economy

    # ------------------------------------------------------------------
    # Auth helper — support both session login and helper token
    # ------------------------------------------------------------------

    def _get_authenticated_user_id():
        """Get user_id from session or helper token."""
        if current_user and current_user.is_authenticated:
            return current_user.id

        # Check for helper token
        auth = request.headers.get('Authorization', '')
        if auth.startswith('Bearer '):
            token = auth[7:]
            from models import HelperProfile
            profile = HelperProfile.query.filter_by(helper_token=token).first()
            if profile:
                return profile.user_id

        return None

    # ------------------------------------------------------------------
    # 1. GET /api/v1/node/consent — Get consent profile + tier
    # ------------------------------------------------------------------

    @app.route('/api/v1/node/consent', methods=['GET'])
    @login_required
    def get_node_consent():
        """Get current consent profile and tier status."""
        from models import NodeConsentProfile

        user_id = current_user.id
        profile = NodeConsentProfile.query.filter_by(user_id=user_id).first()

        if not profile:
            profile = node_consent_economy.create_default_profile(user_id)

        return jsonify(profile.to_dict())

    # ------------------------------------------------------------------
    # 2. PUT /api/v1/node/consent — Update consent toggles
    # ------------------------------------------------------------------

    @app.route('/api/v1/node/consent', methods=['PUT'])
    @login_required
    def update_node_consent():
        """Update data consent toggles. Triggers tier reassessment if changed."""
        data = request.get_json()
        if not data:
            return jsonify({'error': 'JSON body required'}), 400

        result = node_consent_economy.update_consent(current_user.id, data)
        if 'error' in result:
            return jsonify(result), 400

        return jsonify(result)

    # ------------------------------------------------------------------
    # 3. GET /api/v1/node/tier — Full tier assessment
    # ------------------------------------------------------------------

    @app.route('/api/v1/node/tier', methods=['GET'])
    @login_required
    def get_node_tier():
        """Get full tier assessment with score breakdown."""
        period = request.args.get('period_days', 30, type=int)
        period = max(7, min(90, period))

        result = node_consent_economy.assess_tier(current_user.id, period_days=period)
        if 'error' in result:
            return jsonify(result), 400

        return jsonify(result)

    # ------------------------------------------------------------------
    # 4. GET /api/v1/node/tier/history — Tier change history
    # ------------------------------------------------------------------

    @app.route('/api/v1/node/tier/history', methods=['GET'])
    @login_required
    def get_node_tier_history():
        """Get tier change audit trail."""
        from models import NodeTierHistory

        limit = min(int(request.args.get('limit', 20)), 100)

        history = NodeTierHistory.query.filter_by(
            user_id=current_user.id
        ).order_by(NodeTierHistory.created_at.desc()).limit(limit).all()

        return jsonify({
            'history': [h.to_dict() for h in history],
            'count': len(history),
        })

    # ------------------------------------------------------------------
    # 5. GET /api/v1/node/wallet — Wallet address + info
    # ------------------------------------------------------------------

    @app.route('/api/v1/node/wallet', methods=['GET'])
    @login_required
    def get_node_wallet():
        """Get XRPL wallet address and KYC status."""
        result = node_consent_economy.get_wallet_info(current_user.id)
        if 'error' in result and not result.get('has_wallet'):
            return jsonify(result), 404

        return jsonify(result)

    # ------------------------------------------------------------------
    # 6. POST /api/v1/node/referral — Get/create referral code
    # ------------------------------------------------------------------

    @app.route('/api/v1/node/referral', methods=['POST'])
    @login_required
    def create_node_referral_code():
        """Get or create the user's referral code."""
        from models import db, User

        user = User.query.get(current_user.id)
        if not user:
            return jsonify({'error': 'User not found'}), 404

        if not user.node_referral_code:
            import secrets
            user.node_referral_code = f"PX{secrets.token_hex(4).upper()}"
            db.session.commit()

        return jsonify({
            'referral_code': user.node_referral_code,
            'referral_url': f"{request.host_url.rstrip('/')}/join/{user.node_referral_code}",
        })

    # ------------------------------------------------------------------
    # 7. GET /api/v1/node/referrals — Referral stats + list
    # ------------------------------------------------------------------

    @app.route('/api/v1/node/referrals', methods=['GET'])
    @login_required
    def get_node_referrals():
        """Get referral statistics and list of referred nodes."""
        result = node_consent_economy.get_referral_stats(current_user.id)
        if 'error' in result:
            return jsonify(result), 400

        return jsonify(result)

    # ------------------------------------------------------------------
    # 8. POST /api/v1/node/fleet/enroll — Enroll in fleet
    # ------------------------------------------------------------------

    @app.route('/api/v1/node/fleet/enroll', methods=['POST'])
    @login_required
    def enroll_in_fleet():
        """Enroll in a commercial fleet via enrollment key."""
        data = request.get_json()
        if not data or not data.get('enrollment_key'):
            return jsonify({'error': 'enrollment_key required'}), 400

        result = node_consent_economy.enroll_node_in_fleet(
            current_user.id,
            data['enrollment_key'],
        )
        if 'error' in result:
            return jsonify(result), 400

        return jsonify(result)

    # ------------------------------------------------------------------
    # 9. GET /api/v1/node/revenue — Revenue allocation history
    # ------------------------------------------------------------------

    @app.route('/api/v1/node/revenue', methods=['GET'])
    @login_required
    def get_node_revenue():
        """Get revenue allocation history (arbitrage fee shares)."""
        limit = min(int(request.args.get('limit', 50)), 200)
        result = node_consent_economy.get_allocation_history(current_user.id, limit=limit)
        return jsonify(result)

    # ------------------------------------------------------------------
    # 10. POST /api/v1/node/wallet/convert — Initiate crypto conversion
    # ------------------------------------------------------------------

    @app.route('/api/v1/node/wallet/convert', methods=['POST'])
    @login_required
    def initiate_crypto_conversion():
        """Initiate a crypto conversion (BTC/ETH/etc → XRP/RLUSD)."""
        data = request.get_json()
        if not data:
            return jsonify({'error': 'JSON body required'}), 400

        source_currency = data.get('source_currency')
        source_amount = data.get('source_amount')

        if not source_currency or not source_amount:
            return jsonify({'error': 'source_currency and source_amount required'}), 400

        try:
            source_amount = float(source_amount)
        except (ValueError, TypeError):
            return jsonify({'error': 'source_amount must be a number'}), 400

        if source_amount <= 0:
            return jsonify({'error': 'source_amount must be positive'}), 400

        result = node_consent_economy.initiate_conversion(
            current_user.id,
            source_currency,
            source_amount,
        )
        if 'error' in result:
            return jsonify(result), 400

        return jsonify(result), 201

    # ------------------------------------------------------------------
    # 11. GET /api/v1/node/wallet/conversions — Conversion history
    # ------------------------------------------------------------------

    @app.route('/api/v1/node/wallet/conversions', methods=['GET'])
    @login_required
    def get_crypto_conversions():
        """Get crypto conversion history."""
        limit = min(int(request.args.get('limit', 20)), 100)
        result = node_consent_economy.get_conversion_history(current_user.id, limit=limit)
        return jsonify(result)

    # ------------------------------------------------------------------
    # 12. GET /admin/node-consent — Admin consent economy dashboard
    # ------------------------------------------------------------------

    @app.route('/admin/node-consent')
    @login_required
    def admin_node_consent_dashboard():
        """Admin dashboard for the consent economy."""
        if not current_user.is_admin:
            return jsonify({'error': 'Admin access required'}), 403

        dashboard = node_consent_economy.get_consent_economy_dashboard()

        # Return JSON for API consumption — template rendering done in server.py if needed
        return jsonify(dashboard)

    # ------------------------------------------------------------------
    # Extension-compatible endpoints (token auth)
    # ------------------------------------------------------------------

    @app.route('/api/v1/node/consent/ext', methods=['GET'])
    def get_node_consent_ext():
        """Get consent profile via helper token (for extension)."""
        user_id = _get_authenticated_user_id()
        if not user_id:
            return jsonify({'error': 'Authentication required'}), 401

        from models import NodeConsentProfile
        profile = NodeConsentProfile.query.filter_by(user_id=user_id).first()
        if not profile:
            profile = node_consent_economy.create_default_profile(user_id)

        return jsonify(profile.to_dict())

    @app.route('/api/v1/node/consent/ext', methods=['PUT'])
    def update_node_consent_ext():
        """Update consent via helper token (for extension)."""
        user_id = _get_authenticated_user_id()
        if not user_id:
            return jsonify({'error': 'Authentication required'}), 401

        data = request.get_json()
        if not data:
            return jsonify({'error': 'JSON body required'}), 400

        result = node_consent_economy.update_consent(user_id, data)
        if 'error' in result:
            return jsonify(result), 400

        return jsonify(result)

    logger.info("Node consent economy routes registered")
