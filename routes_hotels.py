"""
Phase 2 — Hotel Routes (Build #166 — Premium UI)
Hotels vertical for MYSTES consumer OTA.

Register in server.py:
    from routes_hotels import register_hotel_routes
    register_hotel_routes(app, csrf, limiter)
"""

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

from flask import request, jsonify, render_template_string, redirect, url_for, session
from flask_login import current_user

from models import db, Deal

logger = logging.getLogger(__name__)


# ============================================================
# HOTEL SEARCH FRONTEND — Premium MYSTES Design (Build #166)
# ============================================================

HOTELS_SEARCH_CONTENT = """
<style>
/* ============================================
   HOTELS PAGE — Page-specific styles only
   (glass card, form elements, buttons, spinners,
    skeletons provided by mystes-* component library)
   ============================================ */

.hotels-page { max-width: 960px; margin: 0 auto; padding: 0 16px; }

/* Extra padding on search card */
.hotel-search-card { padding: 28px; margin-bottom: 24px; }

/* Star rating chips (page-specific) */
.star-chips { display: flex; gap: 8px; flex-wrap: wrap; }
.star-chip {
    display: flex; align-items: center; gap: 6px;
    padding: 8px 14px; border-radius: 20px;
    background: rgba(255,255,255,0.06);
    border: 1px solid rgba(255,255,255,0.12);
    cursor: pointer; transition: all 0.2s;
    font-size: 13px; color: #ccc;
}
.star-chip:hover { border-color: rgba(124,58,237,0.4); }
.star-chip input { display: none; }
.star-chip.active {
    background: rgba(124,58,237,0.15);
    border-color: #7c3aed;
    color: #fff;
}
.star-chip-star { color: #f59e0b; }

/* Search button top margin */
.hotel-search-btn { margin-top: 18px; }

/* Loading skeleton container (page-specific layout) */
.hotel-loading-state {
    margin-top: 20px; padding: 30px;
    background: rgba(15, 10, 25, 0.6);
    border-radius: 16px;
    border: 1px solid rgba(124, 58, 237, 0.2);
}
.hotel-loading-header {
    display: flex; align-items: center; gap: 16px; margin-bottom: 24px;
}
.hotel-skeleton-cards { display: flex; flex-direction: column; gap: 12px; }
.hotel-skeleton-card {
    background: rgba(255,255,255,0.05); border-radius: 12px;
    padding: 20px; display: flex; gap: 16px;
}
.hotel-skeleton-img {
    width: 120px; height: 90px; border-radius: 8px; flex-shrink: 0;
}
.hotel-skeleton-line {
    height: 14px; border-radius: 6px;
}
.hotel-skeleton-line.w40 { width: 40%; }
.hotel-skeleton-line.w60 { width: 60%; }
.hotel-skeleton-line.w30 { width: 30%; }

/* Results header + controls */
.hotel-results-bar {
    display: flex; justify-content: space-between; align-items: center;
    flex-wrap: wrap; gap: 12px; margin-bottom: 16px;
}
.hotel-results-count {
    color: #f5f5f5; font-size: 18px; font-weight: 600; margin: 0;
}
.hotel-results-dates { color: #999; font-size: 13px; }
.hotel-controls {
    display: flex; gap: 8px; align-items: center; flex-wrap: wrap;
}
.hotel-filter-chip {
    display: flex; align-items: center; gap: 6px;
    padding: 7px 12px; border-radius: 20px;
    background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.12);
    cursor: pointer; font-size: 12px; color: #ccc; transition: all 0.2s;
}
.hotel-filter-chip:hover { border-color: rgba(76,175,80,0.4); }
.hotel-filter-chip.active {
    background: rgba(76,175,80,0.12); border-color: #4caf50; color: #4caf50;
}
.hotel-filter-chip input { display: none; }

/* ============================================
   HOTEL RESULT CARDS (page-specific)
   ============================================ */

.hotel-cards-grid { display: flex; flex-direction: column; gap: 14px; }

.hotel-card {
    background: rgba(255,255,255,0.03);
    border: 1px solid rgba(255,255,255,0.1);
    border-radius: 12px;
    position: relative;
    transition: all 0.2s ease;
    overflow: hidden;
}
.hotel-card:hover {
    background: rgba(255,255,255,0.06);
    border-color: rgba(124, 58, 237, 0.3);
    transform: translateY(-2px);
    box-shadow: 0 8px 30px rgba(0,0,0,0.3);
}
.hotel-card-deal { border-color: rgba(40, 167, 69, 0.4); }

.hotel-card-badge {
    position: absolute; top: 12px; right: 12px; z-index: 2;
    background: linear-gradient(135deg, #28a745, #20c997);
    color: white; padding: 4px 12px; border-radius: 16px;
    font-size: 11px; font-weight: 700;
}

.hotel-card-inner { display: flex; }

.hotel-card-image {
    width: 200px; min-height: 180px; flex-shrink: 0;
    background: linear-gradient(135deg, rgba(124,58,237,0.15), rgba(109,40,217,0.08));
    display: flex; align-items: center; justify-content: center;
    position: relative; overflow: hidden;
}
.hotel-card-image-icon { font-size: 48px; opacity: 0.3; }
.hotel-card-image img {
    width: 100%; height: 100%; object-fit: cover;
    position: absolute; top: 0; left: 0;
}

.hotel-card-details {
    flex: 1; padding: 18px 20px; display: flex;
    flex-direction: column; justify-content: space-between; min-width: 0;
}
.hotel-card-name {
    font-size: 17px; font-weight: 600; color: #fff;
    margin: 0 0 4px; line-height: 1.3;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.hotel-card-room { font-size: 13px; color: #aaa; margin-bottom: 6px; }

.hotel-card-tags { display: flex; flex-wrap: wrap; gap: 4px; margin: 6px 0; }
.hotel-tag {
    font-size: 11px; padding: 2px 8px; border-radius: 4px;
    background: rgba(255,255,255,0.08); color: #ccc;
    border: 1px solid rgba(255,255,255,0.08); white-space: nowrap;
}
.hotel-tag-cancel {
    background: rgba(76,175,80,0.1); color: #4caf50;
    border-color: rgba(76,175,80,0.2);
}
.hotel-tag-board {
    background: rgba(124,58,237,0.1); color: #a78bfa;
    border-color: rgba(124,58,237,0.2);
}

.hotel-card-bottom {
    display: flex; justify-content: space-between;
    align-items: flex-end; gap: 12px;
    padding-top: 12px; border-top: 1px solid rgba(255,255,255,0.06);
}
.hotel-card-pricing { display: flex; flex-direction: column; }
.hotel-card-price-label {
    font-size: 11px; color: #999; text-transform: uppercase; letter-spacing: 0.5px;
}
.hotel-card-price-value { font-size: 24px; font-weight: 700; color: #4ade80; }
.hotel-card-price-unit { font-size: 13px; font-weight: 400; color: #999; }
.hotel-card-price-total { font-size: 12px; color: #888; margin-top: 2px; }
.hotel-card-retail { display: flex; flex-direction: column; align-items: flex-end; }
.hotel-card-price-strike { font-size: 15px; color: #888; text-decoration: line-through; }
.hotel-card-savings {
    font-size: 12px; font-weight: 600; color: #4ade80;
    background: rgba(40,167,69,0.1); padding: 2px 8px;
    border-radius: 10px; margin-top: 2px;
}

.hotel-card-cta {
    width: 100%; padding: 12px;
    border: 1px solid rgba(124, 58, 237, 0.4);
    background: rgba(124, 58, 237, 0.1);
    color: #fff; font-size: 14px; font-weight: 600;
    border-radius: 0 0 12px 12px;
    cursor: pointer; transition: all 0.2s;
    font-family: var(--font-sans, 'Outfit', sans-serif);
}
.hotel-card-cta:hover { background: rgba(124, 58, 237, 0.25); border-color: #7c3aed; }
.hotel-card-cta-deal {
    background: linear-gradient(135deg, #28a745, #20c997);
    border: none; color: white;
}
.hotel-card-cta-deal:hover {
    background: linear-gradient(135deg, #218838, #1aab8a);
    box-shadow: 0 4px 15px rgba(40, 167, 69, 0.3);
}

/* Typeahead dropdown (page-specific) */
.hotel-typeahead-wrap { position: relative; }
.hotel-typeahead-dropdown {
    position: absolute; top: 100%; left: 0; right: 0; z-index: 100;
    background: rgba(20, 15, 35, 0.98); border: 1px solid rgba(124, 58, 237, 0.4);
    border-top: none; border-radius: 0 0 8px 8px; max-height: 280px;
    overflow-y: auto; display: none;
}
.hotel-typeahead-dropdown.open { display: block; }
.hotel-typeahead-item {
    padding: 10px 14px; cursor: pointer; border-bottom: 1px solid rgba(255,255,255,0.05);
    transition: background 0.15s;
}
.hotel-typeahead-item:hover, .hotel-typeahead-item.active {
    background: rgba(124, 58, 237, 0.15);
}
.hotel-typeahead-item-name { color: #f5f5f5; font-size: 14px; font-weight: 500; }
.hotel-typeahead-item-sub { color: #888; font-size: 12px; margin-top: 2px; }
.hotel-typeahead-loading { padding: 12px 14px; color: #888; font-size: 13px; text-align: center; }

/* Responsive */
@media (max-width: 700px) {
    .hotel-card-inner { flex-direction: column; }
    .hotel-card-image { width: 100%; min-height: 140px; max-height: 180px; }
    .hotel-results-bar { flex-direction: column; align-items: flex-start; }
    .hotel-card-name { white-space: normal; }
    .hotel-card-bottom { flex-direction: column; align-items: flex-start; gap: 8px; }
    .hotel-card-retail { align-items: flex-start; }
}
</style>

<div class="hotels-page">
    <div class="mystes-page-header">
        <h1>HOTELS</h1>
        <p>Wholesale rates. Real savings. Powered by MYSTES.</p>
    </div>

    <!-- Search Form -->
    <div class="mystes-card hotel-search-card">
        <div class="mystes-form-grid">
            <div class="form-group full-width">
                <label class="mystes-label">Destination</label>
                <div class="hotel-typeahead-wrap">
                    <input type="text" id="hotel-city" class="mystes-input" placeholder="Search hotels, cities, or neighborhoods..." autocomplete="off">
                    <input type="hidden" id="hotel-lat">
                    <input type="hidden" id="hotel-lng">
                    <input type="hidden" id="hotel-city-code">
                    <div class="hotel-typeahead-dropdown" id="hotel-suggest-dropdown"></div>
                </div>
            </div>
            <div class="form-group">
                <label class="mystes-label">Check-in</label>
                <input type="date" id="hotel-checkin" class="mystes-input">
            </div>
            <div class="form-group">
                <label class="mystes-label">Check-out</label>
                <input type="date" id="hotel-checkout" class="mystes-input">
            </div>
            <div class="form-group">
                <label class="mystes-label">Guests</label>
                <select id="hotel-adults" class="mystes-select">
                    <option value="1">1 Guest</option>
                    <option value="2" selected>2 Guests</option>
                    <option value="3">3 Guests</option>
                    <option value="4">4 Guests</option>
                </select>
            </div>
            <div class="form-group">
                <label class="mystes-label">Rooms</label>
                <select id="hotel-rooms" class="mystes-select">
                    <option value="1" selected>1 Room</option>
                    <option value="2">2 Rooms</option>
                    <option value="3">3 Rooms</option>
                </select>
            </div>
            <div class="form-group full-width">
                <label class="mystes-label">Star Rating</label>
                <div class="star-chips">
                    <label class="star-chip" onclick="this.classList.toggle('active')">
                        <input type="checkbox" name="rating" value="3">
                        <span class="star-chip-star">&#9733;&#9733;&#9733;</span> 3 Star
                    </label>
                    <label class="star-chip active" onclick="this.classList.toggle('active')">
                        <input type="checkbox" name="rating" value="4" checked>
                        <span class="star-chip-star">&#9733;&#9733;&#9733;&#9733;</span> 4 Star
                    </label>
                    <label class="star-chip active" onclick="this.classList.toggle('active')">
                        <input type="checkbox" name="rating" value="5" checked>
                        <span class="star-chip-star">&#9733;&#9733;&#9733;&#9733;&#9733;</span> 5 Star
                    </label>
                </div>
            </div>
        </div>
        <button class="mystes-btn mystes-btn-primary mystes-btn-full hotel-search-btn" id="hotel-search-btn" onclick="searchHotels()">
            Search Hotels
        </button>
    </div>

    <!-- Loading State -->
    <div id="hotel-loading" style="display: none;">
        <div class="hotel-loading-state">
            <div class="hotel-loading-header">
                <div class="mystes-spinner"></div>
                <div>
                    <div style="color: #f5f5f5; font-size: 16px; font-weight: 600;">Searching wholesale rates...</div>
                    <div style="color: #999; font-size: 13px; margin-top: 4px;">Comparing prices across suppliers</div>
                </div>
            </div>
            <div class="hotel-skeleton-cards">
                <div class="hotel-skeleton-card">
                    <div class="hotel-skeleton-img mystes-skeleton"></div>
                    <div style="flex:1; display:flex; flex-direction:column; gap:10px;">
                        <div class="hotel-skeleton-line mystes-skeleton w60"></div>
                        <div class="hotel-skeleton-line mystes-skeleton w40"></div>
                        <div class="hotel-skeleton-line mystes-skeleton w30"></div>
                    </div>
                </div>
                <div class="hotel-skeleton-card">
                    <div class="hotel-skeleton-img mystes-skeleton"></div>
                    <div style="flex:1; display:flex; flex-direction:column; gap:10px;">
                        <div class="hotel-skeleton-line mystes-skeleton w60"></div>
                        <div class="hotel-skeleton-line mystes-skeleton w40"></div>
                        <div class="hotel-skeleton-line mystes-skeleton w30"></div>
                    </div>
                </div>
                <div class="hotel-skeleton-card">
                    <div class="hotel-skeleton-img mystes-skeleton"></div>
                    <div style="flex:1; display:flex; flex-direction:column; gap:10px;">
                        <div class="hotel-skeleton-line mystes-skeleton w60"></div>
                        <div class="hotel-skeleton-line mystes-skeleton w40"></div>
                        <div class="hotel-skeleton-line mystes-skeleton w30"></div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <!-- Results -->
    <div id="hotel-results" style="display: none;">
        <div id="hotel-results-header"></div>
        <div id="hotel-results-list" class="hotel-cards-grid"></div>
    </div>
</div>

<script>
let allHotels = [];
let suggestTimer = null;
let selectedDestination = null;

// Typeahead: debounced suggestions from Duffel Stays API
(function setupTypeahead() {
    const input = document.getElementById('hotel-city');
    const dropdown = document.getElementById('hotel-suggest-dropdown');
    if (!input || !dropdown) return;

    input.addEventListener('input', function() {
        const q = this.value.trim();
        // Clear selection when user types
        document.getElementById('hotel-lat').value = '';
        document.getElementById('hotel-lng').value = '';
        selectedDestination = null;

        if (q.length < 3) { dropdown.classList.remove('open'); return; }
        clearTimeout(suggestTimer);
        suggestTimer = setTimeout(() => fetchSuggestions(q), 300);
    });

    input.addEventListener('blur', function() {
        setTimeout(() => dropdown.classList.remove('open'), 200);
    });
    input.addEventListener('focus', function() {
        if (dropdown.children.length > 0 && this.value.length >= 3) dropdown.classList.add('open');
    });
})();

async function fetchSuggestions(query) {
    const dropdown = document.getElementById('hotel-suggest-dropdown');
    dropdown.innerHTML = '<div class="hotel-typeahead-loading">Searching...</div>';
    dropdown.classList.add('open');
    try {
        const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || '';
        const resp = await fetch('/api/hotels/suggest', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
            body: JSON.stringify({ query: query })
        });
        const data = await resp.json();
        if (!data.success || !data.suggestions || !data.suggestions.length) {
            dropdown.innerHTML = '<div class="hotel-typeahead-loading">No results found</div>';
            return;
        }
        dropdown.innerHTML = data.suggestions.map((s, i) => {
            const loc = s.location || {};
            const geo = loc.geographic_coordinates || loc;
            const lat = geo.latitude || '';
            const lng = geo.longitude || '';
            const sub = s.type === 'accommodation' ? 'Hotel' : (s.type || 'Location');
            return '<div class="hotel-typeahead-item" data-lat="' + lat + '" data-lng="' + lng + '" data-name="' + (s.name || '').replace(/"/g, '&quot;') + '" data-id="' + (s.id || '') + '" onclick="selectSuggestion(this)">' +
                '<div class="hotel-typeahead-item-name">' + (s.name || 'Unknown') + '</div>' +
                '<div class="hotel-typeahead-item-sub">' + sub + '</div></div>';
        }).join('');
    } catch (err) {
        dropdown.innerHTML = '<div class="hotel-typeahead-loading">Search failed</div>';
    }
}

function selectSuggestion(el) {
    const name = el.dataset.name;
    const lat = el.dataset.lat;
    const lng = el.dataset.lng;
    document.getElementById('hotel-city').value = name;
    document.getElementById('hotel-lat').value = lat;
    document.getElementById('hotel-lng').value = lng;
    selectedDestination = { name: name, lat: parseFloat(lat), lng: parseFloat(lng) };
    document.getElementById('hotel-suggest-dropdown').classList.remove('open');
}

(function() {
    const tomorrow = new Date(); tomorrow.setDate(tomorrow.getDate() + 1);
    const dayAfter = new Date(); dayAfter.setDate(dayAfter.getDate() + 3);
    document.getElementById('hotel-checkin').value = tomorrow.toISOString().split('T')[0];
    document.getElementById('hotel-checkout').value = dayAfter.toISOString().split('T')[0];
    document.getElementById('hotel-checkin').min = tomorrow.toISOString().split('T')[0];
    document.getElementById('hotel-checkin').addEventListener('change', function() {
        const next = new Date(this.value);
        next.setDate(next.getDate() + 1);
        document.getElementById('hotel-checkout').min = next.toISOString().split('T')[0];
        if (document.getElementById('hotel-checkout').value <= this.value) {
            document.getElementById('hotel-checkout').value = next.toISOString().split('T')[0];
        }
    });
    const params = new URLSearchParams(window.location.search);
    if (params.get('city')) document.getElementById('hotel-city').value = params.get('city');
    if (params.get('checkin')) document.getElementById('hotel-checkin').value = params.get('checkin');
    if (params.get('checkout')) document.getElementById('hotel-checkout').value = params.get('checkout');
})();

async function searchHotels() {
    const cityInput = document.getElementById('hotel-city').value.trim();
    if (!cityInput) { alert('Please enter a destination'); return; }
    const lat = document.getElementById('hotel-lat').value;
    const lng = document.getElementById('hotel-lng').value;
    const checkIn = document.getElementById('hotel-checkin').value;
    const checkOut = document.getElementById('hotel-checkout').value;
    if (!checkIn || !checkOut) { alert('Please select check-in and check-out dates'); return; }
    if (checkIn >= checkOut) { alert('Check-out must be after check-in'); return; }
    const adults = document.getElementById('hotel-adults').value;
    const rooms = document.getElementById('hotel-rooms').value;
    const ratings = [...document.querySelectorAll('input[name="rating"]:checked')].map(c => parseInt(c.value));

    const btn = document.getElementById('hotel-search-btn');
    btn.disabled = true;
    btn.innerHTML = '<span class="mystes-spinner-sm mystes-spinner-white" style="display:inline-block;vertical-align:middle;margin-right:8px;"></span>Searching...';
    document.getElementById('hotel-loading').style.display = 'block';
    document.getElementById('hotel-results').style.display = 'none';

    try {
        const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || '';
        const body = {
            check_in: checkIn, check_out: checkOut,
            adults: parseInt(adults), rooms: parseInt(rooms),
            ratings: ratings.length > 0 ? ratings : null,
            destination_name: cityInput,
        };
        if (lat && lng) { body.latitude = parseFloat(lat); body.longitude = parseFloat(lng); }
        const resp = await fetch('/api/hotels/search', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
            body: JSON.stringify(body)
        });
        const data = await resp.json();
        allHotels = data.hotels || [];
        renderHotelResults(data, cityInput, checkIn, checkOut);
    } catch (err) {
        document.getElementById('hotel-loading').style.display = 'none';
        alert('Search failed: ' + err.message);
    } finally {
        btn.disabled = false;
        btn.innerHTML = 'Search Hotels';
    }
}

function renderHotelResults(data, destination, checkIn, checkOut) {
    document.getElementById('hotel-loading').style.display = 'none';
    document.getElementById('hotel-results').style.display = 'block';
    const header = document.getElementById('hotel-results-header');
    const list = document.getElementById('hotel-results-list');
    const displayCity = destination;

    if (!data.success || !allHotels.length) {
        header.innerHTML = '';
        list.innerHTML = '<div class="mystes-empty"><div class="mystes-empty-icon">&#127960;</div><h3 style="color:#f5f5f5; margin:0 0 8px;">No hotels found</h3><p>' + (data.error || 'Try different dates or destination') + '</p></div>';
        return;
    }

    const dealsCount = allHotels.filter(h => h.user_savings > 0).length;
    header.innerHTML = `
        <div class="hotel-results-bar">
            <div>
                <h2 class="hotel-results-count">${allHotels.length} Hotels in ${displayCity}</h2>
                <div class="hotel-results-dates">${checkIn} to ${checkOut}${dealsCount ? ' &middot; <span style="color:#4ade80;">' + dealsCount + ' with savings</span>' : ''}</div>
            </div>
            <div class="hotel-controls">
                <select class="mystes-select" id="hotel-sort" onchange="sortAndRender()" style="padding:8px 12px;font-size:13px;width:auto;">
                    <option value="price-asc">Price: Low to High</option>
                    <option value="price-desc">Price: High to Low</option>
                    <option value="savings">Best Savings</option>
                </select>
                <label class="hotel-filter-chip" id="filter-cancel" onclick="this.classList.toggle('active'); sortAndRender();">
                    <input type="checkbox"> &#10003; Free Cancellation
                </label>
            </div>
        </div>
    `;
    renderCards(allHotels);
}

function sortAndRender() {
    let filtered = [...allHotels];
    if (document.getElementById('filter-cancel')?.classList.contains('active')) {
        filtered = filtered.filter(h => h.cancellation_description && h.cancellation_description.toLowerCase().includes('free'));
    }
    const sort = document.getElementById('hotel-sort')?.value || 'price-asc';
    if (sort === 'price-asc') filtered.sort((a,b) => a.price_per_night - b.price_per_night);
    else if (sort === 'price-desc') filtered.sort((a,b) => b.price_per_night - a.price_per_night);
    else if (sort === 'savings') filtered.sort((a,b) => (b.user_savings || 0) - (a.user_savings || 0));
    renderCards(filtered);
}

function renderCards(hotels) {
    const list = document.getElementById('hotel-results-list');
    if (!hotels.length) {
        list.innerHTML = '<div class="mystes-empty"><p>No hotels match your filters</p></div>';
        return;
    }
    list.innerHTML = hotels.map(h => {
        const hasDeal = h.user_savings > 0;
        const nights = h.nights || 1;
        let tags = '';
        if (h.cancellation_description && h.cancellation_description.toLowerCase().includes('free')) {
            tags += '<span class="hotel-tag hotel-tag-cancel">Free Cancellation</span>';
        } else if (h.cancellation_description === 'Non-refundable') {
            tags += '<span class="hotel-tag">Non-refundable</span>';
        }
        if (h.room_description && h.room_description.toLowerCase().includes('breakfast')) {
            tags += '<span class="hotel-tag hotel-tag-board">Breakfast Included</span>';
        }
        tags += '<span class="hotel-tag">' + nights + ' night' + (nights > 1 ? 's' : '') + '</span>';

        let retailHtml = '';
        if (hasDeal && h.google_price) {
            const gpn = (h.google_price / nights).toFixed(0);
            retailHtml = `
                <div class="hotel-card-retail">
                    <span class="hotel-card-price-strike">$${gpn}/nt</span>
                    <span class="hotel-card-savings">Save $${h.user_savings.toFixed(0)} (${h.savings_pct}%)</span>
                </div>`;
        }

        return `
        <div class="hotel-card${hasDeal ? ' hotel-card-deal' : ''}">
            ${hasDeal ? '<div class="hotel-card-badge">SAVE ' + h.savings_pct + '%</div>' : ''}
            <div class="hotel-card-inner">
                <div class="hotel-card-image"><span class="hotel-card-image-icon">&#127960;</span></div>
                <div class="hotel-card-details">
                    <div>
                        <h3 class="hotel-card-name">${h.hotel_name}</h3>
                        <div class="hotel-card-room">${h.room_type || 'Standard Room'}${h.bed_type && h.bed_type !== h.room_type ? ' &middot; ' + h.bed_type : ''}</div>
                        <div class="hotel-card-tags">${tags}</div>
                    </div>
                    <div class="hotel-card-bottom">
                        <div class="hotel-card-pricing">
                            <span class="hotel-card-price-label">MYSTES Price</span>
                            <div><span class="hotel-card-price-value">$${h.price_per_night.toFixed(0)}</span><span class="hotel-card-price-unit">/night</span></div>
                            <span class="hotel-card-price-total">$${h.price_total.toFixed(0)} total</span>
                        </div>
                        ${retailHtml}
                    </div>
                </div>
            </div>
            <button class="hotel-card-cta${hasDeal ? ' hotel-card-cta-deal' : ''}" onclick="selectHotel('${h.offer_id}', '${h.hotel_id}', '${h.source || 'liteapi'}', this)">
                ${hasDeal ? 'Book &amp; Save $' + h.user_savings.toFixed(0) : 'Book This Hotel'}
            </button>
        </div>`;
    }).join('');
}

async function selectHotel(offerId, hotelId, source, btn) {
    btn.disabled = true;
    const orig = btn.innerHTML;
    btn.innerHTML = '<span class="mystes-spinner-sm mystes-spinner-white" style="display:inline-block;vertical-align:middle;margin-right:8px;"></span>Creating deal...';
    try {
        const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || '';
        const resp = await fetch('/api/hotels/select', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
            body: JSON.stringify({ offer_id: offerId, hotel_id: hotelId, source: source })
        });
        const data = await resp.json();
        if (data.success && data.deal_id) {
            window.location.href = '/save-deal/' + data.deal_id;
        } else {
            alert('Error: ' + (data.error || 'Failed to create hotel deal'));
            btn.disabled = false;
            btn.innerHTML = orig;
        }
    } catch (err) {
        alert('Error: ' + err.message);
        btn.disabled = false;
        btn.innerHTML = orig;
    }
}
</script>
"""


