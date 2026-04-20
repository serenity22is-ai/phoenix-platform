"""
Phase 2 — Activities & Tours Routes (Build #164)
Viator Partner API integration for MYSTES consumer OTA.

Sell activities directly on MYSTES — full merchant booking flow.
Search → Product Details → Availability Check → Hold → Book → Cancel.

Re-enable by adding to server.py:
    from routes_activities import register_activities_routes
    register_activities_routes(app, csrf, limiter)
"""

import json
import logging
import secrets
from datetime import datetime, timedelta

from flask import request, jsonify, render_template_string, redirect, url_for, session
from flask_login import current_user

from models import db, Deal

logger = logging.getLogger(__name__)


# ============================================================
# ACTIVITIES SEARCH FRONTEND
# ============================================================

ACTIVITIES_SEARCH_CONTENT = """
<style>
    .activity-card { transition: all 0.3s ease; }
    .activity-card:hover { transform: translateX(4px); border-color: var(--glass-border-hover); }
    .activity-img { width: 120px; height: 90px; border-radius: var(--radius-md); object-fit: cover; flex-shrink: 0; }
    .activity-stars { color: #fbbf24; font-size: 14px; }
    .filter-group { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 10px; }
    .filter-group label { display: flex; align-items: center; cursor: pointer; font-weight: normal; color: var(--text-muted); font-size: 14px; }
    .filter-group input[type="checkbox"] { width: auto; margin-right: 6px; }
    @media (max-width: 600px) {
        .activity-img { width: 80px; height: 60px; }
    }
</style>

<div class="mystes-card" style="max-width: 900px; margin: 0 auto 30px;">
    <div class="mystes-page-header" style="padding-top: 0;">
        <h1>Search Activities & Tours</h1>
    </div>
    <div class="mystes-form-grid">
        <div class="full-width">
            <label class="mystes-label">Destination</label>
            <input type="text" id="activity-dest" class="mystes-input" placeholder="Paris, New York, Tokyo, Barcelona..." list="dest-suggestions">
            <datalist id="dest-suggestions">
                <option value="Paris"><option value="London"><option value="New York">
                <option value="Rome"><option value="Barcelona"><option value="Tokyo">
                <option value="Bangkok"><option value="Dubai"><option value="Singapore">
                <option value="Amsterdam"><option value="Berlin"><option value="Istanbul">
                <option value="Bali"><option value="Sydney"><option value="Los Angeles">
                <option value="Miami"><option value="Cancun"><option value="Phuket">
                <option value="Lisbon"><option value="Prague"><option value="Athens">
                <option value="San Francisco"><option value="Marrakech"><option value="Cairo">
                <option value="Dublin"><option value="Vienna"><option value="Florence">
                <option value="Santorini"><option value="Reykjavik"><option value="Honolulu">
            </datalist>
        </div>
        <div>
            <label class="mystes-label">From Date</label>
            <input type="date" id="activity-date-from" class="mystes-input">
        </div>
        <div>
            <label class="mystes-label">To Date</label>
            <input type="date" id="activity-date-to" class="mystes-input">
        </div>
        <div>
            <label class="mystes-label">Travelers</label>
            <select id="activity-travelers" class="mystes-select">
                <option value="1">1 Adult</option>
                <option value="2" selected>2 Adults</option>
                <option value="3">3 Adults</option>
                <option value="4">4 Adults</option>
                <option value="5">5 Adults</option>
                <option value="6">6+ Adults</option>
            </select>
        </div>
        <div>
            <label class="mystes-label">Sort By</label>
            <select id="activity-sort" class="mystes-select">
                <option value="DEFAULT">Recommended</option>
                <option value="PRICE">Price (Low to High)</option>
                <option value="TRAVELER_RATING">Rating</option>
            </select>
        </div>
        <div class="full-width">
            <label class="mystes-label">Filters</label>
            <div class="filter-group">
                <label><input type="checkbox" name="activity-filter" value="FREE_CANCELLATION"> Free Cancellation</label>
                <label><input type="checkbox" name="activity-filter" value="SKIP_THE_LINE"> Skip the Line</label>
                <label><input type="checkbox" name="activity-filter" value="PRIVATE_TOUR"> Private Tour</label>
                <label><input type="checkbox" name="activity-filter" value="LIKELY_TO_SELL_OUT"> Likely to Sell Out</label>
            </div>
        </div>
    </div>
    <button class="mystes-btn mystes-btn-primary mystes-btn-lg mystes-btn-full mt-md" onclick="searchActivities()">
        Search Activities
    </button>
</div>

<div id="activity-loading" style="display: none;" class="text-center" style="padding: 40px;">
    <div style="padding: 40px;">
        <div class="mystes-spinner" style="margin: 0 auto 20px;"></div>
        <p style="color: var(--text-muted);">Searching activities via Viator...</p>
    </div>
</div>

<div id="activity-results" style="display: none; max-width: 900px; margin: 0 auto;">
    <div id="activity-results-header"></div>
    <div id="activity-results-list" style="display: grid; gap: 20px;"></div>
</div>

<script>
(function() {
    const tomorrow = new Date(); tomorrow.setDate(tomorrow.getDate() + 3);
    const weekLater = new Date(); weekLater.setDate(weekLater.getDate() + 10);
    document.getElementById('activity-date-from').value = tomorrow.toISOString().split('T')[0];
    document.getElementById('activity-date-to').value = weekLater.toISOString().split('T')[0];
    document.getElementById('activity-date-from').min = new Date().toISOString().split('T')[0];
})();

async function searchActivities() {
    const dest = document.getElementById('activity-dest').value.trim();
    if (!dest) { alert('Please enter a destination'); return; }

    const dateFrom = document.getElementById('activity-date-from').value;
    const dateTo = document.getElementById('activity-date-to').value;
    if (!dateFrom || !dateTo) { alert('Please select travel dates'); return; }
    if (dateFrom >= dateTo) { alert('End date must be after start date'); return; }

    const travelers = parseInt(document.getElementById('activity-travelers').value);
    const sortBy = document.getElementById('activity-sort').value;
    const filters = [...document.querySelectorAll('input[name="activity-filter"]:checked')].map(c => c.value);

    document.getElementById('activity-loading').style.display = 'block';
    document.getElementById('activity-results').style.display = 'none';

    try {
        const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || '';
        const resp = await fetch('/api/activities/search', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
            body: JSON.stringify({
                destination: dest,
                date_from: dateFrom,
                date_to: dateTo,
                travelers: travelers,
                sort_by: sortBy,
                filters: filters.length > 0 ? filters : null,
            })
        });
        const data = await resp.json();
        renderActivityResults(data, dest, dateFrom, dateTo);
    } catch (err) {
        document.getElementById('activity-loading').style.display = 'none';
        alert('Search failed: ' + err.message);
    }
}

function renderStars(rating) {
    if (!rating) return '';
    const full = Math.floor(rating);
    const half = rating - full >= 0.25;
    let stars = '';
    for (let i = 0; i < full; i++) stars += '&#9733;';
    if (half) stars += '&#189;';
    return '<span class="activity-stars">' + stars + '</span> <span style="color: var(--text-muted); font-size: 13px;">' + rating.toFixed(1) + '</span>';
}

function renderActivityResults(data, dest, dateFrom, dateTo) {
    document.getElementById('activity-loading').style.display = 'none';
    document.getElementById('activity-results').style.display = 'block';

    const header = document.getElementById('activity-results-header');
    const list = document.getElementById('activity-results-list');

    if (!data.success || !data.activities || data.activities.length === 0) {
        header.innerHTML = '<div class="mystes-empty"><div class="mystes-empty-icon">&#127915;</div><p style="font-size: 16px; font-weight: 600;">No activities found</p><p>' + (data.error || 'Try a different destination or dates') + '</p></div>';
        list.innerHTML = '';
        return;
    }

    header.innerHTML = '<div class="flex-between mb-lg" style="flex-wrap: wrap; gap: 10px;"><h2 style="margin: 0;">' + data.activities.length + ' Activities in ' + dest + '</h2><span style="color: var(--text-muted);">' + dateFrom + ' to ' + dateTo + '</span></div>';

    list.innerHTML = data.activities.map(a => {
        let badges = '';
        if (a.free_cancellation) badges += '<span class="mystes-badge mystes-badge-green">Free Cancellation</span> ';
        if (a.skip_the_line) badges += '<span class="mystes-badge mystes-badge-teal">Skip the Line</span> ';
        if (a.likely_to_sell_out) badges += '<span class="mystes-badge mystes-badge-amber">Likely to Sell Out</span> ';
        if (a.private_tour) badges += '<span class="mystes-badge mystes-badge-purple">Private Tour</span> ';

        const discount = a.price_before_discount > a.price ?
            '<span style="text-decoration: line-through; color: rgba(255,255,255,0.35); font-size: 14px; margin-right: 8px;">$' + a.price_before_discount.toFixed(0) + '</span>' : '';

        const imgTag = a.thumbnail ?
            '<img src="' + a.thumbnail + '" class="activity-img" alt="" onerror="this.style.display=\'none\'">' : '';

        return '<div class="mystes-card activity-card" style="border-left: 3px solid var(--accent-purple);">' +
            '<div style="display: flex; gap: 15px; align-items: start; flex-wrap: wrap;">' +
                imgTag +
                '<div style="flex: 1; min-width: 200px;">' +
                    '<div style="margin-bottom: 6px;">' + badges + '</div>' +
                    '<h3 style="margin: 0 0 6px; font-size: 16px;">' + a.title + '</h3>' +
                    '<div style="font-size: 13px; color: var(--text-muted); margin-bottom: 5px;">' +
                        (a.duration ? '<span style="margin-right: 12px;">&#9201; ' + a.duration + '</span>' : '') +
                        (a.rating ? renderStars(a.rating) + ' <span style="opacity: 0.5;">(' + (a.review_count || 0) + ')</span>' : '') +
                    '</div>' +
                    (a.description ? '<div style="font-size: 13px; color: var(--text-muted); margin-top: 5px; line-height: 1.5;">' + a.description.substring(0, 150) + (a.description.length > 150 ? '...' : '') + '</div>' : '') +
                '</div>' +
                '<div style="text-align: right; min-width: 120px; flex-shrink: 0;">' +
                    '<div style="font-size: 12px; color: var(--text-muted); margin-bottom: 4px;">From</div>' +
                    '<div>' + discount +
                        '<span style="font-size: 24px; font-weight: bold; color: var(--accent-purple);">$' + a.price.toFixed(0) + '</span>' +
                    '</div>' +
                    '<div style="font-size: 12px; color: var(--text-muted);">per person</div>' +
                '</div>' +
            '</div>' +
            '<hr class="mystes-divider">' +
            '<div class="flex-between">' +
                '<span style="color: rgba(255,255,255,0.3); font-size: 12px;">Viator</span>' +
                '<button class="mystes-btn mystes-btn-primary mystes-btn-sm" onclick="selectActivity(\'' + a.product_code + '\', this)">' +
                    'View & Book' +
                '</button>' +
            '</div>' +
        '</div>';
    }).join('');
}

async function selectActivity(productCode, btn) {
    btn.disabled = true;
    btn.textContent = 'Loading...';

    try {
        const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || '';
        const resp = await fetch('/api/activities/select', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
            body: JSON.stringify({
                product_code: productCode,
                date_from: document.getElementById('activity-date-from').value,
                travelers: parseInt(document.getElementById('activity-travelers').value),
            })
        });
        const data = await resp.json();
        if (data.success && data.deal_id) {
            window.location.href = '/save-deal/' + data.deal_id;
        } else {
            alert('Error: ' + (data.error || 'Failed to create activity deal'));
            btn.disabled = false;
            btn.textContent = 'View & Book';
        }
    } catch (err) {
        alert('Error: ' + err.message);
        btn.disabled = false;
        btn.textContent = 'View & Book';
    }
}
</script>
"""


