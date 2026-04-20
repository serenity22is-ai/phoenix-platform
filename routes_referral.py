"""
Build #233 — Referral Attribution Chain + Conversion Tracking

2-level attribution: ref= (direct sharer, earns points) + src= (upstream B2B, earns commission).
Conversion funnel: click → signup → first_search → first_booking → subscription.
Points/commission awarded at each milestone.

Endpoints:
  POST  /api/referral/track-click          — record a referral click (no auth)
  GET   /api/referral/resolve              — resolve ref + src codes to display names (no auth)
  POST  /api/referral/attribute            — record a conversion event (auth required)
  GET   /api/referral/my-stats             — current user's referral dashboard
  GET   /api/referral/my-conversions       — current user's conversion events list
  GET   /api/admin/referral/leaderboard    — admin: top referrers by conversions

Registration: register_referral_routes(app, csrf, limiter)
"""

import hashlib
import json
import logging
from datetime import datetime, timezone, timedelta

from flask import request, jsonify, current_app
from flask_login import current_user, login_required

from models import (
    db, User, CommercialAccount, FeatureFlag, ConsumerReferral,
    ReferralClick, ConversionEvent, InviteLink, Booking, RewardsAccount,
)

logger = logging.getLogger(__name__)

# ── Points awarded per conversion milestone (config overrides) ──
_DEFAULT_POINTS = {
    'signup': 2000,
    'first_search': 500,
    'first_booking': 5000,
    'subscription': 10000,
}


def _check_flag():
    """Return error response if referral_attribution flag is disabled."""
    if not FeatureFlag.is_flag_enabled('referral_attribution'):
        return jsonify({
            'status': 'error',
            'error': 'Feature "referral_attribution" is not enabled',
        }), 403
    return None


def _utcnow():
    return datetime.now(timezone.utc)


def _hash_visitor(ip, user_agent):
    """Create a privacy-safe visitor fingerprint for 24h dedup."""
    raw = f"{ip or ''}:{user_agent or ''}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _resolve_referral_code(code):
    """Return (owner_type, owner_id, owner_name) for a referral code."""
    if not code:
        return None, None, None
    # Check consumer user first
    user = User.query.filter_by(referral_code=code).first()
    if user:
        return 'user', user.id, user.name
    # Check B2B account
    acct = CommercialAccount.query.filter_by(referral_code=code).first()
    if acct:
        return 'b2b', acct.id, acct.name
    return None, None, None


def _get_points_for(event_type):
    """Get point award for an event type from config."""
    config_map = {
        'signup': 'REFERRAL_SIGNUP_POINTS',
        'first_search': 'REFERRAL_FIRST_SEARCH_POINTS',
        'first_booking': 'REFERRAL_FIRST_BOOKING_POINTS',
        'subscription': 'REFERRAL_TRAVEL_PLUS_POINTS',
    }
    config_key = config_map.get(event_type)
    if config_key:
        return current_app.config.get(config_key, _DEFAULT_POINTS.get(event_type, 0))
    return _DEFAULT_POINTS.get(event_type, 0)


