"""
Builds #228-229 — Narrative Pitch Generator + SharedCart (Pay-For-Someone)

All endpoints gated behind FeatureFlag checks (narrative_pitch, shared_cart).
Admin enables flags when Phase C launches.

Endpoints:
  Narrative Pitch (#228):
  - GET    /api/trips/<id>/narrative             — personalized narrative for current user
  - GET    /api/trips/<id>/narrative/<gid>       — narrative for specific guest (admin only)

  SharedCart (#229):
  - POST   /api/trips/<id>/carts               — create shared cart from items
  - GET    /api/trips/<id>/carts               — list carts for this trip
  - GET    /api/carts/<token>                  — view cart by token (NO AUTH — guest access)
  - PUT    /api/carts/<token>                  — update cart (builder only)
  - POST   /api/carts/<token>/share            — mark as shared + generate InviteLink
  - POST   /api/carts/<token>/pay              — record payment info (guest access)
  - DELETE /api/carts/<token>                  — delete draft cart (builder only)

  UI Pages:
  - GET    /cart/<token>                       — public cart checkout page (no auth)
  - GET    /carts                              — user's cart management dashboard

Registration: register_sharing_cart_routes(app, csrf, limiter)
"""

import json
import logging
import secrets
from datetime import datetime, timezone, timedelta

from flask import request, jsonify, render_template_string
from flask_login import current_user, login_required

from models import (
    db, FeatureFlag, TripPlan, TripMember, TripGuest,
    ItineraryItem, SharedCart, InviteLink,
)

logger = logging.getLogger(__name__)


def _utcnow():
    return datetime.now(timezone.utc)


def _is_expired(dt):
    """Check if a datetime is in the past, handling naive/aware comparison."""
    if dt is None:
        return False
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        # Treat naive datetimes as UTC
        dt = dt.replace(tzinfo=timezone.utc)
    return dt < now


def _check_flag(flag_key):
    """Return error response if flag is disabled, else None."""
    if not FeatureFlag.is_flag_enabled(flag_key):
        return jsonify({
            'status': 'error',
            'error': f'Feature "{flag_key}" is not enabled',
        }), 403
    return None


def _check_trip_access(trip_id, require_edit=False):
    """Verify current user has access to this trip. Returns (trip, error_response)."""
    trip = db.session.get(TripPlan, trip_id)
    if not trip:
        return None, (jsonify({'status': 'error', 'error': 'Trip not found'}), 404)

    if trip.creator_id == current_user.id:
        return trip, None

    member = TripMember.query.filter_by(
        trip_plan_id=trip_id, user_id=current_user.id
    ).first()
    if not member:
        guest = TripGuest.query.filter_by(
            trip_id=trip_id, user_id=current_user.id
        ).first()
        if not guest:
            return None, (jsonify({'status': 'error', 'error': 'Access denied'}), 403)
        if require_edit and guest.role in ('viewer', 'payer'):
            return None, (jsonify({'status': 'error', 'error': 'Edit access required'}), 403)
        return trip, None

    if require_edit and member.role == 'viewer':
        return None, (jsonify({'status': 'error', 'error': 'Edit access required'}), 403)

    return trip, None


def _generate_cart_token():
    """Generate a unique cart token."""
    for _ in range(10):
        token = secrets.token_urlsafe(12)[:16]
        if not SharedCart.query.filter_by(cart_token=token).first():
            return token
    return secrets.token_urlsafe(16)[:16]


# ================================================================
# Build #228: Narrative Pitch Generator
# ================================================================

# Template pools per item type — randomized slightly for variety
_ARRIVAL_TEMPLATES = [
    "{guests} arrive in {destination} on {date}.",
    "{guests} touch down in {destination} on {date}.",
    "{guests} land in {destination} on {date} — the adventure begins.",
    "On {date}, {guests} arrive in {destination} ready for an unforgettable trip.",
]

_HOTEL_TEMPLATES = [
    "Check into {hotel_name} and settle in for the stay.",
    "Home base: {hotel_name}. Drop the bags and get ready to explore.",
    "Settle into {hotel_name} — your home away from home.",
    "Head to {hotel_name} to check in and freshen up.",
]

_ACTIVITY_TEMPLATES = [
    "{time_prefix}{name} — a highlight of the day.",
    "{time_prefix}Time for {name}.",
    "{time_prefix}{name} is on the agenda.",
    "{time_prefix}Don't miss {name}.",
]

_RESTAURANT_TEMPLATES = [
    "{time_prefix}Grab a meal at {name}.",
    "{time_prefix}Dinner at {name} — enjoy!",
    "{time_prefix}Head to {name} for a great bite.",
]

_CAR_TEMPLATES = [
    "Pick up the rental car and hit the road.",
    "Grab the rental and start exploring on your own terms.",
]

_CUSTOM_TEMPLATES = [
    "{time_prefix}{name}.",
]

_FREE_DAY_TEMPLATES = [
    "A free day to explore {destination} at your own pace.",
    "No plans today — wander, relax, or discover something unexpected in {destination}.",
    "The day is yours. Explore {destination} however you like.",
]

_DEPARTURE_TEMPLATES = [
    "{guests} depart {destination} on {date}. Until next time!",
    "On {date}, it's time to head home from {destination}.",
    "{date}: farewell, {destination}. What a trip.",
]


def _pick_template(templates, seed_val):
    """Pick a template deterministically from a pool based on seed value."""
    return templates[seed_val % len(templates)]


def _format_guest_names(guest_names, perspective_name=None):
    """Format guest names from the perspective of a specific guest.

    If perspective_name is set, replace it with "You" and put it first.
    """
    if not guest_names:
        return "Everyone"

    names = list(guest_names)
    if perspective_name and perspective_name in names:
        names.remove(perspective_name)
        names = ["You"] + names

    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} and {names[1]}"
    return ", ".join(names[:-1]) + f", and {names[-1]}"