ACTIVITY_BOOK_CONTENT = """
<style>
    .payment-method-card {
        border: 1px solid var(--glass-border);
        border-radius: var(--radius-lg);
        padding: 20px;
        margin-bottom: 15px;
        cursor: pointer;
        transition: all 0.2s ease;
        background: var(--glass-bg);
    }
    .payment-method-card:hover { border-color: var(--glass-border-hover); }
    .payment-method-card.selected { border-color: var(--accent-purple); background: rgba(124, 58, 237, 0.08); }
    .payment-method-card .method-header { display: flex; align-items: center; gap: 15px; margin-bottom: 10px; }
    .payment-method-card .method-icon { font-size: 32px; width: 50px; text-align: center; }
    .payment-method-card .method-title { font-weight: bold; font-size: 18px; }
    .payment-method-card .method-subtitle { color: var(--text-muted); font-size: 14px; }
    .payment-details-panel { display: none; border-radius: var(--radius-md); padding: 20px; margin-top: 15px; background: var(--glass-bg-light); }
    .payment-details-panel.active { display: block; }
    .order-summary {
        background: var(--glass-bg);
        border: 1px solid var(--glass-border);
        border-radius: var(--radius-xl);
        padding: 25px;
        margin-bottom: 25px;
    }
    .order-summary h3 { margin: 0 0 20px 0; color: var(--accent-teal); }
    .order-row { display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid var(--glass-border); }
    .order-row:last-child { border-bottom: none; }
    .order-row.total { font-size: 20px; font-weight: bold; padding-top: 15px; margin-top: 10px; border-top: 2px solid rgba(255,255,255,0.15); }
    .flight-leg-item { background: var(--glass-bg-light); border-radius: var(--radius-md); padding: 12px 15px; margin-bottom: 10px; }
    .processing-overlay { display: none; position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.7); z-index: 9999; justify-content: center; align-items: center; }
    .processing-overlay.active { display: flex; }
    .processing-box { background: var(--glass-bg); border: 1px solid var(--glass-border); border-radius: var(--radius-xl); padding: 40px; text-align: center; max-width: 400px; }
</style>

<div class="mystes-card" style="max-width: 800px; margin: 40px auto;">
    <div class="mystes-page-header" style="padding-top: 0;">
        <h1 style="font-size: clamp(20px, 4vw, 28px);">Complete Your Activity Booking</h1>
    </div>

    <!-- Order Summary -->
    <div class="order-summary">
        <h3>Activity Reservation</h3>
        <div class="flight-leg-item">
            <div class="flex-between" style="flex-wrap: wrap; gap: 10px;">
                <div>
                    <strong>{{ deal.hotel_name }}</strong><br>
                    <span style="color: var(--accent-teal);">{{ deal.city_code }}{{ ' - ' + deal.city_name if deal.city_name else '' }}</span><br>
                    <small style="color: var(--text-muted);">{{ deal.check_in_date }} &middot; {{ deal.adults or deal.rooms or 1 }} traveler{{ 's' if (deal.adults or deal.rooms or 1) != 1 else '' }}</small>
                    {% if deal.room_type %}<br><small style="color: var(--text-muted);">{{ deal.room_type }}</small>{% endif %}
                </div>
                <div style="text-align: right;">
                    <span style="font-size: 18px; font-weight: bold;">${{ "%.0f"|format(deal.price_total_usd or 0) }}</span>
                </div>
            </div>
        </div>

        <div class="order-row">
            <span>Activity Price</span>
            <span>${{ "%.2f"|format(deal.price_total_usd or 0) }}</span>
        </div>
        <div class="order-row">
            <span>Service Fee ({{ fee_tier_name }})</span>
            <span>${{ "%.2f"|format(deal.platform_fee_usd or 0) }}</span>
        </div>
        <div class="order-row total">
            <span>MYSTES Price</span>
            <span>${{ "%.2f"|format((deal.price_total_usd or 0) + (deal.platform_fee_usd or 0)) }}</span>
        </div>
        {% if deal.cancellation_policy %}
        <div style="margin-top: 10px; font-size: 13px; color: var(--success-green);">
            {{ deal.cancellation_policy }}
        </div>
        {% endif %}
    </div>

    {% if payment_verified %}
        <!-- Payment Complete - Collect Traveler Details -->
        <div class="mystes-card text-center" style="padding: 25px; border-color: rgba(34, 197, 94, 0.3);">
            <span style="font-size: 48px;">&#9989;</span>
            <h3 class="mt-sm mb-sm">Payment Verified!</h3>
            <p style="color: var(--text-muted);">Your payment has been confirmed. Please provide traveler details to complete your booking.</p>
        </div>

        <form id="guest-form" action="/complete-booking/{{ deal.deal_id }}" method="POST" class="mt-lg">
            <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
            <div class="mystes-card">
                <h4 class="mb-sm">Lead Traveler Information</h4>
                <p style="color: var(--text-muted); margin-bottom: 20px;">Enter details for the lead traveler (as they appear on ID).</p>

                <div class="mystes-form-grid">
                    <div>
                        <label class="mystes-label">First Name *</label>
                        <input type="text" name="first_name" required placeholder="John" class="mystes-input">
                    </div>
                    <div>
                        <label class="mystes-label">Last Name *</label>
                        <input type="text" name="last_name" required placeholder="Doe" class="mystes-input">
                    </div>
                    <div>
                        <label class="mystes-label">Email *</label>
                        <input type="email" name="email" required value="{{ passenger_email or '' }}" placeholder="john@email.com" class="mystes-input">
                    </div>
                    <div>
                        <label class="mystes-label">Phone *</label>
                        <input type="tel" name="phone" required placeholder="+1 555-123-4567" class="mystes-input">
                    </div>
                </div>

                <div class="mystes-card compact mt-lg" style="border-color: rgba(124, 58, 237, 0.2);">
                    <h5 class="mb-sm">Booking Method</h5>
                    <label style="display: flex; align-items: center; cursor: pointer;">
                        <input type="radio" name="fulfillment_type" value="automated" checked style="margin-right: 10px;">
                        <span><strong>Automated Booking</strong> - We book for you (recommended)</span>
                    </label>
                </div>

                <button type="submit" class="mystes-btn mystes-btn-success mystes-btn-lg mystes-btn-full mt-lg">
                    Complete Activity Booking
                </button>
            </div>
        </form>

    {% else %}
        <!-- Guest Email Collection -->
        {% if not current_user.is_authenticated %}
        <div class="mystes-card mb-lg" style="border-color: rgba(124, 58, 237, 0.3);">
            <h4 class="mb-sm">Guest Checkout</h4>
            <p style="color: var(--text-muted); margin-bottom: 15px;">Enter your email to receive your booking confirmation.</p>
            <div>
                <label class="mystes-label" for="guest_email">Email Address *</label>
                <input type="email" id="guest_email" name="guest_email" required
                       value="{{ session.get('guest_email', '') }}"
                       placeholder="your@email.com"
                       class="mystes-input"
                       onchange="saveGuestEmail(this.value)">
            </div>
            <p style="margin-top: 10px; font-size: 12px; color: var(--text-muted);">
                <a href="/register?deal={{ deal.deal_id }}" style="color: var(--accent-purple);">Create an account</a> to track your bookings.
            </p>
        </div>
        {% endif %}

        <!-- Payment Selection -->
        <h3 class="mb-lg">Choose Payment Method</h3>

        <div class="payment-method-card" onclick="selectPayment('card')" id="method-card">
            <div class="method-header">
                <span class="method-icon">&#128179;</span>
                <div>
                    <div class="method-title">Credit or Debit Card</div>
                    <div class="method-subtitle">Visa, Mastercard, American Express</div>
                </div>
                <div style="margin-left: auto; font-weight: bold; color: var(--accent-purple);">
                    ${{ "%.2f"|format((deal.price_total_usd or 0) + (deal.platform_fee_usd or 0)) }}
                </div>
            </div>
            <div class="payment-details-panel" id="details-card">
                <p style="color: var(--text-muted);">Secure payment powered by Stripe. You'll be redirected to complete your payment.</p>
                <button class="mystes-btn mystes-btn-primary mystes-btn-full mt-sm" onclick="payWithCard(event)">
                    Pay ${{ "%.2f"|format((deal.price_total_usd or 0) + (deal.platform_fee_usd or 0)) }} with Card
                </button>
            </div>
        </div>

        <p class="text-center mt-lg" style="color: var(--text-muted); font-size: 14px;">
            All payments are secure and encrypted<br>
            <small>By proceeding, you agree to our Terms of Service</small>
        </p>
    {% endif %}
</div>

<!-- Processing Overlay -->
<div class="processing-overlay" id="processing-overlay">
    <div class="processing-box">
        <div class="mystes-spinner" style="margin: 0 auto 20px;"></div>
        <h3 id="processing-title">Processing Payment...</h3>
        <p id="processing-message" style="color: var(--text-muted);">Please wait while we verify your payment.</p>
    </div>
</div>

<script>
const dealId = "{{ deal.deal_id }}";
const totalAmount = {{ (deal.price_total_usd or 0) + (deal.platform_fee_usd or 0) }};
let guestEmail = "{{ session.get('guest_email', '') }}";

function saveGuestEmail(email) {
    guestEmail = email;
    fetch('/api/save-guest-email', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email: email }) });
}
function selectPayment(method) {
    document.querySelectorAll('.payment-method-card').forEach(c => c.classList.remove('selected'));
    document.querySelectorAll('.payment-details-panel').forEach(p => p.classList.remove('active'));
    document.getElementById('method-' + method).classList.add('selected');
    document.getElementById('details-' + method).classList.add('active');
}
async function payWithCard(event) {
    event.stopPropagation();
    const overlay = document.getElementById('processing-overlay');
    overlay.classList.add('active');
    document.getElementById('processing-title').textContent = 'Redirecting to Stripe...';
    try {
        const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || '';
        const resp = await fetch('/api/payment/stripe/create', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
            body: JSON.stringify({ deal_id: dealId, amount: totalAmount })
        });
        const data = await resp.json();
        if (data.checkout_url) { window.location.href = data.checkout_url; }
        else { overlay.classList.remove('active'); alert('Error: ' + (data.error || 'Failed to create payment session')); }
    } catch (err) { overlay.classList.remove('active'); alert('Payment error: ' + err.message); }
}
</script>
"""


