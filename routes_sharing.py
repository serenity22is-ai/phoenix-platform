"""
Build #219 — Universal Share System Routes

One short URL pattern /i/<token> resolves to different content types.
Every shareable surface in MYSTES uses InviteLink.

Endpoints:
- GET  /i/<token>              — resolve + render shared content
- POST /api/share/create       — create a share link
- GET  /api/share/my-links     — list user's share links
- POST /api/share/<token>/revoke — deactivate a link
- GET  /api/share/<token>/stats  — analytics for a link

Registration: register_sharing_routes(app, csrf, limiter)
"""

import logging
import secrets
from datetime import datetime, timezone

from flask import request, jsonify, render_template_string, redirect, session
from flask_login import current_user, login_required

from models import db, InviteLink, User, Deal, TripPlan, Collection

logger = logging.getLogger(__name__)


def _utcnow():
    return datetime.now(timezone.utc)


def _gen_token():
    """Generate a URL-safe token (8-10 chars)."""
    return secrets.token_urlsafe(6)  # 8 chars


# ============================================================
# OG Meta Generators (per link_type)
# ============================================================

def _build_og_meta(invite, resolved_object=None):
    """Build OG meta tags for social previews based on link type."""
    # Use override if set
    if invite.og_title:
        return invite.og_meta()

    og = {
        'og:type': 'website',
        'og:site_name': 'MYSTES',
        'og:url': f'/i/{invite.token}',
        'og:image': '/static/icons/icon-512x512.png',
    }

    if invite.link_type == 'flight' and resolved_object:
        deal = resolved_object
        og['og:title'] = f'{getattr(deal, "origin", "?")} to {getattr(deal, "destination", "?")} — MYSTES'
        savings = getattr(deal, 'user_savings_usd', 0) or 0
        if savings > 0:
            og['og:description'] = f'Save ${savings:.0f} on this flight. Book through MYSTES.'
        else:
            og['og:description'] = 'Find cheaper flights through MYSTES.'

    elif invite.link_type == 'trip_invite' and resolved_object:
        trip = resolved_object
        og['og:title'] = f"You're invited: {getattr(trip, 'name', 'Trip')} — MYSTES"
        og['og:description'] = 'Join this trip and plan together on MYSTES.'

    elif invite.link_type == 'trip_view' and resolved_object:
        trip = resolved_object
        og['og:title'] = f'{getattr(trip, "name", "Trip")} — MYSTES'
        og['og:description'] = 'View this trip itinerary on MYSTES.'

    elif invite.link_type == 'referral':
        sender = db.session.get(User, invite.sender_user_id)
        name = sender.name if sender else 'A friend'
        og['og:title'] = f'{name} invited you to MYSTES'
        og['og:description'] = 'AI-powered travel intelligence. Find cheaper flights through MYSTES.'

    elif invite.link_type == 'collection' and resolved_object:
        col = resolved_object
        og['og:title'] = f'{getattr(col, "name", "Collection")} — MYSTES'
        og['og:description'] = 'Browse this curated travel collection on MYSTES.'

    elif invite.link_type == 'settle_up':
        og['og:title'] = 'Pay Your Share — MYSTES'
        og['og:description'] = 'A friend is requesting payment for a shared trip.'

    elif invite.link_type == 'event_registration':
        og['og:title'] = 'Event Registration — MYSTES'
        og['og:description'] = 'Register for this event on MYSTES.'

    else:
        og['og:title'] = 'MYSTES — AI-Powered Travel Intelligence'
        og['og:description'] = 'Find cheaper flights through MYSTES.'

    return og


def _resolve_object(invite):
    """Resolve the polymorphic object_id to an actual model instance."""
    try:
        if invite.link_type in ('flight', 'hotel'):
            return db.session.get(Deal, invite.object_id)
        elif invite.link_type in ('trip_invite', 'trip_view', 'itinerary'):
            return db.session.get(TripPlan, invite.object_id)
        elif invite.link_type == 'collection':
            return db.session.get(Collection, invite.object_id)
        # Other types resolved as needed in future builds
    except Exception:
        pass
    return None


# ============================================================
# Share Link Landing Page Template
# ============================================================

