"""
Payment Zone Compatibility API (Build #85)

Blueprint providing endpoints for:
- User payment compatibility checks
- Deal-specific payment assessment
- Interop group listing
- Admin rule management
"""

import json
import logging
from flask import Blueprint, jsonify, request
from functools import wraps

logger = logging.getLogger(__name__)

payment_compat_bp = Blueprint('payment_compat', __name__)


def _get_current_user():
    """Get the currently authenticated user, or None."""
    try:
        from flask_login import current_user
        if current_user and current_user.is_authenticated:
            return current_user
    except ImportError:
        pass
    return None


def _require_admin(f):
    """Decorator requiring admin access."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        user = _get_current_user()
        if not user or not getattr(user, 'is_admin', False):
            return jsonify({'error': 'Admin access required'}), 403
        return f(*args, **kwargs)
    return wrapper


# ---------------------------------------------------------------
# User-facing endpoints
# ---------------------------------------------------------------

@payment_compat_bp.route('/api/payment/compatibility')
def get_user_compatibility():
    """Get current user's reachable markets based on their payment instruments."""
    user = _get_current_user()
    if not user:
        return jsonify({'error': 'Authentication required'}), 401

    from payment_compatibility import payment_compat_engine

    vertical = request.args.get('vertical')
    min_acceptance = request.args.get('min_acceptance', 'medium')

    profile = payment_compat_engine.get_user_payment_profile(user.id)
    reachable = payment_compat_engine.get_reachable_countries(
        profile=profile, vertical=vertical, min_acceptance=min_acceptance
    )

    # Determine blocked countries
    from payment_compatibility import ALL_MARKET_COUNTRIES
    blocked = {}
    for country in ALL_MARKET_COUNTRIES:
        if country not in reachable:
            blocked[country] = 'No accepted payment method'

    return jsonify({
        'success': True,
        'payment_profile': {
            'cards': [
                {'brand': c['brand'], 'billing_country': c['billing_country'],
                 'last_four': c.get('last_four', '****')}
                for c in profile.cards
            ],
            'has_xrp_wallet': profile.has_xrp_wallet,
            'has_verified_wallet': profile.has_verified_wallet,
            'home_market': profile.home_market,
        },
        'reachable_countries': reachable,
        'reachable_count': len(reachable),
        'total_countries': len(ALL_MARKET_COUNTRIES),
        'blocked_countries': list(blocked.keys()),
        'blocked_reasons': blocked,
    })


@payment_compat_bp.route('/api/payment/compatibility/deal/<deal_type>/<deal_id>')
def get_deal_compatibility(deal_type, deal_id):
    """Check payment compatibility for a specific deal."""
    user = _get_current_user()
    if not user:
        return jsonify({'error': 'Authentication required'}), 401

    from payment_compatibility import payment_compat_engine

    # Load the deal to get its market
    deal = None
    vertical = deal_type

    try:
        if deal_type == 'flight':
            from models import Deal
            deal = Deal.query.filter_by(deal_id=deal_id).first()
        elif deal_type == 'hotel':
            from models import HotelDeal
            deal = HotelDeal.query.filter_by(hotel_deal_id=deal_id).first()
        elif deal_type == 'cruise':
            from models import CruiseDeal
            deal = CruiseDeal.query.filter_by(cruise_deal_id=deal_id).first()
        elif deal_type == 'rental':
            from models import RentalDeal
            deal = RentalDeal.query.filter_by(rental_deal_id=deal_id).first()
    except Exception as e:
        logger.warning("Error loading deal %s/%s: %s", deal_type, deal_id, e)

    if not deal:
        return jsonify({'error': 'Deal not found'}), 404

    market = getattr(deal, 'arbitrage_market', None) or 'US'

    compat = payment_compat_engine.assess_deal_compatibility(
        deal_market=market, user_id=user.id, vertical=vertical
    )

    return jsonify({
        'success': True,
        'deal_id': deal_id,
        'deal_type': deal_type,
        'arbitrage_market': market,
        'compatibility': compat,
    })