def register_referral_routes(app, csrf, limiter):
    """Register referral attribution routes (Build #233)."""

    # ──────────────────────────────────────────────
    # TRACK CLICK (no auth — visitors aren't signed in)
    # ──────────────────────────────────────────────

    @app.route('/api/referral/track-click', methods=['POST'])
    @csrf.exempt
    def referral_track_click():
        """Record a referral click.

        Called when someone visits any page with ?ref= or ?src= params.
        Deduplicates within a 24h window per visitor hash + referral code.
        """
        blocked = _check_flag()
        if blocked:
            return blocked

        data = request.get_json(silent=True) or {}
        ref_code = (data.get('ref') or '').strip()
        src_code = (data.get('src') or '').strip()

        if not ref_code:
            return jsonify({'status': 'error', 'error': 'ref code required'}), 400

        # Validate ref code exists
        ref_type, ref_id, _ = _resolve_referral_code(ref_code)
        if not ref_type:
            return jsonify({'status': 'error', 'error': 'Unknown referral code'}), 404

        # Visitor fingerprint for dedup
        ip = request.remote_addr
        ua = request.headers.get('User-Agent', '')
        v_hash = _hash_visitor(ip, ua)

        # Dedup: same visitor + same code within 24h
        cutoff = _utcnow() - timedelta(hours=24)
        existing = ReferralClick.query.filter(
            ReferralClick.referral_code == ref_code,
            ReferralClick.visitor_hash == v_hash,
            ReferralClick.created_at > cutoff,
        ).first()
        if existing:
            return jsonify({'status': 'ok', 'click_id': existing.id, 'deduplicated': True})

        click = ReferralClick(
            referral_code=ref_code,
            upstream_b2b_code=src_code or None,
            source_type=data.get('source_type'),
            source_id=data.get('source_id'),
            landing_url=data.get('landing_url', '')[:500],
            visitor_hash=v_hash,
            ip_country=data.get('ip_country'),
        )
        db.session.add(click)
        db.session.commit()

        # Also increment click_count on InviteLink if source is invite_link
        if data.get('source_type') == 'invite_link' and data.get('source_id'):
            link = InviteLink.query.get(data['source_id'])
            if link:
                link.click_count = (link.click_count or 0) + 1
                db.session.commit()

        logger.info("Referral click recorded: ref=%s src=%s", ref_code, src_code)
        return jsonify({'status': 'ok', 'click_id': click.id, 'deduplicated': False})

    # ──────────────────────────────────────────────
    # RESOLVE (no auth — used by landing pages)
    # ──────────────────────────────────────────────

    @app.route('/api/referral/resolve', methods=['GET'])
    def referral_resolve():
        """Resolve ref + src codes to display names.

        Used by landing pages to show "Referred by Jake" banners.
        """
        blocked = _check_flag()
        if blocked:
            return blocked

        ref_code = request.args.get('ref', '').strip()
        src_code = request.args.get('src', '').strip()

        result = {}
        if ref_code:
            rtype, rid, rname = _resolve_referral_code(ref_code)
            result['ref'] = {
                'code': ref_code,
                'type': rtype,
                'name': rname,
            } if rtype else None

        if src_code:
            stype, sid, sname = _resolve_referral_code(src_code)
            result['src'] = {
                'code': src_code,
                'type': stype,
                'name': sname,
            } if stype else None

        return jsonify({'status': 'ok', **result})

    # ──────────────────────────────────────────────
    # ATTRIBUTE CONVERSION (auth required)
    # ──────────────────────────────────────────────

    @app.route('/api/referral/attribute', methods=['POST'])
    @login_required
    def referral_attribute():
        """Record a conversion event in the referral funnel.

        Called by internal flows (signup, first search, booking, subscription).
        Deduplicates: one event per (code, user, event_type).
        Awards points to the referrer and optionally B2B commission.
        """
        blocked = _check_flag()
        if blocked:
            return blocked

        data = request.get_json(silent=True) or {}
        ref_code = (data.get('ref') or '').strip()
        event_type = (data.get('event_type') or '').strip()

        if not ref_code:
            return jsonify({'status': 'error', 'error': 'ref code required'}), 400
        if event_type not in ConversionEvent.EVENT_TYPES:
            return jsonify({
                'status': 'error',
                'error': f'Invalid event_type. Must be one of: {", ".join(ConversionEvent.EVENT_TYPES)}',
            }), 400

        # Can't self-refer
        referrer = User.query.filter_by(referral_code=ref_code).first()
        if referrer and referrer.id == current_user.id:
            return jsonify({'status': 'error', 'error': 'Cannot self-refer'}), 400

        # Dedup check
        existing = ConversionEvent.query.filter_by(
            referral_code=ref_code,
            user_id=current_user.id,
            event_type=event_type,
        ).first()
        if existing:
            return jsonify({
                'status': 'ok',
                'event': existing.to_dict(),
                'deduplicated': True,
            })

        # Build event
        src_code = (data.get('src') or '').strip() or None
        points = _get_points_for(event_type)

        event = ConversionEvent(
            referral_code=ref_code,
            upstream_b2b_code=src_code,
            user_id=current_user.id,
            event_type=event_type,
            booking_id=data.get('booking_id'),
            click_id=data.get('click_id'),
            points_awarded=points,
            commission_usd=0.0,  # B2B commission calculated separately
        )
        db.session.add(event)

        # Award points to the referrer (if user) via RewardsAccount
        if referrer and points > 0:
            ra = RewardsAccount.query.filter_by(user_id=referrer.id).first()
            if not ra:
                ra = RewardsAccount(user_id=referrer.id, points_balance=0, lifetime_earned=0)
                db.session.add(ra)
            ra.points_balance = (ra.points_balance or 0) + points
            ra.lifetime_earned = (ra.lifetime_earned or 0) + points

            # Update ConsumerReferral milestones if exists
            cr = ConsumerReferral.query.filter_by(
                referrer_id=referrer.id,
                referee_id=current_user.id,
            ).first()
            if cr:
                if event_type == 'signup' and not cr.signup_rewarded:
                    cr.signup_rewarded = True
                    cr.total_points_awarded = (cr.total_points_awarded or 0) + points
                elif event_type == 'first_booking' and not cr.first_booking_rewarded:
                    cr.first_booking_rewarded = True
                    cr.total_points_awarded = (cr.total_points_awarded or 0) + points
                elif event_type == 'subscription' and not cr.travel_plus_rewarded:
                    cr.travel_plus_rewarded = True
                    cr.total_points_awarded = (cr.total_points_awarded or 0) + points

        # Link back to the most recent click for this code + user (if any)
        if not event.click_id:
            recent_click = ReferralClick.query.filter_by(
                referral_code=ref_code,
                converted_user_id=current_user.id,
            ).order_by(ReferralClick.created_at.desc()).first()
            if not recent_click:
                # Try unlinked clicks (converted_user_id is NULL) — grab latest for this code
                recent_click = ReferralClick.query.filter(
                    ReferralClick.referral_code == ref_code,
                    ReferralClick.converted_user_id.is_(None),
                ).order_by(ReferralClick.created_at.desc()).first()
                if recent_click:
                    recent_click.converted_user_id = current_user.id
            if recent_click:
                event.click_id = recent_click.id

        db.session.commit()

        logger.info("Conversion event: ref=%s user=%s type=%s pts=%d",
                     ref_code, current_user.id, event_type, points)
        return jsonify({
            'status': 'ok',
            'event': event.to_dict(),
            'deduplicated': False,
        })

    # ──────────────────────────────────────────────
    # MY STATS (referrer dashboard)
    # ──────────────────────────────────────────────

    @app.route('/api/referral/my-stats', methods=['GET'])
    @login_required
    def referral_my_stats():
        """Current user's referral dashboard: clicks, funnel, points earned."""
        blocked = _check_flag()
        if blocked:
            return blocked

        code = current_user.referral_code
        if not code:
            return jsonify({
                'status': 'ok',
                'referral_code': None,
                'total_clicks': 0,
                'funnel': {},
                'total_points_earned': 0,
                'total_commission_usd': 0.0,
            })

        # Click stats
        total_clicks = ReferralClick.query.filter_by(referral_code=code).count()
        unique_visitors = db.session.query(
            db.func.count(db.func.distinct(ReferralClick.visitor_hash))
        ).filter(ReferralClick.referral_code == code).scalar() or 0

        # Funnel counts
        funnel = {}
        for etype in ConversionEvent.EVENT_TYPES:
            funnel[etype] = ConversionEvent.query.filter_by(
                referral_code=code, event_type=etype
            ).count()

        # Total points & commission
        total_points = db.session.query(
            db.func.coalesce(db.func.sum(ConversionEvent.points_awarded), 0)
        ).filter(ConversionEvent.referral_code == code).scalar()

        total_commission = db.session.query(
            db.func.coalesce(db.func.sum(ConversionEvent.commission_usd), 0)
        ).filter(ConversionEvent.referral_code == code).scalar()

        # Recent conversions (last 10)
        recent = ConversionEvent.query.filter_by(referral_code=code)\
            .order_by(ConversionEvent.created_at.desc()).limit(10).all()

        return jsonify({
            'status': 'ok',
            'referral_code': code,
            'total_clicks': total_clicks,
            'unique_visitors': unique_visitors,
            'funnel': funnel,
            'total_points_earned': total_points,
            'total_commission_usd': float(total_commission),
            'recent_conversions': [e.to_dict() for e in recent],
        })

    # ──────────────────────────────────────────────
    # MY CONVERSIONS (list)
    # ──────────────────────────────────────────────

    @app.route('/api/referral/my-conversions', methods=['GET'])
    @login_required
    def referral_my_conversions():
        """List conversion events for the current user's referral code."""
        blocked = _check_flag()
        if blocked:
            return blocked

        code = current_user.referral_code
        if not code:
            return jsonify({'status': 'ok', 'conversions': [], 'total': 0})

        page = request.args.get('page', 1, type=int)
        per_page = min(request.args.get('per_page', 20, type=int), 100)

        query = ConversionEvent.query.filter_by(referral_code=code)\
            .order_by(ConversionEvent.created_at.desc())
        total = query.count()
        events = query.offset((page - 1) * per_page).limit(per_page).all()

        return jsonify({
            'status': 'ok',
            'conversions': [e.to_dict() for e in events],
            'total': total,
            'page': page,
            'per_page': per_page,
        })

    # ──────────────────────────────────────────────
    # ADMIN LEADERBOARD
    # ──────────────────────────────────────────────

    @app.route('/api/admin/referral/leaderboard', methods=['GET'])
    @login_required
    def referral_admin_leaderboard():
        """Admin view: top referrers by total conversion events."""
        blocked = _check_flag()
        if blocked:
            return blocked

        if not getattr(current_user, 'is_admin', False):
            return jsonify({'status': 'error', 'error': 'Admin required'}), 403

        limit = min(request.args.get('limit', 20, type=int), 100)
        event_filter = request.args.get('event_type')  # optional filter

        query = db.session.query(
            ConversionEvent.referral_code,
            db.func.count(ConversionEvent.id).label('event_count'),
            db.func.coalesce(db.func.sum(ConversionEvent.points_awarded), 0).label('total_points'),
        ).group_by(ConversionEvent.referral_code)

        if event_filter and event_filter in ConversionEvent.EVENT_TYPES:
            query = query.filter(ConversionEvent.event_type == event_filter)

        rows = query.order_by(db.text('event_count DESC')).limit(limit).all()

        leaderboard = []
        for code, count, points in rows:
            rtype, rid, rname = _resolve_referral_code(code)
            leaderboard.append({
                'referral_code': code,
                'owner_type': rtype,
                'owner_name': rname,
                'event_count': count,
                'total_points': points,
            })

        # Summary stats
        total_clicks = ReferralClick.query.count()
        total_conversions = ConversionEvent.query.count()
        total_signups = ConversionEvent.query.filter_by(event_type='signup').count()
        total_bookings = ConversionEvent.query.filter_by(event_type='first_booking').count()

        return jsonify({
            'status': 'ok',
            'leaderboard': leaderboard,
            'summary': {
                'total_clicks': total_clicks,
                'total_conversions': total_conversions,
                'total_signups': total_signups,
                'total_bookings': total_bookings,
            },
        })
