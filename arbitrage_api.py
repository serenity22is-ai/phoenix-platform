"""
REST API routes for the universal arbitrage search system.

Provides the universal search endpoint and commercial agent API.
Vertical-specific browse endpoints (hotel, cruise, rental, package)
removed in Build #89 — Google-native architecture.
"""

import logging
from flask import Blueprint, request, jsonify
from flask_login import current_user, login_required

from arbitrage_search import ArbitrageSearchEngine, arbitrage_engine
from models import db, Deal
from node_consent_economy import node_consent_economy

logger = logging.getLogger(__name__)

arbitrage_bp = Blueprint('arbitrage', __name__)


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def _validate_api_key():
    """Validate the X-API-Key header. Returns None if valid, or an error response."""
    api_key = request.headers.get('X-API-Key')
    if not api_key:
        return jsonify({'success': False, 'error': 'Missing X-API-Key header'}), 401
    # Delegate actual key validation to the node consent economy layer
    if not node_consent_economy.validate_api_key(api_key):
        return jsonify({'success': False, 'error': 'Invalid API key'}), 403
    return None


# ---------------------------------------------------------------------------
# 1. POST /api/search/arbitrage  -- Universal search
# ---------------------------------------------------------------------------

@arbitrage_bp.route('/api/search/arbitrage', methods=['POST'])
def search_arbitrage():
    """Universal arbitrage search across all deal verticals."""
    try:
        data = request.get_json(silent=True) or {}
        query = data.get('query', '').strip()
        if not query:
            return jsonify({'success': False, 'error': 'Missing required field: query'}), 400

        home_market = data.get('home_market', 'US')

        user_id = None
        if current_user and current_user.is_authenticated:
            user_id = current_user.id

        results = arbitrage_engine.search(query, user_id, home_market)

        # Record platform activity for authenticated users
        if user_id is not None:
            try:
                node_consent_economy.record_activity(
                    user_id=user_id,
                    activity_type='arbitrage_search',
                    metadata={'query': query, 'home_market': home_market}
                )
            except Exception as exc:
                logger.warning('Failed to record platform activity: %s', exc)

        deals_count = results.get('deals_count', 0) if isinstance(results, dict) else 0

        return jsonify({
            'success': True,
            'vertical': results.get('vertical', 'unknown') if isinstance(results, dict) else 'unknown',
            'query': query,
            'results': results,
            'deals_count': deals_count
        })

    except Exception as exc:
        logger.exception('Error in search_arbitrage: %s', exc)
        return jsonify({'success': False, 'error': 'Internal server error'}), 500


# ---------------------------------------------------------------------------
# 2. POST /api/v1/agent/search/arbitrage  -- Commercial API
# ---------------------------------------------------------------------------

@arbitrage_bp.route('/api/v1/agent/search/arbitrage', methods=['POST'])
def agent_search_arbitrage():
    """Commercial / agent arbitrage search endpoint (requires API key)."""
    try:
        auth_error = _validate_api_key()
        if auth_error is not None:
            return auth_error

        data = request.get_json(silent=True) or {}
        query = data.get('query', '').strip()
        if not query:
            return jsonify({'success': False, 'error': 'Missing required field: query'}), 400

        home_market = data.get('home_market', 'US')

        # For commercial API the user_id comes from the API key context
        api_key = request.headers.get('X-API-Key')
        agent_user_id = data.get('user_id')

        results = arbitrage_engine.search(query, agent_user_id, home_market)

        # Record commercial activity
        try:
            node_consent_economy.record_activity(
                user_id=agent_user_id,
                activity_type='commercial_arbitrage_search',
                metadata={
                    'query': query,
                    'home_market': home_market,
                    'api_key': api_key[:8] + '...' if api_key and len(api_key) > 8 else api_key
                }
            )
        except Exception as exc:
            logger.warning('Failed to record commercial platform activity: %s', exc)

        deals_count = results.get('deals_count', 0) if isinstance(results, dict) else 0

        return jsonify({
            'success': True,
            'vertical': results.get('vertical', 'unknown') if isinstance(results, dict) else 'unknown',
            'query': query,
            'results': results,
            'deals_count': deals_count
        })

    except Exception as exc:
        logger.exception('Error in agent_search_arbitrage: %s', exc)
        return jsonify({'success': False, 'error': 'Internal server error'}), 500