def _get_destination_from_items(items):
    """Extract primary destination from flight items."""
    for item in items:
        if item.item_type == 'flight' and item.search_params_json:
            try:
                params = json.loads(item.search_params_json)
                return params.get('destination', 'your destination')
            except (json.JSONDecodeError, TypeError):
                pass
    return "your destination"


def _build_narrative(trip, guest_id=None, perspective_name=None):
    """Build a template-based day-by-day narrative for a trip.

    If guest_id is provided, personalizes for that guest's perspective.
    Returns dict with 'narrative' (full text) and 'days' (structured).
    """
    items = ItineraryItem.query.filter_by(trip_id=trip.id).order_by(
        ItineraryItem.date, ItineraryItem.position
    ).all()

    if not items:
        return {
            'narrative': f"Your trip \"{trip.name}\" is being planned. Add some items to see the story unfold!",
            'days': [],
            'item_count': 0,
        }

    # Gather all guest names for this trip
    guests = TripGuest.query.filter_by(trip_id=trip.id).all()
    all_guest_names = [g.display_name for g in guests]
    destination = _get_destination_from_items(items)

    # Group items by date
    days = {}
    dateless_items = []
    for item in items:
        if item.date:
            key = item.date.isoformat()
            if key not in days:
                days[key] = []
            days[key].append(item)
        else:
            dateless_items.append(item)

    sorted_dates = sorted(days.keys())
    narrative_parts = []
    day_structures = []

    for day_idx, date_str in enumerate(sorted_dates):
        day_items = days[date_str]
        day_lines = []
        day_label = f"Day {day_idx + 1} — {date_str}"

        for item in day_items:
            seed = item.id if item.id else day_idx
            time_prefix = f"At {item.start_time}, " if item.start_time else ""

            # Determine which guests are involved (scope-based)
            if item.scope == 'trip':
                involved = _format_guest_names(all_guest_names, perspective_name)
            elif item.scope == 'party' and item.scope_party_id:
                party_guests = TripGuest.query.filter_by(
                    trip_id=trip.id, party_id=item.scope_party_id
                ).all()
                involved = _format_guest_names(
                    [g.display_name for g in party_guests], perspective_name
                )
            elif item.scope == 'individual' and item.assigned_to_guest_id:
                assigned = db.session.get(TripGuest, item.assigned_to_guest_id)
                involved = assigned.display_name if assigned else "Someone"
                if perspective_name and involved == perspective_name:
                    involved = "You"
            else:
                involved = _format_guest_names(all_guest_names, perspective_name)

            # Generate line based on item type
            if item.item_type == 'flight':
                # First flight of trip = arrival, last = departure
                params = {}
                if item.search_params_json:
                    try:
                        params = json.loads(item.search_params_json)
                    except (json.JSONDecodeError, TypeError):
                        pass
                dest = params.get('destination', destination)
                if day_idx == 0:
                    tmpl = _pick_template(_ARRIVAL_TEMPLATES, seed)
                    line = tmpl.format(guests=involved, destination=dest, date=date_str)
                else:
                    tmpl = _pick_template(_DEPARTURE_TEMPLATES, seed)
                    line = tmpl.format(guests=involved, destination=dest, date=date_str)
            elif item.item_type == 'hotel':
                name = item.external_name or "your hotel"
                tmpl = _pick_template(_HOTEL_TEMPLATES, seed)
                line = tmpl.format(hotel_name=name)
            elif item.item_type == 'activity':
                name = item.external_name or item.notes or "an activity"
                tmpl = _pick_template(_ACTIVITY_TEMPLATES, seed)
                line = tmpl.format(time_prefix=time_prefix, name=name)
            elif item.item_type == 'restaurant':
                name = item.external_name or item.notes or "a local spot"
                tmpl = _pick_template(_RESTAURANT_TEMPLATES, seed)
                line = tmpl.format(time_prefix=time_prefix, name=name)
            elif item.item_type == 'car':
                tmpl = _pick_template(_CAR_TEMPLATES, seed)
                line = tmpl.format()
            else:
                name = item.external_name or item.notes or "something special"
                tmpl = _pick_template(_CUSTOM_TEMPLATES, seed)
                line = tmpl.format(time_prefix=time_prefix, name=name)
                # Prepend scope context for non-trip scoped items
                if item.scope == 'individual' and involved != "Everyone":
                    line = f"{involved}: {line}"

            day_lines.append(line)

        # If no items for a day but it's between start/end, it's a free day
        if not day_lines:
            tmpl = _pick_template(_FREE_DAY_TEMPLATES, day_idx)
            day_lines.append(tmpl.format(destination=destination))

        day_structures.append({
            'day_number': day_idx + 1,
            'date': date_str,
            'lines': day_lines,
        })
        narrative_parts.append(f"**{day_label}**\n" + "\n".join(day_lines))

    # Add dateless items as "Anytime" section
    if dateless_items:
        anytime_lines = []
        for item in dateless_items:
            name = item.external_name or item.notes or item.item_type
            anytime_lines.append(f"- {name}")
        narrative_parts.append("**Anytime**\n" + "\n".join(anytime_lines))
        day_structures.append({
            'day_number': None,
            'date': None,
            'lines': anytime_lines,
        })

    return {
        'narrative': "\n\n".join(narrative_parts),
        'days': day_structures,
        'item_count': len(items),
        'destination': destination,
    }


# ================================================================
# Cart Checkout Page Template (public — no auth required)
# ================================================================