# ============================================================
# HOTEL BOOKING FRONTEND (Build #101)
# ============================================================

HOTEL_BOOK_CONTENT = """
<style>
    /* Payment method cards — dark theme */
    .payment-method-card {
        border: 1px solid var(--glass-border, rgba(255,255,255,0.08));
        border-radius: var(--radius-lg, 12px);
        padding: 20px; margin-bottom: 15px; cursor: pointer;
        transition: all 0.2s ease;
        background: var(--glass-bg, rgba(10,6,18,0.85));
        color: var(--text-bright, #f5f5f5);
    }
    .payment-method-card:hover {
        border-color: var(--accent-purple, #7c3aed);
        box-shadow: 0 4px 12px rgba(124, 58, 237, 0.15);
    }
    .payment-method-card.selected {
        border-color: var(--accent-purple, #7c3aed);
        background: rgba(124, 58, 237, 0.08);
    }
    .payment-method-card .method-header { display: flex; align-items: center; gap: 15px; margin-bottom: 10px; }
    .payment-method-card .method-icon { font-size: 32px; width: 50px; text-align: center; }
    .payment-method-card .method-title { font-weight: bold; font-size: 18px; color: var(--text-bright, #f5f5f5); }
    .payment-method-card .method-subtitle { color: var(--text-muted, #ccc); font-size: 14px; }
    .payment-details-panel {
        display: none;
        background: rgba(255,255,255,0.04);
        border-radius: var(--radius-md, 8px);
        padding: 20px; margin-top: 15px;
        color: var(--text-bright, #f5f5f5);
    }
    .payment-details-panel.active { display: block; }
    .crypto-address-box {
        background: rgba(255,255,255,0.06);
        border: 1px solid var(--glass-border, rgba(255,255,255,0.08));
        border-radius: var(--radius-md, 8px);
        padding: 15px; font-family: monospace; font-size: 14px;
        word-break: break-all; margin: 10px 0;
        color: var(--text-bright, #f5f5f5);
    }
    /* Order summary — dark theme */
    .order-summary {
        background: rgba(15, 10, 25, 0.85);
        border: 1px solid var(--glass-border, rgba(255,255,255,0.08));
        color: var(--text-bright, #f5f5f5);
        border-radius: var(--radius-lg, 12px);
        padding: 25px; margin-bottom: 25px;
    }
    .order-summary h3 { margin: 0 0 20px 0; color: #14b8a6; }
    .order-row { display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid rgba(255,255,255,0.1); }
    .order-row:last-child { border-bottom: none; }
    .order-row.total { font-size: 20px; font-weight: bold; padding-top: 15px; margin-top: 10px; border-top: 2px solid rgba(255,255,255,0.3); }
    .flight-leg-item { background: rgba(255,255,255,0.06); border-radius: var(--radius-md, 8px); padding: 12px 15px; margin-bottom: 10px; }
    /* Guest info form — dark theme */
    .hotel-guest-form-panel {
        background: rgba(255,255,255,0.04);
        border: 1px solid var(--glass-border, rgba(255,255,255,0.08));
        border-radius: var(--radius-lg, 12px);
        padding: 25px;
    }
    .hotel-guest-form-panel h4 { margin: 0 0 20px 0; color: var(--text-bright, #f5f5f5); }
    .hotel-guest-form-panel p { color: var(--text-muted, #ccc); }
    /* Booking method panel */
    .booking-method-panel {
        margin-top: 25px; padding: 20px;
        background: rgba(124, 58, 237, 0.06);
        border: 1px solid rgba(124, 58, 237, 0.15);
        border-radius: var(--radius-md, 8px);
    }
    .booking-method-panel h5 { margin: 0 0 10px 0; color: var(--text-bright, #f5f5f5); }
    /* Guest checkout panel */
    .guest-checkout-panel {
        background: rgba(124, 58, 237, 0.06);
        border: 1px solid rgba(124, 58, 237, 0.2);
        border-radius: var(--radius-lg, 12px);
        padding: 20px; margin-bottom: 25px;
    }
    .guest-checkout-panel h4 { margin: 0 0 15px 0; color: var(--text-bright, #f5f5f5); }
    .guest-checkout-panel p { color: var(--text-muted, #ccc); }
</style>

<div class="mystes-card" style="max-width: 800px; margin: 40px auto;">
    <h2 style="text-align: center; margin-bottom: 25px; color: var(--text-bright, #f5f5f5);">Complete Your Hotel Booking</h2>

    <!-- Order Summary -->
    <div class="order-summary">
        <h3>Hotel Reservation</h3>
        <div class="flight-leg-item">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <div>
                    <strong>{{ deal.hotel_name }}</strong><br>
                    <span style="color: #14b8a6;">{{ deal.city_code }}{{ ' - ' + deal.city_name if deal.city_name else '' }} / {{ deal.room_type or 'Standard Room' }}{{ ' / ' + deal.bed_type if deal.bed_type else '' }}</span><br>
                    <small style="color: var(--text-muted, #ccc);">{{ deal.check_in_date }} to {{ deal.check_out_date }} ({{ deal.nights }} night{{ 's' if deal.nights != 1 else '' }})</small>
                </div>
                <div style="text-align: right;">
                    <span style="font-size: 18px; font-weight: bold;">${{ "%.0f"|format(deal.price_total_usd or 0) }}</span>
                    <br><small style="color: #14b8a6;">${{ "%.0f"|format(deal.price_per_night_usd or 0) }}/night</small>
                </div>
            </div>
        </div>

        <div class="order-row total">
            <span>MYSTES Price</span>
            <span>${{ "%.2f"|format((deal.price_total_usd or 0) + (deal.platform_fee_usd or 0)) }}</span>
        </div>
        {% if deal.user_savings_usd and deal.user_savings_usd > 0 %}
        <div class="order-row" style="color: #4caf50;">
            <span>You save vs retail</span>
            <span>${{ "%.0f"|format(deal.user_savings_usd or 0) }}</span>
        </div>
        {% endif %}
        {% if deal.cancellation_policy %}
        <div style="margin-top: 10px; font-size: 13px; color: #4caf50;">
            Cancellation: {{ deal.cancellation_policy }}
        </div>
        {% endif %}
    </div>

    {% if payment_verified %}
        <!-- Payment Complete - Collect Guest Details -->
        <div style="text-align: center; padding: 25px; background: rgba(34,197,94,0.08); border: 1px solid rgba(34,197,94,0.2); border-radius: var(--radius-lg, 12px); margin-bottom: 20px;">
            <span style="font-size: 48px;">&#9989;</span>
            <h3 style="margin: 15px 0; color: var(--text-bright, #f5f5f5);">Payment Verified!</h3>
            <p style="color: var(--text-muted, #ccc);">Your payment has been confirmed. Please provide guest details to complete your booking.</p>
        </div>

        <form id="guest-form" action="/complete-booking/{{ deal.deal_id }}" method="POST" style="margin-top: 20px;">
            <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
            <div class="hotel-guest-form-panel">
                <h4>Guest Information</h4>
                <p style="margin-bottom: 20px;">Enter guest details as they will appear on the reservation.</p>

                <div class="mystes-form-grid">
                    <div class="form-group">
                        <label class="mystes-label">Title *</label>
                        <select name="title" required class="mystes-select">
                            <option value="MR">Mr</option>
                            <option value="MS">Ms</option>
                            <option value="MRS">Mrs</option>
                        </select>
                    </div>
                    <div></div>
                    <div class="form-group">
                        <label class="mystes-label">First Name *</label>
                        <input type="text" name="first_name" required placeholder="John" class="mystes-input">
                    </div>
                    <div class="form-group">
                        <label class="mystes-label">Last Name *</label>
                        <input type="text" name="last_name" required placeholder="Doe" class="mystes-input">
                    </div>
                    <div class="form-group">
                        <label class="mystes-label">Email *</label>
                        <input type="email" name="email" required value="{{ passenger_email or '' }}" placeholder="john@email.com" class="mystes-input">
                    </div>
                    <div class="form-group">
                        <label class="mystes-label">Phone *</label>
                        <input type="tel" name="phone" required placeholder="+1 555-123-4567" class="mystes-input">
                    </div>
                    <div class="form-group full-width">
                        <label class="mystes-label">Special Requests (optional)</label>
                        <textarea name="special_requests" rows="3" placeholder="Late check-in, extra pillows, high floor..." class="mystes-textarea"></textarea>
                    </div>
                </div>

                <div class="booking-method-panel">
                    <h5>Booking Method</h5>
                    <label style="display: flex; align-items: center; cursor: pointer; color: var(--text-bright, #f5f5f5);">
                        <input type="radio" name="fulfillment_type" value="automated" checked style="margin-right: 10px;">
                        <span><strong>Automated Booking</strong> - We book for you (recommended)</span>
                    </label>
                </div>

                <button type="submit" class="mystes-btn mystes-btn-success mystes-btn-full mystes-btn-lg" style="margin-top: 25px;">
                    Complete Hotel Booking
                </button>
            </div>
        </form>

    {% else %}
        <!-- Guest Email Collection (for non-authenticated users) -->
        {% if not current_user.is_authenticated %}
        <div class="guest-checkout-panel">
            <h4>Guest Checkout</h4>
            <p style="margin-bottom: 15px;">Enter your email to receive your booking confirmation.</p>
            <div class="form-group" style="margin-bottom: 0;">
                <label class="mystes-label" for="guest_email">Email Address *</label>
                <input type="email" id="guest_email" name="guest_email" required
                       value="{{ session.get('guest_email', '') }}"
                       placeholder="your@email.com"
                       class="mystes-input"
                       onchange="saveGuestEmail(this.value)">
            </div>
            <p style="margin-top: 10px; font-size: 12px; color: var(--text-muted, #ccc);">
                <a href="/register?deal={{ deal.deal_id }}" style="color: var(--accent-purple, #7c3aed);">Create an account</a> to track your bookings.
            </p>
        </div>
        {% endif %}

        <!-- Payment Selection -->
        <h3 style="margin-bottom: 20px; color: var(--text-bright, #f5f5f5);">Choose Payment Method</h3>

        <!-- Credit Card -->
        <div class="payment-method-card" onclick="selectPayment('card')" id="method-card">
            <div class="method-header">
                <span class="method-icon">&#128179;</span>
                <div>
                    <div class="method-title">Credit or Debit Card</div>
                    <div class="method-subtitle">Visa, Mastercard, American Express</div>
                </div>
                <div style="margin-left: auto; font-weight: bold; color: var(--accent-purple, #7c3aed);">
                    ${{ "%.2f"|format((deal.price_total_usd or 0) + (deal.platform_fee_usd or 0)) }}
                </div>
            </div>
            <div class="payment-details-panel" id="details-card">
                <p>Secure payment powered by Stripe. You'll be redirected to complete your payment.</p>
                <button class="mystes-btn mystes-btn-primary mystes-btn-full" onclick="payWithCard(event)" style="margin-top: 10px;">
                    Pay ${{ "%.2f"|format((deal.price_total_usd or 0) + (deal.platform_fee_usd or 0)) }} with Card
                </button>
            </div>
        </div>

        <!-- XRP/RLUSD payment options removed (Build #173 — Stripe + MoonPay only) -->

        <p style="text-align: center; color: var(--text-muted, #ccc); margin-top: 20px; font-size: 14px;">
            All payments are secure and encrypted<br>
            <small>By proceeding, you agree to our Terms of Service</small>
        </p>
    {% endif %}
</div>

<!-- Processing Overlay -->
<div class="mystes-modal-overlay" id="processing-overlay">
    <div class="mystes-modal" style="text-align: center; max-width: 400px;">
        <div class="mystes-spinner" style="margin: 0 auto 20px;"></div>
        <h3 id="processing-title" style="color: var(--text-bright, #f5f5f5);">Processing Payment...</h3>
        <p id="processing-message" style="color: var(--text-muted, #ccc);">Please wait while we verify your payment.</p>
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
    overlay.classList.add('open');
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
        else { overlay.classList.remove('open'); alert('Error: ' + (data.error || 'Failed to create payment session')); }
    } catch (err) { overlay.classList.remove('open'); alert('Payment error: ' + err.message); }
}
</script>
"""


