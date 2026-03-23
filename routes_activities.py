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
    .activity-search-form { max-width: 900px; margin: 0 auto 30px; }
    .activity-search-form label { font-weight: bold; color: #f5f5f5; display: block; margin-bottom: 5px; }
    .activity-search-form input, .activity-search-form select {
        width: 100%; padding: 12px; border: 1px solid rgba(255,255,255,0.2);
        border-radius: 8px; font-size: 16px; color: #fff;
        background: rgba(15, 10, 25, 0.6); backdrop-filter: blur(10px);
    }
    .activity-search-form input::placeholder { color: #999; }
    .activity-search-form input:focus, .activity-search-form select:focus {
        border-color: #7c3aed; outline: none; box-shadow: 0 0 0 3px rgba(124, 58, 237, 0.2);
    }
    .activity-card { transition: all 0.3s ease; }
    .activity-card:hover { transform: translateX(4px); border-color: rgba(124, 58, 237, 0.5); }
    .activity-badge { font-size: 11px; padding: 2px 8px; border-radius: 4px; display: inline-block; margin-right: 5px; margin-bottom: 5px; }
    .activity-badge-green { background: #065f46; color: #6ee7b7; }
    .activity-badge-blue { background: #1e3a5f; color: #93c5fd; }
    .activity-badge-orange { background: #78350f; color: #fbbf24; }
    .activity-badge-purple { background: #6d28d9; color: white; }
    .activity-img { width: 120px; height: 90px; border-radius: 8px; object-fit: cover; flex-shrink: 0; }
    .activity-stars { color: #fbbf24; font-size: 14px; }
    .filter-group { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 10px; }
    .filter-group label { display: flex; align-items: center; cursor: pointer; font-weight: normal; color: #ccc; font-size: 14px; }
    .filter-group input { width: auto; margin-right: 6px; }
    .spinner-activity { width: 50px; height: 50px; border: 4px solid rgba(255,255,255,0.1); border-top-color: #7c3aed; border-radius: 50%; animation: activityspin 1s linear infinite; margin: 0 auto 20px; }
    @keyframes activityspin { to { transform: rotate(360deg); } }
    @media (max-width: 600px) {
        .activity-img { width: 80px; height: 60px; }
    }
</style>

<div class="card activity-search-form">
    <h1 style="text-align: center; margin-bottom: 25px; color: #f5f5f5;">Search Activities & Tours</h1>
    <div>
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 15px;">
            <div class="form-group" style="grid-column: 1 / -1;">
                <label>Destination</label>
                <input type="text" id="activity-dest" placeholder="Paris, New York, Tokyo, Barcelona..." list="dest-suggestions">
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
            <div class="form-group">
                <label>From Date</label>
                <input type="date" id="activity-date-from">
            </div>
            <div class="form-group">
                <label>To Date</label>
                <input type="date" id="activity-date-to">
            </div>
            <div class="form-group">
                <label>Travelers</label>
                <select id="activity-travelers">
                    <option value="1">1 Adult</option>
                    <option value="2" selected>2 Adults</option>
                    <option value="3">3 Adults</option>
                    <option value="4">4 Adults</option>
                    <option value="5">5 Adults</option>
                    <option value="6">6+ Adults</option>
                </select>
            </div>
            <div class="form-group">
                <label>Sort By</label>
                <select id="activity-sort">
                    <option value="DEFAULT">Recommended</option>
                    <option value="PRICE">Price (Low to High)</option>
                    <option value="TRAVELER_RATING">Rating</option>
                </select>
            </div>
            <div class="form-group" style="grid-column: 1 / -1;">
                <label>Filters</label>
                <div class="filter-group">
                    <label><input type="checkbox" name="activity-filter" value="FREE_CANCELLATION"> Free Cancellation</label>
                    <label><input type="checkbox" name="activity-filter" value="SKIP_THE_LINE"> Skip the Line</label>
                    <label><input type="checkbox" name="activity-filter" value="PRIVATE_TOUR"> Private Tour</label>
                    <label><input type="checkbox" name="activity-filter" value="LIKELY_TO_SELL_OUT"> Likely to Sell Out</label>
                </div>
            </div>
        </div>
        <button class="btn" onclick="searchActivities()" style="width: 100%; margin-top: 15px; padding: 15px; font-size: 16px;">
            Search Activities
        </button>
    </div>
</div>

<div id="activity-loading" style="display: none; text-align: center; padding: 40px;">
    <div class="spinner-activity"></div>
    <p style="color: #ccc;">Searching activities via Viator...</p>
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
    return '<span class="activity-stars">' + stars + '</span> <span style="color: #ccc; font-size: 13px;">' + rating.toFixed(1) + '</span>';
}

function renderActivityResults(data, dest, dateFrom, dateTo) {
    document.getElementById('activity-loading').style.display = 'none';
    document.getElementById('activity-results').style.display = 'block';

    const header = document.getElementById('activity-results-header');
    const list = document.getElementById('activity-results-list');

    if (!data.success || !data.activities || data.activities.length === 0) {
        header.innerHTML = '<div class="card" style="text-align: center; padding: 40px;"><h3 style="color: #f5f5f5;">No activities found</h3><p style="color: #ccc;">' + (data.error || 'Try a different destination or dates') + '</p></div>';
        list.innerHTML = '';
        return;
    }

    header.innerHTML = '<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; flex-wrap: wrap; gap: 10px;"><h2 style="color: #f5f5f5; margin: 0;">' + data.activities.length + ' Activities in ' + dest + '</h2><span style="color: #ccc;">' + dateFrom + ' to ' + dateTo + '</span></div>';

    list.innerHTML = data.activities.map(a => {
        let badges = '';
        if (a.free_cancellation) badges += '<span class="activity-badge activity-badge-green">Free Cancellation</span>';
        if (a.skip_the_line) badges += '<span class="activity-badge activity-badge-blue">Skip the Line</span>';
        if (a.likely_to_sell_out) badges += '<span class="activity-badge activity-badge-orange">Likely to Sell Out</span>';
        if (a.private_tour) badges += '<span class="activity-badge activity-badge-purple">Private Tour</span>';

        const discount = a.price_before_discount > a.price ?
            '<span style="text-decoration: line-through; color: #888; font-size: 14px; margin-right: 8px;">$' + a.price_before_discount.toFixed(0) + '</span>' : '';

        const imgTag = a.thumbnail ?
            '<img src="' + a.thumbnail + '" class="activity-img" alt="" onerror="this.style.display=\'none\'">' : '';

        return '<div class="card activity-card" style="border-left: 4px solid #7c3aed;">' +
            '<div style="display: flex; gap: 15px; align-items: start; flex-wrap: wrap;">' +
                imgTag +
                '<div style="flex: 1; min-width: 200px;">' +
                    '<div>' + badges + '</div>' +
                    '<h3 style="margin: 5px 0; color: #f5f5f5; font-size: 16px;">' + a.title + '</h3>' +
                    '<div style="font-size: 13px; color: #ccc; margin-bottom: 5px;">' +
                        (a.duration ? '<span style="margin-right: 12px;">&#9201; ' + a.duration + '</span>' : '') +
                        (a.rating ? renderStars(a.rating) + ' <span style="color: #888;">(' + (a.review_count || 0) + ')</span>' : '') +
                    '</div>' +
                    (a.description ? '<div style="font-size: 13px; color: #aaa; margin-top: 5px; line-height: 1.4;">' + a.description.substring(0, 150) + (a.description.length > 150 ? '...' : '') + '</div>' : '') +
                '</div>' +
                '<div style="text-align: right; min-width: 120px; flex-shrink: 0;">' +
                    '<div style="font-size: 12px; color: #ccc; margin-bottom: 4px;">From</div>' +
                    '<div>' + discount +
                        '<span style="font-size: 24px; font-weight: bold; color: #7c3aed;">$' + a.price.toFixed(0) + '</span>' +
                    '</div>' +
                    '<div style="font-size: 12px; color: #ccc;">per person</div>' +
                '</div>' +
            '</div>' +
            '<div style="margin-top: 15px; display: flex; justify-content: space-between; align-items: center; padding-top: 15px; border-top: 1px solid rgba(255,255,255,0.1);">' +
                '<span style="color: #666; font-size: 12px;">Viator</span>' +
                '<button class="btn" onclick="selectActivity(\'' + a.product_code + '\', this)" style="padding: 8px 20px;">' +
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
    .payment-method-card { border: 2px solid #e9ecef; border-radius: 12px; padding: 20px; margin-bottom: 15px; cursor: pointer; transition: all 0.2s ease; background: white; }
    .payment-method-card:hover { border-color: #7c3aed; box-shadow: 0 4px 12px rgba(67, 97, 238, 0.15); }
    .payment-method-card.selected { border-color: #7c3aed; background: #f5f3ff; }
    .payment-method-card .method-header { display: flex; align-items: center; gap: 15px; margin-bottom: 10px; }
    .payment-method-card .method-icon { font-size: 32px; width: 50px; text-align: center; }
    .payment-method-card .method-title { font-weight: bold; font-size: 18px; color: #16213e; }
    .payment-method-card .method-subtitle { color: #666; font-size: 14px; }
    .payment-details-panel { display: none; background: #f8f9fa; border-radius: 8px; padding: 20px; margin-top: 15px; }
    .payment-details-panel.active { display: block; }
    .order-summary { background: linear-gradient(135deg, #16213e 0%, #1a1a2e 100%); color: white; border-radius: 12px; padding: 25px; margin-bottom: 25px; }
    .order-summary h3 { margin: 0 0 20px 0; color: #14b8a6; }
    .order-row { display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid rgba(255,255,255,0.1); }
    .order-row:last-child { border-bottom: none; }
    .order-row.total { font-size: 20px; font-weight: bold; padding-top: 15px; margin-top: 10px; border-top: 2px solid rgba(255,255,255,0.3); }
    .flight-leg-item { background: rgba(255,255,255,0.1); border-radius: 8px; padding: 12px 15px; margin-bottom: 10px; }
    .processing-overlay { display: none; position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.7); z-index: 9999; justify-content: center; align-items: center; }
    .processing-overlay.active { display: flex; }
    .processing-box { background: white; border-radius: 16px; padding: 40px; text-align: center; max-width: 400px; }
    .spinner { width: 50px; height: 50px; border: 4px solid #e9ecef; border-top-color: #7c3aed; border-radius: 50%; animation: spin 1s linear infinite; margin: 0 auto 20px; }
    @keyframes spin { to { transform: rotate(360deg); } }
</style>

<div class="card card-light" style="max-width: 800px; margin: 40px auto;">
    <h2 style="text-align: center; margin-bottom: 25px; color: #1a1a2e;">Complete Your Activity Booking</h2>

    <!-- Order Summary -->
    <div class="order-summary">
        <h3>Activity Reservation</h3>
        <div class="flight-leg-item">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <div>
                    <strong>{{ deal.hotel_name }}</strong><br>
                    <span style="color: #14b8a6;">{{ deal.city_code }}{{ ' - ' + deal.city_name if deal.city_name else '' }}</span><br>
                    <small>{{ deal.check_in_date }} &middot; {{ deal.adults or deal.rooms or 1 }} traveler{{ 's' if (deal.adults or deal.rooms or 1) != 1 else '' }}</small>
                    {% if deal.room_type %}<br><small style="color: #999;">{{ deal.room_type }}</small>{% endif %}
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
        <div style="margin-top: 10px; font-size: 13px; color: #4caf50;">
            {{ deal.cancellation_policy }}
        </div>
        {% endif %}
    </div>

    {% if payment_verified %}
        <!-- Payment Complete - Collect Traveler Details -->
        <div class="alert alert-success" style="text-align: center; padding: 25px;">
            <span style="font-size: 48px;">&#9989;</span>
            <h3 style="margin: 15px 0;">Payment Verified!</h3>
            <p>Your payment has been confirmed. Please provide traveler details to complete your booking.</p>
        </div>

        <form id="guest-form" action="/complete-booking/{{ deal.deal_id }}" method="POST" style="margin-top: 20px;">
            <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
            <div style="background: #f8f9fa; border-radius: 12px; padding: 25px;">
                <h4 style="margin: 0 0 20px 0; color: #1a1a2e;">Lead Traveler Information</h4>
                <p style="color: #666; margin-bottom: 20px;">Enter details for the lead traveler (as they appear on ID).</p>

                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 15px;">
                    <div class="form-group">
                        <label style="font-weight: bold; color: #16213e; display: block; margin-bottom: 5px;">First Name *</label>
                        <input type="text" name="first_name" required placeholder="John" style="width: 100%; padding: 12px; border: 1px solid #ddd; border-radius: 8px; font-size: 16px; color: #1a1a2e;">
                    </div>
                    <div class="form-group">
                        <label style="font-weight: bold; color: #16213e; display: block; margin-bottom: 5px;">Last Name *</label>
                        <input type="text" name="last_name" required placeholder="Doe" style="width: 100%; padding: 12px; border: 1px solid #ddd; border-radius: 8px; font-size: 16px; color: #1a1a2e;">
                    </div>
                    <div class="form-group">
                        <label style="font-weight: bold; color: #16213e; display: block; margin-bottom: 5px;">Email *</label>
                        <input type="email" name="email" required value="{{ passenger_email or '' }}" placeholder="john@email.com" style="width: 100%; padding: 12px; border: 1px solid #ddd; border-radius: 8px; font-size: 16px; color: #1a1a2e;">
                    </div>
                    <div class="form-group">
                        <label style="font-weight: bold; color: #16213e; display: block; margin-bottom: 5px;">Phone *</label>
                        <input type="tel" name="phone" required placeholder="+1 555-123-4567" style="width: 100%; padding: 12px; border: 1px solid #ddd; border-radius: 8px; font-size: 16px; color: #1a1a2e;">
                    </div>
                </div>

                <div style="margin-top: 25px; padding: 20px; background: #f5f3ff; border-radius: 8px;">
                    <h5 style="margin: 0 0 10px 0;">Booking Method</h5>
                    <label style="display: flex; align-items: center; cursor: pointer;">
                        <input type="radio" name="fulfillment_type" value="automated" checked style="margin-right: 10px;">
                        <span><strong>Automated Booking</strong> - We book for you (recommended)</span>
                    </label>
                </div>

                <button type="submit" class="btn btn-success" style="width: 100%; margin-top: 25px; padding: 15px; font-size: 18px;">
                    Complete Activity Booking
                </button>
            </div>
        </form>

    {% else %}
        <!-- Guest Email Collection -->
        {% if not current_user.is_authenticated %}
        <div style="background: #f5f3ff; border: 2px solid #7c3aed; border-radius: 12px; padding: 20px; margin-bottom: 25px;">
            <h4 style="margin: 0 0 15px 0; color: #16213e;">Guest Checkout</h4>
            <p style="color: #666; margin-bottom: 15px;">Enter your email to receive your booking confirmation.</p>
            <div class="form-group" style="margin-bottom: 0;">
                <label for="guest_email" style="font-weight: bold; color: #16213e;">Email Address *</label>
                <input type="email" id="guest_email" name="guest_email" required
                       value="{{ session.get('guest_email', '') }}"
                       placeholder="your@email.com"
                       style="width: 100%; padding: 12px; border: 1px solid #ddd; border-radius: 8px; font-size: 16px;"
                       onchange="saveGuestEmail(this.value)">
            </div>
            <p style="margin-top: 10px; font-size: 12px; color: #666;">
                <a href="/register?deal={{ deal.deal_id }}" style="color: #7c3aed;">Create an account</a> to track your bookings.
            </p>
        </div>
        {% endif %}

        <!-- Payment Selection -->
        <h3 style="margin-bottom: 20px;">Choose Payment Method</h3>

        <div class="payment-method-card" onclick="selectPayment('card')" id="method-card">
            <div class="method-header">
                <span class="method-icon">&#128179;</span>
                <div>
                    <div class="method-title">Credit or Debit Card</div>
                    <div class="method-subtitle">Visa, Mastercard, American Express</div>
                </div>
                <div style="margin-left: auto; font-weight: bold; color: #7c3aed;">
                    ${{ "%.2f"|format((deal.price_total_usd or 0) + (deal.platform_fee_usd or 0)) }}
                </div>
            </div>
            <div class="payment-details-panel" id="details-card">
                <p>Secure payment powered by Stripe. You'll be redirected to complete your payment.</p>
                <button class="btn" onclick="payWithCard(event)" style="width: 100%; margin-top: 10px;">
                    Pay ${{ "%.2f"|format((deal.price_total_usd or 0) + (deal.platform_fee_usd or 0)) }} with Card
                </button>
            </div>
        </div>

        <p style="text-align: center; color: #666; margin-top: 20px; font-size: 14px;">
            All payments are secure and encrypted<br>
            <small>By proceeding, you agree to our Terms of Service</small>
        </p>
    {% endif %}
</div>

<!-- Processing Overlay -->
<div class="processing-overlay" id="processing-overlay">
    <div class="processing-box">
        <div class="spinner"></div>
        <h3 id="processing-title">Processing Payment...</h3>
        <p id="processing-message">Please wait while we verify your payment.</p>
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
