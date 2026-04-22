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

  UI Pages:
  GET   /referral                          — my referral dashboard page

Registration: register_referral_routes(app, csrf, limiter)
"""

import hashlib
import json
import logging
from datetime import datetime, timezone, timedelta

from flask import request, jsonify, current_app, render_template_string
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


# ================================================================
# Referral Dashboard Page Template
# ================================================================

REFERRAL_DASHBOARD_CONTENT = '''
<style>
    .ref-page { min-height: calc(100vh - 80px); padding: 40px 20px 80px; max-width: 960px; margin: 0 auto; }

    /* Referral code card */
    .ref-code-card { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 24px; background: linear-gradient(135deg, rgba(124,58,237,0.12) 0%, rgba(20,184,166,0.08) 100%); border: 1px solid rgba(124,58,237,0.25); border-radius: var(--radius-xl); margin-bottom: 32px; flex-wrap: wrap; }
    .ref-code-left { flex: 1; min-width: 200px; }
    .ref-code-label { font-size: 12px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 1px; margin-bottom: 6px; }
    .ref-code-value { font-family: var(--font-brand); font-size: 28px; font-weight: 700; color: var(--text-bright); letter-spacing: 4px; word-break: break-all; }
    .ref-code-url { font-size: 12px; color: var(--text-muted); margin-top: 6px; word-break: break-all; }
    .ref-code-actions { display: flex; gap: 8px; flex-wrap: wrap; }

    /* Stats grid */
    .ref-stats { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 14px; margin-bottom: 36px; }
    .ref-stat-card { padding: 20px; background: var(--glass-bg); border: 1px solid var(--glass-border); border-radius: var(--radius-xl); text-align: center; transition: border-color 0.2s, transform 0.2s; }
    .ref-stat-card:hover { border-color: var(--glass-border-hover); transform: translateY(-2px); }
    .ref-stat-num { font-family: var(--font-brand); font-size: 32px; font-weight: 700; color: var(--text-bright); line-height: 1.1; margin-bottom: 6px; }
    .ref-stat-num.teal { color: #14b8a6; }
    .ref-stat-num.gold { color: #C9A96E; }
    .ref-stat-num.purple { color: #a78bfa; }
    .ref-stat-num.green { color: #4ade80; }
    .ref-stat-label { font-size: 11px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 1px; }

    /* Funnel visualization */
    .ref-funnel { margin-bottom: 36px; }
    .ref-funnel h3 { font-family: var(--font-brand); font-size: 16px; letter-spacing: 2px; color: var(--text-bright); margin-bottom: 20px; text-transform: uppercase; }
    .ref-funnel-bar { display: flex; align-items: center; margin-bottom: 12px; gap: 14px; }
    .ref-funnel-label { width: 110px; font-size: 13px; color: var(--text-muted); text-align: right; text-transform: capitalize; flex-shrink: 0; }
    .ref-funnel-track { flex: 1; height: 32px; background: rgba(255,255,255,0.04); border-radius: var(--radius-full); overflow: hidden; position: relative; border: 1px solid var(--glass-border); }
    .ref-funnel-fill { height: 100%; border-radius: var(--radius-full); transition: width 0.8s cubic-bezier(0.16,1,0.3,1); display: flex; align-items: center; justify-content: flex-end; padding-right: 12px; min-width: 0; }
    .ref-funnel-fill.clicks { background: linear-gradient(90deg, rgba(124,58,237,0.4), rgba(124,58,237,0.7)); }
    .ref-funnel-fill.signups { background: linear-gradient(90deg, rgba(20,184,166,0.4), rgba(20,184,166,0.7)); }
    .ref-funnel-fill.searches { background: linear-gradient(90deg, rgba(201,169,110,0.4), rgba(201,169,110,0.7)); }
    .ref-funnel-fill.bookings { background: linear-gradient(90deg, rgba(34,197,94,0.4), rgba(34,197,94,0.7)); }
    .ref-funnel-fill.subscriptions { background: linear-gradient(90deg, rgba(239,68,68,0.3), rgba(239,68,68,0.6)); }
    .ref-funnel-count { font-family: var(--font-brand); font-size: 13px; font-weight: 600; color: var(--text-bright); white-space: nowrap; }
    .ref-funnel-pct { width: 50px; font-size: 12px; color: var(--text-muted); text-align: left; flex-shrink: 0; }

    /* Conversion history table */
    .ref-history { margin-bottom: 36px; }
    .ref-history h3 { font-family: var(--font-brand); font-size: 16px; letter-spacing: 2px; color: var(--text-bright); margin-bottom: 16px; text-transform: uppercase; }
    .ref-table-wrap { overflow-x: auto; -webkit-overflow-scrolling: touch; }
    .ref-table { width: 100%; border-collapse: collapse; }
    .ref-table th { text-align: left; padding: 10px 14px; font-size: 11px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 1px; border-bottom: 1px solid var(--glass-border); }
    .ref-table td { padding: 12px 14px; font-size: 14px; color: var(--text-bright); border-bottom: 1px solid rgba(255,255,255,0.04); }
    .ref-table tr:hover td { background: rgba(255,255,255,0.02); }
    .ref-table .event-type { text-transform: capitalize; }

    .ref-load-more { text-align: center; margin-top: 16px; }
    .ref-empty { text-align: center; padding: 40px 20px; color: var(--text-muted); font-size: 14px; }

    .ref-loading { text-align: center; padding: 60px 20px; color: var(--text-muted); font-size: 15px; }

    @media (max-width: 640px) {
        .ref-code-card { flex-direction: column; text-align: center; }
        .ref-code-actions { justify-content: center; }
        .ref-stats { grid-template-columns: repeat(2, 1fr); }
        .ref-funnel-label { width: 80px; font-size: 11px; }
        .ref-funnel-pct { width: 40px; font-size: 11px; }
    }
</style>

<div class="ref-page">
    <div class="mystes-page-header" style="margin-bottom: 32px;">
        <h1>REFERRAL DASHBOARD</h1>
        <p>Share your code, earn points on every milestone. Track your referral funnel in real time.</p>
    </div>

    <div id="refLoading" class="ref-loading">Loading your referral stats...</div>
    <div id="refContent" style="display:none;">

        <!-- Referral code card -->
        <div class="ref-code-card" id="refCodeCard">
            <div class="ref-code-left">
                <div class="ref-code-label">Your Referral Code</div>
                <div class="ref-code-value" id="refCodeValue">---</div>
                <div class="ref-code-url" id="refCodeUrl"></div>
            </div>
            <div class="ref-code-actions">
                <button class="mystes-btn mystes-btn-gold" id="copyCodeBtn" onclick="copyRefCode()">COPY CODE</button>
                <button class="mystes-btn mystes-btn-ghost" id="copyLinkBtn" onclick="copyRefLink()">COPY LINK</button>
            </div>
        </div>

        <!-- Stats grid -->
        <div class="ref-stats" id="refStats"></div>

        <!-- Funnel -->
        <div class="ref-funnel mystes-card" id="refFunnel">
            <h3>CONVERSION FUNNEL</h3>
            <div id="funnelBars"></div>
        </div>

        <!-- Conversion history -->
        <div class="ref-history">
            <h3>CONVERSION HISTORY</h3>
            <div id="refHistoryContent"></div>
            <div class="ref-load-more" id="loadMoreWrap" style="display:none;">
                <button class="mystes-btn mystes-btn-ghost mystes-btn-sm" id="loadMoreBtn" onclick="loadMoreConversions()">LOAD MORE</button>
            </div>
        </div>
    </div>
</div>

<script>
var refCode = '';
var convPage = 1;
var convTotal = 0;
var convLoaded = 0;

function escapeHtml(str) {
    if (!str) return '';
    var div = document.createElement('div');
    div.appendChild(document.createTextNode(str));
    return div.innerHTML;
}

function copyRefCode() {
    if (!refCode) return;
    if (navigator.clipboard) {
        navigator.clipboard.writeText(refCode);
        document.getElementById('copyCodeBtn').textContent = 'COPIED!';
        setTimeout(function() { document.getElementById('copyCodeBtn').textContent = 'COPY CODE'; }, 2000);
    } else {
        prompt('Your referral code:', refCode);
    }
}

function copyRefLink() {
    if (!refCode) return;
    var url = window.location.origin + '/?ref=' + refCode;
    if (navigator.clipboard) {
        navigator.clipboard.writeText(url);
        document.getElementById('copyLinkBtn').textContent = 'COPIED!';
        setTimeout(function() { document.getElementById('copyLinkBtn').textContent = 'COPY LINK'; }, 2000);
    } else {
        prompt('Your referral link:', url);
    }
}

function eventTypeBadge(etype) {
    var colors = {
        'signup': 'mystes-badge mystes-badge-teal',
        'first_search': 'mystes-badge mystes-badge-amber',
        'first_booking': 'mystes-badge mystes-badge-green',
        'subscription': 'mystes-badge mystes-badge-gold'
    };
    var label = etype.replace(/_/g, ' ');
    return '<span class="' + (colors[etype] || 'mystes-badge mystes-badge-neutral') + '">' + label + '</span>';
}

function renderStats(data) {
    var funnel = data.funnel || {};
    var statsHtml = '';
    statsHtml += '<div class="ref-stat-card"><div class="ref-stat-num purple">' + (data.total_clicks || 0) + '</div><div class="ref-stat-label">Total Clicks</div></div>';
    statsHtml += '<div class="ref-stat-card"><div class="ref-stat-num teal">' + (data.unique_visitors || 0) + '</div><div class="ref-stat-label">Unique Visitors</div></div>';
    statsHtml += '<div class="ref-stat-card"><div class="ref-stat-num">' + (funnel.signup || 0) + '</div><div class="ref-stat-label">Signups</div></div>';
    statsHtml += '<div class="ref-stat-card"><div class="ref-stat-num green">' + (funnel.first_booking || 0) + '</div><div class="ref-stat-label">Bookings</div></div>';
    statsHtml += '<div class="ref-stat-card"><div class="ref-stat-num gold">' + (data.total_points_earned || 0).toLocaleString() + '</div><div class="ref-stat-label">Points Earned</div></div>';
    statsHtml += '<div class="ref-stat-card"><div class="ref-stat-num teal">$' + (data.total_commission_usd || 0).toFixed(2) + '</div><div class="ref-stat-label">Commission</div></div>';
    document.getElementById('refStats').innerHTML = statsHtml;
}

function renderFunnel(data) {
    var funnel = data.funnel || {};
    var clicks = data.total_clicks || 0;
    var steps = [
        {key: 'clicks', label: 'Clicks', value: clicks, cls: 'clicks'},
        {key: 'signup', label: 'Signups', value: funnel.signup || 0, cls: 'signups'},
        {key: 'first_search', label: 'Searches', value: funnel.first_search || 0, cls: 'searches'},
        {key: 'first_booking', label: 'Bookings', value: funnel.first_booking || 0, cls: 'bookings'},
        {key: 'subscription', label: 'Subscriptions', value: funnel.subscription || 0, cls: 'subscriptions'}
    ];
    var maxVal = clicks || 1;

    var html = '';
    for (var i = 0; i < steps.length; i++) {
        var s = steps[i];
        var pct = maxVal > 0 ? Math.round((s.value / maxVal) * 100) : 0;
        var barWidth = Math.max(pct, s.value > 0 ? 5 : 0);
        html += '<div class="ref-funnel-bar">';
        html += '<span class="ref-funnel-label">' + s.label + '</span>';
        html += '<div class="ref-funnel-track"><div class="ref-funnel-fill ' + s.cls + '" style="width:' + barWidth + '%">';
        if (barWidth > 15) html += '<span class="ref-funnel-count">' + s.value + '</span>';
        html += '</div></div>';
        if (barWidth <= 15 && s.value > 0) {
            html += '<span class="ref-funnel-count" style="margin-left:-4px;">' + s.value + '</span>';
        }
        html += '<span class="ref-funnel-pct">' + pct + '%</span>';
        html += '</div>';
    }
    document.getElementById('funnelBars').innerHTML = html;
}

function renderConversions(events, append) {
    var container = document.getElementById('refHistoryContent');
    if (!events || events.length === 0) {
        if (!append) {
            container.innerHTML = '<div class="ref-empty">No conversions yet. Share your referral code to start earning!</div>';
        }
        return;
    }
    var tableHtml = '';
    if (!append) {
        tableHtml += '<div class="ref-table-wrap"><table class="ref-table"><thead><tr>';
        tableHtml += '<th>Date</th><th>Type</th><th>Points</th><th>Commission</th>';
        tableHtml += '</tr></thead><tbody id="refTableBody">';
    }
    var rows = '';
    for (var i = 0; i < events.length; i++) {
        var ev = events[i];
        var dateStr = ev.created_at ? new Date(ev.created_at).toLocaleDateString() : '-';
        rows += '<tr>';
        rows += '<td>' + dateStr + '</td>';
        rows += '<td>' + eventTypeBadge(ev.event_type) + '</td>';
        rows += '<td>+' + (ev.points_awarded || 0).toLocaleString() + '</td>';
        rows += '<td>$' + (ev.commission_usd || 0).toFixed(2) + '</td>';
        rows += '</tr>';
    }
    if (append) {
        var tbody = document.getElementById('refTableBody');
        if (tbody) tbody.insertAdjacentHTML('beforeend', rows);
    } else {
        tableHtml += rows + '</tbody></table></div>';
        container.innerHTML = tableHtml;
    }
}

function loadDashboard() {
    fetch('/api/referral/my-stats')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            document.getElementById('refLoading').style.display = 'none';
            document.getElementById('refContent').style.display = 'block';

            refCode = data.referral_code || '';
            document.getElementById('refCodeValue').textContent = refCode || 'No code assigned';
            if (refCode) {
                document.getElementById('refCodeUrl').textContent = window.location.origin + '/?ref=' + refCode;
            }

            renderStats(data);
            renderFunnel(data);

            // Load first page of conversions
            loadConversions(1, false);
        })
        .catch(function() {
            document.getElementById('refLoading').style.display = 'none';
            document.getElementById('refContent').style.display = 'block';
            document.getElementById('refStats').innerHTML = '<div class="ref-empty">Failed to load stats.</div>';
        });
}

function loadConversions(page, append) {
    fetch('/api/referral/my-conversions?page=' + page + '&per_page=15')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.status === 'ok') {
                convTotal = data.total || 0;
                convLoaded += (data.conversions || []).length;
                convPage = page;
                renderConversions(data.conversions, append);
                if (convLoaded < convTotal) {
                    document.getElementById('loadMoreWrap').style.display = 'block';
                } else {
                    document.getElementById('loadMoreWrap').style.display = 'none';
                }
            }
        })
        .catch(function() {});
}

function loadMoreConversions() {
    var btn = document.getElementById('loadMoreBtn');
    btn.disabled = true;
    btn.textContent = 'LOADING...';
    loadConversions(convPage + 1, true);
    setTimeout(function() { btn.disabled = false; btn.textContent = 'LOAD MORE'; }, 500);
}

document.addEventListener('DOMContentLoaded', loadDashboard);
</script>
'''


def register_referral_routes(app, csrf, limiter):
    """Register referral attribution routes (Build #233)."""
    from server import BASE_TEMPLATE

    # ──────────────────────────────────────────────
    # UI PAGE
    # ──────────────────────────────────────────────

    @app.route('/referral')
    @login_required
    def referral_dashboard_page():
        """My Referral Dashboard — stats, funnel, conversion history."""
        return render_template_string(
            BASE_TEMPLATE,
            title='Referral Dashboard',
            content=REFERRAL_DASHBOARD_CONTENT,
        )

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