def register_activities_routes(app, csrf, limiter):
    """Register Phase 2 activities/tours routes on the Flask app."""
    from server import BASE_TEMPLATE, is_feature_enabled

    @app.route("/activities")
    def activities():
        """Activities search page."""
        if not is_feature_enabled("vertical_activities"):
            return redirect(url_for("home"))
        return render_template_string(
            BASE_TEMPLATE,
            title="Activities & Tours",
            content=render_template_string(ACTIVITIES_SEARCH_CONTENT, current_user=current_user),
            current_user=current_user
        )

    @app.route("/api/activities/search", methods=["POST"])
    @csrf.exempt
    def api_activities_search():
        """Search activities via Viator."""
        if not is_feature_enabled("vertical_activities"):
            return jsonify({"success": False, "error": "Activities search is not available yet"}), 410
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "No data provided"}), 400

        destination = data.get("destination", "").strip()
        date_from = data.get("date_from")
        date_to = data.get("date_to")
        travelers = data.get("travelers", 2)
        sort_by = data.get("sort_by", "DEFAULT")
        filters = data.get("filters")

        if not destination:
            return jsonify({"success": False, "error": "Destination required"}), 400
        if not date_from or not date_to:
            return jsonify({"success": False, "error": "Travel dates required"}), 400

        try:
            from viator_client import ViatorClient

            client = ViatorClient()
            if not client.is_configured():
                return jsonify({"success": False, "error": "Viator API not configured", "activities": []})

            # ANASTASiA ActivitiesNeuron dispatch (Build #185) — fallback to direct client
            _used_neuron = False
            result = None
            try:
                from anastasia.verticals.activities import ActivitiesNeuron
                from anastasia.core.events import EventBus
                _act_neuron = ActivitiesNeuron()
                _act_neuron.initialize(EventBus(), {"activities_enabled": True})
                result = _act_neuron.search(
                    destination=destination,
                    date_from=date_from,
                    date_to=date_to,
                    client=client,
                )
                _used_neuron = result.get("success", False)
                if _used_neuron:
                    logger.info("[ANASTASiA] ActivitiesNeuron handled search (%d results)", len(result.get("activities", [])))
            except Exception as _neuron_err:
                logger.debug("[ANASTASiA] ActivitiesNeuron unavailable, using direct client: %s", _neuron_err)

            if not _used_neuron:
                # Resolve destination name to Viator destination ID
                destination_id = None
                if destination.isdigit():
                    destination_id = destination
                else:
                    ft_result = client.search_freetext(
                        query=destination, search_types=["DESTINATIONS"],
                        currency="USD", count=5,
                    )
                    if ft_result["success"]:
                        dest_data = ft_result["data"].get("destinations", {})
                        dest_results = dest_data.get("results", [])
                        if dest_results:
                            destination_id = str(dest_results[0].get("ref", dest_results[0].get("destinationId", "")))

                if not destination_id:
                    return jsonify({"success": False, "error": f"Could not find destination: {destination}", "activities": []})

                # Search products
                sort_order = "ASCENDING" if sort_by == "PRICE" else "DESCENDING"
                result = client.search_products(
                    destination_id=destination_id,
                    date_from=date_from,
                    date_to=date_to,
                    currency="USD",
                    sort_by=sort_by,
                    sort_order=sort_order,
                    count=30,
                    flags=filters if filters else None,
                )

            try:
                from monitoring import track_search
                track_search(origin=destination, destination=destination, market="activity")
            except Exception:
                pass

            if not result.get("success"):
                return jsonify({"success": False, "error": result.get("error", "No activities found"), "activities": []})

            activities = result.get("activities", [])

            # Cache search results in session for selection
            session['activity_search_results'] = {a["product_code"]: a for a in activities if a.get("product_code")}

            return jsonify({
                "success": True,
                "activities": activities,
                "count": len(activities),
                "total_count": result.get("total_count", len(activities)),
                "destination": destination,
                "date_from": date_from,
                "date_to": date_to,
            })

        except Exception as e:
            logger.error("Activity search error: %s", e, exc_info=True)
            return jsonify({"success": False, "error": "Activity search failed. Please try again."}), 500

    @app.route("/api/activities/select", methods=["POST"])
    @csrf.exempt
    def api_activities_select():
        """Create a Deal record from a selected activity for checkout."""
        if not is_feature_enabled("vertical_activities"):
            return jsonify({"success": False, "error": "Activity booking is not available yet"}), 410
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "No data provided"}), 400

        product_code = data.get("product_code")
        if not product_code:
            return jsonify({"success": False, "error": "Product code required"}), 400

        travel_date = data.get("date_from")
        travelers = data.get("travelers", 1)

        try:
            cached = session.get('activity_search_results', {})
            activity_data = cached.get(product_code)

            if not activity_data:
                return jsonify({"success": False, "error": "Activity expired. Please search again."}), 400

            # Check real-time availability + pricing
            from viator_client import ViatorClient
            client = ViatorClient()

            pax_mix = [{"ageBand": "ADULT", "numberOfTravelers": travelers}]
            avail_result = client.check_availability(
                product_code=product_code,
                travel_date=travel_date or (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d"),
                currency="USD",
                pax_mix=pax_mix,
            )

            # Use availability pricing if available, fall back to search pricing
            total_price = float(activity_data.get("price", 0)) * travelers
            if avail_result.get("success"):
                slots = avail_result.get("slots", [])
                available_slots = [s for s in slots if s.get("available")]
                if available_slots:
                    total_price = available_slots[0].get("total_price", total_price)

            deal_id = secrets.token_hex(8)
            destination_tag = abs(hash(deal_id)) % 2147483647

            # Platform fee — use standard fee calculation
            try:
                from payments import get_fee_percent
                fee_pct = get_fee_percent(current_user)
            except Exception:
                fee_pct = 0.50  # Default consumer rate (50%)
            platform_fee = max(3.0, total_price * fee_pct)

            deal = Deal(
                deal_id=deal_id,
                deal_type="activity",
                hotel_name=activity_data.get("title", "Unknown Activity"),
                hotel_id=product_code,
                hotel_offer_id=product_code,
                city_code=activity_data.get("destination", ""),
                check_in_date=datetime.strptime(travel_date, "%Y-%m-%d").date() if travel_date else None,
                nights=1,
                rooms=travelers,
                adults=travelers,
                room_type=activity_data.get("duration", ""),
                room_description=activity_data.get("description", "")[:500] if activity_data.get("description") else None,
                price_per_night_usd=float(activity_data.get("price", 0)),
                price_total_usd=total_price,
                home_price_usd=total_price,
                arbitrage_price_usd=total_price,
                platform_fee_usd=platform_fee,
                user_savings_usd=0,
                gross_savings_usd=0,
                savings_percent=0,
                destination_tag=destination_tag,
                amadeus_offer_data=json.dumps({
                    "product_code": product_code,
                    "activity": activity_data,
                    "travel_date": travel_date,
                    "travelers": travelers,
                    "pax_mix": pax_mix,
                }),
                is_active=True,
                expires_at=datetime.utcnow() + timedelta(hours=1),
                created_at=datetime.utcnow(),
            )

            db.session.add(deal)
            db.session.commit()

            return jsonify({
                "success": True,
                "deal_id": deal_id,
                "activity_name": activity_data.get("title"),
                "total_price": total_price + platform_fee,
                "redirect_url": f"/save-deal/{deal_id}",
            })

        except Exception as e:
            logger.error("Activity select error: %s", e, exc_info=True)
            return jsonify({"success": False, "error": "Activity selection failed. Please try again."}), 500