def register_hotel_routes(app, csrf, limiter):
    """Register all hotel routes on the Flask app."""
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

    @app.route("/api/hotels/suggest", methods=["POST"])
    @csrf.exempt
    def api_hotel_suggest():
        """Autocomplete hotel destinations via Duffel Stays."""
        data = request.get_json()
        query = (data or {}).get("query", "").strip()
        if len(query) < 3:
            return jsonify({"success": False, "error": "Query must be at least 3 characters"})

        try:
            from picasso_sdk_clients import get_duffel_stays_client
            client = get_duffel_stays_client()
            if not client:
                return jsonify({"success": False, "error": "Hotel suggestions unavailable", "suggestions": []})

            result = client.suggest_accommodation(query)
            if not result.get("success"):
                return jsonify({"success": False, "error": result.get("error", "No suggestions"), "suggestions": []})

            return jsonify({
                "success": True,
                "suggestions": result.get("suggestions", []),
                "count": result.get("count", 0),
            })
        except ImportError:
            # Fallback: try direct import from SDK
            try:
                import sys, os
                sdk_path = os.path.join(os.path.dirname(__file__), "picasso-sdk")
                if sdk_path not in sys.path:
                    sys.path.insert(0, sdk_path)
                from clients.duffel_stays import DuffelStaysClient
                client = DuffelStaysClient()
                if not client.is_configured():
                    return jsonify({"success": False, "error": "Duffel not configured", "suggestions": []})
                result = client.suggest_accommodation(query)
                return jsonify({
                    "success": result.get("success", False),
                    "suggestions": result.get("suggestions", []),
                    "count": result.get("count", 0),
                })
            except Exception as e:
                logger.error("Hotel suggest error: %s", e)
                return jsonify({"success": False, "error": "Suggestions unavailable", "suggestions": []})

    @app.route("/api/hotels/search", methods=["POST"])
    @csrf.exempt
    def api_hotel_search():
        """Search hotels — dual-source: liteAPI + Duffel Stays in parallel."""
        if not is_feature_enabled("vertical_hotels"):
            return jsonify({"success": False, "error": "Hotel search is not available yet"}), 410
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "No data provided"}), 400

        check_in = data.get("check_in")
        check_out = data.get("check_out")
        adults = data.get("adults", 1)
        rooms = data.get("rooms", 1)
        ratings = data.get("ratings")
        latitude = data.get("latitude")
        longitude = data.get("longitude")
        city_code = data.get("city_code", "").upper() if data.get("city_code") else ""
        destination_name = data.get("destination_name", "")

        if not check_in or not check_out:
            return jsonify({"success": False, "error": "Check-in and check-out dates required"}), 400

        try:
            return _execute_hotel_search(
                check_in, check_out, adults, rooms, ratings,
                latitude, longitude, city_code, destination_name,
            )
        except Exception as e:
            logger.error("Hotel search error: %s", e, exc_info=True)
            return jsonify({"success": False, "error": "Hotel search failed. Please try again."}), 500

    def _execute_hotel_search(
        check_in, check_out, adults, rooms, ratings,
        latitude, longitude, city_code, destination_name,
    ):
        """Internal: run dual-source hotel search."""
        try:
            from payments import get_hotel_fee_percent
        except ImportError:
            get_hotel_fee_percent = None

        all_hotels = []
        sources_searched = []

        def _search_liteapi():
            """Search liteAPI (city_code based)."""
            if not city_code or len(city_code) != 3:
                return []
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
                if result.get("success"):
                    hotels = result.get("hotels", [])
                    for h in hotels:
                        h["source"] = "liteapi"
                    return hotels
            except Exception as e:
                logger.warning("liteAPI hotel search failed: %s", e)
            return []

        def _search_duffel_stays():
            """Search Duffel Stays (coordinate based)."""
            if latitude is None or longitude is None:
                return []
            try:
                import sys, os
                sdk_path = os.path.join(os.path.dirname(__file__), "picasso-sdk")
                if sdk_path not in sys.path:
                    sys.path.insert(0, sdk_path)
                from clients.duffel_stays import DuffelStaysClient
                client = DuffelStaysClient()
                if not client.is_configured():
                    return []

                result = client.search_stays(
                    check_in_date=check_in,
                    check_out_date=check_out,
                    adults=adults,
                    rooms=rooms,
                    latitude=float(latitude),
                    longitude=float(longitude),
                )
                if not result.get("success"):
                    return []

                # Calculate nights
                from datetime import datetime as _dt
                ci = _dt.strptime(check_in, "%Y-%m-%d")
                co = _dt.strptime(check_out, "%Y-%m-%d")
                nights = max((co - ci).days, 1)

                # Flat 8% hotel markup — all tiers, not tiered like flights
                fee_pct = 0.08
                if get_hotel_fee_percent:
                    try:
                        fee_pct = get_hotel_fee_percent(current_user)
                    except Exception:
                        pass

                hotels = []
                for r in result.get("results", []):
                    raw_total = float(r.get("cheapest_rate_total", 0))
                    if raw_total <= 0:
                        continue

                    # Apply MYSTES fee: $3 minimum, NO maximum
                    platform_fee = max(3.0, raw_total * fee_pct)
                    price_total = raw_total + platform_fee
                    price_per_night = price_total / nights

                    # Build a unique offer_id for caching
                    rate_id = r.get("cheapest_rate_id", "")
                    offer_key = f"duffel_stays_{r.get('property_id', '')}_{rate_id}"

                    hotels.append({
                        "hotel_id": r.get("property_id", ""),
                        "hotel_name": r.get("property_name", "Unknown Hotel"),
                        "offer_id": offer_key,
                        "city_code": city_code or "",
                        "check_in": check_in,
                        "check_out": check_out,
                        "nights": nights,
                        "price_total": round(price_total, 2),
                        "price_per_night": round(price_per_night, 2),
                        "our_cost": round(raw_total, 2),
                        "price_base": round(raw_total, 2),
                        "platform_fee": round(platform_fee, 2),
                        "currency": r.get("cheapest_rate_currency", "USD"),
                        "room_type": None,
                        "bed_type": None,
                        "room_description": "",
                        "cancellation_deadline": None,
                        "cancellation_description": None,
                        "adults": adults,
                        "rooms": rooms,
                        "google_price": None,
                        "user_savings": 0,
                        "savings_pct": 0,
                        "source": "duffel_stays",
                        "rate_id": rate_id,
                        "accommodation_id": r.get("property_id", ""),
                        "star_rating": r.get("star_rating"),
                        "raw_offer": {
                            "source": "duffel_stays",
                            "rate_id": rate_id,
                            "accommodation_id": r.get("property_id", ""),
                            "search_result_id": result.get("search_result_id", ""),
                        },
                    })
                return hotels
            except Exception as e:
                logger.warning("Duffel Stays hotel search failed: %s", e)
            return []

        # Run both sources in parallel
        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = {
                    executor.submit(_search_liteapi): "liteapi",
                    executor.submit(_search_duffel_stays): "duffel_stays",
                }
                for future in as_completed(futures, timeout=60):
                    source_name = futures[future]
                    try:
                        results = future.result()
                        if results:
                            all_hotels.extend(results)
                            sources_searched.append(source_name)
                    except Exception as e:
                        logger.warning("Hotel source %s failed: %s", source_name, e)
        except Exception as e:
            logger.error("Hotel parallel search error: %s", e, exc_info=True)

        try:
            from monitoring import track_search
            track_search(origin=city_code or "geo", destination=city_code or destination_name, market="hotel")
        except Exception:
            pass

        if not all_hotels:
            return jsonify({"success": False, "error": "No hotels found", "hotels": []})

        # Dedup by property name (case-insensitive, keep cheapest)
        seen = {}
        for h in all_hotels:
            key = (h.get("hotel_name", "")).strip().lower()
            if key not in seen or h.get("price_total", float("inf")) < seen[key].get("price_total", float("inf")):
                seen[key] = h
        deduped = list(seen.values())
        deduped.sort(key=lambda x: x.get("price_per_night", float("inf")))

        # Build frontend-safe list
        hotels_out = []
        for h in deduped:
            hotels_out.append({
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
                "google_price": h.get("google_price"),
                "user_savings": h.get("user_savings", 0),
                "savings_pct": h.get("savings_pct", 0),
                "source": h.get("source", "liteapi"),
            })

        # Cache full results for hotel selection (includes raw_offer, source, rate_id)
        session['hotel_search_results'] = {
            h.get("offer_id"): h for h in deduped if h.get("offer_id")
        }

        return jsonify({
            "success": True,
            "hotels": hotels_out,
            "count": len(hotels_out),
            "sources": sources_searched,
            "check_in": check_in,
            "check_out": check_out,
        })

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

            # Use real pricing from search results
            source = hotel_data.get("source", "liteapi")
            nights = hotel_data.get("nights", 1)
            our_cost = float(hotel_data.get("our_cost", hotel_data.get("price_base", 0)))
            platform_fee = float(hotel_data.get("platform_fee", 0))
            mystes_price = float(hotel_data.get("price_total", 0))
            price_per_night = float(hotel_data.get("price_per_night", 0))
            google_price = float(hotel_data.get("google_price", 0)) if hotel_data.get("google_price") else None
            user_savings = float(hotel_data.get("user_savings", 0))
            savings_pct = float(hotel_data.get("savings_pct", 0))

            if platform_fee <= 0 and our_cost <= 0:
                our_cost = mystes_price
                platform_fee = 3.00

            # Build raw_offer for booking dispatch
            raw_offer = hotel_data.get("raw_offer")
            if not raw_offer:
                raw_offer = {"source": source, "offer_id": offer_id}
            # Ensure source is always set
            if isinstance(raw_offer, dict):
                raw_offer["source"] = source

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
                price_total_usd=our_cost,
                cancellation_policy=hotel_data.get("cancellation_description"),
                home_price_usd=google_price or mystes_price,
                arbitrage_price_usd=our_cost,
                platform_fee_usd=platform_fee,
                user_savings_usd=user_savings,
                gross_savings_usd=round((google_price - our_cost), 2) if google_price else 0,
                savings_percent=savings_pct,
                destination_tag=destination_tag,
                amadeus_offer_data=json.dumps(raw_offer) if raw_offer else None,
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
                "total_price": round(our_cost + platform_fee, 2),
                "redirect_url": f"/save-deal/{deal_id}",
            })

        except Exception as e:
            logger.error("Hotel select error: %s", e, exc_info=True)
            return jsonify({"success": False, "error": "Hotel selection failed. Please try again."}), 500
