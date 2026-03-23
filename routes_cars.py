"""
Phase 2 — Car Rental Routes
Car rentals vertical for MYSTES consumer OTA via Discover Cars API.

Register in server.py:
    from routes_cars import register_car_routes
    register_car_routes(app, csrf, limiter)
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
# CAR RENTALS SEARCH FRONTEND — Premium MYSTES Design
# ============================================================

CARS_SEARCH_CONTENT = """
<style>
/* ============================================
   CARS PAGE — Matches flights/hotels aesthetic
   ============================================ */

.cars-page { max-width: 960px; margin: 0 auto; padding: 0 16px; }

.cars-page-header {
    text-align: center;
    padding: 40px 0 10px;
}
.cars-page-header .brand-label {
    font-family: var(--font-brand, 'Cinzel', serif);
    font-size: 14px;
    font-weight: 600;
    letter-spacing: 6px;
    color: #c9a44a;
    display: block;
    margin-bottom: 8px;
}
.cars-page-header h1 {
    font-family: var(--font-brand, 'Cinzel', serif);
    font-size: 32px;
    font-weight: 700;
    letter-spacing: 4px;
    color: var(--text-bright, #f5f5f5);
    margin: 0 0 8px;
}
.cars-page-header p {
    color: var(--text-secondary, #aaa);
    font-size: 15px;
    margin: 0;
}

/* Search form card */
.car-search-card {
    background: rgba(10, 6, 18, 0.85);
    backdrop-filter: blur(16px);
    -webkit-backdrop-filter: blur(16px);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 16px;
    padding: 28px;
    margin-bottom: 24px;
}
.car-search-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 16px;
}
.car-search-grid .full-width { grid-column: 1 / -1; }

.car-search-card label {
    display: block;
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 0.5px;
    text-transform: uppercase;
    color: var(--text-secondary, #aaa);
    margin-bottom: 6px;
}
.car-search-card input,
.car-search-card select {
    width: 100%;
    padding: 12px 14px;
    background: rgba(255, 255, 255, 0.06);
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 10px;
    color: var(--text-bright, #f5f5f5);
    font-family: var(--font-body, 'Outfit', sans-serif);
    font-size: 15px;
    transition: all 0.3s ease;
    box-sizing: border-box;
}
.car-search-card input:focus,
.car-search-card select:focus {
    outline: none;
    background: rgba(255, 255, 255, 0.10);
    border-color: #c9a44a;
    box-shadow: 0 0 0 3px rgba(201, 164, 74, 0.15);
}
.car-search-card input::placeholder { color: rgba(255,255,255,0.3); }
.car-search-card select option { background: #1a1a2e; color: #f5f5f5; }

/* Location autocomplete */
.loc-autocomplete-wrapper {
    position: relative;
}
.loc-autocomplete-dropdown {
    display: none;
    position: absolute;
    top: 100%;
    left: 0;
    right: 0;
    z-index: 100;
    background: rgba(20, 14, 35, 0.98);
    backdrop-filter: blur(16px);
    border: 1px solid rgba(255,255,255,0.12);
    border-radius: 10px;
    margin-top: 4px;
    max-height: 260px;
    overflow-y: auto;
    box-shadow: 0 12px 40px rgba(0,0,0,0.5);
}
.loc-autocomplete-dropdown.visible { display: block; }
.loc-autocomplete-item {
    padding: 12px 14px;
    cursor: pointer;
    transition: background 0.15s;
    border-bottom: 1px solid rgba(255,255,255,0.05);
    font-family: var(--font-body, 'Outfit', sans-serif);
}
.loc-autocomplete-item:last-child { border-bottom: none; }
.loc-autocomplete-item:hover { background: rgba(201, 164, 74, 0.12); }
.loc-autocomplete-item .loc-name { color: #f5f5f5; font-size: 14px; font-weight: 500; }
.loc-autocomplete-item .loc-detail { color: rgba(255,255,255,0.5); font-size: 12px; margin-top: 2px; }

/* Different return location toggle */
.return-toggle {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-top: 4px;
    cursor: pointer;
    font-size: 13px;
    color: #c9a44a;
    user-select: none;
}
.return-toggle input { display: none; }
.return-toggle .toggle-box {
    width: 16px;
    height: 16px;
    border: 1px solid rgba(255,255,255,0.2);
    border-radius: 4px;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: all 0.2s;
    font-size: 11px;
    color: transparent;
}
.return-toggle input:checked + .toggle-box {
    background: rgba(201, 164, 74, 0.2);
    border-color: #c9a44a;
    color: #c9a44a;
}

/* Search button */
.car-search-btn {
    width: 100%;
    margin-top: 18px;
    padding: 14px;
    background: #c9a44a;
    color: #000;
    border: none;
    border-radius: 10px;
    font-size: 15px;
    font-weight: 600;
    font-family: var(--font-body, 'Outfit', sans-serif);
    cursor: pointer;
    transition: all 0.3s;
    letter-spacing: 0.5px;
}
.car-search-btn:hover {
    background: #d4b05c;
    box-shadow: 0 8px 30px rgba(201, 164, 74, 0.35);
    transform: translateY(-1px);
}
.car-search-btn:disabled { opacity: 0.6; cursor: not-allowed; transform: none; }
.car-search-spinner {
    display: inline-block; width: 16px; height: 16px;
    border: 2px solid rgba(0,0,0,0.2);
    border-top-color: #000; border-radius: 50%;
    animation: cspin 0.6s linear infinite;
    vertical-align: middle; margin-right: 8px;
}
@keyframes cspin { to { transform: rotate(360deg); } }

/* Loading skeleton */
.car-loading-state {
    margin-top: 20px; padding: 30px;
    background: rgba(15, 10, 25, 0.6);
    border-radius: 16px;
    border: 1px solid rgba(201, 164, 74, 0.15);
}
.car-loading-header {
    display: flex; align-items: center; gap: 16px; margin-bottom: 24px;
}
.car-loading-spinner {
    width: 40px; height: 40px;
    border: 3px solid rgba(201, 164, 74, 0.2);
    border-top-color: #c9a44a; border-radius: 50%;
    animation: cspin 0.8s linear infinite; flex-shrink: 0;
}
.car-skeleton-cards { display: flex; flex-direction: column; gap: 12px; }
.car-skeleton-card {
    background: rgba(255,255,255,0.05); border-radius: 12px;
    padding: 20px; display: flex; gap: 16px;
}
.car-skeleton-img {
    width: 140px; height: 90px; border-radius: 8px;
    background: linear-gradient(90deg, rgba(255,255,255,0.06) 25%, rgba(255,255,255,0.12) 50%, rgba(255,255,255,0.06) 75%);
    background-size: 200% 100%; animation: cshimmer 1.5s infinite; flex-shrink: 0;
}
.car-skeleton-line {
    height: 14px;
    background: linear-gradient(90deg, rgba(255,255,255,0.06) 25%, rgba(255,255,255,0.12) 50%, rgba(255,255,255,0.06) 75%);
    background-size: 200% 100%; animation: cshimmer 1.5s infinite; border-radius: 6px;
}
.car-skeleton-line.w40 { width: 40%; }
.car-skeleton-line.w60 { width: 60%; }
.car-skeleton-line.w30 { width: 30%; }
@keyframes cshimmer { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } }

/* Results header + controls */
.car-results-bar {
    display: flex; justify-content: space-between; align-items: center;
    flex-wrap: wrap; gap: 12px; margin-bottom: 16px;
}
.car-results-count {
    color: #f5f5f5; font-size: 18px; font-weight: 600; margin: 0;
}
.car-results-dates { color: rgba(255,255,255,0.5); font-size: 13px; }
.car-controls {
    display: flex; gap: 8px; align-items: center; flex-wrap: wrap;
}
.car-sort-select,
.car-filter-select {
    padding: 8px 12px; background: rgba(255,255,255,0.06);
    border: 1px solid rgba(255,255,255,0.12); border-radius: 10px;
    color: #f5f5f5; font-size: 13px;
    font-family: var(--font-body, 'Outfit', sans-serif); cursor: pointer;
}
.car-sort-select option,
.car-filter-select option { background: #1a1a2e; }

/* ============================================
   CAR RESULT CARDS
   ============================================ */

.car-cards-grid { display: flex; flex-direction: column; gap: 14px; }

.car-card {
    background: rgba(10, 6, 18, 0.85);
    backdrop-filter: blur(16px);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 16px;
    position: relative;
    transition: all 0.2s ease;
    overflow: hidden;
}
.car-card:hover {
    background: rgba(15, 10, 25, 0.95);
    border-color: rgba(201, 164, 74, 0.3);
    transform: translateY(-2px);
    box-shadow: 0 8px 30px rgba(0,0,0,0.3);
}

.car-card-inner { display: flex; }

.car-card-image {
    width: 200px; min-height: 160px; flex-shrink: 0;
    background: linear-gradient(135deg, rgba(201,164,74,0.08), rgba(201,164,74,0.03));
    display: flex; align-items: center; justify-content: center;
    position: relative; overflow: hidden;
}
.car-card-image img {
    width: 100%; height: 100%; object-fit: cover;
    position: absolute; top: 0; left: 0;
}
.car-card-image-placeholder {
    opacity: 0.25; width: 80px; height: 80px;
}

.car-card-details {
    flex: 1; padding: 18px 20px; display: flex;
    flex-direction: column; justify-content: space-between; min-width: 0;
}
.car-card-name {
    font-size: 17px; font-weight: 600; color: #fff;
    margin: 0 0 2px; line-height: 1.3;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.car-card-type {
    font-size: 13px; color: rgba(255,255,255,0.6); margin-bottom: 4px;
}
.car-card-supplier {
    font-size: 12px; color: #c9a44a; margin-bottom: 8px; font-weight: 500;
}

.car-card-features {
    display: flex; flex-wrap: wrap; gap: 10px; margin: 6px 0;
}
.car-feature {
    display: flex; align-items: center; gap: 5px;
    font-size: 12px; color: #aaa;
}
.car-feature svg { width: 16px; height: 16px; fill: rgba(255,255,255,0.4); flex-shrink: 0; }

.car-card-bottom {
    display: flex; justify-content: space-between;
    align-items: flex-end; gap: 12px;
    padding-top: 12px; border-top: 1px solid rgba(255,255,255,0.06);
}
.car-card-pricing { display: flex; flex-direction: column; }
.car-card-price-label {
    font-size: 11px; color: rgba(255,255,255,0.5); text-transform: uppercase; letter-spacing: 0.5px;
}
.car-card-price-value { font-size: 24px; font-weight: 700; color: #c9a44a; }
.car-card-price-unit { font-size: 13px; font-weight: 400; color: rgba(255,255,255,0.5); }
.car-card-price-total { font-size: 12px; color: rgba(255,255,255,0.4); margin-top: 2px; }

.car-card-cta {
    padding: 10px 24px;
    background: #c9a44a;
    color: #000;
    border: none;
    border-radius: 10px;
    font-size: 14px;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.2s;
    font-family: var(--font-body, 'Outfit', sans-serif);
    white-space: nowrap;
    flex-shrink: 0;
}
.car-card-cta:hover {
    background: #d4b05c;
    box-shadow: 0 4px 15px rgba(201, 164, 74, 0.3);
}
.car-card-cta:disabled { opacity: 0.6; cursor: not-allowed; }

/* No results */
.car-no-results {
    text-align: center; padding: 60px 20px;
}
.car-no-results-icon { font-size: 48px; margin-bottom: 16px; opacity: 0.3; }

/* Responsive */
@media (max-width: 700px) {
    .car-card-inner { flex-direction: column; }
    .car-card-image { width: 100%; min-height: 140px; max-height: 180px; }
    .car-search-grid { grid-template-columns: 1fr; }
    .car-search-grid .full-width { grid-column: 1; }
    .car-results-bar { flex-direction: column; align-items: flex-start; }
    .car-card-name { white-space: normal; }
    .car-card-bottom { flex-direction: column; align-items: flex-start; gap: 10px; }
    .car-controls { width: 100%; }
}
</style>

<div class="cars-page">
    <div class="cars-page-header">
        <span class="brand-label">MYSTES</span>
        <h1>CAR RENTALS</h1>
        <p>500+ suppliers. Best rates. Powered by MYSTES.</p>
    </div>

    <!-- Search Form -->
    <div class="car-search-card">
        <div class="car-search-grid">
            <div class="form-group full-width">
                <label>Pickup Location</label>
                <div class="loc-autocomplete-wrapper" id="pickup-wrapper">
                    <input type="text" id="car-pickup-location" placeholder="Airport, city, or address..." autocomplete="off" oninput="debouncedLocationSearch(this, 'pickup')">
                    <input type="hidden" id="car-pickup-location-id">
                    <div class="loc-autocomplete-dropdown" id="pickup-dropdown"></div>
                </div>
            </div>
            <div class="form-group full-width">
                <label class="return-toggle" onclick="toggleReturnLocation()">
                    <input type="checkbox" id="different-return-check">
                    <span class="toggle-box">&#10003;</span>
                    Different return location
                </label>
            </div>
            <div class="form-group full-width" id="dropoff-location-group" style="display: none;">
                <label>Dropoff Location</label>
                <div class="loc-autocomplete-wrapper" id="dropoff-wrapper">
                    <input type="text" id="car-dropoff-location" placeholder="Return to a different location..." autocomplete="off" oninput="debouncedLocationSearch(this, 'dropoff')">
                    <input type="hidden" id="car-dropoff-location-id">
                    <div class="loc-autocomplete-dropdown" id="dropoff-dropdown"></div>
                </div>
            </div>
            <div class="form-group">
                <label>Pickup Date</label>
                <input type="date" id="car-pickup-date">
            </div>
            <div class="form-group">
                <label>Dropoff Date</label>
                <input type="date" id="car-dropoff-date">
            </div>
            <div class="form-group">
                <label>Pickup Time</label>
                <input type="time" id="car-pickup-time" value="10:00">
            </div>
            <div class="form-group">
                <label>Dropoff Time</label>
                <input type="time" id="car-dropoff-time" value="10:00">
            </div>
            <div class="form-group">
                <label>Driver Age</label>
                <input type="number" id="car-driver-age" value="30" min="18" max="99">
            </div>
        </div>
        <button class="car-search-btn" id="car-search-btn" onclick="searchCars()">
            Search Car Rentals
        </button>
    </div>

    <!-- Loading State -->
    <div id="car-loading" style="display: none;">
        <div class="car-loading-state">
            <div class="car-loading-header">
                <div class="car-loading-spinner"></div>
                <div>
                    <div style="color: #f5f5f5; font-size: 16px; font-weight: 600;">Searching rental cars...</div>
                    <div style="color: rgba(255,255,255,0.5); font-size: 13px; margin-top: 4px;">Comparing 500+ suppliers worldwide</div>
                </div>
            </div>
            <div class="car-skeleton-cards">
                <div class="car-skeleton-card">
                    <div class="car-skeleton-img"></div>
                    <div style="flex:1; display:flex; flex-direction:column; gap:10px;">
                        <div class="car-skeleton-line w60"></div>
                        <div class="car-skeleton-line w40"></div>
                        <div class="car-skeleton-line w30"></div>
                    </div>
                </div>
                <div class="car-skeleton-card">
                    <div class="car-skeleton-img"></div>
                    <div style="flex:1; display:flex; flex-direction:column; gap:10px;">
                        <div class="car-skeleton-line w60"></div>
                        <div class="car-skeleton-line w40"></div>
                        <div class="car-skeleton-line w30"></div>
                    </div>
                </div>
                <div class="car-skeleton-card">
                    <div class="car-skeleton-img"></div>
                    <div style="flex:1; display:flex; flex-direction:column; gap:10px;">
                        <div class="car-skeleton-line w60"></div>
                        <div class="car-skeleton-line w40"></div>
                        <div class="car-skeleton-line w30"></div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <!-- Results -->
    <div id="car-results" style="display: none;">
        <div id="car-results-header"></div>
        <div id="car-results-list" class="car-cards-grid"></div>
    </div>
</div>

<script>
let allCars = [];
let locationTimers = {};

/* ---- Date defaults ---- */
(function() {
    const tomorrow = new Date(); tomorrow.setDate(tomorrow.getDate() + 1);
    const weekLater = new Date(); weekLater.setDate(weekLater.getDate() + 8);
    document.getElementById('car-pickup-date').value = tomorrow.toISOString().split('T')[0];
    document.getElementById('car-dropoff-date').value = weekLater.toISOString().split('T')[0];
    document.getElementById('car-pickup-date').min = tomorrow.toISOString().split('T')[0];
    document.getElementById('car-pickup-date').addEventListener('change', function() {
        const next = new Date(this.value);
        next.setDate(next.getDate() + 1);
        document.getElementById('car-dropoff-date').min = next.toISOString().split('T')[0];
        if (document.getElementById('car-dropoff-date').value <= this.value) {
            document.getElementById('car-dropoff-date').value = next.toISOString().split('T')[0];
        }
    });
})();

/* ---- Toggle different return location ---- */
function toggleReturnLocation() {
    const cb = document.getElementById('different-return-check');
    cb.checked = !cb.checked;
    document.getElementById('dropoff-location-group').style.display = cb.checked ? 'block' : 'none';
    if (!cb.checked) {
        document.getElementById('car-dropoff-location').value = '';
        document.getElementById('car-dropoff-location-id').value = '';
    }
}

/* ---- Location autocomplete ---- */
function debouncedLocationSearch(input, type) {
    if (locationTimers[type]) clearTimeout(locationTimers[type]);
    locationTimers[type] = setTimeout(function() { fetchLocations(input, type); }, 300);
}

async function fetchLocations(input, type) {
    const query = input.value.trim();
    const dropdown = document.getElementById(type + '-dropdown');

    if (query.length < 2) {
        dropdown.classList.remove('visible');
        return;
    }

    try {
        const resp = await fetch('/api/cars/locations?q=' + encodeURIComponent(query));
        const data = await resp.json();

        if (!data.success || !data.locations || data.locations.length === 0) {
            dropdown.classList.remove('visible');
            return;
        }

        dropdown.innerHTML = data.locations.map(function(loc) {
            var detail = [loc.city, loc.country].filter(Boolean).join(', ');
            if (loc.iata_code) detail = loc.iata_code + (detail ? ' - ' + detail : '');
            return '<div class="loc-autocomplete-item" onclick="selectLocation(\'' + type + '\', \'' +
                loc.location_id.toString().replace(/'/g, "\\\\'") + '\', \'' +
                loc.name.replace(/'/g, "\\\\'") + '\')">' +
                '<div class="loc-name">' + loc.name + '</div>' +
                (detail ? '<div class="loc-detail">' + detail + '</div>' : '') +
                '</div>';
        }).join('');
        dropdown.classList.add('visible');
    } catch (err) {
        dropdown.classList.remove('visible');
    }
}

function selectLocation(type, locationId, name) {
    document.getElementById('car-' + type + '-location').value = name;
    document.getElementById('car-' + type + '-location-id').value = locationId;
    document.getElementById(type + '-dropdown').classList.remove('visible');
}

/* Close dropdowns on outside click */
document.addEventListener('click', function(e) {
    if (!e.target.closest('#pickup-wrapper')) {
        document.getElementById('pickup-dropdown').classList.remove('visible');
    }
    if (!e.target.closest('#dropoff-wrapper')) {
        document.getElementById('dropoff-dropdown').classList.remove('visible');
    }
});

/* ---- Search ---- */
async function searchCars() {
    var pickupLocationId = document.getElementById('car-pickup-location-id').value;
    var pickupLocationName = document.getElementById('car-pickup-location').value.trim();
    if (!pickupLocationId && !pickupLocationName) {
        alert('Please select a pickup location');
        return;
    }
    var pickupDate = document.getElementById('car-pickup-date').value;
    var dropoffDate = document.getElementById('car-dropoff-date').value;
    if (!pickupDate || !dropoffDate) { alert('Please select pickup and dropoff dates'); return; }
    if (pickupDate >= dropoffDate) { alert('Dropoff date must be after pickup date'); return; }

    var pickupTime = document.getElementById('car-pickup-time').value || '10:00';
    var dropoffTime = document.getElementById('car-dropoff-time').value || '10:00';
    var driverAge = parseInt(document.getElementById('car-driver-age').value) || 30;

    var dropoffLocationId = null;
    if (document.getElementById('different-return-check').checked) {
        dropoffLocationId = document.getElementById('car-dropoff-location-id').value || null;
    }

    var btn = document.getElementById('car-search-btn');
    btn.disabled = true;
    btn.innerHTML = '<span class="car-search-spinner"></span>Searching...';
    document.getElementById('car-loading').style.display = 'block';
    document.getElementById('car-results').style.display = 'none';

    try {
        var csrfToken = (document.querySelector('meta[name="csrf-token"]') || {}).content || '';
        var body = {
            pickup_location_id: pickupLocationId,
            pickup_location_name: pickupLocationName,
            pickup_date: pickupDate,
            dropoff_date: dropoffDate,
            pickup_time: pickupTime,
            dropoff_time: dropoffTime,
            driver_age: driverAge
        };
        if (dropoffLocationId) body.dropoff_location_id = dropoffLocationId;

        var resp = await fetch('/api/cars/search', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
            body: JSON.stringify(body)
        });
        var data = await resp.json();
        allCars = data.cars || [];
        renderCarResults(data, pickupLocationName, pickupDate, dropoffDate);
    } catch (err) {
        document.getElementById('car-loading').style.display = 'none';
        alert('Search failed: ' + err.message);
    } finally {
        btn.disabled = false;
        btn.innerHTML = 'Search Car Rentals';
    }
}

/* ---- Render results ---- */
function renderCarResults(data, location, pickupDate, dropoffDate) {
    document.getElementById('car-loading').style.display = 'none';
    document.getElementById('car-results').style.display = 'block';
    var header = document.getElementById('car-results-header');
    var list = document.getElementById('car-results-list');

    if (!data.success || !allCars.length) {
        header.innerHTML = '';
        list.innerHTML = '<div class="car-no-results">' +
            '<div class="car-no-results-icon">&#128663;</div>' +
            '<h3 style="color:#f5f5f5; margin:0 0 8px;">No cars found</h3>' +
            '<p style="color:rgba(255,255,255,0.5);">' + (data.error || 'Try different dates or location') + '</p></div>';
        return;
    }

    header.innerHTML =
        '<div class="car-results-bar">' +
            '<div>' +
                '<h2 class="car-results-count">' + allCars.length + ' Cars Available</h2>' +
                '<div class="car-results-dates">' + location + ' &middot; ' + pickupDate + ' to ' + dropoffDate + '</div>' +
            '</div>' +
            '<div class="car-controls">' +
                '<select class="car-sort-select" id="car-sort" onchange="sortAndFilterCars()">' +
                    '<option value="price-asc">Price: Low to High</option>' +
                    '<option value="price-desc">Price: High to Low</option>' +
                '</select>' +
                '<select class="car-filter-select" id="car-filter-type" onchange="sortAndFilterCars()">' +
                    '<option value="">Any Type</option>' +
                    '<option value="economy">Economy</option>' +
                    '<option value="compact">Compact</option>' +
                    '<option value="intermediate">Intermediate</option>' +
                    '<option value="full-size">Full-size</option>' +
                    '<option value="suv">SUV</option>' +
                    '<option value="van">Van</option>' +
                '</select>' +
                '<select class="car-filter-select" id="car-filter-transmission" onchange="sortAndFilterCars()">' +
                    '<option value="">Any Transmission</option>' +
                    '<option value="automatic">Automatic</option>' +
                    '<option value="manual">Manual</option>' +
                '</select>' +
            '</div>' +
        '</div>';
    renderCarCards(allCars);
}

function sortAndFilterCars() {
    var filtered = allCars.slice();
    var typeFilter = (document.getElementById('car-filter-type') || {}).value || '';
    var transFilter = (document.getElementById('car-filter-transmission') || {}).value || '';

    if (typeFilter) {
        filtered = filtered.filter(function(c) {
            var ct = (c.vehicle_type || c.vehicle_class || '').toLowerCase();
            return ct.indexOf(typeFilter) !== -1;
        });
    }
    if (transFilter) {
        filtered = filtered.filter(function(c) {
            return (c.transmission || '').toLowerCase().indexOf(transFilter) !== -1;
        });
    }

    var sort = (document.getElementById('car-sort') || {}).value || 'price-asc';
    if (sort === 'price-asc') filtered.sort(function(a, b) { return a.price_total - b.price_total; });
    else if (sort === 'price-desc') filtered.sort(function(a, b) { return b.price_total - a.price_total; });

    renderCarCards(filtered);
}

function renderCarCards(cars) {
    var list = document.getElementById('car-results-list');
    if (!cars.length) {
        list.innerHTML = '<div style="text-align:center; padding:40px; color:rgba(255,255,255,0.5);">No cars match your filters</div>';
        return;
    }

    list.innerHTML = cars.map(function(c) {
        var imageHtml = c.image_url
            ? '<img src="' + c.image_url + '" alt="" onerror="this.style.display=\'none\';this.nextElementSibling.style.display=\'block\'">' +
              '<svg class="car-card-image-placeholder" style="display:none" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M19 17H22V15H19V17Z" fill="currentColor" opacity="0.3"/><path d="M17.71 7.04C17.37 6.73 16.94 6.5 16.47 6.38L15 2H9L7.53 6.38C7.06 6.5 6.63 6.73 6.29 7.04L2 8V15H4.18C4.59 16.72 6.14 18 8 18C9.86 18 11.41 16.72 11.82 15H12.18C12.59 16.72 14.14 18 16 18C17.86 18 19.41 16.72 19.82 15H22V12L17.71 7.04ZM8 16C6.9 16 6 15.1 6 14C6 12.9 6.9 12 8 12C9.1 12 10 12.9 10 14C10 15.1 9.1 16 8 16ZM16 16C14.9 16 14 15.1 14 14C14 12.9 14.9 12 16 12C17.1 12 18 12.9 18 14C18 15.1 17.1 16 16 16Z" fill="currentColor"/></svg>'
            : '<svg class="car-card-image-placeholder" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M19 17H22V15H19V17Z" fill="currentColor" opacity="0.3"/><path d="M17.71 7.04C17.37 6.73 16.94 6.5 16.47 6.38L15 2H9L7.53 6.38C7.06 6.5 6.63 6.73 6.29 7.04L2 8V15H4.18C4.59 16.72 6.14 18 8 18C9.86 18 11.41 16.72 11.82 15H12.18C12.59 16.72 14.14 18 16 18C17.86 18 19.41 16.72 19.82 15H22V12L17.71 7.04ZM8 16C6.9 16 6 15.1 6 14C6 12.9 6.9 12 8 12C9.1 12 10 12.9 10 14C10 15.1 9.1 16 8 16ZM16 16C14.9 16 14 15.1 14 14C14 12.9 14.9 12 16 12C17.1 12 18 12.9 18 14C18 15.1 17.1 16 16 16Z" fill="currentColor"/></svg>';

        var typeLabel = c.vehicle_type || c.vehicle_class || '';
        var transmissionIcon = '<svg viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 17.93c-3.95-.49-7-3.85-7-7.93 0-.62.08-1.21.21-1.79L9 15v1c0 1.1.9 2 2 2v1.93zm6.9-2.54c-.26-.81-1-1.39-1.9-1.39h-1v-3c0-.55-.45-1-1-1H8v-2h2c.55 0 1-.45 1-1V7h2c1.1 0 2-.9 2-2v-.41c2.93 1.19 5 4.06 5 7.41 0 2.08-.8 3.97-2.1 5.39z" fill="currentColor"/></svg>';
        var acIcon = '<svg viewBox="0 0 24 24"><path d="M22 11h-4.17l3.24-3.24-1.41-1.42L15 11h-2V9l4.66-4.66-1.42-1.41L13 6.17V2h-2v4.17L7.76 2.93 6.34 4.34 11 9v2H9L4.34 6.34 2.93 7.76 6.17 11H2v2h4.17l-3.24 3.24 1.41 1.42L9 13h2v2l-4.66 4.66 1.42 1.41L11 17.83V22h2v-4.17l3.24 3.24 1.42-1.41L13 15v-2h2l4.66 4.66 1.41-1.42L17.83 13H22v-2z" fill="currentColor"/></svg>';

        var features = '';
        if (c.transmission) features += '<span class="car-feature">' + transmissionIcon + ' ' + c.transmission + '</span>';
        if (c.air_conditioning) features += '<span class="car-feature">' + acIcon + ' A/C</span>';
        if (c.seats) features += '<span class="car-feature"><svg viewBox="0 0 24 24"><path d="M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z" fill="currentColor"/></svg> ' + c.seats + ' seats</span>';
        var totalBags = (c.bags_large || 0) + (c.bags_small || 0);
        if (totalBags > 0) features += '<span class="car-feature"><svg viewBox="0 0 24 24"><path d="M17 6h-2V3c0-.55-.45-1-1-1h-4c-.55 0-1 .45-1 1v3H7c-1.1 0-2 .9-2 2v11c0 1.1.9 2 2 2 0 .55.45 1 1 1s1-.45 1-1h6c0 .55.45 1 1 1s1-.45 1-1c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2zM10 3h4v3h-4V3z" fill="currentColor"/></svg> ' + totalBags + ' bag' + (totalBags > 1 ? 's' : '') + '</span>';

        var perDay = c.price_per_day > 0 ? c.price_per_day.toFixed(0) : '--';
        var safeJson = JSON.stringify(c).replace(/'/g, '&#39;').replace(/"/g, '&quot;');

        return '<div class="car-card">' +
            '<div class="car-card-inner">' +
                '<div class="car-card-image">' + imageHtml + '</div>' +
                '<div class="car-card-details">' +
                    '<div>' +
                        '<h3 class="car-card-name">' + c.vehicle_name + '</h3>' +
                        (typeLabel ? '<div class="car-card-type">' + typeLabel + '</div>' : '') +
                        (c.supplier ? '<div class="car-card-supplier">' + c.supplier + '</div>' : '') +
                        '<div class="car-card-features">' + features + '</div>' +
                    '</div>' +
                    '<div class="car-card-bottom">' +
                        '<div class="car-card-pricing">' +
                            '<span class="car-card-price-label">MYSTES Price</span>' +
                            '<div><span class="car-card-price-value">$' + c.price_total.toFixed(0) + '</span><span class="car-card-price-unit"> total</span></div>' +
                            '<span class="car-card-price-total">$' + perDay + '/day</span>' +
                        '</div>' +
                        '<button class="car-card-cta" data-car="' + safeJson + '" onclick="selectCar(this)">Select</button>' +
                    '</div>' +
                '</div>' +
            '</div>' +
        '</div>';
    }).join('');
}

/* ---- Select car ---- */
async function selectCar(btn) {
    var carData;
    try {
        var raw = btn.getAttribute('data-car').replace(/&quot;/g, '"').replace(/&#39;/g, "'");
        carData = JSON.parse(raw);
    } catch (e) {
        alert('Error reading car data'); return;
    }

    btn.disabled = true;
    var orig = btn.innerHTML;
    btn.innerHTML = '<span class="car-search-spinner"></span>';

    try {
        var csrfToken = (document.querySelector('meta[name="csrf-token"]') || {}).content || '';
        var resp = await fetch('/api/cars/select', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
            body: JSON.stringify({ offer_id: carData.offer_id })
        });
        var data = await resp.json();
        if (data.success && data.deal_id) {
            window.location.href = data.redirect_url || ('/save-deal/' + data.deal_id);
        } else {
            alert('Error: ' + (data.error || 'Failed to create car rental deal'));
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


CAR_BOOK_CONTENT = """
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
    <h2 style="text-align: center; margin-bottom: 25px; color: #1a1a2e;">Complete Your Car Rental</h2>

    <!-- Order Summary -->
    <div class="order-summary">
        <h3>Car Rental Reservation</h3>
        <div class="flight-leg-item">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <div>
                    <strong>{{ deal.hotel_name }}</strong><br>
                    <span style="color: #14b8a6;">{{ deal.city_code }}</span><br>
                    <small>{{ deal.check_in_date }} to {{ deal.check_out_date }} ({{ deal.nights }} day{{ 's' if deal.nights != 1 else '' }})</small>
                </div>
                <div style="text-align: right;">
                    <span style="font-size: 18px; font-weight: bold;">${{ "%.0f"|format(deal.price_total_usd or 0) }}</span>
                    <br><small style="color: #14b8a6;">${{ "%.0f"|format(deal.price_per_night_usd or 0) }}/day</small>
                </div>
            </div>
        </div>

        <div class="order-row">
            <span>Rental ({{ deal.nights }} day{{ 's' if deal.nights != 1 else '' }})</span>
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
    </div>

    {% if payment_verified %}
        <!-- Payment Complete - Collect Driver Details -->
        <div class="alert alert-success" style="text-align: center; padding: 25px;">
            <span style="font-size: 48px;">&#9989;</span>
            <h3 style="margin: 15px 0;">Payment Verified!</h3>
            <p>Your payment has been confirmed. Please provide driver details to complete your booking.</p>
        </div>

        <form id="guest-form" action="/complete-booking/{{ deal.deal_id }}" method="POST" style="margin-top: 20px;">
            <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
            <div style="background: #f8f9fa; border-radius: 12px; padding: 25px;">
                <h4 style="margin: 0 0 20px 0; color: #1a1a2e;">Driver Information</h4>
                <p style="color: #666; margin-bottom: 20px;">Enter details for the primary driver (must match driver's license).</p>

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
                    <div class="form-group">
                        <label style="font-weight: bold; color: #16213e; display: block; margin-bottom: 5px;">Country *</label>
                        <select name="nationality" required style="width: 100%; padding: 12px; border: 1px solid #ddd; border-radius: 8px; font-size: 16px; color: #1a1a2e;">
                            <option value="US">United States</option>
                            <option value="GB">United Kingdom</option>
                            <option value="CA">Canada</option>
                            <option value="AU">Australia</option>
                            <option value="DE">Germany</option>
                            <option value="FR">France</option>
                            <option value="ES">Spain</option>
                            <option value="IT">Italy</option>
                            <option value="JP">Japan</option>
                            <option value="BR">Brazil</option>
                            <option value="MX">Mexico</option>
                            <option value="IN">India</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label style="font-weight: bold; color: #16213e; display: block; margin-bottom: 5px;">Driver Age *</label>
                        <input type="number" name="driver_age" required min="18" max="99" value="30" style="width: 100%; padding: 12px; border: 1px solid #ddd; border-radius: 8px; font-size: 16px; color: #1a1a2e;">
                    </div>
                    <div class="form-group" style="grid-column: 1 / -1;">
                        <label style="font-weight: bold; color: #16213e; display: block; margin-bottom: 5px;">Flight Number (optional, for airport pickup)</label>
                        <input type="text" name="flight_number" placeholder="AA 1234" style="width: 100%; padding: 12px; border: 1px solid #ddd; border-radius: 8px; font-size: 16px; color: #1a1a2e;">
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
                    Complete Car Rental Booking
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


def register_car_routes(app, csrf, limiter):
    """Register all car rental routes on the Flask app."""
    from server import BASE_TEMPLATE, is_feature_enabled

    @app.route("/cars")
    def cars():
        """Car rental search page."""
        if not is_feature_enabled("vertical_rentals"):
            return redirect(url_for("home"))
        return render_template_string(
            BASE_TEMPLATE,
            title="Car Rentals",
            content=render_template_string(CARS_SEARCH_CONTENT, current_user=current_user),
            current_user=current_user
        )

    @app.route("/api/cars/locations", methods=["GET"])
    @csrf.exempt
    def api_car_locations():
        """Location autocomplete for car rental search."""
        q = request.args.get("q", "").strip()
        if not q or len(q) < 2:
            return jsonify({"success": False, "error": "Query too short", "locations": []})

        try:
            from discover_cars_client import DiscoverCarsClient
            client = DiscoverCarsClient()
            if not client.is_configured():
                return jsonify({"success": False, "error": "Car rental API not configured", "locations": []})

            result = client.search_locations(q)
            if not result.get("success"):
                return jsonify({"success": False, "error": result.get("error", "Location search failed"), "locations": []})

            return jsonify({
                "success": True,
                "locations": result.get("locations", []),
            })

        except Exception as e:
            logger.error("Car location search error: %s", e, exc_info=True)
            return jsonify({"success": False, "error": "Location search failed. Please try again.", "locations": []})

    @app.route("/api/cars/search", methods=["POST"])
    @csrf.exempt
    def api_car_search():
        """Search rental cars via Discover Cars API."""
        if not is_feature_enabled("vertical_rentals"):
            return jsonify({"success": False, "error": "Car rental search is not available yet"}), 410
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "No data provided"}), 400

        pickup_location_id = data.get("pickup_location_id", "").strip()
        pickup_location_name = data.get("pickup_location_name", "").strip()
        pickup_date = data.get("pickup_date")
        dropoff_date = data.get("dropoff_date")
        pickup_time = data.get("pickup_time", "10:00")
        dropoff_time = data.get("dropoff_time", "10:00")
        dropoff_location_id = data.get("dropoff_location_id")
        driver_age = data.get("driver_age", 30)

        if not pickup_date or not dropoff_date:
            return jsonify({"success": False, "error": "Pickup and dropoff dates required"}), 400

        try:
            from discover_cars_client import DiscoverCarsClient
            client = DiscoverCarsClient()
            if not client.is_configured():
                return jsonify({"success": False, "error": "Car rental API not configured", "cars": []})

            # Resolve location ID if not provided (user typed but did not select from dropdown)
            if not pickup_location_id and pickup_location_name:
                loc_result = client.search_locations(pickup_location_name)
                if loc_result.get("success") and loc_result.get("locations"):
                    pickup_location_id = str(loc_result["locations"][0]["location_id"])
                else:
                    return jsonify({"success": False, "error": f"Location not found: {pickup_location_name}", "cars": []})

            if not pickup_location_id:
                return jsonify({"success": False, "error": "Pickup location required"}), 400

            # ANASTASiA CarsNeuron dispatch (Build #185) — fallback to direct client
            _used_neuron = False
            result = None
            try:
                from anastasia.verticals.cars import CarsNeuron
                from anastasia.core.events import EventBus
                _cars_neuron = CarsNeuron()
                _cars_neuron.initialize(EventBus(), {"cars_enabled": True})
                result = _cars_neuron.search(
                    pickup_location=pickup_location_name or pickup_location_id,
                    pickup_date=pickup_date,
                    dropoff_date=dropoff_date,
                    client=client,
                )
                _used_neuron = result.get("success", False)
                if _used_neuron:
                    logger.info("[ANASTASiA] CarsNeuron handled search (%d results)", len(result.get("cars", [])))
            except Exception as _neuron_err:
                logger.debug("[ANASTASiA] CarsNeuron unavailable, using direct client: %s", _neuron_err)

            if not _used_neuron:
                result = client.search_cars(
                    pickup_location_id=pickup_location_id,
                    pickup_date=pickup_date,
                    pickup_time=pickup_time,
                    dropoff_date=dropoff_date,
                    dropoff_time=dropoff_time,
                    dropoff_location_id=dropoff_location_id if dropoff_location_id else None,
                    currency="USD",
                    driver_age=int(driver_age),
                )

            try:
                from monitoring import track_search
                track_search(origin=pickup_location_name or pickup_location_id,
                             destination=pickup_location_name or pickup_location_id,
                             market="car_rental")
            except Exception:
                pass

            if not result.get("success"):
                return jsonify({"success": False, "error": result.get("error", "No cars found"), "cars": []})

            cars = result.get("cars", [])

            # Cache full results in session for car selection
            session['car_search_results'] = {c.get("offer_id"): c for c in cars if c.get("offer_id")}

            return jsonify({
                "success": True,
                "cars": cars,
                "count": len(cars),
                "pickup_date": pickup_date,
                "dropoff_date": dropoff_date,
            })

        except Exception as e:
            logger.error("Car search error: %s", e, exc_info=True)
            return jsonify({"success": False, "error": "Car search failed. Please try again."}), 500

    @app.route("/api/cars/select", methods=["POST"])
    @csrf.exempt
    def api_car_select():
        """Create a Deal record from a selected car rental offer for checkout."""
        if not is_feature_enabled("vertical_rentals"):
            return jsonify({"success": False, "error": "Car rental booking is not available yet"}), 410
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "No data provided"}), 400

        offer_id = data.get("offer_id")
        if not offer_id:
            return jsonify({"success": False, "error": "Offer ID required"}), 400

        try:
            cached = session.get('car_search_results', {})
            car_data = cached.get(offer_id)

            if not car_data:
                return jsonify({"success": False, "error": "Offer expired. Please search again."}), 400

            deal_id = secrets.token_hex(8)
            destination_tag = abs(hash(deal_id)) % 2147483647

            # Pricing
            price_total = float(car_data.get("price_total", 0))
            price_per_day = float(car_data.get("price_per_day", 0))
            vehicle_name = car_data.get("vehicle_name", "Unknown Car")
            pickup_location = car_data.get("pickup_location", "")
            pickup_date_str = car_data.get("pickup_date")
            dropoff_date_str = car_data.get("dropoff_date")

            # Calculate rental days
            rental_days = 1
            if pickup_date_str and dropoff_date_str:
                try:
                    d1 = datetime.strptime(pickup_date_str, "%Y-%m-%d")
                    d2 = datetime.strptime(dropoff_date_str, "%Y-%m-%d")
                    rental_days = max(1, (d2 - d1).days)
                except ValueError:
                    rental_days = 1

            # Platform fee — use standard fee calculation
            try:
                from payments import get_fee_percent
                fee_pct = get_fee_percent(current_user)
            except Exception:
                fee_pct = 0.50  # Default consumer rate (50%)
            platform_fee = max(3.0, price_total * fee_pct)

            deal = Deal(
                deal_id=deal_id,
                deal_type="car_rental",
                hotel_name=vehicle_name,
                hotel_id=offer_id,
                hotel_offer_id=offer_id,
                city_code=pickup_location,
                check_in_date=datetime.strptime(pickup_date_str, "%Y-%m-%d").date() if pickup_date_str else None,
                check_out_date=datetime.strptime(dropoff_date_str, "%Y-%m-%d").date() if dropoff_date_str else None,
                nights=rental_days,
                price_per_night_usd=price_per_day,
                price_total_usd=price_total,
                home_price_usd=price_total,
                arbitrage_price_usd=price_total,
                platform_fee_usd=platform_fee,
                user_savings_usd=0,
                gross_savings_usd=0,
                savings_percent=0,
                destination_tag=destination_tag,
                amadeus_offer_data=json.dumps(car_data),
                is_active=True,
                expires_at=datetime.utcnow() + timedelta(hours=2),
                created_at=datetime.utcnow(),
            )

            db.session.add(deal)
            db.session.commit()

            return jsonify({
                "success": True,
                "deal_id": deal_id,
                "vehicle_name": vehicle_name,
                "total_price": round(price_total + platform_fee, 2),
                "redirect_url": f"/save-deal/{deal_id}",
            })

        except Exception as e:
            logger.error("Car select error: %s", e, exc_info=True)
            return jsonify({"success": False, "error": "Car selection failed. Please try again."}), 500