SHARE_LANDING_CONTENT = '''
<style>
    .share-wrap { min-height: calc(100vh - 80px); padding: 40px 20px 60px; max-width: 700px; margin: 0 auto; text-align: center; }
    .share-quote { font-size: 14px; color: var(--text-bright); background: var(--glass-bg-light); padding: 16px; border-radius: var(--radius-md); margin-bottom: 20px; font-style: italic; }
    .share-detail { font-size: 14px; color: var(--text-secondary); margin: 4px 0; }
    .share-footer { font-size: 13px; color: var(--text-muted); margin-top: 16px; }
</style>

<div class="share-wrap">
    {% if expired %}
        <div class="mystes-empty">
            <div class="mystes-empty-icon">🔗</div>
            <h2 style="font-family:var(--font-brand);letter-spacing:3px;margin:0 0 8px;">LINK EXPIRED</h2>
            <p>This share link is no longer active.</p>
            <a href="/" class="mystes-btn mystes-btn-gold mystes-btn-lg" style="margin-top:16px;">EXPLORE MYSTES</a>
        </div>
    {% else %}
        <div class="mystes-card" style="text-align:left;margin:24px 0;padding:32px;">
            <div class="mystes-page-header" style="text-align:left;padding:0 0 8px;">
                <h1>{{ title }}</h1>
                <p style="margin-bottom:24px;">{{ subtitle }}</p>
            </div>
            {% if message %}
                <div class="share-quote">"{{ message }}"</div>
            {% endif %}
            {% if details %}
                {% for key, val in details.items() %}
                    <p class="share-detail"><strong>{{ key }}:</strong> {{ val }}</p>
                {% endfor %}
            {% endif %}
            <div class="text-center" style="margin-top:24px;">
                <a href="{{ cta_url }}" class="mystes-btn mystes-btn-gold mystes-btn-lg">{{ cta_text }}</a>
            </div>
            <p class="share-footer">Shared via MYSTES</p>
        </div>
    {% endif %}
</div>
'''


# ============================================================
# Route Registration
# ============================================================

