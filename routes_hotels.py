"""
Phase 2 — Hotel Routes
Extracted from server.py (Build #136) to slim Phase 1 OTA.

All code preserved intact. Re-enable by adding to server.py:
    from routes_hotels import register_hotel_routes
    register_hotel_routes(app, csrf, limiter)

Original locations in server.py:
  - Hotel routes: lines 4032-4208
  - HOTELS_SEARCH_CONTENT: lines 5387-5613
  - HOTEL_BOOK_CONTENT: lines 5616-5917
"""

import json
import logging
from datetime import datetime, timedelta

from flask import request, jsonify, render_template_string, redirect, url_for, session
from flask_login import current_user

from models import db, Deal

logger = logging.getLogger(__name__)


# ============================================================
# HOTEL SEARCH FRONTEND (Build #101)
# ============================================================

HOTELS_SEARCH_CONTENT = """
<style>
    .hotel-search-form { max-width: 900px; margin: 0 auto 30px; }
    .hotel-search-form label { font-weight: bold; color: #f5f5f5; display: block; margin-bottom: 5px; }
    .hotel-search-form input, .hotel-search-form select {
        width: 100%; padding: 12px; border: 1px solid rgba(255,255,255,0.2);
        border-radius: 8px; font-size: 16px; color: #fff;
        background: rgba(15, 10, 25, 0.6); backdrop-filter: blur(10px);
    }
    .hotel-search-form input::placeholder { color: #999; }
    .hotel-search-form input:focus, .hotel-search-form select:focus {
        border-color: #7c3aed; outline: none; box-shadow: 0 0 0 3px rgba(124, 58, 237, 0.2);
    }
    .rating-group { display: flex; gap: 15px; flex-wrap: wrap; }
    .rating-group label { display: flex; align-items: center; cursor: pointer; font-weight: normal; color: #ccc; }
    .rating-group input { width: auto; margin-right: 6px; }
    .hotel-card { transition: all 0.3s ease; }
    .hotel-card:hover { transform: translateX(4px); border-color: rgba(124, 58, 237, 0.5); }
    .hotel-badge { font-size: 11px; padding: 2px 8px; border-radius: 4px; display: inline-block; margin-bottom: 5px; }
    .spinner-hotel { width: 50px; height: 50px; border: 4px solid rgba(255,255,255,0.1); border-top-color: #7c3aed; border-radius: 50%; animation: hotelspin 1s linear infinite; margin: 0 auto 20px; }
    @keyframes hotelspin { to { transform: rotate(360deg); } }
</style>

<div class="card hotel-search-form">
    <h1 style="text-align: center; margin-bottom: 25px; color: #f5f5f5;">Search Hotels</h1>
    <div>
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 15px;">
            <div class="form-group" style="grid-column: 1 / -1;">
                <label>City</label>
                <input type="text" id="hotel-city" placeholder="Paris, New York, Tokyo..." list="city-suggestions">
                <datalist id="city-suggestions">
                    <option value="Paris (PAR)"><option value="New York (NYC)"><option value="London (LON)">
                    <option value="Tokyo (TYO)"><option value="Rome (ROM)"><option value="Barcelona (BCN)">
                    <option value="Bangkok (BKK)"><option value="Dubai (DXB)"><option value="Singapore (SIN)">
                    <option value="Los Angeles (LAX)"><option value="San Francisco (SFO)"><option value="Miami (MIA)">
                    <option value="Chicago (CHI)"><option value="Sydney (SYD)"><option value="Hong Kong (HKG)">
                    <option value="Seoul (SEL)"><option value="Amsterdam (AMS)"><option value="Berlin (BER)">
                    <option value="Madrid (MAD)"><option value="Lisbon (LIS)"><option value="Istanbul (IST)">
                    <option value="Mexico City (MEX)"><option value="Toronto (YTO)"><option value="Osaka (OSA)">
                    <option value="Munich (MUC)"><option value="Vienna (VIE)"><option value="Prague (PRG)">
                    <option value="Dublin (DUB)"><option value="Athens (ATH)"><option value="Honolulu (HNL)">
                </datalist>
            </div>
            <div class="form-group">
                <label>Check-in</label>
                <input type="date" id="hotel-checkin">
            </div>
            <div class="form-group">
                <label>Check-out</label>
                <input type="date" id="hotel-checkout">
            </div>
            <div class="form-group">
                <label>Adults</label>
                <select id="hotel-adults">
                    <option value="1">1</option>
                    <option value="2" selected>2</option>
                    <option value="3">3</option>
                    <option value="4">4</option>
                </select>
            </div>
            <div class="form-group">
                <label>Rooms</label>
                <select id="hotel-rooms">
                    <option value="1" selected>1</option>
                    <option value="2">2</option>
                    <option value="3">3</option>
                </select>
            </div>
            <div class="form-group" style="grid-column: 1 / -1;">
                <label>Star Rating</label>
                <div class="rating-group">
                    <label><input type="checkbox" name="rating" value="3"> 3 Stars</label>
                    <label><input type="checkbox" name="rating" value="4" checked> 4 Stars</label>
                    <label><input type="checkbox" name="rating" value="5" checked> 5 Stars</label>
                </div>
            </div>
        </div>
        <button class="btn" onclick="searchHotels()" style="width: 100%; margin-top: 15px; padding: 15px; font-size: 16px;">
            Search Hotels
        </button>
    </div>
</div>

<div id="hotel-loading" style="display: none; text-align: center; padding: 40px;">
    <div class="spinner-hotel"></div>
    <p style="color: #ccc;">Searching hotels via Amadeus...</p>
</div>

<div id="hotel-results" style="display: none; max-width: 900px; margin: 0 auto;">
    <div id="hotel-results-header"></div>
    <div id="hotel-results-list" style="display: grid; gap: 20px;"></div>
</div>

<script>
const cityMap = {
    'paris': 'PAR', 'new york': 'NYC', 'london': 'LON', 'tokyo': 'TYO',
    'rome': 'ROM', 'barcelona': 'BCN', 'bangkok': 'BKK', 'dubai': 'DXB',
    'singapore': 'SIN', 'los angeles': 'LAX', 'san francisco': 'SFO', 'miami': 'MIA',
    'chicago': 'CHI', 'sydney': 'SYD', 'hong kong': 'HKG', 'seoul': 'SEL',
    'amsterdam': 'AMS', 'berlin': 'BER', 'madrid': 'MAD', 'lisbon': 'LIS',
    'istanbul': 'IST', 'mexico city': 'MEX', 'toronto': 'YTO', 'osaka': 'OSA',
    'munich': 'MUC', 'vienna': 'VIE', 'prague': 'PRG', 'dublin': 'DUB',
    'athens': 'ATH', 'honolulu': 'HNL'
};

function extractCityCode(input) {
    const match = input.match(/\\(([A-Z]{3})\\)/);
    if (match) return match[1];
    const lower = input.toLowerCase().trim();
    if (cityMap[lower]) return cityMap[lower];
    if (/^[A-Z]{3}$/.test(input.trim())) return input.trim();
    return null;
}

// Set default dates
(function() {
    const tomorrow = new Date(); tomorrow.setDate(tomorrow.getDate() + 1);
    const dayAfter = new Date(); dayAfter.setDate(dayAfter.getDate() + 3);
    document.getElementById('hotel-checkin').value = tomorrow.toISOString().split('T')[0];
    document.getElementById('hotel-checkout').value = dayAfter.toISOString().split('T')[0];
    document.getElementById('hotel-checkin').min = tomorrow.toISOString().split('T')[0];
})();

async function searchHotels() {
    const cityInput = document.getElementById('hotel-city').value;
    const cityCode = extractCityCode(cityInput);
    if (!cityCode) { alert('Please enter a valid city or IATA code (e.g. Paris, PAR, NYC)'); return; }

    const checkIn = document.getElementById('hotel-checkin').value;
    const checkOut = document.getElementById('hotel-checkout').value;
    if (!checkIn || !checkOut) { alert('Please select check-in and check-out dates'); return; }
    if (checkIn >= checkOut) { alert('Check-out date must be after check-in date'); return; }

    const adults = document.getElementById('hotel-adults').value;
    const rooms = document.getElementById('hotel-rooms').value;
    const ratings = [...document.querySelectorAll('input[name="rating"]:checked')].map(c => parseInt(c.value));

    document.getElementById('hotel-loading').style.display = 'block';
    document.getElementById('hotel-results').style.display = 'none';

    try {
        const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || '';
        const resp = await fetch('/api/hotels/search', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
            body: JSON.stringify({ city_code: cityCode, check_in: checkIn, check_out: checkOut, adults: parseInt(adults), rooms: parseInt(rooms), ratings: ratings.length > 0 ? ratings : null })
        });
        const data = await resp.json();
        renderHotelResults(data, cityCode, checkIn, checkOut);
    } catch (err) {
        document.getElementById('hotel-loading').style.display = 'none';
        alert('Search failed: ' + err.message);
    }
}

function renderHotelResults(data, cityCode, checkIn, checkOut) {
    document.getElementById('hotel-loading').style.display = 'none';
    document.getElementById('hotel-results').style.display = 'block';

    const header = document.getElementById('hotel-results-header');
    const list = document.getElementById('hotel-results-list');

    if (!data.success || !data.hotels || data.hotels.length === 0) {
        header.innerHTML = '<div class="card" style="text-align: center; padding: 40px;"><h3 style="color: #f5f5f5;">No hotels found</h3><p style="color: #ccc;">' + (data.error || 'Try different dates or city') + '</p></div>';
        list.innerHTML = '';
        return;
    }

    header.innerHTML = '<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; flex-wrap: wrap; gap: 10px;"><h2 style="color: #f5f5f5; margin: 0;">' + data.hotels.length + ' Hotels in ' + cityCode + '</h2><span style="color: #ccc;">' + checkIn + ' to ' + checkOut + '</span></div>';

    list.innerHTML = data.hotels.map(hotel => `
        <div class="card hotel-card" style="border-left: 4px solid #7c3aed;">
            <div style="display: flex; justify-content: space-between; align-items: start; flex-wrap: wrap; gap: 10px;">
                <div style="flex: 1; min-width: 200px;">
                    <span class="hotel-badge" style="background: #6d28d9; color: white;">HOTEL</span>
                    <h3 style="margin: 5px 0; color: #f5f5f5;">${hotel.hotel_name}</h3>
                    <div style="font-size: 14px; color: #ccc;">
                        ${hotel.room_type || 'Standard Room'}${hotel.bed_type ? ' / ' + hotel.bed_type : ''}
                        ${hotel.nights ? ' / ' + hotel.nights + ' night' + (hotel.nights > 1 ? 's' : '') : ''}
                    </div>
                    ${hotel.room_description ? '<div style="font-size: 13px; color: #aaa; margin-top: 5px;">' + hotel.room_description.substring(0, 120) + '</div>' : ''}
                    ${hotel.cancellation_deadline ? '<div style="font-size: 12px; color: #4caf50; margin-top: 5px;">Free cancellation until ' + hotel.cancellation_deadline.split('T')[0] + '</div>' : ''}
                </div>
                <div style="text-align: right; min-width: 140px;">
                    <div style="font-size: 24px; font-weight: bold; color: #7c3aed;">
                        $${hotel.price_per_night.toFixed(0)}<span style="font-size: 14px; font-weight: normal; color: #ccc;">/night</span>
                    </div>
                    <div style="color: #ccc; font-size: 14px;">$${hotel.price_total.toFixed(0)} total</div>
                </div>
            </div>
            <div style="margin-top: 15px; display: flex; justify-content: space-between; align-items: center; padding-top: 15px; border-top: 1px solid rgba(255,255,255,0.1);">
                <span style="color: #666; font-size: 12px;">Amadeus</span>
                <button class="btn" onclick="selectHotel('${hotel.offer_id}', '${hotel.hotel_id}', this)">
                    Book This Hotel
                </button>
            </div>
        </div>
    `).join('');
}

async function selectHotel(offerId, hotelId, btn) {
    btn.disabled = true;
    btn.textContent = 'Creating deal...';

    try {
        const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || '';
        const resp = await fetch('/api/hotels/select', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
            body: JSON.stringify({ offer_id: offerId, hotel_id: hotelId })
        });
        const data = await resp.json();
        if (data.success && data.deal_id) {
            window.location.href = '/save-deal/' + data.deal_id;
        } else {
            alert('Error: ' + (data.error || 'Failed to create hotel deal'));
            btn.disabled = false;
            btn.textContent = 'Book This Hotel';
        }
    } catch (err) {
        alert('Error: ' + err.message);
        btn.disabled = false;
        btn.textContent = 'Book This Hotel';
    }
}
</script>
"""