CART_CHECKOUT_CONTENT = '''
<style>
    .cart-page { min-height: calc(100vh - 80px); padding: 40px 20px 80px; max-width: 720px; margin: 0 auto; }
    .cart-hero { text-align: center; margin-bottom: 36px; }
    .cart-hero h1 { font-family: var(--font-brand); font-size: clamp(24px, 5vw, 32px); font-weight: 700; letter-spacing: 3px; color: var(--text-bright); margin: 0 0 8px; text-transform: uppercase; }
    .cart-hero .cart-from { font-size: 15px; color: var(--text-muted); margin: 0 0 4px; }
    .cart-hero .cart-from strong { color: var(--accent-teal); }
    .cart-hero .cart-msg { font-size: 14px; color: var(--text-muted); font-style: italic; margin: 12px 0 0; padding: 12px 20px; background: rgba(124,58,237,0.06); border-left: 3px solid var(--accent-purple); border-radius: 0 8px 8px 0; }

    .cart-meta { display: flex; gap: 16px; justify-content: center; flex-wrap: wrap; margin-bottom: 28px; }
    .cart-meta-chip { padding: 6px 14px; background: rgba(255,255,255,0.05); border: 1px solid var(--glass-border); border-radius: var(--radius-full); font-size: 12px; color: var(--text-muted); letter-spacing: 0.5px; text-transform: uppercase; }

    .cart-countdown { text-align: center; margin-bottom: 24px; padding: 12px; border-radius: var(--radius-md); background: rgba(245,158,11,0.08); border: 1px solid rgba(245,158,11,0.2); }
    .cart-countdown .cd-label { font-size: 12px; color: #fbbf24; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 4px; }
    .cart-countdown .cd-time { font-family: var(--font-brand); font-size: 22px; color: #fbbf24; font-weight: 600; letter-spacing: 2px; }
    .cart-countdown.expired { background: rgba(239,68,68,0.08); border-color: rgba(239,68,68,0.2); }
    .cart-countdown.expired .cd-label, .cart-countdown.expired .cd-time { color: #f87171; }

    .cart-items { margin-bottom: 28px; }
    .cart-item { display: flex; justify-content: space-between; align-items: center; padding: 16px 20px; background: var(--glass-bg); border: 1px solid var(--glass-border); border-radius: var(--radius-lg); margin-bottom: 10px; transition: border-color 0.2s; }
    .cart-item:hover { border-color: var(--glass-border-hover); }
    .cart-item-info { flex: 1; min-width: 0; }
    .cart-item-name { font-size: 15px; font-weight: 600; color: var(--text-bright); margin-bottom: 4px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .cart-item-detail { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
    .cart-item-type { padding: 3px 10px; border-radius: var(--radius-full); font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; }
    .cart-item-type.flight { background: rgba(20,184,166,0.15); color: #14b8a6; }
    .cart-item-type.hotel { background: rgba(124,58,237,0.15); color: #a78bfa; }
    .cart-item-type.activity { background: rgba(245,158,11,0.15); color: #fbbf24; }
    .cart-item-type.car { background: rgba(34,197,94,0.15); color: #4ade80; }
    .cart-item-type.restaurant { background: rgba(239,68,68,0.15); color: #f87171; }
    .cart-item-type.custom { background: rgba(255,255,255,0.1); color: var(--text-muted); }
    .cart-item-date { font-size: 12px; color: var(--text-muted); }
    .cart-item-price { font-family: var(--font-brand); font-size: 18px; font-weight: 600; color: var(--text-bright); margin-left: 16px; white-space: nowrap; }

    .cart-total-card { padding: 20px 24px; background: rgba(124,58,237,0.06); border: 1px solid rgba(124,58,237,0.2); border-radius: var(--radius-xl); margin-bottom: 32px; }
    .cart-total-row { display: flex; justify-content: space-between; align-items: center; padding: 6px 0; }
    .cart-total-row.total { padding-top: 12px; margin-top: 8px; border-top: 1px solid rgba(255,255,255,0.1); }
    .cart-total-label { font-size: 14px; color: var(--text-muted); }
    .cart-total-label.total { font-size: 16px; font-weight: 700; color: var(--text-bright); text-transform: uppercase; letter-spacing: 1px; }
    .cart-total-value { font-family: var(--font-brand); font-size: 14px; color: var(--text-bright); }
    .cart-total-value.total { font-size: 24px; font-weight: 700; color: #14b8a6; }

    .cart-pay-section { margin-top: 32px; }
    .cart-pay-section h3 { font-family: var(--font-brand); font-size: 16px; letter-spacing: 2px; color: var(--text-bright); margin-bottom: 16px; text-transform: uppercase; }
    .cart-pay-form { display: flex; flex-direction: column; gap: 12px; }
    .cart-pay-btn { margin-top: 8px; }

    .cart-status-banner { text-align: center; padding: 24px; border-radius: var(--radius-xl); margin-bottom: 24px; }
    .cart-status-banner.paid { background: rgba(34,197,94,0.08); border: 1px solid rgba(34,197,94,0.2); }
    .cart-status-banner.paid h2 { color: #4ade80; margin-bottom: 4px; }
    .cart-status-banner.expired { background: rgba(239,68,68,0.08); border: 1px solid rgba(239,68,68,0.2); }
    .cart-status-banner.expired h2 { color: #f87171; margin-bottom: 4px; }
    .cart-status-banner p { font-size: 14px; color: var(--text-muted); }

    .cart-error { text-align: center; padding: 60px 20px; }
    .cart-error h2 { font-family: var(--font-brand); font-size: 24px; color: var(--text-bright); margin-bottom: 8px; }
    .cart-error p { color: var(--text-muted); font-size: 14px; }

    .cart-loading { text-align: center; padding: 80px 20px; color: var(--text-muted); font-size: 15px; }

    @media (max-width: 640px) {
        .cart-item { flex-direction: column; align-items: flex-start; gap: 8px; }
        .cart-item-price { margin-left: 0; }
    }
</style>

<div class="cart-page">
    <div id="cartLoading" class="cart-loading">Loading cart...</div>
    <div id="cartContent" style="display:none;"></div>
    <div id="cartError" style="display:none;" class="cart-error">
        <h2>CART NOT FOUND</h2>
        <p>This cart link may have expired or been removed.</p>
        <a href="/trips" style="display:inline-block; margin-top:16px; padding:10px 24px; background:rgba(20,184,166,0.15); border:1px solid rgba(20,184,166,0.3); border-radius:10px; color:#14b8a6; font-size:13px; font-weight:600; text-decoration:none;">&#8592; Back to My Trips</a>
    </div>
</div>

<script>
var CART_TOKEN = '{{ cart_token }}';
var countdownInterval = null;

function escapeHtml(str) {
    if (!str) return '';
    var div = document.createElement('div');
    div.appendChild(document.createTextNode(str));
    return div.innerHTML;
}

function formatPrice(n) {
    return '$' + (n || 0).toFixed(2).replace(/\\B(?=(\\d{3})+(?!\\d))/g, ',');
}

function itemTypeBadge(type) {
    var cls = 'custom';
    if (['flight','hotel','activity','car','restaurant'].indexOf(type) >= 0) cls = type;
    return '<span class="cart-item-type ' + cls + '">' + escapeHtml(type) + '</span>';
}

function startCountdown(expiresIso) {
    var el = document.getElementById('cartCountdown');
    if (!el || !expiresIso) return;
    var target = new Date(expiresIso).getTime();
    function tick() {
        var now = Date.now();
        var diff = target - now;
        if (diff <= 0) {
            el.className = 'cart-countdown expired';
            el.querySelector('.cd-label').textContent = 'EXPIRED';
            el.querySelector('.cd-time').textContent = '00:00:00';
            clearInterval(countdownInterval);
            return;
        }
        var h = Math.floor(diff / 3600000);
        var m = Math.floor((diff % 3600000) / 60000);
        var s = Math.floor((diff % 60000) / 1000);
        el.querySelector('.cd-time').textContent =
            (h < 10 ? '0' : '') + h + ':' + (m < 10 ? '0' : '') + m + ':' + (s < 10 ? '0' : '') + s;
    }
    tick();
    countdownInterval = setInterval(tick, 1000);
}

function renderCart(cart, builderName) {
    var items = cart.items || [];
    var isPaid = cart.payment_status === 'paid';
    var isExpired = cart.payment_status === 'expired';

    var html = '';

    // Status banner for paid/expired
    if (isPaid) {
        html += '<div class="cart-status-banner paid">' +
            '<h2>PAYMENT COMPLETE</h2>' +
            '<p>Paid by ' + escapeHtml(cart.payer_name || cart.payer_email || 'Guest') +
            (cart.paid_at ? ' on ' + new Date(cart.paid_at).toLocaleDateString() : '') + '</p></div>';
    } else if (isExpired) {
        html += '<div class="cart-status-banner expired">' +
            '<h2>CART EXPIRED</h2>' +
            '<p>This cart is no longer available for payment.</p></div>';
    }

    // Hero
    html += '<div class="cart-hero">';
    html += '<h1>' + escapeHtml(cart.title) + '</h1>';
    if (builderName) {
        html += '<p class="cart-from">Shared by <strong>' + escapeHtml(builderName) + '</strong></p>';
    }
    if (cart.message) {
        html += '<p class="cart-msg">"' + escapeHtml(cart.message) + '"</p>';
    }
    html += '</div>';

    // Meta chips
    html += '<div class="cart-meta">';
    html += '<span class="cart-meta-chip">' + items.length + ' item' + (items.length !== 1 ? 's' : '') + '</span>';
    html += '<span class="cart-meta-chip">' + cart.payment_status.toUpperCase() + '</span>';
    if (cart.created_at) {
        html += '<span class="cart-meta-chip">Created ' + new Date(cart.created_at).toLocaleDateString() + '</span>';
    }
    html += '</div>';

    // Countdown
    if (!isPaid && !isExpired && cart.expires_at) {
        html += '<div class="cart-countdown" id="cartCountdown">' +
            '<div class="cd-label">EXPIRES IN</div>' +
            '<div class="cd-time">--:--:--</div></div>';
    }

    // Items
    html += '<div class="cart-items">';
    for (var i = 0; i < items.length; i++) {
        var it = items[i];
        html += '<div class="cart-item">';
        html += '<div class="cart-item-info">';
        html += '<div class="cart-item-name">' + escapeHtml(it.name) + '</div>';
        html += '<div class="cart-item-detail">';
        html += itemTypeBadge(it.item_type);
        if (it.date) html += '<span class="cart-item-date">' + escapeHtml(it.date) + '</span>';
        html += '</div></div>';
        html += '<div class="cart-item-price">' + formatPrice(it.price_usd) + '</div>';
        html += '</div>';
    }
    html += '</div>';

    // Total
    html += '<div class="cart-total-card">';
    html += '<div class="cart-total-row"><span class="cart-total-label">Subtotal (' + items.length + ' items)</span><span class="cart-total-value">' + formatPrice(cart.total_estimated_usd) + '</span></div>';
    if (cart.reprice_at_checkout) {
        html += '<div class="cart-total-row"><span class="cart-total-label">Live repricing</span><span class="cart-total-value" style="color:#14b8a6;font-size:12px;">ENABLED</span></div>';
    }
    html += '<div class="cart-total-row total"><span class="cart-total-label total">ESTIMATED TOTAL</span><span class="cart-total-value total">' + formatPrice(cart.total_estimated_usd) + '</span></div>';
    html += '</div>';

    // Pay form (only if cart is payable)
    if (!isPaid && !isExpired && (cart.payment_status === 'shared' || cart.payment_status === 'repriced')) {
        html += '<div class="cart-pay-section mystes-card">';
        html += '<h3>COMPLETE PAYMENT</h3>';
        html += '<div class="cart-pay-form">';
        html += '<input type="text" class="mystes-input" id="payerName" placeholder="Your Name">';
        html += '<input type="email" class="mystes-input" id="payerEmail" placeholder="Your Email" required>';
        html += '<button class="mystes-btn mystes-btn-gold mystes-btn-lg mystes-btn-full cart-pay-btn" id="payBtn" onclick="submitPayment()">PAY ' + formatPrice(cart.total_estimated_usd) + '</button>';
        html += '<p style="text-align:center;font-size:12px;color:var(--text-muted);margin-top:8px;">Secure payment powered by Stripe. Booking executes under the trip builder\'s account.</p>';
        html += '</div></div>';
    }

    document.getElementById('cartContent').innerHTML = html;
    document.getElementById('cartContent').style.display = 'block';

    if (!isPaid && !isExpired && cart.expires_at) {
        startCountdown(cart.expires_at);
    }
}

function loadCart() {
    fetch('/api/carts/' + CART_TOKEN)
        .then(function(r) { return r.json(); })
        .then(function(data) {
            document.getElementById('cartLoading').style.display = 'none';
            if (data.status === 'ok') {
                renderCart(data.cart, data.builder_name);
            } else {
                document.getElementById('cartError').style.display = 'block';
                if (data.error) {
                    document.getElementById('cartError').querySelector('p').textContent = data.error;
                }
            }
        })
        .catch(function() {
            document.getElementById('cartLoading').style.display = 'none';
            document.getElementById('cartError').style.display = 'block';
        });
}

function submitPayment() {
    var btn = document.getElementById('payBtn');
    var email = document.getElementById('payerEmail').value.trim();
    var name = document.getElementById('payerName').value.trim();
    if (!email) { alert('Email is required'); return; }
    btn.disabled = true;
    btn.textContent = 'PROCESSING...';
    var csrf = document.querySelector('meta[name="csrf-token"]');
    var headers = {'Content-Type': 'application/json'};
    if (csrf) headers['X-CSRFToken'] = csrf.content;
    fetch('/api/carts/' + CART_TOKEN + '/pay', {
        method: 'POST',
        headers: headers,
        body: JSON.stringify({payer_email: email, payer_name: name})
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.status === 'ok') {
            loadCart();
        } else {
            alert(data.error || 'Payment failed');
            btn.disabled = false;
            btn.textContent = 'PAY NOW';
        }
    })
    .catch(function(e) {
        alert('Error: ' + e.message);
        btn.disabled = false;
        btn.textContent = 'PAY NOW';
    });
}

document.addEventListener('DOMContentLoaded', loadCart);
</script>
'''