def register_sharing_routes(app, csrf, limiter):
    """Register all sharing/InviteLink routes on the Flask app."""
    from server import BASE_TEMPLATE

    # ----------------------------------------------------------
    # GET /i/<token> — resolve and render shared content
    # ----------------------------------------------------------
    @app.route('/i/<token>')
    def resolve_invite_link(token):
        invite = InviteLink.query.filter_by(token=token).first()
        if not invite or not invite.is_valid():
            return render_template_string(
                BASE_TEMPLATE,
                title='Link Expired',
                content=render_template_string(SHARE_LANDING_CONTENT, expired=True),
            ), 404

        # Track click
        invite.record_click()
        db.session.commit()

        # Apply referral attribution
        if invite.referral_code:
            session['referral_source'] = invite.referral_code
        if invite.upstream_b2b_code:
            session['b2b_source'] = invite.upstream_b2b_code

        # Resolve the linked object
        obj = _resolve_object(invite)
        og_meta = _build_og_meta(invite, obj)

        # Build landing page content based on link_type
        title = og_meta.get('og:title', 'MYSTES')
        subtitle = og_meta.get('og:description', '')
        details = {}
        cta_text = 'EXPLORE MYSTES'
        cta_url = '/'

        if invite.link_type == 'flight' and obj:
            details = {
                'Route': f'{obj.origin} → {obj.destination}',
                'Airline': obj.airline or 'Multiple',
                'Date': str(obj.departure_date) if obj.departure_date else 'Flexible',
            }
            if invite.show_prices and obj.user_savings_usd and obj.user_savings_usd > 0:
                details['Savings'] = f'${obj.user_savings_usd:.0f} off Google price'
            cta_text = 'SEARCH THIS ROUTE'
            cta_url = f'/flights?origin={obj.origin}&destination={obj.destination}'

        elif invite.link_type == 'trip_invite' and obj:
            details = {'Trip': obj.name, 'Status': obj.status or 'Planning'}
            cta_text = 'JOIN THIS TRIP'
            cta_url = f'/trips'

        elif invite.link_type == 'trip_view' and obj:
            details = {'Trip': obj.name}
            cta_text = 'CREATE YOUR OWN TRIP'
            cta_url = '/trips'

        elif invite.link_type == 'referral':
            cta_text = 'SEARCH FLIGHTS WITH DISCOUNT'
            cta_url = '/flights'

        elif invite.link_type == 'collection' and obj:
            details = {'Collection': obj.name}
            cta_text = 'BROWSE COLLECTION'
            cta_url = '/'

        elif invite.link_type == 'settle_up':
            cta_text = 'PAY YOUR SHARE'
            cta_url = '/trips'

        elif invite.link_type == 'event_registration':
            cta_text = 'REGISTER NOW'
            cta_url = '/trips'

        rendered = render_template_string(
            SHARE_LANDING_CONTENT,
            expired=False,
            title=title.replace(' — MYSTES', ''),
            subtitle=subtitle,
            message=invite.message,
            details=details,
            cta_text=cta_text,
            cta_url=cta_url,
        )

        # Inject OG meta into head
        og_tags = '\n'.join(
            f'<meta property="{k}" content="{v}">'
            for k, v in og_meta.items()
        )

        return render_template_string(
            BASE_TEMPLATE,
            title=title,
            content=rendered,
            extra_head=og_tags,
        )

    # ----------------------------------------------------------
    # POST /api/share/create — create a share link
    # ----------------------------------------------------------
    @app.route('/api/share/create', methods=['POST'])
    @login_required
    def create_share_link():
        data = request.get_json(silent=True) or {}

        link_type = data.get('link_type', '')
        if link_type not in InviteLink.LINK_TYPES:
            return jsonify({'status': 'error', 'error': f'Invalid link_type. Valid: {", ".join(InviteLink.LINK_TYPES)}'}), 400

        object_id = data.get('object_id')
        if object_id is None:
            return jsonify({'status': 'error', 'error': 'object_id required'}), 400

        permissions = data.get('permissions', 'view_only')
        if permissions not in InviteLink.PERMISSIONS:
            permissions = 'view_only'

        # Auto-embed user's referral code
        referral_code = getattr(current_user, 'referral_code', None)
        # Check if user was originally from a B2B
        upstream_b2b = getattr(current_user, 'referral_code_used', None)

        invite = InviteLink(
            token=_gen_token(),
            link_type=link_type,
            object_id=int(object_id),
            sender_user_id=current_user.id,
            recipient_email=data.get('recipient_email'),
            permissions=permissions,
            show_prices=data.get('show_prices', True),
            message=data.get('message', '').strip() or None,
            referral_code=referral_code,
            upstream_b2b_code=upstream_b2b,
            og_title=data.get('og_title'),
            og_description=data.get('og_description'),
            og_image_url=data.get('og_image_url'),
            expires_at=None,  # No expiry by default
        )
        db.session.add(invite)
        db.session.commit()

        return jsonify({
            'status': 'ok',
            'link': invite.to_dict(),
            'full_url': f'/i/{invite.token}',
        })

    # ----------------------------------------------------------
    # GET /api/share/my-links — list user's share links
    # ----------------------------------------------------------
    @app.route('/api/share/my-links')
    @login_required
    def my_share_links():
        links = InviteLink.query.filter_by(
            sender_user_id=current_user.id
        ).order_by(InviteLink.created_at.desc()).limit(50).all()

        return jsonify({
            'status': 'ok',
            'links': [l.to_dict() for l in links],
            'count': len(links),
        })

    # ----------------------------------------------------------
    # POST /api/share/<token>/revoke — deactivate a link
    # ----------------------------------------------------------
    @app.route('/api/share/<token>/revoke', methods=['POST'])
    @login_required
    def revoke_share_link(token):
        invite = InviteLink.query.filter_by(
            token=token, sender_user_id=current_user.id
        ).first()
        if not invite:
            return jsonify({'status': 'error', 'error': 'Not found'}), 404

        invite.is_active = False
        db.session.commit()
        return jsonify({'status': 'ok'})

    # ----------------------------------------------------------
    # GET /api/share/<token>/stats — link analytics
    # ----------------------------------------------------------
    @app.route('/api/share/<token>/stats')
    @login_required
    def share_link_stats(token):
        invite = InviteLink.query.filter_by(
            token=token, sender_user_id=current_user.id
        ).first()
        if not invite:
            return jsonify({'status': 'error', 'error': 'Not found'}), 404

        return jsonify({
            'status': 'ok',
            'stats': {
                'token': invite.token,
                'link_type': invite.link_type,
                'clicks': invite.click_count,
                'unique_visitors': invite.unique_visitors,
                'conversions': invite.conversions,
                'is_active': invite.is_active,
                'created_at': invite.created_at.isoformat() if invite.created_at else None,
            },
        })

    logger.info("Sharing routes registered (Build #219)")