# ============================================================
# HOTEL BOOKING FRONTEND (Build #101)
# ============================================================

HOTEL_BOOK_CONTENT = """
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
    .crypto-address-box { background: white; border: 1px solid #ddd; border-radius: 8px; padding: 15px; font-family: monospace; font-size: 14px; word-break: break-all; margin: 10px 0; }
    .copy-btn { background: #7c3aed; color: white; border: none; padding: 8px 16px; border-radius: 6px; cursor: pointer; font-size: 14px; margin-top: 10px; }
    .copy-btn:hover { background: #6d28d9; }
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
    <h2 style="text-align: center; margin-bottom: 25px; color: #1a1a2e;">Complete Your Hotel Booking</h2>

    <!-- Order Summary -->
    <div class="order-summary">
        <h3>Hotel Reservation</h3>
        <div class="flight-leg-item">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <div>
                    <strong>{{ deal.hotel_name }}</strong><br>
                    <span style="color: #14b8a6;">{{ deal.city_code }}{{ ' - ' + deal.city_name if deal.city_name else '' }} / {{ deal.room_type or 'Standard Room' }}{{ ' / ' + deal.bed_type if deal.bed_type else '' }}</span><br>
                    <small>{{ deal.check_in_date }} to {{ deal.check_out_date }} ({{ deal.nights }} night{{ 's' if deal.nights != 1 else '' }})</small>
                </div>
                <div style="text-align: right;">
                    <span style="font-size: 18px; font-weight: bold;">${{ "%.0f"|format(deal.price_total_usd or 0) }}</span>
                    <br><small style="color: #14b8a6;">${{ "%.0f"|format(deal.price_per_night_usd or 0) }}/night</small>
                </div>
            </div>
        </div>

        <div class="order-row">
            <span>Hotel ({{ deal.nights }} night{{ 's' if deal.nights != 1 else '' }})</span>
            <span>${{ "%.2f"|format(deal.price_total_usd or 0) }}</span>
        </div>
        <div class="order-row">
            <span>Service Fee</span>
            <span>${{ "%.2f"|format(deal.platform_fee_usd or 0) }}</span>
        </div>
        <div class="order-row total">
            <span>Total Due</span>
            <span>${{ "%.2f"|format((deal.price_total_usd or 0) + (deal.platform_fee_usd or 0)) }}</span>
        </div>
        {% if deal.cancellation_policy %}
        <div style="margin-top: 10px; font-size: 13px; color: #4caf50;">
            Cancellation: {{ deal.cancellation_policy }}
        </div>
        {% endif %}
    </div>

    {% if payment_verified %}
        <!-- Payment Complete - Collect Guest Details -->
        <div class="alert alert-success" style="text-align: center; padding: 25px;">
            <span style="font-size: 48px;">&#9989;</span>
            <h3 style="margin: 15px 0;">Payment Verified!</h3>
            <p>Your payment has been confirmed. Please provide guest details to complete your booking.</p>
        </div>

        <form id="guest-form" action="/complete-booking/{{ deal.deal_id }}" method="POST" style="margin-top: 20px;">
            <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
            <div style="background: #f8f9fa; border-radius: 12px; padding: 25px;">
                <h4 style="margin: 0 0 20px 0; color: #1a1a2e;">Guest Information</h4>
                <p style="color: #666; margin-bottom: 20px;">Enter guest details as they will appear on the reservation.</p>

                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 15px;">
                    <div class="form-group">
                        <label style="font-weight: bold; color: #16213e; display: block; margin-bottom: 5px;">Title *</label>
                        <select name="title" required style="width: 100%; padding: 12px; border: 1px solid #ddd; border-radius: 8px; font-size: 16px; color: #1a1a2e;">
                            <option value="MR">Mr</option>
                            <option value="MS">Ms</option>
                            <option value="MRS">Mrs</option>
                        </select>
                    </div>
                    <div></div>
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
                    <div class="form-group" style="grid-column: 1 / -1;">
                        <label style="font-weight: bold; color: #16213e; display: block; margin-bottom: 5px;">Special Requests (optional)</label>
                        <textarea name="special_requests" rows="3" placeholder="Late check-in, extra pillows, high floor..." style="width: 100%; padding: 12px; border: 1px solid #ddd; border-radius: 8px; font-size: 16px; color: #1a1a2e; resize: vertical;"></textarea>
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
                    Complete Hotel Booking
                </button>
            </div>
        </form>

    {% else %}
        <!-- Guest Email Collection (for non-authenticated users) -->
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

        <!-- Credit Card -->
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

        {% if feature_xrp_payments %}
        <!-- XRP Direct (Phase 2) -->
        <div class="payment-method-card" onclick="selectPayment('xrp')" id="method-xrp">
            <div class="method-header">
                <span class="method-icon">&#9889;</span>
                <div>
                    <div class="method-title">XRP (Direct)</div>
                    <div class="method-subtitle">Pay directly on XRPL</div>
                </div>
                <div style="margin-left: auto; font-weight: bold; color: #7c3aed;">
                    {{ "%.4f"|format(payment_options.methods.xrp.amount_xrp or 0) }} XRP
                </div>
            </div>
            <div class="payment-details-panel" id="details-xrp">
                <p><strong>Send exactly:</strong></p>
                <div class="crypto-address-box">{{ "%.6f"|format(payment_options.methods.xrp.amount_xrp or 0) }} XRP</div>
                <p><strong>To address:</strong></p>
                <div class="crypto-address-box" id="xrp-address">{{ payment_options.methods.xrp.destination or platform_wallet }}</div>
                <button class="copy-btn" onclick="copyToClipboard('xrp-address', event)">Copy Address</button>
                <p style="margin-top: 15px;"><strong>Destination Tag:</strong></p>
                <div class="crypto-address-box" style="background: #f0fdfa; border-color: #14b8a6;" id="xrp-tag">{{ payment_options.methods.xrp.destination_tag or deal.destination_tag }}</div>
                <button class="copy-btn" onclick="copyToClipboard('xrp-tag', event)">Copy Tag</button>
                <div style="background: #f8d7da; color: #721c24; padding: 12px; border-radius: 8px; margin-top: 15px;">
                    <strong>Warning:</strong> You MUST include the destination tag.
                </div>
                <p style="margin-top: 15px; color: #666;">Network: {{ network }}</p>
                <form method="POST" style="margin-top: 15px;" onsubmit="return validateGuestEmail()">
                    <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
                    <input type="hidden" name="payment_method" value="xrp">
                    <input type="hidden" name="guest_email" id="xrp_guest_email" value="">
                    <button type="submit" class="btn" style="width: 100%;" onclick="document.getElementById('xrp_guest_email').value = getGuestEmail();">
                        I've Sent the Payment - Verify Now
                    </button>
                </form>
            </div>
        </div>
        {% endif %}

        {% if feature_rlusd_payments %}
        <!-- RLUSD Stablecoin (Phase 2) -->
        <div class="payment-method-card" onclick="selectPayment('rlusd')" id="method-rlusd">
            <div class="method-header">
                <span class="method-icon">&#128181;</span>
                <div>
                    <div class="method-title">RLUSD Stablecoin</div>
                    <div class="method-subtitle">Ripple's USD stablecoin on XRPL</div>
                </div>
                <div style="margin-left: auto; font-weight: bold; color: #7c3aed;">
                    ${{ "%.2f"|format((deal.price_total_usd or 0) + (deal.platform_fee_usd or 0)) }} RLUSD
                </div>
            </div>
            <div class="payment-details-panel" id="details-rlusd">
                <p><strong>Send exactly:</strong></p>
                <div class="crypto-address-box">{{ "%.2f"|format((deal.price_total_usd or 0) + (deal.platform_fee_usd or 0)) }} RLUSD</div>
                <p><strong>To address:</strong></p>
                <div class="crypto-address-box" id="rlusd-address">{{ payment_options.methods.rlusd.destination or platform_wallet }}</div>
                <button class="copy-btn" onclick="copyToClipboard('rlusd-address', event)">Copy Address</button>
                <p style="margin-top: 15px;"><strong>Destination Tag:</strong></p>
                <div class="crypto-address-box" style="background: #f0fdfa;" id="rlusd-tag">{{ payment_options.methods.rlusd.destination_tag or deal.destination_tag }}</div>
                <button class="copy-btn" onclick="copyToClipboard('rlusd-tag', event)">Copy Tag</button>
                <form method="POST" style="margin-top: 15px;" onsubmit="return validateGuestEmail()">
                    <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
                    <input type="hidden" name="payment_method" value="rlusd">
                    <input type="hidden" name="guest_email" id="rlusd_guest_email" value="">
                    <button type="submit" class="btn" style="width: 100%;" onclick="document.getElementById('rlusd_guest_email').value = getGuestEmail();">
                        I've Sent RLUSD - Verify Now
                    </button>
                </form>
            </div>
        </div>
        {% endif %}

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
function getGuestEmail() { const el = document.getElementById('guest_email'); return el ? el.value : guestEmail; }
function validateGuestEmail() { const el = document.getElementById('guest_email'); if (el && !el.value) { alert('Please enter your email address.'); el.focus(); return false; } return true; }

function selectPayment(method) {
    document.querySelectorAll('.payment-method-card').forEach(c => c.classList.remove('selected'));
    document.querySelectorAll('.payment-details-panel').forEach(p => p.classList.remove('active'));
    document.getElementById('method-' + method).classList.add('selected');
    document.getElementById('details-' + method).classList.add('active');
}
function copyToClipboard(elementId, event) {
    event.stopPropagation();
    const text = document.getElementById(elementId).innerText.trim();
    navigator.clipboard.writeText(text).then(() => { const btn = event.target; btn.textContent = 'Copied!'; setTimeout(() => btn.textContent = 'Copy', 2000); });
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

// Coinbase crypto payments removed — Stripe + MoonPay only
</script>
"""