@payment_compat_bp.route('/api/payment/interop-groups')
def list_interop_groups():
    """List all active payment interoperability groups."""
    from models import PaymentInteropGroup

    groups = PaymentInteropGroup.query.filter_by(is_active=True).all()

    return jsonify({
        'success': True,
        'groups': [g.to_dict() for g in groups],
        'count': len(groups),
    })


@payment_compat_bp.route('/api/payment/market/<country_code>')
def get_market_info(country_code):
    """Get payment acceptance summary for a specific market."""
    from payment_compatibility import payment_compat_engine

    vertical = request.args.get('vertical')
    summary = payment_compat_engine.get_market_payment_summary(
        country_code, vertical=vertical
    )

    return jsonify({
        'success': True,
        **summary,
    })


# ---------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------

@payment_compat_bp.route('/api/admin/payment/rules', methods=['GET'])
@_require_admin
def list_rules():
    """List all payment zone rules with optional filters."""
    from models import PaymentZoneRule

    query = PaymentZoneRule.query

    payment_type = request.args.get('payment_type')
    if payment_type:
        query = query.filter_by(payment_type=payment_type)

    merchant_country = request.args.get('merchant_country')
    if merchant_country:
        query = query.filter(
            (PaymentZoneRule.merchant_country == merchant_country) |
            (PaymentZoneRule.merchant_country == '*')
        )

    active_only = request.args.get('active_only', 'true').lower() == 'true'
    if active_only:
        query = query.filter_by(is_active=True)

    rules = query.order_by(PaymentZoneRule.payment_type, PaymentZoneRule.merchant_country).all()

    return jsonify({
        'success': True,
        'rules': [r.to_dict() for r in rules],
        'count': len(rules),
    })


@payment_compat_bp.route('/api/admin/payment/rules', methods=['POST'])
@_require_admin
def create_rule():
    """Create or update a payment zone rule."""
    from models import db, PaymentZoneRule
    from payment_compatibility import payment_compat_engine

    data = request.get_json()
    if not data:
        return jsonify({'error': 'JSON body required'}), 400

    required = ['payment_type', 'issuing_country', 'merchant_country', 'acceptance_level']
    for field in required:
        if field not in data:
            return jsonify({'error': f'Missing required field: {field}'}), 400

    if data['acceptance_level'] not in ('high', 'medium', 'low', 'none'):
        return jsonify({'error': 'acceptance_level must be high, medium, low, or none'}), 400

    rule = PaymentZoneRule(
        payment_type=data['payment_type'],
        issuing_country=data['issuing_country'],
        merchant_country=data['merchant_country'],
        acceptance_level=data['acceptance_level'],
        vertical=data.get('vertical'),
        notes=data.get('notes'),
    )
    db.session.add(rule)
    db.session.commit()

    payment_compat_engine.invalidate_cache()

    return jsonify({
        'success': True,
        'rule': rule.to_dict(),
    }), 201


@payment_compat_bp.route('/api/admin/payment/rules/<int:rule_id>', methods=['DELETE'])
@_require_admin
def deactivate_rule(rule_id):
    """Deactivate a payment zone rule."""
    from models import db, PaymentZoneRule
    from payment_compatibility import payment_compat_engine

    rule = PaymentZoneRule.query.get(rule_id)
    if not rule:
        return jsonify({'error': 'Rule not found'}), 404

    rule.is_active = False
    db.session.commit()

    payment_compat_engine.invalidate_cache()

    return jsonify({
        'success': True,
        'deactivated': rule.to_dict(),
    })