# ================================================================
# My Carts Dashboard Page Template (auth required)
# ================================================================

MY_CARTS_CONTENT = '''
<style>
    .carts-page { min-height: calc(100vh - 80px); padding: 40px 20px 80px; max-width: 900px; margin: 0 auto; }

    .carts-tabs { display: flex; gap: 8px; margin-bottom: 24px; flex-wrap: wrap; }
    .carts-tab { padding: 8px 18px; border-radius: var(--radius-full); font-size: 13px; font-weight: 600; letter-spacing: 0.5px; text-transform: uppercase; cursor: pointer; border: 1px solid var(--glass-border); background: transparent; color: var(--text-muted); transition: all 0.2s; }
    .carts-tab:hover { border-color: var(--glass-border-hover); color: var(--text-bright); }
    .carts-tab.active { background: rgba(124,58,237,0.15); border-color: rgba(124,58,237,0.3); color: #a78bfa; }

    .cart-list-card { padding: 20px; background: var(--glass-bg); border: 1px solid var(--glass-border); border-radius: var(--radius-xl); margin-bottom: 14px; transition: border-color 0.2s, transform 0.2s; cursor: pointer; }
    .cart-list-card:hover { border-color: var(--glass-border-hover); transform: translateY(-2px); }
    .cart-list-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
    .cart-list-title { font-family: var(--font-brand); font-size: 17px; font-weight: 600; color: var(--text-bright); letter-spacing: 1px; }
    .cart-list-meta { display: flex; gap: 14px; font-size: 13px; color: var(--text-muted); flex-wrap: wrap; }
    .cart-list-actions { display: flex; gap: 8px; margin-top: 12px; }

    .carts-empty { text-align: center; padding: 60px 20px; }
    .carts-empty p { color: var(--text-muted); font-size: 14px; margin: 8px 0; }

    .cart-status-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; vertical-align: middle; }
    .cart-status-dot.draft { background: rgba(255,255,255,0.4); }
    .cart-status-dot.shared { background: #a78bfa; }
    .cart-status-dot.repriced { background: #14b8a6; }
    .cart-status-dot.paid { background: #4ade80; }
    .cart-status-dot.expired { background: #f87171; }
</style>

<div class="carts-page">
    <div class="mystes-page-header" style="margin-bottom: 32px;">
        <h1>MY SHARED CARTS</h1>
        <p>Manage carts you have built and shared with others for payment.</p>
    </div>

    <div class="carts-tabs" id="cartsTabs">
        <button class="carts-tab active" data-filter="all" onclick="filterCarts('all', this)">All</button>
        <button class="carts-tab" data-filter="draft" onclick="filterCarts('draft', this)">Draft</button>
        <button class="carts-tab" data-filter="shared" onclick="filterCarts('shared', this)">Shared</button>
        <button class="carts-tab" data-filter="paid" onclick="filterCarts('paid', this)">Paid</button>
        <button class="carts-tab" data-filter="expired" onclick="filterCarts('expired', this)">Expired</button>
    </div>

    <div id="cartsLoading" style="text-align:center;padding:40px;color:var(--text-muted);">Loading carts...</div>
    <div id="cartsList"></div>
</div>

<script>
var allCarts = [];
var currentFilter = 'all';

function escapeHtml(str) {
    if (!str) return '';
    var div = document.createElement('div');
    div.appendChild(document.createTextNode(str));
    return div.innerHTML;
}

function formatPrice(n) {
    return '$' + (n || 0).toFixed(2).replace(/\\B(?=(\\d{3})+(?!\\d))/g, ',');
}

function statusBadgeClass(status) {
    var map = {
        'draft': 'mystes-badge mystes-badge-neutral',
        'shared': 'mystes-badge mystes-badge-purple',
        'repriced': 'mystes-badge mystes-badge-teal',
        'paid': 'mystes-badge mystes-badge-green',
        'expired': 'mystes-badge mystes-badge-red'
    };
    return map[status] || 'mystes-badge mystes-badge-neutral';
}

function filterCarts(filter, btn) {
    currentFilter = filter;
    var tabs = document.querySelectorAll('.carts-tab');
    for (var i = 0; i < tabs.length; i++) tabs[i].className = 'carts-tab';
    if (btn) btn.className = 'carts-tab active';
    renderCarts();
}

function renderCarts() {
    var container = document.getElementById('cartsList');
    var filtered = allCarts;
    if (currentFilter !== 'all') {
        filtered = allCarts.filter(function(c) { return c.payment_status === currentFilter; });
    }
    if (filtered.length === 0) {
        container.innerHTML = '<div class="carts-empty"><p>No carts found' +
            (currentFilter !== 'all' ? ' with status "' + currentFilter + '"' : '') + '.</p>' +
            '<p>Create a shared cart from any trip\'s itinerary to request payment from someone.</p></div>';
        return;
    }
    var html = '';
    for (var i = 0; i < filtered.length; i++) {
        var c = filtered[i];
        var items = c.items || [];
        var created = c.created_at ? new Date(c.created_at).toLocaleDateString() : '';
        html += '<div class="cart-list-card" onclick="window.location=\'/cart/' + escapeHtml(c.cart_token) + '\'">';
        html += '<div class="cart-list-header">';
        html += '<span class="cart-list-title">' + escapeHtml(c.title) + '</span>';
        html += '<span class="' + statusBadgeClass(c.payment_status) + '"><span class="cart-status-dot ' + c.payment_status + '"></span>' + c.payment_status.toUpperCase() + '</span>';
        html += '</div>';
        html += '<div class="cart-list-meta">';
        html += '<span>' + items.length + ' item' + (items.length !== 1 ? 's' : '') + '</span>';
        html += '<span>' + formatPrice(c.total_estimated_usd) + '</span>';
        if (created) html += '<span>Created ' + created + '</span>';
        if (c.payer_name || c.payer_email) html += '<span>Payer: ' + escapeHtml(c.payer_name || c.payer_email) + '</span>';
        html += '</div>';
        html += '<div class="cart-list-actions">';
        if (c.payment_status === 'draft') {
            html += '<button class="mystes-btn mystes-btn-sm mystes-btn-gold" onclick="event.stopPropagation();shareCart(\'' + c.cart_token + '\')">SHARE</button>';
            html += '<button class="mystes-btn mystes-btn-sm mystes-btn-danger" onclick="event.stopPropagation();deleteCart(\'' + c.cart_token + '\')">DELETE</button>';
        } else if (c.payment_status === 'shared' || c.payment_status === 'repriced') {
            html += '<button class="mystes-btn mystes-btn-sm mystes-btn-ghost" onclick="event.stopPropagation();copyLink(\'' + c.cart_token + '\')">COPY LINK</button>';
        }
        html += '</div></div>';
    }
    container.innerHTML = html;
}

function loadAllCarts() {
    fetch('/api/carts/my-carts')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            document.getElementById('cartsLoading').style.display = 'none';
            if (data.status === 'ok') {
                allCarts = data.carts || [];
                renderCarts();
            }
        })
        .catch(function() {
            document.getElementById('cartsLoading').style.display = 'none';
            document.getElementById('cartsList').innerHTML = '<div class="carts-empty"><p>Failed to load carts.</p></div>';
        });
}

function shareCart(token) {
    var csrf = document.querySelector('meta[name="csrf-token"]');
    var headers = {'Content-Type': 'application/json'};
    if (csrf) headers['X-CSRFToken'] = csrf.content;
    fetch('/api/carts/' + token + '/share', {
        method: 'POST',
        headers: headers
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.status === 'ok') {
            var url = window.location.origin + '/cart/' + token;
            if (navigator.clipboard) {
                navigator.clipboard.writeText(url);
                alert('Cart shared! Link copied to clipboard.');
            } else {
                prompt('Cart shared! Copy this link:', url);
            }
            loadAllCarts();
        } else {
            alert(data.error || 'Share failed');
        }
    })
    .catch(function(e) { alert('Error: ' + e.message); });
}

function deleteCart(token) {
    if (!confirm('Delete this draft cart?')) return;
    var csrf = document.querySelector('meta[name="csrf-token"]');
    var headers = {};
    if (csrf) headers['X-CSRFToken'] = csrf.content;
    fetch('/api/carts/' + token, {
        method: 'DELETE',
        headers: headers
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.status === 'ok') loadAllCarts();
        else alert(data.error || 'Delete failed');
    })
    .catch(function(e) { alert('Error: ' + e.message); });
}

function copyLink(token) {
    var url = window.location.origin + '/cart/' + token;
    if (navigator.clipboard) {
        navigator.clipboard.writeText(url);
        alert('Link copied to clipboard!');
    } else {
        prompt('Copy this link:', url);
    }
}

document.addEventListener('DOMContentLoaded', loadAllCarts);
</script>
'''