def register_hotel_routes(app, csrf, limiter):
    """Register all Phase 2 hotel routes on the Flask app.

    Requires:
      - is_feature_enabled() to be defined on app or imported
      - BASE_TEMPLATE to be available (import from server)
    """
    # Import here to avoid circular imports at module level
    from server import BASE_TEMPLATE, is_feature_enabled

    @app.route("/hotels")
    def hotels():
        """Hotel search page."""
        if not is_feature_enabled("vertical_hotels"):
            return redirect(url_for("home"))
        return render_template_string(
            BASE_TEMPLATE,
            title="Hotels",
            content=render_template_string(HOTELS_SEARCH_CONTENT, current_user=current_user),
            current_user=current_user
        )

    @app.route("/api/hotels/search", methods=["POST"])
    @csrf.exempt
    def api_hotel_search():
        """Search hotels via liteAPI."""
        if not is_feature_enabled("vertical_hotels"):
            return jsonify({"success": False, "error": "Hotel search is not available yet"}), 410
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "No data provided"}), 400

        city_code = data.get("city_code", "").upper()
        check_in = data.get("check_in")
        check_out = data.get("check_out")
        adults = data.get("adults", 1)
        rooms = data.get("rooms", 1)
        ratings = data.get("ratings")

        if not city_code or len(city_code) != 3:
            return jsonify({"success": False, "error": "Valid 3-letter city code required"}), 400
        if not check_in or not check_out:
            return jsonify({"success": False, "error": "Check-in and check-out dates required"}), 400

        try:
            from liteapi_client import LiteAPIHotelClient
            client = LiteAPIHotelClient()

            result = client.search_hotels(
                city_code=city_code,
                check_in=check_in,
                check_out=check_out,
                adults=adults,
                rooms=rooms,
                currency="USD",
                ratings=ratings,
                max_hotels=20,
                user=current_user,
            )

            # Track hotel search metric
            try:
                from monitoring import track_search
                track_search(origin=city_code, destination=city_code, market="hotel")
            except Exception:
                pass

            if not result.get("success"):
                return jsonify({"success": False, "error": result.get("error", "No hotels found"), "hotels": []})

            hotels = []
            for h in result.get("hotels", []):
                hotels.append({
                    "hotel_id": h.get("hotel_id"),
                    "hotel_name": h.get("hotel_name", "Unknown Hotel"),
                    "offer_id": h.get("offer_id"),
                    "city_code": h.get("city_code"),
                    "check_in": h.get("check_in"),
                    "check_out": h.get("check_out"),
                    "nights": h.get("nights", 1),
                    "price_total": h.get("price_total", 0),
                    "price_per_night": h.get("price_per_night", 0),
                    "currency": h.get("currency", "USD"),
                    "room_type": h.get("room_type"),
                    "bed_type": h.get("bed_type"),
                    "room_description": h.get("room_description", ""),
                    "cancellation_deadline": h.get("cancellation_deadline"),
                    "cancellation_description": h.get("cancellation_description"),
                    "adults": h.get("adults"),
                    "rooms": h.get("rooms"),
                })

            # Cache full results in session for hotel selection
            session['hotel_search_results'] = {h.get("offer_id"): h for h in result.get("hotels", []) if h.get("offer_id")}

            hotels.sort(key=lambda x: x["price_per_night"])

            return jsonify({
                "success": True,
                "hotels": hotels,
                "count": len(hotels),
                "city_code": city_code,
                "check_in": check_in,
                "check_out": check_out,
            })

        except Exception as e:
            logger.error(f"Hotel search error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @app.route("/api/hotels/select", methods=["POST"])
    @csrf.exempt
    def api_hotel_select():
        """Create a Deal record from a selected hotel offer for checkout."""
        if not is_feature_enabled("vertical_hotels"):
            return jsonify({"success": False, "error": "Hotel booking is not available yet"}), 410
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "No data provided"}), 400

        offer_id = data.get("offer_id")
        if not offer_id:
            return jsonify({"success": False, "error": "Offer ID required"}), 400

        try:
            cached = session.get('hotel_search_results', {})
            hotel_data = cached.get(offer_id)

            if not hotel_data:
                return jsonify({"success": False, "error": "Offer expired. Please search again."}), 400

            import secrets as _secrets
            deal_id = _secrets.token_hex(8)
            destination_tag = abs(hash(deal_id)) % 2147483647

            HOTEL_PLATFORM_FEE = 15.00
            total_price = float(hotel_data.get("price_total", 0))
            nights = hotel_data.get("nights", 1)
            price_per_night = float(hotel_data.get("price_per_night", 0))

            deal = Deal(
                deal_id=deal_id,
                deal_type="hotel",
                hotel_name=hotel_data.get("hotel_name", "Unknown Hotel"),
                hotel_id=hotel_data.get("hotel_id"),
                hotel_offer_id=offer_id,
                city_code=hotel_data.get("city_code"),
                check_in_date=datetime.strptime(hotel_data["check_in"], "%Y-%m-%d").date() if hotel_data.get("check_in") else None,
                check_out_date=datetime.strptime(hotel_data["check_out"], "%Y-%m-%d").date() if hotel_data.get("check_out") else None,
                nights=nights,
                rooms=hotel_data.get("rooms", 1),
                adults=hotel_data.get("adults", 1),
                room_type=hotel_data.get("room_type"),
                bed_type=hotel_data.get("bed_type"),
                room_description=hotel_data.get("room_description"),
                price_per_night_usd=price_per_night,
                price_total_usd=total_price,
                cancellation_policy=hotel_data.get("cancellation_description"),
                home_price_usd=total_price,
                arbitrage_price_usd=total_price,
                platform_fee_usd=HOTEL_PLATFORM_FEE,
                user_savings_usd=0,
                gross_savings_usd=0,
                savings_percent=0,
                destination_tag=destination_tag,
                amadeus_offer_data=json.dumps(hotel_data.get("raw_offer")) if hotel_data.get("raw_offer") else None,
                is_active=True,
                expires_at=datetime.utcnow() + timedelta(hours=1),
                created_at=datetime.utcnow(),
            )

            db.session.add(deal)
            db.session.commit()

            return jsonify({
                "success": True,
                "deal_id": deal_id,
                "hotel_name": deal.hotel_name,
                "total_price": total_price + HOTEL_PLATFORM_FEE,
                "redirect_url": f"/save-deal/{deal_id}",
            })

        except Exception as e:
            logger.error(f"Hotel select error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