@payment_compat_bp.route('/api/admin/payment/interop-groups', methods=['POST'])
@_require_admin
def create_interop_group():
    """Create or update a payment interop group."""
    from models import db, PaymentInteropGroup
    from payment_compatibility import payment_compat_engine

    data = request.get_json()
    if not data:
        return jsonify({'error': 'JSON body required'}), 400

    required = ['group_code', 'group_name', 'countries', 'payment_types']
    for field in required:
        if field not in data:
            return jsonify({'error': f'Missing required field: {field}'}), 400

    # Upsert by group_code
    existing = PaymentInteropGroup.query.filter_by(group_code=data['group_code']).first()
    if existing:
        existing.group_name = data['group_name']
        existing.description = data.get('description', '')
        existing.countries = json.dumps(data['countries'])
        existing.payment_types = json.dumps(data['payment_types'])
        existing.default_acceptance = data.get('default_acceptance', 'high')
        group = existing
    else:
        group = PaymentInteropGroup(
            group_code=data['group_code'],
            group_name=data['group_name'],
            description=data.get('description', ''),
            countries=json.dumps(data['countries']),
            payment_types=json.dumps(data['payment_types']),
            default_acceptance=data.get('default_acceptance', 'high'),
        )
        db.session.add(group)

    db.session.commit()
    payment_compat_engine.invalidate_cache()

    return jsonify({
        'success': True,
        'group': group.to_dict(),
    }), 201


# ===================================================================
# Payment Ramp Network endpoints (Build #86)
# ===================================================================

@payment_compat_bp.route('/api/payment/zone-availability')
def get_zone_availability():
    """Get current user's zone availability summary for wallet UI.

    Returns per-interop-group coverage, FX estimates, and reachable country counts.
    Works for both arbitrage and free browsing/shopping.
    """
    user = _get_current_user()
    if not user:
        return jsonify({'error': 'Authentication required'}), 401

    try:
        from payment_compatibility import payment_compat_engine
        summary = payment_compat_engine.get_zone_availability_summary(user.id)
        return jsonify({'success': True, 'zones': summary})
    except Exception as e:
        logger.error("Zone availability error: %s", e)
        return jsonify({'success': False, 'error': str(e)}), 500


@payment_compat_bp.route('/api/payment/ramps')
def get_ramp_recommendations():
    """Get recommended on-ramp providers for the current user.

    Returns providers sorted by priority for the user's home market,
    with fee estimates and availability status.
    """
    user = _get_current_user()
    if not user:
        return jsonify({'error': 'Authentication required'}), 401

    try:
        from payment_ramps import ramp_engine
        ramps = ramp_engine.get_recommended_ramps(user.id)
        return jsonify({'success': True, 'ramps': ramps})
    except ImportError:
        return jsonify({'success': False, 'error': 'Payment ramps module not available'}), 500
    except Exception as e:
        logger.error("Ramp recommendations error: %s", e)
        return jsonify({'success': False, 'error': str(e)}), 500


@payment_compat_bp.route('/api/payment/ramps/<provider_code>/widget-url')
def get_ramp_widget_url(provider_code):
    """Generate a widget URL for a specific ramp provider.

    Query params: crypto (default USDC), fiat (default user's preferred), amount
    """
    user = _get_current_user()
    if not user:
        return jsonify({'error': 'Authentication required'}), 401

    try:
        from payment_ramps import ramp_engine

        wallet_address = getattr(user, 'xrpl_wallet_address', '') or ''
        params = {
            'wallet_address': wallet_address,
            'crypto_currency': request.args.get('crypto', 'USDC'),
            'fiat_currency': request.args.get('fiat', getattr(user, 'preferred_currency', 'USD') or 'USD'),
            'fiat_amount': request.args.get('amount'),
        }

        url = ramp_engine.generate_widget_url(provider_code, params)
        if not url:
            return jsonify({'error': 'Provider not available or not configured'}), 404

        cost = ramp_engine.estimate_ramp_cost(
            provider_code,
            float(params['fiat_amount']) if params['fiat_amount'] else 100.0,
        )

        return jsonify({
            'success': True,
            'widget_url': url,
            'provider': provider_code,
            'cost_estimate': cost,
        })
    except ImportError:
        return jsonify({'success': False, 'error': 'Payment ramps module not available'}), 500
    except Exception as e:
        logger.error("Widget URL error: %s", e)
        return jsonify({'success': False, 'error': str(e)}), 500