# ================================================================
# Route Registration
# ================================================================

def register_sharing_cart_routes(app, csrf, limiter):
    """Register narrative pitch + shared cart routes (Builds #228-229)."""
    from server import BASE_TEMPLATE

    # ──────────────────────────────────────────────
    # UI PAGES
    # ──────────────────────────────────────────────

    @app.route('/cart/<token>')
    def cart_checkout_page(token):
        """Public cart checkout page — NO AUTH required."""
        return render_template_string(
            BASE_TEMPLATE,
            title='Shared Cart',
            content=render_template_string(CART_CHECKOUT_CONTENT, cart_token=token),
        )

    @app.route('/carts')
    @login_required
    def my_carts_page():
        """User's cart management dashboard."""
        return render_template_string(
            BASE_TEMPLATE,
            title='My Shared Carts',
            content=MY_CARTS_CONTENT,
        )

    @app.route('/api/carts/my-carts', methods=['GET'])
    @login_required
    def list_my_carts():
        """List all carts built by the current user across all trips."""
        carts = SharedCart.query.filter_by(builder_user_id=current_user.id).order_by(
            SharedCart.created_at.desc()
        ).all()
        return jsonify({
            'status': 'ok',
            'carts': [c.to_dict() for c in carts],
            'count': len(carts),
        })

    # ──────────────────────────────────────────────
    # NARRATIVE PITCH (Build #228)
    # ──────────────────────────────────────────────

    @app.route('/api/trips/<int:trip_id>/narrative', methods=['GET'])
    @login_required
    def get_trip_narrative(trip_id):
        """Generate personalized narrative for current user's guest perspective."""
        flag_err = _check_flag('narrative_pitch')
        if flag_err:
            return flag_err

        trip, err = _check_trip_access(trip_id)
        if err:
            return err

        # Find current user's guest record for personalization
        guest = TripGuest.query.filter_by(
            trip_id=trip_id, user_id=current_user.id
        ).first()
        perspective_name = guest.display_name if guest else current_user.name

        result = _build_narrative(trip, perspective_name=perspective_name)
        return jsonify({
            'status': 'ok',
            'trip_id': trip_id,
            'trip_name': trip.name,
            'perspective': perspective_name,
            **result,
        })

    @app.route('/api/trips/<int:trip_id>/narrative/<int:guest_id>', methods=['GET'])
    @login_required
    def get_guest_narrative(trip_id, guest_id):
        """Generate narrative from a specific guest's perspective (admin only)."""
        flag_err = _check_flag('narrative_pitch')
        if flag_err:
            return flag_err

        trip, err = _check_trip_access(trip_id)
        if err:
            return err

        # Only trip creator can view other guests' narratives
        if trip.creator_id != current_user.id:
            return jsonify({'status': 'error', 'error': 'Only trip creator can view guest narratives'}), 403

        guest = db.session.get(TripGuest, guest_id)
        if not guest or guest.trip_id != trip_id:
            return jsonify({'status': 'error', 'error': 'Guest not found'}), 404

        result = _build_narrative(trip, guest_id=guest.id, perspective_name=guest.display_name)
        return jsonify({
            'status': 'ok',
            'trip_id': trip_id,
            'trip_name': trip.name,
            'guest_id': guest_id,
            'perspective': guest.display_name,
            **result,
        })

    # ──────────────────────────────────────────────
    # SHARED CART (Build #229)
    # ──────────────────────────────────────────────

    @app.route('/api/trips/<int:trip_id>/carts', methods=['POST'])
    @login_required
    def create_shared_cart(trip_id):
        """Create a shared cart from trip itinerary items."""
        flag_err = _check_flag('shared_cart')
        if flag_err:
            return flag_err

        trip, err = _check_trip_access(trip_id, require_edit=True)
        if err:
            return err

        data = request.get_json(silent=True) or {}
        title = data.get('title', '').strip()
        if not title:
            return jsonify({'status': 'error', 'error': 'title is required'}), 400

        # Validate item_ids if provided
        item_ids = data.get('item_ids', [])
        items_snapshot = []
        total = 0.0
        for iid in item_ids:
            item = db.session.get(ItineraryItem, iid)
            if item and item.trip_id == trip_id:
                price = item.cached_price_usd or item.external_cost_usd or 0.0
                items_snapshot.append({
                    'item_id': item.id,
                    'item_type': item.item_type,
                    'name': item.external_name or item.notes or item.item_type,
                    'price_usd': round(price, 2),
                    'date': item.date.isoformat() if item.date else None,
                })
                total += price

        # Allow empty carts (items added later)
        message = data.get('message', '').strip() or None
        expires_hours = data.get('expires_hours', 72)
        try:
            expires_hours = int(expires_hours)
        except (ValueError, TypeError):
            expires_hours = 72

        cart = SharedCart(
            cart_token=_generate_cart_token(),
            trip_id=trip_id,
            builder_user_id=current_user.id,
            title=title,
            message=message,
            items_json=json.dumps(items_snapshot),
            reprice_at_checkout=data.get('reprice_at_checkout', True),
            total_estimated_usd=round(total, 2),
            payment_status='draft',
            expires_at=_utcnow() + timedelta(hours=expires_hours),
        )
        db.session.add(cart)
        db.session.commit()

        return jsonify({
            'status': 'ok',
            'cart': cart.to_dict(include_message=True),
        })

    @app.route('/api/trips/<int:trip_id>/carts', methods=['GET'])
    @login_required
    def list_shared_carts(trip_id):
        """List shared carts for this trip."""
        flag_err = _check_flag('shared_cart')
        if flag_err:
            return flag_err

        trip, err = _check_trip_access(trip_id)
        if err:
            return err

        carts = SharedCart.query.filter_by(trip_id=trip_id).order_by(
            SharedCart.created_at.desc()
        ).all()

        return jsonify({
            'status': 'ok',
            'carts': [c.to_dict() for c in carts],
            'count': len(carts),
        })

    @app.route('/api/carts/<token>', methods=['GET'])
    def view_shared_cart(token):
        """View a shared cart by token — NO AUTH REQUIRED (guest access).

        This is the endpoint payers see when they click the shared link.
        Only shows cart details for shared/repriced status carts.
        """
        cart = SharedCart.query.filter_by(cart_token=token).first()
        if not cart:
            return jsonify({'status': 'error', 'error': 'Cart not found'}), 404

        # Check expiry
        if _is_expired(cart.expires_at):
            if cart.payment_status not in ('paid',):
                cart.payment_status = 'expired'
                db.session.commit()
            return jsonify({'status': 'error', 'error': 'Cart has expired'}), 410

        # Draft carts are only visible to builder
        if cart.payment_status == 'draft':
            if not current_user.is_authenticated or current_user.id != cart.builder_user_id:
                return jsonify({'status': 'error', 'error': 'Cart not yet shared'}), 403

        return jsonify({
            'status': 'ok',
            'cart': cart.to_dict(include_message=True),
            'builder_name': cart.builder.name if cart.builder else None,
        })

    @app.route('/api/carts/<token>', methods=['PUT'])
    @login_required
    def update_shared_cart(token):
        """Update a shared cart (builder only, draft/shared only)."""
        flag_err = _check_flag('shared_cart')
        if flag_err:
            return flag_err

        cart = SharedCart.query.filter_by(cart_token=token).first()
        if not cart:
            return jsonify({'status': 'error', 'error': 'Cart not found'}), 404
        if cart.builder_user_id != current_user.id:
            return jsonify({'status': 'error', 'error': 'Only cart builder can update'}), 403
        if cart.payment_status in ('paid', 'expired'):
            return jsonify({'status': 'error', 'error': f'Cannot update {cart.payment_status} cart'}), 400

        data = request.get_json(silent=True) or {}

        if 'title' in data:
            title = data['title'].strip()
            if title:
                cart.title = title
        if 'message' in data:
            cart.message = data['message'].strip() or None
        if 'reprice_at_checkout' in data:
            cart.reprice_at_checkout = bool(data['reprice_at_checkout'])

        # Update items if provided
        if 'item_ids' in data:
            items_snapshot = []
            total = 0.0
            for iid in data['item_ids']:
                item = db.session.get(ItineraryItem, iid)
                if item and item.trip_id == cart.trip_id:
                    price = item.cached_price_usd or item.external_cost_usd or 0.0
                    items_snapshot.append({
                        'item_id': item.id,
                        'item_type': item.item_type,
                        'name': item.external_name or item.notes or item.item_type,
                        'price_usd': round(price, 2),
                        'date': item.date.isoformat() if item.date else None,
                    })
                    total += price
            cart.items_json = json.dumps(items_snapshot)
            cart.total_estimated_usd = round(total, 2)

        db.session.commit()
        return jsonify({'status': 'ok', 'cart': cart.to_dict(include_message=True)})

    @app.route('/api/carts/<token>/share', methods=['POST'])
    @login_required
    def share_cart(token):
        """Mark cart as shared and generate an InviteLink for guest payment."""
        flag_err = _check_flag('shared_cart')
        if flag_err:
            return flag_err

        cart = SharedCart.query.filter_by(cart_token=token).first()
        if not cart:
            return jsonify({'status': 'error', 'error': 'Cart not found'}), 404
        if cart.builder_user_id != current_user.id:
            return jsonify({'status': 'error', 'error': 'Only cart builder can share'}), 403
        if cart.payment_status not in ('draft', 'shared'):
            return jsonify({'status': 'error', 'error': f'Cannot share {cart.payment_status} cart'}), 400

        cart.payment_status = 'shared'

        # Create InviteLink of type cart_checkout
        invite = InviteLink(
            token=secrets.token_urlsafe(8)[:10],
            link_type='cart_checkout',
            object_id=cart.id,
            sender_user_id=current_user.id,
            permissions='can_pay',
            message=cart.message,
            referral_code=getattr(current_user, 'referral_code', None),
        )
        db.session.add(invite)
        db.session.commit()

        return jsonify({
            'status': 'ok',
            'cart': cart.to_dict(),
            'share_token': invite.token,
            'share_url': f"/i/{invite.token}",
        })

    @app.route('/api/carts/<token>/pay', methods=['POST'])
    def pay_shared_cart(token):
        """Record payer info for a shared cart (NO AUTH — guest access).

        In production, this would create a Stripe Checkout session.
        For now, records payer info and marks as paid.
        """
        cart = SharedCart.query.filter_by(cart_token=token).first()
        if not cart:
            return jsonify({'status': 'error', 'error': 'Cart not found'}), 404

        if cart.payment_status not in ('shared', 'repriced'):
            return jsonify({
                'status': 'error',
                'error': f'Cart is {cart.payment_status}, cannot pay',
            }), 400

        # Check expiry
        if _is_expired(cart.expires_at):
            cart.payment_status = 'expired'
            db.session.commit()
            return jsonify({'status': 'error', 'error': 'Cart has expired'}), 410

        data = request.get_json(silent=True) or {}
        payer_email = data.get('payer_email', '').strip()
        payer_name = data.get('payer_name', '').strip()

        if not payer_email:
            return jsonify({'status': 'error', 'error': 'payer_email is required'}), 400

        cart.payer_email = payer_email
        cart.payer_name = payer_name or None
        cart.payment_status = 'paid'
        cart.paid_at = _utcnow()
        # In production: cart.stripe_session_id = stripe_session.id
        db.session.commit()

        return jsonify({
            'status': 'ok',
            'cart': cart.to_dict(),
            'message': 'Payment recorded. Booking will be processed under the trip builder\'s account.',
        })

    @app.route('/api/carts/<token>', methods=['DELETE'])
    @login_required
    def delete_shared_cart(token):
        """Delete a draft cart (builder only)."""
        flag_err = _check_flag('shared_cart')
        if flag_err:
            return flag_err

        cart = SharedCart.query.filter_by(cart_token=token).first()
        if not cart:
            return jsonify({'status': 'error', 'error': 'Cart not found'}), 404
        if cart.builder_user_id != current_user.id:
            return jsonify({'status': 'error', 'error': 'Only cart builder can delete'}), 403
        if cart.payment_status not in ('draft',):
            return jsonify({'status': 'error', 'error': 'Can only delete draft carts'}), 400

        db.session.delete(cart)
        db.session.commit()
        return jsonify({'status': 'ok', 'message': 'Cart deleted'})
